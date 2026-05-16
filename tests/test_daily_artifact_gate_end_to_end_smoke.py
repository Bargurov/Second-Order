"""Tests for ``scripts/daily_artifact_gate_end_to_end_smoke.py``.

The end-to-end smoke proves the full Daily artifact-gate path can
admit one artifact-backed candidate and hold one unenriched
candidate using the same gate helper
(:func:`routes.daily_artifact_gate.filter_daily_section_c_cards`)
that the ``/movers/today`` route invokes.  It runs entirely
against a temp artifact directory the smoke owns; it never reads
or writes the events DB, an LLM, ``yfinance``, ``market_data``,
a paid provider, or any FastAPI surface.

Pin the contract:

* Read-only by construction.  No DB writes; no
  ``yfinance`` / ``market_data`` / LLM / paid provider / FastAPI
  imports at module load.
* Output dict has EXACTLY these 9 keys::

    ok, candidates_checked, admitted_count,
    held_for_review_count, admitted_candidates, held_candidates,
    real_files_unchanged, warnings, errors

* ``admitted_candidates`` items carry the three artifact-backed
  fields (``mechanism_family`` / ``primary_ticker`` /
  ``benchmark_ticker``) sourced from the temp artifact body so
  the operator can see *why* the row was eligible.
* ``held_candidates`` items carry a ``hold_reason`` so the
  operator can see *why* the row was held.
* Real ``artifacts/`` directory bytes and real
  ``news_inbox.json`` bytes are unchanged before and after the
  smoke; ``real_files_unchanged`` is ``True`` on a clean run.
* Default invocation has no filesystem side effect outside
  Python's tempdir; ``--output`` is the only way to write a file
  and the script refuses to overwrite an existing path.
* Conservative wording — banned tokens absent from every
  rendered text and JSON envelope.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import daily_artifact_gate_end_to_end_smoke as smoke  # noqa: E402


_REQUIRED_TOP_KEYS: tuple[str, ...] = (
    "ok",
    "candidates_checked",
    "admitted_count",
    "held_for_review_count",
    "admitted_candidates",
    "held_candidates",
    "real_files_unchanged",
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


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _hash_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _hash_tree(root: Path) -> dict[str, str] | None:
    if not root.is_dir():
        return None
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = _hash_file(p) or ""
    return out


# ---------------------------------------------------------------------------
# Pure-compute behavior
# ---------------------------------------------------------------------------


class TestRunEndToEndSmoke(unittest.TestCase):

    def test_returns_required_top_level_keys(self) -> None:
        report = smoke.run_daily_artifact_gate_end_to_end_smoke()
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))

    def test_admits_one_and_holds_one(self) -> None:
        report = smoke.run_daily_artifact_gate_end_to_end_smoke()
        self.assertEqual(report["candidates_checked"], 2)
        self.assertEqual(report["admitted_count"], 1)
        self.assertEqual(report["held_for_review_count"], 1)

    def test_admitted_item_carries_artifact_backed_fields(self) -> None:
        report = smoke.run_daily_artifact_gate_end_to_end_smoke()
        admitted = report["admitted_candidates"]
        self.assertEqual(len(admitted), 1)
        item = admitted[0]
        self.assertIsInstance(item, dict)
        # Three artifact-backed fields must be present and non-empty.
        for field in (
            "candidate_id",
            "mechanism_family",
            "primary_ticker",
            "benchmark_ticker",
        ):
            self.assertIn(field, item)
            self.assertIsInstance(item[field], str)
            self.assertNotEqual(item[field].strip(), "")

    def test_held_item_carries_candidate_id_and_hold_reason(self) -> None:
        report = smoke.run_daily_artifact_gate_end_to_end_smoke()
        held = report["held_candidates"]
        self.assertEqual(len(held), 1)
        item = held[0]
        self.assertIsInstance(item, dict)
        self.assertIn("candidate_id", item)
        self.assertIsInstance(item["candidate_id"], str)
        self.assertNotEqual(item["candidate_id"].strip(), "")
        self.assertIn("hold_reason", item)
        self.assertIsInstance(item["hold_reason"], str)
        self.assertNotEqual(item["hold_reason"].strip(), "")

    def test_admitted_and_held_candidate_ids_are_disjoint(self) -> None:
        report = smoke.run_daily_artifact_gate_end_to_end_smoke()
        admitted_ids = {i["candidate_id"] for i in report["admitted_candidates"]}
        held_ids = {i["candidate_id"] for i in report["held_candidates"]}
        self.assertEqual(admitted_ids & held_ids, set())

    def test_ok_true_on_designed_outcome(self) -> None:
        report = smoke.run_daily_artifact_gate_end_to_end_smoke()
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])

    def test_real_files_unchanged_is_true(self) -> None:
        report = smoke.run_daily_artifact_gate_end_to_end_smoke()
        self.assertIs(report["real_files_unchanged"], True)


# ---------------------------------------------------------------------------
# Filesystem isolation — verified at runtime via bytes snapshot
# ---------------------------------------------------------------------------


class TestRealFilesUntouched(unittest.TestCase):

    def test_real_artifacts_bytes_unchanged(self) -> None:
        d = _REPO_ROOT / "artifacts"
        before = _hash_tree(d)
        smoke.run_daily_artifact_gate_end_to_end_smoke()
        after = _hash_tree(d)
        self.assertEqual(before, after)

    def test_real_news_inbox_bytes_unchanged(self) -> None:
        f = _REPO_ROOT / "news_inbox.json"
        before = _hash_file(f)
        smoke.run_daily_artifact_gate_end_to_end_smoke()
        after = _hash_file(f)
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Production gate wiring — pin the smoke uses the same helper as
# the route, not a parallel reimplementation
# ---------------------------------------------------------------------------


class TestUsesProductionGateHelper(unittest.TestCase):

    def test_smoke_imports_filter_daily_section_c_cards(self) -> None:
        text = (
            _REPO_ROOT
            / "scripts" / "daily_artifact_gate_end_to_end_smoke.py"
        ).read_text(encoding="utf-8")
        # The smoke must call the same helper that ``routes/movers.py``
        # invokes on the Daily branch — not a parallel reimplementation.
        self.assertIn(
            "from routes.daily_artifact_gate import",
            text,
        )
        self.assertIn("filter_daily_section_c_cards", text)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):

    def test_default_text_mode_emits_compact_view(self) -> None:
        out = StringIO()
        rc = smoke.main([], out=out)
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("Daily artifact-gate end-to-end smoke", text)
        self.assertIn("Admitted:", text)
        self.assertIn("Held for review:", text)
        self.assertIn("Real files unchanged:", text)

    def test_json_mode_emits_envelope(self) -> None:
        out = StringIO()
        rc = smoke.main(["--json"], out=out)
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(set(payload.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertEqual(payload["candidates_checked"], 2)
        self.assertEqual(payload["admitted_count"], 1)
        self.assertEqual(payload["held_for_review_count"], 1)
        self.assertIs(payload["real_files_unchanged"], True)

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
            self.assertNotEqual(rc, 0)
            self.assertEqual(
                target.read_text(encoding="utf-8"), "preexisting",
            )


# ---------------------------------------------------------------------------
# Source-level read-only assertions
# ---------------------------------------------------------------------------


class TestSmokeModuleSurface(unittest.TestCase):

    def _read(self, rel: str) -> str:
        path = _REPO_ROOT / rel
        return path.read_text(encoding="utf-8")

    def test_smoke_module_has_no_paid_or_provider_imports(self) -> None:
        text = self._read(
            "scripts/daily_artifact_gate_end_to_end_smoke.py",
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
                f"daily_artifact_gate_end_to_end_smoke.py",
            )

    def test_smoke_module_uses_tempfile(self) -> None:
        text = self._read(
            "scripts/daily_artifact_gate_end_to_end_smoke.py",
        )
        self.assertIn("tempfile", text)

    def test_smoke_module_does_not_write_to_real_artifacts_dir(
        self,
    ) -> None:
        """The smoke source must not call ``write_text`` /
        ``write_bytes`` against any path resolved from the real
        ``artifacts/`` directory or ``news_inbox.json``.  These
        paths are read-only seams in this script; integrity is
        verified by hashing them before and after the run.
        """
        text = self._read(
            "scripts/daily_artifact_gate_end_to_end_smoke.py",
        )
        for banned in (
            'open("artifacts',
            "open('artifacts",
            'shutil.rmtree("artifacts',
            "shutil.rmtree('artifacts",
            'open("news_inbox',
            "open('news_inbox",
        ):
            self.assertNotIn(banned, text, f"forbidden write/delete: {banned!r}")


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
