"""Tests for the scribe.

The properties worth pinning are the ones that make a postmortem blameless and
an audit trail complete — not whether the model writes nice prose.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from incident_scribe.audit import emitted, reset_audit
from incident_scribe.classifier import (
    classify_message,
    is_noise,
    neutralize,
    strip_identifiers,
)
from incident_scribe.config import settings
from incident_scribe.drafter import format_timeline, render_markdown
from incident_scribe.nudge import maybe_nudge
from incident_scribe.schema import ActionItem, PostmortemDraft, TimelineEntry
from incident_scribe.store import store
from incident_scribe.watcher import ingest_message, ingest_thread, is_incident_channel

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
THREAD = json.loads((FIXTURES / "threads" / "incident-2026-03-30-payments.json").read_text())


@pytest.fixture(autouse=True)
def _clean():
    store.reset()
    reset_audit()
    yield
    store.reset()
    reset_audit()


def _entry(cat, content, minutes_ago=0, role="on-call SRE"):
    return TimelineEntry(
        incident_id="incident-x",
        timestamp=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        category=cat,
        content=content,
        actor_role=role,
    )


# --- privacy: the property that makes it blameless --------------------------

def test_slack_mentions_are_stripped_before_storage():
    assert "<@U01>" not in strip_identifiers("thanks <@U01>")
    assert "a responder" in strip_identifiers("thanks <@U01>")


def test_neutralize_redacts_before_anything_is_stored():
    assert "<@U01>" not in neutralize("thanks <@U01>")


def test_at_handles_are_stripped():
    out = strip_identifiers("@alice rolled it back")
    assert "@alice" not in out
    assert out.startswith("a responder")


def test_timeline_has_no_field_that_can_hold_a_name():
    """Structural, not a prompt instruction: there is nowhere to put a name."""
    fields = set(TimelineEntry.model_fields)
    assert "actor_role" in fields
    assert not {"user", "username", "actor_name", "author"} & fields


async def test_ingested_thread_carries_no_raw_mentions():
    await ingest_thread(THREAD)
    timeline = await store.get(THREAD["channel"])
    assert timeline, "expected some entries"
    assert not any("<@" in e.content for e in timeline)


# --- classification ---------------------------------------------------------

@pytest.mark.parametrize("noise", ["lol", ":+1:", "thanks", "ok", "👍", "..."])
def test_noise_is_filtered_without_a_model_call(noise):
    assert is_noise(noise)


async def test_noise_messages_never_reach_the_timeline():
    assert await classify_message("lol") is None
    assert await classify_message(":+1:") is None


async def test_events_are_classified_into_the_contract():
    assert await classify_message("paged: HighErrorRate firing") == "detection"
    assert await classify_message("i think it's the deploy") == "hypothesis"
    assert await classify_message("rolled back payments-api") == "action"


async def test_non_incident_channels_are_ignored():
    assert not is_incident_channel("general")
    out = await ingest_message(
        channel_name="general", text="rolled back payments-api",
        actor_role="on-call SRE", ts="2026-03-30T03:24:00Z",
    )
    assert out is None


async def test_recorded_thread_produces_a_usable_timeline():
    entries = await ingest_thread(THREAD)
    cats = {e.category for e in entries}
    assert {"detection", "hypothesis", "action"} <= cats
    assert len(entries) < len(THREAD["messages"])  # noise was dropped


# --- nudges are bounded -----------------------------------------------------

async def test_no_nudge_before_the_timeline_has_substance():
    for i in range(3):
        await store.append(_entry("observation", f"thing {i}"))
    assert await maybe_nudge("incident-x") is None


async def test_nudges_stop_at_the_per_incident_budget():
    for i in range(6):
        await store.append(_entry("observation", f"thing {i}", minutes_ago=40))
    fired = 0
    for _ in range(10):
        if await maybe_nudge("incident-x"):
            fired += 1
    assert fired == settings.NUDGE_MAX_PER_INCIDENT


async def test_nudge_is_framed_as_dismissible():
    for i in range(6):
        await store.append(_entry("observation", f"thing {i}", minutes_ago=40))
    text = await maybe_nudge("incident-x")
    assert text and "dismiss" in text.lower()


async def test_no_hypothesis_nudge_once_a_hypothesis_exists():
    for i in range(5):
        await store.append(_entry("observation", f"thing {i}", minutes_ago=40))
    await store.append(_entry("hypothesis", "suspect the deploy", minutes_ago=30))
    assert await maybe_nudge("incident-x") is None


# --- audit completeness -----------------------------------------------------

async def test_every_classified_message_is_audited():
    entries = await ingest_thread(THREAD)
    classified = [e for e in emitted() if e["action"] == "message_classified"]
    assert len(classified) == len(entries)


async def test_nudges_are_audited():
    for i in range(6):
        await store.append(_entry("observation", f"thing {i}", minutes_ago=40))
    await maybe_nudge("incident-x")
    assert any(e["action"] == "nudge_posted" for e in emitted())


# --- drafting ---------------------------------------------------------------

def test_draft_requires_contributing_factors_and_timeline():
    """An empty draft must not validate: a postmortem with no contributing
    factors is a status update wearing a postmortem's title."""
    with pytest.raises(ValidationError):
        PostmortemDraft(title="t", summary="s", impact="i",
                        contributing_factors=[], timeline_highlights=[])


def test_rendered_markdown_says_it_is_a_draft_for_review():
    d = PostmortemDraft(
        title="payments-api error spike",
        summary="A deploy introduced a regression; it was rolled back.",
        impact="~23% of card payments failed for 15 minutes.",
        contributing_factors=["A release introduced an unguarded null path."],
        timeline_highlights=["03:14 alert fired", "03:24 rollback"],
        action_items=[ActionItem(description="Add a regression test",
                                 owner_role="service owner", due="2026-04-06")],
        open_questions=["Why did the canary not catch this?"],
    )
    md = render_markdown(d)
    assert "Review and edit before merging" in md
    assert "Open questions" in md
    assert "service owner" in md


def test_formatted_timeline_exposes_roles_not_names():
    line = format_timeline([_entry("action", "rolled back the release")])
    assert "(on-call SRE)" in line
