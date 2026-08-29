"""HTTP client to the OPA sidecar.

OPA exposes policies at /v1/data/<package>/<rule>. This client posts the
PolicyInput as JSON and parses the PolicyDecision back out. The bundle
version is read from OPA's /v1/data/system/bundles endpoint and cached for
the lifetime of the process; OPA pushes new bundle versions atomically so a
restart of the client side is not required for policy updates.
"""

from typing import Optional

import httpx

from .models import PolicyDecision, PolicyInput


class OPAClient:
    def __init__(self, base_url: str = "http://localhost:8181", timeout_s: float = 1.5):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s)
        self._bundle_version_cache: Optional[str] = None

    def evaluate(self, policy_input: PolicyInput) -> PolicyDecision:
        url = f"{self.base_url}/v1/data/remediator/autonomy/decision"
        try:
            resp = self._client.post(url, json={"input": policy_input.model_dump()})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            # OPA unreachable — default to deny. The runner already treats
            # the OPA call as a critical-path dependency; failing closed
            # here is the correct posture.
            return PolicyDecision(
                effect="deny",
                reason=f"OPA unreachable: {exc!r}",
                bundle_version="unreachable",
            )

        body = resp.json().get("result")
        if body is None:
            return PolicyDecision(
                effect="deny",
                reason="OPA returned no decision; default deny",
                bundle_version=self._bundle_version() or "unknown",
            )

        return PolicyDecision(
            effect=body.get("effect", "deny"),
            reason=body.get("reason", ""),
            constraints=body.get("constraints", {}),
            bundle_version=self._bundle_version() or "unknown",
        )

    def _bundle_version(self) -> Optional[str]:
        if self._bundle_version_cache is not None:
            return self._bundle_version_cache
        try:
            resp = self._client.get(f"{self.base_url}/v1/data/system/bundles")
            data = resp.json().get("result", {})
            for bundle in data.values():
                rev = bundle.get("active_revision") or bundle.get("last_successful_activation")
                if rev:
                    self._bundle_version_cache = rev
                    return rev
        except (httpx.HTTPError, ValueError):
            pass
        return None
