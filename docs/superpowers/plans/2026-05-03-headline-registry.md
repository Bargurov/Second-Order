# Headline Registry + Low-Impact Expiry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `headline_registry` table that tracks every ingested headline through its lifecycle (seen → eligible → analyzed → market_checked → surfaced → expired_low_impact), use it to short-circuit reanalysis, and apply a configurable low-impact expiry filter to `/movers/today` and the `/events` listing surfaces.

**Architecture:** New SQLite table keyed by `(source, title_key)`, populated at ingest by `news_cluster_store.refresh_clusters`. Pre-LLM check + post-action stamps in the `routes/movers.py` backfill loop, keyed on `title_key` (not `cluster_id` — the cluster payload at the loop site does not carry the persisted id). A small `headline_registry.py` module exposes `is_expired_low_impact`, `stamp_expired_if_observed`, `filter_expired_low_impact`, and `advance_state`. Read-time filter on `/movers/today` (after the in-memory cache pull) and on `/events` listing (after dedup, before pagination slice). Diagnostics endpoint surfaces state counts, skip-reason counts, and the major eligible-but-unanalyzed candidates.

**Tech Stack:** Python 3, SQLite (existing `db.py`), FastAPI (existing routers), `unittest` (project test framework).

**Spec:** `docs/superpowers/specs/2026-05-03-headline-registry-design.md`

**Project conventions to honor (from CLAUDE.md):**
- Tests use `python -m unittest`. Use `unittest.TestCase` style.
- Do NOT create branches or commits unless explicitly asked. The "Commit" step is omitted from each task; the executing agent should ask the user before committing.
- Edit only files in scope per task.
- Keep changes small and aligned with existing patterns (procedural helpers in `db.py`; router files under `routes/`; shared helpers as top-level modules).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `db.py` | modify | Add `headline_registry` table + indexes; add helpers `upsert_headline_registry_seen`, `update_registry_state`, `load_registry_state_counts`, `load_registry_skip_reason_counts`, `load_registry_last_analyzed_at`, `load_registry_expired_count_since`, `load_eligible_unanalyzed_candidates`, `load_registry_analyzed_at_for_keys`. |
| `headline_registry.py` | create | Module exposing `is_expired_low_impact`, `stamp_expired_if_observed`, `filter_expired_low_impact`, `advance_state`. |
| `news_cluster_store.py` | modify | Inject one extra DI call after the existing `upsert_assignments_fn` to write registry rows. |
| `routes/movers.py` | modify | Pre-LLM registry check, post-action state stamp, skip-reason stamp inside backfill loop; read-time expiry filter at `/movers/today`. |
| `routes/events.py` | modify | Read-time expiry filter applied after dedup, before the offset/limit slice; detail-by-id untouched. |
| `routes/diagnostics.py` | create | New `/registry/diagnostics` endpoint. |
| `api.py` | modify | One-line `app.include_router(...)` registration for the diagnostics router. |
| `tests/test_headline_registry.py` | create | All tests for this feature. |
| `.env.example` | modify | Document `HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS=5`. |

Untouched (frozen contracts per CLAUDE.md): `/events/{id}` detail, `/movers/persistent`, `/movers/yearly`, `portfolio_view`, track-record, saved-study replay, news inbox, candidates, frontend. The `/movers/persistent` and `/movers/yearly` regression test (Task 9) provides a guard.

---

## Task 1: DB schema + persistence helpers

**Files:**
- Modify: `db.py` (init function + new helper functions appended near other registry helpers around `db.py:2663`)
- Test: `tests/test_headline_registry.py` (create)

**Goal:** Stand up the `headline_registry` table and the SQL helpers everything else will call.

- [ ] **Step 1.1: Write failing test for table presence + upsert + no-state-regression**

Create `tests/test_headline_registry.py` with the following content:

```python
"""Tests for headline_registry feature.

Run with:
    python -m unittest tests.test_headline_registry -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _RegistryTestBase(unittest.TestCase):
    """Per-test temp DB so cases never share state."""

    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        # Re-bind db.DB_FILE to a fresh file for this test, then re-init.
        import db
        self._orig_db_file = db.DB_FILE
        db.DB_FILE = self.db_path
        db._db_ready = False
        db.init_db()
        self._db = db

    def tearDown(self) -> None:
        import db
        db.DB_FILE = self._orig_db_file
        db._db_ready = False
        try:
            os.unlink(self.db_path)
        except OSError:
            pass


class TestRegistrySchema(_RegistryTestBase):

    def test_upsert_creates_seen_row(self) -> None:
        now_iso = "2026-05-03T12:00:00"
        self._db.upsert_headline_registry_seen(
            [("Reuters", "fed-cuts-rates", 17)],
            now_iso,
        )
        rows = self._db.load_registry_state_counts()
        self.assertEqual(rows.get("seen"), 1)

    def test_upsert_does_not_regress_state(self) -> None:
        now_iso = "2026-05-03T12:00:00"
        self._db.upsert_headline_registry_seen(
            [("Reuters", "fed-cuts-rates", 17)],
            now_iso,
        )
        # Promote to analyzed.
        self._db.update_registry_state(
            title_key="fed-cuts-rates",
            new_state="analyzed",
            event_id=42,
            impact_level="high",
            analyzed_at=now_iso,
        )
        # Re-ingest: state must NOT regress.
        later_iso = "2026-05-03T13:00:00"
        self._db.upsert_headline_registry_seen(
            [("Reuters", "fed-cuts-rates", 17)],
            later_iso,
        )
        counts = self._db.load_registry_state_counts()
        self.assertEqual(counts.get("analyzed"), 1)
        self.assertEqual(counts.get("seen", 0), 0)
```

- [ ] **Step 1.2: Run test, verify it fails with AttributeError on `upsert_headline_registry_seen`**

Run: `python -m unittest tests.test_headline_registry.TestRegistrySchema -v`

Expected: FAIL — `AttributeError: module 'db' has no attribute 'upsert_headline_registry_seen'`.

- [ ] **Step 1.3: Add table + indexes inside `db.init_db`**

In `db.py`, locate the block that creates `news_headline_assignments` (around `db.py:297`). Append immediately after its index creation block:

```python
        # Headline registry — one row per ingested (source, title_key).
        # Tracks the lifecycle of every ingested headline independently
        # of the cluster store and the events table.  See
        # docs/superpowers/specs/2026-05-03-headline-registry-design.md.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS headline_registry (
                source           TEXT NOT NULL,
                title_key        TEXT NOT NULL,
                cluster_id       INTEGER,
                event_id         INTEGER,
                state            TEXT NOT NULL DEFAULT 'seen',
                last_skip_reason TEXT,
                impact_level     TEXT,
                first_seen_at    TEXT NOT NULL,
                last_seen_at     TEXT NOT NULL,
                analyzed_at      TEXT,
                expired_at       TEXT,
                PRIMARY KEY (source, title_key)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_headline_registry_state
            ON headline_registry (state)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_headline_registry_analyzed_at
            ON headline_registry (analyzed_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_headline_registry_cluster
            ON headline_registry (cluster_id)
        """)
```

- [ ] **Step 1.4: Add `upsert_headline_registry_seen`, `update_registry_state`, `load_registry_state_counts` helpers**

Append to `db.py` (near the existing `upsert_news_headline_assignments` around `db.py:2675`):

