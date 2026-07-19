"""U0 — Universal Event Dossier contract (event-dossier-index-v1 /
event-dossier-v1).

One deterministic, read-only, tracked-publication-backed capability over
the complete published historical research universe: 97 events (65 FOMC +
32 OPEC), every one individually addressable, none selected, ranked, or
curated.  The assembler joins the Mission I v2 event-level surface
(anchor sessions, per-event observations, denominators) to the G1A / G1B
identity-and-source ledgers and the Mission G / I / J aggregate builders;
the six G6C published per-event dossiers are an enrichment tier
discovered from the publication, never a product universe.

Contract floors pinned here:
  - exact identity joins (slug), event date and anchor session separate;
  - 97 / 65+32 / 904 / 520+384 accounting;
  - explicit section states (never bare null), visible missingness;
  - aggregate labels remain aggregate context (context_scope=aggregate),
    never an individual-event verdict;
  - FOMC 20d ordinary comparison structurally unavailable; Mission J
    not applicable for OPEC (mission_j_fomc_only);
  - contradiction fails closed (CONTRADICTORY, no silent repair);
  - deterministic, stable serialization; no provider / DB / cache touch.
"""
import copy
import hashlib
import json
import unittest
from pathlib import Path

from routes.event_dossiers import (
    DETAIL_CONTRACT_VERSION,
    G1A_PATH,
    G1B_PATH,
    G6C_PATH,
    INDEX_CONTRACT_VERSION,
    build_all_event_dossiers,
    build_event_dossier,
    build_event_dossier_index,
)
from routes.mission_g_evidence import build_mission_g_evidence_summary
from routes.mission_i_evidence import build_mission_i_evidence_summary
from routes.mission_j_evidence import build_mission_j_evidence_summary

_ROOT = Path(__file__).resolve().parents[1]

# Published constants of the frozen universe (contract pins, not tunables).
TOTAL_EVENTS = 97
FOMC_EVENTS = 65
OPEC_EVENTS = 32
TOTAL_ROWS = 904
FOMC_ROWS = 520
OPEC_ROWS = 384

# The six G6C published per-event dossiers (published constants; the
# assembler must DISCOVER them from the publication, never from a list).
G6C_IDS = {
    "opec-2024-11-03-one-month-delay",
    "opec-2023-11-30-voluntary-2p2",
    "opec-2025-09-07-oct-137k",
    "opec-2024-03-03-q2-extension",
    "fomc-policy-decision-2019-09-18",
    "fomc-policy-decision-2018-05-02",
}

REQUIRED_SECTIONS = (
    "identity",
    "source_provenance",
    "eligibility_denominators",
    "mechanism_asset_basis",
    "reaction_observations",
    "reaction_enrichment",
    "ordinary_period_context",
    "aggregate_research_context",
    "robustness_timing_transmission",
    "falsifier_fragility",
    "missingness_limitations",
    "evidence_class_claim_ceiling",
    "non_claim",
)

SECTION_STATUSES = {
    "available",
    "structurally_unavailable",
    "not_applicable",
    "not_exposed",
    "unresolved",
    "contradictory",
}

TOP_LEVEL_STATUSES = {"COMPLETE", "PARTIAL", "UNAVAILABLE", "CONTRADICTORY"}

# Published aggregate vocabulary that must never become an event verdict.
AGGREGATE_LABELS = {
    "ELEVATED",
    "ORDINARY_UNRESOLVED",
    "ORDINARY / UNRESOLVED",
    "PROPAGATED",
    "BROAD MEASUREMENT CONSISTENCY",
    "LOWER-MAGNITUDE",
}

_STATE: dict = {}


def setUpModule():
    """Build every upstream summary and the full dossier set exactly once
    (tracked files only), so the suite stays fast and deterministic."""
    mission_i = build_mission_i_evidence_summary()
    mission_g = build_mission_g_evidence_summary()
    mission_j = build_mission_j_evidence_summary()
    seams = dict(
        mission_i_summary=mission_i,
        mission_g_summary=mission_g,
        mission_j_summary=mission_j,
    )
    _STATE["mission_i"] = mission_i
    _STATE["mission_g"] = mission_g
    _STATE["mission_j"] = mission_j
    _STATE["seams"] = seams
    _STATE["dossiers"] = build_all_event_dossiers(**seams)
    _STATE["index"] = build_event_dossier_index(**seams)


def _index() -> dict:
    return _STATE["index"]


