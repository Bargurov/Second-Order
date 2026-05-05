# Reaction Profile — Data Contract Sketch

**Status:** sketch — no schema, endpoint, `market_check`, or UI changes
proposed in this document.
**Scope:** define the data contract for the reaction profile so the implementer
has unambiguous semantics for every field. Computation rules reference
existing modules; no new fetch path, no provider call.

## 1. Layer model

The reaction profile lives at **two layers**:

- **Ticker-level (primary).** All eight fields below are first defined per
  ticker. This is the contract this document pins down.
- **Event-level (derived rollups).** Optional aggregations across the event's
  `market_tickers`. Sketched in §6 but kept secondary so per-ticker semantics
  stay clean. There is no single event-level `peak_move` or
  `time_to_peak` — peaks of opposite-direction tickers do not aggregate
  meaningfully (see §6 for what is rollup-able and what is not).

This split mirrors the existing system: `market_check.py` already produces
per-ticker `return_1d/5d/20d`, `volume_ratio`, `relative_return_1d/5d/20d`;
event-level reads sit on top via `validation_outcome.score_weighted_evidence`.
The reaction profile follows the same pattern.

## 2. Conventions (apply to every field)

- **Anchor.** Event-date close (`iloc[0]` of the `_fetch_since` series), same
  as `market_check._check_one_ticker` already uses. When the event is
  `same_day_fallback` (event-day == latest available bar), only `return_1d`
  has an anchor; longer-horizon fields are `None` (see §4 edge cases).
- **Sampling.** **Close-to-close only.** No intraday high/low. `peak_move`
  scans daily closes in the window; `time_to_peak` is in **trading bars**,
  not calendar days.
- **Sign.** Returns are **signed raw moves** (positive = price up), matching
  `return_1d/5d/20d`. The reaction profile does **not** rotate signs into the
  thesis direction. Thesis-direction interpretation lives in
  `fade_or_hold_label` (and downstream in `validation_evidence.py`).
- **Units.** Percent (e.g. `return_5d = 1.23` means `+1.23%`), rounded to 2dp,
  matching the existing JSON shape from `market_check.py:1086-1101`.
- **Source.** `price_cache` only. **No provider calls** in the reaction-profile
  composer. A cache miss for any required bar produces `None` for the
  affected field, never a fetch.
- **Determinism.** Pure composer. Same input bars → same output dict. No
  hidden clock reads.

## 3. Field contract (ticker level)

Each field is a row in the per-ticker reaction-profile dict, additive to the
existing `_check_one_ticker` output.

### 3.1 `return_1d` / `return_5d` / `return_20d`

| Aspect | Spec |
|--------|------|
| Type | `float \| None` |
| Units | percent, 2dp |
| Source | existing `market_check._check_one_ticker` (no change) |
| Computation | `_pct_forward(closes, N)` from event-anchor close (`iloc[0]`) to `iloc[N]`. Already shipped. |
| Null when | fewer than `N+1` closes available since anchor; sanity-bound rejected by `_sanitize_returns`; provider failure |
| New work | **none** — these are surfaced as-is in the profile to give consumers a single read. |

### 3.2 `return_60d` *(new)*

| Aspect | Spec |
|--------|------|
| Type | `float \| None` |
| Units | percent, 2dp |
| Source | `price_cache` series already extends to `_DEFAULT_PERIOD_DAYS = 93` calendar days (`price_cache.py:87`); 60 trading bars ≈ 84 calendar days, fits inside the existing default fetch window. **No window extension needed.** |
| Computation | `_pct_forward(closes, 60)` — same primitive as the existing horizons. |
| Null when | fewer than 61 closes available since anchor (most events younger than ~12 weeks); same sanity-bound and provider-failure rules as the other horizons. |
| Notes | Independent nullability from 5d/20d. A missing 60d does not invalidate the rest of the profile. |

### 3.3 `peak_move` *(new)*

