#!/usr/bin/env python3
"""Section C — Daily Market headline quality diagnostic.

A read-only diagnostic over the local Daily Market headline inbox
(``news_inbox.json`` by default).  For every candidate headline the
diagnostic classifies why a downstream filter would (or would not)
keep it and surfaces an aggregate per category so an operator can
see, at a glance, which buckets the noise is concentrated in.

The diagnostic does **not** change the filters, mutate the inbox,
write to any DB, or hit a provider.  It is descriptive: it tells the
operator what the inbox looks like today; the decision to retune the
filter remains a separate, manual step.

Why this exists
---------------

The frontend "Daily Market" page surfaces headlines that have cleared
the news pipeline's relevance filter.  When the bar is too loose the
page fills with junk; when it is too tight, real signals get dropped.
Section C is the diagnostic the operator runs to see what is in the
inbox **before** it reaches the filter — junk, raw legal text, off-
topic, vague, duplicate, or missing-mechanism — without touching the
pipeline.

Read-only by construction
-------------------------

* Single input: the local ``news_inbox.json`` (or any JSON path
  passed via ``--input``).  Opens in read mode only.
* No DB writes anywhere.  No ``yfinance``, ``market_data``, LLM, or
  paid provider call.  No FastAPI surface (never imports ``api`` or
  ``routes.*``).
* Uses ``news_relevance.is_relevant`` and friends for the off-topic
  check — they are pure-Python pattern matchers with no side effects.
  Lazy-imported so this module's top-level import surface stays
  narrow.
* Conservative wording: every per-candidate ``inclusion_reason`` /
  ``exclusion_reason`` and every recommended-rule note is descriptive,
  never causal.  Banned tokens in emitted prose: ``proof``,
  ``proven``, ``validated``, ``guaranteed``, ``automatically``,
  ``alpha generated``, ``correct ticker``.

Categories (priority order)
---------------------------

A candidate is placed in the FIRST category that fits:

1. ``junk_headlines``         — empty / whitespace / single-token /
                                  marketing fluff headline.
2. ``raw_legal_text_cases``    — docket / case-citation language
                                  (``v.``, ``vs.``, ``case no.``,
                                  ``petitioner``, ``respondent``,
                                  ``subpoena``, ``indictment``,
                                  ``docket``) above a token-count
                                  threshold.
3. ``off_topic_cases``         — ``news_relevance.is_relevant``
                                  returns False.
4. ``vague_cases``             — under N words, or matches a generic
                                  phrase list (``"market update"``,
                                  ``"today's top stories"``,
                                  ``"market wrap"``).
5. ``duplicate_cases``         — same normalised headline already
                                  surfaced earlier in the inbox.
6. ``missing_mechanism_cases`` — entry presents a ``mechanism_family``
                                  field but the value is null / empty /
                                  ``"none"``.  When NO entry carries
                                  the field at all, this category is
                                  zero and a warning is surfaced
                                  (the inbox source-schema does not
                                  carry mechanism_family yet).
7. ``accepted_like_candidates`` — passes every check above.  "-like"
                                  because the diagnostic does not
                                  itself accept a candidate; it only
                                  reports that no exclusion fired.

Output contract (JSON)::

    {
      "ok":                            bool,
      "candidates_checked":            int,
      "accepted_like_candidates":      [candidate, ...],
      "junk_headlines":                [candidate, ...],
      "raw_legal_text_cases":          [candidate, ...],
      "off_topic_cases":               [candidate, ...],
      "vague_cases":                   [candidate, ...],
      "duplicate_cases":               [candidate, ...],
      "missing_mechanism_cases":       [candidate, ...],
      "recommended_daily_filter_rules":[dict, ...],
      "warnings":                      [str, ...],
      "errors":                        [str, ...],
    }

Each candidate is a 9-field dict::

    {
      "event_id":              int | None,
      "headline":              str,
      "event_date":            str | None,
      "primary_ticker":        str | None,
      "mechanism_family":      str | None,
      "market_relevance_score":float,   # [0.0, 1.0]
      "diagnostic_tags":       [str, ...],
      "inclusion_reason":      str | None,
      "exclusion_reason":      str | None,
    }

Usage::

    python scripts/section_c_daily_quality_diagnostic.py --json
    python scripts/section_c_daily_quality_diagnostic.py \\
        --input news_inbox.json --json
    python scripts/section_c_daily_quality_diagnostic.py \\
        --input my_inbox.json --output artifacts/section_c_diagnostic.json
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


_DEFAULT_INPUT_PATH: str = "news_inbox.json"

# Threshold above which a repeat pattern triggers a recommended-rule
# suggestion in ``recommended_daily_filter_rules``.  Below this, the
# signal is too thin to bother the operator with a tuning note.
_RECOMMENDED_RULE_COUNT_THRESHOLD: int = 2

# Maximum keyword matches the relevance score will count before it
# saturates to 1.0.  Five is the rough density of a "rich" headline
# (sector + actor + verb).
_RELEVANCE_SCORE_SATURATION: int = 5

# Vague headlines: short word count OR matches one of these generic
# phrases (matched case-insensitive, substring).
_VAGUE_WORD_COUNT_MAX: int = 4
_VAGUE_GENERIC_PHRASES: tuple[str, ...] = (
    "market update",
    "market wrap",
    "today's top stories",
    "today's news",
    "morning briefing",
    "evening briefing",
    "headlines roundup",
    "news roundup",
)


# Raw-legal-text detector — token counts of citation / docket vocabulary.
_LEGAL_TOKENS_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?:v\.|vs\.|case\s+no\.?|docket(?:\s+entry)?|petitioner|"
    r"respondent|subpoena|indictment|in\s+re\b|plaintiff|defendant|"
    r"per\s+curiam|complaint\s+filed|motion\s+to\s+dismiss|"
    r"cv-\d|cr-\d)\b",
    re.IGNORECASE,
)

# A headline must hit this many legal tokens to qualify as raw legal
# text.  Two matches keeps single-mention business news (e.g. "Apple
# v Samsung patent case settled") out of the legal bucket.
_LEGAL_TOKEN_THRESHOLD: int = 2


# ---------------------------------------------------------------------------
# Patchable seam
# ---------------------------------------------------------------------------


def _load_daily_market_candidates(
    input_path: str | None,
    *,
    errors:   list[str],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Load candidate headlines from the inbox file.

    Returns a list of entry dicts.  Each dict is treated as a candidate
    and walked through the classifier.  Tests patch this seam directly
    with synthetic payloads so they never depend on a real inbox.

    The loader is read-only — it opens the file with ``"r"`` and never
    writes back.  Missing files surface an error string and return
    ``[]``; malformed JSON does the same.
    """
    if not input_path:
        errors.append(
            "--input is required and no default inbox path could be "
            "resolved"
        )
        return []
    path = Path(input_path)
    if not path.exists():
        errors.append(
            f"inbox path does not exist on disk: {input_path!r}"
        )
        return []
    try:
        with open(input_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(
            f"failed to parse inbox as JSON: "
            f"{type(exc).__name__}: {exc}"
        )
        return []
    if not isinstance(raw, list):
        errors.append(
            f"inbox root must be a JSON list, got "
            f"{type(raw).__name__}"
        )
        return []
    candidates: list[dict[str, Any]] = []
    for idx, entry in enumerate(raw):
        if isinstance(entry, dict):
            candidates.append(entry)
        else:
            warnings.append(
                f"inbox entry[{idx}] is not a JSON object ({type(entry).__name__})"
                f"; skipped"
            )
    return candidates


def _default_input_path() -> str:
    """Return the default inbox path.  Always returns a string — the
    file may not exist; the seam reports that as an error."""
    return _DEFAULT_INPUT_PATH


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_section_c_daily_quality_diagnostic(
    *,
    input_path:  str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Run the Section C daily-quality diagnostic.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    if input_path is None:
        input_path = _default_input_path()

    raw_entries = _load_daily_market_candidates(
        input_path,
        errors=errors, warnings=warnings,
    )

    # Detect whether the source-schema carries ``mechanism_family`` at
    # all.  If not, suppress the missing_mechanism bucket and surface a
    # warning — the inbox simply is not classified yet, and tagging
    # every entry as missing-mechanism would be noise.
    any_entry_has_mechanism = any(
        "mechanism_family" in entry for entry in raw_entries
    )
    if raw_entries and not any_entry_has_mechanism:
        warnings.append(
            "inbox entries do not carry a mechanism_family field; "
            "missing_mechanism_cases is reported as zero for this run"
        )

    # Build candidate envelopes (the 9-field dict) for every entry.
    candidates: list[dict[str, Any]] = [
        _candidate_envelope(idx, entry)
        for idx, entry in enumerate(raw_entries)
    ]

    # First-pass classification — single-headline checks.
    seen_normalised: dict[str, int] = {}
    junk:       list[dict[str, Any]] = []
    legal:      list[dict[str, Any]] = []
    off_topic:  list[dict[str, Any]] = []
    vague:      list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    missing_mechanism: list[dict[str, Any]] = []
    accepted:   list[dict[str, Any]] = []

    for candidate in candidates:
        headline = candidate["headline"] or ""
        # 1. Junk.
        if _is_junk_headline(headline):
            candidate["diagnostic_tags"].append("junk")
            candidate["exclusion_reason"] = "junk_headline"
            junk.append(candidate)
            continue
        # 2. Raw legal text.
        if _is_raw_legal_text(headline):
            candidate["diagnostic_tags"].append("raw_legal_text")
            candidate["exclusion_reason"] = "raw_legal_text"
            legal.append(candidate)
            continue
        # 3. Off-topic.
        if not _is_relevant_headline(headline):
            candidate["diagnostic_tags"].append("off_topic")
            candidate["exclusion_reason"] = "off_topic"
            off_topic.append(candidate)
            continue
        # 4. Vague.
        if _is_vague_headline(headline):
            candidate["diagnostic_tags"].append("vague")
            candidate["exclusion_reason"] = "vague_short_headline"
            vague.append(candidate)
            continue
        # 5. Duplicate.
        norm = _normalised_for_duplicate_check(headline)
        if norm and norm in seen_normalised:
            candidate["diagnostic_tags"].append("duplicate")
            candidate["exclusion_reason"] = "duplicate_headline"
            duplicates.append(candidate)
            continue
        if norm:
            seen_normalised[norm] = candidate["event_id"] \
                if candidate["event_id"] is not None else -1
        # 6. Missing mechanism — only applies when the source-schema
        # carries the field at all.
        if any_entry_has_mechanism:
            mech = candidate["mechanism_family"]
            if not _is_valid_mechanism(mech):
                candidate["diagnostic_tags"].append("missing_mechanism")
                candidate["exclusion_reason"] = "missing_mechanism"
                missing_mechanism.append(candidate)
                continue
        # 7. Accepted-like.
        candidate["inclusion_reason"] = "passes_filters"
        accepted.append(candidate)

    recommended_rules = _build_recommended_rules(
        junk_count=len(junk),
        legal_count=len(legal),
        off_topic_count=len(off_topic),
        vague_count=len(vague),
        duplicate_count=len(duplicates),
        missing_mechanism_count=len(missing_mechanism),
    )

    envelope: dict[str, Any] = {
        "ok":                              not errors,
        "candidates_checked":              len(candidates),
        "accepted_like_candidates":        accepted,
        "junk_headlines":                  junk,
        "raw_legal_text_cases":            legal,
        "off_topic_cases":                 off_topic,
        "vague_cases":                     vague,
        "duplicate_cases":                 duplicates,
        "missing_mechanism_cases":         missing_mechanism,
        "recommended_daily_filter_rules":  recommended_rules,
        "warnings":                        warnings,
        "errors":                          errors,
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
# Helpers — candidate construction
# ---------------------------------------------------------------------------


def _candidate_envelope(
    idx: int, entry: dict[str, Any],
) -> dict[str, Any]:
    """Build the 9-field candidate dict from one inbox entry.

    The diagnostic accepts both ``title`` (the inbox key) and
    ``headline`` (the events-table key) so the same script can be
    aimed at either source via the seam.
    """
    headline_raw = entry.get("headline")
    if not isinstance(headline_raw, str):
        headline_raw = entry.get("title")
    if not isinstance(headline_raw, str):
        headline_raw = ""
    event_date = _maybe_event_date(entry)
    mech = entry.get("mechanism_family") if "mechanism_family" in entry \
        else None
    primary_ticker = entry.get("primary_ticker")
    if not isinstance(primary_ticker, str) or not primary_ticker.strip():
        primary_ticker = None
    event_id_raw = entry.get("event_id")
    if isinstance(event_id_raw, int) and not isinstance(event_id_raw, bool):
        event_id: int | None = event_id_raw
    else:
        event_id = idx
    score = _relevance_score(headline_raw)
    return {
        "event_id":               event_id,
        "headline":               headline_raw,
        "event_date":             event_date,
        "primary_ticker":         primary_ticker,
        "mechanism_family":       mech if (mech is None or isinstance(mech, str)) else None,
        "market_relevance_score": score,
        "diagnostic_tags":        [],
        "inclusion_reason":       None,
        "exclusion_reason":       None,
    }


def _maybe_event_date(entry: dict[str, Any]) -> str | None:
    for key in ("event_date", "published_at", "date"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            # Slice to the ISO date portion to keep downstream renders
            # tidy.  No mutation of the inbox — this is a copy.
            return value[:10] if len(value) >= 10 else value
    return None


# ---------------------------------------------------------------------------
# Helpers — classifiers
# ---------------------------------------------------------------------------


def _is_junk_headline(headline: str) -> bool:
    stripped = (headline or "").strip()
    if not stripped:
        return True
    tokens = stripped.split()
    if len(tokens) <= 1:
        return True
    return False


def _is_raw_legal_text(headline: str) -> bool:
    matches = _LEGAL_TOKENS_PATTERN.findall(headline or "")
    return len(matches) >= _LEGAL_TOKEN_THRESHOLD


def _is_relevant_headline(headline: str) -> bool:
    """Wrap ``news_relevance.is_relevant`` so the import stays lazy.

    Returns True if the headline carries an economic / policy
    transmission channel; False otherwise.  The diagnostic flags
    False-returns as off-topic.
    """
    try:
        from news_relevance import is_relevant as _is_relevant
    except Exception:  # noqa: BLE001 — degrade gracefully if the
        # relevance module cannot be imported.  Treat such cases as
        # "we cannot say" → relevant (avoid false-flagging everything
        # as off-topic when the module is missing).
        return True
    try:
        return bool(_is_relevant(headline or ""))
    except Exception:  # noqa: BLE001 — surface as relevant on error.
        return True


def _is_vague_headline(headline: str) -> bool:
    stripped = (headline or "").strip()
    if not stripped:
        return False
    tokens = stripped.split()
    if len(tokens) < _VAGUE_WORD_COUNT_MAX:
        return True
    low = stripped.lower()
    for phrase in _VAGUE_GENERIC_PHRASES:
        if phrase in low:
            return True
    return False


def _normalised_for_duplicate_check(headline: str) -> str:
    """Lower-case, collapse whitespace, strip punctuation for a stable
    duplicate key.  No mutation of the source headline."""
    if not headline:
        return ""
    low = headline.lower()
    low = re.sub(r"[\s ]+", " ", low).strip()
    low = re.sub(r"[^\w\s]", "", low)
    return low


def _is_valid_mechanism(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip().lower()
    if not stripped:
        return False
    if stripped == "none":
        return False
    return True


def _relevance_score(headline: str) -> float:
    """Count relevance-keyword hits in the headline; cap and scale to
    [0.0, 1.0].

    Junk / empty headlines score 0.0.  Headlines with many keyword
    hits saturate at 1.0.  The score is descriptive — not a verdict
    of any kind.
    """
    if not headline or not headline.strip():
        return 0.0
    low = headline.lower()
    try:
        from news_relevance import (
            RELEVANCE_KEYWORDS,
            _WB_PATTERN,
        )
    except Exception:  # noqa: BLE001 — relevance module unavailable.
        return 0.0
    hits = 0
    for kw in RELEVANCE_KEYWORDS:
        if kw in low:
            hits += 1
            if hits >= _RELEVANCE_SCORE_SATURATION:
                break
    if hits < _RELEVANCE_SCORE_SATURATION:
        try:
            wb_matches = _WB_PATTERN.findall(low)
        except Exception:  # noqa: BLE001
            wb_matches = []
        hits += len(wb_matches)
    capped = min(hits, _RELEVANCE_SCORE_SATURATION)
    return float(capped) / float(_RELEVANCE_SCORE_SATURATION)


# ---------------------------------------------------------------------------
# Helpers — recommended rules
# ---------------------------------------------------------------------------


_RULE_NOTES: dict[str, str] = {
    "junk": (
        "{n} candidate(s) tagged junk_headline (empty / whitespace / "
        "single-token); consider adding a minimum-token-count guard "
        "at the inbox-ingestion step."
    ),
    "raw_legal_text": (
        "{n} candidate(s) tagged raw_legal_text (docket / case-citation "
        "tokens above threshold); consider routing these to a "
        "separate legal-filings worklist rather than the daily-market "
        "page."
    ),
    "off_topic": (
        "{n} candidate(s) tagged off_topic by the existing relevance "
        "filter; descriptive observation only — no change to the "
        "filter is proposed here."
    ),
    "vague": (
        "{n} candidate(s) tagged vague (short word count or generic "
        "wrap phrase); consider adding a minimum-headline-length "
        "guard or a generic-phrase reject pattern."
    ),
    "duplicate": (
        "{n} candidate(s) tagged duplicate of an earlier inbox row; "
        "consider deduplicating by normalised headline at ingestion."
    ),
    "missing_mechanism": (
        "{n} candidate(s) carry a null / empty / 'none' "
        "mechanism_family; consider gating the daily-market surface "
        "on a non-empty mechanism_family value."
    ),
}


def _build_recommended_rules(
    *,
    junk_count:              int,
    legal_count:             int,
    off_topic_count:         int,
    vague_count:             int,
    duplicate_count:         int,
    missing_mechanism_count: int,
) -> list[dict[str, Any]]:
    """Emit a descriptive rule suggestion for each category whose count
    crosses the threshold.  Suggestions are notes, not commands —
    every entry is phrased so the operator decides whether to act."""
    counts: list[tuple[str, int]] = [
        ("junk",              junk_count),
        ("raw_legal_text",    legal_count),
        ("off_topic",         off_topic_count),
        ("vague",             vague_count),
        ("duplicate",         duplicate_count),
        ("missing_mechanism", missing_mechanism_count),
    ]
    rules: list[dict[str, Any]] = []
    for tag, n in counts:
        if n < _RECOMMENDED_RULE_COUNT_THRESHOLD:
            continue
        note = _RULE_NOTES.get(tag, "").format(n=n)
        rules.append({
            "tag":   tag,
            "count": n,
            "note":  note,
        })
    return rules


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Section C daily-quality diagnostic", ""]
    lines.append(f"OK:                            {report['ok']}")
    lines.append(f"Candidates checked:            {report['candidates_checked']}")
    lines.append(
        f"Accepted-like:                 "
        f"{len(report['accepted_like_candidates'])}"
    )
    lines.append(f"Junk headlines:                {len(report['junk_headlines'])}")
    lines.append(
        f"Raw legal text cases:          "
        f"{len(report['raw_legal_text_cases'])}"
    )
    lines.append(f"Off-topic cases:               {len(report['off_topic_cases'])}")
    lines.append(f"Vague cases:                   {len(report['vague_cases'])}")
    lines.append(f"Duplicate cases:               {len(report['duplicate_cases'])}")
    lines.append(
        f"Missing-mechanism cases:       "
        f"{len(report['missing_mechanism_cases'])}"
    )
    rules = report.get("recommended_daily_filter_rules") or []
    lines.append(f"Recommended-rule suggestions:  {len(rules)}")
    for r in rules:
        if isinstance(r, dict):
            lines.append(
                f"  - {r.get('tag')!r} count={r.get('count')}: "
                f"{r.get('note')}"
            )
        else:
            lines.append(f"  - {r}")
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
            "Read-only Section C daily-quality diagnostic.  Inspects "
            "the local Daily Market headline inbox (news_inbox.json "
            "by default) and reports which candidates are junk, raw "
            "legal text, off-topic, vague, duplicates, or missing a "
            "mechanism_family.  Descriptive only — never mutates the "
            "inbox, never changes the relevance filter, never claims "
            "the filter is broken."
        ),
    )
    parser.add_argument(
        "--input", dest="input_path", default=None,
        help=(
            "Path to a JSON inbox file.  Defaults to "
            f"{_DEFAULT_INPUT_PATH!r}.  Read-only."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the diagnostic has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_section_c_daily_quality_diagnostic(
        input_path=args.input_path,
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_daily_quality_diagnostic",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
