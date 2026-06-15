#!/usr/bin/env python3
"""Read-only mechanism-family evidence inventory (E1).

Summarise where the accepted archive has real evidence depth and where it is
thin, by mechanism family - WITHOUT adding any new claim, p-value, FDR pool,
forecast, or trading language.

Family lens (non-negotiable, and the reason this report exists): every accepted
thesis row is stored ``mechanism_family='none'``, so the stored taxonomy gives
no structure for the 86 track-record rows. The inventory therefore groups the
accepted thesis corpus by the *tested* J1 headline overlay
(``accepted_family_overlay_report.classify_headline``) and surfaces the
multi-match and unclassified buckets explicitly. The 8 stored accepted
observations (tariff/sanction) are the coverage-only bridge to the stored
taxonomy and are reported separately - they are in the 94 coverage denominator,
not the 86 track-record denominator.

Two denominator lenses are kept apart at every row (the carousel discipline):

  * coverage lens     = 94 accepted rows; event-study availability is 78 / 94;
  * track-record lens = 86 accepted thesis rows; per-family event-study counts
    are ``k of the family's thesis rows`` on THIS lens, never against 94.

Everything is read-only (``mode=ro`` connections; reused tested loaders); no DB
or price_cache write, no paid call, no /analyze, no fetch.

Usage::

    python scripts/mechanism_family_evidence_inventory.py --db-path events.db --json
    python scripts/mechanism_family_evidence_inventory.py --db-path events.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import date as _date
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from scripts.accepted_family_overlay_report import (  # noqa: E402
    FAMILY_RULES,
    build_overlay,
    classify_headline,
)
from scripts.event_study_coverage_report import (  # noqa: E402
    summarize_event_study_coverage,
)
from scripts.mechanism_family_overview_report import build_overview  # noqa: E402
from scripts.track_record_sensitivity_report import _load_accepted_records  # noqa: E402
from stats.robust_diagnostics import independent_window_summary  # noqa: E402
from stats.track_record_scoring import score_event_under_rule  # noqa: E402

# Tunables (deterministic, inspectable).
LOW_N_FLOOR = 5          # families below this are flagged low_n
CAPACITY_MIN_N = 8       # per-family independent-window capacity suppressed below
                         # this (matches the C1 min-independent-window gate); a
                         # bare capacity number on tiny n reads as effective-n
REPRESENTATIVE_CAP = 3   # representative cases per family
TOP_TICKERS = 5
SCORING_RULE = "any_support"  # the canonical track-record rule (AV3)
CAPACITY_HORIZONS = (1, 5, 20)

# The C1 independent-window non-claim, carried verbatim so a per-family or
# global capacity number can never read as a power / effective-sample claim.
CAPACITY_NON_CLAIM = (
    "Diagnostic only: quantifies overlap/dependence pressure on the nominal n. "
    "It is an upper-bound count of mutually non-overlapping windows, not a true "
    "effective sample size; it runs no cohort inference, adds no p-value or CI, "
    "does not validate any mechanism, changes no FDR scope, and does not "
    "authorize pooling."
)

NON_CLAIMS: tuple[str, ...] = (
    "Descriptive coverage decomposition only; this inventory adds no new claim.",
    "No pooled significance: no CI, p-value, or FDR is computed or implied "
    "anywhere here.",
    "No family-level causal claim is established; per-family rows are post-hoc "
    "headline matches over small n.",
    "No family performance ranking and no across-family comparison is implied; "
    "outcome labels are the canonical any_support vocabulary applied per event, "
    "descriptively.",
    "Not a recommendation of any kind.",
    "Representative cases are illustrative, not evidence.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor reopened.",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked.",
    "Denominators unchanged: 94 accepted coverage / 86 accepted track-record on "
    "the live archive; staged candidates (13) are excluded and never classified "
    "here.",
)

# Order families by the canonical rule table so output ordering is stable and
# the canonical-vs-overlay flag travels with each family.
_FAMILY_ORDER = [r["family"] for r in FAMILY_RULES]
_CANONICAL_FLAG = {r["family"]: bool(r["canonical_family"]) for r in FAMILY_RULES}


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def _ordinal(value: Any) -> int | None:
    """ISO ``YYYY-MM-DD`` (or leading date) -> day ordinal; else None."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return _date.fromisoformat(value[:10]).toordinal()
    except ValueError:
        return None


