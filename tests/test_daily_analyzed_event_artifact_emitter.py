"""Tests for ``scripts/daily_analyzed_event_artifact_emitter.py``.

The Daily analyzed-event artifact emitter reads operator-reviewed
candidate rows (CSV or JSON) and writes one
``analyzed_event_artifact_<candidate_id>.json`` per included
candidate.  These tests pin:

* the dry-run preview default has no filesystem side effect;
* CSV and JSON input loaders return the same row shape;
* the ``include_in_daily_section_c`` operator gate admits only
  ``yes`` / ``true`` (case-insensitive);
* missing or invalid required fields surface as envelope errors and
  the row is skipped;
* the per-row artifact body carries the ten required fields, with
  ``artifact_type`` pinned to ``"analyzed_event_artifact"``;
* ``--output-dir`` is the only write path and refuses to overwrite
  existing artifacts unless ``--overwrite`` is supplied;
* the module imports nothing that would breach the read-only
  contract (no DB writes, no provider/yfinance/LLM/FastAPI surface);
* conservative wording — banned tokens never appear in the module
  text.
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

from scripts import daily_analyzed_event_artifact_emitter as emitter  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _good_row(
    *,
    candidate_id: str = "cid-001",
    headline: str = "OPEC extends voluntary cuts",
    event_date: str = "2026-05-12",
    mechanism_family: str = "supply_shock",
    primary_ticker: str = "XOM",
    benchmark_ticker: str = "XLE",
    market_relevance: Any = "0.85",
    inclusion_reason: str = "operator review",
    operator_notes: str = "",
    include_in_daily_section_c: str = "yes",
) -> dict[str, Any]:
    return {
        "candidate_id":               candidate_id,
        "headline":                   headline,
        "event_date":                 event_date,
        "mechanism_family":           mechanism_family,
        "primary_ticker":             primary_ticker,
        "benchmark_ticker":           benchmark_ticker,
        "market_relevance":           market_relevance,
        "inclusion_reason":           inclusion_reason,
        "operator_notes":             operator_notes,
        "include_in_daily_section_c": include_in_daily_section_c,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv
    fields = [
        "candidate_id",
        "headline",
        "event_date",
        "mechanism_family",
        "primary_ticker",
        "benchmark_ticker",
        "market_relevance",
        "inclusion_reason",
        "operator_notes",
        "include_in_daily_section_c",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


# ---------------------------------------------------------------------------
# Dry-run preview default
# ---------------------------------------------------------------------------


class TestDryRunPreview(unittest.TestCase):

    def test_no_input_returns_empty_preview_with_ok_true(self) -> None:
        env = emitter.run_emitter()
        self.assertTrue(env["ok"])
        self.assertEqual(env["loaded_row_count"], 0)
        self.assertEqual(env["emitted_count"], 0)
        self.assertEqual(env["skipped_count"], 0)
        self.assertEqual(env["candidates"], [])
        self.assertTrue(env["dry_run"])
        self.assertIsNone(env["input_path"])
        self.assertIsNone(env["output_dir"])
        self.assertEqual(env["artifact_type"], "daily_analyzed_event_artifact_emitter_run")
        joined = " ".join(env["warnings"])
        self.assertIn("no --input", joined)
        self.assertIn("dry-run", joined)

    def test_no_filesystem_writes_in_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.csv"
            _write_csv(in_path, [_good_row()])
            entries_before = sorted(Path(tmp).iterdir())
            env = emitter.run_emitter(input_path=str(in_path))
            entries_after = sorted(Path(tmp).iterdir())
            self.assertEqual(entries_before, entries_after)
            self.assertTrue(env["dry_run"])
            # The would-emit body is in the envelope for preview.
            self.assertEqual(env["emitted_count"], 1)
            self.assertEqual(env["candidates"][0]["status"], "would_emit")
            self.assertIsNotNone(env["candidates"][0]["artifact"])

    def test_main_prints_json_and_returns_zero_without_input(self) -> None:
        buf = io.StringIO()
        rc = emitter.main([], out=buf)
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["loaded_row_count"], 0)


# ---------------------------------------------------------------------------
# Input loading — CSV and JSON
# ---------------------------------------------------------------------------


class TestInputLoading(unittest.TestCase):

    def test_loads_csv_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.csv"
            _write_csv(in_path, [_good_row(candidate_id="a"),
                                 _good_row(candidate_id="b")])
            env = emitter.run_emitter(input_path=str(in_path))
            self.assertEqual(env["loaded_row_count"], 2)
            self.assertEqual(env["emitted_count"], 2)
            ids = {c["candidate_id"] for c in env["candidates"]}
            self.assertEqual(ids, {"a", "b"})

    def test_loads_json_list_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.json"
            _write_json(in_path, [_good_row(candidate_id="a")])
            env = emitter.run_emitter(input_path=str(in_path))
            self.assertEqual(env["loaded_row_count"], 1)
            self.assertEqual(env["emitted_count"], 1)

    def test_loads_json_mapping_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.json"
            in_path.write_text(
                json.dumps({"candidates": [_good_row(candidate_id="m")]}),
                encoding="utf-8",
            )
            env = emitter.run_emitter(input_path=str(in_path))
            self.assertEqual(env["loaded_row_count"], 1)
            self.assertEqual(env["emitted_count"], 1)

    def test_missing_input_file_surfaces_error(self) -> None:
        env = emitter.run_emitter(input_path="/no/such/path.csv")
        self.assertFalse(env["ok"])
        self.assertTrue(env["errors"])
        self.assertIn("does not exist", env["errors"][0])

    def test_unsupported_input_extension_surfaces_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "rev.txt"
            bad.write_text("nope", encoding="utf-8")
            env = emitter.run_emitter(input_path=str(bad))
            self.assertFalse(env["ok"])
            self.assertTrue(any(
                "unsupported --input extension" in e for e in env["errors"]
            ))

    def test_malformed_json_surfaces_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.json"
            in_path.write_text("not json {", encoding="utf-8")
            env = emitter.run_emitter(input_path=str(in_path))
            self.assertFalse(env["ok"])
            self.assertTrue(any(
                "failed to parse --input JSON" in e for e in env["errors"]
            ))

    def test_json_top_level_not_list_or_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.json"
            in_path.write_text("42", encoding="utf-8")
            env = emitter.run_emitter(input_path=str(in_path))
            self.assertFalse(env["ok"])
            self.assertTrue(any(
                "top level is not a list or mapping" in e
                for e in env["errors"]
            ))

    def test_json_mapping_without_candidates_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.json"
            in_path.write_text(json.dumps({"other": []}), encoding="utf-8")
            env = emitter.run_emitter(input_path=str(in_path))
            self.assertFalse(env["ok"])
            self.assertTrue(any(
                "no 'candidates' list" in e for e in env["errors"]
            ))

    def test_json_row_that_is_not_mapping_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.json"
            in_path.write_text(
                json.dumps([_good_row(), "not a row"]),
                encoding="utf-8",
            )
            env = emitter.run_emitter(input_path=str(in_path))
            # First row good, second is reported as a row error but
            # does not block emission of the good row.
            self.assertEqual(env["loaded_row_count"], 1)
            self.assertFalse(env["ok"])
            self.assertTrue(any(
                "row 1 is not a mapping" in e for e in env["errors"]
            ))


# ---------------------------------------------------------------------------
# Operator emit-gate and per-row validation
# ---------------------------------------------------------------------------


class TestRowEvaluation(unittest.TestCase):

    def _run_single(self, row: dict[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.json"
            _write_json(in_path, [row])
            return emitter.run_emitter(input_path=str(in_path))

    def test_include_flag_yes_admits_row(self) -> None:
        env = self._run_single(_good_row(include_in_daily_section_c="yes"))
        self.assertEqual(env["candidates"][0]["status"], "would_emit")

    def test_include_flag_true_admits_row(self) -> None:
        env = self._run_single(_good_row(include_in_daily_section_c="true"))
        self.assertEqual(env["candidates"][0]["status"], "would_emit")

    def test_include_flag_is_case_insensitive(self) -> None:
        for token in ("YES", "Yes", "TRUE", "True", "  yes  "):
            env = self._run_single(
                _good_row(include_in_daily_section_c=token),
            )
            self.assertEqual(
                env["candidates"][0]["status"], "would_emit",
                f"token {token!r} should admit the row",
            )

    def test_include_flag_no_skips_row_without_error(self) -> None:
        env = self._run_single(_good_row(include_in_daily_section_c="no"))
        self.assertEqual(env["candidates"][0]["status"], "skipped")
        self.assertIn(
            "include_in_daily_section_c", env["candidates"][0]["reason"],
        )
        # Skipping a not-yet-ready row is not an envelope error.
        self.assertTrue(env["ok"])
        self.assertEqual(env["errors"], [])

    def test_include_flag_blank_skips_row_without_error(self) -> None:
        env = self._run_single(_good_row(include_in_daily_section_c=""))
        self.assertEqual(env["candidates"][0]["status"], "skipped")
        self.assertTrue(env["ok"])

    def test_missing_candidate_id_is_skipped_and_errored(self) -> None:
        env = self._run_single(_good_row(candidate_id=""))
        c = env["candidates"][0]
        self.assertEqual(c["status"], "skipped")
        self.assertIn("candidate_id", c["missing_fields"])
        self.assertFalse(env["ok"])

    def test_missing_mechanism_family_is_skipped_and_errored(self) -> None:
        env = self._run_single(_good_row(mechanism_family=""))
        c = env["candidates"][0]
        self.assertEqual(c["status"], "skipped")
        self.assertIn("mechanism_family", c["missing_fields"])
        self.assertFalse(env["ok"])

    def test_mechanism_family_none_sentinel_is_treated_as_missing(self) -> None:
        env = self._run_single(_good_row(mechanism_family="none"))
        c = env["candidates"][0]
        self.assertEqual(c["status"], "skipped")
        self.assertIn("mechanism_family", c["missing_fields"])
        self.assertFalse(env["ok"])

    def test_mechanism_family_none_case_insensitive(self) -> None:
        env = self._run_single(_good_row(mechanism_family="NONE"))
        c = env["candidates"][0]
        self.assertEqual(c["status"], "skipped")
        self.assertIn("mechanism_family", c["missing_fields"])

    def test_missing_primary_ticker_is_skipped_and_errored(self) -> None:
        env = self._run_single(_good_row(primary_ticker=""))
        c = env["candidates"][0]
        self.assertEqual(c["status"], "skipped")
        self.assertIn("primary_ticker", c["missing_fields"])
        self.assertFalse(env["ok"])

    def test_missing_benchmark_ticker_is_skipped_and_errored(self) -> None:
        env = self._run_single(_good_row(benchmark_ticker=""))
        c = env["candidates"][0]
        self.assertEqual(c["status"], "skipped")
        self.assertIn("benchmark_ticker", c["missing_fields"])
        self.assertFalse(env["ok"])

    def test_blank_required_field_treated_as_missing(self) -> None:
        env = self._run_single(_good_row(primary_ticker="   "))
        c = env["candidates"][0]
        self.assertEqual(c["status"], "skipped")
        self.assertIn("primary_ticker", c["missing_fields"])

    def test_multiple_missing_fields_listed(self) -> None:
        env = self._run_single(
            _good_row(mechanism_family="", primary_ticker="", benchmark_ticker=""),
        )
        c = env["candidates"][0]
        self.assertEqual(c["status"], "skipped")
        self.assertEqual(
            set(c["missing_fields"]),
            {"mechanism_family", "primary_ticker", "benchmark_ticker"},
        )


# ---------------------------------------------------------------------------
# Artifact body shape
# ---------------------------------------------------------------------------


class TestArtifactBodyShape(unittest.TestCase):

    def test_artifact_body_carries_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.json"
            _write_json(in_path, [_good_row(candidate_id="cid-shape")])
            env = emitter.run_emitter(input_path=str(in_path))
            body = env["candidates"][0]["artifact"]
            self.assertIsInstance(body, dict)
            expected = {
                "candidate_id",
                "headline",
                "event_date",
                "mechanism_family",
                "primary_ticker",
                "benchmark_ticker",
                "market_relevance",
                "inclusion_reason",
                "operator_notes",
                "artifact_type",
            }
            self.assertEqual(set(body.keys()), expected)
            self.assertEqual(body["artifact_type"], "analyzed_event_artifact")
            self.assertEqual(body["candidate_id"], "cid-shape")

    def test_artifact_body_strips_required_gate_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.json"
            _write_json(in_path, [_good_row(
                mechanism_family="  supply_shock  ",
                primary_ticker="  XOM ",
                benchmark_ticker=" XLE  ",
            )])
            env = emitter.run_emitter(input_path=str(in_path))
            body = env["candidates"][0]["artifact"]
            self.assertEqual(body["mechanism_family"], "supply_shock")
            self.assertEqual(body["primary_ticker"], "XOM")
            self.assertEqual(body["benchmark_ticker"], "XLE")

    def test_artifact_body_passes_through_free_text_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.json"
            _write_json(in_path, [_good_row(
                headline="  Spaced headline  ",
                operator_notes="line 1\nline 2",
                inclusion_reason="operator review",
            )])
            env = emitter.run_emitter(input_path=str(in_path))
            body = env["candidates"][0]["artifact"]
            # Free-text fields are not stripped — operator formatting
            # survives round-trip.
            self.assertEqual(body["headline"], "  Spaced headline  ")
            self.assertEqual(body["operator_notes"], "line 1\nline 2")
            self.assertEqual(body["inclusion_reason"], "operator review")

    def test_artifact_body_preserves_market_relevance_as_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "rev.json"
            _write_json(in_path, [_good_row(market_relevance=0.42)])
            env = emitter.run_emitter(input_path=str(in_path))
            body = env["candidates"][0]["artifact"]
            self.assertEqual(body["market_relevance"], 0.42)

    def test_artifact_body_satisfies_gate_predicate(self) -> None:
        # The whole point of the emitter is that the emitted artifact
        # is admissible by ``routes/daily_artifact_gate``.  Wire the
        # two together end-to-end.
        from routes import daily_artifact_gate as gate
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            in_path = tmp_dir / "rev.json"
            _write_json(in_path, [_good_row(candidate_id="cid-gate")])
            env = emitter.run_emitter(
                input_path=str(in_path),
                output_dir=str(tmp_dir),
            )
            self.assertTrue(env["ok"])
            self.assertEqual(env["emitted_count"], 1)
            self.assertEqual(env["candidates"][0]["status"], "emitted")
            # The gate predicate now admits the card.
            card = {"candidate_id": "cid-gate"}
            self.assertTrue(
                gate.is_artifact_backed_daily_card(
                    card, artifact_dir=tmp_dir,
                )
            )


# ---------------------------------------------------------------------------
# Output-file persistence
# ---------------------------------------------------------------------------


class TestOutputDirPersistence(unittest.TestCase):

    def test_writes_one_file_per_emitted_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            in_path = tmp_dir / "rev.json"
            out_dir = tmp_dir / "artifacts"
            rows = [
                _good_row(candidate_id="cid-a"),
                _good_row(candidate_id="cid-b"),
            ]
            _write_json(in_path, rows)
            env = emitter.run_emitter(
                input_path=str(in_path),
                output_dir=str(out_dir),
            )
            self.assertTrue(env["ok"])
            self.assertFalse(env["dry_run"])
            self.assertEqual(env["emitted_count"], 2)
            files = sorted(p.name for p in out_dir.iterdir())
            self.assertEqual(
                files,
                [
                    "analyzed_event_artifact_cid-a.json",
                    "analyzed_event_artifact_cid-b.json",
                ],
            )
            for outcome in env["candidates"]:
                self.assertEqual(outcome["status"], "emitted")
                self.assertIn("written_path", outcome)

    def test_artifact_file_content_matches_envelope_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            in_path = tmp_dir / "rev.json"
            out_dir = tmp_dir / "artifacts"
            _write_json(in_path, [_good_row(candidate_id="cid-1")])
            env = emitter.run_emitter(
                input_path=str(in_path),
                output_dir=str(out_dir),
            )
            on_disk = json.loads(
                (out_dir / "analyzed_event_artifact_cid-1.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(env["candidates"][0]["artifact"], on_disk)

    def test_refuses_to_overwrite_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            in_path = tmp_dir / "rev.json"
            out_dir = tmp_dir / "artifacts"
            _write_json(in_path, [_good_row(candidate_id="cid-x")])

            env1 = emitter.run_emitter(
                input_path=str(in_path), output_dir=str(out_dir),
            )
            self.assertTrue(env1["ok"])
            self.assertEqual(env1["emitted_count"], 1)
            original = (
                out_dir / "analyzed_event_artifact_cid-x.json"
            ).read_bytes()

            # Re-run without --overwrite.  The artifact file already
            # exists; the emitter refuses to replace it.
            env2 = emitter.run_emitter(
                input_path=str(in_path),
                output_dir=str(out_dir),
                overwrite=False,
            )
            self.assertFalse(env2["ok"])
            self.assertEqual(env2["candidates"][0]["status"], "skipped")
            self.assertIn("refusing to overwrite", env2["candidates"][0]["reason"])
            # File is untouched.
            self.assertEqual(
                (out_dir / "analyzed_event_artifact_cid-x.json").read_bytes(),
                original,
            )

    def test_overwrites_with_overwrite_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            in_path = tmp_dir / "rev.json"
            out_dir = tmp_dir / "artifacts"
            _write_json(in_path, [_good_row(
                candidate_id="cid-y", operator_notes="first",
            )])
            emitter.run_emitter(
                input_path=str(in_path), output_dir=str(out_dir),
            )

            _write_json(in_path, [_good_row(
                candidate_id="cid-y", operator_notes="second",
            )])
            env = emitter.run_emitter(
                input_path=str(in_path),
                output_dir=str(out_dir),
                overwrite=True,
            )
            self.assertTrue(env["ok"])
            self.assertEqual(env["emitted_count"], 1)
            on_disk = json.loads(
                (out_dir / "analyzed_event_artifact_cid-y.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(on_disk["operator_notes"], "second")

    def test_does_not_write_artifact_for_skipped_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            in_path = tmp_dir / "rev.json"
            out_dir = tmp_dir / "artifacts"
            _write_json(in_path, [
                _good_row(candidate_id="ok"),
                _good_row(candidate_id="bad", mechanism_family=""),
                _good_row(candidate_id="off",
                          include_in_daily_section_c="no"),
            ])
            env = emitter.run_emitter(
                input_path=str(in_path),
                output_dir=str(out_dir),
            )
            files = sorted(p.name for p in out_dir.iterdir())
            self.assertEqual(
                files, ["analyzed_event_artifact_ok.json"],
            )
            # Envelope sees one good row plus one error from the
            # missing-mechanism_family row.  The include=no row is a
            # silent skip.
            self.assertEqual(env["emitted_count"], 1)
            self.assertFalse(env["ok"])
            self.assertTrue(any(
                "mechanism_family" in e for e in env["errors"]
            ))


# ---------------------------------------------------------------------------
# Module surface — read-only contract assertions
# ---------------------------------------------------------------------------


class TestEmitterModuleSurface(unittest.TestCase):

    def _path(self) -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "scripts" / "daily_analyzed_event_artifact_emitter.py"
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
        """Return the module source with module/function/class
        docstrings stripped, so substring checks fire only on real
        code rather than on prose in the docstring header.
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
        lines = text.splitlines()
        for i, line in enumerate(lines, start=1):
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
                f"emitter imports forbidden module {m!r}",
            )

    def test_does_not_reference_news_inbox_outside_docstrings(self) -> None:
        body = self._code_without_docstrings()
        self.assertNotIn(
            "news_inbox", body,
            "emitter code references news_inbox outside its docstring "
            "header — the script must not read or write the inbox",
        )

    def test_no_db_writes(self) -> None:
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
                f"emitter contains forbidden DB write surface: {banned!r}",
            )

    def test_conservative_wording_no_banned_tokens(self) -> None:
        text = self._read().lower()
        # ``banned tokens`` and the word ``validated`` appear inside
        # the module's own conservative-wording header (which lists
        # the banned tokens by name).  Strip that header before the
        # search so the audit fires only on real claims.
        header_marker_open = "banned tokens in any prose this script emits:"
        if header_marker_open in text:
            i = text.index(header_marker_open)
            # The header runs through a clear sentence end; cut from
            # the marker to the next blank-line paragraph break.
            paragraph_break = text.find("\n\n", i)
            body = text[:i] + text[(paragraph_break or len(text)):]
        else:
            body = text
        # Strip the conservative-wording section heading too.
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
                f"emitter prose contains banned token {banned!r}",
            )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLIPlumbing(unittest.TestCase):

    def test_main_returns_zero_on_clean_dry_run(self) -> None:
        buf = io.StringIO()
        rc = emitter.main(["--json"], out=buf)
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertTrue(parsed["ok"])

    def test_main_returns_one_on_missing_input(self) -> None:
        buf = io.StringIO()
        rc = emitter.main(["--input", "/no/such/file.csv"], out=buf)
        self.assertEqual(rc, 1)
        parsed = json.loads(buf.getvalue())
        self.assertFalse(parsed["ok"])

    def test_main_writes_artifacts_with_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            in_path = tmp_dir / "rev.csv"
            out_dir = tmp_dir / "out"
            _write_csv(in_path, [_good_row(candidate_id="cli-1")])
            buf = io.StringIO()
            rc = emitter.main(
                ["--input", str(in_path), "--output-dir", str(out_dir)],
                out=buf,
            )
            self.assertEqual(rc, 0)
            self.assertTrue(
                (out_dir / "analyzed_event_artifact_cli-1.json").exists()
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
