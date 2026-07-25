"""automatic-event-inbox-v1 — cluster time identity (A0-R1).

Every displayed time, ordering key, window decision and lifecycle age for an
inbox event must be derived from the publication timestamps of records the
cluster actually OWNS.  Stored cluster metadata (``latest_published_at``) is
maintained by the refresh writer from the in-memory clusterer output and is
provably able to drift in BOTH directions:

* forward — metadata newer than every owned record, which promoted a nine-day
  old notice to the top of the inbox as if it were current;
* backward — metadata older than a fresh owned record, which silently counted
  a cluster holding yesterday's article as ``beyond_window``.

These tests pin the repaired ownership rule.  Minimal logic fixtures below are
anchored to one fixed clock (never ``datetime.now()``); the tracked
``event_inbox_cluster_rows.json`` rows are used for the producer-shaped
invariant checks.  No test here touches the network or a provider.
"""

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import api as _api
import db as _db
import event_inbox
from event_inbox import (
    CONTRACT_VERSION,
    INBOX_WINDOW_DAYS,
    RESOLVED_AFTER_HOURS,
    build_inbox,
    validate_inbox_payload,
)

_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "event_inbox_cluster_rows.json")

# One anchor clock for every synthetic timestamp in this module.
_NOW = datetime(2026, 7, 25, 12, 0, 0)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _ago(**kw) -> datetime:
    return _NOW - timedelta(**kw)


def _rec(source: str, title: str, at) -> dict:
    """Producer-shaped headline record.  ``at`` may be a datetime or a raw str
    (used to inject malformed / missing publication timestamps)."""
    published = _iso(at) if isinstance(at, datetime) else at
    return {"source": source, "title": title, "published_at": published, "url": ""}


def _row(cid: int, records: list[dict], *, headline: str | None = None,
         latest: str | None = None, summary: str = "",
         agreement: str = "consistent", uncertainty: str = "medium") -> dict:
    """Producer-shaped ``news_clusters`` row (``load_news_clusters`` dict shape).

    ``latest`` is the STORED metadata column and is set independently of the
    records on purpose — that divergence is the defect under test.
    """
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
        "headline": head,
        "summary": summary,
        "consensus": {"actors": [], "action": "unknown", "geography": [],
                      "sector": "unknown", "uncertainty": uncertainty,
                      "consensus": "consensus" if agreement == "consistent" else "mixed"},
        "sources": sources,
        "published_at": max(pubs) if pubs else "",
        "source_count": len(sources),
        "agreement": agreement,
        "evidence": [],
    }
    return {
        "id": cid,
        "headline": head,
        "payload": payload,
        "records": records,
        "latest_published_at": latest if latest is not None else (max(pubs) if pubs else ""),
        "updated_at": _iso(_NOW),
    }


def _by_id(payload: dict, cid: int) -> dict:
    """The single candidate of a parent cluster (fails loudly if it split)."""
    hits = [ev for ev in payload["events"] if ev["cluster_id"] == cid]
    if len(hits) != 1:
        raise AssertionError(
            f"expected exactly one candidate for cluster {cid}, got {len(hits)}: "
            f"{[e['headline'] for e in hits]}")
    return hits[0]


def _partition_for(row: dict, event: dict) -> list[dict]:
    """The identity partition that produced ``event``."""
    for key, recs in event_inbox.partition_records_by_identity(row["records"]):
        if event_inbox.candidate_event_id(row["id"], key) == event["event_id"]:
            return recs
    raise AssertionError(f"no partition matches {event['event_id']}")


def _load_real_rows() -> list[dict]:
    with open(_FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)["rows"]


def _owned_times(row: dict) -> list[datetime]:
    out = []
    for r in row.get("records") or []:
        dt = event_inbox._parse_dt(r.get("published_at"))
        if dt is not None:
            out.append(dt)
    return out


# ---------------------------------------------------------------------------
# The shared derivation seam
# ---------------------------------------------------------------------------

