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
import json
import os
from datetime import datetime

SAMPLE_FILE = "sample_events.json"

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


def parse_args() -> argparse.Namespace:
    """Parse lightweight CLI options for cheaper evaluation subsets."""
    parser = argparse.ArgumentParser(
        description="Run the sample evaluation set and save a timestamped eval_output_*.json file.",
    )
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument(
        "--preset",
        choices=["canary"],
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


def select_samples(
    samples: list[dict],
    preset: str | None = None,
    ids: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Select all samples or a smaller subset based on CLI options."""
    if limit is not None and limit < 1:
        raise ValueError("--limit must be at least 1.")

    if preset == "canary":
        ids = CANARY_SAMPLE_IDS

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


def run_one(sample: dict, model: str | None = None) -> dict:
    """Run one sample headline through the current evaluation flow."""
    from analyze_event import analyze_event
    from classify import classify_persistence, classify_stage
    from market_check import market_check

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
    analysis = analyze_event(headline, stage, persistence, model=model)
    market = market_check(analysis["beneficiary_tickers"], analysis["loser_tickers"])
    quality = _quality_score(analysis)

    return {
        "id": sample["id"],
        "category": sample["category"],
        "headline": headline,
        "stage": stage,
        "persistence": persistence,
        "expected_stage": expected_stage,
        "expected_persistence": expected_persistence,
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
        "degraded": bool(analysis.get("degraded")),
        "quality": quality,
        "market_note": market["note"],
        "market_tickers": market["tickers"],
    }


def main() -> None:
    args = parse_args()
    samples = load_samples()
    selected = select_samples(
        samples,
        preset=args.preset,
        ids=args.ids,
        limit=args.limit,
    )

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

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": effective_model,
        "source_file": SAMPLE_FILE,
        "num_samples": len(selected),
        "summary": {
            "total": len(selected),
            "stage_correct": stage_correct,
            "stage_wrong": stage_wrong,
            "persistence_correct": persistence_correct,
            "persistence_wrong": persistence_wrong,
        },
        "quality_summary": quality_summary,
        "results": results,
    }

    output_file = make_output_file()
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

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
    print("Per-check pass counts:")
    for check in QUALITY_CHECKS:
        print(f"  {check:<32} {check_totals[check]} / {len(results)}")


if __name__ == "__main__":
    main()
