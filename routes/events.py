"""Route handlers for /events/* endpoints."""

import io
import zipfile
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from db import (
    load_recent_events, update_review, delete_event,
    find_related_events, get_event_cascade, append_revisit_snapshot, load_revisit_snapshots,
    dedup_events,
)
from market_check import (
    _suppress_duplicate_tickers, _scrub_implausible_ticker_returns,
)
from market_check_freshness import compute_staleness
from persistence_signal import classify_persistence_signal

import api as _api

router = APIRouter()


@router.get("/events")
def events(limit: int = 25):
    cap = min(limit, 100)
    # Over-fetch so dedup doesn't reduce the returned count below what was asked for.
    rows = load_recent_events(limit=min(cap * 2, 200))
    rows = dedup_events(rows)[:cap]
    for row in rows:
        sig = compute_staleness(row)
        row["stale_signal"] = sig["status"]
        row["hours_since_check"] = sig.get("hours_since_check")
        row["event_age_days"] = sig.get("event_age_days")
        row["persistence_signal"] = classify_persistence_signal(row)
    return _api._sanitize_floats(rows)


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
    return build_json_export(evs)


@router.patch("/events/{event_id}/review")
def review(event_id: int, req: _api.ReviewRequest):
    if req.rating is None and req.notes is None:
        raise HTTPException(400, "Provide at least one of rating or notes.")
    updated = update_review(event_id, rating=req.rating, notes=req.notes)
    if not updated:
        raise HTTPException(404, f"Event {event_id} not found.")
    return {"ok": True, "event_id": event_id}


@router.delete("/events/{event_id}")
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
    found, skipped = [], []
    for eid in req.event_ids:
        ev = _api.load_event_by_id(eid)
        (found if ev else skipped).append(ev or eid)
    found = [e for e in found if isinstance(e, dict)]
    skipped = [s for s in skipped if isinstance(s, int)]
    # re-derive from the request ids properly
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


@router.get("/events/{event_id}/cascade")
def cascade(event_id: int):
    result = get_event_cascade(event_id)
    if result["root"] is None:
        raise HTTPException(404, f"Event {event_id} not found.")
    return _api._sanitize_floats(result)


@router.get("/events/{event_id}/backtest")
def backtest(event_id: int, force: bool = Query(False)):
    result = _api._backtest_one(event_id, force=force)
    if result.get("error") == "not found":
        raise HTTPException(404, f"Event {event_id} not found.")
    return _api._sanitize_floats(result)


@router.post("/events/{event_id}/refresh-market")
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
            target_for_refresh, force=True,
            followup_check_fn=_api.followup_check, market_check_fn=_api.market_check,
        )
    except Exception:
        _api._log.warning("refresh-market: failed for event %d", event_id, exc_info=True)
        raise HTTPException(502, "Market data provider failed.")
    tickers = _scrub_implausible_ticker_returns(market_block.get("tickers", []))
    tickers = _suppress_duplicate_tickers(tickers)
    return _api._sanitize_floats({
        "event_id": event_id,
        "market": {
            "note": market_block.get("note", ""), "details": {}, "tickers": tickers,
            "last_market_check_at": market_block.get("last_market_check_at"),
            "market_check_staleness": market_block.get("market_check_staleness"),
        },
    })


@router.get("/events/{event_id}/revisit")
def get_revisit_timeline(event_id: int):
    target = _api.load_event_by_id(event_id)
    if not target:
        raise HTTPException(404, f"Event {event_id} not found.")
    return _api._sanitize_floats({"event_id": event_id, "snapshots": load_revisit_snapshots(event_id)})


@router.post("/events/{event_id}/revisit")
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
    return _api._sanitize_floats({"event_id": event_id, "snapshots": load_revisit_snapshots(event_id)})
