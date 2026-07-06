# J1B engine readiness - pre-outcome pipeline verification (Mission J)

Contract: `j1b-preoutcome-engine-v1` (`scripts/j1b_outcome_engine.py`).
This is an ENGINEERING note, not an outcome artifact: the complete frozen
12-cell J1 statistical pipeline was built and verified on deterministic
SYNTHETIC fixtures only, before any real Mission J outcome exists. No real
J1 value appears here or anywhere in the engine's outputs; every synthetic
run is stamped `SYNTHETIC ENGINE VERIFICATION - NOT RESEARCH EVIDENCE`.

## Contracts implemented (traced from the tracked frozen artifacts)

- Exact 12-cell manifest and order (J0 section 13 J1 table), no
  thirteenth cell, no OPEC cell; 2s10s frozen as the curve-shape
  contextual layer outside every panel (J0 section 12.2).
- Symmetric membership-free response extraction: raw simple return
  `P[t+1]/P[t] - 1`; rates raw change `y[t+1] - y[t]`; frozen 252/20
  rolling-beta abnormal return (OLS with intercept, estimation returns
  r_j for j in {i-272..i-21}, 20-session embargo, 1d AR at session i+1;
  J0 section 9). No membership argument exists on any response function.
- Frozen basis policy: adjusted/adjusted preferred, matched raw/raw as
  the only disclosed fallback, cross-basis pairs impossible (BasisError).
- Mid-rank percentile and MEMP exactly per I0 section 13 / I2B (hand
  tests: below-all, above-all, single tie, repeated ties, all-equal,
  duplicate preservation; median odd/even/tie cases).
- Era-matched placement calibration per I2C-A mechanics: B = 2,000, seed
  20180101, one numpy `default_rng` per frozen policy, per-year
  event-count matching on the CELL-SPECIFIC available-event year vector,
  uniform draws without replacement from sorted year pools, self-included
  reference percentiles precomputed once, observed MEMP external over
  denominator exactly 2,000, mid-rank tie rule, pool shortfall fails
  loudly (CalibrationInfeasibleError). Global RNG activity cannot affect
  results (local generator; tested).
- Four frozen node states with inclusive [0.25, 0.75] boundaries,
  exhaustive and mutually exclusive (grid-tested).
- Role modifiers over the frozen panels only (2Y+SHY; KRE/IAT/KBE;
  XLF/VFH), primary-anchored per J0 section 6.5, reproducing the J0
  section-5 worked example (KRE ELEVATED + alternates ordinary ->
  PROXY-SPECIFIC). No edge state exists anywhere in the engine or its
  outputs (tested against all five J3-owned names).
- Stability overlays: LOYO removes each year's events AND ordinary
  reference dates (the pinned I0 section-15 / I2C-B convention); LOEO
  removes one event with the reference untouched; F3 uses the canonical
  greedy earliest-first disjoint geometry (starts >= span+1). Overlays
  re-rank precomputed responses and never rewrite the node state.
- Deterministic frozen-order report renderer: all 12 cells, panel
  summaries, contextual section; no highlighting, no value ordering, no
  hypothesis-test vocabulary; byte-identical regeneration (tested).

## Fail-closed execution boundary

`run_engine` refuses to execute without an authorization object. Live
authorization can only be minted by `authorize_from_verification`, which
consumes the failure list of the externally owned J1A frozen-input
verifier (this module implements NO competing hash verification and
hardcodes no input hash); a forged authorization object without the
module-private stamp is rejected, as is a failed or non-empty
verification result. Synthetic runs require an explicit
`SyntheticFixtureAuthorization` carrying the exact banner string, are
rejected unless the inputs are synthetic-flagged, and stamp every output
with the banner; live authorization symmetrically rejects
synthetic-flagged inputs. The frozen J1B gate rule (J1A freeze manifest)
is therefore structural: no response value can be computed on unverified
inputs through any public path.

## Load-bearing ambiguity found and RESOLVED (history preserved)

J0 section 4.1 inherits the I2C-A calibration semantics "verbatim" (one
local deterministic RNG, seed 20180101, fixed consumption order), but
I2C-A's consumption order is defined over Mission I's family-by-horizon
groups with one drawn calendar shared across that group's four metrics.
J0 did not define how that single-stream order maps onto the 12
heterogeneous J1 cells. The original engine build therefore implemented
two candidate readings behind a mandatory explicit `rng_policy` argument
and refused to default (historical alternatives, no longer selectable:
a fresh seed-20180101 generator per geometry group vs one stream in
manifest order).

The ambiguity is now RESOLVED by the outcome-blind J0 post-publication
clarification `grouped_shared_calendar_single_stream`, and the runtime
fork has been REMOVED: the engine implements exactly one policy - one
local `numpy.random.default_rng(20180101)` stream for the full family,
three frozen placement groups in fixed order (rolling-beta equity cells
1-5; raw ETF returns cells 6-9 and 12; Treasury/rates cells 10-11),
exact identity-set equality asserted per group before any draw
(eligible ordinary-anchor identities, available-event identities,
event-year vectors - counts alone are insufficient and any mismatch
raises CalibrationGeometryError with no split/fallback/reseed), one
drawn calendar reused across every cell in a group, and the stream
continuing across groups without reset. No `rng_policy` parameter,
selector constant, or alternate seed survives in the engine; tests pin
the group structure, the identity assertions, the shared calendars, and
the continuing stream against an independent replica of the frozen draw
semantics. MEMPs, node-state rules, overlays, and everything upstream
of the placement draw were always policy-independent.

A second, non-blocking convention is documented in code: role modifiers
are computed primary-anchored (a faithful mechanical rendering of J0
section 6.5 that reproduces the section-5 worked example); J3 should
confirm this rendering before any edge adjudication consumes it.

## Tests and synthetic verification

- 78 tests, RED-first (the suite was watched failing before the engine
  existed), all GREEN. Coverage: manifest/scope (6), execution gate (9),
  responses/basis/geometry (12), numerical safety (4), mid-rank/MEMP
  (9), substrate/denominators (7), calibration (9), node states (3,
  grid-exhaustive), panels (5), overlays (6), rendering (6), tripwires
  (3, minus overlap).
- Full synthetic end-to-end smoke: 12 cells, responses built once,
  B = 2,000 calibration, states, modifiers, overlays, frozen-order
  render. Timing on this machine: substrate 0.99 s, calibration 0.18 s,
  total 1.20 s - no `2000 x response reconstruction` architecture
  exists (asserted structurally: response-evaluation counter is frozen
  after substrate build).
- Tripwires: the engine module contains no provider/network/cache/file
  I/O token (statically tested), runs with sockets disabled, performs no
  file writes, and the synthetic suite never opens a canonical J1A
  input (the isolated worktree contains no local caches at all).

## Integration gate still pending

Live J1B remains blocked, by design, on: (1) the J1A frozen-input
verification gate wired through `authorize_from_verification`; (2) the
read-only loader that converts the frozen caches into `EngineInputs`.
The cross-cell RNG policy is no longer a blocker: it is frozen by the
outcome-blind J0 clarification and hard-wired in the engine. No real
outcome report exists; `stats/J1B_*.md` outcome artifacts are
deliberately not created by this slice.
