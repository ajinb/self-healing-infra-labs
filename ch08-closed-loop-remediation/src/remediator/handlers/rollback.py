"""Deploy rollback handler — RECOVERABLE within the autonomy window
(default 15 minutes); IRREVERSIBLE past it via the reversibility adjuster's
max_age_seconds rule."""

import time
from typing import Any

from ..context import ActionContext
from ..reversibility import Reversibility, reversibility
from ..verifier import poll_until, register


class RollbackHandler:
    def __init__(self, k8s_client, error_rate_probe):
        self.k8s = k8s_client
        self.error_rate_probe = error_rate_probe

    def inspect(self, params: dict) -> dict[str, Any]:
        ns, dep = params["namespace"], params["deployment"]
        d = self.k8s.read_deployment(ns, dep)
        max_age = params.get("max_age_seconds", 900)
        # Compute actual age of the current revision; pass to adjuster.
        last_change_ts = self.k8s.read_last_revision_ts(ns, dep)
        age = int(time.time()) - last_change_ts if last_change_ts else 0
        return {
            "replicas": d.spec.replicas,
            "has_readiness_probe": True,
            "stateful": False,
            "max_age_seconds": age if age > max_age else 0,
        }

    @reversibility(Reversibility.RECOVERABLE)
    def execute(self, params: dict, ctx: ActionContext) -> None:
        ns, dep = params["namespace"], params["deployment"]
        # `kubectl rollout undo` — revert to the previous ReplicaSet.
        self.k8s.rollout_undo(ns, dep)


# ---- Verifier probe -------------------------------------------------------

_ROLLBACK_REFS: dict = {"client": None, "error_rate_probe": None}


def _rollback_probe(params: dict, ctx: ActionContext):
    ns, dep = params["namespace"], params["deployment"]
    client = _ROLLBACK_REFS["client"]
    err_probe = _ROLLBACK_REFS["error_rate_probe"]

    def check():
        d = client.read_deployment(ns, dep)
        ready = d.status.ready_replicas or 0
        desired = d.spec.replicas
        if ready < desired:
            return False, f"rollback in progress: {ready}/{desired} Ready"
        # Then verify the error-rate signal has retreated to baseline.
        rate = err_probe.current_rate(target=dep)
        baseline = err_probe.baseline(target=dep)
        if rate <= baseline * 1.1:  # 10% tolerance band
            return True, f"error rate {rate:.3f} within baseline {baseline:.3f}"
        return False, f"error rate {rate:.3f} above baseline {baseline:.3f}"

    return poll_until(check, deadline_unix=ctx.deadline_unix, interval_seconds=5)


def install(k8s_client, error_rate_probe) -> None:
    _ROLLBACK_REFS["client"] = k8s_client
    _ROLLBACK_REFS["error_rate_probe"] = error_rate_probe
    register("rollback", _rollback_probe)
