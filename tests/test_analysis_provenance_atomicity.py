"""A1-2 — atomic persistence of analysis + provenance, and link sequencing.

The three artifacts of a successful Inbox-originated analysis are one logical
operation:

    events row  →  analysis_provenance row  →  registry linkage

Failure anywhere upstream must leave NOTHING downstream.  In particular a
provenance failure must not leave a linked candidate that reads as analyzed,
because that is exactly the state a reviewer would mistake for a verified
analysis.

Both routes are exercised so streaming and non-streaming stay identical.
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

import analysis_provenance as ap
import api as _api
import db as _db
from event_inbox import candidate_event_id
from news_sources import _dedup_key

_TITLE = "Oil prices climb after pipeline outage"
_OTHER = "Central bank holds policy rate steady"
_KEY = _dedup_key(_TITLE)
_OTHER_KEY = _dedup_key(_OTHER)
_PARENT = 4211
_CANDIDATE = candidate_event_id(_PARENT, _KEY)
_NOW = "2026-07-26T10:00:00"


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


def _records() -> list[dict]:
    def rec(source, title, ts):
        return {"source": source, "title": title, "published_at": ts,
                "url": f"https://example.test/{source}".replace(" ", "-")}
    return [
        rec("Reuters World", _TITLE, "2026-07-07T09:00:00"),
        rec("BBC Business", _TITLE, "2026-07-07T11:30:00"),
        rec("CNBC World", _OTHER, "2026-07-07T12:00:00"),
    ]


class _RouteBase(unittest.TestCase):

    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_ap_atomic_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()
        self._seed_clusters()
        self._seed_registry()
        self.client = TestClient(_api.app)
        self.provider_calls: list = []

    def tearDown(self):
        _db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    # -- fixtures ------------------------------------------------------
    def _seed_clusters(self):
        conn = sqlite3.connect(self._tmp)
        conn.execute(
            "INSERT OR REPLACE INTO news_clusters "
            "(id, headline, payload_json, records_json, latest_published_at, "
            " updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (_PARENT, _TITLE, json.dumps({}), json.dumps(_records()),
             "2026-07-07T12:00:00", "2026-07-07T12:00:00"))
        conn.commit()
        conn.close()

    def _seed_registry(self, rows=None):
        rows = rows or [("Reuters World", _KEY, _PARENT, None),
                        ("BBC Business", _KEY, _PARENT, None)]
        conn = sqlite3.connect(self._tmp)
        for source, key, cluster_id, event_id in rows:
            conn.execute(
                "INSERT OR REPLACE INTO headline_registry "
                "(source, title_key, cluster_id, event_id, state, "
                " first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source, key, cluster_id, event_id,
                 "analyzed" if event_id else "seen", _NOW, _NOW))
        conn.commit()
        conn.close()

    # -- observations --------------------------------------------------
    def _counts(self) -> tuple[int, int]:
        conn = sqlite3.connect(self._tmp)
        events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        prov = conn.execute(
            "SELECT COUNT(*) FROM analysis_provenance").fetchone()[0]
        conn.close()
        return events, prov

    def _linked_ids(self) -> set:
        conn = sqlite3.connect(self._tmp)
        rows = conn.execute(
            "SELECT event_id FROM headline_registry WHERE title_key = ?",
            (_KEY,)).fetchall()
        conn.close()
        return {r[0] for r in rows}

    def _body(self, **over) -> dict:
        b = {"headline": _TITLE, "event_context": "Sources (2): Reuters, BBC",
             "candidate_id": _CANDIDATE, "parent_cluster_id": _PARENT,
             "title_key": _KEY, "confirm_paid": True}
        b.update(over)
        return b

    def _fake_provider(self, *a, **k):
        self.provider_calls.append((a, k))
        return _analysis()

    def _post(self, path: str, body: dict, extra=None):
        stack = [patch("routes.analyze._call_analyze_event", self._fake_provider),
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

    def _frames(self, resp) -> list[dict]:
        return [json.loads(ln[6:]) for ln in resp.text.splitlines()
                if ln.startswith("data: ")]


# ---------------------------------------------------------------------------
# Success: all three artifacts, exactly once
# ---------------------------------------------------------------------------

class TestSuccessfulAnalysisPersistsAllThree(_RouteBase):

    def test_analyze_creates_event_provenance_and_link(self):
        resp = self._post("/analyze", self._body())
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        new_id = body.get("analysis_event_id")
        self.assertIsInstance(new_id, int)
        self.assertEqual(self._counts(), (1, 1))
        self.assertEqual(self._linked_ids(), {new_id})
        stored = _db.load_analysis_provenance(new_id)
        self.assertEqual(stored["candidate_id"], _CANDIDATE)
        self.assertEqual(ap.verify_provenance(stored), [])

    def test_stream_creates_the_identical_three(self):
        resp = self._post("/analyze/stream", self._body())
        terminal = self._frames(resp)[-1]
        new_id = terminal.get("analysis_event_id")
        self.assertIsInstance(new_id, int)
        self.assertEqual(self._counts(), (1, 1))
        self.assertEqual(self._linked_ids(), {new_id})

    def test_snapshot_holds_only_the_candidates_own_records(self):
        resp = self._post("/analyze", self._body())
        stored = _db.load_analysis_provenance(resp.json()["analysis_event_id"])
        snap = stored["candidate_snapshot"]
        self.assertEqual({r["source"] for r in snap["records"]},
                         {"Reuters World", "BBC Business"})
        self.assertNotIn("CNBC World", {r["source"] for r in snap["records"]})

    def test_persisted_context_is_the_exact_context_sent(self):
        exact = "Summary: pipeline outage.\nAgreement: consistent"
        resp = self._post("/analyze", self._body(event_context=exact))
        stored = _db.load_analysis_provenance(resp.json()["analysis_event_id"])
        self.assertEqual(stored["candidate_context_snapshot"], exact)

    def test_prompt_snapshots_are_the_real_rendered_prompts(self):
        from analyze_event import SYSTEM_PROMPT, render_analysis_prompt
        resp = self._post("/analyze", self._body())
        stored = _db.load_analysis_provenance(resp.json()["analysis_event_id"])
        self.assertEqual(stored["system_prompt_snapshot"], SYSTEM_PROMPT)
        self.assertIn(_TITLE, stored["rendered_user_prompt_snapshot"])
        self.assertEqual(
            stored["rendered_user_prompt_snapshot"],
            render_analysis_prompt(
                headline=_TITLE,
                stage=stored["candidate_snapshot"].get("stage", "")
                or stored.get("stage", ""),
                persistence=stored.get("persistence", ""),
                event_context=stored["candidate_context_snapshot"],
                macro_context=stored["macro_context_snapshot"],
            ))


# ---------------------------------------------------------------------------
# Failure: nothing downstream survives
# ---------------------------------------------------------------------------

class TestFailuresLeaveNothingDownstream(_RouteBase):

    def test_event_persistence_failure_creates_none_of_the_three(self):
        # Patch the seam the CANDIDATE path actually calls.  A candidate run
        # no longer goes through save_event — it shares one transaction via
        # _insert_event_row — so patching save_event here would be a dead
        # no-op and the test would pass while proving nothing.
        resp = self._post("/analyze", self._body(), extra=[
            patch.object(_db, "_insert_event_row",
                         side_effect=RuntimeError("disk full"))])
        body = resp.json()
        self.assertTrue(body.get("persistence_failed"))
        self.assertIsNone(body.get("analysis_event_id"))
        self.assertEqual(self._counts(), (0, 0))
        self.assertEqual(self._linked_ids(), {None})

    def test_provenance_failure_rolls_back_the_event_and_skips_the_link(self):
        resp = self._post("/analyze", self._body(), extra=[
            patch.object(_db, "_insert_analysis_provenance",
                         side_effect=RuntimeError("provenance write failed"))])
        body = resp.json()
        self.assertTrue(body.get("persistence_failed"),
                        "a provenance failure must not report a clean save")
        self.assertEqual(self._counts(), (0, 0),
                         "the events row must roll back with the provenance row")
        self.assertEqual(self._linked_ids(), {None})

    def test_provenance_failure_never_yields_a_verified_state(self):
        resp = self._post("/analyze", self._body(), extra=[
            patch.object(_db, "_insert_analysis_provenance",
                         side_effect=RuntimeError("provenance write failed"))])
        prov = resp.json().get("provenance") or {}
        self.assertNotEqual(prov.get("status"), "VERIFIED_CURRENT")

    def test_stream_provenance_failure_behaves_identically(self):
        resp = self._post("/analyze/stream", self._body(), extra=[
            patch.object(_db, "_insert_analysis_provenance",
                         side_effect=RuntimeError("provenance write failed"))])
        terminal = self._frames(resp)[-1]
        self.assertTrue(terminal.get("persistence_failed"))
        self.assertEqual(self._counts(), (0, 0))
        self.assertEqual(self._linked_ids(), {None})

    def test_mock_analysis_creates_no_event_provenance_or_link(self):
        with patch("routes.analyze._is_mock_analysis", return_value=True):
            resp = self._post("/analyze", self._body())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._counts(), (0, 0))
        self.assertEqual(self._linked_ids(), {None})

    def test_an_unresolvable_candidate_fails_closed_before_the_provider(self):
        conn = sqlite3.connect(self._tmp)
        conn.execute("DELETE FROM news_clusters WHERE id = ?", (_PARENT,))
        conn.commit()
        conn.close()
        resp = self._post("/analyze", self._body())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"),
                         "candidate_provenance_unavailable")
        self.assertEqual(self.provider_calls, [],
                         "an unresolvable candidate must not reach a provider")
        self.assertEqual(self._counts(), (0, 0))
        self.assertEqual(self._linked_ids(), {None})


# ---------------------------------------------------------------------------
# Link sequencing, conflicts and idempotency
# ---------------------------------------------------------------------------

class TestLinkSequencingAndIdempotency(_RouteBase):

    def test_a_registry_conflict_is_not_overwritten_and_is_visible(self):
        self._seed_registry([("Reuters World", _KEY, _PARENT, 42),
                             ("BBC Business", _KEY, _PARENT, 99)])
        resp = self._post("/analyze", self._body())
        self.assertEqual(self._linked_ids(), {42, 99})
        self.assertEqual(resp.json().get("candidate_link"), "conflict")

    def test_a_conflicted_candidate_cannot_read_as_verified_current(self):
        self._seed_registry([("Reuters World", _KEY, _PARENT, 42),
                             ("BBC Business", _KEY, _PARENT, 99)])
        resp = self._post("/analyze", self._body())
        prov = resp.json().get("provenance") or {}
        self.assertNotEqual(prov.get("status"), "VERIFIED_CURRENT")

    def test_repeating_the_same_analysis_creates_no_duplicate_provenance(self):
        first = self._post("/analyze", self._body()).json()["analysis_event_id"]
        self._post("/analyze", self._body())
        events, prov = self._counts()
        self.assertEqual(prov, 1, "one analysis event keeps exactly one snapshot")
        self.assertEqual(self._linked_ids(), {first})

    def test_linkage_happens_only_after_provenance_is_committed(self):
        order: list[str] = []
        real_link = _db.link_candidate_analysis
        real_insert = _db._insert_analysis_provenance

        def spy_insert(conn, provenance):
            order.append("provenance")
            return real_insert(conn, provenance)

        def spy_link(*a, **k):
            order.append("link")
            return real_link(*a, **k)

        self._post("/analyze", self._body(), extra=[
            patch.object(_db, "_insert_analysis_provenance", spy_insert),
            patch.object(_api, "link_candidate_analysis", spy_link)])
        self.assertEqual(order, ["provenance", "link"])


# ---------------------------------------------------------------------------
# Saved reuse — no provider, honest state
# ---------------------------------------------------------------------------

class TestSavedReuseIsProviderFree(_RouteBase):

    def _run_once(self) -> int:
        return self._post("/analyze", self._body()).json()["analysis_event_id"]

    def test_reopening_a_saved_analysis_calls_no_provider(self):
        saved = self._run_once()
        self.provider_calls.clear()
        resp = self._post("/analyze", {"headline": _TITLE, "event_id": saved})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.provider_calls, [])
        self.assertEqual(self._counts()[0], 1)

    def test_an_unchanged_basis_reads_verified_current(self):
        saved = self._run_once()
        resp = self._post("/analyze", {"headline": _TITLE, "event_id": saved})
        prov = resp.json().get("provenance") or {}
        self.assertEqual(prov.get("status"), "VERIFIED_CURRENT")
        self.assertEqual(prov.get("changed_dimensions"), [])

    def test_changed_candidate_records_read_as_older_basis(self):
        saved = self._run_once()
        self.provider_calls.clear()  # the seeding run legitimately called it
        conn = sqlite3.connect(self._tmp)
        extra = _records() + [{"source": "AFP", "title": _TITLE,
                               "published_at": "2026-07-08T09:00:00",
                               "url": "https://example.test/afp"}]
        conn.execute("UPDATE news_clusters SET records_json = ? WHERE id = ?",
                     (json.dumps(extra), _PARENT))
        conn.commit()
        conn.close()
        resp = self._post("/analyze", {"headline": _TITLE, "event_id": saved})
        prov = resp.json().get("provenance") or {}
        self.assertEqual(prov.get("status"), "SAVED_WITH_OLDER_BASIS")
        self.assertIn("candidate_records", prov.get("changed_dimensions") or [])
        self.assertEqual(self.provider_calls, [],
                         "a stale basis must never trigger re-analysis")

    def test_a_legacy_event_reads_as_provenance_unavailable(self):
        legacy = _db.save_event({
            "headline": "Legacy analysis with no provenance",
            "stage": "breaking", "persistence": "transient",
            "event_date": "2026-07-01", "mechanism_summary": "stored",
            "what_changed": "stored", "confidence": "medium"})
        resp = self._post("/analyze", {"headline": "Legacy analysis with no provenance",
                                       "event_id": legacy})
        prov = resp.json().get("provenance") or {}
        self.assertEqual(prov.get("status"), "LEGACY_PROVENANCE_UNAVAILABLE")
        self.assertEqual(self.provider_calls, [])

    def test_tampered_stored_provenance_reads_invalid(self):
        saved = self._run_once()
        self.provider_calls.clear()  # the seeding run legitimately called it
        conn = sqlite3.connect(self._tmp)
        conn.execute("UPDATE analysis_provenance SET model = 'swapped' "
                     "WHERE analysis_event_id = ?", (saved,))
        conn.commit()
        conn.close()
        resp = self._post("/analyze", {"headline": _TITLE, "event_id": saved})
        prov = resp.json().get("provenance") or {}
        self.assertEqual(prov.get("status"), "PROVENANCE_INVALID")
        self.assertEqual(self.provider_calls, [])


if __name__ == "__main__":
    unittest.main()
