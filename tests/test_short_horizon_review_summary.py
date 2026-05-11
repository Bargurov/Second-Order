"""Tests for ``scripts/short_horizon_review_summary.py``.

The summary script reads a manually-reviewed short-horizon worksheet
CSV and produces a compact operator-facing JSON checklist.

Pin the contract:

* Pure builder + CLI — no patchable runner seam.  Tests materialise
  tempfile CSVs and call ``build_review_summary`` / ``main``
  directly.
* JSON only — no text-mode result rendering, no CSV emission.  The
  worksheet on disk is read-only.
* Envelope schema (10 keys)::

      ok, worksheet_path, total_rows,
      yes_count, no_count, pending_count,
      top_pending_rows, recommended_manual_review_order,
      warnings, errors

* Gate vocabulary (``include_in_short_horizon_validation``):
    - ``yes`` (case- and whitespace-insensitive) → yes_count
    - ``no``  (case- and whitespace-insensitive) → no_count
    - blank / whitespace-only → pending_count, NO warning
    - any other non-blank value → pending_count + 1 warning per row
* ``top_pending_rows`` and ``recommended_manual_review_order`` are
  sorted by (priority_rank, event_id ascending) and capped at
  ``--limit``.  Both lists use the SAME cap.
* ``recommended_manual_review_order`` entries carry EXACTLY three
  fields::

      event_id, repair_priority, reason

  ``reason`` reads ``operator_decision_needed``; falls back to the
  literal string ``"manual_review_required"`` when blank.
* Read-only invariant — the CSV bytes are never rewritten.
* Conservative wording — error / warning strings avoid
  ``proof``, ``proves``, ``validated``, ``alpha``, ``guaranteed``.
"""
from __future__ import annotations

import csv as csv_module
import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import short_horizon_review_summary as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "worksheet_path",
    "total_rows",
    "yes_count",
    "no_count",
    "pending_count",
    "top_pending_rows",
    "recommended_manual_review_order",
    "warnings",
    "errors",
)


_RECO_ENTRY_FIELDS = ("event_id", "repair_priority", "reason")


_BANNED_WORDS = ("proof", "proves", "validated", "alpha", "guaranteed")


# Canonical short-horizon review worksheet header — same column order
# emitted by ``scripts.short_horizon_review_worksheet``.
_WORKSHEET_HEADER: tuple[str, ...] = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "current_mechanism_family",
    "repair_type",
    "repair_priority",
    "operator_decision_needed",
    "reason_for_review",
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "include_in_short_horizon_validation",
    "exclude_reason",
    "operator_notes",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _row(**fields: Any) -> dict[str, str]:
    base = {c: "" for c in _WORKSHEET_HEADER}
    base.update({k: ("" if v is None else str(v)) for k, v in fields.items()})
    return base


def _write_worksheet(
    rows: Iterable[dict[str, str]],
    *,
    header: Iterable[str] = _WORKSHEET_HEADER,
) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"sh_review_summary_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv_module.DictWriter(
            fh, fieldnames=list(header), extrasaction="ignore",
        )
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return path


class _TempCSV:
    """Context manager that materialises a tempfile worksheet CSV."""

    def __init__(
        self,
        rows: Iterable[dict[str, str]] | None = None,
        header: Iterable[str] = _WORKSHEET_HEADER,
        raw_text: str | None = None,
    ) -> None:
        self._rows = list(rows) if rows is not None else None
        self._header = list(header)
        self._raw_text = raw_text
        self._path: str | None = None

    def __enter__(self) -> str:
        if self._raw_text is not None:
            self._path = os.path.join(
                tempfile.gettempdir(),
                f"sh_review_summary_raw_{uuid.uuid4().hex}.csv",
            )
            Path(self._path).write_text(self._raw_text, encoding="utf-8")
        else:
            self._path = _write_worksheet(
                self._rows or [], header=self._header,
            )
        return self._path

    def __exit__(self, *exc: Any) -> None:
        if self._path and os.path.exists(self._path):
            os.unlink(self._path)


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_envelope_has_required_keys(self) -> None:
        with _TempCSV([_row(event_id=1)]) as path:
            report = cli.build_review_summary(worksheet_path=path)
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, report, f"missing envelope key: {k}")

    def test_envelope_has_no_extra_keys(self) -> None:
        with _TempCSV([_row(event_id=1)]) as path:
            report = cli.build_review_summary(worksheet_path=path)
        extras = set(report) - set(_REQUIRED_ENVELOPE_KEYS)
        self.assertEqual(extras, set(),
                         f"unexpected envelope keys: {extras}")

    def test_worksheet_path_echoed(self) -> None:
        with _TempCSV([_row(event_id=1)]) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertEqual(report["worksheet_path"], path)


