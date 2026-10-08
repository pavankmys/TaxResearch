"""Job runner for executing tasks from the queue."""

import logging
import threading
import time
from collections.abc import Callable

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
        """
        self._queue = queue
        self._handlers = handlers
        self._worker_id = worker_id
        self._poll_interval_seconds = poll_interval_seconds
        self._reconcile_interval_seconds = reconcile_interval_seconds

    def run_once(self) -> bool:
        """
        Attempt to claim and execute one job from any registered queue.

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
                    error_msg = str(e)[:500]
                    self._queue.fail(job.id, error_msg)
                    logger.exception(f"Handler failed for job {job.id}: {error_msg}")
                    return True

        return False

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
