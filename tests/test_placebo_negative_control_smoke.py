"""Tests for ``scripts/placebo_negative_control_smoke.py``.

Pin the contract:

* The smoke is read-only.  It never imports a paid provider, an LLM,
  the FastAPI app, or ``yfinance``.  The default run writes nothing
  to disk; ``--output`` is the only flag that produces a file.
* The output JSON envelope carries the eight pinned top-level keys
  ``ok``, ``cohort_event_count``, ``placebo_dates_tested``,
  ``event_signal_summary``, ``placebo_signal_summary``,
  ``comparison_notes``, ``warnings``, ``errors``.
* The summaries keep ``raw_p_candidate_count`` and
  ``fdr_significant_count`` as separate fields — never folded.
* The real-cohort summary is read from the artifact verbatim, not
  recomputed.  Mutating the placebo-side input does not change the
  real-side count.
* Missing data surfaces in ``warnings`` and never crashes the run.
* The estimation-window-contamination warning is attached whenever
  any default offset is supplied — operators cannot miss it.

The tests inject a synthetic ``price_reader`` so the compute path
runs without any live price-cache dependency.  Synthetic data uses
a fixed deterministic random walk; nothing in the test path imports
``yfinance``, ``market_data``, ``anthropic``, ``openai``, or
``routes``.
"""
from __future__ import annotations

import json
import math
import os
import random
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import placebo_negative_control_smoke as smoke  # noqa: E402


_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "ok",
    "cohort_event_count",
    "placebo_dates_tested",
    "requested_placebo_draws",
    "computable_placebo_draws",
    "skipped_placebo_draws",
    "skip_reason_counts",
    "placebo_offsets_used",
    "coverage_diagnostics",
    "methodology_adjustments",
    "recommended_next_action",
    "event_signal_summary",
    "placebo_signal_summary",
    "comparison_notes",
    "warnings",
    "errors",
)

_SUMMARY_REQUIRED_KEYS: tuple[str, ...] = (
    "records_count",
    "raw_p_candidate_count",
    "fdr_significant_count",
    "by_horizon",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_evidence(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "artifact_type":   "freeze_candidate_evidence",
        "generated_at":    "2026-05-17T00:00:00",
        "ok":              True,
        "records":         records,
        "cohort_summary":  {},
        "verdict_counts":  {},
        "by_horizon":      {},
        "warnings":        [],
        "errors":          [],
    }


def _write_evidence(tmp: Path, records: list[dict[str, Any]]) -> Path:
    path = tmp / "freeze.json"
    path.write_text(
        json.dumps(_make_evidence(records)), encoding="utf-8",
    )
    return path


def _make_events_db(tmp: Path, mapping: dict[int, str]) -> Path:
    """Tiny ``events.db`` with just the fields the smoke reads."""
    path = tmp / "events.db"
    con = sqlite3.connect(path.as_posix())
    con.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, event_date TEXT)",
    )
    con.executemany(
        "INSERT INTO events(id, event_date) VALUES (?, ?)",
        list(mapping.items()),
    )
    con.commit()
    con.close()
    return path


