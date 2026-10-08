"""In-memory job queue implementation for testing and local development."""

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from worker.queue import Job, JobQueue


class InMemoryJobQueue(JobQueue):
    """Thread-safe in-memory job queue implementation."""

    def __init__(self, max_attempts: int = 3) -> None:
        """
        Initialize the in-memory queue.

        Args:
            max_attempts: Maximum number of attempts before a job is marked failed.
        """
        self._jobs: dict[str, dict[str, Any]] = {}
        self._idempotency_keys: dict[tuple[str, str], str] = {}  # (queue, key) -> job_id
        self._lock = threading.RLock()
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        """Attempts allowed before a job is marked failed for good."""
        return self._max_attempts

    def enqueue(
        self,
        queue: str,
        payload: dict[str, Any],
        *,
        run_after: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Enqueue a job with optional idempotency key."""
        with self._lock:
            # Check idempotency
            if idempotency_key:
                key = (queue, idempotency_key)
                if key in self._idempotency_keys:
                    return self._idempotency_keys[key]

            job_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            run_after = run_after or now

            self._jobs[job_id] = {
                "id": job_id,
                "queue": queue,
                "payload": payload,
                "attempts": 0,
                "status": "queued",
                "run_after": run_after,
                "locked_by": None,
                "locked_at": None,
                "last_error": None,
                "idempotency_key": idempotency_key,
                "created_at": now,
                "updated_at": now,
            }

            if idempotency_key:
                self._idempotency_keys[(queue, idempotency_key)] = job_id

            return job_id

    def claim(self, queue: str, worker_id: str) -> Job | None:
        """Claim the next available job from the queue (atomic)."""
        with self._lock:
            now = datetime.now(timezone.utc)

            # Find the first available job in this queue
            for _job_id, job_data in self._jobs.items():
                if (
                    job_data["queue"] == queue
                    and job_data["status"] == "queued"
                    and job_data["run_after"] <= now
                ):
                    # Claim this job
                    job_data["status"] = "running"
                    job_data["locked_by"] = worker_id
                    job_data["locked_at"] = now
                    job_data["updated_at"] = now
                    job_data["attempts"] += 1

                    return Job(
                        id=job_data["id"],
                        queue=job_data["queue"],
                        payload=job_data["payload"],
                        attempts=job_data["attempts"],
                        status=job_data["status"],
                    )

            return None

    def complete(self, job_id: str) -> None:
        """Mark a job as completed."""
        with self._lock:
            if job_id in self._jobs:
                job_data = self._jobs[job_id]
                job_data["status"] = "done"
                job_data["locked_by"] = None
                job_data["locked_at"] = None
                job_data["updated_at"] = datetime.now(timezone.utc)

    def fail(self, job_id: str, error: str, *, retry_in_seconds: int | None = None) -> None:
        """Mark a job as failed, optionally retrying."""
        with self._lock:
            if job_id not in self._jobs:
                return

            job_data = self._jobs[job_id]
            now = datetime.now(timezone.utc)

            # Truncate error to 500 chars, excluding payload references
            truncated_error = error[:500]
            job_data["last_error"] = truncated_error
            job_data["locked_by"] = None
            job_data["locked_at"] = None
            job_data["updated_at"] = now

            # Check if we should retry
            if retry_in_seconds is not None and job_data["attempts"] < self._max_attempts:
                # Calculate retry time
                from datetime import timedelta

                job_data["status"] = "queued"
                job_data["run_after"] = now + timedelta(seconds=retry_in_seconds)
            else:
                # Move to failed status
                job_data["status"] = "failed"

    def requeue_stale(self, older_than_seconds: int) -> int:
        """Requeue jobs stuck in 'running' beyond the timeout."""
        with self._lock:
            now = datetime.now(timezone.utc)
            requeued = 0

            for job_data in self._jobs.values():
                if job_data["status"] == "running" and job_data["locked_at"] is not None:
                    age = (now - job_data["locked_at"]).total_seconds()
                    if age > older_than_seconds:
                        # Requeue only if not at max attempts
                        if job_data["attempts"] < self._max_attempts:
                            job_data["status"] = "queued"
                            job_data["locked_by"] = None
                            job_data["locked_at"] = None
                            job_data["updated_at"] = now
                            requeued += 1

            return requeued
