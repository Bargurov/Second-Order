"""
tests/test_event_age_policy.py

Focused tests for the unified event-age TTL / freeze policy.

Covers the cases the task brief calls out:

  1. Short-TTL recent event (today/yesterday)  → "hot" bucket
  2. Medium-TTL week-old event                  → "warm" bucket
  3. Stable bucket (8-30 days)                  → "stable" bucket
  4. Frozen 30+ day event                       → "frozen" bucket
  5. Force-refresh override path                → bypasses freeze
  6. Legacy / missing-anchor row degrades cleanly
  7. Unchanged output contract for /analyze cached response
  8. _build_cached_response skips live macro recomputes for frozen events
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
import event_age_policy as eap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 4, 8, 12, 0, 0)


def _event(*, days_old: int, **overrides) -> dict:
    """Build an in-memory event dict the policy can classify."""
    now = _now()
    event_date = (now - timedelta(days=days_old)).strftime("%Y-%m-%d")
    base = {
        "id": 1,
        "headline": "Policy test",
        "stage": "realized",
        "persistence": "medium",
        "event_date": event_date,
        "timestamp": (now - timedelta(days=days_old)).isoformat(timespec="seconds"),
        "market_tickers": [
            {"symbol": "AAPL", "role": "beneficiary",
             "return_5d": 1.2, "return_20d": 2.3,
             "direction_tag": "supports \u2191"},
        ],
        "last_market_check_at": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. classify_event_age — pure bucket classification
# ---------------------------------------------------------------------------


class TestClassifyEventAge(unittest.TestCase):
    """The pure age → bucket mapping with TTL + frozen handling."""

    def test_today_event_is_hot_bucket(self):
        """Case 1a: today's event → hot, short TTL."""
        c = eap.classify_event_age(_event(days_old=0), now=_now())
        self.assertEqual(c["bucket"], "hot")
        self.assertEqual(c["natural_bucket"], "hot")
        self.assertEqual(c["event_age_days"], 0)
        self.assertEqual(c["ttl_seconds"], eap._HOT_TTL_SECONDS)
        self.assertFalse(c["is_frozen"])
        self.assertFalse(c["force_bypassed"])

    def test_yesterday_event_is_hot_bucket(self):
        """Case 1b: 1-day-old event also lands in the hot bucket."""
        c = eap.classify_event_age(_event(days_old=1), now=_now())
        self.assertEqual(c["bucket"], "hot")
        self.assertEqual(c["ttl_seconds"], eap._HOT_TTL_SECONDS)

    def test_two_day_event_is_warm_bucket(self):
        """Case 2: 2-day-old event → warm bucket, medium TTL."""
        c = eap.classify_event_age(_event(days_old=2), now=_now())
        self.assertEqual(c["bucket"], "warm")
        self.assertEqual(c["ttl_seconds"], eap._WARM_TTL_SECONDS)

    def test_week_old_event_is_warm_bucket(self):
        """7-day-old event still warm; 8 is the breakpoint."""
        c = eap.classify_event_age(_event(days_old=7), now=_now())
        self.assertEqual(c["bucket"], "warm")

    def test_eight_day_event_is_stable_bucket(self):
        """Case 3: 8-day-old event → stable bucket, long TTL."""
        c = eap.classify_event_age(_event(days_old=8), now=_now())
        self.assertEqual(c["bucket"], "stable")
        self.assertEqual(c["ttl_seconds"], eap._STABLE_TTL_SECONDS)

    def test_thirty_day_event_is_stable_bucket(self):
        """30 is the upper bound of stable; 31 is the freeze breakpoint."""
        c = eap.classify_event_age(_event(days_old=30), now=_now())
        self.assertEqual(c["bucket"], "stable")

    def test_frozen_event_no_force(self):
        """Case 4: 31-day-old event → frozen bucket, no TTL."""
        c = eap.classify_event_age(_event(days_old=31), now=_now())
        self.assertEqual(c["bucket"], "frozen")
        self.assertEqual(c["natural_bucket"], "frozen")
        self.assertIsNone(c["ttl_seconds"])
        self.assertTrue(c["is_frozen"])
        self.assertFalse(c["force_bypassed"])

    def test_old_frozen_event_no_force(self):
        """365-day-old event also frozen."""
        c = eap.classify_event_age(_event(days_old=365), now=_now())
        self.assertEqual(c["bucket"], "frozen")
        self.assertTrue(c["is_frozen"])

    def test_force_bypasses_frozen(self):
        """Case 5: force=True converts frozen → stable + flag."""
        c = eap.classify_event_age(_event(days_old=45), now=_now(), force=True)
        self.assertEqual(c["bucket"], "stable")
        self.assertEqual(c["natural_bucket"], "frozen")
        self.assertTrue(c["force_bypassed"])
        self.assertEqual(c["ttl_seconds"], eap._STABLE_TTL_SECONDS)
        # is_frozen still reflects the underlying truth so observability
        # layers can distinguish forced refreshes from natural live rows.
        self.assertTrue(c["is_frozen"])

    def test_force_on_warm_event_is_noop(self):
        """force=True on a non-frozen row leaves classification unchanged."""
        c = eap.classify_event_age(_event(days_old=3), now=_now(), force=True)
        self.assertEqual(c["bucket"], "warm")
        self.assertFalse(c["force_bypassed"])

    def test_legacy_no_anchor(self):
        """Case 6: row with no event_date or timestamp → legacy bucket."""
        ev = {"id": 1, "headline": "Legacy"}
        c = eap.classify_event_age(ev, now=_now())
        self.assertEqual(c["bucket"], "legacy")
        self.assertEqual(c["ttl_seconds"], 0)
        self.assertFalse(c["is_frozen"])

    def test_legacy_invalid_anchor(self):
        """Unparsable date strings still classify as legacy."""
        ev = {"id": 1, "headline": "Bad", "event_date": "not a date"}
        c = eap.classify_event_age(ev, now=_now())
        self.assertEqual(c["bucket"], "legacy")

    def test_future_event_clamps_to_zero(self):
        """A future event_date never produces a negative age."""
        ev = _event(days_old=-3)
        c = eap.classify_event_age(ev, now=_now())
        self.assertEqual(c["event_age_days"], 0)
        self.assertEqual(c["bucket"], "hot")

    def test_timestamp_fallback_when_event_date_missing(self):
        """Missing event_date falls back to the timestamp anchor."""
        ev = _event(days_old=5)
        ev["event_date"] = None
        c = eap.classify_event_age(ev, now=_now())
        self.assertEqual(c["event_age_days"], 5)
        self.assertEqual(c["bucket"], "warm")


