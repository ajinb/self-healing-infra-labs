"""Test fixtures — fake Kubernetes client and an in-memory audit sink so the
suite runs without a kind cluster. Integration runs swap in the real client.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from remediator.handlers import (
    RestartHandler,
    RollbackHandler,
    ScaleHandler,
    ScaleInverseHandler,
)
from remediator.handlers import restart as restart_mod
from remediator.handlers import rollback as rollback_mod
from remediator.handlers import scale as scale_mod
from remediator.ledger import Ledger
from remediator.runner import Runner


# ---- Fake K8s client ------------------------------------------------------

@dataclass
class _Container:
    readiness_probe: Any = None


@dataclass
class _PodTemplate:
    spec: Any = None


@dataclass
class _DeploymentSpec:
    replicas: int = 1
    template: Any = None


@dataclass
class _DeploymentStatus:
    ready_replicas: int = 0
    unavailable_replicas: int = 0


@dataclass
class _Deployment:
    spec: _DeploymentSpec = field(default_factory=_DeploymentSpec)
    status: _DeploymentStatus = field(default_factory=_DeploymentStatus)


class FakeK8s:
    def __init__(self):
        self._deployments: dict[tuple[str, str], _Deployment] = {}
        self._restart_after_recovers = True  # Scenario 1 toggles this off
        self._revision_ts: dict[tuple[str, str], int] = {}

    def add_deployment(
        self,
        ns: str,
        name: str,
        replicas: int,
        ready: int,
        has_readiness: bool = True,
        revision_ts: int | None = None,
    ) -> None:
        container = _Container(readiness_probe=("yes" if has_readiness else None))
        spec = _DeploymentSpec(
            replicas=replicas,
            template=_PodTemplate(spec=type("S", (), {"containers": [container]})()),
        )
        status = _DeploymentStatus(ready_replicas=ready, unavailable_replicas=replicas - ready)
        self._deployments[(ns, name)] = _Deployment(spec=spec, status=status)
        if revision_ts is not None:
            self._revision_ts[(ns, name)] = revision_ts

    def read_deployment(self, ns: str, name: str) -> _Deployment:
        return self._deployments[(ns, name)]

    def patch_deployment_restart_annotation(self, ns: str, name: str) -> None:
        d = self._deployments[(ns, name)]
        if self._restart_after_recovers:
            d.status.ready_replicas = d.spec.replicas
            d.status.unavailable_replicas = 0
        else:
            d.status.ready_replicas = 0
            d.status.unavailable_replicas = d.spec.replicas

    def scale_deployment(self, ns: str, name: str, target: int) -> None:
        d = self._deployments[(ns, name)]
        d.spec.replicas = target
        d.status.ready_replicas = target
        d.status.unavailable_replicas = 0

    def rollout_undo(self, ns: str, name: str) -> None:
        d = self._deployments[(ns, name)]
        d.status.ready_replicas = d.spec.replicas
        d.status.unavailable_replicas = 0

    def read_last_revision_ts(self, ns: str, name: str) -> int | None:
        return self._revision_ts.get((ns, name))

    def force_pod_unhealthy(self, ns: str, name: str) -> None:
        self._restart_after_recovers = False


# ---- Fake error-rate probe ------------------------------------------------

class FakeErrorRateProbe:
    def __init__(self):
        self._rates: dict[str, float] = {}
        self._baselines: dict[str, float] = {}

    def set(self, target: str, rate: float, baseline: float = 0.01) -> None:
        self._rates[target] = rate
        self._baselines[target] = baseline

    def current_rate(self, target: str) -> float:
        return self._rates.get(target, 0.0)

    def baseline(self, target: str) -> float:
        return self._baselines.get(target, 0.01)


# ---- In-memory audit sink -------------------------------------------------

class MemorySink:
    def __init__(self):
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        self.records.append(record)


# ---- Pytest fixtures ------------------------------------------------------

@pytest.fixture
def fake_k8s() -> FakeK8s:
    return FakeK8s()


@pytest.fixture
def err_probe() -> FakeErrorRateProbe:
    return FakeErrorRateProbe()


@pytest.fixture
def remediator(fake_k8s, err_probe):
    handlers = {
        "pod_restart": RestartHandler(fake_k8s),
        "scale": ScaleHandler(fake_k8s),
        "scale_inverse": ScaleInverseHandler(fake_k8s),
        "rollback": RollbackHandler(fake_k8s, err_probe),
    }
    restart_mod.install(fake_k8s)
    scale_mod.install(fake_k8s)
    rollback_mod.install(fake_k8s, err_probe)

    return Runner(handlers=handlers, ledger=Ledger(), audit_sink=MemorySink())
