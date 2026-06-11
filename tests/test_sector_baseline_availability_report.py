"""Tests for scripts/sector_baseline_availability_report.py (read-only).

O1 reports, for the 86 accepted rows (and the N1 walkthrough cases), whether a
SUGGESTED sector ETF baseline is locally cached and computable at the 1d/5d/20d
event windows, and shows the sector ETF's OWN raw window move as descriptive
context beside the existing SPY-based event-study layer.

It is an availability/gating report ONLY:
  * SPY stays the canonical abnormal-return benchmark; the engine is untouched.
  * The sector ETF is a HINT (reused classifier), never a correction.
  * It NEVER recomputes an asset's abnormal return vs the sector ETF.
  * Cached != computable-at-date: a cached ETF with no contiguous window is
    marked unavailable, not assumed; missing windows are surfaced, not filled.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
import uuid

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts import sector_baseline_availability_report as S  # noqa: E402
import event_study_validation as _esv  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bdays(start_iso: str, count: int) -> list[str]:
    """`count` business-day ISO dates starting at start_iso (inclusive)."""
    out: list[str] = []
    d = _dt.date.fromisoformat(start_iso)
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d = d + _dt.timedelta(days=1)
    return out


def _daily_closes(start_iso: str, count: int, base: float = 100.0,
                  step: float = 0.5) -> dict[str, float]:
    return {d: base + i * step for i, d in enumerate(_bdays(start_iso, count))}


def _row(event_id, headline, *, event_date="2025-06-02", primary_ticker=None):
    return {"event_id": event_id, "headline": headline,
            "event_date": event_date, "primary_ticker": primary_ticker}


def _denoms():
    return {"archive_rows": 180, "accepted_coverage_denominator": 94,
            "accepted_track_record_denominator": 86, "staged_candidate_count": 13}


def _file_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
# Pure availability gate (cached != computable-at-date)
# ---------------------------------------------------------------------------


class TestSectorWindowAvailability(unittest.TestCase):
    def test_available_when_contiguous_forward_window_cached(self):
        closes = _daily_closes("2025-05-20", 40)  # spans event + 20 bdays fwd
        avail, raw = S.sector_window_availability("2025-06-02", closes)
        self.assertTrue(avail[1]["available"])
        self.assertTrue(avail[5]["available"])
        self.assertTrue(avail[20]["available"])
        self.assertIsNotNone(raw[1])
        self.assertIsNotNone(raw[20])

    def test_unavailable_when_etf_not_cached(self):
        avail, raw = S.sector_window_availability("2025-06-02", {})
        for h in (1, 5, 20):
            self.assertFalse(avail[h]["available"])
            self.assertEqual(avail[h]["reason"], "sector_etf_not_cached")
            self.assertIsNone(raw[h])

    def test_unavailable_when_forward_window_missing(self):
        # Cached only up to the event date - no forward bars.
        closes = _daily_closes("2025-05-20", 10)  # ends ~2025-05-31
        avail, raw = S.sector_window_availability("2025-06-02", closes)
        for h in (1, 5, 20):
            self.assertFalse(avail[h]["available"])
            self.assertIsNone(raw[h])

    def test_unavailable_when_no_pre_event_close(self):
        # All cached bars are AFTER the event date - no anchor.
        closes = _daily_closes("2025-06-10", 30)
        avail, _ = S.sector_window_availability("2025-06-02", closes)
        self.assertFalse(avail[1]["available"])
        self.assertEqual(avail[1]["reason"], "no_pre_event_close")

    def test_unavailable_when_window_non_contiguous(self):
        # A big calendar gap inside the forward window breaks contiguity.
        closes = _daily_closes("2025-05-20", 10)
        closes.update(_daily_closes("2025-07-15", 10))  # ~6-week hole
        avail, _ = S.sector_window_availability("2025-06-02", closes)
        self.assertFalse(avail[20]["available"])
        self.assertIn("non_contiguous", avail[20]["reason"])

    def test_raw_move_is_simple_return_not_abnormal(self):
        # entry close 100, exit at +1 bday is 100.5 -> +0.005, no SPY anywhere.
        closes = _daily_closes("2025-05-20", 40, base=100.0, step=0.5)
        _, raw = S.sector_window_availability("2025-06-02", closes)
        # raw move equals (exit/entry - 1) of the ETF's OWN closes.
        dates = sorted(closes)
        i = max(j for j, d in enumerate(dates) if d <= "2025-06-02")
        exit_i = next(j for j, d in enumerate(dates)
                      if d >= _esv._business_day_offset(
                          _dt.date(2025, 6, 2), 1).isoformat())
        expected = round(closes[dates[exit_i]] / closes[dates[i]] - 1.0, 6)
        self.assertAlmostEqual(raw[1], expected, places=6)


# ---------------------------------------------------------------------------
# Report assembly (injected rows / closes)
# ---------------------------------------------------------------------------


def _full_closes():
    return {"XLE": _daily_closes("2025-05-20", 40),
            "XLK": _daily_closes("2025-05-20", 40)}


class TestReportAssembly(unittest.TestCase):
    def _rep(self, **kw):
        rows = [
            _row(1, "Oil sector update", primary_ticker="XLE"),   # high -> XLE
            _row(2, "Tech sector update", primary_ticker="XLK"),  # high -> XLK
            _row(3, "Quarterly note with no sector words",
                 primary_ticker="ZZZZ"),                          # none -> SPY
        ]
        return S.build_report(rows=rows, denominators=_denoms(),
                              closes_by_ticker=_full_closes(),
                              walkthrough_case_ids=[1], **kw)

    def test_denominators_passthrough(self):
        d = self._rep()["denominators"]
        self.assertEqual(d["accepted_track_record_denominator"], 86)
        self.assertEqual(d["accepted_coverage_denominator"], 94)

    def test_scope_flags(self):
        sc = self._rep()["scope"]
        self.assertIs(sc["read_only"], True)
        self.assertIs(sc["spy_canonical_benchmark"], True)
        self.assertIs(sc["engine_math_changed"], False)
        self.assertIs(sc["sector_is_hint_not_correction"], True)
        self.assertIs(sc["no_sector_abnormal_return"], True)
        self.assertIs(sc["no_backfill"], True)

    def test_distinct_sector_row_is_available(self):
        rep = self._rep()
        r = next(x for x in rep["rows"] if x["event_id"] == 1)
        self.assertEqual(r["suggested_sector_etf"], "XLE")
        self.assertEqual(r["suggestion_confidence"], "high")
        self.assertTrue(r["availability"]["horizon_1d"]["available"])
        self.assertIsNotNone(r["sector_raw_moves"]["horizon_1d"])

    def test_fallback_spy_row_has_no_distinct_sector(self):
        rep = self._rep()
        r = next(x for x in rep["rows"] if x["event_id"] == 3)
        self.assertEqual(r["suggested_sector_etf"], "SPY")
        self.assertIn(r["suggestion_confidence"], ("none", "low"))
        self.assertFalse(r["availability"]["horizon_1d"]["available"])
        self.assertIsNone(r["sector_raw_moves"]["horizon_1d"])

    def test_uncached_sector_etf_marked_unavailable_not_filled(self):
        rows = [_row(9, "Financials sector update", primary_ticker="XLF")]
        rep = S.build_report(rows=rows, denominators=_denoms(),
                             closes_by_ticker={},  # XLF not cached
                             walkthrough_case_ids=[])
        r = rep["rows"][0]
        self.assertEqual(r["suggested_sector_etf"], "XLF")
        self.assertFalse(r["availability"]["horizon_20d"]["available"])
        self.assertEqual(r["availability"]["horizon_20d"]["reason"],
                         "sector_etf_not_cached")
        self.assertTrue(r["missingness_note"])

    def test_availability_summary_counts(self):
        rep = self._rep()
        s = rep["accepted_availability_summary"]
        self.assertEqual(s["accepted_rows"], 3)
        self.assertEqual(s["suggested_sector_count"], 2)        # XLE, XLK
        self.assertEqual(s["fallback_or_manual_review_count"], 1)  # SPY row
        self.assertEqual(s["available_1d_count"], 2)
        self.assertEqual(s["available_20d_count"], 2)

    def test_walkthrough_cases_section_present(self):
        rep = self._rep()
        wc = rep["n1_walkthrough_cases"]
        self.assertEqual(wc["selected_case_ids"], [1])
        self.assertTrue(wc["cases"])
        self.assertEqual(wc["cases"][0]["event_id"], 1)

    def test_no_sector_abnormal_return_field_anywhere(self):
        # The negation flags (no_sector_abnormal_return) are honest disclosure;
        # what must NOT exist is a per-row COMPUTED sector-relative AR field.
        rep = self._rep()
        cases = rep["rows"] + rep["n1_walkthrough_cases"]["cases"]
        for c in cases:
            for key in list(c.keys()):
                self.assertNotIn("abnormal", key.lower())
                self.assertNotIn("sar", key.lower())
                self.assertNotIn("car", key.lower())
            # the only sector numbers live under raw moves, keyed by horizon.
            self.assertEqual(set(c["sector_raw_moves"].keys()),
                             {"horizon_1d", "horizon_5d", "horizon_20d"})

    def test_spy_canonical_note_on_each_row(self):
        for r in self._rep()["rows"]:
            self.assertIn("spy", r["spy_canonical_note"].lower())


# ---------------------------------------------------------------------------
# Engine safety / discipline
# ---------------------------------------------------------------------------


class TestEngineSafetyAndDiscipline(unittest.TestCase):
    def _rep(self):
        rows = [_row(1, "Oil sector update", primary_ticker="XLE"),
                _row(2, "No sector words here", primary_ticker="ZZZZ")]
        return S.build_report(rows=rows, denominators=_denoms(),
                             closes_by_ticker=_full_closes(),
                             walkthrough_case_ids=[1])

    def test_benchmark_ticker_unchanged_after_run(self):
        self._rep()
        self.assertEqual(_esv.BENCHMARK_TICKER, "SPY")

    def test_interpretation_block_present(self):
        it = self._rep()["interpretation"]
        for key in ("what_sector_context_helps_clarify",
                    "what_it_does_not_prove", "why_spy_remains_canonical",
                    "why_this_is_not_sector_relative_abnormal_return"):
            self.assertIn(key, it)

    def test_non_claims_cover_required_ground(self):
        blob = " ".join(self._rep()["non_claims"]).lower()
        for needle in ("benchmark replacement", "event-study math",
                       "sector-relative", "significance", "family-level",
                       "recommendation", "paid", "mutation", "denominator"):
            self.assertIn(needle, blob)

    def test_banned_framing_absent_from_source_and_output(self):
        rep = self._rep()
        text = S._render_text(rep) + " " + json.dumps(rep)
        with open(os.path.join(_REPO, "scripts",
                               "sector_baseline_availability_report.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        blob = (text + " " + src).lower()
        for pattern in (r"trading signal", r"buy/sell recommendation",
                        r"\bforecast\b", r"\bproves\b", r"\bproven\b",
                        r"confirmed mechanism", r"validated.as.success",
                        r"actionable trade", r"\balpha\b", r"\bsignal\b"):
            self.assertIsNone(re.search(pattern, blob),
                              f"banned framing {pattern!r} present")


# ---------------------------------------------------------------------------
# Live path / no-write (fixture DB)
# ---------------------------------------------------------------------------

_EVENTS_DDL = """
CREATE TABLE events (
    id INTEGER PRIMARY KEY, event_date TEXT, stage TEXT,
    mechanism_family TEXT, headline TEXT, market_tickers TEXT,
    revisit_snapshots TEXT, mechanism_summary TEXT, what_changed TEXT,
    transmission_chain TEXT, market_note TEXT
)
""".strip()

_PRICE_CACHE_DDL = """
CREATE TABLE price_cache (
    ticker TEXT NOT NULL, date TEXT NOT NULL, close REAL, volume REAL,
    auto_adjust INTEGER NOT NULL, fetched_at TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()

_EVENT_HYGIENE_DDL = """
CREATE TABLE event_hygiene (
    event_id INTEGER PRIMARY KEY, override_class TEXT,
    override_reason TEXT, created_at TEXT
)
""".strip()


class TestLivePathNoWrite(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_sba_{uuid.uuid4().hex}.db")
        conn = sqlite3.connect(self._tmp)
        try:
            for ddl in (_EVENTS_DDL, _PRICE_CACHE_DDL, _EVENT_HYGIENE_DDL):
                conn.execute(ddl)
            # one accepted energy row + cached XLE forward window
            conn.execute(
                "INSERT INTO events (id,event_date,stage,mechanism_family,"
                "headline,market_tickers,mechanism_summary) "
                "VALUES (?,?,?,?,?,?,?)",
                (1, "2025-06-02", "realized", "none", "Oil sector update",
                 json.dumps([{"symbol": "XLE"}]), "summary"))
            for d, c in _daily_closes("2025-05-20", 40).items():
                conn.execute(
                    "INSERT INTO price_cache VALUES (?,?,?,?,?,?)",
                    ("XLE", d, c, 1.0, 0, "2025-06-01"))
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def test_build_never_writes_database(self):
        before = _file_sha256(self._tmp)
        S.build_report(db_path=self._tmp)
        self.assertEqual(_file_sha256(self._tmp), before)

    def test_denominator_is_seeded_accepted_count(self):
        rep = S.build_report(db_path=self._tmp)
        self.assertEqual(
            rep["denominators"]["accepted_track_record_denominator"], 1)

    def test_live_xle_window_available(self):
        rep = S.build_report(db_path=self._tmp)
        r = next(x for x in rep["rows"] if x["event_id"] == 1)
        self.assertEqual(r["suggested_sector_etf"], "XLE")
        self.assertTrue(r["availability"]["horizon_1d"]["available"])


# ---------------------------------------------------------------------------
# Rendering / CLI
# ---------------------------------------------------------------------------


class TestRendering(unittest.TestCase):
    def _rep(self):
        rows = [_row(1, "Oil sector update", primary_ticker="XLE"),
                _row(2, "No sector words", primary_ticker="ZZZZ")]
        return S.build_report(rows=rows, denominators=_denoms(),
                             closes_by_ticker=_full_closes(),
                             walkthrough_case_ids=[1])

    def test_text_render_cp1252_with_required_sections(self):
        text = S._render_text(self._rep())
        text.encode("cp1252")
        low = text.lower()
        for section in ("denominator", "availability", "sector", "spy",
                        "walkthrough", "non-claims"):
            self.assertIn(section, low)

    def test_main_json_smoke(self):
        self.assertEqual(S.main(["--db-path", _ABSENT, "--json"]), 0)

    def test_main_text_smoke(self):
        self.assertEqual(S.main(["--db-path", _ABSENT]), 0)


_ABSENT = os.path.join(tempfile.gettempdir(), f"sba_absent_{uuid.uuid4().hex}.db")


if __name__ == "__main__":
    unittest.main()
