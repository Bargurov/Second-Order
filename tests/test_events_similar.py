"""tests/test_events_similar.py

Contract tests for ``GET /events/{event_id}/similar`` — the zero-cost
similar-event retrieval surface.

Invariants:
  1) Returns up to ``limit`` archived events (default 5), each carrying
     ``event_id``, ``headline``, ``timestamp``, ``score``,
     ``shared_terms``, ``shared_tickers``, ``stage``, ``persistence``.
  2) Higher headline / mechanism / ticker overlap → higher score.
  3) Shared tickers reinforce a real link; calendar / boilerplate
     headlines are filtered out the same way ``find_related_events``
     does.
  4) Items are sorted by ``score`` descending, then by ``event_id``
     descending (newest tiebreak).
  5) Missing target ``event_id`` → HTTP 404 (not 200 with []).
  6) The endpoint is pure read: no LLM, no provider call, no DB write.
     Tested by checking event row counts before/after.
  7) ``/events/{id}`` detail response is unchanged (additive endpoint
     only).

No LLM, no market_check — events are seeded directly into a temp DB.
"""

from __future__ import annotations

import os
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


def _tmp_db() -> str:
    return os.path.join(
        tempfile.gettempdir(), f"test_events_similar_{uuid.uuid4().hex}.db",
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


def _ticker(symbol: str) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "symbol":        symbol,
        "role":          "beneficiary",
        "return_5d":     2.0,
        "return_20d":    3.0,
        "direction_tag": "supports ↑",
        "spark":         [],
        "anchor_date":   today,
    }


def _seed(
    *,
    headline: str,
    mechanism_summary: str = "Mechanism summary text.",
    stage: str = "realized",
    persistence: str = "structural",
    tickers: list[str] | None = None,
    days_old: int = 1,
) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
    db.save_event({
        "headline":          headline,
        "stage":             stage,
        "persistence":       persistence,
        "event_date":        today,
        "timestamp":         ts,
        "what_changed":      "Real change description.",
        "mechanism_summary": mechanism_summary,
        "transmission_chain": ["a", "b"],
        "if_persists":       {"thesis": "stub"},
        "confidence":        "medium",
        "market_tickers": [
            _ticker(s) for s in (tickers or [])
        ],
    })
    return db.load_recent_events(1)[0]["id"]


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

    def _row_count(self) -> int:
        import sqlite3
        with sqlite3.connect(db.DB_FILE) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])


# --------------------------------------------------------------------------
# 1) Response shape — every documented per-item field is present.
# --------------------------------------------------------------------------

class TestResponseShape(_Base):

    def test_each_item_carries_required_keys(self) -> None:
        target = _seed(
            headline="OPEC cuts oil output by 500k bpd",
            mechanism_summary="Output cut tightens crude supply.",
            tickers=["XOM", "CVX"],
        )
        _seed(
            headline="OPEC reduces crude output further",
            mechanism_summary="Crude supply tightens further.",
            tickers=["XOM", "BP"],
        )

        resp = client.get(f"/events/{target}/similar")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, list)
        self.assertGreaterEqual(len(body), 1)
        for required in (
            "event_id", "headline", "timestamp", "score",
            "shared_terms", "shared_tickers", "stage", "persistence",
        ):
            self.assertIn(required, body[0], f"missing field: {required}")
        self.assertIsInstance(body[0]["shared_terms"], list)
        self.assertIsInstance(body[0]["shared_tickers"], list)
        self.assertGreater(body[0]["score"], 0.0)

    def test_default_limit_is_five(self) -> None:
        target = _seed(
            headline="Fed cuts rates by 25bp",
            mechanism_summary="Rate cut eases policy stance.",
            tickers=["TLT"],
        )
        for i in range(8):
            _seed(
                headline=f"Fed cuts rates further variant {i}",
                mechanism_summary="Rate cut eases policy stance.",
                tickers=["TLT"],
            )
        body = client.get(f"/events/{target}/similar").json()
        self.assertLessEqual(len(body), 5)

    def test_explicit_limit_cap_honored(self) -> None:
        target = _seed(
            headline="Fed cuts rates by 25bp",
            mechanism_summary="Rate cut eases policy stance.",
            tickers=["TLT"],
        )
        for i in range(8):
            _seed(
                headline=f"Fed cuts rates further variant {i}",
                mechanism_summary="Rate cut eases policy stance.",
                tickers=["TLT"],
            )
        body = client.get(f"/events/{target}/similar?limit=3").json()
        self.assertEqual(len(body), 3)


# --------------------------------------------------------------------------
# 2) Scoring — overlap drives ranking.
# --------------------------------------------------------------------------

