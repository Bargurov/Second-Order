"""The event-chain routes (event_chain_view and event_chain_records), added to the app by create_app.

GET /api/theses/copper/event-chains serves the view and writes nothing. Two owner writes, a review and a reading, save
one append-only record each under the records folder and nothing else. No route fetches, calls a model or costs
anything. A refusal is a plain {"detail"} reply; a 409 also carries "latest", the id of the newest record (or null),
so a page can reload without guessing.
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import auth, event_chain_records as records, event_chain_view as chain_view
from .event_chain_evidence import Folders
from .event_chain_schema import ChainRefused
from .event_chain_text import TextRefused

RECORDS_DIR = Path(__file__).resolve().parent.parent / "data" / "event-chains"
EVENT_CHAIN_HEADER = "x-second-order-event-chain"
MAX_BODY = 16_384
SUBJECT = "event-chain request"
BASE = "/api/theses/copper/event-chains"


def _refusal(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


def add_routes(app: FastAPI, folders: Folders, check_local_write, limited_body, clock, accounts_enabled: bool) -> None:
    @app.get(BASE)
    def get_event_chains():
        """Every chain with its evidence states, measured block and owner records. Reads only."""
        try:
            return chain_view.view(folders)
        except ChainRefused as exc:
            return _refusal(exc.status, str(exc))
        except OSError as exc:
            return _refusal(500, f"The local records could not be read ({type(exc).__name__})")

    async def write(request: Request, chain_id: str, save):
        check_local_write(request, EVENT_CHAIN_HEADER, SUBJECT)
        if accounts_enabled and auth.bound_account(request.headers.getlist(auth.ACCOUNT_HEADER)) is None:
            raise auth.ContractError(428, "account_binding_required")
        body = await limited_body(request, MAX_BODY, SUBJECT)
        identity = auth.identity_of(request)
        account = {"user_id": identity.user_id, "username": identity.username}
        try:
            current = chain_view.current(folders, chain_id)
            return JSONResponse({"record": save(folders.records, current, body, account, clock)}, status_code=201)
        except records.RecordRefused as exc:
            if exc.status == 409:
                return JSONResponse({"detail": exc.message, "latest": exc.latest}, status_code=409)
            return _refusal(exc.status, exc.message)
        except (ChainRefused, TextRefused) as exc:
            return _refusal(exc.status, str(exc))
        except OSError as exc:
            return _refusal(500, f"The local records could not be written ({type(exc).__name__})")

    @app.post(BASE + "/{chain_id}/reviews")
    async def post_review(request: Request, chain_id: str):
        """Save the owner's review of the chain's current version, once."""
        return await write(request, chain_id, records.save_review)

    @app.post(BASE + "/{chain_id}/readings")
    async def post_reading(request: Request, chain_id: str):
        """Save the owner's reading of the chain's current version, once."""
        return await write(request, chain_id, records.save_reading)
