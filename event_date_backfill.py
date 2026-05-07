"""Dry-run planner and guarded writer for missing ``event_date`` values.

The dry-run planner (:func:`plan_event_date_backfill`) reads the local
SQLite ``events`` table, identifies rows whose ``event_date`` is NULL
or empty while ``timestamp`` is non-empty, and proposes
``timestamp[:10]`` as the same-day backfill candidate.  Pure read —
issues only ``SELECT`` statements.

The writer (:func:`apply_event_date_backfill`) requires the explicit
``confirm=True`` keyword.  Without it the call returns the plan and
writes nothing.  The write path issues a single ``BEGIN IMMEDIATE``
transaction that serialises against any concurrent uvicorn writer on
the same SQLite file, then a guarded
``UPDATE events SET event_date = ? WHERE id = ? AND
(event_date IS NULL OR event_date = '')`` per proposal — so already
dated rows can never be re-dated even if a stale plan is replayed.
A second ``apply_event_date_backfill(confirm=True)`` on the same DB
performs zero writes because the planner returns no candidates.

Neither path imports ``price_cache`` / ``market_data`` /
``market_check`` (so the ``_purge_corrupt_rows`` write path can never
be triggered as a side effect), touches ``yfinance``, calls the LLM,
or exposes a FastAPI route surface.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any


SKIP_TIMESTAMP_UNPARSEABLE = "timestamp_unparseable"

SKIP_COUNT_KEYS = (
    SKIP_TIMESTAMP_UNPARSEABLE,
)

CONFIDENCE_NOTE = (
    "Same-day proxy: events without an event_date are backfilled from "
    "the headline timestamp's calendar date (timestamp[:10]). Confidence "
    "is highest for headlines that report a same-day event and lowest "
    "for headlines reporting a prior-day event or pre-/post-market "
    "moves; verify before persisting."
)


def plan_event_date_backfill(*, db_path: str | None = None) -> dict[str, Any]:
    """Return a deterministic dry-run event_date backfill plan.

    Parameters
    ----------
    db_path
        Optional path to a SQLite ``events.db`` file.  When omitted,
        reads ``db.DB_FILE`` so the planner aligns with whichever DB
        the caller's process is bound to.

    Returns
    -------
    dict with keys:

      * ``total_candidates``           — events whose ``event_date`` is
        NULL or '' AND whose ``timestamp`` is non-empty.
      * ``events_with_market_tickers`` — subset of the above with at
        least one parseable ticker symbol.
      * ``ticker_rows_blocked``        — total distinct ticker symbols
        across qualifying events; the per-ticker hydration rows the
        absent ``event_date`` is currently blocking.  Counts every
        candidate's tickers, including rows whose timestamp does not
        parse — the absent ``event_date`` blocks hydration regardless
        of whether this planner can resolve the date.
      * ``proposed_updates``           — list of update proposals
        ordered by ``id`` ascending.  Each entry carries ``event_id``,
        ``headline``, ``timestamp``, ``proposed_event_date``,
        ``ticker_count``, ``tickers`` (sorted symbol list) and
        ``projected_tickers_unblocked`` (count of distinct
        market_tickers on this event that would move out of the
        no_event_date hydration blocker once the proposed date is
        persisted).  Rows whose timestamp does not parse are excluded.
      * ``skipped_counts``             — dict of skip-reason → count.
        Currently:
          * ``timestamp_unparseable``  — timestamp does not parse as
            ISO ``YYYY-MM-DD``.
      * ``projected_hydration_impact`` — aggregate dry-run projection
        of the impact a write of every proposed update would have on
        the per-ticker hydration backlog.  Carries:
          * ``candidate_events``                — mirrors
            ``total_candidates``.
          * ``proposed_updates_count``          — ``len(proposed_updates)``.
          * ``ticker_rows_blocked``             — mirrors top-level
            ``ticker_rows_blocked``.
          * ``ticker_rows_unblocked_by_write``  — sum of
            ``projected_tickers_unblocked`` across proposals; rows that
            would be unblocked once every proposal is persisted.
          * ``remaining_ticker_rows_blocked``   — rows that stay
            blocked because their candidate event's timestamp did not
            parse.  Equals ``ticker_rows_blocked
            - ticker_rows_unblocked_by_write`` by construction.
          * ``skipped_counts``                  — mirrors top-level
            ``skipped_counts``.
      * ``confidence_note``            — fixed string describing the
        heuristic and its degradation modes.
    """
    import db as _db

    path = db_path if db_path is not None else _db.DB_FILE

    skipped_counts: dict[str, int] = {key: 0 for key in SKIP_COUNT_KEYS}
    empty: dict[str, Any] = {
        "total_candidates":           0,
        "events_with_market_tickers": 0,
        "ticker_rows_blocked":        0,
        "proposed_updates":           [],
        "skipped_counts":             dict(skipped_counts),
        "projected_hydration_impact": _compose_impact(
            candidate_events=0,
            proposed_updates_count=0,
            ticker_rows_blocked=0,
            ticker_rows_unblocked_by_write=0,
            skipped_counts=skipped_counts,
        ),
        "confidence_note":            CONFIDENCE_NOTE,
    }

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return empty

    try:
        try:
            rows = conn.execute(
                "SELECT id, headline, timestamp, market_tickers "
                "FROM events "
                "WHERE (event_date IS NULL OR event_date = '') "
                "  AND timestamp IS NOT NULL "
                "  AND timestamp != '' "
                "ORDER BY id ASC"
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        conn.close()

    total_candidates = 0
    events_with_tickers = 0
    ticker_rows_blocked = 0
    proposed_updates: list[dict[str, Any]] = []

    for event_id, headline, timestamp, market_tickers_blob in rows:
        total_candidates += 1
        symbols = _db._ticker_symbols(market_tickers_blob)
        symbol_count = len(symbols)
        if symbol_count > 0:
            events_with_tickers += 1
            ticker_rows_blocked += symbol_count

        proposed = _parse_proposed_event_date(timestamp)
        if proposed is None:
            skipped_counts[SKIP_TIMESTAMP_UNPARSEABLE] += 1
            continue

        proposed_updates.append({
            "event_id":                    event_id,
            "headline":                    headline if isinstance(headline, str) else "",
            "timestamp":                   timestamp if isinstance(timestamp, str) else None,
            "proposed_event_date":         proposed,
            "ticker_count":                symbol_count,
            "tickers":                     sorted(symbols),
            "projected_tickers_unblocked": symbol_count,
        })

    ticker_rows_unblocked_by_write = sum(
        p["projected_tickers_unblocked"] for p in proposed_updates
    )

    return {
        "total_candidates":           total_candidates,
        "events_with_market_tickers": events_with_tickers,
        "ticker_rows_blocked":        ticker_rows_blocked,
        "proposed_updates":           proposed_updates,
        "skipped_counts":             skipped_counts,
        "projected_hydration_impact": _compose_impact(
            candidate_events=total_candidates,
            proposed_updates_count=len(proposed_updates),
            ticker_rows_blocked=ticker_rows_blocked,
            ticker_rows_unblocked_by_write=ticker_rows_unblocked_by_write,
            skipped_counts=skipped_counts,
        ),
        "confidence_note":            CONFIDENCE_NOTE,
    }


def _compose_impact(
    *,
    candidate_events: int,
    proposed_updates_count: int,
    ticker_rows_blocked: int,
    ticker_rows_unblocked_by_write: int,
    skipped_counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "candidate_events":               candidate_events,
        "proposed_updates_count":         proposed_updates_count,
        "ticker_rows_blocked":            ticker_rows_blocked,
        "ticker_rows_unblocked_by_write": ticker_rows_unblocked_by_write,
        "remaining_ticker_rows_blocked":
            ticker_rows_blocked - ticker_rows_unblocked_by_write,
        "skipped_counts":                 dict(skipped_counts),
    }


def _parse_proposed_event_date(timestamp: Any) -> str | None:
    if not (isinstance(timestamp, str) and len(timestamp) >= 10):
        return None
    try:
        return date.fromisoformat(timestamp[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def apply_event_date_backfill(
    *, db_path: str | None = None, confirm: bool = False,
) -> dict[str, Any]:
    """Apply the dry-run plan when ``confirm=True``; otherwise no-op.

    Parameters
    ----------
    db_path
        Optional SQLite file path.  Defaults to ``db.DB_FILE``.
    confirm
        Hard gate.  When ``False`` the function delegates to the
        planner, returns the dry-run shape with ``applied_count = 0``
        and ``applied_updates = []``, and writes nothing.

    Returns
    -------
    dict
        Carries every field from :func:`plan_event_date_backfill` plus:

          * ``applied_count``    — number of rows whose ``event_date``
            transitioned from NULL/empty to ``timestamp[:10]``.
          * ``applied_updates``  — list of ``{event_id, timestamp,
            proposed_event_date}`` ordered by ``event_id`` ascending,
            mirroring the planner's proposal order.

    Safety contract (see ``docs/event_date_backfill_write_design.md``)
    --------------------------------------------------------------------
    * Only NULL / empty ``event_date`` rows are touched — the per-row
      ``UPDATE`` carries ``WHERE id = ? AND (event_date IS NULL OR
      event_date = '')`` so a stale plan cannot re-date a row that was
      filled in between the planner read and the write.
    * Malformed timestamps are skipped and surfaced in
      ``skipped_counts.timestamp_unparseable`` (inherited from the
      planner — they never make it onto ``proposed_updates``).
    * Idempotent: a second call on the same DB writes nothing because
      the planner returns zero proposals after the first run.
    * Concurrency: the write path opens the connection in autocommit
      mode and issues an explicit ``BEGIN IMMEDIATE`` so a concurrent
      uvicorn writer on the same SQLite file serialises on the lock.
    * No paid surfaces: never imports ``market_check`` / ``market_data``
      / ``price_cache``, never touches ``yfinance``, never calls the
      LLM, exposes no FastAPI route.
    """
    plan = plan_event_date_backfill(db_path=db_path)

    if not confirm:
        return {
            **plan,
            "applied_count":   0,
            "applied_updates": [],
        }

    proposals = plan.get("proposed_updates") or []
    if not proposals:
        return {
            **plan,
            "applied_count":   0,
            "applied_updates": [],
        }

    import db as _db

    path = db_path if db_path is not None else _db.DB_FILE

    applied: list[dict[str, Any]] = []

    # ``isolation_level=None`` puts the driver in autocommit mode so we
    # can issue an explicit ``BEGIN IMMEDIATE`` — Python's default
    # deferred transaction would only escalate to RESERVED on the first
    # write statement, which is too late for serialising against a
    # concurrent uvicorn writer that may already hold a deferred read.
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for proposal in proposals:
                event_id = proposal.get("event_id")
                proposed = proposal.get("proposed_event_date")
                if event_id is None or not isinstance(proposed, str):
                    continue
                cur = conn.execute(
                    "UPDATE events SET event_date = ? "
                    "WHERE id = ? AND (event_date IS NULL OR event_date = '')",
                    (proposed, event_id),
                )
                if cur.rowcount > 0:
                    applied.append({
                        "event_id":            event_id,
                        "timestamp":           proposal.get("timestamp"),
                        "proposed_event_date": proposed,
                    })
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    return {
        **plan,
        "applied_count":   len(applied),
        "applied_updates": applied,
    }
