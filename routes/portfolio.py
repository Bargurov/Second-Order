"""Route handler for GET /portfolio — ranked research portfolio."""

from fastapi import APIRouter, HTTPException, Query, Depends

from cohort_research import SCENARIO_PACKS, run_batch_research
from db import load_recent_events, load_event_by_id, dedup_events
import api as _api
from engine_phase_surface import decorate_compact as _decorate_compact
from low_information_gate import EVIDENCE_QUALITY_TIERS
from market_check_freshness import compute_staleness
from persistence_signal import classify_persistence_signal
from relevance_ranking import rank_with_diversity
from portfolio_flags import (
    PROOF_QUALITY_BUCKETS,
    QUEUE_IDS,
    classify_queues,
    portfolio_flags,
    proof_quality_bucket,
)
from family_inference import resolve_effective_family
from thesis_state import (
    THESIS_STATES,
    derive_thesis_state,
    derive_thesis_state_reason,
    derive_validation_rationale,
)
from validation_outcome import (
    _extract_primary_set,
    score_validation_outcome,
    score_weighted_evidence,
)

router = APIRouter()


def _validation_outcome(tickers: list) -> tuple[str, float | None]:
    """Return ``(label, support_ratio)`` using the shared majority-rule
    helper so ``/portfolio`` and ``/events`` cannot drift apart.

    Labels: ``"no_data"`` | ``"unresolved"`` | ``"validated"`` |
    ``"contradicted"``.  See ``validation_outcome.py``.
    """
    return score_validation_outcome(tickers)


def _portfolio_score(ev: dict) -> float:
    """Higher is better. Range roughly -3 to +8."""
    score = 0.0

    conf_map = {"high": 3.0, "medium": 2.0, "low": 1.0, "very_low": 0.0}
    score += conf_map.get(str(ev.get("confidence") or "").lower(), 0.0)

    tickers = ev.get("market_tickers") or []
    tags = [(t.get("direction_tag") or "") for t in tickers if isinstance(t, dict)]
    with_tag = [t for t in tags if t]
    if with_tag:
        score += 2.0
        supporting = sum(1 for t in with_tag if t.startswith("supports"))
        score += supporting / len(with_tag)

    rating_map = {"good": 2.0, "mixed": 0.5, "poor": -1.0}
    score += rating_map.get(str(ev.get("rating") or "").lower(), 0.0)

    revisits = ev.get("revisit_snapshots") or []
    score += min(len(revisits) * 0.5, 1.5)

    if ev.get("low_signal"):
        score -= 2.0

    return score


