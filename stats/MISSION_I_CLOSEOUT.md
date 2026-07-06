# Mission I closeout — the ordinary-period baseline

Mission I is one bounded research section. It asks a single question and
answers it with a frozen, pre-declared surface rather than a highlighted
result:

> Are completed FOMC and OPEC event windows unusual relative to eligible
> ordinary periods on the same frozen assets and response metrics?

The answer is not a yes or a no. Event exceptionalism is **family-, horizon-,
and metric-specific**, and this closeout reports that structure exactly as the
frozen evidence produced it. It interprets and reconciles the completed chain;
it introduces no new statistic, reopens no denominator, and reruns no audit.

## 1. The evidence chain

Mission I ran as a single ordered chain, each stage frozen before the next
consumed it:

`I0 protocol → I1 candidate universe → I2A symmetric response substrate →
I2B frozen 20-cell MEMP family → I2C-A 2,000-placement calibration →
I2C-B F1–F6 falsifiers`

The tracked artifacts are authoritative; this section reconciles their
load-bearing counts.

**Study denominators.** FOMC `65` monetary-policy decisions (2018–2025,
frame-complete); OPEC `32` source-pinned production-policy identities. Never
pooled.

**Ordinary reference denominators (eligible ordinary sessions per horizon).**

| family | 1d | 5d | 20d |
|---|---|---|---|
| FOMC | 1816 | 1299 | — (structurally infeasible) |
| OPEC | 1903 | 1631 | 889 |

**Canonical non-overlapping reference counts** (greedy earliest-first disjoint
windows, starts ≥ h+1 apart):

| family | 1d | 5d | 20d |
|---|---|---|---|
| FOMC | 927 | 233 | — |
| OPEC | 960 | 287 | 51 |

**Result family.** Exactly `20` frozen primary statistics
(FOMC × 4 metrics × {1d, 5d} = 8; OPEC × 4 metrics × {1d, 5d, 20d} = 12);
`904` event-percentile rows; no FOMC 20d primary cell; no family pooling.

**Calibration.** `B = 2,000` era-matched placements per family × horizon; fixed
seed `20180101`; per-family anchor-year event-count matching; one placement
calendar reused across the four metrics; **no p-values; no new FDR pool.**

**Falsifiers.** LOYO `160` total perturbations (8 years × 20 cells); LOEO `904`
total perturbations (65 or 32 events × cells); F3 `0/20` sign flips; F6
`9 inside / 11 outside`. No cell sits exactly on a `0.25` or `0.75` boundary.

The primary estimand throughout is the **MEMP** — the median across a family's
events of each event's absolute-response mid-rank percentile within the cell's
ordinary reference. `MEMP > 0.5` means the family's event-window magnitudes sit,
on median, above the middle of the ordinary reference; `MEMP < 0.5` means below.
Direction is `sign(MEMP − 0.5)`.

## 2. FOMC interpretation

### FOMC 1d — a broad, perturbation-stable elevation

All four frozen 1d metrics point the same way and survive every frozen
perturbation:

- all four metrics have `MEMP > 0.5` (raw 0.674559, SPY-relative 0.672357,
  sector-relative 0.662996, SAR 0.725771);
- all four calibration percentiles lie **above** the central-50% interval
  (0.997000, 0.999500, 0.997000, 1.000000 — F6 outside on the **upper** side);
- `0/8` LOYO sign flips for all four cells;
- `0/65` LOEO sign flips for all four cells;
- `0/4` F3 sign flips;
- all four metric directions agree (F4 = 4 positive / 0 zero / 0 negative).

> FOMC decision windows show a broad, perturbation-stable elevation in one-day
> response magnitude relative to era-matched ordinary periods across all four
> frozen response metrics.

Limitations, stated with the finding, not after it. This is **descriptive
only** — not causal, not predictive, and not a significance claim. It is tied to
the frozen KRE / XLF / SPY asset specification and to the 1d horizon. There is
no anticipation or timing-robustness layer here and no beta-robustness layer;
those are later robustness questions, not established here.

### FOMC 5d — the pattern does not persist coherently

The broad 1d picture does not extend into a coherent 5d effect:

- cross-metric direction weakens to `3 positive / 1 negative`;
- raw-return MEMP is `0.501155` — essentially at the reference midpoint;
- raw-return LOYO flips `5/8`, and LOEO flips `32/65`;
- raw-return calibration position is **inside** the central 50%;
- sector-relative AR is below 0.5 (`0.408006`);
- the 5d surface is mixed.

