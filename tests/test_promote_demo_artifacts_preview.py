"""Tests for ``scripts/promote_demo_artifacts_preview.py``.

Pin the contract:

* Read-only by default.  No filesystem writes unless ``--output-dir``
  is explicitly supplied; ``--overwrite`` is required before any
  existing destination file may be replaced.
* No DB, no provider (yfinance / anthropic / openai), no LLM, no
  FastAPI surface.  The helper never stages or commits to git.
* The helper only touches a small whitelist of demo-relevant files
  under ``artifacts/`` — it never copies the directory wholesale.
  In particular, it MUST pick up:
    - every match of ``analyzed_event_artifact_daily-demo-*.json``
    - ``freeze_candidate_evidence.json`` (when present)
    - ``daily_reviewed_candidates.csv`` (when present)
  …and MUST NOT pick up unrelated artifacts (XLE backfill packets,
  section-C diagnostics, random text files).
* Conservative wording: the preview must surface a "these are demo
  inputs, not research truth" disclaimer in its warnings.
* Output dict has EXACTLY these 6 keys::

      ok, source_files, proposed_output_files,
      missing_required_files, warnings, errors

* ``ok`` is True iff ``errors`` is empty.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import promote_demo_artifacts_preview as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "source_files",
    "proposed_output_files",
    "missing_required_files",
    "warnings",
    "errors",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_artifacts_dir(
    tmpdir: str,
    *,
    include_daily: bool = True,
    include_freeze: bool = True,
    include_csv: bool = True,
    extra_files: list[str] | None = None,
) -> str:
    art_dir = Path(tmpdir) / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    if include_daily:
        for i in (1, 2, 3):
            (art_dir / f"analyzed_event_artifact_daily-demo-{i:03d}.json"
             ).write_text("{\"demo\": true}", encoding="utf-8")
    if include_freeze:
        (art_dir / "freeze_candidate_evidence.json").write_text(
            "{}", encoding="utf-8",
        )
    if include_csv:
        (art_dir / "daily_reviewed_candidates.csv").write_text(
            "event_id,headline\n", encoding="utf-8",
        )
    for name in (extra_files or []):
        (art_dir / name).write_text("X", encoding="utf-8")
    return str(art_dir)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_required_keys_present_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
            self.assertTrue(report["ok"], report["errors"])

    def test_required_keys_when_inputs_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(
                tmp,
                include_daily=False, include_freeze=False, include_csv=False,
            )
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))

    def test_required_keys_when_artifacts_dir_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "does-not-exist")
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=missing,
            )
            self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))


# ---------------------------------------------------------------------------
# Source file discovery — must pick up the three whitelisted demo inputs
# ---------------------------------------------------------------------------


class TestSourceFileDiscovery(unittest.TestCase):
    def test_includes_three_daily_artifacts_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            paths = [s["path"] for s in report["source_files"]]
            for i in (1, 2, 3):
                self.assertTrue(
                    any(
                        p.endswith(f"daily-demo-{i:03d}.json")
                        for p in paths
                    ),
                    f"daily-demo-{i:03d}.json not in source_files: {paths}",
                )

    def test_includes_freeze_candidate_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            paths = [s["path"] for s in report["source_files"]]
            self.assertTrue(
                any(p.endswith("freeze_candidate_evidence.json")
                    for p in paths),
                f"freeze_candidate_evidence.json missing: {paths}",
            )

    def test_includes_reviewed_candidates_csv_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            paths = [s["path"] for s in report["source_files"]]
            self.assertTrue(
                any(p.endswith("daily_reviewed_candidates.csv")
                    for p in paths),
                f"daily_reviewed_candidates.csv missing: {paths}",
            )

    def test_does_not_pick_up_unrelated_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp, extra_files=[
                "section_c_regression_smoke.json",
                "xle_backfill_request_packet.json",
                "short_horizon_review_top10.csv",
                "random_unrelated.txt",
            ])
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            paths = [s["path"] for s in report["source_files"]]
            for forbidden in (
                "section_c_regression_smoke.json",
                "xle_backfill_request_packet.json",
                "short_horizon_review_top10.csv",
                "random_unrelated.txt",
            ):
                self.assertFalse(
                    any(p.endswith(forbidden) for p in paths),
                    f"unrelated file {forbidden!r} leaked into source_files",
                )

    def test_source_entries_carry_kind_tag(self) -> None:
        """Each source entry must declare what kind of input it is so
        the demo wiring can branch on it deterministically."""
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            for entry in report["source_files"]:
                self.assertIn("kind", entry)
                self.assertIn("path", entry)
                self.assertIsInstance(entry["kind"], str)


# ---------------------------------------------------------------------------
# Missing-file accounting
# ---------------------------------------------------------------------------


class TestMissingRequiredFiles(unittest.TestCase):
    def test_missing_freeze_listed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp, include_freeze=False)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            missing = " | ".join(report["missing_required_files"])
            self.assertIn("freeze_candidate_evidence.json", missing)

    def test_missing_csv_listed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp, include_csv=False)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            missing = " | ".join(report["missing_required_files"])
            self.assertIn("daily_reviewed_candidates.csv", missing)

    def test_missing_daily_listed_when_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp, include_daily=False)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            missing = " | ".join(report["missing_required_files"])
            self.assertIn("analyzed_event_artifact_daily-demo", missing)

    def test_no_missing_when_everything_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            self.assertEqual(
                report["missing_required_files"], [],
                f"expected no missing files, got "
                f"{report['missing_required_files']}",
            )


# ---------------------------------------------------------------------------
# Preview-by-default — no writes unless --output-dir is supplied
# ---------------------------------------------------------------------------


class TestPreviewByDefault(unittest.TestCase):
    def test_no_output_dir_creates_no_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            outdir = Path(tmp) / "would_be_demo_out"
            cli.run_promote_demo_artifacts_preview(artifacts_dir=art)
            self.assertFalse(
                outdir.exists(),
                "preview mode must never create an output directory",
            )

    def test_proposed_output_files_populated_in_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            self.assertGreater(
                len(report["proposed_output_files"]), 0,
                "preview must list proposed destination entries even "
                "without --output-dir",
            )
            for entry in report["proposed_output_files"]:
                self.assertIn("source", entry)
                self.assertIn("destination", entry)

    def test_preview_does_not_mutate_source_files(self) -> None:
        """The helper must never modify source files even by accident."""
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            freeze = Path(art) / "freeze_candidate_evidence.json"
            before = freeze.read_bytes()
            cli.run_promote_demo_artifacts_preview(artifacts_dir=art)
            self.assertEqual(
                freeze.read_bytes(), before,
                "source bytes must be preserved during preview",
            )


# ---------------------------------------------------------------------------
# Write mode (--output-dir)
# ---------------------------------------------------------------------------


class TestWriteMode(unittest.TestCase):
    def test_output_dir_copies_whitelisted_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            outdir = str(Path(tmp) / "demo_out")
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art, output_dir=outdir,
            )
            self.assertTrue(report["ok"], report["errors"])
            for i in (1, 2, 3):
                self.assertTrue(
                    (Path(outdir)
                     / f"analyzed_event_artifact_daily-demo-{i:03d}.json"
                     ).exists(),
                    f"daily-demo-{i:03d}.json not copied to {outdir}",
                )
            self.assertTrue(
                (Path(outdir) / "freeze_candidate_evidence.json").exists()
            )
            self.assertTrue(
                (Path(outdir) / "daily_reviewed_candidates.csv").exists()
            )

    def test_output_dir_does_not_copy_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp, extra_files=[
                "section_c_regression_smoke.json",
                "random_unrelated.txt",
            ])
            outdir = str(Path(tmp) / "demo_out")
            cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art, output_dir=outdir,
            )
            self.assertFalse(
                (Path(outdir) / "section_c_regression_smoke.json").exists(),
                "unrelated artifact must not be copied",
            )
            self.assertFalse(
                (Path(outdir) / "random_unrelated.txt").exists(),
                "random file must not be copied",
            )

    def test_refuses_overwrite_when_dest_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            outdir = Path(tmp) / "demo_out"
            outdir.mkdir()
            existing = outdir / "freeze_candidate_evidence.json"
            existing.write_text("original-bytes", encoding="utf-8")
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art, output_dir=str(outdir),
            )
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("overwrite", joined)
            self.assertEqual(
                existing.read_text(encoding="utf-8"), "original-bytes",
                "existing destination must NOT be overwritten without "
                "--overwrite",
            )

    def test_overwrite_flag_allows_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            outdir = Path(tmp) / "demo_out"
            outdir.mkdir()
            existing = outdir / "freeze_candidate_evidence.json"
            existing.write_text("original-bytes", encoding="utf-8")
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art, output_dir=str(outdir), overwrite=True,
            )
            self.assertTrue(report["ok"], report["errors"])
            self.assertNotEqual(
                existing.read_text(encoding="utf-8"), "original-bytes",
                "--overwrite must allow replacement of an existing dest",
            )

    def test_output_dir_created_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            outdir = Path(tmp) / "newly_created_demo_out"
            self.assertFalse(outdir.exists())
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art, output_dir=str(outdir),
            )
            self.assertTrue(report["ok"], report["errors"])
            self.assertTrue(outdir.exists())


# ---------------------------------------------------------------------------
# Conservative language — preview must say these are demo inputs
# ---------------------------------------------------------------------------


class TestConservativeLanguage(unittest.TestCase):
    def test_preview_carries_demo_input_disclaimer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            joined = " | ".join(report["warnings"]).lower()
            self.assertIn("demo", joined)
            self.assertIn(
                "not research truth", joined,
                "preview must clearly state these are demo inputs, "
                f"not research truth — got warnings: {report['warnings']}",
            )

    def test_no_overclaim_tokens_in_emitted_text(self) -> None:
        """The helper's own output must not parrot overclaim language."""
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            report = cli.run_promote_demo_artifacts_preview(
                artifacts_dir=art,
            )
            joined = " | ".join(
                list(report["warnings"]) + list(report["errors"])
                + list(report["missing_required_files"])
            ).lower()
            for token in ("proven", "guaranteed", "alpha generated"):
                self.assertNotIn(
                    token, joined,
                    f"banned overclaim token {token!r} appeared in "
                    f"helper's own output",
                )


