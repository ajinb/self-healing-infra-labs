"""Scale handler — scale-out is REVERSIBLE within ceiling; scale-in is
RECOVERABLE (loses warm caches)."""

from typing import Any

from ..context import ActionContext
from ..reversibility import Reversibility, reversibility
from ..verifier import poll_until, register


class ScaleHandler:
    def __init__(self, k8s_client):
        self.k8s = k8s_client

    def inspect(self, params: dict) -> dict[str, Any]:
        ns, dep = params["namespace"], params["deployment"]
        d = self.k8s.read_deployment(ns, dep)
        return {
            "replicas": d.spec.replicas,
            "has_readiness_probe": True,
            "stateful": False,
        }

    @reversibility(Reversibility.REVERSIBLE)
    def execute(self, params: dict, ctx: ActionContext) -> None:
        ns, dep, delta, ceiling = (
            params["namespace"],
            params["deployment"],
            params.get("delta", 1),
            params.get("ceiling", 10),
        )
        if delta <= 0:
            raise ValueError("ScaleHandler is scale-out only; use ScaleInverseHandler")
        d = self.k8s.read_deployment(ns, dep)
        target = min(d.spec.replicas + delta, ceiling)
        if target == d.spec.replicas:
            raise RuntimeError(f"already at ceiling {ceiling}")
        self.k8s.scale_deployment(ns, dep, target)


class ScaleInverseHandler:
    """Scale-in. Recoverable, not reversible — losing warm caches has a
    measurable user-visible cost during the warm-up window."""

    def __init__(self, k8s_client):
        self.k8s = k8s_client

    def inspect(self, params: dict) -> dict[str, Any]:
        ns, dep = params["namespace"], params["deployment"]
        d = self.k8s.read_deployment(ns, dep)
        return {
            "replicas": d.spec.replicas,
            "has_readiness_probe": True,
            "stateful": False,
        }

    @reversibility(Reversibility.RECOVERABLE)
    def execute(self, params: dict, ctx: ActionContext) -> None:
        ns, dep = params["namespace"], params["deployment"]
        delta = params.get("delta", 0)
        # Caller may pass the original positive delta — invert it here.
        contract = abs(delta) if delta else 1
        d = self.k8s.read_deployment(ns, dep)
        target = max(d.spec.replicas - contract, 1)
        self.k8s.scale_deployment(ns, dep, target)


# ---- Verifier probe -------------------------------------------------------

_SCALE_CLIENT_REF: dict = {"client": None}


def _scale_probe(params: dict, ctx: ActionContext):
    ns, dep = params["namespace"], params["deployment"]
    client = _SCALE_CLIENT_REF["client"]

    def check():
        d = client.read_deployment(ns, dep)
        ready = d.status.ready_replicas or 0
        desired = d.spec.replicas
        if ready >= desired:
            return True, f"scaled to {desired} replicas, all Ready"
        return False, f"{ready}/{desired} replicas Ready"

    return poll_until(check, deadline_unix=ctx.deadline_unix, interval_seconds=3)


def install(k8s_client) -> None:
    _SCALE_CLIENT_REF["client"] = k8s_client
    register("scale", _scale_probe)
    register("scale_inverse", _scale_probe)
