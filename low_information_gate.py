"""Strict low-information gate for analysis output.

A study must clear two concrete-evidence prongs to be treated as a
real mechanism call:

  1. A concrete mechanism statement — the LLM's ``mechanism_summary``
     must be longer than trivial filler and must not contain the
     standard "insufficient evidence" / "unclear mechanism" markers.
  2. At least one concrete asset / ticker / proxy — the analysis
     must name at least one tickerable instrument in any of its
     asset buckets.

When either prong fails, the gate fires and the event is coerced to a
canonical low-information shape:

  * ``confidence`` → ``"low"``
  * ``minimum_proof_set`` → ``[]``
  * ``key_falsifiers`` → ``[]``
  * ``critical_breakpoints`` → ``[]``
  * ``beneficiaries`` / ``losers`` / ``assets_to_watch`` → re-filtered
    to drop any vague-placeholder padding

This module is the single source of truth for "what counts as a
low-information study."  ``portfolio_flags.is_low_information`` and
the UI-facing ``thesis_state`` state both read from it so the
classification stays consistent across surfaces.

Pure composer.  No I/O.  Never raises.
"""

from __future__ import annotations

import re
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Mechanism-text gate
# ---------------------------------------------------------------------------

# Exact substring markers the LLM emits when it doesn't have enough
# evidence to commit to a mechanism.  Case-insensitive substring match.
_GENERIC_FILLER_MARKERS: tuple[str, ...] = (
    "insufficient evidence",
    "insufficient data",
    "not enough evidence",
    "unclear mechanism",
    "no clear mechanism",
    "mechanism is unclear",
    "mechanism unclear",
    "n/a",
    "none identified",
    "not applicable",
    "too early to tell",
    "remains to be seen",
    "not yet clear",
    "no specific mechanism",
    "no identifiable mechanism",
    "cannot be determined",
    "cannot determine",
)

# Minimum mechanism-summary length, in characters.  A real mechanism
# statement at least names the actor + the action + the channel —
# comfortably more than 40 chars of prose.  Below this threshold we
# treat the text as filler.
_MIN_MECHANISM_LENGTH: int = 40

# Minimum count of "content words" (alphabetic tokens of ≥5 chars).
# Catches short strings that happen to clear the character count via
# punctuation / numbers but carry no real content (e.g. "n/a n/a n/a").
_MIN_CONTENT_WORDS: int = 3


def is_low_information_mechanism(text: Any) -> bool:
    """True when ``text`` is missing, empty, a filler marker, or too
    short / content-sparse to be a real mechanism statement."""
    if not isinstance(text, str):
        return True
    stripped = text.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    for marker in _GENERIC_FILLER_MARKERS:
        if marker in lowered:
            return True
    if len(stripped) < _MIN_MECHANISM_LENGTH:
        return True
    words = [w for w in re.findall(r"[a-zA-Z]+", stripped) if len(w) >= 5]
    if len(words) < _MIN_CONTENT_WORDS:
        return True
    return False


# ---------------------------------------------------------------------------
# Mechanism-quality gate — five-prong structural check
# ---------------------------------------------------------------------------
# A real mechanism statement explicitly names FIVE elements:
#
#   1. trigger                               — the concrete change that
#                                               sets the cascade off
#   2. transmission channel                  — the named route through
#                                               which the shock travels
#   3. affected constraint / pricing rel.    — the chokepoint, spread,
#                                               or capacity the shock
#                                               actually moves
#   4. affected actor                        — named beneficiary or
#                                               loser entity
#   5. expected market expression            — a tradable asset / proxy
#                                               the chain lands on
#
# Without all five, the mechanism is narrative without a tape.  We
# treat that as a low-information study even if the prose looks rich.

# Vague mechanism phrases — text shapes the LLM falls back to when it
# cannot articulate a real mechanism.  Anchored to the patterns the
# tightening rounds keep surfacing in production analyses.
_VAGUE_MECHANISM_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bmarkets?\s+price\s+(risk|in)\b", re.I),
    re.compile(r"\binvestors?\s+(react|reposition|reprice|adjust)\b", re.I),
    re.compile(r"\b(the\s+)?sector\s+benefits?\b", re.I),
    re.compile(r"\buncertainty\s+(rises?|increases?|grows?|builds?)\b", re.I),
    re.compile(r"\bmarket\s+sentiment\s+(shifts?|changes?)\b", re.I),
    re.compile(r"\b(broader|general)\s+market\s+reaction\b", re.I),
    re.compile(r"\bmacro\s+headwinds?\b", re.I),
    re.compile(r"\brisk\s+appetite\s+(shifts?|fades?|wanes?)\b", re.I),
)

# Constraint / pricing-relationship markers — the LLM has named a
# concrete chokepoint or pricing primitive the mechanism turns on.
# Substring match (case-insensitive) over mechanism_summary.
_CONSTRAINT_MARKER_TOKENS: tuple[str, ...] = (
    "spread", "discount", "premium", "margin", "yield", "basis",
    "pricing power", "feedstock", "chokepoint", "bottleneck",
    "scarcity", "capacity", "throughput", "passthrough", "pass-through",
    "supply", "demand", "diff", "differential", "carry",
    "inventory", "stockpile", "import", "export", "tariff",
    "license", "licence", "sanction", "embargo", "quota",
    "rate", "duration", "credit spread", "discount rate",
    "carveout", "carve-out", "sole source", "sole-source",
)


def _has_vague_mechanism_text(text: Any) -> bool:
    """True when ``text`` matches any vague-mechanism pattern."""
    if not isinstance(text, str) or not text:
        return False
    for pat in _VAGUE_MECHANISM_PATTERNS:
        if pat.search(text):
            return True
    return False


def _content_tokens(text: Any, *, min_len: int = 5) -> set[str]:
    """Lowercased content tokens (alphabetic, length >= ``min_len``)."""
    if not isinstance(text, str) or not text:
        return set()
    return {
        w.lower() for w in re.findall(r"[a-zA-Z]+", text)
        if len(w) >= min_len
    }


def _flatten_actor_text(event: dict) -> str:
    """Join beneficiary/loser strings + transmission-path actors into
    one searchable blob.  Used both for primary-thesis overlap and for
    the actor-prong check."""
    bits: list[str] = []
    for key in ("beneficiaries", "losers"):
        seq = event.get(key)
        if isinstance(seq, list):
            bits.extend(s for s in seq if isinstance(s, str))
    path = event.get("transmission_path")
    if isinstance(path, list):
        for hop in path:
            if not isinstance(hop, dict):
                continue
            actor = hop.get("actor")
            if isinstance(actor, str):
                bits.append(actor)
    return " ".join(bits)


def _has_named_actor(event: dict) -> bool:
    """True when at least one concrete beneficiary or loser entity is
    listed.  Vague placeholders are filtered by the analyze_event
    sanitizers before we get here, so a non-empty list is sufficient."""
    for key in ("beneficiaries", "losers"):
        seq = event.get(key)
        if isinstance(seq, list) and any(
            isinstance(s, str) and s.strip() for s in seq
        ):
            return True
    # Fallback: a transmission path with at least one named actor.
    path = event.get("transmission_path")
    if isinstance(path, list):
        for hop in path:
            if isinstance(hop, dict):
                actor = hop.get("actor")
                if isinstance(actor, str) and actor.strip():
                    return True
    return False


def _has_transmission_channel(event: dict) -> bool:
    """True when at least one canonical transmission channel is
    named — either via a transmission_path hop or via the
    expected_first_order_channels list."""
    path = event.get("transmission_path")
    if isinstance(path, list):
        for hop in path:
            if not isinstance(hop, dict):
                continue
            ch = hop.get("channel")
            if isinstance(ch, str) and ch and ch != "unclassified":
                return True
    first_pack = event.get("expected_first_order_channels")
    if isinstance(first_pack, list) and any(
        isinstance(x, str) and x.strip() for x in first_pack
    ):
        return True
    return False


def _has_constraint_relationship(event: dict) -> bool:
    """True when the mechanism narrative names a constraint / pricing
    primitive — either by keyword in ``mechanism_summary`` /
    ``what_changed`` or via a populated structural field
    (``substitution_barriers`` / ``hidden_mechanism.bottleneck_type``)."""
    blob_parts: list[str] = []
    for key in ("mechanism_summary", "what_changed"):
        v = event.get(key)
        if isinstance(v, str):
            blob_parts.append(v)
    blob = " ".join(blob_parts).lower()
    if any(tok in blob for tok in _CONSTRAINT_MARKER_TOKENS):
        return True

    barriers = event.get("substitution_barriers")
    if isinstance(barriers, list) and any(
        isinstance(b, dict) and isinstance(b.get("barrier"), str)
        and b.get("barrier", "").strip() for b in barriers
    ):
        return True

    hm = event.get("hidden_mechanism")
    if isinstance(hm, dict):
        bt = hm.get("bottleneck_type")
        if isinstance(bt, str) and bt and bt != "none":
            return True
    return False


def _has_market_expression(event: dict) -> bool:
    """True when the analysis lands at a tradable instrument — either
    a concrete ticker bucket or the LAST transmission_path hop carries
    an ``expected_market_effect``."""
    if has_concrete_asset(event):
        return True
    path = event.get("transmission_path")
    if isinstance(path, list) and path:
        last = path[-1]
        if isinstance(last, dict):
            effect = last.get("expected_market_effect")
            if isinstance(effect, str) and effect.strip():
                return True
    return False


# ---------------------------------------------------------------------------
# Causal-strength score — internal 0/5 scoring derived from the same
# five mechanism prongs.
# ---------------------------------------------------------------------------
# Why a number on top of the existing boolean gate
# ------------------------------------------------
# The mechanism-quality gate is binary: either all five prongs pass or
# the study is weak.  That collapses the natural middle band — an
# analysis with 4/5 prongs satisfied is a real read with one weak spot,
# not a placeholder.  The causal-strength score keeps the same prong
# definitions but exposes the count, which the tier classifier uses to
# split:
#
#   * score == 5            → potentially actionable (existing 3-prong
#                              actionable check decides the final call)
#   * score in [3, 5)        → watch_only (real but incomplete chain)
#   * score < 3              → low_information (≥3 prongs missing)
#
# The score also drives ``clear_weak_chain_proof``: a chain rated
# below the watch_only floor cannot earn a populated proof / falsifier
# / critical_breakpoints structure, since those elements are testing
# claims the mechanism never actually makes.
#
# Score is INTERNAL — not added to the event dict / response shape.
# Callers compute it on demand.

# Threshold below which the proof / falsifier / breakpoint lists are
# stripped: a chain with this many prongs missing can't carry
# verifiable claims.
_PROOF_RETENTION_FLOOR: float = 4.0

# Threshold below which the study is forced to ``low_information``.
# Mirrors the score-band definition above; the gate uses this when
# normalising weak mechanisms.
_LOW_INFO_FLOOR: float = 3.0

_CAUSAL_STRENGTH_PRONGS: tuple[str, ...] = (
    "trigger", "channel", "constraint", "actor", "market_expression",
)


def compute_causal_strength(event: Any) -> dict[str, Any]:
    """Return ``{score, max_score, components}`` for the five-prong
    causal-strength check.

    ``score`` is the count of satisfied prongs (0.0 – 5.0).  A vague-
    mechanism placeholder (matched by ``_VAGUE_MECHANISM_PATTERNS``)
    collapses the score to 0.0 regardless of structural shape.

    ``components`` is a dict mapping each prong name to a bool — the
    classifier uses it for richer diagnostics; output shape stays
    stable because the score itself is never written onto ``event``.
    """
    empty_components = {prong: False for prong in _CAUSAL_STRENGTH_PRONGS}
    if not isinstance(event, dict):
        return {
            "score": 0.0, "max_score": 5.0, "components": empty_components,
        }

    quality = evaluate_mechanism_quality(event)
    if quality.get("vague"):
        return {
            "score": 0.0, "max_score": 5.0, "components": empty_components,
        }

    missing = set(quality.get("missing") or [])
    components = {prong: prong not in missing for prong in _CAUSAL_STRENGTH_PRONGS}
    score = float(sum(1 for v in components.values() if v))
    return {
        "score": score,
        "max_score": 5.0,
        "components": components,
    }


def clear_weak_chain_proof(event: dict) -> bool:
    """Strip proof / falsifier / breakpoint lists when the causal
    chain is too weak to support testable claims.

    Mutates ``event`` in place.  Returns True when the lists were
    cleared (callers can record this in validation_warnings); False
    otherwise.  Output keys stay stable — the lists are emptied,
    never deleted.
    """
    if not isinstance(event, dict):
        return False
    strength = compute_causal_strength(event)
    if strength["score"] >= _PROOF_RETENTION_FLOOR:
        return False
    cleared = False
    for key in ("minimum_proof_set", "key_falsifiers", "critical_breakpoints"):
        if event.get(key):
            event[key] = []
            cleared = True
    return cleared


