# I2C-B frozen falsifier battery (Mission I)

Contract: `i2c-falsifiers-v1`, running exactly the six I0 section-15 falsifiers against the frozen I2B 20-cell MEMP family and the I2C-A calibration. Direction is `sign(MEMP - 0.5)` under the frozen G6B convention (`sign(0) = 0`; a flip requires strict opposite signs). This slice reports mechanical stability facts only - no ranking, no combined score, no significance language, and no overall Mission-I interpretation.

## A. Complete 20-cell falsifier surface (frozen order)

| family | horizon | metric | observed MEMP | calibration pct | LOYO runs | LOYO flips | LOEO runs | LOEO flips | orig. ref N | F3 dec. N | F3 dec. MEMP | F3 change | F3 flip | F6 central-50% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FOMC | 1d | raw_return | 0.674559 | 0.997000 | 8 | 0 | 65 | 0 | 1816 | 927 | 0.666667 | -0.007893 | no | outside |
| FOMC | 1d | spy_relative_ar | 0.672357 | 0.999500 | 8 | 0 | 65 | 0 | 1816 | 927 | 0.664509 | -0.007848 | no | outside |
| FOMC | 1d | sector_relative_ar | 0.662996 | 0.997000 | 8 | 0 | 65 | 0 | 1816 | 927 | 0.662352 | -0.000644 | no | outside |
| FOMC | 1d | sar | 0.725771 | 1.000000 | 8 | 0 | 65 | 0 | 1816 | 927 | 0.707659 | -0.018112 | no | outside |
| FOMC | 5d | raw_return | 0.501155 | 0.476500 | 8 | 5 | 65 | 32 | 1299 | 233 | 0.506438 | +0.005283 | no | inside |
| FOMC | 5d | spy_relative_ar | 0.527329 | 0.661000 | 8 | 0 | 65 | 0 | 1299 | 233 | 0.506438 | -0.020891 | no | inside |
| FOMC | 5d | sector_relative_ar | 0.408006 | 0.059500 | 8 | 0 | 65 | 0 | 1299 | 233 | 0.412017 | +0.004011 | no | outside |
| FOMC | 5d | sar | 0.556582 | 0.824000 | 8 | 1 | 65 | 0 | 1299 | 233 | 0.557940 | +0.001358 | no | outside |
| OPEC | 1d | raw_return | 0.529164 | 0.792000 | 8 | 1 | 32 | 0 | 1903 | 960 | 0.522917 | -0.006248 | no | outside |
| OPEC | 1d | spy_relative_ar | 0.523384 | 0.705250 | 8 | 2 | 32 | 0 | 1903 | 960 | 0.507292 | -0.016092 | no | inside |
| OPEC | 1d | sector_relative_ar | 0.472149 | 0.550250 | 8 | 0 | 32 | 0 | 1903 | 960 | 0.461979 | -0.010170 | no | inside |
| OPEC | 1d | sar | 0.602733 | 0.885250 | 8 | 0 | 32 | 0 | 1903 | 960 | 0.570833 | -0.031899 | no | outside |
| OPEC | 5d | raw_return | 0.469957 | 0.461500 | 8 | 0 | 32 | 0 | 1631 | 287 | 0.445993 | -0.023964 | no | inside |
| OPEC | 5d | spy_relative_ar | 0.584304 | 0.891250 | 8 | 0 | 32 | 0 | 1631 | 287 | 0.588850 | +0.004546 | no | outside |
| OPEC | 5d | sector_relative_ar | 0.428878 | 0.390250 | 8 | 1 | 32 | 0 | 1631 | 287 | 0.372822 | -0.056056 | no | inside |
| OPEC | 5d | sar | 0.580012 | 0.740000 | 8 | 0 | 32 | 0 | 1631 | 287 | 0.585366 | +0.005354 | no | inside |
| OPEC | 20d | raw_return | 0.420135 | 0.530500 | 8 | 0 | 32 | 0 | 889 | 51 | 0.450980 | +0.030845 | no | inside |
| OPEC | 20d | spy_relative_ar | 0.402137 | 0.297000 | 8 | 0 | 32 | 0 | 889 | 51 | 0.490196 | +0.088059 | no | inside |
| OPEC | 20d | sector_relative_ar | 0.449381 | 0.034500 | 8 | 0 | 32 | 0 | 889 | 51 | 0.450980 | +0.001599 | no | outside |
| OPEC | 20d | sar | 0.383577 | 0.049500 | 8 | 0 | 32 | 0 | 889 | 51 | 0.431373 | +0.047795 | no | outside |

`sign(MEMP - 0.5)` gives each cell's frozen direction; a flip is a strict sign reversal of that quantity. F6 states whether the calibration percentile falls inside `[0.25, 0.75]`; it is a position label, not a test outcome.

## B. Full leave-one-year-out (F1) appendix

**F1 reference convention.** F1 follows I0 section 15, which removes each calendar year's *events and ordinary dates* - so the reference R shrinks and every surviving event is re-ranked against the reduced R. This differs from an R-fixed reading (keep each event's original percentile and take the median of survivors); the two can produce different flip counts for cells near 0.5. The authoritative I0 reading (R reduced) is used throughout, and is the basis of the LOYO flip counts in Section A.

Each year removes that calendar year's events and ordinary reference dates; the surviving events are re-ranked against the reduced reference. Every year is shown.

### FOMC | 1d | raw_return

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.687854 | no |
| 2019 | 0.678841 | no |
| 2020 | 0.697170 | no |
| 2021 | 0.680730 | no |
| 2022 | 0.668974 | no |
| 2023 | 0.652201 | no |
| 2024 | 0.656171 | no |
| 2025 | 0.685535 | no |

### FOMC | 1d | spy_relative_ar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.669604 | no |
| 2019 | 0.632242 | no |
| 2020 | 0.688365 | no |
| 2021 | 0.681990 | no |
| 2022 | 0.662052 | no |
| 2023 | 0.669182 | no |
| 2024 | 0.676952 | no |
| 2025 | 0.680503 | no |

### FOMC | 1d | sector_relative_ar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.728760 | no |
| 2019 | 0.578086 | no |
| 2020 | 0.704403 | no |
| 2021 | 0.695844 | no |
| 2022 | 0.677785 | no |
| 2023 | 0.631447 | no |
| 2024 | 0.612720 | no |
| 2025 | 0.691195 | no |

### FOMC | 1d | sar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.734424 | no |
| 2019 | 0.664358 | no |
| 2020 | 0.737107 | no |
| 2021 | 0.722292 | no |
| 2022 | 0.731907 | no |
| 2023 | 0.718239 | no |
| 2024 | 0.731108 | no |
| 2025 | 0.763522 | no |

### FOMC | 5d | raw_return

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.498239 | yes |
| 2019 | 0.484581 | yes |
| 2020 | 0.441769 | yes |
| 2021 | 0.481938 | yes |
| 2022 | 0.520246 | no |
| 2023 | 0.505717 | no |
| 2024 | 0.453744 | yes |
| 2025 | 0.514512 | no |

### FOMC | 5d | spy_relative_ar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.536092 | no |
| 2019 | 0.505727 | no |
| 2020 | 0.543783 | no |
| 2021 | 0.524229 | no |
| 2022 | 0.513204 | no |
| 2023 | 0.533861 | no |
| 2024 | 0.546256 | no |
| 2025 | 0.532982 | no |

### FOMC | 5d | sector_relative_ar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.402289 | no |
| 2019 | 0.379736 | no |
| 2020 | 0.408494 | no |
| 2021 | 0.394714 | no |
| 2022 | 0.408451 | no |
| 2023 | 0.398417 | no |
| 2024 | 0.389427 | no |
| 2025 | 0.423043 | no |

### FOMC | 5d | sar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.614437 | no |
| 2019 | 0.542731 | no |
| 2020 | 0.524956 | no |
| 2021 | 0.543612 | no |
| 2022 | 0.493838 | yes |
| 2023 | 0.583993 | no |
| 2024 | 0.598238 | no |
| 2025 | 0.568162 | no |

### OPEC | 1d | raw_return

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.513261 | no |
| 2019 | 0.549126 | no |
| 2020 | 0.552014 | no |
| 2021 | 0.528916 | no |
| 2022 | 0.558488 | no |
| 2023 | 0.524067 | no |
| 2024 | 0.480192 | yes |
| 2025 | 0.669139 | no |

### OPEC | 1d | spy_relative_ar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.494274 | yes |
| 2019 | 0.607595 | no |
| 2020 | 0.532171 | no |
| 2021 | 0.513855 | no |
| 2022 | 0.523695 | no |
| 2023 | 0.515644 | no |
| 2024 | 0.495198 | yes |
| 2025 | 0.797923 | no |

### OPEC | 1d | sector_relative_ar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.454189 | no |
| 2019 | 0.471971 | no |
| 2020 | 0.467228 | no |
| 2021 | 0.463253 | no |
| 2022 | 0.489802 | no |
| 2023 | 0.460289 | no |
| 2024 | 0.442377 | no |
| 2025 | 0.496439 | no |

### OPEC | 1d | sar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.567209 | no |
| 2019 | 0.613321 | no |
| 2020 | 0.585689 | no |
| 2021 | 0.535542 | no |
| 2022 | 0.563287 | no |
| 2023 | 0.610710 | no |
| 2024 | 0.593637 | no |
| 2025 | 0.726409 | no |

### OPEC | 5d | raw_return

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.452245 | no |
| 2019 | 0.483607 | no |
| 2020 | 0.480729 | no |
| 2021 | 0.468040 | no |
| 2022 | 0.499652 | no |
| 2023 | 0.418670 | no |
| 2024 | 0.441423 | no |
| 2025 | 0.461822 | no |

