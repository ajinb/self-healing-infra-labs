package remediator.autonomy_test

import data.remediator.autonomy
import rego.v1

base_input := {
    "subject": {"tenant": "tenant-a", "actor": "sre-agent"},
    "action": {"name": "pod_restart", "tier": "REVERSIBLE", "params": {}},
    "resource": {"namespace": "default", "criticality": "production"},
    "environment": {"hour": 14, "weekday": 2, "in_active_incident": false, "actions_today": []},
    "condition": {"replicas": 3, "has_readiness_probe": true, "blast_radius_pods": 3},
}

test_default_denies_unknown_action if {
    inp := json.patch(base_input, [
        {"op": "replace", "path": "/action", "value": {"name": "delete_database", "tier": "RECOVERABLE", "params": {}}},
    ])
    autonomy.decision.effect == "deny" with input as inp
}

test_irreversible_always_denied if {
    inp := json.patch(base_input, [
        {"op": "replace", "path": "/action/tier", "value": "IRREVERSIBLE"},
    ])
    autonomy.decision.effect == "deny" with input as inp
}

test_reversible_business_hours_allows if {
    autonomy.decision.effect == "allow" with input as base_input
}

test_off_hours_recoverable_requires_approval if {
    inp := json.patch(base_input, [
        {"op": "replace", "path": "/action", "value": {"name": "rollback", "tier": "RECOVERABLE", "params": {}}},
        {"op": "replace", "path": "/environment/hour", "value": 3},
    ])
    autonomy.decision.effect == "require_approval" with input as inp
}

test_untrusted_tenant_recoverable_denied if {
    inp := json.patch(base_input, [
        {"op": "replace", "path": "/subject/tenant", "value": "tenant-stranger"},
        {"op": "replace", "path": "/action", "value": {"name": "rollback", "tier": "RECOVERABLE", "params": {}}},
    ])
    autonomy.decision.effect == "deny" with input as inp
}

test_blast_radius_cap_denies_oversized if {
    inp := json.patch(base_input, [
        {"op": "replace", "path": "/condition/blast_radius_pods", "value": 200},
    ])
    autonomy.decision.effect == "deny" with input as inp
}

test_budget_exhausted_denies if {
    big_history := [{"action": "rollback", "ts": 1} | _ := numbers.range(1, 4)[_]]
    inp := json.patch(base_input, [
        {"op": "replace", "path": "/environment/actions_today", "value": big_history},
    ])
    autonomy.decision.effect == "deny" with input as inp
}
