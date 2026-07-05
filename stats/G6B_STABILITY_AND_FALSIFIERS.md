# G6B stability diagnostics and falsifier pass (Mission G, g0-v1)

Version: `g6b-stability-falsifiers-v1`.

## 1. Contract

- POST-READOUT descriptive robustness analysis over the complete frozen G6A surface. It was NOT pre-specified before outcomes were visible (G6A froze the comparisons; this slice was designed after the raw surface existed) and is therefore itself descriptive diagnostics, not part of any closed inferential pool.
- Uniformly applied: the SAME diagnostics run on every one of the 120 continuous entry x metric x horizon associations (10 continuous manifest entries x 4 metrics x 3 horizons - equivalently 40 entry x metric panels of 3 horizons each) and on every one of the 14 frozen categorical cells. No selected subset, no ranking, no weighted score, no 'best pattern' rule.
- Terminology check (task section 1): the tracked G6A report was verified and does not contain an erroneous 40-combination count; the correct continuous surface size, stated here, is 120 associations.
- Influence runs REPORT; they never remove an event from the main result. Surviving a diagnostic is not validation, and no binary robust/fragile threshold is invented.
- No p-value, no confidence interval, no significance claim, no pooled FOMC + OPEC statistic anywhere.
- G6A remains the authoritative raw readout; universe, manifest, axes, tags, metrics, horizons, tickers, denominators, and the support floor (11) are unchanged and re-reconciled fail-loud before this report renders (frame 65 / designed 32 / total 97; basis split 97/0/0).

## 2. Continuous stability board (all 120 associations)

Columns: full-sample Spearman rho; leave-one-event-out (LOEO) min / max / opposite-sign runs / max |change|; leave-one-year-out (LOYO) min / max / opposite-sign runs / minimum retained N over the years tested.

