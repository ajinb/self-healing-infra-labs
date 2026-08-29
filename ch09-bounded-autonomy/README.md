# Chapter 9 — Bounded Autonomy in Practice (Lab)

Companion code for *Self-Healing Infrastructure* Chapter 9. An autonomy
contract built from three pieces: an OPA policy bundle, a Redis-backed
kill-switch, and a FastAPI approval queue. Wraps the Chapter 8 remediator
without modifying it.

## What it does

- **OPA policy bundle** (`policies/autonomy.rego`) encoding the five-input/
  four-output decision contract from Chapter 9
- **Kill-switch service** with three scopes (action, tenant, global) and
  four-eyes recovery for the global switch
- **Approval queue** with time-boxed (15 min default) approvals that
  default-deny on timeout
- **PolicyRunner** that wraps `Runner` from Ch 8 — order of operations is
  kill-switch → policy → runner, because that is the order in which each
  layer's failure is the most expensive

## Layout

```
ch09-bounded-autonomy/
├── src/autonomy/
│   ├── models.py           # Typed PolicyInput, PolicyDecision (the OPA contract)
│   ├── opa_client.py       # HTTP client to the OPA sidecar; default-deny on unreachable
│   ├── kill_switch.py      # Redis-backed; per-action / per-tenant / global scopes
│   ├── approval.py         # FastAPI service + Redis queue; default-deny on timeout
│   └── policy_runner.py    # Wraps Ch 8 Runner with the autonomy layer
├── policies/
│   ├── autonomy.rego       # The autonomy bundle
│   └── tests/              # OPA unit tests for the bundle
├── fixtures/
│   └── docker-compose.yaml # OPA + Redis + the approval-queue service
├── tests/                  # Python unit tests with fakeredis + a fake OPA
└── pyproject.toml
```

## Quick start

The Python tests run without infrastructure (fakeredis + a fake OPA):

```bash
cd ch09-bounded-autonomy
uv sync --extra dev
uv run pytest -q
```

The OPA bundle has its own Rego unit tests (run with the OPA binary):

```bash
opa test policies/
```

For integration runs against real OPA + Redis:

```bash
docker compose -f fixtures/docker-compose.yaml up -d
# Wire your PolicyRunner with OPAClient(base_url="http://localhost:8181"),
# KillSwitch(redis.from_url("redis://localhost:6379")), and an
# ApprovalQueue.
```

## Reading the policy

`policies/autonomy.rego` implements the chapter's five-input/four-output
contract. Default deny is the floor; every rule that matches returns
`{effect, reason, constraints}`. The bundle version is read from OPA's
`/v1/data/system/bundles` endpoint and stamped onto every audit event so a
regulator's "what authorized this" question has a one-line answer.

## Reading the policy_runner

`PolicyRunner.execute` enforces the order of operations. Read it as a
contract:

1. Kill-switch checks (global → tenant → action). Sub-millisecond. Refuses
   immediately if any scope is tripped.
2. Build `PolicyInput` from runner-supplied call-site facts and the Ch 8
   ledger.
3. Evaluate against OPA. Default-deny if OPA is unreachable.
4. Route on the decision: `deny` → refuse with reason; `require_approval`
   → enqueue and refuse; `allow` → apply constraints and delegate to the
   Ch 8 runner.

The Ch 8 runner's contract did not change. Only what it is allowed to do
did.

## Production porting

| Concern | Lab | Production |
|---|---|---|
| Policy distribution | Static `--bundle` to OPA | OPAL or OCI bundles for live updates |
| Kill-switch backend | Local Redis / fakeredis | ElastiCache / Memorystore (clustered) |
| Approval surface | FastAPI + curl | Slack interactive / PagerDuty / ServiceNow |
| Policy CI | `opa test policies/` | Conftest in PR pipeline + bundle signing |

## License

Apache-2.0 for code in `src/`, `tests/`, `policies/`, `fixtures/`.
Manuscript prose is separately licensed; see top-level `LICENSE`.
