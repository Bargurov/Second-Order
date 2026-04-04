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
from datetime import datetime

SAMPLE_FILE = "sample_events.json"
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


def run_one(sample: dict) -> dict:
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
    analysis = analyze_event(headline, stage, persistence)
    market = market_check(analysis["beneficiary_tickers"], analysis["loser_tickers"])

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

    results = []
    for index, sample in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] {sample['headline']}")
        results.append(run_one(sample))

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

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": SAMPLE_FILE,
        "num_samples": len(selected),
        "summary": {
            "total": len(selected),
            "stage_correct": stage_correct,
            "stage_wrong": stage_wrong,
            "persistence_correct": persistence_correct,
            "persistence_wrong": persistence_wrong,
        },
        "results": results,
    }

    output_file = make_output_file()
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nEval complete. {len(selected)} sample(s). Output → {output_file}")
    print(f"Stage:       {stage_correct} correct  |  {stage_wrong} wrong")
    print(f"Persistence: {persistence_correct} correct  |  {persistence_wrong} wrong")


if __name__ == "__main__":
    main()
