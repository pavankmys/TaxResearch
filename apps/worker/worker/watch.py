"""Watch folder: loads files dropped into ``<root>/<source_code>/<doc_type>/``.

A file is loaded once its size and modification time have been the same for ``stable_scans``
consecutive scans. It is then moved to ``<root>/.done/<yyyymmdd>/<uuid>__<name>`` before the
load is submitted, so the worker reads a file that no longer changes. A file that fails
validation, or whose submit fails, goes to ``<root>/.failed/<name>`` with ``<name>.reason.txt``.
"""

import logging
import os
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.engine import Connection, Engine

from worker.ingest import loaders
from worker.ingest.loaders import LoadError, LoadRequest

logger = logging.getLogger(__name__)

SubmitFn = Callable[[Connection, LoadRequest], UUID]


@dataclass(frozen=True)
class _Seen:
    signature: tuple[int, int]  # (size, mtime_ns)
    scans: int  # consecutive scans with this signature


class WatchFolder:
    """Scans the watch root and submits stable files as loads."""

    def __init__(
        self,
        root: Path,
        engine: Engine,
        stable_scans: int = 2,
        *,
        submit: SubmitFn = loaders.submit,
    ) -> None:
        """
        Args:
            root: The watch folder (the container path is /watch).
            engine: Sync engine; each load runs in one transaction.
            stable_scans: Consecutive unchanged scans required before a file is loaded.
            submit: Function that creates the job. Tests inject a fake.
        """
        if stable_scans < 1:
            raise ValueError("stable_scans must be at least 1")
        self._root = root
        self._engine = engine
        self._stable_scans = stable_scans
        self._submit = submit
        self._seen: dict[Path, _Seen] = {}

    def scan_once(self) -> list[UUID]:
        """Run one scan. Returns the ingestion job ids submitted during this scan."""
        if not self._root.is_dir():
            return []
        seen: dict[Path, _Seen] = {}
        submitted: list[UUID] = []
        for path in self._candidates():
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            signature = (stat.st_size, stat.st_mtime_ns)
            previous = self._seen.get(path)
            if previous is not None and previous.signature == signature:
                scans = previous.scans + 1
            else:
                scans = 1
            if scans < self._stable_scans:
                seen[path] = _Seen(signature, scans)
                continue
            job_id = self._load(path)
            if job_id is not None:
                submitted.append(job_id)
        self._seen = seen
        return submitted

    def _candidates(self) -> Iterator[Path]:
        for source_dir in sorted(self._root.iterdir()):
            if not source_dir.is_dir() or source_dir.name.startswith("."):
                continue
            for type_dir in sorted(source_dir.iterdir()):
                if not type_dir.is_dir() or type_dir.name.startswith("."):
                    continue
                for path in sorted(type_dir.iterdir()):
                    if path.is_file() and not path.name.startswith("."):
                        yield path

    def _load(self, path: Path) -> UUID | None:
        relative = path.relative_to(self._root)
        source_code, doc_type = relative.parts[0], relative.parts[1]
        request = LoadRequest(source_code=source_code, doc_type=doc_type, file_path=str(path))
        try:
            loaders.validate_request(request)
        except LoadError as exc:
            self._move_to_failed(path, str(exc))
            return None

        day = datetime.now(UTC).strftime("%Y%m%d")
        done = self._root / ".done" / day / f"{uuid.uuid4()}__{path.name}"
        done.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(path, done)
        except FileNotFoundError:
            return None

        request = replace(request, file_path=str(done))
        try:
            with self._engine.begin() as conn:
                job_id = self._submit(conn, request)
        except Exception as exc:
            self._move_to_failed(done, str(exc) or type(exc).__name__)
            return None
        logger.info(f"Watch folder: {path.name} loaded as ingestion job {job_id}")
        return job_id

    def _move_to_failed(self, path: Path, reason: str) -> None:
        failed_dir = self._root / ".failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        target = failed_dir / path.name
        if target.exists():
            target = failed_dir / f"{uuid.uuid4()}__{path.name}"
        os.replace(path, target)
        target.with_name(target.name + ".reason.txt").write_text(
            reason[:2000] + "\n", encoding="utf-8"
        )
        logger.warning(f"Watch folder: {path.name} moved to .failed: {reason}")


def run_watch_loop(watch: WatchFolder, stop_event: threading.Event, interval: float) -> None:
    """Scan every ``interval`` seconds until stop_event is set."""
    while not stop_event.is_set():
        try:
            watch.scan_once()
        except Exception:
            logger.exception("Watch folder scan failed")
        stop_event.wait(timeout=interval)
