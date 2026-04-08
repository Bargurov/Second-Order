"""
tests/test_freeze_policy_contract.py

End-to-end tests for the freeze-policy contract fix.

Covers:

  1. Frozen cached event keeps its persisted overlay blocks
     (DB persistence + load-path round-trip).
  2. Fresh vs cached /analyze response parity:
     - identical top-level key set
     - identical market-freshness field set
     - identical freshness block shape
  3. Force / frozen semantics on event_age_policy.is_frozen:
     - force=True on a frozen row returns False
       (the caller opted in to a refresh)
     - is_naturally_frozen always reports the underlying truth
  4. Frontend/backend typing contract:
     - api.ts carries AnalyzeRequest.force
     - api.ts carries AnalyzeResponse.freshness
     - api.ts carries MarketResult freshness fields
     - api.ts carries BacktestResult freshness fields
"""

from __future__ import annotations

import json
import os
import re
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


def _mock_analyze(headline, stage, persistence, event_context=""):
    return {
        "what_changed": "Stub change text.",
        "mechanism_summary": "Stub mechanism for contract tests.",
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
            {
                "symbol": "AAPL", "role": "beneficiary", "label": "flat",
                "direction_tag": "supports \u2191",
                "return_1d": 0.1, "return_5d": 0.5, "return_20d": 1.2,
                "volume_ratio": 1.0, "vs_xle_5d": None, "spark": [],
            },
        ],
    }


_CONTRACT_PATCHES = [
    patch("api.analyze_event", side_effect=_mock_analyze),
    patch("api.market_check", side_effect=_mock_market),
]


# ---------------------------------------------------------------------------
# Case 1 — DB persistence + load-path round-trip for macro overlays
# ---------------------------------------------------------------------------


