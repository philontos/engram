"""replay_profile_merge.replay 端到端测试。"""

import json

import pytest

from app.lib.db import get_conn
from app.lib.profile_merge import merge_dimension


def _seed_entry(content_jsons: list[tuple[str, dict]]) -> int:
    """Insert one entry + slice + N slice_features. Returns entry_id."""
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO entries (type, raw) VALUES (?, ?)", ("thought", "x"))
        entry_id = cur.lastrowid
        cur = conn.execute("INSERT INTO slices (entry_id) VALUES (?)", (entry_id,))
        slice_id = cur.lastrowid
        for dim, content in content_jsons:
            conn.execute(
                "INSERT INTO slice_features (slice_id, dimension, content_json) VALUES (?, ?, ?)",
                (slice_id, dim, json.dumps(content)),
            )
    return entry_id


class TestReplay:
    def test_replay_rebuilds_profile_from_slice_features(self, db):
        # seed: 3 entries, OCEAN.E grows from 70 → 75 → 80
        for x in [70, 75, 80]:
            _seed_entry([("ocean", {"E": {"score": x, "confidence": 0.7, "evidence": "x"}})])

        # nuke profile state
        with get_conn() as conn:
            conn.execute("DELETE FROM profile_dimensions")
            conn.execute("DELETE FROM profile_snapshots")

        from scripts.replay_profile_merge import replay
        stats = replay()

        assert stats.entries_processed == 3
        assert stats.slice_features_replayed == 3
        assert stats.snapshots_written == 3

        # profile should be rebuilt
        with get_conn() as conn:
            row = conn.execute("SELECT content_json FROM profile_dimensions").fetchone()
        content = json.loads(row["content_json"])
        # Score should be between 50 (prior) and 80 (last obs); we expect ~70+
        assert "E" in content
        assert 65 <= content["E"]["score"] <= 80

    def test_replay_dimension_filter(self, db):
        # seed both ocean and mbti
        _seed_entry([
            ("ocean", {"E": {"score": 75, "confidence": 0.7, "evidence": "x"}}),
            ("mbti", {"E_I": {"score": 80, "confidence": 0.7, "evidence": "x"}}),
        ])

        # Pre-populate mbti via merge so we can verify it's NOT touched
        merge_dimension("mbti", {"E_I": {"score": 30, "confidence": 0.7, "evidence": "before"}})

        with get_conn() as conn:
            conn.execute("DELETE FROM profile_dimensions WHERE dimension='ocean'")

        from scripts.replay_profile_merge import replay
        stats = replay(dimension="ocean")

        # ocean should be rebuilt
        with get_conn() as conn:
            ocean_row = conn.execute(
                "SELECT content_json FROM profile_dimensions WHERE dimension='ocean'"
            ).fetchone()
            mbti_row = conn.execute(
                "SELECT content_json FROM profile_dimensions WHERE dimension='mbti'"
            ).fetchone()

        assert ocean_row is not None
        assert stats.dimensions_touched == 1

        # mbti should be untouched (still has the score from the manual merge above)
        mbti_content = json.loads(mbti_row["content_json"])
        assert mbti_content["E_I"]["evidence"] == "before"  # not "x" from the slice_feature

    def test_replay_limit(self, db):
        for x in [60, 65, 70, 75, 80]:
            _seed_entry([("ocean", {"E": {"score": x, "confidence": 0.7, "evidence": "x"}})])

        with get_conn() as conn:
            conn.execute("DELETE FROM profile_dimensions")
            conn.execute("DELETE FROM profile_snapshots")

        from scripts.replay_profile_merge import replay
        stats = replay(limit=2)

        assert stats.entries_processed == 2
        assert stats.snapshots_written == 2

    def test_dry_run_does_not_modify_db(self, db):
        # Seed a baseline state, then run dry_run replay, then verify state unchanged
        merge_dimension("ocean", {"E": {"score": 30, "confidence": 0.9, "evidence": "baseline"}})
        with get_conn() as conn:
            before = conn.execute("SELECT content_json FROM profile_dimensions WHERE dimension='ocean'").fetchone()
        before_json = before["content_json"]

        # Seed slice_features that, if applied, would shift the score significantly
        for x in [80, 80, 80]:
            _seed_entry([("ocean", {"E": {"score": x, "confidence": 0.9, "evidence": "would shift"}})])

        from scripts.replay_profile_merge import replay
        stats = replay(dry_run=True)

        # Stats reflect the would-be replay
        assert stats.entries_processed >= 3

        # But DB is unchanged
        with get_conn() as conn:
            after = conn.execute("SELECT content_json FROM profile_dimensions WHERE dimension='ocean'").fetchone()
        assert after["content_json"] == before_json, "dry_run should not modify DB"
