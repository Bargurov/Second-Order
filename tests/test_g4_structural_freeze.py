"""Tests for the G4 outcome-blind structural validation and final freeze.

Contract under test (G0 protocol g0-v1, sections 6-9; task G4):

* the structural universe reconciles EXACTLY (65 + 32 = 97, unique ids,
  unique event dates, 97/97 canonical + sector-relative mechanical
  eligibility parsed from the tracked G3 artifact) and drift fails loudly;
* only the five G0-frozen state dimensions may be evaluated; each receives
  exactly one deterministic status from outcome-blind structure alone;
* tags are secondary, definition-derived (sign-based only), and rejected
  deterministically when any category lacks unique-date support;
* designed-contrast recruitment is a deterministic, outcome-blind rule over
  the 32-row reservoir; every reservoir row is accounted for exactly once;
  the 65 frame rows are never filtered;
* the G6 manifest is deterministic, within-lane only, never keyed by the
  G3B mechanism taxonomy, and carries descriptive-only claim tiers;
* the tracked freeze report regenerates byte-identically;
* no outcome-shaped field can enter any G4 input or artifact.

Pure fixtures where possible; live tests skip when artifacts are absent.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import g_state_acquisition as gsa  # noqa: E402
from scripts import g4_structural_freeze as g4  # noqa: E402

G1A = ROOT / "stats" / "G1A_FOMC_FRAME_INVENTORY.md"
G1B = ROOT / "stats" / "G1B_OPEC_DESIGNED_RESERVOIR.md"
G3_REPORT = ROOT / "stats" / "G3_MECHANICAL_ELIGIBILITY.md"
CACHE = ROOT / "g_state_cache"

LIVE_READY = (G1A.exists() and G1B.exists() and G3_REPORT.exists()
              and (CACHE / "vix.json").exists()
              and (CACHE / "hy_oas.json").exists())


# ---------------------------------------------------------------------------
# Fixtures: a tiny 6-candidate universe with computable states
# ---------------------------------------------------------------------------

def _weekday_sessions(n, end=(2024, 6, 28)):
    from datetime import date, timedelta
    out, cur = [], date(*end)
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur -= timedelta(days=1)
    return sorted(out)


SESSIONS = _weekday_sessions(400)


def _series(dates, fn):
    return {d: fn(i, d) for i, d in enumerate(dates)}


def _fixture_bundle(hy_from=None):
    """States computable at late-2023/2024 cutoffs; hy optionally truncated
    to start at `hy_from` (era-structural missingness shape)."""
    vix = _series(SESSIONS, lambda i, d: 15.0 + (i % 7))
    spy = _series(SESSIONS, lambda i, d: 400.0 + 0.1 * i - (5 if i % 11 == 0
                                                            else 0))
    curve = _series(SESSIONS, lambda i, d: -0.5 + 0.005 * i)
    hy = {d: 3.5 + 0.001 * i for i, d in enumerate(SESSIONS)
          if hy_from is None or d >= hy_from}
    return gsa.SourceBundle(
        sessions=SESSIONS, vix=vix, spy=spy, curve_2s10s=curve, hy_oas=hy,
        fed_timeline=[("2022-01-05", 1.0), ("2024-03-05", 1.5),
                      ("2024-05-01", 1.25)],
        blocked={})


def _fixture_candidates():
    return [
        {"candidate_id": "fomc-policy-decision-2024-05-01",
         "event_date": "2024-05-01", "lane": "frame_complete_historical"},
        {"candidate_id": "fomc-policy-decision-2024-06-12",
         "event_date": "2024-06-12", "lane": "frame_complete_historical"},
        {"candidate_id": "opec-2024-06-02-fixture",
         "event_date": "2024-06-02", "lane": "designed_contrast"},
        {"candidate_id": "opec-2024-03-03-fixture",
         "event_date": "2024-03-03", "lane": "designed_contrast"},
    ]


# ---------------------------------------------------------------------------
# 1. Structural rows: delegation to G2 primitives, firewall on inputs
# ---------------------------------------------------------------------------


class StructuralRowTests(unittest.TestCase):
    def test_state_values_delegate_to_frozen_g2_primitives(self):
        bundle = _fixture_bundle()
        rows = g4.build_structural_rows(_fixture_candidates(), bundle)
        row = next(r for r in rows
                   if r["candidate_id"] == "fomc-policy-decision-2024-06-12")
        cutoff = gsa.conservative_cutoff("2024-06-12", SESSIONS)
        self.assertEqual(row["cutoff"], cutoff)
        self.assertEqual(row["state"]["fed_policy_path"],
                         gsa.fed_net_change(bundle.fed_timeline, cutoff,
                                            months=6)["value"])
        self.assertEqual(row["state"]["vix_level_percentile"],
                         gsa.trailing_percentile(bundle.vix, cutoff,
                                                 window=252)["value"])
        self.assertEqual(row["state"]["spy_trend_ma200"],
                         gsa.ma_distance(bundle.spy, cutoff,
                                         window=200)["value"])
        self.assertEqual(row["state"]["curve_2s10s"],
                         gsa.latest_eligible(bundle.curve_2s10s, cutoff,
                                             availability="next_day")[1])
        self.assertEqual(row["state"]["credit_hy_oas"],
                         gsa.latest_eligible(bundle.hy_oas, cutoff,
                                             availability="next_day")[1])

    def test_no_new_lookback_constants_in_module_source(self):
        src = Path(g4.__file__).read_text(encoding="utf-8")
        for m in re.finditer(r"window\s*=\s*(\d+)", src):
            self.assertIn(m.group(1), ("200", "252"), m.group(0))
        self.assertNotRegex(src, r"months\s*=\s*(?!6\b)\d+")

    def test_outcome_shaped_candidate_key_is_rejected(self):
        bad = dict(_fixture_candidates()[0])
        bad["car_20d"] = 0.05
        with self.assertRaises(ValueError):
            g4.build_structural_rows([bad], _fixture_bundle())

    def test_rows_carry_only_whitelisted_fields(self):
        rows = g4.build_structural_rows(_fixture_candidates(),
                                        _fixture_bundle())
        for r in rows:
            self.assertEqual(set(r), set(g4.STRUCTURAL_ROW_FIELDS))
            self.assertEqual(set(r["state"]), set(gsa.DIMENSIONS))
        dumped = json.dumps(rows).lower()
        for banned in ("abnormal", "outcome", '"sar"', '"car"', "raw_return",
                       "readout", "reaction", "direction", "effect"):
            self.assertNotIn(banned, dumped, banned)


# ---------------------------------------------------------------------------
# 2. Deterministic dimension-status freeze
# ---------------------------------------------------------------------------


class DimensionStatusTests(unittest.TestCase):
    def test_full_coverage_dimensions_are_primary_retained(self):
        rows = g4.build_structural_rows(_fixture_candidates(),
                                        _fixture_bundle())
        statuses = g4.freeze_dimension_statuses(rows)
        self.assertEqual(set(statuses), set(gsa.DIMENSIONS))
        for dim in ("fed_policy_path", "vix_level_percentile",
                    "spy_trend_ma200", "curve_2s10s"):
            self.assertEqual(statuses[dim]["status"], "primary_retained",
                             dim)
        for dim in statuses:
            self.assertIn(statuses[dim]["status"], g4.STATUSES)

    def test_era_structural_partial_dimension_is_secondary_subset_only(self):
        bundle = _fixture_bundle(hy_from="2024-04-01")
        rows = g4.build_structural_rows(_fixture_candidates(), bundle)
        statuses = g4.freeze_dimension_statuses(rows)
        self.assertEqual(statuses["credit_hy_oas"]["status"],
                         "secondary_subset_only")

    def test_zero_coverage_dimension_is_dropped(self):
        bundle = _fixture_bundle()
        bundle = gsa.SourceBundle(
            sessions=bundle.sessions, vix=bundle.vix, spy=bundle.spy,
            curve_2s10s=bundle.curve_2s10s, hy_oas=None,
            fed_timeline=bundle.fed_timeline,
            blocked={"hy_oas": "source_blocked"})
        rows = g4.build_structural_rows(_fixture_candidates(), bundle)
        statuses = g4.freeze_dimension_statuses(rows)
        self.assertEqual(statuses["credit_hy_oas"]["status"], "dropped")

    def test_status_freeze_is_deterministic(self):
        bundle = _fixture_bundle(hy_from="2024-04-01")
        rows = g4.build_structural_rows(_fixture_candidates(), bundle)
        self.assertEqual(g4.freeze_dimension_statuses(rows),
                         g4.freeze_dimension_statuses(list(reversed(rows))))


# ---------------------------------------------------------------------------
# 3. Deterministic secondary tags (sign-based only, degeneracy rejected)
# ---------------------------------------------------------------------------


class TagFreezeTests(unittest.TestCase):
    def _rows(self, n_pos, n_neg, dim="curve_2s10s"):
        """n_pos rows with positive state and n_neg with negative, distinct
        event dates throughout."""
        rows = []
        for i in range(n_pos + n_neg):
            val = 1.0 if i < n_pos else -1.0
            state = {d: 0.5 for d in gsa.DIMENSIONS}
            state[dim] = val
            rows.append({
                "candidate_id": f"c{i:03d}",
                "lane": "frame_complete_historical" if i % 2 == 0
                        else "designed_contrast",
                "family": "fomc" if i % 2 == 0 else "opec",
                "event_date": f"2024-{1 + i // 27:02d}-{1 + i % 27:02d}",
                "year": "2024",
                "cutoff": "2024-01-02",
                "state": state,
            })
        return rows

    def test_sign_tag_retained_when_every_category_supported(self):
        rows = self._rows(g4.MIN_TAG_CATEGORY_UNIQUE_DATES,
                          g4.MIN_TAG_CATEGORY_UNIQUE_DATES)
        statuses = {d: {"status": "primary_retained"} for d in gsa.DIMENSIONS}
        tags = g4.freeze_tags(rows, statuses)
        curve = tags["curve_2s10s"]
        self.assertEqual(curve["decision"], "tag_retained")
        self.assertEqual(curve["rule"],
                         "inverted if value < 0 else non_inverted")
        occ = curve["occupancy"]["by_category"]
        self.assertEqual(occ["inverted"]["unique_dates"],
                         g4.MIN_TAG_CATEGORY_UNIQUE_DATES)

    def test_sign_tag_rejected_as_degenerate_when_one_side_is_thin(self):
        rows = self._rows(2 * g4.MIN_TAG_CATEGORY_UNIQUE_DATES,
                          g4.MIN_TAG_CATEGORY_UNIQUE_DATES - 1)
        statuses = {d: {"status": "primary_retained"} for d in gsa.DIMENSIONS}
        tags = g4.freeze_tags(rows, statuses)
        self.assertEqual(tags["curve_2s10s"]["decision"], "continuous_only")
        self.assertIn("degenerate", tags["curve_2s10s"]["reason"])

    def test_vix_percentile_is_always_continuous_only(self):
        rows = self._rows(20, 20)
        statuses = {d: {"status": "primary_retained"} for d in gsa.DIMENSIONS}
        tags = g4.freeze_tags(rows, statuses)
        self.assertEqual(tags["vix_level_percentile"]["decision"],
                         "continuous_only")
        self.assertIn("arbitrary", tags["vix_level_percentile"]["reason"])

    def test_non_primary_dimension_gets_no_tag(self):
        rows = self._rows(20, 20)
        statuses = {d: {"status": "primary_retained"} for d in gsa.DIMENSIONS}
        statuses["credit_hy_oas"] = {"status": "secondary_subset_only"}
        tags = g4.freeze_tags(rows, statuses)
        self.assertEqual(tags["credit_hy_oas"]["decision"],
                         "continuous_only")

    def test_tag_assignment_is_deterministic(self):
        rows = self._rows(15, 15)
        statuses = {d: {"status": "primary_retained"} for d in gsa.DIMENSIONS}
        self.assertEqual(g4.freeze_tags(rows, statuses),
                         g4.freeze_tags(list(reversed(rows)), statuses))


# ---------------------------------------------------------------------------
# 4. Designed-contrast recruitment (deterministic, outcome-blind)
# ---------------------------------------------------------------------------


class RecruitmentTests(unittest.TestCase):
    def _rows(self):
        bundle = _fixture_bundle()
        return g4.build_structural_rows(_fixture_candidates(), bundle)

    def test_frame_rows_are_never_filtered(self):
        rows = self._rows()
        primary = ("fed_policy_path", "vix_level_percentile",
                   "spy_trend_ma200", "curve_2s10s")
        ledger = g4.recruit_designed(rows, primary_dims=primary)
        frame_ids = {r["candidate_id"] for r in rows
                     if r["lane"] == "frame_complete_historical"}
        self.assertEqual(set(ledger["frame_preserved_ids"]), frame_ids)

    def test_reservoir_partitions_exactly_once(self):
        rows = self._rows()
        primary = ("fed_policy_path", "vix_level_percentile",
                   "spy_trend_ma200", "curve_2s10s")
        ledger = g4.recruit_designed(rows, primary_dims=primary)
        reservoir = {r["candidate_id"] for r in rows
                     if r["lane"] == "designed_contrast"}
        recruited = set(ledger["recruited_ids"])
        non_recruited = {e["candidate_id"] for e in ledger["non_recruited"]}
        self.assertEqual(recruited | non_recruited, reservoir)
        self.assertEqual(recruited & non_recruited, set())
        self.assertTrue(recruited.issubset(reservoir))

    def test_incomplete_primary_state_is_non_recruited_with_reason(self):
        rows = self._rows()
        for r in rows:
            if r["candidate_id"] == "opec-2024-03-03-fixture":
                r["state"]["curve_2s10s"] = None
        primary = ("fed_policy_path", "vix_level_percentile",
                   "spy_trend_ma200", "curve_2s10s")
        ledger = g4.recruit_designed(rows, primary_dims=primary)
        non = {e["candidate_id"]: e["reason"]
               for e in ledger["non_recruited"]}
        self.assertIn("opec-2024-03-03-fixture", non)
        self.assertIn("incomplete_primary_state", non
                      ["opec-2024-03-03-fixture"])

    def test_outcome_shaped_row_key_is_rejected(self):
        rows = self._rows()
        rows[0] = dict(rows[0])
        rows[0]["sar_5d"] = 1.2
        with self.assertRaises(ValueError):
            g4.recruit_designed(rows, primary_dims=("fed_policy_path",))


# ---------------------------------------------------------------------------
# 5. G6 comparison manifest (deterministic, mechanism-free, within-lane)
# ---------------------------------------------------------------------------


class ManifestTests(unittest.TestCase):
    def _inputs(self):
        bundle = _fixture_bundle()
        rows = g4.build_structural_rows(_fixture_candidates(), bundle)
        statuses = g4.freeze_dimension_statuses(rows)
        tags = g4.freeze_tags(rows, statuses)
        return rows, statuses, tags

    def test_manifest_is_deterministic_and_within_lane_only(self):
        rows, statuses, tags = self._inputs()
        m1 = g4.build_manifest(rows, statuses, tags)
        m2 = g4.build_manifest(list(reversed(rows)), statuses, tags)
        self.assertEqual(m1, m2)
        for entry in m1:
            self.assertIn(entry["lane"],
                          ("frame_complete_historical", "designed_contrast"))
            self.assertNotIn("pooled", json.dumps(entry).lower())

    def test_manifest_axes_are_only_retained_dims_or_frozen_tags(self):
        rows, statuses, tags = self._inputs()
        manifest = g4.build_manifest(rows, statuses, tags)
        allowed = {d for d, s in statuses.items()
                   if s["status"] != "dropped"}
        for entry in manifest:
            self.assertIn(entry["state_axis"], allowed)

    def test_mechanism_taxonomy_cannot_enter_manifest(self):
        rows, statuses, tags = self._inputs()
        manifest = g4.build_manifest(rows, statuses, tags)
        dumped = json.dumps(manifest).lower()
        for banned in ("mechanism", "taxonomy", "j1", "overlay",
                       "supply_shock", "tariff", "sanction"):
            self.assertNotIn(banned, dumped, banned)
        with self.assertRaises(ValueError):
            g4.build_manifest(rows, statuses, tags,
                              extra_axes=("mechanism_family",))

    def test_every_entry_is_descriptive_only_with_no_fdr_pool(self):
        rows, statuses, tags = self._inputs()
        for entry in g4.build_manifest(rows, statuses, tags):
            self.assertEqual(entry["claim_tier"],
                             "conditional_descriptive")
            self.assertEqual(entry["fdr_scope"], "none_descriptive_only")

    def test_benchmarks_come_from_frozen_transmission_map(self):
        rows, statuses, tags = self._inputs()
        from scripts.g3_mechanical_grinder import TRANSMISSION_MAP
        for entry in g4.build_manifest(rows, statuses, tags):
            fam = "fomc" if entry["lane"] == "frame_complete_historical" \
                else "opec"
            lens = TRANSMISSION_MAP[fam]
            self.assertEqual(entry["primary_asset"], lens.primary)
            self.assertEqual(entry["market_benchmark"], lens.market)
            self.assertEqual(entry["sector_benchmark"], lens.sector)


# ---------------------------------------------------------------------------
# 6. Live structural run (97 candidates, real cache, real artifacts)
# ---------------------------------------------------------------------------


@unittest.skipUnless(LIVE_READY, "live ledgers, G3 artifact, cache required")
class LiveFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidates = (gsa.parse_g1a_candidates(str(G1A))
                          + gsa.parse_g1b_candidates(str(G1B)))
        cls.bundle = gsa.load_bundle()
        cls.rows = g4.build_structural_rows(cls.candidates, cls.bundle)

    def test_universe_reconciles_65_32_97_unique(self):
        recon = g4.reconcile_universe(
            self.rows, G3_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(recon["frame_complete_historical"], 65)
        self.assertEqual(recon["designed_contrast"], 32)
        self.assertEqual(recon["total"], 97)
        self.assertEqual(recon["unique_candidate_ids"], 97)
        self.assertEqual(recon["unique_event_dates"], 97)
        self.assertEqual(recon["canonical_eligible"], 97)
        self.assertEqual(recon["sector_relative_eligible"], 97)

    def test_reconciliation_drift_fails_loudly(self):
        with self.assertRaises(ValueError):
            g4.reconcile_universe(
                self.rows[:-1], G3_REPORT.read_text(encoding="utf-8"))

    def test_live_statuses_four_primary_credit_secondary(self):
        statuses = g4.freeze_dimension_statuses(self.rows)
        for dim in ("fed_policy_path", "vix_level_percentile",
                    "spy_trend_ma200", "curve_2s10s"):
            self.assertEqual(statuses[dim]["status"], "primary_retained")
        self.assertEqual(statuses["credit_hy_oas"]["status"],
                         "secondary_subset_only")
        self.assertEqual(statuses["credit_hy_oas"]["coverage"], 36)

    def test_live_retained_tags_obey_support_rule(self):
        statuses = g4.freeze_dimension_statuses(self.rows)
        tags = g4.freeze_tags(self.rows, statuses)
        for dim, t in tags.items():
            if t["decision"] == "tag_retained":
                for cat in t["occupancy"]["by_category"].values():
                    self.assertGreaterEqual(
                        cat["unique_dates"],
                        g4.MIN_TAG_CATEGORY_UNIQUE_DATES, dim)

    def test_live_recruitment_covers_full_reservoir(self):
        statuses = g4.freeze_dimension_statuses(self.rows)
        primary = tuple(d for d, s in statuses.items()
                        if s["status"] == "primary_retained")
        ledger = g4.recruit_designed(self.rows, primary_dims=primary)
        self.assertEqual(len(ledger["frame_preserved_ids"]), 65)
        self.assertEqual(
            len(ledger["recruited_ids"]) + len(ledger["non_recruited"]), 32)

    def test_live_manifest_denominators_match_structure(self):
        statuses = g4.freeze_dimension_statuses(self.rows)
        tags = g4.freeze_tags(self.rows, statuses)
        manifest = g4.build_manifest(self.rows, statuses, tags)
        by_key = {(e["lane"], e["state_axis"], e["use"]): e
                  for e in manifest}
        self.assertEqual(len(by_key), len(manifest))  # no duplicate entry
        cont_frame = by_key[("frame_complete_historical",
                             "fed_policy_path", "continuous")]
        self.assertEqual(cont_frame["eligible_denominator"], 65)
        self.assertEqual(cont_frame["unique_dates"], 65)
        credit_opec = by_key[("designed_contrast", "credit_hy_oas",
                              "continuous")]
        self.assertEqual(credit_opec["eligible_denominator"], 16)
        self.assertEqual(credit_opec["claim_tier"],
                         "conditional_descriptive")

    def test_report_regenerates_byte_identically(self):
        artifact = ROOT / "stats" / "G4_STRUCTURAL_FREEZE.md"
        if not artifact.exists():
            self.skipTest("freeze report not yet generated")
        self.assertEqual(artifact.read_text(encoding="utf-8"),
                         g4.build_freeze_report_text())

    def test_report_names_g3b_exclusion_and_nonclaims(self):
        text = g4.build_freeze_report_text()
        self.assertIn("J1 mechanism overlay is not a comparable "
                      "cross-cohort axis", text)
        self.assertIn("excluded from G6 conditioning", text)
        self.assertIn("No outcome inference", text)


if __name__ == "__main__":
    unittest.main()
