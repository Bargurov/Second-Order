# Evaluation Guide

This file describes a simple manual review process for the current V1.5
pipeline. The goal is not to produce a formal benchmark. The goal is to check
whether the system is directionally useful on a small, varied set of
geopolitical and policy headlines.

## Sample set

Use the headlines in `sample_events.json` as a reusable input set for manual
evaluation. The sample includes trade, sanctions, military, diplomacy,
energy, shipping, central bank, and industrial policy cases. Each sample now
also carries lightweight expected labels for `stage` and `persistence`.

## How to use it

1. Run the evaluation helper:

```powershell
python eval.py --preset canary
python eval.py
python eval.py --ids sample_001 sample_005
python eval.py --limit 6
```

2. Open the newest timestamped output file, such as `eval_output_20260403_154500.json`.
3. Review `stage` / `persistence` against `expected_stage` / `expected_persistence`.
4. Review `stage_match`, `persistence_match`, and the top-level correct/wrong counts.
5. Review mechanism, ticker lists, and market output manually.

The JSON output format stays the same for full runs and subset runs. Only the
selected sample count and output filename change.

The canary preset uses `sample_001`, `sample_004`, `sample_007`, `sample_011`,
`sample_015`, and `sample_018` because together they cover anticipation,
realized, escalation, de-escalation, normalization, sanctions or energy, and
a central-bank case with lower API spend than a full run.

Use canary eval for cheap iteration and full eval for milestone checks.

## Manual review checklist

### Stage

Ask whether the lifecycle label is directionally right:

- Is this mainly anticipation, realized, escalation, de-escalation, or normalization?
- Does the chosen label fit the wording of the headline?

### Persistence

Ask whether the durability estimate is reasonable:

- Does the event look transient, medium-duration, or structural?
- Is the persistence label too weak or too strong for the policy or shock described?

### Mechanism quality

Ask whether the explanation identifies the core economic transmission path:

- Does it explain what changed in practical terms?
- Does it connect the headline to likely second-order market or sector effects?
- Is the reasoning specific enough to be useful?

### Watchlist quality

Ask whether the suggested ticker lists are plausible and relevant:

- Are the names specific rather than vague?
- Do `beneficiary_tickers` and `loser_tickers` fit the mechanism described?
- Are obvious beneficiaries or losers missing?
- Is `assets_to_watch` a sensible merged compatibility list?

### Market-check usefulness

Ask whether the market-check output helps:

- Does it add directional evidence?
- In current-price mode, does the rolling recent-price screen make sense for the headline?
- In event-date anchored mode, do the forward returns from the event date better match the event story?
- Do the per-ticker role labels and direction tags make sense?
- Are tags such as `supports ↑`, `supports ↓`, `contradicts ↑`, and `contradicts ↓` directionally reasonable?
- Does the summary line `Hypothesis support: X of Y` help you understand overall support?
- Does it highlight useful support or disagreement from markets?
- Is it mostly noise, errors, or generic filler?

## Suggested rating

For each headline, assign one simple rating:

- `good`: mostly useful and directionally correct
- `mixed`: partly useful, but with noticeable gaps or weak reasoning
- `poor`: not useful enough to trust for review

## Practical note

The current V1 is heuristic and incomplete. It should be judged for practical
usefulness, not precision. The sample set is meant to support repeatable
manual review, not to claim benchmark performance.

Only `stage` and `persistence` get automated comparison checks in the current
evaluation harness. The JSON output also includes `beneficiary_tickers`,
`loser_tickers`, `assets_to_watch`, and `market_note` for manual review.
Mechanism quality, watchlist quality, and market-check usefulness remain
manual review tasks by design.
