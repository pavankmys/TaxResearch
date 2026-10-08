"""Tests for the watch folder: stability, moves, failures (fake submit, no database)."""

import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from worker.ingest.loaders import LoadRequest
from worker.watch import WatchFolder


class FakeEngine:
    """Provides the begin() context manager the watch folder uses."""

    @contextmanager
    def begin(self) -> Any:  # noqa: ANN401
        yield object()


class FakeSubmit:
    """Records each request and returns a fresh job id."""

    def __init__(self, error: Exception | None = None) -> None:
        self.requests: list[LoadRequest] = []
        self.error = error

    def __call__(self, conn: Any, req: LoadRequest) -> uuid.UUID:  # noqa: ANN401
        if self.error is not None:
            raise self.error
        self.requests.append(req)
        return uuid.uuid4()


def _drop(root: Path, source: str, doc_type: str, name: str, data: bytes = b"%PDF-1.4 x") -> Path:
    folder = root / source / doc_type
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return path


def test_missing_root_does_nothing(tmp_path: Path) -> None:
    """A watch root that does not exist is not an error."""
    fake = FakeSubmit()
    watch = WatchFolder(tmp_path / "absent", FakeEngine(), submit=fake)  # type: ignore[arg-type]
    assert watch.scan_once() == []
    assert fake.requests == []


def test_file_is_loaded_after_two_stable_scans(tmp_path: Path) -> None:
    """The first scan only observes the file. The second loads it from the .done folder."""
    _drop(tmp_path, "cbic_gst_portal", "notification", "ct11.pdf")
    fake = FakeSubmit()
    watch = WatchFolder(tmp_path, FakeEngine(), stable_scans=2, submit=fake)  # type: ignore[arg-type]

    assert watch.scan_once() == []
    assert fake.requests == []

    jobs = watch.scan_once()
    assert len(jobs) == 1
    request = fake.requests[0]
    assert request.source_code == "cbic_gst_portal"
    assert request.doc_type == "notification"
    assert request.file_path is not None

    loaded = Path(request.file_path)
    assert loaded.parent.parent == tmp_path / ".done"
    assert loaded.name.endswith("__ct11.pdf")
    assert loaded.read_bytes() == b"%PDF-1.4 x"
    assert not (tmp_path / "cbic_gst_portal" / "notification" / "ct11.pdf").exists()


def test_changing_file_restarts_the_stability_count(tmp_path: Path) -> None:
    """A file still being written (its size changes) is not loaded."""
    path = _drop(tmp_path, "cbic_gst_portal", "notification", "growing.pdf", b"%PDF-1.4 a")
    fake = FakeSubmit()
    watch = WatchFolder(tmp_path, FakeEngine(), stable_scans=2, submit=fake)  # type: ignore[arg-type]

    assert watch.scan_once() == []
    path.write_bytes(b"%PDF-1.4 a longer body")
    assert watch.scan_once() == []
    assert fake.requests == []

    assert len(watch.scan_once()) == 1


def test_single_stable_scan_loads_at_once(tmp_path: Path) -> None:
    """With stable_scans=1 the first scan loads the file."""
    _drop(tmp_path, "cbic_gst_portal", "circular", "c.pdf")
    fake = FakeSubmit()
    watch = WatchFolder(tmp_path, FakeEngine(), stable_scans=1, submit=fake)  # type: ignore[arg-type]
    assert len(watch.scan_once()) == 1
    assert fake.requests[0].doc_type == "circular"


def test_loaded_file_is_not_loaded_again(tmp_path: Path) -> None:
    """Files under .done and .failed, and hidden files, are never picked up again."""
    _drop(tmp_path, "cbic_gst_portal", "notification", "once.pdf")
    _drop(tmp_path, "cbic_gst_portal", "notification", ".hidden.pdf")
    fake = FakeSubmit()
    watch = WatchFolder(tmp_path, FakeEngine(), stable_scans=1, submit=fake)  # type: ignore[arg-type]
    assert len(watch.scan_once()) == 1
    assert watch.scan_once() == []
    assert len(fake.requests) == 1


def test_unknown_source_goes_to_failed_with_reason(tmp_path: Path) -> None:
    """An invalid source is moved to .failed with a reason file, and never submitted."""
    _drop(tmp_path, "not_a_source", "notification", "bad.pdf")
    fake = FakeSubmit()
    watch = WatchFolder(tmp_path, FakeEngine(), stable_scans=1, submit=fake)  # type: ignore[arg-type]

    assert watch.scan_once() == []
    assert fake.requests == []
    failed = tmp_path / ".failed"
    assert (failed / "bad.pdf").is_file()
    reason = (failed / "bad.pdf.reason.txt").read_text(encoding="utf-8")
    assert "unknown source" in reason


def test_unknown_doc_type_goes_to_failed(tmp_path: Path) -> None:
    """An invalid doc_type folder is moved to .failed."""
    _drop(tmp_path, "cbic_gst_portal", "poem", "bad.pdf")
    fake = FakeSubmit()
    watch = WatchFolder(tmp_path, FakeEngine(), stable_scans=1, submit=fake)  # type: ignore[arg-type]
    watch.scan_once()
    assert fake.requests == []
    assert "unknown doc_type" in (tmp_path / ".failed" / "bad.pdf.reason.txt").read_text(
        encoding="utf-8"
    )


def test_submit_error_moves_the_file_to_failed(tmp_path: Path) -> None:
    """If the submit fails, the moved file is put in .failed with the error as the reason."""
    _drop(tmp_path, "cbic_gst_portal", "notification", "db.pdf")
    watch = WatchFolder(
        tmp_path,
        FakeEngine(),  # type: ignore[arg-type]
        stable_scans=1,
        submit=FakeSubmit(error=RuntimeError("database is down")),
    )
    assert watch.scan_once() == []
    failed = tmp_path / ".failed"
    names = [p.name for p in failed.iterdir() if not p.name.endswith(".reason.txt")]
    assert len(names) == 1 and names[0].endswith("__db.pdf")
    reason_file = failed / f"{names[0]}.reason.txt"
    assert "database is down" in reason_file.read_text(encoding="utf-8")


def test_files_below_the_type_folder_are_ignored(tmp_path: Path) -> None:
    """Only <root>/<source>/<doc_type>/<file> is a candidate."""
    (tmp_path / "cbic_gst_portal").mkdir()
    (tmp_path / "cbic_gst_portal" / "loose.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "root_loose.pdf").write_bytes(b"%PDF-1.4")
    fake = FakeSubmit()
    watch = WatchFolder(tmp_path, FakeEngine(), stable_scans=1, submit=fake)  # type: ignore[arg-type]
    assert watch.scan_once() == []
    assert fake.requests == []


def test_stable_scans_must_be_positive(tmp_path: Path) -> None:
    """A stability count below one is refused."""
    with pytest.raises(ValueError, match="stable_scans"):
        WatchFolder(tmp_path, FakeEngine(), stable_scans=0)  # type: ignore[arg-type]
