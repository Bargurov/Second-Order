# Expanded case notes — 9 newly proposed F1 cases (F2)

Read-only, source-grounded notes for the nine cases F1 newly proposed for the
representative case library: **7, 29, 38, 71, 153, 154, 160, 212, 239**. Each
note gives event identity, mechanism (the record's own text, verbatim — never
invented), assets, the SPY-relative event-study readout where available, the
deterministic F1 selection reason, caveats, and an explicit non-claim. The six
N1 anchors (1, 46, 61, 66, 210, 211) are referenced but **not rewritten**, and
the N1 walkthrough is untouched. No new selection, no new analysis, no p-value,
no FDR, no forecast, no trading language.

**Two lenses, kept separate.** The event-study readout is the *primary ticker's*
abnormal return vs SPY over the event window. The outcome (support /
contradiction / unresolved) is *thesis-direction scoring of the named tickers*.
These are different computations, so two same-date cases can share an identical
readout yet carry opposite outcomes — see events 29 and 38.

## Denominator guardrail (live, unchanged)

archive **180** · accepted coverage **94** · accepted track-record **86** ·
event-study **78/94** · staged **13** (excluded).

## Source / reproduce (read-only)

```
python scripts/expanded_case_notes_report.py --db-path events.db --json
python scripts/expanded_case_notes_report.py --db-path events.db
python scripts/representative_case_expansion_report.py --db-path events.db --json
```

Selected case ids (this report): **7, 29, 38, 71, 153, 154, 160, 212, 239**.
N1 anchors carried but not rewritten: **1, 46, 61, 66, 210, 211**.

## Case notes

Readout shown as AR% / SAR / CAR% per horizon (SPY-relative; SAR is a ratio, not
a percent). "Readout: unavailable" means no event-study readout exists for the case.

The mechanism line in each note below is **abridged** from that record's fuller
`mechanism_summary` field for readability; it asserts nothing the record does
not. The `--json` / text output of the script carries the record's verbatim
`mechanism_summary` and `what_changed` — re-run the reproduce command for the
full field text.

### Event 7 — US and Iran trade threats to unleash 'hell' amid missing-airman search
- Family lens: geopolitical_conflict_context (overlay-only) · Outcome: support · Event date: 2026-04-05 (anchor: manual_review_needed)
- Why selected: support example in geopolitical_conflict_context (overlay-only bucket).
- Mechanism: heightened US-Iran tensions raise the geopolitical risk premium in crude and tanker-transit risk through the Strait of Hormuz; defense names benefit from elevated threat perception.
- Assets: XLE, LMT, RTX, DAL, UAL, JETS (event-study primary XLE vs SPY; ticker fields do not rank primary vs secondary exposure).
- Readout: 1d +0.25 / 0.15 / +0.25 · 5d -7.50 / -1.99 / -7.47 · 20d -10.56 / -1.40 / -9.95.
- Caveats / falsifier: event-date anchor manual_review_needed; readout is XLE-vs-SPY, a different lens from the outcome.
- Non-claim: illustrative case note only — not evidence, no family-level inference, no recommendation or forecast.

### Event 29 — Iran threatens to 'completely' close Strait of Hormuz, hit power plants
- Family lens: supply_shock · Outcome: contradiction · Event date: 2026-04-05 (anchor: duplicate_or_deferred)
- Why selected: contradiction example in supply_shock.
- Mechanism: the Strait of Hormuz carries ~21% of global petroleum-liquids transit; closure threats create oil supply-risk premia, benefiting non-Gulf producers and penalizing Asian refiners.
- Assets: XLE, XOP, CVX, JETS, DAL, UAL (event-study primary XLE vs SPY).
- Readout: 1d +0.25 / 0.15 / +0.25 · 5d -7.50 / -1.99 / -7.47 · 20d -10.56 / -1.40 / -9.95.
- Caveats / falsifier: non-supporting (contradiction); duplicate_or_deferred anchor; identical readout to events 7 and 38 (same XLE primary + date), opposite outcome — a different lens.
- Non-claim: illustrative case note only — not evidence, no family-level inference, no recommendation or forecast.

### Event 38 — "this feels big for oil and shipping"
- Family lens: supply_shock · Outcome: support · Event date: 2026-04-05 (anchor: manual_review_needed)
- Why selected: support example in supply_shock (the F1A balance-repair pick that gives the largest family a support example).
- Mechanism: record notes "insufficient evidence to identify mechanism" — surfaced as-is, not invented.
- Assets: XLE, STNG, BDRY, XLI (event-study primary XLE vs SPY).
- Readout: 1d +0.25 / 0.15 / +0.25 · 5d -7.50 / -1.99 / -7.47 · 20d -10.56 / -1.40 / -9.95.
- Caveats / falsifier: thin mechanism in record; manual_review_needed anchor; identical readout to 7/29 (shared XLE primary + date), yet scored support — outcome is a different lens from the readout.
- Non-claim: illustrative case note only — not evidence, no family-level inference, no recommendation or forecast.

### Event 71 — 'Iran open to negotiations': diplomacy shows signs of progress
- Family lens: ceasefire_deescalation (thin) · Outcome: support · Event date: 2026-04-09 (anchor: scheduled_or_weak_anchor)
- Why selected: support example in ceasefire_deescalation (thin family).
- Mechanism: Iranian diplomatic overtures reduce escalation probability and signal potential sanctions relief, pressuring oil futures as supply expectations rise; refiners benefit, competing exporters lose share.
- Assets: VLO, PSX, XOM, XLE, XOP, OXY (event-study primary VLO vs SPY).
- Readout: 1d +0.43 / 0.16 / +0.43 · 5d -1.61 / -0.27 / -1.53 · 20d -8.28 / -0.68 / -7.28.
- Caveats / falsifier: low-n / thin family; scheduled_or_weak_anchor (anticipated diplomacy).
- Non-claim: illustrative case note only — not evidence, no family-level inference, no recommendation or forecast.

