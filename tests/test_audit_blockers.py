"""Focused tests for the audit-blocker fixes.

Covers only the changed behaviour from the audit pass:

  * ``validation_outcome`` majority rule (shared by /events + /portfolio)
  * ``/events`` date_from/date_to normalisation
  * ``/events`` paginate-before-decorate when ``validated`` is not set
  * ``/events`` bulk markdown export no longer double-loads
  * ``/events/{id}/refresh-market`` passes the caller's ``force`` flag

All fetches are mocked; no network, no DB writes.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Importing api first resolves the circular dependency between
# routes/*.py modules (each imports api, api imports every router).
import api  # noqa: F401  — import-order fix

from validation_outcome import score_validation_label, score_validation_outcome


# ---------------------------------------------------------------------------
# Shared majority rule
# ---------------------------------------------------------------------------

class TestSharedMajorityRule(unittest.TestCase):
    def test_no_tickers_is_no_data(self):
        self.assertEqual(score_validation_outcome([]), ("no_data", None))

    def test_untagged_tickers_is_no_data(self):
        tickers = [{"symbol": "A"}, {"symbol": "B", "direction_tag": ""}]
        self.assertEqual(score_validation_outcome(tickers), ("no_data", None))

    def test_supporting_majority_is_validated(self):
        tickers = [
            {"direction_tag": "supports up"},
            {"direction_tag": "supports up"},
            {"direction_tag": "contradicts down"},
        ]
        label, ratio = score_validation_outcome(tickers)
        self.assertEqual(label, "validated")
        self.assertAlmostEqual(ratio or 0.0, 2 / 3, places=6)

    def test_contradicting_majority_is_contradicted(self):
        tickers = [
            {"direction_tag": "supports up"},
            {"direction_tag": "contradicts down"},
            {"direction_tag": "contradicts down"},
        ]
        label, ratio = score_validation_outcome(tickers)
        self.assertEqual(label, "contradicted")
        self.assertAlmostEqual(ratio or 0.0, 1 / 3, places=6)

    def test_tie_is_contradicted_matching_events_rule(self):
        """Ties land on 'contradicted' — identical to the existing
        /events behaviour that /portfolio now shares."""
        tickers = [
            {"direction_tag": "supports up"},
            {"direction_tag": "contradicts down"},
        ]
        label, _ = score_validation_outcome(tickers)
        self.assertEqual(label, "contradicted")

    def test_single_supporting_and_two_contradicting_flips_from_old_rule(self):
        """The old /portfolio rule returned 'validated' whenever any
        supporting was present.  Majority rule must flip to
        'contradicted'."""
        tickers = [
            {"direction_tag": "supports up"},
            {"direction_tag": "contradicts down"},
            {"direction_tag": "contradicts down"},
        ]
        label, _ = score_validation_outcome(tickers)
        self.assertEqual(label, "contradicted")

    def test_neutral_only_tags_yield_unresolved(self):
        tickers = [{"direction_tag": "pending"}, {"direction_tag": "neutral"}]
        label, ratio = score_validation_outcome(tickers)
        self.assertEqual(label, "unresolved")
        self.assertEqual(ratio, 0.0)

    def test_non_dict_entries_skipped(self):
        tickers = ["garbage", None, {"direction_tag": "supports up"}]
        label, _ = score_validation_outcome(tickers)
        self.assertEqual(label, "validated")

    def test_label_shorthand_collapses_no_data_to_unresolved(self):
        # /events needs a single string; no_data isn't part of its vocab.
        self.assertEqual(score_validation_label([]), "unresolved")


# ---------------------------------------------------------------------------
# Date-bound normalisation
# ---------------------------------------------------------------------------

class TestDateNormalisation(unittest.TestCase):
    def _normalise(self, value, field="date_from"):
        from routes.events import _normalise_date_bound
        return _normalise_date_bound(value, field=field)

    def test_none_passes_through(self):
        self.assertIsNone(self._normalise(None))

    def test_plain_date_passes(self):
        self.assertEqual(self._normalise("2026-04-20"), "2026-04-20")

    def test_full_iso_datetime_coerced_to_date(self):
        self.assertEqual(
            self._normalise("2026-04-20T10:30:00"), "2026-04-20",
        )

    def test_timezone_aware_datetime_coerced_to_date(self):
        self.assertEqual(
            self._normalise("2026-04-20T10:30:00Z"), "2026-04-20",
        )

    def test_offset_datetime_coerced_to_date(self):
        self.assertEqual(
            self._normalise("2026-04-20T10:30:00+02:00"), "2026-04-20",
        )

    def test_invalid_string_raises_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as cm:
            self._normalise("not-a-date")
        self.assertEqual(cm.exception.status_code, 400)

    def test_empty_string_raises_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self._normalise("  ")


# ---------------------------------------------------------------------------
# /events pagination path — unvalidated decorates only the page
# ---------------------------------------------------------------------------

class TestEventsPaginationPath(unittest.TestCase):
    """When ``validated`` is not set, the route must decorate only the
    rows it actually returns, not the entire filtered archive."""

    def _make_rows(self, n: int) -> list[dict]:
        return [
            {
                "id": i,
                "headline": f"Event {i}",
                "event_date": "2026-04-01",
                "timestamp": "2026-04-01T12:00:00",
                "stage": "confirmed",
                "persistence": "medium",
                "market_tickers": [],
            }
            for i in range(1, n + 1)
        ]

    def test_unvalidated_path_decorates_only_page(self):
        from routes.events import events
        rows = self._make_rows(40)

        call_counter = {"count": 0}

        def _spy_staleness(row):
            call_counter["count"] += 1
            return {"status": "fresh", "hours_since_check": 0,
                    "event_age_days": 1}

        with patch("routes.events.query_events_filtered", return_value=rows), \
             patch("routes.events.dedup_events", side_effect=lambda r: r), \
             patch("routes.events.compute_staleness", side_effect=_spy_staleness), \
             patch("routes.events.classify_persistence_signal",
                   return_value={"status": "watching", "label": "", "evidence": ""}):
            result = events(
                limit=5, offset=0,
                search=None, stage=None, persistence=None,
                confidence=None, rating=None,
                date_from=None, date_to=None, validated=None,
                mover_window=None,
            )

        self.assertEqual(len(result["items"]), 5)
        # Only the 5 returned rows should have been decorated.
        self.assertEqual(call_counter["count"], 5)
        self.assertEqual(result["total"], 40)

    def test_validated_path_decorates_all_then_filters(self):
        from routes.events import events
        rows = self._make_rows(12)
        # Tag the first 3 as validated, rest untagged.
        for i, r in enumerate(rows):
            r["market_tickers"] = [
                {"direction_tag": "supports up"}
                if i < 3 else {"direction_tag": ""}
            ]

        call_counter = {"count": 0}

        def _spy_staleness(row):
            call_counter["count"] += 1
            return {"status": "fresh", "hours_since_check": 0,
                    "event_age_days": 1}

        with patch("routes.events.query_events_filtered", return_value=rows), \
             patch("routes.events.dedup_events", side_effect=lambda r: r), \
             patch("routes.events.compute_staleness", side_effect=_spy_staleness), \
             patch("routes.events.classify_persistence_signal",
                   return_value={"status": "watching", "label": "", "evidence": ""}):
            result = events(
                limit=5, offset=0,
                search=None, stage=None, persistence=None,
                confidence=None, rating=None,
                date_from=None, date_to=None,
                validated="validated",
                mover_window=None,
            )

        # Full decorate on all 12 because we need validation_status to
        # filter.
        self.assertEqual(call_counter["count"], 12)
        self.assertEqual(result["total"], 3)


# ---------------------------------------------------------------------------
# Bulk markdown export no longer loads each id twice
# ---------------------------------------------------------------------------

class TestBulkExportSingleLoad(unittest.TestCase):
    def test_each_id_loaded_exactly_once(self):
        from routes.events import export_events_markdown_bulk
        import api as _api

        call_counter = {"count": 0}

        def _fake_load(eid):
            call_counter["count"] += 1
            return {
                "id": eid,
                "headline": f"Event {eid}",
                "event_date": "2026-04-20",
                "market_tickers": [],
            }

        class _Req:
            event_ids = [1, 2, 3]

        with patch.object(_api, "load_event_by_id", side_effect=_fake_load), \
             patch.object(_api, "_build_event_markdown_memo",
                          return_value="## memo"):
            resp = export_events_markdown_bulk(_Req())

        # One load per id; the old code did two passes → 6.
        self.assertEqual(call_counter["count"], 3)
        self.assertTrue(resp.body)


# ---------------------------------------------------------------------------
# refresh-market passes force=force, not hardcoded True
# ---------------------------------------------------------------------------

class TestRefreshMarketForceFlag(unittest.TestCase):
    def test_force_false_propagates_through(self):
        from routes.events import refresh_market_endpoint
        import api as _api

        captured = {}

        def _fake_refresh(event, *, force, followup_check_fn, market_check_fn):
            captured["force"] = force
            return {"note": "ok", "tickers": [],
                    "last_market_check_at": None,
                    "market_check_staleness": None}

        with patch.object(_api, "load_event_by_id",
                          return_value={"id": 1, "headline": "h",
                                        "event_date": "2026-04-20",
                                        "market_tickers": []}), \
             patch.object(_api, "refresh_market_for_saved_event",
                          side_effect=_fake_refresh):
            refresh_market_endpoint(event_id=1, force=False)

        self.assertIs(captured.get("force"), False)

    def test_force_true_propagates_through(self):
        from routes.events import refresh_market_endpoint
        import api as _api

        captured = {}

        def _fake_refresh(event, *, force, followup_check_fn, market_check_fn):
            captured["force"] = force
            return {"note": "ok", "tickers": [],
                    "last_market_check_at": None,
                    "market_check_staleness": None}

        with patch.object(_api, "load_event_by_id",
                          return_value={"id": 1, "headline": "h",
                                        "event_date": "2026-04-20",
                                        "market_tickers": []}), \
             patch.object(_api, "refresh_market_for_saved_event",
                          side_effect=_fake_refresh):
            refresh_market_endpoint(event_id=1, force=True)

        self.assertIs(captured.get("force"), True)


# ---------------------------------------------------------------------------
# PEP 701 / Python 3.11 compatibility
# ---------------------------------------------------------------------------

class TestPython311Compatibility(unittest.TestCase):
    def test_scanner_reports_clean(self):
        """The PEP 701 scanner must report zero issues after the audit fix.

        Re-run here so regressions that re-introduce backslashes or
        matching quotes inside f-string expressions fail CI even on
        a 3.12 interpreter.
        """
        import subprocess
        result = subprocess.run(
            [sys.executable, "tools/scan_pep701.py"],
            capture_output=True, text=True,
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        )
        self.assertEqual(
            result.returncode, 0,
            msg=f"PEP 701 scanner found issues:\n{result.stdout}",
        )


if __name__ == "__main__":
    unittest.main()
