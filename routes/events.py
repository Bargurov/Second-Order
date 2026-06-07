"""Route handlers for /events/* endpoints."""

import io
import zipfile
from datetime import datetime

from fastapi import APIRouter, HTTPException, Path, Query, Depends
from fastapi.responses import Response

from db import (
    update_review, delete_event,
    find_related_events, find_similar_events,
    get_event_cascade, append_revisit_snapshot, load_revisit_snapshots,
    dedup_events, query_events_filtered,
)
from market_check import (
    _suppress_duplicate_tickers, _scrub_implausible_ticker_returns,
)
from movers_cache import is_mock_event
from family_inference import resolve_effective_family
from market_check_freshness import compute_staleness
from persistence_signal import classify_persistence_signal
from portfolio_flags import portfolio_flags
from thesis_state import (
    derive_thesis_state,
    derive_thesis_state_reason,
    derive_validation_rationale,
)
from validation_outcome import (
    _extract_primary_set,
    score_validation_label,
    score_weighted_evidence,
)
from validation_status import score_validation_status
from reaction_profile_hydration import build_reaction_profile_v1
from event_study_validation import build_event_study_validation

import api as _api
import headline_registry as _hr

router = APIRouter()


# Markers used by ``_is_mock_demo_or_degraded`` below.
#  * ``[mock:`` prefix on ``what_changed`` is set by ``analyze_event._mock``.
#  * ``showcase_seed_v1`` model tag + ``[DEMO] `` headline prefix come
#    from ``tools/seed_showcase_events.py`` (defense-in-depth — either
#    marker alone is enough so a hand-edited row still gets caught).
#  * The ``what_changed`` string written by ``analyze_event._degraded_fallback``
#    is the only stable signature for degraded rows (the
#    ``degraded: True`` boolean on the analysis result is not persisted
#    as its own DB column).
_DEMO_MODEL_TAG = "showcase_seed_v1"
_DEMO_HEADLINE_PREFIX = "[DEMO] "
_DEGRADED_WHAT_CHANGED_PREFIX = "Model returned a thin response"


def _is_demo_event(row: dict) -> bool:
    if (row.get("model") or "") == _DEMO_MODEL_TAG:
        return True
    headline = row.get("headline") or ""
    return isinstance(headline, str) and headline.startswith(_DEMO_HEADLINE_PREFIX)


def _is_degraded_event(row: dict) -> bool:
    what_changed = row.get("what_changed") or ""
    return (
        isinstance(what_changed, str)
        and what_changed.startswith(_DEGRADED_WHAT_CHANGED_PREFIX)
    )


def _is_mock_demo_or_degraded(row: dict) -> bool:
    return is_mock_event(row) or _is_demo_event(row) or _is_degraded_event(row)


# Operational archive-quality buckets exposed via ``/events?quality=...``.
# Distinct from the engine ``quality_tier`` filter — these classify rows
# by archive lifecycle state (analyzed → market-checked → clean) rather
# than by engine evidence tier.  See _matches_quality below for the
# precedence rules (degraded wins over data-state buckets so each row
# lands in at most one bucket).
_QUALITY_VALUES: frozenset[str] = frozenset({
    "pending", "degraded", "no_tickers", "market_checked", "clean",
})


def _has_market_check_stamp(row: dict) -> bool:
    return bool(row.get("last_market_check_at"))


def _has_any_market_tickers(row: dict) -> bool:
    tickers = row.get("market_tickers") or []
    return isinstance(tickers, list) and len(tickers) > 0


def _matches_quality(row: dict, quality: str) -> bool:
    """True when ``row`` lands in the requested archive-quality bucket.

    Bucket precedence — ``degraded`` wins over the data-state buckets so
    a degraded row that happens to carry tickers stays classified as
    ``degraded`` (a single row matches at most one bucket).  ``clean``
    is a strict subset of ``market_checked``.
    """
    is_degraded = _is_degraded_event(row)
    if quality == "degraded":
        return is_degraded
    if is_degraded:
        return False
    has_tx = _has_any_market_tickers(row)
    if quality == "market_checked":
        return has_tx
    if quality == "clean":
        return has_tx and not portfolio_flags(row)["low_information"]
    if quality == "no_tickers":
        return _has_market_check_stamp(row) and not has_tx
    if quality == "pending":
        return not _has_market_check_stamp(row) and not has_tx
    return False


def _score_validation(row: dict) -> str:
    """Derive validation status from stored market_tickers direction_tags.

    Delegates to the shared majority-rule helper in
    ``validation_outcome.py`` so ``/events`` and ``/portfolio`` can't
    drift apart on this classification.
    """
    return score_validation_label(row.get("market_tickers") or [])


def _calendar_for_event(event_date: str | None) -> list[dict] | None:
    """Return a macro-calendar slice anchored to the event's own date.

    Fresh-analysis events are captured near the release window so the
    default live calendar (anchored to ``date.today()``) covers them.
    A saved study from weeks or months ago falls outside the live
    ``[-3, 0]`` window — the builder would return ``{}`` even when the
    event clearly maps to a release.  Anchoring to ``event_date``
    replays the original window so a later-landing feed can backfill
    the block on refresh / revisit.

    Returns ``None`` on a missing or malformed date — the builder then
    falls back to its own ``get_macro_releases()`` default, which
    preserves fresh-analysis behaviour.
    """
    if not isinstance(event_date, str) or not event_date:
        return None
    try:
        from datetime import date
        from macro_calendar import get_macro_releases
        anchor = date.fromisoformat(event_date[:10])
        # The builder's window is ``-3 ≤ days_until ≤ 0`` so only the
        # three days preceding the anchor can match.  Passing
        # ``days_after=0`` guarantees no post-anchor release sneaks in
        # (that would only happen on a malformed date anyway).
        return get_macro_releases(today=anchor, days_before=3, days_after=0)
    except Exception:
        return None


