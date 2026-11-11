"""The fuels operator commands (python -m second_order fuels ...). Neither report ever carries a price value."""
import argparse
from datetime import date, datetime, timezone
from pathlib import Path

from . import fuels_snapshots, fuels_sources, fuels_view
from .fred import ImportRefused

NEXT = "python -m second_order fuels status"


def add_commands(commands: argparse._SubParsersAction) -> None:
    fuels = commands.add_parser("fuels", help="The fuels page: refresh its EIA snapshot and read its status")
    actions = fuels.add_subparsers(dest="fuels_action", required=True)
    refresh = actions.add_parser("refresh", help="Request the five EIA spot series once and append a snapshot; "
                                                 "uses EIA_API_KEY when set, else the key stored by `fuels key set`")
    refresh.add_argument("--start", type=date.fromisoformat, help="First observation date, YYYY-MM-DD")
    status = actions.add_parser("status", help="Snapshot and note states, dates and counts; never a value")
    for sub in (refresh, status):
        sub.add_argument("--snapshots", type=Path, default=fuels_snapshots.SNAPSHOTS_DIR)
        sub.add_argument("--content", type=Path, default=fuels_sources.CONTENT_DIR)
    key = actions.add_parser("key", help="The EIA key kept in Windows Credential Manager; it is never printed")
    key_actions = key.add_subparsers(dest="key_action", required=True)
    key_actions.add_parser("set", help="Store the key once, typed twice at a hidden prompt; refreshes nothing")
    key_actions.add_parser("replace", help="Store a new key in place of the stored one, typed twice, hidden")
    key_actions.add_parser("delete", help="Remove the stored key")
    key_actions.add_parser("status", help="Whether a key is stored and whether EIA_API_KEY is set; never the key")


def refresh_report(snapshots: Path, content: Path, api_key: str, start: date | None, client=None,
                   clock=lambda: datetime.now(timezone.utc)) -> dict:
    from .fuels_eia import refresh  # The only network path; loaded only here.
    return {**refresh(snapshots, content, api_key, start, client, clock), "next": NEXT}


def status_report(content: Path, snapshots: Path) -> dict:
    page = fuels_view.view(content, snapshots)
    snapshot, barrel = page["snapshot"], page["barrel"]
    latest = None
    if snapshot["id"]:
        latest = {"snapshot_id": snapshot["id"], "retrieved_at": snapshot["retrieved_at"],
                  "retrieved_on": snapshot["retrieved_on"], "provider": snapshot["provider"], "barrel_date": barrel["date"],
                  "previous_date": barrel["previous_date"], "barrel_state": barrel["state"],
                  "series": {row["series_id"]: {"state": row["state"],
                                                "last_date": row["latest"]["date"] if row["latest"] else None,
                                                "publication_date":
                                                    row["latest"]["published_on"] if row["latest"] else None}
                             for row in page["series"]}}
    notes = [{key: note[key] for key in ("number", "state", "snapshot_id", "observation_date")}
             for note in page["notes"]]
    return {"snapshots": len(page["snapshots"]), "state": snapshot["state"], "problem": snapshot["problem"],
            "latest": latest, "notes": notes}


def run(args: argparse.Namespace) -> dict:
    """A refusal leaves as ImportRefused, so main() prints "Failed: <message>" rather than a traceback."""
    try:
        return _run(args)
    except fuels_sources.FuelsRefused as exc:
        raise ImportRefused(str(exc)) from None


def _run(args: argparse.Namespace) -> dict:
    if args.fuels_action == "status":
        return status_report(args.content, args.snapshots)
    from . import fuels_key  # The key's store: loaded only by `fuels key` and `fuels refresh`.
    if args.fuels_action == "key":
        return fuels_key.run(args.key_action)
    api_key, source = fuels_key.refresh_key()
    return {**refresh_report(args.snapshots, args.content, api_key, args.start), "key_from": source}