### OPEC | 5d | spy_relative_ar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.564861 | no |
| 2019 | 0.610121 | no |
| 2020 | 0.595655 | no |
| 2021 | 0.573153 | no |
| 2022 | 0.601394 | no |
| 2023 | 0.553748 | no |
| 2024 | 0.548117 | no |
| 2025 | 0.608171 | no |

### OPEC | 5d | sector_relative_ar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.423378 | no |
| 2019 | 0.447256 | no |
| 2020 | 0.359495 | no |
| 2021 | 0.424006 | no |
| 2022 | 0.511150 | yes |
| 2023 | 0.428571 | no |
| 2024 | 0.411437 | no |
| 2025 | 0.484930 | no |

### OPEC | 5d | sar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.579116 | no |
| 2019 | 0.627940 | no |
| 2020 | 0.632796 | no |
| 2021 | 0.516335 | no |
| 2022 | 0.639024 | no |
| 2023 | 0.519095 | no |
| 2024 | 0.539052 | no |
| 2025 | 0.503014 | no |

### OPEC | 20d | raw_return

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.432961 | no |
| 2019 | 0.402355 | no |
| 2020 | 0.415287 | no |
| 2021 | 0.452092 | no |
| 2022 | 0.424751 | no |
| 2023 | 0.419397 | no |
| 2024 | 0.398295 | no |
| 2025 | 0.440299 | no |

### OPEC | 20d | spy_relative_ar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.425279 | no |
| 2019 | 0.382964 | no |
| 2020 | 0.417834 | no |
| 2021 | 0.388664 | no |
| 2022 | 0.402363 | no |
| 2023 | 0.424640 | no |
| 2024 | 0.383678 | no |
| 2025 | 0.397819 | no |

### OPEC | 20d | sector_relative_ar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.458799 | no |
| 2019 | 0.438366 | no |
| 2020 | 0.448408 | no |
| 2021 | 0.419703 | no |
| 2022 | 0.465796 | no |
| 2023 | 0.469201 | no |
| 2024 | 0.434836 | no |
| 2025 | 0.499426 | no |

### OPEC | 20d | sar

| removed year | leave-year-out MEMP | sign flip |
|---|---|---|
| 2018 | 0.399441 | no |
| 2019 | 0.337950 | no |
| 2020 | 0.383439 | no |
| 2021 | 0.391363 | no |
| 2022 | 0.388682 | no |
| 2023 | 0.378768 | no |
| 2024 | 0.344702 | no |
| 2025 | 0.383467 | no |

## C. Full leave-one-event-out (F2) appendix

Each event is removed once with the reference held fixed; the leave-one MEMP is the median of the surviving event percentiles. Every event is shown.

### FOMC | 1d | raw_return

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| fomc-policy-decision-2018-01-31 | 0.682544 | no |
| fomc-policy-decision-2018-03-21 | 0.669053 | no |
| fomc-policy-decision-2018-05-02 | 0.682544 | no |
| fomc-policy-decision-2018-06-13 | 0.682544 | no |
| fomc-policy-decision-2018-08-01 | 0.682544 | no |
| fomc-policy-decision-2018-09-26 | 0.682544 | no |
| fomc-policy-decision-2018-11-08 | 0.682544 | no |
| fomc-policy-decision-2018-12-19 | 0.682544 | no |
| fomc-policy-decision-2019-01-30 | 0.682544 | no |
| fomc-policy-decision-2019-03-20 | 0.682544 | no |
| fomc-policy-decision-2019-05-01 | 0.682544 | no |
| fomc-policy-decision-2019-06-19 | 0.682544 | no |
| fomc-policy-decision-2019-07-31 | 0.669053 | no |
| fomc-policy-decision-2019-09-18 | 0.682544 | no |
| fomc-policy-decision-2019-10-30 | 0.677037 | no |
| fomc-policy-decision-2019-12-11 | 0.669053 | no |
| fomc-policy-decision-2020-01-29 | 0.682544 | no |
| fomc-policy-decision-2020-03-03 | 0.669053 | no |
| fomc-policy-decision-2020-03-15 | 0.669053 | no |
| fomc-policy-decision-2020-04-29 | 0.669053 | no |
| fomc-policy-decision-2020-06-10 | 0.669053 | no |
| fomc-policy-decision-2020-07-29 | 0.669053 | no |
| fomc-policy-decision-2020-09-16 | 0.682544 | no |
| fomc-policy-decision-2020-11-05 | 0.669053 | no |
| fomc-policy-decision-2020-12-16 | 0.682544 | no |
| fomc-policy-decision-2021-01-27 | 0.669053 | no |
| fomc-policy-decision-2021-03-17 | 0.682544 | no |
| fomc-policy-decision-2021-04-28 | 0.682544 | no |
| fomc-policy-decision-2021-06-16 | 0.669053 | no |
| fomc-policy-decision-2021-07-28 | 0.682544 | no |
| fomc-policy-decision-2021-09-22 | 0.669053 | no |
| fomc-policy-decision-2021-11-03 | 0.669053 | no |
| fomc-policy-decision-2021-12-15 | 0.682544 | no |
| fomc-policy-decision-2022-01-26 | 0.669053 | no |
| fomc-policy-decision-2022-03-16 | 0.682544 | no |
| fomc-policy-decision-2022-05-04 | 0.669053 | no |
| fomc-policy-decision-2022-06-15 | 0.669053 | no |
| fomc-policy-decision-2022-07-27 | 0.682544 | no |
| fomc-policy-decision-2022-09-21 | 0.669053 | no |
| fomc-policy-decision-2022-11-02 | 0.682544 | no |
| fomc-policy-decision-2022-12-14 | 0.669053 | no |
| fomc-policy-decision-2023-02-01 | 0.669053 | no |
| fomc-policy-decision-2023-03-22 | 0.669053 | no |
| fomc-policy-decision-2023-05-03 | 0.669053 | no |
| fomc-policy-decision-2023-06-14 | 0.669053 | no |
| fomc-policy-decision-2023-07-26 | 0.669053 | no |
| fomc-policy-decision-2023-09-20 | 0.682544 | no |
| fomc-policy-decision-2023-11-01 | 0.669053 | no |
| fomc-policy-decision-2023-12-13 | 0.669053 | no |
| fomc-policy-decision-2024-01-31 | 0.669053 | no |
| fomc-policy-decision-2024-03-20 | 0.682544 | no |
| fomc-policy-decision-2024-05-01 | 0.669053 | no |
| fomc-policy-decision-2024-06-12 | 0.669053 | no |
| fomc-policy-decision-2024-07-31 | 0.669053 | no |
| fomc-policy-decision-2024-09-18 | 0.669053 | no |
| fomc-policy-decision-2024-11-07 | 0.682544 | no |
| fomc-policy-decision-2024-12-18 | 0.682544 | no |
| fomc-policy-decision-2025-01-29 | 0.682544 | no |
| fomc-policy-decision-2025-03-19 | 0.682544 | no |
| fomc-policy-decision-2025-05-07 | 0.669053 | no |
| fomc-policy-decision-2025-06-18 | 0.682544 | no |
| fomc-policy-decision-2025-07-30 | 0.682544 | no |
| fomc-policy-decision-2025-09-17 | 0.669053 | no |
| fomc-policy-decision-2025-10-29 | 0.682544 | no |
| fomc-policy-decision-2025-12-10 | 0.682544 | no |

### FOMC | 1d | spy_relative_ar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| fomc-policy-decision-2018-01-31 | 0.664648 | no |
| fomc-policy-decision-2018-03-21 | 0.675110 | no |
| fomc-policy-decision-2018-05-02 | 0.675110 | no |
| fomc-policy-decision-2018-06-13 | 0.675110 | no |
| fomc-policy-decision-2018-08-01 | 0.675110 | no |
| fomc-policy-decision-2018-09-26 | 0.675110 | no |
| fomc-policy-decision-2018-11-08 | 0.675110 | no |
| fomc-policy-decision-2018-12-19 | 0.664648 | no |
| fomc-policy-decision-2019-01-30 | 0.664648 | no |
| fomc-policy-decision-2019-03-20 | 0.664648 | no |
| fomc-policy-decision-2019-05-01 | 0.664648 | no |
| fomc-policy-decision-2019-06-19 | 0.675110 | no |
| fomc-policy-decision-2019-07-31 | 0.664648 | no |
| fomc-policy-decision-2019-09-18 | 0.675110 | no |
| fomc-policy-decision-2019-10-30 | 0.664648 | no |
| fomc-policy-decision-2019-12-11 | 0.664648 | no |
| fomc-policy-decision-2020-01-29 | 0.675110 | no |
| fomc-policy-decision-2020-03-03 | 0.664648 | no |
| fomc-policy-decision-2020-03-15 | 0.664648 | no |
| fomc-policy-decision-2020-04-29 | 0.664648 | no |
| fomc-policy-decision-2020-06-10 | 0.664648 | no |
| fomc-policy-decision-2020-07-29 | 0.664648 | no |
| fomc-policy-decision-2020-09-16 | 0.675110 | no |
| fomc-policy-decision-2020-11-05 | 0.664648 | no |
| fomc-policy-decision-2020-12-16 | 0.675110 | no |
| fomc-policy-decision-2021-01-27 | 0.675110 | no |
| fomc-policy-decision-2021-03-17 | 0.664648 | no |
| fomc-policy-decision-2021-04-28 | 0.675110 | no |
| fomc-policy-decision-2021-06-16 | 0.664648 | no |
| fomc-policy-decision-2021-07-28 | 0.675110 | no |
| fomc-policy-decision-2021-09-22 | 0.664648 | no |
| fomc-policy-decision-2021-11-03 | 0.664648 | no |
| fomc-policy-decision-2021-12-15 | 0.675110 | no |
| fomc-policy-decision-2022-01-26 | 0.664648 | no |
| fomc-policy-decision-2022-03-16 | 0.664648 | no |
| fomc-policy-decision-2022-05-04 | 0.675110 | no |
| fomc-policy-decision-2022-06-15 | 0.675110 | no |
| fomc-policy-decision-2022-07-27 | 0.664648 | no |
| fomc-policy-decision-2022-09-21 | 0.664648 | no |
| fomc-policy-decision-2022-11-02 | 0.675110 | no |
| fomc-policy-decision-2022-12-14 | 0.675110 | no |
| fomc-policy-decision-2023-02-01 | 0.664648 | no |
| fomc-policy-decision-2023-03-22 | 0.664648 | no |
| fomc-policy-decision-2023-05-03 | 0.664648 | no |
| fomc-policy-decision-2023-06-14 | 0.675110 | no |
| fomc-policy-decision-2023-07-26 | 0.675110 | no |
| fomc-policy-decision-2023-09-20 | 0.675110 | no |
| fomc-policy-decision-2023-11-01 | 0.664648 | no |
| fomc-policy-decision-2023-12-13 | 0.664648 | no |
| fomc-policy-decision-2024-01-31 | 0.664648 | no |
| fomc-policy-decision-2024-03-20 | 0.675110 | no |
| fomc-policy-decision-2024-05-01 | 0.675110 | no |
| fomc-policy-decision-2024-06-12 | 0.664648 | no |
| fomc-policy-decision-2024-07-31 | 0.664648 | no |
| fomc-policy-decision-2024-09-18 | 0.675110 | no |
| fomc-policy-decision-2024-11-07 | 0.675110 | no |
| fomc-policy-decision-2024-12-18 | 0.675110 | no |
| fomc-policy-decision-2025-01-29 | 0.675110 | no |
| fomc-policy-decision-2025-03-19 | 0.675110 | no |
| fomc-policy-decision-2025-05-07 | 0.664648 | no |
| fomc-policy-decision-2025-06-18 | 0.675110 | no |
| fomc-policy-decision-2025-07-30 | 0.675110 | no |
| fomc-policy-decision-2025-09-17 | 0.664648 | no |
| fomc-policy-decision-2025-10-29 | 0.667401 | no |
| fomc-policy-decision-2025-12-10 | 0.675110 | no |

