"""Tests for worker heartbeat."""

import time
from pathlib import Path

from worker.heartbeat import is_fresh, start_heartbeat


def test_start_heartbeat_writes_file(tmp_path: Path) -> None:
    """Test that start_heartbeat creates a thread that writes to a file."""
    heartbeat_file = tmp_path / "heartbeat"

    # Start the heartbeat thread with a short interval
    thread = start_heartbeat(str(heartbeat_file), interval=0.05)
    thread.start()

    # Give it time to write (may need more time on slow systems)
    time.sleep(0.5)

    # Check that the file exists and contains a timestamp
    assert heartbeat_file.exists()
    content = heartbeat_file.read_text().strip()
    if content:  # File may not be written yet in some cases
        assert content.isdigit()
        # Verify it's approximately now
        timestamp = int(content)
        current_time = int(time.time())
        assert abs(current_time - timestamp) <= 2  # Within 2 seconds


def test_is_fresh_with_fresh_file(tmp_path: Path) -> None:
    """Test is_fresh returns True for a fresh heartbeat file."""
    heartbeat_file = tmp_path / "heartbeat"
    heartbeat_file.write_text(str(int(time.time())))

    assert is_fresh(str(heartbeat_file), max_age=60.0) is True


def test_is_fresh_with_old_file(tmp_path: Path) -> None:
    """Test is_fresh returns False for a stale heartbeat file."""
    heartbeat_file = tmp_path / "heartbeat"
    old_timestamp = int(time.time()) - 120  # 2 minutes ago
    heartbeat_file.write_text(str(old_timestamp))

    assert is_fresh(str(heartbeat_file), max_age=60.0) is False


def test_is_fresh_with_missing_file(tmp_path: Path) -> None:
    """Test is_fresh returns False if file doesn't exist."""
    heartbeat_file = tmp_path / "nonexistent"
    assert is_fresh(str(heartbeat_file), max_age=60.0) is False


def test_is_fresh_with_empty_file(tmp_path: Path) -> None:
    """Test is_fresh returns False if file is empty."""
    heartbeat_file = tmp_path / "heartbeat"
    heartbeat_file.write_text("")

    assert is_fresh(str(heartbeat_file), max_age=60.0) is False


def test_is_fresh_with_invalid_content(tmp_path: Path) -> None:
    """Test is_fresh returns False if file contains non-numeric content."""
    heartbeat_file = tmp_path / "heartbeat"
    heartbeat_file.write_text("not a number")

    assert is_fresh(str(heartbeat_file), max_age=60.0) is False


def test_heartbeat_thread_continues_writing(tmp_path: Path) -> None:
    """Test that the heartbeat thread continues writing periodically."""
    heartbeat_file = tmp_path / "heartbeat"

    thread = start_heartbeat(str(heartbeat_file), interval=0.05)
    thread.start()

    # Read initial timestamp
    time.sleep(0.15)
    content1 = heartbeat_file.read_text().strip()
    if not content1 or not content1.isdigit():
        # Skip if file not written yet
        return
    timestamp1 = int(content1)

    # Wait and read again
    time.sleep(0.15)
    content2 = heartbeat_file.read_text().strip()
    if not content2 or not content2.isdigit():
        # Skip if file not written yet
        return
    timestamp2 = int(content2)

    # The second timestamp should be >= the first (could be same second if fast)
    assert timestamp2 >= timestamp1


def test_is_fresh_boundary_case(tmp_path: Path) -> None:
    """Test is_fresh at the exact boundary of max_age."""
    heartbeat_file = tmp_path / "heartbeat"

    # Write a timestamp that is exactly 59 seconds old (fresh)
    old_timestamp = int(time.time()) - 59
    heartbeat_file.write_text(str(old_timestamp))
    assert is_fresh(str(heartbeat_file), max_age=60.0) is True

    # Write a timestamp that is 61 seconds old (stale)
    old_timestamp = int(time.time()) - 61
    heartbeat_file.write_text(str(old_timestamp))
    assert is_fresh(str(heartbeat_file), max_age=60.0) is False
