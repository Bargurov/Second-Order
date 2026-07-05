"""G3B comparison-mechanism classification overlay (Mission G, g0-v1).

Applies ONE deterministic, versioned comparison-mechanism rubric uniformly
across three cohorts - the 86 accepted track-record rows, the 65 G1A FOMC
historical candidates, and the 32 G1B OPEC historical candidates (183 total) -
and measures classification coverage and attrition before G4.

Core rule: SAMPLING FAMILY IS NOT COMPARISON MECHANISM. ``fomc`` / ``opec`` are
never used as mechanism labels. The rubric REUSES the frozen J1 headline rule
set (``accepted_family_overlay_report.FAMILY_RULES`` / ``classify_headline``)
verbatim - nine mechanism-family labels keyed on whole-token headline
keywords. No rule is added, removed, or specialised here; a pin test fails
loudly if the upstream rules drift so a silent change cannot redefine
``g3-comparison-taxonomy-v1``.

One comparable input surface per cohort (the most headline-like text each
source artifact NATIVELY carries), applied with identical rules:

* accepted 86 : events.db ``headline`` (the exact field the J1 overlay uses),
  loaded read-only with the same AV3 loader; stored ``mechanism_family``,
  ``market_tickers``, and ``revisit_snapshots`` are dropped at the boundary
  and never used as classification keys;
* G1A 65      : the "concise policy action from source" cell;
* G1B 32      : the "title / decision (concise)" cell.

No cohort's text is enriched or substituted. Re-sourcing richer historical
text (e.g. native news headlines for the historical events) is the FORBIDDEN
rescue named in the honesty rule and is not done. Classification uses no
market data, outcome, or state field; it never writes the archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from scripts import accepted_family_overlay_report as O  # noqa: E402
from scripts import track_record_sensitivity_report as TR  # noqa: E402

TAXONOMY_VERSION = "g3-comparison-taxonomy-v1"
SOURCE_OVERLAY = "accepted_family_overlay_report"

REPORT_PATH = ROOT / "stats" / "G3_MECHANISM_CLASSIFICATION_ATTRITION.md"
G1A_PATH = ROOT / "stats" / "G1A_FOMC_FRAME_INVENTORY.md"
G1B_PATH = ROOT / "stats" / "G1B_OPEC_DESIGNED_RESERVOIR.md"

# The reused nine mechanism-family labels, in source order (pinned).
EXPECTED_FAMILY_LABELS = (
    "tariff",
    "sanction",
    "supply_shock",
    "ceasefire_deescalation",
    "regulation",
    "labor_inflation",
    "industrial_policy",
    "monetary_policy_or_rates",
    "geopolitical_conflict_context",
)

# Cohort identifiers.
COHORT_ACCEPTED = "accepted_track_record"
COHORT_G1A = "g1a_fomc_historical"
COHORT_G1B = "g1b_opec_historical"

SOURCE_FAMILY = {
    COHORT_ACCEPTED: "accepted_news_headline",
    COHORT_G1A: "official_fomc_statement",
    COHORT_G1B: "official_opec_record",
}
COHORT_LANE = {
    COHORT_ACCEPTED: "accepted_thesis",
    COHORT_G1A: "frame_complete_historical",
    COHORT_G1B: "designed_contrast",
}

KLASS_SINGLE = "single"
KLASS_MULTI = "multi_match"
KLASS_UNCLASSIFIED = "unclassified"

# Whitelisted persisted classified-row fields (outcome-blindness firewall):
# classification metadata ONLY - no headline text, no stored mechanism field,
# no ticker, no outcome, no state value.
G3B_ROW_FIELDS = frozenset({
    "row_key", "cohort", "lane", "source_family", "year",
    "klass", "family", "matched", "taxonomy_version",
})


# ---------------------------------------------------------------------------
# Frozen-taxonomy pin
# ---------------------------------------------------------------------------


def taxonomy_fingerprint() -> str:
    """SHA256 of a canonical serialization of the REUSED J1 rule set.

    Fingerprints the semantic rules (family label + sorted include terms and
    phrases), not the rationale prose. Any add/remove/rename upstream changes
    this digest, so the pin test fails and forces a version bump + full re-run.
    """
    parts = []
    for rule in O.FAMILY_RULES:
        terms = ",".join(sorted(rule["include_terms"]))
        phrases = ",".join(sorted(rule["include_phrases"]))
        parts.append(f"{rule['family']}|{terms}|{phrases}")
    canonical = "\n".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


PINNED_TAXONOMY_FINGERPRINT = (
    "04ff3c68d7f91a200e30ba769426bd9a053f77b33237966255f248eb2a819eaa"
)


# ---------------------------------------------------------------------------
# Pure classification (reuses the J1 classifier; text is the only key)
# ---------------------------------------------------------------------------


def classify_text(text: Optional[str]) -> list[str]:
    """Matched mechanism families for one headline-like text (J1 rules)."""
    return O.classify_headline(text)


def classify_record(*, row_key: str, cohort: str, lane: str,
                    source_family: str, year: str,
                    text: Optional[str]) -> dict[str, Any]:
    """Classify one cohort row from its text alone. No override path: the
    only classification input is ``text``; there is no family/force parameter."""
    matched = classify_text(text)
    if len(matched) == 1:
        klass, family = KLASS_SINGLE, matched[0]
    elif matched:
        klass, family = KLASS_MULTI, None
    else:
        klass, family = KLASS_UNCLASSIFIED, None
    return {
        "row_key": row_key,
        "cohort": cohort,
        "lane": lane,
        "source_family": source_family,
        "year": year,
        "klass": klass,
        "family": family,
        "matched": matched,
        "taxonomy_version": TAXONOMY_VERSION,
    }


def _accepted_row(record: Mapping[str, Any], *, event_date: str) -> dict[str, Any]:
    """Build one classified accepted row from an AV3 loader record.

    Reduces to text at the boundary: only ``event_id`` and ``headline`` are
    read. The stored ``mechanism_family``, ``market_tickers``, and
    ``revisit_snapshots`` are dropped and never used as classification keys.
    """
    return classify_record(
        row_key=f"accepted:{record['event_id']}",
        cohort=COHORT_ACCEPTED,
        lane=COHORT_LANE[COHORT_ACCEPTED],
        source_family=SOURCE_FAMILY[COHORT_ACCEPTED],
        year=(event_date or "")[:4],
        text=record.get("headline"),
    )


# ---------------------------------------------------------------------------
# Cohort input-surface loaders (read-only; text is the only classification key)
# ---------------------------------------------------------------------------

_G1A_ROW = re.compile(r"^\|\s*`fomc-policy-decision-(\d{4}-\d{2}-\d{2})`\s*\|")
_G1B_ROW = re.compile(r"^\|\s*D\d{2}\s*\|")
_BACKTICKED = re.compile(r"`([a-z0-9][a-z0-9-]+)`")


def _g1_row(*, row_key: str, cohort: str, year: str,
            text: str) -> dict[str, Any]:
    return classify_record(row_key=row_key, cohort=cohort,
                           lane=COHORT_LANE[cohort],
                           source_family=SOURCE_FAMILY[cohort],
                           year=year, text=text)


def _g1a_rows_from_lines(lines: Sequence[str]) -> list[dict[str, Any]]:
    """G1A rows keyed on the 'concise policy action from source' cell."""
    rows: list[dict[str, Any]] = []
    for line in lines:
        m = _G1A_ROW.match(line)
        if not m:
            continue
        date = m.group(1)
        cells = line.split("|")
        if len(cells) <= 5:
            continue
        text = cells[5].strip()   # concise policy action from source
        rows.append(_g1_row(row_key=f"g1a:fomc-policy-decision-{date}",
                            cohort=COHORT_G1A, year=date[:4], text=text))
    return rows


def _g1b_rows_from_lines(lines: Sequence[str]) -> list[dict[str, Any]]:
    """G1B rows keyed on the 'title / decision (concise)' cell; mirrors and
    held rows are not advanced (same rule as the G1B parser)."""
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not _G1B_ROW.match(line):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 10:
            continue
        if cells[8].lower() not in ("canonical", "none"):
            continue
        ident = _BACKTICKED.search(cells[6])
        if not ident:
            continue
        text = cells[4]           # title / decision (concise)
        rows.append(_g1_row(row_key=f"g1b:{ident.group(1)}",
                            cohort=COHORT_G1B, year=cells[2][:4], text=text))
    return rows


def load_g1a_rows() -> list[dict[str, Any]]:
    return _g1a_rows_from_lines(
        G1A_PATH.read_text(encoding="utf-8").splitlines())


def load_g1b_rows() -> list[dict[str, Any]]:
    return _g1b_rows_from_lines(
        G1B_PATH.read_text(encoding="utf-8").splitlines())


def _accepted_event_dates(path: Any, ids: Sequence[int]) -> dict[int, str]:
    """Read-only supplemental: event_date for the canonical accepted ids.

    The AV3 loader does not return event_date; this attaches it for the
    year breakdown without changing the accepted set. Reads nothing else."""
    out: dict[int, str] = {}
    if not ids:
        return out
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        conn.row_factory = sqlite3.Row
        q = ("SELECT id, event_date FROM events WHERE id IN ("
             + ",".join("?" * len(ids)) + ")")
        for r in conn.execute(q, list(ids)).fetchall():
            out[r["id"]] = r["event_date"] or ""
    except sqlite3.Error:
        return out
    finally:
        conn.close()
    return out


def load_accepted_rows(db_path: Any = None) -> list[dict[str, Any]]:
    """The 86 accepted track-record rows, classified on the `headline` field.

    Reuses the AV3 loader for the canonical accepted set (read-only), then
    reduces to text at the boundary: only event_id + headline flow into
    classification; stored mechanism/ticker/revisit fields are dropped."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    records, _ = TR._load_accepted_records(path)
    dates = _accepted_event_dates(path, [r["event_id"] for r in records])
    return [_accepted_row(r, event_date=dates.get(r["event_id"], ""))
            for r in records]