> The broad FOMC 1d pattern does not extend into a coherent 5d effect. The 5d
> surface is metric-dependent, and the raw-return cell is a near-0.5 knife-edge
> that is highly leave-out sensitive.

The 5d result is not rescued by reading only its favorable metrics: the
raw-return cell's direction is decided by a hair and reverses under ordinary
leave-out perturbation.

## 3. OPEC interpretation

There is no single universal OPEC effect. The OPEC surface is horizon-dependent
and, within horizons, metric-dependent.

### OPEC 1d — no uniform cross-metric pattern

- cross-metric direction is `3 positive / 1 negative`;
- some LOYO sensitivity exists (raw-return 1 flip, SPY-relative AR 2 flips);
- calibration positions are mixed (SPY-relative and sector-relative inside;
  raw-return and SAR outside on the upper side).

> OPEC 1d windows do not show a uniform cross-metric response-magnitude pattern.

### OPEC 5d — explicitly metric-dependent

- cross-metric direction is `2 positive / 2 negative`;
- one LOYO-sensitive cell (sector-relative AR, 1 flip);
- calibration positions are mixed (raw-return, sector-relative, and SAR inside;
  SPY-relative outside on the upper side).

> OPEC 5d results are explicitly metric-dependent and do not support a single
> event-exceptionality claim.

### OPEC 20d — uniformly below ordinary magnitude, with limited cross-horizon consistency

- all four MEMPs are below `0.5` (raw 0.420135, SPY-relative 0.402137,
  sector-relative 0.449381, SAR 0.383577);
- `0/8` LOYO flips for all four;
- `0/32` LOEO flips for all four;
- `0/4` F3 flips;
- sector-relative AR and SAR are **outside** the central-50% interval on the
  **lower** side (calibration 0.034500 and 0.049500); raw-return and
  SPY-relative remain inside;
- cross-horizon consistency exists only for sector-relative AR.

> At 20d, all four OPEC response metrics are descriptively lower in magnitude
> than their ordinary-period references. The direction survives the frozen
> leave-out and overlap perturbations, but the result is not a universal
> cross-horizon mechanism because three of four metrics change direction across
> feasible horizons.

This lower-magnitude 20d reading is descriptive. It is not suppression, not
causal dampening, not OPEC-induced mean reversion, and not a predictive
reversal.

## 4. Whole-mission conclusion

> Mission I rejects the blanket idea that major event windows are generally more
> extreme than ordinary periods. Event exceptionalism is family-, horizon-, and
> metric-specific. FOMC shows the clearest broad pattern at 1d; that coherence
> weakens by 5d. OPEC is mixed at 1d and 5d and uniformly below ordinary
> response magnitude at 20d, but with limited cross-horizon consistency.

The word **"rejects" here refers to the broad descriptive narrative, not a
formal hypothesis test.** Mission I ran no significance test, computed no
p-value, and declared no null rejected. It reports where a frozen descriptive
comparison did and did not find event windows to sit away from ordinary-period
magnitude.

## 5. Stability synthesis

The six falsifiers stand separately. They are not averaged, scored, graded, or
combined into any index.

### LOYO (leave-one-year-out)

Only five cells show any sign flip:

| cell | LOYO flips (of 8) |
|---|---|
| FOMC 5d raw_return | 5 |
| FOMC 5d SAR | 1 |
| OPEC 1d raw_return | 1 |
| OPEC 1d SPY-relative AR | 2 |
| OPEC 5d sector-relative AR | 1 |

All other `15/20` cells have zero LOYO flips. Total: **`10 / 160`** LOYO
perturbations flip.

### LOEO (leave-one-event-out)

Only **FOMC 5d raw_return** shows any LOEO flip, at `32/65`. All other `19/20`
cells have zero LOEO flips. Total: **`32 / 904`** LOEO perturbations flip.

The LOEO fragility is concentrated in the cell whose full-sample MEMP is almost
exactly 0.5 (`0.501155`): with the family median sitting on the knife-edge,
removing any single event that tips the median across 0.5 flips the sign, so a
majority of leave-outs flip while the rest of the surface is leave-out stable.

### F3 (canonical overlap decimation)

`0 / 20` sign flips.

> The direction of no primary cell depends on replacing the full overlapping
> ordinary reference with the canonical disjoint-window subset.

