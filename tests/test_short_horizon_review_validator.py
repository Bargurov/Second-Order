"""Tests for ``scripts/short_horizon_review_validator.py``.

Pin the contract:

* ``validate_review_worksheet(worksheet_path)`` returns a dict with
  EXACTLY these keys::

    ok, worksheet_path, total_rows, include_count, exclude_count,
    pending_count, errors, warnings, accepted_rows, excluded_rows,
    pending_rows

* ``include_in_short_horizon_validation`` is the operator gate.
  Accepted values (case- and whitespace-insensitive): "yes", "no", "".
  Any other value is a per-row error.
* ``yes`` rows must carry non-blank values for:
    proposed_primary_ticker, proposed_benchmark_ticker,
    proposed_mechanism_family, predicted_direction.
* ``no`` rows must carry a non-blank ``exclude_reason``.
* Blank rows are pending_review and never flip ``ok`` to False on
  their own.
* ``predicted_direction`` must be one of ``{"up", "down", "neutral"}``.
  Note: this contract uses ``neutral`` — NOT ``flat``.
* Tickers must look like symbol/ETF strings — uppercase letters /
  digits with optional ``.`` or ``-`` separators, length 1-10, no
  prose, no spaces.
* The CLI ``main`` returns 0 on success, non-zero when any worksheet
  row fails validation OR the file is structurally bad.
* Conservative wording — error and warning strings never use the
  banned tokens (``validated``, ``proves``, ``proof``, ``alpha``,
  ``automatic``).  The validator does NOT claim any candidate is
  validated.
* Read-only by construction — the worksheet on disk is never
  rewritten, and the surfaced row dicts carry the operator's RAW
  values (no normalisation, no uppercasing, no whitespace trim).
"""
from __future__ import annotations

import csv as csv_module
import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import short_horizon_review_validator as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "worksheet_path",
    "total_rows",
    "include_count",
    "exclude_count",
    "pending_count",
    "errors",
    "warnings",
    "accepted_rows",
    "excluded_rows",
    "pending_rows",
)


_BANNED_WORDS = (
    "validated",
    "proves",
    "proof",
    "alpha",
    "automatic",
)


_HEADER = (
    "event_id",
    "headline",
    "include_in_short_horizon_validation",
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "exclude_reason",
)


def _good_yes(**overrides: Any) -> dict[str, str]:
    base = {
        "event_id":                                "30",
        "headline":                                "Bank dividend lift",
        "include_in_short_horizon_validation":     "yes",
        "proposed_primary_ticker":                 "MS",
        "proposed_benchmark_ticker":               "SPY",
        "proposed_mechanism_family":               "bank_regulatory_capital_relief",
        "predicted_direction":                     "up",
        "exclude_reason":                          "",
    }
    base.update({k: str(v) for k, v in overrides.items()})
    return base


def _good_no(**overrides: Any) -> dict[str, str]:
    base = {
        "event_id":                                "42",
        "headline":                                "Off-topic feature story",
        "include_in_short_horizon_validation":     "no",
        "proposed_primary_ticker":                 "",
        "proposed_benchmark_ticker":               "",
        "proposed_mechanism_family":               "",
        "predicted_direction":                     "",
        "exclude_reason":                          "off-topic; no mechanism",
    }
    base.update({k: str(v) for k, v in overrides.items()})
    return base


def _blank(**overrides: Any) -> dict[str, str]:
    base = {
        "event_id":                                "44",
        "headline":                                "Awaiting review",
        "include_in_short_horizon_validation":     "",
        "proposed_primary_ticker":                 "",
        "proposed_benchmark_ticker":               "",
        "proposed_mechanism_family":               "",
        "predicted_direction":                     "",
        "exclude_reason":                          "",
    }
    base.update({k: str(v) for k, v in overrides.items()})
    return base


