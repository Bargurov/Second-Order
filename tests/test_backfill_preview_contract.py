"""T3C — zero-cost backfill-preview contract regressions.

``GET /movers/backfill-preview`` must answer four DISTINCT operator
questions without collapsing them into one boolean:

  * candidate requirement — ``requires_llm``: the corresponding paid
    action for this item is a fresh LLM analysis (structural; skip /
    cached-refresh items are False), independent of configuration;
  * provider readiness — ``llm_available``: the configured backfill
    provider has a usable (non-placeholder) key right now;
  * paid authorization — ``paid_analysis_enabled``: the server-side
    ``ENABLE_PAID_ANALYSIS`` kill-switch state;
  * executable-now — ``would_call_llm`` (backward-compatible, value
    unchanged): ``requires_llm AND llm_available`` — an authorized,
    confirmed paid run under the current provider configuration would
    reach the LLM for this item.

``execution_blockers`` lists, per requiring item, every currently
visible gate the corresponding paid request must clear (in order):
``llm_unavailable``, ``paid_analysis_disabled``, ``confirm_paid_required``
(POST /movers/backfill-candidate always demands ``confirm_paid=true``).
Counters reconcile exactly with item fields.

Every test pins ``BACKFILL_PROVIDER`` explicitly (run-window scoped
``patch.dict``) so nothing depends on the untracked ``.env`` — the exact
clean-clone hole that made the old preview assertion fail in canonical
discovery.  Every preview call runs with all paid seams banned and a DNS
guard proving zero network resolution.  Temp DB per test; the preview is
strictly read-only.
"""
from __future__ import annotations

import contextlib
import os
import socket
import sys
import tempfile
import unittest
from datetime import datetime as _datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import api as _api  # noqa: E402

_FRESH_HEADLINE = "Fed signals two rate cuts at next meeting"
_SECOND_HEADLINE = "OPEC agrees surprise oil output cut of 1m bpd"


@contextlib.contextmanager
def _env_removed(name: str):
    """Remove ``name`` from os.environ, restoring EXACTLY on exit
    (missing stays missing, prior value comes back byte-for-byte)."""
    sentinel = object()
    prior = os.environ.pop(name, sentinel)
    try:
        yield
    finally:
        if prior is not sentinel:
            os.environ[name] = prior  # type: ignore[assignment]