| lane | axis | metric | h | N | uniq | rho | LOEO min | LOEO max | LOEO opp | LOEO max abs ch | LOYO min | LOYO max | LOYO opp | LOYO min N |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| designed_contrast | `credit_hy_oas` (sec) | absolute_asset_return | 1d | 16 | 16 | -0.0427 | -0.2198 | +0.1055 | 5 | +0.1772 | -0.2198 | +0.2571 | 2 | 6 |
| designed_contrast | `credit_hy_oas` (sec) | absolute_asset_return | 5d | 16 | 16 | -0.0854 | -0.2466 | +0.0590 | 3 | +0.1613 | -0.6000 | +0.0590 | 2 | 6 |
| designed_contrast | `credit_hy_oas` (sec) | absolute_asset_return | 20d | 16 | 16 | +0.1781 | +0.0500 | +0.2824 | 0 | +0.1280 | +0.0592 | +0.2288 | 0 | 6 |
| designed_contrast | `credit_hy_oas` (sec) | sar | 1d | 16 | 16 | -0.1177 | -0.2788 | +0.0214 | 1 | +0.1611 | -0.1913 | +0.3143 | 1 | 6 |
| designed_contrast | `credit_hy_oas` (sec) | sar | 5d | 16 | 16 | -0.3194 | -0.4987 | -0.2020 | 0 | +0.1793 | -0.4286 | -0.2020 | 0 | 6 |
| designed_contrast | `credit_hy_oas` (sec) | sar | 20d | 16 | 16 | -0.0780 | -0.1821 | +0.0590 | 3 | +0.1370 | -0.1868 | +0.0214 | 1 | 6 |
| designed_contrast | `credit_hy_oas` (sec) | sector_relative_ar | 1d | 16 | 16 | -0.0618 | -0.2431 | +0.0643 | 2 | +0.1813 | -0.1769 | +0.4857 | 1 | 6 |
| designed_contrast | `credit_hy_oas` (sec) | sector_relative_ar | 5d | 16 | 16 | -0.0486 | -0.2270 | +0.1055 | 4 | +0.1784 | -0.8286 | +0.2232 | 2 | 6 |
| designed_contrast | `credit_hy_oas` (sec) | sector_relative_ar | 20d | 16 | 16 | +0.1545 | +0.0089 | +0.3271 | 0 | +0.1726 | -0.5429 | +0.4556 | 1 | 6 |
| designed_contrast | `credit_hy_oas` (sec) | spy_relative_ar | 1d | 16 | 16 | -0.1060 | -0.2645 | +0.0393 | 1 | +0.1586 | -0.1913 | +0.3143 | 1 | 6 |
| designed_contrast | `credit_hy_oas` (sec) | spy_relative_ar | 5d | 16 | 16 | -0.2899 | -0.5165 | -0.1448 | 0 | +0.2266 | -0.6000 | -0.1448 | 0 | 6 |
| designed_contrast | `credit_hy_oas` (sec) | spy_relative_ar | 20d | 16 | 16 | -0.1074 | -0.2179 | +0.0375 | 1 | +0.1450 | -0.1868 | -0.0143 | 0 | 6 |
| designed_contrast | `curve_2s10s` | absolute_asset_return | 1d | 32 | 32 | +0.1115 | +0.0476 | +0.2162 | 0 | +0.1047 | -0.0537 | +0.2676 | 1 | 22 |
| designed_contrast | `curve_2s10s` | absolute_asset_return | 5d | 32 | 32 | +0.0770 | +0.0044 | +0.1767 | 0 | +0.0997 | +0.0171 | +0.1764 | 0 | 22 |
| designed_contrast | `curve_2s10s` | absolute_asset_return | 20d | 32 | 32 | -0.1419 | -0.2186 | -0.0637 | 0 | +0.0782 | -0.1840 | -0.0800 | 0 | 22 |
| designed_contrast | `curve_2s10s` | sar | 1d | 32 | 32 | +0.1188 | +0.0557 | +0.2138 | 0 | +0.0950 | -0.0261 | +0.2607 | 1 | 22 |
| designed_contrast | `curve_2s10s` | sar | 5d | 32 | 32 | +0.1034 | +0.0343 | +0.1884 | 0 | +0.0850 | +0.0238 | +0.1690 | 0 | 22 |
| designed_contrast | `curve_2s10s` | sar | 20d | 32 | 32 | -0.1973 | -0.2812 | -0.1444 | 0 | +0.0839 | -0.2829 | -0.1513 | 0 | 22 |
| designed_contrast | `curve_2s10s` | sector_relative_ar | 1d | 32 | 32 | +0.2457 | +0.1932 | +0.3703 | 0 | +0.1246 | +0.0981 | +0.3859 | 0 | 22 |
| designed_contrast | `curve_2s10s` | sector_relative_ar | 5d | 32 | 32 | +0.2138 | +0.1549 | +0.3267 | 0 | +0.1130 | +0.0493 | +0.3687 | 0 | 22 |
| designed_contrast | `curve_2s10s` | sector_relative_ar | 20d | 32 | 32 | +0.0396 | -0.0387 | +0.1162 | 4 | +0.0783 | -0.0498 | +0.1311 | 2 | 22 |
| designed_contrast | `curve_2s10s` | spy_relative_ar | 1d | 32 | 32 | +0.1258 | +0.0629 | +0.2384 | 0 | +0.1126 | -0.0340 | +0.2725 | 1 | 22 |
| designed_contrast | `curve_2s10s` | spy_relative_ar | 5d | 32 | 32 | +0.0491 | -0.0246 | +0.1541 | 2 | +0.1050 | -0.0324 | +0.1207 | 1 | 22 |
| designed_contrast | `curve_2s10s` | spy_relative_ar | 20d | 32 | 32 | -0.2200 | -0.2840 | -0.1497 | 0 | +0.0704 | -0.2937 | -0.1621 | 0 | 22 |
| designed_contrast | `fed_policy_path` | absolute_asset_return | 1d | 32 | 32 | -0.1433 | -0.2254 | -0.0587 | 0 | +0.0845 | -0.2464 | -0.0202 | 0 | 22 |
| designed_contrast | `fed_policy_path` | absolute_asset_return | 5d | 32 | 32 | +0.0713 | -0.0136 | +0.1270 | 1 | +0.0849 | +0.0089 | +0.1105 | 0 | 22 |
| designed_contrast | `fed_policy_path` | absolute_asset_return | 20d | 32 | 32 | -0.2087 | -0.3095 | -0.1276 | 0 | +0.1008 | -0.2386 | -0.1473 | 0 | 22 |
| designed_contrast | `fed_policy_path` | sar | 1d | 32 | 32 | -0.1511 | -0.2382 | -0.0686 | 0 | +0.0870 | -0.2861 | -0.0416 | 0 | 22 |
| designed_contrast | `fed_policy_path` | sar | 5d | 32 | 32 | +0.0253 | -0.0440 | +0.0690 | 7 | +0.0694 | -0.0544 | +0.1534 | 3 | 22 |
| designed_contrast | `fed_policy_path` | sar | 20d | 32 | 32 | -0.1264 | -0.2078 | -0.0500 | 0 | +0.0814 | -0.2136 | -0.0659 | 0 | 22 |
| designed_contrast | `fed_policy_path` | sector_relative_ar | 1d | 32 | 32 | -0.4564 | -0.5288 | -0.4015 | 0 | +0.0723 | -0.5183 | -0.3668 | 0 | 22 |
| designed_contrast | `fed_policy_path` | sector_relative_ar | 5d | 32 | 32 | -0.2929 | -0.3838 | -0.2378 | 0 | +0.0908 | -0.4754 | -0.1859 | 0 | 22 |
| designed_contrast | `fed_policy_path` | sector_relative_ar | 20d | 32 | 32 | -0.3824 | -0.4445 | -0.3190 | 0 | +0.0633 | -0.4569 | -0.3104 | 0 | 22 |
| designed_contrast | `fed_policy_path` | spy_relative_ar | 1d | 32 | 32 | -0.1973 | -0.2928 | -0.1179 | 0 | +0.0955 | -0.3201 | -0.0850 | 0 | 22 |
| designed_contrast | `fed_policy_path` | spy_relative_ar | 5d | 32 | 32 | +0.0647 | -0.0027 | +0.1073 | 1 | +0.0674 | -0.0326 | +0.1760 | 2 | 22 |
| designed_contrast | `fed_policy_path` | spy_relative_ar | 20d | 32 | 32 | -0.0941 | -0.1935 | -0.0012 | 0 | +0.0994 | -0.2105 | -0.0364 | 0 | 22 |
| designed_contrast | `spy_trend_ma200` | absolute_asset_return | 1d | 32 | 32 | +0.0367 | -0.0524 | +0.0992 | 5 | +0.0891 | -0.0593 | +0.1197 | 2 | 22 |
| designed_contrast | `spy_trend_ma200` | absolute_asset_return | 5d | 32 | 32 | +0.0663 | -0.0270 | +0.1254 | 2 | +0.0934 | -0.0271 | +0.1465 | 1 | 22 |
| designed_contrast | `spy_trend_ma200` | absolute_asset_return | 20d | 32 | 32 | +0.0759 | -0.0081 | +0.1544 | 1 | +0.0839 | -0.0088 | +0.1542 | 1 | 22 |
| designed_contrast | `spy_trend_ma200` | sar | 1d | 32 | 32 | -0.0392 | -0.1278 | +0.0270 | 4 | +0.0886 | -0.1903 | +0.0665 | 2 | 22 |
| designed_contrast | `spy_trend_ma200` | sar | 5d | 32 | 32 | +0.0674 | -0.0258 | +0.1496 | 3 | +0.0933 | -0.0291 | +0.1828 | 1 | 22 |
| designed_contrast | `spy_trend_ma200` | sar | 20d | 32 | 32 | -0.0088 | -0.0940 | +0.0492 | 12 | +0.0852 | -0.0775 | +0.0480 | 3 | 22 |
| designed_contrast | `spy_trend_ma200` | sector_relative_ar | 1d | 32 | 32 | +0.1741 | +0.0988 | +0.2524 | 0 | +0.0783 | +0.0471 | +0.2363 | 0 | 22 |
| designed_contrast | `spy_trend_ma200` | sector_relative_ar | 5d | 32 | 32 | +0.0968 | +0.0065 | +0.1617 | 0 | +0.0903 | +0.0340 | +0.2230 | 0 | 22 |
| designed_contrast | `spy_trend_ma200` | sector_relative_ar | 20d | 32 | 32 | +0.1371 | +0.0516 | +0.2177 | 0 | +0.0855 | -0.0608 | +0.3235 | 1 | 22 |
| designed_contrast | `spy_trend_ma200` | spy_relative_ar | 1d | 32 | 32 | +0.0191 | -0.0718 | +0.0859 | 8 | +0.0908 | -0.0774 | +0.0928 | 2 | 22 |
| designed_contrast | `spy_trend_ma200` | spy_relative_ar | 5d | 32 | 32 | +0.0282 | -0.0690 | +0.0968 | 6 | +0.0972 | -0.0773 | +0.1385 | 2 | 22 |
| designed_contrast | `spy_trend_ma200` | spy_relative_ar | 20d | 32 | 32 | -0.0436 | -0.1278 | +0.0306 | 2 | +0.0842 | -0.1258 | +0.0016 | 1 | 22 |
| designed_contrast | `vix_level_percentile` | absolute_asset_return | 1d | 32 | 32 | +0.0477 | -0.0323 | +0.1287 | 3 | +0.0810 | -0.0746 | +0.1745 | 3 | 22 |
| designed_contrast | `vix_level_percentile` | absolute_asset_return | 5d | 32 | 32 | -0.0654 | -0.1474 | +0.0058 | 1 | +0.0820 | -0.2119 | +0.0096 | 1 | 22 |
| designed_contrast | `vix_level_percentile` | absolute_asset_return | 20d | 32 | 32 | +0.1980 | +0.1214 | +0.2626 | 0 | +0.0766 | +0.1197 | +0.2733 | 0 | 22 |
| designed_contrast | `vix_level_percentile` | sar | 1d | 32 | 32 | +0.1520 | +0.0835 | +0.2414 | 0 | +0.0894 | -0.0177 | +0.2931 | 1 | 22 |
| designed_contrast | `vix_level_percentile` | sar | 5d | 32 | 32 | +0.0400 | -0.0248 | +0.1258 | 4 | +0.0859 | -0.0476 | +0.1293 | 2 | 22 |
| designed_contrast | `vix_level_percentile` | sar | 20d | 32 | 32 | +0.2508 | +0.2029 | +0.3345 | 0 | +0.0838 | +0.1762 | +0.2962 | 0 | 22 |
| designed_contrast | `vix_level_percentile` | sector_relative_ar | 1d | 32 | 32 | +0.1045 | +0.0165 | +0.1791 | 0 | +0.0880 | -0.0081 | +0.2016 | 1 | 22 |
| designed_contrast | `vix_level_percentile` | sector_relative_ar | 5d | 32 | 32 | +0.0554 | -0.0198 | +0.1343 | 4 | +0.0789 | -0.0320 | +0.1502 | 3 | 22 |
| designed_contrast | `vix_level_percentile` | sector_relative_ar | 20d | 32 | 32 | +0.1802 | +0.1059 | +0.2396 | 0 | +0.0743 | +0.1078 | +0.3309 | 0 | 22 |
| designed_contrast | `vix_level_percentile` | spy_relative_ar | 1d | 32 | 32 | +0.1379 | +0.0548 | +0.2150 | 0 | +0.0830 | +0.0186 | +0.2434 | 0 | 22 |
| designed_contrast | `vix_level_percentile` | spy_relative_ar | 5d | 32 | 32 | +0.0379 | -0.0502 | +0.1139 | 4 | +0.0882 | -0.0710 | +0.1276 | 2 | 22 |
| designed_contrast | `vix_level_percentile` | spy_relative_ar | 20d | 32 | 32 | +0.2376 | +0.1686 | +0.3154 | 0 | +0.0778 | +0.1710 | +0.2824 | 0 | 22 |
| frame_complete_historical | `credit_hy_oas` (sec) | absolute_asset_return | 1d | 20 | 20 | +0.0369 | -0.1238 | +0.1527 | 4 | +0.1607 | -0.0385 | +0.1228 | 2 | 12 |
| frame_complete_historical | `credit_hy_oas` (sec) | absolute_asset_return | 5d | 20 | 20 | -0.1640 | -0.3301 | -0.0869 | 0 | +0.1661 | -0.2000 | -0.0420 | 0 | 12 |
| frame_complete_historical | `credit_hy_oas` (sec) | absolute_asset_return | 20d | 20 | 20 | -0.1053 | -0.2897 | -0.0044 | 0 | +0.1844 | -0.1754 | +0.1016 | 1 | 12 |
| frame_complete_historical | `credit_hy_oas` (sec) | sar | 1d | 20 | 20 | +0.0971 | -0.0536 | +0.1835 | 2 | +0.1506 | -0.1501 | +0.3158 | 1 | 12 |
| frame_complete_historical | `credit_hy_oas` (sec) | sar | 5d | 20 | 20 | -0.1016 | -0.2133 | -0.0167 | 0 | +0.1118 | -0.2384 | +0.0386 | 1 | 12 |
| frame_complete_historical | `credit_hy_oas` (sec) | sar | 20d | 20 | 20 | -0.2641 | -0.4135 | -0.2046 | 0 | +0.1494 | -0.3576 | -0.0771 | 0 | 12 |
| frame_complete_historical | `credit_hy_oas` (sec) | sector_relative_ar | 1d | 20 | 20 | +0.2212 | +0.0966 | +0.3284 | 0 | +0.1246 | -0.0765 | +0.3018 | 1 | 12 |
| frame_complete_historical | `credit_hy_oas` (sec) | sector_relative_ar | 5d | 20 | 20 | +0.1272 | +0.0097 | +0.1923 | 0 | +0.1175 | -0.1707 | +0.2837 | 1 | 12 |
| frame_complete_historical | `credit_hy_oas` (sec) | sector_relative_ar | 20d | 20 | 20 | -0.1392 | -0.2397 | -0.0404 | 0 | +0.1005 | -0.1634 | +0.0526 | 1 | 12 |
| frame_complete_historical | `credit_hy_oas` (sec) | spy_relative_ar | 1d | 20 | 20 | +0.0647 | -0.0860 | +0.1720 | 3 | +0.1508 | -0.1163 | +0.2281 | 1 | 12 |
| frame_complete_historical | `credit_hy_oas` (sec) | spy_relative_ar | 5d | 20 | 20 | -0.1535 | -0.2493 | -0.0825 | 0 | +0.0958 | -0.2987 | -0.0035 | 0 | 12 |
| frame_complete_historical | `credit_hy_oas` (sec) | spy_relative_ar | 20d | 20 | 20 | -0.2746 | -0.3977 | -0.1948 | 0 | +0.1231 | -0.3164 | -0.0877 | 0 | 12 |
| frame_complete_historical | `curve_2s10s` | absolute_asset_return | 1d | 65 | 65 | +0.0572 | +0.0223 | +0.0992 | 0 | +0.0421 | -0.0150 | +0.1570 | 1 | 56 |
| frame_complete_historical | `curve_2s10s` | absolute_asset_return | 5d | 65 | 65 | +0.0349 | -0.0045 | +0.0745 | 1 | +0.0396 | -0.0261 | +0.0950 | 1 | 56 |
| frame_complete_historical | `curve_2s10s` | absolute_asset_return | 20d | 65 | 65 | +0.0522 | +0.0162 | +0.0867 | 0 | +0.0360 | -0.0182 | +0.1136 | 2 | 56 |
| frame_complete_historical | `curve_2s10s` | sar | 1d | 65 | 65 | +0.0547 | +0.0215 | +0.1006 | 0 | +0.0459 | -0.0224 | +0.1403 | 1 | 56 |
| frame_complete_historical | `curve_2s10s` | sar | 5d | 65 | 65 | +0.0519 | +0.0135 | +0.0938 | 0 | +0.0418 | -0.0207 | +0.0945 | 1 | 56 |
| frame_complete_historical | `curve_2s10s` | sar | 20d | 65 | 65 | +0.0546 | +0.0170 | +0.0969 | 0 | +0.0423 | -0.0151 | +0.0905 | 2 | 56 |
| frame_complete_historical | `curve_2s10s` | sector_relative_ar | 1d | 65 | 65 | -0.0566 | -0.0966 | -0.0184 | 0 | +0.0400 | -0.1035 | +0.0244 | 1 | 56 |
| frame_complete_historical | `curve_2s10s` | sector_relative_ar | 5d | 65 | 65 | +0.0190 | -0.0238 | +0.0562 | 10 | +0.0428 | -0.0576 | +0.0597 | 3 | 56 |
| frame_complete_historical | `curve_2s10s` | sector_relative_ar | 20d | 65 | 65 | +0.1366 | +0.1044 | +0.1825 | 0 | +0.0459 | +0.1045 | +0.1690 | 0 | 56 |
| frame_complete_historical | `curve_2s10s` | spy_relative_ar | 1d | 65 | 65 | +0.0439 | +0.0060 | +0.0891 | 0 | +0.0451 | -0.0322 | +0.1456 | 2 | 56 |
| frame_complete_historical | `curve_2s10s` | spy_relative_ar | 5d | 65 | 65 | +0.0871 | +0.0499 | +0.1275 | 0 | +0.0404 | +0.0076 | +0.1443 | 0 | 56 |
| frame_complete_historical | `curve_2s10s` | spy_relative_ar | 20d | 65 | 65 | +0.0792 | +0.0436 | +0.1273 | 0 | +0.0481 | +0.0132 | +0.1231 | 0 | 56 |
| frame_complete_historical | `fed_policy_path` | absolute_asset_return | 1d | 65 | 65 | -0.0506 | -0.1010 | -0.0196 | 0 | +0.0504 | -0.2168 | +0.0505 | 2 | 56 |
| frame_complete_historical | `fed_policy_path` | absolute_asset_return | 5d | 65 | 65 | -0.0740 | -0.1257 | -0.0458 | 0 | +0.0517 | -0.2679 | +0.0525 | 1 | 56 |
| frame_complete_historical | `fed_policy_path` | absolute_asset_return | 20d | 65 | 65 | +0.0984 | +0.0568 | +0.1279 | 0 | +0.0416 | -0.0495 | +0.1573 | 1 | 56 |
| frame_complete_historical | `fed_policy_path` | sar | 1d | 65 | 65 | +0.0039 | -0.0347 | +0.0419 | 24 | +0.0386 | -0.1113 | +0.0925 | 3 | 56 |
| frame_complete_historical | `fed_policy_path` | sar | 5d | 65 | 65 | -0.0339 | -0.0786 | -0.0014 | 0 | +0.0447 | -0.1592 | +0.1102 | 2 | 56 |
| frame_complete_historical | `fed_policy_path` | sar | 20d | 65 | 65 | +0.0790 | +0.0462 | +0.1207 | 0 | +0.0416 | -0.0450 | +0.1564 | 1 | 56 |
| frame_complete_historical | `fed_policy_path` | sector_relative_ar | 1d | 65 | 65 | +0.1647 | +0.1299 | +0.2098 | 0 | +0.0451 | +0.1013 | +0.2199 | 0 | 56 |
| frame_complete_historical | `fed_policy_path` | sector_relative_ar | 5d | 65 | 65 | +0.0537 | +0.0147 | +0.0902 | 0 | +0.0390 | -0.0068 | +0.1298 | 1 | 56 |
| frame_complete_historical | `fed_policy_path` | sector_relative_ar | 20d | 65 | 65 | +0.1269 | +0.0861 | +0.1680 | 0 | +0.0412 | +0.0072 | +0.2254 | 0 | 56 |
| frame_complete_historical | `fed_policy_path` | spy_relative_ar | 1d | 65 | 65 | +0.0612 | +0.0212 | +0.1011 | 0 | +0.0400 | -0.1170 | +0.1602 | 1 | 56 |
| frame_complete_historical | `fed_policy_path` | spy_relative_ar | 5d | 65 | 65 | -0.0253 | -0.0748 | +0.0030 | 3 | +0.0495 | -0.1970 | +0.1167 | 2 | 56 |
| frame_complete_historical | `fed_policy_path` | spy_relative_ar | 20d | 65 | 65 | +0.1145 | +0.0726 | +0.1456 | 0 | +0.0419 | -0.0641 | +0.1740 | 1 | 56 |
| frame_complete_historical | `spy_trend_ma200` | absolute_asset_return | 1d | 65 | 65 | +0.2465 | +0.2110 | +0.2875 | 0 | +0.0410 | +0.1213 | +0.2987 | 0 | 56 |
| frame_complete_historical | `spy_trend_ma200` | absolute_asset_return | 5d | 65 | 65 | +0.0519 | +0.0077 | +0.0827 | 0 | +0.0441 | -0.0920 | +0.1252 | 2 | 56 |
| frame_complete_historical | `spy_trend_ma200` | absolute_asset_return | 20d | 65 | 65 | +0.0616 | +0.0178 | +0.1011 | 0 | +0.0438 | -0.0558 | +0.1269 | 1 | 56 |
| frame_complete_historical | `spy_trend_ma200` | sar | 1d | 65 | 65 | +0.1631 | +0.1329 | +0.2049 | 0 | +0.0418 | +0.0945 | +0.2221 | 0 | 56 |
| frame_complete_historical | `spy_trend_ma200` | sar | 5d | 65 | 65 | +0.1092 | +0.0792 | +0.1450 | 0 | +0.0358 | -0.0043 | +0.1882 | 1 | 56 |
| frame_complete_historical | `spy_trend_ma200` | sar | 20d | 65 | 65 | +0.1502 | +0.1163 | +0.1960 | 0 | +0.0458 | +0.0441 | +0.1957 | 0 | 56 |
| frame_complete_historical | `spy_trend_ma200` | sector_relative_ar | 1d | 65 | 65 | -0.0177 | -0.0505 | +0.0128 | 7 | +0.0328 | -0.1117 | +0.0421 | 3 | 56 |
| frame_complete_historical | `spy_trend_ma200` | sector_relative_ar | 5d | 65 | 65 | -0.0418 | -0.0767 | -0.0092 | 0 | +0.0349 | -0.1758 | +0.0478 | 2 | 56 |
| frame_complete_historical | `spy_trend_ma200` | sector_relative_ar | 20d | 65 | 65 | +0.0111 | -0.0322 | +0.0447 | 15 | +0.0433 | -0.1428 | +0.0565 | 2 | 56 |
| frame_complete_historical | `spy_trend_ma200` | spy_relative_ar | 1d | 65 | 65 | +0.1549 | +0.1245 | +0.1962 | 0 | +0.0413 | +0.1173 | +0.2112 | 0 | 56 |
| frame_complete_historical | `spy_trend_ma200` | spy_relative_ar | 5d | 65 | 65 | +0.1373 | +0.1041 | +0.1747 | 0 | +0.0374 | +0.0312 | +0.1910 | 0 | 56 |
| frame_complete_historical | `spy_trend_ma200` | spy_relative_ar | 20d | 65 | 65 | +0.1487 | +0.1083 | +0.1896 | 0 | +0.0409 | +0.0176 | +0.2077 | 0 | 56 |
| frame_complete_historical | `vix_level_percentile` | absolute_asset_return | 1d | 65 | 65 | -0.0670 | -0.1057 | -0.0226 | 0 | +0.0444 | -0.1228 | +0.0267 | 2 | 56 |
| frame_complete_historical | `vix_level_percentile` | absolute_asset_return | 5d | 65 | 65 | -0.0302 | -0.0628 | +0.0160 | 6 | +0.0462 | -0.1294 | +0.1168 | 2 | 56 |
| frame_complete_historical | `vix_level_percentile` | absolute_asset_return | 20d | 65 | 65 | -0.0675 | -0.1078 | -0.0242 | 0 | +0.0433 | -0.1575 | +0.0763 | 1 | 56 |
| frame_complete_historical | `vix_level_percentile` | sar | 1d | 65 | 65 | -0.0097 | -0.0460 | +0.0345 | 14 | +0.0442 | -0.0637 | +0.0964 | 3 | 56 |
| frame_complete_historical | `vix_level_percentile` | sar | 5d | 65 | 65 | -0.0427 | -0.0811 | +0.0023 | 1 | +0.0450 | -0.1273 | +0.1044 | 2 | 56 |
| frame_complete_historical | `vix_level_percentile` | sar | 20d | 65 | 65 | -0.0463 | -0.0879 | -0.0019 | 0 | +0.0444 | -0.1478 | +0.0807 | 1 | 56 |
| frame_complete_historical | `vix_level_percentile` | sector_relative_ar | 1d | 65 | 65 | +0.0066 | -0.0337 | +0.0539 | 19 | +0.0474 | -0.0764 | +0.1113 | 5 | 56 |
| frame_complete_historical | `vix_level_percentile` | sector_relative_ar | 5d | 65 | 65 | +0.0323 | -0.0054 | +0.0775 | 3 | +0.0451 | -0.0611 | +0.1696 | 3 | 56 |
| frame_complete_historical | `vix_level_percentile` | sector_relative_ar | 20d | 65 | 65 | +0.1084 | +0.0753 | +0.1596 | 0 | +0.0512 | +0.0168 | +0.2702 | 0 | 56 |
| frame_complete_historical | `vix_level_percentile` | spy_relative_ar | 1d | 65 | 65 | -0.0170 | -0.0577 | +0.0297 | 10 | +0.0467 | -0.0694 | +0.0902 | 3 | 56 |
| frame_complete_historical | `vix_level_percentile` | spy_relative_ar | 5d | 65 | 65 | -0.0236 | -0.0608 | +0.0221 | 6 | +0.0457 | -0.0895 | +0.1085 | 2 | 56 |
| frame_complete_historical | `vix_level_percentile` | spy_relative_ar | 20d | 65 | 65 | -0.0230 | -0.0634 | +0.0225 | 4 | +0.0454 | -0.1112 | +0.1317 | 3 | 56 |