class TestDerivationSeam(unittest.TestCase):
    """One pure rule, reused by every inbox consumer."""

    def test_seam_returns_min_and_max_of_owned_records(self):
        records = [
            _rec("Reuters World", "Oil supply update A", _ago(hours=30)),
            _rec("Bloomberg Markets", "Oil supply update B", _ago(hours=3)),
            _rec("BBC Business", "Oil supply update C", _ago(hours=12)),
        ]
        times = event_inbox.derive_cluster_times(records)
        self.assertEqual(times.first_seen, _ago(hours=30))
        self.assertEqual(times.last_updated, _ago(hours=3))
        self.assertEqual(times.valid_count, 3)
        self.assertEqual(times.record_count, 3)

    def test_seam_is_pure_on_empty_and_never_substitutes_a_clock(self):
        times = event_inbox.derive_cluster_times([])
        self.assertIsNone(times.first_seen)
        self.assertIsNone(times.last_updated)
        self.assertIsNone(times.newest_record)
        self.assertEqual(times.valid_count, 0)

    def test_seam_newest_record_is_the_record_supplying_last_updated(self):
        newest = _rec("Bloomberg Markets", "OPEC extends output cut", _ago(hours=2))
        records = [_rec("Reuters World", "Oil steady in Asia", _ago(hours=9)), newest]
        times = event_inbox.derive_cluster_times(records)
        self.assertEqual(times.newest_record, newest)


# ---------------------------------------------------------------------------
# Ownership: displayed time comes only from owned records
# ---------------------------------------------------------------------------

class TestTimestampOwnership(unittest.TestCase):

    def test_metadata_newer_than_every_owned_record_is_not_displayed(self):
        """Proven defect A: stale cluster promoted as current."""
        stale = _row(101,
                     [_rec("Fed Press Releases",
                           "Federal Reserve issues enforcement action on bank capital",
                           _ago(days=9))],
                     latest=_iso(_ago(hours=1)))
        payload = build_inbox([stale], now=_NOW)
        ev = _by_id(payload, 101)
        self.assertEqual(ev["last_updated_at"], _iso(_ago(days=9)))
        self.assertNotEqual(ev["last_updated_at"], _iso(_ago(hours=1)))

    def test_stale_cluster_is_not_ordered_above_a_genuinely_fresh_one(self):
        stale = _row(101,
                     [_rec("Fed Press Releases",
                           "Federal Reserve issues enforcement action on bank capital",
                           _ago(days=9))],
                     latest=_iso(_ago(hours=1)))
        fresh = _row(102,
                     [_rec("Reuters World",
                           "Oil prices jump after pipeline outage", _ago(hours=2))])
        payload = build_inbox([stale, fresh], now=_NOW)
        order = [ev["cluster_id"] for ev in payload["events"]]
        self.assertEqual(order[0], 102, "fresh cluster must lead the inbox")
        self.assertEqual(order, [102, 101])

    def _copper_row(self, latest: str) -> dict:
        """One identity carried by three sources at three different times."""
        title = "Copper output falls at Chile mine"
        return _row(110, [
            _rec("Reuters World", title, _ago(days=4)),
            _rec("Mining.com", title, _ago(hours=7)),
            _rec("BBC Business", title, _ago(days=2)),
        ], latest=latest)

    def test_newest_owned_record_determines_last_updated_at(self):
        ev = _by_id(build_inbox([self._copper_row("")], now=_NOW), 110)
        self.assertEqual(ev["last_updated_at"], _iso(_ago(hours=7)))

    def test_oldest_owned_record_determines_first_seen_at(self):
        ev = _by_id(build_inbox([self._copper_row(_iso(_ago(minutes=5)))],
                                now=_NOW), 110)
        self.assertEqual(ev["first_seen_at"], _iso(_ago(days=4)))
        self.assertLessEqual(ev["first_seen_at"], ev["last_updated_at"])

    def test_no_surfaced_event_time_exceeds_its_newest_owned_record(self):
        """Producer-shaped invariant over the tracked captured rows.

        Since A0-R2B the owning unit is the identity partition, not the parent
        row, so each candidate is checked against the records IT owns.
        """
        rows = _load_real_rows()
        payload = build_inbox(rows, now=datetime(2026, 7, 7, 12, 0, 0))
        by_cid = {r["id"]: r for r in rows}
        self.assertGreater(len(payload["events"]), 0)
        for ev in payload["events"]:
            part = _partition_for(by_cid[ev["cluster_id"]], ev)
            owned = [d for d in (event_inbox._parse_dt(r.get("published_at"))
                                 for r in part) if d is not None]
            self.assertTrue(owned, f"{ev['event_id']} has no owned times")
            self.assertEqual(ev["last_updated_at"], _iso(max(owned)))
            self.assertEqual(ev["first_seen_at"], _iso(min(owned)))

    def test_record_timestamps_do_not_leak_between_clusters(self):
        a = _row(201, [_rec("Reuters World", "Oil steady after OPEC meeting",
                            _ago(hours=2))], latest=_iso(_ago(days=20)))
        b = _row(202, [_rec("BBC Business", "Inflation eases in the euro area",
                            _ago(days=6))], latest=_iso(_ago(minutes=1)))
        payload = build_inbox([a, b], now=_NOW)
        self.assertEqual(_by_id(payload, 201)["last_updated_at"], _iso(_ago(hours=2)))
        self.assertEqual(_by_id(payload, 202)["last_updated_at"], _iso(_ago(days=6)))
        self.assertEqual(_by_id(payload, 201)["first_seen_at"], _iso(_ago(hours=2)))
        self.assertEqual(_by_id(payload, 202)["first_seen_at"], _iso(_ago(days=6)))


