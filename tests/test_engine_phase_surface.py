"""Tests for engine-phase field surfacing on /events/{id} and /portfolio.

The engine emits ``mechanism_subtype``, ``quality_tier``,
``quality_warnings``, ``actionability_check``, ``counterfactual_check``,
``thesis_timing``, ``critical_breakpoints``, ``evidence_sources``,
``confidence_rationale``, and ``validation_rationale`` at finalize
time, but most of those fields are NOT persisted as DB columns.
``engine_phase_surface.decorate_full / decorate_compact`` re-derive
them on read so HTTP responses carry a stable engine shape.

These tests pin:

  * /events/{id} surfaces the full set with stable defaults on a
    saved event, even one whose row pre-dates the engine fields
    entirely (the "minimum row" path).
  * /portfolio rows surface the compact subset with the documented
    nested ``actionability_check.tradable`` shape.
  * Always-recompute is purely additive — no other documented keys
    in the response shape are removed or relabelled.
"""

from __future__ import annotations

import gc
import os
import shutil
import sys
import time
import unittest
import uuid
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db as _db
import engine_phase_surface as _surface


def _remove_temp_dir(path: str) -> None:
    last = None
    for _ in range(5):
        gc.collect()
        try:
            shutil.rmtree(path)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(0.05)
    if last is not None:
        raise last


class _RouteTestCase(unittest.TestCase):
    """TestClient against a temp DB with no LLM / market patches needed —
    routes under test only read the row back from the DB."""

    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient
        from api import app
        cls.client = TestClient(app)

    def setUp(self) -> None:
        self._orig = _db.DB_FILE
        self._tmp_dir = os.path.join(
            os.path.dirname(__file__),
            f"test_engine_phase_surface_{uuid.uuid4().hex}",
        )
        os.makedirs(self._tmp_dir)
        self._tmp = os.path.join(self._tmp_dir, "events.db")
        _db.DB_FILE = self._tmp
        _db.init_db()

    def tearDown(self) -> None:
        _db.DB_FILE = self._orig
        _remove_temp_dir(self._tmp_dir)


def _save_minimum_event(headline: str = "US imposes 25pct tariffs on Chinese steel") -> int:
    """Save a row with only the required NOT-NULL columns set so the
    engine-phase decorators have to fall back to defaults for nearly
    every field.  Returns the inserted event id.
    """
    _db.save_event({
        "headline":          headline,
        "stage":             "anticipation",
        "persistence":       "1d",
        "what_changed":      "Tariff escalation announced.",
        "mechanism_summary": "Tariff escalation announced.",
        "confidence":        "low",
        "event_date":        "2026-04-20",
    })
    rows = _db.load_recent_events(limit=1)
    return rows[0]["id"]


def _save_richer_event() -> int:
    """Save a row carrying a competing_thesis + hidden_mechanism so the
    nested-field lifting paths (``thesis_timing``,
    ``critical_breakpoints``, ``evidence_sources``) are exercised.
    """
    _db.save_event({
        "headline":          "OPEC announces production cut targets for 2026",
        "stage":             "anticipation",
        "persistence":       "1-5d",
        "what_changed":      "OPEC announces production cuts.",
        "mechanism_summary": "OPEC supply curtailment lifts crude prices.",
        "confidence":        "medium",
        "event_date":        "2026-04-21",
        "mechanism_family":  "energy_supply",
        "competing_thesis":  {
            "primary_thesis":     "OPEC discipline holds; crude rallies.",
            "alternative_thesis": "Cheating undercuts the cut.",
            "thesis_timing": {
                "first_signal_window": "1d",
                "confirmation_window": "1-5d",
                "primary_horizon":     "20d",
                "validation_window":   "20d",
            },
            "evidence_sources": [
                {"label": "OPEC press release", "kind": "primary"},
            ],
        },
        "hidden_mechanism":  {
            "bottleneck_type":   "supply_constraint",
            "transmission_type": "price",
            "channel_domain":    "energy",
            "critical_breakpoints": [
                {"condition": "Saudi reverses cut", "timing": "1-5d"},
            ],
        },
    })
    rows = _db.load_recent_events(limit=1)
    return rows[0]["id"]