class TestPolicyShortcuts(unittest.TestCase):
    """is_frozen and bucket_for_event convenience wrappers."""

    def test_is_frozen_for_frozen_event(self):
        self.assertTrue(eap.is_frozen(_event(days_old=45), now=_now()))

    def test_is_frozen_for_warm_event(self):
        self.assertFalse(eap.is_frozen(_event(days_old=3), now=_now()))

    def test_is_frozen_with_force(self):
        """is_frozen answers 'should I skip recompute' — force=True always False.

        The hot-path semantics: force=True means the caller opted in
        to a refresh, so from their perspective nothing is frozen.
        Observability layers that want the underlying natural state
        can call ``is_naturally_frozen`` or read ``natural_bucket``
        from classify_event_age directly.
        """
        self.assertFalse(
            eap.is_frozen(_event(days_old=45), now=_now(), force=True),
        )
        # classify_event_age still records the natural freeze via
        # natural_bucket / force_bypassed so telemetry keeps working.
        c = eap.classify_event_age(_event(days_old=45), now=_now(), force=True)
        self.assertEqual(c["bucket"], "stable")
        self.assertEqual(c["natural_bucket"], "frozen")
        self.assertTrue(c["force_bypassed"])
        # is_naturally_frozen ignores the caller's force flag.
        self.assertTrue(
            eap.is_naturally_frozen(_event(days_old=45), now=_now()),
        )

    def test_bucket_for_event(self):
        self.assertEqual(eap.bucket_for_event(_event(days_old=0), now=_now()), "hot")
        self.assertEqual(eap.bucket_for_event(_event(days_old=4), now=_now()), "warm")
        self.assertEqual(eap.bucket_for_event(_event(days_old=15), now=_now()), "stable")
        self.assertEqual(eap.bucket_for_event(_event(days_old=99), now=_now()), "frozen")


# ---------------------------------------------------------------------------
# 2. Cross-module consistency — market_check_freshness uses the same buckets
# ---------------------------------------------------------------------------


class TestPolicyMarketCheckIntegration(unittest.TestCase):
    """The two layers must agree on age + frozen for the same event."""

    def test_warm_event_agrees(self):
        import market_check_freshness as mcf
        ev = _event(days_old=3, last_market_check_at=None)
        ev["last_market_check_at"] = (
            _now() - timedelta(hours=1)
        ).isoformat(timespec="seconds")
        policy = eap.classify_event_age(ev, now=_now())
        staleness = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(policy["bucket"], "warm")
        self.assertEqual(staleness["status"], "fresh")
        # Same age view
        self.assertEqual(policy["event_age_days"], staleness["event_age_days"])

    def test_frozen_event_agrees(self):
        import market_check_freshness as mcf
        ev = _event(days_old=45)
        policy = eap.classify_event_age(ev, now=_now())
        staleness = mcf.compute_staleness(ev, now=_now())
        self.assertTrue(policy["is_frozen"])
        self.assertEqual(staleness["status"], "frozen")

    def test_hot_event_uses_market_check_recent_threshold(self):
        """The 4h market_check window covers hot + warm in one bucket.

        market_check_freshness intentionally collapses hot + warm into
        one "recent" decision so the existing 15.9% refresh-rate
        calibration (4h recent / 24h older) is preserved unchanged.
        """
        import market_check_freshness as mcf
        ev = _event(days_old=0)
        ev["last_market_check_at"] = (
            _now() - timedelta(hours=1)
        ).isoformat(timespec="seconds")
        staleness = mcf.compute_staleness(ev, now=_now())
        self.assertEqual(staleness["refresh_threshold_hours"], 4)


