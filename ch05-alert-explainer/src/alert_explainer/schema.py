"""Wire schemas. The triage brief is schema-constrained on purpose: free text
does not survive contact with PagerDuty's parsing layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Alert(BaseModel):
    """One alert out of an Alertmanager webhook payload."""

    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str | None = None
    generatorURL: str | None = None

    @property
    def name(self) -> str:
        return self.labels.get("alertname", "UnknownAlert")

    @property
    def severity(self) -> str:
        return self.labels.get("severity", "unknown")

    def raw_text(self) -> str:
        """What the on-call sees when enrichment is unavailable."""
        summary = self.annotations.get("summary", "")
        return f"{self.name} [{self.severity}] {summary}".strip()


class AlertmanagerPayload(BaseModel):
    version: str = "4"
    status: str = "firing"
    alerts: list[Alert] = Field(default_factory=list)


class TriageBrief(BaseModel):
    """The constrained output contract. Every field is required so a partial
    answer fails validation instead of reaching the pager half-formed."""

    probable_cause: str = Field(description="One sentence. The single most likely cause.")
    confidence: Literal["high", "medium", "low"]
    blast_radius: str = Field(description="What is affected, in user-visible terms.")
    verification_steps: list[str] = Field(
        min_length=1, max_length=5, description="Ordered checks the on-call runs first."
    )
    suggested_runbook: str | None = None

    @classmethod
    def as_tool_schema(cls) -> dict:
        """Anthropic tool-use schema, so the model is forced into this shape."""
        return {
            "name": "TriageBrief",
            "description": "Structured triage brief for a single production alert.",
            "input_schema": cls.model_json_schema(),
        }
