# K0 - Data-compatible research adjacency gate (read-only)

Contract: `k0-research-adjacency-v1`. Snapshot date: 2026-07-11.

## 1. Executive verdict

### NO_ADJACENT_FAMILY_READY

No adjacent recurring event family is currently studiable from the
structured data that exists in this repository and local environment.
The repository contains exactly two source-pinned event registers (FOMC
decisions, 65 events 2018-01-31..2025-12-10; OPEC production-policy
decisions, 32 events 2018-06-23..2025-11-30) - both already the core
research families - and one architecturally complete but historically
empty macro-release seam: the `macro_releases` and
`macro_release_facts` tables hold **0 rows each**, and the in-repo
macro calendar is a self-declared approximate app-layer display list
(dates only, 2025-2026, no timestamps, no values, no consensus) that a
prior tracked adjudication (`stats/J2_TIMING_COLLISION_RESULTS.md`,
section 5) already ruled non-source-pinned and missing the 2018-2024
era. Every candidate family derived source-first from the existing
substrate fails at least one foundational gate (A-D). This is a
substrate result, not a value judgment on any economic topic.

## 2. Correction to the previous broad-expansion premise

A prior expansion proposal treated broad cross-domain screening (AI,
semiconductors, pharma, cyber, logistics, commodities) as inexpensive
preliminary work. That was a material planning error, corrected here
and recorded as a standing lesson in the root local `CLAUDE.md`
(`## Lessons`, present exactly once): event-source construction is
itself research infrastructure, not preliminary work. The repository's
own history quantifies the cost: the OPEC register required a full
mission slice (G1B) of official-source discovery to pin 32 canonical
identities from 38 source records, and the FOMC frame (G1A/J1A)
required its own inventory, freeze and verification passes. Grouping
heterogeneous idiosyncratic events into broad "mechanism families" was
already tried and closed: the C3 staged-family arc ended in a freeze
after the sanctions thread collapsed to zero independent events.
Expansion therefore defaults to data-compatible adjacent families;
anything else needs an explicitly justified new event, timing,
exposure and identification substrate.

## 3. Current substrate inventory

Structured sources actually present (verified read-only on this
snapshot; commands in section 21):

| source | owner | publisher | fields | resolution | local history | consensus | revisions | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FOMC decision register | `g_historical_evidence` (sampling_family `fomc`, ledger `frame_complete_historical`), frozen via G1A/J1A; `scripts/i2a_response_substrate.py` | Federal Reserve | event_date, anchors, state/tags, panels | daily | **65 events, 2018-01-31..2025-12-10** | n/a (decision regime) | n/a | live core family |
| OPEC decision register | `g_historical_evidence` (sampling_family `opec`, ledger `designed_contrast`), G1B reservoir | OPEC/V8 press releases | event_date, action type, canonical identity | daily | **32 events, 2018-06-23..2025-11-30** (+41-date known-date exclusion register, contamination control only) | n/a | n/a | live core family |
| Macro release calendar | `macro_calendar.py` | BLS / BEA (transcribed) | (indicator, release_date, period_label) | date only | CPI 24, PPI 24, NFP 24, Unemployment 24, PCE 24 entries; 2025-01-10..2026-12-18; 18-19 past per indicator | none | none | static display list, self-declared approximate |
| Macro release values | `macro_releases` table (`macro_surprises.py`) | (future feed) | series, release_time, expected, realized, surprise z/direction/magnitude | timestamped schema | **0 rows** | schema only | schema only | empty seam |
| Macro release facts | `macro_release_facts` table | (future feed) | actual, prior, revised_prior, consensus, release_time | timestamped schema | **0 rows** | schema only | schema only | empty seam |
| Treasury yield curve | `g_state_cache/curve_2s10s.json`, `j1a_treasury.json` (`scripts/g_state_acquisition.py`) | U.S. Treasury daily CSVs | date -> spread / 2yr level | daily observation | 2,396 obs 2016-06-01..2025-12-31; J1A extension 2,520 obs ..2026-06-30 | n/a (state series) | n/a | cached state series |
| HY OAS | `g_state_cache/hy_oas.json` | FRED (ICE BofA BAMLH0A0HYM2) | date -> OAS | daily observation | 654 obs 2023-07-04..2025-12-31 | n/a | n/a | cached; era-bounded (see s4) |
| SPY / VIX state | `g_state_cache/spy.json`, `vix.json` | Yahoo chart / Cboe | date -> close | daily observation | 2,411 / 2,438 obs 2016-06-01..2025-12-31 | n/a | n/a | cached state series |
| Market price cache | `price_cache` table in `events.db` | provider-cached closes | ticker, date, close, volume, raw+adjusted | daily close | 65,976 rows, 181 tickers, 2015-08-04..2026-07-05 | n/a | n/a | live cache |
| Accepted event archive | `events` table | curated news events | thesis, tickers, roles | daily | 180 rows / 86 accepted | n/a | n/a | core corpus, not a release feed |
| News layer | `headline_registry` (12,439), `news_clusters` (13,529), `news_consensus.py` keyword extraction | RSS/news | headlines, clusters | intraday-ish text | large | none | none | unstructured; not a release schema |
| Candidate pack | `data/candidates/z1a_multi_regime_candidates.yaml` | hand-curated | historical archive backfill pack | n/a | one file | n/a | n/a | curated, not a feed |

