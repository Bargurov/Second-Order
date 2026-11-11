"""Recorded assessments of frozen hypotheses, their prepared Dossiers, and drafts' links to freezes. Reads, except for
one explicit action: preparing the Dossier of one stored assessment.

Preparing builds the store Dossier view of exactly one hypothesis and one of its stored evaluations (store_dossier):
the chart and reference distribution are rebuilt from the pinned baseline and outcome snapshots, the recorded rules and
the recorded cutoff, and the rebuilt evaluation must equal the stored one exactly, or nothing is written. Nothing new is
recorded and no other view is touched: the file is created once, beside the store (Folders.dossiers), and never
rewritten. A Dossier read checks the file against its own fingerprint and the stored evaluation, and reports apart
whether the snapshots still verify in the store (reproducibility) and whether a raw source file is held here (a
snapshot's observations are copied in the store, so it does not need the package folder). Reads never evaluate,
import, prepare or fetch.

Draft links are derived from verified freeze records only: a freeze action whose identity, hypothesis and effective
content verify, joined to a draft by the draft ID the freeze recorded, never by matching titles or dates. Drafts,
published views, saved requests and reviews are never rewritten.
"""
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable

from . import market_store
from .dossier import VIEW_VERSION, shared_view
from .freeze_origins import LIFECYCLE_VERSION, Folders, LifecycleRefused
from .registry import FRED
from .schema import Hypothesis, utc
from .scoring import Rules
from .snapshots import Snapshot, verify_snapshot
from .store import connect_read_only, digest, store_schema
from .store_dossier import build_store_dossier, select_evaluation

SHA = re.compile(r"[0-9a-f]{64}")
DOSSIER_VERSION = "lifecycle-dossier-0.1"
# A prepared file is created once and never rewritten, and a store case's view has the same shape in dossier-view-0.2
# and 0.3 (0.3 changed only the fixture showcases), so a file prepared at 0.2 is still read; new files carry 0.3.
READABLE_VIEW_VERSIONS = ("dossier-view-0.2", VIEW_VERSION)
DOSSIER_FIELDS = {"dossier_version", "hypothesis_id", "evaluation_id", "action_id", "prepared_at", "view_version",
                  "view_sha256", "view", "reproduction"}
REPRODUCTION = ("Prepared from the stored assessment: the chart and reference distribution were rebuilt from the pinned "
                "baseline and outcome snapshots, the recorded rules and the recorded cutoff, and the rebuilt "
                "assessment matched the stored one exactly. Preparing recorded nothing new.")


class PreparationFailed(ValueError):
    pass


def _ids(*values: str) -> None:
    if not all(isinstance(value, str) and SHA.fullmatch(value) for value in values):
        raise LifecycleRefused(404, "Unknown hypothesis or assessment")


def dossier_path(folders: Folders, hypothesis_id: str, evaluation_id: str) -> Path:
    return folders.dossiers / hypothesis_id / f"{evaluation_id}.json"


def _relative(folders: Folders, path: Path) -> str:
    return f"{folders.dossiers.name}/{path.relative_to(folders.dossiers).as_posix()}"


def read_prepared(path: Path, hypothesis_id: str, evaluation_id: str) -> dict:
    """A prepared Dossier file checked against itself: fields, versions, identities and the view's fingerprint."""
    try:
        record = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise PreparationFailed("The prepared Dossier file cannot be read") from None
    if not isinstance(record, dict) or set(record) != DOSSIER_FIELDS or record["dossier_version"] != DOSSIER_VERSION \
            or record["view_version"] not in READABLE_VIEW_VERSIONS or not isinstance(record["view"], dict):
        raise PreparationFailed("The prepared Dossier file does not have this version's fields")
    view = record["view"]
    if (record["hypothesis_id"], record["evaluation_id"]) != (hypothesis_id, evaluation_id) or \
            (view.get("id"), view.get("evaluation_id")) != (hypothesis_id, evaluation_id) or \
            view.get("view_version") != record["view_version"] or digest(view) != record["view_sha256"]:
        raise PreparationFailed("The prepared Dossier file does not match its assessment or its fingerprint")
    return record


