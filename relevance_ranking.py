"""Market-relevance scoring and diversity-aware ranking.

Why this module
---------------
The Portfolio page has been ranked by ``_portfolio_score``, a weighted
sum of *validation-quality* signals:

    confidence · rating · direction-tag presence · revisit count

That ranks analyses by how *easy* they are to validate, not by how
much they *matter to the market*.  Two structural failures followed:

    1. Events with rich validation metadata (many tagged tickers,
       high confidence, clean revisit) crowded out events with
       moderate metadata but genuine cross-asset significance.
    2. One macro cluster — typically oil / war — would own the top-N
       on any given week because those themes produce confident,
       tag-dense events even when other themes were the more
       market-relevant story.

This module separates the two questions.  Per-event score is *pure
market relevance*:

    cross_asset_significance — how many channels the event actually
    moved and how hard, normalised to channel σ_5d.  This is the
    primary "truly matters" axis.

    persistence — did the move hold?  Stage + LLM-emitted
    persistence tag + revisit-held count.  A 3σ one-day spike that
    fully retraced is a different animal from a 1σ move that held
    over 20 days.

    validation — the legacy confidence / rating / tag-presence
    signal, retained but down-weighted and labelled explicitly as
    the "easy to validate" axis so callers can see the separation.

Diversity is then applied as a **list-level post-pass**, not baked
into per-event scores.  Running ``rank_with_diversity`` applies a
multiplicative decay to each additional event in the same
``mechanism_family`` that is picked ahead of it.  A single oil event
with overwhelming cross-asset + persistence scores still wins — the
decay only kicks in for the *second* oil event competing against a
first-class credit or industrial-policy story.

This module is a **pure composer**: no I/O, no DB, no imports outside
stdlib + ``asset_selection._ticker_channel``.  All inputs are
already-loaded event dicts.
"""

from __future__ import annotations

from datetime import datetime as _dt
from typing import Any, Optional

from asset_selection import _ticker_channel


# ---------------------------------------------------------------------------
# Component weights — tunable, but kept documented so calibration runs
# can audit them alongside the other magic numbers in the system.
# ---------------------------------------------------------------------------

# Overall = w_cross * cross_asset + w_persist * persistence + w_valid * validation
# Weights sum to 1.0; outputs land in [0, 1].
_WEIGHT_CROSS_ASSET: float = 0.50
_WEIGHT_PERSISTENCE: float = 0.30
_WEIGHT_VALIDATION:  float = 0.20

_WEIGHT_SUM = (
    _WEIGHT_CROSS_ASSET + _WEIGHT_PERSISTENCE + _WEIGHT_VALIDATION
)
assert abs(_WEIGHT_SUM - 1.0) < 1e-9, (
    "Relevance component weights must sum to 1.0"
)


# Per-channel 5-day 1-sigma price moves in % (institutional priors).
# Mirrors the sigma_5d values in benchmark_quarantine but collapsed
# to the six grouped channels used here.  Tickers with |return_5d|
# above _CHANNEL_Z_CAP × sigma saturate — a 50σ move is either corrupt
# or once-in-a-decade; in both cases adding more score past the cap
# doesn't help ranking.
_CHANNEL_SIGMA_5D_PCT: dict[str, float] = {
    "equities":    1.5,
    "commodities": 3.0,
    "rates":       1.0,    # price-unit proxy; yield moves use their own scale
    "credit":      1.0,
    "fx":          0.8,
    "vol":         25.0,
}

_CHANNEL_Z_CAP: float = 3.0   # ≥ 3σ moves saturate in the scorer

# Expected full-breadth channel count.  Normalising by this (rather
# than by the number of observed channels) is what prevents a single
# 3σ move from claiming the same score as a true four-channel event —
# the sum of per-channel contributions is divided by ``_EXPECTED_BREADTH``
# so single-axis dominance is explicitly capped relative to genuine
# cross-asset significance.
_EXPECTED_BREADTH: float = 4.0