| Aspect | Spec |
|--------|------|
| Type | `float \| None` |
| Units | percent, 2dp |
| Sign | **Signed raw move** (positive = price moved up from anchor). Same convention as `return_5d`. Thesis-direction interpretation belongs to `fade_or_hold_label`, not here. |
| Window | Computed within the **same window as the longest available horizon**. Concretely: produce **three independent fields** — `peak_move_5d`, `peak_move_20d`, `peak_move_60d` — each scoped to its horizon, each independently nullable. This avoids the "one missing 60d bar nukes the field" failure mode and gives consumers a peak read aligned to whichever horizon they're looking at. |
| Computation | For each horizon `N`: `peak_move_N = max(closes[1:N+1], key=abs) / closes[0] - 1`, expressed in percent. (Largest absolute deviation from the anchor close, in either direction; sign retained.) |
| Null when | the corresponding `return_N` is null (same data dependency); horizon window has fewer than 2 forward bars. |
| Notes | "Largest absolute deviation" deliberately picks the magnitude extreme regardless of direction, so a ticker that whipsawed 4% up then settled flat reports `peak_move_5d = +4.0`. The fade/hold label uses this against the terminal return to decide whether the move stuck. |

### 3.4 `time_to_peak` *(new)*

| Aspect | Spec |
|--------|------|
| Type | `int \| None` |
| Units | **trading bars** (1 = next-session close, 5 = one trading week) |
| Window | Three independent fields: `time_to_peak_5d`, `time_to_peak_20d`, `time_to_peak_60d`, each scoped to the same window as the corresponding `peak_move_N`. |
| Computation | For each horizon `N`: `time_to_peak_N = argmax(abs(closes[1:N+1] - closes[0])) + 1`. The `+1` makes the value 1-indexed in trading bars, so `time_to_peak_5d = 1` means the move peaked at the first session after the event. |
| Null when | corresponding `peak_move_N` is null; window has fewer than 2 forward bars. |
| Notes | When two bars tie on absolute deviation, take the **earliest** — preserves the "did it peak fast?" question. |

### 3.5 `fade_or_hold_label` *(new)*

| Aspect | Spec |
|--------|------|
| Type | `str` ∈ `{"hold", "fade", "reverse", "flat", "insufficient"}` |
| Window | Per-horizon: `fade_or_hold_label_5d`, `fade_or_hold_label_20d`, `fade_or_hold_label_60d`. Each consumes the matching `peak_move_N` and `return_N`. |
| Computation | Given `peak = peak_move_N`, `final = return_N`, and noise floor `noise = _NOISE_NS_PCT` (already pinned in `validation_evidence.py`: 0.5% / 1.0% / 2.0% for 1d/5d/20d; for 60d propose `_NOISE_60D_PCT = 3.0`): <br>1. If `peak` is None or `final` is None → `"insufficient"`. <br>2. Else if `abs(peak) < noise` → `"flat"` (the move never crossed noise; nothing to fade or hold). <br>3. Else if `sign(final) != sign(peak)` → `"reverse"` (the tape gave back the move and crossed zero). <br>4. Else if `abs(final) / abs(peak) >= 0.7` → `"hold"` (kept ≥70% of the peak move in the same direction). <br>5. Else → `"fade"` (gave back >30% of the peak, did not flip). |
| Thresholds | `0.7` retention boundary is a **starting calibration**, pinned as a module constant (`_FADE_HOLD_THRESHOLD = 0.7`) so it can be tuned in one place. Documented here as the contract's initial value, not as immutable. |
| Notes | This field is the only one in the reaction profile that depends on a threshold judgment; the rest are direct numeric reads. The five-value vocabulary is exhaustive and mutually exclusive. |

### 3.6 `benchmark_relative_return` *(per horizon)*

