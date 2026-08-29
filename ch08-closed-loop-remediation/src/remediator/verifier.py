"""Post-action verifier.

A handler that "succeeded" without verification did not succeed — it
committed an action whose effect we have not measured. The verifier polls
the relevant signal for up to a deadline and returns a structured result
the runner can either accept or roll back from.

The lab uses pluggable probes. Production deployments wire these to
Prometheus / Datadog / your APM of choice.
"""

import time
from typing import Callable

from .context import ActionContext

ProbeFn = Callable[[dict, ActionContext], tuple[bool, str]]

_PROBES: dict[str, ProbeFn] = {}


def register(action_name: str, probe: ProbeFn) -> None:
    _PROBES[action_name] = probe


def verify(action_name: str, params: dict, ctx: ActionContext) -> tuple[bool, str]:
    probe = _PROBES.get(action_name)
    if probe is None:
        return False, f"no probe registered for action '{action_name}'"
    return probe(params, ctx)


def poll_until(
    check: Callable[[], tuple[bool, str]],
    *,
    deadline_unix: int,
    interval_seconds: float = 2.0,
) -> tuple[bool, str]:
    """Run `check` repeatedly until it returns True or the deadline passes."""
    last_msg = "deadline reached before any check ran"
    while time.time() < deadline_unix:
        ok, msg = check()
        last_msg = msg
        if ok:
            return True, msg
        time.sleep(interval_seconds)
    return False, last_msg
