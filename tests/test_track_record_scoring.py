"""Tests for stats.track_record_scoring — track-record scoring-rule sensitivity.

Pure scoring logic only (no DB). The rules recompute the accepted track-record
outcome under transparent alternatives to the canonical generous ANY-support
rule. No rule is claimed "correct"; this is disclosure, not a truth claim.
"""
from __future__ import annotations

import pytest

from stats.track_record_scoring import (
    SCORING_NON_CLAIMS,
    event_evidence,
    normalize_ticker,
    score_event_under_rule,
    summarize_rules,
)


def _sup(weight_key=None):
    t = {"symbol": "AAA", "direction_tag": "supports ↑"}
    if weight_key:
        t["evidence_quality"] = weight_key
    return t


def _con(weight_key=None):
    t = {"symbol": "BBB", "direction_tag": "contradicts ↓"}
    if weight_key:
        t["evidence_quality"] = weight_key
    return t


# ---------------------------------------------------------------------------
# Per-ticker normalization
# ---------------------------------------------------------------------------


def test_normalize_supports_tag_default_weight():
    assert normalize_ticker({"direction_tag": "supports ↑"}) == ("support", 1.0)


def test_normalize_contradicts_tag_default_weight():
    assert normalize_ticker({"direction_tag": "contradicts ↓"}) == ("contradict", 1.0)


def test_normalize_revisit_direction_key():
    # revisit snapshots carry ``direction`` rather than ``direction_tag``
    assert normalize_ticker({"direction": "supports ↑"})[0] == "support"


def test_normalize_evidence_tier_weight():
    assert normalize_ticker(_sup("low")) == ("support", 0.15)
    assert normalize_ticker(_sup("provisional")) == ("support", 0.5)
    assert normalize_ticker(_sup("high")) == ("support", 1.0)


def test_normalize_missing_or_garbage_tag_is_neutral():
    assert normalize_ticker({"symbol": "Z"})[0] == "neutral"
    assert normalize_ticker({"direction_tag": ""})[0] == "neutral"
    assert normalize_ticker("not-a-dict")[0] == "neutral"


