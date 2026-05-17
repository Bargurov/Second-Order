"""Tests for ``scripts/manual_five_event_cache_coverage_preview.py``.

Pin the contract that the cache-coverage preview is:

* Read-only.  Never imports a provider, ``yfinance``, an LLM, the
  FastAPI app, or ``market_data``.  Writes nothing to disk unless
  ``--output`` is supplied.
* Self-contained on the operator's CSV.  Loads the five-event
  expansion-batch CSV by default; ``--input-csv`` overrides.
* Honest about missing coverage.  Every (event_row, ticker) pair
  whose cached pre-event history is shorter than the 60-trading-day
  estimation window must surface in ``missing_coverage`` and the
  envelope's ``recommended_next_action`` must point to cache
  expansion.
* Aware of known short-history risks.  ZIM IPO'd 2021-01-28, so
  any operator row that names ZIM as the primary for an event
  before mid-2021 leaves no pre-event estimation window; the
  preview must surface this in ``warnings``.  The bundled CSV no
  longer references ZIM (the Suez row was swapped to MATX), so the
  warning is exercised via a synthetic CSV — the registry remains
  load-bearing for future operator additions.
* Deterministic.  Given the same CSV and the same patched price
  reader, the JSON envelope is byte-equal across runs.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import manual_five_event_cache_coverage_preview as preview  # noqa: E402


_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "ok",
    "input_csv",
    "rows_checked",
    "tickers_needed",
    "required_windows",
    "available_coverage",
    "missing_coverage",
    "recommended_next_action",
    "warnings",
    "errors",
)

_BATCH_CSV: Path = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "manual_five_event_expansion_batch.csv"
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _empty_reader(ticker: str, start: str, end: str):
    """Patchable price reader that always reports an empty cache."""
    return [], []


def _full_reader(*, pre_bars: int = 80, post_bars: int = 40):
    """Returns a reader that produces ``pre_bars`` trading days before
    the requested-end midpoint and ``post_bars`` after — enough to
    satisfy the 60-bar estimation window contract."""
    def _read(ticker: str, start: str, end: str):
        s = date.fromisoformat(start[:10])
        e = date.fromisoformat(end[:10])
        # Synthetic anchor at the midpoint of the requested window.
        midpoint = s + (e - s) // 2
        dates: list[str] = []
        d = midpoint - timedelta(days=pre_bars + 30)
        while d <= midpoint + timedelta(days=post_bars + 30):
            if d.weekday() < 5:        # Mon–Fri
                if s <= d <= e:
                    dates.append(d.isoformat())
            d += timedelta(days=1)
        closes = [100.0] * len(dates)
        return dates, closes
    return _read


def _write_csv(tmp: Path, rows: list[dict[str, str]]) -> Path:
    path = tmp / "batch.csv"
    if not rows:
        path.write_text(
            "event_date,primary_ticker,benchmark_ticker\n",
            encoding="utf-8",
        )
        return path
    fieldnames = sorted({k for row in rows for k in row})
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class TestEnvelopeShape(unittest.TestCase):
    def test_top_level_keys_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            csv_path = _write_csv(tmp, [
                {
                    "event_date":       "2024-01-15",
                    "primary_ticker":   "SPY",
                    "benchmark_ticker": "QQQ",
                },
            ])
            payload = preview.run_coverage_preview(
                input_csv=csv_path,
                price_reader=_empty_reader,
            )
        for key in _TOP_LEVEL_KEYS:
            self.assertIn(key, payload, f"missing key: {key}")

    def test_real_csv_loads_with_nine_tickers(self) -> None:
        payload = preview.run_coverage_preview(
            input_csv=_BATCH_CSV,
            price_reader=_empty_reader,
        )
        self.assertEqual(payload["rows_checked"], 5)
        expected = {
            "UGA", "USO", "NUE", "SPY", "KBE", "NVDA",
            "SMH", "MATX", "IYT",
        }
        self.assertEqual(set(payload["tickers_needed"]), expected)


# ---------------------------------------------------------------------------
# Empty cache → every window is missing + recommended_next_action set
# ---------------------------------------------------------------------------


class TestEmptyCache(unittest.TestCase):
    def test_empty_cache_marks_every_window_missing(self) -> None:
        payload = preview.run_coverage_preview(
            input_csv=_BATCH_CSV,
            price_reader=_empty_reader,
        )
        # 5 events × 2 tickers per event = 10 required windows.
        self.assertEqual(len(payload["required_windows"]), 10)
        self.assertEqual(len(payload["available_coverage"]), 10)
        self.assertEqual(len(payload["missing_coverage"]), 10)
        for entry in payload["available_coverage"]:
            self.assertEqual(entry["bar_count"], 0)
            self.assertFalse(entry["sufficient_for_estimation_window"])

    def test_recommended_next_action_mentions_cache_expansion(self) -> None:
        payload = preview.run_coverage_preview(
            input_csv=_BATCH_CSV,
            price_reader=_empty_reader,
        )
        rec = payload["recommended_next_action"]
        self.assertIsNotNone(rec)
        self.assertIn("expand", rec.lower())
        self.assertIn("price cache", rec.lower())


# ---------------------------------------------------------------------------
# Sufficient cache → no missing entries, no recommendation
# ---------------------------------------------------------------------------


class TestSufficientCache(unittest.TestCase):
    def test_full_cache_yields_no_missing(self) -> None:
        payload = preview.run_coverage_preview(
            input_csv=_BATCH_CSV,
            price_reader=_full_reader(pre_bars=80, post_bars=40),
        )
        self.assertEqual(
            payload["missing_coverage"], [],
            "no missing entries expected when cache is full",
        )
        self.assertIsNone(
            payload["recommended_next_action"],
            "recommended_next_action must be cleared when coverage is full",
        )
        for entry in payload["available_coverage"]:
            self.assertTrue(
                entry["sufficient_for_estimation_window"],
                f"insufficient flag for {entry['ticker']} "
                f"({entry['role']}) at {entry['event_date']}",
            )


# ---------------------------------------------------------------------------
# ZIM IPO-risk warning
# ---------------------------------------------------------------------------


class TestZimIpoWarning(unittest.TestCase):
    def test_zim_pre_ipo_window_emits_ipo_warning(self) -> None:
        # Bundled CSV no longer references ZIM (the Suez row uses MATX
        # to clear the IPO-window gap), so this test pins the warning
        # path against a synthetic CSV that re-creates the original
        # pre-IPO scenario.  Keeps coverage of _scan_ipo_risk +
        # _KNOWN_IPO_RISKS so the registry stays load-bearing.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            csv_path = _write_csv(tmp, [
                {
                    "event_date":       "2021-03-24",
                    "primary_ticker":   "ZIM",
                    "benchmark_ticker": "IYT",
                    "headline":         "Synthetic Ever Given row using ZIM",
                },
            ])
            payload = preview.run_coverage_preview(
                input_csv=csv_path,
                price_reader=_empty_reader,
            )
        joined = " ".join(payload["warnings"]).lower()
        self.assertIn("zim", joined)
        self.assertIn("ipo", joined)
        self.assertIn("2021-01-28", joined)

    def test_zim_post_ipo_event_does_not_emit_pre_ipo_warning(
        self,
    ) -> None:
        # Sweep ZIM to a 2024 event_date where every requested-window
        # boundary lands well after the IPO; the IPO warning must
        # NOT fire.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            csv_path = _write_csv(tmp, [
                {
                    "event_date":       "2024-06-15",
                    "primary_ticker":   "ZIM",
                    "benchmark_ticker": "IYT",
                    "headline":         "Synthetic ZIM event after IPO",
                },
            ])
            payload = preview.run_coverage_preview(
                input_csv=csv_path,
                price_reader=_full_reader(pre_bars=80, post_bars=40),
            )
        joined = " ".join(payload["warnings"]).lower()
        self.assertNotIn("zim", joined)


# ---------------------------------------------------------------------------
# Missing-coverage reasons carry ZIM IPO context when the ticker is ZIM
# ---------------------------------------------------------------------------


class TestZimMissingReasonContext(unittest.TestCase):
    def test_zim_missing_entry_mentions_ipo_when_history_starts_post_ipo(
        self,
    ) -> None:
        # Reader simulates a cache where ZIM has *some* history that
        # begins exactly at the IPO date but is shorter than the
        # 60-bar estimation window; the missing-entry reason should
        # call out the IPO context.
        def _reader_zim_post_ipo(ticker: str, start: str, end: str):
            if ticker != "ZIM":
                # Plenty of data for the benchmark.
                return _full_reader(
                    pre_bars=80, post_bars=40,
                )(ticker, start, end)
            ipo = date.fromisoformat("2021-01-28")
            requested_end = date.fromisoformat(end[:10])
            dates: list[str] = []
            d = ipo
            while d <= requested_end:
                if d.weekday() < 5:
                    dates.append(d.isoformat())
                d += timedelta(days=1)
            closes = [10.0] * len(dates)
            return dates, closes

        # Bundled CSV no longer references ZIM (the Suez row uses
        # MATX), so this test drives the IPO-context branch via a
        # synthetic CSV that re-creates the short-history scenario.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            csv_path = _write_csv(tmp, [
                {
                    "event_date":       "2021-03-24",
                    "primary_ticker":   "ZIM",
                    "benchmark_ticker": "IYT",
                    "headline":         "Synthetic Ever Given row using ZIM",
                },
            ])
            payload = preview.run_coverage_preview(
                input_csv=csv_path,
                price_reader=_reader_zim_post_ipo,
            )
        zim_entries = [
            m for m in payload["missing_coverage"]
            if m["ticker"] == "ZIM"
        ]
        self.assertTrue(zim_entries, "expected a ZIM missing entry")
        joined = " ".join(e["reason"] for e in zim_entries).lower()
        self.assertIn("ipo", joined)
        self.assertIn("2021-01-28", joined)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_produce_byte_equal_output(self) -> None:
        a = preview.run_coverage_preview(
            input_csv=_BATCH_CSV,
            price_reader=_full_reader(pre_bars=80, post_bars=40),
        )
        b = preview.run_coverage_preview(
            input_csv=_BATCH_CSV,
            price_reader=_full_reader(pre_bars=80, post_bars=40),
        )
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# Required windows include both roles and the right ticker pair
# ---------------------------------------------------------------------------


class TestRequiredWindows(unittest.TestCase):
    def test_each_row_emits_two_required_windows(self) -> None:
        payload = preview.run_coverage_preview(
            input_csv=_BATCH_CSV,
            price_reader=_empty_reader,
        )
        # 5 rows × 2 roles (primary + benchmark) = 10 windows.
        self.assertEqual(len(payload["required_windows"]), 10)
        by_role: dict[str, int] = {}
        for w in payload["required_windows"]:
            by_role[w["role"]] = by_role.get(w["role"], 0) + 1
        self.assertEqual(by_role.get("primary"), 5)
        self.assertEqual(by_role.get("benchmark"), 5)

    def test_required_windows_carry_estimation_hint(self) -> None:
        payload = preview.run_coverage_preview(
            input_csv=_BATCH_CSV,
            price_reader=_empty_reader,
        )
        for w in payload["required_windows"]:
            self.assertIn("estimation_window_start_iso", w)
            self.assertLess(
                w["estimation_window_start_iso"], w["event_date"],
                "estimation window start must precede event date",
            )


# ---------------------------------------------------------------------------
# CSV loader contract
# ---------------------------------------------------------------------------


class TestCsvLoader(unittest.TestCase):
    def test_missing_csv_yields_error(self) -> None:
        payload = preview.run_coverage_preview(
            input_csv="does/not/exist.csv",
            price_reader=_empty_reader,
        )
        self.assertFalse(payload["ok"])
        self.assertTrue(any("not found" in e for e in payload["errors"]))
        # Envelope shape is still intact:
        for key in _TOP_LEVEL_KEYS:
            self.assertIn(key, payload)

    def test_missing_required_column_yields_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            path = tmp / "bad.csv"
            path.write_text(
                "event_date,primary_ticker\n"
                "2024-01-01,SPY\n",
                encoding="utf-8",
            )
            payload = preview.run_coverage_preview(
                input_csv=path,
                price_reader=_empty_reader,
            )
        self.assertFalse(payload["ok"])
        self.assertTrue(
            any("benchmark_ticker" in e for e in payload["errors"]),
        )


# ---------------------------------------------------------------------------
# CLI default-no-disk-writes
# ---------------------------------------------------------------------------


class TestNoDefaultWrites(unittest.TestCase):
    def test_main_without_output_creates_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            csv_path = _write_csv(tmp, [
                {
                    "event_date":       "2024-01-15",
                    "primary_ticker":   "SPY",
                    "benchmark_ticker": "QQQ",
                },
            ])
            before = set(tmp.iterdir())
            buf = StringIO()
            rc = preview.main(
                argv=[
                    "--json",
                    "--input-csv", str(csv_path),
                ],
                out=buf,
            )
            after = set(tmp.iterdir())
        self.assertEqual(before, after, "default run wrote to disk")
        json.loads(buf.getvalue())
        self.assertIn(rc, (0, 1))

    def test_main_with_output_writes_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            csv_path = _write_csv(tmp, [
                {
                    "event_date":       "2024-01-15",
                    "primary_ticker":   "SPY",
                    "benchmark_ticker": "QQQ",
                },
            ])
            out_path = tmp / "report.json"
            buf = StringIO()
            preview.main(
                argv=[
                    "--json",
                    "--input-csv", str(csv_path),
                    "--output",    str(out_path),
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

        tree = ast.parse(inspect.getsource(preview))
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
            f"coverage-preview must not import: {leaked}",
        )


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_envelope_avoids_overclaim_vocabulary(self) -> None:
        payload = preview.run_coverage_preview(
            input_csv=_BATCH_CSV,
            price_reader=_empty_reader,
        )
        joined = json.dumps(payload).lower()
        banned = (
            "proven", "guaranteed", "passes", "passed",
            "fails", "failed", "confirms", "refutes",
            "validated", "production-ready", "demo-ready",
            "alpha generated",
        )
        for token in banned:
            with self.subTest(token=token):
                self.assertNotIn(token, joined)


if __name__ == "__main__":
    unittest.main()
