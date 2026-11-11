"""The comparison development command (python -m second_order comparisons pin ...), run in the working session only.

The assistant writes a comparison version v<N>.json with "evidence": null; `pin` copies the publications, passages and
acquisition records that version rests on into its evidence (publication_comparison.pin, from the raw research files:
absent retained documents do not matter), checks the result as the app would load it, writes it back (LF, indent=1) and
appends the version to the comparison's index with its SHA-256 and publication date. A version already in the index is
refused, so a published version never changes. The app never runs this; nothing here fetches or calls a model.
"""
import argparse
from datetime import date
from pathlib import Path
import shutil
import tempfile

from . import bis_snapshot, company_research_view, publication_comparison as comparison, thesis_schema
from .event_chain_cli import RECORDS_DIR, _json_bytes, _replace, _strict
from .event_chain_evidence import Folders
from .event_chain_schema import ID, INDEX, ChainRefused


def add_commands(commands: argparse._SubParsersAction) -> None:
    group = commands.add_parser("comparisons", help="Publication comparisons, in the working session: pin a written "
                                                    "version's evidence and publish it in the comparison's index")
    actions = group.add_subparsers(dest="comparisons_action", required=True)
    pin = actions.add_parser("pin", help='Fill v<N>.json\'s "evidence": null from the research files and append it to '
                                         "the index; a version already in the index is refused")
    pin.add_argument("--comparison", required=True, help="The comparison id (its folder under copper/comparisons)")
    pin.add_argument("--version", required=True, type=int, help="The version to pin: the next one after the index")
    pin.add_argument("--published-on", required=True, type=date.fromisoformat, help="Publication date, YYYY-MM-DD")
    pin.add_argument("--theses", type=Path, default=thesis_schema.THESES_DIR)
    pin.add_argument("--research", type=Path, default=company_research_view.RESEARCH_DIR)
    pin.add_argument("--company-sources", type=Path, default=company_research_view.SOURCES_DIR)


def pin_version(comparison_id: str, number: int, published_on: date, theses: Path, research: Path,
                company_sources: Path) -> dict:
    """Pin and publish version ``number`` of ``comparison_id``; returns {"comparison", "version", "sha256"}. Raises
    ChainRefused(422) and writes nothing when the version is not the next one, its file is not an unpinned version of
    this comparison, a record it rests on cannot be pinned, or the pinned version would not load."""
    if not ID.fullmatch(comparison_id):
        raise ChainRefused(422, f"--comparison: {comparison_id!r} is not a lowercase comparison id")
    folder = comparison.comparisons_dir(theses) / comparison_id
    index_path = folder / INDEX
    if index_path.exists():
        index = _strict(index_path, f"{comparison_id}/{INDEX}")
        if not (isinstance(index, dict) and index.get("index_version") == comparison.INDEX_VERSION
                and index.get("id") == comparison_id and isinstance(index.get("versions"), list)):
            raise ChainRefused(422, f"{comparison_id}/{INDEX}: not the index of this comparison")
    else:
        index = {"index_version": comparison.INDEX_VERSION, "id": comparison_id, "versions": []}
    if any(isinstance(entry, dict) and entry.get("version") == number for entry in index["versions"]):
        raise ChainRefused(422, f"{comparison_id}: version {number} is already in the index; a published version never "
                                "changes, so write the next version")
    expected = len(index["versions"]) + 1
    if number != expected:
        raise ChainRefused(422, f"{comparison_id}: the next version is {expected}, not {number}")
    name = f"v{number}.json"
    written = _strict(folder / name, f"{comparison_id}/{name}")
    if not (isinstance(written, dict) and written.get("id") == comparison_id and written.get("version") == number):
        raise ChainRefused(422, f"{comparison_id}/{name}: not version {number} of this comparison")
    if "evidence" not in written or written["evidence"] is not None:
        raise ChainRefused(422, f'{comparison_id}/{name}: expected "evidence": null, to be pinned')
    if not (isinstance(written.get("rows"), list) and all(isinstance(row, dict) and set(comparison.SIDES) <= set(row)
                                                          for row in written["rows"])
            and all(isinstance(written.get(side), dict) and "document" in written[side] for side in comparison.SIDES)):
        raise ChainRefused(422, f"{comparison_id}/{name}: expected rows with an earlier and a later passage, and the "
                                "two publications")

    folders = Folders(theses=Path(theses), thesis_sources=Path(theses), metals=Path(theses),
                      metals_sources=Path(theses), research=Path(research), company_sources=Path(company_sources),
                      records=RECORDS_DIR)  # Only the research and company folders are read.
    pinned = {**written, "evidence": comparison.pin(written, folders)}
    sha256 = bis_snapshot.sha256(bis_snapshot.canonical(pinned))
    entry = {"version": number, "file": name, "sha256": sha256, "published_on": published_on.isoformat()}
    published = {**index, "versions": [*index["versions"], entry]}
    files = {name: _json_bytes(pinned), INDEX: _json_bytes(published)}

    with tempfile.TemporaryDirectory(prefix="second-order-comparison-pin-") as tmp:
        trial = Path(tmp) / comparison_id
        shutil.copytree(folder, trial)
        for file_name, data in files.items():
            (trial / file_name).write_bytes(data)
        try:  # The whole comparison as the app loads it, with the new version, before anything is written.
            comparison.load_comparisons(Path(tmp))
        except ChainRefused as exc:
            raise ChainRefused(422, f"the pinned version would not load: {exc.message}") from None
    _replace(folder / name, files[name])
    _replace(index_path, files[INDEX])
    return {"comparison": comparison_id, "version": number, "sha256": sha256}


def run(args: argparse.Namespace) -> dict:
    return pin_version(args.comparison, args.version, args.published_on, args.theses, args.research,
                       args.company_sources)
