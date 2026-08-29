"""Pod restart handler — reversible by default; upgrades to RECOVERABLE when
the call site has fewer than 2 replicas or no readiness probe.

The handler talks to the Kubernetes API. The lab's tests use a fake client
so the suite runs without a kind cluster; integration runs swap in the real
client.
"""

from typing import Any

from ..context import ActionContext
from ..reversibility import Reversibility, reversibility
from ..verifier import poll_until, register


class RestartHandler:
    def __init__(self, k8s_client):
        self.k8s = k8s_client

    def inspect(self, params: dict) -> dict[str, Any]:
        ns, dep = params["namespace"], params["deployment"]
        d = self.k8s.read_deployment(ns, dep)
        return {
            "replicas": d.spec.replicas,
            "has_readiness_probe": _any_container_has_readiness(d),
            "stateful": False,
        }

    @reversibility(Reversibility.REVERSIBLE)
    def execute(self, params: dict, ctx: ActionContext) -> None:
        ns, dep = params["namespace"], params["deployment"]
        # `kubectl rollout restart` annotates the pod template to trigger a
        # rolling update without changing the image.
        self.k8s.patch_deployment_restart_annotation(ns, dep)


def _any_container_has_readiness(deployment) -> bool:
    for c in deployment.spec.template.spec.containers or []:
        if getattr(c, "readiness_probe", None):
            return True
    return False


# ---- Verifier probe -------------------------------------------------------

def _restart_probe(params: dict, ctx: ActionContext, *, k8s_client=None):
    ns, dep = params["namespace"], params["deployment"]
    client = k8s_client or _RESTART_CLIENT_REF["client"]

    def check():
        d = client.read_deployment(ns, dep)
        ready = d.status.ready_replicas or 0
        desired = d.spec.replicas
        if ready >= desired and (d.status.unavailable_replicas or 0) == 0:
            return True, f"{ready}/{desired} pods Ready"
        return False, f"only {ready}/{desired} pods Ready, still not Ready"

    return poll_until(check, deadline_unix=ctx.deadline_unix, interval_seconds=3)


_RESTART_CLIENT_REF: dict = {"client": None}


def install(k8s_client) -> None:
    """Wire the restart handler's verifier probe with a shared k8s client."""
    _RESTART_CLIENT_REF["client"] = k8s_client
    register("pod_restart", _restart_probe)
