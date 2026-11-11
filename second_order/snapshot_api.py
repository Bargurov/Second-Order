"""Routes of the retained BIS snapshot (see bis_snapshot) and of its explicit import into the Event Inbox (see
inbox_imports), added to the app by create_app.

The GET routes read the retained page (verified against its acquisition record on every read), its local index once it
has been opened, and the Inbox's imported entries; they never write or fetch. The POSTs come only from this server's
own page, with the inbox header: open (build the index once, or reuse it), preview (sort a selection; writes nothing)
and import (adds the chosen records to the Inbox). None contacts a provider, a model or the network; all are local and
free, and nothing is classified, summarized or analyzed.
"""
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import bis_snapshot, inbox_imports

VIEW_VERSION = "bis-snapshot-view-0.1"
INBOX_HEADER = "x-second-order-inbox"
MAX_BODY = 8192
OPENING = 280
STATEMENT = ("A copy of BIS's News & Updates page, retained once on approval: a snapshot of what the page listed then, "
             "not a live feed. Nothing here requests anything. Importing a record adds it to the Event Inbox locally "
             "and costs nothing; it does not verify the record's claims, and nothing is classified, summarized or "
             "analyzed.")
FILTERS_NOTE = ("Keyword filters are fixed word lists this application applies (the same lists as Related Cases); "
                "topics and country tags are BIS's own. Neither is a model classification.")


def _import_state(record: dict, states: dict) -> dict:
    held = states.get(record["key"])
    if held is None:
        return {"state": "new", "versions": 0}
    if held["state"] == "unreadable":
        return {"state": "unreadable", "versions": None}
    return {"state": "imported" if held["record_sha256"] == record["record_sha256"] else "changed",
            "versions": held["versions"]}


def _row(record: dict, states: dict) -> dict:
    text = " ".join(record["text"]["paragraphs"])
    external = record["publisher"]["external_link"]
    published = record["listing"]["published"]
    return {"key": record["key"], "id": record["id"], "title": record["publisher"]["title"], "link": record["identity"],
            "position": record["position"], "date": published["date"], "date_state": published["state"],
            "published": published["time"], "topics": record["publisher"]["topics"],
            "external_host": external["host"] if external else None, "completeness": record["completeness"],
            "text_chars": record["text"]["chars"],
            "opening": (text[:OPENING - 1].rstrip() + "…") if len(text) > OPENING else text,
            "filters": {name: found["matched"] for name, found in record["filters"].items()},
            "same_title": len(record["same_title"]), "import": _import_state(record, states)}


def _index_summary(index: dict) -> dict:
    return {"name": bis_snapshot.index_name(index["package"]), "version": index["index_version"],
            "extractor_version": index["extractor_version"], "built_at": index["built_at"],
            "content_sha256": index["content_sha256"], "release_pages": index["release_pages"]}


def view(inbox: Path, sources: Path, index_dir: Path) -> dict:
    """The snapshot page: unavailable, refused, not opened, or open with every record's row. Reads only."""
    base = {"view_version": VIEW_VERSION, "label": inbox_imports.SOURCES[inbox_imports.SOURCE_KEY].label,
            "page_url": bis_snapshot.PAGE_URL, "statement": STATEMENT, "filters_note": FILTERS_NOTE,
            "filters": {name: spec["label"] for name, spec in bis_snapshot.FILTERS.items()},
            "completeness_labels": bis_snapshot.COMPLETENESS, "selection_limit": inbox_imports.MAX_SELECTION,
            "provider_called": False, "package": None, "index": None, "counts": None, "rows": [], "unusable": [],
            "problem": None}
    try:
        package, index = bis_snapshot.read_index(sources, index_dir)
    except bis_snapshot.SnapshotRefused as exc:
        return {**base, "state": "unavailable" if exc.status == 503 else "refused", "problem": str(exc)}
    if index is None:
        return {**base, "state": "not_opened", "package": package}
    states = inbox_imports.states(inbox)
    return {**base, "state": "open", "package": package, "index": _index_summary(index),
            "counts": bis_snapshot.counts(index), "rows": [_row(record, states) for record in index["records"]],
            "unusable": index["unusable"]}


def _opened(sources: Path, index_dir: Path) -> dict:
    _, index = bis_snapshot.read_index(sources, index_dir)
    if index is None:
        raise bis_snapshot.SnapshotRefused(409, "Open the retained snapshot first; nothing was previewed or imported")
    return index


def record_view(key: str, inbox: Path, sources: Path, index_dir: Path) -> dict:
    """One record with every extracted field, its provenance and its import state. Reads only."""
    if not inbox_imports.KEY.fullmatch(key or ""):
        raise bis_snapshot.SnapshotRefused(404, "No record of the snapshot has this key")
    index = _opened(sources, index_dir)
    record = next((record for record in index["records"] if record["key"] == key), None)
    if record is None:
        raise bis_snapshot.SnapshotRefused(404, "No usable record of the snapshot has this key")
    return {"view_version": VIEW_VERSION, "record": record, "package": index["package"],
            "index": _index_summary(index), "import": _import_state(record, inbox_imports.states(inbox)),
            "completeness": bis_snapshot.COMPLETENESS[record["completeness"]], "provider_called": False}


def add_routes(app: FastAPI, inbox: Path, sources: Path, index_dir: Path, check_write: Callable, read_body: Callable,
               clock: Callable) -> None:
    def call(action):
        try:
            return action()
        except (bis_snapshot.SnapshotRefused, inbox_imports.ImportRefused) as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local records could not be read or written ({type(exc).__name__})") \
                from None

    async def body_of(request: Request, subject: str):
        check_write(request, INBOX_HEADER, "Snapshot actions")
        raw = await read_body(request, MAX_BODY, subject)
        try:
            return bis_snapshot._strict_json(raw.decode("utf-8"), f"The {subject}")
        except (UnicodeDecodeError, bis_snapshot.SnapshotRefused):
            raise HTTPException(422, f"The {subject} must be strict JSON") from None

    @app.get("/api/inbox/snapshots/bis")
    def get_snapshot() -> dict:
        """The retained snapshot, verified, and its records once opened. Reads only."""
        return call(lambda: view(inbox, sources, index_dir))

    @app.get("/api/inbox/snapshots/bis/records/{key}")
    def get_snapshot_record(key: str) -> dict:
        """One record in full. Reads only."""
        return call(lambda: record_view(key, inbox, sources, index_dir))

    @app.post("/api/inbox/snapshots/bis/open")
    async def post_open(request: Request) -> dict:
        """The explicit open: verify the retained page and build its local index once, or reuse it."""
        if await body_of(request, "open request") != {}:
            raise HTTPException(422, "Opening the snapshot takes no options; send an empty JSON object")

        def action():
            _, state = bis_snapshot.open_index(sources, index_dir, clock)
            return {**view(inbox, sources, index_dir), "opened": state}
        return await run_in_threadpool(call, action)

    @app.post("/api/inbox/snapshots/bis/preview")
    async def post_preview(request: Request) -> dict:
        """What importing the selection would do. Writes nothing."""
        body = await body_of(request, "preview request")
        return await run_in_threadpool(call, lambda: inbox_imports.preview(_opened(sources, index_dir), body, inbox))

    @app.post("/api/inbox/snapshots/bis/import")
    async def post_import(request: Request) -> Response:
        """The explicit import of the selection into the Event Inbox: local and free."""
        body = await body_of(request, "import request")
        result = await run_in_threadpool(call, lambda: inbox_imports.run_import(
            _opened(sources, index_dir), body, inbox, clock))
        return JSONResponse(result, status_code=201 if result["written"] else 200)