@router.get("/portfolio")
def get_portfolio(
    limit: int = Query(20, ge=1, le=50),
    family_decay: float = Query(
        0.70, ge=0.1, le=1.0,
        description=(
            "Per-family score multiplier applied to each additional "
            "event already picked from the same mechanism_family. "
            "1.0 disables diversity and falls back to pure relevance "
            "ranking; lower values broaden topic coverage."
        ),
    ),
    cluster_decay: float = Query(
        0.45, ge=0.1, le=1.0,
        description=(
            "Per-cluster score multiplier applied to each additional "
            "event sharing the same transmission-path signature "
            "(family + ordered channel tuple).  Strictly tighter "
            "than family_decay so near-identical mechanisms don't "
            "monopolise slots; ignored when family_decay=1.0."
        ),
    ),
    thesis_state: str | None = Query(
        None,
        description=(
            "Filter results to events matching the supplied "
            "``thesis_state``.  Must be one of the stored states."
        ),
    ),
    proof_quality: str | None = Query(
        None,
        description=(
            "Filter results to events whose proof-quality bucket "
            "matches.  Must be one of the stored buckets."
        ),
    ),
    low_information: bool | None = Query(
        None,
        description=(
            "``true`` → return only low-information studies; "
            "``false`` → exclude them; omit for no filter."
        ),
    ),
    queue: str | None = Query(
        None,
        description=(
            "Return only events that belong to the named research "
            "queue.  See portfolio_flags.QUEUE_IDS for the enum."
        ),
    ),
    mover_window: str | None = Query(
        None,
        pattern="^(today|weekly|persistent|market)$",
        description=(
            "Return only events currently active on the named mover "
            "surface.  Accepted values: today | weekly | persistent "
            "| market.  Uses already-cached mover slices; no new "
            "market fetches are issued."
        ),
    ),
    quality_tier: str | None = Query(
        None,
        description=(
            "Filter results to events whose engine quality_tier "
            "matches.  Closed enum: actionable | watch_only | "
            "low_information.  Uses the surfaced tier from "
            "``engine_phase_surface.decorate_compact``."
        ),
    ),
    tradable: bool | None = Query(
        None,
        description=(
            "``true`` → only events whose actionability_check.tradable "
            "is True; ``false`` → only events whose tradable is False; "
            "omit for no filter.  Reads the surfaced compact field."
        ),
    ),
    mechanism_subtype: str | None = Query(
        None,
        description=(
            "Filter results to events whose surfaced "
            "``mechanism_subtype`` matches the supplied id.  Open-ended "
            "(per-family registry in ``mechanism_family.FAMILY_SUBTYPES``); "
            "an unknown subtype simply yields zero results."
        ),
    ),
):
    """Return the top-N events ranked by market relevance, diversified.

    Ranking splits into two explicit axes so ``easy to validate`` no
    longer crowds out ``matters to markets``:

      * ``relevance.components.cross_asset_significance`` — how many
        channels moved and how hard (primary signal).
      * ``relevance.components.persistence`` — did the move hold?
      * ``relevance.components.validation`` — legacy confidence /
        rating / revisit signal, retained at reduced weight.

    A greedy diversity post-pass then applies two decay axes per
    prior pick: ``family_decay`` for mechanism-family repeats plus a
    tighter ``cluster_decay`` for near-identical transmission paths.
    One cluster can still own multiple slots when its scores
    genuinely beat the alternatives, but duplicate oil/war chains
    don't dominate by density alone.
    """
    # Validate filter enums up-front so typos surface as 400s rather
    # than silently returning empty results.
    if thesis_state is not None and thesis_state not in THESIS_STATES:
        raise HTTPException(
            400,
            f"thesis_state must be one of {list(THESIS_STATES)}",
        )
    if proof_quality is not None and proof_quality not in PROOF_QUALITY_BUCKETS:
        raise HTTPException(
            400,
            f"proof_quality must be one of {list(PROOF_QUALITY_BUCKETS)}",
        )
    if queue is not None and queue not in QUEUE_IDS:
        raise HTTPException(
            400,
            f"queue must be one of {list(QUEUE_IDS)}",
        )
    if quality_tier is not None and quality_tier not in EVIDENCE_QUALITY_TIERS:
        raise HTTPException(
            400,
            f"quality_tier must be one of {list(EVIDENCE_QUALITY_TIERS)}",
        )
    filters_active = (
        thesis_state is not None
        or proof_quality is not None
        or low_information is not None
        or queue is not None
        or mover_window is not None
        or quality_tier is not None
        or tradable is not None
        or mechanism_subtype is not None
    )

    # Load the already-cached mover slices once per request so the
    # mover_window filter + the mover_window_counts facet can be
    # answered without per-event recomputation.  One try/except so a
    # flaky slice doesn't sink the portfolio response.
    event_window_index: dict[int, list[str]] = {}
    try:
        from mover_context import MOVER_WINDOW_IDS, build_event_window_index
        from routes.movers import load_ui_slices_for_event_context
        event_window_index = build_event_window_index(
            load_ui_slices_for_event_context()
        )
    except Exception:
        from mover_context import MOVER_WINDOW_IDS
        event_window_index = {}

    events = dedup_events(load_recent_events(limit=200))

    # Archive-wide queue tally.  ``queue_counts`` is computed pre-
    # filter so the UI can size the "confirming now (4), watch
    # falsifiers (7), ..." facets regardless of the current filter.
    queue_counts: dict[str, int] = {q: 0 for q in QUEUE_IDS}

    # Archive-wide mover-window tally.  Same archive-wide convention
    # as ``queue_counts`` — counts reflect every candidate, not the
    # post-filter set, so the UI can size the "today (3), weekly (7),
    # …" facets regardless of the current filter.
    mover_window_counts: dict[str, int] = {w: 0 for w in MOVER_WINDOW_IDS}

    # Archive-wide quality_tier tally.  Same convention as
    # ``queue_counts`` / ``mover_window_counts`` — pre-filter so the
    # facet stays sized regardless of the current filter selection.
    quality_tier_counts: dict[str, int] = {t: 0 for t in EVIDENCE_QUALITY_TIERS}

    # Drop mock / empty-mechanism rows upstream so they don't pollute
    # the ranked list.  Also carries per-event context (staleness,
    # persistence signal, validation outcome) forward onto the ranked
    # entries.
    context_by_id: dict[int, dict] = {}
    candidates: list[dict] = []
    for ev in events:
        mechanism = ev.get("mechanism_summary") or ""
        if mechanism.startswith("[mock:") or not mechanism.strip():
            continue
        # Response-path family fallback: upgrade stored ``"none"`` rows
        # to a canonical family using the deterministic tiers in
        # ``family_inference``.  Works on the in-memory event dict only;
        # never writes back to the DB.
        ev["mechanism_family"] = resolve_effective_family(ev)
        tickers = ev.get("market_tickers") or []
        outcome, support_ratio = _validation_outcome(tickers)
        sig = compute_staleness(ev)
        flags = portfolio_flags(ev)
        weighted = score_weighted_evidence(
            tickers, explicit_primary=_extract_primary_set(ev),
        )
        persistence_sig = classify_persistence_signal(ev)
        _ts_payload = {
            **ev,
            "weighted_evidence":  weighted,
            "has_proof_set":      flags["has_proof_set"],
            "has_falsifiers":     flags["has_falsifiers"],
            "low_information":    flags["low_information"],
            "stale_signal":       sig["status"],
            "persistence_signal": persistence_sig,
        }
        ts_state = derive_thesis_state(_ts_payload)
        ts_reason = derive_thesis_state_reason(_ts_payload, state=ts_state)
        ts_validation_rationale = derive_validation_rationale(
            _ts_payload, state=ts_state,
        )
        pq_bucket = proof_quality_bucket({
            **ev,
            "weighted_evidence":  weighted,
        })
        queues = classify_queues({
            "thesis_state":     ts_state,
            "low_information":  flags["low_information"],
            "has_falsifiers":   flags["has_falsifiers"],
            "stale_signal":     sig["status"],
        })
        for q in queues:
            queue_counts[q] += 1
        # Active mover windows for this event — from the already-
        # cached mover slices.  Drives both the mover_window filter
        # and the archive-wide mover_window_counts facet below.
        active_windows = list(event_window_index.get(ev["id"]) or [])
        for w in active_windows:
            if w in mover_window_counts:
                mover_window_counts[w] += 1
        # Engine-phase compact surface — composed once here so the
        # filter pass below can branch on quality_tier / tradable /
        # mechanism_subtype without recomputing them per filter, and
        # the response builder can reuse the stashed dict instead of
        # invoking the composers a second time.
        compact = _decorate_compact(ev)
        _qt = compact.get("quality_tier")
        if _qt in quality_tier_counts:
            quality_tier_counts[_qt] += 1
        context_by_id[ev["id"]] = {
            "validation_outcome": outcome,
            "support_ratio":      support_ratio,
            "weighted_evidence":  weighted,
            "stale_signal":       sig["status"],
            "hours_since_check":  sig.get("hours_since_check"),
            "event_age_days":     sig.get("event_age_days"),
            "persistence_signal": persistence_sig,
            "has_proof_set":      flags["has_proof_set"],
            "has_falsifiers":     flags["has_falsifiers"],
            "low_information":    flags["low_information"],
            "thesis_state":       ts_state,
            "thesis_state_reason": ts_reason,
            "validation_rationale": ts_validation_rationale,
            "proof_quality":      pq_bucket,
            "queues":             queues,
            "active_mover_windows": active_windows,
            "compact":            compact,
        }
        candidates.append(ev)

    # Apply thesis-quality + queue filters BEFORE ranking so the
    # top-N returned genuinely matches the filter instead of
    # returning fewer-than-limit rows once filtering drops non-
    # matches.
    if filters_active:
        def _keeps(ev: dict) -> bool:
            ctx = context_by_id.get(ev["id"], {})
            if thesis_state is not None and ctx.get("thesis_state") != thesis_state:
                return False
            if proof_quality is not None and ctx.get("proof_quality") != proof_quality:
                return False
            if low_information is not None:
                if bool(ctx.get("low_information")) != bool(low_information):
                    return False
            if queue is not None and queue not in (ctx.get("queues") or []):
                return False
            if mover_window is not None and mover_window not in (
                ctx.get("active_mover_windows") or []
            ):
                return False
            compact = ctx.get("compact") or {}
            if quality_tier is not None and compact.get("quality_tier") != quality_tier:
                return False
            if tradable is not None:
                ac = compact.get("actionability_check") or {}
                if bool(ac.get("tradable", False)) != bool(tradable):
                    return False
            if mechanism_subtype is not None and compact.get("mechanism_subtype") != mechanism_subtype:
                return False
            return True
        candidates = [ev for ev in candidates if _keeps(ev)]

    ranked = rank_with_diversity(
        candidates, limit=limit,
        family_decay=family_decay,
        cluster_decay=cluster_decay,
    )

    entries: list[dict] = []
    for r in ranked:
        ev = r["event"]
        tickers = ev.get("market_tickers") or []
        ctx = context_by_id.get(ev["id"], {})
        compact = ctx.get("compact") or _decorate_compact(ev)
        entries.append({
            "id": ev["id"],
            "headline": ev.get("headline", ""),
            "event_date": ev.get("event_date"),
            "timestamp": ev.get("timestamp"),
            "stage": ev.get("stage"),
            "persistence": ev.get("persistence"),
            "mechanism_family": r["mechanism_family"],
            "mechanism_summary": ev.get("mechanism_summary") or "",
            "beneficiaries": ev.get("beneficiaries") or [],
            "losers": ev.get("losers") or [],
            "market_tickers": [
                {
                    "symbol": t.get("symbol"),
                    "role": t.get("role"),
                    "direction_tag": t.get("direction_tag"),
                    "return_5d": t.get("return_5d"),
                }
                for t in tickers
                if isinstance(t, dict)
            ],
            "confidence": ev.get("confidence"),
            "rating": ev.get("rating"),
            "revisit_snapshots": ev.get("revisit_snapshots") or [],
            "validation_outcome": ctx.get("validation_outcome"),
            "support_ratio":      ctx.get("support_ratio"),
            "weighted_evidence":  ctx.get("weighted_evidence"),
            "has_proof_set":      ctx.get("has_proof_set", False),
            "has_falsifiers":     ctx.get("has_falsifiers", False),
            "low_information":    ctx.get("low_information", False),
            "thesis_state":         ctx.get("thesis_state"),
            "thesis_state_reason":  ctx.get("thesis_state_reason"),
            "validation_rationale": ctx.get("validation_rationale"),
            "quality_tier":         compact["quality_tier"],
            "quality_warnings":     compact["quality_warnings"],
            "actionability_check":  compact["actionability_check"],
            "mechanism_subtype":    compact["mechanism_subtype"],
            "proof_quality":        ctx.get("proof_quality"),
            "queues":             list(ctx.get("queues") or []),
            "active_mover_windows": list(ctx.get("active_mover_windows") or []),
            "stale_signal":       ctx.get("stale_signal"),
            "hours_since_check":  ctx.get("hours_since_check"),
            "event_age_days":     ctx.get("event_age_days"),
            "persistence_signal": ctx.get("persistence_signal"),
            "relevance": {
                "overall_score":         r["overall_score"],
                "effective_score":       r["effective_score"],
                "components":            r["components"],
                "diversity_decay":       r["diversity_decay"],
                "family_rank_in_list":   r["family_rank_in_list"],
                "cluster_decay_applied": r["cluster_decay_applied"],
                "cluster_rank_in_list":  r["cluster_rank_in_list"],
                "rank":                  r["rank"],
            },
        })

    # Default response shape (no thesis-quality filters applied) stays
    # a bare list for backward compatibility with earlier clients.
    # When any filter param is set the response wraps the items +
    # summary counts so the caller can size UI facets without a
    # second request.
    if not filters_active:
        return _api._sanitize_floats(entries)

    ts_counts: dict[str, int] = {s: 0 for s in THESIS_STATES}
    pq_counts: dict[str, int] = {b: 0 for b in PROOF_QUALITY_BUCKETS}
    # tradable_counts is post-filter (rendered items only) — same
    # convention as ``thesis_state_counts`` / ``proof_quality_counts``.
    # String keys keep the JSON readable on the wire.
    tradable_counts: dict[str, int] = {"true": 0, "false": 0}
    # mechanism_subtype_counts is post-filter and open-keyed: only
    # subtypes that actually appear in the rendered items get a row.
    # Pre-filling the global registry would explode the response.
    mechanism_subtype_counts: dict[str, int] = {}
    for e in entries:
        if e.get("thesis_state") in ts_counts:
            ts_counts[e["thesis_state"]] += 1
        if e.get("proof_quality") in pq_counts:
            pq_counts[e["proof_quality"]] += 1
        ac = e.get("actionability_check") or {}
        if isinstance(ac, dict) and "tradable" in ac:
            tradable_counts["true" if ac.get("tradable") else "false"] += 1
        sub = e.get("mechanism_subtype")
        if isinstance(sub, str) and sub:
            mechanism_subtype_counts[sub] = mechanism_subtype_counts.get(sub, 0) + 1

    return _api._sanitize_floats({
        "items":                entries,
        "thesis_state_counts":  ts_counts,
        "proof_quality_counts": pq_counts,
        # queue_counts is archive-wide (pre-filter) so the UI can
        # always show the size of every research queue regardless of
        # which filter is currently applied.
        "queue_counts":         queue_counts,
        # mover_window_counts — archive-wide, pre-filter counts per
        # mover surface so facets stay sizeable across filter state.
        "mover_window_counts":  mover_window_counts,
        # quality_tier_counts — archive-wide (pre-filter), every tier
        # in the closed enum carries a row.  Same convention as
        # ``queue_counts`` / ``mover_window_counts``.
        "quality_tier_counts":  quality_tier_counts,
        # tradable_counts / mechanism_subtype_counts — post-filter,
        # mirror ``thesis_state_counts`` / ``proof_quality_counts``.
        # Tradable carries both string keys; subtype is open-dict.
        "tradable_counts":         tradable_counts,
        "mechanism_subtype_counts": mechanism_subtype_counts,
    })


