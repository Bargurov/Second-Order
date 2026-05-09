"""Backend contract tests for ``POST /movers/backfill-recent``.

The route is the explicit safe operation that pulls recent cluster
headlines through the analyze + market_check + persist pipeline so
mover surfaces (Section C) can populate from real saved events
without inventing rows.

The functional happy/degraded paths are exercised in
``tests/test_movers_cache.py``.  This file pins the public response
contract — the stats envelope keys, the empty-cache degraded fallback,
and the ``no fake mover rows`` invariant — so a regression that
strips a stat or starts fabricating rows is caught at the wire shape.

No live network, no LLM, no yfinance.  External seams are stubbed
the same way the rest of the contract suite stubs them.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402


_REQUIRED_DIAG_KEYS: tuple[str, ...] = (
    "headlines_scanned",
    "analyzed",
    "market_checked",
    "persisted",
    "with_tickers",
    "with_returns",
    "skipped",
    "failures",
    "llm_available",
    "market_data_status",
)


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    def setUp(self):
        self._orig_db = db.DB_FILE
        self._tmp_db = os.path.join(
            tempfile.gettempdir(),
            f"test_movers_populate_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp_db
        db.init_db()
        self.api._TODAYS_MOVERS_CACHE["data"] = None
        self.api._TODAYS_MOVERS_CACHE["ts"] = 0.0
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0
        self._orig_backfill_provider = os.environ.get("BACKFILL_PROVIDER")
        self._orig_backfill_dry_run = os.environ.get("BACKFILL_DRY_RUN_DEFAULT")
        self._orig_backfill_budget = os.environ.get("MAX_BACKFILL_LLM_CALLS")
        self._orig_enable_paid = os.environ.get("ENABLE_PAID_ANALYSIS")
        # Most tests exercise the active populate pipeline through stubs.
        # Keep those tests explicit while separate cases below pin the safe
        # production defaults.
        os.environ["BACKFILL_PROVIDER"] = "anthropic"
        os.environ["BACKFILL_DRY_RUN_DEFAULT"] = "false"
        os.environ["MAX_BACKFILL_LLM_CALLS"] = "20"
        # Kill-switch: paid populate path is gated by ENABLE_PAID_ANALYSIS
        # at routes/movers.py:1426.  These tests exercise diagnostics shape
        # and pipeline reuse, not the kill-switch itself (covered by
        # tests/test_backfill_paid_guard.py), so authorise the paid path
        # to mirror the same setUp pattern used by the registry and paid-
        # guard contract suites.
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"

    def tearDown(self):
        if self._orig_backfill_provider is None:
            os.environ.pop("BACKFILL_PROVIDER", None)
        else:
            os.environ["BACKFILL_PROVIDER"] = self._orig_backfill_provider
        if self._orig_backfill_dry_run is None:
            os.environ.pop("BACKFILL_DRY_RUN_DEFAULT", None)
        else:
            os.environ["BACKFILL_DRY_RUN_DEFAULT"] = self._orig_backfill_dry_run
        if self._orig_backfill_budget is None:
            os.environ.pop("MAX_BACKFILL_LLM_CALLS", None)
        else:
            os.environ["MAX_BACKFILL_LLM_CALLS"] = self._orig_backfill_budget
        if self._orig_enable_paid is None:
            os.environ.pop("ENABLE_PAID_ANALYSIS", None)
        else:
            os.environ["ENABLE_PAID_ANALYSIS"] = self._orig_enable_paid
        db.DB_FILE = self._orig_db
        try:
            os.remove(self._tmp_db)
        except (OSError, PermissionError):
            pass

    def _seed_news(self, headlines: list[str]):
        """Prime the in-memory news cache with the listed headlines."""
        self.api._news_cache["data"] = {
            "clusters": [
                {
                    "id": i + 1,
                    "headline": headlines[i],
                    "source_count": 2,
                    "published_at": datetime.now().isoformat(timespec="seconds"),
                }
                for i in range(len(headlines))
            ],
            "total_headlines": len(headlines),
            "feed_status": [{"name": "test", "ok": True}],
            "refresh_meta": {
                "status": "ok", "freshness": "fresh",
                "last_successful_refresh": datetime.now().isoformat(timespec="seconds"),
            },
            "_schema_version": self.api._NEWS_CACHE_VERSION,
        }
        self.api._news_cache["ts"] = 999_999_999.0


# ---------------------------------------------------------------------------
# Stats envelope shape — the keys the diagnostic surface depends on.
# ---------------------------------------------------------------------------

class TestStatsEnvelope(_Base):
    def test_response_carries_required_top_level_keys(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            r = self.client.post("/movers/backfill-recent?max_llm_calls=1")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        for key in ("status", "diagnostics", "items", "dry_run", "limit", "scan_limit"):
            self.assertIn(key, body, f"missing top-level key: {key}")
        self.assertIn(body["status"], ("ok", "degraded"))
        self.assertIsInstance(body["items"], list)

    def test_diagnostics_carries_full_stats(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            r = self.client.post("/movers/backfill-recent?max_llm_calls=1")
        body = r.json()
        diag = body["diagnostics"]
        for key in _REQUIRED_DIAG_KEYS:
            self.assertIn(key, diag, f"missing diagnostic key: {key}")
        self.assertIsInstance(diag["skipped"], dict)
        self.assertIsInstance(diag["failures"], list)
        self.assertIsInstance(diag["llm_available"], bool)
        self.assertIn(diag["market_data_status"], ("ok", "degraded", "unknown"))


# ---------------------------------------------------------------------------
# Cost guards - default dry-run + low env-backed LLM budget.
# ---------------------------------------------------------------------------

class TestCostGuards(_Base):
    def test_missing_max_llm_calls_is_rejected(self):
        self._seed_news(["OPEC cuts output by 500k bpd"])
        r = self.client.post("/movers/backfill-recent?limit=1&scan_limit=1")
        self.assertEqual(r.status_code, 400)
        self.assertIn("max_llm_calls", r.json().get("detail", ""))

    def test_backfill_defaults_to_dry_run_when_env_unset(self):
        self._seed_news(["OPEC cuts output by 500k bpd"])
        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "test-key",
                "BACKFILL_DRY_RUN_DEFAULT": "",
                "MAX_BACKFILL_LLM_CALLS": "1",
            },
        ), patch("api.analyze_event") as analyze_mock:
            r = self.client.post(
                "/movers/backfill-recent?limit=1&scan_limit=1&max_llm_calls=1",
            )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        diag = body["diagnostics"]
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["max_llm_calls"], 1)
        self.assertEqual(diag["llm_calls"], 0)
        self.assertGreaterEqual(diag["skipped"].get("dry_run", 0), 1)
        analyze_mock.assert_not_called()

    def test_backfill_provider_and_model_are_configurable(self):
        self._seed_news(["OPEC cuts output by 500k bpd"])
        with patch.dict(
            os.environ,
            {
                "BACKFILL_PROVIDER": "openai",
                "BACKFILL_MODEL": "gpt-4o-mini",
                "MAX_BACKFILL_LLM_CALLS": "1",
                "BACKFILL_DRY_RUN_DEFAULT": "true",
            },
        ):
            r = self.client.post(
                "/movers/backfill-recent?limit=1&scan_limit=1&max_llm_calls=1",
            )
        self.assertEqual(r.status_code, 200, r.text)
        diag = r.json()["diagnostics"]
        self.assertEqual(diag["llm_provider"], "openai")
        self.assertEqual(diag["analysis_model"], "gpt-4o-mini")
        self.assertEqual(diag["analysis_model_key"], "openai:gpt-4o-mini")

    def test_explicit_dry_run_false_overrides_safe_default(self):
        self._seed_news(["OPEC cuts output by 500k bpd"])
        analysis = {
            "what_changed": "stub", "mechanism_summary": "stub",
            "beneficiaries": [], "losers": [],
            "beneficiary_tickers": ["XOM"], "loser_tickers": [],
            "assets_to_watch": ["XOM"], "confidence": "high",
            "transmission_chain": ["a", "b"], "if_persists": {},
            "currency_channel": {},
        }
        market_payload = {"note": "stub", "tickers": [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": 1.5, "direction_tag": "supports ↑"},
        ]}
        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "test-key",
                "BACKFILL_DRY_RUN_DEFAULT": "true",
                "MAX_BACKFILL_LLM_CALLS": "1",
            },
        ), patch("api.analyze_event", return_value=analysis) as analyze_mock, \
             patch("api.market_check", return_value=market_payload), \
             patch("routes.analyze._run_pre_market_overlays",
                   return_value=(None, None)), \
             patch("routes.analyze._run_post_market_overlays"), \
             patch("routes.analyze._enrich_macro_context_with_country",
                   side_effect=lambda ctx, _h: ctx):
            r = self.client.post(
                "/movers/backfill-recent?dry_run=false&limit=1&scan_limit=1&max_llm_calls=1",
            )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertFalse(body["dry_run"])
        self.assertEqual(body["diagnostics"]["llm_calls"], 1)
        analyze_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Empty / cold cache - degraded with a reason, no fake rows.
# ---------------------------------------------------------------------------

class TestEmptyCacheDegrades(_Base):
    def test_no_headlines_returns_degraded_status(self):
        """No primed news + cold DB → status='degraded' with a clearly
        empty diagnostics block.  Must not raise."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.post("/movers/backfill-recent?max_llm_calls=1")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["status"], "degraded")
        diag = body["diagnostics"]
        self.assertEqual(diag["headlines_scanned"], 0)
        self.assertEqual(diag["analyzed"], 0)
        self.assertEqual(diag["persisted"], 0)
        self.assertEqual(diag["with_tickers"], 0)
        self.assertEqual(diag["with_returns"], 0)
        self.assertEqual(diag["failures"], [])
        self.assertEqual(body["items"], [])

    def test_no_headlines_does_not_persist_rows(self):
        """Section C invariant: the populate operation must not invent
        events.  After a cold-cache run, the events table stays empty."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            self.client.post("/movers/backfill-recent?max_llm_calls=1")
        self.assertEqual(db.load_recent_events(50), [])


# ---------------------------------------------------------------------------
# Missing API key — degraded with llm_unavailable, no LLM call attempted.
# ---------------------------------------------------------------------------

class TestApiKeyPreflight(_Base):
    def setUp(self):
        super().setUp()
        # Common fixture: one primed headline so the route enters the loop.
        self._seed_news(["OPEC cuts output by 500k bpd"])

    def test_missing_key_skips_with_llm_unavailable(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}), \
             patch("api.analyze_event") as analyze_mock:
            r = self.client.post(
                "/movers/backfill-recent?limit=1&scan_limit=1&max_llm_calls=1",
            )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["status"], "degraded")
        diag = body["diagnostics"]
        self.assertFalse(diag["llm_available"])
        self.assertEqual(diag["analyzed"], 0)
        self.assertEqual(diag["persisted"], 0)
        self.assertGreaterEqual(diag["skipped"].get("llm_unavailable", 0), 1)
        analyze_mock.assert_not_called()
        # Items list still emitted, marked degraded so the caller can
        # distinguish "ran but couldn't proceed" from "didn't even try".
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["status"], "degraded")
        self.assertEqual(body["items"][0]["reason"], "llm_unavailable")


# ---------------------------------------------------------------------------
# Failure tracking — analyze_event raising must not crash the run.
# ---------------------------------------------------------------------------

class TestFailureTracking(_Base):
    def setUp(self):
        super().setUp()
        self._seed_news(["OPEC cuts output by 500k bpd"])

    def test_analyze_failure_logged_in_failures_list(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("api.analyze_event", side_effect=RuntimeError("boom")), \
             patch("api.market_check") as market_mock:
            r = self.client.post(
                "/movers/backfill-recent?limit=1&scan_limit=1&max_llm_calls=1",
            )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["status"], "degraded")
        diag = body["diagnostics"]
        self.assertEqual(diag["analyzed"], 0)
        self.assertEqual(diag["persisted"], 0)
        self.assertEqual(len(diag["failures"]), 1)
        self.assertIn("boom", diag["failures"][0]["reason"])
        # market_check must not have been called: analyze raised before
        # we reached the market step.
        market_mock.assert_not_called()


# ---------------------------------------------------------------------------
# High-impact-only persistent rule must NOT be loosened by a backfill.
#
# A backfill that successfully persists a generic event must not cause
# /movers/persistent to surface a card that fails the high-conviction
# gate.  The persistent surface is filter-only: anything that doesn't
# meet the rule is dropped, never demoted.
# ---------------------------------------------------------------------------

class TestPersistentRuleUnchanged(_Base):
    def test_backfilled_generic_event_does_not_leak_to_persistent(self):
        """Even when the backfill persists an event with market_tickers,
        /movers/persistent must stay empty unless the event also clears
        the high-impact + conviction gate.  This locks the
        high-impact-only rule against an accidental loosening from the
        populate path."""
        self._seed_news(["OPEC cuts output by 500k bpd"])

        analysis = {
            "what_changed": "OPEC cut output.",
            "mechanism_summary": "Lower supply supports oil-linked assets.",
            "beneficiaries": ["Energy producers"],
            "losers": ["Oil consumers"],
            "beneficiary_tickers": ["GLD"],
            "loser_tickers": ["USO"],
            "assets_to_watch": ["GLD", "USO"],
            "confidence": "high",
            "transmission_chain": ["Supply falls", "prices rise"],
            "if_persists": {},
            "currency_channel": {},
        }
        market_payload = {
            "note": "stub market check",
            "tickers": [
                {"symbol": "GLD", "role": "beneficiary",
                 "return_5d": 2.2, "return_20d": 2.6,
                 "direction_tag": "supports ↑"},
            ],
        }

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("api.analyze_event", return_value=analysis), \
             patch("api.market_check", return_value=market_payload), \
             patch("routes.analyze._run_pre_market_overlays",
                   return_value=(None, None)), \
             patch("routes.analyze._run_post_market_overlays"), \
             patch("routes.analyze._enrich_macro_context_with_country",
                   side_effect=lambda ctx, _h: ctx):
            backfill = self.client.post(
                "/movers/backfill-recent?limit=1&scan_limit=1&max_llm_calls=1",
            )
        self.assertEqual(backfill.status_code, 200, backfill.text)
        # Independently of whether the backfill succeeded, the persistent
        # surface must NOT surface a generic event that lacks
        # ``conviction.impact_level == "high"`` + supportive evidence.
        r = self.client.get("/movers/persistent")
        self.assertEqual(r.status_code, 200, r.text)
        # Bare-list contract is the default; any envelope unwraps to the
        # ``items`` field for forward-compatibility.
        body = r.json()
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        self.assertEqual(items, [])


# ---------------------------------------------------------------------------
# Reuse of existing pipeline pieces — analyze + market_check + persist.
# ---------------------------------------------------------------------------

class TestPipelineReuse(_Base):
    def setUp(self):
        super().setUp()
        self._seed_news(["OPEC cuts output by 500k bpd"])

    def test_uses_api_analyze_event_and_market_check(self):
        """The route must call into ``api.analyze_event`` and
        ``api.market_check`` (the same seams the /analyze pipeline uses)
        so a stub on one composes correctly with the rest of the run."""
        analysis = {
            "what_changed": "OPEC cut output.",
            "mechanism_summary": "Lower supply supports oil-linked assets.",
            "beneficiaries": ["Energy producers"],
            "losers": ["Oil consumers"],
            "beneficiary_tickers": ["GLD"],
            "loser_tickers": ["USO"],
            "assets_to_watch": ["GLD", "USO"],
            "confidence": "high",
            "transmission_chain": ["Supply falls", "prices rise"],
            "if_persists": {},
            "currency_channel": {},
        }
        market_payload = {
            "note": "stub market check",
            "tickers": [
                {"symbol": "GLD", "role": "beneficiary",
                 "return_5d": 2.2, "return_20d": 2.6,
                 "direction_tag": "supports ↑"},
            ],
        }
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("api.analyze_event", return_value=analysis) as analyze_mock, \
             patch("api.market_check", return_value=market_payload) as market_mock, \
             patch("routes.analyze._run_pre_market_overlays",
                   return_value=(None, None)), \
             patch("routes.analyze._run_post_market_overlays"), \
             patch("routes.analyze._enrich_macro_context_with_country",
                   side_effect=lambda ctx, _h: ctx):
            r = self.client.post(
                "/movers/backfill-recent?limit=1&scan_limit=1&max_llm_calls=1",
            )
        self.assertEqual(r.status_code, 200, r.text)
        analyze_mock.assert_called_once()
        market_mock.assert_called_once()
        body = r.json()
        diag = body["diagnostics"]
        self.assertEqual(diag["analyzed"], 1)
        self.assertEqual(diag["with_tickers"], 1)
        self.assertEqual(diag["with_returns"], 1)


# ---------------------------------------------------------------------------
# Recency filter — old clusters dropped before the LLM is consulted.
# ---------------------------------------------------------------------------

class TestRecencyFilter(_Base):
    def _seed_with_age(self, headlines: list[tuple[str, datetime]]):
        """Prime the news cache with explicit per-cluster timestamps."""
        self.api._news_cache["data"] = {
            "clusters": [
                {
                    "id": i + 1,
                    "headline": hl,
                    "source_count": 2,
                    "published_at": when.isoformat(timespec="seconds"),
                }
                for i, (hl, when) in enumerate(headlines)
            ],
            "total_headlines": len(headlines),
            "feed_status": [{"name": "test", "ok": True}],
            "refresh_meta": {
                "status": "ok", "freshness": "fresh",
                "last_successful_refresh": datetime.now().isoformat(timespec="seconds"),
            },
            "_schema_version": self.api._NEWS_CACHE_VERSION,
        }
        self.api._news_cache["ts"] = 999_999_999.0

    def test_clusters_outside_recency_window_skipped(self):
        from datetime import timedelta
        old = datetime.now() - timedelta(hours=200)
        recent = datetime.now() - timedelta(hours=2)
        self._seed_with_age([
            ("OPEC slashes output by 500k bpd", old),
            ("Federal Reserve hikes rates 25bp", recent),
        ])
        analysis = {
            "what_changed": "stub", "mechanism_summary": "stub",
            "beneficiaries": [], "losers": [],
            "beneficiary_tickers": ["XOM"], "loser_tickers": [],
            "assets_to_watch": ["XOM"], "confidence": "high",
            "transmission_chain": ["a", "b"], "if_persists": {},
            "currency_channel": {},
        }
        market_payload = {"note": "stub", "tickers": [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": 1.5, "direction_tag": "supports ↑"},
        ]}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("api.analyze_event", return_value=analysis), \
             patch("api.market_check", return_value=market_payload), \
             patch("routes.analyze._run_pre_market_overlays",
                   return_value=(None, None)), \
             patch("routes.analyze._run_post_market_overlays"), \
             patch("routes.analyze._enrich_macro_context_with_country",
                   side_effect=lambda ctx, _h: ctx):
            r = self.client.post(
                "/movers/backfill-recent?since_hours=24&limit=5&scan_limit=5&max_llm_calls=5&confirm_paid=true",
            )
        body = r.json()
        diag = body["diagnostics"]
        # Only the recent cluster makes it past the recency gate.
        self.assertEqual(diag["candidates_considered"], 1)
        self.assertGreaterEqual(diag["skipped"].get("outside_recency_window", 0), 1)
        # The recent one was actually analyzed.
        self.assertEqual(diag["analyzed"], 1)


# ---------------------------------------------------------------------------
# Relevance filter — non-market headlines skipped before LLM call.
# ---------------------------------------------------------------------------

class TestRelevanceFilter(_Base):
    def test_irrelevant_headline_skipped(self):
        # Two clusters: one clearly market-relevant, one a non-market
        # human-interest headline.  Default ``include_low_signal=False``
        # means the irrelevant one is pre-filtered.
        self._seed_news([
            "OPEC slashes oil output by 500k bpd",
            "Local cat rescued from tree after three-day standoff",
        ])
        analysis = {
            "what_changed": "stub", "mechanism_summary": "stub",
            "beneficiaries": [], "losers": [],
            "beneficiary_tickers": ["XOM"], "loser_tickers": [],
            "assets_to_watch": ["XOM"], "confidence": "high",
            "transmission_chain": ["a", "b"], "if_persists": {},
            "currency_channel": {},
        }
        market_payload = {"note": "stub", "tickers": [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": 1.5, "direction_tag": "supports ↑"},
        ]}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("api.analyze_event", return_value=analysis) as analyze_mock, \
             patch("api.market_check", return_value=market_payload), \
             patch("routes.analyze._run_pre_market_overlays",
                   return_value=(None, None)), \
             patch("routes.analyze._run_post_market_overlays"), \
             patch("routes.analyze._enrich_macro_context_with_country",
                   side_effect=lambda ctx, _h: ctx):
            r = self.client.post(
                "/movers/backfill-recent?limit=5&scan_limit=5&max_llm_calls=5&confirm_paid=true",
            )
        body = r.json()
        diag = body["diagnostics"]
        # Cat headline pre-filtered as irrelevant; OPEC kept.
        self.assertGreaterEqual(diag["skipped"].get("irrelevant_headline", 0), 1)
        self.assertEqual(diag["candidates_considered"], 1)
        # Only one LLM call (the relevant cluster).
        self.assertEqual(analyze_mock.call_count, 1)


# ---------------------------------------------------------------------------
# max_llm_calls budget — caps actual LLM invocations.
# ---------------------------------------------------------------------------

class TestMaxLlmCallsBudget(_Base):
    def test_max_llm_calls_caps_actual_invocations(self):
        # Three relevant headlines, but ``max_llm_calls=1`` — only one
        # of them should reach the LLM.
        self._seed_news([
            "OPEC cuts output by 500k bpd",
            "Federal Reserve hikes rates 25bp",
            "Chinese exporters hit by new tariff package",
        ])
        analysis = {
            "what_changed": "stub", "mechanism_summary": "stub",
            "beneficiaries": [], "losers": [],
            "beneficiary_tickers": ["XOM"], "loser_tickers": [],
            "assets_to_watch": ["XOM"], "confidence": "high",
            "transmission_chain": ["a", "b"], "if_persists": {},
            "currency_channel": {},
        }
        market_payload = {"note": "stub", "tickers": [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": 1.5, "direction_tag": "supports ↑"},
        ]}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("api.analyze_event", return_value=analysis) as analyze_mock, \
             patch("api.market_check", return_value=market_payload), \
             patch("routes.analyze._run_pre_market_overlays",
                   return_value=(None, None)), \
             patch("routes.analyze._run_post_market_overlays"), \
             patch("routes.analyze._enrich_macro_context_with_country",
                   side_effect=lambda ctx, _h: ctx):
            r = self.client.post(
                "/movers/backfill-recent?max_llm_calls=1&limit=5&scan_limit=5",
            )
        body = r.json()
        diag = body["diagnostics"]
        self.assertEqual(diag["llm_calls"], 1)
        self.assertEqual(diag["llm_calls_budget"], 1)
        self.assertEqual(analyze_mock.call_count, 1)
        self.assertGreaterEqual(diag["skipped"].get("llm_budget_exhausted", 0), 1)

    def test_max_llm_calls_zero_blocks_all_fresh_analyses(self):
        # ``max_llm_calls=0`` is the "refresh-only" mode — no fresh
        # analyses, no LLM invocations.
        self._seed_news(["OPEC cuts output by 500k bpd"])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("api.analyze_event") as analyze_mock:
            r = self.client.post(
                "/movers/backfill-recent?max_llm_calls=0&limit=5&scan_limit=5",
            )
        body = r.json()
        diag = body["diagnostics"]
        self.assertEqual(diag["llm_calls"], 0)
        analyze_mock.assert_not_called()
        # The cluster should be marked as budget-exhausted, not as a
        # successful analysis.
        self.assertGreaterEqual(diag["skipped"].get("llm_budget_exhausted", 0), 1)

    def test_explicit_max_llm_calls_sets_budget(self):
        # The caller must state the budget; the route echoes that cap into
        # diagnostics so operators can confirm the intended spend.
        self._seed_news(["OPEC cuts output by 500k bpd"])
        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "",
                "MAX_BACKFILL_LLM_CALLS": "1",
                "BACKFILL_DRY_RUN_DEFAULT": "",
            },
        ):
            r = self.client.post("/movers/backfill-recent?limit=4&max_llm_calls=1")
        body = r.json()
        self.assertEqual(body["max_llm_calls"], 1)
        self.assertEqual(body["diagnostics"]["llm_calls_budget"], 1)

    def test_max_llm_calls_rejects_values_above_env_cap(self):
        self._seed_news(["OPEC cuts output by 500k bpd"])
        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "",
                "MAX_BACKFILL_LLM_CALLS": "2",
                "BACKFILL_DRY_RUN_DEFAULT": "",
            },
        ):
            r = self.client.post("/movers/backfill-recent?limit=4&max_llm_calls=3")
        self.assertEqual(r.status_code, 400)
        self.assertIn("MAX_BACKFILL_LLM_CALLS", r.json().get("detail", ""))


# ---------------------------------------------------------------------------
# Degraded-reasons surface — explicit machine-readable causes.
# ---------------------------------------------------------------------------

class TestDegradedReasons(_Base):
    def test_no_api_key_surfaces_llm_unavailable_reason(self):
        self._seed_news(["OPEC cuts output by 500k bpd"])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            r = self.client.post("/movers/backfill-recent?max_llm_calls=1")
        body = r.json()
        self.assertEqual(body["status"], "degraded")
        self.assertIn(
            "llm_unavailable", body["diagnostics"]["degraded_reasons"],
        )

    def test_empty_news_cache_surfaces_news_cache_empty(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.post("/movers/backfill-recent?max_llm_calls=1")
        body = r.json()
        self.assertEqual(body["status"], "degraded")
        self.assertIn(
            "news_cache_empty", body["diagnostics"]["degraded_reasons"],
        )

    def test_all_clusters_filtered_surfaces_no_eligible(self):
        # Stock the cache with only irrelevant headlines so the recency
        # filter passes but the relevance filter strips everything.
        self._seed_news([
            "Beach concert announces summer lineup",
            "Local bakery wins regional sourdough title",
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.post("/movers/backfill-recent?max_llm_calls=1")
        body = r.json()
        diag = body["diagnostics"]
        self.assertEqual(body["status"], "degraded")
        self.assertIn("no_eligible_clusters", diag["degraded_reasons"])
        self.assertGreaterEqual(diag["skipped"].get("irrelevant_headline", 0), 1)


# ---------------------------------------------------------------------------
# return_1d counts as ``with_returns`` — the today-window contract.
# ---------------------------------------------------------------------------

class TestReturn1dCountsAsUsable(_Base):
    """A backfilled event whose tickers have ``return_1d`` but not
    ``return_5d`` (the natural state for events younger than 5
    trading days) must be counted as ``with_returns`` and must NOT
    push the response into ``market_data_unavailable``.
    """

    def test_return_1d_only_counts_with_returns_and_not_degraded(self):
        self._seed_news(["OPEC cuts oil output by 500k bpd"])
        analysis = {
            "what_changed": "stub", "mechanism_summary": "stub",
            "beneficiaries": [], "losers": [],
            "beneficiary_tickers": ["XOM"], "loser_tickers": [],
            "assets_to_watch": ["XOM"], "confidence": "high",
            "transmission_chain": ["a", "b"], "if_persists": {},
            "currency_channel": {},
        }
        # Tickers with return_1d populated but return_5d=None — the
        # exact shape produced for events 1-4 trading days post-event.
        market_payload = {"note": "stub", "tickers": [
            {"symbol": "XOM", "role": "beneficiary",
             "return_1d": 2.7, "return_5d": None,
             "direction_tag": "supports ↑"},
            {"symbol": "CVX", "role": "beneficiary",
             "return_1d": 2.0, "return_5d": None,
             "direction_tag": "supports ↑"},
        ]}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("api.analyze_event", return_value=analysis), \
             patch("api.market_check", return_value=market_payload), \
             patch("routes.analyze._run_pre_market_overlays",
                   return_value=(None, None)), \
             patch("routes.analyze._run_post_market_overlays"), \
             patch("routes.analyze._enrich_macro_context_with_country",
                   side_effect=lambda ctx, _h: ctx):
            r = self.client.post(
                "/movers/backfill-recent?limit=1&scan_limit=1&max_llm_calls=1",
            )
        body = r.json()
        diag = body["diagnostics"]
        self.assertEqual(diag["with_tickers"], 1)
        # The whole point of the fix: return_1d alone counts.
        self.assertEqual(diag["with_returns"], 1)
        # And the response is NOT degraded for market-data reasons.
        self.assertNotIn(
            "market_data_unavailable", diag["degraded_reasons"],
            f"degraded_reasons={diag['degraded_reasons']!r} should "
            f"not include 'market_data_unavailable' when return_1d is "
            f"populated",
        )

    def test_return_1d_event_skipped_as_already_market_checked(self):
        """A SAVED event that already carries ``return_1d`` must be
        treated as already market-checked — backfill must not waste an
        LLM budget slot on re-running it."""
        headline = "OPEC cuts oil output by 500k bpd"
        event_date = datetime.now().strftime("%Y-%m-%d")
        self._seed_news([headline])
        # Pre-seed a saved event with return_1d but no return_5d.
        db.save_event({
            "headline": headline,
            "stage": "realized", "persistence": "medium",
            "event_date": event_date,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "beneficiaries": ["XOM"], "losers": [],
            "assets_to_watch": ["XOM"],
            "market_tickers": [
                {"symbol": "XOM", "role": "beneficiary",
                 "return_1d": 2.7, "return_5d": None,
                 "direction_tag": "supports ↑"},
            ],
            "mechanism_summary": "Oil supply channel.",
            "confidence": "high",
        })
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("api.analyze_event") as analyze_mock, \
             patch("api.market_check") as market_mock:
            r = self.client.post(
                "/movers/backfill-recent?limit=2&scan_limit=2&max_llm_calls=2&confirm_paid=true",
            )
        body = r.json()
        diag = body["diagnostics"]
        self.assertGreaterEqual(
            diag["skipped"].get("already_market_checked", 0), 1,
        )
        analyze_mock.assert_not_called()
        market_mock.assert_not_called()

    def test_already_checked_cached_events_count_toward_with_returns(self):
        """A subsequent backfill over clusters that all match cached events
        carrying ``return_1d`` must report ``with_returns > 0`` and must
        NOT flag ``market_data_unavailable``.

        The bug it pins: the prior implementation only counted return-bearing
        events when this run's market_check produced them.  Cached skips
        were invisible to the success metrics, so a backfill that found
        all clusters already done would report ``with_returns=0`` even
        though /movers/today surfaced rows from the same DB."""
        h1, h2 = "OPEC cuts oil output by 500k bpd", "Federal Reserve hikes 25bp"
        event_date = datetime.now().strftime("%Y-%m-%d")
        self._seed_news([h1, h2])
        for hl, sym in ((h1, "XOM"), (h2, "TLT")):
            db.save_event({
                "headline": hl,
                "stage": "realized", "persistence": "medium",
                "event_date": event_date,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "beneficiaries": [sym], "losers": [],
                "assets_to_watch": [sym],
                "market_tickers": [
                    {"symbol": sym, "role": "beneficiary",
                     "return_1d": 1.8, "return_5d": None,
                     "direction_tag": "supports ↑"},
                ],
                "mechanism_summary": "Channel stub.",
                "confidence": "high",
            })
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("api.analyze_event") as analyze_mock, \
             patch("api.market_check") as market_mock:
            r = self.client.post(
                "/movers/backfill-recent?limit=5&scan_limit=5&max_llm_calls=5&confirm_paid=true",
            )
        body = r.json()
        diag = body["diagnostics"]
        analyze_mock.assert_not_called()
        market_mock.assert_not_called()
        self.assertGreaterEqual(diag["skipped"].get("already_market_checked", 0), 2)
        # Cached return_1d events count as success — diagnostics must
        # reflect the cache state, not just provider calls this run made.
        self.assertGreaterEqual(diag["with_returns"], 2)
        self.assertGreaterEqual(diag["with_tickers"], 2)
        # And no false market_data_unavailable flag when the cache is healthy.
        self.assertNotIn(
            "market_data_unavailable", diag["degraded_reasons"],
            f"degraded_reasons={diag['degraded_reasons']!r} should not "
            f"include 'market_data_unavailable' when cached events "
            f"already carry return_1d",
        )


# ---------------------------------------------------------------------------
# partial_market_data vs full market_data_unavailable, plus item-row outcome.
#
# When SOME ticker-bearing events get usable returns but others don't, the
# run is "partial" — degraded but not the full provider failure that
# ``market_data_unavailable`` reserves.  Item rows must independently
# carry an ``outcome`` field that distinguishes ``persisted_with_returns``
# from ``persisted_without_returns`` so consumers don't have to reverse-
# engineer the state from ``status`` + ``persisted`` + ``with_returns``.
# ---------------------------------------------------------------------------

class TestMarketDataPartialVsFull(_Base):

    _ANALYSIS = {
        "what_changed": "stub", "mechanism_summary": "stub",
        "beneficiaries": [], "losers": [],
        "beneficiary_tickers": ["XOM"], "loser_tickers": [],
        "assets_to_watch": ["XOM"], "confidence": "high",
        "transmission_chain": ["a", "b"], "if_persists": {},
        "currency_channel": {},
    }

    _STUB_PATCHES = (
        ("routes.analyze._run_pre_market_overlays", {"return_value": (None, None)}),
        ("routes.analyze._run_post_market_overlays", {}),
        ("routes.analyze._enrich_macro_context_with_country",
         {"side_effect": lambda ctx, _h: ctx}),
    )

    def _patches(self, market_check_kw):
        # Build the same patch stack the existing tests use, plus a
        # configurable market_check seam.
        from contextlib import ExitStack
        from unittest.mock import patch as _patch
        stack = ExitStack()
        stack.enter_context(patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}))
        stack.enter_context(_patch("api.analyze_event", return_value=self._ANALYSIS))
        stack.enter_context(_patch("api.market_check", **market_check_kw))
        for target, kw in self._STUB_PATCHES:
            stack.enter_context(_patch(target, **kw))
        return stack

    def test_partial_when_some_events_get_returns_others_dont(self):
        """Mixed run: cluster A's market_check returns return_5d, cluster B
        gets tickers but null returns.  Expected:
          * diagnostics.market_data_status == 'partial'
          * degraded_reasons contains 'partial_market_data', NOT 'market_data_unavailable'
          * top-level status == 'degraded' (any degraded_reasons triggers it)
          * item rows carry distinguishing outcome labels
        """
        self._seed_news([
            "OPEC slashes oil output by 500k bpd",
            "Federal Reserve hikes rates 25bp",
        ])
        market_payloads = [
            {"note": "stub", "tickers": [
                {"symbol": "XOM", "role": "beneficiary",
                 "return_5d": 1.5, "direction_tag": "supports ↑"},
            ]},
            {"note": "stub", "tickers": [
                {"symbol": "TLT", "role": "beneficiary",
                 "return_5d": None, "return_1d": None,
                 "direction_tag": "supports ↑"},
            ]},
        ]
        with self._patches({"side_effect": market_payloads}):
            r = self.client.post(
                "/movers/backfill-recent?limit=5&scan_limit=5&max_llm_calls=5&confirm_paid=true",
            )
        body = r.json()
        diag = body["diagnostics"]

        self.assertEqual(diag["with_tickers"], 2)
        self.assertEqual(diag["with_returns"], 1)
        self.assertEqual(diag["market_data_status"], "partial")
        self.assertIn("partial_market_data", diag["degraded_reasons"])
        self.assertNotIn(
            "market_data_unavailable", diag["degraded_reasons"],
            "partial runs must not also raise the full-failure reason",
        )
        self.assertEqual(body["status"], "degraded")

        outcomes = [it.get("outcome") for it in body["items"]]
        self.assertIn("persisted_with_returns", outcomes)
        self.assertIn("persisted_without_returns", outcomes)

    def test_full_market_data_unavailable_when_no_returns_anywhere(self):
        """Full provider failure: every ticker-bearing event came back
        without returns.  Expected:
          * diagnostics.market_data_status == 'degraded'
          * degraded_reasons contains 'market_data_unavailable', NOT 'partial_market_data'
          * item rows show outcome 'persisted_without_returns'
          * item-row reason is 'persisted_without_returns' (not the
            misleading 'market_data_unavailable' for rows that DID save)
        """
        self._seed_news([
            "OPEC slashes oil output by 500k bpd",
            "Federal Reserve hikes rates 25bp",
        ])
        market_payload = {"note": "stub", "tickers": [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": None, "return_1d": None,
             "direction_tag": "supports ↑"},
        ]}
        with self._patches({"return_value": market_payload}):
            r = self.client.post(
                "/movers/backfill-recent?limit=5&scan_limit=5&max_llm_calls=5&confirm_paid=true",
            )
        body = r.json()
        diag = body["diagnostics"]

        self.assertEqual(diag["with_returns"], 0)
        self.assertGreater(diag["with_tickers"], 0)
        self.assertEqual(diag["market_data_status"], "degraded")
        self.assertIn("market_data_unavailable", diag["degraded_reasons"])
        self.assertNotIn(
            "partial_market_data", diag["degraded_reasons"],
            "full-failure runs must not also raise the partial reason",
        )

        for it in body["items"]:
            if it.get("persisted"):
                self.assertEqual(
                    it.get("outcome"), "persisted_without_returns",
                    f"persisted item should be tagged "
                    f"persisted_without_returns: {it!r}",
                )
                self.assertEqual(
                    it.get("reason"), "persisted_without_returns",
                    "item-row reason should reflect the persisted state, "
                    "not the misleading run-level full-failure label",
                )

    def test_persisted_with_returns_outcome_on_success(self):
        """Single-cluster healthy run.  Item row carries
        ``outcome='persisted_with_returns'`` and reason=None."""
        self._seed_news(["OPEC slashes oil output by 500k bpd"])
        market_payload = {"note": "stub", "tickers": [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": 1.5, "direction_tag": "supports ↑"},
        ]}
        with self._patches({"return_value": market_payload}):
            r = self.client.post(
                "/movers/backfill-recent?limit=1&scan_limit=1&max_llm_calls=1",
            )
        body = r.json()
        diag = body["diagnostics"]
        self.assertEqual(diag["with_returns"], 1)
        self.assertEqual(diag["market_data_status"], "ok")
        self.assertNotIn("market_data_unavailable", diag["degraded_reasons"])
        self.assertNotIn("partial_market_data", diag["degraded_reasons"])
        self.assertEqual(body["status"], "ok")

        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertEqual(item["outcome"], "persisted_with_returns")
        self.assertIsNone(item["reason"])
        self.assertEqual(item["status"], "ok")


# ---------------------------------------------------------------------------
# /movers/backfill-preview — zero-cost eligibility preview.
#
# Mirrors the backfill's pre-filter / sort / per-cluster classification
# without touching the LLM, market_check, persistence, or the
# headline_registry.  Tests pin the four no-call invariants and the
# response shape the operator UI depends on.
# ---------------------------------------------------------------------------


class _PreviewBase(_Base):
    """Shared helpers for the preview-endpoint contract tests."""

    def _seed_news_with_meta(
        self,
        clusters: list[dict],
    ) -> None:
        self.api._news_cache["data"] = {
            "clusters": clusters,
            "total_headlines": len(clusters),
            "feed_status": [{"name": "test", "ok": True}],
            "refresh_meta": {
                "status": "ok", "freshness": "fresh",
                "last_successful_refresh":
                    datetime.now().isoformat(timespec="seconds"),
            },
            "_schema_version": self.api._NEWS_CACHE_VERSION,
        }
        self.api._news_cache["ts"] = 999_999_999.0


class TestPreviewZeroCost(_PreviewBase):
    """Hard contract: the preview must call NO paid / side-effect path."""

    def test_preview_does_not_call_llm_market_check_persist_or_registry(self):
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "OPEC cuts output by 500k bpd",
                "source_count": 4,
                "published_at": datetime.now().isoformat(timespec="seconds"),
            },
            {
                "id": 2,
                "headline": "Fed signals two cuts at next meeting",
                "source_count": 3,
                "published_at": datetime.now().isoformat(timespec="seconds"),
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("api.analyze_event") as analyze_mock, \
             patch("api.market_check") as market_mock, \
             patch("api._persist_event") as persist_mock, \
             patch("routes.movers._hr.advance_state") as advance_state_mock:
            r = self.client.get("/movers/backfill-preview")
        self.assertEqual(r.status_code, 200, r.text)
        analyze_mock.assert_not_called()
        market_mock.assert_not_called()
        persist_mock.assert_not_called()
        advance_state_mock.assert_not_called()
        # The preview must not invent or persist events.
        self.assertEqual(db.load_recent_events(50), [])


class TestPreviewResponseShape(_PreviewBase):
    """Per-item fields and aggregate counts the UI binds to."""

    def test_each_item_carries_required_fields(self):
        # Relative timestamp so the cluster stays inside the default
        # recency window regardless of when the suite runs; a hardcoded
        # date silently slips outside the window once calendar time
        # advances past it and the route then skips the cluster as
        # ``outside_recency_window`` instead of returning the eligible
        # preview row this test pins.
        recent_published_at = datetime.now().isoformat(timespec="seconds")
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "OPEC cuts output by 500k bpd",
                "source_count": 4,
                "published_at": recent_published_at,
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get("/movers/backfill-preview")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        for key in (
            "items", "counts", "skip_reasons", "filters",
            "news_source", "llm_available",
            "llm_provider", "analysis_model", "analysis_model_key",
        ):
            self.assertIn(key, body, f"missing top-level key: {key}")
        self.assertGreaterEqual(len(body["items"]), 1)
        item = body["items"][0]
        for key in (
            "headline", "source_count", "published_at",
            "skip_reason", "already_analyzed", "would_call_llm",
        ):
            self.assertIn(key, item, f"missing item key: {key}")
        # Source count came back as an int, published_at preserved.
        self.assertEqual(item["source_count"], 4)
        self.assertEqual(item["published_at"], recent_published_at)
        # No registry / cache hit on a fresh DB → eligible.
        self.assertIsNone(item["skip_reason"])
        self.assertFalse(item["already_analyzed"])
        self.assertTrue(item["would_call_llm"])

    def test_eligible_counts_match_skip_reasons(self):
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "OPEC cuts output by 500k bpd",
                "source_count": 4,
                "published_at": datetime.now().isoformat(timespec="seconds"),
            },
            {
                "id": 2,
                "headline": "Fed signals two cuts at next meeting",
                "source_count": 3,
                "published_at": datetime.now().isoformat(timespec="seconds"),
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get("/movers/backfill-preview")
        body = r.json()
        items = body["items"]
        eligible = sum(1 for i in items if i["skip_reason"] is None)
        self.assertEqual(body["counts"]["eligible"], eligible)
        # would_call_llm equals eligible when the API key is set.
        self.assertEqual(body["counts"]["would_call_llm"], eligible)


class TestPreviewRespectsRecencyAndRelevance(_PreviewBase):
    """Pre-filter rejections show up in skip_reasons but not items."""

    def test_outside_recency_window_excluded_from_items(self):
        from datetime import timedelta
        old_published = (
            datetime.now() - timedelta(hours=200)
        ).isoformat(timespec="seconds")
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "Older OPEC story",
                "source_count": 3,
                "published_at": old_published,
            },
            {
                "id": 2,
                "headline": "Recent Fed signals two cuts",
                "source_count": 3,
                "published_at": datetime.now().isoformat(timespec="seconds"),
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get(
                "/movers/backfill-preview?since_hours=48",
            )
        body = r.json()
        headlines = [i["headline"] for i in body["items"]]
        self.assertNotIn("Older OPEC story", headlines)
        self.assertEqual(
            body["skip_reasons"].get("outside_recency_window"), 1,
        )

    def test_irrelevant_headline_excluded_from_items(self):
        # ``news_relevance.is_relevant`` rejects this headline (sports);
        # the preview must aggregate it into skip_reasons without
        # surfacing it in items.
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "Olympic skater wins gold medal",
                "source_count": 3,
                "published_at": datetime.now().isoformat(timespec="seconds"),
            },
            {
                "id": 2,
                "headline": "Fed signals two cuts at next meeting",
                "source_count": 3,
                "published_at": datetime.now().isoformat(timespec="seconds"),
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get("/movers/backfill-preview")
        body = r.json()
        headlines = [i["headline"] for i in body["items"]]
        self.assertNotIn("Olympic skater wins gold medal", headlines)
        self.assertGreaterEqual(
            body["skip_reasons"].get("irrelevant_headline", 0), 1,
        )


class TestPreviewRespectsRegistryState(_PreviewBase):
    """Registry-analyzed clusters surface as already_analyzed=True."""

    def test_registry_analyzed_marks_already_analyzed(self):
        from news_sources import _dedup_key
        import headline_registry as _hr
        headline = "OPEC cuts output by 500k bpd"
        title_key = _dedup_key(headline)
        # ``advance_state`` is forward-only on existing rows — the
        # registry must carry a ``seen`` row first.  Then we stamp it
        # ``analyzed`` so the preview's read sees the advanced state.
        now_iso = datetime.now().isoformat(timespec="seconds")
        db.upsert_headline_registry_seen(
            [("test", title_key, None)], now_iso,
        )
        _hr.advance_state(
            title_key=title_key,
            new_state="analyzed",
            event_id=12345,
        )
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": headline,
                "source_count": 5,
                "published_at": datetime.now().isoformat(timespec="seconds"),
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get("/movers/backfill-preview")
        body = r.json()
        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertEqual(item["skip_reason"], "registry_already_analyzed")
        self.assertTrue(item["already_analyzed"])
        self.assertFalse(item["would_call_llm"])
        self.assertEqual(body["counts"]["eligible"], 0)
        self.assertEqual(body["counts"]["already_analyzed"], 1)


class TestPreviewForceReanalyze(_PreviewBase):
    """force_reanalyze=true ignores registry / cache markers."""

    def test_force_reanalyze_brings_registry_row_back_to_eligible(self):
        from news_sources import _dedup_key
        import headline_registry as _hr
        headline = "OPEC cuts output by 500k bpd"
        title_key = _dedup_key(headline)
        now_iso = datetime.now().isoformat(timespec="seconds")
        db.upsert_headline_registry_seen(
            [("test", title_key, None)], now_iso,
        )
        _hr.advance_state(
            title_key=title_key,
            new_state="analyzed",
            event_id=12345,
        )
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": headline,
                "source_count": 5,
                "published_at": datetime.now().isoformat(timespec="seconds"),
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get(
                "/movers/backfill-preview?force_reanalyze=true",
            )
        body = r.json()
        item = body["items"][0]
        self.assertIsNone(item["skip_reason"])
        self.assertFalse(item["already_analyzed"])
        self.assertTrue(item["would_call_llm"])


class TestPreviewMissingApiKey(_PreviewBase):
    """Without an API key, eligible items report would_call_llm=False."""

    def test_no_api_key_surfaces_llm_unavailable_in_payload(self):
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "OPEC cuts output by 500k bpd",
                "source_count": 4,
                "published_at": datetime.now().isoformat(timespec="seconds"),
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            r = self.client.get("/movers/backfill-preview")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertFalse(body["llm_available"])
        item = body["items"][0]
        # Eligible by registry / cache rules — but no LLM call would
        # actually fire because the key is missing.
        self.assertIsNone(item["skip_reason"])
        self.assertFalse(item["would_call_llm"])
        self.assertEqual(body["counts"]["would_call_llm"], 0)


class TestPreviewPaidGuardUnchanged(_PreviewBase):
    """Adding the preview must not weaken the paid-backfill guard."""

    def test_multi_call_paid_backfill_still_requires_confirm_paid(self):
        self._seed_news(["OPEC cuts output by 500k bpd"])
        r = self.client.post(
            "/movers/backfill-recent?dry_run=false&max_llm_calls=2",
        )
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("confirm_paid", r.json().get("detail", ""))


# ---------------------------------------------------------------------------
# Preview candidate ranking — zero-cost score surfaces "major market
# headline" above "generic finance wrap" noise.  All inputs come from
# already-cached cluster metadata (source_count, sources, headline
# text); ranking does NOT call the LLM, market_check, or yfinance.
# ---------------------------------------------------------------------------


class TestPreviewRankingPrefersMajorOverGeneric(_PreviewBase):
    """A central-bank headline at a lower source_count must rank above
    a generic finance wrap at a higher source_count.  The legacy
    source_count-only sort produced the opposite order."""

    def test_macro_headline_outranks_generic_finance_wrap(self):
        ts = datetime.now().isoformat(timespec="seconds")
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "Wall Street markets close mixed",
                "source_count": 6,
                "published_at": ts,
                "sources": [{"name": "MarketWatch"}],
            },
            {
                "id": 2,
                "headline": "Fed signals two rate cuts at next meeting",
                "source_count": 3,
                "published_at": ts,
                "sources": [{"name": "Reuters World"}],
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get("/movers/backfill-preview")
        body = r.json()
        headlines = [i["headline"] for i in body["items"]]
        self.assertLess(
            headlines.index("Fed signals two rate cuts at next meeting"),
            headlines.index("Wall Street markets close mixed"),
            f"macro headline should outrank generic finance wrap; "
            f"got order: {headlines}",
        )

    def test_geopolitical_headline_outranks_generic_finance_wrap(self):
        ts = datetime.now().isoformat(timespec="seconds")
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "Bond yields tick higher in light trading",
                "source_count": 5,
                "published_at": ts,
                "sources": [{"name": "Yahoo Finance"}],
            },
            {
                "id": 2,
                "headline": "US imposes new sanctions on Iranian crude exports",
                "source_count": 3,
                "published_at": ts,
                "sources": [{"name": "Reuters World"}],
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get("/movers/backfill-preview")
        body = r.json()
        headlines = [i["headline"] for i in body["items"]]
        self.assertLess(
            headlines.index(
                "US imposes new sanctions on Iranian crude exports"
            ),
            headlines.index("Bond yields tick higher in light trading"),
            f"geopolitical+commodity headline should outrank generic "
            f"yields-tick wrap; got order: {headlines}",
        )


class TestPreviewItemsCarryRankingDiagnostics(_PreviewBase):
    """Per-item ``rank_score`` + ``rank_factors`` are stable shape so
    the operator UI can explain why each candidate ranked where it did."""

    _RANK_FACTOR_KEYS = (
        "source_count", "high_tier_sources", "has_asset_terms",
        "macro_policy", "geopolitical", "commodity_policy",
        "corporate_action", "generic_finance_noise",
    )

    def test_each_item_has_rank_score_and_full_rank_factors_shape(self):
        ts = datetime.now().isoformat(timespec="seconds")
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "Fed signals two rate cuts at next meeting",
                "source_count": 4,
                "published_at": ts,
                "sources": [
                    {"name": "Reuters World"},
                    {"name": "Bloomberg Markets"},
                ],
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get("/movers/backfill-preview")
        item = r.json()["items"][0]
        self.assertIn("rank_score", item)
        self.assertIsInstance(item["rank_score"], (int, float))
        self.assertIn("rank_factors", item)
        factors = item["rank_factors"]
        for key in self._RANK_FACTOR_KEYS:
            self.assertIn(
                key, factors, f"missing rank_factors key: {key}",
            )
        # Fed mention → macro_policy fires.  Reuters + Bloomberg are
        # both ``high`` tier in news_fetch._SOURCE_TIERS.
        self.assertTrue(factors["macro_policy"])
        self.assertEqual(factors["high_tier_sources"], 2)
        self.assertEqual(factors["source_count"], 4)
        self.assertFalse(factors["generic_finance_noise"])

    def test_geopolitical_and_commodity_factors_fire(self):
        ts = datetime.now().isoformat(timespec="seconds")
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "OPEC slashes output 500k bpd; Iran sanctions extended",
                "source_count": 4,
                "published_at": ts,
                "sources": [{"name": "Reuters World"}],
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get("/movers/backfill-preview")
        factors = r.json()["items"][0]["rank_factors"]
        self.assertTrue(factors["commodity_policy"])
        self.assertTrue(factors["geopolitical"])

    def test_generic_finance_noise_factor_fires(self):
        ts = datetime.now().isoformat(timespec="seconds")
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "Wall Street markets close mixed in light trading",
                "source_count": 4,
                "published_at": ts,
                "sources": [{"name": "Yahoo Finance"}],
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get("/movers/backfill-preview")
        factors = r.json()["items"][0]["rank_factors"]
        self.assertTrue(factors["generic_finance_noise"])
        self.assertFalse(factors["macro_policy"])
        self.assertEqual(factors["high_tier_sources"], 0)

    def test_missing_sources_field_yields_zero_high_tier(self):
        # ``_seed_news`` (used by other paid-flow tests) omits ``sources``.
        # The scorer must default to 0 without raising.
        ts = datetime.now().isoformat(timespec="seconds")
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "Treasury yields rise on jobs data",
                "source_count": 3,
                "published_at": ts,
                # NB: no ``sources`` key.
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get("/movers/backfill-preview")
        item = r.json()["items"][0]
        self.assertEqual(item["rank_factors"]["high_tier_sources"], 0)
        # Score still numeric — no None / NaN leakage on missing sources.
        self.assertIsInstance(item["rank_score"], (int, float))


class TestPreviewRankingTiebreakStability(_PreviewBase):
    """Equal-rank clusters fall back to the legacy
    ``(source_count, has_asset_terms)`` tiebreak so order is
    deterministic across runs."""

    def test_equal_score_falls_back_to_source_count(self):
        ts = datetime.now().isoformat(timespec="seconds")
        self._seed_news_with_meta([
            {
                "id": 1,
                "headline": "OPEC slashes output 500k bpd",
                "source_count": 3,
                "published_at": ts,
                "sources": [{"name": "Reuters World"}],
            },
            {
                "id": 2,
                "headline": "OPEC raises output 500k bpd",
                "source_count": 5,
                "published_at": ts,
                "sources": [{"name": "Reuters World"}],
            },
        ])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            r = self.client.get("/movers/backfill-preview")
        headlines = [i["headline"] for i in r.json()["items"]]
        # Both score the same on keyword categories + tier; higher
        # source_count wins the tiebreak.
        self.assertEqual(
            headlines[0], "OPEC raises output 500k bpd",
        )


if __name__ == "__main__":
    unittest.main()
