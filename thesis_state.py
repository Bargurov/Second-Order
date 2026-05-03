"""Single ``thesis_state`` summary for a saved event.

Reads only fields already on the stored event (or pre-decorated on a
response row): the weighted-evidence label, proof-discipline flags,
persistence signal, and staleness signal.  Every other track-record
or research surface still speaks its own vocabulary — this composer
collapses those signals into a single state word the UI and exports
can display consistently.

Allowed states (closed enum):

    ``falsified``        overrides everything.  Analyst named a
                         falsifier AND the weighted evidence came back
                         contradictory — the thesis failed on its own
                         stated terms.
    ``low_information``  analyst confidence is low AND the mechanism
                         text reads "insufficient evidence" / empty.
    ``stale``            the market check itself is stale or legacy
                         (not merely an old event — a frozen event
                         with a completed check is not stale here).
    ``weakening``        evidence is contradictory without a named
                         falsifier, OR persistence signal is fading.
    ``confirming``       evidence is supportive AND proof-backed
                         (both minimum proof set and falsifiers
                         present).  The thesis is holding up on its
                         own terms.
    ``partial``          some positive structure — supportive evidence
                         OR partial proof discipline — but not the
                         full confirming set.
    ``watching``         default resting state when nothing else fires.

Precedence strictly follows the order above: ``falsified`` beats
``low_information``, which beats ``stale``, and so on down the list.

Pure composer.  No I/O beyond lazy imports of the helpers the
composer already relies on.  Never raises.
"""

from __future__ import annotations

import logging
from typing import Any, Optional


_log = logging.getLogger("second_order.thesis_state")


THESIS_STATES: tuple[str, ...] = (
    "confirming",
    "partial",
    "watching",
    "weakening",
    "falsified",
    "stale",
    "low_information",
)


def _get_flags(event: dict) -> dict:
    """Return portfolio_flags for ``event``, respecting per-key overrides.

    Starts from ``portfolio_flags(event)`` so stored fields
    (``minimum_proof_set`` / ``key_falsifiers`` / ``confidence``) drive
    the baseline, then overrides any key that the caller has already
    decorated onto ``event``.  That lets routes that have pre-computed
    the flags feed them through without double work, and also lets
    tests pass any one field explicitly.
    """
    try:
        from portfolio_flags import portfolio_flags
        flags = portfolio_flags(event)
    except Exception:
        flags = {
            "has_proof_set":   False,
            "has_falsifiers":  False,
            "low_information": False,
        }
    for key in ("has_proof_set", "has_falsifiers", "low_information"):
        if key in event:
            flags[key] = bool(event[key])
    return flags


def _get_evidence_label(event: dict) -> Optional[str]:
    block = event.get("weighted_evidence")
    if isinstance(block, dict) and block.get("evidence_label"):
        return block["evidence_label"]
    try:
        from validation_outcome import (
            _extract_primary_set,
            score_weighted_evidence,
        )
        block = score_weighted_evidence(
            event.get("market_tickers") or [],
            explicit_primary=_extract_primary_set(event),
        )
        return block.get("evidence_label")
    except Exception:
        return None


def _get_stale_status(event: dict, *, now=None) -> Optional[str]:
    raw = event.get("stale_signal")
    if isinstance(raw, str):
        return raw
    try:
        from market_check_freshness import compute_staleness
        return compute_staleness(event, now=now).get("status")
    except Exception:
        return None


def _get_persistence_status(event: dict) -> Optional[str]:
    sig = event.get("persistence_signal")
    if isinstance(sig, dict) and sig.get("status"):
        return sig["status"]
    try:
        from persistence_signal import classify_persistence_signal
        sig = classify_persistence_signal(event)
        if isinstance(sig, dict):
            return sig.get("status")
    except Exception as exc:
        _log.warning(
            "persistence_signal hook failed: %s — falling back to None",
            exc,
        )
    return None


