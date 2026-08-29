package remediator.budget

import rego.v1

# Blast-radius budget: the daily cap on cumulative damage potential, per tenant.
# The per-call ceiling answers "can the system act here?"; this budget answers
# "how much damage potential can it run through per day before the kill-switch
# trips?". The numbers are scaffolding — the pattern (every autonomous action
# carries a damage-unit cost, summed per tenant per day) is the deliverable.

budget_total := 50  # damage units per day, per tenant

budget_remaining := budget_total - consumed_today

consumed_today := sum([damage_units(e) | some e in input.environment.actions_today])

# Default-then-override: an unconditional `damage_units(event) := 0` alongside
# the conditional rules would derive two values for the same event and fail the
# whole evaluation with a conflict error. `default` is the idiom.
default damage_units(_) := 0

damage_units(event) := 1 if event.action == "pod_restart"

damage_units(event) := 5 if event.action == "scale"

damage_units(event) := 20 if event.action == "rollback"

# Exhausted budget flips any would-be allow into a deny upstream.
budget_exhausted if budget_remaining <= 0
