"""Entry point for the worker: runs the job loop and the watch folder."""

import importlib
import logging
import signal
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from worker.config import load_ingestion_config
from worker.ingest.acquire import make_acquire_handler
from worker.ingest.apply_metadata import make_apply_metadata_handler
from worker.ingest.build_provisions import make_build_provisions_handler
from worker.ingest.classify import make_classify_handler
from worker.ingest.detect_amendments import make_amend_detect_handler
from worker.ingest.extract_meta import make_extract_meta_handler
from worker.ingest.publish import make_publish_handler
from worker.ingest.queues import (
    AMEND_DETECT_QUEUE,
    APPLY_METADATA_QUEUE,
    BUILD_PROVISIONS_QUEUE,
    CLASSIFY_QUEUE,
    EXTRACT_META_QUEUE,
    PUBLISH_QUEUE,
    SEGMENT_QUEUE,
)
from worker.ingest.segment import make_segment_handler
from worker.objectstore import ObjectStore, make_object_store
from worker.queue import Job
from worker.queue_postgres import PostgresJobQueue
from worker.runner import Runner
from worker.settings import get_settings
from worker.watch import WatchFolder, run_watch_loop

logger = logging.getLogger(__name__)


def noop_handler(job: Job) -> None:
    """No-op handler for smoke testing."""
    pass


def echo_handler(job: Job) -> None:
    """Echo handler: logs the job payload."""
    logging.info(f"Echo handler: {job.payload}")


def _parse_handler(engine: Engine, store: ObjectStore) -> Callable[[Job], None] | None:
    """Build the ingest.parse handler if the parse stage is present.

    The parse stage is a later task, so this import is guarded. The module must provide
    make_parse_handler(engine, store).
    """
    try:
        module = importlib.import_module("worker.ingest.parse")
    except ImportError as exc:
        logger.info(f"ingest.parse not registered: {exc}")
        return None
    factory: Any = getattr(module, "make_parse_handler", None)
    if factory is None:
        logger.info("ingest.parse not registered: make_parse_handler is missing")
        return None
    return cast(Callable[[Job], None], factory(engine, store))


def main() -> None:
    """Start the worker."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    db_url = settings.get_database_url()

    # Create database engine
    engine = create_engine(db_url, echo=False)
    store = make_object_store(settings)

    # Create job queue and runner
    queue = PostgresJobQueue(engine)

    handlers: dict[str, Callable[[Job], None]] = {
        "noop": noop_handler,
        "echo": echo_handler,
        "ingest.acquire": make_acquire_handler(engine, store),
    }
    parse_handler = _parse_handler(engine, store)
    if parse_handler is not None:
        handlers["ingest.parse"] = parse_handler
    handlers[CLASSIFY_QUEUE] = make_classify_handler(engine, store)
    handlers[SEGMENT_QUEUE] = make_segment_handler(engine, store)
    handlers[EXTRACT_META_QUEUE] = make_extract_meta_handler(engine, store)
    handlers[APPLY_METADATA_QUEUE] = make_apply_metadata_handler(engine, store)
    handlers[PUBLISH_QUEUE] = make_publish_handler(engine, store)
    handlers[BUILD_PROVISIONS_QUEUE] = make_build_provisions_handler(engine, store)
    handlers[AMEND_DETECT_QUEUE] = make_amend_detect_handler(engine, store)

    runner = Runner(
        queue=queue,
        handlers=handlers,
        worker_id="default",
        poll_interval_seconds=settings.poll_interval_seconds,
        retry_base_seconds=settings.retry_base_seconds,
    )

    # Setup signal handling for graceful shutdown
    stop_event = threading.Event()

    def signal_handler(signum: int, frame: Any) -> None:
        logging.info(f"Received signal {signum}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    watch_thread: threading.Thread | None = None
    watch_root = Path(settings.watch_folder)
    if watch_root.is_dir():
        watch = WatchFolder(
            watch_root,
            engine,
            stable_scans=load_ingestion_config().watch.stable_scans,
        )
        watch_thread = threading.Thread(
            target=run_watch_loop,
            args=(watch, stop_event, settings.watch_poll_seconds),
            name="watch-folder",
            daemon=True,
        )
        watch_thread.start()
        logging.info(f"Watching {watch_root}")
    else:
        logging.info(f"Watch folder {watch_root} not found; watch loading is off")

    try:
        logging.info("Starting worker...")
        runner.run_forever(stop_event)
    finally:
        stop_event.set()
        if watch_thread is not None:
            watch_thread.join(timeout=10)
        logging.info("Worker stopped")
        engine.dispose()


if __name__ == "__main__":
    main()
