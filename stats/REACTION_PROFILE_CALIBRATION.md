# Reaction-profile classification calibration (read-only)

Contract: `reaction-profile-calibration-v1`. Snapshot date: 2026-07-11.

## 1. Executive verdict

### KEEP_CURRENT_RULE

Retain the `flat / hold / fade / reverse / insufficient` labels as a
transparent descriptive convention. The production classifier was
reproduced audit-side with **0 mismatches across 936 (observation,
horizon) checks**; the two-decimal rounding step changes **zero** labels
on this archive; the 0.70 retention threshold sits inside an
observed-empty interval (0.695816 .. 0.703296) with only 6.2% of
eligible ratios within +/-0.05 of it; the noise floors barely bind
(7 / 5 / 0 flat labels at 5d / 20d / 60d); no leave-out view changes the
modal 20d label; and no data-derived alternative rule is admissible
under the documented conventions. This is a stability finding, not an
accuracy finding - see the non-claims in section 20.

Provenance of this snapshot:

- source database: `events.db`
- database sha256:
  `bcaa7f10773fc3c5ded14164400d16ced8391e986343ede5e7f6e2290d664e82`
  (identical before and after the run; the whole-file hash covers
  volatile non-research tables and is a same-run safety proof, not a
  reproduction key - reproduce via the funnel and denominators below)
- produced from the working tree at commit
  `cf353ab8a314dc23753ccda6a490303fe859f213` (the commit adding this
  file is its immediate child)
- clean-clone caveat: an empty or different archive computes its own
  numbers; every figure below is a dated snapshot of a derivable truth,
  re-derivable with the command in section 21.

## 2. Question and non-claim

Do the current labels describe the archived price paths stably, or are
they materially driven by the unvalidated noise floors, the 0.70
retention threshold, 2dp rounding, the raw-price basis, the horizon
surface or duplicated market stories? No accuracy claim is possible:
there is no independent ground truth for whether a market reaction
truly held, faded or reversed, so this audit characterizes coverage,
boundary concentration and stability only.

## 3. Current production rule (inspected, not assumed)

- noise floors (percent of anchor close): 5d `1.0`, 20d `2.0`, 60d `3.0`
- retention threshold: `abs(final) / abs(peak) >= 0.70` (inclusive)
- label order: insufficient (missing peak/final) -> flat (|peak| below
  floor) -> reverse (opposite signs; final == 0 is NOT a sign flip and
  falls through to fade) -> hold (ratio at or above threshold) -> fade
- peak: largest absolute deviation from the anchor close; ties select
  the earliest bar
- rounding: peak and final are rounded to 2dp inside the composer
  before the label is produced
- basis: raw closes (`auto_adjust = 0`) read from the local
  `price_cache` table; hydration never fetches a provider
- floor coherence: the 1d/5d/20d floors equal
  `validation_evidence._NOISE_*_PCT` (True / True / True); the 60d
  floor exists only in `reaction_profile.py` - the borrowed layer has
  no 60d floor to stay coherent with.

## 4. Consumer map

- **GET /events/{id} + cached POST /analyze restore** - reads the whole
  `reaction_profile_v1` block (available, reason, n_tickers, per-ticker
  profile including basis and hydration_status). No horizon privileged.
  Current.
- **ReactionProfileCard** (analysis-view.tsx) - shows one label per
  ticker via `label_20d ?? label_5d ?? label_60d`. Because composer
  labels are always strings, a 20d `insufficient` wins over a scorable
  5d label; basis is shown; only the first 4 tickers render. Current.
- **GET /diagnostics/track-record** - aggregates hydrated
  `fade_or_hold_label_20d` (insufficient excluded), average `return_5d`
  and `peak_move_20d` per validation status; ticker-weighted, clusters
  pooled. Current, but no mounted frontend consumer (the `lib/api.ts`
  method is an orphan).
