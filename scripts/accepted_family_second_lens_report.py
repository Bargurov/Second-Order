#!/usr/bin/env python3
"""Read-only second lens for the accepted-family overlay (mechanism text).

J1 (``scripts/accepted_family_overlay_report.py``) classified the accepted
thesis corpus from the HEADLINE only. K1
(``scripts/accepted_family_overlay_review.py``) reviewed the resulting weak
buckets. This report tests K1's suggested idea read-only: run the SAME J1
whole-token family rules over local mechanism-text fields
(``mechanism_summary``, ``what_changed``, ``transmission_chain``,
``market_note``, ``notes``) and compare that SECOND lens against the headline
lens - does richer text resolve headline ambiguity, or add to it?

Discipline (non-negotiable):

  * **Consumes J1, does not replace it.** The headline label for every row is
    taken from J1's ``build_overlay`` output, never recomputed here. The
    second lens reuses J1's ``classify_headline`` rule engine on text; it does
    NOT modify J1 rules and does NOT apply any K1 refinement.
  * **Reported separately, never overwrites.** Each row carries both
    ``headline_lens_families`` and ``second_lens_families``. The second-lens
    label is a comparison artifact, not a DB label - nothing is written to
    events.db and the ``mechanism_family`` column is untouched.
  * **No fake precision.** Empty / generic mechanism text never manufactures a
    label (``no_text_basis``). Multi-match rows are not force-resolved without
    a strong text basis. No family-level inference, no significance.

Usage::

    python scripts/accepted_family_second_lens_report.py --db-path events.db --json
    python scripts/accepted_family_second_lens_report.py --db-path events.db
    python scripts/accepted_family_second_lens_report.py --db-path events.db \
        --include-examples 5
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

from scripts.accepted_family_overlay_report import (  # noqa: E402
    build_overlay,
    classify_headline,
)
from scripts.track_record_sensitivity_report import (  # noqa: E402
    _load_accepted_records,
)

DEFAULT_EXAMPLES = 3
_OVERLAY_LIST_CAP = 100000

# Local mechanism-text fields, in basis order. notes / transmission_path are
# kept in the candidate set so field_coverage reports them HONESTLY (they are
# empty / placeholder-only in the live archive), but they contribute no text.
CANDIDATE_FIELDS: tuple[str, ...] = (
    "mechanism_summary",
    "what_changed",
    "transmission_chain",
    "market_note",
    "notes",
    "transmission_path",
)

# A field is "usable" only if it carries real prose. Placeholder JSON ("[]"),
# empty tokens, and very short stubs are "generic" and contribute nothing.
EMPTY_TOKENS: frozenset[str] = frozenset(
    {"", "none", "n/a", "na", "-", "tbd", "null"})
_JSON_EMPTY: frozenset[str] = frozenset({"[]", "{}", "[ ]", "{ }"})
GENERIC_MIN_LEN = 12

# Change-type vocabulary (also the row-level grouping).
_CHANGED = frozenset({
    "resolved_unclassified", "clarified_multi_match",
    "worsened_or_more_ambiguous", "review_needed",
})
_UNRESOLVED = frozenset({
    "review_needed", "worsened_or_more_ambiguous", "unchanged_unclassified",
})

NON_CLAIMS: tuple[str, ...] = (
    "Second-lens labels are a read-only comparison artifact, not DB labels: "
    "the mechanism_family column was not read as truth and was not modified.",
    "No database write occurred anywhere in this report (read-only "
    "connections; price_cache untouched).",
    "J1 rules are unchanged: the second lens reuses the same classify_headline "
    "rule engine on text and edits no rule.",
    "K1 refinements are not applied: no 'trade war' negative phrase, no "
    "context-gated supply phrase, no catch-all bucket - the lens uses J1 "
    "rules exactly as they are.",
    "No family-level inference: per-row labels are post-hoc keyword matches "
    "over tiny n; nothing is claimed about any family's behavior.",
    "No family performance ranking and no validated-vs-contradicted "
    "comparison across families is implied.",
    "No significance testing: no CI, p-value, or FDR anywhere here.",
    "Not a recommendation of any kind.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor reopened.",
    "No paid analysis was run and none is approved; paid /analyze remains "
    "blocked.",
    "Denominators unchanged: 94 accepted coverage / 86 accepted "
    "track-record on the live archive; this lens adds no denominator.",
)


# ---------------------------------------------------------------------------
# Field state / text basis
# ---------------------------------------------------------------------------


def field_state(value: Any) -> str:
    """Classify a mechanism-text field value: empty | generic | usable."""
    if value is None:
        return "empty"
    s = str(value).strip()
    if s.lower() in EMPTY_TOKENS:
        return "empty"
    if s in _JSON_EMPTY:
        return "generic"
    if len(s) < GENERIC_MIN_LEN:
        return "generic"
    return "usable"


def usable_text(fields: dict[str, Any]) -> tuple[str, list[str]]:
    """Return (combined usable text, list of usable basis field names)."""
    parts: list[str] = []
    basis: list[str] = []
    for f in CANDIDATE_FIELDS:
        if field_state(fields.get(f)) == "usable":
            parts.append(str(fields[f]))
            basis.append(f)
    return " ".join(parts), basis


def second_lens_families(text: str) -> list[str]:
    """Run J1's rule engine over mechanism text (same family vocabulary)."""
    return classify_headline(text)


