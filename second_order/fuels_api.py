"""The fuels page's read route, added to the app by create_app: GET /api/fuels returns the whole view
(fuels_view). It reads the committed source record, the verified snapshots and the committed notes, and never fetches,
calls a model or writes. Admin only (the app's access check). A refusal keeps its status; a local read error is a 500
naming the exception type only, and so is a malformed record that fails while the view is built (ValueError,
KeyError or TypeError): the message never carries the exception's text."""
from pathlib import Path

from fastapi import FastAPI, HTTPException

from . import fuels_sources, fuels_view


def add_routes(app: FastAPI, content: Path, snapshots: Path | None, synthetic: bool = False) -> None:
    @app.get("/api/fuels")
    def fuels() -> dict:
        try:
            return fuels_view.view(content, snapshots, synthetic)
        except fuels_sources.FuelsRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local fuels records could not be read ({type(exc).__name__})") from None
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(500, f"The local fuels records are malformed ({type(exc).__name__})") from None
