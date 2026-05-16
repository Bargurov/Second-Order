"""Tests for ``scripts/daily_artifact_gate_fixture_smoke.py``.

The fixture smoke is a read-only sanity check that proves the
Daily Section C artifact gate
(:mod:`routes.daily_artifact_gate`) can produce one admitted
candidate and one held-for-review candidate against a fresh temp
artifact directory.  It must never touch the real ``artifacts/``
directory, the events DB, ``yfinance``, ``market_data``, an LLM,
a paid provider, or any FastAPI surface.

Pin the contract:

* Read-only by construction.  No DB writes; no
  ``yfinance``, ``market_data``, LLM, paid provider, or FastAPI
  surface imported at module load.
* Output dict has EXACTLY these 8 keys::

    ok, candidates_checked, admitted_count,
    held_for_review_count, admitted_candidates,
    held_candidates, warnings, errors

* Default invocation has no filesystem side effect outside
  Python's tempdir; ``--output`` is the only way to write a file
  and the script refuses to overwrite an existing path.
* The smoke creates exactly two synthetic Daily cards and one
  matching ``analyzed_event_artifact_<cid>.json`` under a fresh
  ``tempfile.TemporaryDirectory`` — never under ``artifacts/``.
* When the gate behaves as designed, ``admitted_count == 1`` and
  ``held_for_review_count == 1`` and ``ok == True``.
* Conservative wording — banned tokens absent from every rendered
  text and JSON envelope.
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
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import daily_artifact_gate_fixture_smoke as smoke  # noqa: E402


_REQUIRED_TOP_KEYS: tuple[str, ...] = (
    "ok",
    "candidates_checked",
    "admitted_count",
    "held_for_review_count",
    "admitted_candidates",
    "held_candidates",
    "warnings",
    "errors",
)


_BANNED_TOKENS: tuple[str, ...] = (
    "proof",
    "proven",
    "guaranteed",
    "automatically",
    "validated",
    "alpha generated",
    "correct ticker",
    "definitely",
    "approved",
    "production ready",
    "production-ready",
    "demo_ready",
    "demo-ready",
)


# ---------------------------------------------------------------------------
# Pure-compute behavior
# ---------------------------------------------------------------------------


class TestRunFixtureSmoke(unittest.TestCase):

    def test_returns_required_top_level_keys(self) -> None:
        report = smoke.run_daily_artifact_gate_fixture_smoke()
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))

    def test_admits_one_and_holds_one(self) -> None:
        report = smoke.run_daily_artifact_gate_fixture_smoke()
        self.assertEqual(report["candidates_checked"], 2)
        self.assertEqual(report["admitted_count"], 1)
        self.assertEqual(report["held_for_review_count"], 1)

    def test_admitted_and_held_lists_match_counts(self) -> None:
        report = smoke.run_daily_artifact_gate_fixture_smoke()
        self.assertIsInstance(report["admitted_candidates"], list)
        self.assertIsInstance(report["held_candidates"], list)
        self.assertEqual(len(report["admitted_candidates"]), 1)
        self.assertEqual(len(report["held_candidates"]), 1)

    def test_admitted_and_held_lists_are_disjoint(self) -> None:
        report = smoke.run_daily_artifact_gate_fixture_smoke()
        admitted_ids = set(report["admitted_candidates"])
        held_ids = set(report["held_candidates"])
        self.assertEqual(admitted_ids & held_ids, set())

    def test_ok_true_on_designed_outcome(self) -> None:
        report = smoke.run_daily_artifact_gate_fixture_smoke()
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])

    def test_warnings_and_errors_are_lists(self) -> None:
        report = smoke.run_daily_artifact_gate_fixture_smoke()
        self.assertIsInstance(report["warnings"], list)
        self.assertIsInstance(report["errors"], list)


# ---------------------------------------------------------------------------
# Filesystem isolation
# ---------------------------------------------------------------------------


class TestSmokeDoesNotTouchRealArtifacts(unittest.TestCase):
    """Pin that the smoke never reads or writes the real
    ``artifacts/`` directory under the repo root.
    """

    def _real_artifacts_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "artifacts"

    def _snapshot_artifacts_dir(self) -> dict[str, bytes] | None:
        d = self._real_artifacts_dir()
        if not d.is_dir():
            return None
        snap: dict[str, bytes] = {}
        for p in d.rglob("*"):
            if p.is_file():
                snap[str(p.relative_to(d))] = p.read_bytes()
        return snap

    def test_real_artifacts_dir_bytes_unchanged(self) -> None:
        before = self._snapshot_artifacts_dir()
        smoke.run_daily_artifact_gate_fixture_smoke()
        after = self._snapshot_artifacts_dir()
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):

    def test_default_text_mode_emits_compact_view(self) -> None:
        out = StringIO()
        rc = smoke.main([], out=out)
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("Daily artifact-gate fixture smoke", text)
        self.assertIn("Admitted:", text)
        self.assertIn("Held for review:", text)

    def test_json_mode_emits_envelope(self) -> None:
        out = StringIO()
        rc = smoke.main(["--json"], out=out)
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(set(payload.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertEqual(payload["candidates_checked"], 2)
        self.assertEqual(payload["admitted_count"], 1)
        self.assertEqual(payload["held_for_review_count"], 1)

    def test_default_invocation_has_no_filesystem_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as cwd:
            cwd_path = Path(cwd)
            before = {p.name for p in cwd_path.iterdir()}
            out = StringIO()
            old_cwd = os.getcwd()
            try:
                os.chdir(cwd)
                smoke.main([], out=out)
            finally:
                os.chdir(old_cwd)
            after = {p.name for p in cwd_path.iterdir()}
            self.assertEqual(before, after)

    def test_output_path_writes_envelope_when_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "envelope.json"
            self.assertFalse(target.exists())
            out = StringIO()
            rc = smoke.main(
                ["--json", "--output", str(target)], out=out,
            )
            self.assertEqual(rc, 0)
            self.assertTrue(target.is_file())
            written = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(set(written.keys()), set(_REQUIRED_TOP_KEYS))
            self.assertEqual(written["admitted_count"], 1)
            self.assertEqual(written["held_for_review_count"], 1)

    def test_output_path_refuses_to_overwrite_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "envelope.json"
            target.write_text("preexisting", encoding="utf-8")
            out = StringIO()
            rc = smoke.main(
                ["--json", "--output", str(target)], out=out,
            )
            # The script must not silently overwrite; rc != 0 and
            # the original bytes survive.
            self.assertNotEqual(rc, 0)
            self.assertEqual(
                target.read_text(encoding="utf-8"), "preexisting",
            )


# ---------------------------------------------------------------------------
# Source-level read-only assertions
# ---------------------------------------------------------------------------


class TestSmokeModuleSurface(unittest.TestCase):

    def _read(self, rel: str) -> str:
        path = Path(__file__).resolve().parents[1] / rel
        return path.read_text(encoding="utf-8")

    def test_smoke_module_has_no_paid_or_provider_imports(self) -> None:
        text = self._read(
            "scripts/daily_artifact_gate_fixture_smoke.py",
        ).lower()
        for banned in (
            "from fastapi",
            "import fastapi",
            "import yfinance",
            "from yfinance",
            "import market_data",
            "from market_data",
            "openai",
            "anthropic",
        ):
            self.assertNotIn(
                banned, text,
                f"forbidden import {banned!r} seen in "
                f"daily_artifact_gate_fixture_smoke.py",
            )

    def test_smoke_module_does_not_reference_real_artifacts_dir(
        self,
    ) -> None:
        """Pin that the smoke source never references the real
        ``artifacts/`` directory by string literal.  Temp dirs
        only.
        """
        text = self._read("scripts/daily_artifact_gate_fixture_smoke.py")
        for banned in (
            '"artifacts/',
            "'artifacts/",
            '"./artifacts',
            "'./artifacts",
        ):
            self.assertNotIn(
                banned, text,
                f"smoke source must not reference real artifacts "
                f"path: {banned!r}",
            )

    def test_smoke_module_uses_tempfile(self) -> None:
        text = self._read(
            "scripts/daily_artifact_gate_fixture_smoke.py",
        )
        self.assertIn("tempfile", text)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):

    def _run_text(self) -> str:
        out = StringIO()
        smoke.main([], out=out)
        return out.getvalue().lower()

    def _run_json(self) -> str:
        out = StringIO()
        smoke.main(["--json"], out=out)
        return out.getvalue().lower()

    def test_text_view_has_no_banned_tokens(self) -> None:
        text = self._run_text()
        for banned in _BANNED_TOKENS:
            self.assertNotIn(
                banned, text,
                f"banned token {banned!r} in text view",
            )

    def test_json_envelope_has_no_banned_tokens(self) -> None:
        text = self._run_json()
        for banned in _BANNED_TOKENS:
            self.assertNotIn(
                banned, text,
                f"banned token {banned!r} in JSON envelope",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
