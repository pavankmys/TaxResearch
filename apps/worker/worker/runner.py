"""Job runner for executing tasks from the queue."""

import logging
import threading
import time
from collections.abc import Callable

from worker.errors import PermanentError
from worker.queue import Job, JobQueue

logger = logging.getLogger(__name__)


class Runner:
    """Executes jobs from a queue using registered handlers."""

    def __init__(
        self,
        queue: JobQueue,
        handlers: dict[str, Callable[[Job], None]],
        worker_id: str,
        poll_interval_seconds: float = 2.0,
        reconcile_interval_seconds: float = 600.0,
        retry_base_seconds: int = 30,
    ) -> None:
        """
        Initialize the runner.

        Args:
            queue: JobQueue instance.
            handlers: Dict mapping queue names to handler callables.
            worker_id: Identifier for this worker.
            poll_interval_seconds: Polling interval in seconds (default 2.0).
            reconcile_interval_seconds: Reconciliation interval in seconds (default
                600, i.e., 10 minutes).
            retry_base_seconds: Backoff base. The n-th failed attempt waits
                retry_base_seconds * 2**(n-1) seconds before the job runs again.
        """
        self._queue = queue
        self._handlers = handlers
        self._worker_id = worker_id
        self._poll_interval_seconds = poll_interval_seconds
        self._reconcile_interval_seconds = reconcile_interval_seconds
        self._retry_base_seconds = retry_base_seconds

    def retry_delay(self, attempts: int) -> int:
        """Seconds to wait after the given (1-based) failed attempt."""
        delay: int = self._retry_base_seconds * 2 ** (attempts - 1)
        return delay

    def run_once(self) -> bool:
        """
        Attempt to claim and execute one job from any registered queue.

        A handler that raises is retried with exponential backoff until max_attempts is
        reached; then the job is marked failed (poisoned). A PermanentError is never
        retried.

        Returns:
            True if a job was executed, False otherwise.
        """
        for queue_name in self._handlers:
            job = self._queue.claim(queue_name, self._worker_id)
            if job:
                try:
                    handler = self._handlers[queue_name]
                    handler(job)
                    self._queue.complete(job.id)
                    return True
                except Exception as e:
                    # Truncate error message to 500 chars, excluding payload
                    error_msg = (str(e) or type(e).__name__)[:500]
                    self._fail(job, error_msg, e)
                    return True

        return False

    def _fail(self, job: Job, error_msg: str, exc: Exception) -> None:
        """Requeue with backoff, or mark the job failed when it must not run again."""
        if isinstance(exc, PermanentError):
            self._queue.fail(job.id, error_msg)
            logger.error(f"Job {job.id} failed permanently: {error_msg}")
        elif job.attempts < self._queue.max_attempts:
            delay = self.retry_delay(job.attempts)
            self._queue.fail(job.id, error_msg, retry_in_seconds=delay)
            logger.warning(
                f"Job {job.id} attempt {job.attempts} failed, retrying in {delay}s: {error_msg}"
            )
        else:
            self._queue.fail(job.id, error_msg)
            logger.error(
                f"Job {job.id} poisoned after {job.attempts} attempts: {error_msg}",
                exc_info=exc,
            )

    def run_forever(self, stop_event: threading.Event) -> None:
        """
        Run the job loop continuously.

        Polls for jobs at the specified interval and periodically reconciles
        stale jobs (every 10 minutes by default).

        Args:
            stop_event: Threading event to signal shutdown.
        """
        last_reconcile = time.time()

        while not stop_event.is_set():
            try:
                # Try to run one job
                self.run_once()

                # Check if it's time to reconcile
                now = time.time()
                if now - last_reconcile >= self._reconcile_interval_seconds:
                    count = self._queue.requeue_stale(int(self._reconcile_interval_seconds))
                    if count > 0:
                        logger.info(f"Requeued {count} stale jobs")
                    last_reconcile = now

                # Poll interval
                stop_event.wait(timeout=self._poll_interval_seconds)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.exception(f"Unexpected error in run loop: {e}")
                stop_event.wait(timeout=self._poll_interval_seconds)
