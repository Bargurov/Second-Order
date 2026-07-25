"""automatic-event-inbox-v2 — pure derivation contract tests.

Since A0-R2B one stored cluster is partitioned by exact normalized-headline
identity and each partition becomes one candidate, so a single stored row may
yield several events.  Cross-source reports of ONE normalized headline still
dedupe; differently-worded reports of the same story split conservatively and
that split is disclosed in ``limitations``.

Three input layers stay distinct (project testing rule):

* ``tests/fixtures/event_inbox_cluster_rows.json`` — tracked durable evidence:
  six REAL news_clusters rows captured read-only from the local store
  (2026-07-24).  Used to prove the contract holds on producer-shaped data and
  that oil and non-oil categories share one contract.
* ``_row(...)`` helpers below — minimal logic fixtures with timestamps derived
  from one fixed anchor clock.  They prove lifecycle / gate mechanics only and
  are never presented as the historical record.

``build_inbox`` is pure: rows + injected ``now`` in, payload out.  No test in
this module touches a database, the network, or a provider.
"""

import json
import os
import unittest
from datetime import datetime, timedelta

import event_inbox
from event_inbox import (
    CONTRACT_VERSION,
    DEVELOPING_WAVE_GAP_HOURS,
    INBOX_WINDOW_DAYS,
    LIFECYCLE_STATES,
    MATERIAL_CHANNELS,
    RESOLVED_AFTER_HOURS,
    build_inbox,
    derive_channels,
    validate_inbox_payload,
)

_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "event_inbox_cluster_rows.json")

# One anchor clock for every synthetic timestamp in this module.  All
# age-sensitive offsets are derived from it (never datetime.now()).
_ANCHOR = datetime(2026, 7, 7, 12, 0, 0)

_TOP_LEVEL_FIELDS = {
    "contract", "generated_from", "as_of", "availability",
    "events", "counts", "limitations", "non_claim",
}

_EVENT_FIELDS = {
    "event_id", "cluster_id", "headline", "event_summary",
    "first_seen_at", "last_updated_at", "lifecycle",
    "source_count", "sources", "official_source_present",
    "event_family", "event_type", "material_channels",
    "why_surfaced", "known_unknowns", "analysis_target",
    "availability_status", "missing_reason",
}


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _rec(source: str, title: str, at: datetime) -> dict:
    return {"source": source, "title": title, "published_at": _iso(at), "url": ""}


def _row(cid: int, records: list[dict], *, headline: str | None = None,
         summary: str = "", agreement: str = "consistent",
         uncertainty: str = "medium", latest: str | None = None) -> dict:
    """Producer-shaped news_clusters row (load_news_clusters dict shape)."""
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
        "updated_at": _iso(_ANCHOR),
    }


def _load_real_rows() -> list[dict]:
    with open(_FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)["rows"]


class TestContractShape(unittest.TestCase):
    def test_contract_version_and_exact_top_level_fields(self):
        payload = build_inbox([], now=_ANCHOR)
        self.assertEqual(payload["contract"], "automatic-event-inbox-v2")
        self.assertEqual(CONTRACT_VERSION, "automatic-event-inbox-v2")
        self.assertEqual(set(payload.keys()), _TOP_LEVEL_FIELDS)

    def test_valid_empty_state_is_honest_not_unavailable(self):
        payload = build_inbox([], now=_ANCHOR)
        self.assertEqual(payload["availability"], "AVAILABLE")
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["counts"]["parent_clusters_total"], 0)
        self.assertEqual(payload["counts"]["candidates_total"], 0)
        self.assertEqual(payload["counts"]["surfaced"], 0)
        # The absence disclosure is permanent, not conditional on content.
        self.assertTrue(any("Absence from the inbox" in l
                            for l in payload["limitations"]))
        self.assertIn("not a prediction", payload["non_claim"])

    def test_event_field_set_is_exact_and_carries_no_bodies(self):
        # One identity reported by two sources -> one candidate.
        title = "Fed raises interest rates"
        rows = [_row(1, [_rec("Reuters World", title, _ANCHOR - timedelta(hours=2)),
                         _rec("BBC World", title, _ANCHOR - timedelta(hours=1))])]
        payload = build_inbox(rows, now=_ANCHOR)
        self.assertEqual(len(payload["events"]), 1)
        ev = payload["events"][0]
        self.assertEqual(set(ev.keys()), _EVENT_FIELDS)
        # No article-body or raw-record duplication in the contract.
        self.assertNotIn("evidence", ev)
        self.assertNotIn("records", ev)