- **GET /diagnostics/reaction-profile-stats** - STALE; see section 18.
- **GET /diagnostics/reaction-profile-blockers** - canonical hydrator,
  mutually exclusive blocker buckets; success = hydrated through 20d
  (no 60d bucket). Current.
- **Tests** - `tests/test_reaction_profile.py`,
  `tests/test_reaction_profile_hydration.py`,
  `tests/test_events_reaction_profile_wiring.py` pin the composer,
  hydrator and wiring contracts. Current.

Historical design docs reconciled against production (production wins;
docs are local references):

- `docs/reaction_profile_design.md` s3.6 recommends reusing the
  `relative_return_*` family; the shipped composer emits
  `benchmark_relative_return_*`.
- `docs/reaction_profile_design.md` s6 sketches event-level rollups;
  none are implemented (`build_reaction_profile_v1` is per-ticker plus
  counts).
- `docs/reaction_profile_design.md` s3.5 phrases reverse as
  `sign(final) != sign(peak)`; production explicitly treats
  `final == 0` as NOT a flip.
- `docs/reaction_profile_hydration_plan.md` s2 says `stale` /
  `same_day_fallback` are already on saved ticker blocks; on this
  archive no stored ticker dict carries either key (the hydrator's
  `bool(...)` default of False is what actually runs).

## 5. Eligibility funnel (accepted track-record gate, recomputed)

- archive rows: 180
- excluded - non-thesis stage: 23
- excluded - synthetic seed: 71
- accepted (denominator): **86** (86 + 23 + 71 = 180)
- accepted with stored tickers: 73 (13 events carry no tickers)
- accepted with at least one hydrated reaction profile: 73
- events scorable at 5d / 20d / 60d: **73 / 73 / 29**
- events without a hydrated profile, by exact reason:
  `no_stored_tickers: 13`
- the scorable subset is never used as the accepted denominator;
  unavailable events stay visible above.

## 6. Ticker-level denominators

- stored ticker entries: 329; non-dict 0; missing symbol 0; valid 329
- hydration status: hydrated 312, cache_miss 17
- basis: forward_anchored 312, unscorable 17 (no stale, no
  same-day-fallback rows exist on this archive)
- scorable observations by horizon: 5d **312**, 20d **300**, 60d **70**
- hold/fade-eligible by horizon: 5d 288, 20d 242, 60d 69 (599 total)
- benchmark path available (same-session anchor): 5d 290, 20d 260,
  60d 38
- quarantined benchmark observations: 0

## 7. Hydration and basis coverage

Hydration reads only existing local `price_cache` rows (read-only
mirror of `read_window_no_fetch`; no provider call). Raw
(`auto_adjust=0`) is the production basis; adjusted rows exist for a
large matched subset (5d 312, 20d 286, 60d 0 matched observations),
used here only as a sensitivity lens (section 12).

## 8. Current label distributions

5d (ticker-weighted n=312): hold 199, fade 89, reverse 17, flat 7.
Event-weighted (73 events): hold 0.667, fade 0.256, reverse 0.057,
flat 0.020; 21 events internally unanimous, 52 mixed. Primary-ticker
(71): hold 62, fade 7, reverse 0, flat 2. Cluster-weighted (5
clusters): hold 0.503, fade 0.317, reverse 0.176, flat 0.004.

20d (ticker-weighted n=300): hold 122, fade 120, reverse 53, flat 5;
12 forward observations are insufficient at 20d. Event-weighted (73):
hold 0.465, fade 0.343, reverse 0.176, flat 0.016; 18 unanimous, 55
mixed. Primary-ticker (68): hold 32, fade 27, reverse 9. Cluster-
weighted (5): hold 0.506, fade 0.257, reverse 0.169, flat 0.069.

60d (ticker-weighted n=70): hold 51, fade 18, reverse 1; 242 forward
observations are insufficient at 60d. Event-weighted (29 events): hold
0.686, fade 0.280, reverse 0.034; 26 unanimous. Cluster-weighted
collapses to 2 clusters.

