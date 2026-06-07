"""Read-only naive-baseline characterization for the scored archive (T2A).

Answers the skeptic's first question — *are the observed support /
contradiction / unresolved outcomes meaningfully different from a baseline, or
mostly the corpus's own drift?* — without any "compared to what" hand-waving.

Design note — why NOT a fair coin
----------------------------------
A "supports" tag means the realized move matched the thesis-predicted direction
(beneficiary => predicted up, loser => predicted down).  A fair-coin (p = 0.5)
null is correct only when predicted directions are balanced ~50/50.  This
archive is beneficiary-heavy (predicted-up fraction well above 0.5) inside a
single, down-drifting market window, so a coin null would mechanically
manufacture a spurious "below chance" reading.

Instead we use a **marginal-preserving permutation null**: the predicted
directions (role labels) are shuffled across the directional ticker-observations
while the realized moves are held fixed.  That preserves both marginals (the
predicted-direction mix AND the window's actual move distribution) and destroys
only the thesis-to-asset linkage, then re-applies the LIVE majority rule
(supporting strictly > contradicting => validated; ties => contradicted) per
event.  Its expected support rate is the corpus's own ``1 - a - b + 2ab``.

Purity / scope
--------------
Pure functions over event dicts; deterministic with a fixed ``seed``.  No DB,
no provider, no network, no DB writes.  It NEVER reads, merges, or implies the
closed Phase 1 / Phase 2 FDR pool q-values — those are a separate scope.  Every
payload carries explicit non-claims, limitations, and a falsifier.
"""

from __future__ import annotations

import random
from typing import Any


# ---------------------------------------------------------------------------
# Pure ticker / event helpers
# ---------------------------------------------------------------------------


def directional_observations(event: Any) -> list[tuple[bool, bool]]:
    """Return ``(predicted_up, realized_up)`` for each directional ticker.

    A ticker is directional only if it carries a ``supports`` / ``contradicts``
    ``direction_tag`` and a ``beneficiary`` / ``loser`` role.  ``predicted_up``
    is ``role == beneficiary``; ``realized_up`` is recovered from the role+tag
    pairing (beneficiary & supports, or loser & contradicts, means the name
    rose).  Non-directional / role-less tickers are skipped.
    """
    out: list[tuple[bool, bool]] = []
    tickers = event.get("market_tickers") if isinstance(event, dict) else None
    if not isinstance(tickers, list):
        return out
    for t in tickers:
        if not isinstance(t, dict):
            continue
        tag = t.get("direction_tag")
        tag = tag.strip().lower() if isinstance(tag, str) else ""
        role = t.get("role")
        role = role.strip().lower() if isinstance(role, str) else ""
        is_sup = tag.startswith("supports")
        is_con = tag.startswith("contradicts")
        if not (is_sup or is_con):
            continue
        if role not in ("beneficiary", "loser"):
            continue
        predicted_up = role == "beneficiary"
        realized_up = (role == "beneficiary" and is_sup) or (role == "loser" and is_con)
        out.append((predicted_up, realized_up))
    return out


def support_contradict_counts(event: Any) -> tuple[int, int]:
    """``(n_supporting, n_contradicting)`` — support iff predicted == realized.

    Equivalent to the live scorer's per-ticker tally (a "supports" tag is
    exactly predicted == realized), so it stays faithful to
    ``validation_status.score_validation_status``.
    """
    obs = directional_observations(event)
    supporting = sum(1 for predicted, realized in obs if predicted == realized)
    return supporting, len(obs) - supporting


def is_null_validated(n_supporting: int, n_directional: int) -> bool:
    """Live majority rule: validated iff supporting strictly > contradicting.

    Ties (and contradicting majorities) resolve to contradicted — the same rule
    ``score_validation_status`` applies, which makes even a fair null
    contradiction-heavy.
    """
    return n_supporting > (n_directional - n_supporting)


def _live_status(event: Any) -> str:
    """Four-label status via the live scorer (fidelity to the viewer surface)."""
    from validation_status import score_validation_status

    return score_validation_status(event)["status"]


