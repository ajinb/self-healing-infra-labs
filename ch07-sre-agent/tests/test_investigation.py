"""Tests for the multi-agent investigation.

The properties worth pinning are the bounds: what the agent may call, what
happens when workers fail, and the guarantee that nothing here executes a
remediation.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from sre_agent.agentops import TRACE
from sre_agent.config import settings
from sre_agent.gate import RemediationRefused, authorize_write, render_for_oncall
from sre_agent.mcp_client import ToolNotPermitted, session
from sre_agent.scheduler import execute
from sre_agent.schema import (
    AlertContext,
    ChainBudgetExceeded,
    Hypothesis,
    InvestigationFailed,
    InvestigationPlan,
    RetrievalResult,
    SubTask,
)
from sre_agent.supervisor import InvalidPlan, preflight_tokens, validate_plan
from sre_agent.tools import ToolClass, classify_tool, is_permitted
from sre_agent.workers import retrieval


def trace_step_wrap(fn):
    """Apply the production decorator to a test double, so the trace behaves
    exactly as it does in the real worker."""
    from sre_agent.agentops import trace_step

    return trace_step("worker.retrieval")(fn)


ALERT = AlertContext(alert_name="HighErrorRate", severity="sev2", service="payments-api")


@pytest.fixture(autouse=True)
def _clean_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def _plan(tools=("runbooks.search", "deploys.recent"), **kw):
    return InvestigationPlan(
        alert=ALERT,
        retrieval_subtasks=[SubTask(id=f"r{i}", tool=t) for i, t in enumerate(tools)],
        diagnosis_subtask_id="d0",
        deadline_ms=kw.get("deadline_ms", 16_000),
        cost_ceiling_usd=kw.get("cost_ceiling_usd", 0.15),
    )


def _hypothesis():
    return Hypothesis(
        probable_cause="Deploy a3f9c2 introduced a regression.",
        confidence="medium",
        supporting_evidence=["deploy at 02:58 precedes the error spike"],
        verification_steps=["Diff a3f9c2", "Compare error ratio pre/post"],
    )


# --- the bright line: no remediation ----------------------------------------

@pytest.mark.parametrize("tool", [
    "pod.restart", "deploy.rollback", "hpa.scale", "db.drop",
    "pager.notify", "terraform.apply", "incidents.create",
])
def test_remediation_and_paging_tools_are_forbidden(tool):
    assert classify_tool(tool) is ToolClass.FORBIDDEN
    assert not is_permitted(tool)


@pytest.mark.parametrize("tool", ["pr.draft", "ticket.queue", "chat.notify"])
def test_only_queued_writes_are_authorised(tool):
    assert classify_tool(tool) is ToolClass.QUEUED_WRITE
    authorize_write(tool)          # does not raise


@pytest.mark.parametrize("tool", ["pod.restart", "deploy.rollback", "runbooks.search"])
def test_authorize_write_refuses_everything_else(tool):
    with pytest.raises(RemediationRefused):
        authorize_write(tool)


def test_a_plan_naming_a_forbidden_tool_fails_to_validate():
    """Enforced at parse time, so a bad plan never reaches a worker."""
    with pytest.raises(ValidationError):
        SubTask(id="r0", tool="pod.restart")


async def test_the_client_refuses_forbidden_tools_even_if_a_plan_slipped_through():
    """Second enforcement point, in case a plan was built some other way."""
    async with session({}) as s:
        with pytest.raises(ToolNotPermitted):
            await s.call("deploy.rollback", {})


# --- plan bounds are enforced, not requested --------------------------------

def test_plan_within_bounds_validates():
    assert validate_plan(_plan()) is not None


def test_too_many_retrieval_subtasks_is_rejected():
    tools = ("runbooks.search", "deploys.recent", "incidents.search", "metrics.query")
    with pytest.raises(InvalidPlan):
        validate_plan(_plan(tools=tools))


def test_queued_write_tool_is_rejected_in_a_retrieval_subtask():
    """pr.draft is allowlisted overall but is not a retrieval tool."""
    with pytest.raises(InvalidPlan):
        validate_plan(_plan(tools=("runbooks.search", "pr.draft")))


def test_duplicate_subtask_ids_are_rejected():
    p = _plan()
    p.retrieval_subtasks[1].id = p.retrieval_subtasks[0].id
    with pytest.raises(InvalidPlan):
        validate_plan(p)


def test_deadline_and_cost_ceilings_are_enforced():
    with pytest.raises(InvalidPlan):
        validate_plan(_plan(deadline_ms=60_000))
    with pytest.raises(InvalidPlan):
        validate_plan(_plan(cost_ceiling_usd=5.0))


def test_chain_token_preflight_refuses_rather_than_truncates():
    with pytest.raises(ChainBudgetExceeded):
        preflight_tokens("x" * (settings.MAX_CHAIN_TOKENS * 4 + 100))


# --- partial failure is the interesting path --------------------------------

async def _fake_diagnose(results, alert, *, partial=False):
    return _hypothesis()


async def test_two_of_three_workers_succeeding_still_produces_a_diagnosis(monkeypatch):
    real_run = retrieval.run

    async def flaky(subtask, ctx):
        if subtask.tool == "incidents.search":
            raise ConnectionError("worker died")
        return await real_run(subtask, ctx)

    monkeypatch.setattr(retrieval, "run", flaky)
    plan = _plan(tools=("runbooks.search", "deploys.recent", "incidents.search"))

    inv = await execute(plan, {}, diagnose=_fake_diagnose)

    assert len(inv.results) == 2
    assert inv.partial is True


async def test_all_workers_failing_raises_rather_than_guessing(monkeypatch):
    async def dead(subtask, ctx):
        raise ConnectionError("gateway down")

    monkeypatch.setattr(retrieval, "run", dead)
    with pytest.raises(InvestigationFailed):
        await execute(_plan(), {}, diagnose=_fake_diagnose)


async def test_full_success_is_not_marked_partial():
    inv = await execute(_plan(), {}, diagnose=_fake_diagnose)
    assert inv.partial is False
    assert len(inv.results) == 2


async def test_retrieval_runs_in_parallel_not_serially():
    """gather, not a loop — one slow worker must not stall the investigation."""
    async def slow(subtask, ctx):
        await asyncio.sleep(0.05)
        return RetrievalResult(subtask_id=subtask.id, raw={})

    import sre_agent.scheduler as sched
    original = sched.retrieval.run
    sched.retrieval.run = slow
    try:
        started = asyncio.get_event_loop().time()
        await execute(_plan(tools=("runbooks.search", "deploys.recent", "metrics.query")),
                      {}, diagnose=_fake_diagnose)
        elapsed = asyncio.get_event_loop().time() - started
    finally:
        sched.retrieval.run = original
    assert elapsed < 0.14, f"three 50ms workers took {elapsed:.3f}s — likely serial"


# --- tracing ----------------------------------------------------------------

async def test_every_worker_step_is_traced():
    await execute(_plan(), {}, diagnose=_fake_diagnose)
    assert TRACE.names().count("worker.retrieval") == 2


async def test_failed_steps_are_traced_with_the_error():
    """An untraced failure is a worker that silently contributed nothing.

    Exercises the decorator directly: patching retrieval.run would replace the
    very wrapper under test.
    """
    from sre_agent.agentops import trace_step

    @trace_step("worker.exploding")
    async def explode():
        raise ConnectionError("gateway down")

    with pytest.raises(ConnectionError):
        await explode()

    step = next(s for s in TRACE.steps if s.name == "worker.exploding")
    assert step.ok is False
    assert "gateway down" in (step.error or "")


async def test_a_failing_worker_still_appears_in_the_trace():
    """The real path: one worker raises, and the investigation can still show
    which one, because the decorator recorded it before re-raising."""
    async def flaky(subtask, ctx):
        if subtask.tool == "deploys.recent":
            raise ConnectionError("down")
        return RetrievalResult(subtask_id=subtask.id, raw={})

    import sre_agent.scheduler as sched
    original = sched.retrieval.run
    sched.retrieval.run = trace_step_wrap(flaky)
    try:
        await execute(_plan(), {}, diagnose=_fake_diagnose)
    finally:
        sched.retrieval.run = original

    named = [s for s in TRACE.steps if s.name == "worker.retrieval"]
    assert any(s.ok is False for s in named)
    assert any(s.ok is True for s in named)


# --- the gate ---------------------------------------------------------------

async def test_rendered_output_is_evidence_not_an_action():
    inv = await execute(_plan(), {}, diagnose=_fake_diagnose)
    out = render_for_oncall(inv)

    assert out["auto_executed"] is False
    assert out["requires_human_action"] is True
    assert "Verification steps" in out["brief"]
    assert out["raw"], "raw evidence must be preserved underneath the brief"


async def test_partial_investigations_say_so_to_the_oncall(monkeypatch):
    async def flaky(subtask, ctx):
        if subtask.tool == "deploys.recent":
            raise ConnectionError("down")
        return RetrievalResult(subtask_id=subtask.id, raw={})

    monkeypatch.setattr(retrieval, "run", flaky)
    inv = await execute(_plan(), {}, diagnose=_fake_diagnose)
    assert "partial evidence" in render_for_oncall(inv)["brief"]


def test_hypothesis_requires_evidence_and_verification_steps():
    with pytest.raises(ValidationError):
        Hypothesis(probable_cause="c", confidence="high",
                   supporting_evidence=[], verification_steps=[])
