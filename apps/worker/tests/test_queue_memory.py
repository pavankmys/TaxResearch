"""Tests for InMemoryJobQueue."""

from datetime import datetime, timedelta, timezone

from worker.queue_memory import InMemoryJobQueue


def test_enqueue_creates_job() -> None:
    """Test that enqueue creates a job with correct fields."""
    queue = InMemoryJobQueue()
    payload = {"url": "https://example.com"}

    job_id = queue.enqueue("fetch", payload)

    assert isinstance(job_id, str)
    assert len(job_id) == 36  # UUID length


def test_enqueue_idempotency() -> None:
    """Test that idempotency key prevents duplicate jobs."""
    queue = InMemoryJobQueue()
    payload = {"url": "https://example.com"}
    idem_key = "example-key"

    job_id1 = queue.enqueue("fetch", payload, idempotency_key=idem_key)
    job_id2 = queue.enqueue("fetch", payload, idempotency_key=idem_key)

    assert job_id1 == job_id2


def test_claim_returns_job() -> None:
    """Test that claim returns a job and updates its status."""
    queue = InMemoryJobQueue()
    payload = {"url": "https://example.com"}

    job_id = queue.enqueue("fetch", payload)
    job = queue.claim("fetch", "worker1")

    assert job is not None
    assert job.id == job_id
    assert job.queue == "fetch"
    assert job.payload == payload
    assert job.status == "running"
    assert job.attempts == 1


def test_claim_returns_none_when_no_jobs() -> None:
    """Test that claim returns None when no jobs are available."""
    queue = InMemoryJobQueue()

    job = queue.claim("fetch", "worker1")

    assert job is None


def test_claim_respects_run_after() -> None:
    """Test that claim does not return jobs before run_after time."""
    queue = InMemoryJobQueue()
    future = datetime.now(timezone.utc) + timedelta(hours=1)  # noqa: UP017
    payload = {"url": "https://example.com"}

    queue.enqueue("fetch", payload, run_after=future)
    job = queue.claim("fetch", "worker1")

    assert job is None


def test_complete_marks_job_done() -> None:
    """Test that complete marks a job as done."""
    queue = InMemoryJobQueue()
    payload = {"url": "https://example.com"}

    job_id = queue.enqueue("fetch", payload)
    job = queue.claim("fetch", "worker1")
    assert job is not None

    queue.complete(job_id)

    # Verify by checking internal state (for testing purposes)
    # In production, we'd query the database
    assert queue._jobs[job_id]["status"] == "done"


def test_fail_moves_to_failed() -> None:
    """Test that fail moves a job to failed status after max attempts."""
    queue = InMemoryJobQueue(max_attempts=1)
    payload = {"url": "https://example.com"}

    job_id = queue.enqueue("fetch", payload)
    queue.claim("fetch", "worker1")

    queue.fail(job_id, "Download failed")

    assert queue._jobs[job_id]["status"] == "failed"
    assert queue._jobs[job_id]["last_error"] == "Download failed"


def test_fail_with_retry() -> None:
    """Test that fail with retry_in_seconds requeues the job."""
    queue = InMemoryJobQueue(max_attempts=3)
    payload = {"url": "https://example.com"}

    job_id = queue.enqueue("fetch", payload)
    queue.claim("fetch", "worker1")

    queue.fail(job_id, "Download failed", retry_in_seconds=60)

    assert queue._jobs[job_id]["status"] == "queued"
    assert queue._jobs[job_id]["attempts"] == 1


def test_fail_truncates_error_to_500_chars() -> None:
    """Test that fail truncates error messages to 500 chars."""
    queue = InMemoryJobQueue(max_attempts=1)
    payload = {"url": "https://example.com"}

    job_id = queue.enqueue("fetch", payload)
    queue.claim("fetch", "worker1")

    long_error = "x" * 1000
    queue.fail(job_id, long_error)

    assert len(queue._jobs[job_id]["last_error"]) == 500


def test_requeue_stale_moves_running_jobs_back_to_queued() -> None:
    """Test that requeue_stale moves stale running jobs back to queued."""
    queue = InMemoryJobQueue(max_attempts=3)
    payload = {"url": "https://example.com"}

    job_id = queue.enqueue("fetch", payload)
    job = queue.claim("fetch", "worker1")
    assert job is not None

    # Manually age the job
    queue._jobs[job_id]["locked_at"] = datetime.now(timezone.utc) - timedelta(  # noqa: UP017
        seconds=100
    )

    requeued = queue.requeue_stale(older_than_seconds=60)

    assert requeued == 1
    assert queue._jobs[job_id]["status"] == "queued"
    assert queue._jobs[job_id]["locked_by"] is None


def test_requeue_stale_respects_max_attempts() -> None:
    """Test that requeue_stale does not requeue jobs at max attempts."""
    queue = InMemoryJobQueue(max_attempts=1)
    payload = {"url": "https://example.com"}

    job_id = queue.enqueue("fetch", payload)
    job = queue.claim("fetch", "worker1")
    assert job is not None

    # Manually age the job and set it to max attempts
    queue._jobs[job_id]["locked_at"] = datetime.now(timezone.utc) - timedelta(  # noqa: UP017
        seconds=100
    )
    queue._jobs[job_id]["attempts"] = 1

    requeued = queue.requeue_stale(older_than_seconds=60)

    assert requeued == 0
    assert queue._jobs[job_id]["status"] == "running"


def test_claim_fifo_order() -> None:
    """Test that claim returns jobs in FIFO order."""
    queue = InMemoryJobQueue()

    job_id1 = queue.enqueue("fetch", {"url": "1"})
    job_id2 = queue.enqueue("fetch", {"url": "2"})
    job_id3 = queue.enqueue("fetch", {"url": "3"})

    job1 = queue.claim("fetch", "worker1")
    assert job1 is not None and job1.id == job_id1

    job2 = queue.claim("fetch", "worker1")
    assert job2 is not None and job2.id == job_id2

    job3 = queue.claim("fetch", "worker1")
    assert job3 is not None and job3.id == job_id3


def test_multiple_queues() -> None:
    """Test that queue names are isolated."""
    queue = InMemoryJobQueue()

    job_id1 = queue.enqueue("fetch", {"url": "1"})
    job_id2 = queue.enqueue("parse", {"file": "1"})

    job1 = queue.claim("fetch", "worker1")
    assert job1 is not None and job1.id == job_id1

    job2 = queue.claim("parse", "worker1")
    assert job2 is not None and job2.id == job_id2

    # fetch and parse queues should be empty now
    assert queue.claim("fetch", "worker1") is None
    assert queue.claim("parse", "worker1") is None