# ---------------------------------------------------------------------------
# Window eligibility
# ---------------------------------------------------------------------------

class TestWindowEligibility(unittest.TestCase):

    def test_in_window_owned_record_survives_older_cluster_metadata(self):
        """Proven defect B: a fresh owned record must not be windowed out by
        stale parent metadata.  Under strict identity the two AFP items are
        different events, so the fresh one surfaces on its own timestamps and
        the genuinely old one is counted beyond_window."""
        row = _row(301, [
            _rec("AFP World", "US tariff schedule published for review", _ago(days=30)),
            _rec("AFP World", "US imposes new tariffs on 60 partners", _ago(days=1)),
        ], headline="US tariff schedule published for review",
            latest=_iso(_ago(days=INBOX_WINDOW_DAYS + 26)))
        payload = build_inbox([row], now=_NOW)
        self.assertEqual(payload["counts"]["beyond_window"], 1)
        ev = _by_id(payload, 301)
        self.assertEqual(ev["headline"], "US imposes new tariffs on 60 partners")
        self.assertEqual(ev["last_updated_at"], _iso(_ago(days=1)))
        self.assertEqual(ev["first_seen_at"], _iso(_ago(days=1)))

    def test_newest_owned_record_outside_window_is_counted_beyond_window(self):
        row = _row(302, [
            _rec("Reuters World", "Oil refinery outage resolved",
                 _ago(days=INBOX_WINDOW_DAYS + 3)),
        ], latest=_iso(_ago(minutes=2)))
        payload = build_inbox([row], now=_NOW)
        self.assertEqual(payload["counts"]["beyond_window"], 1)
        self.assertEqual(payload["events"], [])


# ---------------------------------------------------------------------------
# Lifecycle timing
# ---------------------------------------------------------------------------

class TestLifecycleTiming(unittest.TestCase):

    def test_lifecycle_age_uses_owned_records_not_cluster_metadata(self):
        row = _row(401, [
            _rec("Fed Press Releases",
                 "Federal Reserve issues enforcement action on bank capital",
                 _ago(hours=RESOLVED_AFTER_HOURS + 24)),
        ], latest=_iso(_ago(minutes=30)))
        ev = _by_id(build_inbox([row], now=_NOW), 401)
        self.assertEqual(ev["lifecycle"], "RESOLVED")

    def test_fresh_owned_record_keeps_an_officially_sourced_cluster_new(self):
        row = _row(402, [
            _rec("ECB Press Releases",
                 "ECB adjusts collateral framework interest rate schedule",
                 _ago(hours=3)),
        ], latest=_iso(_ago(days=40)))
        ev = _by_id(build_inbox([row], now=_NOW), 402)
        self.assertEqual(ev["lifecycle"], "NEW")


# ---------------------------------------------------------------------------
# Representative headline
# ---------------------------------------------------------------------------

