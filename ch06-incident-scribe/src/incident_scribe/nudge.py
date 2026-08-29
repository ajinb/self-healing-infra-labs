"""Stage 2 — surfacing what is missing.

Bounded on purpose: never more than one nudge per check, never more than
NUDGE_MAX_PER_INCIDENT per incident, and always framed as an observation the
team can dismiss. An unbounded nudger is a bot that gets muted, and a muted
bot cannot surface the thing that mattered.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .audit import emit_audit
from .config import settings
from .schema import TimelineEntry
from .store import store

DISMISS = "(scribe is asking; reply or react to dismiss)"


def _has_category(timeline: list[TimelineEntry], category: str) -> bool:
    return any(e.category == category for e in timeline)


def _minutes_since_open(timeline: list[TimelineEntry]) -> float:
    if not timeline:
        return 0.0
    first = min(e.timestamp for e in timeline)
    now = datetime.now(UTC)
    if first.tzinfo is None:
        first = first.replace(tzinfo=UTC)
    return (now - first).total_seconds() / 60.0


def _contradicts(timeline: list[TimelineEntry]) -> bool:
    """Very small heuristic: recent observations that disagree on recovery."""
    recent = timeline[-4:]
    said_recovered = any("recovered" in e.content.lower() for e in recent)
    said_still = any(
        ("still" in e.content.lower() or "not recovered" in e.content.lower())
        for e in recent
    )
    return said_recovered and said_still


async def maybe_nudge(incident_id: str) -> str | None:
    """Return the nudge text to post, or None. At most one per call."""
    timeline = await store.get(incident_id)

    if len(timeline) < settings.NUDGE_MIN_TIMELINE_ENTRIES:
        return None  # too early to have an opinion
    if await store.nudge_count(incident_id) >= settings.NUDGE_MAX_PER_INCIDENT:
        return None  # budget spent; silence is the correct behaviour

    text: str | None = None
    if (
        not _has_category(timeline, "hypothesis")
        and _minutes_since_open(timeline) > settings.NUDGE_HYPOTHESIS_AFTER_MIN
    ):
        text = (
            f":memo: {settings.NUDGE_HYPOTHESIS_AFTER_MIN} minutes in — does the team "
            f"have a working hypothesis on cause? {DISMISS}"
        )
    elif _contradicts(timeline):
        text = (
            ":memo: Two recent messages contradict on the state of the service. "
            f"Which is current? {DISMISS}"
        )

    if text is None:
        return None

    await store.record_nudge(incident_id)
    await emit_audit("nudge_posted", incident_id, nudge=text)
    return text
