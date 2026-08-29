"""The negative tests that matter.

A green positive-path suite tells you the happy path works. The negative suite
is what tells you the auth, policy, rate limit, and audit are doing their jobs.

These tests run against pure-Python units (not the live FastMCP server),
so they pass without docker-compose. Integration tests against the live
fixture live in `tests/integration/` and are opt-in via marker.
"""

from __future__ import annotations

import pytest

from mcp_server import policy
from mcp_server.auth import AuthContext


def _ctx(*, tenant="flight-ops", roles=("runbook.reader",), sub="user-1") -> AuthContext:
    return AuthContext(
        sub=sub,
        email=f"{sub}@example.com",
        tenant=tenant,
        roles=tuple(roles),
        deadline_ms=10_000,
    )


def test_authorize_unknown_tool_is_denied():
    with pytest.raises(policy.PolicyDeny):
        policy.authorize(_ctx(), tool="not.a.real.tool")


def test_authorize_runbook_reader_can_search():
    policy.authorize(_ctx(roles=("runbook.reader",)), tool="runbooks.search")


def test_authorize_missing_role_is_denied():
    # incidents.create requires incident.writer; this caller lacks it.
    with pytest.raises(policy.PolicyDeny):
        policy.authorize(_ctx(roles=("runbook.reader",)), tool="incidents.create")


def test_authorize_wrong_tenant_is_denied():
    # incidents.create restricts to flight-ops/platform.
    with pytest.raises(policy.PolicyDeny):
        policy.authorize(
            _ctx(tenant="billing", roles=("incident.writer",)),
            tool="incidents.create",
        )


def test_authorize_correct_tenant_and_role_is_allowed():
    policy.authorize(
        _ctx(tenant="platform", roles=("incident.writer",)),
        tool="incidents.create",
    )


def test_incident_severity_validation():
    """The incidents tool boundary validates inputs even though the schema also did."""
    from mcp_server.tools import incidents

    async def _run():
        with pytest.raises(ValueError):
            await incidents.create(_ctx(roles=("incident.writer",)), title="t", severity="catastrophic", summary="s")
        with pytest.raises(ValueError):
            await incidents.create(_ctx(roles=("incident.writer",)), title="x" * 999, severity="sev2", summary="s")

    import asyncio
    asyncio.run(_run())


# --- retry-safety -----------------------------------------------------------
# MCP 2026-07-28 removed SSE stream resumability, so a dropped stream means the
# client re-issues the request. These tests pin the behaviour that keeps that
# from duplicating records.


async def test_retry_of_identical_write_does_not_duplicate():
    from mcp_server.tools import incidents

    incidents._STUB_ROWS.clear()
    ctx = _ctx(roles=("incident.writer",))
    args = dict(title="payments latency", severity="sev2", summary="p99 breach")

    first = await incidents.create(ctx, **args)
    replay = await incidents.create(ctx, **args)

    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    assert first["id"] == replay["id"]
    assert len(incidents._STUB_ROWS) == 1


async def test_distinct_content_still_creates_distinct_incidents():
    from mcp_server.tools import incidents

    incidents._STUB_ROWS.clear()
    ctx = _ctx(roles=("incident.writer",))
    a = await incidents.create(ctx, title="a", severity="sev3", summary="one")
    b = await incidents.create(ctx, title="b", severity="sev3", summary="two")

    assert a["id"] != b["id"]
    assert len(incidents._STUB_ROWS) == 2


async def test_explicit_idempotency_key_beats_content_hash():
    """Same content, different keys -> two incidents, which is the caller's call."""
    from mcp_server.tools import incidents

    incidents._STUB_ROWS.clear()
    ctx = _ctx(roles=("incident.writer",))
    args = dict(title="disk full", severity="sev3", summary="node-7")

    a = await incidents.create(ctx, **args, idempotency_key="run-1")
    b = await incidents.create(ctx, **args, idempotency_key="run-2")

    assert a["id"] != b["id"]
    assert len(incidents._STUB_ROWS) == 2


async def test_idempotency_is_scoped_per_tenant():
    """Two tenants sending identical content must not collide."""
    from mcp_server.tools import incidents

    incidents._STUB_ROWS.clear()
    args = dict(title="same", severity="sev4", summary="text")
    a = await incidents.create(_ctx(tenant="flight-ops", roles=("incident.writer",)), **args)
    b = await incidents.create(_ctx(tenant="ground-ops", roles=("incident.writer",)), **args)

    assert a["id"] != b["id"]
    assert len(incidents._STUB_ROWS) == 2


async def test_oversized_idempotency_key_rejected():
    from mcp_server.tools import incidents

    incidents._STUB_ROWS.clear()
    ctx = _ctx(roles=("incident.writer",))
    with pytest.raises(ValueError, match="idempotency key too long"):
        await incidents.create(
            ctx, title="t", severity="sev4", summary="s", idempotency_key="x" * 500
        )
