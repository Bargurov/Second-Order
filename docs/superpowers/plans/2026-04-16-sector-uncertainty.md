# Sector Uncertainty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface news-derived sector uncertainty as the lead signal in the UncertaintySection of Market Overview when concentration is clearly sector-specific, with vol-ratio corroboration badges per sector chip.

**Architecture:** Add `uncertainty_concentration` to the `/market-context` response by wiring the already-existing `compute_news_uncertainty()` helper through `compose_market_context()`. The frontend reads the field from the existing `useMarketContext()` query and passes it to a restructured `UncertaintySection` that conditionally leads with sector chips vs the global 5-signal grid.

**Tech Stack:** Python/FastAPI backend, React/TypeScript frontend, TanStack Query, Tailwind CSS, shadcn/ui

---

## File Map

| File | Change |
|------|--------|
| `market_context.py` | Add `uncertainty_concentration` param + normalizer + return field |
| `routes/market.py` | Call `compute_news_uncertainty()` and pass to `compose_market_context()` |
| `tests/test_market_context_consumer.py` | Add `"uncertainty_concentration"` to required keys; add shape tests |
| `frontend/src/lib/api.ts` | Add `NewsSectorUncertaintyEntry`, `NewsUncertaintyConcentration` types; extend `MarketContext` |
| `frontend/src/components/ui/stress-strip.tsx` | Add `SectorLeadRow` component; update `UncertaintySection` props + conditional layout |
| `frontend/src/components/pages/market-overview.tsx` | Extract `uncertainty_concentration` from `ctx`; pass to `UncertaintySection` |

---

## Task 1: Extend `compose_market_context` with uncertainty_concentration

**Files:**
- Modify: `market_context.py:124-161`
- Test: `tests/test_market_context_consumer.py`

- [ ] **Step 1: Write failing tests**

In `tests/test_market_context_consumer.py`:

1a. Update `CONTEXT_REQUIRED_KEYS` (line 50-55) to include the new field:

```python
CONTEXT_REQUIRED_KEYS = {
    "built_at", "source",
    "snapshots", "snapshots_meta",
    "stress", "rates", "regime_vector",
    "highlights", "highlights_meta",
    "uncertainty_concentration",
}
```

1b. Add a new test class after `TestStaleStateRendering`:

```python
class TestUncertaintyConcentration(_Base):

    def _full(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            return self.client.get("/market-context?highlight_limit=10").json()

    def test_field_present(self):
        data = self._full()
        self.assertIn("uncertainty_concentration", data)

    def test_shape(self):
        data = self._full()
        uc = data["uncertainty_concentration"]
        self.assertIn("uncertainty_scope", uc)
        self.assertIn("sector_uncertainty", uc)
        self.assertIn("lead_sector", uc)

    def test_scope_valid_value(self):
        data = self._full()
        self.assertIn(
            data["uncertainty_concentration"]["uncertainty_scope"],
            {"global", "sector", "mixed"},
        )

    def test_sector_uncertainty_is_list(self):
        data = self._full()
        self.assertIsInstance(data["uncertainty_concentration"]["sector_uncertainty"], list)

    def test_fallback_on_compute_failure(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        with patch("api.compute_news_uncertainty", side_effect=RuntimeError("uc_fail")):
            data = self.client.get("/market-context").json()
        uc = data["uncertainty_concentration"]
        self.assertEqual(uc["uncertainty_scope"], "global")
        self.assertEqual(uc["sector_uncertainty"], [])
        self.assertIsNone(uc["lead_sector"])

    def test_all_sections_fail_still_has_uncertainty_concentration(self):
        with patch("market_snapshots.get_all_snapshots", side_effect=RuntimeError("snap")), \
             patch("api.compute_stress_regime", side_effect=RuntimeError("stress")), \
             patch("api.movers_today", side_effect=RuntimeError("movers")), \
             patch("api.compute_news_uncertainty", side_effect=RuntimeError("uc")):
            data = self.client.get("/market-context").json()
        self.assertIn("uncertainty_concentration", data)
        uc = data["uncertainty_concentration"]
        self.assertEqual(uc["uncertainty_scope"], "global")
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m unittest tests.test_market_context_consumer.TestUncertaintyConcentration -v
```

