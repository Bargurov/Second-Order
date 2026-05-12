"""Pure projection from raw mover cards to the UI-ready card shape.

Every mover surface (/market-movers, /movers/today, /movers/weekly,
/movers/persistent) runs through the same ``_build_mover_summary``
→ ``sanitize_mover_card`` pipeline inside ``movers_cache`` / ``api``.
The raw card it produces carries many legacy fields that differ from
what the frontend mover strips actually need.  This module is the
single projection step that collapses the raw card into the
11-field UI-ready shape documented in the task contract:

    {
      id, headline, mechanism_family, thesis_state, proof_quality,
      stale_signal, mover_window, weighted_evidence, surfaced_reason,
      moved_tickers, strongest_move_5d,
    }

Pure composer — no I/O, no DB.  Takes a raw mover card dict plus the
window token and returns the UI-ready dict.  ``dedup_mover_cards``
is a sibling helper that collapses near-identical studies (same
``mechanism_family`` + same leading headline content words) so one
cluster cannot flood a surface.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


# ``mover_window`` vocabulary — the task pins these exact four tokens.
MOVER_WINDOWS: tuple[str, ...] = ("today", "weekly", "persistent", "market")
_MOVER_WINDOWS_SET: frozenset[str] = frozenset(MOVER_WINDOWS)

# Top-N moved tickers kept on the UI card.  Task cap is 1–3.
_MOVED_TICKERS_MAX: int = 3

# Max characters preserved on ``surfaced_reason`` — a concise one-liner
# for card footers / share text, not the full prose.
_SURFACED_REASON_MAX_LEN: int = 200

# Signature-length for dedup.  Five content-word prefix is enough to
# catch re-wrap of the same headline while not conflating distinct
# events with shared leading words ("OPEC cuts oil" vs "OPEC cuts
# production").  Mechanism family is tied into the signature so a
# tariff headline on X and a sanction headline on X don't collide.
_CLUSTER_WORD_PREFIX: int = 5
_CLUSTER_MIN_WORD_LEN: int = 3

# Minimum content-word count a headline must carry before the cluster
# signature is trusted to collapse duplicates.  Below this floor the
# signature is "weak" — we pass the card through rather than
# collapsing unrelated short headlines (e.g. "Energy event A" vs
# "Energy event B" share the first two content words but are
# different stories).
_CLUSTER_MIN_WORDS_FOR_SIGNATURE: int = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _top_moved_tickers(raw_tickers: Any, *, window: str = "market") -> list[dict]:
    """Return the top 1–3 thesis-relevant tickers by |return|.

    A ticker qualifies when it has a finite return for the surface's
    primary window: ``return_5d`` for everything except ``today``, where
    we fall back to ``return_1d`` because the 24h surface is younger
    than the 5-day window by definition (a today event typically only
    has a 1-day reaction so far).  Sort is descending by absolute
    magnitude with ``symbol`` as a deterministic tiebreaker — same
    convention as ``_build_mover_summary``.
    """
    if not isinstance(raw_tickers, list):
        return []
    candidates: list[tuple[float, dict, float]] = []
    for t in raw_tickers:
        if not isinstance(t, dict):
            continue
        r5 = _safe_float(t.get("return_5d"))
        if r5 is None and window == "today":
            r5 = _safe_float(t.get("return_1d"))
        if r5 is None:
            continue
        candidates.append((abs(r5), t, r5))
    # Sort by |r| desc, symbol asc as tiebreaker.
    candidates.sort(
        key=lambda triple: (-triple[0], (triple[1].get("symbol") or "")),
    )
    out: list[dict] = []
    for _, t, primary in candidates[:_MOVED_TICKERS_MAX]:
        out.append({
            "symbol":    t.get("symbol") or "",
            "role":      t.get("role"),
            "direction": t.get("direction") or t.get("direction_tag"),
            "return_5d": primary,
        })
    return out


def _strongest_move_5d(moved: list[dict]) -> float | None:
    """Max |return_5d| across the already-trimmed moved_tickers list."""
    best: float | None = None
    for t in moved:
        r5 = _safe_float(t.get("return_5d"))
        if r5 is None:
            continue
        if best is None or abs(r5) > abs(best):
            best = r5
    return best


def _proof_quality(card: dict) -> str:
    """Collapse per-card proof signals into a single-word quality hint.

    Priority: explicit ``proof_status.status`` → ``quality.confidence_basis``
    → ``"unknown"``.  Vocabulary is intentionally open — UI can style
    known values (``met`` / ``partial`` / ``unmet`` / ``none`` from the
    evaluator, ``strong_evidence`` / ``mixed_quality`` / etc from the
    evidence-quality layer) and fall back to the string verbatim.
    """
    proof = card.get("proof_status")
    if isinstance(proof, dict):
        status = proof.get("status")
        if isinstance(status, str) and status:
            return status
    quality = card.get("quality")
    if isinstance(quality, dict):
        basis = quality.get("confidence_basis")
        if isinstance(basis, str) and basis:
            return basis
    return "unknown"


def _stale_signal(card: dict) -> str:
    """Surface the data-quality tag the sanitizer already attached.

    Falls back to the event-row ``stale_signal`` value (persisted by
    ``market_check_freshness.compute_staleness``) when the sanitizer
    field is absent.  Default is ``"ok"`` — anything stale should have
    been marked explicitly upstream.
    """
    dq = card.get("data_quality")
    if isinstance(dq, str) and dq:
        return dq
    tag = card.get("stale_signal")
    if isinstance(tag, str) and tag:
        return tag
    return "ok"


def _surfaced_reason(card: dict) -> str:
    """Pull a concise one-line reason from the rich mover dict.

    Prefers ``why_still_moving`` (hand-composed narrative), falls
    through to ``rank_rationale`` and finally to the evidence ladder's
    ``narrative``.  Truncates to keep card footers compact.
    """
    for key in ("why_still_moving", "rank_rationale"):
        val = card.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:_SURFACED_REASON_MAX_LEN]
    evidence = card.get("evidence")
    if isinstance(evidence, dict):
        narr = evidence.get("narrative")
        if isinstance(narr, str) and narr.strip():
            return narr.strip()[:_SURFACED_REASON_MAX_LEN]
    return ""


# ---------------------------------------------------------------------------
# Quality gate — demote / filter / choose-best-per-cluster
# ---------------------------------------------------------------------------

# Controlled vocabulary for ``surfaced_reason`` on every surfaced
# card.  The task pins exactly these four phrases; no new enum tokens
# are added beyond them.
SURFACED_REASONS: tuple[str, ...] = (
    "strongest move",
    "persistent follow-through",
    "proof-backed confirmation",
    "contradiction worth attention",
)

# Stale-style tags that mean the market read is too old to trust — the
# same vocabulary ``compute_staleness`` / ``thesis_state`` already use.
_STALE_STATUSES: frozenset[str] = frozenset({"stale", "legacy"})


def _has_low_information(card: dict) -> bool:
    """True when the card carries the low-information flag."""
    if not isinstance(card, dict):
        return False
    if card.get("low_information") is True:
        return True
    if card.get("thesis_state") == "low_information":
        return True
    return False


def _has_insufficient_evidence(card: dict) -> bool:
    we = card.get("weighted_evidence")
    if not isinstance(we, dict):
        return False
    return we.get("evidence_label") == "insufficient"


def _is_stale_card(card: dict) -> bool:
    return _stale_signal(card) in _STALE_STATUSES


def _should_demote(card: dict) -> bool:
    """Cards pushed to the tail of /movers/today and /movers/weekly.

    These surfaces still want to *show* the card so the reader can
    see why it lost trust, but it should never lead the list.
    """
    return (
        _is_stale_card(card)
        or _has_low_information(card)
        or _has_insufficient_evidence(card)
    )


def _is_persistent_eligible(card: dict) -> bool:
    """Loose persistent-window eligibility.

    Drops stale / legacy / low-info / falsified rows.  Used by the
    yearly-projected-as-persistent surface and as the first stage of
    the ``/movers/persistent`` strict gate.  A persistence window is
    about ongoing follow-through, and anything carrying one of those
    tags is no longer meaningfully tracked.
    """
    if _is_stale_card(card):
        return False
    if _has_low_information(card):
        return False
    thesis = card.get("thesis_state")
    if thesis in ("low_information", "falsified"):
        return False
    return True


# ``thesis_state`` values that pass the high-conviction persistent
# gate.  ``confirming`` is the proof-backed positive; ``partial`` is
# the supportive-evidence-without-full-proof positive.  Anything else
# (watching / weakening / falsified / stale / low_information) is
# either neutral or already disqualifying.
_PERSISTENT_THESIS_STATES: frozenset[str] = frozenset({"confirming", "partial"})


# Sector-ETF symbols that are too broad to serve as a single-name
# "primary" read on the Still Moving Market surface.  Mirrors the
# blocklist in scripts/section_c_still_moving_quality_diagnostic.py
# (``_SECTOR_ETFS_AS_PRIMARY_BLOCKLIST``) so the production gate and
# the curated-archive diagnostic flag the same proxies.  A persistent
# card whose top mover (by |return_5d|) sits in this set is rejected
# so the surface reads as a single-name story, not a sector-wide
# tape.
_SECTOR_ETFS_AS_PRIMARY: frozenset[str] = frozenset({
    "SPY",
    "XLE", "XLF", "XLK", "XLV", "XLI", "XLB",
    "XLU", "XLY", "XLP", "XLRE",
    "SMH", "XAR",
})


def _persistent_top_mover_symbol(card: dict) -> str | None:
    """Return the upper-cased symbol of the card's strongest |return_5d|
    mover, or ``None`` when no usable ticker is present.

    Reuses ``_top_moved_tickers`` so the "primary" the gate inspects
    matches what the surface would actually render at the top of the
    card preview.
    """
    if not isinstance(card, dict):
        return None
    moved = _top_moved_tickers(card.get("tickers"))
    if not moved:
        return None
    sym = moved[0].get("symbol")
    if not isinstance(sym, str):
        return None
    sym = sym.strip().upper()
    return sym or None


def primary_is_sector_etf(card: dict) -> bool:
    """True when the persistent card's top mover is in the sector-ETF
    blocklist.  Used by both the route-level gate and the diagnostic
    rejection-reason attributor so the two stay aligned.
    """
    sym = _persistent_top_mover_symbol(card)
    return sym is not None and sym in _SECTOR_ETFS_AS_PRIMARY


def _conviction_class(card: dict) -> str | None:
    block = card.get("conviction")
    if isinstance(block, dict):
        cc = block.get("conviction_class")
        if isinstance(cc, str):
            return cc
    return None


def _evidence_label(card: dict) -> str | None:
    we = card.get("weighted_evidence")
    if isinstance(we, dict):
        label = we.get("evidence_label")
        if isinstance(label, str):
            return label
    return None


def is_high_conviction_persistent(card: dict) -> bool:
    """Strict ``/movers/persistent`` gate — the high-impact "Still Moving
    Markets" rule.

    A card surfaces only when ALL of the following hold:

      * passes the loose persistent gate (no stale / legacy /
        low-information / falsified row),
      * carries ``weighted_evidence.evidence_label == "supportive"``,
      * ``thesis_state`` is ``confirming`` or ``partial``,
      * ``conviction.conviction_class == "conviction"`` — the
        primary-confirmation × durable-follow-through bucket from
        :mod:`movers_ranking`,
      * ``conviction.impact_level == "high"``,
      * the top mover (by ``|return_5d|``) is NOT a sector ETF from
        :data:`_SECTOR_ETFS_AS_PRIMARY` — a sector-ETF primary cannot
        carry the single-name read this surface promises.

    The conviction-class condition already requires
    ``persistence_quality >= 0.15`` (i.e. a ``grind`` / ``gap_and_hold``
    / ``second_leg`` repricing read), so it subsumes the explicit
    "persistent follow-through" requirement without a redundant
    persistence_signal probe.
    """
    if not isinstance(card, dict):
        return False
    if not _is_persistent_eligible(card):
        return False
    if _has_insufficient_evidence(card):
        return False
    if card.get("thesis_state") not in _PERSISTENT_THESIS_STATES:
        return False
    if _evidence_label(card) != "supportive":
        return False
    if _conviction_class(card) != "conviction":
        return False
    conviction = card.get("conviction")
    if not isinstance(conviction, dict):
        return False
    if conviction.get("impact_level") != "high":
        return False
    if primary_is_sector_etf(card):
        return False
    return True


def _cluster_quality_score(card: dict) -> float:
    """Score used to pick the strongest representative inside a cluster.

    Combines the per-card move magnitude with the weighted-evidence
    score (when present) and a small lift for proof-backed cards.
    Deterministic: tiebreaker is the ``event_id`` (lower wins to keep
    stable ordering) handled by the caller via sort key.
    """
    if not isinstance(card, dict):
        return 0.0
    score = 0.0
    we = card.get("weighted_evidence") or {}
    if isinstance(we, dict):
        s = _safe_float(we.get("evidence_score"))
        if s is not None:
            score += abs(s) * 100.0
    moved = _top_moved_tickers(card.get("tickers"))
    strongest = _strongest_move_5d(moved)
    if strongest is not None:
        score += abs(strongest)
    if card.get("has_proof_set") and card.get("has_falsifiers"):
        score += 10.0
    return score


def _explicit_surfaced_reason(card: dict, *, window: str) -> str:
    """Return one of ``SURFACED_REASONS`` explaining why this card
    was chosen.  Priority:

      1. ``contradiction worth attention``  — falsified thesis or
         contradictory weighted evidence.
      2. ``proof-backed confirmation``       — supportive weighted
         evidence on a proof-backed study.
      3. ``persistent follow-through``       — the persistent surface.
      4. ``strongest move``                  — the default residual
         for today / weekly / market cards that don't trip the above.
    """
    we = card.get("weighted_evidence")
    label = we.get("evidence_label") if isinstance(we, dict) else None
    thesis = card.get("thesis_state")
    if label == "contradictory" or thesis == "falsified":
        return "contradiction worth attention"
    if (
        label == "supportive"
        and card.get("has_proof_set")
        and card.get("has_falsifiers")
    ):
        return "proof-backed confirmation"
    if window == "persistent":
        return "persistent follow-through"
    return "strongest move"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def to_ui_card(card: Any, window: str) -> dict:
    """Project a raw mover card onto the UI-ready 11-field shape.

    Parameters
    ----------
    card : the raw mover dict emitted by ``_build_mover_summary`` and
        (typically) post-processed by ``sanitize_mover_card``.
    window : one of ``MOVER_WINDOWS`` — the surface the card is being
        served from.  Raised to ``ValueError`` on unknown tokens so
        misspellings can't silently drift.
    """
    if window not in _MOVER_WINDOWS_SET:
        raise ValueError(
            f"unknown mover_window={window!r}; allowed: {list(MOVER_WINDOWS)}"
        )
    if not isinstance(card, dict):
        card = {}

    moved = _top_moved_tickers(card.get("tickers"), window=window)
    strongest = _strongest_move_5d(moved)

    weighted = card.get("weighted_evidence")
    if not isinstance(weighted, dict):
        weighted = {}

    return {
        "id":                card.get("event_id"),
        "headline":          card.get("headline") or "",
        "mechanism_family":  card.get("mechanism_family") or "none",
        "thesis_state":      card.get("thesis_state") or "unknown",
        "proof_quality":     _proof_quality(card),
        "stale_signal":      _stale_signal(card),
        "mover_window":      window,
        "weighted_evidence": weighted,
        "surfaced_reason":   _explicit_surfaced_reason(card, window=window),
        "moved_tickers":     moved,
        "strongest_move_5d": strongest,
    }


# ---------------------------------------------------------------------------
# Dedup — one cluster should not flood a mover surface
# ---------------------------------------------------------------------------


def _cluster_signature(card: dict) -> tuple[str, str]:
    """Return a ``(family, content-word-prefix)`` signature.

    Strips punctuation, lower-cases, drops words shorter than
    ``_CLUSTER_MIN_WORD_LEN``, and joins the first
    ``_CLUSTER_WORD_PREFIX`` survivors.  Combined with mechanism
    family this captures "same story" — two re-wraps of the same
    event under the same family share a signature; a tariff story
    and a sanction story on the same actor do not.
    """
    fam = (card.get("mechanism_family") or "none").strip().lower()
    headline = str(card.get("headline") or "").lower()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", headline)
    words = [w for w in cleaned.split() if len(w) >= _CLUSTER_MIN_WORD_LEN]
    # Thin-signature guard: short headlines don't carry enough
    # content-word mass to be safely clustered.  Return an empty
    # prefix so the dedup layer treats the card as "no cluster
    # identity" and lets it through.
    if len(words) < _CLUSTER_MIN_WORDS_FOR_SIGNATURE:
        return (fam, "")
    prefix = " ".join(words[:_CLUSTER_WORD_PREFIX])
    return (fam, prefix)


def dedup_mover_cards(cards: Iterable[dict]) -> list[dict]:
    """Collapse near-identical studies to one card per cluster.

    First-seen-wins on the ``(mechanism_family, headline prefix)``
    signature so the caller's input ordering (already ranked by the
    mover builder) controls which card survives.  Empty / malformed
    cards pass through untouched so the dedup layer can't silently
    drop data it doesn't understand.
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for c in cards or []:
        if not isinstance(c, dict):
            out.append(c)
            continue
        sig = _cluster_signature(c)
        # Empty-prefix signatures (thin headlines below the
        # ``_CLUSTER_MIN_WORDS_FOR_SIGNATURE`` floor, regardless of
        # family) cannot be safely grouped — pass the card through so
        # short distinct headlines aren't collapsed onto one slot.
        if sig[1] == "":
            out.append(c)
            continue
        if sig in seen:
            continue
        seen.add(sig)
        out.append(c)
    return out


