"""Tests for stats.robust_diagnostics — small-sample robustness diagnostics.

These are descriptive supplements (exact sign test, Wilcoxon signed-rank,
event-window overlap disclosure, SAR-convention audit). Known-answer cases use
externally-anchored values (binomial / pure combinatorics), not self-consistency.
"""
from __future__ import annotations

import math

import pytest

from stats.robust_diagnostics import (
    ROBUST_DIAGNOSTICS_NON_CLAIMS,
    build_diagnostics_block,
    build_overlap_disclosure,
    exact_sign_test,
    rank_test_summary,
    sar_convention_summary,
    window_overlap_summary,
)


# ---------------------------------------------------------------------------
# exact_sign_test — exact binomial, p=0.5 null
# ---------------------------------------------------------------------------


def test_sign_test_known_answer_9_of_10():
    # External anchor: two-sided binomial p for 9/10 successes at p=0.5
    # = 2 * (C(10,9)+C(10,10))/2^10 = 2 * 11/1024 = 0.021484375
    out = exact_sign_test([1, 1, 1, 1, 1, 1, 1, 1, 1, -1])
    assert out["status"] == "ok"
    assert out["n"] == 10
    assert out["n_pos"] == 9
    assert out["n_neg"] == 1
    assert out["n_zero"] == 0
    assert out["method"] == "exact_binomial_sign_test"
    assert out["p_value"] == pytest.approx(0.021484375, abs=1e-12)


def test_sign_test_all_positive_n6():
    # two-sided = 2 * C(6,6)/2^6 = 2/64 = 0.03125
    out = exact_sign_test([0.4, 0.1, 2.0, 0.7, 0.3, 1.1])
    assert out["status"] == "ok"
    assert out["n_pos"] == 6 and out["n_neg"] == 0
    assert out["p_value"] == pytest.approx(0.03125, abs=1e-12)


def test_sign_test_all_negative_n6():
    out = exact_sign_test([-0.4, -0.1, -2.0, -0.7, -0.3, -1.1])
    assert out["status"] == "ok"
    assert out["n_pos"] == 0 and out["n_neg"] == 6
    assert out["p_value"] == pytest.approx(0.03125, abs=1e-12)


def test_sign_test_balanced_is_p_one():
    # 2 pos / 2 neg: observed is the modal outcome -> two-sided p clamps to 1.0
    out = exact_sign_test([1.0, 2.0, -1.0, -2.0])
    assert out["status"] == "ok"
    assert out["p_value"] == pytest.approx(1.0, abs=1e-12)


def test_sign_test_one_sided_greater():
    out = exact_sign_test([1] * 9 + [-1], alternative="greater")
    # P(X >= 9) = (C(10,9)+C(10,10))/1024 = 11/1024
    assert out["p_value"] == pytest.approx(11.0 / 1024.0, abs=1e-12)
    assert out["alternative"] == "greater"


def test_sign_test_zeros_dropped_and_counted():
    out = exact_sign_test([0.0, 1.0, 2.0, 3.0])
    assert out["n_zero"] == 1
    assert out["n"] == 3  # effective n excludes the zero
    assert out["n_pos"] == 3


def test_sign_test_all_zero_status():
    out = exact_sign_test([0.0, 0.0, 0.0])
    assert out["status"] == "all_zero"
    assert out["p_value"] is None


def test_sign_test_empty_is_insufficient():
    out = exact_sign_test([])
    assert out["status"] == "insufficient_n"
    assert out["p_value"] is None


def test_sign_test_invalid_alternative_raises():
    with pytest.raises(ValueError):
        exact_sign_test([1, -1], alternative="Two-Sided")


def test_sign_test_null_label_present():
    out = exact_sign_test([1, -1, 1])
    assert "0.5" in out["null"] and "direction" in out["null"].lower()


# ---------------------------------------------------------------------------
# rank_test_summary — Wilcoxon signed-rank (symmetry-about-zero null)
# ---------------------------------------------------------------------------