## 3. Calendar-time confound board

Spearman rho between the pre-event STATE value and the event-date ordinal, per lane x axis. A structural diagnostic only - it contains no outcome value and nothing is residualized or 'corrected' here. A large |rho| means the axis tracks calendar time within that lane and any conditional pattern on it could proxy temporal drift.

| lane | axis | N | rho(state, date) |
|---|---|---|---|
| designed_contrast | `credit_hy_oas` | 16 | -0.4489 |
| designed_contrast | `curve_2s10s` | 32 | +0.0521 |
| designed_contrast | `fed_policy_path` | 32 | -0.2708 |
| designed_contrast | `spy_trend_ma200` | 32 | +0.2100 |
| designed_contrast | `vix_level_percentile` | 32 | -0.0126 |
| frame_complete_historical | `credit_hy_oas` | 20 | -0.7254 |
| frame_complete_historical | `curve_2s10s` | 65 | -0.2550 |
| frame_complete_historical | `fed_policy_path` | 65 | -0.1414 |
| frame_complete_historical | `spy_trend_ma200` | 65 | +0.2096 |
| frame_complete_historical | `vix_level_percentile` | 65 | -0.1553 |

## 4. Categorical fragility board (all 14 frozen cells)

Medians under leave-one-event-out and (where the cell spans more than one calendar year) leave-one-year-out. Insufficient cells stay fully visible; none is merged or hidden.

