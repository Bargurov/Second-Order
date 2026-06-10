"""Track-record scoring-rule sensitivity — pure scoring logic.

The canonical track-record rule (`db.compute_track_record`) is a generous
ANY-support OR-rule: one supporting ticker makes an event count as validated,
even against several contradictions. That is useful but attackable. This module
recomputes the SAME accepted event set under several transparent rules
side-by-side so a reader can see how sensitive the validated / contradicted /
unresolved breakdown is to that generosity.

This is **disclosure, not a truth claim**. No rule is asserted "correct", the
canonical headline rule is unchanged, and every rule shares one denominator.

Rules
-----
- ``any_support``        — >=1 supporting ticker -> validated; else >=1
  contradicting -> contradicted; else unresolved. Matches the canonical rule.
- ``majority``           — supporting count vs contradicting count; tie or no
  direction -> unresolved.
- ``evidence_weighted``  — supporting weight vs contradicting weight, using a
  per-ticker evidence weight. No canonical per-ticker weight exists in the
  corpus, so every directional ticker defaults to weight 1.0 and this rule
  reduces to ``majority`` on the live archive (reported as an explicit delta).
  It diverges from majority only when per-ticker weights are present.
- ``all_support_strict`` — validated only if every directional ticker supports
  and none contradicts; any contradiction -> contradicted; no direction ->
  unresolved. The sharpest contrast to the generous ANY-support rule.

Per-ticker direction is read through ``db._resolve_direction_tag`` (the same
``supports`` / ``contradicts`` prefix convention the canonical scorer uses) so
the ANY-support rule matches the canonical breakdown exactly.

Pure: no DB query, no provider, no network, no event-study math. The only db
dependency is the tag-prefix resolver, imported lazily.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

__all__ = (
    "RULES",
    "CANONICAL_RULE",
    "EVIDENCE_TIER_WEIGHTS",
    "EVIDENCE_WEIGHT_FALLBACK_NOTE",
    "SCORING_NON_CLAIMS",
    "normalize_ticker",
    "event_evidence",
    "score_event_under_rule",
    "summarize_rules",
)


RULES: tuple[str, ...] = (
    "any_support", "majority", "evidence_weighted", "all_support_strict",
)
CANONICAL_RULE = "any_support"

# Evidence-quality tier -> weight. Mirrors the task's transparent scheme. These
# apply only when a per-ticker tier is present; the live corpus carries none.
EVIDENCE_TIER_WEIGHTS: dict[str, float] = {
    "high": 1.0, "provisional": 0.5, "low": 0.15,
}
_DEFAULT_WEIGHT = 1.0

EVIDENCE_WEIGHT_FALLBACK_NOTE = (
    "No canonical per-ticker evidence weight exists in the corpus; every "
    "directional ticker is weighted 1.0, so evidence_weighted reduces to "
    "majority on the current archive (reported as changed_vs_majority). The "
    "weighted rule diverges from majority only when per-ticker evidence "
    "weights are present."
)

SCORING_NON_CLAIMS: tuple[str, ...] = (
    "Alternative scoring rules shown side-by-side for sensitivity disclosure; "
    "no rule is claimed correct and the canonical headline rule stays "
    "any_support.",
    "Every rule is evaluated over the SAME accepted track-record event set (one "
    "denominator); the counts are descriptive, carry no statistical-significance "
    "claim, and are not a prediction.",
    "validated / contradicted / unresolved are the project's canonical labels, "
    "not confirmed verdicts.",
    "Representative disagreement cases are illustrative, not evidence.",
    "Separate from the closed Phase 1 / Phase 2 FDR pools; no pool q-values are "
    "used or implied.",
)


# ---------------------------------------------------------------------------
# Per-ticker normalization
# ---------------------------------------------------------------------------

_RESOLVE_TAG = None  # cached db._resolve_direction_tag


def _resolve_tag(t: Any) -> str:
    """Direction tag for a ticker dict via the canonical resolver.

    Reuses ``db._resolve_direction_tag`` (handles both ``direction_tag`` on
    market_tickers and ``direction`` on revisit snapshots) so this module can
    never drift from the canonical prefix convention. Falls back to a local
    read if db is unimportable.
    """
    global _RESOLVE_TAG
    if _RESOLVE_TAG is None:
        try:
            from db import _resolve_direction_tag
            _RESOLVE_TAG = _resolve_direction_tag
        except Exception:
            _RESOLVE_TAG = False  # sentinel: use local fallback
    if _RESOLVE_TAG:
        try:
            return _RESOLVE_TAG(t) or ""
        except Exception:
            pass
    if isinstance(t, dict):
        return str(t.get("direction_tag") or t.get("direction") or "")
    return ""


def _ticker_weight(t: Any) -> float:
    """Per-ticker evidence weight: explicit numeric weight, else an evidence
    tier mapped through ``EVIDENCE_TIER_WEIGHTS``, else the 1.0 fallback."""
    if not isinstance(t, dict):
        return _DEFAULT_WEIGHT
    w = t.get("evidence_weight")
    if isinstance(w, (int, float)) and not isinstance(w, bool):
        return float(w)
    tier = t.get("evidence_quality") or t.get("evidence_tier")
    if isinstance(tier, str):
        return EVIDENCE_TIER_WEIGHTS.get(tier.strip().lower(), _DEFAULT_WEIGHT)
    return _DEFAULT_WEIGHT


def normalize_ticker(t: Any) -> tuple[str, float]:
    """Return ``(direction, weight)`` where direction ∈
    ``{support, contradict, neutral}``. Non-dict / untagged / unknown-prefix
    tickers are ``neutral`` (excluded from directional counts)."""
    tag = _resolve_tag(t)
    weight = _ticker_weight(t)
    if isinstance(tag, str) and tag.startswith("supports"):
        return "support", weight
    if isinstance(tag, str) and tag.startswith("contradicts"):
        return "contradict", weight
    return "neutral", weight


def event_evidence(tickers: Iterable[Any]) -> dict[str, Any]:
    """Aggregate one event's directional evidence (counts + weights)."""
    sup_n = con_n = 0
    sup_w = con_w = 0.0
    for t in tickers or []:
        direction, weight = normalize_ticker(t)
        if direction == "support":
            sup_n += 1
            sup_w += weight
        elif direction == "contradict":
            con_n += 1
            con_w += weight
    return {
        "sup_n": sup_n,
        "con_n": con_n,
        "dir_n": sup_n + con_n,
        "sup_w": sup_w,
        "con_w": con_w,
        "mixed": sup_n >= 1 and con_n >= 1,
    }


