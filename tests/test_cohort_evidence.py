"""Tests for ``cohort_evidence.py``.

Pin the contract:

* Phase 1 freeze cohort loads as five normalized records.
* Phase 2 pool loads as five normalized records, three of which pass
  BH at q<=0.05 (BA / ALB / NVDA) and two of which fail (AMAT / CF).
* Phase 1 and Phase 2 q-values are returned in separate scopes and
  must not be co-mingled.
* A missing artifact path returns a clear, path-bearing error for
  Phase 1; for Phase 2 a missing path returns ``None`` (Phase 2 may
  not yet exist).
* The loader is read-only: no provider / db / cache / FastAPI
  imports; loading does not mutate source files (byte identity).

The tests use the on-disk tracked artifacts as the source of truth
where they exercise default behaviour, and synthesised in-memory
fixtures (written to a tempdir) for error-path coverage.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cohort_evidence  # noqa: E402


_PHASE1_EXPECTED_TICKERS = {"WHR", "TXT", "FSLR", "RIO", "LITE"}
_PHASE2_EXPECTED_PASS_TICKERS = {"BA", "ALB", "NVDA"}
_PHASE2_EXPECTED_FAIL_TICKERS = {"AMAT", "CF"}

_PHASE2_EXPECTED_Q_BH = {
    "BA":   1.6e-07,
    "ALB":  0.00011,
    "NVDA": 0.0135,
    "AMAT": 0.065875,
    "CF":   0.161,
}

_PHASE1_EXPECTED_Q_BH_SUBSET = {
    "WHR":  0.013514,
    "TXT":  0.001519,
    "RIO":  0.011822,
    "FSLR": 2.326326e-06,
    "LITE": 1.4155e-07,
}


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------


class TestPhase1Loader(unittest.TestCase):
    def test_default_path_loads_five_records(self) -> None:
        records = cohort_evidence.load_phase1()
        self.assertEqual(len(records), 5)

    def test_each_record_has_exactly_the_documented_keys(self) -> None:
        records = cohort_evidence.load_phase1()
        expected = set(cohort_evidence.RECORD_KEYS)
        for r in records:
            self.assertEqual(
                set(r.keys()),
                expected,
                f"record keys mismatch: {set(r.keys()) ^ expected}",
            )

    def test_every_record_is_labelled_phase1(self) -> None:
        records = cohort_evidence.load_phase1()
        for r in records:
            self.assertEqual(r["phase"], cohort_evidence.PHASE1_LABEL)

    def test_tickers_match_freeze_bundle(self) -> None:
        records = cohort_evidence.load_phase1()
        self.assertEqual(
            {r["primary_ticker"] for r in records},
            _PHASE1_EXPECTED_TICKERS,
        )

    def test_q_bh_values_match_freeze_artifact(self) -> None:
        records = cohort_evidence.load_phase1()
        by_ticker = {r["primary_ticker"]: r["q_bh"] for r in records}
        for ticker, expected_q in _PHASE1_EXPECTED_Q_BH_SUBSET.items():
            self.assertIn(ticker, by_ticker)
            self.assertIsNotNone(by_ticker[ticker])
            self.assertAlmostEqual(by_ticker[ticker], expected_q, places=8)

    def test_all_phase1_rows_pass_bh_at_005(self) -> None:
        records = cohort_evidence.load_phase1()
        self.assertTrue(all(r["passes_bh_at_005"] for r in records))

    def test_candidate_id_is_stable_and_nontrivial(self) -> None:
        records = cohort_evidence.load_phase1()
        ids = [r["candidate_id"] for r in records]
        self.assertEqual(len(ids), len(set(ids)), "candidate_id collisions")
        for cid in ids:
            self.assertTrue(cid.startswith("phase1-"), cid)
            self.assertGreater(len(cid), len("phase1-"))


# ---------------------------------------------------------------------------
# Phase 2
# ---------------------------------------------------------------------------


class TestPhase2Loader(unittest.TestCase):
    def test_default_path_loads_five_records(self) -> None:
        records = cohort_evidence.load_phase2()
        self.assertIsNotNone(records)
        assert records is not None  # narrow for type-checker
        self.assertEqual(len(records), 5)

    def test_each_record_has_exactly_the_documented_keys(self) -> None:
        records = cohort_evidence.load_phase2() or []
        expected = set(cohort_evidence.RECORD_KEYS)
        for r in records:
            self.assertEqual(
                set(r.keys()),
                expected,
                f"record keys mismatch: {set(r.keys()) ^ expected}",
            )

    def test_every_record_is_labelled_phase2(self) -> None:
        records = cohort_evidence.load_phase2() or []
        for r in records:
            self.assertEqual(r["phase"], cohort_evidence.PHASE2_LABEL)

    def test_three_pass_two_fail_with_expected_tickers(self) -> None:
        records = cohort_evidence.load_phase2() or []
        passes = {r["primary_ticker"] for r in records if r["passes_bh_at_005"]}
        fails = {
            r["primary_ticker"] for r in records if not r["passes_bh_at_005"]
        }
        self.assertEqual(len(passes), 3)
        self.assertEqual(len(fails), 2)
        self.assertEqual(passes, _PHASE2_EXPECTED_PASS_TICKERS)
        self.assertEqual(fails, _PHASE2_EXPECTED_FAIL_TICKERS)

    def test_q_bh_matches_pool_artifact(self) -> None:
        records = cohort_evidence.load_phase2() or []
        by_ticker = {r["primary_ticker"]: r["q_bh"] for r in records}
        for ticker, expected_q in _PHASE2_EXPECTED_Q_BH.items():
            self.assertIn(ticker, by_ticker)
            self.assertIsNotNone(by_ticker[ticker])
            self.assertAlmostEqual(by_ticker[ticker], expected_q, places=10)

    def test_passes_field_is_strict_bool(self) -> None:
        records = cohort_evidence.load_phase2() or []
        for r in records:
            self.assertIsInstance(r["passes_bh_at_005"], bool)


# ---------------------------------------------------------------------------
# Scope separation
# ---------------------------------------------------------------------------


class TestScopeSeparation(unittest.TestCase):
    def test_phase_labels_are_distinct(self) -> None:
        self.assertNotEqual(
            cohort_evidence.PHASE1_LABEL,
            cohort_evidence.PHASE2_LABEL,
        )

    def test_no_ticker_appears_in_both_phases(self) -> None:
        phase1 = cohort_evidence.load_phase1()
        phase2 = cohort_evidence.load_phase2() or []
        p1 = {r["primary_ticker"] for r in phase1}
        p2 = {r["primary_ticker"] for r in phase2}
        self.assertEqual(
            p1 & p2,
            set(),
            "Phase 1 and Phase 2 tickers must not overlap",
        )

    def test_phase1_q_bh_unchanged_by_phase2_pool_existence(self) -> None:
        """Phase 1 q-values are frozen, not recomputed against Phase 2.

        If the loader were silently merging the two pools (10-row
        denominator instead of two independent 5-row denominators),
        Phase 1's q-values would shift away from the frozen values
        recorded in ``freeze_candidate_evidence.json``. Pin them.
        """
        records = cohort_evidence.load_phase1()
        by_ticker = {r["primary_ticker"]: r["q_bh"] for r in records}
        for ticker, expected_q in _PHASE1_EXPECTED_Q_BH_SUBSET.items():
            self.assertAlmostEqual(
                by_ticker[ticker], expected_q, places=8,
                msg=f"Phase 1 q_bh for {ticker} drifted from the frozen value",
            )

    def test_q_bh_arrays_are_disjoint_by_phase(self) -> None:
        """A q-value loaded under Phase 1 must not appear in Phase 2 and
        vice versa for a row that belongs to the other phase."""
        phase1 = cohort_evidence.load_phase1()
        phase2 = cohort_evidence.load_phase2() or []
        # Compare on (phase, primary_ticker) — every q_bh must be
        # reachable only through its own phase's loader.
        phase1_pairs = {(r["phase"], r["primary_ticker"]): r["q_bh"] for r in phase1}
        phase2_pairs = {(r["phase"], r["primary_ticker"]): r["q_bh"] for r in phase2}
        for (phase, _), _ in phase1_pairs.items():
            self.assertEqual(phase, cohort_evidence.PHASE1_LABEL)
        for (phase, _), _ in phase2_pairs.items():
            self.assertEqual(phase, cohort_evidence.PHASE2_LABEL)
        # Cross-phase keys must not collide; if they did, scope
        # separation would be ambiguous.
        self.assertEqual(
            set(phase1_pairs.keys()) & set(phase2_pairs.keys()),
            set(),
        )


# ---------------------------------------------------------------------------
# Missing files
# ---------------------------------------------------------------------------


class TestMissingFile(unittest.TestCase):
    def test_phase1_missing_path_raises_filenotfound_with_path(self) -> None:
        bogus = "definitely/does/not/exist/phase1.json"
        with self.assertRaises(FileNotFoundError) as cm:
            cohort_evidence.load_phase1(bogus)
        self.assertIn(bogus, str(cm.exception))

    def test_phase2_missing_path_returns_none(self) -> None:
        bogus = "definitely/does/not/exist/phase2.json"
        self.assertIsNone(cohort_evidence.load_phase2(bogus))

    def test_summary_with_missing_phase2_reports_zero_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_phase2 = str(Path(tmp) / "absent_phase2.json")
            tmp_rej = str(Path(tmp) / "absent_rejection.json")
            result = cohort_evidence.summarize(
                phase2_path=tmp_phase2,
                rejection_path=tmp_rej,
            )
            self.assertEqual(result["phase2_count"], 0)
            self.assertEqual(result["phase2_pass_count"], 0)
            self.assertEqual(result["phase2_fail_count"], 0)
            self.assertIsNone(result["deferred_count"])
            self.assertEqual(result["phase1_count"], 5)

    def test_phase1_missing_file_propagates_through_summary(self) -> None:
        bogus = "definitely/does/not/exist/phase1.json"
        with self.assertRaises(FileNotFoundError):
            cohort_evidence.summarize(phase1_path=bogus)

    def test_malformed_artifact_root_raises_valueerror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text("[1, 2, 3]", encoding="utf-8")  # array, not object
            with self.assertRaises(ValueError):
                cohort_evidence.load_phase1(str(p))

    def test_artifact_without_candidates_list_raises_valueerror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "no_candidates.json"
            p.write_text(json.dumps({"other_key": "value"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                cohort_evidence.load_phase1(str(p))
            with self.assertRaises(ValueError):
                cohort_evidence.load_phase2(str(p))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestSummary(unittest.TestCase):
    def test_default_summary_counts(self) -> None:
        result = cohort_evidence.summarize()
        self.assertEqual(result["phase1_count"], 5)
        self.assertEqual(result["phase2_count"], 5)
        self.assertEqual(result["phase2_pass_count"], 3)
        self.assertEqual(result["phase2_fail_count"], 2)
        # The rejection log exists in this snapshot; deferred_count is
        # an int. We don't pin the exact value because the rejection
        # log is allowed to grow over time.
        self.assertIsInstance(result["deferred_count"], int)
        self.assertGreaterEqual(result["deferred_count"], 0)

    def test_summary_keys_are_exactly_documented(self) -> None:
        result = cohort_evidence.summarize()
        self.assertEqual(
            set(result.keys()),
            {
                "phase1_count",
                "phase2_count",
                "phase2_pass_count",
                "phase2_fail_count",
                "deferred_count",
            },
        )

    def test_summary_pass_plus_fail_equals_phase2_count(self) -> None:
        result = cohort_evidence.summarize()
        self.assertEqual(
            result["phase2_pass_count"] + result["phase2_fail_count"],
            result["phase2_count"],
        )

    def test_summary_deferred_count_zero_when_log_lacks_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "rejection.json"
            # Well-formed JSON object but no decision_counts mapping
            p.write_text(json.dumps({"summary": {}}), encoding="utf-8")
            result = cohort_evidence.summarize(rejection_path=str(p))
            self.assertIsNone(result["deferred_count"])

    def test_summary_deferred_count_reads_explicit_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "rejection.json"
            payload = {
                "summary": {
                    "decision_counts": {
                        "deferred_methodology_lesson": 7,
                    }
                }
            }
            p.write_text(json.dumps(payload), encoding="utf-8")
            result = cohort_evidence.summarize(rejection_path=str(p))
            self.assertEqual(result["deferred_count"], 7)

    def test_tracked_evidence_compatibility_wrappers(self) -> None:
        data = cohort_evidence.load_tracked_evidence()
        self.assertEqual(set(data.keys()), {"phase1", "phase2"})
        self.assertEqual(len(data["phase1"]), 5)
        self.assertEqual(len(data["phase2"]), 5)
        self.assertEqual(
            cohort_evidence.summarize_tracked_evidence(data),
            cohort_evidence.summarize(),
        )


# ---------------------------------------------------------------------------
# Read-only by construction
# ---------------------------------------------------------------------------


class TestReadOnlyByConstruction(unittest.TestCase):
    """Behavioural + AST-level checks that the loader is read-only.

    The user contract is "Never read DB/cache. Never call providers.
    Never mutate files." These tests pin all three.
    """

    _ALLOWED_TOP_LEVEL_IMPORTS: frozenset[str] = frozenset({
        "__future__",
        "json",
        "pathlib",
        "typing",
    })

    def _module_source(self) -> str:
        path = Path(cohort_evidence.__file__)
        return path.read_text(encoding="utf-8")

    def test_module_imports_only_stdlib_whitelist(self) -> None:
        tree = ast.parse(self._module_source())
        observed_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    observed_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    observed_modules.add(node.module.split(".")[0])
        unexpected = observed_modules - self._ALLOWED_TOP_LEVEL_IMPORTS
        self.assertEqual(
            unexpected,
            set(),
            f"cohort_evidence must import only stdlib whitelist; "
            f"unexpected: {sorted(unexpected)}",
        )

    def test_module_does_not_import_provider_or_db_or_routes(self) -> None:
        """Defence-in-depth: even if the whitelist were widened later,
        the specific forbidden families must never appear."""
        tree = ast.parse(self._module_source())
        observed: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    observed.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    observed.add(node.module)
        forbidden_prefixes = (
            "yfinance",
            "price_cache",
            "providers",
            "api",
            "routes",
            "fastapi",
            "anthropic",
            "openai",
            "requests",
            "httpx",
            "sqlalchemy",
            "sqlite3",
            "db",
            "market_data",
        )
        for mod in observed:
            head = mod.split(".")[0]
            self.assertNotIn(
                head,
                forbidden_prefixes,
                f"cohort_evidence imports forbidden module: {mod}",
            )

    def test_load_does_not_mutate_artifact_files(self) -> None:
        """Hash invariance: full summarize() preserves byte identity of
        every default artifact path."""
        paths = [
            cohort_evidence.DEFAULT_PHASE1_PATH,
            cohort_evidence.DEFAULT_PHASE2_PATH,
            cohort_evidence.DEFAULT_REJECTION_PATH,
        ]
        before: dict[str, str] = {}
        for p in paths:
            if Path(p).exists():
                before[p] = hashlib.sha256(Path(p).read_bytes()).hexdigest()
        _ = cohort_evidence.summarize()
        after: dict[str, str] = {}
        for p in paths:
            if Path(p).exists():
                after[p] = hashlib.sha256(Path(p).read_bytes()).hexdigest()
        self.assertEqual(
            before,
            after,
            "summarize() must not modify any source artifact",
        )

    def test_repeated_loads_return_equal_records(self) -> None:
        """A second load must produce equal output (no hidden state)."""
        a = cohort_evidence.load_phase1()
        b = cohort_evidence.load_phase1()
        self.assertEqual(a, b)
        a2 = cohort_evidence.load_phase2()
        b2 = cohort_evidence.load_phase2()
        self.assertEqual(a2, b2)


# ---------------------------------------------------------------------------
# Normalized record value typing
# ---------------------------------------------------------------------------


class TestNormalizedRecordTyping(unittest.TestCase):
    """The normalized record shape is the contract callers rely on."""

    def _check_record_types(self, record: dict[str, Any]) -> None:
        self.assertIsInstance(record["phase"], str)
        self.assertIsInstance(record["candidate_id"], str)
        self.assertIsInstance(record["primary_ticker"], str)
        self.assertIsInstance(record["benchmark_ticker"], str)
        self.assertIsInstance(record["event_date"], str)
        self.assertIsInstance(record["mechanism_family"], str)
        # raw_p / q_bh may be None for legitimately-absent values; here
        # the tracked artifacts have them set, so assert float.
        self.assertIsInstance(record["raw_p"], float)
        self.assertIsInstance(record["q_bh"], float)
        self.assertIsInstance(record["passes_bh_at_005"], bool)
        self.assertIsInstance(record["status"], str)
        self.assertIsInstance(record["caveat"], str)

    def test_phase1_record_types(self) -> None:
        for r in cohort_evidence.load_phase1():
            self._check_record_types(r)

    def test_phase2_record_types(self) -> None:
        for r in cohort_evidence.load_phase2() or []:
            self._check_record_types(r)


if __name__ == "__main__":
    unittest.main()
