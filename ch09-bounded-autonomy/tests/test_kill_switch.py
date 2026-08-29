"""Kill-switch contracts: trip + reset, scope isolation, four-eyes for global."""

import pytest


def test_per_action_trip_and_reset(kill_switch):
    assert not kill_switch.is_tripped("action:rollback")
    kill_switch.trip("action:rollback", reason="probe flapping", actor="alice")
    assert kill_switch.is_tripped("action:rollback")

    kill_switch.reset("action:rollback", actor="alice")
    assert not kill_switch.is_tripped("action:rollback")


def test_per_tenant_does_not_affect_other_tenant(kill_switch):
    kill_switch.trip("tenant:tenant-a", reason="incident", actor="alice")
    assert kill_switch.is_tripped("tenant:tenant-a")
    assert not kill_switch.is_tripped("tenant:tenant-b")


def test_global_requires_two_operators_to_reset(kill_switch):
    kill_switch.trip("global", reason="remediator misbehaving", actor="alice")

    with pytest.raises(PermissionError, match="second operator"):
        kill_switch.reset("global", actor="alice")

    with pytest.raises(PermissionError, match="distinct operators"):
        kill_switch.reset("global", actor="alice", second_actor="alice")

    kill_switch.reset("global", actor="alice", second_actor="bob")
    assert not kill_switch.is_tripped("global")


def test_info_returns_trip_record(kill_switch):
    kill_switch.trip("tenant:tenant-a", reason="planned maintenance", actor="alice")
    info = kill_switch.info("tenant:tenant-a")
    assert info is not None
    assert info["reason"] == "planned maintenance"
    assert info["tripped_by"] == "alice"


def test_audit_trail_captures_ops(kill_switch, redis):
    kill_switch.trip("action:scale", reason="bad ceiling", actor="alice")
    kill_switch.reset("action:scale", actor="alice")

    audit = redis.lrange("killswitch:audit", 0, -1)
    assert len(audit) == 2
