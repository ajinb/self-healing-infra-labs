"""Safe (read-only) tool: tenant-scoped full-text search over a runbook store.

The actual database call is stubbed; replace `_db_fetch` with your real
adapter. Tenant scoping is mandatory and enforced inside the SQL.
"""

from __future__ import annotations

import hashlib

from ..auth import AuthContext


async def search(ctx: AuthContext, *, query: str, limit: int) -> dict:
    rows = await _db_fetch(
        "SELECT id, title, summary FROM runbooks "
        "WHERE tenant = $1 AND search_vec @@ websearch_to_tsquery($2) LIMIT $3",
        ctx.tenant,
        query,
        limit,
    )
    return {"results": rows, "query": query}


def hash_input(query: str, limit: int) -> str:
    return "sha256:" + hashlib.sha256(f"{query}|{limit}".encode()).hexdigest()


async def _db_fetch(sql: str, *args) -> list[dict]:
    """Stub. Replace with real DB adapter (asyncpg, sqlalchemy[asyncio], etc.)."""
    return []