# ---------------------------------------------------------------------------
# Import isolation — no paid surfaces, no FastAPI, no git
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_paid_or_app_attrs(self) -> None:
        for attr in ("yfinance", "anthropic", "openai", "fastapi"):
            self.assertFalse(
                hasattr(cli, attr),
                f"helper must not bind {attr} as a module attr",
            )

    def test_module_does_not_import_git(self) -> None:
        """The helper must never reach for ``git`` programmatically;
        promotion is a copy, not a commit."""
        with open(cli.__file__, "r", encoding="utf-8") as fh:
            src = fh.read()
        for forbidden in ("git add", "git commit", "git stage"):
            self.assertNotIn(
                forbidden, src,
                f"helper source mentions {forbidden!r}; promotion must "
                f"not touch git",
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_json_emits_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            rc, output = self._run([
                "--artifacts-dir", art, "--json",
            ])
            parsed = json.loads(output)
            self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
            self.assertEqual(rc, 0)
            self.assertTrue(parsed["ok"], parsed["errors"])

    def test_text_render_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            art = _make_artifacts_dir(tmp)
            rc, output = self._run(["--artifacts-dir", art])
            self.assertEqual(rc, 0)
            self.assertIn("demo", output.lower())

    def test_cli_default_artifacts_dir_smokes_clean(self) -> None:
        """CLI must run without --artifacts-dir against the live
        repository ``artifacts/`` directory; this matches the
        verification command in the task spec."""
        rc, output = self._run(["--json"])
        # We do not assert ok=True here because the live tree may be
        # incomplete during interim development; we DO assert the
        # output shape so the script never crashes.
        parsed = json.loads(output)
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))


if __name__ == "__main__":
    unittest.main()
