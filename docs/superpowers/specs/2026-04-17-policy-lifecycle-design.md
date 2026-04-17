# Policy Lifecycle Design Spec
**Date:** 2026-04-17
**Status:** Approved

## Problem

The existing `policy_tracker.py` uses a flat `"upcoming" | "active" | "revisit_due" | "past"` status model. "Upcoming" collapses two meaningfully distinct phases:

- **Announced** — policy exists but effective date is far out; market is aware but positioning hasn't started
- **Pre-effective** — within the positioning window; smart money is already moving

Without distinguishing these, the tracker can't signal when to act vs. when to monitor.

## Goal

Add a phase-driven lifecycle to policy items:
```
announced → pre_effective → active → revisit_due → past
```

Surface the richer phases in the Headlines page strip (enhanced) and add a compact policy context widget to Market Overview showing only the phases that matter for current decisions (`active`, `revisit_due`).

## Constraints

- Additive only — news ingestion and event analysis pipelines unchanged
- No DB schema changes — policy items are in-memory only
- Date/window logic validated with representative tests

---

## Section 1 — Backend (`policy_tracker.py`)

### 1.1 Registry tuple format

The static `_ITEMS` list grows from 6-element tuples to 7-element tuples, adding `announcement_date` as the 6th element (before `description`):

```python
(name, policy_type, jurisdiction, effective_date, announcement_date, revisit_date, description)
```

### 1.2 Phase thresholds

```python
_PRE_EFFECTIVE_DAYS: dict[str, int] = {
    "rate_decision":   3,
    "tariff":          7,
    "sanction":        7,
    "executive_order": 7,
    "regulation":     30,
}
```

`_REVISIT_WARN_DAYS = 14` and `_PAST_GRACE_DAYS = 30` are unchanged.

### 1.3 Phase derivation

Replace the `if days_until > 0: status = "upcoming"` block with:

```python
pre_eff_threshold = _PRE_EFFECTIVE_DAYS.get(policy_type, 7)

if days_until > pre_eff_threshold:
    status = "announced"
elif days_until > 0:
    status = "pre_effective"
elif days_until_revisit > _REVISIT_WARN_DAYS:
    status = "active"
elif days_until_revisit < 0 and abs(days_until_revisit) > _PAST_GRACE_DAYS:
    status = "past"  # will be filtered out
else:
    status = "revisit_due"
```

### 1.4 `PolicyStatus` type

```python
PolicyStatus = Literal["announced", "pre_effective", "active", "revisit_due", "past"]
```

`"upcoming"` is removed.

### 1.5 Returned dict gains `announcement_date`

```python
results.append({
    "name":             name,
    "policy_type":      policy_type,
    "jurisdiction":     jurisdiction,
    "effective_date":   eff_iso,
    "announcement_date": ann_iso,   # new
    "revisit_date":     rev_iso,
    "description":      description,
    "status":           status,
    "days_until":       days_until,
    "days_until_revisit": days_until_revisit,
})
```

### 1.6 Registry entries with announcement dates

| Item | announcement_date |
|------|-------------------|
| US Reciprocal Tariffs — 10% Baseline | 2026-04-02 |
| US-China Tariffs — 145% | 2026-04-07 |
| EU Retaliatory Tariffs on US Goods | 2026-04-09 |
| USTR Section 301 — China Tech Review | 2025-09-01 |
| ECB Rate Decision | 2026-03-06 |
| Fed FOMC Decision | 2026-03-19 |
| OFAC Russia Sanctions — Energy Expansion | 2026-01-10 |
| EU Carbon Border Adjustment (CBAM) | 2023-05-16 |
| US AI / Chip Export Controls (BIS) | 2025-07-01 |
| Basel III Endgame — US Implementation | 2026-03-15 |
| EU AI Act — High-Risk System Requirements | 2024-05-21 |

---

## Section 2 — Backend Tests (`tests/test_policy_tracker.py`)

### 2.1 Update `TestStatusDerivation`

Replace `test_upcoming_when_effective_in_future` with two tests:

