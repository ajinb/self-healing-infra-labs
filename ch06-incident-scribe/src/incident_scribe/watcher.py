"""Stage 1 — the watcher.

In production this is a Slack Bolt app subscribed to `incident-*` channels.
`ingest_message` is the part worth testing, so it is separated from the Bolt
binding: the classification, redaction, and persistence happen here and the
Slack SDK is only a transport.
"""

from __future__ import annotations

from datetime import datetime

from .audit import emit_audit
from .classifier import classify_message, neutralize
from .schema import TimelineEntry
from .store import store


def is_incident_channel(channel_name: str) -> bool:
    return channel_name.startswith("incident-")


async def ingest_message(
    *, channel_name: str, text: str, actor_role: str, ts: str
) -> TimelineEntry | None:
    """Classify one message and append it to the timeline if it is an event.

    Returns None for non-incident channels and non-events, which is the
    majority of traffic.
    """
    if not is_incident_channel(channel_name):
        return None

    category = await classify_message(text)
    if category is None:
        return None

    entry = TimelineEntry(
        incident_id=channel_name,
        timestamp=datetime.fromisoformat(ts.removesuffix("Z") + "+00:00")
        if ts.endswith("Z")
        else datetime.fromisoformat(ts),
        category=category,
        content=neutralize(text),
        actor_role=actor_role,
    )
    await store.append(entry)
    await emit_audit("message_classified", channel_name,
                     category=category, actor_role=actor_role)
    return entry


async def ingest_thread(thread: dict) -> list[TimelineEntry]:
    """Replay a recorded thread. This is how the lab runs without Slack."""
    out = []
    for m in thread["messages"]:
        entry = await ingest_message(
            channel_name=thread["channel"],
            text=m["text"],
            actor_role=m.get("role", "responder"),
            ts=m["ts"],
        )
        if entry is not None:
            out.append(entry)
    return out


def build_bolt_app():  # pragma: no cover - requires a live workspace
    """The Slack binding. Kept thin: it resolves names to roles and delegates."""
    from slack_bolt.async_app import AsyncApp

    from .config import settings

    app = AsyncApp(token=settings.SLACK_BOT_TOKEN, signing_secret=settings.SLACK_SIGNING_SECRET)

    @app.event("message")
    async def on_message(event, client):
        if event.get("channel_type") != "channel":
            return
        info = await client.conversations_info(channel=event["channel"])
        await ingest_message(
            channel_name=info["channel"]["name"],
            text=event.get("text", ""),
            actor_role=await _resolve_role(client, event.get("user")),
            ts=event["ts"],
        )

    return app


async def _resolve_role(client, user_id):  # pragma: no cover
    """Look up the directory role. Returns role strings, never names."""
    profile = await client.users_info(user=user_id)
    return profile["user"]["profile"].get("title") or "responder"
