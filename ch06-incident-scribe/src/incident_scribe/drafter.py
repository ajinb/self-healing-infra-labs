"""Stage 3 — the postmortem draft.

The scribe drafts and opens a pull request. A human reviews and merges. It
never publishes directly, which is what keeps the human-oversight control real
rather than nominal.
"""

from __future__ import annotations

from .audit import emit_audit
from .config import settings
from .schema import PostmortemDraft, TimelineEntry

DRAFTER_SYSTEM_PROMPT = """You are an incident scribe drafting a blameless postmortem.

Rules you must obey:
1. Neutral, third-person voice. No proper nouns for individuals.
2. Render `actor_role` from the timeline; never fabricate roles.
3. If a fact is not in the timeline, do not assert it. Add it to `open_questions`.
4. Contributing factors are causal, not attributive. "A retry storm overwhelmed
   the upstream" — not "the team did not configure the retry policy correctly."
5. Action items must be concrete (an owner role and a date), or go into
   `open_questions` for human assignment.
"""


def format_timeline(timeline: list[TimelineEntry]) -> str:
    return "\n".join(
        f"{e.timestamp.isoformat()} [{e.category}] ({e.actor_role}) {e.content}"
        for e in timeline
    )


async def draft(timeline: list[TimelineEntry]) -> PostmortemDraft:
    from anthropic import AsyncAnthropic  # imported lazily; no key needed to import

    claude = AsyncAnthropic()
    resp = await claude.messages.create(
        model=settings.DRAFTER_MODEL,
        max_tokens=2048,
        system=DRAFTER_SYSTEM_PROMPT,
        tools=[PostmortemDraft.as_tool_schema()],
        tool_choice={"type": "tool", "name": "PostmortemDraft"},
        messages=[{"role": "user", "content": format_timeline(timeline)}],
    )
    out = PostmortemDraft.model_validate(resp.content[0].input)
    if timeline:
        await emit_audit("draft_generated", timeline[0].incident_id,
                         entries=len(timeline), model=settings.DRAFTER_MODEL)
    return out


def render_markdown(d: PostmortemDraft) -> str:
    """Render for the pull request a human will review."""
    lines = [f"# {d.title}", "", "## Summary", d.summary, "", "## Impact", d.impact, ""]
    lines += ["## Contributing factors", ""]
    lines += [f"- {f}" for f in d.contributing_factors] + [""]
    lines += ["## Timeline", ""]
    lines += [f"- {t}" for t in d.timeline_highlights] + [""]
    if d.action_items:
        lines += ["## Action items", "", "| Action | Owner role | Due |", "|---|---|---|"]
        lines += [f"| {a.description} | {a.owner_role} | {a.due} |" for a in d.action_items]
        lines += [""]
    if d.open_questions:
        lines += ["## Open questions", ""]
        lines += [f"- {q}" for q in d.open_questions] + [""]
    footer = (
        "*Drafted by incident-scribe from the channel timeline. Review and edit "
        "before merging — this draft asserts only what the timeline supports.*"
    )
    lines += ["---", "", footer]
    return "\n".join(lines)