class TestRepresentativeHeadline(unittest.TestCase):
    """Headline ownership under strict identity partitioning.

    A candidate's headline is the representative of ITS OWN partition, so the
    parent's stored representative can never stand in for a record it does not
    describe.  A parent headline belonging to no record simply names no
    candidate.
    """

    def test_unowned_parent_headline_names_no_candidate(self):
        row = _row(501, [
            _rec("Reuters World", "Oil steady in Asian trade", _ago(hours=9)),
            _rec("Bloomberg Markets", "OPEC extends output cut through December",
                 _ago(hours=2)),
        ], headline="Samsung and SK Hynix unveil chip supply partnerships")
        payload = build_inbox([row], now=_NOW)
        heads = {ev["headline"] for ev in payload["events"]}
        self.assertEqual(heads, {"Oil steady in Asian trade",
                                 "OPEC extends output cut through December"})
        self.assertNotIn("Samsung and SK Hynix unveil chip supply partnerships",
                         heads)
        for ev in payload["events"]:
            self.assertEqual(ev["analysis_target"]["headline"], ev["headline"])

    def test_each_candidate_headline_is_owned_by_its_partition(self):
        row = _row(502, [
            _rec("Reuters World", "Oil steady in Asian trade", _ago(hours=9)),
            _rec("Bloomberg Markets", "OPEC extends output cut through December",
                 _ago(hours=2)),
        ], headline="Oil steady in Asian trade")
        payload = build_inbox([row], now=_NOW)
        for ev in payload["events"]:
            part = _partition_for(row, ev)
            self.assertIn(ev["headline"], {r["title"] for r in part})

    def test_surface_variants_of_one_identity_use_a_deterministic_tie_break(self):
        """Same normalized identity, different raw punctuation/case: the
        displayed variant is chosen deterministically and stably."""
        same = _ago(hours=2)
        row = _row(503, [
            _rec("Reuters World", "Alpha oil terminal halts loading!", same),
            _rec("Bloomberg Markets", "Alpha oil terminal halts loading", same),
        ], headline="Unowned oil headline from another cluster")
        first = _by_id(build_inbox([row], now=_NOW), 503)
        second = _by_id(build_inbox([row], now=_NOW), 503)
        self.assertEqual(first["headline"], second["headline"])
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(first["source_count"], 2)
        self.assertEqual(first["last_updated_at"], _iso(same))

    def test_parent_headline_stands_in_only_when_there_are_no_records(self):
        row = _row(504, [], headline="Oil market note with no owned records")
        ev = _by_id(build_inbox([row], now=_NOW), 504)
        self.assertEqual(ev["headline"], "Oil market note with no owned records")
        self.assertIsNone(ev["last_updated_at"])
        self.assertEqual(ev["availability_status"], "PARTIAL")
        self.assertTrue(any("no owned records" in u.lower()
                            for u in ev["known_unknowns"]))

    def test_tracked_producer_rows_keep_their_owned_representative_headlines(self):
        rows = _load_real_rows()
        payload = build_inbox(rows, now=datetime(2026, 7, 7, 12, 0, 0))
        by_cid = {r["id"]: r for r in rows}
        for ev in payload["events"]:
            owned = {(r.get("title") or "").strip()
                     for r in by_cid[ev["cluster_id"]]["records"]}
            self.assertIn(ev["headline"], owned)


# ---------------------------------------------------------------------------
# Missing / malformed publication timestamps stay explicit
# ---------------------------------------------------------------------------

class TestMissingTimestamps(unittest.TestCase):

    def test_malformed_timestamp_never_becomes_the_current_time(self):
        title = "Oil pipeline outage reported"
        row = _row(601, [
            _rec("Reuters World", title, "not-a-timestamp"),
            _rec("BBC Business", title, _ago(days=3)),
        ], latest=_iso(_ago(minutes=1)))
        ev = _by_id(build_inbox([row], now=_NOW), 601)
        self.assertEqual(ev["last_updated_at"], _iso(_ago(days=3)))
        self.assertEqual(ev["first_seen_at"], _iso(_ago(days=3)))
        self.assertNotEqual(ev["last_updated_at"], _iso(_NOW))

    def test_all_timestamps_missing_is_explicit_partial_and_still_visible(self):
        title = "Oil market briefing"
        row = _row(602, [
            _rec("Reuters World", title, ""),
            _rec("BBC Business", title, None),
        ], latest=_iso(_ago(minutes=1)))
        payload = build_inbox([row], now=_NOW)
        ev = _by_id(payload, 602)
        self.assertIsNone(ev["first_seen_at"])
        self.assertIsNone(ev["last_updated_at"])
        self.assertEqual(ev["availability_status"], "PARTIAL")
        self.assertIn("timestamp", (ev["missing_reason"] or "").lower())
        self.assertEqual(ev["lifecycle"], "WATCH")
        self.assertEqual(payload["counts"]["beyond_window"], 0)
        self.assertTrue(any("timestamps missing" in u.lower()
                            for u in ev["known_unknowns"]))


# ---------------------------------------------------------------------------
# Route-level regression — the full payload, through GET /news/inbox
# ---------------------------------------------------------------------------