### FOMC | 1d | sector_relative_ar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| fomc-policy-decision-2018-01-31 | 0.678139 | no |
| fomc-policy-decision-2018-03-21 | 0.678139 | no |
| fomc-policy-decision-2018-05-02 | 0.678139 | no |
| fomc-policy-decision-2018-06-13 | 0.678139 | no |
| fomc-policy-decision-2018-08-01 | 0.635738 | no |
| fomc-policy-decision-2018-09-26 | 0.678139 | no |
| fomc-policy-decision-2018-11-08 | 0.678139 | no |
| fomc-policy-decision-2018-12-19 | 0.635738 | no |
| fomc-policy-decision-2019-01-30 | 0.635738 | no |
| fomc-policy-decision-2019-03-20 | 0.635738 | no |
| fomc-policy-decision-2019-05-01 | 0.635738 | no |
| fomc-policy-decision-2019-06-19 | 0.678139 | no |
| fomc-policy-decision-2019-07-31 | 0.635738 | no |
| fomc-policy-decision-2019-09-18 | 0.678139 | no |
| fomc-policy-decision-2019-10-30 | 0.635738 | no |
| fomc-policy-decision-2019-12-11 | 0.635738 | no |
| fomc-policy-decision-2020-01-29 | 0.678139 | no |
| fomc-policy-decision-2020-03-03 | 0.635738 | no |
| fomc-policy-decision-2020-03-15 | 0.678139 | no |
| fomc-policy-decision-2020-04-29 | 0.635738 | no |
| fomc-policy-decision-2020-06-10 | 0.635738 | no |
| fomc-policy-decision-2020-07-29 | 0.678139 | no |
| fomc-policy-decision-2020-09-16 | 0.678139 | no |
| fomc-policy-decision-2020-11-05 | 0.635738 | no |
| fomc-policy-decision-2020-12-16 | 0.678139 | no |
| fomc-policy-decision-2021-01-27 | 0.678139 | no |
| fomc-policy-decision-2021-03-17 | 0.678139 | no |
| fomc-policy-decision-2021-04-28 | 0.678139 | no |
| fomc-policy-decision-2021-06-16 | 0.635738 | no |
| fomc-policy-decision-2021-07-28 | 0.678139 | no |
| fomc-policy-decision-2021-09-22 | 0.635738 | no |
| fomc-policy-decision-2021-11-03 | 0.678139 | no |
| fomc-policy-decision-2021-12-15 | 0.635738 | no |
| fomc-policy-decision-2022-01-26 | 0.635738 | no |
| fomc-policy-decision-2022-03-16 | 0.635738 | no |
| fomc-policy-decision-2022-05-04 | 0.678139 | no |
| fomc-policy-decision-2022-06-15 | 0.635738 | no |
| fomc-policy-decision-2022-07-27 | 0.678139 | no |
| fomc-policy-decision-2022-09-21 | 0.678139 | no |
| fomc-policy-decision-2022-11-02 | 0.678139 | no |
| fomc-policy-decision-2022-12-14 | 0.678139 | no |
| fomc-policy-decision-2023-02-01 | 0.635738 | no |
| fomc-policy-decision-2023-03-22 | 0.635738 | no |
| fomc-policy-decision-2023-05-03 | 0.635738 | no |
| fomc-policy-decision-2023-06-14 | 0.678139 | no |
| fomc-policy-decision-2023-07-26 | 0.678139 | no |
| fomc-policy-decision-2023-09-20 | 0.678139 | no |
| fomc-policy-decision-2023-11-01 | 0.635738 | no |
| fomc-policy-decision-2023-12-13 | 0.635738 | no |
| fomc-policy-decision-2024-01-31 | 0.635738 | no |
| fomc-policy-decision-2024-03-20 | 0.678139 | no |
| fomc-policy-decision-2024-05-01 | 0.635738 | no |
| fomc-policy-decision-2024-06-12 | 0.635738 | no |
| fomc-policy-decision-2024-07-31 | 0.635738 | no |
| fomc-policy-decision-2024-09-18 | 0.635738 | no |
| fomc-policy-decision-2024-11-07 | 0.678139 | no |
| fomc-policy-decision-2024-12-18 | 0.635738 | no |
| fomc-policy-decision-2025-01-29 | 0.678139 | no |
| fomc-policy-decision-2025-03-19 | 0.650881 | no |
| fomc-policy-decision-2025-05-07 | 0.635738 | no |
| fomc-policy-decision-2025-06-18 | 0.678139 | no |
| fomc-policy-decision-2025-07-30 | 0.678139 | no |
| fomc-policy-decision-2025-09-17 | 0.635738 | no |
| fomc-policy-decision-2025-10-29 | 0.678139 | no |
| fomc-policy-decision-2025-12-10 | 0.635738 | no |

### FOMC | 1d | sar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| fomc-policy-decision-2018-01-31 | 0.725220 | no |
| fomc-policy-decision-2018-03-21 | 0.725220 | no |
| fomc-policy-decision-2018-05-02 | 0.732104 | no |
| fomc-policy-decision-2018-06-13 | 0.732104 | no |
| fomc-policy-decision-2018-08-01 | 0.732104 | no |
| fomc-policy-decision-2018-09-26 | 0.725220 | no |
| fomc-policy-decision-2018-11-08 | 0.732104 | no |
| fomc-policy-decision-2018-12-19 | 0.725220 | no |
| fomc-policy-decision-2019-01-30 | 0.725220 | no |
| fomc-policy-decision-2019-03-20 | 0.725220 | no |
| fomc-policy-decision-2019-05-01 | 0.725220 | no |
| fomc-policy-decision-2019-06-19 | 0.732104 | no |
| fomc-policy-decision-2019-07-31 | 0.725220 | no |
| fomc-policy-decision-2019-09-18 | 0.732104 | no |
| fomc-policy-decision-2019-10-30 | 0.725220 | no |
| fomc-policy-decision-2019-12-11 | 0.725220 | no |
| fomc-policy-decision-2020-01-29 | 0.732104 | no |
| fomc-policy-decision-2020-03-03 | 0.725220 | no |
| fomc-policy-decision-2020-03-15 | 0.725220 | no |
| fomc-policy-decision-2020-04-29 | 0.725220 | no |
| fomc-policy-decision-2020-06-10 | 0.725220 | no |
| fomc-policy-decision-2020-07-29 | 0.732104 | no |
| fomc-policy-decision-2020-09-16 | 0.732104 | no |
| fomc-policy-decision-2020-11-05 | 0.731553 | no |
| fomc-policy-decision-2020-12-16 | 0.732104 | no |
| fomc-policy-decision-2021-01-27 | 0.732104 | no |
| fomc-policy-decision-2021-03-17 | 0.725220 | no |
| fomc-policy-decision-2021-04-28 | 0.732104 | no |
| fomc-policy-decision-2021-06-16 | 0.725220 | no |
| fomc-policy-decision-2021-07-28 | 0.732104 | no |
| fomc-policy-decision-2021-09-22 | 0.725220 | no |
| fomc-policy-decision-2021-11-03 | 0.725220 | no |
| fomc-policy-decision-2021-12-15 | 0.732104 | no |
| fomc-policy-decision-2022-01-26 | 0.725220 | no |
| fomc-policy-decision-2022-03-16 | 0.725220 | no |
| fomc-policy-decision-2022-05-04 | 0.732104 | no |
| fomc-policy-decision-2022-06-15 | 0.732104 | no |
| fomc-policy-decision-2022-07-27 | 0.725220 | no |
| fomc-policy-decision-2022-09-21 | 0.725220 | no |
| fomc-policy-decision-2022-11-02 | 0.732104 | no |
| fomc-policy-decision-2022-12-14 | 0.732104 | no |
| fomc-policy-decision-2023-02-01 | 0.725220 | no |
| fomc-policy-decision-2023-03-22 | 0.725220 | no |
| fomc-policy-decision-2023-05-03 | 0.725220 | no |
| fomc-policy-decision-2023-06-14 | 0.732104 | no |
| fomc-policy-decision-2023-07-26 | 0.732104 | no |
| fomc-policy-decision-2023-09-20 | 0.732104 | no |
| fomc-policy-decision-2023-11-01 | 0.725220 | no |
| fomc-policy-decision-2023-12-13 | 0.725220 | no |
| fomc-policy-decision-2024-01-31 | 0.725220 | no |
| fomc-policy-decision-2024-03-20 | 0.732104 | no |
| fomc-policy-decision-2024-05-01 | 0.732104 | no |
| fomc-policy-decision-2024-06-12 | 0.725220 | no |
| fomc-policy-decision-2024-07-31 | 0.725220 | no |
| fomc-policy-decision-2024-09-18 | 0.732104 | no |
| fomc-policy-decision-2024-11-07 | 0.732104 | no |
| fomc-policy-decision-2024-12-18 | 0.732104 | no |
| fomc-policy-decision-2025-01-29 | 0.732104 | no |
| fomc-policy-decision-2025-03-19 | 0.732104 | no |
| fomc-policy-decision-2025-05-07 | 0.725220 | no |
| fomc-policy-decision-2025-06-18 | 0.732104 | no |
| fomc-policy-decision-2025-07-30 | 0.732104 | no |
| fomc-policy-decision-2025-09-17 | 0.725220 | no |
| fomc-policy-decision-2025-10-29 | 0.732104 | no |
| fomc-policy-decision-2025-12-10 | 0.732104 | no |