def evaluate_mechanism_quality(event: Any) -> dict[str, Any]:
    """Return ``{is_valid, missing, vague}`` for the five-prong gate.

    ``missing`` is the closed-set list of element names that failed the
    structural check; ``vague`` is the matched vague-mechanism pattern
    text when the mechanism prose hits one of the placeholder phrases.
    Pure check — does NOT mutate ``event``.

    Element names: ``trigger`` | ``channel`` | ``constraint`` |
    ``actor`` | ``market_expression``.
    """
    if not isinstance(event, dict):
        return {
            "is_valid": False,
            "missing": [
                "trigger", "channel", "constraint", "actor",
                "market_expression",
            ],
            "vague": False,
        }

    mech = event.get("mechanism_summary") or ""
    wc = event.get("what_changed") or ""

    if _has_vague_mechanism_text(mech) or _has_vague_mechanism_text(wc):
        return {"is_valid": False, "missing": [], "vague": True}

    missing: list[str] = []
    # Trigger — what_changed must be a concrete statement.  We do NOT
    # apply the full mechanism-text gate here: what_changed is meant
    # to be terse ("OPEC cut ratified.") so the 40-char bar is too
    # high.  Instead we require: a non-empty string, no vague-mechanism
    # placeholder phrasing, and at least two content tokens of >=4
    # chars to filter out "n/a" / "tbd" / "x".
    if (
        not isinstance(wc, str)
        or not wc.strip()
        or _has_vague_mechanism_text(wc)
        or len(_content_tokens(wc, min_len=4)) < 2
    ):
        missing.append("trigger")
    if not _has_transmission_channel(event):
        missing.append("channel")
    if not _has_constraint_relationship(event):
        missing.append("constraint")
    if not _has_named_actor(event):
        missing.append("actor")
    if not _has_market_expression(event):
        missing.append("market_expression")

    return {
        "is_valid": not missing,
        "missing": missing,
        "vague": False,
    }


def primary_thesis_inconsistent(event: Any) -> bool:
    """True when ``competing_thesis.primary_thesis`` shares no content
    token with the mechanism narrative.

    Cheap heuristic: the primary_thesis sentence and the union of
    mechanism_summary / what_changed / beneficiaries / losers /
    transmission_path actors must overlap on at least one content
    token (alphabetic, length >= 5).  Zero overlap means the primary
    thesis is talking about something the mechanism never reaches —
    a self-contradiction.

    Returns False when no primary_thesis is present (nothing to
    contradict)."""
    if not isinstance(event, dict):
        return False
    ct = event.get("competing_thesis")
    if not isinstance(ct, dict):
        return False
    pt = ct.get("primary_thesis")
    if not isinstance(pt, str) or not pt.strip():
        return False
    pt_tokens = _content_tokens(pt)
    if not pt_tokens:
        return False

    blob_parts: list[str] = [
        event.get("mechanism_summary") or "",
        event.get("what_changed") or "",
        _flatten_actor_text(event),
    ]
    mech_tokens = _content_tokens(" ".join(blob_parts))
    if not mech_tokens:
        # If the mechanism has no content tokens at all, the mechanism
        # itself is the problem; let the mechanism-quality gate report
        # that without double-firing.
        return False
    return len(pt_tokens & mech_tokens) == 0


# ---------------------------------------------------------------------------
# Asset concreteness gate
# ---------------------------------------------------------------------------

# A ticker-like string: 1-6 uppercase letters / digits, with optional
# dot / equals / caret / hyphen suffixes (e.g. "ES=F", "^TNX", "BRK.B").
_TICKER_REGEX = re.compile(r"^[A-Z0-9][A-Z0-9.\-=\^]{0,9}$")

# Stricter than ``_is_bad_ticker`` in analyze_event — that one is a
# provider-level guard.  Here we additionally reject placeholder words
# the LLM sometimes emits inside ticker fields.
_TICKER_PLACEHOLDERS: frozenset[str] = frozenset({
    "N/A", "NONE", "TBD", "UNKNOWN", "NULL",
})