Not connected at all: Treasury auctions, ECB/BoE calendars, EIA
feeds, earnings calendars, FDA/clinical registries, shipping/port
data. None was researched manually; absence was established from the
repository only.

## 4. Connected-source limitations

- The FRED-authenticated HY OAS path serves only a rolling ~3-year
  window (era-bounded since April 2026; `hy_oas.blocked.json` records
  the earlier blocked acquisition path).
- `macro_calendar.py` self-declares its dates "approximate for future
  months" and instructs annual manual verification; J2 formally ruled
  it an app-layer display list, not a source-pinned register, and it
  is missing the 2018-2024 era that the existing event registers
  cover.
- `macro_surprises.py` and `macro_release_facts.py` state in their own
  docstrings that no ingestion or scheduler exists: "the upsert API is
  the seam a future data feed plugs into".
- Role-asset price coverage outside the current families is thin:
  SPY has 2,020 raw bars (2015-2026) but TLT has 110 bars (2026 only),
  GLD 87, XLF 3, KRE 110, and IEF / SHY / TIP / HYG / LQD are absent
  from `price_cache` entirely.

## 5. Candidate-generation method

Candidates were derived source-first, in the mandated order (existing
source -> coverage -> recurring schema -> objective shock -> anchor ->
resolution -> roles -> ordinary periods -> value), from the inventory
in section 3 only. No industry or theme list was consulted. Five
candidates emerged; PPI is structurally identical to CPI and shares
its verdict rather than consuming a separate row.

1. **C1 - BLS CPI monthly release** (headline print vs consensus),
   from the macro calendar + empty value stores + surprise classifier.
2. **C2 - BLS Employment Situation release** (NFP + unemployment rate,
   one scheduled release), same seam.
3. **C3 - BEA Personal Income and Outlays (PCE) release**, same seam.
4. **C4 - Treasury yield-curve regime-crossing events** (e.g. 2s10s
   sign changes), from the fully local Treasury series.
5. **C5 - Federal Reserve FOMC minutes releases**, from the Fed
   publisher regime adjacent to the frozen FOMC register.

## 6. Candidate matrix (hard gates)

Gates: A structured source with existing history; B repeated schema;
C honest anchor; D objective shock; E resolution fit; F co-shock
discipline; G leakage/anticipation; H frozen asset roles; I ordinary
periods; J second-order value; K effective independence. A candidate
failing any of A-H is rejected immediately.

