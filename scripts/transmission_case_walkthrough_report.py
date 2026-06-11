#!/usr/bin/env python3
"""Read-only representative transmission-case walkthrough report.

For a small, deterministic, outcome-diverse set of accepted thesis rows, this
report renders the full research chain a reviewer wants to read end to end:

    event -> what changed -> mechanism / transmission -> named assets ->
    1d / 5d / 20d reaction -> event-study (AR/SAR/CAR) readout if available ->
    event-date-quality caveat -> track-record outcome / scoring-sensitivity
    caveat -> honest non-claims.

It is a backend research artifact, not a frontend change and not a trading
surface. It REUSES existing local layers and rebuilds none of them:

  * accepted rows + denominator 86 -> ``_load_accepted_records`` (the same
    loader J1/L1 use);
  * family-overlay label -> J1's ``classify_headline``;
  * event-date-quality caveat -> ``event_date_quality_report.build_report``;
  * track-record outcome + scoring sensitivity ->
    ``stats.track_record_scoring`` (any_support / majority / strict);
  * 1d/5d/20d AR/SAR/CAR -> ``event_study_coverage_report`` (the same gate as
    ``GET /events/{id}/event-study``).

Discipline (non-negotiable):

  * **Deterministic, outcome-diverse selection.** The set is forced to include
    at least one support, one contradiction, and one unresolved / data-limited
    case, then filled by family diversity. Never winners-only. No randomness.
  * **Representative, not proof.** Every case is n=1 descriptive event-window
    evidence. No single-event significance, no family-level inference, no
    performance ranking, no recommendation.
  * **Read-only.** Nothing is written to events.db; no DB labels; price_cache
    untouched; no new denominator; no event-study math changed.

Usage::

    python scripts/transmission_case_walkthrough_report.py --db-path events.db --json
    python scripts/transmission_case_walkthrough_report.py --db-path events.db
    python scripts/transmission_case_walkthrough_report.py --db-path events.db \
        --include-cases 6
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

from scripts.accepted_family_overlay_report import classify_headline  # noqa: E402
from scripts.event_date_quality_report import build_report as edq_build_report  # noqa: E402
from scripts.event_study_coverage_report import (  # noqa: E402
    summarize_event_study_coverage,
)
from scripts.track_record_sensitivity_report import (  # noqa: E402
    _load_accepted_records,
)
from stats.track_record_scoring import (  # noqa: E402
    event_evidence,
    normalize_ticker,
    score_event_under_rule,
)

DEFAULT_CASES = 6
DEFAULT_EXAMPLES = 3
_BIG = 100000

# Event-date-quality labels that flag a non-clean anchor (anticipation /
# duplicate / thread / unparseable) - preferred AGAINST during selection.
_CAVEATED_ANCHORS = frozenset({
    "duplicate_or_deferred", "continuation_or_thread_sibling",
    "manual_review_needed",
})

NON_CLAIMS: tuple[str, ...] = (
    "These cases are representative illustrations drawn from the archive, not "
    "proof of any mechanism.",
    "Each case is a single event (n=1): descriptive event-window evidence "
    "only.",
    "No single-event significance is claimed (no CI, p-value, or FDR at n=1).",
    "No family-level inference and no performance ranking across families is "
    "implied.",
    "Not a recommendation of any kind; the readouts are descriptive, not "
    "directional guidance.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor reopened.",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked.",
    "No database write occurred; the mechanism_family column and price_cache "
    "are untouched.",
    "Denominators unchanged: 94 accepted coverage / 86 accepted "
    "track-record.",
)

_CASE_NON_CLAIMS: tuple[str, ...] = (
    "n=1 descriptive event-window evidence",
    "representative, not proof of a mechanism",
    "no single-event significance",
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def family_primary(headline: str | None) -> str:
    fams = classify_headline(headline or "")
    return fams[0] if fams else "unclassified"


def outcome_bucket(tickers: Any, has_es: bool = True) -> str:
    """Map an event's directional evidence to one of four buckets."""
    outcome = score_event_under_rule(tickers, "any_support")
    if outcome == "validated":
        return "support"
    if outcome == "contradicted":
        return "contradiction"
    ev = event_evidence(tickers)
    if not has_es and ev["dir_n"] == 0:
        return "data_limited"
    return "unresolved"


def _usable(text: Any) -> bool:
    return text is not None and len(str(text).strip()) > 2


