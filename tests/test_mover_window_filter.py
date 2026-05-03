"""
tests/test_mover_window_filter.py

Contract tests for the ``mover_window`` filter on ``/portfolio`` and
``/events``.

Covers:
  * Composer-level helper ``build_event_window_index`` — inverts
    slice dict to an ``{event_id: [windows]}`` index.
  * Closed window vocabulary (``today`` / ``weekly`` / ``persistent``
    / ``market``) rejected at the route layer for unknown tokens.
  * Default response shape unchanged when ``mover_window`` is absent.
  * Filtered response adds ``mover_window_counts`` facet (archive-
    wide counts) + keeps the wrapped shape.
  * Per-window filtering returns only events active on that surface.
  * Combined-filter behaviour: ``mover_window`` stacks with existing
    ``queue`` / ``thesis_state`` / ``proof_quality`` / ``low_information``
    filters.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from mover_context import MOVER_WINDOW_IDS, build_event_window_index


# ---------------------------------------------------------------------------
# Composer — build_event_window_index
# ---------------------------------------------------------------------------


def _card(event_id: int, window: str, *, use_event_id_key: bool = False) -> dict:
    key = "event_id" if use_event_id_key else "id"
    return {
        key:                 event_id,
        "mover_window":      window,
        "surfaced_reason":   f"Active on {window}.",
        "strongest_move_5d": 2.0,
        "moved_tickers":     [],
    }


class TestBuildEventWindowIndex(unittest.TestCase):
    def test_window_vocab_is_closed_set(self) -> None:
        self.assertEqual(
            set(MOVER_WINDOW_IDS),
            {"today", "weekly", "persistent", "market"},
        )

    def test_single_event_multiple_windows(self) -> None:
        slices = {
            "today":      [_card(1, "today")],
            "market":     [_card(1, "market")],
            "weekly":     [],
            "persistent": [_card(1, "persistent")],
        }
        idx = build_event_window_index(slices)
        self.assertEqual(idx[1], ["today", "market", "persistent"])

    def test_multiple_events_across_windows(self) -> None:
        slices = {
            "today":      [_card(1, "today"), _card(2, "today")],
            "market":     [_card(2, "market")],
            "weekly":     [_card(3, "weekly")],
            "persistent": [],
        }
        idx = build_event_window_index(slices)
        self.assertEqual(idx[1], ["today"])
        self.assertEqual(idx[2], ["today", "market"])
        self.assertEqual(idx[3], ["weekly"])

    def test_tolerates_event_id_key_shape(self) -> None:
        """Raw cards carry ``event_id`` instead of ``id`` — the
        composer normalises both."""
        slices = {
            "today":  [_card(42, "today", use_event_id_key=True)],
            "market": [], "weekly": [], "persistent": [],
        }
        idx = build_event_window_index(slices)
        self.assertEqual(idx[42], ["today"])

    def test_malformed_inputs_safe(self) -> None:
        self.assertEqual(build_event_window_index(None), {})
        self.assertEqual(build_event_window_index({}), {})
        slices = {
            "today":      "not a list",  # type: ignore[dict-item]
            "market":     [None, 42, "oops", _card(1, "market")],  # type: ignore[list-item]
            "weekly":     [{"id": True, "mover_window": "weekly"}],  # bool id
            "persistent": [],
        }
        idx = build_event_window_index(slices)
        self.assertEqual(idx, {1: ["market"]})


# ---------------------------------------------------------------------------
# /portfolio + /events — HTTP surface
# ---------------------------------------------------------------------------


class MoverFilterHTTPBase(unittest.TestCase):
    def setUp(self) -> None:
        import db as _db
        self._db = _db
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"mwf_{uuid.uuid4().hex}.db",
        )
        _db.DB_FILE = self._tmp
        _db._db_ready = False
        _db.init_db()

        from fastapi.testclient import TestClient
        import api as _api_mod
        self.client = TestClient(_api_mod.app)
        self._event_ids: list[int] = []
        self._seed_events()

    def tearDown(self) -> None:
        self._db.DB_FILE = self._orig
        self._db._db_ready = False
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _seed_events(self) -> None:
        """Seed three analyzable events so both routes return data."""
        for i, headline in enumerate([
            "OPEC extends production cuts through Q3",
            "Fed holds rates unchanged in split vote",
            "China tightens export controls on rare earths",
        ]):
            self._db.save_event({
                "headline":          headline,
                "stage":              "realized",
                "persistence":        "medium",
                "mechanism_summary":  f"Mechanism summary with enough length for event {i}.",
                "beneficiaries":      [f"B{i}"],
                "losers":             [f"L{i}"],
                "assets_to_watch":    [f"B{i}", f"L{i}"],
                "confidence":         "medium",
                "market_note":        "",
                "notes":              "",
                "market_tickers": [{
                    "symbol": "USO", "role": "beneficiary",
                    "return_5d": 3.0,
                    "direction_tag": "supports thesis",
                }],
                "mechanism_family":   "commodity_squeeze",
            })
        for row in self._db.load_recent_events(limit=10):
            self._event_ids.append(row["id"])
        # Reverse so index 0 maps to the first-seeded event (oldest).
        self._event_ids.sort()

    def _slices(self, mapping: dict[int, list[str]]) -> dict[str, list[dict]]:
        """Convert ``{event_id: [windows]}`` into the four-slice shape
        the route loader would return."""
        slices: dict[str, list[dict]] = {
            w: [] for w in MOVER_WINDOW_IDS
        }
        for eid, windows in mapping.items():
            for w in windows:
                slices[w].append(_card(eid, w))
        return slices


class TestPortfolioMoverWindowFilter(MoverFilterHTTPBase):
    def test_default_shape_unchanged_when_mover_window_absent(self) -> None:
        """Without mover_window (or any other filter), /portfolio
        returns a bare list — the existing contract."""
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value=self._slices({}),
        ):
            r = self.client.get("/portfolio")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, list)

    def test_mover_window_filter_wraps_response(self) -> None:
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value=self._slices({
                self._event_ids[0]: ["today"],
                self._event_ids[1]: ["weekly"],
            }),
        ):
            r = self.client.get("/portfolio?mover_window=today")
        body = r.json()
        # Filtered response shape is wrapped.
        self.assertIsInstance(body, dict)
        self.assertIn("items", body)
        self.assertIn("mover_window_counts", body)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["id"], self._event_ids[0])
        self.assertIn("today", body["items"][0]["active_mover_windows"])

    def test_mover_window_counts_are_archive_wide(self) -> None:
        """Counts reflect the full candidate set — not post-filter."""
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value=self._slices({
                self._event_ids[0]: ["today"],
                self._event_ids[1]: ["weekly", "persistent"],
                self._event_ids[2]: ["market"],
            }),
        ):
            r = self.client.get("/portfolio?mover_window=today")
        counts = r.json()["mover_window_counts"]
        self.assertEqual(counts["today"], 1)
        self.assertEqual(counts["weekly"], 1)
        self.assertEqual(counts["persistent"], 1)
        self.assertEqual(counts["market"], 1)

    def test_invalid_mover_window_is_400(self) -> None:
        r = self.client.get("/portfolio?mover_window=yearly")
        self.assertEqual(r.status_code, 422)  # FastAPI pattern rejection

    def test_mover_window_combines_with_queue_filter(self) -> None:
        """Combined mover_window + queue must AND the filters: only
        events on the right surface AND in the right queue survive."""
        # Put all three events on today, then filter by a queue that
        # at most one event matches.  The combined result must be a
        # subset of both.
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value=self._slices({
                self._event_ids[0]: ["today"],
                self._event_ids[1]: ["today"],
                self._event_ids[2]: ["weekly"],
            }),
        ):
            # Use a queue that exists in QUEUE_IDS but likely matches
            # a subset of the seeded events.  If QUEUE_IDS changes,
            # this still exercises the combining logic — we're only
            # asserting that the response shape stays wrapped and
            # that items are a subset of the mover_window=today set.
            r = self.client.get(
                "/portfolio?mover_window=today&queue=refresh_needed",
            )
        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertIn("items", body)
        self.assertIn("mover_window_counts", body)
        # Every returned item must be active on today.
        for item in body["items"]:
            self.assertIn("today", item["active_mover_windows"])

    def test_mover_window_combines_with_low_information(self) -> None:
        """Both filters active → wrapped shape returned, no crash."""
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value=self._slices({
                self._event_ids[0]: ["today"],
            }),
        ):
            r = self.client.get(
                "/portfolio?mover_window=today&low_information=false",
            )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, dict)
        self.assertIn("mover_window_counts", body)

    def test_active_mover_windows_on_every_item(self) -> None:
        """Even without a filter being set, each entry in the bare
        list response must carry the new ``active_mover_windows``
        field (additive, always-present)."""
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value=self._slices({
                self._event_ids[0]: ["today", "market"],
            }),
        ):
            r = self.client.get("/portfolio")
        body = r.json()
        self.assertIsInstance(body, list)
        by_id = {e["id"]: e for e in body}
        self.assertEqual(
            by_id[self._event_ids[0]]["active_mover_windows"],
            ["today", "market"],
        )


class TestEventsMoverWindowFilter(MoverFilterHTTPBase):
    def test_default_shape_unchanged_when_mover_window_absent(self) -> None:
        """/events already wraps responses; the default keys stay
        unchanged and mover_window_counts is NOT present."""
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value=self._slices({}),
        ):
            r = self.client.get("/events")
        body = r.json()
        self.assertEqual(
            set(body.keys()), {"items", "total", "offset", "limit"},
        )

    def test_mover_window_filter_adds_counts(self) -> None:
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value=self._slices({
                self._event_ids[0]: ["today"],
                self._event_ids[1]: ["weekly"],
            }),
        ):
            r = self.client.get("/events?mover_window=today")
        body = r.json()
        self.assertIn("mover_window_counts", body)
        self.assertEqual(body["total"], 1)
        # The single returned item is the event active on today.
        self.assertEqual(body["items"][0]["id"], self._event_ids[0])
        self.assertIn("today", body["items"][0]["active_mover_windows"])

    def test_mover_window_counts_archive_wide(self) -> None:
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value=self._slices({
                self._event_ids[0]: ["today"],
                self._event_ids[1]: ["weekly", "today"],
                self._event_ids[2]: ["persistent"],
            }),
        ):
            r = self.client.get("/events?mover_window=persistent")
        counts = r.json()["mover_window_counts"]
        self.assertEqual(counts["today"], 2)
        self.assertEqual(counts["weekly"], 1)
        self.assertEqual(counts["persistent"], 1)
        self.assertEqual(counts["market"], 0)

    def test_invalid_mover_window_is_422(self) -> None:
        r = self.client.get("/events?mover_window=yearly")
        self.assertEqual(r.status_code, 422)

    def test_each_window_returns_only_its_events(self) -> None:
        mapping = {
            self._event_ids[0]: ["today"],
            self._event_ids[1]: ["weekly"],
            self._event_ids[2]: ["persistent"],
        }
        for window, expected_id in (
            ("today", self._event_ids[0]),
            ("weekly", self._event_ids[1]),
            ("persistent", self._event_ids[2]),
        ):
            with patch(
                "routes.movers.load_ui_slices_for_event_context",
                return_value=self._slices(mapping),
            ):
                r = self.client.get(f"/events?mover_window={window}")
            body = r.json()
            self.assertEqual(body["total"], 1, f"window={window}")
            self.assertEqual(
                body["items"][0]["id"], expected_id,
                f"window={window}: wrong item",
            )

    def test_market_window_filter(self) -> None:
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value=self._slices({
                self._event_ids[0]: ["market"],
                self._event_ids[1]: ["today"],
            }),
        ):
            r = self.client.get("/events?mover_window=market")
        body = r.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["id"], self._event_ids[0])

    def test_no_matches_returns_empty_items_with_counts(self) -> None:
        """When the filter matches nothing, total=0 but the facet
        counts still reflect archive state."""
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value=self._slices({
                self._event_ids[0]: ["weekly"],
            }),
        ):
            r = self.client.get("/events?mover_window=market")
        body = r.json()
        self.assertEqual(body["total"], 0)
        self.assertEqual(body["items"], [])
        self.assertEqual(body["mover_window_counts"]["weekly"], 1)


if __name__ == "__main__":
    unittest.main()
