"""Inter-agent contracts.

Every hop between agents is schema-constrained. A free-text handoff is where a
multi-agent system quietly turns into a game of telephone.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .tools import is_permitted


class AlertContext(BaseModel):
    alert_name: str
    severity: str
    service: str
    summary: str = ""
    fired_at: str | None = None


class SubTask(BaseModel):
    id: str
    tool: str
    args: dict = Field(default_factory=dict)

    @field_validator("tool")
    @classmethod
    def _tool_must_be_allowlisted(cls, v: str) -> str:
        """Enforced at parse time.

        The supervisor's prompt also says not to invent tools, but a prompt is
        not an enforcement point. A plan naming a forbidden tool fails to
        validate and never reaches a worker.
        """
        if not is_permitted(v):
            raise ValueError(f"tool {v!r} is not on the allowlist")
        return v


class InvestigationPlan(BaseModel):
    alert: AlertContext
    retrieval_subtasks: list[SubTask] = Field(min_length=1)
    diagnosis_subtask_id: str
    deadline_ms: int
    cost_ceiling_usd: float

    @classmethod
    def as_tool_schema(cls) -> dict:
        return {
            "name": "InvestigationPlan",
            "description": "A bounded investigation plan. Retrieval then diagnosis. No remediation.",
            "input_schema": cls.model_json_schema(),
        }


class RetrievalResult(BaseModel):
    subtask_id: str
    raw: dict | list | str


class Hypothesis(BaseModel):
    probable_cause: str
    confidence: Literal["high", "medium", "low"]
    supporting_evidence: list[str] = Field(min_length=1)
    verification_steps: list[str] = Field(
        min_length=1,
        description="Checks the on-call runs. Never remediation actions.",
    )
    unknowns: list[str] = Field(default_factory=list)

    @classmethod
    def as_tool_schema(cls) -> dict:
        return {
            "name": "Hypothesis",
            "description": "A diagnosis grounded strictly in retrieved evidence.",
            "input_schema": cls.model_json_schema(),
        }


class Investigation(BaseModel):
    plan: InvestigationPlan
    results: list[RetrievalResult]
    hypothesis: Hypothesis
    partial: bool = Field(
        default=False,
        description="True when some retrieval workers failed and diagnosis ran on partial context.",
    )


class InvestigationFailed(Exception):
    """Raised when no retrieval worker produced a result."""


class ChainBudgetExceeded(Exception):
    """Pre-flight refusal. The on-call sees the raw alert, not a truncated one."""
