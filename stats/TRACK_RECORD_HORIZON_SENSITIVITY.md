# Track-record horizon sensitivity (H1)

Read-only diagnostic over the accepted track-record corpus, dated 2026-06-11
(live archive: 180 rows; accepted track-record denominator: 86; coverage
denominator: 94; staged candidates: 13 - all unchanged by this report).

## Purpose

The canonical track-record scorer (`db.compute_track_record`) labels each
accepted event from the longest-horizon revisit snapshot that carries at
least one directional ticker (20d > 5d > 1d), falling back to the initial
`market_tickers` read when no snapshot qualifies. In principle that mixes
observation horizons inside one headline, and a label could change with the
horizon that happens to hold data. This report measures that sensitivity
instead of assuming it, by re-labelling the same 86 events under fixed
single-horizon variants (1d-only / 5d-only / 20d-only, from revisit
snapshots only). It is the horizon twin of the scoring-rule sensitivity
report (`track_record_sensitivity_report.py`): the rule twin varies the
classification rule, this one varies the observation horizon. Neither
changes the canonical headline.

## Canonical rule (measured, not changed)

- Source per event: best revisit snapshot by day (20d > 5d > 1d) **if** it
  has at least one directional ticker (`dir_cnt > 0`); otherwise the initial
  `market_tickers` read (whose per-ticker direction derives from the 5d
  move, see `market_check.py`).
- Label: ANY-support OR-rule - at least one supporting ticker -> validated;
  else at least one contradicting ticker -> contradicted; else unresolved.
- Live canonical headline, reproduced exactly by this report and by
  `db.compute_track_record`: **validated 46 / contradicted 8 / unresolved
  32** over 86 accepted events.

## Headline finding: the horizon mix is latent, not realized

The feared heterogeneity does not materialize in the live corpus:

- Canonical source distribution: **86 of 86 events score from the initial
  `market_tickers` read; 0 from any revisit snapshot** (matches
  `revisit_scored: 0` in `db.compute_track_record`).
- Exactly **one** archive event (#36) carries revisit snapshots at all: a
  single 1d snapshot with 5 tickers and **zero directional tags**, so the
  canonical `dir_cnt > 0` gate correctly passes over it.

So the current 46/8/32 headline is effectively horizon-homogeneous: every
label rests on the same initial 5d-derived read. The best-available
multi-horizon code path exists but is essentially unexercised today. This
diagnostic stands as a regression guard: if revisit snapshots ever populate,
re-running it will show how much of the headline starts to ride on horizon
choice.

## Per-horizon diagnostics (live)

| Horizon | available | missing | support | contradiction | unresolved | data-limited (no direction) | differs vs canonical |
|---------|-----------|---------|---------|---------------|------------|------------------------------|----------------------|
| 1d      | 1         | 85      | 0       | 0             | 1          | 1                            | 1                    |
| 5d      | 0         | 86      | 0       | 0             | 0          | 0                            | 0                    |
| 20d     | 0         | 86      | 0       | 0             | 0          | 0                            | 0                    |

Within each horizon: support + contradiction + unresolved = available, and
available + missing = 86. "Data-limited" counts available snapshots whose
tickers carry no directional tag (a subset of unresolved).

## Flip summary

- Flips vs canonical: one, at 1d - event #36 (canonical support via the
  `market_tickers` fallback; its 1d snapshot read is unresolved/data-limited:
  `support_to_unresolved = 1`). This is a source-availability artifact, not
  a directional reversal.
- Cross-horizon flips: **0 events** have snapshots at 2 or more horizons, so
  no label changes between horizons are observable in the live corpus.

## Interpretation

- The canonical best-available rule remains the primary headline; the
  single-horizon variants are diagnostics only.
- No horizon variant is a new claim; each is a descriptive re-label of the
  same accepted events under a fixed observation window.
- Horizon variants read revisit snapshots only; events without a snapshot at
  a horizon are reported as missing there, never re-scored.
- The honest takeaway is a negative result: today's headline is not
  horizon-fragile because the corpus contains almost no revisit snapshots.
  The sensitivity becomes informative the moment snapshots accumulate.

## Non-claims

- Counts are descriptive event-window evidence labels, not a confirmed
  mechanism and not a measure of predictive power.
- A flip between horizons shows label sensitivity to the observation window;
  it does not say which horizon is correct.
- No FDR adjustment and no statistical-significance readout is attached to
  any count; the closed Phase 1 / Phase 2 FDR pools are never read,
  combined, or implied.
- This report carries no directive or trade framing of any kind.

## Reproduce

```bash
python scripts/track_record_horizon_sensitivity_report.py --db-path events.db
python scripts/track_record_horizon_sensitivity_report.py --db-path events.db --json
python -m unittest tests.test_track_record_horizon_sensitivity_report -v
```

Read-only: a single `mode=ro` SQLite connection, plain SELECTs; no DB or
price-cache write, no provider or paid call, no event-study math, no
frontend change.
