"""Reversibility tiers, the @reversibility decorator, and the per-call gate.

The gate is the operational expression of the Chapter 0 Reversibility Gate
mental model. Three tiers, with a per-call adjuster that may upgrade the
realized tier when call-site conditions are worse than the handler's
optimistic baseline.
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable


class Reversibility(IntEnum):
    REVERSIBLE = 1
    RECOVERABLE = 2
    IRREVERSIBLE = 3


def reversibility(tier: Reversibility) -> Callable:
    def wrap(fn: Callable) -> Callable:
        fn.__reversibility__ = tier  # type: ignore[attr-defined]
        return fn

    return wrap


@dataclass
class GateDecision:
    tier: Reversibility
    proceed: bool
    reason: str
    requires_human: bool


def evaluate(
    handler: Callable,
    call_site: dict[str, Any],
    *,
    autonomy_ceiling: Reversibility = Reversibility.RECOVERABLE,
) -> GateDecision:
    """Compute the realized reversibility tier for one call and decide whether
    to proceed autonomously.

    `handler` is the callable that will perform the action; its
    `__reversibility__` attribute (set by the decorator) is the optimistic
    baseline. `call_site` carries handler-specific signals consulted by the
    adjuster. `autonomy_ceiling` is the highest realized tier the runner is
    permitted to act on without a human; default RECOVERABLE.
    """
    base = getattr(handler, "__reversibility__", Reversibility.IRREVERSIBLE)
    realized = _adjust(base, call_site)
    if realized > autonomy_ceiling:
        return GateDecision(
            tier=realized,
            proceed=False,
            reason=(
                f"realized tier {realized.name} exceeds autonomy ceiling "
                f"{autonomy_ceiling.name}"
            ),
            requires_human=True,
        )
    return GateDecision(
        tier=realized, proceed=True, reason="ok", requires_human=False
    )


def _adjust(base: Reversibility, call_site: dict[str, Any]) -> Reversibility:
    """The honesty function. Upgrade the tier when call-site conditions are
    worse than the optimistic baseline assumes.

    Add a rule here every time a postmortem teaches you a new one.
    """
    tier = base
    if call_site.get("replicas", 99) < 2:
        tier = max(tier, Reversibility.RECOVERABLE)
    if call_site.get("has_readiness_probe") is False:
        tier = max(tier, Reversibility.RECOVERABLE)
    if call_site.get("stateful") is True:
        tier = max(tier, Reversibility.IRREVERSIBLE)
    if call_site.get("max_age_seconds", 0) > 900:
        # Rollback older than 15 minutes is treated as IRREVERSIBLE — see Ch 8.
        tier = max(tier, Reversibility.IRREVERSIBLE)
    return tier