### FOMC | 5d | raw_return

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| fomc-policy-decision-2018-01-31 | 0.505774 | no |
| fomc-policy-decision-2018-03-21 | 0.495766 | yes |
| fomc-policy-decision-2018-05-02 | 0.495766 | yes |
| fomc-policy-decision-2018-06-13 | 0.505774 | no |
| fomc-policy-decision-2018-08-01 | 0.505774 | no |
| fomc-policy-decision-2018-09-26 | 0.505774 | no |
| fomc-policy-decision-2018-11-08 | 0.505774 | no |
| fomc-policy-decision-2018-12-19 | 0.505774 | no |
| fomc-policy-decision-2019-01-30 | 0.505774 | no |
| fomc-policy-decision-2019-03-20 | 0.495766 | yes |
| fomc-policy-decision-2019-05-01 | 0.505774 | no |
| fomc-policy-decision-2019-06-19 | 0.505774 | no |
| fomc-policy-decision-2019-07-31 | 0.495766 | yes |
| fomc-policy-decision-2019-09-18 | 0.505774 | no |
| fomc-policy-decision-2019-10-30 | 0.495766 | yes |
| fomc-policy-decision-2019-12-11 | 0.495766 | yes |
| fomc-policy-decision-2020-01-29 | 0.495766 | yes |
| fomc-policy-decision-2020-03-03 | 0.495766 | yes |
| fomc-policy-decision-2020-03-15 | 0.495766 | yes |
| fomc-policy-decision-2020-04-29 | 0.495766 | yes |
| fomc-policy-decision-2020-06-10 | 0.495766 | yes |
| fomc-policy-decision-2020-07-29 | 0.505774 | no |
| fomc-policy-decision-2020-09-16 | 0.495766 | yes |
| fomc-policy-decision-2020-11-05 | 0.495766 | yes |
| fomc-policy-decision-2020-12-16 | 0.505774 | no |
| fomc-policy-decision-2021-01-27 | 0.495766 | yes |
| fomc-policy-decision-2021-03-17 | 0.495766 | yes |
| fomc-policy-decision-2021-04-28 | 0.500385 | no |
| fomc-policy-decision-2021-06-16 | 0.495766 | yes |
| fomc-policy-decision-2021-07-28 | 0.505774 | no |
| fomc-policy-decision-2021-09-22 | 0.495766 | yes |
| fomc-policy-decision-2021-11-03 | 0.505774 | no |
| fomc-policy-decision-2021-12-15 | 0.505774 | no |
| fomc-policy-decision-2022-01-26 | 0.505774 | no |
| fomc-policy-decision-2022-03-16 | 0.495766 | yes |
| fomc-policy-decision-2022-05-04 | 0.495766 | yes |
| fomc-policy-decision-2022-06-15 | 0.505774 | no |
| fomc-policy-decision-2022-07-27 | 0.505774 | no |
| fomc-policy-decision-2022-09-21 | 0.495766 | yes |
| fomc-policy-decision-2022-11-02 | 0.505774 | no |
| fomc-policy-decision-2022-12-14 | 0.505774 | no |
| fomc-policy-decision-2023-02-01 | 0.505774 | no |
| fomc-policy-decision-2023-03-22 | 0.505774 | no |
| fomc-policy-decision-2023-05-03 | 0.495766 | yes |
| fomc-policy-decision-2023-06-14 | 0.495766 | yes |
| fomc-policy-decision-2023-07-26 | 0.505774 | no |
| fomc-policy-decision-2023-09-20 | 0.495766 | yes |
| fomc-policy-decision-2023-11-01 | 0.495766 | yes |
| fomc-policy-decision-2023-12-13 | 0.505774 | no |
| fomc-policy-decision-2024-01-31 | 0.495766 | yes |
| fomc-policy-decision-2024-03-20 | 0.495766 | yes |
| fomc-policy-decision-2024-05-01 | 0.495766 | yes |
| fomc-policy-decision-2024-06-12 | 0.505774 | no |
| fomc-policy-decision-2024-07-31 | 0.495766 | yes |
| fomc-policy-decision-2024-09-18 | 0.495766 | yes |
| fomc-policy-decision-2024-11-07 | 0.505774 | no |
| fomc-policy-decision-2024-12-18 | 0.495766 | yes |
| fomc-policy-decision-2025-01-29 | 0.505774 | no |
| fomc-policy-decision-2025-03-19 | 0.505774 | no |
| fomc-policy-decision-2025-05-07 | 0.495766 | yes |
| fomc-policy-decision-2025-06-18 | 0.495766 | yes |
| fomc-policy-decision-2025-07-30 | 0.505774 | no |
| fomc-policy-decision-2025-09-17 | 0.505774 | no |
| fomc-policy-decision-2025-10-29 | 0.505774 | no |
| fomc-policy-decision-2025-12-10 | 0.505774 | no |

### FOMC | 5d | spy_relative_ar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| fomc-policy-decision-2018-01-31 | 0.526559 | no |
| fomc-policy-decision-2018-03-21 | 0.530023 | no |
| fomc-policy-decision-2018-05-02 | 0.530023 | no |
| fomc-policy-decision-2018-06-13 | 0.530023 | no |
| fomc-policy-decision-2018-08-01 | 0.530023 | no |
| fomc-policy-decision-2018-09-26 | 0.530023 | no |
| fomc-policy-decision-2018-11-08 | 0.530023 | no |
| fomc-policy-decision-2018-12-19 | 0.530023 | no |
| fomc-policy-decision-2019-01-30 | 0.530023 | no |
| fomc-policy-decision-2019-03-20 | 0.526559 | no |
| fomc-policy-decision-2019-05-01 | 0.530023 | no |
| fomc-policy-decision-2019-06-19 | 0.530023 | no |
| fomc-policy-decision-2019-07-31 | 0.526559 | no |
| fomc-policy-decision-2019-09-18 | 0.530023 | no |
| fomc-policy-decision-2019-10-30 | 0.526559 | no |
| fomc-policy-decision-2019-12-11 | 0.526559 | no |
| fomc-policy-decision-2020-01-29 | 0.526559 | no |
| fomc-policy-decision-2020-03-03 | 0.526559 | no |
| fomc-policy-decision-2020-03-15 | 0.526559 | no |
| fomc-policy-decision-2020-04-29 | 0.526559 | no |
| fomc-policy-decision-2020-06-10 | 0.530023 | no |
| fomc-policy-decision-2020-07-29 | 0.526559 | no |
| fomc-policy-decision-2020-09-16 | 0.526559 | no |
| fomc-policy-decision-2020-11-05 | 0.526559 | no |
| fomc-policy-decision-2020-12-16 | 0.530023 | no |
| fomc-policy-decision-2021-01-27 | 0.526559 | no |
| fomc-policy-decision-2021-03-17 | 0.526559 | no |
| fomc-policy-decision-2021-04-28 | 0.526559 | no |
| fomc-policy-decision-2021-06-16 | 0.526559 | no |
| fomc-policy-decision-2021-07-28 | 0.530023 | no |
| fomc-policy-decision-2021-09-22 | 0.526559 | no |
| fomc-policy-decision-2021-11-03 | 0.530023 | no |
| fomc-policy-decision-2021-12-15 | 0.530023 | no |
| fomc-policy-decision-2022-01-26 | 0.526559 | no |
| fomc-policy-decision-2022-03-16 | 0.526559 | no |
| fomc-policy-decision-2022-05-04 | 0.530023 | no |
| fomc-policy-decision-2022-06-15 | 0.529253 | no |
| fomc-policy-decision-2022-07-27 | 0.530023 | no |
| fomc-policy-decision-2022-09-21 | 0.526559 | no |
| fomc-policy-decision-2022-11-02 | 0.530023 | no |
| fomc-policy-decision-2022-12-14 | 0.526559 | no |
| fomc-policy-decision-2023-02-01 | 0.530023 | no |
| fomc-policy-decision-2023-03-22 | 0.530023 | no |
| fomc-policy-decision-2023-05-03 | 0.526559 | no |
| fomc-policy-decision-2023-06-14 | 0.526559 | no |
| fomc-policy-decision-2023-07-26 | 0.530023 | no |
| fomc-policy-decision-2023-09-20 | 0.530023 | no |
| fomc-policy-decision-2023-11-01 | 0.526559 | no |
| fomc-policy-decision-2023-12-13 | 0.530023 | no |
| fomc-policy-decision-2024-01-31 | 0.526559 | no |
| fomc-policy-decision-2024-03-20 | 0.530023 | no |
| fomc-policy-decision-2024-05-01 | 0.530023 | no |
| fomc-policy-decision-2024-06-12 | 0.530023 | no |
| fomc-policy-decision-2024-07-31 | 0.526559 | no |
| fomc-policy-decision-2024-09-18 | 0.526559 | no |
| fomc-policy-decision-2024-11-07 | 0.526559 | no |
| fomc-policy-decision-2024-12-18 | 0.530023 | no |
| fomc-policy-decision-2025-01-29 | 0.530023 | no |
| fomc-policy-decision-2025-03-19 | 0.530023 | no |
| fomc-policy-decision-2025-05-07 | 0.530023 | no |
| fomc-policy-decision-2025-06-18 | 0.526559 | no |
| fomc-policy-decision-2025-07-30 | 0.526559 | no |
| fomc-policy-decision-2025-09-17 | 0.530023 | no |
| fomc-policy-decision-2025-10-29 | 0.526559 | no |
| fomc-policy-decision-2025-12-10 | 0.526559 | no |

