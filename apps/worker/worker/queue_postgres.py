"""PostgreSQL job queue implementation using SELECT ... FOR UPDATE SKIP LOCKED."""

from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from worker.queue import JobQueue


class PostgresJobQueue(JobQueue):
    """PostgreSQL-based job queue using atomic SELECT ... FOR UPDATE SKIP LOCKED."""

    def __init__(self, engine: Engine, max_attempts: int = 3) -> None:
        """
        Initialize the PostgreSQL queue.

        Args:
            engine: SQLAlchemy engine for the database.
            max_attempts: Maximum number of attempts before a job is marked failed.
        """
        self._engine = engine
        self._max_attempts = max_attempts

    def enqueue(
        self,
        queue: str,
        payload: dict[str, Any],
        *,
        run_after: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Enqueue a job with optional idempotency key."""
        from uuid import uuid4

        now = datetime.now(timezone.utc)
        run_after = run_after or now
        job_id = str(uuid4())

        with self._engine.begin() as conn:
            # Check idempotency
            if idempotency_key:
                result = conn.execute(
                    sa.text(
                        """
                        SELECT id FROM job_queue
                        WHERE queue = :queue AND idempotency_key = :idempotency_key
                        LIMIT 1
                        """
                    ),
                    {"queue": queue, "idempotency_key": idempotency_key},
                )
                row = result.fetchone()
                if row:
                    return str(row[0])

            # Insert new job
            conn.execute(
                sa.text(
                    """
                    INSERT INTO job_queue
                    (id, queue, payload, status, attempts, max_attempts, run_after,
                     idempotency_key, created_at, updated_at)
                    VALUES (:id, :queue, :payload, :status, :attempts, :max_attempts,
                            :run_after, :idempotency_key, :created_at, :updated_at)
                    """
                ),
                {
                    "id": job_id,
                    "queue": queue,
                    "payload": payload,
                    "status": "queued",
                    "attempts": 0,
                    "max_attempts": self._max_attempts,
                    "run_after": run_after,
                    "idempotency_key": idempotency_key,
                    "created_at": now,
                    "updated_at": now,
                },
            )

        return job_id

    def claim(self, queue: str, worker_id: str) -> Any:
        """Claim the next available job from the queue (atomic)."""
        from worker.queue import Job

        now = datetime.now(timezone.utc)

        with self._engine.begin() as conn:
            # Atomic claim: SELECT ... FOR UPDATE SKIP LOCKED
            result = conn.execute(
                sa.text(
                    """
                    SELECT id, queue, payload, attempts, status
                    FROM job_queue
                    WHERE queue = :queue
                      AND status = 'queued'
                      AND run_after <= :now
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"queue": queue, "now": now},
            )
            row = result.fetchone()

            if not row:
                return None

            job_id = row[0]

            # Update the job to running state
            conn.execute(
                sa.text(
                    """
                    UPDATE job_queue
                    SET status = 'running',
                        locked_by = :worker_id,
                        locked_at = :now,
                        attempts = attempts + 1,
                        updated_at = :now
                    WHERE id = :id
                    """
                ),
                {"id": job_id, "worker_id": worker_id, "now": now},
            )

            # Fetch the updated job
            result = conn.execute(
                sa.text(
                    """
                    SELECT id, queue, payload, attempts, status
                    FROM job_queue
                    WHERE id = :id
                    """
                ),
                {"id": job_id},
            )
            row = result.fetchone()

            if not row:
                return None

            import json

            return Job(
                id=row[0],
                queue=row[1],
                payload=json.loads(row[2]) if isinstance(row[2], str) else row[2],
                attempts=row[3],
                status=row[4],
            )

    def complete(self, job_id: str) -> None:
        """Mark a job as completed."""
        now = datetime.now(timezone.utc)

        with self._engine.begin() as conn:
            conn.execute(
                sa.text(
                    """
                    UPDATE job_queue
                    SET status = 'done',
                        locked_by = NULL,
                        locked_at = NULL,
                        updated_at = :now
                    WHERE id = :id
                    """
                ),
                {"id": job_id, "now": now},
            )

    def fail(self, job_id: str, error: str, *, retry_in_seconds: int | None = None) -> None:
        """Mark a job as failed, optionally retrying."""
        now = datetime.now(timezone.utc)

        # Truncate error to 500 chars, excluding payload references
        truncated_error = error[:500]

        with self._engine.begin() as conn:
            # Get current job state
            result = conn.execute(
                sa.text(
                    """
                    SELECT attempts, max_attempts
                    FROM job_queue
                    WHERE id = :id
                    """
                ),
                {"id": job_id},
            )
            row = result.fetchone()
            if not row:
                return

            attempts, max_attempts = row

            # Determine next action
            should_retry = retry_in_seconds is not None and attempts < max_attempts

            if should_retry:
                from datetime import timedelta

                assert retry_in_seconds is not None
                run_after = now + timedelta(seconds=retry_in_seconds)
                conn.execute(
                    sa.text(
                        """
                        UPDATE job_queue
                        SET status = 'queued',
                            last_error = :error,
                            locked_by = NULL,
                            locked_at = NULL,
                            run_after = :run_after,
                            updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": job_id,
                        "error": truncated_error,
                        "run_after": run_after,
                        "now": now,
                    },
                )
            else:
                conn.execute(
                    sa.text(
                        """
                        UPDATE job_queue
                        SET status = 'failed',
                            last_error = :error,
                            locked_by = NULL,
                            locked_at = NULL,
                            updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {"id": job_id, "error": truncated_error, "now": now},
                )

    def requeue_stale(self, older_than_seconds: int) -> int:
        """Requeue jobs stuck in 'running' beyond the timeout."""
        now = datetime.now(timezone.utc)

        with self._engine.begin() as conn:
            from datetime import timedelta

            cutoff = now - timedelta(seconds=older_than_seconds)

            result = conn.execute(
                sa.text(
                    """
                    UPDATE job_queue
                    SET status = 'queued',
                        locked_by = NULL,
                        locked_at = NULL,
                        updated_at = :now
                    WHERE status = 'running'
                      AND locked_at <= :cutoff
                      AND attempts < max_attempts
                    RETURNING id
                    """
                ),
                {"cutoff": cutoff, "now": now},
            )

            return len(result.fetchall())