No event-level "winning" label is invented anywhere: event views are
within-event share vectors plus agreement counts.

## 9. Retention-ratio behaviour and transition curve

- eligible observations (labeled hold or fade): 599 (5d 288, 20d 242,
  60d 69); final-zero 0; 204 unique unrounded ratios
- quantiles: min 0.041, p10 0.195, p25 0.522, p50 0.882, p75 1.0,
  p90 1.0, max 1.0
- **182 of 599 ratios are exactly 1.0** (30.4%): the peak sits on the
  final bar, so hold follows by construction; 48.9% of all hold labels
  are such peak-at-end paths. This is a structural property of the
  peak/final definition worth knowing when reading hold shares.
- around 0.70: nearest observed ratio below 0.695816, nearest at/above
  0.703296 (empty interval width 0.0075); within +/-0.02: 22
  observations; +/-0.05: 37 (6.2% of eligible); +/-0.10: 76; exactly
  0.70 after 2dp rounding: 0; labels that depend on rounding at this
  boundary: 0
- transition-curve excerpt (threshold -> hold count -> observations
  changed vs current): 0.6564 -> 395 -> 23; 0.6833 -> 390 -> 18;
  0.6958 -> 373 -> 1; **0.7033 -> 372 -> 0 (current region)**;
  0.7200 -> 369 -> 3; 0.7448 -> 363 -> 9; 0.7941 -> 340 -> 32. Moving
  the threshold +/-0.01 moves at most 3 observations; +/-0.05 moves at
  most ~23 (3.8%). Full curve over all 204 breakpoints in `--json`.
- widest interior plateau in the observed support: 0.3482 .. 0.3790
  (width 0.031) - below the 0.10 minimum visible-plateau width, so no
  admissible alternative threshold exists.
- boundary observations (+/-0.05) name events 2, 3, 7, 11, 12, 17, 25
  (tickers NOC, JETS x4, VLO x2, VNM); all 37 sit in cluster c01,
  which is proportional to c01 holding 79 of 86 events.

## 10. Noise floors

- **5d (floor 1.0%)**: 312 observations; |peak| quantiles p10 2.31,
  p50 4.59, p90 8.52, max 28.89; flat 7; within +/-0.25pp of the
  floor: 5; empty interval around the floor 0.916 .. 1.068; rounding
  flips 0.
- **20d (floor 2.0%)**: 300 observations; p10 4.87, p50 8.79, p90
  21.33; flat 5; within +/-0.25pp: 2; empty interval 1.912 .. 2.087;
  rounding flips 0.
- **60d (floor 3.0%)**: 70 observations; minimum observed |peak| is
  **11.14%**, so the 3% floor never binds on this archive (0 flat, no
  observation anywhere near it). The floor is inert rather than
  miscalibrated: no observed data exists near 3% from which any other
  value could be derived, and changing it would alter zero labels.
- coherence: the 5d/20d floors remain equal to the
  `validation_evidence` layer they were borrowed from.
- scale-bias probe (20d, 89 tickers split by median |peak|): low-half
  flat share 0.030 (168 obs), high-half 0.000 (132 obs) - the expected
  direction for a raw percent floor, small in absolute terms here.
- volatility-scaled floors: pre-anchor cached bars exist for 286 of
  312 forward observations, so the data side is evaluable, but no
  local point-in-time volatility measure module exists and none was
  built here. Future research, not performed (section 19).

## 11. Rounding sensitivity

682 scorable labels compared between the production (2dp-rounded) and
unrounded computation: **0 differences** at any horizon. On this
archive the rounding order is immaterial; no observation sits close
enough to a floor or the threshold for 2dp rounding to flip it.

## 12. Raw vs benchmark-relative and adjusted-basis sensitivity