# ---------------------------------------------------------------------------
# /events/{id} — full surface
# ---------------------------------------------------------------------------


_FULL_FIELDS = (
    "mechanism_subtype",
    "quality_tier",
    "quality_warnings",
    "actionability_check",
    "counterfactual_check",
    "thesis_timing",
    "critical_breakpoints",
    "evidence_sources",
    "confidence_rationale",
    "validation_rationale",
)


class EventDetailFullSurfaceTests(_RouteTestCase):
    def test_minimum_row_carries_every_field_with_default_shape(self) -> None:
        event_id = _save_minimum_event()
        r = self.client.get(f"/events/{event_id}")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        for f in _FULL_FIELDS:
            self.assertIn(f, body, f"missing engine-phase field '{f}'")
        # Type contracts — defaults must match the documented shape.
        self.assertIsInstance(body["quality_tier"], str)
        self.assertIsInstance(body["quality_warnings"], list)
        self.assertIsInstance(body["actionability_check"], dict)
        self.assertIsInstance(body["counterfactual_check"], dict)
        self.assertIsInstance(body["thesis_timing"], dict)
        self.assertIsInstance(body["critical_breakpoints"], list)
        self.assertIsInstance(body["evidence_sources"], list)
        self.assertIsInstance(body["confidence_rationale"], str)
        self.assertIsInstance(body["validation_rationale"], str)
        # mechanism_subtype is allowed to be None when no keyword matches.
        self.assertTrue(
            body["mechanism_subtype"] is None
            or isinstance(body["mechanism_subtype"], str)
        )
        # actionability_check carries the tradable boolean even on a
        # near-empty row — the decorator never returns the bare {}.
        self.assertIn("tradable", body["actionability_check"])
        self.assertIsInstance(body["actionability_check"]["tradable"], bool)

    def test_richer_row_lifts_competing_thesis_subfields(self) -> None:
        """``competing_thesis`` is a persisted JSON column, so its
        ``thesis_timing`` and ``evidence_sources`` sub-blocks survive a
        save / load round-trip and the decorator lifts them to top
        level.  ``hidden_mechanism`` is NOT persisted; the lift path
        for ``critical_breakpoints`` is exercised directly by
        ``DecorateFullDirectTests``.
        """
        event_id = _save_richer_event()
        r = self.client.get(f"/events/{event_id}")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(
            body["thesis_timing"].get("first_signal_window"), "1d",
        )
        self.assertTrue(
            isinstance(body["evidence_sources"], list)
            and len(body["evidence_sources"]) >= 1
        )
        self.assertEqual(
            body["evidence_sources"][0].get("label"), "OPEC press release",
        )
        # critical_breakpoints — empty default on the saved row because
        # hidden_mechanism is not a DB column.
        self.assertEqual(body["critical_breakpoints"], [])

    def test_pre_existing_keys_remain_stable(self) -> None:
        """The decorator is additive — none of the historically-present
        response keys (``id``, ``headline``, ``mechanism_family``,
        ``thesis_state``, ``proof_status``) get dropped or renamed."""
        event_id = _save_minimum_event()
        r = self.client.get(f"/events/{event_id}")
        body = r.json()
        for k in (
            "id", "headline", "stage", "persistence", "mechanism_family",
            "thesis_state", "thesis_state_reason", "proof_status",
            "falsifier_status", "macro_release_context",
            "policy_timing_context", "country_vulnerability_context",
        ):
            self.assertIn(k, body, f"pre-existing key '{k}' was dropped")


# ---------------------------------------------------------------------------
# /portfolio — compact surface
# ---------------------------------------------------------------------------


_COMPACT_FIELDS = (
    "quality_tier",
    "quality_warnings",
    "actionability_check",
    "mechanism_subtype",
    "thesis_state_reason",
)


