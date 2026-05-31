"""Diagnostics routes — zero-cost introspection over the
headline_registry lifecycle.  See
docs/superpowers/specs/2026-05-03-headline-registry-design.md.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query, Request

import api as _api
from auto_backfill_config import load_auto_backfill_config
from auto_backfill_ledger import AutoBackfillLedger
from auto_backfill_runner import run_auto_backfill_dry_run
from auto_backfill_state import AutoBackfillState
from headline_registry import compose_diagnostics
from reaction_profile_hydration import hydrate_per_ticker_profile
from validation_status import VALID_STATUSES, score_validation_status

router = APIRouter()


@router.get("/registry/diagnostics")
def registry_diagnostics(
    candidates_limit: int = Query(50, ge=1, le=500),
    recent_hours: int = Query(
        24, ge=1, le=720,
        description=(
            "Window (hours) for the ``analyzed_recent`` and "
            "``surfaced_recent`` counts.  Defaults to 24h to match the "
            "frozen ``expired_count_24h`` field's semantics."
        ),
    ),
):
    """Pure-SQL view over headline_registry.  Zero LLM cost.

    Preserves the legacy fields (``state_counts``, ``skip_reason_counts``,
    ``last_analyzed_at``, ``expired_count_24h``,
    ``eligible_unanalyzed_candidates``) and adds the demo-readiness
    block (``counts.eligible_unanalyzed``, ``counts.analyzed_recent``,
    ``counts.surfaced_recent``, ``counts.expired_low_impact``) plus
    ``last_surfaced_at`` at the top level.  Read-only — never analyzes
    or mutates registry rows.
    """
    return compose_diagnostics(
        candidates_limit=candidates_limit,
        recent_hours=recent_hours,
    )


@router.get("/registry/candidate-queue")
def registry_candidate_queue(
    limit: int = Query(25, ge=1, le=200),
    since_hours: int = Query(
        72, ge=1, le=720,
        description=(
            "Recency window (hours) for cluster eligibility.  Mirrors the "
            "``since_hours`` filter on ``/movers/backfill-preview`` so "
            "the queue reflects the same universe a paid run would see."
        ),
    ),
    include_low_signal: bool = Query(
        False,
        description=(
            "When true, low-signal clusters and headlines that fail the "
            "relevance gate are admitted.  Mirrors the backfill flag of "
            "the same name."
        ),
    ),
):
    """Read-only queue of unanalyzed preview candidates, ranked.

    Pure read of in-memory + SQLite state — no LLM call, no
    ``yfinance`` fetch, no persistence write.  Reuses
    ``routes.movers``'s preview helpers (cluster filter, scorer,
    label/explanation composers) plus the headline-registry lookup so
    the queue stays byte-aligned with what the preview would emit.

    Items: clusters whose registry state is unanalyzed (``seen`` /
    ``eligible`` / not-yet-registered).  ``registry_state`` and
    ``skip_reason`` per item carry the registry's current view so the
    operator sees prior skip reasons (e.g., ``llm_budget_exhausted``)
    on rows that survived an earlier paid run.

    Counts are aggregated over clusters that passed the recency +
    relevance pre-filter:
      * ``eligible``           — items in the queue.
      * ``already_analyzed``   — registry state in
        ``{analyzed, market_checked, surfaced}``.
      * ``expired_low_impact`` — registry state ``expired_low_impact``.
      * ``skipped``            — sum of the two above.
    """
    # Late imports — keep diagnostics' import-time surface light and
    # prevent a circular import path through routes.movers at startup.
    from routes.movers import (
        _cached_news_payload,
        _cluster_event_date,
        _cluster_has_asset_terms,
        _cluster_headline,
        _cluster_is_recent,
        _hr_dedup_key,
        _headline_is_market_relevant,
        _rank_explanation,
        _registry_state_for_title_key,
        _score_cluster_for_preview,
        _skip_reason_label,
    )

    payload, source = _cached_news_payload()
    raw_clusters = (payload or {}).get("clusters") or []
    since_dt = (
        datetime.now() - timedelta(hours=since_hours)
        if since_hours and since_hours > 0 else None
    )

    counts = {
        "eligible":           0,
        "skipped":            0,
        "already_analyzed":   0,
        "expired_low_impact": 0,
    }

    # Pre-filter: same recency / relevance / low_signal gates the
    # backfill-preview applies, so the queue counts reflect the same
    # working set a paid run would consider.
    eligible_clusters: list[dict] = []
    for cluster in raw_clusters:
        if not isinstance(cluster, dict):
            continue
        if not _cluster_is_recent(cluster, since=since_dt):
            continue
        headline = _cluster_headline(cluster)
        if not headline:
            continue
        if cluster.get("low_signal") and not include_low_signal:
            continue
        if (
            not include_low_signal
            and not _headline_is_market_relevant(headline)
        ):
            continue
        eligible_clusters.append(cluster)

    cluster_scores: list[tuple[dict, float, dict]] = []
    for cluster in eligible_clusters:
        score, factors = _score_cluster_for_preview(cluster)
        cluster_scores.append((cluster, score, factors))
    cluster_scores.sort(
        key=lambda triple: (
            triple[1],
            int(triple[0].get("source_count") or 0),
            1 if _cluster_has_asset_terms(triple[0]) else 0,
        ),
        reverse=True,
    )

    items: list[dict] = []
    for cluster, rank_score, rank_factors in cluster_scores:
        headline = _cluster_headline(cluster)
        title_key = _hr_dedup_key(headline)
        registry_state, _eid = _registry_state_for_title_key(title_key)

        if registry_state in ("analyzed", "market_checked", "surfaced"):
            counts["already_analyzed"] += 1
            counts["skipped"] += 1
            continue
        if registry_state == "expired_low_impact":
            counts["expired_low_impact"] += 1
            counts["skipped"] += 1
            continue

        # Surface the registry's last_skip_reason (e.g.,
        # ``llm_budget_exhausted`` from a prior partial run) so the
        # operator can tell why an actionable cluster hasn't been
        # picked up yet.  Pulled lazily; missing rows return None.
        last_skip_reason = _last_skip_reason_for_title_key(title_key)
        counts["eligible"] += 1
        if len(items) >= limit:
            continue
        items.append({
            "headline":          headline,
            "source_count":      int(cluster.get("source_count") or 0),
            "published_at":      str(cluster.get("published_at") or "") or None,
            "event_date":        _cluster_event_date(cluster),
            "registry_state":    registry_state,
            "skip_reason":       last_skip_reason,
            "skip_reason_label": _skip_reason_label(last_skip_reason),
            "rank_score":        round(float(rank_score), 3),
            "rank_factors":      rank_factors,
            "rank_explanation":  _rank_explanation(rank_factors),
        })

    return _api._sanitize_floats({
        "items": items,
        "counts": counts,
        "filters": {
            "limit":              limit,
            "since_hours":        since_hours,
            "include_low_signal": include_low_signal,
        },
        "news_source": source,
    })


def _last_skip_reason_for_title_key(title_key: str) -> str | None:
    """Return the most recent ``last_skip_reason`` across all registry
    rows that share ``title_key``.  Multiple sources can register
    duplicate headlines; the queue surfaces the freshest skip
    annotation so an operator sees the latest reason.  Pure read; no
    writes, no LLM, no provider calls.
    """
    import sqlite3
    import db as _db
    if not _db._db_ready:
        return None
    try:
        with _db.connect_db() as conn:
            row = conn.execute(
                "SELECT last_skip_reason "
                "FROM headline_registry "
                "WHERE title_key = ? AND last_skip_reason IS NOT NULL "
                "ORDER BY last_seen_at DESC "
                "LIMIT 1",
                (title_key,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row and row[0] else None


@router.get("/diagnostics/data-quality")
def data_quality_summary():
    """Compact zero-cost data-quality view.

    Skeleton: composes already-existing read-only helpers into a
    single small payload the operator can poll without paying for any
    LLM, market_check, yfinance, or persistence work.  Each top-level
    block carries an ``available`` flag so a partial failure (a helper
    raising, a missing dependency) leaves the rest of the response
    intact — consumers branch on ``available`` rather than on the
    presence of the block.

    Blocks:
      * ``registry_counts``  — registry-lifecycle demo-readiness counts
        plus the skip-reason histogram, sourced from ``compose_diagnostics``.
      * ``archive_counts``   — total saved events + max event id.
      * ``snapshot_freshness`` — ``{total, fresh, stale, unavailable}``
        from the warm SnapshotStore (no refresh).
      * ``candidate_queue_counts`` — same eligible / skipped / already-
        analyzed / expired-low-impact counts the registry candidate-
        queue endpoint emits, recomputed from the cached news payload
        without any provider call.
      * ``latest_analyzed_at`` — most recent registry ``analyzed_at``
        timestamp, or None.
    """
    out: dict = {
        "registry_counts":        {"available": False},
        "archive_counts":         {"available": False},
        "snapshot_freshness":     {"available": False},
        "candidate_queue_counts": {"available": False},
        "latest_analyzed_at":     None,
    }

    diag: dict = {}
    try:
        diag = compose_diagnostics(candidates_limit=1, recent_hours=24)
    except Exception:
        diag = {}
    if diag:
        out["registry_counts"] = {
            "available":          True,
            "counts":             diag.get("counts", {}),
            "state_counts":       diag.get("state_counts", {}),
            "skip_reason_counts": diag.get("skip_reason_counts", {}),
            "last_surfaced_at":   diag.get("last_surfaced_at"),
            "expired_count_24h":  diag.get("expired_count_24h", 0),
        }
        out["latest_analyzed_at"] = diag.get("last_analyzed_at")

    try:
        from db import get_events_fingerprint
        count, max_id = get_events_fingerprint()
        out["archive_counts"] = {
            "available":   True,
            "total":       int(count),
            "max_id":      int(max_id),
        }
    except Exception:
        pass

    try:
        from market_snapshots import get_all_snapshots
        from market_context import _summarize_snapshots
        snaps = get_all_snapshots() or []
        # ``_summarize_snapshots`` accepts dict rows; coerce dataclass
        # rows so the helper stays simple.
        rows = []
        for s in snaps:
            if isinstance(s, dict):
                rows.append(s)
            elif hasattr(s, "to_dict"):
                try:
                    rows.append(s.to_dict())
                except Exception:
                    continue
        meta = _summarize_snapshots(rows)
        out["snapshot_freshness"] = {"available": True, **meta}
    except Exception:
        pass

    try:
        out["candidate_queue_counts"] = _candidate_queue_counts()
    except Exception:
        pass

    return _api._sanitize_floats(out)


def _candidate_queue_counts() -> dict:
    """Mirror the counts ``GET /registry/candidate-queue`` emits without
    re-fetching news.  Pure read of the in-memory news payload + the
    registry; no LLM, no market_check, no provider call.  Returns
    ``{"available": False}`` when the news cache or registry helpers
    are unavailable so the partial-availability contract holds.
    """
    try:
        from datetime import datetime, timedelta
        from routes.movers import (
            _cached_news_payload,
            _cluster_headline,
            _cluster_is_recent,
            _hr_dedup_key,
            _headline_is_market_relevant,
            _registry_state_for_title_key,
        )
    except Exception:
        return {"available": False}

    payload, _source = _cached_news_payload()
    raw_clusters = (payload or {}).get("clusters") or []
    since_dt = datetime.now() - timedelta(hours=72)

    counts = {
        "eligible":           0,
        "skipped":            0,
        "already_analyzed":   0,
        "expired_low_impact": 0,
    }

    for cluster in raw_clusters:
        if not isinstance(cluster, dict):
            continue
        if not _cluster_is_recent(cluster, since=since_dt):
            continue
        headline = _cluster_headline(cluster)
        if not headline:
            continue
        if cluster.get("low_signal"):
            continue
        if not _headline_is_market_relevant(headline):
            continue

        state, _eid = _registry_state_for_title_key(_hr_dedup_key(headline))
        if state in ("analyzed", "market_checked", "surfaced"):
            counts["already_analyzed"] += 1
            counts["skipped"] += 1
        elif state == "expired_low_impact":
            counts["expired_low_impact"] += 1
            counts["skipped"] += 1
        else:
            counts["eligible"] += 1

    return {"available": True, **counts}


@router.get("/diagnostics/config-health")
def config_health():
    """Operator-readable cost/security config snapshot.

    Returns booleans, integer caps, and a coarse ``present`` flag for
    each provider key — never the key text itself.  Pure read of env
    state via the ``routes.movers`` helpers; no LLM call, no provider
    request, no DB write.

    Top-level shape:
      * ``paid_analysis_enabled``      — ``ENABLE_PAID_ANALYSIS`` flag.
      * ``backfill_dry_run_default``   — default dry-run mode for
        ``/movers/backfill-recent`` when the request omits ``dry_run``.
      * ``max_backfill_llm_calls``     — server-side cap.
      * ``anthropic_key_present``      — bool only; no key bytes leaked.
      * ``openai_key_present``         — bool only.
      * ``warnings``                   — list of operator-actionable
        config-risk strings (paid+no-cap, paid+no-key, etc.).  Empty
        list = config looks safe.
    """
    from routes.movers import (
        _backfill_dry_run_default,
        _llm_available,
        _max_backfill_llm_calls,
        _paid_analysis_enabled,
    )

    paid_enabled  = bool(_paid_analysis_enabled())
    dry_run_def   = bool(_backfill_dry_run_default())
    max_calls     = int(_max_backfill_llm_calls())
    anthropic_ok  = bool(_llm_available("anthropic"))
    openai_ok     = bool(_llm_available("openai"))

    warnings: list[str] = []
    if paid_enabled and max_calls <= 0:
        warnings.append(
            "paid_analysis_enabled=true but max_backfill_llm_calls=0 — "
            "paid backfill cannot spend; either lift the cap or "
            "disable paid analysis."
        )
    if paid_enabled and not dry_run_def and max_calls > 5:
        warnings.append(
            f"paid_analysis_enabled=true with backfill_dry_run_default=false "
            f"and max_backfill_llm_calls={max_calls} (>5) — a stray request "
            f"could spend up to {max_calls} LLM calls. Consider lowering "
            f"the cap or re-enabling the dry-run default."
        )
    if paid_enabled and not (anthropic_ok or openai_ok):
        warnings.append(
            "paid_analysis_enabled=true but no provider API key is "
            "present — paid invocations will fail before any work is "
            "done.  Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or "
            "disable paid analysis."
        )

    return {
        "paid_analysis_enabled":     paid_enabled,
        "backfill_dry_run_default":  dry_run_def,
        "max_backfill_llm_calls":    max_calls,
        "anthropic_key_present":     anthropic_ok,
        "openai_key_present":        openai_ok,
        "warnings":                  warnings,
    }


@router.get("/diagnostics/archive-stats")
def archive_stats():
    """Compact zero-cost archive aggregates for Phase 1 validation planning.

    Each block carries an ``available`` flag so partial failures stay
    isolated — consumers branch on ``available`` rather than presence.

    Pure read.  No LLM, no yfinance, no market_check, no provider call,
    no DB write.  Deliberately does not depend on ``validation_status``
    while that wiring lands separately.
    """
    out: dict = {
        "total_events":            {"available": False},
        "events_with_tickers":     {"available": False},
        "events_with_returns":     {"available": False},
        "events_by_stage":         {"available": False},
        "events_by_persistence":   {"available": False},
        "events_by_thesis_state":  {"available": False},
        "market_checked_count":    {"available": False},
        "latest_event_timestamp":  None,
    }

    try:
        from db import get_events_fingerprint
        count, _max_id = get_events_fingerprint()
        out["total_events"] = {"available": True, "count": int(count)}
    except Exception:
        pass

    try:
        agg = _compute_archive_aggregates()
        for key, value in agg.items():
            out[key] = value
    except Exception:
        pass

    return _api._sanitize_floats(out)


def _compute_archive_aggregates() -> dict:
    """Single-pass aggregator over the events archive.

    Returned dict mirrors the archive-stats blocks the aggregator owns
    (everything except ``total_events``).  Each block carries
    ``available`` (or, for ``latest_event_timestamp``, the ISO-8601
    string or ``None``).  Pure read; never raises — structural
    failures collapse to the unavailable shape.
    """
    blocks: dict = {
        "events_with_tickers":    {"available": False},
        "events_with_returns":    {"available": False},
        "events_by_stage":        {"available": False},
        "events_by_persistence":  {"available": False},
        "events_by_thesis_state": {"available": False},
        "market_checked_count":   {"available": False},
        "latest_event_timestamp": None,
    }

    try:
        import sqlite3
        import db as _db
        if not _db._db_ready:
            return blocks
        with _db.connect_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM events").fetchall()
    except Exception:
        return blocks

    decoded: list[dict] = []
    by_stage:       dict[str, int] = {}
    by_persistence: dict[str, int] = {}
    with_tickers   = 0
    with_returns   = 0
    market_checked = 0
    latest_ts: str | None = None

    for row in rows:
        try:
            event = _db._decode_event_row(row)
        except Exception:
            event = dict(row)
        decoded.append(event)

        stage = (event.get("stage") or "").strip() or "unknown"
        by_stage[stage] = by_stage.get(stage, 0) + 1

        persistence = (event.get("persistence") or "").strip() or "unknown"
        by_persistence[persistence] = by_persistence.get(persistence, 0) + 1

        tickers = event.get("market_tickers") or []
        if isinstance(tickers, list) and len(tickers) > 0:
            with_tickers += 1
            if any(_ticker_has_return(t) for t in tickers):
                with_returns += 1

        mc = event.get("last_market_check_at")
        if isinstance(mc, str) and mc.strip():
            market_checked += 1

        ts = event.get("timestamp")
        if isinstance(ts, str) and ts and (latest_ts is None or ts > latest_ts):
            latest_ts = ts

    blocks["events_by_stage"]        = {"available": True, "counts": by_stage}
    blocks["events_by_persistence"]  = {"available": True, "counts": by_persistence}
    blocks["events_with_tickers"]    = {"available": True, "count": with_tickers}
    blocks["events_with_returns"]    = {"available": True, "count": with_returns}
    blocks["market_checked_count"]   = {"available": True, "count": market_checked}
    blocks["latest_event_timestamp"] = latest_ts

    try:
        from thesis_state import derive_thesis_state
        ts_counts: dict[str, int] = {}
        for event in decoded:
            # Curated-intake stubs are kept in the stage / persistence
            # inventory histograms above but carry no thesis to classify —
            # exclude them from the outcome (thesis-state) block.
            stage = (event.get("stage") or "").strip()
            if stage in _db.NON_ANALYSIS_STAGES:
                continue
            try:
                state = derive_thesis_state(event)
            except Exception:
                continue
            ts_counts[state] = ts_counts.get(state, 0) + 1
        blocks["events_by_thesis_state"] = {
            "available": True, "counts": ts_counts,
        }
    except Exception:
        pass

    return blocks


def _ticker_has_return(ticker) -> bool:
    """True when the ticker dict carries at least one numeric return field."""
    if not isinstance(ticker, dict):
        return False
    for key in ("return_1d", "return_5d", "return_20d"):
        v = ticker.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return True
    return False


@router.get("/diagnostics/validation-status-stats")
def validation_status_stats():
    """Archive-aggregate counts of the four-label validation status.

    Pure read.  No LLM, no yfinance, no market_check, no provider call,
    no DB write.  Calls ``validation_status.score_validation_status`` on
    each archived event and aggregates by status + reason category.

    Single top-level ``available`` flag — when false, every numeric
    field is zeroed and ``latest_event_timestamp`` is null, so consumers
    can render the panel without branching on field presence.
    """
    try:
        return _api._sanitize_floats(_compute_validation_status_stats())
    except Exception:
        return _api._sanitize_floats(_validation_status_unavailable())


def _validation_status_unavailable() -> dict:
    """Stable empty shape returned when the aggregator cannot run."""
    return {
        "available":              False,
        "total_events":           0,
        "counts_by_status": {
            "validated":    0,
            "contradicted": 0,
            "unresolved":   0,
            "pending":      0,
        },
        "counts_by_reason":       {},
        "pending_count":          0,
        "unresolved_count":       0,
        "curated_intake_excluded_count": 0,
        "latest_event_timestamp": None,
    }


def _compute_validation_status_stats() -> dict:
    """Single-pass aggregator scoring every archived event.

    Per-event scoring failures are skipped (the row contributes to
    ``total_events`` and ``latest_event_timestamp`` but not to status /
    reason counts) so a single bad row never breaks the aggregate.
    Curated-intake stubs (stage in ``db.NON_ANALYSIS_STAGES``) carry no
    thesis to validate; they are excluded from ``total_events`` and every
    status / reason bucket and disclosed via ``curated_intake_excluded_count``
    so they are never silently hidden.  Structural failures (DB unreachable,
    import error) raise so the outer route handler can flip ``available`` to
    ``False``.
    """
    import sqlite3
    import db as _db
    from validation_status import VALID_STATUSES, score_validation_status

    if not _db._db_ready:
        return _validation_status_unavailable()

    with _db.connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM events").fetchall()

    counts_by_status: dict[str, int] = {s: 0 for s in VALID_STATUSES}
    counts_by_reason: dict[str, int] = {}
    latest_ts: str | None = None
    total = 0
    curated_intake_excluded = 0

    for row in rows:
        try:
            event = _db._decode_event_row(row)
        except Exception:
            event = dict(row)

        # Curated-intake stubs are real archived rows with no thesis to
        # validate; exclude them from the denominator and every bucket.
        stage = (event.get("stage") or "").strip()
        if stage in _db.NON_ANALYSIS_STAGES:
            curated_intake_excluded += 1
            continue

        total += 1

        ts = event.get("timestamp")
        if isinstance(ts, str) and ts and (latest_ts is None or ts > latest_ts):
            latest_ts = ts

        try:
            scored = score_validation_status(event)
        except Exception:
            continue

        status = scored.get("status") if isinstance(scored, dict) else None
        if status in counts_by_status:
            counts_by_status[status] += 1

        reason = scored.get("reason") if isinstance(scored, dict) else None
        category = _reason_category(reason, status)
        counts_by_reason[category] = counts_by_reason.get(category, 0) + 1

    return {
        "available":              True,
        "total_events":           total,
        "counts_by_status":       counts_by_status,
        "counts_by_reason":       counts_by_reason,
        "pending_count":          counts_by_status["pending"],
        "unresolved_count":       counts_by_status["unresolved"],
        "curated_intake_excluded_count": curated_intake_excluded,
        "latest_event_timestamp": latest_ts,
    }


def _reason_category(reason, status) -> str:
    """Bucket a free-form ``score_validation_status`` reason into a
    stable category so the ``counts_by_reason`` histogram has bounded
    keys.  The categories track the branches in
    ``validation_status.score_validation_status``.
    """
    if not isinstance(reason, str) or not reason:
        return "unknown"
    r = reason.lower()
    if "classifier abstained" in r:
        return "classifier_abstained"
    if "no parsable" in r:
        return "missing_anchor"
    if "pending window" in r and ">" in reason:
        return "past_pending_window"
    if "no directional tags yet" in r:
        return "pending_within_window"
    if "no scorable surface" in r:
        return "no_scorable_surface"
    if status in ("validated", "contradicted") and "supports vs" in r:
        return "majority_rule"
    return "other"


@router.get("/diagnostics/major-skipped-headlines")
def major_skipped_headlines(
    limit: int = Query(25, ge=1, le=200),
    since_hours: int = Query(
        72, ge=1, le=720,
        description=(
            "Recency window (hours) for cluster eligibility.  Mirrors "
            "the ``since_hours`` filter on ``/registry/candidate-queue`` "
            "so this view reflects the same working set the queue and "
            "any paid backfill would consider."
        ),
    ),
    min_source_count: int = Query(
        2, ge=1, le=50,
        description=(
            "Minimum cluster ``source_count`` to admit into the items "
            "list.  Default 2 filters singleton-source rumours; raise to "
            "narrow further for an at-a-glance major-headline view."
        ),
    ),
    include_low_signal: bool = Query(
        False,
        description=(
            "When true, low-signal clusters and headlines that fail the "
            "relevance gate are admitted.  Mirrors the candidate-queue "
            "flag of the same name."
        ),
    ),
):
    """High-priority headlines NOT reaching analysis — early-warning view.

    Pure read.  Reuses cached news payload + headline registry only —
    no LLM, no yfinance, no market_check, no provider call, no DB
    write.  Companion to ``/registry/candidate-queue``: the queue
    surfaces *eligible* items; this view extends that with
    ``expired_low_impact`` rows and per-item ``why_visible`` so the
    operator can see at a glance which major headlines are stuck or
    expiring.

    **Treats already-analyzed separately.**  Rows whose registry state
    is ``analyzed`` / ``market_checked`` / ``surfaced`` are counted in
    ``counts.already_analyzed`` but are NOT included in ``items``;
    they are doing fine and would crowd out the headlines that need
    operator attention.

    Items are ranked by
    ``routes.movers._score_cluster_for_preview`` (the same scorer the
    paid backfill ranks against), tie-broken by ``source_count`` then
    by asset-term presence, capped at ``limit``.

    Returns ``available=False`` with an empty items list if the
    aggregator cannot run (registry helpers unimportable, news cache
    inaccessible) so the operator panel renders a clear unavailable
    state rather than a 500.
    """
    try:
        return _api._sanitize_floats(_compute_major_skipped(
            limit=limit,
            since_hours=since_hours,
            min_source_count=min_source_count,
            include_low_signal=include_low_signal,
        ))
    except Exception:
        return _api._sanitize_floats(_major_skipped_unavailable(
            limit=limit,
            since_hours=since_hours,
            min_source_count=min_source_count,
            include_low_signal=include_low_signal,
        ))


def _major_skipped_unavailable(
    *,
    limit: int,
    since_hours: int,
    min_source_count: int,
    include_low_signal: bool,
) -> dict:
    """Stable empty shape returned when the aggregator cannot run."""
    return {
        "available":               False,
        "items":                   [],
        "counts": {
            "eligible":            0,
            "skipped":             0,
            "already_analyzed":    0,
            "expired_low_impact":  0,
        },
        "counts_by_skip_reason":   {},
        "counts_by_registry_state": {},
        "filters": {
            "limit":               limit,
            "since_hours":         since_hours,
            "min_source_count":    min_source_count,
            "include_low_signal":  include_low_signal,
        },
        "news_source":             None,
    }


def _compute_major_skipped(
    *,
    limit: int,
    since_hours: int,
    min_source_count: int,
    include_low_signal: bool,
) -> dict:
    """Single-pass aggregator over the cached news clusters.

    Mirrors the pre-filter pipeline ``/registry/candidate-queue`` uses
    (recency + headline + low_signal + relevance) so the two views
    operate on the same universe; adds the ``min_source_count`` filter
    and the ``expired_low_impact`` surfacing on top.

    Pure read — every helper imported from ``routes.movers`` is
    ``_cached_*`` / pure / read-only.  Late imports keep this
    diagnostics module's import-time surface light and avoid pulling
    in the movers cycle when the endpoint isn't called.
    """
    from datetime import datetime, timedelta
    from routes.movers import (
        _cached_news_payload,
        _cluster_event_date,
        _cluster_has_asset_terms,
        _cluster_headline,
        _cluster_is_recent,
        _hr_dedup_key,
        _headline_is_market_relevant,
        _rank_explanation,
        _registry_state_for_title_key,
        _score_cluster_for_preview,
        _skip_reason_label,
    )

    payload, source = _cached_news_payload()
    raw_clusters = (payload or {}).get("clusters") or []
    since_dt = (
        datetime.now() - timedelta(hours=since_hours)
        if since_hours and since_hours > 0 else None
    )

    counts = {
        "eligible":           0,
        "skipped":            0,
        "already_analyzed":   0,
        "expired_low_impact": 0,
    }
    counts_by_skip_reason:    dict[str, int] = {}
    counts_by_registry_state: dict[str, int] = {}

    eligible_clusters: list[dict] = []
    for cluster in raw_clusters:
        if not isinstance(cluster, dict):
            continue
        if not _cluster_is_recent(cluster, since=since_dt):
            continue
        headline = _cluster_headline(cluster)
        if not headline:
            continue
        if int(cluster.get("source_count") or 0) < min_source_count:
            continue
        if cluster.get("low_signal") and not include_low_signal:
            continue
        if (
            not include_low_signal
            and not _headline_is_market_relevant(headline)
        ):
            continue
        eligible_clusters.append(cluster)

    cluster_scores: list[tuple[dict, float, dict]] = []
    for cluster in eligible_clusters:
        score, factors = _score_cluster_for_preview(cluster)
        cluster_scores.append((cluster, score, factors))
    cluster_scores.sort(
        key=lambda triple: (
            triple[1],
            int(triple[0].get("source_count") or 0),
            1 if _cluster_has_asset_terms(triple[0]) else 0,
        ),
        reverse=True,
    )

    items: list[dict] = []
    for cluster, rank_score, rank_factors in cluster_scores:
        headline = _cluster_headline(cluster)
        title_key = _hr_dedup_key(headline)
        registry_state, _eid = _registry_state_for_title_key(title_key)

        state_key = registry_state if registry_state else "unregistered"
        counts_by_registry_state[state_key] = (
            counts_by_registry_state.get(state_key, 0) + 1
        )

        # Already-analyzed: counted, never surfaced — those rows are
        # doing fine and would crowd the major-skipped view.
        if registry_state in ("analyzed", "market_checked", "surfaced"):
            counts["already_analyzed"] += 1
            counts["skipped"] += 1
            continue

        last_skip_reason = _last_skip_reason_for_title_key(title_key)
        if last_skip_reason:
            counts_by_skip_reason[last_skip_reason] = (
                counts_by_skip_reason.get(last_skip_reason, 0) + 1
            )

        if registry_state == "expired_low_impact":
            counts["expired_low_impact"] += 1
            counts["skipped"] += 1
            why_visible = (
                f"expired before analysis (state={registry_state})"
            )
        else:
            counts["eligible"] += 1
            if last_skip_reason:
                why_visible = f"skipped: {last_skip_reason}"
            else:
                why_visible = (
                    f"high source_count "
                    f"({int(cluster.get('source_count') or 0)}), "
                    f"awaiting analysis"
                )

        if len(items) >= limit:
            continue
        items.append({
            "headline":          headline,
            "source_count":      int(cluster.get("source_count") or 0),
            "published_at":      str(cluster.get("published_at") or "") or None,
            "event_date":        _cluster_event_date(cluster),
            "registry_state":    registry_state,
            "skip_reason":       last_skip_reason,
            "skip_reason_label": _skip_reason_label(last_skip_reason),
            "rank_score":        round(float(rank_score), 3),
            "rank_factors":      rank_factors,
            "rank_explanation":  _rank_explanation(rank_factors),
            "why_visible":       why_visible,
        })

    return {
        "available":               True,
        "items":                   items,
        "counts":                  counts,
        "counts_by_skip_reason":   counts_by_skip_reason,
        "counts_by_registry_state": counts_by_registry_state,
        "filters": {
            "limit":               limit,
            "since_hours":         since_hours,
            "min_source_count":    min_source_count,
            "include_low_signal":  include_low_signal,
        },
        "news_source":             source,
    }


@router.get("/diagnostics/reaction-profile-stats")
def reaction_profile_stats():
    """Archive-level visibility into reaction_profile_v1 input readiness.

    Pure read.  No LLM, no yfinance, no market_check, no provider call,
    no DB write.

    Honest accounting: today's archive stores per-ticker scalar returns
    on ``market_tickers`` but does not persist raw close-series, so
    ``reaction_profile.compute_reaction_profile`` cannot actually run
    on archived rows.  This endpoint reports how many rows would even
    have the inputs to feed a future composer call.

    ``profile_basis_counts`` is an *event-level* categorization derived
    from stored shape, not a passthrough of ``REACTION_PROFILE_BASES``:

      * ``unscorable``           — event has no tickers, or no ticker
                                   carries a numeric return field; the
                                   composer would have nothing to chew.
      * ``scalar_returns_only``  — at least one ticker has stored
                                   returns; would become a candidate
                                   for the composer once raw closes
                                   are persisted.

    Single top-level ``available`` flag — when false, every numeric
    field is zeroed and ``latest_event_timestamp`` is null, so consumers
    can render the panel without branching on field presence.
    """
    try:
        return _api._sanitize_floats(_compute_reaction_profile_stats())
    except Exception:
        return _api._sanitize_floats(_reaction_profile_unavailable())


def _reaction_profile_unavailable() -> dict:
    """Stable empty shape returned when the aggregator cannot run."""
    return {
        "available":                       False,
        "total_events":                    0,
        "events_with_market_tickers":      0,
        "events_with_profile_input_ready": 0,
        "events_unscorable":               0,
        "ticker_count":                    0,
        "tickers_with_scalar_returns":     0,
        "profile_basis_counts":            {},
        "latest_event_timestamp":          None,
    }


def _compute_reaction_profile_stats() -> dict:
    """Single-pass aggregator over events and their stored ``market_tickers``.

    Per-event categorization is mutually exclusive: every event lands
    in either ``scalar_returns_only`` (input-ready) or ``unscorable``
    (no usable input).  ``ticker_count`` and
    ``tickers_with_scalar_returns`` are the underlying ticker-level
    sums so consumers can see the per-ticker readiness rate.

    Structural failures (DB unreachable) raise so the outer route
    handler flips ``available`` to ``False``; per-row decode errors
    are swallowed so a single bit-rotted row doesn't break the
    aggregate.
    """
    import sqlite3
    import db as _db

    if not _db._db_ready:
        return _reaction_profile_unavailable()

    with _db.connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM events").fetchall()

    total_events       = 0
    with_tickers       = 0
    input_ready        = 0
    unscorable         = 0
    ticker_count       = 0
    tickers_with_ret   = 0
    basis_counts: dict[str, int] = {}
    latest_ts: str | None = None

    for row in rows:
        total_events += 1
        try:
            event = _db._decode_event_row(row)
        except Exception:
            event = dict(row)

        ts = event.get("timestamp")
        if isinstance(ts, str) and ts and (latest_ts is None or ts > latest_ts):
            latest_ts = ts

        tickers = event.get("market_tickers") or []
        if not isinstance(tickers, list):
            tickers = []

        if len(tickers) > 0:
            with_tickers += 1

        event_has_return = False
        for t in tickers:
            if not isinstance(t, dict):
                continue
            ticker_count += 1
            if _ticker_has_return(t):
                tickers_with_ret += 1
                event_has_return = True

        if event_has_return:
            input_ready += 1
            basis_counts["scalar_returns_only"] = (
                basis_counts.get("scalar_returns_only", 0) + 1
            )
        else:
            unscorable += 1
            basis_counts["unscorable"] = basis_counts.get("unscorable", 0) + 1

    return {
        "available":                       True,
        "total_events":                    total_events,
        "events_with_market_tickers":      with_tickers,
        "events_with_profile_input_ready": input_ready,
        "events_unscorable":               unscorable,
        "ticker_count":                    ticker_count,
        "tickers_with_scalar_returns":     tickers_with_ret,
        "profile_basis_counts":            basis_counts,
        "latest_event_timestamp":          latest_ts,
    }


# ---------------------------------------------------------------------------
# /diagnostics/track-record — validation status × hydrated reaction profile
# ---------------------------------------------------------------------------


@router.get("/diagnostics/track-record")
def track_record():
    """Aggregate "did the thesis play out?" view.

    Pure read.  Joins
    :func:`validation_status.score_validation_status` (event-level
    classification into ``validated`` / ``contradicted`` / ``unresolved``
    / ``pending``) with the per-ticker reaction-profile hydration path
    (:func:`reaction_profile_hydration.hydrate_per_ticker_profile`,
    which itself reads from ``price_cache`` only — no provider call,
    no fetch).

    Returns compact aggregates: count of events per validation status,
    how many events have a hydrated reaction profile, average ``return_5d``
    and ``peak_move_20d`` per status, and the per-status
    ``fade_or_hold_label_20d`` histogram.  Coverage notes call out how
    many events landed in each "no signal" reason (no tickers, all
    tickers unscorable, partial horizon coverage) so consumers can
    interpret a thin average without re-deriving the cause.

    Single top-level ``available`` flag — when false, every numeric
    field is zeroed and ``latest_event_timestamp`` is null.  Per-event
    failures (scoring or hydration) are caught so a single bad row
    cannot collapse the aggregate to ``available=False``.

    No DB write, no LLM, no ``yfinance`` / ``market_check`` /
    provider / network call.
    """
    try:
        return _api._sanitize_floats(_compute_track_record())
    except Exception:
        return _api._sanitize_floats(_track_record_unavailable())


def _track_record_unavailable() -> dict:
    """Stable empty shape returned when the aggregator cannot run."""
    return {
        "available":                                False,
        "total_events":                             0,
        "counts_by_validation_status":              {s: 0 for s in VALID_STATUSES},
        "reaction_profile_available_count":         0,
        "average_return_5d_by_validation_status":   {s: None for s in VALID_STATUSES},
        "average_peak_move_20d_by_validation_status": {s: None for s in VALID_STATUSES},
        "fade_or_hold_counts_by_validation_status": {s: {} for s in VALID_STATUSES},
        "coverage_notes": {
            "events_with_no_tickers": 0,
            "events_unscorable":      0,
            "events_with_5d_signal":  0,
            "events_with_20d_signal": 0,
            "score_failures":         0,
            "hydration_failures":     0,
        },
        "curated_intake_excluded_count":            0,
        "latest_event_timestamp":                   None,
    }


def _compute_track_record() -> dict:
    """Single-pass aggregator joining validation_status + hydrated profile.

    Per-row scoring or hydration failures are caught individually so
    one bad row never breaks the aggregate; the failure counts surface
    in ``coverage_notes`` so consumers can see how thin the underlying
    data is.  Structural failures (DB unreachable, import error) raise
    so the outer route handler can flip ``available`` to ``False``.
    """
    import sqlite3
    import db as _db

    if not _db._db_ready:
        return _track_record_unavailable()

    with _db.connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM events").fetchall()

    counts_by_status: dict[str, int] = {s: 0 for s in VALID_STATUSES}
    sum_5d:   dict[str, float] = {s: 0.0 for s in VALID_STATUSES}
    n_5d:     dict[str, int]   = {s: 0   for s in VALID_STATUSES}
    sum_20d:  dict[str, float] = {s: 0.0 for s in VALID_STATUSES}
    n_20d:    dict[str, int]   = {s: 0   for s in VALID_STATUSES}
    fhh:      dict[str, dict[str, int]] = {s: {} for s in VALID_STATUSES}

    total_events                 = 0
    rp_available_events          = 0
    events_with_no_tickers       = 0
    events_unscorable            = 0
    events_with_5d_signal        = 0
    events_with_20d_signal       = 0
    score_failures               = 0
    hydration_failures           = 0
    curated_intake_excluded      = 0
    latest_ts: str | None        = None

    for raw in rows:
        try:
            event = _db._decode_event_row(raw)
        except Exception:
            event = dict(raw)

        # Curated-intake stubs are real archived rows with no thesis to
        # score; exclude them from every outcome count and disclose the
        # tally separately so they are never silently hidden.
        stage = (event.get("stage") or "").strip()
        if stage in _db.NON_ANALYSIS_STAGES:
            curated_intake_excluded += 1
            continue

        total_events += 1
        ts = event.get("timestamp")
        if isinstance(ts, str) and ts and (latest_ts is None or ts > latest_ts):
            latest_ts = ts

        try:
            scored = score_validation_status(event)
            status = scored.get("status") if isinstance(scored, dict) else None
        except Exception:
            score_failures += 1
            status = None

        if status in counts_by_status:
            counts_by_status[status] += 1

        tickers = event.get("market_tickers") or []
        if not isinstance(tickers, list) or not tickers:
            events_with_no_tickers += 1
            # Without tickers there is nothing to hydrate; the event
            # contributes only to total_events and the status bucket.
            continue

        event_date = event.get("event_date")
        any_5d   = False
        any_20d  = False
        any_hyd  = False
        for t in tickers:
            if not isinstance(t, dict):
                continue
            try:
                profile = hydrate_per_ticker_profile(t, event_date=event_date)
            except Exception:
                hydration_failures += 1
                continue

            r5  = profile.get("return_5d")
            r20 = profile.get("return_20d")
            p20 = profile.get("peak_move_20d")
            label20 = profile.get("fade_or_hold_label_20d")

            if isinstance(r5, (int, float)) and not isinstance(r5, bool):
                any_5d = True
                any_hyd = True
                if status in counts_by_status:
                    sum_5d[status] += float(r5)
                    n_5d[status]   += 1
            if isinstance(r20, (int, float)) and not isinstance(r20, bool):
                any_20d = True
                any_hyd = True
            if isinstance(p20, (int, float)) and not isinstance(p20, bool):
                if status in counts_by_status:
                    sum_20d[status] += float(p20)
                    n_20d[status]   += 1
            if (
                isinstance(label20, str)
                and label20 != "insufficient"
                and status in fhh
            ):
                fhh[status][label20] = fhh[status].get(label20, 0) + 1

        if any_hyd:
            rp_available_events += 1
        else:
            events_unscorable += 1
        if any_5d:
            events_with_5d_signal += 1
        if any_20d:
            events_with_20d_signal += 1

    avg_5d = {
        s: (round(sum_5d[s] / n_5d[s], 2) if n_5d[s] > 0 else None)
        for s in VALID_STATUSES
    }
    avg_20d = {
        s: (round(sum_20d[s] / n_20d[s], 2) if n_20d[s] > 0 else None)
        for s in VALID_STATUSES
    }

    return {
        "available":                                True,
        "total_events":                             total_events,
        "counts_by_validation_status":              counts_by_status,
        "reaction_profile_available_count":         rp_available_events,
        "average_return_5d_by_validation_status":   avg_5d,
        "average_peak_move_20d_by_validation_status": avg_20d,
        "fade_or_hold_counts_by_validation_status": fhh,
        "coverage_notes": {
            "events_with_no_tickers": events_with_no_tickers,
            "events_unscorable":      events_unscorable,
            "events_with_5d_signal":  events_with_5d_signal,
            "events_with_20d_signal": events_with_20d_signal,
            "score_failures":         score_failures,
            "hydration_failures":     hydration_failures,
        },
        "curated_intake_excluded_count":            curated_intake_excluded,
        "latest_event_timestamp":                   latest_ts,
    }


# ---------------------------------------------------------------------------
# /diagnostics/reaction-profile-blockers — per-event/ticker hydration triage
# ---------------------------------------------------------------------------


_RPB_REASON_KEYS: tuple[str, ...] = (
    "no_market_tickers",
    "no_event_date",
    "no_anchor_close",
    "no_forward_1d_close",
    "no_forward_5d_close",
    "no_forward_20d_close",
    "scalar_returns_only_fallback",
    "hydrated_from_price_cache",
    "invalid_ticker",
)

# The success bucket — ``examples`` excludes rows that landed here.
_RPB_HYDRATED_REASON: str = "hydrated_from_price_cache"

_RPB_EXAMPLES_LIMIT: int = 10


@router.get("/diagnostics/reaction-profile-blockers")
def reaction_profile_blockers():
    """Per-event/ticker triage of why reaction-profile hydration is blocked.

    Pure read.  Loops over the events archive and the SQLite
    ``price_cache`` only — no LLM call, no ``yfinance`` import, no
    provider seam, no ``market_check`` invocation, no DB write.

    Each event's tickers are classified into exactly one bucket:

      * ``no_market_tickers``           — event-level: the event has no
                                          tickers to hydrate.  Counted
                                          once per event.
      * ``no_event_date``               — per-ticker: the event has no
                                          ``event_date`` so the
                                          hydrator has no anchor.
      * ``invalid_ticker``              — per-ticker: dict missing a
                                          usable ``symbol`` field.
      * ``no_anchor_close``             — per-ticker: cache holds zero
                                          rows at or after the anchor.
      * ``scalar_returns_only_fallback``— per-ticker: cache miss but
                                          the saved row carries a
                                          legacy scalar return field.
      * ``no_forward_1d_close``         — per-ticker: composer ran but
                                          ``return_1d`` is None.
      * ``no_forward_5d_close``         — per-ticker: ``return_1d``
                                          populated, ``return_5d`` is
                                          None.
      * ``no_forward_20d_close``        — per-ticker: ``return_5d``
                                          populated, ``return_20d`` is
                                          None.
      * ``hydrated_from_price_cache``   — per-ticker success: every
                                          horizon up through 20d has a
                                          numeric return.

    ``examples`` carries up to 10 blocked rows
    (``hydrated_from_price_cache`` is the success bucket and is
    excluded).  Each example is ``{event_id, headline, ticker,
    missing_reason}``; for ``no_market_tickers`` the ``ticker`` field
    is ``None``.

    Single top-level ``available`` flag — when false, every count is
    zero and ``examples`` is empty.
    """
    try:
        return _api._sanitize_floats(_compute_reaction_profile_blockers())
    except Exception:
        return _api._sanitize_floats(_reaction_profile_blockers_unavailable())


def _reaction_profile_blockers_unavailable() -> dict:
    """Stable empty shape returned when the aggregator cannot run."""
    return {
        "available":    False,
        "total_events": 0,
        "counts":       {k: 0 for k in _RPB_REASON_KEYS},
        "examples":     [],
    }


def _classify_blocker_for_ticker(saved_ticker: Any, event_date: Any) -> str:
    """Map one saved per-ticker dict to its blocker bucket.

    Mutually exclusive: every ticker lands in exactly one reason.
    Per-ticker hydration failures collapse to a cache-miss-equivalent
    bucket so one bad row never raises out of the aggregator.
    """
    if not isinstance(saved_ticker, dict):
        return "invalid_ticker"
    sym = saved_ticker.get("symbol")
    if not isinstance(sym, str) or not sym:
        return "invalid_ticker"
    if not (isinstance(event_date, str) and event_date):
        return "no_event_date"

    try:
        profile = hydrate_per_ticker_profile(
            saved_ticker, event_date=event_date,
        )
    except Exception:
        if _ticker_has_return(saved_ticker):
            return "scalar_returns_only_fallback"
        return "no_anchor_close"

    if profile.get("hydration_status") == "cache_miss":
        if _ticker_has_return(saved_ticker):
            return "scalar_returns_only_fallback"
        return "no_anchor_close"

    if profile.get("return_1d") is None:
        return "no_forward_1d_close"
    if profile.get("return_5d") is None:
        return "no_forward_5d_close"
    if profile.get("return_20d") is None:
        return "no_forward_20d_close"
    return "hydrated_from_price_cache"


def _compute_reaction_profile_blockers() -> dict:
    """Single-pass aggregator over events + ``price_cache`` (read-only).

    Structural failures (DB unreachable) raise so the outer route
    handler flips ``available`` to ``False``; per-row decode and
    per-ticker classification errors are absorbed so one bad row
    cannot collapse the aggregate.
    """
    import sqlite3
    import db as _db

    if not _db._db_ready:
        return _reaction_profile_blockers_unavailable()

    with _db.connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM events").fetchall()

    counts: dict[str, int] = {k: 0 for k in _RPB_REASON_KEYS}
    examples: list[dict] = []
    total_events = 0

    for raw in rows:
        total_events += 1
        try:
            event = _db._decode_event_row(raw)
        except Exception:
            event = dict(raw)

        event_id = event.get("id")
        headline = event.get("headline")
        if not isinstance(headline, str):
            headline = "" if headline is None else str(headline)

        tickers = event.get("market_tickers") or []
        if not isinstance(tickers, list) or len(tickers) == 0:
            counts["no_market_tickers"] += 1
            if len(examples) < _RPB_EXAMPLES_LIMIT:
                examples.append({
                    "event_id":       event_id,
                    "headline":       headline,
                    "ticker":         None,
                    "missing_reason": "no_market_tickers",
                })
            continue

        event_date = event.get("event_date")
        for t in tickers:
            reason = _classify_blocker_for_ticker(t, event_date)
            counts[reason] += 1
            if (
                reason != _RPB_HYDRATED_REASON
                and len(examples) < _RPB_EXAMPLES_LIMIT
            ):
                ticker_sym = (
                    t.get("symbol")
                    if isinstance(t, dict)
                    and isinstance(t.get("symbol"), str)
                    and t.get("symbol")
                    else None
                )
                examples.append({
                    "event_id":       event_id,
                    "headline":       headline,
                    "ticker":         ticker_sym,
                    "missing_reason": reason,
                })

    return {
        "available":    True,
        "total_events": total_events,
        "counts":       counts,
        "examples":     examples,
    }


# ---------------------------------------------------------------------------
# /diagnostics/no-forward-20d-blockers — sub-classification of why the 20d
# horizon can't hydrate
# ---------------------------------------------------------------------------


_NF20_REASON_KEYS: tuple[str, ...] = (
    "event_too_recent_for_20d",
    "auto_adjust_mismatch_for_20d",
    "likely_delisted_or_sparse",
    "cache_max_before_20d_horizon",
)
_NF20_EXAMPLES_LIMIT: int = 10
# A ticker whose newest cached row across both ``auto_adjust`` flags is
# more than this many calendar days behind today is treated as
# delisted/sparse.  60 days is wide enough to ride out normal weekend +
# holiday gaps and any short refresh lag, but narrow enough to surface
# a ticker that has stopped reporting altogether.
_NF20_DELISTED_THRESHOLD_CALENDAR_DAYS: int = 60


@router.get("/diagnostics/no-forward-20d-blockers")
def no_forward_20d_blockers():
    """Sub-classification of /diagnostics/reaction-profile-blockers'
    ``no_forward_20d_close`` bucket.

    Pure read.  Does not call the LLM, ``yfinance``,
    ``market_check.market_check``, or any provider seam, and never
    writes to the DB.  Re-uses :func:`_classify_blocker_for_ticker` so
    the universe (``total_no_forward_20d``) matches the headline
    ``no_forward_20d_close`` count exactly, then for every such ticker
    queries ``price_cache`` once for ``MAX(date)`` per
    ``(ticker, auto_adjust)`` pair and assigns one of four diagnostic
    sub-reasons (mutually exclusive, in precedence order):

      * ``event_too_recent_for_20d``       — ``event_date + 20 bd`` is
                                             still in the future, so no
                                             cache anywhere can satisfy
                                             the 20d horizon yet.  No
                                             action needed; wait for
                                             time to pass.
      * ``auto_adjust_mismatch_for_20d``   — cache rows reach the 20d
                                             target but only at
                                             ``auto_adjust=1``, while
                                             the hydrator reads
                                             ``auto_adjust=0``.  An
                                             ingestion-flag regression
                                             — the cache HAS the data,
                                             the hydrator can't see it.
      * ``likely_delisted_or_sparse``      — the newest cached row for
                                             the ticker (across both
                                             flags) is more than
                                             ``_NF20_DELISTED_THRESHOLD_CALENDAR_DAYS``
                                             calendar days behind
                                             today, suggesting the
                                             ticker stopped reporting.
                                             Backfill won't fix this
                                             one — the data source
                                             does not have rows to
                                             give.
      * ``cache_max_before_20d_horizon``   — fallback: cache exists,
                                             newest row is reasonably
                                             fresh, but the per-ticker
                                             window doesn't extend
                                             back to cover the 20d
                                             horizon.  Refresh-lag /
                                             partial backfill — a
                                             targeted re-fetch should
                                             close it.

    ``examples`` carries up to 10 rows
    (``{event_id, headline, ticker, missing_reason,
    diagnostic_reason}``) so an operator can spot-check which events
    drove which sub-bucket.

    Single top-level ``available`` flag — when false, every count is
    zero and ``examples`` is empty.
    """
    try:
        return _api._sanitize_floats(_compute_no_forward_20d_breakdown())
    except Exception:
        return _api._sanitize_floats(_no_forward_20d_blockers_unavailable())


def _no_forward_20d_blockers_unavailable() -> dict:
    """Stable empty shape returned when the aggregator cannot run."""
    return {
        "available":            False,
        "total_no_forward_20d": 0,
        "counts":               {k: 0 for k in _NF20_REASON_KEYS},
        "examples":             [],
    }


def _classify_no_forward_20d_subreason(
    *,
    event_d: date,
    today: date,
    aa_false_max: date | None,
    aa_true_max: date | None,
) -> str:
    """Pure decision tree.  Inputs are already-parsed dates; no I/O."""
    target_20d = _business_day_offset(event_d, 20)
    if target_20d > today:
        return "event_too_recent_for_20d"

    aa_true_satisfies  = aa_true_max  is not None and aa_true_max  >= target_20d
    aa_false_satisfies = aa_false_max is not None and aa_false_max >= target_20d
    if aa_true_satisfies and not aa_false_satisfies:
        return "auto_adjust_mismatch_for_20d"

    newest: date | None = None
    for d in (aa_false_max, aa_true_max):
        if d is not None and (newest is None or d > newest):
            newest = d
    if (
        newest is not None
        and (today - newest).days > _NF20_DELISTED_THRESHOLD_CALENDAR_DAYS
    ):
        return "likely_delisted_or_sparse"
    return "cache_max_before_20d_horizon"


def _compute_no_forward_20d_breakdown() -> dict:
    """Single-pass breakdown.  One ``SELECT *`` against ``events``, one
    ``GROUP BY ticker, auto_adjust`` against ``price_cache``, then per
    ticker a hydration call (already cached behind the same SQLite
    file the breakdown reads).
    """
    import sqlite3
    import db as _db

    if not _db._db_ready:
        return _no_forward_20d_blockers_unavailable()

    with _db.connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM events").fetchall()
        try:
            cache_max_rows = conn.execute(
                "SELECT ticker, auto_adjust, MAX(date) "
                "FROM price_cache GROUP BY ticker, auto_adjust"
            ).fetchall()
        except sqlite3.Error:
            cache_max_rows = []

    cache_max: dict[tuple[str, int], date] = {}
    for ticker, flag, max_d in cache_max_rows:
        if not isinstance(ticker, str) or not isinstance(max_d, str):
            continue
        try:
            cache_max[(ticker.upper(), int(flag))] = date.fromisoformat(
                max_d[:10],
            )
        except (ValueError, TypeError):
            continue

    today = date.today()
    counts: dict[str, int] = {k: 0 for k in _NF20_REASON_KEYS}
    examples: list[dict] = []
    total = 0

    for raw in rows:
        try:
            event = _db._decode_event_row(raw)
        except Exception:
            event = dict(raw)

        event_id = event.get("id")
        headline = event.get("headline")
        if not isinstance(headline, str):
            headline = "" if headline is None else str(headline)

        event_date_str = event.get("event_date")
        if not isinstance(event_date_str, str) or not event_date_str:
            continue
        try:
            event_d = date.fromisoformat(event_date_str[:10])
        except (ValueError, TypeError):
            continue

        tickers = event.get("market_tickers") or []
        if not isinstance(tickers, list):
            continue

        for t in tickers:
            try:
                reason = _classify_blocker_for_ticker(t, event_date_str)
            except Exception:
                continue
            if reason != "no_forward_20d_close":
                continue

            total += 1
            sym_raw = t.get("symbol") if isinstance(t, dict) else None
            sym_upper = sym_raw.upper() if isinstance(sym_raw, str) else ""

            sub = _classify_no_forward_20d_subreason(
                event_d=event_d,
                today=today,
                aa_false_max=cache_max.get((sym_upper, 0)),
                aa_true_max=cache_max.get((sym_upper, 1)),
            )
            counts[sub] += 1

            if len(examples) < _NF20_EXAMPLES_LIMIT:
                examples.append({
                    "event_id":          event_id,
                    "headline":          headline,
                    "ticker":            sym_upper or None,
                    "missing_reason":    "no_forward_20d_close",
                    "diagnostic_reason": sub,
                })

    return {
        "available":            True,
        "total_no_forward_20d": total,
        "counts":               counts,
        "examples":             examples,
    }


# ---------------------------------------------------------------------------
# /diagnostics/auto-backfill-config — read-only env-driven config snapshot
# ---------------------------------------------------------------------------


@router.get("/diagnostics/auto-backfill-config")
def auto_backfill_config():
    """Read-only snapshot of the auto-backfill scheduler configuration.

    Pure read of ``os.environ`` via
    :func:`auto_backfill_config.load_auto_backfill_config` — does NOT
    start the scheduler, does NOT execute a backfill, does NOT touch
    SQLite, does NOT call the LLM, ``yfinance``, ``market_check``, or
    any provider seam.  Safe to call at any time, including before any
    paid path has been authorised.

    The response surfaces operational toggles only.  No API keys, no
    raw env values for credential variables, and no headline content
    are emitted — see ``docs/auto_backfill_scheduler_design.md`` §9
    for the wider data-handling contract.

    The endpoint never raises: a structural failure inside the loader
    falls back to the disabled-shape so the operator panel renders a
    clean "off" state rather than a 500.
    """
    try:
        return _api._sanitize_floats(load_auto_backfill_config().to_dict())
    except Exception:
        return _api._sanitize_floats(_auto_backfill_config_unavailable())


def _auto_backfill_config_unavailable() -> dict:
    """Stable fallback shape — every key the populated response carries,
    with safe defaults that look like an off-and-quiet environment.
    """
    from auto_backfill_config import (
        DEFAULT_INTERVAL_HOURS,
        DEFAULT_MAX_PER_DAY,
        DEFAULT_MAX_PER_RUN,
        DEFAULT_MODEL,
        EFFECTIVE_DISABLED,
    )
    return {
        "enabled":               False,
        "paid_analysis_enabled": False,
        "interval_hours":        DEFAULT_INTERVAL_HOURS,
        "max_calls_per_run":     DEFAULT_MAX_PER_RUN,
        "max_calls_per_day":     DEFAULT_MAX_PER_DAY,
        "model":                 DEFAULT_MODEL,
        "effective_status":      EFFECTIVE_DISABLED,
        "warnings":              [],
    }


# ---------------------------------------------------------------------------
# /diagnostics/auto-backfill-status — config + ledger + state composition
# ---------------------------------------------------------------------------

# Process-local singletons.  Created lazily on first endpoint hit so
# importing this module never starts a scheduler, never opens a socket,
# and never spends an LLM call.  The ledger is keyed on the current
# ``max_calls_per_day`` so an env-driven cap change is observable on
# the next snapshot without restarting the process.
_AUTO_BACKFILL_LEDGER: AutoBackfillLedger | None = None
_AUTO_BACKFILL_LEDGER_CAP: int | None = None
_AUTO_BACKFILL_STATE: AutoBackfillState | None = None
# 1h covers a generous lock TTL even if some future scheduler holds
# the lock for the full interval; this layer never triggers a run.
_AUTO_BACKFILL_STATE_TTL_SECONDS: int = 3600


def _get_auto_backfill_ledger(daily_cap: int) -> AutoBackfillLedger:
    global _AUTO_BACKFILL_LEDGER, _AUTO_BACKFILL_LEDGER_CAP
    if _AUTO_BACKFILL_LEDGER is None or _AUTO_BACKFILL_LEDGER_CAP != daily_cap:
        _AUTO_BACKFILL_LEDGER = AutoBackfillLedger(daily_cap=daily_cap)
        _AUTO_BACKFILL_LEDGER_CAP = daily_cap
    return _AUTO_BACKFILL_LEDGER


def _get_auto_backfill_state() -> AutoBackfillState:
    global _AUTO_BACKFILL_STATE
    if _AUTO_BACKFILL_STATE is None:
        _AUTO_BACKFILL_STATE = AutoBackfillState(
            ttl_seconds=_AUTO_BACKFILL_STATE_TTL_SECONDS,
        )
    return _AUTO_BACKFILL_STATE


@router.get("/diagnostics/auto-backfill-status")
def auto_backfill_status(request: Request):
    """Read-only composition of config + ledger + state for the auto-
    backfill scheduler.

    Pure read.  Never starts the scheduler, never authorises paid
    execution, never writes to SQLite, never calls the LLM,
    ``yfinance``, ``market_check``, or any provider.  Safe to call at
    any time.

    The response composes:
      * ``config``           — the same shape ``/diagnostics/auto-backfill-config``
                               returns.
      * ``ledger``           — daily-cap / used / remaining / day from
                               the in-memory call ledger.
      * ``state``            — the lock + last-run snapshot from the
                               in-memory state holder.
      * ``scheduler``        — live snapshot of any scheduler the
                               FastAPI lifespan published to
                               ``app.state.auto_backfill_scheduler``;
                               falls back to the not-wired shape when
                               nothing was published.
      * ``effective_status`` — mirror of ``config.effective_status`` so
                               consumers can branch on the canonical
                               vocabulary without unwrapping ``config``.
      * ``last_skip_reason`` / ``last_error`` — convenience top-level
                               mirrors of the matching state fields so
                               the operator panel can render a one-line
                               status without descending into ``state``.
      * ``daily_remaining``  — convenience top-level mirror of
                               ``ledger.remaining``.

    The endpoint never raises: a structural failure inside any helper
    falls back to the stable unavailable shape so the operator panel
    renders cleanly rather than 500-ing.
    """
    try:
        scheduler = getattr(
            request.app.state, "auto_backfill_scheduler", None,
        )
        return _api._sanitize_floats(
            _compose_auto_backfill_status(scheduler=scheduler),
        )
    except Exception:
        return _api._sanitize_floats(_auto_backfill_status_unavailable())


def _compose_auto_backfill_status(scheduler: Any = None) -> dict:
    cfg = load_auto_backfill_config()
    now = datetime.now(timezone.utc)

    ledger = _get_auto_backfill_ledger(cfg.max_calls_per_day)
    state = _get_auto_backfill_state()
    ledger_dec = ledger.snapshot(now=now)
    state_snap = state.snapshot(now=now)

    return {
        "config":           cfg.to_dict(),
        "ledger": {
            "daily_cap":    ledger_dec.daily_cap,
            "used":         ledger_dec.used,
            "remaining":    ledger_dec.remaining,
            "day":          ledger_dec.day,
        },
        "state": {
            "lock_held":           state_snap.lock_held,
            "lock_owner":          state_snap.lock_owner,
            "lock_acquired_at":    state_snap.lock_acquired_at,
            "lock_expires_at":     state_snap.lock_expires_at,
            "last_run_id":         state_snap.last_run_id,
            "last_started_at":     state_snap.last_started_at,
            "last_completed_at":   state_snap.last_completed_at,
            "last_skip_reason":    state_snap.last_skip_reason,
            "last_error":          state_snap.last_error,
            "last_selected_count": state_snap.last_selected_count,
            "last_spent_calls":    state_snap.last_spent_calls,
        },
        "scheduler":        _scheduler_block(scheduler),
        "effective_status": cfg.effective_status,
        "last_skip_reason": state_snap.last_skip_reason,
        "last_error":       state_snap.last_error,
        "daily_remaining":  ledger_dec.remaining,
    }


def _scheduler_block(scheduler: Any = None) -> dict:
    """Read-only scheduler snapshot.

    Surfaces enough for an operator panel to render "is the auto-
    backfill scheduler wired and running?" without instantiating
    APScheduler.  The diagnostics layer never constructs a
    ``BackgroundScheduler`` — it only inspects the scheduler the
    FastAPI lifespan attached to ``app.state.auto_backfill_scheduler``
    (passed in via ``scheduler``) — so this function never starts a
    thread, never imports ``apscheduler`` directly, and never makes a
    network or paid call.

    ``scheduler_available`` reflects whether the
    :mod:`auto_backfill_scheduler` module imports cleanly.  Since
    that module imports ``apscheduler`` at its top, a False here is
    equally a signal that either the skeleton or its underlying
    dependency is missing.

    ``mode`` is one of:
      * ``"not_wired"``    — no scheduler attached to ``app.state``;
                              the lifespan either skipped construction
                              or shut it down.
      * ``"dry_run_only"`` — a scheduler is attached.  Whether it is
                              currently running is reported via
                              ``scheduler_started``; ``job_count``
                              reflects ``len(scheduler.get_jobs())``.

    The introspection is fully defensive: a scheduler whose
    ``running`` attribute is missing or whose ``get_jobs()`` raises
    falls back to ``scheduler_started=False`` / ``job_count=0`` while
    keeping ``mode="dry_run_only"`` — the attachment is real even if
    its enumeration broke.
    """
    try:
        import auto_backfill_scheduler  # noqa: F401
        available = True
    except Exception:
        available = False

    if scheduler is None:
        return {
            "scheduler_available": available,
            "scheduler_started":   False,
            "job_count":           0,
            "mode":                "not_wired",
        }

    started = bool(getattr(scheduler, "running", False))
    try:
        jobs = scheduler.get_jobs()
        job_count = len(jobs) if jobs is not None else 0
    except Exception:
        job_count = 0

    return {
        "scheduler_available": available,
        "scheduler_started":   started,
        "job_count":           job_count,
        "mode":                "dry_run_only",
    }


def _auto_backfill_status_unavailable() -> dict:
    """Stable fallback shape — every field the populated response
    carries, with safe defaults that look like an off-and-quiet
    environment.  Mirrors the shape ``_compose_auto_backfill_status``
    builds so consumers never need to branch on key presence.
    """
    cfg_block = _auto_backfill_config_unavailable()
    return {
        "config":           cfg_block,
        "ledger": {
            "daily_cap":    0,
            "used":         0,
            "remaining":    0,
            "day":          None,
        },
        "state": {
            "lock_held":           False,
            "lock_owner":          None,
            "lock_acquired_at":    None,
            "lock_expires_at":     None,
            "last_run_id":         None,
            "last_started_at":     None,
            "last_completed_at":   None,
            "last_skip_reason":    None,
            "last_error":          None,
            "last_selected_count": None,
            "last_spent_calls":    None,
        },
        "scheduler": {
            "scheduler_available": False,
            "scheduler_started":   False,
            "job_count":           0,
            "mode":                "not_wired",
        },
        "effective_status": cfg_block["effective_status"],
        "last_skip_reason": None,
        "last_error":       None,
        "daily_remaining":  0,
    }


# ---------------------------------------------------------------------------
# /diagnostics/auto-backfill-dry-run — operator-triggered simulated tick
# ---------------------------------------------------------------------------


@router.post("/diagnostics/auto-backfill-dry-run")
def auto_backfill_dry_run(
    since_hours: int = Query(
        72, ge=1, le=720,
        description=(
            "Recency window (hours) for the injected candidate list — "
            "mirrors the ``since_hours`` filter on "
            "``/registry/candidate-queue``."
        ),
    ),
    include_low_signal: bool = Query(
        False,
        description=(
            "When true, low-signal clusters and headlines that fail the "
            "relevance gate are admitted into the injected candidate list."
        ),
    ),
):
    """Simulate one auto-backfill scheduler tick without spending anything.

    Composes the cached-news candidate-queue pipeline (recency +
    relevance + scoring, mirroring ``/registry/candidate-queue``) with
    :func:`auto_backfill_runner.run_auto_backfill_dry_run`.  Returns the
    config snapshot, the planner's selection, skip counts/reasons, and
    the post-tick ledger + state snapshots so an operator can see what
    a real tick would do *right now*.

    Pure read.  Uses **ephemeral** :class:`AutoBackfillState` and
    :class:`AutoBackfillLedger` instances per request so the call:

    * never reserves a ledger call (the ephemeral ledger is discarded
      after the response is built),
    * never writes to SQLite,
    * never mutates the singletons exposed by
      ``/diagnostics/auto-backfill-status`` — repeated dry-run hits do
      not contaminate that endpoint's view of real scheduler activity,
    * never starts the scheduler, never invokes the LLM, ``yfinance``,
      ``market_check``, or any provider seam.

    The endpoint never raises: a structural failure inside any helper
    falls back to a stable ``available=False`` shape so an operator
    panel renders cleanly rather than 500-ing.
    """
    try:
        return _api._sanitize_floats(_compose_auto_backfill_dry_run(
            since_hours=since_hours,
            include_low_signal=include_low_signal,
        ))
    except Exception:
        return _api._sanitize_floats(_auto_backfill_dry_run_unavailable(
            since_hours=since_hours,
            include_low_signal=include_low_signal,
        ))


def _compose_auto_backfill_dry_run(
    *,
    since_hours: int,
    include_low_signal: bool,
) -> dict:
    """Compose config + ephemeral state/ledger + injected candidates +
    planner result into the dry-run response shape.

    Ephemeral state/ledger: a fresh pair is constructed per call so the
    runner's ``state.acquire`` / ``mark_started`` / ``mark_completed`` /
    ``release`` mutations are scoped to this request and the long-lived
    singletons backing ``/diagnostics/auto-backfill-status`` stay clean.
    """
    cfg = load_auto_backfill_config()
    now = datetime.now(timezone.utc)

    candidates, queue_counts, news_source = _build_dry_run_candidates(
        since_hours=since_hours,
        include_low_signal=include_low_signal,
    )

    state = AutoBackfillState(ttl_seconds=_AUTO_BACKFILL_STATE_TTL_SECONDS)
    ledger = AutoBackfillLedger(daily_cap=cfg.max_calls_per_day)

    result = run_auto_backfill_dry_run(
        candidates=candidates,
        config=cfg,
        state=state,
        ledger=ledger,
        now=now,
    )

    plan = result.plan
    selected           = [dict(item) for item in (plan.selected if plan else ())]
    skip_counts        = dict(plan.skip_counts) if plan else {}
    skip_reasons       = dict(plan.skip_reasons) if plan else {}
    eligible_count     = plan.eligible_count if plan else 0
    considered_count   = plan.considered_count if plan else 0
    effective_call_cap = plan.effective_call_cap if plan else 0

    state_snap  = result.state_snapshot_after
    ledger_snap = ledger.snapshot(now=now)

    return {
        "config":                 cfg.to_dict(),
        "selected":               selected,
        "selected_count":         result.selected_count,
        "skip_counts":            skip_counts,
        "skip_reasons":           skip_reasons,
        "candidates_considered":  considered_count,
        "eligible_count":         eligible_count,
        "effective_call_cap":     effective_call_cap,
        "decision_reason":        result.decision_reason,
        "started":                result.started,
        "completed":              result.completed,
        "skip_reason":            result.skip_reason,
        "run_id":                 result.run_id,
        "spent_calls":            result.spent_calls,
        "now":                    result.now,
        "candidate_queue_counts": queue_counts,
        "news_source":            news_source,
        "ledger": {
            "daily_cap": ledger_snap.daily_cap,
            "used":      ledger_snap.used,
            "remaining": ledger_snap.remaining,
            "day":       ledger_snap.day,
        },
        "state": {
            "lock_held":           state_snap.lock_held,
            "lock_owner":          state_snap.lock_owner,
            "lock_acquired_at":    state_snap.lock_acquired_at,
            "lock_expires_at":     state_snap.lock_expires_at,
            "last_run_id":         state_snap.last_run_id,
            "last_started_at":     state_snap.last_started_at,
            "last_completed_at":   state_snap.last_completed_at,
            "last_skip_reason":    state_snap.last_skip_reason,
            "last_error":          state_snap.last_error,
            "last_selected_count": state_snap.last_selected_count,
            "last_spent_calls":    state_snap.last_spent_calls,
        },
        "filters": {
            "since_hours":        since_hours,
            "include_low_signal": include_low_signal,
        },
        "available": True,
    }


def _build_dry_run_candidates(
    *,
    since_hours: int,
    include_low_signal: bool,
) -> tuple[list[dict], dict, str | None]:
    """Build the injected candidate list for one dry-run tick.

    Mirrors the recency / headline / low_signal / relevance pre-filter
    pipeline that ``/registry/candidate-queue`` and
    ``/diagnostics/major-skipped-headlines`` apply, then ranks the
    survivors with ``_score_cluster_for_preview`` so the dry-run sees
    the same universe a paid scheduler tick would.

    Already-analyzed and ``expired_low_impact`` rows are filtered out
    here (the planner would also skip them, but pre-filtering keeps the
    ``selected`` payload focused on actionable candidates) and tallied
    into the ``candidate_queue_counts`` block so the response mirrors
    the queue endpoint's view.

    Returns ``(items, counts, news_source)``.  Items are NOT capped —
    the planner enforces ``max_calls_per_run`` / ``daily_remaining``.

    Pure read.  No LLM, no provider, no network, no DB write.
    """
    from routes.movers import (
        _cached_news_payload,
        _cluster_event_date,
        _cluster_has_asset_terms,
        _cluster_headline,
        _cluster_is_recent,
        _hr_dedup_key,
        _headline_is_market_relevant,
        _rank_explanation,
        _registry_state_for_title_key,
        _score_cluster_for_preview,
        _skip_reason_label,
    )

    payload, source = _cached_news_payload()
    raw_clusters = (payload or {}).get("clusters") or []
    since_dt = (
        datetime.now() - timedelta(hours=since_hours)
        if since_hours and since_hours > 0 else None
    )

    counts = {
        "eligible":           0,
        "skipped":            0,
        "already_analyzed":   0,
        "expired_low_impact": 0,
    }

    eligible_clusters: list[dict] = []
    for cluster in raw_clusters:
        if not isinstance(cluster, dict):
            continue
        if not _cluster_is_recent(cluster, since=since_dt):
            continue
        headline = _cluster_headline(cluster)
        if not headline:
            continue
        if cluster.get("low_signal") and not include_low_signal:
            continue
        if (
            not include_low_signal
            and not _headline_is_market_relevant(headline)
        ):
            continue
        eligible_clusters.append(cluster)

    cluster_scores: list[tuple[dict, float, dict]] = []
    for cluster in eligible_clusters:
        score, factors = _score_cluster_for_preview(cluster)
        cluster_scores.append((cluster, score, factors))
    cluster_scores.sort(
        key=lambda triple: (
            triple[1],
            int(triple[0].get("source_count") or 0),
            1 if _cluster_has_asset_terms(triple[0]) else 0,
        ),
        reverse=True,
    )

    items: list[dict] = []
    for cluster, rank_score, rank_factors in cluster_scores:
        headline = _cluster_headline(cluster)
        title_key = _hr_dedup_key(headline)
        registry_state, _eid = _registry_state_for_title_key(title_key)

        if registry_state in ("analyzed", "market_checked", "surfaced"):
            counts["already_analyzed"] += 1
            counts["skipped"] += 1
            continue
        if registry_state == "expired_low_impact":
            counts["expired_low_impact"] += 1
            counts["skipped"] += 1
            continue

        last_skip_reason = _last_skip_reason_for_title_key(title_key)
        counts["eligible"] += 1
        items.append({
            "headline":          headline,
            "source_count":      int(cluster.get("source_count") or 0),
            "published_at":      str(cluster.get("published_at") or "") or None,
            "event_date":        _cluster_event_date(cluster),
            "registry_state":    registry_state,
            "skip_reason":       last_skip_reason,
            "skip_reason_label": _skip_reason_label(last_skip_reason),
            "rank_score":        round(float(rank_score), 3),
            "rank_factors":      rank_factors,
            "rank_explanation":  _rank_explanation(rank_factors),
        })

    return items, counts, source


def _auto_backfill_dry_run_unavailable(
    *,
    since_hours: int,
    include_low_signal: bool,
) -> dict:
    """Stable fallback shape — every field the populated response
    carries, with safe defaults that look like an off-and-quiet
    environment.  Mirrors ``_compose_auto_backfill_dry_run`` so
    consumers never need to branch on key presence.
    """
    cfg_block = _auto_backfill_config_unavailable()
    return {
        "config":                 cfg_block,
        "selected":               [],
        "selected_count":         0,
        "skip_counts":            {},
        "skip_reasons":           {},
        "candidates_considered":  0,
        "eligible_count":         0,
        "effective_call_cap":     0,
        "decision_reason":        "unavailable",
        "started":                False,
        "completed":              False,
        "skip_reason":            "unavailable",
        "run_id":                 None,
        "spent_calls":            0,
        "now":                    None,
        "candidate_queue_counts": {
            "eligible":           0,
            "skipped":            0,
            "already_analyzed":   0,
            "expired_low_impact": 0,
        },
        "news_source":            None,
        "ledger": {
            "daily_cap": 0,
            "used":      0,
            "remaining": 0,
            "day":       None,
        },
        "state": {
            "lock_held":           False,
            "lock_owner":          None,
            "lock_acquired_at":    None,
            "lock_expires_at":     None,
            "last_run_id":         None,
            "last_started_at":     None,
            "last_completed_at":   None,
            "last_skip_reason":    None,
            "last_error":          None,
            "last_selected_count": None,
            "last_spent_calls":    None,
        },
        "filters": {
            "since_hours":        since_hours,
            "include_low_signal": include_low_signal,
        },
        "available": False,
    }


# ---------------------------------------------------------------------------
# /diagnostics/price-cache-coverage — pure SQL, no provider, no DB write
# ---------------------------------------------------------------------------


# Bucket label, inclusive lower bound (calendar days) for events whose
# ``event_date`` is set.  Events without ``event_date`` land in the
# ``"unknown"`` bucket so the coverage panel never silently drops them.
_PRICE_CACHE_AGE_BUCKETS: tuple[tuple[str, int], ...] = (
    ("0_7d",     0),
    ("8_30d",    8),
    ("31_90d",  31),
    ("91d_plus", 91),
)
_PRICE_CACHE_BUCKET_UNKNOWN = "unknown"


def _empty_age_bucket() -> dict:
    return {
        "total_events":                  0,
        "events_with_market_tickers":    0,
        "events_with_any_forward_cache": 0,
        "events_with_5d_forward_cache":  0,
        "events_with_20d_forward_cache": 0,
    }


def _empty_age_bucket_set() -> dict:
    buckets: dict[str, dict] = {
        label: _empty_age_bucket()
        for label, _ in _PRICE_CACHE_AGE_BUCKETS
    }
    buckets[_PRICE_CACHE_BUCKET_UNKNOWN] = _empty_age_bucket()
    return buckets


def _age_bucket_label(age_days: int) -> str:
    """Map an event's age-in-calendar-days (vs. today) to a bucket key.

    Negative ages (event_date in the future) collapse into the
    youngest bucket so a clock-skewed row never disappears.  The
    boundaries are inclusive on the lower side and the buckets are
    contiguous, so every non-negative age maps to exactly one label.
    """
    if age_days < 0:
        return _PRICE_CACHE_AGE_BUCKETS[0][0]
    chosen = _PRICE_CACHE_AGE_BUCKETS[0][0]
    for label, lower in _PRICE_CACHE_AGE_BUCKETS:
        if age_days >= lower:
            chosen = label
        else:
            break
    return chosen


def _business_day_offset(start: date, n: int) -> date:
    """Shift ``start`` forward by ``n`` business days.

    Inlined here so the endpoint never imports ``price_cache`` (which
    would trip ``_purge_corrupt_rows`` and violate the no-DB-write
    contract on first call).
    """
    if n <= 0:
        return start
    out = start
    remaining = n
    while remaining > 0:
        out = out + timedelta(days=1)
        if out.weekday() < 5:
            remaining -= 1
    return out


@router.get("/diagnostics/price-cache-coverage")
def price_cache_coverage():
    """Read-only coverage view of the SQLite ``price_cache`` against the
    ``events`` archive.

    Pure read.  Issues only ``SELECT`` statements directly against the
    local SQLite DB.  Never imports ``market_data`` or ``price_cache``
    (the latter would trigger ``_purge_corrupt_rows`` on first call,
    violating the no-DB-write contract), never touches ``yfinance``,
    never calls the LLM, and never writes to the DB.  Safe to poll
    from an operator panel at any cadence.

    Top-level fields:

      * ``total_events``                — ``COUNT(*)`` of events.
      * ``events_with_market_tickers``  — events whose ``market_tickers``
                                          JSON decodes to at least one
                                          recognised symbol entry.
      * ``unique_tickers``              — distinct upper-cased symbols
                                          across every event row.
      * ``tickers_with_cache_rows``     — count of those symbols that
                                          appear in ``price_cache``.
      * ``tickers_without_cache_rows``  — ``unique_tickers`` minus the
                                          above.
      * ``events_with_any_forward_cache``  — events with ``event_date``
                                              and at least one ticker
                                              whose ``MAX(date)`` in
                                              ``price_cache`` is at or
                                              after the event date.
      * ``events_with_5d_forward_cache``   — same, but the ticker max
                                              must reach
                                              ``event_date + 5`` business
                                              days.
      * ``events_with_20d_forward_cache``  — same, ``+20`` business days.
      * ``coverage_by_event_age_bucket`` — per-bucket event tallies.
                                          Bucket labels:
                                          ``0_7d`` / ``8_30d`` /
                                          ``31_90d`` / ``91d_plus`` /
                                          ``unknown``.  ``unknown``
                                          holds events without an
                                          ``event_date``.  Each bucket
                                          carries
                                          ``total_events``,
                                          ``events_with_market_tickers``,
                                          and the three forward-cache
                                          counts.
      * ``latest_cache_date``           — ``MAX(date)`` over every row
                                          in ``price_cache``, ISO-8601,
                                          or ``None`` when the cache is
                                          empty.
      * ``cache_rows_auto_adjust_false``—  total ``COUNT(*)`` of
                                          ``price_cache`` rows persisted
                                          with ``auto_adjust=0``.  These
                                          are the rows
                                          :func:`reaction_profile_hydration.hydrate_per_ticker_profile`
                                          can actually read (it always
                                          calls
                                          ``read_window_no_fetch(...,
                                          auto_adjust=False)``).
      * ``cache_rows_auto_adjust_true`` — total ``COUNT(*)`` of rows
                                          with ``auto_adjust=1``.
                                          Invisible to the hydrator.
      * ``hydrated_visible_tickers_auto_adjust_false`` —
                                          distinct symbols in
                                          ``price_cache`` with at least
                                          one ``auto_adjust=0`` row.
      * ``cache_only_auto_adjust_true_tickers`` —
                                          distinct symbols that appear
                                          ONLY with ``auto_adjust=1``
                                          (i.e., the ticker has cached
                                          rows but the hydrator cannot
                                          see any of them).  Non-zero
                                          here is the early signal of an
                                          ingestion-flag regression
                                          where the cache write side
                                          flipped to adjusted-close
                                          while the hydrator is still
                                          reading raw closes (or vice
                                          versa).

    Forward-coverage semantics: a ticker satisfies the ``+Nd``
    condition when its newest cached row is dated at or after
    ``event_date + N`` business days.  Per-event truth is OR across
    the event's tickers.  Events without ``event_date`` or
    ``market_tickers`` still appear in ``total_events`` and the bucket
    breakdown but never count toward the forward-coverage totals.
    """
    import sqlite3
    import db as _db
    from db import _ticker_symbols

    empty = {
        "total_events":                              0,
        "events_with_market_tickers":                0,
        "unique_tickers":                            0,
        "tickers_with_cache_rows":                   0,
        "tickers_without_cache_rows":                0,
        "events_with_any_forward_cache":             0,
        "events_with_5d_forward_cache":              0,
        "events_with_20d_forward_cache":             0,
        "coverage_by_event_age_bucket":              _empty_age_bucket_set(),
        "latest_cache_date":                         None,
        "cache_rows_auto_adjust_false":              0,
        "cache_rows_auto_adjust_true":               0,
        "hydrated_visible_tickers_auto_adjust_false": 0,
        "cache_only_auto_adjust_true_tickers":       0,
    }

    try:
        conn = _db.connect_db()
    except sqlite3.Error:
        return _api._sanitize_floats(empty)

    try:
        try:
            event_rows = conn.execute(
                "SELECT market_tickers, event_date FROM events"
            ).fetchall()
        except sqlite3.Error:
            event_rows = []

        try:
            cache_max_rows = conn.execute(
                "SELECT ticker, MAX(date) FROM price_cache GROUP BY ticker"
            ).fetchall()
        except sqlite3.Error:
            cache_max_rows = []

        try:
            row = conn.execute(
                "SELECT MAX(date) FROM price_cache"
            ).fetchone()
            latest_cache_date = row[0] if row else None
        except sqlite3.Error:
            latest_cache_date = None

        # Auto-adjust split — cheap GROUP BY queries straight off the
        # ``price_cache`` table.  Two queries (row count + distinct
        # ticker per flag) so we can derive both the row totals and the
        # "ticker is invisible to hydrator" set without round-tripping.
        try:
            auto_adjust_count_rows = conn.execute(
                "SELECT auto_adjust, COUNT(*) FROM price_cache "
                "GROUP BY auto_adjust"
            ).fetchall()
        except sqlite3.Error:
            auto_adjust_count_rows = []

        try:
            auto_adjust_ticker_rows = conn.execute(
                "SELECT DISTINCT ticker, auto_adjust FROM price_cache"
            ).fetchall()
        except sqlite3.Error:
            auto_adjust_ticker_rows = []
    finally:
        conn.close()

    cache_rows_aa_false = 0
    cache_rows_aa_true  = 0
    for flag, n in auto_adjust_count_rows:
        try:
            flag_int = int(flag)
            n_int    = int(n)
        except (TypeError, ValueError):
            continue
        if flag_int == 0:
            cache_rows_aa_false += n_int
        elif flag_int == 1:
            cache_rows_aa_true += n_int

    tickers_with_aa_false: set[str] = set()
    tickers_with_aa_true:  set[str] = set()
    for ticker, flag in auto_adjust_ticker_rows:
        if not isinstance(ticker, str) or not ticker:
            continue
        try:
            flag_int = int(flag)
        except (TypeError, ValueError):
            continue
        sym = ticker.upper()
        if flag_int == 0:
            tickers_with_aa_false.add(sym)
        elif flag_int == 1:
            tickers_with_aa_true.add(sym)

    hydrated_visible_tickers = len(tickers_with_aa_false)
    cache_only_aa_true_tickers = len(
        tickers_with_aa_true - tickers_with_aa_false,
    )

    cache_max_by_ticker: dict[str, date] = {}
    for ticker, max_date_str in cache_max_rows:
        if not isinstance(ticker, str) or not isinstance(max_date_str, str):
            continue
        try:
            cache_max_by_ticker[ticker.upper()] = date.fromisoformat(
                max_date_str[:10],
            )
        except (ValueError, TypeError):
            continue

    total_events = len(event_rows)
    events_with_market_tickers = 0
    events_with_any_forward = 0
    events_with_5d_forward  = 0
    events_with_20d_forward = 0
    unique_tickers: set[str] = set()
    age_buckets = _empty_age_bucket_set()
    today = date.today()

    for market_tickers_blob, event_date_str in event_rows:
        symbols = _ticker_symbols(market_tickers_blob)
        has_tickers = bool(symbols)
        if has_tickers:
            events_with_market_tickers += 1
            unique_tickers.update(symbols)

        event_d: date | None = None
        if isinstance(event_date_str, str) and event_date_str:
            try:
                event_d = date.fromisoformat(event_date_str[:10])
            except (ValueError, TypeError):
                event_d = None

        any_forward = five_forward = twenty_forward = False
        if has_tickers and event_d is not None:
            plus_5  = _business_day_offset(event_d, 5)
            plus_20 = _business_day_offset(event_d, 20)
            for symbol in symbols:
                cache_max = cache_max_by_ticker.get(symbol)
                if cache_max is None:
                    continue
                if cache_max >= event_d:
                    any_forward = True
                if cache_max >= plus_5:
                    five_forward = True
                if cache_max >= plus_20:
                    twenty_forward = True
                if any_forward and five_forward and twenty_forward:
                    break

        if any_forward:
            events_with_any_forward += 1
        if five_forward:
            events_with_5d_forward += 1
        if twenty_forward:
            events_with_20d_forward += 1

        if event_d is None:
            bucket_label = _PRICE_CACHE_BUCKET_UNKNOWN
        else:
            bucket_label = _age_bucket_label((today - event_d).days)
        bucket = age_buckets[bucket_label]
        bucket["total_events"] += 1
        if has_tickers:
            bucket["events_with_market_tickers"] += 1
        if any_forward:
            bucket["events_with_any_forward_cache"] += 1
        if five_forward:
            bucket["events_with_5d_forward_cache"] += 1
        if twenty_forward:
            bucket["events_with_20d_forward_cache"] += 1

    tickers_with_cache_rows = sum(
        1 for sym in unique_tickers if sym in cache_max_by_ticker
    )

    return _api._sanitize_floats({
        "total_events":                              total_events,
        "events_with_market_tickers":                events_with_market_tickers,
        "unique_tickers":                            len(unique_tickers),
        "tickers_with_cache_rows":                   tickers_with_cache_rows,
        "tickers_without_cache_rows":                len(unique_tickers) - tickers_with_cache_rows,
        "events_with_any_forward_cache":             events_with_any_forward,
        "events_with_5d_forward_cache":              events_with_5d_forward,
        "events_with_20d_forward_cache":             events_with_20d_forward,
        "coverage_by_event_age_bucket":              age_buckets,
        "latest_cache_date":                         latest_cache_date,
        "cache_rows_auto_adjust_false":              cache_rows_aa_false,
        "cache_rows_auto_adjust_true":               cache_rows_aa_true,
        "hydrated_visible_tickers_auto_adjust_false": hydrated_visible_tickers,
        "cache_only_auto_adjust_true_tickers":       cache_only_aa_true_tickers,
    })


_EVENT_DATE_BACKFILL_EXAMPLE_LIMIT = 10
_EVENT_DATE_BACKFILL_CONFIDENCE_NOTE = (
    "Same-day proxy: events without an event_date can be backfilled from "
    "the headline timestamp's calendar date (timestamp[:10]). Confidence "
    "is highest for headlines that report a same-day event and lowest "
    "for headlines reporting a prior-day event or pre-/post-market "
    "moves; verify before persisting."
)


@router.get("/diagnostics/event-date-backfill-candidates")
def event_date_backfill_candidates():
    """Read-only candidate list for event_date backfill.

    Identifies events whose ``event_date`` is null or empty while
    ``timestamp`` is present, and proposes the timestamp's calendar
    date (``timestamp[:10]``) as the backfill candidate.  Pure read —
    issues only ``SELECT`` statements directly against the local
    SQLite DB, never imports ``price_cache`` or ``market_data``,
    never touches ``yfinance`` or the LLM, and never writes to the
    DB.  Does not implement the backfill itself.

    Top-level fields:

      * ``total_events_missing_event_date`` — count of events whose
        ``event_date`` is NULL or empty and whose ``timestamp`` is
        non-empty.
      * ``events_with_market_tickers``       — subset of the above
        whose ``market_tickers`` JSON decodes to at least one
        recognised symbol.
      * ``ticker_rows_blocked``              — total distinct ticker
        symbols across the qualifying events; the per-ticker
        hydration rows the absent ``event_date`` is currently
        blocking.
      * ``timestamp_same_day_confidence_note`` — fixed string
        describing the heuristic and its degradation modes.
      * ``examples`` — up to 10 candidate events ordered by ``id``
        ascending, each carrying ``event_id``, ``headline``,
        ``timestamp``, ``proposed_event_date`` (None when the
        timestamp does not parse as ISO YYYY-MM-DD), ``ticker_count``,
        and ``tickers`` (sorted symbol list).
    """
    import sqlite3
    import db as _db
    from db import _ticker_symbols

    empty = {
        "total_events_missing_event_date":    0,
        "events_with_market_tickers":         0,
        "ticker_rows_blocked":                0,
        "timestamp_same_day_confidence_note": _EVENT_DATE_BACKFILL_CONFIDENCE_NOTE,
        "examples":                           [],
    }

    try:
        conn = _db.connect_db()
    except sqlite3.Error:
        return _api._sanitize_floats(empty)

    try:
        try:
            rows = conn.execute(
                "SELECT id, headline, timestamp, market_tickers "
                "FROM events "
                "WHERE (event_date IS NULL OR event_date = '') "
                "  AND timestamp IS NOT NULL "
                "  AND timestamp != '' "
                "ORDER BY id ASC"
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        conn.close()

    total_missing = 0
    events_with_tickers = 0
    ticker_rows_blocked = 0
    examples: list[dict] = []

    for event_id, headline, timestamp, market_tickers_blob in rows:
        total_missing += 1
        symbols = _ticker_symbols(market_tickers_blob)
        symbol_count = len(symbols)
        if symbol_count > 0:
            events_with_tickers += 1
            ticker_rows_blocked += symbol_count

        if len(examples) < _EVENT_DATE_BACKFILL_EXAMPLE_LIMIT:
            proposed: str | None = None
            if isinstance(timestamp, str) and len(timestamp) >= 10:
                try:
                    proposed = date.fromisoformat(
                        timestamp[:10],
                    ).isoformat()
                except (ValueError, TypeError):
                    proposed = None
            examples.append({
                "event_id":            event_id,
                "headline":            headline if isinstance(headline, str) else "",
                "timestamp":           timestamp if isinstance(timestamp, str) else None,
                "proposed_event_date": proposed,
                "ticker_count":        symbol_count,
                "tickers":             sorted(symbols),
            })

    return _api._sanitize_floats({
        "total_events_missing_event_date":    total_missing,
        "events_with_market_tickers":         events_with_tickers,
        "ticker_rows_blocked":                ticker_rows_blocked,
        "timestamp_same_day_confidence_note": _EVENT_DATE_BACKFILL_CONFIDENCE_NOTE,
        "examples":                           examples,
    })


@router.get("/diagnostics/event-date-backfill-impact-preview")
def event_date_backfill_impact_preview():
    """Read-only impact preview for the event_date backfill plan.

    Reuses ``event_date_backfill.plan_event_date_backfill`` — a pure
    SELECT-only planner that never imports ``price_cache`` /
    ``market_data`` / ``yfinance``, never calls the LLM, and never
    writes to the DB.  This endpoint only reshapes the planner's
    output into impact-projection counts; it does not implement the
    write path.

    Top-level fields:

      * ``candidate_events`` — events whose ``event_date`` is NULL or
        empty AND whose ``timestamp`` is non-empty.  These are
        currently blocking per-ticker hydration.
      * ``ticker_rows_blocked`` — total distinct ticker symbols across
        the candidate events; the per-ticker hydration rows the absent
        ``event_date`` is currently blocking.  Counts every
        candidate's tickers, including rows whose timestamp does not
        parse — the absent ``event_date`` blocks hydration regardless
        of whether this planner can resolve the date.
      * ``proposed_updates`` — count of candidate events the planner
        would propose to update.  Excludes rows whose timestamp does
        not parse as ISO ``YYYY-MM-DD``.
      * ``projected_no_event_date_after`` — count of events that would
        still be missing ``event_date`` after applying every proposed
        update.  Equal to ``candidate_events - proposed_updates``.
      * ``projected_ticker_rows_unblocked`` — sum of ticker counts
        across the proposed updates; the per-ticker hydration rows
        that would become unblocked once the proposed dates are
        persisted.  Bounded above by ``ticker_rows_blocked``.
      * ``examples`` — up to 10 sample proposed updates ordered by
        ``id`` ascending, each carrying ``event_id``, ``headline``,
        ``timestamp``, ``proposed_event_date``, ``ticker_count`` and
        ``tickers`` (sorted symbol list).  Sampled from the proposed
        updates only, so unparseable-timestamp rows never appear.
    """
    from event_date_backfill import plan_event_date_backfill

    plan = plan_event_date_backfill()

    proposed = plan.get("proposed_updates") or []
    candidate_events = int(plan.get("total_candidates") or 0)
    ticker_rows_blocked = int(plan.get("ticker_rows_blocked") or 0)
    proposed_count = len(proposed)
    projected_unblocked = sum(
        int(p.get("ticker_count") or 0) for p in proposed
    )

    return _api._sanitize_floats({
        "candidate_events":                candidate_events,
        "ticker_rows_blocked":             ticker_rows_blocked,
        "proposed_updates":                proposed_count,
        "projected_no_event_date_after":   candidate_events - proposed_count,
        "projected_ticker_rows_unblocked": projected_unblocked,
        "examples":                        proposed[:_EVENT_DATE_BACKFILL_EXAMPLE_LIMIT],
    })
