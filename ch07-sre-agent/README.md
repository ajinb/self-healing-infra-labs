# Chapter 7 — Multi-agent investigation (Lab)

Companion code for *Self-Healing Infrastructure* Chapter 7. A supervisor plans,
retrieval workers execute in parallel, a diagnosis worker synthesises, and a
human acts. Every tool call goes through the Chapter 4 MCP gateway; every step
is traced.

## The bright line

**This system never closes the loop on disruptive remediation.** It produces
better evidence faster; the human still does the thing that touches production.

That is enforced in three places, not asserted in a prompt:

1. `tools.py` classifies every tool as `READ`, `QUEUED_WRITE`, or `FORBIDDEN`.
   Adding a capability means editing that file — which is the review you want
   the change to get.
2. `SubTask` rejects a forbidden tool **at parse time**, so a bad plan never
   reaches a worker.
3. `mcp_client` refuses again **at call time**, in case a plan was constructed
   some other way.

`QUEUED_WRITE` covers exactly three tools — `pr.draft`, `ticket.queue`,
`chat.notify` — because a human still merges, triages, or reads the result.
Anything that executes, pages, or mutates production is `FORBIDDEN`.

## Layout

```
ch07-sre-agent/
├── src/sre_agent/
│   ├── tools.py        # the allowlist — the bright line, as data
│   ├── schema.py       # inter-agent contracts; SubTask enforces the allowlist
│   ├── supervisor.py   # planning + bound enforcement (validate_plan)
│   ├── scheduler.py    # asyncio dispatcher; parallel retrieval, partial failure
│   ├── workers/        # retrieval (trivial by design) + diagnosis
│   ├── gate.py         # human-review gate; render_for_oncall, authorize_write
│   ├── agentops.py     # step tracing, including failures
│   └── mcp_client.py   # Ch 4 gateway client, with a fixture-replaying mock
├── fixtures/mcp/       # recorded tool responses
└── tests/
```

## Quick start

Runs with no infrastructure and no API key — `MCP_ENDPOINT` defaults to `mock`
and the scheduler takes an injectable `diagnose`, so the failure paths are
testable without model calls:

```bash
python3.12 -m venv ~/.venvs/ch07-sre-agent
~/.venvs/ch07-sre-agent/bin/pip install pydantic pydantic-settings structlog \
    httpx pytest pytest-asyncio
~/.venvs/ch07-sre-agent/bin/python -m pytest -q
```

Do not create the venv inside this directory — the repo is under an
iCloud-synced path, which breaks editable installs.

## Bounds the prompt asks for and the code enforces

The supervisor prompt requests ≤3 retrieval subtasks, one diagnosis, no
remediation, and a deadline and cost ceiling. `validate_plan` makes those true:

| Bound | Enforced by |
|---|---|
| ≤ 3 retrieval subtasks | `validate_plan` |
| Retrieval uses read tools only | `validate_plan` (`pr.draft` is allowlisted but not a retrieval tool) |
| No duplicate subtask ids | `validate_plan` |
| Deadline ≤ 16s, cost ≤ $0.15 | `validate_plan` |
| Chain context ≤ 8K tokens | `preflight_tokens` — **refuses**, never truncates |

## Partial failure is the interesting path

If two of three retrieval workers succeed, diagnosis still runs — and the chain
tells the model its evidence is incomplete so the confidence it reports means
something. Only total retrieval failure raises. One slow or broken worker must
not stall an investigation an on-call engineer is waiting on.

`render_for_oncall` marks partial investigations explicitly, because a
confident-looking brief built on half the evidence is worse than an obviously
incomplete one.

## Budget (Chapter 7)

| Stage | Latency | Cost |
|---|---|---|
| Supervisor plan | 4s | $0.04 |
| Retrieval ×3 (parallel) | 4s | $0.06 |
| Diagnosis | 6s | $0.05 |
| MCP overhead | 2s | — |
| **Total** | **≤ 16s** | **≤ $0.15** |

This is the most expensive lab in the book. Set a hard spend cap on the API key
before the first live run.

## License

Apache-2.0.