def test_rank_test_all_positive_n3_exact():
    # ranks {1,2,3}; W+ = 6 (max). Over 2^3=8 sign vectors only +++ gives 6,
    # so two-sided = 2 * (1/8) = 0.25. Pure combinatorics anchor.
    out = rank_test_summary([1.0, 2.0, 3.0])
    assert out["status"] == "ok"
    assert out["n"] == 3
    assert out["w_plus"] == pytest.approx(6.0)
    assert out["method"] == "exact_signed_rank"
    assert out["p_value"] == pytest.approx(0.25, abs=1e-12)


def test_rank_test_all_positive_n5_exact():
    # two-sided = 2 * (1/2^5) = 0.0625
    out = rank_test_summary([0.1, 0.2, 0.3, 0.4, 0.5])
    assert out["p_value"] == pytest.approx(0.0625, abs=1e-12)
    assert out["method"] == "exact_signed_rank"


def test_rank_test_all_positive_n4_exact():
    out = rank_test_summary([1, 2, 3, 4])
    assert out["p_value"] == pytest.approx(0.125, abs=1e-12)


def test_rank_test_zero_dropped():
    out = rank_test_summary([0.0, 1.0, 2.0, 3.0])
    assert out["n"] == 3
    assert out["n_zero"] == 1
    assert out["p_value"] == pytest.approx(0.25, abs=1e-12)


def test_rank_test_symmetry_assumption_disclosed():
    out = rank_test_summary([1.0, -2.0, 3.0])
    assert out["assumption"] == "symmetry_about_zero"


def test_rank_test_all_zero_status():
    out = rank_test_summary([0.0, 0.0])
    assert out["status"] == "all_zero"
    assert out["p_value"] is None


def test_rank_test_empty_is_insufficient():
    out = rank_test_summary([])
    assert out["status"] == "insufficient_n"


def test_rank_test_large_n_uses_normal_approx():
    # n above the exact-enumeration cap switches method label and stays valid.
    out = rank_test_summary([float(i) for i in range(1, 25)])  # 24 positives
    assert out["method"] == "normal_approx_signed_rank"
    assert out["status"] == "ok"
    assert 0.0 <= out["p_value"] <= 1.0


def test_rank_test_normal_approx_agrees_with_exact():
    # The live report runs at n=72, so EVERY shipped Wilcoxon p-value comes from
    # the normal-approximation path. Anchor that path to the externally-verified
    # exact path: on the same ranks they must agree closely in the central
    # region. Two independent implementations (DP enumeration vs closed-form
    # Gaussian) agreeing catches a wrong variance, a missing continuity
    # correction, or a one-vs-two-sided slip.
    from stats.robust_diagnostics import (
        _average_ranks,
        _wilcoxon_exact_two_sided,
        _wilcoxon_normal_two_sided,
    )
    # 20 distinct magnitudes (ranks 1..20); largest 7 negative -> moderate W+.
    vals = [float(i) for i in range(1, 14)] + [float(-i) for i in range(14, 21)]
    ranks = _average_ranks([abs(v) for v in vals])
    w_obs = sum(r for v, r in zip(vals, ranks) if v > 0.0)
    p_exact = _wilcoxon_exact_two_sided(ranks, w_obs)
    p_norm = _wilcoxon_normal_two_sided(ranks, w_obs)
    assert 0.0 < p_exact < 1.0          # a real (non-degenerate) p
    assert abs(p_exact - p_norm) <= 0.03


# ---------------------------------------------------------------------------
# window_overlap_summary — interval overlap disclosure
# ---------------------------------------------------------------------------


def test_overlap_known_answer_one_pair():
    # windows [0,5) [1,6) [10,15): pair (0,1) overlaps; max concurrent = 2
    out = window_overlap_summary([0, 1, 10], window_length=5)
    assert out["status"] == "ok"
    assert out["n_windows"] == 3
    assert out["overlapping_pairs"] == 1
    assert out["max_concurrent"] == 2
    assert out["fraction_in_overlap"] == pytest.approx(2.0 / 3.0, abs=1e-9)


def test_overlap_none_when_spaced():
    out = window_overlap_summary([0, 10, 20], window_length=5)
    assert out["overlapping_pairs"] == 0
    assert out["max_concurrent"] == 1
    assert out["fraction_in_overlap"] == pytest.approx(0.0)


def test_overlap_all_same_date():
    out = window_overlap_summary([5, 5, 5], window_length=1)
    assert out["overlapping_pairs"] == 3  # C(3,2)
    assert out["max_concurrent"] == 3
    assert out["fraction_in_overlap"] == pytest.approx(1.0)


