"""Step tracing.

Every agent step is captured: which agent, how long, what it cost, whether it
succeeded. Without this a multi-agent system is unfalsifiable — you cannot tell
a slow worker from a broken one, or a cheap investigation from an expensive one.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field


@dataclass
class Step:
    name: str
    duration_ms: float
    ok: bool
    error: str | None = None


@dataclass
class Trace:
    steps: list[Step] = field(default_factory=list)

    def record(self, step: Step) -> None:
        self.steps.append(step)

    @property
    def total_ms(self) -> float:
        return sum(s.duration_ms for s in self.steps)

    def names(self) -> list[str]:
        return [s.name for s in self.steps]

    def reset(self) -> None:
        self.steps.clear()


TRACE = Trace()


def trace_step(name: str):
    """Decorator recording one agent step, on success and on failure alike.

    Failures are the interesting half: an untraced exception is a worker that
    silently contributed nothing to the investigation.
    """
    def outer(fn):
        @functools.wraps(fn)
        async def inner(*args, **kwargs):
            started = time.monotonic()
            try:
                out = await fn(*args, **kwargs)
            except Exception as e:
                TRACE.record(Step(name, (time.monotonic() - started) * 1000, False, str(e)))
                raise
            TRACE.record(Step(name, (time.monotonic() - started) * 1000, True))
            return out
        return inner
    return outer
