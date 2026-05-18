"""Cognitive agent runtime.

Replaces the multi-stage query_pipeline with a single agent loop that owns
its own decisions: which tools to call, in what order, when to stop, what
voice to answer in. The runtime here is just plumbing — the intelligence
lives in the system prompt and the tool descriptions.

Streamed events (NDJSON-friendly dicts):

  {type:"agent_start",  session_id, question}
  {type:"intent_check", intent, mode, message}
  {type:"round_start",  round}
  {type:"delta",        round, phase:"intermediate", delta}     # text content
  {type:"tool_call",    round, call_id, tool, args}
  {type:"tool_result",  round, call_id, tool, summary, detail, latency_ms}
  {type:"round_end",    round, finish_reason, had_tool_calls, latency_ms}
  {type:"done",         session_id, log_id, final_round_index, total_rounds}
  {type:"error",        message, where}

The frontend treats `delta` events from the FINAL round as the canonical
answer and renders prior rounds as collapsible "thinking" panels.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from app.lib.agent_tools import AGENT_TOOLS, ToolContext, execute_tool
from app.lib.db import get_conn
from app.lib.slice_pipeline import get_mood_stats, get_profile_summary
from app.lib.trace_recorder import TraceRecorder
from shared.llm import (
    chat_json,
    chat_with_tools_stream,
    is_structured_llm_configured,
)

MAX_ROUNDS         = 8
MAX_HISTORY_TURNS  = 20    # how many prior turns we surface in the brief
RECENT_FULL_TURNS  = 2     # most-recent N turns also injected as full Q+A pairs

_VALID_MODES = {"factual", "reflective", "exploratory"}

# Intent gate (cheap classifier; routes obvious off-topic / clarify cases away
# from the full agent loop so we don't burn tokens on greetings).
_INTENT_SYSTEM = """\
You are an intent classifier for a personal cognitive analysis system.
Classify the user's input. Output strict JSON only, no other text:
{"intent": "proceed" | "clarify" | "off_topic", "mode": "factual" | "reflective" | "exploratory", "message": "..."}

## intent
proceed: Input has clear self-exploration / cognition / decision-making intent, specific enough to analyze.
  Special case: if the conversation history contains a concept/framework/methodology the system mentioned,
  and the user asks "what is X" or "explain X" — this is cognitive exploration, always classify as proceed.
  message: leave empty.
clarify: Has analytical potential but too vague to analyze. message: one concise follow-up question, matching the user's input language.
off_topic: Greetings / small talk / test input / meaningless / unrelated to personal cognition.
  Even if conversation history exists, judge by the current input itself.
  message: brief friendly note, matching the user's input language.

## mode (only meaningful when intent=proceed; default to "reflective" for other intents)
factual: Asks about how the world works — facts, definitions, mechanisms, possibility.
reflective: Asks for self-diagnosis / advice / decisions about themselves.
exploratory: Records a thought, observation, or musing — not really asking but inviting connection.

When in doubt between any two, default to reflective."""


def _load_history_from_db(session_id: str, max_turns: int = MAX_HISTORY_TURNS) -> list[dict]:
    """Load prior 'proceed' turns of a session, oldest first."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT turns_json FROM query_logs WHERE session_id=?", (session_id,)
        ).fetchone()
    if not row:
        return []
    try:
        turns = json.loads(row["turns_json"] or "[]")
    except Exception:
        turns = []
    proceed_turns = [
        {
            "question": t.get("question", ""),
            "answer":   t.get("response", ""),
            "distill":  t.get("distill") or {},
        }
        for t in turns
        if t.get("intent") == "proceed"
    ]
    return proceed_turns[-max_turns:]


# ---------------------------------------------------------------------------
# System prompt — the agent's identity and operating principles
# ---------------------------------------------------------------------------

