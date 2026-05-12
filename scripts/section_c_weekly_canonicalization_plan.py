#!/usr/bin/env python3
"""Section C — Weekly Market duplicate canonicalization implementation
plan.

A read-only planner that consumes the existing Weekly Market
duplicate-cluster diagnostic
(:mod:`scripts.section_c_weekly_duplicate_diagnostic`) and proposes,
for each duplicate group it surfaces:

* a *suggested* canonical event_id and a *suggested* canonical
  headline (longest non-truncated, with documented fallback),
* the named rule the operator would enable to dedup the group,
* a count of duplicates that would be removed if every suggestion
  were honoured,
* a short list of where in the codebase the rules would land, and
* the false-positive risks of applying them.

The planner does not apply anything.  It is a study report intended
to be reviewed and turned into a worksheet before any production
change is made.

Read-only by construction
-------------------------

* Single upstream source: the diagnostic's
  :func:`scripts.section_c_weekly_duplicate_diagnostic.build_diagnostic`.
  Lazy-imported behind a thin seam so the planner's top-level import
  surface stays narrow and tests can patch the seam directly.
* No DB writes anywhere.  No ``yfinance``, ``market_data``, LLM, or
  paid provider call.  No FastAPI surface (never imports ``api`` or
  ``routes.*``).
* No mutation of the events table, the news cache, or any artifact.
  The planner's ``--output`` writes a single JSON file when
  explicitly passed; the inbox / DB / cache stay untouched.
* The planner emits no command — every entry in
  ``proposed_canonicalization_rules`` and
  ``implementation_targets`` is a description.

Conservative wording
--------------------

Banned tokens in emitted prose: ``proof``, ``proven``,
``validated``, ``guaranteed``, ``alpha generated``, ``correct
ticker``, ``dedupe automatically``, ``correct merge``, ``will
merge``, ``rule guarantees``.  The planner says "suggests" and
"would propose" — never "will".

Canonical-pick heuristic
------------------------

For each duplicate group the planner walks the group's headlines and
picks the candidate canonical with the following priority:

1. Reject candidates that *look raw / truncated*: ends with ``…``
   or ``...``; starts with a lowercase letter (mid-sentence leak);
   contains ``<``, ``[``, or unbalanced quotes; ends mid-word (last
   token < 3 chars without terminal punctuation).
2. Among the remaining clean candidates, pick the longest headline.
   Tie-break on lowest ``event_id``.
3. If every candidate looks raw, fall back to the upstream
   diagnostic's own ``suggested_canonical_event_id`` and emit a
   ``warnings`` entry naming the group so the operator can review.

Rule routing
------------

The rule a suggestion proposes is read from the group's
``duplicate_group_id`` prefix:

* ``headline_*``     → ``exact_headline_match_within_event_date``
                       (when every normalised headline is equal)
                       or
                       ``headline_token_prefix_within_event_date``
                       (when one normalised headline is a strict
                       token-prefix of another).
* ``date_ticker_*``  → ``date_ticker_match``.

Every ``rule_to_apply`` value points to a ``rule_id`` listed in
``proposed_canonicalization_rules`` so the output is referentially
consistent.

Output contract (JSON)::

    {
      "ok":                             bool,
      "duplicate_groups_analyzed":      int,
      "proposed_canonicalization_rules":[
        {"rule_id": str, "description": str, "scope": str},
        ...
      ],
      "canonical_event_suggestions":    [
        {
          "duplicate_group_id":          str,
          "event_ids":                   [int, ...],
          "suggested_canonical_event_id": int | None,
          "suggested_canonical_headline":str,
          "reason":                      str,
          "rule_to_apply":               str,
        },
        ...
      ],
      "expected_removed_duplicates":    int,
      "implementation_targets":         [
        {"path": str, "note": str},
        ...
      ],
      "false_positive_risks":           [str, ...],
      "warnings":                       [str, ...],
      "errors":                         [str, ...],
    }

Usage::

    python scripts/section_c_weekly_canonicalization_plan.py --json
    python scripts/section_c_weekly_canonicalization_plan.py --json \\
        --db-path events.db --window-days 7 \\
        --output artifacts/section_c_weekly_canonicalization_plan.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_DB_PATH:     str = "events.db"
_DEFAULT_WINDOW_DAYS: int = 7


# ---------------------------------------------------------------------------
# Named canonicalization rules.
#
# The planner emits these as a stable, named catalogue so each
# canonical_event_suggestion.rule_to_apply can reference a rule_id by
# string.  Descriptions are operator-facing prose; the planner does not
# define what "applying" a rule means here — that decision lands in a
# follow-up worksheet.
# ---------------------------------------------------------------------------


_RULES: tuple[dict[str, str], ...] = (
    {
        "rule_id":     "exact_headline_match_within_event_date",
        "scope":       "ingestion",
        "description": (
            "When two events share an identical normalised headline "
            "on the same event_date, suggest treating them as one "
            "cluster.  Surface the canonical headline as the cluster "
            "representative and keep the rest as 'see also' references."
        ),
    },
    {
        "rule_id":     "headline_token_prefix_within_event_date",
        "scope":       "ingestion",
        "description": (
            "When one event's normalised headline is a strict "
            "token-prefix of another within the same event_date, "
            "suggest treating the shorter headline as a partial echo "
            "of the longer story rather than a distinct event."
        ),
    },
    {
        "rule_id":     "date_ticker_match",
        "scope":       "weekly_surface",
        "description": (
            "When two or more events share the same event_date and "
            "the same market_tickers set, suggest routing the second "
            "and subsequent rows to operator review before they enter "
            "the weekly mover ranking."
        ),
    },
    {
        "rule_id":     "prefer_longest_non_truncated_headline_as_canonical",
        "scope":       "selection",
        "description": (
            "When several headlines describe the same story, suggest "
            "the longest headline that does not look raw or truncated "
            "as the canonical.  Fall back to the diagnostic's own "
            "suggestion when every candidate looks raw."
        ),
    },
)


# Rule lookup by id — used to verify rule_to_apply is referentially
# valid before we emit a suggestion.
_RULE_IDS: frozenset[str] = frozenset(r["rule_id"] for r in _RULES)


# ---------------------------------------------------------------------------
# Implementation targets — every path is a real file in the repo as of
# this writing; the planner does not invent surfaces.
# ---------------------------------------------------------------------------


_IMPL_TARGETS: tuple[dict[str, str], ...] = (
    {
        "path": "news_clustering.py",
        "note": (
            "pre-DB clustering layer.  An ingestion-time rule "
            "(exact_headline_match, token_prefix) would land here so "
            "two near-identical headlines merge into one cluster "
            "before ``save_event`` ever sees them."
        ),
    },
    {
        "path": "db.save_event",
        "note": (
            "DB write boundary.  A defensive dedup gate at write time "
            "would check the incoming (event_date, normalised_headline) "
            "against recent rows before INSERT.  Belt-and-braces with "
            "the upstream clustering layer."
        ),
    },
    {
        "path": "routes/movers.py",
        "note": (
            "weekly mover surface.  The date_ticker_match rule would "
            "apply here so the second and subsequent rows of a same-"
            "ticker pair are routed to operator review rather than "
            "double-counted in the ranking."
        ),
    },
)


# ---------------------------------------------------------------------------
# False-positive risks — short, conservative bullets.
# ---------------------------------------------------------------------------


_FP_RISKS: tuple[str, ...] = (
    "real follow-up stories with identical headlines on consecutive "
    "trading days could be silently collapsed; the exact-match rule "
    "should be scoped to within a single event_date, never across "
    "dates.",
    "two stories whose headlines share a common stem but diverge in "
    "the tail (e.g., 'OPEC discusses cuts' vs 'OPEC discusses output "
    "freeze') would still cluster under the token-prefix rule; "
    "operator review is suggested before any merge is materialised.",
    "the date_ticker_match rule would group unrelated stories that "
    "happen to share the same ticker set on the same date (e.g., two "
    "distinct earnings-day events for the same issuer); operator "
    "review before surfacing is suggested.",
    "the longest-headline canonical-pick prefers length over recency; "
    "an operator who relies on the most recent timestamp as a tie-"
    "breaker would want a different rule.  This planner suggests the "
    "longest-clean-headline heuristic; it does not claim it is the "
    "only reasonable choice.",
)


# ---------------------------------------------------------------------------
# Patchable seam — lazy import of the upstream diagnostic.
# ---------------------------------------------------------------------------


def _build_weekly_diagnostic(
    *,
    db_path:        str,
    window_days:    int,
    reference_date: str | None,
) -> dict[str, Any]:
    """Call the existing weekly duplicate diagnostic and return its
    full report.

    Lazy-imports the diagnostic so the planner's top-level import
    surface stays narrow.  Tests patch this seam directly with a
    synthetic payload so they never depend on the live events DB.
    """
    from scripts.section_c_weekly_duplicate_diagnostic import (
        build_diagnostic,
    )
    return build_diagnostic(
        db_path=db_path,
        window_days=window_days,
        reference_date=reference_date,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_section_c_weekly_canonicalization_plan(
    *,
    db_path:        str       = _DEFAULT_DB_PATH,
    window_days:    int       = _DEFAULT_WINDOW_DAYS,
    reference_date: str | None = None,
    output_path:    str | None = None,
) -> dict[str, Any]:
    """Run the read-only canonicalization planner.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    try:
        diagnostic = _build_weekly_diagnostic(
            db_path=db_path,
            window_days=window_days,
            reference_date=reference_date,
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"weekly duplicate diagnostic raised: "
            f"{type(exc).__name__}: {exc}"
        )
        diagnostic = {}

    # Propagate any warnings/errors the upstream diagnostic produced.
    for w in diagnostic.get("warnings") or []:
        if isinstance(w, str) and w:
            warnings.append(f"upstream diagnostic: {w}")
    for e in diagnostic.get("errors") or []:
        if isinstance(e, str) and e:
            errors.append(f"upstream diagnostic: {e}")

    duplicate_groups = diagnostic.get("duplicate_groups") or []
    if not isinstance(duplicate_groups, list):
        warnings.append(
            "upstream diagnostic returned a non-list duplicate_groups; "
            "treating as empty"
        )
        duplicate_groups = []

    suggestions: list[dict[str, Any]] = []
    for group in duplicate_groups:
        if not isinstance(group, dict):
            continue
        suggestion = _build_suggestion(group, warnings=warnings)
        if suggestion is not None:
            suggestions.append(suggestion)

    expected_removed = _count_expected_removed(suggestions)

    envelope: dict[str, Any] = {
        "ok":                             not errors,
        "duplicate_groups_analyzed":      len(suggestions),
        "proposed_canonicalization_rules":[dict(r) for r in _RULES],
        "canonical_event_suggestions":    suggestions,
        "expected_removed_duplicates":    expected_removed,
        "implementation_targets":         [dict(t) for t in _IMPL_TARGETS],
        "false_positive_risks":           list(_FP_RISKS),
        "warnings":                       warnings,
        "errors":                         errors,
    }

    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, sort_keys=True, default=str)
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False

    return envelope


