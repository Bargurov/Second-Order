"""Z1B — copy-only candidate-pack ingestion + free backfill harness (safety tests).

Pins the gated contract for ``scripts/z1b_candidate_pack_copy_ingest.py``:

* It REFUSES to target the live archive (``db.LIVE_DB_FILE``) and REQUIRES an
  explicit copy path — neither ingestion nor backfill can touch live.
* Ingestion reuses the Z1A validators (``validate_no_synthetic_data`` +
  ``validate_event_content_framing``) and refuses a pack that fails either —
  it does not weaken or re-implement them.
* Each candidate becomes one ``events`` row (stage ``z1a_candidate_pack``,
  market_tickers = minimal ``[{symbol, role}]`` with roles VERBATIM — no
  directional reframing) plus one ``event_provenance`` row that preserves the
  source_url and marks ``intake_path = z1a_candidate_pack``.
* Idempotent by ``event_provenance.source_url`` — a re-run inserts nothing.
* The backfill is FREE-ONLY by construction: it pins the free yfinance provider,
  refuses a non-free provider, and the module never references ``confirm_paid``
  or the paid Polygon path.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid

import pandas as pd
import yaml

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import db  # noqa: E402
from scripts import z1b_candidate_pack_copy_ingest as Z  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------

class _FakeProvider:
    """In-process FREE provider stand-in (no network).  ``provider_name`` is
    ``yfinance`` so it passes the free-provider guard; closes dodge the
    price_cache suspect-fixture fingerprint (close<10 & vol==1e6 & integer)."""
    provider_name = "yfinance"

    def __init__(self):
        self.calls = []

    def fetch_daily(self, ticker, *, period=None, start=None, end=None, auto_adjust=True):
        self.calls.append((ticker, start, end, auto_adjust))
        idx = pd.bdate_range(start=start, end=end)
        if len(idx) == 0:
            return None
        close = [100.0 + i * 0.37 for i in range(len(idx))]
        vol = [2_000_000.0] * len(idx)
        return pd.DataFrame({"Close": close, "Volume": vol}, index=idx)


class _PaidProvider(_FakeProvider):
    provider_name = "polygon"


def _cand(**over) -> dict:
    """A single fully Z1A-valid candidate dict (passes both Z1A validators)."""
    base = {
        "id": f"doj-v-example-2023-01-02-{uuid.uuid4().hex[:6]}",
        "event_date": "2023-01-02",
        "title": "Justice Department sues Example Corp for monopolizing a market",
        "source_url": f"https://www.justice.gov/opa/pr/example-{uuid.uuid4().hex[:8]}",
        "source_type": "official",
        "category": "antitrust",
        "mechanism_family": "regulation",
        "mechanism_summary": "A structural-remedy antitrust complaint reprices "
                             "regulatory and breakup risk attached to the named firm.",
        "affected_assets": [
            {"ticker": "GOOGL", "role": "exposed",
             "rationale": "the named defendant carries remedy risk on the name"},
            {"ticker": "MA", "role": "beneficiary",
             "rationale": "a competing name whose relative positioning could improve"},
        ],
        "benchmark": "SPY",
        "placebo_feasibility_guess": "uncertain",
        "limitation_or_falsifier": "n=1 descriptive read vs SPY; not an established mechanism.",
        "review_status": "candidate_only_not_ingested",
    }
    base.update(over)
    return base


class _Base(unittest.TestCase):
    def setUp(self):
        self._orig_db = db.DB_FILE
        self._copy = os.path.join(tempfile.gettempdir(), f"z1b_copy_{uuid.uuid4().hex}.db")
        db.DB_FILE = self._copy
        db.init_db()
        db.DB_FILE = self._orig_db  # the helper takes an explicit copy_path, not db.DB_FILE
        self._paths = [self._copy]

    def tearDown(self):
        db.DB_FILE = self._orig_db
        for p in self._paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def _write_pack(self, cands) -> str:
        path = os.path.join(tempfile.gettempdir(), f"z1b_pack_{uuid.uuid4().hex}.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump({"candidates": cands}, fh, sort_keys=False, allow_unicode=True)
        self._paths.append(path)
        return path

    def _count(self, table) -> int:
        con = sqlite3.connect(f"file:{self._copy}?mode=ro", uri=True)
        try:
            return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            con.close()

    def _rows(self, sql) -> list:
        con = sqlite3.connect(f"file:{self._copy}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(sql)]
        finally:
            con.close()


# ---------------------------------------------------------------------------
# Live-refusal + explicit-copy-path gates
# ---------------------------------------------------------------------------

class TestGates(_Base):
    def test_ingest_refuses_live_target(self):
        path = self._write_pack([_cand()])
        with self.assertRaises(ValueError):
            Z.apply_copy_ingest(candidates_path=path, copy_path=db.LIVE_DB_FILE, confirm=True)

    def test_ingest_requires_explicit_copy_path(self):
        path = self._write_pack([_cand()])
        for bad in (None, ""):
            with self.assertRaises(ValueError):
                Z.apply_copy_ingest(candidates_path=path, copy_path=bad, confirm=True)

    def test_backfill_refuses_live_target(self):
        path = self._write_pack([_cand()])
        with self.assertRaises(ValueError):
            Z.backfill_candidate_prices(
                copy_path=db.LIVE_DB_FILE, candidates_path=path, provider=_FakeProvider())

    def test_backfill_refuses_non_free_provider(self):
        path = self._write_pack([_cand()])
        with self.assertRaises(ValueError):
            Z.backfill_candidate_prices(
                copy_path=self._copy, candidates_path=path, provider=_PaidProvider())


# ---------------------------------------------------------------------------
# Ingestion contract
# ---------------------------------------------------------------------------

class TestIngest(_Base):
    def test_dry_run_writes_nothing(self):
        path = self._write_pack([_cand()])
        plan = Z.plan_copy_ingest(candidates_path=path, copy_path=self._copy)
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["to_insert_count"], 1)
        self.assertEqual(self._count("events"), 0)
        self.assertEqual(self._count("event_provenance"), 0)

    def test_ingest_inserts_event_and_provenance_and_preserves_source_url(self):
        c = _cand()
        path = self._write_pack([c])
        rep = Z.apply_copy_ingest(candidates_path=path, copy_path=self._copy, confirm=True)
        self.assertTrue(rep["write_attempted"])
        self.assertEqual(rep["inserted_count"], 1)
        self.assertEqual(self._count("events"), 1)
        self.assertEqual(self._count("event_provenance"), 1)
        pv = self._rows("SELECT * FROM event_provenance")[0]
        self.assertEqual(pv["source_url"], c["source_url"])
        self.assertEqual(pv["intake_path"], "z1a_candidate_pack")
        self.assertEqual(pv["source_type"], "official")

    def test_marks_candidate_origin_stage_and_notes(self):
        path = self._write_pack([_cand()])
        Z.apply_copy_ingest(candidates_path=path, copy_path=self._copy, confirm=True)
        ev = self._rows("SELECT * FROM events")[0]
        self.assertEqual(ev["stage"], "z1a_candidate_pack")
        self.assertEqual(ev["persistence"], "unscored")
        self.assertIn("candidate_only_not_ingested", (ev["notes"] or ""))

    def test_market_tickers_minimal_roles_verbatim(self):
        path = self._write_pack([_cand()])
        Z.apply_copy_ingest(candidates_path=path, copy_path=self._copy, confirm=True)
        ev = self._rows("SELECT * FROM events")[0]
        mt = json.loads(ev["market_tickers"])
        self.assertEqual(mt, [
            {"symbol": "GOOGL", "role": "exposed"},
            {"symbol": "MA", "role": "beneficiary"},
        ])
        # no precomputed-verdict keys smuggled in
        for entry in mt:
            self.assertNotIn("direction_tag", entry)
            self.assertNotIn("return_1d", entry)
            self.assertNotIn("label", entry)

    def test_idempotent_by_source_url(self):
        path = self._write_pack([_cand()])
        r1 = Z.apply_copy_ingest(candidates_path=path, copy_path=self._copy, confirm=True)
        self.assertEqual(r1["inserted_count"], 1)
        r2 = Z.apply_copy_ingest(candidates_path=path, copy_path=self._copy, confirm=True)
        self.assertEqual(r2["inserted_count"], 0)
        self.assertEqual(self._count("events"), 1)
        self.assertEqual(self._count("event_provenance"), 1)

    def test_rejects_synthetic_pack_via_z1a_validator(self):
        bad = _cand(title="demo placeholder event for showcase")
        path = self._write_pack([bad])
        rep = Z.apply_copy_ingest(candidates_path=path, copy_path=self._copy, confirm=True)
        self.assertFalse(rep["write_attempted"])
        self.assertTrue(rep["rejected"])
        self.assertEqual(self._count("events"), 0)

    def test_rejects_banned_framing_pack_via_z1a_validator(self):
        bad = _cand(mechanism_summary="a strong buy signal for the sector")
        path = self._write_pack([bad])
        rep = Z.apply_copy_ingest(candidates_path=path, copy_path=self._copy, confirm=True)
        self.assertFalse(rep["write_attempted"])
        self.assertTrue(rep["rejected"])
        self.assertEqual(self._count("events"), 0)


# ---------------------------------------------------------------------------
# Backfill contract (free-only, copy-only)
# ---------------------------------------------------------------------------

class TestBackfill(_Base):
    def test_backfill_writes_rows_into_copy_with_fake_free_provider(self):
        path = self._write_pack([_cand()])
        fake = _FakeProvider()
        before = self._count("price_cache")
        summary = Z.backfill_candidate_prices(
            copy_path=self._copy, candidates_path=path, provider=fake)
        self.assertGreater(summary["rows_written"], 0)
        self.assertGreater(len(fake.calls), 0)
        self.assertEqual(self._count("price_cache"), before + summary["rows_written"])
        # benchmark SPY is fetched alongside the candidate tickers
        self.assertIn("SPY", {c[0] for c in fake.calls})

    def test_backfill_restores_db_file_and_provider(self):
        import market_data
        path = self._write_pack([_cand()])
        before_db = db.DB_FILE
        before_prov = market_data.get_provider()
        Z.backfill_candidate_prices(
            copy_path=self._copy, candidates_path=path, provider=_FakeProvider())
        self.assertEqual(db.DB_FILE, before_db)
        self.assertIs(market_data.get_provider(), before_prov)

    def test_backfill_request_cap_honoured(self):
        cands = [_cand(), _cand(), _cand()]
        path = self._write_pack(cands)
        fake = _FakeProvider()
        summary = Z.backfill_candidate_prices(
            copy_path=self._copy, candidates_path=path, provider=fake, max_requests=2)
        self.assertLessEqual(summary["requests"], 2)
        self.assertLessEqual(len(fake.calls), 2)


# ---------------------------------------------------------------------------
# Static safety: no paid path, no confirm_paid
# ---------------------------------------------------------------------------

class TestNoPaidPath(unittest.TestCase):
    def test_module_has_no_confirm_paid_or_polygon_path(self):
        with open(os.path.join(_REPO, "scripts", "z1b_candidate_pack_copy_ingest.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        for forbidden in ("confirm_paid", "PolygonProvider", "Polygon", "polygon"):
            self.assertNotIn(forbidden, src,
                             f"copy-ingest helper must not reference {forbidden!r}")


if __name__ == "__main__":
    unittest.main()