### designed_contrast / `curve_2s10s` = `inverted` - N 9, unique dates 9, support `insufficient_n`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | -0.0140 | -0.0144 | -0.0121 | -0.0152 | -0.0030 | 6 |
| absolute_asset_return | 5d | +0.0058 | -0.0061 | +0.0104 | -0.0121 | +0.0173 | 6 |
| absolute_asset_return | 20d | +0.0484 | +0.0240 | +0.0484 | +0.0240 | +0.0607 | 6 |
| spy_relative_ar | 1d | -0.0091 | -0.0100 | -0.0040 | -0.0100 | -0.0040 | 6 |
| spy_relative_ar | 5d | +0.0016 | -0.0132 | +0.0048 | -0.0196 | +0.0123 | 6 |
| spy_relative_ar | 20d | +0.0075 | +0.0046 | +0.0221 | -0.0091 | +0.0455 | 6 |
| sector_relative_ar | 1d | -0.0031 | -0.0032 | -0.0029 | -0.0044 | -0.0011 | 6 |
| sector_relative_ar | 5d | -0.0069 | -0.0069 | -0.0065 | -0.0069 | -0.0018 | 6 |
| sector_relative_ar | 20d | -0.0011 | -0.0113 | +0.0003 | -0.0114 | +0.0003 | 6 |
| sar | 1d | -0.3623 | -0.5116 | -0.1358 | -0.5116 | -0.1160 | 6 |
| sar | 5d | +0.0249 | -0.1949 | +0.1415 | -0.6676 | +0.3063 | 6 |
| sar | 20d | +0.0952 | +0.0539 | +0.2850 | -0.1083 | +0.5476 | 6 |

