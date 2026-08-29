"""The diagnosis worker.

Synthesises retrieved evidence into a hypothesis with verification steps. It
does not propose remediation — that boundary is what keeps the human review
gate meaningful rather than decorative.
"""

from __future__ import annotations

import json

from ..agentops import trace_step
from ..config import settings
from ..schema import AlertContext, Hypothesis, RetrievalResult

DIAGNOSIS_PROMPT = """You are the diagnosis agent. Given retrieval results,
produce a structured Hypothesis. Do not assert anything not supported by the
retrieved context. When uncertain, lower confidence. Output verification steps
the on-call engineer can run; do NOT propose remediation actions.
"""


def format_results(alert: AlertContext, results: list[RetrievalResult], *, partial: bool) -> str:
    body = {
        "alert": alert.model_dump(),
        "retrieval_results": [r.model_dump() for r in results],
    }
    if partial:
        # The chain tells the model its evidence is incomplete, so the
        # confidence it reports reflects what it actually had.
        body["note"] = (
            "Some retrieval subtasks failed. Evidence is incomplete; "
            "lower confidence accordingly and list what is missing in `unknowns`."
        )
    return json.dumps(body, indent=2)


@trace_step("worker.diagnosis")
async def run(  # pragma: no cover
    results: list[RetrievalResult], alert: AlertContext, *, partial: bool = False
) -> Hypothesis:
    from anthropic import AsyncAnthropic

    claude = AsyncAnthropic()
    resp = await claude.messages.create(
        model=settings.DIAGNOSIS_MODEL,
        max_tokens=1024,
        system=DIAGNOSIS_PROMPT,
        tools=[Hypothesis.as_tool_schema()],
        tool_choice={"type": "tool", "name": "Hypothesis"},
        messages=[{"role": "user", "content": format_results(alert, results, partial=partial)}],
    )
    return Hypothesis.model_validate(resp.content[0].input)
