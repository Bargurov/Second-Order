# I1 — Ordinary-Period Candidate Universe and Funnel

Version `i1-candidate-universe-v1` — mechanical execution of the frozen `i0-v1` baseline protocol (`stats/I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md`).

This report records **only** how the ordinary-date reference universes, exclusion sets, and denominator funnels were constructed. It does **not** compute the event-versus-ordinary comparison, and reads no price close values — every number below is a date, a session index, or a count.

The two families keep entirely separate ledgers: their denominators, exclusion sets, and funnels are never pooled.

## FOMC lane

- Primary asset `KRE`; market benchmark `SPY`; sector benchmark `XLF`.
- Joint (triple-intersection) sessions: **2385** (`2017-01-03` → `2026-06-30`); era 2018–2025 sessions: **2011**.
- Raw-only sessions (adjusted basis unavailable): **0** — F3 basis is uniformly adjusted, no cross-basis pairing.
- Study denominator (promoted events): **65**.
- Exclusion set: the complete 65-event frame → **65** anchor sessions.

| horizon | era | est cut | fwd cut | gap cut | excl cut | eligible | non-overlap blocks | status |
|---|---|---|---|---|---|---|---|---|
| 1d | 2011 | 0 | 0 | 0 | 195 | **1816** | 927 | feasible |
| 5d | 2011 | 0 | 0 | 0 | 712 | **1299** | 233 | feasible |
| 20d | 2011 | 0 | 0 | 0 | 2011 | **0** | 0 | structurally_infeasible |

Funnel order (I0 §17): era → estimation (≥60 prior) → forward (≥h ahead) → interior-gap → known-date exclusion; each stage sieves the prior survivors, so era − cuts = eligible at every horizon. The non-overlap block count is the size of the canonical set of disjoint response windows `[t, t+h]` — a deterministic greedy earliest-first packing on the eligible session indices, where two windows share no session only if their starts are at least `h+1` apart (I0 §8; a shared endpoint at distance `h` is overlap). It is **not** `eligible // h` (which ignores index positions and, at `h=1`, returns the full count), and **not** an independent, effective, or degrees-of-freedom sample size.

The 20d horizon is **structurally infeasible**: with the estimation and forward gates removing nothing in-era, the exclusion geometry alone leaves zero eligible sessions — a pre-declared calendar fact (I0 §8), not a data gap and not rescued by any substitute date.

Eligible-session count by year:

| horizon | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| 1d | 227 | 228 | 226 | 228 | 227 | 226 | 228 | 226 |
| 5d | 163 | 164 | 157 | 164 | 163 | 162 | 164 | 162 |
| 20d | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## OPEC lane

- Primary asset `XOP`; market benchmark `SPY`; sector benchmark `XLE`.
- Joint (triple-intersection) sessions: **2385** (`2017-01-03` → `2026-06-30`); era 2018–2025 sessions: **2011**.
- Raw-only sessions (adjusted basis unavailable): **0** — F3 basis is uniformly adjusted, no cross-basis pairing.
- Study denominator (promoted events): **32**.
- Known-date exclusion register (`opec-known-date-exclusion-register@i0-v1`): **41** calendar dates = 38 discovery-ledger source records + 3 named non-ledger dates (`2020-03-06`, `2022-12-04`, `2025-05-28`) → **39** anchor sessions.
  The register is a contamination-control set. Its dates are **never** study-denominator members: the OPEC study sample stays exactly **32** promoted identities, and the register is **not** added to it.

| horizon | era | est cut | fwd cut | gap cut | excl cut | eligible | non-overlap blocks | status |
|---|---|---|---|---|---|---|---|---|
| 1d | 2011 | 0 | 0 | 0 | 108 | **1903** | 960 | feasible |
| 5d | 2011 | 0 | 0 | 0 | 380 | **1631** | 287 | feasible |
| 20d | 2011 | 0 | 0 | 0 | 1122 | **889** | 51 | feasible |

Funnel order (I0 §17): era → estimation (≥60 prior) → forward (≥h ahead) → interior-gap → known-date exclusion; each stage sieves the prior survivors, so era − cuts = eligible at every horizon. The non-overlap block count is the size of the canonical set of disjoint response windows `[t, t+h]` — a deterministic greedy earliest-first packing on the eligible session indices, where two windows share no session only if their starts are at least `h+1` apart (I0 §8; a shared endpoint at distance `h` is overlap). It is **not** `eligible // h` (which ignores index positions and, at `h=1`, returns the full count), and **not** an independent, effective, or degrees-of-freedom sample size.

Eligible-session count by year:

| horizon | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| 1d | 244 | 244 | 240 | 243 | 236 | 241 | 237 | 218 |
| 5d | 228 | 228 | 204 | 223 | 196 | 217 | 197 | 138 |
| 20d | 173 | 167 | 104 | 148 | 85 | 126 | 68 | 18 |

---

Reproducibility: joint-session and era pins (2385 / 2011 per lane) are fail-loud; the builder refuses to run if the substrate frame counts do not reconcile. Substrate: the gitignored `g3_price_cache.db` (Yahoo refetch; drift disclosed). Event universes come from the tracked G1 ledgers.