class PortfolioCompactSurfaceTests(_RouteTestCase):
    def test_each_row_carries_compact_fields(self) -> None:
        _save_minimum_event(headline="Headline A — tariffs A")
        _save_richer_event()
        r = self.client.get("/portfolio")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        # Default response shape (no filter) is a bare list.
        self.assertIsInstance(body, list)
        self.assertGreaterEqual(len(body), 1)
        for entry in body:
            for f in _COMPACT_FIELDS:
                self.assertIn(f, entry, f"compact field '{f}' missing")
            self.assertIsInstance(entry["quality_tier"], str)
            self.assertIsInstance(entry["quality_warnings"], list)
            self.assertIsInstance(entry["actionability_check"], dict)
            self.assertIn("tradable", entry["actionability_check"])
            self.assertIsInstance(
                entry["actionability_check"]["tradable"], bool,
            )
            # Compact block ONLY carries tradable — surfacing more
            # would silently widen the contract.
            self.assertEqual(
                set(entry["actionability_check"].keys()), {"tradable"},
                "/portfolio actionability_check must carry only "
                "{'tradable': bool}; full block lives on /events/{id}",
            )
            self.assertTrue(
                entry["mechanism_subtype"] is None
                or isinstance(entry["mechanism_subtype"], str)
            )

    def test_pre_existing_portfolio_keys_remain_stable(self) -> None:
        _save_minimum_event(headline="Headline B — tariffs B")
        r = self.client.get("/portfolio")
        body = r.json()
        self.assertGreaterEqual(len(body), 1)
        entry = body[0]
        for k in (
            "id", "headline", "mechanism_family", "thesis_state",
            "thesis_state_reason", "validation_outcome", "relevance",
            "queues",
        ):
            self.assertIn(k, entry, f"pre-existing portfolio key '{k}' was dropped")


# ---------------------------------------------------------------------------
# Helper-level — no HTTP, exercise the decorator directly
# ---------------------------------------------------------------------------


class DecorateFullDirectTests(unittest.TestCase):
    def test_non_dict_input_returns_input_unchanged(self) -> None:
        for bad in (None, "x", 42, []):
            self.assertEqual(_surface.decorate_full(bad), bad)  # type: ignore[arg-type]

    def test_missing_fields_default_to_documented_shape(self) -> None:
        out = _surface.decorate_full({"mechanism_summary": "thin"})
        for f in _FULL_FIELDS:
            self.assertIn(f, out)
        self.assertEqual(out["thesis_timing"], {})
        self.assertEqual(out["critical_breakpoints"], [])
        self.assertEqual(out["evidence_sources"], [])
        self.assertEqual(out["validation_rationale"], "")

    def test_lifts_critical_breakpoints_from_hidden_mechanism(self) -> None:
        """Direct path: ``hidden_mechanism`` is not a DB column, but if
        an in-memory event carries it, the decorator lifts its
        ``critical_breakpoints`` list to the top level."""
        ev = {
            "mechanism_summary": "x",
            "hidden_mechanism": {
                "critical_breakpoints": [
                    {"condition": "trigger A", "timing": "1d"},
                ],
            },
        }
        out = _surface.decorate_full(ev)
        self.assertEqual(len(out["critical_breakpoints"]), 1)
        self.assertEqual(
            out["critical_breakpoints"][0]["condition"], "trigger A",
        )

    def test_lifts_thesis_timing_and_evidence_sources_from_competing(self) -> None:
        ev = {
            "mechanism_summary": "x",
            "competing_thesis": {
                "thesis_timing": {"first_signal_window": "1d"},
                "evidence_sources": [{"label": "src", "kind": "primary"}],
            },
        }
        out = _surface.decorate_full(ev)
        self.assertEqual(out["thesis_timing"]["first_signal_window"], "1d")
        self.assertEqual(out["evidence_sources"][0]["label"], "src")


class DecorateCompactDirectTests(unittest.TestCase):
    def test_non_dict_input_returns_full_default_shape(self) -> None:
        out = _surface.decorate_compact(None)  # type: ignore[arg-type]
        self.assertEqual(set(out.keys()), {
            "quality_tier", "quality_warnings",
            "actionability_check", "mechanism_subtype",
        })
        self.assertEqual(out["actionability_check"], {"tradable": False})

    def test_does_not_mutate_input(self) -> None:
        ev = {"mechanism_summary": "x"}
        before = dict(ev)
        _surface.decorate_compact(ev)
        self.assertEqual(ev, before)


if __name__ == "__main__":
    unittest.main()