def select_representative_cases(
    rows: Sequence[dict], *, cap: int = REPRESENTATIVE_CAP
) -> list[dict]:
    """Deterministic representative pick under an explicit total order:

    1. one ``contradicted`` row if any exists,
    2. one ``unresolved`` row if any exists,
    3. fill the remaining slots,

    where every pick prefers event-study-available rows, then the lowest
    event_id. The returned list is finally sorted by event_id for stable
    display. Never forces a case that does not exist.
    """
    cap = max(int(cap), 0)

    def order(r: dict) -> tuple[bool, Any]:
        return (not bool(r.get("event_study_available")), r["event_id"])

    chosen: list[dict] = []
    taken: set = set()

    def _take(candidates: list[dict]) -> None:
        for r in sorted(candidates, key=order):
            if len(chosen) >= cap:
                return
            if r["event_id"] in taken:
                continue
            chosen.append(r)
            taken.add(r["event_id"])
            return

    if cap:
        _take([r for r in rows if r.get("outcome") == "contradicted"])
        _take([r for r in rows if r.get("outcome") == "unresolved"])
        for r in sorted([r for r in rows if r["event_id"] not in taken], key=order):
            if len(chosen) >= cap:
                break
            chosen.append(r)
            taken.add(r["event_id"])

    return sorted(chosen, key=lambda r: r["event_id"])


def _top_tickers(rows: Iterable[dict]) -> list[dict]:
    cnt: Counter = Counter()
    for r in rows:
        for sym in (r.get("symbols") or []):
            if isinstance(sym, str) and sym:
                cnt[sym] += 1
    ordered = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_TICKERS]
    return [{"symbol": s, "count": c} for s, c in ordered]


def _top_sectors(rows: Iterable[dict]) -> list[dict]:
    cnt: Counter = Counter()
    for r in rows:
        sec = r.get("sector")
        if isinstance(sec, str) and sec:
            cnt[sec] += 1
    ordered = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_TICKERS]
    return [{"sector": s, "count": c} for s, c in ordered]


# ---------------------------------------------------------------------------
# Pure assembly core
# ---------------------------------------------------------------------------

