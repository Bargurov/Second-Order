"""
validation_plan.py

Explicit validation-plan layer for the thesis engine.

Why this module
---------------
The shipped pipeline hands the validation engine a flat set of ticker
suggestions and a channel-pack expectation — but it doesn't say which
asset to watch first, which macro channels must confirm for the
mechanism to be real, or which channels would break it.  The agreement
scorer can then over-weight a marginal satellite name against a
confirming primary channel, or collapse to "low agreement" when the
first-order rate move is textbook.

This composer sits on top of ``asset_selection`` and the family channel
packs and produces a compact, decision-useful scoring plan:

  * primary assets       — direct / sector-on-primary-channel names
  * secondary assets     — non-primary-channel ETFs + secondary tier
  * signal assets        — hedge / inverse / vol / FX (read, not validate)
  * confirming channels  — macro channels the thesis expects to move,
                           each with an ``expected_direction`` pulled
                           from the shipped thesis classifier
  * disconfirming        — mirror of confirming (breaks_if text) so the
                           UI / scorer can render falsifiers explicitly
  * expected_order       — a named scoring sequence the agreement engine
                           (or the UI) can walk top-down

Design
------
Pure composer.  No I/O.  Never raises.  Compose-on-read — does not
mutate the AnalysisResult or persist anything.  Reuses
``asset_selection.classify_and_rank_assets`` for the asset taxonomy
instead of re-walking ticker lists, and ``real_yield_context.classify_thesis``
+ ``mechanism_family.FAMILY_CHANNEL_PACKS`` for channel direction priors.

Per-asset enrichment
--------------------
When ``hidden_mechanism`` is provided, each asset entry in
``primary_assets`` / ``secondary_assets`` / ``signal_assets`` is
enriched with its ``why`` line (from
``hidden_mechanism.asset_rationales``) and a per-asset
``confirming_channel`` / ``invalidating_channel`` pick drawn from the
plan's confirming set.  No new source of truth — the role comes from
list membership (beneficiary / loser), the exposure tier comes from
``asset_selection``, the why-line comes from the LLM's
``hidden_mechanism`` block, and the channels come from this plan.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

_log = logging.getLogger("second_order.validation_plan")

from asset_selection import classify_and_rank_assets
# _ticker_channel is technically private to asset_selection but kept as
# the single source of truth for "which channel does this ETF belong
# to".  Duplicating that registry here would let the two drift.
from asset_selection import _ticker_channel
from mechanism_family import FAMILY_CHANNEL_PACKS, get_validation_matrix
from real_yield_context import classify_thesis


# ---------------------------------------------------------------------------
# Channel direction priors per thesis classification.
# ---------------------------------------------------------------------------
# Each entry spells out the move the named thesis implies for that
# channel — used to produce confirming_channels with an explicit
# expected_direction.  Missing (thesis, channel) pairs fall back to a
# family-pack lookup and, failing that, "direction unclear" so the UI
# still renders the channel row.

_THESIS_CHANNEL_DIRECTION: dict[str, dict[str, str]] = {
    "inflationary": {
        "rates":       "up",
        "commodities": "up",
        "credit":      "wider",
        "fx":          "up",
        "vol":         "up",
        "equities":    "down",
    },
    "disinflationary": {
        "rates":       "down",
        "commodities": "down",
        "credit":      "tighter",
        "fx":          "down",
        "vol":         "down",
        "equities":    "up",
    },
    "rate_pressure_up": {
        "rates":       "up",
        "fx":          "up",
        "credit":      "wider",
        "vol":         "up",
        "equities":    "down",
        "commodities": "mixed",
    },
    "rate_pressure_down": {
        "rates":       "down",
        "fx":          "down",
        "credit":      "tighter",
        "vol":         "down",
        "equities":    "up",
        "commodities": "mixed",
    },
}

# Human-readable label for each direction token.  Keeps the UI and the
# engine aligned on phrasing.
_DIRECTION_LABEL: dict[str, str] = {
    "up":      "move higher",
    "down":    "move lower",
    "wider":   "widen",
    "tighter": "tighten",
    "mixed":   "move either way",
    "unclear": "direction unclear",
}

# Mirror direction used for the disconfirming_channels "breaks_if" text.
_MIRROR_DIRECTION: dict[str, str] = {
    "up":      "down",
    "down":    "up",
    "wider":   "tighter",
    "tighter": "wider",
    "mixed":   "mixed",
    "unclear": "unclear",
}


# ---------------------------------------------------------------------------
# Ordered scoring steps — named so callers can branch on a stable token
# set rather than re-deriving the sequence per caller.
# ---------------------------------------------------------------------------

_EXPECTED_ORDER: tuple[str, ...] = (
    "primary_assets",         # direct-name equities first
    "confirming_channels",    # macro first-order channels next
    "secondary_assets",       # sector ETFs / secondary-tier proxies
    "disconfirming_channels", # watch invalidators last
    "signal_assets",          # hedge / inverse — read, not validated
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_of_strings(raw: Any) -> list[str]:
    """Lightweight normaliser for channel lists — silent on bad input."""
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for v in raw:
        if isinstance(v, str):
            s = v.strip().lower()
            if s and s not in out:
                out.append(s)
    return out


def _family_first_channels(family: Optional[str]) -> list[str]:
    pack = FAMILY_CHANNEL_PACKS.get(family or "none") or FAMILY_CHANNEL_PACKS["none"]
    return list(pack.get("first") or [])


def _family_second_channels(family: Optional[str]) -> list[str]:
    pack = FAMILY_CHANNEL_PACKS.get(family or "none") or FAMILY_CHANNEL_PACKS["none"]
    return list(pack.get("second") or [])


def _channel_direction(thesis: str, channel: str) -> str:
    """Expected move for the given channel under the given thesis.

    Falls back to ``"unclear"`` when the thesis is ``none`` or the
    (thesis, channel) pair isn't mapped — the validation engine can
    still watch the channel, it just has no signed confirmation rule.
    """
    return (_THESIS_CHANNEL_DIRECTION.get(thesis) or {}).get(channel, "unclear")


# tier → compact exposure label the UI and scorer can branch on
# without knowing the asset_selection internal token set.
_EXPOSURE_BY_TIER: dict[str, str] = {
    "direct_proxy":  "direct",
    "sector_proxy":  "direct",
    "second_order":  "secondary",
    "hedge_signal":  "signal",
    "excluded":      "excluded",
}


def _asset_channel(symbol: Optional[str], tier: Optional[str]) -> str:
    """Pick the macro channel this specific ticker maps to.

    Every asset — including hedge / inverse / vol / FX — must map to a
    named macro channel so a signal asset's read isn't lost when proof
    evaluation is scoped per-channel.  ``_ticker_channel`` now returns
    a real channel for VXX/UVXY (vol), UUP/FXE (fx), TBT (rates), and
    inverse equity ETFs (equities); we use it for every tier.

    The ``"signal"`` pseudo-channel is reserved as the LAST defensible
    fallback — a hedge-tier ticker we genuinely can't route (rare; the
    registry covers the standard hedge universe).  Direct-tier and
    unmapped single-name picks default to ``"equities"`` because most
    direct-name picks are sector equity stories regardless of family.
    """
    if isinstance(symbol, str):
        ch = _ticker_channel(symbol.upper())
        if ch:
            return ch
    if tier == "hedge_signal":
        return "signal"
    return "equities"


def _pick_confirming_for(
    asset_channel: str,
    confirming_channels: list[dict],
) -> Optional[dict]:
    """Prefer the confirming-channel entry whose channel matches the
    asset's own channel; fall back to the first entry so every asset
    gets a concrete confirmation rule even on weak channel matches."""
    if not confirming_channels:
        return None
    for entry in confirming_channels:
        if entry.get("channel") == asset_channel:
            return entry
    return confirming_channels[0]


def _mirror_for(
    confirming: Optional[dict],
    disconfirming_channels: list[dict],
) -> Optional[dict]:
    if not confirming:
        return None
    target = confirming.get("channel")
    for entry in disconfirming_channels:
        if entry.get("channel") == target:
            return entry
    return disconfirming_channels[0] if disconfirming_channels else None


def _eligibility_status(
    *,
    channel: str,
    tier: Optional[str],
    mechanism_channels: set[str],
    direct_channels: set[str],   # noqa: ARG001 — kept for call-site compat
) -> tuple[str, Optional[str], Optional[str]]:
    """Classify one asset row into ``primary | secondary | hedge_signal
    | rejected`` and return ``(status, reason_text, rejection_reason)``.

    Strict role separation
    ----------------------
    The validation plan distinguishes:

      * ``primary``  — direct single-name expression of the thesis
        (a tier-1 ``direct_proxy`` ticker).  Sector / commodity / bond
        ETFs are baskets, not direct expressions, so they never land
        in primary regardless of channel match.  This forces a thin
        analysis with only ETF picks to surface an empty primary
        bucket — a strong signal that no direct pick has been named.
      * ``secondary``— indirect / second-order exposures: every ETF
        (sector_proxy, second_order tier) belongs here.
      * ``hedge_signal`` — explicit signal-only tier (vol / fx /
        inverse).  Never promotes to primary or secondary.
      * ``rejected`` — off-pack channel or unknown tier.

    ``rejection_reason`` is non-None only when ``status == "rejected"``,
    and uses the controlled vocabulary from ``REJECTION_REASONS``.

    Rules
    -----
    1. **Off-pack channels are rejected.**  When the family carries a
       mechanism pack, an asset whose channel is outside the
       ``first ∪ second`` set is broad/noisy by definition — it can't
       transmit through the family's playbook, so it's pulled out of
       the validation universe entirely.  Family ``"none"`` (or any
       family with an empty pack) skips the channel filter so the
       LLM's picks aren't gutted on un-typed events.
    2. **Hedge tier stays signal-only.**  ``hedge_signal`` rows that
       survive the channel check land in ``signal_assets`` —
       never as a primary or secondary thesis beneficiary.
    3. **Direct picks beat sector ETFs on the same channel.**  When a
       direct single-name asset already covers a channel, any
       ``sector_proxy`` ETF on that same channel demotes from primary
       to secondary so the index proxy doesn't dilute the named-name
       read.
    """
    # Hedge tier is always signal-only — bypass the off-pack filter
    # because hedge ETFs are inherently broad reads (VXX, UUP, TBT)
    # and the user contract is that they stay labeled signal-only
    # regardless of pack membership, never as a thesis beneficiary.
    if tier == "hedge_signal":
        return "hedge_signal", None, None

    if mechanism_channels and channel not in mechanism_channels:
        return "rejected", (
            f"asset on '{channel}' channel — family mechanism pack "
            f"covers {sorted(mechanism_channels)}; off-pack proxies "
            f"don't transmit through this family"
        ), "wrong_channel"

    # Strict role separation: only direct single-name picks reach
    # primary.  Every ETF (sector_proxy / second_order) is an indirect
    # / second-order exposure by definition — secondary, regardless
    # of whether a direct pick exists on the same channel.
    if tier == "direct_proxy":
        return "primary", None, None
    if tier in ("sector_proxy", "second_order"):
        return "secondary", None, None

    return "rejected", f"unknown tier {tier!r}", "weak_exposure"


def _asset_row(
    entry: dict,
    *,
    why_map: Optional[dict] = None,
    confirming_channels: Optional[list[dict]] = None,
    disconfirming_channels: Optional[list[dict]] = None,
) -> dict:
    """Trim a classify_and_rank_assets entry down to the fields the
    validation engine cares about, then enrich with per-asset why /
    confirming / invalidating picks.  Keeps shape stable even if
    asset_selection adds internal fields later."""
    symbol = entry.get("symbol")
    tier   = entry.get("tier")
    sym_key = symbol.upper() if isinstance(symbol, str) else ""
    row: dict = {
        "symbol":    symbol,
        "side":      entry.get("side"),
        "tier":      tier,
        "exposure":  _EXPOSURE_BY_TIER.get(tier or "", "secondary"),
        "rationale": entry.get("rationale"),
    }

    # Eligibility read — surfaced directly from asset_selection so the
    # validation engine can filter weak proxies without re-deriving.
    # Composite score + confidence band for back-compat consumers, AND
    # the four-axis component breakdown + short rationale so the UI /
    # audit can render *why* the proxy scored where it did.
    score = entry.get("eligibility_score")
    if score is not None:
        row["eligibility_score"] = score
    confidence = entry.get("proxy_confidence")
    if confidence:
        row["proxy_confidence"] = confidence
    components = entry.get("eligibility_components")
    if components is not None:
        row["eligibility_components"] = components
    rationale_short = entry.get("eligibility_rationale")
    if rationale_short:
        row["eligibility_rationale"] = rationale_short

    if why_map and sym_key and sym_key in why_map:
        row["why"] = why_map[sym_key]

    if confirming_channels:
        asset_channel = _asset_channel(symbol, tier)
        conf = _pick_confirming_for(asset_channel, confirming_channels)
        if conf is not None:
            row["confirming_channel"] = dict(conf)
            mirror = _mirror_for(conf, disconfirming_channels or [])
            if mirror is not None:
                row["invalidating_channel"] = dict(mirror)

    return row


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_validation_plan(
    *,
    headline:         str = "",
    mechanism_text:   str = "",
    mechanism_family: Optional[str] = None,
    beneficiary_tickers: Optional[Iterable[Any]] = None,
    loser_tickers:       Optional[Iterable[Any]] = None,
    beneficiaries_text:  Optional[Iterable[Any]] = None,
    losers_text:         Optional[Iterable[Any]] = None,
    expected_first_order_channels:  Optional[Iterable[Any]] = None,
    expected_second_order_channels: Optional[Iterable[Any]] = None,
    hidden_mechanism:     Optional[dict] = None,
) -> dict[str, Any]:
    """Build the validation plan for an analysed event.

    Returns an empty-but-shaped dict when there's nothing to validate
    (no tickers and no channel expectations) so callers can rely on the
    key surface without null-checking every field.
    """
    classified = classify_and_rank_assets(
        beneficiary_tickers=beneficiary_tickers,
        loser_tickers=loser_tickers,
        mechanism_family=mechanism_family,
        beneficiaries_text=beneficiaries_text,
        losers_text=losers_text,
    )

    # --- Channel expectations (built first so per-asset enrichment
    #     can pick confirming / invalidating channels deterministically) ---
    # Blend LLM-provided channels (more event-specific) with the family
    # pack (deterministic baseline).  De-duped while preserving
    # LLM-first order.
    llm_first  = _list_of_strings(expected_first_order_channels)
    llm_second = _list_of_strings(expected_second_order_channels)
    fam_first  = _family_first_channels(mechanism_family)
    fam_second = _family_second_channels(mechanism_family)

    confirming_channel_ids: list[str] = []
    for c in llm_first + fam_first:
        if c not in confirming_channel_ids:
            confirming_channel_ids.append(c)

    # Secondary-wave channels are kept distinct from the first-wave set;
    # they're not part of the primary confirmation test but appear in
    # the expected_order so the scorer knows where to look for cascade
    # evidence.
    cascade_channel_ids: list[str] = []
    for c in llm_second + fam_second:
        if c in confirming_channel_ids:
            continue
        if c not in cascade_channel_ids:
            cascade_channel_ids.append(c)

    thesis_info = classify_thesis(headline or "", mechanism_text or "")
    thesis = thesis_info.get("thesis") or "none"

    confirming_channels: list[dict] = []
    for ch in confirming_channel_ids:
        direction = _channel_direction(thesis, ch)
        confirming_channels.append({
            "channel":            ch,
            "expected_direction": direction,
            "rationale": (
                f"{ch} expected to {_DIRECTION_LABEL.get(direction, direction)} "
                "if the mechanism plays out"
            ),
        })

    cascade_channels: list[dict] = []
    for ch in cascade_channel_ids:
        direction = _channel_direction(thesis, ch)
        cascade_channels.append({
            "channel":            ch,
            "expected_direction": direction,
            "rationale": (
                f"{ch} expected to {_DIRECTION_LABEL.get(direction, direction)} "
                "in the 5-20d cascade"
            ),
        })

    # --- Disconfirming channels: mirror of confirming ---
    disconfirming_channels: list[dict] = []
    for entry in confirming_channels:
        mirror = _MIRROR_DIRECTION.get(entry["expected_direction"], "unclear")
        disconfirming_channels.append({
            "channel":   entry["channel"],
            "breaks_if": mirror,
            "rationale": (
                f"{entry['channel']} moving {_DIRECTION_LABEL.get(mirror, mirror)} "
                "would invalidate the confirmation"
            ),
        })

    # --- Per-asset enrichment ---
    # Pull the LLM's asset_rationales ("why this asset matters") and
    # build each asset row with its own confirming / invalidating
    # channel pick.  When hidden_mechanism is absent, the rows still
    # come out — just without the why-line.
    why_map: dict[str, str] = {}
    if isinstance(hidden_mechanism, dict):
        raw_rationales = hidden_mechanism.get("asset_rationales")
        if isinstance(raw_rationales, dict):
            for sym, text in raw_rationales.items():
                if isinstance(sym, str) and isinstance(text, str):
                    s = sym.strip().upper()
                    t = text.strip()
                    if s and t:
                        why_map[s] = t

    def _row(entry: dict) -> dict:
        return _asset_row(
            entry,
            why_map=why_map,
            confirming_channels=confirming_channels,
            disconfirming_channels=disconfirming_channels,
        )

    raw_primary_ben    = list((classified.get("primary")   or {}).get("beneficiary") or [])
    raw_primary_los    = list((classified.get("primary")   or {}).get("loser")       or [])
    raw_secondary_ben  = list((classified.get("secondary") or {}).get("beneficiary") or [])
    raw_secondary_los  = list((classified.get("secondary") or {}).get("loser")       or [])
    raw_signal         = list(classified.get("hedge_signal") or [])

    # --- Eligibility filter — stricter classification before assets
    #     enter the validation universe.  Each retained asset carries an
    #     ``eligibility_status`` ∈ {primary, secondary, hedge_signal,
    #     rejected}; rejected assets land in ``excluded_assets`` with a
    #     concrete reason instead of polluting the scorer.
    fam_pack: dict[str, list[str]] = (
        FAMILY_CHANNEL_PACKS.get(mechanism_family or "none")
        or FAMILY_CHANNEL_PACKS["none"]
    )
    mechanism_channels: set[str] = (
        set(fam_pack.get("first") or []) | set(fam_pack.get("second") or [])
    )

    # Build the "channel has a direct single-name on it" map BEFORE
    # tier reshuffling so the prefer-direct rule reads from the
    # untouched classification.
    direct_channels: set[str] = set()
    for entry in raw_primary_ben + raw_primary_los:
        if entry.get("tier") == "direct_proxy":
            sym = entry.get("symbol")
            ch = _asset_channel(sym, entry.get("tier"))
            direct_channels.add(ch)

    primary_assets:   list[dict] = []
    secondary_assets: list[dict] = []
    signal_assets:    list[dict] = []
    excluded_assets:  list[dict] = []

    # Pass-through excluded entries from the classifier first
    # (broad-market, foreign listings, ticker collisions).  These keep
    # their original reason, gain an explicit status tag, and inherit
    # the controlled rejection_reason vocabulary set by asset_selection.
    # The component-driven eligibility_rationale rides through too so
    # the UI has a one-line read on every rejection.
    for e in classified.get("excluded") or []:
        row = {
            "symbol":             e.get("symbol"),
            "side":               e.get("side"),
            "reason":             e.get("reason"),
            "eligibility_status": "rejected",
            "rejection_reason":   e.get("rejection_reason") or "weak_exposure",
        }
        rationale = e.get("eligibility_rationale")
        if rationale:
            row["eligibility_rationale"] = rationale
        excluded_assets.append(row)

    # Track which (side, channel) pairs already have an accepted
    # sector_proxy so subsequent ETFs on the same pair are caught as
    # duplicate_proxy.  Direct picks don't count — the prefer-direct
    # rule handles those by demoting any later sector_proxy to
    # secondary instead of rejecting it.
    sector_proxy_covered: set[tuple[str, str]] = set()

    def _route_entry(entry: dict, *, expected_bucket: str) -> None:
        """Compute eligibility for one classified entry and route it
        to the right output bucket.  ``expected_bucket`` is the bucket
        the entry came from — used only for diagnostic clarity in the
        rejection reason.
        """
        sym  = entry.get("symbol")
        tier = entry.get("tier")
        side = entry.get("side") or expected_bucket
        channel = _asset_channel(sym, tier)

        # Audit record: a hedge_signal asset that arrived via the
        # beneficiary or loser side is signal-only; we still route it
        # to ``signal_assets`` (fall through below) but add a separate
        # excluded_assets entry so the audit captures the misuse.
        if (
            tier == "hedge_signal"
            and side in ("beneficiary", "loser")
        ):
            excluded_assets.append({
                "symbol":             sym,
                "side":               side,
                "reason": (
                    f"hedge/signal asset supplied as {side} — kept as "
                    "signal-only; never promoted to a thesis beneficiary"
                ),
                "eligibility_status": "rejected",
                "rejection_reason":   "signal_only_not_beneficiary",
                "eligibility_rationale": (
                    f"{sym}: signal-only — validates through its named "
                    f"channel, never as a thesis {side}"
                ),
            })

        # Duplicate-proxy gate: a 2nd sector_proxy on the same
        # (side, channel) adds no orthogonal information; reject it
        # so the scorer doesn't double-weight a single channel read.
        if tier == "sector_proxy":
            key = (side, channel)
            if key in sector_proxy_covered:
                excluded_assets.append({
                    "symbol":             sym,
                    "side":               side,
                    "reason": (
                        f"second sector ETF on '{channel}' for {side} — "
                        f"channel already covered by a prior sector proxy"
                    ),
                    "eligibility_status": "rejected",
                    "rejection_reason":   "duplicate_proxy",
                    "eligibility_rationale": (
                        f"{sym}: duplicate basket on '{channel}' — "
                        f"channel already covered by a prior sector ETF"
                    ),
                })
                return
            sector_proxy_covered.add(key)

        status, reason, rej_tag = _eligibility_status(
            channel=channel,
            tier=tier,
            mechanism_channels=mechanism_channels,
            direct_channels=direct_channels,
        )
        if status == "rejected":
            row = {
                "symbol":             sym,
                "side":               side,
                "reason":             reason or f"rejected from {expected_bucket}",
                "eligibility_status": "rejected",
                "rejection_reason":   rej_tag or "weak_exposure",
            }
            # Re-derive the eligibility rationale via asset_selection
            # so the rejection row carries a short human-readable read
            # alongside the controlled rejection_reason tag.
            try:
                from asset_selection import compute_eligibility_components
                comps = compute_eligibility_components(
                    entry, mechanism_family=mechanism_family,
                )
                if comps.get("eligibility_rationale"):
                    row["eligibility_rationale"] = comps["eligibility_rationale"]
            except Exception as exc:
                _log.warning(
                    "compute_eligibility_components failed for %s: %s — "
                    "rejection row will omit eligibility_rationale",
                    entry, exc,
                )
            excluded_assets.append(row)
            return
        row = _row(entry)
        row["eligibility_status"] = status
        if status == "primary":
            primary_assets.append(row)
        elif status == "secondary":
            secondary_assets.append(row)
        else:  # hedge_signal
            signal_assets.append(row)

    for e in raw_primary_ben + raw_primary_los:
        _route_entry(e, expected_bucket="primary")
    for e in raw_secondary_ben + raw_secondary_los:
        _route_entry(e, expected_bucket="secondary")
    for e in raw_signal:
        _route_entry(e, expected_bucket="signal")

    # --- Availability + rationale ---
    available = bool(
        primary_assets or secondary_assets
        or confirming_channels or cascade_channels
    )

    rationale_bits: list[str] = []
    if primary_assets:
        rationale_bits.append(f"{len(primary_assets)} primary asset(s)")
    if secondary_assets:
        rationale_bits.append(f"{len(secondary_assets)} secondary")
    if confirming_channels:
        rationale_bits.append(f"{len(confirming_channels)} confirming channel(s)")
    if cascade_channels:
        rationale_bits.append(f"{len(cascade_channels)} cascade channel(s)")
    if signal_assets:
        rationale_bits.append(f"{len(signal_assets)} signal-only asset(s)")
    rationale = (
        "Validation plan: " + ", ".join(rationale_bits)
        if rationale_bits else
        "No assets or channel expectations available to validate against."
    )

    return {
        "available":              available,
        "thesis":                 thesis,
        "mechanism_family":       mechanism_family or "none",
        "primary_assets":         primary_assets,
        "secondary_assets":       secondary_assets,
        "signal_assets":          signal_assets,
        "excluded_assets":        excluded_assets,
        "confirming_channels":    confirming_channels,
        "cascade_channels":       cascade_channels,
        "disconfirming_channels": disconfirming_channels,
        "expected_order":         list(_EXPECTED_ORDER),
        "rationale":              rationale,
    }


# ---------------------------------------------------------------------------
# Mechanism-specific validation matrix
# ---------------------------------------------------------------------------
# The validation plan above says WHAT this specific event should check;
# the matrix below says HOW A FAMILY validates in general — the desk
# playbook for a sanction vs a bank-stress vs a ceasefire.  Kept as a
# separate public function so consumers that only need one don't pay
# for both, but co-located so there's a single module to import.


# ---------------------------------------------------------------------------
# Monitor plan — unified operational view
# ---------------------------------------------------------------------------
# The LLM emits only the two NET-NEW monitor fields (first_decisive_tell,
# no_call_signals).  Everything else in the "monitor plan" shape the
# user asks for is already covered by existing LLM-emitted fields:
#
#   key_monitor_signals    ← horizon_checkpoints.*.expected
#   shift_to_alternative   ← competing_thesis.evidence_favoring_alternative
#   confirm_first_vs_later ← horizon_checkpoints 1d vs 5d/20d confirms_if
#
# This composer assembles the unified 5-field monitor view from the
# existing structure so consumers can read one block instead of joining
# three sources themselves.  Pure composer — no I/O, no state.


def compute_monitor_plan(analysis: dict) -> dict[str, Any]:
    """Return the unified monitoring-plan view for an analysis dict.

    Joins ``monitor_plan`` (LLM-emitted net-new fields) with derived
    views of ``horizon_checkpoints`` and ``competing_thesis`` so the UI
    / telemetry can read one block instead of three.

    Output keys:
      * ``first_decisive_tell``   — temporally-earliest 1d tell (from LLM)
      * ``no_call_signals``       — both-readings-inconsistent signals (from LLM)
      * ``key_monitor_signals``   — derived from horizon_checkpoints.expected
      * ``shift_to_alternative``  — derived from competing_thesis.evidence_favoring_alternative
      * ``confirm_first_vs_later``— derived from horizon_checkpoints.confirms_if
      * ``available``             — False only when every field is empty
    """
    monitor_raw: dict = analysis.get("monitor_plan") or {}
    first_tell         = monitor_raw.get("first_decisive_tell") or {}
    no_call_signals    = list(monitor_raw.get("no_call_signals") or [])

    # Key monitor signals — flatten 1d + 5d "expected" observations.
    hz: dict = analysis.get("horizon_checkpoints") or {}
    horizons_list = hz.get("horizons") or []
    key_signals: list[dict] = []
    for h in horizons_list:
        if not isinstance(h, dict):
            continue
        horizon = h.get("horizon")
        if horizon not in ("1d", "5d"):
            continue
        for obs in h.get("expected") or []:
            if isinstance(obs, str) and obs.strip():
                key_signals.append({"horizon": horizon, "observation": obs.strip()})

    # Shift-to-alternative — reuse the competing_thesis structured list.
    ct: dict = analysis.get("competing_thesis") or {}
    shift_to_alternative = list(ct.get("evidence_favoring_alternative") or [])

    # Confirm first vs later — partition confirms_if by horizon.
    confirm_first: list[dict] = []
    confirm_later: list[dict] = []
    for h in horizons_list:
        if not isinstance(h, dict):
            continue
        horizon = h.get("horizon")
        bucket = confirm_first if horizon == "1d" else confirm_later
        for obs in h.get("confirms_if") or []:
            if isinstance(obs, str) and obs.strip():
                bucket.append({"horizon": horizon, "observation": obs.strip()})

    available = bool(
        first_tell or no_call_signals
        or key_signals or shift_to_alternative
        or confirm_first or confirm_later
    )

    return {
        "available":              available,
        "first_decisive_tell":    first_tell,
        "no_call_signals":        no_call_signals,
        "key_monitor_signals":    key_signals,
        "shift_to_alternative":   shift_to_alternative,
        "confirm_first_vs_later": {
            "first":  confirm_first,
            "later":  confirm_later,
        },
    }


def compute_validation_matrix_for_event(
    event: Optional[dict],
) -> dict[str, Any]:
    """Convenience: resolve the effective family from ``event`` and
    return its validation matrix.

    Wraps ``compute_validation_matrix`` with
    ``family_inference.resolve_effective_family`` so a row stored with
    ``mechanism_family="none"`` (or missing) but containing a clear
    headline / mechanism_summary / primary_thesis still surfaces the
    correct family-specific playbook on the response path — without
    mutating the underlying row.

    Returns the empty-shape matrix when ``event`` isn't a dict.
    """
    if not isinstance(event, dict):
        return compute_validation_matrix(None)
    try:
        from family_inference import resolve_effective_family
    except Exception:
        return compute_validation_matrix(event.get("mechanism_family"))
    return compute_validation_matrix(resolve_effective_family(event))


def compute_validation_matrix(
    mechanism_family: Optional[str] = None,
) -> dict[str, Any]:
    """Return the family-specific validation playbook.

    Pure data lookup on ``mechanism_family.FAMILY_VALIDATION_MATRIX``,
    wrapped so the caller gets a stable shape even for unknown / None
    families (everything degrades to the empty ``"none"`` entry).

    The returned dict surfaces:
      * ``primary`` / ``secondary`` — expected confirmation channels
        with expected_direction, timing, and desk-note rationale
      * ``false_positives`` — channels that often LOOK like confirmation
        but aren't mechanism-specific; each carries a
        ``distinguishing_signal`` for separating real from coincidental
      * ``invalidation`` — the strongest falsifiers
      * ``timing_by_channel`` — per-channel horizon (controlled
        vocabulary: "1d" | "1-5d" | "5-20d" | "20d+")
      * ``available`` — false iff family is "none" / unmapped
    """
    family = mechanism_family or "none"
    matrix = get_validation_matrix(family)
    available = bool(
        matrix["primary"] or matrix["secondary"]
        or matrix["false_positives"] or matrix["invalidation"]
    )
    return {
        "mechanism_family": family,
        "available":        available,
        **matrix,
    }
