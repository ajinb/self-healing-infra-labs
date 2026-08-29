"""Scenario 3 — bad deploy with rollback.

The rollback handler is RECOVERABLE within the autonomy window (default 15
minutes). Past it, the reversibility adjuster's max_age_seconds rule
upgrades the call to IRREVERSIBLE and the runner refuses, surfacing
human-required review.
"""

import time

from remediator.context import ActionContext


def test_bad_deploy_rollback_succeeds(remediator, fake_k8s, err_probe):
    now = int(time.time())
    fake_k8s.add_deployment(
        "default", "api", replicas=3, ready=0, revision_ts=now - 120
    )
    err_probe.set("api", rate=0.005, baseline=0.01)

    ctx = ActionContext(
        tenant="tenant-a",
        actor="sre-agent",
        trace_id="t3",
        deadline_unix=now + 30,
    )
    event = remediator.execute(
        action_name="rollback",
        params={"namespace": "default", "deployment": "api", "max_age_seconds": 900},
        ctx=ctx,
    )

    assert event.outcome == "ok"
    assert event.tier == "RECOVERABLE"


def test_old_revision_rollback_refused(remediator, fake_k8s, err_probe):
    now = int(time.time())
    # Revision is 2 hours old — well past the 15-minute autonomy window.
    fake_k8s.add_deployment(
        "default", "api", replicas=3, ready=3, revision_ts=now - 7200
    )
    err_probe.set("api", rate=0.005, baseline=0.01)

    ctx = ActionContext(
        tenant="tenant-a",
        actor="sre-agent",
        trace_id="t3b",
        deadline_unix=now + 30,
    )
    event = remediator.execute(
        action_name="rollback",
        params={"namespace": "default", "deployment": "api", "max_age_seconds": 900},
        ctx=ctx,
    )

    assert event.outcome == "refused_human_required"
    assert "IRREVERSIBLE" in event.reason
