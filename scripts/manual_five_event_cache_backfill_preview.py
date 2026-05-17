#!/usr/bin/env python3
"""Online preview for the 5-event historical cache backfill.

Reads the operator-curated CSV at
``examples/manual_five_event_expansion_batch.csv`` and reports, per
ticker and per event, the historical date window the read-only
validation path would need plus the bar count already cached in the
live ``price_cache`` table.  Two modes:

* **Default (no ``--confirm-online``).**  Pure preview.  The script
  makes no network request, never opens any DB file for writes,
  never imports ``yfinance``, and never creates a temp file.  The
  output envelope reports ``fetched_rows = 0``, ``temp_db_path =
  None``, and a ``blocked_reasons`` entry citing the missing
  ``--confirm-online`` flag.  Safe for any verification pipeline.

* **``--confirm-online``.**  Authorises a single online fetch per
  (ticker, window) via the patchable
  :func:`_fetch_ticker_rows_online` seam (which lazily imports
  ``yfinance``).  Fetched rows are inserted into a freshly-created
  TEMP SQLite file — NEVER the live cache.  The temp DB path is
  surfaced via ``temp_db_path`` so the operator can inspect or
  promote the staged rows in a separate, explicit step.  The live
  ``events.db`` file is hashed before and after; ``live_db_unchanged``
  surfaces byte-identity.

Promotion to the live cache is intentionally out of scope for this
script.  Producing a temp bundle and promoting it are separate
authorisation steps.

Constraints (pinned by the test suite):

* No live DB or live cache writes in either mode.
* No paid market-data provider, no LLM, no FastAPI surface, no
  ``routes.*`` import — neither at module load nor under
  ``--confirm-online``.  The only online seam is ``yfinance``, lazily
  imported inside :func:`_fetch_ticker_rows_online` (free provider).
* No ``/movers/*`` or other GET-endpoint side effect — the script
  never starts a server and never calls a request handler.
* Conservative wording — the preview reports cache geometry, not
  market evidence.  Banned overclaim tokens are absent from any
  rendered output.

Output contract (JSON, exactly 16 keys)::

    {
      "ok":                    bool,
      "mode":                  "preview" | "online",
      "confirm_online":        bool,
      "input_csv":             str,
      "rows_loaded":           int,
      "candidates":            [{candidate_id, row_index, event_date,
                                 headline, mechanism_family,
                                 primary_ticker, benchmark_ticker}, ...],
      "tickers":               [str, ...],
      "windows":               [{ticker, candidate_id, event_date,
                                 start, end, cached_bars,
                                 fetched_bars}, ...],
      "fetched_rows":          int,
      "inserted_temp_rows":    int,
      "temp_db_path":          str | None,
      "blocked_reasons":       [str, ...],
      "live_db_unchanged":     bool,
      "warnings":              [str, ...],
      "errors":                [str, ...],
      "recommended_next_action": str,
    }

Usage::

    python scripts/manual_five_event_cache_backfill_preview.py --json
    python scripts/manual_five_event_cache_backfill_preview.py --json \\
        --confirm-online
    python scripts/manual_five_event_cache_backfill_preview.py --json \\
        --input-csv examples/manual_five_event_expansion_batch.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
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


_DEFAULT_INPUT_CSV: str = "examples/manual_five_event_expansion_batch.csv"
_CANDIDATE_PREFIX:  str = "manual-five-"

# Calendar-day padding around the event date.  Mirrors
# scripts/manual_five_event_validation_smoke.py so a successful
# online preview lines up with the read-only validation path.
_LOAD_PRE_CAL_DAYS:  int = 200
_LOAD_POST_CAL_DAYS: int = 60


_PRICE_CACHE_DDL: str = """
CREATE TABLE IF NOT EXISTS price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()