def event_study_split(events: Any, event_study_fn) -> dict:
    """Split the scored set by event-study availability via an injected fn.

    ``event_study_fn(event)`` returns the gated event-study block (the read-only
    ``build_event_study_validation``).  Any engine error degrades the event to
    *unavailable* — this descriptive split must never raise.  Kept separate from
    the pure baseline so the permutation engine carries no price-cache I/O.
    """
    available = unavailable = 0
    for ev in events if isinstance(events, list) else []:
        tickers = ev.get("market_tickers") if isinstance(ev, dict) else None
        if not isinstance(tickers, list) or len(tickers) == 0:
            continue
        try:
            block = event_study_fn(ev) or {}
            if block.get("status") == "event_study_available":
                available += 1
            else:
                unavailable += 1
        except Exception:
            unavailable += 1
    return {
        "scored": available + unavailable,
        "event_study_available": available,
        "event_study_unavailable": unavailable,
    }


# ---------------------------------------------------------------------------
# Characterization
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T2B — benchmark-adjusted AR-sign disentangler
#
# The event-study (build_event_study_validation) computes an abnormal return
# (vs SPY) for the PRIMARY ticker only, so this comparison is one observation
# per event (not the full directional ticker set used above).  It asks whether
# benchmark adjustment changes the raw directional picture — but is only a
# usable baseline test when the predicted-direction marginal is non-degenerate.
# ---------------------------------------------------------------------------

_AR_BENCHMARK = "SPY"
_AR_MIN_RELIABLE_ELIGIBLE = 10


def ar_sign_observation(event: Any, es_block: Any, horizon: int):
    """``(predicted_up, ar_up)`` for the primary ticker, or ``None`` to exclude.

    Predicted direction comes from the primary ticker's role (beneficiary =>
    up, loser => down); realized direction comes from the benchmark-adjusted
    abnormal-return sign at ``horizon`` (NOT the raw return).  A missing /
    NaN / exactly-zero AR, or a primary without a beneficiary/loser role, is
    excluded.
    """
    if not isinstance(event, dict) or not isinstance(es_block, dict):
        return None
    tickers = event.get("market_tickers")
    if not isinstance(tickers, list) or not tickers:
        return None

    role = None
    primary_sym = es_block.get("primary_ticker")
    if isinstance(primary_sym, str) and primary_sym.strip():
        target = primary_sym.strip().upper()
        for t in tickers:
            if (isinstance(t, dict) and isinstance(t.get("symbol"), str)
                    and t["symbol"].strip().upper() == target):
                role = t.get("role")
                break
    if role is None:
        first = tickers[0]
        role = first.get("role") if isinstance(first, dict) else None
    role = role.strip().lower() if isinstance(role, str) else ""
    if role not in ("beneficiary", "loser"):
        return None

    ar = None
    for h in es_block.get("per_horizon") or []:
        if isinstance(h, dict) and h.get("horizon") == horizon:
            ar = h.get("abnormal_return")
            break
    try:
        ar = float(ar)
    except (TypeError, ValueError):
        return None
    if ar != ar or ar == 0.0:  # NaN or exactly zero -> no usable direction
        return None
    return (role == "beneficiary", ar > 0.0)


