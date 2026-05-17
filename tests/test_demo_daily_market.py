"""Tests for ``routes/demo_daily.py``.

Pin the contract:

* Envelope carries EXACTLY these 7 top-level keys::

    ok, section, items, count, skipped_artifacts, warnings, errors

* ``section`` is the literal ``"daily"``.
* Every item carries the required fields
  (``candidate_id`` / ``headline`` / ``event_date`` /
  ``mechanism_family`` / ``primary_ticker`` / ``benchmark_ticker`` /
  ``market_relevance`` / ``inclusion_reason`` / ``operator_notes`` /
  ``caution_label``).
* Only valid ``analyzed_event_artifact_<candidate_id>.json`` files
  are emitted as items.  Invalid artifacts (missing gate-required
  field, missing card-content field, unreadable JSON, non-object
  root) are surfaced under ``skipped_artifacts`` with a non-empty
  ``reason``.
* When ``artifact_dir`` is ``None`` the source returns ``ok=True``
  with ``count=0`` and a warning.  It does NOT default to the real
  ``artifacts/`` directory.
* The source never mutates the artifact directory and never reads
  ``news_inbox.json``.
* Conservative wording — banned tokens never appear in any text or
  JSON the source emits.
* The module imports no DB, provider, ``yfinance``, ``market_data``,
  LLM, or FastAPI surface at module load.  No network access.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes import demo_daily as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS: tuple[str, ...] = (
    "ok",
    "section",
    "items",
    "count",
    "skipped_artifacts",
    "warnings",
    "errors",
)


_REQUIRED_ITEM_KEYS: tuple[str, ...] = (
    "candidate_id",
    "headline",
    "event_date",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "market_relevance",
    "inclusion_reason",
    "operator_notes",
    "caution_label",
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
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):

    def test_top_level_keys_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            envelope = cli.build_demo_daily_market(artifact_dir=tmp)
        self.assertEqual(
            set(envelope.keys()), set(_REQUIRED_ENVELOPE_KEYS),
            f"unexpected envelope keys: {sorted(envelope.keys())}",
        )

    def test_section_is_daily(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            envelope = cli.build_demo_daily_market(artifact_dir=tmp)
        self.assertEqual(envelope["section"], "daily")

    def test_count_matches_items_length(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(d, candidate_id="cid-1", body=_well_formed_body())
            _write_artifact(
                d, candidate_id="cid-2",
                body=_well_formed_body(event_date="2026-05-02"),
            )
            envelope = cli.build_demo_daily_market(artifact_dir=tmp)
        self.assertEqual(envelope["count"], len(envelope["items"]))
        self.assertEqual(envelope["count"], 2)


# ---------------------------------------------------------------------------
# Valid artifact loading
# ---------------------------------------------------------------------------


class TestLoadValidArtifact(unittest.TestCase):

    def test_loads_one_valid_artifact_into_one_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(d, candidate_id="cid-1", body=_well_formed_body())
            envelope = cli.build_demo_daily_market(artifact_dir=tmp)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["errors"], [])
        self.assertEqual(envelope["skipped_artifacts"], [])
        self.assertEqual(len(envelope["items"]), 1)

    def test_item_carries_all_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(d, candidate_id="cid-1", body=_well_formed_body())
            item = cli.build_demo_daily_market(artifact_dir=tmp)["items"][0]
        for key in _REQUIRED_ITEM_KEYS:
            self.assertIn(key, item, f"item missing required key {key!r}")

    def test_item_fields_come_verbatim_from_artifact(self) -> None:
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
            item = cli.build_demo_daily_market(artifact_dir=tmp)["items"][0]
        self.assertEqual(item["candidate_id"], "cid-x")
        self.assertEqual(item["headline"], "Refinery outage on Gulf Coast")
        self.assertEqual(item["event_date"], "2026-05-01")
        self.assertEqual(item["mechanism_family"], "supply_shock")
        self.assertEqual(item["primary_ticker"], "VLO")
        self.assertEqual(item["benchmark_ticker"], "XLE")
        self.assertEqual(item["market_relevance"], "elevated")
        self.assertEqual(
            item["inclusion_reason"],
            "operator marked as artifact-backed",
        )
        self.assertEqual(item["operator_notes"], "confirmed 2026-05-01")

    def test_optional_fields_default_to_empty_string_when_absent(self) -> None:
        """Operator review fields (market_relevance, inclusion_reason,
        operator_notes) are not gate-enforced.  When the artifact
        body omits them, the item surfaces them as ``""`` — never an
        inferred value.
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
            item = cli.build_demo_daily_market(artifact_dir=tmp)["items"][0]
        self.assertEqual(item["market_relevance"], "")
        self.assertEqual(item["inclusion_reason"], "")
        self.assertEqual(item["operator_notes"], "")