class TestDeduplication(unittest.TestCase):
    def test_one_identity_across_sources_is_one_event(self):
        """Cross-source corroboration of ONE normalized headline dedupes."""
        title = "OPEC announces oil output cut"
        rows = [_row(7, [
            _rec("Reuters World", title, _ANCHOR - timedelta(hours=3)),
            _rec("BBC World", title, _ANCHOR - timedelta(hours=3)),
            _rec("FT World", title, _ANCHOR - timedelta(hours=2)),
        ])]
        payload = build_inbox(rows, now=_ANCHOR)
        self.assertEqual(len(payload["events"]), 1)
        ev = payload["events"][0]
        self.assertEqual(ev["cluster_id"], 7)
        self.assertTrue(ev["event_id"].startswith("aei-7-"))
        self.assertEqual(ev["source_count"], 3)
        names = [s["name"] for s in ev["sources"]]
        self.assertEqual(sorted(names), ["BBC World", "FT World", "Reuters World"])

    def test_differently_worded_reports_split_conservatively(self):
        """The disclosed cost of strict identity: paraphrases of one story
        become separate candidates rather than one merged event."""
        rows = [_row(8, [
            _rec("Reuters World", "OPEC announces oil output cut", _ANCHOR - timedelta(hours=3)),
            _rec("BBC World", "OPEC agrees to cut oil production", _ANCHOR - timedelta(hours=2)),
        ])]
        payload = build_inbox(rows, now=_ANCHOR)
        self.assertEqual(len(payload["events"]), 2)
        self.assertTrue(any("separate candidates" in l.lower()
                            for l in payload["limitations"]))


