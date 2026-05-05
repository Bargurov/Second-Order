# Magic-Number Validation Baseline

**Status:** read-only empirical baseline. No values proposed, no thresholds changed. Computed 2026-05-05 from local `events.db`.
**Companion:** `docs/magic_numbers_inventory.md` (top-5 risk list).
**Harness:** `scripts/magic_number_baseline.py` (read-only sqlite, no provider calls, no DB writes).
**Raw output:** `baseline_output.json` (regenerated each run).

## Corpus

| Surface | Rows | Time range |
|---|---|---|
| `events` | 270 | 2026-04-03 → 2026-05-05 (≈32d) |
| `news_clusters` | 6,255 | (cluster window — payloads carry `published_at`) |
| `headline_registry` | 766 | 2026-05-03 → 2026-05-05 (≈2d, all rows) |

The registry is much younger than the events table (registry-lifecycle feature is recent), which directly affects what risk 5 can say.

---

## Risk 1 — Cluster ranking weights `_RANK_W_*`

**Source:** `routes/movers.py:614–622`. The scorer sums weighted features over each cluster's headline + sources.

**Method:** loaded all 6,255 `news_clusters` rows, parsed `payload_json`, and applied the live `_score_cluster_for_preview` logic verbatim (regexes mirrored from `routes/movers.py:580–679` because importing the module triggers a circular import via `api.py`). Computed feature firing rates, distribution of `source_count` and `high_tier` source count, distribution of the resulting score, and which weight contributed the largest absolute slice per cluster.

### Feature firing rates (over 6,255 clusters)

| Feature | Firing count | Rate |
|---|---:|---:|
| `has_asset_terms` | 1,101 | 17.6% |
| `geopolitical` | 773 | 12.4% |
| `commodity_policy` | 475 | 7.6% |
| `macro_policy` | 358 | 5.7% |
| `corporate_action` | 217 | 3.5% |
| `generic_finance_noise` | 34 | 0.5% |

### `source_count` distribution

p5..p99 = 1, 1, 1, 1, 2, 3, 22. **98 clusters (1.6%) exceed the diminishing-returns cap of 8**, so for the long tail the cap is doing real work; for the median cluster (`source_count=1`) the per-publisher weight contributes only `1.0`.

### `high_tier` source count distribution

p5..p99 = 0, 0, 1, 1, 1, 2, 11. **3,069 clusters (49.1%) have `high_tier=0`**, so half the corpus gets no boost from `_RANK_W_HIGH_TIER_PER`.

### Resulting score distribution

| Stat | Value |
|---|---:|
| mean | 3.45 |
| p5 | 1.0 |
| p25 | 2.0 |
| p50 | 2.5 |
| p75 | 4.0 |
| p90 | 5.5 |
| p95 | 7.5 |
| p99 | 25.5 |
| negative-score clusters | 10 (the noise penalty wins) |
| zero-score clusters | 0 |

### Largest absolute contributor per cluster (single-weight dominance)

| Winning feature | # clusters |
|---|---:|
| `source_count` | 2,164 (34.6%) |
| `high_tier` | 2,040 (32.6%) |
| `asset_terms` | 694 (11.1%) |
| `geopolitical` | 628 (10.0%) |
| `commodity_policy` | 403 (6.4%) |
| `macro_policy` | 297 (4.7%) |
| `generic_finance_noise` | 29 (0.5%) |

**Observation (evidence only, no recommendation):** ordering is dominated by the two count-based weights (67% of clusters). The boost weights (`macro_policy=3.0`, `geopolitical=2.5`, `commodity_policy=2.5`) only flip the dominant contributor on a minority of rows because the topical regexes fire on 3–12% of headlines. The penalty weight (`generic_finance_noise=-3.0`) is the dominant factor for only 29 clusters — small absolute number, but those are exactly the clusters the penalty is designed to demote.

---

## Risk 2 — Jaccard family (`_DEDUP_THRESHOLD=0.65`, `_RELATED_THRESHOLD=0.35`, `_ANALOG_THRESHOLD=0.15`)

**Source:** `db.py:1475`, `db.py:1792`, `db.py:1943`. All three operate on saved-event headlines via `_jaccard(_headline_words(h1), _headline_words(h2))`.

