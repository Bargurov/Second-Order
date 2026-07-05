"""Tests for the G5 controlled promotion of Mission G historical evidence.

Contract under test (G0 protocol s2/s16; task G5):

* one storage substrate (events.db), separate denominator ledgers: promoted
  rows live in a dedicated `g_historical_evidence` table whose every row
  carries its ledger; no existing table or row is ever updated;
* ledger precedence: a candidate colliding with a live events row (same
  event date + family identity) halts promotion loudly - it may never be
  double-stored or moved to a more convenient ledger;
* frame rows cannot enter the designed ledger and vice versa; the frozen
  G3A transmission map and G4 state/tag freeze are enforced at insert;
* promotion is one transaction: idempotent on rerun, full rollback on any
  failure, never a per-row manual patch;
* no outcome-shaped and no mechanism-taxonomy field can be promoted; the
  table schema itself carries no such column.

Fixture databases are temporary copies shaped like the live schema; live
tests skip when the G artifacts or state cache are absent.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import g5_promotion as g5  # noqa: E402
from scripts import g_state_acquisition as gsa  # noqa: E402
from scripts.g3_mechanical_grinder import (  # noqa: E402
    MAPPING_VERSION, TRANSMISSION_MAP)

G1A = ROOT / "stats" / "G1A_FOMC_FRAME_INVENTORY.md"
G1B = ROOT / "stats" / "G1B_OPEC_DESIGNED_RESERVOIR.md"
CACHE = ROOT / "g_state_cache"
LIVE_READY = (G1A.exists() and G1B.exists()
              and (CACHE / "vix.json").exists()
              and (CACHE / "hy_oas.json").exists())


def _fixture_db(dirname: str) -> Path:
    """A live-shaped fixture DB: events + event_hygiene with accepted and
    synthetic rows (accepted denominator = 2)."""
    path = Path(dirname) / "fixture_events.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY, headline TEXT, stage TEXT,
            event_date TEXT);
        CREATE TABLE event_hygiene (
            event_id INTEGER, override_class TEXT, override_reason TEXT,
            created_at TEXT);
        INSERT INTO events VALUES
            (1, 'Accepted 2026 event', 'realized', '2026-04-06'),
            (2, 'Another accepted event', 'anticipation', '2026-04-07'),
            (3, 'Synthetic seed event', 'realized', '2020-05-04'),
            (4, 'Staged pack row', 'z1a_candidate_pack', '2026-04-08');
        INSERT INTO event_hygiene VALUES
            (3, 'synthetic_seed', 'seed', '2026-01-01');
    """)
    con.commit()
    con.close()
    return path


def _valid_rows() -> list[dict]:
    """Four valid promotion rows (2 frame FOMC, 2 designed OPEC)."""
    rows = []
    for cid, fam, ledger, date, cutoff, curve, tag_curve in (
            ("fomc-policy-decision-2024-05-01", "fomc",
             "frame_complete_historical", "2024-05-01", "2024-04-30",
             -0.35, "inverted"),
            ("fomc-policy-decision-2024-06-12", "fomc",
             "frame_complete_historical", "2024-06-12", "2024-06-11",
             -0.40, "inverted"),
            ("opec-2024-06-02-fixture", "opec", "designed_contrast",
             "2024-06-02", "2024-05-31", -0.38, "inverted"),
            ("opec-2024-09-05-fixture", "opec", "designed_contrast",
             "2024-09-05", "2024-09-04", 0.05, "non_inverted")):
        lens = TRANSMISSION_MAP[fam]
        rows.append({
            "candidate_id": cid,
            "denominator_ledger": ledger,
            "sampling_family": fam,
            "source_provenance": json.dumps(
                {"artifact": "fixture", "selection": "frame_member"
                 if fam == "fomc" else "designed_recruitment"}),
            "event_date": date,
            "cutoff": cutoff,
            "mapping_version": MAPPING_VERSION,
            "primary_asset": lens.primary,
            "market_benchmark": lens.market,
            "sector_benchmark": lens.sector,
            "freeze_version": "g4-structural-freeze-v1",
            "state_fed_policy_path": -0.25,
            "state_vix_level_percentile": 0.42,
            "state_spy_trend_ma200": 0.03,
            "state_curve_2s10s": curve,
            "state_credit_hy_oas": 3.25,
            "credit_availability": "available",
            "tag_fed_policy_path": "easing",
            "tag_spy_trend_ma200": "above_ma",
            "tag_curve_2s10s": tag_curve,
        })
    return rows