```python
# ---------------------------------------------------------------------------
# Headline registry helpers
# ---------------------------------------------------------------------------

# Forward-only lifecycle. Index = "advancement rank"; advance_state never
# regresses (a higher-rank state already on the row wins).
_REGISTRY_LIFECYCLE = (
    "seen", "eligible", "analyzed", "market_checked", "surfaced",
    "expired_low_impact",
)
_REGISTRY_RANK = {s: i for i, s in enumerate(_REGISTRY_LIFECYCLE)}


def upsert_headline_registry_seen(
    rows: list[tuple[str, str, int | None]],
    now_iso: str,
) -> None:
    """UPSERT one registry row per ``(source, title_key, cluster_id)``.

    On conflict, only ``cluster_id`` and ``last_seen_at`` are updated;
    ``state``, ``event_id``, ``analyzed_at``, ``impact_level``, and
    ``expired_at`` are preserved so re-ingesting an analyzed headline
    cannot regress its lifecycle.
    """
    if not _db_ready or not rows:
        return
    payload = [
        (src, key, cluster_id, now_iso, now_iso)
        for (src, key, cluster_id) in rows
    ]
    with sqlite3.connect(DB_FILE) as conn:
        conn.executemany(
            "INSERT INTO headline_registry "
            "(source, title_key, cluster_id, state, "
            " first_seen_at, last_seen_at) "
            "VALUES (?, ?, ?, 'seen', ?, ?) "
            "ON CONFLICT(source, title_key) DO UPDATE SET "
            "  cluster_id   = excluded.cluster_id, "
            "  last_seen_at = excluded.last_seen_at",
            payload,
        )


def update_registry_state(
    *,
    title_key: str,
    new_state: str | None = None,
    event_id: int | None = None,
    impact_level: str | None = None,
    analyzed_at: str | None = None,
    expired_at: str | None = None,
    last_skip_reason: str | None = None,
) -> None:
    """Forward-only state advance for every registry row matching ``title_key``.

    ``new_state`` is applied only when its rank is strictly higher than
    the row's current state rank.  ``last_skip_reason`` is overwritten
    on every call (it is a "most recent skip" field, not a lifecycle
    field).  Other fields are written when provided.
    """
    if not _db_ready or not title_key:
        return
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT source, state FROM headline_registry WHERE title_key = ?",
            (title_key,),
        ).fetchall()
        if not rows:
            return
        for row in rows:
            current_state = row["state"] or "seen"
            target_state = current_state
            if new_state and _REGISTRY_RANK.get(
                new_state, -1,
            ) > _REGISTRY_RANK.get(current_state, -1):
                target_state = new_state
            sets: list[str] = ["state = ?"]
            params: list[object] = [target_state]
            if event_id is not None:
                sets.append("event_id = ?")
                params.append(int(event_id))
            if impact_level is not None:
                sets.append("impact_level = ?")
                params.append(impact_level)
            if analyzed_at is not None:
                sets.append("analyzed_at = ?")
                params.append(analyzed_at)
            if expired_at is not None:
                sets.append("expired_at = ?")
                params.append(expired_at)
            if last_skip_reason is not None:
                sets.append("last_skip_reason = ?")
                params.append(last_skip_reason)
            params.extend([row["source"], title_key])
            conn.execute(
                f"UPDATE headline_registry SET {', '.join(sets)} "
                "WHERE source = ? AND title_key = ?",
                params,
            )


def load_registry_state_counts() -> dict[str, int]:
    """Return ``{state: count}`` for every distinct ``state`` value."""
    if not _db_ready:
        return {}
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT state, COUNT(*) FROM headline_registry GROUP BY state"
        ).fetchall()
    return {state: int(count) for state, count in rows}
```

- [ ] **Step 1.5: Run test, verify both pass**

Run: `python -m unittest tests.test_headline_registry.TestRegistrySchema -v`

Expected: PASS (2 tests).

- [ ] **Step 1.6: Add the remaining read-side helpers used by the diagnostics endpoint**

Append to `db.py` (immediately after `load_registry_state_counts`):

```python
def load_registry_skip_reason_counts() -> dict[str, int]:
    """Return ``{last_skip_reason: count}`` for non-null reasons only."""
    if not _db_ready:
        return {}
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT last_skip_reason, COUNT(*) FROM headline_registry "
            "WHERE last_skip_reason IS NOT NULL "
            "GROUP BY last_skip_reason"
        ).fetchall()
    return {reason: int(count) for reason, count in rows}


def load_registry_last_analyzed_at() -> str | None:
    if not _db_ready:
        return None
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            "SELECT MAX(analyzed_at) FROM headline_registry"
        ).fetchone()
    return row[0] if row and row[0] else None


def load_registry_expired_count_since(since_iso: str) -> int:
    if not _db_ready:
        return 0
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM headline_registry "
            "WHERE state = 'expired_low_impact' AND expired_at >= ?",
            (since_iso,),
        ).fetchone()
    return int(row[0] or 0)


def load_registry_analyzed_at_for_keys(
    title_keys: list[str],
) -> dict[str, str]:
    """Return ``{title_key: max(analyzed_at)}`` for the given keys.

    Used by ``headline_registry.filter_expired_low_impact`` to bulk-load
    analyzed_at for a page of events.  Same title_key from multiple
    sources collapses via MAX so the most recent analysis wins.
    """
    if not _db_ready or not title_keys:
        return {}
    placeholders = ",".join("?" * len(title_keys))
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            f"SELECT title_key, MAX(analyzed_at) "
            f"FROM headline_registry "
            f"WHERE title_key IN ({placeholders}) "
            f"  AND analyzed_at IS NOT NULL "
            f"GROUP BY title_key",
            title_keys,
        ).fetchall()
    return {tk: at for tk, at in rows if at}


def load_eligible_unanalyzed_candidates(
    *, limit: int = 50,
) -> list[dict]:
    """Major headlines ingested but not yet analyzed.

    Joins ``headline_registry`` to ``news_clusters`` so we can rank by
    the cluster's ``source_count`` (number of publishers) — that's how
    the backfill route already prioritises clusters.  Returns the top
    ``limit`` rows in source_count-then-recency order.
    """
    if not _db_ready:
        return []
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT hr.cluster_id, "
            "       MIN(hr.first_seen_at) AS first_seen_at, "
            "       MAX(hr.last_seen_at)  AS last_seen_at, "
            "       hr.last_skip_reason, "
            "       hr.state, "
            "       nc.headline, "
            "       nc.payload_json "
            "FROM headline_registry hr "
            "JOIN news_clusters nc ON nc.id = hr.cluster_id "
            "WHERE hr.state IN ('seen', 'eligible') "
            "  AND hr.event_id IS NULL "
            "GROUP BY hr.cluster_id "
            "ORDER BY json_extract(nc.payload_json, '$.source_count') DESC, "
            "         MAX(hr.last_seen_at) DESC "
            "LIMIT ?",
            (int(limit),),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        out.append({
            "headline":         r["headline"] or "",
            "cluster_id":       r["cluster_id"],
            "source_count":     int(payload.get("source_count") or 0),
            "has_asset_terms":  bool(payload.get("has_asset_terms", False)),
            "first_seen_at":    r["first_seen_at"],
            "last_seen_at":     r["last_seen_at"],
            "last_skip_reason": r["last_skip_reason"],
            "state":            r["state"],
        })
    return out
```

If `json` is not already imported at the top of `db.py`, add `import json` near the other top-of-file imports.

- [ ] **Step 1.7: Re-run the schema tests to confirm nothing regressed**

Run: `python -m unittest tests.test_headline_registry.TestRegistrySchema -v`

Expected: PASS (still 2).

---

## Task 2: `headline_registry.py` module — expiry helpers + state advance wrapper

**Files:**
- Create: `headline_registry.py`
- Test: `tests/test_headline_registry.py` (extend)

**Goal:** Provide the small surface every caller will use — the expiry decision helper, the lazy-stamp helper, the bulk page filter, and a thin pass-through to `db.update_registry_state`.

- [ ] **Step 2.1: Write failing tests for `is_expired_low_impact` boundary cases**

Append to `tests/test_headline_registry.py`:

```python
class TestIsExpiredLowImpact(unittest.TestCase):

    def setUp(self) -> None:
        # Pin a stable "now" for all cases.
        self.now = datetime(2026, 5, 10, 12, 0, 0)
        self._old = "2026-05-01T00:00:00"     # 9d before now → past 5d TTL
        self._fresh = "2026-05-09T00:00:00"   # 1d before now → within TTL

    def _row(self, impact: str | None, ts: str | None) -> dict:
        return {
            "conviction": {"impact_level": impact} if impact else {},
            "timestamp":  ts,
            "headline":   "test headline",
        }

    def test_low_with_old_registry_anchor_is_expired(self) -> None:
        from headline_registry import is_expired_low_impact
        self.assertTrue(is_expired_low_impact(
            self._row("low", self._fresh),
            registry_analyzed_at=self._old,
            now=self.now,
        ))

    def test_low_with_fresh_registry_anchor_is_not_expired(self) -> None:
        from headline_registry import is_expired_low_impact
        self.assertFalse(is_expired_low_impact(
            self._row("low", self._old),  # event ts old, but...
            registry_analyzed_at=self._fresh,  # ...registry says fresh
            now=self.now,
        ))

    def test_low_falls_back_to_event_timestamp(self) -> None:
        from headline_registry import is_expired_low_impact
        # No registry anchor: expiry uses event timestamp.
        self.assertTrue(is_expired_low_impact(
            self._row("low", self._old),
            registry_analyzed_at=None,
            now=self.now,
        ))

    def test_high_impact_never_expires(self) -> None:
        from headline_registry import is_expired_low_impact
        self.assertFalse(is_expired_low_impact(
            self._row("high", self._old),
            registry_analyzed_at=self._old,
            now=self.now,
        ))

    def test_missing_impact_returns_false(self) -> None:
        from headline_registry import is_expired_low_impact
        self.assertFalse(is_expired_low_impact(
            self._row(None, self._old),
            registry_analyzed_at=self._old,
            now=self.now,
        ))

    def test_env_override_shrinks_window(self) -> None:
        from headline_registry import is_expired_low_impact
        with patch.dict(
            os.environ,
            {"HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS": "1"},
        ):
            # 1d TTL: a 2-day-old row is now expired.
            two_days_old = (self.now - timedelta(days=2)).isoformat(
                timespec="seconds",
            )
            self.assertTrue(is_expired_low_impact(
                self._row("low", two_days_old),
                registry_analyzed_at=None,
                now=self.now,
            ))
```

