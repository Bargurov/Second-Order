"""Tests for scripts/transmission_case_walkthrough_report.py (read-only).

N1 renders a small, deterministic, outcome-diverse set of accepted rows as
per-case transmission walkthroughs: event -> what changed -> mechanism ->
named assets -> 1d/5d/20d reaction -> event-study readout if available ->
event-date-quality caveat -> track-record outcome / sensitivity caveat ->
honest non-claims. It REUSES the J1 overlay, the event-date-quality report,
the track-record scoring, and the event-study coverage engine - it rebuilds
none of them, writes no DB labels, and forces outcome diversity so the set is
never winners-only.
"""
from __future__ import annotations

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

from scripts import transmission_case_walkthrough_report as W  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers: synthetic enriched rows / edq report / event-study dicts
# ---------------------------------------------------------------------------


def _tk(symbol, direction=None):
    d = {"symbol": symbol}
    if direction == "support":
        d["direction_tag"] = "supports_thesis"
    elif direction == "contradict":
        d["direction_tag"] = "contradicts_thesis"
    return d


def _row(event_id, headline, *, tickers=(), event_date="2025-06-01",
         mechanism_summary="A substantive mechanism summary of the event.",
         what_changed="What changed in one substantive sentence here.",
         transmission_chain="oil -> energy equities -> index",
         market_note="A substantive market note about the reaction.",
         assets_to_watch=None, key_falsifiers=None, mechanism_family="none"):
    return {
        "event_id": event_id,
        "headline": headline,
        "event_date": event_date,
        "tickers": list(tickers),
        "mechanism_family": mechanism_family,
        "what_changed": what_changed,
        "mechanism_summary": mechanism_summary,
        "transmission_chain": transmission_chain,
        "market_note": market_note,
        "assets_to_watch": assets_to_watch,
        "key_falsifiers": key_falsifiers,
    }


def _edq_report(events, *, denoms=None):
    d = {
        "archive_rows": 180,
        "accepted_coverage_denominator": 94,
        "accepted_track_record_denominator": 86,
        "staged_candidate_count": 13,
    }
    if denoms:
        d.update(denoms)
    return {"denominators": d, "events": list(events)}


def _edq_event(event_id, quality="clean_discrete_event", risk="low",
               caution="window is interpretable with standard caveats"):
    return {
        "event_id": event_id,
        "event_date_quality": quality,
        "anticipation_risk": risk,
        "horizon_interpretation_caution": caution,
    }


def _per_horizon():
    return [
        {"horizon": 1, "abnormal_return": 0.012, "sar": 0.4, "car": 0.012},
        {"horizon": 5, "abnormal_return": 0.031, "sar": 0.7, "car": 0.031},
        {"horizon": 20, "abnormal_return": 0.05, "sar": 0.9, "car": 0.05},
    ]


def _es_available(event_id, primary="AAA", benchmark="SPY"):
    return {event_id: {"per_horizon": _per_horizon(),
                       "primary_ticker": primary, "benchmark": benchmark}}


def _file_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _diverse_pool():
    """A pool spanning outcomes and families (support/contra/unresolved/data)."""
    return [
        _row(1, "US imposes new tariffs on electric vehicle imports",
             tickers=[_tk("TSLA", "support")]),                  # support/tariff
        _row(2, "OPEC extends voluntary oil output cuts",
             tickers=[_tk("XLE", "support")]),                   # support/supply
        _row(3, "Iran threatens to close the Strait of Hormuz",
             tickers=[_tk("USO", "contradict")]),                # contra/supply
        _row(4, "DOJ files antitrust suit; monopoly power alleged",
             tickers=[_tk("GOOGL", "contradict")]),              # contra/regulation
        _row(5, "Federal Reserve holds interest rates steady",
             tickers=[_tk("TLT")]),                              # neutral/monetary
        _row(6, "Ceasefire talks begin as peace deal nears",
             tickers=[_tk("ITA")]),                              # neutral/ceasefire
    ]


# ---------------------------------------------------------------------------
# Outcome bucketing (pure)
# ---------------------------------------------------------------------------


