"""The FCX documents the review server serves (--company-fcx), kept out of review_browser_server.py.

serve_fcx(root, mode) returns the (research folder, documents folder) the app reads:
- no mode: the committed research and an empty documents folder below the root, so every FCX figure is withheld (and
  the copper tools' later Bagdad row with it);
- ``retained``: the committed research and data/company-sources/fcx, read-only;
- ``changed``, ``release-changed``, ``missing``: a copy of the retained documents below the root with one byte of the
  Bagdad release or of the results release changed, or the results release removed (company check);
- ``synthetic``: the SYNTHETIC FCX package (fcx_fakes), so the copper check reads the later Bagdad statement as
  verified without the private documents.
The retained folder itself is only read.
"""
from pathlib import Path
import shutil

import fcx_fakes
from second_order import company_research_view

MODES = ("retained", "changed", "release-changed", "missing", "synthetic")


def company_copy(target: Path, how: str) -> None:
    """A copy of the retained FCX documents: one byte of the Bagdad release changed ("changed") or of the results
    release ("release-changed"), or the results release removed ("missing")."""
    shutil.copytree(company_research_view.SOURCES_DIR, target)
    sources = {s["id"]: s for s in company_research_view.load_sources(company_research_view.RESEARCH_DIR)}
    if how in ("changed", "release-changed"):
        sid = "news-2026-11-04" if how == "changed" else "release-2026q3"
        path = target / sources[sid]["folder"] / sources[sid]["name"]
        raw = bytearray(path.read_bytes())
        raw[len(raw) // 2] ^= 1
        path.write_bytes(bytes(raw))
    else:
        (target / sources["release-2026q3"]["folder"] / sources["release-2026q3"]["name"]).unlink()


def serve_fcx(root: Path, mode: str | None) -> tuple[Path, Path]:
    """(research folder, documents folder) for ``mode`` (see the module docstring)."""
    root = Path(root)
    if mode == "synthetic":
        target = root / "fcx-synthetic"
        if (target / "research").is_dir():  # A kept root (--keep-records) already holds it.
            return target / "research", target / "sources"
        return fcx_fakes.synthetic_package(target)
    if mode == "retained":
        return company_research_view.RESEARCH_DIR, company_research_view.SOURCES_DIR
    if mode in ("changed", "release-changed", "missing"):
        if not (root / "company-sources").exists():
            company_copy(root / "company-sources", mode)
    elif mode is not None:
        raise ValueError(f"unknown FCX mode {mode!r}")
    return company_research_view.RESEARCH_DIR, root / "company-sources"