class _PreviewContractBase(unittest.TestCase):
    """Temp DB + seeded in-memory news cache + banned paid seams."""

    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        import db
        self._db = db
        self._orig_db_file = db.DB_FILE
        db.DB_FILE = self.db_path
        db._db_ready = False
        db.init_db()
        from fastapi.testclient import TestClient
        self.client = TestClient(_api.app)

    def tearDown(self) -> None:
        self._db.DB_FILE = self._orig_db_file
        self._db._db_ready = False
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    @staticmethod
    def _ban(label: str):
        def _raise(*_a, **_kw):
            raise AssertionError(f"preview contract: must not call {label}")
        return _raise

    def _seed_news_cache(self, *headlines: str) -> None:
        now = _datetime.now().isoformat(timespec="seconds")
        _api._news_cache["data"] = {
            "clusters": [
                {
                    "id": i + 1,
                    "headline": h,
                    "source_count": 4,
                    "published_at": now,
                    "sources": [{"name": "Reuters"}],
                }
                for i, h in enumerate(headlines)
            ],
            "total_headlines": len(headlines),
            "feed_status": [{"name": "test", "ok": True}],
            "refresh_meta": {
                "status": "ok", "freshness": "fresh",
                "last_successful_refresh": now,
            },
            "_schema_version": _api._NEWS_CACHE_VERSION,
        }
        _api._news_cache["ts"] = 999_999_999.0

    def _registry_signature(self) -> tuple:
        import sqlite3
        with sqlite3.connect(self._db.DB_FILE) as conn:
            row_count = conn.execute(
                "SELECT COUNT(*) FROM headline_registry",
            ).fetchone()[0]
        return int(row_count), dict(self._db.load_registry_state_counts())

    def _seed_registry_analyzed(self, headline: str) -> None:
        """Create a registry row (state machine requires an existing row:
        update_registry_state is an UPDATE, not an UPSERT) and advance it
        to ``analyzed`` — the preview must then classify the headline as
        registry_already_analyzed."""
        import headline_registry as _hr
        from news_sources import _dedup_key
        key = _dedup_key(headline)
        self._db.upsert_headline_registry_seen(
            [("test", key, 1)],
            _datetime.now().isoformat(timespec="seconds"),
        )
        _hr.advance_state(title_key=key, new_state="analyzed")

    @contextlib.contextmanager
    def _sealed(self):
        """Ban every paid/provider/persistence seam + DNS during a call."""
        with mock.patch("routes.movers._fresh_analysis_market_event",
                        self._ban("_fresh_analysis_market_event")), \
             mock.patch("routes.movers._refresh_existing_market_event",
                        self._ban("_refresh_existing_market_event")), \
             mock.patch("routes.movers._hr.advance_state",
                        self._ban("_hr.advance_state")), \
             mock.patch("api.analyze_event", self._ban("api.analyze_event")), \
             mock.patch("api.market_check", self._ban("api.market_check")), \
             mock.patch("api._persist_event", self._ban("api._persist_event")), \
             mock.patch("yfinance.download", self._ban("yfinance.download")), \
             mock.patch("yfinance.Ticker", self._ban("yfinance.Ticker")), \
             mock.patch.object(socket, "getaddrinfo",
                               self._ban("socket.getaddrinfo")):
            yield

    def _preview(self, **params):
        with self._sealed():
            r = self.client.get("/movers/backfill-preview",
                                params=params or {"limit": 10})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    @staticmethod
    def _reconcile(body: dict) -> None:
        items = body["items"]
        counts = body["counts"]
        assert counts["requires_llm"] == sum(
            1 for i in items if i["requires_llm"]), (counts, items)
        assert counts["would_call_llm"] == sum(
            1 for i in items if i["would_call_llm"]), (counts, items)
        assert counts["blocked"] == sum(
            1 for i in items if i["execution_blockers"]), (counts, items)
        assert counts["already_analyzed"] == sum(
            1 for i in items if i["already_analyzed"]), (counts, items)


class FreshEligibleProviderAvailableTest(_PreviewContractBase):

    def test_requirement_readiness_and_blockers_all_explicit(self):
        self._seed_news_cache(_FRESH_HEADLINE)
        sig_before = self._registry_signature()
        with mock.patch.dict(os.environ, {
            "BACKFILL_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "test-key-preview",
            "ENABLE_PAID_ANALYSIS": "true",
        }):
            body = self._preview(limit=5)
        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertEqual(item["headline"], _FRESH_HEADLINE)
        self.assertTrue(item["requires_llm"])
        self.assertTrue(item["would_call_llm"])
        self.assertFalse(item["already_analyzed"])
        self.assertIsNone(item["skip_reason"])
        # Provider ready + kill-switch on → only the confirmation gate.
        self.assertEqual(item["execution_blockers"], ["confirm_paid_required"])
        self.assertTrue(body["llm_available"])
        self.assertTrue(body["paid_analysis_enabled"])
        self._reconcile(body)
        self.assertEqual(self._registry_signature(), sig_before)