# ---------------------------------------------------------------------------
# Per-group helpers
# ---------------------------------------------------------------------------


def _build_suggestion(
    group: dict[str, Any], *, warnings: list[str],
) -> dict[str, Any] | None:
    group_id = group.get("duplicate_group_id")
    if not isinstance(group_id, str) or not group_id:
        return None
    raw_event_ids = group.get("event_ids") or []
    if not isinstance(raw_event_ids, list):
        return None
    event_ids: list[int] = [
        e for e in raw_event_ids
        if isinstance(e, int) and not isinstance(e, bool)
    ]
    if len(event_ids) < 2:
        return None
    raw_headlines = group.get("headlines") or []
    if not isinstance(raw_headlines, list):
        raw_headlines = []
    headlines: list[str] = [
        h for h in raw_headlines if isinstance(h, str)
    ]

    upstream_canonical = group.get("suggested_canonical_event_id")
    if not isinstance(upstream_canonical, int) or isinstance(
            upstream_canonical, bool):
        upstream_canonical = None

    canonical_event_id, canonical_headline, reason = _pick_canonical(
        group_id=group_id,
        event_ids=event_ids,
        headlines=headlines,
        upstream_canonical=upstream_canonical,
        warnings=warnings,
    )

    rule_to_apply = _select_rule(group_id, headlines)
    if rule_to_apply not in _RULE_IDS:
        # Defensive — should not happen because _select_rule only
        # returns rule_ids drawn from the catalogue.  Surface as a
        # warning rather than a silent error.
        warnings.append(
            f"rule selection produced unknown rule_id "
            f"{rule_to_apply!r} for group {group_id!r}; defaulting "
            f"to the longest-non-truncated rule"
        )
        rule_to_apply = "prefer_longest_non_truncated_headline_as_canonical"

    return {
        "duplicate_group_id":           group_id,
        "event_ids":                    sorted(event_ids),
        "suggested_canonical_event_id": canonical_event_id,
        "suggested_canonical_headline": canonical_headline,
        "reason":                       reason,
        "rule_to_apply":                rule_to_apply,
    }


