"""tests/test_events_archive_detail_consistency.py

Smoke tests pinning the listing ↔ detail consistency contract on
``/events`` / ``/events/{id}``.

Two contracts under test:

  1) **Listing-vs-detail invariant** — a row hidden from the archive
     listing by any of the documented filters (default mock/demo/
     degraded suppression, ``quality=...``, expired-low-impact expiry)
     stays accessible via ``GET /events/{id}``.  The product spec is
     "filter the listing, never the row" — review by id must keep
     working regardless of how strictly the listing is narrowed.

  2) **Detail shape integrity** — ``GET /events/{id}`` returns the full
     canonical key-set for every operational bucket (degraded /
     pending / no_tickers / market_checked / clean).  A row with a
     thin or empty payload must not collapse into a half-decoded
     shape that the UI can't render against.

Pagination totals are also re-asserted under combined filters as a
smoke against drift between filter pre-pass and slice math.

No LLM, market_check, or yfinance — events are seeded directly into a
temp DB.
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

# Keys ``GET /events/{id}`` is supposed to surface for every saved row,
# including thin / pending / degraded ones.  Each entry maps the key to
# the JSON type the consumer should bind against — the smoke check
# asserts both that the key exists and that it's the right shape.
_CANONICAL_DETAIL_KEYS: dict[str, type | tuple[type, ...]] = {
    "id":                            int,
    "headline":                      str,
    "what_changed":                  str,
    "mechanism_summary":             str,
    "market_tickers":                list,
    "proof_status":                  dict,
    "falsifier_status":              dict,
    "macro_release_context":         dict,
    "policy_timing_context":         dict,
    "country_vulnerability_context": dict,
    "mover_context":                 dict,
    "mechanism_family":              str,
    "thesis_state":                  str,
    "thesis_state_reason":           str,
    "validation_rationale":          str,
}


def _tmp_db() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"test_events_consistency_{uuid.uuid4().hex}.db",
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
        "symbol":        symbol,
        "role":          "beneficiary",
        "return_5d":     4.0,
        "return_20d":    5.0,
        "direction_tag": "supports ↑",
        "spark":         [0.1, 0.2, 0.3],
        "anchor_date":   today,
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
        "headline":           headline,
        "stage":              "realized",
        "persistence":        "structural",
        "event_date":         today,
        "timestamp":          ts,
        "what_changed":       what_changed,
        "mechanism_summary":  mechanism_summary,
        "model":              model,
        "confidence":         confidence,
        "transmission_chain": transmission_chain or ["a", "b"],
        "if_persists":        if_persists or {"thesis": "stub"},
        "market_tickers":     [_ticker()] if tickers is None else tickers,
    })
    return db.load_recent_events(1)[0]["id"]


def _clear_market_check_stamp(event_id: int) -> None:
    """Mark a row as never-market-checked.  ``db.save_event`` always
    stamps ``last_market_check_at`` (a saved row is, by construction,
    market-checked); the ``pending`` bucket is the inverse, so we have
    to clear the stamp directly."""
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

    # Per-bucket seeds — kept here so the smoke is self-contained.
    def _seed_clean(self, headline: str = "Clean Fed decision") -> int:
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

    def _seed_market_checked(
        self, headline: str = "Market-checked thin",
    ) -> int:
        """Has tickers but otherwise sparse → low_information=True."""
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
        return _seed(headline=headline, tickers=[])

    def _seed_pending(self, headline: str = "Pending row") -> int:
        eid = _seed(headline=headline, tickers=[])
        _clear_market_check_stamp(eid)
        return eid

    def _seed_degraded(
        self, headline: str = "Degraded row", with_tickers: bool = False,
    ) -> int:
        return _seed(
            headline=headline,
            what_changed=_DEGRADED_PREFIX,
            tickers=[_ticker("XLE")] if with_tickers else [],
        )

    def _seed_mock(self, headline: str = "Mock row") -> int:
        return _seed(headline=headline, what_changed="[mock: overloaded]")

    def _seed_demo(self, headline: str = "[DEMO] Showcase") -> int:
        return _seed(headline=headline)

    def _assert_canonical_detail_shape(
        self, body: dict, *, where: str,
    ) -> None:
        for key, expected_type in _CANONICAL_DETAIL_KEYS.items():
            self.assertIn(key, body, f"{where}: missing key {key!r}")
            self.assertIsInstance(
                body[key], expected_type,
                f"{where}: key {key!r} should be {expected_type}, "
                f"got {type(body[key]).__name__}",
            )


# --------------------------------------------------------------------------
# 1) Detail shape per bucket — every operational bucket must serve a
#    well-formed canonical detail body.
# --------------------------------------------------------------------------

class TestDetailShapePerBucket(_Base):

    def test_clean_row_detail_has_canonical_keys(self) -> None:
        eid = self._seed_clean()
        resp = client.get(f"/events/{eid}")
        self.assertEqual(resp.status_code, 200)
        self._assert_canonical_detail_shape(
            resp.json(), where="clean",
        )

    def test_market_checked_low_info_row_detail_has_canonical_keys(self) -> None:
        eid = self._seed_market_checked()
        resp = client.get(f"/events/{eid}")
        self.assertEqual(resp.status_code, 200)
        self._assert_canonical_detail_shape(
            resp.json(), where="market_checked",
        )

    def test_no_tickers_row_detail_has_canonical_keys(self) -> None:
        eid = self._seed_no_tickers()
        resp = client.get(f"/events/{eid}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self._assert_canonical_detail_shape(body, where="no_tickers")
        # Empty market_tickers must surface as an empty list, not None.
        self.assertEqual(body["market_tickers"], [])

    def test_pending_row_detail_has_canonical_keys(self) -> None:
        eid = self._seed_pending()
        resp = client.get(f"/events/{eid}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self._assert_canonical_detail_shape(body, where="pending")
        self.assertEqual(body["market_tickers"], [])

    def test_degraded_row_detail_has_canonical_keys(self) -> None:
        eid = self._seed_degraded()
        resp = client.get(f"/events/{eid}")
        self.assertEqual(resp.status_code, 200)
        self._assert_canonical_detail_shape(
            resp.json(), where="degraded",
        )

    def test_proof_falsifier_blocks_have_items_list_for_thin_rows(self) -> None:
        """Always-shaped contract: ``proof_status.items`` and
        ``falsifier_status.items`` must be lists (possibly empty) even
        on a degraded row that stored ``{}`` at the DB layer."""
        eid = self._seed_degraded()
        body = client.get(f"/events/{eid}").json()
        self.assertIsInstance(body["proof_status"].get("items"), list)
        self.assertIsInstance(body["falsifier_status"].get("items"), list)


# --------------------------------------------------------------------------
# 2) Listing ↔ detail consistency — rows hidden by each filter mode are
#    still served by id.  The detail handler is supposed to bypass every
#    listing-side filter; this pins that.
# --------------------------------------------------------------------------

class TestListingDetailConsistencyDefaultFilters(_Base):
    """Default listing hides mock + demo + degraded + (registry-aware)
    expired-low-impact rows.  Each must still open by id."""

    def test_mock_row_hidden_default_visible_by_id(self) -> None:
        mock_id = self._seed_mock()
        listing = client.get("/events").json()
        self.assertNotIn(
            mock_id, [e["id"] for e in listing["items"]],
        )
        resp = client.get(f"/events/{mock_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], mock_id)

    def test_demo_row_hidden_default_visible_by_id(self) -> None:
        demo_id = self._seed_demo()
        listing = client.get("/events").json()
        self.assertNotIn(
            demo_id, [e["id"] for e in listing["items"]],
        )
        resp = client.get(f"/events/{demo_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], demo_id)

    def test_degraded_row_hidden_default_visible_by_id(self) -> None:
        deg_id = self._seed_degraded()
        listing = client.get("/events").json()
        self.assertNotIn(
            deg_id, [e["id"] for e in listing["items"]],
        )
        resp = client.get(f"/events/{deg_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], deg_id)


class TestListingDetailConsistencyExpiredLowImpact(_Base):
    """Analyzed-low-impact rows past the registry TTL are hidden from
    the listing — the detail endpoint MUST keep serving them so review
    by id stays usable after the listing has stopped surfacing them."""

    def setUp(self) -> None:
        super().setUp()
        self._orig_ttl = os.environ.get(
            "HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS",
        )
        os.environ["HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS"] = "1"

    def tearDown(self) -> None:
        if self._orig_ttl is None:
            os.environ.pop("HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS", None)
        else:
            os.environ["HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS"] = self._orig_ttl
        super().tearDown()

    def _seed_expired_low_impact(self) -> int:
        from news_sources import _dedup_key
        headline = "Old low-impact print"
        eid = _seed(headline=headline, days_old=5)
        analyzed_at = (
            datetime.now() - timedelta(days=5)
        ).isoformat(timespec="seconds")
        title_key = _dedup_key(headline)
        db.upsert_headline_registry_seen(
            [("Reuters", title_key, 1)], analyzed_at,
        )
        db.update_registry_state(
            title_key=title_key,
            new_state="analyzed",
            event_id=eid,
            impact_level="low",
            analyzed_at=analyzed_at,
        )
        return eid

    def test_expired_low_impact_hidden_default_visible_by_id(self) -> None:
        expired_id = self._seed_expired_low_impact()
        listing = client.get("/events").json()
        self.assertNotIn(
            expired_id, [e["id"] for e in listing["items"]],
        )
        resp = client.get(f"/events/{expired_id}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["id"], expired_id)
        # Detail body still carries the canonical key-set.
        self._assert_canonical_detail_shape(body, where="expired_low_impact")


class TestListingDetailConsistencyQualityFilter(_Base):
    """Each ``quality=...`` value narrows the listing to one bucket;
    rows in OTHER buckets are absent from the listing but must still
    open by id."""

    def test_quality_clean_excludes_other_buckets_but_id_serves_them(
        self,
    ) -> None:
        clean_id    = self._seed_clean()
        market_id   = self._seed_market_checked()
        notx_id     = self._seed_no_tickers()
        pending_id  = self._seed_pending()

        listing = client.get("/events?quality=clean").json()
        listed_ids = {e["id"] for e in listing["items"]}
        self.assertEqual(listed_ids, {clean_id})
        self.assertEqual(listing["total"], 1)

        # Each excluded row still resolves by id.
        for excluded in (market_id, notx_id, pending_id):
            resp = client.get(f"/events/{excluded}")
            self.assertEqual(
                resp.status_code, 200,
                f"id={excluded} should resolve by detail despite "
                "exclusion from quality=clean listing",
            )
            self.assertEqual(resp.json()["id"], excluded)

    def test_quality_pending_excludes_clean_but_id_serves_clean(
        self,
    ) -> None:
        clean_id   = self._seed_clean()
        pending_id = self._seed_pending()

        listing = client.get("/events?quality=pending").json()
        listed_ids = {e["id"] for e in listing["items"]}
        self.assertEqual(listed_ids, {pending_id})

        resp = client.get(f"/events/{clean_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], clean_id)

    def test_quality_degraded_listing_does_not_break_other_id_lookups(
        self,
    ) -> None:
        deg_id   = self._seed_degraded()
        clean_id = self._seed_clean()

        listing = client.get("/events?quality=degraded").json()
        listed_ids = {e["id"] for e in listing["items"]}
        self.assertEqual(listed_ids, {deg_id})

        # Clean row excluded from this slice — still 200 by id with the
        # canonical shape.
        resp = client.get(f"/events/{clean_id}")
        self.assertEqual(resp.status_code, 200)
        self._assert_canonical_detail_shape(
            resp.json(), where="clean-via-id-during-degraded-filter",
        )


# --------------------------------------------------------------------------
# 3) Pagination totals — combined filters must still produce a
#    consistent ``total`` / ``items`` slice.
# --------------------------------------------------------------------------

class TestPaginationTotalsAcrossFilters(_Base):

    def _seed_mixed_archive(self) -> dict[str, list[int]]:
        """Seed a mixed archive covering every bucket the listing
        cares about.  Returns a per-bucket id index for assertions."""
        return {
            "clean":    [self._seed_clean(headline=f"Clean #{i}")
                         for i in range(4)],
            "market":   [self._seed_market_checked(
                            headline=f"Mkt thin #{i}",
                         ) for i in range(2)],
            "no_tx":    [self._seed_no_tickers(headline=f"No tx #{i}")
                         for i in range(2)],
            "pending":  [self._seed_pending(headline=f"Pending #{i}")
                         for i in range(1)],
            "degraded": [self._seed_degraded(headline=f"Degraded #{i}")
                         for i in range(1)],
            "mock":     [self._seed_mock(headline=f"Mock #{i}")
                         for i in range(1)],
            "demo":     [self._seed_demo(headline=f"[DEMO] #{i}")
                         for i in range(1)],
        }

    def test_default_listing_total_excludes_polluted_rows(self) -> None:
        seeded = self._seed_mixed_archive()
        # Polluted = degraded + mock + demo (3 rows).  Surviving rows:
        # 4 clean + 2 mkt + 2 no_tx + 1 pending = 9.
        body = client.get("/events?limit=100").json()
        listed = {e["id"] for e in body["items"]}
        expected = set(
            seeded["clean"] + seeded["market"]
            + seeded["no_tx"] + seeded["pending"]
        )
        self.assertEqual(listed, expected)
        self.assertEqual(body["total"], 9)

    def test_quality_clean_total_matches_filtered_count(self) -> None:
        seeded = self._seed_mixed_archive()
        body = client.get("/events?quality=clean&limit=2&offset=0").json()
        self.assertEqual(body["total"], 4)
        self.assertEqual(len(body["items"]), 2)
        body2 = client.get("/events?quality=clean&limit=2&offset=2").json()
        self.assertEqual(body2["total"], 4)
        self.assertEqual(len(body2["items"]), 2)
        # Pagination covers the full clean slice, no duplicates.
        all_ids = {e["id"] for e in body["items"]} | {
            e["id"] for e in body2["items"]
        }
        self.assertEqual(all_ids, set(seeded["clean"]))

    def test_include_mock_total_matches_archive_size(self) -> None:
        seeded = self._seed_mixed_archive()
        all_seeded = {
            i for ids in seeded.values() for i in ids
        }
        body = client.get("/events?include_mock=true&limit=100").json()
        listed = {e["id"] for e in body["items"]}
        self.assertEqual(listed, all_seeded)
        self.assertEqual(body["total"], len(all_seeded))

    def test_include_mock_with_quality_degraded_narrows_to_degraded(
        self,
    ) -> None:
        seeded = self._seed_mixed_archive()
        body = client.get(
            "/events?include_mock=true&quality=degraded&limit=100",
        ).json()
        listed = {e["id"] for e in body["items"]}
        self.assertEqual(listed, set(seeded["degraded"]))
        self.assertEqual(body["total"], len(seeded["degraded"]))


# ---------------------------------------------------------------------------
# Similar-event retrieval — ``GET /events/{id}/related``
# ---------------------------------------------------------------------------
# Tiny fixture set: one target plus two siblings that share the target's
# ticker basket + stage, and one unrelated row with a disjoint headline,
# different stage, and a different ticker.  Pins the three contract
# points the operator UI depends on:
#
#   1. Missing event_id → 404 (no spend seam runs).
#   2. Sibling rows that share the target's ticker basket / stage rank
#      above unrelated rows in the response.
#   3. The endpoint is zero-cost — analyze_event, market_check,
#      _persist_event, and the two yfinance entry points are banned via
#      raisers; if any is reached, the test fails loudly.
# ---------------------------------------------------------------------------


class TestRelatedEventsRetrieval(_Base):

    def _seed_unrelated(self) -> int:
        """Seed a row with a disjoint headline, distinct stage, and a
        different ticker so the related ranking has something to
        ignore."""
        today = datetime.now().strftime("%Y-%m-%d")
        ts = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        db.save_event({
            "headline":           "Fed raises interest rates by 25 basis points",
            "stage":              "anticipated",
            "persistence":        "transient",
            "event_date":         today,
            "timestamp":          ts,
            "what_changed":       "Unrelated rate hike",
            "mechanism_summary":  "Different mechanism text long enough to pass.",
            "transmission_chain": ["c", "d"],
            "if_persists":        {"thesis": "rate"},
            "market_tickers":     [{
                "symbol":        "TLT",
                "role":          "beneficiary",
                "return_5d":    -1.0,
                "direction_tag": "supports ↓",
                "anchor_date":   today,
            }],
        })
        return db.load_recent_events(1)[0]["id"]

    def test_missing_event_returns_404(self) -> None:
        from unittest.mock import patch

        # Even the 404 path must be cost-free — bans below would fire if
        # the handler somehow reached a paid helper before the 404.
        with patch("api.analyze_event",
                   side_effect=AssertionError("related must not call analyze_event")), \
             patch("api.market_check",
                   side_effect=AssertionError("related must not call market_check")), \
             patch("yfinance.download",
                   side_effect=AssertionError("related must not call yfinance.download")), \
             patch("yfinance.Ticker",
                   side_effect=AssertionError("related must not call yfinance.Ticker")):
            r = client.get("/events/99999/related")
        self.assertEqual(r.status_code, 404)

    def test_overlapping_ticker_stage_rank_above_unrelated(self) -> None:
        # Target + two siblings sharing the XLE / realized basket +
        # overlapping headline content; one unrelated row with a
        # disjoint headline and a different ticker / stage.
        target = _seed(
            headline="OPEC cuts crude oil output by 500k bpd",
        )
        sibling_a = _seed(
            headline="OPEC extends crude oil output cuts to Q4",
        )
        sibling_b = _seed(
            headline="OPEC further crude oil output reduction announced",
        )
        unrelated = self._seed_unrelated()

        r = client.get(f"/events/{target}/related")
        self.assertEqual(r.status_code, 200, r.text)
        ids = [e["id"] for e in r.json()]

        # Both siblings appear; unrelated does not.
        self.assertIn(sibling_a, ids)
        self.assertIn(sibling_b, ids)
        self.assertNotIn(unrelated, ids)
        # Sibling stage matches the target — the response carries it
        # through so a future ranking change that drops stage still
        # leaves the siblings ahead.
        for ev in r.json():
            if ev["id"] in (sibling_a, sibling_b):
                self.assertEqual(ev["stage"], "realized")

    def test_related_endpoint_is_zero_cost(self) -> None:
        from unittest.mock import patch

        target = _seed(headline="OPEC cuts crude oil output by 500k bpd")
        _seed(headline="OPEC extends crude oil output cuts to Q4")

        with patch("api.analyze_event",
                   side_effect=AssertionError("related must not call analyze_event")), \
             patch("api.market_check",
                   side_effect=AssertionError("related must not call market_check")), \
             patch("api._persist_event",
                   side_effect=AssertionError("related must not call _persist_event")), \
             patch("yfinance.download",
                   side_effect=AssertionError("related must not call yfinance.download")), \
             patch("yfinance.Ticker",
                   side_effect=AssertionError("related must not call yfinance.Ticker")):
            r = client.get(f"/events/{target}/related")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsInstance(r.json(), list)


if __name__ == "__main__":
    unittest.main()
