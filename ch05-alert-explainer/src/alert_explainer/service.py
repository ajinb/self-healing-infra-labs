"""The enrichment service.

Four stages, each with its own failure behaviour: ingress -> context ->
structured triage -> routing. The invariant that matters more than any of
them: an alert always leaves this service, enriched or not.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI

from .breaker import BreakerOpen, model_breaker
from .config import settings
from .context import ContextBudgetExceeded, gather_context
from .render import render_for_pagerduty
from .schema import Alert, AlertmanagerPayload, TriageBrief

log = structlog.get_logger()
app = FastAPI(title="alert-explainer")

SYSTEM_PROMPT = """You are triaging a production alert for an on-call engineer.
Use only the supplied context. If the context does not support a conclusion, say
so and set confidence to "low" rather than guessing. Never invent a runbook."""


def _model_client():
    """Constructed lazily so the service imports without an API key present."""
    from anthropic import AsyncAnthropic

    return AsyncAnthropic()


@app.get("/healthz")
async def healthz() -> dict:
    """The enricher's own health is a self-healing trigger (WAF anchor)."""
    return {"status": "ok", "breaker_open": model_breaker._is_open()}


@app.post("/enrich")
async def enrich(payload: AlertmanagerPayload) -> dict:
    out = []
    for alert in payload.alerts:
        try:
            context = await gather_context(alert)
            brief = await _triage(alert, context)
            out.append(render_for_pagerduty(alert, brief))
        except BreakerOpen:
            log.warning("breaker_open_passthrough", alert=alert.name)
            out.append(render_for_pagerduty(alert, brief=None))
        except ContextBudgetExceeded as e:
            # Refuse the call rather than truncate; page with the raw alert.
            log.warning("context_budget_exceeded", alert=alert.name, error=str(e))
            out.append(render_for_pagerduty(alert, brief=None))
        except Exception as e:  # noqa: BLE001 - deliberate catch-all
            # Any unexpected failure degrades to passthrough. The alert is the
            # product; the enrichment is the optional part. Narrowing this
            # would mean some unanticipated exception drops the page, which is
            # the one outcome this service exists to prevent.
            log.error("enrichment_failed_passthrough", alert=alert.name, error=str(e))
            out.append(render_for_pagerduty(alert, brief=None))
    return {"enriched": out}


async def _triage(alert: Alert, context: dict) -> TriageBrief:
    resp = await model_breaker.call(
        _model_client().messages.create,
        model=settings.TRIAGE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[TriageBrief.as_tool_schema()],
        tool_choice={"type": "tool", "name": "TriageBrief"},
        messages=[{"role": "user", "content": _format(alert, context)}],
    )
    return TriageBrief.model_validate(resp.content[0].input)


def _format(alert: Alert, context: dict) -> str:
    import json

    return (
        f"ALERT\n{alert.model_dump_json(indent=2)}\n\n"
        f"CONTEXT\n{json.dumps(context, indent=2)}"
    )
