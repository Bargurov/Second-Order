"""Topic-balance audit — deterministic report over recent + surfaced headlines.

Run examples
------------

    # Dry audit over the last 200 stored headlines, surfaced = cluster
    # representatives from news_cluster_store (default).
    python tools/topic_balance_validation.py

    # Audit a snapshot JSON file instead of the live archive.
    python tools/topic_balance_validation.py --from-json scripts/headline_snapshot.json

    # Write the markdown report to disk for review.
    python tools/topic_balance_validation.py --out TOPIC_BALANCE_REPORT.md

    # Cap the recent-headline sample (useful on large archives).
    python tools/topic_balance_validation.py --recent-limit 500

See ``topic_balance.py`` for the composer contract and
``TOPIC_BALANCE_REVIEW.md`` for the review checklist.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from topic_balance import (   # noqa: E402
    compute_topic_balance,
    format_topic_balance_report,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Topic-balance audit over recent + surfaced headlines.",
    )
    p.add_argument(
        "--from-json", default=None,
        help="Read headlines from a JSON file instead of the archive. "
             "File shape: {'recent': [...], 'surfaced': [...]}.",
    )
    p.add_argument(
        "--recent-limit", type=int, default=500,
        help="Cap on recent headlines loaded from the archive.",
    )
    p.add_argument(
        "--surfaced-limit", type=int, default=60,
        help="Cap on surfaced cluster representatives.",
    )
    p.add_argument(
        "--out", default=None,
        help="Write the markdown report to this path (stdout always gets it).",
    )
    p.add_argument(
        "--json-out", default=None,
        help="Write the full structured report to this JSON path.",
    )
    return p.parse_args(argv)


def _load_from_json(path: str) -> tuple[list, list]:
    body = json.loads(Path(path).read_text(encoding="utf-8"))
    recent = body.get("recent") or body.get("headlines") or []
    surfaced = body.get("surfaced") or []
    return recent, surfaced


def _load_from_archive(
    recent_limit: int, surfaced_limit: int,
) -> tuple[list, list]:
    """Best-effort loader: tries news_cluster_store, falls back to DB rows."""
    try:
        from news_cluster_store import (
            list_recent_headlines,
            list_recent_clusters,
        )
        recent = list_recent_headlines(limit=recent_limit) or []
        clusters = list_recent_clusters(limit=surfaced_limit) or []
        # Cluster representatives are the "surfaced" stream.  Shape
        # varies; coerce to {title} dicts.
        surfaced: list[dict] = []
        for c in clusters:
            if not isinstance(c, dict):
                continue
            title = (
                c.get("representative_title")
                or c.get("title")
                or c.get("headline")
            )
            if isinstance(title, str) and title.strip():
                surfaced.append({"title": title})
        return recent, surfaced
    except Exception as exc:   # noqa: BLE001
        print(
            f"[topic_balance_validation] archive loader failed ({exc}); "
            "returning empty streams.  Pass --from-json to audit a snapshot.",
            file=sys.stderr,
        )
        return [], []


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])

    if args.from_json:
        recent, surfaced = _load_from_json(args.from_json)
    else:
        recent, surfaced = _load_from_archive(
            args.recent_limit, args.surfaced_limit,
        )

    report = compute_topic_balance(
        recent,
        surfaced_headlines=surfaced if surfaced else None,
    )
    md = format_topic_balance_report(report)
    print(md)

    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(
            f"[topic_balance_validation] markdown written to {args.out}",
            file=sys.stderr,
        )
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )
        print(
            f"[topic_balance_validation] json written to {args.json_out}",
            file=sys.stderr,
        )

    # Exit code signals whether a large bias or very-concentrated band
    # was surfaced — helpful in CI / cron scripts.
    flags = report.get("bias_flags") or []
    large = sum(1 for f in flags if f.get("severity") == "large")
    recent_band = (
        (report.get("recent") or {}).get("sector_mix", {}).get("band")
    )
    surfaced_band = (
        (report.get("surfaced") or {}).get("sector_mix", {}).get("band")
        if report.get("surfaced") else None
    )
    if large > 0 or surfaced_band == "very_concentrated" or recent_band == "very_concentrated":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
