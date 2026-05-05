"""Tests for the three prompt audit fixes (PR #7).

C3: edge_extract.spt internal↔internal evidence rule
C4: activation.spt effort_weight scale alignment
C5: _q2_system defensive citation guidance
"""

from pathlib import Path

import pytest

from app.lib.agent_tools import _q2_system


_REPO_ROOT     = Path(__file__).resolve().parents[2]
_EDGE_EXTRACT  = _REPO_ROOT / "app/config/backbones/_shared/edge_extract.spt"
_ACTIVATION    = _REPO_ROOT / "app/config/backbones/_shared/activation.spt"


# ── C3: edge_extract evidence rule ──────────────────────────────────────────

class TestEdgeExtractEvidenceRule:
    @pytest.fixture(scope="class")
    def prompt(self) -> str:
        return _EDGE_EXTRACT.read_text(encoding="utf-8")

    def test_internal_internal_skip_when_no_raw(self, prompt):
        # New rule must explicitly say: skip the edge if no raw text for internal pairs
        assert "Skip the edge" in prompt or "skip the edge" in prompt

    def test_no_fabricate_quotes_warning(self, prompt):
        assert "fabricate" in prompt.lower()

    def test_evidence_prefix_convention(self, prompt):
        # Prompt should require either "raw:" or "dom:" prefix in evidence
        assert '"raw:' in prompt
        assert '"dom:' in prompt

    def test_old_ambiguous_rule_removed(self, prompt):
        # The old "even if raw_entry has no explicit opposition, build the opposes edge"
        # was the contradiction source — must not still exist
        assert "even if raw_entry has no explicit" not in prompt.lower().replace("“", '"').replace("”", '"')


# ── C4: activation.spt effort_weight scale ─────────────────────────────────

class TestActivationEffortWeightScale:
    @pytest.fixture(scope="class")
    def prompt(self) -> str:
        return _ACTIVATION.read_text(encoding="utf-8")

    def test_buckets_match_node_extract(self, prompt):
        # effort_weight buckets must match _template/node_extract.spt downstream contract:
        # 0.8-1.0 → 5-8, 0.5-0.7 → 3-5, 0.2-0.4 → 1-3
        for anchor in ("0.8", "0.5", "0.2", "5–8", "3–5", "1–3"):
            assert anchor in prompt, f"missing scale anchor: {anchor!r}"

    def test_calibration_warning_present(self, prompt):
        # Must warn against assigning 0.8 to many domains (the "everything is hot" pathology)
        assert "0.8" in prompt and ("recheck" in prompt.lower() or "rare" in prompt.lower())


# ── C5: _q2_system defensive citation ──────────────────────────────────────

class TestQ2SystemDefensiveCitation:
    def test_empty_profile_skips_citation(self):
        out = _q2_system(profile_summary="(no historical profile yet)")
        # Must not ask LLM to cite values when nothing's there
        assert "early-stage" in out.lower() or "still empty" in out.lower()
        assert "anchor every claim in the raw records" in out.lower()

    def test_empty_string_profile_treated_as_empty(self):
        out = _q2_system(profile_summary="")
        assert "still empty" in out.lower() or "early-stage" in out.lower()

    def test_real_profile_keeps_citation_instruction(self):
        # When profile_summary has content, citation instruction should be present
        out = _q2_system(profile_summary="OCEAN: O=78(conf=0.85), C=86(conf=0.8)")
        # Either "Cite specific sub-key scores" (if scored dims active) or
        # "Cite specific sub-key values" (if non-scored only)
        assert "Cite specific" in out or "cite specific" in out