Expected: FAIL — `uncertainty_concentration` not in response, `CONTEXT_REQUIRED_KEYS` mismatch.

Also expect `TestFullContext.test_top_level_keys` to now fail because CONTEXT_REQUIRED_KEYS grew. That's intentional — it will pass once Task 1 Step 4 is done.

- [ ] **Step 3: Add normalizer + param to `compose_market_context` in `market_context.py`**

Add `_normalize_uncertainty_concentration` helper after `_normalize_regime_vector` (line 121):

```python
def _normalize_uncertainty_concentration(uc: Optional[dict]) -> dict:
    """Ensure uncertainty_concentration always has a stable fallback shape."""
    if not uc or not isinstance(uc, dict):
        return {"uncertainty_scope": "global", "sector_uncertainty": [], "lead_sector": None}
    return uc
```

Update `compose_market_context` signature (add `uncertainty_concentration` keyword arg):

```python
def compose_market_context(
    snapshots: list[dict],
    stress: Optional[dict],
    highlights: list[dict],
    *,
    rates: Optional[dict] = None,
    regime_vector: Optional[dict] = None,
    source: Optional[str] = None,
    uncertainty_concentration: Optional[dict] = None,
) -> dict:
```

Add the field to the return dict (after `highlights_meta`):

```python
    return {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source or _provider_name(),
        "snapshots": list(snapshots or []),
        "snapshots_meta": _summarize_snapshots(snapshots or []),
        "stress": _normalize_stress(stress),
        "rates": _normalize_rates(rates),
        "regime_vector": _normalize_regime_vector(regime_vector),
        "highlights": list(highlights or []),
        "highlights_meta": _summarize_highlights(highlights or []),
        "uncertainty_concentration": _normalize_uncertainty_concentration(uncertainty_concentration),
    }
```

- [ ] **Step 4: Wire `compute_news_uncertainty` in `routes/market.py`**

In the `/market-context` handler (around line 162-171), add an `uc` fetch before the `return` statement:

```python
    uc: dict | None = None
    try:
        uc = _api.compute_news_uncertainty()
    except Exception:
        _api._log.warning("market_context: uncertainty_concentration failed", exc_info=True)

    return _api._sanitize_floats(compose_market_context(
        snaps_list, stress_dict, highlights,
        rates=rates_dict, regime_vector=regime_vec,
        uncertainty_concentration=uc,
    ))
```

The full updated handler bottom (replacing lines 162-171):

```python
    uc: dict | None = None
    try:
        uc = _api.compute_news_uncertainty()
    except Exception:
        _api._log.warning("market_context: uncertainty_concentration failed", exc_info=True)

    return _api._sanitize_floats(compose_market_context(
        snaps_list, stress_dict, highlights,
        rates=rates_dict, regime_vector=regime_vec,
        uncertainty_concentration=uc,
    ))
```

- [ ] **Step 5: Run the tests**

```
python -m unittest tests.test_market_context_consumer -v
```

Expected: All tests PASS (including the new `TestUncertaintyConcentration` class and the updated `test_top_level_keys`).

- [ ] **Step 6: Commit**

```bash
git add market_context.py routes/market.py tests/test_market_context_consumer.py
git commit -m "feat: add uncertainty_concentration to /market-context response"
```

---

## Task 2: Add TypeScript types in `api.ts`

**Files:**
- Modify: `frontend/src/lib/api.ts:690-701`

- [ ] **Step 1: Add new interfaces**

Insert after the `SectorUncertainty` interface (after line 745 in `api.ts`):

```typescript
export interface NewsSectorUncertaintyEntry {
  sector: string
  score: number
  cluster_count: number
  high_fraction: number
}

export interface NewsUncertaintyConcentration {
  uncertainty_scope: "global" | "sector" | "mixed"
  sector_uncertainty: NewsSectorUncertaintyEntry[]
  lead_sector: string | null
}
```

