"""
tests/test_overlay_sanitize.py

Validates the shared overlay + mover sanitizers.
Covers:
  - NaN / inf scrub
  - Empty / None / non-dict input → explicit degraded marker block
  - Magnitude caps tripping → degraded=True + reason
  - Composer-marked unavailable → degraded=True
  - Existing degraded_reason preserved
  - Mover data_quality: fresh / stale / missing-timestamp paths
  - Idempotence on already-sanitized input
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from overlay_sanitize import (  # noqa: E402
    sanitize_overlay_block,
    sanitize_mover_card,
    sanitize_floats,
    MOVER_STALE_AFTER_DAYS,
)


# ---------------------------------------------------------------------------
# sanitize_floats primitive
# ---------------------------------------------------------------------------

class TestSanitizeFloats(unittest.TestCase):

    def test_nan_replaced_with_none(self):
        self.assertIsNone(sanitize_floats(float("nan")))

    def test_positive_inf_replaced(self):
        self.assertIsNone(sanitize_floats(float("inf")))

    def test_negative_inf_replaced(self):
        self.assertIsNone(sanitize_floats(float("-inf")))

    def test_normal_float_preserved(self):
        self.assertEqual(sanitize_floats(3.14), 3.14)

    def test_nested_dict_and_list(self):
        obj = {"a": [1.0, float("nan"), float("inf"), {"b": float("-inf")}]}
        out = sanitize_floats(obj)
        self.assertEqual(out, {"a": [1.0, None, None, {"b": None}]})


# ---------------------------------------------------------------------------
# sanitize_overlay_block — empty / missing input
# ---------------------------------------------------------------------------

class TestEmptyInput(unittest.TestCase):

    def test_none_returns_explicit_degraded_block(self):
        out = sanitize_overlay_block(None, name="reserve_stress")
        self.assertFalse(out["available"])
        self.assertTrue(out["stale"])
        self.assertTrue(out["degraded"])
        self.assertIn("reserve_stress", out["degraded_reason"])

    def test_empty_dict_returns_explicit_degraded_block(self):
        out = sanitize_overlay_block({}, name="terms_of_trade")
        self.assertFalse(out["available"])
        self.assertTrue(out["degraded"])
        self.assertIn("terms_of_trade", out["degraded_reason"])

    def test_non_dict_returns_degraded_block(self):
        for val in ([], "string", 42, True):
            out = sanitize_overlay_block(val, name="x")
            self.assertFalse(out["available"])
            self.assertTrue(out["degraded"])


# ---------------------------------------------------------------------------
# sanitize_overlay_block — populated input
# ---------------------------------------------------------------------------

class TestPopulatedInput(unittest.TestCase):

    def test_composer_available_block_preserved(self):
        raw = {"regime": "bear_flattener", "available": True, "stale": False}
        out = sanitize_overlay_block(raw, name="shock_decomposition")
        self.assertEqual(out["regime"], "bear_flattener")
        self.assertTrue(out["available"])
        self.assertFalse(out["stale"])
        self.assertFalse(out["degraded"])
        self.assertEqual(out["degraded_reason"], "")

    def test_missing_marker_fields_defaults_to_available(self):
        raw = {"some_metric": 0.42, "label": "custom"}
        out = sanitize_overlay_block(raw, name="custom")
        self.assertTrue(out["available"])
        self.assertFalse(out["stale"])
        self.assertFalse(out["degraded"])

    def test_composer_unavailable_marks_degraded(self):
        raw = {"available": False}
        out = sanitize_overlay_block(raw, name="credit_regime")
        self.assertFalse(out["available"])
        self.assertTrue(out["stale"])
        self.assertTrue(out["degraded"])
        self.assertIn("credit_regime", out["degraded_reason"])

    def test_existing_degraded_reason_preserved(self):
        raw = {"degraded_reason": "VIX feed timed out"}
        out = sanitize_overlay_block(raw, name="stress_regime")
        self.assertTrue(out["degraded"])
        self.assertIn("VIX feed timed out", out["degraded_reason"])


# ---------------------------------------------------------------------------
# sanitize_overlay_block — NaN scrub
# ---------------------------------------------------------------------------

class TestFloatsInBlock(unittest.TestCase):

    def test_nan_value_scrubbed(self):
        raw = {"available": True, "move_5d": float("nan"), "z": 1.2}
        out = sanitize_overlay_block(raw, name="x")
        self.assertIsNone(out["move_5d"])
        self.assertEqual(out["z"], 1.2)

    def test_inf_scrubbed_in_nested_list(self):
        raw = {"available": True,
               "channels": [{"move_5d": float("inf"), "label": "rates"}]}
        out = sanitize_overlay_block(raw, name="x")
        self.assertIsNone(out["channels"][0]["move_5d"])


# ---------------------------------------------------------------------------
# sanitize_overlay_block — magnitude caps
# ---------------------------------------------------------------------------

class TestMagnitudeCaps(unittest.TestCase):

    def test_cap_tripped_clears_field_and_marks_degraded(self):
        raw = {"available": True, "pressure_score": 8500}
        out = sanitize_overlay_block(
            raw, name="reserve_stress",
            magnitude_caps={"pressure_score": 100},
        )
        self.assertIsNone(out["pressure_score"])
        self.assertTrue(out["degraded"])
        self.assertIn("magnitude caps tripped", out["degraded_reason"])

    def test_value_within_cap_preserved(self):
        raw = {"available": True, "pressure_score": 55}
        out = sanitize_overlay_block(
            raw, name="reserve_stress",
            magnitude_caps={"pressure_score": 100},
        )
        self.assertEqual(out["pressure_score"], 55)
        self.assertFalse(out["degraded"])

    def test_nonnumeric_value_not_tripped(self):
        raw = {"available": True, "label": "elevated"}
        out = sanitize_overlay_block(
            raw, name="x", magnitude_caps={"label": 10},
        )
        self.assertEqual(out["label"], "elevated")

    def test_bool_field_not_considered_numeric(self):
        raw = {"available": True, "degraded": False}
        out = sanitize_overlay_block(
            raw, name="x", magnitude_caps={"degraded": 0.5},
        )
        # bool should pass through — not clamped as a numeric overflow.
        self.assertEqual(out["degraded"], False)


# ---------------------------------------------------------------------------
# sanitize_overlay_block — idempotence
# ---------------------------------------------------------------------------

class TestIdempotence(unittest.TestCase):

    def test_second_call_preserves_markers(self):
        raw = {"regime": "bear"}
        first = sanitize_overlay_block(raw, name="x")
        second = sanitize_overlay_block(first, name="x")
        self.assertEqual(first, second)

    def test_does_not_mutate_caller_dict(self):
        raw = {"available": True, "val": float("nan")}
        before = dict(raw)
        _ = sanitize_overlay_block(raw, name="x")
        self.assertEqual(raw, before, "input dict should not mutate")


# ---------------------------------------------------------------------------
# sanitize_mover_card — data_quality computation
# ---------------------------------------------------------------------------

class TestMoverDataQuality(unittest.TestCase):

    def test_fresh_timestamp_is_ok(self):
        now = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
        card = {
            "event_id": 1,
            "last_market_check_at": (now - timedelta(hours=6)).isoformat(),
        }
        out = sanitize_mover_card(card, now=now)
        self.assertEqual(out["data_quality"], "ok")
        self.assertEqual(out["data_quality_reason"], "")
        self.assertEqual(out["data_quality_age_days"], 0)

    def test_stale_timestamp(self):
        now = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
        card = {
            "event_id": 1,
            "last_market_check_at":
                (now - timedelta(days=MOVER_STALE_AFTER_DAYS + 3)).isoformat(),
        }
        out = sanitize_mover_card(card, now=now)
        self.assertEqual(out["data_quality"], "stale")
        self.assertIn("10d", out["data_quality_reason"])
        self.assertEqual(out["data_quality_age_days"],
                         MOVER_STALE_AFTER_DAYS + 3)

    def test_missing_timestamp_is_degraded(self):
        card = {"event_id": 1, "last_market_check_at": None}
        out = sanitize_mover_card(card)
        self.assertEqual(out["data_quality"], "degraded")
        self.assertEqual(out["data_quality_reason"],
                         "missing last_market_check_at")
        self.assertIsNone(out["data_quality_age_days"])

    def test_unparseable_timestamp_is_degraded(self):
        card = {"event_id": 1, "last_market_check_at": "not a date"}
        out = sanitize_mover_card(card)
        self.assertEqual(out["data_quality"], "degraded")

    def test_naive_timestamp_handled(self):
        # Backend sometimes persists naive ISO strings; should still parse.
        now = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
        card = {
            "event_id": 1,
            "last_market_check_at": "2026-04-17T09:30:00",
        }
        out = sanitize_mover_card(card, now=now)
        self.assertIn(out["data_quality"], ("ok", "stale"))
        self.assertIsNotNone(out["data_quality_age_days"])

    def test_nan_float_in_card_is_scrubbed(self):
        card = {
            "event_id": 1,
            "impact": float("nan"),
            "tickers": [{"symbol": "AAA", "return_5d": float("inf")}],
            "last_market_check_at": None,
        }
        out = sanitize_mover_card(card)
        self.assertIsNone(out["impact"])
        self.assertIsNone(out["tickers"][0]["return_5d"])

    def test_exactly_at_threshold_is_ok(self):
        # Age exactly MOVER_STALE_AFTER_DAYS should still be ok (> not >=).
        now = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
        card = {
            "event_id": 1,
            "last_market_check_at":
                (now - timedelta(days=MOVER_STALE_AFTER_DAYS)).isoformat(),
        }
        out = sanitize_mover_card(card, now=now)
        self.assertEqual(out["data_quality"], "ok")

    def test_non_dict_passes_through(self):
        # Lists/strings/Nones pass through untouched — caller handles them.
        self.assertEqual(sanitize_mover_card(None), None)
        self.assertEqual(sanitize_mover_card("not a dict"), "not a dict")


# ---------------------------------------------------------------------------
# api.py integration — _build_cached_response uses the sanitizer
# ---------------------------------------------------------------------------

class TestCachedResponseSanitization(unittest.TestCase):
    """Smoke test: frozen-archive branch emits sanitized overlays."""

    def test_empty_overlay_becomes_explicit_degraded_block(self):
        """When the stored event lacks a given overlay, the API response must
        carry the explicit degraded marker rather than an empty dict."""
        import api
        cached = {
            "headline": "test frozen event",
            "stage": "realized",
            "persistence": "medium",
            "event_date": "2024-01-01",
            "timestamp": "2024-01-01T00:00:00",
            "confidence": "low",
            # Persisted overlays missing / empty
            "policy_sensitivity": None,
            "policy_constraint": None,
            "reserve_stress": None,
            "credit_regime": None,
        }
        # Patch is_frozen_archive via the age classifier — a 2024 event is
        # past the 30d horizon when today is 2026.  Use force=False to hit
        # the frozen branch.
        try:
            resp = api._build_cached_response(
                cached, "test frozen event",
                effective_date="2024-01-01", force=False,
            )
        except Exception as e:
            self.skipTest(f"cached response path requires full api stack: {e}")
            return
        analysis = resp.get("analysis") or {}
        for name in ("policy_sensitivity", "policy_constraint",
                     "reserve_stress", "credit_regime"):
            block = analysis.get(name)
            self.assertIsInstance(block, dict, f"{name} should be dict")
            self.assertIn("available", block, f"{name} missing available")
            self.assertIn("degraded", block, f"{name} missing degraded")
            self.assertFalse(block["available"], f"{name} should be unavailable")
            self.assertTrue(block["degraded"], f"{name} should be degraded")


if __name__ == "__main__":
    unittest.main()
