#!/usr/bin/env python3
"""Temp-only online XLE backfill preview.

Reads the exact missing XLE estimation-window dates from
:mod:`scripts.xle_benchmark_backfill_request_packet`, optionally
fetches just those dates from an online market-data provider, stages
the fetched rows into a TEMP DB copy only, and re-runs
:func:`scripts.benchmark_sensitivity_preflight.summarize_benchmark_sensitivity_preflight`
to see whether events 60 and 73 become benchmark-ready.

Two modes
---------

* **Default (no ``--confirm-online``).**  The preview NEVER opens
  the live DB for writes, NEVER copies the live DB, NEVER imports a
  market-data provider, and NEVER calls the network.  It builds the
  request packet so the operator sees the required dates verbatim,
  then returns ``ok=False`` with an explicit message pointing at
  ``--confirm-online`` as the next step.  This is the safe default
  any verification pipeline can call without authorisation.

* **Online preview (``--confirm-online``).**  Copies the live DB to
  a temp file, runs the preflight against the temp copy, calls the
  patchable seam :func:`_fetch_xle_rows_online` (which lazily
  imports ``yfinance``) for ticker ``XLE`` and the exact required
  dates only, ``INSERT OR IGNORE``-s the returned rows into the
  temp DB's ``price_cache`` table, then re-runs the preflight on
  the same temp DB and reports the before / after counts.

Read-only constraints
---------------------

* No live DB writes.  The live DB is hashed before and after the
  online run and ``live_db_unchanged`` surfaces byte-identity.
* No DB writes outside the auto-retained temp copy.
* No Anthropic / LLM / FastAPI surface (never imports ``api`` /
  ``routes.*``).
* The default code path never imports ``yfinance`` or any other
  market-data provider.  ``--confirm-online`` is the *only* gate
  that authorises the lazy import inside the fetch seam.
* Fetches only ``XLE`` and only the dates surfaced by the request
  packet.  Never fabricates prices — a date for which the provider
  returns no row is *not* synthesised and lands in
  ``still_missing_dates``.
* No SPY-vs-XLE inference; the preview reports cache geometry only.

Output contract (JSON, EXACTLY 16 keys)::

    {
      "ok":                       bool,
      "confirm_online":           bool,
      "required_dates":           [str, ...],
      "fetched_rows":             int,
      "inserted_temp_rows":       int,
      "preflight_before": {
        "checked_events": int,
        "ready_count":    int,
        "blocked_count":  int,
      },
      "preflight_after": {
        "checked_events": int,
        "ready_count":    int,
        "blocked_count":  int,
      },
      "ready_before":             int,
      "ready_after":              int,
      "blocked_before":           int,
      "blocked_after":            int,
      "still_missing_dates":      [str, ...],
      "live_db_unchanged":        bool,
      "warnings":                 [str, ...],
      "errors":                   [str, ...],
      "recommended_next_action":  str,
    }

Patchable seams
---------------

  * ``_build_request_packet(*, db_path, event_ids, benchmark,
    horizons, estimation_window)`` — returns the
    ``build_xle_benchmark_backfill_request_packet`` envelope so tests
    can drive ``required_dates`` synthetically.
  * ``_copy_live_db_to_temp(*, src_path)`` — ``shutil.copy2`` from
    src to a fresh file in ``tempfile.gettempdir()``.
  * ``_fetch_xle_rows_online(*, dates)`` — lazy ``yfinance`` import
    + filtered fetch.  Returns ``(rows, errors)``.  Tests patch this
    seam directly so the no-paid invariants hold even when
    ``--confirm-online`` is exercised.
  * ``_run_preflight(*, db_path, event_ids, benchmark, horizons,
    estimation_window)`` — wraps the read-only benchmark-sensitivity
    preflight runner so tests can drive the before / after
    transition without seeding a full events archive.

Conservative wording — the preview reports cache geometry, not
market evidence.  Banned tokens in any text the preview emits:
``proof``, ``proves``, ``alpha``, ``guaranteed``, ``automatically``,
``definitely validated``, ``is proven``.  The preview never asserts
SPY-vs-XLE conclusions.

Usage::

    python scripts/xle_online_backfill_preview.py --json
    python scripts/xle_online_backfill_preview.py --json --confirm-online
    python scripts/xle_online_backfill_preview.py --json --confirm-online \\
        --output artifacts/xle_online_backfill_preview.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import uuid
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


# Recommendation templates — each one is a closed message the
# operator can branch on without parsing English.  Banned tokens are
# absent by construction.
_RECOMMENDED_CONFIRM_ONLINE_REQUIRED: str = (
    "Online market-data fetch was NOT attempted because "
    "--confirm-online was not supplied.  Required dates surfaced in "
    "'required_dates' so the operator can audit them first.  Pass "
    "--confirm-online to authorise a single XLE-only, dates-only "
    "fetch into a TEMP DB copy (the live DB is never opened for "
    "writes)."
)
_RECOMMENDED_ERRORED: str = (
    "Preview surfaced errors before the before/after counts settled. "
    " Inspect 'errors' before relying on any of the preflight blocks."
)
_RECOMMENDED_NO_REQUIRED_DATES: str = (
    "Request packet reports zero required dates — the preflight "
    "surfaced no missing XLE benchmark coverage.  Nothing to fetch."
)
_RECOMMENDED_ONLINE_NO_ROWS: str = (
    "Online fetch returned zero rows for the {n} requested date(s); "
    "every required date lands in 'still_missing_dates' and the "
    "events stay blocked in the temp preview."
)
_RECOMMENDED_ONLINE_CLEARED: str = (
    "Online fetch returned {fetched} row(s); {inserted} new row(s) "
    "staged into the temp DB.  All {checked} checked event(s) now "
    "become benchmark-ready against {bench} in the temp preview.  "
    "The live DB is unchanged.  Live promotion may be considered "
    "ONLY after taking a backup of the live events DB and supplying "
    "an explicit, separate live-confirmation flag — do not promote "
    "without both.  This preview reports cache geometry only and "
    "does not infer any benchmark-sensitivity conclusion."
)
_RECOMMENDED_ONLINE_PARTIAL: str = (
    "Online fetch returned {fetched} row(s); {inserted} new row(s) "
    "staged into the temp DB.  {blocked} of {checked} event(s) "
    "still blocked.  Do NOT promote to live.  Inspect "
    "'still_missing_dates' and each blocked event's per-row "
    "blockers before any further action."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _build_request_packet(
    *,
    db_path: str | None,
    event_ids: Sequence[int],
    benchmark: str,
    horizons: Sequence[int],
    estimation_window: int,
) -> dict[str, Any]:
    """Wrap the XLE benchmark backfill request packet builder so
    tests patch a single seam.  Lazy import keeps the preview's
    import graph free of the upstream preflight/event surface on
    the patched test path.
    """
    from scripts.xle_benchmark_backfill_request_packet import (
        build_xle_benchmark_backfill_request_packet,
    )

    return build_xle_benchmark_backfill_request_packet(
        db_path=db_path,
        event_ids=event_ids,
        benchmark=benchmark,
        horizons=horizons,
        estimation_window=estimation_window,
    )


def _copy_live_db_to_temp(*, src_path: str) -> str:
    """``shutil.copy2`` from ``src_path`` to a fresh file inside
    ``tempfile.gettempdir()``.  The temp DB is retained on disk after
    the preview returns so an operator can inspect the staged rows;
    its path is surfaced via a warning.
    """
    src = Path(src_path)
    dst_name = (
        f"xle_online_preview_{uuid.uuid4().hex}{src.suffix or '.db'}"
    )
    dst = Path(tempfile.gettempdir()) / dst_name
    shutil.copy2(str(src), str(dst))
    return str(dst)


def _fetch_xle_rows_online(
    *, dates: Sequence[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch ticker ``XLE`` bars for the exact ``dates`` from the
    online market-data provider.  Returns ``(rows, errors)``.

    Lazily imports ``yfinance`` so the default code path (no
    ``--confirm-online``) never pulls a provider into ``sys.modules``.
    Tests MUST patch this seam to keep the no-paid invariants in
    place even when ``--confirm-online`` is exercised.

    Each returned row carries
    ``(ticker, date, close, volume, auto_adjust, fetched_at)``.
    Dates with no provider data are silently omitted; the caller
    compares the returned set against the requested set to populate
    ``still_missing_dates``.  Prices are NEVER fabricated.
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
    """Wrap the benchmark-sensitivity preflight runner so tests can
    drive the before / after transition with synthetic payloads
    without seeding a full events archive.
    """
    from scripts.benchmark_sensitivity_preflight import (
        summarize_benchmark_sensitivity_preflight,
    )

    return summarize_benchmark_sensitivity_preflight(
        db_path=db_path,
        event_ids=event_ids,
        benchmark=benchmark,
        horizons=horizons,
        estimation_window=estimation_window,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_xle_online_backfill_preview(
    *,
    confirm_online:    bool = False,
    db_path:           str | None = None,
    event_ids:         Sequence[int] = _DEFAULT_EVENT_IDS,
    benchmark:         str = _DEFAULT_BENCHMARK,
    horizons:          Sequence[int] = _DEFAULT_HORIZONS,
    estimation_window: int = _DEFAULT_ESTIMATION_WINDOW,
    output_path:       str | None = None,
) -> dict[str, Any]:
    """Run the temp-only XLE online backfill preview.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    benchmark_upper = (benchmark or _DEFAULT_BENCHMARK).strip().upper()
    horizons_tuple = tuple(
        int(h) for h in horizons if isinstance(h, int) and h > 0
    )
    if not horizons_tuple:
        horizons_tuple = _DEFAULT_HORIZONS

    # Step 1: build the request packet.  The packet is read-only so
    # this runs in BOTH modes — without --confirm-online the
    # operator still sees the dates that would be needed.
    packet = _safe_dict(_build_request_packet(
        db_path=db_path,
        event_ids=event_ids,
        benchmark=benchmark_upper,
        horizons=horizons_tuple,
        estimation_window=int(estimation_window),
    ))
    required_dates: list[str] = [
        d for d in (packet.get("required_dates") or [])
        if isinstance(d, str)
    ]
    for w in packet.get("warnings") or []:
        if isinstance(w, str) and w:
            warnings.append(f"packet: {w}")
    for e in packet.get("errors") or []:
        if isinstance(e, str) and e:
            errors.append(f"packet: {e}")

    # Step 2: --confirm-online gate.  Without the flag, refuse to
    # copy / fetch / run preflight.  Surface required_dates so the
    # operator audits the request, return ok=False with a clear
    # error pointing at the missing flag.
    if not confirm_online:
        errors.append(
            "online market-data fetch requires explicit operator "
            "authorisation via --confirm-online; without it this "
            "preview makes no network request, no temp DB copy, and "
            "no preflight run"
        )
        return _finalize(
            envelope=_envelope(
                confirm_online=False,
                required_dates=required_dates,
                live_db_unchanged=True,
                recommended_next_action=_RECOMMENDED_CONFIRM_ONLINE_REQUIRED,
                errors=errors, warnings=warnings,
            ),
            output_path=output_path,
        )

    # From here on we have explicit authorisation for the temp-only
    # online flow.  The live DB is still NEVER opened for writes.

    live_path = _resolve_live_db_path(db_path)
    if live_path is None or not Path(live_path).exists():
        errors.append(
            f"live events DB not found at {live_path!r}; "
            f"--confirm-online requires a path that exists"
        )
        return _finalize(
            envelope=_envelope(
                confirm_online=True,
                required_dates=required_dates,
                live_db_unchanged=True,
                recommended_next_action=_RECOMMENDED_ERRORED,
                errors=errors, warnings=warnings,
            ),
            output_path=output_path,
        )

    live_hash_before = _hash_file_safe(live_path)

    # Step 3: copy live → temp.
    try:
        temp_db_path = _copy_live_db_to_temp(src_path=live_path)
    except OSError as exc:
        errors.append(f"failed to copy live DB to temp: {exc}")
        return _finalize(
            envelope=_envelope(
                confirm_online=True,
                required_dates=required_dates,
                live_db_unchanged=True,
                recommended_next_action=_RECOMMENDED_ERRORED,
                errors=errors, warnings=warnings,
            ),
            output_path=output_path,
        )
    warnings.append(
        f"Temp DB copy retained at {temp_db_path} for inspection — "
        f"clean up manually if not needed."
    )

    # Step 4: preflight BEFORE.
    before_report = _safe_dict(_run_preflight(
        db_path=temp_db_path,
        event_ids=event_ids,
        benchmark=benchmark_upper,
        horizons=horizons_tuple,
        estimation_window=int(estimation_window),
    ))

    # Step 5: online fetch.  Only when required_dates is non-empty.
    fetched_rows: list[dict[str, Any]] = []
    if required_dates:
        rows, fetch_errors = _fetch_xle_rows_online(dates=required_dates)
        if isinstance(rows, list):
            fetched_rows = [r for r in rows if isinstance(r, dict)]
        for fe in fetch_errors or []:
            if isinstance(fe, str) and fe:
                errors.append(f"fetch: {fe}")

    # Step 6: INSERT into temp DB.
    inserted_temp_rows = 0
    if fetched_rows:
        try:
            inserted_temp_rows = _insert_rows_into_temp_price_cache(
                temp_db_path=temp_db_path, rows=fetched_rows,
            )
        except sqlite3.Error as exc:
            errors.append(f"temp DB INSERT failed: {exc}")
            inserted_temp_rows = 0

    # Step 7: preflight AFTER.  Always called, even when fetch
    # returned zero rows, so before / after are symmetric.
    after_report = _safe_dict(_run_preflight(
        db_path=temp_db_path,
        event_ids=event_ids,
        benchmark=benchmark_upper,
        horizons=horizons_tuple,
        estimation_window=int(estimation_window),
    ))

    # Step 8: still_missing_dates.  Every required date the provider
    # did NOT return a row for surfaces here.  The operator decides
    # whether the gap is real (delisted / holiday / sparse coverage).
    fetched_date_set = {
        r.get("date") for r in fetched_rows
        if isinstance(r.get("date"), str)
    }
    still_missing_dates = sorted(
        d for d in required_dates if d not in fetched_date_set
    )

    # Step 9: live DB byte-identity.
    live_hash_after = _hash_file_safe(live_path)
    live_db_unchanged = (
        live_hash_before is not None
        and live_hash_after is not None
        and live_hash_before == live_hash_after
    )
    if (
        live_hash_before is not None
        and live_hash_after  is not None
        and live_hash_before != live_hash_after
    ):
        errors.append(
            f"LIVE DB BYTES CHANGED during XLE online backfill "
            f"preview — investigate: {live_path}"
        )

    ready_before    = _safe_int(before_report.get("ready_count"))
    ready_after     = _safe_int(after_report.get("ready_count"))
    blocked_before  = _safe_int(before_report.get("blocked_count"))
    blocked_after   = _safe_int(after_report.get("blocked_count"))
    checked_after   = _safe_int(after_report.get("checked_events"))

    recommended = _recommend(
        has_errors=bool(errors),
        required_dates_count=len(required_dates),
        fetched_count=len(fetched_rows),
        inserted_count=inserted_temp_rows,
        blocked_after=blocked_after,
        checked=checked_after,
        benchmark=benchmark_upper,
    )

    return _finalize(
        envelope=_envelope(
            confirm_online=True,
            required_dates=required_dates,
            fetched_rows=len(fetched_rows),
            inserted_temp_rows=inserted_temp_rows,
            preflight_before=_summarize_preflight(before_report),
            preflight_after=_summarize_preflight(after_report),
            ready_before=ready_before,
            ready_after=ready_after,
            blocked_before=blocked_before,
            blocked_after=blocked_after,
            still_missing_dates=still_missing_dates,
            live_db_unchanged=live_db_unchanged,
            recommended_next_action=recommended,
            errors=errors, warnings=warnings,
        ),
        output_path=output_path,
    )


