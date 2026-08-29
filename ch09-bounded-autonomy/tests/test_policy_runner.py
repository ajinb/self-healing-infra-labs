"""PolicyRunner integration: order of operations is kill-switch → policy → runner.

These tests use a fake OPA so the policy decision is whatever the test
configures. The Rego bundle is exercised separately by `opa test policies/`.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import pytest

from autonomy.kill_switch import KillSwitch
from autonomy.models import PolicyDecision
from autonomy.policy_runner import PolicyRunner


# ---- Fake Ch 8 runner -----------------------------------------------------

@dataclass
class FakeAuditEvent:
    outcome: str
    reason: str = ""


@dataclass
class FakeLedger:
    entries: list = field(default_factory=list)

    def all(self):
        return self.entries


class FakeCh8Runner:
    def __init__(self):
        self.ledger = FakeLedger()
        self.calls: list = []

    def execute(self, action_name, params, ctx):
        self.calls.append((action_name, params, ctx))
        return FakeAuditEvent(outcome="ok", reason="delegated to fake")


@dataclass
class FakeCtx:
    tenant: str
    actor: str
    trace_id: str


# ---- Tests ----------------------------------------------------------------

def test_global_kill_switch_blocks_before_policy(opa, kill_switch, approval_queue):
    runner = PolicyRunner(FakeCh8Runner(), opa, kill_switch, approval_queue)
    kill_switch.trip("global", reason="full stop", actor="alice")

    out = runner.execute(
        "pod_restart",
        {"namespace": "default", "deployment": "api"},
        FakeCtx(tenant="tenant-a", actor="sre-agent", trace_id="t1"),
    )
    assert out.outcome == "refused"
    assert "kill-switch" in out.reason
    assert opa.last_input is None  # never reached


def test_tenant_kill_switch_only_blocks_that_tenant(opa, kill_switch, approval_queue):
    runner = PolicyRunner(FakeCh8Runner(), opa, kill_switch, approval_queue)
    opa.set(PolicyDecision(effect="allow", reason="ok", bundle_version="b1"))
    kill_switch.trip("tenant:tenant-a", reason="incident", actor="alice")

    blocked = runner.execute(
        "pod_restart", {}, FakeCtx(tenant="tenant-a", actor="sre", trace_id="t1")
    )
    assert blocked.outcome == "refused"

    allowed = runner.execute(
        "pod_restart", {}, FakeCtx(tenant="tenant-b", actor="sre", trace_id="t2")
    )
    assert allowed.outcome == "ok"


def test_policy_deny_refuses(opa, kill_switch, approval_queue):
    runner = PolicyRunner(FakeCh8Runner(), opa, kill_switch, approval_queue)
    opa.set(
        PolicyDecision(
            effect="deny", reason="not in business hours", bundle_version="b1"
        )
    )

    out = runner.execute(
        "rollback",
        {"namespace": "default", "deployment": "api"},
        FakeCtx(tenant="tenant-a", actor="sre-agent", trace_id="t1"),
    )
    assert out.outcome == "refused"
    assert out.bundle_version == "b1"
    assert "not in business hours" in out.reason


def test_policy_require_approval_enqueues(opa, kill_switch, approval_queue):
    runner = PolicyRunner(FakeCh8Runner(), opa, kill_switch, approval_queue)
    opa.set(
        PolicyDecision(
            effect="require_approval", reason="off hours", bundle_version="b1"
        )
    )

    out = runner.execute(
        "rollback",
        {"namespace": "default", "deployment": "api"},
        FakeCtx(tenant="tenant-a", actor="sre-agent", trace_id="t1"),
    )
    assert out.outcome == "queued_for_approval"
    assert out.approval_id is not None
    pending = approval_queue.list_pending()
    assert len(pending) == 1
    assert pending[0]["request"]["action_name"] == "rollback"


def test_policy_allow_delegates_to_ch8(opa, kill_switch, approval_queue):
    fake = FakeCh8Runner()
    runner = PolicyRunner(fake, opa, kill_switch, approval_queue)
    opa.set(
        PolicyDecision(
            effect="allow",
            reason="ok",
            constraints={"max_replicas": 4},
            bundle_version="b1",
        )
    )

    out = runner.execute(
        "scale",
        {"namespace": "default", "deployment": "api", "delta": 2, "ceiling": 8},
        FakeCtx(tenant="tenant-a", actor="sre-agent", trace_id="t1"),
    )
    assert out.outcome == "ok"
    # Constraint applied: ceiling clamped from 8 to 4.
    assert fake.calls[0][1]["ceiling"] == 4
