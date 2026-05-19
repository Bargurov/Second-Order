"""Tests for ``scripts/selection_funnel_summary.py``.

Pins the contract:

* ``load_ledger`` returns ``([], errors)`` on missing / malformed YAML
  and ``(candidates, [])`` on well-formed input.
* ``validate_entries`` surfaces missing required fields, unknown
  enum values, and duplicate candidate_ids.
* ``compute_summary`` produces accurate per-outcome / per-gate /
  per-result counts from a deterministic fixture.
* ``check_against_v2_expectations`` returns ``all_pass=True`` for the
  fixture that mirrors the v2.1 artifact and ``all_pass=False`` when
  any single count is off.
* ``run_all`` integrates the above and exits non-zero on mismatch.

No live ledger / artifact / DB / provider access.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.selection_funnel_summary import (  # noqa: E402
    check_against_v2_expectations,
    compute_summary,
    load_ledger,
    main,
    run_all,
    validate_entries,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(text: str, *, suffix: str = "yaml") -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"selection_funnel_test_{uuid.uuid4().hex}.{suffix}",
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _v2_matching_fixture():
    """Return a 19-entry candidate list whose counts match the v2.1
    disclosure exactly: 5 accepted, 3 corrected_original_failed,
    1 wrong-sign rejected, 2 provider-blocked, 5 planning-rejected,
    3 backup → 8 validation runs (4 PASS, 4 FAIL).
    """
    out: list[dict] = []

    def add(cid, gate, outcome, result):
        out.append({
            "candidate_id":     cid,
            "event_name":       f"event for {cid}",
            "primary_ticker":   "AAA",
            "benchmark_ticker": "BBB",
            "gate_stage":       gate,
            "outcome":          outcome,
            "result_code":      result,
        })

    # 5 accepted (1 carryover + 4 from validation)
    add("carryover-acc",  "accepted_v2",         "accepted", "N/A")
    add("val-pass-1",     "temp_validation",     "accepted", "PASS")
    add("val-pass-2",     "corrected_validation", "accepted", "PASS")
    add("val-pass-3",     "corrected_validation", "accepted", "PASS")
    add("val-pass-4",     "corrected_validation", "accepted", "PASS")

    # 3 corrected_original_failed (date errors)
    add("date-err-1",     "temp_validation",     "corrected_original_failed", "FAIL_DATE_ERROR")
    add("date-err-2",     "temp_validation",     "corrected_original_failed", "FAIL_DATE_ERROR")
    add("date-err-3",     "temp_validation",     "corrected_original_failed", "FAIL_DATE_ERROR")

    # 1 wrong-sign rejected at validation
    add("wrong-sign-val", "temp_validation",     "rejected", "FAIL_WRONG_SIGN")

    # 2 provider-blocked
    add("blocked-1",      "provider_preview",    "blocked",  "N/A")
    add("blocked-2",      "provider_preview",    "blocked",  "N/A")

    # 5 rejected at planning / date_sanity
    add("plan-rej-1",     "planning",            "rejected", "N/A")
    add("plan-rej-2",     "planning",            "rejected", "N/A")
    add("plan-rej-3",     "planning",            "rejected", "N/A")
    add("plan-rej-4",     "date_sanity",         "rejected", "N/A")
    add("plan-rej-5",     "date_sanity",         "rejected", "N/A")

    # 3 backups
    add("backup-1",       "planning",            "backup",   "N/A")
    add("backup-2",       "planning",            "backup",   "N/A")
    add("backup-3",       "planning",            "backup",   "N/A")

    return out  # length 19


# ---------------------------------------------------------------------------
# load_ledger
# ---------------------------------------------------------------------------


class TestLoadLedger(unittest.TestCase):
    def test_missing_file_returns_error(self):
        candidates, errors = load_ledger(
            "/nonexistent/path/that/should/not/exist.yaml",
        )
        self.assertEqual(candidates, [])
        self.assertTrue(any("not found" in e for e in errors))

    def test_well_formed_returns_candidates(self):
        path = _write_yaml(
            "candidates:\n"
            "  - candidate_id: test-1\n"
            "    event_name: testing\n"
            "    primary_ticker: AAA\n"
            "    benchmark_ticker: BBB\n"
            "    gate_stage: planning\n"
            "    outcome: rejected\n"
            "    result_code: N/A\n"
        )
        try:
            candidates, errors = load_ledger(path)
            self.assertEqual(errors, [])
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["candidate_id"], "test-1")
        finally:
            os.remove(path)

    def test_malformed_yaml_surfaces_parse_error(self):
        path = _write_yaml("candidates: [unclosed\n")
        try:
            candidates, errors = load_ledger(path)
            self.assertEqual(candidates, [])
            self.assertTrue(any("failed to parse" in e for e in errors))
        finally:
            os.remove(path)

    def test_missing_candidates_key_returns_error(self):
        path = _write_yaml("not_candidates: []\n")
        try:
            candidates, errors = load_ledger(path)
            self.assertEqual(candidates, [])
            self.assertTrue(any("candidates" in e for e in errors))
        finally:
            os.remove(path)

    def test_empty_file_returns_empty_no_error(self):
        path = _write_yaml("")
        try:
            candidates, errors = load_ledger(path)
            self.assertEqual(candidates, [])
            self.assertEqual(errors, [])
        finally:
            os.remove(path)


# ---------------------------------------------------------------------------
# validate_entries
# ---------------------------------------------------------------------------


class TestValidateEntries(unittest.TestCase):
    def _ok_entry(self):
        return {
            "candidate_id":     "ok-1",
            "event_name":       "ok",
            "primary_ticker":   "AAA",
            "benchmark_ticker": "BBB",
            "gate_stage":       "planning",
            "outcome":          "rejected",
            "result_code":      "N/A",
        }

    def test_valid_entry_passes(self):
        errors = validate_entries([self._ok_entry()])
        self.assertEqual(errors, [])

    def test_missing_required_field_surfaced(self):
        entry = self._ok_entry()
        del entry["gate_stage"]
        errors = validate_entries([entry])
        self.assertTrue(any("gate_stage" in e for e in errors))

    def test_unknown_gate_stage_surfaced(self):
        entry = self._ok_entry()
        entry["gate_stage"] = "made_up_gate"
        errors = validate_entries([entry])
        self.assertTrue(any("made_up_gate" in e for e in errors))

    def test_unknown_outcome_surfaced(self):
        entry = self._ok_entry()
        entry["outcome"] = "WIN_BIG"
        errors = validate_entries([entry])
        self.assertTrue(any("WIN_BIG" in e for e in errors))

    def test_unknown_result_code_surfaced(self):
        entry = self._ok_entry()
        entry["result_code"] = "MAYBE"
        errors = validate_entries([entry])
        self.assertTrue(any("MAYBE" in e for e in errors))

    def test_duplicate_candidate_id_surfaced(self):
        a, b = self._ok_entry(), self._ok_entry()
        errors = validate_entries([a, b])  # both share candidate_id "ok-1"
        self.assertTrue(any("duplicate candidate_id" in e for e in errors))


# ---------------------------------------------------------------------------
# compute_summary
# ---------------------------------------------------------------------------


class TestComputeSummary(unittest.TestCase):
    def test_counts_on_v2_matching_fixture(self):
        s = compute_summary(_v2_matching_fixture())
        self.assertEqual(s["total_candidates"], 19)
        self.assertEqual(s["v2_queue_size"], 5)
        self.assertEqual(s["validation_runs"], 8)
        self.assertEqual(s["validation_pass_count"], 4)
        self.assertEqual(s["validation_fail_count"], 4)
        self.assertEqual(s["date_error_count"], 3)
        self.assertEqual(s["wrong_sign_at_validation_count"], 1)
        self.assertEqual(s["provider_blocked_count"], 2)
        self.assertEqual(s["by_outcome"]["accepted"], 5)
        self.assertEqual(s["by_outcome"]["corrected_original_failed"], 3)
        self.assertEqual(s["by_outcome"]["rejected"], 6)  # 5 plan + 1 val
        self.assertEqual(s["by_outcome"]["blocked"], 2)
        self.assertEqual(s["by_outcome"]["backup"], 3)
        self.assertEqual(s["by_gate_stage"]["temp_validation"], 5)
        self.assertEqual(s["by_gate_stage"]["corrected_validation"], 3)


# ---------------------------------------------------------------------------
# check_against_v2_expectations
# ---------------------------------------------------------------------------


class TestCheckAgainstV2Expectations(unittest.TestCase):
    def test_v2_matching_fixture_all_pass(self):
        s = compute_summary(_v2_matching_fixture())
        audit = check_against_v2_expectations(s)
        self.assertTrue(audit["all_pass"], audit)
        for name, body in audit["checks"].items():
            self.assertTrue(body["ok"], f"{name} failed: {body}")

    def test_wrong_pass_count_flags(self):
        fixture = _v2_matching_fixture()
        # Convert one PASS into FAIL_WRONG_SIGN at temp_validation.
        for c in fixture:
            if c["result_code"] == "PASS":
                c["result_code"] = "FAIL_WRONG_SIGN"
                c["gate_stage"] = "temp_validation"
                c["outcome"] = "rejected"
                break
        s = compute_summary(fixture)
        audit = check_against_v2_expectations(s)
        self.assertFalse(audit["all_pass"])
        self.assertFalse(audit["checks"]["pass_count_match_4"]["ok"])

    def test_extra_candidates_flagged_when_out_of_range(self):
        fixture = _v2_matching_fixture()
        # Push total above the 22 upper bound.
        for i in range(6):
            fixture.append({
                "candidate_id":     f"extra-{i}",
                "event_name":       "extra",
                "primary_ticker":   "ZZZ",
                "benchmark_ticker": "QQQ",
                "gate_stage":       "planning",
                "outcome":          "rejected",
                "result_code":      "N/A",
            })
        s = compute_summary(fixture)
        audit = check_against_v2_expectations(s)
        self.assertFalse(audit["all_pass"])
        self.assertFalse(audit["checks"]["total_candidates_in_range"]["ok"])

    def test_wrong_v2_queue_size_flagged(self):
        fixture = _v2_matching_fixture()
        # Drop one acceptance.
        for c in fixture:
            if c["outcome"] == "accepted":
                c["outcome"] = "rejected"
                break
        s = compute_summary(fixture)
        audit = check_against_v2_expectations(s)
        self.assertFalse(audit["all_pass"])
        self.assertFalse(audit["checks"]["v2_queue_match_5"]["ok"])

    def test_wrong_date_error_count_flagged(self):
        fixture = _v2_matching_fixture()
        # Convert one FAIL_DATE_ERROR into FAIL_WRONG_SIGN at validation.
        for c in fixture:
            if c["result_code"] == "FAIL_DATE_ERROR":
                c["result_code"] = "FAIL_WRONG_SIGN"
                c["outcome"] = "rejected"
                break
        s = compute_summary(fixture)
        audit = check_against_v2_expectations(s)
        self.assertFalse(audit["all_pass"])
        self.assertFalse(audit["checks"]["date_error_count_match_3"]["ok"])
        # And wrong-sign-at-validation count is now 2 instead of 1
        self.assertFalse(
            audit["checks"]["wrong_sign_at_validation_match_1"]["ok"],
        )

    def test_wrong_provider_blocked_flagged(self):
        fixture = _v2_matching_fixture()
        # Convert one blocked into rejected
        for c in fixture:
            if c["outcome"] == "blocked":
                c["outcome"] = "rejected"
                c["gate_stage"] = "planning"
                break
        s = compute_summary(fixture)
        audit = check_against_v2_expectations(s)
        self.assertFalse(audit["all_pass"])
        self.assertFalse(audit["checks"]["provider_blocked_match_2"]["ok"])


# ---------------------------------------------------------------------------
# run_all + main
# ---------------------------------------------------------------------------


class TestRunAllAndMain(unittest.TestCase):
    def _write_fixture_yaml(self, candidates: list[dict]) -> str:
        import yaml as _yaml
        text = _yaml.safe_dump({"candidates": candidates}, sort_keys=False)
        return _write_yaml(text)

    def test_run_all_passes_on_matching_fixture(self):
        path = self._write_fixture_yaml(_v2_matching_fixture())
        try:
            result = run_all(path)
            self.assertTrue(result["ok"], result)
        finally:
            os.remove(path)

    def test_run_all_fails_on_load_error(self):
        result = run_all("/nonexistent/ledger.yaml")
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("load_errors"))

    def test_run_all_fails_on_validation_error(self):
        fixture = _v2_matching_fixture()
        # Inject a row with unknown gate_stage
        fixture[0]["gate_stage"] = "made_up"
        path = self._write_fixture_yaml(fixture)
        try:
            result = run_all(path)
            self.assertFalse(result["ok"])
            self.assertTrue(result.get("validation_errors"))
        finally:
            os.remove(path)

    def test_main_exits_zero_on_match(self):
        path = self._write_fixture_yaml(_v2_matching_fixture())
        try:
            exit_code = main(["--ledger", path, "--json"])
            self.assertEqual(exit_code, 0)
        finally:
            os.remove(path)

    def test_main_exits_nonzero_on_mismatch(self):
        # Empty ledger → total < 18 → out of range
        path = _write_yaml("candidates: []\n")
        try:
            exit_code = main(["--ledger", path, "--json"])
            self.assertNotEqual(exit_code, 0)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
