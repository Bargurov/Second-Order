"""Tests for ``scripts/short_horizon_review_fixture.py`` — a deterministic
test-fixture worksheet generator for short-horizon review tooling.

The fixture script emits a small in-memory worksheet (a handful of
yes / no / pending rows) in the canonical 16-column schema so the
apply and validate smokes can exercise their CSV-consuming paths
without depending on the operator-filled
``artifacts/short_horizon_review_top10.csv``.

Pin the contract:

  * The fixture columns match the canonical worksheet schema
    (``short_horizon_review_worksheet._WORKSHEET_COLUMNS``).
  * ``include_in_short_horizon_validation`` is the canonical gate —
    every row carries it.
  * At least two ``yes`` rows with complete proposed fields, at
    least one ``no`` row with non-blank ``exclude_reason``, at least
    one pending row with a blank gate.
  * The rendered CSV round-trips through the real validator with
    ``ok=True`` and the surfaced bucket counts match the fixture's
    yes / no / pending mix.
  * Default invocation emits a JSON preview to stdout; ``--csv``
    emits the canonical CSV body to stdout; both modes write to a
    file ONLY when ``--output PATH`` is passed (in which case stdout
    stays empty).
  * No DB writes, no provider seam, no LLM, no FastAPI.
  * ``artifacts/short_horizon_review_top10.csv`` is byte-identical
    after any combination of CLI invocations.
  * Conservative wording — surfaced text never uses the banned
    tokens shared with the validator and worksheet (``proof``,
    ``proves``, ``validated``, ``alpha``, ``guaranteed``,
    ``automatic``).
  * Event IDs are synthetic-looking (>= 999000) so they cannot
    collide with archive rows by accident.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import short_horizon_review_fixture as cli  # noqa: E402
from scripts import short_horizon_review_validator as validator  # noqa: E402
from scripts import short_horizon_review_worksheet as worksheet  # noqa: E402


_GATE = "include_in_short_horizon_validation"


# Substring tokens banned in any text the fixture surfaces.  Combined
# from the validator's and worksheet's banned-token lists.
#
# NOTE: ``validated`` is the verb form — the column NAME
# ``include_in_short_horizon_validation`` contains the noun
# ``validation`` which is a distinct substring and is NOT banned.
_BANNED_TOKENS: tuple[str, ...] = (
    "proof",
    "proves",
    "validated",
    "alpha",
    "guaranteed",
    "automatic",
)


def _run_cli(argv):
    buf = StringIO()
    rc = cli.main(argv, out=buf)
    return rc, buf.getvalue()


def _no_banned_token(haystack: str) -> tuple[bool, str | None]:
    lowered = haystack.lower()
    for t in _BANNED_TOKENS:
        if t in lowered:
            return False, t
    return True, None


# ---------------------------------------------------------------------------
# Schema coupling — fixture columns must match the canonical worksheet
# ---------------------------------------------------------------------------


class TestSchemaCoupling(unittest.TestCase):
    def test_fixture_columns_match_canonical_worksheet_columns(self) -> None:
        self.assertEqual(
            tuple(cli._WORKSHEET_COLUMNS),
            tuple(worksheet._WORKSHEET_COLUMNS),
            "fixture columns must match the canonical worksheet schema",
        )

    def test_gate_column_is_in_schema(self) -> None:
        self.assertIn(_GATE, cli._WORKSHEET_COLUMNS)

    def test_substring_assumption_holds(self) -> None:
        # Sanity check on the banned-token substring math:
        # ``validated`` (banned verb) must NOT match inside
        # ``validation`` (unbanned noun used in the column name).
        self.assertNotIn("validated", "validation")


# ---------------------------------------------------------------------------
# Row-level contract on the in-memory fixture
# ---------------------------------------------------------------------------


class TestFixtureRowsContract(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = cli.build_fixture_rows()

    def test_returns_at_least_four_rows(self) -> None:
        self.assertGreaterEqual(len(self.rows), 4)

    def test_every_row_has_all_sixteen_columns(self) -> None:
        for r in self.rows:
            for col in cli._WORKSHEET_COLUMNS:
                self.assertIn(col, r, f"missing column {col!r} in {r}")

    def test_at_least_two_yes_rows(self) -> None:
        yes = [r for r in self.rows
               if str(r.get(_GATE, "")).strip().lower() == "yes"]
        self.assertGreaterEqual(len(yes), 2)

    def test_at_least_one_no_row(self) -> None:
        no = [r for r in self.rows
              if str(r.get(_GATE, "")).strip().lower() == "no"]
        self.assertGreaterEqual(len(no), 1)

    def test_at_least_one_pending_row(self) -> None:
        pending = [r for r in self.rows
                   if str(r.get(_GATE, "")).strip() == ""]
        self.assertGreaterEqual(len(pending), 1)

    def test_yes_rows_have_complete_proposed_fields(self) -> None:
        required = (
            "proposed_primary_ticker",
            "proposed_benchmark_ticker",
            "proposed_mechanism_family",
            "predicted_direction",
        )
        for r in self.rows:
            if str(r.get(_GATE, "")).strip().lower() != "yes":
                continue
            for f in required:
                v = str(r.get(f, "")).strip()
                self.assertTrue(v, f"yes row missing {f!r}: {r}")

    def test_yes_rows_use_valid_direction_vocabulary(self) -> None:
        for r in self.rows:
            if str(r.get(_GATE, "")).strip().lower() != "yes":
                continue
            d = str(r.get("predicted_direction", "")).strip().lower()
            self.assertIn(d, {"up", "down", "neutral"})

    def test_yes_rows_have_iso_event_date(self) -> None:
        # apply_smoke validates event_date format on yes rows; pin
        # the fixture rows so they pass the apply parser as well.
        from datetime import date as _date
        for r in self.rows:
            if str(r.get(_GATE, "")).strip().lower() != "yes":
                continue
            _date.fromisoformat(str(r["event_date"]))  # raises on bad

    def test_yes_rows_have_ticker_shaped_tickers(self) -> None:
        import re
        ticker_re = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
        for r in self.rows:
            if str(r.get(_GATE, "")).strip().lower() != "yes":
                continue
            for f in ("proposed_primary_ticker", "proposed_benchmark_ticker"):
                v = str(r.get(f, "")).strip()
                self.assertTrue(ticker_re.match(v), f"bad ticker in {r}: {f}={v!r}")

    def test_no_row_has_non_blank_exclude_reason(self) -> None:
        for r in self.rows:
            if str(r.get(_GATE, "")).strip().lower() != "no":
                continue
            self.assertTrue(
                str(r.get("exclude_reason", "")).strip(),
                f"no row must carry exclude_reason: {r}",
            )

    def test_pending_rows_have_blank_gate(self) -> None:
        any_pending = False
        for r in self.rows:
            if str(r.get(_GATE, "")).strip() == "":
                any_pending = True
                # Pending rows have no required proposed fields — the
                # worksheet is legitimately mid-review.  Just pin the
                # blank gate.
                self.assertEqual(str(r.get(_GATE, "")).strip(), "")
        self.assertTrue(any_pending)

    def test_event_ids_are_synthetic_looking(self) -> None:
        # Block accidental collision with live archive rows: every
        # fixture event_id must be >= 999000 (or negative).  Live
        # archive IDs land far below this in the current ledger.
        for r in self.rows:
            ev_id = r["event_id"]
            self.assertIsInstance(ev_id, int)
            self.assertNotIsInstance(ev_id, bool)
            self.assertTrue(
                ev_id < 0 or ev_id >= 999000,
                f"event_id {ev_id!r} must look synthetic "
                "(negative or >= 999000)",
            )

    def test_build_fixture_rows_returns_a_fresh_list(self) -> None:
        # Mutating the returned list must not corrupt the module-level
        # fixture.  Sanity-check deep independence on a representative
        # field.
        a = cli.build_fixture_rows()
        b = cli.build_fixture_rows()
        a[0]["headline"] = "MUTATED"
        self.assertNotEqual(b[0]["headline"], "MUTATED")


# ---------------------------------------------------------------------------
# Round-trip through the real validator
# ---------------------------------------------------------------------------


class TestPassesValidator(unittest.TestCase):
    def test_csv_output_validates_ok(self) -> None:
        _, csv_text = _run_cli(["--csv"])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "fixture.csv"
            p.write_text(csv_text, encoding="utf-8")
            report = validator.validate_review_worksheet(str(p))
        self.assertTrue(
            report["ok"], msg=f"validator errors: {report.get('errors')}"
        )

    def test_validator_bucket_counts_match_fixture(self) -> None:
        _, csv_text = _run_cli(["--csv"])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "fixture.csv"
            p.write_text(csv_text, encoding="utf-8")
            report = validator.validate_review_worksheet(str(p))
        rows = cli.build_fixture_rows()
        yes_n = sum(
            1 for r in rows
            if str(r.get(_GATE, "")).strip().lower() == "yes"
        )
        no_n = sum(
            1 for r in rows
            if str(r.get(_GATE, "")).strip().lower() == "no"
        )
        pending_n = sum(
            1 for r in rows
            if str(r.get(_GATE, "")).strip() == ""
        )
        self.assertEqual(report["include_count"], yes_n)
        self.assertEqual(report["exclude_count"], no_n)
        self.assertEqual(report["pending_count"], pending_n)


# ---------------------------------------------------------------------------
# JSON mode
# ---------------------------------------------------------------------------


class TestJsonMode(unittest.TestCase):
    def test_default_invocation_emits_json_to_stdout(self) -> None:
        rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertIn("rows", body)
        self.assertIn("columns", body)

    def test_json_flag_matches_default(self) -> None:
        _, out_default = _run_cli([])
        _, out_json    = _run_cli(["--json"])
        self.assertEqual(
            json.loads(out_default), json.loads(out_json),
        )

    def test_json_envelope_keys(self) -> None:
        _, output = _run_cli([])
        body = json.loads(output)
        for k in (
            "ok", "fixture_count", "include_count",
            "exclude_count", "pending_count", "columns", "rows",
        ):
            self.assertIn(k, body, f"missing key: {k}")
        self.assertIs(body["ok"], True)
        self.assertEqual(body["columns"], list(cli._WORKSHEET_COLUMNS))
        self.assertEqual(body["fixture_count"], len(body["rows"]))


# ---------------------------------------------------------------------------
# CSV mode
# ---------------------------------------------------------------------------


class TestCsvMode(unittest.TestCase):
    def test_csv_header_matches_worksheet_columns(self) -> None:
        _, output = _run_cli(["--csv"])
        first = output.splitlines()[0]
        self.assertEqual(first, ",".join(cli._WORKSHEET_COLUMNS))

    def test_csv_emits_one_data_row_per_fixture_row(self) -> None:
        _, output = _run_cli(["--csv"])
        reader = csv.DictReader(io.StringIO(output))
        parsed = list(reader)
        self.assertEqual(len(parsed), len(cli.build_fixture_rows()))
        self.assertEqual(reader.fieldnames, list(cli._WORKSHEET_COLUMNS))

    def test_csv_uses_lf_line_endings(self) -> None:
        _, output = _run_cli(["--csv"])
        self.assertNotIn("\r\n", output)


# ---------------------------------------------------------------------------
# --output flag — file written only when given, stdout suppressed
# ---------------------------------------------------------------------------


class TestOutputFlag(unittest.TestCase):
    def test_output_writes_csv_file_and_suppresses_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.csv"
            rc, stdout = _run_cli(["--csv", "--output", str(target)])
            self.assertEqual(rc, 0)
            self.assertEqual(stdout, "")
            self.assertTrue(target.exists())
            text = target.read_text(encoding="utf-8")
            self.assertTrue(
                text.startswith(",".join(cli._WORKSHEET_COLUMNS)),
                f"written CSV must start with the canonical header; "
                f"got: {text[:200]!r}",
            )

    def test_output_writes_json_file_in_default_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.json"
            rc, stdout = _run_cli(["--json", "--output", str(target)])
            self.assertEqual(rc, 0)
            self.assertEqual(stdout, "")
            self.assertTrue(target.exists())
            body = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn("rows", body)
            self.assertEqual(body["columns"], list(cli._WORKSHEET_COLUMNS))


# ---------------------------------------------------------------------------
# Read-only against the real worksheet artifact
# ---------------------------------------------------------------------------


class TestDoesNotMutateRealWorksheet(unittest.TestCase):
    def test_real_worksheet_csv_is_byte_identical_after_runs(self) -> None:
        real = (
            Path(__file__).resolve().parents[1]
            / "artifacts" / "short_horizon_review_top10.csv"
        )
        if not real.exists():
            self.skipTest("real worksheet CSV not present in this checkout")
        before = real.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            _run_cli([])
            _run_cli(["--json"])
            _run_cli(["--csv"])
            _run_cli(["--csv", "--output", str(Path(tmp) / "x.csv")])
            _run_cli(["--json", "--output", str(Path(tmp) / "x.json")])
        after = real.read_bytes()
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Forbidden seams — no DB writes, no provider, no LLM, no FastAPI
# ---------------------------------------------------------------------------


_FORBIDDEN_SEAMS: tuple[tuple[str, str], ...] = (
    ("db",              "save_event"),
    ("db",              "update_review"),
    ("db",              "append_revisit_snapshot"),
    ("db",              "delete_event"),
    ("db",              "save_movers_cache"),
    ("market_check",    "market_check"),
    ("market_check",    "_fetch"),
    ("market_data",     "get_provider"),
    ("price_cache",     "fetch_daily_cached"),
    ("analyze_event",   "analyze_event"),
    ("analyze_event",   "_call_llm_provider"),
)


def _patch_raisers(stack, seams, *, label):
    for module_name, attr in seams:
        try:
            mod = __import__(module_name)
        except Exception:
            continue
        if not hasattr(mod, attr):
            continue
        stack.enter_context(patch.object(
            mod, attr,
            side_effect=AssertionError(
                f"short_horizon_review_fixture must not invoke "
                f"{module_name}.{attr} ({label})",
            ),
        ))


class TestNoForbiddenSeams(unittest.TestCase):
    def test_no_db_or_provider_seam_invoked(self) -> None:
        with ExitStack() as stack:
            _patch_raisers(stack, _FORBIDDEN_SEAMS, label="db/provider/LLM")
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "fixture must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            rc_json, _ = _run_cli(["--json"])
            rc_csv,  _ = _run_cli(["--csv"])
        self.assertEqual(rc_json, 0)
        self.assertEqual(rc_csv, 0)


# ---------------------------------------------------------------------------
# Conservative wording — banned substrings absent from surfaced text
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_token_in_json_output(self) -> None:
        _, output = _run_cli(["--json"])
        ok, token = _no_banned_token(output)
        self.assertTrue(ok, f"banned token {token!r} in JSON output")

    def test_no_banned_token_in_csv_output(self) -> None:
        _, output = _run_cli(["--csv"])
        ok, token = _no_banned_token(output)
        self.assertTrue(ok, f"banned token {token!r} in CSV output")

    def test_no_banned_token_in_module_docstring(self) -> None:
        doc = (cli.__doc__ or "")
        ok, token = _no_banned_token(doc)
        self.assertTrue(ok, f"banned token {token!r} in module docstring")

    def test_no_banned_token_in_help_text(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                cli.main(["--help"], out=StringIO())
        help_text = buf.getvalue()
        ok, token = _no_banned_token(help_text)
        self.assertTrue(ok, f"banned token {token!r} in --help text")


# ---------------------------------------------------------------------------
# Argparse plumbing
# ---------------------------------------------------------------------------


class TestArgparse(unittest.TestCase):
    def test_help_exits_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--help"], out=StringIO())
        self.assertEqual(ctx.exception.code, 0)

    def test_json_and_csv_are_mutually_exclusive(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.main(["--json", "--csv"], out=StringIO())


if __name__ == "__main__":
    unittest.main()