_AGENT_SYSTEM_BASE = """\
You are a senior cognitive advisor who has been tracking this user's mind for
a long time. Your expertise spans psychology, decision science, philosophy,
and behavioral economics. You know this user more intimately than any external
consultant could: you can pull up every word they have written
(recall_raw / recall_raw_by_node), inspect their cognitive graph
(search_graph / expand_node / get_node_neighborhood / get_opposites /
compare_nodes / list_blindspots / list_bridges), run a focused personality
lens (get_persona_lens), trace concrete evolution paths through their beliefs
(find_evolution_paths), search the public web when needed (web_search), and
re-open prior turns of this same session in increasing detail
(recall_history_answer / recall_history_tools / recall_history_tool_detail).

## The user (core profile)
{profile_block}

## How you work
- Speak as if face-to-face. Do not write reports.
- Depth follows the complexity of the question, not your urge to display.
- Before answering, you ground yourself in the user: pull relevant raw entries,
  the persona lens, and the graph nodes / tensions that bear on the question.
  Speaking without grounding is dereliction.
- Tools are for fact-finding. The test of "should I call this" is "would my
  answer be wrong without it", not "how many tools should I use".
- Graph nodes carry origin=internal (the user's own beliefs / experiences)
  or origin=external (concepts they have referenced but may not have
  internalised). The internal↔external bridge edges mark the user's cognitive
  boundary — the highest-leverage zone for insight.
- When the user holds a high-strength internal belief with no opposing tension,
  proactively probe it with get_opposites or list_blindspots. This is what
  separates you from a generic advisor.
- Cite evidence by weaving it into prose ("you wrote…", "your X and Y are in
  tension…"). Do not invent section headers or bracketed labels.
- As an expert, name problems directly — but every judgement must be anchored
  in the user's own material, never generic advice or motivational filler.

## Hard requirements before answering
For any question that touches the user themselves (emotions, decisions,
personality, relationships, values), you must complete at least one of:
  (a) call recall_raw to see the user's own words
  (b) call get_persona_lens to obtain a personality lens for this question
For pure knowledge / factual questions you may skip this.

## Language
Always answer in the language the user asked in. Your internal reasoning,
tool arguments, and tool descriptions stay in English."""


def _profile_block(profile_summary: str, mood_stats: str) -> str:
    parts = []
    if profile_summary:
        parts.append(profile_summary.strip())
    if mood_stats:
        parts.append(f"\nRecent mood & journaling patterns:\n{mood_stats.strip()}")
    return "\n".join(parts) or "(no profile summary available yet)"


def _build_system_prompt(profile_summary: str, mood_stats: str,
                         history_brief: str = "") -> str:
    base = _AGENT_SYSTEM_BASE.format(
        profile_block=_profile_block(profile_summary, mood_stats),
    )
    if history_brief:
        return f"{base}\n\n{history_brief}"
    return base


async def _ensure_history_distilled(session_id: str, history: list[dict]) -> list[dict]:
    """Backfill distill for any historical turn that doesn't have one yet.

    Computed once per turn, then written back into the JSON column so subsequent
    sessions never re-run the distill LLM call. Robust against partial failure.
    """
    if not history:
        return history
    needs: list[tuple[int, dict]] = []
    for i, h in enumerate(history):
        if not h.get("distill") or not (h["distill"].get("summary")):
            needs.append((i, h))
    if not needs:
        return history
    # compute distills sequentially (cheap; avoids spawning tasks)
    for _, h in needs:
        d = await _distill_turn(h.get("question", ""), h.get("answer", "") or "")
        h["distill"] = d
    # write back into query_logs.turns_json
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, turns_json FROM query_logs WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if not row:
                return history
            try:
                turns = json.loads(row["turns_json"] or "[]")
            except Exception:
                return history
            # match by turn position; history is built from these turns in order
            proceed_positions = [i for i, t in enumerate(turns) if t.get("intent") == "proceed"]
            for hist_idx, h in enumerate(history):
                if hist_idx < len(proceed_positions):
                    pos = proceed_positions[hist_idx]
                    turns[pos]["distill"] = h.get("distill") or {}
            conn.execute(
                "UPDATE query_logs SET turns_json=? WHERE id=?",
                (json.dumps(turns, ensure_ascii=False), row["id"]),
            )
    except Exception:
        # backfill is best-effort
        pass
    return history


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_DISTILL_SYSTEM = """\
You compress one Q&A turn from a cognitive-advising session into a compact
record so a future turn can decide whether to pull more detail.

Output strict JSON only, no other text:
{"summary": "...", "key_nodes": [{"id": <int>, "label": "..."}, ...]}

Rules:
- summary: 60-100 words, in the language of the original answer. Capture the
  ACTUAL conclusion, not the topic. Mention the cognitive move (which belief
  was challenged, which framework was suggested, which tension was named).
  Avoid vague verbs like "discussed" / "explored".
- key_nodes: extract up to 5 graph node ids the answer explicitly referenced.
  If the answer cites no node ids, return [].
"""