class TestOutcomeBucket(unittest.TestCase):
    def test_support_when_any_supporting_ticker(self):
        self.assertEqual(
            W.outcome_bucket([_tk("A", "support")], has_es=True), "support")

    def test_contradiction_when_only_contradicting(self):
        self.assertEqual(
            W.outcome_bucket([_tk("A", "contradict")], has_es=True),
            "contradiction")

    def test_unresolved_when_neutral_but_has_event_study(self):
        self.assertEqual(
            W.outcome_bucket([_tk("A")], has_es=True), "unresolved")

    def test_data_limited_when_neutral_and_no_event_study(self):
        self.assertEqual(
            W.outcome_bucket([_tk("A")], has_es=False), "data_limited")


# ---------------------------------------------------------------------------
# Deterministic, outcome-diverse selection
# ---------------------------------------------------------------------------


class TestSelection(unittest.TestCase):
    def _build(self, n_cases=6):
        rows = _diverse_pool()
        edq = _edq_report([_edq_event(r["event_id"]) for r in rows])
        es_av = {}
        es_av.update(_es_available(1))
        es_av.update(_es_available(2))
        es_av.update(_es_available(3))
        es_av.update(_es_available(4))
        es_av.update(_es_available(5))  # row5 neutral + es -> unresolved
        return W.build_walkthrough(rows=rows, edq_report=edq,
                                   es_available=es_av, es_insufficient={},
                                   n_cases=n_cases)

    def test_selection_is_deterministic(self):
        a = [c["event_id"] for c in self._build()["selected_cases"]]
        b = [c["event_id"] for c in self._build()["selected_cases"]]
        self.assertEqual(a, b)

    def test_selection_is_outcome_diverse(self):
        rep = self._build()
        chk = rep["outcome_diversity_check"]
        self.assertGreaterEqual(chk["support_count"], 1)
        self.assertGreaterEqual(chk["contradiction_count"], 1)
        self.assertGreaterEqual(chk["unresolved_or_limited_count"], 1)
        self.assertIs(chk["passes"], True)

    def test_selection_is_not_winners_only(self):
        rep = self._build()
        buckets = {c["outcome_bucket"] for c in rep["selected_cases"]}
        self.assertNotEqual(buckets, {"support"})

    def test_selected_are_accepted_input_rows_only(self):
        rep = self._build()
        pool_ids = {r["event_id"] for r in _diverse_pool()}
        for c in rep["selected_cases"]:
            self.assertIn(c["event_id"], pool_ids)

    def test_first_three_roles_are_the_required_diverse_roles(self):
        rep = self._build()
        roles = [c["case_role"] for c in rep["selected_cases"][:3]]
        self.assertIn("support_case", roles)
        self.assertIn("contradiction_case", roles)
        self.assertIn("unresolved_or_limited_case", roles)

    def test_family_diversity_preferred_in_fills(self):
        rep = self._build()
        fams = {tuple(c["family_overlay"]) for c in rep["selected_cases"]}
        self.assertGreater(len(fams), 1)

    def test_n_cases_respected(self):
        rep = self._build(n_cases=4)
        self.assertEqual(len(rep["selected_cases"]), 4)


# ---------------------------------------------------------------------------
# Per-case assembly
# ---------------------------------------------------------------------------