def _named_assets(row: dict) -> dict[str, Any]:
    scored = []
    for t in row.get("tickers") or []:
        if isinstance(t, dict) and t.get("symbol"):
            direction, _ = normalize_ticker(t)
            scored.append({"symbol": t["symbol"], "direction": direction})
    return {"scored": scored, "watch": _parse_assets(row.get("assets_to_watch"))}


def _parse_assets(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        s = str(raw).strip()
        if not s or s in ("[]", "{}"):
            return []
        try:
            parsed = json.loads(s)
            items = parsed if isinstance(parsed, list) else [parsed]
        except (ValueError, TypeError):
            items = [p.strip() for p in s.split(",") if p.strip()]
    out: list[str] = []
    for it in items:
        if isinstance(it, dict):
            sym = it.get("symbol") or it.get("ticker")
            if sym:
                out.append(str(sym))
        elif it:
            out.append(str(it))
    return out


def info_score(row: dict, edq_entry: dict | None, has_es: bool) -> int:
    """Deterministic informativeness: prefer rows that make a fuller, less
    anticipation-confounded walkthrough."""
    score = 2 if has_es else 0
    if _usable(row.get("mechanism_summary")):
        score += 1
    if _named_assets(row)["scored"]:
        score += 1
    if edq_entry and edq_entry.get("event_date_quality") not in _CAVEATED_ANCHORS:
        score += 1
    return score


# ---------------------------------------------------------------------------
# Deterministic selection
# ---------------------------------------------------------------------------


def select_cases(rows: list[dict], n_cases: int) -> list[dict]:
    """Pick an outcome-diverse, family-diverse set, deterministically.

    ``rows`` carry precomputed ``outcome_bucket``, ``family_primary``, and
    ``info_score``. Selection order: the three required diversity roles first
    (support, contradiction, unresolved/limited), then family-diversity fills.
    Ranking is (info_score desc, event_id asc) - fully deterministic.
    """
    n = max(int(n_cases), 0)
    selected: list[dict] = []
    used: set = set()
    used_families: set = set()

    def best(pred):
        cands = [r for r in rows
                 if r["event_id"] not in used and pred(r)]
        cands.sort(key=lambda r: (-r["info_score"], r["event_id"]))
        return cands[0] if cands else None

    def take(r, role):
        chosen = dict(r)
        chosen["case_role"] = role
        selected.append(chosen)
        used.add(r["event_id"])
        used_families.add(r.get("family_primary"))

    required = (
        (lambda r: r["outcome_bucket"] == "support", "support_case"),
        (lambda r: r["outcome_bucket"] == "contradiction", "contradiction_case"),
        (lambda r: r["outcome_bucket"] in ("unresolved", "data_limited"),
         "unresolved_or_limited_case"),
    )
    for pred, role in required:
        if len(selected) >= n:
            break
        r = best(pred)
        if r is not None:
            take(r, role)

    while len(selected) < n:
        r = best(lambda r: r.get("family_primary") not in used_families)
        if r is None:
            r = best(lambda r: True)
        if r is None:
            break
        take(r, "mechanism_diversity_case")

    return selected


# ---------------------------------------------------------------------------
# Loaders (read-only)
# ---------------------------------------------------------------------------

_EXTRA_FIELDS = (
    "event_date", "what_changed", "mechanism_summary", "transmission_chain",
    "market_note", "notes", "assets_to_watch", "beneficiaries", "losers",
    "key_falsifiers",
)


def _load_case_rows(db_path: str | None) -> list[dict]:
    records, _ = _load_accepted_records(db_path)
    by_id = {r["event_id"]: r for r in records}
    ids = list(by_id)
    extra: dict[int, dict] = {}
    if db_path and ids:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            existing = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
            sel = [f for f in _EXTRA_FIELDS if f in existing]
            idset = set(ids)
            query = (f"SELECT id, {', '.join(sel)} FROM events" if sel
                     else "SELECT id FROM events")
            for r in conn.execute(query):
                if r["id"] in idset:
                    extra[r["id"]] = {f: r[f] for f in sel}
            conn.close()
        except sqlite3.Error:
            extra = {}
    rows = []
    for eid, rec in by_id.items():
        ex = extra.get(eid, {})
        rows.append({
            "event_id": eid,
            "headline": rec["headline"],
            "tickers": rec["tickers"],
            "mechanism_family": rec.get("mechanism_family"),
            "event_date": ex.get("event_date"),
            "what_changed": ex.get("what_changed"),
            "mechanism_summary": ex.get("mechanism_summary"),
            "transmission_chain": ex.get("transmission_chain"),
            "market_note": ex.get("market_note"),
            "notes": ex.get("notes"),
            "assets_to_watch": ex.get("assets_to_watch"),
            "key_falsifiers": ex.get("key_falsifiers"),
        })
    rows.sort(key=lambda r: r["event_id"])
    return rows


def _load_event_study(db_path: str | None) -> tuple[dict, dict]:
    if not db_path:
        return {}, {}
    rep = summarize_event_study_coverage(db_path=db_path, limit=_BIG)
    available = {a["event_id"]: a for a in rep.get("available", [])}
    insufficient = {i["event_id"]: i for i in rep.get("insufficient", [])}
    return available, insufficient


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _clip(text: Any, n: int = 280) -> str:
    t = str(text or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 3] + "..."


def _safe(text: str) -> str:
    return str(text or "").encode("cp1252", "replace").decode("cp1252")


def _horizon(ph_by: dict, h: int) -> dict | None:
    entry = ph_by.get(h)
    if not entry:
        return None
    return {"abnormal_return": entry.get("abnormal_return"),
            "sar": entry.get("sar"), "car": entry.get("car")}


def _reaction_readout(eid: int, es_available: dict,
                      es_insufficient: dict) -> dict[str, Any]:
    av = es_available.get(eid)
    if av:
        ph_by = {h.get("horizon"): h for h in av.get("per_horizon") or []}
        return {
            "horizon_1d": _horizon(ph_by, 1),
            "horizon_5d": _horizon(ph_by, 5),
            "horizon_20d": _horizon(ph_by, 20),
            "ar_sar_car_if_available": True,
            "primary_ticker": av.get("primary_ticker"),
            "benchmark": av.get("benchmark"),
            "missingness_note": "",
        }
    ins = es_insufficient.get(eid)
    note = ("event-study not computable: "
            + ", ".join(ins.get("blocking_reasons") or [])) if ins else (
        "event-study point estimates not available for this row")
    return {
        "horizon_1d": None, "horizon_5d": None, "horizon_20d": None,
        "ar_sar_car_if_available": False, "missingness_note": note,
    }


def _sensitivity_caveat(tickers: Any) -> dict[str, Any]:
    return {
        "any_support": score_event_under_rule(tickers, "any_support"),
        "majority": score_event_under_rule(tickers, "majority"),
        "all_support_strict": score_event_under_rule(tickers,
                                                     "all_support_strict"),
        "note": ("The track-record label depends on the scoring rule; shown "
                 "across rules as a sensitivity caveat. No rule is claimed "
                 "correct; the canonical headline rule is any_support."),
    }


_CASE_READ = {
    "support": (
        "Under the generous any-support rule, at least one named asset moved "
        "with the thesis direction across the event window. Descriptive "
        "event-window evidence at n=1, not proof of a mechanism."),
    "contradiction": (
        "The named assets moved against the thesis direction over the window. "
        "Included deliberately as a counterweight so the set is never "
        "winners-only. Descriptive at n=1, not proof of a mechanism."),
    "unresolved": (
        "The window neither supports nor contradicts the thesis under the "
        "any-support rule. An honest non-result at n=1, not proof of a "
        "mechanism."),
    "data_limited": (
        "Insufficient local directional evidence and no computable "
        "event-study window; surfaced as a data limitation rather than a "
        "result."),
}


def _falsifier_or_limit(row: dict) -> str:
    kf = row.get("key_falsifiers")
    if _usable(kf) and str(kf).strip() not in ("[]", "{}"):
        return _clip(kf, 200)
    return ("Standing limit: n=1 point estimate vs SPY; event-window overlap, "
            "anticipation, and single-name exposure caveats apply.")


def _assemble_case(case: dict, edq_by: dict, es_available: dict,
                   es_insufficient: dict) -> dict[str, Any]:
    eid = case["event_id"]
    edq = edq_by.get(eid, {})
    return {
        "event_id": eid,
        "headline": _clip(case.get("headline"), 160),
        "event_date": case.get("event_date"),
        "family_overlay": case.get("family_overlay"),
        "track_record_outcome": case.get("track_record_outcome"),
        "outcome_bucket": case["outcome_bucket"],
        "case_role": case["case_role"],
        "what_changed": _clip(case.get("what_changed")),
        "mechanism_summary": _clip(case.get("mechanism_summary")),
        "transmission_chain": _clip(case.get("transmission_chain"), 200),
        "named_assets": _named_assets(case),
        "event_date_quality": edq.get("event_date_quality", "unavailable"),
        "event_date_caveat": edq.get(
            "horizon_interpretation_caution",
            "event-date quality unavailable for this row"),
        "reaction_readout": _reaction_readout(eid, es_available,
                                              es_insufficient),
        "sensitivity_or_scoring_caveat": _sensitivity_caveat(
            case.get("tickers") or []),
        "case_read": _CASE_READ.get(case["outcome_bucket"], ""),
        "falsifier_or_limit": _falsifier_or_limit(case),
        "non_claims": list(_CASE_NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Sector backdrop (O2) - sourced from O1, never recomputed here
# ---------------------------------------------------------------------------

_SECTOR_SPY_NOTE = (
    "Abnormal return remains SPY-relative (canonical); the sector move is the "
    "ETF's own raw window change, descriptive backdrop only.")
_SECTOR_BACKDROP_INTERP = (
    "Sector ETF move is descriptive backdrop only; SPY remains canonical; no "
    "sector-relative abnormal return is computed.")


def _sector_backdrop(o1_row: dict | None) -> dict[str, Any]:
    """Echo O1's per-row sector-availability fields (sourced, not recomputed).

    The fields come verbatim from
    ``sector_baseline_availability_report.build_report``; O2 only adds the
    interpretation note. No sector-relative abnormal return is ever produced.
    """
    if o1_row is None:
        unavail = {f"horizon_{h}d": {"available": False,
                                     "reason": "not_in_sector_report"}
                   for h in (1, 5, 20)}
        return {
            "suggested_sector_etf": None,
            "suggestion_confidence": "none",
            "suggestion_reason": "not_in_sector_report",
            "availability": unavail,
            "sector_raw_moves": {f"horizon_{h}d": None for h in (1, 5, 20)},
            "missingness_note": "No sector-baseline row for this event_id.",
            "spy_canonical_note": _SECTOR_SPY_NOTE,
            "interpretation_note": _SECTOR_BACKDROP_INTERP,
        }
    return {
        "suggested_sector_etf": o1_row.get("suggested_sector_etf"),
        "suggestion_confidence": o1_row.get("suggestion_confidence"),
        "suggestion_reason": o1_row.get("suggestion_reason"),
        "availability": o1_row.get("availability"),
        "sector_raw_moves": o1_row.get("sector_raw_moves"),
        "missingness_note": o1_row.get("missingness_note", ""),
        "spy_canonical_note": o1_row.get("spy_canonical_note",
                                        _SECTOR_SPY_NOTE),
        "interpretation_note": _SECTOR_BACKDROP_INTERP,
    }


def _load_sector_by_id(db_path: str | None) -> dict[int, dict]:
    """Reuse O1's report read-only. ``walkthrough_case_ids=[]`` breaks the
    N1<->O1 cycle (O1's default path would otherwise call build_walkthrough)."""
    try:
        from scripts.sector_baseline_availability_report import (
            build_report as _sector_build_report,
        )
        rep = _sector_build_report(db_path=db_path, walkthrough_case_ids=[])
        return {r["event_id"]: r for r in rep.get("rows", [])}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Report composer
# ---------------------------------------------------------------------------


def build_walkthrough(db_path: str | None = None, *,
                      rows: list[dict] | None = None,
                      edq_report: dict | None = None,
                      es_available: dict | None = None,
                      es_insufficient: dict | None = None,
                      sector_by_id: dict | None = None,
                      n_cases: int = DEFAULT_CASES,
                      include_examples: int = DEFAULT_EXAMPLES) -> dict[str, Any]:
    """Build the representative-case walkthrough. Read-only; reuses J1/EDQ/
    track-record/event-study layers (and O1 sector backdrop) and writes
    nothing."""
    if rows is None:
        rows = _load_case_rows(db_path)
    if edq_report is None:
        edq_report = edq_build_report(db_path=db_path, lens="accepted", limit=0)
    if es_available is None or es_insufficient is None:
        av, ins = _load_event_study(db_path)
        es_available = av if es_available is None else es_available
        es_insufficient = ins if es_insufficient is None else es_insufficient

    edq_by = {e["event_id"]: e for e in edq_report.get("events", [])}

    # Enrich every accepted row deterministically.
    enriched = []
    for row in rows:
        eid = row["event_id"]
        has_es = eid in es_available
        bucket = outcome_bucket(row.get("tickers") or [], has_es)
        fams = classify_headline(row.get("headline") or "")
        enriched.append({
            **row,
            "family_overlay": sorted(fams),
            "family_primary": fams[0] if fams else "unclassified",
            "outcome_bucket": bucket,
            "track_record_outcome": score_event_under_rule(
                row.get("tickers") or [], "any_support"),
            "info_score": info_score(row, edq_by.get(eid), has_es),
        })

    selected = select_cases(enriched, n_cases)
    cases = [_assemble_case(c, edq_by, es_available, es_insufficient)
             for c in selected]

    # O2: attach O1's sector backdrop to each selected case (read-only). The
    # SPY reaction_readout above is the canonical layer and is unchanged.
    if sector_by_id is None:
        sector_by_id = _load_sector_by_id(db_path)
    for c in cases:
        c["sector_backdrop"] = _sector_backdrop(sector_by_id.get(c["event_id"]))

    sup = sum(1 for c in cases if c["outcome_bucket"] == "support")
    con = sum(1 for c in cases if c["outcome_bucket"] == "contradiction")
    unl = sum(1 for c in cases
              if c["outcome_bucket"] in ("unresolved", "data_limited"))
    diversity = {
        "support_count": sup,
        "contradiction_count": con,
        "unresolved_or_limited_count": unl,
        "passes": sup >= 1 and con >= 1 and unl >= 1,
    }

    missingness = {
        "cases_missing_event_study": sum(
            1 for c in cases
            if not c["reaction_readout"]["ar_sar_car_if_available"]),
        "cases_missing_assets": sum(
            1 for c in cases
            if not c["named_assets"]["scored"] and not c["named_assets"]["watch"]),
        "cases_missing_mechanism_text": sum(
            1 for c in cases if not _usable(c["mechanism_summary"])),
    }

    od = edq_report.get("denominators", {})
    denoms = {
        "archive_rows": od.get("archive_rows"),
        "accepted_coverage_denominator": od.get("accepted_coverage_denominator"),
        "accepted_track_record_denominator":
            od.get("accepted_track_record_denominator"),
        "staged_candidate_count": od.get("staged_candidate_count"),
    }

    return {
        "denominators": denoms,
        "selection_policy": {
            "deterministic": True,
            "accepted_only": True,
            "outcome_diversity_required": True,
            "family_diversity_preferred": True,
            "winners_only_guard": True,
            "no_new_denominator": True,
            "ranking": "info_score desc, then event_id asc",
            "n_cases": n_cases,
        },
        "selected_cases": cases,
        "outcome_diversity_check": diversity,
        "missingness_summary": missingness,
        "taxonomy_lessons": _taxonomy_lessons(diversity),
        "non_claims": list(NON_CLAIMS),
    }


def _taxonomy_lessons(diversity: dict) -> dict[str, list[str]]:
    return {
        "what_cases_show": [
            "Each case is a full, recomputable transmission walkthrough: what "
            "changed, the mechanism / transmission, the named assets, and how "
            "those assets actually moved over the 1d / 5d / 20d window.",
            "The set is forced outcome-diverse - at least one support, one "
            "contradiction, and one unresolved / data-limited case - so it "
            "reads as an honest cross-section, not a winners reel "
            f"(support {diversity['support_count']} / contradiction "
            f"{diversity['contradiction_count']} / unresolved-or-limited "
            f"{diversity['unresolved_or_limited_count']}).",
        ],
        "what_cases_do_not_show": [
            "No case is statistical evidence: each is n=1, with no CI, "
            "p-value, or FDR.",
            "No family-level inference: a single case does not characterise "
            "its mechanism family, and the cases are not compared for "
            "performance.",
            "Event-study readouts, where present, are point estimates vs SPY; "
            "where absent, the missingness is surfaced, not hidden.",
        ],
        "why_representative_cases_are_not_proof": [
            "Representative cases are chosen to be legible and honest, not to "
            "demonstrate a result; the scoring-sensitivity and "
            "event-date-quality caveats on each case show how fragile a "
            "single-event read is.",
            "A clean window can still reflect anticipation, overlap with "
            "neighbouring events, or single-name idiosyncrasy - the caveats "
            "are part of the case, not a footnote.",
        ],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:+.4f}"
    return str(v)


def _h_line(label: str, h: dict | None) -> str:
    if not h:
        return f"      {label}: (no estimate)"
    return (f"      {label}: AR={_fmt(h.get('abnormal_return'))} "
            f"SAR={_fmt(h.get('sar'))} CAR={_fmt(h.get('car'))}")


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("Representative transmission-case walkthrough (read-only)")
    add("=" * 60)
    d = report["denominators"]
    add(f"Denominators: archive {d['archive_rows']} | coverage "
        f"{d['accepted_coverage_denominator']} | track record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']}")
    add("Representative, not proof. Each case is n=1 descriptive "
        "event-window evidence.")
    add("")

    chk = report["outcome_diversity_check"]
    add(f"Selected cases ({len(report['selected_cases'])}) - outcome "
        f"diversity: support {chk['support_count']} / contradiction "
        f"{chk['contradiction_count']} / unresolved-or-limited "
        f"{chk['unresolved_or_limited_count']} -> passes={chk['passes']}")
    add("")

    for c in report["selected_cases"]:
        assets = ", ".join(a["symbol"] for a in c["named_assets"]["scored"]) \
            or "(none named)"
        add(f"[{c['event_id']}] {c['case_role']} | {c['outcome_bucket']} | "
            f"{'+'.join(c['family_overlay']) or 'unclassified'} | "
            f"track_record={c['track_record_outcome']}")
        add(f"  {_safe(_clip(c['headline'], 96))}  ({c['event_date']})")
        add(f"  what changed: {_safe(_clip(c['what_changed'], 130))}")
        add(f"  mechanism:    {_safe(_clip(c['mechanism_summary'], 130))}")
        add(f"  transmission: {_safe(_clip(c['transmission_chain'], 110))}")
        add(f"  named assets: {_safe(assets)}")
        rr = c["reaction_readout"]
        add("  reaction readout (point estimates vs SPY, n=1):")
        add(_h_line("1d ", rr["horizon_1d"]))
        add(_h_line("5d ", rr["horizon_5d"]))
        add(_h_line("20d", rr["horizon_20d"]))
        if rr["missingness_note"]:
            add(f"      missing: {_safe(rr['missingness_note'])}")
        sb = c["sector_backdrop"]
        add(f"  sector backdrop ({sb['suggested_sector_etf'] or 'n/a'}/"
            f"{sb['suggestion_confidence']}, descriptive only, not "
            "sector-relative AR):")
        for hl, hk in (("1d ", "horizon_1d"), ("5d ", "horizon_5d"),
                       ("20d", "horizon_20d")):
            cell = sb["availability"][hk]
            mv = sb["sector_raw_moves"][hk]
            val = _fmt(mv) if cell["available"] else f"n/a ({cell['reason']})"
            add(f"      {hl}: {val}")
        if sb["missingness_note"]:
            add(f"      sector note: {_safe(_clip(sb['missingness_note'], 80))}")
        add(f"  event-date quality: {c['event_date_quality']} - "
            f"{_safe(_clip(c['event_date_caveat'], 90))}")
        sc = c["sensitivity_or_scoring_caveat"]
        add(f"  scoring sensitivity: any_support={sc['any_support']} | "
            f"majority={sc['majority']} | strict={sc['all_support_strict']}")
        add(f"  read: {_safe(c['case_read'])}")
        add(f"  limit: {_safe(c['falsifier_or_limit'])}")
        add("")

    ms = report["missingness_summary"]
    add("Missingness summary:")
    add(f"  cases missing event-study: {ms['cases_missing_event_study']} | "
        f"missing assets: {ms['cases_missing_assets']} | missing mechanism "
        f"text: {ms['cases_missing_mechanism_text']}")
    add("")

    add("Non-claims:")
    for item in report["non_claims"]:
        add(f"  - {_safe(item)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only representative transmission-case walkthrough.")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--include-cases", type=int, default=DEFAULT_CASES)
    parser.add_argument("--include-examples", type=int, default=DEFAULT_EXAMPLES)
    args = parser.parse_args(argv)

    report = build_walkthrough(db_path=args.db_path,
                               n_cases=args.include_cases,
                               include_examples=args.include_examples)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
