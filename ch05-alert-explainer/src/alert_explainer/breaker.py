"""A minimal asyncio circuit breaker around the model call.

Hand-rolled deliberately: the mature Python breaker libraries are sync-first,
and adapting one across an async boundary is more code — and more failure
surface — than this. Graduate to a shared, Redis-backed breaker when you need
state coordinated across replicas, and not before.
"""

from __future__ import annotations

import time

from pydantic import ValidationError


class BreakerOpen(Exception):
    """Raised instead of calling the provider while the breaker is open."""


class AsyncCircuitBreaker:
    def __init__(self, fail_max: int = 5, reset_timeout: float = 30.0):
        self.fail_max, self.reset_timeout = fail_max, reset_timeout
        self._failures: int = 0
        self._opened_at: float | None = None

    def _is_open(self) -> bool:
        if self._opened_at is None:
            return False
        # past the reset window -> half-open: let the next call probe the provider
        return time.monotonic() - self._opened_at < self.reset_timeout

    async def call(self, fn, *args, **kwargs):
        if self._is_open():
            raise BreakerOpen
        try:
            result = await fn(*args, **kwargs)
        except (ValueError, ValidationError):
            raise  # logic errors are bugs, not provider failures; don't trip
        except Exception:
            self._failures += 1
            if self._failures >= self.fail_max:
                self._opened_at = time.monotonic()
            raise
        self._failures, self._opened_at = 0, None
        return result

    def reset(self) -> None:
        self._failures, self._opened_at = 0, None


model_breaker = AsyncCircuitBreaker(fail_max=5, reset_timeout=30)