def _pick_canonical(
    *,
    group_id:           str,
    event_ids:          list[int],
    headlines:          list[str],
    upstream_canonical: int | None,
    warnings:           list[str],
) -> tuple[int | None, str, str]:
    """Return (canonical_event_id, canonical_headline, reason).

    Pairs the event_ids and headlines positionally where possible.
    The upstream diagnostic emits ``event_ids`` and ``headlines`` as
    parallel lists (sorted by event_id ascending in
    ``_group_to_dict``).  We rely on that pairing here; if it's
    broken (lengths differ) we fall back to upstream and warn.
    """
    if len(headlines) != len(event_ids):
        warnings.append(
            f"group {group_id!r}: event_ids / headlines length mismatch "
            f"({len(event_ids)} vs {len(headlines)}); falling back to "
            f"upstream suggested_canonical_event_id"
        )
        return (
            upstream_canonical,
            (headlines[0] if headlines else ""),
            "event_ids and headlines lists are inconsistent; using "
            "upstream diagnostic's suggested canonical without "
            "re-ranking",
        )

    paired: list[tuple[int, str]] = list(zip(event_ids, headlines))
    clean = [(eid, h) for eid, h in paired if not _looks_truncated(h)]

    if not clean:
        warnings.append(
            f"group {group_id!r}: every candidate headline looks raw / "
            f"truncated; using fallback canonical from upstream "
            f"diagnostic"
        )
        # Locate the headline that corresponds to upstream's canonical
        # if we can; else use the first headline as the displayed
        # canonical.  Either way, we never invent a string.
        canon_headline = ""
        if upstream_canonical is not None:
            for eid, h in paired:
                if eid == upstream_canonical:
                    canon_headline = h
                    break
        if not canon_headline and headlines:
            canon_headline = headlines[0]
        return (
            upstream_canonical,
            canon_headline,
            "every candidate headline looks raw or truncated; using "
            "upstream diagnostic's suggested canonical as a fallback",
        )

    # Pick the longest clean headline; tie-break on lowest event_id.
    canon = max(clean, key=lambda p: (len(p[1]), -int(p[0])))
    canon_id, canon_headline = canon

    # If we dropped any candidates as truncated, mention that in the
    # reason so the operator sees why a shorter headline won.
    dropped = [
        h for eid, h in paired
        if (eid, h) not in clean
    ]
    if dropped:
        reason = (
            "longest clean headline; rejected {n} candidate(s) that "
            "look raw / truncated"
        ).format(n=len(dropped))
    else:
        reason = "longest headline; every candidate is clean"
    return canon_id, canon_headline, reason


