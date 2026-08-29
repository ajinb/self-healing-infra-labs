package remediator.autonomy

import rego.v1

# Default deny — every policy starts here. The single most important property
# of the bundle: a typo silently refuses an action, never silently authorizes
# one.
default decision := {
    "effect": "deny",
    "reason": "no rule matched",
    "constraints": {},
}

# Reversible action within business hours and blast radius cap → allow.
decision := {
    "effect": "allow",
    "reason": "reversible action within business hours and blast-radius cap",
    "constraints": {},
} if {
    input.action.tier == "REVERSIBLE"
    business_hours
    input.condition.blast_radius_pods <= 50
}

# Recoverable action explicitly allowed for a trusted tenant during business hours.
decision := {
    "effect": "allow",
    "reason": sprintf(
        "recoverable action %v allowed for trusted tenant %v",
        [input.action.name, input.subject.tenant],
    ),
    "constraints": {"max_replicas": 8},
} if {
    input.action.tier == "RECOVERABLE"
    allowed_recoverable[input.action.name]
    input.subject.tenant in trusted_tenants
    business_hours
}

# Recoverable action outside business hours → human approval, queued.
decision := {
    "effect": "require_approval",
    "reason": "recoverable action outside business hours; queued for human review",
    "constraints": {},
} if {
    input.action.tier == "RECOVERABLE"
    allowed_recoverable[input.action.name]
    not business_hours
}

# Irreversible actions are *never* autonomous. The runner's reversibility
# adjuster should already have escalated, but defense in depth: the policy
# refuses regardless.
decision := {
    "effect": "deny",
    "reason": "irreversible actions are never autonomous; require human authorization out-of-band",
    "constraints": {},
} if {
    input.action.tier == "IRREVERSIBLE"
}

# Daily blast-radius budget exhausted → deny regardless of per-call match.
decision := {
    "effect": "deny",
    "reason": sprintf(
        "daily blast-radius budget exhausted (%v / %v damage units)",
        [consumed_today, budget_total],
    ),
    "constraints": {},
} if {
    consumed_today >= budget_total
}

# ----- helpers -------------------------------------------------------------

business_hours if {
    input.environment.hour >= 9
    input.environment.hour < 18
    input.environment.weekday < 5
}

allowed_recoverable := {"rollback", "scale_inverse", "scale"}
trusted_tenants := {"tenant-a", "tenant-b"}

# Damage-unit cost per action class. Numbers are scaffolding; the pattern is
# the deliverable.
damage_units(event) := 1 if event.action == "pod_restart"
damage_units(event) := 5 if event.action == "scale"
damage_units(event) := 5 if event.action == "scale_inverse"
damage_units(event) := 20 if event.action == "rollback"
damage_units(_) := 0

budget_total := 50

consumed_today := sum([damage_units(e) | e := input.environment.actions_today[_]])
