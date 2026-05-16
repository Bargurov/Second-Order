"""Tests for ``scripts/daily_artifact_backed_card_source.py``.

The card source is a read-only loader that walks an artifact
directory the operator hands it, parses each
``analyzed_event_artifact_<candidate_id>.json`` file, and emits a
list of Daily demo cards whose mechanism / ticker fields come
verbatim from the artifact body.  The loader never invents a
field, never imports a paid provider, and never reads the inbox.

Pin the contract:

* Read-only by construction.  No DB writes; no
  ``yfinance`` / ``market_data`` / LLM / paid provider / FastAPI
  imports at module load.
* Output dict has EXACTLY these 5 keys::

    ok, cards, skipped_artifacts, warnings, errors

* Each emitted card carries ``candidate_id``, ``headline``,
  ``event_date``, ``mechanism_family``, ``primary_ticker``,
  ``benchmark_ticker``, ``market_relevance``, ``inclusion_reason``,
  ``operator_notes`` and the literal
  ``source == "analyzed_event_artifact"``.
* Artifacts missing one of the three gate-required fields
  (``mechanism_family`` / ``primary_ticker`` /
  ``benchmark_ticker``) or missing a card-content field
  (``headline`` / ``event_date``) are skipped and surfaced under
  ``skipped_artifacts`` with a non-empty ``reason``.
* Cards land in deterministic ``(event_date, candidate_id)``
  order regardless of filesystem order.
* When ``--artifact-dir`` is not supplied, the loader does not
  default to the real ``artifacts/`` directory and never treats a
  fixture/temp directory as a real source — it surfaces a
  warning and an empty ``cards`` list.
* The loader never reads ``news_inbox.json``.
* Conservative wording — banned tokens absent from every
  rendered text and JSON envelope.
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

from scripts import daily_artifact_backed_card_source as src  # noqa: E402


_REQUIRED_TOP_KEYS: tuple[str, ...] = (
    "ok",
    "cards",
    "skipped_artifacts",
    "warnings",
    "errors",
)


_REQUIRED_CARD_FIELDS: tuple[str, ...] = (
    "candidate_id",
    "headline",
    "event_date",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "market_relevance",
    "inclusion_reason",
    "operator_notes",
    "source",
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


def _write_artifact(
    artifact_dir: Path,
    *,
    candidate_id: str,
    body: dict[str, Any],
) -> Path:
    p = artifact_dir / f"analyzed_event_artifact_{candidate_id}.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def _well_formed_body(
    *,
    headline:         str = "OPEC extends voluntary cuts",
    event_date:       str = "2026-04-30",
    mechanism_family: str = "supply_shock",
    primary_ticker:   str = "XOM",
    benchmark_ticker: str = "XLE",
    market_relevance: str | None = "elevated",
    inclusion_reason: str | None = "operator marked as artifact-backed",
    operator_notes:   str | None = "reviewed 2026-04-30",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "headline":         headline,
        "event_date":       event_date,
        "mechanism_family": mechanism_family,
        "primary_ticker":   primary_ticker,
        "benchmark_ticker": benchmark_ticker,
    }
    if market_relevance is not None:
        body["market_relevance"] = market_relevance
    if inclusion_reason is not None:
        body["inclusion_reason"] = inclusion_reason
    if operator_notes is not None:
        body["operator_notes"] = operator_notes
    return body


# ---------------------------------------------------------------------------
# Pure-compute behavior
# ---------------------------------------------------------------------------


class TestEnvelopeShape(unittest.TestCase):

    def test_returns_required_top_level_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )
            self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))


class TestLoadValidArtifact(unittest.TestCase):

    def test_loads_one_valid_artifact_into_one_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(
                d, candidate_id="cid-1", body=_well_formed_body(),
            )
            report = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )
            self.assertTrue(report["ok"])
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["skipped_artifacts"], [])
            self.assertEqual(len(report["cards"]), 1)

    def test_card_carries_all_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(
                d, candidate_id="cid-1", body=_well_formed_body(),
            )
            card = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )["cards"][0]
            for field in _REQUIRED_CARD_FIELDS:
                self.assertIn(field, card)

    def test_card_fields_come_from_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(
                d, candidate_id="cid-x",
                body=_well_formed_body(
                    headline="Refinery outage on Gulf Coast",
                    event_date="2026-05-01",
                    mechanism_family="supply_shock",
                    primary_ticker="VLO",
                    benchmark_ticker="XLE",
                    market_relevance="elevated",
                    inclusion_reason="operator marked as artifact-backed",
                    operator_notes="confirmed 2026-05-01",
                ),
            )
            card = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )["cards"][0]
            self.assertEqual(card["candidate_id"], "cid-x")
            self.assertEqual(card["headline"], "Refinery outage on Gulf Coast")
            self.assertEqual(card["event_date"], "2026-05-01")
            self.assertEqual(card["mechanism_family"], "supply_shock")
            self.assertEqual(card["primary_ticker"], "VLO")
            self.assertEqual(card["benchmark_ticker"], "XLE")
            self.assertEqual(card["market_relevance"], "elevated")
            self.assertEqual(
                card["inclusion_reason"],
                "operator marked as artifact-backed",
            )
            self.assertEqual(card["operator_notes"], "confirmed 2026-05-01")

    def test_source_is_pinned_literal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(
                d, candidate_id="cid-1", body=_well_formed_body(),
            )
            card = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )["cards"][0]
            self.assertEqual(card["source"], "analyzed_event_artifact")

    def test_optional_fields_default_to_empty_string_when_absent(
        self,
    ) -> None:
        """Operator-supplied fields (market_relevance,
        inclusion_reason, operator_notes) are not gate-enforced.
        When missing on the artifact body, the card surfaces them
        as ``""`` — never an inferred value.
        """
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(
                d, candidate_id="cid-1",
                body=_well_formed_body(
                    market_relevance=None,
                    inclusion_reason=None,
                    operator_notes=None,
                ),
            )
            card = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )["cards"][0]
            self.assertEqual(card["market_relevance"], "")
            self.assertEqual(card["inclusion_reason"], "")
            self.assertEqual(card["operator_notes"], "")


# ---------------------------------------------------------------------------
# Skip-on-invalid behavior
# ---------------------------------------------------------------------------


class TestSkipInvalidArtifacts(unittest.TestCase):

    def _skipped_one(
        self, body_overrides: dict[str, Any], *, candidate_id: str = "cid-bad",
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            body = _well_formed_body()
            body.update(body_overrides)
            _write_artifact(d, candidate_id=candidate_id, body=body)
            report = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )
            self.assertEqual(report["cards"], [])
            self.assertEqual(len(report["skipped_artifacts"]), 1)
            return report["skipped_artifacts"][0]

    def test_skips_when_mechanism_family_missing(self) -> None:
        skip = self._skipped_one({"mechanism_family": ""})
        self.assertIn("mechanism_family", skip["reason"])

    def test_skips_when_mechanism_family_is_none_sentinel(self) -> None:
        skip = self._skipped_one({"mechanism_family": "none"})
        self.assertIn("mechanism_family", skip["reason"])

    def test_skips_when_primary_ticker_missing(self) -> None:
        skip = self._skipped_one({"primary_ticker": ""})
        self.assertIn("primary_ticker", skip["reason"])

    def test_skips_when_benchmark_ticker_missing(self) -> None:
        skip = self._skipped_one({"benchmark_ticker": ""})
        self.assertIn("benchmark_ticker", skip["reason"])

    def test_skips_when_headline_missing(self) -> None:
        skip = self._skipped_one({"headline": ""})
        self.assertIn("headline", skip["reason"])

    def test_skips_when_event_date_missing(self) -> None:
        skip = self._skipped_one({"event_date": ""})
        self.assertIn("event_date", skip["reason"])

    def test_skips_when_artifact_is_not_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "analyzed_event_artifact_cid-1.json").write_text(
                "not json {", encoding="utf-8",
            )
            report = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )
            self.assertEqual(report["cards"], [])
            self.assertEqual(len(report["skipped_artifacts"]), 1)
            self.assertIn("json", report["skipped_artifacts"][0]["reason"].lower())

    def test_skips_when_artifact_root_is_not_a_json_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "analyzed_event_artifact_cid-1.json").write_text(
                "[]", encoding="utf-8",
            )
            report = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )
            self.assertEqual(report["cards"], [])
            self.assertEqual(len(report["skipped_artifacts"]), 1)

    def test_skipped_entry_carries_path_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "analyzed_event_artifact_cid-1.json").write_text(
                "not json {", encoding="utf-8",
            )
            report = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )
            entry = report["skipped_artifacts"][0]
            self.assertIn("path", entry)
            self.assertIn("reason", entry)
            self.assertIsInstance(entry["path"], str)
            self.assertIsInstance(entry["reason"], str)
            self.assertNotEqual(entry["reason"].strip(), "")


class TestFileSelection(unittest.TestCase):

    def test_only_files_matching_glob_are_loaded(self) -> None:
        """Files outside the ``analyzed_event_artifact_*.json``
        naming pattern are ignored entirely — never loaded, never
        skipped.
        """
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(
                d, candidate_id="cid-1", body=_well_formed_body(),
            )
            (d / "freeze_candidate_evidence.json").write_text(
                json.dumps({"unrelated": True}), encoding="utf-8",
            )
            (d / "notes.txt").write_text("ignored", encoding="utf-8")
            report = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )
            self.assertEqual(len(report["cards"]), 1)
            self.assertEqual(report["skipped_artifacts"], [])


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicSort(unittest.TestCase):

    def test_cards_sorted_by_event_date_then_candidate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            # Write in mixed order; the loader must sort.
            _write_artifact(
                d, candidate_id="cid-zebra",
                body=_well_formed_body(event_date="2026-05-02"),
            )
            _write_artifact(
                d, candidate_id="cid-apple",
                body=_well_formed_body(event_date="2026-05-02"),
            )
            _write_artifact(
                d, candidate_id="cid-mango",
                body=_well_formed_body(event_date="2026-04-30"),
            )
            cards = src.build_daily_artifact_backed_cards(
                artifact_dir=tmp,
            )["cards"]
            order = [(c["event_date"], c["candidate_id"]) for c in cards]
            self.assertEqual(order, [
                ("2026-04-30", "cid-mango"),
                ("2026-05-02", "cid-apple"),
                ("2026-05-02", "cid-zebra"),
            ])


# ---------------------------------------------------------------------------
# Default-no-source behavior
# ---------------------------------------------------------------------------


class TestNoArtifactDirSupplied(unittest.TestCase):

    def test_no_artifact_dir_returns_empty_with_warning(self) -> None:
        report = src.build_daily_artifact_backed_cards(artifact_dir=None)
        self.assertTrue(report["ok"])
        self.assertEqual(report["cards"], [])
        self.assertEqual(report["skipped_artifacts"], [])
        self.assertEqual(report["errors"], [])
        self.assertGreaterEqual(len(report["warnings"]), 1)
        self.assertIn(
            "artifact-dir",
            " ".join(report["warnings"]).lower(),
        )

    def test_missing_artifact_dir_surfaces_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "does_not_exist")
            report = src.build_daily_artifact_backed_cards(
                artifact_dir=missing,
            )
            self.assertFalse(report["ok"])
            self.assertEqual(report["cards"], [])
            self.assertGreaterEqual(len(report["errors"]), 1)


# ---------------------------------------------------------------------------
# Filesystem isolation — read-only against real artifacts/
# ---------------------------------------------------------------------------


class TestRealFilesUntouched(unittest.TestCase):

    def _snapshot_dir(self, root: Path) -> dict[str, bytes] | None:
        if not root.is_dir():
            return None
        out: dict[str, bytes] = {}
        for p in root.rglob("*"):
            if p.is_file():
                out[str(p.relative_to(root))] = p.read_bytes()
        return out

    def test_real_artifacts_bytes_unchanged_after_load(self) -> None:
        d = _REPO_ROOT / "artifacts"
        before = self._snapshot_dir(d)
        src.build_daily_artifact_backed_cards(artifact_dir=str(d))
        after = self._snapshot_dir(d)
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):

    def test_default_text_mode_emits_compact_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(
                d, candidate_id="cid-1", body=_well_formed_body(),
            )
            out = StringIO()
            rc = src.main(["--artifact-dir", tmp], out=out)
            self.assertEqual(rc, 0)
            text = out.getvalue()
            self.assertIn("Daily artifact-backed card source", text)
            self.assertIn("Cards:", text)

    def test_json_mode_emits_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(
                d, candidate_id="cid-1", body=_well_formed_body(),
            )
            out = StringIO()
            rc = src.main(["--json", "--artifact-dir", tmp], out=out)
            self.assertEqual(rc, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(set(payload.keys()), set(_REQUIRED_TOP_KEYS))
            self.assertEqual(len(payload["cards"]), 1)

    def test_default_invocation_without_artifact_dir_returns_empty(
        self,
    ) -> None:
        out = StringIO()
        rc = src.main(["--json"], out=out)
        # No --artifact-dir: rc 0 (warning, not an error) and zero
        # cards; the loader does not infer a default source.
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["cards"], [])

    def test_cli_against_real_artifacts_dir_runs_clean(self) -> None:
        """Mirror the verification command:
        ``python scripts/daily_artifact_backed_card_source.py
        --json --artifact-dir artifacts``.

        On a repo with no analyzed_event_artifact_*.json files
        present, the loader returns ok=True with zero cards and
        zero skipped_artifacts.  Pin that path runs clean.
        """
        d = _REPO_ROOT / "artifacts"
        if not d.is_dir():
            self.skipTest("real artifacts/ directory missing")
        out = StringIO()
        rc = src.main(["--json", "--artifact-dir", str(d)], out=out)
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["cards"], list)


# ---------------------------------------------------------------------------
# Source-level read-only assertions
# ---------------------------------------------------------------------------


class TestModuleSurface(unittest.TestCase):

    def _read(self, rel: str) -> str:
        return (_REPO_ROOT / rel).read_text(encoding="utf-8")

    def test_no_paid_or_provider_imports(self) -> None:
        text = self._read(
            "scripts/daily_artifact_backed_card_source.py",
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
            self.assertNotIn(banned, text)

    def test_does_not_reference_news_inbox(self) -> None:
        text = self._read(
            "scripts/daily_artifact_backed_card_source.py",
        ).lower()
        self.assertNotIn("news_inbox", text)

    def test_does_not_call_write_or_delete_helpers(self) -> None:
        text = self._read(
            "scripts/daily_artifact_backed_card_source.py",
        )
        for banned in (
            ".write_text(",
            ".write_bytes(",
            "os.remove(",
            "os.unlink(",
            "shutil.rmtree(",
        ):
            self.assertNotIn(
                banned, text,
                f"forbidden mutation call: {banned!r}",
            )


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):

    def _run(self, args: list[str]) -> str:
        out = StringIO()
        src.main(args, out=out)
        return out.getvalue().lower()

    def test_text_view_no_banned_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(
                d, candidate_id="cid-1", body=_well_formed_body(),
            )
            text = self._run(["--artifact-dir", tmp])
            for banned in _BANNED_TOKENS:
                self.assertNotIn(
                    banned, text,
                    f"banned token {banned!r} in text view",
                )

    def test_json_view_no_banned_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(
                d, candidate_id="cid-1", body=_well_formed_body(),
            )
            text = self._run(["--json", "--artifact-dir", tmp])
            for banned in _BANNED_TOKENS:
                self.assertNotIn(
                    banned, text,
                    f"banned token {banned!r} in JSON envelope",
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
