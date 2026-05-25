"""Tests for ``scripts/daily_artifact_gate_preview.py``.

The offline gate preview reads a local inbox JSON and a staging
artifact directory, converts each inbox row into a minimal card,
and runs the Daily artifact gate to produce an admitted / held-for-
review split — without starting the FastAPI server and without
touching the live ``artifacts/`` directory.

Read-only contract:

* No DB, ``yfinance``, ``market_data``, paid provider, LLM, or
  FastAPI surface is imported at module load.
* No mutation of the real ``artifacts/`` directory or any shared
  file.  All filesystem activity uses ``tempfile.TemporaryDirectory``
  only.

What the tests pin:

* A card whose ``candidate_id`` points at a present, well-formed
  artifact is admitted.
* A card with a missing artifact file is held for review.
* A card whose artifact is missing ``primary_ticker`` is held.
* A card with no ``candidate_id`` is held.
* A mixed input correctly splits admitted vs held with correct
  counts.
* The real ``artifacts/`` directory is never read or mutated.
* The JSON envelope schema is stable across invocations.
* The CLI fails closed on missing ``--artifact-dir`` or unreadable
  input.
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

from scripts.daily_artifact_gate_preview import (  # noqa: E402
    main,
    run_preview,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_artifact(
    artifact_dir: Path,
    *,
    candidate_id: str,
    mechanism_family: str | None = "supply_shock",
    primary_ticker: str | None = "XOM",
    benchmark_ticker: str | None = "XLE",
) -> Path:
    body: dict[str, Any] = {}
    if mechanism_family is not None:
        body["mechanism_family"] = mechanism_family
    if primary_ticker is not None:
        body["primary_ticker"] = primary_ticker
    if benchmark_ticker is not None:
        body["benchmark_ticker"] = benchmark_ticker
    path = artifact_dir / f"analyzed_event_artifact_{candidate_id}.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _write_inbox(
    tmp_dir: Path,
    rows: list[dict[str, Any]],
    filename: str = "inbox.json",
) -> Path:
    path = tmp_dir / filename
    path.write_text(
        json.dumps(rows, indent=2), encoding="utf-8",
    )
    return path


_ENVELOPE_KEYS: frozenset[str] = frozenset({
    "ok",
    "artifact_type",
    "input_path",
    "artifact_dir",
    "total_cards",
    "admitted_count",
    "held_for_review_count",
    "gate_id",
    "admitted",
    "held_for_review",
    "warnings",
    "errors",
})


# ---------------------------------------------------------------------------
# Gate verdict tests
# ---------------------------------------------------------------------------


class TestCompleteArtifactAdmitted(unittest.TestCase):

    def test_complete_artifact_admits_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            _write_artifact(artifact_dir, candidate_id="cid-001")
            inbox = _write_inbox(tmp_path, [
                {
                    "candidate_id": "cid-001",
                    "title": "OPEC extends voluntary cuts",
                    "source": "local",
                    "published_at": "2026-04-15T10:00:00",
                },
            ])
            env = run_preview(
                input_path=str(inbox),
                artifact_dir=str(artifact_dir),
            )
            self.assertTrue(env["ok"])
            self.assertEqual(env["admitted_count"], 1)
            self.assertEqual(env["held_for_review_count"], 0)
            self.assertEqual(len(env["admitted"]), 1)
            self.assertEqual(len(env["held_for_review"]), 0)
            self.assertEqual(
                env["admitted"][0]["candidate_id"], "cid-001",
            )


class TestMissingArtifactHeld(unittest.TestCase):

    def test_missing_artifact_holds_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            inbox = _write_inbox(tmp_path, [
                {
                    "candidate_id": "cid-missing",
                    "title": "EU proposes retaliatory tariffs",
                    "source": "local",
                    "published_at": "2026-04-02T08:30:00",
                },
            ])
            env = run_preview(
                input_path=str(inbox),
                artifact_dir=str(artifact_dir),
            )
            self.assertTrue(env["ok"])
            self.assertEqual(env["admitted_count"], 0)
            self.assertEqual(env["held_for_review_count"], 1)
            self.assertEqual(len(env["held_for_review"]), 1)


class TestIncompleteArtifactHeld(unittest.TestCase):

    def test_artifact_missing_primary_ticker_holds_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            _write_artifact(
                artifact_dir, candidate_id="cid-inc",
                primary_ticker=None,
            )
            inbox = _write_inbox(tmp_path, [
                {
                    "candidate_id": "cid-inc",
                    "title": "Incomplete artifact row",
                    "source": "local",
                    "published_at": "2026-04-03T06:00:00",
                },
            ])
            env = run_preview(
                input_path=str(inbox),
                artifact_dir=str(artifact_dir),
            )
            self.assertTrue(env["ok"])
            self.assertEqual(env["admitted_count"], 0)
            self.assertEqual(env["held_for_review_count"], 1)


class TestMissingCandidateIdHeld(unittest.TestCase):

    def test_card_without_candidate_id_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            inbox = _write_inbox(tmp_path, [
                {
                    "title": "No candidate_id on this row",
                    "source": "local",
                    "published_at": "2026-04-04T09:00:00",
                },
            ])
            env = run_preview(
                input_path=str(inbox),
                artifact_dir=str(artifact_dir),
            )
            self.assertTrue(env["ok"])
            self.assertEqual(env["admitted_count"], 0)
            self.assertEqual(env["held_for_review_count"], 1)
            held_card = env["held_for_review"][0]
            self.assertNotIn("candidate_id", held_card)


class TestMixedInput(unittest.TestCase):

    def test_mixed_input_splits_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            _write_artifact(artifact_dir, candidate_id="cid-good")
            inbox = _write_inbox(tmp_path, [
                {
                    "candidate_id": "cid-good",
                    "title": "Admitted card",
                    "source": "local",
                    "published_at": "2026-04-01T10:00:00",
                },
                {
                    "candidate_id": "cid-no-artifact",
                    "title": "No artifact on disk",
                    "source": "local",
                    "published_at": "2026-04-02T08:00:00",
                },
                {
                    "title": "No candidate_id at all",
                    "source": "local",
                    "published_at": "2026-04-03T06:00:00",
                },
            ])
            env = run_preview(
                input_path=str(inbox),
                artifact_dir=str(artifact_dir),
            )
            self.assertTrue(env["ok"])
            self.assertEqual(env["total_cards"], 3)
            self.assertEqual(env["admitted_count"], 1)
            self.assertEqual(env["held_for_review_count"], 2)
            self.assertEqual(len(env["admitted"]), 1)
            self.assertEqual(len(env["held_for_review"]), 2)
            self.assertEqual(
                env["admitted"][0]["candidate_id"], "cid-good",
            )


# ---------------------------------------------------------------------------
# No live artifacts/ mutation
# ---------------------------------------------------------------------------


class TestNoLiveArtifactsMutation(unittest.TestCase):

    def test_real_artifacts_dir_not_touched(self) -> None:
        real_artifacts = (
            Path(__file__).resolve().parents[1] / "artifacts"
        )
        if real_artifacts.is_dir():
            before = set(real_artifacts.iterdir())
        else:
            before = set()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            _write_artifact(artifact_dir, candidate_id="cid-safe")
            inbox = _write_inbox(tmp_path, [
                {"candidate_id": "cid-safe", "title": "test"},
            ])
            run_preview(
                input_path=str(inbox),
                artifact_dir=str(artifact_dir),
            )

        if real_artifacts.is_dir():
            after = set(real_artifacts.iterdir())
        else:
            after = set()
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# JSON envelope schema stability
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):

    def test_envelope_carries_all_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            inbox = _write_inbox(tmp_path, [
                {"candidate_id": "cid-schema", "title": "schema test"},
            ])
            env = run_preview(
                input_path=str(inbox),
                artifact_dir=str(artifact_dir),
            )
            self.assertEqual(set(env.keys()), _ENVELOPE_KEYS)

    def test_artifact_type_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            inbox = _write_inbox(tmp_path, [])
            env = run_preview(
                input_path=str(inbox),
                artifact_dir=str(artifact_dir),
            )
            self.assertEqual(
                env["artifact_type"], "daily_artifact_gate_preview",
            )

    def test_gate_id_matches_gate_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            inbox = _write_inbox(tmp_path, [])
            env = run_preview(
                input_path=str(inbox),
                artifact_dir=str(artifact_dir),
            )
            self.assertEqual(
                env["gate_id"],
                "daily_section_c_requires_analyzed_event_artifact",
            )

    def test_admitted_card_carries_headline_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            _write_artifact(artifact_dir, candidate_id="cid-shape")
            inbox = _write_inbox(tmp_path, [
                {
                    "candidate_id": "cid-shape",
                    "title": "Shape check headline",
                    "source": "reuters",
                    "published_at": "2026-04-10T12:00:00",
                },
            ])
            env = run_preview(
                input_path=str(inbox),
                artifact_dir=str(artifact_dir),
            )
            card = env["admitted"][0]
            self.assertEqual(card["headline"], "Shape check headline")
            self.assertEqual(card["source"], "reuters")
            self.assertEqual(card["published_at"], "2026-04-10T12:00:00")
            self.assertEqual(card["candidate_id"], "cid-shape")


# ---------------------------------------------------------------------------
# CLI error handling — fail closed
# ---------------------------------------------------------------------------


class TestCLIFailsClosed(unittest.TestCase):

    def test_missing_artifact_dir_argument_exits_nonzero(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--input", "news_inbox.json"])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_nonexistent_artifact_dir_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            inbox = _write_inbox(tmp_path, [
                {"candidate_id": "cid-x", "title": "test"},
            ])
            env = run_preview(
                input_path=str(inbox),
                artifact_dir=str(tmp_path / "does_not_exist"),
            )
            self.assertFalse(env["ok"])
            self.assertTrue(any(
                "does not exist" in e for e in env["errors"]
            ))

    def test_nonexistent_input_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            env = run_preview(
                input_path=str(Path(tmp) / "missing_inbox.json"),
                artifact_dir=str(artifact_dir),
            )
            self.assertFalse(env["ok"])
            self.assertTrue(any(
                "does not exist" in e for e in env["errors"]
            ))

    def test_unparseable_json_input_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            bad_json = tmp_path / "bad.json"
            bad_json.write_text("not json {{{", encoding="utf-8")
            env = run_preview(
                input_path=str(bad_json),
                artifact_dir=str(artifact_dir),
            )
            self.assertFalse(env["ok"])
            self.assertTrue(any(
                "failed to parse" in e for e in env["errors"]
            ))


# ---------------------------------------------------------------------------
# CLI integration — main() writes JSON to stdout
# ---------------------------------------------------------------------------


class TestCLIIntegration(unittest.TestCase):

    def test_main_writes_parseable_json_to_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifacts"
            artifact_dir.mkdir()
            _write_artifact(artifact_dir, candidate_id="cid-cli")
            inbox = _write_inbox(tmp_path, [
                {"candidate_id": "cid-cli", "title": "CLI test"},
            ])
            buf = io.StringIO()
            rc = main(
                ["--input", str(inbox),
                 "--artifact-dir", str(artifact_dir),
                 "--json"],
                out=buf,
            )
            self.assertEqual(rc, 0)
            env = json.loads(buf.getvalue())
            self.assertTrue(env["ok"])
            self.assertEqual(env["admitted_count"], 1)


# ---------------------------------------------------------------------------
# Source-level read-only assertions
# ---------------------------------------------------------------------------


class TestModuleSurface(unittest.TestCase):

    def _read(self) -> str:
        return (
            Path(__file__).resolve().parents[1]
            / "scripts" / "daily_artifact_gate_preview.py"
        ).read_text(encoding="utf-8")

    def test_no_fastapi_or_provider_imports(self) -> None:
        text = self._read().lower()
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
                f"forbidden import {banned!r} in preview script",
            )

    def test_no_write_calls(self) -> None:
        text = self._read()
        for banned in (
            ".write_text(",
            ".write_bytes(",
            "os.remove(",
            "os.unlink(",
            "shutil.rmtree(",
        ):
            self.assertNotIn(
                banned, text,
                f"preview script contains forbidden call: {banned!r}",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