class TestOverlayPersistence(unittest.TestCase):
    """Macro overlay blocks must round-trip through save_event / load_*."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_freeze_contract_{uuid.uuid4().hex}.db",
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

    def _save_rich_event(self, *, event_date: str) -> int:
        """Save an event with every overlay block populated."""
        db.save_event({
            "headline": f"Rich event {uuid.uuid4().hex[:6]}",
            "stage": "realized",
            "persistence": "structural",
            "what_changed": "ctx",
            "mechanism_summary": "mech",
            "beneficiaries": ["A"],
            "losers": ["B"],
            "beneficiary_tickers": ["AAPL"],
            "loser_tickers": ["MSFT"],
            "assets_to_watch": ["AAPL", "MSFT"],
            "confidence": "high",
            "market_note": "note",
            "market_tickers": [
                {"symbol": "AAPL", "role": "beneficiary",
                 "return_5d": 2.1, "direction_tag": "supports \u2191"},
            ],
            "event_date": event_date,
            "transmission_chain": ["a", "b", "c"],
            "if_persists": {"horizon": "months"},
            "currency_channel": {"pair": "USD/CNY"},
            "policy_sensitivity": {"stance": "neutral"},
            "inventory_context": {"status": "tight"},
            "regime_snapshot": {"available": True, "inflation": "cool"},
            # Macro overlays
            "real_yield_context": {
                "available": True, "thesis": "inflationary", "alignment": "confirm",
            },
            "policy_constraint": {
                "available": True, "binding": "inflation", "policy_room": "limited",
            },
            "shock_decomposition": {
                "available": True, "primary": "nominal_yield",
            },
            "reaction_function_divergence": {
                "available": True, "implied": "hawkish", "priced": "dovish",
                "divergence": "mild",
            },
            "surprise_vs_anticipation": {
                "available": True, "regime": "mixed",
            },
            "terms_of_trade": {
                "available": True, "dominant_channel": "oil_import",
                "signals": {"crude_5d": 5.0, "dxy_5d": 1.2},
            },
            "reserve_stress": {
                "available": True, "dominant_channel": "dual_oil_dollar",
                "pressure_score": 75, "pressure_label": "elevated",
            },
        })
        return db.load_recent_events(1)[0]["id"]

    def test_save_and_load_by_id_roundtrip(self):
        """load_event_by_id decodes every overlay block."""
        eid = self._save_rich_event(event_date="2025-10-01")
        ev = db.load_event_by_id(eid)

        self.assertIsNotNone(ev)
        for field in (
            "real_yield_context", "policy_constraint", "shock_decomposition",
            "reaction_function_divergence", "surprise_vs_anticipation",
            "terms_of_trade", "reserve_stress",
        ):
            self.assertIsInstance(ev[field], dict)
            self.assertTrue(
                ev[field].get("available"),
                f"{field} should round-trip available=True",
            )

        self.assertEqual(ev["real_yield_context"]["thesis"], "inflationary")
        self.assertEqual(ev["policy_constraint"]["binding"], "inflation")
        self.assertEqual(ev["shock_decomposition"]["primary"], "nominal_yield")
        self.assertEqual(ev["reaction_function_divergence"]["implied"], "hawkish")
        self.assertEqual(ev["surprise_vs_anticipation"]["regime"], "mixed")
        self.assertEqual(ev["terms_of_trade"]["dominant_channel"], "oil_import")
        self.assertEqual(ev["reserve_stress"]["pressure_score"], 75)

    def test_load_recent_events_decodes_overlays(self):
        """The bulk list loader must decode the same set of overlays."""
        self._save_rich_event(event_date="2025-10-01")
        rows = db.load_recent_events(1)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["reserve_stress"]["dominant_channel"], "dual_oil_dollar")
        self.assertEqual(row["terms_of_trade"]["signals"]["crude_5d"], 5.0)

    def test_find_cached_analysis_decodes_overlays(self):
        """The cached-analysis lookup path also decodes overlays."""
        self._save_rich_event(event_date="2025-10-01")
        ev = db.load_recent_events(1)[0]
        cached = db.find_cached_analysis(
            ev["headline"], event_date="2025-10-01", model=None,
        )
        self.assertIsNotNone(cached)
        self.assertEqual(
            cached["policy_constraint"]["policy_room"], "limited",
        )
        self.assertEqual(
            cached["reserve_stress"]["pressure_label"], "elevated",
        )

    def test_missing_overlays_default_to_empty_dicts(self):
        """Events saved without overlays still decode to {}."""
        db.save_event({
            "headline": "Sparse event",
            "stage": "realized",
            "persistence": "medium",
            "event_date": "2025-10-01",
            "market_tickers": [
                {"symbol": "AAPL", "role": "beneficiary", "return_5d": 1.0},
            ],
        })
        ev = db.load_recent_events(1)[0]
        for field in (
            "real_yield_context", "policy_constraint", "shock_decomposition",
            "reaction_function_divergence", "surprise_vs_anticipation",
            "terms_of_trade", "reserve_stress",
        ):
            self.assertEqual(ev[field], {})


# ---------------------------------------------------------------------------
# Case 2 — Fresh vs cached /analyze response parity
# ---------------------------------------------------------------------------


class TestAnalyzeFreshCachedParity(unittest.TestCase):
    """Fresh and cached /analyze responses must carry the same key set."""

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""
        for p in _CONTRACT_PATCHES:
            p.start()
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    @classmethod
    def tearDownClass(cls):
        for p in _CONTRACT_PATCHES:
            p.stop()

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_parity_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    _TOP_LEVEL_KEYS = {
        "headline", "stage", "persistence", "analysis", "market",
        "freshness", "is_mock", "event_date",
    }

    _MARKET_FRESHNESS_KEYS = {
        "last_market_check_at", "market_check_staleness", "event_age_days",
    }

    _FRESHNESS_KEYS = {
        "bucket", "natural_bucket", "event_age_days",
        "is_frozen", "force_bypassed",
    }

    def _post_analyze(
        self, headline: str, event_date: str | None = None, force: bool = False,
    ):
        body = {"headline": headline}
        if event_date:
            body["event_date"] = event_date
        if force:
            body["force"] = True
        r = self.client.post("/analyze", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _assert_response_shape(self, body: dict):
        self.assertTrue(
            self._TOP_LEVEL_KEYS.issubset(body.keys()),
            f"missing top-level keys: {self._TOP_LEVEL_KEYS - set(body.keys())}",
        )
        # Market freshness keys
        market = body["market"]
        self.assertTrue(
            self._MARKET_FRESHNESS_KEYS.issubset(market.keys()),
            f"market missing freshness keys: "
            f"{self._MARKET_FRESHNESS_KEYS - set(market.keys())}",
        )
        # Freshness block shape
        freshness = body["freshness"]
        self.assertIsInstance(freshness, dict)
        self.assertTrue(
            self._FRESHNESS_KEYS.issubset(freshness.keys()),
            f"freshness missing keys: "
            f"{self._FRESHNESS_KEYS - set(freshness.keys())}",
        )

    def test_fresh_response_carries_freshness_metadata(self):
        """A brand-new /analyze call returns freshness + market freshness."""
        headline = f"Fresh contract test {uuid.uuid4().hex[:6]}"
        body = self._post_analyze(headline)
        self._assert_response_shape(body)
        # Today's date → hot bucket
        self.assertEqual(body["freshness"]["bucket"], "hot")
        self.assertFalse(body["freshness"]["is_frozen"])
        # Fresh paths mark market_check_staleness == "fresh"
        self.assertEqual(body["market"]["market_check_staleness"], "fresh")
        self.assertIsNotNone(body["market"]["last_market_check_at"])

    def test_fresh_and_cached_top_level_keys_match(self):
        """The two paths must produce the same top-level key set."""
        headline = f"Parity contract test {uuid.uuid4().hex[:6]}"
        fresh = self._post_analyze(headline)        # persists the event
        cached = self._post_analyze(headline)       # cache hit
        self.assertEqual(set(fresh.keys()), set(cached.keys()))
        # Market block must share the freshness-field set
        self.assertEqual(
            set(fresh["market"].keys()) & self._MARKET_FRESHNESS_KEYS,
            self._MARKET_FRESHNESS_KEYS,
        )
        self.assertEqual(
            set(cached["market"].keys()) & self._MARKET_FRESHNESS_KEYS,
            self._MARKET_FRESHNESS_KEYS,
        )
        # Freshness block key set must match
        self.assertEqual(
            set(fresh["freshness"].keys()),
            set(cached["freshness"].keys()),
        )

    def test_fresh_and_cached_analysis_sub_shape_matches(self):
        """The analysis.* overlay set must be identical across paths."""
        headline = f"Analysis parity {uuid.uuid4().hex[:6]}"
        fresh = self._post_analyze(headline)
        cached = self._post_analyze(headline)
        required = {
            "real_yield_context", "policy_constraint",
            "shock_decomposition", "reaction_function_divergence",
            "surprise_vs_anticipation", "terms_of_trade", "reserve_stress",
            "historical_analogs",
        }
        self.assertTrue(required.issubset(set(fresh["analysis"].keys())))
        self.assertTrue(required.issubset(set(cached["analysis"].keys())))

    def _seed_frozen_event(
        self, *, headline: str, frozen_date: str, overlays: dict,
    ) -> None:
        """Seed a frozen event using the same model the /analyze path resolves.

        ``find_cached_analysis`` matches on (headline, event_date, model),
        so the seed MUST use the same model identifier the test client
        will hit.  We resolve it through the api module so any change to
        ``_active_model`` flows through automatically.
        """
        record = {
            "headline": headline,
            "stage": "realized",
            "persistence": "structural",
            "what_changed": "ctx",
            "mechanism_summary": "mech",
            "event_date": frozen_date,
            "model": self.api._active_model(),
            "market_tickers": [
                {"symbol": "AAPL", "role": "beneficiary", "return_5d": 2.1,
                 "direction_tag": "supports \u2191"},
            ],
        }
        record.update(overlays)
        db.save_event(record)

    def test_frozen_cached_event_keeps_persisted_overlays(self):
        """A cached event > 30d old must surface its stored overlays."""
        frozen_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        headline = f"Frozen cached {uuid.uuid4().hex[:6]}"
        self._seed_frozen_event(
            headline=headline,
            frozen_date=frozen_date,
            overlays={
                "policy_constraint": {
                    "available": True, "binding": "inflation",
                    "policy_room": "limited",
                },
                "terms_of_trade": {
                    "available": True, "dominant_channel": "oil_import",
                },
                "reserve_stress": {
                    "available": True, "dominant_channel": "usd_funding_stress",
                    "pressure_score": 55, "pressure_label": "moderate",
                },
            },
        )

        body = self._post_analyze(headline, event_date=frozen_date)
        self.assertEqual(body["freshness"]["natural_bucket"], "frozen")
        self.assertTrue(body["freshness"]["is_frozen"])
        # The persisted overlays should flow through the frozen branch.
        self.assertEqual(
            body["analysis"]["policy_constraint"]["binding"], "inflation",
        )
        self.assertEqual(
            body["analysis"]["terms_of_trade"]["dominant_channel"],
            "oil_import",
        )
        self.assertEqual(
            body["analysis"]["reserve_stress"]["pressure_label"], "moderate",
        )

    def test_force_on_frozen_cached_event_bypasses_freeze(self):
        """force=True on a frozen row flips bucket and force_bypassed."""
        frozen_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        headline = f"Force frozen {uuid.uuid4().hex[:6]}"
        self._seed_frozen_event(
            headline=headline,
            frozen_date=frozen_date,
            overlays={
                "policy_constraint": {
                    "available": True, "binding": "inflation",
                },
            },
        )

        body = self._post_analyze(headline, event_date=frozen_date, force=True)
        fresh = body["freshness"]
        self.assertEqual(fresh["natural_bucket"], "frozen")
        self.assertEqual(fresh["bucket"], "stable")
        self.assertTrue(fresh["force_bypassed"])
        self.assertTrue(fresh["is_frozen"])

    def test_stream_complete_frame_matches_analyze_shape(self):
        """/analyze/stream's complete frame must carry the same shape."""
        headline = f"Stream parity {uuid.uuid4().hex[:6]}"
        with self.client.stream(
            "POST", "/analyze/stream",
            json={"headline": headline},
        ) as r:
            self.assertEqual(r.status_code, 200)
            frames = []
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                frames.append(json.loads(line[6:]))

        complete = [f for f in frames if f.get("_phase") == "complete"]
        self.assertTrue(complete, "no complete SSE frame emitted")
        body = complete[-1]
        self._assert_response_shape(body)


