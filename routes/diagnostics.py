"""Diagnostics routes — zero-cost introspection over the
headline_registry lifecycle.  See
docs/superpowers/specs/2026-05-03-headline-registry-design.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

import api as _api
from auto_backfill_config import load_auto_backfill_config
from auto_backfill_ledger import AutoBackfillLedger
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
    from db import DB_FILE, _db_ready
    if not _db_ready:
        return None
    try:
        with sqlite3.connect(DB_FILE) as conn:
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
        with sqlite3.connect(_db.DB_FILE) as conn:
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
        "latest_event_timestamp": None,
    }


def _compute_validation_status_stats() -> dict:
    """Single-pass aggregator scoring every archived event.

    Per-event scoring failures are skipped (the row contributes to
    ``total_events`` and ``latest_event_timestamp`` but not to status /
    reason counts) so a single bad row never breaks the aggregate.
    Structural failures (DB unreachable, import error) raise so the
    outer route handler can flip ``available`` to ``False``.
    """
    import sqlite3
    import db as _db
    from validation_status import VALID_STATUSES, score_validation_status

    if not _db._db_ready:
        return _validation_status_unavailable()

    with sqlite3.connect(_db.DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM events").fetchall()

    counts_by_status: dict[str, int] = {s: 0 for s in VALID_STATUSES}
    counts_by_reason: dict[str, int] = {}
    latest_ts: str | None = None
    total = 0

    for row in rows:
        try:
            event = _db._decode_event_row(row)
        except Exception:
            event = dict(row)
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

    with sqlite3.connect(_db.DB_FILE) as conn:
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

    with sqlite3.connect(_db.DB_FILE) as conn:
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
    latest_ts: str | None        = None

    for raw in rows:
        total_events += 1
        try:
            event = _db._decode_event_row(raw)
        except Exception:
            event = dict(raw)

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
        "latest_event_timestamp":                   latest_ts,
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
def auto_backfill_status():
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
        return _api._sanitize_floats(_compose_auto_backfill_status())
    except Exception:
        return _api._sanitize_floats(_auto_backfill_status_unavailable())


def _compose_auto_backfill_status() -> dict:
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
        "effective_status": cfg.effective_status,
        "last_skip_reason": state_snap.last_skip_reason,
        "last_error":       state_snap.last_error,
        "daily_remaining":  ledger_dec.remaining,
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
        "effective_status": cfg_block["effective_status"],
        "last_skip_reason": None,
        "last_error":       None,
        "daily_remaining":  0,
    }