| Aspect | Spec |
|--------|------|
| Naming | **Reuse existing field family.** `relative_return_1d`, `relative_return_5d`, `relative_return_20d` are already produced by `market_check._check_one_ticker:1099-1101`. **Add `relative_return_60d`** to extend the family. Do **not** introduce a singular `benchmark_relative_return` — it would shadow the existing per-horizon fields and force callers to choose between two parallel naming conventions. The task brief's singular form is interpreted as "the family", not a single new field. |
| Type | `float \| None` |
| Units | percent (ticker return minus benchmark return at the same horizon), 2dp |
| Source | `relative_move.classify_relative_move` (existing). For the new 60d field, extend the same composer; no new benchmark resolution logic. |
| Benchmark | Per `market_math.resolve_benchmark(ticker)` — sector ETF when mapped, SPY fallback. |
| Null when | Either the ticker `return_N` or the benchmark `return_N` is null; **OR the benchmark is quarantined** (see §4.5). The benchmark-quarantine flag must propagate so a quarantined SPY print doesn't silently corrupt every ticker's relative read. |
| Notes | This is the only field whose nullability depends on a *second* ticker (the benchmark). The existing `validation_quality` field on the per-ticker block already carries the benchmark health signal; the reaction profile passes it through without restating it. |

## 4. Edge cases — explicit behavior

### 4.1 No tickers on the event

- `event.market_tickers = []` → no per-ticker reaction profiles to compute.
- Event-level rollups (§6) return their `insufficient` shape (empty lists,
  null aggregates).
- Composer never raises; never partial-fills.

### 4.2 Missing price data (cache miss for some bars)

- Per-field nullability is the contract: each horizon's fields populate
  independently. A missing 60d bar nulls only the `*_60d` family; 5d / 20d
  fields stay valid.
- Implementer must **not** call the provider to backfill missing bars from
  inside the reaction-profile composer. Cache miss → `None`. The market-check
  freshness path is the only place that should refill the cache.

### 4.3 Event too young (`same_day_fallback`)

This is the dominant edge case for fresh events.

- `same_day_fallback` is already detected by `market_check.py:914-917`. When
  it fires, `return_1d` is computed via rolling `_pct` (anchor = prior close),
  and `return_5d` / `return_20d` are forced to `None`.
- The reaction profile inherits this exactly. `peak_move_5d/20d/60d`,
  `time_to_peak_5d/20d/60d`, and `fade_or_hold_label_5d/20d/60d` are all
  `None` / `"insufficient"` for a same-day-fallback ticker — the forward bar
  series doesn't exist yet to scan for a peak.
- `return_1d` and (only when computed against a prior close) any same-day
  derived signal still surfaces.
- A `reaction_profile_basis` flag (`"forward_anchored"` /
  `"same_day_fallback"` / `"unscorable"`) sits on the per-ticker profile so
  consumers can tell why fields are null without re-deriving the cause.

### 4.4 Contradictory ticker directions

- Reaction profile is **per-ticker**, so contradictory directions across the
  basket do not cause any per-ticker field to be null or invalid. Each ticker
  reports its own move regardless of what other tickers in the same event are
  doing.
- At the event-level rollup (§6), contradictory directions surface as
  `direction_consistency = "split"` and the basket-weighted return aggregate
  is reported but flagged as low-conviction. **No event-level `peak_move`** is
  computed when the basket is split — averaging a +5% peak with a −5% peak
  produces a 0% number that misrepresents both.

### 4.5 Benchmark quarantine

- `benchmark_quarantine.compute_benchmark_quarantine` returns
  `data_quality ∈ {"ok", "warn", "quarantined"}`. When `"quarantined"`, the
  benchmark print is definitively bad and **must not** be used.
- All `relative_return_N` fields in the reaction profile are `None` when the
  benchmark is quarantined for that horizon, regardless of whether the ticker
  return itself is valid.
- The per-ticker block's existing `validation_quality` field carries this
  signal already; the reaction profile composer reads it and propagates
  rather than re-quarantining.

### 4.6 Stale / delisted tickers

- `market_check._check_one_ticker:939-945` already sets `stale = True` when
  the last bar is older than `_STALE_TICKER_CALENDAR_DAYS`. The reaction
  profile composer reads this flag and emits **all forward-looking fields
  as `None`** — a delisted ticker's "peak move" since the event is undefined
  in any meaningful sense.
- `reaction_profile_basis = "stale"` distinguishes this from
  `"unscorable"` (which means data is just missing).

### 4.7 Sanity-rejected returns

- `_sanitize_returns` already drops implausibly-large returns from corrupt
  source bars. Whatever it returns is what the reaction profile sees. Rejected
  returns surface as `None` and are treated like any other missing horizon.

### 4.8 Future-dated events

