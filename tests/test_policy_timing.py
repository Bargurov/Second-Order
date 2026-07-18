"""Focused tests for per-cluster ``policy_timing`` attachment.

Pins the task contract:

  * Block shape matches the frontend ``PolicyTiming`` interface
    exactly — ``policy_key / announced_date / effective_date /
    review_date / status / source``.
  * ``status`` is always one of the four pinned values.
  * Headlines that map to a tracked policy get the block stamped.
  * Headlines that don't map are left byte-stable (no new key).
  * Status derivation is deterministic off ``today``.
  * /news response surfaces the block on matching clusters.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from policy_timing import (  # noqa: E402
    TIMING_STATUSES,
    attach_policy_timing_blocks,
    match_headline_to_policy,
)


_REQUIRED_KEYS = {
    "policy_key", "announced_date", "effective_date",
    "review_date", "status", "source",
}


# ---------------------------------------------------------------------------
# Shape + vocabulary contract
# ---------------------------------------------------------------------------

class TestBlockShape(unittest.TestCase):
    def test_allowed_status_set_is_exactly_four(self) -> None:
        self.assertEqual(
            set(TIMING_STATUSES),
            {"announced", "effective", "under_review", "expired"},
        )

    def test_match_returns_all_required_keys(self) -> None:
        block = match_headline_to_policy(
            "FOMC delivers rate decision",
            today=date(2026, 5, 6),  # day before effective
        )
        self.assertIsNotNone(block)
        assert block is not None
        self.assertEqual(set(block.keys()), _REQUIRED_KEYS)
        self.assertIn(block["status"], TIMING_STATUSES)


# ---------------------------------------------------------------------------
# Status derivation — pinned dates chosen off the registry
# ---------------------------------------------------------------------------

class TestStatusDerivation(unittest.TestCase):
    """Uses the ECB rate decision entry:
         announced 2026-03-06, effective 2026-04-17, review 2026-06-05."""

    _HEADLINE = "ECB governing council rate decision due"

    def test_announced_before_effective_date(self) -> None:
        block = match_headline_to_policy(self._HEADLINE, today=date(2026, 3, 10))
        assert block is not None
        self.assertEqual(block["status"], "announced")

    def test_effective_after_in_force_review_far_off(self) -> None:
        # After effective (Apr 17) but well before review (Jun 5 − 14d = May 22).
        block = match_headline_to_policy(self._HEADLINE, today=date(2026, 4, 30))
        assert block is not None
        self.assertEqual(block["status"], "effective")

    def test_under_review_when_review_imminent(self) -> None:
        # Within _REVISIT_WARN_DAYS (14) of review_date.
        block = match_headline_to_policy(self._HEADLINE, today=date(2026, 5, 25))
        assert block is not None
        self.assertEqual(block["status"], "under_review")

    def test_expired_when_review_long_past(self) -> None:
        # More than _PAST_GRACE_DAYS (30) after the 2026-06-05 review.
        block = match_headline_to_policy(self._HEADLINE, today=date(2026, 8, 1))
        assert block is not None
        self.assertEqual(block["status"], "expired")


# ---------------------------------------------------------------------------
# Matching behaviour
# ---------------------------------------------------------------------------

class TestHeadlineMatching(unittest.TestCase):
    def test_unrelated_headline_returns_none(self) -> None:
        self.assertIsNone(match_headline_to_policy(
            "Tech stocks rally on earnings beats",
            today=date(2026, 4, 20),
        ))

    def test_empty_headline_returns_none(self) -> None:
        self.assertIsNone(match_headline_to_policy("", today=date(2026, 4, 20)))

    def test_match_is_case_insensitive(self) -> None:
        a = match_headline_to_policy("FOMC decision", today=date(2026, 5, 1))
        b = match_headline_to_policy("fomc decision", today=date(2026, 5, 1))
        self.assertEqual(a, b)

    def test_tariff_keyword_hits_correct_policy(self) -> None:
        block = match_headline_to_policy(
            "US reciprocal tariffs to take effect",
            today=date(2026, 4, 3),
        )
        assert block is not None
        self.assertEqual(block["policy_key"], "us_reciprocal_tariffs_baseline_2026")
        self.assertEqual(block["source"], "USTR")

    def test_sanction_keyword_hits_sanction_policy(self) -> None:
        block = match_headline_to_policy(
            "OFAC rolls out new Russia sanctions package",
            today=date(2026, 2, 1),
        )
        assert block is not None
        self.assertEqual(block["policy_key"], "ofac_russia_energy_sanctions_2026")
        self.assertEqual(block["source"], "OFAC")


# ---------------------------------------------------------------------------
# attach_policy_timing_blocks — per-cluster attachment
# ---------------------------------------------------------------------------

class TestAttachPolicyTimingBlocks(unittest.TestCase):
    def _today(self) -> date:
        # Fix today inside the ECB effective-but-review-far window.
        return date(2026, 4, 30)

    def test_matching_cluster_gets_block(self) -> None:
        clusters = [
            {"headline": "ECB rate decision: council holds rates", "sources": []},
        ]
        out = attach_policy_timing_blocks(clusters, today=self._today())
        self.assertIn("policy_timing", out[0])
        self.assertEqual(out[0]["policy_timing"]["policy_key"],
                         "ecb_rate_decision_2026_04")
        self.assertEqual(out[0]["policy_timing"]["status"], "effective")

    def test_non_matching_cluster_is_left_byte_stable(self) -> None:
        """Unmapped cluster must carry no ``policy_timing`` key so
        downstream consumers that don't read the block see the
        NewsCluster shape unchanged."""
        inp = {"headline": "Oil prices slip on inventory build", "sources": []}
        out = attach_policy_timing_blocks([inp], today=self._today())
        self.assertNotIn("policy_timing", out[0])
        # Every original key survives, nothing extra beyond what we had.
        self.assertEqual(set(out[0].keys()), set(inp.keys()))

    def test_inputs_are_not_mutated(self) -> None:
        inp = {"headline": "FOMC delivers rate decision", "sources": []}
        before_keys = set(inp.keys())
        _ = attach_policy_timing_blocks([inp], today=self._today())
        self.assertEqual(set(inp.keys()), before_keys)
        self.assertNotIn("policy_timing", inp)

    def test_pre_existing_block_is_not_overwritten(self) -> None:
        """A cluster that already carries a ``policy_timing`` on
        re-attachment (retry / double-wrap path) keeps its original
        block — first match wins."""
        existing = {
            "policy_key":     "sentinel",
            "announced_date": "2000-01-01",
            "effective_date": "2000-01-02",
            "review_date":    "2000-12-31",
            "status":         "effective",
            "source":         "SENTINEL",
        }
        clusters = [{
            "headline": "ECB rate decision: council holds rates",
            "sources": [],
            "policy_timing": existing,
        }]
        out = attach_policy_timing_blocks(clusters, today=self._today())
        self.assertEqual(out[0]["policy_timing"], existing)

    def test_none_and_malformed_pass_through(self) -> None:
        # Non-dict entries and None input must not crash.
        self.assertEqual(attach_policy_timing_blocks(None), [])
        out = attach_policy_timing_blocks(
            [{"headline": "FOMC decision", "sources": []}, "stray", None],
            today=self._today(),
        )
        self.assertEqual(len(out), 3)
        self.assertIn("policy_timing", out[0])
        self.assertEqual(out[1], "stray")
        self.assertIsNone(out[2])


# ---------------------------------------------------------------------------
# /news HTTP surface — matching clusters surface the block
# ---------------------------------------------------------------------------

class TestNewsRouteSurfacesPolicyTiming(unittest.TestCase):
    """End-to-end: /news stamps clusters whose headline maps to a
    tracked policy, and leaves unmatched clusters shaped exactly as
    they were before this task landed."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        import api as _api
        self.client = TestClient(_api.app)
        self._api = _api

    def _fake_news_payload(self) -> dict:
        return {
            "clusters": [
                {"headline": "FOMC delivers rate decision — holds steady",
                 "sources": [{"name": "Reuters"}], "source_count": 5},
                {"headline": "Oil prices slip on inventory build",
                 "sources": [{"name": "Bloomberg"}], "source_count": 3},
            ],
            "total_headlines": 2,
            "feed_status": [],
            "refresh_meta": {
                "status": "ok", "known": 0, "new": 0, "merged": 0,
                "created": 0, "reused": 2, "source": "stored",
                "freshness": "fresh", "last_successful_refresh": None,
                "ok_feeds": 1, "fail_feeds": 0,
            },
        }

    def test_matching_cluster_surfaces_policy_timing(self) -> None:
        # The /news route reads via read_news_cache_state (cache-only); inject
        # the fake payload at that seam as an available local cache.
        with mock.patch.object(
            self._api, "read_news_cache_state",
            return_value=self._api.NewsCacheState(
                "available", self._fake_news_payload(), "persisted", None, False),
        ):
            r = self.client.get("/news?limit=10")
        self.assertEqual(r.status_code, 200)
        clusters = r.json()["clusters"]
        fomc = next(c for c in clusters if "FOMC" in c["headline"])
        oil  = next(c for c in clusters if "Oil"  in c["headline"])

        self.assertIn("policy_timing", fomc)
        block = fomc["policy_timing"]
        self.assertEqual(set(block.keys()), _REQUIRED_KEYS)
        self.assertEqual(block["policy_key"], "fomc_rate_decision_2026_05")
        self.assertEqual(block["source"], "Federal Reserve")
        self.assertIn(block["status"], TIMING_STATUSES)

        # Unmapped cluster must not gain a policy_timing key — the
        # NewsCluster shape stays stable for consumers that ignore it.
        self.assertNotIn("policy_timing", oil)


if __name__ == "__main__":
    unittest.main()
