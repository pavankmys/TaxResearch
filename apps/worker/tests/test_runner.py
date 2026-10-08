"""Tests for the Runner class."""

import threading
from typing import Any

from worker.queue_memory import InMemoryJobQueue
from worker.runner import Runner


def test_run_once_claims_and_executes_job() -> None:
    """Test that run_once claims a job and calls the handler."""
    queue = InMemoryJobQueue()
    executed = []

    def handler(job: Any) -> None:
        executed.append(job.id)

    job_id = queue.enqueue("test", {"key": "value"})

    runner = Runner(queue, {"test": handler}, "worker1")
    result = runner.run_once()

    assert result is True
    assert len(executed) == 1
    assert executed[0] == job_id
    # Job should be completed
    assert queue._jobs[job_id]["status"] == "done"


def test_run_once_returns_false_when_no_jobs() -> None:
    """Test that run_once returns False when no jobs are available."""
    queue = InMemoryJobQueue()

    runner = Runner(queue, {"test": lambda x: None}, "worker1")
    result = runner.run_once()

    assert result is False


def test_run_once_handles_handler_exception() -> None:
    """Test that run_once catches handler exceptions and marks job as failed."""
    queue = InMemoryJobQueue()

    def failing_handler(job: Any) -> None:
        raise ValueError("Handler error")

    job_id = queue.enqueue("test", {})

    runner = Runner(queue, {"test": failing_handler}, "worker1")
    result = runner.run_once()

    assert result is True
    assert queue._jobs[job_id]["status"] == "failed"
    assert "Handler error" in queue._jobs[job_id]["last_error"]


def test_run_once_truncates_error_message() -> None:
    """Test that run_once truncates error messages."""
    queue = InMemoryJobQueue()

    def failing_handler(job: Any) -> None:
        raise ValueError("x" * 1000)

    job_id = queue.enqueue("test", {})

    runner = Runner(queue, {"test": failing_handler}, "worker1")
    runner.run_once()

    assert len(queue._jobs[job_id]["last_error"]) == 500


def test_run_once_checks_all_queues() -> None:
    """Test that run_once tries all registered queues."""
    queue = InMemoryJobQueue()
    executed = []

    def handler1(job: Any) -> None:
        executed.append(("queue1", job.id))

    def handler2(job: Any) -> None:
        executed.append(("queue2", job.id))

    job_id1 = queue.enqueue("queue1", {})
    job_id2 = queue.enqueue("queue2", {})

    runner = Runner(queue, {"queue1": handler1, "queue2": handler2}, "worker1")

    # First run should get a job from queue1
    result = runner.run_once()
    assert result is True
    assert len(executed) == 1

    # Second run should get a job from queue2
    result = runner.run_once()
    assert result is True
    assert len(executed) == 2


def test_run_forever_loops_until_stop_event() -> None:
    """Test that run_forever loops until the stop event is set."""
    queue = InMemoryJobQueue()
    call_count = [0]

    def counting_handler(job: Any) -> None:
        call_count[0] += 1

    # Enqueue multiple jobs
    for _ in range(3):
        queue.enqueue("test", {})

    runner = Runner(queue, {"test": counting_handler}, "worker1", poll_interval_seconds=0.01)
    stop_event = threading.Event()

    # Run in a thread and stop after a short time
    def run_worker() -> None:
        runner.run_forever(stop_event)

    thread = threading.Thread(target=run_worker)
    thread.start()

    # Give it time to process some jobs
    threading.Event().wait(timeout=0.5)
    stop_event.set()
    thread.join(timeout=2)

    # Should have processed at least some jobs
    assert call_count[0] > 0


def test_run_forever_calls_reconcile_periodically() -> None:
    """Test that run_forever calls requeue_stale periodically."""
    queue = InMemoryJobQueue()
    reconcile_calls = [0]

    original_requeue_stale = queue.requeue_stale

    def tracking_requeue_stale(older_than: int) -> int:
        reconcile_calls[0] += 1
        return original_requeue_stale(older_than)

    queue.requeue_stale = tracking_requeue_stale  # type: ignore

    runner = Runner(
        queue,
        {"test": lambda x: None},
        "worker1",
        poll_interval_seconds=0.01,
        reconcile_interval_seconds=0.1,
    )
    stop_event = threading.Event()

    def run_worker() -> None:
        runner.run_forever(stop_event)

    thread = threading.Thread(target=run_worker)
    thread.start()

    # Give it time to process
    threading.Event().wait(timeout=0.3)
    stop_event.set()
    thread.join(timeout=2)

    # Should have called reconcile at least once
    assert reconcile_calls[0] > 0
