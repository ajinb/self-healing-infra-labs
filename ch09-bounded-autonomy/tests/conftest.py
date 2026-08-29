"""Test fixtures — fakeredis for the kill-switch and approval queue, and a
fake OPA client that returns whatever the test sets up. Production swaps in
real Redis + a real OPA sidecar."""

from typing import Any

import fakeredis
import pytest

from autonomy.approval import ApprovalQueue
from autonomy.kill_switch import KillSwitch
from autonomy.models import PolicyDecision


class FakeOPA:
    def __init__(self):
        self._decision: PolicyDecision = PolicyDecision(
            effect="deny", reason="default-deny (unconfigured)", bundle_version="fake-v0"
        )
        self.last_input: Any = None

    def set(self, decision: PolicyDecision) -> None:
        self._decision = decision

    def evaluate(self, policy_input) -> PolicyDecision:
        self.last_input = policy_input
        return self._decision


@pytest.fixture
def redis():
    return fakeredis.FakeStrictRedis()


@pytest.fixture
def kill_switch(redis):
    return KillSwitch(redis)


@pytest.fixture
def approval_queue(redis):
    return ApprovalQueue(redis)


@pytest.fixture
def opa():
    return FakeOPA()