Benchmark-relative (audit-only lens: ticker cumulative return minus
benchmark cumulative return, same anchor/horizon, same rule; the audit
additionally requires both windows to open on the same session -
production's positional convention does not check dates; 0 misaligned
pairs were found):

- matched: 5d 290, 20d 260, 60d 38; unavailable: 22 / 40 / 32;
  quarantined 0
- label changes: 5d **163 of 290 (56%)**, 20d **173 of 260 (67%)**,
  60d 21 of 38; sign-flip (reverse-involving) changes 35 / 51 / 1;
  hold/fade swaps 46 / 68 / 0
- largest 20d flows: fade->hold 57, fade->flat 35, reverse->hold 27,
  hold->flat 14.

The raw-tape labels are strongly basis-dependent. This is a scope
property, not a defect: the production label deliberately reads the
raw tape, and the benchmark-relative read answers a different question
(the existing F-arc sector-relative work covers that lens). Consumers
must not read a raw hold as market-relative outperformance.

Adjusted-basis (cached `auto_adjust=1` rows, same rule): matched 5d
312, 20d 286, 60d 0; label changes 23 (7.4%) at 5d and 14 (4.9%) at
20d (largest flows: 20d reverse->fade 8; 5d hold->fade 6, reverse->hold
4). Split/dividend adjustment shifts a modest label share; production
binds to raw closes so stored labels stay historical facts.

## 13. Horizon transitions and frontend-priority implications

- 5d vs 20d: 300 matched observations, only **137 (46%) agree**
  (largest flows hold->fade 68, hold->reverse 37, fade->hold 28).
- 20d vs 60d: 70 matched, **1 agrees** (fade->hold 44, hold->fade 17).
  Labels are strongly horizon-specific by construction.
- Frontend 20d-first display: all 329 ticker rows display the 20d
  label (the null-coalescing chain never reaches 5d/60d because labels
  are always strings). 12 rows display `insufficient` while the 5d
  label is scorable; 192 of 329 rows (58%) hide a disagreeing label
  at another available horizon; 60d contributes zero visible
  information under the current priority.
- `/diagnostics/track-record` (20d, ticker-weighted, insufficient
  excluded): hold 122, fade 120, reverse 53, flat 5 - and **96% of
  those labeled observations come from the single largest market-story
  cluster**, so its histogram describes essentially one story cluster,
  ticker-multiplied.

Consumer implications only; no UI or route was edited, and no UI
priority change is recommended as part of this audit's outcome.

## 14. Event-, ticker-, primary- and cluster-aware results

All four lenses agree on the modal 20d label (hold) and none overturns
the interpretation: ticker 0.41/0.40/0.18/0.02 (hold/fade/reverse/flat
shares), event 0.47/0.34/0.18/0.02, primary 0.47/0.40/0.13/0.00,
cluster 0.51/0.26/0.17/0.07. The 86 accepted events group into 7
market-story clusters under the canonical K2 rules re-derived live
(sizes: c01 79, c02 2, five singletons; reconciles with the
event-date-quality lens: True). Cluster counts are an independence
caution, not an effective sample size.

## 15. Leave-out tests

Event-weighted 20d shares, base hold 0.465 / fade 0.343 / reverse
0.176 / flat 0.016 (modal hold, 73 events):

- leave-one-event-out (73 runs): hold range 0.458..0.471; no modal flip
- leave-one-year-out: unavailable - all scorable events are 2026
- leave-one-cluster-out (5 runs): hold 0.458..0.517; no modal flip;
  without the largest cluster the shares become hold 0.517 / fade
  0.233 / reverse 0.167 / flat 0.083 (6 events remain - thin but not
  contradictory)
- no same-day fallback / no quarantined rows: identical to base (no
  such observations exist)
- multi-ticker events only: identical (all 73 scorable events have
  2+ valid tickers)
- primary vs all-ticker (20d): max share delta 0.064; same modal label.

## 16. Candidate comparison

