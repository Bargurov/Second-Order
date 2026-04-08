"""
tests/test_market_check_freshness.py

Regression tests for the event-age-aware market-check freshness layer.

Covers the five cases the task checklist calls out:

  1. Fresh event does not re-run market check
  2. Stale recent event re-runs on the 4h rule
  3. Stale older event re-runs on the 24h rule
  4. Frozen old event (> 30d) skips the refresh path
  5. Legacy row without last_market_check_at still works

Plus a few adjacent properties: the frozen cutoff can be bypassed with
``force=True``, tickers without any return data are classified legacy
regardless of age, and ``refresh_market_for_saved_event`` persists
through the injected writer so ``db.update_event_market_refresh`` is
only called when the row was actually refreshed.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import market_check_freshness as mcf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 4, 7, 12, 0, 0)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _make_event(
    *,
    days_old: int,
    last_check_hours_ago: int | None,
    with_return_data: bool = True,
    event_id: int = 1,
) -> dict:
    """Build an in-memory event dict the staleness helpers can consume."""
    now = _now()
    event_date = (now - timedelta(days=days_old)).strftime("%Y-%m-%d")
    last_check = (
        _iso(now - timedelta(hours=last_check_hours_ago))
        if last_check_hours_ago is not None else None
    )
    ticker: dict = {"symbol": "AAPL", "role": "beneficiary"}
    if with_return_data:
        ticker.update({
            "return_1d": 0.5, "return_5d": 2.0, "return_20d": 4.0,
            "direction_tag": "supports \u2191",
        })
    return {
        "id": event_id,
        "headline": "Freshness test event",
        "stage": "realized",
        "persistence": "medium",
        "event_date": event_date,
        "timestamp": _iso(now - timedelta(days=days_old)),
        "market_note": "",
        "market_tickers": [ticker],
        "last_market_check_at": last_check,
    }


# ---------------------------------------------------------------------------
# 1. Pure staleness: compute_staleness + should_refresh
# ---------------------------------------------------------------------------


class TestComputeStaleness(unittest.TestCase):
    """The pure age-aware decision function."""

    def test_fresh_recent_event_not_stale(self):
        """Recent event (< 7d), last check within 4h → fresh."""
        ev = _make_event(days_old=2, last_check_hours_ago=1)
        s = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(s["status"], "fresh")
        self.assertFalse(mcf.should_refresh(s))
        self.assertEqual(s["refresh_threshold_hours"], 4)

    def test_stale_recent_event_beyond_4h(self):
        """Recent event, last check 5h ago → stale (4h rule)."""
        ev = _make_event(days_old=2, last_check_hours_ago=5)
        s = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(s["status"], "stale")
        self.assertTrue(mcf.should_refresh(s))
        self.assertEqual(s["refresh_threshold_hours"], 4)

    def test_older_event_within_24h_is_fresh(self):
        """Older event (10d old), last check 6h ago → fresh on 24h rule."""
        ev = _make_event(days_old=10, last_check_hours_ago=6)
        s = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(s["status"], "fresh")
        self.assertFalse(mcf.should_refresh(s))
        self.assertEqual(s["refresh_threshold_hours"], 24)

    def test_older_event_past_24h_is_stale(self):
        """Older event, last check 25h ago → stale on 24h rule."""
        ev = _make_event(days_old=10, last_check_hours_ago=25)
        s = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(s["status"], "stale")
        self.assertTrue(mcf.should_refresh(s))

    def test_frozen_cutoff(self):
        """Event older than 30d with data → frozen, no refresh."""
        ev = _make_event(days_old=45, last_check_hours_ago=48)
        s = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(s["status"], "frozen")
        self.assertFalse(mcf.should_refresh(s))

    def test_force_bypasses_frozen_cutoff(self):
        """force=True converts frozen → stale so callers refresh on demand."""
        ev = _make_event(days_old=45, last_check_hours_ago=48)
        s = mcf.compute_staleness(ev, now=_now(), force=True)
        self.assertEqual(s["status"], "stale")
        self.assertEqual(s["natural_status"], "frozen")
        self.assertTrue(mcf.should_refresh(s))

    def test_legacy_no_last_check(self):
        """Row with no last_market_check_at → legacy, needs refresh."""
        ev = _make_event(days_old=2, last_check_hours_ago=None)
        ev["last_market_check_at"] = None
        s = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(s["status"], "legacy")
        self.assertTrue(mcf.should_refresh(s))

    def test_legacy_missing_return_data(self):
        """Row with tickers but no numeric returns is legacy regardless of age."""
        ev = _make_event(
            days_old=45, last_check_hours_ago=1, with_return_data=False,
        )
        s = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(s["status"], "legacy")
        self.assertTrue(mcf.should_refresh(s))

    def test_event_date_in_future_clamps_to_zero(self):
        """A future event_date should not produce a negative age."""
        ev = _make_event(days_old=-3, last_check_hours_ago=1)
        s = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(s["event_age_days"], 0)
        self.assertEqual(s["status"], "fresh")

    def test_empty_tickers_pass_through_rules(self):
        """A row with no tickers at all still goes through the normal rules."""
        ev = _make_event(days_old=2, last_check_hours_ago=1)
        ev["market_tickers"] = []
        s = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(s["status"], "fresh")

    def test_timestamp_fallback_for_missing_event_date(self):
        """When event_date is missing, timestamp drives the age calculation."""
        ev = _make_event(days_old=3, last_check_hours_ago=1)
        ev["event_date"] = None
        s = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(s["event_age_days"], 3)


# ---------------------------------------------------------------------------
# 2. Merge helper
# ---------------------------------------------------------------------------


class TestMergeFollowupIntoStored(unittest.TestCase):

    def test_overlays_return_fields(self):
        stored = [
            {"symbol": "AAPL", "role": "beneficiary", "label": "flat",
             "volume_ratio": 1.1, "spark": [0.1, 0.5, 0.9]},
        ]
        followup = [
            {"symbol": "AAPL", "role": "beneficiary", "return_1d": 0.5,
             "return_5d": 3.0, "return_20d": 5.0, "direction": "supports \u2191",
             "anchor_date": "2026-04-01"},
        ]
        merged = mcf._merge_followup_into_stored(stored, followup)
        self.assertEqual(len(merged), 1)
        row = merged[0]
        # Fresh return numbers spliced in
        self.assertEqual(row["return_5d"], 3.0)
        self.assertEqual(row["direction_tag"], "supports \u2191")
        # Original fields preserved
        self.assertEqual(row["label"], "flat")
        self.assertEqual(row["volume_ratio"], 1.1)
        self.assertEqual(row["spark"], [0.1, 0.5, 0.9])

    def test_passes_through_unmatched_tickers(self):
        stored = [
            {"symbol": "AAPL", "role": "beneficiary"},
            {"symbol": "XYZ", "role": "loser"},
        ]
        followup = [
            {"symbol": "AAPL", "role": "beneficiary", "return_5d": 1.0,
             "direction": "supports \u2191"},
        ]
        merged = mcf._merge_followup_into_stored(stored, followup)
        self.assertEqual(len(merged), 2)
        # XYZ has no follow-up match → passes through unchanged
        xyz = next(m for m in merged if m["symbol"] == "XYZ")
        self.assertNotIn("return_5d", xyz)

    def test_empty_stored_returns_empty(self):
        self.assertEqual(
            mcf._merge_followup_into_stored([], [{"symbol": "A"}]), [],
        )


# ---------------------------------------------------------------------------
# 3. Imperative refresh — provider dispatch + persistence
# ---------------------------------------------------------------------------


class TestRefreshMarketForSavedEvent(unittest.TestCase):
    """End-to-end wiring of compute_staleness → provider → persist."""

    def test_fresh_returns_without_calling_provider(self):
        """Case 1: fresh event does not re-run market check."""
        ev = _make_event(days_old=2, last_check_hours_ago=1)
        followup = MagicMock(name="followup_check")
        market = MagicMock(name="market_check")
        persist = MagicMock(name="persist", return_value=True)

        result = mcf.refresh_market_for_saved_event(
            ev, now=_now(),
            followup_check_fn=followup,
            market_check_fn=market,
            persist_fn=persist,
        )
        self.assertEqual(result["market_check_staleness"], "fresh")
        followup.assert_not_called()
        market.assert_not_called()
        persist.assert_not_called()
        # Stored tickers flow through unchanged
        self.assertEqual(result["tickers"][0]["return_5d"], 2.0)

    def test_stale_recent_refreshes_via_followup(self):
        """Case 2: stale recent event re-runs via followup_check + persist."""
        ev = _make_event(days_old=3, last_check_hours_ago=5)
        followup = MagicMock(
            name="followup_check",
            return_value=[
                {"symbol": "AAPL", "role": "beneficiary", "return_1d": 0.9,
                 "return_5d": 3.3, "return_20d": 6.6, "direction": "supports \u2191"},
            ],
        )
        persist = MagicMock(return_value=True)
        market = MagicMock(name="market_check")

        result = mcf.refresh_market_for_saved_event(
            ev, now=_now(),
            followup_check_fn=followup,
            market_check_fn=market,
            persist_fn=persist,
        )
        self.assertEqual(result["market_check_staleness"], "stale_refreshed")
        followup.assert_called_once()
        market.assert_not_called()
        persist.assert_called_once()
        # Fresh numbers appear on the returned row
        self.assertEqual(result["tickers"][0]["return_5d"], 3.3)
        self.assertIn("last_market_check_at", result)

    def test_stale_older_refreshes_on_24h_rule(self):
        """Case 3: stale older event (> 7d) refreshes on the 24h rule."""
        ev = _make_event(days_old=15, last_check_hours_ago=30)
        followup = MagicMock(
            return_value=[
                {"symbol": "AAPL", "role": "beneficiary", "return_5d": 4.2,
                 "return_20d": 8.4, "direction": "supports \u2191"},
            ],
        )
        persist = MagicMock(return_value=True)
        result = mcf.refresh_market_for_saved_event(
            ev, now=_now(),
            followup_check_fn=followup,
            market_check_fn=MagicMock(),
            persist_fn=persist,
        )
        self.assertEqual(result["market_check_staleness"], "stale_refreshed")
        followup.assert_called_once()
        self.assertEqual(result["tickers"][0]["return_5d"], 4.2)

    def test_older_event_within_24h_not_refreshed(self):
        """Older event with last check 12h ago → fresh, no refresh."""
        ev = _make_event(days_old=15, last_check_hours_ago=12)
        followup = MagicMock()
        persist = MagicMock()
        result = mcf.refresh_market_for_saved_event(
            ev, now=_now(),
            followup_check_fn=followup,
            market_check_fn=MagicMock(),
            persist_fn=persist,
        )
        self.assertEqual(result["market_check_staleness"], "fresh")
        followup.assert_not_called()
        persist.assert_not_called()

    def test_frozen_old_event_skipped(self):
        """Case 4: event older than 30d with data → skipped without force."""
        ev = _make_event(days_old=45, last_check_hours_ago=200)
        followup = MagicMock()
        persist = MagicMock()
        result = mcf.refresh_market_for_saved_event(
            ev, now=_now(),
            followup_check_fn=followup,
            market_check_fn=MagicMock(),
            persist_fn=persist,
        )
        self.assertEqual(result["market_check_staleness"], "frozen")
        followup.assert_not_called()
        persist.assert_not_called()
        # Stored tickers flow through unchanged
        self.assertEqual(result["tickers"][0]["return_5d"], 2.0)

    def test_frozen_bypassed_with_force(self):
        """force=True pushes a frozen row through the refresh path."""
        ev = _make_event(days_old=45, last_check_hours_ago=200)
        followup = MagicMock(
            return_value=[
                {"symbol": "AAPL", "role": "beneficiary", "return_5d": 7.0,
                 "return_20d": 9.0, "direction": "supports \u2191"},
            ],
        )
        persist = MagicMock(return_value=True)
        result = mcf.refresh_market_for_saved_event(
            ev, now=_now(), force=True,
            followup_check_fn=followup,
            market_check_fn=MagicMock(),
            persist_fn=persist,
        )
        self.assertEqual(result["market_check_staleness"], "forced_refreshed")
        followup.assert_called_once()
        persist.assert_called_once()
        self.assertEqual(result["tickers"][0]["return_5d"], 7.0)

    def test_legacy_row_without_metadata_still_works(self):
        """Case 5: row with last_market_check_at=None still refreshes cleanly."""
        ev = _make_event(days_old=4, last_check_hours_ago=None)
        ev["last_market_check_at"] = None
        followup = MagicMock(
            return_value=[
                {"symbol": "AAPL", "role": "beneficiary", "return_5d": 5.5,
                 "direction": "supports \u2191"},
            ],
        )
        persist = MagicMock(return_value=True)
        result = mcf.refresh_market_for_saved_event(
            ev, now=_now(),
            followup_check_fn=followup,
            market_check_fn=MagicMock(),
            persist_fn=persist,
        )
        self.assertEqual(result["market_check_staleness"], "legacy_refreshed")
        followup.assert_called_once()
        persist.assert_called_once()
        self.assertEqual(result["tickers"][0]["return_5d"], 5.5)

    def test_rolling_mode_calls_market_check_when_no_event_date(self):
        """Row without event_date uses market_check(bens, losers) rolling mode."""
        ev = _make_event(days_old=0, last_check_hours_ago=None)
        ev["event_date"] = None
        ev["last_market_check_at"] = None
        ev["timestamp"] = None

        market = MagicMock(return_value={
            "note": "rolling refreshed",
            "tickers": [
                {"symbol": "AAPL", "role": "beneficiary", "return_5d": 9.9},
            ],
        })
        followup = MagicMock()
        persist = MagicMock(return_value=True)

        result = mcf.refresh_market_for_saved_event(
            ev, now=_now(),
            followup_check_fn=followup,
            market_check_fn=market,
            persist_fn=persist,
        )
        self.assertEqual(result["market_check_staleness"], "legacy_refreshed")
        followup.assert_not_called()
        market.assert_called_once()
        self.assertEqual(result["tickers"][0]["return_5d"], 9.9)
        self.assertEqual(result["note"], "rolling refreshed")

    def test_provider_exception_returns_stored_payload(self):
        """Provider failure degrades cleanly to the stored tickers."""
        ev = _make_event(days_old=3, last_check_hours_ago=5)
        followup = MagicMock(side_effect=RuntimeError("yfinance down"))
        persist = MagicMock()
        result = mcf.refresh_market_for_saved_event(
            ev, now=_now(),
            followup_check_fn=followup,
            market_check_fn=MagicMock(),
            persist_fn=persist,
        )
        # Falls back to base payload with original staleness label
        self.assertEqual(result["market_check_staleness"], "stale")
        # Stored tickers preserved
        self.assertEqual(result["tickers"][0]["return_5d"], 2.0)
        persist.assert_not_called()


# ---------------------------------------------------------------------------
# 4. DB integration: schema + persistence end-to-end
# ---------------------------------------------------------------------------


class TestDbSchemaAndPersistence(unittest.TestCase):
    """Verify the migration + update helper round-trip through SQLite."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_freshness_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def test_save_event_stamps_last_market_check_at(self):
        """Newly saved events carry a non-null last_market_check_at."""
        db.save_event({
            "headline": "Freshness stamp smoke",
            "stage": "realized",
            "persistence": "medium",
            "event_date": "2026-04-06",
            "market_tickers": [
                {"symbol": "AAPL", "role": "beneficiary", "return_5d": 1.0},
            ],
        })
        ev = db.load_recent_events(1)[0]
        self.assertIsNotNone(ev.get("last_market_check_at"))
        self.assertIn("T", ev["last_market_check_at"])

    def test_update_event_market_refresh_writes_back(self):
        """update_event_market_refresh persists the refreshed payload."""
        db.save_event({
            "headline": "Refresh write target",
            "stage": "realized",
            "persistence": "medium",
            "event_date": "2026-04-06",
            "market_tickers": [
                {"symbol": "AAPL", "role": "beneficiary", "return_5d": 1.0},
            ],
        })
        eid = db.load_recent_events(1)[0]["id"]

        new_tickers = [
            {"symbol": "AAPL", "role": "beneficiary", "return_5d": 4.4,
             "return_20d": 8.8, "direction_tag": "supports \u2191"},
        ]
        ok = db.update_event_market_refresh(
            eid, new_tickers, "refreshed note", "2026-04-07T11:00:00",
        )
        self.assertTrue(ok)

        ev = db.load_event_by_id(eid)
        self.assertEqual(ev["market_tickers"][0]["return_5d"], 4.4)
        self.assertEqual(ev["market_note"], "refreshed note")
        self.assertEqual(ev["last_market_check_at"], "2026-04-07T11:00:00")

    def test_update_event_market_refresh_returns_false_for_missing_row(self):
        ok = db.update_event_market_refresh(
            99999, [], "", "2026-04-07T11:00:00",
        )
        self.assertFalse(ok)

    def test_refresh_end_to_end_persists_through_sqlite(self):
        """Full wiring: refresh_market_for_saved_event + db.update writes."""
        db.save_event({
            "headline": "End-to-end freshness",
            "stage": "realized",
            "persistence": "medium",
            "event_date": "2026-04-03",  # 4 days old on 2026-04-07
            "market_tickers": [
                {"symbol": "AAPL", "role": "beneficiary", "return_5d": 1.0},
            ],
        })
        eid = db.load_recent_events(1)[0]["id"]

        # Backdate the stamp so the row looks stale under the 4h rule
        import sqlite3
        with sqlite3.connect(db.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET last_market_check_at = ? WHERE id = ?",
                ("2026-04-07T06:00:00", eid),
            )

        ev = db.load_event_by_id(eid)
        followup = MagicMock(
            return_value=[
                {"symbol": "AAPL", "role": "beneficiary", "return_5d": 9.9,
                 "return_20d": 11.1, "direction": "supports \u2191"},
            ],
        )
        result = mcf.refresh_market_for_saved_event(
            ev, now=_now(),
            followup_check_fn=followup,
            market_check_fn=MagicMock(),
            # No persist_fn override → real db.update_event_market_refresh runs
        )
        self.assertEqual(result["market_check_staleness"], "stale_refreshed")

        # Re-load and confirm persistence
        reloaded = db.load_event_by_id(eid)
        self.assertEqual(reloaded["market_tickers"][0]["return_5d"], 9.9)
        self.assertNotEqual(
            reloaded["last_market_check_at"], "2026-04-07T06:00:00",
        )


if __name__ == "__main__":
    unittest.main()
