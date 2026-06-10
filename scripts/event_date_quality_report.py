#!/usr/bin/env python3
"""Read-only event-date quality / anticipation-risk report.

Market reactions are only as interpretable as their event date. A DOJ suit
filing is a discrete information shock; a scheduled bill signing is the
culmination of a telegraphed process; a strike start is partly anticipated; a
same-thread export-control update is real but not independent of an earlier
anchor row. This report classifies every reviewable row into a categorical
anchor label BEFORE anyone reads 1d/5d/20d windows, so event-date risk is
visible up front.

Labels (categorical on purpose - no fake-precision numeric score):

  * ``clean_discrete_anchor``        - discrete filing/action wording
  * ``partial_anticipation``         - process-start / anticipatory wording
  * ``scheduled_or_weak_anchor``     - scheduled culmination wording
  * ``continuation_or_thread_sibling`` - shares a policy thread with an
                                         earlier same-family row
  * ``duplicate_or_deferred``        - same-announcement collision
  * ``manual_review_needed``         - missing/ambiguous fields or wording

Rules are deliberately simple and explainable: headline keyword lists, a
same-date/same-ticker/near-identical-headline collision check, a same-family
primary-ticker thread link, and a small curated thread-entity lexicon derived
from the curated sanction anchors (298/300/301). Every label carries an
``anchor_rationale`` naming the rule that fired.

This is a research-readiness / caution layer. An event-date label is NOT a
statement about mechanism correctness and never a claim of significance.
Read-only: one ``mode=ro`` connection; no DB write, no provider, no paid
call, no promotion; accepted, curated, staged, and pending rows stay
separated and excluded rows (intake stubs, synthetic seeds) are disclosed
but not classified.

Usage::

    python scripts/event_date_quality_report.py --db-path events.db --json
    python scripts/event_date_quality_report.py --db-path events.db
    python scripts/event_date_quality_report.py --db-path events.db --lens staged
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date as _date
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402  - stage constants + synthetic_seed_ids + DB_FILE

LABELS: tuple[str, ...] = (
    "clean_discrete_anchor", "partial_anticipation",
    "scheduled_or_weak_anchor", "continuation_or_thread_sibling",
    "duplicate_or_deferred", "manual_review_needed",
)

# Keyword rules. Scheduled is checked before anticipation, anticipation
# before clean, so culmination and caution wording always win over action
# verbs in the same headline. Phrases match as lowercase substrings; single
# words match WHOLE TOKENS only (so 'sues' never fires inside 'issues' and
# 'possible' never fires inside 'impossible'); the 'approv' stem covers
# approve/approves/approval.
_SCHEDULED_PHRASES = ("signed into law", "takes effect", "set to")
_SCHEDULED_TOKENS = frozenset({"signs", "scheduled"})
_SCHEDULED_STEMS = ("approv",)

_ANTICIPATION_PHRASES: tuple[str, ...] = ()
_ANTICIPATION_TOKENS = frozenset({
    "expected", "expects", "may", "could", "considers", "considering",
    "consider", "proposed", "proposes", "planned", "plans", "intent",
    "intends", "begins", "deadline", "possible",
})

_CLEAN_PHRASES = ("announces final rule",)
_CLEAN_TOKENS = frozenset({
    "sues", "sued", "files", "filed", "lawsuit", "imposes", "imposed",
    "adds", "added", "designates", "directs", "issues", "implements",
    "strengthens", "amends", "discloses", "launches", "hits", "halts",
    "seizes", "raises",
})

# Curated thread-entity lexicon (v1) - target entities of the curated
# semiconductor export-control anchors (rows 298/300/301). A later
# same-family row whose headline shares one of these with an earlier row is
# a thread continuation, not an independent anchor. Deliberately small:
# instrument/commodity words (steel, tariff, entity list, china) are NOT
# threads - threads are defined by target entity, mirroring the AX1 review.
THREAD_LEXICON: tuple[str, ...] = ("huawei", "smic", "nvidia")

# Same-date collision thresholds: with a shared primary ticker a moderate
# headline overlap is enough; with different primary legs the headlines must
# be near-identical (live 302/315 share an identical headline but list
# different primary legs).
_DUP_TOKEN_OVERLAP = 0.5
_DUP_TOKEN_OVERLAP_NO_TICKER = 0.9

_HORIZON_CAUTION: dict[str, str] = {
    "clean_discrete_anchor": (
        "Windows anchor on a discrete date; the n=1 descriptive limits "
        "still apply."
    ),
    "partial_anticipation": (
        "Pre-date anticipation can leak into prices; the 1d window may "
        "understate (or misplace) the full repricing."
    ),
    "scheduled_or_weak_anchor": (
        "Most information was likely priced before this date; the 1d window "
        "measures residual surprise only."
    ),
    "continuation_or_thread_sibling": (
        "Windows overlap an existing policy thread; the read is not "
        "independent of the earlier anchor row(s)."
    ),
    "duplicate_or_deferred": (
        "Deferred: resolve the duplicate before reading any window."
    ),
    "manual_review_needed": (
        "Do not interpret windows until the anchor is manually reviewed."
    ),
}

_ANTICIPATION_RISK: dict[str, str] = {
    "clean_discrete_anchor": "low",
    "partial_anticipation": "elevated",
    "scheduled_or_weak_anchor": "high",
    "continuation_or_thread_sibling": "thread_dependent",
    "duplicate_or_deferred": "deferred",
    "manual_review_needed": "unknown",
}

NON_CLAIMS: tuple[str, ...] = (
    "An event-date quality label is research caution, not proof of any "
    "mechanism and not a measure of mechanism correctness.",
    "Representative classifications are illustrative; rules are simple "
    "keyword/collision heuristics a reviewer can re-derive.",
    "Staged candidates are not accepted evidence and stay excluded from "
    "every accepted denominator (denominators unchanged).",
    "No paid analysis was run and no candidate was promoted; paid /analyze "
    "remains blocked.",
    "No single-event significance is claimed at any horizon (n=1: no CI, "
    "p-value, or FDR).",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor implied.",
)

# Shortlist implications - curated sentences keyed by event id; the LABEL is
# always taken from the live classification, never hardcoded.
_SHORTLIST_NOTES: dict[int, str] = {
    303: "Regulation conduct case (DOJ v Apple); a clean suit-filing date "
         "supports window interpretation.",
    304: "Regulation structural case (DOJ v Google ad-tech); clean filing "
         "date; paid analysis deferred by operator decision (B2b).",
    313: "Labor production/wage-cost case (UAW); useful but carries a "
         "partial-anticipation caveat (telegraphed deadline).",
    311: "Industrial-policy case (CHIPS); scheduled signing is a weak "
         "information-shock anchor.",
    312: "Industrial-policy case (IRA); scheduled signing is a weak "
         "information-shock anchor.",
}


# ---------------------------------------------------------------------------
# Read-only load + corpus status
# ---------------------------------------------------------------------------


def _stage_names() -> tuple[frozenset, str, str, str, str]:
    non_analysis = frozenset(getattr(db, "NON_ANALYSIS_STAGES", frozenset(
        {"curated_intake", "z1a_candidate_pack", "analysis_pending_review"})))
    candidate = getattr(db, "CANDIDATE_PACK_STAGE", "z1a_candidate_pack")
    if not isinstance(candidate, str):
        candidate = "z1a_candidate_pack"
    intake = getattr(db, "CURATED_INTAKE_STAGE", "curated_intake")
    pending = getattr(db, "ANALYSIS_PENDING_REVIEW_STAGE",
                      "analysis_pending_review")
    observation = getattr(db, "CURATED_OBSERVATION_STAGE",
                          "curated_observation")
    return non_analysis, candidate, intake, pending, observation


def _primary_ticker(raw: Any) -> str | None:
    if not raw:
        return None
    parsed = raw
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (TypeError, ValueError):
            return None
    if not isinstance(parsed, list):
        return None
    for entry in parsed:
        if isinstance(entry, dict):
            sym = entry.get("symbol")
            if isinstance(sym, str) and sym.strip():
                return sym.strip().upper()
    return None


def _parse_date(value: Any) -> _date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _load_rows(path: str) -> tuple[list[dict], frozenset]:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return [], frozenset()
    try:
        conn.row_factory = sqlite3.Row
        try:
            raw = conn.execute(
                "SELECT id, event_date, stage, mechanism_family, headline, "
                "market_tickers FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            return [], frozenset()
        try:
            synthetic = db.synthetic_seed_ids(conn)
        except Exception:
            synthetic = frozenset()
    finally:
        conn.close()
    rows = []
    for r in raw:
        rows.append({
            "event_id": r["id"],
            "date": (r["event_date"] or "")[:10],
            "parsed_date": _parse_date(r["event_date"]),
            "stage": r["stage"] if isinstance(r["stage"], str) else None,
            "family": (r["mechanism_family"] or "").strip().lower() or "none",
            "headline": r["headline"] or "",
            "primary_ticker": _primary_ticker(r["market_tickers"]),
        })
    return rows, synthetic


def _corpus_status(row: dict, synthetic: frozenset) -> str:
    non_analysis, candidate, intake, pending, observation = _stage_names()
    stage = row["stage"]
    if stage == candidate:
        return "staged"
    if stage == intake:
        return "excluded"
    if stage == pending:
        return "pending"
    if row["event_id"] in synthetic:
        return "excluded"
    if stage == observation:
        return "curated"
    return "accepted"


# ---------------------------------------------------------------------------
# Classification rules
# ---------------------------------------------------------------------------


def _tokens(text: str) -> set[str]:
    out = set()
    for w in "".join(c if c.isalnum() else " " for c in text.lower()).split():
        if len(w) >= 3:
            out.add(w)
    return out


def _headline_overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _find_duplicates(row: dict, others: list[dict]) -> list[int]:
    out = []
    for o in others:
        if o["event_id"] == row["event_id"]:
            continue
        if not row["date"] or o["date"] != row["date"]:
            continue
        overlap = _headline_overlap(row["headline"], o["headline"])
        same_primary = (row["primary_ticker"] is not None
                        and o["primary_ticker"] == row["primary_ticker"])
        threshold = _DUP_TOKEN_OVERLAP if same_primary else _DUP_TOKEN_OVERLAP_NO_TICKER
        if overlap >= threshold:
            out.append(o["event_id"])
    return sorted(out)


def _find_thread_anchors(row: dict, others: list[dict]) -> tuple[list[int], str]:
    """Earlier same-family rows this row continues; ('', []) when none.

    Two explainable links: (a) same primary ticker as an earlier same-family
    row; (b) a curated thread-lexicon entity shared with an earlier
    same-family row's headline.
    """
    if row["family"] == "none" or row["parsed_date"] is None:
        return [], ""
    hl = row["headline"].lower()
    anchors: list[int] = []
    basis = ""
    for o in others:
        if o["event_id"] == row["event_id"] or o["family"] != row["family"]:
            continue
        if o["parsed_date"] is None or o["parsed_date"] >= row["parsed_date"]:
            continue
        if (row["primary_ticker"] is not None
                and o["primary_ticker"] == row["primary_ticker"]):
            anchors.append(o["event_id"])
            basis = basis or (
                f"shares primary ticker {row['primary_ticker']} with earlier "
                f"same-family row(s)"
            )
            continue
        shared = [t for t in THREAD_LEXICON if t in hl and t in o["headline"].lower()]
        if shared:
            anchors.append(o["event_id"])
            basis = basis or (
                f"shares thread entity '{shared[0]}' with earlier "
                f"same-family row(s)"
            )
    return sorted(set(anchors)), basis


def _keyword_hit(headline: str, *, phrases: tuple[str, ...],
                 tokens: frozenset, stems: tuple[str, ...] = ()) -> str | None:
    """First matching keyword: phrase substring, whole-token, or token stem."""
    hl = headline.lower()
    for phrase in phrases:
        if phrase in hl:
            return phrase
    headline_tokens = _tokens(headline)  # whole words, len >= 3 ('may' included)
    for tok in sorted(tokens):
        if tok in headline_tokens:
            return tok
    for stem in stems:
        for word in headline_tokens:
            if word.startswith(stem):
                return word
    return None


def _keyword_label(headline: str) -> tuple[str | None, str]:
    hit = _keyword_hit(headline, phrases=_SCHEDULED_PHRASES,
                       tokens=_SCHEDULED_TOKENS, stems=_SCHEDULED_STEMS)
    if hit:
        return "scheduled_or_weak_anchor", (
            f"keyword '{hit}' marks a scheduled culmination, not a fresh "
            f"information shock"
        )
    hit = _keyword_hit(headline, phrases=_ANTICIPATION_PHRASES,
                       tokens=_ANTICIPATION_TOKENS)
    if hit:
        return "partial_anticipation", (
            f"keyword '{hit}' signals anticipatory / process-start wording"
        )
    hit = _keyword_hit(headline, phrases=_CLEAN_PHRASES, tokens=_CLEAN_TOKENS)
    if hit:
        return "clean_discrete_anchor", (
            f"keyword '{hit}' indicates a discrete filing/action date"
        )
    return None, ""


def classify_row(row: dict, others: list[dict]) -> dict:
    """Assign the categorical anchor label + caution fields for one row."""
    if row["parsed_date"] is None:
        label, rationale = "manual_review_needed", "no parseable event date"
        independence = "unknown_insufficient_fields"
    else:
        dups = _find_duplicates(row, others)
        if dups:
            label = "duplicate_or_deferred"
            rationale = ("same date + primary ticker + near-identical "
                         f"headline as row(s) {dups}")
            independence = f"duplicate_of_rows: {dups}"
        else:
            anchors, basis = _find_thread_anchors(row, others)
            if anchors:
                label = "continuation_or_thread_sibling"
                rationale = f"{basis} {anchors}"
                independence = f"shares_thread_with_earlier_rows: {anchors}"
            else:
                kw_label, kw_rationale = _keyword_label(row["headline"])
                if kw_label is None:
                    label = "manual_review_needed"
                    rationale = "no classification rule matched the headline wording"
                    independence = "unknown_insufficient_fields"
                else:
                    label, rationale = kw_label, kw_rationale
                    independence = "independent_no_local_thread_links"
    return {
        "event_date_quality": label,
        "anticipation_risk": _ANTICIPATION_RISK[label],
        "thread_independence": independence,
        "anchor_rationale": rationale,
        "horizon_interpretation_caution": _HORIZON_CAUTION[label],
    }


# ---------------------------------------------------------------------------
# Report composer
# ---------------------------------------------------------------------------

_LENSES = ("accepted", "staged", "all")


def build_report(
    *, db_path: str | None = None, lens: str = "all", limit: int = 0,
) -> dict[str, Any]:
    """Build the event-date quality report. Read-only."""
    if lens not in _LENSES:
        raise ValueError(f"unknown lens {lens!r}; expected one of {_LENSES}")
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    rows, synthetic = _load_rows(path) if path else ([], frozenset())

    classified_pool: list[dict] = []
    excluded_counts = {"synthetic_seed": 0, "curated_intake": 0}
    _, _, intake, _, observation = _stage_names()
    for row in rows:
        status = _corpus_status(row, synthetic)
        if status == "excluded":
            if row["stage"] == intake:
                excluded_counts["curated_intake"] += 1
            else:
                excluded_counts["synthetic_seed"] += 1
            continue
        classified_pool.append({**row, "corpus_status": status})

    # Classify against the full reviewable pool (collision partners must be
    # findable across statuses - e.g. staged 302 vs pending 315).
    events: list[dict] = []
    for row in classified_pool:
        fields = classify_row(row, classified_pool)
        events.append({
            "event_id": row["event_id"],
            "date": row["date"],
            "headline": row["headline"][:100],
            "stage": row["stage"],
            "mechanism_family": row["family"],
            "corpus_status": row["corpus_status"],
            **fields,
        })

    if lens == "accepted":
        events = [e for e in events if e["corpus_status"] in ("accepted", "curated")]
    elif lens == "staged":
        events = [e for e in events if e["corpus_status"] == "staged"]

    by_status: dict[str, dict[str, int]] = {}
    by_family: dict[str, dict[str, int]] = {}
    for e in events:
        s = by_status.setdefault(e["corpus_status"], {})
        s[e["event_date_quality"]] = s.get(e["event_date_quality"], 0) + 1
        f = by_family.setdefault(e["mechanism_family"], {})
        f[e["event_date_quality"]] = f.get(e["event_date_quality"], 0) + 1

    accepted_n = sum(1 for r in classified_pool if r["corpus_status"] == "accepted")
    curated_n = sum(1 for r in classified_pool if r["corpus_status"] == "curated")
    staged_n = sum(1 for r in classified_pool if r["corpus_status"] == "staged")

    by_id = {e["event_id"]: e for e in events}
    shortlist = []
    for sid, note in _SHORTLIST_NOTES.items():
        e = by_id.get(sid)
        if e is not None:
            shortlist.append({
                "event_id": sid,
                "event_date_quality": e["event_date_quality"],
                "corpus_status": e["corpus_status"],
                "note": note,
            })
    shortlist.sort(key=lambda x: x["event_id"])

    capped = max(int(limit), 0)
    surfaced = events[:capped] if capped else events

    return {
        "lens": lens,
        "denominators": {
            "archive_rows": len(rows),
            "accepted_coverage_denominator": accepted_n + curated_n,
            "accepted_track_record_denominator": accepted_n,
            "staged_candidate_count": staged_n,
            "excluded_counts": excluded_counts,
            "note": (
                "Accepted lens mirrors the canonical hygiene-aware corpus; "
                "staged candidates and pending rows are classified for "
                "caution but never enter accepted denominators; intake stubs "
                "and synthetic seeds are disclosed, not classified."
            ),
        },
        "label_counts": {
            "by_corpus_status": by_status,
            "by_mechanism_family": by_family,
        },
        "events": surfaced,
        "events_total": len(events),
        "shortlist_implications": shortlist,
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    d = report["denominators"]
    lines = ["Event-date quality / anticipation-risk report (read-only)", ""]
    lines.append(
        f"Lens: {report['lens']} | archive rows {d['archive_rows']} | "
        f"accepted coverage {d['accepted_coverage_denominator']} | "
        f"track-record {d['accepted_track_record_denominator']} | "
        f"staged {d['staged_candidate_count']} | excluded "
        f"synthetic={d['excluded_counts']['synthetic_seed']} "
        f"intake={d['excluded_counts']['curated_intake']}"
    )
    lines.append("")
    lines.append("Label counts by corpus status (accepted vs staged never merged):")
    for status, counts in sorted(report["label_counts"]["by_corpus_status"].items()):
        parts = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        lines.append(f"  {status:<9} {parts}")
    lines.append("")

    staged_rows = [e for e in report["events"] if e["corpus_status"] == "staged"]
    if staged_rows:
        lines.append("Staged shortlist anchors (no-paid; review staging only):")
        for e in sorted(staged_rows, key=lambda x: x["event_id"]):
            lines.append(
                f"  #{e['event_id']} {e['date']} [{e['mechanism_family']}] "
                f"{e['event_date_quality']} (risk: {e['anticipation_risk']})"
            )
            lines.append(f"      {e['anchor_rationale']}")
        lines.append("")

    weak = [e for e in report["events"]
            if e["event_date_quality"] in
            ("scheduled_or_weak_anchor", "duplicate_or_deferred",
             "continuation_or_thread_sibling")]
    lines.append(f"Weak / non-independent anchors ({len(weak)}):")
    for e in weak:
        lines.append(
            f"  #{e['event_id']} [{e['corpus_status']}] "
            f"{e['event_date_quality']} - {e['horizon_interpretation_caution']}"
        )
    if not weak:
        lines.append("  (none in this lens)")
    lines.append("")

    lines.append("How to use this before cohort analysis:")
    lines.append(
        "  Read each row's anchor label BEFORE interpreting its 1d/5d/20d "
        "windows: scheduled/weak anchors mostly measure residual surprise, "
        "thread siblings are not independent observations, and duplicates "
        "must be resolved first. A cohort built without this screen "
        "overstates its count of independent, well-anchored events."
    )
    lines.append("")
    lines.append("Non-claims:")
    for nc in report["non_claims"]:
        lines.append(f"  - {nc}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Read-only event-date quality / anticipation-risk report. "
            "Categorical anchor labels with explainable rules; a research "
            "caution layer, never proof; no DB write, no provider call, no "
            "paid analysis, no promotion."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.add_argument("--db-path", dest="db_path", default=None,
                   help="Optional events.db path; defaults to db.DB_FILE.")
    p.add_argument("--lens", choices=_LENSES, default="all",
                   help="accepted (accepted+curated) | staged | all (default).")
    p.add_argument("--limit", type=int, default=0,
                   help="Cap surfaced event entries (0 = no cap; aggregates "
                        "always cover the full lens).")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = build_report(db_path=args.db_path, lens=args.lens, limit=args.limit)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
