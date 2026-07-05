"""Tests for the G3A mechanical-eligibility grinder (Mission G, g0-v1).

Contract under test:

* the transmission map is FROZEN at the family level (``g3-transmission-map-v1``):
  FOMC -> KRE / SPY / XLF, OPEC -> XOP / SPY / XLE, and nothing else;
* mapping is a pure function of family alone - no per-event override path, no
  dependence on event date or remembered historical importance;
* the input gate reconciles 65 + 32 = 97 unique candidates and fails LOUDLY on
  an unknown family, an id/lane family mismatch, or a duplicate id that would
  receive two different canonical mappings;
* the grinder reuses the SHIPPED event-study gate
  (``event_study_validation.build_event_study_validation``) under its default
  canonical basis policy - adjusted/adjusted preferred, matched raw/raw as the
  only fallback, never a cross-basis pair - and never reimplements it;
* the multi-code failure ledger captures ALL applicable failure codes, keeps
  the canonical (market-relative) and sector-relative layers independent, and
  preserves partial eligibility honestly;
* persisted rows and the rendered report carry ONLY whitelisted, outcome-blind
  fields - no AR / SAR / CAR / sector-relative return / sign / magnitude.

Pure fixtures build a temp ``price_cache`` DB and rebind ``db.DB_FILE``; no
network. Live-ledger reconciliation tests skip when the artifacts are absent.
"""
from __future__ import annotations

import inspect
import json
import sqlite3
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as _db  # noqa: E402
from scripts import g3_mechanical_grinder as g3  # noqa: E402

G1A = ROOT / "stats" / "G1A_FOMC_FRAME_INVENTORY.md"
G1B = ROOT / "stats" / "G1B_OPEC_DESIGNED_RESERVOIR.md"
_LEDGERS = G1A.exists() and G1B.exists()


def _fomc(cid="fomc-policy-decision-2020-03-15", d="2020-03-15"):
    return {"candidate_id": cid, "event_date": d,
            "lane": "frame_complete_historical"}


def _opec(cid="opec-2020-04-12-cut-9p7", d="2020-04-12"):
    return {"candidate_id": cid, "event_date": d, "lane": "designed_contrast"}


# ---------------------------------------------------------------------------
# 1. Frozen transmission mapping (family-level)
# ---------------------------------------------------------------------------


class MappingTests(unittest.TestCase):
    def test_mapping_version_is_frozen_v1(self):
        self.assertEqual(g3.MAPPING_VERSION, "g3-transmission-map-v1")

    def test_fomc_maps_to_kre_spy_xlf(self):
        lens = g3.map_candidate(_fomc())
        self.assertEqual(lens.family, "fomc")
        self.assertEqual(lens.primary, "KRE")
        self.assertEqual(lens.market, "SPY")
        self.assertEqual(lens.sector, "XLF")
        self.assertTrue(lens.interpretation)
        self.assertTrue(lens.claim_ceiling)

    def test_opec_maps_to_xop_spy_xle(self):
        lens = g3.map_candidate(_opec())
        self.assertEqual(lens.family, "opec")
        self.assertEqual(lens.primary, "XOP")
        self.assertEqual(lens.market, "SPY")
        self.assertEqual(lens.sector, "XLE")
        self.assertTrue(lens.interpretation)
        self.assertTrue(lens.claim_ceiling)

    def test_only_two_families_exist(self):
        self.assertEqual(set(g3.TRANSMISSION_MAP), {"fomc", "opec"})

    def test_no_third_asset_family(self):
        # No mapping introduces an asset outside the two frozen lenses.
        primaries = {l.primary for l in g3.TRANSMISSION_MAP.values()}
        self.assertEqual(primaries, {"KRE", "XOP"})


# ---------------------------------------------------------------------------
# 2. No per-event override; mapping depends on family alone
# ---------------------------------------------------------------------------