def run_overlay(db_path: Any = None) -> list[dict[str, Any]]:
    """Classify all 183 rows across the three cohorts under one rubric."""
    return (load_accepted_rows(db_path)
            + load_g1a_rows()
            + load_g1b_rows())


def reconcile(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Cohort reconciliation. Raises on a duplicate row key; otherwise returns
    per-cohort and total counts (expected 86 + 65 + 32 = 183)."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["cohort"]] = counts.get(r["cohort"], 0) + 1
    total = len(rows)
    unique = len({r["row_key"] for r in rows})
    if unique != total:
        raise ValueError(f"duplicate row keys: {total} rows, {unique} unique")
    return {
        "accepted": counts.get(COHORT_ACCEPTED, 0),
        "g1a": counts.get(COHORT_G1A, 0),
        "g1b": counts.get(COHORT_G1B, 0),
        "total": total,
        "unique": unique,
    }


# ---------------------------------------------------------------------------
# Attrition summary (pure)
# ---------------------------------------------------------------------------


def _coverage(single: int, multi: int, n: int) -> float:
    return (single + multi) / n if n else 0.0


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Classification coverage and attrition by cohort / source family / year.
    Pure; reads only classification labels, never any outcome or state value."""
    per_cohort: dict[str, dict[str, Any]] = {}
    per_sf: dict[str, dict[str, int]] = {}
    per_cohort_year: dict[str, dict[str, dict[str, int]]] = {}
    totals = {"single": 0, "multi": 0, "unclassified": 0}

    key = {"single": "single", "multi_match": "multi",
           "unclassified": "unclassified"}
    for r in rows:
        c, sf, yr = r["cohort"], r["source_family"], r["year"]
        k = key[r["klass"]]
        pc = per_cohort.setdefault(
            c, {"n": 0, "single": 0, "multi": 0, "unclassified": 0,
                "families": {}})
        pc["n"] += 1
        pc[k] += 1
        if r["klass"] == KLASS_SINGLE and r["family"]:
            pc["families"][r["family"]] = pc["families"].get(r["family"], 0) + 1
        ps = per_sf.setdefault(
            sf, {"n": 0, "single": 0, "multi": 0, "unclassified": 0})
        ps["n"] += 1
        ps[k] += 1
        cy = per_cohort_year.setdefault(c, {}).setdefault(
            yr, {"n": 0, "classified": 0})
        cy["n"] += 1
        if k in ("single", "multi"):
            cy["classified"] += 1
        totals[k] += 1

    for pc in per_cohort.values():
        pc["coverage"] = _coverage(pc["single"], pc["multi"], pc["n"])
        pc["families"] = dict(sorted(pc["families"].items()))
    for ps in per_sf.values():
        ps["coverage"] = _coverage(ps["single"], ps["multi"], ps["n"])
    for years in per_cohort_year.values():
        for cy in years.values():
            cy["coverage"] = cy["classified"] / cy["n"] if cy["n"] else 0.0

    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "n": len(rows),
        "totals": totals,
        "per_cohort": dict(sorted(per_cohort.items())),
        "per_source_family": dict(sorted(per_sf.items())),
        "per_cohort_year": {c: dict(sorted(y.items()))
                            for c, y in sorted(per_cohort_year.items())},
        "differential": {
            "coverage": {c: per_cohort[c]["coverage"]
                         for c in sorted(per_cohort)},
        },
    }


# ---------------------------------------------------------------------------
# Deterministic, timestamp-free report render
# ---------------------------------------------------------------------------


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _year_span(summary: Mapping[str, Any],
               cohorts: Sequence[str]) -> tuple[Optional[str], Optional[str]]:
    years: set[str] = set()
    for c in cohorts:
        years |= set(summary["per_cohort_year"].get(c, {}))
    if not years:
        return None, None
    return min(years), max(years)


def _span_str(lo: Optional[str], hi: Optional[str]) -> str:
    if lo is None:
        return "n/a"
    return lo if lo == hi else f"{lo}-{hi}"


_COHORT_LABEL = {
    COHORT_ACCEPTED: "accepted track-record (86)",
    COHORT_G1A: "G1A FOMC historical (65)",
    COHORT_G1B: "G1B OPEC historical (32)",
}


def render_report(summary: Mapping[str, Any], *,
                  meta: Mapping[str, Any]) -> str:
    """Deterministic markdown for the tracked attrition report.

    Timestamp-free: provenance is the input sources (events.db content hash +
    the two tracked G ledgers) and the pinned taxonomy fingerprint, so the
    report regenerates byte-identically from unchanged inputs."""
    pc = summary["per_cohort"]
    tot = summary["totals"]

    def cov(c):
        return pc[c]["coverage"] if c in pc else 0.0

    acc_lo, acc_hi = _year_span(summary, [COHORT_ACCEPTED])
    hist_lo, hist_hi = _year_span(summary, [COHORT_G1A, COHORT_G1B])
    acc_span, hist_span = _span_str(acc_lo, acc_hi), _span_str(hist_lo, hist_hi)
    disjoint = bool(acc_lo and hist_lo
                    and (acc_lo > hist_hi or acc_hi < hist_lo))
    if disjoint:
        _time_caveat = (
            f"The accepted rows fall in {acc_span} while the historical rows "
            f"span {hist_span}, so the two cohorts are temporally disjoint. "
            "Because the accepted and historical cohorts are temporally "
            "disjoint, source-register effects cannot be cleanly isolated from "
            "calendar-time language drift; the finding is an input-surface "
            "register mismatch strongly consistent with the data, not a claim "
            "that register is perfectly isolated from time.")
    else:
        _time_caveat = (
            f"The accepted rows fall in {acc_span} and the historical rows "
            f"span {hist_span}; the cohorts overlap in calendar time, so "
            "register and calendar-time language drift cannot be separately "
            "attributed from this comparison alone.")

    L: list[str] = [
        "# G3 mechanism-classification attrition (Mission G, g0-v1)",
        "",
        "## Headline finding",
        "",
        "Applying one deterministic comparison-mechanism rubric "
        f"(`{TAXONOMY_VERSION}`) uniformly across all three cohorts, "
        "classification coverage COLLAPSES for the sampling-family historical "
        "candidates relative to the accepted track record:",
        "",
        f"- accepted track-record (news headlines): {_pct(cov(COHORT_ACCEPTED))} "
        "classified",
        f"- G1A FOMC historical (official policy-action titles): "
        f"{_pct(cov(COHORT_G1A))} classified",
        f"- G1B OPEC historical (official decision titles): "
        f"{_pct(cov(COHORT_G1B))} classified",
        "",
        "This near-total differential loss reflects the SOURCE REGISTER of the "
        "text each cohort natively carries - concise official policy-action "
        "and decision titles ('Maintain target range at 1.25-1.50 percent'; "
        "'1.2 mb/d joint production adjustment') do not contain the "
        "news-headline vocabulary the rubric keys on ('federal reserve', "
        "'interest rate', 'oil', 'crude') - NOT the events' mechanisms. FOMC "
        "decisions are monetary events and OPEC decisions are supply events "
        "regardless; the collapse is a comparability property of the input "
        "text, not a statement about the events.",
        "",
        "The collapse is strongly consistent with, and directly explained by, "
        "input-surface register mismatch. " + _time_caveat,
        "",
        "The honest consequence for G4: mechanism classification via this "
        "headline rubric is NOT a comparable axis across the accepted corpus "
        "and the sampling-family historical candidates. Their input surfaces "
        "are incommensurable source registers. This report sets no G4 warning "
        "threshold; it records the comparability finding.",
        "",
        "## Method (one rubric, one native surface per cohort)",
        "",
        "SAMPLING FAMILY IS NOT COMPARISON MECHANISM: `fomc` / `opec` are "
        "never used as mechanism labels. The rubric reuses the frozen J1 "
        f"headline rule set verbatim (module `{meta.get('source_overlay')}`, "
        "nine mechanism labels: tariff, sanction, supply_shock, "
        "ceasefire_deescalation, regulation, labor_inflation, "
        "industrial_policy, monetary_policy_or_rates, "
        "geopolitical_conflict_context). Taxonomy fingerprint "
        f"`{meta.get('taxonomy_fingerprint')}` is pinned; any rule change fails "
        "a test and requires a version bump plus a full re-run. Classification "
        "is a pure function of one normalized headline-like text field; stored "
        "archive mechanism fields are never used as classification keys.",
        "",
        "Each cohort is classified on the most headline-like text its OWN "
        "source artifact natively carries: the accepted rows on the events.db "
        "`headline` field (the exact field the J1 overlay uses); G1A on the "
        "'concise policy action from source' cell; G1B on the 'title / "
        "decision (concise)' cell. No cohort's text was enriched or "
        "substituted. Re-sourcing richer historical text (for example native "
        "news headlines for the historical events) would be the FORBIDDEN "
        "rescue named in the honesty rule; the accepted 86 cannot be "
        "re-sourced either. Classifying each cohort on its own native surface "
        "is the only method-symmetric option.",
        "",
        "## 183-row classification split",
        "",
        "| cohort | N | single | multi-match | unclassified | coverage |",
        "|---|---|---|---|---|---|",
    ]
    for c in (COHORT_ACCEPTED, COHORT_G1A, COHORT_G1B):
        b = pc.get(c, {"n": 0, "single": 0, "multi": 0, "unclassified": 0,
                       "coverage": 0.0})
        L.append(f"| {_COHORT_LABEL[c]} | {b['n']} | {b['single']} | "
                 f"{b['multi']} | {b['unclassified']} | {_pct(b['coverage'])} |")
    L.append(f"| **total** | {summary['n']} | {tot['single']} | "
             f"{tot['multi']} | {tot['unclassified']} | "
             f"{_pct(_coverage(tot['single'], tot['multi'], summary['n']))} |")

    L += ["", "## Coverage by source family", "",
          "| source family | N | classified | coverage |", "|---|---|---|---|"]
    for sf, b in summary["per_source_family"].items():
        L.append(f"| {sf} | {b['n']} | {b['single'] + b['multi']} | "
                 f"{_pct(b['coverage'])} |")

    L += ["", "## Coverage by calendar year (per cohort)", ""]
    for c in (COHORT_ACCEPTED, COHORT_G1A, COHORT_G1B):
        years = summary["per_cohort_year"].get(c, {})
        if not years:
            continue
        L.append(f"- {_COHORT_LABEL[c]}: "
                 + ", ".join(f"{yr} {cy['classified']}/{cy['n']} "
                             f"({_pct(cy['coverage'])})"
                             for yr, cy in years.items()))

    L += ["", "## Single-family distribution (per cohort)", ""]
    for c in (COHORT_ACCEPTED, COHORT_G1A, COHORT_G1B):
        fams = pc.get(c, {}).get("families", {})
        body = (", ".join(f"{f}:{n}" for f, n in fams.items())
                if fams else "(none)")
        L.append(f"- {_COHORT_LABEL[c]}: {body}")

    L += [
        "",
        "## Differential classification attrition",
        "",
        f"- accepted vs FOMC historical: {_pct(cov(COHORT_ACCEPTED))} vs "
        f"{_pct(cov(COHORT_G1A))} classified",
        f"- accepted vs OPEC historical: {_pct(cov(COHORT_ACCEPTED))} vs "
        f"{_pct(cov(COHORT_G1B))} classified",
        f"- FOMC vs OPEC historical: {_pct(cov(COHORT_G1A))} vs "
        f"{_pct(cov(COHORT_G1B))} classified",
    ]

    L += [
        "",
        "## Point-in-time state coverage (where structurally possible)",
        "",
        "State coverage is structurally defined only for the 97 historical "
        "candidates (the G2 substrate: four state dimensions 97/97, "
        "credit_hy_oas 36/97). The accepted 86 have no G-state substrate, so "
        "the axis is not applicable to them. Because historical classification "
        "coverage is near zero regardless of state availability, the two axes "
        "are independent: point-in-time state availability does not rescue "
        "mechanism classification, and no further cross-tabulation is "
        "meaningful.",
        "",
        "## Non-claims and firewall",
        "",
        "Overlay-only: no stored archive field is rewritten, no row is "
        "promoted, and no DB is mutated. Classification uses no market data, "
        "no outcome, and no state value; the persisted rows carry only "
        "classification metadata (cohort, lane, source family, year, class, "
        "matched labels) - no absolute return, abnormal return, SAR, CAR, "
        "sector-relative return, sign, direction, magnitude, or outcome label, "
        "enforced by a tested field whitelist. This is a coverage-comparability "
        "measurement for G4, not a mechanism-performance or prevalence claim, "
        "and not a trading or recommendation surface.",
        "",
        "## Provenance and reproduction",
        "",
        f"- taxonomy: `{TAXONOMY_VERSION}`, fingerprint "
        f"`{meta.get('taxonomy_fingerprint')}` (pinned to the reused "
        f"`{meta.get('source_overlay')}` rule set)",
        f"- accepted set: events.db (SHA256 `{meta.get('events_db_sha256')}`), "
        "accepted track-record loader (read-only)",
        "- historical sets: `stats/G1A_FOMC_FRAME_INVENTORY.md` and "
        "`stats/G1B_OPEC_DESIGNED_RESERVOIR.md` (tracked ledgers)",
        "",
        "```",
        "python scripts/g3_mechanism_classification.py --classify",
        "python scripts/g3_mechanism_classification.py --emit-report",
        "python -m unittest tests.test_g3_mechanism_classification",
        "```",
    ]
    return "\n".join(L) + "\n"


def emit_report(*, db_path: Any = None) -> dict[str, Any]:
    """Run the 183-row overlay and write the tracked attrition report."""
    rows = run_overlay(db_path)
    reconcile(rows)  # loud on duplicate keys
    summary = summarize(rows)
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    sha = None
    try:
        p = Path(path)
        if p.exists():
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
    except (OSError, TypeError):
        pass
    meta = {"taxonomy_fingerprint": taxonomy_fingerprint(),
            "source_overlay": SOURCE_OVERLAY, "events_db_sha256": sha}
    REPORT_PATH.write_text(render_report(summary, meta=meta),
                           encoding="utf-8", newline="\n")
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="G3B comparison-mechanism classification overlay "
                    "(read-only; no DB mutation).")
    parser.add_argument("--classify", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--emit-report", action="store_true")
    args = parser.parse_args(argv)

    if args.emit_report:
        summary = emit_report()
        print(f"report -> {REPORT_PATH.relative_to(ROOT)}")
        args.classify = args.classify or not args.json
    if args.classify:
        rows = run_overlay()
        rec = reconcile(rows)
        summary = summarize(rows)
        if args.json:
            print(json.dumps(summary, indent=1, sort_keys=True))
        else:
            print(f"reconcile: {rec}")
            for c, b in summary["per_cohort"].items():
                print(f"  {c}: n={b['n']} single={b['single']} "
                      f"multi={b['multi']} unclassified={b['unclassified']} "
                      f"coverage={b['coverage'] * 100:.1f}%")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