def _is_concrete_ticker(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip().upper()
    if not v or v in _TICKER_PLACEHOLDERS:
        return False
    return bool(_TICKER_REGEX.match(v))


def has_concrete_asset(event: Any) -> bool:
    """True when any of the event's ticker buckets carries a real
    instrument worth market-checking."""
    if not isinstance(event, dict):
        return False
    for key in (
        "beneficiary_tickers", "loser_tickers", "assets_to_watch",
    ):
        bucket = event.get(key)
        if not isinstance(bucket, list):
            continue
        for entry in bucket:
            if _is_concrete_ticker(entry):
                return True
            # Some bucket formats use dict entries with a ``symbol`` key.
            if isinstance(entry, dict):
                sym = entry.get("symbol") or entry.get("ticker")
                if _is_concrete_ticker(sym):
                    return True
    return False


# ---------------------------------------------------------------------------
# Gate + normalisation
# ---------------------------------------------------------------------------

def evaluate_low_information(event: Any) -> dict[str, Any]:
    """Return ``{is_low_info, reason}`` for ``event``.

    Reasons (closed set) surface why the gate fires so callers + tests
    can branch on them:

      * ``"filler_mechanism"``         — mechanism_summary is filler /
                                          too thin to count as a real
                                          statement
      * ``"no_concrete_asset"``        — no tickerable instrument in
                                          any asset bucket
      * ``"invalid_transmission_chain"`` — the event's transmission_path
                                          was provided but did not pass
                                          structural validation (vague
                                          hops, missing actor / channel /
                                          expected_market_effect, or no
                                          asset/proxy landing)
      * ``"weak_mechanism"``           — mechanism failed the five-prong
                                          quality gate: trigger /
                                          channel / constraint / actor /
                                          market_expression must all be
                                          named OR the prose hits a
                                          vague-mechanism placeholder
                                          ("markets price risk",
                                          "investors react", "sector
                                          benefits", "uncertainty
                                          rises")
      * ``"primary_thesis_inconsistent"`` — competing_thesis.primary_thesis
                                          shares no content token with
                                          the accepted mechanism — the
                                          thesis names actors / channels
                                          the mechanism never reaches
      * ``""``                         — gate cleared
    """
    if not isinstance(event, dict):
        return {"is_low_info": True, "reason": "filler_mechanism"}

    if is_low_information_mechanism(event.get("mechanism_summary")):
        return {"is_low_info": True, "reason": "filler_mechanism"}
    if not has_concrete_asset(event):
        return {"is_low_info": True, "reason": "no_concrete_asset"}

    # Structural-chain prong — a non-empty but invalid transmission_path
    # means the LLM tried to articulate the chain and produced something
    # the contract rejects (vague hops, no asset landing, missing
    # required fields).  An absent / empty path is handled by the
    # other gates above; we only fire this reason when a path was
    # provided.
    path = event.get("transmission_path")
    if isinstance(path, list) and path:
        try:
            from analyze_event import _is_valid_transmission_chain
        except Exception:
            _is_valid_transmission_chain = None  # type: ignore[assignment]
        if _is_valid_transmission_chain is not None \
                and not _is_valid_transmission_chain(path):
            return {
                "is_low_info": True,
                "reason": "invalid_transmission_chain",
            }

    # Mechanism-quality gate — five-prong structural check + vague-
    # phrase rejection.  A real mechanism statement names trigger,
    # transmission channel, affected constraint / pricing relationship,
    # affected actor, and an expected market expression.  The boolean
    # gate fires immediately on a vague-mechanism placeholder; the
    # prong-count threshold is governed by causal_strength so the
    # middle band (3-4 prongs satisfied) lands in ``watch_only`` rather
    # than ``low_information``.  Below the score floor the chain is
    # too thin to be a real read.
    quality = evaluate_mechanism_quality(event)
    if quality.get("vague"):
        return {"is_low_info": True, "reason": "weak_mechanism"}
    strength = compute_causal_strength(event)
    if strength["score"] < _LOW_INFO_FLOOR:
        return {"is_low_info": True, "reason": "weak_mechanism"}

    # Primary-thesis consistency — the committed primary_thesis must
    # overlap (on at least one content token) with the mechanism it
    # claims to read.  A primary_thesis naming actors the mechanism
    # never touches is a self-contradiction; coerce to low-info so the
    # UI doesn't render two stories at once.
    if primary_thesis_inconsistent(event):
        return {
            "is_low_info": True,
            "reason": "primary_thesis_inconsistent",
        }

    return {"is_low_info": False, "reason": ""}


# Vague-entity stripping reused across surfaces.  Mirrors the legacy
# ``_is_vague_entity`` in analyze_event for a single-file definition
# we can import from anywhere.
_VAGUE_ENTITY_PATTERNS: tuple[str, ...] = (
    "the sector", "the industry", "the market", "the economy",
    "broader market", "global markets", "various", "relevant",
    "multiple", "affected parties", "related parties",
    "interested parties", "stakeholders",
)


def _is_vague_asset_label(text: Any) -> bool:
    if not isinstance(text, str):
        return True
    s = text.strip().lower()
    if not s or len(s) < 3:
        return True
    return any(pat in s for pat in _VAGUE_ENTITY_PATTERNS)


def _strip_vague(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        t = item.strip()
        if not t or _is_vague_asset_label(t):
            continue
        out.append(t)
    return out


def normalize_low_information(event: dict) -> dict:
    """Coerce ``event`` (in place) to the canonical low-information
    shape.  Safe to call repeatedly — idempotent.

    Returns the same dict for caller chaining.  Non-dict input is
    returned unchanged.
    """
    if not isinstance(event, dict):
        return event
    event["confidence"]           = "low"
    event["minimum_proof_set"]    = []
    event["key_falsifiers"]       = []
    event["critical_breakpoints"] = []
    # Re-filter narrative asset lists so upstream sanitation can't
    # leave vague filler in on a low-info row.  Ticker lists stay as
    # the analysis emitted them — when the gate fires because there's
    # no concrete asset at all, they're already empty; when it fires
    # because the mechanism is filler, the tickers might still be
    # legitimate and shouldn't be erased.
    for key in ("beneficiaries", "losers", "assets_to_watch"):
        event[key] = _strip_vague(event.get(key))
    return event


# ---------------------------------------------------------------------------
# Evidence-quality tier — three-state internal classification
# ---------------------------------------------------------------------------
# A real analysis falls on a small ladder:
#
#   * ``actionable``      — valid mechanism, committed primary_thesis,
#                           a concrete asset rationale on at least one
#                           primary asset, AND ≥1 proof or falsifier
#                           item.  Safe to ship as a confident call.
#   * ``watch_only``      — mechanism is real (passes the 5-prong gate
#                           and asset prong) but the study is missing
#                           proof/falsifier coverage, the primary
#                           thesis, or a concrete asset rationale.
#                           Useful as a heads-up but cannot carry the
#                           confidence weight of a full call.
#   * ``low_information`` — the existing low-info gate fires.  Weak
#                           mechanism, no tickerable asset, vague
#                           prose, or a self-contradicting primary
#                           thesis.  Coerced to the canonical empty
#                           low-info shape elsewhere in the pipeline.
#
# Pure read.  No I/O.  Returns a string token from the closed set.
# Used internally to keep ``watch_only`` outputs from shipping at
# ``high`` confidence and to keep ``low_information`` outputs from
# generating proof or asset plans they don't earn.

EVIDENCE_QUALITY_TIERS: tuple[str, ...] = (
    "actionable",
    "watch_only",
    "low_information",
)


def _has_committed_primary_thesis(event: dict) -> bool:
    """True when ``competing_thesis.primary_thesis`` is a non-empty
    string and the mechanism's content tokens overlap (already enforced
    upstream by ``primary_thesis_inconsistent``)."""
    ct = event.get("competing_thesis")
    if not isinstance(ct, dict):
        return False
    pt = ct.get("primary_thesis")
    return isinstance(pt, str) and bool(pt.strip())


def _has_concrete_asset_rationale(event: dict) -> bool:
    """True when at least one ``primary_assets`` entry carries a
    non-empty rationale string.  Vague rationales are filtered upstream
    by ``_clean_ranked_asset_list`` so a non-empty rationale here
    has already cleared the generic-filler check."""
    bucket = event.get("primary_assets")
    if not isinstance(bucket, list):
        return False
    for entry in bucket:
        if not isinstance(entry, dict):
            continue
        rat = entry.get("rationale")
        if isinstance(rat, str) and rat.strip():
            return True
    return False


def _has_any_proof_or_falsifier(event: dict) -> bool:
    """True when ``minimum_proof_set`` OR ``key_falsifiers`` carries
    at least one non-empty item.  Either side is enough — actionable
    just needs at least one verifiable claim."""
    for key in ("minimum_proof_set", "key_falsifiers"):
        items = event.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and any(item.get(k) for k in (
                "observation", "signal", "trigger_condition",
            )):
                return True
            if isinstance(item, str) and item.strip():
                return True
    return False


# ---------------------------------------------------------------------------
# Cross-field consistency — thesis vs mechanism vs assets vs proofs
# ---------------------------------------------------------------------------
# A real analysis is a single causal read.  The primary thesis, the
# mechanism narrative (mechanism_family + transmission_path),
# beneficiaries / losers, asset rationales, and proof / falsifier
# items must all describe the same shock.  The contract-tightening
# upstream catches narrow violations; this layer is the cross-field
# audit that drops items still surviving inside an otherwise valid
# shape.
#
# All filtering is in-place mutation.  Callers that want a read-only
# pass should call ``evaluate_consistency`` instead.
#
# Pure composer.  No I/O.  Never raises.

# Threshold above which the share of items dropped in this pass is
# treated as a structural collapse — too much of the analysis was
# off-thesis for any of it to be trusted, so the event is coerced to
# the canonical low-information shape.
_INCONSISTENCY_COLLAPSE_RATE: float = 0.6


def _stem(token: str) -> str:
    """Cheap morphology — collapse plural / -ing / -ed forms so a
    proof item that says 'Saudis' still aligns with a thesis that
    says 'Saudi'.  Not linguistically rigorous; just enough to keep
    surface-form drift from breaking the overlap check."""
    if not token:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("es") and len(token) > 5 and token[-3] not in "aeiou":
        return token[:-2]
    if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
        return token[:-1]
    return token


def _stemmed_tokens(text: Any, *, min_len: int = 4) -> set[str]:
    """Stemmed content-token set, used by the consistency audit so
    'Saudis walks back' matches a thesis token of 'saudi' /
    'walking'."""
    return {_stem(t) for t in _content_tokens(text, min_len=min_len)}


def _thesis_keyword_set(event: dict) -> set[str]:
    """Build the content-token set that defines the primary causal read.

    Pulled from the fields the LLM uses to commit to a thesis:
    ``competing_thesis.primary_thesis``, ``mechanism_summary``,
    ``what_changed``, named actors in transmission_path /
    beneficiaries / losers, and the ``mechanism_family`` token (with
    underscores split so 'supply_normalization' contributes 'supply'
    and 'normalization').  Tickers in the committed buckets are
    lowercased and added so a rationale that just names the symbol
    counts as aligned.
    """
    if not isinstance(event, dict):
        return set()
    parts: list[str] = []
    ct = event.get("competing_thesis")
    if isinstance(ct, dict):
        pt = ct.get("primary_thesis")
        if isinstance(pt, str):
            parts.append(pt)
    for key in ("mechanism_summary", "what_changed"):
        v = event.get(key)
        if isinstance(v, str):
            parts.append(v)
    parts.append(_flatten_actor_text(event))
    fam = event.get("mechanism_family")
    if isinstance(fam, str):
        parts.append(fam.replace("_", " "))

    tokens = _stemmed_tokens(" ".join(parts), min_len=4)

    # Tickers act like proper nouns for alignment — add them at any
    # length so two-letter symbols still count.
    for key in ("beneficiary_tickers", "loser_tickers", "assets_to_watch"):
        seq = event.get(key)
        if isinstance(seq, list):
            for sym in seq:
                if isinstance(sym, str) and sym.strip():
                    tokens.add(sym.strip().lower())
    return tokens


def _entry_aligned_with_thesis(
    text: Any, thesis_kws: set[str], *, min_overlap: int = 1,
) -> bool:
    """True when ``text`` shares at least ``min_overlap`` content tokens
    with the thesis-keyword set.  Both sides are stemmed (cheap
    plural / -ing / -ed normalization) so surface-form drift between
    'Saudis walks back' and 'Saudi walking' doesn't break the match.
    Short uppercase tokens (1-5 letters) are also harvested as
    candidate tickers — 'TSM' / 'SU' / 'BP' won't survive the >=4
    content-word filter otherwise but they are load-bearing for
    proof / falsifier alignment.  Empty / non-string text is treated
    as not aligned."""
    if not isinstance(text, str) or not text.strip() or not thesis_kws:
        return False
    tokens = _stemmed_tokens(text, min_len=4)
    for raw in re.findall(r"[A-Z]{1,5}", text):
        tokens.add(raw.lower())
    if not tokens:
        return False
    return len(tokens & thesis_kws) >= min_overlap


def _filter_ranked_assets(
    bucket: Any, thesis_kws: set[str],
) -> tuple[list[dict], int, int]:
    """Drop ranked asset entries whose symbol AND rationale fail the
    thesis-overlap check.

    Returns ``(kept_entries, checked_count, dropped_count)``.  The
    bucket is treated as already-sanitized; non-dict entries are
    skipped and counted as neither kept nor dropped.
    """
    if not isinstance(bucket, list):
        return [], 0, 0
    kept: list[dict] = []
    checked = 0
    dropped = 0
    for entry in bucket:
        if not isinstance(entry, dict):
            continue
        checked += 1
        sym = (entry.get("symbol") or "").strip().lower()
        rat = entry.get("rationale") or ""
        if sym and sym in thesis_kws:
            kept.append(entry)
            continue
        if _entry_aligned_with_thesis(rat, thesis_kws):
            kept.append(entry)
            continue
        dropped += 1
    return kept, checked, dropped


def _filter_proof_items(
    items: Any, thesis_kws: set[str],
) -> tuple[list, int, int]:
    """Drop proof / falsifier entries whose text shares no content
    token with the thesis-keyword set.

    Accepts both the structured shape (dict with observation /
    signal / trigger_condition / threshold keys) and flat strings.
    """
    if not isinstance(items, list):
        return [], 0, 0
    kept: list = []
    checked = 0
    dropped = 0
    for item in items:
        if isinstance(item, dict):
            text = " ".join(
                str(item.get(k) or "")
                for k in ("observation", "signal", "trigger_condition", "threshold")
            )
        elif isinstance(item, str):
            text = item
        else:
            continue
        checked += 1
        if _entry_aligned_with_thesis(text, thesis_kws):
            kept.append(item)
        else:
            dropped += 1
    return kept, checked, dropped


def evaluate_consistency(event: Any) -> dict[str, Any]:
    """Read-only pass — return the same audit ``enforce_thesis_consistency``
    would run, but without mutating the event.

    Returned dict carries:
      * ``checked``       — total items inspected
      * ``dropped``       — total items the audit would drop
      * ``rate``          — dropped / checked (0.0 when nothing checked)
      * ``downgrade``     — None | "watch_only" | "low_information"
      * ``per_field``     — dict of ``{field_name: {checked, dropped}}``
    """
    empty = {
        "checked": 0, "dropped": 0, "rate": 0.0,
        "downgrade": None, "per_field": {},
    }
    if not isinstance(event, dict):
        return empty
    thesis_kws = _thesis_keyword_set(event)
    if not thesis_kws:
        return empty

    per_field: dict[str, dict[str, int]] = {}
    total_checked = 0
    total_dropped = 0

    # Asset buckets — hedge/signal is exempt (those are non-thesis
    # exposures by construction; their job is to hedge or confirm via
    # macro proxies, not to align with the named mechanism).
    for key in ("primary_assets", "secondary_assets"):
        bucket = event.get(key)
        if not isinstance(bucket, list) or not bucket:
            continue
        _, checked, dropped = _filter_ranked_assets(bucket, thesis_kws)
        if checked:
            per_field[key] = {"checked": checked, "dropped": dropped}
            total_checked += checked
            total_dropped += dropped

    # Proof / falsifier / breakpoint lists — items must test the
    # primary thesis, not a different read.
    for key in ("minimum_proof_set", "key_falsifiers", "critical_breakpoints"):
        items = event.get(key)
        if not isinstance(items, list) or not items:
            continue
        _, checked, dropped = _filter_proof_items(items, thesis_kws)
        if checked:
            per_field[key] = {"checked": checked, "dropped": dropped}
            total_checked += checked
            total_dropped += dropped

    rate = (total_dropped / total_checked) if total_checked else 0.0
    downgrade: str | None = None
    if rate >= _INCONSISTENCY_COLLAPSE_RATE:
        downgrade = "low_information"
    else:
        primary_kept_count = (
            per_field.get("primary_assets", {}).get("checked", 0)
            - per_field.get("primary_assets", {}).get("dropped", 0)
        )
        # Watch-only when the thesis lost its primary-asset coverage to
        # filtering even though the rest of the analysis survives.
        primary_assets = event.get("primary_assets") or []
        if isinstance(primary_assets, list) and primary_assets and primary_kept_count == 0:
            downgrade = "watch_only"

    return {
        "checked": total_checked,
        "dropped": total_dropped,
        "rate": round(rate, 3),
        "downgrade": downgrade,
        "per_field": per_field,
    }


def enforce_thesis_consistency(event: dict) -> dict[str, Any]:
    """Mutating audit — drop off-thesis items in place and return the
    same audit summary ``evaluate_consistency`` produces.

    Callers should run this AFTER the other sanitizers have committed
    the schema and BEFORE ``apply_low_information_gate`` so the gate
    sees the post-filter shape.  Output keys stay stable: only items
    inside existing list fields are dropped.

    When the audit reports a ``downgrade`` of ``"low_information"``,
    callers should follow up with ``normalize_low_information`` to
    coerce the canonical empty shape; ``"watch_only"`` is advisory
    (the existing ``evidence_quality_tier`` already reads watch_only
    when ``primary_assets`` is empty).
    """
    if not isinstance(event, dict):
        return {
            "checked": 0, "dropped": 0, "rate": 0.0,
            "downgrade": None, "per_field": {},
        }
    thesis_kws = _thesis_keyword_set(event)
    if not thesis_kws:
        return {
            "checked": 0, "dropped": 0, "rate": 0.0,
            "downgrade": None, "per_field": {},
        }

    per_field: dict[str, dict[str, int]] = {}
    total_checked = 0
    total_dropped = 0

    for key in ("primary_assets", "secondary_assets"):
        bucket = event.get(key)
        if not isinstance(bucket, list) or not bucket:
            continue
        kept, checked, dropped = _filter_ranked_assets(bucket, thesis_kws)
        if checked:
            per_field[key] = {"checked": checked, "dropped": dropped}
            total_checked += checked
            total_dropped += dropped
            event[key] = kept

    for key in ("minimum_proof_set", "key_falsifiers", "critical_breakpoints"):
        items = event.get(key)
        if not isinstance(items, list) or not items:
            continue
        kept, checked, dropped = _filter_proof_items(items, thesis_kws)
        if checked:
            per_field[key] = {"checked": checked, "dropped": dropped}
            total_checked += checked
            total_dropped += dropped
            event[key] = kept

    rate = (total_dropped / total_checked) if total_checked else 0.0
    downgrade: str | None = None
    if rate >= _INCONSISTENCY_COLLAPSE_RATE:
        downgrade = "low_information"
    else:
        primary_assets = event.get("primary_assets") or []
        if isinstance(primary_assets, list) and not primary_assets:
            # Watch_only fires only when primary_assets is empty AFTER
            # filtering — pre-empty buckets are a separate diagnosis.
            primary_field = per_field.get("primary_assets")
            if primary_field and primary_field["checked"]:
                downgrade = "watch_only"

    return {
        "checked": total_checked,
        "dropped": total_dropped,
        "rate": round(rate, 3),
        "downgrade": downgrade,
        "per_field": per_field,
    }


# ---------------------------------------------------------------------------
# Counterforce / blocker discipline
# ---------------------------------------------------------------------------
# A real analysis names the forces that weaken its thesis (counterforces)
# AND the forces that can interrupt its transmission chain (blockers,
# carried as ``kind=blocker`` entries in the same ``counterforces``
# list).  Both must be concrete; both should map to at least one proof /
# falsifier item when they are high-likelihood.  When a high-likelihood
# blocker has no proof / falsifier coverage at all, the thesis is
# effectively untestable in market terms — the discipline gate flips
# the study to ``watch_only`` (or ``low_information`` when nothing is
# testable at all).
#
# Pure read.  No I/O.  Never raises.

_HIGH_RISK_LIKELIHOODS: frozenset[str] = frozenset({"high"})


def _force_text(entry: Any) -> str:
    """Return the searchable text from a counterforce / blocker entry."""
    if not isinstance(entry, dict):
        return ""
    return " ".join(
        str(entry.get(k) or "")
        for k in ("force", "actor", "chain_hop")
    )


def _force_is_blocker(entry: dict) -> bool:
    """True when the counterforce entry is tagged ``kind=blocker``.
    Defaults to False (treats unspecified kind as counterforce)."""
    return isinstance(entry, dict) and entry.get("kind") == "blocker"


def _force_is_high_risk(entry: dict) -> bool:
    """True for counterforce / blocker entries with high likelihood —
    these are the ones the proof / falsifier set MUST cover."""
    if not isinstance(entry, dict):
        return False
    return entry.get("likelihood") in _HIGH_RISK_LIKELIHOODS


def _proof_set_text_blob(event: dict) -> str:
    """Concatenate every proof / falsifier observation into a single
    searchable blob — used by the discipline gate to ask 'does ANY
    proof item address this counterforce / blocker?'."""
    parts: list[str] = []
    for key in ("minimum_proof_set", "key_falsifiers", "critical_breakpoints"):
        items = event.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                parts.extend(
                    str(item.get(k) or "")
                    for k in ("observation", "signal", "trigger_condition", "threshold")
                )
            elif isinstance(item, str):
                parts.append(item)
    return " ".join(parts)


def _force_has_proof_coverage(force_entry: dict, event: dict) -> bool:
    """True when at least one proof / falsifier item shares a stemmed
    content token with the counterforce / blocker text.  Mirrors the
    cross-field consistency overlap rule, applied against the union of
    proof / falsifier / critical_breakpoint observations."""
    force = _force_text(force_entry)
    if not force.strip():
        return False
    proof_blob = _proof_set_text_blob(event)
    if not proof_blob.strip():
        return False
    proof_tokens = _stemmed_tokens(proof_blob, min_len=4)
    for raw in re.findall(r"[A-Z]{1,5}", proof_blob):
        proof_tokens.add(raw.lower())
    if not proof_tokens:
        return False
    return _entry_aligned_with_thesis(force, proof_tokens)


def evaluate_blocker_discipline(event: Any) -> dict[str, Any]:
    """Audit counterforces / blockers and their proof-set coverage.

    Returns a dict with:
      * ``counterforce_count`` — entries with kind != "blocker"
      * ``blocker_count``      — entries with kind == "blocker"
      * ``high_risk_uncovered`` — list of high-likelihood entries with
        no proof / falsifier coverage
      * ``downgrade``  — None | "watch_only" | "low_information"

    A high-likelihood blocker without proof coverage signals
    ``watch_only`` (the chain can be interrupted at a critical step
    and the desk has nothing to watch).  Multiple uncovered
    high-likelihood blockers AND no proof / falsifier list at all
    signals ``low_information`` (the thesis is effectively
    untestable).  Pure read — does NOT mutate ``event``.
    """
    empty = {
        "counterforce_count": 0,
        "blocker_count": 0,
        "high_risk_uncovered": [],
        "downgrade": None,
    }
    if not isinstance(event, dict):
        return empty
    forces = event.get("counterforces")
    if not isinstance(forces, list) or not forces:
        return empty

    counterforce_count = 0
    blocker_count = 0
    uncovered: list[dict] = []
    for entry in forces:
        if not isinstance(entry, dict):
            continue
        if _force_is_blocker(entry):
            blocker_count += 1
        else:
            counterforce_count += 1
        if _force_is_high_risk(entry) and not _force_has_proof_coverage(entry, event):
            uncovered.append(entry)

    # Downgrade decision.
    downgrade: str | None = None
    proof_blob = _proof_set_text_blob(event).strip()
    high_risk_blockers_uncovered = [
        e for e in uncovered if _force_is_blocker(e)
    ]
    if high_risk_blockers_uncovered and not proof_blob:
        # Multiple uncovered high-risk blockers AND no proof / falsifier
        # set at all → the thesis is structurally untestable.
        if len(high_risk_blockers_uncovered) >= 2:
            downgrade = "low_information"
        else:
            downgrade = "watch_only"
    elif high_risk_blockers_uncovered:
        # Some proof exists but the high-risk blocker isn't covered —
        # watch_only is the right call: the read is real but the
        # specific blocker isn't being tested.
        downgrade = "watch_only"

    return {
        "counterforce_count": counterforce_count,
        "blocker_count":      blocker_count,
        "high_risk_uncovered": uncovered,
        "downgrade":          downgrade,
    }


# ---------------------------------------------------------------------------
# Chain-family consistency — transmission_path channels must match the
# committed mechanism_family
# ---------------------------------------------------------------------------
# Each canonical mechanism family carries a set of TRANSMISSION-MODE
# channels it can plausibly use (see
# ``mechanism_family.FAMILY_TRANSMISSION_CHANNELS``).  A chain whose
# hops mostly fall OUTSIDE the family's set is a structural conflict:
# either the LLM picked the wrong family or articulated the wrong
# cascade.  The audit reads each hop's ``channel`` against the family
# set; the off-family share drives the downgrade tier.
#
# ``"unclassified"`` channels (LLM emitted a token outside the canonical
# 10-channel enum) count as off-family unless the family explicitly
# permits unclassified — none of the canonical families do, so a
# generic hop ("risk sentiment", "broader market reaction", etc.) is
# always a conflict signal except when ``mechanism_family == "none"``.
#
# Pure read.  No I/O.  Never raises.

# Off-family share above which the chain is considered structurally
# conflicting.  Mirrors the consistency-collapse threshold; a mostly-
# off-family chain hides the failing read behind narrative.
_CHAIN_FAMILY_COLLAPSE_RATE: float = 0.6

# Off-family share above which the audit caps the call at watch_only.
# A single off-family hop is tolerated; two or more in a 3-hop chain
# (~0.5+ share) signals the LLM is reaching outside the family.
_CHAIN_FAMILY_WATCH_ONLY_RATE: float = 0.4


def evaluate_chain_family_consistency(event: Any) -> dict[str, Any]:
    """Audit transmission_path channels against the family-allowed set.

    Returns ``{checked, off_family, rate, downgrade, off_family_hops}``.

    Decision flow:
      * no transmission_path / no family / family == "none" → no audit;
        downgrade is None.
      * off_family share >= _CHAIN_FAMILY_COLLAPSE_RATE → ``low_information``.
      * off_family share >= _CHAIN_FAMILY_WATCH_ONLY_RATE → ``watch_only``.
      * lower share → None (chain is family-consistent enough).

    ``off_family_hops`` is the list of hop dicts the audit flagged —
    callers can surface these in validation_warnings.
    Pure read — does NOT mutate ``event``.
    """
    empty = {
        "checked": 0, "off_family": 0, "rate": 0.0,
        "downgrade": None, "off_family_hops": [],
    }
    if not isinstance(event, dict):
        return empty
    family = event.get("mechanism_family")
    path = event.get("transmission_path")
    if not isinstance(path, list) or not path:
        return empty
    if not isinstance(family, str) or not family.strip() or family == "none":
        # No committed family → nothing to compare against.
        return empty

    try:
        from mechanism_family import get_family_transmission_channels
    except Exception:
        return empty
    allowed = get_family_transmission_channels(family)

    checked = 0
    off_family: list[dict] = []
    for hop in path:
        if not isinstance(hop, dict):
            continue
        checked += 1
        ch = hop.get("channel")
        if not isinstance(ch, str):
            off_family.append(hop)
            continue
        c = ch.strip().lower()
        if c == "unclassified" or c not in allowed:
            off_family.append(hop)

    if not checked:
        return empty
    rate = len(off_family) / checked
    downgrade: str | None = None
    if rate >= _CHAIN_FAMILY_COLLAPSE_RATE:
        downgrade = "low_information"
    elif rate >= _CHAIN_FAMILY_WATCH_ONLY_RATE:
        downgrade = "watch_only"

    return {
        "checked": checked,
        "off_family": len(off_family),
        "rate": round(rate, 3),
        "downgrade": downgrade,
        "off_family_hops": off_family,
    }


# ---------------------------------------------------------------------------
# Regime-conditioned caveats — materiality check
# ---------------------------------------------------------------------------
# Caveats live in ``hidden_mechanism.regime_caveats`` (an optional
# list).  Each entry names a regime condition the thesis depends on,
# the effect on the read, and the evidence that would force a
# revisit.  When ANY caveat materially weakens the read — i.e. the
# regime flip would break / blunt / reverse the chain — the analysis
# can't ship as ``actionable``: the call is structurally conditional.
#
# Pure read.  No I/O.  Never raises.

_REGIME_WEAKENING_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\b(weakens?|weakened|weakening)\b", re.I),
    re.compile(r"\b(blunts?|blunted|blunting)\b", re.I),
    re.compile(r"\b(reverses?|reversed|reversing)\b", re.I),
    re.compile(r"\b(stalls?|stalled|stalling)\b", re.I),
    re.compile(r"\b(fades?|fading)\b", re.I),
    re.compile(r"\b(kills?|killed|killing)\s+the\s+thesis\b", re.I),
    re.compile(r"\b(breaks?|broke|broken)\s+the\s+(thesis|chain)\b", re.I),
    re.compile(r"\bthesis\s+(fails?|failed|fails\s+to\s+transmit)\b", re.I),
    re.compile(r"\bdoes\s+not\s+transmit\b", re.I),
    re.compile(r"\bno\s+(transmission|propagation)\b", re.I),
    re.compile(r"\bblocked?\s+at\s+the\b", re.I),
    re.compile(r"\bcompresses\s+the\s+(thesis|read|cascade)\b", re.I),
)


def regime_caveats_weaken_thesis(event: Any) -> bool:
    """True when at least one regime caveat materially weakens the
    thesis — i.e. the named regime flip would break, blunt, reverse,
    or stall the chain.  Read-only; pure pattern check over
    ``hidden_mechanism.regime_caveats[*].effect_on_thesis``.
    """
    if not isinstance(event, dict):
        return False
    hm = event.get("hidden_mechanism")
    if not isinstance(hm, dict):
        return False
    caveats = hm.get("regime_caveats")
    if not isinstance(caveats, list) or not caveats:
        return False
    for entry in caveats:
        if not isinstance(entry, dict):
            continue
        effect = entry.get("effect_on_thesis")
        if not isinstance(effect, str):
            continue
        for pat in _REGIME_WEAKENING_PATTERNS:
            if pat.search(effect):
                return True
    return False


# Positive-vocabulary mirror of :data:`_REGIME_WEAKENING_PATTERNS`.  A
# regime caveat whose ``effect_on_thesis`` matches one of these is
# saying the macro/regime backdrop ALIGNS with the read — the named
# regime flip would amplify, strengthen, or reinforce the chain.
# Used to detect the "macro supports thesis" half of a market-vs-macro
# conflict.
_REGIME_SUPPORTING_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\b(amplifies?|amplified|amplifying)\b", re.I),
    re.compile(r"\b(strengthens?|strengthened|strengthening)\b", re.I),
    re.compile(r"\b(reinforces?|reinforced|reinforcing)\b", re.I),
    re.compile(r"\b(supports?|supported|supporting)\s+the\s+thesis\b", re.I),
    re.compile(r"\b(aligns?|aligned|aligning)\s+with\s+the\s+thesis\b", re.I),
    re.compile(r"\b(confirms?|confirmed|confirming)\s+the\s+thesis\b", re.I),
    re.compile(r"\b(accelerates?|accelerated|accelerating)\s+the\s+(thesis|chain|cascade)\b", re.I),
    re.compile(r"\bbacks?\s+the\s+(thesis|read|call)\b", re.I),
)


