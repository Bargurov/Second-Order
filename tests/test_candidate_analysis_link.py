"""A1-1 — strict candidate ↔ persisted analysis linkage.

A strict Automatic Event Inbox candidate is identified by
``(parent_cluster_id, title_key)``: the parent cluster supplies provenance and
``title_key`` is the exact ``_dedup_key`` the partition was formed on.  A
candidate may own records from several sources sharing that one key, so the
link scope is BOTH fields — never one representative source.

These tests pin the registry-link helpers and the ``automatic-event-inbox-v3``
analysis_target that exposes them.  Nothing here calls a provider.
"""

import os
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

import db
import event_inbox
from event_inbox import CONTRACT_VERSION, build_inbox, validate_inbox_payload
from news_sources import _dedup_key

_NOW = datetime(2026, 7, 25, 12, 0, 0)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _rec(source: str, title: str, hours_ago: int = 2) -> dict:
    return {"source": source, "title": title,
            "published_at": _iso(_NOW - timedelta(hours=hours_ago)), "url": ""}


def _row(cid: int, records: list[dict], *, headline: str | None = None) -> dict:
    from news_fetch import source_tier
    head = headline if headline is not None else (records[0]["title"] if records else "")
    seen: set[str] = set()
    sources = []
    for r in records:
        if r["source"] in seen:
            continue
        seen.add(r["source"])
        sources.append({"name": r["source"], "tier": source_tier(r["source"]), "url": ""})
    pubs = [r["published_at"] for r in records if r.get("published_at")]
    payload = {
        "headline": head, "summary": head,
        "consensus": {"actors": [], "action": "unknown", "geography": [],
                      "sector": "unknown", "uncertainty": "medium",
                      "consensus": "consensus"},
        "sources": sources, "published_at": max(pubs) if pubs else "",
        "source_count": len(sources), "agreement": "consistent", "evidence": [],
    }
    return {"id": cid, "headline": head, "payload": payload, "records": records,
            "latest_published_at": max(pubs) if pubs else "",
            "updated_at": _iso(_NOW)}


