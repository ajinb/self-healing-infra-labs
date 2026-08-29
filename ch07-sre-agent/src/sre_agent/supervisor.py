"""The supervisor — planning only.

It decides; the workers execute. Every degree of freedom given to a worker is a
way the worker can be wrong, so the plan is where the thinking happens and the
workers stay trivial.
"""

from __future__ import annotations

import json

from .agentops import trace_step
from .config import settings
from .schema import AlertContext, ChainBudgetExceeded, InvestigationPlan
from .tools import ToolClass, classify_tool

SUPERVISOR_PROMPT = """You are the supervisor of an SRE investigation.
Given an alert, produce a plan with:
- 1-3 retrieval sub-tasks (runbooks, similar incidents, recent deploys)
- exactly 1 diagnosis sub-task that consumes the retrieval results
- chain-wide deadline <= 30 seconds, cost ceiling <= $0.25
Do not include remediation sub-tasks. The platform humans take all actions.
Do not invent tools. Use only the tools listed in `available_tools`.
"""


class InvalidPlan(Exception):
    """The plan violated a bound the prompt merely asked for."""


def validate_plan(plan: InvestigationPlan) -> InvestigationPlan:
    """Enforce what the prompt requests.

    The prompt asks for <=3 retrieval subtasks and no remediation. This makes
    those properties true rather than requested — the difference between a
    guideline and a control.
    """
    n = len(plan.retrieval_subtasks)
    if n > settings.MAX_RETRIEVAL_SUBTASKS:
        raise InvalidPlan(f"{n} retrieval subtasks exceeds {settings.MAX_RETRIEVAL_SUBTASKS}")

    ids = [s.id for s in plan.retrieval_subtasks]
    if len(set(ids)) != len(ids):
        raise InvalidPlan("duplicate subtask ids")

    for s in plan.retrieval_subtasks:
        if classify_tool(s.tool) is not ToolClass.READ:
            raise InvalidPlan(f"retrieval subtask may only use read tools, got {s.tool!r}")

    if plan.deadline_ms > settings.CHAIN_DEADLINE_MS:
        raise InvalidPlan(f"deadline {plan.deadline_ms}ms exceeds chain budget")
    if plan.cost_ceiling_usd > settings.COST_CEILING_USD:
        raise InvalidPlan(f"cost ceiling ${plan.cost_ceiling_usd} exceeds chain budget")
    return plan


def preflight_tokens(payload: str) -> None:
    """Refuse rather than truncate. A truncated chain produces a confident
    diagnosis built on whichever evidence happened to fit."""
    estimated = len(payload) // 4
    if estimated > settings.MAX_CHAIN_TOKENS:
        raise ChainBudgetExceeded(
            f"chain context ~{estimated} tokens exceeds {settings.MAX_CHAIN_TOKENS}"
        )


def format_alert(alert: AlertContext, deadline_ms: int, available_tools: list[str]) -> str:
    return json.dumps(
        {
            "alert": alert.model_dump(),
            "deadline_ms": deadline_ms,
            "available_tools": available_tools,
        },
        indent=2,
    )


@trace_step("supervisor.plan")
async def plan(alert: AlertContext, deadline_ms: int) -> InvestigationPlan:  # pragma: no cover
    from anthropic import AsyncAnthropic

    from .tools import READ_TOOLS

    claude = AsyncAnthropic()
    payload = format_alert(alert, deadline_ms, sorted(READ_TOOLS))
    preflight_tokens(payload)

    resp = await claude.messages.create(
        model=settings.PLANNING_MODEL,
        max_tokens=1024,
        system=SUPERVISOR_PROMPT,
        tools=[InvestigationPlan.as_tool_schema()],
        tool_choice={"type": "tool", "name": "InvestigationPlan"},
        messages=[{"role": "user", "content": payload}],
    )
    return validate_plan(InvestigationPlan.model_validate(resp.content[0].input))