# ---------------------------------------------------------------------------
# Case 3 — is_frozen force semantics
# ---------------------------------------------------------------------------


class TestIsFrozenForceSemantics(unittest.TestCase):
    """Hot-path is_frozen contract: force=True → False."""

    def _event(self, days_old: int) -> dict:
        now = datetime(2026, 4, 8, 12, 0, 0)
        event_date = (now - timedelta(days=days_old)).strftime("%Y-%m-%d")
        return {
            "id": 1,
            "event_date": event_date,
            "timestamp": (now - timedelta(days=days_old)).isoformat(timespec="seconds"),
        }

    def test_frozen_row_no_force_returns_true(self):
        self.assertTrue(
            eap.is_frozen(self._event(45), now=datetime(2026, 4, 8, 12, 0, 0)),
        )

    def test_frozen_row_with_force_returns_false(self):
        """force=True is the caller saying 'I'll refresh regardless'."""
        self.assertFalse(
            eap.is_frozen(
                self._event(45),
                now=datetime(2026, 4, 8, 12, 0, 0),
                force=True,
            ),
        )

    def test_warm_row_no_force_returns_false(self):
        self.assertFalse(
            eap.is_frozen(self._event(3), now=datetime(2026, 4, 8, 12, 0, 0)),
        )

    def test_warm_row_with_force_returns_false(self):
        self.assertFalse(
            eap.is_frozen(
                self._event(3),
                now=datetime(2026, 4, 8, 12, 0, 0),
                force=True,
            ),
        )

    def test_is_naturally_frozen_ignores_force(self):
        """Observability helper always reflects the underlying state."""
        self.assertTrue(
            eap.is_naturally_frozen(
                self._event(45), now=datetime(2026, 4, 8, 12, 0, 0),
            ),
        )
        self.assertFalse(
            eap.is_naturally_frozen(
                self._event(3), now=datetime(2026, 4, 8, 12, 0, 0),
            ),
        )

    def test_classify_event_age_still_records_natural_state(self):
        """The full classification must keep natural_bucket=frozen + force_bypassed."""
        c = eap.classify_event_age(
            self._event(45),
            now=datetime(2026, 4, 8, 12, 0, 0),
            force=True,
        )
        self.assertEqual(c["bucket"], "stable")
        self.assertEqual(c["natural_bucket"], "frozen")
        self.assertTrue(c["force_bypassed"])