def test_overlap_empty_is_insufficient():
    out = window_overlap_summary([], window_length=5)
    assert out["status"] == "insufficient_n"
    assert out["n_windows"] == 0


def test_overlap_bad_window_length_raises():
    with pytest.raises(ValueError):
        window_overlap_summary([1, 2, 3], window_length=0)


# ---------------------------------------------------------------------------
# sar_convention_summary — SAR-level convention delta (report-only)
# ---------------------------------------------------------------------------


def test_sar_convention_h1_zero_delta():
    # At h=1 BHAR == CAR by construction -> SAR delta 0.
    out = sar_convention_summary(
        [{"horizon": 1, "abnormal_return": 0.02, "car": 0.02, "sigma_ar_daily": 0.01}]
    )
    assert out["status"] == "ok"
    assert out["conventions_match"] is False
    assert out["numerator_convention"] == "bhar_compounded"
    h = out["per_horizon"][0]
    assert h["horizon"] == 1
    assert h["n"] == 1
    assert h["mean_sar_delta"] == pytest.approx(0.0, abs=1e-12)
    assert h["max_abs_sar_delta"] == pytest.approx(0.0, abs=1e-12)
    # per-row example preserved for external anchoring
    assert h["example"]["sar_bhar"] == pytest.approx(2.0, abs=1e-9)
    assert h["example"]["sar_car"] == pytest.approx(2.0, abs=1e-9)


def test_sar_convention_h5_nonzero_delta():
    # sigma=0.01, h=5 -> sigma*sqrt(5)=0.022360679...
    # sar_bhar = 0.05/0.0223607 = 2.2360679..., sar_car = 0.045/0.0223607 = 2.0124612...
    out = sar_convention_summary(
        [{"horizon": 5, "abnormal_return": 0.05, "car": 0.045, "sigma_ar_daily": 0.01}]
    )
    h = out["per_horizon"][0]
    denom = 0.01 * math.sqrt(5)
    assert h["mean_sar_delta"] == pytest.approx((0.05 - 0.045) / denom, abs=1e-9)
    assert h["example"]["sar_bhar"] == pytest.approx(0.05 / denom, abs=1e-9)
    assert h["example"]["sar_car"] == pytest.approx(0.045 / denom, abs=1e-9)


def test_sar_convention_aggregates_multiple_events_per_horizon():
    # Two events at h=5; aggregate the convention gap across them.
    denom = 0.01 * math.sqrt(5)
    out = sar_convention_summary([
        {"horizon": 5, "abnormal_return": 0.05, "car": 0.045, "sigma_ar_daily": 0.01},
        {"horizon": 5, "abnormal_return": 0.03, "car": 0.030, "sigma_ar_daily": 0.01},
    ])
    h = out["per_horizon"][0]
    assert h["n"] == 2
    d1 = (0.05 - 0.045) / denom
    d2 = 0.0
    assert h["mean_sar_delta"] == pytest.approx((d1 + d2) / 2.0, abs=1e-9)
    assert h["max_abs_sar_delta"] == pytest.approx(abs(d1), abs=1e-9)


def test_sar_convention_empty_not_applicable():
    out = sar_convention_summary([])
    assert out["status"] == "not_applicable"


def test_sar_convention_skips_bad_sigma():
    out = sar_convention_summary(
        [{"horizon": 1, "abnormal_return": 0.02, "car": 0.02, "sigma_ar_daily": 0.0}]
    )
    assert out["status"] == "not_applicable"


# ---------------------------------------------------------------------------
# non_claims + orchestrator
# ---------------------------------------------------------------------------


def test_non_claims_cover_independence_and_fdr():
    blob = " ".join(ROBUST_DIAGNOSTICS_NON_CLAIMS).lower()
    assert "independ" in blob          # independence caveat
    assert "overlap" in blob           # overlap is the actual hardening
    assert "single-event" in blob or "single event" in blob
    assert "fdr" in blob               # frozen pools untouched
    assert all(isinstance(s, str) and s for s in ROBUST_DIAGNOSTICS_NON_CLAIMS)