# ---------------------------------------------------------------------------
# Per-event scoring
# ---------------------------------------------------------------------------


def score_event_under_rule(tickers: Iterable[Any], rule: str) -> str:
    """Classify one event as ``validated`` / ``contradicted`` / ``unresolved``
    under ``rule``. Raises :class:`ValueError` on an unknown rule."""
    if rule not in RULES:
        raise ValueError(f"unknown rule {rule!r}; expected one of {RULES}")
    ev = event_evidence(tickers)
    sup_n, con_n, dir_n = ev["sup_n"], ev["con_n"], ev["dir_n"]

    if rule == "any_support":
        if sup_n >= 1:
            return "validated"
        if con_n >= 1:
            return "contradicted"
        return "unresolved"
    if rule == "majority":
        if sup_n > con_n:
            return "validated"
        if con_n > sup_n:
            return "contradicted"
        return "unresolved"
    if rule == "evidence_weighted":
        if ev["sup_w"] > ev["con_w"]:
            return "validated"
        if ev["con_w"] > ev["sup_w"]:
            return "contradicted"
        return "unresolved"
    # all_support_strict
    if dir_n == 0:
        return "unresolved"
    if con_n == 0 and sup_n >= 1:
        return "validated"
    return "contradicted"


# ---------------------------------------------------------------------------
# Multi-rule summary over an event set
# ---------------------------------------------------------------------------


