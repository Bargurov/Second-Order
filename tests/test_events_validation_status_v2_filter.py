"""tests/test_events_validation_status_v2_filter.py

Tests for the ``?validation_status_v2=...`` filter on ``/events``.

Contract pinned here:

  * Param accepts exactly the four status values
    (``validated|contradicted|unresolved|pending``).
  * Filter runs after row decoration so the four-label scorer's
    output drives the cut, not the legacy three-label string.
  * ``total`` reflects the **post-filter** count, not the pre-filter
    universe — pagination is stable across pages of the same query.
  * Legacy ``?validated=...`` filter keeps working unchanged.
  * Both filters compose by AND when supplied together.
  * Invalid value returns 400 (no spend seam runs).
  * Endpoint stays read-only — no DB writes, no provider calls.
"""

from __future__ import annotations

import os
import sqlite3
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
from fastapi.testclient import TestClient

client = TestClient(api.app)


# ---------------------------------------------------------------------------
# Fixture helpers — distinct headlines so dedup never collapses a seed
# ---------------------------------------------------------------------------


def _tmp_db() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"test_events_vs_v2_filter_{uuid.uuid4().hex}.db",
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


def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _ticker(
    symbol: str = "XLE",
    *,
    direction_tag: str | None = None,
    role: str | None = "beneficiary",
    return_5d: float | None = 4.0,
) -> dict:
    out: dict = {"symbol": symbol, "anchor_date": _today_iso()}
    if direction_tag is not None:
        out["direction_tag"] = direction_tag
    if role is not None:
        out["role"] = role
    if return_5d is not None:
        out["return_5d"] = return_5d
    return out


def _seed(
    *,
    headline: str,
    tickers: list[dict],
    days_old: int = 1,
    mechanism_summary: str = "Mechanism summary text long enough to pass.",
    what_changed: str = "Real change description",
) -> int:
    today = _today_iso()
    ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
    db.save_event({
        "headline":           headline,
        "stage":              "realized",
        "persistence":        "structural",
        "event_date":         today,
        "timestamp":          ts,
        "what_changed":       what_changed,
        "mechanism_summary":  mechanism_summary,
        "transmission_chain": ["a", "b"],
        "if_persists":        {"thesis": "stub"},
        "market_tickers":     tickers,
        "confidence":         "medium",
    })
    return db.load_recent_events(1)[0]["id"]


def _force_event_date(event_id: int, days_old: int) -> None:
    """Push event_date / timestamp back so the row is past the
    pending window.  Used to seed an unresolved-from-age row without
    waiting wall-clock days."""
    old = (datetime.now() - timedelta(days=days_old)).date().isoformat()
    with sqlite3.connect(db.DB_FILE) as conn:
        conn.execute(
            "UPDATE events SET event_date = ?, timestamp = ? WHERE id = ?",
            (old, old + "T10:00:00", event_id),
        )
        conn.commit()


def _seed_validated(headline: str) -> int:
    """2 supports + 0 contradicts → validated under both legacy + v2."""
    return _seed(
        headline=headline,
        tickers=[
            _ticker("XLE", direction_tag="supports_thesis"),
            _ticker("XOM", direction_tag="supports_thesis"),
        ],
    )


def _seed_contradicted(headline: str) -> int:
    """0 supports + 2 contradicts → contradicted under both."""
    return _seed(
        headline=headline,
        tickers=[
            _ticker("AAPL", direction_tag="contradicts_thesis"),
            _ticker("MSFT", direction_tag="contradicts_thesis"),
        ],
    )


def _seed_pending(headline: str) -> int:
    """No directional tags but role + thesis present, fresh → pending."""
    return _seed(
        headline=headline,
        tickers=[
            _ticker("AMZN", direction_tag=None, role="beneficiary"),
        ],
    )


def _seed_unresolved(headline: str) -> int:
    """No tickers, no thesis classification, fresh → unresolved.

    Empties every field the pending-vs-unresolved discriminator
    inspects so the row falls through to ``unresolved`` rather than
    ``pending``: empty market_tickers, empty mechanism_summary, empty
    what_changed (the ``_has_thesis`` check covers that field too).
    """
    return _seed(
        headline=headline,
        tickers=[],
        mechanism_summary="",
        what_changed="",
    )


def _snapshot_events_table(path: str) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return list(conn.execute("SELECT * FROM events ORDER BY id"))


# ---------------------------------------------------------------------------
# Base — temp DB per test
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Per-status filtering
# ---------------------------------------------------------------------------