class NoOverrideTests(unittest.TestCase):
    def test_two_fomc_candidates_map_identically(self):
        a = g3.map_candidate(_fomc("fomc-policy-decision-2018-01-31",
                                   "2018-01-31"))
        b = g3.map_candidate(_fomc("fomc-policy-decision-2025-12-10",
                                   "2025-12-10"))
        self.assertEqual(a, b)

    def test_mapping_ignores_event_date(self):
        base = _opec()
        moved = dict(base, event_date="2022-10-05")
        self.assertEqual(g3.map_candidate(base), g3.map_candidate(moved))

    def test_map_candidate_has_no_override_parameter(self):
        params = list(inspect.signature(g3.map_candidate).parameters)
        self.assertEqual(params, ["candidate"], params)


# ---------------------------------------------------------------------------
# 3. Input gate fails loudly
# ---------------------------------------------------------------------------


class InputGateTests(unittest.TestCase):
    def test_unknown_lane_raises(self):
        with self.assertRaises(ValueError):
            g3.map_candidate({"candidate_id": "x-1", "event_date": "2020-01-01",
                              "lane": "some_other_lane"})

    def test_id_prefix_mismatch_raises(self):
        # OPEC lane but an FOMC-style id: the cross-check must reject it.
        with self.assertRaises(ValueError):
            g3.map_candidate({"candidate_id": "fomc-policy-decision-2020-03-15",
                              "event_date": "2020-03-15",
                              "lane": "designed_contrast"})

    def test_duplicate_id_raises(self):
        # A repeated candidate id would receive its mapping twice; the input
        # gate must reject it rather than double-count or silently dedupe.
        dupe = [_fomc(), _fomc()]
        with self.assertRaises(ValueError):
            g3.reconcile(dupe)

    def test_every_candidate_receives_exactly_one_mapping(self):
        cands = [_fomc(), _opec()]
        mapped = g3.map_all(cands)
        self.assertEqual(set(mapped), {"fomc-policy-decision-2020-03-15",
                                       "opec-2020-04-12-cut-9p7"})
        for lens in mapped.values():
            self.assertIn(lens.family, ("fomc", "opec"))


# ---------------------------------------------------------------------------
# 4. Live-ledger reconciliation (65 + 32 = 97, unique)
# ---------------------------------------------------------------------------


@unittest.skipUnless(_LEDGERS, "G1A/G1B ledgers absent")
class ReconciliationTests(unittest.TestCase):
    def test_reconciles_to_65_32_97_unique(self):
        cands = g3.load_candidates()
        rec = g3.reconcile(cands)
        self.assertEqual(rec["g1a"], 65)
        self.assertEqual(rec["g1b"], 32)
        self.assertEqual(rec["total"], 97)
        self.assertEqual(rec["unique"], 97)

    def test_all_live_candidates_map_without_raising(self):
        cands = g3.load_candidates()
        fams = {g3.map_candidate(c).family for c in cands}
        self.assertEqual(fams, {"fomc", "opec"})


# ---------------------------------------------------------------------------
# 5. Grinder core: 7-stage eval, multi-code failure ledger, basis policy.
#    Pure fixtures build a temp price_cache DB; the grinder reuses the SHIPPED
#    gate (event_study_validation) against the rebound db.DB_FILE.
# ---------------------------------------------------------------------------


_EVENT_D = date(2026, 3, 16)   # a Monday
_EVENT_ISO = _EVENT_D.isoformat()

_BASE = {"KRE": 50.0, "XLF": 30.0, "XOP": 40.0, "XLE": 70.0, "SPY": 100.0}
# Distinct idiosyncratic wiggles so the abnormal-return series has non-zero
# variance against BOTH the market (SPY, smooth) and the sector ETF - a shared
# wiggle would cancel and force sigma≈0 (engine unavailable) for the wrong
# reason.
_WIGGLE = {"KRE": 0.004, "XLF": 0.002, "XOP": 0.004, "XLE": 0.0025, "SPY": 0.0}


