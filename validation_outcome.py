"""Shared majority-rule validation-outcome helper.

Both ``/events`` and ``/portfolio`` classify an event's validation
status from the ``direction_tag`` field on its ``market_tickers``.  The
rule must match in both routes — mixing rules produced the earlier
audit blocker where ``/portfolio`` claimed "validated" on a single
supporting ticker even when contradicting tickers outnumbered it.

The rule
--------

Start from the tickers whose ``direction_tag`` starts with
``"supports"`` or ``"contradicts"``.  Ignore everything else
(``""`` / ``"pending"`` / unknown).

  * If no directional tags at all         → ``"no_data"``      (ratio None)
  * Otherwise count ``supporting`` + ``contradicting``:
      - both zero (tagged neutral rows)   → ``"unresolved"``   (ratio 0)
      - ``supporting > contradicting``    → ``"validated"``    (ratio)
      - else                              → ``"contradicted"`` (ratio)

The "else" branch collapses ties and ``contradicting > supporting`` into
``"contradicted"``; that matches the current behaviour of the
``/events`` route (``routes/events.py::_score_validation``).

``ratio`` is ``supporting / (supporting + contradicting)`` when there is
any directional data, else ``None``.  It's a convenience for callers
that want to show "support ratio 60%" without re-scanning the tickers.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Weighted event-level evidence — see EVALUATION.md "Weighted Event
# Evidence" section for the representative-fixture check that produced
# these thresholds.
# ---------------------------------------------------------------------------

# Event-level bands.  Mirror the per-ticker bands in
# ``validation_evidence.py`` so the vocabulary stays consistent — a
# ticker whose own evidence is ``supportive`` contributes +0.7..+1.0,
# so an event aggregate that clears +0.35 is backed by at least one
# firm per-ticker supportive read (or multiple half-weight tag votes).
_EVT_SUPPORTIVE: float = 0.35
_EVT_CONTRADICTORY: float = -0.35

# Scoring weights.  A ticker that carries a full per-horizon
# ``evidence_score`` gets weight 1.0; a ticker with only a
# ``direction_tag`` gets half weight, reflecting that a tag alone is
# weaker evidence than a horizon-backed read.  Tag-only contributions
# sit at +/-0.5 so an all-tag cohort can still tilt the aggregate
# into a verdict when the signal is unanimous.
_W_EVIDENCE_SCORE: float = 1.0
_W_DIRECTION_TAG:  float = 0.5
_TAG_CONTRIBUTION: float = 0.5

# A verdict needs enough scorable tickers *and* enough total weight.
# Two tag-only tickers (weight 1.0) is the floor — one lonely ticker
# is never enough to call an event supportive or contradictory.
_MIN_SCORABLE_TICKERS: int = 2
_MIN_AGGREGATE_WEIGHT: float = 1.0

# Asymmetric primary-asset weighting — when a primary (direct
# single-name) ticker contradicts the thesis, the contribution is
# multiplied by this factor so the event-level read can't ignore a
# direct-name move that goes the wrong way.  Confirmations on primary
# assets retain the base contribution: a primary tape-following the
# thesis is the expected case, while a primary tape-fighting it is
# the read that forces a re-evaluation.
_W_PRIMARY_CONTRADICTION: float = 1.5

EVIDENCE_LABELS: tuple = (
    "supportive", "mixed", "contradictory", "insufficient",
)


def score_validation_outcome(
    tickers: list,
) -> tuple[str, Optional[float]]:
    """Return ``(label, ratio)`` using the majority rule above.

    ``tickers`` may be any iterable of dicts; entries without a string
    ``direction_tag`` are skipped.  Returns ``("no_data", None)`` on
    empty input / no tagged rows.  Never raises.
    """
    if not isinstance(tickers, list):
        return ("no_data", None)

    supporting = 0
    contradicting = 0
    tagged_total = 0
    for t in tickers:
        if not isinstance(t, dict):
            continue
        tag = t.get("direction_tag") or ""
        if not isinstance(tag, str) or not tag:
            continue
        tagged_total += 1
        if tag.startswith("supports"):
            supporting += 1
        elif tag.startswith("contradicts"):
            contradicting += 1

    if tagged_total == 0:
        return ("no_data", None)

    directional = supporting + contradicting
    if directional == 0:
        # Tagged rows present but none are directional (all "neutral" /
        # "pending" / unknown-prefix).
        return ("unresolved", 0.0)

    ratio = supporting / directional
    if supporting > contradicting:
        return ("validated", ratio)
    return ("contradicted", ratio)


def score_validation_label(tickers: list) -> str:
    """Label-only shorthand for callers that don't use the ratio.

    Collapses ``"no_data"`` into ``"unresolved"`` so consumers that
    don't distinguish between "no tickers at all" and "tickers with no
    directional tags" see a single string.  ``/events`` wants this
    shape because its response doesn't carry a ratio field.
    """
    label, _ratio = score_validation_outcome(tickers)
    return "unresolved" if label == "no_data" else label


# ---------------------------------------------------------------------------
# Weighted event-level evidence
# ---------------------------------------------------------------------------

def _safe_float(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        if f != f:   # NaN
            return None
        return f
    return None


def _tag_sign(direction_tag: Any) -> int:
    """Map ``direction_tag`` to a sign: +1 supports, -1 contradicts, else 0."""
    if not isinstance(direction_tag, str):
        return 0
    if direction_tag.startswith("supports"):
        return 1
    if direction_tag.startswith("contradicts"):
        return -1
    return 0


def _extract_primary_set(event: Any) -> Optional[set[str]]:
    """Return the explicit primary-symbol set for ``event``.

    Pulled from ``event.primary_assets`` (the analyst's committed
    direct-name picks).  Used by ``_is_primary_asset`` and
    ``_eligibility_tier`` to enforce that primary tier requires
    explicit classification — symbols outside this set fall back to
    secondary or rejected, never default to primary weight.

    Returns ``None`` when the event does not carry a ``primary_assets``
    field at all (legacy / test fixture / non-dict input).  In that
    case downstream callers fall back to the tightened single-name
    heuristic.  Returns a set (possibly empty) when the field is
    present — even an empty list signals "the analyst named no
    primary picks" and must engage strict mode so unmapped tickers
    cannot inherit primary weight.
    """
    if not isinstance(event, dict):
        return None
    bucket = event.get("primary_assets")
    if not isinstance(bucket, list):
        return None
    out: set[str] = set()
    for entry in bucket:
        sym: Any = None
        if isinstance(entry, dict):
            sym = entry.get("symbol") or entry.get("ticker")
        elif isinstance(entry, str):
            sym = entry
        if isinstance(sym, str) and sym.strip():
            out.add(sym.strip().upper())
    return out


def _is_primary_asset(
    symbol: Any,
    *,
    explicit_primary: set[str] | None = None,
) -> bool:
    """True when ``symbol`` is a direct single-name pick.

    Tightened: a registered ETF / hedge / FX / broad-market / foreign
    listing is NEVER primary regardless of explicit_primary — the
    registries are authoritative on rejection and signal-only role.

    When ``explicit_primary`` is provided, primary status requires the
    symbol to be in that set (the analyst's committed direct picks).
    Without explicit classification, an unmapped symbol cannot default
    to primary.

    When ``explicit_primary`` is None (legacy callers without event
    context), falls back to a tightened single-name heuristic
    (alpha-only, 1-5 chars, no dot, no caret) so existing call sites
    that haven't been threaded keep working without silently promoting
    typos or arbitrary tokens to primary weight.
    """
    if not isinstance(symbol, str):
        return False
    sym = symbol.strip().upper()
    if not sym:
        return False
    try:
        from asset_selection import (
            _BROAD_MARKET, _FX_ETFS, _HEDGE_ETFS, _INDEX_OR_BENCHMARK,
            _has_foreign_suffix, _ticker_channel,
        )
    except Exception:
        return False
    # Registries are authoritative — these can never be primary.
    if (
        sym in _BROAD_MARKET
        or sym in _INDEX_OR_BENCHMARK
        or sym in _HEDGE_ETFS
        or sym in _FX_ETFS
        or _has_foreign_suffix(sym)
        or _ticker_channel(sym) is not None
    ):
        return False
    # Explicit-classification path: the analyst's primary picks.
    if explicit_primary is not None:
        return sym in explicit_primary
    # Legacy back-compat heuristic — tightened to alpha-only / no
    # dotted symbols.  Production call sites should always supply
    # explicit_primary.
    return (
        sym.isalpha()
        and 1 <= len(sym) <= 5
        and "." not in sym
        and "^" not in sym
    )


# ---------------------------------------------------------------------------
# Per-tier validation weights — eligibility-driven contribution scaling
# ---------------------------------------------------------------------------
# Each ticker's contribution to the event-level weighted-evidence score
# is scaled by the asset's eligibility tier so the basket aggregate
# respects role separation:
#
#   * ``primary``  (direct single-name) — full weight (1.0).
#   * ``secondary`` (sector / commodity / bond ETF) — 0.7×; an ETF is
#     a basket read, structurally less specific than a direct pick.
#   * ``signal``   (vol / FX / inverse hedge ETF) — 0.0; hedge assets
#     confirm only through their named signal channel via
#     ``cross_asset_confirmation``, never through the event-level
#     aggregator.  Counting them here would let an off-thesis hedge
#     move tip the basket score in either direction.
#   * ``rejected`` (broad-market index / foreign / unknown) — 0.0.
#
# The existing ``_W_PRIMARY_CONTRADICTION`` multiplier stacks on top
# of the tier weight so a primary contradiction is the heaviest
# negative signal the aggregator can see.

_TIER_WEIGHT_PRIMARY:   float = 1.0
_TIER_WEIGHT_SECONDARY: float = 0.7
_TIER_WEIGHT_SIGNAL:    float = 0.0
_TIER_WEIGHT_REJECTED:  float = 0.0


def _eligibility_tier(
    symbol: Any,
    *,
    explicit_primary: set[str] | None = None,
) -> str:
    """Classify ``symbol`` into the validation-weighting tier:
    ``primary`` / ``secondary`` / ``signal`` / ``rejected``.

    Tightened: primary tier requires an explicit positive signal —
    either ``symbol`` is in ``explicit_primary`` (the event's
    ``primary_assets`` set), or — when no explicit set is supplied —
    the symbol passes a strict single-name heuristic (alpha-only,
    1-5 chars, no dot, no caret) AND is not in any
    ETF / hedge / FX / broad-market / foreign-suffix registry.

    Symbols that fail the strict heuristic and aren't explicitly
    primary land in ``secondary`` (when they pass the basic shape but
    the caller knows they aren't primary) or ``rejected`` (typos,
    dotted symbols, anything that doesn't look like a US listing) —
    never silently promoted to primary weight.

    Missing / empty / non-string symbols collapse to ``rejected`` —
    the previous "default to primary" behaviour silently inflated
    contribution weights for synthetic / unstamped rows.
    """
    if not isinstance(symbol, str):
        return "rejected"
    sym = symbol.strip().upper()
    if not sym:
        return "rejected"
    try:
        from asset_selection import (
            _BROAD_MARKET, _FX_ETFS, _HEDGE_ETFS, _INDEX_OR_BENCHMARK,
            _has_foreign_suffix, _ticker_channel,
        )
    except Exception:
        return "rejected"

    # Outright rejected: broad-market indices, price benchmarks,
    # foreign-primary listings.  Authoritative — explicit_primary
    # cannot override these.
    if (
        sym in _BROAD_MARKET
        or sym in _INDEX_OR_BENCHMARK
        or _has_foreign_suffix(sym)
    ):
        return "rejected"

    # Hedge / signal tier — vol / FX / inverse / leveraged.
    # Authoritative; explicit_primary cannot override these either —
    # signal-only assets confirm only through their named channel and
    # must not contribute primary weight to the event-level score.
    if sym in _HEDGE_ETFS or sym in _FX_ETFS:
        return "signal"

    # Routes via a sector / commodity / bond registry → secondary.
    # An ETF can never be primary, even when explicitly listed in
    # primary_assets — keeps the basket-vs-direct-name distinction
    # clean at the weighting layer.
    if _ticker_channel(sym) is not None:
        return "secondary"

    # Strict single-name shape — alpha-only, 1-5 chars, no special chars.
    looks_single_name = (
        sym.isalpha()
        and 1 <= len(sym) <= 5
        and "." not in sym
        and "^" not in sym
    )

    if explicit_primary is not None:
        # Explicit-classification path.  Symbols in the set get primary;
        # symbols outside it that pass the shape get secondary so they
        # can still contribute as evidence but cannot override a primary
        # read.  Off-shape unknowns are rejected.
        if sym in explicit_primary:
            return "primary"
        return "secondary" if looks_single_name else "rejected"

    # Legacy back-compat: no explicit set supplied.  Apply the
    # tightened heuristic — typos / dotted / off-shape symbols no
    # longer default to primary.
    if looks_single_name:
        return "primary"
    return "rejected"


def _tier_weight(tier: str) -> float:
    """Per-tier multiplier on contribution.  Hedge/signal and
    rejected tiers zero out — they don't count at the event level."""
    return {
        "primary":   _TIER_WEIGHT_PRIMARY,
        "secondary": _TIER_WEIGHT_SECONDARY,
        "signal":    _TIER_WEIGHT_SIGNAL,
        "rejected":  _TIER_WEIGHT_REJECTED,
    }.get(tier, 0.0)


def _ticker_contribution(
    t: dict,
    *,
    explicit_primary: set[str] | None = None,
) -> Optional[dict[str, Any]]:
    """Score one ticker.  Prefers per-ticker ``evidence_score`` (full
    weight); falls back to ``direction_tag`` (half weight).  Returns
    ``None`` when the ticker has neither — unscorable rows don't
    dilute the aggregate.

    Tier-weighted: primary single-name 1.0×, secondary ETF 0.7×,
    hedge/signal and rejected tickers 0.0× (they're dropped from the
    event-level aggregate; signal assets confirm only through their
    named channel via ``cross_asset_confirmation``).

    Primary single-name tickers get an extra contradiction-only
    multiplier (:data:`_W_PRIMARY_CONTRADICTION`) so a direct-name move
    opposite the expected direction tips the event-level read harder
    than the same move on a secondary ETF.

    ``explicit_primary``, when supplied, is the set of symbols the
    event's ``primary_assets`` block names — primary tier requires
    membership.  Forwarded to ``_eligibility_tier``.
    """
    symbol = t.get("symbol")
    tier = _eligibility_tier(symbol, explicit_primary=explicit_primary)
    tier_w = _tier_weight(tier)
    if tier_w <= 0.0:
        # Hedge/signal and rejected tickers don't contribute to the
        # event-level basket score regardless of evidence_score /
        # direction_tag.  Returning None keeps them out of the
        # aggregate AND out of the scored-tickers count.
        return None

    is_primary = tier == "primary"

    score = _safe_float(t.get("evidence_score"))
    if score is not None:
        contribution = score * _W_EVIDENCE_SCORE * tier_w
        if is_primary and score < 0:
            contribution *= _W_PRIMARY_CONTRADICTION
        return {
            "symbol":        symbol,
            "source":        "evidence_score",
            "contribution":  contribution,
            "weight":        _W_EVIDENCE_SCORE * tier_w,
            "signed_score":  score,
            "ticker_label":  t.get("evidence_label"),
            "direction_tag": t.get("direction_tag"),
            "is_primary":    is_primary,
            "eligibility_tier": tier,
        }
    sign = _tag_sign(t.get("direction_tag"))
    if sign != 0:
        contribution = sign * _TAG_CONTRIBUTION * _W_DIRECTION_TAG * tier_w
        if is_primary and sign < 0:
            contribution *= _W_PRIMARY_CONTRADICTION
        return {
            "symbol":        symbol,
            "source":        "direction_tag",
            "contribution":  contribution,
            "weight":        _W_DIRECTION_TAG * tier_w,
            "signed_score":  sign * _TAG_CONTRIBUTION,
            "ticker_label":  None,
            "direction_tag": t.get("direction_tag"),
            "is_primary":    is_primary,
            "eligibility_tier": tier,
        }
    return None


def _reason_line(row: dict, *, rank: int) -> str:
    sym = row.get("symbol") or f"row{rank}"
    signed = row.get("signed_score") or 0.0
    source = row.get("source")
    if source == "evidence_score":
        label = row.get("ticker_label") or "evidence"
        return f"{sym}: {label} ({signed:+.2f})"
    tag = row.get("direction_tag") or "tagged"
    return f"{sym}: {tag} ({signed:+.2f})"


def score_weighted_evidence(
    tickers: Optional[list],
    *,
    explicit_primary: set[str] | None = None,
) -> dict[str, Any]:
    """Event-level weighted evidence from per-ticker reads.

    Input:  the event's ``market_tickers`` list — each ticker may
            carry a per-ticker ``evidence_score`` (from
            ``validation_evidence``) and/or a ``direction_tag``.

    ``explicit_primary``, when supplied, is the set of symbols
    explicitly classified as primary by the event (typically extracted
    from ``event.primary_assets`` via :func:`_extract_primary_set`).
    Tightens primary tier so unmapped / typo / off-shape tickers don't
    silently inherit primary weight.  Optional for back-compat —
    legacy callers without event context fall back to the tightened
    single-name heuristic.

    Output dict keys (stable):
        evidence_label      — one of EVIDENCE_LABELS
        evidence_score      — aggregate in [-1, +1]
        evidence_reasons    — short per-ticker bullets (top by |contrib|)
        scored_tickers      — count of tickers contributing
        total_tickers       — size of the input list
        tag_only_tickers    — count falling back to direction_tag
        evidence_basis      — "evidence_scores" | "tags_only" | "mixed" | "unscorable"

    Never raises; returns ``insufficient`` on any malformed or thin input.
    """
    total = len(tickers) if isinstance(tickers, list) else 0
    empty = {
        "evidence_label":   "insufficient",
        "evidence_score":   0.0,
        "evidence_reasons": [],
        "scored_tickers":   0,
        "total_tickers":    total,
        "tag_only_tickers": 0,
        "evidence_basis":   "unscorable",
    }
    if not isinstance(tickers, list) or not tickers:
        return empty

    scored: list[dict[str, Any]] = []
    tag_only = 0
    evidence_rows = 0
    for t in tickers:
        if not isinstance(t, dict):
            continue
        row = _ticker_contribution(t, explicit_primary=explicit_primary)
        if row is None:
            continue
        scored.append(row)
        if row["source"] == "direction_tag":
            tag_only += 1
        else:
            evidence_rows += 1

    aggregate_weight = sum(r["weight"] for r in scored)

    if (len(scored) < _MIN_SCORABLE_TICKERS
            or aggregate_weight < _MIN_AGGREGATE_WEIGHT):
        return {
            **empty,
            "scored_tickers":   len(scored),
            "tag_only_tickers": tag_only,
            "evidence_basis":   "unscorable",
            "evidence_reasons": [
                "Too few tickers carry per-horizon evidence or direction tags.",
            ] if scored else [],
        }

    numerator = sum(r["contribution"] for r in scored)
    event_score = numerator / aggregate_weight
    event_score = max(-1.0, min(1.0, event_score))
    event_score = round(event_score, 3)

    if event_score >= _EVT_SUPPORTIVE:
        label = "supportive"
    elif event_score <= _EVT_CONTRADICTORY:
        label = "contradictory"
    else:
        label = "mixed"

    # Broad-beta filter: a ``supportive`` label can't ride on
    # secondary-ETF support alone.  When no primary single-name
    # contributed positively, the supportive aggregate is coming
    # from broad-market beta — downgrade to ``mixed`` so the desk
    # doesn't ship a false-positive read off ETF tape-following.
    # ``mixed`` (rather than ``insufficient``) is the right floor:
    # the basket DID score positively, just not on a thesis-specific
    # axis.
    if label == "supportive":
        primary_supports = any(
            r.get("eligibility_tier") == "primary"
            and (r.get("contribution") or 0) > 0
            for r in scored
        )
        if not primary_supports:
            label = "mixed"

    # Reasons: top rows by |contribution|.  Always include at least one
    # counter-signal when the basket has both sides, so reviewers see
    # why the read isn't cleaner.
    ordered = sorted(scored, key=lambda r: -abs(r["contribution"]))
    reasons = [_reason_line(r, rank=i) for i, r in enumerate(ordered[:3], 1)]
    if label in ("supportive", "contradictory"):
        wrong_sign = 1 if label == "contradictory" else -1
        counter = next(
            (r for r in ordered
             if (r["contribution"] > 0) == (wrong_sign > 0)
             and abs(r["contribution"]) > 0.1),
            None,
        )
        if counter is not None and counter not in ordered[:3]:
            reasons.append(
                "counter: " + _reason_line(counter, rank=len(reasons) + 1)
            )

    if evidence_rows > 0 and tag_only == 0:
        basis = "evidence_scores"
    elif evidence_rows == 0 and tag_only > 0:
        basis = "tags_only"
    else:
        basis = "mixed"

    return {
        "evidence_label":   label,
        "evidence_score":   event_score,
        "evidence_reasons": reasons,
        "scored_tickers":   len(scored),
        "total_tickers":    total,
        "tag_only_tickers": tag_only,
        "evidence_basis":   basis,
    }