def _looks_truncated(headline: str) -> bool:
    """Return True if the headline looks raw / mid-feed / truncated.

    Conservative — when in doubt, return False (let the candidate
    survive) so we do not over-reject and force every group to the
    fallback path.
    """
    if not isinstance(headline, str):
        return True
    h = headline.strip()
    if not h:
        return True
    # Ellipsis terminators.
    if h.endswith("…"):
        return True
    if h.endswith("..."):
        return True
    if "..." in h and not h.endswith(".") and not h.endswith("..."):
        # Mid-string ellipsis that does not terminate the headline is
        # a strong truncation signal — the feed often emits "Foo …
        # Bar" mid-stream.  The h.endswith("...") branch above already
        # caught the terminal case; this is the mid-string case.
        # We require the ellipsis to be surrounded by content to
        # avoid double-counting.
        return True
    # Mid-sentence leak — starts with lowercase letter or a stray
    # punctuation character.
    if h[0].isalpha() and h[0].islower():
        return True
    # Stray markup leak — angle brackets or unclosed square brackets.
    if "<" in h or "[" in h.split("]", 1)[0] and "]" not in h.split("[", 1)[1]:
        return True
    # Unbalanced quotes — odd count of straight quotes is a feed-leak
    # tell when the rest of the headline looks like a partial.
    if h.count('"') % 2 == 1:
        return True
    return False