# Persistence component inputs.
_STAGE_SCORE: dict[str, float] = {
    "realized":        1.0,
    "escalation":      0.85,
    "de-escalation":   0.75,
    "announced":       0.75,
    "anticipation":    0.50,
    "preview":         0.30,
    "scheduled":       0.20,
}
_PERSISTENCE_TAG_SCORE: dict[str, float] = {
    "high":     1.0,
    "medium":   0.6,
    "low":      0.3,
    "one-off":  0.0,
    "fleeting": 0.0,
}
_REVISIT_PER_SNAPSHOT: float = 0.15
_REVISIT_MAX_BONUS:    float = 0.45


# Validation component inputs (legacy "easy to validate" axis).
_CONFIDENCE_SCORE: dict[str, float] = {
    "high":     1.0,
    "medium":   0.65,
    "low":      0.3,
    "very_low": 0.0,
}
_RATING_SCORE: dict[str, float] = {
    "good":  1.0,
    "mixed": 0.4,
    "poor":  0.0,
}
_TAGGED_TICKERS_PRESENCE_BONUS: float = 0.15
_LOW_SIGNAL_PENALTY:            float = 0.30


# Diversity post-pass: two-axis decay.
#
# * ``_FAMILY_DECAY`` — soft cap on per-family concentration.  Each
#   already-picked event in a family multiplies the next candidate
#   from that family by this factor.  0.70 means the 2nd event in a
#   family gets 70 % effective weight, the 3rd 49 %, the 4th 34 %.  A
#   dominant oil event with overall=1.0 still outranks a moderate
#   credit event with 0.6 even at 2nd oil slot (1.0 × 0.7 = 0.70 >
#   0.60).
#
# * ``_CLUSTER_DECAY`` — tighter cap on events sharing a transmission
#   path signature (family + ordered channel tuple, as produced by
#   ``transmission_cluster.transmission_signature``).  Near-identical
#   mechanisms (e.g. two oil-to-commodity chains with the same
#   channel sequence) would otherwise stack up inside the family
#   decay budget because the family allows fairly liberal repeats.
#   The cluster decay applies *on top of* the family decay and is
#   strictly smaller, so two identical-path events get
#   family_decay × cluster_decay = 0.70 × 0.45 = 0.315 at the second
#   slot — below a 0.30 credit alternative but above a thin 0.15
#   filler.  Events whose transmission signature is "thin" (no family
#   identity available) are exempted from cluster decay.
_FAMILY_DECAY:  float = 0.70
_CLUSTER_DECAY: float = 0.45


# ---------------------------------------------------------------------------
# Quality-adjustment multipliers applied to per-event overall scores.
#
# These are deliberately soft — the relevance components still drive
# ordering.  Multipliers tilt events with stale market checks or
# low-information analyses down, and reward events whose weighted
# evidence came back supportive (a fresh, horizon-backed read).
# Every gate requires enough data to be sure: events without
# ``last_market_check_at`` are not penalised for "legacy" unless they
# also carry an ``event_date`` that places them in the real archive.
# ---------------------------------------------------------------------------

_STALENESS_PENALTY:          float = 0.80
_LOW_INFO_PENALTY:           float = 0.75
_FRESH_EVIDENCE_BONUS:       float = 1.08
_FRESH_EVIDENCE_SCORE_FLOOR: float = 0.60   # tag-only 0.5 does not trigger
_PROOF_DISCIPLINE_BONUS:     float = 1.08   # has_proof_set AND has_falsifiers

# Cluster-decay weakness tier: a duplicate-cluster candidate scoring
# below this fraction of the cluster representative's score picks up
# an additional tick of ``cluster_decay``.  Keeps "one strong
# representative near the top" without letting weaker siblings
# colonise adjacent slots just because they share a theme.
_CLUSTER_WEAK_SIBLING_RATIO: float = 0.80


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# Cross-asset significance
# ---------------------------------------------------------------------------

def _channel_z_from_tickers(
    tickers: list[Any],
) -> dict[str, float]:
    """For each channel, return max |return_5d| / channel_sigma observed.

    Saturates at ``_CHANNEL_Z_CAP``.  An unknown-channel ticker is
    dropped silently; the scorer only rewards channels we can attribute
    to a benchmark-backed channel.
    """
    by_channel: dict[str, float] = {}
    for t in tickers or []:
        if not isinstance(t, dict):
            continue
        symbol = t.get("symbol")
        if not isinstance(symbol, str):
            continue
        channel = _ticker_channel(symbol)
        if channel is None:
            continue
        sigma = _CHANNEL_SIGMA_5D_PCT.get(channel)
        if sigma is None or sigma <= 0:
            continue
        ret = _f(t.get("return_5d"))
        if ret is None:
            continue
        z = min(abs(ret) / sigma, _CHANNEL_Z_CAP)
        if z > by_channel.get(channel, 0.0):
            by_channel[channel] = z
    return by_channel