def _bdays_before(anchor, count):
    out, cur = [], anchor
    while len(out) < count:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    out.reverse()
    return out


def _bdays_after(anchor, count):
    out, cur = [], anchor
    while len(out) < count:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    return out


def _close(i, base, wiggle):
    return round(base * (1 + 0.0005 * i + wiggle * ((-1) ** i)), 4)


def _dates(pre=65, post=25):
    return _bdays_before(_EVENT_D, pre) + [_EVENT_D] + _bdays_after(_EVENT_D, post)


def _rows(ticker, flags=(0, 1), *, pre=65, post=25):
    """price_cache rows (ticker, iso, close, auto_adjust) for one ticker."""
    ds = _dates(pre, post)
    b, w = _BASE[ticker], _WIGGLE[ticker]
    return [(ticker, d.isoformat(), _close(i, b, w), aa)
            for aa in flags for i, d in enumerate(ds)]


def _seed_price_db(path, rows):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, "
            "volume REAL, auto_adjust INTEGER, fetched_at TEXT, "
            "source_provider TEXT, PRIMARY KEY (ticker, date, auto_adjust))")
        conn.executemany(
            "INSERT INTO price_cache (ticker, date, close, volume, auto_adjust, "
            "fetched_at, source_provider) VALUES (?,?,?,?,?,?,?)",
            [(t, d, c, 1000.0, aa, "2026-01-01T00:00:00", "test")
             for (t, d, c, aa) in rows])
        conn.commit()
    finally:
        conn.close()


class _DbRebind:
    """Point db.DB_FILE at a temp DB for the duration of a test."""

    def __init__(self, path):
        self.path = path
        self._saved = None

    def __enter__(self):
        self._saved = _db.DB_FILE
        _db.DB_FILE = self.path
        return self

    def __exit__(self, *exc):
        _db.DB_FILE = self._saved


def _grind_fomc(tmpdir, rows, *, event=_EVENT_ISO):
    path = str(Path(tmpdir) / "g3.db")
    _seed_price_db(path, rows)
    with _DbRebind(path):
        return g3.grind_candidate(_fomc("fomc-policy-decision-" + event, event))


import tempfile  # noqa: E402


class GrinderBasisTests(unittest.TestCase):
    def test_full_ready_passes_all_stages_adjusted_basis(self):
        rows = _rows("KRE") + _rows("SPY") + _rows("XLF")
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        self.assertEqual(row["failure_codes"], [])
        self.assertTrue(row["availability"]["canonical_event_study_available"])
        self.assertTrue(row["availability"]["sector_relative_available"])
        self.assertEqual(row["canonical_basis"], "adjusted")

    def test_matched_raw_fallback_when_adjusted_unavailable(self):
        # Primary has only raw (auto_adjust=0) rows: the adjusted/adjusted pair
        # is not computable, so the canonical policy falls back to matched
        # raw/raw and DISCLOSES it. Never a cross pair.
        rows = _rows("KRE", flags=(0,)) + _rows("SPY") + _rows("XLF")
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        self.assertTrue(row["availability"]["canonical_event_study_available"])
        self.assertEqual(row["canonical_basis"], "raw_fallback")
        self.assertEqual(row["failure_codes"], [])

    def test_no_cross_basis_pair_gates_to_unavailable(self):
        # Primary adjusted-only, market raw-only: the ONLY alignable pair is
        # cross (adj asset vs raw benchmark). The canonical policy excludes it,
        # so the stage is unavailable and NO cross basis is ever recorded -
        # even though both tickers are present.
        rows = (_rows("KRE", flags=(1,)) + _rows("SPY", flags=(0,))
                + _rows("XLF"))
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        self.assertTrue(row["availability"]["primary_price_available"])
        self.assertTrue(row["availability"]["market_benchmark_available"])
        self.assertFalse(row["availability"]["canonical_event_study_available"])
        self.assertIn("canonical_event_study_unavailable", row["failure_codes"])
        self.assertIsNone(row["canonical_basis"])
        self.assertNotEqual(row["canonical_basis"], "cross")


