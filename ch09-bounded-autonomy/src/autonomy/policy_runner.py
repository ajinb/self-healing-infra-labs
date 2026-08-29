"""PolicyRunner — wraps the Chapter 8 Runner with kill-switch + OPA + approval.

The Ch 8 Runner's contract did not change. Only what it is allowed to do
did. The order of operations matters: kill-switch first (cheapest, most
important), policy second, runner third — because that is the order in
which each layer's failure is the most expensive.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from .approval import ApprovalQueue, ApprovalRequest
from .kill_switch import KillSwitch
from .models import (
    Action,
    Condition,
    Environment,
    PolicyDecision,
    PolicyInput,
    Resource,
    Subject,
)
from .opa_client import OPAClient


@dataclass
class PolicyRunnerOutcome:
    outcome: str  # "ok", "rolled_back", "refused", "queued_for_approval", ...
    reason: str
    bundle_version: str = "n/a"
    approval_id: Optional[str] = None
    delegated_event: Optional[Any] = None  # the Ch 8 AuditEvent if delegated


class PolicyRunner:
    def __init__(
        self,
        ch8_runner,
        opa: OPAClient,
        kill_switch: KillSwitch,
        approvals: ApprovalQueue,
    ):
        self.ch8 = ch8_runner
        self.opa = opa
        self.kill_switch = kill_switch
        self.approvals = approvals

    def execute(
        self,
        action_name: str,
        params: dict,
        ctx,  # remediator.ActionContext from Ch 8
        action_tier: str = "REVERSIBLE",
    ) -> PolicyRunnerOutcome:
        # 1. Kill-switch checks — sub-millisecond, before anything else.
        for scope in (
            "global",
            f"tenant:{ctx.tenant}",
            f"action:{action_name}",
        ):
            if self.kill_switch.is_tripped(scope):
                info = self.kill_switch.info(scope) or {}
                return PolicyRunnerOutcome(
                    outcome="refused",
                    reason=(
                        f"kill-switch tripped ({scope}): "
                        f"{info.get('reason', 'no reason recorded')}"
                    ),
                )

        # 2. Build the policy input from runner-supplied facts + ledger.
        policy_input = self._build_input(action_name, action_tier, params, ctx)
        decision = self.opa.evaluate(policy_input)

        # 3. Route on effect.
        if decision.effect == "deny":
            return PolicyRunnerOutcome(
                outcome="refused",
                reason=f"policy deny: {decision.reason}",
                bundle_version=decision.bundle_version,
            )

        if decision.effect == "require_approval":
            req = ApprovalRequest(
                action_name=action_name,
                params=params,
                tenant=ctx.tenant,
                actor=ctx.actor,
                trace_id=ctx.trace_id,
                reason=decision.reason,
                bundle_version=decision.bundle_version,
                ttl_seconds=900,
            )
            approval_id = self.approvals.enqueue(req)
            return PolicyRunnerOutcome(
                outcome="queued_for_approval",
                reason=f"queued: {decision.reason}",
                bundle_version=decision.bundle_version,
                approval_id=approval_id,
            )

        # 4. Allow → apply policy constraints, delegate to Ch 8 runner.
        constrained = self._apply_constraints(params, decision.constraints)
        event = self.ch8.execute(action_name, constrained, ctx)
        return PolicyRunnerOutcome(
            outcome=event.outcome,
            reason=event.reason,
            bundle_version=decision.bundle_version,
            delegated_event=event,
        )

    # ------------------------------------------------------------------ helpers

    def _build_input(
        self, action_name: str, action_tier: str, params: dict, ctx
    ) -> PolicyInput:
        now = time.localtime()
        return PolicyInput(
            subject=Subject(tenant=ctx.tenant, actor=ctx.actor),
            action=Action(name=action_name, tier=action_tier, params=params),
            resource=Resource(
                namespace=params.get("namespace", "default"),
                deployment=params.get("deployment"),
            ),
            environment=Environment(
                hour=now.tm_hour,
                weekday=now.tm_wday,
                actions_today=[
                    {"action": e.action, "ts": e.ts_unix}
                    for e in self.ch8.ledger.all()
                    if e.tenant == ctx.tenant
                ],
            ),
            condition=Condition(
                replicas=params.get("_replicas", 1),
                blast_radius_pods=params.get("_replicas", 1),
            ),
        )

    @staticmethod
    def _apply_constraints(params: dict, constraints: dict) -> dict:
        out = dict(params)
        if "max_replicas" in constraints:
            ceiling = constraints["max_replicas"]
            if "ceiling" in out:
                out["ceiling"] = min(out["ceiling"], ceiling)
            else:
                out["ceiling"] = ceiling
        return out


def run_id() -> str:
    return str(uuid.uuid4())
