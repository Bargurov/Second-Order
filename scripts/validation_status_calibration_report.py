"""validation_status_calibration_report.py

READ-ONLY empirical calibration of the production event-level decision
rule ``validation_status.score_validation_status`` (the
``validation_status_v2`` label) against the real event archive.

What this does
--------------
It answers one question: does the current simple-majority rule provide a
defensible *minimum evidence floor*, or does it assign decisive labels
(``validated`` / ``contradicted``) from too few directional observations?
It does **not** test whether the economic theses are true, and it changes
no production behaviour or label. It reuses the production scorer verbatim
for the "current" column so the report reflects real behaviour, and
evaluates a small, documented set of candidate re-labelings as pure
functions layered on the same per-event evidence counts.

Safety boundary
---------------
* reads from a caller-supplied ``--db-path`` over a ``mode=ro`` connection;
* never mutates the database, never calls a provider, never touches the
  network, never triggers paid analysis, never refreshes prices, never
  alters a validation label;
* the accepted denominator is the established accepted-track-record gate
  (``db.NON_THESIS_STAGES`` stage exclusion + ``db.synthetic_seed_ids``),
  reproduced here so the report reconciles with the production diagnostics
  (``routes/diagnostics.py::_compute_validation_status_stats``). The
  accepted lens and the raw/analysis-stage lens are separate columns and
  are never summed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import db  # noqa: E402
from event_age_policy import classify_event_age  # noqa: E402
from validation_status import _has_thesis, score_validation_status  # noqa: E402

CONTRACT_VERSION = "validation-status-calibration-v1"
STATUS_ORDER = ("validated", "contradicted", "unresolved", "pending")
DECISIVE = ("validated", "contradicted")


# ---------------------------------------------------------------------------
# Eligibility gate (established accepted-track-record denominator)
# ---------------------------------------------------------------------------


def classify_eligibility(event: dict, *, synthetic_ids, non_thesis_stages) -> str:
    """Return the accepted/excluded class for one event.

    Stage is checked before synthetic membership so a row that is both a
    non-thesis stage and a synthetic seed counts once, under the stage
    reason (never double-counted).
    """
    stage = event.get("stage")
    if isinstance(stage, str) and stage.strip() in non_thesis_stages:
        return "excluded_non_thesis_stage"
    if event.get("id") in synthetic_ids:
        return "excluded_synthetic_seed"
    return "accepted"


def build_funnel(events, *, synthetic_ids, non_thesis_stages) -> dict:
    """Missingness funnel: archive == accepted + excluded-by-reason."""
    excl_stage = excl_syn = accepted = 0
    for ev in events:
        cls = classify_eligibility(
            ev, synthetic_ids=synthetic_ids, non_thesis_stages=non_thesis_stages)
        if cls == "excluded_non_thesis_stage":
            excl_stage += 1
        elif cls == "excluded_synthetic_seed":
            excl_syn += 1
        else:
            accepted += 1
    return {
        "archive_rows": len(events),
        "excluded_non_thesis_stage": excl_stage,
        "excluded_synthetic_seed": excl_syn,
        "accepted": accepted,
    }


# ---------------------------------------------------------------------------
# Per-event characterization (wraps the production scorer verbatim)
# ---------------------------------------------------------------------------


def characterize_event(event: dict, *, now: Optional[datetime] = None) -> dict:
    """Only the existing fields needed to characterize the rule per event."""
    scored = score_validation_status(event, now=now)
    counts = scored["counts"]
    age = classify_event_age(event, now=now)
    fam = event.get("mechanism_family")
    fam_key = fam.strip() if isinstance(fam, str) and fam.strip() else None
    rating = event.get("rating")
    rating_v = rating.strip() if isinstance(rating, str) and rating.strip() else None
    return {
        "event_id": event.get("id"),
        "event_date": event.get("event_date"),
        "mechanism_family": fam_key,
        "age_bucket": age["natural_bucket"],
        "age_days": age["event_age_days"],
        "total_tickers": counts["total_tickers"],
        "tagged_tickers": counts["tagged_tickers"],
        "directional": counts["directional"],
        "supporting": counts["supporting"],
        "contradicting": counts["contradicting"],
        "ratio": scored["ratio"],
        "current_status": scored["status"],
        "has_thesis": _has_thesis(event),
        "rating": rating_v,
    }


# ---------------------------------------------------------------------------
# Candidate re-labelings — pure. Every candidate holds the non-directional
# branch fixed (returns the current status unchanged) so transition matrices
# attribute changes ONLY to the evidence-floor rule, never to age logic.
# ---------------------------------------------------------------------------


def candidate_current(current_status: str, supporting: int, contradicting: int) -> str:
    """The production rule: majority; ties -> contradicted; floor of 1."""
    d = supporting + contradicting
    if d == 0:
        return current_status
    return "validated" if supporting > contradicting else "contradicted"


def candidate_min2(current_status: str, supporting: int, contradicting: int) -> str:
    """Require >= 2 directional tickers for a decisive label; else unresolved."""
    d = supporting + contradicting
    if d == 0:
        return current_status
    if d < 2:
        return "unresolved"
    return "validated" if supporting > contradicting else "contradicted"


def candidate_tie_unresolved(current_status: str, supporting: int,
                             contradicting: int) -> str:
    """Floor of 1, but a genuine tie (supports == contradicts) -> unresolved."""
    d = supporting + contradicting
    if d == 0:
        return current_status
    if supporting == contradicting:
        return "unresolved"
    return "validated" if supporting > contradicting else "contradicted"


def candidate_min2_supermajority(current_status: str, supporting: int,
                                 contradicting: int) -> str:
    """Require >= 2 directional AND a 2/3 supermajority for a decisive label."""
    d = supporting + contradicting
    if d == 0:
        return current_status
    if d < 2:
        return "unresolved"
    r = supporting / d
    if r >= 2 / 3:
        return "validated"
    if r <= 1 / 3:
        return "contradicted"
    return "unresolved"


CANDIDATES: list[dict[str, Any]] = [
    {"key": "current", "fn": candidate_current,
     "label": "Current rule (majority; ties -> contradicted; floor 1)",
     "basis": "the production rule, reproduced verbatim for the baseline column"},
    {"key": "min2", "fn": candidate_min2,
     "label": "Minimum 2 directional tickers for a decisive label",
     "basis": "grounded in the observed single-directional-ticker decisive rows"},
    {"key": "tie_unresolved", "fn": candidate_tie_unresolved,
     "label": "Ties -> unresolved (balance floor, keeps count floor of 1)",
     "basis": "grounded in the observed exact-tie (supports == contradicts) rows"},
    {"key": "min2_supermajority", "fn": candidate_min2_supermajority,
     "label": "Minimum 2 directional AND a 2/3 supermajority",
     "basis": "combines the count floor and the balance floor over observed combos"},
]


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------


def directional_count_distribution(chars) -> dict:
    out: dict[int, int] = {}
    for ch in chars:
        out[ch["directional"]] = out.get(ch["directional"], 0) + 1
    return out


def decisive_evidence_breakdown(chars) -> dict:
    """How many decisive labels rest on 1 / 2 / 3+ directional tickers."""
    by_bucket = {b: {"validated": 0, "contradicted": 0}
                 for b in ("1", "2", "3plus")}
    decisive_total = single = tie = 0
    for ch in chars:
        st = ch["current_status"]
        if st not in DECISIVE:
            continue
        decisive_total += 1
        d = ch["directional"]
        bucket = "1" if d == 1 else ("2" if d == 2 else "3plus")
        by_bucket[bucket][st] += 1
        if d == 1:
            single += 1
        if ch["supporting"] == ch["contradicting"]:
            tie += 1
    share = (single / decisive_total) if decisive_total else 0.0
    return {
        "by_bucket": by_bucket,
        "decisive_total": decisive_total,
        "single_ticker_decisive": single,
        "single_ticker_share": share,
        "tie_decisive": tie,
    }


def observed_combinations(chars) -> Counter:
    c: Counter = Counter()
    for ch in chars:
        c[(ch["supporting"], ch["contradicting"])] += 1
    return c


def status_distribution(chars) -> dict:
    out: dict[str, int] = {}
    for ch in chars:
        out[ch["current_status"]] = out.get(ch["current_status"], 0) + 1
    return out


def status_by_family(chars) -> dict:
    out: dict[str, dict[str, int]] = {}
    for ch in chars:
        fam = ch["mechanism_family"] or "none"
        bucket = out.setdefault(fam, {})
        bucket[ch["current_status"]] = bucket.get(ch["current_status"], 0) + 1
    return out


def status_by_age_bucket(chars) -> dict:
    out: dict[str, dict[str, int]] = {}
    for ch in chars:
        b = ch["age_bucket"]
        bucket = out.setdefault(b, {})
        bucket[ch["current_status"]] = bucket.get(ch["current_status"], 0) + 1
    return out


def transition_matrix(chars, candidate_fn: Callable) -> dict:
    transitions: dict[tuple, int] = {}
    changed = total = 0
    for ch in chars:
        total += 1
        frm = ch["current_status"]
        to = candidate_fn(frm, ch["supporting"], ch["contradicting"])
        transitions[(frm, to)] = transitions.get((frm, to), 0) + 1
        if frm != to:
            changed += 1
    return {"transitions": transitions, "changed": changed, "total": total}


def percentages(counts: dict, denom: int, ndigits: int = 2) -> dict:
    """Round to ``ndigits`` and force the set to sum to exactly 100 via the
    largest-remainder adjustment on the largest raw share (deterministic)."""
    if not denom:
        return {}
    raw = {k: v * 100.0 / denom for k, v in counts.items()}
    rounded = {k: round(x, ndigits) for k, x in raw.items()}
    drift = round(100.0 - sum(rounded.values()), ndigits)
    if rounded and abs(drift) >= 10 ** (-ndigits):
        kmax = max(rounded, key=lambda k: (raw[k], k))
        rounded[kmax] = round(rounded[kmax] + drift, ndigits)
    return rounded


# ---------------------------------------------------------------------------
# Ground-truth availability
# ---------------------------------------------------------------------------


def ground_truth_availability(chars) -> dict:
    """Determine what comparison targets exist. Manual ``rating`` is human
    judgement written in the same archive pass; it is never an independent
    market target for label accuracy. Event-study inference is n=1. So no
    defensible independent target exists: agreement can only be described,
    never used to call one rule 'more accurate'."""
    rated = sum(1 for ch in chars if ch.get("rating"))
    vocab = sorted({ch["rating"] for ch in chars if ch.get("rating")})
    return {
        "rating_present_count": rated,
        "rating_vocabulary": vocab,
        "independent_target_available": False,
        "note": ("manual rating is human judgement (same archive), not a market "
                 "outcome; event-study inference is n=1 with no cross-sectional "
                 "test; predictive accuracy cannot be calibrated"),
    }


# ---------------------------------------------------------------------------
# Recommendation (verdict is documented prose; the branches below are
# objective guards, pinned in tests only on clear-cut synthetic fixtures)
# ---------------------------------------------------------------------------


def recommend(metrics: dict) -> dict:
    accepted_n = int(metrics.get("accepted_n", 0) or 0)
    decisive = int(metrics.get("decisive_total", 0) or 0)
    share = float(metrics.get("single_ticker_share", 0.0) or 0.0)
    if accepted_n <= 0 or decisive <= 0:
        verdict = "UNRESOLVED — ARCHIVE NOT CALIBRATION-READY"
    elif share >= 0.5:
        # A majority of decisive labels rest on a single directional ticker:
        # the floor is genuinely too low.
        verdict = "TIGHTEN_EVIDENCE_FLOOR"
    else:
        # Most decisive labels already rest on >= 2 directional tickers: the
        # evidence floor is empirically adequate for this archive.
        verdict = "KEEP_CURRENT_RULE"
    return {"verdict": verdict}


# ---------------------------------------------------------------------------
# DB access (the only impure functions)
# ---------------------------------------------------------------------------


def _load_rows(db_path: str) -> tuple[list[dict], frozenset]:
    """Read-only decode of every archived event + the synthetic-seed set."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
        try:
            synthetic = db.synthetic_seed_ids(conn)
        except Exception:
            synthetic = frozenset()
    finally:
        conn.close()
    decoded: list[dict] = []
    for r in rows:
        try:
            ev = db._decode_event_row(r)
        except Exception:
            ev = dict(r)
        mt = ev.get("market_tickers")
        if isinstance(mt, str):
            try:
                ev["market_tickers"] = json.loads(mt or "[]")
            except (json.JSONDecodeError, TypeError):
                ev["market_tickers"] = []
        decoded.append(ev)
    return decoded, synthetic


