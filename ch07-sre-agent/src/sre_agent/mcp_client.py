"""Client for the Chapter 4 MCP gateway.

Every call carries the caller's delegated identity; the gateway authorises,
rate-limits, and audits. The mock session replays fixtures so the lab runs
without the Ch 4 stack up.
"""

from __future__ import annotations

import contextlib
import json
import pathlib

from .config import settings
from .tools import is_permitted

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures"


class ToolNotPermitted(Exception):
    """Second enforcement point. The schema rejects forbidden tools at plan
    time; this rejects them at call time, in case a plan was constructed some
    other way."""


class _Session:
    def __init__(self, ctx: dict):
        self.ctx = ctx

    async def call(self, tool: str, args: dict):
        if not is_permitted(tool):
            raise ToolNotPermitted(f"{tool} is not on the allowlist")
        if settings.MCP_ENDPOINT == "mock":
            return self._replay(tool, args)
        return await self._call_gateway(tool, args)  # pragma: no cover

    def _replay(self, tool: str, args: dict):
        path = FIXTURES / "mcp" / f"{tool}.json"
        if path.exists():
            return json.loads(path.read_text())
        return {"tool": tool, "args": args, "result": []}

    async def _call_gateway(self, tool: str, args: dict):  # pragma: no cover
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(
                f"{settings.MCP_ENDPOINT}/tools/{tool}",
                json=args,
                headers={"authorization": f"Bearer {self.ctx.get('token', '')}"},
            )
            r.raise_for_status()
            return r.json()


@contextlib.asynccontextmanager
async def session(ctx: dict):
    yield _Session(ctx)
