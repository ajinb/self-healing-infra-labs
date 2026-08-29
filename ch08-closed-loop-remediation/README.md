# Chapter 8 — Closed-Loop Remediation (Lab)

Companion code for *Self-Healing Infrastructure* Chapter 8. A bounded
remediator that takes recommendations from `sre-agent` (Chapter 7), runs
them through a four-step closed loop — gate, act, verify, audit — and
records every action against a structured outcome.

## What it does

- Wraps the supervisor's recommendation in the **Reversibility Gate** from
  Chapter 0
- Executes one of three action handlers: `pod_restart`, `scale`, `rollback`
- Verifies the action via a probe-poll against the relevant signal
- Rolls back on probe failure using the inverse handler registry
- Emits a single structured `AuditEvent` per action with one of seven
  terminal outcomes

## Layout

```
ch08-closed-loop-remediation/
├── src/remediator/
│   ├── reversibility.py    # Reversibility enum, decorator, per-call adjuster
│   ├── context.py          # ActionContext, AuditEvent
│   ├── ledger.py           # Last-100 action breadcrumbs (storm + rollback support)
│   ├── verifier.py         # Pluggable post-action probes
│   ├── runner.py           # The orchestrator: gate → act → verify → audit
│   └── handlers/
│       ├── restart.py      # Pod restart with readiness verification
│       ├── scale.py        # HPA scale-out + scale-in (RECOVERABLE) inverse
│       └── rollback.py     # Deploy rollback with error-rate verification
├── fixtures/
│   ├── docker-compose.yaml # kind cluster + Prometheus (integration runs)
│   └── scenarios/          # Workload manifests for each scenario
├── tests/                  # Unit + scenario tests with fake K8s client
└── pyproject.toml
```

## Quick start

The unit and scenario tests run without a cluster — they use a fake
Kubernetes client (`tests/conftest.py`).

```bash
cd ch08-closed-loop-remediation
uv sync --extra dev
uv run pytest -q
```

For integration runs against a real kind cluster:

```bash
docker compose -f fixtures/docker-compose.yaml up -d
# Wire src/remediator/handlers/*.install() with kubernetes.client.AppsV1Api()
uv run python -m remediator.runner --dry-run examples/recommendation.json
```

## Reading the runner

`Runner.execute` in `src/remediator/runner.py` is the chapter in 100 lines.
The four steps are numbered in comments. Read it as a contract: every
mutating action passes through this method, and every action emits exactly
one `AuditEvent` with a terminal outcome from this set:

- `ok` — action executed and verifier passed
- `rolled_back` — action executed, verifier failed, inverse handler ran
- `dry_run_ok` — full call path completed without mutation
- `refused` — gate or safety bound rejected the call
- `refused_human_required` — gate refused; queued for human review
- `action_failed` — handler raised before mutation completed

## Production porting

The lab is intentionally minimal — the seed for the policy work in Chapter 9,
not a competitor to a workflow engine. Three swaps for production:

| Concern | Lab | Production |
|---|---|---|
| K8s API client | `tests/conftest.FakeK8s` | `kubernetes.client.AppsV1Api()` |
| Audit sink | `MemorySink` | S3 with Object Lock (per Ch 4 pattern) |
| Verifier probes | Synchronous polling | Prometheus / Datadog / your APM |

Production deployments fork this and graduate to Argo Rollouts, Flagger,
Crossplane, or a custom controller. What they keep is the runner contract
and the four containment patterns (action storms, oscillation, rollback
chains, stale diagnosis).

## License

Apache-2.0 for code in `src/`, `tests/`, `fixtures/`. Manuscript prose is
separately licensed; see top-level `LICENSE`.