### designed_contrast / `curve_2s10s` = `non_inverted` - N 23, unique dates 23, support `sufficient_structure`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | +0.0032 | +0.0004 | +0.0049 | -0.0040 | +0.0066 | 13 |
| absolute_asset_return | 5d | +0.0199 | +0.0155 | +0.0203 | +0.0110 | +0.0207 | 13 |
| absolute_asset_return | 20d | -0.0068 | -0.0138 | +0.0138 | -0.0207 | +0.0344 | 13 |
| spy_relative_ar | 1d | +0.0036 | +0.0000 | +0.0042 | -0.0067 | +0.0097 | 13 |
| spy_relative_ar | 5d | +0.0142 | +0.0141 | +0.0154 | +0.0140 | +0.0154 | 13 |
| spy_relative_ar | 20d | -0.0054 | -0.0160 | -0.0039 | -0.0267 | -0.0024 | 13 |
| sector_relative_ar | 1d | +0.0000 | -0.0007 | +0.0004 | -0.0013 | +0.0007 | 13 |
| sector_relative_ar | 5d | +0.0050 | +0.0048 | +0.0055 | +0.0033 | +0.0151 | 13 |
| sector_relative_ar | 20d | +0.0080 | +0.0045 | +0.0087 | +0.0010 | +0.0095 | 13 |
| sar | 1d | +0.2462 | +0.0166 | +0.2859 | -0.3966 | +0.3481 | 13 |
| sar | 5d | +0.3529 | +0.3422 | +0.3621 | +0.3315 | +0.3713 | 13 |
| sar | 20d | -0.0784 | -0.2314 | -0.0566 | -0.3844 | -0.0347 | 13 |

### designed_contrast / `fed_policy_path` = `easing` - N 12, unique dates 12, support `sufficient_structure`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | +0.0069 | +0.0066 | +0.0072 | +0.0066 | +0.0096 | 5 |
| absolute_asset_return | 5d | +0.0203 | +0.0199 | +0.0207 | +0.0199 | +0.0207 | 5 |
| absolute_asset_return | 20d | +0.0559 | +0.0537 | +0.0582 | +0.0537 | +0.1120 | 5 |
| spy_relative_ar | 1d | +0.0069 | +0.0062 | +0.0075 | +0.0055 | +0.0188 | 5 |
| spy_relative_ar | 5d | +0.0154 | +0.0142 | +0.0166 | -0.0096 | +0.0169 | 5 |
| spy_relative_ar | 20d | +0.0073 | +0.0068 | +0.0079 | +0.0068 | +0.0550 | 5 |
| sector_relative_ar | 1d | +0.0019 | +0.0015 | +0.0023 | +0.0011 | +0.0078 | 5 |
| sector_relative_ar | 5d | +0.0114 | +0.0077 | +0.0151 | +0.0063 | +0.0179 | 5 |
| sector_relative_ar | 20d | +0.0230 | +0.0171 | +0.0289 | +0.0133 | +0.0383 | 5 |
| sar | 1d | +0.3817 | +0.3481 | +0.4153 | +0.3481 | +0.4201 | 5 |
| sar | 5d | +0.3514 | +0.3315 | +0.3713 | -0.0798 | +0.4293 | 5 |
| sar | 20d | +0.0927 | +0.0888 | +0.0967 | +0.0888 | +0.8481 | 5 |

### designed_contrast / `fed_policy_path` = `hold` - N 11, unique dates 11, support `sufficient_structure`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | -0.0102 | -0.0106 | -0.0088 | -0.0129 | -0.0048 | 8 |
| absolute_asset_return | 5d | +0.0038 | +0.0010 | +0.0048 | +0.0010 | +0.0126 | 8 |
| absolute_asset_return | 20d | +0.0344 | +0.0045 | +0.0446 | +0.0045 | +0.0446 | 8 |
| spy_relative_ar | 1d | -0.0098 | -0.0100 | -0.0095 | -0.0100 | -0.0095 | 8 |
| spy_relative_ar | 5d | -0.0119 | -0.0168 | -0.0020 | -0.0168 | +0.0010 | 8 |
| spy_relative_ar | 20d | -0.0024 | -0.0195 | +0.0171 | -0.0195 | +0.0171 | 8 |
| sector_relative_ar | 1d | -0.0026 | -0.0029 | -0.0020 | -0.0032 | -0.0020 | 8 |
| sector_relative_ar | 5d | +0.0008 | -0.0026 | +0.0012 | -0.0026 | +0.0018 | 8 |
| sector_relative_ar | 20d | +0.0018 | -0.0099 | +0.0031 | -0.0099 | +0.0031 | 8 |
| sar | 1d | -0.6268 | -0.6438 | -0.6034 | -0.6438 | -0.6034 | 8 |
| sar | 5d | -0.3419 | -0.3754 | -0.0419 | -0.3754 | +0.0055 | 8 |
| sar | 20d | -0.0347 | -0.2633 | +0.1312 | -0.2633 | +0.1312 | 8 |

### designed_contrast / `fed_policy_path` = `tightening` - N 9, unique dates 9, support `insufficient_n`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | -0.0140 | -0.0144 | -0.0030 | -0.0205 | +0.0080 | 5 |
| absolute_asset_return | 5d | +0.0150 | +0.0130 | +0.0173 | +0.0110 | +0.0197 | 5 |
| absolute_asset_return | 20d | -0.0068 | -0.0088 | -0.0036 | -0.0285 | -0.0003 | 5 |
| spy_relative_ar | 1d | -0.0110 | -0.0115 | -0.0045 | -0.0121 | +0.0021 | 5 |
| spy_relative_ar | 5d | +0.0231 | +0.0123 | +0.0233 | +0.0126 | +0.0231 | 5 |
| spy_relative_ar | 20d | -0.0257 | -0.0262 | -0.0120 | -0.0267 | +0.0017 | 5 |
| sector_relative_ar | 1d | -0.0055 | -0.0058 | -0.0044 | -0.0062 | -0.0032 | 5 |
| sector_relative_ar | 5d | +0.0005 | -0.0032 | +0.0019 | -0.0032 | +0.0033 | 5 |
| sector_relative_ar | 20d | -0.0148 | -0.0183 | -0.0080 | -0.0218 | -0.0011 | 5 |
| sar | 1d | -0.3623 | -0.5245 | -0.1160 | -0.6866 | +0.1304 | 5 |
| sar | 5d | +0.5877 | +0.3063 | +0.6120 | +0.3306 | +0.5877 | 5 |
| sar | 20d | -0.3118 | -0.3481 | -0.1496 | -0.3844 | +0.0127 | 5 |

