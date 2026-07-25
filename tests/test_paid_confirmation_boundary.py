"""A1-1 — explicit paid confirmation on the analysis routes.

Provider work is permitted only when a cache miss is paired with an explicit
``confirm_paid=true`` from the operator AND the existing paid guard passes.  A
cache miss without confirmation fails closed with a structured, non-provider
response; a cache hit is served regardless because it costs nothing.

Successful persistence links every registry row of the strict candidate
``(parent_cluster_id, title_key)`` to the one new numeric ``events.id``.  A
mock, degraded, failed or unpersisted run must never stamp that link.

Every provider seam here is patched; no test calls a real provider.
"""

import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

import api as _api
import db as _db
from event_inbox import candidate_event_id
from news_sources import _dedup_key

_TITLE = "Oil prices climb after pipeline outage"
_KEY = _dedup_key(_TITLE)
_PARENT = 7
# The one derivation the route re-computes; a literal would only prove the
# validator rejects a mismatch, never that a real candidate is accepted.
_CANDIDATE_ID = candidate_event_id(_PARENT, _KEY)
_NOW_ISO = "2026-07-25T12:00:00"


def _analysis(**over) -> dict:
    base = {
        "what_changed": "Pipeline outage removed export capacity.",
        "mechanism_summary": "Supply loss tightens the crude balance.",
        "beneficiaries": ["refiners"], "losers": ["importers"],
        "beneficiary_tickers": [], "loser_tickers": [],
        "assets_to_watch": [], "confidence": "medium",
        "transmission_chain": [], "if_persists": {}, "currency_channel": {},
    }
    base.update(over)
    return base


class _RouteBase(unittest.TestCase):
    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_paid_confirm_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()
        self.client = TestClient(_api.app)
        self.provider_calls: list[tuple] = []

    def tearDown(self):
        _db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    # -- helpers -------------------------------------------------------
    def _seed_registry(self, rows):
        conn = sqlite3.connect(self._tmp)
        for source, key, cluster_id, event_id in rows:
            conn.execute(
                "INSERT OR REPLACE INTO headline_registry "
                "(source, title_key, cluster_id, event_id, state, "
                " first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source, key, cluster_id, event_id,
                 "analyzed" if event_id else "seen", _NOW_ISO, _NOW_ISO))
        conn.commit()
        conn.close()

    def _registry(self):
        conn = sqlite3.connect(self._tmp)
        rows = conn.execute(
            "SELECT source, event_id, state FROM headline_registry "
            "ORDER BY source").fetchall()
        conn.close()
        return rows

    def _event_count(self):
        conn = sqlite3.connect(self._tmp)
        n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        return n

    def _fake_provider(self, *a, **k):
        self.provider_calls.append((a, k))
        return _analysis()

    def _candidate_body(self, **over) -> dict:
        body = {"headline": _TITLE, "event_context": "Sources (2): A, B",
                "candidate_id": _CANDIDATE_ID,
                "parent_cluster_id": _PARENT, "title_key": _KEY}
        body.update(over)
        return body

    def _post(self, path: str, body: dict):
        with patch("routes.analyze._call_analyze_event", self._fake_provider), \
                patch.object(_api, "market_check",
                             return_value={"note": "", "tickers": []}):
            return self.client.post(path, json=body)


class TestPaidConfirmationRequired(_RouteBase):
    """Cache miss without confirmation must never reach the provider."""

    def _assert_blocked(self, resp):
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body.get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])
        self.assertEqual(self._event_count(), 0)

    def test_analyze_blocks_unconfirmed_cache_miss(self):
        self._seed_registry([("Reuters World", _KEY, _PARENT, None)])
        self._assert_blocked(self._post("/analyze", self._candidate_body()))
        self.assertEqual([r[1] for r in self._registry()], [None])

    def test_analyze_stream_blocks_unconfirmed_cache_miss(self):
        self._seed_registry([("Reuters World", _KEY, _PARENT, None)])
        resp = self._post("/analyze/stream", self._candidate_body())
        self.assertEqual(resp.status_code, 200)
        frames = [json.loads(ln[6:]) for ln in resp.text.splitlines()
                  if ln.startswith("data: ")]
        terminal = frames[-1]
        self.assertEqual(terminal.get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])
        self.assertEqual(self._event_count(), 0)
        self.assertEqual([r[1] for r in self._registry()], [None])

    def test_explicit_false_is_the_default(self):
        body = self._candidate_body()
        self.assertNotIn("confirm_paid", body)
        self._assert_blocked(self._post("/analyze", body))


