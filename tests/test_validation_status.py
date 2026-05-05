"""tests/test_validation_status.py

Pure-function tests for ``validation_status.score_validation_status``.

Covers:
  * §5 of docs/validation_status_design.md — edge-case truth table
  * §7.2 — time-awareness (now param honoured, default works, future dates)
  * §7.3 — transition behaviour of the pure function
  * §7.4 — pending-vs-unresolved discriminator
  * Return-shape contract (status / reason / ratio / counts / event_age_days)

No DB, no network. Fixtures are dict literals.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from validation_status import score_validation_status


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

# A fixed reference clock so tests don't depend on wall-clock time.
NOW = datetime(2026, 5, 5, 12, 0, 0)
PENDING_MAX_DAYS = 7  # Mirrors design §4.4; helper cross-checks the constant.


def _date_n_days_ago(now: datetime, n: int) -> str:
    return (now - timedelta(days=n)).date().isoformat()


def _ticker(
    symbol: str = "AAPL",
    *,
    direction_tag: str | None = None,
    role: str | None = None,
    return_1d: float | None = None,
) -> dict:
    """Build a minimal ticker dict with only the fields the scorer reads."""
    out: dict = {"symbol": symbol}
    if direction_tag is not None:
        out["direction_tag"] = direction_tag
    if role is not None:
        out["role"] = role
    if return_1d is not None:
        out["return_1d"] = return_1d
    return out


def _event(
    *,
    event_date: str | None = None,
    timestamp: str | None = None,
    market_tickers: list | None = None,
    mechanism_summary: str | None = None,
    what_changed: str | None = None,
    mechanism_family: str | None = None,
) -> dict:
    """Build a minimal event dict.  Only fields the scorer reads."""
    out: dict = {}
    if event_date is not None:
        out["event_date"] = event_date
    if timestamp is not None:
        out["timestamp"] = timestamp
    if market_tickers is not None:
        out["market_tickers"] = market_tickers
    if mechanism_summary is not None:
        out["mechanism_summary"] = mechanism_summary
    if what_changed is not None:
        out["what_changed"] = what_changed
    if mechanism_family is not None:
        out["mechanism_family"] = mechanism_family
    return out


# ---------------------------------------------------------------------------
# §5 — Majority rule (existing behaviour preserved verbatim)
# ---------------------------------------------------------------------------


class TestMajorityRule(unittest.TestCase):
    """Validates and contradicts come from directional tag counts."""

    def test_supports_majority_validates(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[
                _ticker("AAPL", direction_tag="supports_thesis"),
                _ticker("MSFT", direction_tag="supports_thesis"),
                _ticker("TSLA", direction_tag="supports_thesis"),
                _ticker("F",    direction_tag="contradicts_thesis"),
            ],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "validated")
        self.assertEqual(out["counts"]["supporting"], 3)
        self.assertEqual(out["counts"]["contradicting"], 1)
        self.assertAlmostEqual(out["ratio"], 0.75)

    def test_tie_goes_to_contradicted(self):
        # §5: supports == contradicts → contradicted (existing rule, preserved)
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[
                _ticker("AAPL", direction_tag="supports_thesis"),
                _ticker("MSFT", direction_tag="supports_thesis"),
                _ticker("TSLA", direction_tag="contradicts_thesis"),
                _ticker("F",    direction_tag="contradicts_thesis"),
            ],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "contradicted")
        self.assertAlmostEqual(out["ratio"], 0.5)

    def test_contradicts_majority_contradicts(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[
                _ticker("AAPL", direction_tag="supports_thesis"),
                _ticker("MSFT", direction_tag="contradicts_thesis"),
                _ticker("TSLA", direction_tag="contradicts_thesis"),
                _ticker("F",    direction_tag="contradicts_thesis"),
            ],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "contradicted")
        self.assertAlmostEqual(out["ratio"], 0.25)

    def test_pure_contradicts_contradicts(self):
        # Zero supports, all contradicts — still contradicted.
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[
                _ticker("MSFT", direction_tag="contradicts_thesis"),
                _ticker("TSLA", direction_tag="contradicts_thesis"),
                _ticker("F",    direction_tag="contradicts_thesis"),
            ],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "contradicted")
        self.assertEqual(out["ratio"], 0.0)


# ---------------------------------------------------------------------------
# §5 — All-neutral / unknown-prefix tags
# ---------------------------------------------------------------------------


class TestNeutralTags(unittest.TestCase):
    def test_all_neutral_tags_unresolved(self):
        # Tag classifier ran and abstained — not a wait condition (§5).
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[
                _ticker("AAPL", direction_tag="neutral"),
                _ticker("MSFT", direction_tag="needs more evidence"),
                _ticker("TSLA", direction_tag="pending"),
            ],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "unresolved")
        self.assertEqual(out["counts"]["tagged_tickers"], 3)
        self.assertEqual(out["counts"]["directional"], 0)


# ---------------------------------------------------------------------------
# §5 + §7.4 — Pending vs unresolved discriminator
# ---------------------------------------------------------------------------


class TestPendingDiscriminator(unittest.TestCase):
    def test_no_tickers_fresh_with_thesis_pending(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[],
            mechanism_summary="Fed signals two rate cuts; risk assets rally.",
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "pending")

    def test_no_tickers_fresh_no_thesis_unresolved(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "unresolved")

    def test_no_tickers_archived_unresolved(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 60),
            market_tickers=[],
            mechanism_summary="Fed signals two rate cuts; risk assets rally.",
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "unresolved")

    def test_tickers_no_tags_fresh_role_present_pending(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 1),
            market_tickers=[
                _ticker("AAPL", role="beneficiary"),
                _ticker("F",    role="loser"),
            ],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "pending")

    def test_tickers_no_tags_fresh_1d_return_present_pending(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 1),
            market_tickers=[
                _ticker("AAPL", return_1d=0.5),
            ],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "pending")

    def test_tickers_no_tags_fresh_no_discriminator_unresolved(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 1),
            market_tickers=[
                _ticker("AAPL"),  # no tag, no role, no 1d
            ],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "unresolved")

    def test_tickers_no_tags_archived_unresolved(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 14),
            market_tickers=[
                _ticker("AAPL", role="beneficiary", return_1d=0.5),
            ],
            mechanism_summary="thesis present",
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "unresolved")


# ---------------------------------------------------------------------------
# §5 — Low-information event (no thesis, no role, no 1d, no tags) — unresolved
# ---------------------------------------------------------------------------


class TestLowInformation(unittest.TestCase):
    def test_low_info_event_unresolved(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[_ticker("AAPL")],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "unresolved")


# ---------------------------------------------------------------------------
# §5 + §7.2 — Time awareness
# ---------------------------------------------------------------------------


class TestTimeAwareness(unittest.TestCase):
    def test_pending_flips_to_unresolved_when_now_advances(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[_ticker("AAPL", role="beneficiary")],
            mechanism_summary="thesis",
        )
        # Within window → pending.
        out_young = score_validation_status(ev, now=NOW)
        self.assertEqual(out_young["status"], "pending")
        # Advance now past PENDING_MAX_DAYS → flips to unresolved.
        later = NOW + timedelta(days=PENDING_MAX_DAYS + 2)
        out_old = score_validation_status(ev, now=later)
        self.assertEqual(out_old["status"], "unresolved")

    def test_default_now_does_not_raise(self):
        # Use an event dated yesterday so default-now won't put it past 7d
        # (default now = wall clock, but the event is fresh).
        today_iso = datetime.now().date().isoformat()
        ev = _event(
            event_date=today_iso,
            market_tickers=[_ticker("AAPL", role="beneficiary")],
            mechanism_summary="thesis",
        )
        out = score_validation_status(ev)  # no now kwarg
        # Should resolve to one of the four labels — never raise.
        self.assertIn(
            out["status"],
            ("validated", "contradicted", "unresolved", "pending"),
        )

    def test_future_dated_event_clamps_to_age_zero(self):
        ev = _event(
            event_date=(NOW + timedelta(days=3)).date().isoformat(),
            market_tickers=[_ticker("AAPL", role="beneficiary")],
            mechanism_summary="thesis",
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["event_age_days"], 0)
        self.assertEqual(out["status"], "pending")


# ---------------------------------------------------------------------------
# §5 — Missing/unparsable anchor → unresolved (legacy)
# ---------------------------------------------------------------------------


class TestLegacyAnchor(unittest.TestCase):
    def test_no_event_date_no_timestamp_unresolved(self):
        ev = _event(
            market_tickers=[_ticker("AAPL", role="beneficiary")],
            mechanism_summary="thesis",
        )
        out = score_validation_status(ev, now=NOW)
        # Cannot evaluate the pending window without an anchor — do not
        # optimistically pending (§5).
        self.assertEqual(out["status"], "unresolved")

    def test_unparsable_event_date_unresolved(self):
        ev = _event(
            event_date="not-a-date",
            timestamp="also-not-a-date",
            market_tickers=[_ticker("AAPL", role="beneficiary")],
            mechanism_summary="thesis",
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "unresolved")

    def test_falls_back_to_timestamp_when_event_date_missing(self):
        ev = _event(
            timestamp=(NOW.replace(hour=10)).isoformat(),
            market_tickers=[_ticker("AAPL", role="beneficiary")],
            mechanism_summary="thesis",
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["event_age_days"], 0)
        self.assertEqual(out["status"], "pending")


# ---------------------------------------------------------------------------
# §7.3 — Transitions of the pure function under input deltas
# ---------------------------------------------------------------------------


class TestTransitionsPureFunction(unittest.TestCase):
    def test_pending_to_validated_when_supports_arrive(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[_ticker("AAPL", role="beneficiary")],
            mechanism_summary="thesis",
        )
        self.assertEqual(score_validation_status(ev, now=NOW)["status"], "pending")
        # Tags appear later; same event dict updated.
        ev["market_tickers"] = [
            _ticker("AAPL", direction_tag="supports_thesis", role="beneficiary"),
            _ticker("MSFT", direction_tag="supports_thesis"),
        ]
        self.assertEqual(score_validation_status(ev, now=NOW)["status"], "validated")

    def test_pending_to_contradicted_when_contradicts_arrive(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[_ticker("AAPL", role="beneficiary")],
            mechanism_summary="thesis",
        )
        self.assertEqual(score_validation_status(ev, now=NOW)["status"], "pending")
        ev["market_tickers"] = [
            _ticker("AAPL", direction_tag="contradicts_thesis"),
            _ticker("MSFT", direction_tag="contradicts_thesis"),
        ]
        self.assertEqual(score_validation_status(ev, now=NOW)["status"], "contradicted")

    def test_pending_stable_within_window(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[_ticker("AAPL", role="beneficiary")],
            mechanism_summary="thesis",
        )
        for d in (1, 3, PENDING_MAX_DAYS):
            later = NOW + timedelta(days=d)
            self.assertEqual(
                score_validation_status(ev, now=later)["status"],
                "pending",
                f"expected pending at +{d}d",
            )


# ---------------------------------------------------------------------------
# Return-shape contract
# ---------------------------------------------------------------------------


class TestReturnShape(unittest.TestCase):
    """The pure function returns a stable dict shape callers can bind to."""

    REQUIRED_KEYS = {
        "status", "reason", "ratio", "counts",
        "event_age_days", "pending_max_days",
    }
    REQUIRED_COUNT_KEYS = {
        "total_tickers", "tagged_tickers", "directional",
        "supporting", "contradicting",
    }

    def test_shape_validated(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[
                _ticker("AAPL", direction_tag="supports_thesis"),
                _ticker("MSFT", direction_tag="supports_thesis"),
            ],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(set(out.keys()) & self.REQUIRED_KEYS, self.REQUIRED_KEYS)
        self.assertEqual(set(out["counts"].keys()), self.REQUIRED_COUNT_KEYS)
        self.assertIsInstance(out["status"], str)
        self.assertIsInstance(out["reason"], str)
        self.assertGreater(len(out["reason"]), 0)
        self.assertIn(out["status"], ("validated", "contradicted", "unresolved", "pending"))

    def test_ratio_is_none_when_no_directional(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[_ticker("AAPL")],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertIsNone(out["ratio"])

    def test_pending_max_days_matches_design(self):
        ev = _event(event_date=_date_n_days_ago(NOW, 0))
        out = score_validation_status(ev, now=NOW)
        # Design §4.4: PENDING_MAX_DAYS = _WARM_MAX_DAYS = 7.
        self.assertEqual(out["pending_max_days"], 7)

    def test_evidence_counts_consistent(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=[
                _ticker("AAPL", direction_tag="supports_thesis"),
                _ticker("MSFT", direction_tag="contradicts_thesis"),
                _ticker("TSLA", direction_tag="neutral"),
                _ticker("F"),  # untagged
            ],
        )
        out = score_validation_status(ev, now=NOW)
        c = out["counts"]
        self.assertEqual(c["total_tickers"], 4)
        self.assertEqual(c["tagged_tickers"], 3)
        self.assertEqual(c["supporting"], 1)
        self.assertEqual(c["contradicting"], 1)
        self.assertEqual(c["directional"], 2)


# ---------------------------------------------------------------------------
# Robustness — function never raises on malformed input
# ---------------------------------------------------------------------------


class TestRobustness(unittest.TestCase):
    def test_tickers_field_is_not_a_list(self):
        ev = {"event_date": _date_n_days_ago(NOW, 0), "market_tickers": "oops"}
        out = score_validation_status(ev, now=NOW)
        self.assertIn(out["status"], ("unresolved", "pending"))

    def test_ticker_entries_not_dicts(self):
        ev = _event(
            event_date=_date_n_days_ago(NOW, 0),
            market_tickers=["AAPL", 123, None],
        )
        out = score_validation_status(ev, now=NOW)
        self.assertEqual(out["status"], "unresolved")

    def test_event_is_empty_dict(self):
        out = score_validation_status({}, now=NOW)
        # No anchor → unresolved per §5.
        self.assertEqual(out["status"], "unresolved")


if __name__ == "__main__":
    unittest.main()