def build_ar_sign_characterization(
    events: Any,
    event_study_fn,
    *,
    horizon: int,
    seed: int = 20260608,
    n_sims: int = 2000,
) -> dict:
    """One-horizon AR-sign characterization with a marginal-preserving null.

    ``event_study_fn(event)`` returns the gated event-study block.  The null is
    flagged ``reliable=False`` when the predicted-direction marginal is
    degenerate (no role variation to permute) or the eligible set is too small.
    """
    n_sims = int(max(1, n_sims))
    obs: list[tuple[bool, bool]] = []
    ready = excluded = 0
    for ev in events if isinstance(events, list) else []:
        tickers = ev.get("market_tickers") if isinstance(ev, dict) else None
        if not isinstance(tickers, list) or len(tickers) == 0:
            continue
        try:
            block = event_study_fn(ev) or {}
        except Exception:
            continue
        if block.get("status") != "event_study_available":
            continue
        ready += 1
        o = ar_sign_observation(ev, block, horizon)
        if o is None:
            excluded += 1
        else:
            obs.append(o)

    D = len(obs)
    a = (sum(1 for p, _ in obs if p) / D) if D else 0.0
    b = (sum(1 for _, u in obs if u) / D) if D else 0.0
    supporting = sum(1 for p, u in obs if p == u)
    reliable = D >= _AR_MIN_RELIABLE_ELIGIBLE and 0.0 < a < 1.0

    pred = [p for p, _ in obs]
    real = [u for _, u in obs]
    rng = random.Random(seed)
    nv_dist: list[int] = []
    rate_dist: list[float] = []
    for _ in range(n_sims):
        perm = pred[:]
        rng.shuffle(perm)
        bits = [1 if perm[i] == real[i] else 0 for i in range(D)]
        rate_dist.append((sum(bits) / D) if D else 0.0)
        nv_dist.append(sum(bits))  # size-1 events: validated == support

    ordered = sorted(nv_dist)

    def _pct(p: float) -> float:
        if not ordered:
            return 0.0
        k = int(round(p * (len(ordered) - 1)))
        return float(ordered[max(0, min(len(ordered) - 1, k))])

    null_mean = (sum(nv_dist) / len(nv_dist)) if nv_dist else 0.0
    null_rate = (sum(rate_dist) / len(rate_dist)) if rate_dist else 0.0
    ci_hi = _pct(0.975)

    if reliable:
        reason = None
    elif not (0.0 < a < 1.0):
        reason = (
            f"predicted-up marginal is degenerate (a={a:.2f}): the event-study computes "
            "abnormal return only for the primary ticker, which here is always one role, so "
            "the permutation null has no predicted-direction variation to shuffle and "
            "collapses to the observed value."
        )
    else:
        reason = f"fewer than {_AR_MIN_RELIABLE_ELIGIBLE} eligible observations (D={D})."

    return {
        "horizon": horizon,
        "benchmark": _AR_BENCHMARK,
        "ready_events": ready,
        "eligible": D,
        "excluded": excluded,
        "observed_support_fraction": round((supporting / D) if D else 0.0, 4),
        "predicted_up_fraction": round(a, 4),
        "ar_up_fraction": round(b, 4),
        "any_supporting": supporting,
        "contradicted": D - supporting,
        "unresolved": excluded,
        "baseline": {
            "definition": ("marginal-preserving permutation null on primary-ticker AR signs: "
                           "predicted-direction (role) labels are shuffled while AR signs are "
                           "held fixed; each event contributes one observation."),
            "seed": seed,
            "n_sims": n_sims,
            "null_support_rate_mean": round(null_rate, 4),
            "observed_validated": supporting,
            "null_validated_mean": round(null_mean, 4),
            "null_validated_ci95": [_pct(0.025), ci_hi],
            "observed_above_null_ci95": bool(supporting > ci_hi),
        },
        "reliable": bool(reliable),
        "reason": reason,
    }


