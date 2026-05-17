"""Tests for ``scripts/manual_five_event_validation_smoke.py``.

The smoke runs the existing zero-cost event-study + raw-p + BH-FDR
primitives over an operator-supplied 5-row CSV of (event_date,
primary_ticker, benchmark_ticker, ...) candidates and produces per-
(event, horizon) records that mirror the freeze-candidate vocabulary
without merging into the main cohort.

Pinned contract:

* Output envelope keys: ``ok``, ``input_csv``, ``horizons``,
  ``alpha``, ``rows_loaded``, ``events_evaluated``, ``records_count``,
  ``fdr_significant_count``, ``raw_p_only_candidate_count``,
  ``event_records``, ``missing_coverage``, ``warnings``, ``errors``.
* ``horizons`` defaults to ``(1, 5, 20)`` — the freeze-candidate set.
* Each per-record entry carries:
  ``candidate_id``, ``row_index``, ``headline``, ``event_date``,
  ``primary_ticker``, ``benchmark_ticker``, ``mechanism_family``,
  ``horizon``, ``abnormal_return``, ``sar``, ``p_value``, ``fdr_q``,
  ``fdr_significant``, ``raw_p_candidate``, ``interpretation``,
  ``source``.
* ``source`` is the literal ``"manual_five_event_batch"`` so the
  records can never be silently merged into the main cohort.
* Raw p vs FDR distinction preserved: at least one synthetic case
  produces a ``raw_p_candidate=True`` row whose ``fdr_significant`` is
  ``False``.
* Per-event-per-horizon p-values come from a normal z-test on SAR;
  BH-adjusted q is computed across the pooled valid p-values; the
  adjusted q is always >= the raw p for each record.
* Missing coverage is surfaced cleanly (no crash; explicit reason).
* Conservative wording — banned overclaim tokens absent from any
  rendered output.
* Import isolation — no provider / yfinance / LLM / FastAPI / api /
  routes.* at module load.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import manual_five_event_validation_smoke as cli  # noqa: E402


_REQUIRED_TOP_KEYS = (
    "ok",
    "input_csv",
    "horizons",
    "alpha",
    "rows_loaded",
    "events_evaluated",
    "records_count",
    "fdr_significant_count",
    "raw_p_only_candidate_count",
    "event_records",
    "missing_coverage",
    "warnings",
    "errors",
)


_REQUIRED_RECORD_KEYS = (
    "candidate_id",
    "row_index",
    "headline",
    "event_date",
    "primary_ticker",
    "benchmark_ticker",
    "mechanism_family",
    "horizon",
    "abnormal_return",
    "sar",
    "p_value",
    "fdr_q",
    "fdr_significant",
    "raw_p_candidate",
    "interpretation",
    "source",
)


_BANNED_TOKENS = (
    "proof",
    "proven",
    "guaranteed",
    "automatically",
    "validated",
    "alpha generated",
    "correct ticker",
    "definitely",
    "approved",
    "production ready",
    "production-ready",
    "demo_ready",
    "demo-ready",
)


_DEFAULT_HORIZONS = (1, 5, 20)
_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Synthetic price generator — used by the seam fake so tests never
# depend on price_cache.db contents.
# ---------------------------------------------------------------------------


def _synthetic_coverage(
    *,
    base_asset:     float = 100.0,
    base_bench:     float = 100.0,
    n_pre:          int   = 80,
    n_post:         int   = 25,
    daily_drift:    float = 0.0,
    forward_jump:   float = 0.02,
) -> dict[str, Any]:
    """Construct synthetic aligned price arrays for one event.

    The pre-event window is filled with a deterministic geometric walk
    so ``sigma_ar_daily`` is well-defined; the event close is at
    ``event_index = n_pre`` and forward closes carry a small jump so
    SAR is non-trivial at each horizon.  The exact numerical values
    don't matter to the contract tests — only the envelope/record
    shape does — but they let the smoke compute deterministic SARs.
    """
    # Pre-event walk: asset and benchmark move identically so daily
    # AR is zero in the estimation window → sigma=0 → SAR=None.  To
    # get a non-zero sigma, give the asset a small random-looking
    # perturbation.  We use a fixed cosine schedule for reproducibility.
    import math
    asset: list[float] = []
    bench: list[float] = []
    for i in range(n_pre):
        # Bench geometric drift.
        bench.append(base_bench * (1.0 + daily_drift) ** i)
        asset.append(
            base_asset
            * (1.0 + daily_drift + 0.001 * math.cos(i)) ** i
        )
    # Event close (event_index).
    asset.append(asset[-1])
    bench.append(bench[-1])
    # Forward closes: asset jumps relative to bench.
    for j in range(1, n_post + 1):
        asset.append(asset[n_pre] * (1.0 + forward_jump) ** j)
        bench.append(bench[n_pre])
    dates = [f"d{idx:04d}" for idx in range(len(asset))]
    return {
        "available":        True,
        "asset_prices":     asset,
        "benchmark_prices": bench,
        "event_index":      n_pre,
        "dates":            dates,
        "reason":           "",
    }


def _missing_coverage(reason: str) -> dict[str, Any]:
    return {
        "available":        False,
        "asset_prices":     [],
        "benchmark_prices": [],
        "event_index":      -1,
        "dates":            [],
        "reason":           reason,
    }


# ---------------------------------------------------------------------------
# Fixture CSV writers
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    import csv
    columns = [
        "event_date",
        "headline",
        "source_url",
        "mechanism_family",
        "primary_ticker",
        "benchmark_ticker",
        "predicted_direction",
        "why_this_event_is_defensible",
        "what_would_falsify",
        "operator_notes",
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def _minimal_row(
    *,
    event_date:        str = "2021-05-10",
    headline:          str = "synthetic",
    mechanism_family:  str = "synth_family",
    primary_ticker:    str = "ASSET",
    benchmark_ticker:  str = "BENCH",
) -> dict[str, str]:
    return {
        "event_date":       event_date,
        "headline":         headline,
        "mechanism_family": mechanism_family,
        "primary_ticker":   primary_ticker,
        "benchmark_ticker": benchmark_ticker,
    }


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class EnvelopeShapeTests(unittest.TestCase):

    def test_envelope_carries_exactly_required_top_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_minimal_row()])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        self.assertEqual(set(env.keys()), set(_REQUIRED_TOP_KEYS))

    def test_default_horizons_are_one_five_twenty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_minimal_row()])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        self.assertEqual(tuple(env["horizons"]), _DEFAULT_HORIZONS)


class RecordShapeTests(unittest.TestCase):

    def test_each_record_carries_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_minimal_row()])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        self.assertGreaterEqual(len(env["event_records"]), 1)
        for rec in env["event_records"]:
            self.assertEqual(
                set(rec.keys()),
                set(_REQUIRED_RECORD_KEYS),
                msg=f"record key drift: {sorted(rec.keys())}",
            )

    def test_source_token_is_manual_five_event_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_minimal_row()])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        for rec in env["event_records"]:
            self.assertEqual(rec["source"], "manual_five_event_batch")

    def test_horizon_set_in_records_matches_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_minimal_row()])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        horizons = sorted({rec["horizon"] for rec in env["event_records"]})
        self.assertEqual(tuple(horizons), _DEFAULT_HORIZONS)

    def test_record_count_is_events_times_horizons(self) -> None:
        rows = [
            _minimal_row(primary_ticker=f"A{i}", event_date=f"2021-05-{i:02d}")
            for i in (10, 11, 12)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, rows)
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        self.assertEqual(env["events_evaluated"], 3)
        self.assertEqual(env["records_count"], 3 * len(_DEFAULT_HORIZONS))
        self.assertEqual(env["records_count"], len(env["event_records"]))


# ---------------------------------------------------------------------------
# Raw p vs FDR distinction
# ---------------------------------------------------------------------------


class RawPVsFdrTests(unittest.TestCase):

    def test_fdr_q_is_always_at_or_above_raw_p(self) -> None:
        """BH-adjusted q is monotone non-decreasing relative to the
        underlying raw p when ordered by rank — for any individual
        record q >= p must hold."""
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [
                _minimal_row(primary_ticker=f"A{i}",
                              event_date=f"2021-05-{i:02d}")
                for i in (10, 11, 12, 13, 14)
            ])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        for rec in env["event_records"]:
            p = rec["p_value"]
            q = rec["fdr_q"]
            if p is None or q is None:
                continue
            self.assertGreaterEqual(
                q, p,
                msg=f"fdr_q ({q}) < p_value ({p}) for record {rec}",
            )

    def test_raw_p_candidate_only_when_p_le_alpha_and_q_gt_alpha(self) -> None:
        """When raw p < alpha but BH q >= alpha, the record carries
        ``raw_p_candidate=True`` and ``fdr_significant=False``.  This
        distinguishes raw-p evidence from FDR-significant evidence.
        """
        # 5 events with one strong jump (=> one small p) and four
        # near-zero jumps (=> p near 1) so BH inflation is large.
        rows = [
            _minimal_row(primary_ticker="STRONG", event_date="2021-05-10"),
            _minimal_row(primary_ticker="WEAK_A", event_date="2021-05-11"),
            _minimal_row(primary_ticker="WEAK_B", event_date="2021-05-12"),
            _minimal_row(primary_ticker="WEAK_C", event_date="2021-05-13"),
            _minimal_row(primary_ticker="WEAK_D", event_date="2021-05-14"),
        ]

        def fake(*, primary_ticker: str, benchmark_ticker: str,
                 event_date: str) -> dict[str, Any]:
            if primary_ticker == "STRONG":
                return _synthetic_coverage(forward_jump=0.08)
            return _synthetic_coverage(forward_jump=0.0001)

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, rows)
            with patch.object(
                cli, "_load_aligned_prices", side_effect=fake,
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        any_raw_only = any(
            rec["raw_p_candidate"] and not rec["fdr_significant"]
            for rec in env["event_records"]
        )
        self.assertTrue(
            any_raw_only,
            "expected at least one raw_p_candidate=True / "
            "fdr_significant=False record in the synthetic scenario",
        )
        # And: no record should be raw_p_candidate AND fdr_significant
        # simultaneously — the two labels are disjoint.
        for rec in env["event_records"]:
            self.assertFalse(
                rec["raw_p_candidate"] and rec["fdr_significant"],
                msg=(
                    f"record carries both raw_p_candidate and "
                    f"fdr_significant: {rec}"
                ),
            )

    def test_counts_match_label_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_minimal_row()])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        fdr_count = sum(
            1 for r in env["event_records"] if r["fdr_significant"]
        )
        rawp_only_count = sum(
            1 for r in env["event_records"]
            if r["raw_p_candidate"] and not r["fdr_significant"]
        )
        self.assertEqual(env["fdr_significant_count"],     fdr_count)
        self.assertEqual(env["raw_p_only_candidate_count"], rawp_only_count)


# ---------------------------------------------------------------------------
# Missing coverage
# ---------------------------------------------------------------------------


class MissingCoverageTests(unittest.TestCase):

    def test_missing_coverage_does_not_crash_and_is_surfaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [
                _minimal_row(primary_ticker="ZIM", event_date="2021-03-24"),
            ])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_missing_coverage(
                    "no cached bars for ZIM at 2021-03-24",
                ),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        self.assertEqual(env["events_evaluated"], 0)
        self.assertEqual(env["records_count"], 0)
        self.assertEqual(len(env["missing_coverage"]), 1)
        entry = env["missing_coverage"][0]
        self.assertEqual(entry["primary_ticker"], "ZIM")
        self.assertNotEqual(entry["reason"].strip(), "")

    def test_partial_coverage_some_events_pass(self) -> None:
        rows = [
            _minimal_row(primary_ticker="COVERED",   event_date="2021-05-10"),
            _minimal_row(primary_ticker="UNCOVERED", event_date="2021-03-24"),
        ]

        def fake(*, primary_ticker: str, benchmark_ticker: str,
                 event_date: str) -> dict[str, Any]:
            if primary_ticker == "COVERED":
                return _synthetic_coverage()
            return _missing_coverage("ipo too recent")

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, rows)
            with patch.object(
                cli, "_load_aligned_prices", side_effect=fake,
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        self.assertEqual(env["events_evaluated"], 1)
        self.assertEqual(env["records_count"], len(_DEFAULT_HORIZONS))
        self.assertEqual(len(env["missing_coverage"]), 1)
        self.assertEqual(env["missing_coverage"][0]["primary_ticker"], "UNCOVERED")

    def test_missing_coverage_still_yields_ok_true(self) -> None:
        """Missing-coverage is a clean reported state, not a failure."""
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_minimal_row(primary_ticker="MISSING")])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_missing_coverage("not in cache"),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        self.assertTrue(env["ok"])
        self.assertEqual(env["errors"], [])

    def test_missing_coverage_entries_carry_headline_and_mechanism_family(
        self,
    ) -> None:
        """A skipped row must still tell the operator which event it
        was — ticker alone is not enough when the batch contains five
        different mechanism families.  The missing-coverage entry has
        to carry ``headline`` and ``mechanism_family`` from the CSV.
        """
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [
                _minimal_row(
                    primary_ticker="ZIM",
                    event_date="2021-03-24",
                    headline="Ever Given blocks Suez Canal",
                    mechanism_family="shipping_chokepoint_logistics",
                ),
            ])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_missing_coverage(
                    "no cached bars for ZIM at 2021-03-24",
                ),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        self.assertEqual(len(env["missing_coverage"]), 1)
        entry = env["missing_coverage"][0]
        self.assertEqual(entry["headline"], "Ever Given blocks Suez Canal")
        self.assertEqual(
            entry["mechanism_family"], "shipping_chokepoint_logistics",
        )


# ---------------------------------------------------------------------------
# CSV ingestion
# ---------------------------------------------------------------------------


class CsvIngestionTests(unittest.TestCase):

    def test_missing_csv_file_surfaces_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "does_not_exist.csv")
            env = cli.run_manual_five_event_validation(input_csv=missing)
        self.assertFalse(env["ok"])
        self.assertGreaterEqual(len(env["errors"]), 1)

    def test_extra_columns_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            # Write the full 10-column header the user provided.
            _write_csv(csv_path, [{
                "event_date":                    "2021-05-10",
                "headline":                      "h",
                "source_url":                    "https://example.test",
                "mechanism_family":              "synth",
                "primary_ticker":                "A",
                "benchmark_ticker":              "B",
                "predicted_direction":           "positive",
                "why_this_event_is_defensible":  "x",
                "what_would_falsify":            "y",
                "operator_notes":                "z",
            }])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        self.assertTrue(env["ok"])
        self.assertEqual(env["rows_loaded"], 1)

    def test_row_missing_required_field_surfaces_as_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            # Row missing primary_ticker.
            _write_csv(csv_path, [_minimal_row(primary_ticker="")])
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                env = cli.run_manual_five_event_validation(
                    input_csv=str(csv_path),
                )
        self.assertEqual(env["events_evaluated"], 0)
        self.assertEqual(len(env["missing_coverage"]), 1)
        self.assertIn(
            "primary_ticker",
            env["missing_coverage"][0]["reason"].lower(),
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class CliTests(unittest.TestCase):

    def test_json_emission_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_minimal_row()])
            buf = io.StringIO()
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                rc = cli.main([
                    "--json", "--input-csv", str(csv_path),
                ], out=buf)
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_TOP_KEYS))

    def test_exit_code_one_when_csv_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "no.csv")
            buf = io.StringIO()
            rc = cli.main(["--json", "--input-csv", missing], out=buf)
        self.assertEqual(rc, 1)

    def test_exit_code_zero_when_only_missing_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_minimal_row()])
            buf = io.StringIO()
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_missing_coverage("no cache"),
            ):
                rc = cli.main(["--json", "--input-csv", str(csv_path)],
                              out=buf)
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class ConservativeWordingTests(unittest.TestCase):

    def test_rendered_json_carries_no_banned_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "rows.csv"
            _write_csv(csv_path, [_minimal_row()])
            buf = io.StringIO()
            with patch.object(
                cli, "_load_aligned_prices",
                return_value=_synthetic_coverage(),
            ):
                cli.main([
                    "--json", "--input-csv", str(csv_path),
                ], out=buf)
        text = buf.getvalue().lower()
        for tok in _BANNED_TOKENS:
            self.assertNotIn(
                tok, text,
                msg=f"banned token {tok!r} appeared in rendered JSON",
            )

    def test_module_docstring_carries_no_banned_tokens(self) -> None:
        doc = (cli.__doc__ or "").lower()
        for tok in _BANNED_TOKENS:
            self.assertNotIn(
                tok, doc,
                msg=f"banned token {tok!r} appeared in module docstring",
            )


# ---------------------------------------------------------------------------
# Read-only / no-paid contract
# ---------------------------------------------------------------------------


class ReadOnlyContractTests(unittest.TestCase):

    _BLOCKED: tuple[str, ...] = (
        "yfinance",
        "market_data",
        "market_check",
        "news_fetch",
        "news_relevance",
        "api",
        "openai",
        "anthropic",
        "fastapi",
    )

    def test_module_import_does_not_leak_paid_or_routes_surfaces(self) -> None:
        from tests._import_isolation_check import (
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name="scripts.manual_five_event_validation_smoke",
            blocked=self._BLOCKED,
            blocked_starts_with=("routes.",),
        )

    def test_module_source_does_not_call_writers(self) -> None:
        src_path = _REPO_ROOT / "scripts" / "manual_five_event_validation_smoke.py"
        text = src_path.read_text(encoding="utf-8")
        for banned in (
            ".write_text(",
            ".write_bytes(",
            "os.remove(",
            "os.unlink(",
            "shutil.rmtree(",
        ):
            self.assertNotIn(
                banned, text,
                msg=f"forbidden mutation call: {banned!r}",
            )


# ---------------------------------------------------------------------------
# Bundled example CSV — the operator-curated 5-row batch
# ---------------------------------------------------------------------------


class BundledCsvTests(unittest.TestCase):

    _CSV_PATH = _REPO_ROOT / "examples" / "manual_five_event_expansion_batch.csv"

    def test_bundled_csv_exists(self) -> None:
        self.assertTrue(self._CSV_PATH.is_file())

    def test_bundled_csv_has_five_rows(self) -> None:
        import csv as _csv
        with open(self._CSV_PATH, "r", encoding="utf-8") as fh:
            reader = _csv.DictReader(fh)
            rows = list(reader)
        self.assertEqual(len(rows), 5)
        for r in rows:
            for required in ("event_date", "primary_ticker", "benchmark_ticker"):
                self.assertTrue(r.get(required), f"missing {required} in row")


if __name__ == "__main__":
    unittest.main()
