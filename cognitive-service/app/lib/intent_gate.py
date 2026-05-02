"""Entry intent gate: decides whether an input is a real reflection / thought.

Engram only stores cognitive signal — thoughts, reflections, ideas, observations,
decisions, emotional self-analysis. Inputs that are pure event logs / reminders
/ factual notes are rejected; the user is asked to either rephrase as a thought
or log them in another tool.

Output:
  {"track": "entry" | "reject", "reason": "<one short sentence>"}
"""

from shared.llm import chat_json, is_structured_llm_configured

_SYSTEM = """\
You are an intent classifier for Engram, a personal *cognitive* capture system.
The system only stores thoughts, reflections, ideas, observations, decisions,
or emotional self-analysis — content that reveals how the user thinks.

Classify the input into exactly one track. Output strict JSON only:
{"track": "entry" | "reject", "reason": "<one short sentence>"}

## entry — accept and store
The user is PROCESSING something cognitive: expressing a view, working through
an emotion, reflecting on a pattern, weighing a decision, narrating an
experience with self-observation, or sharing an insight. Any first-person
sentence with self-observation, judgment, or interpretation qualifies.

## reject — refuse politely
The input is a pure event log, fact, reminder, schedule item, or measurement —
no reflection, no judgment, no emotional processing. Engram is not a notes app.
A bare emotion tag with no elaboration ("I'm tired") is also rejected; ask the
user to expand into the thought behind the feeling.

## Borderline rule
When in doubt, prefer **entry**. Do not reject content that contains even one
sentence of self-observation or interpretation. The user is here because they
want to think out loud — give them the benefit of the doubt.

The "reason" field, when track="reject", explains in ONE sentence what kind of
reflection would make this entry-worthy. Match the user's input language.
"""


async def classify(content: str) -> dict:
    """Returns {"track": "entry"|"reject", "reason": str}.
    Falls back to "entry" when the LLM is unavailable (don't lose data)."""
    if not is_structured_llm_configured():
        return {"track": "entry", "reason": "llm not configured, fallback to entry"}

    try:
        result = await chat_json(
            system_prompt=_SYSTEM,
            user_prompt=content,
            stage="intent_gate",
        )
        track = result.get("track", "entry")
        if track not in ("entry", "reject"):
            track = "entry"
        return {"track": track, "reason": result.get("reason", "")}
    except Exception:
        return {"track": "entry", "reason": "classification failed, fallback to entry"}
