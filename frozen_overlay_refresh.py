"""
frozen_overlay_refresh.py

Macro-overlay-only refresh path for saved events.

What it does
------------
Recomputes the composer-derived macro overlay blocks on an existing
event using TODAY's live macro tape, writes the sanitized results back
to the overlay columns only, and leaves the LLM thesis, ticker
returns, direction tags, and review labels untouched.

Why it's separate from market_check_freshness
---------------------------------------------
``market_check_freshness.refresh_market_for_saved_event`` refreshes
ticker returns on a saved event, and explicitly refuses to touch
FROZEN rows (> 30 days) because the stored tickers are the backtest
ground-truth that track-record / analog / calibration code reads from.

Overlay refresh is a narrower operation:

  * the thesis text (what_changed / mechanism_summary / beneficiaries /
    losers / transmission_chain / …) stays EXACTLY as written;
  * the ``market_tickers`` payload and the ``last_market_check_at``
    stamp are NOT touched, so backtests still read the original returns;
  * only the *macro-view overlays* (rates/stress/credit-driven blocks)
    are replaced with today's values.

That combination is safe to run on frozen events — no historical
ground-truth is overwritten — and it closes the gap where an archived
analysis' macro context rotted forever as soon as the event crossed
the 30-day cutoff.

Contract
--------
``refresh_overlays_for_event(event, *, persist=True)`` returns a dict::

    {
      "event_id":    int | None,
      "refreshed":   list[str],     # overlay keys that came back available
      "skipped":     list[str],     # overlay keys sanitized as degraded
      "eligibility": dict,           # from event_age_policy
      "written":     bool,           # True iff update_event_overlays touched a row
    }

Never raises on provider failure — each composer is guarded; failures
degrade to the uniform ``sanitize_overlay_block`` degraded contract.
"""

from __future__ import annotations

import logging
from datetime import datetime as _dt
from typing import Any, Callable, Optional

from event_age_policy import eligible_for_overlay_refresh
from overlay_sanitize import sanitize_overlay_block


_log = logging.getLogger("second_order.frozen_overlay_refresh")


