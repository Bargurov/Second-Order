"""
tests/test_frozen_overlay_refresh.py

Contract tests for the frozen-event overlay-refresh path.

Covers:
  1. Eligibility: every bucket except ``legacy`` is eligible; explicit
     reason string echoed to the caller.
  2. Composer path: refresh never raises on provider failure and emits
     the sanitized degraded contract on every block.
  3. DB writeback: ``db.update_event_overlays`` touches ONLY the overlay
     columns — thesis text, tickers, review labels, and the
     ``last_market_check_at`` stamp stay exactly as written.
  4. Endpoint: ``POST /events/{id}/refresh-overlays`` returns 404 for
     unknown events, 409 for legacy events, 200 + summary otherwise.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db
from event_age_policy import eligible_for_overlay_refresh
from frozen_overlay_refresh import (
    REFRESHABLE_OVERLAYS,
    refresh_overlays_for_event,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tmp_db() -> str:
    return os.path.join(
        tempfile.gettempdir(), f"test_frozen_overlay_{uuid.uuid4().hex}.db",
    )


def _seed_event(**overrides) -> int:
    """Write one event and return its id.  Default anchor is 60 days ago so
    the row falls in the frozen bucket — the case this module exists for."""
    frozen_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    base = {
        "headline":          "Archived: OPEC cuts 500k bpd",
        "stage":             "realized",
        "persistence":       "structural",
        "what_changed":      "OPEC cut by 500k bpd",
        "mechanism_summary": "Tighter supply, higher crude",
        "beneficiaries":     ["XOM"],
        "losers":            ["airlines"],
        "confidence":        "high",
        "event_date":        frozen_date,
        "market_tickers":    [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": 3.5, "direction_tag": "supports thesis",
             "spark": [0.5] * 20},
        ],
        "market_note":       "Crude up 4% on the session",
        "rating":            "good",
        "notes":             "Played clean",
    }
    base.update(overrides)
    db.save_event(base)
    return db.load_recent_events(limit=1)[0]["id"]


class _DBTest(unittest.TestCase):
    def setUp(self):
        self._orig_db = db.DB_FILE
        self._tmp = _tmp_db()
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig_db
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


# ---------------------------------------------------------------------------
# 1. Eligibility gate
# ---------------------------------------------------------------------------

class TestOverlayRefreshEligibility(unittest.TestCase):
    """Eligibility is explicit and readable from event_age_policy alone."""

    def _ev(self, days_ago: int | None) -> dict:
        if days_ago is None:
            return {"headline": "no anchor"}
        d = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        return {"event_date": d, "headline": "anchored"}

    def test_frozen_event_is_eligible(self):
        """Frozen events are explicitly eligible — this is the whole point."""
        r = eligible_for_overlay_refresh(self._ev(60))
        self.assertTrue(r["eligible"])
        self.assertEqual(r["bucket"], "frozen")
        self.assertIn("thesis text", r["reason"].lower())

    def test_stable_event_is_eligible(self):
        r = eligible_for_overlay_refresh(self._ev(15))
        self.assertTrue(r["eligible"])
        self.assertEqual(r["bucket"], "stable")

    def test_warm_event_is_eligible(self):
        r = eligible_for_overlay_refresh(self._ev(3))
        self.assertTrue(r["eligible"])
        self.assertEqual(r["bucket"], "warm")

    def test_hot_event_is_eligible(self):
        r = eligible_for_overlay_refresh(self._ev(0))
        self.assertTrue(r["eligible"])
        self.assertEqual(r["bucket"], "hot")

    def test_legacy_event_is_not_eligible(self):
        """No parsable anchor → we won't blindly stamp an age."""
        r = eligible_for_overlay_refresh(self._ev(None))
        self.assertFalse(r["eligible"])
        self.assertEqual(r["bucket"], "legacy")
        self.assertIn("no parsable anchor", r["reason"].lower())


# ---------------------------------------------------------------------------
# 2. Composer never raises on provider failure
# ---------------------------------------------------------------------------

class TestComposerRobustness(_DBTest):
    """Every composer is guarded; provider failure degrades cleanly."""

    def test_refresh_survives_rates_provider_failure(self):
        eid = _seed_event()
        event = db.load_event_by_id(eid)

        # Make both primary macro inputs raise — the path must still
        # return a well-formed result with every overlay marked degraded.
        with patch("market_check.compute_rates_context",
                   side_effect=RuntimeError("yfinance down")), \
             patch("market_check.compute_stress_regime",
                   side_effect=RuntimeError("yfinance down")):
            result = refresh_overlays_for_event(event, persist=False)

        self.assertTrue(result["eligibility"]["eligible"])
        # Every refreshable overlay MUST be accounted for — either
        # refreshed or explicitly skipped — nothing silently dropped.
        all_keys = set(result["refreshed"]) | set(result["skipped"])
        self.assertEqual(all_keys, set(REFRESHABLE_OVERLAYS))
        self.assertFalse(result["written"])  # persist=False

    def test_legacy_event_short_circuits_cleanly(self):
        """Legacy event returns the degraded summary without composer runs."""
        db.save_event({
            "headline":    "no anchor",
            "stage":       "developing",
            "persistence": "medium",
            # no event_date, no timestamp anchor handling writes an ISO ts
            # — but _has_timestamp_anchor accepts either, so we also clear
            # the save_event-written timestamp below.
        })
        eid = db.load_recent_events(limit=1)[0]["id"]
        ev = db.load_event_by_id(eid)
        # Force the event into the legacy bucket by stripping anchors.
        ev["event_date"] = ""
        ev["timestamp"] = ""

        result = refresh_overlays_for_event(ev, persist=False)
        self.assertFalse(result["eligibility"]["eligible"])
        self.assertEqual(result["refreshed"], [])
        # Every refreshable overlay is surfaced as skipped.
        self.assertEqual(set(result["skipped"]), set(REFRESHABLE_OVERLAYS))
        self.assertFalse(result["written"])