**Method:** loaded all 270 events, tokenised via the live `token_norm._headline_words`, computed pairwise Jaccard for every pair (36,315 pairs). Counted pairs above each cutoff; for the dedup case also applied the live `_short_headline_guard` and the 2-day `_DEDUP_DATE_WINDOW_DAYS` filter so the figures reflect what the actual filter would do.

### Sample size

- 270 events, 36,315 pairs total.
- 8,898 pairs (24.5%) within the ±2-day dedup window.

### Pairwise similarity quantiles

| Quantile | All pairs | Within ±2d window |
|---|---:|---:|
| p5 | 0.000 | 0.000 |
| p25 | 0.000 | 0.000 |
| p50 | 0.000 | 0.000 |
| p75 | 0.000 | 0.500 |
| p90 | 0.500 | 1.000 |
| p95 | 1.000 | 1.000 |
| p99 | 1.000 | 1.000 |
| max | 1.000 | 1.000 |

The distribution is heavily bimodal — most pairs are 0 (different events) and a long upper tail clusters near 1 (same headline indexed multiple times).

### Counts above each threshold

| Threshold | Cutoff | Pairs above | % of all pairs |
|---|---:|---:|---:|
| `_ANALOG_THRESHOLD` | ≥ 0.15 | 4,434 | 12.21% |
| `_RELATED_THRESHOLD` | ≥ 0.35 | 4,216 | 11.61% |
| `_DEDUP_THRESHOLD` (no guard) | ≥ 0.65 | 2,278 | 6.27% |
| `_DEDUP_THRESHOLD` + short-headline guard | ≥ 0.65 + guard | 2,278 | 6.27% |
| `_DEDUP_THRESHOLD` + guard + within ±2d window | ≥ 0.65 + guard + 2d | 1,150 | 3.17% |

### Observations (evidence only)

- The short-headline guard (`_MIN_SHARED_TOKENS=2`, `_SHORT_HEADLINE_THRESHOLD=4`) does not strip any of the 2,278 dedup-eligible pairs in this corpus — guard is non-load-bearing on the current data.
- Distance from analog (0.15) to related (0.35) only excludes 218 pairs (4,434 → 4,216). The two thresholds are operationally close on this corpus — the gap between 0.15 and 0.35 captures very few pairs because the distribution jumps from ≈0 directly into the high band.
- The date window halves the dedup-eligible count (2,278 → 1,150), so the 2-day guard is materially active.
- 11.6% of all pairs cross the related-events threshold — that is the prevalence of headline-overlap in saved events, not a per-event rate. Re-projected: each event has on average ≈ 2 × 4,216 / 270 ≈ 31 related candidates above 0.35; `find_related_events` then caps at 5.

---

## Risk 5 — `headline_registry._DEFAULT_TTL_DAYS = 5`

**Source:** `headline_registry.py:22`. Filter at `headline_registry.py:54–85` (`is_expired_low_impact`) checks `impact_level == "low"` AND `analyzed_at < now − 5d`, falling back to `event_row.timestamp` when the registry has no `analyzed_at`.

**Method:** read the full `headline_registry` table; counted by `impact_level` and `state`; computed first-seen age distribution.

### Sample size and filter inputs

- 766 registry rows.
- **`impact_level` distribution: 100% NULL.** No row has been advanced past `state='seen'`.
- **`state` distribution: 100% `seen`.**
- `events` table has no `conviction` / `impact_level` column at all (verified with `PRAGMA table_info`).

| Source the filter consults | Coverage |
|---|---|
| `event_row['conviction']['impact_level']` | column does not exist on events table |
| `registry_impact_level` (fallback) | NULL on 766/766 rows (100%) |

### Empirical state

**Insufficient data for a TTL distribution** — the 5-day cutoff has nothing to fire on. With both inputs empty, `is_expired_low_impact` returns `False` on every row. The TTL is operationally inert on the current local archive.

### Corpus-age side-view (informational, not a TTL distribution)

For context: how old is the registry as it stands?

| Bucket (first_seen age) | Rows |
|---|---:|
| < 1 day | 531 |
| < 5 days | 766 |
| ≥ 5 days | 0 |
| ≥ 10 / 30 / 90 days | 0 |

