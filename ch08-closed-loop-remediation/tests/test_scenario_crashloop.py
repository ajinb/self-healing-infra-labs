"""Scenario 1 — pod crashloop with scoped restart.

The bug is in the image, not transient. The remediator restarts once, the
verifier sees the new pod still not Ready, and the runner records
`rolled_back` with the probe failure. A remediator that cannot fail well is
worse than no remediator at all.
"""

import time

from remediator.context import ActionContext


def test_crashloop_restart_recovers(remediator, fake_k8s):
    fake_k8s.add_deployment("default", "crashloop-app", replicas=3, ready=0)

    ctx = ActionContext(
        tenant="tenant-a",
        actor="sre-agent",
        trace_id="t1",
        deadline_unix=int(time.time()) + 30,
    )
    event = remediator.execute(
        action_name="pod_restart",
        params={"namespace": "default", "deployment": "crashloop-app"},
        ctx=ctx,
    )

    assert event.outcome == "ok"
    assert event.tier == "REVERSIBLE"
    assert "Ready" in event.reason


def test_crashloop_persistent_bug_rolls_back(remediator, fake_k8s):
    fake_k8s.add_deployment("default", "crashloop-app", replicas=3, ready=0)
    fake_k8s.force_pod_unhealthy("default", "crashloop-app")  # restart will not help

    ctx = ActionContext(
        tenant="tenant-a",
        actor="sre-agent",
        trace_id="t1b",
        deadline_unix=int(time.time()) + 12,
    )
    event = remediator.execute(
        action_name="pod_restart",
        params={"namespace": "default", "deployment": "crashloop-app"},
        ctx=ctx,
    )

    assert event.outcome == "rolled_back"
    assert "still not Ready" in event.reason


def test_crashloop_single_replica_requires_human(remediator, fake_k8s):
    # Single replica → call-site adjuster upgrades tier to RECOVERABLE; default
    # ceiling is RECOVERABLE so it proceeds. But if the team narrows the
    # ceiling for restarts, a single replica triggers human review.
    fake_k8s.add_deployment("default", "single-replica-app", replicas=1, ready=0)

    ctx = ActionContext(
        tenant="tenant-a",
        actor="sre-agent",
        trace_id="t1c",
        deadline_unix=int(time.time()) + 30,
    )
    event = remediator.execute(
        action_name="pod_restart",
        params={"namespace": "default", "deployment": "single-replica-app"},
        ctx=ctx,
        autonomy_ceiling=__import__(
            "remediator.reversibility", fromlist=["Reversibility"]
        ).Reversibility.REVERSIBLE,
    )

    assert event.outcome == "refused_human_required"
    assert "exceeds autonomy ceiling" in event.reason
