"""Write-once, hash-named snapshot files of retrieved fuel spot prices, verified on every read.

Reads never fetch: this module touches only local files. New snapshots are fuels-snapshot-0.2 (EIA). A
fuels-snapshot-0.1 file (FRED, written before the page moved to EIA) still reads and verifies as it is: it is never
rewritten, and the view withholds its values because the page no longer reads that provider.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date
from fractions import Fraction
from pathlib import Path

from . import bis_snapshot, store
from .fuels_sources import ROOT
from .thesis_arithmetic import decimal_of

SNAPSHOT_VERSION = "fuels-snapshot-0.2"
READABLE_VERSIONS = ("fuels-snapshot-0.1", SNAPSHOT_VERSION)
SNAPSHOTS_DIR = ROOT / "data" / "fuels" / "snapshots"
SEMANTICS = {
    "observation_date": "the trading day the price describes",
    "eia_publication_date": ("not given by EIA's API: stored as unknown and shown as missing, never inferred from the "
                             "observation date or the retrieval; EIA releases spot prices weekly"),
    "retrieved_at": "our clock after the last reply arrived; shows possession, not first public availability",
    "history": ("the values EIA's file held when retrieved; not a record of what was known on the days they "
                "describe, since EIA may revise a value after it first publishes it"),
}
MISSING = "No fuels snapshot on this machine. Run: python -m second_order fuels refresh"
_NAME = re.compile(r"[0-9a-f]{64}\.json")


def _bytes_of(payload: dict) -> bytes:
    return store.canonical(payload).encode("utf-8")


def write(folder: Path, payload: dict) -> tuple[str, bool]:
    data = _bytes_of(payload)
    snapshot_id = hashlib.sha256(data).hexdigest()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{snapshot_id}.json"
    if path.exists() and path.read_bytes() == data:
        return snapshot_id, False
    temporary = folder / f"{snapshot_id}.json.tmp"
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return snapshot_id, True


def _changed(name: str, why: str) -> dict:
    return {"state": "changed", "problem": f"Fuels snapshot {name[:12]} {why}; every price is withheld.", "snapshots": []}


def load_all(folder: Path | None) -> dict:
    files = sorted(p for p in Path(folder).iterdir() if p.name.endswith(".json")) if folder is not None and Path(folder).is_dir() else []
    if not files:
        return {"state": "missing", "problem": MISSING, "snapshots": []}
    loaded = []
    for path in files:
        if not _NAME.fullmatch(path.name):
            return _changed(path.name, "has a name that is not its content hash")
        data = path.read_bytes()
        snapshot_id = path.name[:-len(".json")]
        if hashlib.sha256(data).hexdigest() != snapshot_id:
            return _changed(snapshot_id, "no longer matches its hash")
        try:
            payload = bis_snapshot._strict_json(data.decode("utf-8"), "snapshot")
        except (bis_snapshot.SnapshotRefused, UnicodeDecodeError):
            return _changed(snapshot_id, "is not strict JSON")
        if not isinstance(payload, dict) or payload.get("snapshot_version") not in READABLE_VERSIONS:
            return _changed(snapshot_id, "is not a snapshot of the expected version")
        loaded.append({**payload, "snapshot_id": snapshot_id})
    loaded.sort(key=lambda s: (str(s.get("retrieved_at")), s["snapshot_id"]))
    return {"state": "verified", "problem": None, "snapshots": loaded}


def values(entry: dict) -> dict[date, Fraction | None]:
    return {date.fromisoformat(day): None if raw is None else Fraction(decimal_of(raw))
            for day, raw in entry["observations"]}


def retrieved_on(snapshot: dict) -> str | None:
    """The New York date of the retrieval: fuels-snapshot-0.2's retrieved_on, or 0.1's vintage date (FRED's real-time
    period, which the FRED importer set to that same date)."""
    return snapshot.get("retrieved_on") or snapshot.get("vintage_date")


def published_on(entry: dict, day: date) -> date | None:
    """The first listed release strictly after the observation date (a release carries data through the days before
    it), or None. An EIA entry lists no release (its API gives none), so its publication date is always None."""
    later = [d for d in map(date.fromisoformat, entry["release_dates"]) if d > day]
    return min(later) if later else None
