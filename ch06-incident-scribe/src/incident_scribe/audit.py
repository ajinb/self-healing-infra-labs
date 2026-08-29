"""Audit emission through the Chapter 4 MCP surface.

Every action the scribe takes is emitted: every classified message, every nudge
posted, every draft generated. The auditor asking "what AI activity touched
this incident?" should get one complete answer, not three partial ones.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from .config import settings

_EMITTED: list[dict] = []  # test-visible sink for AUDIT_SINK=stdout


async def emit_audit(action: str, incident_id: str, **kwargs) -> dict:
    event = {
        "ts": datetime.now(UTC).isoformat(),
        "source": "incident-scribe",
        "action": action,
        "incident_id": incident_id,
        **kwargs,
    }
    if settings.AUDIT_SINK == "stdout":
        _EMITTED.append(event)
        print(json.dumps(event))
    else:  # pragma: no cover - requires the Ch 4 fixture
        import httpx

        async with httpx.AsyncClient(timeout=2.0) as c:
            await c.post(f"{settings.MCP_ENDPOINT}/audit", json=event)
    return event


def emitted() -> list[dict]:
    return list(_EMITTED)


def reset_audit() -> None:
    _EMITTED.clear()