def _write_csv(
    path: Path,
    rows: Iterable[dict[str, str]],
    header: Iterable[str] = _HEADER,
) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv_module.DictWriter(
            fh, fieldnames=list(header), extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class _TempCSV:
    """Context manager that materialises a temp worksheet path."""

    def __init__(
        self,
        rows: Iterable[dict[str, str]] | None = None,
        header: Iterable[str] = _HEADER,
        raw_text: str | None = None,
    ) -> None:
        self._rows = list(rows) if rows is not None else None
        self._header = list(header)
        self._raw_text = raw_text
        self._tmpdir: tempfile.TemporaryDirectory | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "review.csv"
        if self._raw_text is not None:
            self.path.write_text(self._raw_text, encoding="utf-8")
        else:
            _write_csv(self.path, self._rows or [], self._header)
        return self.path

    def __exit__(self, *exc: Any) -> None:
        if self._tmpdir is not None:
            self._tmpdir.cleanup()


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_keys_present_for_minimal_valid_worksheet(self) -> None:
        with _TempCSV([_good_yes()]) as p:
            result = cli.validate_review_worksheet(str(p))
        for k in _REQUIRED_KEYS:
            self.assertIn(k, result, f"missing output key: {k}")

    def test_no_extra_keys(self) -> None:
        with _TempCSV([_good_yes()]) as p:
            result = cli.validate_review_worksheet(str(p))
        extra = set(result) - set(_REQUIRED_KEYS)
        self.assertEqual(extra, set(), f"unexpected keys: {extra}")

    def test_worksheet_path_echoed(self) -> None:
        with _TempCSV([_good_yes()]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertEqual(result["worksheet_path"], str(p))


# ---------------------------------------------------------------------------
# Structural errors
# ---------------------------------------------------------------------------


class TestStructuralErrors(unittest.TestCase):
    def test_missing_worksheet_path_is_error(self) -> None:
        result = cli.validate_review_worksheet(
            "/this/path/does/not/exist.csv",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["total_rows"], 0)
        self.assertEqual(result["include_count"], 0)
        self.assertEqual(result["exclude_count"], 0)
        self.assertEqual(result["pending_count"], 0)
        self.assertTrue(result["errors"])

    def test_none_worksheet_path_is_error(self) -> None:
        result = cli.validate_review_worksheet(None)
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])

    def test_missing_required_column_is_structural_error(self) -> None:
        # Drop the gate column entirely.
        bad_header = [c for c in _HEADER
                      if c != "include_in_short_horizon_validation"]
        with _TempCSV([_good_yes()], header=bad_header) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])
        self.assertTrue(any(
            "include_in_short_horizon_validation" in e
            for e in result["errors"]
        ))

    def test_missing_proposed_columns_is_structural_error(self) -> None:
        bad_header = [
            "event_id", "headline",
            "include_in_short_horizon_validation",
            "exclude_reason",
            # missing proposed_primary_ticker, _benchmark_ticker,
            # _mechanism_family, predicted_direction
        ]
        with _TempCSV([_blank()], header=bad_header) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])

    def test_completely_empty_worksheet_is_error(self) -> None:
        # No header, no rows.
        with _TempCSV(raw_text="") as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])
        self.assertEqual(result["total_rows"], 0)

    def test_header_only_no_rows_is_not_ok(self) -> None:
        with _TempCSV([]) as p:
            result = cli.validate_review_worksheet(str(p))
        # No rows means nothing to validate — treat as a structural
        # problem so the operator notices.
        self.assertFalse(result["ok"])
        self.assertEqual(result["total_rows"], 0)


# ---------------------------------------------------------------------------
# Gate-value semantics
# ---------------------------------------------------------------------------


