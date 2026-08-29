"""The tests that matter for this service.

A green happy path proves the model call works. These prove the alert still
reaches the on-call when it doesn't — which is the property the whole design
exists to guarantee.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

from alert_explainer.breaker import AsyncCircuitBreaker, BreakerOpen, model_breaker
from alert_explainer.context import ContextBudgetExceeded, gather_context
from alert_explainer.render import render_for_pagerduty
from alert_explainer.schema import Alert, AlertmanagerPayload, TriageBrief
from alert_explainer.service import app

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _reset_breaker():
    model_breaker.reset()
    yield
    model_breaker.reset()


@pytest.fixture
def client():
    return TestClient(app)


# --- the headline behaviour -------------------------------------------------

def test_passthrough_when_breaker_open(client, monkeypatch):
    """Breaker open -> the on-call still gets paged, with the raw alert."""
    monkeypatch.setattr(model_breaker, "_opened_at", time.monotonic())

    r = client.post("/enrich", json=fixture("alertmanager.json"))
    body = r.json()

    assert r.status_code == 200
    assert body["enriched"][0]["description"].startswith("HighErrorRate")
    assert "verification steps" not in body["enriched"][0]["description"].lower()
    assert body["enriched"][0]["enriched"] is False


def test_alert_always_leaves_the_service_even_on_unexpected_error(client, monkeypatch):
    """Any unexpected failure degrades to passthrough rather than dropping the page."""
    async def boom(_alert):
        raise RuntimeError("context store is down")

    monkeypatch.setattr("alert_explainer.service.gather_context", boom)
    body = client.post("/enrich", json=fixture("alertmanager.json")).json()

    assert len(body["enriched"]) == 1
    assert body["enriched"][0]["enriched"] is False
    assert "HighErrorRate" in body["enriched"][0]["description"]


# --- breaker semantics ------------------------------------------------------

async def test_breaker_opens_after_fail_max_and_then_short_circuits():
    b = AsyncCircuitBreaker(fail_max=3, reset_timeout=30)

    async def failing():
        raise ConnectionError("provider unavailable")

    for _ in range(3):
        with pytest.raises(ConnectionError):
            await b.call(failing)

    with pytest.raises(BreakerOpen):          # 4th call short-circuits
        await b.call(failing)


async def test_logic_errors_do_not_trip_the_breaker():
    """A bad schema is our bug, not a provider outage. Tripping on it would
    take out enrichment for everyone because one alert was malformed."""
    b = AsyncCircuitBreaker(fail_max=2, reset_timeout=30)

    async def bad_shape():
        raise ValueError("schema mismatch")

    for _ in range(5):
        with pytest.raises(ValueError):
            await b.call(bad_shape)

    assert b._opened_at is None                # still closed


async def test_breaker_half_opens_after_reset_window():
    b = AsyncCircuitBreaker(fail_max=1, reset_timeout=0.05)

    async def failing():
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        await b.call(failing)
    with pytest.raises(BreakerOpen):
        await b.call(failing)

    await asyncio.sleep(0.06)                   # past the reset window

    async def ok():
        return "recovered"

    assert await b.call(ok) == "recovered"
    assert b._failures == 0


# --- context budget ---------------------------------------------------------

async def test_context_budget_refuses_rather_than_truncates(monkeypatch):
    """Truncation yields a confident answer built on whatever happened to fit."""
    monkeypatch.setattr("alert_explainer.context.settings.MAX_CONTEXT_TOKENS", 10)
    alert = Alert(**fixture("alertmanager.json")["alerts"][0])

    with pytest.raises(ContextBudgetExceeded):
        await gather_context(alert)


async def test_context_is_retrieved_for_a_known_alert():
    alert = Alert(**fixture("alertmanager.json")["alerts"][0])
    ctx = await gather_context(alert)
    assert ctx["runbooks"][0]["id"] == "RB-114"


# --- rendering --------------------------------------------------------------

def test_enriched_render_keeps_the_raw_alert_on_top():
    """Brief on top, raw underneath — the raw text is never replaced."""
    alert = Alert(**fixture("alertmanager.json")["alerts"][0])
    brief = TriageBrief(
        probable_cause="Deploy a3f9c2 introduced a null check regression.",
        confidence="medium",
        blast_radius="Card payments failing for ~23% of requests.",
        verification_steps=["Check deploy a3f9c2 diff", "Compare error ratio pre/post"],
        suggested_runbook="RB-114",
    )
    out = render_for_pagerduty(alert, brief)

    assert out["description"].startswith("HighErrorRate")   # raw first
    assert "Probable cause (medium confidence)" in out["description"]
    assert "RB-114" in out["description"]
    assert out["enriched"] is True


def test_multiple_alerts_are_each_rendered():
    payload = fixture("alertmanager.json")
    payload["alerts"].append(dict(payload["alerts"][0]))
    payload["alerts"][1]["labels"] = {"alertname": "DiskFull", "severity": "warning"}

    parsed = AlertmanagerPayload(**payload)
    assert len(parsed.alerts) == 2
    assert parsed.alerts[1].name == "DiskFull"
