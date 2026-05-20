import json
import pytest
from unittest.mock import patch, AsyncMock


@pytest.fixture
def entry_factory(db):
    def _make(raw="今天跟小李吵架了"):
        with db.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO entries (raw, type, memory_type) VALUES (?, 'text', 'thought')",
                (raw,),
            )
            return cur.lastrowid
    return _make


@pytest.mark.asyncio
async def test_new_candidate_creates_contact_and_evidence(db, entry_factory):
    from app.lib import contacts_pipeline

    entry_id = entry_factory("今天跟小李吵架了，我答应他下周给反馈")

    fake_llm = AsyncMock(return_value={
        "mentions": [{
            "verdict": "new_candidate",
            "matched_contact_id": None,
            "candidate_contact_ids": [],
            "mention_text": "小李",
            "excerpt": "今天跟小李吵架了",
            "interaction_observed": True,
            "suggested_display_name": "小李",
            "suggested_aliases": [],
            "suggested_kind": "friend",
            "context_summary": "一次争吵的对象",
            "confidence": 0.85,
        }],
    })

    emits = []
    def emit(stage, status, **extra):
        emits.append((stage, status, extra))

    with patch.object(contacts_pipeline, "chat_json", new=fake_llm), \
         patch.object(contacts_pipeline, "is_structured_llm_configured", return_value=True):
        result = await contacts_pipeline.run_contacts_pipeline(
            entry_id, "今天跟小李吵架了，我答应他下周给反馈",
            trace={}, emit=emit,
        )

    assert len(result["candidates_created"]) == 1
    assert len(result["evidence_attached"]) == 1
    assert result["matched_existing"] == []

    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (result["candidates_created"][0],)).fetchone()
        assert row["display_name"] == "小李"
        assert row["status"] == "candidate"
        assert row["relationship_kind"] == "friend"
        assert row["kind_locked"] == 0
        assert row["first_seen_entry_id"] == entry_id
        assert row["last_seen_entry_id"] == entry_id

        ev = conn.execute("SELECT * FROM contact_evidence WHERE entry_id=?", (entry_id,)).fetchone()
        assert ev["contact_id"] == row["id"]
        assert ev["mention_text"] == "小李"
        assert ev["interaction_observed"] == 1

    stages = [(s, st) for s, st, _ in emits]
    assert ("contacts", "start") in stages
    assert ("contacts", "done") in stages


@pytest.mark.asyncio
async def test_match_existing_updates_last_seen_and_merges_aliases(db, entry_factory):
    from app.lib import contacts_pipeline

    with db.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO contacts
                 (display_name, aliases_json, status, relationship_kind, kind_locked)
               VALUES ('Andy', '[]', 'confirmed', 'friend', 1)"""
        )
        cid = cur.lastrowid

    entry_id = entry_factory("Andy 又来跟我吃饭")

    fake_llm = AsyncMock(return_value={
        "mentions": [{
            "verdict": "match_existing",
            "matched_contact_id": cid,
            "candidate_contact_ids": [],
            "mention_text": "Andy",
            "excerpt": "Andy 又来跟我吃饭",
            "interaction_observed": True,
            "suggested_display_name": "Andy",
            "suggested_aliases": ["安迪"],
            "suggested_kind": "colleague",  # 与已锁的 friend 不一致
            "context_summary": "吃饭",
            "confidence": 0.9,
        }],
    })

    def emit(*a, **kw): pass
    with patch.object(contacts_pipeline, "chat_json", new=fake_llm), \
         patch.object(contacts_pipeline, "is_structured_llm_configured", return_value=True):
        result = await contacts_pipeline.run_contacts_pipeline(
            entry_id, "Andy 又来跟我吃饭", trace={}, emit=emit,
        )

    assert result["matched_existing"] == [cid]
    assert result["candidates_created"] == []

    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        assert json.loads(row["aliases_json"]) == ["安迪"]   # 别名 merge
        assert row["last_seen_entry_id"] == entry_id
        assert row["last_interaction_at"] is not None
        assert row["relationship_kind"] == "friend"           # kind_locked=1 → 不被覆盖
        ev = conn.execute(
            "SELECT * FROM contact_evidence WHERE entry_id=? AND contact_id=?", (entry_id, cid),
        ).fetchone()
        assert ev is not None
        assert ev["suggested_kind"] == "colleague"            # evidence 仍记录原推荐


@pytest.mark.asyncio
async def test_match_existing_fills_null_kind_when_unlocked(db, entry_factory):
    from app.lib import contacts_pipeline

    with db.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO contacts (display_name, aliases_json, status, relationship_kind, kind_locked)
               VALUES ('Eva', '[]', 'confirmed', NULL, 0)"""
        )
        cid = cur.lastrowid
    entry_id = entry_factory("Eva 提到了她家人")

    fake_llm = AsyncMock(return_value={
        "mentions": [{
            "verdict": "match_existing", "matched_contact_id": cid,
            "candidate_contact_ids": [], "mention_text": "Eva", "excerpt": "Eva 提到了她家人",
            "interaction_observed": False,
            "suggested_display_name": "Eva", "suggested_aliases": [],
            "suggested_kind": "colleague", "context_summary": "", "confidence": 0.8,
        }],
    })
    def emit(*a, **kw): pass
    with patch.object(contacts_pipeline, "chat_json", new=fake_llm), \
         patch.object(contacts_pipeline, "is_structured_llm_configured", return_value=True):
        await contacts_pipeline.run_contacts_pipeline(entry_id, "Eva 提到了她家人", trace={}, emit=emit)

    with db.get_conn() as conn:
        row = conn.execute("SELECT relationship_kind, kind_locked FROM contacts WHERE id=?", (cid,)).fetchone()
        assert row["relationship_kind"] == "colleague"  # NULL + 未锁 → 填充
        assert row["kind_locked"] == 0                   # 仍未锁（只有用户操作才置锁）


