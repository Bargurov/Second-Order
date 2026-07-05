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
`--json` output. "unavailable" = no event-study readout for the case. Readouts
are on the canonical basis policy (matched adjusted closes preferred, matched
raw fallback disclosed); see `stats/BASIS_RESTATEMENT.md` for the adoption
record and the exact restated values.

| case | role | family | outcome | ES | primary | 1d AR% | 5d AR% | 20d AR% | event-date anchor |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | anchor | tariff | support | yes | TSLA | -2.63 | -6.83 | -1.50 | partial_anticipation |
| 46 | anchor | monetary_policy_or_rates | support | yes | DRIV | -0.19 | +4.10 | +11.63 | scheduled_or_weak_anchor |
| 61 | anchor | geopolitical_conflict_context | contradiction | yes | BTU | -8.76 | -10.66 | -25.85 | partial_anticipation |
| 66 | anchor | ceasefire_deescalation | support | yes | XLE | -1.82 | -7.48 | -10.36 | scheduled_or_weak_anchor |
| 210 | anchor | supply_shock | unresolved | yes | XOM | -1.30 | -6.82 | -10.50 | clean_discrete_anchor |
| 211 | anchor | sanction | unresolved | yes | FSLR | +4.92 | +11.24 | +53.12 | scheduled_or_weak_anchor |
| 7 | new | geopolitical_conflict_context | support | yes | XLE | +0.25 | -7.50 | -10.56 | manual_review_needed |
| 29 | new | supply_shock | contradiction | yes | XLE | +0.25 | -7.50 | -10.56 | duplicate_or_deferred |
| 38 | new | supply_shock | support | yes | XLE | +0.25 | -7.50 | -10.56 | manual_review_needed |
| 71 | new | ceasefire_deescalation | support | yes | VLO | +1.65 | -0.37 | -7.07 | scheduled_or_weak_anchor |
| 153 | new | sanction | unresolved | no | — | unavailable | unavailable | unavailable | scheduled_or_weak_anchor |
| 154 | new | sanction | unresolved | no | — | unavailable | unavailable | unavailable | manual_review_needed |
| 160 | new | ceasefire_deescalation | unresolved | no | — | unavailable | unavailable | unavailable | partial_anticipation |
| 212 | new | tariff | unresolved | yes | TJX | -0.89 | -3.85 | -6.80 | clean_discrete_anchor |
| 239 | new | monetary_policy_or_rates | unresolved | yes | BAC | +0.10 | -1.77 | -10.04 | manual_review_needed |

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

## Sector-relative second lens (F1, additive)

A second descriptive comparison beside the canonical SPY-relative readout:
absolute return -> vs SPY -> vs the primary ticker's own sector ETF, at the
same 1d / 5d / 20d horizons, computed by the same gated engine (same
estimation-window, forward-cache, and contiguity discipline; beta fixed at 1,
no local beta, no factor model). **SPY stays canonical**; the sector read is a
lens on how much of a SPY-relative move was the sector tape.

Eligibility is deliberately narrow: the ticker -> sector map is the
conservative suggestion-layer map (`sector-map v1`), reused verbatim and never
extended to maximise coverage. Every state is explicit; nothing falls back
silently.

| case | primary | sector ETF | state | 1d sect-rel | 5d sect-rel | 20d sect-rel |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | TSLA | XLY | available | -2.98% | -7.61% | -1.88% |
| 46 | DRIV | - | no sector benchmark (SPY-only) | - | - | - |
| 61 | BTU | - | no sector benchmark (SPY-only) | - | - | - |
| 66 | XLE | - | asset is a sector ETF | - | - | - |
| 210 | XOM | XLE | available | +0.32% | +1.18% | +0.39% |
| 211 | FSLR | - | no sector benchmark (SPY-only) | - | - | - |
| 7 | XLE | - | asset is a sector ETF | - | - | - |
| 29 | XLE | - | asset is a sector ETF | - | - | - |
| 38 | XLE | - | asset is a sector ETF | - | - | - |
| 71 | VLO | XLE | available | +2.26% | +4.13% | +2.94% |
| 153 | - | - | no readout primary | - | - | - |
| 154 | - | - | no readout primary | - | - | - |
| 160 | - | - | no readout primary | - | - | - |
| 212 | TJX | - | no sector benchmark (SPY-only) | - | - | - |
| 239 | BAC | XLF | sector window unavailable (missing benchmark cache) | - | - | - |

What the second lens changes here, descriptively:

- **210 (XOM)**: 5d vs SPY -6.82% reads as sharp underperformance; vs XLE it is
  **+1.18%** - the SPY-relative move was overwhelmingly the energy-sector tape,
  and XOM was slightly ahead of its sector.
- **71 (VLO)**: 5d vs SPY -0.37% but vs XLE **+4.13%** - a clean,
  basis-matched sign contrast: roughly flat against the market, clearly ahead
  of its own sector. (Under the pre-restatement mixed-basis readout this row
  needed a basis caveat; the canonical adjusted-preferred policy resolved it -
  both lenses now share the same adjusted asset series.)
- **1 (TSLA)**: vs SPY and vs XLY read similarly (5d -6.83% vs -7.61%) - the
  move is not explained by the consumer-discretionary tape; the second lens
  adds little and says so.
- The four XLE-primary cases (7, 29, 38, 66) are the sector benchmark itself;
  comparing an ETF to itself is degenerate, so they are labeled, not computed.

Archive-wide (all 86 accepted rows, read-only): 20 rows eligible (17
computable, 3 with an uncached sector window: BA / LMT-late / BAC), 25
XLE-primary rows labeled asset-is-sector-ETF, 28 unmapped (thematic / country
ETFs and unmapped single names stay SPY-only), 13 with no readout primary.
The **sector-vs-market component** (SPY-relative AR minus sector-relative AR;
on a shared asset basis this equals the sector ETF's own excess return over
SPY on the window - a tape property of the (sector, window) pair, not an
asset-specific quantity) has medians of -0.61% at 1d, -7.48% at 5d, and
-10.36% at 20d across **all 17 computable rows, now basis-matched**. Under
the pre-restatement mixed-basis policy four rows (52, 63, 71, 72) had to be
excluded because the two lenses resolved different price bases for the same
asset; the canonical adjusted-preferred policy (see
`stats/BASIS_RESTATEMENT.md`) removed that artifact and no row is excluded.
The 17 computable rows still span only **8 unique (sector ETF, date)
windows** - 14 of 17 are XLE across five dates, so duplicate same-window rows
repeat the same value and these medians describe the XLE tape, not 17
independent observations (the same independence caution the K2 layer applies
to row counts). The component is material at 5d / 20d in this energy-dominated
window and small at 1d.

Sector-lens caveats (in addition to the caveats above):

- A sector-relative residual does not establish company-specific causality; it
  only describes the move relative to one sector ETF over the window.
- Missing sector windows are reported unavailable, never approximated; no
  fetch or backfill is triggered by this layer.
- The outcome labels, accepted denominators, representative-case selection,
  and closed FDR pools are unchanged by this lens.

Reproduce (read-only):

```
python scripts/sector_relative_readout.py --db-path events.db
python scripts/case_library_reaction_matrix.py --db-path events.db --json
```
