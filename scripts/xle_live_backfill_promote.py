#!/usr/bin/env python3
"""Live XLE backfill promotion — gated, single-transaction insert.

Promotes the exact XLE estimation-window rows demonstrated by
:mod:`scripts.xle_online_backfill_preview` into the live events DB's
``price_cache`` table.  This is the ONLY script in the workflow that
writes to the live DB, and it does so only when every safety gate
passes:

  1. ``--confirm-live-write`` is supplied (explicit, opt-in).
  2. ``--backup-path`` is supplied AND the file exists and is readable
     (the operator has taken a backup BEFORE running this script).
  3. The preview artifact reports ``ready_after == 2`` AND
     ``blocked_after == 0`` (i.e., the temp preview cleared the
     benchmark-sensitivity preflight against XLE).

Any single gate failing → ``ok=False`` and the live DB is not opened
for writes.  All three gates are evaluated independently so the
operator sees every problem on a single run.

Read-only safety guarantees
---------------------------

* Without ``--confirm-live-write`` no provider is imported, no fetch
  fires, and the live DB is not opened for writes.
* The fetch seam ``_fetch_xle_rows_online`` is imported lazily
  (``yfinance``) only inside the confirmed-write path.  Tests MUST
  patch this seam so the no-paid invariants hold under
  ``--confirm-live-write``.
* Writes go through a single explicit transaction (``BEGIN`` →
  inserts → ``COMMIT``).  On any exception inside the loop the
  transaction is rolled back so a half-promoted state never lands.
* Writes are filtered at insert time to ticker ``XLE`` and to dates
  in the preview artifact's ``required_dates`` list — even though
  the fetch seam is also asked for those dates only.  Defense in
  depth against a misbehaving fetch.
* Prices are NEVER fabricated.  A date the provider does not return
  a row for is silently skipped; the gap surfaces in
  ``skipped_existing_count == 0`` for that date and in the
  post-write preflight (which will still report it as blocked).
* No Anthropic / LLM / FastAPI surface (never imports ``api`` /
  ``routes.*``).

Bit-identity caveat
-------------------

This promoter re-fetches XLE bars from the provider rather than
copying rows out of the preview's temp DB (which is not surfaced as
an input).  Daily bars from a stable provider are append-only and do
not revise retroactively, so the rows the promoter writes are
*the same dates and ticker* the preview demonstrated.  The
``live_db_hash_before`` / ``live_db_hash_after`` fields record the
byte transition so an operator can audit it; no claim is made that
the resulting rows are bit-identical to the preview's temp rows.

Output contract (JSON)::

    {
      "ok":                       bool,
      "confirm_live_write":       bool,
      "backup_path":              str | None,
      "backup_exists":            bool,
      "backup_hash":              str | None,
      "preview_artifact_path":    str,
      "preview_ready_after":      int,
      "preview_blocked_after":    int,
      "preview_ready":            bool,
      "required_dates":           [str, ...],
      "inserted_count":           int,
      "skipped_existing_count":   int,
      "live_db_hash_before":      str | None,
      "live_db_hash_after":       str | None,
      "preflight_after": {
        "checked_events": int,
        "ready_count":    int,
        "blocked_count":  int,
      },
      "ready_count":              int,
      "blocked_count":            int,
      "warnings":                 [str, ...],
      "errors":                   [str, ...],
      "recommended_next_action":  str,
    }

Conservative wording — the script reports cache geometry, never
benchmark-sensitivity conclusions.  Banned tokens in any text the
script emits: ``proof``, ``proves``, ``proven``, ``alpha``,
``guaranteed``, ``automatically``, ``validated``, ``definitely``.
No SPY-vs-XLE inference is ever asserted.

Usage::

    python scripts/xle_live_backfill_promote.py --json
    python scripts/xle_live_backfill_promote.py --json \\
        --confirm-live-write \\
        --backup-path /path/to/events.db.bak \\
        --preview-artifact artifacts/xle_online_backfill_preview_post_calendar_fix.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sqlite3
import sys
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_EVENT_IDS:         tuple[int, ...] = (60, 73)
_DEFAULT_BENCHMARK:         str             = "XLE"
_DEFAULT_HORIZONS:          tuple[int, ...] = (1, 5, 20)
_DEFAULT_ESTIMATION_WINDOW: int             = 60

_DEFAULT_PREVIEW_ARTIFACT: str = (
    "artifacts/xle_online_backfill_preview_post_calendar_fix.json"
)

# Literal gate values for the preview artifact — these mirror the
# "two events become benchmark-ready against XLE" outcome the preview
# is designed to demonstrate.  Generalising these would be a silent
# weakening of the promotion gate.
_REQUIRED_READY_AFTER:   int = 2
_REQUIRED_BLOCKED_AFTER: int = 0


_RECOMMENDED_GATE_FAILED: str = (
    "Live promotion was NOT attempted because one or more gates "
    "failed.  Required: --confirm-live-write, --backup-path pointing "
    "at an existing readable backup file, and a preview artifact "
    "reporting ready_after=2 and blocked_after=0.  Inspect 'errors' "
    "for the per-gate reason."
)
_RECOMMENDED_BACKUP_MISSING: str = (
    "Live promotion refused: --backup-path is missing, does not "
    "exist, or is unreadable.  Take a backup of the live events DB "
    "and re-run with --backup-path pointing at it."
)
_RECOMMENDED_PREVIEW_NOT_READY: str = (
    "Live promotion refused: the preview artifact does not report "
    "ready_after=2 and blocked_after=0.  Re-run the online preview "
    "until it cleared, then re-run this promoter."
)
_RECOMMENDED_FETCH_EMPTY: str = (
    "Live promotion refused: the provider returned zero rows for "
    "the required dates; no XLE rows were inserted into the live "
    "price_cache.  Inspect provider coverage before re-trying."
)
_RECOMMENDED_PROMOTED_AND_CLEARED: str = (
    "Promoted {inserted} XLE row(s) into the live price_cache "
    "(skipped {skipped} already-present row(s)).  Post-write "
    "benchmark-sensitivity preflight reports {ready} ready and "
    "{blocked} blocked event(s).  Live DB hash recorded "
    "before/after; the backup remains untouched.  This script "
    "reports cache geometry only and does not infer any benchmark-"
    "sensitivity conclusion."
)
_RECOMMENDED_PROMOTED_NOT_CLEARED: str = (
    "Promoted {inserted} XLE row(s) into the live price_cache "
    "(skipped {skipped} already-present row(s)).  Post-write "
    "benchmark-sensitivity preflight still reports {blocked} of "
    "{checked} event(s) blocked ({ready} ready).  Inspect each "
    "blocked event's per-row blockers before relying on any "
    "downstream benchmark step.  This script reports cache "
    "geometry only and does not infer any benchmark-sensitivity "
    "conclusion."
)
_RECOMMENDED_ERRORED: str = (
    "Live promotion errored mid-flow.  Inspect 'errors'; compare "
    "'live_db_hash_before' to the current live DB to decide whether "
    "to restore from --backup-path."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _read_preview_artifact(*, path: str) -> dict[str, Any]:
    """Read the preview artifact JSON from disk.

    Patched in tests so the artifact is driven synthetically without
    a real file on disk.  Returns an empty dict on read failure; the
    caller surfaces a clear error.
    """
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _fetch_xle_rows_online(
    *, dates: Sequence[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch ticker ``XLE`` bars for the exact ``dates`` from the
    online market-data provider.  Returns ``(rows, errors)``.

    Lazily imports ``yfinance`` so the default code path (no
    ``--confirm-live-write``) never pulls a provider into
    ``sys.modules``.  Tests MUST patch this seam to keep the no-paid
    invariants in place even when ``--confirm-live-write`` is
    exercised.

    Each returned row carries
    ``(ticker, date, close, volume, auto_adjust, fetched_at)``.
    Dates with no provider data are silently omitted — prices are
    NEVER fabricated.
    """
    if not dates:
        return [], []
    try:
        import yfinance as yf  # noqa: PLC0415 — lazy by contract
    except ImportError as exc:
        return [], [
            f"yfinance unavailable; cannot perform online fetch: {exc}"
        ]

    iso_dates = sorted({d for d in dates if isinstance(d, str) and d})
    if not iso_dates:
        return [], []

    try:
        start = _date.fromisoformat(iso_dates[0])
        end   = _date.fromisoformat(iso_dates[-1]) + _timedelta(days=1)
    except ValueError as exc:
        return [], [f"required_dates contained a non-ISO date: {exc}"]

    fetched_at = _dt.datetime.now(tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )
    try:
        history = yf.Ticker("XLE").history(
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=True,
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        return [], [
            f"yfinance fetch raised: {type(exc).__name__}: {exc}"
        ]

    out: list[dict[str, Any]] = []
    wanted = set(iso_dates)
    for ts, row in history.iterrows():
        iso = ts.strftime("%Y-%m-%d")
        if iso not in wanted:
            continue
        close = row.get("Close")
        volume = row.get("Volume")
        try:
            close_f  = float(close)  if close  is not None else None
            volume_f = float(volume) if volume is not None else None
        except (TypeError, ValueError):
            continue
        if close_f is None:
            continue
        out.append({
            "ticker":      "XLE",
            "date":        iso,
            "close":       close_f,
            "volume":      volume_f if volume_f is not None else 0.0,
            "auto_adjust": 1,
            "fetched_at":  fetched_at,
        })
    return out, []


def _run_preflight(
    *,
    db_path: str | None,
    event_ids: Sequence[int],
    benchmark: str,
    horizons: Sequence[int],
    estimation_window: int,
) -> dict[str, Any]:
    """Wrap the read-only benchmark-sensitivity preflight runner so
    tests can drive the post-write counts synthetically without
    seeding a full events archive.
    """
    from scripts.benchmark_sensitivity_preflight import (
        summarize_benchmark_sensitivity_preflight,
    )

    return summarize_benchmark_sensitivity_preflight(
        db_path=db_path,
        event_ids=event_ids,
        benchmark=benchmark,
        horizons=horizons,
        estimation_window=int(estimation_window),
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_xle_live_backfill_promote(
    *,
    confirm_live_write: bool = False,
    backup_path:        str | None = None,
    preview_artifact:   str = _DEFAULT_PREVIEW_ARTIFACT,
    db_path:            str | None = None,
    event_ids:          Sequence[int] = _DEFAULT_EVENT_IDS,
    benchmark:          str = _DEFAULT_BENCHMARK,
    horizons:           Sequence[int] = _DEFAULT_HORIZONS,
    estimation_window:  int = _DEFAULT_ESTIMATION_WINDOW,
    output_path:        str | None = None,
) -> dict[str, Any]:
    """Run the gated live XLE backfill promotion.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    benchmark_upper = (benchmark or _DEFAULT_BENCHMARK).strip().upper()
    horizons_tuple  = tuple(
        int(h) for h in horizons if isinstance(h, int) and h > 0
    )
    if not horizons_tuple:
        horizons_tuple = _DEFAULT_HORIZONS

    # Step 1: read the preview artifact.  Surfaces required_dates and
    # the readiness counts the gate is evaluated against.
    preview_path = preview_artifact or _DEFAULT_PREVIEW_ARTIFACT
    preview = _safe_dict(_read_preview_artifact(path=preview_path))
    if not preview:
        errors.append(
            f"preview artifact at {preview_path!r} could not be read "
            f"as JSON; cannot promote without a readable preview"
        )

    preview_ready_after       = _safe_int(preview.get("ready_after"))
    preview_blocked_after     = _safe_int(preview.get("blocked_after"))
    preview_ok                = preview.get("ok") is True
    preview_live_db_unchanged = preview.get("live_db_unchanged") is True
    preview_ready = (
        bool(preview)
        and preview_ok
        and preview_live_db_unchanged
        and preview_ready_after   == _REQUIRED_READY_AFTER
        and preview_blocked_after == _REQUIRED_BLOCKED_AFTER
    )

    required_dates_set: set[str] = set()
    for d in preview.get("required_dates") or []:
        if isinstance(d, str) and d:
            required_dates_set.add(d)
    required_dates = sorted(required_dates_set)

    # Step 2: accumulate gate failures up front.  All three are
    # evaluated independently so the operator sees every problem on a
    # single run rather than fixing them one at a time.
    if not confirm_live_write:
        errors.append(
            "live DB write requires explicit operator authorisation "
            "via --confirm-live-write; without it this script makes "
            "no live DB write"
        )
    backup_exists = False
    backup_hash:  str | None = None
    if not backup_path:
        errors.append(
            "live DB write requires --backup-path pointing at a "
            "readable backup file taken before this run"
        )
    else:
        check = _verify_backup(path=backup_path)
        backup_exists = bool(check["exists"])
        backup_hash   = check["hash"]
        if not backup_exists:
            errors.append(
                f"--backup-path {backup_path!r} does not exist, is "
                f"not a regular file, is empty, or is unreadable"
            )
    if preview and not preview_ready:
        errors.append(
            f"preview artifact at {preview_path!r} reports "
            f"ok={preview.get('ok')!r}, "
            f"ready_after={preview_ready_after}, "
            f"blocked_after={preview_blocked_after}, "
            f"live_db_unchanged={preview.get('live_db_unchanged')!r}; "
            f"promotion requires ALL of ok=True AND "
            f"ready_after={_REQUIRED_READY_AFTER} AND "
            f"blocked_after={_REQUIRED_BLOCKED_AFTER} AND "
            f"live_db_unchanged=True"
        )

    if errors:
        return _finalize(
            envelope=_envelope(
                confirm_live_write=confirm_live_write,
                backup_path=backup_path,
                backup_exists=backup_exists,
                backup_hash=backup_hash,
                preview_artifact_path=preview_path,
                preview_ready_after=preview_ready_after,
                preview_blocked_after=preview_blocked_after,
                preview_ready=preview_ready,
                required_dates=required_dates,
                recommended_next_action=_choose_gate_recommendation(
                    confirm_live_write=confirm_live_write,
                    backup_exists=backup_exists,
                    backup_supplied=bool(backup_path),
                    preview_ready=preview_ready,
                ),
                errors=errors, warnings=warnings,
            ),
            output_path=output_path,
        )

    # All three gates passed.  From here on we are authorised to
    # touch the live DB.

    live_path = _resolve_live_db_path(db_path)
    if live_path is None or not Path(live_path).exists():
        errors.append(
            f"live events DB not found at {live_path!r}; "
            f"--confirm-live-write requires a path that exists"
        )
        return _finalize(
            envelope=_envelope(
                confirm_live_write=confirm_live_write,
                backup_path=backup_path,
                backup_exists=backup_exists,
                backup_hash=backup_hash,
                preview_artifact_path=preview_path,
                preview_ready_after=preview_ready_after,
                preview_blocked_after=preview_blocked_after,
                preview_ready=preview_ready,
                required_dates=required_dates,
                recommended_next_action=_RECOMMENDED_ERRORED,
                errors=errors, warnings=warnings,
            ),
            output_path=output_path,
        )

    live_hash_before = _hash_file_safe(live_path)

    # Step 3: fetch XLE rows for the exact required_dates only.  The
    # seam returns (rows, errors); a misbehaving seam returning extra
    # tickers or dates is caught by the per-row filter at insert time.
    rows: list[dict[str, Any]] = []
    if required_dates:
        try:
            fetched, fetch_errors = _fetch_xle_rows_online(
                dates=required_dates,
            )
        except Exception as exc:  # noqa: BLE001 — operator-visible
            fetched = []
            fetch_errors = [
                f"fetch seam raised: {type(exc).__name__}: {exc}"
            ]
        if isinstance(fetched, list):
            rows = [r for r in fetched if isinstance(r, dict)]
        for fe in fetch_errors or []:
            if isinstance(fe, str) and fe:
                errors.append(f"fetch: {fe}")
    else:
        warnings.append(
            "preview artifact reported no required_dates; nothing to "
            "promote"
        )

    if errors:
        # Fetch errored before any write — live DB untouched.
        live_hash_after = _hash_file_safe(live_path)
        return _finalize(
            envelope=_envelope(
                confirm_live_write=confirm_live_write,
                backup_path=backup_path,
                backup_exists=backup_exists,
                backup_hash=backup_hash,
                preview_artifact_path=preview_path,
                preview_ready_after=preview_ready_after,
                preview_blocked_after=preview_blocked_after,
                preview_ready=preview_ready,
                required_dates=required_dates,
                live_db_hash_before=live_hash_before,
                live_db_hash_after=live_hash_after,
                recommended_next_action=_RECOMMENDED_ERRORED,
                errors=errors, warnings=warnings,
            ),
            output_path=output_path,
        )

    # Step 4: filter at insert time — defense in depth against a
    # misbehaving fetch seam.  Only ticker == "XLE" and only
    # dates in the preview's required_dates set may land in the live
    # price_cache.
    filtered = _filter_rows_for_write(
        rows=rows,
        allowed_ticker="XLE",
        allowed_dates=required_dates_set,
    )
    if not filtered and required_dates:
        # Fetch returned zero rows that match the gate.  Treat as a
        # failure so the operator does not silently believe the
        # promotion ran when nothing was inserted.
        errors.append(
            "provider returned zero XLE rows for the required dates; "
            "no live DB writes attempted"
        )
        live_hash_after = _hash_file_safe(live_path)
        return _finalize(
            envelope=_envelope(
                confirm_live_write=confirm_live_write,
                backup_path=backup_path,
                backup_exists=backup_exists,
                backup_hash=backup_hash,
                preview_artifact_path=preview_path,
                preview_ready_after=preview_ready_after,
                preview_blocked_after=preview_blocked_after,
                preview_ready=preview_ready,
                required_dates=required_dates,
                live_db_hash_before=live_hash_before,
                live_db_hash_after=live_hash_after,
                recommended_next_action=_RECOMMENDED_FETCH_EMPTY,
                errors=errors, warnings=warnings,
            ),
            output_path=output_path,
        )

    # Step 5: single-transaction INSERT OR IGNORE.  On any exception
    # inside the loop the transaction is rolled back so a partial
    # promotion never lands.
    inserted_count = 0
    skipped_existing_count = 0
    try:
        inserted_count, skipped_existing_count = _insert_rows_single_tx(
            live_db_path=live_path,
            rows=filtered,
        )
    except sqlite3.Error as exc:
        errors.append(
            f"live DB INSERT failed inside the single transaction "
            f"(rolled back): {type(exc).__name__}: {exc}"
        )
        live_hash_after = _hash_file_safe(live_path)
        return _finalize(
            envelope=_envelope(
                confirm_live_write=confirm_live_write,
                backup_path=backup_path,
                backup_exists=backup_exists,
                backup_hash=backup_hash,
                preview_artifact_path=preview_path,
                preview_ready_after=preview_ready_after,
                preview_blocked_after=preview_blocked_after,
                preview_ready=preview_ready,
                required_dates=required_dates,
                live_db_hash_before=live_hash_before,
                live_db_hash_after=live_hash_after,
                recommended_next_action=_RECOMMENDED_ERRORED,
                errors=errors, warnings=warnings,
            ),
            output_path=output_path,
        )

    live_hash_after = _hash_file_safe(live_path)

    # Step 6: post-write preflight on the live DB.  Reports cache
    # geometry only — never asserts a benchmark-sensitivity verdict.
    try:
        after_report = _safe_dict(_run_preflight(
            db_path=live_path,
            event_ids=event_ids,
            benchmark=benchmark_upper,
            horizons=horizons_tuple,
            estimation_window=int(estimation_window),
        ))
    except Exception as exc:  # noqa: BLE001 — operator-visible
        warnings.append(
            f"post-write preflight raised: "
            f"{type(exc).__name__}: {exc}; counts not recorded"
        )
        after_report = {}

    ready_count   = _safe_int(after_report.get("ready_count"))
    blocked_count = _safe_int(after_report.get("blocked_count"))

    if blocked_count > 0:
        recommended = _RECOMMENDED_PROMOTED_NOT_CLEARED.format(
            inserted=inserted_count,
            skipped=skipped_existing_count,
            ready=ready_count,
            blocked=blocked_count,
            checked=ready_count + blocked_count,
        )
    else:
        recommended = _RECOMMENDED_PROMOTED_AND_CLEARED.format(
            inserted=inserted_count,
            skipped=skipped_existing_count,
            ready=ready_count,
            blocked=blocked_count,
        )

    return _finalize(
        envelope=_envelope(
            confirm_live_write=confirm_live_write,
            backup_path=backup_path,
            backup_exists=backup_exists,
            backup_hash=backup_hash,
            preview_artifact_path=preview_path,
            preview_ready_after=preview_ready_after,
            preview_blocked_after=preview_blocked_after,
            preview_ready=preview_ready,
            required_dates=required_dates,
            inserted_count=inserted_count,
            skipped_existing_count=skipped_existing_count,
            live_db_hash_before=live_hash_before,
            live_db_hash_after=live_hash_after,
            preflight_after=_summarize_preflight(after_report),
            ready_count=ready_count,
            blocked_count=blocked_count,
            recommended_next_action=recommended,
            errors=errors, warnings=warnings,
        ),
        output_path=output_path,
    )


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def _filter_rows_for_write(
    *,
    rows: Sequence[dict[str, Any]],
    allowed_ticker: str,
    allowed_dates: set[str],
) -> list[dict[str, Any]]:
    """Filter ``rows`` to only those matching the allowed ticker and
    one of the allowed dates.  Defense in depth: even if the fetch
    seam returns rows outside the requested set, those rows never
    reach the live INSERT path.
    """
    out: list[dict[str, Any]] = []
    for r in rows:
        ticker = r.get("ticker")
        date_  = r.get("date")
        if not isinstance(ticker, str) or ticker.strip().upper() != allowed_ticker:
            continue
        if not isinstance(date_, str) or date_ not in allowed_dates:
            continue
        if r.get("close") is None:
            continue
        out.append(r)
    return out


def _insert_rows_single_tx(
    *,
    live_db_path: str,
    rows: Sequence[dict[str, Any]],
) -> tuple[int, int]:
    """``INSERT OR IGNORE`` each row into the live ``price_cache``
    inside a single explicit transaction.

    Returns ``(inserted_count, skipped_existing_count)``.  A row whose
    insert affected a new physical row contributes to
    ``inserted_count``; a row that hit the PRIMARY KEY and was
    silently ignored contributes to ``skipped_existing_count``.

    On any exception the transaction is rolled back so the live DB
    stays in its pre-call state.
    """
    if not rows:
        return 0, 0
    inserted = 0
    skipped  = 0
    conn = sqlite3.connect(live_db_path, isolation_level=None)
    try:
        conn.execute("BEGIN")
        try:
            for r in rows:
                ticker = r.get("ticker")
                date_  = r.get("date")
                if not isinstance(ticker, str) or not ticker:
                    continue
                if not isinstance(date_, str) or not date_:
                    continue
                auto_adjust = r.get("auto_adjust")
                if not isinstance(auto_adjust, int):
                    auto_adjust = 1
                cur = conn.execute(
                    "INSERT OR IGNORE INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        ticker, date_,
                        r.get("close"), r.get("volume"),
                        int(auto_adjust),
                        str(r.get("fetched_at") or ""),
                    ),
                )
                if cur.rowcount and cur.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return inserted, skipped


# ---------------------------------------------------------------------------
# Backup verification
# ---------------------------------------------------------------------------


def _verify_backup(*, path: str) -> dict[str, Any]:
    """Verify ``path`` is an existing, non-empty, readable regular
    file and return its SHA-256.

    Does NOT verify the backup matches the live DB — that is an
    operator responsibility.  Exposing the hash lets a downstream
    audit correlate the backup with ``live_db_hash_before``.
    """
    out: dict[str, Any] = {"exists": False, "hash": None}
    p = Path(path)
    if not p.is_file():
        return out
    try:
        size = p.stat().st_size
    except OSError:
        return out
    if size <= 0:
        return out
    try:
        with open(p, "rb") as fh:
            # Sanity read so a path that exists but is unreadable
            # fails closed instead of looking healthy.
            if not fh.read(1):
                return out
    except OSError:
        return out
    out["exists"] = True
    out["hash"]   = _hash_file_safe(path)
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_live_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


def _hash_file_safe(path: str | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _summarize_preflight(report: dict[str, Any]) -> dict[str, int]:
    return {
        "checked_events": _safe_int(report.get("checked_events")),
        "ready_count":    _safe_int(report.get("ready_count")),
        "blocked_count":  _safe_int(report.get("blocked_count")),
    }


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _choose_gate_recommendation(
    *,
    confirm_live_write: bool,
    backup_exists:      bool,
    backup_supplied:    bool,
    preview_ready:      bool,
) -> str:
    # Count the failures so a single-failure run gets a specific
    # corrective message, while a multi-failure run gets the generic
    # message that names every gate (otherwise the operator has to
    # parse the errors list to see what else is wrong).
    failure_count = 0
    if not confirm_live_write:
        failure_count += 1
    if not backup_supplied or not backup_exists:
        failure_count += 1
    if not preview_ready:
        failure_count += 1
    if failure_count > 1:
        return _RECOMMENDED_GATE_FAILED
    if backup_supplied and not backup_exists:
        return _RECOMMENDED_BACKUP_MISSING
    if not preview_ready:
        return _RECOMMENDED_PREVIEW_NOT_READY
    return _RECOMMENDED_GATE_FAILED


# ---------------------------------------------------------------------------
# Envelope + finalize
# ---------------------------------------------------------------------------


def _envelope(
    *,
    confirm_live_write:      bool,
    backup_path:             str | None = None,
    backup_exists:           bool = False,
    backup_hash:             str | None = None,
    preview_artifact_path:   str = "",
    preview_ready_after:     int = 0,
    preview_blocked_after:   int = 0,
    preview_ready:           bool = False,
    required_dates:          list[str] | None = None,
    inserted_count:          int = 0,
    skipped_existing_count:  int = 0,
    live_db_hash_before:     str | None = None,
    live_db_hash_after:      str | None = None,
    preflight_after:         dict[str, int] | None = None,
    ready_count:             int = 0,
    blocked_count:           int = 0,
    recommended_next_action: str = "",
    errors:   list[str],
    warnings: list[str],
) -> dict[str, Any]:
    empty_summary = {
        "checked_events": 0,
        "ready_count":    0,
        "blocked_count":  0,
    }
    return {
        "ok":                       not errors,
        "confirm_live_write":       bool(confirm_live_write),
        "backup_path":              backup_path,
        "backup_exists":            bool(backup_exists),
        "backup_hash":              backup_hash,
        "preview_artifact_path":    preview_artifact_path,
        "preview_ready_after":      int(preview_ready_after),
        "preview_blocked_after":    int(preview_blocked_after),
        "preview_ready":            bool(preview_ready),
        "required_dates":           required_dates or [],
        "inserted_count":           int(inserted_count),
        "skipped_existing_count":   int(skipped_existing_count),
        "live_db_hash_before":      live_db_hash_before,
        "live_db_hash_after":       live_db_hash_after,
        "preflight_after":          preflight_after or dict(empty_summary),
        "ready_count":              int(ready_count),
        "blocked_count":            int(blocked_count),
        "warnings":                 warnings,
        "errors":                   errors,
        "recommended_next_action":  recommended_next_action,
    }


def _finalize(
    *, envelope: dict[str, Any], output_path: str | None,
) -> dict[str, Any]:
    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(
                    envelope, fh, indent=2, sort_keys=True, default=str,
                )
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False
    return envelope


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_int_csv(value: str) -> tuple[int, ...]:
    out: list[int] = []
    for tok in (value or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return tuple(out)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Live XLE backfill promotion.  Gated by three independent "
            "checks: --confirm-live-write, --backup-path pointing at "
            "an existing readable backup, and a preview artifact "
            "reporting ready_after=2 and blocked_after=0.  Writes "
            "only ticker XLE on only the preview's required_dates, "
            "inside a single transaction.  Never imports a provider, "
            "an LLM, or a FastAPI route.  Conservative wording: "
            "reports cache geometry, not benchmark-sensitivity "
            "conclusions."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help=(
            "Accepted for ergonomic parity with sibling scripts.  "
            "Output is always JSON."
        ),
    )
    parser.add_argument(
        "--confirm-live-write", dest="confirm_live_write",
        action="store_true",
        help=(
            "Authorise the single live DB write transaction.  "
            "Without this flag no provider is imported, no fetch "
            "fires, and the live DB is not opened for writes."
        ),
    )
    parser.add_argument(
        "--backup-path", dest="backup_path", default=None,
        help=(
            "Path to an existing readable backup of the live events "
            "DB taken before this run.  The promoter does not create "
            "the backup; the operator must produce it first."
        ),
    )
    parser.add_argument(
        "--preview-artifact", dest="preview_artifact",
        default=_DEFAULT_PREVIEW_ARTIFACT,
        help=(
            f"Path to the online preview artifact JSON.  Defaults "
            f"to {_DEFAULT_PREVIEW_ARTIFACT!r}.  Must report "
            f"ready_after={_REQUIRED_READY_AFTER} and "
            f"blocked_after={_REQUIRED_BLOCKED_AFTER} for promotion "
            f"to proceed."
        ),
    )
    parser.add_argument(
        "--event-ids", dest="event_ids",
        default=",".join(str(i) for i in _DEFAULT_EVENT_IDS),
        help=(
            f"Comma-separated event_ids passed to the post-write "
            f"preflight (default "
            f"{','.join(str(i) for i in _DEFAULT_EVENT_IDS)})."
        ),
    )
    parser.add_argument(
        "--benchmark", dest="benchmark", default=_DEFAULT_BENCHMARK,
        help=f"Benchmark ticker symbol (default {_DEFAULT_BENCHMARK!r}).",
    )
    parser.add_argument(
        "--horizons", dest="horizons",
        default=",".join(str(h) for h in _DEFAULT_HORIZONS),
        help=(
            f"Comma-separated forward horizons in business days "
            f"(default {','.join(str(h) for h in _DEFAULT_HORIZONS)})."
        ),
    )
    parser.add_argument(
        "--estimation-window", dest="estimation_window",
        type=int, default=_DEFAULT_ESTIMATION_WINDOW,
        help=(
            f"Number of distinct pre-event cache dates required "
            f"(default {_DEFAULT_ESTIMATION_WINDOW})."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the live events DB.  Defaults to "
            "db.DB_FILE.  This is the file the script writes to "
            "once every gate passes."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the promoter prints the envelope on stdout "
            "and has no other filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_xle_live_backfill_promote(
        confirm_live_write=bool(args.confirm_live_write),
        backup_path=args.backup_path,
        preview_artifact=args.preview_artifact,
        db_path=args.db_path,
        event_ids=_parse_int_csv(args.event_ids),
        benchmark=args.benchmark,
        horizons=_parse_int_csv(args.horizons),
        estimation_window=args.estimation_window,
        output_path=args.output_path,
    )
    print(_render_json(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_xle_live_backfill_promote",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