@pytest.mark.asyncio
async def test_ambiguous_writes_evidence_with_null_contact(db, entry_factory):
    from app.lib import contacts_pipeline

    with db.get_conn() as conn:
        c1 = conn.execute("INSERT INTO contacts (display_name, status) VALUES ('张三', 'confirmed')").lastrowid
        c2 = conn.execute("INSERT INTO contacts (display_name, status) VALUES ('张三', 'confirmed')").lastrowid

    entry_id = entry_factory("张三 又联系我了")
    fake_llm = AsyncMock(return_value={
        "mentions": [{
            "verdict": "ambiguous",
            "matched_contact_id": None,
            "candidate_contact_ids": [c1, c2],
            "mention_text": "张三", "excerpt": "张三 又联系我了",
            "interaction_observed": True,
            "suggested_display_name": "张三", "suggested_aliases": [],
            "suggested_kind": None, "context_summary": "", "confidence": 0.5,
        }],
    })
    def emit(*a, **kw): pass
    with patch.object(contacts_pipeline, "chat_json", new=fake_llm), \
         patch.object(contacts_pipeline, "is_structured_llm_configured", return_value=True):
        result = await contacts_pipeline.run_contacts_pipeline(entry_id, "张三 又联系我了", trace={}, emit=emit)

    assert result["candidates_created"] == []
    assert result["matched_existing"] == []
    assert len(result["evidence_attached"]) == 1

    with db.get_conn() as conn:
        ev = conn.execute("SELECT * FROM contact_evidence WHERE entry_id=?", (entry_id,)).fetchone()
        assert ev["contact_id"] is None
        assert json.loads(ev["ambiguous_candidate_ids_json"]) == [c1, c2]
        assert ev["interaction_observed"] == 1


@pytest.mark.asyncio
async def test_new_candidate_demoted_when_name_already_exists(db, entry_factory):
    """LLM 说 new_candidate，但同名已存在 → 应降级为 match_existing。"""
    from app.lib import contacts_pipeline

    with db.get_conn() as conn:
        cid = conn.execute(
            "INSERT INTO contacts (display_name, aliases_json, status) VALUES ('小李', '[\"Lee\"]', 'candidate')"
        ).lastrowid
    entry_id = entry_factory("又见到小李了")

    fake_llm = AsyncMock(return_value={
        "mentions": [{
            "verdict": "new_candidate", "matched_contact_id": None, "candidate_contact_ids": [],
            "mention_text": "小李", "excerpt": "又见到小李了", "interaction_observed": True,
            "suggested_display_name": "小李", "suggested_aliases": [], "suggested_kind": None,
            "context_summary": "", "confidence": 0.7,
        }],
    })
    def emit(*a, **kw): pass
    with patch.object(contacts_pipeline, "chat_json", new=fake_llm), \
         patch.object(contacts_pipeline, "is_structured_llm_configured", return_value=True):
        result = await contacts_pipeline.run_contacts_pipeline(entry_id, "又见到小李了", trace={}, emit=emit)

    assert result["candidates_created"] == []
    assert result["matched_existing"] == [cid]
    with db.get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM contacts").fetchone()["c"]
        assert n == 1   # 没创建第二条


def test_truncate_by_recency_keeps_top_k(db):
    """200 个 contacts → 截到 100 个，按 recency + evidence_count 打分。"""
    from app.lib import contacts_pipeline
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    items = []
    with db.get_conn() as conn:
        for i in range(200):
            iso = (now - timedelta(days=i)).isoformat(sep=" ")
            cur = conn.execute(
                "INSERT INTO contacts (display_name, status, last_interaction_at) VALUES (?, 'confirmed', ?)",
                (f"P{i}", iso),
            )
            items.append({"id": cur.lastrowid, "display_name": f"P{i}",
                          "aliases_json": "[]", "relationship_kind": None, "status": "confirmed",
                          "last_interaction_at": iso, "last_seen_entry_id": None})

    truncated = contacts_pipeline._truncate_by_recency(items, 100)
    assert len(truncated) == 100
    # 最新（P0、P1...）应靠前
    assert truncated[0]["display_name"] == "P0"