| cand | source | publisher | history now | shock | A | B | C | D | E | F | G | H | I | J | K | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C1 CPI | calendar dates + empty stores | BLS | 18 past app-layer dates; 0 value rows | actual - consensus | **FAIL** | PASS | **FAIL** | **FAIL** | PASS | UNKNOWN | PASS | PASS | PASS | PASS | UNKNOWN | REJECT (A, C, D) |
| C2 Employment Situation | calendar dates + empty stores | BLS | 19 past app-layer dates; 0 value rows | actual - consensus | **FAIL** | PASS | **FAIL** | **FAIL** | PASS | **FAIL** | PASS | PASS | PASS | PASS | UNKNOWN | REJECT (A, C, D, F) |
| C3 PCE | calendar dates + empty stores | BEA | 18 past app-layer dates; 0 value rows | actual - consensus | **FAIL** | PASS | **FAIL** | **FAIL** | PASS | **FAIL** | PASS | PASS | PASS | PASS | UNKNOWN | REJECT (A, C, D, F) |
| C4 curve crossings | local Treasury series (2,520 obs) | U.S. Treasury (data), but no event publisher | full 2016-2026 | market-state change | PASS | **FAIL** | **FAIL** | **FAIL** | PASS | UNKNOWN | **FAIL** | UNKNOWN | PASS | UNKNOWN | UNKNOWN | REJECT (B, C, D, G) |
| C5 FOMC minutes | no local minutes-date register | Federal Reserve | 0 local dates | none available | **FAIL** | PASS | **FAIL** | **FAIL** | UNKNOWN | PASS | PASS | PASS | PASS | UNKNOWN | UNKNOWN | REJECT (A, C, D) |

No composite score exists or is implied; foundational FAILs decide.

## 7. Actual data-readiness counts (verified read-only)

- `macro_releases`: 0 rows. `macro_release_facts`: 0 rows.
  `saved_studies`: 0. `movers_cache`: 0.
- `macro_calendar._RELEASES`: 24 entries per indicator (CPI, PPI, NFP,
  Unemployment, PCE), 2025-01-10..2026-12-18; past entries at
  2026-07-11: CPI 18, PPI 18, NFP 19, Unemployment 19, PCE 18. Fields:
  (indicator, date, period label) only - no release times, no actual,
  no prior, no consensus, no revisions.
- Registers: FOMC 65 (2018-01-31..2025-12-10), OPEC 32
  (2018-06-23..2025-11-30) in `g_historical_evidence`; OPEC known-date
  exclusion register 41 calendar dates (contamination control only).
- State series: 2s10s 2,396 obs (+J1A 2,520 to 2026-06-30), HY OAS 654
  obs (2023-07..2025-12), SPY 2,411, VIX 2,438.
- `price_cache`: 65,976 rows, 181 tickers, 2015-08-04..2026-07-05;
  role-asset coverage per section 4.
- Code presence was never counted as readiness: the macro seam is
  complete code with zero history, and is reported exactly that way.

## 8. Timing and collision findings

Recorded for the rejected-but-nearest candidates, contingent on a real
register existing in the future; nothing here rescues a gate:

- CPI / Employment Situation are scheduled 08:30 ET pre-open releases;
  a daily close-to-close t=0 would capture release-day discovery
  (resolution gate E passes structurally). PCE is also pre-open.
- CPI and PPI print on adjacent days in the same weeks (in-repo
  calendar shows repeated 1-2 day gaps); same-publisher adjacency must
  be an explicit collision rule for any future pilot.
- The Employment Situation is an inseparable bundle (payrolls,
  unemployment rate, average hourly earnings in one print) - co-shock
  gate F fails for a single-variable reading. PCE bundles income,
  spending and deflators similarly. CPI headline-vs-core is a milder,
  manageable bundle (headline print is the conventional shock).
- FOMC minutes are 14:00 ET intraday releases three weeks after each
  decision; daily closes would mix the minutes with the same-day tape.
- J2's collision architecture (exact [t, t+1] session overlap) already
  exists and would transfer to any future scheduled-release family.

## 9. Leakage and anticipation findings

Scheduled, embargoed, consensus-bearing government releases (CPI, ES,
PCE) support a defensible t=0 by regime design: the lockup makes the
release time public and sharp, and the consensus field would carry the
anticipation state. Gate G passes structurally for C1-C3 and is not
the blocker - the blocker is that no consensus or actual history
exists locally. C4 (curve crossings) fails G outright: the "event" is
the market's own cumulative move, so anticipation and event are the
same object and no defensible t=0 exists.