def _table_count(path: Path, table: str) -> int:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
    except sqlite3.OperationalError:
        return -1
    finally:
        con.close()


class PromotionMechanicsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = _fixture_db(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_promote_inserts_and_partitions_ledgers(self):
        result = g5.promote(self.db, _valid_rows())
        self.assertEqual(result["inserted"], 4)
        self.assertEqual(result["already_present"], 0)
        self.assertEqual(result["by_ledger"],
                         {"designed_contrast": 2,
                          "frame_complete_historical": 2})

    def test_idempotent_rerun_inserts_zero(self):
        g5.promote(self.db, _valid_rows())
        again = g5.promote(self.db, _valid_rows())
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(again["already_present"], 4)
        self.assertEqual(_table_count(self.db, g5.GTABLE), 4)

    def test_changed_row_on_rerun_raises_and_never_updates(self):
        g5.promote(self.db, _valid_rows())
        tampered = _valid_rows()
        tampered[0]["state_vix_level_percentile"] = 0.99
        with self.assertRaises(ValueError):
            g5.promote(self.db, tampered)
        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        v = con.execute(
            f"SELECT state_vix_level_percentile FROM {g5.GTABLE} "
            "WHERE candidate_id = ?",
            (tampered[0]["candidate_id"],)).fetchone()[0]
        con.close()
        self.assertEqual(v, 0.42)

    def test_mid_batch_failure_rolls_back_everything(self):
        rows = _valid_rows()
        rows[3] = dict(rows[3], event_date=rows[0]["event_date"])  # dup date
        with self.assertRaises(Exception):
            g5.promote(self.db, rows)
        self.assertIn(_table_count(self.db, g5.GTABLE), (0, -1))

    def test_events_and_hygiene_tables_are_byte_identical_after(self):
        before = g5.table_dump_hashes(self.db)
        g5.promote(self.db, _valid_rows())
        after = g5.table_dump_hashes(self.db)
        self.assertEqual(before, after)  # GTABLE excluded by default

    def test_accepted_denominator_is_unchanged_by_promotion(self):
        pre = g5.accepted_track_record_count(self.db)
        g5.promote(self.db, _valid_rows())
        self.assertEqual(g5.accepted_track_record_count(self.db), pre)
        self.assertEqual(pre, 2)  # fixture: 3 accepted-stage - 1 synthetic


class PromotionValidationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = _fixture_db(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _expect_reject(self, mutate, msg_part):
        rows = _valid_rows()
        mutate(rows)
        with self.assertRaises(ValueError) as ctx:
            g5.promote(self.db, rows)
        self.assertIn(msg_part, str(ctx.exception))
        self.assertIn(_table_count(self.db, g5.GTABLE), (0, -1))

    def test_frame_row_cannot_enter_designed_ledger(self):
        self._expect_reject(
            lambda rows: rows[0].update(
                denominator_ledger="designed_contrast"),
            "ledger")

    def test_designed_row_cannot_enter_frame_ledger(self):
        self._expect_reject(
            lambda rows: rows[2].update(
                denominator_ledger="frame_complete_historical"),
            "ledger")

    def test_mapping_must_match_frozen_transmission_map(self):
        self._expect_reject(
            lambda rows: rows[0].update(primary_asset="XOP"),
            "transmission")

    def test_mapping_version_must_match_g3a(self):
        self._expect_reject(
            lambda rows: rows[0].update(mapping_version="v0-wrong"),
            "mapping_version")

    def test_null_primary_state_rejected(self):
        self._expect_reject(
            lambda rows: rows[0].update(state_spy_trend_ma200=None),
            "primary state")

    def test_credit_availability_must_match_value_presence(self):
        self._expect_reject(
            lambda rows: rows[0].update(state_credit_hy_oas=None,
                                        credit_availability="available"),
            "credit_availability")

    def test_tag_inconsistent_with_state_sign_rejected(self):
        self._expect_reject(
            lambda rows: rows[0].update(state_curve_2s10s=0.25,
                                        tag_curve_2s10s="inverted"),
            "tag")

    def test_outcome_shaped_key_rejected(self):
        self._expect_reject(
            lambda rows: rows[0].update(abnormal_return_1d=0.02),
            "outcome")

    def test_mechanism_taxonomy_key_rejected(self):
        self._expect_reject(
            lambda rows: rows[0].update(mechanism_family="supply_shock"),
            "mechanism")

    def test_collision_with_live_family_row_halts(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO events VALUES "
                    "(9, 'FOMC raises target range', 'realized', "
                    "'2024-05-01')")
        con.commit()
        con.close()
        with self.assertRaises(ValueError) as ctx:
            g5.promote(self.db, _valid_rows())
        self.assertIn("collision", str(ctx.exception))
        self.assertIn(_table_count(self.db, g5.GTABLE), (0, -1))

    def test_schema_carries_only_whitelisted_columns(self):
        g5.promote(self.db, _valid_rows())
        con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        cols = [r[1] for r in con.execute(
            f"PRAGMA table_info({g5.GTABLE})")]
        con.close()
        self.assertEqual(tuple(cols), g5.G_COLUMNS)
        joined = " ".join(cols).lower()
        for banned in ("abnormal", "sar", "car", "return", "outcome",
                       "mechanism", "readout", "reaction"):
            self.assertNotIn(banned, joined, banned)


@unittest.skipUnless(LIVE_READY, "live ledgers and state cache required")
class LivePromotionInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = g5.build_promotion_rows()

    def test_input_reconciles_65_32_97_unique(self):
        by_ledger: dict[str, int] = {}
        for r in self.rows:
            by_ledger[r["denominator_ledger"]] = by_ledger.get(
                r["denominator_ledger"], 0) + 1
        self.assertEqual(len(self.rows), 97)
        self.assertEqual(by_ledger["frame_complete_historical"], 65)
        self.assertEqual(by_ledger["designed_contrast"], 32)
        self.assertEqual(len({r["candidate_id"] for r in self.rows}), 97)
        self.assertEqual(len({r["event_date"] for r in self.rows}), 97)

    def test_credit_availability_is_exactly_36_61(self):
        avail = [r for r in self.rows
                 if r["credit_availability"] == "available"]
        missing = [r for r in self.rows
                   if r["credit_availability"] == "source_missing"]
        self.assertEqual(len(avail), 36)
        self.assertEqual(len(missing), 61)
        self.assertTrue(all(r["state_credit_hy_oas"] is not None
                            for r in avail))
        self.assertTrue(all(r["state_credit_hy_oas"] is None
                            for r in missing))

    def test_four_primary_dimensions_present_for_all_97(self):
        for col in ("state_fed_policy_path", "state_vix_level_percentile",
                    "state_spy_trend_ma200", "state_curve_2s10s"):
            self.assertTrue(all(r[col] is not None for r in self.rows), col)

    def test_tag_occupancy_matches_g4_freeze(self):
        from scripts import g4_structural_freeze as g4
        g4_rows, _ = g4._load_live()
        statuses = g4.freeze_dimension_statuses(g4_rows)
        tags = g4.freeze_tags(g4_rows, statuses)
        for dim, col in (("fed_policy_path", "tag_fed_policy_path"),
                         ("spy_trend_ma200", "tag_spy_trend_ma200"),
                         ("curve_2s10s", "tag_curve_2s10s")):
            counts: dict[str, int] = {}
            for r in self.rows:
                counts[r[col]] = counts.get(r[col], 0) + 1
            expected = {c: cell["count"] for c, cell in
                        tags[dim]["occupancy"]["by_category"].items()
                        if cell["count"]}
            self.assertEqual(counts, expected, dim)

    def test_transmission_mapping_matches_g3a_exactly(self):
        for r in self.rows:
            lens = TRANSMISSION_MAP[r["sampling_family"]]
            self.assertEqual(r["primary_asset"], lens.primary)
            self.assertEqual(r["market_benchmark"], lens.market)
            self.assertEqual(r["sector_benchmark"], lens.sector)
            self.assertEqual(r["mapping_version"], MAPPING_VERSION)

    def test_live_rows_pass_the_promotion_validators(self):
        g5.validate_rows(self.rows)  # must not raise


if __name__ == "__main__":
    unittest.main()