@router.get("/portfolio/cohort-research")
def get_cohort_research(limit: int = Query(500, ge=50, le=1000)):
    """Return batch research across every scenario pack.

    Loads the recent archive, runs ``run_batch_research`` for each
    named scenario pack, and returns a compact per-pack summary so the
    Portfolio research tab can surface "how do tariff cycles usually
    reprice?" without the caller orchestrating multiple queries.
    """
    events = dedup_events(load_recent_events(limit=limit))
    packs: list[dict] = []
    for pack_name in SCENARIO_PACKS:
        report = run_batch_research(
            events,
            scenario_pack=pack_name,
            cohort_label=pack_name,
        )
        packs.append({
            "pack":             pack_name,
            "families":         list(SCENARIO_PACKS[pack_name]),
            "size":             report["size"],
            "confidence_basis": report["confidence_basis"],
            "persistence":      report["persistence"],
            "repricing_path":   report["repricing_path"],
            "falsification":    report["falsification"],
            "summary":          report["summary"],
            "rationale":        report["rationale"],
        })
    return _api._sanitize_floats({
        "packs":        packs,
        "total_events": len(events),
    })


@router.get("/portfolio/cross-event-studies")
def get_cross_event_studies(limit: int = Query(500, ge=50, le=1000)):
    """Return archive-native cross-event correlation studies.

    Wraps ``cross_event_studies.compute_cross_event_studies`` over the
    recent event archive so the Portfolio research tab can surface
    family co-occurrence, sector clusters, transmission-path shapes,
    and family × sector hit-rate cross-cuts without the caller
    rescanning the table.
    """
    from cross_event_studies import compute_cross_event_studies
    events = dedup_events(load_recent_events(limit=limit))
    studies = compute_cross_event_studies(events)
    return _api._sanitize_floats(studies)


