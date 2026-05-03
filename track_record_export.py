"""
track_record_export.py

Export serializers for the mechanism-family + regime + compound-regime
performance breakdown produced by ``track_record_breakdown``.

Three research-friendly output formats, all pure composers on top of the
breakdown dict — no DB access, no provider calls.

  * ``build_breakdown_json(breakdown)``      — structured JSON envelope
  * ``build_breakdown_csv(breakdown)``       — flat multi-section CSV
  * ``build_breakdown_markdown(breakdown)``  — desk-note style memo

Design rules
------------
* Deterministic column order + row ordering.  Two exports of the same
  breakdown diff to zero.
* Empty dimensions render as an empty-table section, never a missing
  one, so memo / report templates can rely on the section layout.
* Hit rates / returns / coverage stay in their decimal form (0.67) in
  JSON and as "67%" / "+2.3%" in the human-facing markdown.  CSV keeps
  the raw numbers so spreadsheet tools can format them.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Column contracts
# ---------------------------------------------------------------------------

_BREAKDOWN_NUMERIC_FIELDS: tuple[str, ...] = (
    "total", "validated", "contradicted", "unresolved", "revisit_scored",
    "hit_rate", "coverage",
    "avg_return_5d", "avg_return_20d", "avg_support_ratio",
)

# One CSV row per dimension entry; per-dimension the identity column differs
# (family / regime_key / state).  ``_CSV_SECTIONS`` spells this out so the
# writer is declarative.
_CSV_SECTIONS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    # (section_title, breakdown_key, identity_columns, identity_value_fn_key)
    (
        "# by_mechanism_family",
        "by_mechanism_family",
        ("family", "family_label"),
        "family",
    ),
    (
        "# by_regime",
        "by_regime",
        ("regime_key", "inflation", "policy_stance"),
        "regime_key",
    ),
    (
        "# by_compound_regime",
        "by_compound_regime",
        ("state", "label"),
        "state",
    ),
    (
        "# by_proof_quality",
        "by_proof_quality",
        ("bucket", "label"),
        "bucket",
    ),
    (
        "# by_policy_status",
        "by_policy_status",
        ("status", "label"),
        "status",
    ),
    (
        "# by_overall_vulnerability",
        "by_overall_vulnerability",
        ("tier", "label"),
        "tier",
    ),
    # Engine-phase dimensions — additive sections appended after the
    # existing ones so any consumer that reads sections by index keeps
    # working.  Identity columns are the verbatim stored tokens — no
    # ``label`` field, no humanised display value.
    (
        "# by_quality_tier",
        "by_quality_tier",
        ("tier",),
        "tier",
    ),
    (
        "# by_mechanism_subtype",
        "by_mechanism_subtype",
        ("subtype", "family"),
        "subtype",
    ),
    (
        "# by_tradable",
        "by_tradable",
        ("bucket",),
        "bucket",
    ),
)


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


def build_breakdown_json(breakdown: dict, *, pretty: bool = False) -> dict:
    """Return a JSON-serialisable envelope for the breakdown payload.

    The envelope adds a stable ``schema`` tag + top-of-file ``generated_at``
    so downstream tools (memo pipelines, research notebooks) can branch on
    schema versions later without re-parsing the whole body.

    ``pretty`` is accepted for API symmetry with the CSV/markdown builders
    but has no effect on the dict return value — pretty printing is a
    serialisation concern handled by the caller.
    """
    del pretty  # accepted for symmetry; no-op in the dict builder
    return {
        "schema":       "track_record_breakdown.v1",
        "generated_at": breakdown.get("generated_at")
                        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "total_events":       breakdown.get("total_events", 0),
            "validated_total":    breakdown.get("validated_total", 0),
            "contradicted_total": breakdown.get("contradicted_total", 0),
            "unresolved_total": (
                (breakdown.get("total_events", 0) or 0)
                - (breakdown.get("validated_total", 0) or 0)
                - (breakdown.get("contradicted_total", 0) or 0)
            ),
            "revisit_scored":      breakdown.get("revisit_scored", 0),
            "hit_rate":            breakdown.get("hit_rate"),
            # Additive proof-discipline counts — existing summary keys
            # kept in place so older consumers don't regress.
            "proof_backed":        breakdown.get("proof_backed", 0),
            "falsifier_triggered": breakdown.get("falsifier_triggered", 0),
            "low_information":     breakdown.get("low_information", 0),
        },
        "by_mechanism_family":      list(breakdown.get("by_mechanism_family") or []),
        "by_regime":                list(breakdown.get("by_regime") or []),
        "by_compound_regime":       list(breakdown.get("by_compound_regime") or []),
        "by_proof_quality":         list(breakdown.get("by_proof_quality") or []),
        "by_policy_status":         list(breakdown.get("by_policy_status") or []),
        "by_overall_vulnerability": list(breakdown.get("by_overall_vulnerability") or []),
        # Engine-phase dimensions — additive; keys above are byte-stable.
        "by_quality_tier":          list(breakdown.get("by_quality_tier") or []),
        "by_mechanism_subtype":     list(breakdown.get("by_mechanism_subtype") or []),
        "by_tradable":              list(breakdown.get("by_tradable") or []),
    }


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _csv_row(entry: dict, identity_cols: tuple[str, ...]) -> list[str]:
    """Render one breakdown entry as a CSV row.

    Identity columns lead, then the universal metric columns, then the
    raw counts.  Missing fields render as empty string.
    """
    ordered: list[Any] = [entry.get(c) for c in identity_cols]
    for f in _BREAKDOWN_NUMERIC_FIELDS:
        ordered.append(entry.get(f))
    return [_csv_cell(v) for v in ordered]


def build_breakdown_csv(breakdown: dict) -> str:
    """Render the breakdown as a flat multi-section CSV.

    Section header rows (``# by_mechanism_family`` etc.) separate the
    per-dimension tables so a single file carries every slice.  Each
    section starts with a column-header row spelling out the identity
    columns + ``_BREAKDOWN_NUMERIC_FIELDS``.  Empty sections still emit
    their header so the layout is predictable.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")

    # Top-of-file summary row — two-column key/value for readability.
    writer.writerow(["# summary"])
    writer.writerow(["metric", "value"])
    writer.writerow(["schema", "track_record_breakdown.v1"])
    writer.writerow([
        "generated_at",
        breakdown.get("generated_at")
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ])
    for key in ("total_events", "validated_total", "contradicted_total",
                "revisit_scored", "hit_rate",
                "proof_backed", "falsifier_triggered", "low_information"):
        writer.writerow([key, _csv_cell(breakdown.get(key))])
    writer.writerow([])  # blank separator

    for title, breakdown_key, identity_cols, _identity_value_key in _CSV_SECTIONS:
        writer.writerow([title])
        header = list(identity_cols) + list(_BREAKDOWN_NUMERIC_FIELDS)
        writer.writerow(header)
        entries = breakdown.get(breakdown_key) or []
        for entry in entries:
            writer.writerow(_csv_row(entry, identity_cols))
        writer.writerow([])  # blank separator between sections

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Markdown export — research-memo style
# ---------------------------------------------------------------------------


def _fmt_pct(value: Any) -> str:
    """Format [0,1] hit-rate / coverage as a percentage for the memo."""
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_return(value: Any) -> str:
    """Format a mean return in signed percent form (+2.3% / −1.4%)."""
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def _fmt_int(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "—"


def _markdown_table(
    headers: tuple[str, ...],
    rows: Iterable[tuple[str, ...]],
) -> str:
    """Render a compact GitHub-style markdown table."""
    lines: list[str] = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    any_row = False
    for row in rows:
        any_row = True
        lines.append("| " + " | ".join(row) + " |")
    if not any_row:
        lines.append("| " + " | ".join(["—"] * len(headers)) + " |")
    return "\n".join(lines)


def _family_rows(entries: list[dict]) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for e in entries:
        out.append((
            e.get("family_label") or e.get("family") or "—",
            _fmt_int(e.get("total")),
            f"{_fmt_int(e.get('validated'))}/{_fmt_int(e.get('contradicted'))}/{_fmt_int(e.get('unresolved'))}",
            _fmt_pct(e.get("hit_rate")),
            _fmt_pct(e.get("coverage")),
            _fmt_return(e.get("avg_return_5d")),
            _fmt_return(e.get("avg_return_20d")),
        ))
    return out


def _regime_rows(entries: list[dict]) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for e in entries:
        regime = e.get("regime_key") or "—"
        out.append((
            regime,
            _fmt_int(e.get("total")),
            f"{_fmt_int(e.get('validated'))}/{_fmt_int(e.get('contradicted'))}/{_fmt_int(e.get('unresolved'))}",
            _fmt_pct(e.get("hit_rate")),
            _fmt_return(e.get("avg_return_5d")),
            _fmt_return(e.get("avg_return_20d")),
        ))
    return out


def _compound_rows(entries: list[dict]) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for e in entries:
        out.append((
            e.get("label") or e.get("state") or "—",
            _fmt_int(e.get("total")),
            f"{_fmt_int(e.get('validated'))}/{_fmt_int(e.get('contradicted'))}/{_fmt_int(e.get('unresolved'))}",
            _fmt_pct(e.get("hit_rate")),
            _fmt_return(e.get("avg_return_5d")),
            _fmt_return(e.get("avg_return_20d")),
        ))
    return out


def _proof_quality_rows(entries: list[dict]) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for e in entries:
        out.append((
            e.get("label") or e.get("bucket") or "—",
            _fmt_int(e.get("total")),
            f"{_fmt_int(e.get('validated'))}/{_fmt_int(e.get('contradicted'))}/{_fmt_int(e.get('unresolved'))}",
            _fmt_pct(e.get("hit_rate")),
            _fmt_return(e.get("avg_return_5d")),
            _fmt_return(e.get("avg_return_20d")),
        ))
    return out


def _policy_status_rows(entries: list[dict]) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for e in entries:
        out.append((
            e.get("label") or e.get("status") or "—",
            _fmt_int(e.get("total")),
            f"{_fmt_int(e.get('validated'))}/{_fmt_int(e.get('contradicted'))}/{_fmt_int(e.get('unresolved'))}",
            _fmt_pct(e.get("hit_rate")),
            _fmt_return(e.get("avg_return_5d")),
            _fmt_return(e.get("avg_return_20d")),
        ))
    return out


def _vulnerability_rows(entries: list[dict]) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for e in entries:
        out.append((
            e.get("label") or e.get("tier") or "—",
            _fmt_int(e.get("total")),
            f"{_fmt_int(e.get('validated'))}/{_fmt_int(e.get('contradicted'))}/{_fmt_int(e.get('unresolved'))}",
            _fmt_pct(e.get("hit_rate")),
            _fmt_return(e.get("avg_return_5d")),
            _fmt_return(e.get("avg_return_20d")),
        ))
    return out


def _quality_tier_rows(entries: list[dict]) -> list[tuple[str, ...]]:
    """Render engine quality_tier entries with verbatim stored tokens."""
    out: list[tuple[str, ...]] = []
    for e in entries:
        tier = e.get("tier") or "—"
        out.append((
            f"`{tier}`" if tier != "—" else tier,
            _fmt_int(e.get("total")),
            f"{_fmt_int(e.get('validated'))}/{_fmt_int(e.get('contradicted'))}/{_fmt_int(e.get('unresolved'))}",
            _fmt_pct(e.get("hit_rate")),
            _fmt_return(e.get("avg_return_5d")),
            _fmt_return(e.get("avg_return_20d")),
        ))
    return out


def _subtype_rows(entries: list[dict]) -> list[tuple[str, ...]]:
    """Render mechanism_subtype entries with verbatim stored tokens.

    Subtype + family are rendered as raw underscore-separated tokens —
    no underscore-to-space rewrite, no title-casing.
    """
    out: list[tuple[str, ...]] = []
    for e in entries:
        subtype = e.get("subtype") or "—"
        family  = (e.get("family") or "").strip()
        cell    = f"`{subtype}`" if subtype != "—" else subtype
        if family:
            cell = f"{cell} · `{family}`"
        out.append((
            cell,
            _fmt_int(e.get("total")),
            f"{_fmt_int(e.get('validated'))}/{_fmt_int(e.get('contradicted'))}/{_fmt_int(e.get('unresolved'))}",
            _fmt_pct(e.get("hit_rate")),
            _fmt_return(e.get("avg_return_5d")),
            _fmt_return(e.get("avg_return_20d")),
        ))
    return out


def _tradable_rows(entries: list[dict]) -> list[tuple[str, ...]]:
    """Render tradable entries with verbatim stored tokens."""
    out: list[tuple[str, ...]] = []
    for e in entries:
        bucket = e.get("bucket") or "—"
        out.append((
            f"`{bucket}`" if bucket != "—" else bucket,
            _fmt_int(e.get("total")),
            f"{_fmt_int(e.get('validated'))}/{_fmt_int(e.get('contradicted'))}/{_fmt_int(e.get('unresolved'))}",
            _fmt_pct(e.get("hit_rate")),
            _fmt_return(e.get("avg_return_5d")),
            _fmt_return(e.get("avg_return_20d")),
        ))
    return out


def build_breakdown_markdown(breakdown: dict) -> str:
    """Render the breakdown as a research-memo style markdown document.

    Structure:
      # Track-record breakdown
      Subtitle: total events, overall hit rate, generated_at
      ## By mechanism family
      ## By regime
      ## By compound regime
    """
    total = breakdown.get("total_events", 0)
    validated = breakdown.get("validated_total", 0)
    contradicted = breakdown.get("contradicted_total", 0)
    hit_rate = breakdown.get("hit_rate")
    generated = (
        breakdown.get("generated_at")
        or datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    unresolved = max(
        int(total or 0) - int(validated or 0) - int(contradicted or 0), 0,
    )

    out: list[str] = []
    out.append("# Track-record breakdown")
    out.append("")
    out.append(
        f"Events: **{total}** · "
        f"validated/contradicted/unresolved: **{validated}/{contradicted}/{unresolved}** · "
        f"overall hit rate: **{_fmt_pct(hit_rate)}** · "
        f"generated: `{generated}`"
    )
    out.append("")
    out.append(
        f"Proof discipline: "
        f"**{_fmt_int(breakdown.get('proof_backed'))}** proof-backed · "
        f"**{_fmt_int(breakdown.get('falsifier_triggered'))}** falsifier-triggered · "
        f"**{_fmt_int(breakdown.get('low_information'))}** low-information"
    )
    out.append("")

    out.append("## By mechanism family")
    out.append("")
    out.append(_markdown_table(
        ("Family", "N", "V/C/U", "Hit rate", "Coverage", "Avg 5d", "Avg 20d"),
        _family_rows(breakdown.get("by_mechanism_family") or []),
    ))
    out.append("")

    out.append("## By regime (inflation / policy stance)")
    out.append("")
    out.append(_markdown_table(
        ("Regime", "N", "V/C/U", "Hit rate", "Avg 5d", "Avg 20d"),
        _regime_rows(breakdown.get("by_regime") or []),
    ))
    out.append("")

    out.append("## By compound regime")
    out.append("")
    out.append(_markdown_table(
        ("Compound state", "N", "V/C/U", "Hit rate", "Avg 5d", "Avg 20d"),
        _compound_rows(breakdown.get("by_compound_regime") or []),
    ))
    out.append("")

    out.append("## By proof quality")
    out.append("")
    out.append(_markdown_table(
        ("Bucket", "N", "V/C/U", "Hit rate", "Avg 5d", "Avg 20d"),
        _proof_quality_rows(breakdown.get("by_proof_quality") or []),
    ))
    out.append("")

    out.append("## By policy status")
    out.append("")
    out.append(_markdown_table(
        ("Status", "N", "V/C/U", "Hit rate", "Avg 5d", "Avg 20d"),
        _policy_status_rows(breakdown.get("by_policy_status") or []),
    ))
    out.append("")

    out.append("## By overall vulnerability")
    out.append("")
    out.append(_markdown_table(
        ("Tier", "N", "V/C/U", "Hit rate", "Avg 5d", "Avg 20d"),
        _vulnerability_rows(breakdown.get("by_overall_vulnerability") or []),
    ))
    out.append("")

    out.append("## By engine quality tier")
    out.append("")
    out.append(_markdown_table(
        ("Tier", "N", "V/C/U", "Hit rate", "Avg 5d", "Avg 20d"),
        _quality_tier_rows(breakdown.get("by_quality_tier") or []),
    ))
    out.append("")

    out.append("## By mechanism subtype")
    out.append("")
    out.append(_markdown_table(
        ("Subtype", "N", "V/C/U", "Hit rate", "Avg 5d", "Avg 20d"),
        _subtype_rows(breakdown.get("by_mechanism_subtype") or []),
    ))
    out.append("")

    out.append("## By tradable")
    out.append("")
    out.append(_markdown_table(
        ("Bucket", "N", "V/C/U", "Hit rate", "Avg 5d", "Avg 20d"),
        _tradable_rows(breakdown.get("by_tradable") or []),
    ))
    out.append("")

    out.append("---")
    out.append(
        "_V/C/U = validated · contradicted · unresolved.  Hit rate excludes "
        "unresolved events.  Avg 5d / 20d are mean best-ticker returns within "
        "each bucket._"
    )
    return "\n".join(out)
