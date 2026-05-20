"""Tests for ``scripts/robustness_cache_backfill_write_smoke.py``.

Pin the contract:

* Default mode is dry-run.  Dry-run NEVER calls
  ``_fetch_into_cache`` (the write-mode seam over
  ``price_cache.fetch_daily_cached``).
* Write mode requires ALL of ``--write --confirm --backup-path``
  together with a backup file that exists and differs from
  ``--db-path``.  Each missing / invalid flag fails closed before
  any provider call or cache write.
* Multiple ``--ticker-window TICKER,YYYY-MM-DD,YYYY-MM-DD`` args
  parse into the expected list of ``(ticker, start, end)`` triples.
* Malformed ``--ticker-window`` values reject with a clean argparse
  error rather than a stack trace.
* The pre / post / rows_added reporting in write mode is driven by
  the patchable COUNT(*) seams; the test wires synthetic counts and
  asserts the per-window dict carries them verbatim.
* Only the ``price_cache`` table is touched in write mode.  The
  test asserts the script's seams do not import or reference any
  other table by name, and that the events row count check fires
  with a drift error when the patched events count changes.
* The output dict carries EXACTLY the documented top-level / per-
  window key sets, in both modes.
* Conservative wording — banned tokens absent from the module
  source so any prose the smoke emits stays descriptive.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import robustness_cache_backfill_write_smoke as cli  # noqa: E402


_EXPECTED_TOP_LEVEL_KEYS: frozenset[str] = frozenset({
    "ok",
    "mode",
    "db_path",
    "backup_path",
    "ticker_window_count",
    "ticker_windows",
    "events_row_count_before",
    "events_row_count_after",
    "events_table_unchanged",
    "warnings",
    "errors",
    "recommended_next_action",
})

_EXPECTED_PER_WINDOW_KEYS: frozenset[str] = frozenset({
    "ticker",
    "start_date",
    "end_date",
    "auto_adjust",
    "pre_cache_row_count",
    "provider_preview",
    "post_cache_row_count",
    "rows_added",
    "error",
})


_ITA = ("ITA", "2022-09-01", "2023-01-31")
_AA  = ("AA",  "2017-09-18", "2018-06-05")


def _stub_preview_ok(ticker: str, start_date: str, end_date: str, auto_adjust: int) -> dict:
    return {
        "row_count":  100,
        "first_date": start_date,
        "last_date":  end_date,
        "error":      None,
    }


def _stub_preview_error(ticker: str, start_date: str, end_date: str, auto_adjust: int) -> dict:
    return {
        "row_count":  None,
        "first_date": None,
        "last_date":  None,
        "error":      "provider call failed: simulated",
    }


def _stub_fetch_noop(ticker: str, start_date: str, end_date: str, auto_adjust: int):
    return None


def _stub_fetch_error(ticker: str, start_date: str, end_date: str, auto_adjust: int):
    return "simulated fetch failure"


class DryRunModeTests(unittest.TestCase):

    def test_dry_run_is_default_and_skips_fetch_seam(self) -> None:
        with mock.patch.object(cli, "_check_provider_available", return_value=True), \
             mock.patch.object(cli, "_provider_preview", side_effect=_stub_preview_ok) as preview_seam, \
             mock.patch.object(cli, "_fetch_into_cache") as fetch_seam, \
             mock.patch.object(cli, "_count_price_cache_rows", return_value=0), \
             mock.patch.object(cli, "_count_events_rows", return_value=42):
            result = cli.run_smoke(
                ticker_windows=[_ITA, _AA],
                auto_adjust=0,
                write=False,
                confirm=False,
                backup_path=None,
                db_path="events.db",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "dry-run")
        self.assertIsNone(result["backup_path"])
        self.assertEqual(result["ticker_window_count"], 2)
        self.assertIsNone(result["events_row_count_before"])
        self.assertIsNone(result["events_row_count_after"])
        self.assertIsNone(result["events_table_unchanged"])
        fetch_seam.assert_not_called()
        # Preview seam fires once per window in dry-run.
        self.assertEqual(preview_seam.call_count, 2)

    def test_dry_run_per_window_payload_has_preview_and_no_post_fields(self) -> None:
        with mock.patch.object(cli, "_check_provider_available", return_value=True), \
             mock.patch.object(cli, "_provider_preview", side_effect=_stub_preview_ok), \
             mock.patch.object(cli, "_fetch_into_cache") as fetch_seam, \
             mock.patch.object(cli, "_count_price_cache_rows", return_value=3), \
             mock.patch.object(cli, "_count_events_rows", return_value=42):
            result = cli.run_smoke(
                ticker_windows=[_ITA],
                auto_adjust=0,
                write=False,
                confirm=False,
                backup_path=None,
                db_path="events.db",
            )
        fetch_seam.assert_not_called()
        win = result["ticker_windows"][0]
        self.assertEqual(set(win.keys()), _EXPECTED_PER_WINDOW_KEYS)
        self.assertEqual(win["ticker"], "ITA")
        self.assertEqual(win["start_date"], "2022-09-01")
        self.assertEqual(win["end_date"],   "2023-01-31")
        self.assertEqual(win["auto_adjust"], 0)
        self.assertEqual(win["pre_cache_row_count"], 3)
        self.assertEqual(win["provider_preview"]["row_count"], 100)
        self.assertIsNone(win["post_cache_row_count"])
        self.assertIsNone(win["rows_added"])
        self.assertIsNone(win["error"])

    def test_dry_run_with_preview_error_flips_ok_false(self) -> None:
        with mock.patch.object(cli, "_check_provider_available", return_value=True), \
             mock.patch.object(cli, "_provider_preview", side_effect=_stub_preview_error), \
             mock.patch.object(cli, "_fetch_into_cache") as fetch_seam, \
             mock.patch.object(cli, "_count_price_cache_rows", return_value=0), \
             mock.patch.object(cli, "_count_events_rows", return_value=42):
            result = cli.run_smoke(
                ticker_windows=[_ITA],
                auto_adjust=0,
                write=False,
                confirm=False,
                backup_path=None,
                db_path="events.db",
            )
        fetch_seam.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["ticker_windows"][0]["provider_preview"]["error"],
                         "provider call failed: simulated")
        self.assertIn("could not be previewed",
                      result["recommended_next_action"])

    def test_dry_run_emits_warning_when_provider_unavailable(self) -> None:
        with mock.patch.object(cli, "_check_provider_available", return_value=False), \
             mock.patch.object(cli, "_provider_preview", side_effect=_stub_preview_error), \
             mock.patch.object(cli, "_fetch_into_cache"), \
             mock.patch.object(cli, "_count_price_cache_rows", return_value=0), \
             mock.patch.object(cli, "_count_events_rows", return_value=42):
            result = cli.run_smoke(
                ticker_windows=[_ITA],
                auto_adjust=0,
                write=False,
                confirm=False,
                backup_path=None,
                db_path="events.db",
            )
        self.assertTrue(any("yfinance not importable" in w for w in result["warnings"]))


class WriteModeFlagGuardTests(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="rcbws_flag_")
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_backup_file(self) -> str:
        path = os.path.join(self._tmp, f"bk_{uuid.uuid4().hex}.db.bak")
        Path(path).write_bytes(b"placeholder")
        return path

    def test_write_without_confirm_fails(self) -> None:
        bk = self._make_backup_file()
        with mock.patch.object(cli, "_fetch_into_cache") as fetch_seam:
            result = cli.run_smoke(
                ticker_windows=[_ITA],
                auto_adjust=0,
                write=True,
                confirm=False,
                backup_path=bk,
                db_path=os.path.join(self._tmp, "live.db"),
            )
        fetch_seam.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertTrue(any("requires --confirm" in e for e in result["errors"]))

    def test_write_without_backup_fails(self) -> None:
        with mock.patch.object(cli, "_fetch_into_cache") as fetch_seam:
            result = cli.run_smoke(
                ticker_windows=[_ITA],
                auto_adjust=0,
                write=True,
                confirm=True,
                backup_path=None,
                db_path=os.path.join(self._tmp, "live.db"),
            )
        fetch_seam.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertTrue(any("requires --backup-path" in e for e in result["errors"]))

    def test_write_with_nonexistent_backup_fails(self) -> None:
        missing = os.path.join(self._tmp, "no_such_backup.db.bak")
        with mock.patch.object(cli, "_fetch_into_cache") as fetch_seam:
            result = cli.run_smoke(
                ticker_windows=[_ITA],
                auto_adjust=0,
                write=True,
                confirm=True,
                backup_path=missing,
                db_path=os.path.join(self._tmp, "live.db"),
            )
        fetch_seam.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertTrue(any("does not exist on disk" in e for e in result["errors"]))

    def test_write_rejects_backup_equal_to_db_path(self) -> None:
        bk = self._make_backup_file()
        with mock.patch.object(cli, "_fetch_into_cache") as fetch_seam:
            result = cli.run_smoke(
                ticker_windows=[_ITA],
                auto_adjust=0,
                write=True,
                confirm=True,
                backup_path=bk,
                db_path=bk,
            )
        fetch_seam.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertTrue(any("must differ from db-path" in e for e in result["errors"]))

    def test_no_ticker_windows_rejects_in_both_modes(self) -> None:
        result = cli.run_smoke(
            ticker_windows=[],
            auto_adjust=0,
            write=False,
            confirm=False,
            backup_path=None,
            db_path=os.path.join(self._tmp, "live.db"),
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("no --ticker-window" in e for e in result["errors"]))


class WriteModeFetchPathTests(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="rcbws_write_")
        self.addCleanup(self._cleanup)
        self.backup_path = os.path.join(self._tmp, "bk.db.bak")
        Path(self.backup_path).write_bytes(b"placeholder")
        self.db_path = os.path.join(self._tmp, "live.db")

    def _cleanup(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_write_calls_fetch_once_per_window_and_reports_rows_added(self) -> None:
        # Pre count 0 for both, post count 100 for ITA and 175 for AA.
        post_counts = {
            ("ITA", "2022-09-01", "2023-01-31"): [0, 100],
            ("AA",  "2017-09-18", "2018-06-05"): [0, 175],
        }
        def fake_count(*, db_path, ticker, start_date, end_date, auto_adjust):
            key = (ticker, start_date, end_date)
            return post_counts[key].pop(0)

        with mock.patch.object(cli, "_count_price_cache_rows", side_effect=fake_count), \
             mock.patch.object(cli, "_count_events_rows", return_value=200), \
             mock.patch.object(cli, "_fetch_into_cache", side_effect=_stub_fetch_noop) as fetch_seam, \
             mock.patch.object(cli, "_provider_preview") as preview_seam:
            result = cli.run_smoke(
                ticker_windows=[_ITA, _AA],
                auto_adjust=0,
                write=True,
                confirm=True,
                backup_path=self.backup_path,
                db_path=self.db_path,
            )
        # fetch_into_cache fires exactly once per window in write mode.
        self.assertEqual(fetch_seam.call_count, 2)
        # provider_preview is NEVER called in write mode.
        preview_seam.assert_not_called()

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "write")
        self.assertEqual(result["backup_path"], self.backup_path)
        self.assertEqual(result["events_row_count_before"], 200)
        self.assertEqual(result["events_row_count_after"],  200)
        self.assertTrue(result["events_table_unchanged"])

        ita = next(w for w in result["ticker_windows"] if w["ticker"] == "ITA")
        aa  = next(w for w in result["ticker_windows"] if w["ticker"] == "AA")
        self.assertEqual(ita["pre_cache_row_count"], 0)
        self.assertEqual(ita["post_cache_row_count"], 100)
        self.assertEqual(ita["rows_added"], 100)
        self.assertIsNone(ita["provider_preview"])
        self.assertEqual(aa["rows_added"], 175)

    def test_write_surfaces_events_table_drift_as_error(self) -> None:
        counts = iter([0, 100])  # pre then post for the one window

        def fake_count(*, db_path, ticker, start_date, end_date, auto_adjust):
            return next(counts)

        events_counts = iter([200, 201])

        def fake_events_count(db_path):
            return next(events_counts)

        with mock.patch.object(cli, "_count_price_cache_rows", side_effect=fake_count), \
             mock.patch.object(cli, "_count_events_rows", side_effect=fake_events_count), \
             mock.patch.object(cli, "_fetch_into_cache", side_effect=_stub_fetch_noop):
            result = cli.run_smoke(
                ticker_windows=[_ITA],
                auto_adjust=0,
                write=True,
                confirm=True,
                backup_path=self.backup_path,
                db_path=self.db_path,
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["events_table_unchanged"])
        self.assertEqual(result["events_row_count_before"], 200)
        self.assertEqual(result["events_row_count_after"],  201)
        self.assertTrue(any("events table row count drifted" in e for e in result["errors"]))

    def test_write_continues_through_one_window_failure(self) -> None:
        counts = iter([0, 0, 50])  # ITA pre (then no post due to error), AA pre, AA post

        def fake_count(*, db_path, ticker, start_date, end_date, auto_adjust):
            return next(counts)

        def fake_fetch(ticker, start_date, end_date, auto_adjust):
            if ticker == "ITA":
                return "simulated network error"
            return None

        with mock.patch.object(cli, "_count_price_cache_rows", side_effect=fake_count), \
             mock.patch.object(cli, "_count_events_rows", return_value=200), \
             mock.patch.object(cli, "_fetch_into_cache", side_effect=fake_fetch):
            result = cli.run_smoke(
                ticker_windows=[_ITA, _AA],
                auto_adjust=0,
                write=True,
                confirm=True,
                backup_path=self.backup_path,
                db_path=self.db_path,
            )
        self.assertFalse(result["ok"])
        ita = next(w for w in result["ticker_windows"] if w["ticker"] == "ITA")
        aa  = next(w for w in result["ticker_windows"] if w["ticker"] == "AA")
        self.assertEqual(ita["error"], "simulated network error")
        self.assertIsNone(ita["post_cache_row_count"])
        self.assertIsNone(ita["rows_added"])
        self.assertIsNone(aa["error"])
        self.assertEqual(aa["rows_added"], 50)


class TickerWindowParsingTests(unittest.TestCase):

    def test_parses_valid_triple(self) -> None:
        out = cli._parse_ticker_window("ITA,2022-09-01,2023-01-31")
        self.assertEqual(out, ("ITA", "2022-09-01", "2023-01-31"))

    def test_rejects_two_part_value(self) -> None:
        with self.assertRaises(Exception):
            cli._parse_ticker_window("ITA,2022-09-01")

    def test_rejects_non_iso_date(self) -> None:
        with self.assertRaises(Exception):
            cli._parse_ticker_window("ITA,2022-09-01,not-a-date")

    def test_rejects_end_before_start(self) -> None:
        with self.assertRaises(Exception):
            cli._parse_ticker_window("ITA,2023-01-31,2022-09-01")

    def test_rejects_blank_ticker(self) -> None:
        with self.assertRaises(Exception):
            cli._parse_ticker_window(",2022-09-01,2023-01-31")

    def test_cli_parser_accepts_multiple_ticker_window_args(self) -> None:
        parser = cli._build_parser()
        args = parser.parse_args([
            "--ticker-window", "ITA,2022-09-01,2023-01-31",
            "--ticker-window", "AA,2017-09-18,2018-06-05",
        ])
        self.assertEqual(args.ticker_window, [
            ("ITA", "2022-09-01", "2023-01-31"),
            ("AA",  "2017-09-18", "2018-06-05"),
        ])
        # Defaults — dry-run is default, no live action.
        self.assertFalse(args.write)
        self.assertFalse(args.confirm)
        self.assertIsNone(args.backup_path)
        self.assertEqual(args.auto_adjust, 0)


class EnvelopeShapeTests(unittest.TestCase):

    def test_top_level_keys_exact_in_both_modes(self) -> None:
        with mock.patch.object(cli, "_check_provider_available", return_value=True), \
             mock.patch.object(cli, "_provider_preview", side_effect=_stub_preview_ok), \
             mock.patch.object(cli, "_count_price_cache_rows", return_value=0), \
             mock.patch.object(cli, "_count_events_rows", return_value=42), \
             mock.patch.object(cli, "_fetch_into_cache", side_effect=_stub_fetch_noop):
            dry = cli.run_smoke(
                ticker_windows=[_ITA],
                auto_adjust=0,
                write=False,
                confirm=False,
                backup_path=None,
                db_path="events.db",
            )
        self.assertEqual(set(dry.keys()), _EXPECTED_TOP_LEVEL_KEYS)
        self.assertEqual(set(dry["ticker_windows"][0].keys()), _EXPECTED_PER_WINDOW_KEYS)

        tmp = tempfile.mkdtemp(prefix="rcbws_env_")
        try:
            bk = os.path.join(tmp, "bk.db.bak")
            Path(bk).write_bytes(b"x")
            with mock.patch.object(cli, "_count_price_cache_rows", return_value=0), \
                 mock.patch.object(cli, "_count_events_rows", return_value=42), \
                 mock.patch.object(cli, "_fetch_into_cache", side_effect=_stub_fetch_noop):
                wet = cli.run_smoke(
                    ticker_windows=[_ITA],
                    auto_adjust=0,
                    write=True,
                    confirm=True,
                    backup_path=bk,
                    db_path=os.path.join(tmp, "live.db"),
                )
            self.assertEqual(set(wet.keys()), _EXPECTED_TOP_LEVEL_KEYS)
            self.assertEqual(set(wet["ticker_windows"][0].keys()), _EXPECTED_PER_WINDOW_KEYS)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class CLIIntegrationTests(unittest.TestCase):

    def test_main_dry_run_returns_zero_when_seam_succeeds(self) -> None:
        argv = [
            "--ticker-window", "ITA,2022-09-01,2023-01-31",
            "--ticker-window", "AA,2017-09-18,2018-06-05",
            "--json",
        ]
        with mock.patch.object(cli, "_check_provider_available", return_value=True), \
             mock.patch.object(cli, "_provider_preview", side_effect=_stub_preview_ok), \
             mock.patch.object(cli, "_count_price_cache_rows", return_value=0), \
             mock.patch.object(cli, "_count_events_rows", return_value=42), \
             mock.patch.object(cli, "_fetch_into_cache") as fetch_seam:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(argv)
        self.assertEqual(rc, 0)
        fetch_seam.assert_not_called()
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["mode"], "dry-run")
        self.assertEqual(payload["ticker_window_count"], 2)
        self.assertTrue(payload["ok"])

    def test_main_write_without_confirm_returns_nonzero(self) -> None:
        argv = [
            "--write",
            "--backup-path", "does-not-matter.db.bak",
            "--ticker-window", "ITA,2022-09-01,2023-01-31",
            "--json",
        ]
        with mock.patch.object(cli, "_fetch_into_cache") as fetch_seam:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(argv)
        self.assertEqual(rc, 1)
        fetch_seam.assert_not_called()
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertTrue(any("requires --confirm" in e for e in payload["errors"]))


class ConservativeWordingTests(unittest.TestCase):

    def _emitted_strings(self) -> str:
        """All text the smoke would print: the recommended_next_action
        constants plus the JSON output of one dry-run and one write
        invocation under patched seams.  This is the surface the
        operator and downstream tooling actually see."""
        recommended_text = "\n".join(
            getattr(cli, name)
            for name in dir(cli)
            if name.startswith("_RECOMMENDED_") and isinstance(getattr(cli, name), str)
        )
        with mock.patch.object(cli, "_check_provider_available", return_value=True), \
             mock.patch.object(cli, "_provider_preview", side_effect=_stub_preview_ok), \
             mock.patch.object(cli, "_count_price_cache_rows", return_value=3), \
             mock.patch.object(cli, "_count_events_rows", return_value=42), \
             mock.patch.object(cli, "_fetch_into_cache", side_effect=_stub_fetch_noop):
            dry = cli.run_smoke(
                ticker_windows=[_ITA, _AA],
                auto_adjust=0,
                write=False,
                confirm=False,
                backup_path=None,
                db_path="events.db",
            )
            tmp = tempfile.mkdtemp(prefix="rcbws_conserv_")
            try:
                bk = os.path.join(tmp, "bk.db.bak")
                Path(bk).write_bytes(b"x")
                wet = cli.run_smoke(
                    ticker_windows=[_ITA],
                    auto_adjust=0,
                    write=True,
                    confirm=True,
                    backup_path=bk,
                    db_path=os.path.join(tmp, "live.db"),
                )
            finally:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
        # Also exercise the flag-rejection path so its recommended
        # string and error text are scanned.
        reject = cli.run_smoke(
            ticker_windows=[_ITA],
            auto_adjust=0,
            write=True,
            confirm=False,
            backup_path=None,
            db_path="events.db",
        )
        return "\n".join([
            recommended_text,
            json.dumps(dry),
            json.dumps(wet),
            json.dumps(reject),
        ])

    def test_banned_tokens_absent_from_emitted_output(self) -> None:
        emitted = self._emitted_strings().lower()
        for token in cli._BANNED_TOKENS:
            self.assertNotIn(token.lower(), emitted,
                             f"banned token {token!r} found in emitted output")


class OnlyPriceCacheTableTouchedTests(unittest.TestCase):
    """Pin the safety claim that nothing but price_cache is written.

    The script must NOT reference any of the other tables that live in
    events.db (events, news_cache, movers_cache, news_clusters,
    news_headline_assignments, saved_studies, macro_releases,
    macro_release_facts, headline_registry, curated_candidates) in any
    write context.  The only allowed read is events (for the integrity
    COUNT(*) check).
    """

    _FORBIDDEN_TABLES: tuple[str, ...] = (
        "news_cache",
        "movers_cache",
        "news_clusters",
        "news_headline_assignments",
        "saved_studies",
        "macro_releases",
        "macro_release_facts",
        "headline_registry",
        "curated_candidates",
    )

    @staticmethod
    def _strip_docstrings(source: str) -> str:
        """Return ``source`` with every triple-quoted string literal
        (module + function + class docstrings) removed.  Uses Python's
        own tokenizer so the result is exactly the executable code."""
        import io as _io
        import tokenize as _tok
        out_parts: list[str] = []
        toks = _tok.tokenize(_io.BytesIO(source.encode("utf-8")).readline)
        for tok in toks:
            if tok.type == _tok.STRING and (
                tok.string.startswith('"""')
                or tok.string.startswith("'''")
                or tok.string.startswith('r"""')
                or tok.string.startswith("r'''")
            ):
                # Replace docstrings with a placeholder so line
                # numbers / structure stay coherent if anything ever
                # inspects them.
                out_parts.append('"<DOCSTRING_STRIPPED>"')
            else:
                out_parts.append(tok.string)
        return " ".join(out_parts)

    def test_no_forbidden_table_named_in_executable_code(self) -> None:
        source = Path(cli.__file__).read_text(encoding="utf-8")
        code_only = self._strip_docstrings(source)
        for tbl in self._FORBIDDEN_TABLES:
            self.assertNotIn(tbl, code_only,
                             f"forbidden table {tbl!r} referenced in executable code")

    def test_no_INSERT_UPDATE_DELETE_in_executable_code(self) -> None:
        # The write seam only delegates to price_cache.fetch_daily_cached.
        # No SQL write statement should appear anywhere in the
        # executable code — the cache write happens inside the
        # price_cache module, which is intentionally separate.  Match
        # full SQL statement signatures, not the bare keyword, so a
        # benign Python call like ``sys.path.insert(...)`` does not
        # trip the check.
        import re as _re
        source = Path(cli.__file__).read_text(encoding="utf-8")
        code_only = self._strip_docstrings(source)
        sql_write_patterns = (
            r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\b",   # INSERT INTO / INSERT OR IGNORE INTO
            r"\bUPDATE\s+[\w\"`]+\s+SET\b",          # UPDATE <tbl> SET
            r"\bDELETE\s+FROM\b",                    # DELETE FROM
            r"\bREPLACE\s+INTO\b",                   # REPLACE INTO
        )
        for pattern in sql_write_patterns:
            self.assertIsNone(
                _re.search(pattern, code_only, flags=_re.IGNORECASE),
                f"forbidden SQL write statement matching {pattern!r} "
                f"found in executable code",
            )


if __name__ == "__main__":
    unittest.main()