def _build_price_reader(
    *,
    base_date:        date,
    span_days:        int = 200,
    asset_tickers:    tuple[str, ...] = ("XOM", "XLE", "VLO"),
    benchmark_ticker: str   = "SPY",
    asset_seed:       int   = 11,
    bench_seed:       int   = 17,
    asset_shock_day:  int | None = None,
    asset_shock_size: float = 0.0,
):
    """Return a (ticker, start, end) -> (dates, closes) callable.

    Generates a deterministic random walk for the benchmark and each
    asset across ``span_days`` calendar days centred on ``base_date``.
    Weekends are dropped so the result reads as a synthetic trading
    calendar.  Two independent RNGs give the asset and benchmark
    similar-but-not-identical paths; a controlled shock can be
    injected on a chosen day for the asset(s).
    """
    start_day = base_date - timedelta(days=span_days // 2)

    def _series(seed: int, shock_day: int | None) -> dict[str, float]:
        rng = random.Random(seed)
        out: dict[str, float] = {}
        price = 100.0
        for i in range(span_days):
            d = start_day + timedelta(days=i)
            if d.weekday() >= 5:           # skip Sat / Sun
                continue
            r = rng.gauss(0.0001, 0.01)
            if shock_day is not None and i == shock_day:
                r += asset_shock_size
            price *= (1.0 + r)
            out[d.isoformat()] = round(price, 6)
        return out

    bench_series  = _series(bench_seed, shock_day=None)
    asset_series  = {
        t: _series(asset_seed + i, shock_day=asset_shock_day)
        for i, t in enumerate(asset_tickers)
    }

    def _read(ticker: str, start: str, end: str):
        if ticker == benchmark_ticker:
            src = bench_series
        else:
            src = asset_series.get(ticker, {})
        start_d = date.fromisoformat(start[:10])
        end_d   = date.fromisoformat(end[:10])
        dates = [
            d for d in src
            if start_d <= date.fromisoformat(d) <= end_d
        ]
        dates.sort()
        closes = [src[d] for d in dates]
        return dates, closes
    return _read


def _seed_records(
    *,
    event_ids: list[int],
    horizons:  tuple[int, ...] = (1, 5, 20),
    primary:   str = "XOM",
    benchmark: str = "SPY",
    p_value_overrides: dict[tuple[int, int], float] | None = None,
) -> list[dict[str, Any]]:
    overrides = p_value_overrides or {}
    out: list[dict[str, Any]] = []
    for eid in event_ids:
        for h in horizons:
            p   = overrides.get((eid, h), 0.55)
            fdr = 0.99
            rec = {
                "event_id":         eid,
                "horizon":          h,
                "primary_ticker":   primary,
                "benchmark":        benchmark,
                "headline":         f"event {eid}",
                "mechanism_family": "supply_shock",
                "p_value":          p,
                "fdr_q":            fdr,
                "raw_p_candidate":  (p <= 0.05) and not (fdr <= 0.05),
                "fdr_significant":  fdr <= 0.05,
                "verdict":          "inconclusive_fdr",
                "source":           "curated_stage_validation",
            }
            out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class TestEnvelopeShape(unittest.TestCase):
    def test_top_level_keys_present_on_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            recs = _seed_records(event_ids=[1, 2])
            ev_path = _write_evidence(tmp, recs)
            db_path = _make_events_db(
                tmp, {1: base.isoformat(), 2: base.isoformat()},
            )
            reader = _build_price_reader(base_date=base)
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path,
                db_path=db_path,
                offsets=(-10, -5, 5, 10),
                horizons=(1, 5, 20),
                alpha=0.05,
                price_reader=reader,
            )
        for key in _TOP_LEVEL_KEYS:
            self.assertIn(key, payload, f"missing top-level key: {key}")

    def test_summaries_keep_raw_p_and_fdr_separate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            recs = _seed_records(event_ids=[1])
            ev_path = _write_evidence(tmp, recs)
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path,
                db_path=db_path,
                offsets=(-10, 10),
                horizons=(1, 5, 20),
                price_reader=_build_price_reader(base_date=base),
            )
        for side in ("event_signal_summary", "placebo_signal_summary"):
            with self.subTest(side=side):
                summary = payload[side]
                for key in _SUMMARY_REQUIRED_KEYS:
                    self.assertIn(key, summary, f"{side} missing {key}")
                self.assertIsInstance(summary["raw_p_candidate_count"], int)
                self.assertIsInstance(summary["fdr_significant_count"], int)


# ---------------------------------------------------------------------------
# Real-side counts come from the artifact, not from recomputation
# ---------------------------------------------------------------------------