# ---------------------------------------------------------------------------
# Structural errors
# ---------------------------------------------------------------------------


class TestStructuralErrors(unittest.TestCase):
    def test_missing_path_is_error(self) -> None:
        report = cli.build_review_summary(worksheet_path=None)
        self.assertFalse(report["ok"])
        self.assertTrue(report["errors"])

    def test_nonexistent_file_is_error(self) -> None:
        report = cli.build_review_summary(
            worksheet_path="/no/such/sh_review_summary.csv",
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "does not exist" in e.lower() or "not found" in e.lower()
            for e in report["errors"]
        ))

    def test_missing_event_id_column_is_error(self) -> None:
        bad_header = [c for c in _WORKSHEET_HEADER if c != "event_id"]
        with _TempCSV(
            [{c: "x" for c in bad_header}], header=bad_header,
        ) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertFalse(report["ok"])
        self.assertTrue(any("event_id" in e for e in report["errors"]))

    def test_missing_gate_column_is_error(self) -> None:
        bad_header = [
            c for c in _WORKSHEET_HEADER
            if c != "include_in_short_horizon_validation"
        ]
        with _TempCSV(
            [{c: "1" for c in bad_header}], header=bad_header,
        ) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "include_in_short_horizon_validation" in e
            for e in report["errors"]
        ))


# ---------------------------------------------------------------------------
# Empty / header-only worksheet
# ---------------------------------------------------------------------------


class TestEmptyWorksheet(unittest.TestCase):
    def test_header_only_yields_zero_counts(self) -> None:
        with _TempCSV([]) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertTrue(report["ok"], f"errors: {report['errors']}")
        self.assertEqual(report["total_rows"], 0)
        self.assertEqual(report["yes_count"], 0)
        self.assertEqual(report["no_count"], 0)
        self.assertEqual(report["pending_count"], 0)
        self.assertEqual(report["top_pending_rows"], [])
        self.assertEqual(report["recommended_manual_review_order"], [])


# ---------------------------------------------------------------------------
# Gate vocabulary
# ---------------------------------------------------------------------------