def regime_caveats_support_thesis(event: Any) -> bool:
    """True when at least one regime caveat actively supports the
    thesis — i.e. the named regime flip amplifies / strengthens /
    reinforces / aligns with the chain.  Mirror of
    :func:`regime_caveats_weaken_thesis`; pure pattern check over
    ``hidden_mechanism.regime_caveats[*].effect_on_thesis``.
    """
    if not isinstance(event, dict):
        return False
    hm = event.get("hidden_mechanism")
    if not isinstance(hm, dict):
        return False
    caveats = hm.get("regime_caveats")
    if not isinstance(caveats, list) or not caveats:
        return False
    for entry in caveats:
        if not isinstance(entry, dict):
            continue
        effect = entry.get("effect_on_thesis")
        if not isinstance(effect, str):
            continue
        for pat in _REGIME_SUPPORTING_PATTERNS:
            if pat.search(effect):
                return True
    return False


# ---------------------------------------------------------------------------
# Scenario-conditioned proof / falsifier check
# ---------------------------------------------------------------------------
# Scenario conditions live in ``competing_thesis.scenario_conditions``
# (an optional list).  Each entry names a specific condition the
# primary thesis depends on, why the condition matters, and the
# observable evidence to watch.  When ANY scenario condition has no
# proof / falsifier coverage referencing its key tokens, the read is
# structurally conditional in a way the desk can't track — the tier
# system must NOT return ``actionable`` until the condition is
# observable in the proof / falsifier set.
#
# Pure read.  No I/O.  Never raises.


def _scenario_conditions(event: Any) -> list[dict]:
    """Pull the scenario_conditions list from competing_thesis.

    Returns an empty list when the field is absent or the shape is
    unexpected.  Defensive — legacy analyses that never carried the
    structure pass through with no audit fired.
    """
    if not isinstance(event, dict):
        return []
    ct = event.get("competing_thesis")
    if not isinstance(ct, dict):
        return []
    conditions = ct.get("scenario_conditions")
    if not isinstance(conditions, list):
        return []
    return [c for c in conditions if isinstance(c, dict)]


def _scenario_text(condition: dict) -> str:
    """Concatenate the condition / why_it_matters / evidence_to_watch
    text for token-overlap matching against proof / falsifier text."""
    parts: list[str] = []
    for key in ("condition", "why_it_matters", "evidence_to_watch"):
        v = condition.get(key)
        if isinstance(v, str):
            parts.append(v)
    return " ".join(parts)


