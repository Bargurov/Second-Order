"""A4 — GET /analysis/representative-case/{candidate_id}.

A provider-free, write-free read contract that resolves one immutable
candidate identity to its linked saved analysis so Evidence Overview can
show a restrained "Representative Live Case" entry point.  Deliberately NOT
under /evidence/* — that lane stays tracked-only.

States: AVAILABLE / CASE_UNLINKED / CASE_NOT_FOUND /
SAVED_ANALYSIS_UNAVAILABLE / PROVENANCE_UNAVAILABLE / INVALID.
A missing or unlinked identity is an explicit state, never a substitute case.
"""

import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

import analysis_provenance as ap
import analysis_request_identity as ari
import analysis_result_snapshot as ars
import api as _api
import db as _db
import market_data as _md
from event_inbox import candidate_event_id
from news_sources import _dedup_key

_HEADLINE = ("Ambassador Greer Issues Statement on President Trump "
             "Imposing Section 338 Tariffs on Canada")
_KEY = _dedup_key(_HEADLINE)
_PARENT = 13530
_CID = candidate_event_id(_PARENT, _KEY)

_ANALYSIS = {
    "what_changed": "Section 338 tariffs imposed on Canadian goods.",
    "mechanism_summary": "Tariffs act as a regulatory gate on landed cost.",
    "beneficiaries": ["US steel producers"], "losers": ["Canadian exporters"],
    "confidence": "medium", "quality_tier": "watch_only",
    "key_falsifiers": ["Tariffs rescinded within one week of imposition"],
    "if_persists": {}, "currency_channel": {},
}


class _Base(unittest.TestCase):

    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_repcase_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()
        self.client = TestClient(_api.app)
        self._seed_cluster()

    def tearDown(self):
        _db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _seed_cluster(self):
        recs = [{"source": "USTR Trade Policy", "title": _HEADLINE,
                 "published_at": "2026-07-20T21:00:00", "url": "u1"}]
        conn = sqlite3.connect(self._tmp)
        conn.execute("INSERT OR REPLACE INTO news_clusters (id, headline,"
                     " payload_json, records_json, latest_published_at,"
                     " updated_at) VALUES (?,?,?,?,?,?)",
                     (_PARENT, _HEADLINE, json.dumps({}), json.dumps(recs),
                      "2026-07-20T21:00:00", "2026-07-20T21:00:00"))
        conn.execute("INSERT OR REPLACE INTO headline_registry (source,"
                     " title_key, cluster_id, event_id, state, first_seen_at,"
                     " last_seen_at) VALUES (?,?,?,NULL,'seen','t','t')",
                     ("USTR Trade Policy", _KEY, _PARENT))
        conn.commit()
        conn.close()

    def _publish(self, *, with_snapshot=True, with_provenance=True):
        """Persist the case the way the live Inbox flow does."""
        prov_builder = None
        if with_provenance:
            prov_builder = lambda i: ap.build_provenance(  # noqa: E731
                analysis_event_id=i, parent_cluster_id=_PARENT,
                title_key=_KEY,
                candidate_snapshot={"headline": _HEADLINE,
                                    "sources": ["USTR Trade Policy"],
                                    "record_count": 1, "records": []},
                candidate_context_snapshot="Summary: official statement",
                provider="anthropic", model="claude-sonnet-4-6",
                system_prompt_snapshot="s",
                rendered_user_prompt_snapshot="p",
                created_at="2026-07-28T00:00:00",
                macro_context_snapshot="m", stage="realized",
                persistence="structural")
        snap_builder = (lambda i: ars.build_result_snapshot(_ANALYSIS)) \
            if with_snapshot else None
        basis = ari.build_request_basis(
            provider="anthropic", model="claude-sonnet-4-6",
            system_prompt="s", rendered_user_prompt="p",
            prompt_version="pv", schema_version="sv",
            event_date="2026-07-20")
        eid, _ = _db.save_event_with_analysis_provenance(
            {"headline": _HEADLINE, "stage": "realized",
             "persistence": "structural", "event_date": "2026-07-20",
             "mechanism_summary": "m", "what_changed": "w",
             "confidence": "medium", "model": "claude-sonnet-4-6"},
            prov_builder, snap_builder,
            lambda i: ari.request_mapping_record(basis))
        _db.link_candidate_analysis(_PARENT, _KEY, int(eid),
                                    "2026-07-28T00:00:00")
        return int(eid)

    def _get(self, cid, *, arm=True):
        stack = []
        if arm:
            class Armed:
                def fetch_daily(self, t, **k):
                    raise AssertionError("market provider reached")

                def fetch_info(self, t):
                    raise AssertionError("market provider reached")

            stack = [patch.object(_md, "_provider", Armed()),
                     patch("routes.analyze._call_analyze_event",
                           lambda *a, **k: (_ for _ in ()).throw(
                               AssertionError("analysis provider reached")))]
        for p in stack:
            p.start()
        try:
            return self.client.get(f"/analysis/representative-case/{cid}")
        finally:
            for p in reversed(stack):
                p.stop()

    def _counts(self):
        conn = sqlite3.connect(self._tmp)
        try:
            return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                         for t in ("events", "analysis_provenance",
                                   "analysis_result_snapshot",
                                   "analysis_request_cache",
                                   "headline_registry", "price_cache"))
        finally:
            conn.close()