### Event 153 — Trump signs order imposing sanctions on the International Criminal Court
- Family lens: sanction (thin) · Outcome: unresolved · Event date: 2026-04-29 (anchor: scheduled_or_weak_anchor)
- Why selected: unresolved example in sanction (thin family).
- Mechanism: record returned a thin response ("insufficient evidence to identify a specific transmission mechanism") — surfaced as-is.
- Assets: no assets in the record.
- Readout: unavailable (no event-study readout for this case).
- Caveats / falsifier: missing event-study readout; thin family; non-supporting (unresolved); scheduled_or_weak_anchor.
- Non-claim: illustrative case note only — not evidence, no family-level inference, no recommendation or forecast.

### Event 154 — Take action over officials in Kyrgyzstan 'helping Russia evade sanctions'
- Family lens: sanction (thin) · Outcome: unresolved · Event date: 2026-04-29 (anchor: manual_review_needed)
- Why selected: unresolved example in sanction (thin family).
- Mechanism: record returned a thin response ("insufficient evidence...") — surfaced as-is.
- Assets: no assets in the record.
- Readout: unavailable.
- Caveats / falsifier: missing event-study readout; thin family; non-supporting (unresolved); manual_review_needed anchor.
- Non-claim: illustrative case note only — not evidence, no family-level inference, no recommendation or forecast.

### Event 160 — Iran's FM Araghchi arrives in Pakistan ahead of planned US ceasefire talks
- Family lens: ceasefire_deescalation (thin) · Outcome: unresolved · Event date: 2026-04-29 (anchor: partial_anticipation)
- Why selected: unresolved example in ceasefire_deescalation (thin family).
- Mechanism: record notes "insufficient evidence to identify mechanism"; the recorded chain explicitly states "no clear transmission channel identified" — surfaced as-is.
- Assets: no assets in the record.
- Readout: unavailable.
- Caveats / falsifier: missing event-study readout; thin family; non-supporting (unresolved); partial_anticipation anchor.
- Non-claim: illustrative case note only — not evidence, no family-level inference, no recommendation or forecast.

### Event 212 — US tariff refund system launches for companies to claim import taxes
- Family lens: tariff · Outcome: unresolved · Event date: 2026-04-29 (anchor: clean_discrete_anchor)
- Why selected: unresolved example in tariff.
- Mechanism: the refund system lets companies recover paid import duties, improving importer cash flow while reducing effective tariff protection for import-competing domestic producers.
- Assets: TJX, COST, WMT (event-study primary TJX vs SPY).
- Readout: 1d -0.50 / -0.38 / -0.50 · 5d -3.52 / -1.21 / -3.49 · 20d -6.80 / -1.16 / -6.40.
- Caveats / falsifier: non-supporting (unresolved). Anchor is clean_discrete_anchor (a cleanly dated case).
- Non-claim: illustrative case note only — not evidence, no family-level inference, no recommendation or forecast.

### Event 239 — Jerome Powell says he'll stay on Fed board after the FOMC holds rates
- Family lens: monetary_policy_or_rates (overlay-only, thin) · Outcome: unresolved · Event date: 2026-04-29 (anchor: manual_review_needed)
- Why selected: unresolved example in monetary_policy_or_rates (overlay-only bucket, thin family).
- Mechanism: Powell's commitment signals Fed independence and reinforces higher-for-longer rate expectations, pressuring duration-sensitive assets while supporting bank NIM prospects.
- Assets: BAC, KRE, IYR, TLT (event-study primary BAC vs SPY).
- Readout: 1d -2.03 / -1.68 / -2.03 · 5d -6.38 / -2.36 / -6.36 · 20d -8.89 / -1.65 / -8.70.
- Caveats / falsifier: overlay-only bucket; low-n / thin family; non-supporting (unresolved); manual_review_needed anchor.
- Non-claim: illustrative case note only — not evidence, no family-level inference, no recommendation or forecast.

## Missingness / caveats summary

- **No event-study readout:** 153, 154, 160 (no assets in the record) — stated, not omitted.
- **Shared event-study primary:** 7, 29, 38 share the XLE primary on the same date (2026-04-05), so their SPY-relative readouts coincide. This is date clustering, not a repeated independent result.
- **Insufficient mechanism in record:** 38, 153, 154, 160 carry the model's honest "insufficient evidence / thin response" text, surfaced verbatim rather than replaced.
- **Outcome vs readout:** readouts are a different lens from outcomes; 29 (contradiction) and 38 (support) share an identical XLE-vs-SPY readout.

## Non-claims

- Expanded case notes are illustrative only; they add no new claim.
- No family-level inference; outcome labels are the canonical any_support vocabulary applied per event, descriptively.
- No pooled significance: no CI, p-value, or FDR is computed or implied.
- Event-study readouts are SPY-relative abnormal returns over the window, a different lens from the outcome and not a significance claim.
- Mechanism text is the record's own field, surfaced verbatim (including its honest insufficient-evidence placeholders); nothing is invented.
- Not a recommendation of any kind, and no forecast.
- Denominators unchanged: 94 accepted coverage / 86 accepted track-record; staged candidates (13) are excluded.
