"""Entry point for the worker CLI."""

import logging
import signal
import threading
from collections.abc import Callable
from typing import Any

from sqlalchemy import create_engine

from worker.queue import Job
from worker.queue_postgres import PostgresJobQueue
from worker.runner import Runner
from worker.settings import get_settings


def noop_handler(job: Job) -> None:
    """No-op handler for smoke testing."""
    pass


def echo_handler(job: Job) -> None:
    """Echo handler: logs the job payload."""
    logging.info(f"Echo handler: {job.payload}")


def main() -> None:
    """Start the worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    settings = get_settings()
    db_url = settings.get_database_url()

    # Create database engine
    engine = create_engine(db_url, echo=False)

    # Create job queue and runner
    queue = PostgresJobQueue(engine)

    handlers: dict[str, Callable[[Job], None]] = {
        "noop": noop_handler,
        "echo": echo_handler,
    }

    runner = Runner(
        queue=queue,
        handlers=handlers,
        worker_id="default",
        poll_interval_seconds=settings.poll_interval_seconds,
    )

    # Setup signal handling for graceful shutdown
    stop_event = threading.Event()

    def signal_handler(signum: int, frame: Any) -> None:
        logging.info(f"Received signal {signum}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        logging.info("Starting worker...")
        runner.run_forever(stop_event)
    finally:
        logging.info("Worker stopped")
        engine.dispose()


if __name__ == "__main__":
    main()