class TestCaseAssembly(unittest.TestCase):
    def _rep(self, **kw):
        rows = _diverse_pool()
        edq = _edq_report([_edq_event(r["event_id"]) for r in rows])
        es_av = {}
        for i in (1, 2, 3, 4, 5):
            es_av.update(_es_available(i))
        return W.build_walkthrough(rows=rows, edq_report=edq,
                                   es_available=es_av, es_insufficient={}, **kw)

    def test_each_case_has_required_fields(self):
        rep = self._rep()
        for c in rep["selected_cases"]:
            for key in ("event_id", "headline", "event_date", "family_overlay",
                        "track_record_outcome", "outcome_bucket", "case_role",
                        "what_changed", "mechanism_summary",
                        "transmission_chain", "named_assets",
                        "event_date_quality", "event_date_caveat",
                        "reaction_readout", "sensitivity_or_scoring_caveat",
                        "case_read", "falsifier_or_limit", "non_claims"):
                self.assertIn(key, c, key)

    def test_reaction_readout_present_when_event_study_available(self):
        rep = self._rep()
        c = next(c for c in rep["selected_cases"] if c["event_id"] == 1)
        rr = c["reaction_readout"]
        self.assertIs(rr["ar_sar_car_if_available"], True)
        self.assertIsNotNone(rr["horizon_1d"])
        self.assertIsNotNone(rr["horizon_5d"])
        self.assertIsNotNone(rr["horizon_20d"])

    def test_missing_event_study_surfaced_not_omitted(self):
        rows = _diverse_pool()
        edq = _edq_report([_edq_event(r["event_id"]) for r in rows])
        # NO event-study available for anyone; some rows become data_limited.
        rep = W.build_walkthrough(rows=rows, edq_report=edq,
                                  es_available={},
                                  es_insufficient={3: {"blocking_reasons":
                                                       ["no_primary_ticker"]}})
        c = next(c for c in rep["selected_cases"] if c["event_id"] == 3)
        rr = c["reaction_readout"]
        self.assertIs(rr["ar_sar_car_if_available"], False)
        self.assertIsNone(rr["horizon_1d"])
        self.assertTrue(rr["missingness_note"])
        self.assertGreaterEqual(
            rep["missingness_summary"]["cases_missing_event_study"], 1)

    def test_sensitivity_caveat_reports_multiple_rules(self):
        rep = self._rep()
        c = rep["selected_cases"][0]
        sc = c["sensitivity_or_scoring_caveat"]
        for rule in ("any_support", "majority", "all_support_strict"):
            self.assertIn(rule, sc)

    def test_denominators_passthrough(self):
        rep = self._rep()
        d = rep["denominators"]
        self.assertEqual(d["accepted_track_record_denominator"], 86)
        self.assertEqual(d["accepted_coverage_denominator"], 94)
        self.assertEqual(d["staged_candidate_count"], 13)

    def test_selection_policy_flags(self):
        rep = self._rep()
        sp = rep["selection_policy"]
        for flag in ("deterministic", "accepted_only",
                     "outcome_diversity_required", "family_diversity_preferred",
                     "winners_only_guard", "no_new_denominator"):
            self.assertIs(sp[flag], True)

    def test_named_assets_reflect_scored_tickers(self):
        rep = self._rep()
        c = next(c for c in rep["selected_cases"] if c["event_id"] == 1)
        scored = c["named_assets"]["scored"]
        self.assertTrue(any(a["symbol"] == "TSLA" for a in scored))


# ---------------------------------------------------------------------------
# Discipline / non-claims / banned framing
# ---------------------------------------------------------------------------


class TestDiscipline(unittest.TestCase):
    def _rep(self):
        rows = _diverse_pool()
        edq = _edq_report([_edq_event(r["event_id"]) for r in rows])
        es_av = {}
        for i in (1, 2, 3, 4, 5):
            es_av.update(_es_available(i))
        return W.build_walkthrough(rows=rows, edq_report=edq,
                                   es_available=es_av, es_insufficient={})

    def test_non_claims_cover_required_ground(self):
        blob = " ".join(self._rep()["non_claims"]).lower()
        for needle in ("representative", "not proof", "n=1", "descriptive",
                       "significance", "family-level", "recommendation",
                       "fdr", "paid", "denominator", "database"):
            self.assertIn(needle, blob)

    def test_taxonomy_lessons_present(self):
        tl = self._rep()["taxonomy_lessons"]
        self.assertTrue(tl["what_cases_show"])
        self.assertTrue(tl["what_cases_do_not_show"])
        self.assertTrue(tl["why_representative_cases_are_not_proof"])

    def test_banned_framing_absent_from_source_and_output(self):
        rep = self._rep()
        text = W._render_text(rep) + " " + json.dumps(rep)
        with open(os.path.join(_REPO, "scripts",
                               "transmission_case_walkthrough_report.py"),
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
    id                 INTEGER PRIMARY KEY,
    event_date         TEXT,
    stage              TEXT,
    mechanism_family   TEXT,
    headline           TEXT,
    market_tickers     TEXT,
    revisit_snapshots  TEXT,
    what_changed       TEXT,
    mechanism_summary  TEXT,
    transmission_chain TEXT,
    market_note        TEXT,
    notes              TEXT,
    assets_to_watch    TEXT,
    beneficiaries      TEXT,
    losers             TEXT,
    key_falsifiers     TEXT
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
            tempfile.gettempdir(), f"test_tcw_{uuid.uuid4().hex}.db")
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(_EVENTS_DDL)
            conn.execute(_PRICE_CACHE_DDL)
            conn.execute(_EVENT_HYGIENE_DDL)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def _mt(self, *pairs):
        return json.dumps([
            {"symbol": s, **({"direction_tag": d} if d else {})}
            for s, d in pairs])

    def _seed(self, eid, headline, *, family="none", tickers=(),
              event_date="2025-06-01"):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events (id,event_date,stage,mechanism_family,"
                "headline,market_tickers,mechanism_summary,what_changed,"
                "transmission_chain,market_note) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (eid, event_date, "realized", family, headline,
                 self._mt(*tickers),
                 "A substantive mechanism summary text body here.",
                 "A substantive what-changed sentence body here.",
                 "oil -> energy equities -> index", "A market note body."))
            conn.commit()

    def _seed_diverse(self):
        self._seed(1, "US imposes new tariffs on EV imports",
                   tickers=[("TSLA", "supports_thesis")])
        self._seed(2, "OPEC extends voluntary oil output cuts",
                   tickers=[("XLE", "supports_thesis")])
        self._seed(3, "Iran threatens to close the Strait of Hormuz",
                   tickers=[("USO", "contradicts_thesis")])
        self._seed(4, "Federal Reserve holds interest rates steady",
                   tickers=[("TLT", None)])

    def test_build_never_writes_database(self):
        self._seed_diverse()
        before = _file_sha256(self._tmp)
        W.build_walkthrough(db_path=self._tmp)
        self.assertEqual(_file_sha256(self._tmp), before)

    def test_denominator_is_seeded_accepted_count(self):
        self._seed_diverse()
        rep = W.build_walkthrough(db_path=self._tmp)
        self.assertEqual(
            rep["denominators"]["accepted_track_record_denominator"], 4)

    def test_db_family_column_untouched(self):
        self._seed_diverse()
        W.build_walkthrough(db_path=self._tmp)
        with sqlite3.connect(self._tmp) as conn:
            fams = [r[0] for r in conn.execute(
                "SELECT mechanism_family FROM events").fetchall()]
        self.assertTrue(all(f == "none" for f in fams))

    def test_outcome_diversity_passes_on_fixture(self):
        self._seed_diverse()
        rep = W.build_walkthrough(db_path=self._tmp)
        self.assertIs(rep["outcome_diversity_check"]["passes"], True)