def evaluate_scenario_observability(event: Any) -> dict[str, Any]:
    """Audit scenario_conditions against proof / falsifier coverage.

    Returns ``{conditions, observed, unobserved, downgrade}``.

    Decision flow:
      * No scenario conditions → no audit; downgrade is None.
      * Each condition is "observed" when at least one proof /
        falsifier / breakpoint item shares stemmed content tokens
        with the condition text.
      * One or more unobserved conditions → ``watch_only`` (the
        thesis is conditional but the desk has nothing to watch for
        the condition's resolution).

    Pure read; does NOT mutate ``event``.
    """
    conditions = _scenario_conditions(event)
    if not conditions:
        return {
            "conditions": 0, "observed": 0,
            "unobserved": [], "downgrade": None,
        }

    proof_blob = _proof_set_text_blob(event)
    proof_tokens = _stemmed_tokens(proof_blob, min_len=4) if proof_blob else set()
    if proof_blob:
        for raw in re.findall(r"[A-Z]{1,5}", proof_blob):
            proof_tokens.add(raw.lower())

    observed_count = 0
    unobserved: list[dict] = []
    for cond in conditions:
        text = _scenario_text(cond)
        if not text.strip():
            unobserved.append(cond)
            continue
        if not proof_tokens:
            unobserved.append(cond)
            continue
        # Require >=2 shared content tokens — a single overlap on a
        # generic preposition / conjunction ("within", "above") would
        # otherwise count as observability and produce false positives.
        if _entry_aligned_with_thesis(
            text, proof_tokens, min_overlap=2,
        ):
            observed_count += 1
        else:
            unobserved.append(cond)

    downgrade: str | None = None
    if unobserved:
        downgrade = "watch_only"

    return {
        "conditions":  len(conditions),
        "observed":    observed_count,
        "unobserved":  unobserved,
        "downgrade":   downgrade,
    }


# ---------------------------------------------------------------------------
# Thesis-timing alignment — proof / falsifier timing must fit the
# windows the thesis_timing block declares
# ---------------------------------------------------------------------------
# When a ``competing_thesis.thesis_timing`` block is present, every
# proof / falsifier / breakpoint item that carries a ``timing`` field
# should land inside the union of the three declared windows
# (expected_reaction_window, follow_through_window, stale_after).
# Items at horizons OUTSIDE that envelope are testing a different
# timing than the thesis itself — the chain has timing dispersion
# that can't ship as actionable.
#
# Pure read; no I/O; never raises.

_TIMING_ALIGNMENT_DOWNGRADE_RATE: float = 0.5


def evaluate_thesis_timing_alignment(event: Any) -> dict[str, Any]:
    """Audit proof / falsifier timing against thesis_timing windows.

    Returns ``{checked, aligned, rate, downgrade}``.  ``checked`` is
    the count of proof / falsifier / breakpoint items with a non-empty
    ``timing`` field; ``aligned`` is the subset whose timing matches
    one of the thesis_timing windows.  ``downgrade`` is ``"watch_only"``
    when the misaligned share is at or above the configured rate; None
    otherwise (including when no timing windows are declared, in which
    case the audit is silent).
    """
    empty = {
        "checked": 0, "aligned": 0, "rate": 0.0, "downgrade": None,
    }
    if not isinstance(event, dict):
        return empty
    ct = event.get("competing_thesis")
    if not isinstance(ct, dict):
        return empty
    timing_block = ct.get("thesis_timing")
    if not isinstance(timing_block, dict):
        return empty

    valid_windows: set[str] = set()
    for key in (
        "expected_reaction_window",
        "follow_through_window",
        "stale_after",
    ):
        v = timing_block.get(key)
        if isinstance(v, str) and v.strip():
            valid_windows.add(v.strip().lower())
    if not valid_windows:
        return empty

    checked = 0
    aligned = 0
    for key in (
        "minimum_proof_set", "key_falsifiers", "critical_breakpoints",
    ):
        items = event.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            t_raw = item.get("timing")
            if not isinstance(t_raw, str):
                continue
            t = t_raw.strip().lower()
            if not t:
                continue
            checked += 1
            if t in valid_windows:
                aligned += 1

    if checked == 0:
        return empty
    misaligned_rate = (checked - aligned) / checked
    downgrade: str | None = None
    if misaligned_rate >= _TIMING_ALIGNMENT_DOWNGRADE_RATE:
        downgrade = "watch_only"
    return {
        "checked":   checked,
        "aligned":   aligned,
        "rate":      round(misaligned_rate, 3),
        "downgrade": downgrade,
    }


# ---------------------------------------------------------------------------
# Source-quality discipline — derived from hidden_mechanism.source_quality
# ---------------------------------------------------------------------------
# A low-specificity headline (rumor, anonymous sourcing, "considering")
# cannot become an actionable read regardless of the rest of the
# analysis — the underlying evidence is too thin for a confident call.
# The tier classifier reads ``hidden_mechanism.source_quality.specificity``
# and caps the read at watch_only when it's "low".


def source_specificity(event: Any) -> str | None:
    """Return the source_quality.specificity token for ``event`` (or
    None when the field is absent).  Read-only; does not mutate."""
    if not isinstance(event, dict):
        return None
    hm = event.get("hidden_mechanism")
    if not isinstance(hm, dict):
        return None
    sq = hm.get("source_quality")
    if not isinstance(sq, dict):
        return None
    spec = sq.get("specificity")
    if isinstance(spec, str) and spec.strip():
        return spec.strip().lower()
    return None


def source_quality_blocks_actionable(event: Any) -> bool:
    """True when ``hidden_mechanism.source_quality.specificity`` is
    "low" — a low-specificity headline can't carry an actionable
    call, so the tier classifier caps at watch_only."""
    return source_specificity(event) == "low"


def evidence_quality_tier(event: Any) -> str:
    """Classify ``event`` into the internal evidence-quality tier.

    Returns one of ``EVIDENCE_QUALITY_TIERS``.  Pure read — does NOT
    mutate ``event``.  Non-dict input collapses to ``low_information``.

    Decision flow:
      * existing low-info gate fires → ``low_information``
      * causal_strength score < 5    → ``watch_only`` (chain has at
                                        least one missing prong; cap
                                        the call regardless of proof
                                        coverage)
      * regime caveats materially
        weaken the thesis            → ``watch_only`` (call is
                                        structurally conditional on
                                        a regime flip the desk has to
                                        watch for)
      * existing 3-prong actionable
        check passes                 → ``actionable``
      * otherwise                    → ``watch_only``
    """
    if not isinstance(event, dict):
        return "low_information"

    # Honor finalize-time coercion markers.  The blended-mechanism, cross-
    # field consistency, blocker-discipline, and off-family chain gates
    # call ``normalize_low_information`` and stamp a
    # "...coerced to low-information" warning, but they don't always
    # mutate the raw mechanism prose, so a fresh ``evaluate_low_information``
    # read can miss the downgrade and the tier slips back to ``watch_only``.
    warnings = event.get("validation_warnings")
    if isinstance(warnings, list) and any(
        isinstance(w, str) and "coerced to low-information" in w
        for w in warnings
    ):
        return "low_information"

    if evaluate_low_information(event)["is_low_info"]:
        return "low_information"

    strength = compute_causal_strength(event)
    if strength["score"] < strength["max_score"]:
        return "watch_only"

    if regime_caveats_weaken_thesis(event):
        return "watch_only"

    if source_quality_blocks_actionable(event):
        # Low-specificity headline — rumor / anonymous source /
        # "considering" — caps at watch_only regardless of how clean
        # the rest of the structure looks.
        return "watch_only"

    timing_alignment = evaluate_thesis_timing_alignment(event)
    if timing_alignment["downgrade"] == "watch_only":
        # Proof / falsifier timing dispersion — items are landing
        # outside the windows the thesis declared, which means the
        # chain isn't testing the thesis it claims to test.
        return "watch_only"

    scenario = evaluate_scenario_observability(event)
    if scenario["downgrade"] == "watch_only":
        # Thesis is conditional and at least one scenario condition is
        # not observable in the proof / falsifier set — the desk
        # can't track when the condition resolves, so the read can't
        # ship as actionable.
        return "watch_only"

    chain_family = evaluate_chain_family_consistency(event)
    if chain_family["downgrade"] in ("watch_only", "low_information"):
        # The finalize-time wiring already coerces to low-information
        # when the share crosses the collapse threshold; here we just
        # cap the read at watch_only when any off-family conflict
        # remains visible at tier-evaluation time.
        return "watch_only"

    if (
        _has_committed_primary_thesis(event)
        and _has_concrete_asset_rationale(event)
        and _has_any_proof_or_falsifier(event)
    ):
        return "actionable"

    return "watch_only"


# ---------------------------------------------------------------------------
# Quality-warning tag generator — short machine-readable strings
# ---------------------------------------------------------------------------
# When an event lands in ``watch_only`` or ``low_information`` the desk
# wants a compact, audit-friendly read of *why* the call was capped.
# These tags are short, fixed tokens — no prose essays — so the UI can
# branch on them and the saved event has a stable, comparable record.
# Empty list on ``actionable`` outputs.

QUALITY_WARNING_TAGS: tuple[str, ...] = (
    "weak_mechanism",            # 5-prong mechanism gate failed / vague phrasing
    "missing_asset_rationale",   # primary_assets has no rationale
    "invalid_chain",             # transmission_path provided but invalid
    "no_observable_condition",   # no minimum_proof_set AND no key_falsifiers
    "inconsistent_proof",        # primary_thesis disagrees with mechanism actors
    "broad_beta_only",           # weighted_evidence supportive but no primary supporter
)


def _has_no_observable_condition(event: dict) -> bool:
    """True when neither minimum_proof_set nor key_falsifiers carries
    a non-empty item — the thesis carries no testable claim."""
    return not _has_any_proof_or_falsifier(event)


def _has_invalid_transmission_chain(event: dict) -> bool:
    """True when transmission_path was provided but doesn't pass the
    structural validator.  Empty / absent paths don't fire this
    warning — they're captured by the chain prong of the
    mechanism-quality gate."""
    path = event.get("transmission_path")
    if not isinstance(path, list) or not path:
        return False
    try:
        from analyze_event import _is_valid_transmission_chain
    except Exception:
        return False
    return not _is_valid_transmission_chain(path)


def _has_broad_beta_only(event: dict) -> bool:
    """True when the weighted-evidence aggregate would have cleared
    the supportive band but no primary single-name supports the
    thesis — the read is broad-beta tape-following.  Mirrors the
    downgrade rule in ``score_weighted_evidence``.

    Threads ``explicit_primary`` from the event's ``primary_assets``
    block so unknown / unmapped alpha tickers cannot silently inherit
    the legacy "alpha-only → primary" heuristic and mask a real
    broad-beta read.  When the event has no ``primary_assets`` field
    at all (legacy row), the call falls back to the tightened
    heuristic in ``_eligibility_tier``.
    """
    tickers = event.get("market_tickers")
    if not isinstance(tickers, list) or not tickers:
        return False
    try:
        from validation_outcome import (
            _EVT_SUPPORTIVE, _extract_primary_set, _ticker_contribution,
        )
    except Exception:
        return False

    explicit_primary = _extract_primary_set(event)
    scored: list[dict] = []
    for t in tickers:
        if not isinstance(t, dict):
            continue
        row = _ticker_contribution(t, explicit_primary=explicit_primary)
        if row is not None:
            scored.append(row)
    if not scored:
        return False

    aggregate_weight = sum(r.get("weight") or 0 for r in scored)
    if aggregate_weight <= 0:
        return False
    score = sum(r.get("contribution") or 0 for r in scored) / aggregate_weight
    if score < _EVT_SUPPORTIVE:
        return False
    primary_supports = any(
        r.get("eligibility_tier") == "primary"
        and (r.get("contribution") or 0) > 0
        for r in scored
    )
    return not primary_supports


def quality_warnings(event: Any) -> list[str]:
    """Return short machine-readable warning tags for ``event``.

    Tags are drawn from the closed ``QUALITY_WARNING_TAGS`` vocabulary
    and emitted in fixed order so consumers branching on the list see
    a stable read.  Empty list on actionable outputs and on non-dict
    input.  Pure read — never mutates the event.
    """
    if not isinstance(event, dict):
        return []
    tier = evidence_quality_tier(event)
    if tier == "actionable":
        return []

    out: list[str] = []
    seen: set[str] = set()

    def _add(tag: str) -> None:
        if tag in QUALITY_WARNING_TAGS and tag not in seen:
            seen.add(tag)
            out.append(tag)

    # weak_mechanism — five-prong gate failed / vague phrasing.
    quality = evaluate_mechanism_quality(event)
    if not quality.get("is_valid"):
        _add("weak_mechanism")

    # missing_asset_rationale — primary_assets bucket has no
    # rationale.  A direct-name pick without a rationale is
    # tape-following, not a thesis read.
    if not _has_concrete_asset_rationale(event):
        _add("missing_asset_rationale")

    # invalid_chain — transmission_path provided but failed validation.
    if _has_invalid_transmission_chain(event):
        _add("invalid_chain")

    # no_observable_condition — no proof set AND no falsifier set.
    if _has_no_observable_condition(event):
        _add("no_observable_condition")

    # inconsistent_proof — primary_thesis tokens disjoint from the
    # mechanism's actors / channels.
    if primary_thesis_inconsistent(event):
        _add("inconsistent_proof")

    # broad_beta_only — supportive aggregate but no primary supporter.
    if _has_broad_beta_only(event):
        _add("broad_beta_only")

    return out


