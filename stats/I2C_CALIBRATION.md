# I2C-A era-matched placement calibration (Mission I)

Contract: `i2c-calibration-v1`, executing the locked i0-v1 calibration layer (section 14) over the verified I2A substrate and the frozen I2B 20-cell MEMP family.

## Frozen calibration statement

Exactly **20** MEMP statistics were frozen before any outcome was compared; all 20 are calibrated below, in frozen I2B order. **B = 2,000** era-matched pseudo-event placements per (family, horizon); fixed seed **20180101**. The output is a percentile-of-placements only: **no p-values**, no significance threshold, no confidence interval, and no new FDR pool (the accepted-86 and Mission G pools stay separate). Families are never pooled; FOMC 20d is structurally infeasible and has no cell. No cell is labelled by size or ranked.

## Calibrated family (all 20 cells, frozen order)

| family | horizon | metric | event N | reference N | observed MEMP | calibration percentile |
|---|---|---|---|---|---|---|
| FOMC | 1d | raw_return | 65 | 1816 | 0.674559 | 0.997000 |
| FOMC | 1d | spy_relative_ar | 65 | 1816 | 0.672357 | 0.999500 |
| FOMC | 1d | sector_relative_ar | 65 | 1816 | 0.662996 | 0.997000 |
| FOMC | 1d | sar | 65 | 1816 | 0.725771 | 1.000000 |
| FOMC | 5d | raw_return | 65 | 1299 | 0.501155 | 0.476500 |
| FOMC | 5d | spy_relative_ar | 65 | 1299 | 0.527329 | 0.661000 |
| FOMC | 5d | sector_relative_ar | 65 | 1299 | 0.408006 | 0.059500 |
| FOMC | 5d | sar | 65 | 1299 | 0.556582 | 0.824000 |
| OPEC | 1d | raw_return | 32 | 1903 | 0.529164 | 0.792000 |
| OPEC | 1d | spy_relative_ar | 32 | 1903 | 0.523384 | 0.705250 |
| OPEC | 1d | sector_relative_ar | 32 | 1903 | 0.472149 | 0.550250 |
| OPEC | 1d | sar | 32 | 1903 | 0.602733 | 0.885250 |
| OPEC | 5d | raw_return | 32 | 1631 | 0.469957 | 0.461500 |
| OPEC | 5d | spy_relative_ar | 32 | 1631 | 0.584304 | 0.891250 |
| OPEC | 5d | sector_relative_ar | 32 | 1631 | 0.428878 | 0.390250 |
| OPEC | 5d | sar | 32 | 1631 | 0.580012 | 0.740000 |
| OPEC | 20d | raw_return | 32 | 889 | 0.420135 | 0.530500 |
| OPEC | 20d | spy_relative_ar | 32 | 889 | 0.402137 | 0.297000 |
| OPEC | 20d | sector_relative_ar | 32 | 889 | 0.449381 | 0.034500 |
| OPEC | 20d | sar | 32 | 889 | 0.383577 | 0.049500 |

Reading (mechanics only): the calibration percentile is the position of the observed MEMP within its 2,000 era-matched placement MEMPs under the section-13 mid-rank rule; 0.5 means the observed value sits at the middle of the placement distribution. The I2B signed-percentile median is a descriptive diagnostic and is not calibrated (calibrating it would create a statistic outside the frozen family of 20).

## Placement reconciliation

| family | horizon | expected placements | completed | per-year event counts (anchor-session year) |
|---|---|---|---|---|
| FOMC | 1d | 2000 | 2000 | 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8 |
| FOMC | 5d | 2000 | 2000 | 2018:8, 2019:8, 2020:9, 2021:8, 2022:8, 2023:8, 2024:8, 2025:8 |
| OPEC | 1d | 2000 | 2000 | 2018:2, 2019:2, 2020:3, 2021:3, 2022:4, 2023:3, 2024:5, 2025:10 |
| OPEC | 5d | 2000 | 2000 | 2018:2, 2019:2, 2020:3, 2021:3, 2022:4, 2023:3, 2024:5, 2025:10 |
| OPEC | 20d | 2000 | 2000 | 2018:2, 2019:2, 2020:3, 2021:3, 2022:4, 2023:3, 2024:5, 2025:10 |

Every placement reproduces the family's per-year event-count vector exactly, drawn without replacement from that year's eligible ordinary sessions for the horizon; every year's pool supplies its required count (no failure, no replacement). The eligible pool is the I1 reference set, which already excludes real event anchors, so no real study event is ever placed.

## Method

One placement reproduces the family's per-year event count on the anchor-session year and draws, per year, that many distinct sessions uniformly without replacement from the horizon's eligible ordinary pool. The same drawn calendar feeds all four metrics. Each placement's pseudo-MEMP is the identical section-13 pipeline: each drawn session's absolute response is given its mid-rank percentile within the cell's fixed ordinary reference (self-included, per section 13's fixed-R definition), and the placement MEMP is the median across the drawn sessions. The observed MEMP's calibration percentile is its mid-rank position within the 2,000 placement MEMPs, denominator 2,000, observed external. Selection uses one local deterministic RNG seeded at 20180101, consumed in the fixed order family, horizon, placement, year.

## Boundary

This slice computes the calibration position only. Not yet run (they belong to I2C-B): F1 LOYO (leave-one-year-out), F2 LOEO (leave-one-event-out), F3 overlap decimation, F4 cross-metric consistency, F5 cross-horizon consistency, and the F6 central-50 percent calibration-position interpretation. No interpretation of any cell is made here.

