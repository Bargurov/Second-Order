"""Changes the copper-events browser check makes below its own served folder, between page loads.

Not a test module: frontend/tests/browser/copper-events-check.mjs runs it against the folder it gave
tests/review_browser_server.py --copper-events synthetic. Each subcommand writes only below --root, in the SYNTHETIC
world that option wrote there (tests/event_chain_fakes.py):
- publish-next: the assistant's next version of a chain, copied from its latest one, answering the review --answers (any
  review id, also one that is not on this machine) with the change note --note, and with --label as its second step's
  label when given. Its evidence is pinned against the served folders (event_chain_evidence.pin). The earlier versions
  are written back byte for byte.
- edit-record: one existing field of one passage in the served facts.json copy, with the file's original bytes kept in
  event-chain-helper/ below the root (one edit at a time).
- undo-record: those original bytes back, and the kept copy removed.
Nothing is fetched and no model is called.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
for _path in (HERE.parent, HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import event_chain_fakes as fakes  # noqa: E402
from second_order import event_chain_evidence as evidence  # noqa: E402

DAY = "2026-11-09"
KEPT = "event-chain-helper"


def _read(path: Path):
    return json.loads(path.read_bytes().decode("utf-8"))


def _world(root: Path):
    folders = fakes.world_folders(root)
    if not (folders.research / "facts.json").is_file():
        raise SystemExit(f"{root} holds no event-chain world (review_browser_server.py --copper-events synthetic)")
    return folders


def publish_next(root: Path, chain_id: str, answers: str, note: str, label: str | None) -> None:
    folders = _world(root)
    folder = folders.theses / fakes.THESIS / "event-chains" / chain_id
    index = _read(folder / "index.json")
    versions = [_read(folder / entry["file"]) for entry in index["versions"]]
    latest = versions[-1]
    following = copy.deepcopy(latest)
    following.update(version=latest["version"] + 1, previous_version=latest["version"],
                     change={"answers_review": answers, "note": note}, evidence=None)
    if label is not None:
        following["steps"][1]["label"] = label
    following["evidence"] = evidence.pin(following, folders)
    fakes.write_chain(folders.theses, chain_id, [*versions, following],
                      [entry["published_on"] for entry in index["versions"]] + [DAY])


def edit_record(root: Path, passage: str, field: str, value: str) -> None:
    facts = _world(root).research / "facts.json"
    kept = root / KEPT / "facts.json"
    if kept.exists():
        raise SystemExit("A record edit is already in place; undo it first")
    original = facts.read_bytes()
    data = json.loads(original.decode("utf-8"))
    found = [item for item in data["passages"] if item["id"] == passage]
    if len(found) != 1 or field not in found[0] or field == "id":
        raise SystemExit(f"facts.json has no single passage {passage!r} with a field {field!r} to edit")
    found[0][field] = value
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(original)
    facts.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


def undo_record(root: Path) -> None:
    facts = _world(root).research / "facts.json"
    kept = root / KEPT / "facts.json"
    if not kept.is_file():
        raise SystemExit("No record edit is in place")
    facts.write_bytes(kept.read_bytes())
    kept.unlink()
    kept.parent.rmdir()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish-next", help="publish a chain's next version, answering a review")
    publish.add_argument("--root", type=Path, required=True)
    publish.add_argument("--chain", required=True)
    publish.add_argument("--answers", required=True, help="the id of the review the version answers")
    publish.add_argument("--note", required=True, help="the change note: one line, no digits")
    publish.add_argument("--label", default=None, help="a new label for the second step")
    edit = commands.add_parser("edit-record", help="edit one field of one passage in the served facts.json")
    edit.add_argument("--root", type=Path, required=True)
    edit.add_argument("--passage", required=True)
    edit.add_argument("--field", required=True)
    edit.add_argument("--value", required=True)
    undo = commands.add_parser("undo-record", help="put the served facts.json back as it was")
    undo.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "publish-next":
        publish_next(args.root, args.chain, args.answers, args.note, args.label)
    elif args.command == "edit-record":
        edit_record(args.root, args.passage, args.field, args.value)
    else:
        undo_record(args.root)


if __name__ == "__main__":
    main()