async def _distill_turn(question: str, answer: str) -> dict:
    """Compute a compact summary of one turn. Returns {"summary", "key_nodes"}.

    Designed to be cheap (small LLM call). On failure returns a degraded record
    so the caller never blocks on this.
    """
    if not (question and answer):
        return {"summary": "", "key_nodes": []}
    user_prompt = f"## Question\n{question}\n\n## Answer\n{answer}"
    try:
        result = await chat_json(
            system_prompt=_DISTILL_SYSTEM,
            user_prompt=user_prompt,
            stage="agent:distill_turn",
        )
        summary = str(result.get("summary", "")).strip()
        nodes_raw = result.get("key_nodes") or []
        key_nodes: list[dict] = []
        for n in nodes_raw[:5]:
            if not isinstance(n, dict):
                continue
            try:
                key_nodes.append({"id": int(n["id"]), "label": str(n.get("label", ""))})
            except (KeyError, TypeError, ValueError):
                continue
        return {"summary": summary, "key_nodes": key_nodes}
    except Exception:
        # degrade — never block persistence on the distill call
        return {"summary": (answer or "")[:200], "key_nodes": []}


def _format_history_brief(history: list[dict]) -> str:
    """Render the prior turns as a compact session index.

    Each turn line: "Turn N: <question> → <distill.summary> (key: nodeA, nodeB)".
    Recent RECENT_FULL_TURNS turns are intentionally omitted here — the caller
    re-injects them as full Q+A messages.
    """
    if not history:
        return ""
    truncated = history[-MAX_HISTORY_TURNS:]
    older = truncated[:-RECENT_FULL_TURNS] if len(truncated) > RECENT_FULL_TURNS else []
    if not older:
        return ""
    lines = [f"## Session so far ({len(older)} earlier turn(s) — recent {RECENT_FULL_TURNS} are reproduced verbatim below)"]
    base_index = len(history) - len(truncated)
    for offset, h in enumerate(older):
        idx = base_index + offset
        q = (h.get("question") or "").strip().replace("\n", " ")
        if len(q) > 120:
            q = q[:117] + "..."
        distill = h.get("distill") or {}
        summary = (distill.get("summary") or "").strip()
        if not summary:
            # very short fallback if distill missing
            summary = (h.get("answer") or "")[:160].replace("\n", " ")
        key_nodes = distill.get("key_nodes") or []
        nodes_str = ""
        if key_nodes:
            labels = ", ".join(str(n.get("label", "")) for n in key_nodes if n.get("label"))
            if labels:
                nodes_str = f"  (key nodes: {labels})"
        lines.append(f"- **Turn {idx}**: \"{q}\" → {summary}{nodes_str}")
    lines.append("")
    lines.append(
        "Use `recall_history_answer(turn_index)` to read the full answer of any earlier turn, "
        "`recall_history_tools(turn_index)` to see what tools that turn called, "
        "and `recall_history_tool_detail(turn_index, tool_index)` to inspect one specific tool result."
    )
    return "\n".join(lines)


def _format_recent_full(history: list[dict]) -> list[dict]:
    """Most-recent RECENT_FULL_TURNS Q+A pairs as message-history entries."""
    if not history:
        return []
    recent = history[-RECENT_FULL_TURNS:]
    msgs: list[dict] = []
    for h in recent:
        msgs.append({"role": "user", "content": h.get("question", "")})
        msgs.append({"role": "assistant", "content": h.get("answer", "") or ""})
    return msgs


def _next_turn_index(session_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT turns_json FROM query_logs WHERE session_id=?", (session_id,)
        ).fetchone()
    if not row:
        return 0
    try:
        return len(json.loads(row["turns_json"] or "[]"))
    except Exception:
        return 0


def _persist_turn(
    session_id: str, question: str, mode: str, intent: str,
    answer: str, tool_trace: list[dict], distill: dict, is_new: bool,
) -> int | None:
    now = datetime.now(timezone.utc).isoformat()
    turn = {
        "question":   question,
        "intent":     intent,
        "mode":       mode,
        "response":   answer,
        "tool_calls": tool_trace,
        "distill":    distill,
        "created_at": now,
        "agent":      True,
    }
    with get_conn() as conn:
        if is_new:
            cur = conn.execute(
                """INSERT INTO query_logs
                   (session_id, question, mode, seeds_json, opposites_json,
                    blindspots_json, q1_text, q2_text, q3_text, q4_text,
                    turns_json, updated_at)
                   VALUES (?, ?, ?, '[]', '[]', '[]', '', '', ?, '', ?, ?)""",
                (session_id, question, mode, answer,
                 json.dumps([turn], ensure_ascii=False), now),
            )
            return cur.lastrowid
        row = conn.execute(
            "SELECT id, turns_json FROM query_logs WHERE session_id=?", (session_id,)
        ).fetchone()
        if not row:
            return None
        try:
            turns = json.loads(row["turns_json"] or "[]")
        except Exception:
            turns = []
        turns.append(turn)
        conn.execute(
            "UPDATE query_logs SET turns_json=?, q3_text=?, updated_at=? WHERE session_id=?",
            (json.dumps(turns, ensure_ascii=False), answer, now, session_id),
        )
        return row["id"]


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