class TestGateValue(unittest.TestCase):
    def test_yes_lowercase_dispatches_to_accepted(self) -> None:
        with _TempCSV([_good_yes()]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertTrue(result["ok"], f"errors: {result['errors']}")
        self.assertEqual(result["include_count"], 1)
        self.assertEqual(result["exclude_count"], 0)
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(len(result["accepted_rows"]), 1)

    def test_yes_uppercase_dispatches_to_accepted(self) -> None:
        with _TempCSV([_good_yes(
            include_in_short_horizon_validation="YES",
        )]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertTrue(result["ok"], f"errors: {result['errors']}")
        self.assertEqual(result["include_count"], 1)

    def test_yes_with_whitespace_dispatches_to_accepted(self) -> None:
        with _TempCSV([_good_yes(
            include_in_short_horizon_validation="  yes  ",
        )]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertTrue(result["ok"], f"errors: {result['errors']}")
        self.assertEqual(result["include_count"], 1)

    def test_no_dispatches_to_excluded(self) -> None:
        with _TempCSV([_good_no()]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertTrue(result["ok"], f"errors: {result['errors']}")
        self.assertEqual(result["exclude_count"], 1)
        self.assertEqual(result["include_count"], 0)
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(len(result["excluded_rows"]), 1)

    def test_no_mixed_case_dispatches_to_excluded(self) -> None:
        with _TempCSV([_good_no(
            include_in_short_horizon_validation="No",
        )]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertTrue(result["ok"])
        self.assertEqual(result["exclude_count"], 1)

    def test_blank_dispatches_to_pending(self) -> None:
        with _TempCSV([_blank()]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertTrue(result["ok"], f"errors: {result['errors']}")
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(result["include_count"], 0)
        self.assertEqual(result["exclude_count"], 0)
        self.assertEqual(len(result["pending_rows"]), 1)

    def test_whitespace_only_gate_is_pending(self) -> None:
        with _TempCSV([_blank(
            include_in_short_horizon_validation="   ",
        )]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertTrue(result["ok"])
        self.assertEqual(result["pending_count"], 1)

    def test_unknown_gate_value_is_per_row_error(self) -> None:
        with _TempCSV([_good_yes(
            include_in_short_horizon_validation="maybe",
        )]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])
        joined = " ".join(result["errors"])
        self.assertIn("include_in_short_horizon_validation", joined)


# ---------------------------------------------------------------------------
# Yes-row required fields
# ---------------------------------------------------------------------------


class TestYesRowRequirements(unittest.TestCase):
    def test_missing_primary_ticker_fails(self) -> None:
        with _TempCSV([_good_yes(proposed_primary_ticker="")]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])
        joined = " ".join(result["errors"])
        self.assertIn("proposed_primary_ticker", joined)

    def test_whitespace_primary_ticker_fails(self) -> None:
        with _TempCSV([_good_yes(proposed_primary_ticker="   ")]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])

    def test_missing_benchmark_ticker_fails(self) -> None:
        with _TempCSV([_good_yes(proposed_benchmark_ticker="")]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])
        joined = " ".join(result["errors"])
        self.assertIn("proposed_benchmark_ticker", joined)

    def test_missing_mechanism_family_fails(self) -> None:
        with _TempCSV([_good_yes(proposed_mechanism_family="")]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])
        joined = " ".join(result["errors"])
        self.assertIn("proposed_mechanism_family", joined)

    def test_missing_predicted_direction_fails(self) -> None:
        with _TempCSV([_good_yes(predicted_direction="")]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])
        joined = " ".join(result["errors"])
        self.assertIn("predicted_direction", joined)


# ---------------------------------------------------------------------------
# predicted_direction vocabulary
# ---------------------------------------------------------------------------


class TestPredictedDirection(unittest.TestCase):
    def test_up_accepts(self) -> None:
        with _TempCSV([_good_yes(predicted_direction="up")]) as p:
            self.assertTrue(cli.validate_review_worksheet(str(p))["ok"])

    def test_down_accepts(self) -> None:
        with _TempCSV([_good_yes(predicted_direction="down")]) as p:
            self.assertTrue(cli.validate_review_worksheet(str(p))["ok"])

    def test_neutral_accepts(self) -> None:
        # This contract uses ``neutral`` — NOT ``flat``.
        with _TempCSV([_good_yes(predicted_direction="neutral")]) as p:
            self.assertTrue(cli.validate_review_worksheet(str(p))["ok"])

    def test_flat_rejects(self) -> None:
        # ``flat`` is the curated-event vocabulary; this validator's
        # vocabulary is {up, down, neutral} and must reject flat.
        with _TempCSV([_good_yes(predicted_direction="flat")]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])
        joined = " ".join(result["errors"])
        self.assertIn("predicted_direction", joined)

    def test_bullish_rejects(self) -> None:
        with _TempCSV([_good_yes(predicted_direction="bullish")]) as p:
            self.assertFalse(cli.validate_review_worksheet(str(p))["ok"])


# ---------------------------------------------------------------------------
# Ticker format
# ---------------------------------------------------------------------------