def assemble_inventory(
    enriched_records: Sequence[dict],
    *,
    denominators: dict,
    taxonomy_readout: Sequence[str],
    observations_bridge: dict,
) -> dict:
    """Build the inventory dict from already-enriched accepted thesis records.

    ``enriched_records`` each carry ``event_id``, ``headline``, ``event_date``,
    ``symbols`` (list[str]), ``tickers`` (directional list for the scorer),
    ``event_study_available`` (bool, track-record lens), and optional
    ``sector``. Pure: no DB, no price data, no network.
    """
    records = list(enriched_records or [])

    # Score + classify every record once.
    single: dict[str, list[dict]] = {f: [] for f in _FAMILY_ORDER}
    multi: list[dict] = []
    unclassified: list[dict] = []
    for rec in records:
        outcome = score_event_under_rule(rec.get("tickers") or [], SCORING_RULE)
        matched = classify_headline(rec.get("headline"))
        row = {
            "event_id": rec["event_id"],
            "headline": (rec.get("headline") or "")[:90],
            "event_date": rec.get("event_date"),
            "symbols": rec.get("symbols") or [],
            "sector": rec.get("sector"),
            "outcome": outcome,
            "event_study_available": bool(rec.get("event_study_available")),
            "matched": matched,
        }
        if len(matched) == 1:
            single[matched[0]].append(row)
        elif matched:
            multi.append(row)
        else:
            unclassified.append(row)

    families: list[dict] = []
    for fam in _FAMILY_ORDER:
        rows = single[fam]
        if not rows:
            continue
        families.append(_family_block(fam, rows))

    single_total = sum(len(single[f]) for f in _FAMILY_ORDER)
    track_record = denominators.get("accepted_track_record_denominator")
    sum_total = single_total + len(multi) + len(unclassified)

    es_count = denominators.get("event_study_available_count")
    es_cov_denom = denominators.get("event_study_coverage_denominator")

    ordered = sorted(
        families, key=lambda f: (-f["accepted_thesis_count"], f["family"])
    )
    largest = [
        {"family": f["family"], "count": f["accepted_thesis_count"]}
        for f in ordered[:3]
    ]
    thinnest = [
        {"family": f["family"], "count": f["accepted_thesis_count"]}
        for f in reversed(ordered[-3:])
    ]

    all_ords = [o for o in (_ordinal(r["event_date"]) for r in records)
                if o is not None]
    capacity_global = {
        "horizons": {
            str(h): independent_window_summary(all_ords, window_length=h)
            for h in CAPACITY_HORIZONS
        },
        "n_with_date": len(all_ords),
        "n_distinct_event_dates": len(set(all_ords)),
        "non_claim": CAPACITY_NON_CLAIM,
    }

    global_summary = {
        "total_accepted_coverage":
            denominators.get("accepted_coverage_denominator"),
        "total_accepted_track_record": track_record,
        "total_event_study_available_coverage_lens":
            f"{es_count} / {es_cov_denom}",
        "n_families_with_accepted_thesis": len(families),
        "largest_families": largest,
        "thinnest_families": thinnest,
        "multi_match_count": len(multi),
        "unclassified_count": len(unclassified),
        "staged_candidates_excluded": denominators.get("staged_candidates"),
        "sum_invariant": {
            "single_match_total": single_total,
            "multi_match": len(multi),
            "unclassified": len(unclassified),
            "sum": sum_total,
            "equals_track_record": sum_total == track_record,
        },
        "independent_window_capacity_global": capacity_global,
    }

    return {
        "denominators": {
            **denominators,
            "lens_note": (
                "Two lenses, kept separate: accepted coverage = "
                f"{denominators.get('accepted_coverage_denominator')}, accepted "
                f"track-record = {track_record}. Event-study availability "
                f"{es_count} / {es_cov_denom} is the COVERAGE lens; per-family "
                "event-study counts are on the track-record lens (k of the "
                "family's thesis rows)."
            ),
        },
        "family_taxonomy_note": {
            "primary_lens": (
                "J1 headline overlay (classify_headline) over the accepted "
                "thesis rows; every thesis row is stored mechanism_family="
                "'none', so the headline overlay is the only lens with family "
                "structure."
            ),
            "stored_taxonomy_note": (
                "The stored taxonomy labels only the accepted curated "
                "observations (tariff/sanction), surfaced in "
                "accepted_observations_bridge as the coverage-only (in the 94, "
                "not the 86) rows the Evidence Overview shows."
            ),
            "taxonomy_readout": list(taxonomy_readout or []),
        },
        "families": families,
        "multi_family_ambiguous": {
            "count": len(multi),
            "representative_event_ids":
                sorted(r["event_id"] for r in multi)[:10],
            "matched_family_sets":
                sorted({tuple(sorted(r["matched"])) for r in multi}),
            "note": (
                "Headlines matching more than one family are reported here with "
                "all matched names, never tie-broken into one family."
            ),
        },
        "unclassified": {
            "count": len(unclassified),
            "representative_event_ids":
                sorted(r["event_id"] for r in unclassified)[:10],
            "representative_headlines":
                [r["headline"] for r in
                 sorted(unclassified, key=lambda r: r["event_id"])[:5]],
            "note": (
                "Headlines matching no family rule stay unclassified - kept "
                "visible, not absorbed into any family."
            ),
        },
        "accepted_observations_bridge": {
            **observations_bridge,
            "note": (
                "Accepted curated observations carry a stored mechanism_family "
                "but no thesis outcome; they are in the coverage denominator "
                "(94), not the track-record denominator (86). This is the "
                "coverage-minus-track-record gap."
            ),
        },
        "global_summary": global_summary,
        "non_claims": list(NON_CLAIMS),
        "reproduce_command": (
            "python scripts/mechanism_family_evidence_inventory.py "
            "--db-path events.db --json"
        ),
    }


