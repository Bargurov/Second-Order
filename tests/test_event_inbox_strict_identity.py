"""automatic-event-inbox-v2 — strict event-candidate identity (A0-R2B).

One stored semantic cluster is a *broad* grouping produced by TF-IDF union-find.
A0-R2 measured that it is not reliable enough to define one analyzable
real-world event: 9 named different-event control pairs collapsed into single
clusters.  The inbox therefore partitions each stored cluster's OWNED records
by the pipeline's existing exact normalized-headline primitive
(``news_sources._dedup_key``) and surfaces one candidate per partition.

The parent cluster is retained as provenance only (``cluster_id``); none of its
combined narrative may reach a candidate.  This is a conservative baseline, not
a claim that exact normalized headlines are the final identity model: exact
republications stay merged, cross-source paraphrases of one event may split, and
that split is disclosed rather than hidden.

No test here touches the network, a provider, or a database.
"""

import unittest
from datetime import datetime, timedelta

import event_inbox
from event_inbox import (
    CONTRACT_VERSION,
    build_inbox,
    validate_inbox_payload,
)
from news_sources import _dedup_key

_NOW = datetime(2026, 7, 25, 12, 0, 0)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _ago(**kw) -> datetime:
    return _NOW - timedelta(**kw)


def _rec(source: str, title: str, at) -> dict:
    published = _iso(at) if isinstance(at, datetime) else at
    return {"source": source, "title": title, "published_at": published, "url": ""}


def _row(cid: int, records: list[dict], *, headline: str | None = None,
         summary: str | None = None, actors: list[str] | None = None,
         agreement: str = "mixed") -> dict:
    """Producer-shaped row whose PARENT payload deliberately describes the union
    of every record, so any leak into a candidate is visible."""
    from news_fetch import source_tier
    head = headline if headline is not None else (records[0]["title"] if records else "")
    seen: set[str] = set()
    sources = []
    for r in records:
        if r["source"] in seen:
            continue
        seen.add(r["source"])
        sources.append({"name": r["source"], "tier": source_tier(r["source"]),
                        "url": ""})
    if summary is None:
        summary = " || ".join(f"{r['title']} (via {r['source']})" for r in records)
    if actors is None:
        actors = sorted({r["source"] for r in records})
    pubs = [r["published_at"] for r in records if r.get("published_at")]
    payload = {
        "headline": head,
        "summary": summary,
        "consensus": {"actors": actors, "action": "unknown", "geography": [],
                      "sector": "unknown", "uncertainty": "high",
                      "consensus": "mixed"},
        "sources": sources,
        "published_at": max(pubs) if pubs else "",
        "source_count": len(sources),
        "agreement": agreement,
        "evidence": [{"source": r["source"], "tier": "high", "title": r["title"],
                      "published_at": r["published_at"], "note": ""}
                     for r in records],
    }
    return {"id": cid, "headline": head, "payload": payload, "records": records,
            "latest_published_at": max(pubs) if pubs else "",
            "updated_at": _iso(_NOW)}


def _events(rows, now=_NOW):
    return build_inbox(rows, now=now)["events"]


# ---------------------------------------------------------------------------
# Partitioning
# ---------------------------------------------------------------------------

class TestStrictPartitioning(unittest.TestCase):

    def test_two_exact_identity_partitions_yield_two_candidates(self):
        rows = [_row(10, [
            _rec("Reuters World", "OPEC extends output cut through December",
                 _ago(hours=2)),
            _rec("Bloomberg Markets", "Copper smelter halts output in Chile",
                 _ago(hours=5)),
        ])]
        events = _events(rows)
        self.assertEqual(len(events), 2)
        self.assertEqual({e["cluster_id"] for e in events}, {10})
        self.assertEqual(
            {e["headline"] for e in events},
            {"OPEC extends output cut through December",
             "Copper smelter halts output in Chile"})

    def test_identical_titles_across_sources_stay_one_candidate(self):
        title = "BOJ likely to keep inflation warning, sources say"
        rows = [_row(11, [
            _rec("Reuters World", title, _ago(hours=3)),
            _rec("LatAm Economy", title, _ago(hours=3)),
            _rec("Yahoo Finance", title, _ago(hours=4)),
        ])]
        events = _events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source_count"], 3)

    def test_source_count_equals_unique_sources_in_the_partition(self):
        shared = "Canada marks Gordie Howe bridge opening after trade war deepens"
        rows = [_row(12, [
            _rec("Reuters World", shared, _ago(hours=2)),
            _rec("Al Jazeera Economy", shared, _ago(hours=3)),
            _rec("Reuters World", "Oil steady in Asian trade", _ago(hours=6)),
        ])]
        by_head = {e["headline"]: e for e in _events(rows)}
        self.assertEqual(by_head[shared]["source_count"], 2)
        self.assertEqual(by_head["Oil steady in Asian trade"]["source_count"], 1)

    def test_parent_cluster_is_retained_only_as_provenance(self):
        rows = [_row(13, [
            _rec("Reuters World", "OPEC extends output cut through December",
                 _ago(hours=2)),
            _rec("Bloomberg Markets", "Copper smelter halts output in Chile",
                 _ago(hours=5)),
        ])]
        for ev in _events(rows):
            self.assertEqual(ev["cluster_id"], 13)


