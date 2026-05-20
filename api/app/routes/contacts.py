"""REST endpoints for contacts root (Day-1)."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, conlist, confloat

from app.lib.db import get_conn

router = APIRouter(prefix="/ui/api/contacts")


# ---------- serialization helpers ----------

def _row_to_contact(r) -> dict:
    try:
        aliases = json.loads(r["aliases_json"] or "[]")
    except Exception:
        aliases = []
    try:
        locks = json.loads(r["field_locks_json"] or "{}")
    except Exception:
        locks = {}
    return {
        "id": r["id"],
        "display_name": r["display_name"],
        "aliases": aliases,
        "status": r["status"],
        "merged_into_id": r["merged_into_id"],
        "relationship_kind": r["relationship_kind"],
        "kind_locked": bool(r["kind_locked"]),
        "field_locks": locks,
        "active_status": r["active_status"],
        "intimacy_score": r["intimacy_score"],
        "first_seen_entry_id": r["first_seen_entry_id"],
        "last_seen_entry_id": r["last_seen_entry_id"],
        "last_interaction_at": r["last_interaction_at"],
        "context_summary": r["context_summary"],
        "metadata": json.loads(r["metadata_json"] or "{}"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def _row_to_evidence(r) -> dict:
    try:
        cand = json.loads(r["ambiguous_candidate_ids_json"] or "[]")
    except Exception:
        cand = []
    return {
        "id": r["id"],
        "contact_id": r["contact_id"],
        "entry_id": r["entry_id"],
        "mention_text": r["mention_text"],
        "excerpt": r["excerpt"],
        "confidence": r["confidence"],
        "suggested_kind": r["suggested_kind"],
        "ambiguous_candidate_ids": cand,
        "interaction_observed": bool(r["interaction_observed"]),
        "created_at": r["created_at"],
    }


# ---------- GET ----------

@router.get("")
def list_contacts(
    status: str = Query("confirmed,candidate"),
    kind: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    wanted = {s.strip() for s in status.split(",") if s.strip()}
    if "all" in wanted:
        wanted = {"confirmed", "candidate", "merged"}
    allowed = {"confirmed", "candidate", "merged"}
    if not wanted.issubset(allowed):
        raise HTTPException(422, f"invalid status: {wanted - allowed}")

    placeholders = ",".join("?" * len(wanted))
    sql = f"SELECT * FROM contacts WHERE status IN ({placeholders})"
    params: list = list(wanted)
    if kind:
        sql += " AND relationship_kind = ?"
        params.append(kind)
    sql += " ORDER BY last_interaction_at IS NULL, last_interaction_at DESC, created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) c FROM contacts WHERE status IN ({placeholders})"
            + (" AND relationship_kind=?" if kind else ""),
            (*wanted, *([kind] if kind else [])),
        ).fetchone()["c"]
    return {"items": [_row_to_contact(r) for r in rows], "total": total}


@router.get("/ambiguous")
def list_ambiguous():
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ev.*, e.raw AS entry_raw
               FROM contact_evidence ev
               JOIN entries e ON e.id = ev.entry_id
               WHERE ev.contact_id IS NULL
               ORDER BY ev.created_at DESC"""
        ).fetchall()
    items = []
    for r in rows:
        ev = _row_to_evidence(r)
        ev["entry_excerpt"] = (r["entry_raw"] or "")[:160]
        items.append(ev)
    return {"items": items}