def _refresh_macro_release_context(event_id: int, target: dict) -> None:
    """Re-derive ``macro_release_context`` from live calendar + facts.

    Called after refresh-market / refresh-overlays / revisit.  Two jobs:

      * **Backfill** — when the stored block is empty and a feed has
        since landed release facts that match the event's headline +
        ``event_date``, attach the block in place.  Anchoring the
        calendar lookup to ``event_date`` (rather than ``today``) is
        what lets this work for older studies that sit outside the
        live release window.

      * **Refresh** — when the stored block is already populated but
        newer facts (revisions, corrections) have landed, rewrite the
        block.

    Never overwrites a populated block with an empty one: if the
    builder can't produce a match on this pass (no known release, or
    the headline stopped matching any indicator keyword), the stored
    block is left intact.  Failures are swallowed so a transient
    backend issue can't fail an otherwise successful refresh.
    """
    try:
        from macro_surprise import build_event_macro_release_context
        from db import update_event_macro_release_context
        event_date = target.get("event_date")
        block = build_event_macro_release_context(
            {"headline": target.get("headline", ""),
             "event_date": event_date},
            _calendar_for_event(event_date),
        )
        if not block:
            # Builder produced no match — don't write {} back.  This
            # preserves (a) a populated block on an old row whose
            # calendar release is outside the live window, and
            # (b) the stable empty shape on rows that never mapped.
            return
        update_event_macro_release_context(event_id, block)
    except Exception:
        _api._log.warning(
            "macro_release_context refresh failed for event %d",
            event_id, exc_info=True,
        )


def _refresh_country_vulnerability_context(
    event_id: int, target: dict,
) -> None:
    """Re-derive ``country_vulnerability_context`` for a saved event.

    Backfills the block when an older row was saved before the
    country-backdrop fixture carried an entry for the event's
    country, OR refreshes it when a fixture value changed (stale flag
    flipped, tier shifted because a field was updated).  Never
    overwrites a populated block with ``{}`` — the builder only
    writes when it has a match.  Failures are swallowed so a
    transient backend issue can't fail an otherwise successful
    refresh.  Mirrors the macro-release / policy-timing refreshers.
    """
    try:
        from country_backdrop import build_event_country_vulnerability_context
        from db import update_event_country_vulnerability_context
        block = build_event_country_vulnerability_context({
            "headline":          target.get("headline", ""),
            "mechanism_summary": target.get("mechanism_summary", ""),
        })
        if not block:
            return
        update_event_country_vulnerability_context(event_id, block)
    except Exception:
        _api._log.warning(
            "country_vulnerability_context refresh failed for event %d",
            event_id, exc_info=True,
        )


def _refresh_policy_timing_context(event_id: int, target: dict) -> None:
    """Re-derive ``policy_timing_context`` from the tracked-policy
    registry.

    Called after refresh-market / refresh-overlays / revisit so:
      * a policy added to the registry AFTER the event was saved
        gets attached on the next refresh;
      * a policy whose status flipped (``effective`` → ``under_review``
        → ``expired``) rewrites the stored block.

    Never overwrites a previously-matched block with an empty one —
    if the current registry stops matching (keyword registry narrowed,
    etc.) the stored block is left intact.  Failures are swallowed so
    a transient backend issue can't fail an otherwise successful
    refresh.  Mirrors ``_refresh_macro_release_context``.
    """
    try:
        from policy_timing import build_event_policy_timing_context
        from db import update_event_policy_timing_context
        block = build_event_policy_timing_context({
            "headline":   target.get("headline", ""),
            "event_date": target.get("event_date"),
        })
        if not block:
            return
        update_event_policy_timing_context(event_id, block)
    except Exception:
        _api._log.warning(
            "policy_timing_context refresh failed for event %d",
            event_id, exc_info=True,
        )


