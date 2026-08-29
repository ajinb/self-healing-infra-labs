"""YAML-driven authorization. Start simple; graduate to OPA when policy logic
exceeds what a static file can express. Picking YAML here is a two-way door.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from .auth import AuthContext


POLICY_PATH = Path(os.environ.get(
    "POLICY_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "policies" / "policy.yaml"),
))


class PolicyDeny(Exception):
    """Raised when a tool call is denied by policy. Mapped to 403 by the server."""


def _load_policy() -> dict:
    return yaml.safe_load(POLICY_PATH.read_text())


_policy = _load_policy()


def reload_policy() -> None:
    """Hot-reload the policy file. Useful for tests and SIGHUP handling."""
    global _policy
    _policy = _load_policy()


def authorize(ctx: AuthContext, *, tool: str) -> None:
    rule = _policy.get("tools", {}).get(tool)
    if not rule:
        raise PolicyDeny(f"no policy for tool: {tool}")

    allowed_tenants = rule.get("allowed_tenants", [])
    if allowed_tenants != "*" and ctx.tenant not in allowed_tenants:
        raise PolicyDeny(f"tenant {ctx.tenant} not allowed for {tool}")

    required = set(rule.get("required_roles", []))
    if not required.issubset(set(ctx.roles)):
        missing = required - set(ctx.roles)
        raise PolicyDeny(f"missing roles for {tool}: need {sorted(missing)}")

    if rule.get("requires_human_approval") and not ctx.roles_include("approver"):
        raise PolicyDeny(f"{tool} requires human approval")