```python
def test_announced_when_effective_far(self):
    # tariff threshold = 7 days; 16 days out → announced
    today = date(2026, 4, 15)
    item = self._single("tariff", "2026-05-01", "2026-08-01", today)
    self.assertEqual(item["status"], "announced")

def test_pre_effective_within_threshold(self):
    # tariff threshold = 7 days; 5 days out → pre_effective
    today = date(2026, 4, 15)
    item = self._single("tariff", "2026-04-20", "2026-07-20", today)
    self.assertEqual(item["status"], "pre_effective")
```

The `_single` helper gains a `policy_type` argument (already used in `_ITEMS` injection; the helper needs to forward the type):

```python
def _single(self, policy_type: str, effective_iso: str, revisit_iso: str, today: date) -> dict:
    import policy_tracker as _mod
    orig = list(_mod._ITEMS)
    _mod._ITEMS = [
        ("Test Policy", policy_type, "US", effective_iso, "2025-01-01", revisit_iso, "desc"),
    ]
    try:
        items = get_policy_items(today=today, days_before=365, days_after=365)
    finally:
        _mod._ITEMS = orig
    return items[0] if items else {}
```

### 2.2 Update `TestFieldPresence`

Add `"announcement_date"` to `REQUIRED`.

### 2.3 Update `TestDaysCalculation`

`test_days_until_positive_for_upcoming` checks `status == "upcoming"` — replace with:
```python
self.assertIn(item["status"], ("announced", "pre_effective"))
```

### 2.4 Update `TestKnownItems`

- `test_ecb_decision_upcoming`: ECB is `rate_decision` (threshold=3). Today=2026-04-15, effective=2026-04-17 → days_until=2 → `pre_effective`. Change assertion to `pre_effective`.
- `test_fed_decision_upcoming`: FOMC is `rate_decision` (threshold=3). Today=2026-04-15, effective=2026-05-07 → days_until=22 → `announced`. Change assertion to `announced`.

### 2.5 Add `TestPhaseThresholds`

New test class validating all 5 policy types cross their threshold correctly:

```python
class TestPhaseThresholds(unittest.TestCase):

    def _phase(self, policy_type: str, days_until: int) -> str:
        from datetime import timedelta
        import policy_tracker as _mod
        today = date(2026, 4, 15)
        effective = (today + timedelta(days=days_until)).isoformat()
        revisit = (today + timedelta(days=days_until + 90)).isoformat()
        orig = list(_mod._ITEMS)
        _mod._ITEMS = [("T", policy_type, "US", effective, "2025-01-01", revisit, "d")]
        try:
            items = get_policy_items(today=today, days_before=365, days_after=365)
        finally:
            _mod._ITEMS = orig
        return items[0]["status"] if items else "excluded"

    def test_rate_decision_threshold_3(self):
        self.assertEqual(self._phase("rate_decision", 4), "announced")
        self.assertEqual(self._phase("rate_decision", 3), "pre_effective")
        self.assertEqual(self._phase("rate_decision", 1), "pre_effective")

    def test_tariff_threshold_7(self):
        self.assertEqual(self._phase("tariff", 8), "announced")
        self.assertEqual(self._phase("tariff", 7), "pre_effective")
        self.assertEqual(self._phase("tariff", 1), "pre_effective")

    def test_sanction_threshold_7(self):
        self.assertEqual(self._phase("sanction", 8), "announced")
        self.assertEqual(self._phase("sanction", 7), "pre_effective")

    def test_executive_order_threshold_7(self):
        self.assertEqual(self._phase("executive_order", 8), "announced")
        self.assertEqual(self._phase("executive_order", 7), "pre_effective")

    def test_regulation_threshold_30(self):
        self.assertEqual(self._phase("regulation", 31), "announced")
        self.assertEqual(self._phase("regulation", 30), "pre_effective")
        self.assertEqual(self._phase("regulation", 1), "pre_effective")
```

---

## Section 3 — Frontend Types (`frontend/src/lib/api.ts`)

```typescript
export type PolicyStatus = "announced" | "pre_effective" | "active" | "revisit_due" | "past";

export interface PolicyItem {
  name: string;
  policy_type: PolicyType;
  jurisdiction: string;
  effective_date: string;
  announcement_date: string;   // new
  revisit_date: string;
  description: string;
  status: PolicyStatus;
  days_until: number;
  days_until_revisit: number;
}
```

---

