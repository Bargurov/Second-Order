"""Tests for ``event_date_backfill.plan_event_date_backfill``.

Read-only dry-run planner — no DB writes, no provider/yfinance/LLM, no
FastAPI surface.  These tests pin the contract:

  * Candidate identification: ``event_date`` IS NULL or '' AND
    ``timestamp`` non-empty.
  * Proposal: ``timestamp[:10]`` when it parses as ISO YYYY-MM-DD;
    otherwise the row counts toward ``total_candidates`` /
    ``ticker_rows_blocked`` but is NOT proposed and contributes to
    ``skipped_counts``.
  * Dated rows excluded.
  * Repeated calls leave events + price_cache byte-identical.
  * No provider, yfinance, market_check, market_data, price_cache,
    or LLM seams are invoked.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
from event_date_backfill import plan_event_date_backfill  # noqa: E402


_TOP_KEYS = (
    "total_candidates",
    "events_with_market_tickers",
    "ticker_rows_blocked",
    "proposed_updates",
    "skipped_counts",
    "confidence_note",
)

_PROPOSAL_KEYS = (
    "event_id",
    "headline",
    "timestamp",
    "proposed_event_date",
    "ticker_count",
    "tickers",
)


def _snapshot_tables(db_path: str) -> tuple[list[tuple], list[tuple]]:
    conn = sqlite3.connect(db_path)
    try:
        events = list(conn.execute("SELECT * FROM events ORDER BY id"))
        cache = list(conn.execute(
            "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
            "FROM price_cache ORDER BY ticker, date, auto_adjust"
        ))
        return events, cache
    finally:
        conn.close()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_edb_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db._db_ready = False
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        db._db_ready = False
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _seed(
        self,
        *,
        event_date,
        symbols=None,
        timestamp=None,
        headline=None,
    ) -> None:
        head = headline or f"EDB seed {uuid.uuid4().hex[:10]}"
        ev = {
            "headline":       head,
            "stage":          "realized",
            "persistence":    "medium",
            "event_date":     event_date,
            "market_tickers": [{"symbol": s.upper()} for s in (symbols or [])],
        }
        if timestamp is not None:
            ev["timestamp"] = timestamp
        db.save_event(ev)


class TestPlanShape(_Base):
    def test_returns_dict_with_top_keyset(self) -> None:
        plan = plan_event_date_backfill()
        self.assertIsInstance(plan, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, plan, f"missing top-level key: {key}")

    def test_confidence_note_is_non_empty_string(self) -> None:
        plan = plan_event_date_backfill()
        self.assertIsInstance(plan["confidence_note"], str)
        self.assertTrue(plan["confidence_note"])

    def test_skipped_counts_is_dict(self) -> None:
        plan = plan_event_date_backfill()
        self.assertIsInstance(plan["skipped_counts"], dict)
        # Schema must include the unparseable bucket so consumers can
        # branch on it without a KeyError on a clean DB.
        self.assertIn("timestamp_unparseable", plan["skipped_counts"])


class TestPlanEmptyDB(_Base):
    def test_zero_counts_and_empty_lists(self) -> None:
        plan = plan_event_date_backfill()
        self.assertEqual(plan["total_candidates"],           0)
        self.assertEqual(plan["events_with_market_tickers"], 0)
        self.assertEqual(plan["ticker_rows_blocked"],        0)
        self.assertEqual(plan["proposed_updates"], [])
        self.assertEqual(sum(plan["skipped_counts"].values()), 0)


class TestPlanIdentifiesCandidates(_Base):
    def test_null_event_date_counts(self) -> None:
        self._seed(event_date=None, symbols=["AAPL"])
        plan = plan_event_date_backfill()
        self.assertEqual(plan["total_candidates"], 1)

    def test_empty_string_event_date_counts(self) -> None:
        self._seed(event_date="", symbols=["MSFT"])
        plan = plan_event_date_backfill()
        self.assertEqual(plan["total_candidates"], 1)

    def test_dated_rows_excluded(self) -> None:
        self._seed(
            event_date=datetime.now().strftime("%Y-%m-%d"),
            symbols=["AAPL", "MSFT"],
        )
        plan = plan_event_date_backfill()
        self.assertEqual(plan["total_candidates"],           0)
        self.assertEqual(plan["events_with_market_tickers"], 0)
        self.assertEqual(plan["ticker_rows_blocked"],        0)
        self.assertEqual(plan["proposed_updates"],           [])
        self.assertEqual(sum(plan["skipped_counts"].values()), 0)

    def test_mixed_archive_only_undated_appear(self) -> None:
        self._seed(event_date=None, symbols=["AAPL"])
        self._seed(
            event_date=datetime.now().strftime("%Y-%m-%d"),
            symbols=["MSFT"],
        )
        self._seed(event_date="", symbols=["GOOG"])
        plan = plan_event_date_backfill()
        self.assertEqual(plan["total_candidates"],            2)
        self.assertEqual(plan["events_with_market_tickers"],  2)
        self.assertEqual(plan["ticker_rows_blocked"],         2)
        self.assertEqual(len(plan["proposed_updates"]),       2)


class TestPlanTickerCounts(_Base):
    def test_events_with_market_tickers_excludes_empty(self) -> None:
        self._seed(event_date=None, symbols=[])
        self._seed(event_date=None, symbols=["AAPL"])
        plan = plan_event_date_backfill()
        self.assertEqual(plan["total_candidates"],           2)
        self.assertEqual(plan["events_with_market_tickers"], 1)

    def test_ticker_rows_blocked_sums_unique_symbols(self) -> None:
        self._seed(event_date=None, symbols=["AAPL", "MSFT"])
        self._seed(event_date="",   symbols=["GOOG"])
        plan = plan_event_date_backfill()
        self.assertEqual(plan["ticker_rows_blocked"], 3)


class TestPlanProposedUpdates(_Base):
    def test_proposal_carries_required_fields(self) -> None:
        self._seed(
            event_date=None,
            symbols=["AAPL", "MSFT"],
            timestamp="2026-04-15T13:30:00",
            headline="Backfill plan one",
        )
        plan = plan_event_date_backfill()
        self.assertEqual(len(plan["proposed_updates"]), 1)
        prop = plan["proposed_updates"][0]
        for key in _PROPOSAL_KEYS:
            self.assertIn(key, prop, f"proposal missing field: {key}")
        self.assertIsInstance(prop["event_id"], int)
        self.assertEqual(prop["headline"], "Backfill plan one")
        self.assertEqual(prop["timestamp"], "2026-04-15T13:30:00")
        self.assertEqual(prop["proposed_event_date"], "2026-04-15")
        self.assertEqual(prop["ticker_count"], 2)
        self.assertEqual(set(prop["tickers"]), {"AAPL", "MSFT"})

    def test_proposed_updates_unbounded(self) -> None:
        # Diagnostic endpoint capped examples at 10; the planner is
        # the source of truth for the full plan and must not cap.
        for i in range(15):
            self._seed(
                event_date=None, symbols=[],
                headline=f"plan {i} {uuid.uuid4().hex[:8]}",
            )
        plan = plan_event_date_backfill()
        self.assertEqual(plan["total_candidates"],      15)
        self.assertEqual(len(plan["proposed_updates"]), 15)

    def test_ordered_by_event_id_ascending(self) -> None:
        for i in range(3):
            self._seed(
                event_date=None, symbols=[],
                headline=f"plan order {i}",
            )
        plan = plan_event_date_backfill()
        ids = [p["event_id"] for p in plan["proposed_updates"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), 3)


class TestPlanSkippedMalformedTimestamp(_Base):
    def test_malformed_timestamp_skipped_from_proposals(self) -> None:
        self._seed(
            event_date=None,
            symbols=["AAPL"],
            timestamp="not-a-date",
            headline="malformed plan one",
        )
        plan = plan_event_date_backfill()
        self.assertEqual(plan["total_candidates"],   1)
        self.assertEqual(plan["proposed_updates"],   [])
        self.assertEqual(
            plan["skipped_counts"].get("timestamp_unparseable", 0), 1,
        )

    def test_malformed_timestamp_still_counts_ticker_rows(self) -> None:
        # ``ticker_rows_blocked`` reflects the hydration-blocking ticker
        # rows; the absent event_date blocks hydration regardless of
        # whether THIS planner can resolve the date.
        self._seed(
            event_date=None,
            symbols=["AAPL", "MSFT"],
            timestamp="not-a-date",
        )
        plan = plan_event_date_backfill()
        self.assertEqual(plan["ticker_rows_blocked"], 2)
        self.assertEqual(plan["events_with_market_tickers"], 1)

    def test_malformed_timestamp_does_not_collapse_other_proposals(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="not-a-date",
            headline="bad ts",
        )
        self._seed(
            event_date=None, symbols=["MSFT"],
            timestamp="2026-04-15T13:30:00",
            headline="good ts",
        )
        plan = plan_event_date_backfill()
        self.assertEqual(plan["total_candidates"],   2)
        self.assertEqual(len(plan["proposed_updates"]), 1)
        self.assertEqual(
            plan["proposed_updates"][0]["proposed_event_date"],
            "2026-04-15",
        )
        self.assertEqual(
            plan["skipped_counts"].get("timestamp_unparseable", 0), 1,
        )


class TestPlanNoMutation(_Base):
    def test_repeated_calls_do_not_modify_events_or_price_cache(self) -> None:
        self._seed(event_date=None, symbols=["AAPL"])
        self._seed(event_date="",   symbols=[])
        self._seed(
            event_date=None, symbols=["MSFT"],
            timestamp="not-a-date",
        )
        # Plant a price_cache row so we can prove the planner does not
        # touch ``price_cache`` (no purge, no fetch, no upsert).
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-04-14", 100.0, 5_000_000.0, 0,
                 "2026-05-06T12:00:00+00:00"),
            )
            conn.commit()

        before = _snapshot_tables(self._tmp)
        for _ in range(3):
            plan_event_date_backfill()
        after = _snapshot_tables(self._tmp)
        self.assertEqual(
            before, after,
            "events + price_cache must be byte-identical before and "
            "after repeated planner calls",
        )


class TestPlanNoProviderCalls(_Base):
    """Planner must never call market_check, market_data, yfinance,
    fetch_daily_cached, or any LLM seam."""

    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        self._seed(event_date=None, symbols=["AAPL"])

        candidate_seams = (
            ("market_check", "_fetch"),
            ("market_check", "_fetch_since"),
            ("market_check", "market_check"),
            ("market_check", "_check_one_ticker"),
            ("market_data",  "get_provider"),
            ("market_data",  "reload_provider_from_env"),
            ("price_cache",  "fetch_daily_cached"),
            ("price_cache",  "_purge_corrupt_rows"),
            ("price_cache",  "_ensure_table"),
        )

        with ExitStack() as stack:
            for module_name, attr in candidate_seams:
                try:
                    mod = __import__(module_name)
                except Exception:
                    continue
                if not hasattr(mod, attr):
                    continue
                stack.enter_context(patch.object(
                    mod, attr,
                    side_effect=AssertionError(
                        f"plan_event_date_backfill must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "plan_event_date_backfill must not call yfinance",
                    ),
                ))
            except ImportError:
                pass

            plan = plan_event_date_backfill()

        # Sanity: real result, not the empty fallback.
        self.assertEqual(plan["total_candidates"],           1)
        self.assertEqual(plan["events_with_market_tickers"], 1)
        self.assertEqual(plan["ticker_rows_blocked"],        1)
        self.assertEqual(len(plan["proposed_updates"]),      1)


class TestPlanExplicitDbPath(_Base):
    """``db_path`` keyword lets callers point the planner at any SQLite
    file without monkey-patching ``db.DB_FILE`` — useful for batch
    operators inspecting an archive snapshot."""

    def test_db_path_kwarg_overrides_default(self) -> None:
        self._seed(event_date=None, symbols=["AAPL"])
        # Switch the global to a fresh empty DB; passing the seeded
        # path explicitly must still resolve the seeded candidate.
        original_seeded = self._tmp
        empty_path = os.path.join(
            tempfile.gettempdir(),
            f"test_edb_alt_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = empty_path
        db._db_ready = False
        db.init_db()
        try:
            plan = plan_event_date_backfill(db_path=original_seeded)
        finally:
            db.DB_FILE = original_seeded
            db._db_ready = False
            db.init_db()
            try:
                os.remove(empty_path)
            except (OSError, PermissionError):
                pass
        self.assertEqual(plan["total_candidates"], 1)


# ---------------------------------------------------------------------------
# Projected hydration impact — track-record projection block.
# ---------------------------------------------------------------------------


_IMPACT_KEYS = (
    "candidate_events",
    "proposed_updates_count",
    "ticker_rows_blocked",
    "ticker_rows_unblocked_by_write",
    "remaining_ticker_rows_blocked",
    "skipped_counts",
)


class TestProjectedHydrationImpactShape(_Base):
    def test_top_level_carries_projection_block(self) -> None:
        plan = plan_event_date_backfill()
        self.assertIn("projected_hydration_impact", plan)
        impact = plan["projected_hydration_impact"]
        self.assertIsInstance(impact, dict)
        for key in _IMPACT_KEYS:
            self.assertIn(key, impact, f"impact missing field: {key}")

    def test_legacy_top_level_keys_remain_backward_compatible(self) -> None:
        # Adding the projection block must not drop any existing key.
        plan = plan_event_date_backfill()
        for key in _TOP_KEYS:
            self.assertIn(
                key, plan,
                f"backward-compatible top-level key dropped: {key}",
            )

    def test_empty_db_projection_is_all_zeroes(self) -> None:
        impact = plan_event_date_backfill()["projected_hydration_impact"]
        self.assertEqual(impact["candidate_events"],               0)
        self.assertEqual(impact["proposed_updates_count"],         0)
        self.assertEqual(impact["ticker_rows_blocked"],            0)
        self.assertEqual(impact["ticker_rows_unblocked_by_write"], 0)
        self.assertEqual(impact["remaining_ticker_rows_blocked"],  0)
        self.assertIsInstance(impact["skipped_counts"], dict)
        self.assertEqual(sum(impact["skipped_counts"].values()),   0)


class TestProjectedHydrationImpactAllParseable(_Base):
    def test_all_candidates_have_parseable_timestamps(self) -> None:
        self._seed(
            event_date=None,
            symbols=["AAPL", "MSFT"],
            timestamp="2026-04-15T13:30:00",
            headline="EDB-IMP all parseable a",
        )
        self._seed(
            event_date="",
            symbols=["GOOG"],
            timestamp="2026-04-16T09:00:00",
            headline="EDB-IMP all parseable b",
        )
        plan = plan_event_date_backfill()
        impact = plan["projected_hydration_impact"]
        self.assertEqual(impact["candidate_events"],               2)
        self.assertEqual(impact["proposed_updates_count"],         2)
        self.assertEqual(impact["ticker_rows_blocked"],            3)
        self.assertEqual(impact["ticker_rows_unblocked_by_write"], 3)
        self.assertEqual(impact["remaining_ticker_rows_blocked"],  0)


class TestProjectedHydrationImpactMixed(_Base):
    def test_unparseable_rows_remain_blocked_after_write(self) -> None:
        self._seed(
            event_date=None,
            symbols=["AAPL", "MSFT"],
            timestamp="2026-04-15T13:30:00",
            headline="EDB-IMP mixed parseable",
        )
        self._seed(
            event_date=None,
            symbols=["TSLA"],
            timestamp="not-a-date",
            headline="EDB-IMP mixed unparseable",
        )
        plan = plan_event_date_backfill()
        impact = plan["projected_hydration_impact"]
        self.assertEqual(impact["candidate_events"],               2)
        self.assertEqual(impact["proposed_updates_count"],         1)
        self.assertEqual(impact["ticker_rows_blocked"],            3)
        self.assertEqual(impact["ticker_rows_unblocked_by_write"], 2)
        self.assertEqual(impact["remaining_ticker_rows_blocked"],  1)
        # Partition invariant.
        self.assertEqual(
            impact["ticker_rows_unblocked_by_write"]
            + impact["remaining_ticker_rows_blocked"],
            impact["ticker_rows_blocked"],
        )
        # Skipped counts mirror the existing top-level shape.
        self.assertEqual(impact["skipped_counts"], plan["skipped_counts"])
        self.assertEqual(
            impact["skipped_counts"].get("timestamp_unparseable", 0), 1,
        )


class TestProjectedHydrationImpactNoTicker(_Base):
    def test_no_ticker_candidate_unblocks_zero_rows(self) -> None:
        self._seed(
            event_date=None,
            symbols=[],
            timestamp="2026-04-17T10:00:00",
            headline="EDB-IMP no tickers",
        )
        plan = plan_event_date_backfill()
        impact = plan["projected_hydration_impact"]
        self.assertEqual(impact["candidate_events"],               1)
        self.assertEqual(impact["proposed_updates_count"],         1)
        self.assertEqual(impact["ticker_rows_blocked"],            0)
        self.assertEqual(impact["ticker_rows_unblocked_by_write"], 0)
        self.assertEqual(impact["remaining_ticker_rows_blocked"],  0)
        # Per-proposal field reflects zero-ticker reality.
        proposal = plan["proposed_updates"][0]
        self.assertEqual(proposal["projected_tickers_unblocked"], 0)


class TestProjectedHydrationImpactDuplicateTickers(_Base):
    def test_duplicate_tickers_in_one_event_count_once(self) -> None:
        # ``_ticker_symbols`` returns a set, so duplicate entries in the
        # raw market_tickers JSON must collapse to a single hydration
        # row in the projection.
        self._seed(
            event_date=None,
            symbols=["AAPL", "AAPL"],
            timestamp="2026-04-18T13:30:00",
            headline="EDB-IMP duplicate tickers",
        )
        plan = plan_event_date_backfill()
        impact = plan["projected_hydration_impact"]
        self.assertEqual(impact["ticker_rows_blocked"],            1)
        self.assertEqual(impact["ticker_rows_unblocked_by_write"], 1)
        self.assertEqual(impact["remaining_ticker_rows_blocked"],  0)
        # Per-proposal: ticker_count and projected_tickers_unblocked
        # must agree on the deduplicated count.
        proposal = plan["proposed_updates"][0]
        self.assertEqual(proposal["ticker_count"],                1)
        self.assertEqual(proposal["projected_tickers_unblocked"], 1)
        self.assertEqual(proposal["tickers"],                     ["AAPL"])


class TestProjectedHydrationImpactDatedExcluded(_Base):
    def test_dated_rows_do_not_appear_in_projection(self) -> None:
        self._seed(
            event_date=datetime.now().strftime("%Y-%m-%d"),
            symbols=["AAPL", "MSFT"],
            timestamp="2026-04-15T13:30:00",
            headline="EDB-IMP dated excluded",
        )
        plan = plan_event_date_backfill()
        impact = plan["projected_hydration_impact"]
        self.assertEqual(impact["candidate_events"],               0)
        self.assertEqual(impact["proposed_updates_count"],         0)
        self.assertEqual(impact["ticker_rows_blocked"],            0)
        self.assertEqual(impact["ticker_rows_unblocked_by_write"], 0)
        self.assertEqual(impact["remaining_ticker_rows_blocked"],  0)


class TestProjectedHydrationImpactConsistencyWithTopLevel(_Base):
    def test_aggregate_matches_per_proposal_sum(self) -> None:
        self._seed(
            event_date=None, symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
            headline="EDB-IMP cons a",
        )
        self._seed(
            event_date=None, symbols=["MSFT", "GOOG"],
            timestamp="2026-04-16T09:00:00",
            headline="EDB-IMP cons b",
        )
        self._seed(
            event_date=None, symbols=["TSLA"],
            timestamp="not-a-date",
            headline="EDB-IMP cons c",
        )
        plan = plan_event_date_backfill()
        impact = plan["projected_hydration_impact"]
        # Aggregate field equals sum of per-proposal estimates.
        per_proposal_sum = sum(
            p["projected_tickers_unblocked"]
            for p in plan["proposed_updates"]
        )
        self.assertEqual(
            impact["ticker_rows_unblocked_by_write"], per_proposal_sum,
        )
        # Sub-block mirrors top-level totals where they overlap.
        self.assertEqual(impact["candidate_events"],
                         plan["total_candidates"])
        self.assertEqual(impact["proposed_updates_count"],
                         len(plan["proposed_updates"]))
        self.assertEqual(impact["ticker_rows_blocked"],
                         plan["ticker_rows_blocked"])


class TestProjectedHydrationImpactNoMutation(_Base):
    def test_repeated_calls_with_projection_do_not_modify_db(self) -> None:
        self._seed(event_date=None, symbols=["AAPL"])
        self._seed(event_date="",   symbols=[])
        self._seed(
            event_date=None, symbols=["MSFT"],
            timestamp="not-a-date",
        )
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-04-14", 100.0, 5_000_000.0, 0,
                 "2026-05-06T12:00:00+00:00"),
            )
            conn.commit()

        before = _snapshot_tables(self._tmp)
        for _ in range(3):
            plan = plan_event_date_backfill()
            # Touch the projection block on every call to confirm it is
            # built without any side effect on the tables.
            self.assertIn("projected_hydration_impact", plan)
        after = _snapshot_tables(self._tmp)
        self.assertEqual(
            before, after,
            "events + price_cache must be byte-identical before and "
            "after repeated planner calls (projection-aware)",
        )


if __name__ == "__main__":
    unittest.main()