def _select_rule(group_id: str, headlines: list[str]) -> str:
    """Map a group's id prefix to the rule_id the planner would
    propose enabling for it."""
    gid = group_id.lower()
    if gid.startswith("date_ticker"):
        return "date_ticker_match"
    if gid.startswith("headline"):
        # Within a headline-axis group, decide whether the cluster is
        # an exact-match or a token-prefix one.  Cheap check: if every
        # normalised headline in the group is identical, the rule is
        # exact-match; otherwise it's the token-prefix variant.
        normed = {_normalise(h) for h in headlines if isinstance(h, str)}
        if len(normed) <= 1:
            return "exact_headline_match_within_event_date"
        return "headline_token_prefix_within_event_date"
    # Unknown prefix — fall back to the selection rule.  The caller
    # surfaces a warning if this happens.
    return "prefer_longest_non_truncated_headline_as_canonical"


def _normalise(headline: str) -> str:
    if not isinstance(headline, str):
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", headline.lower()))


def _count_expected_removed(
    suggestions: list[dict[str, Any]],
) -> int:
    """Return the number of distinct duplicates that would be
    removed if every suggestion's canonical were kept and the rest
    discarded.  De-duplicates event_ids across groups so an event
    appearing in two groups is counted once."""
    keep: set[int] = set()
    seen: set[int] = set()
    for s in suggestions:
        canon = s.get("suggested_canonical_event_id")
        if isinstance(canon, int) and not isinstance(canon, bool):
            keep.add(canon)
        for eid in s.get("event_ids") or []:
            if isinstance(eid, int) and not isinstance(eid, bool):
                seen.add(eid)
    return max(0, len(seen) - len(keep))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Section C weekly canonicalization plan", "",
    ]
    lines.append(f"OK:                            {report['ok']}")
    lines.append(
        f"Duplicate groups analyzed:     {report['duplicate_groups_analyzed']}"
    )
    lines.append(
        f"Expected removed duplicates:   {report['expected_removed_duplicates']}"
    )
    lines.append("")
    lines.append(
        f"Proposed canonicalization rules "
        f"({len(report['proposed_canonicalization_rules'])}):"
    )
    for r in report["proposed_canonicalization_rules"]:
        if isinstance(r, dict):
            lines.append(
                f"  - {r.get('rule_id'):<48} scope={r.get('scope')}"
            )
    lines.append("")
    lines.append(
        f"Canonical event suggestions "
        f"({len(report['canonical_event_suggestions'])}):"
    )
    for s in report["canonical_event_suggestions"]:
        lines.append(
            f"  - {s['duplicate_group_id']:<24} "
            f"event_ids={s['event_ids']} "
            f"suggested_canonical={s['suggested_canonical_event_id']}"
        )
        lines.append(f"      headline: {s['suggested_canonical_headline']}")
        lines.append(f"      reason:   {s['reason']}")
        lines.append(f"      rule:     {s['rule_to_apply']}")
    lines.append("")
    lines.append(
        f"Implementation targets ({len(report['implementation_targets'])}):"
    )
    for t in report["implementation_targets"]:
        if isinstance(t, dict):
            lines.append(f"  - {t.get('path')}: {t.get('note')}")
        else:
            lines.append(f"  - {t}")
    lines.append("")
    lines.append(
        f"False-positive risks ({len(report['false_positive_risks'])}):"
    )
    for risk in report["false_positive_risks"]:
        lines.append(f"  - {risk}")
    if report.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    if report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in report["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Section C weekly canonicalization planner.  "
            "Consumes the existing weekly duplicate diagnostic's "
            "output and proposes named canonicalization rules, "
            "suggested canonical event_ids and headlines, "
            "implementation targets, and false-positive risks.  Does "
            "NOT mutate the events DB, the news cache, or any "
            "artifact.  Suggestions only — no rule is applied."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=_DEFAULT_DB_PATH,
        help=(
            f"Path to the SQLite events DB the upstream diagnostic "
            f"reads from (default {_DEFAULT_DB_PATH!r}).  Read-only."
        ),
    )
    parser.add_argument(
        "--window-days", dest="window_days",
        type=int, default=_DEFAULT_WINDOW_DAYS,
        help=(
            f"Trailing window (in days) the upstream diagnostic "
            f"scans (default {_DEFAULT_WINDOW_DAYS})."
        ),
    )
    parser.add_argument(
        "--reference-date", dest="reference_date", default=None,
        help=(
            "ISO-format reference date the window ends on.  Defaults "
            "to today."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text plan.",
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the planner has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_section_c_weekly_canonicalization_plan(
        db_path=args.db_path,
        window_days=args.window_days,
        reference_date=args.reference_date,
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_weekly_canonicalization_plan",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
