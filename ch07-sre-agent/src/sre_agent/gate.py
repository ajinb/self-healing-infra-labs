"""The human-review gate.

The single most important architectural decision in this chapter: the system
never closes the loop on disruptive remediation. It renders evidence for a
human — brief on top, raw underneath — and stops.
"""

from __future__ import annotations

from .schema import Investigation
from .tools import ToolClass, classify_tool


class RemediationRefused(Exception):
    """Raised if anything asks this system to execute a remediation."""


def render_for_oncall(inv: Investigation) -> dict:
    """Brief on top, raw underneath. No execute button."""
    h = inv.hypothesis
    lines = [
        f"{inv.plan.alert.alert_name} [{inv.plan.alert.severity}] on {inv.plan.alert.service}",
        "",
        f"Probable cause ({h.confidence} confidence): {h.probable_cause}",
        "",
        "Verification steps:",
        *[f"  {i}. {s}" for i, s in enumerate(h.verification_steps, 1)],
    ]
    if h.unknowns:
        lines += ["", "Unknowns:", *[f"  - {u}" for u in h.unknowns]]
    if inv.partial:
        lines += ["", "NOTE: some retrieval failed; this ran on partial evidence."]
    return {
        "brief": "\n".join(lines),
        "raw": [r.model_dump() for r in inv.results],
        "requires_human_action": True,
        "auto_executed": False,
    }


def authorize_write(tool: str) -> None:
    """The only write path out of this system.

    Queued writes are permitted because a human still reviews the result: a
    draft PR gets merged, a backlog ticket gets triaged, a notification gets
    read. Anything that executes, pages, or mutates production is refused.
    """
    cls = classify_tool(tool)
    if cls is ToolClass.QUEUED_WRITE:
        return
    raise RemediationRefused(
        f"{tool!r} is classified {cls.value}; this system does not execute remediation"
    )