- `event_date` strictly after `now` → `_fetch_since` returns no rows; the
  composer returns the no-data shape, identical to a stale ticker. Never
  raises.

## 5. Field placement summary

All fields below are **per-ticker**, attached to each entry in
`event.market_tickers[]`:

```
return_1d, return_5d, return_20d                    (existing — reused)
return_60d                                           (new)
relative_return_1d, relative_return_5d,              (existing — reused)
  relative_return_20d
relative_return_60d                                  (new)
peak_move_5d, peak_move_20d, peak_move_60d           (new)
time_to_peak_5d, time_to_peak_20d, time_to_peak_60d  (new)
fade_or_hold_label_5d, fade_or_hold_label_20d,       (new)
  fade_or_hold_label_60d
reaction_profile_basis                               (new)
```

Storage: same JSON blob as the existing per-ticker dict. **No schema column
is added** — `market_tickers` is already a free-shape JSON list per the
existing `market_check.py` writer.

## 6. Event-level rollups (sketch — secondary)

Defined here so the implementer doesn't reinvent them, but **subordinate to**
the per-ticker contract above. The event-level layer is read-only over the
per-ticker fields.

| Rollup | Computed when | Definition |
|--------|---------------|------------|
| `basket_return_5d/20d/60d` | basket has ≥2 tickers with non-null horizon | tier-weighted average of per-ticker `return_N`, using the same weights as `validation_outcome._tier_weight` (primary 1.0, secondary 0.7, signal/rejected 0.0). |
| `basket_relative_return_5d/20d/60d` | as above | tier-weighted average of `relative_return_N`. |
| `direction_consistency` | always | `"aligned"` if all scorable per-ticker returns at the chosen horizon share a sign; `"split"` if mixed; `"insufficient"` if <2 scorable. |
| `median_time_to_peak_5d/20d/60d` | basket is `aligned` AND ≥2 tickers populated | median of per-ticker `time_to_peak_N` across primary-tier tickers; null when basket is `split` (no shared peak to time). |
| `basket_fade_or_hold_5d/20d/60d` | basket is `aligned` AND `basket_return_N` is non-null | apply the per-ticker `fade_or_hold_label` decision tree to `(basket_peak_proxy, basket_return)` where `basket_peak_proxy` is the tier-weighted average of per-ticker `peak_move_N`. **Not computed when `direction_consistency = "split"`** — averaging opposing peaks is meaningless. |

Explicitly **not** rolled up at event level: `peak_move`, `time_to_peak`
(except median above), `reaction_profile_basis`. These are inherently
per-ticker primitives.

## 7. Tests required before implementation

These tests must exist (and fail against the current implementation) before
the composer ships. All fixtures are dict / array literals — no DB, no
network, no provider calls.

### 7.1 Per-field unit tests (new file: `tests/test_reaction_profile.py`)