### FOMC | 5d | sector_relative_ar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| fomc-policy-decision-2018-01-31 | 0.396074 | no |
| fomc-policy-decision-2018-03-21 | 0.409161 | no |
| fomc-policy-decision-2018-05-02 | 0.409161 | no |
| fomc-policy-decision-2018-06-13 | 0.396074 | no |
| fomc-policy-decision-2018-08-01 | 0.409161 | no |
| fomc-policy-decision-2018-09-26 | 0.409161 | no |
| fomc-policy-decision-2018-11-08 | 0.409161 | no |
| fomc-policy-decision-2018-12-19 | 0.409161 | no |
| fomc-policy-decision-2019-01-30 | 0.409161 | no |
| fomc-policy-decision-2019-03-20 | 0.409161 | no |
| fomc-policy-decision-2019-05-01 | 0.396074 | no |
| fomc-policy-decision-2019-06-19 | 0.409161 | no |
| fomc-policy-decision-2019-07-31 | 0.396074 | no |
| fomc-policy-decision-2019-09-18 | 0.409161 | no |
| fomc-policy-decision-2019-10-30 | 0.409161 | no |
| fomc-policy-decision-2019-12-11 | 0.396074 | no |
| fomc-policy-decision-2020-01-29 | 0.396074 | no |
| fomc-policy-decision-2020-03-03 | 0.396074 | no |
| fomc-policy-decision-2020-03-15 | 0.409161 | no |
| fomc-policy-decision-2020-04-29 | 0.396074 | no |
| fomc-policy-decision-2020-06-10 | 0.409161 | no |
| fomc-policy-decision-2020-07-29 | 0.409161 | no |
| fomc-policy-decision-2020-09-16 | 0.396074 | no |
| fomc-policy-decision-2020-11-05 | 0.396074 | no |
| fomc-policy-decision-2020-12-16 | 0.409161 | no |
| fomc-policy-decision-2021-01-27 | 0.409161 | no |
| fomc-policy-decision-2021-03-17 | 0.396074 | no |
| fomc-policy-decision-2021-04-28 | 0.409161 | no |
| fomc-policy-decision-2021-06-16 | 0.396074 | no |
| fomc-policy-decision-2021-07-28 | 0.396074 | no |
| fomc-policy-decision-2021-09-22 | 0.396074 | no |
| fomc-policy-decision-2021-11-03 | 0.409161 | no |
| fomc-policy-decision-2021-12-15 | 0.409161 | no |
| fomc-policy-decision-2022-01-26 | 0.396074 | no |
| fomc-policy-decision-2022-03-16 | 0.396074 | no |
| fomc-policy-decision-2022-05-04 | 0.409161 | no |
| fomc-policy-decision-2022-06-15 | 0.409161 | no |
| fomc-policy-decision-2022-07-27 | 0.409161 | no |
| fomc-policy-decision-2022-09-21 | 0.409161 | no |
| fomc-policy-decision-2022-11-02 | 0.409161 | no |
| fomc-policy-decision-2022-12-14 | 0.396074 | no |
| fomc-policy-decision-2023-02-01 | 0.396074 | no |
| fomc-policy-decision-2023-03-22 | 0.409161 | no |
| fomc-policy-decision-2023-05-03 | 0.396074 | no |
| fomc-policy-decision-2023-06-14 | 0.396074 | no |
| fomc-policy-decision-2023-07-26 | 0.409161 | no |
| fomc-policy-decision-2023-09-20 | 0.409161 | no |
| fomc-policy-decision-2023-11-01 | 0.396074 | no |
| fomc-policy-decision-2023-12-13 | 0.396074 | no |
| fomc-policy-decision-2024-01-31 | 0.396074 | no |
| fomc-policy-decision-2024-03-20 | 0.396074 | no |
| fomc-policy-decision-2024-05-01 | 0.396074 | no |
| fomc-policy-decision-2024-06-12 | 0.396074 | no |
| fomc-policy-decision-2024-07-31 | 0.396074 | no |
| fomc-policy-decision-2024-09-18 | 0.396074 | no |
| fomc-policy-decision-2024-11-07 | 0.409161 | no |
| fomc-policy-decision-2024-12-18 | 0.396074 | no |
| fomc-policy-decision-2025-01-29 | 0.397229 | no |
| fomc-policy-decision-2025-03-19 | 0.409161 | no |
| fomc-policy-decision-2025-05-07 | 0.396074 | no |
| fomc-policy-decision-2025-06-18 | 0.396074 | no |
| fomc-policy-decision-2025-07-30 | 0.409161 | no |
| fomc-policy-decision-2025-09-17 | 0.409161 | no |
| fomc-policy-decision-2025-10-29 | 0.409161 | no |
| fomc-policy-decision-2025-12-10 | 0.396074 | no |

### FOMC | 5d | sar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| fomc-policy-decision-2018-01-31 | 0.555042 | no |
| fomc-policy-decision-2018-03-21 | 0.555042 | no |
| fomc-policy-decision-2018-05-02 | 0.574288 | no |
| fomc-policy-decision-2018-06-13 | 0.574288 | no |
| fomc-policy-decision-2018-08-01 | 0.574288 | no |
| fomc-policy-decision-2018-09-26 | 0.574288 | no |
| fomc-policy-decision-2018-11-08 | 0.574288 | no |
| fomc-policy-decision-2018-12-19 | 0.574288 | no |
| fomc-policy-decision-2019-01-30 | 0.574288 | no |
| fomc-policy-decision-2019-03-20 | 0.555042 | no |
| fomc-policy-decision-2019-05-01 | 0.574288 | no |
| fomc-policy-decision-2019-06-19 | 0.574288 | no |
| fomc-policy-decision-2019-07-31 | 0.555042 | no |
| fomc-policy-decision-2019-09-18 | 0.574288 | no |
| fomc-policy-decision-2019-10-30 | 0.555042 | no |
| fomc-policy-decision-2019-12-11 | 0.555042 | no |
| fomc-policy-decision-2020-01-29 | 0.555042 | no |
| fomc-policy-decision-2020-03-03 | 0.555042 | no |
| fomc-policy-decision-2020-03-15 | 0.555042 | no |
| fomc-policy-decision-2020-04-29 | 0.555042 | no |
| fomc-policy-decision-2020-06-10 | 0.574288 | no |
| fomc-policy-decision-2020-07-29 | 0.574288 | no |
| fomc-policy-decision-2020-09-16 | 0.555042 | no |
| fomc-policy-decision-2020-11-05 | 0.555042 | no |
| fomc-policy-decision-2020-12-16 | 0.574288 | no |
| fomc-policy-decision-2021-01-27 | 0.574288 | no |
| fomc-policy-decision-2021-03-17 | 0.555042 | no |
| fomc-policy-decision-2021-04-28 | 0.555042 | no |
| fomc-policy-decision-2021-06-16 | 0.555042 | no |
| fomc-policy-decision-2021-07-28 | 0.574288 | no |
| fomc-policy-decision-2021-09-22 | 0.555042 | no |
| fomc-policy-decision-2021-11-03 | 0.574288 | no |
| fomc-policy-decision-2021-12-15 | 0.574288 | no |
| fomc-policy-decision-2022-01-26 | 0.555042 | no |
| fomc-policy-decision-2022-03-16 | 0.555042 | no |
| fomc-policy-decision-2022-05-04 | 0.574288 | no |
| fomc-policy-decision-2022-06-15 | 0.555042 | no |
| fomc-policy-decision-2022-07-27 | 0.555042 | no |
| fomc-policy-decision-2022-09-21 | 0.555042 | no |
| fomc-policy-decision-2022-11-02 | 0.574288 | no |
| fomc-policy-decision-2022-12-14 | 0.555042 | no |
| fomc-policy-decision-2023-02-01 | 0.555042 | no |
| fomc-policy-decision-2023-03-22 | 0.574288 | no |
| fomc-policy-decision-2023-05-03 | 0.555042 | no |
| fomc-policy-decision-2023-06-14 | 0.555042 | no |
| fomc-policy-decision-2023-07-26 | 0.574288 | no |
| fomc-policy-decision-2023-09-20 | 0.574288 | no |
| fomc-policy-decision-2023-11-01 | 0.572748 | no |
| fomc-policy-decision-2023-12-13 | 0.574288 | no |
| fomc-policy-decision-2024-01-31 | 0.555042 | no |
| fomc-policy-decision-2024-03-20 | 0.574288 | no |
| fomc-policy-decision-2024-05-01 | 0.574288 | no |
| fomc-policy-decision-2024-06-12 | 0.574288 | no |
| fomc-policy-decision-2024-07-31 | 0.555042 | no |
| fomc-policy-decision-2024-09-18 | 0.555042 | no |
| fomc-policy-decision-2024-11-07 | 0.574288 | no |
| fomc-policy-decision-2024-12-18 | 0.574288 | no |
| fomc-policy-decision-2025-01-29 | 0.574288 | no |
| fomc-policy-decision-2025-03-19 | 0.574288 | no |
| fomc-policy-decision-2025-05-07 | 0.574288 | no |
| fomc-policy-decision-2025-06-18 | 0.555042 | no |
| fomc-policy-decision-2025-07-30 | 0.555042 | no |
| fomc-policy-decision-2025-09-17 | 0.574288 | no |
| fomc-policy-decision-2025-10-29 | 0.555042 | no |
| fomc-policy-decision-2025-12-10 | 0.555042 | no |