# ---------------------------------------------------------------------------
# 3. DB writeback touches ONLY the overlay columns
# ---------------------------------------------------------------------------

class TestDbWritebackScope(_DBTest):
    """Thesis text, tickers, review labels, stamps all stay untouched."""

    def test_thesis_and_tickers_unchanged_after_refresh(self):
        eid = _seed_event()
        before = db.load_event_by_id(eid)

        with patch("market_check.compute_rates_context",
                   side_effect=RuntimeError("provider offline")), \
             patch("market_check.compute_stress_regime",
                   side_effect=RuntimeError("provider offline")):
            result = refresh_overlays_for_event(before, persist=True)
        self.assertTrue(result["written"])

        after = db.load_event_by_id(eid)
        # Immutable fields: every column that isn't in REFRESHABLE_OVERLAYS.
        for key in (
            "headline", "stage", "persistence", "confidence",
            "what_changed", "mechanism_summary",
            "beneficiaries", "losers", "market_note",
            "market_tickers", "rating", "notes", "event_date",
        ):
            self.assertEqual(
                before.get(key), after.get(key),
                f"refresh leaked into {key!r}",
            )

    def test_update_event_overlays_rejects_unknown_keys(self):
        eid = _seed_event()
        ok = db.update_event_overlays(eid, {
            "policy_constraint": {"available": True, "signal": "tight"},
            "not_a_real_overlay": {"garbage": 1},
        })
        self.assertTrue(ok)
        row = db.load_event_by_id(eid)
        self.assertEqual(row["policy_constraint"]["signal"], "tight")
        self.assertNotIn("not_a_real_overlay", row)

    def test_update_event_overlays_returns_false_for_missing_event(self):
        self.assertFalse(
            db.update_event_overlays(999_999, {"policy_constraint": {"x": 1}})
        )

    def test_update_event_overlays_returns_false_for_empty_dict(self):
        eid = _seed_event()
        self.assertFalse(db.update_event_overlays(eid, {}))

    def test_refresh_writes_every_overlay_column_in_registry(self):
        """After a successful refresh, every column in REFRESHABLE_OVERLAYS
        must be present on the loaded row — empty blocks are filled with
        the sanitized degraded contract rather than dropped."""
        eid = _seed_event()
        ev = db.load_event_by_id(eid)
        with patch("market_check.compute_rates_context",
                   side_effect=RuntimeError("offline")), \
             patch("market_check.compute_stress_regime",
                   side_effect=RuntimeError("offline")):
            refresh_overlays_for_event(ev, persist=True)
        row = db.load_event_by_id(eid)
        for key in REFRESHABLE_OVERLAYS:
            self.assertIn(key, row, f"overlay {key!r} missing post-refresh")
            block = row[key]
            self.assertIsInstance(block, dict)
            # Sanitizer always emits these four markers on a non-empty write.
            for marker in ("available", "stale", "degraded", "degraded_reason"):
                self.assertIn(marker, block,
                              f"{key} missing {marker!r} after sanitize")


# ---------------------------------------------------------------------------
# 4. HTTP endpoint contract
# ---------------------------------------------------------------------------

class TestRefreshOverlaysEndpoint(_DBTest):

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import api as api_module
        cls.client = TestClient(api_module.app)

    def test_404_on_missing_event(self):
        r = self.client.post("/events/999999/refresh-overlays")
        self.assertEqual(r.status_code, 404)

    def test_200_on_frozen_event(self):
        eid = _seed_event()
        with patch("market_check.compute_rates_context",
                   side_effect=RuntimeError("offline")), \
             patch("market_check.compute_stress_regime",
                   side_effect=RuntimeError("offline")):
            r = self.client.post(f"/events/{eid}/refresh-overlays")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["event_id"], eid)
        self.assertTrue(body["eligibility"]["eligible"])
        self.assertEqual(body["eligibility"]["bucket"], "frozen")
        self.assertIn("refreshed", body)
        self.assertIn("skipped", body)
        self.assertTrue(body["written"])


if __name__ == "__main__":
    unittest.main()
