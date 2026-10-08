"""Tests for the in-memory login rate limiter."""

from app.auth.ratelimit import LoginRateLimiter

KEY = ("user@example.com", "203.0.113.5")


class FakeClock:
    """A clock that only moves when told to."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _limiter(clock: FakeClock) -> LoginRateLimiter:
    return LoginRateLimiter(max_failures=5, window_seconds=900, clock=clock)


def test_blocked_after_five_failures() -> None:
    """Four failures do not block; the fifth does."""
    clock = FakeClock()
    limiter = _limiter(clock)
    for _ in range(4):
        limiter.record_failure(KEY)
    assert limiter.is_blocked(KEY) is False
    limiter.record_failure(KEY)
    assert limiter.is_blocked(KEY) is True


def test_unblocked_after_window() -> None:
    """Failures age out once the window has passed."""
    clock = FakeClock()
    limiter = _limiter(clock)
    for _ in range(5):
        limiter.record_failure(KEY)
    clock.now += 899
    assert limiter.is_blocked(KEY) is True
    clock.now += 2
    assert limiter.is_blocked(KEY) is False


def test_reset_clears_failures() -> None:
    """A successful login clears the key."""
    clock = FakeClock()
    limiter = _limiter(clock)
    for _ in range(5):
        limiter.record_failure(KEY)
    limiter.reset(KEY)
    assert limiter.is_blocked(KEY) is False


def test_keys_are_independent() -> None:
    """Failures for one email and IP do not block another."""
    clock = FakeClock()
    limiter = _limiter(clock)
    for _ in range(5):
        limiter.record_failure(KEY)
    assert limiter.is_blocked(("other@example.com", "203.0.113.5")) is False
    assert limiter.is_blocked((KEY[0], "198.51.100.9")) is False


def test_old_entries_are_pruned() -> None:
    """Recording a failure removes expired entries for other keys."""
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.record_failure(KEY)
    clock.now += 1000
    limiter.record_failure(("other@example.com", None))
    assert KEY not in limiter._failures  # noqa: SLF001
