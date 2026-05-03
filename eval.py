# eval.py
# Runs the sample headline set through the current non-interactive flow and
# saves the results to a readable JSON file for manual review.
#
# Usage:
#   python eval.py
#   python eval.py --preset canary
#   python eval.py --ids sample_001 sample_005
#   python eval.py --limit 6
#
# This helper does not call main() and does not write to the database.
# Each run writes a timestamped eval_output_*.json file.

import argparse
import glob
import json
import os
import re
from datetime import datetime

SAMPLE_FILE = "sample_events.json"
EVAL_RUN_INDEX_FILE = "eval_run_index.json"
ENGINE_PHASE_PARITY_FIELDS = (
    "mechanism_subtype",
    "actionability_check",
    "counterfactual_check",
    "quality_warnings",
    "proof_status",
    "falsifier_status",
    "thesis_state",
    "thesis_state_reason",
    "validation_rationale",
    "evidence_sources",
)

# Quality scoring weights used by _quality_score() below.
# Each check contributes an integer toward a 0..10 score so a human
# reviewer can eyeball before/after runs without reading every analysis.
QUALITY_CHECKS = (
    "mechanism_length_ok",          # mechanism_summary >= 100 chars and not "insufficient evidence"
    "transmission_chain_depth_ok",  # >= 3 distinct steps
    "beneficiary_tickers_ok",       # >= 2 tickers
    "loser_tickers_ok",             # >= 1 ticker
    "both_entities_populated",      # beneficiaries and losers both non-empty
    "if_persists_horizon_ok",       # has an enum horizon
    "currency_channel_complete",    # pair + mechanism both populated, or cleanly null
    "no_validation_warnings",       # validator left the result untouched
    "not_degraded",                 # degraded fallback did not fire
    "specific_what_changed",        # what_changed non-trivial (>= 40 chars, no vague filler)
)
ENGINE_QUALITY_FIELDS = (
    "primary_thesis_present",
    "alternative_thesis_present",
    "discriminator_present",
    "mechanism_family",
    "low_information",
    "asset_why_lines_present",
    "transmission_chain_valid",
    "proof_set_count",
    "falsifier_count",
    "thesis_asset_consistent",
    "thesis_proof_consistent",
    "thesis_falsifier_consistent",
    "chain_ends_in_asset_implication",
    "rejected_asset_count",
    "quality_tier",
    "high_confidence_without_proof",
    "actionable_without_valid_chain",
    "actionable_without_asset_rationale",
    "actionable_with_family_none",
    "low_information_but_has_assets",
    "causal_strength",
    "causal_trigger_present",
    "causal_channel_present",
    "pricing_relationship_present",
    "asset_implication_present",
    "regime_caveats_present",
    "regime_caveats_concrete",
    "primary_asset_count",
    "secondary_asset_count",
    "signal_asset_count",
    "beneficiary_signal_conflict",
    "role_channel_mismatch_count",
    "first_order_present",
    "second_order_count",
    "second_order_has_bridge",
    "second_order_skipped_channel",
    "expected_direction_present",
    "signal_asset_direction_valid",
    "family_chain_consistent",
    "generic_chain_hops_count",
    "chain_asset_implication_present",
    "coherence_rejection_triggered",
    "primary_asset_contradiction_count",
    "weak_signal_only_support",
    "mechanism_subtype_present",
    "subtype_family_consistent",
    "proxy_eligibility_present",
    "rejected_proxy_count",
    "low_channel_match_count",
    "high_noise_proxy_count",
    # Subtype normalization + proxy-eligibility diagnostics added by
    # the eval-side normalization pass.  All six default to false / 0
    # cleanly when the underlying engine fields are absent.
    "mechanism_subtype_valid",
    "subtype_dropped_or_warned",
    "primary_weighted_assets_count",
    "rejected_assets_excluded_from_validation",
    "signal_assets_channel_bound",
    "high_noise_override_detected",
    "confidence_rationale_present",
    "confidence_rationale_concrete",
    "thesis_state_present",
    "validation_rationale_present",
    "validation_rationale_concrete",
    "actionability_check_shaped",
    "counterfactual_check_present",
    "counterfactual_check_shaped",
    "counterfactual_evidence_count",
    "proof_status_shaped",
    "proof_status_item_count",
    "falsifier_status_shaped",
    "falsifier_status_item_count",
    "evidence_sources_shaped",
    "rationale_too_generic",
    "actionability_present",
    "tradable_true_without_confirmation",
    "low_info_marked_tradable",
    "market_macro_conflict_detected",
    "conflict_reason_present",
    "actionability_risk_level_present",
    "invalidation_trigger_present",
    "evidence_sources_present",
    "evidence_sources_concrete",
    "weak_traceability_but_high_confidence",
)
# Chosen to cover key V1.5 stage/category patterns at low API cost:
# anticipation, realized, escalation, de-escalation, normalization,
# sanctions/energy, and a central-bank case.
CANARY_SAMPLE_IDS = [
    "sample_001",
    "sample_004",
    "sample_007",
    "sample_011",
    "sample_015",
    "sample_018",
]
TARGETED_ENGINE_SAMPLE_IDS = [
    "sample_021",
    "sample_022",
    "sample_023",
    "sample_024",
    "sample_025",
    "sample_026",
    "sample_027",
    "sample_028",
    "sample_029",
    "sample_030",
]


def parse_args() -> argparse.Namespace:
    """Parse lightweight CLI options for cheaper evaluation subsets."""
    parser = argparse.ArgumentParser(
        description="Run the sample evaluation set and save a timestamped eval_output_*.json file.",
    )
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument(
        "--preset",
        choices=[
            "all",
            "canary",
            "engine-next",
            "targeted",
            "low-information",
            "mechanism-family",
        ],
        help="Run a named representative subset instead of the full sample set.",
    )
    selector.add_argument(
        "--ids",
        nargs="+",
        help="Run only the specified sample IDs, preserving the order given.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Run only the first N samples after preset/ID selection.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Anthropic model ID to use (overrides ANTHROPIC_MODEL env var). "
             "E.g. claude-haiku-4-5-20251001 for faster/cheaper runs.",
    )
    parser.add_argument(
        "--compare-latest",
        action="store_true",
        help="Compare the two newest timestamped eval outputs and exit.",
    )
    return parser.parse_args()