@router.get("/{cid}")
def get_contact(cid: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        if not row:
            raise HTTPException(404, "contact not found")
        ev_rows = conn.execute(
            """SELECT ev.*, e.raw AS entry_raw
               FROM contact_evidence ev JOIN entries e ON e.id = ev.entry_id
               WHERE ev.contact_id = ? ORDER BY ev.created_at DESC LIMIT 50""",
            (cid,),
        ).fetchall()
    contact = _row_to_contact(row)
    if row["merged_into_id"]:
        with get_conn() as conn:
            into = conn.execute("SELECT * FROM contacts WHERE id=?", (row["merged_into_id"],)).fetchone()
        contact["merged_into"] = _row_to_contact(into) if into else None
    evidence = []
    for er in ev_rows:
        d = _row_to_evidence(er)
        d["entry_excerpt"] = (er["entry_raw"] or "")[:160]
        evidence.append(d)
    return {"contact": contact, "evidence": evidence}


# ---------- Pydantic models ----------

_KINDS = ("friend","colleague","family","romantic","mentor","client","acquaintance")
_ACTIVE = ("active","dormant","severed")


class ContactCreate(BaseModel):
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    relationship_kind: Optional[str] = None
    context_summary: str = ""
    active_status: Optional[str] = None
    intimacy_score: Optional[float] = None


class ContactConfirm(BaseModel):
    display_name: Optional[str] = None
    aliases: Optional[list[str]] = None
    relationship_kind: Optional[str] = None
    context_summary: Optional[str] = None


def _validate_kind(k):
    if k is not None and k not in _KINDS:
        raise HTTPException(422, f"invalid relationship_kind: {k}")
def _validate_active(a):
    if a is not None and a not in _ACTIVE:
        raise HTTPException(422, f"invalid active_status: {a}")


@router.post("")
def create_contact(body: ContactCreate):
    _validate_kind(body.relationship_kind)
    _validate_active(body.active_status)
    if body.intimacy_score is not None and not 0 <= body.intimacy_score <= 1:
        raise HTTPException(422, "intimacy_score out of range")

    kind_locked = 1 if body.relationship_kind is not None else 0
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO contacts
                 (display_name, aliases_json, status, relationship_kind, kind_locked,
                  active_status, intimacy_score, context_summary)
               VALUES (?, ?, 'confirmed', ?, ?, ?, ?, ?)""",
            (body.display_name, json.dumps(body.aliases, ensure_ascii=False),
             body.relationship_kind, kind_locked,
             body.active_status, body.intimacy_score, body.context_summary),
        )
        cid = cur.lastrowid
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    return _row_to_contact(row)


@router.post("/{cid}/confirm")
def confirm_contact(cid: int, body: ContactConfirm):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        if not row:
            raise HTTPException(404, "contact not found")
        if row["status"] != "candidate":
            raise HTTPException(409, f"cannot confirm: status={row['status']}")

        # 计算字段
        new_name = body.display_name if body.display_name is not None else row["display_name"]
        new_aliases = body.aliases if body.aliases is not None else json.loads(row["aliases_json"] or "[]")
        new_summary = body.context_summary if body.context_summary is not None else row["context_summary"]
        _validate_kind(body.relationship_kind)
        new_kind = row["relationship_kind"]
        new_locked = row["kind_locked"]
        if body.relationship_kind is not None:
            new_kind = body.relationship_kind
            new_locked = 1

        conn.execute(
            """UPDATE contacts SET
                 display_name=?, aliases_json=?, context_summary=?,
                 relationship_kind=?, kind_locked=?,
                 status='confirmed', updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (new_name, json.dumps(new_aliases, ensure_ascii=False), new_summary,
             new_kind, new_locked, cid),
        )
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    return _row_to_contact(row)


# ---------- PATCH ----------

class ContactPatch(BaseModel):
    display_name: Optional[str] = None
    aliases: Optional[list[str]] = None
    relationship_kind: Optional[str] = Field(default=None)
    kind_locked: Optional[bool] = None    # 仅允许显式置 False（reset）
    context_summary: Optional[str] = None
    active_status: Optional[str] = None
    intimacy_score: Optional[float] = None

    model_config = {"extra": "forbid"}   # 阻止 status / merged_into_id 等