This is a dependence check on the reference construction, **not an independence
proof** — it says nothing about whether the events themselves are independent.

### F6 (calibration position)

`9 inside`, `11 outside` of the central 50% `[0.25, 0.75]` interval. Of the 11
outside, `8` are on the **upper** side (elevated magnitude relative to the
placement distribution — all four FOMC 1d cells, FOMC 5d SAR, OPEC 1d raw &
SAR, OPEC 5d SPY-relative) and `3` are on the **lower** side (OPEC 20d
sector-relative & SAR, FOMC 5d sector-relative). "Outside upper" and "outside
lower" are opposite readings and are kept distinct.

**F6 is a calibration-position diagnostic, not a significance test.**

## 6. Cross-surface synthesis

### F4 — cross-metric direction (per family × horizon)

| family × horizon | positive | zero | negative |
|---|---|---|---|
| FOMC 1d | 4 | 0 | 0 |
| FOMC 5d | 3 | 0 | 1 |
| OPEC 1d | 3 | 0 | 1 |
| OPEC 5d | 2 | 0 | 2 |
| OPEC 20d | 0 | 0 | 4 |

### F5 — cross-horizon consistency (per family × metric)

| family | metric | feasible-horizon agreement |
|---|---|---|
| FOMC | raw_return | agree (see caveat) |
| FOMC | SPY-relative AR | agree |
| FOMC | sector-relative AR | disagree |
| FOMC | SAR | agree |
| OPEC | raw_return | disagree |
| OPEC | SPY-relative AR | disagree |
| OPEC | sector-relative AR | agree |
| OPEC | SAR | disagree |

Caveat on FOMC raw-return "agree": formal sign agreement here is weak evidence,
because the 5d raw cell is the documented near-0.5 knife-edge
(`MEMP = 0.501155`, LOEO `32/65`). Its `+1` sign is decided by a hair, so its
agreement with the 1d `+1` sign should not be read as a stable cross-horizon
pattern. These agreement flags are descriptive; they are not converted into a
score.

## 7. Signed-percentile diagnostic (subordinate)

I2B also carried, beside each MEMP, a **signed-percentile median** — the same
mid-rank rule applied to signed rather than absolute responses. Read flatly, it
locates the family's signed responses within the ordinary signed distribution.
For example, FOMC 1d has `MEMP > 0.5` (elevated magnitude) while its
signed-percentile medians sit below 0.5; the OPEC 5d and 20d signed medians sit
above 0.5. These are noted only as context.

Three disclaimers govern this section:

- the signed-percentile medians were **not** among the 20 calibrated primary
  statistics;
- they were **not** separately placement-calibrated;
- they are **descriptive context only**.

The signed diagnostic does not overturn the absolute-response MEMP conclusions
above and is not read as a directional or net-return statement.

## 8. Permanent non-claims

Mission I does **not** establish any of the following. They are later
robustness questions, not hidden assumptions of this section:

- causality;
- prediction;
- tradeability;
- alpha;
- single-event significance;
- permanent asset effects;
- cross-family comparability of raw magnitudes;
- robustness to alternative primary assets;
- robustness to rolling beta;
- immunity to anticipation / pre-event drift;
- immunity to cross-family event collisions;
- mechanism causality.

## 9. What Mission I taught the project

1. Ordinary-period baselines materially change what "event reaction" means: a
   move is only unusual against an explicit eligible-period reference.
2. Horizon choice changes the conclusion (FOMC coherent at 1d, mixed at 5d;
   OPEC below-magnitude at 20d only).
3. Metric choice changes the conclusion (raw, SPY-relative, sector-relative,
   and SAR disagree within several family × horizon cells).
4. Overlap dependence did not drive any primary sign (F3 `0/20`).
5. Near-0.5 cells can be mechanically fragile even when most of the surface is
   leave-out stable (FOMC 5d raw-return vs. the other 19 cells).
6. A complete multiplicity surface is more informative than a highlighted
   winner: all 20 cells, both appendices, and every mixed or zero-flip cell are
   shown.

## 10. Boundary

This closeout consumes frozen evidence; it does not rewrite it. The I0–I2C
artifacts, statistical code, tests, denominators, and values are unchanged. The
robustness questions enumerated in the non-claims — alternative assets, rolling
beta, anticipation / pre-event drift, cross-family collisions — are future work
and are deliberately not answered here.