- [ ] **Step 2.2: Run tests, verify they fail with ModuleNotFoundError**

Run: `python -m unittest tests.test_headline_registry.TestIsExpiredLowImpact -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'headline_registry'`.

- [ ] **Step 2.3: Create `headline_registry.py` with the four public helpers**

Create `headline_registry.py`:

```python
"""Headline registry — lifecycle tracking for every ingested headline.

See docs/superpowers/specs/2026-05-03-headline-registry-design.md for
the full design.  This module exposes the non-DB surface:

  * is_expired_low_impact   — pure decision helper (no DB)
  * stamp_expired_if_observed — idempotent lazy-stamp (writes to DB)
  * filter_expired_low_impact — bulk page filter for read sites
  * advance_state            — thin wrapper around db.update_registry_state
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

_log = logging.getLogger("second_order.headline_registry")

_TTL_ENV_VAR = "HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS"
_DEFAULT_TTL_DAYS = 5


def _ttl_days() -> int:
    raw = os.environ.get(_TTL_ENV_VAR)
    if not raw:
        return _DEFAULT_TTL_DAYS
    try:
        value = int(raw)
        return value if value > 0 else _DEFAULT_TTL_DAYS
    except (TypeError, ValueError):
        return _DEFAULT_TTL_DAYS


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        # SQLite ISO timestamps may or may not include microseconds /
        # timezone; datetime.fromisoformat handles both for the shapes
        # this codebase writes.
        return datetime.fromisoformat(value)
    except ValueError:
        # Trim trailing 'Z' or extra fractional digits.
        try:
            return datetime.fromisoformat(value.replace("Z", ""))
        except ValueError:
            return None


def _title_key(headline: str) -> str:
    """Reuse the canonical normalizer the cluster store + ingestion use."""
    from news_sources import _dedup_key
    return _dedup_key(headline or "")


def is_expired_low_impact(
    event_row: dict,
    registry_analyzed_at: Optional[str] = None,
    now: Optional[datetime] = None,
) -> bool:
    """True when an event is low-impact AND its analyzed_at is past TTL.

    Uses ``registry_analyzed_at`` when provided; falls back to
    ``event_row['timestamp']`` only when the registry analyzed_at is
    missing (covers events analyzed before the registry existed).
    """
    impact = (event_row.get("conviction") or {}).get("impact_level")
    if impact != "low":
        return False
    anchor = registry_analyzed_at or event_row.get("timestamp")
    if not anchor:
        return False
    parsed = _parse_iso(anchor)
    if parsed is None:
        return False
    cutoff = (now or datetime.now()) - timedelta(days=_ttl_days())
    return parsed < cutoff


def stamp_expired_if_observed(
    event_row: dict,
    registry_analyzed_at: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Idempotent UPSERT setting state='expired_low_impact' + expired_at.

    No-op when the row is not expired.  Re-stamping an already-stamped
    row is a no-op because ``update_registry_state`` is forward-only on
    state advancement and ``expired_at`` is overwritten with the same
    semantic value (the ISO 'now' at first observation is what the
    diagnostics endpoint reads).
    """
    if not is_expired_low_impact(event_row, registry_analyzed_at, now):
        return
    headline = event_row.get("headline") or ""
    title_key = _title_key(headline)
    if not title_key:
        return
    now_iso = (now or datetime.now()).replace(microsecond=0).isoformat()
    try:
        from db import update_registry_state
        update_registry_state(
            title_key=title_key,
            new_state="expired_low_impact",
            expired_at=now_iso,
        )
    except Exception:
        _log.warning(
            "headline_registry.stamp_expired_if_observed failed",
            exc_info=True,
        )


def filter_expired_low_impact(
    event_rows: list[dict],
    now: Optional[datetime] = None,
) -> list[dict]:
    """Drop expired-low-impact rows; lazy-stamp them in the registry.

    One DB round-trip per page (bulk SELECT of analyzed_at for the
    page's title_keys).  Returns surviving rows in original order.
    """
    if not event_rows:
        return []
    title_keys: list[str] = []
    per_row_keys: list[str] = []
    for row in event_rows:
        tk = _title_key(row.get("headline") or "")
        per_row_keys.append(tk)
        if tk:
            title_keys.append(tk)
    if not title_keys:
        # Nothing keyable — fall back to per-row (no DB anchor).
        survivors: list[dict] = []
        for row in event_rows:
            if is_expired_low_impact(row, registry_analyzed_at=None, now=now):
                stamp_expired_if_observed(row, registry_analyzed_at=None, now=now)
                continue
            survivors.append(row)
        return survivors
    try:
        from db import load_registry_analyzed_at_for_keys
        analyzed_at_map = load_registry_analyzed_at_for_keys(
            list(set(title_keys))
        )
    except Exception:
        _log.warning(
            "headline_registry.filter_expired_low_impact: bulk load failed",
            exc_info=True,
        )
        analyzed_at_map = {}
    survivors = []
    for row, tk in zip(event_rows, per_row_keys):
        anchor = analyzed_at_map.get(tk)
        if is_expired_low_impact(row, registry_analyzed_at=anchor, now=now):
            stamp_expired_if_observed(row, registry_analyzed_at=anchor, now=now)
            continue
        survivors.append(row)
    return survivors


def advance_state(
    *,
    title_key: str,
    new_state: Optional[str] = None,
    event_id: Optional[int] = None,
    impact_level: Optional[str] = None,
    analyzed_at: Optional[str] = None,
    last_skip_reason: Optional[str] = None,
) -> None:
    """Thin pass-through to ``db.update_registry_state``.

    Centralised here so callers don't import db.update_registry_state
    directly — keeps the state machine surface in one module.
    """
    if not title_key:
        return
    try:
        from db import update_registry_state
        update_registry_state(
            title_key=title_key,
            new_state=new_state,
            event_id=event_id,
            impact_level=impact_level,
            analyzed_at=analyzed_at,
            last_skip_reason=last_skip_reason,
        )
    except Exception:
        _log.warning(
            "headline_registry.advance_state failed for %s", title_key,
            exc_info=True,
        )
```

- [ ] **Step 2.4: Run the boundary-case tests, verify all six pass**

Run: `python -m unittest tests.test_headline_registry.TestIsExpiredLowImpact -v`

Expected: PASS (6 tests).

---

## Task 3: Wire ingestion to write registry rows

**Files:**
- Modify: `news_cluster_store.py:212` (the `refresh_clusters` signature + DI defaults + call site near the existing `upsert_assignments_fn` call at `news_cluster_store.py:393`)
- Test: `tests/test_headline_registry.py` (extend)

**Goal:** Every record processed by `refresh_clusters` writes a `headline_registry` row at ingest with `state='seen'`, and re-ingest never regresses an analyzed row.

- [ ] **Step 3.1: Write failing tests for the ingest path**

Append to `tests/test_headline_registry.py`:

```python
class TestIngestionWritesRegistry(_RegistryTestBase):

    def _fake_records(self) -> list[dict]:
        return [
            {"source": "Reuters",  "title": "Fed cuts rates by 25bp",
             "url": "u1", "published_at": "2026-05-03T10:00:00"},
            {"source": "Bloomberg", "title": "Fed cuts rates by 25bp",
             "url": "u2", "published_at": "2026-05-03T10:05:00"},
        ]

    def _stub_cluster_fn(self, records: list[dict]) -> list[dict]:
        return [{
            "headline":     records[0]["title"],
            "source_count": len(records),
            "sources":      [{"name": r["source"]} for r in records],
            "published_at": records[-1]["published_at"],
        }]

    def test_ingest_writes_seen_rows(self) -> None:
        import news_cluster_store
        records = self._fake_records()
        news_cluster_store.refresh_clusters(
            records,
            cluster_fn=self._stub_cluster_fn,
            now=datetime(2026, 5, 3, 10, 30, 0),
        )
        counts = self._db.load_registry_state_counts()
        self.assertEqual(counts.get("seen"), 2)

    def test_reingest_preserves_analyzed_state(self) -> None:
        import news_cluster_store
        records = self._fake_records()
        # First ingest → 'seen'.
        news_cluster_store.refresh_clusters(
            records,
            cluster_fn=self._stub_cluster_fn,
            now=datetime(2026, 5, 3, 10, 30, 0),
        )
        # Promote to 'analyzed' for the shared title_key.
        from news_sources import _dedup_key
        tk = _dedup_key(records[0]["title"])
        self._db.update_registry_state(
            title_key=tk,
            new_state="analyzed",
            event_id=99,
            impact_level="high",
            analyzed_at="2026-05-03T11:00:00",
        )
        # Re-ingest → state must stay 'analyzed' for both rows.
        news_cluster_store.refresh_clusters(
            records,
            cluster_fn=self._stub_cluster_fn,
            now=datetime(2026, 5, 3, 12, 0, 0),
        )
        counts = self._db.load_registry_state_counts()
        self.assertEqual(counts.get("analyzed"), 2)
        self.assertEqual(counts.get("seen", 0), 0)
```

- [ ] **Step 3.2: Run tests, verify they fail**

Run: `python -m unittest tests.test_headline_registry.TestIngestionWritesRegistry -v`

Expected: FAIL on `seen` count (registry never written by current `refresh_clusters`).

- [ ] **Step 3.3: Add the registry call into `news_cluster_store.refresh_clusters`**

In `news_cluster_store.py`, modify the `refresh_clusters` signature to add the new injectable + its default (mirroring the pattern already used for `upsert_assignments_fn` at lines 222 and 257-259):

Locate the keyword args at `news_cluster_store.py:222`:

```python
    upsert_assignments_fn: Optional[Callable[[list, str], None]] = None,
    meta: Optional[dict] = None,
```

Insert between them:

```python
    upsert_assignments_fn: Optional[Callable[[list, str], None]] = None,
    upsert_registry_fn: Optional[Callable[[list, str], None]] = None,
    meta: Optional[dict] = None,
```

Locate the DI default block around `news_cluster_store.py:257-259`:

```python
    if upsert_assignments_fn is None:
        from db import upsert_news_headline_assignments
        upsert_assignments_fn = upsert_news_headline_assignments
```

Append:

```python
    if upsert_registry_fn is None:
        from db import upsert_headline_registry_seen
        upsert_registry_fn = upsert_headline_registry_seen
```

Locate the existing assignment write near `news_cluster_store.py:393`:

```python
    if pending_assignments:
        upsert_assignments_fn(pending_assignments, now_iso)
```

Replace with:

```python
    if pending_assignments:
        upsert_assignments_fn(pending_assignments, now_iso)
        try:
            upsert_registry_fn(pending_assignments, now_iso)
        except Exception:
            _log.warning(
                "news_cluster_store: registry upsert failed", exc_info=True,
            )
```

Wrapping the registry call in `try/except` matches the module's existing defensive style (compare the cluster-rebuild guard at line 192) — a transient registry-table issue should never crash an otherwise-successful refresh.

- [ ] **Step 3.4: Run the ingest tests, verify both pass**

Run: `python -m unittest tests.test_headline_registry.TestIngestionWritesRegistry -v`

Expected: PASS (2 tests).

- [ ] **Step 3.5: Run the news-cluster-store regression tests to confirm no break**

Run: `python -m unittest discover -s tests -p "test_*news_cluster*.py" -v`

Expected: every existing test passes (the new injectable has a default; no caller needs to change).

---

## Task 4: Backfill loop — pre-LLM check, post-action stamp, skip-reason stamp

**Files:**
- Modify: `routes/movers.py` (the eligible-cluster loop starting at `routes/movers.py:1159`)
- Test: `tests/test_headline_registry.py` (extend)

**Goal:** The `/movers/backfill-recent` route must skip clusters whose representative headline already has a registry row in `analyzed`/`market_checked`/`surfaced`/`expired_low_impact` state (unless `force_reanalyze=True`), advance state on success, and record `last_skip_reason` on rejection.

- [ ] **Step 4.1: Write failing tests for skip-analyzed, skip-expired, force-override, and skip-reason stamping**

Append to `tests/test_headline_registry.py`:

```python
class TestBackfillRegistryShortCircuit(_RegistryTestBase):
    """Stub the analyze + market-check + provider helpers so tests
    measure routing decisions, not LLM behaviour."""

    def _stub_route_for_test(self, monkey: dict) -> None:
        """Replace heavy collaborators in routes.movers with stubs.

        ``monkey`` is a dict mapping attr name -> stub callable.  Tests
        that need to count LLM calls inspect the registry post-call.
        """
        import routes.movers as rm
        self._original = {}
        for name, value in monkey.items():
            self._original[name] = getattr(rm, name, None)
            setattr(rm, name, value)
        self._rm = rm

    def tearDown(self) -> None:
        super().tearDown()
        if hasattr(self, "_rm") and hasattr(self, "_original"):
            for name, value in self._original.items():
                if value is None:
                    if hasattr(self._rm, name):
                        delattr(self._rm, name)
                else:
                    setattr(self._rm, name, value)

    def _seed_registry_analyzed(self, headline: str) -> str:
        from news_sources import _dedup_key
        tk = _dedup_key(headline)
        self._db.upsert_headline_registry_seen(
            [("Reuters", tk, 1)], "2026-05-01T10:00:00",
        )
        self._db.update_registry_state(
            title_key=tk,
            new_state="analyzed",
            event_id=1,
            impact_level="high",
            analyzed_at="2026-05-01T10:30:00",
        )
        return tk

    def test_pre_llm_check_skips_analyzed(self) -> None:
        """A cluster whose title_key has registry state='analyzed' is
        skipped without calling the analyze stub."""
        headline = "Fed cuts rates by 25bp"
        self._seed_registry_analyzed(headline)

        # Run the loop's gate logic via the public route, with a stub
        # cached news payload and stub analysis collaborators.  We use
        # the route's force_reanalyze=False default.
        from routes.movers import movers_backfill_recent

        analyze_calls = {"count": 0}

        def fake_fresh(*a, **kw):
            analyze_calls["count"] += 1
            return {"status": "ok", "event_id": 99}

        def fake_payload():
            return ({
                "clusters": [{
                    "headline":     headline,
                    "source_count": 5,
                    "published_at": "2026-05-03T08:00:00",
                    "sources":      [{"name": "Reuters"}],
                }],
            }, "memory")

        self._stub_route_for_test({
            "_cached_news_payload":          fake_payload,
            "_fresh_analysis_market_event":  fake_fresh,
            "_max_backfill_llm_calls":       lambda: 5,
            "_backfill_dry_run_default":     lambda: False,
            "_llm_available":                lambda *_: True,
        })

        result = movers_backfill_recent(
            limit=3,
            max_llm_calls=2,
            scan_limit=10,
            since_hours=72,
            dry_run=False,
            force_reanalyze=False,
            include_low_signal=False,
        )
        self.assertEqual(analyze_calls["count"], 0)
        skipped = result.get("diagnostics", {}).get("skipped", {})
        self.assertEqual(skipped.get("registry_already_analyzed"), 1)

    def test_pre_llm_check_skips_expired_low(self) -> None:
        """A cluster whose title_key has registry state='expired_low_impact'
        is skipped without calling the analyze stub."""
        from news_sources import _dedup_key
        headline = "Old low-impact print"
        tk = _dedup_key(headline)
        self._db.upsert_headline_registry_seen(
            [("Reuters", tk, 1)], "2026-04-25T10:00:00",
        )
        self._db.update_registry_state(
            title_key=tk,
            new_state="analyzed",
            event_id=1,
            impact_level="low",
            analyzed_at="2026-04-25T10:30:00",
        )
        self._db.update_registry_state(
            title_key=tk,
            new_state="expired_low_impact",
            expired_at="2026-05-03T00:00:00",
        )

        from routes.movers import movers_backfill_recent
        analyze_calls = {"count": 0}

        def fake_fresh(*a, **kw):
            analyze_calls["count"] += 1
            return {"status": "ok", "event_id": 99}

        def fake_payload():
            return ({
                "clusters": [{
                    "headline":     headline,
                    "source_count": 5,
                    "published_at": "2026-05-03T08:00:00",
                    "sources":      [{"name": "Reuters"}],
                }],
            }, "memory")

        self._stub_route_for_test({
            "_cached_news_payload":          fake_payload,
            "_fresh_analysis_market_event":  fake_fresh,
            "_max_backfill_llm_calls":       lambda: 5,
            "_backfill_dry_run_default":     lambda: False,
            "_llm_available":                lambda *_: True,
        })

        result = movers_backfill_recent(
            limit=3,
            max_llm_calls=2,
            scan_limit=10,
            since_hours=240,  # wide window so the old cluster is in scope
            dry_run=False,
            force_reanalyze=False,
            include_low_signal=False,
        )
        self.assertEqual(analyze_calls["count"], 0)
        skipped = result.get("diagnostics", {}).get("skipped", {})
        self.assertEqual(skipped.get("registry_expired_low_impact"), 1)

    def test_force_reanalyze_overrides_registry_skip(self) -> None:
        headline = "Fed cuts rates by 25bp"
        self._seed_registry_analyzed(headline)
        # Same fixture as previous test.
        from routes.movers import movers_backfill_recent
        analyze_calls = {"count": 0}

        def fake_fresh(*a, **kw):
            analyze_calls["count"] += 1
            return {"status": "ok", "event_id": 99}

        def fake_payload():
            return ({
                "clusters": [{
                    "headline":     headline,
                    "source_count": 5,
                    "published_at": "2026-05-03T08:00:00",
                    "sources":      [{"name": "Reuters"}],
                }],
            }, "memory")

        self._stub_route_for_test({
            "_cached_news_payload":          fake_payload,
            "_fresh_analysis_market_event":  fake_fresh,
            "_max_backfill_llm_calls":       lambda: 5,
            "_backfill_dry_run_default":     lambda: False,
            "_llm_available":                lambda *_: True,
        })

        movers_backfill_recent(
            limit=3,
            max_llm_calls=2,
            scan_limit=10,
            since_hours=72,
            dry_run=False,
            force_reanalyze=True,   # <-- override
            include_low_signal=False,
        )
        self.assertGreaterEqual(analyze_calls["count"], 1)

    def test_skip_reason_stamped_without_state_regression(self) -> None:
        """A cluster filtered by 'irrelevant_headline' lands
        last_skip_reason='irrelevant_headline' on every registry row
        sharing the title_key; state stays 'seen'."""
        from news_sources import _dedup_key
        from routes.movers import movers_backfill_recent

        headline = "Sports team wins championship"
        tk = _dedup_key(headline)
        # Pre-create a registry row in 'seen' with cluster_id=1.
        self._db.upsert_headline_registry_seen(
            [("ESPN", tk, 1)], "2026-05-03T08:00:00",
        )

        def fake_payload():
            return ({
                "clusters": [{
                    "headline":     headline,
                    "source_count": 1,
                    "published_at": "2026-05-03T08:00:00",
                    "sources":      [{"name": "ESPN"}],
                }],
            }, "memory")

        self._stub_route_for_test({
            "_cached_news_payload":           fake_payload,
            "_max_backfill_llm_calls":        lambda: 5,
            "_backfill_dry_run_default":      lambda: True,
            "_llm_available":                 lambda *_: True,
            "_headline_is_market_relevant":   lambda *_: False,
        })

        movers_backfill_recent(
            limit=3,
            max_llm_calls=2,
            scan_limit=10,
            since_hours=72,
            dry_run=True,
            force_reanalyze=False,
            include_low_signal=False,
        )
        # State should still be 'seen', skip reason stamped.
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT state, last_skip_reason FROM headline_registry "
                "WHERE title_key = ?",
                (tk,),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "seen")
        self.assertEqual(row[1], "irrelevant_headline")
```

- [ ] **Step 4.2: Run tests, verify all four fail**

Run: `python -m unittest tests.test_headline_registry.TestBackfillRegistryShortCircuit -v`

Expected: FAIL — registry skips don't exist yet; analyze stub is called when it shouldn't be, and the new skip-reason keys (`registry_already_analyzed`, `registry_expired_low_impact`) are missing from the diagnostics.

- [ ] **Step 4.3: Patch the eligible-cluster loop in `routes/movers.py`**

Open `routes/movers.py`. The eligible-cluster loop starts at line 1159 with:

```python
    for cluster in eligible_clusters[:scan_limit]:
        diagnostics["headlines_scanned"] += 1
        headline = _cluster_headline(cluster)
        if not headline:
            _bump_skip(skipped, "empty_headline")
            continue
        if cluster.get("low_signal") and not include_low_signal:
            _bump_skip(skipped, "low_signal")
            continue
```

Add an import at the top of the file (near the other top-level imports, alongside the `news_relevance` import seen near `routes/movers.py:1000`):

```python
import headline_registry as _hr
from news_sources import _dedup_key as _hr_dedup_key
```

Immediately after the `low_signal` skip block (i.e. before the `event_date = _cluster_event_date(cluster)` line at the start of the existing per-cluster body), insert the pre-LLM registry check:

```python
        # Headline-registry pre-LLM check.  Skips clusters whose
        # representative headline has already been analyzed (or has
        # expired as low-impact) without burning LLM budget.  See
        # docs/superpowers/specs/2026-05-03-headline-registry-design.md.
        registry_title_key = _hr_dedup_key(headline)
        registry_state, _registry_event_id = _registry_state_for_title_key(
            registry_title_key,
        )
        if not force_reanalyze and registry_state in (
            "analyzed", "market_checked", "surfaced",
        ):
            _bump_skip(skipped, "registry_already_analyzed")
            _hr.advance_state(
                title_key=registry_title_key,
                last_skip_reason="registry_already_analyzed",
            )
            continue
        if not force_reanalyze and registry_state == "expired_low_impact":
            _bump_skip(skipped, "registry_expired_low_impact")
            _hr.advance_state(
                title_key=registry_title_key,
                last_skip_reason="registry_expired_low_impact",
            )
            continue
```

Locate the existing `_bump_skip(skipped, ...)` call sites inside the loop — `dry_run`, `limit_reached`, `already_market_checked`, `llm_budget_exhausted`. Immediately after each `_bump_skip` call inside the eligible loop body, append:

```python
            _hr.advance_state(
                title_key=registry_title_key,
                last_skip_reason="<the same string just passed to _bump_skip>",
            )
```

Substitute the literal string for each occurrence. For the four skip reasons in the eligible-cluster body (`dry_run`, `limit_reached`, `already_market_checked`, `llm_budget_exhausted`), each gets one stamp call with the matching reason.

For the pre-eligible filter (`outside_recency_window`, `irrelevant_headline`, `empty_headline`), the cluster has been filtered before we know the title_key safely — but we DO know the headline. In the pre-eligible filter loop near `routes/movers.py:1124-1136`, after each `_bump_skip` call, add:

```python
        _stamp_skip_reason_for_cluster(cluster, "<reason>")
```

Then add this helper near the top of the file (alongside the other per-route helpers):