class TestRealSideTrustsArtifact(unittest.TestCase):
    def test_real_counts_match_artifact_booleans(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            # Two raw-p records and one fdr-significant record, all
            # set by the booleans the artifact recorded.
            recs = _seed_records(event_ids=[1, 2])
            recs[0]["p_value"] = 0.01
            recs[0]["raw_p_candidate"] = True
            recs[1]["p_value"] = 0.02
            recs[1]["raw_p_candidate"] = True
            recs[2]["fdr_q"] = 0.01
            recs[2]["fdr_significant"] = True
            ev_path = _write_evidence(tmp, recs)
            db_path = _make_events_db(
                tmp, {1: base.isoformat(), 2: base.isoformat()},
            )
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path,
                db_path=db_path,
                offsets=(-10, 10),
                horizons=(1, 5, 20),
                price_reader=_build_price_reader(base_date=base),
            )
        ev_summary = payload["event_signal_summary"]
        self.assertEqual(ev_summary["raw_p_candidate_count"], 2)
        self.assertEqual(ev_summary["fdr_significant_count"], 1)

    def test_mutating_placebo_p_does_not_change_real_count(self) -> None:
        # Even if the synthetic data generates many "significant"
        # placebo SARs, the real-side counts remain pinned to the
        # artifact's own booleans.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            recs = _seed_records(event_ids=[1])
            ev_path = _write_evidence(tmp, recs)
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            quiet  = _build_price_reader(base_date=base, asset_seed=1)
            spiked = _build_price_reader(
                base_date=base, asset_seed=2,
                asset_shock_day=80, asset_shock_size=0.30,
            )
            p1 = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-10, 10), horizons=(1,),
                price_reader=quiet,
            )
            p2 = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-10, 10), horizons=(1,),
                price_reader=spiked,
            )
        self.assertEqual(
            p1["event_signal_summary"],
            p2["event_signal_summary"],
            "real-side summary must not change with placebo data",
        )


# ---------------------------------------------------------------------------
# Missing-data surfaces as warnings, not crashes
# ---------------------------------------------------------------------------


class TestMissingDataIsSurfaced(unittest.TestCase):
    def test_missing_evidence_file_yields_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            db_path = _make_events_db(tmp, {})
            payload = smoke.run_placebo_smoke(
                evidence_path=tmp / "does_not_exist.json",
                db_path=db_path,
                offsets=(-5, 5),
                horizons=(1,),
            )
        self.assertFalse(payload["ok"])
        self.assertTrue(any("not found" in e for e in payload["errors"]))
        # Envelope shape is still intact:
        for key in _TOP_LEVEL_KEYS:
            self.assertIn(key, payload)

    def test_missing_db_file_yields_warning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            recs = _seed_records(event_ids=[1])
            ev_path = _write_evidence(tmp, recs)
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path,
                db_path=tmp / "no_db.db",
                offsets=(-5, 5),
                horizons=(1,),
                price_reader=_build_price_reader(base_date=date(2026, 4, 6)),
            )
        self.assertTrue(
            any("events DB not found" in w for w in payload["warnings"]),
        )
        self.assertEqual(payload["placebo_dates_tested"], 0)

    def test_event_with_no_primary_ticker_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            recs = _seed_records(event_ids=[1])
            recs[0]["primary_ticker"] = None
            recs[1]["primary_ticker"] = None
            recs[2]["primary_ticker"] = None
            ev_path = _write_evidence(tmp, recs)
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-5, 5), horizons=(1,),
                price_reader=_build_price_reader(base_date=base),
            )
        self.assertTrue(
            any("primary_ticker" in w for w in payload["warnings"]),
        )
        self.assertEqual(payload["cohort_event_count"], 0)


# ---------------------------------------------------------------------------
# Estimation-window contamination warning attached automatically
# ---------------------------------------------------------------------------


class TestContaminationWarning(unittest.TestCase):
    def test_default_offsets_attach_contamination_warning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(tmp, _seed_records(event_ids=[1]))
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-10, -5, 5, 10), horizons=(1, 5, 20),
                price_reader=_build_price_reader(base_date=base),
            )
        joined = " ".join(payload["warnings"]).lower()
        self.assertIn("not a clean null", joined)


# ---------------------------------------------------------------------------
# Placebo computation actually fires when coverage is present
# ---------------------------------------------------------------------------


class TestPlaceboCompute(unittest.TestCase):
    def test_placebo_records_produced_with_full_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(
                tmp, _seed_records(event_ids=[1, 2, 3]),
            )
            db_path = _make_events_db(tmp, {
                1: base.isoformat(),
                2: base.isoformat(),
                3: base.isoformat(),
            })
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-10, 10), horizons=(1, 5, 20),
                price_reader=_build_price_reader(
                    base_date=base, span_days=300,
                ),
            )
        # At least one placebo (event, offset) pair should have landed
        # on a trading day with sufficient pre-history.
        self.assertGreater(payload["placebo_dates_tested"], 0)
        pl = payload["placebo_signal_summary"]
        self.assertGreater(pl["records_count"], 0)
        # raw-p / fdr counts are non-negative ints bounded by record count.
        self.assertGreaterEqual(pl["raw_p_candidate_count"], 0)
        self.assertGreaterEqual(pl["fdr_significant_count"], 0)
        self.assertLessEqual(
            pl["raw_p_candidate_count"] + pl["fdr_significant_count"],
            pl["records_count"],
        )

    def test_deterministic_with_fixed_reader(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(tmp, _seed_records(event_ids=[1, 2]))
            db_path = _make_events_db(tmp, {
                1: base.isoformat(), 2: base.isoformat(),
            })
            opts = dict(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-10, 10), horizons=(1, 5, 20),
            )
            a = smoke.run_placebo_smoke(
                **opts,
                price_reader=_build_price_reader(
                    base_date=base, span_days=300,
                ),
            )
            b = smoke.run_placebo_smoke(
                **opts,
                price_reader=_build_price_reader(
                    base_date=base, span_days=300,
                ),
            )
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# Default run writes nothing; --output writes a file
# ---------------------------------------------------------------------------


