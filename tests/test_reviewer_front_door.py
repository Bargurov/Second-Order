"""Reviewer front door — README.md and RESEARCH_OVERVIEW.md reconciliation.

Protects the 2026-07-11 canonical-archive reconciliation on the two
reviewer-facing documents:

* one primary numbered finance-reviewer path that starts at
  ``RESEARCH_OVERVIEW.md`` and walks Mission G -> Mission I -> Mission J in
  order;
* the in-app walkthrough explicitly labeled as requiring a populated local
  archive (a clean clone starts empty; the app is not the sole durable
  record);
* the accepted-archive outcome ledgers restated post-recovery under BOTH
  explicit lens names (Any-support OR-rule 59/14/13; directional-majority
  rule 29/44/13 over the same 86 rows — never merged);
* a compact current-results table over already-published conclusions only;
* the maintained chain including ``ordinary-period comparison -> robustness``;
* the dated validation-status calibration described as a pre-recovery
  snapshot while ``KEEP_CURRENT_RULE`` stays the current conclusion.

Pure text checks over tracked docs — no DB, no network, no app.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
OVERVIEW = (ROOT / "RESEARCH_OVERVIEW.md").read_text(encoding="utf-8")

# Markdown prose hard-wraps at ~80 columns, so multi-word phrases can span a
# line break — match phrases on the flattened text (established repo pattern).
README_FLAT = " ".join(README.split())
OVERVIEW_FLAT = " ".join(OVERVIEW.split())


def _section(doc: str, heading: str) -> str:
    """Return the body of a ``## heading`` section (up to the next ``## ``)."""
    pattern = rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)"
    m = re.search(pattern, doc, flags=re.MULTILINE | re.DOTALL)
    assert m, f"section '## {heading}' not found"
    return m.group(1)


# ---------------------------------------------------------------------------
# README — one primary reviewer path, G -> I -> J
# ---------------------------------------------------------------------------


class TestReadmeReviewerPath:
    def test_path_section_exists(self):
        assert "## Reviewer reading path" in README

    def test_step_one_is_research_overview(self):
        path = _section(README, "Reviewer reading path")
        first_step = re.search(r"^1\.\s+(.+)$", path, flags=re.MULTILINE)
        assert first_step, "no numbered step 1 in the reviewer path"
        assert "RESEARCH_OVERVIEW.md" in first_step.group(1)

    def test_path_walks_g_then_i_then_j(self):
        path = _section(README, "Reviewer reading path")
        g, i, j = (
            path.find("Mission G"),
            path.find("Mission I"),
            path.find("Mission J"),
        )
        assert g != -1, "Mission G missing from the reviewer path"
        assert i != -1, "Mission I missing from the reviewer path"
        assert j != -1, "Mission J missing from the reviewer path"
        assert g < i < j, "reviewer path must read Mission G -> I -> J in order"

    def test_path_covers_ledgers_cases_and_methodology(self):
        path = _section(README, "Reviewer reading path").lower()
        assert "outcome ledger" in path
        assert "representative case" in path
        assert "methodology" in path
        assert "read-only" in path

    def test_no_second_competing_numbered_path_to_app_screens(self):
        # The old path started at the in-app Evidence Overview screen; the
        # durable record now comes first.
        path = _section(README, "Reviewer reading path")
        first_step = re.search(r"^1\.\s+(.+)$", path, flags=re.MULTILINE)
        assert "Research nav" not in first_step.group(1)


class TestReadmeInAppWalkthrough:
    def test_walkthrough_is_labeled_and_bounded(self):
        assert "## In-app walkthrough" in README
        walk = " ".join(_section(README, "In-app walkthrough").split())
        lw = walk.lower()
        assert "populated local `events.db`" in walk
        assert "clean clone starts with an empty archive" in lw
        assert "not the sole durable research record" in lw


# ---------------------------------------------------------------------------
# README — post-recovery outcome ledgers, named by lens
# ---------------------------------------------------------------------------