def _seed_db(path: str, rows: list[dict]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS news_clusters ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " headline TEXT NOT NULL,"
        " payload_json TEXT NOT NULL,"
        " records_json TEXT NOT NULL DEFAULT '[]',"
        " latest_published_at TEXT,"
        " updated_at TEXT NOT NULL)")
    for r in rows:
        conn.execute(
            "INSERT INTO news_clusters "
            "(id, headline, payload_json, records_json, latest_published_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (r["id"], r["headline"], json.dumps(r["payload"]),
             json.dumps(r["records"]), r["latest_published_at"], r["updated_at"]))
    conn.commit()
    conn.close()


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _raise(name):
    def _inner(*a, **k):
        raise AssertionError(f"GET /news/inbox must never call {name}")
    return _inner


class TestInboxRouteTimeIdentity(unittest.TestCase):
    """Both proven defect shapes, end-to-end through the real route."""

    def setUp(self):
        self.rows = [
            _row(701,
                 [_rec("Fed Press Releases",
                       "Federal Reserve issues enforcement action on bank capital",
                       _ago(days=9))],
                 latest=_iso(_ago(hours=1))),
            _row(702,
                 [_rec("Reuters World",
                       "Oil prices jump after pipeline outage", _ago(hours=2))]),
            _row(703, [
                _rec("AFP World", "US tariff schedule published for review",
                     _ago(days=30)),
                _rec("AFP World", "US imposes new tariffs on 60 partners",
                     _ago(days=1)),
            ], headline="US tariff schedule published for review",
                latest=_iso(_ago(days=INBOX_WINDOW_DAYS + 26))),
        ]
        fd, self.db_path = tempfile.mkstemp(prefix="test_inbox_time_", suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        _seed_db(self.db_path, self.rows)
        self._patches = [
            patch.object(_db, "DB_FILE", self.db_path),
            patch.object(_api, "_fetch_fresh_news", _raise("_fetch_fresh_news")),
            patch("news_sources.fetch_all", _raise("news_sources.fetch_all")),
            patch.object(_db, "insert_news_cluster", _raise("insert_news_cluster")),
            patch.object(_db, "update_news_cluster", _raise("update_news_cluster")),
            patch.object(_db, "upsert_news_headline_assignments",
                         _raise("upsert_news_headline_assignments")),
            patch.object(_api, "save_news_cache", _raise("save_news_cache")),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(_api.app)
        self.pre_hash = _sha256(self.db_path)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _get(self) -> dict:
        with patch.object(event_inbox, "_now", return_value=_NOW):
            resp = self.client.get("/news/inbox")
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_route_payload_still_satisfies_the_contract(self):
        payload = self._get()
        self.assertEqual(payload["contract"], CONTRACT_VERSION)
        self.assertEqual(validate_inbox_payload(payload), [])

    def test_route_derives_every_stamp_from_owned_records(self):
        payload = self._get()
        by_cid = {r["id"]: r for r in self.rows}
        for ev in payload["events"]:
            part = _partition_for(by_cid[ev["cluster_id"]], ev)
            owned = [d for d in (event_inbox._parse_dt(r.get("published_at"))
                                 for r in part) if d is not None]
            self.assertEqual(ev["last_updated_at"], _iso(max(owned)))
            self.assertEqual(ev["first_seen_at"], _iso(min(owned)))

    def test_route_does_not_promote_the_stale_cluster_or_drop_the_fresh_one(self):
        payload = self._get()
        order = [ev["cluster_id"] for ev in payload["events"]]
        self.assertEqual(order, [702, 703, 701])
        # 703's older tariff-schedule record is a different identity and is
        # genuinely outside the window; its fresh sibling still surfaces.
        self.assertEqual(payload["counts"]["beyond_window"], 1)
        fresh = _by_id(payload, 703)
        self.assertEqual(fresh["headline"], "US imposes new tariffs on 60 partners")
        self.assertEqual(fresh["last_updated_at"], _iso(_ago(days=1)))

    def test_route_stays_write_free(self):
        self._get()
        self.assertEqual(_sha256(self.db_path), self.pre_hash,
                         "GET /news/inbox mutated the local database")

    def test_route_stays_provider_free(self):
        # Every provider / refresh seam is patched to raise in setUp; a clean
        # 200 with a valid payload is the proof.
        payload = self._get()
        self.assertEqual(payload["availability"], "AVAILABLE")

    def test_repeated_requests_over_unchanged_state_are_deterministic(self):
        self.assertEqual(self._get(), self._get())


if __name__ == "__main__":
    unittest.main()
