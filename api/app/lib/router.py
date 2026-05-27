"""Entry router: tags an entry's statements/spans with multiple lenses.

Replaces the old binary intent gate. The router NEVER rejects — every capture
becomes an entry. One LLM call per entry produces N signals, each carrying a
lens (content_type) plus an effort strength (0-1). Admission is delegated
downstream: each consumer applies its own effort threshold (see entry_signals
and process_entry; only the `cognitive` consumer is wired this cycle).

Fallback: when the LLM is unconfigured, the call errors, returns a non-list, or
yields zero valid signals, route() returns ONE `cognitive` signal at effort 0.5
spanning the full content. This mirrors the old gate's "fall back to entry,
don't lose data" behavior and keeps the cognitive flow running when the LLM is
down.

route(content) -> [{"lens": str, "effort": float, "span": str|None,
                    "payload": dict}, ...]
"""

from shared.llm import chat_json, is_structured_llm_configured

# Canonical lens enum — English (AGENTS.md rule #2). No reject / factual / mixed.
LENSES = (
    "cognitive",           # thinking / reflection / value judgment
    "outcome",             # event result / project completion / experiment data
    "retrospective",       # looking back on the past
    "method_in_use",       # "I used method X to handle Y"
    "intent_express",      # directional intent / commitment
    "relationship_event",  # an interaction event with a known person
)

# Threshold the cognitive consumer (slice + backbone) applies. Other downstream
# roots (open_loop_extract, case_extract, …) define their own; not wired here.
COGNITIVE_MIN_EFFORT = 0.3

_SYSTEM = """\
You are the router for Engram, a personal cognitive system. You receive one raw
entry (in any language) and tag the statements/segments inside it with one or
more "lenses". A single entry often spans multiple lenses at once — split by
statement/segment; do not force a single whole-entry label.

You NEVER reject. Every entry produces at least one signal. There is no
"reject", "factual", or "mixed" lens.

For each distinct signal, emit:
  - "lens": exactly one of the lenses below (English string).
  - "effort": a number 0.0-1.0 — how strongly/clearly this lens is present.
  - "span": the verbatim substring of the input this signal is drawn from.
  - "payload": an object; leave it as {} for now.

Lenses:
  - "cognitive": thinking, reflection, value judgment, working through an
    emotion, weighing a decision, an insight about how things work.
  - "outcome": an event result, project/experiment completion, a measurable
    result or data point.
  - "retrospective": looking back on / reviewing the past.
  - "method_in_use": "I used method/approach X to handle Y" — a concrete method
    being applied.
  - "intent_express": a directional intent, plan, or commitment ("I will…",
    "I promised…", "I plan to…").
  - "relationship_event": an interaction event with a specific known person.

Output a single JSON object exactly of this form:
  {"signals": [{"lens": "...", "effort": 0.0, "span": "...", "payload": {}}, ...]}

Quote the user's original text in "span" in its original language. Output JSON
only — no markdown, no prose.
"""


def _clamp_effort(value) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _fallback(content: str) -> list[dict]:
    return [{"lens": "cognitive", "effort": 0.5, "span": content, "payload": {}}]


def _normalize(raw_signals: list) -> list[dict]:
    signals: list[dict] = []
    for item in raw_signals:
        if not isinstance(item, dict):
            continue
        lens = item.get("lens")
        if lens not in LENSES:
            continue
        span = item.get("span")
        payload = item.get("payload")
        signals.append({
            "lens": lens,
            "effort": _clamp_effort(item.get("effort", 0.0)),
            "span": span if isinstance(span, str) else None,
            "payload": payload if isinstance(payload, dict) else {},
        })
    return signals


async def route(content: str) -> list[dict]:
    """Tag `content` with lens signals. Never raises; always returns >= 1 signal."""
    if not is_structured_llm_configured():
        return _fallback(content)
    try:
        result = await chat_json(
            system_prompt=_SYSTEM,
            user_prompt=content,
            stage="router",
        )
        # chat_json returns a JSON object; the prompt wraps the array under
        # "signals", but tolerate a bare list too.
        raw_signals = result.get("signals", []) if isinstance(result, dict) else result
        if not isinstance(raw_signals, list):
            return _fallback(content)
        signals = _normalize(raw_signals)
        return signals or _fallback(content)
    except Exception:
        return _fallback(content)