def _sha256_file(path: str) -> Optional[str]:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def build_report(*, db_path: str, as_of: Optional[str] = None) -> dict:
    """Build the calibration report dict. Read-only; never mutates the DB."""
    now_dt: Optional[datetime] = None
    as_of_label = as_of
    if as_of:
        try:
            now_dt = datetime.strptime(as_of[:10], "%Y-%m-%d")
        except ValueError:
            now_dt = None
            as_of_label = f"{as_of} (unparsable; used wall clock)"
    if now_dt is None and not as_of:
        now_dt = datetime.now()
        as_of_label = now_dt.date().isoformat() + " (default: wall clock)"

    db_sha_before = _sha256_file(db_path)
    decoded, synthetic = _load_rows(db_path)
    db_sha_after = _sha256_file(db_path)

    non_thesis = getattr(db, "NON_THESIS_STAGES", frozenset())
    non_analysis = getattr(db, "NON_ANALYSIS_STAGES", frozenset())

    funnel = build_funnel(decoded, synthetic_ids=synthetic,
                          non_thesis_stages=non_thesis)

    # Primary lens: accepted track-record (NON_THESIS_STAGES + synthetic).
    accepted_events = [
        ev for ev in decoded
        if classify_eligibility(ev, synthetic_ids=synthetic,
                                non_thesis_stages=non_thesis) == "accepted"]
    accepted_chars = [characterize_event(ev, now=now_dt) for ev in accepted_events]

    # Secondary lens: raw analysis-stage (NON_ANALYSIS_STAGES + synthetic).
    # Kept SEPARATE from the accepted conclusions; never summed.
    raw_events = [
        ev for ev in decoded
        if not ((isinstance(ev.get("stage"), str)
                 and ev["stage"].strip() in non_analysis)
                or ev.get("id") in synthetic)]
    raw_chars = [characterize_event(ev, now=now_dt) for ev in raw_events]

    def _evidence_presence(chars) -> dict:
        return {
            "n": len(chars),
            "with_thesis": sum(1 for c in chars if c["has_thesis"]),
            "with_tickers": sum(1 for c in chars if c["total_tickers"] > 0),
            "with_directional_tags": sum(1 for c in chars if c["directional"] > 0),
            "no_directional_evidence": sum(1 for c in chars if c["directional"] == 0),
        }

    def _lens(chars, label) -> dict:
        status = status_distribution(chars)
        return {
            "n": len(chars),
            "denominator_label": label,
            "status_counts": status,
            "status_pct": percentages(status, len(chars)),
            "directional_count_distribution": directional_count_distribution(chars),
            "decisive_breakdown": decisive_evidence_breakdown(chars),
            "combinations": dict(observed_combinations(chars)),
            "by_family": status_by_family(chars),
            "by_age_bucket": status_by_age_bucket(chars),
            "evidence_presence": _evidence_presence(chars),
        }

    accepted_lens = _lens(accepted_chars, "accepted_track_record")
    raw_lens = _lens(raw_chars, "raw_analysis_stage")

    # Candidate comparison + transitions on the PRIMARY (accepted) lens.
    candidate_results = []
    for cand in CANDIDATES:
        tm = transition_matrix(accepted_chars, cand["fn"])
        cand_status: dict[str, int] = {}
        for ch in accepted_chars:
            s = cand["fn"](ch["current_status"], ch["supporting"], ch["contradicting"])
            cand_status[s] = cand_status.get(s, 0) + 1
        decisive_cov = sum(cand_status.get(s, 0) for s in DECISIVE)
        candidate_results.append({
            "key": cand["key"],
            "label": cand["label"],
            "basis": cand["basis"],
            "status_counts": cand_status,
            "status_pct": percentages(cand_status, len(accepted_chars)),
            "labels_changed": tm["changed"],
            "transitions": {f"{a}->{b}": n for (a, b), n in tm["transitions"].items()},
            "decisive_coverage": decisive_cov,
        })

    gt = ground_truth_availability(accepted_chars)
    breakdown = accepted_lens["decisive_breakdown"]
    rec = recommend({
        "accepted_n": len(accepted_chars),
        "decisive_total": breakdown["decisive_total"],
        "single_ticker_share": breakdown["single_ticker_share"],
    })

    return {
        "contract_version": CONTRACT_VERSION,
        "db_basename": Path(db_path).name,
        "db_sha256": db_sha_before,
        "db_sha256_after": db_sha_after,
        "db_unchanged": db_sha_before == db_sha_after,
        "as_of": as_of_label,
        "as_of_invariance_note": ("decisive labels (validated/contradicted) are "
                                  "age-invariant; only pending vs unresolved on "
                                  "no-directional rows depends on as-of"),
        "funnel": funnel,
        "accepted": accepted_lens,
        "raw": raw_lens,
        "candidates": candidate_results,
        "ground_truth": gt,
        "recommendation": rec,
    }


