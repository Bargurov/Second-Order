"""
tests/test_mover_context.py

Contract tests for the ``mover_context`` block attached to
``/events/{id}`` when the event is active in any mover surface.

Covers:
  * Pure composer ``build_mover_context`` — correct shape, window
    priority, multi-window aggregation, empty-shape defaults.
  * ``empty_mover_context`` factory matches the documented empty
    contract.
  * HTTP surface — ``/events/{id}`` carries ``mover_context``
    populated when the event is active on any slice, and the stable
    empty shape when it isn't.
  * Existing response keys on ``/events/{id}`` stay intact — no
    collisions with the additive ``mover_context`` key.
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

from mover_context import build_mover_context, empty_mover_context


REQUIRED_KEYS = {
    "active_windows", "surfaced_reason",
    "strongest_move_5d", "moved_tickers",
}


def _ui_card(event_id: int, window: str, **overrides) -> dict:
    """Build a minimal UI-ready mover card for composer tests."""
    card = {
        "id":                event_id,
        "headline":          "Stub headline",
        "mechanism_family":  "commodity_squeeze",
        "thesis_state":      "active",
        "proof_quality":     "met",
        "stale_signal":      "ok",
        "mover_window":      window,
        "weighted_evidence": {"label": "validated"},
        "surfaced_reason":   f"Active on {window} surface.",
        "moved_tickers": [
            {"symbol": "USO", "role": "beneficiary",
             "direction": "supports", "return_5d": 3.0},
        ],
        "strongest_move_5d": 3.0,
    }
    card.update(overrides)
    return card


# ---------------------------------------------------------------------------
# Composer — shape / priority / empty paths
# ---------------------------------------------------------------------------


class TestEmptyContext(unittest.TestCase):
    def test_factory_shape(self) -> None:
        out = empty_mover_context()
        self.assertEqual(set(out.keys()), REQUIRED_KEYS)
        self.assertEqual(out["active_windows"], [])
        self.assertEqual(out["surfaced_reason"], "")
        self.assertIsNone(out["strongest_move_5d"])
        self.assertEqual(out["moved_tickers"], [])

    def test_inactive_event_returns_empty_shape(self) -> None:
        slices = {"today": [_ui_card(1, "today")],
                  "market": [], "weekly": [], "persistent": []}
        out = build_mover_context(99, slices)
        self.assertEqual(set(out.keys()), REQUIRED_KEYS)
        self.assertEqual(out["active_windows"], [])
        self.assertEqual(out["moved_tickers"], [])

    def test_none_event_id_returns_empty_shape(self) -> None:
        out = build_mover_context(None, {"today": [_ui_card(1, "today")]})  # type: ignore[arg-type]
        self.assertEqual(out["active_windows"], [])

    def test_bool_id_rejected(self) -> None:
        """``bool`` is a subclass of ``int`` — guard against silent
        coercion so ``True`` doesn't match event_id=1."""
        out = build_mover_context(True, {"today": [_ui_card(1, "today")]})  # type: ignore[arg-type]
        self.assertEqual(out["active_windows"], [])

    def test_missing_slices_returns_empty_shape(self) -> None:
        out = build_mover_context(1, None)  # type: ignore[arg-type]
        self.assertEqual(out["active_windows"], [])

    def test_empty_slice_map_returns_empty_shape(self) -> None:
        out = build_mover_context(1, {})
        self.assertEqual(out["active_windows"], [])


class TestSingleWindow(unittest.TestCase):
    def test_event_active_on_today_only(self) -> None:
        slices = {
            "today":      [_ui_card(42, "today",
                                    surfaced_reason="Oil spiking 3% today.",
                                    strongest_move_5d=4.2)],
            "market":     [], "weekly": [], "persistent": [],
        }
        out = build_mover_context(42, slices)
        self.assertEqual(out["active_windows"], ["today"])
        self.assertIn("Oil spiking", out["surfaced_reason"])
        self.assertEqual(out["strongest_move_5d"], 4.2)
        self.assertEqual(len(out["moved_tickers"]), 1)

    def test_event_active_on_persistent_only(self) -> None:
        slices = {
            "today": [], "market": [], "weekly": [],
            "persistent": [_ui_card(42, "persistent",
                                    surfaced_reason="Still moving 12d later.")],
        }
        out = build_mover_context(42, slices)
        self.assertEqual(out["active_windows"], ["persistent"])