class GrinderFailureCodeTests(unittest.TestCase):
    def test_primary_price_missing_and_canonical_unavailable(self):
        rows = _rows("SPY") + _rows("XLF")   # no KRE at all
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        self.assertFalse(row["availability"]["primary_price_available"])
        self.assertIn("primary_price_missing", row["failure_codes"])
        self.assertIn("canonical_event_study_unavailable", row["failure_codes"])

    def test_market_benchmark_missing(self):
        rows = _rows("KRE") + _rows("XLF")   # no SPY
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        self.assertFalse(row["availability"]["market_benchmark_available"])
        self.assertIn("market_benchmark_missing", row["failure_codes"])
        self.assertIn("canonical_event_study_unavailable", row["failure_codes"])

    def test_short_estimation_window_fails_canonical_not_presence(self):
        # KRE present but with fewer than 60 pre-event bars: history is
        # 'available' (stage 3) yet the canonical event study is not (stage 5).
        rows = (_rows("KRE", pre=40) + _rows("SPY", pre=65)
                + _rows("XLF", pre=65))
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        self.assertTrue(row["availability"]["primary_price_available"])
        self.assertNotIn("primary_price_missing", row["failure_codes"])
        self.assertFalse(row["availability"]["canonical_event_study_available"])
        self.assertIn("canonical_event_study_unavailable", row["failure_codes"])

    def test_sector_benchmark_missing_keeps_canonical_available(self):
        # Partial eligibility: canonical (market-relative) is available; only
        # the sector layer is missing. A missing sector layer is NOT a complete
        # event-study failure.
        rows = _rows("KRE") + _rows("SPY")   # no XLF
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        self.assertTrue(row["availability"]["canonical_event_study_available"])
        self.assertNotIn("canonical_event_study_unavailable",
                         row["failure_codes"])
        self.assertFalse(row["availability"]["sector_benchmark_available"])
        self.assertIn("sector_benchmark_missing", row["failure_codes"])
        self.assertIn("sector_relative_unavailable", row["failure_codes"])

    def test_sector_present_but_short_fails_only_sector_relative(self):
        rows = (_rows("KRE", pre=65) + _rows("SPY", pre=65)
                + _rows("XLF", pre=40))
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        self.assertTrue(row["availability"]["canonical_event_study_available"])
        self.assertTrue(row["availability"]["sector_benchmark_available"])
        self.assertNotIn("sector_benchmark_missing", row["failure_codes"])
        self.assertFalse(row["availability"]["sector_relative_available"])
        self.assertIn("sector_relative_unavailable", row["failure_codes"])

    def test_multiple_failure_codes_captured_together(self):
        rows = _rows("SPY")   # only market present; no KRE, no XLF
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        for code in ("primary_price_missing", "canonical_event_study_unavailable",
                     "sector_benchmark_missing", "sector_relative_unavailable"):
            self.assertIn(code, row["failure_codes"], code)
        self.assertGreaterEqual(len(row["failure_codes"]), 4)

    def test_mapping_missing_is_a_defined_zero_by_input_gate_code(self):
        # The code exists in the ledger vocabulary; the loud input gate
        # guarantees it never fires in a real run (unknown family raises).
        self.assertIn("mapping_missing", g3.FAILURE_CODES)


# ---------------------------------------------------------------------------
# 6. Outcome-blindness firewall (persisted bytes, not just keys)
# ---------------------------------------------------------------------------


_BANNED = ("abnormal", "abnormal_return", "sar", "car", "raw_return",
           "sector_relative_return", "benchmark_return", "sigma",
           "sign", "direction", "magnitude", "effect", "outcome", "per_horizon")