@router.patch("/{cid}")
def patch_contact(cid: int, body: ContactPatch):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        if not row:
            raise HTTPException(404, "contact not found")
        if row["status"] == "merged":
            raise HTTPException(409, "cannot patch a merged tombstone")

        _validate_active(body.active_status)
        if body.intimacy_score is not None and not 0 <= body.intimacy_score <= 1:
            raise HTTPException(422, "intimacy_score out of range")

        fields, params = [], []

        if body.display_name is not None:
            fields.append("display_name=?"); params.append(body.display_name)
        if body.aliases is not None:
            fields.append("aliases_json=?"); params.append(json.dumps(body.aliases, ensure_ascii=False))
        if body.context_summary is not None:
            fields.append("context_summary=?"); params.append(body.context_summary)
        if body.active_status is not None:
            fields.append("active_status=?"); params.append(body.active_status)
        if body.intimacy_score is not None:
            fields.append("intimacy_score=?"); params.append(body.intimacy_score)

        # kind & lock 一起处理
        explicit_kind = "relationship_kind" in body.model_fields_set
        explicit_lock = "kind_locked" in body.model_fields_set
        if explicit_kind:
            _validate_kind(body.relationship_kind)
            fields.append("relationship_kind=?"); params.append(body.relationship_kind)
            if explicit_lock:
                fields.append("kind_locked=?"); params.append(1 if body.kind_locked else 0)
            else:
                # 显式赋 kind 默认上锁；显式 None 也算用户操作 → 上锁? No: 显式 None 通常是 reset → 不锁。
                # 规则：传 kind=具体值 → 锁；传 kind=None 不带 kind_locked → 不锁
                if body.relationship_kind is not None:
                    fields.append("kind_locked=?"); params.append(1)
                else:
                    fields.append("kind_locked=?"); params.append(0)
        elif explicit_lock:
            fields.append("kind_locked=?"); params.append(1 if body.kind_locked else 0)

        if not fields:
            return _row_to_contact(row)

        fields.append("updated_at=CURRENT_TIMESTAMP")
        params.append(cid)
        conn.execute(f"UPDATE contacts SET {', '.join(fields)} WHERE id=?", params)
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    return _row_to_contact(row)


# ---------- MERGE ----------

class MergeBody(BaseModel):
    into_id: int