def dossier_state(folders: Folders, hypothesis_id: str, evaluation_id: str) -> dict:
    """Whether one assessment's Dossier is prepared. Reads only."""
    path = dossier_path(folders, hypothesis_id, evaluation_id)
    if not path.is_file():
        return {"state": "not_prepared", "detail": "No Dossier has been prepared for this assessment.",
                "prepared_at": None, "file": None}
    try:
        record = read_prepared(path, hypothesis_id, evaluation_id)
    except PreparationFailed as exc:
        return {"state": "problem", "detail": f"{exc}; it is not shown and was left as it is.", "prepared_at": None,
                "file": _relative(folders, path)}
    return {"state": "prepared", "detail": None, "prepared_at": record["prepared_at"], "file": _relative(folders, path)}


def _actions(connection: sqlite3.Connection, hypothesis_id: str) -> dict[str, tuple[str, dict]]:
    if store_schema(connection) != 4:
        return {}
    return {evaluation_id: (action_id, json.loads(payload)) for action_id, evaluation_id, payload in connection.execute(
        "SELECT action_id, evaluation_id, payload FROM assessment_actions WHERE hypothesis_id=?", (hypothesis_id,))}


def recorded_assessments(connection: sqlite3.Connection, folders: Folders, hypothesis_id: str) -> list[dict]:
    """Every stored evaluation of one hypothesis, oldest first, with how it was recorded and its Dossier's state."""
    actions = _actions(connection, hypothesis_id)
    rows = []
    for evaluation_id, recorded_at, payload in connection.execute(
            "SELECT id, recorded_at, payload FROM evaluations WHERE hypothesis_id=? ORDER BY recorded_at, id",
            (hypothesis_id,)):
        result = json.loads(payload)
        action = actions.get(evaluation_id)
        pinned = result.get("snapshots") or {}
        rows.append({"evaluation_id": evaluation_id, "recorded_at": recorded_at, "as_of": result["as_of"],
                     "verdict": result["verdict"], "rules_version": result["rules"]["version"],
                     "rules_hash": result["rules_hash"], "baseline_snapshot_id": pinned.get("baseline"),
                     "outcome_snapshot_id": pinned.get("outcome"),
                     "legs": [{key: leg.get(key) for key in ("leg_id", "primary", "observable_id", "verdict")}
                              for leg in result["legs"]],
                     "action_id": action[0] if action else None,
                     "recorded_by": "interface approval" if action else "outside this interface (offline command)",
                     "dossier": dossier_state(folders, hypothesis_id, evaluation_id)})
    return rows


def _bound(connection: sqlite3.Connection, hypothesis_id: str) -> tuple[Hypothesis, str]:
    row = connection.execute("SELECT h.payload, b.baseline_snapshot_id FROM hypotheses h JOIN freeze_bindings b ON "
                             "b.hypothesis_id = h.id WHERE h.id=?", (hypothesis_id,)).fetchone() \
        if store_schema(connection) in (2, 3, 4) else None
    if row is None:
        raise LifecycleRefused(404, "No frozen hypothesis with a baseline bound at freeze has this ID in this store")
    if digest(json.loads(row[0])) != hypothesis_id:
        raise LifecycleRefused(500, "The stored hypothesis does not match its ID; it is not used")
    return Hypothesis.model_validate_json(row[0]), row[1]


def _connect(folders: Folders) -> sqlite3.Connection:
    if not folders.store.is_file():
        raise LifecycleRefused(409, "No store exists yet")
    try:
        return connect_read_only(str(folders.store))
    except ValueError as exc:
        raise LifecycleRefused(409, str(exc)) from None