class TestLifecycle(unittest.TestCase):
    def test_lifecycle_values_are_workflow_only_enum(self):
        self.assertEqual(LIFECYCLE_STATES, ("NEW", "DEVELOPING", "WATCH", "RESOLVED"))
        rows = _load_real_rows()
        payload = build_inbox(rows, now=datetime(2026, 7, 7, 12, 0, 0))
        for ev in payload["events"]:
            self.assertIn(ev["lifecycle"], LIFECYCLE_STATES)

    def test_recent_multi_source_cluster_is_new(self):
        title = "ECB cuts interest rates"
        rows = [_row(1, [
            _rec("Reuters World", title, _ANCHOR - timedelta(hours=2)),
            _rec("BBC World", title, _ANCHOR - timedelta(hours=1, minutes=30)),
        ])]
        payload = build_inbox(rows, now=_ANCHOR)
        self.assertEqual(payload["events"][0]["lifecycle"], "NEW")

    def test_repeated_article_without_new_fact_is_not_developing(self):
        # Second source republishes the SAME normalized title 10h later:
        # article count grows, information does not -> stays NEW.
        rows = [_row(2, [
            _rec("Reuters World", "ECB cuts interest rates", _ANCHOR - timedelta(hours=12)),
            _rec("BBC World", "ECB cuts interest rates", _ANCHOR - timedelta(hours=2)),
        ])]
        payload = build_inbox(rows, now=_ANCHOR)
        self.assertEqual(payload["events"][0]["lifecycle"], "NEW")

    def test_same_wave_rewording_is_a_separate_candidate_not_a_development(self):
        # A differently-worded report is a different normalized identity, so
        # under strict partitioning it is its own candidate — a rewording can
        # never be recorded as a development of another candidate.
        rows = [_row(3, [
            _rec("Reuters World", "ECB cuts interest rates", _ANCHOR - timedelta(hours=3)),
            _rec("BBC World", "European Central Bank lowers rates by 25 basis points",
                 _ANCHOR - timedelta(hours=2)),
        ])]
        payload = build_inbox(rows, now=_ANCHOR)
        self.assertEqual(len(payload["events"]), 2)
        for ev in payload["events"]:
            self.assertNotEqual(ev["lifecycle"], "DEVELOPING")

    def test_late_official_update_is_its_own_candidate(self):
        """Structural consequence of strict identity: a later, differently
        worded official update is a SEPARATE candidate, so it cannot promote
        another candidate to DEVELOPING.  Recorded, not hidden."""
        rows = [_row(4, [
            _rec("Reuters World", "Fed expected to hold interest rates steady",
                 _ANCHOR - timedelta(hours=20)),
            _rec("Fed Press Releases",
                 "Federal Reserve issues FOMC statement on interest rates",
                 _ANCHOR - timedelta(hours=2)),
        ])]
        payload = build_inbox(rows, now=_ANCHOR)
        self.assertEqual(len(payload["events"]), 2)
        official = [ev for ev in payload["events"] if ev["official_source_present"]]
        self.assertEqual(len(official), 1)
        self.assertIn("FOMC statement", official[0]["headline"])

    def test_developing_is_structurally_unreachable_under_strict_identity(self):
        """DEVELOPING needs a later record with a DIFFERENT normalized title;
        inside one identity partition every record shares that title, so the
        state stays in the vocabulary but cannot currently arise.  Re-linking
        related candidates is deferred process/theme work."""
        rows = _load_real_rows()
        payload = build_inbox(rows, now=datetime(2026, 7, 7, 12, 0, 0))
        self.assertIn("DEVELOPING", LIFECYCLE_STATES)
        self.assertEqual(payload["counts"]["by_lifecycle"]["DEVELOPING"], 0)

    def test_single_nonofficial_source_is_watch_with_visible_reason(self):
        rows = [_row(5, [
            _rec("OilPrice.com", "Oil pipeline outage may cut crude exports",
                 _ANCHOR - timedelta(hours=2)),
        ])]
        payload = build_inbox(rows, now=_ANCHOR)
        ev = payload["events"][0]
        self.assertEqual(ev["lifecycle"], "WATCH")
        self.assertTrue(any("single source" in u.lower() for u in ev["known_unknowns"]))

    def test_parent_mixed_agreement_does_not_leak_into_a_candidate(self):
        """Conflicting reports are different identities, so they become
        different candidates and the PARENT's 'mixed' agreement label — which
        described the union — must not be attached to either of them."""
        rows = [_row(6, [
            _rec("Reuters World", "Oil output cut announced by OPEC", _ANCHOR - timedelta(hours=2)),
            _rec("BBC World", "OPEC oil supply increase under discussion", _ANCHOR - timedelta(hours=1)),
        ], agreement="mixed")]
        payload = build_inbox(rows, now=_ANCHOR)
        self.assertEqual(len(payload["events"]), 2)
        for ev in payload["events"]:
            self.assertEqual(ev["lifecycle"], "WATCH")
            self.assertTrue(any("single source" in u.lower()
                                for u in ev["known_unknowns"]))
            self.assertFalse(any("conflict" in u.lower()
                                 for u in ev["known_unknowns"]))

    def test_cluster_quiet_past_archive_window_is_resolved(self):
        title = "Fed raises interest rates"
        rows = [_row(8, [
            _rec("Reuters World", title,
                 _ANCHOR - timedelta(hours=RESOLVED_AFTER_HOURS + 6)),
            _rec("BBC World", title,
                 _ANCHOR - timedelta(hours=RESOLVED_AFTER_HOURS + 1)),
        ])]
        payload = build_inbox(rows, now=_ANCHOR)
        self.assertEqual(payload["events"][0]["lifecycle"], "RESOLVED")