class TestConfirmedAnalysisLinksTheCandidate(_RouteBase):

    def test_confirmed_miss_calls_provider_once_and_links_every_row(self):
        self._seed_registry([("Reuters World", _KEY, _PARENT, None),
                             ("BBC Business", _KEY, _PARENT, None)])
        resp = self._post("/analyze", self._candidate_body(confirm_paid=True))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(self.provider_calls), 1)
        self.assertEqual(self._event_count(), 1)
        new_id = body.get("analysis_event_id")
        self.assertIsInstance(new_id, int)
        rows = self._registry()
        self.assertEqual({r[1] for r in rows}, {new_id})
        self.assertTrue(all(r[2] == "analyzed" for r in rows))

    def test_stream_confirmed_miss_links_identically(self):
        self._seed_registry([("Reuters World", _KEY, _PARENT, None),
                             ("BBC Business", _KEY, _PARENT, None)])
        resp = self._post("/analyze/stream",
                          self._candidate_body(confirm_paid=True))
        frames = [json.loads(ln[6:]) for ln in resp.text.splitlines()
                  if ln.startswith("data: ")]
        terminal = frames[-1]
        self.assertEqual(len(self.provider_calls), 1)
        new_id = terminal.get("analysis_event_id")
        self.assertIsInstance(new_id, int)
        self.assertEqual({r[1] for r in self._registry()}, {new_id})

    def test_no_candidate_identity_means_no_registry_write(self):
        self._seed_registry([("Reuters World", _KEY, _PARENT, None)])
        resp = self._post("/analyze", {"headline": _TITLE, "confirm_paid": True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.provider_calls), 1)
        self.assertEqual([r[1] for r in self._registry()], [None])

    def test_existing_conflict_is_never_overwritten(self):
        self._seed_registry([("Reuters World", _KEY, _PARENT, 42),
                             ("BBC Business", _KEY, _PARENT, 99)])
        self._post("/analyze", self._candidate_body(confirm_paid=True))
        self.assertEqual({r[1] for r in self._registry()}, {42, 99})


class TestFailedRunsNeverLink(_RouteBase):

    def test_mock_analysis_does_not_link_or_persist(self):
        self._seed_registry([("Reuters World", _KEY, _PARENT, None)])
        with patch("routes.analyze._call_analyze_event",
                   side_effect=lambda *a, **k: _analysis(
                       mechanism_summary="[MOCK] no API key configured")), \
                patch("routes.analyze._is_mock_analysis", return_value=True):
            resp = self.client.post("/analyze",
                                    json=self._candidate_body(confirm_paid=True))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._event_count(), 0)
        self.assertEqual([r[1] for r in self._registry()], [None])

    def test_persistence_failure_does_not_link(self):
        self._seed_registry([("Reuters World", _KEY, _PARENT, None)])
        with patch("routes.analyze._call_analyze_event", self._fake_provider), \
                patch.object(_api, "market_check",
                             return_value={"note": "", "tickers": []}), \
                patch.object(_api, "_persist_event",
                             return_value=("disk full", None)):
            resp = self.client.post("/analyze",
                                    json=self._candidate_body(confirm_paid=True))
        body = resp.json()
        self.assertTrue(body.get("persistence_failed"))
        self.assertIsNone(body.get("analysis_event_id"))
        self.assertEqual([r[1] for r in self._registry()], [None])


class TestSavedRetrievalIsFree(_RouteBase):

    def _save_one(self) -> int:
        return _db.save_event({
            "headline": _TITLE, "stage": "breaking", "persistence": "transient",
            "event_date": "2026-07-25", "mechanism_summary": "stored",
            "what_changed": "stored", "confidence": "medium",
        })

    def test_cache_hit_by_event_id_needs_no_confirmation(self):
        saved = self._save_one()
        resp = self._post("/analyze", {"headline": _TITLE, "event_id": saved})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.provider_calls, [])
        self.assertEqual(self._event_count(), 1)

    def test_repeat_access_creates_no_duplicate_row(self):
        saved = self._save_one()
        for _ in range(3):
            self._post("/analyze", {"headline": _TITLE, "event_id": saved})
        self.assertEqual(self.provider_calls, [])
        self.assertEqual(self._event_count(), 1)

    def test_missing_saved_event_never_falls_through_to_a_paid_run(self):
        resp = self._post("/analyze", {"headline": _TITLE, "event_id": 99999})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "paid_confirmation_required")
        self.assertEqual(self.provider_calls, [])
        self.assertEqual(self._event_count(), 0)


class TestCandidateIdentityValidation(_RouteBase):

    def test_identity_fields_are_all_or_none(self):
        for partial in ({"candidate_id": "aei-7-abc"},
                        {"parent_cluster_id": 7},
                        {"title_key": _KEY},
                        {"candidate_id": "aei-7-abc", "parent_cluster_id": 7}):
            with self.subTest(partial=sorted(partial)):
                resp = self.client.post(
                    "/analyze", json={"headline": _TITLE, **partial})
                self.assertEqual(resp.status_code, 422)

    def test_an_aei_string_is_rejected_as_the_numeric_event_id(self):
        resp = self.client.post(
            "/analyze", json={"headline": _TITLE, "event_id": "aei-7-deadbeef"})
        self.assertEqual(resp.status_code, 422)

    def test_candidate_id_must_match_parent_and_title_key(self):
        resp = self.client.post("/analyze", json=self._candidate_body(
            candidate_id="aei-999-deadbeef", confirm_paid=True))
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
