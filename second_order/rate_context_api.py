"""The market-implied rate path route (see rate_context), added to the app by create_app.

GET only: it reads and verifies one saved event's rate-path context and never fetches, prepares or writes anything.
Records are made only by the explicit local commands `python -m second_order rate-context retain` and `prepare`.
"""
from fastapi import FastAPI, HTTPException

from . import rate_context


def add_routes(app: FastAPI, folders: rate_context.Folders) -> None:
    @app.get("/api/rate-context/capture/{capture_id}")
    def get_rate_context(capture_id: str) -> dict:
        """One saved event's verified rate path, or its explicit state. Reads only."""
        try:
            return rate_context.view(capture_id, folders)
        except rate_context.RateRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
