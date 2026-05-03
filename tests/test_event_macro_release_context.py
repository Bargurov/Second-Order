"""Focused tests for per-event macro_release_context persistence + exports.

Covers:
  * builder maps a headline to an in-window calendar release
  * persist round-trip through save_event → load_event_by_id
  * /events/{id} returns the canonical empty-shape dict when absent
  * refresh path flips the block after facts land
  * JSON / markdown / text memo exports include the block
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db as _db
import macro_release_facts as _facts
import macro_surprise as _ms


class _TempDBMixin:
    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="ev_macro_ctx_")
        os.close(fd)
        os.unlink(path)
        self._tmp_path = path
        self._patchers = [
            mock.patch.object(_db, "DB_FILE", path),
            mock.patch.object(_facts, "DB_FILE", path),
        ]
        for p in self._patchers:
            p.start()
        _db.init_db()

    def tearDown(self) -> None:
        for p in self._patchers:
            p.stop()
        try:
            os.unlink(self._tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Builder — maps headline → release via indicator keywords
# ---------------------------------------------------------------------------

class TestBuildEventMacroReleaseContext(_TempDBMixin, unittest.TestCase):
    def _calendar(self, today: date) -> list[dict]:
        from macro_calendar import get_macro_releases
        return get_macro_releases(today=today, days_before=3, days_after=0)

    def test_maps_headline_to_release_with_stored_facts(self) -> None:
        _facts.upsert_release_facts(
            release_key="CPI:2026-04-10",
            release_time="2026-04-10T12:30:00Z",
            actual=3.5, prior=3.0, consensus=3.0, source="BLS",
        )
        cal = self._calendar(date(2026, 4, 10))
        block = _ms.build_event_macro_release_context(
            {"headline": "US CPI rose 3.5% in March"}, cal,
        )
        self.assertEqual(block["release_key"], "CPI:2026-04-10")
        self.assertEqual(block["release_time"], "2026-04-10T12:30:00Z")
        self.assertEqual(block["actual"], 3.5)
        self.assertEqual(block["consensus"], 3.0)
        self.assertEqual(block["surprise_label"], "beat")
        self.assertEqual(block["source"], "BLS")

    def test_maps_without_facts_leaves_numerics_none(self) -> None:
        cal = self._calendar(date(2026, 4, 10))
        block = _ms.build_event_macro_release_context(
            {"headline": "US CPI rose 3.5% in March"}, cal,
        )
        self.assertEqual(block["release_key"], "CPI:2026-04-10")
        self.assertIsNone(block["actual"])
        self.assertIsNone(block["consensus"])
        self.assertIsNone(block["surprise_label"])
        self.assertEqual(block["source"], "")

    def test_unrelated_headline_returns_empty_dict(self) -> None:
        cal = self._calendar(date(2026, 4, 10))
        block = _ms.build_event_macro_release_context(
            {"headline": "Tech stocks rally as bond yields slip"}, cal,
        )
        self.assertEqual(block, {})

    def test_out_of_window_release_is_ignored(self) -> None:
        # Far-past release — not within the [-3, 0] window.
        cal = self._calendar(date(2026, 4, 30))
        block = _ms.build_event_macro_release_context(
            {"headline": "Looking back at CPI from earlier this month"}, cal,
        )
        self.assertEqual(block, {})


# ---------------------------------------------------------------------------
# Coercion — stable empty shape at the HTTP boundary
# ---------------------------------------------------------------------------

class TestCoerceMacroReleaseContext(unittest.TestCase):
    def test_empty_inflates_to_canonical_shape(self) -> None:
        for raw in ({}, None, "", 0, []):
            with self.subTest(raw=raw):
                out = _ms.coerce_macro_release_context(raw)  # type: ignore[arg-type]
                self.assertEqual(set(out.keys()), {
                    "release_key", "release_time", "actual", "prior",
                    "revised_prior", "consensus", "surprise_label", "source",
                })
                for key in ("release_key", "release_time", "actual", "prior",
                            "revised_prior", "consensus", "surprise_label"):
                    self.assertIsNone(out[key])
                self.assertEqual(out["source"], "")

    def test_populated_block_passes_through(self) -> None:
        raw = {
            "release_key": "CPI:2026-04-10",
            "release_time": "2026-04-10T12:30:00Z",
            "actual": 3.5, "prior": 3.0, "revised_prior": None,
            "consensus": 3.0, "surprise_label": "beat", "source": "BLS",
        }
        out = _ms.coerce_macro_release_context(raw)
        self.assertEqual(out, raw)


# ---------------------------------------------------------------------------
# Save → load round-trip through the real DB layer
# ---------------------------------------------------------------------------

class TestEventPersistRoundTrip(_TempDBMixin, unittest.TestCase):
    def _seed(self, **overrides) -> int:
        ts = datetime.now().isoformat(timespec="seconds")
        event = {
            "timestamp":         ts,
            "headline":          "CPI rose 3.5% in March — hot print",
            "stage":             "confirmed",
            "persistence":       "medium",
            "confidence":        "medium",
            "mechanism_summary": "Sticky services inflation.",
            "event_date":        "2026-04-10",
            "market_tickers":    [],
            "macro_release_context": overrides.get("macro_release_context", {}),
        }
        event.update({k: v for k, v in overrides.items()
                      if k != "macro_release_context"})
        _db.save_event(event)
        from db import load_recent_events
        return load_recent_events(limit=1)[0]["id"]

    def test_save_without_block_round_trips_as_empty_dict(self) -> None:
        eid = self._seed()
        from db import load_event_by_id
        loaded = load_event_by_id(eid)
        self.assertEqual(loaded["macro_release_context"], {})

    def test_save_with_block_round_trips_as_dict_not_raw_json(self) -> None:
        block = {
            "release_key": "CPI:2026-04-10",
            "release_time": "2026-04-10T12:30:00Z",
            "actual": 3.5, "prior": 3.0, "revised_prior": None,
            "consensus": 3.0, "surprise_label": "beat", "source": "BLS",
        }
        eid = self._seed(macro_release_context=block)
        from db import load_event_by_id
        loaded = load_event_by_id(eid)
        self.assertIsInstance(loaded["macro_release_context"], dict)
        self.assertEqual(loaded["macro_release_context"], block)


# ---------------------------------------------------------------------------
# /events/{id} returns canonical shape; refresh path updates block
# ---------------------------------------------------------------------------

class TestEventDetailAndRefresh(_TempDBMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        from fastapi.testclient import TestClient
        import api as _api_mod
        self.client = TestClient(_api_mod.app)

    def _seed(self, *, headline: str, block: dict | None = None) -> int:
        ts = datetime.now().isoformat(timespec="seconds")
        event = {
            "timestamp":         ts,
            "headline":          headline,
            "stage":             "confirmed",
            "persistence":       "medium",
            "confidence":        "medium",
            "mechanism_summary": "Sample.",
            "event_date":        "2026-04-10",
            "market_tickers":    [],
            "macro_release_context": block or {},
        }
        _db.save_event(event)
        from db import load_recent_events
        return load_recent_events(limit=1)[0]["id"]

    def test_detail_returns_canonical_empty_shape_for_unmapped(self) -> None:
        eid = self._seed(headline="Tech stocks rally as bond yields slip")
        resp = self.client.get(f"/events/{eid}")
        self.assertEqual(resp.status_code, 200)
        block = resp.json()["macro_release_context"]
        self.assertIsNone(block["release_key"])
        self.assertIsNone(block["actual"])
        self.assertEqual(block["source"], "")

    def test_refresh_flow_fills_block_after_facts_land(self) -> None:
        # Headline maps to CPI:2026-04-10 but no facts stored yet.
        eid = self._seed(headline="US CPI rose 3.5% in March")
        # Sanity: stored block is {} until a refresh runs.
        from db import load_event_by_id
        self.assertEqual(load_event_by_id(eid)["macro_release_context"], {})

        # Simulate a feed landing the release facts.
        _facts.upsert_release_facts(
            release_key="CPI:2026-04-10",
            release_time="2026-04-10T12:30:00Z",
            actual=3.5, prior=3.0, consensus=3.0, source="BLS",
        )

        # Run the refresh helper directly — exercises the
        # update path used by refresh-market / refresh-overlays /
        # revisit without booting yfinance.
        from routes.events import _refresh_macro_release_context

        today = date.today()
        calendar_today = date(2026, 4, 10)
        delta = calendar_today - today
        with mock.patch("macro_calendar.date") as mock_date:
            mock_date.today.return_value = today + delta
            mock_date.fromisoformat = date.fromisoformat
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            _refresh_macro_release_context(eid, {
                "headline":   "US CPI rose 3.5% in March",
                "event_date": "2026-04-10",
            })
        loaded = load_event_by_id(eid)
        block = loaded["macro_release_context"]
        self.assertEqual(block["release_key"], "CPI:2026-04-10")
        self.assertEqual(block["actual"], 3.5)
        self.assertEqual(block["surprise_label"], "beat")
        self.assertEqual(block["source"], "BLS")


# ---------------------------------------------------------------------------
# Exports — JSON / markdown / text memo all surface the block
# ---------------------------------------------------------------------------

class TestExportsIncludeMacroBlock(_TempDBMixin, unittest.TestCase):
    _POPULATED_BLOCK = {
        "release_key": "CPI:2026-04-10",
        "release_time": "2026-04-10T12:30:00Z",
        "actual": 3.5, "prior": 3.0, "revised_prior": 2.9,
        "consensus": 3.0, "surprise_label": "beat", "source": "BLS",
    }

    def _sample(self, with_block: bool) -> dict:
        return {
            "id": 1,
            "timestamp": "2026-04-10T12:00:00",
            "headline": "US CPI rose 3.5%",
            "event_date": "2026-04-10",
            "stage": "confirmed", "persistence": "medium", "confidence": "medium",
            "what_changed": "Hot print.",
            "mechanism_summary": "Sticky services.",
            "beneficiaries": [], "losers": [], "assets_to_watch": [],
            "market_note": "", "market_tickers": [],
            "macro_release_context": (
                self._POPULATED_BLOCK if with_block else {}
            ),
        }

    def test_json_export_includes_block_when_populated(self) -> None:
        import api as _api
        ev = self._sample(with_block=True)
        out = _api._build_event_json_export(ev)
        self.assertIn("macro_release_context", out)
        self.assertEqual(out["macro_release_context"]["release_key"], "CPI:2026-04-10")
        self.assertEqual(out["macro_release_context"]["surprise_label"], "beat")

    def test_json_export_emits_canonical_empty_shape_when_absent(self) -> None:
        import api as _api
        ev = self._sample(with_block=False)
        out = _api._build_event_json_export(ev)
        block = out["macro_release_context"]
        self.assertIsNone(block["release_key"])
        self.assertIsNone(block["actual"])
        self.assertEqual(block["source"], "")

    def test_markdown_memo_renders_section(self) -> None:
        import api as _api
        md = _api._build_event_markdown_memo(self._sample(with_block=True))
        self.assertIn("## Macro Release", md)
        self.assertIn("CPI:2026-04-10", md)
        self.assertIn("`beat`", md)
        self.assertIn("3 → 2.9", md)  # revised_prior surfaces

    def test_markdown_memo_omits_section_when_empty(self) -> None:
        import api as _api
        md = _api._build_event_markdown_memo(self._sample(with_block=False))
        self.assertNotIn("Macro Release", md)

    def test_text_memo_renders_block(self) -> None:
        import api as _api
        txt = _api._build_event_text_memo(self._sample(with_block=True))
        self.assertIn("MACRO RELEASE", txt)
        self.assertIn("CPI:2026-04-10", txt)
        self.assertIn("beat", txt)

    def test_research_memo_renders_section(self) -> None:
        import api as _api
        md = _api._build_event_research_memo(self._sample(with_block=True))
        self.assertIn("## Macro Release", md)
        self.assertIn("CPI:2026-04-10", md)


# ---------------------------------------------------------------------------
# Backfill / refresh — older studies pick up the block once facts land
# ---------------------------------------------------------------------------

class TestMacroReleaseBackfill(_TempDBMixin, unittest.TestCase):
    """Task contract: refresh/revisit on an older study must backfill
    ``macro_release_context`` from stored release facts when a clear
    calendar match exists, never overwrite a populated block with an
    empty one, and keep the stable empty/default shape on unmapped
    headlines — independent of when the refresh runs relative to the
    release date."""

    def setUp(self) -> None:
        super().setUp()
        from fastapi.testclient import TestClient
        import api as _api_mod
        self.client = TestClient(_api_mod.app)

    def _seed(
        self,
        *,
        headline: str,
        event_date: str,
        block: dict | None = None,
    ) -> int:
        ts = datetime.now().isoformat(timespec="seconds")
        event = {
            "timestamp":             ts,
            "headline":              headline,
            "stage":                 "confirmed",
            "persistence":           "medium",
            "confidence":            "medium",
            "mechanism_summary":     "Sample.",
            "event_date":            event_date,
            "market_tickers":        [],
            "macro_release_context": block if block is not None else {},
        }
        _db.save_event(event)
        from db import load_recent_events
        return load_recent_events(limit=1)[0]["id"]

    # ---- 1. Backfill -----------------------------------------------------

    def test_backfill_on_older_event_after_facts_land(self) -> None:
        """The refresh call runs "today" (far from the release date), but
        the event was captured on 2026-04-10 — a CPI release the facts
        store now knows about.  Anchoring the calendar to the event's
        own date must let the backfill land."""
        eid = self._seed(
            headline="US CPI rose 3.5% in March",
            event_date="2026-04-10",
        )
        from db import load_event_by_id
        self.assertEqual(load_event_by_id(eid)["macro_release_context"], {})

        _facts.upsert_release_facts(
            release_key="CPI:2026-04-10",
            release_time="2026-04-10T12:30:00Z",
            actual=3.5, prior=3.0, consensus=3.0, source="BLS",
        )
        # NOTE: no mocking of today — proves the anchoring works even
        # when the live calendar window would not match.
        from routes.events import _refresh_macro_release_context
        _refresh_macro_release_context(eid, {
            "headline":   "US CPI rose 3.5% in March",
            "event_date": "2026-04-10",
        })

        block = load_event_by_id(eid)["macro_release_context"]
        self.assertEqual(block["release_key"], "CPI:2026-04-10")
        self.assertEqual(block["actual"], 3.5)
        self.assertEqual(block["consensus"], 3.0)
        self.assertEqual(block["surprise_label"], "beat")
        self.assertEqual(block["source"], "BLS")

    # ---- 2. Do not overwrite a populated block with empty ---------------

    def test_populated_block_preserved_when_builder_cannot_match(self) -> None:
        """A very old event (before the static calendar begins) cannot
        map to any calendar release today — the refresh must leave the
        already-populated block intact rather than wipe it with {}."""
        populated = {
            "release_key":    "CPI:2020-01-14",
            "release_time":   "2020-01-14T13:30:00Z",
            "actual":         2.3, "prior": 2.1, "revised_prior": None,
            "consensus":      2.4, "surprise_label": "miss", "source": "BLS",
        }
        eid = self._seed(
            headline="US CPI rose 2.3% in December",
            event_date="2020-01-14",
            block=populated,
        )
        from routes.events import _refresh_macro_release_context
        _refresh_macro_release_context(eid, {
            "headline":   "US CPI rose 2.3% in December",
            "event_date": "2020-01-14",
        })

        from db import load_event_by_id
        block = load_event_by_id(eid)["macro_release_context"]
        self.assertEqual(block, populated)

    # ---- 3. No-data fallback keeps stable empty shape -------------------

    def test_unmapped_headline_stays_empty_after_refresh(self) -> None:
        """A headline that doesn't hit any indicator keyword produces
        no match on refresh — the stored block stays at the stable
        empty default ``{}`` so ``/events/{id}`` can still inflate it
        to the canonical keyset."""
        eid = self._seed(
            headline="Tech stocks rally as bond yields slip",
            event_date="2026-04-10",
        )
        from routes.events import _refresh_macro_release_context
        _refresh_macro_release_context(eid, {
            "headline":   "Tech stocks rally as bond yields slip",
            "event_date": "2026-04-10",
        })

        from db import load_event_by_id
        self.assertEqual(load_event_by_id(eid)["macro_release_context"], {})

        # /events/{id} still inflates to the canonical shape.
        resp = self.client.get(f"/events/{eid}")
        self.assertEqual(resp.status_code, 200)
        shaped = resp.json()["macro_release_context"]
        self.assertIn("release_key", shaped)
        self.assertIsNone(shaped["release_key"])
        self.assertEqual(shaped["source"], "")

    # ---- 4. /events/{id} and refresh paths agree on shape ---------------

    def test_detail_and_post_refresh_block_have_same_shape(self) -> None:
        """After a successful backfill, the ``macro_release_context``
        block returned by ``/events/{id}`` must carry exactly the same
        keyset the refresh helper just stored (coerce at the boundary
        only adds missing defaults)."""
        eid = self._seed(
            headline="NFP: 180k jobs added in March",
            event_date="2026-04-03",
        )
        _facts.upsert_release_facts(
            release_key="NFP:2026-04-03",
            release_time="2026-04-03T12:30:00Z",
            actual=180_000, prior=200_000, revised_prior=185_000,
            consensus=190_000, source="BLS",
        )
        from routes.events import _refresh_macro_release_context
        _refresh_macro_release_context(eid, {
            "headline":   "NFP: 180k jobs added in March",
            "event_date": "2026-04-03",
        })

        from db import load_event_by_id
        stored = load_event_by_id(eid)["macro_release_context"]
        resp = self.client.get(f"/events/{eid}")
        self.assertEqual(resp.status_code, 200)
        shaped = resp.json()["macro_release_context"]

        expected_keys = {
            "release_key", "release_time", "actual", "prior",
            "revised_prior", "consensus", "surprise_label", "source",
        }
        self.assertEqual(set(shaped.keys()), expected_keys)
        # Every key the stored block carries must match the detail-path
        # block; coerce_macro_release_context may add defaults for
        # missing keys but must not alter populated values.
        for key, value in stored.items():
            self.assertEqual(shaped[key], value, msg=f"key={key}")

    # ---- 5. Old-row load tolerance: NULL column / legacy shape ----------

    def test_null_column_loads_as_empty_dict(self) -> None:
        """An older row whose ``macro_release_context`` column is NULL
        (e.g. written before the default-value migration ran) must load
        cleanly as ``{}`` without blowing up the JSON decode path."""
        import sqlite3
        eid = self._seed(
            headline="Generic event", event_date="2026-04-10",
        )
        # Force the column to NULL to simulate the pre-migration state.
        with sqlite3.connect(self._tmp_path) as conn:
            conn.execute(
                "UPDATE events SET macro_release_context = NULL WHERE id = ?",
                (eid,),
            )
        from db import load_event_by_id
        loaded = load_event_by_id(eid)
        self.assertEqual(loaded["macro_release_context"], {})

        # /events/{id} still coerces to the canonical keyset.
        resp = self.client.get(f"/events/{eid}")
        self.assertEqual(resp.status_code, 200)
        shaped = resp.json()["macro_release_context"]
        self.assertIsNone(shaped["release_key"])
        self.assertEqual(shaped["source"], "")


if __name__ == "__main__":
    unittest.main()
