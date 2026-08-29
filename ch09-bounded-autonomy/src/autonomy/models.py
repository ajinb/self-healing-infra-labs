"""Typed contracts between the PolicyRunner and OPA.

The five-input/four-output contract from Chapter 9 §"The shape of an action
policy" is encoded here. The same structures travel through the audit
event so a regulator's "what authorized this" question has a one-line
answer."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Subject(BaseModel):
    tenant: str
    actor: str
    sub: Optional[str] = None  # human-on-behalf-of from RFC 8693
    act: Optional[str] = None  # delegated agent identity


class Action(BaseModel):
    name: str
    tier: Literal["REVERSIBLE", "RECOVERABLE", "IRREVERSIBLE"]
    params: dict[str, Any] = Field(default_factory=dict)


class Resource(BaseModel):
    namespace: str
    deployment: Optional[str] = None
    criticality: Literal["production-critical", "production", "internal"] = "production"


class Environment(BaseModel):
    hour: int = Field(ge=0, le=23)
    weekday: int = Field(ge=0, le=6)
    in_active_incident: bool = False
    actions_today: list[dict[str, Any]] = Field(default_factory=list)


class Condition(BaseModel):
    replicas: int
    has_readiness_probe: bool = True
    blast_radius_pods: int = 1


class PolicyInput(BaseModel):
    subject: Subject
    action: Action
    resource: Resource
    environment: Environment
    condition: Condition


class PolicyDecision(BaseModel):
    effect: Literal["allow", "deny", "require_approval"]
    reason: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    bundle_version: str = "unknown"