# ---------------------------------------------------------------------------
# Skip-on-invalid behavior
# ---------------------------------------------------------------------------


class TestSkipInvalidArtifacts(unittest.TestCase):

    def _skipped_one(
        self, body_overrides: dict[str, Any],
        *, candidate_id: str = "cid-bad",
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            body = _well_formed_body()
            body.update(body_overrides)
            _write_artifact(d, candidate_id=candidate_id, body=body)
            envelope = cli.build_demo_daily_market(artifact_dir=tmp)
        self.assertEqual(envelope["items"], [])
        self.assertEqual(envelope["count"], 0)
        self.assertEqual(len(envelope["skipped_artifacts"]), 1)
        return envelope["skipped_artifacts"][0]

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
            envelope = cli.build_demo_daily_market(artifact_dir=tmp)
        self.assertEqual(envelope["items"], [])
        self.assertEqual(len(envelope["skipped_artifacts"]), 1)
        self.assertIn(
            "json", envelope["skipped_artifacts"][0]["reason"].lower(),
        )

    def test_skips_when_artifact_root_is_not_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "analyzed_event_artifact_cid-1.json").write_text(
                "[]", encoding="utf-8",
            )
            envelope = cli.build_demo_daily_market(artifact_dir=tmp)
        self.assertEqual(envelope["items"], [])
        self.assertEqual(len(envelope["skipped_artifacts"]), 1)

    def test_skipped_entry_carries_path_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "analyzed_event_artifact_cid-1.json").write_text(
                "not json {", encoding="utf-8",
            )
            envelope = cli.build_demo_daily_market(artifact_dir=tmp)
        entry = envelope["skipped_artifacts"][0]
        self.assertIn("path", entry)
        self.assertIn("reason", entry)
        self.assertIsInstance(entry["path"], str)
        self.assertIsInstance(entry["reason"], str)
        self.assertNotEqual(entry["reason"].strip(), "")


# ---------------------------------------------------------------------------
# File selection — only the artifact glob is loaded
# ---------------------------------------------------------------------------


class TestFileSelection(unittest.TestCase):

    def test_only_files_matching_artifact_glob_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(d, candidate_id="cid-1", body=_well_formed_body())
            (d / "freeze_candidate_evidence.json").write_text(
                json.dumps({"unrelated": True}), encoding="utf-8",
            )
            (d / "notes.txt").write_text("ignored", encoding="utf-8")
            envelope = cli.build_demo_daily_market(artifact_dir=tmp)
        self.assertEqual(envelope["count"], 1)
        self.assertEqual(envelope["skipped_artifacts"], [])


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicSort(unittest.TestCase):

    def test_items_sorted_by_event_date_then_candidate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
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
            items = cli.build_demo_daily_market(artifact_dir=tmp)["items"]
        order = [(it["event_date"], it["candidate_id"]) for it in items]
        self.assertEqual(order, [
            ("2026-04-30", "cid-mango"),
            ("2026-05-02", "cid-apple"),
            ("2026-05-02", "cid-zebra"),
        ])


# ---------------------------------------------------------------------------
# No artifact_dir / missing artifact_dir
# ---------------------------------------------------------------------------


class TestNoArtifactDirSupplied(unittest.TestCase):

    def test_no_artifact_dir_returns_empty_with_warning(self) -> None:
        envelope = cli.build_demo_daily_market(artifact_dir=None)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["items"], [])
        self.assertEqual(envelope["count"], 0)
        self.assertEqual(envelope["skipped_artifacts"], [])
        self.assertEqual(envelope["errors"], [])
        self.assertGreaterEqual(len(envelope["warnings"]), 1)
        self.assertIn(
            "artifact",
            " ".join(envelope["warnings"]).lower(),
        )

    def test_no_artifact_files_present_returns_ok_zero_with_warning(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            envelope = cli.build_demo_daily_market(artifact_dir=tmp)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["items"], [])
        self.assertEqual(envelope["count"], 0)
        self.assertEqual(envelope["skipped_artifacts"], [])
        self.assertGreaterEqual(len(envelope["warnings"]), 1)

    def test_missing_artifact_dir_surfaces_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "does_not_exist")
            envelope = cli.build_demo_daily_market(artifact_dir=missing)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["items"], [])
        self.assertGreaterEqual(len(envelope["errors"]), 1)


# ---------------------------------------------------------------------------
# Caution label — pinned constant on every item
# ---------------------------------------------------------------------------