def to_ui_cards(cards: Iterable[Any], window: str) -> list[dict]:
    """Convenience: project + dedup in one call.

    Dedup runs on the PROJECTED cards (UI shape) so the cluster
    signature is computed against the same ``mechanism_family`` /
    ``headline`` values a consumer sees — not the richer raw card
    keys that can drift as ``_build_mover_summary`` evolves.
    """
    projected = [to_ui_card(c, window) for c in cards or []]
    return dedup_mover_cards(projected)


# ---------------------------------------------------------------------------
# Diversity guardrails — applied to today / weekly / market-movers
# ---------------------------------------------------------------------------

# Exponential decay applied each time a family appears.  Tuned softer
# than relevance_ranking (0.7) because mover surfaces are smaller and
# a single very-strong mover should still lead even if it shares a
# family with the next-best card.  Siblings are demoted, not hidden.
_FAMILY_DECAY_MOVERS: float = 0.6


def _raw_mover_score(card: dict) -> float:
    """Raw magnitude signal on a card, independent of ordering.

    Prefers ``impact``/``rank_score``/``effective_score`` (the ranker's
    own composite) and falls back to the strongest |return_5d| on
    moved_tickers so a card without a composite score still carries
    weight.  Returns ``0.0`` for anything non-numeric.
    """
    if not isinstance(card, dict):
        return 0.0
    for key in ("impact", "rank_score", "effective_score"):
        v = card.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            f = _safe_float(v)
            if f is not None:
                return abs(f)
    moved = card.get("moved_tickers")
    if isinstance(moved, list):
        strongest = _strongest_move_5d(moved)
        if strongest is not None:
            return abs(strongest)
    s = card.get("strongest_move_5d")
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        f = _safe_float(s)
        if f is not None:
            return abs(f)
    return 0.0


