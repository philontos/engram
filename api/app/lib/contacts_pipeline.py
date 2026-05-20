"""contacts_pipeline — 从 entry 抽取熟人候选，与现有 contacts 消歧。

输入是 raw entry 文本（router 落地后内部改吃 entry_signals[relationship_event]，
对外签名不变）。输出 dict 含本次新建 / 命中 / ambiguous 的 ids，
用于 process_entry 写入 trace["rollback"]。

LLM 调用是单次结构化 JSON：抽取 mentions[] + verdict + 推荐 kind。
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from typing import Any, Callable

from shared.llm import chat_json, is_structured_llm_configured
from app.lib.db import get_conn


_ALLOWED_KINDS = {"friend","colleague","family","romantic","mentor","client","acquaintance"}
_PROMPT_KNOWN_LIMIT = 100  # known contacts 列表注入上限


SYSTEM_PROMPT = """\
You extract personal-contact mentions from a single user diary entry.

Engram tracks the user's social circle — friends, colleagues, family,
mentors, clients, etc. — people the user has ongoing interaction with.

DO NOT extract: famous thinkers, philosophers, public figures, schools-of-
thought representatives, or any name that appears only as a reference /
citation. Those belong to a separate knowledge layer.

You are given the user's known contacts (id | display_name | aliases | kind).
For every personal-contact mention in the entry, decide:
  - "match_existing": this mention refers to a known contact (set matched_contact_id)
  - "new_candidate":  no plausible existing match; propose a new candidate
  - "ambiguous":      multiple plausible existing matches (fill candidate_contact_ids)

Output strict JSON (no commentary, no markdown):
{
  "mentions": [
    {
      "verdict": "match_existing" | "new_candidate" | "ambiguous",
      "matched_contact_id": <int|null>,
      "candidate_contact_ids": [<int>, ...],
      "mention_text": "<as it appeared>",
      "excerpt": "<short surrounding fragment in the user's language>",
      "interaction_observed": <bool>,
      "suggested_display_name": "<proposed canonical name; required for new_candidate>",
      "suggested_aliases": [<str>, ...],
      "suggested_kind": "friend|colleague|family|romantic|mentor|client|acquaintance" | null,
      "context_summary": "<one short sentence about this person from this entry,\
 in the user's language>",
      "confidence": <float 0-1>
    }
  ]
}

If no personal-contact mentions, return {"mentions": []}.
"""


async def run_contacts_pipeline(
    entry_id: int,
    raw: str,
    *,
    trace: dict,
    emit: Callable[..., Any] | None = None,
) -> dict:
    _emit = emit or (lambda *a, **kw: None)
    _emit("contacts", "start")

    result = {
        "candidates_created": [],
        "evidence_attached":  [],
        "matched_existing":   [],
        "rollback_contacts":  [],
        "rollback_evidence":  [],
    }

    if not is_structured_llm_configured():
        _emit("contacts", "skipped", reason="llm_not_configured")
        return result

    known = _load_known_contacts()
    user_prompt = _build_user_prompt(known, raw)

    t0 = time.perf_counter()
    llm_out = await chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        stage="contacts_extract",
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    mentions = llm_out.get("mentions") if isinstance(llm_out, dict) else None
    if not isinstance(mentions, list):
        mentions = []

    _emit("contacts", "llm_done", mentions_count=len(mentions), latency_ms=latency_ms)

    for m in mentions:
        _process_mention(entry_id, m, known, result)

    _emit("contacts", "done",
          candidates_created=len(result["candidates_created"]),
          matched_existing=len(result["matched_existing"]),
          ambiguous=sum(1 for e in result["evidence_attached"]
                        if e in result["_ambiguous_evidence_ids"]) if "_ambiguous_evidence_ids" in result else 0,
          evidence_attached=len(result["evidence_attached"]))
    result.pop("_ambiguous_evidence_ids", None)
    return result


# ----- helpers -----

def _load_known_contacts() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, display_name, aliases_json, relationship_kind, status,
                      last_interaction_at, last_seen_entry_id
               FROM contacts
               WHERE status IN ('candidate','confirmed')"""
        ).fetchall()
    items = [dict(r) for r in rows]
    if len(items) <= _PROMPT_KNOWN_LIMIT:
        return items
    return _truncate_by_recency(items, _PROMPT_KNOWN_LIMIT)