# ---------------------------------------------------------------------------
# Confidence calibration — derived from evidence quality, not LLM prose
# ---------------------------------------------------------------------------
# Confidence is the contract-tightening sequence's terminal output.
# Earlier gates set the tier (low_information / watch_only /
# actionable); this composer maps tier + proof / falsifier coverage
# back to the existing low | medium | high enum so consumers don't
# need to know the internal tier vocabulary.
#
# Rules:
#   * tier == low_information → "low" (the canonical low-info shape
#     already forces confidence to low; calibration agrees so the
#     post-coercion read stays consistent)
#   * tier == watch_only      → "medium" (never "high" — the read is
#     real but the desk has open conditions / proof gaps)
#   * tier == actionable AND  → "high" (passes every gate AND has
#     ≥1 minimum_proof_set entry AND ≥1 key_falsifiers entry — the
#     desk has concrete coverage on both sides of the read)
#   * tier == actionable but  → "medium" (clean structure but the
#     proof / falsifier coverage is too thin for a high-conviction
#     call)
#
# Pure read — does NOT mutate ``event``.  Returns one of
# ``low | medium | high``; non-dict input collapses to "low".


def calibrate_confidence(event: Any) -> str:
    """Return the calibrated confidence string for ``event``.

    The output drives ``analysis['confidence']`` AFTER the gates run,
    replacing the LLM's prose-derived value with one anchored to the
    structural-evidence quality.  Confidence enum stays stable —
    callers see the same low / medium / high vocabulary.
    """
    if not isinstance(event, dict):
        return "low"

    tier = evidence_quality_tier(event)
    if tier == "low_information":
        return "low"
    if tier == "watch_only":
        return "medium"

    # ``actionable`` — promote to high only when proof AND falsifier
    # coverage both exist.  An actionable read with one-sided coverage
    # (proof but no falsifier, or vice versa) lacks the fast-break
    # invalidator the desk needs to size confidently.
    proof = event.get("minimum_proof_set")
    falsifiers = event.get("key_falsifiers")
    has_proof = isinstance(proof, list) and any(
        bool(item) for item in proof
    )
    has_falsifier = isinstance(falsifiers, list) and any(
        bool(item) for item in falsifiers
    )
    if has_proof and has_falsifier:
        return "high"
    return "medium"


def apply_low_information_gate(event: dict) -> dict[str, Any]:
    """Run the gate and apply normalisation if it fires.

    Returns ``{is_low_info, reason, event}``.  ``event`` is the same
    dict passed in (mutated when the gate fires).  Callers that want
    a non-mutating check can call ``evaluate_low_information`` alone.
    """
    result = evaluate_low_information(event)
    if result["is_low_info"] and isinstance(event, dict):
        normalize_low_information(event)
    return {**result, "event": event}


# ---------------------------------------------------------------------------
# Confidence rationale — short prose tied to the structural signals
# ---------------------------------------------------------------------------
# A 1-2 sentence string that names the concrete factors driving the
# confidence enum.  Pure read.  Returns "" on non-dict input.  Inputs
# are the same signals the tier classifier already computes, so the
# rationale stays consistent with the calibrated confidence value.

# Human-readable labels for the five causal-strength prongs.  Used by
# the rationale composer so output reads as prose ("missing trigger,
# channel") rather than internal slugs.
_PRONG_LABELS: dict[str, str] = {
    "trigger":           "trigger",
    "channel":           "transmission channel",
    "constraint":        "constraint/pricing relationship",
    "actor":             "named actor",
    "market_expression": "tradable market expression",
}


def _format_missing_prongs(components: dict) -> str:
    missing = [
        _PRONG_LABELS.get(k, k) for k, v in components.items() if not v
    ]
    if not missing:
        return ""
    if len(missing) == 1:
        return missing[0]
    if len(missing) == 2:
        return f"{missing[0]} and {missing[1]}"
    return ", ".join(missing[:-1]) + f", and {missing[-1]}"


def compose_confidence_rationale(event: Any) -> str:
    """Return a 1-2 sentence rationale string for the calibrated
    confidence value.

    Reads the same structural signals the tier classifier uses
    (causal_strength prongs, source quality, asset eligibility,
    proof / falsifier coverage, regime caveats, quality_warnings).
    Pure read — does NOT mutate ``event``.  Empty string on
    non-dict input.
    """
    if not isinstance(event, dict):
        return ""

    conf = calibrate_confidence(event)

    # Low — name the dominant missing input.  Drives off the
    # low-information gate's reason code so the rationale always
    # points at the prong the desk would need to fix.
    if conf == "low":
        gate = evaluate_low_information(event)
        reason = gate.get("reason") or ""
        if reason == "filler_mechanism":
            return (
                "Confidence low: mechanism narrative is filler or "
                "too thin to support a real causal read."
            )
        if reason == "no_concrete_asset":
            return (
                "Confidence low: no concrete tickerable asset named "
                "in any bucket — the call has no market expression."
            )
        if reason == "invalid_transmission_chain":
            return (
                "Confidence low: transmission_path provided but "
                "failed structural validation (vague hops or missing "
                "actor/channel/effect)."
            )
        if reason == "primary_thesis_inconsistent":
            return (
                "Confidence low: primary_thesis names actors the "
                "mechanism narrative never reaches."
            )
        if reason == "weak_mechanism":
            quality = evaluate_mechanism_quality(event)
            if quality.get("vague"):
                return (
                    "Confidence low: mechanism prose hits a vague-"
                    "placeholder pattern (\"markets price risk\"-"
                    "type filler)."
                )
            strength = compute_causal_strength(event)
            missing_label = _format_missing_prongs(
                strength.get("components") or {}
            )
            if missing_label:
                return (
                    f"Confidence low: causal chain only "
                    f"{int(strength['score'])}/5 prongs satisfied "
                    f"(missing {missing_label})."
                )
            return (
                "Confidence low: mechanism failed the five-prong "
                "structural gate."
            )
        return (
            "Confidence low: insufficient structural evidence to "
            "support a real read."
        )

    # Medium — name the cap.  Pull the strongest visible reason the
    # tier didn't promote to actionable / proof+falsifier coverage
    # didn't earn high.
    if conf == "medium":
        bits: list[str] = []
        strength = compute_causal_strength(event)
        if strength["score"] < strength["max_score"]:
            missing_label = _format_missing_prongs(
                strength.get("components") or {}
            )
            if missing_label:
                bits.append(
                    f"causal chain {int(strength['score'])}/5 "
                    f"(missing {missing_label})"
                )
        if regime_caveats_weaken_thesis(event):
            bits.append("regime caveats weaken the thesis")
        if source_quality_blocks_actionable(event):
            bits.append("low-specificity source")
        proof = event.get("minimum_proof_set") or []
        fals = event.get("key_falsifiers") or []
        has_proof = isinstance(proof, list) and any(bool(x) for x in proof)
        has_fals = isinstance(fals, list) and any(bool(x) for x in fals)
        if strength["score"] >= strength["max_score"]:
            if has_proof and not has_fals:
                bits.append("falsifier set empty")
            elif has_fals and not has_proof:
                bits.append("proof set empty")
            elif not has_proof and not has_fals:
                bits.append("no proof or falsifier coverage")
        warnings = quality_warnings(event)
        if "missing_asset_rationale" in warnings:
            bits.append("primary asset has no rationale")
        if "broad_beta_only" in warnings and "broad-beta only" not in bits:
            bits.append("broad-beta only — no primary single-name supporter")
        if "inconsistent_proof" in warnings:
            bits.append("primary_thesis disagrees with mechanism actors")
        if not bits:
            bits.append(
                "structure clean but proof/falsifier coverage too "
                "thin for a high-conviction call"
            )
        return "Confidence medium: " + "; ".join(bits[:2]) + "."

    # High — actionable tier with both proof and falsifier coverage.
    # quality_warnings() returns [] for actionable tier so we don't
    # need a defensive warning check here.
    return (
        "Confidence high: actionable tier with all five causal "
        "prongs, concrete asset rationale, and both proof and "
        "falsifier sets populated."
    )


# ---------------------------------------------------------------------------
# Counterfactual check — explicit "what would break the thesis" block
# ---------------------------------------------------------------------------
# Composes the optional ``counterfactual_check`` field from existing
# falsifier evidence.  Linked to the canonical falsifier set by
# reusing exact strings, so consumers can match an evidence_to_watch
# entry back to ``key_falsifiers`` / ``hidden_mechanism.critical_breakpoints``
# without an extra ID column.  Pure read.

# Maximum number of evidence_to_watch items to surface.  Keeps the
# block compact while preserving the strongest 1-3 falsifiers.
_MAX_COUNTERFACTUAL_EVIDENCE: int = 3

# Minimum length for a critical_breakpoints observation to count as a
# concrete counterfactual fallback.  Mirrors the key_falsifiers cleaner
# in analyze_event so we don't surface filler when only the structured
# block is populated.
_MIN_COUNTERFACTUAL_TEXT_LEN: int = 15


def _counterfactual_evidence_strings(event: dict) -> list[str]:
    """Collect concrete falsifier-like strings from the event.

    Preference order:
      1. ``key_falsifiers`` — already cleaned upstream to ≥15-char
         price-checkable strings.
      2. ``hidden_mechanism.critical_breakpoints[].observation`` (or
         signal / trigger_condition) — falls back when the flat list
         is empty but the structured block carries fast-break items.

    Does NOT walk ``minimum_proof_set`` — that fallback is exposed via
    :func:`_proof_inversion_strings` so the composer can distinguish
    proof-inversion-derived counterfactuals (and label them in the
    why-line) from explicit falsifier / breakpoint commitments.
    """
    out: list[str] = []
    seen: set[str] = set()

    fals = event.get("key_falsifiers")
    if isinstance(fals, list):
        for item in fals:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if len(text) < _MIN_COUNTERFACTUAL_TEXT_LEN:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)

    if out:
        return out

    hm = event.get("hidden_mechanism")
    if isinstance(hm, dict):
        cb = hm.get("critical_breakpoints")
        if isinstance(cb, list):
            for entry in cb:
                if not isinstance(entry, dict):
                    continue
                for key_field in ("observation", "signal", "trigger_condition"):
                    raw = entry.get(key_field)
                    if not isinstance(raw, str):
                        continue
                    text = raw.strip()
                    if len(text) < _MIN_COUNTERFACTUAL_TEXT_LEN:
                        continue
                    key = text.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(text)
                    break
    return out


def _proof_inversion_strings(event: dict) -> list[str]:
    """Derive counterfactual strings by inverting the strongest proof
    items.

    Used as the third-pass fallback when ``key_falsifiers`` and
    ``hidden_mechanism.critical_breakpoints`` are both empty but the
    event still committed to a ``minimum_proof_set``.  Each proof item
    becomes a single string: ``"Expected proof fails to print: <obs>"``.
    Phrasing matches :func:`_first_invalidation_trigger` so the two
    derived blocks share the same proof-inversion language when they
    both fall back here.
    """
    out: list[str] = []
    seen: set[str] = set()
    if not isinstance(event, dict):
        return out
    proof = event.get("minimum_proof_set")
    if not isinstance(proof, list):
        return out
    for entry in proof:
        text = ""
        if isinstance(entry, dict):
            obs = entry.get("observation") or entry.get("signal") \
                or entry.get("trigger_condition")
            if isinstance(obs, str):
                text = obs.strip()
        elif isinstance(entry, str):
            text = entry.strip()
        if not text or len(text) < _MIN_COUNTERFACTUAL_TEXT_LEN:
            continue
        inverted = f"Expected proof fails to print: {text}"
        key = inverted.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(inverted)
    return out


def _has_observable_counterfactual(event: Any) -> bool:
    """True when at least one usable counterfactual string can be
    derived from the event — explicit falsifier, critical breakpoint,
    OR proof-set inversion.  Used by ``compose_actionability_check``
    to gate the actionable verdict: a tier-actionable event with no
    observable counterfactual is demoted to watch_only-without-trigger
    so the desk never ships a tradable read with nothing to monitor
    for invalidation.
    """
    if not isinstance(event, dict):
        return False
    return bool(
        _counterfactual_evidence_strings(event)
        or _proof_inversion_strings(event)
    )


def _counterfactual_anchor(event: dict) -> str:
    """First-sentence anchor used to build why_it_would_break_thesis.

    Pulls from ``competing_thesis.primary_thesis`` first so the why
    line ties to the desk's committed read; falls back to the first
    sentence of ``mechanism_summary``.  Returns "" when neither
    field carries usable prose.
    """
    ct = event.get("competing_thesis")
    if isinstance(ct, dict):
        pt = ct.get("primary_thesis")
        if isinstance(pt, str) and pt.strip():
            return pt.strip()
    ms = event.get("mechanism_summary")
    if isinstance(ms, str) and ms.strip():
        return ms.strip().split(". ")[0].strip().rstrip(".")
    return ""