def _family_block(fam: str, rows: list[dict]) -> dict:
    count = len(rows)
    validated = sum(1 for r in rows if r["outcome"] == "validated")
    contradicted = sum(1 for r in rows if r["outcome"] == "contradicted")
    unresolved = sum(1 for r in rows if r["outcome"] == "unresolved")
    es_avail = sum(1 for r in rows if r["event_study_available"])

    dates = sorted([r["event_date"] for r in rows if r.get("event_date")])
    distinct_dates = len(set(dates))
    date_span = ({"first": dates[0], "last": dates[-1]} if dates
                 else {"first": None, "last": None})

    capacity = None
    if count >= CAPACITY_MIN_N:
        ords = [o for o in (_ordinal(r["event_date"]) for r in rows)
                if o is not None]
        capacity = {
            "horizons": {
                str(h): independent_window_summary(ords, window_length=h)
                for h in CAPACITY_HORIZONS
            },
            "non_claim": CAPACITY_NON_CLAIM,
        }

    weaknesses: list[str] = []
    if count < LOW_N_FLOOR:
        weaknesses.append(
            f"low_n: {count} accepted thesis rows (< {LOW_N_FLOOR})"
        )
    if es_avail < count:
        weaknesses.append(
            f"missing_event_study_coverage: {es_avail}/{count} thesis rows "
            "have a SPY-relative readout"
        )
    if distinct_dates < count:
        weaknesses.append(
            f"clustered_dates: {distinct_dates} distinct event dates across "
            f"{count} rows"
        )
    if count < CAPACITY_MIN_N:
        weaknesses.append(
            "capacity_suppressed_small_family: independent-window capacity "
            f"withheld below n={CAPACITY_MIN_N} to avoid an "
            "effective-sample-size read"
        )
    if not _CANONICAL_FLAG.get(fam, False):
        weaknesses.append(
            "overlay_only_family: outside the canonical stored taxonomy "
            "(headline-overlay bucket, made honest rather than forced)"
        )

    reps = select_representative_cases(rows, cap=REPRESENTATIVE_CAP)
    representative_cases = [
        {
            "event_id": r["event_id"],
            "event_date": r["event_date"],
            "headline": r["headline"],
            "outcome": r["outcome"],
            "event_study_available": r["event_study_available"],
        }
        for r in reps
    ]

    return {
        "family": fam,
        "canonical_family": _CANONICAL_FLAG.get(fam, False),
        "accepted_thesis_count": count,
        "accepted_row_denominator": count,
        "track_record_denominator": count,
        "event_study_available": {
            "available": es_avail,
            "of_family_thesis": count,
            "lens": "track_record",
        },
        "outcomes": {
            "validated": validated,
            "contradicted": contradicted,
            "unresolved": unresolved,
            "rule": SCORING_RULE,
        },
        "top_tickers": _top_tickers(rows),
        "top_sectors": _top_sectors(rows),
        "date_span": date_span,
        "distinct_event_dates": distinct_dates,
        "independent_window_capacity": capacity,
        "representative_cases": representative_cases,
        "weaknesses": weaknesses,
    }


# ---------------------------------------------------------------------------
# Read-only DB wiring
# ---------------------------------------------------------------------------

