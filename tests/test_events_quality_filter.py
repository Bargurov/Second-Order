"""tests/test_events_quality_filter.py

Contract tests for the optional ``quality`` filter on ``GET /events``.

The filter narrows the archive listing to one of five operational
buckets so an operator can drill into archive quality without scrolling
the whole feed:

  - ``pending``        — analyzed but never market-checked.
  - ``degraded``       — degraded-fallback rows (thin LLM response).
  - ``no_tickers``     — market-check ran but produced no tickers.
  - ``market_checked`` — at least one ticker stored.
  - ``clean``          — market_checked AND not low_information.

Invariants:
  1) Default behavior is unchanged when ``quality`` is omitted.
  2) ``include_mock=true`` keeps working alongside ``quality``.
  3) ``quality=degraded`` is the documented opt-in to surface degraded
     rows; mock + demo stay hidden unless ``include_mock=true``.
  4) Buckets are mutually exclusive.  ``degraded`` takes precedence —
     a degraded row that happens to carry tickers is in ``degraded``,
     not ``market_checked``.
  5) ``/events/{id}`` keeps serving any row regardless of bucket — the
     filter narrows the listing only.
  6) ``total`` reflects the filtered universe so pagination math stays
     consistent.
  7) Invalid ``quality`` values return HTTP 400.

No LLM or market calls — events are seeded directly into a temp DB.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api
import movers_cache
from fastapi.testclient import TestClient

client = TestClient(api.app)


_DEGRADED_PREFIX = (
    "Model returned a thin response for this headline (no mechanism). "
    "Confidence forced to low and structured sections cleared."
)


def _tmp_db() -> str:
    return os.path.join(
        tempfile.gettempdir(), f"test_events_quality_{uuid.uuid4().hex}.db",
    )


def _reset_caches() -> None:
    movers_cache.invalidate()
    api._news_cache["data"] = None
    api._news_cache["ts"] = 0.0
    api._TODAYS_MOVERS_CACHE["data"] = None
    api._TODAYS_MOVERS_CACHE["ts"] = 0.0
    api._WEEKLY_MOVERS_CACHE["data"] = None
    api._YEARLY_MOVERS_CACHE["data"] = None
    api._PERSISTENT_MOVERS_CACHE["data"] = None


def _ticker(symbol: str = "XLE") -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "symbol": symbol,
        "role": "beneficiary",
        "return_5d": 4.0,
        "return_20d": 5.0,
        "direction_tag": "supports ↑",
        "spark": [0.1, 0.2, 0.3],
        "anchor_date": today,
    }


def _seed(
    *,
    headline: str,
    what_changed: str = "Real change description",
    model: str | None = None,
    days_old: int = 1,
    tickers: list[dict] | None = None,
    mechanism_summary: str = "Mechanism summary text long enough to pass.",
    transmission_chain: list[str] | None = None,
    if_persists: dict | None = None,
    confidence: str = "medium",
) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
    db.save_event({
        "headline": headline,
        "stage": "realized",
        "persistence": "structural",
        "event_date": today,
        "timestamp": ts,
        "what_changed": what_changed,
        "mechanism_summary": mechanism_summary,
        "model": model,
        "confidence": confidence,
        "transmission_chain": transmission_chain or ["a", "b"],
        "if_persists": if_persists or {"thesis": "stub"},
        "market_tickers": [_ticker()] if tickers is None else tickers,
    })
    return db.load_recent_events(1)[0]["id"]


def _clear_market_check_stamp(event_id: int) -> None:
    """Mark a seeded row as never-market-checked.

    ``db.save_event`` always stamps ``last_market_check_at`` (a row that
    has just been saved is, by definition, market-checked).  The
    ``pending`` quality bucket is the inverse of that — analyzed but
    never market-checked — so we have to clear the stamp directly to
    construct the fixture.
    """
    with sqlite3.connect(db.DB_FILE) as conn:
        conn.execute(
            "UPDATE events SET last_market_check_at = NULL WHERE id = ?",
            (event_id,),
        )
        conn.commit()


class _Base(unittest.TestCase):

    def setUp(self) -> None:
        os.environ.setdefault("ANTHROPIC_API_KEY", "")
        self._orig = db.DB_FILE
        self._tmp = _tmp_db()
        db.DB_FILE = self._tmp
        db.init_db()
        _reset_caches()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig
        _reset_caches()
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    # ------------------------------------------------------------------
    # Bucket-specific seeding helpers — each produces a row that lands
    # in exactly one of the five quality buckets.
    # ------------------------------------------------------------------

    def _seed_clean(self, headline: str = "Clean Fed decision") -> int:
        """Real, market-checked, NOT low-information."""
        return _seed(
            headline=headline,
            tickers=[_ticker("XLE"), _ticker("XOM")],
            mechanism_summary=(
                "A clearly-written mechanism that walks through how the "
                "policy change transmits into commodity flows and front-"
                "end rates, with enough detail to clear the low-info gate."
            ),
            transmission_chain=["policy", "rates", "commodity"],
            if_persists={"thesis": "rates higher for longer", "horizon": "3m"},
            confidence="high",
        )

    def _seed_market_checked_low_info(
        self, headline: str = "Market-checked but thin",
    ) -> int:
        """Has tickers but row is otherwise sparse → low_information=True."""
        return _seed(
            headline=headline,
            mechanism_summary="",
            transmission_chain=[],
            if_persists={},
            confidence="low",
            tickers=[_ticker("XLE")],
        )

    def _seed_no_tickers(
        self, headline: str = "No-tickers row",
    ) -> int:
        """Market-check ran (last_market_check_at stamped) but no tickers."""
        return _seed(headline=headline, tickers=[])

    def _seed_pending(self, headline: str = "Pending row") -> int:
        """Analyzed but never market-checked — last_market_check_at=NULL."""
        eid = _seed(headline=headline, tickers=[])
        _clear_market_check_stamp(eid)
        return eid

    def _seed_degraded(
        self, headline: str = "Degraded row", with_tickers: bool = False,
    ) -> int:
        """Degraded-fallback row.  ``with_tickers`` proves bucket precedence."""
        return _seed(
            headline=headline,
            what_changed=_DEGRADED_PREFIX,
            tickers=[_ticker("XLE")] if with_tickers else [],
        )

    def _seed_mock(self, headline: str = "Mock row") -> int:
        return _seed(headline=headline, what_changed="[mock: overloaded]")

    def _seed_demo(self, headline: str = "[DEMO] Showcase") -> int:
        return _seed(headline=headline)


# --------------------------------------------------------------------------
# Per-bucket selection — each filter returns ONLY its bucket.
# --------------------------------------------------------------------------

class TestQualityBucketSelection(_Base):

    def test_clean_filter_returns_only_clean_rows(self) -> None:
        clean_id = self._seed_clean()
        self._seed_market_checked_low_info()
        self._seed_no_tickers()
        self._seed_pending()

        body = client.get("/events?quality=clean").json()
        ids = [e["id"] for e in body["items"]]
        self.assertEqual(ids, [clean_id])
        self.assertEqual(body["total"], 1)

    def test_market_checked_filter_returns_rows_with_tickers(self) -> None:
        clean_id = self._seed_clean()
        thin_id = self._seed_market_checked_low_info()
        self._seed_no_tickers()
        self._seed_pending()

        body = client.get("/events?quality=market_checked").json()
        ids = sorted(e["id"] for e in body["items"])
        self.assertEqual(ids, sorted([clean_id, thin_id]))
        self.assertEqual(body["total"], 2)

    def test_no_tickers_filter_returns_only_market_checked_empty(self) -> None:
        self._seed_clean()
        no_id = self._seed_no_tickers()
        self._seed_pending()

        body = client.get("/events?quality=no_tickers").json()
        ids = [e["id"] for e in body["items"]]
        self.assertEqual(ids, [no_id])
        self.assertEqual(body["total"], 1)

    def test_pending_filter_returns_only_unstamped_rows(self) -> None:
        self._seed_clean()
        self._seed_no_tickers()
        pending_id = self._seed_pending()

        body = client.get("/events?quality=pending").json()
        ids = [e["id"] for e in body["items"]]
        self.assertEqual(ids, [pending_id])
        self.assertEqual(body["total"], 1)

    def test_degraded_filter_surfaces_degraded_rows_alone(self) -> None:
        """Default suppression hides degraded rows; the ``quality=degraded``
        opt-in surfaces them without requiring ``include_mock=true``."""
        self._seed_clean()
        degraded_id = self._seed_degraded()

        body = client.get("/events?quality=degraded").json()
        ids = [e["id"] for e in body["items"]]
        self.assertEqual(ids, [degraded_id])
        self.assertEqual(body["total"], 1)

    def test_degraded_filter_keeps_mock_and_demo_hidden(self) -> None:
        """Carve-out is degraded-only — mock + demo stay suppressed
        unless ``include_mock=true`` is also set."""
        degraded_id = self._seed_degraded()
        self._seed_mock()
        self._seed_demo()

        body = client.get("/events?quality=degraded").json()
        ids = [e["id"] for e in body["items"]]
        self.assertEqual(ids, [degraded_id])
        self.assertEqual(body["total"], 1)


# --------------------------------------------------------------------------
# Bucket precedence — degraded wins over data-state buckets.
# --------------------------------------------------------------------------

class TestDegradedTakesPrecedence(_Base):

    def test_degraded_with_tickers_stays_in_degraded_bucket(self) -> None:
        clean_id = self._seed_clean()
        degraded_with_tx = self._seed_degraded(with_tickers=True)

        # market_checked should NOT include the degraded-with-tickers row.
        mc_body = client.get("/events?quality=market_checked").json()
        mc_ids = [e["id"] for e in mc_body["items"]]
        self.assertEqual(mc_ids, [clean_id])
        self.assertNotIn(degraded_with_tx, mc_ids)

        # degraded SHOULD include it.
        deg_body = client.get("/events?quality=degraded").json()
        self.assertEqual(
            [e["id"] for e in deg_body["items"]], [degraded_with_tx],
        )


# --------------------------------------------------------------------------
# Default behavior unchanged — listing without ``quality`` is identical.
# --------------------------------------------------------------------------

class TestDefaultBehaviorUnchanged(_Base):

    def test_default_listing_total_unchanged_when_quality_absent(self) -> None:
        clean_id = self._seed_clean()
        thin_id = self._seed_market_checked_low_info()
        no_id = self._seed_no_tickers()
        pending_id = self._seed_pending()
        # Polluted rows should stay hidden by default.
        self._seed_degraded()
        self._seed_mock()
        self._seed_demo()

        body = client.get("/events").json()
        ids = sorted(e["id"] for e in body["items"])
        self.assertEqual(
            ids, sorted([clean_id, thin_id, no_id, pending_id]),
        )
        self.assertEqual(body["total"], 4)


# --------------------------------------------------------------------------
# include_mock=true preserved.  When combined with quality=, the quality
# filter narrows further.
# --------------------------------------------------------------------------

class TestIncludeMockInteraction(_Base):

    def test_include_mock_alone_unchanged(self) -> None:
        self._seed_clean()
        self._seed_mock()
        self._seed_demo()
        self._seed_degraded()

        body = client.get("/events?include_mock=true").json()
        # All four show up; existing ``include_mock`` contract preserved.
        self.assertEqual(body["total"], 4)

    def test_include_mock_plus_quality_degraded_narrows(self) -> None:
        clean_id = self._seed_clean()
        mock_id = self._seed_mock()
        degraded_id = self._seed_degraded()

        body = client.get("/events?include_mock=true&quality=degraded").json()
        ids = [e["id"] for e in body["items"]]
        self.assertEqual(ids, [degraded_id])
        self.assertNotIn(clean_id, ids)
        self.assertNotIn(mock_id, ids)

    def test_quality_pending_without_include_mock_excludes_mock(self) -> None:
        """A mock-flavoured pending row stays hidden under
        ``quality=pending`` because mock suppression still applies."""
        real_pending = self._seed_pending(headline="Real pending row")
        mock_pending_id = _seed(
            headline="Mock pending row",
            what_changed="[mock: overloaded]",
            tickers=[],
        )
        _clear_market_check_stamp(mock_pending_id)

        body = client.get("/events?quality=pending").json()
        ids = [e["id"] for e in body["items"]]
        self.assertEqual(ids, [real_pending])
        self.assertEqual(body["total"], 1)

    def test_quality_pending_with_include_mock_includes_mock(self) -> None:
        real_pending = self._seed_pending(headline="Real pending row")
        mock_pending_id = _seed(
            headline="Mock pending row",
            what_changed="[mock: overloaded]",
            tickers=[],
        )
        _clear_market_check_stamp(mock_pending_id)

        body = client.get("/events?include_mock=true&quality=pending").json()
        ids = sorted(e["id"] for e in body["items"])
        self.assertEqual(ids, sorted([real_pending, mock_pending_id]))
        self.assertEqual(body["total"], 2)


# --------------------------------------------------------------------------
# /events/{id} keeps serving all rows regardless of bucket.
# --------------------------------------------------------------------------

class TestDetailByIdAlwaysServes(_Base):

    def test_pending_row_excluded_by_clean_still_served_by_id(self) -> None:
        pending_id = self._seed_pending()
        list_ids = [
            e["id"]
            for e in client.get("/events?quality=clean").json()["items"]
        ]
        self.assertNotIn(pending_id, list_ids)
        # Detail by id still 200s.
        resp = client.get(f"/events/{pending_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], pending_id)

    def test_degraded_row_served_by_id_even_without_filter(self) -> None:
        degraded_id = self._seed_degraded()
        # Hidden from default listing.
        body = client.get("/events").json()
        self.assertNotIn(degraded_id, [e["id"] for e in body["items"]])
        # But detail still 200s.
        resp = client.get(f"/events/{degraded_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], degraded_id)


# --------------------------------------------------------------------------
# Pagination — total reflects post-filter universe.
# --------------------------------------------------------------------------

class TestPaginationReflectsFilter(_Base):

    def test_total_matches_filtered_count_with_offset_limit(self) -> None:
        clean_ids = [self._seed_clean(headline=f"Clean #{i}") for i in range(3)]
        # Add some non-clean rows that should NOT inflate total.
        self._seed_market_checked_low_info()
        self._seed_pending()
        self._seed_no_tickers()

        body = client.get("/events?quality=clean&limit=2&offset=0").json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["limit"], 2)
        self.assertEqual(body["offset"], 0)
        self.assertTrue(
            all(item["id"] in clean_ids for item in body["items"]),
        )

        body2 = client.get("/events?quality=clean&limit=2&offset=2").json()
        self.assertEqual(body2["total"], 3)
        self.assertEqual(len(body2["items"]), 1)


# --------------------------------------------------------------------------
# Invalid value handling.
# --------------------------------------------------------------------------

class TestInvalidQualityValue(_Base):

    def test_unknown_value_returns_400(self) -> None:
        resp = client.get("/events?quality=bogus")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("quality", resp.text.lower())


if __name__ == "__main__":
    unittest.main()
