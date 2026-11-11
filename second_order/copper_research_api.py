"""The copper research routes (copper_research_view and research_notes), added to the app by create_app.

GET /api/theses/copper/research serves the desk, the comparisons and the owner's notes, and writes nothing. One owner
write, POST /api/theses/copper/research/notes, saves one append-only note under the notes folder and nothing else. No
route fetches, calls a model or costs anything. A refusal is a plain {"detail"} reply; a 409 also carries "latest", the
id of the newest note (or null), so a page can reload without guessing.
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import auth, copper_research_view as research_view, research_notes
from .event_chain_evidence import Folders
from .event_chain_records import RecordRefused
from .event_chain_schema import ChainRefused

NOTES_DIR = Path(__file__).resolve().parent.parent / "data" / "research-notes" / "copper"
NOTE_HEADER = "x-second-order-research-note"
MAX_BODY = 16_384
SUBJECT = "research note request"
BASE = "/api/theses/copper/research"


def _refusal(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


def add_routes(app: FastAPI, folders: Folders, notes: Path, check_local_write, limited_body, clock,
               accounts_enabled: bool) -> None:
    @app.get(BASE)
    def get_copper_research():
        """The desk's page lines, the comparisons with their evidence states and the owner's notes. Reads only."""
        try:
            return research_view.view(folders, notes, clock)
        except ChainRefused as exc:
            return _refusal(exc.status, str(exc))
        except OSError as exc:
            return _refusal(500, f"The local records could not be read ({type(exc).__name__})")

    @app.post(BASE + "/notes")
    async def post_note(request: Request):
        """Save one note of the owner's about a comparison, a chain or the thesis, once."""
        check_local_write(request, NOTE_HEADER, SUBJECT)
        if accounts_enabled and auth.bound_account(request.headers.getlist(auth.ACCOUNT_HEADER)) is None:
            raise auth.ContractError(428, "account_binding_required")
        body = await limited_body(request, MAX_BODY, SUBJECT)
        identity = auth.identity_of(request)
        account = {"user_id": identity.user_id, "username": identity.username}
        try:
            payload = research_notes.parse(body)
            about = payload["about"]
            subject = research_view.subject(folders, about["kind"], about["id"])
            return JSONResponse({"record": research_notes.save(notes, subject, payload, account, clock)},
                                status_code=201)
        except RecordRefused as exc:
            if exc.status == 409:
                return JSONResponse({"detail": exc.message, "latest": exc.latest}, status_code=409)
            return _refusal(exc.status, exc.message)
        except ChainRefused as exc:
            return _refusal(exc.status, str(exc))
        except OSError as exc:
            return _refusal(500, f"The local records could not be written ({type(exc).__name__})")