# ---------------------------------------------------------------------------
# Temp-DB INSERT
# ---------------------------------------------------------------------------


def _insert_rows_into_temp_price_cache(
    *, temp_db_path: str, rows: Sequence[dict[str, Any]],
) -> int:
    """``INSERT OR IGNORE`` each row into the temp DB's price_cache
    table.  Returns the count of rows whose insert affected a new
    physical row.  Duplicates against the PRIMARY KEY are silently
    skipped so the preview stays idempotent across repeated runs
    against the same temp DB.
    """
    if not rows:
        return 0
    inserted = 0
    conn = sqlite3.connect(temp_db_path)
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
        conn.commit()
    finally:
        conn.close()
    return inserted


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


def _recommend(
    *,
    has_errors: bool,
    required_dates_count: int,
    fetched_count: int,
    inserted_count: int,
    blocked_after: int,
    checked: int,
    benchmark: str,
) -> str:
    if has_errors:
        return _RECOMMENDED_ERRORED
    if required_dates_count == 0:
        return _RECOMMENDED_NO_REQUIRED_DATES
    if fetched_count == 0:
        return _RECOMMENDED_ONLINE_NO_ROWS.format(n=required_dates_count)
    if blocked_after <= 0:
        return _RECOMMENDED_ONLINE_CLEARED.format(
            fetched=fetched_count, inserted=inserted_count,
            checked=checked or required_dates_count,
            bench=benchmark or "(unspecified)",
        )
    return _RECOMMENDED_ONLINE_PARTIAL.format(
        fetched=fetched_count, inserted=inserted_count,
        blocked=blocked_after, checked=checked or required_dates_count,
    )


