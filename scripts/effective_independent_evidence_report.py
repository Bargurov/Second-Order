"""
scripts/effective_independent_evidence_report.py

K2 — effective independent evidence: market-story clusters over the
accepted track-record corpus.

The reviewer question this answers: the archive carries 86 accepted
track-record rows — how many distinct market stories does that actually
represent?  Rows are grouped into descriptive "market-story clusters"
with three transparent rules (shared event date; shared primary ticker
inside the 20-day reaction window; explicit duplicate links from the
event-date-quality layer).  The cluster count is an independence-caution
reading aid for the nominal row count.

This is a descriptive grouping, not inference: it adds no p-value, no FDR
pool, no score, no rank, and no inferential effective sample size.  It is
not a trading surface of any kind.

Read-only: opens the archive via SQLite ``mode=ro`` layers it reuses and
writes nothing.  No provider, no network, no paid call.

Reproduce:
    python scripts/effective_independent_evidence_report.py --db-path events.db
    python scripts/effective_independent_evidence_report.py --db-path events.db --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.accepted_family_overlay_report import classify_headline  # noqa: E402
from scripts.event_date_quality_report import (  # noqa: E402
    _primary_ticker,
    build_report as _edq_build_report,
)
from scripts.event_study_coverage_report import (  # noqa: E402
    summarize_event_study_coverage,
)
from scripts.representative_case_expansion_report import (  # noqa: E402
    build_report as _f1_build_report,
)
from scripts.track_record_sensitivity_report import (  # noqa: E402
    _load_accepted_records,
)
from stats.track_record_scoring import score_event_under_rule  # noqa: E402

DEFAULT_DB = str(_ROOT / "events.db")
WINDOW_DAYS = 20
LARGEST_CLUSTERS_SHOWN = 8

_OUTCOME_DISPLAY = {
    "validated": "support",
    "contradicted": "contradiction",
    "unresolved": "unresolved",
}

_MISSING_READOUT_IDS = [153, 154, 160]

_DUP_IDS_RE = re.compile(r"\[([0-9,\s]*)\]")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _parse_iso(value: Any) -> Optional[_date]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _parse_duplicate_ids(thread_independence: Any) -> list[int]:
    """Extract linked row ids from the C4 ``thread_independence`` field.

    The event-date-quality layer records duplicate collisions as e.g.
    ``"duplicate_of_rows: [41]"``; anything without a bracketed id list
    yields no links.
    """
    if not isinstance(thread_independence, str):
        return []
    m = _DUP_IDS_RE.search(thread_independence)
    if not m:
        return []
    inner = m.group(1).strip()
    if not inner:
        return []
    out: list[int] = []
    for part in inner.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return sorted(set(out))


class _UnionFind:
    def __init__(self, ids: Iterable[int]):
        self._parent = {i: i for i in ids}

    def find(self, i: int) -> int:
        parent = self._parent
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:
            parent[i], i = root, parent[i]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Deterministic: smaller root wins.
            lo, hi = (ra, rb) if ra < rb else (rb, ra)
            self._parent[hi] = lo


def build_clusters(rows: list[dict], window_days: int = WINDOW_DAYS) -> list[dict]:
    """Group rows into descriptive market-story clusters.

    Two rows share a cluster when any of these transparent rules links
    them (directly or through a chain):

    * same event date — their reaction windows are the same tape day;
    * same primary ticker with event dates within ``window_days``
      calendar days — the same price series read over overlapping
      windows;
    * an explicit duplicate link recorded by the event-date-quality
      layer.

    Descriptive grouping only — no inference, no weighting, no score.
    Returns clusters ordered by size (largest first), then by smallest
    member id; cluster ids ``c01``, ``c02``, ... follow that order.
    """
    ids = [r["event_id"] for r in rows]
    uf = _UnionFind(ids)
    by_id = {r["event_id"]: r for r in rows}

    # Rule 1 — same event date.
    by_date: dict[str, list[int]] = {}
    for r in rows:
        d = r.get("date")
        if isinstance(d, str) and d:
            by_date.setdefault(d, []).append(r["event_id"])
    for members in by_date.values():
        members.sort()
        for a, b in zip(members, members[1:]):
            uf.union(a, b)

    # Rule 2 — same primary ticker within the reaction window.
    with_ticker = [
        (r["primary_ticker"], _parse_iso(r.get("date")), r["event_id"])
        for r in rows
        if r.get("primary_ticker") and _parse_iso(r.get("date")) is not None
    ]
    with_ticker.sort(key=lambda t: (t[0], t[1], t[2]))
    for (tk1, d1, id1), (tk2, d2, id2) in zip(with_ticker, with_ticker[1:]):
        if tk1 == tk2 and (d2 - d1).days <= window_days:
            uf.union(id1, id2)

    # Rule 3 — explicit duplicate links from the event-date-quality layer.
    for r in rows:
        for linked in r.get("duplicate_of") or []:
            if linked in by_id:
                uf.union(r["event_id"], linked)

    groups: dict[int, list[int]] = {}
    for i in sorted(ids):
        groups.setdefault(uf.find(i), []).append(i)

    clusters: list[dict] = []
    for members in groups.values():
        members.sort()
        dates = sorted(
            d for d in (by_id[m].get("date") for m in members)
            if isinstance(d, str) and d
        )
        tickers = sorted(
            {by_id[m]["primary_ticker"] for m in members
             if by_id[m].get("primary_ticker")}
        )
        clusters.append({
            "event_ids": members,
            "size": len(members),
            "date_min": dates[0] if dates else None,
            "date_max": dates[-1] if dates else None,
            "primary_tickers": tickers,
        })
    clusters.sort(key=lambda c: (-c["size"], c["event_ids"][0]))
    for idx, c in enumerate(clusters):
        c["cluster_id"] = f"c{idx + 1:02d}"
        if c["date_min"] is None:
            span = "undated"
        elif c["date_min"] == c["date_max"]:
            span = c["date_min"]
        else:
            span = f"{c['date_min']} .. {c['date_max']}"
        dom = c["primary_tickers"][0] if len(c["primary_tickers"]) == 1 else (
            "mixed tickers" if c["primary_tickers"] else "no primary ticker")
        c["label"] = f"{span} / {dom}"
    return clusters


def max_non_overlapping_windows(dates: list[str], horizon_days: int) -> int:
    """Largest set of mutually non-overlapping ``[date, date+horizon)``
    windows (greedy earliest-finish interval scheduling).

    An upper-bound independence caution in the C1 house convention — it
    is not an inferential effective sample size.
    """
    parsed = sorted(
        d for d in (_parse_iso(v) for v in dates) if d is not None
    )
    count = 0
    current_end: Optional[_date] = None
    for d in parsed:
        if current_end is None or d >= current_end:
            count += 1
            current_end = d + _timedelta(days=horizon_days)
    return count


def _pct(count: int, denom: int) -> float:
    if not denom:
        return 0.0
    return round(100.0 * count / denom, 1)


# ---------------------------------------------------------------------------
# Report assembly (read-only)
# ---------------------------------------------------------------------------

def _assemble_rows(db_path: str) -> tuple[list[dict], dict, dict]:
    edq = _edq_build_report(db_path=db_path)
    accepted = [e for e in edq.get("events", [])
                if e.get("corpus_status") == "accepted"]

    records, _meta = _load_accepted_records(db_path)
    tickers_by_id = {r["event_id"]: r.get("tickers") or [] for r in records}
    outcome_by_id = {
        r["event_id"]: score_event_under_rule(r.get("tickers") or [],
                                              "any_support")
        for r in records
    }

    coverage = summarize_event_study_coverage(db_path=db_path, limit=100000)
    es_ids = {e.get("event_id") for e in coverage.get("available", [])}

    rows: list[dict] = []
    for e in accepted:
        eid = e["event_id"]
        fams = classify_headline(e.get("headline"))
        if len(fams) == 1:
            family_lens = fams[0]
        elif fams:
            family_lens = "multi_match"
        else:
            family_lens = "unclassified"
        rows.append({
            "event_id": eid,
            "date": e.get("date"),
            "primary_ticker": _primary_ticker(tickers_by_id.get(eid)),
            "duplicate_of": _parse_duplicate_ids(e.get("thread_independence")),
            "edq_label": e.get("event_date_quality"),
            "outcome": _OUTCOME_DISPLAY.get(
                outcome_by_id.get(eid), outcome_by_id.get(eid) or "unknown"),
            "event_study_available": eid in es_ids,
            "family_lens": family_lens,
        })
    rows.sort(key=lambda r: r["event_id"])
    return rows, edq, coverage


def _outcome_split(rows: list[dict]) -> dict:
    c = Counter(r["outcome"] for r in rows)
    return {
        "support": c.get("support", 0),
        "contradiction": c.get("contradiction", 0),
        "unresolved": c.get("unresolved", 0),
    }


def _why_grouped(cluster: dict, members: list[dict]) -> str:
    dates = Counter(m["date"] for m in members if m.get("date"))
    shared_dates = sorted(
        ((d, n) for d, n in dates.items() if n >= 2),
        key=lambda kv: (-kv[1], kv[0]))
    tickers = Counter(m["primary_ticker"] for m in members
                      if m.get("primary_ticker"))
    repeated = sorted(
        ((t, n) for t, n in tickers.items() if n >= 2),
        key=lambda kv: (-kv[1], kv[0]))
    dup_linked = sorted(
        m["event_id"] for m in members if m.get("duplicate_of"))
    parts: list[str] = []
    if shared_dates:
        top = ", ".join(f"{d} x{n}" for d, n in shared_dates[:3])
        if len(shared_dates) > 3:
            parts.append(
                f"{len(shared_dates)} shared event dates (top: {top})")
        else:
            parts.append(f"shared event date(s) {top}")
    if repeated:
        top = ", ".join(f"{t} x{n}" for t, n in repeated[:3])
        if len(repeated) > 3:
            parts.append(
                f"{len(repeated)} repeated primary tickers (top: {top})")
        else:
            parts.append(f"repeated primary ticker(s) {top}")
    if dup_linked:
        parts.append(f"{len(dup_linked)} duplicate-linked row(s)")
    if not parts:
        parts.append(
            f"same primary ticker read within {WINDOW_DAYS} calendar days")
    return "; ".join(parts)


def build_report(*, db_path: str | None = None) -> dict:
    """Assemble the K2 market-story cluster report (read-only)."""
    path = db_path or DEFAULT_DB
    rows, edq, coverage = _assemble_rows(path)
    by_id = {r["event_id"]: r for r in rows}

    clusters = build_clusters(rows, window_days=WINDOW_DAYS)
    cluster_by_event: dict[int, dict] = {}
    for c in clusters:
        for eid in c["event_ids"]:
            cluster_by_event[eid] = c

    nominal = len(rows)
    singleton = [c for c in clusters if c["size"] == 1]
    multi = [c for c in clusters if c["size"] >= 2]

    date_counts = Counter(r["date"] for r in rows if r.get("date"))
    ticker_counts = Counter(
        r["primary_ticker"] for r in rows if r.get("primary_ticker"))
    top_dates = [
        {"date": d, "rows": n}
        for d, n in sorted(date_counts.items(),
                           key=lambda kv: (-kv[1], kv[0]))[:3]
        if n >= 2
    ]
    top_tickers = [
        {"ticker": t, "rows": n}
        for t, n in sorted(ticker_counts.items(),
                           key=lambda kv: (-kv[1], kv[0]))[:3]
        if n >= 2
    ]

    date_clustered_rows = sum(n for n in date_counts.values() if n >= 2)
    dup_linked_rows = sum(1 for r in rows if r.get("duplicate_of"))
    pressures = [
        ("shared event dates", date_clustered_rows),
        ("repeated primary tickers inside overlapping windows",
         sum(n for n in ticker_counts.values() if n >= 2)),
        ("duplicate/thread links", dup_linked_rows),
    ]
    dominant_pressure = max(pressures, key=lambda p: p[1])

    es_clustered = sum(
        1 for r in rows
        if r["event_study_available"] and cluster_by_event[r["event_id"]]["size"] >= 2)
    es_singleton = sum(
        1 for r in rows
        if r["event_study_available"] and cluster_by_event[r["event_id"]]["size"] == 1)

    window_capacity = max_non_overlapping_windows(
        [r["date"] for r in rows if r.get("date")], WINDOW_DAYS)

    cluster_summary = {
        "nominal_rows": nominal,
        "cluster_count": len(clusters),
        "singleton_clusters": len(singleton),
        "multi_row_clusters": len(multi),
        "rows_in_multi_row_clusters": sum(c["size"] for c in multi),
        "largest_cluster_size": clusters[0]["size"] if clusters else 0,
        "top_dates": top_dates,
        "top_primary_tickers": top_tickers,
        "dominant_clustering_pressure": dominant_pressure[0],
        "date_clustered_rows": date_clustered_rows,
        "duplicate_linked_rows": dup_linked_rows,
        "max_non_overlapping_20d_windows": window_capacity,
        "event_study_rows_in_multi_row_clusters": es_clustered,
        "event_study_rows_in_singletons": es_singleton,
    }

    largest_clusters: list[dict] = []
    for c in multi[:LARGEST_CLUSTERS_SHOWN]:
        members = [by_id[eid] for eid in c["event_ids"]]
        families = sorted(
            {m["family_lens"] for m in members
             if m["family_lens"] not in ("multi_match", "unclassified")})
        largest_clusters.append({
            "cluster_id": c["cluster_id"],
            "label": c["label"],
            "size": c["size"],
            "date_min": c["date_min"],
            "date_max": c["date_max"],
            "event_ids": c["event_ids"],
            "primary_tickers": c["primary_tickers"],
            "family_lenses": families,
            "outcome_split": _outcome_split(members),
            "event_study_available_rows": sum(
                1 for m in members if m["event_study_available"]),
            "why_grouped": _why_grouped(c, members),
            "interpretation_caution": (
                f"These {c['size']} rows read overlapping reaction windows "
                "on one stretch of tape; weigh them as one market story, "
                f"not {c['size']} separate pieces of market evidence."
            ),
        })

    f1 = _f1_build_report(db_path=path)
    overlay_cases: list[dict] = []
    for case in sorted(f1.get("selected", []), key=lambda c: c["event_id"]):
        eid = case["event_id"]
        cluster = cluster_by_event.get(eid)
        overlay_cases.append({
            "event_id": eid,
            "role": case.get("role"),
            "family": case.get("family"),
            "outcome": _OUTCOME_DISPLAY.get(case.get("outcome"),
                                            case.get("outcome")),
            "cluster_id": cluster["cluster_id"] if cluster else None,
            "cluster_size": cluster["size"] if cluster else None,
            "grouping": (
                "multi_row" if cluster and cluster["size"] >= 2
                else "singleton" if cluster else "not_in_lens"),
            "missing_readout": eid in _MISSING_READOUT_IDS,
        })
    triplet_clusters = {
        cluster_by_event[i]["cluster_id"]
        for i in (7, 29, 38) if i in cluster_by_event
    }
    triplet = {
        "event_ids": [7, 29, 38],
        "same_cluster": len(triplet_clusters) == 1,
        "cluster_ids": sorted(triplet_clusters),
        "note": (
            "Cases 7, 29 and 38 share the 2026-04-05 event date and the "
            "XLE primary readout; under the stated rules they are one "
            "market-story cluster, not three separate pieces of market "
            "evidence."
            if len(triplet_clusters) == 1 else
            "Cases 7, 29 and 38 did not group into one cluster under the "
            "stated rules on this snapshot; re-run the report for the "
            "live grouping."
        ),
    }

    edq_den = edq.get("denominators", {})
    denominators = {
        "archive_rows": edq_den.get("archive_rows"),
        "accepted_coverage": edq_den.get("accepted_coverage_denominator"),
        "accepted_track_record": edq_den.get(
            "accepted_track_record_denominator"),
        "event_study_available": coverage.get("event_study_available_count"),
        "event_study_denominator": coverage.get("total_events"),
        "staged_candidates": edq_den.get("staged_candidate_count"),
        "k2_lens": "accepted_track_record",
    }

    reviewer_headline = [
        (f"The {nominal} accepted track-record rows group into "
         f"{len(clusters)} descriptive market-story clusters under three "
         "transparent rules -- they are not "
         f"{nominal} independent market stories."),
        (f"{cluster_summary['rows_in_multi_row_clusters']} of {nominal} rows "
         f"({_pct(cluster_summary['rows_in_multi_row_clusters'], nominal)}%) "
         f"sit in {len(multi)} multi-row clusters; the largest single "
         f"cluster holds {cluster_summary['largest_cluster_size']} rows."),
        (f"The largest clustering pressure is {dominant_pressure[0]}: "
         f"{dominant_pressure[1]} rows are touched by it."),
        ("This does not invalidate the archive; it makes the "
         "interpretation more honest. Clustered rows remain real archive "
         "evidence -- they are one story observed several times, not "
         "several stories."),
    ]

    non_claims = [
        "Descriptive grouping, not inference: this report is not a "
        "p-value, an FDR pool, a score, a rank, a signal, a forecast, or "
        "a recommendation.",
        "The cluster count is an independence caution, not an inferential "
        "effective sample size; no statistical independence is claimed "
        "for any row or cluster.",
        "Clustered rows are not invalid and singleton rows are not proof; "
        "no causal claim is made.",
        "Representative cases remain illustrative walkthrough material, "
        "not evidence of any mechanism.",
        "No family-level inference; family lenses are context columns "
        "only.",
        "The closed Phase 1 / Phase 2 FDR pools are neither read nor "
        "touched.",
        "Not a recommendation, forecast, or trading signal.",
    ]

    return {
        "denominators": denominators,
        "reviewer_headline": reviewer_headline,
        "cluster_summary": cluster_summary,
        "clusters": clusters,
        "largest_clusters": largest_clusters,
        "representative_overlay": {
            "cases": overlay_cases,
            "triplet_7_29_38": triplet,
            "missing_readouts": list(_MISSING_READOUT_IDS),
        },
        "non_claims": non_claims,
        "reproduce": {
            "commands": [
                "python scripts/effective_independent_evidence_report.py "
                "--db-path events.db",
                "python scripts/effective_independent_evidence_report.py "
                "--db-path events.db --json",
            ],
        },
    }


# ---------------------------------------------------------------------------
# Markdown exhibit
# ---------------------------------------------------------------------------

def render_markdown(report: dict) -> str:
    d = report["denominators"]
    s = report["cluster_summary"]
    overlay = report["representative_overlay"]
    lines: list[str] = []
    add = lines.append

    add("# Effective independent evidence - market-story clusters (K2)")
    add("")
    add("How many distinct market stories sit behind the accepted "
        "track-record rows? This is a read-only honesty layer over the "
        "accepted corpus: rows are grouped into descriptive market-story "
        "clusters so a reviewer can weigh the nominal row count against "
        "date clustering, repeated tickers, and duplicate links. It adds "
        "**no new score, no ranking, and no inference**.")
    add("")

    add("## What a reviewer should take away first")
    add("")
    for h in report["reviewer_headline"]:
        add(f"- {h}")
    add("")

    add("## Scope and non-claims")
    add("")
    add("- Accepted track-record rows only "
        f"(**{s['nominal_rows']}** rows); staged candidates "
        f"(**{d['staged_candidates']}**) are excluded.")
    add("- Read-only archive description; the database is opened "
        "read-only and nothing is written.")
    for nc in report["non_claims"]:
        add(f"- {nc}")
    add("")

    add("## Method in plain English")
    add("")
    add("Two rows are grouped into one market-story cluster when any of "
        "these transparent rules links them, directly or through a "
        "chain:")
    add("")
    add("- **Same event date** - their 1d/5d/20d reaction windows sit on "
        "the same tape day, so the market readouts are the same tape, "
        "whatever the headlines say.")
    add(f"- **Same primary ticker within {WINDOW_DAYS} calendar days** - "
        "the same price series is being re-read over overlapping "
        "reaction windows.")
    add("- **Duplicate links** - the event-date-quality layer already "
        "marked the rows as same-announcement collisions.")
    add("")
    add("Mechanism families are shown as context only; they play no part "
        "in the grouping. The rules are deliberately conservative about "
        "claiming separateness: chained links merge (a row 19 days from "
        "the next can chain a long same-ticker run into one cluster), "
        "and same-date rows on different tickers still share one tape "
        "day. Cross-ticker window overlap on *different* dates is NOT "
        "grouped here - that stricter lens is reported as the "
        "20d-window capacity line below and would group even more "
        "aggressively. The method is descriptive grouping, not "
        "inference.")
    add("")

    add("## Denominator ledger (live, unchanged)")
    add("")
    add(f"archive **{d['archive_rows']}** - accepted coverage "
        f"**{d['accepted_coverage']}** - accepted track-record "
        f"**{d['accepted_track_record']}** - event-study "
        f"**{d['event_study_available']}/{d['event_study_denominator']}** "
        f"- staged **{d['staged_candidates']}** (excluded).")
    add("")
    add("K2 reads the **accepted track-record** lens "
        f"(**{d['accepted_track_record']}** rows): it is the corpus the "
        "track-record split is quoted from, so it is where an inflated "
        "nominal row count would mislead a reviewer most.")
    add("")

    add("## Cluster summary")
    add("")
    add("| measure | value |")
    add("| --- | --- |")
    add(f"| nominal accepted track-record rows | {s['nominal_rows']} |")
    add(f"| market-story clusters | **{s['cluster_count']}** |")
    add(f"| singleton clusters | {s['singleton_clusters']} |")
    add(f"| multi-row clusters | {s['multi_row_clusters']} |")
    add(f"| rows in multi-row clusters | {s['rows_in_multi_row_clusters']} "
        f"({_pct(s['rows_in_multi_row_clusters'], s['nominal_rows'])}%) |")
    add(f"| largest cluster size | {s['largest_cluster_size']} |")
    top_dates = ", ".join(
        f"{t['date']} ({t['rows']} rows)" for t in s["top_dates"]) or "none"
    add(f"| top clustered dates | {top_dates} |")
    top_tickers = ", ".join(
        f"{t['ticker']} ({t['rows']} rows)"
        for t in s["top_primary_tickers"]) or "none"
    add(f"| top repeated primary tickers | {top_tickers} |")
    add(f"| event-study rows inside multi-row clusters | "
        f"{s['event_study_rows_in_multi_row_clusters']} |")
    add(f"| event-study rows on singletons | "
        f"{s['event_study_rows_in_singletons']} |")
    add(f"| max non-overlapping 20d windows (C1-style caution) | "
        f"{s['max_non_overlapping_20d_windows']} |")
    add("")
    add("The 20d-window capacity line is the stricter cross-ticker "
        "caution: even ignoring tickers and headlines, at most "
        f"{s['max_non_overlapping_20d_windows']} mutually non-overlapping "
        "20-day reaction windows exist among these rows' event dates. It "
        "is an upper-bound diagnostic in the C1 house convention, not an "
        "inferential effective sample size.")
    add("")

    add("## Largest clusters")
    add("")
    add("| cluster | rows | dates | primary tickers | S / C / U | ES | "
        "why grouped |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for c in report["largest_clusters"]:
        span = (c["date_min"] if c["date_min"] == c["date_max"]
                else f"{c['date_min']} .. {c['date_max']}")
        osp = c["outcome_split"]
        tickers = ", ".join(c["primary_tickers"][:4]) or "-"
        if len(c["primary_tickers"]) > 4:
            tickers += ", ..."
        add(f"| {c['cluster_id']} | {c['size']} | {span} | {tickers} | "
            f"{osp['support']} / {osp['contradiction']} / "
            f"{osp['unresolved']} | {c['event_study_available_rows']}/"
            f"{c['size']} | {c['why_grouped']} |")
    add("")
    add("Event ids per cluster:")
    add("")
    for c in report["largest_clusters"]:
        ids = ", ".join(str(i) for i in c["event_ids"])
        add(f"- **{c['cluster_id']}** ({c['label']}): {ids}")
    add("")
    add("Interpretation caution, per cluster: rows inside one cluster "
        "read overlapping reaction windows on one stretch of tape - "
        "weigh each cluster as one market story, not as its row count.")
    add("")

    add("## Singleton / less-clustered rows")
    add("")
    add(f"{s['singleton_clusters']} rows stand alone under these rules "
        "(no shared date, no repeated primary ticker inside the "
        f"{WINDOW_DAYS}-day window, no duplicate link). These rows are "
        "**less exposed to this specific clustering issue** - nothing "
        "more. A singleton is still one n=1 descriptive read with its "
        "own anchor and scoring caveats; it is not proof of anything.")
    add("")

    add("## Representative case overlay")
    add("")
    add("Where the 15 representative walkthrough cases fall under the "
        "same grouping:")
    add("")
    add("| case | family | outcome | cluster | cluster size | grouping | "
        "readout |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for case in overlay["cases"]:
        readout = "missing" if case["missing_readout"] else "available"
        add(f"| {case['event_id']} | {case['family']} | {case['outcome']} "
            f"| {case['cluster_id']} | {case['cluster_size']} | "
            f"{case['grouping'].replace('_', '-')} | {readout} |")
    add("")
    triplet = overlay["triplet_7_29_38"]
    add(f"- **Cases 7 / 29 / 38:** {triplet['note']}")
    missing = ", ".join(str(i) for i in overlay["missing_readouts"])
    add(f"- **Missing market readouts:** {missing} - these cases still "
        "carry event-date and cluster context even though no window can "
        "be read; a missing readout is stated, never hidden.")
    add("")

    add("## Reader guardrails")
    add("")
    add("- Market-story clusters are a descriptive review aid; they are "
        "not an inferential effective sample size and no 'effective n' "
        "is claimed or implied.")
    add("- Clustered rows are not invalid; singleton rows are not proof.")
    add("- The cluster count is an independence caution, not a quality "
        "measure of the archive or of any family.")
    add("- No family-level inference: family lenses are context columns "
        "only.")
    add("- No causal claim; descriptive grouping, not inference.")
    add("- Not a trading signal, forecast, or recommendation.")
    add("")

    add("## Reproduce (read-only)")
    add("")
    add("```")
    for cmd in report["reproduce"]["commands"]:
        add(cmd)
    add("```")
    add("")
    add("Source lens: the accepted track-record rows "
        f"(**{d['accepted_track_record']}**), assembled from the "
        "event-date-quality layer (dates, anchor labels, duplicate "
        "links), the track-record scoring layer (canonical any-support "
        "outcomes), the event-study coverage layer (readout "
        "availability), and the representative case selection - all "
        "read-only (`mode=ro`); the database is never written. No "
        "provider, API, network, fetch, or backfill call is made.")
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "K2 - descriptive market-story clusters over the accepted "
            "track-record corpus (read-only)."
        ),
    )
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--json", action="store_true",
                        help="emit the report as JSON instead of markdown")
    args = parser.parse_args(argv)

    report = build_report(db_path=args.db_path)
    sink = sys.stdout
    if args.json:
        json.dump(report, sink, indent=2, sort_keys=True)
        sink.write("\n")
    else:
        sink.write(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
