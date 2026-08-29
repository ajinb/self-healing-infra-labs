"""Timeline and postmortem contracts.

The privacy property is structural, not a prompt instruction: a TimelineEntry
has an `actor_role` field and no field capable of holding a person's name.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["detection", "hypothesis", "action", "observation", "decision"]
CATEGORIES: tuple[str, ...] = ("detection", "hypothesis", "action", "observation", "decision")


class TimelineEntry(BaseModel):
    incident_id: str
    timestamp: datetime
    category: Category
    content: str = Field(description="Third-person neutral voice. No individual names.")
    actor_role: str = Field(description="A role, e.g. 'on-call SRE'. Never a person's name.")


class ActionItem(BaseModel):
    description: str
    owner_role: str
    due: str


class PostmortemDraft(BaseModel):
    """What the drafter is forced to produce.

    `open_questions` is the pressure valve: anything the timeline does not
    support goes here instead of becoming an asserted fact.
    """

    title: str
    summary: str = Field(description="Neutral, third-person. What happened, in five sentences or fewer.")
    impact: str
    contributing_factors: list[str] = Field(
        min_length=1,
        description="Causal, not attributive. Describe mechanisms, not people's choices.",
    )
    timeline_highlights: list[str] = Field(min_length=1)
    action_items: list[ActionItem] = Field(default_factory=list)
    open_questions: list[str] = Field(
        default_factory=list,
        description="Anything the timeline does not establish. Never guess into the summary.",
    )

    @classmethod
    def as_tool_schema(cls) -> dict:
        return {
            "name": "PostmortemDraft",
            "description": "A blameless postmortem drafted strictly from a timeline.",
            "input_schema": cls.model_json_schema(),
        }