# ---------------------------------------------------------------------------
# Envelope + finalize
# ---------------------------------------------------------------------------


def _envelope(
    *,
    confirm_online:        bool,
    required_dates:        list[str] | None = None,
    fetched_rows:          int = 0,
    inserted_temp_rows:    int = 0,
    preflight_before:      dict[str, int] | None = None,
    preflight_after:       dict[str, int] | None = None,
    ready_before:          int = 0,
    ready_after:           int = 0,
    blocked_before:        int = 0,
    blocked_after:         int = 0,
    still_missing_dates:   list[str] | None = None,
    live_db_unchanged:     bool = True,
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
        "confirm_online":           bool(confirm_online),
        "required_dates":           required_dates or [],
        "fetched_rows":             int(fetched_rows),
        "inserted_temp_rows":       int(inserted_temp_rows),
        "preflight_before":         preflight_before or dict(empty_summary),
        "preflight_after":          preflight_after  or dict(empty_summary),
        "ready_before":             ready_before,
        "ready_after":              ready_after,
        "blocked_before":           blocked_before,
        "blocked_after":            blocked_after,
        "still_missing_dates":      still_missing_dates or [],
        "live_db_unchanged":        live_db_unchanged,
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
            "Temp-only XLE online backfill preview.  Reads the exact "
            "missing XLE dates from the request packet, optionally "
            "fetches just those dates from a market-data provider, "
            "stages the rows into a TEMP DB copy only, and re-runs "
            "the benchmark-sensitivity preflight.  Default: no "
            "network, no copy, no preflight; ok=False until "
            "--confirm-online is supplied.  Never mutates the live "
            "DB.  Conservative wording: the preview reports cache "
            "geometry, not market evidence."
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
        "--confirm-online", dest="confirm_online", action="store_true",
        help=(
            "Authorise a single online fetch of the request packet's "
            "required XLE dates.  Without this flag the preview "
            "never imports or calls any market-data provider, never "
            "copies the live DB, and returns ok=False."
        ),
    )
    parser.add_argument(
        "--event-ids", dest="event_ids",
        default=",".join(str(i) for i in _DEFAULT_EVENT_IDS),
        help=(
            f"Comma-separated event_ids to check (default "
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
            "db.DB_FILE.  Read-only by construction."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the preview has no filesystem side effect "
            "outside the retained temp DB copy."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_xle_online_backfill_preview(
        confirm_online=bool(args.confirm_online),
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
    "run_xle_online_backfill_preview",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
