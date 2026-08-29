"""FastMCP server wiring auth → policy → rate limit → tool → audit.

Each tool follows the same lifecycle. Inline here for visibility; refactoring
into a decorator is the obvious next step once the structure is settled.
"""

from __future__ import annotations

import time
from contextvars import ContextVar

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

from .audit import emit_audit_event
from .auth import (
    EXPECTED_AUDIENCE,
    JWKS_URL,
    OAUTH_ISSUER,
    AuthContext,
    verify_jwt_and_build_context,
)
from .policy import PolicyDeny, authorize
from .ratelimit import RateLimitExceeded, enforce_rate_limit
from .tools import incidents, runbooks


app = FastMCP(
    "self-healing-infra-mcp",
    # Transport-level OAuth 2.1 resource server: bad tokens are rejected with an
    # HTTP 401 before any MCP message is processed, and the server advertises
    # RFC 9728 protected-resource metadata for client discovery.
    auth=JWTVerifier(jwks_uri=JWKS_URL, issuer=OAUTH_ISSUER, audience=EXPECTED_AUDIENCE),
)
auth_ctx: ContextVar[AuthContext] = ContextVar("auth_ctx")


class CABPMiddleware(Middleware):
    """Build the per-request authorization context (CABP) from the verified token."""

    async def on_request(self, context: MiddlewareContext, call_next):
        headers = get_http_headers()
        token = headers.get("authorization", "").removeprefix("Bearer ").strip()
        ctx = await verify_jwt_and_build_context(token)  # raises AuthError on failure
        auth_ctx.set(ctx)
        return await call_next(context)


app.add_middleware(CABPMiddleware())


@app.tool(name="runbooks.search")
async def runbooks_search(query: str, limit: int = 10) -> dict:
    ctx = auth_ctx.get()
    started = time.monotonic()
    try:
        authorize(ctx, tool="runbooks.search")
        await enforce_rate_limit(ctx, tool="runbooks.search")
        result = await runbooks.search(ctx, query=query, limit=limit)
    except PolicyDeny:
        await emit_audit_event(
            ctx,
            tool="runbooks.search",
            outcome="denied",
            input_hash=runbooks.hash_input(query, limit),
            policy_decision="deny",
        )
        raise
    except RateLimitExceeded:
        await emit_audit_event(
            ctx,
            tool="runbooks.search",
            outcome="rate_limited",
            input_hash=runbooks.hash_input(query, limit),
        )
        raise
    await emit_audit_event(
        ctx,
        tool="runbooks.search",
        outcome="success",
        input_hash=runbooks.hash_input(query, limit),
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return result


@app.tool(name="incidents.create")
async def incidents_create(
    title: str, severity: str, summary: str, idempotency_key: str | None = None
) -> dict:
    """Create an incident.

    `idempotency_key` is optional: pass one to make a retry provably the same
    logical write. Omitted, the tool derives a key from the tenant, subject,
    and content, so an unmodified re-issue after a dropped stream collapses
    onto the original record instead of creating a second incident.
    """
    ctx = auth_ctx.get()
    started = time.monotonic()
    try:
        authorize(ctx, tool="incidents.create")
        await enforce_rate_limit(ctx, tool="incidents.create")
        result = await incidents.create(
            ctx,
            title=title,
            severity=severity,
            summary=summary,
            idempotency_key=idempotency_key,
        )
    except PolicyDeny:
        await emit_audit_event(
            ctx,
            tool="incidents.create",
            outcome="denied",
            input_hash=incidents.hash_input(title, severity, summary),
            policy_decision="deny",
        )
        raise
    except RateLimitExceeded:
        await emit_audit_event(
            ctx,
            tool="incidents.create",
            outcome="rate_limited",
            input_hash=incidents.hash_input(title, severity, summary),
        )
        raise
    await emit_audit_event(
        ctx,
        tool="incidents.create",
        # A replay is not a second write. Recording it as "success" would make
        # the audit log show two creations where the platform performed one.
        outcome="idempotent_replay" if result.get("idempotent_replay") else "success",
        input_hash=incidents.hash_input(title, severity, summary),
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("mcp_server.server:app", host="0.0.0.0", port=8080, reload=False)
