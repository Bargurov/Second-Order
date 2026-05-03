"""Tests for the /movers/backfill-recent paid-backfill safety guard.

A multi-call paid backfill (dry_run=false AND max_llm_calls > 1) must
require confirm_paid=true.  Without it, the route must short-circuit
with a clear 400 BEFORE any LLM-spending work begins.

Run with:
    python -m unittest tests.test_backfill_paid_guard -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api  # noqa: F401  — break circular import surfaced in test path


class _PaidGuardTestBase(unittest.TestCase):
    """Per-test temp DB so cases never share state.  Mirrors the
    _RegistryTestBase pattern from tests.test_headline_registry."""

    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        import db
        self._orig_db_file = db.DB_FILE
        db.DB_FILE = self.db_path
        db._db_ready = False
        db.init_db()
        self._db = db
        self._original: dict = {}
        self._rm = None

    def tearDown(self) -> None:
        # Restore monkey-patches.
        if self._rm is not None:
            for name, value in self._original.items():
                if value is None:
                    if hasattr(self._rm, name):
                        delattr(self._rm, name)
                else:
                    setattr(self._rm, name, value)
        # Restore db state.
        import db
        db.DB_FILE = self._orig_db_file
        db._db_ready = False
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _stub_route(self, monkey: dict) -> None:
        import routes.movers as rm
        for name, value in monkey.items():
            self._original[name] = getattr(rm, name, None)
            setattr(rm, name, value)
        self._rm = rm


class TestPaidBackfillGuard(_PaidGuardTestBase):

    def _stubs_with_analyze_counter(self) -> dict:
        """Stub set that lets us count how many times the analyze
        path was invoked.  ``count`` is mutable so the test can
        assert against it after the call."""
        self._analyze_calls = {"count": 0}

        def fake_fresh(*a, **kw):
            self._analyze_calls["count"] += 1
            return {"status": "ok", "analyzed": True, "with_returns": True,
                    "with_tickers": True, "persisted": True, "ticker_count": 1,
                    "event_id": 99, "conviction": {"impact_level": "high"}}

        def fake_payload():
            return ({
                "clusters": [{
                    "headline":     "Fed cuts rates by 25bp",
                    "source_count": 5,
                    "published_at": "2026-05-03T08:00:00",
                    "sources":      [{"name": "Reuters"}],
                }],
            }, "memory")

        return {
            "_cached_news_payload":         fake_payload,
            "_fresh_analysis_market_event": fake_fresh,
            "_max_backfill_llm_calls":      lambda: 5,
            "_backfill_dry_run_default":    lambda: False,
            "_llm_available":               lambda *_: True,
            "_headline_is_market_relevant": lambda *_: True,
        }

    def test_blocks_multi_call_paid_without_confirm(self) -> None:
        """dry_run=false + max_llm_calls=2 + confirm_paid=false → 400.
        Zero LLM calls in the blocked path."""
        from fastapi import HTTPException
        from routes.movers import movers_backfill_recent
        self._stub_route(self._stubs_with_analyze_counter())
        with self.assertRaises(HTTPException) as ctx:
            movers_backfill_recent(
                limit=3,
                max_llm_calls=2,
                scan_limit=10,
                since_hours=72,
                dry_run=False,
                force_reanalyze=False,
                include_low_signal=False,
                confirm_paid=False,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("confirm_paid", ctx.exception.detail)
        self.assertEqual(self._analyze_calls["count"], 0)

    def test_allows_multi_call_paid_with_confirm(self) -> None:
        """dry_run=false + max_llm_calls=2 + confirm_paid=true → proceeds.
        Existing max_llm_calls behaviour preserved."""
        from routes.movers import movers_backfill_recent
        self._stub_route(self._stubs_with_analyze_counter())
        result = movers_backfill_recent(
            limit=3,
            max_llm_calls=2,
            scan_limit=10,
            since_hours=72,
            dry_run=False,
            force_reanalyze=False,
            include_low_signal=False,
            confirm_paid=True,
        )
        # Analyze stub was called at least once; budget is honored.
        self.assertGreaterEqual(self._analyze_calls["count"], 1)
        self.assertLessEqual(
            self._analyze_calls["count"],
            2,
            "max_llm_calls=2 budget should be honored",
        )
        self.assertEqual(
            result.get("max_llm_calls"), 2,
            "echoed budget should match request",
        )

    def test_dry_run_unaffected_by_guard(self) -> None:
        """dry_run=true + max_llm_calls=20 + confirm_paid=false → proceeds
        as a dry run.  No LLM calls; no 400."""
        from routes.movers import movers_backfill_recent
        self._stub_route(self._stubs_with_analyze_counter())
        result = movers_backfill_recent(
            limit=3,
            max_llm_calls=2,
            scan_limit=10,
            since_hours=72,
            dry_run=True,
            force_reanalyze=False,
            include_low_signal=False,
            confirm_paid=False,
        )
        self.assertEqual(self._analyze_calls["count"], 0)
        self.assertTrue(result.get("dry_run"))
        skipped = result.get("diagnostics", {}).get("skipped", {})
        self.assertGreaterEqual(skipped.get("dry_run", 0), 1)

    def test_single_call_paid_unaffected_by_guard(self) -> None:
        """dry_run=false + max_llm_calls=1 + confirm_paid=false → proceeds.
        Single-call paid runs are below the guard threshold."""
        from routes.movers import movers_backfill_recent
        self._stub_route(self._stubs_with_analyze_counter())
        result = movers_backfill_recent(
            limit=3,
            max_llm_calls=1,
            scan_limit=10,
            since_hours=72,
            dry_run=False,
            force_reanalyze=False,
            include_low_signal=False,
            confirm_paid=False,
        )
        self.assertEqual(self._analyze_calls["count"], 1)
        self.assertEqual(result.get("max_llm_calls"), 1)


class TestDryRunPreview(_PaidGuardTestBase):
    """Dry-run mode returns a per-cluster preview with predicted
    actions, a would_call_llm count, and a would_skip_paid_guard
    boolean — without spending any LLM or market-data calls."""

    def _stubs_no_spend(self) -> dict:
        """Stub set whose analyze + refresh helpers raise if called.
        Dry-run preview must not call either."""
        self._analyze_calls = {"count": 0}
        self._refresh_calls = {"count": 0}

        def fake_fresh(*a, **kw):
            self._analyze_calls["count"] += 1
            raise AssertionError(
                "dry_run preview must not call _fresh_analysis_market_event",
            )

        def fake_refresh(*a, **kw):
            self._refresh_calls["count"] += 1
            raise AssertionError(
                "dry_run preview must not call _refresh_existing_market_event",
            )

        def fake_payload():
            return ({
                "clusters": [
                    {"headline":     "OPEC slashes output 500k bpd",
                     "source_count": 5,
                     "published_at": "2026-05-03T08:00:00",
                     "sources":      [{"name": "Reuters"}]},
                    {"headline":     "Fed cuts rates by 25bp",
                     "source_count": 7,
                     "published_at": "2026-05-03T09:00:00",
                     "sources":      [{"name": "Bloomberg"}]},
                ],
            }, "memory")

        return {
            "_cached_news_payload":         fake_payload,
            "_fresh_analysis_market_event": fake_fresh,
            "_refresh_existing_market_event": fake_refresh,
            "_max_backfill_llm_calls":      lambda: 5,
            "_backfill_dry_run_default":    lambda: True,
            "_llm_available":               lambda *_: True,
            "_headline_is_market_relevant": lambda *_: True,
        }

    def test_dry_run_returns_preview_items_per_cluster(self) -> None:
        from routes.movers import movers_backfill_recent
        self._stub_route(self._stubs_no_spend())
        result = movers_backfill_recent(
            limit=10,
            max_llm_calls=3,
            scan_limit=10,
            since_hours=72,
            dry_run=True,
            force_reanalyze=False,
            include_low_signal=False,
            confirm_paid=False,
        )
        # No LLM or market_data calls happened.
        self.assertEqual(self._analyze_calls["count"], 0)
        self.assertEqual(self._refresh_calls["count"], 0)
        # Two preview items (one per cluster), each carrying the new
        # predicted-action shape.
        items = result["items"]
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertIn("predicted_action",      item)
            self.assertIn("predicted_skip_reason", item)
            self.assertIn("would_call_llm",        item)
        actions = sorted(i["predicted_action"] for i in items)
        # Both clusters are uncached + market-relevant + not registered,
        # so both predict would_analyze.
        self.assertEqual(actions, ["would_analyze", "would_analyze"])
        # Each predicts an LLM call.
        self.assertTrue(all(i["would_call_llm"] for i in items))

    def test_dry_run_diagnostics_carry_new_fields(self) -> None:
        from routes.movers import movers_backfill_recent
        self._stub_route(self._stubs_no_spend())
        result = movers_backfill_recent(
            limit=10,
            max_llm_calls=3,
            scan_limit=10,
            since_hours=72,
            dry_run=True,
            force_reanalyze=False,
            include_low_signal=False,
            confirm_paid=False,
        )
        diag = result["diagnostics"]
        # would_call_llm == sum(items where would_call_llm=True),
        # capped at the budget.  Two predicted analyses, budget 3 → 2.
        self.assertEqual(diag["would_call_llm"], 2)
        # would_skip_paid_guard reflects max_llm_calls=3 + confirm_paid=false.
        self.assertTrue(diag["would_skip_paid_guard"])
        # Existing skipped["dry_run"] still increments per cluster
        # (preserves the historical counter semantic).
        self.assertEqual(diag["skipped"].get("dry_run"), 2)

    def test_dry_run_would_skip_paid_guard_false_when_confirmed(self) -> None:
        from routes.movers import movers_backfill_recent
        self._stub_route(self._stubs_no_spend())
        result = movers_backfill_recent(
            limit=10,
            max_llm_calls=3,
            scan_limit=10,
            since_hours=72,
            dry_run=True,
            force_reanalyze=False,
            include_low_signal=False,
            confirm_paid=True,
        )
        self.assertFalse(result["diagnostics"]["would_skip_paid_guard"])

    def test_dry_run_would_skip_paid_guard_false_for_single_call(self) -> None:
        from routes.movers import movers_backfill_recent
        self._stub_route(self._stubs_no_spend())
        result = movers_backfill_recent(
            limit=10,
            max_llm_calls=1,
            scan_limit=10,
            since_hours=72,
            dry_run=True,
            force_reanalyze=False,
            include_low_signal=False,
            confirm_paid=False,
        )
        # max_llm_calls=1 is below the guard threshold.
        self.assertFalse(result["diagnostics"]["would_skip_paid_guard"])

    def test_dry_run_predicts_budget_exhaustion(self) -> None:
        """With 2 clusters + max_llm_calls=1, the second cluster's
        preview shows would_skip / llm_budget_exhausted."""
        from routes.movers import movers_backfill_recent
        self._stub_route(self._stubs_no_spend())
        result = movers_backfill_recent(
            limit=10,
            max_llm_calls=1,
            scan_limit=10,
            since_hours=72,
            dry_run=True,
            force_reanalyze=False,
            include_low_signal=False,
            confirm_paid=False,
        )
        items = result["items"]
        actions = [i["predicted_action"] for i in items]
        skip_reasons = [i["predicted_skip_reason"] for i in items]
        self.assertEqual(actions.count("would_analyze"), 1)
        self.assertEqual(actions.count("would_skip"), 1)
        self.assertIn("llm_budget_exhausted", skip_reasons)
        # would_call_llm in diagnostics matches: 1 predicted call (= budget cap).
        self.assertEqual(result["diagnostics"]["would_call_llm"], 1)

    def test_dry_run_emits_preview_for_registry_already_analyzed(self) -> None:
        """A cluster whose registry shows state='analyzed' produces a
        would_skip/registry_already_analyzed preview item — without
        going through the LLM-prediction branch."""
        from news_sources import _dedup_key
        from routes.movers import movers_backfill_recent

        # Seed registry: first headline already analyzed.
        tk_seeded = _dedup_key("OPEC slashes output 500k bpd")
        self._db.upsert_headline_registry_seen(
            [("Reuters", tk_seeded, 1)], "2026-05-01T10:00:00",
        )
        self._db.update_registry_state(
            title_key=tk_seeded,
            new_state="analyzed",
            event_id=1,
            impact_level="high",
            analyzed_at="2026-05-01T10:30:00",
        )

        self._stub_route(self._stubs_no_spend())
        result = movers_backfill_recent(
            limit=10,
            max_llm_calls=3,
            scan_limit=10,
            since_hours=72,
            dry_run=True,
            force_reanalyze=False,
            include_low_signal=False,
            confirm_paid=False,
        )
        items = result["items"]
        # Pre-seeded headline → would_skip; the other → would_analyze.
        skip_items = [i for i in items
                      if i["predicted_action"] == "would_skip"]
        self.assertEqual(len(skip_items), 1)
        self.assertEqual(
            skip_items[0]["predicted_skip_reason"],
            "registry_already_analyzed",
        )
        # The seeded one's registry pre-LLM check fires before the
        # would_call_llm prediction, so only the other cluster
        # contributes a predicted LLM call.
        self.assertEqual(result["diagnostics"]["would_call_llm"], 1)


if __name__ == "__main__":
    unittest.main()
