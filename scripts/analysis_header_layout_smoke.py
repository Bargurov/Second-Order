"""Analysis-header layout smoke — freshness/status legibility contract.

A5A-R3 regression harness for the Analysis "Tape alignment" header: at
mobile width the freshness/status area must receive USABLE width (the
right-side control group must never squeeze it to zero), the disclosure
must wrap by words, and desktop must keep the side-by-side composition.

The repo ships no browser-automation dependency, so this smoke follows
the project's in-app-browser convention: this script owns the SEEDED
BACKEND, the MEASUREMENT SNIPPET, and the VALIDATION of measurements; any
real browser (the in-app preview harness, or a maintainer's browser)
drives the page and posts what it measured.

Usage (maintainer / in-app browser):

  1. ``python scripts/analysis_header_layout_smoke.py``  — serves the real
     app on 127.0.0.1:8000 against a TEMP seeded database (never the live
     ``events.db``): five saved events covering the badge states
     stale / unchecked / partial-coverage, plus scripted refresh modes
     (``GET /____refresh_mode/{fail|partial|full}``) so the immediate
     refresh-failed / partially-refreshed / refreshed states are
     reachable through the real refresh route.
  2. Point the frontend dev server at it, open each seeded event at
     375px and 1280px, evaluate ``MEASURE_JS`` on the page, and POST the
     returned JSON to ``/____layout_report``.
  3. The endpoint validates the measurements against
     ``validate_layout_measurements`` and answers PASS/FAIL with every
     violated rule named.  ``GET /____layout_verdict`` summarises all
     reports received in the session.

The validation rules are unit-tested in the default suite
(tests/test_analysis_header_layout_smoke.py); the browser drive itself is
maintainer-run, like every other ``scripts/*_smoke.py``.

NOTE: no ``from __future__ import annotations`` here — the FastAPI routes
are defined inside ``_serve()`` with function-local imports, and postponed
annotations would make ``request: Request`` unresolvable at
route-registration time (FastAPI then mis-reads it as a required query
field and every forwarded request 422s).
"""
import json
import os
import sys
import tempfile
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Evaluated by the driving browser on the OPEN Analysis page.  Returns the
# geometry the validator consumes.  The status root is located by its
# stable content (the badge chip row rendered by MarketValidationStatus).
MEASURE_JS = r"""
(() => {
  const doc = document.documentElement;
  const leaf = [...document.querySelectorAll('body *')].find(
    el => el.children.length === 0 &&
      /(stale|unchecked|refresh failed|partially refreshed|refreshed)/i
        .test(el.textContent || '') &&
      el.closest('div.flex.flex-wrap'));
  const root = leaf ? leaf.closest('div.flex.flex-wrap') : null;
  const detail = root ? [...root.children].find(
    el => /break-words/.test(el.className || '')) : null;
  const container = root ? root.parentElement : null;
  const r = root ? root.getBoundingClientRect() : null;
  const c = container ? container.getBoundingClientRect() : null;
  return JSON.stringify({
    viewport_w: window.innerWidth,
    page_overflow_x: doc.scrollWidth - doc.clientWidth,
    status_root_w: root ? root.clientWidth : 0,
    detail_w: detail ? detail.clientWidth : 0,
    status_right: r ? Math.round(r.right) : null,
    container_right: c ? Math.round(c.right) : null,
    detail_text: detail ? (detail.textContent || '').slice(0, 120) : '',
    label_text: leaf ? (leaf.textContent || '').trim().slice(0, 40) : '',
  });
})()
"""

# Word-wrap floor: a detail column narrower than this wraps roughly one
# word per line at the badge's 9px type and reads as broken.
_MIN_DETAIL_W = 80
_MIN_STATUS_W = 120


def validate_layout_measurements(m: dict) -> list[str]:
    """Return every violated layout rule (empty list == PASS).

    Rules (the committed A5A-R3 contract):
      * the status root and the detail must have usable width;
      * the status root must stay inside its container;
      * the row must not add page-level horizontal overflow beyond the
        known pre-existing chrome residual (<= 4px, per A5A-V3);
      * a state label must actually be rendered.
    """
    errors: list[str] = []
    viewport = m.get("viewport_w") or 0
    if not m.get("label_text"):
        errors.append("no freshness state label rendered")
    if (m.get("status_root_w") or 0) < _MIN_STATUS_W:
        errors.append(
            f"status root width {m.get('status_root_w')}px < "
            f"{_MIN_STATUS_W}px — the header squeezed the status area")
    if m.get("detail_text") and (m.get("detail_w") or 0) < _MIN_DETAIL_W:
        errors.append(
            f"detail width {m.get('detail_w')}px < {_MIN_DETAIL_W}px — "
            "disclosure wraps unreadably")
    sr, cr = m.get("status_right"), m.get("container_right")
    if sr is not None and cr is not None and sr > cr + 1:
        errors.append(f"status root ({sr}px) escapes its container ({cr}px)")
    if viewport and viewport <= 420 and (m.get("page_overflow_x") or 0) > 4:
        errors.append(
            f"page overflow {m.get('page_overflow_x')}px > 4px at mobile "
            "width — exceeds the known pre-existing chrome residual")
    return errors


