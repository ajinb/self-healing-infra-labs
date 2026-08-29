"""Stage 2 — context retrieval through the Chapter 4 MCP surface.

Context is the substrate, not the prompt. This is the call that decides whether
the model has anything useful to say, and it is bounded on both time and size.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

from .config import settings
from .schema import Alert

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures"


class ContextBudgetExceeded(Exception):
    """Raised when assembled context exceeds the token budget.

    Deliberately not a truncation: silently dropping context produces a
    confident answer built on the half of the evidence that happened to fit.
    """


def _estimate_tokens(text: str) -> int:
    # ~4 chars/token is close enough for a pre-flight guard.
    return len(text) // 4


async def gather_context(alert: Alert) -> dict:
    """Fetch runbooks, recent deploys, and service ownership for this alert.

    Returns a dict rather than a prompt string so the caller decides framing.
    """
    if settings.MCP_ENDPOINT == "mock":
        ctx = _replay_fixture(alert)
    else:  # pragma: no cover - requires the Ch 4 fixture running
        ctx = await asyncio.wait_for(
            _fetch_via_mcp(alert), timeout=settings.CONTEXT_TIMEOUT_S
        )

    budget = _estimate_tokens(json.dumps(ctx))
    if budget > settings.MAX_CONTEXT_TOKENS:
        raise ContextBudgetExceeded(
            f"context {budget} tokens exceeds budget {settings.MAX_CONTEXT_TOKENS}"
        )
    return ctx


def _replay_fixture(alert: Alert) -> dict:
    path = FIXTURES / "context" / f"{alert.name}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"runbooks": [], "recent_deploys": [], "owner": None, "note": "no context found"}


async def _fetch_via_mcp(alert: Alert) -> dict:  # pragma: no cover
    """Call the Chapter 4 MCP gateway. Every call carries the caller's
    delegated identity; the gateway authorises, rate-limits, and audits it."""
    import httpx

    async with httpx.AsyncClient(timeout=settings.CONTEXT_TIMEOUT_S) as c:
        r = await c.post(
            f"{settings.MCP_ENDPOINT}/tools/runbooks.search",
            json={"query": alert.name, "limit": 3},
        )
        r.raise_for_status()
        return r.json()