def _ticker_sign(ticker: dict) -> int:
    """Return +1 supports, -1 contradicts, 0 unknown for one ticker.
    Reads ``evidence_score`` first (full read), falls back to
    ``direction_tag`` (tag-only) so the coherence check sees every
    ticker the validation pipeline scored."""
    if not isinstance(ticker, dict):
        return 0
    score = ticker.get("evidence_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        if score > 0:
            return 1
        if score < 0:
            return -1
    tag = ticker.get("direction_tag")
    if isinstance(tag, str):
        if tag.startswith("supports"):
            return 1
        if tag.startswith("contradicts"):
            return -1
    return 0


# Decay-detection thresholds for ``_follow_through_decayed``.
#
# DECAY_NOISE_PP — moves below this are noise; we only count tickers
# whose 5d return cleared this floor as "aligned movers" worth
# checking for follow-through.
# FADE_RETENTION_FRACTION — the 20d leg must retain at least this
# share of the 5d magnitude to NOT be a massive fade.
# STRUCTURAL_DECAY_RATE / TRANSIENT_DECAY_RATE — share of aligned
# movers that must show decay before the gate fires.  Structural
# events tolerate a higher rate because the cascade is supposed to
# play out over weeks; transient events fail with even partial fade.
_DECAY_NOISE_PP: float = 0.3
_FADE_RETENTION_FRACTION: float = 0.2
_STRUCTURAL_DECAY_RATE: float = 0.5
_TRANSIENT_DECAY_RATE: float = 0.33


def _follow_through_decayed(event: dict) -> bool:
    """True when the majority of thesis-aligned tickers fade or reverse
    on the 5d→20d leg of post-event price action.

    The case the rule catches: an event whose 5d returns confirmed the
    thesis (refining margins widened, semis dispersed, etc.) but whose
    20d returns reversed sign or gave back >80% of the magnitude.
    Confirming a thesis on that pattern hides the follow-through
    failure behind a stale 5d snapshot.

    Persistence-aware: structural events tolerate a higher decay rate
    (the cascade is supposed to play out over weeks); transient events
    fail with even partial fade.

    Reads only fields already on ``market_tickers`` (return_5d,
    return_20d, direction_tag / evidence_score).  No I/O; no new
    fetches.  Mirror of ``_cross_asset_coherence_rejects`` — read-side
    helper that demotes a "supportive" aggregate when the underlying
    follow-through doesn't justify it.
    """
    if not isinstance(event, dict):
        return False
    tickers = event.get("market_tickers")
    if not isinstance(tickers, list) or len(tickers) < 2:
        return False

    persistence = ""
    raw_persist = event.get("persistence")
    if isinstance(raw_persist, str):
        persistence = raw_persist.strip().lower()
    is_structural = persistence == "structural"

    aligned = 0
    decayed = 0
    for t in tickers:
        if not isinstance(t, dict):
            continue
        r5 = t.get("return_5d")
        r20 = t.get("return_20d")
        if not isinstance(r5, (int, float)) or isinstance(r5, bool):
            continue
        if not isinstance(r20, (int, float)) or isinstance(r20, bool):
            continue
        sign = _ticker_sign(t)
        if sign == 0:
            continue
        # The 5d return must (a) clear the noise floor and (b) be in
        # the direction the ticker was tagged supporting / contradicting.
        # A "supports" ticker with negative 5d isn't an early-confirm
        # mover; skip it.
        if abs(r5) < _DECAY_NOISE_PP:
            continue
        if sign > 0 and r5 <= 0:
            continue
        if sign < 0 and r5 >= 0:
            continue
        aligned += 1

        # Decay condition 1 — 5d and 20d are both above noise but the
        # sign flipped: the move that confirmed the thesis at 5d has
        # since reversed.
        if abs(r20) >= _DECAY_NOISE_PP:
            same_sign = (r5 > 0 and r20 > 0) or (r5 < 0 and r20 < 0)
            if not same_sign:
                decayed += 1
                continue
        # Decay condition 2 — 5d cleared the floor but 20d retained
        # less than _FADE_RETENTION_FRACTION of the magnitude: the
        # move stalled / faded toward zero rather than building.
        if abs(r20) < abs(r5) * _FADE_RETENTION_FRACTION:
            decayed += 1

    if aligned == 0:
        return False
    decay_rate = decayed / aligned
    threshold = (
        _STRUCTURAL_DECAY_RATE if is_structural else _TRANSIENT_DECAY_RATE
    )
    return decay_rate >= threshold


def _macro_hostile_to_thesis(event: dict) -> bool:
    """True when the analyst's stored regime caveats actively weaken
    the thesis.  Thin wrapper around
    :func:`low_information_gate.regime_caveats_weaken_thesis` so the
    macro/market-conflict gate stays consistent with the existing
    low-information audit.
    """
    if not isinstance(event, dict):
        return False
    try:
        from low_information_gate import regime_caveats_weaken_thesis
        return bool(regime_caveats_weaken_thesis(event))
    except Exception:
        return False


def _macro_supports_thesis(event: dict) -> bool:
    """True when the analyst's stored regime caveats actively support
    the thesis.  Mirror of :func:`_macro_hostile_to_thesis` for the
    cases where macro alignment + primary contradiction is the
    market-vs-macro conflict to flag.
    """
    if not isinstance(event, dict):
        return False
    try:
        from low_information_gate import regime_caveats_support_thesis
        return bool(regime_caveats_support_thesis(event))
    except Exception:
        return False


def _proof_is_strong(event: dict) -> bool:
    """True when stored ``proof_status.status`` reports every proof
    entry has been matched on observed evidence AND that verdict is
    still backed by the event's current ``market_tickers`` snapshot.

    "Strong" here is the actual evidence-coverage read, NOT the bare
    structural commitment captured by ``has_proof_set`` /
    ``has_falsifiers``.

    Stale-evidence guard: the stored block is a snapshot from save
    time.  If a ticker has since been deleted, retagged, or the
    market_check refreshed against a different basket, a stored "met"
    verdict can claim coverage on channels that no longer carry
    supporting tickers.  We re-derive per-channel counts from the
    current market_tickers and require each item's channel to still
    show supporting evidence (with no contradictions); items whose
    channel is no longer covered are treated as stale and the
    strong-proof verdict drops to False.

    Defensive default — any missing or malformed block returns False
    so the macro-hostility demotion fires by default.
    """
    if not isinstance(event, dict):
        return False
    block = event.get("proof_status")
    if not isinstance(block, dict):
        return False
    if block.get("status") != "met":
        return False

    items = block.get("items")
    tickers = event.get("market_tickers")
    if not isinstance(items, list) or not items:
        # No item-level detail to cross-check — preserve the stored
        # status (back-compat with legacy rows).
        return True
    if not isinstance(tickers, list) or not tickers:
        # Stored "met" originated from now-absent tickers — treat the
        # block as stale and drop the strong-proof verdict.
        return False

    try:
        from proof_evaluator import _channel_tag_counts
    except Exception:
        return True

    by_channel = _channel_tag_counts(tickers)
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "met":
            continue
        channel = item.get("channel")
        if not isinstance(channel, str) or not channel:
            continue
        counts = by_channel.get(
            channel.lower(), {"supports": 0, "contradicts": 0},
        )
        # Original "met" requires >=1 supporting / 0 contradicting on
        # the channel.  If current tickers no longer satisfy that, the
        # item's "met" is stale and the strong-proof gate drops.
        if counts.get("supports", 0) <= 0 or counts.get("contradicts", 0) > 0:
            return False
    return True


def _falsifier_status_triggered(event: dict) -> bool:
    """True when the stored ``falsifier_status`` block reports that at
    least one named falsifier has fired AND the trigger is still
    supported by the event's current ``market_tickers``.

    Stale-evidence guard: the stored block is a snapshot from save
    time.  If the underlying tickers have since been deleted /
    retagged / recomputed against a different basket, a stored
    "triggered" verdict can point at evidence that no longer exists.
    We re-derive the current event-wide validation label and the
    per-channel counts; the trigger only counts when:

      * current market_tickers yield a ``contradicted`` event-wide
        label (the basket as a whole is still contradicting), AND
      * at least one stored "triggered" item lands on a channel that
        still carries contradicting tickers in the current snapshot.

    Items whose channel is no longer contradicting are treated as
    stale and ignored.  An empty / missing market_tickers list is
    treated as stale by definition — the original references are
    gone, so the stored trigger cannot be honoured.

    Reads only fields already on the event; no I/O / no new fetches.
    """
    block = event.get("falsifier_status") if isinstance(event, dict) else None
    if not isinstance(block, dict):
        return False
    if block.get("status") != "triggered":
        return False

    tickers = event.get("market_tickers")
    if not isinstance(tickers, list) or not tickers:
        # No ticker context to validate against — original references
        # are gone, so the stored trigger is stale and ignored.
        return False

    try:
        from validation_outcome import score_validation_outcome
    except Exception:
        return True
    label, _ = score_validation_outcome(tickers)
    if label != "contradicted":
        # Current basket no longer reads as contradicting — the stored
        # trigger doesn't match live evidence.
        return False

    # Per-item channel cross-check: at least one stored "triggered"
    # item must land on a channel that still has contradicting
    # tickers.  When the block has no item-level detail, the
    # event-wide label check above is sufficient.
    items = block.get("items")
    if not isinstance(items, list) or not items:
        return True

    try:
        from proof_evaluator import _channel_tag_counts
    except Exception:
        return True
    by_channel = _channel_tag_counts(tickers)
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "triggered":
            continue
        channel = item.get("channel")
        if not isinstance(channel, str) or not channel:
            # No channel to cross-check; event-wide label already
            # confirmed the basket is contradicting, so accept.
            return True
        counts = by_channel.get(channel.lower())
        if counts and counts.get("contradicts", 0) > 0:
            return True
    # Every stored "triggered" item is on a channel that no longer
    # carries contradicting tickers — the block is stale.
    return False


# Strong-primary contradiction threshold.  A single primary
# contradiction with no primary support is already caught by
# :func:`_cross_asset_coherence_rejects`; the strong-primary gate adds
# the case where primaries lean clearly contradictory (≥2 contradict
# AND contradicts > supports) even if one primary still tape-follows
# the thesis.  A 1–1 split is genuinely ambiguous and falls through.
_STRONG_PRIMARY_MIN_CONTRADICTIONS: int = 2


def _strong_primary_contradiction(event: dict) -> bool:
    """True when primary single-name picks lean strongly contradictory.

    Definition: at least :data:`_STRONG_PRIMARY_MIN_CONTRADICTIONS`
    primary tickers contradict the thesis AND primary contradictions
    outnumber primary supports.  This complements
    :func:`_cross_asset_coherence_rejects`, which only fires when
    *every* primary contradicts; the strong gate catches the case
    where the desk has multiple primary picks fighting the tape even
    if one still confirms.

    A 1–1 primary split (one supports, one contradicts) is genuinely
    ambiguous and does NOT trigger the override — those events
    resolve to ``mixed`` / ``watching`` per the normal ladder.
    """
    tickers = event.get("market_tickers") if isinstance(event, dict) else None
    if not isinstance(tickers, list):
        return False
    try:
        from validation_outcome import _extract_primary_set, _is_primary_asset
    except Exception:
        return False

    explicit_primary = _extract_primary_set(event)
    primary_supports = 0
    primary_contradicts = 0
    for t in tickers:
        if not isinstance(t, dict):
            continue
        if not _is_primary_asset(
            t.get("symbol"), explicit_primary=explicit_primary,
        ):
            continue
        sign = _ticker_sign(t)
        if sign > 0:
            primary_supports += 1
        elif sign < 0:
            primary_contradicts += 1

    return (
        primary_contradicts >= _STRONG_PRIMARY_MIN_CONTRADICTIONS
        and primary_contradicts > primary_supports
    )


def _cross_asset_coherence_rejects(event: dict) -> bool:
    """True when primary single-name assets contradict the thesis AND
    only secondary / signal proxies support it.

    The case the rule catches: an event whose aggregate weighted
    evidence reads ``supportive`` because a couple of broad / hedge
    proxies move in the right direction, even though the desk's
    direct-name picks are tape-fighting the thesis.  Confirming a
    thesis on that pattern is exactly the over-reach the user
    contract forbids.

    Mixed primary reads (some support, some contradict) do NOT trigger
    this rule — the cross-asset picture is genuinely ambiguous and the
    state should resolve to ``partial`` / ``watching`` per the normal
    ladder, not be forced to weakening.

    All-signal baskets with no primary picks at all also do NOT trigger
    — a thesis without a direct-name commitment isn't being tape-tested
    on the primary axis, so coherence has nothing to reject.
    """
    tickers = event.get("market_tickers") or []
    if not isinstance(tickers, list):
        return False

    try:
        from validation_outcome import _extract_primary_set, _is_primary_asset
    except Exception:
        return False

    explicit_primary = _extract_primary_set(event)
    primary_supports = False
    primary_contradicts = False
    non_primary_supports = False

    for t in tickers:
        if not isinstance(t, dict):
            continue
        sign = _ticker_sign(t)
        if sign == 0:
            continue
        if _is_primary_asset(
            t.get("symbol"), explicit_primary=explicit_primary,
        ):
            if sign > 0:
                primary_supports = True
            else:
                primary_contradicts = True
        else:
            if sign > 0:
                non_primary_supports = True

    return (
        primary_contradicts
        and not primary_supports
        and non_primary_supports
    )


def derive_thesis_state(event: Any, *, now=None) -> str:
    """Return the single state word for ``event``.

    Always returns one of ``THESIS_STATES``.  Non-dict input collapses
    to ``"watching"`` so the caller can attach the field on every row
    without a preceding isinstance check.
    """
    if not isinstance(event, dict):
        return "watching"

    # Top-priority override — a triggered ``falsifier_status`` is the
    # analyst's own pre-committed break condition firing on observed
    # tape, and it must force ``falsified`` regardless of the broader
    # weighted-evidence aggregate.  Read the stored block only; no
    # re-evaluation here.
    if _falsifier_status_triggered(event):
        return "falsified"

    flags = _get_flags(event)
    evidence_label = _get_evidence_label(event)
    has_proof = flags.get("has_proof_set", False)
    has_fals = flags.get("has_falsifiers", False)
    low_info = flags.get("low_information", False)

    # Cross-asset coherence rejection — when the desk's primary
    # single-name picks are contradicting the thesis and only signal /
    # secondary proxies support it, the aggregate ``supportive`` label
    # is a false read.  Treat it as ``contradictory`` for state
    # resolution so the result can't promote to confirming / partial
    # off the back of weak coherence.
    if (
        evidence_label == "supportive"
        and _cross_asset_coherence_rejects(event)
    ):
        evidence_label = "contradictory"

    # Strong primary contradiction — when ≥2 primary picks contradict
    # AND outnumber primary supports, the broad supportive aggregate
    # is being driven by signal / secondary tape rather than the
    # desk's direct-name commitments.  Demote to ``contradictory`` so
    # a counterfactual primary read can't be papered over by broad
    # tape.  Goes after cross-asset (which is the stricter "all
    # primaries contradict" case) to preserve precedence.
    if (
        evidence_label == "supportive"
        and _strong_primary_contradiction(event)
    ):
        evidence_label = "contradictory"

    # Priced-in / reaction-window gate — when most of the
    # thesis-aligned move happened BEFORE the event timestamp and the
    # post-event tape is weak, a supportive aggregate is largely
    # tape-following anticipation rather than fresh confirmation.
    # Demote to ``mixed`` so the state can't resolve to confirming on
    # priced-in evidence alone.  Mirror of the broad-beta downgrade.
    if evidence_label == "supportive":
        try:
            from reaction_window import reaction_window_blocks_confirmation
            if reaction_window_blocks_confirmation(event):
                evidence_label = "mixed"
        except Exception as exc:
            _log.warning(
                "reaction_window hook failed: %s — leaving evidence_label "
                "unchanged",
                exc,
            )

    # Follow-through decay — when the majority of thesis-aligned
    # tickers' 5d→20d trajectory shows a sign flip or a massive fade,
    # the early confirmation didn't follow through.  Demote to
    # ``mixed`` so the state cannot resolve to ``confirming`` on a
    # decayed read.  Persistence-aware: structural events tolerate a
    # higher decay rate before the gate fires.  Stale events return
    # at the staleness step below; this gate only matters when the
    # data is fresh enough to reach the confirming check.
    if evidence_label == "supportive" and _follow_through_decayed(event):
        evidence_label = "mixed"

    # Market-vs-macro conflict — when primary tape supports the thesis
    # but the analyst's own regime caveats flag the macro/regime
    # backdrop as hostile (weakening / blunting / reversing the
    # chain), confirming should hold ONLY when the proof set itself
    # is strongly evidenced (every minimum_proof_set entry matched on
    # observed tape).  Otherwise the supportive aggregate is at risk
    # of being papered over by a macro flip the analyst already
    # warned about — demote to ``mixed`` so the state falls through
    # to ``partial`` / ``watching``.
    if (
        evidence_label == "supportive"
        and _macro_hostile_to_thesis(event)
        and not _proof_is_strong(event)
    ):
        evidence_label = "mixed"

    # 1. Falsified — the thesis lost on its own stated terms.
    if has_fals and evidence_label == "contradictory":
        return "falsified"

    # 2. Low information — analyst never committed to a mechanism.
    if low_info:
        return "low_information"

    # 3. Stale / legacy market check — the evidence is too old to
    #    trust.  Only applies when the event is real enough to have a
    #    staleness reading (``event_date`` or ``timestamp`` present);
    #    a frozen event with a completed historical check is not
    #    stale here — we're flagging stale *evidence*, not age.
    has_temporal_anchor = bool(
        event.get("event_date") or event.get("timestamp")
    )
    if has_temporal_anchor:
        stale_status = _get_stale_status(event, now=now)
        if stale_status in ("stale", "legacy"):
            return "stale"

    # 4. Weakening — evidence is contradictory (without a named
    #    falsifier the thesis can't be formally falsified) OR the
    #    persistence signal reports fading.
    if evidence_label == "contradictory":
        return "weakening"
    persist_status = _get_persistence_status(event)
    if persist_status == "fading":
        return "weakening"

    # 5. Confirming — evidence is supportive AND proof-backed.
    if evidence_label == "supportive" and has_proof and has_fals:
        return "confirming"

    # 6. Partial — supportive evidence on its own, or partial proof
    #    structure (proof-set-only or falsifiers-only).
    if evidence_label == "supportive":
        return "partial"
    if has_proof or has_fals:
        return "partial"

    # 7. Default resting state.
    return "watching"


# ---------------------------------------------------------------------------
# Compact reason strings — one short line per state explaining what
# dominated the verdict.  Read-only; same stored fields the state
# itself reads.  Used by every consumer that stamps ``thesis_state``
# so the UI / audit can render *why* the state landed where it did
# without re-deriving the ladder.
# ---------------------------------------------------------------------------

_REASON_MAX_LEN: int = 140


def derive_thesis_state_reason(
    event: Any, *, state: Optional[str] = None, now=None,
) -> str:
    """Return a short explanation for ``event``'s thesis_state value.

    When ``state`` isn't supplied, the function derives it via
    ``derive_thesis_state``.  The reason string is a one-liner
    capped at :data:`_REASON_MAX_LEN` chars.  Pure read; never
    mutates the event.

    Reasons are derived from the same stored fields the state ladder
    reads: ``weighted_evidence`` label, ``has_proof_set`` /
    ``has_falsifiers`` (proof / falsifier coverage), ``low_information``
    flag, ``stale_signal`` status, ``persistence_signal`` status.
    Empty input → ``"No event payload available."``.
    """
    if not isinstance(event, dict):
        return "No event payload available."
    if state is None:
        state = derive_thesis_state(event, now=now)

    flags = _get_flags(event)
    evidence_label = _get_evidence_label(event) or "insufficient"
    has_proof = flags.get("has_proof_set", False)
    has_fals = flags.get("has_falsifiers", False)

    def _cap(s: str) -> str:
        s = " ".join(s.split())
        return s if len(s) <= _REASON_MAX_LEN else (
            s[: _REASON_MAX_LEN - 1].rstrip() + "…"
        )

    if state == "falsified":
        if _falsifier_status_triggered(event):
            return _cap(
                "Falsified: falsifier_status reports at least one named "
                "falsifier observation has triggered — thesis lost on "
                "its own stated terms."
            )
        return _cap(
            "Falsified: evidence contradictory and at least one named "
            "key_falsifier observation is in the proof set — thesis "
            "lost on its own stated terms."
        )

    if state == "low_information":
        return _cap(
            "Low information: analyst flagged the mechanism as "
            "insufficient or the asset universe is too thin to score."
        )

    if state == "stale":
        stale_status = _get_stale_status(event, now=now) or "stale"
        return _cap(
            f"Stale evidence: market-check status is '{stale_status}' — "
            "the last validation read is too old to trust."
        )

    if state == "weakening":
        # Market-vs-macro conflict — primary single-name picks
        # contradict the thesis even though the analyst's regime
        # caveats align with it.  Surface the conflict directly so
        # consumers don't have to cross-reference the regime block.
        if (
            _macro_supports_thesis(event)
            and (
                _cross_asset_coherence_rejects(event)
                or _strong_primary_contradiction(event)
            )
        ):
            return _cap(
                "Weakening: primary single-name picks tape-fight the "
                "thesis even though regime caveats align with it — "
                "market-vs-macro conflict, primary tape wins."
            )
        if evidence_label == "contradictory":
            return _cap(
                "Weakening: weighted evidence reads contradictory "
                "without a named falsifier to formalise the break."
            )
        persist_status = _get_persistence_status(event) or "fading"
        return _cap(
            f"Weakening: persistence signal reports '{persist_status}' — "
            "the move is fading even though no contradicting tape fired."
        )

    if state == "confirming":
        return _cap(
            "Confirming: weighted evidence supportive AND both proof "
            "set and falsifier set are present — thesis holding on its "
            "own terms."
        )

    if state == "partial":
        # Market-vs-macro conflict — primary tape supports the thesis
        # but the analyst's regime caveats flag a hostile macro and
        # the proof set isn't strongly evidenced.  Confirming was held
        # back by the macro-hostility gate; surface that as the
        # dominant reason so the audit trail is explicit.
        if (
            evidence_label == "supportive"
            and _macro_hostile_to_thesis(event)
            and not _proof_is_strong(event)
        ):
            return _cap(
                "Partial: primary tape supports the thesis but the "
                "analyst's regime caveats flag a hostile macro — "
                "confirming held back pending strong proof coverage."
            )
        if evidence_label == "supportive":
            cov = "no proof / falsifier coverage" if not (has_proof or has_fals) else (
                "partial proof / falsifier coverage"
            )
            return _cap(
                f"Partial: weighted evidence supportive but {cov} — the "
                "tape backs the read but the analyst hasn't named a "
                "decisive break."
            )
        if has_proof and not has_fals:
            return _cap(
                "Partial: minimum_proof_set committed but key_falsifiers "
                "missing — half the structural discipline is in place."
            )
        if has_fals and not has_proof:
            return _cap(
                "Partial: key_falsifiers committed but minimum_proof_set "
                "missing — half the structural discipline is in place."
            )
        return _cap(
            "Partial: some structural evidence in place but the full "
            "supportive + proof + falsifier set hasn't aligned."
        )

    # state == "watching" or unrecognised
    return _cap(
        "Watching: no firing signal — evidence reads neutral / "
        "insufficient and no proof / falsifier has triggered."
    )


def derive_thesis_state_with_reason(
    event: Any, *, now=None,
) -> tuple[str, str]:
    """Convenience: return ``(state, reason)`` together so consumers
    that stamp both don't recompute the state twice."""
    state = derive_thesis_state(event, now=now)
    return state, derive_thesis_state_reason(event, state=state, now=now)


# ---------------------------------------------------------------------------
# Validation rationale — names the dominant validation read for the
# event (which gate fired / which tier of asset moved the score).
# Distinct from ``thesis_state_reason``: the reason explains where on
# the *state ladder* we landed; the rationale explains *why the
# validation evidence read what it did*.  Five enumerated categories
# (primary support / primary contradiction / signal-only support /
# stale evidence / priced-in risk / cross-asset rejection) plus the
# off-list "insufficient evidence" for low-information rows.
#
# Pure read; same stored fields the rest of this module reads.  Never
# raises; returns a short capped string.
# ---------------------------------------------------------------------------


def _primary_reads(event: dict) -> tuple[bool, bool, bool]:
    """Return ``(primary_supports, primary_contradicts, signal_supports)``
    over the event's market_tickers.

    ``primary_*`` flags are based on direct single-name picks (per
    ``validation_outcome._is_primary_asset``); ``signal_supports`` is
    True when at least one non-primary ticker tilts positive.  Pure
    sign read — uses :func:`_ticker_sign` so both ``evidence_score``
    and ``direction_tag`` rows participate.
    """
    primary_supports = False
    primary_contradicts = False
    signal_supports = False
    try:
        from validation_outcome import _extract_primary_set, _is_primary_asset
        explicit_primary = _extract_primary_set(event)
    except Exception:
        _is_primary_asset = lambda _s, **_: False  # noqa: E731
        explicit_primary = set()
    tickers = event.get("market_tickers") if isinstance(event, dict) else None
    if not isinstance(tickers, list):
        return (False, False, False)
    for t in tickers:
        if not isinstance(t, dict):
            continue
        sign = _ticker_sign(t)
        if sign == 0:
            continue
        if _is_primary_asset(t.get("symbol"), explicit_primary=explicit_primary):
            if sign > 0:
                primary_supports = True
            else:
                primary_contradicts = True
        else:
            if sign > 0:
                signal_supports = True
    return primary_supports, primary_contradicts, signal_supports


def _reaction_window_priced_in(event: dict) -> bool:
    """True when the reaction-window gate would block confirmation —
    i.e. the thesis-aligned move happened largely before the event."""
    try:
        from reaction_window import reaction_window_blocks_confirmation
        return bool(reaction_window_blocks_confirmation(event))
    except Exception:
        return False


def derive_validation_rationale(
    event: Any, *, state: Optional[str] = None, now=None,
) -> str:
    """Return a short rationale naming the dominant validation read.

    Categories returned (one per call):
        * ``"Insufficient evidence: …"``        — low_information rows
        * ``"Stale evidence: …"``                — stale market check
        * ``"Cross-asset rejection: …"``         — primary names contradict, signal proxies support
        * ``"Priced-in risk: …"``                — most thesis-aligned move happened before the event
        * ``"Signal-only support: …"``           — secondary / signal proxies tilt positive without a primary confirmation
        * ``"Primary asset support: …"``         — direct single-name picks confirm
        * ``"Primary asset contradiction: …"``   — direct single-name picks tape-fight

    Precedence mirrors ``derive_thesis_state``: state-driven mandatory
    reads first (low_information / stale / falsified), then gate-
    driven (cross-asset rejection > priced-in > signal-only), then the
    base primary read.  Always returns a string; capped at
    :data:`_REASON_MAX_LEN`.  Pure read — no new fetches.
    """
    if not isinstance(event, dict):
        return ""
    if state is None:
        state = derive_thesis_state(event, now=now)

    flags = _get_flags(event)
    raw_label = _get_evidence_label(event) or "insufficient"
    primary_supports, primary_contradicts, signal_supports = (
        _primary_reads(event)
    )
    cross_asset = _cross_asset_coherence_rejects(event)
    strong_primary = _strong_primary_contradiction(event)

    def _cap(s: str) -> str:
        s = " ".join(s.split())
        return s if len(s) <= _REASON_MAX_LEN else (
            s[: _REASON_MAX_LEN - 1].rstrip() + "…"
        )

    # 1. State-mandated reasons.
    if state == "low_information":
        return _cap(
            "Insufficient evidence: analyst flagged the mechanism as "
            "insufficient or the asset universe is too thin to score."
        )
    if state == "stale":
        stale_status = _get_stale_status(event, now=now) or "stale"
        return _cap(
            f"Stale evidence: market-check status is '{stale_status}' — "
            "the last validation read is too old to trust."
        )
    if state == "falsified":
        if cross_asset:
            return _cap(
                "Cross-asset rejection: primary single-name picks "
                "contradict the thesis while only signal proxies support "
                "it — falsifier observation in the proof set."
            )
        if strong_primary:
            return _cap(
                "Primary asset contradiction: ≥2 direct single-name "
                "picks tape-fight the thesis — falsifier observation "
                "in the proof set."
            )
        return _cap(
            "Primary asset contradiction: direct single-name picks "
            "tape-fight the thesis with a named falsifier observed."
        )

    # 2. Gate-driven precedence.  ``cross_asset`` and ``strong_primary``
    #    fire BEFORE the raw_label branch so a supportive aggregate
    #    that was overridden to contradictory inside ``derive_thesis_state``
    #    still produces the correct rationale (otherwise the rationale
    #    would describe ``raw_label == "supportive"`` while the state is
    #    ``weakening``).
    if cross_asset:
        return _cap(
            "Cross-asset rejection: primary single-name picks contradict "
            "the thesis while only signal / secondary proxies support it."
        )
    if strong_primary:
        return _cap(
            "Primary asset contradiction: ≥2 direct single-name picks "
            "tape-fight the thesis; broad supportive aggregate overridden."
        )
    if raw_label == "supportive" and _reaction_window_priced_in(event):
        return _cap(
            "Priced-in risk: most of the thesis-aligned move happened "
            "before the event timestamp — post-event tape isn't fresh "
            "confirmation."
        )

    # 3. Base read.
    if raw_label == "supportive":
        if primary_supports:
            return _cap(
                "Primary asset support: direct single-name picks confirm "
                "the thesis on the post-event tape."
            )
        if signal_supports:
            return _cap(
                "Signal-only support: secondary / signal proxies tilt "
                "positive without a primary single-name confirmation."
            )
        return _cap(
            "Supportive aggregate without identifiable primary or signal "
            "contributors."
        )
    if raw_label == "contradictory":
        if primary_contradicts:
            return _cap(
                "Primary asset contradiction: direct single-name picks "
                "tape-fight the thesis."
            )
        return _cap(
            "Contradictory aggregate: weighted evidence reads against "
            "the thesis."
        )
    if raw_label == "mixed":
        if primary_contradicts and not primary_supports and signal_supports:
            return _cap(
                "Cross-asset rejection: primary single-name picks "
                "contradict the thesis while only signal proxies "
                "support it."
            )
        if primary_supports and primary_contradicts:
            return _cap(
                "Mixed primary asset reads: direct single-name picks "
                "split between support and contradiction."
            )
        if primary_contradicts:
            return _cap(
                "Primary asset contradiction: direct single-name picks "
                "tape-fight the thesis; aggregate dilutes to mixed."
            )
        if primary_supports:
            return _cap(
                "Primary asset support: direct single-name picks confirm "
                "the thesis; aggregate dilutes to mixed."
            )
        if signal_supports:
            return _cap(
                "Signal-only support: secondary / signal proxies tilt "
                "positive without a primary single-name confirmation."
            )
        return _cap(
            "Mixed aggregate: no primary single-name picks have "
            "tipped the read either way."
        )

    # raw_label == "insufficient" or unknown
    return _cap(
        "Insufficient evidence: too few tickers carry per-horizon "
        "evidence or direction tags to score."
    )