# ---------------------------------------------------------------------------
# Rendering / CLI
# ---------------------------------------------------------------------------


class TestRendering(unittest.TestCase):
    def _rep(self):
        rows = _diverse_pool()
        edq = _edq_report([_edq_event(r["event_id"]) for r in rows])
        es_av = {}
        for i in (1, 2, 3, 4, 5):
            es_av.update(_es_available(i))
        return W.build_walkthrough(rows=rows, edq_report=edq,
                                   es_available=es_av, es_insufficient={})

    def test_text_render_cp1252_with_required_sections(self):
        text = W._render_text(self._rep())
        text.encode("cp1252")
        low = text.lower()
        for section in ("denominator", "selected cases", "event-date",
                        "1d", "5d", "20d", "outcome diversity",
                        "missingness", "non-claims"):
            self.assertIn(section, low)

    def test_main_json_smoke(self):
        self.assertEqual(W.main(["--db-path", _NONEXISTENT, "--json"]), 0)

    def test_main_text_smoke(self):
        self.assertEqual(W.main(["--db-path", _NONEXISTENT]), 0)


# ---------------------------------------------------------------------------
# O2 - sector backdrop embedded from O1 (sector_baseline_availability_report)
# ---------------------------------------------------------------------------


def _o1_row(eid, *, etf="XLE", conf="high", available=True,
            moves=(0.011, 0.022, 0.033)):
    """An O1-shaped sector-availability row, for injection."""
    if available:
        av = {f"horizon_{h}d": {"available": True, "reason": None}
              for h in (1, 5, 20)}
        rm = {f"horizon_{h}d": m for h, m in zip((1, 5, 20), moves)}
        note = ""
    else:
        av = {f"horizon_{h}d": {"available": False,
                                "reason": f"forward_window_not_cached_{h}d"}
              for h in (1, 5, 20)}
        rm = {f"horizon_{h}d": None for h in (1, 5, 20)}
        note = f"Sector ETF {etf} has no computable window."
    return {
        "event_id": eid, "headline": "h", "event_date": "2025-06-01",
        "suggested_sector_etf": etf, "suggestion_confidence": conf,
        "suggestion_reason": "ticker_match_energy",
        "availability": av, "sector_raw_moves": rm,
        "missingness_note": note,
        "spy_canonical_note": ("Abnormal return remains SPY-relative "
                               "(canonical); the sector move above is the "
                               "ETF's own raw window change."),
    }


