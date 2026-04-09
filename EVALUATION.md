# Evaluation Guide

This repo uses lightweight manual evaluation, not a benchmark suite. The goal
is to catch regressions, compare model choices cheaply, and review whether the
current analysis pipeline remains practically useful.

The maintained product surfaces are FastAPI, the React app, and the Telegram
bot. `eval.py` evaluates the backend analysis path only.

## What `eval.py` Covers

- deterministic stage and persistence classification
- `analyze_event(...)`
- market validation and the current market-context enrichment path
- timestamped `eval_output_*.json` output for review

It does not validate:

- React UX, streaming rendering, archive/backtest screens, or export UX
- Telegram bot commands, `/brief`, or scheduled delivery
- inbox refresh/caching UX
- clustering quality or threshold calibration on live RSS data

## Core Commands

```powershell
python eval.py
python eval.py --preset canary
python eval.py --ids sample_001 sample_005
python eval.py --limit 6
python eval.py --preset canary --model claude-haiku-4-5-20251001
```

## Canary Flow

Use canary first during active iteration:

```powershell
python eval.py --preset canary
```

Use the full sample set before calling a change stable:

```powershell
python eval.py
```

## Canary Model Comparison

There is no dedicated compare command. Run the same canary slice twice with
different models, then compare the two output files.

```powershell
python eval.py --preset canary --model claude-haiku-4-5-20251001
python eval.py --preset canary --model claude-sonnet-4-20250514
```

When comparing runs, check:

- top-level `model`
- `summary.stage_correct` / `summary.stage_wrong`
- `summary.persistence_correct` / `summary.persistence_wrong`
- manual quality of mechanism summaries, watchlists, market notes, and market-context overlays

## What To Review

### Automated checks

- `stage` vs `expected_stage`
- `persistence` vs `expected_persistence`
- `stage_match`
- `persistence_match`
- summary totals at the top of the file

### Manual checks

- `what_changed` is specific and readable
- `mechanism_summary` explains the transmission path, not just the headline
- beneficiaries and losers are plausible
- `assets_to_watch` is useful and not noisy
- market validation adds directional evidence rather than filler
- context blocks such as real-yield, policy, shock, external-balance, or reserve overlays are coherent rather than contradictory noise

## News Threshold Evaluation

Use `scripts/eval_news_thresholds.py` when touching relevance filtering or
clustering:

```powershell
python scripts/eval_news_thresholds.py
python scripts/eval_news_thresholds.py --save
python scripts/eval_news_thresholds.py --load snap
```

This is the right tool for RSS filtering and clustering quality. `eval.py` is
not.

## Practical Guidance

- Use canary for cheap iteration
- Use full runs before shipping meaningful backend changes
- Use threshold evals before and after touching RSS relevance or clustering logic
- Treat output quality as a mix of automated checks and manual analyst review
- Use separate spot checks for frontend, Telegram, export, and cache behavior because `eval.py` does not cover those surfaces
