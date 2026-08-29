"""The dispatcher.

Python asyncio, not an LLM. It enforces parallelism, captures partial failures,
and raises only when nothing succeeded. Using a model here would add a
non-deterministic failure mode to the one component that should be boring.
"""

from __future__ import annotations

import asyncio

import structlog

from .schema import (
    Investigation,
    InvestigationFailed,
    InvestigationPlan,
    RetrievalResult,
)
from .workers import diagnosis, retrieval

log = structlog.get_logger()


async def execute(plan: InvestigationPlan, ctx: dict, *, diagnose=None) -> Investigation:
    """Run the plan: retrieval in parallel, then a single diagnosis.

    `diagnose` is injectable so the scheduler's failure handling can be tested
    without a model call — the partial-context path is the one worth pinning.
    """
    tasks = [asyncio.create_task(retrieval.run(s, ctx)) for s in plan.retrieval_subtasks]
    settled = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[RetrievalResult] = []
    failures = 0
    for outcome in settled:
        if isinstance(outcome, BaseException):
            failures += 1
            log.warning("retrieval_worker_failed", error=str(outcome))
        else:
            results.append(outcome)

    if not results:
        # Total failure is the only fatal case. One slow or broken worker must
        # not stall an investigation the on-call is waiting on.
        raise InvestigationFailed("all retrieval workers failed")

    partial = failures > 0
    if partial:
        log.info("diagnosing_on_partial_context", failed=failures, succeeded=len(results))

    run_diagnosis = diagnose or diagnosis.run
    hypothesis = await run_diagnosis(results, plan.alert, partial=partial)

    return Investigation(plan=plan, results=results, hypothesis=hypothesis, partial=partial)
