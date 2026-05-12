"""Tests for ``scripts/section_c_quality_diagnostic.py``.

Pin the contract:

* Read-only on every input.  The diagnostic never imports the
  production filter surface (``api`` / ``routes.*`` /
  ``movers_cache``); doing so would couple the diagnostic to the
  thing it is supposed to find bugs in.
* Missing source files surface as warnings, not errors; ``ok=True``
  unless an actual sqlite or parse error fires.
* The envelope carries the documented 13 top-level keys.
* Each candidate carries the 14 spec fields plus ``diagnostic_tags``
  (closed vocabulary).
* The script never claims a row is excluded or filtered — every
  candidate from the candidate pool is surfaced.
* Tag invariants: ``accepted_candidate`` is mutually exclusive with
  every exclusion-worthy tag.
* ``recommended_filter_rules`` entries start with a suggestion verb
  (``Consider``, ``Operators may``, ``Investigate``) — never an
  imperative.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import section_c_quality_diagnostic as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "generated_at",
    "sources_checked",
    "daily_candidates",
    "weekly_candidates",
    "still_moving_candidates",
    "junk_headlines",
    "duplicate_groups",
    "weak_ticker_cases",
    "missing_mechanism_cases",
    "bad_proxy_cases",
    "recommended_filter_rules",
    "warnings",
    "errors",
)


_REQUIRED_CANDIDATE_FIELDS = (
    "event_id",
    "headline",
    "event_date",
    "source_section",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "inclusion_reason",
    "exclusion_reason",
    "duplicate_group_id",
    "ticker_quality",
    "market_relevance_score",
    "evidence_available",
    "diagnostic_tags",
)


_CLOSED_TAG_VOCAB = (
    "off_topic",
    "raw_legal_text",
    "duplicate_headline",
    "duplicate_date_ticker",
    "weak_proxy",
    "missing_mechanism_family",
    "vague_diplomacy",
    "no_price_cache",
    "low_market_relevance",
    "accepted_candidate",
    "needs_operator_review",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "validated",
    "automatically",
    "alpha generated",
    "guaranteed",
    "correct ticker",
)


_SUGGESTION_VERB_PREFIXES = ("Consider", "Operators may", "Investigate")


# Anchor "now" so timestamps in synthetic events are deterministic.
_NOW_DT = _dt.datetime(2026, 5, 12, 12, 0, 0, tzinfo=_dt.timezone.utc)
_NOW_ISO = "2026-05-12T12:00:00Z"


def _ts_hours_ago(hours: float) -> str:
    dt = _NOW_DT - _dt.timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(
    *,
    event_id:         int,
    headline:         str       = "Refiner outage tightens crude product supply",
    event_date:       str       = "2026-05-10",
    timestamp_hours_ago: float  = 12.0,
    market_tickers:   list[dict[str, Any]] | None = None,
    mechanism_family: str | None = "supply_shock",
    low_signal:       int       = 0,
    mechanism_summary: str | None = None,
) -> dict[str, Any]:
    if market_tickers is None:
        market_tickers = [{"symbol": "XOM"}]
    return {
        "event_id":          event_id,
        "headline":          headline,
        "event_date":        event_date,
        "timestamp":         _ts_hours_ago(timestamp_hours_ago),
        "market_tickers":    market_tickers,
        "mechanism_family":  mechanism_family,
        "low_signal":        low_signal,
        "mechanism_summary": mechanism_summary,
    }


def _state(
    *,
    events: list[dict[str, Any]] | None = None,
    cache:  dict[str, int] | None       = None,
    sources_checked: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    errors:   list[str] | None = None,
) -> dict[str, Any]:
    return {
        "events":              events or [],
        "price_cache_tickers": cache or {},
        "sources_checked":     sources_checked or [],
        "warnings":            warnings or [],
        "errors":              errors or [],
    }


def _patch_state(state: dict[str, Any]):
    return patch.object(
        cli, "_load_section_c_state", return_value=state,
    )


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_envelope_has_all_required_keys(self) -> None:
        with _patch_state(_state()):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, report, f"missing key: {k}")

    def test_ok_true_when_no_errors(self) -> None:
        with _patch_state(_state()):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])

    def test_generated_at_is_passed_through(self) -> None:
        with _patch_state(_state()):
            report = cli.run_section_c_quality_diagnostic(
                generated_at="2099-01-01T00:00:00Z",
            )
        self.assertEqual(report["generated_at"], "2099-01-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Per-candidate schema and tag-vocabulary closure
# ---------------------------------------------------------------------------


class TestCandidateSchema(unittest.TestCase):
    def test_each_candidate_has_14_spec_fields_plus_tags(self) -> None:
        events = [_event(event_id=1)]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        self.assertEqual(len(report["daily_candidates"]), 1)
        cand = report["daily_candidates"][0]
        self.assertEqual(set(cand.keys()), set(_REQUIRED_CANDIDATE_FIELDS))

    def test_all_emitted_tags_are_in_closed_vocabulary(self) -> None:
        events = [
            _event(event_id=1, headline="OPEC announces production cut"),
            _event(event_id=2, headline="Section 27 CFR 478 amends scope"),
            _event(event_id=3, headline="Cooking recipe takes social media by storm"),
            _event(event_id=4, headline="Refiner outage tightens supply",
                   market_tickers=[{"symbol": "SPY"}]),  # broad proxy
            _event(event_id=5, mechanism_family=None),
            _event(event_id=6, market_tickers=[{"symbol": "RARE_TKR"}]),  # not cached
        ]
        with _patch_state(_state(events=events, cache={"XOM": 100, "SPY": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        for c in report["daily_candidates"]:
            for tag in c["diagnostic_tags"]:
                self.assertIn(
                    tag, _CLOSED_TAG_VOCAB,
                    f"diagnostic_tag {tag!r} outside closed vocabulary",
                )

    def test_source_section_is_one_of_three(self) -> None:
        events = [
            _event(event_id=1, timestamp_hours_ago=2.0),    # daily
            _event(event_id=2, timestamp_hours_ago=48.0),   # weekly only
            _event(event_id=3, timestamp_hours_ago=14 * 24),  # still_moving
        ]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        all_sections = {
            c["source_section"]
            for c in report["daily_candidates"]
            + report["weekly_candidates"]
            + report["still_moving_candidates"]
        }
        self.assertTrue(
            all_sections.issubset({"daily", "weekly", "still_moving"})
        )


# ---------------------------------------------------------------------------
# Window partitioning
# ---------------------------------------------------------------------------


class TestWindowPartitioning(unittest.TestCase):
    def test_daily_window_admits_under_24h_events(self) -> None:
        events = [_event(event_id=1, timestamp_hours_ago=4.0)]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        self.assertEqual(len(report["daily_candidates"]), 1)

    def test_daily_window_excludes_older_than_24h(self) -> None:
        events = [_event(event_id=1, timestamp_hours_ago=72.0)]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        self.assertEqual(len(report["daily_candidates"]), 0)

    def test_still_moving_window_admits_between_7_and_60_days_old(self) -> None:
        events = [
            _event(event_id=1, timestamp_hours_ago=2 * 24),   # too fresh
            _event(event_id=2, timestamp_hours_ago=14 * 24),  # in window
            _event(event_id=3, timestamp_hours_ago=120 * 24),  # too old
        ]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        ids = {c["event_id"] for c in report["still_moving_candidates"]}
        self.assertEqual(ids, {2})


# ---------------------------------------------------------------------------
# Diagnostic tags — "at least one when present" requirement
# ---------------------------------------------------------------------------


class TestDiagnosticTags(unittest.TestCase):
    def test_off_topic_headline_surfaces(self) -> None:
        events = [_event(
            event_id=1,
            headline="Cooking recipe goes viral on social media",
        )]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        self.assertTrue(any(
            "off_topic" in c["diagnostic_tags"]
            for c in report["junk_headlines"]
        ))
        self.assertGreaterEqual(len(report["junk_headlines"]), 1)

    def test_raw_legal_text_headline_surfaces(self) -> None:
        events = [_event(
            event_id=1,
            headline="Section 27 CFR 478 subparagraph amends scope",
        )]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        self.assertTrue(any(
            "raw_legal_text" in c["diagnostic_tags"]
            for c in report["junk_headlines"]
        ))

    def test_duplicate_headline_group_surfaces(self) -> None:
        # Three rows sharing the same headline — a duplicate group.
        events = [
            _event(event_id=10, headline="OPEC announces production cut"),
            _event(event_id=11, headline="OPEC announces production cut"),
            _event(event_id=12, headline="OPEC announces production cut"),
        ]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        # The duplicate_groups list has at least one entry of type
        # 'headline' that includes all three IDs.
        headline_groups = [
            g for g in report["duplicate_groups"]
            if g["duplicate_type"] == "headline"
        ]
        self.assertGreaterEqual(len(headline_groups), 1)
        self.assertIn(10, headline_groups[0]["event_ids"])
        self.assertIn(11, headline_groups[0]["event_ids"])
        self.assertIn(12, headline_groups[0]["event_ids"])
        for c in report["daily_candidates"]:
            if c["event_id"] in {10, 11, 12}:
                self.assertIn("duplicate_headline", c["diagnostic_tags"])
                self.assertIsNotNone(c["duplicate_group_id"])

    def test_duplicate_date_ticker_group_surfaces(self) -> None:
        # Two events with different headlines but same (event_date,
        # primary_ticker) — the date_ticker group covers them.
        events = [
            _event(
                event_id=20,
                headline="Refiner outage in Texas tightens supply",
                event_date="2026-05-10",
                market_tickers=[{"symbol": "XOM"}],
            ),
            _event(
                event_id=21,
                headline="XOM downgraded after refiner accident",
                event_date="2026-05-10",
                market_tickers=[{"symbol": "XOM"}],
            ),
        ]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        date_groups = [
            g for g in report["duplicate_groups"]
            if g["duplicate_type"] == "date_ticker"
        ]
        self.assertGreaterEqual(len(date_groups), 1)

    def test_missing_mechanism_family_surfaces(self) -> None:
        events = [
            _event(event_id=30, mechanism_family=None),
            _event(event_id=31, mechanism_family=""),
            _event(event_id=32, mechanism_family="none"),
            _event(
                event_id=33, mechanism_family="supply_shock",
                mechanism_summary="Insufficient evidence to characterise",
            ),
        ]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        ids = {c["event_id"] for c in report["missing_mechanism_cases"]}
        self.assertEqual(ids, {30, 31, 32, 33})

    def test_weak_proxy_when_primary_is_broad_etf(self) -> None:
        events = [
            _event(event_id=40, market_tickers=[{"symbol": "SPY"}]),
            _event(event_id=41, market_tickers=[{"symbol": "XLE"}]),
        ]
        with _patch_state(_state(events=events,
                                  cache={"SPY": 200, "XLE": 200})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        ids = {c["event_id"] for c in report["bad_proxy_cases"]}
        self.assertEqual(ids, {40, 41})
        for c in report["bad_proxy_cases"]:
            self.assertIn("weak_proxy", c["diagnostic_tags"])

    def test_no_price_cache_when_ticker_absent(self) -> None:
        events = [_event(event_id=50,
                          market_tickers=[{"symbol": "ZZZ_UNCACHED"}])]
        with _patch_state(_state(events=events, cache={})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        ids = {c["event_id"] for c in report["weak_ticker_cases"]}
        self.assertEqual(ids, {50})
        c = report["daily_candidates"][0]
        self.assertEqual(c["ticker_quality"], "no_cache")
        self.assertIn("no_price_cache", c["diagnostic_tags"])

    def test_missing_primary_ticker(self) -> None:
        events = [_event(event_id=60, market_tickers=[])]
        with _patch_state(_state(events=events, cache={})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        self.assertEqual(len(report["weak_ticker_cases"]), 1)
        self.assertEqual(report["weak_ticker_cases"][0]["ticker_quality"],
                         "missing_primary")

    def test_weak_ticker_and_bad_proxy_are_disjoint(self) -> None:
        events = [
            _event(event_id=70, market_tickers=[{"symbol": "SPY"}]),   # bad_proxy
            _event(event_id=71, market_tickers=[]),                    # weak (missing)
            _event(event_id=72, market_tickers=[{"symbol": "ZZZ"}]),   # weak (no cache)
        ]
        with _patch_state(_state(events=events, cache={"SPY": 200})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        weak_ids  = {c["event_id"] for c in report["weak_ticker_cases"]}
        proxy_ids = {c["event_id"] for c in report["bad_proxy_cases"]}
        self.assertEqual(weak_ids & proxy_ids, set(),
                         "weak_ticker and bad_proxy must be disjoint")


# ---------------------------------------------------------------------------
# Tag invariants
# ---------------------------------------------------------------------------


class TestTagInvariants(unittest.TestCase):
    def test_accepted_excludes_every_exclusion_worthy_tag(self) -> None:
        # Synthesise events covering each exclusion-worthy tag.
        events = [
            _event(event_id=1, headline="Cooking recipe goes viral"),
            _event(event_id=2, headline="Section 27 CFR 478 amends scope"),
            _event(event_id=3, mechanism_family=None),
            _event(event_id=4, market_tickers=[{"symbol": "ZZZ_UNCACHED"}]),
            _event(event_id=5),  # clean — should be accepted
        ]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        for c in report["daily_candidates"]:
            tags = set(c["diagnostic_tags"])
            if "accepted_candidate" in tags:
                self.assertFalse(
                    tags & cli._EXCLUSION_WORTHY_TAGS,
                    f"accepted_candidate co-exists with an "
                    f"exclusion-worthy tag for event {c['event_id']}: {tags}",
                )

    def test_clean_event_gets_accepted_candidate(self) -> None:
        # Reasonably good headline with mechanism + cached ticker.
        events = [_event(
            event_id=99,
            headline="OPEC announces production cut of 1mb/d effective May",
            mechanism_family="supply_shock",
            market_tickers=[{"symbol": "XOM"}],
        )]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        cand = report["daily_candidates"][0]
        self.assertIn("accepted_candidate", cand["diagnostic_tags"])

    def test_observational_concern_on_accepted_triggers_review(self) -> None:
        # Two events sharing a headline — both accepted (clean
        # otherwise) but flagged as duplicate (observational).  Both
        # should pick up needs_operator_review.
        events = [
            _event(event_id=100, headline="OPEC announces production cut"),
            _event(event_id=101, headline="OPEC announces production cut"),
        ]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        for c in report["daily_candidates"]:
            if "accepted_candidate" in c["diagnostic_tags"]:
                self.assertIn("needs_operator_review", c["diagnostic_tags"])


# ---------------------------------------------------------------------------
# market_relevance_score — coarse 0.1 steps
# ---------------------------------------------------------------------------


class TestMarketRelevanceScore(unittest.TestCase):
    def test_score_is_multiple_of_0_1(self) -> None:
        events = [
            _event(event_id=1),
            _event(event_id=2, mechanism_family=None),
            _event(event_id=3, market_tickers=[{"symbol": "SPY"}]),
            _event(event_id=4, headline="Cooking recipe goes viral"),
        ]
        with _patch_state(_state(events=events, cache={"XOM": 100, "SPY": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        for c in report["daily_candidates"]:
            s = c["market_relevance_score"]
            # Multiples of 0.1 in [0.0, 1.0].
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)
            self.assertAlmostEqual(
                round(s * 10) / 10.0, s, places=6,
                msg=f"score {s} is not a multiple of 0.1",
            )

    def test_clean_event_scores_high(self) -> None:
        events = [_event(
            event_id=1,
            headline="OPEC announces production cut of 1mb/d effective May",
            mechanism_family="supply_shock",
            market_tickers=[{"symbol": "XOM"}],
        )]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        self.assertGreaterEqual(
            report["daily_candidates"][0]["market_relevance_score"], 0.9,
        )

    def test_off_topic_event_with_missing_mechanism_scores_low(self) -> None:
        events = [_event(
            event_id=1,
            headline="Cooking recipe",
            mechanism_family=None,
            market_tickers=[{"symbol": "SPY"}],
        )]
        with _patch_state(_state(events=events, cache={"SPY": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        c = report["daily_candidates"][0]
        self.assertLess(c["market_relevance_score"], 0.7)
        # Low score also fires the observational tag.
        self.assertIn("low_market_relevance", c["diagnostic_tags"])


# ---------------------------------------------------------------------------
# recommended_filter_rules — suggestion verbs only
# ---------------------------------------------------------------------------


class TestRecommendedFilterRules(unittest.TestCase):
    def test_rules_list_is_non_empty(self) -> None:
        with _patch_state(_state()):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        self.assertGreater(len(report["recommended_filter_rules"]), 0)

    def test_every_rule_starts_with_a_suggestion_verb(self) -> None:
        with _patch_state(_state()):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        for rule in report["recommended_filter_rules"]:
            self.assertTrue(
                any(rule.startswith(v) for v in _SUGGESTION_VERB_PREFIXES),
                f"rule must start with a suggestion verb "
                f"({_SUGGESTION_VERB_PREFIXES}); got {rule!r}",
            )

    def test_no_rule_uses_imperative_reject_or_drop(self) -> None:
        # Rules are suggestions only.  An imperative ("Reject X",
        # "Drop X") would imply applied intent.
        with _patch_state(_state()):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        joined = " ".join(report["recommended_filter_rules"]).lower()
        for verb in ("reject ", "drop ", "delete ", "remove "):
            self.assertNotIn(verb, joined,
                             f"imperative {verb!r} leaked into rules")


# ---------------------------------------------------------------------------
# Missing-source handling
# ---------------------------------------------------------------------------


class TestMissingSourceHandling(unittest.TestCase):
    def test_missing_db_path_yields_warning_not_error(self) -> None:
        # Use the un-patched seam with a path that does not exist.
        bogus = os.path.join(
            tempfile.gettempdir(),
            f"no_such_db_{uuid.uuid4().hex}.db",
        )
        self.assertFalse(Path(bogus).exists())
        report = cli.run_section_c_quality_diagnostic(
            db_path=bogus, generated_at=_NOW_ISO,
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])
        self.assertTrue(any(
            "does not exist" in w for w in report["warnings"]
        ))
        self.assertEqual(report["daily_candidates"], [])

    def test_none_db_path_yields_warning_not_error(self) -> None:
        report = cli.run_section_c_quality_diagnostic(
            db_path=None, generated_at=_NOW_ISO,
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])
        self.assertTrue(any(
            "db-path" in w.lower() for w in report["warnings"]
        ))

    def test_missing_events_table_yields_warning(self) -> None:
        # Real sqlite file but no events table.  The seam must
        # surface a warning and return empty events.
        tmp = os.path.join(
            tempfile.gettempdir(),
            f"empty_db_{uuid.uuid4().hex}.db",
        )
        try:
            sqlite3.connect(tmp).close()  # Empty file.
            report = cli.run_section_c_quality_diagnostic(
                db_path=tmp, generated_at=_NOW_ISO,
            )
            self.assertTrue(report["ok"])
            joined = " ".join(report["warnings"]).lower()
            self.assertIn("events", joined)
            self.assertEqual(report["daily_candidates"], [])
        finally:
            if Path(tmp).exists():
                Path(tmp).unlink()

    def test_missing_price_cache_table_still_runs(self) -> None:
        # events table exists but price_cache does not.  Every event
        # picks up the no_price_cache tag (no cache rows → 0 count).
        tmp = os.path.join(
            tempfile.gettempdir(),
            f"events_only_db_{uuid.uuid4().hex}.db",
        )
        try:
            conn = sqlite3.connect(tmp)
            try:
                conn.execute(
                    "CREATE TABLE events ("
                    "id INTEGER PRIMARY KEY, headline TEXT, "
                    "event_date TEXT, timestamp TEXT, "
                    "market_tickers TEXT, mechanism_family TEXT, "
                    "low_signal INTEGER, mechanism_summary TEXT)"
                )
                conn.execute(
                    "INSERT INTO events (id, headline, event_date, "
                    "timestamp, market_tickers, mechanism_family, "
                    "low_signal, mechanism_summary) VALUES "
                    "(1, ?, ?, ?, ?, ?, 0, NULL)",
                    (
                        "Refiner outage tightens crude product supply",
                        "2026-05-10",
                        _ts_hours_ago(12.0),
                        json.dumps([{"symbol": "XOM"}]),
                        "supply_shock",
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            report = cli.run_section_c_quality_diagnostic(
                db_path=tmp, generated_at=_NOW_ISO,
            )
            # Still ok=True; warning lists price_cache.
            self.assertTrue(report["ok"])
            joined = " ".join(report["warnings"]).lower()
            self.assertIn("price_cache", joined)
            self.assertEqual(len(report["daily_candidates"]), 1)
            self.assertIn(
                "no_price_cache",
                report["daily_candidates"][0]["diagnostic_tags"],
            )
        finally:
            if Path(tmp).exists():
                Path(tmp).unlink()


# ---------------------------------------------------------------------------
# Read-only invariant against a real sqlite file
# ---------------------------------------------------------------------------


class TestReadOnlyInvariant(unittest.TestCase):
    def test_diagnostic_does_not_add_or_remove_rows(self) -> None:
        tmp = os.path.join(
            tempfile.gettempdir(),
            f"ro_db_{uuid.uuid4().hex}.db",
        )
        try:
            conn = sqlite3.connect(tmp)
            try:
                conn.execute(
                    "CREATE TABLE events ("
                    "id INTEGER PRIMARY KEY, headline TEXT, "
                    "event_date TEXT, timestamp TEXT, "
                    "market_tickers TEXT, mechanism_family TEXT, "
                    "low_signal INTEGER, mechanism_summary TEXT)"
                )
                conn.execute(
                    "CREATE TABLE price_cache ("
                    "ticker TEXT, date TEXT, close REAL, "
                    "volume REAL, auto_adjust INTEGER, "
                    "fetched_at TEXT, "
                    "PRIMARY KEY (ticker, date, auto_adjust))"
                )
                for i in range(3):
                    conn.execute(
                        "INSERT INTO events VALUES "
                        "(?, ?, ?, ?, ?, ?, 0, NULL)",
                        (
                            i + 1,
                            f"Synthetic headline {i}",
                            "2026-05-10",
                            _ts_hours_ago(12.0),
                            json.dumps([{"symbol": "XOM"}]),
                            "supply_shock",
                        ),
                    )
                conn.execute(
                    "INSERT INTO price_cache VALUES "
                    "(?, ?, ?, ?, ?, ?)",
                    ("XOM", "2026-05-10", 100.0, 1_000_000, 1,
                     "2026-05-10T00:00:00Z"),
                )
                conn.commit()
            finally:
                conn.close()

            # Snapshot row counts.
            conn = sqlite3.connect(tmp)
            try:
                before_events = conn.execute(
                    "SELECT COUNT(*) FROM events"
                ).fetchone()[0]
                before_cache = conn.execute(
                    "SELECT COUNT(*) FROM price_cache"
                ).fetchone()[0]
            finally:
                conn.close()

            cli.run_section_c_quality_diagnostic(
                db_path=tmp, generated_at=_NOW_ISO,
            )

            conn = sqlite3.connect(tmp)
            try:
                after_events = conn.execute(
                    "SELECT COUNT(*) FROM events"
                ).fetchone()[0]
                after_cache = conn.execute(
                    "SELECT COUNT(*) FROM price_cache"
                ).fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(before_events, after_events)
            self.assertEqual(before_cache, after_cache)
        finally:
            if Path(tmp).exists():
                Path(tmp).unlink()

    def test_diagnostic_does_not_mutate_candidates(self) -> None:
        # Even with junk + duplicate + missing-mechanism events, no
        # candidate is dropped from the per-section lists — the
        # diagnostic surfaces every event the candidate pool admits.
        events = [
            _event(event_id=1, headline="Cooking recipe"),
            _event(event_id=2, mechanism_family=None),
            _event(event_id=3, market_tickers=[]),
            _event(event_id=4),
            _event(event_id=5, headline="OPEC announces production cut"),
            _event(event_id=6, headline="OPEC announces production cut"),
        ]
        with _patch_state(_state(events=events, cache={"XOM": 100})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        self.assertEqual(len(report["daily_candidates"]), 6)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_tokens_in_json_render(self) -> None:
        events = [
            _event(event_id=1, headline="Cooking recipe"),
            _event(event_id=2, mechanism_family=None),
            _event(event_id=3, market_tickers=[{"symbol": "SPY"}]),
        ]
        with _patch_state(_state(events=events, cache={"SPY": 200})):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        blob = cli._render_json(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, blob,
                             f"banned token {term!r} in JSON render")

    def test_no_banned_tokens_in_text_render(self) -> None:
        with _patch_state(_state()):
            report = cli.run_section_c_quality_diagnostic(
                generated_at=_NOW_ISO,
            )
        text = cli._render_text(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, text)


# ---------------------------------------------------------------------------
# Import isolation — no production filter surface
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_production_filter_modules(self) -> None:
        # The diagnostic must be decoupled from production filters so
        # it can find bugs in them rather than re-applying them.
        for attr in ("api", "routes", "movers_cache",
                     "market_check", "market_data",
                     "yfinance", "anthropic", "openai", "fastapi"):
            self.assertFalse(
                hasattr(cli, attr),
                f"diagnostic must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_json_flag_emits_envelope_keys(self) -> None:
        # Use a bogus DB path so the seam returns empty state.
        bogus = os.path.join(
            tempfile.gettempdir(),
            f"no_such_{uuid.uuid4().hex}.db",
        )
        rc, output = self._run(["--json", "--db-path", bogus])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)
        self.assertTrue(parsed["ok"])

    def test_default_text_render_runs(self) -> None:
        bogus = os.path.join(
            tempfile.gettempdir(),
            f"no_such_{uuid.uuid4().hex}.db",
        )
        rc, output = self._run(["--db-path", bogus])
        self.assertEqual(rc, 0)
        self.assertIn("Section C", output)


if __name__ == "__main__":
    unittest.main()