# ---------------------------------------------------------------------------
# 3. End-to-end: /analyze cached response respects the freeze policy
# ---------------------------------------------------------------------------


def _mock_analyze(headline, stage, persistence, event_context=""):
    return {
        "what_changed": "Stub what-changed.",
        "mechanism_summary": "Stub mechanism summary for unit tests.",
        "beneficiaries": ["CompanyA"],
        "losers": ["CompanyB"],
        "beneficiary_tickers": ["AAPL"],
        "loser_tickers": ["MSFT"],
        "assets_to_watch": ["AAPL", "MSFT"],
        "confidence": "medium",
        "transmission_chain": ["a", "b", "c"],
        "if_persists": {},
        "currency_channel": {},
    }


def _mock_market(beneficiary_tickers, loser_tickers, event_date=None):
    return {
        "note": "Stub market check.",
        "details": {},
        "tickers": [
            {"symbol": "AAPL", "role": "beneficiary", "label": "flat",
             "direction_tag": "supports \u2191",
             "return_1d": 0.1, "return_5d": 0.5, "return_20d": 1.2,
             "volume_ratio": 1.0, "vs_xle_5d": None, "spark": []},
        ],
    }


_CACHED_RESPONSE_PATCHES = [
    patch("api.analyze_event", side_effect=_mock_analyze),
    patch("api.market_check", side_effect=_mock_market),
]


