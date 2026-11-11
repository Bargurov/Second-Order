"""SYNTHETIC event-chain content for the event-chain tests: a mechanism list, a chain citing two made-up passages, a
hand-written pinned evidence, and writers for their index and version files. Every name, quote and number here is made
up; nothing stands for a real source. The fakes state the file contract independently of the code under test.

The world (write_world): a complete SYNTHETIC set of folders the evidence reads, the synthetic copper thesis (as
"copper") with its retained sources, the synthetic FCX package, the metals sources, a register and the mechanism list,
and a world chain whose every cited record is in it (world_chain)."""
import copy
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
for _path in (HERE.parent, HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import fcx_fakes  # noqa: E402
import metals_fakes  # noqa: E402
import thesis_fakes  # noqa: E402
from second_order.event_chain_evidence import Folders  # noqa: E402

MECHANISMS = {
    "restart-takes-time": "When a halted mine restarts in stages, the metal it would have supplied reaches users "
                          "later than planned.",
    "thin-stocks": "If stocks held by users are thin, an interruption of supply matters more to them.",
}
EVENT = "copper:producer-sales-2025"
SECOND = "fcx:k25-mud-rush-85pct"


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


def write_mechanisms(metals: Path, entries: dict[str, str] | None = None) -> None:
    """Write ``metals/mechanisms/index.json`` and ``v1.json`` (one published version)."""
    entries = MECHANISMS if entries is None else entries
    version = {"mechanisms_version": "event-mechanisms-0.1", "version": 1,
               "entries": [{"id": key, "text": text} for key, text in entries.items()]}
    folder = Path(metals) / "mechanisms"
    _write(folder / "v1.json", version)
    _write(folder / "index.json", {
        "index_version": "event-mechanisms-index-0.1", "id": "mechanisms",
        "versions": [{"version": 1, "file": "v1.json", "sha256": hashlib.sha256(_canonical(version)).hexdigest(),
                      "published_on": "2026-11-01"}]})


def _acquisition(kind: str, name: str) -> dict:
    found = {"approval_id": f"synthetic-{kind}-01", "attempt": 1, "url": f"https://example.org/{name}",
             "folder": name, "name": f"{name}.html", "sha256": hashlib.sha256(name.encode()).hexdigest(),
             "bytes": 100, "retrieved_at": "2026-01-01T00:00:00Z"}
    if kind == "copper":
        found["origin"] = "get"
    return found


def shape_evidence(metals: Path) -> dict:
    """A shape-valid evidence for ``chain_v1``: hand-written passage copies; only the mechanisms index is read."""
    index = json.loads((Path(metals) / "mechanisms" / "index.json").read_bytes().decode("utf-8"))
    return {
        "event": {"passage": EVENT, "kind": "output", "when": "2025"},
        "passages": [
            {"ref": EVENT, "source": "synthetic-sales", "location": {"page": 1},
             "quote": "Synthetic sales report: producer sales were 12 units in 2025."},
            {"ref": SECOND, "source": "synthetic-k25", "location": {"page": 2, "printed_page": "2", "location": "top"},
             "quote": "Synthetic annual filing: a made-up wet-material release halted one pit."},
        ],
        "documents": [{"ref": "copper:synthetic-sales", "acquisition": _acquisition("copper", "synthetic-sales")},
                      {"ref": "fcx:synthetic-k25", "acquisition": _acquisition("fcx", "synthetic-k25")}],
        "thesis": {"id": "copper", "version": 1, "sha256": hashlib.sha256(b"synthetic thesis").hexdigest()},
        "mechanisms": {"version": 1, "sha256": index["versions"][0]["sha256"]},
    }


def chain_v1(evidence: dict | None) -> dict:
    return copy.deepcopy({
        "chain_version": "event-chain-0.1", "id": "synthetic-chain", "version": 1, "previous_version": None,
        "title": "A halted pit and the supply of one mine",
        "event": EVENT,
        "target": {"kind": "reason", "id": "mine-supply-slow"},
        "steps": [
            {"kind": "stated", "passage": EVENT, "label": "Producers sold 12 units in the year"},
            {"kind": "stated", "passage": SECOND, "label": "One pit was halted by a release"},
            {"kind": "not_stated", "text": "No retained source states when the pit's output returned"},
            {"kind": "mechanism", "id": "restart-takes-time"},
        ],
        "evidence": evidence,
        "change": None,
        "provenance": {"prepared_by": "assistant", "ai_assisted": True, "research_use": "excluded"},
    })


def write_chain(theses: Path, chain_id: str, versions: list[dict], published: list[str]) -> None:
    """Write ``theses/copper/event-chains/<chain_id>/`` index.json and v1.json … vN.json."""
    folder = Path(theses) / "copper" / "event-chains" / chain_id
    entries = []
    for number, (version, day) in enumerate(zip(versions, published, strict=True), start=1):
        _write(folder / f"v{number}.json", version)
        entries.append({"version": number, "file": f"v{number}.json",
                        "sha256": hashlib.sha256(_canonical(version)).hexdigest(), "published_on": day})
    _write(folder / "index.json", {"index_version": "event-chain-index-0.1", "id": chain_id, "versions": entries})


# ---------------------------------------------------------------- the world

THESIS = "copper"
WORLD_CHAIN = "synthetic-world-chain"
THIRD = "fcx:q3-p-gbc-capacity-targets"
WRITTEN_BY = ("Written by the assistant from the figures on this page and retained sources; not reviewed by the "
              "owner.")
REGISTER = {  # The register's events: the world chain's event, an FCX event and an event of another chapter.
    "copper": {"thesis": THESIS, "events": [
        {"passage": EVENT, "kind": "Synthetic sales report", "when": "2025"},
        {"passage": "fcx:k25-mud-rush-event", "kind": "Supply disruption", "when": "September 8, 2025"}]},
    "nickel": {"events": [{"passage": "copper:maker-deliveries-2025", "kind": "Synthetic deliveries", "when": "2025"}]},
}
REPLACED_AT = "2026-11-09T09:00:00+00:00"


def world_thesis(folders: Folders) -> dict:
    """The synthetic thesis version 1 as the "copper" thesis, bound to the world's retained thesis sources."""
    return dict(thesis_fakes.thesis_v1(folders.thesis_sources), id=THESIS)


def world_folders(root: Path) -> Folders:
    """The folders of the world below ``root``, as write_world lays them out (nothing is read or written)."""
    root = Path(root)
    return Folders(theses=root / "theses", thesis_sources=root / "thesis-sources", metals=root / "metals",
                   metals_sources=root / "metals-sources", research=root / "fcx" / "research",
                   company_sources=root / "fcx" / "sources", records=root / "records")


def write_world(root: Path) -> Folders:
    """Write the world below ``root`` (see the module docstring) and return its folders; records stay unwritten."""
    root = Path(root)
    folders = world_folders(root)
    thesis_fakes.write_sources(folders.thesis_sources)
    thesis_fakes.write_theses(folders.theses, [world_thesis(folders)], [thesis_fakes.OPENED_ON], thesis_id=THESIS)
    fcx_fakes.synthetic_package(root / "fcx")
    metals_fakes.write_sources(folders.metals_sources)
    _write(folders.metals / "sources.json", metals_fakes.sources_file(folders.metals_sources))
    _write(folders.metals / "research.json", {"research_version": "metals-research-0.3", "written_by": WRITTEN_BY,
                                              "metals": copy.deepcopy(REGISTER)})
    write_mechanisms(folders.metals)
    return folders


def world_chain(evidence: dict | None) -> dict:
    """A chain version 1 on the world: the register's sales event, two FCX passages (the 10-K and the 10-Q) and a
    mechanism, aimed at the reason mine-supply-slow. Its labels hold no figures and repeat no six words of a quote."""
    return copy.deepcopy({
        "chain_version": "event-chain-0.1", "id": WORLD_CHAIN, "version": 1, "previous_version": None,
        "title": "Synthetic sales, a halted pit and slow mine supply",
        "event": EVENT,
        "target": {"kind": "reason", "id": "mine-supply-slow"},
        "steps": [
            {"kind": "stated", "passage": EVENT, "label": "The producer reports its copper sales for the year"},
            {"kind": "stated", "passage": SECOND, "label": "The company expects most output back in the second half"},
            {"kind": "stated", "passage": THIRD, "label": "The company names when the block cave nears capacity"},
            {"kind": "not_stated", "text": "No retained source states when the pit's output returned"},
            {"kind": "mechanism", "id": "restart-takes-time"},
        ],
        "evidence": evidence,
        "change": None,
        "provenance": {"prepared_by": "assistant", "ai_assisted": True, "research_use": "excluded"},
    })


def _read(path: Path):
    return json.loads(Path(path).read_bytes().decode("utf-8"))


def replace_fcx_acquisition(folders: Folders, source_id: str = "10q-2026q3") -> dict:
    """A later SYNTHETIC acquisition of one FCX document: a new file in a new folder, recorded under the next free
    attempt of the same approval (outcome-<n>.json), with the sources.json entry pointed at it. The old file and its
    record stay. Returns the new entry."""
    listing = _read(folders.research / "sources.json")
    entry = next(item for item in listing["sources"] if item["id"] == source_id)
    approval = folders.research / "acquisition" / entry["approval_id"]
    old = _read(approval / f"outcome-{entry['attempt']}.json")
    attempt = 1 + max(int(path.stem.split("-")[1]) for path in approval.glob("outcome-*.json"))
    raw = (f"SYNTHETIC FCX document {source_id}, a later acquisition: made-up bytes for tests.\n" * 16).encode("ascii")
    folder = f"{entry['folder']}-{attempt}"
    (folders.company_sources / folder).mkdir(parents=True, exist_ok=True)
    (folders.company_sources / folder / entry["name"]).write_bytes(raw)
    entry.update(attempt=attempt, folder=folder, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                 retrieved_at=REPLACED_AT)
    _write(approval / f"outcome-{attempt}.json", {
        **old, "n": attempt, "sha256": entry["sha256"], "bytes": entry["bytes"], "dispatched_at": REPLACED_AT,
        "retained": f"data/company-sources/fcx/{folder}/{entry['name']}"})
    _write(folders.research / "sources.json", listing)
    return dict(entry)


# ---------------------------------------------------------------- a publication comparison on the world

WORLD_COMPARISON = "synthetic-annual-to-quarter"
EARLIER_DOCUMENT, LATER_DOCUMENT = "fcx:10k-2025", "fcx:10q-2026q3"


def world_comparison(evidence: dict | None) -> dict:
    """A comparison version 1 on the world: the synthetic package's annual report against its quarterly report, two
    rows of made-up labels over two passages each. Its labels and notes hold no figure and repeat no six words."""
    return copy.deepcopy({
        "comparison_version": "publication-comparison-0.1", "id": WORLD_COMPARISON, "version": 1,
        "previous_version": None,
        "title": "Synthetic: the annual report against the quarterly report",
        "earlier": {"document": EARLIER_DOCUMENT}, "later": {"document": LATER_DOCUMENT},
        "historical": True,
        "rows": [
            {"id": "return-to-operation", "label": "The return to operation",
             "earlier": SECOND, "later": THIRD, "same_measure": "not_established",
             "note": "The earlier line is about total production at normal rates; the later is about capacity."},
            {"id": "licence", "label": "The mining licence",
             "earlier": "fcx:k25-iupk-application-2026", "later": "fcx:q3-p-iupk-extension",
             "same_measure": "not_applicable", "note": None},
        ],
        "prices": ["k25-copper-realized-price-fy2025", "q3-cu-realized-price-q3-2026"],
        "evidence": evidence,
        "change": None,
        "provenance": {"prepared_by": "assistant", "ai_assisted": True, "research_use": "excluded"},
    })


def write_comparison(theses: Path, comparison_id: str, versions: list[dict], published: list[str]) -> None:
    """Write ``theses/copper/comparisons/<comparison_id>/`` index.json and v1.json … vN.json."""
    folder = Path(theses) / "copper" / "comparisons" / comparison_id
    entries = []
    for number, (version, day) in enumerate(zip(versions, published, strict=True), start=1):
        _write(folder / f"v{number}.json", version)
        entries.append({"version": number, "file": f"v{number}.json",
                        "sha256": hashlib.sha256(_canonical(version)).hexdigest(), "published_on": day})
    _write(folder / "index.json", {"index_version": "publication-comparison-index-0.1", "id": comparison_id,
                                   "versions": entries})