### designed_contrast / `spy_trend_ma200` = `above_ma` - N 24, unique dates 24, support `sufficient_structure`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | +0.0004 | -0.0023 | +0.0032 | -0.0062 | +0.0066 | 16 |
| absolute_asset_return | 5d | +0.0084 | +0.0058 | +0.0110 | +0.0048 | +0.0199 | 16 |
| absolute_asset_return | 20d | +0.0170 | -0.0003 | +0.0344 | -0.0036 | +0.0344 | 16 |
| spy_relative_ar | 1d | +0.0016 | +0.0012 | +0.0021 | -0.0040 | +0.0036 | 16 |
| spy_relative_ar | 5d | +0.0141 | +0.0140 | +0.0142 | +0.0110 | +0.0166 | 16 |
| spy_relative_ar | 20d | -0.0039 | -0.0054 | -0.0024 | -0.0257 | -0.0024 | 16 |
| sector_relative_ar | 1d | +0.0002 | +0.0000 | +0.0005 | -0.0011 | +0.0023 | 16 |
| sector_relative_ar | 5d | +0.0033 | +0.0020 | +0.0046 | +0.0018 | +0.0049 | 16 |
| sector_relative_ar | 20d | +0.0014 | +0.0010 | +0.0018 | -0.0011 | +0.0018 | 16 |
| sar | 1d | +0.1106 | +0.0908 | +0.1304 | -0.2446 | +0.2462 | 16 |
| sar | 5d | +0.3422 | +0.3315 | +0.3529 | +0.2948 | +0.3713 | 16 |
| sar | 20d | -0.0566 | -0.0784 | -0.0347 | -0.3118 | -0.0347 | 16 |

### designed_contrast / `spy_trend_ma200` = `below_ma` - N 8, unique dates 8, support `insufficient_n`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | -0.0160 | -0.0173 | -0.0147 | -0.0248 | -0.0026 | 4 |
| absolute_asset_return | 5d | +0.0173 | +0.0150 | +0.0197 | -0.0285 | +0.0197 | 4 |
| absolute_asset_return | 20d | +0.0053 | -0.0378 | +0.0484 | -0.0378 | +0.0484 | 4 |
| spy_relative_ar | 1d | -0.0113 | -0.0116 | -0.0110 | -0.0229 | +0.0039 | 4 |
| spy_relative_ar | 5d | -0.0040 | -0.0096 | +0.0016 | -0.0378 | +0.0016 | 4 |
| spy_relative_ar | 20d | +0.0048 | +0.0017 | +0.0079 | -0.0111 | +0.0280 | 4 |
| sector_relative_ar | 1d | -0.0044 | -0.0055 | -0.0032 | -0.0070 | -0.0032 | 4 |
| sector_relative_ar | 5d | -0.0018 | -0.0069 | +0.0033 | -0.0069 | +0.0033 | 4 |
| sector_relative_ar | 20d | +0.0011 | -0.0148 | +0.0171 | -0.0183 | +0.0316 | 4 |
| sar | 1d | -0.4984 | -0.6345 | -0.3623 | -1.4546 | -0.0071 | 4 |
| sar | 5d | -0.0274 | -0.0798 | +0.0249 | -1.0192 | +0.0249 | 4 |
| sar | 20d | +0.0547 | +0.0127 | +0.0967 | -0.1753 | +0.2438 | 4 |

### frame_complete_historical / `curve_2s10s` = `inverted` - N 17, unique dates 17, support `sufficient_structure`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | -0.0145 | -0.0152 | -0.0109 | -0.0158 | -0.0109 | 9 |
| absolute_asset_return | 5d | -0.0004 | -0.0040 | +0.0014 | -0.0076 | +0.0014 | 9 |
| absolute_asset_return | 20d | -0.0012 | -0.0058 | -0.0003 | -0.0105 | +0.0083 | 9 |
| spy_relative_ar | 1d | +0.0020 | -0.0042 | +0.0025 | -0.0124 | +0.0025 | 9 |
| spy_relative_ar | 5d | -0.0033 | -0.0051 | -0.0011 | -0.0180 | -0.0011 | 9 |
| spy_relative_ar | 20d | -0.0155 | -0.0186 | -0.0154 | -0.0217 | -0.0087 | 9 |
| sector_relative_ar | 1d | +0.0013 | -0.0015 | +0.0017 | -0.0060 | +0.0020 | 9 |
| sector_relative_ar | 5d | -0.0028 | -0.0030 | -0.0017 | -0.0036 | -0.0006 | 9 |
| sector_relative_ar | 20d | -0.0181 | -0.0190 | -0.0160 | -0.0200 | -0.0138 | 9 |
| sar | 1d | +0.1315 | -0.1471 | +0.2030 | -1.3217 | +0.2030 | 9 |
| sar | 5d | -0.0678 | -0.0966 | -0.0178 | -0.5973 | -0.0178 | 9 |
| sar | 20d | -0.2148 | -0.2845 | -0.1782 | -0.3543 | -0.0949 | 9 |

### frame_complete_historical / `curve_2s10s` = `non_inverted` - N 48, unique dates 48, support `sufficient_structure`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | -0.0049 | -0.0055 | -0.0043 | -0.0069 | +0.0002 | 39 |
| absolute_asset_return | 5d | -0.0019 | -0.0020 | -0.0018 | -0.0055 | +0.0005 | 39 |
| absolute_asset_return | 20d | +0.0043 | +0.0021 | +0.0066 | -0.0013 | +0.0134 | 39 |
| spy_relative_ar | 1d | -0.0034 | -0.0039 | -0.0029 | -0.0072 | +0.0022 | 39 |
| spy_relative_ar | 5d | -0.0006 | -0.0020 | +0.0009 | -0.0044 | +0.0010 | 39 |
| spy_relative_ar | 20d | -0.0118 | -0.0137 | -0.0099 | -0.0169 | -0.0091 | 39 |
| sector_relative_ar | 1d | -0.0028 | -0.0031 | -0.0025 | -0.0045 | -0.0019 | 39 |
| sector_relative_ar | 5d | -0.0016 | -0.0017 | -0.0016 | -0.0027 | +0.0010 | 39 |
| sector_relative_ar | 20d | -0.0086 | -0.0087 | -0.0084 | -0.0107 | -0.0062 | 39 |
| sar | 1d | -0.3240 | -0.3588 | -0.2892 | -0.4431 | +0.1407 | 39 |
| sar | 5d | -0.0257 | -0.0806 | +0.0291 | -0.1670 | +0.0426 | 39 |
| sar | 20d | -0.2027 | -0.2356 | -0.1697 | -0.3346 | -0.1458 | 39 |

### frame_complete_historical / `fed_policy_path` = `easing` - N 17, unique dates 17, support `sufficient_structure`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | +0.0008 | -0.0030 | +0.0030 | -0.0088 | +0.0052 | 11 |
| absolute_asset_return | 5d | +0.0125 | +0.0125 | +0.0152 | -0.0090 | +0.0186 | 11 |
| absolute_asset_return | 20d | -0.0013 | -0.0081 | +0.0026 | -0.0149 | +0.0196 | 11 |
| spy_relative_ar | 1d | -0.0039 | -0.0062 | -0.0014 | -0.0125 | +0.0029 | 11 |
| spy_relative_ar | 5d | +0.0139 | +0.0104 | +0.0165 | -0.0044 | +0.0198 | 11 |
| spy_relative_ar | 20d | -0.0172 | -0.0258 | -0.0170 | -0.0344 | -0.0042 | 11 |
| sector_relative_ar | 1d | -0.0036 | -0.0039 | -0.0031 | -0.0043 | -0.0025 | 11 |
| sector_relative_ar | 5d | +0.0003 | -0.0006 | +0.0007 | -0.0018 | +0.0026 | 11 |
| sector_relative_ar | 20d | -0.0141 | -0.0155 | -0.0139 | -0.0209 | -0.0087 | 11 |
| sar | 1d | -0.3624 | -0.3973 | -0.1543 | -0.7784 | +0.1970 | 11 |
| sar | 5d | +0.3307 | +0.3080 | +0.4133 | -0.1011 | +0.6730 | 11 |
| sar | 20d | -0.3755 | -0.4375 | -0.3550 | -0.4996 | -0.0976 | 11 |