For each field in §3, fixture-driven tests covering:
- happy path (forward bars present, peak interior to window, fade vs hold)
- nullability (missing bar at horizon N nulls only that horizon's family)
- sign convention (a price drop produces negative `peak_move`, not positive)
- units (percent for returns, trading-bar count for `time_to_peak`)
- 2dp rounding consistency with existing `return_5d` shape

### 7.2 `peak_move` / `time_to_peak` algorithmic tests

- Peak at first bar (`time_to_peak_5d == 1`).
- Peak at last bar in window (`time_to_peak_5d == 5`).
- Tied peak magnitudes — assert **earliest** bar is selected.
- Whipsaw: ticker goes +4%, then settles to 0% by `return_5d`. Assert
  `peak_move_5d ≈ +4.0`, `time_to_peak_5d` is the bar where +4 occurred,
  `fade_or_hold_label_5d == "fade"` (final/peak < 0.7).
- Reversal: ticker goes +3% intraday closes 1-2, then closes 4-5 at -3%.
  Assert `fade_or_hold_label_5d == "reverse"`, `peak_move_5d` is whichever
  has greater absolute magnitude.

### 7.3 `fade_or_hold_label` decision-table tests

Direct assertions against the §3.5 rules — one fixture per branch:
- `"insufficient"` when peak or final is None
- `"flat"` when `|peak| < noise` for the horizon
- `"reverse"` when signs differ
- `"hold"` at exactly the threshold (`final/peak == 0.7`) — pin the
  inclusive-boundary choice
- `"fade"` just below the threshold (`final/peak == 0.69`)

### 7.4 Edge-case tests (one per §4 sub-case)

- No tickers → empty rollup, no per-ticker dicts.
- Cache miss for one horizon → only that horizon's family null; others valid.
- `same_day_fallback` → `reaction_profile_basis == "same_day_fallback"`,
  every horizon-N field null, `return_1d` populated.
- Mixed-direction basket → `direction_consistency == "split"`,
  `median_time_to_peak_*` and `basket_fade_or_hold_*` null.
- Quarantined benchmark → `relative_return_N` null at the affected horizon,
  ticker `return_N` still populated.
- Stale ticker → `reaction_profile_basis == "stale"`, all forward fields null.
- Sanity-rejected return → field null, no exception.
- Future-dated event → no-data shape, no exception.

### 7.5 Determinism tests

- Same input bars → same output dict, byte-equal across two invocations.
- No clock reads inside the composer (assert by patching `datetime.now` to
  raise — composer must still produce results from cached bars).

### 7.6 No-provider-call test

- Mock the provider seam (`market_data.get_provider()` or whichever entry
  point the price cache exposes) to raise on any call. Run the reaction
  profile composer over a fixture event whose tickers have full cached bar
  series. Assert: no provider invocation, full profile populated.
- Same setup with a deliberately incomplete cache: assert the composer
  produces nulls where bars are missing rather than triggering a fetch.

### 7.7 Event-level rollup tests

- Aligned basket of 3 tickers → `basket_return_5d` matches hand-computed
  tier-weighted average; `direction_consistency == "aligned"`;
  `basket_fade_or_hold_5d` derived from basket aggregates.
- Split basket → consistency flag flips; rollups requiring alignment go null.
- Single-ticker basket → rollups requiring ≥2 tickers return `insufficient`.

## 8. Out of scope (intentionally)

- DB schema migrations. The new fields ride inside the existing per-ticker
  JSON dict; the `market_tickers` column does not change shape.
- Endpoint changes. Consumers that read `event.market_tickers[i].return_5d`
  will see the new sibling fields automatically; no route changes required.
  Specifying which routes surface the new fields to the UI is a separate
  product decision.
- `market_check` modifications. The composer is **read-only** over the per-
  ticker block already produced by `_check_one_ticker`. Adding the 60d
  horizon needs `_fetch`/`_fetch_since` to return enough bars (which the
  existing `_DEFAULT_PERIOD_DAYS = 93` already provides), but does not
  modify the fetch path.
- UI rendering. Whether `fade_or_hold_label_5d == "fade"` shows as a chip,
  pill, or text glyph is for the frontend layer.
- Provider / yfinance / LLM integration. None of these are touched.
- Calibration of `_FADE_HOLD_THRESHOLD` and `_NOISE_60D_PCT`. The values in
  this doc are starting points; tuning waits until the composer has produced
  enough rows that a calibration script (analogous to
  `tools/event_age_policy_validation.py`) has real data to chew on.

## 9. Open questions (defer to implementation review)

- **Where does the composer live?** Two reasonable homes:
  (a) extend `market_check._check_one_ticker` to emit the new fields inline
  (couples reaction-profile semantics to the fetch path);
  (b) new module `reaction_profile.py` that reads the per-ticker block as
  input (cleaner separation, matches the `validation_outcome` /
  `validation_evidence` pattern). Default recommendation: (b).
- **`reaction_profile_basis` enum extension.** The starter values are
  `"forward_anchored" / "same_day_fallback" / "stale" / "unscorable"`.
  If the implementer finds a fifth case during build-out, it should be
  added here, not in code, before merging.
- **Should `time_to_peak` be reported in trading bars or calendar days?**
  This doc commits to trading bars for parity with `return_Nd` (which counts
  trading sessions). If the desk prefers calendar-day phrasing in the UI,
  conversion happens at the rendering layer, not in the composer.
