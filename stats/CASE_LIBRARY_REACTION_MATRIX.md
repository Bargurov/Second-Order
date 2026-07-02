# Case-library market reaction matrix (H1)

A read-only, descriptive market-reaction matrix over the 15 representative cases
(6 N1 anchors + 9 newly proposed). One compact row per case:
case → role → family → outcome → event-study availability → primary ticker →
1d / 5d / 20d SPY-relative readout → caveats. It reuses F1's selection and the
event-study readout layer; it recomputes no event-study math and makes no
inference. This is a readout surface only — no model, no p-values, no FDR, no
thresholds, no trading language.

**Two lenses, kept separate.** The **readout** is the *primary ticker's*
abnormal return vs SPY over the event window (AR% / SAR / CAR%; SAR is a ratio,
not a percent). The **outcome** is *thesis-direction scoring of the named
tickers* (support / contradiction / unresolved). They can disagree — readout
availability is not the same as thesis support. **Cases 29 and 38 are the
canonical example: the same XLE-vs-SPY readout on the same date (2026-04-05),
opposite outcomes (29 contradiction, 38 support).**

## Denominator guardrail (live, unchanged)

archive **180** · accepted coverage **94** · accepted track-record **86** ·
event-study **78/94** · staged **13** (excluded).

## Reproduce (read-only)

```
python scripts/case_library_reaction_matrix.py --db-path events.db --json
python scripts/case_library_reaction_matrix.py --db-path events.db
```

Selected ids — anchors: **1, 46, 61, 66, 210, 211**; new: **7, 29, 38, 71, 153,
154, 160, 212, 239**.

## Reaction matrix

AR% per horizon shown (SPY-relative); full AR% / SAR / CAR% per horizon is in the
`--json` output. "unavailable" = no event-study readout for the case.

| case | role | family | outcome | ES | primary | 1d AR% | 5d AR% | 20d AR% | event-date anchor |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | anchor | tariff | support | yes | TSLA | -2.63 | -6.83 | -2.08 | partial_anticipation |
| 46 | anchor | monetary_policy_or_rates | support | yes | DRIV | -0.19 | +4.10 | +11.63 | scheduled_or_weak_anchor |
| 61 | anchor | geopolitical_conflict_context | contradiction | yes | BTU | -8.76 | -10.66 | -25.85 | partial_anticipation |
| 66 | anchor | ceasefire_deescalation | support | yes | XLE | -1.82 | -7.48 | -10.36 | scheduled_or_weak_anchor |
| 210 | anchor | supply_shock | unresolved | yes | XOM | -1.30 | -6.82 | -10.50 | clean_discrete_anchor |
| 211 | anchor | sanction | unresolved | yes | FSLR | +4.92 | +11.24 | +53.12 | scheduled_or_weak_anchor |
| 7 | new | geopolitical_conflict_context | support | yes | XLE | +0.25 | -7.50 | -10.56 | manual_review_needed |
| 29 | new | supply_shock | contradiction | yes | XLE | +0.25 | -7.50 | -10.56 | duplicate_or_deferred |
| 38 | new | supply_shock | support | yes | XLE | +0.25 | -7.50 | -10.56 | manual_review_needed |
| 71 | new | ceasefire_deescalation | support | yes | VLO | +0.43 | -1.61 | -8.28 | scheduled_or_weak_anchor |
| 153 | new | sanction | unresolved | no | — | unavailable | unavailable | unavailable | scheduled_or_weak_anchor |
| 154 | new | sanction | unresolved | no | — | unavailable | unavailable | unavailable | manual_review_needed |
| 160 | new | ceasefire_deescalation | unresolved | no | — | unavailable | unavailable | unavailable | partial_anticipation |
| 212 | new | tariff | unresolved | yes | TJX | -0.50 | -3.52 | -6.80 | clean_discrete_anchor |
| 239 | new | monetary_policy_or_rates | unresolved | yes | BAC | -0.20 | -1.41 | -10.04 | manual_review_needed |

Caveat markers (from F1/F2, surfaced per row in `--json`): thin family (46, 66,
71, 153, 154, 160, 211, 239); overlay-only (7, 46, 61, 239); missing readout
(153, 154, 160); shared XLE primary/date cluster (7, 29, 38 on 2026-04-05);
non-supporting outcome on every contradiction / unresolved row.

## Missingness summary

- readout available: **12 / 15**
- readout missing: **3** — ids **153, 154, 160** (no assets in the record), stated
  explicitly, not omitted.

## Lens warning (29 / 38)

The readout and the outcome are different computations. Cases **29** and **38**
share an identical XLE-vs-SPY readout on the same date (2026-04-05) yet carry
opposite outcomes (29 contradiction, 38 support) — the readout is not the basis
for the outcome. The same disagreement shows elsewhere: e.g. 211 (sanction,
unresolved) has a large positive FSLR readout, and 66 (ceasefire, support) has a
negative XLE readout. Readout availability and direction are not thesis support.

## Caveats / non-claims

- Descriptive case-library readout only; this matrix adds no new claim.
- No family-level inference; outcome labels are the canonical any_support
  vocabulary applied per event, descriptively.
- No pooled significance: no CI, p-value, FDR, or threshold is computed or implied.
- Readout is the primary ticker's abnormal return vs SPY over the window — a
  different lens from the outcome, not a significance claim.
- Not a recommendation of any kind, and no forecast.
- Denominators unchanged: 94 accepted coverage / 86 accepted track-record;
  staged candidates (13) are excluded.