### frame_complete_historical / `fed_policy_path` = `hold` - N 22, unique dates 22, support `sufficient_structure`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | -0.0049 | -0.0055 | -0.0043 | -0.0114 | +0.0019 | 14 |
| absolute_asset_return | 5d | -0.0078 | -0.0079 | -0.0076 | -0.0155 | -0.0049 | 14 |
| absolute_asset_return | 20d | +0.0067 | -0.0012 | +0.0146 | -0.0178 | +0.0159 | 14 |
| spy_relative_ar | 1d | -0.0030 | -0.0083 | +0.0022 | -0.0130 | +0.0027 | 14 |
| spy_relative_ar | 5d | -0.0132 | -0.0180 | -0.0083 | -0.0338 | -0.0083 | 14 |
| spy_relative_ar | 20d | -0.0118 | -0.0137 | -0.0099 | -0.0152 | +0.0003 | 14 |
| sector_relative_ar | 1d | -0.0059 | -0.0060 | -0.0057 | -0.0095 | -0.0052 | 14 |
| sector_relative_ar | 5d | -0.0116 | -0.0140 | -0.0091 | -0.0239 | -0.0077 | 14 |
| sector_relative_ar | 20d | -0.0089 | -0.0134 | -0.0044 | -0.0139 | -0.0041 | 14 |
| sar | 1d | -0.1126 | -0.3588 | +0.1336 | -0.8789 | +0.1407 | 14 |
| sar | 5d | -0.4495 | -0.5973 | -0.3017 | -0.9600 | -0.2929 | 14 |
| sar | 20d | -0.1473 | -0.1697 | -0.1250 | -0.2148 | +0.0069 | 14 |

### frame_complete_historical / `fed_policy_path` = `tightening` - N 26, unique dates 26, support `sufficient_structure`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | -0.0079 | -0.0083 | -0.0074 | -0.0126 | -0.0049 | 18 |
| absolute_asset_return | 5d | -0.0016 | -0.0029 | -0.0004 | -0.0030 | +0.0001 | 18 |
| absolute_asset_return | 20d | +0.0014 | +0.0007 | +0.0021 | -0.0049 | +0.0090 | 18 |
| spy_relative_ar | 1d | -0.0004 | -0.0029 | +0.0020 | -0.0048 | +0.0025 | 18 |
| spy_relative_ar | 5d | +0.0010 | +0.0010 | +0.0011 | -0.0012 | +0.0017 | 18 |
| spy_relative_ar | 20d | -0.0127 | -0.0155 | -0.0099 | -0.0186 | -0.0047 | 18 |
| sector_relative_ar | 1d | +0.0010 | +0.0006 | +0.0013 | -0.0007 | +0.0028 | 18 |
| sector_relative_ar | 5d | +0.0003 | -0.0006 | +0.0012 | -0.0016 | +0.0028 | 18 |
| sector_relative_ar | 20d | -0.0077 | -0.0077 | -0.0077 | -0.0105 | -0.0067 | 18 |
| sar | 1d | -0.0789 | -0.2892 | +0.1315 | -0.4763 | +0.2030 | 18 |
| sar | 5d | +0.0375 | +0.0323 | +0.0426 | -0.0178 | +0.0739 | 18 |
| sar | 20d | -0.2012 | -0.2356 | -0.1667 | -0.2949 | -0.0949 | 18 |

### frame_complete_historical / `spy_trend_ma200` = `above_ma` - N 50, unique dates 50, support `sufficient_structure`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | -0.0017 | -0.0042 | +0.0008 | -0.0049 | +0.0019 | 42 |
| absolute_asset_return | 5d | -0.0024 | -0.0029 | -0.0020 | -0.0053 | -0.0018 | 42 |
| absolute_asset_return | 20d | -0.0003 | -0.0012 | +0.0007 | -0.0013 | +0.0066 | 42 |
| spy_relative_ar | 1d | +0.0016 | +0.0011 | +0.0020 | -0.0067 | +0.0022 | 42 |
| spy_relative_ar | 5d | -0.0006 | -0.0020 | +0.0009 | -0.0033 | +0.0009 | 42 |
| spy_relative_ar | 20d | -0.0154 | -0.0155 | -0.0152 | -0.0170 | -0.0137 | 42 |
| sector_relative_ar | 1d | -0.0022 | -0.0025 | -0.0019 | -0.0036 | -0.0015 | 42 |
| sector_relative_ar | 5d | -0.0001 | -0.0006 | +0.0003 | -0.0017 | +0.0011 | 42 |
| sector_relative_ar | 20d | -0.0136 | -0.0138 | -0.0134 | -0.0139 | -0.0127 | 42 |
| sar | 1d | +0.0926 | +0.0537 | +0.1315 | -0.3923 | +0.1407 | 42 |
| sar | 5d | -0.0193 | -0.0678 | +0.0291 | -0.0742 | +0.0307 | 42 |
| sar | 20d | -0.2252 | -0.2356 | -0.2148 | -0.3444 | -0.1416 | 42 |

### frame_complete_historical / `spy_trend_ma200` = `below_ma` - N 15, unique dates 15, support `sufficient_structure`

| metric | h | median | LOEO min med | LOEO max med | LOYO min med | LOYO max med | LOYO min N |
|---|---|---|---|---|---|---|---|
| absolute_asset_return | 1d | -0.0112 | -0.0147 | -0.0110 | -0.0183 | -0.0068 | 7 |
| absolute_asset_return | 5d | +0.0032 | +0.0014 | +0.0040 | -0.0004 | +0.0085 | 7 |
| absolute_asset_return | 20d | +0.0021 | -0.0034 | +0.0109 | -0.0034 | +0.0196 | 7 |
| spy_relative_ar | 1d | -0.0039 | -0.0081 | -0.0034 | -0.0124 | -0.0029 | 7 |
| spy_relative_ar | 5d | -0.0133 | -0.0163 | -0.0049 | -0.0193 | +0.0068 | 7 |
| spy_relative_ar | 20d | -0.0099 | -0.0139 | -0.0059 | -0.0372 | -0.0019 | 7 |
| sector_relative_ar | 1d | -0.0060 | -0.0065 | -0.0029 | -0.0065 | +0.0005 | 7 |
| sector_relative_ar | 5d | -0.0036 | -0.0044 | -0.0032 | -0.0044 | +0.0027 | 7 |
| sector_relative_ar | 20d | -0.0058 | -0.0067 | -0.0052 | -0.0067 | -0.0046 | 7 |
| sar | 1d | -0.3624 | -0.7212 | -0.3258 | -1.0801 | -0.2892 | 7 |
| sar | 5d | -0.5423 | -0.7132 | -0.2168 | -0.8841 | +0.2854 | 7 |
| sar | 20d | -0.1697 | -0.2726 | -0.1089 | -0.3755 | -0.0482 | 7 |

## 5. Cross-metric and cross-horizon consistency board

Descriptive sign accounting per continuous entry (12 metric x horizon rhos each). 'Same sign' means all three horizons share one nonzero sign for that metric; 'LOYO preserves' additionally means no year exclusion at any horizon flips it. No score, no ranking, no winner.