### OPEC | 1d | raw_return

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.526537 | no |
| opec-2018-12-07-cut-1p2 | 0.526537 | no |
| opec-2019-07-02-extension | 0.531792 | no |
| opec-2019-12-06-deepen-1p7 | 0.531792 | no |
| opec-2020-04-12-cut-9p7 | 0.531792 | no |
| opec-2020-06-06-extension | 0.526537 | no |
| opec-2020-12-03-restoration-start | 0.526537 | no |
| opec-2021-01-05-feb-mar-levels | 0.526537 | no |
| opec-2021-04-01-gradual-return | 0.526537 | no |
| opec-2021-07-18-monthly-400k | 0.526537 | no |
| opec-2022-06-02-accelerate-648k | 0.531792 | no |
| opec-2022-08-03-sep-100k | 0.526537 | no |
| opec-2022-09-05-oct-minus-100k | 0.526537 | no |
| opec-2022-10-05-cut-2mbd | 0.531792 | no |
| opec-2023-04-02-voluntary-1p16 | 0.526537 | no |
| opec-2023-06-04-2024-levels | 0.531792 | no |
| opec-2023-11-30-voluntary-2p2 | 0.531792 | no |
| opec-2024-03-03-q2-extension | 0.531792 | no |
| opec-2024-06-02-extension-schedule | 0.526537 | no |
| opec-2024-09-05-two-month-delay | 0.526537 | no |
| opec-2024-11-03-one-month-delay | 0.526537 | no |
| opec-2024-12-05-april-start | 0.526537 | no |
| opec-2025-03-03-activation | 0.531792 | no |
| opec-2025-04-03-may-411k | 0.526537 | no |
| opec-2025-05-03-jun-411k | 0.526537 | no |
| opec-2025-06-01-jul-411k | 0.531792 | no |
| opec-2025-07-05-aug-548k | 0.531792 | no |
| opec-2025-08-03-sep-547k | 0.531792 | no |
| opec-2025-09-07-oct-137k | 0.531792 | no |
| opec-2025-10-05-nov-137k | 0.531792 | no |
| opec-2025-11-02-dec-137k-pause | 0.531792 | no |
| opec-2025-11-30-2026-hold | 0.531792 | no |

### OPEC | 1d | spy_relative_ar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.517604 | no |
| opec-2018-12-07-cut-1p2 | 0.517604 | no |
| opec-2019-07-02-extension | 0.529164 | no |
| opec-2019-12-06-deepen-1p7 | 0.529164 | no |
| opec-2020-04-12-cut-9p7 | 0.517604 | no |
| opec-2020-06-06-extension | 0.517604 | no |
| opec-2020-12-03-restoration-start | 0.517604 | no |
| opec-2021-01-05-feb-mar-levels | 0.517604 | no |
| opec-2021-04-01-gradual-return | 0.517604 | no |
| opec-2021-07-18-monthly-400k | 0.517604 | no |
| opec-2022-06-02-accelerate-648k | 0.517604 | no |
| opec-2022-08-03-sep-100k | 0.517604 | no |
| opec-2022-09-05-oct-minus-100k | 0.529164 | no |
| opec-2022-10-05-cut-2mbd | 0.517604 | no |
| opec-2023-04-02-voluntary-1p16 | 0.517604 | no |
| opec-2023-06-04-2024-levels | 0.529164 | no |
| opec-2023-11-30-voluntary-2p2 | 0.529164 | no |
| opec-2024-03-03-q2-extension | 0.529164 | no |
| opec-2024-06-02-extension-schedule | 0.517604 | no |
| opec-2024-09-05-two-month-delay | 0.529164 | no |
| opec-2024-11-03-one-month-delay | 0.517604 | no |
| opec-2024-12-05-april-start | 0.517604 | no |
| opec-2025-03-03-activation | 0.529164 | no |
| opec-2025-04-03-may-411k | 0.517604 | no |
| opec-2025-05-03-jun-411k | 0.529164 | no |
| opec-2025-06-01-jul-411k | 0.529164 | no |
| opec-2025-07-05-aug-548k | 0.529164 | no |
| opec-2025-08-03-sep-547k | 0.529164 | no |
| opec-2025-09-07-oct-137k | 0.529164 | no |
| opec-2025-10-05-nov-137k | 0.529164 | no |
| opec-2025-11-02-dec-137k-pause | 0.529164 | no |
| opec-2025-11-30-2026-hold | 0.529164 | no |

### OPEC | 1d | sector_relative_ar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.468208 | no |
| opec-2018-12-07-cut-1p2 | 0.468208 | no |
| opec-2019-07-02-extension | 0.468208 | no |
| opec-2019-12-06-deepen-1p7 | 0.468208 | no |
| opec-2020-04-12-cut-9p7 | 0.468208 | no |
| opec-2020-06-06-extension | 0.468208 | no |
| opec-2020-12-03-restoration-start | 0.468208 | no |
| opec-2021-01-05-feb-mar-levels | 0.468208 | no |
| opec-2021-04-01-gradual-return | 0.468208 | no |
| opec-2021-07-18-monthly-400k | 0.468208 | no |
| opec-2022-06-02-accelerate-648k | 0.476090 | no |
| opec-2022-08-03-sep-100k | 0.468208 | no |
| opec-2022-09-05-oct-minus-100k | 0.468208 | no |
| opec-2022-10-05-cut-2mbd | 0.476090 | no |
| opec-2023-04-02-voluntary-1p16 | 0.476090 | no |
| opec-2023-06-04-2024-levels | 0.468208 | no |
| opec-2023-11-30-voluntary-2p2 | 0.476090 | no |
| opec-2024-03-03-q2-extension | 0.476090 | no |
| opec-2024-06-02-extension-schedule | 0.476090 | no |
| opec-2024-09-05-two-month-delay | 0.476090 | no |
| opec-2024-11-03-one-month-delay | 0.476090 | no |
| opec-2024-12-05-april-start | 0.468208 | no |
| opec-2025-03-03-activation | 0.476090 | no |
| opec-2025-04-03-may-411k | 0.468208 | no |
| opec-2025-05-03-jun-411k | 0.476090 | no |
| opec-2025-06-01-jul-411k | 0.476090 | no |
| opec-2025-07-05-aug-548k | 0.476090 | no |
| opec-2025-08-03-sep-547k | 0.476090 | no |
| opec-2025-09-07-oct-137k | 0.476090 | no |
| opec-2025-10-05-nov-137k | 0.476090 | no |
| opec-2025-11-02-dec-137k-pause | 0.468208 | no |
| opec-2025-11-30-2026-hold | 0.476090 | no |

### OPEC | 1d | sar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.589595 | no |
| opec-2018-12-07-cut-1p2 | 0.589595 | no |
| opec-2019-07-02-extension | 0.615870 | no |
| opec-2019-12-06-deepen-1p7 | 0.615870 | no |
| opec-2020-04-12-cut-9p7 | 0.615870 | no |
| opec-2020-06-06-extension | 0.589595 | no |
| opec-2020-12-03-restoration-start | 0.589595 | no |
| opec-2021-01-05-feb-mar-levels | 0.589595 | no |
| opec-2021-04-01-gradual-return | 0.589595 | no |
| opec-2021-07-18-monthly-400k | 0.589595 | no |
| opec-2022-06-02-accelerate-648k | 0.589595 | no |
| opec-2022-08-03-sep-100k | 0.589595 | no |
| opec-2022-09-05-oct-minus-100k | 0.615870 | no |
| opec-2022-10-05-cut-2mbd | 0.589595 | no |
| opec-2023-04-02-voluntary-1p16 | 0.589595 | no |
| opec-2023-06-04-2024-levels | 0.615870 | no |
| opec-2023-11-30-voluntary-2p2 | 0.615870 | no |
| opec-2024-03-03-q2-extension | 0.615870 | no |
| opec-2024-06-02-extension-schedule | 0.589595 | no |
| opec-2024-09-05-two-month-delay | 0.615870 | no |
| opec-2024-11-03-one-month-delay | 0.589595 | no |
| opec-2024-12-05-april-start | 0.589595 | no |
| opec-2025-03-03-activation | 0.615870 | no |
| opec-2025-04-03-may-411k | 0.589595 | no |
| opec-2025-05-03-jun-411k | 0.615870 | no |
| opec-2025-06-01-jul-411k | 0.615870 | no |
| opec-2025-07-05-aug-548k | 0.615870 | no |
| opec-2025-08-03-sep-547k | 0.615870 | no |
| opec-2025-09-07-oct-137k | 0.615870 | no |
| opec-2025-10-05-nov-137k | 0.615870 | no |
| opec-2025-11-02-dec-137k-pause | 0.615870 | no |
| opec-2025-11-30-2026-hold | 0.589595 | no |

