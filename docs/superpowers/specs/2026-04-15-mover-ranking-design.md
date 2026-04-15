# Mover Ranking: Validated Move Magnitude

**Date:** 2026-04-15
**Status:** Approved

---

## Problem

Market movers are currently ranked by:

```
impact = max(abs(return_5d)) * (1.0 + support_ratio)
```

The `(1 + support_ratio)` multiplier means an event with broad directional confirmation but a smaller raw move can outrank an event with a larger raw move but lower confirmation rate. The biggest realized moves should lead — not events the model felt most confident about.

---

## Goal

Use the strongest **validated realized move** as the primary ordering signal. A "validated move" is the maximum absolute 5-day return among tickers where `direction_tag` starts with `"supports"` — i.e., tickers where the actual market move confirmed the model's predicted direction.

---

## Design

### New field: `validated_max_move`

Computed per event during mover assembly in `api.py`:

```python
validated_max_move = max(
    (abs(t["return_5d"]) for t in big_moves
     if t.get("direction_tag", "").startswith("supports")
     and t["return_5d"] is not None),
    default=0.0,
)
```

- `0.0` when no supporting tickers exist — event falls to bottom of rankings.
- Non-supporting tickers (contradicts, unknown) do not contribute.

### Sort key change

```python
# Before
scored.sort(key=lambda x: x["impact"], reverse=True)

# After
scored.sort(key=lambda x: (x["validated_max_move"], x["impact"]), reverse=True)
```

`impact` is retained as tiebreaker and remains in the payload unchanged.

### Persistent movers secondary sort

`/movers/persistent` sorts primarily by `days_since_event` desc. Its secondary key currently uses `impact`. This also switches to `validated_max_move` for consistency.

### Payload

`validated_max_move` is added to every mover record. `impact` is preserved. No fields removed. Route shapes unchanged.

```json
{
  "impact": 4.2,
  "validated_max_move": 3.1
}
```

### Qualification threshold

Unchanged. Events still require `abs(return_5d) >= 1.5%` on any ticker to appear in the market-movers surface. The new field only affects ordering.

---

## Affected Files

| File | Change |
|------|--------|
| `api.py` | Add `validated_max_move` computation; change sort key; add field to payload |
| `movers_cache.py` | Bump `_CACHE_VERSION` by 1 to invalidate stale cached slices |
| `tests/test_mover_ranking.py` | New — focused tests for ranking logic |

No frontend changes. No schema changes.

---

## Tests

New file: `tests/test_mover_ranking.py`

| Test | Validates |
|------|-----------|
| `test_validated_max_uses_supporting_only` | Only supporting tickers contribute to validated_max_move |
| `test_non_supporting_excluded` | Contradicting/unknown tickers don't inflate the score |
| `test_zero_support_gives_zero` | Events with no supporting tickers → 0.0 |
| `test_sort_confirmed_above_larger_raw_move` | Smaller confirmed move ranks above larger unconfirmed move |
| `test_tiebreaker_uses_impact` | Equal validated_max_move → higher impact wins |

Existing tests unaffected except `movers_cache` version assertions, which are updated to match the new version number.

---

## Behavior Summary

`direction_tag` is the backend field (set by `market_check.py`). Values: `"supports ↑"`, `"supports ↓"`, `"contradicts ↑"`, `"contradicts ↓"`. Frontend displays this as the `direction` field — only the backend `direction_tag` is used for scoring.

| Scenario | Before | After |
|----------|--------|-------|
| 5% confirmed move (all supporting) | impact=10.0, ranks high | validated=5.0, ranks high |
| 8% raw move, 0% support | impact=8.0, outranks 5%+100% event | validated=0.0, falls to bottom |
| Event A: max supporting=3%, max raw=3% vs Event B: max supporting=2%, max raw=4% (big move was contradicting) | 3×1.0=3.0 vs 4×1.5=6.0 — B wins on raw | validated 3.0 vs 2.0 — A wins on confirmed move |
| Mixed tickers (some supporting, some contradicting) | max raw move across all tickers | max move among supporting tickers only |
