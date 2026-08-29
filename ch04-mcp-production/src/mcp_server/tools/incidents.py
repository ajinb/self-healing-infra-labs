"""Sensitive (write) tool: create an incident.

Stricter validation than the read tool: every field is bounded at the tool
boundary even though the model already validated against the schema.
Defense-in-depth catches a buggy model and a poisoned schema.

Retry-safety is not optional here. MCP `2026-07-28` removed SSE stream
resumability (`Last-Event-ID` and event IDs): a broken response stream now
loses the in-flight request and the client MUST re-issue it as a new request.
Retry is therefore the *specified* recovery path, not an edge case — so a
write tool that is not idempotent will duplicate records the first time a
load balancer drops a long-running connection. Every write tool on this
server takes an idempotency key and returns the original result on replay.
"""

from __future__ import annotations

import hashlib

from ..auth import AuthContext


ALLOWED_SEVERITIES = {"sev1", "sev2", "sev3", "sev4"}
MAX_TITLE = 200
MAX_SUMMARY = 4000
MAX_IDEMPOTENCY_KEY = 200


async def create(
    ctx: AuthContext,
    *,
    title: str,
    severity: str,
    summary: str,
    idempotency_key: str | None = None,
) -> dict:
    """Create an incident, at most once per idempotency key.

    `idempotency_key` is optional on the wire. When the caller omits it we
    derive one from the tenant, the acting subject, and a hash of the content,
    so an unmodified retry collapses onto the same key. A caller that wants two
    genuinely distinct incidents with identical content must pass distinct
    keys — that is the trade this design makes, and it is the right way round:
    a duplicated incident is noise a human has to clean up, while a suppressed
    duplicate is one the caller can always force through.
    """
    if severity not in ALLOWED_SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(ALLOWED_SEVERITIES)}")
    if len(title) > MAX_TITLE or len(summary) > MAX_SUMMARY:
        raise ValueError("input too long")
    if idempotency_key is not None and len(idempotency_key) > MAX_IDEMPOTENCY_KEY:
        raise ValueError("idempotency key too long")

    key = idempotency_key or derive_idempotency_key(ctx, title, severity, summary)

    existing = await _db_lookup_by_key(ctx.tenant, key)
    if existing is not None:
        # Replay of a request we already committed. Return the original result
        # and mark it, so the audit trail distinguishes "created" from
        # "returned an earlier creation" rather than showing two writes.
        return {**existing, "idempotent_replay": True}

    incident_id = await _db_insert(
        "INSERT INTO incidents "
        "(tenant, title, severity, summary, created_by, idempotency_key) "
        "VALUES ($1, $2, $3, $4, $5, $6) "
        "ON CONFLICT (tenant, idempotency_key) DO NOTHING "
        "RETURNING id",
        ctx.tenant,
        title,
        severity,
        summary,
        ctx.sub,
        key,
    )

    if incident_id is None:
        # Lost a race with a concurrent retry: the unique constraint rejected
        # the insert. The winner's row is authoritative, so read it back rather
        # than reporting a failure the caller cannot act on.
        existing = await _db_lookup_by_key(ctx.tenant, key)
        if existing is None:  # pragma: no cover - only on constraint misconfiguration
            raise RuntimeError("insert conflicted but no row found for idempotency key")
        return {**existing, "idempotent_replay": True}

    return {
        "id": incident_id,
        "title": title,
        "severity": severity,
        "idempotent_replay": False,
    }


def derive_idempotency_key(
    ctx: AuthContext, title: str, severity: str, summary: str
) -> str:
    """Stable key for an unmodified retry by the same subject in the same tenant."""
    return "auto:" + hashlib.sha256(
        "|".join([ctx.tenant, ctx.sub, title, severity, summary]).encode()
    ).hexdigest()


def hash_input(title: str, severity: str, summary: str) -> str:
    return "sha256:" + hashlib.sha256(f"{title}|{severity}|{summary}".encode()).hexdigest()


# --- storage stubs; replace with a real DB adapter --------------------------
# The unique constraint is what actually enforces idempotency under concurrency:
#   ALTER TABLE incidents ADD CONSTRAINT incidents_tenant_idem
#     UNIQUE (tenant, idempotency_key);
# Application-level checking alone races; the constraint is the guarantee.

_STUB_ROWS: dict[tuple[str, str], dict] = {}


async def _db_lookup_by_key(tenant: str, key: str) -> dict | None:
    """Stub. Replace with: SELECT id, title, severity FROM incidents
    WHERE tenant = $1 AND idempotency_key = $2."""
    return _STUB_ROWS.get((tenant, key))


async def _db_insert(sql: str, *args) -> str | None:
    """Stub. Replace with real DB adapter.

    Returns None when ON CONFLICT DO NOTHING suppressed the insert, which is
    how the caller detects a concurrent retry.
    """
    tenant, title, severity, _summary, _sub, key = args
    if (tenant, key) in _STUB_ROWS:
        return None
    incident_id = f"inc-stub-{abs(hash((tenant, key))) % 100000}"
    _STUB_ROWS[(tenant, key)] = {
        "id": incident_id,
        "title": title,
        "severity": severity,
    }
    return incident_id