def _cross_asset_significance(event: dict) -> float:
    """Return cross-asset significance in [0, 1].

    Shape: every channel contributes ``z / Z_CAP`` (so one 3σ channel
    = 1.0 from that channel alone), normalised by the number of
    channels expected for a full-breadth event (=4 → mean of all six
    channels' contributions, clipped).  A breadth bonus rewards
    events that clear ≥1σ on multiple channels — a 4-channel 1σ
    event outranks a 1-channel 3σ event.
    """
    tickers = event.get("market_tickers") or []
    by_channel = _channel_z_from_tickers(tickers)
    if not by_channel:
        return 0.0

    # Normalised per-channel contribution ∈ [0, 1] each; we divide the
    # SUM by the expected-breadth constant rather than the observed
    # count, so breadth is a first-class input to the score.  A single
    # 3σ channel contributes 1.0 / 4 = 0.25; four 1σ channels contribute
    # 1.33 / 4 = 0.33.  The breadth-dominant event wins even though
    # single-axis magnitude is larger.
    contribs = [z / _CHANNEL_Z_CAP for z in by_channel.values()]
    base = sum(contribs) / _EXPECTED_BREADTH
    return _clamp(base)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _persistence_score(event: dict) -> float:
    """Persistence score in [0, 1].

    Three inputs: event ``stage``, LLM-emitted ``persistence`` tag,
    count of ``revisit_snapshots``.  A staged event that held through
    multiple revisits beats a one-off spike on every axis.
    """
    stage_raw = str(event.get("stage") or "").strip().lower()
    stage = _STAGE_SCORE.get(stage_raw, 0.4)  # unknown → mid-low

    tag_raw = str(event.get("persistence") or "").strip().lower()
    tag = _PERSISTENCE_TAG_SCORE.get(tag_raw, 0.3)

    revisits = event.get("revisit_snapshots") or []
    held = sum(
        1 for snap in revisits
        if isinstance(snap, dict)
        and _f(snap.get("return_5d") or snap.get("return_20d")) is not None
    )
    revisit_bonus = min(
        held * _REVISIT_PER_SNAPSHOT, _REVISIT_MAX_BONUS,
    )

    # Weighted blend: tag is the LLM's structured read, stage is the
    # ground-truth lifecycle marker, revisits are real follow-through.
    score = 0.45 * tag + 0.35 * stage + 0.20 * min(revisit_bonus / _REVISIT_MAX_BONUS, 1.0)
    return _clamp(score)


# ---------------------------------------------------------------------------
# Validation (legacy "easy to validate" axis, down-weighted)
# ---------------------------------------------------------------------------

def _validation_score(event: dict) -> float:
    """Validation score in [0, 1].

    Retains the existing confidence/rating/tag-presence signal as a
    smaller component so ranked events still prefer higher-quality
    analyses *among events of equal market relevance*, not as the
    primary sort key.
    """
    conf_raw = str(event.get("confidence") or "").strip().lower()
    conf = _CONFIDENCE_SCORE.get(conf_raw, 0.2)

    rating_raw = str(event.get("rating") or "").strip().lower()
    rating = _RATING_SCORE.get(rating_raw, 0.4)

    tickers = event.get("market_tickers") or []
    has_tagged = any(
        (isinstance(t, dict) and (t.get("direction_tag") or "").strip())
        for t in tickers
    )
    tag_bonus = _TAGGED_TICKERS_PRESENCE_BONUS if has_tagged else 0.0

    penalty = _LOW_SIGNAL_PENALTY if event.get("low_signal") else 0.0

    score = 0.55 * conf + 0.30 * rating + tag_bonus - penalty
    return _clamp(score)


# ---------------------------------------------------------------------------
# Quality adjustment — staleness, low-information, fresh-evidence bonus
# ---------------------------------------------------------------------------