def _dossiers() -> list:
    return _STATE["dossiers"]


def _dossier(candidate_id: str) -> dict:
    for d in _dossiers():
        if d["candidate_id"] == candidate_id:
            return d
    raise AssertionError(f"candidate missing from build: {candidate_id}")


def _mutated_mission_i(rename_from: str, rename_to: str) -> dict:
    m = copy.deepcopy(_STATE["mission_i"])
    for cell in m["event_level"]["cells"]:
        for row in cell["rows"]:
            if row["event"] == rename_from:
                row["event"] = rename_to
    return m


def _walk(node, ancestors):
    """Yield (value, ancestors) for every primitive in a JSON tree."""
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v, ancestors + [node])
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, ancestors)
    else:
        yield node, ancestors


# ---------------------------------------------------------------------------
# 1–2. Contract versions
# ---------------------------------------------------------------------------


class ContractVersionTests(unittest.TestCase):
    def test_1_index_contract_version(self):
        self.assertEqual(INDEX_CONTRACT_VERSION, "event-dossier-index-v1")
        self.assertEqual(_index()["contract_version"], "event-dossier-index-v1")
        self.assertEqual(_index()["universe"], "historical_research")

    def test_2_detail_contract_version(self):
        self.assertEqual(DETAIL_CONTRACT_VERSION, "event-dossier-v1")
        for d in _dossiers():
            self.assertEqual(d["contract_version"], "event-dossier-v1")


# ---------------------------------------------------------------------------
# 3–8. Universe accounting and publication order
# ---------------------------------------------------------------------------


class UniverseTests(unittest.TestCase):
    def test_3_exactly_97_indexed_events(self):
        self.assertEqual(len(_index()["events"]), TOTAL_EVENTS)
        self.assertEqual(_index()["coverage"]["total"], TOTAL_EVENTS)
        self.assertEqual(len(_dossiers()), TOTAL_EVENTS)

    def test_4_family_split_65_fomc_32_opec(self):
        events = _index()["events"]
        fams = [e["family"] for e in events]
        self.assertEqual(fams.count("FOMC"), FOMC_EVENTS)
        self.assertEqual(fams.count("OPEC"), OPEC_EVENTS)
        self.assertEqual(
            _index()["coverage"]["family_counts"],
            {"FOMC": FOMC_EVENTS, "OPEC": OPEC_EVENTS},
        )

    def test_5_candidate_ids_unique(self):
        ids = [e["candidate_id"] for e in _index()["events"]]
        self.assertEqual(len(set(ids)), TOTAL_EVENTS)

    def test_6_publication_order_preserved(self):
        # The authoritative order is the Mission I event surface: the FOMC
        # block first, then the OPEC block, each ascending by anchor
        # session — never response, percentile, aggregate state,
        # completeness, or G6C membership.
        events = _index()["events"]
        fomc_block = events[:FOMC_EVENTS]
        opec_block = events[FOMC_EVENTS:]
        self.assertTrue(all(e["family"] == "FOMC" for e in fomc_block))
        self.assertTrue(all(e["family"] == "OPEC" for e in opec_block))
        expected = {"FOMC": [], "OPEC": []}
        for cell in _STATE["mission_i"]["event_level"]["cells"]:
            if cell["cell_key"] in ("FOMC|1d|raw_return", "OPEC|1d|raw_return"):
                expected[cell["family"]] = [r["event"] for r in cell["rows"]]
        self.assertEqual(
            [e["candidate_id"] for e in fomc_block], expected["FOMC"])
        self.assertEqual(
            [e["candidate_id"] for e in opec_block], expected["OPEC"])
        for block in (fomc_block, opec_block):
            anchors = [e["anchor_session"] for e in block]
            self.assertEqual(anchors, sorted(anchors))

    def test_7_all_904_mission_i_rows_accounted(self):
        total = sum(
            len(d["sections"]["reaction_observations"]["data"]["rows"])
            for d in _dossiers())
        self.assertEqual(total, TOTAL_ROWS)

    def test_8_row_split_520_fomc_384_opec(self):
        by_family = {"FOMC": 0, "OPEC": 0}
        for d in _dossiers():
            fam = d["sections"]["identity"]["data"]["family"]
            by_family[fam] += len(
                d["sections"]["reaction_observations"]["data"]["rows"])
        self.assertEqual(by_family, {"FOMC": FOMC_ROWS, "OPEC": OPEC_ROWS})