class TestTickerFormat(unittest.TestCase):
    def test_single_letter_ticker_accepts(self) -> None:
        with _TempCSV([_good_yes(proposed_primary_ticker="F")]) as p:
            self.assertTrue(cli.validate_review_worksheet(str(p))["ok"])

    def test_four_letter_etf_accepts(self) -> None:
        with _TempCSV([_good_yes(proposed_primary_ticker="BDRY")]) as p:
            self.assertTrue(cli.validate_review_worksheet(str(p))["ok"])

    def test_dotted_class_share_accepts(self) -> None:
        with _TempCSV([_good_yes(proposed_primary_ticker="BRK.B")]) as p:
            self.assertTrue(cli.validate_review_worksheet(str(p))["ok"])

    def test_hyphen_share_accepts(self) -> None:
        with _TempCSV([_good_yes(proposed_primary_ticker="BRK-A")]) as p:
            self.assertTrue(cli.validate_review_worksheet(str(p))["ok"])

    def test_lowercase_ticker_rejects(self) -> None:
        with _TempCSV([_good_yes(proposed_primary_ticker="ms")]) as p:
            self.assertFalse(cli.validate_review_worksheet(str(p))["ok"])

    def test_ticker_with_space_rejects(self) -> None:
        with _TempCSV([_good_yes(
            proposed_primary_ticker="MS Bank",
        )]) as p:
            self.assertFalse(cli.validate_review_worksheet(str(p))["ok"])

    def test_prose_ticker_rejects(self) -> None:
        with _TempCSV([_good_yes(
            proposed_primary_ticker="Morgan Stanley",
        )]) as p:
            self.assertFalse(cli.validate_review_worksheet(str(p))["ok"])

    def test_overly_long_ticker_rejects(self) -> None:
        with _TempCSV([_good_yes(
            proposed_primary_ticker="ABCDEFGHIJKLMNOP",
        )]) as p:
            self.assertFalse(cli.validate_review_worksheet(str(p))["ok"])

    def test_lowercase_benchmark_rejects(self) -> None:
        with _TempCSV([_good_yes(proposed_benchmark_ticker="spy")]) as p:
            self.assertFalse(cli.validate_review_worksheet(str(p))["ok"])

    def test_blank_ticker_in_no_row_is_ok(self) -> None:
        # No rows have blank tickers — that's correct.  Ticker format
        # check only fires on yes rows.
        with _TempCSV([_good_no()]) as p:
            self.assertTrue(cli.validate_review_worksheet(str(p))["ok"])


# ---------------------------------------------------------------------------
# No-row requirements
# ---------------------------------------------------------------------------


class TestNoRowRequirements(unittest.TestCase):
    def test_no_row_with_reason_excluded(self) -> None:
        with _TempCSV([_good_no()]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertTrue(result["ok"])
        self.assertEqual(result["exclude_count"], 1)

    def test_no_row_without_reason_fails(self) -> None:
        with _TempCSV([_good_no(exclude_reason="")]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])
        joined = " ".join(result["errors"])
        self.assertIn("exclude_reason", joined)

    def test_no_row_whitespace_reason_fails(self) -> None:
        with _TempCSV([_good_no(exclude_reason="   ")]) as p:
            self.assertFalse(cli.validate_review_worksheet(str(p))["ok"])


# ---------------------------------------------------------------------------
# Pending-row semantics
# ---------------------------------------------------------------------------