class TestNoDefaultWrites(unittest.TestCase):
    def test_main_without_output_creates_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(tmp, _seed_records(event_ids=[1]))
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            before = set(tmp.iterdir())
            buf = StringIO()
            rc = smoke.main(
                argv=[
                    "--json",
                    "--evidence-path", str(ev_path),
                    "--db-path",       str(db_path),
                    "--offsets",       "-5", "5",
                    "--horizons",      "1",
                ],
                out=buf,
            )
            after = set(tmp.iterdir())
        self.assertEqual(before, after, "default run wrote to disk")
        json.loads(buf.getvalue())  # exits 0 or 1 — output is JSON
        self.assertIn(rc, (0, 1))

    def test_main_with_output_writes_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(tmp, _seed_records(event_ids=[1]))
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            out_path = tmp / "report.json"
            buf = StringIO()
            smoke.main(
                argv=[
                    "--json",
                    "--evidence-path", str(ev_path),
                    "--db-path",       str(db_path),
                    "--offsets",       "-5", "5",
                    "--horizons",      "1",
                    "--output",        str(out_path),
                ],
                out=buf,
            )
            self.assertTrue(out_path.is_file())
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            for key in _TOP_LEVEL_KEYS:
                self.assertIn(key, payload)


# ---------------------------------------------------------------------------
# Banned-imports guard
# ---------------------------------------------------------------------------


class TestBannedImports(unittest.TestCase):
    def test_module_does_not_pull_in_paid_or_fastapi_seams(self) -> None:
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(smoke))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])

        banned = {
            "yfinance", "openai", "anthropic",
            "market_data", "market_check",
            "api", "routes", "fastapi",
        }
        leaked = imported & banned
        self.assertEqual(
            leaked, set(),
            f"placebo smoke must not import: {leaked}",
        )


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_comparison_notes_avoid_pass_fail_vocabulary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(tmp, _seed_records(event_ids=[1, 2]))
            db_path = _make_events_db(tmp, {
                1: base.isoformat(), 2: base.isoformat(),
            })
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-10, 10), horizons=(1, 5, 20),
                price_reader=_build_price_reader(
                    base_date=base, span_days=300,
                ),
            )
        joined = " ".join(payload["comparison_notes"]).lower()
        for token in (
            "proven", "guaranteed", "passes", "passed",
            "fails", "failed", "confirms", "refutes",
            "alpha generated", "validated trade",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, joined)


# ---------------------------------------------------------------------------
# Coverage diagnostics + draw accounting
# ---------------------------------------------------------------------------