# ---------------------------------------------------------------------------
# No content crosses a partition boundary
# ---------------------------------------------------------------------------

class TestNoCrossPartitionLeak(unittest.TestCase):

    def setUp(self):
        self.rows = [_row(20, [
            _rec("Reuters World", "OPEC extends output cut through December",
                 _ago(hours=2)),
            _rec("Semiconductor Trade",
                 "Semiconductor export controls tightened for Dutch supplier",
                 _ago(hours=5)),
        ])]
        self.events = {e["headline"]: e for e in _events(self.rows)}
        self.opec = self.events["OPEC extends output cut through December"]
        self.chips = self.events[
            "Semiconductor export controls tightened for Dutch supplier"]

    def test_no_foreign_source_crosses(self):
        self.assertEqual({s["name"] for s in self.opec["sources"]},
                         {"Reuters World"})
        self.assertEqual({s["name"] for s in self.chips["sources"]},
                         {"Semiconductor Trade"})

    def test_no_foreign_summary_text_crosses(self):
        self.assertNotIn("Semiconductor", self.opec["event_summary"] or "")
        self.assertNotIn("OPEC", self.chips["event_summary"] or "")

    def test_no_foreign_actor_crosses(self):
        for ev in (self.opec, self.chips):
            ctx = ev["analysis_target"]["context"]
            self.assertNotIn("Semiconductor Trade", ctx) if ev is self.opec \
                else self.assertNotIn("Reuters World", ctx)

    def test_no_foreign_channel_crosses(self):
        self.assertIn("ENERGY_COMMODITIES", self.opec["material_channels"])
        self.assertNotIn("TECHNOLOGY_PRODUCTIVITY", self.opec["material_channels"])
        self.assertIn("TECHNOLOGY_PRODUCTIVITY", self.chips["material_channels"])
        self.assertNotIn("ENERGY_COMMODITIES", self.chips["material_channels"])

    def test_analysis_target_contains_only_its_own_partition(self):
        self.assertEqual(self.opec["analysis_target"]["headline"],
                         "OPEC extends output cut through December")
        self.assertNotIn("Semiconductor", self.opec["analysis_target"]["context"])
        self.assertEqual(
            self.chips["analysis_target"]["headline"],
            "Semiconductor export controls tightened for Dutch supplier")
        self.assertNotIn("OPEC", self.chips["analysis_target"]["context"])

    def test_each_candidate_owns_its_timestamps(self):
        self.assertEqual(self.opec["last_updated_at"], _iso(_ago(hours=2)))
        self.assertEqual(self.opec["first_seen_at"], _iso(_ago(hours=2)))
        self.assertEqual(self.chips["last_updated_at"], _iso(_ago(hours=5)))
        self.assertEqual(self.chips["first_seen_at"], _iso(_ago(hours=5)))


# ---------------------------------------------------------------------------
# Candidate identity
# ---------------------------------------------------------------------------

class TestCandidateIdentity(unittest.TestCase):

    def _rows(self):
        return [_row(30, [
            _rec("Reuters World", "OPEC extends output cut through December",
                 _ago(hours=2)),
            _rec("Bloomberg Markets", "Copper smelter halts output in Chile",
                 _ago(hours=5)),
        ])]

    def test_ids_are_distinct_within_one_parent(self):
        ids = [e["event_id"] for e in _events(self._rows())]
        self.assertEqual(len(ids), len(set(ids)))

    def test_ids_carry_the_parent_and_are_deterministic(self):
        first = [e["event_id"] for e in _events(self._rows())]
        second = [e["event_id"] for e in _events(self._rows())]
        self.assertEqual(first, second)
        for eid in first:
            self.assertTrue(eid.startswith("aei-30-"), eid)

    def test_ids_do_not_expose_raw_headline_text(self):
        for ev in _events(self._rows()):
            self.assertNotIn("opec", ev["event_id"].lower())
            self.assertNotIn("copper", ev["event_id"].lower())

    def test_id_is_stable_for_the_same_identity_key(self):
        rows = self._rows()
        target = "OPEC extends output cut through December"
        first = next(e for e in _events(rows) if e["headline"] == target)
        # Same identity, different parent record ordering and an extra source.
        shuffled = [_row(30, list(reversed(rows[0]["records"])) + [
            _rec("Al Jazeera Economy", target, _ago(hours=4))])]
        second = next(e for e in _events(shuffled) if e["headline"] == target)
        self.assertEqual(first["event_id"], second["event_id"])

    def test_ordering_is_deterministic_and_newest_first(self):
        rows = self._rows()
        stamps = [(e["last_updated_at"], e["cluster_id"], e["event_id"])
                  for e in _events(rows)]
        self.assertEqual(stamps, sorted(stamps, reverse=True))


