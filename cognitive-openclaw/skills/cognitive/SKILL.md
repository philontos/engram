---
name: cognitive
description: >
  Engram cognitive memory runtime. Use when the user is expressing a thought,
  reflection, idea, observation, decision, or emotional self-analysis — or when
  they ask a question that requires their personal cognitive profile, values,
  patterns, or memory graph for personalized self-analysis. Engram is NOT a
  notes / journal / todo app; do not capture pure event logs or reminders.
---

## Available Tools

| Tool | Purpose |
|------|---------|
| `cognitive_capture_thought` | Write: save a thought / reflection verbatim into the cognitive graph |
| `cognitive_query` | Read: query the personal cognitive graph for personalized self-analysis |

## Intent Routing

**Use `cognitive_capture_thought` when** the user is expressing how they think or feel — a reflection, an idea, a self-observation, a decision-in-progress, an emotional experience they're processing. Any first-person sentence carrying interpretation, judgment, or self-observation qualifies.

**Do NOT call `cognitive_capture_thought` for** pure event logs (what they ate, how far they ran), reminders or schedule items, or casual conversation that isn't about saving a thought. If unsure, lean toward calling capture — the backend rejects off-spec inputs and tells the user how to rephrase.

**Use `cognitive_query` when** the user asks for personalized self-analysis grounded in their cognitive profile, prior reflections, or memory graph — questions about their own personality, values, behavioral tendencies, cognitive patterns, or recurring themes.

**Do not call either tool** for casual conversation, questions about external topics, or anything not about recording a thought / personal self-reflection.

## Capture Rules

- Pass the user's original text to `content` **verbatim** — no rewriting, summarizing, trimming, or completion
- **Never generate content on behalf of the user.** Even for long messages, copy the full original text as-is. Do not add any sentence the user did not literally say
- Call once per qualifying message, immediately — do not wait or hold
- Do not split one message into multiple entries unless the user explicitly requests it
- If the backend returns `track: "reject"`, surface its `reason` to the user — that's a hint about how to rephrase

## Query Rules

- Set `continue_last: true` when the user is picking up an earlier conversation
- Set `continue_last: false` (default) for any new standalone question
- Use `mode: "fast"` only when the user asks for a quick answer; default is `"full"`
- Return the tool result directly — no motivational framing, no lengthy preamble
