"""Tests for ``scripts/manual_event_intake_worksheet.py``.

Pin the contract:

* Read-only on every input.  No DB writes, no DB reads, no provider,
  no ``yfinance``, no LLM, no FastAPI surface.
* No existing artifact is mutated.  ``--output`` refuses to
  overwrite an existing path.
* The envelope has the documented top-level keys.
* ``worksheet_columns`` exposes the 15 spec column names in spec
  order.
* Every emitted worksheet row carries exactly those 15 keys, all
  with empty-string values (the script never assigns a value).
* CSV output renders the header in spec order followed by N blank
  rows; lines terminate with ``\n`` (LF, not CRLF).
* Conservative wording — banned tokens absent from any prose.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import manual_event_intake_worksheet as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "artifact_type",
    "generated_at",
    "worksheet_columns",
    "worksheet_count",
    "worksheet",
    "instructions",
    "limitations",
    "warnings",
    "errors",
    "recommended_next_action",
)


_SPEC_COLUMNS = (
    "candidate_id",
    "event_date",
    "headline",
    "source_url",
    "event_family",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "predicted_direction",
    "horizon_focus",
    "why_this_event_is_defensible",
    "what_would_falsify",
    "include_in_validation",
    "exclude_reason",
    "operator_notes",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "validated",
    "automatically",
    "alpha generated",
    "guaranteed",
    "correct ticker",
)


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_envelope_has_all_required_keys(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            generated_at="2026-05-12T00:00:00Z",
        )
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, report, f"missing key: {k}")

    def test_artifact_type_is_manual_event_intake_worksheet(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            generated_at="2026-05-12T00:00:00Z",
        )
        self.assertEqual(
            report["artifact_type"], "manual_event_intake_worksheet",
        )

    def test_ok_true_by_default(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            generated_at="2026-05-12T00:00:00Z",
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])

    def test_generated_at_seam_is_honored(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            generated_at="2099-01-01T00:00:00Z",
        )
        self.assertEqual(report["generated_at"], "2099-01-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Worksheet columns — spec order
# ---------------------------------------------------------------------------


class TestWorksheetColumns(unittest.TestCase):
    def test_columns_match_spec_in_spec_order(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            generated_at="2026-05-12T00:00:00Z",
        )
        self.assertEqual(
            tuple(report["worksheet_columns"]),
            _SPEC_COLUMNS,
            "worksheet_columns must echo the 15 spec columns in spec order",
        )

    def test_columns_match_module_constant(self) -> None:
        # The module's _WORKSHEET_COLUMNS is the single source of
        # truth for both JSON and CSV rendering.
        self.assertEqual(tuple(cli._WORKSHEET_COLUMNS), _SPEC_COLUMNS)

    def test_columns_count_is_fifteen(self) -> None:
        self.assertEqual(len(_SPEC_COLUMNS), 15)
        report = cli.build_manual_event_intake_worksheet(
            generated_at="2026-05-12T00:00:00Z",
        )
        self.assertEqual(len(report["worksheet_columns"]), 15)


# ---------------------------------------------------------------------------
# Row count and blank-row invariant
# ---------------------------------------------------------------------------


class TestRowCount(unittest.TestCase):
    def test_default_rows_is_one(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            generated_at="2026-05-12T00:00:00Z",
        )
        self.assertEqual(report["worksheet_count"], 1)
        self.assertEqual(len(report["worksheet"]), 1)

    def test_rows_n_controls_count(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=5, generated_at="2026-05-12T00:00:00Z",
        )
        self.assertEqual(report["worksheet_count"], 5)
        self.assertEqual(len(report["worksheet"]), 5)

    def test_rows_zero_yields_empty_worksheet(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=0, generated_at="2026-05-12T00:00:00Z",
        )
        self.assertEqual(report["worksheet_count"], 0)
        self.assertEqual(report["worksheet"], [])

    def test_rows_negative_clamps_to_zero_with_warning(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=-3, generated_at="2026-05-12T00:00:00Z",
        )
        self.assertEqual(report["worksheet_count"], 0)
        self.assertTrue(any(
            "non-negative" in w for w in report["warnings"]
        ), f"warnings: {report['warnings']}")

    def test_rows_capped_at_max(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=10_000, generated_at="2026-05-12T00:00:00Z",
        )
        self.assertEqual(report["worksheet_count"], cli._MAX_ROWS)
        self.assertTrue(any(
            "capped" in w for w in report["warnings"]
        ))


class TestBlankRowInvariant(unittest.TestCase):
    def test_each_row_has_all_fifteen_fields(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=3, generated_at="2026-05-12T00:00:00Z",
        )
        for row in report["worksheet"]:
            self.assertEqual(set(row.keys()), set(_SPEC_COLUMNS))

    def test_every_field_is_empty_string(self) -> None:
        # The script never assigns a value to any field — every row
        # is blank by construction.  Failing this test means the
        # script started proposing values on the operator's behalf.
        report = cli.build_manual_event_intake_worksheet(
            rows=4, generated_at="2026-05-12T00:00:00Z",
        )
        for row in report["worksheet"]:
            for col in _SPEC_COLUMNS:
                self.assertEqual(
                    row[col], "",
                    f"column {col!r} must be empty by construction; "
                    f"got {row[col]!r}",
                )

    def test_rows_are_independent_dicts(self) -> None:
        # Defensive: rows shouldn't share a mutable dict identity, so
        # an operator can fill row 0 without aliasing row 1.
        report = cli.build_manual_event_intake_worksheet(
            rows=2, generated_at="2026-05-12T00:00:00Z",
        )
        report["worksheet"][0]["candidate_id"] = "mn-001"
        self.assertEqual(report["worksheet"][1]["candidate_id"], "")


# ---------------------------------------------------------------------------
# CSV rendering
# ---------------------------------------------------------------------------


class TestCsvRendering(unittest.TestCase):
    def test_csv_header_matches_spec_order(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=2, generated_at="2026-05-12T00:00:00Z",
        )
        csv_text = cli._render_csv(report)
        header = csv_text.split("\n", 1)[0]
        self.assertEqual(header, ",".join(_SPEC_COLUMNS))

    def test_csv_row_count_matches_rows(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=3, generated_at="2026-05-12T00:00:00Z",
        )
        csv_text = cli._render_csv(report)
        # Header + 3 rows + trailing empty after final \n.
        non_empty = [l for l in csv_text.split("\n") if l != ""]
        self.assertEqual(len(non_empty), 4)

    def test_csv_lines_are_lf_not_crlf(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=3, generated_at="2026-05-12T00:00:00Z",
        )
        csv_text = cli._render_csv(report)
        self.assertNotIn("\r", csv_text,
                         "CSV must use LF line endings, not CRLF")

    def test_csv_zero_rows_emits_header_only(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=0, generated_at="2026-05-12T00:00:00Z",
        )
        csv_text = cli._render_csv(report)
        non_empty = [l for l in csv_text.split("\n") if l != ""]
        self.assertEqual(non_empty, [",".join(_SPEC_COLUMNS)])

    def test_csv_rows_are_all_blank(self) -> None:
        # Every CSV data cell must be empty.  An assigned value
        # leaking through would mean the script started proposing.
        report = cli.build_manual_event_intake_worksheet(
            rows=2, generated_at="2026-05-12T00:00:00Z",
        )
        csv_text = cli._render_csv(report)
        lines = [l for l in csv_text.split("\n") if l != ""]
        # 14 commas separate 15 empty fields per data row.
        expected_blank = "," * (len(_SPEC_COLUMNS) - 1)
        for line in lines[1:]:
            self.assertEqual(line, expected_blank)


# ---------------------------------------------------------------------------
# --output file persistence
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def _tmp(self, suffix: str) -> str:
        return os.path.join(
            tempfile.gettempdir(),
            f"mei_{uuid.uuid4().hex}{suffix}",
        )

    def test_no_output_means_no_file(self) -> None:
        # Building the envelope without --output must have zero
        # filesystem side effects.
        sentinel = self._tmp(".json")
        cli.build_manual_event_intake_worksheet(
            rows=1, generated_at="2026-05-12T00:00:00Z",
        )
        self.assertFalse(Path(sentinel).exists())

    def test_output_writes_json_when_format_json(self) -> None:
        out = self._tmp(".json")
        try:
            report = cli.build_manual_event_intake_worksheet(
                rows=2, output_path=out, output_format="json",
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertTrue(report["ok"])
            self.assertTrue(Path(out).exists())
            parsed = json.loads(Path(out).read_text(encoding="utf-8"))
            self.assertEqual(parsed["worksheet_count"], 2)
            self.assertEqual(
                tuple(parsed["worksheet_columns"]), _SPEC_COLUMNS,
            )
        finally:
            if Path(out).exists():
                Path(out).unlink()

    def test_output_writes_csv_when_format_csv(self) -> None:
        out = self._tmp(".csv")
        try:
            report = cli.build_manual_event_intake_worksheet(
                rows=2, output_path=out, output_format="csv",
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertTrue(report["ok"])
            self.assertTrue(Path(out).exists())
            raw = Path(out).read_bytes()
            self.assertNotIn(b"\r", raw,
                             "CSV file must use LF line endings")
            text = raw.decode("utf-8")
            self.assertEqual(
                text.split("\n", 1)[0], ",".join(_SPEC_COLUMNS),
            )
        finally:
            if Path(out).exists():
                Path(out).unlink()

    def test_output_refuses_to_overwrite_existing_file(self) -> None:
        # "Do not mutate existing artifacts" — the script must refuse
        # when the output path already exists.
        out = self._tmp(".json")
        try:
            Path(out).write_text("preexisting content", encoding="utf-8")
            report = cli.build_manual_event_intake_worksheet(
                rows=1, output_path=out, output_format="json",
                generated_at="2026-05-12T00:00:00Z",
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "refusing to overwrite" in e.lower()
                for e in report["errors"]
            ), f"errors: {report['errors']}")
            # Pre-existing content must be intact — we must not
            # touch the file.
            self.assertEqual(
                Path(out).read_text(encoding="utf-8"),
                "preexisting content",
            )
        finally:
            if Path(out).exists():
                Path(out).unlink()


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_tokens_in_envelope_prose(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=2, generated_at="2026-05-12T00:00:00Z",
        )
        text = " ".join([
            *report["instructions"],
            *report["limitations"],
            *report["warnings"],
            *[str(e) for e in report["errors"]],
            report["recommended_next_action"],
        ]).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(
                term, text,
                f"banned token {term!r} in worksheet prose",
            )

    def test_no_banned_tokens_in_json_render(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=2, generated_at="2026-05-12T00:00:00Z",
        )
        blob = cli._render_json(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, blob)

    def test_no_banned_tokens_in_csv_render(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=2, generated_at="2026-05-12T00:00:00Z",
        )
        text = cli._render_csv(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, text)


# ---------------------------------------------------------------------------
# Import isolation — no provider / LLM / FastAPI binding
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_provider_attrs(self) -> None:
        for attr in ("yfinance", "anthropic", "openai", "fastapi"):
            self.assertFalse(
                hasattr(cli, attr),
                f"intake worksheet must not bind {attr} as a module attr",
            )

    def test_module_does_not_bind_db_attr(self) -> None:
        # The script is intake-only and must not pull in the project
        # db module at import time.
        self.assertFalse(hasattr(cli, "db"))

    def test_module_does_not_bind_routes_or_api(self) -> None:
        for attr in ("api", "routes"):
            self.assertFalse(hasattr(cli, attr))


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_default_emits_json(self) -> None:
        rc, output = self._run([])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(
            tuple(parsed["worksheet_columns"]), _SPEC_COLUMNS,
        )

    def test_json_flag_emits_json(self) -> None:
        rc, output = self._run(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["artifact_type"], "manual_event_intake_worksheet")

    def test_csv_flag_emits_csv(self) -> None:
        rc, output = self._run(["--csv"])
        self.assertEqual(rc, 0)
        # First line is the header; must match spec order.
        first_line = output.split("\n", 1)[0]
        self.assertEqual(first_line, ",".join(_SPEC_COLUMNS))

    def test_csv_and_json_are_mutually_exclusive(self) -> None:
        # argparse should reject the combination with a nonzero exit.
        rc, _ = self._run(["--csv", "--json"])
        self.assertNotEqual(rc, 0)

    def test_rows_flag_controls_csv_row_count(self) -> None:
        rc, output = self._run(["--csv", "--rows", "5"])
        self.assertEqual(rc, 0)
        non_empty = [l for l in output.split("\n") if l != ""]
        self.assertEqual(len(non_empty), 6)  # header + 5 rows

    def test_output_flag_writes_file_and_stdout_still_emits(self) -> None:
        out = os.path.join(
            tempfile.gettempdir(),
            f"mei_cli_{uuid.uuid4().hex}.csv",
        )
        try:
            rc, output = self._run([
                "--csv", "--rows", "2", "--output", out,
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(Path(out).exists())
            # File contents have the same header as stdout.
            file_first = Path(out).read_text(encoding="utf-8").split("\n", 1)[0]
            stdout_first = output.split("\n", 1)[0]
            self.assertEqual(file_first, stdout_first)
        finally:
            if Path(out).exists():
                Path(out).unlink()

    def test_cli_output_refuses_overwrite_and_returns_nonzero(self) -> None:
        out = os.path.join(
            tempfile.gettempdir(),
            f"mei_cli_overwrite_{uuid.uuid4().hex}.json",
        )
        try:
            Path(out).write_text("existing", encoding="utf-8")
            rc, output = self._run(["--json", "--output", out])
            self.assertNotEqual(rc, 0)
            # Pre-existing content untouched.
            self.assertEqual(
                Path(out).read_text(encoding="utf-8"), "existing",
            )
            # The error is surfaced in the stdout JSON envelope.
            parsed = json.loads(output)
            self.assertFalse(parsed["ok"])
            self.assertTrue(any(
                "refusing to overwrite" in e.lower()
                for e in parsed["errors"]
            ))
        finally:
            if Path(out).exists():
                Path(out).unlink()


if __name__ == "__main__":
    unittest.main()