class FirewallTests(unittest.TestCase):
    def test_row_fields_whitelisted(self):
        rows = _rows("KRE") + _rows("SPY") + _rows("XLF")
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        self.assertTrue(set(row).issubset(g3.G3_ROW_FIELDS), set(row))
        self.assertTrue(set(row["availability"]).issubset(g3.STAGE_FLAGS),
                        set(row["availability"]))

    def test_row_bytes_carry_no_outcome_vocab(self):
        rows = _rows("KRE") + _rows("SPY") + _rows("XLF")
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        dumped = json.dumps(row).lower()
        for banned in _BANNED:
            self.assertNotIn(banned, dumped, banned)

    def test_row_holds_no_return_or_sigma_values(self):
        rows = _rows("KRE") + _rows("SPY") + _rows("XLF")
        with tempfile.TemporaryDirectory() as tmp:
            row = _grind_fomc(tmp, rows)
        self.assertNotIn("per_horizon", row)
        self.assertNotIn("sigma_ar_daily", row)
        self.assertNotIn("aligned_sample_size", row)


# ---------------------------------------------------------------------------
# 7. Aggregation (summarize) + deterministic report render
# ---------------------------------------------------------------------------


def _mkrow(*, family="fomc", event_date="2020-03-15", basis="adjusted",
           primary=True, market=True, canonical=True, sector_bench=True,
           sector=True, codes=None):
    lens = g3.TRANSMISSION_MAP[family]
    lane = ("frame_complete_historical" if family == "fomc"
            else "designed_contrast")
    return {
        "candidate_id": f"{family}-{event_date}",
        "lane": lane, "family": family, "family_label": lens.family_label,
        "event_date": event_date, "primary_asset": lens.primary,
        "market_benchmark": lens.market, "sector_benchmark": lens.sector,
        "canonical_basis": basis if canonical else None,
        "availability": {
            "identity_valid": True, "mapped": True,
            "primary_price_available": primary,
            "market_benchmark_available": market,
            "canonical_event_study_available": canonical,
            "sector_benchmark_available": sector_bench,
            "sector_relative_available": sector,
        },
        "failure_codes": list(codes or []),
        "mapping_version": g3.MAPPING_VERSION,
    }


class SummarizeTests(unittest.TestCase):
    def test_funnel_is_monotone_non_increasing(self):
        rows = [
            _mkrow(),                                      # all pass
            _mkrow(family="opec", event_date="2021-01-01"),
            _mkrow(event_date="2019-06-06", canonical=False,
                   sector=False, basis=None,
                   codes=["canonical_event_study_unavailable",
                          "sector_relative_unavailable"]),
            _mkrow(event_date="2018-03-21", sector=False,
                   codes=["sector_relative_unavailable"]),
        ]
        s = g3.summarize(rows)
        funnel = s["funnel"]["total"]
        self.assertEqual(len(funnel), 5)
        for a, b in zip(funnel, funnel[1:]):
            self.assertGreaterEqual(a, b)
        self.assertEqual(funnel[0], 4)   # identity-valid
        self.assertEqual(funnel[3], 3)   # canonical available
        self.assertEqual(funnel[4], 2)   # sector-relative available

    def test_basis_split_and_cross_is_zero(self):
        rows = [_mkrow(basis="adjusted"),
                _mkrow(event_date="2020-01-02", basis="raw_fallback"),
                _mkrow(event_date="2020-01-03", canonical=False, basis=None,
                       codes=["canonical_event_study_unavailable"])]
        s = g3.summarize(rows)
        self.assertEqual(s["basis"]["adjusted"], 1)
        self.assertEqual(s["basis"]["raw_fallback"], 1)
        self.assertEqual(s["basis"]["unavailable"], 1)
        self.assertEqual(s["basis"]["cross"], 0)

    def test_failure_composition_and_multi_failure_count(self):
        rows = [
            _mkrow(),
            _mkrow(event_date="2019-01-01", sector=False,
                   codes=["sector_relative_unavailable"]),
            _mkrow(event_date="2019-02-01", primary=False, canonical=False,
                   sector_bench=False, sector=False, basis=None,
                   codes=["primary_price_missing",
                          "canonical_event_study_unavailable",
                          "sector_benchmark_missing",
                          "sector_relative_unavailable"]),
        ]
        s = g3.summarize(rows)
        self.assertEqual(s["failure"]["by_code"]["sector_relative_unavailable"], 2)
        self.assertEqual(s["failure"]["by_code"]["primary_price_missing"], 1)
        self.assertEqual(s["failure"]["multi_failure"], 1)

    def test_date_structure_entering_vs_surviving(self):
        rows = [
            _mkrow(event_date="2020-03-15"),
            _mkrow(event_date="2020-03-15", family="opec"),   # shared date
            _mkrow(event_date="2019-06-06", canonical=False, basis=None,
                   codes=["canonical_event_study_unavailable"]),
        ]
        s = g3.summarize(rows)
        self.assertEqual(s["dates"]["entering_unique"], 2)    # two distinct
        self.assertEqual(s["dates"]["surviving_unique"], 1)   # only 2020-03-15