class TestSectorBackdrop(unittest.TestCase):
    _ETF_BY_ID = {1: "XLE", 2: "XLK", 3: "XLF", 4: "XLI", 5: "XLV", 6: "XLU"}

    def _rep(self, sector_by_id):
        rows = _diverse_pool()
        edq = _edq_report([_edq_event(r["event_id"]) for r in rows])
        es_av = {}
        for i in (1, 2, 3, 4, 5):
            es_av.update(_es_available(i))
        return W.build_walkthrough(rows=rows, edq_report=edq,
                                   es_available=es_av, es_insufficient={},
                                   sector_by_id=sector_by_id)

    def _all_available(self):
        return {i: _o1_row(i, etf=etf) for i, etf in self._ETF_BY_ID.items()}

    def test_each_selected_case_has_sector_backdrop(self):
        rep = self._rep(self._all_available())
        for c in rep["selected_cases"]:
            self.assertIn("sector_backdrop", c)

    def test_sector_backdrop_required_subfields(self):
        rep = self._rep(self._all_available())
        for c in rep["selected_cases"]:
            sb = c["sector_backdrop"]
            for key in ("suggested_sector_etf", "suggestion_confidence",
                        "suggestion_reason", "availability",
                        "sector_raw_moves", "missingness_note",
                        "spy_canonical_note", "interpretation_note"):
                self.assertIn(key, sb, key)
            for h in ("horizon_1d", "horizon_5d", "horizon_20d"):
                self.assertIn(h, sb["availability"])
                self.assertIn(h, sb["sector_raw_moves"])

    def test_sector_backdrop_sourced_from_injected_o1_data(self):
        # The backdrop must echo the O1 row for that event_id, not recompute it.
        rep = self._rep(self._all_available())
        for c in rep["selected_cases"]:
            self.assertEqual(c["sector_backdrop"]["suggested_sector_etf"],
                             self._ETF_BY_ID[c["event_id"]])

    def test_no_sector_relative_abnormal_return_key(self):
        rep = self._rep(self._all_available())
        for c in rep["selected_cases"]:
            sb = c["sector_backdrop"]
            self.assertNotIn("sector_relative_abnormal_return", sb)
            for key in list(sb.keys()):
                low = key.lower()
                self.assertNotIn("abnormal", low)
                self.assertNotIn("sector_sar", low)
                self.assertNotIn("sector_car", low)

    def test_unavailable_sector_window_surfaced_not_omitted(self):
        sector_by_id = {i: _o1_row(i, etf=etf, available=False)
                        for i, etf in self._ETF_BY_ID.items()}
        rep = self._rep(sector_by_id)
        any_case = rep["selected_cases"][0]["sector_backdrop"]
        self.assertFalse(any_case["availability"]["horizon_1d"]["available"])
        self.assertTrue(any_case["missingness_note"])
        self.assertIsNone(any_case["sector_raw_moves"]["horizon_1d"])

    def test_missing_o1_row_degrades_to_unavailable(self):
        rep = self._rep({})  # no O1 rows for any id
        for c in rep["selected_cases"]:
            sb = c["sector_backdrop"]
            self.assertFalse(sb["availability"]["horizon_20d"]["available"])
            self.assertTrue(sb["missingness_note"])

    def test_spy_reaction_readout_unchanged_alongside_backdrop(self):
        rep = self._rep(self._all_available())
        for c in rep["selected_cases"]:
            rr = c["reaction_readout"]
            self.assertIn("ar_sar_car_if_available", rr)
            for h in ("horizon_1d", "horizon_5d", "horizon_20d"):
                self.assertIn(h, rr)

    def test_interpretation_note_states_spy_canonical_and_descriptive(self):
        rep = self._rep(self._all_available())
        for c in rep["selected_cases"]:
            note = c["sector_backdrop"]["interpretation_note"].lower()
            self.assertIn("descriptive", note)
            self.assertIn("spy", note)
            self.assertIn("no sector-relative abnormal return", note)
            self.assertTrue(c["sector_backdrop"]["spy_canonical_note"])

    def test_text_render_includes_sector_backdrop_line(self):
        text = W._render_text(self._rep(self._all_available()))
        self.assertIn("sector backdrop", text.lower())
        text.encode("cp1252")


_NONEXISTENT = os.path.join(tempfile.gettempdir(),
                            f"tcw_absent_{uuid.uuid4().hex}.db")


if __name__ == "__main__":
    unittest.main()