| lane | axis | rho signs +/0/- | absolute_asset_return: same-sign / LOYO-preserves | spy_relative_ar: same-sign / LOYO-preserves | sector_relative_ar: same-sign / LOYO-preserves | sar: same-sign / LOYO-preserves |
|---|---|---|---|---|---|---|
| designed_contrast | `credit_hy_oas` | 2/0/10 | no / no | yes / no | no / no | yes / no |
| designed_contrast | `curve_2s10s` | 9/0/3 | no / no | no / no | yes / no | no / no |
| designed_contrast | `fed_policy_path` | 3/0/9 | no / no | no / no | yes / yes | no / no |
| designed_contrast | `spy_trend_ma200` | 9/0/3 | yes / no | no / no | yes / no | no / no |
| designed_contrast | `vix_level_percentile` | 11/0/1 | no / no | yes / no | yes / no | yes / no |
| frame_complete_historical | `credit_hy_oas` | 5/0/7 | no / no | no / no | no / no | no / no |
| frame_complete_historical | `curve_2s10s` | 11/0/1 | yes / no | yes / no | no / no | yes / no |
| frame_complete_historical | `fed_policy_path` | 8/0/4 | no / no | no / no | yes / no | no / no |
| frame_complete_historical | `spy_trend_ma200` | 10/0/2 | yes / no | yes / yes | no / no | yes / no |
| frame_complete_historical | `vix_level_percentile` | 3/0/9 | yes / no | yes / no | yes / no | yes / no |

## 6. Contradiction board (described directly, not adjudicated)

- cross-lane sign disagreements (same axis/metric/horizon, opposite nonzero sign): 35 - credit_hy_oas/absolute_asset_return/1d, credit_hy_oas/absolute_asset_return/20d, credit_hy_oas/spy_relative_ar/1d, credit_hy_oas/sector_relative_ar/1d, credit_hy_oas/sector_relative_ar/5d, credit_hy_oas/sector_relative_ar/20d, credit_hy_oas/sar/1d, curve_2s10s/absolute_asset_return/20d, curve_2s10s/spy_relative_ar/20d, curve_2s10s/sector_relative_ar/1d, curve_2s10s/sar/20d, fed_policy_path/absolute_asset_return/5d, fed_policy_path/absolute_asset_return/20d, fed_policy_path/spy_relative_ar/1d, fed_policy_path/spy_relative_ar/5d, fed_policy_path/spy_relative_ar/20d, fed_policy_path/sector_relative_ar/1d, fed_policy_path/sector_relative_ar/5d, fed_policy_path/sector_relative_ar/20d, fed_policy_path/sar/1d, fed_policy_path/sar/5d, fed_policy_path/sar/20d, spy_trend_ma200/spy_relative_ar/20d, spy_trend_ma200/sector_relative_ar/1d, spy_trend_ma200/sector_relative_ar/5d, spy_trend_ma200/sar/1d, spy_trend_ma200/sar/20d, vix_level_percentile/absolute_asset_return/1d, vix_level_percentile/absolute_asset_return/20d, vix_level_percentile/spy_relative_ar/1d, vix_level_percentile/spy_relative_ar/5d, vix_level_percentile/spy_relative_ar/20d, vix_level_percentile/sar/1d, vix_level_percentile/sar/5d, vix_level_percentile/sar/20d
- horizon sign reversals (within lane/axis/metric): 20 - designed_contrast/credit_hy_oas/absolute_asset_return, designed_contrast/credit_hy_oas/sector_relative_ar, designed_contrast/curve_2s10s/absolute_asset_return, designed_contrast/curve_2s10s/spy_relative_ar, designed_contrast/curve_2s10s/sar, designed_contrast/fed_policy_path/absolute_asset_return, designed_contrast/fed_policy_path/spy_relative_ar, designed_contrast/fed_policy_path/sar, designed_contrast/spy_trend_ma200/spy_relative_ar, designed_contrast/spy_trend_ma200/sar, designed_contrast/vix_level_percentile/absolute_asset_return, frame_complete_historical/credit_hy_oas/absolute_asset_return, frame_complete_historical/credit_hy_oas/spy_relative_ar, frame_complete_historical/credit_hy_oas/sector_relative_ar, frame_complete_historical/credit_hy_oas/sar, frame_complete_historical/curve_2s10s/sector_relative_ar, frame_complete_historical/fed_policy_path/absolute_asset_return, frame_complete_historical/fed_policy_path/spy_relative_ar, frame_complete_historical/fed_policy_path/sar, frame_complete_historical/spy_trend_ma200/sector_relative_ar
- metric sign disagreements (within lane/axis/horizon): 15 - designed_contrast/credit_hy_oas/20d, designed_contrast/curve_2s10s/20d, designed_contrast/fed_policy_path/5d, designed_contrast/spy_trend_ma200/1d, designed_contrast/spy_trend_ma200/20d, designed_contrast/vix_level_percentile/5d, frame_complete_historical/credit_hy_oas/5d, frame_complete_historical/curve_2s10s/1d, frame_complete_historical/fed_policy_path/1d, frame_complete_historical/fed_policy_path/5d, frame_complete_historical/spy_trend_ma200/1d, frame_complete_historical/spy_trend_ma200/5d, frame_complete_historical/vix_level_percentile/1d, frame_complete_historical/vix_level_percentile/5d, frame_complete_historical/vix_level_percentile/20d
- associations with at least one LOEO sign reversal: 44
- associations with at least one LOYO sign reversal: 76

A pattern that survives these checks is not thereby 'validated'; a pattern that fails them is not thereby refuted. Both facts are recorded and carried forward as-is.

## 7. Explicit falsifier treatment (uniform, no custom model)

The two patterns singled out in the G6A session summary receive the same diagnostics as every other association - their rows sit in the section 2 board above under exactly the same columns:

- OPEC `fed_policy_path` x sector-relative AR 1d: rho -0.4564; LOEO [-0.5288, -0.4015], opposite 0; LOYO [-0.5183, -0.3668], opposite 0, min retained N 22
- OPEC `fed_policy_path` x sector-relative AR 5d: rho -0.2929; LOEO [-0.3838, -0.2378], opposite 0; LOYO [-0.4754, -0.1859], opposite 0, min retained N 22
- OPEC `fed_policy_path` x sector-relative AR 20d: rho -0.3824; LOEO [-0.4445, -0.3190], opposite 0; LOYO [-0.4569, -0.3104], opposite 0, min retained N 22

- calendar-time confound: OPEC-lane `fed_policy_path` vs date ordinal rho = -0.2708 (section 3). A material value here means the pattern cannot be distinguished from calendar-time drift inside this lane by these data alone.

- OPEC credit subset (N=16, era-bounded, secondary-only) - all 12 associations, same treatment:
  - absolute_asset_return 1d: rho -0.0427; LOEO opposite 5; LOYO opposite 2
  - absolute_asset_return 5d: rho -0.0854; LOEO opposite 3; LOYO opposite 2
  - absolute_asset_return 20d: rho +0.1781; LOEO opposite 0; LOYO opposite 0
  - sar 1d: rho -0.1177; LOEO opposite 1; LOYO opposite 1
  - sar 5d: rho -0.3194; LOEO opposite 0; LOYO opposite 0
  - sar 20d: rho -0.0780; LOEO opposite 3; LOYO opposite 1
  - sector_relative_ar 1d: rho -0.0618; LOEO opposite 2; LOYO opposite 1
  - sector_relative_ar 5d: rho -0.0486; LOEO opposite 4; LOYO opposite 2
  - sector_relative_ar 20d: rho +0.1545; LOEO opposite 0; LOYO opposite 1
  - spy_relative_ar 1d: rho -0.1060; LOEO opposite 1; LOYO opposite 1
  - spy_relative_ar 5d: rho -0.2899; LOEO opposite 0; LOYO opposite 0
  - spy_relative_ar 20d: rho -0.1074; LOEO opposite 1; LOYO opposite 0

## 8. Null findings (kept visible)

The broad FOMC frame-complete surface remains flat: the largest absolute full-sample rho anywhere in that lane is 0.2746, and the section 5 board shows how few metric panels hold one sign across horizons even before leave-one-out stress. This flatness is a first-class finding of the frozen manifest and is not reduced to the exceptions above.

## 9. Non-claims

Descriptive robustness accounting only. No causal regime effect, no forecast, no trading recommendation, no single-event significance, no prevalence claim for designed-contrast evidence, no inferential claim from the structural support floor, and no 'validated pattern' label. Not a trading, prediction, or recommendation surface.

## 10. Reproduction

```
python scripts/g6b_stability_falsifiers.py --emit
python -m unittest tests.test_g6b_stability_falsifiers
```
