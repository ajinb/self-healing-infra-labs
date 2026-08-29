"""Stage 4 — rendering for the routing target.

The rule the chapter calls "brief on top, raw underneath": enrichment is
additive. Losing it must never mean losing the page.
"""

from __future__ import annotations

from .schema import Alert, TriageBrief


def render_for_pagerduty(alert: Alert, brief: TriageBrief | None) -> dict:
    """Render one alert. `brief=None` is the deterministic fallback path."""
    if brief is None:
        # Passthrough: the on-call loses the enrichment, not the page.
        return {
            "summary": alert.name,
            "severity": alert.severity,
            "description": alert.raw_text(),
            "enriched": False,
        }

    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(brief.verification_steps, 1))
    description = (
        f"{alert.raw_text()}\n\n"
        f"Probable cause ({brief.confidence} confidence): {brief.probable_cause}\n"
        f"Blast radius: {brief.blast_radius}\n\n"
        f"Verification steps:\n{steps}"
    )
    if brief.suggested_runbook:
        description += f"\n\nRunbook: {brief.suggested_runbook}"

    return {
        "summary": alert.name,
        "severity": alert.severity,
        "description": description,
        "enriched": True,
    }
