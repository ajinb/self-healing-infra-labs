"""The four containment patterns: action storms, oscillation, rollback
chains, stale diagnosis."""

import time

from remediator.context import ActionContext


def test_stale_diagnosis_refused(remediator, fake_k8s):
    fake_k8s.add_deployment("default", "stale-app", replicas=3, ready=3)

    ctx = ActionContext(
        tenant="tenant-a",
        actor="sre-agent",
        trace_id="ts1",
        deadline_unix=int(time.time()) + 30,
        diagnosis_ts_unix=int(time.time()) - 300,  # 5 minutes old
        staleness_budget_seconds=60,
    )
    event = remediator.execute(
        action_name="pod_restart",
        params={"namespace": "default", "deployment": "stale-app"},
        ctx=ctx,
    )

    assert event.outcome == "refused"
    assert "stale" in event.reason or "exceeds" in event.reason


def test_action_storm_cooldown_blocks_concurrent(remediator, fake_k8s):
    """A second restart against the same resource within the cooldown window
    while the first is still in-flight should be refused."""
    fake_k8s.add_deployment("default", "stormy", replicas=3, ready=0)
    # Force the first restart to leave the deployment unhealthy so the verifier
    # rolls back, but the in-flight check happens before that.
    fake_k8s.force_pod_unhealthy("default", "stormy")

    # Manually plant an open ledger entry to simulate a concurrent action.
    remediator.ledger.record(
        event_id="prev-event",
        action="pod_restart",
        params={"namespace": "default", "deployment": "stormy"},
        ctx=ActionContext(
            tenant="tenant-a",
            actor="sre-agent",
            trace_id="prev",
            deadline_unix=int(time.time()) + 30,
        ),
    )

    ctx = ActionContext(
        tenant="tenant-a",
        actor="sre-agent",
        trace_id="ts2",
        deadline_unix=int(time.time()) + 30,
    )
    event = remediator.execute(
        action_name="pod_restart",
        params={"namespace": "default", "deployment": "stormy"},
        ctx=ctx,
    )

    assert event.outcome == "refused"
    assert "in-flight" in event.reason