class TestMaterialityGate(unittest.TestCase):
    def test_material_channel_required_for_inclusion(self):
        rows = [_row(9, [
            _rec("Reuters World", "Celebrity gala photographs draw large crowds",
                 _ANCHOR - timedelta(hours=2)),
            _rec("BBC World", "Gala evening celebrates local artists",
                 _ANCHOR - timedelta(hours=1)),
        ])]
        payload = build_inbox(rows, now=_ANCHOR)
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["counts"]["parent_clusters_total"], 1)
        self.assertEqual(payload["counts"]["candidates_total"], 2)
        self.assertEqual(payload["counts"]["excluded_no_material_channel"], 2)

    def test_every_surfaced_event_has_channel_and_reason(self):
        payload = build_inbox(_load_real_rows(), now=datetime(2026, 7, 7, 12, 0, 0))
        self.assertGreater(len(payload["events"]), 0)
        for ev in payload["events"]:
            self.assertGreaterEqual(len(ev["material_channels"]), 1)
            self.assertGreaterEqual(len(ev["why_surfaced"]), 1)
            for ch in ev["material_channels"]:
                self.assertIn(ch, MATERIAL_CHANNELS)

    def test_multiple_material_channels_preserved(self):
        channels = derive_channels("Fed rate hike lifts dollar to two-year high")
        self.assertIn("RATES", channels)
        self.assertIn("CURRENCY", channels)

    def test_unknown_channel_rejected_by_validator(self):
        payload = build_inbox([_row(1, [
            _rec("Reuters World", "Fed raises interest rates", _ANCHOR - timedelta(hours=2)),
            _rec("BBC World", "Federal Reserve lifts policy rate", _ANCHOR - timedelta(hours=1)),
        ])], now=_ANCHOR)
        payload["events"][0]["material_channels"] = ["VIBES"]
        problems = validate_inbox_payload(payload)
        self.assertTrue(any("channel" in p.lower() for p in problems))

    def test_derived_channels_always_within_enum(self):
        for text in ("oil sanctions on tariff war and rate cuts",
                     "semiconductor export controls hit supply chain",
                     "completely unrelated gardening text"):
            for ch in derive_channels(text):
                self.assertIn(ch, MATERIAL_CHANNELS)

    def test_official_source_reason_surfaced(self):
        title = "Federal Reserve issues FOMC statement on interest rates"
        rows = [_row(10, [
            _rec("Fed Press Releases", title, _ANCHOR - timedelta(hours=2)),
            _rec("Reuters World", title, _ANCHOR - timedelta(hours=1)),
        ])]
        ev = build_inbox(rows, now=_ANCHOR)["events"][0]
        self.assertTrue(ev["official_source_present"])
        self.assertTrue(any("official" in w.lower() for w in ev["why_surfaced"]))

    def test_source_diversity_reason_surfaced(self):
        title = "OPEC announces oil output cut"
        rows = [_row(11, [
            _rec("Reuters World", title, _ANCHOR - timedelta(hours=3)),
            _rec("BBC World", title, _ANCHOR - timedelta(hours=3)),
            _rec("FT World", title, _ANCHOR - timedelta(hours=2)),
        ])]
        ev = build_inbox(rows, now=_ANCHOR)["events"][0]
        self.assertTrue(any("3 independent sources" in w for w in ev["why_surfaced"]))


class TestNoScoresNoDirection(unittest.TestCase):
    _BANNED_FIELD_TOKENS = (
        "score", "priority", "urgency", "conviction", "importance",
        "impact", "direction", "buy", "sell", "long", "short",
        "trade_", "tradeab", "signal",
    )
    _BANNED_TEXT_TOKENS = (
        "buy", "sell", "bullish", "bearish", "upside", "downside",
        "outperform", "underperform", "tradeable", "tradeable",
    )

    def _walk_keys(self, node, out):
        if isinstance(node, dict):
            for k, v in node.items():
                out.append(k)
                self._walk_keys(v, out)
        elif isinstance(node, list):
            for v in node:
                self._walk_keys(v, out)

    def test_no_opaque_score_or_directional_field(self):
        payload = build_inbox(_load_real_rows(), now=datetime(2026, 7, 7, 12, 0, 0))
        keys: list[str] = []
        self._walk_keys(payload, keys)
        for key in keys:
            for token in self._BANNED_FIELD_TOKENS:
                self.assertNotIn(token, key.lower(),
                                 f"field {key!r} looks like a score/trade field")

    def test_inbox_authored_text_carries_no_directional_language(self):
        # Applies to text WE author (reasons, unknowns, limitations,
        # non-claim) — never to quoted source headlines/summaries.
        payload = build_inbox(_load_real_rows(), now=datetime(2026, 7, 7, 12, 0, 0))
        authored: list[str] = [payload["non_claim"], *payload["limitations"]]
        for ev in payload["events"]:
            authored.extend(ev["why_surfaced"])
            authored.extend(ev["known_unknowns"])
        import re
        for text in authored:
            for token in self._BANNED_TEXT_TOKENS:
                self.assertIsNone(re.search(rf"\b{token}\b", text.lower()),
                                  f"authored text {text!r} contains {token!r}")