## Section 4 — Headlines Page Strip (`frontend/src/components/pages/headlines-page.tsx`)

### 4.1 `PolicyItemChip` — phase-driven visual treatment

Replace `isUpcoming / isRevisitDue` with four phase flags:

```typescript
const isAnnounced   = item.status === "announced";
const isPreEff      = item.status === "pre_effective";
const isActive      = item.status === "active";
const isRevisitDue  = item.status === "revisit_due";
```

Border/background per phase:

| Phase | Container classes |
|---|---|
| `announced` | `bg-[#13131a] border-border/15 opacity-75` |
| `pre_effective` | `bg-[#242533] border-[#facc15]/25` (yellow — watch state, already used in codebase) |
| `active` | `bg-[#13131a] border-border/20 opacity-65` |
| `revisit_due` | `bg-[#242533] border-[#ee7d77]/25` (existing) |

Status dot per phase:

| Phase | Dot class |
|---|---|
| `announced` | `bg-[#93d1d3]/30` |
| `pre_effective` | `bg-[#facc15]` (yellow watch dot — already used for "watch" status in stress-strip) |
| `active` | `bg-muted-foreground/25` |
| `revisit_due` | `bg-[#ee7d77]` (existing) |

Timing label per phase:

| Phase | Label |
|---|---|
| `announced` | `"Effective in Nd"` (quiet) |
| `pre_effective` | `"Effective in Nd"` (yellow emphasis) |
| `active` | `_revisitLabel(days_until_revisit)` |
| `revisit_due` | `_revisitLabel(days_until_revisit)` (existing) |

Timing label text color:

| Phase | Color |
|---|---|
| `announced` | `text-muted-foreground/40` |
| `pre_effective` | `text-[#facc15]/80` |
| `active` | `text-muted-foreground/40` |
| `revisit_due` | `text-[#ee7d77]/80` (existing) |

### 4.2 `PolicyTrackerStrip`

No change — the `status !== "past"` filter continues to work with the new status values.

---

## Section 5 — Market Overview Policy Widget (`frontend/src/components/pages/market-overview.tsx`)

### 5.1 New `PolicyContextStrip` component (defined in `market-overview.tsx`)

```tsx
function PolicyContextStrip({ items }: { items: PolicyItem[] }) {
  const visible = items.filter(
    (i) => i.status === "active" || i.status === "revisit_due" || i.status === "pre_effective"
  );
  if (visible.length === 0) return null;
  // ...renders compact chips
}
```

Each chip: type badge · jurisdiction · truncated name · phase label (`"Pre-effective"` / `"Active"` / `"Revisit due"`). The type label mapping (`tariff → "Tariff"`, etc.) is inlined as a local `const` in `market-overview.tsx` — not imported from `headlines-page.tsx` since that constant is private to that module.

No new surface levels. Chip style matches the `bg-[#13131a] border border-border/20` pattern used elsewhere in the market overview.

### 5.2 Placement

Inserted after `RegimeStrip` (section 1b), before `TrendingThemesPanel` (section 1c):

```tsx
{/* 1c. Policy Context — active and revisit-due policy items */}
<PolicyContextStrip items={newsData?.policy_items ?? []} />
```

Uses the existing `newsData` from the `useQuery` already present in the page — no new fetch.

---

## Files to touch

| File | Change |
|------|--------|
| `policy_tracker.py` | Add `_PRE_EFFECTIVE_DAYS`, new `PolicyStatus`, 7-element tuples with `announcement_date`, updated phase derivation |
| `tests/test_policy_tracker.py` | Update status assertions, add `announcement_date` to required fields, add `TestPhaseThresholds` |
| `frontend/src/lib/api.ts` | Expand `PolicyStatus`, add `announcement_date` to `PolicyItem` |
| `frontend/src/components/pages/headlines-page.tsx` | Phase-driven visual treatment in `PolicyItemChip` |
| `frontend/src/components/pages/market-overview.tsx` | Add `PolicyContextStrip` component + insertion point |

## What is NOT changing

- `/news` API endpoint — returns `policy_items` as before, shape is additive
- News ingestion pipeline
- Event analysis pipeline (`/analyze`)
- `policy_constraint.py` (event-analysis side)
- Macro calendar logic
- DB schema