# ---------------------------------------------------------------------------
# 9–11. Addressability and section schema
# ---------------------------------------------------------------------------


class SectionSchemaTests(unittest.TestCase):
    def test_9_every_indexed_id_resolves_via_detail(self):
        for entry in _index()["events"]:
            d = build_event_dossier(entry["candidate_id"], **_STATE["seams"])
            self.assertIsNotNone(d, entry["candidate_id"])
            self.assertEqual(d["candidate_id"], entry["candidate_id"])

    def test_10_every_dossier_has_all_required_sections(self):
        for d in _dossiers():
            self.assertEqual(
                tuple(d["sections"].keys()), REQUIRED_SECTIONS,
                d["candidate_id"])
            self.assertIn(d["top_level_status"], TOP_LEVEL_STATUSES)
            self.assertEqual(d["top_level_status"], "COMPLETE",
                             d["candidate_id"])

    def test_11_every_section_has_explicit_status_and_sources(self):
        for d in _dossiers():
            for name, section in d["sections"].items():
                ctx = f"{d['candidate_id']}::{name}"
                self.assertIn(section["status"], SECTION_STATUSES, ctx)
                self.assertIsInstance(section["reason_code"], str, ctx)
                self.assertNotEqual(section["reason_code"], "", ctx)
                self.assertIsInstance(section["summary"], str, ctx)
                self.assertNotEqual(section["summary"], "", ctx)
                refs = section["source_references"]
                self.assertIsInstance(refs, list, ctx)
                self.assertGreater(len(refs), 0, ctx)
                for ref in refs:
                    self.assertIn("artifact", ref, ctx)


# ---------------------------------------------------------------------------
# 12–14. G6C enrichment tier
# ---------------------------------------------------------------------------


class EnrichmentTests(unittest.TestCase):
    def test_12_g6c_events_discovered_from_publication(self):
        enriched = {
            e["candidate_id"]
            for e in _index()["events"]
            if e["enrichment_tier"] == "published_per_event_dossier"
        }
        self.assertEqual(enriched, G6C_IDS)
        self.assertEqual(
            _index()["coverage"]["enrichment_counts"],
            {"published_per_event_dossier": 6,
             "core_published_evidence": TOTAL_EVENTS - 6},
        )
        for cid in G6C_IDS:
            section = _dossier(cid)["sections"]["reaction_enrichment"]
            self.assertEqual(section["status"], "available", cid)
            rows = section["data"]["readout_rows"]
            self.assertEqual(len(rows), 4, cid)  # four published lenses
            for row in rows:
                for key in ("metric", "1d", "5d", "20d"):
                    self.assertIn(key, row, cid)

    def test_13_non_g6c_events_remain_in_index(self):
        core = [
            e for e in _index()["events"]
            if e["enrichment_tier"] == "core_published_evidence"
        ]
        self.assertEqual(len(core), TOTAL_EVENTS - 6)
        self.assertTrue(
            all(e["candidate_id"] not in G6C_IDS for e in core))

    def test_14_non_g6c_richer_reaction_reports_not_exposed(self):
        sample = "fomc-policy-decision-2018-01-31"
        self.assertNotIn(sample, G6C_IDS)
        section = _dossier(sample)["sections"]["reaction_enrichment"]
        self.assertEqual(section["status"], "not_exposed")
        self.assertEqual(
            section["reason_code"], "per_event_reaction_not_published")
        self.assertIsNone(section["data"])


# ---------------------------------------------------------------------------
# 15–16. Ordinary-period horizon availability
# ---------------------------------------------------------------------------


class HorizonAvailabilityTests(unittest.TestCase):
    def test_15_fomc_20d_structural_unavailability_visible(self):
        d = _dossier("fomc-policy-decision-2018-05-02")
        ordinary = d["sections"]["ordinary_period_context"]["data"]
        block = ordinary["fomc_20d"]
        self.assertEqual(block["status"], "structurally_unavailable")
        self.assertEqual(
            block["reason_code"], "fomc_20d_ordinary_substrate_unavailable")
        self.assertNotEqual(block["limitation"], "")
        elig = d["sections"]["eligibility_denominators"]["data"]
        self.assertEqual(elig["unavailable_horizons"], ["20d"])
        self.assertEqual(elig["available_horizons"], ["1d", "5d"])
        horizons = {r["horizon"] for r in ordinary["rows"]}
        self.assertEqual(horizons, {"1d", "5d"})

    def test_16_opec_20d_remains_available(self):
        d = _dossier("opec-2024-03-03-q2-extension")
        elig = d["sections"]["eligibility_denominators"]["data"]
        self.assertEqual(elig["unavailable_horizons"], [])
        self.assertEqual(elig["available_horizons"], ["1d", "5d", "20d"])
        ordinary = d["sections"]["ordinary_period_context"]["data"]
        self.assertNotIn("fomc_20d", ordinary)
        horizons = {r["horizon"] for r in ordinary["rows"]}
        self.assertEqual(horizons, {"1d", "5d", "20d"})