def _quality_adjust(
    event: dict, *, now: Optional[_dt] = None,
) -> dict[str, Any]:
    """Return a multiplier + rationale bits for the event's headline
    score based on freshness, information content, and evidence depth.

    The multiplier is meant to tilt ranking — not reorder magnitudes.
    Gates require enough data to be confident before applying a
    penalty so synthetic / barebones test events don't silently pick
    up a multiplier from a missing field.

    * Freshness: when the event carries an ``event_date`` (i.e. it's
      a real archive row) and ``compute_staleness`` flags ``stale`` or
      ``legacy``, the score is multiplied by
      :data:`_STALENESS_PENALTY`.  Frozen events (past the refresh
      cutoff) don't get penalised — they have a completed check.
    * Low-information: low / very_low confidence combined with a
      mechanism_summary that is empty or contains an
      insufficient-evidence marker multiplies by
      :data:`_LOW_INFO_PENALTY`.  The combined gate is intentional —
      a tentatively-phrased mechanism on a genuinely high-confidence
      event is not a low-information study.
    * Fresh evidence bonus: when
      ``validation_outcome.score_weighted_evidence`` reports
      ``supportive`` AND the aggregate score clears
      :data:`_FRESH_EVIDENCE_SCORE_FLOOR`, multiply by
      :data:`_FRESH_EVIDENCE_BONUS`.  Tag-only baskets (aggregate
      0.5) fall below the floor and don't trigger the bonus; only
      horizon-backed reads do.
    """
    multiplier = 1.0
    reasons: list[str] = []
    status: Optional[str] = None

    event_date_present = bool(
        event.get("event_date") or event.get("timestamp")
    )
    if event_date_present:
        try:
            from market_check_freshness import compute_staleness
            staleness = compute_staleness(event, now=now)
            status = staleness.get("status")
            if status in ("stale", "legacy"):
                multiplier *= _STALENESS_PENALTY
                reasons.append(f"{status} market check")
        except Exception:
            # Staleness derivation failing shouldn't poison the whole
            # relevance score — fall back to neutral.
            status = None

    try:
        from portfolio_flags import portfolio_flags
        flags = portfolio_flags(event)
    except Exception:
        flags = {"has_proof_set": False, "has_falsifiers": False,
                 "low_information": False}

    if flags.get("low_information"):
        multiplier *= _LOW_INFO_PENALTY
        reasons.append("low-information study")

    if flags.get("has_proof_set") and flags.get("has_falsifiers"):
        multiplier *= _PROOF_DISCIPLINE_BONUS
        reasons.append("proof set + falsifiers")

    try:
        from validation_outcome import _extract_primary_set, score_weighted_evidence
        ev_block = score_weighted_evidence(
            event.get("market_tickers") or [],
            explicit_primary=_extract_primary_set(event),
        )
        if ev_block.get("evidence_label") == "supportive":
            ev_score = float(ev_block.get("evidence_score") or 0.0)
            if ev_score >= _FRESH_EVIDENCE_SCORE_FLOOR:
                multiplier *= _FRESH_EVIDENCE_BONUS
                reasons.append(
                    f"supportive evidence score {ev_score:.2f}"
                )
    except Exception:
        pass

    return {
        "multiplier":     round(multiplier, 4),
        "reasons":        reasons,
        "stale_status":   status,
    }


# ---------------------------------------------------------------------------
# Public API — per-event scoring
# ---------------------------------------------------------------------------

