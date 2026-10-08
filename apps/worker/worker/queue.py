"""Abstract job queue interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Job:
    """Representation of a job in the queue."""

    id: str
    queue: str
    payload: dict[str, Any]
    attempts: int
    status: str  # 'queued', 'running', 'done', 'failed'


class JobQueue(ABC):
    """Abstract base class for job queue implementations."""

    @abstractmethod
    def enqueue(
        self,
        queue: str,
        payload: dict[str, Any],
        *,
        run_after: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """
        Enqueue a job.

        Args:
            queue: Queue name.
            payload: Job payload as a dictionary.
            run_after: Optional timestamp after which the job can be claimed.
            idempotency_key: Optional key for deduplication. If provided and a job
                            with the same key exists on the same queue, returns the
                            existing job ID without creating a new one.

        Returns:
            Job ID as a string.
        """
        pass

    @abstractmethod
    def claim(self, queue: str, worker_id: str) -> Job | None:
        """
        Claim the next available job from a queue (atomic operation).

        Args:
            queue: Queue name.
            worker_id: Identifier for this worker.

        Returns:
            A Job if one was available, None otherwise.
        """
        pass

    @abstractmethod
    def complete(self, job_id: str) -> None:
        """
        Mark a job as completed.

        Args:
            job_id: Job ID.
        """
        pass

    @abstractmethod
    def fail(self, job_id: str, error: str, *, retry_in_seconds: int | None = None) -> None:
        """
        Mark a job as failed.

        Args:
            job_id: Job ID.
            error: Error message.
            retry_in_seconds: Optional delay before retrying the job. If not provided
                            or if max attempts reached, the job stays in 'failed' status.
        """
        pass

    @abstractmethod
    def requeue_stale(self, older_than_seconds: int) -> int:
        """
        Requeue jobs stuck in 'running' status beyond a timeout.

        This is called by the reconciler to recover from lost messages (e.g., worker crash).
        Jobs stuck in 'running' for more than older_than_seconds are moved back to 'queued',
        preserving their attempt count. If a job has reached max_attempts, it stays 'failed'.

        Args:
            older_than_seconds: Age threshold in seconds.

        Returns:
            Number of jobs requeued.
        """
        pass