## 10. Asset-role findings

A family-level role map for a future scheduled-release family is
pre-definable from economic structure (rates duration response via the
local Treasury 2yr/2s10s series; equity index response via SPY;
credit via HY OAS within its era bound) - gate H passes structurally
for C1-C3. However, preliminary role coverage in `price_cache` is
inadequate beyond SPY: the natural rate/credit ETF proxies (TLT, IEF,
SHY, TIP, HYG, LQD) are absent or 2026-only (section 4), so a
cross-asset role map would require routine cache backfill - provider
work outside K0. Roles were not selected by inspecting historical
reactions; no reaction of any candidate asset was examined in this
audit.

## 11. Ordinary-period feasibility

The Mission I ordinary-period architecture
(`scripts/i2a_response_substrate.py`: symmetric event-exclusion gate,
membership-as-metadata, per-horizon references) is family-agnostic and
would transfer to any scheduled-release family on the same daily
basis. Gate I passes structurally for C1-C3/C5. It cannot be
instantiated today because no candidate has an event register to
exclude around.

## 12. Effective-independence concerns

With only the app-layer 2025-2026 dates, C1-C3 would offer at most
18-19 monthly observations spanning 18 months - one macro regime, no
era contrast with the 2018-2024 registers, and heavy overlap with the
FOMC family's own calendar. No intuition-based minimum N is asserted;
the honest statement is that the currently visible history is both
non-source-pinned and era-truncated, so leave-one-year-out and regime
splits - the fragility tools this project already uses - would be
unavailable or degenerate. A future register covering 2018+ (~96
monthly events) would change that assessment.

## 13. Research-value questions

For the nearest family (a future CPI-surprise pilot), one bounded
question compatible with this workbench exists: does a predefined
surprise direction (actual minus consensus, sign frozen at release)
produce a stable cross-asset descriptive pattern - short-rate path,
curve, equity index - at 1d/5d/20d relative to eligible ordinary
periods, beyond the FOMC-day family already studied? Denominator:
the future register's eligible releases; basis: raw daily closes plus
the Treasury series; comparator: i2a-style ordinary periods;
collision rule: exact-session overlap with FOMC/OPEC/PPI registers;
fragility: leave-one-event/year-out; falsifier: pattern instability
under era splits. This question is recorded to show gate J would
pass; it confers no readiness (gates A/C/D still fail today).

## 14. Rejected candidates and exact reasons

- **C1 CPI**: no local release-value or consensus history (0 rows in
  both stores); calendar dates non-source-pinned and self-declared
  approximate (J2 adjudication); no objective shock computable
  locally. FAIL A, C, D.
- **C2 Employment Situation**: identical store failures plus an
  inseparable multi-variable release bundle. FAIL A, C, D, F.
- **C3 PCE**: identical store failures plus a component bundle.
  FAIL A, C, D, F.
- **C4 Curve crossings**: rich local data but no publisher event
  schema; the anchor and the shock are the market response itself
  (identification circularity); no defensible t=0. FAIL B, C, D, G.
- **C5 FOMC minutes**: no local register of minutes release dates
  (constructing one is manual historical research, i.e. the exact
  cost K0 exists to price honestly); no objective shock variable
  available locally. FAIL A, C, D.
