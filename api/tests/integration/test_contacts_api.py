import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(db):
    from app.main import app
    return TestClient(app)


def _seed(db, **kwargs):
    cols = ",".join(kwargs.keys())
    qs = ",".join("?" * len(kwargs))
    with db.get_conn() as conn:
        return conn.execute(f"INSERT INTO contacts ({cols}) VALUES ({qs})",
                            tuple(kwargs.values())).lastrowid


def test_list_default_returns_confirmed_and_candidate(db, client):
    _seed(db, display_name="A", status="confirmed")
    _seed(db, display_name="B", status="candidate")
    _seed(db, display_name="C", status="merged")
    r = client.get("/ui/api/contacts")
    assert r.status_code == 200
    names = {i["display_name"] for i in r.json()["items"]}
    assert names == {"A", "B"}


def test_list_filter_status(db, client):
    _seed(db, display_name="A", status="confirmed")
    _seed(db, display_name="B", status="candidate")
    r = client.get("/ui/api/contacts?status=confirmed")
    assert {i["display_name"] for i in r.json()["items"]} == {"A"}


def test_detail_returns_contact_and_evidence(db, client):
    cid = _seed(db, display_name="A", status="confirmed", relationship_kind="friend")
    with db.get_conn() as conn:
        entry_id = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES ('x', 'text', 'thought')"
        ).lastrowid
        conn.execute(
            "INSERT INTO contact_evidence (contact_id, entry_id, mention_text) VALUES (?, ?, 'A')",
            (cid, entry_id),
        )
    r = client.get(f"/ui/api/contacts/{cid}")
    assert r.status_code == 200
    body = r.json()
    assert body["contact"]["display_name"] == "A"
    assert len(body["evidence"]) == 1


def test_ambiguous_returns_evidence_without_contact(db, client):
    with db.get_conn() as conn:
        entry_id = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES ('x', 'text', 'thought')"
        ).lastrowid
        conn.execute(
            "INSERT INTO contact_evidence (contact_id, entry_id, ambiguous_candidate_ids_json) VALUES (NULL, ?, '[1,2]')",
            (entry_id,),
        )
    r = client.get("/ui/api/contacts/ambiguous")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["ambiguous_candidate_ids"] == [1, 2]


def test_detail_404(db, client):
    r = client.get("/ui/api/contacts/999")
    assert r.status_code == 404


# ---- T11: POST manual create + confirm ----

def test_manual_create_confirmed_with_kind_locks(db, client):
    r = client.post("/ui/api/contacts", json={
        "display_name": "Wei",
        "aliases": ["小卫"],
        "relationship_kind": "friend",
        "context_summary": "from work",
    })
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        assert row["status"] == "confirmed"
        assert row["relationship_kind"] == "friend"
        assert row["kind_locked"] == 1
        assert json.loads(row["aliases_json"]) == ["小卫"]


def test_manual_create_without_kind_no_lock(db, client):
    r = client.post("/ui/api/contacts", json={"display_name": "Z"})
    assert r.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (r.json()["id"],)).fetchone()
        assert row["relationship_kind"] is None
        assert row["kind_locked"] == 0


def test_confirm_promotes_candidate_and_locks_kind_when_provided(db, client):
    cid = _seed(db, display_name="P", status="candidate", relationship_kind=None)
    r = client.post(f"/ui/api/contacts/{cid}/confirm", json={"relationship_kind": "mentor"})
    assert r.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        assert row["status"] == "confirmed"
        assert row["relationship_kind"] == "mentor"
        assert row["kind_locked"] == 1


def test_confirm_without_overrides_keeps_existing(db, client):
    cid = _seed(db, display_name="P", status="candidate", relationship_kind="friend")
    r = client.post(f"/ui/api/contacts/{cid}/confirm", json={})
    assert r.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        assert row["status"] == "confirmed"
        assert row["relationship_kind"] == "friend"
        assert row["kind_locked"] == 0   # 用户未传 kind → 不上锁


def test_confirm_404(db, client):
    r = client.post("/ui/api/contacts/999/confirm", json={})
    assert r.status_code == 404


def test_confirm_already_confirmed_409(db, client):
    cid = _seed(db, display_name="P", status="confirmed")
    r = client.post(f"/ui/api/contacts/{cid}/confirm", json={})
    assert r.status_code == 409


# ---- T12: PATCH editor + kind_locked reset ----

def test_patch_kind_locks(db, client):
    cid = _seed(db, display_name="A", status="confirmed", relationship_kind=None)
    r = client.patch(f"/ui/api/contacts/{cid}", json={"relationship_kind": "colleague"})
    assert r.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        assert row["relationship_kind"] == "colleague"
        assert row["kind_locked"] == 1


def test_patch_reset_kind(db, client):
    cid = _seed(db, display_name="A", status="confirmed", relationship_kind="friend", kind_locked=1)
    r = client.patch(f"/ui/api/contacts/{cid}", json={"relationship_kind": None, "kind_locked": False})
    assert r.status_code == 200
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        assert row["relationship_kind"] is None
        assert row["kind_locked"] == 0


def test_patch_cannot_change_status_directly(db, client):
    cid = _seed(db, display_name="A", status="confirmed")
    r = client.patch(f"/ui/api/contacts/{cid}", json={"status": "merged"})
    assert r.status_code == 422


# ---- T13: Merge endpoint ----