# ---------------------------------------------------------------------------
# Deterministic Markdown rendering
# ---------------------------------------------------------------------------


def _status_row(counts: dict, pct: dict) -> str:
    cells = []
    for s in STATUS_ORDER:
        if s in counts:
            cells.append(f"{s} {counts[s]} ({pct.get(s, 0)}%)")
    return "; ".join(cells) if cells else "(none)"


def render_markdown(report: dict) -> str:
    L: list[str] = []
    acc = report["accepted"]
    raw = report["raw"]
    f = report["funnel"]
    bd = acc["decisive_breakdown"]
    gt = report["ground_truth"]
    rec = report["recommendation"]

    L.append("# Validation-status evidence-floor calibration (read-only)")
    L.append("")
    L.append(f"Contract: `{report['contract_version']}`. This report calibrates "
             "the production event-level rule "
             "`validation_status.score_validation_status` (the "
             "`validation_status_v2` label) against the real archive. It reuses "
             "the production scorer verbatim for the current-rule column, changes "
             "no production behaviour or label, and reads the database over a "
             "`mode=ro` connection only.")
    L.append("")
    L.append(f"- source database: `{report['db_basename']}`")
    L.append(f"- database sha256: `{report['db_sha256']}`")
    L.append(f"- database unchanged during run: {report['db_unchanged']} "
             f"(sha256 after: `{report['db_sha256_after']}`)")
    L.append("- note: the snapshot sha is a whole-file hash covering volatile "
             "non-research tables (news / market caches) that mutate "
             "independently of the archive; it is a same-run safety proof, not a "
             "reproduction key — reproduce via the accepted denominator and "
             "funnel below, never the whole-file hash.")
    L.append(f"- as-of: {report['as_of']}")
    L.append(f"- {report['as_of_invariance_note']}")
    L.append("")

    L.append("## 1. Eligibility and denominators")
    L.append("")
    L.append("Primary lens: the accepted track-record population — every "
             "`events` row whose `stage` is not in `db.NON_THESIS_STAGES` and "
             "whose id is not an `event_hygiene` `synthetic_seed`. This is the "
             "established accepted denominator, reproduced so the report "
             "reconciles with `routes/diagnostics.py::_compute_validation_status_stats`. "
             "Accepted (86-style) and raw analysis-stage lenses are separate "
             "columns and are never summed. The accepted set is 'archive minus "
             "non-thesis stages minus override-flagged synthetic seeds' — not "
             "'all real events'.")
    L.append("")
    L.append("## 2. Missingness funnel")
    L.append("")
    L.append(f"- total archive rows: {f['archive_rows']}")
    L.append(f"- excluded — non-thesis stage: {f['excluded_non_thesis_stage']}")
    L.append(f"- excluded — synthetic seed: {f['excluded_synthetic_seed']}")
    L.append(f"- accepted (primary denominator): {f['accepted']}")
    L.append(f"- reconciliation: {f['accepted']} + {f['excluded_non_thesis_stage']} "
             f"+ {f['excluded_synthetic_seed']} = {f['archive_rows']}")
    ep = acc["evidence_presence"]
    L.append("")
    L.append(f"Within the {acc['n']} accepted rows:")
    L.append(f"- with thesis information: {ep['with_thesis']}")
    L.append(f"- with market tickers: {ep['with_tickers']}")
    L.append(f"- with directional ticker tags: {ep['with_directional_tags']}")
    L.append(f"- with no directional evidence: {ep['no_directional_evidence']}")
    L.append("")
    L.append(f"Secondary raw/analysis-stage lens (separate, never summed): "
             f"{raw['n']} rows.")
    L.append("")

    L.append("## 3. Current-rule status distribution (accepted lens)")
    L.append("")
    L.append(f"- {_status_row(acc['status_counts'], acc['status_pct'])}")
    L.append("")

    L.append("## 4. Directional-evidence-count distribution (accepted lens)")
    L.append("")
    for k in sorted(acc["directional_count_distribution"]):
        L.append(f"- {k} directional ticker(s): "
                 f"{acc['directional_count_distribution'][k]} events")
    L.append("")
    L.append("### Decisive labels by directional-evidence count (the crux)")
    L.append("")
    L.append(f"- decisive labels total: {bd['decisive_total']}")
    L.append(f"- resting on exactly 1 directional ticker: "
             f"{bd['by_bucket']['1']['validated']} validated + "
             f"{bd['by_bucket']['1']['contradicted']} contradicted = "
             f"{bd['single_ticker_decisive']} "
             f"({round(bd['single_ticker_share'] * 100, 1)}% of decisive labels)")
    L.append(f"- resting on exactly 2 directional tickers: "
             f"{bd['by_bucket']['2']['validated']} validated + "
             f"{bd['by_bucket']['2']['contradicted']} contradicted")
    L.append(f"- resting on 3+ directional tickers: "
             f"{bd['by_bucket']['3plus']['validated']} validated + "
             f"{bd['by_bucket']['3plus']['contradicted']} contradicted")
    L.append(f"- decisive labels resting on an exact tie "
             f"(supports == contradicts): {bd['tie_decisive']}")
    L.append("")

    L.append("## 5. Observed (supporting, contradicting) combinations (accepted lens)")
    L.append("")
    for combo in sorted(acc["combinations"], key=lambda c: (-acc["combinations"][c], c)):
        sup, con = combo
        L.append(f"- supports {sup}, contradicts {con}: {acc['combinations'][combo]}")
    L.append("")

    L.append("## 6. Candidate rules and transition matrices (accepted lens)")
    L.append("")
    L.append("Each candidate holds the non-directional branch fixed, so every "
             "reported change is attributable to the evidence-floor rule alone.")
    for cand in report["candidates"]:
        L.append("")
        L.append(f"### {cand['key']} — {cand['label']}")
        L.append(f"- empirical basis: {cand['basis']}")
        L.append(f"- status: {_status_row(cand['status_counts'], cand['status_pct'])}")
        L.append(f"- decisive-label coverage: {cand['decisive_coverage']}")
        L.append(f"- labels changed vs current: {cand['labels_changed']}")
        if cand["transitions"]:
            moved = sorted(k for k in cand["transitions"]
                           if k.split("->")[0] != k.split("->")[1])
            if moved:
                L.append("- transitions: " + "; ".join(
                    f"{k} {cand['transitions'][k]}" for k in moved))
            else:
                L.append("- transitions: none (identity)")
    L.append("")

    L.append("## 7. Family and age-bucket sensitivity (accepted lens)")
    L.append("")
    fams = acc["by_family"]
    L.append(f"- mechanism families present: {sorted(fams)}")
    if set(fams) == {"none"}:
        L.append("- NOTE: every accepted row carries `mechanism_family = 'none'`; "
                 "family stratification is degenerate and unavailable on this "
                 "archive.")
    else:
        for fam in sorted(fams):
            L.append(f"  - {fam}: {fams[fam]}")
    L.append(f"- age buckets present: {sorted(acc['by_age_bucket'])}")
    for b in sorted(acc["by_age_bucket"]):
        L.append(f"  - {b}: {acc['by_age_bucket'][b]}")
    L.append("")

    L.append("## 8. Ground-truth availability")
    L.append("")
    L.append(f"- accepted rows with a manual `rating`: {gt['rating_present_count']}")
    L.append(f"- rating vocabulary observed: {gt['rating_vocabulary']}")
    L.append(f"- independent target available: {gt['independent_target_available']}")
    L.append(f"- {gt['note']}")
    L.append("")
    L.append("Because no defensible independent target exists, predictive "
             "accuracy CANNOT be calibrated. The analysis is restricted to "
             "evidence sufficiency, label stability, coverage, and sensitivity. "
             "No claim is made that any rule is 'more accurate'; any agreement "
             "with manual ratings or outcomes would be descriptive and "
             "same-sample only.")
    L.append("")

    L.append("## 9. Recommendation")
    L.append("")
    _render_recommendation(L, report)
    L.append("")
    L.append(f"### {rec['verdict']}")
    return "\n".join(L) + "\n"


