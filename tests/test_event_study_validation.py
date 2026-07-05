"""Tests for ``event_study_validation.build_event_study_validation``.

Covers the gated single-event proof:

* a ready event returns ``event_study_available`` with per-horizon
  SAR/CAR and CI explicitly unavailable at n=1;
* non-ready events return ``insufficient_data`` with specific reasons
  (no ticker, missing forward cache);
* an event that passes the date-union gates but whose intersected window
  has an interior gap is caught by the contiguity guard (the silent-wrong
  -SAR landmine);
* the module performs no provider/network call and reads no Phase 1/2
  FDR-pool artifacts.

All reads go through ``db.DB_FILE`` (rebound to a temp price-cache DB);
no live archive is touched.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as _db  # noqa: E402
import event_study_validation as esv  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _bdays_before(anchor: date, count: int) -> list[date]:
    """``count`` business days strictly before ``anchor`` (ascending)."""
    out: list[date] = []
    cur = anchor
    while len(out) < count:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    out.reverse()
    return out


def _bdays_after(anchor: date, count: int) -> list[date]:
    out: list[date] = []
    cur = anchor
    while len(out) < count:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    return out


def _close(i: int, base: float, *, noise: bool = True, jump_from: int | None = None) -> float:
    # The ticker carries an alternating idiosyncratic term the (smooth)
    # benchmark does not, so the daily abnormal-return series has a
    # non-zero variance → positive sigma in the estimation window.  The
    # optional post-event jump creates a clear abnormal return.
    val = base * (1 + 0.0005 * i + (0.003 * ((-1) ** i) if noise else 0.0))
    if jump_from is not None and i >= jump_from:
        val *= 1.04
    return round(val, 4)


def _make_price_db(path: str, rows: list[tuple]) -> None:
    """rows: (ticker, iso_date, close, auto_adjust_int)."""
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, "
            "volume REAL, auto_adjust INTEGER, fetched_at TEXT, "
            "PRIMARY KEY (ticker, date, auto_adjust))"
        )
        conn.executemany(
            "INSERT INTO price_cache (ticker, date, close, volume, auto_adjust, "
            "fetched_at) VALUES (?,?,?,?,?,?)",
            [(t, d, c, 1000.0, aa, "2026-01-01T00:00:00") for (t, d, c, aa) in rows],
        )
        conn.commit()
    finally:
        conn.close()


_EVENT_D = date(2026, 3, 16)  # a Monday
_EVENT_ISO = _EVENT_D.isoformat()


def _ready_rows() -> list[tuple]:
    pre = _bdays_before(_EVENT_D, 65)
    post = _bdays_after(_EVENT_D, 25)
    dates = pre + [_EVENT_D] + post
    event_index = len(pre)
    # Jump starts the day AFTER the event so the event-date anchor close is
    # pre-jump; the abnormal return then shows up in the forward window.
    rows: list[tuple] = []
    for i, d in enumerate(dates):
        rows.append(("SPY", d.isoformat(), _close(i, 100.0, noise=False), 0))
        rows.append(("XLE", d.isoformat(), _close(i, 50.0, jump_from=event_index + 1), 0))
    return rows


class _DbRebind:
    """Point db.DB_FILE at a temp DB for the duration of a test."""

    def __init__(self, path: str):
        self.path = path
        self._saved = None

    def __enter__(self):
        self._saved = _db.DB_FILE
        _db.DB_FILE = self.path
        return self

    def __exit__(self, *exc):
        _db.DB_FILE = self._saved


class ReadyEventTest(unittest.TestCase):
    def test_ready_event_returns_event_study_payload(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, _ready_rows())
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 1, "event_date": _EVENT_ISO,
                    "market_tickers": [{"symbol": "XLE"}],
                })
        self.assertEqual(out["status"], "event_study_available")
        self.assertEqual(out["primary_ticker"], "XLE")
        self.assertEqual(out["benchmark"], "SPY")
        self.assertEqual(out["auto_adjust_basis"], {"asset": False, "benchmark": False})
        self.assertNotIn("basis_caveat", out)  # matched flags → no bias caveat
        self.assertGreater(out["sigma_ar_daily"], 0.0)
        horizons = {row["horizon"]: row for row in out["per_horizon"]}
        self.assertEqual(set(horizons), {1, 5, 20})
        for h in (1, 5, 20):
            self.assertIsNotNone(horizons[h]["sar"], f"sar None at h={h}")
            self.assertIsNotNone(horizons[h]["abnormal_return"])
            self.assertIsNotNone(horizons[h]["car"])
        # Post-event +4% jump → positive abnormal return at h=20.
        self.assertGreater(horizons[20]["abnormal_return"], 0.0)

    def test_ready_event_marks_ci_unavailable_at_n1_and_makes_no_significance_claim(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, _ready_rows())
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 1, "event_date": _EVENT_ISO,
                    "market_tickers": [{"symbol": "XLE"}],
                })
        ci = out["cross_sectional_inference"]
        self.assertFalse(ci["available"])
        self.assertEqual(ci["n_events"], 1)
        self.assertEqual(ci["min_samples"], esv.MIN_COHORT_SAMPLES)
        # Never claims significance / validated for a single event.
        self.assertNotIn("statistically_significant", out)
        self.assertIn("confirmed", out["claims"]["not_claimed"])
        self.assertIn("validated", out["claims"]["not_claimed"])
        self.assertIn("confidence_interval", out["claims"]["not_claimed"])


class NonReadyEventTest(unittest.TestCase):
    def test_no_ticker_is_insufficient(self):
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, [])
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 2, "event_date": _EVENT_ISO, "market_tickers": [],
                })
        self.assertEqual(out["status"], "insufficient_data")
        self.assertIn("no_primary_ticker", out["blocking_reasons"])

    def test_missing_forward_cache_is_insufficient(self):
        # Primary ticker has a full pre-event window but no forward rows.
        pre = _bdays_before(_EVENT_D, 65)
        rows: list[tuple] = []
        for i, d in enumerate(pre + [_EVENT_D]):
            rows.append(("XLE", d.isoformat(), _close(i, 50.0), 0))
        # SPY fully covered (so the only gap is the primary's forward cache).
        for i, d in enumerate(pre + [_EVENT_D] + _bdays_after(_EVENT_D, 25)):
            rows.append(("SPY", d.isoformat(), _close(i, 100.0), 0))
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, rows)
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 3, "event_date": _EVENT_ISO,
                    "market_tickers": [{"symbol": "XLE"}],
                })
        self.assertEqual(out["status"], "insufficient_data")
        self.assertIn("missing_forward_cache_20d", out["blocking_reasons"])


class CrossFlagTest(unittest.TestCase):
    def _cross_rows(self) -> list[tuple]:
        # Asset cached ONLY adjusted (flag=1); benchmark ONLY raw (flag=0).
        return [(t, d, c, 1 if t == "XLE" else 0) for (t, d, c, _aa) in _ready_rows()]

    def test_cross_flag_split_is_insufficient_under_canonical_policy(self):
        # F3 canonical policy: the default order carries NO cross-basis pair,
        # so a series split across flags gates to insufficient rather than
        # silently mixing an adjusted asset with a raw benchmark.
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, self._cross_rows())
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 5, "event_date": _EVENT_ISO,
                    "market_tickers": [{"symbol": "XLE"}],
                })
        self.assertEqual(out["status"], "insufficient_data")

    def test_cross_flag_still_computes_when_forced_explicitly(self):
        # The F2 forced-basis machinery is policy-exempt: an explicit cross
        # pair still computes (with the cross-basis caveat).
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, self._cross_rows())
            with _DbRebind(p):
                out = esv.build_event_study_validation(
                    {"id": 5, "event_date": _EVENT_ISO,
                     "market_tickers": [{"symbol": "XLE"}]},
                    flag_pairs=((True, False),))
        self.assertEqual(out["status"], "event_study_available")
        self.assertEqual(out["auto_adjust_basis"], {"asset": True, "benchmark": False})
        self.assertIn("basis_caveat", out)
        self.assertGreater(out["sigma_ar_daily"], 0.0)


class CanonicalBasisPolicyTests(unittest.TestCase):
    """F3 canonical default: matched adjusted preferred, matched raw fallback
    explicitly disclosed, no cross-basis pair."""

    def _both_flag_db(self, dtmp) -> str:
        rows: list[tuple] = []
        for (t, d, c, _aa) in _ready_rows():
            rows.append((t, d, c, 0))
            rows.append((t, d, round(c * 0.98, 4), 1))
        p = os.path.join(dtmp, "events.db")
        _make_price_db(p, rows)
        return p

    def _event(self) -> dict:
        return {"id": 7, "event_date": _EVENT_ISO,
                "market_tickers": [{"symbol": "XLE"}]}

    def test_adjusted_preferred_when_both_matched_bases_compute(self):
        with tempfile.TemporaryDirectory() as dtmp:
            with _DbRebind(self._both_flag_db(dtmp)):
                out = esv.build_event_study_validation(self._event())
        self.assertEqual(out["status"], "event_study_available")
        self.assertEqual(out["auto_adjust_basis"], {"asset": True, "benchmark": True})
        self.assertNotIn("basis_fallback", out)

    def test_raw_fallback_when_adjusted_unavailable_is_explicit(self):
        # raw-only cache: the canonical default must fall back to matched
        # raw/raw AND say so in the payload.
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, _ready_rows())  # aa=0 only
            with _DbRebind(p):
                out = esv.build_event_study_validation(self._event())
        self.assertEqual(out["status"], "event_study_available")
        self.assertEqual(out["auto_adjust_basis"], {"asset": False, "benchmark": False})
        self.assertEqual(out["basis_fallback"], "matched_raw_fallback")
        self.assertIn("adjusted", out["basis_fallback_note"].lower())

    def test_forced_pairs_bypass_policy_without_fallback_disclosure(self):
        # forced mode is not a policy fallback: no disclosure field
        with tempfile.TemporaryDirectory() as dtmp:
            with _DbRebind(self._both_flag_db(dtmp)):
                out = esv.build_event_study_validation(
                    self._event(), flag_pairs=((False, False),))
        self.assertEqual(out["status"], "event_study_available")
        self.assertEqual(out["auto_adjust_basis"], {"asset": False, "benchmark": False})
        self.assertNotIn("basis_fallback", out)


class ContiguityGuardTest(unittest.TestCase):
    def test_interior_gap_passes_date_gates_but_is_caught_by_contiguity(self):
        # SPY: fully contiguous 70 pre + event + 25 post.
        spy_dates = _bdays_before(_EVENT_D, 70) + [_EVENT_D] + _bdays_after(_EVENT_D, 25)
        # XLE pre-event: drop a 10-business-day run from the middle of the
        # 70, leaving 60 pre-event dates (>= ESTIMATION_WINDOW) but with a
        # ~2-week hole inside the closest-60 window the engine consumes.
        xle_pre_full = _bdays_before(_EVENT_D, 70)
        xle_pre = xle_pre_full[:25] + xle_pre_full[35:]  # remove indices 25..34
        self.assertGreaterEqual(len(xle_pre), esv.ESTIMATION_WINDOW)
        xle_dates = xle_pre + [_EVENT_D] + _bdays_after(_EVENT_D, 25)

        rows: list[tuple] = []
        for i, d in enumerate(spy_dates):
            rows.append(("SPY", d.isoformat(), _close(i, 100.0), 0))
        for i, d in enumerate(xle_dates):
            rows.append(("XLE", d.isoformat(), _close(i, 50.0), 0))

        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, rows)
            with _DbRebind(p):
                out = esv.build_event_study_validation({
                    "id": 4, "event_date": _EVENT_ISO,
                    "market_tickers": [{"symbol": "XLE"}],
                })
        # Date-union gates pass (>=60 pre, forward present), so the only
        # thing that can stop a wrong SAR is the contiguity guard.
        self.assertEqual(out["status"], "insufficient_data")
        self.assertIn("no_contiguous_aligned_window", out["blocking_reasons"])


class IsolationTest(unittest.TestCase):
    def test_module_imports_no_provider_or_fdr_pool(self):
        import ast
        src = (ROOT / "event_study_validation.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        # Actual imports — not docstring prose — must carry no provider /
        # network seam and no Phase 1/2 FDR-pool module.
        for forbidden in (
            "yfinance", "market_data", "market_check", "cohort_evidence",
        ):
            self.assertNotIn(forbidden, imported, f"unexpected import: {forbidden}")

    def test_does_not_reimplement_sar(self):
        # SAR/CAR must come from the existing engine, not a local formula.
        src = (ROOT / "event_study_validation.py").read_text(encoding="utf-8")
        self.assertIn("from stats.event_study import compute_event_study", src)


class EventDateAnchorInvariantTest(unittest.TestCase):
    """Event-date normalization invariants for the canonical event-study gate.

    Second Order stores every ``event_date`` as a plain ``YYYY-MM-DD`` calendar
    date and every ``timestamp`` as a naive ``YYYY-MM-DDTHH:MM:SS`` (no tz).
    Real archive rows exist whose ``event_date`` differs from ``timestamp[:10]``
    (the ingestion / headline date), so the two fields are semantically distinct
    calendar dates and the research gate must anchor on ``event_date``.  These
    tests pin the load-bearing contract that keeps every research and
    market-anchoring path in agreement:

      * the gate anchors on ``event_date`` and never rescues from the ingestion
        ``timestamp`` — so a row whose headline date differs can never be
        silently re-anchored;
      * the supported stored shapes (plain ``YYYY-MM-DD`` date; naive
        ``YYYY-MM-DDTHH:MM:SS``) normalize to their literal calendar date with
        no host-timezone dependence;
      * a missing / malformed ``event_date`` fails closed, never a plausible
        substitute.

    Behavioural, not structural: they assert that the same input yields the
    same canonical calendar date and that malformed input fails closed — not
    which helper any particular module happens to call.  Timezone-aware
    event-date semantics are intentionally left unspecified: no such value is
    stored or produced, so pinning a rollover rule would define an unsupported
    future contract.
    """

    def test_supported_stored_shapes_normalize_to_plain_calendar_date(self):
        # The only shapes the archive actually holds: a plain YYYY-MM-DD
        # event_date and a naive YYYY-MM-DDTHH:MM:SS timestamp.  Both normalize
        # to their literal calendar date with no dependence on the host
        # timezone (the parser reads no wall clock and converts no zone).
        # Teeth: fails if a naive value is reinterpreted through the host zone
        # (e.g. datetime.fromisoformat(...).astimezone(...).date()), which would
        # make the resolved date host-dependent.  Timezone-aware event-date
        # inputs are deliberately NOT asserted: none is stored or produced, so
        # their rollover behaviour is an unsupported future contract.
        self.assertEqual(esv._parse_iso_date("2026-01-15"), date(2026, 1, 15))
        self.assertEqual(esv._parse_iso_date("2026-04-03T22:08:35"), date(2026, 4, 3))

    def test_malformed_event_date_fails_closed(self):
        # Teeth: fails if a silent plausible-date substitute is introduced.
        for bad in ("2026-13-99", "2026-02-30", "not-a-date", "", None):
            self.assertIsNone(esv._parse_iso_date(bad), f"expected None for {bad!r}")

    def test_gate_anchors_on_event_date_not_ingestion_timestamp(self):
        # Mirrors the archive rows where event_date != timestamp[:10]: a valid
        # ingestion timestamp must NOT rescue a missing or malformed event_date.
        # Teeth: fails if a ``timestamp`` fallback is added into the gate.
        with tempfile.TemporaryDirectory() as dtmp:
            p = os.path.join(dtmp, "events.db")
            _make_price_db(p, [])
            with _DbRebind(p):
                missing_ed = esv.build_event_study_validation({
                    "id": 900, "event_date": None,
                    "timestamp": "2026-04-29T15:35:07",
                    "market_tickers": [{"symbol": "KRE"}],
                })
                malformed_ed = esv.build_event_study_validation({
                    "id": 901, "event_date": "2026-13-99",
                    "timestamp": "2026-04-29T15:35:07",
                    "market_tickers": [{"symbol": "KRE"}],
                })
        for out in (missing_ed, malformed_ed):
            self.assertEqual(out["status"], "insufficient_data")
            self.assertIn("missing_or_malformed_event_date", out["blocking_reasons"])


if __name__ == "__main__":
    unittest.main()