@router.get("/portfolio/cohort-comparison")
def get_cohort_comparison(
    a: str = Query(..., description="Scenario pack name for cohort A"),
    b: str = Query(..., description="Scenario pack name for cohort B"),
    limit: int = Query(500, ge=50, le=1000),
):
    """Run batch research for two scenario packs and diff them.

    Both ``a`` and ``b`` must be keys of ``SCENARIO_PACKS``.  Returns
    the full output of ``cohort_comparison.compare_cohorts`` so the
    Portfolio research tab can answer "how did tariff cycles differ
    across scenarios?"-style questions with one request.
    """
    from cohort_comparison import compare_cohorts
    if a not in SCENARIO_PACKS or b not in SCENARIO_PACKS:
        raise HTTPException(400, "Unknown scenario pack.")
    events = dedup_events(load_recent_events(limit=limit))
    report_a = run_batch_research(events, scenario_pack=a, cohort_label=a)
    report_b = run_batch_research(events, scenario_pack=b, cohort_label=b)
    comparison = compare_cohorts(report_a, report_b)
    return _api._sanitize_floats({
        "comparison":       comparison,
        "a_report":         report_a,
        "b_report":         report_b,
        "available_packs":  list(SCENARIO_PACKS.keys()),
    })


@router.get("/portfolio/event-graph")
def get_event_graph(limit: int = Query(500, ge=50, le=1000)):
    """Return the cross-event cascade / spillover graph.

    Wraps ``event_graph.build_event_graph`` over the recent archive so
    the research surface can navigate parent → child spillovers
    (shared mechanism family, transmission-path shape, asset / sector
    overlap) with decay-adjusted weights.  Every edge carries
    component provenance so the UI can render why the link exists.
    """
    from event_graph import build_event_graph
    events = dedup_events(load_recent_events(limit=limit))
    graph = build_event_graph(events)
    return _api._sanitize_floats(graph)


