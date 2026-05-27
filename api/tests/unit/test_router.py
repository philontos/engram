"""route() parsing, effort clamping, bad-lens drop, and fallback behavior.

router.py is DB-free, so these tests need no `db` fixture. chat_json and
is_structured_llm_configured are patched on the router module namespace.
"""

import pytest
from unittest.mock import AsyncMock, patch

import app.lib.router as router


@pytest.mark.asyncio
async def test_route_parses_clamps_and_drops_bad_lens():
    fake = {"signals": [
        {"lens": "cognitive",          "effort": 0.85, "span": "a", "payload": {}},
        {"lens": "intent_express",     "effort": 1.5,  "span": "b", "payload": {}},
        {"lens": "relationship_event", "effort": -0.2, "span": "c"},
        {"lens": "reject",             "effort": 0.9,  "span": "d"},   # bad lens → dropped
        {"lens": "method_in_use",      "effort": "oops", "span": "e"}, # non-numeric → 0.0
    ]}
    with patch.object(router, "is_structured_llm_configured", return_value=True), \
         patch.object(router, "chat_json", new=AsyncMock(return_value=fake)):
        signals = await router.route("some text")

    lenses = [s["lens"] for s in signals]
    assert "reject" not in lenses
    assert len(signals) == 4
    by_lens = {s["lens"]: s for s in signals}
    assert by_lens["cognitive"]["effort"] == 0.85
    assert by_lens["intent_express"]["effort"] == 1.0       # clamped down
    assert by_lens["relationship_event"]["effort"] == 0.0   # clamped up
    assert by_lens["method_in_use"]["effort"] == 0.0        # non-numeric → 0.0
    assert by_lens["relationship_event"]["payload"] == {}   # missing payload → {}


@pytest.mark.asyncio
async def test_route_fallback_when_unconfigured():
    with patch.object(router, "is_structured_llm_configured", return_value=False):
        signals = await router.route("full content here")
    assert len(signals) == 1
    assert signals[0]["lens"] == "cognitive"
    assert signals[0]["effort"] == 0.5
    assert signals[0]["span"] == "full content here"
    assert signals[0]["payload"] == {}


@pytest.mark.asyncio
async def test_route_fallback_on_exception():
    with patch.object(router, "is_structured_llm_configured", return_value=True), \
         patch.object(router, "chat_json", new=AsyncMock(side_effect=RuntimeError("boom"))):
        signals = await router.route("content")
    assert len(signals) == 1
    assert signals[0]["lens"] == "cognitive"


@pytest.mark.asyncio
async def test_route_fallback_on_empty_signals():
    with patch.object(router, "is_structured_llm_configured", return_value=True), \
         patch.object(router, "chat_json", new=AsyncMock(return_value={"signals": []})):
        signals = await router.route("content")
    assert len(signals) == 1
    assert signals[0]["lens"] == "cognitive"


@pytest.mark.asyncio
async def test_route_accepts_bare_list():
    fake = [{"lens": "outcome", "effort": 0.7, "span": "shipped v1"}]
    with patch.object(router, "is_structured_llm_configured", return_value=True), \
         patch.object(router, "chat_json", new=AsyncMock(return_value=fake)):
        signals = await router.route("content")
    assert len(signals) == 1
    assert signals[0]["lens"] == "outcome"
    assert signals[0]["effort"] == 0.7