_RECOMMENDED_PREVIEW_ONLY: str = (
    "Preview mode only.  No online fetch was attempted because "
    "--confirm-online was not supplied.  The 'windows' list shows "
    "which (ticker, window) pairs would be requested; the live cache "
    "is untouched.  Pass --confirm-online to authorise a single fetch "
    "per ticker/window into a TEMP SQLite file (the live cache stays "
    "byte-identical)."
)
_RECOMMENDED_ONLINE_OK: str = (
    "Online preview ran: {fetched} row(s) fetched across {nt} ticker(s) "
    "and inserted into the TEMP SQLite at {temp_db_path}.  The live "
    "events DB is unchanged.  Promotion to the live cache is a "
    "separate, explicit step and is intentionally out of scope for "
    "this script.  Inspect the temp DB before any further action."
)
_RECOMMENDED_ONLINE_PARTIAL: str = (
    "Online preview ran with {err_count} fetch error(s); {fetched} "
    "row(s) inserted into the TEMP SQLite at {temp_db_path}.  The "
    "live events DB is unchanged.  Inspect 'errors' before relying on "
    "the staged rows."
)
_RECOMMENDED_ONLINE_NO_ROWS: str = (
    "Online preview ran but the provider returned zero rows across "
    "every (ticker, window) requested.  Nothing was staged.  The "
    "live events DB is unchanged."
)
_RECOMMENDED_CSV_MISSING: str = (
    "Input CSV is missing.  No window was computed and no fetch was "
    "attempted.  The live events DB is unchanged."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _read_cached_window(
    *, ticker: str, start: str, end: str,
) -> list[str]:
    """Read the cached trading days for one ticker between ``start``
    and ``end`` from the strictly read-only
    :func:`price_cache.read_window_no_fetch` entry.  Returns the
    list of ISO-formatted dates that are already in the cache, in
    ascending order; an empty list signals nothing cached.

    Tests patch this seam directly so the suite never depends on
    ``price_cache.db`` contents.  The default path imports the cache
    module lazily so the script's module-level import stays narrow.
    """
    try:
        from price_cache import read_window_no_fetch  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — degrade quietly
        return []
    try:
        df = read_window_no_fetch(
            ticker, start=start, end=end, auto_adjust=False,
        )
    except Exception:  # noqa: BLE001 — degrade quietly
        return []
    if df is None or df.empty:
        return []
    dates: list[str] = []
    for row in df.itertuples(index=False):
        try:
            dates.append(str(row.date))
        except AttributeError:
            continue
    return sorted({d for d in dates if isinstance(d, str) and d})


def _fetch_ticker_rows_online(
    *, ticker: str, start: str, end: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch raw (auto_adjust=False) daily bars for ``ticker`` between
    ``start`` and ``end`` from the free ``yfinance`` provider.
    Returns ``(rows, errors)``.

    Lazy import — ``yfinance`` is pulled into ``sys.modules`` only
    when this function is actually called.  Tests MUST patch this
    seam so the no-paid import-isolation invariants hold even when
    ``--confirm-online`` is exercised.

    Each returned row carries
    ``(ticker, date, close, volume, auto_adjust, fetched_at)``.
    Bars the provider does not return are silently omitted — the
    caller compares the returned set against the requested window to
    surface gaps.  Prices are never fabricated.
    """
    try:
        import yfinance as yf  # noqa: PLC0415 — lazy by contract
    except ImportError as exc:
        return [], [
            f"yfinance unavailable; cannot perform online fetch: {exc}"
        ]

    try:
        start_d = _date.fromisoformat(start[:10])
        end_d   = _date.fromisoformat(end[:10])
    except (TypeError, ValueError) as exc:
        return [], [f"online fetch received non-ISO date for {ticker}: {exc}"]

    fetched_at = _now_iso_utc()
    try:
        history = yf.Ticker(ticker).history(
            start=start_d.isoformat(),
            # yfinance treats `end` as exclusive — add a day so the
            # requested upper bound is covered.
            end=(end_d + _timedelta(days=1)).isoformat(),
            auto_adjust=False,
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        return [], [
            f"yfinance fetch raised for {ticker}: "
            f"{type(exc).__name__}: {exc}"
        ]

    out: list[dict[str, Any]] = []
    for ts, row in history.iterrows():
        try:
            iso = ts.strftime("%Y-%m-%d")
        except AttributeError:
            iso = str(ts)[:10]
        close = row.get("Close")
        volume = row.get("Volume")
        try:
            close_f = float(close) if close is not None else None
            volume_f = float(volume) if volume is not None else None
        except (TypeError, ValueError):
            continue
        if close_f is None:
            continue
        out.append({
            "ticker":      ticker,
            "date":        iso,
            "close":       close_f,
            "volume":      volume_f if volume_f is not None else 0.0,
            "auto_adjust": 0,
            "fetched_at":  fetched_at,
        })
    return out, []


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_manual_five_event_cache_backfill_preview(
    *,
    confirm_online:     bool = False,
    input_csv:          str = _DEFAULT_INPUT_CSV,
    db_path:            str | None = None,
    pre_calendar_days:  int = _LOAD_PRE_CAL_DAYS,
    post_calendar_days: int = _LOAD_POST_CAL_DAYS,
    output_path:        str | None = None,
) -> dict[str, Any]:
    """Return the preview envelope for the 5-event cache backfill.

    See module docstring for the full output contract.
    """
    errors:          list[str] = []
    warnings:        list[str] = []
    blocked_reasons: list[str] = []

    # Live DB byte-identity is a hard invariant in both modes.  Hash
    # before anything else so we have a baseline even if a later step
    # raises.  ``_hash_file_safe`` returns None when the path is None
    # or does not exist; in that case live_db_unchanged is vacuously
    # true because there was nothing to mutate in the first place.
    live_path = _resolve_live_db_path(db_path)
    live_hash_before = _hash_file_safe(live_path)

    candidates, csv_warnings, csv_errors, rows_loaded = _load_candidates(
        input_csv=input_csv,
    )
    warnings.extend(csv_warnings)
    errors.extend(csv_errors)

    # Build the per-(ticker, candidate) window list once.  Both modes
    # need the windows; only the online mode iterates over them to
    # fetch.
    windows: list[dict[str, Any]] = []
    tickers: set[str] = set()
    for cand in candidates:
        anchor = cand["event_date"]
        try:
            anchor_d = _date.fromisoformat(anchor[:10])
        except (TypeError, ValueError):
            blocked_reasons.append(
                f"{cand['candidate_id']}: event_date {anchor!r} is not "
                f"ISO YYYY-MM-DD; window cannot be computed"
            )
            continue
        for col in ("primary_ticker", "benchmark_ticker"):
            ticker = cand.get(col) or ""
            if not ticker:
                blocked_reasons.append(
                    f"{cand['candidate_id']}: {col} is empty; ticker "
                    f"cannot be requested"
                )
                continue
            start = (anchor_d - _timedelta(days=pre_calendar_days)).isoformat()
            end   = (anchor_d + _timedelta(days=post_calendar_days)).isoformat()
            cached = _read_cached_window(
                ticker=ticker, start=start, end=end,
            )
            windows.append({
                "ticker":       ticker,
                "candidate_id": cand["candidate_id"],
                "event_date":   anchor,
                "start":        start,
                "end":          end,
                "cached_bars":  int(len(cached)),
                "fetched_bars": 0,
            })
            tickers.add(ticker)

    # Default mode: pure preview.  Hard-stop here without touching
    # any DB or the network.
    if not confirm_online:
        blocked_reasons.append(
            "default preview mode: --confirm-online was not supplied; "
            "no online fetch was attempted, no temp DB was created"
        )
        live_db_unchanged = _verify_live_db_unchanged(
            live_path=live_path,
            live_hash_before=live_hash_before,
            errors=errors,
        )
        recommended = (
            _RECOMMENDED_CSV_MISSING
            if any("input CSV" in e for e in errors)
            else _RECOMMENDED_PREVIEW_ONLY
        )
        return _finalize(
            envelope=_envelope(
                mode="preview",
                confirm_online=False,
                input_csv=input_csv,
                rows_loaded=rows_loaded,
                candidates=candidates,
                tickers=sorted(tickers),
                windows=windows,
                fetched_rows=0,
                inserted_temp_rows=0,
                temp_db_path=None,
                blocked_reasons=blocked_reasons,
                live_db_unchanged=live_db_unchanged,
                warnings=warnings,
                errors=errors,
                recommended_next_action=recommended,
            ),
            output_path=output_path,
        )

    # Online mode.  From here on we may call the patchable fetch seam,
    # but the live DB still must not be opened for writes.  Every
    # write target is the freshly created TEMP SQLite file.
    if not windows:
        live_db_unchanged = _verify_live_db_unchanged(
            live_path=live_path,
            live_hash_before=live_hash_before,
            errors=errors,
        )
        recommended = (
            _RECOMMENDED_CSV_MISSING
            if any("input CSV" in e for e in errors)
            else _RECOMMENDED_ONLINE_NO_ROWS
        )
        return _finalize(
            envelope=_envelope(
                mode="online",
                confirm_online=True,
                input_csv=input_csv,
                rows_loaded=rows_loaded,
                candidates=candidates,
                tickers=sorted(tickers),
                windows=windows,
                fetched_rows=0,
                inserted_temp_rows=0,
                temp_db_path=None,
                blocked_reasons=blocked_reasons,
                live_db_unchanged=live_db_unchanged,
                warnings=warnings,
                errors=errors,
                recommended_next_action=recommended,
            ),
            output_path=output_path,
        )

    temp_db_path: str | None = None
    try:
        temp_db_path = _create_temp_price_cache_db()
    except OSError as exc:
        errors.append(f"failed to create temp SQLite: {exc}")

    total_fetched = 0
    total_inserted = 0
    fetch_error_count = 0
    if temp_db_path is not None:
        for w in windows:
            ticker = w["ticker"]
            start  = w["start"]
            end    = w["end"]
            rows, fetch_errors = _fetch_ticker_rows_online(
                ticker=ticker, start=start, end=end,
            )
            for fe in fetch_errors or []:
                if isinstance(fe, str) and fe:
                    errors.append(f"fetch: {fe}")
                    fetch_error_count += 1
            row_count = len(rows) if isinstance(rows, list) else 0
            w["fetched_bars"] = int(row_count)
            total_fetched += row_count
            if row_count:
                try:
                    inserted = _insert_rows_into_temp_price_cache(
                        temp_db_path=temp_db_path, rows=rows,
                    )
                    total_inserted += inserted
                except sqlite3.Error as exc:
                    errors.append(
                        f"temp DB INSERT failed for {ticker}: {exc}"
                    )

    live_db_unchanged = _verify_live_db_unchanged(
        live_path=live_path,
        live_hash_before=live_hash_before,
        errors=errors,
    )

    recommended = _recommend_online(
        fetched=total_fetched,
        nt=len(tickers),
        temp_db_path=temp_db_path or "",
        fetch_error_count=fetch_error_count,
    )
    return _finalize(
        envelope=_envelope(
            mode="online",
            confirm_online=True,
            input_csv=input_csv,
            rows_loaded=rows_loaded,
            candidates=candidates,
            tickers=sorted(tickers),
            windows=windows,
            fetched_rows=total_fetched,
            inserted_temp_rows=total_inserted,
            temp_db_path=temp_db_path,
            blocked_reasons=blocked_reasons,
            live_db_unchanged=live_db_unchanged,
            warnings=warnings,
            errors=errors,
            recommended_next_action=recommended,
        ),
        output_path=output_path,
    )


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------


def _load_candidates(
    *, input_csv: str,
) -> tuple[list[dict[str, Any]], list[str], list[str], int]:
    warnings: list[str] = []
    errors:   list[str] = []
    csv_path = Path(input_csv)
    if not csv_path.is_file():
        errors.append(
            f"input CSV missing: {input_csv!r}; the preview requires "
            f"the operator-curated batch CSV on disk"
        )
        return [], warnings, errors, 0
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            raw_rows = list(reader)
    except (OSError, csv.Error) as exc:
        errors.append(
            f"failed to read input CSV {input_csv!r}: "
            f"{type(exc).__name__}: {exc}"
        )
        return [], warnings, errors, 0

    candidates: list[dict[str, Any]] = []
    for row_index, raw in enumerate(raw_rows):
        candidates.append({
            "candidate_id":     f"{_CANDIDATE_PREFIX}{row_index + 1:03d}",
            "row_index":        int(row_index),
            "event_date":       (raw.get("event_date") or "").strip(),
            "headline":         (raw.get("headline") or "").strip(),
            "mechanism_family": (raw.get("mechanism_family") or "").strip(),
            "primary_ticker":   (raw.get("primary_ticker") or "").strip().upper(),
            "benchmark_ticker": (raw.get("benchmark_ticker") or "").strip().upper(),
        })
    return candidates, warnings, errors, len(raw_rows)


# ---------------------------------------------------------------------------
# Temp SQLite plumbing
# ---------------------------------------------------------------------------


def _create_temp_price_cache_db() -> str:
    """Create a brand-new SQLite file under :func:`tempfile.gettempdir`
    with just the ``price_cache`` table.  Returns the absolute path.
    The caller is responsible for cleaning up the file when done; the
    preview surfaces the path via ``temp_db_path`` so the operator can
    inspect the staged rows.
    """
    path = Path(tempfile.gettempdir()) / (
        f"five_event_preview_temp_{uuid.uuid4().hex}.db"
    )
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_PRICE_CACHE_DDL)
        conn.commit()
    finally:
        conn.close()
    return str(path)


def _insert_rows_into_temp_price_cache(
    *, temp_db_path: str, rows: Sequence[dict[str, Any]],
) -> int:
    """``INSERT OR IGNORE`` each row into the temp DB's price_cache
    table.  Returns the count of rows actually inserted (duplicates
    against the PRIMARY KEY skip silently so reruns stay idempotent).
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
                auto_adjust = 0
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


def _now_iso_utc() -> str:
    from datetime import datetime, timezone  # noqa: PLC0415
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_live_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    # Best-effort lookup of the canonical events.db path.  We import
    # ``db`` lazily so the module load remains light; the module is
    # pure-Python stdlib + sqlite3 and does not bring in any provider
    # or FastAPI surface.
    try:
        import db as _db  # noqa: PLC0415
    except Exception:  # noqa: BLE001
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


def _verify_live_db_unchanged(
    *,
    live_path:        str | None,
    live_hash_before: str | None,
    errors:           list[str],
) -> bool:
    """Re-hash the live DB and surface a hard error if its bytes have
    changed.  Returns the boolean for the envelope's
    ``live_db_unchanged`` field.

    Vacuously True when the live DB path is None or did not exist
    when the run began — the script had nothing to mutate.
    """
    if live_path is None or live_hash_before is None:
        return True
    after = _hash_file_safe(live_path)
    if after is None:
        # File disappeared during the run — that itself is a mutation.
        errors.append(
            f"LIVE DB FILE NO LONGER PRESENT after preview run: "
            f"{live_path}"
        )
        return False
    if after != live_hash_before:
        errors.append(
            f"LIVE DB BYTES CHANGED during preview run — investigate: "
            f"{live_path}"
        )
        return False
    return True


def _recommend_online(
    *,
    fetched:           int,
    nt:                int,
    temp_db_path:      str,
    fetch_error_count: int,
) -> str:
    if fetched <= 0:
        return _RECOMMENDED_ONLINE_NO_ROWS
    if fetch_error_count:
        return _RECOMMENDED_ONLINE_PARTIAL.format(
            err_count=fetch_error_count,
            fetched=fetched,
            temp_db_path=temp_db_path or "(temp DB path unavailable)",
        )
    return _RECOMMENDED_ONLINE_OK.format(
        fetched=fetched,
        nt=nt,
        temp_db_path=temp_db_path or "(temp DB path unavailable)",
    )


# ---------------------------------------------------------------------------
# Envelope + finalize
# ---------------------------------------------------------------------------


def _envelope(
    *,
    mode:                   str,
    confirm_online:         bool,
    input_csv:              str,
    rows_loaded:            int,
    candidates:             list[dict[str, Any]],
    tickers:                list[str],
    windows:                list[dict[str, Any]],
    fetched_rows:           int,
    inserted_temp_rows:     int,
    temp_db_path:           str | None,
    blocked_reasons:        list[str],
    live_db_unchanged:      bool,
    warnings:               list[str],
    errors:                 list[str],
    recommended_next_action: str,
) -> dict[str, Any]:
    return {
        "ok":                       not errors,
        "mode":                     str(mode),
        "confirm_online":           bool(confirm_online),
        "input_csv":                str(input_csv),
        "rows_loaded":              int(rows_loaded),
        "candidates":               list(candidates),
        "tickers":                  list(tickers),
        "windows":                  list(windows),
        "fetched_rows":             int(fetched_rows),
        "inserted_temp_rows":       int(inserted_temp_rows),
        "temp_db_path":             temp_db_path,
        "blocked_reasons":          list(blocked_reasons),
        "live_db_unchanged":        bool(live_db_unchanged),
        "warnings":                 list(warnings),
        "errors":                   list(errors),
        "recommended_next_action":  str(recommended_next_action),
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


def _render_json(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Online preview for the 5-event historical cache backfill. "
            " Default mode is zero-network and read-only: reports the "
            "(ticker, window) plan plus cached coverage.  "
            "--confirm-online authorises a single yfinance fetch per "
            "ticker/window into a TEMP SQLite file; the live cache is "
            "never opened for writes in either mode.  Conservative "
            "wording — the preview reports cache geometry, not market "
            "evidence."
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
            "Authorise a single online fetch per ticker/window via the "
            "free yfinance provider into a TEMP SQLite file.  Without "
            "this flag the preview never calls a provider and never "
            "creates a temp file."
        ),
    )
    parser.add_argument(
        "--input-csv", dest="input_csv", default=_DEFAULT_INPUT_CSV,
        help=(
            "Path to the operator-curated batch CSV.  Defaults to "
            f"{_DEFAULT_INPUT_CSV!r}.  Read-only."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the live events DB.  Defaults to "
            "``db.DB_FILE``.  Read-only — hashed before and after the "
            "run to surface ``live_db_unchanged``."
        ),
    )
    parser.add_argument(
        "--pre-calendar-days", dest="pre_calendar_days",
        type=int, default=_LOAD_PRE_CAL_DAYS,
        help=(
            "Calendar-day padding before each event_date when "
            "requesting a window "
            f"(default {_LOAD_PRE_CAL_DAYS})."
        ),
    )
    parser.add_argument(
        "--post-calendar-days", dest="post_calendar_days",
        type=int, default=_LOAD_POST_CAL_DAYS,
        help=(
            "Calendar-day padding after each event_date when "
            "requesting a window "
            f"(default {_LOAD_POST_CAL_DAYS})."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope.  Omitted by "
            "default — the preview has no filesystem side effect "
            "outside the retained temp DB copy."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    envelope = run_manual_five_event_cache_backfill_preview(
        confirm_online=bool(args.confirm_online),
        input_csv=args.input_csv,
        db_path=args.db_path,
        pre_calendar_days=int(args.pre_calendar_days),
        post_calendar_days=int(args.post_calendar_days),
        output_path=args.output_path,
    )
    print(_render_json(envelope), file=output)
    return 0 if envelope.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_manual_five_event_cache_backfill_preview",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