def compute_relevance_score(
    event: dict, *, now: Optional[_dt] = None,
) -> dict[str, Any]:
    """Return the decomposed market-relevance read for one event.

    Output shape::

        {
          "overall_score": float in [0, 1],
          "components": {
            "cross_asset_significance": float in [0, 1],
            "persistence":              float in [0, 1],
            "validation":               float in [0, 1],
          },
          "weights": {
            "cross_asset_significance": float,
            "persistence":              float,
            "validation":               float,
          },
          "mechanism_family": str,
          "explanation":      str,
        }

    ``mechanism_family`` is surfaced so the diversity post-pass can
    read it without re-walking the event dict.
    """
    if not isinstance(event, dict):
        event = {}

    cross = _cross_asset_significance(event)
    persist = _persistence_score(event)
    valid = _validation_score(event)

    raw_overall = (
        _WEIGHT_CROSS_ASSET * cross
        + _WEIGHT_PERSISTENCE * persist
        + _WEIGHT_VALIDATION * valid
    )
    raw_overall = _clamp(raw_overall)

    quality = _quality_adjust(event, now=now)
    overall = _clamp(raw_overall * quality["multiplier"])

    family = str(event.get("mechanism_family") or "none")

    if quality["reasons"]:
        adj = f"; adjust×{quality['multiplier']:.2f} ({', '.join(quality['reasons'])})"
    else:
        adj = ""
    explanation = (
        f"overall={overall:.2f} (market={cross:.2f} · "
        f"persist={persist:.2f} · valid={valid:.2f}); "
        f"family={family}{adj}"
    )

    return {
        "overall_score": round(overall, 4),
        "components": {
            "cross_asset_significance": round(cross, 4),
            "persistence":              round(persist, 4),
            "validation":               round(valid, 4),
        },
        "weights": {
            "cross_asset_significance": _WEIGHT_CROSS_ASSET,
            "persistence":              _WEIGHT_PERSISTENCE,
            "validation":               _WEIGHT_VALIDATION,
        },
        "mechanism_family": family,
        "explanation":      explanation,
    }


# ---------------------------------------------------------------------------
# Public API — diversity-aware ranking
# ---------------------------------------------------------------------------

def _cluster_key(event: dict, *, family: str) -> Optional[tuple]:
    """Return a hashable cluster key for ``event`` or ``None`` when the
    event has too little mechanism identity to collide with siblings.

    The key combines the signature kind, family, and the ordered
    channel tuple so two events with the same transmission-path
    signature land in the same cluster bucket.  ``"thin"`` signatures
    return ``None`` — thin events don't share a collision space.

    Import is lazy so the ranking module stays light-weight when the
    transmission-cluster layer is mid-refactor.
    """
    try:
        from transmission_cluster import transmission_signature
        sig = transmission_signature(event)
    except Exception:
        return None
    kind = sig.get("kind")
    if kind == "thin":
        return None
    return (kind, family, tuple(sig.get("channels") or ()))