def _symbols_from_market_tickers(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    out: list[str] = []
    for t in parsed if isinstance(parsed, list) else []:
        if isinstance(t, dict):
            sym = t.get("symbol") or t.get("ticker")
            if isinstance(sym, str) and sym:
                out.append(sym)
    return out


def _sector_classifier():
    """Best-effort import of the descriptive sector classifier. Returns a
    callable ``(symbol, headline) -> sector_name | None`` or None if the mapping
    is unavailable (kept optional so a missing sector layer never breaks the
    inventory). The mapping is keyword-only
    (``_classify(*, ticker, headline) -> (sector_name, sector_etf, confidence,
    reason)``); the no-signal ``broad`` fallback is treated as 'no sector'."""
    try:
        from scripts.sector_benchmark_suggestion_report import _classify
    except Exception:
        return None

    def _sector(symbol: str | None, headline: str | None):
        try:
            result = _classify(ticker=symbol, headline=headline)
        except Exception:
            return None
        name = result[0] if isinstance(result, (tuple, list)) and result else result
        if isinstance(name, str) and name and name != "broad":
            return name
        return None

    return _sector


def _enrich_records(path: str | None) -> tuple[list[dict], int | None, int | None]:
    """Load the canonical 86 thesis records and attach event_date, symbols,
    event-study availability (track-record lens), and a best-effort sector.
    Read-only. Returns (enriched, es_available_count, es_coverage_total)."""
    records, _denom_meta = _load_accepted_records(path)

    meta: dict[int, dict] = {}
    if path is not None:
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.Error:
            conn = None
        if conn is not None:
            try:
                conn.row_factory = sqlite3.Row
                for r in conn.execute(
                    "SELECT id, event_date, market_tickers FROM events"
                ).fetchall():
                    meta[r["id"]] = {
                        "event_date": r["event_date"],
                        "symbols": _symbols_from_market_tickers(
                            r["market_tickers"]
                        ),
                    }
            except sqlite3.Error:
                pass
            finally:
                conn.close()

    es = summarize_event_study_coverage(db_path=path, limit=10_000)
    es_ids = {e.get("event_id") for e in es.get("available", [])}
    es_count = es.get("event_study_available_count")
    es_total = es.get("total_events")

    sector_of = _sector_classifier()
    enriched: list[dict] = []
    for r in records:
        m = meta.get(r["event_id"], {})
        symbols = m.get("symbols", [])
        sector = None
        if sector_of is not None:
            sector = sector_of(symbols[0] if symbols else None, r.get("headline"))
        enriched.append({
            "event_id": r["event_id"],
            "headline": r.get("headline"),
            "event_date": m.get("event_date"),
            "symbols": symbols,
            "tickers": r.get("tickers") or [],
            "event_study_available": r["event_id"] in es_ids,
            "sector": sector,
        })
    return enriched, es_count, es_total


def build_inventory(*, db_path: str | None = None) -> dict:
    """Build the inventory from the live archive. Read-only end to end."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)

    enriched, es_count, es_total = _enrich_records(path)

    overview = build_overview(db_path=path, limit_cases=0)
    od = overview["denominators"]
    denominators = {
        "archive_rows": od.get("archive_rows"),
        "accepted_coverage_denominator":
            od.get("accepted_coverage_denominator"),
        "accepted_track_record_denominator":
            od.get("accepted_track_record_denominator"),
        "event_study_available_count": es_count,
        "event_study_coverage_denominator": es_total,
        "staged_candidates": od.get("staged_candidates"),
    }

    by_stored = [
        {"family": f["family"], "count": f.get("accepted_observation_count", 0)}
        for f in overview.get("families", [])
        if f.get("accepted_observation_count")
    ]
    cov = od.get("accepted_coverage_denominator")
    trk = od.get("accepted_track_record_denominator")
    observations_bridge = {
        "count": (cov - trk) if isinstance(cov, int) and isinstance(trk, int)
        else None,
        "by_stored_family": by_stored,
    }

    overlay = build_overlay(db_path=path, include_examples=3, limit=10)
    tr = overlay.get("taxonomy_readout", {})
    taxonomy_readout = list(tr.get("what_the_overlay_reveals", [])) + \
        list(tr.get("what_remains_missing", []))

    return assemble_inventory(
        enriched,
        denominators=denominators,
        taxonomy_readout=taxonomy_readout,
        observations_bridge=observations_bridge,
    )


# ---------------------------------------------------------------------------
# Rendering / CLI
# ---------------------------------------------------------------------------

def render_text(report: dict) -> str:
    """ASCII / cp1252-safe text rendering."""
    d = report["denominators"]
    g = report["global_summary"]
    lines: list[str] = []
    lines.append("Mechanism-family evidence inventory (read-only)")
    lines.append("=" * 48)
    lines.append("")
    lines.append("Denominators:")
    lines.append(f"  archive rows                : {d.get('archive_rows')}")
    lines.append(f"  accepted coverage           : "
                 f"{d.get('accepted_coverage_denominator')}")
    lines.append(f"  accepted track-record       : "
                 f"{d.get('accepted_track_record_denominator')}")
    lines.append(f"  event-study available (cov) : "
                 f"{g.get('total_event_study_available_coverage_lens')}")
    lines.append(f"  staged candidates (excluded): "
                 f"{d.get('staged_candidates')}")
    lines.append("")
    inv = g["sum_invariant"]
    lines.append(
        f"Sum-invariant: single {inv['single_match_total']} + multi "
        f"{inv['multi_match']} + unclassified {inv['unclassified']} = "
        f"{inv['sum']} (== track-record: {inv['equals_track_record']})"
    )
    lines.append("")
    lines.append("Families (track-record lens):")
    for f in report["families"]:
        oc = f["outcomes"]
        es = f["event_study_available"]
        lines.append(
            f"  {f['family']:<32} n={f['accepted_thesis_count']:<3} "
            f"v/c/u={oc['validated']}/{oc['contradicted']}/{oc['unresolved']} "
            f"ES={es['available']}/{es['of_family_thesis']} "
            f"dates={f['distinct_event_dates']} "
            f"span={f['date_span']['first']}..{f['date_span']['last']}"
        )
        if f["weaknesses"]:
            for w in f["weaknesses"]:
                lines.append(f"      - {w}")
    lines.append("")
    lines.append(f"Multi-family ambiguous : {g['multi_match_count']}")
    lines.append(f"Unclassified           : {g['unclassified_count']}")
    bridge = report["accepted_observations_bridge"]
    lines.append(
        f"Observations bridge    : {bridge.get('count')} "
        f"(coverage-only, stored taxonomy)"
    )
    lines.append("")
    lines.append("Non-claims:")
    for nc in report["non_claims"]:
        lines.append(f"  - {nc}")
    lines.append("")
    lines.append(f"Reproduce: {report['reproduce_command']}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only mechanism-family evidence inventory.",
    )
    parser.add_argument("--db-path", default=None,
                        help="path to events.db (default: db.DB_FILE)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    args = parser.parse_args(argv)
    stream = out if out is not None else sys.stdout

    report = build_inventory(db_path=args.db_path)
    if args.json:
        json.dump(report, stream, indent=2)  # ensure_ascii=True -> cp1252-safe
        stream.write("\n")
    else:
        stream.write(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
