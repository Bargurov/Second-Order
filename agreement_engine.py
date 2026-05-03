"""
agreement_engine.py

Upgraded agreement / validation verdict composer.

Why this module
---------------
The shipped :func:`api._compute_support_ratio` is a naive count —
eligible tickers divided into "supports" vs everything else, weighted
equally.  That produces finance-unreal readings:

  * An oil-shock thesis with XOM +3% alpha-supporting but a drifting
    JPM satellite scores 50% agreement — identical to a coin flip,
    despite the direct proxy validating.
  * A supply-shock thesis with USO flat and XLE contradicting on the
    tape reports 0% agreement even when the persistence signal is
    clearly building.
  * Mechanism family is ignored — a tariff thesis and a commodity
    squeeze are scored against the same flat basket weighting.

This module replaces that count with a weighted, mechanism-aware
verdict that distinguishes DIRECT (alpha-support) from SECOND-ORDER
(beta-aligned) confirmation and clearly reports mixed / partial /
contradicted cases so the UI can render a real reason string.

Design
------
Pure composer.  No I/O.  Never raises.  Reads only fields that are
already written onto ``market_tickers`` by the shipped market-check
pipeline (``direction_tag``, ``validation_quality``,
``benchmark_sector``, ``return_5d``).

Ticker classification — the weight per ticker is picked by the
highest-quality signal available:

  * ``validation_quality`` in {alpha_support, alpha_contradicts}
        → **direct**  (alpha, isolated from tape)
  * ``validation_quality`` in {beta_aligned, beta_contradicts}
        → **second_order**  (moved with tape, corroborating but not thesis-specific)
  * ``validation_quality`` in {drift, flat, unavailable}
        → **noise**  (contributes zero to the score)
  * Legacy rows without ``validation_quality``:
        fall back to ``direction_tag``;
        treated as **direct** when the ticker's ``benchmark_sector``
        matches a primary channel for the event's mechanism family
        (see ``_is_family_primary``), else **second_order**.

Weighted score = Σ(signed_contribution) / Σ(|weight|) for tickers
with a classification; falls in [-1, 1].

Verdict bands (ordered for precedence — first match wins):
  * ``confirmed``:         weighted ≥ 0.50 AND ≥1 direct support
  * ``second_order_only``: weighted ≥ 0.15, direct_support = 0, direct_contradict = 0,
                           second_order_support ≥ 1 (tape confirms while direct lags)
  * ``partial``:           0.15 ≤ weighted < 0.50 (direct support present but diluted)
  * ``mixed``:            -0.15 ≤ weighted < 0.15 AND n ≥ 2
  * ``direct_miss``:      weighted in [-0.50, -0.15) AND direct_contradict ≥ 1
                          (a named direct proxy missed; tape-led evidence mixed)
  * ``weak``:             weighted in [-0.40, -0.15) AND direct_contradict = 0
                          (beta-led pushback, direct names flat)
  * ``contradicted``:     weighted < -0.40 OR (direct_contradict ≥ 2 AND direct_support = 0)
  * ``insufficient``:     fewer than 2 eligible tickers

Backward compat
---------------
``compute_support_ratio`` is preserved as a float-returning shim with
the original naive semantics so legacy tests and serialized mover
summaries continue to pass.  Callers that want the richer verdict
should call ``compute_agreement_verdict`` directly.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Classification weights — document the "direct over satellite" intent
# ---------------------------------------------------------------------------

# Bottleneck proxies are tickers named explicitly in the event's
# transmission_path / substitution_barriers / beneficiaries / losers
# text — the actors the LLM identified as the mechanism's chokepoints.
# They sit ABOVE the generic "direct" tier because a move on a named
# bottleneck is finance-direct by construction; a move on a similar
# pure-play peer still only counts as direct.
_CLASS_WEIGHT: dict[str, float] = {
    "bottleneck_proxy": 3.5,
    "direct":           2.5,
    "second_order":     1.0,
    # Hedge / signal proxies (UUP, VIX, TLT, inverse ETFs) are
    # explicitly non-direct exposures — they corroborate or hedge the
    # tape rather than name the mechanism.  A contradicting hedge ETF
    # must weigh less than a contradicting primary.
    "hedge_signal":     0.5,
    "satellite":        0.3,
    "noise":            0.0,
}

# Per-ticker signed contribution per signal class.  Alpha signals are
# finance-direct; beta signals corroborate at a discount so a tape-led
# supporting move doesn't lock in "confirmed" on its own.
_ALPHA_SIGN: dict[str, float] = {
    "alpha_support":      +1.0,
    "alpha_contradicts":  -1.0,
    "beta_aligned":       +0.7,
    "beta_contradicts":   -0.7,
    "drift":               0.0,
    "flat":                0.0,
    "unavailable":         0.0,
}

# Verdict thresholds.  Asymmetric band for the lean-contradict case so
# a thesis leaning wrong isn't labelled outright contradicted until
# the score crosses the same magnitude as "confirmed" uses for support.
_CONFIRMED_FLOOR:  float = 0.50
_PARTIAL_FLOOR:    float = 0.15
_CONTRADICTED_CEIL: float = -0.40

_INSUFFICIENT_N: int = 2


# Family → primary-channel asset classes.  Derived from
# mechanism_family.FAMILY_CHANNEL_PACKS so this module stays in sync
# with the canonical pack definitions.  Lazy-loaded to avoid import
# cost on modules that don't need the classifier.
_FAMILY_PRIMARY_CACHE: Optional[dict[str, set[str]]] = None


def _family_primary_channels() -> dict[str, set[str]]:
    global _FAMILY_PRIMARY_CACHE
    if _FAMILY_PRIMARY_CACHE is not None:
        return _FAMILY_PRIMARY_CACHE
    try:
        from mechanism_family import FAMILY_CHANNEL_PACKS
        _FAMILY_PRIMARY_CACHE = {
            fam: set(pack.get("first") or [])
            for fam, pack in FAMILY_CHANNEL_PACKS.items()
        }
    except Exception:
        _FAMILY_PRIMARY_CACHE = {}
    return _FAMILY_PRIMARY_CACHE


# Ticker benchmark_sector → the asset-class bucket used in channel packs.
# Kept small: anything we don't explicitly map gets treated as
# "equities" (the dominant universe) so an unmapped sector equity
# never blocks the second-order read.
_SECTOR_TO_CHANNEL: dict[str, str] = {
    "energy":        "commodities",
    "materials":     "commodities",
    "metals":        "commodities",
    "oil":           "commodities",
    "gold":          "commodities",
    "copper":        "commodities",
    "rates":         "rates",
    "bonds":         "rates",
    "duration":      "rates",
    "credit":        "credit",
    "hy":            "credit",
    "ig":            "credit",
    "fx":            "fx",
    "dollar":        "fx",
    "currencies":    "fx",
    "vol":           "vol",
    "volatility":    "vol",
    # Sector equities — all fall into the generic equities bucket.
    "financials":    "equities",
    "banks":         "equities",
    "technology":    "equities",
    "healthcare":    "equities",
    "discretionary": "equities",
    "staples":       "equities",
    "industrials":   "equities",
    "utilities":     "equities",
    "real_estate":   "equities",
    "market":        "equities",
}


def _channel_for_sector(benchmark_sector: Any) -> Optional[str]:
    if not isinstance(benchmark_sector, str):
        return None
    key = benchmark_sector.strip().lower().replace(" ", "_")
    if key in _SECTOR_TO_CHANNEL:
        return _SECTOR_TO_CHANNEL[key]
    # Last-resort: any sector we don't know about that's a recognised
    # equity sector still slots into "equities".  Unknown → None so the
    # family-aware classifier doesn't pretend the ticker is a primary.
    if key in {"communications", "services", "defense", "semiconductors"}:
        return "equities"
    return None


def _is_family_primary(family: Optional[str], channel: Optional[str]) -> bool:
    """True when the ticker's channel is in the family's FIRST pack."""
    if not family or not channel:
        return False
    primaries = _family_primary_channels().get(family) or set()
    return channel in primaries


# ---------------------------------------------------------------------------
# Per-ticker classification
# ---------------------------------------------------------------------------

def _eligible(t: dict) -> bool:
    """Minimum evidence bar — ticker carries a 5d return AND either a
    direction_tag or a validation_quality.  Tickers missing both are
    not informative enough to contribute."""
    if not isinstance(t, dict):
        return False
    if t.get("return_5d") is None:
        return False
    vq = t.get("validation_quality")
    dt = t.get("direction_tag")
    return bool(vq) or bool(dt)


def extract_mechanism_actors(
    transmission_path: Any = None,
    substitution_barriers: Any = None,
    beneficiaries_text: Any = None,
    losers_text: Any = None,
) -> frozenset[str]:
    """Pull uppercase ticker-like tokens from the event's mechanism
    structure.  Returned as an immutable set so callers can cache it.

    A token qualifies when it is 1-5 alphabetic characters — the
    canonical US ticker shape.  We tolerate surrounding punctuation
    like "Exxon (XOM)" or "LRCX / AMAT cut".  Non-string inputs are
    silently skipped so malformed LLM output never crashes the
    classifier.
    """
    tokens: set[str] = set()

    def _harvest(text: Any) -> None:
        if not isinstance(text, str) or not text:
            return
        # Replace common separators / bullets with spaces so token
        # boundaries stay intact.
        for raw in text.replace("·", " ").replace("/", " ").split():
            t = raw.strip("(),.;:!?\"'[]{}·—–-").upper()
            if 1 <= len(t) <= 5 and t.isalpha():
                tokens.add(t)

    # transmission_path: list of {hop, channel, actor} dicts.
    if isinstance(transmission_path, list):
        for hop in transmission_path:
            if isinstance(hop, dict):
                _harvest(hop.get("actor"))
                _harvest(hop.get("hop"))

    # substitution_barriers: list of {barrier, kind, severity} dicts.
    if isinstance(substitution_barriers, list):
        for b in substitution_barriers:
            if isinstance(b, dict):
                _harvest(b.get("barrier"))

    # beneficiaries / losers text — names of firms, often with ticker
    # in parentheses.  Iterable of strings.
    for seq in (beneficiaries_text, losers_text):
        if isinstance(seq, (list, tuple)):
            for item in seq:
                _harvest(str(item) if item is not None else "")

    return frozenset(tokens)


_HEDGE_DEMOTE_FROM: frozenset[str] = frozenset(
    {"bottleneck_proxy", "direct", "second_order"},
)


def _classify(
    t: dict,
    family: Optional[str],
    bottleneck_symbols: frozenset[str] = frozenset(),
    hedge_or_signal_symbols: frozenset[str] = frozenset(),
) -> tuple[str, float]:
    """Return ``(class, signed_sign_magnitude)`` for the ticker.

    ``class`` is one of ``"bottleneck_proxy" | "direct" | "second_order"
    | "hedge_signal" | "satellite" | "noise"``.  ``bottleneck_proxy``
    is a promotion of the ``direct`` class for tickers whose symbol is
    named in the event's mechanism structure (transmission_path /
    substitution_barriers / beneficiaries / losers).  A generic sector
    ETF is never promoted — being in the narrative doesn't make it a
    bottleneck actor.

    ``hedge_signal`` is a DEMOTION applied last: a ticker explicitly
    listed in the event's ``hedge_or_signal_assets`` bucket (UUP, VIX,
    TLT, inverse ETFs) caps out at ~0.5 weight regardless of what the
    base classifier returned.  Hedge proxies are watch-or-hedge
    instruments by construction — a contradicting hedge must weigh
    less than a contradicting primary, even when the hedge happens to
    look like a clean alpha mover on the tape.
    """
    sym = (t.get("symbol") or "").strip().upper()
    is_bottleneck = bool(sym) and sym in bottleneck_symbols
    is_hedge      = bool(sym) and sym in hedge_or_signal_symbols

    def _maybe_demote_hedge(cls: str, sign: float) -> tuple[str, float]:
        if is_hedge and cls in _HEDGE_DEMOTE_FROM:
            return "hedge_signal", sign
        return cls, sign

    vq = t.get("validation_quality")
    if isinstance(vq, str) and vq in _ALPHA_SIGN:
        sign = _ALPHA_SIGN[vq]
        if vq in ("alpha_support", "alpha_contradicts"):
            cls = "bottleneck_proxy" if is_bottleneck else "direct"
            return _maybe_demote_hedge(cls, sign)
        if vq in ("beta_aligned", "beta_contradicts"):
            return _maybe_demote_hedge("second_order", sign)
        if vq == "drift":
            # Drift = moved against / away from the thesis even after
            # removing beta — weak satellite evidence, not pure noise.
            return "satellite", 0.0
        return "noise", 0.0

    # Legacy / market-check-only rows: fall back to direction_tag.
    dt = t.get("direction_tag") or ""
    if isinstance(dt, str):
        if dt.startswith("supports"):
            sign = +1.0
        elif dt.startswith("contradicts"):
            sign = -1.0
        else:
            return "noise", 0.0
    else:
        return "noise", 0.0

    # Family-aware classification of the legacy row: a ticker whose
    # benchmark_sector maps to one of the family's FIRST channels is
    # treated as a direct proxy; others are second-order so a diffuse
    # basket doesn't dominate the direct proxies.
    channel = _channel_for_sector(t.get("benchmark_sector"))
    if _is_family_primary(family, channel):
        cls = "bottleneck_proxy" if is_bottleneck else "direct"
        return _maybe_demote_hedge(cls, sign)
    # Named-but-not-a-primary-channel still gets the direct tier — a
    # bottleneck name that happens to sit on a second-order channel is
    # still more informative than a random sector ETF.
    if is_bottleneck:
        return _maybe_demote_hedge("direct", sign)
    return _maybe_demote_hedge("second_order", sign)


# ---------------------------------------------------------------------------
# Verdict + reason composition
# ---------------------------------------------------------------------------

def _verdict_for(
    score: float,
    n_direct_support: int,
    n_direct_contradict: int,
    n_second_support: int,
    n_eligible: int,
) -> str:
    """Classify the verdict.  Order matters — first match wins.

    The precedence captures the finance-real distinctions the user-
    facing reason-string reads on: a direct proxy missing is a
    different failure mode from a tape-led beta fade, and a tape
    confirming while the direct names sleep is different from a
    half-dominant direct-proxy confirmation.
    """
    if n_eligible < _INSUFFICIENT_N:
        return "insufficient"

    # Hard contradiction first — multiple direct proxies wrong with no
    # offsetting direct support is "true contradiction" even if the
    # weighted aggregate hasn't crossed _CONTRADICTED_CEIL yet.
    if n_direct_contradict >= 2 and n_direct_support == 0:
        return "contradicted"

    if score >= _CONFIRMED_FLOOR and n_direct_support >= 1:
        return "confirmed"

    # Second-order-only: tape / beta names confirm but the direct
    # proxies are silent (drift / flat / unavailable), not missing.
    # This deserves its own label so the UI can say "second-order
    # confirms, direct names lagging" instead of a flat "partial".
    if (
        score >= _PARTIAL_FLOOR
        and n_direct_support == 0
        and n_direct_contradict == 0
        and n_second_support >= 1
    ):
        return "second_order_only"

    # Strong primary contradiction overrides weak / noisy support.
    # When a named direct or bottleneck proxy is moving against the
    # thesis with NO direct alpha offset, a positive aggregate score
    # — driven by beta-aligned tape or hedge/signal corroboration —
    # shouldn't be allowed to lift the verdict to "partial".  Doing so
    # hides the failing mechanism behind drift; calling it
    # "contradicted" is the finance-real read.  The existing
    # 2-direct-contradicts rule above still fires regardless of score
    # when the primary basket is uniformly wrong.
    if (
        score >= _PARTIAL_FLOOR
        and n_direct_contradict >= 1
        and n_direct_support == 0
    ):
        return "contradicted"

    if score >= _PARTIAL_FLOOR:
        return "partial"

    if score > -_PARTIAL_FLOOR:
        return "mixed"

    # Split the "leaning against" band by whether a direct proxy is
    # the culprit — direct_miss (named proxy missed) vs weak (beta-led
    # tape fade, direct names flat).
    if score > _CONTRADICTED_CEIL:
        if n_direct_contradict >= 1:
            return "direct_miss"
        return "weak"

    return "contradicted"


def _join_symbols(tickers: list[dict], limit: int = 3) -> str:
    syms = [t.get("symbol", "") for t in tickers if t.get("symbol")]
    return ", ".join(syms[:limit])


def _reason(
    verdict: str,
    direct_support: list[dict],
    direct_contradict: list[dict],
    second_support: list[dict],
    second_contradict: list[dict],
    satellite: list[dict],
    n_eligible: int,
) -> str:
    """Human-readable desk-note rationale for the verdict.

    The priority is telling the reader WHY the aggregate reads the
    way it does — which proxy carried the weight, what's dragging,
    and whether the tape is doing the work or the named proxy is.
    """
    if verdict == "insufficient":
        return f"Only {n_eligible} ticker(s) with usable direction — sample too thin."

    if verdict == "confirmed":
        bits = [f"direct proxies {_join_symbols(direct_support)} support"]
        if second_support:
            bits.append(f"{len(second_support)} beta-aligned name(s) corroborate")
        if direct_contradict or second_contradict:
            bits.append(
                f"{len(direct_contradict) + len(second_contradict)} counter-signal(s)"
            )
        return "; ".join(bits)

    if verdict == "second_order_only":
        lead = (
            f"{len(second_support)} beta-aligned name(s) "
            f"({_join_symbols(second_support, 3)}) confirm via the tape; "
            "direct proxies silent — watch the named equities for follow-through."
        )
        if second_contradict:
            lead += f"  {len(second_contradict)} tape-level counter-move(s) noted."
        return lead

    if verdict == "partial":
        if direct_support:
            lead = f"direct proxy {_join_symbols(direct_support, 2)} supports"
        elif second_support:
            lead = f"{len(second_support)} beta-aligned name(s) support"
        else:
            lead = "partial lean on satellites only"
        tail = []
        if direct_contradict:
            tail.append(
                f"but {_join_symbols(direct_contradict, 2)} pushing back (direct)"
            )
        elif second_contradict:
            tail.append(f"{len(second_contradict)} tape-led counter-moves dragging")
        if satellite and not (direct_contradict or second_contradict):
            tail.append(
                f"{len(satellite)} satellite name(s) drifting — diluting the read"
            )
        return lead + (" — " + "; ".join(tail) if tail else "")

    if verdict == "mixed":
        s_total = len(direct_support) + len(second_support)
        c_total = len(direct_contradict) + len(second_contradict)
        bits = [
            f"Split read: {s_total} support / {c_total} contradict across "
            f"{n_eligible} tickers"
        ]
        if direct_support and direct_contradict:
            bits.append(
                f"direct proxies split — {_join_symbols(direct_support, 2)} vs "
                f"{_join_symbols(direct_contradict, 2)}"
            )
        return " — ".join(bits) + "."

    if verdict == "direct_miss":
        lead = (
            f"direct proxy {_join_symbols(direct_contradict, 2)} missed "
            "— the named thesis name is moving against"
        )
        tail = []
        if direct_support:
            tail.append(
                f"{_join_symbols(direct_support, 2)} still holding — thesis "
                "partially intact on a different direct read"
            )
        if second_support:
            tail.append(
                f"{len(second_support)} beta-aligned name(s) corroborating — "
                "second-order channel still live"
            )
        return lead + (" — " + "; ".join(tail) if tail else "") + "."

    if verdict == "weak":
        lead = "tape-led fade: beta-aligned names leaning against"
        if direct_support:
            return (
                lead + f"; {_join_symbols(direct_support, 2)} still holding the "
                "thesis direction — not outright broken."
            )
        return lead + " — direct proxies silent, thesis fraying but not contradicted."

    # contradicted
    if direct_contradict:
        lead = (
            f"{_join_symbols(direct_contradict)} contradict (direct) — "
            "named thesis names moving the wrong way"
        )
    elif second_contradict:
        lead = (
            f"{len(second_contradict)} beta-aligned name(s) moved against "
            "across the tape"
        )
    else:
        lead = "Broad negative lean across eligible tickers"
    if direct_support or second_support:
        lead += (
            f"; {len(direct_support) + len(second_support)} offsetting "
            "support(s) insufficient to rescue thesis"
        )
    return lead + "."


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def _diagnose_failure_mode(
    verdict: str,
    *,
    bottleneck_support: int,    bottleneck_contradict: int,
    direct_support:     int,    direct_contradict:     int,
    second_support:     int,    second_contradict:     int,
) -> Optional[dict[str, str]]:
    """Explain WHY the agreement is less than clean.

    Returns ``None`` when the verdict is already clean (``confirmed``
    or ``insufficient``); otherwise returns a dict with a
    single-word ``mode`` and a readable ``rationale`` that names the
    specific failure pattern.  The four modes map to the four
    diagnoses a research desk would actually cite for a low-
    agreement thesis:

      * ``true_contradiction``   — the named/direct proxies oppose;
                                   the mechanism itself is failing.
      * ``bad_primary_proxy``    — direct names are silent/flat while
                                   the cross-asset tape is with the
                                   thesis; the proxy basket is off.
      * ``second_order_lag``     — direct proxies confirm but the tape
                                   hasn't echoed; classic cascade lag.
      * ``mixed_cross_asset_tape`` — the tape itself is split across
                                   channels; no dominant signal.
    """
    if verdict in ("confirmed", "insufficient"):
        return None

    d_sup = bottleneck_support + direct_support
    d_con = bottleneck_contradict + direct_contradict
    s_sup = second_support
    s_con = second_contradict

    # 1. True contradiction — the mechanism's named proxies oppose,
    # with no offsetting direct support.
    if d_con >= 1 and d_sup == 0:
        names = []
        if bottleneck_contradict:
            names.append(f"{bottleneck_contradict} bottleneck")
        if direct_contradict:
            names.append(f"{direct_contradict} direct")
        joined = " + ".join(names) if names else f"{d_con} direct"
        return {
            "mode": "true_contradiction",
            "rationale": (
                f"{joined} proxy move(s) against the thesis with no "
                "alpha offset — the mechanism appears to be failing, "
                "not merely slow."
            ),
        }

    # 2. Bad primary proxy — no direct signal in either direction, but
    # tape is confirming.  The named basket isn't capturing the move.
    if d_sup == 0 and d_con == 0 and s_sup >= 1 and s_sup > s_con:
        return {
            "mode": "bad_primary_proxy",
            "rationale": (
                "Direct proxies are silent while the cross-asset tape "
                f"confirms ({s_sup} support / {s_con} contradict on beta) — "
                "the named basket likely doesn't capture the mechanism."
            ),
        }

    # 3. Second-order lag — direct proxies confirm alone; the cascade
    # hasn't arrived yet.  Preserved as a SOFT failure (not truly bad).
    if d_sup >= 1 and s_sup == 0 and s_con == 0:
        return {
            "mode": "second_order_lag",
            "rationale": (
                f"{d_sup} direct proxy confirm(s) but the tape hasn't "
                "echoed yet — classic cascade lag; monitor the "
                "follow-through channels for the second leg."
            ),
        }

    # 4. Mixed cross-asset tape — tape itself disagrees with itself.
    if s_sup >= 1 and s_con >= 1:
        return {
            "mode": "mixed_cross_asset_tape",
            "rationale": (
                f"Cross-asset tape is split ({s_sup} support / "
                f"{s_con} contradict) — reads disagree across channels; "
                "wait for a cleaner signal."
            ),
        }

    # Fallback — we got a non-clean verdict but none of the patterns
    # above matched cleanly.  Surface it honestly.
    return {
        "mode": "mixed_cross_asset_tape",
        "rationale": (
            "Signal is diluted across proxy tiers with no dominant "
            "driver — no single failure mode stands out."
        ),
    }


def _coerce_hedge_symbols(raw: Any) -> frozenset[str]:
    """Normalise the hedge_or_signal_assets input into a symbol set.

    Accepts None / list of strings / list of {symbol, ...} dicts (the
    structured ranked-asset shape) and returns a frozenset of upper-
    cased ticker symbols.  Defensive — bad shapes degrade to empty.
    """
    if not isinstance(raw, (list, tuple)):
        return frozenset()
    out: set[str] = set()
    for entry in raw:
        sym = None
        if isinstance(entry, str):
            sym = entry
        elif isinstance(entry, dict):
            sym = entry.get("symbol")
        if isinstance(sym, str):
            s = sym.strip().upper()
            if s:
                out.add(s)
    return frozenset(out)


def compute_agreement_verdict(
    tickers: Optional[list[dict]],
    *,
    mechanism_family: Optional[str] = None,
    transmission_path: Optional[list] = None,
    substitution_barriers: Optional[list] = None,
    beneficiaries_text: Optional[Any] = None,
    losers_text: Optional[Any] = None,
    hedge_or_signal_assets: Optional[Any] = None,
) -> dict[str, Any]:
    """Weighted agreement verdict across ticker classes.

    ``mechanism_family`` drives channel-pack routing for legacy rows.

    ``transmission_path`` / ``substitution_barriers`` /
    ``beneficiaries_text`` / ``losers_text`` are the event's richer
    mechanism structure.  Tickers whose symbols are named in those
    fields get promoted from ``direct`` to ``bottleneck_proxy`` — a
    named bottleneck move weighs ~40% more than a generic direct peer,
    because the LLM specifically flagged that actor as the mechanism's
    chokepoint.  Missing / None inputs degrade to the legacy classification.

    Returns a dict with ``support_ratio`` (backward-compat float),
    per-class counters including ``bottleneck_support``/``bottleneck_contradict``,
    ``verdict``, ``weighted_score``, a human-readable ``reason``, and a
    ``failure_mode`` block that names WHY the agreement is short of
    confirmed.
    """
    tickers = tickers or []
    eligible = [t for t in tickers if _eligible(t)]

    # Extract the mechanism-actor set once per event — passed into the
    # per-ticker classifier so a named actor gets promoted to the
    # bottleneck_proxy tier.
    bottleneck_symbols = extract_mechanism_actors(
        transmission_path=transmission_path,
        substitution_barriers=substitution_barriers,
        beneficiaries_text=beneficiaries_text,
        losers_text=losers_text,
    )
    # Hedge / signal pool — passed in as either a list of symbols or
    # the structured {symbol, rank, rationale} shape from
    # ``hedge_or_signal_assets``.  Tickers in this set are demoted at
    # classification time so a contradicting hedge ETF weighs less than
    # a contradicting primary.
    hedge_symbols = _coerce_hedge_symbols(hedge_or_signal_assets)

    bottleneck_support:    list[dict] = []
    bottleneck_contradict: list[dict] = []
    direct_support:        list[dict] = []
    direct_contradict:     list[dict] = []
    second_support:        list[dict] = []
    second_contradict:     list[dict] = []
    satellite:             list[dict] = []
    noise:                 list[dict] = []

    numerator = 0.0
    denominator = 0.0
    for t in eligible:
        cls, sign = _classify(
            t, mechanism_family, bottleneck_symbols, hedge_symbols,
        )
        weight = _CLASS_WEIGHT.get(cls, 0.0)
        if cls == "noise":
            noise.append(t)
            continue
        if cls == "satellite":
            satellite.append(t)
            # Satellites contribute only to denominator when not drifting
            # against — a drift-tagged ticker is pure noise.  Here the
            # magnitude is 0 by construction so no numerator impact either.
            denominator += weight
            continue

        contribution = weight * sign
        numerator += contribution
        denominator += weight

        # hedge_signal is an internal sub-tier of the second-order /
        # tape-level bucket — for output counters we fold it into
        # second_order_* so the response shape stays stable.  The
        # weight reduction has already taken effect on the score.
        bucket_cls = "second_order" if cls == "hedge_signal" else cls
        bucket_key = (bucket_cls, "support" if sign > 0 else "contradict")
        {
            ("bottleneck_proxy", "support"):    bottleneck_support,
            ("bottleneck_proxy", "contradict"): bottleneck_contradict,
            ("direct",       "support"):        direct_support,
            ("direct",       "contradict"):     direct_contradict,
            ("second_order", "support"):        second_support,
            ("second_order", "contradict"):     second_contradict,
        }[bucket_key].append(t)

    n_eligible = (
        len(bottleneck_support) + len(bottleneck_contradict)
        + len(direct_support) + len(direct_contradict)
        + len(second_support) + len(second_contradict) + len(satellite)
    )

    # Keep full float precision on the internal score so
    # ``compute_support_ratio`` preserves 2/3-style canonical values
    # without rounding-induced drift.  UI consumers are expected to
    # round at display time.
    weighted_score = (numerator / denominator) if denominator > 0 else 0.0

    # Fold bottleneck counters into the "direct" totals for the existing
    # verdict classifier — a bottleneck move IS a direct move, just
    # heavier-weighted.  The verdict bands don't need to know about the
    # new tier.
    folded_direct_support    = len(bottleneck_support) + len(direct_support)
    folded_direct_contradict = len(bottleneck_contradict) + len(direct_contradict)

    verdict = _verdict_for(
        weighted_score,
        folded_direct_support,
        folded_direct_contradict,
        len(second_support),
        n_eligible,
    )

    failure_mode = _diagnose_failure_mode(
        verdict,
        bottleneck_support=len(bottleneck_support),
        bottleneck_contradict=len(bottleneck_contradict),
        direct_support=len(direct_support),
        direct_contradict=len(direct_contradict),
        second_support=len(second_support),
        second_contradict=len(second_contradict),
    )

    # Backward-compat ratio: same semantics as the original naive count,
    # so existing consumers (serialized mover summaries, old UI pills)
    # stay unchanged on the wire even when the richer verdict is new.
    legacy_pool = [
        t for t in tickers
        if t.get("direction_tag") is not None and t.get("return_5d") is not None
    ]
    legacy_supports = sum(
        1 for t in legacy_pool
        if (t.get("direction_tag") or "").startswith("supports")
    )
    legacy_ratio = (
        legacy_supports / len(legacy_pool) if legacy_pool else 0.0
    )

    return {
        "support_ratio":   round(legacy_ratio, 3),
        "weighted_score":  weighted_score,
        "verdict":         verdict,
        "n_eligible":      n_eligible,
        # Bottleneck tier — NEW.  Counts tickers named in the mechanism
        # structure that moved with / against the thesis on alpha.
        "bottleneck_support":      len(bottleneck_support),
        "bottleneck_contradict":   len(bottleneck_contradict),
        "bottleneck_symbols":      sorted(bottleneck_symbols),
        # Direct / second-order counters — unchanged, do NOT include
        # bottleneck tier (the "direct" counter is the non-bottleneck
        # direct tier only).
        "direct_support":          len(direct_support),
        "direct_contradict":       len(direct_contradict),
        "second_order_support":    len(second_support),
        "second_order_contradict": len(second_contradict),
        "satellite":               len(satellite),
        "noise":                   len(noise),
        # Failure-mode diagnosis — None when verdict is confirmed /
        # insufficient; otherwise names the specific pattern:
        # true_contradiction | bad_primary_proxy | second_order_lag |
        # mixed_cross_asset_tape.
        "failure_mode":            failure_mode,
        "reason": _reason(
            verdict,
            # Fold bottleneck winners/losers into the direct list the
            # reason builder names explicitly — readers want to see
            # "bottleneck XOM supports" stated plainly.
            bottleneck_support + direct_support,
            bottleneck_contradict + direct_contradict,
            second_support, second_contradict,
            satellite,
            n_eligible,
        ),
    }


def compute_support_ratio(
    tickers: Optional[list[dict]],
    *,
    mechanism_family: Optional[str] = None,
) -> float:
    """Weighted agreement as a single float in [0, 1].

    Maps the signed ``weighted_score`` from ``compute_agreement_verdict``
    back to the 0-1 range callers and frontend pills already consume.
    Insufficient-sample cases return 0.0 rather than the legacy naive
    ratio — the verdict dict is the right surface for that nuance.

    Existing callers that want exact backward-compat with the old naive
    count can read ``compute_agreement_verdict(tickers)["support_ratio"]``
    directly.
    """
    verdict = compute_agreement_verdict(tickers, mechanism_family=mechanism_family)
    # Map signed [-1, 1] to [0, 1].  A score of 0 maps to 0.5 so a
    # genuinely mixed thesis looks mixed, not 0%.  No rounding — the
    # caller displays with its own precision.
    #
    # The float is returned even for ``insufficient``-verdict samples
    # (n_eligible in {1}) so the legacy "single ticker supports → 1.0"
    # contract used by the mover pill keeps working.  Callers that
    # need to gate on sample depth should read the verdict dict.
    if verdict["n_eligible"] == 0:
        return 0.0
    score = verdict["weighted_score"]
    return max(0.0, min(1.0, 0.5 + score / 2))
