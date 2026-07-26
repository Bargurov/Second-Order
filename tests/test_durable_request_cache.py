"""A1-4 — durable request reuse, universal saved results, bundle atomicity.

Two defects close here:

  * a DIRECT (non-Inbox) analysis persisted an events row but no result
    snapshot, so reopening it showed "Not reported" for fields the run had
    reported — the same persistence loss A1-3R fixed for Inbox runs;
  * the non-numeric reuse path keyed on headline + event_date + model with a
    24-hour TTL, so an unchanged request could bill again after a day, and a
    changed context could be served an old result.

The replacement is an exact request identity over the provider, model, both
prompt snapshots and the contract versions.  Reuse is unlimited in time and
impossible across a changed basis.

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

import analysis_request_identity as ari
import analysis_result_snapshot as ars
import api as _api
import db as _db
from event_inbox import candidate_event_id
from news_sources import _dedup_key

_DIRECT = "Central bank leaves policy rate unchanged"
_INBOX = "Refinery outage cuts regional diesel supply"
_KEY = _dedup_key(_INBOX)
_PARENT = 8801
_CAND = candidate_event_id(_PARENT, _KEY)

FULL = {
    "what_changed": "Outage removed 400kb/d of capacity.",
    "mechanism_summary": "Regional diesel balance tightens through Q3.",
    "beneficiaries": ["independent refiners"], "losers": ["road hauliers"],
    "beneficiary_tickers": [], "loser_tickers": [], "assets_to_watch": [],
    "confidence": "medium",
    "transmission_chain": ["outage", "cracks widen"],
    "transmission_path": [{"step": 1, "node": "Refinery capacity",
                           "so_what": "Supply removed"}],
    "hidden_mechanism": {"transmission_type": "physical_supply",
                         "bottleneck_type": "processing_capacity",
                         "critical_breakpoints": ["Restart before day 10"],
                         "source_quality": {"tier": "single_outlet",
                                            "evidence_limitations": ["One outlet"]}},
    "primary_assets": ["VLO"], "secondary_assets": ["ODFL"],
    "hedge_or_signal_assets": ["XLE"],
    "expected_second_order_channels": ["SUPPLY_CHAIN"],
    "counterforces": [{"force": "SPR release", "effect": "Could offset",
                       "likelihood": "medium"}],
    "substitution_barriers": [{"barrier": "Import berths", "severity": "high"}],
    "competing_thesis": {"thesis": "Demand weakness dominates"},
    "adversarial_challenge": "The outage may be repaired faster.",
    "key_falsifiers": ["Cracks flat after 5 sessions"],
    "minimum_proof_set": ["Diesel crack > +8%"],
    "horizon_checkpoints": {"1d": "Crack reaction"},
    "monitor_plan": ["Weekly EIA inventory print"],
    "quality_tier": "actionable", "quality_warnings": ["Single-outlet estimate"],
    "validation_warnings": ["Ticker set unconfirmed"], "degraded": False,
    "regime_conditioned_caveat": "Holds while imports stay constrained.",
    "if_persists": {}, "currency_channel": {},
}


class _Base(unittest.TestCase):

    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_drc_{uuid.uuid4().hex}.db")
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
        recs = [{"source": "Reuters World", "title": _INBOX,
                 "published_at": "2026-07-20T09:00:00", "url": "u1"},
                {"source": "BBC Business", "title": _INBOX,
                 "published_at": "2026-07-20T11:30:00", "url": "u2"}]
        conn = sqlite3.connect(self._tmp)
        conn.execute("INSERT OR REPLACE INTO news_clusters (id, headline,"
                     " payload_json, records_json, latest_published_at, updated_at)"
                     " VALUES (?,?,?,?,?,?)",
                     (_PARENT, _INBOX, json.dumps({}), json.dumps(recs),
                      "2026-07-20T11:30:00", "2026-07-20T11:30:00"))
        for s in ("Reuters World", "BBC Business"):
            conn.execute("INSERT OR REPLACE INTO headline_registry (source,"
                         " title_key, cluster_id, event_id, state, first_seen_at,"
                         " last_seen_at) VALUES (?,?,?,NULL,'seen','t','t')",
                         (s, _KEY, _PARENT))
        conn.commit()
        conn.close()

    def _provider(self, *a, **k):
        self.provider_calls.append(1)
        return dict(FULL)

    def _post(self, path, body, extra=None):
        # A fixed macro backdrop.  These tests are about request IDENTITY, and
        # since A1-4R the lookup basis is rebuilt from LOCAL data only: with an
        # empty price cache the route would (correctly) report the exact basis
        # unreconstructable and never reach the identity logic under test.
        # Pinning the backdrop makes the local basis deterministic and complete
        # while keeping the macro context genuinely inside the hash.
        # tests/test_analyze_local_lookup_boundary.py covers the real macro
        # path — warm memo, cold-but-covered, partial and absent local prices.
        stack = [patch("routes.analyze._call_analyze_event", self._provider),
                 patch.object(_api, "build_macro_context_for_prompt",
                              return_value="Macro backdrop: fixed for tests"),
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
        n = tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
                  ("events", "analysis_provenance", "analysis_result_snapshot",
                   "analysis_request_cache"))
        conn.close()
        return n

    def _sub(self, analysis):
        return {f: analysis.get(f) for f in ars.RESULT_SNAPSHOT_FIELDS
                if f in analysis}

    def _inbox_body(self, **over):
        b = {"headline": _INBOX, "event_context": "Sources (2)",
             "candidate_id": _CAND, "parent_cluster_id": _PARENT,
             "title_key": _KEY, "confirm_paid": True}
        b.update(over)
        return b


# ---------------------------------------------------------------------------
# Limitation 1 — direct analyses keep their readout
# ---------------------------------------------------------------------------

class TestDirectAnalysisKeepsItsReadout(_Base):

    def test_a_direct_run_creates_event_snapshot_and_mapping_but_no_provenance(self):
        resp = self._post("/analyze", {"headline": _DIRECT,
                                       "confirm_paid": True}).json()
        eid = resp["analysis_event_id"]
        self.assertIsInstance(eid, int)
        self.assertEqual(self._counts(), (1, 0, 1, 1))
        self.assertIsNone(_db.load_analysis_provenance(eid))

    def test_a_direct_run_reports_legacy_provenance_not_a_fabricated_one(self):
        resp = self._post("/analyze", {"headline": _DIRECT,
                                       "confirm_paid": True}).json()
        self.assertEqual(resp["provenance"]["status"],
                         "LEGACY_PROVENANCE_UNAVAILABLE")

    def test_reopening_a_direct_run_by_id_restores_the_full_readout(self):
        fresh = self._post("/analyze", {"headline": _DIRECT,
                                        "confirm_paid": True}).json()
        want = self._sub(fresh["analysis"])
        self.assertGreater(len(want), 15, "the fixture must exercise the readout")
        self.provider_calls.clear()
        again = self._post("/analyze", {"headline": _DIRECT,
                                        "event_id": fresh["analysis_event_id"]}).json()
        self.assertEqual(self._sub(again["analysis"]), want)
        self.assertEqual(self.provider_calls, [])

    def test_reopening_a_direct_run_by_exact_request_restores_the_full_readout(self):
        fresh = self._post("/analyze", {"headline": _DIRECT,
                                        "confirm_paid": True}).json()
        want = self._sub(fresh["analysis"])
        self.provider_calls.clear()
        # No event_id, no confirm_paid — the durable request hash must serve it.
        again = self._post("/analyze", {"headline": _DIRECT}).json()
        self.assertEqual(self._sub(again["analysis"]), want)
        self.assertEqual(self.provider_calls, [])

    def test_reads_create_no_snapshot_or_mapping(self):
        self._post("/analyze", {"headline": _DIRECT, "confirm_paid": True})
        before = self._counts()
        for _ in range(3):
            self._post("/analyze", {"headline": _DIRECT})
        self.assertEqual(self._counts(), before)

    def test_a_legacy_direct_row_keeps_honest_missingness(self):
        legacy = _db.save_event({
            "headline": "Legacy direct row", "stage": "breaking",
            "persistence": "transient", "event_date": "2026-07-01",
            "mechanism_summary": "stored", "what_changed": "stored",
            "confidence": "medium"})
        resp = self._post("/analyze", {"headline": "Legacy direct row",
                                       "event_id": legacy}).json()
        self.assertEqual(resp["analysis"].get("mechanism_summary"), "stored")
        self.assertFalse(resp["analysis"].get("key_falsifiers"))
        self.assertIsNone(_db.load_analysis_result_snapshot(legacy))
        self.assertEqual(self.provider_calls, [])


# ---------------------------------------------------------------------------
# Limitation 2 — durable request reuse
# ---------------------------------------------------------------------------

class TestDurableRequestReuse(_Base):

    def _run(self, headline=_DIRECT, **over):
        return self._post("/analyze", {"headline": headline,
                                       "confirm_paid": True, **over}).json()

    def test_an_exact_repeat_is_served_without_confirmation_or_provider(self):
        first = self._run()
        self.provider_calls.clear()
        again = self._post("/analyze", {"headline": _DIRECT}).json()
        self.assertEqual(again.get("analysis_event_id") or
                         again.get("analysis", {}).get("__id"),
                         again.get("analysis_event_id"))
        self.assertEqual(self.provider_calls, [])
        self.assertNotEqual(again.get("status"), "paid_confirmation_required")
        self.assertEqual(self._sub(again["analysis"]), self._sub(first["analysis"]))

    def test_reuse_is_not_limited_by_the_24_hour_window(self):
        first = self._run()
        eid = first["analysis_event_id"]
        # Age the row far beyond the legacy TTL and its event_date window.
        conn = sqlite3.connect(self._tmp)
        conn.execute("UPDATE events SET timestamp = '2020-01-01T00:00:00',"
                     " event_date = '2020-01-01' WHERE id = ?", (eid,))
        conn.commit()
        conn.close()
        self.provider_calls.clear()
        again = self._post("/analyze", {"headline": _DIRECT}).json()
        self.assertEqual(self.provider_calls, [],
                         "an exact request must reuse regardless of age")
        self.assertEqual(again["analysis_event_id"], eid)

    def test_a_changed_context_misses_and_requires_confirmation(self):
        self._run()
        self.provider_calls.clear()
        miss = self._post("/analyze", {"headline": _DIRECT,
                                       "event_context": "different context"}).json()
        self.assertEqual(miss.get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])

    def test_a_changed_contract_version_misses(self):
        self._run()
        self.provider_calls.clear()
        for attr in ("ANALYSIS_PROMPT_VERSION", "ANALYSIS_SCHEMA_VERSION"):
            with self.subTest(bumped=attr):
                import analysis_provenance as ap
                with patch.object(ap, attr, "bumped-v99"):
                    miss = self._post("/analyze", {"headline": _DIRECT}).json()
                self.assertEqual(miss.get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])

    def test_a_changed_model_misses(self):
        self._run()
        self.provider_calls.clear()
        with patch.object(_api, "_active_model", return_value="some-other-model"):
            miss = self._post("/analyze", {"headline": _DIRECT}).json()
        self.assertEqual(miss.get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])

    def test_a_miss_without_confirmation_never_reaches_a_provider(self):
        miss = self._post("/analyze", {"headline": "Never analyzed headline"}).json()
        self.assertEqual(miss.get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])
        self.assertEqual(self._counts(), (0, 0, 0, 0))

    def test_a_mapping_to_a_missing_event_fails_closed(self):
        first = self._run()
        conn = sqlite3.connect(self._tmp)
        conn.execute("DELETE FROM events WHERE id = ?",
                     (first["analysis_event_id"],))
        conn.commit()
        conn.close()
        self.provider_calls.clear()
        resp = self._post("/analyze", {"headline": _DIRECT}).json()
        self.assertEqual(resp.get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])

    def test_a_mapping_to_a_malformed_snapshot_fails_closed(self):
        first = self._run()
        conn = sqlite3.connect(self._tmp)
        conn.execute("UPDATE analysis_result_snapshot SET result_json = '{bad'"
                     " WHERE analysis_event_id = ?", (first["analysis_event_id"],))
        conn.commit()
        conn.close()
        self.provider_calls.clear()
        resp = self._post("/analyze", {"headline": _DIRECT}).json()
        self.assertEqual(resp.get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])

    def test_streaming_uses_the_same_durable_lookup(self):
        first = self._run()
        self.provider_calls.clear()
        resp = self._post("/analyze/stream", {"headline": _DIRECT})
        frames = [json.loads(l[6:]) for l in resp.text.splitlines()
                  if l.startswith("data: ")]
        terminal = frames[-1]
        self.assertEqual(self.provider_calls, [])
        self.assertEqual(self._sub(terminal["analysis"]),
                         self._sub(first["analysis"]))

    def test_streaming_misses_identically_on_a_changed_basis(self):
        self._run()
        self.provider_calls.clear()
        resp = self._post("/analyze/stream", {"headline": _DIRECT,
                                              "event_context": "changed"})
        frames = [json.loads(l[6:]) for l in resp.text.splitlines()
                  if l.startswith("data: ")]
        self.assertEqual(frames[-1].get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])


# ---------------------------------------------------------------------------
# Lookup order
# ---------------------------------------------------------------------------

class TestLookupOrder(_Base):

    def test_a_numeric_id_wins_over_the_durable_hash(self):
        a = self._post("/analyze", {"headline": _DIRECT,
                                    "confirm_paid": True}).json()
        b = self._post("/analyze", {"headline": "Another direct headline",
                                    "confirm_paid": True}).json()
        self.provider_calls.clear()
        # The headline matches a's request basis, but the explicit id must
        # win.  Assert on the restored event id, not the echoed headline:
        # _build_cached_response echoes the REQUEST headline by long-standing
        # design, so a headline assertion would prove nothing here.
        got = self._post("/analyze", {"headline": _DIRECT,
                                      "event_id": b["analysis_event_id"]}).json()
        self.assertEqual(got["analysis_event_id"], b["analysis_event_id"])
        self.assertNotEqual(got["analysis_event_id"], a["analysis_event_id"])
        self.assertEqual(self.provider_calls, [])

    def test_a_stale_numeric_id_never_falls_through_to_a_paid_run(self):
        resp = self._post("/analyze", {"headline": _DIRECT,
                                       "event_id": 999999}).json()
        self.assertEqual(resp.get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])

    def test_a_legacy_headline_row_still_serves_within_its_old_window(self):
        # A pre-A1-4 row: saved directly, so it has no request mapping.
        _db.save_event({"headline": "Pre-A1-4 legacy headline",
                        "stage": "breaking", "persistence": "transient",
                        "event_date": _api.datetime.now().strftime("%Y-%m-%d"),
                        "mechanism_summary": "stored", "what_changed": "stored",
                        "confidence": "medium",
                        "model": _api._active_model()})
        resp = self._post("/analyze", {"headline": "Pre-A1-4 legacy headline"}).json()
        self.assertNotEqual(resp.get("status"), "paid_confirmation_required")
        self.assertEqual(resp["analysis"].get("mechanism_summary"), "stored")
        self.assertEqual(self.provider_calls, [])

    def test_the_legacy_fallback_cannot_override_a_changed_basis(self):
        """A row WITH a mapping must not be reachable by a weak headline match
        once its request basis changed."""
        self._post("/analyze", {"headline": _DIRECT, "confirm_paid": True})
        self.provider_calls.clear()
        resp = self._post("/analyze", {"headline": _DIRECT,
                                       "event_context": "materially different"}).json()
        self.assertEqual(resp.get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])


# ---------------------------------------------------------------------------
# Atomicity — both bundles
# ---------------------------------------------------------------------------

class TestBundleAtomicity(_Base):

    def _linked(self):
        conn = sqlite3.connect(self._tmp)
        rows = {r[0] for r in conn.execute(
            "SELECT event_id FROM headline_registry WHERE title_key = ?", (_KEY,))}
        conn.close()
        return rows

    def test_inbox_bundle_writes_all_four_then_links(self):
        resp = self._post("/analyze", self._inbox_body()).json()
        self.assertEqual(self._counts(), (1, 1, 1, 1))
        self.assertEqual(self._linked(), {resp["analysis_event_id"]})

    def test_direct_bundle_writes_three_and_no_provenance(self):
        self._post("/analyze", {"headline": _DIRECT, "confirm_paid": True})
        self.assertEqual(self._counts(), (1, 0, 1, 1))

    def test_each_inbox_writer_failure_rolls_back_the_whole_bundle(self):
        for seam in ("_insert_event_row", "_insert_analysis_provenance",
                     "_insert_analysis_result_snapshot",
                     "_insert_analysis_request_mapping"):
            with self.subTest(seam=seam):
                resp = self._post("/analyze", self._inbox_body(), extra=[
                    patch.object(_db, seam, side_effect=RuntimeError("boom"))]).json()
                self.assertTrue(resp.get("persistence_failed"))
                self.assertEqual(self._counts(), (0, 0, 0, 0))
                self.assertEqual(self._linked(), {None})

    def test_each_direct_writer_failure_rolls_back_the_whole_bundle(self):
        for seam in ("_insert_event_row", "_insert_analysis_result_snapshot",
                     "_insert_analysis_request_mapping"):
            with self.subTest(seam=seam):
                resp = self._post("/analyze", {"headline": _DIRECT,
                                               "confirm_paid": True}, extra=[
                    patch.object(_db, seam, side_effect=RuntimeError("boom"))]).json()
                self.assertTrue(resp.get("persistence_failed"))
                self.assertEqual(self._counts(), (0, 0, 0, 0))

    def test_linkage_is_never_attempted_after_a_failed_bundle(self):
        seen = []
        real = _db.link_candidate_analysis
        self._post("/analyze", self._inbox_body(), extra=[
            patch.object(_db, "_insert_analysis_request_mapping",
                         side_effect=RuntimeError("boom")),
            patch.object(_api, "link_candidate_analysis",
                         side_effect=lambda *a, **k: (seen.append(1),
                                                      real(*a, **k))[1])])
        self.assertEqual(seen, [])

    def test_a_mock_run_writes_nothing(self):
        with patch("routes.analyze._is_mock_analysis", return_value=True):
            self._post("/analyze", {"headline": _DIRECT, "confirm_paid": True})
            self._post("/analyze", self._inbox_body())
        self.assertEqual(self._counts(), (0, 0, 0, 0))


# ---------------------------------------------------------------------------
# Research isolation
# ---------------------------------------------------------------------------

class TestResearchIsolation(unittest.TestCase):

    def test_no_research_consumer_reads_the_request_mapping(self):
        import pathlib
        allowed = {"db.py", "api.py", "analysis_request_identity.py",
                   "routes/analyze.py"}
        offenders = []
        for root in ("db.py", "api.py", "eval.py", "routes", "stats", "scripts"):
            p = pathlib.Path(root)
            if not p.exists():
                continue
            for f in ([p] if p.is_file() else list(p.rglob("*.py"))):
                rel = f.as_posix()
                if rel in allowed:
                    continue
                text = f.read_text(encoding="utf-8", errors="ignore")
                if "analysis_request_cache" in text or "request_hash" in text:
                    offenders.append(rel)
        self.assertEqual(offenders, [], f"offenders={offenders}")

    def test_track_record_does_not_reference_the_mapping(self):
        import inspect
        self.assertNotIn("analysis_request_cache",
                         inspect.getsource(_db.compute_track_record))


if __name__ == "__main__":
    unittest.main()