@router.get("/portfolio/archive-drift")
def get_archive_drift(limit: int = Query(500, ge=50, le=1000)):
    """Return theme-trend + regime-drift summaries over rolling windows.

    Wraps ``archive_drift.build_archive_drift`` over the recent event
    archive so the Portfolio research tab can surface how the macro
    structure of the archive is shifting (which families are rising,
    which regime axes have flipped).
    """
    from archive_drift import build_archive_drift
    events = dedup_events(load_recent_events(limit=limit))
    drift = build_archive_drift(events)
    return _api._sanitize_floats(drift)


@router.post("/portfolio/simulate")
def simulate_portfolio_endpoint(req: _api.SimulatePortfolioRequest):
    from portfolio_simulator import simulate_portfolio
    events = [load_event_by_id(eid) for eid in req.event_ids]
    events = [e for e in events if e]
    if not events:
        raise HTTPException(404, "No events found for the given IDs.")
    result = simulate_portfolio(
        events,
        horizon=req.horizon,
        include_shorts=req.include_shorts,
        direction_filter=req.direction_filter,
    )
    return _api._sanitize_floats(result)


# ---------------------------------------------------------------------------
# Saved study views — persistent, deterministic research-workflow configs
# (cohort comparison / correlation study / scenario pack / cascade view).
# Storage lives in ``saved_studies.py``; these routes are the HTTP surface
# the Portfolio page uses to save, list, reopen, and delete views.  None
# of these execute the study — the caller re-runs the matching composer
# with the returned config so the numbers are always against today's tape.
# ---------------------------------------------------------------------------


