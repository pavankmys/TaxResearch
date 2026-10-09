"""Worker heartbeat for health checks.

Writes the current epoch seconds to a file periodically, allowing a container
healthcheck to verify the worker is still running.
"""

import argparse
import os
import sys
import threading
import time


def start_heartbeat(path: str, interval: float = 10.0) -> threading.Thread:
    """Start a heartbeat thread that writes epoch seconds to a file.

    Args:
        path: Path to the heartbeat file
        interval: Interval in seconds between heartbeats (default 10.0)

    Returns:
        A daemon thread that can be started with thread.start()
    """

    def _heartbeat_loop() -> None:
        """Write epoch seconds to file periodically."""
        while True:
            try:
                with open(path, "w") as f:
                    f.write(str(int(time.time())))
            except Exception:
                # If we can't write the heartbeat, log it but continue
                pass
            time.sleep(interval)

    thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    return thread


def is_fresh(path: str, max_age: float = 60.0) -> bool:
    """Check if the heartbeat file exists and is fresh.

    Args:
        path: Path to the heartbeat file
        max_age: Maximum age in seconds (default 60.0)

    Returns:
        True if the heartbeat file exists and was updated within max_age seconds
    """
    try:
        if not os.path.exists(path):
            return False

        with open(path) as f:
            content = f.read().strip()

        if not content:
            return False

        timestamp = int(content)
        current_time = int(time.time())
        age = current_time - timestamp

        return age <= max_age
    except Exception:
        return False


def main() -> int:
    """Entry point for heartbeat check via `python -m worker.heartbeat`.

    Usage:
        python -m worker.heartbeat --check [--file PATH] [--max-age N]

    Returns:
        0 if heartbeat is fresh, 1 otherwise
    """
    parser = argparse.ArgumentParser(description="Worker heartbeat check")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if heartbeat is fresh and exit (used by healthcheck)",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Path to heartbeat file (default: HEARTBEAT_FILE env var or /tmp/worker.heartbeat)",
    )
    parser.add_argument(
        "--max-age",
        type=float,
        default=60.0,
        help="Maximum heartbeat age in seconds (default: 60)",
    )

    args = parser.parse_args()

    # Determine heartbeat file path
    heartbeat_file = args.file or os.getenv("HEARTBEAT_FILE", "/tmp/worker.heartbeat")

    if args.check:
        # Just check if fresh and exit
        if is_fresh(heartbeat_file, max_age=args.max_age):
            sys.exit(0)
        else:
            sys.exit(1)

    # No-op if not in check mode (shouldn't be called without --check from outside)
    sys.exit(0)


if __name__ == "__main__":
    sys.exit(main())
