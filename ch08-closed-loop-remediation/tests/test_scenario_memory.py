"""Scenario 2 — memory pressure with scale-out.

Scaling out within the HPA ceiling stays REVERSIBLE; the verifier confirms
the new replicas are Ready. The ceiling parameter is what keeps the action
bounded — Chapter 9 widens this seam into policy-as-code.
"""

import time

from remediator.context import ActionContext


def test_memory_pressure_scale_out(remediator, fake_k8s):
    fake_k8s.add_deployment("default", "memory-app", replicas=3, ready=3)

    ctx = ActionContext(
        tenant="tenant-a",
        actor="sre-agent",
        trace_id="t2",
        deadline_unix=int(time.time()) + 30,
    )
    event = remediator.execute(
        action_name="scale",
        params={
            "namespace": "default",
            "deployment": "memory-app",
            "delta": 2,
            "ceiling": 6,
        },
        ctx=ctx,
    )

    assert event.outcome == "ok"
    assert event.tier == "REVERSIBLE"
    assert fake_k8s.read_deployment("default", "memory-app").spec.replicas == 5


def test_scale_at_ceiling_fails(remediator, fake_k8s):
    fake_k8s.add_deployment("default", "memory-app", replicas=6, ready=6)

    ctx = ActionContext(
        tenant="tenant-a",
        actor="sre-agent",
        trace_id="t2b",
        deadline_unix=int(time.time()) + 30,
    )
    event = remediator.execute(
        action_name="scale",
        params={
            "namespace": "default",
            "deployment": "memory-app",
            "delta": 2,
            "ceiling": 6,
        },
        ctx=ctx,
    )

    assert event.outcome == "action_failed"
    assert "ceiling" in event.reason