def apply_diversity_guardrails(
    cards: Iterable[Any],
    *,
    family_decay: float = _FAMILY_DECAY_MOVERS,
) -> list[dict]:
    """Re-rank mover cards to prevent cluster / family flood.

    Greedy decay walk: at each step pick the card with the highest
    adjusted score, where adjustment = raw_score × decay^(times this
    family has already been picked).  Cluster signature collisions are
    collapsed upstream by dedup, so the guardrail here only fights
    one-family dominance.  Ordering stability: ties fall back to the
    original input order.

    Non-dict entries pass through to the tail so the guardrail cannot
    silently drop data it doesn't understand.
    """
    items: list[dict] = []
    pass_through: list[Any] = []
    for c in cards or []:
        if isinstance(c, dict):
            items.append(c)
        else:
            pass_through.append(c)
    if not items:
        return list(pass_through)

    # Preserve original rank as a deterministic tiebreaker.
    original_index = {id(c): i for i, c in enumerate(items)}
    family_seen: dict[str, int] = {}
    remaining = list(items)
    ordered: list[dict] = []

    while remaining:
        best = None
        best_adj = None
        best_idx = None
        for i, card in enumerate(remaining):
            fam = (card.get("mechanism_family") or "none") or "none"
            n = family_seen.get(fam, 0)
            adj = _raw_mover_score(card) * (family_decay ** n)
            if (
                best is None
                or adj > best_adj
                or (adj == best_adj
                    and original_index[id(card)]
                    < original_index[id(best)])
            ):
                best = card
                best_adj = adj
                best_idx = i
        ordered.append(best)
        remaining.pop(best_idx)
        fam = (best.get("mechanism_family") or "none") or "none"
        family_seen[fam] = family_seen.get(fam, 0) + 1

    return ordered + pass_through


