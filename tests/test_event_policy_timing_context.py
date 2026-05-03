"""Focused tests for per-event policy_timing_context persistence + exports.

Covers:
  * builder maps a headline to a tracked policy
  * persist round-trip through save_event → load_event_by_id
  * /events/{id} returns canonical empty-shape dict when absent
  * refresh path flips the block after a later run
  * JSON / markdown / text memo exports include the block
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db as _db
import policy_timing as _pt


class _TempDBMixin:
    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="ev_policy_ctx_")
        os.close(fd)
        os.unlink(path)
        self._tmp_path = path
        self._patchers = [mock.patch.object(_db, "DB_FILE", path)]
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
# Builder — headline → tracked-policy block
# ---------------------------------------------------------------------------

class TestBuildEventPolicyTimingContext(unittest.TestCase):
    def test_matched_headline_returns_full_block(self) -> None:
        block = _pt.build_event_policy_timing_context(
            {"headline": "Biden ECB rate decision passes"},
            today=date(2026, 5, 1),
        )
        # Should match one of the tracked policies (ECB rate decision).
        self.assertTrue(block)
        for key in ("policy_key", "announced_date", "effective_date",
                    "review_date", "status", "source"):
            self.assertIn(key, block)

    def test_unmatched_headline_returns_empty_dict(self) -> None:
        block = _pt.build_event_policy_timing_context(
            {"headline": "Tech stocks rally as bond yields slip"},
            today=date(2026, 5, 1),
        )
        self.assertEqual(block, {})

    def test_blank_headline_returns_empty_dict(self) -> None:
        self.assertEqual(
            _pt.build_event_policy_timing_context({"headline": ""}), {},
        )
        self.assertEqual(_pt.build_event_policy_timing_context({}), {})
        self.assertEqual(_pt.build_event_policy_timing_context(None), {})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Coercion — stable empty shape
# ---------------------------------------------------------------------------

class TestCoercePolicyTimingContext(unittest.TestCase):
    _keys = {
        "policy_key", "announced_date", "effective_date",
        "review_date", "status", "source",
    }

    def test_empty_inflates_to_canonical_shape(self) -> None:
        for raw in ({}, None, "", 0, []):
            with self.subTest(raw=raw):
                out = _pt.coerce_policy_timing_context(raw)  # type: ignore[arg-type]
                self.assertEqual(set(out.keys()), self._keys)
                for key in ("policy_key", "announced_date", "effective_date",
                            "review_date", "status"):
                    self.assertIsNone(out[key])
                self.assertEqual(out["source"], "")

    def test_populated_block_passes_through(self) -> None:
        raw = {
            "policy_key":     "ecb_rate_decision_2026_04",
            "announced_date": "2026-03-06",
            "effective_date": "2026-04-17",
            "review_date":    "2026-06-05",
            "status":         "effective",
            "source":         "ECB",
        }
        self.assertEqual(_pt.coerce_policy_timing_context(raw), raw)


# ---------------------------------------------------------------------------
# Save → load round-trip through the real DB layer
# ---------------------------------------------------------------------------

class TestEventPersistRoundTrip(_TempDBMixin, unittest.TestCase):
    def _seed(self, *, block=None, headline=None) -> int:
        ts = datetime.now().isoformat(timespec="seconds")
        event = {
            "timestamp":             ts,
            "headline":              headline or "ECB rate decision passes",
            "stage":                 "confirmed",
            "persistence":           "medium",
            "confidence":            "medium",
            "mechanism_summary":     "Policy move.",
            "event_date":            "2026-04-17",
            "market_tickers":        [],
            "policy_timing_context": block if block is not None else {},
        }
        _db.save_event(event)
        from db import load_recent_events
        return load_recent_events(limit=1)[0]["id"]

    def test_save_without_block_round_trips_as_empty_dict(self) -> None:
        eid = self._seed()
        from db import load_event_by_id
        loaded = load_event_by_id(eid)
        self.assertEqual(loaded["policy_timing_context"], {})

    def test_save_with_block_round_trips_as_dict_not_raw_json(self) -> None:
        block = {
            "policy_key":     "ecb_rate_decision_2026_04",
            "announced_date": "2026-03-06",
            "effective_date": "2026-04-17",
            "review_date":    "2026-06-05",
            "status":         "effective",
            "source":         "ECB",
        }
        eid = self._seed(block=block)
        from db import load_event_by_id
        loaded = load_event_by_id(eid)
        self.assertIsInstance(loaded["policy_timing_context"], dict)
        self.assertEqual(loaded["policy_timing_context"], block)


# ---------------------------------------------------------------------------
# /events/{id} canonical shape + refresh backfill
# ---------------------------------------------------------------------------

class TestEventDetailAndRefresh(_TempDBMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        from fastapi.testclient import TestClient
        import api as _api_mod
        self.client = TestClient(_api_mod.app)

    def _seed(self, headline: str, *, block=None) -> int:
        ts = datetime.now().isoformat(timespec="seconds")
        event = {
            "timestamp":             ts,
            "headline":              headline,
            "stage":                 "confirmed",
            "persistence":           "medium",
            "confidence":            "medium",
            "mechanism_summary":     "Sample.",
            "event_date":            "2026-04-17",
            "market_tickers":        [],
            "policy_timing_context": block if block is not None else {},
        }
        _db.save_event(event)
        from db import load_recent_events
        return load_recent_events(limit=1)[0]["id"]

    def test_detail_returns_canonical_empty_shape_for_unmapped(self) -> None:
        eid = self._seed("Tech stocks rally as bond yields slip")
        resp = self.client.get(f"/events/{eid}")
        self.assertEqual(resp.status_code, 200)
        block = resp.json()["policy_timing_context"]
        self.assertIsNone(block["policy_key"])
        self.assertIsNone(block["status"])
        self.assertEqual(block["source"], "")

    def test_refresh_flow_fills_block_for_matching_headline(self) -> None:
        # Save the event with an empty block to simulate a row persisted
        # before policy_timing existed.
        eid = self._seed("ECB rate decision passes")
        from db import load_event_by_id
        self.assertEqual(load_event_by_id(eid)["policy_timing_context"], {})

        from routes.events import _refresh_policy_timing_context
        _refresh_policy_timing_context(eid, {
            "headline":   "ECB rate decision passes",
            "event_date": "2026-04-17",
        })
        loaded = load_event_by_id(eid)
        block = loaded["policy_timing_context"]
        self.assertIsNotNone(block.get("policy_key"))
        self.assertEqual(block.get("source"), "ECB")


# ---------------------------------------------------------------------------
# Exports — JSON / markdown / text memo all surface the block
# ---------------------------------------------------------------------------

class TestExportsIncludePolicyTimingBlock(unittest.TestCase):
    _POPULATED_BLOCK = {
        "policy_key":     "ecb_rate_decision_2026_04",
        "announced_date": "2026-03-06",
        "effective_date": "2026-04-17",
        "review_date":    "2026-06-05",
        "status":         "effective",
        "source":         "ECB",
    }

    def _sample(self, with_block: bool) -> dict:
        return {
            "id": 1,
            "timestamp": "2026-04-17T12:00:00",
            "headline": "ECB rate decision passes",
            "event_date": "2026-04-17",
            "stage": "confirmed", "persistence": "medium", "confidence": "medium",
            "what_changed": "ECB cuts.", "mechanism_summary": "Policy move.",
            "beneficiaries": [], "losers": [], "assets_to_watch": [],
            "market_note": "", "market_tickers": [],
            "policy_timing_context": (
                self._POPULATED_BLOCK if with_block else {}
            ),
        }

    def test_json_export_includes_block_when_populated(self) -> None:
        import api as _api
        out = _api._build_event_json_export(self._sample(with_block=True))
        self.assertIn("policy_timing_context", out)
        self.assertEqual(
            out["policy_timing_context"]["policy_key"],
            "ecb_rate_decision_2026_04",
        )
        self.assertEqual(out["policy_timing_context"]["status"], "effective")

    def test_json_export_emits_canonical_empty_shape_when_absent(self) -> None:
        import api as _api
        out = _api._build_event_json_export(self._sample(with_block=False))
        block = out["policy_timing_context"]
        self.assertIsNone(block["policy_key"])
        self.assertIsNone(block["status"])
        self.assertEqual(block["source"], "")

    def test_markdown_memo_renders_section(self) -> None:
        import api as _api
        md = _api._build_event_markdown_memo(self._sample(with_block=True))
        self.assertIn("## Policy Timing", md)
        self.assertIn("ecb_rate_decision_2026_04", md)
        self.assertIn("`effective`", md)
        self.assertIn("ECB", md)

    def test_markdown_memo_omits_section_when_empty(self) -> None:
        import api as _api
        md = _api._build_event_markdown_memo(self._sample(with_block=False))
        self.assertNotIn("Policy Timing", md)

    def test_text_memo_renders_block(self) -> None:
        import api as _api
        txt = _api._build_event_text_memo(self._sample(with_block=True))
        self.assertIn("POLICY TIMING", txt)
        self.assertIn("ecb_rate_decision_2026_04", txt)
        self.assertIn("effective", txt)

    def test_research_memo_renders_section(self) -> None:
        import api as _api
        md = _api._build_event_research_memo(self._sample(with_block=True))
        self.assertIn("## Policy Timing", md)
        self.assertIn("ecb_rate_decision_2026_04", md)


if __name__ == "__main__":
    unittest.main()
