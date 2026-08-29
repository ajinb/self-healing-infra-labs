"""Timeline store.

In-memory here so the lab runs with nothing installed; the production shape is
Postgres with the same interface. The timeline is a first-class artifact, not a
byproduct of drafting — you can inspect it, correct it, and re-draft from it.
"""

from __future__ import annotations

from collections import defaultdict

from .schema import TimelineEntry


class TimelineStore:
    def __init__(self) -> None:
        self._entries: dict[str, list[TimelineEntry]] = defaultdict(list)
        self._nudges: dict[str, int] = defaultdict(int)

    async def append(self, entry: TimelineEntry) -> None:
        self._entries[entry.incident_id].append(entry)

    async def get(self, incident_id: str) -> list[TimelineEntry]:
        return sorted(self._entries[incident_id], key=lambda e: e.timestamp)

    async def nudge_count(self, incident_id: str) -> int:
        return self._nudges[incident_id]

    async def record_nudge(self, incident_id: str) -> None:
        self._nudges[incident_id] += 1

    def reset(self) -> None:
        self._entries.clear()
        self._nudges.clear()


store = TimelineStore()