class TestCoverageDiagnostics(unittest.TestCase):
    def test_coverage_diagnostics_carry_per_event_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            recs = _seed_records(event_ids=[1])
            ev_path = _write_evidence(tmp, recs)
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-5, 5), horizons=(1,),
                price_reader=_build_price_reader(
                    base_date=base, span_days=300,
                ),
            )
        diags = payload["coverage_diagnostics"]
        self.assertIn("1", diags)
        entry = diags["1"]
        for key in (
            "event_date", "primary_ticker", "benchmark",
            "asset_first", "asset_last",
            "asset_bar_count", "pre_event_bar_count",
        ):
            self.assertIn(key, entry, f"missing coverage key: {key}")
        self.assertGreater(entry["asset_bar_count"], 0)

    def test_draw_accounting_balances(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            recs = _seed_records(event_ids=[1, 2])
            ev_path = _write_evidence(tmp, recs)
            db_path = _make_events_db(
                tmp, {1: base.isoformat(), 2: base.isoformat()},
            )
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-10, 10), horizons=(1, 5),
                price_reader=_build_price_reader(
                    base_date=base, span_days=300,
                ),
            )
        req = payload["requested_placebo_draws"]
        comp = payload["computable_placebo_draws"]
        skip = payload["skipped_placebo_draws"]
        self.assertEqual(
            req, comp + skip,
            "requested = computable + skipped accounting must hold",
        )

    def test_skip_reason_counts_use_canonical_vocabulary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(tmp, _seed_records(event_ids=[1]))
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            # Use a tight cache window that forces both uncached_bar
            # and insufficient_pre_history skips: the asset has only
            # a handful of bars and offset +10 falls outside it.
            base_day = base
            small_reader = _build_price_reader(
                base_date=base_day, span_days=20,
            )
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-10, -5, 5, 10), horizons=(1,),
                price_reader=small_reader,
            )
        reasons = set(payload["skip_reason_counts"].keys())
        allowed = {
            "uncached_bar",
            "insufficient_pre_history",
            "compute_event_study_error",
            "no_event_date",
            "no_price_coverage",
        }
        self.assertTrue(reasons, "no skip reasons recorded for tight cache")
        self.assertTrue(
            reasons <= allowed,
            f"unexpected skip-reason keys: {reasons - allowed}",
        )


# ---------------------------------------------------------------------------
# Auto-shrink surfaces methodology adjustments
# ---------------------------------------------------------------------------


class TestAutoShrink(unittest.TestCase):
    def test_auto_shrink_records_methodology_adjustment(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(tmp, _seed_records(event_ids=[1]))
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            # 60-day estimation window > pre-history we can build from
            # a 50-day synthetic series, so auto-shrink must fire and
            # record an adjustment per draw.
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(5,), horizons=(1,),
                estimation_window=60,
                min_estimation_window=5,
                auto_shrink_estimation_window=True,
                price_reader=_build_price_reader(
                    base_date=base, span_days=40,
                ),
            )
        self.assertGreater(len(payload["methodology_adjustments"]), 0)
        joined = " ".join(payload["warnings"]).lower()
        self.assertIn("methodology adjustment", joined)
        self.assertIn("estimation window was reduced", joined)

    def test_no_shrink_flag_skips_when_pre_history_short(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(tmp, _seed_records(event_ids=[1]))
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(5,), horizons=(1,),
                estimation_window=60,
                auto_shrink_estimation_window=False,
                price_reader=_build_price_reader(
                    base_date=base, span_days=40,
                ),
            )
        # No draws should compute; no methodology adjustments either.
        self.assertEqual(payload["computable_placebo_draws"], 0)
        self.assertEqual(len(payload["methodology_adjustments"]), 0)
        # And the operator gets a pointed recommendation.
        self.assertIsNotNone(payload["recommended_next_action"])
        self.assertIn(
            "--no-shrink",
            payload["recommended_next_action"],
        )


# ---------------------------------------------------------------------------
# Coverage-aware fallback offsets
# ---------------------------------------------------------------------------


