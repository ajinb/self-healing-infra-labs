# Chapter 4 — MCP in Production (Lab)

Companion code for *Self-Healing Infrastructure* Chapter 4. A production-grade Model Context Protocol server with OAuth 2.1 (Keycloak in-fixture, Okta/Entra/Auth0 in production), policy-driven RBAC, per-tenant rate limiting, and an append-only audit trail.

## Layout

```
ch04-mcp-production/
├── src/mcp_server/
│   ├── server.py     # FastMCP app + per-tool lifecycle (authorize → ratelimit → execute → audit)
│   ├── auth.py       # OAuth 2.1 JWT verification, JWKS cache, CABP AuthContext
│   ├── policy.py     # YAML-driven allow/deny per (tool, scope, tenant)
│   ├── ratelimit.py  # Redis sliding-window per-tenant per-tool
│   ├── audit.py      # Append-only structured events to S3 Object Lock
│   └── tools/
│       ├── runbooks.py    # safe (read-only) tool
│       └── incidents.py   # sensitive (write) tool with stricter validation
├── policies/
│   └── policy.yaml   # the policy bundle the YAML-first stance starts from
├── fixtures/
│   ├── docker-compose.yaml  # Keycloak + Redis + MinIO (with Object Lock)
│   └── keycloak-realm.json  # preconfigured realm for the lab
├── terraform/
│   └── main.tf       # S3 Object Lock + ECS Fargate (excerpt — full module in code/terraform/)
├── tests/
│   └── test_negative_cases.py  # the negative tests that matter
└── pyproject.toml
```

## Quick start

```bash
cd ch04-mcp-production
docker-compose -f fixtures/docker-compose.yaml up -d   # Keycloak + Redis + MinIO
uv sync
uv run pytest -q                                        # negative tests
uv run python -m mcp_server.server                      # serve on :8080
```

## Spec revision

The chapter targets MCP `2026-07-28`, which made the protocol stateless. This
lab is aligned with it where the alignment is ours to make, and blocked where
it is not. Being explicit about which is which:

**Done — and required by the new revision:**

- **Write tools are idempotent.** `2026-07-28` removed SSE stream resumability,
  so a dropped stream means the client re-issues the request. `incidents.create`
  takes an `idempotency_key`, derives one from tenant + subject + content when
  the caller omits it, and enforces uniqueness with `ON CONFLICT` on
  `UNIQUE (tenant, idempotency_key)`. The audit record distinguishes `success`
  from `idempotent_replay`.
- **No session state.** This server never used sessions, so removing
  protocol-level sessions and `Mcp-Session-Id` costs it nothing. The rate
  limiter keys on `(tenant, tool)`, not on a connection.
- **No deprecated features.** The server uses none of Sampling, Roots, or
  Logging, all deprecated in this revision.

**Blocked on the SDK, not on this code:**

The pinned FastMCP implements protocol `2025-06-18`; it has no `server/discover`,
no `InputRequiredResult`, and still carries session plumbing internally. These
are framework-owned parts of the protocol layer and cannot be implemented from
application code:

- `server/discover` (mandatory in `2026-07-28`)
- Removal of the `initialize` / `notifications/initialized` handshake, with
  protocol version and client capabilities moving into per-request `_meta`
- Multi Round-Trip Requests replacing server-initiated elicitation and sampling
- `ttlMs` / `cacheScope` on list results

Track FastMCP's protocol support and revisit when it ships `2026-07-28`. The
gateway's structure does not change when that lands — it was already stateless
— so the migration should be a dependency bump plus the removal of any
compatibility shims, not a redesign.

## Production porting

The Keycloak fixture is for local development and reproducibility. Three swaps for production:

| Concern | Fixture | Production |
|---|---|---|
| OAuth 2.1 IdP | Keycloak | Okta / Entra ID / Auth0 |
| Audit sink | MinIO with Object Lock | AWS S3 with Object Lock (compliance mode) |
| Rate-limit store | Local Redis | ElastiCache / Memorystore / shared Redis |

Each swap is a config-only change. See `docs/PRODUCTION_PORTING.md`.

## License

Apache-2.0 for code in `src/`, `tests/`, `fixtures/`, `terraform/`. Manuscript prose is separately licensed; see top-level `LICENSE`.
