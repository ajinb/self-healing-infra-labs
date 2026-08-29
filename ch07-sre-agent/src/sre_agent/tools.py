"""The tool allowlist — the bright line of this chapter.

Read tools are unrestricted. Writes are permitted only where a human still
reviews the result: a draft PR, a backlog ticket, a message to a non-paging
channel. Nothing here executes a remediation, pages a human, or mutates
production state.

The list is data, and `classify_tool` is the only way to ask about a tool, so
adding a capability means editing this file — which is exactly the review you
want that change to get.
"""

from __future__ import annotations

from enum import Enum


class ToolClass(str, Enum):
    READ = "read"
    QUEUED_WRITE = "queued_write"   # a human reviews before it takes effect
    FORBIDDEN = "forbidden"         # executes, pages, or mutates production


READ_TOOLS: frozenset[str] = frozenset({
    "runbooks.search",
    "incidents.search",
    "deploys.recent",
    "servicegraph.dependencies",
    "metrics.query",
})

# Two-way doors in the strongest sense: a human merges, closes, or reads them.
QUEUED_WRITE_TOOLS: frozenset[str] = frozenset({
    "pr.draft",        # draft PR against the runbook repo
    "ticket.queue",    # backlog state only, never in-progress
    "chat.notify",     # non-paging channel only
})


def classify_tool(name: str) -> ToolClass:
    if name in READ_TOOLS:
        return ToolClass.READ
    if name in QUEUED_WRITE_TOOLS:
        return ToolClass.QUEUED_WRITE
    return ToolClass.FORBIDDEN


def is_permitted(name: str) -> bool:
    return classify_tool(name) is not ToolClass.FORBIDDEN