class TestScoringRanking(_Base):

    def test_higher_headline_overlap_outranks_weaker_match(self) -> None:
        target = _seed(
            headline="OPEC cuts oil output by 500k bpd",
            mechanism_summary="Output cut tightens crude supply.",
            tickers=["XOM", "CVX"],
        )
        strong = _seed(
            headline="OPEC reduces oil output by 300k bpd",
            mechanism_summary="Output cut tightens crude supply further.",
            tickers=["XOM", "CVX"],
        )
        weak = _seed(
            headline="ECB statement on monetary policy",
            mechanism_summary="Policy stance reaffirmed.",
            tickers=[],
        )
        body = client.get(f"/events/{target}/similar").json()
        # Strong match must rank above (or replace) weak match.
        ids = [it["event_id"] for it in body]
        self.assertIn(strong, ids)
        if weak in ids:
            self.assertLess(ids.index(strong), ids.index(weak))

    def test_shared_tickers_reflected_in_per_item_field(self) -> None:
        target = _seed(
            headline="Fed cuts rates",
            mechanism_summary="Rate cut eases policy stance.",
            tickers=["TLT", "IEF", "SHY"],
        )
        match = _seed(
            headline="Fed lowers rates further",
            mechanism_summary="Rate cut eases policy stance further.",
            tickers=["TLT", "IEF"],
        )
        body = client.get(f"/events/{target}/similar").json()
        match_row = next(it for it in body if it["event_id"] == match)
        self.assertEqual(
            sorted(match_row["shared_tickers"]),
            sorted(["IEF", "TLT"]),
        )

    def test_items_sorted_by_score_desc_then_id_desc(self) -> None:
        target = _seed(
            headline="Fed cuts rates by 25bp",
            mechanism_summary="Rate cut eases policy stance.",
            tickers=["TLT"],
        )
        for i in range(3):
            _seed(
                headline=f"Fed cuts rates variant {i}",
                mechanism_summary="Rate cut eases policy stance.",
                tickers=["TLT"],
            )
        body = client.get(f"/events/{target}/similar").json()
        scores = [it["score"] for it in body]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # Tiebreak inside equal-score groups → descending event_id.
        for a, b in zip(body, body[1:]):
            if a["score"] == b["score"]:
                self.assertGreater(a["event_id"], b["event_id"])

    def test_target_event_excluded_from_results(self) -> None:
        target = _seed(
            headline="Fed cuts rates by 25bp",
            mechanism_summary="Rate cut eases policy stance.",
            tickers=["TLT"],
        )
        _seed(
            headline="Fed cuts rates further",
            mechanism_summary="Rate cut eases policy stance further.",
            tickers=["TLT"],
        )
        body = client.get(f"/events/{target}/similar").json()
        self.assertNotIn(target, [it["event_id"] for it in body])


# --------------------------------------------------------------------------
# 3) Empty / missing cases.
# --------------------------------------------------------------------------

class TestEmptyAndMissing(_Base):

    def test_missing_target_returns_404(self) -> None:
        resp = client.get("/events/9999/similar")
        self.assertEqual(resp.status_code, 404)

    def test_no_other_events_returns_empty_list(self) -> None:
        target = _seed(
            headline="Lone event",
            mechanism_summary="Lone event mechanism.",
            tickers=["XOM"],
        )
        body = client.get(f"/events/{target}/similar").json()
        self.assertEqual(body, [])

    def test_unrelated_events_score_zero_and_drop_off(self) -> None:
        target = _seed(
            headline="Aluminum smelter capacity",
            mechanism_summary="Aluminum smelter capacity changes.",
            tickers=["AA"],
        )
        # Unrelated row — different domain, no shared tokens / tickers,
        # different stage + persistence so even the tiebreak weights
        # contribute nothing.
        _seed(
            headline="Cocoa harvest forecast",
            mechanism_summary="Cocoa harvest forecast revision.",
            tickers=["CC"],
            stage="anticipated",
            persistence="cyclical",
        )
        body = client.get(f"/events/{target}/similar").json()
        self.assertEqual(body, [])


# --------------------------------------------------------------------------
# 4) Read-only invariant — no DB writes from the similar endpoint.
# --------------------------------------------------------------------------

class TestReadOnly(_Base):

    def test_endpoint_does_not_mutate_event_table(self) -> None:
        target = _seed(
            headline="Fed cuts rates by 25bp",
            mechanism_summary="Rate cut eases policy stance.",
            tickers=["TLT"],
        )
        _seed(
            headline="Fed cuts rates further",
            mechanism_summary="Rate cut eases policy stance further.",
            tickers=["TLT"],
        )
        before = self._row_count()
        # Hit the endpoint several times — no row count change either way.
        for _ in range(3):
            client.get(f"/events/{target}/similar").raise_for_status()
        after = self._row_count()
        self.assertEqual(before, after)


# --------------------------------------------------------------------------
# 5) Detail response unchanged — additive endpoint only.
# --------------------------------------------------------------------------

class TestDetailResponseUnchanged(_Base):

    def test_detail_endpoint_does_not_carry_similar_block(self) -> None:
        target = _seed(
            headline="Fed cuts rates by 25bp",
            mechanism_summary="Rate cut eases policy stance.",
            tickers=["TLT"],
        )
        body = client.get(f"/events/{target}").json()
        # The new surface is a dedicated endpoint; the detail body must
        # not start carrying ``similar`` / ``similar_events`` / etc.
        for forbidden in ("similar", "similar_events"):
            self.assertNotIn(
                forbidden, body,
                f"detail body must not carry '{forbidden}' "
                "(similar surface is a dedicated endpoint)",
            )


if __name__ == "__main__":
    unittest.main()
