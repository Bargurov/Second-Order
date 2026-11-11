"""The metals route (metals_view), added to the app by create_app.

GET /api/metals reads the whole view: both retained source files verified on each read, then read. There is no write
route. No route fetches, calls a model or costs anything.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException

from . import company_research_view, metals_view, thesis_schema
from .thesis_rules import ThesisRefused


def add_routes(app: FastAPI, folder: Path, sources_root: Path, theses: Path | None = None,
               research: Path = company_research_view.RESEARCH_DIR,
               company_sources: Path = company_research_view.SOURCES_DIR) -> None:
    @app.get("/api/metals")
    def get_metals() -> dict:
        """The metals comparison: USGS and IEA parts, each available or withheld with its problem. Reads only."""
        try:
            return metals_view.view(folder, sources_root, theses or thesis_schema.THESES_DIR, research,
                                     company_sources)
        except ThesisRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local records could not be read ({type(exc).__name__})") from None
