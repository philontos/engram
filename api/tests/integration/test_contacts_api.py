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