- [ ] **Step 2: Extend `MarketContext`**

In the `MarketContext` interface (around line 690-701), add the optional field after `highlights_meta`:

```typescript
export interface MarketContext {
  built_at: string;
  source: string;
  snapshots: MarketSnapshot[];
  snapshots_meta: SnapshotsMeta;
  /** Backend always sends stress/rates/regime_vector (with available:false when degraded). */
  stress: StressRegime & { available?: boolean };
  rates: RatesContext & { available?: boolean };
  regime_vector: RegimeVector;
  highlights: MarketMover[];
  highlights_meta: HighlightsMeta;
  uncertainty_concentration?: NewsUncertaintyConcentration;
}
```

- [ ] **Step 3: Run TypeScript check**

```
cd frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add NewsUncertaintyConcentration types to MarketContext"
```

---

## Task 3: Add `SectorLeadRow` and update `UncertaintySection` in `stress-strip.tsx`

**Files:**
- Modify: `frontend/src/components/ui/stress-strip.tsx`

- [ ] **Step 1: Update import line to include new types**

Change line 4 from:
```typescript
import { api, type StressComponentDetail, type StressRegime, type SectorVolEntry } from "@/lib/api";
```
To:
```typescript
import { api, type StressComponentDetail, type StressRegime, type SectorVolEntry, type NewsSectorUncertaintyEntry, type NewsUncertaintyConcentration } from "@/lib/api";
```

- [ ] **Step 2: Add `SectorLeadRow` component**

Insert this component after the closing `}` of `SectorPressureRow` (after line 185), before the `// Two-column Uncertainty section` comment block:

