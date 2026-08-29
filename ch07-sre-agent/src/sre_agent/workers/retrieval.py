"""The retrieval worker.

Intentionally trivial. It does not decide anything: it calls the tool the
supervisor selected, returns the result verbatim, exits.
"""

from __future__ import annotations

from ..agentops import trace_step
from ..mcp_client import session
from ..schema import RetrievalResult, SubTask

RETRIEVAL_PROMPT = """You are the retrieval agent. Given a sub-task, call the
specified MCP tool with the specified arguments. Return the result verbatim.
Do not synthesize. Do not summarize. Do not call additional tools.
"""


@trace_step("worker.retrieval")
async def run(subtask: SubTask, ctx: dict) -> RetrievalResult:
    async with session(ctx) as s:
        raw = await s.call(subtask.tool, subtask.args)
    return RetrievalResult(subtask_id=subtask.id, raw=raw)