No candidate rule entered. Admissibility required a visible interior
plateau at least 3x wider than the empty interval around the current
value with at least 5 observations pressing the boundary; the widest
observed retention plateau is 0.031 wide (minimum 0.10) and the noise
floors sit in sparse regions (5d: 5 observations within +/-0.25pp;
20d: 2; 60d: 0). The current rule is therefore the only rule in the
comparison. Thresholds were never tuned toward balanced label counts,
`validation_status_v2`, or any narrative.

## 17. Recommendation

**KEEP_CURRENT_RULE.** Guard inputs, all printed for dispute:
equivalence_mismatches 0; accepted_n 86; events_scorable_20d 73;
eligible_holdfade_total 599; boundary_share_pm005 0.062;
rounding_flip_share 0.0; loeo_modal_flip False; loco_modal_flip False;
admissible_candidates 0. Audit conventions: minimum 15 scorable 20d
events; minimum 15 hold/fade-eligible observations; dense-boundary
share 0.30; rounding-flip share 0.10; candidate admissibility as in
section 16. Retaining the rule keeps a transparent descriptive
convention; it does not certify accuracy.

## 18. Stale diagnostics contract (recorded, not repaired)

`GET /diagnostics/reaction-profile-stats` still claims the archive
stores only per-ticker scalar returns and that
`compute_reaction_profile` "cannot actually run" on archived rows,
classifying readiness via `_ticker_has_return` into
`scalar_returns_only` / `unscorable` - a vocabulary that is not in
`REACTION_PROFILE_BASES`. Since hydration shipped, raw close paths
hydrate from the local `price_cache` (as `/diagnostics/track-record`
and `/diagnostics/reaction-profile-blockers` already do), so the
endpoint understates real readiness. It does not affect this audit
(the canonical hydrator was used directly). Bounded future consumer
debt; `routes/diagnostics.py` was not edited.

## 19. Unavailable analyses

- volatility-scaled noise floors: pre-anchor data exists (286/312
  observations) but no local point-in-time volatility module exists
  and none was built; future research, not performed
- leave-one-year-out: fewer than two event-date years in the
  20d-scorable set
- 60d floor calibration: no observed |peak| anywhere near 3%, so no
  data-derived alternative is possible; the 60d surface is also thin -
  only 29 of 86 accepted events reach a scorable 60d window
- independent ground-truth labels for hold/fade/reverse: none exist;
  accuracy calibration is permanently out of scope for this data.

## 20. Permanent non-claims

- No claim that any label is accurate: there is no independent ground
  truth for whether a reaction truly held, faded or reversed. This
  audit characterizes stability, coverage and boundary behaviour only.
- No predictive validation is performed or implied.
- Labels are descriptive tape reads, not thesis outcomes; no mapping
  from hold/fade/reverse to validated/contradicted is asserted, and
  none should be inferred.
- Cluster counts are an independence caution, not an effective
  statistical sample size.
- The benchmark-relative and adjusted-basis lenses are audit-only
  sensitivity views, not proposed production rules.
- Not a recommendation, forecast, or trading signal; no buy or sell
  framing exists or is implied anywhere in this audit.

## 21. Reproduce (read-only)

```
python -m scripts.reaction_profile_calibration_report --db-path events.db
python -m scripts.reaction_profile_calibration_report --db-path events.db --json
```

The command opens the database over `mode=ro` connections only, makes
no provider/network/paid call, writes nothing, and is deterministic
across repeated runs (verified by byte-identical JSON on back-to-back
runs). Detailed per-observation rows, the full transition curves and
the complete transition matrices live in the `--json` output only.

## 22. Falsifier / reopen condition

Reopen this calibration when any of the following holds: the accepted
archive grows or changes enough that a guard input in section 17
crosses its documented floor; the equivalence check reports any
mismatch; the production constants in `reaction_profile.py` change;
the 60d surface gains materially more scorable events; or a
point-in-time volatility measure is built locally (which would make
the volatility-scaled floor evaluable end to end).