# ---------------------------------------------------------------------------
# Named controls
# ---------------------------------------------------------------------------

NEGATIVE_CONTROLS = [
    ("separate Fed releases",
     "Federal Reserve Board issues enforcement action with Heritage State Bank",
     "Federal Reserve Board issues enforcement action with TS Banking Group"),
    ("Fed enforcement vs stress test",
     "Federal Reserve Board issues enforcement action with Small Business Bank",
     "Federal Reserve Board annual bank stress test confirms large banks are "
     "well positioned"),
    ("freight rise vs fall",
     "Freight Rates Rally on Early Peak Season Demand",
     "Container Spot Rates Fall as Capacity Growth Pressures Freight Rates"),
    ("AFP trade items spanning years",
     "Trump hails fantastic trade deals with Xi as China issues a tariff warning",
     "US imposes new tariffs on 60 partners as Trump rebuilds trade agenda"),
    ("USDA Texas vs Missouri",
     "USDA Offers Disaster Assistance to Texas Grain Producers After Flooding",
     "USDA Offers Disaster Assistance to Missouri Grain Producers After Flooding"),
    ("USTR 2026 vs 2025",
     "USTR Releases 2026 National Trade Estimate and Tariff Report",
     "USTR Releases 2025 National Trade Estimate and Tariff Report"),
    ("coal estimate vs coal terminal",
     "US estimates federal coal could power nation for 600 years",
     "An embattled coal terminal could be a lifeline for US coal"),
    ("oil futures vs Iranian crude flows",
     "OIL FUTURES: Prices open higher following Iranian and US attacks",
     "Iranian crude flows to Singapore up sharply on brief US sanctions relief"),
    ("same template, different action",
     "Federal Reserve Board issues enforcement action with employee of Bank of "
     "Eufaula",
     "Federal Reserve Board announces termination of enforcement action with "
     "Jiko Group"),
]


class TestNamedControls(unittest.TestCase):

    def test_every_negative_control_stays_two_candidates(self):
        for i, (name, a, b) in enumerate(NEGATIVE_CONTROLS):
            with self.subTest(control=name):
                rows = [_row(40 + i, [
                    _rec("Fed Press Releases", a, _ago(hours=3)),
                    _rec("Fed Press Releases", b, _ago(hours=6)),
                ])]
                events = _events(rows)
                self.assertEqual(len(events), 2, f"{name} collapsed")
                self.assertNotEqual(events[0]["event_id"], events[1]["event_id"])
                self.assertEqual({e["headline"] for e in events}, {a, b})

    def test_exact_republication_positive_controls_stay_one_candidate(self):
        for i, title in enumerate((
                "BOJ likely to keep inflation warning, sources say",
                "Canada marks Gordie Howe bridge opening after trade war deepens")):
            with self.subTest(title=title):
                rows = [_row(60 + i, [
                    _rec("Reuters World", title, _ago(hours=2)),
                    _rec("Al Jazeera Economy", title, _ago(hours=3)),
                ])]
                events = _events(rows)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["source_count"], 2)

    def test_paraphrase_positives_split_and_are_disclosed_not_forced(self):
        """Known cost of the conservative rule — visible, never silently merged."""
        a = "US unveils new tariffs on 60 partners as Trump rebuilds trade agenda"
        b = "US imposes new tariffs on 60 partners as Trump rebuilds trade agenda"
        self.assertNotEqual(_dedup_key(a), _dedup_key(b))
        rows = [_row(70, [_rec("AFP World", a, _ago(hours=6)),
                          _rec("AFP World", b, _ago(hours=2))])]
        payload = build_inbox(rows, now=_NOW)
        self.assertEqual(len(payload["events"]), 2)
        self.assertTrue(
            any("paraphrase" in lim.lower() or "separate candidates" in lim.lower()
                for lim in payload["limitations"]),
            "conservative splitting must be disclosed in limitations")


# ---------------------------------------------------------------------------
# v2 counts contract
# ---------------------------------------------------------------------------