# ---------------------------------------------------------------------------
# 17–20. Aggregate context stays aggregate
# ---------------------------------------------------------------------------


class AggregateContextTests(unittest.TestCase):
    def test_17_mission_j_is_aggregate_context_for_fomc(self):
        d = _dossier("fomc-policy-decision-2019-09-18")
        mj = d["sections"]["robustness_timing_transmission"]["data"][
            "mission_j"]
        self.assertEqual(mj["status"], "available")
        self.assertEqual(mj["context_scope"], "aggregate")
        self.assertIn("Class B", mj["evidence_class"])
        # the published lens-dependent timing labels survive as aggregate
        # published cell labels, never per-event states
        timing = {c["metric"]: c["label"] for c in mj["j2_timing_cells"]}
        self.assertEqual(timing["raw_return"], "ORDINARY_UNRESOLVED")
        self.assertEqual(timing["spy_relative_ar"], "ORDINARY_UNRESOLVED")
        self.assertEqual(timing["sector_relative_ar"], "ELEVATED")
        self.assertEqual(timing["sar"], "ELEVATED")
        self.assertEqual(mj["c2_opec_collision_tags"], "0/65")
        self.assertEqual(mj["c1_status"], "unadjudicable")

    def test_18_mission_j_not_applicable_for_opec(self):
        d = _dossier("opec-2023-11-30-voluntary-2p2")
        mj = d["sections"]["robustness_timing_transmission"]["data"][
            "mission_j"]
        self.assertEqual(mj["status"], "not_applicable")
        self.assertEqual(mj["reason_code"], "mission_j_fomc_only")

    def test_19_no_aggregate_label_becomes_event_verdict(self):
        for d in _dossiers():
            self.assertNotIn("event_status", json.dumps(d))
            self.assertIn(d["top_level_status"], TOP_LEVEL_STATUSES)
            for name, section in d["sections"].items():
                self.assertNotIn(section["status"], AGGREGATE_LABELS)
            for value, ancestors in _walk(d, []):
                if isinstance(value, str) and value in AGGREGATE_LABELS:
                    scopes = [
                        a.get("context_scope") for a in ancestors
                        if isinstance(a, dict) and "context_scope" in a
                    ]
                    self.assertIn(
                        "aggregate", scopes,
                        f"{d['candidate_id']}: label {value!r} outside an "
                        f"aggregate-scoped context")

    def test_20_aggregate_contexts_carry_aggregate_scope(self):
        for d in _dossiers():
            agg = d["sections"]["aggregate_research_context"]["data"]
            self.assertGreater(len(agg["contexts"]), 0)
            for ctx in agg["contexts"]:
                self.assertEqual(ctx["context_scope"], "aggregate")


# ---------------------------------------------------------------------------
# 21–23. Identity separation, provenance independence, explicit nulls
# ---------------------------------------------------------------------------


