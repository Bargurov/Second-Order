"""Tests for ``scripts/daily_reviewed_artifact_end_to_end_smoke.py``.

The smoke wires the four steps of the operator-reviewed Daily
Section C path together using temp files only:

  reviewed worksheet row  ->  emitter
                          ->  analyzed_event_artifact_<cid>.json
                          ->  artifact-backed card source
                          ->  routes.daily_artifact_gate
                          ->  admitted card

Pin the contract:

* Read-only.  No DB writes; no ``yfinance``, ``market_data``, LLM,
  paid provider, or FastAPI surface imported at module load.
* Output dict has EXACTLY these 10 keys::

    ok, worksheet_rows, artifacts_written, cards_loaded,
    admitted_count, held_for_review_count, admitted_candidates,
    real_files_unchanged, warnings, errors

* Happy path: the included CSV row's ``candidate_id``
  (``daily-demo-001``) flows from the CSV to the artifact
  filename to the admitted card unchanged.  The excluded row
  produces no artifact and no admitted card.
* Real ``artifacts/`` and real ``news_inbox.json`` are never
  written; bytes are unchanged before and after the smoke.
* ``--output`` is the only filesystem side effect (refuses to
  overwrite).  Default invocation has no filesystem side effect
  outside Python's tempdir.
* Conservative wording -- banned tokens absent from every render.
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

from scripts import daily_reviewed_artifact_end_to_end_smoke as cli  # noqa: E402


_REQUIRED_TOP_KEYS = (
    "ok",
    "worksheet_rows",
    "artifacts_written",
    "cards_loaded",
    "admitted_count",
    "held_for_review_count",
    "admitted_candidates",
    "real_files_unchanged",
    "warnings",
    "errors",
)


_ADMITTED_ITEM_KEYS = (
    "candidate_id",
    "headline",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
)


_BANNED_WORDS = (
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


_INCLUDED_CANDIDATE_ID = "daily-demo-001"
_EXCLUDED_CANDIDATE_ID = "daily-demo-excluded-002"


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_envelope_carries_exactly_ten_keys(self) -> None:
        report = cli.run_daily_reviewed_artifact_end_to_end_smoke()
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))

    def test_admitted_item_has_expected_field_shape(self) -> None:
        report = cli.run_daily_reviewed_artifact_end_to_end_smoke()
        for item in report["admitted_candidates"]:
            self.assertEqual(set(item.keys()), set(_ADMITTED_ITEM_KEYS))


# ---------------------------------------------------------------------------
# Happy-path wiring
# ---------------------------------------------------------------------------


class TestHappyPath(unittest.TestCase):
    def test_happy_path_admits_included_candidate(self) -> None:
        report = cli.run_daily_reviewed_artifact_end_to_end_smoke()
        # Worksheet has two rows: one included, one excluded.
        self.assertEqual(report["worksheet_rows"], 2)
        # Emitter writes exactly one artifact (the excluded row is
        # silently skipped).
        self.assertEqual(report["artifacts_written"], 1)
        # Card source builds exactly one card from the single
        # artifact present in the temp dir.
        self.assertEqual(report["cards_loaded"], 1)
        # Gate admits the one artifact-backed card.
        self.assertGreaterEqual(report["admitted_count"], 1)
        # No held cards because the card source only knows about
        # artifacts that exist on disk.
        self.assertEqual(report["held_for_review_count"], 0)
        # The admitted candidate_id matches the artifact filename
        # and the included CSV row.
        ids = {i["candidate_id"] for i in report["admitted_candidates"]}
        self.assertIn(_INCLUDED_CANDIDATE_ID, ids)
        self.assertNotIn(_EXCLUDED_CANDIDATE_ID, ids)
        # Real shared inputs unchanged.
        self.assertTrue(report["real_files_unchanged"])
        # Happy path is ok=True with no errors.
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])

    def test_admitted_card_carries_artifact_backed_fields(self) -> None:
        report = cli.run_daily_reviewed_artifact_end_to_end_smoke()
        included = next(
            i for i in report["admitted_candidates"]
            if i["candidate_id"] == _INCLUDED_CANDIDATE_ID
        )
        # Every artifact-backed field on the admitted item is a
        # non-empty string (came from the temp artifact body).
        for field in ("headline", "mechanism_family",
                      "primary_ticker", "benchmark_ticker"):
            self.assertIsInstance(included[field], str)
            self.assertNotEqual(included[field], "")

    def test_excluded_row_does_not_produce_artifact_or_admit(self) -> None:
        # Run the smoke and verify the excluded candidate_id is
        # absent from admitted_candidates.  We can't observe the
        # temp dir directly (it's torn down inside the run), but
        # the admitted set tells us the excluded row never reached
        # the artifact directory.
        report = cli.run_daily_reviewed_artifact_end_to_end_smoke()
        ids = {i["candidate_id"] for i in report["admitted_candidates"]}
        self.assertNotIn(_EXCLUDED_CANDIDATE_ID, ids)


# ---------------------------------------------------------------------------
# Card-source helper
# ---------------------------------------------------------------------------


class TestCardsFromArtifactDir(unittest.TestCase):
    def test_returns_empty_list_for_missing_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cards = cli._cards_from_artifact_dir(
                Path(tmp) / "nonexistent",
            )
        self.assertEqual(cards, [])

    def test_returns_one_card_per_artifact_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "analyzed_event_artifact_alpha.json").write_text(
                json.dumps({
                    "headline":         "alpha headline",
                    "mechanism_family": "supply_shock",
                    "primary_ticker":   "XOM",
                    "benchmark_ticker": "XLE",
                }),
                encoding="utf-8",
            )
            (d / "analyzed_event_artifact_beta.json").write_text(
                json.dumps({
                    "headline":         "beta headline",
                    "mechanism_family": "rate_shock",
                    "primary_ticker":   "TLT",
                    "benchmark_ticker": "SPY",
                }),
                encoding="utf-8",
            )
            # An unrelated file is ignored.
            (d / "unrelated.json").write_text("{}", encoding="utf-8")
            cards = cli._cards_from_artifact_dir(d)
        ids = sorted(c["candidate_id"] for c in cards)
        self.assertEqual(ids, ["alpha", "beta"])
        # Headlines come from the artifact body when readable.
        headlines = {c["candidate_id"]: c["headline"] for c in cards}
        self.assertEqual(headlines["alpha"], "alpha headline")
        self.assertEqual(headlines["beta"], "beta headline")

    def test_card_built_when_body_is_unreadable(self) -> None:
        # A malformed body still produces a card (with empty
        # headline) so the gate can see the candidate and hold it
        # for review.  The card source never raises on a bad body.
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "analyzed_event_artifact_bad.json").write_text(
                "not json {",
                encoding="utf-8",
            )
            cards = cli._cards_from_artifact_dir(d)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["candidate_id"], "bad")
        self.assertEqual(cards[0]["headline"], "")


# ---------------------------------------------------------------------------
# Real-file integrity
# ---------------------------------------------------------------------------


class TestRealFileIntegrity(unittest.TestCase):
    def test_real_files_unchanged_after_smoke(self) -> None:
        before_artifacts = cli._hash_dir(cli._REAL_ARTIFACTS_DIR)
        before_inbox     = cli._hash_file(cli._REAL_NEWS_INBOX)
        report = cli.run_daily_reviewed_artifact_end_to_end_smoke()
        after_artifacts  = cli._hash_dir(cli._REAL_ARTIFACTS_DIR)
        after_inbox      = cli._hash_file(cli._REAL_NEWS_INBOX)
        self.assertEqual(before_artifacts, after_artifacts)
        self.assertEqual(before_inbox,     after_inbox)
        self.assertTrue(report["real_files_unchanged"])


# ---------------------------------------------------------------------------
# Emitter failure path (lazy seam)
# ---------------------------------------------------------------------------


class TestEmitterFailure(unittest.TestCase):
    def test_emitter_errors_surface_in_envelope(self) -> None:
        bad_envelope = {
            "ok":             False,
            "loaded_row_count": 2,
            "emitted_count":  0,
            "skipped_count":  2,
            "errors":         ["row 0: missing required field foo"],
            "warnings":       [],
        }
        with patch.object(
            cli, "_run_emitter", return_value=bad_envelope,
        ):
            report = cli.run_daily_reviewed_artifact_end_to_end_smoke()
        self.assertFalse(report["ok"])
        self.assertEqual(report["artifacts_written"], 0)
        # The emitter's error string is carried through with a
        # prefix so the operator can tell which step surfaced it.
        joined = " | ".join(report["errors"])
        self.assertIn("emitter:", joined)
        self.assertIn("missing required field foo", joined)

    def test_emitter_exception_surfaces_in_envelope(self) -> None:
        with patch.object(
            cli, "_run_emitter",
            side_effect=RuntimeError("boom"),
        ):
            report = cli.run_daily_reviewed_artifact_end_to_end_smoke()
        self.assertFalse(report["ok"])
        joined = " | ".join(report["errors"]).lower()
        self.assertIn("emitter raised", joined)
        self.assertIn("runtimeerror", joined)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_words_in_json_render(self) -> None:
        report = cli.run_daily_reviewed_artifact_end_to_end_smoke()
        blob = cli._render_json(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(
                term, blob,
                f"banned token {term!r} in JSON render",
            )

    def test_no_banned_words_in_text_render(self) -> None:
        report = cli.run_daily_reviewed_artifact_end_to_end_smoke()
        text = cli._render_text(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(
                term, text,
                f"banned token {term!r} in text render",
            )


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_provider_attrs(self) -> None:
        # The lazy emitter seam pulls scripts.daily_analyzed_event_artifact_emitter
        # on the un-patched path only; the top-level import surface
        # of this smoke must never bind a paid provider or FastAPI.
        for attr in (
            "yfinance", "anthropic", "openai", "fastapi",
            "FastAPI", "APIRouter", "market_data", "sqlite3",
        ):
            self.assertFalse(
                hasattr(cli, attr),
                f"smoke must not bind {attr!r} as a module attr",
            )


# ---------------------------------------------------------------------------
# Worksheet writer
# ---------------------------------------------------------------------------


class TestWorksheetWriter(unittest.TestCase):
    def test_writer_emits_expected_header_and_two_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "worksheet.csv"
            cli._write_worksheet_csv(csv_path, [
                cli._INCLUDED_ROW, cli._EXCLUDED_ROW,
            ])
            text = csv_path.read_text(encoding="utf-8")
        # Header columns appear in the declared order.
        first_line = text.splitlines()[0]
        for col in cli._WORKSHEET_FIELDS:
            self.assertIn(col, first_line)
        # The included row's candidate_id appears verbatim — no
        # auto-generation.
        self.assertIn(_INCLUDED_CANDIDATE_ID, text)
        self.assertIn(_EXCLUDED_CANDIDATE_ID, text)
        # The excluded row's include flag is "no".
        self.assertIn("no", text)


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

    def test_json_emits_required_keys(self) -> None:
        rc, output = self._run(["--json"])
        parsed = json.loads(output)
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertEqual(rc, 0)
        self.assertTrue(parsed["ok"])

    def test_text_render_does_not_crash(self) -> None:
        rc, output = self._run([])
        self.assertIn("end-to-end smoke", output.lower())
        self.assertIn(rc, (0, 1))

    def test_output_refuses_to_overwrite_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "envelope.json"
            out_path.write_text("preexisting", encoding="utf-8")
            rc, _ = self._run([
                "--json", "--output", str(out_path),
            ])
            # File contents are unchanged after the refusal.
            self.assertEqual(
                out_path.read_text(encoding="utf-8"),
                "preexisting",
            )
        self.assertNotEqual(rc, 0)

    def test_output_writes_json_envelope_when_path_is_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "envelope.json"
            rc, _ = self._run([
                "--json", "--output", str(out_path),
            ])
            self.assertTrue(out_path.is_file())
            envelope = json.loads(
                out_path.read_text(encoding="utf-8"),
            )
        self.assertEqual(rc, 0)
        self.assertEqual(set(envelope.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertTrue(envelope["ok"])
        # The admitted_candidates block carries the included row.
        ids = {i["candidate_id"] for i in envelope["admitted_candidates"]}
        self.assertIn(_INCLUDED_CANDIDATE_ID, ids)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