- (PPI shares C1's verdict for the same reasons.)

## 15. Selected family

None. A GO selection requires all foundational gates to pass on
existing data; no candidate qualifies.

## 16. Reserve family

None. Naming a reserve would imply a viable secondary; none exists.

## 17. Bounded K1 preview

Not applicable under a NO_ADJACENT_FAMILY_READY verdict. For the
operator's planning only: the nearest future path is a deliberate,
bounded **event-source construction phase** (not a K1 pilot) that
would build a source-pinned BLS CPI release register (2018+) with
release timestamps, actual/prior/consensus values landed through the
existing `macro_release_facts` seam, plus routine price-cache backfill
for the role assets - after which K0's gates could be re-run. That
phase was not started, scoped, or approved here.

## 18. Unavailable analyses

- Any empirical readout for C1-C3/C5 (no event values exist locally).
- CPI/ES collision adjudication for the 2018-2024 era (per J2, no
  source-pinned register; unchanged).
- Consensus-based anticipation measurement (no consensus history).
- Cross-asset role coverage beyond SPY/Treasury series (ETF proxies
  absent from the price cache).
- Micro-event domains (AI capex, earnings variables, product
  launches, fab accidents, cyberattacks, FDA outcomes, port strikes,
  shipping incidents, grid outages, heterogeneous geopolitical
  disruptions): out of K0 scope by design; they were not manually
  researched, and their absence from this repository's structured
  sources is the only claim made about them.

## 19. Permanent non-claims

- No new family was empirically validated; no event effect was
  estimated anywhere in this audit.
- No production rule, contract, threshold or publication changed.
- No predictive, causal, significant or tradeable claim is made, and
  none is implied.
- Source availability is not evidence that any mechanism works;
  data-compatibility is a feasibility property only.
- A GO verdict would have meant only that a bounded pilot is
  methodologically feasible; the actual NO-GO verdict does not mean
  any economic topic is unimportant.
- Micro-event domains may require a separate research substrate; this
  audit neither built nor evaluated one.

## 20. Exact verdict

`NO_ADJACENT_FAMILY_READY`

## 21. Reproduction steps (read-only)

```
# table row counts (macro seams are empty)
python -c "import sqlite3; c=sqlite3.connect('file:events.db?mode=ro',uri=True); \
  [print(t, c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]) for t in \
  ('macro_releases','macro_release_facts','g_historical_evidence','price_cache','events')]"

# registers: family, count, date range
python -c "import sqlite3; c=sqlite3.connect('file:events.db?mode=ro',uri=True); \
  [print(tuple(r)) for r in c.execute('SELECT sampling_family, COUNT(*), MIN(event_date), \
  MAX(event_date) FROM g_historical_evidence GROUP BY sampling_family')]"

# macro calendar entries and past counts
python -c "import macro_calendar as m; from collections import Counter; \
  r=m._RELEASES; print(Counter(i for i,_,_ in r)); \
  print(Counter(i for i,d,_ in r if d<='2026-07-11')); \
  print(min(d for _,d,_ in r), max(d for _,d,_ in r))"

# state-series coverage
python -c "import json; \
  [print(f, json.load(open('g_state_cache/'+f+'.json'))['meta']) for f in \
  ('curve_2s10s','hy_oas','spy','vix')]"

# price cache range and role-asset coverage
python -c "import sqlite3; c=sqlite3.connect('file:events.db?mode=ro',uri=True); \
  print(c.execute('SELECT COUNT(*), MIN(date), MAX(date), COUNT(DISTINCT ticker) \
  FROM price_cache').fetchone()); \
  [print(t, c.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM price_cache \
  WHERE ticker=? AND auto_adjust=0',(t,)).fetchone()) for t in \
  ('SPY','TLT','IEF','SHY','TIP','HYG','LQD','GLD','XLF','KRE')]"
```

All connections are `mode=ro`; no provider, network, or paid call is
made; nothing is written.

## 22. Source commit and database/cache hashes

- produced from the working tree at commit
  `92feff558f95e36eb1a318645fa13a3e7a6f90f8` (the commit adding this
  file is its immediate child)
- `events.db` sha256 (identical before and after every K0 command):
  `bcaa7f10773fc3c5ded14164400d16ced8391e986343ede5e7f6e2290d664e82`
- `events.h2.dev.db` sha256:
  `6c17f0446cfd8b1c2354f0d81df06f727fb74546728cc58122e189f2a55c74f5`
- `price_cache.db` (empty standalone file; the real cache is the
  `price_cache` table inside `events.db`) sha256:
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- no SQLite sidecars (`-wal` / `-shm` / `-journal`) present.
