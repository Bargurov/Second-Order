"""A1-3R — saved-analysis readout parity and three-way atomicity.

The product contract: for one successful analysis the A1-3 readout fields are
identical across the fresh response, the numeric saved-event response and the
headline-cache response.  A reopened analysis shows what the run reported —
not a degraded shadow of it.

Atomicity extends A1-2 to three artifacts: events row + provenance + result
snapshot commit together, and candidate linkage happens only after.

Every provider seam is patched; no test calls a real provider.
"""

import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

import analysis_result_snapshot as ars
import api as _api
import db as _db
from event_inbox import candidate_event_id
from news_sources import _dedup_key

_TITLE = "Refinery outage cuts regional diesel supply"
_KEY = _dedup_key(_TITLE)
_PARENT = 6301
_CANDIDATE = candidate_event_id(_PARENT, _KEY)

FULL = {
    "what_changed": "Outage removed 400kb/d of refining capacity.",
    "mechanism_summary": "The regional diesel balance tightens through Q3.",
    "beneficiaries": ["independent refiners"], "losers": ["road hauliers"],
    "beneficiary_tickers": [], "loser_tickers": [], "assets_to_watch": [],
    "confidence": "medium",
    "transmission_chain": ["outage", "cracks widen", "costs rise"],
    "transmission_path": [
        {"step": 1, "node": "Refinery capacity", "so_what": "Supply removed"},
        {"step": 2, "node": "Crack spreads", "so_what": "Margins widen"},
    ],
    "hidden_mechanism": {
        "transmission_type": "physical_supply",
        "bottleneck_type": "processing_capacity",
        "substitution_escape_path": "Seaborne imports within 3 weeks",
        "critical_breakpoints": ["Restart before day 10"],
        "optional_confirming_evidence": ["Freight rate divergence"],
        "source_quality": {"tier": "single_outlet",
                           "evidence_limitations": ["One outlet only"]},
        "regime_caveats": {"evidence_to_revisit": ["Demand prints"]},
    },
    "primary_assets": ["VLO", "PSX"], "secondary_assets": ["ODFL"],
    "hedge_or_signal_assets": ["XLE"],
    "expected_second_order_channels": ["SUPPLY_CHAIN", "INFLATION"],
    "counterforces": [{"force": "SPR release", "effect": "Could offset",
                       "likelihood": "medium"}],
    "substitution_barriers": [{"barrier": "Import berths", "severity": "high"}],
    "competing_thesis": {"thesis": "Demand weakness dominates",
                         "evidence": "Freight volumes falling"},
    "adversarial_challenge": "The outage may be repaired faster.",
    "key_falsifiers": ["Cracks flat after 5 sessions"],
    "minimum_proof_set": ["Diesel crack > +8%"],
    "horizon_checkpoints": {"1d": "Crack reaction", "5d": "Inventory print"},
    "monitor_plan": ["Weekly EIA inventory print"],
    "quality_tier": "actionable",
    "quality_warnings": ["Single-outlet estimate"],
    "validation_warnings": ["Ticker set unconfirmed"],
    "degraded": False,
    "regime_conditioned_caveat": "Holds while imports stay constrained.",
    "if_persists": {}, "currency_channel": {},
}


class _RouteBase(unittest.TestCase):

    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_arp_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()
        self._seed_cluster()
        self.client = TestClient(_api.app)
        self.provider_calls: list = []

    def tearDown(self):
        _db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _seed_cluster(self):
        records = [{"source": "Reuters World", "title": _TITLE,
                    "published_at": "2026-07-20T09:00:00", "url": "https://x.test/r"},
                   {"source": "BBC Business", "title": _TITLE,
                    "published_at": "2026-07-20T11:30:00", "url": "https://x.test/b"}]
        conn = sqlite3.connect(self._tmp)
        conn.execute("INSERT OR REPLACE INTO news_clusters (id, headline,"
                     " payload_json, records_json, latest_published_at, updated_at)"
                     " VALUES (?,?,?,?,?,?)",
                     (_PARENT, _TITLE, json.dumps({}), json.dumps(records),
                      "2026-07-20T11:30:00", "2026-07-20T11:30:00"))
        for src in ("Reuters World", "BBC Business"):
            conn.execute("INSERT OR REPLACE INTO headline_registry (source,"
                         " title_key, cluster_id, event_id, state, first_seen_at,"
                         " last_seen_at) VALUES (?,?,?,NULL,'seen','t','t')",
                         (src, _KEY, _PARENT))
        conn.commit()
        conn.close()

    def _provider(self, *a, **k):
        self.provider_calls.append(1)
        return dict(FULL)

    def _body(self, **over):
        b = {"headline": _TITLE, "event_context": "Sources (2)",
             "candidate_id": _CANDIDATE, "parent_cluster_id": _PARENT,
             "title_key": _KEY, "confirm_paid": True}
        b.update(over)
        return b

    def _post(self, path, body, extra=None):
        stack = [patch("routes.analyze._call_analyze_event", self._provider),
                 patch.object(_api, "market_check",
                              return_value={"note": "", "tickers": []})]
        if extra:
            stack.extend(extra)
        for p in stack:
            p.start()
        try:
            return self.client.post(path, json=body)
        finally:
            for p in reversed(stack):
                p.stop()

    def _counts(self):
        conn = sqlite3.connect(self._tmp)
        n = tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("events", "analysis_provenance",
                            "analysis_result_snapshot"))
        conn.close()
        return n

    def _linked(self):
        conn = sqlite3.connect(self._tmp)
        rows = {r[0] for r in conn.execute(
            "SELECT event_id FROM headline_registry WHERE title_key = ?",
            (_KEY,)).fetchall()}
        conn.close()
        return rows

    def _readout(self, analysis: dict) -> dict:
        """The A1-3 field subset — the thing that must be equal everywhere."""
        return {f: analysis.get(f) for f in ars.RESULT_SNAPSHOT_FIELDS
                if f in analysis}