class TestReadmeOutcomeLedgers:
    def test_or_rule_ledger_current_and_named(self):
        assert "Any-support OR-rule" in README
        assert "59 any-supporting" in README
        assert "14 contradicted" in README
        assert "13 unresolved" in README

    def test_stale_pre_recovery_split_gone(self):
        assert "46 any-supporting" not in README
        assert "8 contradicted" not in README
        assert "32 unresolved" not in README

    def test_majority_ledger_current_and_named(self):
        assert "Directional-majority rule" in README
        assert "validation_status_v2" in README
        assert "29 validated" in README
        assert "44 contradicted" in README

    def test_majority_labels_qualified_not_success(self):
        lr = README_FLAT.lower()
        assert "not a success verdict" in lr
        assert "ties count as contradicted" in lr

    def test_divergence_explained(self):
        assert "one supporting name is enough" in README_FLAT.lower()

    def test_lanes_never_pooled(self):
        # 86 accepted + 97 promoted must never appear as one 183 sample.
        assert "183" not in README


# ---------------------------------------------------------------------------
# README — compact current-results table
# ---------------------------------------------------------------------------


class TestReadmeResultsTable:
    def test_results_table_exists_with_all_five_lanes(self):
        assert "## Current results at a glance" in README
        table = _section(README, "Current results at a glance")
        for lane in (
            "Accepted archive",
            "Mission G",
            "Mission I",
            "Mission J",
            "Validation-status calibration",
        ):
            assert lane in table, f"results table missing lane: {lane}"

    def test_rows_carry_denominators(self):
        table = _section(README, "Current results at a glance")
        assert "86" in table
        assert "97" in table  # Mission G promoted (65 FOMC / 32 OPEC)
        assert "65" in table  # FOMC frames
        assert "32" in table  # OPEC register

    def test_rows_carry_durable_artifacts(self):
        table = _section(README, "Current results at a glance")
        assert "RESEARCH_OVERVIEW.md" in table or "stats/" in table
        assert "MISSION_I_CLOSEOUT.md" in table
        assert "VALIDATION_STATUS_CALIBRATION.md" in table

    def test_rows_carry_fragility_and_nonclaims(self):
        table = _section(README, "Current results at a glance").lower()
        # fragility / unavailable-measure column content
        assert "knife-edge" in table
        assert "unadjudicable" in table or "m1" in table
        # non-claim column content
        assert "no causal" in table or "not causal" in table or "no causality" in table

    def test_calibration_row_keeps_current_rule(self):
        table = _section(README, "Current results at a glance")
        assert "KEEP_CURRENT_RULE" in table


# ---------------------------------------------------------------------------
# RESEARCH_OVERVIEW — chain + calibration pointer
# ---------------------------------------------------------------------------


class TestResearchOverview:
    def test_maintained_chain_includes_ordinary_and_robustness(self):
        assert "ordinary-period comparison -> robustness" in OVERVIEW

    def test_missions_read_in_front_door_order(self):
        g = OVERVIEW.find("## 4. Mission G")
        i = OVERVIEW.find("Mission I: Ordinary-Period Baseline")
        j = OVERVIEW.find("Mission J: Hindsight-Controlled FOMC Robustness")
        assert -1 not in (g, i, j)
        assert g < i < j

    def test_calibration_pointer_distinguishes_snapshot_from_current(self):
        lo = OVERVIEW.lower()
        assert "validation_status_calibration.md" in lo
        assert "pre-recovery" in lo
        assert "73 decisive" in lo  # current post-recovery ledger
        assert "KEEP_CURRENT_RULE" in OVERVIEW

    def test_both_outcome_lenses_named(self):
        assert "Any-support OR-rule" in OVERVIEW
        assert "validation_status_v2" in OVERVIEW


# ---------------------------------------------------------------------------
# Frozen research record — untouched by the reconciliation
# ---------------------------------------------------------------------------


class TestFrozenRecordPreserved:
    @pytest.mark.parametrize(
        "fragment",
        [
            "stable descriptive association with unresolved calendar-time confounding",
            "12/12" if "12/12" in OVERVIEW else "all twelve cells are ELEVATED",
            "unadjudicable",
        ],
    )
    def test_overview_keeps_frozen_findings(self, fragment):
        assert fragment in OVERVIEW

    def test_calibration_snapshot_doc_still_pre_recovery(self):
        # The tracked calibration publication remains the dated pre-recovery
        # snapshot: its decisive-label count stays 65 and it must not be
        # rewritten to the post-recovery 73.
        cal = (ROOT / "stats" / "VALIDATION_STATUS_CALIBRATION.md").read_text(
            encoding="utf-8"
        )
        assert "65" in cal
        assert "73 decisive" not in cal