class TestPerStatusFilter(_Base):
    def _seed_mixed_archive(self) -> dict[str, list[int]]:
        """Seed two of each status so totals can flex with pagination."""
        return {
            "validated":    [
                _seed_validated("OPEC announces production cut of 500k bpd"),
                _seed_validated("Aramco lifts long-term oil price guidance"),
            ],
            "contradicted": [
                _seed_contradicted("Tech earnings miss expectations broadly"),
                _seed_contradicted("Mega-cap names disappoint on guidance"),
            ],
            "pending":      [
                _seed_pending("ECB holds policy rate steady at 4 percent"),
                _seed_pending("Bank of Japan keeps yield curve control"),
            ],
            "unresolved":   [
                _seed_unresolved("Industry roundup with no specific direction"),
                _seed_unresolved("Generic market commentary headline"),
            ],
        }

    def test_filter_validated_returns_only_validated(self) -> None:
        seeded = self._seed_mixed_archive()
        body = client.get("/events?validation_status_v2=validated&limit=100").json()
        listed = {e["id"] for e in body["items"]}
        self.assertEqual(listed, set(seeded["validated"]))
        self.assertEqual(body["total"], 2)
        for item in body["items"]:
            self.assertEqual(item["validation_status_v2"]["status"], "validated")

    def test_filter_contradicted_returns_only_contradicted(self) -> None:
        seeded = self._seed_mixed_archive()
        body = client.get("/events?validation_status_v2=contradicted&limit=100").json()
        listed = {e["id"] for e in body["items"]}
        self.assertEqual(listed, set(seeded["contradicted"]))
        self.assertEqual(body["total"], 2)
        for item in body["items"]:
            self.assertEqual(item["validation_status_v2"]["status"], "contradicted")

    def test_filter_pending_returns_only_pending(self) -> None:
        seeded = self._seed_mixed_archive()
        body = client.get("/events?validation_status_v2=pending&limit=100").json()
        listed = {e["id"] for e in body["items"]}
        self.assertEqual(listed, set(seeded["pending"]))
        self.assertEqual(body["total"], 2)
        for item in body["items"]:
            self.assertEqual(item["validation_status_v2"]["status"], "pending")

    def test_filter_unresolved_returns_only_unresolved(self) -> None:
        seeded = self._seed_mixed_archive()
        body = client.get("/events?validation_status_v2=unresolved&limit=100").json()
        listed = {e["id"] for e in body["items"]}
        self.assertEqual(listed, set(seeded["unresolved"]))
        self.assertEqual(body["total"], 2)
        for item in body["items"]:
            self.assertEqual(item["validation_status_v2"]["status"], "unresolved")


# ---------------------------------------------------------------------------
# Total reflects post-filter universe + pagination
# ---------------------------------------------------------------------------

# Each of the headlines below is intentionally token-disjoint from the
# others so read-time Jaccard dedup (``_DEDUP_THRESHOLD = 0.65`` in db.py)
# never collapses two of them.  Five validated + two contradicted gives
# enough material for the pagination and post-filter-total tests.
_DISTINCT_VALIDATED_HEADLINES = [
    "OPEC slashes crude output by five hundred thousand barrels daily",
    "Aramco raises long term Brent price guidance for next quarter",
    "Iran exports surge defying United States sanctions enforcement",
    "Strait of Hormuz closure raises spot premium overnight",
    "Nigeria production declines pipeline outage spreads onshore",
]
_DISTINCT_CONTRADICTED_HEADLINES = [
    "Megacap technology earnings miss expectations badly",
    "Cloud growth disappoints across hyperscaler guidance",
]


class TestTotalAndPagination(_Base):
    def test_total_reflects_post_filter_count(self) -> None:
        # 4 validated + 2 contradicted; full archive is 6 rows.  Filtered
        # total must be 4, not 6.
        ids_v = [
            _seed_validated(_DISTINCT_VALIDATED_HEADLINES[i])
            for i in range(4)
        ]
        ids_c = [
            _seed_contradicted(_DISTINCT_CONTRADICTED_HEADLINES[i])
            for i in range(2)
        ]
        body = client.get(
            "/events?validation_status_v2=validated&limit=100",
        ).json()
        self.assertEqual(body["total"], 4)
        self.assertEqual({e["id"] for e in body["items"]}, set(ids_v))
        self.assertNotIn(ids_c[0], {e["id"] for e in body["items"]})

    def test_pagination_slices_filtered_set(self) -> None:
        ids = [
            _seed_validated(_DISTINCT_VALIDATED_HEADLINES[i])
            for i in range(5)
        ]
        # First page of 2.
        body1 = client.get(
            "/events?validation_status_v2=validated&limit=2&offset=0",
        ).json()
        self.assertEqual(body1["total"], 5)
        self.assertEqual(len(body1["items"]), 2)
        # Second page.
        body2 = client.get(
            "/events?validation_status_v2=validated&limit=2&offset=2",
        ).json()
        self.assertEqual(body2["total"], 5)
        self.assertEqual(len(body2["items"]), 2)
        # Third page — only one row left.
        body3 = client.get(
            "/events?validation_status_v2=validated&limit=2&offset=4",
        ).json()
        self.assertEqual(body3["total"], 5)
        self.assertEqual(len(body3["items"]), 1)
        # No row appears on more than one page.
        seen = (
            {e["id"] for e in body1["items"]}
            | {e["id"] for e in body2["items"]}
            | {e["id"] for e in body3["items"]}
        )
        self.assertEqual(seen, set(ids))