### OPEC | 5d | raw_return

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.481913 | no |
| opec-2018-12-07-cut-1p2 | 0.458001 | no |
| opec-2019-07-02-extension | 0.481913 | no |
| opec-2019-12-06-deepen-1p7 | 0.481913 | no |
| opec-2020-04-12-cut-9p7 | 0.481913 | no |
| opec-2020-06-06-extension | 0.458001 | no |
| opec-2020-12-03-restoration-start | 0.458001 | no |
| opec-2021-01-05-feb-mar-levels | 0.458001 | no |
| opec-2021-04-01-gradual-return | 0.458001 | no |
| opec-2021-07-18-monthly-400k | 0.481913 | no |
| opec-2022-06-02-accelerate-648k | 0.458001 | no |
| opec-2022-08-03-sep-100k | 0.481913 | no |
| opec-2022-09-05-oct-minus-100k | 0.481913 | no |
| opec-2022-10-05-cut-2mbd | 0.481913 | no |
| opec-2023-04-02-voluntary-1p16 | 0.458001 | no |
| opec-2023-06-04-2024-levels | 0.481913 | no |
| opec-2023-11-30-voluntary-2p2 | 0.458001 | no |
| opec-2024-03-03-q2-extension | 0.481913 | no |
| opec-2024-06-02-extension-schedule | 0.458001 | no |
| opec-2024-09-05-two-month-delay | 0.458001 | no |
| opec-2024-11-03-one-month-delay | 0.458001 | no |
| opec-2024-12-05-april-start | 0.481913 | no |
| opec-2025-03-03-activation | 0.481913 | no |
| opec-2025-04-03-may-411k | 0.458001 | no |
| opec-2025-05-03-jun-411k | 0.458001 | no |
| opec-2025-06-01-jul-411k | 0.458001 | no |
| opec-2025-07-05-aug-548k | 0.458001 | no |
| opec-2025-08-03-sep-547k | 0.481913 | no |
| opec-2025-09-07-oct-137k | 0.481913 | no |
| opec-2025-10-05-nov-137k | 0.458001 | no |
| opec-2025-11-02-dec-137k-pause | 0.481913 | no |
| opec-2025-11-30-2026-hold | 0.481913 | no |

### OPEC | 5d | spy_relative_ar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.603924 | no |
| opec-2018-12-07-cut-1p2 | 0.564684 | no |
| opec-2019-07-02-extension | 0.603924 | no |
| opec-2019-12-06-deepen-1p7 | 0.603924 | no |
| opec-2020-04-12-cut-9p7 | 0.603924 | no |
| opec-2020-06-06-extension | 0.564684 | no |
| opec-2020-12-03-restoration-start | 0.564684 | no |
| opec-2021-01-05-feb-mar-levels | 0.564684 | no |
| opec-2021-04-01-gradual-return | 0.564684 | no |
| opec-2021-07-18-monthly-400k | 0.603924 | no |
| opec-2022-06-02-accelerate-648k | 0.564684 | no |
| opec-2022-08-03-sep-100k | 0.603924 | no |
| opec-2022-09-05-oct-minus-100k | 0.603924 | no |
| opec-2022-10-05-cut-2mbd | 0.564684 | no |
| opec-2023-04-02-voluntary-1p16 | 0.564684 | no |
| opec-2023-06-04-2024-levels | 0.603924 | no |
| opec-2023-11-30-voluntary-2p2 | 0.564684 | no |
| opec-2024-03-03-q2-extension | 0.603924 | no |
| opec-2024-06-02-extension-schedule | 0.564684 | no |
| opec-2024-09-05-two-month-delay | 0.564684 | no |
| opec-2024-11-03-one-month-delay | 0.564684 | no |
| opec-2024-12-05-april-start | 0.603924 | no |
| opec-2025-03-03-activation | 0.603924 | no |
| opec-2025-04-03-may-411k | 0.564684 | no |
| opec-2025-05-03-jun-411k | 0.564684 | no |
| opec-2025-06-01-jul-411k | 0.603924 | no |
| opec-2025-07-05-aug-548k | 0.603924 | no |
| opec-2025-08-03-sep-547k | 0.603924 | no |
| opec-2025-09-07-oct-137k | 0.603924 | no |
| opec-2025-10-05-nov-137k | 0.564684 | no |
| opec-2025-11-02-dec-137k-pause | 0.564684 | no |
| opec-2025-11-30-2026-hold | 0.603924 | no |

### OPEC | 5d | sector_relative_ar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.438994 | no |
| opec-2018-12-07-cut-1p2 | 0.418761 | no |
| opec-2019-07-02-extension | 0.438994 | no |
| opec-2019-12-06-deepen-1p7 | 0.418761 | no |
| opec-2020-04-12-cut-9p7 | 0.418761 | no |
| opec-2020-06-06-extension | 0.418761 | no |
| opec-2020-12-03-restoration-start | 0.418761 | no |
| opec-2021-01-05-feb-mar-levels | 0.418761 | no |
| opec-2021-04-01-gradual-return | 0.418761 | no |
| opec-2021-07-18-monthly-400k | 0.438994 | no |
| opec-2022-06-02-accelerate-648k | 0.418761 | no |
| opec-2022-08-03-sep-100k | 0.438994 | no |
| opec-2022-09-05-oct-minus-100k | 0.438994 | no |
| opec-2022-10-05-cut-2mbd | 0.438994 | no |
| opec-2023-04-02-voluntary-1p16 | 0.438994 | no |
| opec-2023-06-04-2024-levels | 0.438994 | no |
| opec-2023-11-30-voluntary-2p2 | 0.418761 | no |
| opec-2024-03-03-q2-extension | 0.438994 | no |
| opec-2024-06-02-extension-schedule | 0.438994 | no |
| opec-2024-09-05-two-month-delay | 0.438994 | no |
| opec-2024-11-03-one-month-delay | 0.418761 | no |
| opec-2024-12-05-april-start | 0.418761 | no |
| opec-2025-03-03-activation | 0.418761 | no |
| opec-2025-04-03-may-411k | 0.418761 | no |
| opec-2025-05-03-jun-411k | 0.418761 | no |
| opec-2025-06-01-jul-411k | 0.438994 | no |
| opec-2025-07-05-aug-548k | 0.438994 | no |
| opec-2025-08-03-sep-547k | 0.438994 | no |
| opec-2025-09-07-oct-137k | 0.418761 | no |
| opec-2025-10-05-nov-137k | 0.418761 | no |
| opec-2025-11-02-dec-137k-pause | 0.438994 | no |
| opec-2025-11-30-2026-hold | 0.438994 | no |

### OPEC | 5d | sar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.635193 | no |
| opec-2018-12-07-cut-1p2 | 0.524831 | no |
| opec-2019-07-02-extension | 0.635193 | no |
| opec-2019-12-06-deepen-1p7 | 0.635193 | no |
| opec-2020-04-12-cut-9p7 | 0.635193 | no |
| opec-2020-06-06-extension | 0.635193 | no |
| opec-2020-12-03-restoration-start | 0.524831 | no |
| opec-2021-01-05-feb-mar-levels | 0.524831 | no |
| opec-2021-04-01-gradual-return | 0.524831 | no |
| opec-2021-07-18-monthly-400k | 0.635193 | no |
| opec-2022-06-02-accelerate-648k | 0.524831 | no |
| opec-2022-08-03-sep-100k | 0.635193 | no |
| opec-2022-09-05-oct-minus-100k | 0.635193 | no |
| opec-2022-10-05-cut-2mbd | 0.635193 | no |
| opec-2023-04-02-voluntary-1p16 | 0.524831 | no |
| opec-2023-06-04-2024-levels | 0.635193 | no |
| opec-2023-11-30-voluntary-2p2 | 0.524831 | no |
| opec-2024-03-03-q2-extension | 0.635193 | no |
| opec-2024-06-02-extension-schedule | 0.524831 | no |
| opec-2024-09-05-two-month-delay | 0.524831 | no |
| opec-2024-11-03-one-month-delay | 0.524831 | no |
| opec-2024-12-05-april-start | 0.635193 | no |
| opec-2025-03-03-activation | 0.635193 | no |
| opec-2025-04-03-may-411k | 0.524831 | no |
| opec-2025-05-03-jun-411k | 0.524831 | no |
| opec-2025-06-01-jul-411k | 0.635193 | no |
| opec-2025-07-05-aug-548k | 0.524831 | no |
| opec-2025-08-03-sep-547k | 0.524831 | no |
| opec-2025-09-07-oct-137k | 0.635193 | no |
| opec-2025-10-05-nov-137k | 0.524831 | no |
| opec-2025-11-02-dec-137k-pause | 0.524831 | no |
| opec-2025-11-30-2026-hold | 0.635193 | no |

