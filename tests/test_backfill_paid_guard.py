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


class TestBackfillPreviewNoSpend(_PaidGuardTestBase):
    """GET /movers/backfill-preview is a zero-cost classifier.

    It must never call ``analyze_event``, ``market_check``,
    ``_persist_event``, or ``yfinance`` — even when clusters are
    uncached, market-relevant, and an LLM key is present.  Pinning
    that contract here so a regression that lets the preview path
    spend money or hit the network is caught before merge.
    """

    def _no_spend_stubs(self) -> dict:
        """Routes-side stubs that keep the preview deterministic
        without touching feeds, news_relevance, or env state."""
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
            "_llm_available":               lambda *_: True,
            "_headline_is_market_relevant": lambda *_: True,
        }

    def _ban_spend_apis(self) -> None:
        """Replace ``analyze_event`` / ``market_check`` /
        ``_persist_event`` on the ``api`` module and the two
        ``yfinance`` entry points with raisers.  Recorded so
        tearDown can restore them."""
        import api as _api
        import yfinance
        self._spend_patches: list = []

        def _ban(label: str):
            def _raise(*_a, **_kw):
                raise AssertionError(
                    f"backfill-preview must not call {label}",
                )
            return _raise

        for name in ("analyze_event", "market_check", "_persist_event"):
            self._spend_patches.append((_api, name, getattr(_api, name)))
            setattr(_api, name, _ban(f"api.{name}"))
        for name in ("download", "Ticker"):
            self._spend_patches.append(
                (yfinance, name, getattr(yfinance, name)),
            )
            setattr(yfinance, name, _ban(f"yfinance.{name}"))

    def _restore_spend_apis(self) -> None:
        for mod, name, original in self._spend_patches:
            setattr(mod, name, original)
        self._spend_patches = []

    def setUp(self) -> None:
        super().setUp()
        self._ban_spend_apis()

    def tearDown(self) -> None:
        self._restore_spend_apis()
        super().tearDown()

    def test_preview_invokes_no_spend_apis(self) -> None:
        """Two uncached, market-relevant clusters with an LLM key
        present.  The preview must classify them without invoking any
        spend API; if it does, the banned stubs raise AssertionError
        and this test fails."""
        from routes.movers import movers_backfill_preview
        self._stub_route(self._no_spend_stubs())
        result = movers_backfill_preview(
            limit=25,
            since_hours=72,
            include_low_signal=False,
            force_reanalyze=False,
        )
        items = result["items"]
        self.assertEqual(len(items), 2)
        # Both clusters are uncached + relevant + LLM-available.
        self.assertTrue(all(i["would_call_llm"] for i in items))
        self.assertTrue(all(not i["already_analyzed"] for i in items))

    def test_preview_response_envelope_carries_required_fields(self) -> None:
        """Wire shape: items / counts / skip_reasons + model and
        provider identifiers so the operator can confirm what would
        run before authorising a paid backfill."""
        from routes.movers import movers_backfill_preview
        self._stub_route(self._no_spend_stubs())
        result = movers_backfill_preview(
            limit=25,
            since_hours=72,
            include_low_signal=False,
            force_reanalyze=False,
        )
        for key in ("items", "counts", "skip_reasons",
                    "analysis_model", "llm_provider"):
            self.assertIn(key, result, f"missing top-level key: {key}")
        for k in ("scanned", "considered", "eligible",
                  "already_analyzed", "would_call_llm"):
            self.assertIn(k, result["counts"], f"missing counts key: {k}")
        self.assertIsInstance(result["items"], list)
        self.assertIsInstance(result["counts"], dict)
        self.assertIsInstance(result["skip_reasons"], dict)
        self.assertIsInstance(result["analysis_model"], str)
        self.assertTrue(result["analysis_model"])
        self.assertIsInstance(result["llm_provider"], str)
        self.assertTrue(result["llm_provider"])

    def test_registry_analyzed_marks_already_analyzed_no_llm_call(self) -> None:
        """A cluster whose registry shows state='analyzed' surfaces
        as already_analyzed=true / would_call_llm=false in the per-
        item preview — and still does not touch any spend API."""
        from news_sources import _dedup_key
        from routes.movers import movers_backfill_preview

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

        self._stub_route(self._no_spend_stubs())
        result = movers_backfill_preview(
            limit=25,
            since_hours=72,
            include_low_signal=False,
            force_reanalyze=False,
        )

        items = result["items"]
        seeded = [i for i in items
                  if i["headline"] == "OPEC slashes output 500k bpd"]
        other = [i for i in items
                 if i["headline"] == "Fed cuts rates by 25bp"]
        self.assertEqual(len(seeded), 1)
        self.assertEqual(len(other), 1)
        # Registry-analyzed cluster: marked already_analyzed, no LLM.
        self.assertTrue(seeded[0]["already_analyzed"])
        self.assertFalse(seeded[0]["would_call_llm"])
        self.assertEqual(
            seeded[0]["skip_reason"], "registry_already_analyzed",
        )
        # The fresh cluster remains a would-call candidate.
        self.assertFalse(other[0]["already_analyzed"])
        self.assertTrue(other[0]["would_call_llm"])
        # Counts reflect the registry-skip.
        self.assertGreaterEqual(result["counts"]["already_analyzed"], 1)
        self.assertGreaterEqual(
            result["skip_reasons"].get("registry_already_analyzed", 0), 1,
        )