class FreshEligibleProviderUnavailableTest(_PreviewContractBase):

    def test_requirement_survives_missing_provider_key(self):
        """Provider unconfigured must NOT erase the structural LLM
        requirement, and must not misclassify the item."""
        self._seed_news_cache(_FRESH_HEADLINE)
        with mock.patch.dict(os.environ, {
            "BACKFILL_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "",
            "ENABLE_PAID_ANALYSIS": "true",
        }):
            body = self._preview(limit=5)
        item = body["items"][0]
        self.assertTrue(item["requires_llm"])          # still visible
        self.assertFalse(item["would_call_llm"])       # not executable now
        self.assertFalse(item["already_analyzed"])     # not misclassified
        self.assertIsNone(item["skip_reason"])
        self.assertEqual(item["execution_blockers"],
                         ["llm_unavailable", "confirm_paid_required"])
        self.assertFalse(body["llm_available"])
        self._reconcile(body)

    def test_clean_clone_shape_openai_default_no_key(self):
        """The exact canonical clean-clone environment: no .env, so the
        provider defaults to openai with no OPENAI_API_KEY.  The old
        conflated boolean silently reported False and hid the
        candidate's requirement — this pins the honest split."""
        self._seed_news_cache(_FRESH_HEADLINE)
        with mock.patch.dict(os.environ, {
            "BACKFILL_PROVIDER": "openai",
            "ENABLE_PAID_ANALYSIS": "true",
        }), _env_removed("OPENAI_API_KEY"):
            body = self._preview(limit=5)
        item = body["items"][0]
        self.assertTrue(item["requires_llm"])
        self.assertFalse(item["would_call_llm"])
        self.assertIn("llm_unavailable", item["execution_blockers"])
        self.assertEqual(body["llm_provider"], "openai")
        self.assertFalse(body["llm_available"])
        self._reconcile(body)


class PaidKillSwitchTest(_PreviewContractBase):

    def _preview_with_paid(self, paid_value: str | None) -> dict:
        self._seed_news_cache(_FRESH_HEADLINE)
        env = {
            "BACKFILL_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "test-key-preview",
        }
        if paid_value is None:
            with mock.patch.dict(os.environ, env), \
                 _env_removed("ENABLE_PAID_ANALYSIS"):
                return self._preview(limit=5)
        env["ENABLE_PAID_ANALYSIS"] = paid_value
        with mock.patch.dict(os.environ, env):
            return self._preview(limit=5)

    def test_absent_empty_and_false_each_read_as_disabled(self):
        for paid_value in (None, "", "false"):
            with self.subTest(paid=repr(paid_value)):
                body = self._preview_with_paid(paid_value)
                item = body["items"][0]
                self.assertTrue(item["requires_llm"])
                self.assertFalse(body["paid_analysis_enabled"])
                self.assertEqual(
                    item["execution_blockers"],
                    ["paid_analysis_disabled", "confirm_paid_required"],
                )
                self._reconcile(body)

    def test_true_reads_as_enabled(self):
        body = self._preview_with_paid("true")
        self.assertTrue(body["paid_analysis_enabled"])
        self.assertEqual(body["items"][0]["execution_blockers"],
                         ["confirm_paid_required"])

    def test_paid_endpoint_refuses_before_provider_work_when_disabled(self):
        self._seed_news_cache(_FRESH_HEADLINE)
        with mock.patch.dict(os.environ, {
            "BACKFILL_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "test-key-preview",
            "ENABLE_PAID_ANALYSIS": "false",
        }), self._sealed():
            r = self.client.post(
                "/movers/backfill-candidate",
                params={"headline": _FRESH_HEADLINE, "confirm_paid": "true"},
            )
        self.assertEqual(r.status_code, 403)
        self.assertIn("enable_paid_analysis",
                      (r.json().get("detail", "") or "").lower())


class ConfirmationBlockerTest(_PreviewContractBase):

    def test_preview_names_confirmation_but_needs_none_itself(self):
        self._seed_news_cache(_FRESH_HEADLINE)
        with mock.patch.dict(os.environ, {
            "BACKFILL_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "test-key-preview",
            "ENABLE_PAID_ANALYSIS": "true",
        }):
            body = self._preview(limit=5)  # no confirm_paid param at all
            self.assertIn("confirm_paid_required",
                          body["items"][0]["execution_blockers"])
            with self._sealed():
                r = self.client.post(
                    "/movers/backfill-candidate",
                    params={"headline": _FRESH_HEADLINE},  # unconfirmed
                )
        self.assertEqual(r.status_code, 400)
        self.assertIn("confirm_paid",
                      (r.json().get("detail", "") or "").lower())