### OPEC | 20d | raw_return

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.421822 | no |
| opec-2018-12-07-cut-1p2 | 0.421822 | no |
| opec-2019-07-02-extension | 0.421822 | no |
| opec-2019-12-06-deepen-1p7 | 0.418448 | no |
| opec-2020-04-12-cut-9p7 | 0.418448 | no |
| opec-2020-06-06-extension | 0.418448 | no |
| opec-2020-12-03-restoration-start | 0.418448 | no |
| opec-2021-01-05-feb-mar-levels | 0.418448 | no |
| opec-2021-04-01-gradual-return | 0.418448 | no |
| opec-2021-07-18-monthly-400k | 0.421822 | no |
| opec-2022-06-02-accelerate-648k | 0.418448 | no |
| opec-2022-08-03-sep-100k | 0.418448 | no |
| opec-2022-09-05-oct-minus-100k | 0.418448 | no |
| opec-2022-10-05-cut-2mbd | 0.421822 | no |
| opec-2023-04-02-voluntary-1p16 | 0.421822 | no |
| opec-2023-06-04-2024-levels | 0.421822 | no |
| opec-2023-11-30-voluntary-2p2 | 0.421822 | no |
| opec-2024-03-03-q2-extension | 0.418448 | no |
| opec-2024-06-02-extension-schedule | 0.421822 | no |
| opec-2024-09-05-two-month-delay | 0.418448 | no |
| opec-2024-11-03-one-month-delay | 0.418448 | no |
| opec-2024-12-05-april-start | 0.421822 | no |
| opec-2025-03-03-activation | 0.418448 | no |
| opec-2025-04-03-may-411k | 0.421822 | no |
| opec-2025-05-03-jun-411k | 0.421822 | no |
| opec-2025-06-01-jul-411k | 0.418448 | no |
| opec-2025-07-05-aug-548k | 0.421822 | no |
| opec-2025-08-03-sep-547k | 0.418448 | no |
| opec-2025-09-07-oct-137k | 0.421822 | no |
| opec-2025-10-05-nov-137k | 0.421822 | no |
| opec-2025-11-02-dec-137k-pause | 0.418448 | no |
| opec-2025-11-30-2026-hold | 0.421822 | no |

### OPEC | 20d | spy_relative_ar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.404949 | no |
| opec-2018-12-07-cut-1p2 | 0.404949 | no |
| opec-2019-07-02-extension | 0.404949 | no |
| opec-2019-12-06-deepen-1p7 | 0.399325 | no |
| opec-2020-04-12-cut-9p7 | 0.399325 | no |
| opec-2020-06-06-extension | 0.399325 | no |
| opec-2020-12-03-restoration-start | 0.404949 | no |
| opec-2021-01-05-feb-mar-levels | 0.399325 | no |
| opec-2021-04-01-gradual-return | 0.399325 | no |
| opec-2021-07-18-monthly-400k | 0.399325 | no |
| opec-2022-06-02-accelerate-648k | 0.399325 | no |
| opec-2022-08-03-sep-100k | 0.399325 | no |
| opec-2022-09-05-oct-minus-100k | 0.404949 | no |
| opec-2022-10-05-cut-2mbd | 0.404949 | no |
| opec-2023-04-02-voluntary-1p16 | 0.404949 | no |
| opec-2023-06-04-2024-levels | 0.404949 | no |
| opec-2023-11-30-voluntary-2p2 | 0.404949 | no |
| opec-2024-03-03-q2-extension | 0.399325 | no |
| opec-2024-06-02-extension-schedule | 0.399325 | no |
| opec-2024-09-05-two-month-delay | 0.404949 | no |
| opec-2024-11-03-one-month-delay | 0.399325 | no |
| opec-2024-12-05-april-start | 0.404949 | no |
| opec-2025-03-03-activation | 0.399325 | no |
| opec-2025-04-03-may-411k | 0.399325 | no |
| opec-2025-05-03-jun-411k | 0.404949 | no |
| opec-2025-06-01-jul-411k | 0.404949 | no |
| opec-2025-07-05-aug-548k | 0.404949 | no |
| opec-2025-08-03-sep-547k | 0.404949 | no |
| opec-2025-09-07-oct-137k | 0.404949 | no |
| opec-2025-10-05-nov-137k | 0.399325 | no |
| opec-2025-11-02-dec-137k-pause | 0.399325 | no |
| opec-2025-11-30-2026-hold | 0.399325 | no |

### OPEC | 20d | sector_relative_ar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.460067 | no |
| opec-2018-12-07-cut-1p2 | 0.460067 | no |
| opec-2019-07-02-extension | 0.438695 | no |
| opec-2019-12-06-deepen-1p7 | 0.438695 | no |
| opec-2020-04-12-cut-9p7 | 0.438695 | no |
| opec-2020-06-06-extension | 0.460067 | no |
| opec-2020-12-03-restoration-start | 0.438695 | no |
| opec-2021-01-05-feb-mar-levels | 0.438695 | no |
| opec-2021-04-01-gradual-return | 0.438695 | no |
| opec-2021-07-18-monthly-400k | 0.438695 | no |
| opec-2022-06-02-accelerate-648k | 0.438695 | no |
| opec-2022-08-03-sep-100k | 0.460067 | no |
| opec-2022-09-05-oct-minus-100k | 0.460067 | no |
| opec-2022-10-05-cut-2mbd | 0.438695 | no |
| opec-2023-04-02-voluntary-1p16 | 0.438695 | no |
| opec-2023-06-04-2024-levels | 0.460067 | no |
| opec-2023-11-30-voluntary-2p2 | 0.460067 | no |
| opec-2024-03-03-q2-extension | 0.460067 | no |
| opec-2024-06-02-extension-schedule | 0.460067 | no |
| opec-2024-09-05-two-month-delay | 0.460067 | no |
| opec-2024-11-03-one-month-delay | 0.438695 | no |
| opec-2024-12-05-april-start | 0.438695 | no |
| opec-2025-03-03-activation | 0.460067 | no |
| opec-2025-04-03-may-411k | 0.460067 | no |
| opec-2025-05-03-jun-411k | 0.438695 | no |
| opec-2025-06-01-jul-411k | 0.460067 | no |
| opec-2025-07-05-aug-548k | 0.460067 | no |
| opec-2025-08-03-sep-547k | 0.460067 | no |
| opec-2025-09-07-oct-137k | 0.460067 | no |
| opec-2025-10-05-nov-137k | 0.438695 | no |
| opec-2025-11-02-dec-137k-pause | 0.438695 | no |
| opec-2025-11-30-2026-hold | 0.438695 | no |

### OPEC | 20d | sar

| removed event | leave-event-out MEMP | sign flip |
|---|---|---|
| opec-2018-06-23-conformity-return | 0.384702 | no |
| opec-2018-12-07-cut-1p2 | 0.384702 | no |
| opec-2019-07-02-extension | 0.382452 | no |
| opec-2019-12-06-deepen-1p7 | 0.382452 | no |
| opec-2020-04-12-cut-9p7 | 0.382452 | no |
| opec-2020-06-06-extension | 0.382452 | no |
| opec-2020-12-03-restoration-start | 0.384702 | no |
| opec-2021-01-05-feb-mar-levels | 0.384702 | no |
| opec-2021-04-01-gradual-return | 0.382452 | no |
| opec-2021-07-18-monthly-400k | 0.384702 | no |
| opec-2022-06-02-accelerate-648k | 0.382452 | no |
| opec-2022-08-03-sep-100k | 0.382452 | no |
| opec-2022-09-05-oct-minus-100k | 0.384702 | no |
| opec-2022-10-05-cut-2mbd | 0.384702 | no |
| opec-2023-04-02-voluntary-1p16 | 0.384702 | no |
| opec-2023-06-04-2024-levels | 0.384702 | no |
| opec-2023-11-30-voluntary-2p2 | 0.382452 | no |
| opec-2024-03-03-q2-extension | 0.382452 | no |
| opec-2024-06-02-extension-schedule | 0.382452 | no |
| opec-2024-09-05-two-month-delay | 0.384702 | no |
| opec-2024-11-03-one-month-delay | 0.382452 | no |
| opec-2024-12-05-april-start | 0.384702 | no |
| opec-2025-03-03-activation | 0.382452 | no |
| opec-2025-04-03-may-411k | 0.382452 | no |
| opec-2025-05-03-jun-411k | 0.384702 | no |
| opec-2025-06-01-jul-411k | 0.384702 | no |
| opec-2025-07-05-aug-548k | 0.384702 | no |
| opec-2025-08-03-sep-547k | 0.384702 | no |
| opec-2025-09-07-oct-137k | 0.384702 | no |
| opec-2025-10-05-nov-137k | 0.382452 | no |
| opec-2025-11-02-dec-137k-pause | 0.382452 | no |
| opec-2025-11-30-2026-hold | 0.382452 | no |

## D. F4 cross-metric consistency (per family x horizon)

| family | horizon | raw_return | spy_relative_ar | sector_relative_ar | sar | positive | zero | negative |
|---|---|---|---|---|---|---|---|---|
| FOMC | 1d | +1 | +1 | +1 | +1 | 4 | 0 | 0 |
| FOMC | 5d | +1 | +1 | -1 | +1 | 3 | 0 | 1 |
| OPEC | 1d | +1 | +1 | -1 | +1 | 3 | 0 | 1 |
| OPEC | 5d | -1 | +1 | -1 | +1 | 2 | 0 | 2 |
| OPEC | 20d | -1 | -1 | -1 | -1 | 0 | 0 | 4 |

Signs are `sign(MEMP - 0.5)` per metric (`+1` above 0.5, `-1` below, `0` exactly at 0.5). The counts describe agreement among the four metrics; they are not a mechanism claim.

## E. F5 cross-horizon consistency (per family x metric)

| family | metric | 1d | 5d | 20d | horizons agree on sign |
|---|---|---|---|---|---|
| FOMC | raw_return | +1 | +1 | n/a | yes |
| FOMC | spy_relative_ar | +1 | +1 | n/a | yes |
| FOMC | sector_relative_ar | +1 | -1 | n/a | no |
| FOMC | sar | +1 | +1 | n/a | yes |
| OPEC | raw_return | +1 | -1 | -1 | no |
| OPEC | spy_relative_ar | +1 | +1 | -1 | no |
| OPEC | sector_relative_ar | -1 | -1 | -1 | yes |
| OPEC | sar | +1 | +1 | -1 | no |

`n/a` marks an infeasible horizon (FOMC has no 20d primary cell). Agreement requires one shared non-zero sign across every feasible horizon.

## Boundary

The six falsifiers stand separately; they are not averaged, scored, graded, or combined into any index. This slice states mechanical stability facts only. The overall Mission-I interpretation is deferred to the closeout task.

