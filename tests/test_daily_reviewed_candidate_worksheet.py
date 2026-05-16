"""Tests for ``scripts/daily_reviewed_candidate_worksheet.py``.

The Daily reviewed-candidate worksheet generator emits a small
operator-fillable worksheet (1-3 reviewed Daily demo candidates).
The filled CSV is the source the downstream emitter
(``scripts/daily_analyzed_event_artifact_emitter.py``) reads to
write per-row ``analyzed_event_artifact_<candidate_id>.json`` files
the Daily artifact gate admits.

Tests pin:

* the 10 spec columns are present in the documented order, on every
  row, on both JSON and CSV output;
* every row is blank by construction — the script never invents or
  derives a ``candidate_id``;
* JSON preview is the default; ``--csv`` switches to CSV output;
* ``--rows`` controls the row count (default 1, capped at the module
  maximum); non-int / negative / over-cap values surface a warning
  and fall back gracefully;
* the script has no filesystem side effect without ``--output``;
* ``--output`` writes the worksheet but refuses to overwrite an
  existing path;
* the module imports nothing that would breach the read-only
  contract (no DB writes, no provider/yfinance/LLM/FastAPI);
* the module never references ``news_inbox`` outside its docstring
  header;
* conservative wording — banned tokens never appear in the module
  text outside the documented header.
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import daily_reviewed_candidate_worksheet as ws  # noqa: E402


_EXPECTED_COLUMNS: tuple[str, ...] = (
    "candidate_id",
    "headline",
    "event_date",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "market_relevance",
    "inclusion_reason",
    "include_in_daily_section_c",
    "operator_notes",
)


# ---------------------------------------------------------------------------
# Worksheet column / row shape
# ---------------------------------------------------------------------------


class TestWorksheetShape(unittest.TestCase):

    def test_module_columns_match_spec_order(self) -> None:
        self.assertEqual(ws._WORKSHEET_COLUMNS, _EXPECTED_COLUMNS)

    def test_envelope_carries_columns_in_spec_order(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet()
        self.assertEqual(
            env["worksheet_columns"], list(_EXPECTED_COLUMNS),
        )

    def test_envelope_artifact_type_is_pinned(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet()
        self.assertEqual(
            env["artifact_type"], "daily_reviewed_candidate_worksheet",
        )

    def test_default_one_blank_row(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet()
        self.assertEqual(env["worksheet_count"], 1)
        self.assertEqual(len(env["worksheet"]), 1)
        row = env["worksheet"][0]
        self.assertEqual(set(row.keys()), set(_EXPECTED_COLUMNS))
        for col in _EXPECTED_COLUMNS:
            self.assertEqual(
                row[col], "",
                f"column {col!r} should be blank by construction",
            )

    def test_each_row_carries_every_spec_column(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(rows=5)
        self.assertEqual(env["worksheet_count"], 5)
        for i, row in enumerate(env["worksheet"]):
            self.assertEqual(
                set(row.keys()), set(_EXPECTED_COLUMNS),
                f"row {i} is missing a spec column",
            )

    def test_candidate_id_column_is_blank_on_every_row(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(rows=3)
        for i, row in enumerate(env["worksheet"]):
            self.assertEqual(
                row["candidate_id"], "",
                f"row {i} candidate_id should be blank — script never "
                "auto-generates a value",
            )

    def test_no_default_fake_candidates(self) -> None:
        # Every value on every row is the empty string.  The script
        # never seeds an example headline or ticker.
        env = ws.build_daily_reviewed_candidate_worksheet(rows=3)
        for row in env["worksheet"]:
            for col, val in row.items():
                self.assertEqual(
                    val, "",
                    f"row carries a non-empty default in column {col!r}",
                )

    def test_envelope_ok_true_on_default_invocation(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet()
        self.assertTrue(env["ok"])
        self.assertEqual(env["errors"], [])

    def test_envelope_carries_instructions_and_limitations(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet()
        self.assertIsInstance(env["instructions"], list)
        self.assertGreater(len(env["instructions"]), 0)
        self.assertIsInstance(env["limitations"], list)
        self.assertGreater(len(env["limitations"]), 0)
        self.assertIsInstance(env["recommended_next_action"], str)
        self.assertGreater(len(env["recommended_next_action"]), 0)


# ---------------------------------------------------------------------------
# --rows clamping
# ---------------------------------------------------------------------------


class TestRowsClamping(unittest.TestCase):

    def test_negative_rows_clamped_to_zero_with_warning(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(rows=-1)
        self.assertEqual(env["worksheet_count"], 0)
        self.assertEqual(env["worksheet"], [])
        self.assertTrue(any("non-negative" in w for w in env["warnings"]))

    def test_over_cap_rows_clamped_with_warning(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(
            rows=ws._MAX_ROWS + 5,
        )
        self.assertEqual(env["worksheet_count"], ws._MAX_ROWS)
        self.assertTrue(any("capped" in w for w in env["warnings"]))

    def test_non_int_rows_falls_back_to_default(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(rows="three")  # type: ignore[arg-type]
        self.assertEqual(env["worksheet_count"], ws._DEFAULT_ROWS)
        self.assertTrue(any("not an int" in w for w in env["warnings"]))

    def test_bool_rows_falls_back_to_default(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(rows=True)
        self.assertEqual(env["worksheet_count"], ws._DEFAULT_ROWS)
        self.assertTrue(any("bool" in w for w in env["warnings"]))

    def test_zero_rows_emits_empty_worksheet(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(rows=0)
        self.assertEqual(env["worksheet_count"], 0)
        self.assertEqual(env["worksheet"], [])
        self.assertEqual(env["warnings"], [])

    def test_three_rows_emits_three_blank_rows(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(rows=3)
        self.assertEqual(env["worksheet_count"], 3)
        self.assertEqual(len(env["worksheet"]), 3)


# ---------------------------------------------------------------------------
# JSON / CSV rendering
# ---------------------------------------------------------------------------


class TestRendering(unittest.TestCase):

    def test_json_default_renders_valid_json(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(rows=2)
        rendered = ws._render_json(env)
        parsed = json.loads(rendered)
        self.assertEqual(parsed["worksheet_count"], 2)
        self.assertEqual(parsed["worksheet_columns"], list(_EXPECTED_COLUMNS))

    def test_csv_header_matches_spec_order(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(rows=3)
        rendered = ws._render_csv(env)
        first_line = rendered.splitlines()[0]
        self.assertEqual(
            first_line, ",".join(_EXPECTED_COLUMNS),
        )

    def test_csv_uses_lf_line_terminator(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(rows=2)
        rendered = ws._render_csv(env)
        # Three lines: header + two rows.  No CRLF.
        self.assertNotIn("\r\n", rendered)
        self.assertEqual(rendered.count("\n"), 3)

    def test_csv_rows_are_blank_under_header(self) -> None:
        env = ws.build_daily_reviewed_candidate_worksheet(rows=2)
        rendered = ws._render_csv(env)
        lines = rendered.splitlines()
        self.assertEqual(len(lines), 3)
        # Each blank row is exactly N-1 commas (N empty cells).
        expected_blank = "," * (len(_EXPECTED_COLUMNS) - 1)
        self.assertEqual(lines[1], expected_blank)
        self.assertEqual(lines[2], expected_blank)


# ---------------------------------------------------------------------------
# Output-file persistence
# ---------------------------------------------------------------------------


class TestOutputPersistence(unittest.TestCase):

    def test_no_filesystem_writes_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            entries_before = sorted(tmp_dir.iterdir())
            ws.build_daily_reviewed_candidate_worksheet(rows=2)
            entries_after = sorted(tmp_dir.iterdir())
            self.assertEqual(entries_before, entries_after)

    def test_writes_json_to_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "ws.json"
            env = ws.build_daily_reviewed_candidate_worksheet(
                rows=2, output_path=str(target),
            )
            self.assertTrue(env["ok"])
            self.assertTrue(target.exists())
            on_disk = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["worksheet_count"], 2)

    def test_writes_csv_to_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "ws.csv"
            env = ws.build_daily_reviewed_candidate_worksheet(
                rows=2,
                output_path=str(target),
                output_format="csv",
            )
            self.assertTrue(env["ok"])
            self.assertTrue(target.exists())
            text = target.read_text(encoding="utf-8")
            self.assertEqual(
                text.splitlines()[0], ",".join(_EXPECTED_COLUMNS),
            )

    def test_refuses_to_overwrite_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "ws.json"
            target.write_text("pre-existing content", encoding="utf-8")
            env = ws.build_daily_reviewed_candidate_worksheet(
                output_path=str(target),
            )
            self.assertFalse(env["ok"])
            self.assertTrue(any(
                "refusing to overwrite" in e for e in env["errors"]
            ))
            # Existing file untouched.
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "pre-existing content",
            )

    def test_creates_parent_directory_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "deeper" / "ws.json"
            env = ws.build_daily_reviewed_candidate_worksheet(
                output_path=str(target),
            )
            self.assertTrue(env["ok"])
            self.assertTrue(target.exists())


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLIPlumbing(unittest.TestCase):

    def test_main_default_prints_json_envelope(self) -> None:
        buf = io.StringIO()
        rc = ws.main([], out=buf)
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["worksheet_count"], 1)

    def test_main_json_flag_is_explicit_default(self) -> None:
        buf = io.StringIO()
        rc = ws.main(["--json"], out=buf)
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["worksheet_count"], 1)

    def test_main_csv_flag_emits_csv(self) -> None:
        buf = io.StringIO()
        rc = ws.main(["--csv", "--rows", "3"], out=buf)
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        lines = text.splitlines()
        self.assertEqual(len(lines), 4)  # header + 3 rows
        self.assertEqual(lines[0], ",".join(_EXPECTED_COLUMNS))

    def test_main_rows_argument_threaded(self) -> None:
        buf = io.StringIO()
        rc = ws.main(["--rows", "3"], out=buf)
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["worksheet_count"], 3)

    def test_main_output_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "ws.json"
            buf = io.StringIO()
            rc = ws.main(
                ["--rows", "2", "--output", str(target)],
                out=buf,
            )
            self.assertEqual(rc, 0)
            self.assertTrue(target.exists())

    def test_main_returns_one_when_overwrite_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "ws.json"
            target.write_text("x", encoding="utf-8")
            buf = io.StringIO()
            rc = ws.main(["--output", str(target)], out=buf)
            self.assertEqual(rc, 1)
            parsed = json.loads(buf.getvalue())
            self.assertFalse(parsed["ok"])

    def test_main_csv_and_json_flags_mutually_exclusive(self) -> None:
        # argparse should raise SystemExit on conflict.
        buf = io.StringIO()
        with self.assertRaises(SystemExit):
            ws.main(["--csv", "--json"], out=buf)


# ---------------------------------------------------------------------------
# Module surface — read-only contract assertions
# ---------------------------------------------------------------------------


class TestWorksheetModuleSurface(unittest.TestCase):

    def _path(self) -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "scripts" / "daily_reviewed_candidate_worksheet.py"
        )

    def _read(self) -> str:
        return self._path().read_text(encoding="utf-8")

    def _imported_modules(self) -> set[str]:
        import ast
        tree = ast.parse(self._read())
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.add(node.module)
        return names

    def _code_without_docstrings(self) -> str:
        """Return module source with module/function/class docstrings
        stripped, so substring checks fire only on real code rather
        than on prose in the docstring header.
        """
        import ast
        text = self._read()
        tree = ast.parse(text)
        spans: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                body = getattr(node, "body", None)
                if not body:
                    continue
                first = body[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    spans.append(
                        (first.value.lineno, first.value.end_lineno or first.value.lineno)
                    )
        if not spans:
            return text
        keep_lines: list[str] = []
        for i, line in enumerate(text.splitlines(), start=1):
            if any(s <= i <= e for s, e in spans):
                continue
            keep_lines.append(line)
        return "\n".join(keep_lines)

    def test_no_provider_or_fastapi_imports(self) -> None:
        modules = self._imported_modules()
        forbidden_prefixes = (
            "fastapi", "yfinance", "market_data", "openai",
            "anthropic", "api", "routes",
        )
        for m in modules:
            head = m.split(".", 1)[0]
            self.assertNotIn(
                head, forbidden_prefixes,
                f"worksheet imports forbidden module {m!r}",
            )

    def test_no_db_writes_in_code(self) -> None:
        body = self._code_without_docstrings()
        for banned in (
            "save_event(",
            "INSERT INTO",
            "UPDATE ",
            "DELETE FROM",
            "events.db",
        ):
            self.assertNotIn(
                banned, body,
                f"worksheet contains forbidden DB write surface: {banned!r}",
            )

    def test_does_not_reference_news_inbox_outside_docstrings(self) -> None:
        body = self._code_without_docstrings()
        self.assertNotIn(
            "news_inbox", body,
            "worksheet code references news_inbox outside its "
            "docstring header — the script must not read or write "
            "the inbox",
        )

    def test_does_not_auto_generate_candidate_id_in_code(self) -> None:
        body = self._code_without_docstrings()
        # Guards against a future edit that derives a candidate_id
        # from a hash, uuid, or timestamp call.
        for banned in (
            "uuid.",
            "uuid4(",
            "hashlib.",
            "secrets.",
        ):
            self.assertNotIn(
                banned, body,
                f"worksheet code uses {banned!r} — candidate_id "
                "must remain operator-filled, never derived",
            )

    def test_conservative_wording_no_banned_tokens_outside_header(self) -> None:
        text = self._read().lower()
        # The conservative-wording header lists banned tokens by
        # name; strip from the header marker through the next blank-
        # line paragraph break before the substring scan.
        marker = "banned tokens in any prose this script emits:"
        if marker in text:
            i = text.index(marker)
            paragraph_break = text.find("\n\n", i)
            body = text[:i] + text[(paragraph_break or len(text)):]
        else:
            body = text
        body = body.replace("conservative wording", "")
        for banned in (
            "proof",
            "proven",
            "validated",
            "automatically",
            "alpha generated",
            "guaranteed",
            "correct ticker",
        ):
            self.assertNotIn(
                banned, body,
                f"worksheet prose contains banned token {banned!r}",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
