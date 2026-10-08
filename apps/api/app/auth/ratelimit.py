"""In-memory login rate limiter, keyed by (email, client ip).

This is enough for the POC's single API process. It is not shared between workers.
"""

import time
from collections.abc import Callable
from functools import lru_cache

from app.settings import get_settings

LoginKey = tuple[str, str | None]


class LoginRateLimiter:
    """Blocks a key after ``max_failures`` failures inside a sliding window."""

    def __init__(
        self,
        max_failures: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_failures = max_failures
        self._window = float(window_seconds)
        self._clock = clock
        self._failures: dict[LoginKey, list[float]] = {}

    def _recent(self, key: LoginKey, now: float) -> list[float]:
        """Return the failures for ``key`` inside the window, dropping old ones."""
        stamps = self._failures.get(key)
        if not stamps:
            self._failures.pop(key, None)
            return []
        cutoff = now - self._window
        recent = [stamp for stamp in stamps if stamp > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def is_blocked(self, key: LoginKey) -> bool:
        """Return True if the key has reached the failure limit inside the window."""
        return len(self._recent(key, self._clock())) >= self._max_failures

    def record_failure(self, key: LoginKey) -> None:
        """Record a failed login for the key and prune entries for all other keys."""
        now = self._clock()
        recent = self._recent(key, now)
        recent.append(now)
        self._failures[key] = recent
        for other in list(self._failures):
            self._recent(other, now)

    def reset(self, key: LoginKey) -> None:
        """Forget all failures for the key (after a successful login)."""
        self._failures.pop(key, None)


@lru_cache(maxsize=1)
def get_login_rate_limiter() -> LoginRateLimiter:
    """Return the process-wide limiter built from settings. Override in tests."""
    settings = get_settings()
    return LoginRateLimiter(settings.login_max_failures, settings.login_window_seconds)