def test_build_diagnostics_block_reuses_denominator():
    per_horizon = {
        1: {
            "ar_values": [0.01, -0.02, 0.03, 0.04, -0.01],
            "window_starts": [0, 1, 2, 3, 4],
            "window_length": 1,
            "es_rows": [
                {"abnormal_return": 0.03, "car": 0.03, "sigma_ar_daily": 0.01},
            ],
        },
        5: {
            "ar_values": [0.05, 0.02, -0.01],
            "window_starts": [0, 1, 2],
            "window_length": 5,
            "es_rows": [
                {"abnormal_return": 0.05, "car": 0.045, "sigma_ar_daily": 0.01},
            ],
        },
    }
    block = build_diagnostics_block(per_horizon)
    assert "horizons" in block and "sar_convention" in block
    assert isinstance(block["non_claims"], (list, tuple)) and block["non_claims"]
    h1 = block["horizons"]["1"]
    # sign-test n + overlap n match the input denominator (no third denominator)
    assert h1["sign_test"]["n"] == 5
    assert h1["overlap"]["n_windows"] == 5
    assert "rank_test" in h1
    # SAR convention assembled across horizons (both 1 and 5 present)
    assert block["sar_convention"]["status"] == "ok"
    sar_h = {r["horizon"] for r in block["sar_convention"]["per_horizon"]}
    assert sar_h == {1, 5}


def test_overlap_disclosure_known_dates():
    # 3 consecutive business days (Mon/Tue/Wed). At horizon 5 all three
    # windows overlap; at horizon 1 the half-open windows merely abut.
    out = build_overlap_disclosure(
        ["2026-03-02", "2026-03-03", "2026-03-04"],
        denominator_label="test_universe",
    )
    assert out["denominator"] == "test_universe"
    assert out["n_with_date"] == 3
    assert out["n_without_date"] == 0
    assert out["n_distinct_event_dates"] == 3
    h5 = out["horizons"]["5"]
    assert h5["overlapping_pairs"] == 3
    assert h5["max_concurrent"] == 3
    assert h5["fraction_in_overlap"] == pytest.approx(1.0)
    assert out["horizons"]["1"]["overlapping_pairs"] == 0


def test_overlap_disclosure_drops_unparseable_dates():
    out = build_overlap_disclosure(
        ["2026-03-02", None, "not-a-date", "2026-03-03"],
        denominator_label="u",
    )
    assert out["n_with_date"] == 2
    assert out["n_without_date"] == 2
    assert out["n_distinct_event_dates"] == 2


def test_overlap_disclosure_counts_distinct_dates():
    out = build_overlap_disclosure(
        ["2026-03-02", "2026-03-02"], denominator_label="u",
    )
    assert out["n_with_date"] == 2
    assert out["n_distinct_event_dates"] == 1
    h1 = out["horizons"]["1"]
    assert h1["overlapping_pairs"] == 1      # identical windows
    assert h1["max_concurrent"] == 2
    assert h1["fraction_in_overlap"] == pytest.approx(1.0)


def test_overlap_disclosure_empty_is_insufficient():
    out = build_overlap_disclosure([], denominator_label="u")
    assert out["n_with_date"] == 0
    assert out["n_distinct_event_dates"] == 0
    assert out["horizons"]["5"]["status"] == "insufficient_n"
    assert isinstance(out["caveat"], str) and out["caveat"]


def test_overlap_disclosure_caveat_flags_independence():
    out = build_overlap_disclosure(["2026-03-02"], denominator_label="u")
    cav = out["caveat"].lower()
    assert "overlap" in cav
    assert "independ" in cav


def test_build_diagnostics_block_handles_empty_horizon():
    block = build_diagnostics_block(
        {1: {"ar_values": [], "window_starts": [], "window_length": 1,
             "es_rows": []}}
    )
    h1 = block["horizons"]["1"]
    assert h1["sign_test"]["status"] == "insufficient_n"
    assert h1["overlap"]["status"] == "insufficient_n"
    assert block["sar_convention"]["status"] == "not_applicable"


# ---------------------------------------------------------------------------
# C1 — independent-window capacity diagnostic (unittest-style so it runs under
# ``python -m unittest`` too; pytest collects TestCase classes natively).
# ---------------------------------------------------------------------------