def compute_mover_meta(cards: Iterable[Any]) -> dict:
    """Return the response-level meta block for a mover surface.

    Keys (pinned by the task):
      surfaced_count   — total cards returned (dict entries only).
      unique_clusters  — distinct ``_cluster_signature`` values,
                         counting thin-signature cards as singletons.
      unique_families  — distinct ``mechanism_family`` values present.
    """
    surfaced = 0
    families: set[str] = set()
    cluster_keys: set = set()
    for idx, c in enumerate(cards or []):
        if not isinstance(c, dict):
            continue
        surfaced += 1
        fam = (c.get("mechanism_family") or "none") or "none"
        families.add(fam)
        sig = _cluster_signature(c)
        # Thin-signature cards count as unique singletons — pair with
        # the positional index so they don't all collapse to one bucket.
        cluster_keys.add(sig if sig[1] else (fam, f"__thin_{idx}"))
    return {
        "surfaced_count":  surfaced,
        "unique_clusters": len(cluster_keys),
        "unique_families": len(families),
    }


def enrich_mover_cards(cards: Iterable[Any], window: str) -> list[dict]:
    """Merge UI-ready fields onto the raw cards (additive projection).

    Window-aware quality gate:

      * ``persistent`` — drop any card that is stale / legacy /
        low-information / falsified.  A persistence surface should
        only carry studies still meaningfully tracked.
      * ``market``     — when multiple cards share a cluster signature,
        keep the single strongest representative (``_cluster_quality_score``)
        rather than first-seen.
      * ``today`` / ``weekly`` — demote stale / low-info /
        insufficient-evidence cards to the tail of the list instead
        of filtering them (the reader still wants to see *why* a
        formerly-moving card lost trust).

    Dedup still runs on every surface so one cluster cannot flood.
    """
    merged: list[dict] = []
    for raw in cards or []:
        if not isinstance(raw, dict):
            merged.append(raw)
            continue
        ui = to_ui_card(raw, window)
        merged.append({**raw, **ui})

    if window == "persistent":
        merged = [c for c in merged
                  if not isinstance(c, dict) or _is_persistent_eligible(c)]

    if window == "market":
        # Pick the strongest representative per cluster signature.
        # Input order still provides the tiebreaker for equal-quality
        # siblings — ``max`` with a stable key preserves "first seen".
        by_cluster: dict[tuple[str, str], dict] = {}
        pass_through: list[dict] = []
        for card in merged:
            if not isinstance(card, dict):
                pass_through.append(card)
                continue
            sig = _cluster_signature(card)
            if sig[1] == "":
                pass_through.append(card)
                continue
            prev = by_cluster.get(sig)
            if prev is None:
                by_cluster[sig] = card
                continue
            if _cluster_quality_score(card) > _cluster_quality_score(prev):
                by_cluster[sig] = card
        # Re-emit in the original input order (using ``merged`` as the
        # ordering reference) so downstream ranking / ordering logic
        # isn't disturbed by the selection step.
        chosen_ids = {id(v) for v in by_cluster.values()}
        pass_through_ids = {id(v) for v in pass_through
                            if isinstance(v, dict)}
        merged = [
            c for c in merged
            if (isinstance(c, dict) and id(c) in chosen_ids)
            or (isinstance(c, dict) and id(c) in pass_through_ids)
            or (not isinstance(c, dict))
        ]
    else:
        # Standard first-seen-wins dedup on the non-market surfaces
        # (today / weekly / persistent).  Preserves backward-compatible
        # behaviour after the window-specific filter/demote above.
        seen: set[tuple[str, str]] = set()
        deduped: list[dict] = []
        for card in merged:
            if not isinstance(card, dict):
                deduped.append(card)
                continue
            sig = _cluster_signature(card)
            if sig[1] != "" and sig in seen:
                continue
            if sig[1] != "":
                seen.add(sig)
            deduped.append(card)
        merged = deduped

    if window in ("today", "weekly"):
        # Stable partition: keep-as-is, then demote-to-tail.  Within
        # each tier the original input order is preserved so the
        # ranker's intent still drives ordering among peers.
        kept: list[dict] = []
        demoted: list[dict] = []
        for card in merged:
            if isinstance(card, dict) and _should_demote(card):
                demoted.append(card)
            else:
                kept.append(card)
        merged = kept + demoted

    return merged