# ---------------------------------------------------------------------------
# Change typing
# ---------------------------------------------------------------------------


def _status(fams: frozenset) -> str:
    n = len(fams)
    return "unclassified" if n == 0 else ("single" if n == 1 else "multi")


def change_type(headline_families: Any, second_families: Any,
                has_text: bool = True) -> str:
    """Compare headline-lens vs second-lens family sets -> change_type."""
    h = frozenset(headline_families)
    s = frozenset(second_families)
    if not has_text:
        if len(h) == 0:
            return "unchanged_unclassified"
        if len(h) == 1:
            return "unchanged_single"
        return "review_needed"
    if h == s:
        if len(h) == 0:
            return "unchanged_unclassified"
        if len(h) == 1:
            return "unchanged_single"
        return "confirmed_multi_match"
    if len(h) == 0 and len(s) > 0:
        return "resolved_unclassified"
    if len(h) > 0 and len(s) == 0:
        return "review_needed"
    if len(h) >= 2 and len(s) == 1 and s < h:
        return "clarified_multi_match"
    if len(h) == 1 and len(s) >= 2:
        return "worsened_or_more_ambiguous"
    if len(h) >= 2 and len(s) > len(h) and h < s:
        return "worsened_or_more_ambiguous"
    return "review_needed"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_mechanism_text(path: str | None,
                         ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    """Read mechanism-text fields for the given ids. Read-only; {} on error."""
    if path is None or not ids:
        return {}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        conn.row_factory = sqlite3.Row
        existing = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
        fields = [f for f in CANDIDATE_FIELDS if f in existing]
        if not fields:
            return {}
        idset = set(ids)
        out: dict[int, dict[str, Any]] = {}
        for r in conn.execute(
                f"SELECT id, {', '.join(fields)} FROM events"):
            if r["id"] in idset:
                out[r["id"]] = {f: r[f] for f in fields}
        return out
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def _headline_map_from_overlay(overlay: dict[str, Any]) -> dict[int, list[str]]:
    """Per-row headline families taken DIRECTLY from J1's overlay buckets."""
    out: dict[int, list[str]] = {}
    for fc in overlay.get("family_counts", []):
        ids = list(fc.get("representative_event_ids", []))
        if len(ids) != fc.get("row_count", 0):
            raise ValueError(
                "overlay family_counts list is truncated; rerun build_overlay "
                "with a larger --limit before the second lens")
        for eid in ids:
            out[eid] = [fc["family"]]
    mm = overlay["ambiguous_or_multi_match"]
    mm_ids = list(mm.get("representative_event_ids", []))
    mm_sets = list(mm.get("matched_family_sets", []))
    if len(mm_ids) != mm.get("count", 0) or len(mm_sets) != mm.get("count", 0):
        raise ValueError(
            "overlay multi-match list is truncated; rerun build_overlay with a "
            "larger --limit before the second lens")
    for eid, fams in zip(mm_ids, mm_sets):
        out[eid] = list(fams)
    unc = overlay["unclassified_or_review_needed"]
    unc_ids = list(unc.get("representative_event_ids", []))
    if len(unc_ids) != unc.get("count", 0):
        raise ValueError(
            "overlay unclassified list is truncated; rerun build_overlay with "
            "a larger --limit before the second lens")
    for eid in unc_ids:
        out[eid] = []
    return out


# ---------------------------------------------------------------------------
# Report composer
# ---------------------------------------------------------------------------


def _clip(text: str | None, n: int = 150) -> str:
    t = (text or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 3] + "..."


def _safe(text: str) -> str:
    return (text or "").encode("cp1252", "replace").decode("cp1252")


def build_second_lens(db_path: str | None = None, *,
                      overlay: dict[str, Any] | None = None,
                      records: list[dict] | None = None,
                      mech_text: dict[int, dict[str, Any]] | None = None,
                      include_examples: int = DEFAULT_EXAMPLES
                      ) -> dict[str, Any]:
    """Build the second-lens comparison dict. Read-only; consumes J1."""
    if overlay is None:
        # include_examples is what caps build_overlay's per-family
        # representative_event_ids; lift BOTH caps so every accepted row's
        # headline bucket is present (the guards below reject any truncation).
        overlay = build_overlay(db_path=db_path,
                                include_examples=_OVERLAY_LIST_CAP,
                                limit=_OVERLAY_LIST_CAP)
    if records is None:
        records, _ = _load_accepted_records(db_path)
    headline_map = _headline_map_from_overlay(overlay)
    ids = list(headline_map.keys())
    if mech_text is None:
        mech_text = _load_mechanism_text(db_path, ids)
    headline_by_id = {r["event_id"]: r for r in (records or [])}
    ex_cap = max(int(include_examples), 0)

    # field coverage over the accepted target rows.
    field_cov = []
    for f in CANDIDATE_FIELDS:
        usable_ids = []
        generic_or_empty = 0
        non_empty = 0
        for eid in ids:
            st = field_state(mech_text.get(eid, {}).get(f))
            if st == "usable":
                usable_ids.append(eid)
                non_empty += 1
            elif st == "generic":
                non_empty += 1
                generic_or_empty += 1
            else:
                generic_or_empty += 1
        field_cov.append({
            "field": f,
            "non_empty_count": non_empty,
            "usable_count": len(usable_ids),
            "generic_or_empty_count": generic_or_empty,
            "representative_event_ids": usable_ids[:ex_cap],
        })

    # per-row comparison.
    rows = []
    for eid in ids:
        hfams = frozenset(headline_map[eid])
        text, basis = usable_text(mech_text.get(eid, {}))
        has_text = bool(basis)
        sfams = frozenset(second_lens_families(text)) if has_text \
            else frozenset()
        ct = change_type(hfams, sfams, has_text)
        rec = headline_by_id.get(eid)
        rows.append({
            "event_id": eid,
            "headline": _clip((rec.get("headline") if rec else "") or ""),
            "headline_lens_status": _status(hfams),
            "headline_lens_families": sorted(hfams),
            "mechanism_text_basis_fields": basis,
            "second_lens_status": _status(sfams) if has_text
            else "no_text_basis",
            "second_lens_families": sorted(sfams),
            "change_type": ct,
            "explanation": _explain(ct, hfams, sfams, has_text),
        })

    # lens comparison aggregates.
    def _hstat(st):
        return sum(1 for r in rows if r["headline_lens_status"] == st)

    def _sstat(st):
        return sum(1 for r in rows if r["second_lens_status"] == st)

    changed = sum(1 for r in rows
                  if r["headline_lens_families"] != r["second_lens_families"])
    worsened = sum(1 for r in rows
                   if r["change_type"] == "worsened_or_more_ambiguous")
    lens_comparison = {
        "headline_single_match": _hstat("single"),
        "headline_multi_match": _hstat("multi"),
        "headline_unclassified": _hstat("unclassified"),
        "second_lens_single_match": _sstat("single"),
        "second_lens_multi_match": _sstat("multi"),
        "second_lens_unclassified": _sstat("unclassified"),
        "second_lens_no_text_basis": _sstat("no_text_basis"),
        "changed_count": changed,
        "unchanged_count": len(rows) - changed,
        "worsened_or_more_ambiguous_count": worsened,
    }

    from collections import Counter
    ct_counts = Counter(r["change_type"] for r in rows)
    examples_by_change_type: dict[str, list[int]] = {}
    for r in rows:
        b = examples_by_change_type.setdefault(r["change_type"], [])
        if len(b) < ex_cap:
            b.append(r["event_id"])

    unresolved = [r for r in rows if r["change_type"] in _UNRESOLVED]

    od = overlay["denominators"]
    denoms = {k: od.get(k) for k in (
        "archive_rows", "accepted_coverage_denominator",
        "accepted_track_record_denominator", "staged_candidate_count",
        "overlay_target_count")}

    return {
        "denominators": denoms,
        "second_lens_scope": {
            "source_report": "accepted_family_overlay_report",
            "source_review": "accepted_family_overlay_review",
            "headline_lens": True,
            "mechanism_text_lens": True,
            "db_write_status": "not_written",
            "overlay_only": True,
            "j1_rules_modified": False,
            "k1_refinements_applied": False,
            "candidate_fields": list(CANDIDATE_FIELDS),
        },
        "field_coverage": field_cov,
        "lens_comparison": lens_comparison,
        "change_type_counts": dict(ct_counts),
        "examples_by_change_type": examples_by_change_type,
        "row_changes": {"count": len(rows), "rows": rows},
        "unresolved_or_review_needed": {
            "count": len(unresolved),
            "rows": unresolved,
        },
        "taxonomy_lessons": _taxonomy_lessons(lens_comparison, dict(ct_counts)),
        "non_claims": list(NON_CLAIMS),
    }


def _explain(ct: str, hfams: frozenset, sfams: frozenset,
             has_text: bool) -> str:
    if not has_text:
        return ("No usable mechanism text for this row; the second lens "
                "abstains and the headline classification stands.")
    h = sorted(hfams) or ["(none)"]
    s = sorted(sfams) or ["(none)"]
    base = f"headline {h} vs mechanism-text {s}. "
    if ct == "resolved_unclassified":
        return base + ("Mechanism text names a family the headline did not - "
                       "a recall gain; verify the family is the event's "
                       "mechanism, not incidental backdrop.")
    if ct == "confirmed_multi_match":
        return base + ("Mechanism text reproduces the same overlap - "
                       "consistent with K1's legitimate-overlap reading.")
    if ct == "clarified_multi_match":
        return base + ("Mechanism text narrows to a subset; treat as a "
                       "candidate only - K1 found these overlaps legitimate, "
                       "so dropping a family may discard a real channel.")
    if ct == "worsened_or_more_ambiguous":
        return base + ("Rich mechanism text matches extra backdrop families, "
                       "adding ambiguity the headline did not have.")
    if ct == "review_needed":
        return base + ("Mechanism text disagrees with the headline (shifted "
                       "or lost families); needs human review, not an "
                       "automatic label.")
    if ct == "unchanged_unclassified":
        return base + ("Neither lens matched a family; the row stays honestly "
                       "unclassified.")
    return base + "Both lenses agree on the single family."


def _taxonomy_lessons(lc: dict[str, int],
                      ct: dict[str, int]) -> dict[str, list[str]]:
    return {
        "what_second_lens_reveals": [
            "Running J1's headline rules over mechanism text does NOT cleanly "
            "reduce ambiguity: it tends to raise the multi-match count "
            "because mechanism summaries describe the whole transmission "
            "(supply + conflict + policy backdrop), so several families match "
            "per row.",
            "The few genuine recall gains are the rule-miss rows K1 already "
            "flagged: rows whose headline dodged the trigger token but whose "
            "mechanism text names the family directly (resolved_unclassified "
            f"= {ct.get('resolved_unclassified', 0)}).",
        ],
        "where_text_fields_help": [
            "Recovering a small number of unclassified rule-miss rows whose "
            "mechanism text states the family explicitly (e.g. an oil-supply "
            "cut whose headline avoided the oil token).",
            "Confirming, not resolving, the legitimate multi-match overlaps: "
            "when text reproduces the same two families, it corroborates K1's "
            f"legitimate-overlap reading (confirmed_multi_match = "
            f"{ct.get('confirmed_multi_match', 0)}).",
        ],
        "where_text_fields_do_not_help": [
            "Single-family headline rows: rich text adds backdrop families and "
            "manufactures ambiguity (worsened_or_more_ambiguous = "
            f"{ct.get('worsened_or_more_ambiguous', 0)}).",
            "Disambiguating legitimate overlaps: text usually keeps or shifts "
            "the overlap rather than resolving it (review_needed = "
            f"{ct.get('review_needed', 0)}).",
            "Archive-noise rows: their mechanism text is generic or matches "
            "nothing, so they stay unclassified - which is correct.",
        ],
        "what_should_not_be_forced": [
            "Do not adopt the second lens as a replacement classifier: it "
            f"raises multi-match from {lc['headline_multi_match']} to "
            f"{lc['second_lens_multi_match']} and changes "
            f"{lc['changed_count']} of "
            f"{lc['changed_count'] + lc['unchanged_count']} rows.",
            "Do not let an incidental backdrop family in mechanism text "
            "override a clean headline single-match.",
            "Do not narrow a legitimate multi-match just because the text "
            "happened to emphasise one channel.",
        ],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("Accepted-family overlay - second lens (mechanism text, read-only)")
    add("=" * 66)
    d = report["denominators"]
    add(f"Denominators: archive {d['archive_rows']} | coverage "
        f"{d['accepted_coverage_denominator']} | track record "
        f"{d['accepted_track_record_denominator']} | staged "
        f"{d['staged_candidate_count']} | overlay target "
        f"{d['overlay_target_count']}")
    sc = report["second_lens_scope"]
    add(f"Second lens, not DB labels: headline label from "
        f"{sc['source_report']}; text lens reuses J1 rules "
        f"(j1_rules_modified={sc['j1_rules_modified']}, "
        f"k1_refinements_applied={sc['k1_refinements_applied']}, "
        f"db_write_status={sc['db_write_status']}).")
    add("")

    add("Field coverage (usable mechanism-text fields over the target rows):")
    add(f"  {'field':<20}{'non_empty':>10}{'usable':>9}{'generic/empty':>15}")
    for f in report["field_coverage"]:
        add(f"  {f['field']:<20}{f['non_empty_count']:>10}"
            f"{f['usable_count']:>9}{f['generic_or_empty_count']:>15}")
    add("")

    lc = report["lens_comparison"]
    add("Headline lens vs second lens:")
    add(f"  headline:    single {lc['headline_single_match']} | multi "
        f"{lc['headline_multi_match']} | unclassified "
        f"{lc['headline_unclassified']}")
    add(f"  second lens: single {lc['second_lens_single_match']} | multi "
        f"{lc['second_lens_multi_match']} | unclassified "
        f"{lc['second_lens_unclassified']} | no-text "
        f"{lc['second_lens_no_text_basis']}")
    add(f"  changed {lc['changed_count']} | unchanged "
        f"{lc['unchanged_count']} | worsened/more-ambiguous "
        f"{lc['worsened_or_more_ambiguous_count']}")
    add("")

    add("Change-type breakdown:")
    for k in ("resolved_unclassified", "clarified_multi_match",
              "confirmed_multi_match", "worsened_or_more_ambiguous",
              "review_needed", "unchanged_single", "unchanged_unclassified"):
        add(f"  {k:<32}{report['change_type_counts'].get(k, 0)}")
    add("")

    add("Row changes (headline -> second lens), interesting rows:")
    shown = 0
    for r in report["row_changes"]["rows"]:
        if r["change_type"] in ("unchanged_single", "unchanged_unclassified",
                                "confirmed_multi_match"):
            continue
        add(f"  [{r['event_id']}] {r['change_type']}: "
            f"{r['headline_lens_families']} -> {r['second_lens_families']}")
        add(f"      {_safe(_clip(r['headline'], 92))}")
        add(f"      {_safe(r['explanation'])}")
        shown += 1
    if not shown:
        add("  (no rows changed family set)")
    add("")

    add("Unresolved / review-needed:")
    add(f"  {report['unresolved_or_review_needed']['count']} rows still "
        "unresolved, more ambiguous, or needing review after the second lens.")
    add("")

    add("Taxonomy lessons:")
    tl = report["taxonomy_lessons"]
    for key in ("what_second_lens_reveals", "where_text_fields_help",
                "where_text_fields_do_not_help", "what_should_not_be_forced"):
        add(f"  {key}:")
        for item in tl[key]:
            add(f"    - {_safe(item)}")
    add("")

    add("Non-claims:")
    for item in report["non_claims"]:
        add(f"  - {_safe(item)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only second lens (mechanism text) for the "
                    "accepted-family overlay.")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--include-examples", type=int,
                        default=DEFAULT_EXAMPLES)
    args = parser.parse_args(argv)

    report = build_second_lens(db_path=args.db_path,
                               include_examples=args.include_examples)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