class IdentityProvenanceTests(unittest.TestCase):
    def test_21_event_date_and_anchor_session_separate(self):
        for d in _dossiers():
            ident = d["sections"]["identity"]["data"]
            self.assertRegex(ident["event_date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertRegex(ident["anchor_session"], r"^\d{4}-\d{2}-\d{2}$")
        # at least one published event anchors on a different session than
        # its calendar event date (weekend OPEC decision)
        weekend = _dossier("opec-2024-11-03-one-month-delay")
        ident = weekend["sections"]["identity"]["data"]
        self.assertEqual(ident["event_date"], "2024-11-03")
        self.assertNotEqual(ident["event_date"], ident["anchor_session"])

    def test_22_source_provenance_never_depends_on_local_database(self):
        for d in _dossiers():
            blob = json.dumps(d)
            self.assertNotIn("events.db", blob, d["candidate_id"])
            src = d["sections"]["source_provenance"]
            self.assertEqual(src["status"], "available")
            arts = [ref["artifact"] for ref in src["source_references"]]
            self.assertTrue(
                any(a.startswith("stats/") for a in arts),
                d["candidate_id"])

    def test_23_missing_provenance_fields_remain_explicit(self):
        d = _dossier("fomc-policy-decision-2018-05-02")
        items = d["sections"]["missingness_limitations"]["data"]["items"]
        codes = {i["reason_code"] for i in items}
        self.assertIn("computation_date_not_recorded", codes)
        self.assertIn("execution_commit_not_recorded", codes)
        self.assertIn("source_section_not_exposed", codes)
        self.assertIn("fomc_20d_ordinary_substrate_unavailable", codes)
        self.assertIn("ideal_rates_measure_unavailable", codes)
        self.assertIn("collision_register_unadjudicable", codes)


# ---------------------------------------------------------------------------
# 24–25. Fail-closed joins and unknown identifiers
# ---------------------------------------------------------------------------


class FailClosedTests(unittest.TestCase):
    def test_24_malformed_identity_join_becomes_contradictory(self):
        renamed = "fomc-policy-decision-9999-01-01"
        mutated = _mutated_mission_i(
            "fomc-policy-decision-2018-01-31", renamed)
        seams = dict(_STATE["seams"], mission_i_summary=mutated)
        index = build_event_dossier_index(**seams)
        entry = next(
            e for e in index["events"] if e["candidate_id"] == renamed)
        self.assertEqual(entry["top_level_status"], "CONTRADICTORY")
        self.assertGreater(entry["contradictory_section_count"], 0)
        self.assertEqual(
            index["coverage"]["status_counts"]["CONTRADICTORY"], 1)
        self.assertGreater(
            index["coverage"]["contradiction_counts"]["events"], 0)
        detail = build_event_dossier(renamed, **seams)
        self.assertEqual(detail["top_level_status"], "CONTRADICTORY")
        self.assertEqual(
            detail["sections"]["identity"]["status"], "contradictory")
        # the untouched real build stays contradiction-free
        self.assertEqual(
            _index()["coverage"]["status_counts"]["CONTRADICTORY"], 0)

    def test_25_unknown_candidate_id_returns_not_found(self):
        self.assertIsNone(
            build_event_dossier("no-such-event", **_STATE["seams"]))
        self.assertIsNone(build_event_dossier("", **_STATE["seams"]))


# ---------------------------------------------------------------------------
# 26–30. Ordering honesty, purity, determinism, serialization
# ---------------------------------------------------------------------------


class DisciplineTests(unittest.TestCase):
    def test_26_no_response_or_percentile_ordering(self):
        # index entries carry no outcome field to sort by, and the order is
        # pinned to the publication surface in test 6; additionally the
        # index must not expose response/percentile values at all
        for entry in _index()["events"]:
            self.assertEqual(
                set(entry.keys()),
                {"candidate_id", "family", "event_date", "anchor_session",
                 "top_level_status", "available_section_count",
                 "unavailable_section_count",
                 "contradictory_section_count", "enrichment_tier"})

    def test_27_no_provider_or_network_import(self):
        source = (_ROOT / "routes" / "event_dossiers.py").read_text(
            encoding="utf-8")
        for token in ("requests", "httpx", "yfinance", "urllib",
                      "market_data", "price_cache", "sqlite3",
                      "movers_cache", "news_sources"):
            self.assertNotIn(f"import {token}", source, token)

    def test_28_no_tracked_source_file_mutates_during_build(self):
        paths = [G1A_PATH, G1B_PATH, G6C_PATH]
        before = [hashlib.sha256(Path(p).read_bytes()).hexdigest()
                  for p in paths]
        build_event_dossier_index(**_STATE["seams"])
        after = [hashlib.sha256(Path(p).read_bytes()).hexdigest()
                 for p in paths]
        self.assertEqual(before, after)

    def test_29_repeated_builds_are_deterministic(self):
        a = build_event_dossier_index(**_STATE["seams"])
        b = build_event_dossier_index(**_STATE["seams"])
        self.assertEqual(a, b)
        da = build_event_dossier(
            "opec-2025-09-07-oct-137k", **_STATE["seams"])
        db = build_event_dossier(
            "opec-2025-09-07-oct-137k", **_STATE["seams"])
        self.assertEqual(da, db)

    def test_30_json_serialization_is_stable(self):
        a = json.dumps(_index(), sort_keys=True)
        b = json.dumps(
            build_event_dossier_index(**_STATE["seams"]), sort_keys=True)
        self.assertEqual(a, b)
        for d in _dossiers()[:3] + _dossiers()[-3:]:
            json.dumps(d, sort_keys=True)  # must not raise


# ---------------------------------------------------------------------------
# Denominators and evidence classes (acceptance-criteria pins)
# ---------------------------------------------------------------------------


class DenominatorEvidenceClassTests(unittest.TestCase):
    def test_family_denominators_stay_separate(self):
        for d in _dossiers():
            elig = d["sections"]["eligibility_denominators"]["data"]
            fam = d["sections"]["identity"]["data"]["family"]
            want = FOMC_EVENTS if fam == "FOMC" else OPEC_EVENTS
            self.assertEqual(elig["family_event_n"], want, d["candidate_id"])
            self.assertGreater(len(elig["reference_n_by_horizon"]), 0)

    def test_evidence_classes_stay_separate_and_unpooled(self):
        fomc = _dossier("fomc-policy-decision-2019-09-18")
        opec = _dossier("opec-2024-11-03-one-month-delay")
        for d, expect_j in ((fomc, True), (opec, False)):
            data = d["sections"]["evidence_class_claim_ceiling"]["data"]
            classes = " ".join(data["classes"])
            self.assertIn("Mission G", classes)
            self.assertIn("Mission I", classes)
            self.assertEqual("Mission J" in classes, expect_j)
            self.assertNotEqual(data["pooling_prohibition"], "")

    def test_exact_non_claim_renders_on_every_dossier(self):
        want = (
            "This dossier assembles published descriptive evidence for one "
            "dated event. Aggregate labels remain aggregate context and are "
            "not individual-event classifications. The record is not a "
            "causal estimate, significance test, independent replication, "
            "prediction, trade signal or proof of a mechanism.")
        for d in _dossiers():
            self.assertEqual(
                d["sections"]["non_claim"]["data"]["statement"], want)


# ---------------------------------------------------------------------------
# U0 provenance repair — canonical G3 mapping, enrichment isolation, and
# exact per-section upstream references.
# ---------------------------------------------------------------------------

G3_ARTIFACT = "stats/G3_MECHANICAL_ELIGIBILITY.md"
G1A_ARTIFACT = "stats/G1A_FOMC_FRAME_INVENTORY.md"
G1B_ARTIFACT = "stats/G1B_OPEC_DESIGNED_RESERVOIR.md"
G6C_ARTIFACT = "stats/G6C_REPRESENTATIVE_CASES.md"
I1_ARTIFACT = "stats/I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md"
I2B_ARTIFACT = "stats/I2B_MEMP_PRIMARY_COMPARISON.md"
I2C_F_ARTIFACT = "stats/I2C_FALSIFIERS.md"
J_ARTIFACTS = {
    "stats/J1B_FOMC_ROBUSTNESS_RESULTS.md",
    "stats/J2_TIMING_COLLISION_RESULTS.md",
    "stats/J3_MECHANISM_TRANSMISSION_READOUT.md",
}

# The canonical family mapping wording exactly as the tracked G3
# publication freezes it — deliberately NOT the G6C per-dossier
# restatements (which append the ticker, e.g. "-> KRE").
G3_HYPOTHESES = {
    "FOMC": ("policy decision -> policy path / funding and curve "
             "conditions -> regional-bank equities"),
    "OPEC": ("collective production policy -> crude supply expectations "
             "-> producer cash flows -> exploration-and-production "
             "equities"),
}


def _mission_g_artifacts() -> set[str]:
    arts = set()
    for ref in _STATE["mission_g"]["provenance"]["sources"].values():
        name = ref["artifact"]
        arts.add(name if name.startswith("stats/") else f"stats/{name}")
    return arts


def _section_artifacts(dossier: dict, section: str) -> set[str]:
    return {ref["artifact"]
            for ref in dossier["sections"][section]["source_references"]}


class CanonicalMappingTests(unittest.TestCase):
    def test_mapping_version_available_from_tracked_g3(self):
        for d in _dossiers():
            mech = d["sections"]["mechanism_asset_basis"]
            self.assertEqual(mech["status"], "available", d["candidate_id"])
            mv = mech["data"]["mapping_version"]
            self.assertEqual(mv["status"], "available", d["candidate_id"])
            self.assertEqual(mv["value"], "g3-transmission-map-v1",
                             d["candidate_id"])
            self.assertIn(G3_ARTIFACT, _section_artifacts(
                d, "mechanism_asset_basis"), d["candidate_id"])

    def test_family_assets_match_canonical_map(self):
        want = {"FOMC": ("KRE", "SPY", "XLF"), "OPEC": ("XOP", "SPY", "XLE")}
        for d in _dossiers():
            fam = d["sections"]["identity"]["data"]["family"]
            data = d["sections"]["mechanism_asset_basis"]["data"]
            got = (data["primary_asset"], data["market_benchmark"],
                   data["sector_benchmark"])
            self.assertEqual(got, want[fam], d["candidate_id"])

    def test_universal_hypothesis_is_canonical_g3_not_g6c(self):
        for d in _dossiers():
            fam = d["sections"]["identity"]["data"]["family"]
            hyp = d["sections"]["mechanism_asset_basis"]["data"][
                "mechanism_hypothesis"]
            self.assertEqual(hyp, G3_HYPOTHESES[fam], d["candidate_id"])
            # the G6C restatements append the ticker; the canonical G3
            # wording does not — a ticker suffix means G6C leaked in
            self.assertFalse(hyp.endswith(("KRE", "XOP")),
                             d["candidate_id"])


class EnrichmentIsolationTests(unittest.TestCase):
    def _mutated_g6c_build(self, old: str, new: str):
        import tempfile
        original = Path(G6C_PATH).read_text(encoding="utf-8")
        assert old in original
        with tempfile.TemporaryDirectory() as tmp:
            mutated_path = Path(tmp) / "G6C_REPRESENTATIVE_CASES.md"
            mutated_path.write_text(
                original.replace(old, new), encoding="utf-8")
            return build_all_event_dossiers(
                mission_i_summary=_STATE["mission_i"],
                mission_g_summary=_STATE["mission_g"],
                mission_j_summary=_STATE["mission_j"],
                g6c_path=mutated_path)

    def test_g6c_readout_mutation_touches_only_enrichment(self):
        # perturb one published enrichment readout value; the universal
        # core (mechanism, observations, ordinary context) must be
        # byte-identical for every event — only the enrichment section of
        # the affected event (and G6C artifact hashes) may move
        mutated = self._mutated_g6c_build("+8.27%", "+9.99%")
        by_id = {d["candidate_id"]: d for d in mutated}
        for d in _dossiers():
            m = by_id[d["candidate_id"]]
            for name in ("mechanism_asset_basis", "reaction_observations",
                         "ordinary_period_context",
                         "eligibility_denominators", "identity"):
                self.assertEqual(d["sections"][name], m["sections"][name],
                                 f"{d['candidate_id']}::{name}")
        changed = "opec-2024-11-03-one-month-delay"
        self.assertNotEqual(
            _dossier(changed)["sections"]["reaction_enrichment"]["data"],
            by_id[changed]["sections"]["reaction_enrichment"]["data"])

    def test_g6c_asset_conflict_fails_closed_as_enrichment_conflict(self):
        # G6C may corroborate the canonical mapping but never redefine
        # it: a conflicting enrichment asset line marks that event's
        # enrichment contradictory and the dossier CONTRADICTORY, while
        # the universal mechanism stays canonical for every event
        mutated = self._mutated_g6c_build(
            "- assets: primary XOP, market benchmark SPY, sector "
            "benchmark XLE\n\nPre-event state (cutoff 2024-11-01)",
            "- assets: primary XLE, market benchmark SPY, sector "
            "benchmark XLE\n\nPre-event state (cutoff 2024-11-01)")
        by_id = {d["candidate_id"]: d for d in mutated}
        conflicted = by_id["opec-2024-11-03-one-month-delay"]
        section = conflicted["sections"]["reaction_enrichment"]
        self.assertEqual(section["status"], "contradictory")
        self.assertEqual(section["reason_code"],
                         "g6c_mapping_conflicts_canonical_map")
        self.assertEqual(conflicted["top_level_status"], "CONTRADICTORY")
        self.assertEqual(
            conflicted["sections"]["mechanism_asset_basis"]["data"][
                "primary_asset"], "XOP")
        untouched = by_id["opec-2023-11-30-voluntary-2p2"]
        self.assertEqual(untouched["top_level_status"], "COMPLETE")


class ExactProvenanceTests(unittest.TestCase):
    SAMPLES = (
        "fomc-policy-decision-2018-05-02",   # FOMC, G6C-enriched
        "fomc-policy-decision-2018-01-31",   # FOMC, core-only
        "opec-2024-03-03-q2-extension",      # OPEC, G6C-enriched
        "opec-2018-06-23-conformity-return",  # OPEC, core-only
    )

    def test_each_section_cites_its_true_upstream_sources(self):
        g_arts = _mission_g_artifacts()
        for cid in self.SAMPLES:
            d = _dossier(cid)
            fam = d["sections"]["identity"]["data"]["family"]
            ledger = G1A_ARTIFACT if fam == "FOMC" else G1B_ARTIFACT
            enriched = d["enrichment_tier"] == "published_per_event_dossier"

            self.assertLessEqual({ledger, I2B_ARTIFACT},
                                 _section_artifacts(d, "identity"), cid)
            self.assertEqual({ledger},
                             _section_artifacts(d, "source_provenance"),
                             cid)
            self.assertLessEqual(
                {I1_ARTIFACT, I2B_ARTIFACT},
                _section_artifacts(d, "eligibility_denominators"), cid)
            self.assertIn(G3_ARTIFACT,
                          _section_artifacts(d, "mechanism_asset_basis"),
                          cid)
            self.assertEqual({I2B_ARTIFACT},
                             _section_artifacts(d, "reaction_observations"),
                             cid)
            self.assertEqual({G6C_ARTIFACT},
                             _section_artifacts(d, "reaction_enrichment"),
                             cid)
            self.assertEqual({I2B_ARTIFACT},
                             _section_artifacts(d, "ordinary_period_context"),
                             cid)
            agg = _section_artifacts(d, "aggregate_research_context")
            self.assertIn(I2B_ARTIFACT, agg, cid)
            self.assertTrue(agg & g_arts, cid)
            rob = _section_artifacts(d, "robustness_timing_transmission")
            self.assertTrue(rob & g_arts, cid)
            if fam == "FOMC":
                self.assertLessEqual(J_ARTIFACTS, rob, cid)
            else:
                self.assertFalse(rob & J_ARTIFACTS, cid)
            fals = _section_artifacts(d, "falsifier_fragility")
            self.assertIn(I2C_F_ARTIFACT, fals, cid)
            if fam == "OPEC":
                self.assertTrue(fals & g_arts, cid)
            missing = _section_artifacts(d, "missingness_limitations")
            if fam == "FOMC":
                # M1 and C1 statements render from Mission J — they must
                # cite Mission J, never only an identity ledger
                self.assertTrue(missing & J_ARTIFACTS, cid)
            classes = _section_artifacts(d, "evidence_class_claim_ceiling")
            self.assertIn(I2B_ARTIFACT, classes, cid)
            self.assertTrue(classes & g_arts, cid)
            self.assertEqual(
                "stats/J1B_FOMC_ROBUSTNESS_RESULTS.md" in classes,
                fam == "FOMC", cid)
            self.assertEqual(G6C_ARTIFACT in classes, enriched, cid)
            self.assertEqual({"event-dossier-v1"},
                             _section_artifacts(d, "non_claim"), cid)

    def test_no_ledger_cited_as_mission_j_source(self):
        for cid in self.SAMPLES:
            d = _dossier(cid)
            src = _section_artifacts(d, "source_provenance")
            self.assertFalse(src & J_ARTIFACTS, cid)


class IndexProvenanceTests(unittest.TestCase):
    def test_generated_from_covers_every_load_bearing_source(self):
        arts = [ref["artifact"] for ref in _index()["generated_from"]]
        required = {G1A_ARTIFACT, G1B_ARTIFACT, G3_ARTIFACT, I1_ARTIFACT,
                    I2B_ARTIFACT, G6C_ARTIFACT} | J_ARTIFACTS
        self.assertLessEqual(required, set(arts))
        self.assertTrue(set(arts) & _mission_g_artifacts())

    def test_generated_from_is_deduplicated_and_deterministic(self):
        arts = [ref["artifact"] for ref in _index()["generated_from"]]
        self.assertEqual(len(arts), len(set(arts)))
        again = [ref["artifact"] for ref in build_event_dossier_index(
            **_STATE["seams"])["generated_from"]]
        self.assertEqual(arts, again)


if __name__ == "__main__":
    unittest.main()