class TestV2Counts(unittest.TestCase):

    def test_contract_version_is_v2(self):
        self.assertEqual(CONTRACT_VERSION, "automatic-event-inbox-v3")
        self.assertEqual(build_inbox([], now=_NOW)["contract"],
                         "automatic-event-inbox-v3")

    def test_counts_field_set_is_exact_and_has_no_ambiguous_alias(self):
        counts = build_inbox([], now=_NOW)["counts"]
        self.assertEqual(set(counts.keys()), {
            "parent_clusters_total", "partitioned_parent_clusters",
            "malformed_parent_clusters", "candidates_total", "surfaced",
            "beyond_window", "excluded_no_material_channel",
            "malformed_candidates", "by_lifecycle"})
        self.assertNotIn("clusters_total", counts)
        self.assertNotIn("malformed_rows", counts)

    def test_parent_level_reconciliation(self):
        rows = [
            _row(80, [_rec("Reuters World", "OPEC extends output cut", _ago(hours=2))]),
            {"id": 81, "headline": "", "payload": {}, "records": [],
             "latest_published_at": "", "updated_at": ""},
        ]
        counts = build_inbox(rows, now=_NOW)["counts"]
        self.assertEqual(counts["parent_clusters_total"], 2)
        self.assertEqual(counts["malformed_parent_clusters"], 1)
        self.assertEqual(counts["partitioned_parent_clusters"], 1)
        self.assertEqual(counts["parent_clusters_total"],
                         counts["partitioned_parent_clusters"]
                         + counts["malformed_parent_clusters"])

    def test_candidate_level_reconciliation(self):
        rows = [_row(82, [
            _rec("Reuters World", "OPEC extends output cut", _ago(hours=2)),
            _rec("BBC Business", "Local council debates library opening hours",
                 _ago(hours=4)),                       # no material channel
            _rec("FT World", "Copper output slips at Chilean mine",
                 _ago(days=30)),                       # beyond window
        ])]
        counts = build_inbox(rows, now=_NOW)["counts"]
        self.assertEqual(counts["candidates_total"], 3)
        self.assertEqual(counts["surfaced"], 1)
        self.assertEqual(counts["beyond_window"], 1)
        self.assertEqual(counts["excluded_no_material_channel"], 1)
        self.assertEqual(
            counts["candidates_total"],
            counts["surfaced"] + counts["beyond_window"]
            + counts["excluded_no_material_channel"]
            + counts["malformed_candidates"])

    def test_malformed_parent_and_malformed_candidate_are_separate(self):
        rows = [
            {"id": 90, "headline": "", "payload": {}, "records": [],
             "latest_published_at": "", "updated_at": ""},          # bad parent
            _row(91, [_rec("Reuters World", "   ", _ago(hours=2)),   # bad candidate
                      _rec("BBC Business", "OPEC extends output cut", _ago(hours=3))],
                 headline="OPEC extends output cut"),
        ]
        counts = build_inbox(rows, now=_NOW)["counts"]
        self.assertEqual(counts["malformed_parent_clusters"], 1)
        self.assertEqual(counts["malformed_candidates"], 1)

    def test_lifecycle_sums_to_surfaced(self):
        rows = [_row(92, [
            _rec("Reuters World", "OPEC extends output cut", _ago(hours=2)),
            _rec("BBC Business", "Copper smelter halts output in Chile",
                 _ago(hours=5)),
        ])]
        counts = build_inbox(rows, now=_NOW)["counts"]
        self.assertEqual(sum(counts["by_lifecycle"].values()), counts["surfaced"])

    def test_validator_accepts_the_real_payload(self):
        rows = [_row(93, [
            _rec("Reuters World", "OPEC extends output cut", _ago(hours=2)),
            _rec("BBC Business", "Copper smelter halts output in Chile",
                 _ago(hours=5)),
        ])]
        self.assertEqual(validate_inbox_payload(build_inbox(rows, now=_NOW)), [])

    def test_validator_rejects_a_broken_candidate_reconciliation(self):
        rows = [_row(94, [_rec("Reuters World", "OPEC extends output cut",
                               _ago(hours=2))])]
        payload = build_inbox(rows, now=_NOW)
        payload["counts"]["candidates_total"] += 1
        self.assertTrue(validate_inbox_payload(payload))

    def test_validator_rejects_a_broken_parent_reconciliation(self):
        rows = [_row(95, [_rec("Reuters World", "OPEC extends output cut",
                               _ago(hours=2))])]
        payload = build_inbox(rows, now=_NOW)
        payload["counts"]["parent_clusters_total"] += 1
        self.assertTrue(validate_inbox_payload(payload))


if __name__ == "__main__":
    unittest.main()