import itertools  # noqa: E402
import json  # noqa: E402
import unittest  # noqa: E402

import stats.robust_diagnostics as rd  # noqa: E402


def _brute_components(starts, length):
    """Brute-force connected overlap components over half-open windows."""
    n = len(starts)
    iv = [(s, s + length) for s in starts]
    adj = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if iv[i][0] < iv[j][1] and iv[j][0] < iv[i][1]:
                adj[i].add(j)
                adj[j].add(i)
    seen, comps = set(), []
    for i in range(n):
        if i in seen:
            continue
        stack, comp = [i], set()
        while stack:
            k = stack.pop()
            if k in comp:
                continue
            comp.add(k)
            stack.extend(adj[k] - comp)
        seen |= comp
        comps.append(len(comp))
    return len(comps), (max(comps) if comps else 0)


def _brute_max_non_overlapping(starts, length):
    """Brute-force optimum count of mutually non-overlapping windows."""
    n = len(starts)
    for r in range(n, 0, -1):
        for combo in itertools.combinations(range(n), r):
            ok = True
            for a, b in itertools.combinations(combo, 2):
                if (starts[a] < starts[b] + length
                        and starts[b] < starts[a] + length):
                    ok = False
                    break
            if ok:
                return r
    return 0


class TestIndependentWindowCapacity(unittest.TestCase):
    def test_disjoint_windows_full_capacity(self):
        out = rd.independent_window_summary([0, 10, 20], window_length=5)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["nominal_n"], 3)
        self.assertEqual(out["overlap_cluster_count"], 3)
        self.assertEqual(out["largest_overlap_cluster_size"], 1)
        self.assertEqual(out["max_non_overlapping_windows"], 3)

    def test_identical_dates_collapse_to_one(self):
        out = rd.independent_window_summary([7, 7, 7], window_length=5)
        self.assertEqual(out["overlap_cluster_count"], 1)
        self.assertEqual(out["largest_overlap_cluster_size"], 3)
        self.assertEqual(out["max_non_overlapping_windows"], 1)

    def test_chain_overlap_single_cluster_capacity_two(self):
        # A=[0,5) overlaps B=[3,8); B overlaps C=[6,11); A does NOT overlap C.
        out = rd.independent_window_summary([0, 3, 6], window_length=5)
        self.assertEqual(out["overlap_cluster_count"], 1)
        self.assertEqual(out["largest_overlap_cluster_size"], 3)
        self.assertEqual(out["max_non_overlapping_windows"],
                         _brute_max_non_overlapping([0, 3, 6], 5))
        self.assertEqual(out["max_non_overlapping_windows"], 2)

    def test_mixed_clusters_counted(self):
        starts = [0, 3, 100, 200, 203, 206]
        out = rd.independent_window_summary(starts, window_length=5)
        self.assertEqual(out["overlap_cluster_count"], 3)
        self.assertEqual(out["largest_overlap_cluster_size"], 3)
        self.assertEqual(out["max_non_overlapping_windows"], 4)

    def test_matches_bruteforce_on_fixtures(self):
        fixtures = [
            ([0, 1, 2, 3, 4], 1),
            ([0, 1, 2, 3, 4], 2),
            ([0, 2, 4, 6, 8, 10], 3),
            ([5, 5, 9, 14, 14, 30], 5),
            ([0, 4, 5, 9, 10, 14, 15], 5),
            ([0, 19, 3, 7, 22, 41, 40], 20),
        ]
        for starts, length in fixtures:
            out = rd.independent_window_summary(starts, window_length=length)
            bc, bl = _brute_components(starts, length)
            self.assertEqual(out["overlap_cluster_count"], bc,
                             (starts, length))
            self.assertEqual(out["largest_overlap_cluster_size"], bl,
                             (starts, length))
            self.assertEqual(out["max_non_overlapping_windows"],
                             _brute_max_non_overlapping(starts, length),
                             (starts, length))

    def test_empty_input_safe(self):
        out = rd.independent_window_summary([], window_length=5)
        self.assertEqual(out["status"], "insufficient_n")
        self.assertEqual(out["nominal_n"], 0)
        self.assertEqual(out["overlap_cluster_count"], 0)
        self.assertEqual(out["largest_overlap_cluster_size"], 0)
        self.assertEqual(out["max_non_overlapping_windows"], 0)
        diag = rd.independent_window_diagnostic([], window_length=5)
        self.assertFalse(diag["meets_min_independent_window_gate"])

    def test_duplicates_and_order_deterministic(self):
        a = rd.independent_window_summary([9, 2, 2, 30, 9], window_length=5)
        b = rd.independent_window_summary([2, 9, 30, 2, 9], window_length=5)
        self.assertEqual(a, b)

    def test_bad_window_length_raises(self):
        for bad in (0, -1, True, "5", None):
            with self.assertRaises(ValueError):
                rd.independent_window_summary([1, 2], window_length=bad)

    def test_gate_fields_and_source(self):
        # 9 fully disjoint windows -> capacity 9 >= 8 gate.
        meets = rd.independent_window_diagnostic(
            [i * 10 for i in range(9)], window_length=5)
        self.assertEqual(meets["min_independent_window_gate"], 8)
        self.assertTrue(meets["meets_min_independent_window_gate"])
        self.assertIn("METHODOLOGY", meets["gate_source"])
        below = rd.independent_window_diagnostic([0, 1, 2], window_length=5)
        self.assertFalse(below["meets_min_independent_window_gate"])

    def test_overlap_disclosure_gains_diagnostic_additively(self):
        dates = ["2026-03-02", "2026-03-03", "2026-03-20", "2026-04-10"]
        out = rd.build_overlap_disclosure(dates, denominator_label="unit")
        for h in ("1", "5", "20"):
            block = out["horizons"][h]
            # existing overlap fields unchanged
            for key in ("status", "n_windows", "window_length",
                        "overlapping_pairs", "max_concurrent",
                        "fraction_in_overlap"):
                self.assertIn(key, block, key)
            diag = block["independent_window_diagnostic"]
            for key in ("nominal_n", "overlap_cluster_count",
                        "largest_overlap_cluster_size",
                        "max_non_overlapping_windows",
                        "min_independent_window_gate",
                        "meets_min_independent_window_gate",
                        "interpretation_note", "non_claim"):
                self.assertIn(key, diag, key)
            self.assertEqual(diag["nominal_n"], block["n_windows"])
        # top-level disclosure fields unchanged
        for key in ("denominator", "n_with_date", "n_without_date",
                    "n_distinct_event_dates", "window_length_basis",
                    "caveat"):
            self.assertIn(key, out, key)

    def test_diagnostics_block_gains_diagnostic_additively(self):
        block = rd.build_diagnostics_block(
            {5: {"ar_values": [0.01, -0.02], "window_starts": [10, 12],
                 "window_length": 5, "es_rows": []}})
        h5 = block["horizons"]["5"]
        self.assertIn("overlap", h5)
        self.assertIn("independent_window_diagnostic", h5)
        self.assertEqual(
            h5["independent_window_diagnostic"]["nominal_n"],
            h5["overlap"]["n_windows"])

    def test_wording_discipline(self):
        diag = rd.independent_window_diagnostic([0, 3, 6, 40],
                                                window_length=5)
        blob = json.dumps(diag).lower()
        self.assertNotIn("statistically significant", blob)
        self.assertNotIn("proves", blob)
        self.assertNotIn("proven", blob)
        self.assertNotIn("trading signal", blob)
        self.assertNotIn("alpha", blob)
        # 'effective sample size' allowed ONLY in the caveated 'not a true
        # statistical ...' form.
        idx = blob.find("effective sample size")
        while idx != -1:
            prefix = blob[max(0, idx - 40):idx]
            self.assertIn("not a true statistical", prefix)
            idx = blob.find("effective sample size", idx + 1)
        # 'validat*' only in negated form.
        if "validat" in blob:
            self.assertIn("does not validate", blob)

    def test_interpretation_says_does_not_unblock(self):
        diag = rd.independent_window_diagnostic(
            [i * 10 for i in range(9)], window_length=5)
        note = diag["interpretation_note"].lower()
        self.assertIn("does not", note)
        self.assertIn("cohort", note)
        nc = diag["non_claim"].lower()
        self.assertIn("not a true statistical", nc)
        self.assertIn("pool", nc)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