def test_event_evidence_counts_and_weights():
    ev = event_evidence([_sup(), _con(), _con(), {"direction_tag": ""}])
    assert ev["sup_n"] == 1
    assert ev["con_n"] == 2
    assert ev["dir_n"] == 3
    assert ev["mixed"] is True
    assert ev["sup_w"] == pytest.approx(1.0)
    assert ev["con_w"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Rule A — any_support (must match canonical generous OR-rule)
# ---------------------------------------------------------------------------


def test_any_support_one_support_three_contradict_is_validated():
    tickers = [_sup(), _con(), _con(), _con()]
    assert score_event_under_rule(tickers, "any_support") == "validated"


def test_any_support_only_contradictions_is_contradicted():
    assert score_event_under_rule([_con(), _con()], "any_support") == "contradicted"


def test_any_support_no_direction_is_unresolved():
    assert score_event_under_rule([{"direction_tag": ""}], "any_support") == "unresolved"


# ---------------------------------------------------------------------------
# Rule B — majority
# ---------------------------------------------------------------------------


def test_majority_two_support_one_contradict_is_validated():
    assert score_event_under_rule([_sup(), _sup(), _con()], "majority") == "validated"


def test_majority_one_support_three_contradict_is_contradicted():
    assert score_event_under_rule([_sup(), _con(), _con(), _con()], "majority") == "contradicted"


def test_majority_tie_is_unresolved():
    assert score_event_under_rule([_sup(), _con()], "majority") == "unresolved"


def test_majority_no_direction_is_unresolved():
    assert score_event_under_rule([{"direction_tag": ""}], "majority") == "unresolved"


# ---------------------------------------------------------------------------
# Rule C — evidence_weighted
# ---------------------------------------------------------------------------


def test_evidence_weighted_low_support_loses_to_high_contradiction():
    # one low-quality supporter (0.15) vs one high-quality contradictor (1.0)
    tickers = [_sup("low"), _con("high")]
    assert score_event_under_rule(tickers, "evidence_weighted") == "contradicted"


def test_evidence_weighted_high_support_beats_low_contradiction():
    tickers = [_sup("high"), _con("low")]
    assert score_event_under_rule(tickers, "evidence_weighted") == "validated"


def test_evidence_weighted_equal_weight_tie_is_unresolved():
    assert score_event_under_rule([_sup("high"), _con("high")], "evidence_weighted") == "unresolved"


def test_evidence_weighted_default_weights_equal_majority():
    # No per-ticker tier -> all weight 1.0 -> identical to majority.
    tickers = [_sup(), _sup(), _con()]
    assert (
        score_event_under_rule(tickers, "evidence_weighted")
        == score_event_under_rule(tickers, "majority")
        == "validated"
    )


# ---------------------------------------------------------------------------
# Rule D — all_support_strict
# ---------------------------------------------------------------------------


def test_strict_all_support_no_contradiction_is_validated():
    assert score_event_under_rule([_sup(), _sup()], "all_support_strict") == "validated"


def test_strict_any_contradiction_is_contradicted():
    assert score_event_under_rule([_sup(), _sup(), _con()], "all_support_strict") == "contradicted"


def test_strict_no_direction_is_unresolved():
    assert score_event_under_rule([{"direction_tag": ""}], "all_support_strict") == "unresolved"


def test_unknown_rule_raises():
    with pytest.raises(ValueError):
        score_event_under_rule([_sup()], "made_up_rule")


# ---------------------------------------------------------------------------
# summarize_rules — denominator stability + deltas + composition
# ---------------------------------------------------------------------------


def _records():
    # e1: 1 sup / 3 con  -> any=validated, majority/weighted/strict=contradicted
    # e2: 2 sup / 0 con  -> validated under ALL rules (agrees everywhere)
    # e3: no direction   -> unresolved under ALL rules
    return [
        {"event_id": 1, "mechanism_family": "tariff", "headline": "h1",
         "tickers": [_sup(), _con(), _con(), _con()]},
        {"event_id": 2, "mechanism_family": "sanction", "headline": "h2",
         "tickers": [_sup(), _sup()]},
        {"event_id": 3, "mechanism_family": "none", "headline": "h3",
         "tickers": [{"direction_tag": ""}]},
    ]


def test_summarize_denominator_is_stable_across_rules():
    out = summarize_rules(_records())
    assert out["denominator"] == 3
    for rule in ("any_support", "majority", "evidence_weighted", "all_support_strict"):
        r = out["rules"][rule]
        assert r["validated"] + r["contradicted"] + r["unresolved"] == 3


def test_summarize_any_support_split():
    out = summarize_rules(_records())
    a = out["rules"]["any_support"]
    assert (a["validated"], a["contradicted"], a["unresolved"]) == (2, 0, 1)


def test_summarize_majority_changes_e1_to_contradicted():
    out = summarize_rules(_records())
    m = out["rules"]["majority"]
    assert (m["validated"], m["contradicted"], m["unresolved"]) == (1, 1, 1)
    assert m["changed_vs_any_support"] == 1


def test_summarize_evidence_weighted_equals_majority_with_no_weights():
    out = summarize_rules(_records())
    ew = out["rules"]["evidence_weighted"]
    assert ew["changed_vs_majority"] == 0  # the reported degeneracy


def test_summarize_disagreements_list_names_changed_event():
    out = summarize_rules(_records())
    ids = {d["event_id"] for d in out["disagreements"]}
    assert 1 in ids  # e1 flips under majority/strict
    assert 2 not in ids  # e2 agrees across rules


def test_summarize_composition_counts():
    out = summarize_rules(_records())
    comp = out["composition"]
    assert comp["multi_ticker"] == 2     # e1 (4 dir), e2 (2 dir)
    assert comp["no_direction"] == 1     # e3
    assert comp["mixed_evidence"] == 1   # only e1 has both sup and con


def test_summarize_non_claims_present_and_no_correct_rule_claim():
    out = summarize_rules(_records())
    assert out["non_claims"]
    blob = " ".join(out["non_claims"]).lower()
    assert "correct" in blob  # explicitly disclaims a "correct" rule
    assert "significance" in blob