class RegistrySkipPathsTest(_PreviewContractBase):

    def test_already_analyzed_rows_report_no_llm_requirement(self):
        self._seed_news_cache(_FRESH_HEADLINE, _SECOND_HEADLINE)
        self._seed_registry_analyzed(_FRESH_HEADLINE)
        with mock.patch.dict(os.environ, {
            "BACKFILL_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "test-key-preview",
            "ENABLE_PAID_ANALYSIS": "true",
        }):
            body = self._preview(limit=5)
        by_headline = {i["headline"]: i for i in body["items"]}
        analyzed = by_headline[_FRESH_HEADLINE]
        fresh = by_headline[_SECOND_HEADLINE]
        self.assertTrue(analyzed["already_analyzed"])
        self.assertEqual(analyzed["skip_reason"], "registry_already_analyzed")
        self.assertFalse(analyzed["requires_llm"])
        self.assertFalse(analyzed["would_call_llm"])
        self.assertEqual(analyzed["execution_blockers"], [])
        self.assertTrue(fresh["requires_llm"])
        self._reconcile(body)

    def test_provider_availability_does_not_alter_skip_classification(self):
        """A cached/analyzed row stays a no-LLM row whether or not the
        provider key is present — readiness never rewrites requirement."""
        self._seed_news_cache(_FRESH_HEADLINE)
        self._seed_registry_analyzed(_FRESH_HEADLINE)
        for key in ("test-key-preview", ""):
            with self.subTest(key_present=bool(key)):
                with mock.patch.dict(os.environ, {
                    "BACKFILL_PROVIDER": "anthropic",
                    "ANTHROPIC_API_KEY": key,
                    "ENABLE_PAID_ANALYSIS": "true",
                }):
                    body = self._preview(limit=5)
                item = body["items"][0]
                self.assertFalse(item["requires_llm"])
                self.assertFalse(item["would_call_llm"])
                self.assertTrue(item["already_analyzed"])
                self.assertEqual(item["execution_blockers"], [])


class CounterReconciliationTest(_PreviewContractBase):

    def test_mixed_universe_counts_reconcile_exactly(self):
        third = "Treasury yields surge after hot inflation print"
        self._seed_news_cache(_FRESH_HEADLINE, _SECOND_HEADLINE, third)
        self._seed_registry_analyzed(_SECOND_HEADLINE)
        with mock.patch.dict(os.environ, {
            "BACKFILL_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "",          # provider blocked
            "ENABLE_PAID_ANALYSIS": "false",  # kill-switch blocked
        }):
            body = self._preview(limit=5)
        self.assertEqual(len(body["items"]), 3)
        counts = body["counts"]
        self.assertEqual(counts["requires_llm"], 2)
        self.assertEqual(counts["eligible"], 2)
        self.assertEqual(counts["would_call_llm"], 0)
        self.assertEqual(counts["blocked"], 2)
        self.assertEqual(counts["already_analyzed"], 1)
        for item in body["items"]:
            if item["requires_llm"]:
                self.assertEqual(
                    item["execution_blockers"],
                    ["llm_unavailable", "paid_analysis_disabled",
                     "confirm_paid_required"],
                )
            else:
                self.assertEqual(item["execution_blockers"], [])
        self._reconcile(body)


class NoSpendBoundaryTest(_PreviewContractBase):

    def test_preview_touches_no_seam_and_writes_nothing(self):
        self._seed_news_cache(_FRESH_HEADLINE, _SECOND_HEADLINE)
        sig_before = self._registry_signature()
        with mock.patch.dict(os.environ, {
            "BACKFILL_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "test-key-preview",
            "ENABLE_PAID_ANALYSIS": "true",
        }):
            body = self._preview(limit=5)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(self._registry_signature(), sig_before)


if __name__ == "__main__":
    unittest.main()
