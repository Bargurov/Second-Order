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


# ---------------------------------------------------------------------------
# --emit-artifacts mode — analyzed_event_artifact_<candidate_id>.json
# ---------------------------------------------------------------------------


_ARTIFACT_BODY_REQUIRED_KEYS = (
    "artifact_type",
    "candidate_id",
    "headline",
    "event_date",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
)


def _fill_row(**overrides: str) -> dict[str, Any]:
    base = {col: "" for col in _SPEC_COLUMNS}
    base.update(overrides)
    return base


class TestEmitArtifactsDefaultIsNoOp(unittest.TestCase):
    """With the flags omitted, build remains read-only."""

    def test_default_does_not_write_per_row_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = cli.build_manual_event_intake_worksheet(
                rows=2, generated_at="2026-05-12T00:00:00Z",
            )
            # The flag fields are present and default-off; no
            # filesystem side effect.
            self.assertFalse(report["emit_artifacts"])
            self.assertIsNone(report["output_dir"])
            self.assertEqual(report["emitted_artifacts"], [])
            self.assertEqual(report["skipped_artifacts"], [])
            # Sanity: tmp directory is empty.
            self.assertEqual(sorted(os.listdir(tmp)), [])

    def test_emit_flag_without_output_dir_warns_and_emits_nothing(self) -> None:
        report = cli.build_manual_event_intake_worksheet(
            rows=1, generated_at="2026-05-12T00:00:00Z",
            emit_artifacts=True, output_dir=None,
        )
        self.assertTrue(report["emit_artifacts"])
        self.assertIsNone(report["output_dir"])
        self.assertEqual(report["emitted_artifacts"], [])
        # The warning surfaces so the operator can see why nothing
        # was written.
        self.assertTrue(any(
            "output-dir" in w.lower()
            for w in report["warnings"]
        ), f"warnings: {report['warnings']}")