# ---------------------------------------------------------------------------
# Legacy filter parity — ``?validated=...`` is preserved exactly
# ---------------------------------------------------------------------------


class TestLegacyValidatedFilterPreserved(_Base):
    def test_legacy_validated_alone_still_filters(self) -> None:
        ids_v = [_seed_validated(f"OPEC distinct event {i}") for i in range(2)]
        _seed_contradicted("Earnings miss far and wide today")
        body = client.get("/events?validated=validated&limit=100").json()
        listed = {e["id"] for e in body["items"]}
        self.assertEqual(listed, set(ids_v))
        self.assertEqual(body["total"], 2)


# ---------------------------------------------------------------------------
# Filters compose by AND
# ---------------------------------------------------------------------------


class TestComposingFilters(_Base):
    def test_legacy_and_v2_filters_intersect(self) -> None:
        # ?validated=validated already matches the validated cohort; AND-ing
        # with ?validation_status_v2=validated must produce the same set.
        ids_v = [
            _seed_validated(_DISTINCT_VALIDATED_HEADLINES[i])
            for i in range(3)
        ]
        body = client.get(
            "/events?validated=validated&validation_status_v2=validated&limit=100",
        ).json()
        self.assertEqual({e["id"] for e in body["items"]}, set(ids_v))
        self.assertEqual(body["total"], 3)

    def test_legacy_and_v2_filters_with_disjoint_intent_yield_empty(self) -> None:
        # Legacy 'validated' but v2 'pending' is impossible — pending in
        # v2 means no directional tags, while legacy 'validated' requires
        # supports majority.  Intersection is empty.
        _seed_validated("OPEC distinct top headline alpha")
        _seed_pending("ECB distinct top headline beta")
        body = client.get(
            "/events?validated=validated&validation_status_v2=pending&limit=100",
        ).json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["total"], 0)

    def test_v2_filter_composes_with_search(self) -> None:
        # Two validated rows; ?search= narrows to one of them.
        ids = [
            _seed_validated("OPEC alpha unique distinct"),
            _seed_validated("OPEC beta unique distinct"),
        ]
        body = client.get(
            "/events?validation_status_v2=validated&search=alpha&limit=100",
        ).json()
        self.assertEqual({e["id"] for e in body["items"]}, {ids[0]})
        self.assertEqual(body["total"], 1)


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------


class TestInvalidParam(_Base):
    def test_invalid_value_returns_422(self) -> None:
        # FastAPI Query(pattern=...) rejects with 422 (validation error).
        # Either 400 or 422 is acceptable as "no spend"; pin 422 since
        # that's FastAPI's default for regex mismatch.
        r = client.get("/events?validation_status_v2=bogus")
        self.assertIn(r.status_code, (400, 422))

    def test_unset_param_does_not_filter(self) -> None:
        _seed_validated("OPEC distinct unique alpha row")
        _seed_pending("ECB distinct unique beta row")
        body = client.get("/events?limit=100").json()
        self.assertEqual(body["total"], 2)


# ---------------------------------------------------------------------------
# Read-only contract
# ---------------------------------------------------------------------------


class TestReadOnlyContract(_Base):
    def test_filter_does_not_write_to_db(self) -> None:
        _seed_validated("OPEC alpha distinct")
        _seed_contradicted("Tech beta distinct earnings")
        before = _snapshot_events_table(self._tmp)
        r = client.get("/events?validation_status_v2=validated&limit=50")
        self.assertEqual(r.status_code, 200)
        after = _snapshot_events_table(self._tmp)
        self.assertEqual(before, after, "filter mutated events table")

    def test_filter_makes_no_provider_calls(self) -> None:
        _seed_validated("OPEC alpha distinct headline here")
        with patch("api.analyze_event",
                   side_effect=AssertionError("filter must not call analyze_event")), \
             patch("api.market_check",
                   side_effect=AssertionError("filter must not call market_check")), \
             patch("yfinance.download",
                   side_effect=AssertionError("filter must not call yfinance.download")), \
             patch("yfinance.Ticker",
                   side_effect=AssertionError("filter must not call yfinance.Ticker")):
            r = client.get("/events?validation_status_v2=validated&limit=10")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertGreater(len(r.json()["items"]), 0)


if __name__ == "__main__":
    unittest.main()