# ---------------------------------------------------------------------------
# Parity — the product contract
# ---------------------------------------------------------------------------

class TestSavedReadoutParity(_RouteBase):

    def test_fresh_numeric_and_headline_readouts_are_equal(self):
        fresh = self._post("/analyze", self._body()).json()
        eid = fresh["analysis_event_id"]
        by_id = self._post("/analyze", {"headline": _TITLE, "event_id": eid}).json()
        by_head = self._post("/analyze", {"headline": _TITLE}).json()

        want = self._readout(fresh["analysis"])
        self.assertGreater(len(want), 15, "the fixture must exercise the readout")
        for name, got in (("numeric", by_id), ("headline", by_head)):
            with self.subTest(path=name):
                self.assertEqual(self._readout(got["analysis"]), want)

    def test_every_required_field_survives_a_reopen(self):
        fresh = self._post("/analyze", self._body()).json()
        eid = fresh["analysis_event_id"]
        reopened = self._post("/analyze",
                              {"headline": _TITLE, "event_id": eid}).json()["analysis"]
        for f in ars.RESULT_SNAPSHOT_FIELDS:
            if f not in FULL:
                continue
            with self.subTest(field=f):
                self.assertEqual(reopened.get(f), FULL[f])

    def test_nested_hidden_mechanism_survives_a_reopen(self):
        fresh = self._post("/analyze", self._body()).json()
        reopened = self._post("/analyze", {
            "headline": _TITLE,
            "event_id": fresh["analysis_event_id"]}).json()["analysis"]
        self.assertEqual(reopened.get("hidden_mechanism"), FULL["hidden_mechanism"])

    def test_streaming_persists_the_same_readout(self):
        resp = self._post("/analyze/stream", self._body())
        frames = [json.loads(l[6:]) for l in resp.text.splitlines()
                  if l.startswith("data: ")]
        eid = frames[-1]["analysis_event_id"]
        reopened = self._post("/analyze",
                              {"headline": _TITLE, "event_id": eid}).json()["analysis"]
        self.assertEqual(self._readout(reopened), self._readout(frames[-1]["analysis"]))

    def test_reopening_calls_no_provider(self):
        eid = self._post("/analyze", self._body()).json()["analysis_event_id"]
        self.provider_calls.clear()
        self._post("/analyze", {"headline": _TITLE, "event_id": eid})
        self._post("/analyze", {"headline": _TITLE})
        self.assertEqual(self.provider_calls, [])

    def test_retrieval_does_not_recompute_saved_output(self):
        """A stored value wins even when current state would derive another."""
        eid = self._post("/analyze", self._body()).json()["analysis_event_id"]
        conn = sqlite3.connect(self._tmp)
        conn.execute("UPDATE events SET key_falsifiers = '[\"COLUMN VALUE\"]' "
                     "WHERE id = ?", (eid,))
        conn.commit()
        conn.close()
        reopened = self._post("/analyze",
                              {"headline": _TITLE, "event_id": eid}).json()["analysis"]
        self.assertEqual(reopened["key_falsifiers"], FULL["key_falsifiers"])


# ---------------------------------------------------------------------------
# Three-way atomicity
# ---------------------------------------------------------------------------

