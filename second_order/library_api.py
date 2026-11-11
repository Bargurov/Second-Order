"""The case library's read-only routes (see case_library, market_context and case_enrichments), added to the app by
create_app: committed editorial content, its verified market context and its enrichments. Reads only."""
from pathlib import Path

from fastapi import FastAPI, HTTPException

from . import case_enrichments, case_library, market_context


def add_routes(app: FastAPI, library: Path, context: Path, enrichment_sources: Path, related: Path) -> None:
    @app.get("/api/case-library")
    def get_case_library() -> dict:
        try:
            return case_library.library_view(library)
        except case_library.LibraryRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @app.get("/api/case-library/{case_id}/market-context")
    def get_market_context(case_id: str) -> dict:
        try:
            return market_context.load_context(case_id, context, library)
        except market_context.ContextRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @app.get("/api/case-library/{case_id}/enrichment")
    def get_case_enrichment(case_id: str) -> dict:
        try:
            return case_enrichments.enrichment_view(case_id, library, enrichment_sources, related)
        except case_library.LibraryRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @app.get("/api/case-library/{case_id}")
    def get_library_case(case_id: str) -> dict:
        try:
            return case_library.case_view(case_id, library)
        except case_library.LibraryRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
