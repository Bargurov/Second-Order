# J1A frozen inputs - the exact pre-outcome data snapshot (Mission J)

Contract: `j1a-data-readiness-v1` input freeze. The gitignored local files below are the EXACT bytes the J1B comparison must consume; they were pinned before any J1 outcome was computed or inspected. They are local inputs, not tracked artifacts; this manifest and the machine verifier (`scripts/j1a_data_readiness.py::verify_frozen_inputs`) are the tracked record.

## Provider-drift note (why bytes are pinned)

During J1A, repeated fetches from the zero-cost provider preserved ticker/date keys and raw closes exactly, while adjusted closes exhibited tiny refetch drift (max relative difference about 1.5e-06). J1B uses the frozen adjusted/adjusted-preferred basis, so Mission J consumes this exact frozen local snapshot rather than treating a future provider refetch as byte-identical evidence. This is a reproducibility discipline; it is not a provider-quality claim, and the drift magnitude is not read as economically meaningful.

## J1B gate (frozen rule)

> J1B must call require_frozen_inputs() and receive success before computing any response value. On any mismatch: stop, report the mismatched file and invariant, do not refetch automatically, do not recompute outcomes.

## Frozen files

| file (g_state_cache/) | sha256 | bytes | role | J1B may mutate |
|---|---|---|---|---|
| `g3_price_cache.db` | `a5bb09f87fa6566588baa6638119ce7b0b349d02143c72415b49d426b14c2754` | 2502656 | inherited Mission I substrate (KRE/XLF/SPY legs of the J1 frames) | no |
| `j1a_price_cache.db` | `b735c227d8155816045eca4bbfc83b361caa64482252182ed4b2c227794eac28` | 1990656 | J1 new-ETF price substrate (SHY/IAT/KBE/VFH, raw + adjusted daily closes) | no |
| `j1a_price_meta.json` | `e4a09b00a72a71f0f2659edcca7dc6df8062011e210699f798095248c36b2b89` | 376 | J1 ETF cache provenance metadata | no |
| `j1a_treasury.json` | `b1df6fa21dfffb281c2f363e439609457a5c2765f873420f8dcac91ca8c529e7` | 127924 | J1 rates substrate: 2 Yr CMT level and 2s10s CMT spread | no |

### `g_state_cache/g3_price_cache.db`

- sha256: `a5bb09f87fa6566588baa6638119ce7b0b349d02143c72415b49d426b14c2754`; size: 2502656 bytes
- source: Yahoo public chart endpoint (G3 fetch)
- role: inherited Mission I substrate (KRE/XLF/SPY legs of the J1 frames)
- provenance: inherited pin: this SHA-256 is already documented in stats/G3_MECHANICAL_ELIGIBILITY.md section 7; no new freeze decision is made here
- J1B may mutate: no (read-only input)

### `g_state_cache/j1a_price_cache.db`

- sha256: `b735c227d8155816045eca4bbfc83b361caa64482252182ed4b2c227794eac28`; size: 1990656 bytes
- source: Yahoo public chart endpoint via the existing G3 seam
- role: J1 new-ETF price substrate (SHY/IAT/KBE/VFH, raw + adjusted daily closes)
- provenance: fetched 2026-07-06T19:37:20.498248+00:00 by scripts/j1a_data_readiness.py --fetch (temp-proofed first; zero-cost)
- J1B may mutate: no (read-only input)
- tables: price_cache; provider identity: yahoo_chart
- IAT raw: 2385 rows, 2017-01-03 .. 2026-06-30
- IAT adjusted: 2385 rows, 2017-01-03 .. 2026-06-30
- KBE raw: 2385 rows, 2017-01-03 .. 2026-06-30
- KBE adjusted: 2385 rows, 2017-01-03 .. 2026-06-30
- SHY raw: 2385 rows, 2017-01-03 .. 2026-06-30
- SHY adjusted: 2385 rows, 2017-01-03 .. 2026-06-30
- VFH raw: 2385 rows, 2017-01-03 .. 2026-06-30
- VFH adjusted: 2385 rows, 2017-01-03 .. 2026-06-30

### `g_state_cache/j1a_price_meta.json`

- sha256: `e4a09b00a72a71f0f2659edcca7dc6df8062011e210699f798095248c36b2b89`; size: 376 bytes
- source: written beside the cache by the same --fetch
- role: J1 ETF cache provenance metadata
- provenance: fetched 2026-07-06T19:37:20.498248+00:00
- J1B may mutate: no (read-only input)

### `g_state_cache/j1a_treasury.json`

- sha256: `b1df6fa21dfffb281c2f363e439609457a5c2765f873420f8dcac91ca8c529e7`; size: 127924 bytes
- source: official U.S. Treasury daily yield-curve CSVs (existing documented path)
- role: J1 rates substrate: 2 Yr CMT level and 2s10s CMT spread
- provenance: fetched 2026-07-06T19:37:40.054780+00:00 by --fetch; refetched spread matched the tracked-path G2 cache on all 2,396 overlapping dates
- J1B may mutate: no (read-only input)
- spread_2s10s: 2520 observations, 2016-06-01 .. 2026-06-30
- two_yr: 2520 observations, 2016-06-01 .. 2026-06-30
- duplicate source dates: 0
- source identity: official U.S. Treasury daily yield-curve CSV distribution (the existing documented path; same parser columns as the tracked 2s10s series)

## Boundary

The verifier is read-only: it never fetches, repairs, rewrites, normalizes, or updates metadata. No response value, MEMP, calibration, node state, or edge state exists in this freeze or its verifier.