class TestCautionLabel(unittest.TestCase):

    def test_caution_label_present_and_non_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(d, candidate_id="cid-1", body=_well_formed_body())
            item = cli.build_demo_daily_market(artifact_dir=tmp)["items"][0]
        self.assertIn("caution_label", item)
        self.assertIsInstance(item["caution_label"], str)
        self.assertTrue(item["caution_label"])

    def test_caution_label_is_module_constant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(d, candidate_id="cid-1", body=_well_formed_body())
            item = cli.build_demo_daily_market(artifact_dir=tmp)["items"][0]
        self.assertEqual(item["caution_label"], cli.CAUTION_LABEL)


# ---------------------------------------------------------------------------
# Filesystem isolation — read-only against the real artifacts/ dir
# ---------------------------------------------------------------------------


class TestRealArtifactsUntouched(unittest.TestCase):

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
        cli.build_demo_daily_market(artifact_dir=str(d))
        after = self._snapshot_dir(d)
        self.assertEqual(before, after)

    def test_local_demo_artifacts_surface_as_items(self) -> None:
        """With the current local artifacts (``daily-demo-001``,
        ``daily-demo-002``, ``daily-demo-003`` under ``artifacts/``),
        the source must surface all three as items.
        """
        d = _REPO_ROOT / "artifacts"
        if not d.is_dir():
            self.skipTest("real artifacts/ directory missing")
        envelope = cli.build_demo_daily_market(artifact_dir=str(d))
        self.assertTrue(envelope["ok"])
        cids = sorted(it["candidate_id"] for it in envelope["items"])
        for expected in (
            "daily-demo-001",
            "daily-demo-002",
            "daily-demo-003",
        ):
            self.assertIn(
                expected, cids,
                f"expected {expected!r} in surfaced items: {cids}",
            )


# ---------------------------------------------------------------------------
# Source-level read-only assertions on the module text
# ---------------------------------------------------------------------------


class TestModuleSurface(unittest.TestCase):

    def _read(self, rel: str) -> str:
        return (_REPO_ROOT / rel).read_text(encoding="utf-8")

    def test_no_paid_or_provider_imports(self) -> None:
        text = self._read("routes/demo_daily.py").lower()
        for banned in (
            "import yfinance",
            "from yfinance",
            "import market_data",
            "from market_data",
            "openai",
            "anthropic",
        ):
            self.assertNotIn(banned, text)

    def test_does_not_reference_news_inbox(self) -> None:
        text = self._read("routes/demo_daily.py").lower()
        self.assertNotIn("news_inbox", text)

    def test_does_not_call_write_or_delete_helpers(self) -> None:
        text = self._read("routes/demo_daily.py")
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

    def test_registered_under_demo_namespace_in_api_py(self) -> None:
        """The demo Daily source is wired in ``api.py`` under
        ``/demo/daily-market``.  This pin replaces the earlier
        "not-yet-registered" pin once the wiring landed.
        """
        api_text = self._read("api.py")
        self.assertIn("/demo/daily-market", api_text)
        self.assertIn("demo_daily", api_text)


# ---------------------------------------------------------------------------
# Import isolation — no DB / provider / LLM / FastAPI at module load
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):

    _BLOCKED: tuple[str, ...] = (
        "yfinance",
        "fastapi",
        "api",
        "market_data",
        "movers_cache",
        "db",
        "price_cache",
        "news_fetch",
        "openai",
        "anthropic",
    )

    def test_module_import_does_not_leak_banned_modules(self) -> None:
        from tests._import_isolation_check import (
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name="routes.demo_daily",
            blocked=self._BLOCKED,
            blocked_starts_with=(),
        )


# ---------------------------------------------------------------------------
# Conservative wording — banned tokens absent from emitted envelope
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):

    def _envelope_text(self, envelope: dict[str, Any]) -> str:
        return json.dumps(envelope, sort_keys=True, default=str).lower()

    def test_emitted_envelope_has_no_banned_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_artifact(d, candidate_id="cid-1", body=_well_formed_body())
            envelope = cli.build_demo_daily_market(artifact_dir=tmp)
        text = self._envelope_text(envelope)
        for banned in _BANNED_TOKENS:
            self.assertNotIn(
                banned, text,
                f"banned token {banned!r} in emitted envelope",
            )

    def test_caution_label_has_no_banned_tokens(self) -> None:
        label = cli.CAUTION_LABEL.lower()
        for banned in _BANNED_TOKENS:
            self.assertNotIn(
                banned, label,
                f"banned token {banned!r} in CAUTION_LABEL",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
