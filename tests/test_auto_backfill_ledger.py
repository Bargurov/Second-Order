"""Tests for auto_backfill_ledger.

The ledger is a pure, in-memory accountant for LLM-call spend against a
daily cap.  It owns no I/O — no DB writes, no network, no scheduler — so
these tests stay fully hermetic and use an injected clock to drive
calendar-day rollover deterministically.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from auto_backfill_ledger import AutoBackfillLedger


def _dt(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


class CanSpendTests(unittest.TestCase):
    def test_allowed_when_under_cap(self):
        led = AutoBackfillLedger(daily_cap=10)
        d = led.can_spend(3, now=_dt(2026, 5, 5))
        self.assertTrue(d.allowed)
        self.assertEqual(d.reason, "allowed")
        self.assertEqual(d.requested, 3)
        self.assertEqual(d.used, 0)
        self.assertEqual(d.remaining, 10)
        self.assertEqual(d.daily_cap, 10)
        self.assertEqual(d.day, "2026-05-05")

    def test_can_spend_does_not_mutate(self):
        led = AutoBackfillLedger(daily_cap=10)
        led.can_spend(4, now=_dt(2026, 5, 5))
        led.can_spend(4, now=_dt(2026, 5, 5))
        # Used should still be zero after only can_spend calls.
        d = led.can_spend(10, now=_dt(2026, 5, 5))
        self.assertTrue(d.allowed)
        self.assertEqual(d.used, 0)
        self.assertEqual(d.remaining, 10)

    def test_zero_requested_is_allowed(self):
        led = AutoBackfillLedger(daily_cap=5)
        d = led.can_spend(0, now=_dt(2026, 5, 5))
        self.assertTrue(d.allowed)
        self.assertEqual(d.reason, "allowed")


class ReserveCallsTests(unittest.TestCase):
    def test_same_day_accumulation(self):
        led = AutoBackfillLedger(daily_cap=10)
        d1 = led.reserve_calls(3, now=_dt(2026, 5, 5, 9))
        d2 = led.reserve_calls(4, now=_dt(2026, 5, 5, 14))

        self.assertTrue(d1.allowed)
        self.assertEqual(d1.used, 3)
        self.assertEqual(d1.remaining, 7)

        self.assertTrue(d2.allowed)
        self.assertEqual(d2.used, 7)
        self.assertEqual(d2.remaining, 3)

    def test_exact_cap_allowed(self):
        led = AutoBackfillLedger(daily_cap=10)
        led.reserve_calls(6, now=_dt(2026, 5, 5))
        d = led.reserve_calls(4, now=_dt(2026, 5, 5))
        self.assertTrue(d.allowed)
        self.assertEqual(d.reason, "allowed")
        self.assertEqual(d.used, 10)
        self.assertEqual(d.remaining, 0)

    def test_full_cap_in_single_call(self):
        led = AutoBackfillLedger(daily_cap=8)
        d = led.reserve_calls(8, now=_dt(2026, 5, 5))
        self.assertTrue(d.allowed)
        self.assertEqual(d.used, 8)
        self.assertEqual(d.remaining, 0)

    def test_daily_cap_exceeded_blocks_reservation(self):
        led = AutoBackfillLedger(daily_cap=10)
        led.reserve_calls(7, now=_dt(2026, 5, 5))
        d = led.reserve_calls(4, now=_dt(2026, 5, 5))
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "daily_cap_exceeded")
        # Failed reservation must not consume budget.
        self.assertEqual(d.used, 7)
        self.assertEqual(d.remaining, 3)

    def test_can_spend_signals_cap_before_reserve(self):
        led = AutoBackfillLedger(daily_cap=5)
        led.reserve_calls(5, now=_dt(2026, 5, 5))
        d = led.can_spend(1, now=_dt(2026, 5, 5))
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "daily_cap_exceeded")
        self.assertEqual(d.remaining, 0)

    def test_zero_request_does_not_change_used(self):
        led = AutoBackfillLedger(daily_cap=5)
        led.reserve_calls(2, now=_dt(2026, 5, 5))
        d = led.reserve_calls(0, now=_dt(2026, 5, 5))
        self.assertTrue(d.allowed)
        self.assertEqual(d.used, 2)
        self.assertEqual(d.remaining, 3)


class CalendarRolloverTests(unittest.TestCase):
    def test_next_day_reset(self):
        led = AutoBackfillLedger(daily_cap=10)
        led.reserve_calls(8, now=_dt(2026, 5, 5, 23))
        # New calendar day: counter resets, full cap is available again.
        d = led.reserve_calls(10, now=_dt(2026, 5, 6, 0))
        self.assertTrue(d.allowed)
        self.assertEqual(d.used, 10)
        self.assertEqual(d.remaining, 0)
        self.assertEqual(d.day, "2026-05-06")

    def test_can_spend_observes_day_rollover(self):
        led = AutoBackfillLedger(daily_cap=4)
        led.reserve_calls(4, now=_dt(2026, 5, 5))
        # Same day → cap exceeded.
        same = led.can_spend(1, now=_dt(2026, 5, 5))
        self.assertFalse(same.allowed)
        # Following day → fresh budget.
        nxt = led.can_spend(4, now=_dt(2026, 5, 6))
        self.assertTrue(nxt.allowed)
        self.assertEqual(nxt.used, 0)
        self.assertEqual(nxt.remaining, 4)

    def test_skipping_days_still_resets_once(self):
        led = AutoBackfillLedger(daily_cap=3)
        led.reserve_calls(3, now=_dt(2026, 5, 5))
        d = led.reserve_calls(3, now=_dt(2026, 5, 12))
        self.assertTrue(d.allowed)
        self.assertEqual(d.used, 3)
        self.assertEqual(d.day, "2026-05-12")


class InvalidInputTests(unittest.TestCase):
    def test_negative_cap_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            AutoBackfillLedger(daily_cap=-1)

    def test_non_integer_cap_rejected(self):
        with self.assertRaises(TypeError):
            AutoBackfillLedger(daily_cap=1.5)  # type: ignore[arg-type]

    def test_negative_request_returns_invalid_reason(self):
        led = AutoBackfillLedger(daily_cap=10)
        d = led.can_spend(-1, now=_dt(2026, 5, 5))
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "invalid_request")

    def test_negative_request_does_not_reserve(self):
        led = AutoBackfillLedger(daily_cap=10)
        d = led.reserve_calls(-3, now=_dt(2026, 5, 5))
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "invalid_request")
        # Used must remain zero.
        snap = led.snapshot(now=_dt(2026, 5, 5))
        self.assertEqual(snap.used, 0)

    def test_non_integer_request_returns_invalid_reason(self):
        led = AutoBackfillLedger(daily_cap=10)
        d = led.can_spend(2.5, now=_dt(2026, 5, 5))  # type: ignore[arg-type]
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "invalid_request")

    def test_zero_cap_blocks_positive_requests(self):
        led = AutoBackfillLedger(daily_cap=0)
        d = led.reserve_calls(1, now=_dt(2026, 5, 5))
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "daily_cap_exceeded")
        # Zero request is still allowed under a zero cap.
        z = led.reserve_calls(0, now=_dt(2026, 5, 5))
        self.assertTrue(z.allowed)


class DeterministicClockTests(unittest.TestCase):
    def test_injected_now_drives_decision_day(self):
        led = AutoBackfillLedger(daily_cap=2)
        d = led.reserve_calls(2, now=_dt(2027, 1, 1))
        self.assertEqual(d.day, "2027-01-01")
        self.assertTrue(d.allowed)

    def test_explicit_clock_argument_overrides_default(self):
        # Default clock would be utcnow; test verifies that passing `now`
        # makes the result depend only on the injected datetime.
        fixed = _dt(2026, 7, 4)
        led = AutoBackfillLedger(daily_cap=1)
        a = led.reserve_calls(1, now=fixed)
        b = led.can_spend(1, now=fixed)
        self.assertTrue(a.allowed)
        self.assertFalse(b.allowed)
        self.assertEqual(b.day, "2026-07-04")


if __name__ == "__main__":
    unittest.main()