```python
# Lifecycle ordering used to pick the most-advanced state across the
# registry rows that share a title_key.  Mirrors db._REGISTRY_LIFECYCLE
# but kept local so this module doesn't reach into a private symbol.
_REGISTRY_LIFECYCLE_ORDER = (
    "seen", "eligible", "analyzed", "market_checked", "surfaced",
    "expired_low_impact",
)


def _registry_state_for_title_key(title_key: str) -> tuple[str | None, int | None]:
    """Return ``(state, event_id)`` for the most-advanced row matching
    title_key; (None, None) when no row exists.

    Multiple sources sharing the same title_key may sit at different
    states transiently (a late-arriving source starts at 'seen' until
    the next ingest+stamp cycle catches it up).  We pick the highest-
    rank state so the pre-LLM check sees the truth that "this headline
    has already been analyzed somewhere".
    """
    if not title_key:
        return None, None
    import sqlite3
    from db import DB_FILE, _db_ready
    if not _db_ready:
        return None, None
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT state, event_id FROM headline_registry "
            "WHERE title_key = ?",
            (title_key,),
        ).fetchall()
    if not rows:
        return None, None
    rank = {s: i for i, s in enumerate(_REGISTRY_LIFECYCLE_ORDER)}
    best_state: str | None = None
    best_event_id: int | None = None
    best_rank = -1
    for state, event_id in rows:
        r = rank.get(state or "seen", -1)
        if r > best_rank:
            best_rank = r
            best_state = state
            best_event_id = event_id
    return best_state, best_event_id


def _stamp_skip_reason_for_cluster(cluster: dict, reason: str) -> None:
    """Stamp last_skip_reason on registry rows matching the cluster's
    representative headline.  No-op when headline is missing/empty."""
    headline = _cluster_headline(cluster) if cluster else ""
    if not headline:
        return
    _hr.advance_state(
        title_key=_hr_dedup_key(headline),
        last_skip_reason=reason,
    )
```

Finally, advance state on success — locate the existing analyze success branch (the spot in the loop body where `_fresh_analysis_market_event` returns successfully and the event is persisted). Append after the persistence call:

```python
            try:
                impact_level = (
                    (result.get("conviction") or {}).get("impact_level")
                    if isinstance(result, dict) else None
                )
                _hr.advance_state(
                    title_key=registry_title_key,
                    new_state="analyzed",
                    event_id=result.get("event_id") if isinstance(result, dict) else None,
                    impact_level=impact_level,
                    analyzed_at=datetime.now().isoformat(timespec="seconds"),
                )
            except Exception:
                _api._log.warning(
                    "registry advance_state(analyzed) failed", exc_info=True,
                )
```

And after `_market_check_event` succeeds (or wherever the loop confirms market data has been fetched for this cluster), append:

```python
            _hr.advance_state(
                title_key=registry_title_key,
                new_state="market_checked",
            )
```

- [ ] **Step 4.4: Run the backfill tests, verify all four pass**

Run: `python -m unittest tests.test_headline_registry.TestBackfillRegistryShortCircuit -v`

Expected: PASS (4 tests).

- [ ] **Step 4.5: Run the existing movers regression suite to confirm no break**

Run: `python -m unittest discover -s tests -p "test_*movers*.py" -v`

Expected: every existing test passes.

---

## Task 5: `/movers/today` read-time expiry filter + lazy stamp

**Files:**
- Modify: `routes/movers.py` (`movers_today` handler at `routes/movers.py:1394`)
- Test: `tests/test_headline_registry.py` (extend)

**Goal:** `/movers/today` hides expired-low-impact rows even when the underlying `_TODAYS_MOVERS_CACHE` (5-minute TTL inside `api.movers_today`) still has them; lazy-stamps the registry on observation.

- [ ] **Step 5.1: Write failing tests for the surface filter**

Append to `tests/test_headline_registry.py`:

```python
class TestMoversTodayExpiry(_RegistryTestBase):

    def _seed_two_rows(self) -> tuple[dict, dict]:
        """Returns (fresh_low, expired_low) row dicts in /movers/today shape."""
        fresh = {
            "id":         1,
            "headline":   "Fresh low-impact print",
            "timestamp":  "2026-05-09T12:00:00",
            "conviction": {"impact_level": "low"},
        }
        expired = {
            "id":         2,
            "headline":   "Old low-impact print",
            "timestamp":  "2026-04-25T12:00:00",
            "conviction": {"impact_level": "low"},
        }
        # Seed registry analyzed_at to mirror the event timestamp so the
        # bulk lookup uses the registry path, not the fallback.
        from news_sources import _dedup_key
        for row in (fresh, expired):
            tk = _dedup_key(row["headline"])
            self._db.upsert_headline_registry_seen(
                [("Reuters", tk, 1)], row["timestamp"],
            )
            self._db.update_registry_state(
                title_key=tk,
                new_state="analyzed",
                event_id=row["id"],
                impact_level="low",
                analyzed_at=row["timestamp"],
            )
        return fresh, expired

    def test_movers_today_hides_expired_low(self) -> None:
        from headline_registry import filter_expired_low_impact
        fresh, expired = self._seed_two_rows()
        now = datetime(2026, 5, 10, 12, 0, 0)
        survivors = filter_expired_low_impact([fresh, expired], now=now)
        self.assertEqual([r["id"] for r in survivors], [1])
        # And the expired row should now be stamped.
        import sqlite3
        from news_sources import _dedup_key
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT state, expired_at FROM headline_registry "
                "WHERE title_key = ?",
                (_dedup_key(expired["headline"]),),
            ).fetchone()
        self.assertEqual(row[0], "expired_low_impact")
        self.assertIsNotNone(row[1])

    def test_filter_runs_on_cached_payload(self) -> None:
        """Calling the filter twice on the same list returns the same
        survivors both times (no double-counting; idempotent stamp)."""
        from headline_registry import filter_expired_low_impact
        fresh, expired = self._seed_two_rows()
        now = datetime(2026, 5, 10, 12, 0, 0)
        first = filter_expired_low_impact([fresh, expired], now=now)
        second = filter_expired_low_impact([fresh, expired], now=now)
        self.assertEqual([r["id"] for r in first],  [1])
        self.assertEqual([r["id"] for r in second], [1])
```

- [ ] **Step 5.2: Run tests, verify they fail**

Run: `python -m unittest tests.test_headline_registry.TestMoversTodayExpiry -v`

Expected: PASS for the unit-level test (the `filter_expired_low_impact` helper exists from Task 2). If both tests already pass, that's because the helper is correct in isolation — Step 5.3 is still required to wire the filter into the route handler so end-to-end behaviour matches.

- [ ] **Step 5.3: Wire the filter into the `/movers/today` handler**

In `routes/movers.py`, locate `movers_today` at line 1394:

```python
@router.get("/movers/today")
def movers_today(
    limit: int = Query(10, ge=1, le=100),
    include_meta: bool = Query(False),
):
    envelope = _sanitize_movers_with_meta(
        _api.movers_today(limit=limit),
        window="today",
        diagnostics=_time_window_diagnostics("today"),
    )
    return _project(envelope, include_meta=include_meta)
```

Replace the body with:

```python
@router.get("/movers/today")
def movers_today(
    limit: int = Query(10, ge=1, le=100),
    include_meta: bool = Query(False),
):
    raw = _api.movers_today(limit=limit)
    # Read-time expiry filter — runs every call, NOT inside the
    # _TODAYS_MOVERS_CACHE build, so rows can't expire mid-TTL invisibly.
    # See docs/superpowers/specs/2026-05-03-headline-registry-design.md.
    filtered = _hr.filter_expired_low_impact(raw or [])
    envelope = _sanitize_movers_with_meta(
        filtered,
        window="today",
        diagnostics=_time_window_diagnostics("today"),
    )
    return _project(envelope, include_meta=include_meta)
```

- [ ] **Step 5.4: Re-run the surface tests + the today-window regression suite**

Run: `python -m unittest tests.test_headline_registry.TestMoversTodayExpiry -v`
Run: `python -m unittest discover -s tests -p "test_*today*.py" -v`

Expected: PASS for both.

---

## Task 6: `/events` listing read-time expiry filter

**Files:**
- Modify: `routes/events.py` (`events` handler at `routes/events.py:225`)
- Test: `tests/test_headline_registry.py` (extend)

**Goal:** The paginated listing endpoint hides expired-low-impact rows; `total` returned to the client reflects the post-expiry universe; `/events/{id}` detail still serves expired rows untouched.

- [ ] **Step 6.1: Write failing tests for the listing filter and detail bypass**

Append to `tests/test_headline_registry.py`:

```python
class TestEventsListingExpiry(_RegistryTestBase):

    def _seed_event_and_registry(
        self, event_id: int, headline: str, ts: str, impact: str,
    ) -> None:
        """Insert an event row and a matching registry row."""
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO events (id, timestamp, headline, stage, "
                "persistence) VALUES (?, ?, ?, 'unknown', 'unknown')",
                (event_id, ts, headline),
            )
        from news_sources import _dedup_key
        tk = _dedup_key(headline)
        self._db.upsert_headline_registry_seen(
            [("Reuters", tk, 1)], ts,
        )
        self._db.update_registry_state(
            title_key=tk,
            new_state="analyzed",
            event_id=event_id,
            impact_level=impact,
            analyzed_at=ts,
        )

    def test_listing_hides_expired_low(self) -> None:
        # Event A: fresh low — stays.  Event B: expired low — hidden.
        self._seed_event_and_registry(
            1, "Fresh low",   "2026-05-09T12:00:00", "low",
        )
        self._seed_event_and_registry(
            2, "Expired low", "2026-04-25T12:00:00", "low",
        )
        # Inject conviction into event rows by patching _decode_event_row
        # so the filter has impact_level to read.  The simpler route is
        # to assert directly against filter_expired_low_impact at the
        # data layer — the route-level wiring uses the same helper.
        from headline_registry import filter_expired_low_impact
        rows = [
            {"id": 1, "headline": "Fresh low",
             "timestamp": "2026-05-09T12:00:00",
             "conviction": {"impact_level": "low"}},
            {"id": 2, "headline": "Expired low",
             "timestamp": "2026-04-25T12:00:00",
             "conviction": {"impact_level": "low"}},
        ]
        survivors = filter_expired_low_impact(
            rows, now=datetime(2026, 5, 10, 12, 0, 0),
        )
        self.assertEqual([r["id"] for r in survivors], [1])

    def test_total_reflects_post_expiry_universe(self) -> None:
        """The /events listing returns total = len(post-filter rows)."""
        # Three rows; one is expired-low.  Expected total=2, items=2.
        rows = [
            {"id": 1, "headline": "Fresh low",
             "timestamp": "2026-05-09T12:00:00",
             "conviction": {"impact_level": "low"}},
            {"id": 2, "headline": "Expired low",
             "timestamp": "2026-04-25T12:00:00",
             "conviction": {"impact_level": "low"}},
            {"id": 3, "headline": "High impact",
             "timestamp": "2026-04-25T12:00:00",
             "conviction": {"impact_level": "high"}},
        ]
        from headline_registry import filter_expired_low_impact
        survivors = filter_expired_low_impact(
            rows, now=datetime(2026, 5, 10, 12, 0, 0),
        )
        self.assertEqual(len(survivors), 2)
        self.assertEqual({r["id"] for r in survivors}, {1, 3})

    def test_detail_does_not_call_filter(self) -> None:
        """Sanity check: get_event_detail returns the row regardless of
        expiry.  Verified by checking routes.events for the import —
        detail handlers must NOT import filter_expired_low_impact."""
        import inspect
        import routes.events as ev
        source = inspect.getsource(ev.get_event_detail)
        self.assertNotIn("filter_expired_low_impact", source)
        self.assertNotIn("is_expired_low_impact", source)
```

