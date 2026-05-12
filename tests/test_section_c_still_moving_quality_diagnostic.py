"""Tests for ``scripts/section_c_still_moving_quality_diagnostic.py``.

The diagnostic is a read-only quality report — for each curated
Still Moving Market candidate it asks whether the row is defensible
against the five known weakness paths:

  * noisy / missing / mis-chosen ticker (``weak_ticker``)
  * sector-ETF-or-equals-benchmark proxy choice (``bad_proxy``)
  * missing ``price_cache`` coverage (``missing_price_cache``)
  * no benchmark-adjusted evidence on file
    (``no_benchmark_adjusted_evidence``)
  * no persistence signal on file (``no_persistence_signal``)
  * duplicate narrative across candidates (``duplicate_narrative``)

Pin the contract:

* Read-only: no DB writes, no provider, no LLM, no FastAPI.  No
  imports of ``movers_ranking``, ``persistence_signal``,
  ``api`` / ``routes.*``, ``yfinance``, ``market_data``, or
  ``fastapi`` (the diagnostic does NOT touch shipped still-moving
  logic).
* Top-level envelope carries exactly the 11 spec keys and nothing
  more.
* Per-candidate row carries exactly the 13 spec keys.  Both
  ``inclusion_reason`` and ``exclusion_reason`` are always present;
  exactly one is non-empty depending on whether the row is
  defensible.
* ``bad_proxy`` is a strict subset of ``weak_ticker``:
  ``primary_equals_benchmark`` and ``sector_etf_as_primary`` rows
  increment BOTH counters.
* Conservative wording — banned tokens (``proof``, ``proves``,
  ``proven``, ``alpha``, ``guaranteed``, ``automatically``,
  ``automatic``, ``definitely``, ``causes``, ``causation``,
  ``correct ticker``) absent from any prose the diagnostic emits.
  The word ``validated`` is reserved for explicit "claim NOT
  allowed" disclaimers, so prose checks also reject it.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import section_c_still_moving_quality_diagnostic as cli  # noqa: E402


_REQUIRED_TOP_KEYS = (
    "ok",
    "candidates_checked",
    "defensible_candidates",
    "weak_ticker_cases",
    "bad_proxy_cases",
    "missing_price_cache_cases",
    "no_persistence_cases",
    "duplicate_narrative_cases",
    "recommended_still_moving_filter_rules",
    "warnings",
    "errors",
)


_REQUIRED_CANDIDATE_KEYS = (
    "event_id",
    "headline",
    "event_date",
    "primary_ticker",
    "benchmark_ticker",
    "mechanism_family",
    "ticker_quality",
    "price_cache_available",
    "benchmark_adjusted_evidence_available",
    "persistence_signal",
    "diagnostic_tags",
    "inclusion_reason",
    "exclusion_reason",
)


_BANNED_WORDS = (
    "proof",
    "proves",
    "proven",
    "alpha",
    "guaranteed",
    "automatically",
    "automatic",
    "validated",
    "definitely",
    "causes",
    "causation",
    "correct ticker",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _candidate(**overrides: Any) -> dict[str, Any]:
    """Build a defensible curated-event dict.  Tests override only
    the fields they care about."""
    base = {
        "event_id":         1,
        "event_date":       "2026-04-08",
        "headline":         "OPEC extends voluntary supply cuts.",
        "primary_ticker":   "XOM",
        "benchmark_ticker": "XLE",
        "mechanism_family": "supply_shock",
    }
    base.update(overrides)
    return base


def _patch_seams(
    *,
    candidates:        list[dict[str, Any]] | None = None,
    candidate_errors:  list[str] | None = None,
    cache:             dict[str, dict[str, Any]] | None = None,
    benchmark_evidence: set[int] | None = None,
    persistence:       dict[int, str] | None = None,
):
    """Patch all four seams in one ``with`` block."""
    cands = list(candidates or [])
    cand_errs = list(candidate_errors or [])
    cache_map = dict(cache or {})
    evidence_set = set(benchmark_evidence or set())
    persistence_map = dict(persistence or {})

    def _cache_seam(*, db_path, tickers):  # noqa: ANN001
        out: dict[str, dict[str, Any]] = {}
        for t in tickers or []:
            if not isinstance(t, str) or not t.strip():
                continue
            key = t.strip().upper()
            if key in cache_map:
                out[key] = dict(cache_map[key])
            else:
                out[key] = {
                    "rows_in_cache": 0,
                    "min_date":      None,
                    "max_date":      None,
                }
        return out

    def _evidence_seam(*, artifact_path):  # noqa: ANN001
        return set(evidence_set)

    def _persistence_seam(*, signals_path):  # noqa: ANN001
        return dict(persistence_map)

    return (
        patch.object(cli, "_load_candidates",
                     return_value=(cands, cand_errs)),
        patch.object(cli, "_load_cache_summaries",
                     side_effect=_cache_seam),
        patch.object(cli, "_load_benchmark_adjusted_evidence",
                     side_effect=_evidence_seam),
        patch.object(cli, "_load_persistence_signals",
                     side_effect=_persistence_seam),
    )


class _PatchStack:
    """Apply a collection of patch objects together."""

    def __init__(self, patches):
        self._patches = list(patches)

    def __enter__(self):
        self._entered = [p.__enter__() for p in self._patches]
        return self._entered

    def __exit__(self, *args):
        for p in reversed(self._patches):
            p.__exit__(*args)


def _good_cache(rows: int = 100) -> dict[str, Any]:
    return {
        "rows_in_cache": rows,
        "min_date":      "2025-01-01",
        "max_date":      "2026-04-30",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath(unittest.TestCase):
    def test_defensible_candidate_has_no_weak_tags(self) -> None:
        cand = _candidate(event_id=1)
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={"XOM": _good_cache(), "XLE": _good_cache()},
            benchmark_evidence={1},
            persistence={1: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        self.assertTrue(report["ok"], report.get("errors"))
        self.assertEqual(report["candidates_checked"], 1)
        self.assertEqual(report["defensible_candidates"], 1)
        self.assertEqual(report["weak_ticker_cases"], 0)
        self.assertEqual(report["bad_proxy_cases"], 0)
        self.assertEqual(report["missing_price_cache_cases"], 0)
        self.assertEqual(report["no_persistence_cases"], 0)
        self.assertEqual(report["duplicate_narrative_cases"], 0)
        row = report["candidates"][0]
        self.assertEqual(row["event_id"], 1)
        self.assertEqual(row["ticker_quality"], "ok")
        self.assertTrue(row["price_cache_available"])
        self.assertTrue(row["benchmark_adjusted_evidence_available"])
        self.assertEqual(row["persistence_signal"], "active")
        self.assertEqual(row["diagnostic_tags"], [])
        self.assertTrue(row["inclusion_reason"])
        self.assertEqual(row["exclusion_reason"], "")


# ---------------------------------------------------------------------------
# Weak ticker / bad proxy
# ---------------------------------------------------------------------------


class TestWeakTickerAndBadProxy(unittest.TestCase):
    def test_missing_primary_ticker_is_weak_ticker_only(self) -> None:
        cand = _candidate(event_id=2, primary_ticker=None)
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={"XLE": _good_cache()},
            benchmark_evidence={2},
            persistence={2: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        row = report["candidates"][0]
        self.assertEqual(row["ticker_quality"], "missing")
        self.assertIn("weak_ticker", row["diagnostic_tags"])
        # missing ticker is NOT a "bad proxy choice" — it is just absent.
        self.assertNotIn("bad_proxy", row["diagnostic_tags"])
        self.assertEqual(report["weak_ticker_cases"], 1)
        self.assertEqual(report["bad_proxy_cases"], 0)
        self.assertEqual(report["defensible_candidates"], 0)
        self.assertTrue(row["exclusion_reason"])
        self.assertEqual(row["inclusion_reason"], "")

    def test_sector_etf_as_primary_increments_both_counters(self) -> None:
        cand = _candidate(event_id=3, primary_ticker="XLE",
                          benchmark_ticker="SPY")
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={"XLE": _good_cache(), "SPY": _good_cache()},
            benchmark_evidence={3},
            persistence={3: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        row = report["candidates"][0]
        self.assertEqual(row["ticker_quality"], "sector_etf_as_primary")
        self.assertIn("weak_ticker", row["diagnostic_tags"])
        self.assertIn("bad_proxy", row["diagnostic_tags"])
        self.assertEqual(report["weak_ticker_cases"], 1)
        self.assertEqual(report["bad_proxy_cases"], 1)

    def test_primary_equals_benchmark_increments_both_counters(
        self,
    ) -> None:
        cand = _candidate(event_id=4, primary_ticker="SPY",
                          benchmark_ticker="SPY")
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={"SPY": _good_cache()},
            benchmark_evidence={4},
            persistence={4: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        row = report["candidates"][0]
        self.assertEqual(row["ticker_quality"], "primary_equals_benchmark")
        self.assertIn("weak_ticker", row["diagnostic_tags"])
        self.assertIn("bad_proxy", row["diagnostic_tags"])
        self.assertEqual(report["weak_ticker_cases"], 1)
        self.assertEqual(report["bad_proxy_cases"], 1)


# ---------------------------------------------------------------------------
# Missing price_cache
# ---------------------------------------------------------------------------


class TestMissingPriceCache(unittest.TestCase):
    def test_no_primary_cache_rows(self) -> None:
        cand = _candidate(event_id=5)
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={
                "XOM": {"rows_in_cache": 0,
                        "min_date": None, "max_date": None},
                "XLE": _good_cache(),
            },
            benchmark_evidence={5},
            persistence={5: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        row = report["candidates"][0]
        self.assertFalse(row["price_cache_available"])
        self.assertIn("missing_price_cache", row["diagnostic_tags"])
        self.assertEqual(report["missing_price_cache_cases"], 1)

    def test_no_benchmark_cache_rows(self) -> None:
        cand = _candidate(event_id=6)
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={
                "XOM": _good_cache(),
                "XLE": {"rows_in_cache": 0,
                        "min_date": None, "max_date": None},
            },
            benchmark_evidence={6},
            persistence={6: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        row = report["candidates"][0]
        self.assertFalse(row["price_cache_available"])
        self.assertEqual(report["missing_price_cache_cases"], 1)


# ---------------------------------------------------------------------------
# Benchmark-adjusted evidence
# ---------------------------------------------------------------------------


class TestBenchmarkAdjustedEvidence(unittest.TestCase):
    def test_missing_evidence_for_event(self) -> None:
        cand = _candidate(event_id=7)
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={"XOM": _good_cache(), "XLE": _good_cache()},
            benchmark_evidence=set(),  # nothing on file
            persistence={7: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        row = report["candidates"][0]
        self.assertFalse(row["benchmark_adjusted_evidence_available"])
        self.assertIn("no_benchmark_adjusted_evidence",
                      row["diagnostic_tags"])
        self.assertEqual(report["defensible_candidates"], 0)


# ---------------------------------------------------------------------------
# No persistence signal
# ---------------------------------------------------------------------------


class TestNoPersistence(unittest.TestCase):
    def test_no_persistence_signal_on_file(self) -> None:
        cand = _candidate(event_id=8)
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={"XOM": _good_cache(), "XLE": _good_cache()},
            benchmark_evidence={8},
            persistence={},  # none recorded
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        row = report["candidates"][0]
        self.assertIsNone(row["persistence_signal"])
        self.assertIn("no_persistence_signal", row["diagnostic_tags"])
        self.assertEqual(report["no_persistence_cases"], 1)


# ---------------------------------------------------------------------------
# Duplicate narrative
# ---------------------------------------------------------------------------


class TestDuplicateNarrative(unittest.TestCase):
    def test_two_candidates_share_headline(self) -> None:
        cands = [
            _candidate(event_id=9,  headline="OPEC extends cuts"),
            _candidate(event_id=10, headline="OPEC extends cuts"),
        ]
        with _PatchStack(_patch_seams(
            candidates=cands,
            cache={"XOM": _good_cache(), "XLE": _good_cache()},
            benchmark_evidence={9, 10},
            persistence={9: "active", 10: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        for row in report["candidates"]:
            self.assertIn("duplicate_narrative", row["diagnostic_tags"])
        self.assertEqual(report["duplicate_narrative_cases"], 2)
        self.assertEqual(report["defensible_candidates"], 0)

    def test_headline_whitespace_and_case_insensitive(self) -> None:
        cands = [
            _candidate(event_id=11, headline="OPEC extends cuts."),
            _candidate(event_id=12, headline="  opec EXTENDS cuts.  "),
        ]
        with _PatchStack(_patch_seams(
            candidates=cands,
            cache={"XOM": _good_cache(), "XLE": _good_cache()},
            benchmark_evidence={11, 12},
            persistence={11: "active", 12: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        self.assertEqual(report["duplicate_narrative_cases"], 2)

    def test_unique_headlines_do_not_trigger_duplicate(self) -> None:
        cands = [
            _candidate(event_id=13, headline="OPEC extends cuts."),
            _candidate(event_id=14, headline="Hormuz reopening threat."),
        ]
        with _PatchStack(_patch_seams(
            candidates=cands,
            cache={"XOM": _good_cache(), "XLE": _good_cache()},
            benchmark_evidence={13, 14},
            persistence={13: "active", 14: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        self.assertEqual(report["duplicate_narrative_cases"], 0)


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_top_level_keys_exactly(self) -> None:
        with _PatchStack(_patch_seams(
            candidates=[],
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        # The diagnostic ALSO emits a 'candidates' list so per-row
        # data is visible to operators; the top-level *spec* keys are
        # the 11 listed.  Pin both.
        for k in _REQUIRED_TOP_KEYS:
            self.assertIn(k, report,
                          f"missing top-level key: {k!r}")

    def test_per_candidate_keys_exactly(self) -> None:
        cand = _candidate(event_id=15)
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={"XOM": _good_cache(), "XLE": _good_cache()},
            benchmark_evidence={15},
            persistence={15: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        row = report["candidates"][0]
        self.assertEqual(set(row.keys()),
                         set(_REQUIRED_CANDIDATE_KEYS),
                         f"unexpected per-candidate keys: "
                         f"{sorted(row.keys())}")

    def test_inclusion_and_exclusion_reasons_both_always_present(
        self,
    ) -> None:
        cand_ok = _candidate(event_id=16)
        cand_bad = _candidate(event_id=17, primary_ticker=None)
        with _PatchStack(_patch_seams(
            candidates=[cand_ok, cand_bad],
            cache={"XOM": _good_cache(), "XLE": _good_cache()},
            benchmark_evidence={16, 17},
            persistence={16: "active", 17: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        for row in report["candidates"]:
            self.assertIn("inclusion_reason", row)
            self.assertIn("exclusion_reason", row)
            # Exactly one of the two strings is non-empty per row.
            self.assertNotEqual(
                bool(row["inclusion_reason"]),
                bool(row["exclusion_reason"]),
                f"row should have exactly one populated reason: {row}",
            )

    def test_empty_candidate_list_yields_clean_envelope(self) -> None:
        with _PatchStack(_patch_seams(candidates=[])):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        self.assertTrue(report["ok"])
        self.assertEqual(report["candidates_checked"], 0)
        self.assertEqual(report["defensible_candidates"], 0)


# ---------------------------------------------------------------------------
# Recommended filter rules
# ---------------------------------------------------------------------------


class TestRecommendedFilterRules(unittest.TestCase):
    def test_rules_are_a_list_of_strings(self) -> None:
        cand = _candidate(event_id=18, primary_ticker=None)
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={},
            benchmark_evidence=set(),
            persistence={},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        rules = report["recommended_still_moving_filter_rules"]
        self.assertIsInstance(rules, list)
        for r in rules:
            self.assertIsInstance(r, str)
            self.assertTrue(r.strip(),
                            f"empty rule string: {r!r}")

    def test_rules_only_surface_when_relevant(self) -> None:
        cand = _candidate(event_id=19)
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={"XOM": _good_cache(), "XLE": _good_cache()},
            benchmark_evidence={19},
            persistence={19: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        # Clean cohort → no rules required.
        self.assertEqual(report["recommended_still_moving_filter_rules"],
                         [])

    def test_rules_mention_weak_ticker_when_weak_ticker_present(
        self,
    ) -> None:
        cand = _candidate(event_id=20, primary_ticker=None)
        with _PatchStack(_patch_seams(
            candidates=[cand],
            cache={"XLE": _good_cache()},
            benchmark_evidence={20},
            persistence={20: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        joined = " ".join(
            report["recommended_still_moving_filter_rules"]
        ).lower()
        self.assertIn("ticker", joined,
                      f"rules: {report['recommended_still_moving_filter_rules']}")


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _all_prose(self, report: dict[str, Any]) -> list[str]:
        out: list[str] = []
        out.extend(report.get("recommended_still_moving_filter_rules") or [])
        out.extend(report.get("warnings") or [])
        out.extend(report.get("errors") or [])
        for row in report.get("candidates") or []:
            for k in ("inclusion_reason", "exclusion_reason"):
                v = row.get(k)
                if isinstance(v, str) and v:
                    out.append(v)
        return out

    def test_no_banned_tokens_anywhere(self) -> None:
        cands = [
            _candidate(event_id=21),
            _candidate(event_id=22, primary_ticker=None),
            _candidate(event_id=23, primary_ticker="XLE",
                       benchmark_ticker="SPY"),
            _candidate(event_id=24, headline="Duplicate"),
            _candidate(event_id=25, headline="Duplicate"),
        ]
        with _PatchStack(_patch_seams(
            candidates=cands,
            cache={"XOM": _good_cache(), "XLE": _good_cache(),
                   "SPY": _good_cache()},
            benchmark_evidence={21, 23, 24, 25},
            persistence={21: "active", 23: "active",
                         24: "active", 25: "active"},
        )):
            report = cli.run_section_c_still_moving_quality_diagnostic()
        for text in self._all_prose(report):
            lowered = text.lower()
            for w in _BANNED_WORDS:
                self.assertNotIn(w, lowered,
                                 f"banned word {w!r} in {text!r}")


# ---------------------------------------------------------------------------
# Read-only invariants
# ---------------------------------------------------------------------------


class TestReadOnly(unittest.TestCase):
    def test_real_load_cache_summaries_issues_only_select(self) -> None:
        path = os.path.join(
            tempfile.gettempdir(),
            f"sec_c_diag_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(path)
        try:
            conn.execute("""
                CREATE TABLE price_cache (
                    ticker TEXT NOT NULL,
                    date   TEXT NOT NULL,
                    close  REAL,
                    volume REAL,
                    auto_adjust INTEGER NOT NULL,
                    fetched_at  TEXT NOT NULL,
                    PRIMARY KEY (ticker, date, auto_adjust)
                )
            """)
            conn.execute(
                "INSERT INTO price_cache VALUES "
                "('XOM', '2026-01-02', 110.0, 1.0, 1, '')"
            )
            conn.execute(
                "INSERT INTO price_cache VALUES "
                "('XLE', '2026-01-02',  90.0, 1.0, 1, '')"
            )
            conn.commit()
        finally:
            conn.close()
        try:
            import hashlib
            def sha256(p):  # noqa: ANN001
                h = hashlib.sha256()
                with open(p, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
                return h.hexdigest()
            before = sha256(path)
            result = cli._load_cache_summaries(
                db_path=path, tickers=["XOM", "XLE"],
            )
            self.assertEqual(sha256(path), before,
                             "_load_cache_summaries mutated the DB")
            self.assertEqual(result["XOM"]["rows_in_cache"], 1)
            self.assertEqual(result["XLE"]["rows_in_cache"], 1)
            self.assertEqual(result["XOM"]["min_date"], "2026-01-02")
        finally:
            os.unlink(path)

    def test_load_cache_summaries_handles_missing_db(self) -> None:
        result = cli._load_cache_summaries(
            db_path=os.path.join(
                tempfile.gettempdir(),
                f"no_such_db_{uuid.uuid4().hex}.db",
            ),
            tickers=["XOM", "XLE"],
        )
        self.assertEqual(result["XOM"]["rows_in_cache"], 0)
        self.assertEqual(result["XLE"]["rows_in_cache"], 0)

    def test_load_benchmark_adjusted_evidence_handles_missing_artifact(
        self,
    ) -> None:
        missing = os.path.join(
            tempfile.gettempdir(),
            f"no_such_artifact_{uuid.uuid4().hex}.json",
        )
        result = cli._load_benchmark_adjusted_evidence(
            artifact_path=missing,
        )
        self.assertEqual(result, set())

    def test_load_benchmark_adjusted_evidence_real_artifact_shape(
        self,
    ) -> None:
        # Build a tiny artifact with two records.  One carries a
        # benchmark, the other does not — only the first event_id
        # should land in the returned set.
        path = os.path.join(
            tempfile.gettempdir(),
            f"sec_c_diag_art_{uuid.uuid4().hex}.json",
        )
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({
                "records": [
                    {"event_id": 100, "benchmark": "SPY",
                     "primary_ticker": "XOM"},
                    {"event_id": 101, "benchmark": None,
                     "primary_ticker": "XOM"},
                ],
            }, fh)
        try:
            result = cli._load_benchmark_adjusted_evidence(
                artifact_path=path,
            )
            self.assertEqual(result, {100})
        finally:
            os.unlink(path)

    def test_load_persistence_signals_handles_missing_file(self) -> None:
        result = cli._load_persistence_signals(
            signals_path=os.path.join(
                tempfile.gettempdir(),
                f"no_such_signals_{uuid.uuid4().hex}.json",
            ),
        )
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    # Diagnostic must NOT touch shipped still-moving logic, paid
    # providers, or the FastAPI surface.
    _BLOCKED = (
        "yfinance",
        "fastapi",
        "api",
        "market_data",
        "movers_ranking",
        "persistence_signal",
    )

    def test_module_import_does_not_pull_blocked_modules(self) -> None:
        # Subprocess-isolated: prior tests in the same discovery run
        # can pollute sys.modules with movers_ranking / routes.* via
        # unrelated test imports.  Fresh subprocess sees only what
        # importing the diagnostic target module pulls in.
        from tests._import_isolation_check import (
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name=(
                "scripts.section_c_still_moving_quality_diagnostic"
            ),
            blocked=self._BLOCKED,
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_emits_valid_json(self) -> None:
        with _PatchStack(_patch_seams(
            candidates=[_candidate(event_id=200)],
            cache={"XOM": _good_cache(), "XLE": _good_cache()},
            benchmark_evidence={200},
            persistence={200: "active"},
        )):
            out = StringIO()
            rc = cli.main(["--json"], out=out)
        self.assertEqual(rc, 0, f"output: {out.getvalue()}")
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_TOP_KEYS:
            self.assertIn(k, parsed)
        self.assertTrue(parsed["ok"])

    def test_cli_default_yaml_path_does_not_crash_when_missing(
        self,
    ) -> None:
        # Even when the curated YAML default is unreachable, the CLI
        # must emit a clean envelope, not a stack trace.
        with patch.object(
            cli, "_load_candidates",
            return_value=([], ["curated YAML file does not exist: x"]),
        ), patch.object(
            cli, "_load_cache_summaries",
            return_value={},
        ), patch.object(
            cli, "_load_benchmark_adjusted_evidence",
            return_value=set(),
        ), patch.object(
            cli, "_load_persistence_signals",
            return_value={},
        ):
            out = StringIO()
            rc = cli.main(["--json"], out=out)
        # Loader errors flow into the envelope's `errors` field; rc=1
        # is acceptable but the JSON must parse cleanly.
        self.assertIn(rc, (0, 1))
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed["candidates_checked"], 0)


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_output_file_written_when_path_passed(self) -> None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"sec_c_diag_out_{uuid.uuid4().hex}.json",
        )
        try:
            with _PatchStack(_patch_seams(
                candidates=[_candidate(event_id=300)],
                cache={"XOM": _good_cache(), "XLE": _good_cache()},
                benchmark_evidence={300},
                persistence={300: "active"},
            )):
                cli.run_section_c_still_moving_quality_diagnostic(
                    output_path=out_path,
                )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
            for k in _REQUIRED_TOP_KEYS:
                self.assertIn(k, parsed)
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)


if __name__ == "__main__":
    unittest.main()
