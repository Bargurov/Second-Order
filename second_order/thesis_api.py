"""The routes of the versioned theses (see thesis_schema and thesis_view), added to the app by create_app.

Three GET routes and no POST: the list of committed theses (content only), a thesis at its latest version, and a thesis
at one named version. A reply is built in memory from the committed version file and the retained sources on this
machine. None of the routes writes, fetches or calls a model, and all cost nothing.
"""
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException

from . import thesis_rules, thesis_schema, thesis_view

VERSION = re.compile(r"[1-9][0-9]{0,3}")
NO_VERSION = "This thesis has no such version"


def add_routes(app: FastAPI, root: Path, sources_root: Path) -> None:
    def served(call, *args):
        try:
            return call(*args)
        except thesis_rules.ThesisRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local records could not be read ({type(exc).__name__})") from None

    @app.get("/api/theses")
    def get_theses() -> dict:
        """The committed theses, read as content only. Reads only."""
        return served(thesis_schema.catalog, root)

    @app.get("/api/theses/{thesis_id}")
    def get_thesis(thesis_id: str) -> dict:
        """One thesis at its latest version, every figure and passage checked against its retained source. Reads
        only."""
        return served(thesis_view.view, thesis_id, None, root, sources_root)

    @app.get("/api/theses/{thesis_id}/versions/{version}")
    def get_thesis_version(thesis_id: str, version: str) -> dict:
        """One thesis at one named version. Reads only."""
        if not VERSION.fullmatch(version):
            raise HTTPException(404, NO_VERSION)
        return served(thesis_view.view, thesis_id, int(version), root, sources_root)