def load_samples() -> list[dict]:
    """Load sample headlines from the JSON input file."""
    with open(SAMPLE_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def make_output_file(now: datetime | None = None) -> str:
    """Return a timestamped eval output filename."""
    if now is None:
        now = datetime.now()
    return f"eval_output_{now.strftime('%Y%m%d_%H%M%S')}.json"


def _unique_ids(ids: list[str]) -> list[str]:
    """Return IDs with duplicates removed while preserving input order."""
    seen = set()
    ordered = []
    for sample_id in ids:
        if sample_id not in seen:
            seen.add(sample_id)
            ordered.append(sample_id)
    return ordered


def _expected_eval_focus(sample: dict) -> dict:
    focus = sample.get("expected_eval_focus")
    return focus if isinstance(focus, dict) else {}


def _targeted_engine_ids(samples: list[dict]) -> list[str]:
    return [
        sample["id"]
        for sample in samples
        if _expected_eval_focus(sample)
    ]


def _low_information_ids(samples: list[dict]) -> list[str]:
    return [
        sample["id"]
        for sample in samples
        if _expected_eval_focus(sample).get("should_be_low_information") is True
    ]


def _mechanism_family_ids(samples: list[dict]) -> list[str]:
    ids: list[str] = []
    for sample in samples:
        family = str(
            _expected_eval_focus(sample).get("mechanism_family") or ""
        ).strip().lower()
        if family and family != "none":
            ids.append(sample["id"])
    return ids


def _preset_ids(samples: list[dict], preset: str | None) -> list[str] | None:
    if preset in (None, "all"):
        return None
    if preset == "canary":
        return CANARY_SAMPLE_IDS
    if preset in {"engine-next", "targeted"}:
        return _targeted_engine_ids(samples)
    if preset == "low-information":
        return _low_information_ids(samples)
    if preset == "mechanism-family":
        return _mechanism_family_ids(samples)
    return None


def select_samples(
    samples: list[dict],
    preset: str | None = None,
    ids: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Select all samples or a smaller subset based on CLI options."""
    if limit is not None and limit < 1:
        raise ValueError("--limit must be at least 1.")

    preset_ids = _preset_ids(samples, preset)
    if preset_ids is not None:
        ids = preset_ids

    if ids:
        sample_map = {sample["id"]: sample for sample in samples}
        selected_ids = _unique_ids(ids)
        missing_ids = [sample_id for sample_id in selected_ids if sample_id not in sample_map]
        if missing_ids:
            raise ValueError(
                "Unknown sample ID(s): " + ", ".join(missing_ids)
            )
        selected = [sample_map[sample_id] for sample_id in selected_ids]
    else:
        selected = list(samples)

    if limit is not None:
        selected = selected[:limit]

    return selected


def selected_sample_ids(samples: list[dict]) -> list[str]:
    return [sample["id"] for sample in samples]


def skipped_sample_ids(samples: list[dict], selected: list[dict]) -> list[str]:
    selected_ids = set(selected_sample_ids(selected))
    return [
        sample["id"]
        for sample in samples
        if sample["id"] not in selected_ids
    ]


def _quality_score(analysis: dict) -> dict:
    """Score a single analysis dict against the QUALITY_CHECKS rubric.

    Returns a small breakdown dict plus a total 0..10 score so runs can be
    diffed cheaply without re-reading every field by eye.
    """
    mechanism = (analysis.get("mechanism_summary") or "").strip()
    mechanism_length_ok = (
        len(mechanism) >= 100
        and "insufficient evidence" not in mechanism.lower()
    )

    chain = analysis.get("transmission_chain") or []
    chain_depth_ok = isinstance(chain, list) and len(chain) >= 3

    ben_tickers = analysis.get("beneficiary_tickers") or []
    los_tickers = analysis.get("loser_tickers") or []
    beneficiary_tickers_ok = isinstance(ben_tickers, list) and len(ben_tickers) >= 2
    loser_tickers_ok = isinstance(los_tickers, list) and len(los_tickers) >= 1

    beneficiaries = analysis.get("beneficiaries") or []
    losers = analysis.get("losers") or []
    both_entities_populated = bool(beneficiaries) and bool(losers)

    if_persists = analysis.get("if_persists") or {}
    if_persists_horizon_ok = bool(if_persists.get("horizon"))

    cc = analysis.get("currency_channel") or {}
    # Either both pair and mechanism are populated, or both are None (the
    # model correctly declared there is no FX channel).
    cc_pair = cc.get("pair")
    cc_mech = cc.get("mechanism")
    currency_channel_complete = (
        (bool(cc_pair) and bool(cc_mech))
        or (cc_pair in (None, "") and cc_mech in (None, ""))
    )

    warnings = analysis.get("validation_warnings") or []
    no_validation_warnings = not warnings

    not_degraded = not analysis.get("degraded")

    what_changed = (analysis.get("what_changed") or "").strip().lower()
    vague_markers = ("various", "multiple", "the market", "investors", "unknown")
    specific_what_changed = (
        len(what_changed) >= 40
        and not any(marker in what_changed for marker in vague_markers)
    )

    breakdown = {
        "mechanism_length_ok": mechanism_length_ok,
        "transmission_chain_depth_ok": chain_depth_ok,
        "beneficiary_tickers_ok": beneficiary_tickers_ok,
        "loser_tickers_ok": loser_tickers_ok,
        "both_entities_populated": both_entities_populated,
        "if_persists_horizon_ok": if_persists_horizon_ok,
        "currency_channel_complete": currency_channel_complete,
        "no_validation_warnings": no_validation_warnings,
        "not_degraded": not_degraded,
        "specific_what_changed": specific_what_changed,
    }
    score = sum(1 for ok in breakdown.values() if ok)
    return {"score": score, "max_score": len(QUALITY_CHECKS), "breakdown": breakdown}


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _count_list(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _ranked_asset_entries(analysis: dict) -> list[dict]:
    entries: list[dict] = []
    for key in (
        "primary_assets",
        "secondary_assets",
        "hedge_or_signal_assets",
        "assets_to_watch",
    ):
        bucket = analysis.get(key)
        if not isinstance(bucket, list):
            continue
        entries.extend(item for item in bucket if isinstance(item, dict))
    return entries


def _asset_why_lines_present(analysis: dict) -> bool:
    """Return True when at least one asset carries a non-trivial rationale."""
    for entry in _ranked_asset_entries(analysis):
        why = (
            entry.get("rationale")
            or entry.get("reason")
            or entry.get("why")
            or entry.get("why_it_matters")
        )
        if _non_empty_text(why) and len(str(why).strip()) >= 10:
            return True
    return False


def _transmission_chain_valid(analysis: dict) -> bool:
    chain = analysis.get("transmission_chain")
    if not isinstance(chain, list) or len(chain) < 3:
        return False
    return all(_non_empty_text(step) for step in chain)


def _consistency_audit(analysis: dict) -> dict:
    """Read the engine's non-mutating consistency audit when available."""
    empty = {"checked": 0, "dropped": 0, "per_field": {}}
    try:
        from low_information_gate import evaluate_consistency
        audit = evaluate_consistency(analysis)
    except Exception:
        return empty
    return audit if isinstance(audit, dict) else empty


def _fields_consistent(audit: dict, field_names: tuple[str, ...]) -> bool:
    per_field = audit.get("per_field")
    if not isinstance(per_field, dict):
        return False
    checked = 0
    dropped = 0
    for field in field_names:
        stats = per_field.get(field)
        if not isinstance(stats, dict):
            continue
        checked += int(stats.get("checked") or 0)
        dropped += int(stats.get("dropped") or 0)
    return checked > 0 and dropped == 0


def _audit_dropped_count(audit: dict, field_names: tuple[str, ...]) -> int:
    per_field = audit.get("per_field")
    if not isinstance(per_field, dict):
        return 0
    total = 0
    for field in field_names:
        stats = per_field.get(field)
        if isinstance(stats, dict):
            total += int(stats.get("dropped") or 0)
    return total


def _explicit_rejected_asset_count(analysis: dict) -> int:
    total = 0
    for key in ("excluded_assets", "rejected_assets", "excluded"):
        bucket = analysis.get(key)
        if isinstance(bucket, list):
            total += len(bucket)
    return total


def _content_tokens(text: object) -> set[str]:
    if not isinstance(text, str):
        return set()
    stopwords = {
        "about", "after", "against", "also", "because", "before", "being",
        "could", "from", "into", "more", "than", "that", "their", "then",
        "there", "this", "through", "with", "would",
    }
    return {
        token
        for token in re.findall(r"[A-Za-z0-9]{3,}", text.lower())
        if token not in stopwords
    }


def _chain_ends_in_asset_implication(analysis: dict) -> bool:
    chain = analysis.get("transmission_chain")
    if not isinstance(chain, list):
        return False
    steps = [str(step).strip() for step in chain if _non_empty_text(step)]
    if len(steps) < 2:
        return False
    last_step = steps[-1]

    asset_terms: set[str] = set()
    asset_text_parts: list[str] = []
    for key in (
        "beneficiary_tickers", "loser_tickers", "assets_to_watch",
        "beneficiaries", "losers",
    ):
        bucket = analysis.get(key)
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if isinstance(item, str) and item.strip():
                asset_terms.add(item.strip().upper())
                asset_text_parts.append(item)
            elif isinstance(item, dict):
                for subkey in ("symbol", "ticker", "name", "rationale", "reason"):
                    value = item.get(subkey)
                    if isinstance(value, str) and value.strip():
                        if subkey in ("symbol", "ticker"):
                            asset_terms.add(value.strip().upper())
                        asset_text_parts.append(value)
    for entry in _ranked_asset_entries(analysis):
        for subkey in ("symbol", "ticker", "rationale", "reason"):
            value = entry.get(subkey)
            if isinstance(value, str) and value.strip():
                if subkey in ("symbol", "ticker"):
                    asset_terms.add(value.strip().upper())
                asset_text_parts.append(value)

    last_upper = last_step.upper()
    if any(term and term in last_upper for term in asset_terms):
        return True
    return bool(_content_tokens(last_step) & _content_tokens(" ".join(asset_text_parts)))


def _quality_tier(
    analysis: dict,
    quality: dict | None = None,
    *,
    low_information: bool = False,
) -> str:
    if quality is None:
        quality = _quality_score(analysis)
    score = float(quality.get("score") or 0)
    max_score = float(quality.get("max_score") or len(QUALITY_CHECKS) or 1)
    pct = score / max_score if max_score else 0.0
    if low_information or analysis.get("degraded") or pct < 0.4:
        return "poor"
    if pct < 0.6:
        return "thin"
    if pct < 0.8:
        return "usable"
    return "excellent"


def _has_any_asset_exposure(analysis: dict) -> bool:
    for key in (
        "beneficiary_tickers", "loser_tickers", "assets_to_watch",
        "primary_assets", "secondary_assets", "hedge_or_signal_assets",
    ):
        bucket = analysis.get(key)
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if isinstance(item, str) and item.strip():
                return True
            if isinstance(item, dict):
                sym = item.get("symbol") or item.get("ticker")
                if isinstance(sym, str) and sym.strip():
                    return True
    return False


def _is_actionable(analysis: dict, quality_tier: str, *, low_information: bool) -> bool:
    if low_information or analysis.get("degraded"):
        return False
    confidence = str(analysis.get("confidence") or "").strip().lower()
    return confidence in {"high", "medium"} or quality_tier in {"excellent", "usable"}


_CAUSAL_CHANNEL_WORDS = {
    "rates", "rate", "yields", "yield", "fx", "currency", "dollar",
    "commodities", "commodity", "oil", "gas", "credit", "spread",
    "equities", "equity", "margin", "supply", "demand", "capacity",
    "inventory", "funding", "volatility", "vol",
}

_PRICING_RELATIONSHIP_RE = re.compile(
    r"\b("
    r"price|prices|pricing|premium|discount|spread|margin|margins|"
    r"yield|yields|rate|rates|cost|costs|revenue|earnings|multiple|"
    r"rerat(?:e|es|ing)|reprice|reprices|repricing|"
    r"widen|widens|narrow|narrows|rise|rises|fall|falls|"
    r"increase|increases|decrease|decreases|tighten|tightens|"
    r"cheaper|costlier|outperform|underperform"
    r")\b",
    re.I,
)


def _causal_text(analysis: dict) -> str:
    parts: list[str] = []
    for key in ("what_changed", "mechanism_summary"):
        value = analysis.get(key)
        if isinstance(value, str):
            parts.append(value)
    chain = analysis.get("transmission_chain")
    if isinstance(chain, list):
        parts.extend(str(step) for step in chain if _non_empty_text(step))
    for entry in _ranked_asset_entries(analysis):
        for key in ("rationale", "reason", "why", "why_it_matters"):
            value = entry.get(key)
            if isinstance(value, str):
                parts.append(value)
    return " ".join(parts)


def _causal_trigger_present(analysis: dict) -> bool:
    what_changed = analysis.get("what_changed")
    if _non_empty_text(what_changed) and len(_content_tokens(what_changed)) >= 3:
        return True
    chain = analysis.get("transmission_chain")
    if isinstance(chain, list) and chain:
        first = next((step for step in chain if _non_empty_text(step)), "")
        return len(_content_tokens(first)) >= 3
    return False


def _causal_channel_present(analysis: dict) -> bool:
    family = str(analysis.get("mechanism_family") or "none").strip().lower()
    if family and family != "none":
        return True
    for key in ("expected_first_order_channels", "expected_second_order_channels"):
        channels = analysis.get(key)
        if isinstance(channels, list) and any(_non_empty_text(c) for c in channels):
            return True
    return bool(_content_tokens(_causal_text(analysis)) & _CAUSAL_CHANNEL_WORDS)


def _pricing_relationship_present(analysis: dict) -> bool:
    return bool(_PRICING_RELATIONSHIP_RE.search(_causal_text(analysis)))


def _asset_implication_present(analysis: dict) -> bool:
    return _chain_ends_in_asset_implication(analysis) or _asset_why_lines_present(analysis)


def _causal_strength(
    *,
    causal_trigger_present: bool,
    causal_channel_present: bool,
    pricing_relationship_present: bool,
    asset_implication_present: bool,
    transmission_chain_valid: bool,
) -> str:
    if (
        causal_trigger_present
        and causal_channel_present
        and pricing_relationship_present
        and asset_implication_present
        and transmission_chain_valid
    ):
        return "strong"
    return "weak"


_REGIME_CAVEAT_PLACEHOLDERS = {
    "",
    "no regime-conditioned caveat.",
    "no regime conditioned caveat.",
    "none",
    "n/a",
    "not applicable",
    "insufficient evidence",
}

_REGIME_WORDS = {
    "regime", "inflation", "disinflation", "growth", "recession",
    "hawkish", "dovish", "policy", "rates", "rate", "yields", "yield",
    "credit", "spreads", "spread", "stress", "stressed", "calm",
    "risk", "dollar", "liquidity", "funding", "volatility", "vol",
}

_REGIME_EFFECT_WORDS = {
    "amplify", "amplifies", "blunt", "blunts", "redirect", "redirects",
    "outweigh", "outweighs", "compress", "compresses", "extend",
    "extends", "limit", "limits", "faster", "slower", "more", "less",
    "because", "when", "if", "but", "already",
}


def _regime_caveat_text(analysis: dict) -> str:
    value = analysis.get("regime_conditioned_caveat")
    return value.strip() if isinstance(value, str) else ""


def _regime_caveats_present(analysis: dict) -> bool:
    text = _regime_caveat_text(analysis)
    return text.lower() not in _REGIME_CAVEAT_PLACEHOLDERS


def _regime_caveats_concrete(analysis: dict) -> bool:
    if not _regime_caveats_present(analysis):
        return False
    text = _regime_caveat_text(analysis)
    tokens = _content_tokens(text)
    return (
        len(tokens) >= 8
        and bool(tokens & _REGIME_WORDS)
        and bool(tokens & _REGIME_EFFECT_WORDS)
    )


def _asset_bucket_count(analysis: dict, key: str) -> int:
    bucket = analysis.get(key)
    return len(bucket) if isinstance(bucket, list) else 0


def _asset_symbols(bucket: object) -> set[str]:
    symbols: set[str] = set()
    if not isinstance(bucket, list):
        return symbols
    for item in bucket:
        if isinstance(item, str) and item.strip():
            symbols.add(item.strip().upper())
        elif isinstance(item, dict):
            sym = item.get("symbol") or item.get("ticker")
            if isinstance(sym, str) and sym.strip():
                symbols.add(sym.strip().upper())
    return symbols


def _beneficiary_signal_conflict(analysis: dict) -> bool:
    beneficiary_symbols = _asset_symbols(analysis.get("beneficiary_tickers"))
    signal_symbols = _asset_symbols(analysis.get("hedge_or_signal_assets"))
    return bool(beneficiary_symbols & signal_symbols)


def _role_channel_mismatch_count(analysis: dict) -> int:
    beneficiary_symbols = _asset_symbols(analysis.get("beneficiary_tickers"))
    loser_symbols = _asset_symbols(analysis.get("loser_tickers"))
    committed_symbols = beneficiary_symbols | loser_symbols
    signal_symbols = _asset_symbols(analysis.get("hedge_or_signal_assets"))
    mismatches = 0

    for key in ("primary_assets", "secondary_assets"):
        bucket = analysis.get(key)
        if not isinstance(bucket, list):
            continue
        for entry in bucket:
            if not isinstance(entry, dict):
                continue
            sym = str(entry.get("symbol") or entry.get("ticker") or "").strip().upper()
            if committed_symbols and sym and sym not in committed_symbols:
                mismatches += 1
                continue
            side = str(entry.get("side") or "").strip().lower()
            tier = str(entry.get("tier") or "").strip().lower()
            if side in {"signal", "hedge"} or tier == "hedge_signal":
                mismatches += 1
            elif side == "beneficiary" and sym in loser_symbols:
                mismatches += 1
            elif side == "loser" and sym in beneficiary_symbols:
                mismatches += 1

    counted_signal_conflicts: set[str] = set()
    for entry in analysis.get("hedge_or_signal_assets") or []:
        if not isinstance(entry, dict):
            continue
        sym = str(entry.get("symbol") or entry.get("ticker") or "").strip().upper()
        side = str(entry.get("side") or "").strip().lower()
        tier = str(entry.get("tier") or "").strip().lower()
        if sym and sym in committed_symbols:
            mismatches += 1
            counted_signal_conflicts.add(sym)
        elif side in {"beneficiary", "loser"}:
            mismatches += 1
        elif tier in {"direct_proxy", "sector_proxy", "second_order"}:
            mismatches += 1
    # String-only signal symbols can still conflict with committed roles.
    mismatches += len((signal_symbols & committed_symbols) - counted_signal_conflicts)
    return mismatches


def _non_empty_list_items(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return [
        item for item in value
        if (isinstance(item, str) and item.strip()) or isinstance(item, dict)
    ]


def _expected_channel_count(analysis: dict, key: str) -> int:
    return len(_non_empty_list_items(analysis.get(key)))


_SECOND_ORDER_BRIDGE_WORDS = {
    "because", "via", "through", "transmit", "transmits", "transmission",
    "spillover", "spillovers", "bridge", "bridges", "proxy", "reflects",
    "reprices", "repricing", "driven", "exposure", "channel", "channels",
    "from", "to", "into", "then", "therefore",
}


def _text_has_second_order_bridge(text: object) -> bool:
    if not isinstance(text, str) or len(text.strip()) < 24:
        return False
    words = set(re.findall(r"[A-Za-z_]{2,}", text.lower()))
    return bool(words & _SECOND_ORDER_BRIDGE_WORDS)


def _second_order_has_bridge(analysis: dict, second_order_count: int) -> bool:
    if second_order_count <= 0:
        return False
    chain = [
        str(step).strip()
        for step in analysis.get("transmission_chain") or []
        if _non_empty_text(step)
    ]
    if len(chain) >= 3:
        return True
    for entry in analysis.get("secondary_assets") or []:
        if not isinstance(entry, dict):
            continue
        text = " ".join(
            str(entry.get(key) or "")
            for key in ("rationale", "why", "why_it_matters", "mechanism", "channel")
        )
        if _text_has_second_order_bridge(text):
            return True
    for item in analysis.get("expected_second_order_channels") or []:
        if _text_has_second_order_bridge(item):
            return True
        if isinstance(item, dict):
            text = " ".join(str(value) for value in item.values())
            if _text_has_second_order_bridge(text):
                return True
    return False


_DIRECTION_WORDS = {
    "up", "down", "higher", "lower", "rise", "rises", "rising", "fall",
    "falls", "falling", "widen", "widens", "wider", "tighten", "tightens",
    "tighter", "steepen", "steepens", "flatten", "flattens", "stronger",
    "weaker", "support", "supports", "pressure", "pressures", "positive",
    "negative", "long", "short", "outperform", "underperform",
    "risk_on", "risk_off", "risk-on", "risk-off",
}


def _direction_value_valid(value: object) -> bool:
    if isinstance(value, (int, float)):
        return value != 0
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    if not text:
        return False
    if text in {"+", "-", "+1", "-1"}:
        return True
    tokens = set(re.findall(r"[A-Za-z_+-]+", text))
    return bool(tokens & _DIRECTION_WORDS)


def _entry_expected_direction_present(entry: object) -> bool:
    if isinstance(entry, str):
        return _direction_value_valid(entry)
    if not isinstance(entry, dict):
        return False
    for key in (
        "expected_direction",
        "direction",
        "direction_tag",
        "expected_move",
        "direction_sign",
        "signal_direction",
    ):
        if _direction_value_valid(entry.get(key)):
            return True
    return False


def _expected_direction_present(analysis: dict) -> bool:
    for key in (
        "minimum_proof_set",
        "primary_assets",
        "secondary_assets",
        "hedge_or_signal_assets",
        "market_tickers",
    ):
        for entry in analysis.get(key) or []:
            if _entry_expected_direction_present(entry):
                return True
    return False


def _signal_asset_direction_valid(analysis: dict) -> bool:
    signals = [
        entry for entry in analysis.get("hedge_or_signal_assets") or []
        if isinstance(entry, dict)
    ]
    if not signals:
        return False
    return all(_entry_expected_direction_present(entry) for entry in signals)


_FAMILY_CHAIN_TERMS: dict[str, set[str]] = {
    "supply_chain_chokepoint": {
        "supply", "chain", "capacity", "scarce", "scarcity", "bottleneck",
        "chokepoint", "export", "access", "equipment", "logistics",
    },
    "commodity_squeeze": {
        "commodity", "oil", "gas", "crude", "supply", "demand",
        "inventory", "price", "prices", "margin", "discount", "premium",
    },
    "demand_shock": {
        "demand", "consumption", "orders", "revenue", "sales", "growth",
    },
    "policy_constraint": {
        "policy", "regulation", "regulatory", "sanction", "sanctions",
        "tariff", "ban", "restriction", "approval", "compliance",
    },
    "funding_stress": {
        "funding", "liquidity", "credit", "spread", "spreads", "default",
        "refinancing", "debt",
    },
    "rate_shock": {
        "rate", "rates", "yield", "yields", "duration", "discount",
        "inflation", "hawkish", "dovish",
    },
}


def _family_chain_consistent(analysis: dict, family_value: str) -> bool:
    family = family_value.strip().lower()
    if not family or family == "none":
        return False
    family_tokens = {
        token for token in re.findall(r"[a-z0-9]+", family)
        if token not in {"family", "mechanism", "shock", "none"}
    }
    chain_text = " ".join(
        str(part)
        for part in (
            [analysis.get("mechanism_summary") or ""]
            + [step for step in analysis.get("transmission_chain") or []]
            + [ch for ch in analysis.get("expected_first_order_channels") or []]
            + [ch for ch in analysis.get("expected_second_order_channels") or []]
        )
    )
    chain_tokens = _content_tokens(chain_text)
    if family_tokens & chain_tokens:
        return True
    for prefix, terms in _FAMILY_CHAIN_TERMS.items():
        if family.startswith(prefix) or prefix.startswith(family):
            return bool(chain_tokens & terms)
    return False


_GENERIC_CHAIN_PHRASES = {
    "market reacts",
    "markets react",
    "investors react",
    "investors respond",
    "assets move",
    "prices move",
    "uncertainty rises",
    "sentiment changes",
    "risk increases",
}

_GENERIC_CHAIN_TOKENS = {
    "market", "markets", "investors", "react", "reacts", "respond",
    "responds", "assets", "prices", "move", "moves", "uncertainty",
    "sentiment", "risk", "impact", "effects", "changes", "event",
    "happens",
}


def _generic_chain_hops_count(analysis: dict) -> int:
    chain = analysis.get("transmission_chain")
    if not isinstance(chain, list):
        return 0
    count = 0
    for step in chain:
        if not isinstance(step, str) or not step.strip():
            continue
        text = step.strip().lower()
        tokens = set(re.findall(r"[A-Za-z]{3,}", text))
        if (
            len(tokens) <= 2
            or text in _GENERIC_CHAIN_PHRASES
            or (tokens and tokens <= _GENERIC_CHAIN_TOKENS)
        ):
            count += 1
    return count


def _chain_asset_implication_present(analysis: dict) -> bool:
    if _chain_ends_in_asset_implication(analysis):
        return True
    chain = analysis.get("transmission_chain")
    if not isinstance(chain, list):
        return False
    chain_text = " ".join(str(step) for step in chain if _non_empty_text(step))
    chain_upper = chain_text.upper()
    asset_terms: set[str] = set()
    for key in (
        "beneficiary_tickers",
        "loser_tickers",
        "assets_to_watch",
        "primary_assets",
        "secondary_assets",
    ):
        bucket = analysis.get(key)
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if isinstance(item, str) and item.strip():
                asset_terms.add(item.strip().upper())
            elif isinstance(item, dict):
                sym = item.get("symbol") or item.get("ticker")
                if isinstance(sym, str) and sym.strip():
                    asset_terms.add(sym.strip().upper())
    return any(term and term in chain_upper for term in asset_terms)


def _primary_asset_contradiction_count(consistency: dict) -> int:
    per_field = consistency.get("per_field")
    if not isinstance(per_field, dict):
        return 0
    stats = per_field.get("primary_assets")
    if not isinstance(stats, dict):
        return 0
    return int(stats.get("dropped") or 0)


_PENDING_PLACEHOLDERS = {
    "", "none", "n/a", "na", "null", "unknown", "unspecified",
    "not applicable", "tbd",
}


def _future_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("id", "name", "subtype", "type", "value"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def _mechanism_subtype_value(analysis: dict) -> str:
    for key in (
        "mechanism_subtype",
        "mechanism_subtype_id",
        "mechanism_family_subtype",
        "subtype",
    ):
        value = _future_text(analysis.get(key))
        if value:
            return value
    return ""


def _mechanism_subtype_present(analysis: dict) -> bool:
    value = _mechanism_subtype_value(analysis).lower()
    return bool(value and value not in _PENDING_PLACEHOLDERS)


def _subtype_family_consistent(analysis: dict, family_value: str) -> bool:
    explicit = analysis.get("subtype_family_consistent")
    if isinstance(explicit, bool):
        return explicit
    subtype = _mechanism_subtype_value(analysis)
    family = family_value.strip()
    if (
        not subtype
        or subtype.lower() in _PENDING_PLACEHOLDERS
        or not family
        or family.lower() == "none"
    ):
        return False
    subtype_raw = analysis.get("mechanism_subtype")
    if isinstance(subtype_raw, dict):
        declared_family = _future_text(
            subtype_raw.get("family") or subtype_raw.get("mechanism_family")
        )
        if declared_family:
            return bool(_content_tokens(declared_family) & _content_tokens(family))
    return bool(_content_tokens(subtype) & _content_tokens(family))


def _is_non_empty_future_field(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() not in _PENDING_PLACEHOLDERS
    if isinstance(value, list):
        return any(_is_non_empty_future_field(item) for item in value)
    if isinstance(value, dict):
        return any(_is_non_empty_future_field(item) for item in value.values())
    return value is not None


def _iter_proxy_records(analysis: dict) -> list[dict]:
    records: list[dict] = []
    for key in (
        "proxy_candidates",
        "proxy_eligibility",
        "proxy_eligibility_matrix",
        "eligible_proxies",
    ):
        value = analysis.get(key)
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            if any(k in value for k in ("symbol", "ticker", "eligible", "status")):
                records.append(value)
            records.extend(item for item in value.values() if isinstance(item, dict))
    for bucket_key in ("primary_assets", "secondary_assets", "hedge_or_signal_assets"):
        bucket = analysis.get(bucket_key)
        if isinstance(bucket, list):
            records.extend(item for item in bucket if isinstance(item, dict))
    return records


def _proxy_eligibility_present(analysis: dict) -> bool:
    for key in (
        "proxy_eligibility",
        "proxy_eligibility_matrix",
        "proxy_candidates",
        "eligible_proxies",
        "proxy_eligibility_summary",
    ):
        if key in analysis and _is_non_empty_future_field(analysis.get(key)):
            return True
    for record in _iter_proxy_records(analysis):
        if any(
            key in record
            for key in (
                "proxy_eligible",
                "eligible",
                "proxy_eligibility",
                "eligibility",
                "proxy_reason",
            )
        ):
            return True
    return False


def _future_list_count(value: object) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


def _falsey_flag(value: object) -> bool:
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        return value.strip().lower() in {
            "false", "no", "0", "ineligible", "rejected", "reject",
        }
    return False


def _truthy_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "rejected", "reject"}
    return False


def _rejected_proxy_count(analysis: dict) -> int:
    total = sum(
        _future_list_count(analysis.get(key))
        for key in ("rejected_proxies", "rejected_proxy_assets", "proxy_rejections")
    )
    for record in _iter_proxy_records(analysis):
        status_text = " ".join(
            str(record.get(key) or "")
            for key in ("status", "reason", "rejection_reason", "eligibility")
        ).lower()
        if (
            _truthy_flag(record.get("rejected"))
            or _falsey_flag(record.get("eligible"))
            or _falsey_flag(record.get("proxy_eligible"))
            or "reject" in status_text
            or "ineligible" in status_text
        ):
            total += 1
    return total


def _low_channel_match_count(analysis: dict) -> int:
    total = sum(
        _future_list_count(analysis.get(key))
        for key in ("low_channel_matches", "low_channel_match_proxies")
    )
    for record in _iter_proxy_records(analysis):
        match = str(
            record.get("channel_match")
            or record.get("channel_match_quality")
            or record.get("match_quality")
            or ""
        ).strip().lower()
        score = record.get("channel_match_score")
        if match in {"low", "weak", "poor"}:
            total += 1
        elif isinstance(score, (int, float)) and score <= 0.33:
            total += 1
    return total


def _high_noise_proxy_count(analysis: dict) -> int:
    total = _future_list_count(analysis.get("high_noise_proxies"))
    for record in _iter_proxy_records(analysis):
        noise = str(
            record.get("noise")
            or record.get("noise_level")
            or record.get("proxy_noise")
            or ""
        ).strip().lower()
        score = record.get("noise_score")
        if noise in {"high", "noisy", "very_high"}:
            total += 1
        elif isinstance(score, (int, float)) and score >= 0.67:
            total += 1
    return total


# ---------------------------------------------------------------------------
# Subtype normalization + proxy-eligibility diagnostics — eval-only.
# Pure read-side helpers; never touch engine logic or market fetches.
# Each returns a sane false/0 default when the underlying field is
# absent so the eval markdown still produces clean numbers on legacy
# analyses that never carried the new structure.
# ---------------------------------------------------------------------------

# Validation-warning markers the engine appends when a noise-driven
# downgrade / coercion / cap fires during normalisation.  Used by
# ``_high_noise_override_detected`` and ``_subtype_dropped_or_warned``.
_HIGH_NOISE_OVERRIDE_MARKERS: tuple[str, ...] = (
    "weak causal chain",
    "consistency collapsed",
    "off-family",
    "high-risk blocker",
    "blended mechanism",
    "coerced to low-information",
    "capped to watch_only",
)

_SIGNAL_CHANNEL_TOKENS: tuple[str, ...] = (
    "fx", "vol", "rate", "rates", "credit", "liquid", "dollar",
    "duration", "currenc", "macro proxy", "spread", "yield",
)


def _validation_warnings(analysis: dict) -> list[str]:
    """Return ``analysis['validation_warnings']`` as a flat list of
    strings, dropping non-string entries.  Defensive — legacy rows or
    test stubs may omit the field entirely."""
    raw = analysis.get("validation_warnings") if isinstance(analysis, dict) else None
    if not isinstance(raw, list):
        return []
    return [w for w in raw if isinstance(w, str)]


def _mechanism_subtype_valid(analysis: dict) -> bool:
    """True when ``mechanism_subtype`` is present AND registered as a
    valid subtype for the committed family.

    Strict variant of ``_subtype_family_consistent`` — that helper uses
    content-token overlap as a loose match; this one requires the
    subtype to be a key in ``FAMILY_SUBTYPES[family]`` so the field
    only reads True when the engine's normalization passed it through.
    Returns False when subtype is absent, family is missing / "none",
    or the family has no subtypes registered at all.
    """
    subtype = _mechanism_subtype_value(analysis).strip()
    if not subtype or subtype.lower() in _PENDING_PLACEHOLDERS:
        return False
    family = str(analysis.get("mechanism_family") or "").strip()
    if not family or family.lower() == "none":
        return False
    try:
        from mechanism_family import FAMILY_SUBTYPES
    except Exception:
        return False
    valid_for_family = FAMILY_SUBTYPES.get(family, {})
    return subtype in valid_for_family


def _subtype_dropped_or_warned(analysis: dict) -> bool:
    """True when ``validation_warnings`` carries a mechanism_subtype
    drop / warn / invalid marker.  The engine appends
    ``"mechanism_subtype dropped — '<token>' not valid for family
    '<fam>'"`` in the normaliser; this helper picks that up plus any
    looser warning shape (drop / warn / invalid) the field supports."""
    for warning in _validation_warnings(analysis):
        low = warning.lower()
        if "mechanism_subtype" in low and any(
            marker in low for marker in ("drop", "warn", "invalid")
        ):
            return True
    return False


def _primary_weighted_assets_count(analysis: dict) -> int:
    """Count of assets the agreement engine treats at primary weight.

    Reads ``primary_assets`` first (the canonical primary-weighted
    bucket), falling back to ``beneficiary_tickers`` when the LLM
    only emitted the legacy shape so legacy analyses still report a
    usable number rather than 0.
    """
    primary = analysis.get("primary_assets")
    if isinstance(primary, list):
        count = sum(
            1 for entry in primary
            if isinstance(entry, dict)
            and isinstance(entry.get("symbol") or entry.get("ticker"), str)
            and (entry.get("symbol") or entry.get("ticker") or "").strip()
        )
        if count:
            return count

    bene = analysis.get("beneficiary_tickers")
    if isinstance(bene, list):
        return sum(
            1 for t in bene if isinstance(t, str) and t.strip()
        )
    return 0


def _rejected_assets_excluded_from_validation(analysis: dict) -> int:
    """Sum of assets the consistency / proxy audits dropped from the
    validation surface.  Combines the existing eval ``rejected_asset``
    count (consistency-driven) with ``rejected_proxy`` (eligibility-
    driven) so the eval markdown shows the consolidated number a
    reviewer cares about: how many assets did the engine refuse to
    validate against?
    """
    consistency = _consistency_audit(analysis)
    consistency_drop = (
        _audit_dropped_count(consistency, ("primary_assets", "secondary_assets"))
        + _explicit_rejected_asset_count(analysis)
    )
    return int(consistency_drop) + int(_rejected_proxy_count(analysis))


def _signal_assets_channel_bound(analysis: dict) -> int:
    """Count of ``hedge_or_signal_assets`` entries that name a clear
    channel binding — either an explicit ``channel`` field or a
    rationale that references a recognised macro-proxy noun (FX /
    vol / rates / credit / dollar / duration).  Hedge / signal
    proxies that don't tie to a channel are eval-flagged as floating
    instruments — they can't carry a deterministic confirmation read.
    """
    bucket = analysis.get("hedge_or_signal_assets")
    if not isinstance(bucket, list):
        return 0
    count = 0
    for entry in bucket:
        if not isinstance(entry, dict):
            continue
        sym = entry.get("symbol") or entry.get("ticker")
        if not isinstance(sym, str) or not sym.strip():
            continue
        ch = entry.get("channel")
        if isinstance(ch, str) and ch.strip():
            count += 1
            continue
        rationale = (
            entry.get("rationale")
            or entry.get("why_it_matters")
            or entry.get("reason")
            or ""
        )
        if not isinstance(rationale, str):
            continue
        low = rationale.lower()
        if any(tok in low for tok in _SIGNAL_CHANNEL_TOKENS):
            count += 1
    return count


def _high_noise_override_detected(analysis: dict) -> bool:
    """True when ``validation_warnings`` indicates the engine applied
    a high-noise override during normalization — a downgrade /
    coercion / cap that fired because a contract gate (consistency,
    blocker discipline, chain-family, causal strength) decided the
    output was too noisy to ship at face value.

    Distinct from ``_high_noise_proxy_count`` (which counts noisy
    proxy candidates).  Returns False when no validation_warnings or
    no marker matches.
    """
    for warning in _validation_warnings(analysis):
        low = warning.lower()
        if any(marker in low for marker in _HIGH_NOISE_OVERRIDE_MARKERS):
            return True
    return False


# ---------------------------------------------------------------------------
# Rationale-quality diagnostics - eval-only.
# These helpers read optional rationale fields if/when the engine emits
# them. Missing fields stay false, so older outputs and pending engine
# contracts remain safe to evaluate.
# ---------------------------------------------------------------------------

_CONFIDENCE_RATIONALE_KEYS: tuple[str, ...] = (
    "confidence_rationale",
    "confidence_reason",
    "confidence_explanation",
    "confidence_basis",
    "confidence_notes",
    "confidence_calibration",
)

_VALIDATION_RATIONALE_KEYS: tuple[str, ...] = (
    "validation_rationale",
    "validation_reason",
    "validation_explanation",
    "validation_basis",
    "market_validation_rationale",
    "validation_outcome",
    "market_note",
)

_RATIONALE_SUBKEYS: tuple[str, ...] = (
    "rationale",
    "reason",
    "explanation",
    "basis",
    "note",
    "notes",
    "why",
)

_EMPTY_PROOF_STATUS: dict[str, object] = {
    "available": False,
    "status": "none",
    "matched_count": 0,
    "total_count": 0,
    "matched_items": [],
    "unmet_items": [],
    "items": [],
}

_EMPTY_FALSIFIER_STATUS: dict[str, object] = {
    "available": False,
    "status": "none",
    "triggered": [],
    "watching": [],
    "items": [],
}

_ACTIONABILITY_CHECK_KEYS: tuple[str, ...] = (
    "tradable",
    "why_tradable_or_not",
    "required_confirmation",
    "sizing_caveat",
    "risk_level",
    "max_confidence_before_confirmation",
    "invalidation_trigger",
)

_COUNTERFACTUAL_CHECK_KEYS: tuple[str, ...] = (
    "what_should_not_happen",
    "why_it_would_break_thesis",
    "evidence_to_watch",
)


def _empty_status_block(template: dict[str, object]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in template.items():
        out[key] = list(value) if isinstance(value, list) else value
    return out


def _proof_status_shaped(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("available"), bool)
        and isinstance(value.get("status"), str)
        and isinstance(value.get("matched_count"), int)
        and isinstance(value.get("total_count"), int)
        and isinstance(value.get("matched_items"), list)
        and isinstance(value.get("unmet_items"), list)
        and isinstance(value.get("items"), list)
    )


def _falsifier_status_shaped(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("available"), bool)
        and isinstance(value.get("status"), str)
        and isinstance(value.get("triggered"), list)
        and isinstance(value.get("watching"), list)
        and isinstance(value.get("items"), list)
    )


def _actionability_check_shaped(value: object) -> bool:
    return isinstance(value, dict) and all(
        key in value for key in _ACTIONABILITY_CHECK_KEYS
    )


def _counterfactual_check_shaped(value: object) -> bool:
    return (
        isinstance(value, dict)
        and all(key in value for key in _COUNTERFACTUAL_CHECK_KEYS)
        and isinstance(value.get("evidence_to_watch"), list)
    )


def _counterfactual_evidence_count(analysis: dict) -> int:
    block = analysis.get("counterfactual_check")
    if not isinstance(block, dict):
        return 0
    evidence = block.get("evidence_to_watch")
    if not isinstance(evidence, list):
        return 0
    return sum(1 for item in evidence if _field_present(item))


def _proof_status_item_count(analysis: dict) -> int:
    block = analysis.get("proof_status")
    if not isinstance(block, dict):
        return 0
    total = block.get("total_count")
    if isinstance(total, int) and total >= 0:
        return total
    items = block.get("items")
    if isinstance(items, list) and items:
        return len(items)
    matched = block.get("matched_items")
    unmet = block.get("unmet_items")
    return (
        len(matched) if isinstance(matched, list) else 0
    ) + (
        len(unmet) if isinstance(unmet, list) else 0
    )


def _falsifier_status_item_count(analysis: dict) -> int:
    block = analysis.get("falsifier_status")
    if not isinstance(block, dict):
        return 0
    total = block.get("total_count")
    if isinstance(total, int) and total >= 0:
        return total
    items = block.get("items")
    if isinstance(items, list) and items:
        return len(items)
    triggered = block.get("triggered")
    watching = block.get("watching")
    return (
        len(triggered) if isinstance(triggered, list) else 0
    ) + (
        len(watching) if isinstance(watching, list) else 0
    )


def _evidence_sources_shaped(value: object) -> bool:
    if isinstance(value, list):
        return True
    if isinstance(value, dict):
        return any(key in value for key in _EVIDENCE_SOURCE_SUBKEYS)
    return False


def _status_blocks_for_result(analysis: dict) -> dict[str, object]:
    proof_status = analysis.get("proof_status")
    falsifier_status = analysis.get("falsifier_status")
    persistence_signal = analysis.get("persistence_signal")
    return {
        "thesis_state": analysis.get("thesis_state") or "",
        "thesis_state_reason": analysis.get("thesis_state_reason") or "",
        "validation_rationale": analysis.get("validation_rationale") or "",
        "persistence_signal": (
            persistence_signal if isinstance(persistence_signal, dict) else {}
        ),
        "proof_status": (
            proof_status if isinstance(proof_status, dict)
            else _empty_status_block(_EMPTY_PROOF_STATUS)
        ),
        "falsifier_status": (
            falsifier_status if isinstance(falsifier_status, dict)
            else _empty_status_block(_EMPTY_FALSIFIER_STATUS)
        ),
    }


def _engine_phase_blocks_for_result(analysis: dict) -> dict[str, object]:
    actionability_check = analysis.get("actionability_check")
    counterfactual_check = analysis.get("counterfactual_check")
    evidence_sources = analysis.get("evidence_sources")
    return {
        "actionability_check": (
            actionability_check if isinstance(actionability_check, dict) else {}
        ),
        "counterfactual_check": (
            counterfactual_check if isinstance(counterfactual_check, dict) else {}
        ),
        "evidence_sources": (
            evidence_sources if isinstance(evidence_sources, (list, dict)) else []
        ),
    }


def _engine_emitted_fields(analysis: dict) -> list[str]:
    """Fields actually present in the analysis before eval defaults.

    Eval-visible fields can be defaulted to stable empty shapes. This list
    keeps the shape-parity report from mistaking those defaults for fields
    emitted by the engine itself.
    """
    return [
        field for field in ENGINE_PHASE_PARITY_FIELDS
        if field in analysis
    ]


def _eval_visible_fields(result: dict) -> list[str]:
    return [
        field for field in ENGINE_PHASE_PARITY_FIELDS
        if field in result
    ]

_GENERIC_RATIONALE_MARKERS: tuple[str, ...] = (
    "market reaction",
    "notable move",
    "mixed signals",
    "needs more evidence",
    "insufficient evidence",
    "confidence is high",
    "confidence is medium",
    "validation passed",
    "validation failed",
    "generic rationale",
    "supportive",
    "watch only",
)

_RATIONALE_CONCRETE_TOKENS = (
    _CAUSAL_CHANNEL_WORDS
    | _REGIME_WORDS
    | {
        "tariff", "tariffs", "reserve", "reserves", "credit", "spread",
        "default", "exports", "imports", "inventory", "capacity",
        "earnings", "revenue", "cashflow", "duration", "basis",
        "shipment", "shipments", "chokepoint", "sanctions", "policy",
    }
)


def _text_values(value: object) -> list[str]:
    """Extract short text leaves from common rationale container shapes."""
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, dict):
        texts: list[str] = []
        for key in _RATIONALE_SUBKEYS:
            texts.extend(_text_values(value.get(key)))
        return texts
    if isinstance(value, list):
        texts = []
        for item in value:
            if isinstance(item, dict):
                texts.extend(_text_values(item))
            elif isinstance(item, str) and item.strip():
                texts.append(item.strip())
        return texts
    return []


def _rationale_text(analysis: dict, keys: tuple[str, ...]) -> str:
    parts: list[str] = []
    for key in keys:
        parts.extend(_text_values(analysis.get(key)))
    return " ".join(parts).strip()


def _rationale_is_generic(text: str) -> bool:
    low = text.strip().lower()
    if not low:
        return False
    tokens = _content_tokens(low)
    if len(tokens) < 5:
        return True
    if any(marker in low for marker in _GENERIC_RATIONALE_MARKERS):
        return True
    return not (
        bool(tokens & _RATIONALE_CONCRETE_TOKENS)
        or bool(_PRICING_RELATIONSHIP_RE.search(text))
        or bool(re.search(r"\b[A-Z]{2,5}\b", text))
    )


def _rationale_concrete(text: str) -> bool:
    if not text.strip() or _rationale_is_generic(text):
        return False
    return len(_content_tokens(text)) >= 6


_ACTIONABILITY_KEYS: tuple[str, ...] = (
    "actionability",
    "action",
    "recommendation",
    "decision",
    "trade_action",
    "tradable",
    "tradeable",
    "is_tradable",
)

_TRADABLE_KEYS: tuple[str, ...] = (
    "tradable",
    "tradeable",
    "is_tradable",
    "tradable_true",
)

_CONFIRMATION_KEYS: tuple[str, ...] = (
    "confirmation",
    "market_confirmation",
    "cross_asset_confirmation",
    "cross_asset_coherence",
    "agreement",
    "weighted_evidence",
    "thesis_state",
    "validation_outcome",
)

_MARKET_MACRO_CONFLICT_KEYS: tuple[str, ...] = (
    "market_macro_conflict",
    "macro_market_conflict",
    "market_macro_conflict_detected",
    "cross_asset_conflict",
    "macro_conflict",
    "narrative_divergence",
    "cross_asset_confirmation",
    "cross_asset_coherence",
)

_CONFLICT_REASON_KEYS: tuple[str, ...] = (
    "conflict_reason",
    "market_macro_conflict_reason",
    "reason",
    "rationale",
    "explanation",
    "note",
    "notes",
)

_ACTIONABILITY_RISK_KEYS: tuple[str, ...] = (
    "risk_level",
    "risk",
    "risk_tier",
    "actionability_risk_level",
    "actionability_risk",
)

_INVALIDATION_TRIGGER_KEYS: tuple[str, ...] = (
    "invalidation_trigger",
    "invalidation_triggers",
    "invalidation",
    "invalidates_if",
    "breaks_if",
    "break_if",
    "key_falsifiers",
    "falsifiers",
    "counterfactuals",
)

_EVIDENCE_SOURCE_KEYS: tuple[str, ...] = (
    "evidence_sources",
    "sources",
    "source_urls",
    "citations",
    "evidence_trace",
    "evidence_traces",
    "proof_sources",
    "minimum_proof_set",
    "evidence_attribution",
    "attribution",
)

_EVIDENCE_SOURCE_SUBKEYS: tuple[str, ...] = (
    "source",
    "sources",
    "url",
    "urls",
    "link",
    "links",
    "citation",
    "citations",
    "title",
    "publisher",
    "name",
    "date",
    "timestamp",
)

_GENERIC_SOURCE_TEXT = {
    "market data",
    "news",
    "sources",
    "evidence",
    "web",
    "n/a",
    "none",
    "unknown",
}

_URL_RE = re.compile(r"https?://|www\.|[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_DATE_RE = re.compile(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")

_TRUE_STRINGS = {
    "true", "yes", "y", "1", "tradable", "tradeable", "actionable",
}

_CONFIRM_STRINGS = {
    "confirmed", "confirming", "strong_confirm", "weak_confirm",
    "validated", "aligned", "supportive", "supported",
}

_CONFLICT_STRINGS = {
    "conflict", "conflicted", "contradict", "contradicted", "contra",
    "disconfirm", "disconfirmed", "weak_disconfirm", "strong_disconfirm",
    "rejected", "confident_miss", "mixed",
}


def _field_present(value: object) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, (list, dict)):
        return bool(value)
    return value is not None


def _actionability_present(analysis: dict) -> bool:
    return any(
        key in analysis and _field_present(analysis.get(key))
        for key in _ACTIONABILITY_KEYS
    ) or _field_present(analysis.get("actionability_check"))


def _actionability_blocks(analysis: dict) -> list[dict]:
    blocks: list[dict] = []
    for key in ("actionability", "actionability_check"):
        value = analysis.get(key)
        if isinstance(value, dict):
            blocks.append(value)
    return blocks


def _truthy_contract_value(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)) and value > 0:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_STRINGS
    if isinstance(value, dict):
        return any(
            _truthy_contract_value(value.get(key))
            for key in _TRADABLE_KEYS
            if key in value
        )
    return False