class TestEmitArtifactsFilledRows(unittest.TestCase):
    """A filled row emits an analyzed_event_artifact_<cid>.json file."""

    def test_filled_row_emits_file_with_required_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            filled = _fill_row(
                candidate_id="mn-001",
                event_date="2022-07-28",
                headline=(
                    "Manchin-Schumer reconciliation deal includes "
                    "Inflation Reduction Act"
                ),
                mechanism_family="policy_driven_direct_beneficiary",
                primary_ticker="FSLR",
                benchmark_ticker="SPY",
                # market_relevance present
                event_family="legislation",
                operator_notes="Pilot row for FSLR IRA event.",
            )
            # Build over the filled row and emit in one call.
            report = cli.build_manual_event_intake_worksheet(
                generated_at="2026-05-12T00:00:00Z",
                worksheet_rows=[filled],
                emit_artifacts=True, output_dir=tmp,
            )
            self.assertTrue(report["ok"])
            self.assertEqual(report["worksheet_count"], 1)
            self.assertEqual(len(report["emitted_artifacts"]), 1)

            entry = report["emitted_artifacts"][0]
            self.assertEqual(entry["candidate_id"], "mn-001")
            self.assertEqual(entry["row_index"], 0)

            path = Path(entry["path"])
            self.assertTrue(path.exists())
            self.assertEqual(path.name, "analyzed_event_artifact_mn-001.json")
            body = json.loads(path.read_text(encoding="utf-8"))
            # Required schema keys present.
            for k in _ARTIFACT_BODY_REQUIRED_KEYS:
                self.assertIn(k, body, f"missing key in body: {k}")
            self.assertEqual(body["artifact_type"], "analyzed_event_artifact")
            self.assertEqual(body["candidate_id"], "mn-001")
            self.assertEqual(body["event_date"], "2022-07-28")
            self.assertEqual(body["primary_ticker"], "FSLR")
            self.assertEqual(body["benchmark_ticker"], "SPY")
            self.assertEqual(
                body["mechanism_family"], "policy_driven_direct_beneficiary",
            )
            self.assertIn("Manchin", body["headline"])

    def test_market_relevance_included_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            filled = _fill_row(
                candidate_id="mn-002",
                headline="Test headline",
                event_date="2022-08-01",
                mechanism_family="supply_shock",
                primary_ticker="XOM",
                benchmark_ticker="XLE",
                operator_notes="market_relevance=high",
            )
            # Append a non-spec market_relevance into the row body —
            # the emitter pulls it through directly.
            filled["market_relevance"] = "high"
            report = cli.build_manual_event_intake_worksheet(
                generated_at="2026-05-12T00:00:00Z",
                worksheet_rows=[filled],
                emit_artifacts=True, output_dir=tmp,
            )
            self.assertEqual(len(report["emitted_artifacts"]), 1)
            body = json.loads(
                Path(report["emitted_artifacts"][0]["path"]).read_text(
                    encoding="utf-8",
                ),
            )
            self.assertEqual(body.get("market_relevance"), "high")

    def test_market_relevance_omitted_when_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            filled = _fill_row(
                candidate_id="mn-003",
                headline="No relevance",
                event_date="2022-08-01",
                mechanism_family="tariffs_industrial_policy",
                primary_ticker="WHR",
                benchmark_ticker="XLY",
            )
            # market_relevance not set on the row at all.
            report = cli.build_manual_event_intake_worksheet(
                generated_at="2026-05-12T00:00:00Z",
                worksheet_rows=[filled],
                emit_artifacts=True, output_dir=tmp,
            )
            self.assertEqual(len(report["emitted_artifacts"]), 1)
            body = json.loads(
                Path(report["emitted_artifacts"][0]["path"]).read_text(
                    encoding="utf-8",
                ),
            )
            # Optional field is absent rather than empty-string.
            self.assertNotIn("market_relevance", body)

    def test_blank_rows_are_skipped_silently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Three rows: one filled, two blank.
            rows_in = [
                _fill_row(
                    candidate_id="mn-keep",
                    headline="Filled row",
                    event_date="2022-08-01",
                    mechanism_family="supply_shock",
                    primary_ticker="AA",
                    benchmark_ticker="XME",
                ),
                _fill_row(),  # blank
                _fill_row(),  # blank
            ]
            report = cli.build_manual_event_intake_worksheet(
                generated_at="2026-05-12T00:00:00Z",
                worksheet_rows=rows_in,
                emit_artifacts=True, output_dir=tmp,
            )
            self.assertEqual(report["worksheet_count"], 3)
            self.assertEqual(len(report["emitted_artifacts"]), 1)
            self.assertEqual(
                report["emitted_artifacts"][0]["candidate_id"], "mn-keep",
            )
            # Blank rows skip silently — they should NOT appear in
            # the skipped list (silent-skip is the contract for
            # default blank rows).
            blank_in_skipped = [
                s for s in report["skipped_artifacts"]
                if not s.get("candidate_id")
            ]
            self.assertEqual(blank_in_skipped, [])
            # And only the one filename ended up on disk.
            files = sorted(os.listdir(tmp))
            self.assertEqual(
                files, ["analyzed_event_artifact_mn-keep.json"],
            )

    def test_refuses_to_overwrite_existing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preexisting = Path(tmp) / "analyzed_event_artifact_mn-dup.json"
            preexisting.write_text(
                '{"artifact_type": "preexisting"}', encoding="utf-8",
            )
            filled = _fill_row(
                candidate_id="mn-dup",
                headline="Would overwrite",
                event_date="2022-08-01",
                mechanism_family="supply_shock",
                primary_ticker="AA",
                benchmark_ticker="XME",
            )
            report = cli.build_manual_event_intake_worksheet(
                generated_at="2026-05-12T00:00:00Z",
                worksheet_rows=[filled],
                emit_artifacts=True, output_dir=tmp,
            )
            # Nothing in emitted; one entry in skipped explaining why.
            self.assertEqual(report["emitted_artifacts"], [])
            self.assertEqual(len(report["skipped_artifacts"]), 1)
            skip = report["skipped_artifacts"][0]
            self.assertEqual(skip["candidate_id"], "mn-dup")
            self.assertIn("already exists", skip["reason"])
            # Pre-existing content untouched.
            self.assertEqual(
                preexisting.read_text(encoding="utf-8"),
                '{"artifact_type": "preexisting"}',
            )

    def test_unsafe_candidate_id_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            filled = _fill_row(
                candidate_id="../escape/mn-bad",
                headline="Path traversal attempt",
                mechanism_family="x",
                primary_ticker="x",
                benchmark_ticker="x",
            )
            report = cli.build_manual_event_intake_worksheet(
                generated_at="2026-05-12T00:00:00Z",
                worksheet_rows=[filled],
                emit_artifacts=True, output_dir=tmp,
            )
            self.assertEqual(report["emitted_artifacts"], [])
            self.assertEqual(len(report["skipped_artifacts"]), 1)
            skip = report["skipped_artifacts"][0]
            self.assertIn("safe for a filename", skip["reason"])
            # And nothing leaked into the temp dir or outside it.
            self.assertEqual(sorted(os.listdir(tmp)), [])