def build_ar_sign_report(events: Any, event_study_fn, *, seed: int = 20260608, n_sims: int = 2000) -> dict:
    """All three horizons (1d / 5d / 20d) + reliability verdict and non-claims."""
    horizons = {
        str(h): build_ar_sign_characterization(events, event_study_fn, horizon=h, seed=seed, n_sims=n_sims)
        for h in (1, 5, 20)
    }
    any_reliable = any(h["reliable"] for h in horizons.values())
    return {
        "schema": "ar_sign_disentangler.v1",
        "benchmark": _AR_BENCHMARK,
        "horizons": horizons,
        "reliable": bool(any_reliable),
        "interpretation": "see_per_horizon" if any_reliable else "not_reliable_degenerate_null",
        "comparison_to_t2a": (
            "Benchmark adjustment does not overturn T2A's 'not_above_baseline' conclusion. As a "
            "permutation-baseline skill test it is unusable when the predicted-direction marginal "
            "is degenerate (the event-study scores only the primary ticker, which is always the "
            "beneficiary, so a ~= 1.0 and the null collapses to the observed value). Descriptively, "
            "where the benchmark-adjusted support rate falls well below 0.5 (5d / 20d) most "
            "beneficiary primaries underperformed SPY — reinforcing, not rescuing, the T2A drift "
            "picture."
        ),
        "limitations": [
            "The event-study abnormal return exists only for the primary ticker, so this "
            "disentangler covers one observation per event (not the full directional ticker set "
            "used in T2A); the two are not directly comparable.",
            "Single-event AR signs are n=1 point estimates; no confidence interval, p-value, or "
            "false-discovery control applies at the single-event level.",
            "Events are date-clustered with overlapping forward windows (see stats/METHODOLOGY.md "
            "'Cohort inference — currently blocked'); any gap from the null is descriptive only.",
        ],
        "falsifier": (
            "This disentangler is unreliable as a skill test whenever the predicted-direction "
            "marginal is degenerate (all primaries one role) or eligible observations are too few; "
            "it would become usable only with abnormal returns for both beneficiary and exposed "
            "names on an independent, drift-balanced event set."
        ),
        "non_claims": [
            "Descriptive characterization of the local archive only.",
            "Not a trading signal and not a measure of edge.",
            "Single-event AR signs are n=1 point estimates, not a statistical-significance test.",
            "Separate from the closed Phase 1 / Phase 2 FDR pools; no pool q-values are used or implied.",
        ],
    }