def _tradable_true(analysis: dict) -> bool:
    if any(
        key in analysis and _truthy_contract_value(analysis.get(key))
        for key in _TRADABLE_KEYS + ("actionability",)
    ):
        return True
    return any(
        _truthy_contract_value(block.get("tradable"))
        for block in _actionability_blocks(analysis)
    )


def _confirmation_present_value(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        low = value.strip().lower()
        return low in _CONFIRM_STRINGS or "confirm" in low
    if isinstance(value, dict):
        for key in ("verdict", "status", "label", "state", "agreement"):
            if _confirmation_present_value(value.get(key)):
                return True
        confirm = value.get("confirm_score")
        disconfirm = value.get("disconfirm_score")
        if isinstance(confirm, (int, float)):
            return confirm > float(disconfirm or 0)
        for key in ("confirms", "supporting", "confirmed"):
            bucket = value.get(key)
            if isinstance(bucket, list) and bucket:
                return True
    if isinstance(value, list):
        return any(_field_present(item) for item in value)
    return False


def _confirmation_present(analysis: dict) -> bool:
    if any(
        key in analysis and _confirmation_present_value(analysis.get(key))
        for key in _CONFIRMATION_KEYS
    ):
        return True
    return any(
        _field_present(block.get("required_confirmation"))
        for block in _actionability_blocks(analysis)
    )


def _market_macro_conflict_value(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        low = value.strip().lower()
        return any(marker in low for marker in _CONFLICT_STRINGS)
    if isinstance(value, dict):
        for key in ("detected", "conflict", "has_conflict", "is_conflict"):
            if value.get(key) is True:
                return True
        for key in ("verdict", "status", "label", "state"):
            if _market_macro_conflict_value(value.get(key)):
                return True
        confirm = value.get("confirm_score")
        disconfirm = value.get("disconfirm_score")
        if isinstance(disconfirm, (int, float)):
            return disconfirm > float(confirm or 0)
    return False


def _market_macro_conflict_detected(analysis: dict) -> bool:
    for key in _MARKET_MACRO_CONFLICT_KEYS:
        if key in analysis and _market_macro_conflict_value(analysis.get(key)):
            return True
    for warning in _validation_warnings(analysis):
        low = warning.lower()
        if (
            any(scope in low for scope in ("market", "macro", "cross-asset"))
            and any(marker in low for marker in _CONFLICT_STRINGS)
        ):
            return True
    return False


def _conflict_reason_present_value(value: object) -> bool:
    if isinstance(value, str):
        return len(value.strip()) >= 10
    if isinstance(value, dict):
        for key in _CONFLICT_REASON_KEYS:
            if _conflict_reason_present_value(value.get(key)):
                return True
    return False


def _conflict_reason_present(analysis: dict) -> bool:
    if not _market_macro_conflict_detected(analysis):
        return False
    for key in _CONFLICT_REASON_KEYS + _MARKET_MACRO_CONFLICT_KEYS:
        if key in analysis and _conflict_reason_present_value(analysis.get(key)):
            return True
    return any(len(warning.strip()) >= 10 for warning in _validation_warnings(analysis))


def _actionability_risk_level_present(analysis: dict) -> bool:
    for key in _ACTIONABILITY_RISK_KEYS:
        if key in analysis and _field_present(analysis.get(key)):
            return True
    for block in _actionability_blocks(analysis):
        if any(key in block and _field_present(block.get(key))
               for key in _ACTIONABILITY_RISK_KEYS):
            return True
    return False


def _trace_text_values(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, dict):
        texts: list[str] = []
        for key in _EVIDENCE_SOURCE_SUBKEYS + _RATIONALE_SUBKEYS:
            texts.extend(_trace_text_values(value.get(key)))
        return texts
    if isinstance(value, list):
        texts = []
        for item in value:
            texts.extend(_trace_text_values(item))
        return texts
    return []


def _invalidation_trigger_present(analysis: dict) -> bool:
    for key in _INVALIDATION_TRIGGER_KEYS:
        if key not in analysis:
            continue
        value = analysis.get(key)
        if isinstance(value, list):
            if any(_field_present(item) for item in value):
                return True
        elif _field_present(value):
            return True
    return any(
        _field_present(block.get("invalidation_trigger"))
        for block in _actionability_blocks(analysis)
    ) or _counterfactual_evidence_count(analysis) > 0 or _field_present(
        (
            analysis.get("counterfactual_check")
            if isinstance(analysis.get("counterfactual_check"), dict)
            else {}
        ).get("what_should_not_happen")
    )


def _evidence_source_values(analysis: dict) -> list[str]:
    values: list[str] = []
    for key in _EVIDENCE_SOURCE_KEYS:
        if key in analysis:
            values.extend(_trace_text_values(analysis.get(key)))
    return values


def _evidence_sources_present(analysis: dict) -> bool:
    if _evidence_source_values(analysis):
        return True
    return any(
        key in analysis and _field_present(analysis.get(key))
        for key in _EVIDENCE_SOURCE_KEYS
    )


def _source_text_concrete(text: str) -> bool:
    stripped = text.strip()
    low = stripped.lower()
    if not stripped or low in _GENERIC_SOURCE_TEXT:
        return False
    if _URL_RE.search(stripped) or _DATE_RE.search(stripped):
        return True
    tokens = _content_tokens(stripped)
    if len(tokens) >= 3 and not tokens <= _content_tokens(" ".join(_GENERIC_SOURCE_TEXT)):
        return True
    return False


def _evidence_sources_concrete(analysis: dict) -> bool:
    return any(_source_text_concrete(text) for text in _evidence_source_values(analysis))


def _engine_quality_checklist(analysis: dict, quality: dict | None = None) -> dict:
    """Build additive eval-only checklist fields from the analysis output."""
    thesis = analysis.get("competing_thesis")
    if not isinstance(thesis, dict):
        thesis = {}

    try:
        from low_information_gate import evaluate_low_information
        low_information = bool(evaluate_low_information(analysis).get("is_low_info"))
    except Exception:
        low_information = False

    family = analysis.get("mechanism_family") or "none"
    consistency = _consistency_audit(analysis)
    rejected_asset_count = (
        _audit_dropped_count(consistency, ("primary_assets", "secondary_assets"))
        + _explicit_rejected_asset_count(analysis)
    )
    family_value = str(family).strip() or "none"
    proof_set_count = _count_list(analysis.get("minimum_proof_set"))
    transmission_chain_valid = _transmission_chain_valid(analysis)
    asset_why_lines_present = _asset_why_lines_present(analysis)
    quality_tier = _quality_tier(
        analysis, quality, low_information=low_information,
    )
    actionable = _is_actionable(
        analysis, quality_tier, low_information=low_information,
    )
    high_confidence = str(analysis.get("confidence") or "").strip().lower() == "high"
    causal_trigger_present = _causal_trigger_present(analysis)
    causal_channel_present = _causal_channel_present(analysis)
    pricing_relationship_present = _pricing_relationship_present(analysis)
    asset_implication_present = _asset_implication_present(analysis)
    regime_caveats_present = _regime_caveats_present(analysis)
    primary_asset_count = _asset_bucket_count(analysis, "primary_assets")
    secondary_asset_count = _asset_bucket_count(analysis, "secondary_assets")
    signal_asset_count = _asset_bucket_count(analysis, "hedge_or_signal_assets")
    first_order_count = _expected_channel_count(
        analysis, "expected_first_order_channels",
    )
    expected_second_order_count = _expected_channel_count(
        analysis, "expected_second_order_channels",
    )
    second_order_count = expected_second_order_count + secondary_asset_count
    second_order_has_bridge = _second_order_has_bridge(
        analysis, second_order_count,
    )
    primary_asset_contradiction_count = _primary_asset_contradiction_count(
        consistency,
    )
    causal_strength = _causal_strength(
        causal_trigger_present=causal_trigger_present,
        causal_channel_present=causal_channel_present,
        pricing_relationship_present=pricing_relationship_present,
        asset_implication_present=asset_implication_present,
        transmission_chain_valid=transmission_chain_valid,
    )
    confidence_rationale_text = _rationale_text(
        analysis, _CONFIDENCE_RATIONALE_KEYS,
    )
    validation_rationale_text = _rationale_text(
        analysis, _VALIDATION_RATIONALE_KEYS,
    )
    tradable_true = _tradable_true(analysis)
    evidence_sources_concrete = _evidence_sources_concrete(analysis)
    return {
        "primary_thesis_present": _non_empty_text(thesis.get("primary_thesis")),
        "alternative_thesis_present": _non_empty_text(thesis.get("alternative_thesis")),
        "discriminator_present": bool(thesis.get("discriminator")),
        "mechanism_family": family_value,
        "low_information": low_information,
        "asset_why_lines_present": asset_why_lines_present,
        "transmission_chain_valid": transmission_chain_valid,
        "proof_set_count": proof_set_count,
        "falsifier_count": _count_list(analysis.get("key_falsifiers")),
        "thesis_asset_consistent": _fields_consistent(
            consistency, ("primary_assets", "secondary_assets"),
        ),
        "thesis_proof_consistent": _fields_consistent(
            consistency, ("minimum_proof_set",),
        ),
        "thesis_falsifier_consistent": _fields_consistent(
            consistency, ("key_falsifiers",),
        ),
        "chain_ends_in_asset_implication": _chain_ends_in_asset_implication(analysis),
        "rejected_asset_count": rejected_asset_count,
        "quality_tier": quality_tier,
        "high_confidence_without_proof": high_confidence and proof_set_count == 0,
        "actionable_without_valid_chain": actionable and not transmission_chain_valid,
        "actionable_without_asset_rationale": actionable and not asset_why_lines_present,
        "actionable_with_family_none": (
            actionable and family_value.strip().lower() == "none"
        ),
        "low_information_but_has_assets": (
            low_information and _has_any_asset_exposure(analysis)
        ),
        "causal_strength": causal_strength,
        "causal_trigger_present": causal_trigger_present,
        "causal_channel_present": causal_channel_present,
        "pricing_relationship_present": pricing_relationship_present,
        "asset_implication_present": asset_implication_present,
        "regime_caveats_present": regime_caveats_present,
        "regime_caveats_concrete": _regime_caveats_concrete(analysis),
        "primary_asset_count": primary_asset_count,
        "secondary_asset_count": secondary_asset_count,
        "signal_asset_count": signal_asset_count,
        "beneficiary_signal_conflict": _beneficiary_signal_conflict(analysis),
        "role_channel_mismatch_count": _role_channel_mismatch_count(analysis),
        "first_order_present": bool(first_order_count or primary_asset_count),
        "second_order_count": second_order_count,
        "second_order_has_bridge": second_order_has_bridge,
        "second_order_skipped_channel": (
            secondary_asset_count > 0 and expected_second_order_count == 0
        ),
        "expected_direction_present": _expected_direction_present(analysis),
        "signal_asset_direction_valid": _signal_asset_direction_valid(analysis),
        "family_chain_consistent": _family_chain_consistent(
            analysis, family_value,
        ),
        "generic_chain_hops_count": _generic_chain_hops_count(analysis),
        "chain_asset_implication_present": _chain_asset_implication_present(analysis),
        "coherence_rejection_triggered": bool(
            int(consistency.get("dropped") or 0)
            or consistency.get("downgrade")
        ),
        "primary_asset_contradiction_count": primary_asset_contradiction_count,
        "weak_signal_only_support": (
            signal_asset_count > 0
            and primary_asset_count == 0
            and secondary_asset_count == 0
        ),
        "mechanism_subtype_present": _mechanism_subtype_present(analysis),
        "subtype_family_consistent": _subtype_family_consistent(
            analysis, family_value,
        ),
        "proxy_eligibility_present": _proxy_eligibility_present(analysis),
        "rejected_proxy_count": _rejected_proxy_count(analysis),
        "low_channel_match_count": _low_channel_match_count(analysis),
        "high_noise_proxy_count": _high_noise_proxy_count(analysis),
        # NEW eval-only diagnostics — subtype normalization + proxy-
        # eligibility consolidation.  False / 0 when underlying fields
        # are absent so the markdown still produces clean numbers.
        "mechanism_subtype_valid": _mechanism_subtype_valid(analysis),
        "subtype_dropped_or_warned": _subtype_dropped_or_warned(analysis),
        "primary_weighted_assets_count": _primary_weighted_assets_count(analysis),
        "rejected_assets_excluded_from_validation":
            _rejected_assets_excluded_from_validation(analysis),
        "signal_assets_channel_bound": _signal_assets_channel_bound(analysis),
        "high_noise_override_detected": _high_noise_override_detected(analysis),
        "confidence_rationale_present": bool(confidence_rationale_text),
        "confidence_rationale_concrete": _rationale_concrete(
            confidence_rationale_text,
        ),
        "thesis_state_present": _field_present(analysis.get("thesis_state")),
        "validation_rationale_present": bool(validation_rationale_text),
        "validation_rationale_concrete": _rationale_concrete(
            validation_rationale_text,
        ),
        "actionability_check_shaped": _actionability_check_shaped(
            analysis.get("actionability_check"),
        ),
        "counterfactual_check_present": _field_present(
            analysis.get("counterfactual_check"),
        ),
        "counterfactual_check_shaped": _counterfactual_check_shaped(
            analysis.get("counterfactual_check"),
        ),
        "counterfactual_evidence_count": _counterfactual_evidence_count(analysis),
        "proof_status_shaped": _proof_status_shaped(analysis.get("proof_status")),
        "proof_status_item_count": _proof_status_item_count(analysis),
        "falsifier_status_shaped": _falsifier_status_shaped(
            analysis.get("falsifier_status"),
        ),
        "falsifier_status_item_count": _falsifier_status_item_count(analysis),
        "evidence_sources_shaped": (
            "evidence_sources" in analysis
            and _evidence_sources_shaped(analysis.get("evidence_sources"))
        ),
        "rationale_too_generic": any(
            _rationale_is_generic(text)
            for text in (confidence_rationale_text, validation_rationale_text)
            if text
        ),
        "actionability_present": _actionability_present(analysis),
        "tradable_true_without_confirmation": (
            tradable_true and not _confirmation_present(analysis)
        ),
        "low_info_marked_tradable": low_information and tradable_true,
        "market_macro_conflict_detected": _market_macro_conflict_detected(analysis),
        "conflict_reason_present": _conflict_reason_present(analysis),
        "actionability_risk_level_present": (
            _actionability_risk_level_present(analysis)
        ),
        "invalidation_trigger_present": _invalidation_trigger_present(analysis),
        "evidence_sources_present": _evidence_sources_present(analysis),
        "evidence_sources_concrete": evidence_sources_concrete,
        "weak_traceability_but_high_confidence": (
            high_confidence and not evidence_sources_concrete
        ),
    }


# Keys whose deltas are computed and rendered in the before/after block.
# Order matters — the markdown follows the same order.
_DELTA_KEYS: tuple[str, ...] = (
    "low_information_count",
    "family_none_count",
    "missing_thesis_count",
    "missing_asset_rationale_count",
    "rejected_asset_count",
    "valid_transmission_chain_count",
    "thesis_asset_consistent_count",
    "thesis_proof_consistent_count",
    "thesis_falsifier_consistent_count",
    "chain_ends_in_asset_implication_count",
    "rejected_asset_total",
    "high_confidence_without_proof_count",
    "actionable_without_valid_chain_count",
    "actionable_without_asset_rationale_count",
    "actionable_with_family_none_count",
    "low_information_but_has_assets_count",
    "strong_causal_chain_count",
    "weak_causal_chain_count",
    "causal_trigger_present_count",
    "causal_channel_present_count",
    "pricing_relationship_present_count",
    "asset_implication_present_count",
    "regime_caveats_present_count",
    "regime_caveats_concrete_count",
    "primary_asset_total",
    "secondary_asset_total",
    "signal_asset_total",
    "beneficiary_signal_conflict_count",
    "role_channel_mismatch_total",
    "first_order_present_count",
    "second_order_total",
    "second_order_has_bridge_count",
    "second_order_skipped_channel_count",
    "expected_direction_present_count",
    "signal_asset_direction_valid_count",
    "family_chain_consistent_count",
    "generic_chain_hops_total",
    "chain_asset_implication_present_count",
    "coherence_rejection_triggered_count",
    "primary_asset_contradiction_total",
    "weak_signal_only_support_count",
    "mechanism_subtype_present_count",
    "subtype_family_consistent_count",
    "proxy_eligibility_present_count",
    "rejected_proxy_total",
    "low_channel_match_total",
    "high_noise_proxy_total",
    # Subtype normalization + proxy-eligibility diagnostics.
    "mechanism_subtype_valid_count",
    "subtype_dropped_or_warned_count",
    "primary_weighted_assets_total",
    "rejected_assets_excluded_total",
    "signal_assets_channel_bound_total",
    "high_noise_override_detected_count",
    "confidence_rationale_present_count",
    "confidence_rationale_concrete_count",
    "thesis_state_present_count",
    "validation_rationale_present_count",
    "validation_rationale_concrete_count",
    "actionability_check_shaped_count",
    "counterfactual_check_present_count",
    "counterfactual_check_shaped_count",
    "counterfactual_evidence_total",
    "proof_status_shaped_count",
    "proof_status_item_total",
    "falsifier_status_shaped_count",
    "falsifier_status_item_total",
    "evidence_sources_shaped_count",
    "rationale_too_generic_count",
    "actionability_present_count",
    "tradable_true_without_confirmation_count",
    "low_info_marked_tradable_count",
    "market_macro_conflict_detected_count",
    "conflict_reason_present_count",
    "actionability_risk_level_present_count",
    "invalidation_trigger_present_count",
    "evidence_sources_present_count",
    "evidence_sources_concrete_count",
    "weak_traceability_but_high_confidence_count",
    "proof_set_count",
    "falsifier_count",
)

# Human-readable labels for the markdown summary.
_DELTA_LABELS: dict[str, str] = {
    "low_information_count":          "Low-information count",
    "family_none_count":              "Family-none count",
    "missing_thesis_count":           "Missing-thesis count",
    "missing_asset_rationale_count":  "Missing-asset-rationale count",
    "rejected_asset_count":           "Rejected-asset count",
    "valid_transmission_chain_count": "Valid transmission_chain count",
    "thesis_asset_consistent_count":  "Thesis-asset consistent count",
    "thesis_proof_consistent_count":  "Thesis-proof consistent count",
    "thesis_falsifier_consistent_count": "Thesis-falsifier consistent count",
    "chain_ends_in_asset_implication_count": "Chain ends in asset implication count",
    "rejected_asset_total":           "Rejected-asset entries",
    "high_confidence_without_proof_count": "High-confidence without proof count",
    "actionable_without_valid_chain_count": "Actionable without valid chain count",
    "actionable_without_asset_rationale_count": "Actionable without asset rationale count",
    "actionable_with_family_none_count": "Actionable with family-none count",
    "low_information_but_has_assets_count": "Low-information but has assets count",
    "strong_causal_chain_count": "Strong causal chain count",
    "weak_causal_chain_count":   "Weak causal chain count",
    "causal_trigger_present_count": "Causal trigger present count",
    "causal_channel_present_count": "Causal channel present count",
    "pricing_relationship_present_count": "Pricing relationship present count",
    "asset_implication_present_count": "Asset implication present count",
    "regime_caveats_present_count": "Regime caveats present count",
    "regime_caveats_concrete_count": "Concrete regime caveats count",
    "primary_asset_total":          "Primary asset entries",
    "secondary_asset_total":        "Secondary asset entries",
    "signal_asset_total":           "Signal asset entries",
    "beneficiary_signal_conflict_count": "Beneficiary-signal conflict count",
    "role_channel_mismatch_total":  "Role/channel mismatch entries",
    "first_order_present_count":    "First-order present count",
    "second_order_total":           "Second-order entries",
    "second_order_has_bridge_count": "Second-order bridge count",
    "second_order_skipped_channel_count": "Second-order skipped-channel count",
    "expected_direction_present_count": "Expected direction present count",
    "signal_asset_direction_valid_count": "Signal asset direction valid count",
    "family_chain_consistent_count": "Family-chain consistent count",
    "generic_chain_hops_total": "Generic chain-hop entries",
    "chain_asset_implication_present_count": "Chain asset implication present count",
    "coherence_rejection_triggered_count": "Coherence rejection triggered count",
    "primary_asset_contradiction_total": "Primary asset contradiction entries",
    "weak_signal_only_support_count": "Weak signal-only support count",
    "mechanism_subtype_present_count": "Mechanism subtype present count",
    "subtype_family_consistent_count": "Subtype-family consistent count",
    "proxy_eligibility_present_count": "Proxy eligibility present count",
    "rejected_proxy_total": "Rejected proxy entries",
    "low_channel_match_total": "Low channel-match entries",
    "high_noise_proxy_total": "High-noise proxy entries",
    # Subtype normalization + proxy-eligibility diagnostics.
    "mechanism_subtype_valid_count":      "Mechanism subtype valid count",
    "subtype_dropped_or_warned_count":    "Subtype dropped/warned count",
    "primary_weighted_assets_total":      "Primary weighted-asset entries",
    "rejected_assets_excluded_total":     "Rejected assets excluded from validation",
    "signal_assets_channel_bound_total":  "Signal assets channel-bound entries",
    "high_noise_override_detected_count": "High-noise override detected count",
    "confidence_rationale_present_count": "Confidence rationale present count",
    "confidence_rationale_concrete_count": "Concrete confidence rationale count",
    "thesis_state_present_count":        "Thesis-state present count",
    "validation_rationale_present_count": "Validation rationale present count",
    "validation_rationale_concrete_count": "Concrete validation rationale count",
    "actionability_check_shaped_count":    "Actionability-check shaped count",
    "counterfactual_check_present_count":  "Counterfactual-check present count",
    "counterfactual_check_shaped_count":   "Counterfactual-check shaped count",
    "counterfactual_evidence_total":       "Counterfactual evidence entries",
    "proof_status_shaped_count":          "Proof-status shaped count",
    "proof_status_item_total":            "Proof-status item entries",
    "falsifier_status_shaped_count":      "Falsifier-status shaped count",
    "falsifier_status_item_total":        "Falsifier-status item entries",
    "evidence_sources_shaped_count":      "Evidence-sources shaped count",
    "rationale_too_generic_count":         "Rationale too generic count",
    "actionability_present_count":         "Actionability present count",
    "tradable_true_without_confirmation_count": "Tradable true without confirmation count",
    "low_info_marked_tradable_count":      "Low-info marked tradable count",
    "market_macro_conflict_detected_count": "Market/macro conflict detected count",
    "conflict_reason_present_count":       "Conflict reason present count",
    "actionability_risk_level_present_count": "Actionability risk level present count",
    "invalidation_trigger_present_count":  "Invalidation trigger present count",
    "evidence_sources_present_count":      "Evidence sources present count",
    "evidence_sources_concrete_count":     "Concrete evidence sources count",
    "weak_traceability_but_high_confidence_count": (
        "Weak traceability but high confidence count"
    ),
    "proof_set_count":                "Proof-set entries",
    "falsifier_count":                "Falsifier entries",
}


def _result_was_asset_rejected(r: dict) -> bool:
    """True when the analysis is NOT low-information yet has no concrete
    ticker exposure landed — the sanitizer rejected the LLM's
    proposed assets and no proxy backfill rescued the basket."""
    if r.get("low_information"):
        return False
    ben = r.get("beneficiary_tickers") or []
    lose = r.get("loser_tickers") or []
    watch = r.get("assets_to_watch") or []
    if any(isinstance(t, str) and t.strip() for t in ben):
        return False
    if any(isinstance(t, str) and t.strip() for t in lose):
        return False
    if any(isinstance(t, str) and t.strip() for t in watch):
        return False
    # Ranked buckets — when present they may carry symbols even when
    # the legacy ticker lists are thin.  Treat any concrete entry as
    # exposure landed.
    for key in ("primary_assets", "secondary_assets", "hedge_or_signal_assets"):
        bucket = r.get(key) or []
        if isinstance(bucket, list):
            for entry in bucket:
                if isinstance(entry, dict):
                    sym = entry.get("symbol") or entry.get("ticker")
                    if isinstance(sym, str) and sym.strip():
                        return False
    return True


def _engine_quality_summary(results: list[dict]) -> dict:
    total = len(results)
    return {
        "total_samples": total,
        "low_information_count": sum(1 for r in results if r["low_information"]),
        "family_none_count": sum(
            1
            for r in results
            if str(r.get("mechanism_family") or "none").strip().lower() == "none"
        ),
        "missing_thesis_count": sum(
            1 for r in results if not r["primary_thesis_present"]
        ),
        "missing_asset_rationale_count": sum(
            1 for r in results if not r["asset_why_lines_present"]
        ),
        # NEW — counts the contract-tightening rounds added.
        "rejected_asset_count": sum(
            1 for r in results if _result_was_asset_rejected(r)
        ),
        "valid_transmission_chain_count": sum(
            1 for r in results if r.get("transmission_chain_valid")
        ),
        "thesis_asset_consistent_count": sum(
            1 for r in results if r.get("thesis_asset_consistent")
        ),
        "thesis_proof_consistent_count": sum(
            1 for r in results if r.get("thesis_proof_consistent")
        ),
        "thesis_falsifier_consistent_count": sum(
            1 for r in results if r.get("thesis_falsifier_consistent")
        ),
        "chain_ends_in_asset_implication_count": sum(
            1 for r in results if r.get("chain_ends_in_asset_implication")
        ),
        "rejected_asset_total": sum(
            int(r.get("rejected_asset_count") or 0) for r in results
        ),
        "quality_tier_counts": {
            tier: sum(1 for r in results if r.get("quality_tier") == tier)
            for tier in ("excellent", "usable", "thin", "poor")
        },
        "high_confidence_without_proof_count": sum(
            1 for r in results if r.get("high_confidence_without_proof")
        ),
        "actionable_without_valid_chain_count": sum(
            1 for r in results if r.get("actionable_without_valid_chain")
        ),
        "actionable_without_asset_rationale_count": sum(
            1 for r in results if r.get("actionable_without_asset_rationale")
        ),
        "actionable_with_family_none_count": sum(
            1 for r in results if r.get("actionable_with_family_none")
        ),
        "low_information_but_has_assets_count": sum(
            1 for r in results if r.get("low_information_but_has_assets")
        ),
        "strong_causal_chain_count": sum(
            1 for r in results if r.get("causal_strength") == "strong"
        ),
        "weak_causal_chain_count": sum(
            1 for r in results if r.get("causal_strength") == "weak"
        ),
        "causal_trigger_present_count": sum(
            1 for r in results if r.get("causal_trigger_present")
        ),
        "causal_channel_present_count": sum(
            1 for r in results if r.get("causal_channel_present")
        ),
        "pricing_relationship_present_count": sum(
            1 for r in results if r.get("pricing_relationship_present")
        ),
        "asset_implication_present_count": sum(
            1 for r in results if r.get("asset_implication_present")
        ),
        "regime_caveats_present_count": sum(
            1 for r in results if r.get("regime_caveats_present")
        ),
        "regime_caveats_concrete_count": sum(
            1 for r in results if r.get("regime_caveats_concrete")
        ),
        "primary_asset_total": sum(
            int(r.get("primary_asset_count") or 0) for r in results
        ),
        "secondary_asset_total": sum(
            int(r.get("secondary_asset_count") or 0) for r in results
        ),
        "signal_asset_total": sum(
            int(r.get("signal_asset_count") or 0) for r in results
        ),
        "beneficiary_signal_conflict_count": sum(
            1 for r in results if r.get("beneficiary_signal_conflict")
        ),
        "role_channel_mismatch_total": sum(
            int(r.get("role_channel_mismatch_count") or 0) for r in results
        ),
        "first_order_present_count": sum(
            1 for r in results if r.get("first_order_present")
        ),
        "second_order_total": sum(
            int(r.get("second_order_count") or 0) for r in results
        ),
        "second_order_has_bridge_count": sum(
            1 for r in results if r.get("second_order_has_bridge")
        ),
        "second_order_skipped_channel_count": sum(
            1 for r in results if r.get("second_order_skipped_channel")
        ),
        "expected_direction_present_count": sum(
            1 for r in results if r.get("expected_direction_present")
        ),
        "signal_asset_direction_valid_count": sum(
            1 for r in results if r.get("signal_asset_direction_valid")
        ),
        "family_chain_consistent_count": sum(
            1 for r in results if r.get("family_chain_consistent")
        ),
        "generic_chain_hops_total": sum(
            int(r.get("generic_chain_hops_count") or 0) for r in results
        ),
        "chain_asset_implication_present_count": sum(
            1 for r in results if r.get("chain_asset_implication_present")
        ),
        "coherence_rejection_triggered_count": sum(
            1 for r in results if r.get("coherence_rejection_triggered")
        ),
        "primary_asset_contradiction_total": sum(
            int(r.get("primary_asset_contradiction_count") or 0)
            for r in results
        ),
        "weak_signal_only_support_count": sum(
            1 for r in results if r.get("weak_signal_only_support")
        ),
        "mechanism_subtype_present_count": sum(
            1 for r in results if r.get("mechanism_subtype_present")
        ),
        "subtype_family_consistent_count": sum(
            1 for r in results if r.get("subtype_family_consistent")
        ),
        "proxy_eligibility_present_count": sum(
            1 for r in results if r.get("proxy_eligibility_present")
        ),
        "rejected_proxy_total": sum(
            int(r.get("rejected_proxy_count") or 0) for r in results
        ),
        "low_channel_match_total": sum(
            int(r.get("low_channel_match_count") or 0) for r in results
        ),
        "high_noise_proxy_total": sum(
            int(r.get("high_noise_proxy_count") or 0) for r in results
        ),
        # Subtype normalization + proxy-eligibility diagnostics —
        # counts default to 0 when the underlying fields are absent,
        # so legacy / partial result rows still aggregate cleanly.
        "mechanism_subtype_valid_count": sum(
            1 for r in results if r.get("mechanism_subtype_valid")
        ),
        "subtype_dropped_or_warned_count": sum(
            1 for r in results if r.get("subtype_dropped_or_warned")
        ),
        "primary_weighted_assets_total": sum(
            int(r.get("primary_weighted_assets_count") or 0) for r in results
        ),
        "rejected_assets_excluded_total": sum(
            int(r.get("rejected_assets_excluded_from_validation") or 0)
            for r in results
        ),
        "signal_assets_channel_bound_total": sum(
            int(r.get("signal_assets_channel_bound") or 0) for r in results
        ),
        "high_noise_override_detected_count": sum(
            1 for r in results if r.get("high_noise_override_detected")
        ),
        "confidence_rationale_present_count": sum(
            1 for r in results if r.get("confidence_rationale_present")
        ),
        "confidence_rationale_concrete_count": sum(
            1 for r in results if r.get("confidence_rationale_concrete")
        ),
        "thesis_state_present_count": sum(
            1 for r in results if r.get("thesis_state_present")
        ),
        "validation_rationale_present_count": sum(
            1 for r in results if r.get("validation_rationale_present")
        ),
        "validation_rationale_concrete_count": sum(
            1 for r in results if r.get("validation_rationale_concrete")
        ),
        "actionability_check_shaped_count": sum(
            1 for r in results if r.get("actionability_check_shaped")
        ),
        "counterfactual_check_present_count": sum(
            1 for r in results if r.get("counterfactual_check_present")
        ),
        "counterfactual_check_shaped_count": sum(
            1 for r in results if r.get("counterfactual_check_shaped")
        ),
        "counterfactual_evidence_total": sum(
            int(r.get("counterfactual_evidence_count") or 0)
            for r in results
        ),
        "proof_status_shaped_count": sum(
            1 for r in results if r.get("proof_status_shaped")
        ),
        "proof_status_item_total": sum(
            int(r.get("proof_status_item_count") or 0) for r in results
        ),
        "falsifier_status_shaped_count": sum(
            1 for r in results if r.get("falsifier_status_shaped")
        ),
        "falsifier_status_item_total": sum(
            int(r.get("falsifier_status_item_count") or 0)
            for r in results
        ),
        "evidence_sources_shaped_count": sum(
            1 for r in results if r.get("evidence_sources_shaped")
        ),
        "rationale_too_generic_count": sum(
            1 for r in results if r.get("rationale_too_generic")
        ),
        "actionability_present_count": sum(
            1 for r in results if r.get("actionability_present")
        ),
        "tradable_true_without_confirmation_count": sum(
            1 for r in results if r.get("tradable_true_without_confirmation")
        ),
        "low_info_marked_tradable_count": sum(
            1 for r in results if r.get("low_info_marked_tradable")
        ),
        "market_macro_conflict_detected_count": sum(
            1 for r in results if r.get("market_macro_conflict_detected")
        ),
        "conflict_reason_present_count": sum(
            1 for r in results if r.get("conflict_reason_present")
        ),
        "actionability_risk_level_present_count": sum(
            1 for r in results if r.get("actionability_risk_level_present")
        ),
        "invalidation_trigger_present_count": sum(
            1 for r in results if r.get("invalidation_trigger_present")
        ),
        "evidence_sources_present_count": sum(
            1 for r in results if r.get("evidence_sources_present")
        ),
        "evidence_sources_concrete_count": sum(
            1 for r in results if r.get("evidence_sources_concrete")
        ),
        "weak_traceability_but_high_confidence_count": sum(
            1 for r in results if r.get("weak_traceability_but_high_confidence")
        ),
        "proof_set_count": sum(
            int(r.get("proof_set_count") or 0) for r in results
        ),
        "falsifier_count": sum(
            int(r.get("falsifier_count") or 0) for r in results
        ),
    }


# ---------------------------------------------------------------------------
# Before/after engine-quality comparison
# ---------------------------------------------------------------------------
# The eval pass already writes a timestamped JSON per run.  Adding a
# side-by-side comparison against the previous run lets reviewers
# answer "did this rev regress?" without diff-ing two files by hand.
# All read-side; never touches engine logic or production routes.

_EVAL_OUTPUT_GLOB: str = "eval_output_*.json"
_TIMESTAMPED_EVAL_OUTPUT_RE = re.compile(
    r"^eval_output_\d{8}_\d{6}\.json$",
)


def _timestamped_eval_outputs(cwd: str | None = None) -> list[str]:
    pattern = os.path.join(cwd, _EVAL_OUTPUT_GLOB) if cwd else _EVAL_OUTPUT_GLOB
    candidates = glob.glob(pattern)
    return sorted(
        path for path in candidates
        if _TIMESTAMPED_EVAL_OUTPUT_RE.match(os.path.basename(path))
    )


def _find_previous_eval_output(
    exclude: str | None = None,
    *,
    cwd: str | None = None,
) -> str | None:
    """Return the most recent eval_output_*.json path, or None.

    ``exclude`` (typically the path being written this run) is filtered
    out so the comparison reaches back to the prior run rather than the
    file the current run will land at.
    """
    candidates = _timestamped_eval_outputs(cwd=cwd)
    if exclude:
        ex = os.path.abspath(exclude)
        candidates = [p for p in candidates if os.path.abspath(p) != ex]
    return candidates[-1] if candidates else None


def _load_engine_summary(path: str | None) -> dict | None:
    """Read and return the ``engine_quality_summary`` block from a
    saved eval-output JSON, or None when the file is missing /
    unreadable / lacks the block."""
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    summary = data.get("engine_quality_summary")
    return summary if isinstance(summary, dict) else None


def _compute_engine_quality_deltas(
    current: dict, previous: dict | None,
) -> dict[str, int]:
    """Return ``{key: current - previous}`` for each comparable count.

    Returns an empty dict when ``previous`` is None — caller treats that
    as 'no prior run on disk'.  Missing keys on either side default to
    0 so a run that newly emits a key still produces a usable delta.
    """
    if not isinstance(previous, dict):
        return {}
    deltas: dict[str, int] = {}
    for key in _DELTA_KEYS:
        if key not in current and key not in previous:
            continue
        cur = int(current.get(key) or 0)
        prev = int(previous.get(key) or 0)
        deltas[key] = cur - prev
    return deltas


def _format_delta(value: int) -> str:
    """Render a delta with an explicit sign (``+3`` / ``-2`` / ``0``)."""
    if value > 0:
        return f"+{value}"
    return str(value)


def _format_engine_quality_markdown(
    summary: dict,
    *,
    deltas: dict[str, int] | None = None,
    previous_path: str | None = None,
) -> str:
    """Compact markdown summary, optionally annotated with deltas vs
    the previous saved eval output.  Existing callers that pass only
    ``summary`` keep the legacy single-run layout."""
    lines: list[str] = ["## Engine Quality Summary", ""]
    lines.append(f"- Total samples: {summary['total_samples']}")
    for key in _DELTA_KEYS:
        if key not in summary:
            continue
        label = _DELTA_LABELS.get(key, key)
        line = f"- {label}: {summary[key]}"
        if deltas and key in deltas:
            line += f"  (Δ {_format_delta(deltas[key])})"
        lines.append(line)
    tier_counts = summary.get("quality_tier_counts")
    if isinstance(tier_counts, dict):
        ordered = [
            f"{tier} {int(tier_counts.get(tier) or 0)}"
            for tier in ("excellent", "usable", "thin", "poor")
        ]
        lines.append(f"- Quality tiers: {' / '.join(ordered)}")
    if deltas:
        ref = previous_path or "previous run"
        lines.append("")
        lines.append(f"_Deltas vs {ref}._")
    return "\n".join(lines)


def _shape_presence_summary(
    results: list[dict],
    *,
    field_getter,
) -> dict:
    missing_fields: list[str] = []
    for field in ENGINE_PHASE_PARITY_FIELDS:
        if not results or any(field not in field_getter(result) for result in results):
            missing_fields.append(field)
    present_count = len(ENGINE_PHASE_PARITY_FIELDS) - len(missing_fields)
    return {
        "present_count": present_count,
        "missing_count": len(missing_fields),
        "missing_fields": missing_fields,
    }


def _result_engine_emitted_fields(result: dict) -> set[str]:
    emitted = result.get("engine_emitted_fields")
    if isinstance(emitted, list):
        return {
            str(field) for field in emitted
            if isinstance(field, str)
        }
    # Backward-compatible fallback for older eval outputs that predate the
    # explicit engine-emitted list. Current runs should always carry it.
    return {
        field for field in ENGINE_PHASE_PARITY_FIELDS
        if field in result
    }


def _engine_shape_parity_summary(results: list[dict]) -> dict:
    eval_visible = _shape_presence_summary(
        results,
        field_getter=lambda result: set(_eval_visible_fields(result)),
    )
    engine_emitted = _shape_presence_summary(
        results,
        field_getter=_result_engine_emitted_fields,
    )
    return {
        # Legacy top-level aliases stay eval-visible for callers that already
        # read these fields.
        "present_count": eval_visible["present_count"],
        "missing_count": eval_visible["missing_count"],
        "missing_fields": eval_visible["missing_fields"],
        "eval_visible": eval_visible,
        "engine_emitted": engine_emitted,
    }


def _format_shape_block(label: str, block: dict) -> list[str]:
    missing = block.get("missing_fields")
    if isinstance(missing, list) and missing:
        missing_text = ", ".join(f"`{field}`" for field in missing)
    else:
        missing_text = "none"
    return [
        f"### {label}",
        "",
        f"- Present count: {int(block.get('present_count') or 0)}",
        f"- Missing count: {int(block.get('missing_count') or 0)}",
        f"- Missing fields: {missing_text}",
    ]


def _format_engine_shape_parity_markdown(summary: dict) -> str:
    eval_visible = summary.get("eval_visible")
    if not isinstance(eval_visible, dict):
        eval_visible = {
            "present_count": summary.get("present_count") or 0,
            "missing_count": summary.get("missing_count") or 0,
            "missing_fields": summary.get("missing_fields") or [],
        }
    engine_emitted = summary.get("engine_emitted")
    if not isinstance(engine_emitted, dict):
        engine_emitted = {
            "present_count": 0,
            "missing_count": len(ENGINE_PHASE_PARITY_FIELDS),
            "missing_fields": list(ENGINE_PHASE_PARITY_FIELDS),
        }
    lines = [
        "## Engine/API/Eval Shape Parity",
        "",
    ]
    lines.extend(_format_shape_block("Eval-visible fields", eval_visible))
    lines.append("")
    lines.extend(_format_shape_block("Engine-emitted fields", engine_emitted))
    return "\n".join(lines)


EVAL_FLAG_KEYS: tuple[str, ...] = (
    "family_none_on_clear_case",
    "low_info_expected_but_actionable",
    "actionable_but_missing_thesis",
    "actionable_but_missing_chain",
    "actionable_but_missing_asset_rationale",
    "proof_or_falsifier_missing_on_actionable",
)

_EVAL_FLAG_LABELS: dict[str, str] = {
    "family_none_on_clear_case": "Family none on clear case",
    "low_info_expected_but_actionable": "Low-info expected but actionable",
    "actionable_but_missing_thesis": "Actionable but missing thesis",
    "actionable_but_missing_chain": "Actionable but missing chain",
    "actionable_but_missing_asset_rationale": (
        "Actionable but missing asset rationale"
    ),
    "proof_or_falsifier_missing_on_actionable": (
        "Proof or falsifier missing on actionable"
    ),
}


_BAD_CONFIDENCE_FLAG_KEYS: tuple[str, ...] = (
    "high_confidence_without_proof",
    "actionable_without_valid_chain",
    "actionable_without_asset_rationale",
    "actionable_with_family_none",
    "low_information_but_has_assets",
)

_CONSISTENCY_FLAG_KEYS: tuple[str, ...] = (
    "thesis_asset_consistent",
    "thesis_proof_consistent",
    "thesis_falsifier_consistent",
    "chain_ends_in_asset_implication",
    "family_chain_consistent",
    "chain_asset_implication_present",
    "signal_asset_direction_valid",
)


def _result_actionable_for_eval(result: dict) -> bool:
    if result.get("low_information") or result.get("degraded"):
        return False
    confidence = str(result.get("confidence") or "").strip().lower()
    tier = str(result.get("quality_tier") or "").strip().lower()
    return confidence in {"high", "medium"} or tier in {"excellent", "usable"}


def _result_watch_only_for_eval(result: dict) -> bool:
    if result.get("low_information") or result.get("degraded"):
        return False
    for key in (
        "actionability",
        "action",
        "recommendation",
        "decision",
        "validation_status",
        "status",
    ):
        value = str(result.get(key) or "").strip().lower()
        if value in {"watch_only", "watch only", "watch-only"}:
            return True
    return not _result_actionable_for_eval(result)


def _engine_eval_flags(result: dict) -> dict[str, bool]:
    focus = result.get("expected_eval_focus")
    if not isinstance(focus, dict):
        focus = {}
    expected_family = str(focus.get("mechanism_family") or "").strip().lower()
    expected_low_info = focus.get("should_be_low_information") is True
    clear_family_case = bool(expected_family and expected_family != "none")
    actual_family = str(result.get("mechanism_family") or "none").strip().lower()
    actionable = _result_actionable_for_eval(result)

    return {
        "family_none_on_clear_case": (
            clear_family_case
            and not expected_low_info
            and actual_family == "none"
        ),
        "low_info_expected_but_actionable": expected_low_info and actionable,
        "actionable_but_missing_thesis": (
            actionable and not result.get("primary_thesis_present")
        ),
        "actionable_but_missing_chain": (
            actionable and not result.get("transmission_chain_valid")
        ),
        "actionable_but_missing_asset_rationale": (
            actionable and not result.get("asset_why_lines_present")
        ),
        "proof_or_falsifier_missing_on_actionable": (
            actionable
            and (
                int(result.get("proof_set_count") or 0) == 0
                or int(result.get("falsifier_count") or 0) == 0
            )
        ),
    }


def _engine_eval_red_flags(results: list[dict]) -> dict[str, dict]:
    summary: dict[str, dict] = {}
    for key in EVAL_FLAG_KEYS:
        sample_ids = [
            str(result.get("id"))
            for result in results
            if isinstance(result.get("eval_flags"), dict)
            and result["eval_flags"].get(key)
        ]
        summary[key] = {"count": len(sample_ids), "sample_ids": sample_ids}
    return summary


def _format_engine_eval_red_flags_markdown(summary: dict[str, dict]) -> str:
    lines = ["## Engine Eval Red Flags", ""]
    for key in EVAL_FLAG_KEYS:
        item = summary.get(key) or {}
        count = int(item.get("count") or 0)
        sample_ids = item.get("sample_ids") or []
        ids = ", ".join(str(sample_id) for sample_id in sample_ids) or "-"
        label = _EVAL_FLAG_LABELS.get(key, key)
        lines.append(f"- {label}: {count} ({ids})")
    return "\n".join(lines)


def _result_red_flag_count(result: dict) -> int:
    flags = result.get("eval_flags")
    if not isinstance(flags, dict):
        return 0
    return sum(1 for key in EVAL_FLAG_KEYS if flags.get(key))


def _result_family_none_clear_case_flagged(result: dict) -> bool:
    flags = result.get("eval_flags")
    if isinstance(flags, dict):
        return bool(flags.get("family_none_on_clear_case"))
    return _engine_eval_flags(result).get("family_none_on_clear_case", False)


def _bad_confidence_flag_count(result: dict) -> int:
    return sum(1 for key in _BAD_CONFIDENCE_FLAG_KEYS if result.get(key))


def _consistency_flag_count(result: dict) -> int:
    total = sum(1 for key in _CONSISTENCY_FLAG_KEYS if result.get(key) is False)
    for key in (
        "rejected_asset_count",
        "primary_asset_contradiction_count",
        "role_channel_mismatch_count",
        "generic_chain_hops_count",
    ):
        total += int(result.get(key) or 0)
    for key in (
        "coherence_rejection_triggered",
        "beneficiary_signal_conflict",
        "weak_signal_only_support",
        "subtype_dropped_or_warned",
        "high_noise_override_detected",
    ):
        if result.get(key):
            total += 1
    return total


def _engine_phase_audit_readiness(results: list[dict]) -> dict:
    total = len(results)
    falsifier_covered = sum(
        1 for result in results if int(result.get("falsifier_count") or 0) > 0
    )
    return {
        "total_samples": total,
        "actionable_outputs_count": sum(
            1 for result in results if _result_actionable_for_eval(result)
        ),
        "watch_only_outputs_count": sum(
            1 for result in results if _result_watch_only_for_eval(result)
        ),
        "low_information_outputs_count": sum(
            1 for result in results if result.get("low_information")
        ),
        "family_none_clear_case_flags": sum(
            1 for result in results if _result_family_none_clear_case_flagged(result)
        ),
        "bad_confidence_flags": sum(
            _bad_confidence_flag_count(result) for result in results
        ),
        "generic_rationale_flags": sum(
            1 for result in results if result.get("rationale_too_generic")
        ),
        "consistency_flags": sum(
            _consistency_flag_count(result) for result in results
        ),
        "falsification_counterfactual_covered_count": falsifier_covered,
        "falsification_counterfactual_missing_count": total - falsifier_covered,
    }


def _format_engine_phase_audit_readiness_markdown(summary: dict) -> str:
    total = int(summary.get("total_samples") or 0)
    covered = int(
        summary.get("falsification_counterfactual_covered_count") or 0
    )
    missing = int(
        summary.get("falsification_counterfactual_missing_count") or 0
    )
    return "\n".join([
        "## Engine Phase Audit Readiness",
        "",
        f"- Actionable outputs: {int(summary.get('actionable_outputs_count') or 0)}",
        f"- Watch-only outputs: {int(summary.get('watch_only_outputs_count') or 0)}",
        f"- Low-information outputs: {int(summary.get('low_information_outputs_count') or 0)}",
        f"- Family-none clear-case flags: {int(summary.get('family_none_clear_case_flags') or 0)}",
        f"- Bad-confidence flags: {int(summary.get('bad_confidence_flags') or 0)}",
        f"- Generic-rationale flags: {int(summary.get('generic_rationale_flags') or 0)}",
        f"- Consistency flags: {int(summary.get('consistency_flags') or 0)}",
        (
            "- Falsification/counterfactual coverage: "
            f"{covered} / {total} covered ({missing} missing)"
        ),
    ])


def _ready_for_engine_audit(results: list[dict]) -> dict:
    total = len(results)
    conflict_count = sum(
        1 for result in results if result.get("market_macro_conflict_detected")
    )
    conflict_reason_count = sum(
        1 for result in results if result.get("conflict_reason_present")
    )
    falsifier_covered = sum(
        1 for result in results if int(result.get("falsifier_count") or 0) > 0
    )
    failure_count = sum(
        1
        for result in results
        if result.get("tradable_true_without_confirmation")
        or result.get("low_info_marked_tradable")
        or result.get("rationale_too_generic")
        or (
            result.get("market_macro_conflict_detected")
            and not result.get("conflict_reason_present")
        )
        or int(result.get("falsifier_count") or 0) == 0
    )
    return {
        "total_samples": total,
        "actionability_present_pass_count": sum(
            1 for result in results if result.get("actionability_present")
        ),
        "actionability_present_fail_count": sum(
            1 for result in results if not result.get("actionability_present")
        ),
        "tradable_confirmation_pass_count": sum(
            1
            for result in results
            if not result.get("tradable_true_without_confirmation")
        ),
        "tradable_confirmation_fail_count": sum(
            1
            for result in results
            if result.get("tradable_true_without_confirmation")
        ),
        "low_info_tradable_pass_count": sum(
            1 for result in results if not result.get("low_info_marked_tradable")
        ),
        "low_info_tradable_fail_count": sum(
            1 for result in results if result.get("low_info_marked_tradable")
        ),
        "conflict_reason_pass_count": conflict_reason_count,
        "conflict_reason_fail_count": max(conflict_count - conflict_reason_count, 0),
        "generic_rationale_pass_count": sum(
            1 for result in results if not result.get("rationale_too_generic")
        ),
        "generic_rationale_fail_count": sum(
            1 for result in results if result.get("rationale_too_generic")
        ),
        "falsification_pass_count": falsifier_covered,
        "falsification_fail_count": total - falsifier_covered,
        "sample_pass_count": max(total - failure_count, 0),
        "sample_fail_count": failure_count,
    }


def _format_ready_for_engine_audit_markdown(summary: dict) -> str:
    total = int(summary.get("total_samples") or 0)

    def pair(pass_key: str, fail_key: str) -> str:
        passed = int(summary.get(pass_key) or 0)
        failed = int(summary.get(fail_key) or 0)
        return f"pass {passed} / fail {failed}"

    return "\n".join([
        "## Ready for Engine Audit",
        "",
        f"- Overall samples: {pair('sample_pass_count', 'sample_fail_count')} / total {total}",
        f"- Actionability field: {pair('actionability_present_pass_count', 'actionability_present_fail_count')}",
        f"- Tradable needs confirmation: {pair('tradable_confirmation_pass_count', 'tradable_confirmation_fail_count')}",
        f"- Low-info not tradable: {pair('low_info_tradable_pass_count', 'low_info_tradable_fail_count')}",
        f"- Conflict reason coverage: {pair('conflict_reason_pass_count', 'conflict_reason_fail_count')}",
        f"- Rationale specificity: {pair('generic_rationale_pass_count', 'generic_rationale_fail_count')}",
        f"- Falsification coverage: {pair('falsification_pass_count', 'falsification_fail_count')}",
    ])


def _focus_metadata(result: dict) -> dict:
    focus = result.get("expected_eval_focus")
    return focus if isinstance(focus, dict) else {}


def _focus_family(focus: dict) -> str:
    family = str(focus.get("mechanism_family") or "").strip().lower()
    return family or "unknown"


def _focus_channels(focus: dict) -> list[str]:
    channels = focus.get("likely_channels")
    if not isinstance(channels, list):
        return []
    out: list[str] = []
    for channel in channels:
        if isinstance(channel, str) and channel.strip():
            out.append(channel.strip().lower())
    return out


def _ensure_focus_row(rows: dict, key: str) -> dict:
    if key not in rows:
        rows[key] = {
            "sample_count": 0,
            "sample_ids": [],
        }
    return rows[key]


def _engine_expected_focus_summary(results: list[dict]) -> dict:
    family_rows: dict[str, dict] = {}
    channel_rows: dict[str, dict] = {}
    low_info_rows: dict[str, dict] = {
        "expected_low_information": {
            "sample_count": 0,
            "actual_low_information_count": 0,
            "actionable_count": 0,
            "red_flag_count": 0,
            "sample_ids": [],
        },
        "expected_not_low_information": {
            "sample_count": 0,
            "actual_low_information_count": 0,
            "actionable_count": 0,
            "red_flag_count": 0,
            "sample_ids": [],
        },
    }
    red_flags_by_family: dict[str, dict] = {}

    for result in results:
        focus = _focus_metadata(result)
        if not focus:
            continue
        sample_id = str(result.get("id") or "")
        family = _focus_family(focus)
        actual_family = str(result.get("mechanism_family") or "none").strip().lower()
        red_flag_count = _result_red_flag_count(result)

        family_row = _ensure_focus_row(family_rows, family)
        family_row.setdefault("actual_family_match_count", 0)
        family_row.setdefault("actual_low_information_count", 0)
        family_row.setdefault("red_flag_count", 0)
        family_row["sample_count"] += 1
        family_row["sample_ids"].append(sample_id)
        if actual_family == family:
            family_row["actual_family_match_count"] += 1
        if result.get("low_information"):
            family_row["actual_low_information_count"] += 1
        family_row["red_flag_count"] += red_flag_count

        for channel in _focus_channels(focus):
            channel_row = _ensure_focus_row(channel_rows, channel)
            channel_row.setdefault("actual_low_information_count", 0)
            channel_row.setdefault("strong_causal_chain_count", 0)
            channel_row.setdefault("red_flag_count", 0)
            channel_row["sample_count"] += 1
            channel_row["sample_ids"].append(sample_id)
            if result.get("low_information"):
                channel_row["actual_low_information_count"] += 1
            if result.get("causal_strength") == "strong":
                channel_row["strong_causal_chain_count"] += 1
            channel_row["red_flag_count"] += red_flag_count

        expected_low_info = focus.get("should_be_low_information") is True
        low_info_key = (
            "expected_low_information"
            if expected_low_info
            else "expected_not_low_information"
        )
        low_info_row = low_info_rows[low_info_key]
        low_info_row["sample_count"] += 1
        low_info_row["sample_ids"].append(sample_id)
        if result.get("low_information"):
            low_info_row["actual_low_information_count"] += 1
        if _result_actionable_for_eval(result):
            low_info_row["actionable_count"] += 1
        low_info_row["red_flag_count"] += red_flag_count

        red_row = _ensure_focus_row(red_flags_by_family, family)
        red_row.setdefault("total_red_flags", 0)
        for key in EVAL_FLAG_KEYS:
            red_row.setdefault(key, 0)
        red_row["sample_count"] += 1
        red_row["sample_ids"].append(sample_id)
        red_row["total_red_flags"] += red_flag_count
        flags = result.get("eval_flags") if isinstance(result.get("eval_flags"), dict) else {}
        for key in EVAL_FLAG_KEYS:
            if flags.get(key):
                red_row[key] += 1

    return {
        "family_coverage": family_rows,
        "channel_coverage": channel_rows,
        "low_information_expected_vs_actual": low_info_rows,
        "red_flags_by_expected_family": red_flags_by_family,
    }


def _table_ids(sample_ids: list) -> str:
    return ", ".join(str(sample_id) for sample_id in sample_ids) or "-"


def _format_engine_expected_focus_markdown(summary: dict) -> str:
    lines = ["## Expected Focus Coverage", ""]

    family_rows = summary.get("family_coverage") or {}
    lines.extend([
        "### Family Coverage",
        "",
        "| expected_family | samples | actual_family_match | actual_low_info | red_flags | sample_ids |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for family, row in sorted(family_rows.items()):
        lines.append(
            f"| {family} | {int(row.get('sample_count') or 0)} "
            f"| {int(row.get('actual_family_match_count') or 0)} "
            f"| {int(row.get('actual_low_information_count') or 0)} "
            f"| {int(row.get('red_flag_count') or 0)} "
            f"| {_table_ids(row.get('sample_ids') or [])} |"
        )
    if not family_rows:
        lines.append("| - | 0 | 0 | 0 | 0 | - |")

    channel_rows = summary.get("channel_coverage") or {}
    lines.extend([
        "",
        "### Channel Coverage",
        "",
        "| expected_channel | samples | strong_causal_chain | actual_low_info | red_flags | sample_ids |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for channel, row in sorted(channel_rows.items()):
        lines.append(
            f"| {channel} | {int(row.get('sample_count') or 0)} "
            f"| {int(row.get('strong_causal_chain_count') or 0)} "
            f"| {int(row.get('actual_low_information_count') or 0)} "
            f"| {int(row.get('red_flag_count') or 0)} "
            f"| {_table_ids(row.get('sample_ids') or [])} |"
        )
    if not channel_rows:
        lines.append("| - | 0 | 0 | 0 | 0 | - |")

    low_rows = summary.get("low_information_expected_vs_actual") or {}
    lines.extend([
        "",
        "### Low-Information Expected Vs Actual",
        "",
        "| expectation | samples | actual_low_info | actionable | red_flags | sample_ids |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for key in ("expected_low_information", "expected_not_low_information"):
        row = low_rows.get(key) or {}
        label = key.replace("_", " ")
        lines.append(
            f"| {label} | {int(row.get('sample_count') or 0)} "
            f"| {int(row.get('actual_low_information_count') or 0)} "
            f"| {int(row.get('actionable_count') or 0)} "
            f"| {int(row.get('red_flag_count') or 0)} "
            f"| {_table_ids(row.get('sample_ids') or [])} |"
        )

    red_rows = summary.get("red_flags_by_expected_family") or {}
    lines.extend([
        "",
        "### Red Flags By Expected Family",
        "",
        "| expected_family | samples | total_red_flags | family_none | low_info_actionable | missing_thesis | missing_chain | missing_asset_rationale | missing_proof_or_falsifier |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for family, row in sorted(red_rows.items()):
        lines.append(
            f"| {family} | {int(row.get('sample_count') or 0)} "
            f"| {int(row.get('total_red_flags') or 0)} "
            f"| {int(row.get('family_none_on_clear_case') or 0)} "
            f"| {int(row.get('low_info_expected_but_actionable') or 0)} "
            f"| {int(row.get('actionable_but_missing_thesis') or 0)} "
            f"| {int(row.get('actionable_but_missing_chain') or 0)} "
            f"| {int(row.get('actionable_but_missing_asset_rationale') or 0)} "
            f"| {int(row.get('proof_or_falsifier_missing_on_actionable') or 0)} |"
        )
    if not red_rows:
        lines.append("| - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |")

    return "\n".join(lines)


def _red_flag_count(summary: dict | None) -> int:
    if not isinstance(summary, dict):
        return 0
    total = 0
    for value in summary.values():
        if isinstance(value, dict):
            total += int(value.get("count") or 0)
    return total


def _run_index_entry(output_file: str, output: dict) -> dict:
    engine_summary = output.get("engine_quality_summary") or {}
    return {
        "output_file": output_file,
        "timestamp": output.get("generated_at"),
        "preset": output.get("preset_name") or output.get("preset"),
        "sample_count": int(output.get("num_samples") or 0),
        "low_information_count": int(
            engine_summary.get("low_information_count") or 0
        ),
        "family_none_count": int(engine_summary.get("family_none_count") or 0),
        "red_flag_count": _red_flag_count(output.get("engine_eval_red_flags")),
    }


def _load_run_index(path: str = EVAL_RUN_INDEX_FILE) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []
    runs = data.get("runs") if isinstance(data, dict) else data
    if not isinstance(runs, list):
        return []
    return [run for run in runs if isinstance(run, dict)]


def _write_run_index(runs: list[dict], path: str = EVAL_RUN_INDEX_FILE) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump({"runs": runs}, file, indent=2, ensure_ascii=False)


def _update_run_index(
    output_file: str,
    output: dict,
    *,
    path: str = EVAL_RUN_INDEX_FILE,
) -> list[dict]:
    entry = _run_index_entry(output_file, output)
    runs = [
        run for run in _load_run_index(path)
        if run.get("output_file") != output_file
    ]
    runs.append(entry)
    runs.sort(key=lambda run: (str(run.get("timestamp") or ""), str(run.get("output_file") or "")))
    _write_run_index(runs, path)
    return runs


def _load_eval_output(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _newest_eval_outputs(limit: int = 2, *, cwd: str | None = None) -> list[str]:
    return _timestamped_eval_outputs(cwd=cwd)[-limit:]


def _format_count_delta(label: str, current: int, previous: int) -> str:
    delta = current - previous
    return f"- {label}: {current}  (Δ {_format_delta(delta)})"


def _format_latest_eval_comparison(
    previous_path: str,
    previous: dict,
    current_path: str,
    current: dict,
) -> str:
    previous_entry = _run_index_entry(previous_path, previous)
    current_entry = _run_index_entry(current_path, current)
    lines = ["## Latest Eval Comparison", ""]
    lines.append(
        f"- Previous: {previous_path} "
        f"({previous_entry.get('timestamp')}, preset {previous_entry.get('preset')})"
    )
    lines.append(
        f"- Current: {current_path} "
        f"({current_entry.get('timestamp')}, preset {current_entry.get('preset')})"
    )
    lines.append("")
    for key, label in (
        ("sample_count", "Sample count"),
        ("low_information_count", "Low-information count"),
        ("family_none_count", "Family-none count"),
        ("red_flag_count", "Red-flag count"),
    ):
        lines.append(
            _format_count_delta(
                label,
                int(current_entry.get(key) or 0),
                int(previous_entry.get(key) or 0),
            )
        )
    return "\n".join(lines)


def compare_latest_eval_runs(*, cwd: str | None = None) -> str:
    paths = _newest_eval_outputs(2, cwd=cwd)
    loaded: list[tuple[str, dict]] = []
    for path in paths:
        data = _load_eval_output(path)
        if data is not None:
            loaded.append((path, data))
    if len(loaded) < 2:
        return "Need at least two timestamped eval_output_*.json runs to compare."
    (previous_path, previous), (current_path, current) = loaded[-2:]
    return _format_latest_eval_comparison(
        previous_path, previous, current_path, current,
    )


def run_one(sample: dict, model: str | None = None) -> dict:
    """Run one sample headline through the current evaluation flow.

    Mirrors the live /analyze pipeline as closely as possible:
      1. macro context injection (same prompt as production)
      2. pre-market overlays (policy_sensitivity … inventory_context)
      3. market_check (with event_date when the sample supplies one)
      4. post-market overlays (surprise_vs_anticipation … narrative_divergence)
    """
    from analyze_event import analyze_event
    from classify import classify_persistence, classify_stage
    from market_check import (
        market_check,
        build_macro_context_for_prompt,
        compute_rates_context,
        compute_stress_regime,
        classify_policy_sensitivity,
        classify_inventory_context,
    )
    from real_yield_context import build_real_yield_context
    from policy_constraint import compute_policy_constraint
    from shock_decomposition import compute_shock_decomposition
    from reaction_function_divergence import compute_reaction_function_divergence
    from regime_vector import build_regime_vector
    from surprise_vs_anticipation import compute_surprise_vs_anticipation
    from terms_of_trade import compute_terms_of_trade
    from reserve_stress_overlay import compute_reserve_stress
    from narrative_divergence import compute_narrative_divergence
    from db import find_historical_analogs, get_confidence_calibration_stats

    headline = sample["headline"]
    stage = classify_stage(headline)
    persistence = classify_persistence(headline)
    expected_stage = sample.get("expected_stage")
    expected_persistence = sample.get("expected_persistence")
    stage_match = expected_stage is not None and stage == expected_stage
    persistence_match = (
        expected_persistence is not None
        and persistence == expected_persistence
    )

    # --- 1. Macro context injection (same prompt enrichment as live path) ---
    macro_ctx = ""
    try:
        macro_ctx = build_macro_context_for_prompt()
    except Exception:
        pass

    analysis = analyze_event(headline, stage, persistence,
                             macro_context=macro_ctx, model=model)

    mech_text = f"{analysis.get('what_changed', '')} {analysis.get('mechanism_summary', '')}"

    # --- 2. Pre-market overlays ---
    rates = None
    stress = None
    try:
        rates = compute_rates_context()
        analysis["policy_sensitivity"] = classify_policy_sensitivity(rates["regime"], mech_text)
    except Exception:
        analysis["policy_sensitivity"] = {}
    try:
        analysis["real_yield_context"] = build_real_yield_context(headline, mech_text, rates)
    except Exception:
        analysis["real_yield_context"] = {}
    try:
        stress = compute_stress_regime()
    except Exception:
        stress = None
    try:
        analysis["policy_constraint"] = compute_policy_constraint(headline, mech_text, rates, stress, snapshots=None)
    except Exception:
        analysis["policy_constraint"] = {}
    try:
        analysis["shock_decomposition"] = compute_shock_decomposition(rates, stress, snapshots=None)
    except Exception:
        analysis["shock_decomposition"] = {}
    try:
        analysis["reaction_function_divergence"] = compute_reaction_function_divergence(headline, mech_text, rates, stress, snapshots=None)
    except Exception:
        analysis["reaction_function_divergence"] = {}
    try:
        regime_vec = build_regime_vector(rates, stress, None)
    except Exception:
        regime_vec = None
    analysis["regime_snapshot"] = regime_vec or {}
    inv_text = f"{headline} {mech_text}"
    try:
        analysis["inventory_context"] = classify_inventory_context(inv_text)
    except Exception:
        analysis["inventory_context"] = {}
    analysis["historical_analogs"] = find_historical_analogs(
        headline,
        mechanism=analysis.get("mechanism_summary", ""),
        stage=stage,
        persistence=persistence,
        exclude_headline=headline,
        current_regime_vector=regime_vec,
    )

    # --- 3. Market check (event_date from sample when available) ---
    event_date = sample.get("event_date")
    market = market_check(
        analysis["beneficiary_tickers"],
        analysis["loser_tickers"],
        event_date=event_date,
    )

    # --- 4. Post-market overlays ---
    try:
        analysis["surprise_vs_anticipation"] = compute_surprise_vs_anticipation(
            stage, tickers=market.get("tickers", []), stress_regime=stress)
    except Exception:
        analysis["surprise_vs_anticipation"] = {}
    try:
        analysis["terms_of_trade"] = compute_terms_of_trade(
            headline, mech_text,
            inventory_context=analysis.get("inventory_context", {}),
            snapshots=None, stress_regime=stress)
    except Exception:
        analysis["terms_of_trade"] = {}
    try:
        analysis["reserve_stress"] = compute_reserve_stress(
            headline, mech_text,
            terms_of_trade=analysis.get("terms_of_trade", {}),
            rates_context=rates, stress_regime=stress)
    except Exception:
        analysis["reserve_stress"] = {}
    try:
        analysis["narrative_divergence"] = compute_narrative_divergence(
            market.get("tickers", []),
            analysis.get("confidence", "low"),
            get_confidence_calibration_stats(),
        )
    except Exception:
        analysis["narrative_divergence"] = {}

    quality = _quality_score(analysis)
    engine_quality = _engine_quality_checklist(analysis, quality)

    result = {
        "id": sample["id"],
        "category": sample["category"],
        "headline": headline,
        "stage": stage,
        "persistence": persistence,
        "expected_stage": expected_stage,
        "expected_persistence": expected_persistence,
        "expected_eval_focus": sample.get("expected_eval_focus"),
        "stage_match": stage_match,
        "persistence_match": persistence_match,
        "what_changed": analysis["what_changed"],
        "mechanism_summary": analysis["mechanism_summary"],
        "beneficiaries": analysis["beneficiaries"],
        "losers": analysis["losers"],
        "beneficiary_tickers": analysis["beneficiary_tickers"],
        "loser_tickers": analysis["loser_tickers"],
        "assets_to_watch": analysis["assets_to_watch"],
        "confidence": analysis["confidence"],
        "transmission_chain": analysis.get("transmission_chain", []),
        "if_persists": analysis.get("if_persists", {}),
        "currency_channel": analysis.get("currency_channel", {}),
        "validation_warnings": analysis.get("validation_warnings", []),
        "mechanism_subtype": analysis.get("mechanism_subtype") or "",
        "quality_warnings": analysis.get("quality_warnings", []),
        **_engine_phase_blocks_for_result(analysis),
        **_status_blocks_for_result(analysis),
        "degraded": bool(analysis.get("degraded")),
        "quality": quality,
        **engine_quality,
        "market_note": market["note"],
        "market_tickers": market["tickers"],
        # Overlay fields — same set the live /analyze endpoint persists and
        # the frontend consumes.  Present in output for manual review and
        # model comparison; not scored by _quality_score.
        "policy_sensitivity": analysis.get("policy_sensitivity", {}),
        "real_yield_context": analysis.get("real_yield_context", {}),
        "policy_constraint": analysis.get("policy_constraint", {}),
        "shock_decomposition": analysis.get("shock_decomposition", {}),
        "reaction_function_divergence": analysis.get("reaction_function_divergence", {}),
        "regime_snapshot": analysis.get("regime_snapshot", {}),
        "inventory_context": analysis.get("inventory_context", {}),
        "surprise_vs_anticipation": analysis.get("surprise_vs_anticipation", {}),
        "terms_of_trade": analysis.get("terms_of_trade", {}),
        "reserve_stress": analysis.get("reserve_stress", {}),
        "narrative_divergence": analysis.get("narrative_divergence", {}),
    }
    result["engine_emitted_fields"] = _engine_emitted_fields(analysis)
    result["eval_visible_fields"] = _eval_visible_fields(result)
    result["eval_flags"] = _engine_eval_flags(result)
    return result


def main() -> None:
    args = parse_args()
    if args.compare_latest:
        print(compare_latest_eval_runs())
        return

    samples = load_samples()
    selected = select_samples(
        samples,
        preset=args.preset,
        ids=args.ids,
        limit=args.limit,
    )
    selected_ids = selected_sample_ids(selected)
    skipped_ids = skipped_sample_ids(samples, selected)

    model = args.model
    if model:
        print(f"[eval] Using model: {model}")

    results = []
    for index, sample in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] {sample['headline']}")
        results.append(run_one(sample, model=model))

    stage_correct = sum(
        1 for result in results
        if result["expected_stage"] is not None and result["stage_match"]
    )
    stage_wrong = sum(
        1 for result in results
        if result["expected_stage"] is not None and not result["stage_match"]
    )
    persistence_correct = sum(
        1
        for result in results
        if result["expected_persistence"] is not None and result["persistence_match"]
    )
    persistence_wrong = sum(
        1
        for result in results
        if result["expected_persistence"] is not None and not result["persistence_match"]
    )

    from analyze_event import _DEFAULT_MODEL
    effective_model = model or os.getenv("ANTHROPIC_MODEL", _DEFAULT_MODEL)

    # Aggregate quality scores for the before/after inspection pass.
    total_score = sum(r["quality"]["score"] for r in results)
    max_possible = len(results) * len(QUALITY_CHECKS) if results else 0
    avg_score = (total_score / len(results)) if results else 0.0
    degraded_count = sum(1 for r in results if r["degraded"])
    warning_count = sum(1 for r in results if r["validation_warnings"])
    check_totals = {check: 0 for check in QUALITY_CHECKS}
    for r in results:
        for check, ok in r["quality"]["breakdown"].items():
            if ok:
                check_totals[check] += 1

    quality_summary = {
        "total_score": total_score,
        "max_possible": max_possible,
        "avg_score": round(avg_score, 2),
        "avg_score_pct": round((avg_score / len(QUALITY_CHECKS)) * 100, 1) if results else 0.0,
        "degraded_count": degraded_count,
        "warning_count": warning_count,
        "check_totals": check_totals,
    }
    engine_quality_summary = _engine_quality_summary(results)
    engine_eval_red_flags = _engine_eval_red_flags(results)
    engine_eval_red_flags_markdown = _format_engine_eval_red_flags_markdown(
        engine_eval_red_flags,
    )
    engine_phase_audit_readiness = _engine_phase_audit_readiness(results)
    engine_phase_audit_readiness_markdown = (
        _format_engine_phase_audit_readiness_markdown(
            engine_phase_audit_readiness,
        )
    )
    ready_for_engine_audit = _ready_for_engine_audit(results)
    ready_for_engine_audit_markdown = _format_ready_for_engine_audit_markdown(
        ready_for_engine_audit,
    )
    expected_focus_summary = _engine_expected_focus_summary(results)
    expected_focus_markdown = _format_engine_expected_focus_markdown(
        expected_focus_summary,
    )
    engine_shape_parity = _engine_shape_parity_summary(results)
    engine_shape_parity_markdown = _format_engine_shape_parity_markdown(
        engine_shape_parity,
    )

    # Resolve the output path FIRST so the previous-run lookup can
    # exclude it deterministically — important when the eval is
    # re-invoked within the same minute.
    output_file = make_output_file()

    # Before/after comparison — read-only against the most recent
    # prior eval_output_*.json on disk.  When no prior run exists
    # (first invocation) the deltas block is empty and the markdown
    # falls back to the legacy single-run layout.
    previous_run_path = _find_previous_eval_output(exclude=output_file)
    previous_summary = _load_engine_summary(previous_run_path)
    engine_quality_deltas = _compute_engine_quality_deltas(
        engine_quality_summary, previous_summary,
    )
    engine_quality_markdown = _format_engine_quality_markdown(
        engine_quality_summary,
        deltas=engine_quality_deltas or None,
        previous_path=previous_run_path,
    )

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": effective_model,
        "source_file": SAMPLE_FILE,
        "preset": args.preset,
        "preset_name": args.preset or "default",
        "selected_sample_ids": selected_ids,
        "skipped_sample_ids": skipped_ids,
        "num_samples": len(selected),
        "summary": {
            "total": len(selected),
            "stage_correct": stage_correct,
            "stage_wrong": stage_wrong,
            "persistence_correct": persistence_correct,
            "persistence_wrong": persistence_wrong,
        },
        "quality_summary": quality_summary,
        "engine_quality_fields": list(ENGINE_QUALITY_FIELDS),
        "engine_quality_summary": engine_quality_summary,
        # NEW additive comparison block — existing keys above unchanged.
        "engine_quality_previous_run": previous_run_path,
        "engine_quality_deltas": engine_quality_deltas,
        "engine_quality_markdown": engine_quality_markdown,
        "engine_eval_red_flags": engine_eval_red_flags,
        "engine_eval_red_flags_markdown": engine_eval_red_flags_markdown,
        "engine_phase_audit_readiness": engine_phase_audit_readiness,
        "engine_phase_audit_readiness_markdown":
            engine_phase_audit_readiness_markdown,
        "ready_for_engine_audit": ready_for_engine_audit,
        "ready_for_engine_audit_markdown": ready_for_engine_audit_markdown,
        "expected_focus_summary": expected_focus_summary,
        "expected_focus_markdown": expected_focus_markdown,
        "engine_shape_parity": engine_shape_parity,
        "engine_shape_parity_markdown": engine_shape_parity_markdown,
        "results": results,
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    _update_run_index(output_file, output)

    print(f"\nEval complete. {len(selected)} sample(s). Output → {output_file}")
    print(f"Stage:       {stage_correct} correct  |  {stage_wrong} wrong")
    print(f"Persistence: {persistence_correct} correct  |  {persistence_wrong} wrong")
    print(
        f"Quality:     {total_score}/{max_possible}  "
        f"(avg {avg_score:.2f}/{len(QUALITY_CHECKS)}, "
        f"{quality_summary['avg_score_pct']}%)"
    )
    print(f"Degraded:    {degraded_count} / {len(results)}")
    print(f"Warnings:    {warning_count} / {len(results)}")
    print()
    print(engine_quality_markdown)
    print()
    print(engine_eval_red_flags_markdown)
    print()
    print(engine_phase_audit_readiness_markdown)
    print()
    print(ready_for_engine_audit_markdown)
    print()
    print(expected_focus_markdown)
    print()
    print(engine_shape_parity_markdown)
    print("Per-check pass counts:")
    for check in QUALITY_CHECKS:
        print(f"  {check:<32} {check_totals[check]} / {len(results)}")


if __name__ == "__main__":
    main()