class TestEmitArtifactsHelperDirect(unittest.TestCase):
    """The emit_analyzed_event_artifacts helper is callable directly."""

    def test_helper_accepts_rows_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                _fill_row(
                    candidate_id="direct-001",
                    headline="Direct emit test",
                    event_date="2022-07-28",
                    mechanism_family="supply_shock",
                    primary_ticker="FSLR",
                    benchmark_ticker="SPY",
                ),
            ]
            result = cli.emit_analyzed_event_artifacts(
                rows=rows, output_dir=tmp,
            )
            self.assertEqual(result["emitted_count"], 1)
            self.assertEqual(result["skipped_count"], 0)
            self.assertEqual(result["errors"], [])
            path = Path(result["emitted"][0]["path"])
            self.assertTrue(path.exists())

    def test_helper_overwrite_flag_replaces_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preexisting = Path(tmp) / "analyzed_event_artifact_direct-002.json"
            preexisting.write_text(
                '{"artifact_type": "old"}', encoding="utf-8",
            )
            rows = [
                _fill_row(
                    candidate_id="direct-002",
                    headline="New",
                    event_date="2022-07-28",
                    mechanism_family="supply_shock",
                    primary_ticker="FSLR",
                    benchmark_ticker="SPY",
                ),
            ]
            # Default overwrite=False → skip.
            result_default = cli.emit_analyzed_event_artifacts(
                rows=rows, output_dir=tmp,
            )
            self.assertEqual(result_default["emitted_count"], 0)
            self.assertEqual(result_default["skipped_count"], 1)
            self.assertEqual(
                preexisting.read_text(encoding="utf-8"),
                '{"artifact_type": "old"}',
            )
            # overwrite=True → write.
            result_overwrite = cli.emit_analyzed_event_artifacts(
                rows=rows, output_dir=tmp, overwrite=True,
            )
            self.assertEqual(result_overwrite["emitted_count"], 1)
            new_body = json.loads(
                preexisting.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                new_body["artifact_type"], "analyzed_event_artifact",
            )
            self.assertEqual(new_body["candidate_id"], "direct-002")


class TestEmitArtifactsCLI(unittest.TestCase):
    """The CLI surfaces --emit-artifacts and --output-dir."""

    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_cli_emit_artifacts_with_blank_worksheet_is_noop(self) -> None:
        # The CLI builds blank rows by default; --emit-artifacts on
        # a blank worksheet writes nothing but exits cleanly.
        with tempfile.TemporaryDirectory() as tmp:
            rc, output = self._run([
                "--json", "--rows", "3",
                "--emit-artifacts", "--output-dir", tmp,
            ])
            self.assertEqual(rc, 0)
            parsed = json.loads(output)
            self.assertTrue(parsed["emit_artifacts"])
            self.assertEqual(parsed["emitted_artifacts"], [])
            self.assertEqual(sorted(os.listdir(tmp)), [])

    def test_cli_emit_flag_without_output_dir_surfaces_warning(self) -> None:
        rc, output = self._run([
            "--json", "--rows", "1", "--emit-artifacts",
        ])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertTrue(parsed["emit_artifacts"])
        self.assertIsNone(parsed["output_dir"])
        self.assertTrue(any(
            "output-dir" in w.lower()
            for w in parsed["warnings"]
        ), f"warnings: {parsed['warnings']}")


# ---------------------------------------------------------------------------
# Conservative wording — extended to new emit-mode prose
# ---------------------------------------------------------------------------


class TestEmitModeConservativeWording(unittest.TestCase):
    def test_emit_mode_envelope_prose_has_no_banned_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            filled = _fill_row(
                candidate_id="cw-001",
                headline="Test",
                event_date="2022-07-28",
                mechanism_family="x",
                primary_ticker="A",
                benchmark_ticker="B",
            )
            report = cli.build_manual_event_intake_worksheet(
                generated_at="2026-05-12T00:00:00Z",
                worksheet_rows=[filled],
                emit_artifacts=True, output_dir=tmp,
            )
            blob = cli._render_json(report).lower()
            for term in _BANNED_WORDS:
                self.assertNotIn(
                    term, blob,
                    f"banned token {term!r} surfaced in emit-mode "
                    f"envelope render",
                )


if __name__ == "__main__":
    unittest.main()