@router.post("/{cid}/merge")
def merge_contact(cid: int, body: MergeBody):
    if cid == body.into_id:
        raise HTTPException(409, "cannot merge contact into itself")
    with get_conn() as conn:
        m = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        i = conn.execute("SELECT * FROM contacts WHERE id=?", (body.into_id,)).fetchone()
        if not m: raise HTTPException(404, "merged contact not found")
        if not i: raise HTTPException(404, "target contact not found")
        if m["status"] == "merged": raise HTTPException(409, "source already merged")
        if i["status"] == "merged": raise HTTPException(409, "target already merged")

        # 合并 aliases
        m_aliases = json.loads(m["aliases_json"] or "[]")
        i_aliases = json.loads(i["aliases_json"] or "[]")
        merged_aliases = list(i_aliases)
        seen = {a.lower() for a in i_aliases if isinstance(a, str)}
        for a in (*m_aliases, m["display_name"]):
            if isinstance(a, str) and a.lower() not in seen:
                merged_aliases.append(a)
                seen.add(a.lower())

        new_summary = i["context_summary"] or m["context_summary"] or ""
        new_kind = i["relationship_kind"] if i["relationship_kind"] is not None else m["relationship_kind"]
        new_active = i["active_status"] if i["active_status"] is not None else m["active_status"]
        new_intimacy = i["intimacy_score"] if i["intimacy_score"] is not None else m["intimacy_score"]
        new_locked = 1 if (i["kind_locked"] or m["kind_locked"]) else 0

        # 取较新的 last_interaction_at / last_seen_entry_id
        def newer(a, b): return a if (a and (not b or a > b)) else b
        new_last_int = newer(i["last_interaction_at"], m["last_interaction_at"])
        new_last_seen = i["last_seen_entry_id"] if (i["last_interaction_at"] or "") >= (m["last_interaction_at"] or "") else m["last_seen_entry_id"]
        if not new_last_seen:
            new_last_seen = i["last_seen_entry_id"] or m["last_seen_entry_id"]

        # 改写 evidence
        moved = conn.execute(
            "UPDATE contact_evidence SET contact_id=? WHERE contact_id=?",
            (body.into_id, cid),
        ).rowcount

        # 改写 ambiguous_candidate_ids_json 中含 cid 的
        amb_rows = conn.execute(
            "SELECT id, ambiguous_candidate_ids_json FROM contact_evidence WHERE contact_id IS NULL"
        ).fetchall()
        for ar in amb_rows:
            try:
                ids = json.loads(ar["ambiguous_candidate_ids_json"] or "[]")
            except Exception:
                ids = []
            if cid in ids:
                new_ids = [body.into_id if x == cid else x for x in ids]
                # 去重保序
                seen2, dedup = set(), []
                for x in new_ids:
                    if x not in seen2:
                        seen2.add(x); dedup.append(x)
                conn.execute(
                    "UPDATE contact_evidence SET ambiguous_candidate_ids_json=? WHERE id=?",
                    (json.dumps(dedup), ar["id"]),
                )

        conn.execute(
            """UPDATE contacts SET
                 aliases_json=?, context_summary=?, relationship_kind=?,
                 kind_locked=?, active_status=?, intimacy_score=?,
                 last_interaction_at=?, last_seen_entry_id=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (json.dumps(merged_aliases, ensure_ascii=False), new_summary, new_kind,
             new_locked, new_active, new_intimacy,
             new_last_int, new_last_seen, body.into_id),
        )
        conn.execute(
            "UPDATE contacts SET status='merged', merged_into_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (body.into_id, cid),
        )

    return {"merged_id": cid, "into_id": body.into_id, "evidence_moved": moved}


# ---------- EVIDENCE ----------

class AssignBody(BaseModel):
    contact_id: Optional[int] = None
    create_new: bool = False
    display_name: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    relationship_kind: Optional[str] = None
    context_summary: str = ""


@router.post("/evidence/{ev_id}/assign")
def assign_evidence(ev_id: int, body: AssignBody):
    with get_conn() as conn:
        ev = conn.execute("SELECT * FROM contact_evidence WHERE id=?", (ev_id,)).fetchone()
        if not ev: raise HTTPException(404, "evidence not found")
        if ev["contact_id"] is not None:
            raise HTTPException(409, "evidence already assigned")

        if body.create_new:
            if not body.display_name:
                raise HTTPException(422, "display_name required when create_new=true")
            _validate_kind(body.relationship_kind)
            kind_locked = 1 if body.relationship_kind is not None else 0
            cur = conn.execute(
                """INSERT INTO contacts
                     (display_name, aliases_json, status, relationship_kind, kind_locked,
                      context_summary, first_seen_entry_id, last_seen_entry_id)
                   VALUES (?, ?, 'confirmed', ?, ?, ?, ?, ?)""",
                (body.display_name, json.dumps(body.aliases, ensure_ascii=False),
                 body.relationship_kind, kind_locked, body.context_summary,
                 ev["entry_id"], ev["entry_id"]),
            )
            cid = cur.lastrowid
        else:
            if not isinstance(body.contact_id, int):
                raise HTTPException(422, "contact_id required when not create_new")
            tgt = conn.execute("SELECT id, status FROM contacts WHERE id=?", (body.contact_id,)).fetchone()
            if not tgt: raise HTTPException(404, "target contact not found")
            if tgt["status"] == "merged":
                raise HTTPException(409, "cannot assign to merged contact")
            cid = tgt["id"]

        conn.execute(
            "UPDATE contact_evidence SET contact_id=?, ambiguous_candidate_ids_json='[]' WHERE id=?",
            (cid, ev_id),
        )
    return {"evidence_id": ev_id, "contact_id": cid}


@router.post("/evidence/{ev_id}/dismiss")
def dismiss_evidence(ev_id: int):
    with get_conn() as conn:
        ev = conn.execute("SELECT contact_id FROM contact_evidence WHERE id=?", (ev_id,)).fetchone()
        if not ev: raise HTTPException(404, "evidence not found")
        if ev["contact_id"] is not None:
            raise HTTPException(409, "evidence is assigned; cannot dismiss")
        conn.execute("DELETE FROM contact_evidence WHERE id=?", (ev_id,))
    return {"ok": True}


# ---------- DELETE ----------

@router.delete("/{cid}")
def delete_contact(cid: int):
    with get_conn() as conn:
        row = conn.execute("SELECT status FROM contacts WHERE id=?", (cid,)).fetchone()
        if not row: raise HTTPException(404, "contact not found")
        if row["status"] != "candidate":
            raise HTTPException(409, "only candidate contacts can be deleted; use merge for confirmed")
        conn.execute("DELETE FROM contact_evidence WHERE contact_id=?", (cid,))
        conn.execute("DELETE FROM contacts WHERE id=?", (cid,))
    return {"deleted_id": cid}