```typescript
// ---------------------------------------------------------------------------
// Sector lead row — shown when news-derived uncertainty_scope === "sector".
// Displays up to 3 top-scoring sectors with optional vol corroboration badge.
// ---------------------------------------------------------------------------

function SectorLeadRow({
  topSectors,
  volSectors,
}: {
  topSectors: NewsSectorUncertaintyEntry[];
  volSectors?: SectorVolEntry[];
}) {
  const displayed = topSectors.slice(0, 3);
  if (displayed.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {displayed.map((s) => {
        const volEntry = volSectors?.find(
          (v) => v.sector.toLowerCase() === s.sector.toLowerCase(),
        );
        const hasBadge = volEntry != null && volEntry.vol_ratio >= 1.3;
        const isHigh = s.high_fraction > 0.5;

        return (
          <span
            key={s.sector}
            title={`${s.sector} — score ${s.score}, ${s.cluster_count} clusters, ${Math.round(s.high_fraction * 100)}% high-uncertainty`}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium border",
              isHigh
                ? "bg-error/10 text-error border-error-dim/20"
                : "bg-surface-container-highest text-on-surface-variant border-outline-variant/20",
            )}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full shrink-0",
                isHigh ? "bg-error" : "bg-on-surface-variant/40",
              )}
            />
            <span className="capitalize">{s.sector}</span>
            {hasBadge && (
              <span className="text-primary/80 font-mono text-[10px] opacity-80">
                {volEntry!.vol_ratio.toFixed(2)}×
              </span>
            )}
          </span>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Update `UncertaintySectionProps` interface**

Replace the existing interface (lines 191-197):
```typescript
interface UncertaintySectionProps {
  /** When provided (parent-driven), this stress regime is rendered directly
   *  and no internal fetch is made.  When omitted (standalone usage), the
   *  component falls back to its own /stress query for backward compat. */
  stress?: StressRegime | null;
  isLoading?: boolean;
  /** News-derived sector uncertainty concentration from /market-context.
   *  When uncertainty_scope is "sector", the section leads with sector chips
   *  and the 5-signal grid becomes a secondary baseline. */
  uncertaintyConcentration?: NewsUncertaintyConcentration | null;
}
```

- [ ] **Step 4: Update the `UncertaintySection` function signature**

Change line 199:
```typescript
export function UncertaintySection({ stress, isLoading: parentLoading }: UncertaintySectionProps = {}) {
```
To:
```typescript
export function UncertaintySection({ stress, isLoading: parentLoading, uncertaintyConcentration }: UncertaintySectionProps = {}) {
```

- [ ] **Step 5: Add sector-lead flag after the existing variable declarations**

After `const sectionDegraded = deriveStressDegraded(data);` and `const regimeLabel = data.regime.toUpperCase();`, add:

```typescript
  const isSectorLed =
    uncertaintyConcentration?.uncertainty_scope === "sector" &&
    (uncertaintyConcentration.sector_uncertainty?.length ?? 0) > 0;
```

- [ ] **Step 6: Replace the rendered JSX inside the `<div className="flex flex-col gap-6 ...">` block**

Replace the entire content of the outer flex column (lines 249-301) with the conditional layout below. The section structure inside `<div className="flex flex-col gap-6 relative z-10">` becomes:

```typescript
        <div className="flex flex-col gap-6 relative z-10">
          {/* Top row: left badge + right content */}
          <div className="flex flex-col lg:flex-row gap-8 items-start">
            {/* Left Badge */}
            <div className="lg:w-1/4 shrink-0">
              {isSectorLed ? (
                <div className={cn(
                  "inline-flex items-center gap-2 px-3 py-1 rounded-full border",
                  rc.badge, rc.badgeBorder,
                )}>
                  <span className="relative flex h-2.5 w-2.5">
                    <span className={cn("animate-ping absolute inline-flex h-full w-full rounded-full opacity-75", rc.dot)} />
                    <span className={cn("relative inline-flex rounded-full h-2.5 w-2.5", rc.dot)} />
                  </span>
                  <span className={cn("font-bold text-xs tracking-widest uppercase", rc.text)}>
                    {uncertaintyConcentration!.lead_sector} · Concentration
                  </span>
                </div>
              ) : (
                <div className={cn(
                  "inline-flex items-center gap-2 px-3 py-1 rounded-full border",
                  rc.badge, rc.badgeBorder,
                )}>
                  <span className="relative flex h-2.5 w-2.5">
                    <span className={cn("animate-ping absolute inline-flex h-full w-full rounded-full opacity-75", rc.dot)} />
                    <span className={cn("relative inline-flex rounded-full h-2.5 w-2.5", rc.dot)} />
                  </span>
                  <span className={cn("font-bold text-xs tracking-widest uppercase", rc.text)}>{regimeLabel}</span>
                </div>
              )}
              <h2 className="text-3xl font-headline font-extrabold mt-4 tracking-tighter leading-tight text-white">
                Uncertainty &amp; Market Instability
              </h2>
              {data.summary && (
                <p className="text-on-surface-variant text-sm mt-3 leading-relaxed">{data.summary}</p>
              )}
              {sectionDegraded && (
                <div className="flex items-center gap-1.5 mt-2">
                  <AlertTriangle className="h-3 w-3 text-error-dim/60 shrink-0" />
                  <span className="text-[10px] text-error-dim/60">{sectionDegraded}</span>
                </div>
              )}
            </div>

            {/* Right — sector chips (sector-led) or 5 indicator cards (global) */}
            {isSectorLed ? (
              <div className="flex-1 flex flex-col gap-3">
                <SectorLeadRow
                  topSectors={uncertaintyConcentration!.sector_uncertainty}
                  volSectors={data.sector_uncertainty?.sectors}
                />
                <div>
                  <span className="text-[9px] uppercase tracking-widest text-on-surface-variant/40 font-bold">
                    Baseline
                  </span>
                  <div className="mt-1 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-px bg-outline-variant/20 rounded-lg overflow-hidden opacity-50">
                    {detailKeys.map((k) => {
                      const d = detail[k];
                      if (!d) return null;
                      return <IndicatorCard key={k} detail={d} />;
                    })}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex-1 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-px bg-outline-variant/20 rounded-lg overflow-hidden">
                {detailKeys.map((k) => {
                  const d = detail[k];
                  if (!d) return null;
                  return <IndicatorCard key={k} detail={d} />;
                })}
              </div>
            )}
          </div>

          {/* Sector pressure row — vol-based, only in global mode when concentrated/mixed */}
          {!isSectorLed && (() => {
            const su = data.sector_uncertainty;
            if (!su?.available) return null;
            if (su.concentration === "diffuse") return null;
            return (
              <div className="border-t border-outline-variant/15 pt-4">
                <SectorPressureRow
                  sectors={su.sectors ?? []}
                  spyVol={su.spy_vol_20d}
                />
              </div>
            );
          })()}
        </div>
```

- [ ] **Step 7: Run TypeScript check**

```
cd frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/ui/stress-strip.tsx
git commit -m "feat: add SectorLeadRow and sector-led layout to UncertaintySection"
```

---

## Task 4: Wire `uncertainty_concentration` into `UncertaintySection` in `market-overview.tsx`

**Files:**
- Modify: `frontend/src/components/pages/market-overview.tsx`

- [ ] **Step 1: Extract the field from `ctx`**

After the existing context destructures (around line 855-858), add:

```typescript
  const uncertaintyConcentration = ctx?.uncertainty_concentration ?? null;
```

- [ ] **Step 2: Pass the prop to `UncertaintySection`**

Change line 932 from:
```typescript
      <UncertaintySection stress={stress} isLoading={ctxLoading} />
```
To:
```typescript
      <UncertaintySection
        stress={stress}
        isLoading={ctxLoading}
        uncertaintyConcentration={uncertaintyConcentration}
      />
```

- [ ] **Step 3: Run TypeScript check**

```
cd frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 4: Run all backend tests**

```
python -m unittest discover -s tests -v 2>&1 | tail -20
```

Expected: Same pass/fail count as before this feature (pre-existing failures in `test_api.py`, `test_event_age_policy.py`, `test_freeze_policy_contract.py`, `test_ticker_independence.py` require a live API key — ignore those).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/pages/market-overview.tsx
git commit -m "feat: thread uncertainty_concentration into UncertaintySection on market overview"
```

---

## Self-Review

**Spec coverage:**
- ✅ News-derived sector uncertainty added to `/market-context` response (Task 1)
- ✅ Types added to frontend (Task 2)
- ✅ Lead with sector when `uncertainty_scope === "sector"` (Task 3 Step 6)
- ✅ Fall back to global when `"global"` | `"mixed"` | absent (Task 3 Step 6 — `isSectorLed` is false)
- ✅ 5-signal grid always visible as baseline (Task 3 Step 6 — rendered at `opacity-50` in sector mode, full opacity in global mode)
- ✅ Vol badge on sector chips when `vol_ratio ≥ 1.3` (Task 3 Step 2 — `hasBadge` logic)
- ✅ `high_fraction > 0.5` → error/coral color; else muted gray (Task 3 Step 2 — `isHigh` logic)
- ✅ Max 3 sector chips (Task 3 Step 2 — `topSectors.slice(0, 3)`)
- ✅ No new surface levels or colors (reuses existing pill + `bg-error/10`, `bg-surface-container-highest`)
- ✅ Edge case: fallback when `compute_news_uncertainty` fails (Task 1 — try/except in route)
- ✅ Edge case: field absent / `uncertainty_concentration` null → renders as global (Task 3 — `isSectorLed` is false)
- ✅ Vol pressure row preserved in global mode (Task 3 Step 6 — `!isSectorLed &&` guard)

**Type consistency:** `NewsUncertaintyConcentration` defined in Task 2, imported and used in Task 3. `NewsSectorUncertaintyEntry` defined in Task 2, used as `topSectors` type in `SectorLeadRow`. Consistent throughout.

**Placeholder scan:** No TBDs. All code blocks are complete. All test assertions are concrete.