class TestGateVocabulary(unittest.TestCase):
    def test_yes_dispatches_to_yes_count(self) -> None:
        rows = [
            _row(event_id=1, include_in_short_horizon_validation="yes"),
            _row(event_id=2, include_in_short_horizon_validation="yes"),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertEqual(report["yes_count"], 2)
        self.assertEqual(report["pending_count"], 0)
        self.assertEqual(report["no_count"], 0)

    def test_no_dispatches_to_no_count(self) -> None:
        rows = [
            _row(event_id=1, include_in_short_horizon_validation="no"),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertEqual(report["no_count"], 1)
        self.assertEqual(report["pending_count"], 0)

    def test_yes_is_case_insensitive(self) -> None:
        rows = [
            _row(event_id=1, include_in_short_horizon_validation="YES"),
            _row(event_id=2, include_in_short_horizon_validation="Yes"),
            _row(event_id=3, include_in_short_horizon_validation="yEs"),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertEqual(report["yes_count"], 3)

    def test_no_is_case_insensitive(self) -> None:
        rows = [
            _row(event_id=1, include_in_short_horizon_validation="NO"),
            _row(event_id=2, include_in_short_horizon_validation="No"),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertEqual(report["no_count"], 2)

    def test_whitespace_padded_yes_dispatches_to_yes(self) -> None:
        rows = [
            _row(event_id=1, include_in_short_horizon_validation="  yes  "),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertEqual(report["yes_count"], 1)
        self.assertEqual(report["pending_count"], 0)

    def test_blank_gate_dispatches_to_pending(self) -> None:
        rows = [
            _row(event_id=1, include_in_short_horizon_validation=""),
            _row(event_id=2, include_in_short_horizon_validation="   "),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertEqual(report["pending_count"], 2)
        self.assertEqual(report["yes_count"], 0)
        self.assertEqual(report["no_count"], 0)

    def test_blank_gate_does_not_emit_a_warning(self) -> None:
        # Blank is the legitimate pending state — no warning.
        rows = [
            _row(event_id=1, include_in_short_horizon_validation=""),
            _row(event_id=2, include_in_short_horizon_validation="   "),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        for w in report["warnings"]:
            self.assertNotIn(
                "unrecognized", w.lower(),
                f"blank gate must not produce a warning: {w}",
            )

    def test_unrecognized_value_counts_as_pending_with_warning(self) -> None:
        rows = [
            _row(event_id=1, include_in_short_horizon_validation="maybe"),
            _row(event_id=2, include_in_short_horizon_validation="?"),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertEqual(report["pending_count"], 2)
        self.assertEqual(report["yes_count"], 0)
        self.assertEqual(report["no_count"], 0)
        # One warning per unrecognized row.
        self.assertEqual(len(report["warnings"]), 2)
        joined = " ".join(report["warnings"]).lower()
        self.assertIn("maybe", joined)


# ---------------------------------------------------------------------------
# top_pending_rows + recommended_manual_review_order
# ---------------------------------------------------------------------------


class TestPendingLists(unittest.TestCase):
    def test_top_pending_rows_lists_pending_only(self) -> None:
        rows = [
            _row(event_id=1, repair_priority="high",
                 include_in_short_horizon_validation="yes"),
            _row(event_id=2, repair_priority="high",
                 include_in_short_horizon_validation=""),
            _row(event_id=3, repair_priority="medium",
                 include_in_short_horizon_validation="no"),
            _row(event_id=4, repair_priority="low",
                 include_in_short_horizon_validation=""),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        ids = [r["event_id"] for r in report["top_pending_rows"]]
        self.assertEqual(set(ids), {2, 4},
                         "only pending rows must appear in top_pending_rows")

    def test_unrecognized_gate_also_in_top_pending_rows(self) -> None:
        rows = [
            _row(event_id=5, repair_priority="medium",
                 include_in_short_horizon_validation="maybe"),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        ids = [r["event_id"] for r in report["top_pending_rows"]]
        self.assertEqual(ids, [5])

    def test_recommended_order_has_only_three_fields(self) -> None:
        rows = [
            _row(event_id=1, repair_priority="high",
                 operator_decision_needed="supply_primary_ticker",
                 include_in_short_horizon_validation=""),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        entries = report["recommended_manual_review_order"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(set(entries[0].keys()), set(_RECO_ENTRY_FIELDS))

    def test_recommended_order_reason_uses_operator_decision_needed(
        self,
    ) -> None:
        rows = [
            _row(event_id=1, repair_priority="high",
                 operator_decision_needed="supply_primary_ticker",
                 include_in_short_horizon_validation=""),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        entry = report["recommended_manual_review_order"][0]
        self.assertEqual(entry["event_id"], 1)
        self.assertEqual(entry["repair_priority"], "high")
        self.assertEqual(entry["reason"], "supply_primary_ticker")

    def test_recommended_order_reason_falls_back_when_blank(self) -> None:
        # When operator_decision_needed is blank/whitespace, the
        # spec mandates the literal fallback "manual_review_required".
        rows = [
            _row(event_id=1, repair_priority="high",
                 operator_decision_needed="",
                 include_in_short_horizon_validation=""),
            _row(event_id=2, repair_priority="medium",
                 operator_decision_needed="   ",
                 include_in_short_horizon_validation=""),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        for entry in report["recommended_manual_review_order"]:
            self.assertEqual(entry["reason"], "manual_review_required")


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


class TestSortOrder(unittest.TestCase):
    def test_priority_high_before_medium_before_low(self) -> None:
        rows = [
            _row(event_id=30, repair_priority="low",
                 include_in_short_horizon_validation=""),
            _row(event_id=10, repair_priority="medium",
                 include_in_short_horizon_validation=""),
            _row(event_id=20, repair_priority="high",
                 include_in_short_horizon_validation=""),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        priorities = [
            r["repair_priority"]
            for r in report["recommended_manual_review_order"]
        ]
        self.assertEqual(priorities, ["high", "medium", "low"])

    def test_event_id_ascending_within_priority(self) -> None:
        rows = [
            _row(event_id=30, repair_priority="high",
                 include_in_short_horizon_validation=""),
            _row(event_id=10, repair_priority="high",
                 include_in_short_horizon_validation=""),
            _row(event_id=20, repair_priority="high",
                 include_in_short_horizon_validation=""),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        ids = [
            r["event_id"]
            for r in report["recommended_manual_review_order"]
        ]
        self.assertEqual(ids, [10, 20, 30])

    def test_top_pending_rows_share_sort_order(self) -> None:
        rows = [
            _row(event_id=99, repair_priority="low",
                 include_in_short_horizon_validation=""),
            _row(event_id=42, repair_priority="high",
                 include_in_short_horizon_validation=""),
            _row(event_id=42, repair_priority="high",
                 include_in_short_horizon_validation="",
                 event_id_dup="x"),
            _row(event_id=11, repair_priority="medium",
                 include_in_short_horizon_validation=""),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        priorities_top = [
            r["repair_priority"] for r in report["top_pending_rows"]
        ]
        priorities_reco = [
            r["repair_priority"]
            for r in report["recommended_manual_review_order"]
        ]
        # Same ordering across the two lists.
        self.assertEqual(priorities_top, priorities_reco)


# ---------------------------------------------------------------------------
# --limit truncation — same cap on both lists
# ---------------------------------------------------------------------------


class TestLimit(unittest.TestCase):
    def test_default_limit_is_ten(self) -> None:
        rows = [
            _row(event_id=i, repair_priority="high",
                 include_in_short_horizon_validation="")
            for i in range(1, 21)
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        self.assertEqual(len(report["top_pending_rows"]), 10)
        self.assertEqual(
            len(report["recommended_manual_review_order"]), 10,
        )
        self.assertEqual(report["pending_count"], 20)

    def test_explicit_limit_truncates_both_lists_to_same_cap(self) -> None:
        rows = [
            _row(event_id=i, repair_priority="high",
                 include_in_short_horizon_validation="")
            for i in range(1, 11)
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(
                worksheet_path=path, limit=3,
            )
        self.assertEqual(len(report["top_pending_rows"]), 3)
        self.assertEqual(
            len(report["recommended_manual_review_order"]), 3,
        )
        # Aggregate counts still reflect every pending row.
        self.assertEqual(report["pending_count"], 10)

    def test_zero_limit_yields_empty_lists_but_keeps_counts(self) -> None:
        rows = [
            _row(event_id=i, repair_priority="high",
                 include_in_short_horizon_validation="")
            for i in range(1, 4)
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(
                worksheet_path=path, limit=0,
            )
        self.assertEqual(report["top_pending_rows"], [])
        self.assertEqual(report["recommended_manual_review_order"], [])
        self.assertEqual(report["pending_count"], 3)


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnly(unittest.TestCase):
    def test_worksheet_bytes_unchanged_after_build(self) -> None:
        rows = [
            _row(event_id=1, repair_priority="high",
                 include_in_short_horizon_validation=""),
            _row(event_id=2, repair_priority="medium",
                 include_in_short_horizon_validation="yes"),
        ]
        with _TempCSV(rows) as path:
            before = Path(path).read_bytes()
            cli.build_review_summary(worksheet_path=path)
            after = Path(path).read_bytes()
        self.assertEqual(before, after,
                         "summary must not rewrite the worksheet on disk")


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_warnings_and_errors_avoid_banned_words(self) -> None:
        rows = [
            _row(event_id=1, repair_priority="high",
                 include_in_short_horizon_validation="maybe"),
            _row(event_id=2, repair_priority="medium",
                 include_in_short_horizon_validation=""),
        ]
        with _TempCSV(rows) as path:
            report = cli.build_review_summary(worksheet_path=path)
        haystack = " ".join(
            list(report["errors"]) + list(report["warnings"])
        ).lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, haystack)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_emits_parseable_json(self) -> None:
        rows = [
            _row(event_id=1, repair_priority="high",
                 include_in_short_horizon_validation=""),
        ]
        with _TempCSV(rows) as path:
            out = StringIO()
            rc = cli.main(
                ["--worksheet", path, "--json", "--limit", "5"], out=out,
            )
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(parsed["worksheet_path"], path)

    def test_cli_returns_nonzero_when_envelope_not_ok(self) -> None:
        out = StringIO()
        rc = cli.main(
            ["--worksheet", "/no/such/file.csv", "--json"], out=out,
        )
        self.assertNotEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertFalse(parsed["ok"])

    def test_cli_default_invocation_still_emits_json(self) -> None:
        # No --json flag — script is JSON-only; output must still be
        # parseable JSON.
        rows = [
            _row(event_id=1, repair_priority="high",
                 include_in_short_horizon_validation=""),
        ]
        with _TempCSV(rows) as path:
            out = StringIO()
            rc = cli.main(["--worksheet", path], out=out)
        self.assertEqual(rc, 0)
        json.loads(out.getvalue())


if __name__ == "__main__":
    unittest.main()