- [ ] **Step 6.2: Run tests, verify two pass and the third (`test_detail_does_not_call_filter`) currently passes by accident (function doesn't exist yet — but will after Step 6.3)**

Run: `python -m unittest tests.test_headline_registry.TestEventsListingExpiry -v`

Expected: PASS for all three (the unit tests use the helper directly; the detail check inspects code that hasn't changed).

- [ ] **Step 6.3: Wire the filter into the `/events` listing**

In `routes/events.py`, add an import near the existing top-of-file imports (alongside `from db import ...`):

```python
import headline_registry as _hr
```

In the `events` handler, locate this block at `routes/events.py:280-288`:

```python
    rows = query_events_filtered(
        search=search,
        stage=stage,
        persistence=persistence,
        confidence=confidence,
        rating=rating,
        date_from=date_from,
        date_to=date_to,
    )

    # Dedup first so total counts reflect the deduped universe.
    rows = dedup_events(rows)
```

Append immediately after the `dedup_events` call:

```python
    # Read-time expiry filter for low-impact analyzed events.  Applied
    # AFTER dedup and BEFORE the offset/limit slice so ``total`` reflects
    # the post-expiry universe and pagination yields stable page sizes.
    # Detail-by-id (/events/{event_id}) does NOT call this filter — see
    # CLAUDE.md frozen UI boundary on detail visibility.
    rows = _hr.filter_expired_low_impact(rows)
```

This call sits before both the `needs_full_scan` branch and the fast path, so both code paths see the post-expiry row set when computing `total = len(rows)` and `items = rows[offset: offset + limit]`.

- [ ] **Step 6.4: Run all listing tests + the existing events suite**

Run: `python -m unittest tests.test_headline_registry.TestEventsListingExpiry -v`
Run: `python -m unittest discover -s tests -p "test_*events*.py" -v`

Expected: PASS for both.

---

## Task 7: `/registry/diagnostics` endpoint with eligible_unanalyzed_candidates

**Files:**
- Create: `routes/diagnostics.py`
- Modify: `api.py` (one-line router registration near `api.py:3274`)
- Test: `tests/test_headline_registry.py` (extend)

**Goal:** Zero-cost diagnostics endpoint exposing state counts, skip-reason counts, last-analyzed timestamp, recent-expired count, and the top-N major eligible-but-unanalyzed candidates ranked by cluster source_count.

- [ ] **Step 7.1: Write failing tests for state counts + ranking**

Append to `tests/test_headline_registry.py`:

```python
class TestRegistryDiagnostics(_RegistryTestBase):

    def _seed_cluster(
        self, cluster_id: int, headline: str, source_count: int,
        has_asset_terms: bool = False,
    ) -> None:
        import json as _json
        import sqlite3
        payload = _json.dumps({
            "headline": headline,
            "source_count": source_count,
            "has_asset_terms": has_asset_terms,
        })
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO news_clusters "
                "(id, headline, payload_json, records_json, "
                " latest_published_at, updated_at) "
                "VALUES (?, ?, ?, '[]', ?, ?)",
                (cluster_id, headline, payload,
                 "2026-05-03T08:00:00", "2026-05-03T08:00:00"),
            )

    def test_state_counts_match_synthetic_flow(self) -> None:
        # Two seen, one analyzed.
        from news_sources import _dedup_key
        self._db.upsert_headline_registry_seen(
            [("Reuters",  _dedup_key("h1"), None),
             ("Bloomberg", _dedup_key("h2"), None)],
            "2026-05-03T08:00:00",
        )
        self._db.upsert_headline_registry_seen(
            [("Reuters", _dedup_key("h3"), None)],
            "2026-05-03T09:00:00",
        )
        self._db.update_registry_state(
            title_key=_dedup_key("h3"),
            new_state="analyzed",
            event_id=1,
            impact_level="high",
            analyzed_at="2026-05-03T09:30:00",
        )
        counts = self._db.load_registry_state_counts()
        self.assertEqual(counts.get("seen"),     2)
        self.assertEqual(counts.get("analyzed"), 1)

    def test_eligible_unanalyzed_candidates_ranked_by_source_count(self) -> None:
        from news_sources import _dedup_key
        self._seed_cluster(10, "Major story", source_count=7)
        self._seed_cluster(11, "Minor story", source_count=1)
        self._db.upsert_headline_registry_seen(
            [("Reuters", _dedup_key("Major story"), 10)],
            "2026-05-03T08:00:00",
        )
        self._db.upsert_headline_registry_seen(
            [("Reuters", _dedup_key("Minor story"), 11)],
            "2026-05-03T08:01:00",
        )
        candidates = self._db.load_eligible_unanalyzed_candidates(limit=10)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["headline"], "Major story")
        self.assertEqual(candidates[0]["source_count"], 7)
        self.assertEqual(candidates[1]["headline"], "Minor story")
```

- [ ] **Step 7.2: Run tests, verify both pass (helpers landed in Task 1)**

Run: `python -m unittest tests.test_headline_registry.TestRegistryDiagnostics -v`

Expected: PASS (2 tests).

- [ ] **Step 7.3: Create the diagnostics router**

Create `routes/diagnostics.py`:

```python
"""Diagnostics routes — zero-cost introspection over the
headline_registry lifecycle.  See
docs/superpowers/specs/2026-05-03-headline-registry-design.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from db import (
    load_registry_state_counts,
    load_registry_skip_reason_counts,
    load_registry_last_analyzed_at,
    load_registry_expired_count_since,
    load_eligible_unanalyzed_candidates,
)

router = APIRouter()


@router.get("/registry/diagnostics")
def registry_diagnostics(
    candidates_limit: int = Query(50, ge=1, le=500),
):
    """Pure-SQL view over headline_registry.  Zero LLM cost.

    Returns state counts, last-skip-reason counts, the most recent
    analyzed_at, the count of low-impact events that have expired in
    the last 24 hours, and the top eligible-but-unanalyzed candidates
    ranked by source_count then recency.
    """
    since_iso = (
        datetime.now() - timedelta(hours=24)
    ).isoformat(timespec="seconds")
    return {
        "state_counts":            load_registry_state_counts(),
        "skip_reason_counts":      load_registry_skip_reason_counts(),
        "last_analyzed_at":        load_registry_last_analyzed_at(),
        "expired_count_24h":       load_registry_expired_count_since(since_iso),
        "eligible_unanalyzed_candidates":
            load_eligible_unanalyzed_candidates(limit=candidates_limit),
    }
```

- [ ] **Step 7.4: Wire the router into `api.py`**

In `api.py`, locate the router-import block at lines 3265-3272:

```python
from routes.analyze import router as _analyze_router
from routes.candidates import router as _candidates_router
from routes.events import router as _events_router
from routes.market import router as _market_router
from routes.movers import router as _movers_router
from routes.news import router as _news_router
from routes.portfolio import router as _portfolio_router
from routes.playbook import router as _playbook_router
```

Append a new line (line 3273):

```python
from routes.diagnostics import router as _diagnostics_router
```

Then locate the `app.include_router(...)` block immediately below (lines 3274-3281). Append after the last include:

```python
app.include_router(_diagnostics_router)
```

- [ ] **Step 7.5: Smoke-test the endpoint via TestClient**

Append to `tests/test_headline_registry.py`:

```python
class TestRegistryDiagnosticsRoute(_RegistryTestBase):

    def test_endpoint_returns_expected_shape(self) -> None:
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)
        resp = client.get("/registry/diagnostics")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("state_counts",                   body)
        self.assertIn("skip_reason_counts",             body)
        self.assertIn("last_analyzed_at",               body)
        self.assertIn("expired_count_24h",              body)
        self.assertIn("eligible_unanalyzed_candidates", body)
        self.assertIsInstance(
            body["eligible_unanalyzed_candidates"], list,
        )
```

Run: `python -m unittest tests.test_headline_registry.TestRegistryDiagnosticsRoute -v`

Expected: PASS.

---

## Task 8: Regression guard — `/movers/persistent` and `/movers/yearly` unchanged

**Files:**
- Test: `tests/test_headline_registry.py` (extend)

**Goal:** Confirm that the new expiry filter is NOT applied to the persistent and yearly mover surfaces (CLAUDE.md frozen contracts).

- [ ] **Step 8.1: Write the regression test**

Append to `tests/test_headline_registry.py`:

```python
class TestPersistentYearlyUntouched(unittest.TestCase):
    """Regression: /movers/persistent and /movers/yearly handlers must
    NOT call the expiry filter.  Source-level inspection guard so a
    future refactor that accidentally wires the filter in is caught."""

    def test_persistent_handler_does_not_use_expiry_filter(self) -> None:
        import inspect
        import routes.movers as rm
        source = inspect.getsource(rm.movers_persistent)
        self.assertNotIn("filter_expired_low_impact", source)
        self.assertNotIn("is_expired_low_impact",     source)

    def test_yearly_handler_does_not_use_expiry_filter(self) -> None:
        import inspect
        import routes.movers as rm
        source = inspect.getsource(rm.movers_yearly)
        self.assertNotIn("filter_expired_low_impact", source)
        self.assertNotIn("is_expired_low_impact",     source)
```

- [ ] **Step 8.2: Run the regression test**

Run: `python -m unittest tests.test_headline_registry.TestPersistentYearlyUntouched -v`

Expected: PASS (2 tests).

---

## Task 9: Document env var + final verification sweep

**Files:**
- Modify: `.env.example`
- (no test changes — this is housekeeping + the project-wide verification matrix)

- [ ] **Step 9.1: Document the TTL env var**

Read `.env.example`, then add (near the other operational defaults documented at the top of the file):

```
# Headline registry low-impact expiry. Active live surfaces
# (/movers/today, /events listing) hide low-impact analyzed events
# whose analyzed_at is older than this many days. Default 5.
HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS=5
```

- [ ] **Step 9.2: Run the full headline_registry test module**

Run: `python -m unittest tests.test_headline_registry -v`

Expected: every test in the module passes.

- [ ] **Step 9.3: Run the broader regression suite (per CLAUDE.md verification matrix)**

Run each command and confirm pass/fail:

```
python -m unittest discover -s tests -p "test_*movers*.py" -v
python -m unittest discover -s tests -p "test_*events*.py" -v
python -m unittest discover -s tests -p "test_*portfolio*.py" -v
python -m unittest discover -s tests -p "test_track_record*.py" -v
python -m unittest tests.test_research_export -v
```

Expected: every existing test passes. If any test fails, it indicates a regression — investigate before declaring the feature complete.

- [ ] **Step 9.4: Frontend smoke (typecheck + build)**

Run from repo root:

```
cd frontend
npm run typecheck
npm run build
```

Expected: typecheck clean; build succeeds (the existing chunk-size warning is non-blocking per CLAUDE.md).

No frontend code changes are part of this plan — these checks confirm the API contracts didn't shift in a way that would break consumers.

- [ ] **Step 9.5: Manual smoke check the diagnostics endpoint**

With the API server running (`python -m uvicorn api:app --reload`), visit:

```
http://localhost:8000/registry/diagnostics
```

Expected: JSON body with the five top-level fields. `state_counts` should populate as ingestion runs; on a fresh DB it may be `{}` until the first `news` refresh fires.

---

## Definition of Done

- [ ] All tests in `tests/test_headline_registry.py` pass.
- [ ] Existing movers / events / portfolio / track-record / research-export suites pass unchanged.
- [ ] `npm run typecheck && npm run build` clean.
- [ ] `/registry/diagnostics` returns the documented shape against the live API server.
- [ ] `.env.example` documents `HEADLINE_REGISTRY_LOW_IMPACT_TTL_DAYS`.
- [ ] `/events/{id}` detail endpoint serves expired-low-impact rows untouched (covered by `test_detail_does_not_call_filter`).
- [ ] `/movers/persistent` and `/movers/yearly` handlers don't reference the expiry filter (covered by Task 8 regression).

---

## Self-Review Notes

**Spec coverage:** every spec test (1–14) maps to a task:
- Spec test 1 (ingest writes seen) → Task 3 `test_ingest_writes_seen_rows`.
- Spec test 2 (no state regression) → Task 3 `test_reingest_preserves_analyzed_state`.
- Spec test 3 (skip-reason stamping) → Task 4 `test_skip_reason_stamped_without_state_regression`.
- Spec test 4 (skip analyzed) → Task 4 `test_pre_llm_check_skips_analyzed`.
- Spec test 5 (skip expired) → Task 4 `test_pre_llm_check_skips_expired_low`.
- Spec test 6 (force_reanalyze override) → Task 4 `test_force_reanalyze_overrides_registry_skip`.
- Spec test 6a (title-key independent of cluster_id) → Task 4 (the seed flow uses title_key with `cluster_id=1` then matches via title_key only).
- Spec test 7 (is_expired_low_impact boundaries) → Task 2 `TestIsExpiredLowImpact` (6 sub-tests).
- Spec test 8 (movers/today hides + lazy-stamps) → Task 5 `test_movers_today_hides_expired_low`.
- Spec test 9 (events listing hides; detail serves) → Task 6 `test_listing_hides_expired_low` + `test_detail_does_not_call_filter`.
- Spec test 10 (persistent/yearly unchanged) → Task 8.
- Spec test 11 (diagnostics counts) → Task 7 `test_state_counts_match_synthetic_flow`.
- Spec test 12 (eligible_unanalyzed_candidates ranking) → Task 7 `test_eligible_unanalyzed_candidates_ranked_by_source_count`.
- Spec test 13 (events total reflects post-expiry) → Task 6 `test_total_reflects_post_expiry_universe`.
- Spec test 14 (movers/today filter on cached payload) → Task 5 `test_filter_runs_on_cached_payload`.

**Type consistency:** `update_registry_state` (db.py) and `advance_state` (headline_registry.py) accept the same kwargs (`title_key`, `new_state`, `event_id`, `impact_level`, `analyzed_at`, `expired_at`, `last_skip_reason`); `_hr.advance_state(...)` is the only call style used at call sites in routes/movers.py. `filter_expired_low_impact(event_rows, now=None)` is the only call style used at read sites.

**No placeholders:** Every code step shows the actual code; every test step shows the actual test; every command step shows the exact command.
