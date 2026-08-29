"""The closed-loop runner: gate → act → verify → audit.

This is the chapter in 100 lines of code. Read `Runner.execute` as the
contract: every action that mutates state passes through this method, and
every action emits exactly one AuditEvent with a terminal outcome.

The runner is also the place every cross-cutting safety bound lives —
action-storm cooldowns, oscillation hysteresis, rollback-chain limits, and
stale-diagnosis refusal. Action handlers stay narrow; the runner stays
paranoid.
"""

import time
import uuid
from dataclasses import asdict
from typing import Optional, Protocol

from .context import ActionContext, AuditEvent
from .ledger import Ledger
from .reversibility import Reversibility, evaluate
from .verifier import verify

# Containment defaults — Chapter 8 §"Failure modes you will create".
DEFAULT_COOLDOWN_SECONDS = {
    "pod_restart": 90,
    "scale": 600,
    "rollback": 600,
}
HYSTERESIS_SECONDS = 600  # min dwell between an action and its inverse
MAX_ROLLBACK_DEPTH = 1


class AuditSink(Protocol):
    def write(self, record: dict) -> None: ...


class Handler(Protocol):
    def inspect(self, params: dict) -> dict: ...
    def execute(self, params: dict, ctx: ActionContext) -> None: ...


class Runner:
    def __init__(
        self,
        handlers: dict[str, Handler],
        ledger: Ledger,
        audit_sink: AuditSink,
    ):
        self.handlers = handlers
        self.ledger = ledger
        self.audit_sink = audit_sink

    def execute(
        self,
        action_name: str,
        params: dict,
        ctx: ActionContext,
        autonomy_ceiling: Reversibility = Reversibility.RECOVERABLE,
        rollback_depth: int = 0,
    ) -> AuditEvent:
        event_id = str(uuid.uuid4())
        handler = self.handlers[action_name]
        key = (params.get("namespace", ""), params.get("deployment", ""))

        # 0. cross-cutting safety bounds
        refusal = self._check_safety_bounds(action_name, params, ctx, key, rollback_depth)
        if refusal:
            event = self._fresh_event(event_id, action_name, params, ctx, "REFUSED_BOUND")
            event.outcome = "refused"
            event.reason = refusal
            self._emit(event)
            return event

        # 1. gate
        call_site = handler.inspect(params)
        decision = evaluate(handler.execute, call_site, autonomy_ceiling=autonomy_ceiling)
        event = self._fresh_event(event_id, action_name, params, ctx, decision.tier.name)

        if not decision.proceed:
            event.outcome = (
                "refused_human_required" if decision.requires_human else "refused"
            )
            event.reason = decision.reason
            self._emit(event)
            return event

        # 2. dry-run short-circuit
        if ctx.dry_run:
            event.outcome = "dry_run_ok"
            event.reason = "dry-run path completed without mutation"
            self._emit(event)
            return event

        # 3. act
        self.ledger.record(event_id, action_name, params, ctx, rollback_depth)
        try:
            handler.execute(params, ctx)
        except Exception as exc:  # noqa: BLE001 — log everything to audit
            event.outcome = "action_failed"
            event.reason = repr(exc)
            self.ledger.mark_terminal(event_id)
            self._emit(event)
            return event

        # 4. verify
        ok, msg = verify(action_name, params, ctx)
        event.verification = {"ok": ok, "msg": msg}

        if ok:
            event.outcome = "ok"
            event.reason = msg
            self.ledger.mark_terminal(event_id)
            self._emit(event)
            return event

        # 5. rollback on probe failure
        self._rollback(event_id, action_name, params, ctx, rollback_depth)
        event.outcome = "rolled_back"
        event.reason = msg
        self.ledger.mark_rolled_back(event_id)
        self._emit(event)
        return event

    # ------------------------------------------------------------------ helpers

    def _check_safety_bounds(
        self,
        action_name: str,
        params: dict,
        ctx: ActionContext,
        key: tuple[str, ...],
        rollback_depth: int,
    ) -> Optional[str]:
        """Return a refusal reason or None."""
        # Stale diagnosis
        if ctx.diagnosis_ts_unix is not None:
            age = int(time.time()) - ctx.diagnosis_ts_unix
            if age > ctx.staleness_budget_seconds:
                return (
                    f"diagnosis is {age}s old, exceeds staleness budget "
                    f"{ctx.staleness_budget_seconds}s"
                )

        # Action-storm cooldown
        cooldown = DEFAULT_COOLDOWN_SECONDS.get(action_name, 60)
        last = self.ledger.find_open(ctx.tenant, action_name, key)
        if last is not None:
            return (
                f"in-flight {action_name} for {key} (event_id={last.event_id}); "
                f"cooldown {cooldown}s"
            )

        # Oscillation hysteresis — refuse the inverse of the most recent action
        # against this resource within the dwell window.
        prev = self.ledger.last_action_against(ctx.tenant, key)
        if prev is not None and prev.terminal:
            inverse_pairs = {
                ("scale", "scale"): self._is_scale_inverse,
            }
            for (a, b), is_inverse in inverse_pairs.items():
                if prev.action == a and action_name == b and is_inverse(prev.params, params):
                    if int(time.time()) - prev.ts_unix < HYSTERESIS_SECONDS:
                        return (
                            f"hysteresis: inverse of recent {prev.action} within "
                            f"{HYSTERESIS_SECONDS}s dwell window"
                        )

        # Rollback-chain limit
        if rollback_depth > MAX_ROLLBACK_DEPTH:
            return f"rollback depth {rollback_depth} exceeds max {MAX_ROLLBACK_DEPTH}"

        return None

    @staticmethod
    def _is_scale_inverse(prev_params: dict, new_params: dict) -> bool:
        prev_delta = prev_params.get("delta", 0)
        new_delta = new_params.get("delta", 0)
        return (prev_delta > 0 and new_delta < 0) or (prev_delta < 0 and new_delta > 0)

    def _rollback(
        self,
        event_id: str,
        action_name: str,
        params: dict,
        ctx: ActionContext,
        rollback_depth: int,
    ) -> None:
        inverse = self.handlers.get(f"{action_name}_inverse")
        if inverse is None:
            return
        # Recursive call back through the runner so rollback inherits all
        # safety bounds — including the rollback-depth limit.
        self.execute(
            f"{action_name}_inverse",
            params,
            ctx,
            autonomy_ceiling=Reversibility.RECOVERABLE,
            rollback_depth=rollback_depth + 1,
        )

    def _fresh_event(
        self,
        event_id: str,
        action_name: str,
        params: dict,
        ctx: ActionContext,
        tier: str,
    ) -> AuditEvent:
        return AuditEvent(
            event_id=event_id,
            trace_id=ctx.trace_id,
            tenant=ctx.tenant,
            actor=ctx.actor,
            action=action_name,
            params=params,
            tier=tier,
            ts_unix=int(time.time()),
        )

    def _emit(self, event: AuditEvent) -> None:
        self.audit_sink.write(asdict(event))