async def run_agent(
    question: str, session_id: str | None = None,
) -> AsyncIterator[dict]:
    if not is_structured_llm_configured():
        yield {"type": "error", "message": "LLM is not configured", "where": "startup"}
        return

    is_new = not session_id
    if not session_id:
        session_id = str(uuid.uuid4())
    turn_index = _next_turn_index(session_id)
    recorder = TraceRecorder(session_id, turn_index)

    yield {"type": "agent_start", "session_id": session_id, "question": question,
           "turn_index": turn_index}

    # ------------------------------------------------------------------
    # Intent gate (cheap, kept from old pipeline so we don't burn tokens
    # running the full agent on greetings / off-topic input)
    # ------------------------------------------------------------------
    history = _load_history_from_db(session_id, max_turns=MAX_HISTORY_TURNS) if not is_new else []
    # Lazy backfill of distill for old turns persisted before distill was added.
    history = await _ensure_history_distilled(session_id, history)
    intent_input = question
    if history:
        recent = history[-1]
        intent_input = (
            f"## Prior turn\nUser: {recent.get('question','')}\nAssistant: "
            f"{(recent.get('answer','') or '')[:400]}\n\n## Current input\n{question}"
        )
    try:
        async with recorder.llm_round(round_num=0) as ev:
            ev.set_request({"system": _INTENT_SYSTEM, "user": intent_input})
            intent_result = await chat_json(
                system_prompt=_INTENT_SYSTEM,
                user_prompt=intent_input,
                stage="agent:intent_check",
            )
            ev.set_response(intent_result)
    except Exception as exc:
        intent_result = {"intent": "proceed", "message": "", "mode": "reflective"}
        yield {"type": "error", "message": f"intent classifier failed: {exc}",
               "where": "intent_check"}

    intent = intent_result.get("intent", "proceed")
    mode = intent_result.get("mode", "reflective")
    if mode not in _VALID_MODES:
        mode = "reflective"
    msg = (intent_result.get("message") or "").strip()
    yield {"type": "intent_check", "intent": intent, "mode": mode, "message": msg}

    if intent in ("off_topic", "clarify"):
        yield {"type": "delta", "round": 0, "phase": "answer", "delta": msg}
        try:
            log_id = _persist_turn(session_id, question, mode, intent, msg, [],
                                   {"summary": "", "key_nodes": []}, is_new)
        except Exception as exc:
            yield {"type": "error", "message": f"persist failed: {exc}", "where": "persist"}
            log_id = None
        try:
            recorder.flush()
        except Exception as exc:
            yield {"type": "error", "message": f"trace flush failed: {exc}", "where": "trace"}
        yield {"type": "done", "session_id": session_id, "log_id": log_id,
               "final_round_index": 0, "total_rounds": 0}
        return

    # ------------------------------------------------------------------
    # Build agent context + system prompt
    # ------------------------------------------------------------------
    profile_summary = get_profile_summary()
    mood_stats = get_mood_stats()
    history_brief = _format_history_brief(history)
    sys_prompt = _build_system_prompt(profile_summary, mood_stats, history_brief)

    ctx = ToolContext(
        question=question,
        profile_summary=profile_summary,
        mood_stats=mood_stats,
        session_id=session_id,
    )

    messages: list[dict] = [{"role": "system", "content": sys_prompt}]
    messages.extend(_format_recent_full(history))
    messages.append({"role": "user", "content": question})

    tool_trace: list[dict] = []
    final_round_index = 1

    # ------------------------------------------------------------------
    # Tool-use loop
    # ------------------------------------------------------------------
    for round_num in range(1, MAX_ROUNDS + 1):
        round_started = time.monotonic()
        yield {"type": "round_start", "round": round_num}

        assistant_message: dict | None = None
        finish_reason = "stop"

        try:
            async with recorder.llm_round(round_num=round_num) as ev:
                # snapshot inputs (without the system prompt's huge profile_block? keep it — debug is the point)
                ev.set_request({
                    "model_messages": messages,
                    "tools_count": len(AGENT_TOOLS),
                })
                async for stream_evt in chat_with_tools_stream(
                    messages=messages,
                    tools=AGENT_TOOLS,
                    stage=f"agent:round_{round_num}",
                ):
                    et = stream_evt["type"]
                    if et == "content_delta":
                        yield {"type": "delta", "round": round_num,
                               "phase": "intermediate", "delta": stream_evt["delta"]}
                    elif et == "tool_call_partial":
                        # quiet — frontend doesn't need partial JSON args; the
                        # consolidated tool_call event below carries full args.
                        pass
                    elif et == "done":
                        assistant_message = stream_evt["message"]
                        finish_reason = stream_evt["finish_reason"]
                        ev.set_response({
                            "finish_reason": finish_reason,
                            "message": assistant_message,
                            "usage": stream_evt.get("usage", {}),
                            "duration_ms": stream_evt.get("duration_ms", 0),
                        })
        except Exception as exc:
            yield {"type": "error", "message": f"round {round_num} failed: {exc}",
                   "where": f"round_{round_num}"}
            break

        if assistant_message is None:
            yield {"type": "error", "message": "no message returned",
                   "where": f"round_{round_num}"}
            break

        tool_calls = assistant_message.get("tool_calls") or []
        had_tool_calls = bool(tool_calls)
        round_latency = int((time.monotonic() - round_started) * 1000)

        yield {"type": "round_end", "round": round_num,
               "finish_reason": finish_reason,
               "had_tool_calls": had_tool_calls,
               "latency_ms": round_latency}

        if not had_tool_calls:
            final_round_index = round_num
            break

        # append assistant message before tool results (OpenAI protocol)
        messages.append(assistant_message)

        # execute every tool call this round
        for tc in tool_calls:
            tool_name = tc.get("function", {}).get("name", "")
            try:
                args = json.loads(tc.get("function", {}).get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            call_id = tc.get("id") or f"call_{round_num}_{tool_name}"

            yield {"type": "tool_call", "round": round_num,
                   "call_id": call_id, "tool": tool_name, "args": args}

            tool_started = time.monotonic()
            tool_result: dict
            try:
                async with recorder.tool_call(round_num=round_num, tool=tool_name) as tev:
                    tev.set_request(args)
                    tool_result = await execute_tool(tool_name, args, ctx)
                    tev.set_response(tool_result)
            except Exception as exc:
                tool_result = {
                    "summary": f"tool '{tool_name}' raised: {exc}",
                    "detail": {"error": str(exc)},
                    "llm_text": f"(tool failed: {exc})",
                }
            tool_latency = int((time.monotonic() - tool_started) * 1000)

            tool_trace.append({
                "round":       round_num,
                "tool":        tool_name,
                "args":        args,
                "summary":     tool_result.get("summary", ""),
                "latency_ms":  tool_latency,
            })

            yield {
                "type":        "tool_result",
                "round":       round_num,
                "call_id":     call_id,
                "tool":        tool_name,
                "summary":     tool_result.get("summary", ""),
                "detail":      tool_result.get("detail", {}),
                "latency_ms":  tool_latency,
            }

            # feed result back to the model
            messages.append({
                "role":         "tool",
                "tool_call_id": call_id,
                "content":      tool_result.get("llm_text") or tool_result.get("summary", ""),
            })
    else:
        # loop exhausted MAX_ROUNDS without natural stop
        final_round_index = MAX_ROUNDS
        yield {"type": "error", "message": f"reached MAX_ROUNDS={MAX_ROUNDS}",
               "where": "loop_cap"}

    # ------------------------------------------------------------------
    # Reconstruct the final answer text from the last round's deltas
    # The frontend already received them as phase=intermediate; persistence
    # needs the same string. We pull it from the assistant_message content.
    # ------------------------------------------------------------------
    final_answer = ""
    if assistant_message and not assistant_message.get("tool_calls"):
        final_answer = assistant_message.get("content") or ""

    # Compute distill for this turn (best-effort; never blocks persistence).
    try:
        distill = await _distill_turn(question, final_answer)
    except Exception:
        distill = {"summary": "", "key_nodes": []}

    try:
        log_id = _persist_turn(session_id, question, mode, "proceed",
                               final_answer, tool_trace, distill, is_new)
    except Exception as exc:
        yield {"type": "error", "message": f"persist failed: {exc}", "where": "persist"}
        log_id = None

    try:
        recorder.flush()
    except Exception as exc:
        yield {"type": "error", "message": f"trace flush failed: {exc}", "where": "trace"}

    yield {
        "type":              "done",
        "session_id":        session_id,
        "log_id":            log_id,
        "final_round_index": final_round_index,
        "total_rounds":      final_round_index,
    }