def test_merge_candidate_into_confirmed_moves_evidence(db, client):
    a = _seed(db, display_name="A", status="candidate", relationship_kind=None)
    b = _seed(db, display_name="A2", aliases_json='["A2"]', status="confirmed", relationship_kind="friend")
    with db.get_conn() as conn:
        entry_id = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES ('x', 'text', 'thought')"
        ).lastrowid
        conn.execute("INSERT INTO contact_evidence (contact_id, entry_id) VALUES (?, ?)", (a, entry_id))

    r = client.post(f"/ui/api/contacts/{a}/merge", json={"into_id": b})
    assert r.status_code == 200, r.text
    assert r.json()["evidence_moved"] == 1
    with db.get_conn() as conn:
        ra = conn.execute("SELECT * FROM contacts WHERE id=?", (a,)).fetchone()
        rb = conn.execute("SELECT * FROM contacts WHERE id=?", (b,)).fetchone()
        assert ra["status"] == "merged" and ra["merged_into_id"] == b
        assert "A" in json.loads(rb["aliases_json"])
        ev = conn.execute("SELECT contact_id FROM contact_evidence WHERE entry_id=?", (entry_id,)).fetchone()
        assert ev["contact_id"] == b


def test_merge_self_409(db, client):
    a = _seed(db, display_name="A", status="confirmed")
    r = client.post(f"/ui/api/contacts/{a}/merge", json={"into_id": a})
    assert r.status_code == 409


def test_merge_into_merged_409(db, client):
    a = _seed(db, display_name="A", status="confirmed")
    b = _seed(db, display_name="B", status="merged")
    r = client.post(f"/ui/api/contacts/{a}/merge", json={"into_id": b})
    assert r.status_code == 409


def test_merge_candidate_into_candidate_allowed(db, client):
    a = _seed(db, display_name="A", status="candidate")
    b = _seed(db, display_name="B", status="candidate")
    r = client.post(f"/ui/api/contacts/{a}/merge", json={"into_id": b})
    assert r.status_code == 200


def test_merge_rewrites_ambiguous_candidate_ids(db, client):
    a = _seed(db, display_name="A", status="candidate")
    b = _seed(db, display_name="B", status="confirmed")
    with db.get_conn() as conn:
        entry_id = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES ('x', 'text', 'thought')"
        ).lastrowid
        # ambiguous evidence 列表里含 a
        conn.execute(
            "INSERT INTO contact_evidence (contact_id, entry_id, ambiguous_candidate_ids_json) VALUES (NULL, ?, ?)",
            (entry_id, json.dumps([a, 999])),
        )
    r = client.post(f"/ui/api/contacts/{a}/merge", json={"into_id": b})
    assert r.status_code == 200
    with db.get_conn() as conn:
        ev = conn.execute("SELECT ambiguous_candidate_ids_json FROM contact_evidence WHERE contact_id IS NULL").fetchone()
        ids = json.loads(ev["ambiguous_candidate_ids_json"])
        assert b in ids and a not in ids


# ---- T14: evidence assign/dismiss ----

def test_assign_ambiguous_to_existing(db, client):
    target = _seed(db, display_name="X", status="confirmed")
    with db.get_conn() as conn:
        entry_id = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES ('x', 'text', 'thought')"
        ).lastrowid
        ev_id = conn.execute(
            "INSERT INTO contact_evidence (contact_id, entry_id, ambiguous_candidate_ids_json) VALUES (NULL, ?, '[1,2]')",
            (entry_id,),
        ).lastrowid
    r = client.post(f"/ui/api/contacts/evidence/{ev_id}/assign", json={"contact_id": target})
    assert r.status_code == 200
    with db.get_conn() as conn:
        ev = conn.execute("SELECT * FROM contact_evidence WHERE id=?", (ev_id,)).fetchone()
        assert ev["contact_id"] == target
        assert json.loads(ev["ambiguous_candidate_ids_json"]) == []


def test_assign_create_new(db, client):
    with db.get_conn() as conn:
        entry_id = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES ('x', 'text', 'thought')"
        ).lastrowid
        ev_id = conn.execute(
            "INSERT INTO contact_evidence (contact_id, entry_id) VALUES (NULL, ?)",
            (entry_id,),
        ).lastrowid
    r = client.post(f"/ui/api/contacts/evidence/{ev_id}/assign",
                    json={"create_new": True, "display_name": "NEW", "relationship_kind": "friend"})
    assert r.status_code == 200
    new_cid = r.json()["contact_id"]
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (new_cid,)).fetchone()
        assert row["status"] == "confirmed"
        assert row["relationship_kind"] == "friend"
        assert row["kind_locked"] == 1


def test_dismiss_evidence(db, client):
    with db.get_conn() as conn:
        entry_id = conn.execute(
            "INSERT INTO entries (raw, type, memory_type) VALUES ('x', 'text', 'thought')"
        ).lastrowid
        ev_id = conn.execute(
            "INSERT INTO contact_evidence (contact_id, entry_id) VALUES (NULL, ?)",
            (entry_id,),
        ).lastrowid
    r = client.post(f"/ui/api/contacts/evidence/{ev_id}/dismiss")
    assert r.status_code == 200
    with db.get_conn() as conn:
        gone = conn.execute("SELECT 1 FROM contact_evidence WHERE id=?", (ev_id,)).fetchone()
        assert gone is None