# ---------------------------------------------------------------------------
# Case 4 — Frontend typing contract
# ---------------------------------------------------------------------------


class TestFrontendTypingContract(unittest.TestCase):
    """The api.ts file must declare every field the backend returns.

    This is a structural grep test: the audit flagged four contract
    drifts that need to be visible in the TypeScript types.  We check
    the literal strings rather than parsing TS because the repo has no
    ts runtime in the Python test path.
    """

    @classmethod
    def setUpClass(cls):
        api_ts_path = os.path.join(
            os.path.dirname(__file__), "..", "frontend", "src", "lib", "api.ts",
        )
        with open(api_ts_path, "r", encoding="utf-8") as f:
            cls.api_ts = f.read()

    def _assert_has(self, pattern: str, msg: str = "") -> None:
        self.assertTrue(
            re.search(pattern, self.api_ts),
            f"api.ts missing {msg or pattern!r}",
        )

    def test_analyze_request_has_force_field(self):
        """AnalyzeRequest must accept the optional force flag."""
        self._assert_has(
            r"export interface AnalyzeRequest[\s\S]*?force\?:\s*boolean",
            "AnalyzeRequest.force",
        )

    def test_analyze_response_has_freshness_block(self):
        """AnalyzeResponse must declare the freshness block."""
        self._assert_has(
            r"export interface AnalyzeResponse[\s\S]*?freshness\?:",
            "AnalyzeResponse.freshness",
        )
        # And FreshnessBlock itself must carry the required keys.
        for key in (
            "bucket", "natural_bucket", "event_age_days",
            "is_frozen", "force_bypassed",
        ):
            self._assert_has(
                rf"FreshnessBlock[\s\S]*?{key}",
                f"FreshnessBlock.{key}",
            )

    def test_market_result_has_freshness_fields(self):
        """MarketResult must extend or include the freshness fields."""
        for key in (
            "last_market_check_at", "market_check_staleness", "event_age_days",
        ):
            self._assert_has(
                rf"MarketFreshness[\s\S]*?{key}",
                f"MarketFreshness.{key}",
            )
        # MarketResult must extend MarketFreshness
        self._assert_has(
            r"MarketResult\s+extends\s+MarketFreshness",
            "MarketResult extends MarketFreshness",
        )

    def test_backtest_result_has_freshness_fields(self):
        """BacktestResult must carry the staleness + timestamp fields."""
        for key in ("market_check_staleness", "last_market_check_at"):
            self._assert_has(
                rf"BacktestResult[\s\S]*?{key}",
                f"BacktestResult.{key}",
            )

    def test_backtest_api_helpers_accept_force(self):
        """The api.backtest / backtestBatch helpers accept a force flag."""
        self._assert_has(
            r"backtest:\s*\(eventId:\s*number,\s*force\s*=\s*false\)",
            "api.backtest(force)",
        )
        self._assert_has(
            r"backtestBatch:\s*\(eventIds:\s*number\[\],\s*force\s*=\s*false\)",
            "api.backtestBatch(force)",
        )


if __name__ == "__main__":
    unittest.main()