class TestMissingnessAndFamilies(unittest.TestCase):
    def test_missing_timestamps_stay_visible_as_partial_watch(self):
        recs = [{"source": "Reuters World", "title": "Fed raises interest rates",
                 "published_at": "", "url": ""},
                {"source": "BBC World", "title": "Federal Reserve lifts policy rate",
                 "published_at": "", "url": ""}]
        rows = [_row(12, recs, latest="")]
        ev = build_inbox(rows, now=_ANCHOR)["events"][0]
        self.assertIsNone(ev["first_seen_at"])
        self.assertEqual(ev["availability_status"], "PARTIAL")
        self.assertIsNotNone(ev["missing_reason"])
        self.assertIn("timestamp", ev["missing_reason"].lower())
        self.assertEqual(ev["lifecycle"], "WATCH")

    def test_unmapped_event_family_is_visible_not_hidden(self):
        rows = [_row(13, [
            _rec("Reuters World", "Government budget deficit widens sharply",
                 _ANCHOR - timedelta(hours=2)),
            _rec("BBC World", "Budget deficit grows on higher government spending",
                 _ANCHOR - timedelta(hours=1)),
        ])]
        ev = build_inbox(rows, now=_ANCHOR)["events"][0]
        if ev["event_family"] is None:
            self.assertTrue(any("family" in u.lower() for u in ev["known_unknowns"]))

    def test_availability_status_enum(self):
        payload = build_inbox(_load_real_rows(), now=datetime(2026, 7, 7, 12, 0, 0))
        for ev in payload["events"]:
            self.assertIn(ev["availability_status"], ("AVAILABLE", "PARTIAL"))


class TestOrderingAndDeterminism(unittest.TestCase):
    def test_deterministic_output_and_publication_order(self):
        rows = _load_real_rows()
        now = datetime(2026, 7, 7, 12, 0, 0)
        a = build_inbox(rows, now=now)
        b = build_inbox(list(reversed(rows)), now=now)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        stamps = [(ev["last_updated_at"] or "", ev["cluster_id"]) for ev in a["events"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_beyond_window_candidates_excluded_but_counted(self):
        old = _ANCHOR - timedelta(days=INBOX_WINDOW_DAYS, hours=6)
        title = "Fed raises interest rates"
        rows = [_row(14, [
            _rec("Reuters World", title, old),
            _rec("BBC World", title, old),
        ])]
        payload = build_inbox(rows, now=_ANCHOR)
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["counts"]["beyond_window"], 1)
        self.assertEqual(payload["counts"]["candidates_total"], 1)


class TestUniversalContract(unittest.TestCase):
    def test_oil_and_non_oil_categories_share_one_contract(self):
        rows = _load_real_rows()
        payload = build_inbox(rows, now=datetime(2026, 7, 7, 12, 0, 0))
        # One parent can now yield several candidates, so collect the channels
        # each parent contributed across all of its candidates.
        by_parent: dict[int, set] = {}
        for ev in payload["events"]:
            by_parent.setdefault(ev["cluster_id"], set()).update(
                ev["material_channels"])
        # Real captured rows: energy (13504), geopolitics (13036),
        # technology (13451), official Fed (12494), sanctions/tech (13060).
        self.assertIn(13504, by_parent)
        self.assertIn(13451, by_parent)
        self.assertIn("ENERGY_COMMODITIES", by_parent[13504])
        self.assertIn("TECHNOLOGY_PRODUCTIVITY", by_parent[13451])
        if 13036 in by_parent:
            self.assertIn("GEOPOLITICAL_RISK", by_parent[13036])
        field_sets = {frozenset(ev.keys()) for ev in payload["events"]}
        self.assertEqual(len(field_sets), 1)

    def test_validator_accepts_real_payload(self):
        payload = build_inbox(_load_real_rows(), now=datetime(2026, 7, 7, 12, 0, 0))
        self.assertEqual(validate_inbox_payload(payload), [])

    def test_analysis_target_reuses_existing_analyze_boundary(self):
        title = "OPEC announces oil output cut"
        rows = [_row(15, [
            _rec("Reuters World", title, _ANCHOR - timedelta(hours=3)),
            _rec("BBC World", title, _ANCHOR - timedelta(hours=2)),
        ], summary="Multiple outlets report an OPEC output cut.")]
        ev = build_inbox(rows, now=_ANCHOR)["events"][0]
        target = ev["analysis_target"]
        self.assertEqual(set(target.keys()), {"headline", "context"})
        self.assertEqual(target["headline"], ev["headline"])
        self.assertIn("Sources (2)", target["context"])
        self.assertIn("Summary:", target["context"])


class TestFrozenThresholdsDocumented(unittest.TestCase):
    def test_thresholds_match_frozen_empirical_basis(self):
        # RESOLVED reuses the cluster store's calibrated 48h archive window;
        # the 6h wave gap and 14d payload window are documented in event_inbox.
        import news_cluster_store
        self.assertEqual(RESOLVED_AFTER_HOURS, news_cluster_store._RECENCY_HOURS)
        self.assertEqual(DEVELOPING_WAVE_GAP_HOURS, 6.0)
        self.assertEqual(INBOX_WINDOW_DAYS, 14)
        self.assertIn("p25", event_inbox.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