def compose_counterfactual_check(event: Any) -> dict:
    """Return ``{what_should_not_happen, why_it_would_break_thesis,
    evidence_to_watch}`` for ``event``.

    Pure read.  Returns ``{}`` only on non-dict input — every analyzable
    event gets the same 3-key shape so consumers can read the same keys
    uniformly across tiers.  Low-information outputs and tiers without
    concrete evidence return the shape with an empty
    ``evidence_to_watch`` list and a tier-aware ``why_it_would_break_thesis``
    explanation.

    Source preference: explicit ``key_falsifiers`` and
    ``hidden_mechanism.critical_breakpoints`` first.  When both are
    empty but ``minimum_proof_set`` exists, the strongest proof items
    are inverted ("Expected proof fails to print: ...") so a tradable
    event whose only structural commitment is proof still emits a
    populated counterfactual block — closes the asymmetry with
    ``actionability_check`` which already falls back to the same
    proof-inversion strings via ``_first_invalidation_trigger``.
    """
    if not isinstance(event, dict):
        return {}

    tier = evidence_quality_tier(event)
    if tier == "low_information":
        return {
            "what_should_not_happen":     "",
            "why_it_would_break_thesis":  (
                "low_information: no committed thesis to define a "
                "counterfactual against."
            ),
            "evidence_to_watch":          [],
        }

    evidence = _counterfactual_evidence_strings(event)
    derived_from_proof = False
    if not evidence:
        evidence = _proof_inversion_strings(event)
        derived_from_proof = bool(evidence)

    if not evidence:
        return {
            "what_should_not_happen":     "",
            "why_it_would_break_thesis":  (
                "No concrete falsifier, critical breakpoint, or proof "
                "item named — counterfactual cannot be anchored to an "
                "observable signal."
            ),
            "evidence_to_watch":          [],
        }

    evidence = evidence[:_MAX_COUNTERFACTUAL_EVIDENCE]
    what_should_not_happen = evidence[0]

    anchor = _counterfactual_anchor(event)
    if derived_from_proof:
        # Falsifiers / breakpoints were not separately committed; the
        # counterfactual is the failure of the named proof.  Why-line
        # signals the source so consumers don't read a proof-inversion
        # entry as an analyst-committed falsifier.
        if anchor:
            why = (
                f"Falsifiers were not separately committed; proof "
                f"failing to print would invalidate the committed "
                f"read: {anchor}."
            )
        else:
            why = (
                "Falsifiers were not separately committed; proof "
                "failing to print would invalidate the named "
                "transmission chain."
            )
    elif anchor:
        why = (
            f"Observing this would invalidate the committed read: "
            f"{anchor}."
        )
    else:
        why = (
            "Observing this would invalidate the named transmission "
            "chain — the mechanism predicts the opposite signal."
        )

    return {
        "what_should_not_happen": what_should_not_happen,
        "why_it_would_break_thesis": why,
        "evidence_to_watch": evidence,
    }


# ---------------------------------------------------------------------------
# Actionability check — explicit "is this tradable" structure
# ---------------------------------------------------------------------------
# Composes the optional ``actionability_check`` field with four sub-keys:
# ``tradable`` (bool), ``why_tradable_or_not`` (str),
# ``required_confirmation`` (list[str], drawn from existing proof /
# falsifier text — exact strings preserved for linkage), and
# ``sizing_caveat`` (str).  Pure read.
#
# Tier rules:
#   * low_information → tradable=False, no required_confirmation; the
#     why line names the low-information reason so the desk knows what
#     to fix.
#   * watch_only      → tradable=True ONLY when required_confirmation
#     is non-empty (proof/falsifier set carries a concrete trigger);
#     otherwise tradable=False with a "no observable trigger" reason.
#   * actionable      → tradable=True; required_confirmation names what
#     still needs monitoring (the existing proof+falsifier set).

# Maximum number of confirmation items surfaced.  Mirrors the
# counterfactual_check evidence cap so the two derived blocks share
# the same compactness contract.
_MAX_REQUIRED_CONFIRMATION: int = 3

# Risk-discipline labels emitted by ``actionability_check``.  Closed
# set: low_information and watch_only-without-trigger map to "high"
# (no concrete entry), watch_only-with-trigger maps to "elevated"
# (sizable but conditional), actionable maps to "standard".
_RISK_HIGH:     str = "high"
_RISK_ELEVATED: str = "elevated"
_RISK_STANDARD: str = "standard"

# Confidence ceiling enforced until ``required_confirmation`` prints.
# low_information and watch_only cap at "low" — without a confirmed
# proof or falsifier the read cannot support medium/high confidence.
# actionable unrestricts to "high" so consumers don't have to null-check.
_CONFIDENCE_CEILING_LOW:  str = "low"
_CONFIDENCE_CEILING_FULL: str = "high"

# Map low-information gate reasons to a one-line "why not tradable"
# string.  Keys mirror the closed reason set returned by
# evaluate_low_information.
_LOW_INFO_TRADABLE_REASON: dict[str, str] = {
    "filler_mechanism": (
        "low_information: mechanism narrative is filler / too thin "
        "to support a real read"
    ),
    "no_concrete_asset": (
        "low_information: no concrete tickerable asset — the call "
        "has no market expression to size"
    ),
    "invalid_transmission_chain": (
        "low_information: transmission_path failed structural "
        "validation — the chain is not finance-real"
    ),
    "weak_mechanism": (
        "low_information: mechanism failed the five-prong gate or "
        "hits a vague-placeholder pattern"
    ),
    "primary_thesis_inconsistent": (
        "low_information: primary_thesis disagrees with the "
        "mechanism it claims to read"
    ),
}


def _required_confirmation_strings(event: dict) -> list[str]:
    """Collect concrete confirmation strings from proof + falsifier sets.

    Preserves exact strings so consumers can match a confirmation entry
    back to ``minimum_proof_set[*].observation`` or ``key_falsifiers``.
    Proof items lead the list (they describe what should print to
    confirm the thesis); falsifiers backfill (what should NOT print).
    """
    out: list[str] = []
    seen: set[str] = set()

    for source_key in ("minimum_proof_set", "key_falsifiers"):
        bucket = event.get(source_key)
        if not isinstance(bucket, list):
            continue
        for entry in bucket:
            text = ""
            if isinstance(entry, dict):
                obs = entry.get("observation") or entry.get("signal") \
                    or entry.get("trigger_condition")
                if isinstance(obs, str):
                    text = obs.strip()
            elif isinstance(entry, str):
                text = entry.strip()
            if not text or len(text) < 10:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
            if len(out) >= _MAX_REQUIRED_CONFIRMATION:
                return out
    return out


def _first_invalidation_trigger(event: dict) -> str:
    """Return a single concrete invalidation-trigger string.

    Prefers ``key_falsifiers`` (literal "what would break the thesis").
    Falls back to inverting the leading ``minimum_proof_set`` item
    ("expected proof fails to print") so an actionable event always
    names something concrete the desk can monitor for invalidation.
    """
    fals = event.get("key_falsifiers")
    if isinstance(fals, list):
        for entry in fals:
            text = ""
            if isinstance(entry, dict):
                obs = entry.get("observation") or entry.get("signal") \
                    or entry.get("trigger_condition")
                if isinstance(obs, str):
                    text = obs.strip()
            elif isinstance(entry, str):
                text = entry.strip()
            if text and len(text) >= 10:
                return text
    proof = event.get("minimum_proof_set")
    if isinstance(proof, list):
        for entry in proof:
            text = ""
            if isinstance(entry, dict):
                obs = entry.get("observation") or entry.get("signal") \
                    or entry.get("trigger_condition")
                if isinstance(obs, str):
                    text = obs.strip()
            elif isinstance(entry, str):
                text = entry.strip()
            if text and len(text) >= 10:
                return f"Expected proof fails to print: {text}"
    return ""


def _weak_traceability_caveat(event: Any) -> str:
    """Return a short sizing-caveat suffix when the event's
    ``competing_thesis.evidence_sources`` is weak, else "".

    The block is only composed by ``analyze_event._clean_competing_thesis``
    when the thesis carries auditable evidence lines — absence is
    treated as "not weak" because other rules (mechanism-quality gate,
    proof / falsifier coverage) already cap a thesis with no
    structured evidence.  Pure read; never raises.
    """
    if not isinstance(event, dict):
        return ""
    competing = event.get("competing_thesis") or {}
    if not isinstance(competing, dict):
        return ""
    sources = competing.get("evidence_sources")
    if sources is None:
        return ""
    try:
        from evidence_sources import is_weak_traceability
    except Exception:
        return ""
    if is_weak_traceability(sources):
        return (
            " Source-traceability is weak — half-size at most until "
            "more auditable lines confirm."
        )
    return ""


def compose_actionability_check(event: Any) -> dict:
    """Return ``{tradable, why_tradable_or_not, required_confirmation,
    sizing_caveat, risk_level, max_confidence_before_confirmation,
    invalidation_trigger}`` for ``event``.

    Pure read.  Returns ``{}`` only on non-dict input — every analyzable
    event gets a populated block so consumers can branch on
    ``tradable`` without checking field presence.

    Risk-discipline fields:
      * ``risk_level`` — closed set ``{"high", "elevated", "standard"}``
      * ``max_confidence_before_confirmation`` — ceiling string
        (``"low"`` until confirmation prints; ``"high"`` for actionable)
      * ``invalidation_trigger`` — single concrete string drawn from
        ``key_falsifiers``; non-empty for actionable.
    """
    if not isinstance(event, dict):
        return {}

    tier = evidence_quality_tier(event)

    if tier == "low_information":
        gate = evaluate_low_information(event)
        reason = gate.get("reason") or ""
        why = _LOW_INFO_TRADABLE_REASON.get(
            reason,
            "low_information: insufficient structural evidence to size a position",
        )
        return {
            "tradable":               False,
            "why_tradable_or_not":    why,
            "required_confirmation":  [],
            "sizing_caveat":          "Not sizable — no real read.",
            "risk_level":             _RISK_HIGH,
            "max_confidence_before_confirmation": _CONFIDENCE_CEILING_LOW,
            "invalidation_trigger":   "",
        }

    required = _required_confirmation_strings(event)
    invalidation = _first_invalidation_trigger(event)
    trace_suffix = _weak_traceability_caveat(event)

    if tier == "watch_only":
        if required:
            return {
                "tradable":              True,
                "why_tradable_or_not":   (
                    "watch_only: causal chain is real but the read is "
                    "conditional — sizable only after the listed "
                    "confirmation prints."
                ),
                "required_confirmation": required,
                "sizing_caveat":         (
                    "Half-size at most until confirmation prints; "
                    "full sizing only on confirmed signal."
                    + trace_suffix
                ),
                "risk_level":            _RISK_ELEVATED,
                "max_confidence_before_confirmation": _CONFIDENCE_CEILING_LOW,
                "invalidation_trigger":  invalidation,
            }
        return {
            "tradable":              False,
            "why_tradable_or_not":   (
                "watch_only with no concrete confirmation signal — "
                "no observable trigger to define an entry."
            ),
            "required_confirmation": [],
            "sizing_caveat":         (
                "Not tradable — needs at least one observable proof "
                "or falsifier item to size."
                + trace_suffix
            ),
            "risk_level":            _RISK_HIGH,
            "max_confidence_before_confirmation": _CONFIDENCE_CEILING_LOW,
            "invalidation_trigger":  "",
        }

    # Defensive cap: an actionable tier with no observable
    # counterfactual (no falsifier, no critical breakpoint, no
    # invertible proof item) would let a tradable read ship without
    # any concrete invalidation signal to monitor.  Demote to
    # watch_only-without-trigger so the desk never sizes a position
    # against an unfalsifiable thesis.
    if not _has_observable_counterfactual(event):
        return {
            "tradable":              False,
            "why_tradable_or_not":   (
                "actionable tier classification but no observable "
                "counterfactual — capped to watch_only until at least "
                "one concrete falsifier, breakpoint, or proof item is "
                "named."
            ),
            "required_confirmation": [],
            "sizing_caveat":         (
                "Not tradable — needs at least one observable proof "
                "or falsifier item to size."
                + trace_suffix
            ),
            "risk_level":            _RISK_HIGH,
            "max_confidence_before_confirmation": _CONFIDENCE_CEILING_LOW,
            "invalidation_trigger":  "",
        }

    # actionable — required_confirmation must be non-empty because the
    # tier classifier already required >=1 proof or falsifier item.
    # When traceability is weak, the actionable read still ships but
    # the risk_level steps up to elevated — the desk size must reflect
    # that the auditable lines are thin even though the structural
    # tier passed.
    actionable_risk = _RISK_ELEVATED if trace_suffix else _RISK_STANDARD
    return {
        "tradable":              True,
        "why_tradable_or_not":   (
            "actionable: full causal chain, concrete asset rationale, "
            "and both proof + falsifier coverage."
        ),
        "required_confirmation": required,
        "sizing_caveat":         (
            "Standard sizing; revisit immediately if any listed "
            "falsifier prints."
            + trace_suffix
        ),
        "risk_level":            actionable_risk,
        "max_confidence_before_confirmation": _CONFIDENCE_CEILING_FULL,
        "invalidation_trigger":  invalidation,
    }


