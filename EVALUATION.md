# Evaluation Guide

This repo uses a lightweight manual eval loop rather than a benchmark suite.
The goal is to catch obvious regressions, compare model choices cheaply, and
check whether the system is still directionally useful on a varied sample of
headline types.

The maintained product path is the React frontend plus FastAPI backend.
`app.py` remains in the repo only as a frozen legacy reference and is not part
of the default workflow.

## What `eval.py` Does

- loads `sample_events.json`
- classifies each sample with the current deterministic logic
- runs `analyze_event(...)`
- runs the current market-check flow
- writes a timestamped `eval_output_*.json` file

It does not call `main.py` and does not write to the SQLite archive.
It also does not validate the frontend product UX: live inbox refresh/caching
behavior, progressive analysis rendering, archive screens, export actions, or
backtest page behavior.
It does not measure cluster quality, related-event quality, or whether the
current thresholds are empirically well-calibrated.

## Core Commands

```powershell
python eval.py
python eval.py --preset canary
python eval.py --ids sample_001 sample_005
python eval.py --limit 6
python eval.py --preset canary --model claude-haiku-4-5-20251001
```

### Selection options

- `--preset canary`: run the cheap representative subset
- `--ids ...`: run specific sample IDs in the order given
- `--limit N`: trim the selected set after preset or ID selection
- `--model MODEL_ID`: override `ANTHROPIC_MODEL` for that run only

## Current Canary Flow

Use canary first for quick checks during active iteration:

```powershell
python eval.py --preset canary
```

The canary preset is intentionally small but still covers multiple stage and
persistence patterns, including escalation, de-escalation, normalization,
sanctions or energy, and a central-bank style case.

Use the full sample set for milestone checks:

```powershell
python eval.py
```

## Canary Model Comparison

There is no dedicated compare command right now. The current comparison flow is
to run the same canary slice twice with different models, then compare the two
timestamped output files.

Example:

```powershell
python eval.py --preset canary --model claude-haiku-4-5-20251001
python eval.py --preset canary --model claude-sonnet-4-20250514
```

When comparing outputs, check:

- top-level `model`
- `summary.stage_correct` / `summary.stage_wrong`
- `summary.persistence_correct` / `summary.persistence_wrong`
- manual quality of mechanism summaries, watchlists, and market notes

## What To Review In The Output

### Automated checks

- `stage` vs `expected_stage`
- `persistence` vs `expected_persistence`
- `stage_match`
- `persistence_match`
- summary totals at the top of the file

### Manual checks

- `what_changed` is specific and readable
- `mechanism_summary` explains the transmission path, not just the headline
- beneficiary/loser lists are plausible
- `assets_to_watch` is useful and not noisy
- `market_note` and `market_tickers` add directional evidence rather than filler

## News Threshold Evaluation

Use `scripts/eval_news_thresholds.py` to validate relevance filtering and
clustering quality against real RSS headlines.

```powershell
python scripts/eval_news_thresholds.py              # live fetch
python scripts/eval_news_thresholds.py --save       # save snapshot
python scripts/eval_news_thresholds.py --load snap  # replay from file
```

### Current Thresholds (validated 2026-04-05)

| Threshold | Value | Rationale |
|-----------|-------|-----------|
| `_CLUSTER_THRESHOLD` | 0.25 | Jaccard merge. Catches cross-source rewording ("fuel prices surge" ↔ "oil highest price") at 0.286 Jaccard, while avoiding false merges from shared background words ("iran"+"war" only = 0.14). Lowered from 0.30 → 0.25 based on empirical live-feed testing. |
| `_AGREEMENT_THRESHOLD` | 0.20 | Below cluster threshold so borderline pairs within a cluster get flagged as "mixed" agreement. |
| `_RELATED_THRESHOLD` | 0.35 | Stricter than clustering — for linking saved events in the archive. Better to miss a link than create a bad one. |

### What Changed in the Last Empirical Pass

- **"import" moved to word-boundary matching** — was a substring keyword, causing false positives on "important", "importantly", etc. Now uses `\b` word boundary via `_WORD_BOUNDARY_KW`.
- **"petrol" and "diesel" added** — missing from all keyword sets. UK-sourced feeds (BBC, Guardian) use "petrol" instead of "gas"/"fuel". Added to `_WORD_BOUNDARY_KW` and `_ECON_CONTEXT_KW`.
- **"economic" added to `_ECON_CONTEXT_KW`** — war/conflict headlines containing "economic" (e.g. "global economic pain") were being dropped because "economic" wasn't in the rescue set. Now passes the war-gate.

### Empirical Results (120 headlines, 9 feeds)

- Keep rate: 58% (70/120) — appropriate for mixed-topic feeds
- Drop rate: 42% (50/120) — all drops are correct (lifestyle, sports, human-interest)
- False positives: 0 detected
- False negatives: 0 detected after fixes
- Multi-source clusters: 2 (fighter jet + Hormuz tanker stories)
- Single-source clusters: 58
- Potential issues flagged: 0

## Practical Guidance

- Use canary runs for cheap iteration and model A/B checks.
- Use full runs before calling a change stable.
- Use `scripts/eval_news_thresholds.py` before and after touching relevance/clustering logic.
- Judge the system for practical usefulness, not benchmark-grade precision.
- Treat mechanism quality, watchlist quality, and market usefulness as manual review tasks.
- Use separate spot checks for inbox refresh, archive/backtest behavior, and UI copy because `eval.py` does not cover them.