class TestBackfillCandidateEndpoint(_PaidGuardTestBase):
    """``POST /movers/backfill-candidate`` is the single-row paid path.

    Contract:
      * Without ``confirm_paid=true`` → 400, no LLM work attempted.
      * Hard cap of one ``_fresh_analysis_market_event`` invocation.
      * Skip gates (registry, cached-event, recency, relevance,
        low_signal) match /movers/backfill-recent so a candidate the
        preview marked ``would_skip`` doesn't get reanalyzed by accident.
      * Result dict carries ``status`` / ``reason`` / ``event_id``
        deterministically so the UI can branch.
    """

    def _stubs(
        self,
        *,
        clusters: list[dict] | None = None,
        analyze_returns: dict | None = None,
        refresh_returns: dict | None = None,
    ) -> dict:
        self._analyze_calls = {"count": 0}
        self._refresh_calls = {"count": 0}

        default_clusters = [{
            "headline":     "Fed cuts rates by 25bp",
            "source_count": 5,
            "published_at": "2026-05-03T08:00:00",
            "sources":      [{"name": "Reuters"}],
        }]
        seeded_clusters = clusters if clusters is not None else default_clusters

        def fake_payload():
            return ({"clusters": seeded_clusters}, "memory")

        def fake_fresh(*a, **kw):
            self._analyze_calls["count"] += 1
            return analyze_returns or {
                "status": "ok", "analyzed": True, "with_returns": True,
                "with_tickers": True, "persisted": True, "ticker_count": 1,
                "event_id": 999, "conviction": {"impact_level": "high"},
            }

        def fake_refresh(*a, **kw):
            self._refresh_calls["count"] += 1
            return refresh_returns or {"status": "skipped", "reason": "needs_fresh"}

        return {
            "_cached_news_payload":           fake_payload,
            "_fresh_analysis_market_event":   fake_fresh,
            "_refresh_existing_market_event": fake_refresh,
            "_llm_available":                 lambda *_: True,
            "_headline_is_market_relevant":   lambda *_: True,
        }

    def test_blocks_without_confirm_paid(self) -> None:
        from fastapi import HTTPException
        from routes.movers import movers_backfill_candidate
        self._stub_route(self._stubs())
        with self.assertRaises(HTTPException) as ctx:
            movers_backfill_candidate(
                headline="Fed cuts rates by 25bp",
                confirm_paid=False,
                since_hours=72,
                force_reanalyze=False,
                include_low_signal=False,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("confirm_paid", ctx.exception.detail)
        self.assertEqual(self._analyze_calls["count"], 0)
        self.assertEqual(self._refresh_calls["count"], 0)

    def test_analyzes_one_candidate_when_confirmed(self) -> None:
        from routes.movers import movers_backfill_candidate
        self._stub_route(self._stubs())
        result = movers_backfill_candidate(
            headline="Fed cuts rates by 25bp",
            confirm_paid=True,
            since_hours=72,
            force_reanalyze=False,
            include_low_signal=False,
        )
        # Exactly one LLM call regardless of pipeline path.
        self.assertEqual(self._analyze_calls["count"], 1)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["analyzed"])
        self.assertTrue(result["persisted"])
        self.assertEqual(result["llm_calls"], 1)
        self.assertEqual(result["event_id"], 999)
        self.assertEqual(result["headline"], "Fed cuts rates by 25bp")

    def test_candidate_not_found_returns_skipped(self) -> None:
        from routes.movers import movers_backfill_candidate
        self._stub_route(self._stubs())
        result = movers_backfill_candidate(
            headline="Headline that is not in the cache at all",
            confirm_paid=True,
            since_hours=72,
            force_reanalyze=False,
            include_low_signal=False,
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "candidate_not_found")
        self.assertEqual(self._analyze_calls["count"], 0)
        self.assertEqual(result["llm_calls"], 0)

    def test_registry_already_analyzed_skips_without_llm(self) -> None:
        from news_sources import _dedup_key
        from routes.movers import movers_backfill_candidate

        title_key = _dedup_key("Fed cuts rates by 25bp")
        self._db.upsert_headline_registry_seen(
            [("Reuters", title_key, 1)], "2026-05-01T10:00:00",
        )
        self._db.update_registry_state(
            title_key=title_key, new_state="analyzed",
            event_id=42, impact_level="high",
            analyzed_at="2026-05-01T10:30:00",
        )
        self._stub_route(self._stubs())
        result = movers_backfill_candidate(
            headline="Fed cuts rates by 25bp",
            confirm_paid=True,
            since_hours=72,
            force_reanalyze=False,
            include_low_signal=False,
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "registry_already_analyzed")
        self.assertEqual(self._analyze_calls["count"], 0)
        self.assertEqual(result["llm_calls"], 0)

    def test_outside_recency_window_skips_without_llm(self) -> None:
        from routes.movers import movers_backfill_candidate
        old_clusters = [{
            "headline":     "Fed cuts rates by 25bp",
            "source_count": 5,
            "published_at": "2024-01-01T08:00:00",
            "sources":      [{"name": "Reuters"}],
        }]
        self._stub_route(self._stubs(clusters=old_clusters))
        result = movers_backfill_candidate(
            headline="Fed cuts rates by 25bp",
            confirm_paid=True,
            since_hours=24,
            force_reanalyze=False,
            include_low_signal=False,
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "outside_recency_window")
        self.assertEqual(self._analyze_calls["count"], 0)

    def test_irrelevant_headline_skips_unless_low_signal_opt_in(self) -> None:
        from routes.movers import movers_backfill_candidate
        # Stub relevance → False so the headline fails the gate.
        stubs = self._stubs()
        stubs["_headline_is_market_relevant"] = lambda *_: False
        self._stub_route(stubs)
        result = movers_backfill_candidate(
            headline="Fed cuts rates by 25bp",
            confirm_paid=True,
            since_hours=72,
            force_reanalyze=False,
            include_low_signal=False,
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "irrelevant_headline")
        self.assertEqual(self._analyze_calls["count"], 0)

    def test_irrelevant_headline_admitted_with_include_low_signal(self) -> None:
        from routes.movers import movers_backfill_candidate
        stubs = self._stubs()
        stubs["_headline_is_market_relevant"] = lambda *_: False
        self._stub_route(stubs)
        result = movers_backfill_candidate(
            headline="Fed cuts rates by 25bp",
            confirm_paid=True,
            since_hours=72,
            force_reanalyze=False,
            include_low_signal=True,
        )
        # include_low_signal lets the irrelevant-headline gate through —
        # the LLM call proceeds.
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self._analyze_calls["count"], 1)

    def test_llm_unavailable_returns_degraded(self) -> None:
        from routes.movers import movers_backfill_candidate
        stubs = self._stubs()
        stubs["_llm_available"] = lambda *_: False
        self._stub_route(stubs)
        result = movers_backfill_candidate(
            headline="Fed cuts rates by 25bp",
            confirm_paid=True,
            since_hours=72,
            force_reanalyze=False,
            include_low_signal=False,
        )
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["reason"], "llm_unavailable")
        self.assertEqual(self._analyze_calls["count"], 0)
        self.assertEqual(result["llm_calls"], 0)

    def test_force_reanalyze_bypasses_registry_skip(self) -> None:
        from news_sources import _dedup_key
        from routes.movers import movers_backfill_candidate

        title_key = _dedup_key("Fed cuts rates by 25bp")
        self._db.upsert_headline_registry_seen(
            [("Reuters", title_key, 1)], "2026-05-01T10:00:00",
        )
        self._db.update_registry_state(
            title_key=title_key, new_state="analyzed",
            event_id=42, impact_level="high",
            analyzed_at="2026-05-01T10:30:00",
        )
        self._stub_route(self._stubs())
        result = movers_backfill_candidate(
            headline="Fed cuts rates by 25bp",
            confirm_paid=True,
            since_hours=72,
            force_reanalyze=True,
            include_low_signal=False,
        )
        # force_reanalyze=True overrides the registry skip → one LLM call.
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self._analyze_calls["count"], 1)


if __name__ == "__main__":
    unittest.main()
