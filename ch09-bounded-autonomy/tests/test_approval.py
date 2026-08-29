"""Approval queue contracts: enqueue, decide, default-deny on missing record."""

import pytest

from autonomy.approval import ApprovalDecision, ApprovalRequest


def _req(**overrides):
    base = dict(
        action_name="rollback",
        params={"namespace": "default", "deployment": "api"},
        tenant="tenant-a",
        actor="sre-agent",
        trace_id="t1",
        reason="off-hours rollback",
        bundle_version="bundle-abc",
    )
    base.update(overrides)
    return ApprovalRequest(**base)


def test_enqueue_creates_pending_record(approval_queue):
    aid = approval_queue.enqueue(_req())
    record = approval_queue.get(aid)
    assert record["status"] == "pending"
    assert record["request"]["action_name"] == "rollback"


def test_list_pending_includes_new_requests(approval_queue):
    a1 = approval_queue.enqueue(_req(trace_id="t1"))
    a2 = approval_queue.enqueue(_req(trace_id="t2"))
    pending = approval_queue.list_pending()
    ids = {p["id"] for p in pending}
    assert {a1, a2} <= ids


def test_approve_marks_record(approval_queue):
    aid = approval_queue.enqueue(_req())
    record = approval_queue.decide(
        aid, ApprovalDecision(approver="alice", decision="approve", note="lgtm")
    )
    assert record["status"] == "approve"
    assert record["decided_by"] == "alice"


def test_decide_missing_raises_keyerror(approval_queue):
    with pytest.raises(KeyError):
        approval_queue.decide(
            "nonexistent", ApprovalDecision(approver="alice", decision="approve")
        )


def test_double_decide_rejected(approval_queue):
    aid = approval_queue.enqueue(_req())
    approval_queue.decide(aid, ApprovalDecision(approver="alice", decision="approve"))
    with pytest.raises(ValueError, match="already in status"):
        approval_queue.decide(aid, ApprovalDecision(approver="bob", decision="deny"))
