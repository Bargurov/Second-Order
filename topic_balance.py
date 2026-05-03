"""Deterministic topic-balance audit over recent + surfaced headlines.

Question this answers
---------------------
"Is oil/war dominating the app because it genuinely is the most
relevant thing happening, or because the ranking layer is biased?"

The audit takes two streams:

* ``recent_headlines`` — the raw feed (what the world actually is).
* ``surfaced_headlines`` — what the app chose to put on top (clusters,
  promoted headlines, etc.).

It classifies every headline into a theme family using the same
keyword maps the rest of the stack uses (``news_consensus._SECTOR_KEYWORDS``
+ ``_ACTION_KEYWORDS``) and produces:

* Per-family share of each stream.
* Concentration metrics: HHI, effective-N, top-3 share.
* Per-family bias flags: when surfaced share diverges from recent
  share by more than a threshold, the family is flagged as
  ``over_surfaced`` or ``under_surfaced`` with a severity bucket.

Design discipline
-----------------
* Pure composer: no I/O, no DB reads, never raises on malformed input.
* Output is a structured dict; the markdown formatter is a view.
* Thresholds are pinned module constants so ``calibrate_thresholds``
  can audit them.  Same input → same report.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Constants — pinned so drift is visible in diffs.
# ---------------------------------------------------------------------------

# Concentration bands applied to HHI (Herfindahl-Hirschman Index).
#   HHI >= 0.40 → very concentrated (near-monopoly of themes)
#   HHI >= 0.25 → concentrated
#   HHI >= 0.15 → moderate
#   HHI <  0.15 → diversified
_HHI_VERY_CONCENTRATED: float = 0.40
_HHI_CONCENTRATED:      float = 0.25
_HHI_MODERATE:          float = 0.15

# Bias deltas (surfaced_share − recent_share in percentage points of
# the pooled universe).  The larger absolute delta, the stronger the
# flag severity.
_BIAS_LARGE:  float = 0.20
_BIAS_MEDIUM: float = 0.10
_BIAS_SMALL:  float = 0.05

# Minimum surfaced share required to flag a family as
# ``over_surfaced``.  Below this the flag is noise (e.g. one lonely
# cluster that doesn't exist in the recent pool).
_MIN_SURFACE_SHARE_FOR_FLAG: float = 0.10

# Minimum total sample before concentration claims are trustworthy.
_MIN_SAMPLE_FOR_CLAIM: int = 8

CONCENTRATION_BANDS: tuple = (
    "diversified", "moderate", "concentrated", "very_concentrated",
)

BIAS_KINDS: tuple = ("balanced", "over_surfaced", "under_surfaced")


# ---------------------------------------------------------------------------
# Headline classification
# ---------------------------------------------------------------------------

def _headline_text(record: Any) -> str:
    if isinstance(record, str):
        return record
    if isinstance(record, dict):
        for key in ("title", "headline", "text"):
            v = record.get(key)
            if isinstance(v, str) and v.strip():
                return v
    return ""


def classify_headline_theme(text: str) -> dict[str, str]:
    """Classify a single headline into ``{sector, action}``.

    Uses the keyword maps already in ``news_consensus``.  Import is
    lazy so tests that monkeypatch the maps see fresh state.
    """
    if not isinstance(text, str) or not text.strip():
        return {"sector": "unclassified", "action": "unknown"}

    from news_consensus import _SECTOR_KEYWORDS, _scan_action, _scan_keywords

    sectors = _scan_keywords(text, _SECTOR_KEYWORDS)
    action = _scan_action(text)
    return {
        "sector": sectors[0] if sectors else "unclassified",
        "action": action,
    }


def _classify_batch(
    headlines: Iterable[Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in headlines or []:
        text = _headline_text(rec)
        theme = classify_headline_theme(text)
        out.append({
            "text":   text,
            "sector": theme["sector"],
            "action": theme["action"],
        })
    return out


# ---------------------------------------------------------------------------
# Concentration math
# ---------------------------------------------------------------------------

def _distribution(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        bucket = r.get(key) or "unclassified"
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def _shares(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values()) if counts else 0
    if total == 0:
        return {}
    return {k: v / total for k, v in counts.items()}


def _hhi(shares: dict[str, float]) -> float:
    if not shares:
        return 0.0
    return sum(s * s for s in shares.values())


def _effective_n(hhi: float) -> float:
    if hhi <= 0:
        return 0.0
    return 1.0 / hhi


def _top_share(shares: dict[str, float], n: int) -> float:
    if not shares:
        return 0.0
    ordered = sorted(shares.values(), reverse=True)
    return sum(ordered[:n])


def _concentration_band(hhi: float) -> str:
    if hhi >= _HHI_VERY_CONCENTRATED:
        return "very_concentrated"
    if hhi >= _HHI_CONCENTRATED:
        return "concentrated"
    if hhi >= _HHI_MODERATE:
        return "moderate"
    return "diversified"


def _concentration_block(
    rows: list[dict[str, Any]], *, key: str,
) -> dict[str, Any]:
    counts = _distribution(rows, key)
    shares = _shares(counts)
    hhi = _hhi(shares)
    return {
        "total":          sum(counts.values()) if counts else 0,
        "distribution":   counts,
        "shares":         {k: round(v, 3) for k, v in shares.items()},
        "hhi":            round(hhi, 3),
        "effective_n":    round(_effective_n(hhi), 2),
        "top1_share":     round(_top_share(shares, 1), 3),
        "top3_share":     round(_top_share(shares, 3), 3),
        "band":           _concentration_band(hhi),
    }


# ---------------------------------------------------------------------------
# Bias detection — surfaced vs recent
# ---------------------------------------------------------------------------

def _severity(delta: float) -> str:
    a = abs(delta)
    if a >= _BIAS_LARGE:
        return "large"
    if a >= _BIAS_MEDIUM:
        return "medium"
    if a >= _BIAS_SMALL:
        return "small"
    return "noise"


def _bias_flags(
    recent_shares: dict[str, float],
    surfaced_shares: dict[str, float],
) -> list[dict[str, Any]]:
    """Return per-family bias flags ordered by |delta| desc.

    An ``over_surfaced`` flag fires when a family's surfaced share
    exceeds its recent share by at least ``_BIAS_MEDIUM`` AND the
    surfaced share itself is ≥ ``_MIN_SURFACE_SHARE_FOR_FLAG`` (one
    stray cluster shouldn't trip the alarm).  ``under_surfaced`` is
    the mirror case.
    """
    if not recent_shares and not surfaced_shares:
        return []
    families = set(recent_shares) | set(surfaced_shares)
    flags: list[dict[str, Any]] = []
    for fam in sorted(families):
        r = recent_shares.get(fam, 0.0)
        s = surfaced_shares.get(fam, 0.0)
        delta = s - r
        severity = _severity(delta)

        kind = "balanced"
        if severity in ("medium", "large"):
            if delta > 0 and s >= _MIN_SURFACE_SHARE_FOR_FLAG:
                kind = "over_surfaced"
            elif delta < 0 and r >= _MIN_SURFACE_SHARE_FOR_FLAG:
                kind = "under_surfaced"

        flags.append({
            "family":         fam,
            "recent_share":   round(r, 3),
            "surfaced_share": round(s, 3),
            "delta":          round(delta, 3),
            "severity":       severity,
            "kind":           kind,
        })
    flags.sort(key=lambda f: (-abs(f["delta"]), f["family"]))
    return flags


def _oil_war_check(
    recent_shares: dict[str, float],
    surfaced_shares: dict[str, float],
) -> dict[str, Any]:
    """Targeted check: is energy/defense dominating because the recent
    feed warrants it, or because surfacing is biased?

    Returns a dict with per-family ``recent_share``, ``surfaced_share``,
    ``reads_as``:

      * ``not_dominant``     — family is not >30% of either stream.
      * ``reflecting_reality`` — family is dominant in both streams at
                                  comparable levels (delta within small).
      * ``over_surfaced``    — surfaced share materially > recent share.
      * ``under_surfaced``   — surfaced share materially < recent share.
    """
    out: dict[str, Any] = {}
    for fam in ("energy", "defense", "military_action_conflict"):
        # The classifier only emits sector families, not the action
        # "military action" — synthesize a conflict read from the
        # actions tally upstream and expose the combined lens here.
        r = recent_shares.get(fam, 0.0)
        s = surfaced_shares.get(fam, 0.0)
        delta = s - r
        if max(r, s) < 0.30:
            reads_as = "not_dominant"
        elif abs(delta) < _BIAS_SMALL:
            reads_as = "reflecting_reality"
        elif delta > 0:
            reads_as = "over_surfaced"
        else:
            reads_as = "under_surfaced"
        out[fam] = {
            "recent_share":   round(r, 3),
            "surfaced_share": round(s, 3),
            "delta":          round(delta, 3),
            "reads_as":       reads_as,
        }
    return out


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_topic_balance(
    recent_headlines: Optional[list[Any]],
    *,
    surfaced_headlines: Optional[list[Any]] = None,
) -> dict[str, Any]:
    """Produce a deterministic topic-balance report.

    Args:
        recent_headlines:   Raw headline records (str or dict with a
                            ``title``/``headline`` key).
        surfaced_headlines: Optional subset representing what the
                            ranking layer chose to surface.  When
                            ``None``, bias flags are skipped.

    Returns:
        {
          "available":   bool,
          "recent":      {concentration block + action_distribution},
          "surfaced":    {same shape} | None,
          "bias_flags":  [...]                              # empty when surfaced is None
          "oil_war_check": {...}                            # energy/defense/conflict
          "sample_note": "...",                             # flags thin samples
          "rationale":   "...",                             # one-line summary
        }

    Never raises on malformed input; non-string / non-dict records are
    skipped.
    """
    recent_rows    = _classify_batch(recent_headlines or [])
    surfaced_rows  = _classify_batch(surfaced_headlines or []) \
        if surfaced_headlines is not None else None

    recent_sector = _concentration_block(recent_rows, key="sector")
    recent_action = _concentration_block(recent_rows, key="action")
    recent_block = {
        "sector_mix": recent_sector,
        "action_mix": recent_action,
    }

    surfaced_block: Optional[dict[str, Any]] = None
    bias_flags: list[dict[str, Any]] = []
    oil_war: dict[str, Any] = {}

    if surfaced_rows is not None:
        surfaced_sector = _concentration_block(surfaced_rows, key="sector")
        surfaced_action = _concentration_block(surfaced_rows, key="action")
        surfaced_block = {
            "sector_mix": surfaced_sector,
            "action_mix": surfaced_action,
        }
        bias_flags = _bias_flags(
            recent_sector["shares"], surfaced_sector["shares"],
        )
        oil_war = _oil_war_check(
            recent_sector["shares"], surfaced_sector["shares"],
        )
        # The action tally lets us include the military-conflict lens
        # in the oil/war check even though it's classified as an
        # action, not a sector.
        conflict_recent   = recent_action["shares"].get("military action", 0.0)
        conflict_surfaced = surfaced_action["shares"].get("military action", 0.0)
        oil_war["military_action_conflict"] = {
            "recent_share":   round(conflict_recent, 3),
            "surfaced_share": round(conflict_surfaced, 3),
            "delta":          round(conflict_surfaced - conflict_recent, 3),
            "reads_as": (
                "not_dominant" if max(conflict_recent, conflict_surfaced) < 0.30
                else "reflecting_reality" if abs(conflict_surfaced - conflict_recent) < _BIAS_SMALL
                else "over_surfaced" if conflict_surfaced > conflict_recent
                else "under_surfaced"
            ),
        }

    total_recent = recent_sector["total"]
    total_surfaced = (surfaced_block or {}).get("sector_mix", {}).get("total", 0)
    sample_note: list[str] = []
    if total_recent < _MIN_SAMPLE_FOR_CLAIM:
        sample_note.append(
            f"recent sample thin ({total_recent} headlines)"
        )
    if surfaced_rows is not None and total_surfaced < _MIN_SAMPLE_FOR_CLAIM:
        sample_note.append(
            f"surfaced sample thin ({total_surfaced} headlines)"
        )

    rationale_bits: list[str] = []
    rationale_bits.append(
        f"recent: {recent_sector['band']} (HHI "
        f"{recent_sector['hhi']}, top-3 "
        f"{int(round(recent_sector['top3_share'] * 100))}%)"
    )
    if surfaced_block:
        rationale_bits.append(
            f"surfaced: {surfaced_block['sector_mix']['band']} "
            f"(HHI {surfaced_block['sector_mix']['hhi']}, top-3 "
            f"{int(round(surfaced_block['sector_mix']['top3_share'] * 100))}%)"
        )
    large_bias = [f for f in bias_flags if f["severity"] == "large"]
    if large_bias:
        names = ", ".join(f["family"] for f in large_bias[:3])
        rationale_bits.append(f"large biases: {names}")

    return {
        "available":   bool(recent_rows),
        "recent":      recent_block,
        "surfaced":    surfaced_block,
        "bias_flags":  bias_flags,
        "oil_war_check": oil_war,
        "sample_note": "; ".join(sample_note) or None,
        "rationale":   "; ".join(rationale_bits),
    }


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------

def _fmt_pct(v: Any) -> str:
    if isinstance(v, (int, float)):
        return f"{int(round(float(v) * 100))}%"
    return "—"


def _fmt_sector_table(block: dict[str, Any]) -> list[str]:
    shares = block.get("shares") or {}
    if not shares:
        return ["_no data_"]
    lines = ["| Family | Count | Share |", "|---|---:|---:|"]
    ordered = sorted(shares.items(), key=lambda kv: -kv[1])
    dist = block.get("distribution") or {}
    for fam, share in ordered:
        lines.append(
            f"| {fam} | {dist.get(fam, 0)} | {_fmt_pct(share)} |"
        )
    return lines


def _fmt_concentration_line(block: dict[str, Any]) -> str:
    return (
        f"HHI={block.get('hhi', 0.0)} |"
        f"effective-N={block.get('effective_n', 0.0)} |"
        f"top-1={_fmt_pct(block.get('top1_share'))} |"
        f"top-3={_fmt_pct(block.get('top3_share'))} |"
        f"**band={block.get('band', '—')}**"
    )


def format_topic_balance_report(report: Optional[dict[str, Any]]) -> str:
    """Render a topic-balance report as markdown."""
    if not isinstance(report, dict):
        return ""

    lines: list[str] = ["# Topic Balance Audit", ""]
    if report.get("sample_note"):
        lines.append(f"> [!] {report['sample_note']}")
        lines.append("")
    lines.append(report.get("rationale") or "")
    lines.append("")

    recent = (report.get("recent") or {}).get("sector_mix") or {}
    lines.append("## Recent - sector mix")
    lines.append(_fmt_concentration_line(recent))
    lines.append("")
    lines.extend(_fmt_sector_table(recent))
    lines.append("")

    surfaced = (report.get("surfaced") or {}).get("sector_mix") \
        if report.get("surfaced") else None
    if surfaced:
        lines.append("## Surfaced - sector mix")
        lines.append(_fmt_concentration_line(surfaced))
        lines.append("")
        lines.extend(_fmt_sector_table(surfaced))
        lines.append("")

        flags = report.get("bias_flags") or []
        if flags:
            lines.append("## Bias flags")
            lines.append("| Family | Recent | Surfaced | Delta | Severity | Kind |")
            lines.append("|---|---:|---:|---:|---|---|")
            for f in flags:
                lines.append(
                    f"| {f['family']} | {_fmt_pct(f['recent_share'])} | "
                    f"{_fmt_pct(f['surfaced_share'])} | "
                    f"{_fmt_pct(f['delta'])} | {f['severity']} | {f['kind']} |"
                )
            lines.append("")

        ow = report.get("oil_war_check") or {}
        if ow:
            lines.append("## Oil / war dominance read")
            for fam, row in ow.items():
                lines.append(
                    f"- **{fam}**: recent {_fmt_pct(row['recent_share'])}  "
                    f"-> surfaced {_fmt_pct(row['surfaced_share'])}  "
                    f"| {row['reads_as'].replace('_', ' ')}"
                )
            lines.append("")
    else:
        lines.append("## Surfaced stream")
        lines.append("_no surfaced stream provided - run with a "
                     "surfaced-headlines input to get bias flags._")
        lines.append("")

    action_block = (report.get("recent") or {}).get("action_mix") or {}
    if action_block.get("distribution"):
        lines.append("## Recent - action tally")
        lines.extend(_fmt_sector_table(action_block))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