def build_baseline_characterization(
    events: Any,
    *,
    seed: int = 20260608,
    n_sims: int = 2000,
) -> dict:
    """Characterize observed outcomes against a marginal-preserving null.

    ``events`` is a list of event row dicts (each with ``market_tickers``).
    Returns a stable, JSON-serialisable payload — see
    ``tests/test_baseline_characterization.py`` for the contract.
    """
    if not isinstance(events, list):
        events = []
    n_sims = int(max(1, n_sims))

    total_scored = any_supporting = contradicted = unresolved = 0
    per_event_obs: list[list[tuple[bool, bool]]] = []
    pred: list[bool] = []
    real: list[bool] = []
    member: list[int] = []  # event index per directional observation

    for ev in events:
        tickers = ev.get("market_tickers") if isinstance(ev, dict) else None
        if not isinstance(tickers, list) or len(tickers) == 0:
            continue  # scored set = events that carry market data
        total_scored += 1
        status = _live_status(ev)
        if status == "validated":
            any_supporting += 1
        elif status == "contradicted":
            contradicted += 1
        else:  # unresolved / pending grouped as unresolved for this denominator
            unresolved += 1
        obs = directional_observations(ev)
        if obs:
            idx = len(per_event_obs)
            per_event_obs.append(obs)
            for p, r in obs:
                pred.append(p)
                real.append(r)
                member.append(idx)

    directional_events = len(per_event_obs)
    sizes = [len(obs) for obs in per_event_obs]
    n_obs = len(pred)
    supporting_total = sum(1 for p, r in zip(pred, real) if p == r)
    a = (sum(1 for p in pred if p) / n_obs) if n_obs else 0.0
    b = (sum(1 for r in real if r) / n_obs) if n_obs else 0.0
    observed_validated = sum(
        1 for obs in per_event_obs
        if is_null_validated(sum(1 for p, r in obs if p == r), len(obs))
    )

    # Marginal-preserving permutation null.
    rng = random.Random(seed)
    n_validated_dist: list[int] = []
    support_rate_dist: list[float] = []
    for _ in range(n_sims):
        perm = pred[:]
        rng.shuffle(perm)
        sup_bits = [1 if perm[i] == real[i] else 0 for i in range(n_obs)]
        support_rate_dist.append((sum(sup_bits) / n_obs) if n_obs else 0.0)
        per_event_sup = [0] * directional_events
        for i in range(n_obs):
            per_event_sup[member[i]] += sup_bits[i]
        n_validated_dist.append(
            sum(1 for j in range(directional_events)
                if is_null_validated(per_event_sup[j], sizes[j]))
        )

    ordered = sorted(n_validated_dist)

    def _pct(p: float) -> float:
        if not ordered:
            return 0.0
        k = int(round(p * (len(ordered) - 1)))
        return float(ordered[max(0, min(len(ordered) - 1, k))])

    null_mean = sum(n_validated_dist) / len(n_validated_dist)
    ci_lo, ci_hi = _pct(0.025), _pct(0.975)
    observed_percentile = (
        sum(1 for v in n_validated_dist if v <= observed_validated) / len(n_validated_dist)
    )
    null_support_rate_mean = sum(support_rate_dist) / len(support_rate_dist)
    above = observed_validated > ci_hi

    beneficiaries = [r for p, r in zip(pred, real) if p]
    losers = [r for p, r in zip(pred, real) if not p]
    ben_rate = (sum(1 for r in beneficiaries if r) / len(beneficiaries)) if beneficiaries else None
    los_rate = (sum(1 for r in losers if not r) / len(losers)) if losers else None

    return {
        "schema": "baseline_characterization.v1",
        "observed": {
            "total_scored": total_scored,
            "any_supporting": any_supporting,
            "contradicted": contradicted,
            "unresolved": unresolved,
            "directional_events": directional_events,
            "directional_ticker_total": n_obs,
            "supporting": supporting_total,
            "contradicting": n_obs - supporting_total,
            "observed_supporting_fraction": round((supporting_total / n_obs) if n_obs else 0.0, 4),
        },
        "marginals": {
            "predicted_up_fraction": round(a, 4),
            "realized_up_fraction": round(b, 4),
            "beneficiary_support_rate": round(ben_rate, 4) if ben_rate is not None else None,
            "loser_support_rate": round(los_rate, 4) if los_rate is not None else None,
            "note": "predicted_up_fraction far from 0.5 means a fair-coin null is the wrong baseline.",
        },
        "baseline": {
            "definition": (
                "marginal-preserving permutation null: predicted-direction (role) labels are "
                "shuffled across directional ticker-observations while realized moves are held "
                "fixed; the live majority rule (supporting strictly > contradicting => validated; "
                "ties => contradicted) is then re-applied per event."
            ),
            "seed": seed,
            "n_sims": n_sims,
            "null_support_rate_mean": round(null_support_rate_mean, 4),
            "event_level": {
                "observed_validated": observed_validated,
                "null_validated_mean": round(null_mean, 4),
                "null_validated_ci95": [ci_lo, ci_hi],
                "observed_validated_percentile": round(observed_percentile, 4),
                "observed_above_null_ci95": bool(above),
            },
        },
        "interpretation": "above_baseline" if above else "not_above_baseline",
        "limitations": [
            "Directional events are date-clustered with overlapping forward windows "
            "(see stats/METHODOLOGY.md 'Cohort inference — currently blocked'); the "
            "observed-vs-null gap is descriptive, not an inferential significance test.",
            "The corpus is prediction-skewed (predicted-up fraction != 0.5) inside one "
            "market window, so realized direction is partly market drift; the permutation "
            "null preserves that drift. A raw-vs-benchmark-adjusted (AR-sign) support "
            "comparison would disentangle drift from thesis content.",
        ],
        "falsifier": (
            "Treat any gap from the null as a characterization of this particular corpus, not "
            "a measure of thesis skill: the directional events are not independent (date-"
            f"clustered) and the predicted-direction marginal is far from balanced (~{a:.2f}). "
            "The comparison would only become a skill test on an independent, drift-balanced "
            "event set or against benchmark-adjusted support."
        ),
        "non_claims": [
            "Descriptive characterization of the local archive only.",
            "Not a trading signal and not a measure of edge.",
            "Not a statistical-significance test; the events are not independent.",
            "Separate from the closed Phase 1 / Phase 2 FDR pools; no pool q-values are used or implied.",
        ],
    }