def _render_recommendation(L: list[str], report: dict) -> None:
    acc = report["accepted"]
    bd = acc["decisive_breakdown"]
    f = report["funnel"]
    gt = report["ground_truth"]
    # Candidate coverage costs (labels changed) for the fragility field.
    changed = {c["key"]: c["labels_changed"] for c in report["candidates"]}
    single = bd["single_ticker_decisive"]
    share_pct = round(bd["single_ticker_share"] * 100, 1)
    L.append(f"- denominator: {acc['n']} accepted track-record events "
             f"(archive {f['archive_rows']}; excluded "
             f"{f['excluded_non_thesis_stage']} non-thesis-stage + "
             f"{f['excluded_synthetic_seed']} synthetic-seed).")
    L.append(f"- observed basis: {bd['decisive_total']} decisive labels; "
             f"{single} rest on a single directional ticker ({share_pct}%); "
             f"{bd['tie_decisive']} rest on an exact tie; the remainder rest on "
             "two or more directional tickers.")
    L.append(f"- proposed rule: none is compelled by the data. A minimum-2 "
             f"directional floor (`min2`) is available and would move "
             f"{changed.get('min2', 0)} label(s); it is documented as an "
             "optional guard, not a required change.")
    L.append(f"- labels affected / coverage cost: min2 {changed.get('min2', 0)}; "
             f"tie_unresolved {changed.get('tie_unresolved', 0)}; "
             f"min2_supermajority {changed.get('min2_supermajority', 0)} "
             "(all out of the accepted decisive set).")
    L.append(f"- fragility: label stability under small rule perturbations is "
             f"reported in section 6; the current decisive labels move only "
             f"{changed.get('min2', 0)} under the count floor and "
             f"{changed.get('min2_supermajority', 0)} under the combined "
             "count+balance floor.")
    L.append(f"- what was unavailable: an independent target "
             f"(manual `rating` present on {gt['rating_present_count']} accepted "
             "rows; mechanism-family labels degenerate; event-study inference is "
             "n=1), so predictive accuracy could not be calibrated.")
    L.append(f"- scope: this characterizes the current {acc['n']}-event accepted "
             f"archive snapshot ({acc['decisive_breakdown']['decisive_total']} "
             "decisive labels) — a small, bounded set; the calibration should be "
             "re-run as accepted coverage grows before any rule change is "
             "considered.")
    L.append("- non-claim: this report does not assert any rule is more "
             "accurate, does not confirm any thesis, and proposes no directional "
             "or trading interpretation; it characterizes evidence sufficiency "
             "and label stability only.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only validation-status evidence-floor calibration.")
    ap.add_argument("--db-path", required=True,
                    help="path to events.db (opened read-only)")
    ap.add_argument("--as-of", default=None,
                    help="ISO date (YYYY-MM-DD) reference clock; recorded in the "
                         "report. Decisive labels are as-of-invariant.")
    ap.add_argument("--out", default=None,
                    help="write Markdown here (default: stdout)")
    ap.add_argument("--json", action="store_true",
                    help="emit the report dict as JSON instead of Markdown")
    args = ap.parse_args(argv)

    report = build_report(db_path=args.db_path, as_of=args.as_of)
    if args.json:
        payload = json.dumps(report, indent=2, sort_keys=True, default=str)
        out = payload
    else:
        out = render_markdown(report)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
    else:
        sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
