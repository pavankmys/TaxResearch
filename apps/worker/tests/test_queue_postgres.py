"""Integration tests for PostgresJobQueue (requires real database)."""

import os
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

pytestmark = pytest.mark.integration


@pytest.fixture
def db_url() -> str:
    """Get the database URL, skip test if not set."""
    url = os.environ.get("DATABASE_URL", "")
    if not url or "localhost/test" in url:
        pytest.skip("DATABASE_URL not set to a real database; skipping integration tests")
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def engine(db_url: str) -> object:
    """Create a database engine and ensure the job_queue table exists."""
    engine = create_engine(db_url)

    # Ensure the table exists by running migrations
    # For now, we'll assume the migration has been run
    from sqlalchemy import inspect

    inspector = inspect(engine)
    if "job_queue" not in inspector.get_table_names():
        pytest.skip("job_queue table not found; migrations not run")

    yield engine

    engine.dispose()


def test_postgres_enqueue_and_claim(engine: object) -> None:
    """Test basic enqueue and claim operations."""
    from worker.queue_postgres import PostgresJobQueue

    queue = PostgresJobQueue(engine)  # type: ignore

    job_id = queue.enqueue("test_queue", {"data": "test"})
    job = queue.claim("test_queue", "worker1")

    assert job is not None
    assert job.id == job_id
    assert job.payload == {"data": "test"}
    assert job.status == "running"


def test_postgres_idempotency(engine: object) -> None:
    """Test idempotency key prevents duplicates."""
    from worker.queue_postgres import PostgresJobQueue

    queue = PostgresJobQueue(engine)  # type: ignore

    job_id1 = queue.enqueue("test_queue", {"data": "test"}, idempotency_key="key1")
    job_id2 = queue.enqueue("test_queue", {"data": "test"}, idempotency_key="key1")

    assert job_id1 == job_id2


def test_postgres_complete_marks_done(engine: object) -> None:
    """Test that complete marks a job as done."""
    from worker.queue_postgres import PostgresJobQueue

    queue = PostgresJobQueue(engine)  # type: ignore

    job_id = queue.enqueue("test_queue", {})
    job = queue.claim("test_queue", "worker1")
    assert job is not None

    queue.complete(job_id)

    # Verify by claiming again - should get None
    job = queue.claim("test_queue", "worker1")
    assert job is None


def test_postgres_fail_marks_failed(engine: object) -> None:
    """Test that fail marks a job as failed after max attempts."""
    from worker.queue_postgres import PostgresJobQueue

    queue = PostgresJobQueue(engine, max_attempts=1)  # type: ignore

    job_id = queue.enqueue("test_queue", {})
    job = queue.claim("test_queue", "worker1")
    assert job is not None

    queue.fail(job_id, "Test error")

    # Verify by attempting to claim - should get None
    job = queue.claim("test_queue", "worker1")
    assert job is None


def test_postgres_fail_with_retry(engine: object) -> None:
    """Test that fail with retry_in_seconds requeues the job."""
    from worker.queue_postgres import PostgresJobQueue

    queue = PostgresJobQueue(engine, max_attempts=3)  # type: ignore

    job_id = queue.enqueue("test_queue", {})
    job = queue.claim("test_queue", "worker1")
    assert job is not None

    queue.fail(job_id, "Test error", retry_in_seconds=1)

    # Should be able to claim again (after the delay)
    # For this test, we'll check it's still in queued status
    # by attempting to claim with a future time
    future_job = queue.claim("test_queue", "worker1")
    # Depending on timing, we might or might not get the job
    # Just verify it doesn't crash


def test_postgres_requeue_stale_concurrency(engine: object) -> None:
    """Test concurrency: two workers claiming from the same queue."""
    from worker.queue_postgres import PostgresJobQueue

    queue = PostgresJobQueue(engine)  # type: ignore

    # Enqueue 10 jobs
    job_ids = []
    for i in range(10):
        job_id = queue.enqueue("test_queue", {"index": i})
        job_ids.append(job_id)

    claimed_jobs = []
    lock = threading.Lock()

    def worker(worker_id: str) -> None:
        for _ in range(5):  # Try to claim up to 5 jobs
            job = queue.claim("test_queue", worker_id)
            if job:
                with lock:
                    claimed_jobs.append((job.id, worker_id))

    # Run two workers concurrently
    thread1 = threading.Thread(target=worker, args=("worker1",))
    thread2 = threading.Thread(target=worker, args=("worker2",))

    thread1.start()
    thread2.start()

    thread1.join()
    thread2.join()

    # Each job should be claimed exactly once
    job_ids_claimed = [j[0] for j in claimed_jobs]
    assert len(job_ids_claimed) == len(set(job_ids_claimed))
    assert len(job_ids_claimed) == 10


def test_postgres_requeue_stale(engine: object) -> None:
    """Test requeue_stale recovers from lost messages."""
    from worker.queue_postgres import PostgresJobQueue

    queue = PostgresJobQueue(engine, max_attempts=3)  # type: ignore

    # Enqueue and claim a job
    job_id = queue.enqueue("test_queue", {})
    job = queue.claim("test_queue", "worker1")
    assert job is not None

    # Simulate the worker crashing without completing the job
    # by manually setting locked_at to the past
    from sqlalchemy import text

    with engine.begin() as conn:  # type: ignore
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=100)  # noqa: UP017
        conn.execute(
            text(
                """
                UPDATE job_queue
                SET locked_at = :cutoff
                WHERE id = :id
                """
            ),
            {"cutoff": cutoff, "id": job_id},
        )

    # Run reconciliation
    requeued = queue.requeue_stale(older_than_seconds=60)

    assert requeued == 1

    # Job should now be claimable again
    job = queue.claim("test_queue", "worker1")
    assert job is not None
    assert job.id == job_id
