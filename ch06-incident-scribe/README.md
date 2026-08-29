# Chapter 6 — Incident scribe (Lab)

Companion code for *Self-Healing Infrastructure* Chapter 6. Reads an incident
channel, builds a structured timeline, surfaces what is missing while the
incident is live, and drafts a blameless postmortem for human review.

## What makes it blameless is structural, not a prompt

The drafter's system prompt says "no proper nouns for individuals." That is an
instruction, and instructions are not guarantees. Two things enforce it:

1. **`TimelineEntry` has an `actor_role` field and no field capable of holding
   a name.** There is nowhere to put one. A test asserts this.
2. **Identifiers are stripped before persistence**, not before rendering. By the
   time anything reaches the model, the mentions are already gone.

Prompt rule plus structure plus a test. Any one alone is a hope.

## Layout

```
ch06-incident-scribe/
├── src/incident_scribe/
│   ├── schema.py      # TimelineEntry, PostmortemDraft (tool-schema constrained)
│   ├── classifier.py  # noise filter, category classification, redaction
│   ├── store.py       # the timeline as a first-class artifact
│   ├── watcher.py     # Stage 1 — ingest; Slack is only a transport
│   ├── nudge.py       # Stage 2 — bounded, dismissible reminders
│   ├── drafter.py     # Stage 3 — draft + markdown render for a PR
│   └── audit.py       # Stage 4 — every action emitted to the Ch 4 surface
├── fixtures/threads/  # a recorded incident thread
└── tests/
```

## Quick start

No Slack workspace, no API key:

```bash
python3.12 -m venv ~/.venvs/ch06-incident-scribe
~/.venvs/ch06-incident-scribe/bin/pip install pydantic pydantic-settings \
    structlog httpx pytest pytest-asyncio
~/.venvs/ch06-incident-scribe/bin/python -m pytest -q
```

Do not create the venv inside this directory — the repo is under an
iCloud-synced path and editable installs break there.

## Why recorded threads are the default

Not a compromise. Iterating on a drafting prompt requires running it against
the *same* input twice, which a live channel cannot give you. Recorded threads
are what make the regression discipline from Chapter 3 possible here. Connect a
real workspace once the output is stable, with a bot token scoped to read
channel history and post messages.

## The nudge budget

Never more than one nudge per check, never more than three per incident, always
framed so the team can dismiss it. An unbounded nudger gets muted, and a muted
bot cannot surface the thing that actually mattered. `NUDGE_MAX_PER_INCIDENT`
is enforced in `nudge.py` and pinned by a test.

## Offline classification

`_classify_via_model` ships a keyword heuristic so the lab runs with no API key.
The contract — one of five categories, or `None` for a non-event — is what the
pipeline depends on; swap the body for a schema-constrained model call and
nothing downstream changes. The noise filter runs *before* any model call,
which is the per-call-economics rule applied to the highest-volume surface in
the system.

## Relationship to `ajinb/incident-scribe`

The standalone repo at <https://github.com/ajinb/incident-scribe> is the
general-purpose tool. This directory is the book's version: the pieces
Chapter 6 argues about, with the privacy properties and the audit emission as
the headline tests.

## License

Apache-2.0.