class TestMultipleWindowPriority(unittest.TestCase):
    def test_today_beats_persistent_for_primary(self) -> None:
        """When an event is on both today and persistent, today wins
        for the primary card (surfaced_reason / strongest_move_5d /
        moved_tickers) — fresh-window priority."""
        slices = {
            "today":      [_ui_card(42, "today",
                                    surfaced_reason="Moving today.",
                                    strongest_move_5d=3.1)],
            "market":     [],
            "weekly":     [],
            "persistent": [_ui_card(42, "persistent",
                                    surfaced_reason="Moving structurally.",
                                    strongest_move_5d=5.0)],
        }
        out = build_mover_context(42, slices)
        self.assertEqual(out["active_windows"], ["today", "persistent"])
        self.assertEqual(out["surfaced_reason"], "Moving today.")
        self.assertEqual(out["strongest_move_5d"], 3.1)

    def test_market_beats_weekly_when_today_absent(self) -> None:
        slices = {
            "today":      [],
            "market":     [_ui_card(42, "market",
                                    surfaced_reason="Big 48h move.")],
            "weekly":     [_ui_card(42, "weekly",
                                    surfaced_reason="7d cumulative.")],
            "persistent": [],
        }
        out = build_mover_context(42, slices)
        self.assertEqual(out["active_windows"], ["market", "weekly"])
        self.assertEqual(out["surfaced_reason"], "Big 48h move.")

    def test_active_on_all_four_surfaces(self) -> None:
        slices = {
            "today":      [_ui_card(42, "today")],
            "market":     [_ui_card(42, "market")],
            "weekly":     [_ui_card(42, "weekly")],
            "persistent": [_ui_card(42, "persistent")],
        }
        out = build_mover_context(42, slices)
        self.assertEqual(
            out["active_windows"],
            ["today", "market", "weekly", "persistent"],
        )


class TestRobustnessToMalformedSlices(unittest.TestCase):
    def test_non_list_slice_value_ignored(self) -> None:
        slices = {
            "today":      "not a list",  # type: ignore[dict-item]
            "market":     [_ui_card(42, "market")],
            "weekly":     [],
            "persistent": [],
        }
        out = build_mover_context(42, slices)
        self.assertEqual(out["active_windows"], ["market"])

    def test_non_dict_card_ignored(self) -> None:
        slices = {
            "today":      ["not a dict", 42, None, _ui_card(42, "today")],  # type: ignore[list-item]
            "market":     [], "weekly": [], "persistent": [],
        }
        out = build_mover_context(42, slices)
        self.assertEqual(out["active_windows"], ["today"])

    def test_card_with_event_id_field_also_matches(self) -> None:
        """Raw cards from the builder carry ``event_id``; enriched UI
        cards carry ``id``.  The composer reads both so it works on
        either shape."""
        slices = {
            "today": [{"event_id": 42, "surfaced_reason": "raw",
                       "strongest_move_5d": 1.0, "moved_tickers": []}],
            "market": [], "weekly": [], "persistent": [],
        }
        out = build_mover_context(42, slices)
        self.assertEqual(out["active_windows"], ["today"])
        self.assertEqual(out["surfaced_reason"], "raw")


# ---------------------------------------------------------------------------
# HTTP surface — /events/{id} carries mover_context
# ---------------------------------------------------------------------------