def summarize_rules(
    event_records: Sequence[dict],
    *,
    rules: Sequence[str] = RULES,
    canonical_rule: str = CANONICAL_RULE,
) -> dict[str, Any]:
    """Score every event under every rule and summarise side-by-side.

    ``event_records`` is the caller's accepted track-record set — each record a
    dict with ``event_id``, ``mechanism_family``, ``headline`` and ``tickers``
    (the already-selected directional ticker list, same source the canonical
    scorer used). The denominator is the record count and is IDENTICAL for every
    rule (no rule re-selects the event set).
    """
    records = list(event_records or [])
    denom = len(records)

    scored: list[tuple[dict, dict, dict]] = []
    for rec in records:
        tickers = rec.get("tickers") or []
        ev = event_evidence(tickers)
        outcomes = {rule: score_event_under_rule(tickers, rule) for rule in rules}
        scored.append((rec, ev, outcomes))

    canon = [oc[canonical_rule] for (_r, _e, oc) in scored]
    maj = [oc.get("majority") for (_r, _e, oc) in scored]

    def _pct(n: int) -> float:
        return round(100.0 * n / denom, 1) if denom else 0.0

    rules_out: dict[str, Any] = {}
    for rule in rules:
        v = sum(1 for (_r, _e, oc) in scored if oc[rule] == "validated")
        c = sum(1 for (_r, _e, oc) in scored if oc[rule] == "contradicted")
        u = sum(1 for (_r, _e, oc) in scored if oc[rule] == "unresolved")
        entry: dict[str, Any] = {
            "validated": v,
            "contradicted": c,
            "unresolved": u,
            "pct": {
                "validated": _pct(v),
                "contradicted": _pct(c),
                "unresolved": _pct(u),
            },
            "changed_vs_any_support": sum(
                1 for i, (_r, _e, oc) in enumerate(scored) if oc[rule] != canon[i]
            ),
        }
        if rule == "evidence_weighted" and "majority" in rules:
            entry["changed_vs_majority"] = sum(
                1 for i, (_r, _e, oc) in enumerate(scored) if oc[rule] != maj[i]
            )
            entry["weight_note"] = EVIDENCE_WEIGHT_FALLBACK_NOTE
        rules_out[rule] = entry

    composition = {
        "single_ticker": sum(1 for (_r, e, _o) in scored if e["dir_n"] == 1),
        "multi_ticker": sum(1 for (_r, e, _o) in scored if e["dir_n"] >= 2),
        "mixed_evidence": sum(1 for (_r, e, _o) in scored if e["mixed"]),
        "no_direction": sum(1 for (_r, e, _o) in scored if e["dir_n"] == 0),
    }

    disagreements: list[dict[str, Any]] = []
    for (rec, e, oc) in scored:
        if any(oc[rule] != oc[canonical_rule] for rule in rules):
            disagreements.append({
                "event_id": rec.get("event_id"),
                "mechanism_family": rec.get("mechanism_family"),
                "headline": (rec.get("headline") or "")[:80],
                "sup_n": e["sup_n"],
                "con_n": e["con_n"],
                "sup_w": round(e["sup_w"], 3),
                "con_w": round(e["con_w"], 3),
                "outcomes": dict(oc),
            })
    disagreements.sort(key=lambda d: (d["event_id"] is None, d["event_id"]))

    return {
        "denominator": denom,
        "canonical_rule": canonical_rule,
        "rules": rules_out,
        "composition": composition,
        "disagreements": disagreements,
        "evidence_weight_fallback": EVIDENCE_WEIGHT_FALLBACK_NOTE,
        "non_claims": list(SCORING_NON_CLAIMS),
    }
