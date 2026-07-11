"""Tests for the legacy directional-evidence recovery backfill.

Root cause under repair: accepted events analyzed before their 5d/20d
windows elapsed were stored with ``return_5d = None`` (so the canonical
5d-based ``direction_tag`` was uncomputable at write time) and were never
refreshed, even though the local ``price_cache`` now holds the raw
event-anchored bars.  The backfill re-derives ONLY the missing derived
fields through the canonical market_check primitives, cache-only (the
provider is blocked), and preserves missingness everywhere the stored
inputs remain insufficient.

Everything here runs on TEMP fixture databases; the real events.db is
never opened.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as _db  # noqa: E402
import market_check  # noqa: E402
from scripts import recover_directional_evidence as rde  # noqa: E402

EVENT_DATE = "2026-04-29"


def _bdays(start_iso: str, n: int) -> list[str]:
    out, d = [], date.fromisoformat(start_iso)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _ticker(symbol: str, role: str, *, r1=None, r5=None, r20=None,
            tag=None, extra=None) -> dict:
    t = {"symbol": symbol, "role": role, "label": "needs more evidence",
         "detail": "Not enough price data.", "direction_tag": tag,
         "return_1d": r1, "return_5d": r5, "return_20d": r20,
         "volume_ratio": None, "vs_xle_5d": None, "spark": []}
    if extra:
        t.update(extra)
    return t


def _insert_event(conn, event_id: int, stage: str, tickers) -> None:
    conn.execute(
        "INSERT INTO events (id, timestamp, headline, mechanism_summary, "
        "stage, persistence, event_date, market_tickers) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (event_id, f"{EVENT_DATE}T12:00:00", f"fixture event {event_id}",
         "fixture mechanism", stage, "structural", EVENT_DATE,
         json.dumps(tickers) if tickers is not None else None))


def _insert_bars(conn, symbol: str, closes: list[float],
                 start: str = EVENT_DATE) -> None:
    for d, c in zip(_bdays(start, len(closes)), closes):
        conn.execute(
            "INSERT OR REPLACE INTO price_cache "
            "(ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES (?,?,?,?,0,'2026-07-01T00:00:00')",
            (symbol, d, c, 1_000_000.0))


def build_fixture_db(path: str) -> None:
    """Fixture archive covering every protected behavior."""
    saved, saved_ready = _db.DB_FILE, _db._db_ready
    _db.DB_FILE = path
    try:
        _db.init_db()
        with sqlite3.connect(path) as conn:
            # A - recoverable: beneficiary rises, loser falls (bars cached)
            _insert_event(conn, 1, "realized", [
                _ticker("AAA", "beneficiary", r1=1.0),
                _ticker("BBB", "loser", r1=-0.8),
            ])
            _insert_bars(conn, "AAA",
                         [100, 101, 101.5, 102, 102.5, 103,
                          103.5, 104, 104, 104, 104, 104, 104, 104, 104,
                          104, 104, 104, 104, 104, 106, 106])
            _insert_bars(conn, "BBB",
                         [100, 99.5, 99, 98.5, 98, 97,
                          97, 97, 97, 97, 97, 97, 97, 97, 97,
                          97, 97, 97, 97, 97, 95, 95])
            # B - flat: r5 fills but stays non-directional
            _insert_event(conn, 2, "realized",
                          [_ticker("CCC", "beneficiary")])
            _insert_bars(conn, "CCC",
                         [100, 100.05, 100.1, 100.1, 100.15, 100.2,
                          100.2, 100.2])
            # C - no cached bars: must remain untouched
            _insert_event(conn, 3, "anticipation",
                          [_ticker("DDD", "beneficiary")])
            # D - non-thesis stage: out of scope even with same shape
            _insert_event(conn, 4, "curated_observation",
                          [_ticker("EEE", "beneficiary")])
            _insert_bars(conn, "EEE", [100, 105, 106, 107, 108, 110, 111])
            # E - synthetic seed: out of scope
            _insert_event(conn, 5, "realized",
                          [_ticker("FFF", "beneficiary")])
            _insert_bars(conn, "FFF", [100, 105, 106, 107, 108, 110, 111])
            conn.execute(
                "INSERT INTO event_hygiene (event_id, override_class, "
                "override_reason, created_at) VALUES "
                "(5, 'synthetic_seed', 'fixture', '2026-05-01T00:00:00')")
            # F - no tickers at all: out of scope
            _insert_event(conn, 6, "realized", None)
            # G - modern payload with directional evidence: byte-untouched
            _insert_event(conn, 7, "realized", [
                _ticker("GGG", "beneficiary", r1=1.0, r5=3.2, r20=4.0,
                        tag="supports ↑"),
            ])
            # H - malformed entries + verification-vetoed ticker
            _insert_event(conn, 8, "realized", [
                "not-a-dict",
                _ticker("III", "unknown-role"),
                _ticker("JJJ", "loser",
                        extra={"verification": {"status": "timed_out"}}),
            ])
            _insert_bars(conn, "III", [100, 105, 106, 107, 108, 110, 111])
            _insert_bars(conn, "JJJ", [100, 95, 94, 93, 92, 90, 90])
            conn.commit()
    finally:
        _db.DB_FILE, _db._db_ready = saved, saved_ready


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = str(self.tmp / "fixture_events.db")
        build_fixture_db(self.db_path)
        market_check._cache_data.clear()

    def _hash(self) -> str:
        return hashlib.sha256(Path(self.db_path).read_bytes()).hexdigest()

    def _tickers(self, event_id: int) -> list:
        with sqlite3.connect(self.db_path) as conn:
            raw = conn.execute(
                "SELECT market_tickers FROM events WHERE id=?",
                (event_id,)).fetchone()[0]
        return json.loads(raw) if raw else []


class PlanTests(FixtureCase):
    def test_scope_is_accepted_tickered_nondirectional_only(self):
        plan = rde.build_recovery_plan(self.db_path)
        ids = sorted(e["event_id"] for e in plan["events"])
        # 4 (non-thesis), 5 (synthetic), 6 (no tickers), 7 (directional)
        # are all out of scope.
        self.assertEqual(ids, [1, 2, 3, 8])
        self.assertEqual(plan["funnel"]["accepted"], 6)
        self.assertEqual(plan["funnel"]["with_tickers"], 5)
        self.assertEqual(plan["funnel"]["directional"], 1)
        self.assertEqual(plan["funnel"]["in_scope"], 4)

    def test_plan_is_read_only(self):
        before = self._hash()
        rde.build_recovery_plan(self.db_path)
        self.assertEqual(self._hash(), before)

    def test_recoverable_tickers_use_canonical_classifier(self):
        plan = rde.build_recovery_plan(self.db_path)
        ev1 = next(e for e in plan["events"] if e["event_id"] == 1)
        by_sym = {t["symbol"]: t for t in ev1["tickers"]}
        self.assertEqual(by_sym["AAA"]["new_fields"]["direction_tag"],
                         "supports ↑")
        self.assertEqual(by_sym["BBB"]["new_fields"]["direction_tag"],
                         "supports ↓")
        self.assertAlmostEqual(by_sym["AAA"]["new_fields"]["return_5d"],
                               3.0, places=6)
        # stored return_1d is never overwritten
        self.assertNotIn("return_1d", by_sym["AAA"]["new_fields"])

    def test_flat_recovers_returns_but_stays_non_directional(self):
        plan = rde.build_recovery_plan(self.db_path)
        ev2 = next(e for e in plan["events"] if e["event_id"] == 2)
        t = ev2["tickers"][0]
        self.assertIn("return_5d", t["new_fields"])
        self.assertLess(abs(t["new_fields"]["return_5d"]), 0.5)
        self.assertNotIn("direction_tag", t["new_fields"])

    def test_missing_bars_preserve_missingness(self):
        plan = rde.build_recovery_plan(self.db_path)
        ev3 = next(e for e in plan["events"] if e["event_id"] == 3)
        t = ev3["tickers"][0]
        self.assertEqual(t["new_fields"], {})
        self.assertEqual(t["blocker"], "no_cached_bars")

    def test_malformed_and_vetoed_entries_gain_no_tags(self):
        plan = rde.build_recovery_plan(self.db_path)
        ev8 = next(e for e in plan["events"] if e["event_id"] == 8)
        by_sym = {t.get("symbol"): t for t in ev8["tickers"]}
        self.assertEqual(by_sym[None]["blocker"], "malformed_entry")
        self.assertEqual(by_sym["III"]["blocker"], "no_usable_role")
        self.assertNotIn("direction_tag", by_sym["III"]["new_fields"])
        # verification veto: returns may fill, the tag may not
        self.assertNotIn("direction_tag", by_sym["JJJ"]["new_fields"])
        self.assertEqual(by_sym["JJJ"]["tag_blocker"],
                         "verification_veto")

    def test_no_event_id_allowlist_in_module(self):
        src = re.sub(r'("""[\s\S]*?"""|#[^\n]*)', "",
                     Path(rde.__file__).read_text(encoding="utf-8"))
        for banned in (r"\b211\b", r"\b212\b", r"\b214\b", r"\b215\b",
                       r"\b218\b", r"\b219\b", r"\b232\b", r"\b250\b"):
            self.assertIsNone(re.search(banned, src), banned)

    def test_no_provider_or_network_reachable(self):
        import socket

        import market_data

        def boom(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("provider/network path reached")

        with patch.object(socket, "socket", boom), \
                patch.object(market_data, "get_provider",
                             side_effect=None) as gp:
            # get_provider may be consulted; it must be the blocking
            # proxy inside the guard - assert no fetch leaks through by
            # replacing the provider itself with a bomb.
            gp.side_effect = boom
            with market_data.no_provider_fetch():
                plan = rde.build_recovery_plan(self.db_path)
        self.assertEqual(plan["funnel"]["in_scope"], 4)


class ApplyTests(FixtureCase):
    def test_dry_run_performs_zero_writes(self):
        before = self._hash()
        result = rde.run_recovery(self.db_path, apply=False)
        self.assertEqual(self._hash(), before)
        self.assertFalse(result["applied"])
        self.assertEqual(result["counts"]["changed"], 0)
        self.assertGreaterEqual(result["counts"]["eligible"], 2)

    def test_apply_recovers_directional_coverage_honestly(self):
        before = rde.build_recovery_plan(self.db_path)["funnel"]
        result = rde.run_recovery(self.db_path, apply=True)
        after = rde.build_recovery_plan(self.db_path)["funnel"]
        # accepted denominator unchanged; directional grows by exactly
        # the one honestly recoverable event (id 1).
        self.assertEqual(after["accepted"], before["accepted"])
        self.assertEqual(after["with_tickers"], before["with_tickers"])
        self.assertEqual(after["directional"], before["directional"] + 1)
        self.assertEqual(result["counts"]["changed"], 2)  # events 1 and 2
        # event 1 now carries canonical tags
        tags = [t.get("direction_tag") for t in self._tickers(1)]
        self.assertEqual(tags, ["supports ↑", "supports ↓"])
        # flat event 2 gained returns but no tag - still non-directional
        t2 = self._tickers(2)[0]
        self.assertIsNotNone(t2["return_5d"])
        self.assertIsNone(t2["direction_tag"])
        # event 3 (no bars) untouched
        self.assertIsNone(self._tickers(3)[0]["return_5d"])

    def test_apply_updates_only_eligible_fields(self):
        original_1 = self._tickers(1)
        rde.run_recovery(self.db_path, apply=True)
        updated_1 = self._tickers(1)
        for orig, upd in zip(original_1, updated_1):
            for key, value in orig.items():
                if key in ("direction_tag", "return_5d", "return_20d"):
                    continue
                self.assertEqual(upd[key], value, key)

    def test_modern_payloads_remain_byte_equivalent(self):
        raw_before = self._tickers(7)
        rde.run_recovery(self.db_path, apply=True)
        self.assertEqual(self._tickers(7), raw_before)
        # out-of-scope rows untouched wholesale
        for ev_id in (4, 5, 6):
            self.assertEqual(self._tickers(ev_id),
                             build_fixture_expected(ev_id))

    def test_second_apply_changes_zero_rows(self):
        rde.run_recovery(self.db_path, apply=True)
        second = rde.run_recovery(self.db_path, apply=True)
        self.assertEqual(second["counts"]["changed"], 0)

    def test_apply_is_transactional_per_event(self):
        with patch.object(_db, "_compute_falsifier_block",
                          side_effect=RuntimeError("boom")):
            result = rde.run_recovery(self.db_path, apply=True)
        self.assertGreaterEqual(result["counts"]["failed"], 1)
        self.assertEqual(result["counts"]["changed"], 0)
        # the failed write rolled back - nothing gained a tag
        tags = [t.get("direction_tag") for t in self._tickers(1)]
        self.assertEqual(tags, [None, None])

    def test_deterministic_plan(self):
        a = rde.build_recovery_plan(self.db_path)
        b = rde.build_recovery_plan(self.db_path)
        self.assertEqual(a, copy.deepcopy(b))

    def test_majority_rule_module_untouched(self):
        import validation_status
        src = Path(validation_status.__file__).read_text(encoding="utf-8")
        self.assertIn('if signals["supporting"] > signals["contradicting"]:',
                      src)


def build_fixture_expected(event_id: int):
    """Original fixture tickers for out-of-scope rows (4, 5, 6)."""
    if event_id == 4:
        return [_ticker("EEE", "beneficiary")]
    if event_id == 5:
        return [_ticker("FFF", "beneficiary")]
    if event_id == 6:
        return []
    raise AssertionError(event_id)


if __name__ == "__main__":
    unittest.main()