class TestThreeWayAtomicity(_RouteBase):

    def test_success_creates_event_provenance_snapshot_then_link(self):
        resp = self._post("/analyze", self._body()).json()
        eid = resp["analysis_event_id"]
        self.assertEqual(self._counts(), (1, 1, 1))
        self.assertEqual(self._linked(), {eid})

    def test_snapshot_failure_rolls_back_event_and_provenance(self):
        resp = self._post("/analyze", self._body(), extra=[
            patch.object(_db, "_insert_analysis_result_snapshot",
                         side_effect=RuntimeError("snapshot write failed"))])
        body = resp.json()
        self.assertTrue(body.get("persistence_failed"))
        self.assertEqual(self._counts(), (0, 0, 0))
        self.assertEqual(self._linked(), {None})

    def test_provenance_failure_creates_no_snapshot(self):
        self._post("/analyze", self._body(), extra=[
            patch.object(_db, "_insert_analysis_provenance",
                         side_effect=RuntimeError("provenance write failed"))])
        self.assertEqual(self._counts(), (0, 0, 0))
        self.assertEqual(self._linked(), {None})

    def test_event_failure_creates_neither_downstream_row(self):
        self._post("/analyze", self._body(), extra=[
            patch.object(_db, "_insert_event_row",
                         side_effect=RuntimeError("disk full"))])
        self.assertEqual(self._counts(), (0, 0, 0))
        self.assertEqual(self._linked(), {None})

    def test_linkage_is_never_attempted_after_a_failed_transaction(self):
        seen = []
        real = _db.link_candidate_analysis
        self._post("/analyze", self._body(), extra=[
            patch.object(_db, "_insert_analysis_result_snapshot",
                         side_effect=RuntimeError("snapshot write failed")),
            patch.object(_api, "link_candidate_analysis",
                         side_effect=lambda *a, **k: (seen.append(1), real(*a, **k))[1])])
        self.assertEqual(seen, [])

    def test_all_three_share_one_transaction(self):
        conns = []
        names = ("_insert_event_row", "_insert_analysis_provenance",
                 "_insert_analysis_result_snapshot")
        originals = {n: getattr(_db, n) for n in names}
        for name in names:
            real = originals[name]

            def spy(conn, *a, _real=real, _n=name, **k):
                conns.append((_n, id(conn)))
                return _real(conn, *a, **k)
            setattr(_db, name, spy)
        try:
            self._post("/analyze", self._body())
        finally:
            # Exact restoration: a spy left installed would leak into every
            # later test in this module and in any module discovery runs next.
            for name, real in originals.items():
                setattr(_db, name, real)
        ids = {c for _, c in conns}
        self.assertEqual(len(conns), 3, f"expected three writers, saw {conns}")
        self.assertEqual(len(ids), 1, "all three must share one connection")
        for name in names:
            self.assertIs(getattr(_db, name), originals[name],
                          f"{name} was not restored")

    def test_a_mock_run_creates_no_snapshot(self):
        with patch("routes.analyze._is_mock_analysis", return_value=True):
            self._post("/analyze", self._body())
        self.assertEqual(self._counts(), (0, 0, 0))
        self.assertEqual(self._linked(), {None})

    def test_a_retry_creates_no_second_snapshot(self):
        first = self._post("/analyze", self._body()).json()["analysis_event_id"]
        self._post("/analyze", self._body())
        self.assertEqual(self._counts()[2], 1)
        self.assertEqual(self._linked(), {first})


# ---------------------------------------------------------------------------
# Legacy rows stay honest
# ---------------------------------------------------------------------------

class TestLegacyRows(_RouteBase):

    def test_a_legacy_event_keeps_honest_missingness(self):
        legacy = _db.save_event({
            "headline": "Legacy analysis with no snapshot",
            "stage": "breaking", "persistence": "transient",
            "event_date": "2026-07-01", "mechanism_summary": "stored",
            "what_changed": "stored", "confidence": "medium"})
        resp = self._post("/analyze", {"headline": "Legacy analysis with no snapshot",
                                       "event_id": legacy}).json()
        analysis = resp["analysis"]
        self.assertEqual(analysis.get("mechanism_summary"), "stored")
        self.assertFalse(analysis.get("key_falsifiers"))
        self.assertFalse(analysis.get("primary_assets"))
        self.assertEqual(self.provider_calls, [])

    def test_reading_a_legacy_event_creates_no_snapshot_and_no_write(self):
        legacy = _db.save_event({
            "headline": "Legacy read-only check", "stage": "breaking",
            "persistence": "transient", "event_date": "2026-07-01",
            "mechanism_summary": "stored", "what_changed": "stored",
            "confidence": "medium"})
        before = self._counts()
        self._post("/analyze", {"headline": "Legacy read-only check",
                                "event_id": legacy})
        self.assertEqual(self._counts(), before)
        self.assertIsNone(_db.load_analysis_result_snapshot(legacy))


# ---------------------------------------------------------------------------
# Research-governance isolation
# ---------------------------------------------------------------------------

class TestResearchIsolation(unittest.TestCase):

    def test_no_research_consumer_reads_the_snapshot(self):
        """A static consumer scan — the snapshot is a display record only."""
        import pathlib
        roots = ["db.py", "api.py", "eval.py", "routes", "stats", "scripts"]
        allowed = {"db.py", "api.py", "analysis_result_snapshot.py",
                   "routes/analyze.py"}
        offenders = []
        for root in roots:
            p = pathlib.Path(root)
            files = [p] if p.is_file() else list(p.rglob("*.py"))
            for f in files:
                rel = f.as_posix()
                if rel in allowed:
                    continue
                text = f.read_text(encoding="utf-8", errors="ignore")
                if "analysis_result_snapshot" in text:
                    offenders.append(rel)
        self.assertEqual(offenders, [],
                         f"research/consumer code must not read the snapshot: {offenders}")

    def test_track_record_does_not_reference_the_snapshot(self):
        import inspect
        import db as _dbm
        self.assertNotIn("analysis_result_snapshot",
                         inspect.getsource(_dbm.compute_track_record))


if __name__ == "__main__":
    unittest.main()