class TestCachedResponseFreezePolicy(unittest.TestCase):
    """_build_cached_response should skip live macro for frozen events."""

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""  # mock path
        for p in _CACHED_RESPONSE_PATCHES:
            p.start()
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    @classmethod
    def tearDownClass(cls):
        for p in _CACHED_RESPONSE_PATCHES:
            p.stop()

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_event_age_policy_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        # Reset news cache so each test starts clean
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _post_analyze(self, headline: str, *, force: bool = False, event_date: str | None = None):
        if event_date is None:
            event_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        payload = {"headline": headline, "event_date": event_date, "force": force}
        return self.client.post("/analyze", json=payload)

    def _seeded_headline_for(self, days_old: int) -> tuple[str, str]:
        """Issue the first /analyze call to seed the cache via the real path.

        Returns (headline, event_date).  The analyse path uses the same
        model that ``_active_model()`` resolves to, so a second /analyze
        call with the same (headline, event_date) will land on the
        cached-response branch regardless of the in-test DB contents.
        """
        event_date = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%d")
        headline = f"Freeze policy test {uuid.uuid4().hex[:6]}"
        r = self.client.post(
            "/analyze",
            json={"headline": headline, "event_date": event_date},
        )
        self.assertEqual(r.status_code, 200, f"seed call failed: {r.text}")
        return headline, event_date

    def test_analyze_request_accepts_force_field(self):
        """The new optional force field is accepted by /analyze."""
        r = self.client.post(
            "/analyze",
            json={"headline": "Force field smoke test", "force": True},
        )
        self.assertEqual(r.status_code, 200)

    def test_analyze_request_force_defaults_to_false(self):
        """Existing /analyze callers don't need to know about force."""
        r = self.client.post(
            "/analyze",
            json={"headline": "Default force smoke test"},
        )
        self.assertEqual(r.status_code, 200)

    def test_cached_warm_event_recomputes_macro_overlays(self):
        """A 3-day-old cached event should still get live macro recomputes."""
        headline, warm_date = self._seeded_headline_for(days_old=3)
        # Second call lands on the cached-response path
        with patch.object(self.api, "compute_rates_context") as rates_mock, \
             patch.object(self.api, "compute_stress_regime") as stress_mock:
            rates_mock.return_value = {
                "regime": "Mixed", "real_yield": 0.5, "twoy_real": 0.4,
                "ten_year_breakeven": 2.4, "two_year_breakeven": 2.5,
                "policy_rate": 5.0, "available": True,
                "stale": False, "as_of": "2026-04-08",
            }
            stress_mock.return_value = {"regime": "Mixed", "available": True}
            r2 = self._post_analyze(headline, event_date=warm_date)

        self.assertEqual(r2.status_code, 200)
        body = r2.json()
        self.assertIn("freshness", body, f"freshness missing from: {list(body.keys())}")
        self.assertEqual(body["freshness"]["bucket"], "warm")
        self.assertFalse(body["freshness"]["is_frozen"])
        # On the warm cached path, live macro IS recomputed.
        self.assertGreaterEqual(rates_mock.call_count, 1)

    def test_cached_frozen_event_skips_live_macro_recomputes(self):
        """A 60-day-old cached event should NOT recompute live macro overlays."""
        headline, frozen_date = self._seeded_headline_for(days_old=60)

        # Second call lands on the cached-response path.  With the event
        # 60 days old it's in the frozen bucket; every macro recompute
        # should be skipped.
        with patch.object(self.api, "compute_rates_context") as rates_mock, \
             patch.object(self.api, "build_real_yield_context") as ryc_mock, \
             patch.object(self.api, "compute_policy_constraint") as pc_mock, \
             patch.object(self.api, "compute_shock_decomposition") as sd_mock, \
             patch.object(self.api, "compute_reaction_function_divergence") as rfd_mock, \
             patch.object(self.api, "compute_surprise_vs_anticipation") as sva_mock, \
             patch.object(self.api, "compute_terms_of_trade") as tot_mock:
            rates_mock.return_value = {"regime": "Mixed", "available": True}
            ryc_mock.return_value = {"available": True}
            pc_mock.return_value = {"available": True}
            sd_mock.return_value = {"available": True}
            rfd_mock.return_value = {"available": True}
            sva_mock.return_value = {"available": True}
            tot_mock.return_value = {"available": True}

            r2 = self._post_analyze(headline, event_date=frozen_date)

        self.assertEqual(r2.status_code, 200)
        body = r2.json()
        self.assertIn("freshness", body, f"freshness missing from: {list(body.keys())}")
        self.assertEqual(body["freshness"]["bucket"], "frozen")
        self.assertTrue(body["freshness"]["is_frozen"])
        # None of the live-macro helpers ran on the cached frozen path.
        self.assertEqual(rates_mock.call_count, 0,
                         "compute_rates_context should not run on a frozen cached event")
        self.assertEqual(ryc_mock.call_count, 0)
        self.assertEqual(pc_mock.call_count, 0)
        self.assertEqual(sd_mock.call_count, 0)
        self.assertEqual(rfd_mock.call_count, 0)
        self.assertEqual(sva_mock.call_count, 0)
        self.assertEqual(tot_mock.call_count, 0)

    def test_force_on_frozen_event_recomputes_macro(self):
        """force=True should re-enable the live macro recompute on frozen rows."""
        headline, frozen_date = self._seeded_headline_for(days_old=60)

        with patch.object(self.api, "compute_rates_context") as rates_mock, \
             patch.object(self.api, "build_real_yield_context") as ryc_mock:
            rates_mock.return_value = {
                "regime": "Mixed", "real_yield": 0.5, "twoy_real": 0.4,
                "available": True, "stale": False,
            }
            ryc_mock.return_value = {"available": True}
            # Force-refresh the cached frozen row
            r2 = self._post_analyze(headline, event_date=frozen_date, force=True)

        self.assertEqual(r2.status_code, 200)
        body = r2.json()
        self.assertIn("freshness", body)
        # Bucket reports the forced bypass
        self.assertEqual(body["freshness"]["natural_bucket"], "frozen")
        self.assertTrue(body["freshness"]["force_bypassed"])
        self.assertEqual(body["freshness"]["bucket"], "stable")
        # Live macro WAS recomputed
        self.assertGreaterEqual(rates_mock.call_count, 1)
        self.assertGreaterEqual(ryc_mock.call_count, 1)

    def test_cached_response_shape_unchanged(self):
        """The /analyze response keeps every existing top-level key.

        Adding the new `freshness` field is allowed by the task spec
        ("one tiny freshness/frozen field if truly needed"); it must
        not displace anything existing.
        """
        headline, warm_date = self._seeded_headline_for(days_old=3)
        # Second call lands on _build_cached_response
        r = self._post_analyze(headline, event_date=warm_date)
        body = r.json()
        for key in ("headline", "stage", "persistence", "analysis", "market",
                    "is_mock", "event_date"):
            self.assertIn(key, body)
        # Analysis sub-shape preserved
        for key in ("real_yield_context", "policy_constraint",
                    "shock_decomposition", "reaction_function_divergence",
                    "surprise_vs_anticipation", "terms_of_trade",
                    "historical_analogs"):
            self.assertIn(key, body["analysis"])
        # New freshness block present
        self.assertIn("freshness", body)
        for key in ("bucket", "natural_bucket", "event_age_days",
                    "is_frozen", "force_bypassed"):
            self.assertIn(key, body["freshness"])


if __name__ == "__main__":
    unittest.main()
