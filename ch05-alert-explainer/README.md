# Chapter 5 — Alert enrichment (Lab)

Companion code for *Self-Healing Infrastructure* Chapter 5. Turns the
exploratory CLI into a service: webhook ingress, MCP-backed context retrieval,
schema-constrained triage output, and — the part that matters — a deterministic
fallback that keeps paging when the model provider is down.

## The invariant

**An alert always leaves this service.** Enriched if everything worked, raw if
anything did not. The on-call may lose the triage brief; they never lose the
page. Every failure path in `service.py` ends in `render_for_pagerduty(alert,
brief=None)` for that reason.

## Layout

```
ch05-alert-explainer/
├── src/alert_explainer/
│   ├── schema.py     # Alert, AlertmanagerPayload, TriageBrief (tool-schema constrained)
│   ├── context.py    # Stage 2 — retrieval via the Ch 4 MCP surface, budget-guarded
│   ├── breaker.py    # async circuit breaker around the model call
│   ├── render.py     # Stage 4 — brief on top, raw underneath
│   ├── service.py    # FastAPI app: ingress -> context -> triage -> routing
│   └── config.py     # every knob the SLO targets depend on
├── fixtures/         # recorded Alertmanager payload + context, so no live Prometheus needed
└── tests/            # the fail-closed suite
```

## Quick start

Runs with no infrastructure: `MCP_ENDPOINT` defaults to `mock`, which replays
`fixtures/context/`.

```bash
python3.12 -m venv ~/.venvs/ch05-alert-explainer
~/.venvs/ch05-alert-explainer/bin/pip install fastapi pydantic pydantic-settings \
    structlog httpx pytest pytest-asyncio
~/.venvs/ch05-alert-explainer/bin/python -m pytest -q
```

Do not create the venv inside this directory — the repo lives under an
iCloud-synced path, which breaks editable installs. `pythonpath = ["src"]` in
`pyproject.toml` is what makes the src layout importable without one.

To run the service:

```bash
uvicorn alert_explainer.service:app --port 8081     # PYTHONPATH=src
curl -sX POST localhost:8081/enrich -H 'content-type: application/json' \
     -d @fixtures/alertmanager.json | jq
```

## Wiring to Chapter 4

Set `MCP_ENDPOINT` to the Ch 4 gateway to retrieve real runbooks and deploys.
Every retrieval then carries the caller's delegated identity and is authorised,
rate-limited, and audited by the gateway — which is the point of having built
it. With `MCP_ENDPOINT=mock` the pipeline still exercises every stage, so the
fail-closed tests are meaningful without the fixture running.

## SLO targets (Chapter 5)

| Target | Value |
|---|---|
| Median enrichment latency | < 4s (1.5s context + 2.5s model) |
| P99 latency cap | 12s |
| Cost per alert | ~$0.005 warm-cache, ~$0.01 cold-cache |
| Availability | 99.5% over 30 days, failing to passthrough |

`MAX_CONTEXT_TOKENS` is a **pre-flight refusal**, not a truncation. Truncating
context produces a confident answer built on whichever half happened to fit.

## Relationship to `ajinb/alert-explainer`

The standalone repo at <https://github.com/ajinb/alert-explainer> is the
general-purpose tool. This directory is the book's version: the same idea
reduced to the pieces Chapter 5 argues about, wired to the Chapter 4 MCP
surface, with the fail-closed behaviour as the headline test.

## License

Apache-2.0, as with all lab code in this book.
