"""The event-chain development command (python -m second_order event-chains pin ...), run in the working session only.

The assistant writes a chain version v<N>.json with "evidence": null; `pin` copies the live records that version rests
on into its evidence (event_chain_evidence.pin, from raw files: absent retained sources do not matter), checks the
result as the app would load it, writes it back (LF, indent=1) and appends the version to the chain's index with its
SHA-256 and publication date. A version already in the index is refused, so a published version never changes. The app
never runs this; nothing here fetches or calls a model.
"""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import shutil
import tempfile

from . import bis_snapshot, company_research_view, thesis_schema, thesis_sources
from .model_draft import DraftRefused, strict_json
from .event_chain_schema import (CHAIN_INDEX_VERSION, ID, INDEX, ChainRefused, chains_dir, load_chains,
                                 load_mechanisms, mechanisms_dir)

METALS_DIR = thesis_sources.ROOT / "content" / "metals"
RECORDS_DIR = thesis_sources.ROOT / "data" / "event-chains"


def add_commands(commands: argparse._SubParsersAction) -> None:
    chains = commands.add_parser("event-chains", help="Copper event chains, in the working session: pin a written "
                                                      "chain version's evidence and publish it in the chain's index")
    actions = chains.add_subparsers(dest="event_chains_action", required=True)
    pin = actions.add_parser("pin", help='Fill v<N>.json\'s "evidence": null from the live records and append it to '
                                         "the index; a version already in the index is refused")
    pin.add_argument("--chain", required=True, help="The chain id (its folder under copper/event-chains)")
    pin.add_argument("--version", required=True, type=int, help="The version to pin: the next one after the index")
    pin.add_argument("--published-on", required=True, type=date.fromisoformat, help="Publication date, YYYY-MM-DD")
    pin.add_argument("--theses", type=Path, default=thesis_schema.THESES_DIR)
    pin.add_argument("--thesis-sources", type=Path, default=thesis_sources.SOURCES_DIR)
    pin.add_argument("--metals", type=Path, default=METALS_DIR, help="The register and the mechanism list")
    pin.add_argument("--research", type=Path, default=company_research_view.RESEARCH_DIR)
    pin.add_argument("--company-sources", type=Path, default=company_research_view.SOURCES_DIR)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def _strict(path: Path, what: str) -> object:
    try:
        return strict_json(path.read_bytes())
    except (OSError, DraftRefused):
        raise ChainRefused(422, f"{what}: not a readable strict UTF-8 JSON file") from None


def _replace(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".tmp-{path.name}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def pin_version(chain_id: str, number: int, published_on: date, theses: Path, thesis_sources_dir: Path, metals: Path,
                research: Path, company_sources: Path) -> dict:
    """Pin and publish version ``number`` of ``chain_id``; returns {"chain", "version", "sha256"}. Raises ChainRefused
    (422) and writes nothing when the version is not the next one, its file is not an unpinned version of this chain,
    a record it rests on cannot be pinned, or the pinned version would not load."""
    from .event_chain_evidence import Folders, pin  # The live records are read only when a pin is asked for.

    if not ID.fullmatch(chain_id):
        raise ChainRefused(422, f"--chain: {chain_id!r} is not a lowercase chain id")
    folder = chains_dir(theses) / chain_id
    index_path = folder / INDEX
    if index_path.exists():
        index = _strict(index_path, f"{chain_id}/{INDEX}")
        if not (isinstance(index, dict) and index.get("index_version") == CHAIN_INDEX_VERSION
                and index.get("id") == chain_id and isinstance(index.get("versions"), list)):
            raise ChainRefused(422, f"{chain_id}/{INDEX}: not the index of this chain")
    else:
        index = {"index_version": CHAIN_INDEX_VERSION, "id": chain_id, "versions": []}
    if any(isinstance(entry, dict) and entry.get("version") == number for entry in index["versions"]):
        raise ChainRefused(422, f"{chain_id}: version {number} is already in the index; a published version never "
                                "changes, so write the next version")
    expected = len(index["versions"]) + 1
    if number != expected:
        raise ChainRefused(422, f"{chain_id}: the next version is {expected}, not {number}")
    name = f"v{number}.json"
    written = _strict(folder / name, f"{chain_id}/{name}")
    if not (isinstance(written, dict) and written.get("id") == chain_id and written.get("version") == number):
        raise ChainRefused(422, f"{chain_id}/{name}: not version {number} of this chain")
    if "evidence" not in written or written["evidence"] is not None:
        raise ChainRefused(422, f'{chain_id}/{name}: expected "evidence": null, to be pinned')

    folders = Folders(theses=Path(theses), thesis_sources=Path(thesis_sources_dir), metals=Path(metals),
                      metals_sources=Path(thesis_sources_dir), research=Path(research),
                      company_sources=Path(company_sources), records=RECORDS_DIR)
    pinned = {**written, "evidence": pin(written, folders)}
    sha256 = bis_snapshot.sha256(bis_snapshot.canonical(pinned))
    entry = {"version": number, "file": name, "sha256": sha256, "published_on": published_on.isoformat()}
    published = {**index, "versions": [*index["versions"], entry]}
    files = {name: _json_bytes(pinned), INDEX: _json_bytes(published)}

    with tempfile.TemporaryDirectory(prefix="second-order-event-chain-pin-") as tmp:
        trial = Path(tmp) / chain_id
        shutil.copytree(folder, trial)
        for file_name, data in files.items():
            (trial / file_name).write_bytes(data)
        try:  # The whole chain as the app loads it, with the new version, before anything is written.
            load_chains(Path(tmp), load_mechanisms(mechanisms_dir(folders.metals)))
        except ChainRefused as exc:
            raise ChainRefused(422, f"the pinned version would not load: {exc.message}") from None
    _replace(folder / name, files[name])
    _replace(index_path, files[INDEX])
    return {"chain": chain_id, "version": number, "sha256": sha256}


def run(args: argparse.Namespace) -> dict:
    return pin_version(args.chain, args.version, args.published_on, args.theses, args.thesis_sources, args.metals,
                       args.research, args.company_sources)
