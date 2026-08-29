"""ActionContext and AuditEvent — the structured envelopes that travel with
every action through the runner."""

from dataclasses import dataclass, field
from typing import Any, Optional

from .reversibility import Reversibility


@dataclass
class ActionContext:
    tenant: str
    actor: str  # "sre-agent" or a user sub
    trace_id: str
    deadline_unix: int
    dry_run: bool = False
    reversibility_override: Optional[Reversibility] = None
    staleness_budget_seconds: int = 60
    diagnosis_ts_unix: Optional[int] = None


@dataclass
class AuditEvent:
    event_id: str
    trace_id: str
    tenant: str
    actor: str
    action: str
    params: dict[str, Any]
    tier: str
    ts_unix: int
    outcome: str = "pending"
    reason: str = ""
    verification: dict[str, Any] = field(default_factory=dict)