class TestFallbackOffsets(unittest.TestCase):
    def test_fallback_used_when_spec_offsets_all_uncached(self) -> None:
        """If every spec'd offset lands outside the cached window, the
        smoke must fall back to coverage-aware offsets derived from
        cached trading days."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(tmp, _seed_records(event_ids=[1]))
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            # All spec'd offsets land well outside the synthetic
            # 30-day cache window, so the first pass produces nothing.
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-200, -180, 180, 200),
                horizons=(1,),
                estimation_window=10,
                price_reader=_build_price_reader(
                    base_date=base, span_days=200,
                ),
            )
        used = payload["placebo_offsets_used"]
        # The fallback must produce offsets and at least one record.
        self.assertGreater(payload["computable_placebo_draws"], 0)
        # And none of the spec'd uncached offsets should appear in
        # the offsets actually used.
        for o in (-200, -180, 180, 200):
            self.assertNotIn(o, used)
        # The note about fallback must surface.
        joined_notes = " ".join(payload["comparison_notes"]).lower()
        self.assertIn(
            "fell back to deterministic offsets", joined_notes,
        )


# ---------------------------------------------------------------------------
# Recommended next action when zero computable draws remain
# ---------------------------------------------------------------------------


class TestRecommendedNextAction(unittest.TestCase):
    def test_zero_draws_with_auto_shrink_recommends_cache_expansion(
        self,
    ) -> None:
        # No price coverage at all → 0 computable draws → cache-
        # expansion recommendation.
        def _no_data(ticker: str, start: str, end: str):
            return [], []

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(tmp, _seed_records(event_ids=[1]))
            db_path = _make_events_db(tmp, {1: base.isoformat()})
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-5, 5), horizons=(1,),
                price_reader=_no_data,
            )
        self.assertEqual(payload["computable_placebo_draws"], 0)
        self.assertIsNotNone(payload["recommended_next_action"])
        self.assertIn(
            "expand the local price cache",
            payload["recommended_next_action"].lower(),
        )

    def test_computable_draws_clear_recommended_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            ev_path = _write_evidence(tmp, _seed_records(event_ids=[1, 2]))
            db_path = _make_events_db(
                tmp, {1: base.isoformat(), 2: base.isoformat()},
            )
            payload = smoke.run_placebo_smoke(
                evidence_path=ev_path, db_path=db_path,
                offsets=(-10, 10), horizons=(1, 5, 20),
                price_reader=_build_price_reader(
                    base_date=base, span_days=300,
                ),
            )
        self.assertGreater(payload["computable_placebo_draws"], 0)
        self.assertIsNone(payload["recommended_next_action"])


# ---------------------------------------------------------------------------
# Live demo bundle: at least some computable draws under default flags
# ---------------------------------------------------------------------------


class TestLiveDemoBundleHasComputableDraws(unittest.TestCase):
    """A bare ``run_placebo_smoke()`` against the tracked demo bundle
    must produce at least one computable placebo draw on the current
    cache — that is the regression this whole task is fixing.

    If the local cache somehow has zero coverage (e.g. a sparse CI
    checkout), the test still passes if the smoke surfaced a
    recommended_next_action — but it must not silently return
    ``computable=0`` with no surfaced reason.
    """

    def test_default_run_produces_draws_or_surfaces_next_action(
        self,
    ) -> None:
        payload = smoke.run_placebo_smoke()
        if payload["computable_placebo_draws"] > 0:
            self.assertIsNone(payload["recommended_next_action"])
            # Every computed draw with shrunk pre-history records a
            # methodology adjustment — count must be ≥ 1 because the
            # local cache has limited pre-history for these tickers.
            self.assertGreater(
                len(payload["methodology_adjustments"]), 0,
                "auto-shrink should fire on the demo cache",
            )
        else:
            self.assertIsNotNone(payload["recommended_next_action"])


# ---------------------------------------------------------------------------
# Default evidence path is the tracked demo bundle
# ---------------------------------------------------------------------------


class TestDefaultEvidencePath(unittest.TestCase):
    """Pin the CLI default to the tracked demo bundle.

    The demo bundle is the stable, checked-in evidence input; the
    smoke must default to it so a fresh clone reproduces the
    comparison without relying on the local untracked
    ``artifacts/`` directory.
    """

    def test_default_evidence_path_is_demo_bundle(self) -> None:
        self.assertEqual(
            smoke._DEFAULT_EVIDENCE_PATH,
            "evidence_artifacts/section_c_v1/freeze_candidate_evidence.json",
        )

    def test_default_evidence_path_resolves_against_repo_root(self) -> None:
        # The tracked bundle ships with the repo; verify it actually
        # exists at the default location so a no-arg invocation can
        # at least open the file.
        repo_root = Path(__file__).resolve().parents[1]
        self.assertTrue(
            (repo_root / smoke._DEFAULT_EVIDENCE_PATH).is_file(),
            (
                "demo bundle missing at "
                f"{smoke._DEFAULT_EVIDENCE_PATH}; "
                "tests for the tracked-bundle default cannot run"
            ),
        )

    def test_default_run_loads_demo_bundle_and_envelope_is_well_formed(
        self,
    ) -> None:
        # Live DB / cache coverage is sparse, so we don't assert any
        # particular placebo count.  We only require that the smoke
        # opens the demo bundle, produces a well-shaped envelope, and
        # leaves cohort_event_count > 0 — proving the default path
        # actually points at a usable evidence file.
        payload = smoke.run_placebo_smoke()
        for key in _TOP_LEVEL_KEYS:
            self.assertIn(key, payload, f"missing top-level key: {key}")
        self.assertIsInstance(payload["errors"], list)
        # The demo bundle's records reference a non-zero cohort.
        self.assertGreater(
            payload["cohort_event_count"], 0,
            "default run did not discover any usable events in the "
            "demo bundle",
        )


# ---------------------------------------------------------------------------
# --input-csv mode (operator-curated batch)
# ---------------------------------------------------------------------------


class TestInputCsv(unittest.TestCase):
    """Pin the --input-csv path: an operator-supplied CSV drives both
    real-side and placebo-side computation; the freeze-candidate
    evidence artifact and events.db are NOT consulted in this mode.
    """

    @staticmethod
    def _write_csv(tmp: Path, rows: list[dict[str, str]]) -> Path:
        import csv as _csv
        path = tmp / "batch.csv"
        if not rows:
            path.write_text(
                "event_date,primary_ticker,benchmark_ticker\n",
                encoding="utf-8",
            )
            return path
        fieldnames = sorted({k for row in rows for k in row})
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = _csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return path

    def test_csv_mode_populates_real_and_placebo_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            csv_path = self._write_csv(tmp, [
                {
                    "event_date":       base.isoformat(),
                    "primary_ticker":   "XOM",
                    "benchmark_ticker": "SPY",
                },
                {
                    "event_date":       (base - timedelta(days=14)).isoformat(),
                    "primary_ticker":   "VLO",
                    "benchmark_ticker": "SPY",
                },
            ])
            payload = smoke.run_placebo_smoke(
                input_csv=csv_path,
                offsets=(-10, 10), horizons=(1, 5, 20),
                price_reader=_build_price_reader(
                    base_date=base, span_days=300,
                ),
            )
        for key in _TOP_LEVEL_KEYS:
            self.assertIn(key, payload, f"missing top-level key: {key}")
        for side in ("event_signal_summary", "placebo_signal_summary"):
            with self.subTest(side=side):
                summary = payload[side]
                for key in _SUMMARY_REQUIRED_KEYS:
                    self.assertIn(key, summary, f"{side} missing {key}")
                self.assertIsInstance(summary["raw_p_candidate_count"], int)
                self.assertIsInstance(summary["fdr_significant_count"], int)
        ev = payload["event_signal_summary"]
        # 2 events × 3 horizons = 6 real-side records when coverage is full.
        self.assertEqual(ev["records_count"], 6)
        # Placebo side must produce at least one draw on the synthetic
        # 300-day series.
        self.assertGreater(payload["placebo_dates_tested"], 0)
        # CSV-mode limitation surfaced.
        joined = " ".join(payload["warnings"]).lower()
        self.assertIn("computed in-session", joined)

    def test_csv_mode_does_not_read_evidence_or_db(self) -> None:
        """In CSV mode, evidence_path / db_path arguments are ignored —
        nonsense paths must not surface artifact/DB error or warning."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            csv_path = self._write_csv(tmp, [
                {
                    "event_date":       base.isoformat(),
                    "primary_ticker":   "XOM",
                    "benchmark_ticker": "SPY",
                },
            ])
            payload = smoke.run_placebo_smoke(
                input_csv=csv_path,
                evidence_path=tmp / "does_not_exist.json",
                db_path=tmp / "no_db.db",
                offsets=(-5, 5), horizons=(1,),
                price_reader=_build_price_reader(
                    base_date=base, span_days=300,
                ),
            )
        joined_errs  = " ".join(payload["errors"]).lower()
        joined_warns = " ".join(payload["warnings"]).lower()
        self.assertNotIn(
            "freeze-candidate evidence file not found", joined_errs,
        )
        self.assertNotIn("events db not found", joined_warns)

    def test_missing_csv_yields_error_with_well_formed_envelope(
        self,
    ) -> None:
        payload = smoke.run_placebo_smoke(
            input_csv=Path("does/not/exist.csv"),
            offsets=(-5, 5), horizons=(1,),
        )
        self.assertFalse(payload["ok"])
        self.assertTrue(
            any("input CSV not found" in e for e in payload["errors"]),
        )
        for key in _TOP_LEVEL_KEYS:
            self.assertIn(key, payload)

    def test_csv_missing_required_column_yields_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = tmp / "bad.csv"
            path.write_text(
                "event_date,primary_ticker\n2024-01-01,SPY\n",
                encoding="utf-8",
            )
            payload = smoke.run_placebo_smoke(
                input_csv=path,
                offsets=(-5, 5), horizons=(1,),
            )
        self.assertFalse(payload["ok"])
        self.assertTrue(
            any("benchmark_ticker" in e for e in payload["errors"]),
        )

    def test_csv_predicted_direction_propagated_without_gating(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            csv_path = self._write_csv(tmp, [
                {
                    "event_date":           base.isoformat(),
                    "primary_ticker":       "XOM",
                    "benchmark_ticker":     "SPY",
                    "predicted_direction":  "positive",
                },
            ])
            payload = smoke.run_placebo_smoke(
                input_csv=csv_path,
                offsets=(-5, 5), horizons=(1,),
                price_reader=_build_price_reader(
                    base_date=base, span_days=300,
                ),
            )
        for key in _TOP_LEVEL_KEYS:
            self.assertIn(key, payload)
        # Direction is documentation only — no direction-related warning
        # or skip reason from CSV mode itself.
        joined = " ".join(payload["warnings"]).lower()
        self.assertNotIn("direction", joined)
        self.assertNotIn("direction", " ".join(payload["errors"]).lower())

    def test_csv_main_flag_routes_through_new_path(self) -> None:
        """The CLI --input-csv flag must route through run_placebo_smoke's
        CSV branch and emit a well-formed JSON envelope."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            csv_path = self._write_csv(tmp, [
                {
                    "event_date":       base.isoformat(),
                    "primary_ticker":   "XOM",
                    "benchmark_ticker": "SPY",
                },
            ])
            buf = StringIO()
            rc = smoke.main(
                argv=[
                    "--json",
                    "--input-csv", str(csv_path),
                    "--evidence-path", str(tmp / "does_not_exist.json"),
                    "--db-path",       str(tmp / "no_db.db"),
                    "--offsets",       "-5", "5",
                    "--horizons",      "1",
                ],
                out=buf,
            )
        payload = json.loads(buf.getvalue())
        for key in _TOP_LEVEL_KEYS:
            self.assertIn(key, payload)
        self.assertIn(rc, (0, 1))
        # Confirm the run actually used the CSV branch.
        joined = " ".join(payload["warnings"]).lower()
        self.assertIn("computed in-session", joined)

    def test_csv_real_side_records_carry_per_horizon_shape(self) -> None:
        """The CSV-mode real-side compute must produce one record per
        (event, horizon) when coverage is full, with well-formed
        non-negative counts.  Pins that the pipeline actually runs
        event-study against the CSV rather than silently returning
        zeros, without relying on the synthetic fixture's
        weekend-aware shock alignment.
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base = date(2026, 4, 6)
            csv_path = self._write_csv(tmp, [
                {
                    "event_date":       base.isoformat(),
                    "primary_ticker":   "XOM",
                    "benchmark_ticker": "SPY",
                },
                {
                    "event_date":       (base - timedelta(days=21)).isoformat(),
                    "primary_ticker":   "VLO",
                    "benchmark_ticker": "SPY",
                },
            ])
            payload = smoke.run_placebo_smoke(
                input_csv=csv_path,
                offsets=(-10, 10), horizons=(1, 5, 20),
                price_reader=_build_price_reader(
                    base_date=base, span_days=300,
                ),
            )
        ev = payload["event_signal_summary"]
        # 2 events × 3 horizons = 6 records with full synthetic coverage.
        self.assertEqual(ev["records_count"], 6)
        # by_horizon breakdown is well-formed and sums to records_count.
        by_h = ev["by_horizon"]
        for h in ("1", "5", "20"):
            self.assertIn(h, by_h)
            self.assertEqual(by_h[h]["records_count"], 2)
        rawp = ev["raw_p_candidate_count"]
        fdrs = ev["fdr_significant_count"]
        self.assertGreaterEqual(rawp, 0)
        self.assertGreaterEqual(fdrs, 0)
        # raw_p and fdr labels are disjoint by construction
        # (raw_p_candidate ↔ p ≤ α AND NOT FDR-significant).
        self.assertLessEqual(rawp + fdrs, ev["records_count"])


if __name__ == "__main__":
    unittest.main()