def _serve() -> None:  # pragma: no cover — maintainer-run server body
    from datetime import datetime, timedelta
    from unittest.mock import patch

    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
              "GEMINI_API_KEY", "GOOGLE_API_KEY", "FRED_API_KEY",
              "POLYGON_API_KEY", "SECOND_ORDER_ADMIN_TOKEN"):
        os.environ[k] = ""
    os.environ["ENABLE_PAID_ANALYSIS"] = "0"
    tmp = os.path.join(tempfile.gettempdir(),
                       f"layout_smoke_{uuid.uuid4().hex}.db")
    os.environ["EVENTS_DB_FILE"] = tmp

    import db as _db

    assert os.path.abspath(_db.get_db_path()) == tmp, _db.get_db_path()
    _db.init_db()

    now = datetime.now()
    stale_stamp = (now - timedelta(hours=90)).isoformat(timespec="seconds")
    week_ago = (now - timedelta(days=6)).strftime("%Y-%m-%d")

    def rows(vals, marker=False):
        out = []
        for i, sym in enumerate(("AAA", "BBB")):
            row = {"symbol": sym, "role": "beneficiary" if i == 0 else
                   "loser", "return_1d": vals, "return_5d": vals,
                   "return_20d": vals, "direction_tag": "supports ↑"}
            if marker and i == 1:
                row["retained_prior"] = True
            out.append(row)
        return out

    seeds = {
        "stale": {"headline": "Layout state: stale saved analysis",
                  "market_tickers": rows(1.0), "check": stale_stamp},
        "unchecked": {"headline": "Layout state: unchecked saved analysis",
                      "market_tickers": rows(1.0), "check": None},
        "partial": {"headline": "Layout state: partial coverage analysis",
                    "market_tickers": rows(1.0, marker=True),
                    "check": stale_stamp},
    }
    ids = {}
    for key, spec in seeds.items():
        eid = _db.save_event({
            "headline": spec["headline"], "stage": "developing",
            "persistence": "medium", "event_date": week_ago,
            "mechanism_summary": (
                "Layout fixture: a stored mechanism summary long enough "
                "to render the saved readout like a real analysis row."),
            "what_changed": (
                "Layout fixture: the stored what-changed text for the "
                "header-layout smoke."),
            "confidence": "medium", "model": "claude-sonnet-4-6",
            "market_tickers": spec["market_tickers"],
        })
        # save_event stamps last_market_check_at at insert, so the
        # "unchecked" state must NULL it explicitly — a None spec means
        # "this row was never market-checked", not "leave the stamp".
        import sqlite3
        conn = sqlite3.connect(tmp)
        conn.execute("UPDATE events SET last_market_check_at=?"
                     " WHERE id=?", (spec["check"], eid))
        conn.commit()
        conn.close()
        ids[key] = eid

    from fastapi import FastAPI, Request, Response
    from fastapi.testclient import TestClient

    import api as _api

    real = TestClient(_api.app)
    real.__enter__()

    MODE = {"v": "fail"}
    REPORTS: list[dict] = []

    def synthetic_rows(mode):
        def fn(tickers, event_date):
            out = []
            for i, t in enumerate(tickers):
                usable = mode == "full" or (mode == "partial" and i == 0)
                out.append({
                    "symbol": t.get("symbol"), "role": t.get("role"),
                    "return_1d": 9.0 if usable else None,
                    "return_5d": 9.5 if usable else None,
                    "return_20d": 10.0 if usable else None,
                    "return_60d": None,
                    "direction": "supports" if usable else None,
                    "anchor_date": event_date if usable else None})
            return out
        return fn

    harness = FastAPI()

    @harness.get("/____layout_ids")
    def layout_ids():
        return ids

    @harness.get("/____refresh_mode/{mode}")
    def set_mode(mode: str):
        MODE["v"] = mode
        return {"mode": mode}

    @harness.post("/events/{event_id}/refresh-market")
    def scripted_refresh(event_id: int):
        with patch.object(_api, "followup_check",
                          synthetic_rows(MODE["v"])):
            r = real.post(f"/events/{event_id}/refresh-market")
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type"))

    @harness.post("/____layout_report")
    async def layout_report(request: Request):
        m = await request.json()
        errors = validate_layout_measurements(m)
        REPORTS.append({"measurement": m, "errors": errors})
        return {"ok": not errors, "errors": errors}

    @harness.get("/____layout_verdict")
    def layout_verdict():
        failed = [r for r in REPORTS if r["errors"]]
        return {"reports": len(REPORTS), "failed": len(failed),
                "ok": bool(REPORTS) and not failed,
                "failures": failed}

    @harness.api_route("/{path:path}",
                       methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def forward(path: str, request: Request):
        body = await request.body()
        resp = real.request(
            request.method, "/" + path,
            params=dict(request.query_params),
            content=body or None,
            headers={k: v for k, v in request.headers.items()
                     if k.lower() in ("content-type",
                                      "x-second-order-admin-token")})
        return Response(content=resp.content, status_code=resp.status_code,
                        media_type=resp.headers.get("content-type"))

    import uvicorn
    print("analysis-header layout smoke on 127.0.0.1:8000; seeded ids:",
          json.dumps(ids), flush=True)
    uvicorn.run(harness, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":  # pragma: no cover
    _serve()