def prepare_dossier(folders: Folders, hypothesis_id: str, evaluation_id: str,
                    clock: Callable[[], datetime]) -> dict:
    """Prepare the Dossier of one stored assessment: one file, created once. An existing file that verifies is returned
    as it is; one that does not is left alone and reported. Raises PreparationFailed when nothing could be prepared."""
    _ids(hypothesis_id, evaluation_id)
    path = dossier_path(folders, hypothesis_id, evaluation_id)
    if path.exists():
        record = read_prepared(path, hypothesis_id, evaluation_id)
        return {"created": False, "prepared_at": record["prepared_at"], "file": _relative(folders, path)}
    connection = _connect(folders)
    try:
        hypothesis, baseline_id = _bound(connection, hypothesis_id)
        selected = select_evaluation(connection, hypothesis_id, evaluation_id)
        rules = Rules(**selected[1]["rules"])
        view = build_store_dossier(connection, hypothesis_id, hypothesis, baseline_id, selected,
                                   shared_view(hypothesis_id, hypothesis, rules))
        action = connection.execute("SELECT action_id FROM assessment_actions WHERE evaluation_id=?",
                                    (evaluation_id,)).fetchone() if store_schema(connection) == 4 else None
    except ValueError as exc:  # Includes a stored assessment that its pinned inputs do not reproduce.
        raise PreparationFailed(str(exc)) from None
    finally:
        connection.close()
    record = {"dossier_version": DOSSIER_VERSION, "hypothesis_id": hypothesis_id, "evaluation_id": evaluation_id,
              "action_id": action[0] if action else None, "prepared_at": utc(clock()).isoformat(),
              "view_version": view["view_version"], "view_sha256": digest(view), "view": view,
              "reproduction": REPRODUCTION}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PreparationFailed(f"The Dossier folder cannot be created ({type(exc).__name__})") from None
    try:
        market_store.write_exclusive(path, record)
    except FileExistsError:  # Another request prepared it first; its file is the one kept.
        record = read_prepared(path, hypothesis_id, evaluation_id)
        return {"created": False, "prepared_at": record["prepared_at"], "file": _relative(folders, path)}
    return {"created": True, "prepared_at": record["prepared_at"], "file": _relative(folders, path)}


def raw_source(folders: Folders, snapshot: Snapshot) -> dict:
    """Whether the source a snapshot was built from is held here. A snapshot stands without it either way."""
    if snapshot.provider == FRED:
        return {"held": None, "detail": "Retrieved from FRED's API; no source file is kept locally. The snapshot holds "
                                        "FRED's responses, compressed, and every classified row."}
    package_id = snapshot.payload["source"]["package_id"]
    folder = folders.market / market_store.PACKAGES / package_id
    if not folder.is_dir():
        return {"held": False, "detail": f"Release package {package_id} is not held here. The snapshot does not need "
                                         "it: both series are copied in the store with their SHA-256."}
    try:
        summary, _ = market_store.package_state(folder)
    except market_store.StoreRefused as exc:
        return {"held": False, "detail": f"Release package {package_id} is here but does not verify ({exc}). The "
                                         "snapshot does not need it."}
    if summary["sha256"] != snapshot.payload["source"]["package_sha256"]:
        return {"held": False, "detail": f"The package folder {package_id} holds other bytes than the snapshot was "
                                         "built from. The snapshot does not need it."}
    return {"held": True, "detail": f"Release package {package_id} is held here and verifies ({summary['status']})."}


def _snapshot_status(connection: sqlite3.Connection, folders: Folders, snapshot_id: str) -> dict:
    try:
        snapshot = verify_snapshot(connection, snapshot_id)
    except ValueError as exc:
        return {"snapshot_id": snapshot_id, "verifies": False, "detail": str(exc), "raw_source": None}
    return {"snapshot_id": snapshot_id, "verifies": True, "provider": snapshot.provider,
            "detail": "Its stored rows verify against their recorded hashes and classification.",
            "raw_source": raw_source(folders, snapshot)}


