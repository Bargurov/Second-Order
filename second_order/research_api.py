"""The route of the source-grounded research views (see policy_research), added to the app by create_app.

It has two GET routes and no POST: one lists the committed research views (content only), the other reads one research
file and checks it against the retained sources on this machine, in memory. Neither writes, fetches or calls a model,
and both cost nothing.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException

from . import policy_research


def add_routes(app: FastAPI, research: Path, sources: dict[str, Path], library: Path, related: Path) -> None:
    @app.get("/api/research")
    def get_research_catalog() -> dict:
        """The committed research views, read as content only. Reads only."""
        try:
            return policy_research.catalog(research)
        except policy_research.PolicyRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @app.get("/api/research/{research_id}")
    def get_research(research_id: str) -> dict:
        """One research view, every quoted passage checked against its retained source. Reads only."""
        try:
            return policy_research.view(research_id, research, sources, library, related)
        except policy_research.PolicyRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local records could not be read ({type(exc).__name__})") from None