# Macro-overlay field set this path regenerates.  Must be a subset of
# ``analyze_event.PERSISTED_OVERLAY_FIELDS`` — enforced at write time in
# ``db.update_event_overlays``.  Intentionally excludes any LLM-derived
# text columns; see module docstring.
REFRESHABLE_OVERLAYS: tuple[str, ...] = (
    "policy_sensitivity",
    "real_yield_context",
    "policy_constraint",
    "shock_decomposition",
    "reaction_function_divergence",
    "inventory_context",
    "surprise_vs_anticipation",
    "terms_of_trade",
    "reserve_stress",
    "credit_regime",
    "credit_transmission",
    "regime_snapshot",
    "narrative_divergence",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a composer; return ``{}`` on any failure.  The empty dict is
    the signal ``sanitize_overlay_block`` uses to emit the degraded
    contract downstream, so the caller never has to special-case errors.
    """
    try:
        return fn(*args, **kwargs) or {}
    except Exception:
        _log.warning("frozen_overlay_refresh: %s composer failed",
                     name, exc_info=True)
        return {}


def _fetch_live_macro() -> tuple[Optional[dict], Optional[dict]]:
    """Pull rates_context and stress_regime from the live provider.

    Both may be None on provider failure.  Downstream composers treat
    None-inputs as signal-absent and emit their own degraded outputs.
    """
    try:
        from market_check import compute_rates_context, compute_stress_regime
    except Exception:
        _log.warning("frozen_overlay_refresh: market_check import failed",
                     exc_info=True)
        return None, None
    rates = _safe("rates_context", compute_rates_context) or None
    stress = _safe("stress_regime", compute_stress_regime) or None
    # _safe returns {} for empty; normalize back to None so composers that
    # branch on "is this dict usable" see a proper absent-signal.
    rates = rates if isinstance(rates, dict) and rates else None
    stress = stress if isinstance(stress, dict) and stress else None
    return rates, stress


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def refresh_overlays_for_event(
    event: dict,
    *,
    now: Optional[_dt] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Recompute macro-tier overlays for ``event`` against today's tape.

    ``event`` is the dict returned by ``db.load_event_by_id`` — must
    carry at least ``id`` and ``headline``; ``stage`` / ``confidence``
    / ``market_tickers`` are read but tolerated when absent.

    When ``persist=True`` (default) the refreshed overlays are written
    back via ``db.update_event_overlays``.  Set ``persist=False`` in
    tests that want to inspect the composed output without a DB write.
    """
    eligibility = eligible_for_overlay_refresh(event, now=now)
    if not eligibility["eligible"]:
        return {
            "event_id":    event.get("id"),
            "refreshed":   [],
            "skipped":     list(REFRESHABLE_OVERLAYS),
            "eligibility": eligibility,
            "written":     False,
        }

    # --- Fetch the two primary macro anchors once; every composer feeds
    #     from them so one fetch hits the cache.
    rates_live, stress_live = _fetch_live_macro()

    headline = event.get("headline") or ""
    what_changed = event.get("what_changed") or ""
    mechanism_summary = event.get("mechanism_summary") or ""
    mech_text = f"{what_changed} {mechanism_summary}".strip()
    stage = event.get("stage") or ""
    tickers = event.get("market_tickers") or []
    confidence = event.get("confidence", "low")

    # --- Late imports isolate composer-import failures.  A broken
    #     surprise_vs_anticipation import must not nuke the whole refresh.
    from market_check import classify_policy_sensitivity
    from real_yield_context import build_real_yield_context
    from policy_constraint import compute_policy_constraint
    from shock_decomposition import compute_shock_decomposition
    from reaction_function_divergence import compute_reaction_function_divergence
    from surprise_vs_anticipation import compute_surprise_vs_anticipation
    from terms_of_trade import compute_terms_of_trade
    from reserve_stress_overlay import compute_reserve_stress
    from credit_regime import classify_credit_regime
    from credit_transmission import compute_credit_transmission
    from narrative_divergence import compute_narrative_divergence
    from regime_vector import build_regime_vector
    from market_check import classify_inventory_context

    # --- Composer runs.  Order preserves data dependencies:
    #       credit_regime feeds regime_snapshot + reserve_stress + credit_transmission
    #       terms_of_trade feeds reserve_stress.
    policy_sensitivity = _safe(
        "policy_sensitivity", classify_policy_sensitivity,
        (rates_live or {}).get("regime", ""), mech_text,
    )
    real_yield_ctx = _safe(
        "real_yield_context", build_real_yield_context,
        headline, mech_text, rates_live,
    )
    policy_constraint_ctx = _safe(
        "policy_constraint", compute_policy_constraint,
        headline, mech_text, rates_live, stress_live, snapshots=None,
    )
    shock_decomp_ctx = _safe(
        "shock_decomposition", compute_shock_decomposition,
        rates_live, stress_live, snapshots=None,
    )
    reaction_div_ctx = _safe(
        "reaction_function_divergence", compute_reaction_function_divergence,
        headline, mech_text, rates_live, stress_live, snapshots=None,
    )
    inventory_context = _safe(
        "inventory_context", classify_inventory_context,
        f"{headline} {mech_text}".strip(),
    )

    raw_stress = (stress_live or {}).get("raw") or {}
    credit_regime_ctx = _safe(
        "credit_regime", classify_credit_regime,
        hy_5d=raw_stress.get("hyg_5d"),
        ig_5d=raw_stress.get("lqd_5d"),
        shy_5d=raw_stress.get("shy_5d"),
    )

    regime_snapshot = _safe(
        "regime_snapshot", build_regime_vector,
        rates_live, stress_live, None,
        credit_regime=credit_regime_ctx,
    )

    # surprise_vs_anticipation: pre-event drift windows are too far back
    # to be meaningful for frozen events, so we pass an empty dict —
    # the composer degrades to its stage-bias branch cleanly.
    surprise_ctx = _safe(
        "surprise_vs_anticipation", compute_surprise_vs_anticipation,
        stage, tickers=tickers, stress_regime=stress_live, pre_event_drift={},
    )

    terms_of_trade_ctx = _safe(
        "terms_of_trade", compute_terms_of_trade,
        headline, mech_text,
        inventory_context=inventory_context, snapshots=None,
        stress_regime=stress_live,
    )

    reserve_stress_ctx = _safe(
        "reserve_stress", compute_reserve_stress,
        headline, mech_text,
        terms_of_trade=terms_of_trade_ctx,
        rates_context=rates_live, stress_regime=stress_live,
        credit_regime=credit_regime_ctx,
    )

    credit_transmission_ctx = _safe(
        "credit_transmission", compute_credit_transmission,
        credit_regime=credit_regime_ctx,
        stress_regime=stress_live,
        rates_context=rates_live,
    )

    try:
        from db import get_confidence_calibration_stats
        calib = get_confidence_calibration_stats()
    except Exception:
        calib = {}
    narrative_div_ctx = _safe(
        "narrative_divergence", compute_narrative_divergence,
        tickers, confidence, calib,
    )

    composed: dict[str, Any] = {
        "policy_sensitivity":           policy_sensitivity,
        "real_yield_context":           real_yield_ctx,
        "policy_constraint":            policy_constraint_ctx,
        "shock_decomposition":          shock_decomp_ctx,
        "reaction_function_divergence": reaction_div_ctx,
        "inventory_context":            inventory_context,
        "surprise_vs_anticipation":     surprise_ctx,
        "terms_of_trade":               terms_of_trade_ctx,
        "reserve_stress":               reserve_stress_ctx,
        "credit_regime":                credit_regime_ctx,
        "credit_transmission":          credit_transmission_ctx,
        "regime_snapshot":              regime_snapshot,
        "narrative_divergence":         narrative_div_ctx,
    }

    # --- Sanitize every block through the uniform degraded contract.
    #     Frozen rows whose composers degraded will carry explicit
    #     {available, stale, degraded, degraded_reason} keys on write.
    sanitized: dict[str, Any] = {
        k: sanitize_overlay_block(v, name=k) for k, v in composed.items()
    }

    refreshed = [k for k, v in sanitized.items() if v.get("available")]
    skipped   = [k for k, v in sanitized.items() if not v.get("available")]

    written = False
    if persist and event.get("id") is not None:
        try:
            from db import update_event_overlays
            written = update_event_overlays(int(event["id"]), sanitized)
        except Exception:
            _log.warning("frozen_overlay_refresh: update_event_overlays failed",
                         exc_info=True)
            written = False

    return {
        "event_id":    event.get("id"),
        "refreshed":   refreshed,
        "skipped":     skipped,
        "eligibility": eligibility,
        "written":     written,
    }