def _truncate_by_recency(items: list[dict], k: int) -> list[dict]:
    """Day-1 经验式打分：recency + evidence_count log。"""
    now = datetime.now(timezone.utc)

    # 一次性查 evidence 计数
    ids = [it["id"] for it in items]
    counts: dict[int, int] = {}
    if ids:
        ph = ",".join("?" * len(ids))
        with get_conn() as conn:
            for row in conn.execute(
                f"SELECT contact_id, COUNT(*) c FROM contact_evidence "
                f"WHERE contact_id IN ({ph}) GROUP BY contact_id",
                ids,
            ).fetchall():
                counts[row["contact_id"]] = row["c"]

    def score(it: dict) -> float:
        last = it.get("last_interaction_at")
        days = 365.0
        if last:
            try:
                last_dt = datetime.fromisoformat(str(last).replace(" ", "T"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                days = max(0.0, (now - last_dt).total_seconds() / 86400.0)
            except Exception:
                pass
        return math.exp(-days / 30.0) + 0.3 * math.log(1 + counts.get(it["id"], 0))

    return sorted(items, key=score, reverse=True)[:k]


def _build_user_prompt(known: list[dict], raw: str) -> str:
    if known:
        lines = ["## Known contacts (id | display_name | aliases | kind)"]
        for c in known:
            try:
                aliases = json.loads(c.get("aliases_json") or "[]")
            except Exception:
                aliases = []
            tag = " [pending]" if c.get("status") == "candidate" else ""
            lines.append(
                f"{c['id']} | {c['display_name']}{tag} | {json.dumps(aliases, ensure_ascii=False)} | {c.get('relationship_kind') or 'unknown'}"
            )
        known_block = "\n".join(lines)
    else:
        known_block = "## Known contacts\n(none yet)"
    return f"{known_block}\n\n## Entry text\n{raw}"


def _process_mention(entry_id: int, m: dict, known: list[dict], result: dict) -> None:
    verdict = m.get("verdict")
    if verdict == "new_candidate":
        _handle_new_candidate(entry_id, m, result)
    elif verdict == "match_existing":
        _handle_match_existing(entry_id, m, result)
    elif verdict == "ambiguous":
        _handle_ambiguous(entry_id, m, result)


def _handle_new_candidate(entry_id: int, m: dict, result: dict) -> None:
    name = (m.get("suggested_display_name") or m.get("mention_text") or "").strip()
    if not name:
        return
    aliases = m.get("suggested_aliases") or []
    kind = m.get("suggested_kind") if m.get("suggested_kind") in _ALLOWED_KINDS else None
    context = (m.get("context_summary") or "").strip()
    interaction = 1 if m.get("interaction_observed") else 0

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO contacts
                 (display_name, aliases_json, status, relationship_kind,
                  first_seen_entry_id, last_seen_entry_id,
                  last_interaction_at, context_summary)
               VALUES (?, ?, 'candidate', ?, ?, ?, CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END, ?)""",
            (name, json.dumps(aliases, ensure_ascii=False), kind,
             entry_id, entry_id, interaction, context),
        )
        contact_id = cur.lastrowid
        ev_cur = conn.execute(
            """INSERT INTO contact_evidence
                 (contact_id, entry_id, mention_text, excerpt, confidence,
                  suggested_kind, interaction_observed)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (contact_id, entry_id,
             m.get("mention_text") or "",
             m.get("excerpt") or "",
             float(m.get("confidence") or 0.0),
             kind, interaction),
        )
        evidence_id = ev_cur.lastrowid

    result["candidates_created"].append(contact_id)
    result["evidence_attached"].append(evidence_id)
    result["rollback_contacts"].append(contact_id)
    result["rollback_evidence"].append(evidence_id)


def _handle_match_existing(entry_id: int, m: dict, result: dict) -> None:
    cid = m.get("matched_contact_id")
    if not isinstance(cid, int):
        return

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, aliases_json, relationship_kind, kind_locked, field_locks_json "
            "FROM contacts WHERE id=? AND status IN ('candidate','confirmed')",
            (cid,),
        ).fetchone()
        if not row:
            return

        # aliases merge（去重保序）
        try:
            current_aliases = json.loads(row["aliases_json"] or "[]")
        except Exception:
            current_aliases = []
        suggested_aliases = m.get("suggested_aliases") or []
        merged_aliases = list(current_aliases)
        seen = {a.lower() for a in current_aliases if isinstance(a, str)}
        for a in suggested_aliases:
            if isinstance(a, str) and a.lower() not in seen:
                merged_aliases.append(a)
                seen.add(a.lower())

        # kind 填充：仅当当前 NULL 且未锁
        kind = m.get("suggested_kind") if m.get("suggested_kind") in _ALLOWED_KINDS else None
        new_kind = row["relationship_kind"]
        if row["relationship_kind"] is None and row["kind_locked"] == 0 and kind is not None:
            new_kind = kind

        interaction = 1 if m.get("interaction_observed") else 0
        # last_interaction_at 仅当有互动语境才更新
        conn.execute(
            """UPDATE contacts SET
                 aliases_json=?,
                 relationship_kind=?,
                 last_seen_entry_id=?,
                 last_interaction_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE last_interaction_at END,
                 updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (json.dumps(merged_aliases, ensure_ascii=False), new_kind,
             entry_id, interaction, cid),
        )

        ev_cur = conn.execute(
            """INSERT INTO contact_evidence
                 (contact_id, entry_id, mention_text, excerpt, confidence,
                  suggested_kind, interaction_observed)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cid, entry_id,
             m.get("mention_text") or "",
             m.get("excerpt") or "",
             float(m.get("confidence") or 0.0),
             kind, interaction),
        )
        evidence_id = ev_cur.lastrowid

    result["matched_existing"].append(cid)
    result["evidence_attached"].append(evidence_id)
    result["rollback_evidence"].append(evidence_id)


def _handle_ambiguous(entry_id: int, m: dict, result: dict) -> None:
    cand_ids = [c for c in (m.get("candidate_contact_ids") or []) if isinstance(c, int)]
    interaction = 1 if m.get("interaction_observed") else 0
    kind = m.get("suggested_kind") if m.get("suggested_kind") in _ALLOWED_KINDS else None
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO contact_evidence
                 (contact_id, entry_id, mention_text, excerpt, confidence,
                  suggested_kind, ambiguous_candidate_ids_json, interaction_observed)
               VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)""",
            (entry_id,
             m.get("mention_text") or "",
             m.get("excerpt") or "",
             float(m.get("confidence") or 0.0),
             kind, json.dumps(cand_ids), interaction),
        )
        evidence_id = cur.lastrowid

    result["evidence_attached"].append(evidence_id)
    result["rollback_evidence"].append(evidence_id)
