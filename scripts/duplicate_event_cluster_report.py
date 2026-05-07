#!/usr/bin/env python3
"""Read-only duplicate ``(headline, event_date)`` cluster report.

Identifies events archive rows that share both a non-empty ``headline``
and a non-empty ``event_date`` — the operator-facing definition of a
duplicate cluster.  Rows whose ``headline`` is NULL/empty OR whose
``event_date`` is NULL/empty are excluded entirely.  An ``event_date``
that does not parse as ISO ``YYYY-MM-DD`` is *still grouped* as long
as it is non-empty: the canonical archive carries operator-curated
``event_date`` strings, and the duplicate signal we want to surface is
"two rows agreed on the same value", not "two rows agreed on a value
this script could re-parse".

Output contract::

    {
      "total_clusters":          int,   # distinct (headline, event_date) pairs with count >= 2
      "total_rows_in_clusters":  int,   # sum of counts across every cluster
      "largest_cluster_size":    int,   # max count across clusters (0 when none)
      "clusters": [                     # capped at --limit, ordered by
                                        # count desc, headline asc, event_date asc,
                                        # min(id) asc
        {
          "headline":   str,
          "event_date": str,
          "count":      int,
          "event_ids":  list[int],      # ascending
        },
        ...
      ],
      "recommended_next_action": str,
    }

Out of scope (deliberately)
---------------------------
* Read-only.  The script issues only ``SELECT`` statements; the
  connection is opened against the configured SQLite file and never
  touches the events row schema.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache``, no provider call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.

Usage::

    python scripts/duplicate_event_cluster_report.py
    python scripts/duplicate_event_cluster_report.py --json
    python scripts/duplicate_event_cluster_report.py --json --limit 5
    python scripts/duplicate_event_cluster_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT = 25


_RECOMMENDED_OK = (
    "No duplicate (headline, event_date) clusters detected — the "
    "events archive is clean."
)
_RECOMMENDED_DUPES = (
    "Duplicate (headline, event_date) clusters detected — review the "
    "listed event_ids and decide whether to deduplicate via the "
    "archive cleanup tool before running downstream analytics."
)


# ---------------------------------------------------------------------------
# Pure SQL probe
# ---------------------------------------------------------------------------


def find_duplicate_clusters(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return the duplicate-cluster report dict.

    Parameters
    ----------
    db_path
        Optional path to a SQLite ``events.db`` file.  When omitted,
        reads ``db.DB_FILE`` so the report aligns with whichever DB
        the caller's process is bound to.
    limit
        Maximum number of cluster entries surfaced under
        ``clusters``.  The aggregate counts (``total_clusters``,
        ``total_rows_in_clusters``, ``largest_cluster_size``) always
        reflect the full clustering — only the listed examples are
        truncated.  Negative values are clamped to ``0``.
    """
    capped_limit = max(int(limit), 0)
    empty: dict[str, Any] = {
        "total_clusters":          0,
        "total_rows_in_clusters":  0,
        "largest_cluster_size":    0,
        "clusters":                [],
        "recommended_next_action": _RECOMMENDED_OK,
    }

    path = _resolve_db_path(db_path)
    if path is None:
        return empty

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return empty

    try:
        try:
            rows = conn.execute(
                "SELECT headline, event_date, COUNT(*) AS cluster_count, "
                "       GROUP_CONCAT(id, ',') AS event_ids "
                "FROM events "
                "WHERE headline IS NOT NULL AND headline != '' "
                "  AND event_date IS NOT NULL AND event_date != '' "
                "GROUP BY headline, event_date "
                "HAVING COUNT(*) > 1 "
                "ORDER BY cluster_count DESC, headline ASC, "
                "         event_date ASC, MIN(id) ASC"
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        conn.close()

    total_clusters        = 0
    total_rows_in_clusters = 0
    largest_cluster_size  = 0
    clusters: list[dict[str, Any]] = []

    for headline, event_date, cluster_count, event_ids_blob in rows:
        total_clusters += 1
        cluster_count_int = int(cluster_count or 0)
        total_rows_in_clusters += cluster_count_int
        if cluster_count_int > largest_cluster_size:
            largest_cluster_size = cluster_count_int

        if len(clusters) < capped_limit:
            clusters.append({
                "headline":   headline if isinstance(headline, str) else "",
                "event_date": event_date if isinstance(event_date, str) else "",
                "count":      cluster_count_int,
                "event_ids":  _parse_event_ids(event_ids_blob),
            })

    return {
        "total_clusters":          total_clusters,
        "total_rows_in_clusters":  total_rows_in_clusters,
        "largest_cluster_size":    largest_cluster_size,
        "clusters":                clusters,
        "recommended_next_action": (
            _RECOMMENDED_OK if total_clusters == 0 else _RECOMMENDED_DUPES
        ),
    }


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


def _parse_event_ids(blob: Any) -> list[int]:
    if not isinstance(blob, str) or not blob:
        return []
    out: list[int] = []
    for chunk in blob.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except ValueError:
            continue
    out.sort()
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Duplicate (headline, event_date) cluster report", ""]
    lines.append(f"Total clusters:          {report['total_clusters']}")
    lines.append(f"Total rows in clusters:  {report['total_rows_in_clusters']}")
    lines.append(f"Largest cluster size:    {report['largest_cluster_size']}")
    lines.append("")

    clusters = report["clusters"]
    lines.append(f"Clusters listed ({len(clusters)}):")
    if clusters:
        for index, cluster in enumerate(clusters, start=1):
            ids = cluster.get("event_ids") or []
            ids_str = ",".join(str(eid) for eid in ids)
            lines.append(
                f"  {index:>2}. count={cluster.get('count')} "
                f"event_date={cluster.get('event_date') or '-'} "
                f"ids=[{ids_str}]"
            )
            lines.append(f"      {cluster.get('headline') or ''}")
    else:
        lines.append("  -")
    lines.append("")
    lines.append(f"Recommended next action: {report['recommended_next_action']}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only report on duplicate (headline, event_date) "
            "clusters in the events archive.  Issues only SELECT "
            "statements; never imports a provider, yfinance, the LLM, "
            "or the FastAPI app."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced cluster list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect the "
            f"full clustering."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the report follows the project's "
            "configured archive."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = find_duplicate_clusters(
        db_path=args.db_path, limit=args.limit,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