class _RegistryBase(unittest.TestCase):
    """Real temp SQLite so the registry helpers are exercised for real."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_cand_link_{uuid.uuid4().hex}.db")
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _seed_registry(self, rows: list[tuple[str, str, int, int | None]]) -> None:
        """rows = [(source, title_key, cluster_id, event_id|None)]"""
        conn = sqlite3.connect(self._tmp)
        for source, key, cluster_id, event_id in rows:
            conn.execute(
                "INSERT OR REPLACE INTO headline_registry "
                "(source, title_key, cluster_id, event_id, state, "
                " first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source, key, cluster_id, event_id,
                 "analyzed" if event_id else "seen", _iso(_NOW), _iso(_NOW)))
        conn.commit()
        conn.close()

    def _registry_rows(self) -> list[tuple]:
        conn = sqlite3.connect(self._tmp)
        rows = conn.execute(
            "SELECT source, title_key, cluster_id, event_id, state, analyzed_at "
            "FROM headline_registry ORDER BY source").fetchall()
        conn.close()
        return rows


class TestCandidateLinkRead(_RegistryBase):

    def test_no_matching_rows_is_unanalyzed(self):
        link = db.get_candidate_analysis_link(7, _dedup_key("Oil prices climb"))
        self.assertEqual(link["status"], "unanalyzed")
        self.assertIsNone(link["analysis_event_id"])

    def test_rows_without_event_id_are_unanalyzed(self):
        key = _dedup_key("Oil prices climb")
        self._seed_registry([("Reuters World", key, 7, None),
                             ("BBC Business", key, 7, None)])
        link = db.get_candidate_analysis_link(7, key)
        self.assertEqual(link["status"], "unanalyzed")
        self.assertIsNone(link["analysis_event_id"])

    def test_agreeing_rows_across_sources_resolve_to_one_event_id(self):
        key = _dedup_key("Oil prices climb")
        self._seed_registry([("Reuters World", key, 7, 42),
                             ("BBC Business", key, 7, 42),
                             ("FT World", key, 7, 42)])
        link = db.get_candidate_analysis_link(7, key)
        self.assertEqual(link["status"], "analyzed")
        self.assertEqual(link["analysis_event_id"], 42)

    def test_partially_linked_rows_still_resolve_when_they_agree(self):
        key = _dedup_key("Oil prices climb")
        self._seed_registry([("Reuters World", key, 7, 42),
                             ("BBC Business", key, 7, None)])
        link = db.get_candidate_analysis_link(7, key)
        self.assertEqual(link["status"], "analyzed")
        self.assertEqual(link["analysis_event_id"], 42)

    def test_conflicting_event_ids_fail_closed(self):
        key = _dedup_key("Oil prices climb")
        self._seed_registry([("Reuters World", key, 7, 42),
                             ("BBC Business", key, 7, 99)])
        link = db.get_candidate_analysis_link(7, key)
        self.assertEqual(link["status"], "conflict")
        self.assertIsNone(link["analysis_event_id"])

    def test_link_is_scoped_by_parent_cluster_not_title_key_alone(self):
        """The same title_key under a different parent is a different candidate."""
        key = _dedup_key("Oil prices climb")
        self._seed_registry([("Reuters World", key, 7, 42),
                             ("BBC Business", key, 8, 99)])
        self.assertEqual(db.get_candidate_analysis_link(7, key)["analysis_event_id"], 42)
        self.assertEqual(db.get_candidate_analysis_link(8, key)["analysis_event_id"], 99)


class TestCandidateLinkWrite(_RegistryBase):

    def test_links_every_matching_row_of_a_multi_source_candidate(self):
        key = _dedup_key("Oil prices climb")
        self._seed_registry([("Reuters World", key, 7, None),
                             ("BBC Business", key, 7, None),
                             ("FT World", key, 7, None)])
        outcome = db.link_candidate_analysis(7, key, 42, _iso(_NOW))
        self.assertEqual(outcome, "linked")
        rows = self._registry_rows()
        self.assertEqual({r[3] for r in rows}, {42})
        self.assertTrue(all(r[4] == "analyzed" for r in rows))
        self.assertTrue(all(r[5] == _iso(_NOW) for r in rows))

    def test_is_idempotent_when_rows_already_point_at_the_same_analysis(self):
        key = _dedup_key("Oil prices climb")
        self._seed_registry([("Reuters World", key, 7, 42)])
        self.assertEqual(db.link_candidate_analysis(7, key, 42, _iso(_NOW)),
                         "already_linked")
        self.assertEqual({r[3] for r in self._registry_rows()}, {42})

    def test_never_overwrites_a_different_existing_analysis(self):
        key = _dedup_key("Oil prices climb")
        self._seed_registry([("Reuters World", key, 7, 42)])
        outcome = db.link_candidate_analysis(7, key, 77, _iso(_NOW))
        self.assertEqual(outcome, "conflict")
        self.assertEqual({r[3] for r in self._registry_rows()}, {42})

    def test_never_repairs_an_existing_conflict(self):
        key = _dedup_key("Oil prices climb")
        self._seed_registry([("Reuters World", key, 7, 42),
                             ("BBC Business", key, 7, 99)])
        outcome = db.link_candidate_analysis(7, key, 42, _iso(_NOW))
        self.assertEqual(outcome, "conflict")
        self.assertEqual({r[3] for r in self._registry_rows()}, {42, 99})

    def test_creates_no_registry_rows_that_the_refresh_path_did_not_make(self):
        key = _dedup_key("Oil prices climb")
        outcome = db.link_candidate_analysis(7, key, 42, _iso(_NOW))
        self.assertEqual(outcome, "no_rows")
        self.assertEqual(self._registry_rows(), [])

    def test_does_not_touch_rows_of_another_parent_cluster(self):
        key = _dedup_key("Oil prices climb")
        self._seed_registry([("Reuters World", key, 7, None),
                             ("BBC Business", key, 8, None)])
        db.link_candidate_analysis(7, key, 42, _iso(_NOW))
        rows = {r[0]: r[3] for r in self._registry_rows()}
        self.assertEqual(rows["Reuters World"], 42)
        self.assertIsNone(rows["BBC Business"])


class TestSaveEventReturnsId(_RegistryBase):

    def test_save_event_returns_the_new_numeric_id(self):
        new_id = db.save_event({
            "headline": "Oil prices climb after pipeline outage",
            "stage": "breaking", "persistence": "transient",
            "event_date": "2026-07-25",
        })
        self.assertIsInstance(new_id, int)
        self.assertGreater(new_id, 0)
        self.assertIsNotNone(db.load_event_by_id(new_id))


class TestInboxV3AnalysisTarget(_RegistryBase):

    TITLE = "Oil prices climb after pipeline outage"

    def _payload(self):
        rows = [_row(7, [_rec("Reuters World", self.TITLE),
                         _rec("BBC Business", self.TITLE, hours_ago=3)])]
        return build_inbox(rows, now=_NOW)

    def test_contract_is_v3(self):
        self.assertEqual(CONTRACT_VERSION, "automatic-event-inbox-v3")
        self.assertEqual(self._payload()["contract"], "automatic-event-inbox-v3")

    def test_analysis_target_carries_the_exact_identity_field_set(self):
        ev = self._payload()["events"][0]
        self.assertEqual(set(ev["analysis_target"].keys()), {
            "headline", "context", "candidate_id", "parent_cluster_id",
            "title_key", "analysis_link_status", "analysis_event_id"})

    def test_candidate_id_recomputes_from_parent_and_title_key(self):
        ev = self._payload()["events"][0]
        tgt = ev["analysis_target"]
        self.assertEqual(
            tgt["candidate_id"],
            event_inbox.candidate_event_id(tgt["parent_cluster_id"],
                                           tgt["title_key"]))
        self.assertEqual(tgt["candidate_id"], ev["event_id"])

    def test_title_key_is_the_strict_normalized_headline_identity(self):
        tgt = self._payload()["events"][0]["analysis_target"]
        self.assertEqual(tgt["title_key"], _dedup_key(tgt["headline"]))

    def test_parent_cluster_id_is_provenance_only(self):
        ev = self._payload()["events"][0]
        self.assertEqual(ev["analysis_target"]["parent_cluster_id"],
                         ev["cluster_id"])

    def test_unlinked_candidate_is_unanalyzed(self):
        tgt = self._payload()["events"][0]["analysis_target"]
        self.assertEqual(tgt["analysis_link_status"], "unanalyzed")
        self.assertIsNone(tgt["analysis_event_id"])

    def test_linked_candidate_exposes_the_saved_numeric_event_id(self):
        key = _dedup_key(self.TITLE)
        self._seed_registry([("Reuters World", key, 7, 42),
                             ("BBC Business", key, 7, 42)])
        tgt = self._payload()["events"][0]["analysis_target"]
        self.assertEqual(tgt["analysis_link_status"], "analyzed")
        self.assertEqual(tgt["analysis_event_id"], 42)

    def test_conflicting_links_surface_as_conflict_with_no_event_id(self):
        key = _dedup_key(self.TITLE)
        self._seed_registry([("Reuters World", key, 7, 42),
                             ("BBC Business", key, 7, 99)])
        tgt = self._payload()["events"][0]["analysis_target"]
        self.assertEqual(tgt["analysis_link_status"], "conflict")
        self.assertIsNone(tgt["analysis_event_id"])

    def test_multi_source_candidate_reads_all_matching_rows(self):
        """Linkage must not depend on picking one representative source."""
        key = _dedup_key(self.TITLE)
        # Only the NON-representative source carries the link.
        self._seed_registry([("Reuters World", key, 7, None),
                             ("BBC Business", key, 7, 55)])
        tgt = self._payload()["events"][0]["analysis_target"]
        self.assertEqual(tgt["analysis_link_status"], "analyzed")
        self.assertEqual(tgt["analysis_event_id"], 55)

    def test_payload_still_validates_and_counts_reconcile(self):
        payload = self._payload()
        self.assertEqual(validate_inbox_payload(payload), [])
        counts = payload["counts"]
        self.assertEqual(counts["parent_clusters_total"],
                         counts["partitioned_parent_clusters"]
                         + counts["malformed_parent_clusters"])
        self.assertEqual(
            counts["candidates_total"],
            counts["surfaced"] + counts["beyond_window"]
            + counts["excluded_no_material_channel"]
            + counts["malformed_candidates"])
        self.assertEqual(sum(counts["by_lifecycle"].values()), counts["surfaced"])


if __name__ == "__main__":
    unittest.main()