def _normalise_date_bound(value: str | None, *, field: str) -> str | None:
    """Coerce a user-supplied date filter to a calendar-day string.

    Accepts ``YYYY-MM-DD`` or any ISO 8601 datetime (``YYYY-MM-DDTHH:MM:SS``
    with or without timezone suffix) and returns only the date portion.
    Prevents the SQL layer from appending ``T23:59:59`` onto an already-
    datetime string (the audit blocker).

    Raises HTTPException(400) on an unparseable input.  None passes
    through unchanged.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(400, f"{field} must be a non-empty string")
    raw = value.strip()
    # Fast-path: already a pure date.
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        try:
            datetime.strptime(raw, "%Y-%m-%d")
            return raw
        except ValueError:
            raise HTTPException(400, f"{field} must be YYYY-MM-DD")
    # Allow datetime, with or without "Z" / offset; take the date.
    candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            dt = datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                400,
                f"{field} must be YYYY-MM-DD or ISO 8601 datetime",
            )
    return dt.date().isoformat()


@router.get("/events")
def events(
    limit:       int        = Query(25, ge=1, le=100),
    offset:      int        = Query(0, ge=0),
    search:      str | None = Query(None),
    stage:       str | None = Query(None),
    persistence: str | None = Query(None),
    confidence:  str | None = Query(None),
    rating:      str | None = Query(None),
    date_from:   str | None = Query(None),
    date_to:     str | None = Query(None),
    validated:   str | None = Query(None, pattern="^(validated|contradicted|unresolved)$"),
    validation_status_v2: str | None = Query(
        None,
        pattern="^(validated|contradicted|unresolved|pending)$",
        description=(
            "Filter rows by the four-label scorer's status "
            "(validated | contradicted | unresolved | pending).  Composes "
            "with the legacy ``validated`` filter by AND when both are "
            "supplied; the legacy filter still binds to the three-label "
            "string under ``validation_status``.  See "
            "docs/validation_status_design.md."
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
        description="Filter by engine quality_tier.",
    ),
    tradable: bool | None = Query(
        None,
        description="Filter by actionability_check.tradable.",
    ),
    mechanism_subtype: str | None = Query(
        None,
        description="Filter by engine mechanism_subtype.",
    ),
    include_mock: bool = Query(
        False,
        description=(
            "Include mock / demo / degraded analysis rows in the listing. "
            "Default False — those rows stay accessible by id at "
            "/events/{event_id} so detail review still works."
        ),
    ),
    quality: str | None = Query(
        None,
        description=(
            "Narrow the archive listing to one operational quality bucket: "
            "pending | degraded | no_tickers | market_checked | clean.  "
            "``quality=degraded`` is the explicit opt-in to surface "
            "degraded rows — mock + demo stay hidden unless "
            "``include_mock=true`` is also set.  Bucket precedence: a "
            "degraded row stays in ``degraded`` even when it carries "
            "tickers, so each row matches at most one bucket."
        ),
    ),
):
    # Normalise date filters up-front — anything other than
    # YYYY-MM-DD gets converted to its calendar-day form so the SQL
    # layer's ``+ "T23:59:59"`` append never concatenates onto an
    # already-full datetime.
    date_from = _normalise_date_bound(date_from, field="date_from")
    date_to   = _normalise_date_bound(date_to,   field="date_to")
    if not isinstance(quality_tier, str):
        quality_tier = None
    if not isinstance(mechanism_subtype, str):
        mechanism_subtype = None
    if not isinstance(tradable, bool):
        tradable = None
    if not isinstance(quality, str):
        quality = None
    if not isinstance(validation_status_v2, str):
        validation_status_v2 = None
    if quality_tier is not None:
        from low_information_gate import EVIDENCE_QUALITY_TIERS
        if quality_tier not in EVIDENCE_QUALITY_TIERS:
            raise HTTPException(
                400,
                f"quality_tier must be one of {list(EVIDENCE_QUALITY_TIERS)}",
            )

    if quality is not None and quality not in _QUALITY_VALUES:
        raise HTTPException(
            400,
            f"quality must be one of {sorted(_QUALITY_VALUES)}",
        )

    rows = query_events_filtered(
        search=search,
        stage=stage,
        persistence=persistence,
        confidence=confidence,
        rating=rating,
        date_from=date_from,
        date_to=date_to,
    )

    # Dedup first so total counts reflect the deduped universe.
    rows = dedup_events(rows)

    # Read-time expiry filter for low-impact analyzed events.  Applied
    # AFTER dedup and BEFORE the offset/limit slice so ``total`` reflects
    # the post-expiry universe and pagination yields stable page sizes.
    # Detail-by-id (/events/{event_id}) does NOT call this filter — see
    # CLAUDE.md frozen UI boundary on detail visibility.
    rows = _hr.filter_expired_low_impact(rows)

    # Mock / demo / degraded suppression — hide obvious archive
    # pollution from the default listing.  Same contract as the expiry
    # filter above: applied AFTER dedup and BEFORE the offset/limit
    # slice so ``total`` reflects the post-suppression universe.  Rows
    # are NOT deleted; ``include_mock=true`` brings them back, and
    # /events/{event_id} keeps serving them regardless so review by id
    # still works.
    #
    # Carve-out: ``quality=degraded`` is the documented opt-in to drill
    # into the degraded bucket without flipping ``include_mock``.  Mock
    # and demo rows stay suppressed regardless — only the degraded
    # subset of the suppression is lifted.
    if not include_mock:
        if quality == "degraded":
            rows = [
                r for r in rows
                if not (is_mock_event(r) or _is_demo_event(r))
            ]
        else:
            rows = [r for r in rows if not _is_mock_demo_or_degraded(r)]

    # Quality bucket filter — operator-driven narrowing on top of the
    # suppression above.  Applied BEFORE the offset/limit slice so
    # ``total`` reflects the post-filter universe; doesn't require row
    # decoration so it stays on the fast path.
    if quality is not None:
        rows = [r for r in rows if _matches_quality(r, quality)]

    # Build the event→active-windows index once per request so we
    # can (a) filter by ``mover_window`` without per-row recomputation
    # and (b) surface the archive-wide ``mover_window_counts`` facet.
    # Reads from the already-cached mover slices; one try/except so a
    # flaky slice can't 500 the archive response.
    from mover_context import MOVER_WINDOW_IDS, build_event_window_index
    event_window_index: dict[int, list[str]] = {}
    try:
        from routes.movers import load_ui_slices_for_event_context
        event_window_index = build_event_window_index(
            load_ui_slices_for_event_context()
        )
    except Exception:
        event_window_index = {}

    mover_window_counts: dict[str, int] = {w: 0 for w in MOVER_WINDOW_IDS}
    for row in rows:
        for w in event_window_index.get(row.get("id"), []):
            if w in mover_window_counts:
                mover_window_counts[w] += 1

    engine_filters_active = (
        quality_tier is not None
        or tradable is not None
        or mechanism_subtype is not None
    )

    def _engine_compact(row: dict) -> dict:
        from engine_phase_surface import decorate_compact
        compact = decorate_compact(row)
        raw_tier = row.get("quality_tier")
        if isinstance(raw_tier, str):
            from low_information_gate import EVIDENCE_QUALITY_TIERS
            if raw_tier in EVIDENCE_QUALITY_TIERS:
                compact["quality_tier"] = raw_tier
        raw_ac = row.get("actionability_check")
        if isinstance(raw_ac, dict) and isinstance(raw_ac.get("tradable"), bool):
            compact["actionability_check"] = {"tradable": raw_ac["tradable"]}
        if "mechanism_subtype" in row:
            raw_subtype = row.get("mechanism_subtype")
            compact["mechanism_subtype"] = (
                raw_subtype if isinstance(raw_subtype, str) and raw_subtype else None
            )
        return compact

    def _matches_engine_filters(row: dict) -> bool:
        compact = row.get("_engine_compact")
        if not isinstance(compact, dict):
            compact = _engine_compact(row)
            row["_engine_compact"] = compact
        if quality_tier is not None and compact.get("quality_tier") != quality_tier:
            return False
        if tradable is not None:
            ac = compact.get("actionability_check") or {}
            if bool(ac.get("tradable", False)) != bool(tradable):
                return False
        if mechanism_subtype is not None and compact.get("mechanism_subtype") != mechanism_subtype:
            return False
        return True

    def _surface_engine_compact(row: dict) -> None:
        compact = row.get("_engine_compact")
        if not isinstance(compact, dict):
            compact = _engine_compact(row)
            row["_engine_compact"] = compact
        row["quality_tier"] = compact.get("quality_tier")
        row["quality_warnings"] = list(compact.get("quality_warnings") or [])
        row["actionability_check"] = compact.get("actionability_check") or {
            "tradable": False,
        }
        row["mechanism_subtype"] = compact.get("mechanism_subtype")

    # Any filter that requires per-row Python scoring forces a whole-
    # archive decorate-then-paginate pass.  ``validated`` already has
    # that contract; ``mover_window`` / engine-derived / four-label
    # ``validation_status_v2`` filters join it for the same reason.
    needs_full_scan = (
        bool(validated)
        or mover_window is not None
        or engine_filters_active
        or validation_status_v2 is not None
    )

    if needs_full_scan:
        for row in rows:
            _decorate_row(row)
            row["active_mover_windows"] = list(
                event_window_index.get(row.get("id"), [])
            )
            if engine_filters_active:
                _surface_engine_compact(row)
        if validated:
            rows = [r for r in rows if r["validation_status"] == validated]
        if validation_status_v2 is not None:
            # ``validation_status_v2`` is the dict from
            # ``score_validation_status``; the ``status`` key carries
            # the four-label string the filter binds against.  Default
            # to ``""`` so a row missing the block (shouldn't happen
            # post-decoration, but defensive) cleanly drops out.
            rows = [
                r for r in rows
                if (r.get("validation_status_v2") or {}).get("status")
                    == validation_status_v2
            ]
        if mover_window is not None:
            rows = [
                r for r in rows
                if mover_window in (r.get("active_mover_windows") or [])
            ]
        if engine_filters_active:
            rows = [r for r in rows if _matches_engine_filters(r)]
            for r in rows:
                r.pop("_engine_compact", None)
        total = len(rows)
        items = rows[offset: offset + limit]
    else:
        # Fast path: paginate first so we only decorate the page the
        # caller actually asked for.
        total = len(rows)
        items = rows[offset: offset + limit]
        for row in items:
            _decorate_row(row)
            row["active_mover_windows"] = list(
                event_window_index.get(row.get("id"), [])
            )

    response: dict = {
        "items":  items,
        "total":  total,
        "offset": offset,
        "limit":  limit,
    }
    # Keep the default response shape byte-stable when the mover
    # filter isn't in use — only attach the facet block once the
    # mover_window filter is active so existing consumers don't see
    # a new top-level key unprompted.
    if mover_window is not None:
        response["mover_window_counts"] = mover_window_counts
    return _api._sanitize_floats(response)


def _decorate_row(row: dict) -> None:
    """Attach freshness, persistence, and validation signals in place."""
    # Deterministic family fallback — only lifts stored ``"none"`` rows
    # using evidence already on the event (headline, mechanism_summary,
    # transmission chain, proof/falsifier text, asset buckets).  No DB
    # writeback; the upgrade lives in the response only.
    row["mechanism_family"] = resolve_effective_family(row)
    sig = compute_staleness(row)
    row["stale_signal"]       = sig["status"]
    row["hours_since_check"]  = sig.get("hours_since_check")
    row["event_age_days"]     = sig.get("event_age_days")
    row["persistence_signal"] = classify_persistence_signal(row)
    row["validation_status"]  = _score_validation(row)
    # Four-label status block from validation_status.score_validation_status.
    # Additive: keyed under a new field so the legacy
    # ``validation_status`` STRING above and any client filtering
    # against it stay stable.  The scorer is pure (no DB / provider
    # calls); it reads the row's tickers + age anchor and returns the
    # full {status, reason, ratio, counts, event_age_days,
    # pending_max_days} block.  See docs/validation_status_design.md.
    row["validation_status_v2"] = score_validation_status(row)
    # Weighted event-level evidence — additive, keyed under a new block
    # so the existing validation_status string stays stable.
    row["weighted_evidence"]  = score_weighted_evidence(
        row.get("market_tickers") or [],
        explicit_primary=_extract_primary_set(row),
    )
    # Proof-discipline flags — additive booleans so the UI can
    # highlight well-structured analyses without reshaping existing
    # fields.  See portfolio_flags.py for the classification rules.
    flags = portfolio_flags(row)
    row["has_proof_set"]   = flags["has_proof_set"]
    row["has_falsifiers"]  = flags["has_falsifiers"]
    row["low_information"] = flags["low_information"]
    # Single-word thesis summary derived from the decorated fields
    # above — kept additive so existing keys stay stable.  The
    # accompanying ``thesis_state_reason`` is a one-line explanation
    # derived from the same stored fields; consumers that don't read
    # it can ignore the additive key.
    state = derive_thesis_state(row)
    row["thesis_state"]        = state
    row["thesis_state_reason"] = derive_thesis_state_reason(row, state=state)
    row["validation_rationale"] = derive_validation_rationale(row, state=state)


@router.get("/events/export")
def events_export(
    format: str = Query("json", pattern="^(json|csv)$"),
    limit: int = Query(10000, ge=1, le=100000),
):
    from events_export import build_csv_export, build_json_export, load_events_for_export
    evs = load_events_for_export(limit=limit)
    if format == "csv":
        body = build_csv_export(evs)
        return Response(content=body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="events_export.csv"'})
    # Scrub NaN / inf before the response leaves the API.  Persisted
    # market_ticker returns and derived overlays can carry NaN when a
    # ticker has no price history (e.g. delisted symbols, stress-tape
    # gaps); stdlib json rejects those as non-compliant on strict
    # consumers (browsers, JSON.parse).  ``_sanitize_floats`` is the
    # same helper the diagnostics layer uses.
    return _api._sanitize_floats(build_json_export(evs))


@router.get("/events/{event_id}")
def get_event_detail(event_id: int = Path(..., ge=1)):
    """Return the full saved event row by id.

    Surfaces the proof-structure fields (``primary_assets`` /
    ``secondary_assets`` / ``hedge_or_signal_assets`` /
    ``minimum_proof_set`` / ``key_falsifiers`` / ``competing_thesis``)
    alongside every other persisted field.  Old rows that pre-date
    these columns read back with stable empty defaults from
    ``_decode_event_row`` and ``_LLM_CORE_DEFAULTS``.
    """
    ev = _api.load_event_by_id(event_id)
    if not ev:
        raise HTTPException(404, f"Event {event_id} not found.")

    # Mover provenance — if the event is currently active in any
    # mover surface (today / market / weekly / persistent), attach a
    # ``mover_context`` block explaining why.  Uses the already-cached
    # mover slices (no new market fetches); an inactive event gets
    # the stable empty-shape default.  Late import keeps routes/events
    # import-light and sidesteps any circular-import risk during
    # module load.
    try:
        from mover_context import build_mover_context, empty_mover_context
        from routes.movers import load_ui_slices_for_event_context
        ev["mover_context"] = build_mover_context(
            event_id, load_ui_slices_for_event_context(),
        )
    except Exception:
        from mover_context import empty_mover_context
        ev["mover_context"] = empty_mover_context()

    # Always-shaped proof / falsifier objects — low-information rows
    # and pre-evaluator rows that stored ``{}`` get coerced to the
    # full canonical shape (every documented key present, ``items``
    # always a list).  Applied at the HTTP boundary only; the DB layer
    # still carries ``{}`` for "never evaluated" rows.
    from proof_evaluator import coerce_falsifier_status, coerce_proof_status
    ev["proof_status"]     = coerce_proof_status(ev.get("proof_status"))
    ev["falsifier_status"] = coerce_falsifier_status(ev.get("falsifier_status"))

    # Stable canonical shape for the macro release context block — DB
    # stores ``{}`` for events that don't map to any release; the route
    # boundary inflates that to the full keyset (every field present,
    # values None / "") so consumers don't branch on shape.
    from macro_surprise import coerce_macro_release_context
    ev["macro_release_context"] = coerce_macro_release_context(
        ev.get("macro_release_context"),
    )

    # Same pattern for the policy timing context block.
    from policy_timing import coerce_policy_timing_context
    ev["policy_timing_context"] = coerce_policy_timing_context(
        ev.get("policy_timing_context"),
    )

    # And for the country vulnerability context block.
    from country_backdrop import coerce_country_vulnerability_context
    ev["country_vulnerability_context"] = coerce_country_vulnerability_context(
        ev.get("country_vulnerability_context"),
    )

    # Deterministic family fallback — improves ``"none"`` rows in the
    # response path using stored evidence only.  Does not write back
    # to the DB; old rows stay byte-for-byte unchanged on disk.
    ev["mechanism_family"] = resolve_effective_family(ev)

    # Engine-phase fields — re-derive the composers / lift nested
    # blocks so ``/events/{id}`` carries the same engine shape that
    # ``_finalize_analysis`` emits at analysis time.  Runs BEFORE the
    # thesis-state derivation below so ``validation_rationale`` is
    # then overwritten with the real value when one is derivable.
    from engine_phase_surface import decorate_full as _decorate_full
    _decorate_full(ev)

    # Single-word thesis summary — derived from the event's stored
    # fields alone (weighted evidence + proof flags + persistence +
    # staleness).  Additive: all pre-existing keys stay intact.
    state = derive_thesis_state(ev)
    ev["thesis_state"]        = state
    ev["thesis_state_reason"] = derive_thesis_state_reason(ev, state=state)
    ev["validation_rationale"] = derive_validation_rationale(ev, state=state)
    # Four-label status block — same key + shape the listing surfaces
    # via _decorate_row above so list-vs-detail consumers can bind to a
    # single contract.  Pure read (see docs/validation_status_design.md).
    ev["validation_status_v2"] = score_validation_status(ev)
    # Reaction-profile v1 block — detail-only.  Per-ticker null-safe
    # shape when raw closes aren't stored (always the case today); the
    # block ships anyway so consumers can bind to a stable key set
    # before a future task hydrates closes from price_cache.  See
    # docs/reaction_profile_design.md.
    ev["reaction_profile_v1"] = build_reaction_profile_v1(ev)
    # Event-study point estimates — detail-only, additive sibling block
    # (E5).  Surfaces the SAME gated payload as GET /events/{id}/event-study:
    # per-horizon abnormal_return / sar / car for compute-ready events, else
    # an explicit insufficient_data block with blocking_reasons.  Point
    # estimates only — the gate marks cross_sectional_inference unavailable
    # at n=1 and never claims confirmed/validated/significant.  Read-only
    # (plain price_cache SELECTs; no provider, no DB write).  Wrapped
    # defensively so an unexpected engine error degrades to a stable
    # insufficient block rather than 500-ing the whole detail response.
    try:
        ev["event_study"] = build_event_study_validation(ev)
    except Exception:
        ev["event_study"] = {
            "status":           "insufficient_data",
            "event_id":         ev.get("id"),
            "blocking_reasons": ["event_study_error"],
        }
    return _api._sanitize_floats(ev)


@router.patch("/events/{event_id}/review", dependencies=[Depends(_api.require_admin_token)])
def review(
    event_id: int = Path(..., ge=1),
    req: _api.ReviewRequest = ...,
):
    if req.rating is None and req.notes is None:
        raise HTTPException(400, "Provide at least one of rating or notes.")
    updated = update_review(event_id, rating=req.rating, notes=req.notes)
    if not updated:
        raise HTTPException(404, f"Event {event_id} not found.")
    return {"ok": True, "event_id": event_id}


@router.delete("/events/{event_id}", dependencies=[Depends(_api.require_admin_token)])
def delete_event_endpoint(event_id: int):
    deleted = delete_event(event_id)
    if not deleted:
        raise HTTPException(404, f"Event {event_id} not found.")
    _api._WEEKLY_MOVERS_CACHE["data"] = None
    _api._YEARLY_MOVERS_CACHE["data"] = None
    _api._PERSISTENT_MOVERS_CACHE["data"] = None
    _api._TODAYS_MOVERS_CACHE["data"] = None
    return {"ok": True, "event_id": event_id}


@router.get("/events/{event_id}/export/text")
def export_event_text(event_id: int):
    ev = _api.load_event_by_id(event_id)
    if not ev:
        raise HTTPException(404, f"Event {event_id} not found.")
    body = _api._build_event_text_memo(ev)
    filename = _api._safe_event_filename(event_id, ev.get("headline", ""), "txt")
    return Response(content=body, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/events/{event_id}/export/markdown")
def export_event_markdown(event_id: int):
    ev = _api.load_event_by_id(event_id)
    if not ev:
        raise HTTPException(404, f"Event {event_id} not found.")
    body = _api._build_event_markdown_memo(ev)
    filename = _api._safe_event_filename(event_id, ev.get("headline", ""), "md")
    return Response(content=body, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/events/{event_id}/export/memo")
def export_event_memo(event_id: int):
    ev = _api.load_event_by_id(event_id)
    if not ev:
        raise HTTPException(404, f"Event {event_id} not found.")
    body = _api._build_event_research_memo(ev)
    filename = _api._safe_event_filename(event_id, ev.get("headline", ""), "md")
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="memo_{filename}"'},
    )


@router.post("/events/export/markdown")
def export_events_markdown_bulk(req: _api.BulkExportRequest):
    found_list: list[dict] = []
    skipped_list: list[int] = []
    for eid in req.event_ids:
        ev = _api.load_event_by_id(eid)
        if ev:
            found_list.append(ev)
        else:
            skipped_list.append(eid)
    if not found_list:
        raise HTTPException(404, "No valid events found for the requested IDs.")
    sections = [_api._build_event_markdown_memo(ev) for ev in found_list]
    body = "\n\n---\n\n".join(sections)
    return Response(content=body, media_type="text/markdown; charset=utf-8",
                    headers={
                        "Content-Disposition": 'attachment; filename="research_packet.md"',
                        "X-Skipped-Ids": ",".join(str(i) for i in skipped_list) if skipped_list else "",
                    })


@router.post("/events/export/zip")
def export_events_zip(req: _api.BulkExportRequest):
    found, skipped = [], []
    for eid in req.event_ids:
        ev = _api.load_event_by_id(eid)
        if ev:
            found.append(ev)
        else:
            skipped.append(eid)
    if not found:
        raise HTTPException(404, "No valid events found for the requested IDs.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ev in found:
            name = _api._safe_event_filename(ev["id"], ev.get("headline", ""), "md")
            zf.writestr(name, _api._build_event_markdown_memo(ev))
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={
                        "Content-Disposition": 'attachment; filename="research_packet.zip"',
                        "X-Skipped-Ids": ",".join(str(i) for i in skipped) if skipped else "",
                    })


@router.post("/events/export/portfolio")
def export_events_portfolio(req: _api.BulkExportRequest):
    found_list: list[dict] = []
    skipped_list: list[int] = []
    for eid in req.event_ids:
        ev = _api.load_event_by_id(eid)
        if ev:
            found_list.append(ev)
        else:
            skipped_list.append(eid)
    if not found_list:
        raise HTTPException(404, "No valid events found for the requested IDs.")
    body = _api._build_portfolio_markdown(found_list)
    return Response(content=body, media_type="text/markdown; charset=utf-8",
                    headers={
                        "Content-Disposition": 'attachment; filename="research_portfolio.md"',
                        "X-Skipped-Ids": ",".join(str(i) for i in skipped_list) if skipped_list else "",
                    })


@router.post("/events/export/deck")
def export_events_deck(req: _api.BulkExportRequest):
    from presentation_deck import build_presentation_deck
    found_list: list[dict] = []
    skipped_list: list[int] = []
    for eid in req.event_ids:
        ev = _api.load_event_by_id(eid)
        if ev:
            found_list.append(ev)
        else:
            skipped_list.append(eid)
    if not found_list:
        raise HTTPException(404, "No valid events found for the requested IDs.")
    body = build_presentation_deck(found_list)
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="briefing_deck.md"',
            "X-Skipped-Ids": ",".join(str(i) for i in skipped_list) if skipped_list else "",
        },
    )


@router.get("/events/{event_id}/export/json")
def export_event_json(event_id: int):
    ev = _api.load_event_by_id(event_id)
    if not ev:
        raise HTTPException(404, f"Event {event_id} not found.")
    return _api._sanitize_floats(_api._build_event_json_export(ev))


@router.get("/events/{event_id}/export/csv")
def export_event_csv(event_id: int):
    ev = _api.load_event_by_id(event_id)
    if not ev:
        raise HTTPException(404, f"Event {event_id} not found.")
    body = _api._build_event_csv_export(ev)
    filename = _api._safe_event_filename(event_id, ev.get("headline", ""), "csv")
    return Response(content=body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/events/{event_id}/related")
def related(event_id: int):
    target = _api.load_event_by_id(event_id)
    if not target:
        raise HTTPException(404, f"Event {event_id} not found.")
    return find_related_events(event_id, target["headline"])


@router.get("/events/{event_id}/similar")
def similar(
    event_id: int = Path(..., ge=1),
    limit: int = Query(5, ge=1, le=50),
):
    """Return up to ``limit`` archived events most similar to
    ``event_id``, scored deterministically from stored fields only.

    Pure read — no LLM call, no provider call, no DB write.  See
    ``db.find_similar_events`` for the score formula.  Distinct from
    ``/events/{id}/related`` (Jaccard on headline only) — this surface
    blends headline / mechanism / tickers / stage / persistence so the
    UI can show a richer neighbourhood without a paid lookup.
    """
    result = find_similar_events(event_id, limit=limit)
    if result is None:
        raise HTTPException(404, f"Event {event_id} not found.")
    return _api._sanitize_floats(result)


@router.get("/events/{event_id}/cascade")
def cascade(event_id: int):
    result = get_event_cascade(event_id)
    if result["root"] is None:
        raise HTTPException(404, f"Event {event_id} not found.")
    return _api._sanitize_floats(result)


@router.get("/events/{event_id}/event-study")
def event_study(event_id: int):
    """Gated, read-only single-event event-study (SAR/CAR) proof.

    Dedicated single-event route.  As of E5 the SAME payload is also
    attached to ``GET /events/{id}`` under the additive ``event_study``
    key, so detail consumers need no second round-trip; the UI does not
    render it yet.  Reaches the :mod:`stats.event_study` engine for one
    event when readiness gates pass, and returns an explicit
    ``insufficient_data`` object with blocking reasons otherwise.  Does
    not alter ``validation_status_v2`` or ``reaction_profile_v1``; no
    provider call, no DB write.
    """
    target = _api.load_event_by_id(event_id)
    if not target:
        raise HTTPException(404, f"Event {event_id} not found.")
    return _api._sanitize_floats(build_event_study_validation(target))


@router.get("/events/{event_id}/backtest")
def backtest(event_id: int, force: bool = Query(False)):
    result = _api._backtest_one(event_id, force=force)
    if result.get("error") == "not found":
        raise HTTPException(404, f"Event {event_id} not found.")
    return _api._sanitize_floats(result)


@router.post("/events/{event_id}/refresh-market", dependencies=[Depends(_api.require_admin_token)])
def refresh_market_endpoint(event_id: int, force: bool = Query(False)):
    target = _api.load_event_by_id(event_id)
    if not target:
        raise HTTPException(404, f"Event {event_id} not found.")
    event_date = target.get("event_date")
    if not event_date:
        ts = target.get("timestamp", "")
        if ts:
            event_date = ts[:10]
    target_for_refresh = dict(target)
    if event_date:
        target_for_refresh["event_date"] = event_date
    try:
        market_block = _api.refresh_market_for_saved_event(
            target_for_refresh, force=force,
            followup_check_fn=_api.followup_check, market_check_fn=_api.market_check,
        )
    except Exception:
        _api._log.warning("refresh-market: failed for event %d", event_id, exc_info=True)
        raise HTTPException(502, "Market data provider failed.")
    tickers = _scrub_implausible_ticker_returns(market_block.get("tickers", []))
    tickers = _suppress_duplicate_tickers(tickers)
    _refresh_macro_release_context(event_id, target)
    _refresh_policy_timing_context(event_id, target)
    _refresh_country_vulnerability_context(event_id, target)
    return _api._sanitize_floats({
        "event_id": event_id,
        "market": {
            "note": market_block.get("note", ""), "details": {}, "tickers": tickers,
            "last_market_check_at": market_block.get("last_market_check_at"),
            "market_check_staleness": market_block.get("market_check_staleness"),
        },
    })


@router.post("/events/{event_id}/refresh-overlays", dependencies=[Depends(_api.require_admin_token)])
def refresh_overlays_endpoint(event_id: int):
    """Recompute macro-tier overlays on a saved event against today's tape.

    Distinct from ``POST /events/{id}/refresh-market``:

      * refresh-market refreshes ticker returns and refuses frozen rows;
      * refresh-overlays only recomputes the rates/stress/credit-driven
        overlay blocks and is safe on frozen rows — the LLM thesis and
        stored tickers are never touched.

    Returns 409 for events without a parsable anchor (``legacy`` bucket),
    502 on unexpected refresh failure, otherwise the refresh summary
    dict produced by :mod:`frozen_overlay_refresh`.
    """
    target = _api.load_event_by_id(event_id)
    if not target:
        raise HTTPException(404, f"Event {event_id} not found.")
    try:
        from frozen_overlay_refresh import refresh_overlays_for_event
        result = refresh_overlays_for_event(target)
    except Exception:
        _api._log.warning(
            "refresh-overlays: failed for event %d", event_id, exc_info=True,
        )
        raise HTTPException(502, "Overlay refresh failed.")
    eligibility = result.get("eligibility") or {}
    if not eligibility.get("eligible"):
        raise HTTPException(
            409,
            eligibility.get("reason", "Event not eligible for overlay refresh."),
        )
    _refresh_macro_release_context(event_id, target)
    _refresh_policy_timing_context(event_id, target)
    _refresh_country_vulnerability_context(event_id, target)
    return _api._sanitize_floats(result)


@router.get("/events/{event_id}/revisit")
def get_revisit_timeline(event_id: int):
    target = _api.load_event_by_id(event_id)
    if not target:
        raise HTTPException(404, f"Event {event_id} not found.")
    return _api._sanitize_floats({"event_id": event_id, "snapshots": load_revisit_snapshots(event_id)})


@router.post("/events/{event_id}/revisit", dependencies=[Depends(_api.require_admin_token)])
def capture_revisit_snapshot(event_id: int):
    target = _api.load_event_by_id(event_id)
    if not target:
        raise HTTPException(404, f"Event {event_id} not found.")
    event_date = target.get("event_date")
    if not event_date:
        ts = target.get("timestamp", "")
        if ts:
            event_date = ts[:10]
    tickers = target.get("market_tickers", [])
    if not event_date or not tickers:
        return _api._sanitize_floats({
            "event_id": event_id, "snapshots": load_revisit_snapshots(event_id),
            "note": "No event_date or tickers — cannot capture.",
        })
    try:
        outcomes = _api.followup_check(tickers, event_date)
    except Exception:
        _api._log.warning("revisit: followup_check failed for event %d", event_id, exc_info=True)
        raise HTTPException(502, "Market data provider failed.")
    now_iso = datetime.now().isoformat(timespec="seconds")
    for day in _api._REVISIT_DAYS:
        return_key = f"return_{day}d"
        day_tickers = [
            {"symbol": o["symbol"], "role": o.get("role", "beneficiary"), return_key: o[return_key], "direction": o.get("direction")}
            for o in outcomes if o.get(return_key) is not None
        ]
        if day_tickers:
            append_revisit_snapshot(event_id, {"day": day, "captured_at": now_iso, "tickers": day_tickers})
    _refresh_macro_release_context(event_id, target)
    _refresh_policy_timing_context(event_id, target)
    _refresh_country_vulnerability_context(event_id, target)
    return _api._sanitize_floats({"event_id": event_id, "snapshots": load_revisit_snapshots(event_id)})
