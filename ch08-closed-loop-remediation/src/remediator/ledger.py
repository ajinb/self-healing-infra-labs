"""Action ledger — last-N breadcrumbs of in-flight and recent actions.

Two purposes: (a) the rollback step needs to know what was changed so the
inverse handler can target the right resources; (b) the kill-switch in
Chapter 9 needs a way to identify in-flight actions to abort.

In-memory deque for the lab; production deployments back this with Redis or
the same audit sink the runner writes to.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LedgerEntry:
    event_id: str
    action: str
    params: dict[str, Any]
    tenant: str
    actor: str
    ts_unix: int
    rollback_depth: int = 0
    rolled_back: bool = False
    terminal: bool = False
    extras: dict[str, Any] = field(default_factory=dict)


class Ledger:
    def __init__(self, capacity: int = 100):
        self._entries: deque[LedgerEntry] = deque(maxlen=capacity)

    def record(
        self,
        event_id: str,
        action: str,
        params: dict[str, Any],
        ctx,
        rollback_depth: int = 0,
    ) -> LedgerEntry:
        entry = LedgerEntry(
            event_id=event_id,
            action=action,
            params=params,
            tenant=ctx.tenant,
            actor=ctx.actor,
            ts_unix=int(time.time()),
            rollback_depth=rollback_depth,
        )
        self._entries.append(entry)
        return entry

    def mark_terminal(self, event_id: str) -> None:
        for e in self._entries:
            if e.event_id == event_id:
                e.terminal = True
                return

    def mark_rolled_back(self, event_id: str) -> None:
        for e in self._entries:
            if e.event_id == event_id:
                e.rolled_back = True
                e.terminal = True
                return

    def find_open(
        self, tenant: str, action: str, key: tuple[str, ...]
    ) -> Optional[LedgerEntry]:
        """Return the most recent non-terminal entry matching tenant + action +
        a handler-specific key (typically (namespace, resource))."""
        for e in reversed(self._entries):
            if e.terminal:
                continue
            if e.tenant != tenant or e.action != action:
                continue
            entry_key = (e.params.get("namespace", ""), e.params.get("deployment", ""))
            if entry_key == key:
                return e
        return None

    def last_action_against(
        self, tenant: str, key: tuple[str, ...]
    ) -> Optional[LedgerEntry]:
        for e in reversed(self._entries):
            if e.tenant != tenant:
                continue
            entry_key = (e.params.get("namespace", ""), e.params.get("deployment", ""))
            if entry_key == key:
                return e
        return None

    def all(self) -> list[LedgerEntry]:
        return list(self._entries)