class RenderReportTests(unittest.TestCase):
    _META = {"retrieved_at": "2026-07-05T10:00:00+00:00",
             "tickers": {"KRE": 2200, "XLF": 2200, "XOP": 2200,
                         "XLE": 2200, "SPY": 2200}}

    def _summary(self):
        rows = [_mkrow(), _mkrow(family="opec", event_date="2021-01-01"),
                _mkrow(event_date="2019-06-06", sector=False,
                       codes=["sector_relative_unavailable"])]
        return g3.summarize(rows)

    def test_render_is_byte_deterministic(self):
        s = self._summary()
        a = g3.render_report(s, cache_meta=self._META, cache_sha256="deadbeef")
        b = g3.render_report(s, cache_meta=self._META, cache_sha256="deadbeef")
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("\n"))

    def test_render_contains_mapping_contract(self):
        s = self._summary()
        text = g3.render_report(s, cache_meta=self._META,
                                cache_sha256="deadbeef")
        for token in ("g3-transmission-map-v1", "KRE", "XOP", "XLF", "XLE",
                      "SPY", "regional-bank", "exploration"):
            self.assertIn(token, text, token)
        self.assertIn("not the complete market reaction", text)   # FOMC ceiling
        self.assertIn("not a complete measure", text)             # OPEC ceiling
        self.assertIn("no event-specific override", text.lower())

    def test_render_declares_outcome_absence_and_leaks_no_values(self):
        # Like the G2D artifact, the non-claims disclaimer legitimately NAMES
        # the excluded outcomes; what must never appear is an actual outcome
        # VALUE. Ban only the data/field forms that would signal a leak.
        s = self._summary()
        text = g3.render_report(s, cache_meta=self._META,
                                cache_sha256="deadbeef")
        low = text.lower()
        self.assertIn("no market response", low)          # explicit disclaimer
        for leak in ("raw_return", "abnormal_return", "sector_relative_return",
                     "sigma_ar", "auto_adjust_basis", "per_horizon"):
            self.assertNotIn(leak, low, leak)


class PriceDbBuilderTests(unittest.TestCase):
    def test_build_price_db_is_gate_readable(self):
        # The acquisition builder writes a DB the shipped gate can read: same
        # price_cache schema, both auto_adjust bases, correct dates.
        ds = [d.isoformat() for d in _dates()]
        raw = {d: 100.0 for d in ds}
        adj = {d: 101.0 for d in ds}
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "g3_price.db")
            g3.build_price_db(path, {"SPY": (raw, adj)},
                              fetched_at="2026-01-01T00:00:00+00:00")
            with _DbRebind(path):
                self.assertEqual(g3._cached_dates("SPY"), set(ds))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