# ---------------------------------------------------------------------------
# Tier-aware deterministic proof / falsifier generators
# ---------------------------------------------------------------------------
# These wrap the family-level fallback generators in
# ``mechanism_family`` (``proof_set_for_family`` /
# ``falsifier_set_for_family``) and apply two extra disciplines:
#
#   1. **Tier gating.**  ``actionable`` chains get the full deterministic
#      set; ``watch_only`` chains get at most a couple of watch-prefixed
#      items so the UI can't read them as a confident proof claim;
#      ``low_information`` chains return the stable empty shape.
#   2. **Channel mapping.**  Generated items must land on the chain's
#      named transmission channel (``transmission_path[*].channel`` ∪
#      ``expected_first_order_channels``).  Items targeting an off-chain
#      channel are dropped — we don't manufacture a proof on a channel
#      the analyst hasn't named.
#
# Item shape is identical to the family-level generators so consumers
# already wired against ``proof_set_for_family`` see the same dict keys.

# Cap on items emitted for the watch_only tier — small enough that the
# desk reads them as "watch checks", not as a full proof set.
_WATCH_ONLY_PROOF_CAP:     int = 2
_WATCH_ONLY_FALSIFIER_CAP: int = 2

# Prefix tag stamped onto the watch_only ``why_it_matters`` /
# ``why_it_breaks_thesis`` strings so a consumer rendering the items
# never reads them as a definitive proof / falsifier label.
_WATCH_ONLY_PREFIX: str = "Watch: "


def _named_transmission_channels(event: Any) -> set[str]:
    """Return the set of macro channels named on the event's
    transmission chain — ``transmission_path[*].channel`` plus the
    ``expected_first_order_channels`` pack.  Empty set means no channel
    was committed; the tier-aware generators treat that as "skip the
    channel filter" so a thin event with no committed chain still
    surfaces something to watch.
    """
    out: set[str] = set()
    if not isinstance(event, dict):
        return out
    path = event.get("transmission_path")
    if isinstance(path, list):
        for hop in path:
            if not isinstance(hop, dict):
                continue
            ch = hop.get("channel")
            if isinstance(ch, str) and ch and ch != "unclassified":
                out.add(ch)
    first_pack = event.get("expected_first_order_channels")
    if isinstance(first_pack, list):
        for ch in first_pack:
            if isinstance(ch, str) and ch.strip():
                out.add(ch)
    return out


def _filter_items_to_channels(
    items: list[dict], channels: set[str],
) -> list[dict]:
    """Keep only items whose ``channel`` is in ``channels``.  When the
    set is empty (no committed chain), pass through unchanged so a
    pre-tier-aware caller doesn't get an unexpectedly empty list."""
    if not channels:
        return list(items)
    return [
        i for i in items
        if isinstance(i, dict) and i.get("channel") in channels
    ]


def _asset_channels_by_tier(event: dict) -> tuple[set[str], set[str], set[str]]:
    """Return the channels covered by ``primary_assets`` /
    ``secondary_assets`` / ``hedge_or_signal_assets`` on the event,
    routed via ``asset_selection._ticker_channel``.  Used to order
    proof and falsifier items so items landing on primary-asset
    channels surface first.

    Single-name picks (CVX, XOM, etc.) aren't in any ETF registry
    and ``_ticker_channel`` returns None for them; they default to
    ``"equities"`` so a thesis with only direct-name picks still
    contributes its equities channel to the primary set.
    """
    try:
        from asset_selection import _ticker_channel
    except Exception:
        return set(), set(), set()

    def _channels_for(bucket_key: str, *, default_for_singles: bool) -> set[str]:
        out: set[str] = set()
        bucket = event.get(bucket_key)
        if not isinstance(bucket, list):
            return out
        for entry in bucket:
            sym: Any = None
            if isinstance(entry, dict):
                sym = entry.get("symbol") or entry.get("ticker")
            elif isinstance(entry, str):
                sym = entry
            if isinstance(sym, str) and sym.strip():
                ch = _ticker_channel(sym.strip().upper())
                if ch:
                    out.add(ch)
                elif default_for_singles:
                    # Single-name picks aren't in the ETF registry —
                    # treat them as equities (matches
                    # validation_plan._asset_channel's fallback).
                    out.add("equities")
        return out

    return (
        # Primary / secondary buckets benefit from the equities
        # fallback because direct single-name picks live there.
        _channels_for("primary_assets",   default_for_singles=True),
        _channels_for("secondary_assets", default_for_singles=True),
        # Hedge / signal bucket uses the strict registry — its members
        # are always recognised ETFs (VXX/UUP/TBT/etc.).
        _channels_for("hedge_or_signal_assets", default_for_singles=False),
    )


def _sort_items_by_asset_priority(
    items: list[dict],
    *,
    primary: set[str],
    secondary: set[str],
    signal: set[str],
) -> list[dict]:
    """Stable-sort ``items`` so primary-asset channels come first,
    then secondary, then signal, then anything else.  Original
    family-level order is preserved within each priority bucket so
    the desk still reads the dominant proof item per channel first.
    """
    def _key(item: dict) -> int:
        ch = item.get("channel") if isinstance(item, dict) else None
        if ch in primary:
            return 0
        if ch in secondary:
            return 1
        if ch in signal:
            return 2
        return 3
    return sorted(items, key=_key)


def _watch_prefixed_proof(item: dict) -> dict:
    """Stamp a ``Watch:`` prefix onto the item's ``why_it_matters`` so a
    watch_only item can't be rendered as a definitive proof claim.
    Returns a new dict — does NOT mutate the input."""
    out = dict(item)
    why = out.get("why_it_matters")
    if isinstance(why, str) and why and not why.startswith(_WATCH_ONLY_PREFIX):
        out["why_it_matters"] = _WATCH_ONLY_PREFIX + why
    return out


def _watch_prefixed_falsifier(item: dict) -> dict:
    """Mirror of ``_watch_prefixed_proof`` for falsifier items."""
    out = dict(item)
    why = out.get("why_it_breaks_thesis")
    if isinstance(why, str) and why and not why.startswith(_WATCH_ONLY_PREFIX):
        out["why_it_breaks_thesis"] = _WATCH_ONLY_PREFIX + why
    return out


def _resolve_event_subtype(event: dict) -> Optional[str]:
    """Return the mechanism subtype for ``event``.  Prefers the stored
    ``mechanism_subtype`` field when present and non-empty; otherwise
    falls back to keyword inference over ``mechanism_summary`` +
    ``what_changed``.  Returns ``None`` when the family doesn't
    register any subtypes (or no keyword matched), which keeps the
    family-level behaviour for callers that haven't been threaded
    through.
    """
    family = event.get("mechanism_family")
    if not isinstance(family, str) or not family.strip() or family == "none":
        return None
    stored = event.get("mechanism_subtype")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    try:
        from mechanism_family import infer_mechanism_subtype
    except Exception:
        return None
    return infer_mechanism_subtype(
        family,
        event.get("mechanism_summary") or "",
        event.get("what_changed") or "",
    )


def _subtype_named_channels(family: Optional[str], subtype: Optional[str]) -> set[str]:
    """Channels named by the subtype's ``primary_overrides``.  Used to
    enforce subtype-channel discipline: a proof item targeting a
    channel outside the subtype's named set tests a *different*
    subtype than the chosen one and gets dropped."""
    if not (isinstance(family, str) and isinstance(subtype, str) and subtype):
        return set()
    try:
        from mechanism_family import FAMILY_SUBTYPES
    except Exception:
        return set()
    meta = FAMILY_SUBTYPES.get(family, {}).get(subtype)
    if not isinstance(meta, dict):
        return set()
    out: set[str] = set()
    for row in meta.get("primary_overrides") or []:
        if isinstance(row, dict):
            ch = row.get("channel")
            if isinstance(ch, str) and ch.strip():
                out.add(ch)
    return out


def _filter_items_to_subtype(
    items: list[dict],
    *,
    subtype_channels: set[str],
    cascade_channels: set[str],
) -> list[dict]:
    """Drop items whose channel is outside the subtype's named set
    UNLESS the channel is in the family's secondary cascade — that
    keeps multi-channel coverage intact for subtypes that span more
    than one channel.  When ``subtype_channels`` is empty (no subtype
    or unknown subtype), the filter is a no-op."""
    if not subtype_channels:
        return list(items)
    allowed = subtype_channels | (cascade_channels or set())
    return [
        i for i in items
        if isinstance(i, dict) and i.get("channel") in allowed
    ]


def _family_secondary_channels(family: Optional[str]) -> set[str]:
    """Channels in the family's ``second`` pack — used as the cascade
    set so multi-channel coverage isn't pruned by the subtype filter."""
    try:
        from mechanism_family import FAMILY_CHANNEL_PACKS
    except Exception:
        return set()
    pack = FAMILY_CHANNEL_PACKS.get(family or "none") or {}
    return set(pack.get("second") or [])


def proof_set_for_event(event: Any) -> list[dict]:
    """Tier-aware ``minimum_proof_set`` generator.

    Returns deterministic proof items scoped by the event's evidence
    quality tier:

      * ``low_information`` → ``[]`` (stable empty shape)
      * ``watch_only``       → at most :data:`_WATCH_ONLY_PROOF_CAP`
        items, each with a ``Watch:`` prefix on ``why_it_matters``
      * ``actionable``       → full family-level set, channel-filtered

    Subtype-aware: when the event names a ``mechanism_subtype`` (or
    one can be inferred from prose), the family generator pulls
    subtype-specialized rows AND items whose channel is outside the
    subtype's named set are rejected — preventing a proof item that
    tests a *different* subtype from surfacing.  Family secondary
    cascade channels stay allowed to preserve multi-channel coverage.

    Output dict keys are identical to ``proof_set_for_family`` so
    existing consumers see no shape change.
    """
    if not isinstance(event, dict):
        return []
    tier = evidence_quality_tier(event)
    if tier == "low_information":
        return []

    try:
        from mechanism_family import proof_set_for_family
    except Exception:
        return []
    family = event.get("mechanism_family") or "none"
    subtype = _resolve_event_subtype(event)
    base = proof_set_for_family(family, subtype=subtype)
    channels = _named_transmission_channels(event)
    base = _filter_items_to_channels(base, channels)

    # Subtype-channel filter: drop items on channels outside the
    # subtype's named set so a proof item testing a different subtype
    # can't sneak through.  Cascade channels (family secondary pack)
    # stay allowed to preserve multi-channel coverage.
    subtype_channels = _subtype_named_channels(family, subtype)
    cascade = _family_secondary_channels(family)
    base = _filter_items_to_subtype(
        base, subtype_channels=subtype_channels, cascade_channels=cascade,
    )

    # Asset-tier prioritisation: items on channels covered by
    # primary_assets land first, then secondary, then signal — proof
    # checks tied to the desk's direct picks read before checks on
    # indirect / signal exposures.
    primary_ch, secondary_ch, signal_ch = _asset_channels_by_tier(event)
    base = _sort_items_by_asset_priority(
        base, primary=primary_ch, secondary=secondary_ch, signal=signal_ch,
    )

    if tier == "watch_only":
        return [_watch_prefixed_proof(i) for i in base[:_WATCH_ONLY_PROOF_CAP]]
    return base


def falsifier_set_for_event(event: Any) -> list[dict]:
    """Tier-aware ``key_falsifiers`` generator.  Mirror of
    ``proof_set_for_event`` — same tier gating, same channel filter,
    same subtype-aware tightening, same item shape as
    ``falsifier_set_for_family``."""
    if not isinstance(event, dict):
        return []
    tier = evidence_quality_tier(event)
    if tier == "low_information":
        return []

    try:
        from mechanism_family import falsifier_set_for_family
    except Exception:
        return []
    family = event.get("mechanism_family") or "none"
    subtype = _resolve_event_subtype(event)
    base = falsifier_set_for_family(family, subtype=subtype)
    channels = _named_transmission_channels(event)
    base = _filter_items_to_channels(base, channels)

    subtype_channels = _subtype_named_channels(family, subtype)
    cascade = _family_secondary_channels(family)
    base = _filter_items_to_subtype(
        base, subtype_channels=subtype_channels, cascade_channels=cascade,
    )

    # Same asset-tier prioritisation as proof_set_for_event so the
    # falsifier list reads in the same priority order — primary-asset
    # channels first, then secondary, then signal.
    primary_ch, secondary_ch, signal_ch = _asset_channels_by_tier(event)
    base = _sort_items_by_asset_priority(
        base, primary=primary_ch, secondary=secondary_ch, signal=signal_ch,
    )

    if tier == "watch_only":
        return [
            _watch_prefixed_falsifier(i)
            for i in base[:_WATCH_ONLY_FALSIFIER_CAP]
        ]
    return base