class EventsDetailMoverContextBase(unittest.TestCase):
    def setUp(self) -> None:
        import db as _db
        self._db = _db
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"ctxt_{uuid.uuid4().hex}.db",
        )
        _db.DB_FILE = self._tmp
        _db._db_ready = False
        _db.init_db()

        from fastapi.testclient import TestClient
        import api as _api_mod
        self.client = TestClient(_api_mod.app)

    def tearDown(self) -> None:
        self._db.DB_FILE = self._orig
        self._db._db_ready = False
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _save_event(self, headline: str = "Mover context smoke") -> int:
        self._db.save_event({
            "headline":           headline,
            "stage":              "realized",
            "persistence":        "medium",
            "mechanism_summary":  "A mechanism with enough length to save.",
            "beneficiaries":      ["CVX"],
            "losers":             ["SU"],
            "assets_to_watch":    ["CVX", "SU"],
            "confidence":         "medium",
            "market_note":        "",
            "notes":              "",
        })
        rows = self._db.load_recent_events(limit=1)
        return rows[0]["id"]


class TestEventsDetailMoverContext(EventsDetailMoverContextBase):
    def test_inactive_event_gets_empty_mover_context(self) -> None:
        eid = self._save_event()
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value={"today": [], "market": [],
                          "weekly": [], "persistent": []},
        ):
            body = self.client.get(f"/events/{eid}").json()
        ctx = body["mover_context"]
        self.assertEqual(set(ctx.keys()), REQUIRED_KEYS)
        self.assertEqual(ctx["active_windows"], [])
        self.assertEqual(ctx["moved_tickers"], [])

    def test_active_event_populates_mover_context(self) -> None:
        eid = self._save_event(headline="Event on today surface")
        card = _ui_card(
            eid, "today",
            surfaced_reason="Today-surface justification.",
            strongest_move_5d=4.5,
        )
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value={
                "today": [card], "market": [], "weekly": [], "persistent": [],
            },
        ):
            body = self.client.get(f"/events/{eid}").json()
        ctx = body["mover_context"]
        self.assertEqual(ctx["active_windows"], ["today"])
        self.assertEqual(ctx["strongest_move_5d"], 4.5)
        self.assertIn("Today-surface", ctx["surfaced_reason"])
        self.assertEqual(len(ctx["moved_tickers"]), 1)

    def test_existing_top_level_keys_unchanged(self) -> None:
        eid = self._save_event(headline="Keys unchanged smoke")
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value={"today": [], "market": [],
                          "weekly": [], "persistent": []},
        ):
            body = self.client.get(f"/events/{eid}").json()
        # Every documented top-level key on the legacy response is
        # still present.  mover_context is purely additive.
        for key in (
            "id", "headline", "confidence", "beneficiaries", "losers",
            "proof_status", "falsifier_status", "mover_context",
        ):
            self.assertIn(key, body, f"missing {key!r}")

    def test_active_on_multiple_windows_uses_today_primary(self) -> None:
        eid = self._save_event(headline="Active on multiple surfaces")
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            return_value={
                "today":      [_ui_card(eid, "today",
                                        surfaced_reason="Today wins.",
                                        strongest_move_5d=2.5)],
                "market":     [],
                "weekly":     [_ui_card(eid, "weekly",
                                        surfaced_reason="Weekly.")],
                "persistent": [_ui_card(eid, "persistent",
                                        surfaced_reason="Persistent.")],
            },
        ):
            body = self.client.get(f"/events/{eid}").json()
        ctx = body["mover_context"]
        self.assertEqual(ctx["active_windows"],
                         ["today", "weekly", "persistent"])
        # Primary = today per priority order.
        self.assertEqual(ctx["surfaced_reason"], "Today wins.")
        self.assertEqual(ctx["strongest_move_5d"], 2.5)

    def test_mover_slice_failure_does_not_break_detail(self) -> None:
        """A crash inside ``load_ui_slices_for_event_context`` must
        not propagate — the detail endpoint still returns 200 with the
        empty mover_context."""
        eid = self._save_event()
        with patch(
            "routes.movers.load_ui_slices_for_event_context",
            side_effect=RuntimeError("boom"),
        ):
            r = self.client.get(f"/events/{eid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["mover_context"]["active_windows"], [])


if __name__ == "__main__":
    unittest.main()