@router.get("/portfolio/saved-studies")
def list_saved_studies(study_type: str | None = Query(None)):
    import saved_studies as _ss
    try:
        rows = _ss.list_studies(study_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _api._sanitize_floats({"studies": rows})


@router.get("/portfolio/saved-studies/{study_id}")
def get_saved_study(study_id: int):
    import saved_studies as _ss
    row = _ss.load_study(study_id)
    if row is None:
        raise HTTPException(404, f"Saved study {study_id} not found.")
    return _api._sanitize_floats(row)


@router.post("/portfolio/saved-studies", dependencies=[Depends(_api.require_admin_token)])
def save_saved_study(req: _api.SavedStudyCreate):
    import saved_studies as _ss
    try:
        row = _ss.save_study(
            req.study_type, req.name, req.config,
            description=req.description, overwrite=req.overwrite,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _api._sanitize_floats(row)


@router.patch("/portfolio/saved-studies/{study_id}", dependencies=[Depends(_api.require_admin_token)])
def update_saved_study(study_id: int, req: _api.SavedStudyUpdate):
    """Update a saved study by id.

    Uses ``saved_studies.update_study`` so a rename rewrites the same
    row rather than creating a duplicate under the new name — the
    save-study ``(study_type, name)`` lookup in ``save_study`` would
    INSERT on a miss otherwise.
    """
    import saved_studies as _ss
    kwargs: dict = {}
    if req.name is not None:
        kwargs["name"] = req.name
    if req.description is not None:
        kwargs["description"] = req.description
    if req.config is not None:
        kwargs["config"] = req.config
    try:
        row = _ss.update_study(study_id, **kwargs)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if row is None:
        raise HTTPException(404, f"Saved study {study_id} not found.")
    return _api._sanitize_floats(row)


@router.delete("/portfolio/saved-studies/{study_id}", dependencies=[Depends(_api.require_admin_token)])
def delete_saved_study(study_id: int):
    import saved_studies as _ss
    removed = _ss.delete_study(study_id)
    if not removed:
        raise HTTPException(404, f"Saved study {study_id} not found.")
    return {"deleted": True, "id": study_id}


@router.post("/portfolio/research-export")
def research_export(req: _api.ResearchExportRequest):
    """Replay saved + inline studies and return a portable bundle.

    Accepts any mix of ``saved_study_ids`` (loaded via
    ``saved_studies.load_study``) and ``studies`` (inline specs).
    Every request replays against the live archive so the numbers are
    current.  ``format="markdown"`` returns a text/markdown artifact;
    ``format="json"`` returns the full bundle dict.
    """
    import saved_studies as _ss
    from fastapi.responses import Response
    from research_export import build_research_bundle, format_research_markdown

    studies: list[dict] = []
    for sid in req.saved_study_ids or []:
        row = _ss.load_study(sid)
        if row is None:
            raise HTTPException(404, f"Saved study {sid} not found.")
        studies.append({
            "id":          row["id"],
            "name":        row["name"],
            "description": row.get("description") or "",
            "study_type":  row["study_type"],
            "config":      row["config"],
        })
    for inline in req.studies or []:
        studies.append({
            "name":        inline.name,
            "description": inline.description or "",
            "study_type":  inline.study_type,
            "config":      inline.config,
        })
    if not studies:
        raise HTTPException(
            400,
            "Provide at least one saved_study_ids entry or inline study.",
        )

    events = dedup_events(load_recent_events(limit=req.limit))
    bundle = build_research_bundle(events, studies)
    bundle = _api._sanitize_floats(bundle)

    if req.format == "markdown":
        body = format_research_markdown(bundle)
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition":
                    'attachment; filename="research_export.md"',
            },
        )
    return bundle
