"""Message classification and neutralisation.

Two jobs the chapter separates on purpose:
  classify_message  — is this incident-relevant, and what kind of event is it?
  neutralize        — rewrite into third-person neutral voice, drop names

Both are small, fast calls. `classify_message` returning None is the common
case: most messages in an incident channel are not timeline events.
"""

from __future__ import annotations

import re

from .schema import CATEGORIES

# Messages that are never timeline events. Cheap filter before any model call —
# the per-call economics rule from How to Read This Book, applied here.
_NOISE = re.compile(
    r"^\s*(lol|:[a-z0-9_+-]+:|\+1|ack|thanks?|ty|ok(ay)?|👍|😂|same|\.{1,3})\s*$",
    re.IGNORECASE,
)

# Redaction of the obvious mention forms before anything is stored.
_SLACK_MENTION = re.compile(r"<@[A-Z0-9]+>")
_AT_HANDLE = re.compile(r"(?<![\w/])@[A-Za-z][\w.-]{1,30}")


def is_noise(text: str) -> bool:
    return bool(_NOISE.match(text or ""))


def strip_identifiers(text: str) -> str:
    """Remove mention forms before storage.

    Defence in depth. The drafter is also instructed not to use names, but a
    prompt instruction is not a guarantee and this runs before persistence.
    """
    text = _SLACK_MENTION.sub("a responder", text)
    text = _AT_HANDLE.sub("a responder", text)
    return text.strip()


async def classify_message(text: str) -> str | None:
    """Return one of CATEGORIES, or None when the message is not a timeline event."""
    if is_noise(text):
        return None
    return await _classify_via_model(text)


async def _classify_via_model(text: str) -> str | None:
    """Schema-constrained classification.

    Offline default uses keyword heuristics so the lab runs against recorded
    threads without an API key; wire the real call by setting a key and
    replacing this body. The contract — one of CATEGORIES or None — is what the
    rest of the pipeline depends on, not the implementation.
    """
    t = (text or "").lower()
    if any(k in t for k in ("alert", "paged", "firing", "detected", "noticed")):
        return "detection"
    if any(k in t for k in ("maybe", "i think", "suspect", "hypothesis", "could be", "looks like")):
        return "hypothesis"
    if any(k in t for k in ("rolled back", "restarted", "scaled", "deployed", "ran ", "disabled")):
        return "action"
    if any(k in t for k in ("decided", "we'll", "we will", "going with", "agreed")):
        return "decision"
    if any(k in t for k in ("error rate", "latency", "recovered", "still", "now at", "back to")):
        return "observation"
    return None


def neutralize(text: str) -> str:
    """Third-person neutral voice, identifiers removed.

    The offline form is redaction only; the production form adds a Haiku-class
    rewrite. Redaction is the part that must not be skipped, so it lives here
    rather than in the prompt.
    """
    assert set(CATEGORIES)  # categories are the shared contract with the store
    return strip_identifiers(text)