def dossier_view(hypothesis_id: str, evaluation_id: str, folders: Folders) -> dict:
    """One prepared Dossier, verified against its file fingerprint and the stored assessment. Reads only."""
    _ids(hypothesis_id, evaluation_id)
    path = dossier_path(folders, hypothesis_id, evaluation_id)
    if not path.is_file():
        raise LifecycleRefused(404, "No Dossier has been prepared for this assessment. Preparing it is an explicit "
                                    "action on the assessment's page")
    try:
        record = read_prepared(path, hypothesis_id, evaluation_id)
    except PreparationFailed as exc:
        raise LifecycleRefused(409, f"{exc}; it is not shown") from None
    connection = _connect(folders)
    try:
        stored = connection.execute("SELECT payload FROM evaluations WHERE id=? AND hypothesis_id=?",
                                    (evaluation_id, hypothesis_id)).fetchone()
        if stored is None or json.loads(stored[0]) != record["view"]["evaluation"]:
            raise LifecycleRefused(409, "The prepared Dossier does not match the stored assessment; it is not shown")
        pinned = record["view"]["evaluation"]["snapshots"]
        snapshots = {role: _snapshot_status(connection, folders, pinned[role]) for role in ("baseline", "outcome")}
    finally:
        connection.close()
    return {"lifecycle_version": LIFECYCLE_VERSION, "dossier_version": DOSSIER_VERSION,
            "hypothesis_id": hypothesis_id, "evaluation_id": evaluation_id, "action_id": record["action_id"],
            "prepared_at": record["prepared_at"], "reproduction": record["reproduction"], "view": record["view"],
            "snapshots": snapshots, "written": False}


# ---------------------------------------------------------------- drafts and the freezes that used them

def _verified_link(connection: sqlite3.Connection, action_id: str, hypothesis_id: str, payload: str) -> dict | None:
    """A model freeze's link to its draft, or None for a manual one. Raises ValueError when the record does not
    verify: its identity is the SHA-256 of what it approved, and the stored hypothesis is exactly that content."""
    action = json.loads(payload)
    binding = action.get("binding") or {}
    origin = binding.get("origin") or {}
    if origin.get("kind") != "model":
        return None
    row = connection.execute("SELECT payload FROM hypotheses WHERE id=?", (hypothesis_id,)).fetchone()
    stored = json.loads(row[0]) if row else None
    rebuilt = None
    if stored is not None and isinstance(binding.get("effective_hypothesis"), dict):
        try:  # The record the freeze stored: the approved content, frozen at the recorded time.
            rebuilt = Hypothesis.model_validate_json(json.dumps({**binding["effective_hypothesis"],
                                                                 "frozen_at": stored["frozen_at"]}), strict=True)
        except ValueError:
            rebuilt = None
    if digest(binding) != action_id or action.get("hypothesis_id") != hypothesis_id or stored is None or \
            digest(stored) != hypothesis_id or digest(binding["effective_hypothesis"]) != action.get("effective_sha256") \
            or rebuilt is None or digest(rebuilt.model_dump(mode="json")) != hypothesis_id:
        raise ValueError(f"The freeze record {action_id[:12]} does not verify")
    return {"draft_id": origin["draft_id"], "capture_id": origin["capture_id"], "hypothesis_id": hypothesis_id,
            "action_id": action_id, "frozen_at": stored["frozen_at"], "headline": stored["event"]["headline"],
            "draft_view_sha256": origin["draft_view_sha256"], "review_at_freeze": origin["review"]}


def draft_links(folders: Folders) -> dict:
    """Which Tracker drafts were frozen, from verified freeze records only. Reads only; no draft record changes."""
    links, problems = [], []
    if folders.store.is_file():
        connection = _connect(folders)
        try:
            rows = connection.execute("SELECT action_id, hypothesis_id, payload FROM freeze_actions ORDER BY "
                                      "recorded_at, action_id").fetchall() if store_schema(connection) in (3, 4) else []
            for action_id, hypothesis_id, payload in rows:
                try:
                    link = _verified_link(connection, action_id, hypothesis_id, payload)
                except (ValueError, KeyError, TypeError) as exc:
                    problems.append({"action_id": action_id, "problem": str(exc) if isinstance(exc, ValueError)
                                     else f"The freeze record {action_id[:12]} is incomplete"})
                    continue
                if link is not None:
                    links.append(link)
        finally:
            connection.close()
    return {"lifecycle_version": LIFECYCLE_VERSION, "links": links, "problems": problems,
            "note": ("Derived from verified freeze records, joined by the draft ID each freeze recorded. The draft, its "
                     "published view, its saved request and its reviews are unchanged; a draft's own record keeps the "
                     "status it was prepared with.")}