def rank_with_diversity(
    events: list[dict],
    *,
    limit: int = 20,
    family_decay: float = _FAMILY_DECAY,
    cluster_decay: float = _CLUSTER_DECAY,
    now: Optional[_dt] = None,
) -> list[dict[str, Any]]:
    """Rank events by relevance with a two-axis diversity post-pass.

    Greedy: at each slot, pick the event whose
    ``overall_score × family_decay ** prior_family_picks
                    × cluster_decay ** prior_cluster_picks`` is
    highest.

    The cluster axis keys on the transmission-path signature (family
    + ordered channel tuple) so near-identical mechanisms are
    additionally penalised on top of the family decay.  Genuinely
    distinct events within the same family (different path shapes)
    only take the family decay.

    Parameters
    ----------
    events : list of raw event dicts — same shape Portfolio already
        loads.  The scorer is robust to missing fields.
    limit : max number of events to return.
    family_decay : multiplicative penalty per prior pick in the same
        family.  Set ``family_decay=1.0`` to disable **all** diversity
        (a back-door to pure relevance ranking) — this also bypasses
        the cluster decay so callers can opt out with one flag.
    cluster_decay : multiplicative penalty per prior pick sharing the
        same transmission-path signature.  Must be in (0, 1].
        Default 0.45 — tighter than family_decay so duplicate
        path-shape events don't monopolise the top of the list.

    Returns
    -------
    List of dicts, one per picked event, in ranked order.  The
    existing keys are preserved for backward compatibility; two new
    keys (``cluster_decay_applied`` and ``cluster_rank_in_list``)
    surface the per-cluster axis without disturbing consumers::

        {
          "event": <original event dict>,
          "overall_score":         float,
          "effective_score":       float,     # overall × combined decay
          "components":            {...},
          "mechanism_family":      str,
          "diversity_decay":       float,     # family multiplier (backward-compat)
          "family_rank_in_list":   int,       # 1 = first in its family
          "cluster_decay_applied": float,     # cluster multiplier (new)
          "cluster_rank_in_list":  int,       # 1 = first in its cluster (new)
          "rank":                  int,       # 1-based position
        }
    """
    if limit < 1:
        raise ValueError("limit must be ≥ 1")
    if not (0.0 < family_decay <= 1.0):
        raise ValueError("family_decay must be in (0, 1]")
    if not (0.0 < cluster_decay <= 1.0):
        raise ValueError("cluster_decay must be in (0, 1]")

    # Preserve the ``family_decay=1.0`` back-door: when the caller has
    # explicitly disabled family diversity, also disable cluster
    # diversity so one flag really does mean "pure relevance order".
    effective_cluster_decay = 1.0 if family_decay == 1.0 else cluster_decay

    scored: list[dict[str, Any]] = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        read = compute_relevance_score(ev, now=now)
        family = read["mechanism_family"]
        scored.append({
            "event":             ev,
            "overall_score":     read["overall_score"],
            "components":        read["components"],
            "mechanism_family":  family,
            "cluster_key":       _cluster_key(ev, family=family),
        })

    # Primary sort — break ties by overall score so the greedy step
    # below is deterministic.
    scored.sort(key=lambda x: x["overall_score"], reverse=True)

    picked: list[dict[str, Any]] = []
    family_counts: dict[str, int] = {}
    cluster_counts: dict[tuple, int] = {}
    cluster_rep_score: dict[tuple, float] = {}
    remaining = list(scored)

    def _cluster_mult(key: Optional[tuple], cand_score: float) -> float:
        """Cluster-axis multiplier for ``cand_score``.

        Applies ``effective_cluster_decay ** prior`` for every prior
        pick in the same cluster, plus one extra tick when the
        candidate scores below ``_CLUSTER_WEAK_SIBLING_RATIO`` of the
        cluster representative.  That keeps one strong representative
        near the top but pulls weaker siblings down faster than the
        flat decay alone would.
        """
        if key is None:
            return 1.0
        prior = cluster_counts.get(key, 0)
        if prior == 0 or effective_cluster_decay == 1.0:
            return effective_cluster_decay ** prior
        rep = cluster_rep_score.get(key)
        mult = effective_cluster_decay ** prior
        if (
            rep is not None
            and rep > 0.0
            and cand_score < rep * _CLUSTER_WEAK_SIBLING_RATIO
        ):
            mult *= effective_cluster_decay
        return mult

    while remaining and len(picked) < limit:
        best_idx = -1
        best_effective = -1.0
        for i, cand in enumerate(remaining):
            fam = cand["mechanism_family"]
            fam_prior = family_counts.get(fam, 0)
            fam_mult = family_decay ** fam_prior
            cl_mult = _cluster_mult(
                cand["cluster_key"], cand["overall_score"],
            )
            eff = cand["overall_score"] * fam_mult * cl_mult
            if eff > best_effective:
                best_effective = eff
                best_idx = i
        if best_idx < 0:
            break
        winner = remaining.pop(best_idx)
        fam = winner["mechanism_family"]
        fam_prior = family_counts.get(fam, 0)
        fam_mult = family_decay ** fam_prior
        family_counts[fam] = fam_prior + 1

        cluster_key = winner["cluster_key"]
        cl_mult = _cluster_mult(cluster_key, winner["overall_score"])
        if cluster_key is None:
            cl_rank = 1
        else:
            cl_prior = cluster_counts.get(cluster_key, 0)
            cluster_counts[cluster_key] = cl_prior + 1
            cl_rank = cluster_counts[cluster_key]
            if cl_prior == 0:
                # First pick in this cluster — record its score so
                # future weaker siblings can be measured against it.
                cluster_rep_score[cluster_key] = winner["overall_score"]

        picked.append({
            "event":                 winner["event"],
            "overall_score":         winner["overall_score"],
            "effective_score":       round(
                winner["overall_score"] * fam_mult * cl_mult, 4,
            ),
            "components":            winner["components"],
            "mechanism_family":      fam,
            "diversity_decay":       round(fam_mult, 4),
            "family_rank_in_list":   family_counts[fam],
            "cluster_decay_applied": round(cl_mult, 4),
            "cluster_rank_in_list":  cl_rank,
            "rank":                  len(picked) + 1,
        })

    return picked