class TestPendingSemantics(unittest.TestCase):
    def test_pending_only_worksheet_is_ok(self) -> None:
        # A worksheet the operator hasn't filled in yet shouldn't fail
        # validation — it's legitimately pending.
        with _TempCSV([_blank(), _blank(event_id="45"),
                       _blank(event_id="46")]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertTrue(result["ok"], f"errors: {result['errors']}")
        self.assertEqual(result["pending_count"], 3)
        self.assertEqual(result["include_count"], 0)
        self.assertEqual(result["exclude_count"], 0)

    def test_pending_row_does_not_require_other_fields(self) -> None:
        # Pending row may carry partially-filled fields — operator
        # might have filled in a ticker but not yet committed.
        partial = _blank(proposed_primary_ticker="MS")
        with _TempCSV([partial]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertTrue(result["ok"], f"errors: {result['errors']}")
        self.assertEqual(result["pending_count"], 1)


# ---------------------------------------------------------------------------
# Multi-row aggregation
# ---------------------------------------------------------------------------


class TestMultiRowAggregation(unittest.TestCase):
    def test_mixed_dispatch(self) -> None:
        rows = [
            _good_yes(event_id="1"),
            _good_no(event_id="2"),
            _blank(event_id="3"),
            _good_yes(event_id="4"),
        ]
        with _TempCSV(rows) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertTrue(result["ok"], f"errors: {result['errors']}")
        self.assertEqual(result["total_rows"], 4)
        self.assertEqual(result["include_count"], 2)
        self.assertEqual(result["exclude_count"], 1)
        self.assertEqual(result["pending_count"], 1)

    def test_one_bad_row_does_not_drop_others_from_buckets(self) -> None:
        rows = [
            _good_yes(event_id="1"),
            _good_yes(event_id="2", predicted_direction="bogus"),
            _good_no(event_id="3"),
            _blank(event_id="4"),
        ]
        with _TempCSV(rows) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertFalse(result["ok"])
        # Only the one valid yes row landed in accepted.  Bad row is
        # NOT in accepted but the rest of the buckets remain intact.
        self.assertEqual(result["include_count"], 1)
        self.assertEqual(result["exclude_count"], 1)
        self.assertEqual(result["pending_count"], 1)
        accepted_ids = {r.get("event_id") for r in result["accepted_rows"]}
        self.assertIn("1", accepted_ids)
        self.assertNotIn("2", accepted_ids)


# ---------------------------------------------------------------------------
# Read-only / no-mutation guarantee
# ---------------------------------------------------------------------------


class TestNoMutation(unittest.TestCase):
    def test_worksheet_file_unchanged_after_validation(self) -> None:
        rows = [_good_yes(), _good_no(), _blank()]
        with _TempCSV(rows) as p:
            before = p.read_bytes()
            cli.validate_review_worksheet(str(p))
            after = p.read_bytes()
        self.assertEqual(before, after,
                         "worksheet bytes changed during validation")

    def test_surfaced_row_carries_raw_gate_value(self) -> None:
        # Operator typed "  Yes  " — surfaced row dict must preserve
        # that exact string, not a normalised "yes".
        with _TempCSV([_good_yes(
            include_in_short_horizon_validation="  Yes  ",
        )]) as p:
            result = cli.validate_review_worksheet(str(p))
        self.assertEqual(result["include_count"], 1)
        surfaced = result["accepted_rows"][0]
        self.assertEqual(
            surfaced["include_in_short_horizon_validation"],
            "  Yes  ",
        )


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_words_in_error_or_warning_text(self) -> None:
        # Synthesize multiple error conditions to exercise the wording
        # paths.
        rows = [
            _good_yes(predicted_direction="flat"),
            _good_yes(proposed_primary_ticker=""),
            _good_yes(proposed_primary_ticker="Morgan Stanley"),
            _good_no(exclude_reason=""),
            _good_yes(include_in_short_horizon_validation="maybe"),
        ]
        with _TempCSV(rows) as p:
            result = cli.validate_review_worksheet(str(p))
        haystack = " ".join(
            list(result["errors"]) + list(result["warnings"])
        ).lower()
        for word in _BANNED_WORDS:
            self.assertNotIn(
                word, haystack,
                f"banned word {word!r} found in {haystack!r}",
            )

    def test_module_docstring_does_not_claim_validated(self) -> None:
        # The validator must not call any candidate "validated."
        text = (cli.__doc__ or "").lower()
        self.assertNotIn(" validated", text,
                         "validator docstring must not claim 'validated'")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_returns_zero_on_valid_worksheet(self) -> None:
        out = StringIO()
        with _TempCSV([_good_yes(), _good_no(), _blank()]) as p:
            rc = cli.main(
                ["--worksheet", str(p), "--json"], out=out,
            )
        self.assertEqual(rc, 0, f"output: {out.getvalue()}")
        parsed = json.loads(out.getvalue())
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["worksheet_path"], str(p))

    def test_cli_returns_nonzero_on_invalid_row(self) -> None:
        out = StringIO()
        with _TempCSV([_good_yes(predicted_direction="flat")]) as p:
            rc = cli.main(
                ["--worksheet", str(p), "--json"], out=out,
            )
        self.assertNotEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertFalse(parsed["ok"])

    def test_cli_returns_nonzero_on_missing_file(self) -> None:
        out = StringIO()
        rc = cli.main(
            ["--worksheet", "/no/such/worksheet.csv", "--json"],
            out=out,
        )
        self.assertNotEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertFalse(parsed["ok"])

    def test_cli_text_mode_runs(self) -> None:
        out = StringIO()
        with _TempCSV([_good_yes()]) as p:
            rc = cli.main(["--worksheet", str(p)], out=out)
        self.assertEqual(rc, 0)
        text = out.getvalue().lower()
        self.assertIn("ok", text)


if __name__ == "__main__":
    unittest.main()
