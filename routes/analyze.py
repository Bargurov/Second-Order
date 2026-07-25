"""Route handlers for /analyze and /analyze/stream.

All domain-module functions (analyze_event, market_check, classify_*,
compute_*, etc.) are accessed via ``_api.XXX`` so that test patches on
``api.analyze_event``, ``api.market_check``, etc. still intercept the
calls.  Direct imports would bypass the patches.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from analyze_event import AnalyzeEventInput, is_mock as _is_mock_analysis
from news_sources import normalize_headline

import api as _api


def _run_pre_market_overlays(
    analysis: dict, headline: str, mech_text: str, stage: str, persistence: str,
) -> tuple[dict | None, dict | None]:
    """Compute overlays that don't need market data.

    Mutates *analysis* in-place with:
      policy_sensitivity, real_yield_context, policy_constraint,
      shock_decomposition, reaction_function_divergence, regime_snapshot,
      inventory_context, historical_analogs.

    Returns (rates_for_overlays, stress_for_overlays) for re-use by post-market.
    """
    rates_for_overlays: dict | None = None
    stress_for_overlays: dict | None = None
    try:
        rates_for_overlays = _api.compute_rates_context()
        analysis["policy_sensitivity"] = _api.classify_policy_sensitivity(rates_for_overlays["regime"], mech_text)
    except Exception:
        _api._log.warning("policy_sensitivity computation failed", exc_info=True)
        analysis["policy_sensitivity"] = {}
    try:
        analysis["real_yield_context"] = _api.build_real_yield_context(headline, mech_text, rates_for_overlays)
    except Exception:
        _api._log.warning("real_yield_context computation failed", exc_info=True)
        analysis["real_yield_context"] = {}
    try:
        stress_for_overlays = _api.compute_stress_regime()
    except Exception:
        _api._log.warning("stress_regime computation failed (analyze)", exc_info=True)
        stress_for_overlays = None
    # Shock decomposition first — its rates_pack feeds the policy_constraint
    # front-end-repricing detector, so the order matters.  Both are pure
    # composers over the same rates_context + stress_regime + snapshots, so
    # reordering is safe.
    try:
        analysis["shock_decomposition"] = _api.compute_shock_decomposition(rates_for_overlays, stress_for_overlays, snapshots=None)
    except Exception:
        _api._log.warning("shock_decomposition computation failed", exc_info=True)
        analysis["shock_decomposition"] = {}
    # Fetch recent macro-calendar releases + classify against current news
    # clusters so policy_constraint can incorporate CPI/NFP surprise signals.
    # Stays best-effort: any failure degrades policy_constraint to its
    # non-surprise-aware behaviour without breaking the flow.
    _macro_releases_classified: list | None = None
    try:
        from macro_calendar import get_macro_releases
        from macro_surprise import classify_macro_surprise
        _releases = get_macro_releases()
        _clusters = (_api._get_news_cached() or {}).get("clusters") or []
        _macro_releases_classified = classify_macro_surprise(_releases, _clusters)
    except Exception:
        _api._log.warning("policy_constraint: macro-release enrichment failed", exc_info=True)
        _macro_releases_classified = None
    try:
        analysis["policy_constraint"] = _api.compute_policy_constraint(
            headline, mech_text, rates_for_overlays, stress_for_overlays,
            snapshots=None,
            macro_releases=_macro_releases_classified,
            rates_pack=(analysis.get("shock_decomposition") or {}).get("rates_pack"),
        )
    except Exception:
        _api._log.warning("policy_constraint computation failed", exc_info=True)
        analysis["policy_constraint"] = {}
    try:
        analysis["reaction_function_divergence"] = _api.compute_reaction_function_divergence(headline, mech_text, rates_for_overlays, stress_for_overlays, snapshots=None)
    except Exception:
        _api._log.warning("reaction_function_divergence computation failed", exc_info=True)
        analysis["reaction_function_divergence"] = {}
    # Classify credit_regime HERE — pre-market — so it can feed the
    # regime vector's new `credit` axis.  _run_post_market_overlays will
    # also write analysis["credit_regime"], but we need the classified
    # output visible to build_regime_vector() right now.
    _pre_credit_regime: dict | None = None
    try:
        _raw = (stress_for_overlays or {}).get("raw") or {}
        _pre_credit_regime = _api.classify_credit_regime(
            hy_5d=_raw.get("hyg_5d"),
            ig_5d=_raw.get("lqd_5d"),
            shy_5d=_raw.get("shy_5d"),
        )
    except Exception:
        _api._log.warning("credit_regime pre-market classify failed", exc_info=True)
        _pre_credit_regime = None
    try:
        current_regime_vec = _api.build_regime_vector(
            rates_for_overlays, stress_for_overlays, None,
            credit_regime=_pre_credit_regime,
        )
    except Exception:
        _api._log.warning("regime_vector computation failed", exc_info=True)
        current_regime_vec = None

    # Compound regime + transition detection — a finance-useful view on
    # top of the raw axis vector.  Baseline is the modal regime over the
    # most recent saved events so transitions are grounded in what the
    # system has actually been seeing, not a snapshot in a vacuum.
    try:
        from regime_compound import baseline_from_events, enrich_with_compound_regime
        _recent = _api.load_recent_events(limit=25)
        _baseline = baseline_from_events(_recent)
        current_regime_vec = enrich_with_compound_regime(
            current_regime_vec, _baseline,
        )
    except Exception:
        _api._log.warning("compound_regime enrichment failed", exc_info=True)

    analysis["regime_snapshot"] = current_regime_vec or {}
    inv_text = f"{headline} {mech_text}"
    try:
        analysis["inventory_context"] = _api.classify_inventory_context(inv_text)
    except Exception:
        _api._log.warning("inventory_context computation failed", exc_info=True)
        analysis["inventory_context"] = {}
    _raw_analogs = _api.find_historical_analogs(
        headline, mechanism=analysis.get("mechanism_summary", ""), stage=stage,
        persistence=persistence, exclude_headline=headline, current_regime_vector=current_regime_vec,
        current_event_mechanism={
            "mechanism_family": analysis.get("mechanism_family"),
            "transmission_path": analysis.get("transmission_path"),
            "expected_first_order_channels": analysis.get("expected_first_order_channels"),
        },
    )
    # Enrich with structured match dimensions + topic-vs-regime mismatch
    # note.  See analog_explainer.py for the per-dimension contract.
    try:
        from analog_explainer import explain_analogs as _explain_analogs
        analysis["historical_analogs"] = _explain_analogs(
            _raw_analogs,
            current_regime=current_regime_vec,
            current_mechanism_family=analysis.get("mechanism_family") or "none",
        )
    except Exception:
        _api._log.warning("analog_explainer failed; serving raw analogs",
                          exc_info=True)
        analysis["historical_analogs"] = _raw_analogs
    return rates_for_overlays, stress_for_overlays


def _run_post_market_overlays(
    analysis: dict, mkt: dict, headline: str, mech_text: str,
    rates: dict | None, stress: dict | None, stage: str,
    event_date: str | None = None,
) -> None:
    """Compute overlays that need market-check data.

    Mutates *analysis* in-place with:
      surprise_vs_anticipation, terms_of_trade, reserve_stress, narrative_divergence.
    """
    pre_drift: dict[str, float] = {}
    try:
        tickers_for_drift = [t.get("symbol") for t in mkt.get("tickers", [])
                             if isinstance(t, dict) and t.get("symbol")]
        if tickers_for_drift:
            pre_drift = _api.compute_pre_event_drift(tickers_for_drift, event_date)
    except Exception:
        _api._log.warning("compute_pre_event_drift failed", exc_info=True)
        pre_drift = {}
    try:
        analysis["surprise_vs_anticipation"] = _api.compute_surprise_vs_anticipation(
            stage, tickers=mkt.get("tickers", []), stress_regime=stress,
            pre_event_drift=pre_drift,
        )
    except Exception:
        _api._log.warning("surprise_vs_anticipation computation failed", exc_info=True)
        analysis["surprise_vs_anticipation"] = {}
    try:
        analysis["terms_of_trade"] = _api.compute_terms_of_trade(headline, mech_text, inventory_context=analysis.get("inventory_context", {}), snapshots=None, stress_regime=stress)
    except Exception:
        _api._log.warning("terms_of_trade computation failed", exc_info=True)
        analysis["terms_of_trade"] = {}
    # Credit regime — classifies HY/IG/SHY moves into default-risk / duration /
    # decoupled / risk-on-off buckets.  Must run BEFORE reserve_stress so the
    # richer tiered credit signal feeds the pressure score.
    try:
        raw = (stress or {}).get("raw") or {}
        analysis["credit_regime"] = _api.classify_credit_regime(
            hy_5d=raw.get("hyg_5d"),
            ig_5d=raw.get("lqd_5d"),
            shy_5d=raw.get("shy_5d"),
        )
    except Exception:
        _api._log.warning("credit_regime computation failed", exc_info=True)
        analysis["credit_regime"] = {}
    try:
        analysis["reserve_stress"] = _api.compute_reserve_stress(
            headline, mech_text,
            terms_of_trade=analysis.get("terms_of_trade", {}),
            rates_context=rates, stress_regime=stress,
            credit_regime=analysis.get("credit_regime", {}),
        )
    except Exception:
        _api._log.warning("reserve_stress computation failed", exc_info=True)
        analysis["reserve_stress"] = {}
    try:
        analysis["narrative_divergence"] = _api.compute_narrative_divergence(
            mkt.get("tickers", []),
            analysis.get("confidence", "low"),
            _api.get_confidence_calibration_stats(),
        )
    except Exception:
        _api._log.warning("narrative_divergence computation failed", exc_info=True)
        analysis["narrative_divergence"] = {}
    # Credit transmission — funding-stress verdict, equity-vs-credit
    # separation, sector exposures.  Depends on credit_regime (just computed)
    # plus the stress regime (VIX, safe-haven) and rates context (real yield).
    try:
        analysis["credit_transmission"] = _api.compute_credit_transmission(
            credit_regime=analysis.get("credit_regime"),
            stress_regime=stress,
            rates_context=rates,
        )
    except Exception:
        _api._log.warning("credit_transmission computation failed", exc_info=True)
        analysis["credit_transmission"] = {}
    # Cross-asset confirmation — derived overlay; not persisted separately
    # because it's a pure function of shock_decomposition + thesis, both of
    # which already live on the event row.  Compute here so fresh responses
    # carry it; _build_cached_response recomputes on cache reads.
    try:
        sd = analysis.get("shock_decomposition") or {}
        thesis_info = _api.classify_thesis(headline, mech_text)
        analysis["cross_asset_confirmation"] = _api.compute_cross_asset_confirmation(
            thesis_info.get("thesis", "none"),
            sd.get("channels") or {},
            rates_pack=sd.get("rates_pack"),
        )
    except Exception:
        _api._log.warning("cross_asset_confirmation computation failed", exc_info=True)
        analysis["cross_asset_confirmation"] = {}
    # Sector passthrough — derived from the ticker lists + mechanism text +
    # shock_decomposition primary.  Second-order read: downstream sectors
    # that should lag-react if the mechanism plays through, plus distinct
    # direct (1-5d) vs downstream (5-20d) validation windows.
    try:
        sd = analysis.get("shock_decomposition") or {}
        analysis["sector_passthrough"] = _api.compute_sector_passthrough(
            beneficiary_tickers=analysis.get("beneficiary_tickers") or [],
            loser_tickers=analysis.get("loser_tickers") or [],
            mechanism_text=mech_text,
            shock_primary=sd.get("primary"),
        )
    except Exception:
        _api._log.warning("sector_passthrough computation failed", exc_info=True)
        analysis["sector_passthrough"] = {}
    # Regime + family-conditioned confidence calibration.  Derives the
    # compound regime label from analysis["regime_snapshot"] (the
    # enriched vector written by _run_pre_market_overlays) and the family
    # from analysis["mechanism_family"].  Cascades from strict joint
    # (family + regime) down to the global confidence bucket, marking
    # the depth tier explicitly so the UI can show a thin-archive chip.
    try:
        from confidence_calibration import (
            build_calibration_tree, lookup_calibration,
        )
        from db import collect_calibration_samples
        _tree = build_calibration_tree(collect_calibration_samples())
        _regime_snap = analysis.get("regime_snapshot") or {}
        _compound = (_regime_snap.get("compound") or {}) if isinstance(_regime_snap, dict) else {}
        _compound_label = _compound.get("label") if isinstance(_compound, dict) else None
        analysis["confidence_calibration"] = lookup_calibration(
            _tree,
            confidence=analysis.get("confidence", "low"),
            family=analysis.get("mechanism_family"),
            compound_regime=_compound_label,
        )
    except Exception:
        _api._log.warning("confidence_calibration lookup failed", exc_info=True)
        analysis["confidence_calibration"] = {}
    # Horizon-aware thesis scorecard — joins the LLM-written 1d/5d/20d
    # expected + confirms_if + falsifies_if criteria against the realized
    # ticker returns (revisit snapshots preferred where present).
    # Surfaces per-horizon status (confirmed/mixed/failed/pending) plus
    # an aggregate on_track/drifting/breaking/pending verdict.
    try:
        from thesis_scorecard import compute_thesis_scorecard
        analysis["thesis_scorecard"] = compute_thesis_scorecard(
            analysis.get("horizon_checkpoints"),
            mkt.get("tickers"),
            revisit_snapshots=None,  # no revisits on the fresh path yet
        )
    except Exception:
        _api._log.warning("thesis_scorecard computation failed", exc_info=True)
        analysis["thesis_scorecard"] = {}
    # Funding / liquidity stress mode classifier — decomposes the tape
    # into four orthogonal modes (duration_shock, credit_widening,
    # dollar_shortage, liquidity_squeeze) so the engine can name the
    # binding mode instead of collapsing everything into one stress read.
    # Inputs are the already-computed composer outputs; fx_pack lives
    # inside shock_decomposition.rates_pack if present.
    try:
        from funding_stress_classifier import classify_funding_stress
        _sd = analysis.get("shock_decomposition") or {}
        _fx_pack = (_sd.get("fx_pack") if isinstance(_sd, dict) else None) or None
        analysis["funding_stress_mode"] = classify_funding_stress(
            rates_context=rates,
            stress_regime=stress,
            credit_regime=analysis.get("credit_regime"),
            fx_pack=_fx_pack,
        )
    except Exception:
        _api._log.warning("funding_stress_mode classification failed", exc_info=True)
        analysis["funding_stress_mode"] = {}
    # Sector-rotation impact map — deterministic macro→sector playbook.
    # Reads rates_5d, breakeven_5d, credit_regime, DXY, crude, gold,
    # and the funding_stress_mode just computed.  Crude/gold values come
    # from stress_regime.raw when present.
    try:
        from sector_rotation import compute_sector_rotation
        _raw = (stress or {}).get("raw") or {}
        _rates_5d = ((rates or {}).get("nominal") or {}).get("change_5d")
        _be_5d    = ((rates or {}).get("breakeven_proxy") or {}).get("change_5d")
        _sd_blk   = analysis.get("shock_decomposition") or {}
        _fx_pack  = (_sd_blk.get("fx_pack") if isinstance(_sd_blk, dict) else {}) or {}
        _dxy_5d   = _fx_pack.get("dxy_5d") if isinstance(_fx_pack, dict) else None
        if _dxy_5d is None:
            # Fallback: safe_haven.assets.Dollar surfaced by stress_regime.
            _dxy_5d = (((stress or {}).get("detail") or {}).get("safe_haven") or {}).get("assets", {}).get("Dollar")
        analysis["sector_rotation"] = compute_sector_rotation(
            rates_5d_pp=_rates_5d,
            breakeven_5d_pp=_be_5d,
            credit_regime=analysis.get("credit_regime"),
            dxy_5d_pct=_dxy_5d,
            crude_5d_pct=_raw.get("crude_5d"),
            gold_5d_pct=_raw.get("gold_5d"),
            funding_stress_mode=analysis.get("funding_stress_mode"),
        )
    except Exception:
        _api._log.warning("sector_rotation computation failed", exc_info=True)
        analysis["sector_rotation"] = {}
    # Finance playbook — single-read synthesis of every block already on
    # ``analysis``.  Runs LAST in the post-market pass so it sees the
    # finished versions of every diagnostic it composes.  Pure read —
    # no provider calls, no new classification.
    try:
        from finance_playbook import compose_finance_playbook
        analysis["finance_playbook"] = compose_finance_playbook(analysis)
    except Exception:
        _api._log.warning("finance_playbook synthesis failed", exc_info=True)
        analysis["finance_playbook"] = {}


def _call_analyze_event(headline: str, stage: str, persistence: str,
                        event_context: str, macro_context: str) -> dict:
    """Build an AnalyzeEventInput and invoke api.analyze_event."""
    inp = AnalyzeEventInput(
        headline=headline, stage=stage, persistence=persistence,
        event_context=event_context, macro_context=macro_context,
    )
    return _api.analyze_event(inp)


def _apply_asset_selection(analysis: dict) -> tuple[list, list]:
    """Run the post-LLM asset-selection discipline on ``analysis`` and
    return ``(cleaned_beneficiary_tickers, cleaned_loser_tickers)``.

    Mutates ``analysis`` in-place so ``analysis["asset_selection"]``
    carries the full ``classify_and_rank_assets`` shape (primary /
    secondary / hedge_signal / excluded + cleaned lists + rationale).
    The cleaned tickers are the lists callers must feed to
    ``market_check`` so broad-market indices, price benchmarks, foreign
    listings, and hedge/signal ETFs never reach the provider.

    Why this lives here: ``/analyze`` and ``/analyze/stream`` need to
    run identical filtering before the market-check call.  Inlining
    the same block twice drifted previously — the streaming path
    skipped the step entirely and shipped raw LLM lists, polluting the
    agreement score with SPY / ^VIX / VXX moves that had nothing to do
    with the thesis.  See tests/test_analyze_ticker_selection_parity.py
    for the pinned contract.

    Defensive: any failure inside ``classify_and_rank_assets`` falls
    back to the raw LLM lists (matching the pre-extraction behaviour)
    so a bug in the composer can't take the analyze flow down with it.
    """
    try:
        from asset_selection import classify_and_rank_assets
        analysis["asset_selection"] = classify_and_rank_assets(
            beneficiary_tickers=analysis.get("beneficiary_tickers") or [],
            loser_tickers=analysis.get("loser_tickers") or [],
            mechanism_family=analysis.get("mechanism_family"),
            beneficiaries_text=analysis.get("beneficiaries") or [],
            losers_text=analysis.get("losers") or [],
        )
        return (
            analysis["asset_selection"]["cleaned_beneficiary_tickers"],
            analysis["asset_selection"]["cleaned_loser_tickers"],
        )
    except Exception:
        _api._log.warning("asset_selection failed; using raw LLM lists", exc_info=True)
        analysis["asset_selection"] = {}
        return (
            analysis.get("beneficiary_tickers") or [],
            analysis.get("loser_tickers") or [],
        )


def _enrich_macro_context_with_country(
    base_macro_ctx: str, headline: str,
) -> str:
    """Append the per-country vulnerability backdrop to ``macro_context``
    when the headline maps to a cached country profile.

    Uses only the task-pinned fields from
    ``country_backdrop.normalize_country_backdrop`` (external balance,
    import shock, commodity dependence, overall vulnerability,
    rationale) and produces a compact multi-line block.  No match →
    returns the base context untouched so the prompt is byte-identical
    on non-country events.  Failures degrade silently; the base macro
    context still reaches the LLM.
    """
    try:
        from country_context import build_country_backdrop_for_prompt
        country_ctx = build_country_backdrop_for_prompt(headline)
    except Exception:
        _api._log.warning(
            "country backdrop enrichment failed", exc_info=True,
        )
        return base_macro_ctx
    if not country_ctx:
        return base_macro_ctx
    return (
        f"{base_macro_ctx}\n\n{country_ctx}"
        if base_macro_ctx else country_ctx
    )


def _paid_confirmation_required(headline: str, effective_date: str) -> dict:
    """The non-provider response for an unconfirmed cache miss.

    Reaching this point means no saved analysis exists, so producing one
    would call a paid provider.  The route returns this instead — no
    provider call, no event row, no registry write — and the operator
    re-sends the same request with ``confirm_paid: true`` to proceed.
    """
    return {
        "status": "paid_confirmation_required",
        "headline": headline,
        "event_date": effective_date,
        "is_mock": False,
        "note": (
            "No saved analysis exists for this headline. Running one calls "
            "a paid provider; confirm explicitly to proceed."
        ),
    }


def _link_candidate_analysis(req: "_api.AnalyzeRequest",
                             analysis_event_id: int | None) -> str | None:
    """Stamp one persisted analysis onto its strict inbox candidate.

    Only runs when the request carried the full candidate identity AND the
    save produced a numeric id — a mock, degraded, failed or unpersisted
    run must never leave a link behind.  Conflicts are surfaced by the db
    layer and never repaired here.  Returns the link outcome, or ``None``
    when no linkage was attempted.
    """
    if analysis_event_id is None or req.candidate_id is None:
        return None
    try:
        return _api.link_candidate_analysis(
            req.parent_cluster_id, req.title_key, int(analysis_event_id),
            datetime.now().isoformat(timespec="seconds"),
        )
    except Exception:
        _api._log.warning("candidate analysis linkage failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# A1-2 — analysis provenance
# ---------------------------------------------------------------------------

def _candidate_provenance_unavailable(headline: str, effective_date: str) -> dict:
    """Fail-closed response when a candidate can no longer be reconstructed.

    Reached BEFORE any provider call.  An analysis whose basis cannot be
    captured would be unreconstructable the moment it was saved, so the run is
    refused rather than billed and stored without provenance.
    """
    return {
        "status": "candidate_provenance_unavailable",
        "headline": headline,
        "event_date": effective_date,
        "is_mock": False,
        "note": (
            "This candidate could not be resolved in the local news store, so "
            "the analysis basis cannot be recorded. No analysis was run."
        ),
    }


def _resolve_candidate_snapshot(req: "_api.AnalyzeRequest") -> dict | None:
    """Rebuild the candidate's owned records SERVER-SIDE, read-only.

    The request's source list is never consulted: provenance that trusted the
    caller would prove nothing.  Returns ``None`` when the candidate cannot be
    resolved, which callers must treat as fail-closed.
    """
    import analysis_provenance as _ap
    import db as _dbm
    from event_inbox import read_cluster_rows
    rows, _reason = read_cluster_rows(_dbm.DB_FILE)
    if rows is None:
        return None
    return _ap.build_candidate_snapshot(rows, req.parent_cluster_id, req.title_key)


def _provenance_builder(
    req: "_api.AnalyzeRequest", *, candidate_snapshot: dict, stage: str,
    persistence: str, macro_context: str, model: str,
):
    """Return a callable that seals provenance around the new events.id.

    The id only exists inside the write transaction, so the builder is handed
    to the db layer rather than a finished object.  Prompts are rendered
    through the SAME renderer ``analyze_event`` uses, so the stored prompt is
    the sent prompt and not a reconstruction.
    """
    import analysis_provenance as _ap
    from analyze_event import SYSTEM_PROMPT, render_analysis_prompt, resolve_provider_configuration

    provider = resolve_provider_configuration().provider
    rendered = render_analysis_prompt(
        headline=req.headline, stage=stage, persistence=persistence,
        event_context=req.event_context or "", macro_context=macro_context,
    )

    def _build(analysis_event_id: int) -> dict:
        return _ap.build_provenance(
            analysis_event_id=analysis_event_id,
            parent_cluster_id=req.parent_cluster_id,
            title_key=req.title_key,
            candidate_snapshot=candidate_snapshot,
            candidate_context_snapshot=req.event_context or "",
            macro_context_snapshot=macro_context,
            stage=stage, persistence=persistence,
            provider=provider, model=model,
            system_prompt_snapshot=SYSTEM_PROMPT,
            rendered_user_prompt_snapshot=rendered,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
    return _build


def _fresh_provenance_summary(
    provenance: dict | None, analysis_event_id: int | None,
    candidate_link: str | None,
) -> dict:
    """Summarize provenance for the run that just produced it.

    A run reads VERIFIED_CURRENT only when it saved a provenance snapshot AND
    the candidate linkage did not conflict.  A conflicted candidate points at
    more than one analysis, so nothing about it is verified — reporting it as
    current would hide the conflict behind a reassuring label.
    """
    import analysis_provenance as _ap
    if provenance is None or analysis_event_id is None:
        return _ap.summarize_for_response(
            None, _ap.derive_provenance_state(None, None))
    if candidate_link == "conflict":
        state = {"status": "SAVED_WITH_OLDER_BASIS",
                 "changed_dimensions": ["candidate_link_conflict"],
                 "problems": [],
                 "non_claim": _ap.PROVENANCE_NON_CLAIM}
        return _ap.summarize_for_response(provenance, state)
    problems = _ap.verify_provenance(provenance)
    if problems:
        return _ap.summarize_for_response(
            provenance, {"status": "PROVENANCE_INVALID",
                         "changed_dimensions": [], "problems": problems,
                         "non_claim": _ap.PROVENANCE_NON_CLAIM})
    return _ap.summarize_for_response(
        provenance, {"status": "VERIFIED_CURRENT", "changed_dimensions": [],
                     "problems": [], "non_claim": _ap.PROVENANCE_NON_CLAIM})


def _persist_with_provenance(
    req: "_api.AnalyzeRequest", headline: str, stage: str, persistence: str,
    analysis: dict, mkt: dict, effective_date: str, model: str,
    candidate_snapshot: dict | None, macro_context: str,
) -> tuple[str | None, int | None, dict | None]:
    """Persist the events row and (for a candidate run) its provenance.

    Returns ``(error, analysis_event_id, provenance)``.  A candidate-backed run
    writes both rows in ONE transaction, so a provenance failure rolls the
    events row back and the caller links nothing.  A direct (non-candidate)
    run keeps the existing single-row path and stores no provenance — it has
    no candidate basis to record.
    """
    # A direct (non-candidate) run keeps the existing single-row path and its
    # ``save_event`` seam untouched.  A1-3R scopes the three-way transaction
    # to Inbox-originated analyses, so routing direct runs through it would be
    # collateral change — reopening a direct analysis keeps the pre-existing
    # honest missingness.  See the deferred note in the A1-3R report.
    if candidate_snapshot is None or req.candidate_id is None:
        error, event_id = _api._persist_event(
            headline, stage, persistence, analysis, mkt, effective_date,
            model=model)
        return error, event_id, None

    import analysis_result_snapshot as _ars
    import db as _dbm

    # A1-3R: the saved readout output, built from the FINAL validated
    # `analysis` — exactly what the operator received.  See
    # analysis_result_snapshot for the inclusion boundary.
    snapshot = _ars.build_result_snapshot(analysis)
    builder = _provenance_builder(
        req, candidate_snapshot=candidate_snapshot, stage=stage,
        persistence=persistence, macro_context=macro_context, model=model)
    try:
        record = _api._build_event_record(
            headline, stage, persistence, analysis, mkt, effective_date,
            model=model)
        event_id, provenance = _dbm.save_event_with_analysis_provenance(
            record, builder, lambda _new_id: snapshot,
            created_at=datetime.now().isoformat(timespec="seconds"))
    except Exception as e:
        _api._log.warning("save_event_with_analysis_provenance failed: %s", e,
                          exc_info=True)
        return f"{type(e).__name__}: {e}", None, None
    _api._TODAYS_MOVERS_CACHE["data"] = None
    return None, event_id, provenance


router = APIRouter()


@router.post("/analyze", dependencies=[Depends(_api.require_paid_analysis)])
def analyze(req: _api.AnalyzeRequest):
    """Classify, analyze via LLM, and run market check for one headline."""
    headline = normalize_headline(req.headline)
    effective_date = req.event_date or datetime.now().strftime("%Y-%m-%d")
    model = _api._active_model()

    if req.event_id is not None:
        cached = _api.load_event_by_id(req.event_id)
        if cached is not None:
            effective_date = cached.get("event_date") or effective_date
            return _api._build_cached_response(cached, headline, effective_date, force=req.force)
        # event_id was given but the row is missing or deleted — do
        # NOT fall through to the headline + 24h cache lookup, since
        # near-duplicate headlines within the TTL window could be
        # served instead of the requested row.  Re-analyze.
    else:
        cached = _api.find_cached_analysis(headline, event_date=effective_date, model=model)
        if cached is not None:
            return _api._build_cached_response(cached, headline, effective_date, force=req.force)

    # Cache miss.  Everything below this line costs money, so it runs only
    # on an explicit per-request confirmation.  Reading a saved analysis
    # stays free and never reaches here.
    if not req.confirm_paid:
        return _api._sanitize_floats(
            _paid_confirmation_required(headline, effective_date))

    # A candidate run must be reconstructable, so its basis is captured
    # BEFORE the paid call.  An unresolvable candidate fails closed here —
    # billing for an analysis whose basis cannot be recorded would produce
    # exactly the un-auditable row this slice exists to prevent.
    candidate_snapshot = None
    if req.candidate_id is not None:
        candidate_snapshot = _resolve_candidate_snapshot(req)
        if candidate_snapshot is None:
            return _api._sanitize_floats(
                _candidate_provenance_unavailable(headline, effective_date))

    stage = _api.classify_stage(headline)
    persistence = _api.classify_persistence(headline)

    # Pre-fetch macro context for prompt injection (uses TTL cache;
    # subsequent overlay calls below are instant cache hits).
    _macro_ctx = ""
    try:
        _macro_ctx = _api.build_macro_context_for_prompt()
    except Exception:
        _api._log.warning("macro context pre-fetch failed (analyze)", exc_info=True)

    # Sharpen mechanism wording + asset logic on import-shock /
    # reserve-stress / external-balance cases by appending the cached
    # country vulnerability backdrop when the headline clearly maps to
    # a country we have a profile for.  No-op otherwise.
    _macro_ctx = _enrich_macro_context_with_country(_macro_ctx, headline)

    analysis = _call_analyze_event(headline, stage, persistence,
                                    event_context=req.event_context or "",
                                    macro_context=_macro_ctx)

    if _is_mock_analysis(analysis):
        return _api._mock_failure_response(headline, analysis, effective_date)

    analysis["if_persists"] = _api._normalize_if_persists(analysis.get("if_persists"))
    analysis["currency_channel"] = _api._normalize_currency_channel(analysis.get("currency_channel"))

    mech_text = f"{analysis.get('what_changed', '')} {analysis.get('mechanism_summary', '')}"
    rates_for_overlays, stress_for_overlays = _run_pre_market_overlays(analysis, headline, mech_text, stage, persistence)

    # Post-LLM asset-selection discipline.  Runs BEFORE market_check so
    # broad-market indices, price benchmarks, foreign listings, and
    # hedge-only tickers never ship to the provider.  Shared with
    # /analyze/stream so both paths feed the same cleaned lists into
    # the agreement score.  See asset_selection.py for the tier rules.
    _ben_for_check, _los_for_check = _apply_asset_selection(analysis)

    mkt = _api.market_check(_ben_for_check, _los_for_check, event_date=req.event_date)

    _run_post_market_overlays(analysis, mkt, headline, mech_text, rates_for_overlays, stress_for_overlays, stage, event_date=req.event_date)

    persistence_error, analysis_event_id, provenance = _persist_with_provenance(
        req, headline, stage, persistence, analysis, mkt, effective_date,
        model, candidate_snapshot, _macro_ctx,
    )
    # Linkage runs only after BOTH the events row and its provenance are
    # committed — a candidate marked analyzed without a recorded basis is
    # exactly the misleading state this ordering prevents.
    candidate_link = _link_candidate_analysis(req, analysis_event_id)
    provenance_summary = _fresh_provenance_summary(
        provenance, analysis_event_id, candidate_link)

    age_classification = _api._classify_for_effective_date(effective_date, force=False)
    mkt_with_freshness = _api._augment_market_freshness(mkt, age_classification)

    return _api._sanitize_floats({
        "headline": headline, "stage": stage, "persistence": persistence,
        "analysis": analysis, "market": mkt_with_freshness,
        "freshness": _api._freshness_payload(age_classification),
        "is_mock": False, "event_date": effective_date,
        # Explicit persistence outcome — clients must never read a
        # clean 200 response as proof the row was saved.  ``True``
        # means ``save_event`` raised; ``persistence_error`` carries
        # the short reason string.
        "persistence_failed": persistence_error is not None,
        "persistence_error":  persistence_error,
        # The numeric events.id this run produced, and what happened to
        # the inbox candidate linkage.  ``None`` whenever the save failed
        # or the request carried no candidate identity — never inferred.
        "analysis_event_id": analysis_event_id,
        "candidate_link": candidate_link,
        "provenance": provenance_summary,
    })


@router.post("/analyze/stream", dependencies=[Depends(_api.require_paid_analysis)])
def analyze_stream(req: _api.AnalyzeRequest):
    """Progressive analysis via Server-Sent Events."""
    headline = normalize_headline(req.headline)
    effective_date = req.event_date or datetime.now().strftime("%Y-%m-%d")
    model = _api._active_model()
    _effective_date = [effective_date]

    def generate():
        if req.event_id is not None:
            by_id = _api.load_event_by_id(req.event_id)
            if by_id is not None:
                _effective_date[0] = by_id.get("event_date") or _effective_date[0]
                yield _api._sse_event("complete", _api._build_cached_response(by_id, headline, _effective_date[0], force=req.force))
                return
            # event_id given but row is missing — skip headline cache
            # lookup so a colliding near-duplicate isn't served.
        else:
            cached = _api.find_cached_analysis(headline, event_date=_effective_date[0], model=model)
            if cached is not None:
                yield _api._sse_event("complete", _api._build_cached_response(cached, headline, _effective_date[0], force=req.force))
                return

        # Cache miss — same explicit-confirmation gate as /analyze.  The
        # terminal frame carries the blocked status so a streaming client
        # sees a completed, honest stream rather than a truncated one.
        if not req.confirm_paid:
            yield _api._sse_event("complete", _api._sanitize_floats(
                _paid_confirmation_required(headline, _effective_date[0])))
            return

        # Same pre-provider capture as /analyze — see the counterpart there.
        candidate_snapshot = None
        if req.candidate_id is not None:
            candidate_snapshot = _resolve_candidate_snapshot(req)
            if candidate_snapshot is None:
                yield _api._sse_event("complete", _api._sanitize_floats(
                    _candidate_provenance_unavailable(
                        headline, _effective_date[0])))
                return

        stage = _api.classify_stage(headline)
        persistence = _api.classify_persistence(headline)
        yield _api._sse_event("classify", {"headline": headline, "stage": stage, "persistence": persistence})

        # Pre-fetch macro context for prompt injection (uses TTL cache).
        _macro_ctx = ""
        try:
            _macro_ctx = _api.build_macro_context_for_prompt()
        except Exception:
            _api._log.warning("macro context pre-fetch failed (stream)", exc_info=True)

        # Country vulnerability backdrop — attached only when the
        # headline resolves to a cached profile.  See _enrich_macro_context_with_country.
        _macro_ctx = _enrich_macro_context_with_country(_macro_ctx, headline)

        analysis = _call_analyze_event(headline, stage, persistence,
                                        event_context=req.event_context or "",
                                        macro_context=_macro_ctx)

        if _is_mock_analysis(analysis):
            yield _api._sse_event("complete", _api._mock_failure_response(headline, analysis, _effective_date[0]))
            return

        analysis["if_persists"] = _api._normalize_if_persists(analysis.get("if_persists"))
        analysis["currency_channel"] = _api._normalize_currency_channel(analysis.get("currency_channel"))
        mech_text = f"{analysis.get('what_changed', '')} {analysis.get('mechanism_summary', '')}"
        rates_for_overlays, stress_for_overlays = _run_pre_market_overlays(analysis, headline, mech_text, stage, persistence)
        # Post-LLM asset-selection discipline — runs BEFORE the
        # ``analysis`` SSE event so the streaming client sees the
        # cleaned ticker lists in the same payload it already consumes,
        # and BEFORE ``market_check`` so the provider never sees broad
        # indices / hedge ETFs / foreign listings.  Shared with
        # /analyze; see _apply_asset_selection for the contract.
        _ben_for_check, _los_for_check = _apply_asset_selection(analysis)
        yield _api._sse_event("analysis", _api._sanitize_floats({"analysis": analysis, "is_mock": False}))

        mkt = _api.market_check(_ben_for_check, _los_for_check, event_date=req.event_date)

        _run_post_market_overlays(analysis, mkt, headline, mech_text, rates_for_overlays, stress_for_overlays, stage, event_date=req.event_date)

        persistence_error, analysis_event_id, provenance = _persist_with_provenance(
            req, headline, stage, persistence, analysis, mkt, effective_date,
            model, candidate_snapshot, _macro_ctx,
        )
        candidate_link = _link_candidate_analysis(req, analysis_event_id)
        provenance_summary = _fresh_provenance_summary(
            provenance, analysis_event_id, candidate_link)
        age_classification = _api._classify_for_effective_date(effective_date, force=False)
        mkt_with_freshness = _api._augment_market_freshness(mkt, age_classification)

        yield _api._sse_event("complete", _api._sanitize_floats({
            "headline": headline, "stage": stage, "persistence": persistence,
            "analysis": analysis, "market": mkt_with_freshness,
            "freshness": _api._freshness_payload(age_classification),
            "is_mock": False, "event_date": effective_date,
            # Explicit persistence outcome — streaming clients must
            # never read a successful ``complete`` event as proof the
            # row was saved.  See the /analyze counterpart.
            "persistence_failed": persistence_error is not None,
            "persistence_error":  persistence_error,
            # See the /analyze counterpart — id and linkage outcome are
            # reported, never inferred from a clean terminal frame.
            "analysis_event_id": analysis_event_id,
            "candidate_link": candidate_link,
            "provenance": provenance_summary,
        }))

    return StreamingResponse(generate(), media_type="text/event-stream")
