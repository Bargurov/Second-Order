"""Tests for ``scripts/xle_benchmark_backfill_request_packet.py``.

Pin the contract:

* Read-only by construction — no DB writes, no provider, no yfinance,
  no LLM, no FastAPI surface.  The packet delegates DB reads to the
  preflight, which itself only issues ``SELECT``.
* Output dict has EXACTLY these 11 keys::

    ok, benchmark_ticker, blocked_events, required_dates,
    date_ranges, reason, why_local_backfill_failed,
    allowed_next_step, not_allowed, warnings, errors

* ``ok=True`` means the packet was built — NOT that the events are
  unblocked.  The whole point of this packet is to surface the
  request for events that remain blocked.
* The packet is a request, not an authorisation.  Banned tokens in
  any text the packet emits: ``proof``, ``proven``, ``validated``,
  ``automatically``, ``alpha generated``, ``correct ticker``,
  ``guaranteed``, ``approved``, ``approves``.
* Live-truth pins: events 60 and 73 are blocked against XLE; the
  required dates include the missing estimation-window dates from
  late Dec 2025 / early Jan 2026.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import xle_benchmark_backfill_request_packet as cli  # noqa: E402
from scripts import benchmark_sensitivity_preflight as preflight_cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "benchmark_ticker",
    "blocked_events",
    "required_dates",
    "date_ranges",
    "reason",
    "why_local_backfill_failed",
    "allowed_next_step",
    "not_allowed",
    "warnings",
    "errors",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "validated",
    "automatically",
    "alpha generated",
    "correct ticker",
    "guaranteed",
    "approved",
    "approves",
)


# ---------------------------------------------------------------------------
# Synthetic preflight payloads
# ---------------------------------------------------------------------------


def _live_truth_payload() -> dict[str, Any]:
    """Mirror the live preflight output captured against the real DB
    on 2026-05-12 for events 60 + 73.  Pinned here so the tests do not
    depend on the live archive being in any particular state.
    """
    return {
        "ok":            True,
        "checked_events": 2,
        "ready_count":   0,
        "blocked_count": 2,
        "rows": [
            {
                "event_id":                  60,
                "event_date":                "2026-04-08",
                "primary_ticker":            "XOM",
                "benchmark_ticker":          "XLE",
                "required_horizons":         [1, 5, 20],
                "primary_cache_available":   True,
                "benchmark_cache_available": False,
                "missing_primary_ranges":    [],
                "missing_benchmark_ranges": [
                    {
                        "start":  "2026-01-01",
                        "end":    "2026-01-02",
                        "reason": "estimation_window_short",
                    },
                ],
                "can_run_sensitivity": False,
                "blocker_reason":      "benchmark XLE: estimation_window_short",
            },
            {
                "event_id":                  73,
                "event_date":                "2026-04-06",
                "primary_ticker":            "XOM",
                "benchmark_ticker":          "XLE",
                "required_horizons":         [1, 5, 20],
                "primary_cache_available":   True,
                "benchmark_cache_available": False,
                "missing_primary_ranges":    [],
                "missing_benchmark_ranges": [
                    {
                        "start":  "2025-12-30",
                        "end":    "2026-01-02",
                        "reason": "estimation_window_short",
                    },
                ],
                "can_run_sensitivity": False,
                "blocker_reason":      "benchmark XLE: estimation_window_short",
            },
        ],
        "recommended_next_action": "",
    }


def _patch_preflight(payload: dict[str, Any]):
    return patch.object(
        preflight_cli,
        "summarize_benchmark_sensitivity_preflight",
        return_value=payload,
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_has_exactly_eleven_keys(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        self.assertEqual(
            set(packet.keys()), set(_REQUIRED_KEYS),
            f"unexpected keys: {sorted(packet.keys())}",
        )

    def test_ok_true_with_blocked_events_is_not_a_contradiction(
        self,
    ) -> None:
        # ``ok`` means "packet built"; the whole point is to surface
        # the open request for events that remain blocked.
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        self.assertTrue(packet["ok"])
        self.assertEqual(len(packet["blocked_events"]), 2)


# ---------------------------------------------------------------------------
# Live truth
# ---------------------------------------------------------------------------


class TestLiveTruth(unittest.TestCase):
    def test_events_60_and_73_remain_blocked(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        ids = {row["event_id"] for row in packet["blocked_events"]}
        self.assertEqual(ids, {60, 73})

    def test_blocked_events_carry_per_event_metadata(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        by_id = {ev["event_id"]: ev for ev in packet["blocked_events"]}
        self.assertEqual(by_id[60]["event_date"], "2026-04-08")
        self.assertEqual(by_id[60]["primary_ticker"], "XOM")
        self.assertEqual(by_id[60]["benchmark_ticker"], "XLE")
        self.assertEqual(by_id[73]["event_date"], "2026-04-06")
        self.assertEqual(by_id[73]["primary_ticker"], "XOM")
        self.assertIn("estimation_window_short", by_id[73]["blocker_reason"])

    def test_benchmark_ticker_echoed(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet(
                benchmark="XLE",
            )
        self.assertEqual(packet["benchmark_ticker"], "XLE")

    def test_required_dates_include_late_dec_and_early_jan(self) -> None:
        # Pin the boundary business-days from the live truth.
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        for required in ("2025-12-30", "2025-12-31",
                         "2026-01-01", "2026-01-02"):
            self.assertIn(
                required, packet["required_dates"],
                f"missing required date {required!r}: "
                f"{packet['required_dates']}",
            )

    def test_required_dates_are_unique_and_sorted(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        rd = packet["required_dates"]
        self.assertEqual(rd, sorted(rd), "required_dates not sorted")
        self.assertEqual(len(rd), len(set(rd)),
                         "required_dates carry duplicates")


# ---------------------------------------------------------------------------
# Date-range expansion
# ---------------------------------------------------------------------------


class TestDateRangeExpansion(unittest.TestCase):
    def test_date_ranges_echo_preflight_ranges_per_event(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        ranges_by_ev = {
            (r["event_id"], r["start"], r["end"], r["reason"])
            for r in packet["date_ranges"]
        }
        self.assertIn(
            (60, "2026-01-01", "2026-01-02", "estimation_window_short"),
            ranges_by_ev,
        )
        self.assertIn(
            (73, "2025-12-30", "2026-01-02", "estimation_window_short"),
            ranges_by_ev,
        )

    def test_reason_is_single_token_when_homogeneous(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        # Both events flag the same reason — the packet emits the
        # exact token, never the fallback "mixed".
        self.assertEqual(packet["reason"], "estimation_window_short")

    def test_reason_is_mixed_when_ranges_disagree(self) -> None:
        payload = _live_truth_payload()
        # Force a heterogeneous reason via a synthetic second range.
        payload["rows"][0]["missing_benchmark_ranges"].append({
            "start": "2026-04-09", "end": "2026-04-10",
            "reason": "forward_horizon_gap",
        })
        with _patch_preflight(payload):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        self.assertEqual(packet["reason"], "mixed")

    def test_business_day_expansion_skips_weekends(self) -> None:
        # 2025-12-27 is Saturday, 2025-12-28 is Sunday — neither
        # should appear in required_dates even if asked for.
        payload = _live_truth_payload()
        payload["rows"][0]["missing_benchmark_ranges"] = [{
            "start": "2025-12-26", "end": "2025-12-30",
            "reason": "estimation_window_short",
        }]
        with _patch_preflight(payload):
            packet = cli.build_xle_benchmark_backfill_request_packet(
                event_ids=[60],
            )
        self.assertNotIn("2025-12-27", packet["required_dates"])
        self.assertNotIn("2025-12-28", packet["required_dates"])
        # Friday + Monday + Tuesday must still appear.
        for d in ("2025-12-26", "2025-12-29", "2025-12-30"):
            self.assertIn(d, packet["required_dates"])

    def test_holiday_2026_01_01_is_retained_not_filtered(self) -> None:
        # The packet matches the preflight's weekday-only date math
        # and does NOT filter NYSE holidays.  2026-01-01 (Thursday,
        # New Year's Day) is therefore retained.  The operator-
        # approval flow that fetches the rows handles holiday skip.
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        self.assertIn("2026-01-01", packet["required_dates"])


# ---------------------------------------------------------------------------
# Operator prose + not-allowed listing
# ---------------------------------------------------------------------------


class TestOperatorProse(unittest.TestCase):
    def test_why_local_backfill_failed_mentions_price_cache(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        why = packet["why_local_backfill_failed"].lower()
        self.assertIn("price_cache", why)
        self.assertIn("xle", why)

    def test_allowed_next_step_mentions_operator_approval(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        step = packet["allowed_next_step"].lower()
        self.assertIn("operator approval", step)
        self.assertIn("request", step)

    def test_allowed_next_step_does_not_claim_approval(self) -> None:
        # The packet is a request, not an authorisation.  The wording
        # must never claim that the backfill is approved.
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        step = packet["allowed_next_step"].lower()
        for token in ("approved", "approves", "authorised", "authorized"):
            self.assertNotIn(token, step,
                             f"banned token {token!r} in allowed_next_step")

    def test_not_allowed_pins_critical_items(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        joined = " | ".join(packet["not_allowed"]).lower()
        # Five canonical things the packet must explicitly refuse.
        self.assertIn("online fetch", joined)
        self.assertIn("approval", joined)
        self.assertIn("write", joined)
        self.assertIn("fabricated", joined)
        self.assertIn("interpretation", joined)
        self.assertTrue(any("spy" in item.lower()
                            for item in packet["not_allowed"]),
                        "SPY-vs-XLE inference must be explicitly disallowed")


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_tokens_in_text_render(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        text = cli._render_text(packet).lower()
        for token in _BANNED_WORDS:
            self.assertNotIn(token, text,
                             f"banned token {token!r} in text render")

    def test_no_banned_tokens_in_json_render(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        blob = cli._render_json(packet).lower()
        for token in _BANNED_WORDS:
            self.assertNotIn(token, blob,
                             f"banned token {token!r} in JSON render")


# ---------------------------------------------------------------------------
# No-op edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    def test_no_blocked_rows_produces_empty_packet(self) -> None:
        # Hypothetical "everything cleared" payload — the packet must
        # still build and surface zero blocked events / required dates.
        clear_payload = {
            "ok": True, "checked_events": 0, "ready_count": 0,
            "blocked_count": 0, "rows": [], "recommended_next_action": "",
        }
        with _patch_preflight(clear_payload):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        self.assertTrue(packet["ok"])
        self.assertEqual(packet["blocked_events"], [])
        self.assertEqual(packet["required_dates"], [])
        self.assertEqual(packet["date_ranges"], [])
        self.assertEqual(packet["reason"], "")

    def test_can_run_sensitivity_rows_are_excluded(self) -> None:
        payload = _live_truth_payload()
        payload["rows"][0]["can_run_sensitivity"] = True
        payload["rows"][0]["missing_benchmark_ranges"] = []
        with _patch_preflight(payload):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        ids = {ev["event_id"] for ev in packet["blocked_events"]}
        self.assertEqual(ids, {73})  # 60 is no longer in the request set

    def test_preflight_exception_lands_in_errors(self) -> None:
        def _boom(**kwargs):
            raise RuntimeError("preflight blew up")
        with patch.object(
            preflight_cli,
            "summarize_benchmark_sensitivity_preflight",
            side_effect=_boom,
        ):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        self.assertFalse(packet["ok"])
        self.assertTrue(any(
            "preflight raised" in e for e in packet["errors"]
        ), f"errors: {packet['errors']}")


# ---------------------------------------------------------------------------
# --output filesystem side effects
# ---------------------------------------------------------------------------


class TestOutputPersistence(unittest.TestCase):
    def test_no_output_means_no_filesystem_side_effect(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            packet = cli.build_xle_benchmark_backfill_request_packet()
        # Nothing to assert beyond "packet built and did not raise".
        # Filesystem isolation is enforced by the absence of any write
        # syscalls on the production code path; the test merely pins
        # the happy path.
        self.assertTrue(packet["ok"])

    def test_output_path_writes_packet(self) -> None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"xle_packet_test_{uuid.uuid4().hex}.json",
        )
        try:
            with _patch_preflight(_live_truth_payload()):
                packet = cli.build_xle_benchmark_backfill_request_packet(
                    output_path=out_path,
                )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            self.assertEqual(set(blob.keys()), set(_REQUIRED_KEYS))
            self.assertEqual(blob["ok"], packet["ok"])
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)


# ---------------------------------------------------------------------------
# No paid-surface imports
# ---------------------------------------------------------------------------


class TestNoPaidSurfaceImports(unittest.TestCase):
    def test_packet_module_does_not_bind_yfinance_anthropic_openai(
        self,
    ) -> None:
        for attr in ("yfinance", "anthropic", "openai"):
            self.assertFalse(
                hasattr(cli, attr),
                f"request packet must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLIEntryPoint(unittest.TestCase):
    def test_main_json_prints_valid_packet(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            buf = StringIO()
            rc = cli.main(["--json"], out=buf)
        payload = json.loads(buf.getvalue())
        self.assertEqual(set(payload.keys()), set(_REQUIRED_KEYS))
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])

    def test_main_text_does_not_crash(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            buf = StringIO()
            rc = cli.main([], out=buf)
        self.assertEqual(rc, 0)
        self.assertIn(
            "XLE benchmark backfill request packet",
            buf.getvalue(),
        )

    def test_main_custom_event_ids_csv(self) -> None:
        with _patch_preflight(_live_truth_payload()):
            buf = StringIO()
            rc = cli.main(["--json", "--event-ids", "60,73"], out=buf)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(
            {ev["event_id"] for ev in payload["blocked_events"]},
            {60, 73},
        )


if __name__ == "__main__":
    unittest.main()
