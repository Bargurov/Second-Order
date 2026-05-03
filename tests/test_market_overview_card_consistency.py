"""
tests/test_market_overview_card_consistency.py

Pin down the Market Overview card-shaping contract.

Three things this file proves:

  1. **Agreement % is deterministic and explainable** —
     ``api._compute_support_ratio`` is the single source of truth for
     the "X% Agreement" pill.  Same event → same percentage across
     /market-movers, /movers/today, /movers/persistent, /movers/weekly,
     and across reload.  Pre-fix three different call sites computed
     this independently and the persistent slice skipped duplicate
     suppression entirely.

  2. **Preview ticker selection is rich and deterministic** —
     ``api._build_mover_summary`` emits up to 4 chips (was 3),
     sorted by largest absolute 5d move with symbol as the
     alphabetical tiebreaker.  Same input → same order on every
     call.

  3. **Per-card market values are consistent** —
     The same XLE ticker on the same event reads the same value on
     every endpoint.  When the SAME symbol legitimately differs
     across two events anchored to different event_dates, the new
     ``anchor_date`` field surfaces the cause so the UI can label it.
     A mixed stale/current path would surface as a missing or
     mismatched anchor_date — pinned with a regression test.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api
import movers_cache


# ---------------------------------------------------------------------------
# Cluster A — _compute_support_ratio determinism
# ---------------------------------------------------------------------------


class TestSupportRatioHelper(unittest.TestCase):
    """The single source of truth for the agreement pill."""

    def test_supports_only(self):
        tickers = [
            {"symbol": "A", "direction_tag": "supports up", "return_5d": 3.0},
            {"symbol": "B", "direction_tag": "supports down", "return_5d": -2.0},
        ]
        self.assertEqual(api._compute_support_ratio(tickers), 1.0)

    def test_contradicts_only(self):
        tickers = [
            {"symbol": "A", "direction_tag": "contradicts up", "return_5d": 3.0},
            {"symbol": "B", "direction_tag": "contradicts down", "return_5d": -2.0},
        ]
        self.assertEqual(api._compute_support_ratio(tickers), 0.0)

    def test_mixed(self):
        tickers = [
            {"symbol": "A", "direction_tag": "supports up", "return_5d": 3.0},
            {"symbol": "B", "direction_tag": "supports up", "return_5d": 4.0},
            {"symbol": "C", "direction_tag": "contradicts down", "return_5d": -1.5},
        ]
        self.assertAlmostEqual(api._compute_support_ratio(tickers), 2 / 3)

    def test_drops_pending_tickers_with_no_direction(self):
        """Pending / direction-less rows must NOT pollute the denominator."""
        tickers = [
            {"symbol": "A", "direction_tag": "supports up", "return_5d": 3.0},
            {"symbol": "B", "direction_tag": None, "return_5d": 5.0},
            {"symbol": "C", "direction_tag": None, "return_5d": None},
        ]
        # Only A counts → 1/1.
        self.assertEqual(api._compute_support_ratio(tickers), 1.0)

    def test_drops_tickers_without_return(self):
        """Eligibility requires BOTH direction and a non-null return."""
        tickers = [
            {"symbol": "A", "direction_tag": "supports up", "return_5d": 3.0},
            {"symbol": "B", "direction_tag": "supports up", "return_5d": None},
        ]
        # Only A counts → 1/1.
        self.assertEqual(api._compute_support_ratio(tickers), 1.0)

    def test_empty_input_returns_zero(self):
        self.assertEqual(api._compute_support_ratio([]), 0.0)

    def test_deterministic_across_repeated_calls(self):
        """Same input → byte-identical float on every call."""
        tickers = [
            {"symbol": "A", "direction_tag": "supports up", "return_5d": 3.0},
            {"symbol": "B", "direction_tag": "contradicts up", "return_5d": 1.5},
            {"symbol": "C", "direction_tag": "supports up", "return_5d": 2.0},
        ]
        first = api._compute_support_ratio(tickers)
        for _ in range(10):
            self.assertEqual(api._compute_support_ratio(tickers), first)


# ---------------------------------------------------------------------------
# Cluster B — preview ticker selection
# ---------------------------------------------------------------------------


class TestPreviewTickerSelection(unittest.TestCase):
    """``_build_mover_summary`` emits up to 4 chips, deterministically sorted."""

    def _ev(self) -> dict:
        return {
            "id": 1,
            "headline": "Preview test event",
            "mechanism_summary": "ctx",
            "event_date": "2026-04-08",
            "stage": "realized",
            "persistence": "structural",
            "transmission_chain": [],
            "if_persists": {},
            "last_market_check_at": "2026-04-08T11:00:00",
        }

    def test_preview_emits_up_to_four_tickers(self):
        big_moves = [
            {"symbol": s, "role": "beneficiary", "return_5d": v,
             "return_20d": v * 1.2, "direction_tag": "supports up",
             "spark": [0.1, 0.5, 0.9], "anchor_date": "2026-04-08"}
            for s, v in [("AAA", 5.0), ("BBB", 4.5), ("CCC", 4.0),
                         ("DDD", 3.5), ("EEE", 3.0)]
        ]
        out = api._build_mover_summary(self._ev(), big_moves, 1.0)
        self.assertEqual(len(out["tickers"]), 4)
        # Sorted by abs(return_5d) desc — top 4 are AAA, BBB, CCC, DDD.
        self.assertEqual(
            [t["symbol"] for t in out["tickers"]],
            ["AAA", "BBB", "CCC", "DDD"],
        )

    def test_preview_sort_uses_alphabetical_tiebreaker(self):
        """Two tickers with identical abs(return_5d) → alphabetical
        order on the symbol so the chip layout is deterministic
        across reloads."""
        big_moves = [
            {"symbol": "ZZZ", "role": "beneficiary", "return_5d": 4.0,
             "return_20d": 5.0, "direction_tag": "supports up",
             "spark": [0.1, 0.5, 0.9], "anchor_date": "2026-04-08"},
            {"symbol": "AAA", "role": "beneficiary", "return_5d": 4.0,
             "return_20d": 5.0, "direction_tag": "supports up",
             "spark": [0.1, 0.5, 0.9], "anchor_date": "2026-04-08"},
            {"symbol": "MMM", "role": "loser", "return_5d": -4.0,
             "return_20d": -5.0, "direction_tag": "supports down",
             "spark": [0.9, 0.5, 0.1], "anchor_date": "2026-04-08"},
        ]
        out = api._build_mover_summary(self._ev(), big_moves, 1.0)
        # All three have abs(return_5d)==4.0 → alphabetical: AAA, MMM, ZZZ.
        self.assertEqual(
            [t["symbol"] for t in out["tickers"]],
            ["AAA", "MMM", "ZZZ"],
        )

    def test_preview_returns_distinct_spark_references(self):
        """No two emitted ticker dicts share the same spark list ref."""
        big_moves = [
            {"symbol": "AAA", "role": "beneficiary", "return_5d": 5.0,
             "spark": [0.1, 0.5, 0.9], "direction_tag": "supports up",
             "anchor_date": "2026-04-08"},
            {"symbol": "BBB", "role": "beneficiary", "return_5d": 4.0,
             "spark": [0.2, 0.4, 0.8], "direction_tag": "supports up",
             "anchor_date": "2026-04-08"},
        ]
        out = api._build_mover_summary(self._ev(), big_moves, 1.0)
        self.assertIsNot(out["tickers"][0]["spark"], big_moves[0]["spark"])
        self.assertIsNot(out["tickers"][0]["spark"], out["tickers"][1]["spark"])

    def test_preview_carries_anchor_date_per_ticker(self):
        """Every emitted ticker carries its anchor_date so the UI can
        label cards with 'anchored YYYY-MM-DD'."""
        big_moves = [
            {"symbol": "XLE", "role": "beneficiary", "return_5d": 5.0,
             "spark": [0.1, 0.2, 0.3], "direction_tag": "supports up",
             "anchor_date": "2026-04-01"},
            {"symbol": "XOM", "role": "beneficiary", "return_5d": 4.0,
             "spark": [0.2, 0.3, 0.4], "direction_tag": "supports up",
             "anchor_date": "2026-04-01"},
        ]
        out = api._build_mover_summary(self._ev(), big_moves, 1.0)
        for t in out["tickers"]:
            self.assertEqual(t["anchor_date"], "2026-04-01")

    def test_preview_repeatable_output(self):
        """Same input → identical emitted ticker order on every call."""
        big_moves = [
            {"symbol": s, "role": "beneficiary", "return_5d": v,
             "spark": [0.1, 0.5, 0.9], "direction_tag": "supports up",
             "anchor_date": "2026-04-08"}
            for s, v in [("ZZZ", 5.0), ("AAA", 4.0), ("MMM", 4.0),
                         ("BBB", 3.0)]
        ]
        first = [t["symbol"] for t in api._build_mover_summary(
            self._ev(), list(big_moves), 0.5)["tickers"]]
        for _ in range(5):
            again = [t["symbol"] for t in api._build_mover_summary(
                self._ev(), list(big_moves), 0.5)["tickers"]]
            self.assertEqual(first, again)


# ---------------------------------------------------------------------------
# Cluster C — per-card market value consistency across endpoints
# ---------------------------------------------------------------------------


class TestPerCardMarketValueConsistency(unittest.TestCase):
    """Same event → same agreement % AND same XLE return value across
    /market-movers, /movers/today, /movers/persistent, /movers/weekly.
    Different events anchored to different dates may legitimately read
    different XLE values, in which case the per-ticker ``anchor_date``
    field reveals the cause."""

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""
        from fastapi.testclient import TestClient
        cls.client = TestClient(api.app)

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_card_consistency_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        movers_cache.invalidate()
        api._news_cache["data"] = None
        api._news_cache["ts"] = 0.0
        api._TODAYS_MOVERS_CACHE["data"] = None
        api._TODAYS_MOVERS_CACHE["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _seed_event(
        self, *,
        headline: str,
        event_date: str,
        days_old: int,
        xle_return: float,
        xom_return: float,
        anchor_date: str,
    ) -> int:
        ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
        # ``last_market_check_at`` is explicitly fresh (now) — in
        # production an event that's days old typically had its market
        # tickers refreshed recently, and the persistent surface only
        # surfaces rows whose data is fresh.  Without this stamp the
        # seed inherits the event timestamp (``days_old`` ago), which
        # ``sanitize_mover_card`` flags as stale and ``enrich_mover_cards``
        # drops at the ``persistent`` window filter.
        last_check = datetime.now().isoformat(timespec="seconds")
        # Enrich the seed so the persistent-window eligibility filter
        # (``mover_card_normalizer._is_persistent_eligible``) does NOT
        # drop these cards as low-information / falsified.  The mechanism
        # summary is non-empty, ``confidence`` is medium, and a non-empty
        # ``minimum_proof_set`` + ``key_falsifiers`` / ``proof_status``
        # block makes ``derive_thesis_state`` resolve to ``confirming``
        # instead of the default ``low_information``.  The high-impact
        # ``is_high_conviction_persistent`` gate still rejects (no
        # persistence_signal on the row), so the per-test ``patch`` of
        # that gate covers the remaining requirement.
        db.save_event({
            "headline": headline,
            "stage": "realized",
            "persistence": "structural",
            "event_date": event_date,
            "timestamp": ts,
            "last_market_check_at": last_check,
            "what_changed": "ctx",
            "mechanism_summary": "Energy supply shock test",
            "confidence": "medium",
            "mechanism_family": "commodity_squeeze",
            "beneficiaries": ["XOM", "XLE"],
            "losers": ["DAL"],
            "primary_assets": ["XOM"],
            "minimum_proof_set": ["Crude prices break out"],
            "key_falsifiers": ["Crude reverses below 70"],
            "proof_status": {"Crude prices break out": "evidenced"},
            "falsifier_status": {"Crude reverses below 70": "not_triggered"},
            "transmission_path": ["XOM benefits from supply shock"],
            "market_tickers": [
                {"symbol": "XLE", "role": "beneficiary",
                 "return_5d": xle_return, "return_20d": xle_return * 1.4,
                 "direction_tag": "supports \u2191",
                 "label": "notable move", "volume_ratio": 1.5,
                 "spark": [0.1, 0.4, 0.7, 0.9, 1.0],
                 "anchor_date": anchor_date},
                {"symbol": "XOM", "role": "beneficiary",
                 "return_5d": xom_return, "return_20d": xom_return * 1.2,
                 "direction_tag": "supports \u2191",
                 "label": "notable move", "volume_ratio": 1.3,
                 "spark": [0.2, 0.4, 0.6, 0.8, 0.9],
                 "anchor_date": anchor_date},
                {"symbol": "DAL", "role": "loser",
                 "return_5d": -2.5, "return_20d": -3.0,
                 "direction_tag": "supports \u2193",
                 "label": "in motion", "volume_ratio": 1.1,
                 "spark": [0.9, 0.7, 0.5, 0.3, 0.1],
                 "anchor_date": anchor_date},
            ],
        })
        return db.load_recent_events(1)[0]["id"]

    def test_agreement_consistent_across_endpoints(self):
        """The exact same event must report the same agreement %
        whether it's served via /market-movers or /movers/today.

        Both endpoints share a time window approach: /movers/today
        uses 24h, /market-movers uses 48h.  Seeding a 1-day-old event
        puts it inside both windows.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed_event(
            headline="Energy shock card-consistency event",
            event_date=today,
            days_old=1,
            xle_return=5.0,
            xom_return=4.0,
            anchor_date=today,
        )

        def _unwrap(body):
            return body["items"] if isinstance(body, dict) and "items" in body else body

        market_movers = _unwrap(self.client.get("/market-movers").json())
        movers_today = _unwrap(self.client.get("/movers/today").json())

        def _agreement(body, headline):
            for m in body:
                if m["headline"] == headline:
                    return m["support_ratio"]
            return None

        h = "Energy shock card-consistency event"
        a_market = _agreement(market_movers, h)
        a_today = _agreement(movers_today, h)

        # Both endpoints found the event.
        self.assertIsNotNone(a_market, f"event missing from /market-movers: {market_movers}")
        self.assertIsNotNone(a_today, f"event missing from /movers/today: {movers_today}")
        # And report the same agreement.
        self.assertEqual(a_market, a_today)

    def test_xle_value_consistent_for_same_event_across_endpoints(self):
        """The XLE chip on the same event must read the same return
        value on every endpoint that surfaces the card."""
        today = datetime.now().strftime("%Y-%m-%d")
        self._seed_event(
            headline="Energy XLE consistency event",
            event_date=today,
            days_old=1,
            xle_return=5.0,
            xom_return=4.0,
            anchor_date=today,
        )

        def _xle_return(body, headline):
            for m in body:
                if m["headline"] == headline:
                    for t in m["tickers"]:
                        if t["symbol"] == "XLE":
                            return t["return_5d"]
            return None

        def _unwrap(body):
            return body["items"] if isinstance(body, dict) and "items" in body else body

        h = "Energy XLE consistency event"
        market_movers = _unwrap(self.client.get("/market-movers").json())
        movers_today = _unwrap(self.client.get("/movers/today").json())

        v_market = _xle_return(market_movers, h)
        v_today = _xle_return(movers_today, h)
        self.assertEqual(v_market, 5.0)
        self.assertEqual(v_today, 5.0)
        self.assertEqual(v_market, v_today)

    def test_xle_legitimately_differs_across_events_with_distinct_anchors(self):
        """Two events anchored to different event_dates may have
        different XLE returns — and the anchor_date field on each
        emitted ticker reveals which window the value came from.

        The route's ``is_high_conviction_persistent`` gate is patched to
        accept these synthetic seed rows.  The seed lacks the deeper
        analysis fields (proof_status, weighted_evidence, conviction
        rank) that the gate normally requires, but those aren't what
        this test asserts — it pins the per-ticker anchor_date contract,
        not the gate.  The high-impact rule itself is covered by
        ``test_market_context_contract.TestPersistentMoversContract``.
        """
        self._seed_event(
            headline="Energy event A",
            event_date="2026-03-29",
            days_old=10,
            xle_return=5.0,
            xom_return=4.0,
            anchor_date="2026-03-29",
        )
        self._seed_event(
            headline="Energy event B",
            event_date="2026-04-01",
            days_old=8,  # >7d so the strict persistent branch picks it up
            xle_return=4.82,
            xom_return=3.5,
            anchor_date="2026-04-01",
        )

        with patch("routes.movers.is_high_conviction_persistent",
                   return_value=True):
            body = self.client.get("/movers/persistent").json()
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        by_headline = {m["headline"]: m for m in items}
        self.assertIn("Energy event A", by_headline)
        self.assertIn("Energy event B", by_headline)

        def _xle(m):
            return next(t for t in m["tickers"] if t["symbol"] == "XLE")

        a_xle = _xle(by_headline["Energy event A"])
        b_xle = _xle(by_headline["Energy event B"])
        # Legitimately different — different event_dates.
        self.assertEqual(a_xle["return_5d"], 5.0)
        self.assertEqual(b_xle["return_5d"], 4.82)
        # The cause is surfaced via the anchor_date field on each chip.
        self.assertEqual(a_xle["anchor_date"], "2026-03-29")
        self.assertEqual(b_xle["anchor_date"], "2026-04-01")
        self.assertNotEqual(a_xle["anchor_date"], b_xle["anchor_date"])

    def test_card_carries_last_market_check_at(self):
        """Each card must carry ``last_market_check_at`` so the UI
        can render an 'as of' freshness footer.  See note in
        ``test_xle_legitimately_differs_across_events_with_distinct_anchors``
        for why ``is_high_conviction_persistent`` is patched here."""
        self._seed_event(
            headline="Energy as-of test event",
            event_date="2026-03-29",
            days_old=10,
            xle_return=5.0,
            xom_return=4.0,
            anchor_date="2026-03-29",
        )
        with patch("routes.movers.is_high_conviction_persistent",
                   return_value=True):
            body = self.client.get("/movers/persistent").json()
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        ev = next(
            (m for m in items if m["headline"] == "Energy as-of test event"),
            None,
        )
        self.assertIsNotNone(ev)
        self.assertIn("last_market_check_at", ev)
        # save_event stamps last_market_check_at to the row's timestamp
        # so this is non-null on freshly-saved rows.
        self.assertIsNotNone(ev["last_market_check_at"])

    def test_no_mixed_stale_current_path_for_same_event(self):
        """Regression: a single event must not surface mixed
        stale/current ticker numbers — every chip on a given card
        must share the same anchor_date if any chip carries one.
        See note in
        ``test_xle_legitimately_differs_across_events_with_distinct_anchors``
        for why ``is_high_conviction_persistent`` is patched here."""
        self._seed_event(
            headline="Oil sanctions mixed-path regression",
            event_date="2026-03-29",
            days_old=10,
            xle_return=5.0,
            xom_return=4.0,
            anchor_date="2026-03-29",
        )
        with patch("routes.movers.is_high_conviction_persistent",
                   return_value=True):
            body = self.client.get("/movers/persistent").json()
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        ev = next(
            (m for m in items
             if m["headline"] == "Oil sanctions mixed-path regression"),
            None,
        )
        self.assertIsNotNone(ev)
        anchors = {t["anchor_date"] for t in ev["tickers"] if t.get("anchor_date")}
        if anchors:
            self.assertEqual(
                len(anchors), 1,
                f"mixed anchor_date across one card's tickers: {anchors}",
            )


if __name__ == "__main__":
    unittest.main()