| Quantile | first_seen age (days) |
|---|---:|
| p50 | 0.87 |
| p75 | 1.01 |
| p90 | 1.68 |
| p95 | 1.69 |
| p99 | 1.96 |

Even if every row were tagged `impact_level='low'` today, none would meet the 5-day TTL — the registry isn't old enough to hold an expired row yet. So we cannot say whether 5 days is too short, too long, or correct from this data; we can only say *the TTL is unused so far*.

---

## Risks 3 & 4 — insufficient data (no provider calls, no audit log)

These were flagged in the inventory but cannot be measured from the local archive without breaking the constraints (no provider calls, no DB writes).

### Risk 3 — stress-regime cutoffs

`market_check.py:2165` (VIX 1.20×), `:2256` (credit spread 0.5pp), `:2295` (haven inflow 0.3%), `:2170` (slightly-elevated 5%).

- **Why insufficient:** `compute_stress_regime` reads live yfinance data (VIX, HYG/SHY, GLD/DXY/TLT). The schema has no `stress_regime_cache` / `stress_regime_decisions` table, so historical firing rates of these cutoffs are not persisted and cannot be reconstructed read-only.
- `price_cache` (10,085 rows) does hold OHLCV per ticker per date and could in principle answer a back-of-envelope "what % of days would VIX > 20d × 1.20 fire?" question for a subset of tickers, but this requires re-implementing the regime composition from cached prices — outside the scope of this baseline (and arguably a separate risk: re-implementing live logic over cached prices duplicates code).
- **Computable next step (deferred):** if the user wants, build `compute_stress_regime` over `price_cache` directly and produce historical firing rates per cutoff. Keeping this out of the current pass since it would mean recreating product logic.

### Risk 4 — verify thresholds (`_VERIFY_MOVE_THRESHOLD=5.0`, `_VERIFY_DELTA_PCT=3.0`, `_VERIFY_LOW_VOL=0.1`)

`market_check.py:598–600`. Triggered inside `_check_one_ticker` when an `r5` move is large; gates a second-source fetch.

- **Why insufficient:** verification is a read-time decision. There is no `verify_log` / `verify_audit` table in the schema (confirmed against `sqlite_master`). The thresholds fire and discard the decision in the same call, so historical firing rate is unrecoverable from the archive.
- The only computable surrogate would be: re-fetch r5 for every event's tickers from `price_cache` and apply the threshold. That requires recomputing `r5` from `price_cache` for the event's `assets_to_watch`, which is feasible but again duplicates `market_check` logic.

---

## What this baseline supports

Strictly evidence; no value changes proposed.

| Risk | Evidence | Supports |
|---|---|---|
| 1 | 67% of clusters dominated by `source_count` or `high_tier` weights; topic boosts active on 3–12% of headlines | a future calibration pass on `_RANK_W_*` should target topic-boost magnitudes against source-count contribution, not against each other |
| 2 | bimodal Jaccard; gap between 0.15 and 0.35 captures only ≈5% of dedup-positive pairs; date window halves dedup count | a future calibration pass should test whether `_RELATED_THRESHOLD=0.35` and `_ANALOG_THRESHOLD=0.15` add discriminative value over a single threshold on this corpus |
| 3 | not measured | requires either re-implementing stress regime over `price_cache` or persisting decision logs |
| 4 | not measured | requires a verify-log table or re-implementation over `price_cache` |
| 5 | TTL is operationally inert (100% NULL impact_level, registry < 2d old) | the 5-day value cannot be validated until the impact_level pipeline backfills the registry |

---

## Reproducibility

```
python scripts/magic_number_baseline.py        # read-only, no writes
```

Outputs `baseline_output.json` next to the run dir. No DB writes, no network. Verified manually that `from token_norm import _headline_words` and `from db import _jaccard, _short_headline_guard` are leaf imports (no circular pulls; `routes.movers` is NOT imported because of the circular dependency on `api.py`).

## Verification

- `python -m unittest tests.test_diagnostics tests.test_backfill_paid_guard -v`
- `git diff --check`

Results recorded in the conversation log alongside this commit.