class TestLinkedCaseResolves(_Base):

    def test_a_linked_case_resolves_with_every_contract_field(self):
        eid = self._publish()
        body = self._get(_CID).json()
        self.assertEqual(body.get("availability"), "AVAILABLE")
        self.assertEqual(body.get("candidate_id"), _CID)
        self.assertEqual(body.get("analysis_event_id"), eid)
        self.assertEqual(body.get("headline"), _HEADLINE)
        self.assertEqual(body.get("event_date"), "2026-07-20")
        self.assertEqual(body.get("sources"), ["USTR Trade Policy"])
        self.assertEqual(body.get("quality_tier"), "watch_only")
        self.assertIn(body.get("basis_status"),
                      ("VERIFIED_CURRENT", "SAVED_WITH_OLDER_BASIS"))

    def test_the_read_makes_zero_provider_calls_and_zero_writes(self):
        self._publish()
        before = self._counts()
        resp = self._get(_CID, arm=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._counts(), before)

    def test_the_response_carries_no_result_snapshot_body(self):
        """The entry point orients; it must not reproduce the analysis."""
        self._publish()
        body = self._get(_CID).json()
        blob = json.dumps(body)
        self.assertNotIn("mechanism_summary", blob)
        self.assertNotIn("key_falsifiers", blob)
        self.assertNotIn("result_json", blob)


class TestUnavailableStatesAreExplicit(_Base):

    def test_an_unlinked_candidate_reports_CASE_UNLINKED(self):
        body = self._get(_CID).json()
        self.assertEqual(body.get("availability"), "CASE_UNLINKED")
        self.assertIsNone(body.get("analysis_event_id"))

    def test_an_unknown_candidate_reports_CASE_NOT_FOUND(self):
        body = self._get("aei-99999-deadbeef").json()
        self.assertEqual(body.get("availability"), "CASE_NOT_FOUND")

    def test_a_malformed_id_reports_INVALID(self):
        for bad in ("not-an-id", "aei--", "aei-13530-zz",
                    "aei-13530-f0a9907a-extra"):
            body = self._get(bad).json()
            self.assertEqual(body.get("availability"), "INVALID", bad)

    def test_a_missing_snapshot_reports_SAVED_ANALYSIS_UNAVAILABLE(self):
        self._publish(with_snapshot=False)
        body = self._get(_CID).json()
        self.assertEqual(body.get("availability"),
                         "SAVED_ANALYSIS_UNAVAILABLE")

    def test_missing_provenance_reports_PROVENANCE_UNAVAILABLE(self):
        self._publish(with_provenance=False)
        body = self._get(_CID).json()
        self.assertEqual(body.get("availability"), "PROVENANCE_UNAVAILABLE")
        # The identity still resolves — nothing is substituted or hidden.
        self.assertEqual(body.get("headline"), _HEADLINE)

    def test_no_state_ever_substitutes_a_different_case(self):
        other = _db.save_event({
            "headline": "A completely different saved analysis",
            "stage": "breaking", "persistence": "transient",
            "event_date": "2026-07-01", "mechanism_summary": "m",
            "what_changed": "w", "confidence": "medium",
            "model": "claude-sonnet-4-6"})
        self.assertIsNotNone(other)
        for cid in (_CID, "aei-99999-deadbeef"):
            body = self._get(cid).json()
            self.assertNotEqual(body.get("analysis_event_id"), other)


if __name__ == "__main__":
    unittest.main()
