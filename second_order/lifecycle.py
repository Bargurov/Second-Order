"""The interface's path to one explicit freeze of an H.15-bound prospective showcase hypothesis.

Two origins, one freeze:
- manual: a structured form on the registered H.15 observables. The person chooses each leg's direction, horizon,
  link, channel, rationale and falsifier, its headline_reports_move flag and the primary leg, and states how the
  content was authored. Engine provenance is honest about that: provider "manual", the authoring statement as the
  model text, and the SHA-256 of the exact submitted input (kept in the freeze record) as its prompt_hash.
- model: a draft of the Tracker's paid run built under the H.15 drafting contract (draft-prompt-6), with a draft
  outcome and a current human review: the latest saved version is bound to the exact view fingerprint served now and
  has the status "human_reviewed". Only the corrections the review workflow permits (summary; each leg's rationale,
  falsifier and headline_reports_move) are applied. The model's output, the engine record (the model that answered
  and the SHA-256 of the exact request) and every draft and review record stay unchanged; the effective content and
  its derivation are recorded in the freeze record. Mock drafts, declines, invalid responses, technical failures,
  requests saved under another contract, and missing, stale or not-yet-approved reviews are never eligible. Human
  review is not approval to freeze.

A baseline is a store snapshot of provider board-h15, chosen from the store or imported explicitly from a kept,
validated release package (package_snapshots; idempotent). Reads never import.

Preview writes nothing. It shows the exact effective hypothesis, the baseline's provenance, coverage and possession
time, freshness policy B, readiness, the scoring window and the limitations, and its SHA-256 binds what an approval
approves: the effective hypothesis, its origin (draft, view fingerprint and review version, or the manual input), the
baseline, the source bindings, the freshness policy and the New York freeze date that sets the scoring anchor.

Freeze is one explicit approval of one preview. The server recomputes the preview from the same inputs; any change
(review, content, baseline, policy or the New York date) refuses it and returns the new preview to approve. The
server stamps the freeze time (no client or backdated time) and stores the hypothesis, its baseline binding and the
freeze action (keyed by the preview SHA-256) in one transaction (store.freeze_with_action). Repeating the same
approval returns the original freeze; a lost reply is resolved by reading the action's outcome, never by sending again.

Everything frozen here is a prospective showcase: daily-date H.15 observations do not meet the research timestamp
gate, research intake is closed, and showcase cases never enter research summaries or rates. Nothing here evaluates,
prepares a Dossier, downloads, calls a model or fetches anything; assessment (explicit evaluation and Dossier
preparation) is a separate step, see assessment.
"""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable

from pydantic import ValidationError

from . import market_store
from .data import ny_date
from .evaluation import DAILY_CONVENTION_NOTE
from .freeze_origins import (H15_IDS, LIFECYCLE_VERSION, STORE_PATH, Folders, LifecycleRefused,  # noqa: F401
                             draft_eligibility, drafts_listing, manual_draft, model_draft)
from .model_draft import errors
from .package_snapshots import PackageImportRefused, import_package
from .registry import BOARD_H15, binding, resolve
from .schema import Hypothesis, utc
from .snapshots import list_snapshots, load_snapshot, snapshot_readiness
from .store import (FRESHNESS_POLICY, bound_provider, check_freshness, connect_read_only, digest, freeze_with_action,
                    migrate_store, open_store, request_identity, store_schema)

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 64_000
SHA = re.compile(r"[0-9a-f]{64}")
INPUT_FIELDS = ("origin", "manual", "draft_id", "baseline_snapshot_id")
CLASSIFICATION = ("Prospective showcase: a lifecycle demonstration under the daily date convention. It is excluded "
                  "from research summaries and rates; H.15 observations are dated, not timed, so they do not meet "
                  "the research timestamp gate, and research intake is closed.")
FROZEN_NOT_EVALUATED = "Frozen · Not evaluated"
LIMITATIONS = (
    "Daily date convention: H.15 observations are compared by America/New_York date; no intraday observation time is "
    "observed or claimed, so whether a value came before or after the publication cannot be told.",
    "No historical vintage: the Board's release package holds its values as published when the package was received. "
    "The receipt time shows possession, not first publication, and earlier values cannot be recovered from it.",
    "Two maturities of one yield curve demonstrate the lifecycle; they are not independent evidence.",
    "Labels later describe whether observations were consistent with the frozen hypothesis. They are not causal "
    "proof, significance tests or trading signals.",
)
POLICY_NOTE = ("Freshness policy B: the baseline must classify, for every leg, the last expected session before the "
               "publication date. A session the source states without a value counts as covered and stays missing; "
               "reference history is never completed from outcome data.")


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- strict input

def strict_body(body: bytes, fields: tuple[str, ...], label: str) -> dict:
    if len(body) > MAX_BODY:
        raise LifecycleRefused(413, f"The {label} is limited to {MAX_BODY} bytes")
    try:
        payload = json.loads(body.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, ValueError):
        raise LifecycleRefused(422, f"The {label} must be strict JSON") from None
    if not isinstance(payload, dict) or set(payload) != set(fields):
        raise LifecycleRefused(422, f"The {label} must contain exactly {', '.join(fields)}")
    return payload


def _pairs(items: list) -> dict:
    if len({key for key, _ in items}) != len(items):
        raise ValueError("repeated key")
    return dict(items)


def _constant(name: str):
    raise ValueError(name)


def parse_inputs(payload: object) -> dict:
    """What a preview or an approval is about: the origin, its content or draft, and the baseline."""
    if not isinstance(payload, dict) or set(payload) != set(INPUT_FIELDS):
        raise LifecycleRefused(422, f"The inputs must contain exactly {', '.join(INPUT_FIELDS)}")
    origin = payload["origin"]
    if origin not in ("manual", "model"):
        raise LifecycleRefused(422, "origin must be manual or model")
    if origin == "manual" and (payload["draft_id"] is not None or not isinstance(payload["manual"], dict)):
        raise LifecycleRefused(422, "A manual hypothesis gives the form's content in manual and no draft_id")
    if origin == "model" and (payload["manual"] is not None or not isinstance(payload["draft_id"], str)
                              or not SHA.fullmatch(payload["draft_id"])):
        raise LifecycleRefused(422, "A model draft gives its draft_id and no manual content")
    if not isinstance(payload["baseline_snapshot_id"], str) or not SHA.fullmatch(payload["baseline_snapshot_id"]):
        raise LifecycleRefused(422, "baseline_snapshot_id must name a stored snapshot")
    return payload


def effective(inputs: dict, folders: Folders, clock: Callable[[], datetime]) -> tuple[dict, dict]:
    if inputs["origin"] == "manual":
        return manual_draft(inputs["manual"], clock)
    return model_draft(inputs["draft_id"], folders)


# ---------------------------------------------------------------- the store, read only

def store_state(folders: Folders) -> dict:
    path = folders.store
    if not path.is_file():
        return {"exists": False, "schema": None, "interface_freezes": False, "assessments": False,
                "detail": "No store exists at the configured path yet. Importing a baseline creates it (schema 4)."}
    try:
        connection = connect_read_only(str(path))
    except ValueError as exc:
        return {"exists": True, "schema": None, "interface_freezes": False, "assessments": False, "detail": str(exc)}
    try:
        version = store_schema(connection)
    finally:
        connection.close()
    needs = ("Assessments need schema 4 (an added assessment-action table)" if version == 3 else
             "Interface freezes need schema 3 or 4 and assessments schema 4 (added action tables)")
    return {"exists": True, "schema": version, "interface_freezes": version in (3, 4), "assessments": version == 4,
            "detail": None if version == 4 else (
                f"This store uses schema {version}. {needs}; upgrading to schema 4 is an explicit action that only "
                "adds tables and leaves every existing record unchanged.")}


def _reader(folders: Folders) -> sqlite3.Connection:
    if not folders.store.is_file():
        raise LifecycleRefused(409, "No store exists yet; import a baseline first")
    try:
        return connect_read_only(str(folders.store))
    except ValueError as exc:
        raise LifecycleRefused(409, str(exc)) from None


def _coverage(payload: dict) -> dict:
    return {series_id: {key: entry.get(key) for key in ("observable_id", "first_date", "last_date", "classified_from",
                                                         "classified_through", "rows", "statuses")}
            for series_id, entry in payload["series"].items()}


def baseline_summary(snapshot) -> dict:
    """What a reader needs about a baseline: provider, possession, vintage (none for H.15), coverage, source."""
    payload = snapshot.payload
    board = payload["provider"] == BOARD_H15
    return {"snapshot_id": snapshot.id, "provider": payload["provider"],
            "provider_label": "Federal Reserve Board H.15 release package" if board else "FRED",
            "retrieved_at": payload["retrieved_at"],
            "possession_note": payload["semantics"]["retrieved_at"],
            "vintage_date": payload["vintage_date"],
            "vintage_note": payload["semantics"]["vintage_date"] if board else payload["semantics"].get("vintage_date"),
            "created_at": payload.get("created_at"),
            "package": {key: payload["source"][key] for key in ("package_id", "package_sha256", "received_at", "url")}
            if board else None,
            "source_prepared_as_stated": payload["validation"]["header"]["prepared_as_stated"] if board else None,
            "adapter_version": payload["adapter_version"], "coverage": _coverage(payload)}


def baselines(folders: Folders) -> dict:
    """The store's H.15 snapshots and the kept packages that could become one. Reads only: nothing is imported."""
    snapshots = []
    if folders.store.is_file():
        connection = _reader(folders)
        try:
            if store_schema(connection) in (2, 3, 4):
                snapshots = [baseline_summary(load_snapshot(connection, row["snapshot_id"]))
                             for row in list_snapshots(connection) if row["provider"] == BOARD_H15]
        finally:
            connection.close()
    _, problems, packages = market_store.local_data(folders.market, None)
    imported = {}
    for snapshot in snapshots:
        imported.setdefault(snapshot["package"]["package_id"], []).append(snapshot["snapshot_id"])
    return {"lifecycle_version": LIFECYCLE_VERSION, "snapshots": snapshots,
            "packages": [{key: package.get(key) for key in ("package_id", "status", "detail", "received_at",
                                                            "requested_at", "sha256", "bytes", "coverage",
                                                            "release_prepared", "validated_at")}
                         | {"importable": package["status"] == "accepted",
                            "snapshots": imported.get(package["package_id"], [])} for package in packages],
            "problems": problems,
            "note": ("Importing copies a kept, validated package's two series into the store, locally; repeating it "
                     "reuses the snapshot. A newer package needs its own approved retrieval under Market context; "
                     "nothing here downloads.")}


def import_baseline(body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    """The explicit local import of a kept package into the store (creating a schema-3 store if none exists)."""
    payload = strict_body(body, ("package_id", "start"), "import")
    if not isinstance(payload["package_id"], str) or not isinstance(payload["start"], str):
        raise LifecycleRefused(422, "package_id and start must be text")
    try:
        start = date.fromisoformat(payload["start"])
    except ValueError:
        raise LifecycleRefused(422, "start must be a date, YYYY-MM-DD") from None
    folders.store.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = open_store(str(folders.store))
    except ValueError as exc:
        raise LifecycleRefused(409, str(exc)) from None
    try:
        stored = import_package(connection, payload["package_id"], start, folders.market, clock)
        snapshot = baseline_summary(load_snapshot(connection, stored["snapshot_id"]))
    except PackageImportRefused as exc:
        raise LifecycleRefused(409, str(exc)) from None
    finally:
        connection.close()
    return {"lifecycle_version": LIFECYCLE_VERSION, "created": stored["created"], "snapshot": snapshot,
            "provider_called": False}


def upgrade_store(body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    payload = strict_body(body, ("upgrade_to",), "upgrade")
    if payload["upgrade_to"] != 4:
        raise LifecycleRefused(422, "upgrade_to must be 4")
    if not folders.store.is_file():
        raise LifecycleRefused(409, "No store exists at the configured path; importing a baseline creates one at "
                                    "schema 4")
    try:
        result = migrate_store(str(folders.store), utc(clock()))
    except (ValueError, RuntimeError) as exc:
        raise LifecycleRefused(409, str(exc)) from None
    return {"lifecycle_version": LIFECYCLE_VERSION, **result}


# ---------------------------------------------------------------- preview and freeze

def _sessions_after(day: date, count: int) -> list[date]:
    from .market_calendar import expected_sessions
    return sorted(expected_sessions(day + timedelta(days=1), day + timedelta(days=60)))[:count]


def scoring_window(hypothesis: Hypothesis, freeze_date: date) -> dict:
    """The expected scoring window under the daily convention, from the SIFMA calendar: a plan, not a measurement."""
    sessions = _sessions_after(freeze_date, 1 + max(leg.horizon for leg in hypothesis.legs))
    return {"freeze_date_new_york": freeze_date.isoformat(),
            "rule": ("Scoring starts at the first observation dated after the New York freeze date; each leg's move is "
                     "measured over its horizon in observations from there. Dates between the event anchor and the "
                     "scoring anchor stay unscored."),
            "expected_score_anchor": sessions[0].isoformat() if sessions else None,
            "legs": {leg.id: {"horizon": leg.horizon,
                              "expected_target": sessions[leg.horizon].isoformat()
                              if len(sessions) > leg.horizon else None} for leg in hypothesis.legs},
            "note": ("Expected dates follow the SIFMA calendar. The measured dates are those the outcome data record: "
                     "a missing session makes a leg unavailable, and a horizon not yet in the data leaves it pending.")}


def _readiness(snapshot, hypothesis: Hypothesis) -> tuple[dict, list[str]]:
    report = snapshot_readiness(snapshot, before=ny_date(hypothesis.event.published_at))
    legs, blockers = {}, []
    for leg in hypothesis.legs:
        _, series_id = binding(leg.observable_id)
        entry = report["series"].get(series_id)
        horizon = entry["horizons"][str(leg.horizon)] if entry else None
        legs[leg.id] = {"observable_id": leg.observable_id, "horizon": leg.horizon,
                        "event_anchor": entry.get("event_anchor") if entry else None,
                        "history_sessions": entry["history_sessions"] if entry else 0,
                        "reference_windows": horizon["reference_windows"] if horizon else 0,
                        "required_reference_windows": horizon["required_reference_windows"] if horizon else None,
                        "scorable": bool(horizon and horizon["scorable"]),
                        "placebo": horizon.get("placebo") if horizon else None}
        if not legs[leg.id]["scorable"]:
            blockers.append(f"The baseline's history is insufficient for {leg.observable_id} at horizon {leg.horizon}.")
    return {"rules_version": report["rules_version"], "rules_hash": report["rules_hash"], "legs": legs}, blockers


def preview(inputs: dict, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    """What one approval would freeze, and whether it can. Writes nothing and contacts nothing."""
    inputs = parse_inputs(inputs)
    moment = utc(clock())
    draft, origin = effective(inputs, folders, lambda: moment)
    try:
        hypothesis = Hypothesis.model_validate_json(json.dumps({**draft, "frozen_at": moment.isoformat()}), strict=True)
    except ValidationError as exc:
        raise LifecycleRefused(422, f"The hypothesis is invalid: {errors(exc)}") from None
    try:
        provider = bound_provider(hypothesis)
    except ValueError as exc:
        raise LifecycleRefused(422, str(exc)) from None
    if provider != BOARD_H15:
        raise LifecycleRefused(422, "This workflow freezes hypotheses on the Board's H.15 observables only")
    blockers, freshness, readiness, baseline = [], None, None, None
    state = store_state(folders)
    if not state["exists"] or state["schema"] not in (2, 3, 4):
        raise LifecycleRefused(409, state["detail"])
    if state["schema"] not in (3, 4):
        blockers.append(state["detail"])
    connection = _reader(folders)
    try:
        try:
            snapshot = load_snapshot(connection, inputs["baseline_snapshot_id"])
        except ValueError:
            raise LifecycleRefused(404, "No such baseline snapshot in this store") from None
        baseline = baseline_summary(snapshot)
        if snapshot.provider != provider:
            raise LifecycleRefused(422, f"The baseline comes from {snapshot.provider}, but the legs are bound to "
                                        f"{provider}; a leg is never measured on another provider's data")
        if snapshot.retrieved_at > moment:
            blockers.append("The baseline was received after this moment; it cannot have been held before a freeze.")
        try:
            freshness = check_freshness(connection, snapshot.id, hypothesis)
        except ValueError as exc:
            freshness = {"policy": FRESHNESS_POLICY, "covered": False, "problem": str(exc)}
            blockers.append(str(exc))
        readiness, insufficient = _readiness(snapshot, hypothesis)
        blockers += insufficient
        same = connection.execute("SELECT id, recorded_at FROM hypotheses WHERE request_hash=?",
                                  (request_identity(hypothesis),)).fetchone()
        if same is not None:
            blockers.append(f"This request (the same event, engine, evidence class and usage) is already frozen as "
                            f"{same[0]} at {same[1]}.")
    finally:
        connection.close()
    freeze_date = ny_date(moment)
    bound = {"lifecycle_version": LIFECYCLE_VERSION, "freeze_policy": FRESHNESS_POLICY,
             "effective_hypothesis": draft, "origin": origin, "baseline_snapshot_id": inputs["baseline_snapshot_id"],
             "source_bindings": {leg.observable_id: resolve(leg.observable_id).source for leg in hypothesis.legs},
             "freeze_date_new_york": freeze_date.isoformat()}
    return {"lifecycle_version": LIFECYCLE_VERSION, "preview_sha256": digest(bound), "binding": bound,
            "effective_sha256": digest(draft), "freezable": not blockers, "blockers": blockers,
            "previewed_at": moment.isoformat(), "baseline": baseline, "freshness": freshness, "readiness": readiness,
            "policy_note": POLICY_NOTE, "scoring": scoring_window(hypothesis, freeze_date),
            "measurement_convention": DAILY_CONVENTION_NOTE, "classification": CLASSIFICATION,
            "limitations": list(LIMITATIONS), "freeze_time": "Stamped by the server when the approval is received.",
            "provider_called": False, "written": False}


def _changed(previewed: object, current: dict) -> list[str]:
    if not isinstance(previewed, dict):
        return []
    labels = {"effective_hypothesis": "the hypothesis", "origin": "its origin or review",
              "baseline_snapshot_id": "the baseline", "source_bindings": "the source bindings",
              "freeze_policy": "the freeze policy", "freeze_date_new_york": "the New York freeze date",
              "lifecycle_version": "the workflow version"}
    return [label for key, label in labels.items() if previewed.get(key) != current.get(key)]


def action_state(action_id: str, folders: Folders) -> dict:
    """Whether an approval froze a hypothesis: the read-only check after a lost reply. Never sends anything again."""
    if not SHA.fullmatch(action_id or ""):
        raise LifecycleRefused(404, "Unknown freeze action")
    base = {"lifecycle_version": LIFECYCLE_VERSION, "action_id": action_id, "written": False}
    if not folders.store.is_file():
        return {**base, "state": "not_recorded", "detail": "No store exists, so nothing was frozen."}
    connection = _reader(folders)
    try:
        row = connection.execute("SELECT hypothesis_id, recorded_at FROM freeze_actions WHERE action_id=?",
                                 (action_id,)).fetchone() if store_schema(connection) in (3, 4) else None
    finally:
        connection.close()
    if row is None:
        return {**base, "state": "not_recorded",
                "detail": "No freeze is recorded for this approval. Nothing was frozen by it; preview again to decide."}
    return {**base, "state": "frozen", "hypothesis_id": row[0], "recorded_at": row[1], "status": FROZEN_NOT_EVALUATED,
            "detail": "This approval froze the hypothesis below. It is never frozen or stamped again."}


def freeze(body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    """One explicit approval of one preview. Repeating it returns the original freeze."""
    payload = strict_body(body, ("inputs", "preview_sha256", "approve_freeze", "previewed_binding"), "approval")
    if payload["approve_freeze"] is not True:
        raise LifecycleRefused(422, "approve_freeze must be true: a freeze needs an explicit approval")
    action_id = payload["preview_sha256"]
    if not isinstance(action_id, str) or not SHA.fullmatch(action_id):
        raise LifecycleRefused(422, "preview_sha256 must be the SHA-256 of the preview being approved")
    done = action_state(action_id, folders)
    if done["state"] == "frozen":
        return {**done, "created": False}
    moment = utc(clock())
    current = preview(payload["inputs"], folders, lambda: moment)
    if current["preview_sha256"] != action_id:
        changed = _changed(payload["previewed_binding"], current["binding"])
        raise LifecycleRefused(409, "The preview has changed since it was approved" +
                               (f" ({', '.join(changed)})" if changed else "") +
                               ". Nothing was frozen; review the new preview and approve it if it is right.",
                               {"preview": current})
    if not current["freezable"]:
        done = action_state(action_id, folders)  # Another tab or worker may have just made this same freeze.
        if done["state"] == "frozen":
            return {**done, "created": False}
        raise LifecycleRefused(409, "Nothing was frozen: " + " ".join(current["blockers"]), {"preview": current})
    hypothesis = Hypothesis.model_validate_json(json.dumps({**current["binding"]["effective_hypothesis"],
                                                            "frozen_at": moment.isoformat()}), strict=True)
    action = {"lifecycle_version": LIFECYCLE_VERSION, "action_id": action_id, "binding": current["binding"],
              "effective_sha256": current["effective_sha256"], "freshness": current["freshness"],
              "readiness": current["readiness"], "scoring": current["scoring"],
              "approval": {"approve_freeze": True, "attributed_to": "local interface user",
                           "received_at": moment.isoformat()}}
    try:
        connection = open_store(str(folders.store))
    except ValueError as exc:
        raise LifecycleRefused(409, str(exc)) from None
    try:
        result = freeze_with_action(connection, hypothesis, moment, current["binding"]["baseline_snapshot_id"],
                                    action_id, action)
    except ValueError as exc:
        raise LifecycleRefused(409, f"Nothing was frozen: {exc}") from None
    finally:
        connection.close()
    return {"lifecycle_version": LIFECYCLE_VERSION, "action_id": action_id, "state": "frozen",
            "created": result["created"], "hypothesis_id": result["hypothesis_id"],
            "recorded_at": result["recorded_at"], "status": FROZEN_NOT_EVALUATED, "provider_called": False,
            "evaluated": False, "prepared": False}


# ---------------------------------------------------------------- frozen hypotheses, read only

def _evaluations(connection: sqlite3.Connection, hypothesis_id: str) -> int:
    return connection.execute("SELECT COUNT(*) FROM evaluations WHERE hypothesis_id=?", (hypothesis_id,)).fetchone()[0]


def _status(evaluations: int) -> str:
    return FROZEN_NOT_EVALUATED if evaluations == 0 else f"Frozen · {evaluations} evaluation(s) recorded"


def _action(connection: sqlite3.Connection, hypothesis_id: str) -> dict | None:
    if store_schema(connection) not in (3, 4):
        return None
    row = connection.execute("SELECT payload FROM freeze_actions WHERE hypothesis_id=?", (hypothesis_id,)).fetchone()
    return json.loads(row[0]) if row else None


def hypotheses_listing(folders: Folders) -> dict:
    """Every frozen hypothesis in the store, newest first, with its state. Reads only."""
    state = store_state(folders)
    rows = []
    if state["exists"] and state["schema"] is not None:
        connection = _reader(folders)
        try:
            bound = dict(connection.execute("SELECT hypothesis_id, baseline_snapshot_id FROM freeze_bindings")) \
                if state["schema"] in (2, 3, 4) else {}
            for identity, recorded_at, payload in connection.execute(
                    "SELECT id, recorded_at, payload FROM hypotheses ORDER BY recorded_at DESC, id"):
                hypothesis = json.loads(payload)
                action = _action(connection, identity)
                count = _evaluations(connection, identity)
                rows.append({"hypothesis_id": identity, "headline": hypothesis["event"]["headline"],
                             "published_at": hypothesis["event"]["published_at"], "frozen_at": hypothesis["frozen_at"],
                             "recorded_at": recorded_at, "evidence_class": hypothesis["evidence_class"],
                             "usage": hypothesis["usage"], "engine_provider": hypothesis["engine"]["provider"],
                             "baseline_snapshot_id": bound.get(identity),
                             "origin": action["binding"]["origin"]["kind"] if action else "outside_interface",
                             "evaluations": count, "status": _status(count)})
        finally:
            connection.close()
    return {"lifecycle_version": LIFECYCLE_VERSION, "store": state, "hypotheses": rows,
            "classification": CLASSIFICATION}


def hypothesis_view(hypothesis_id: str, folders: Folders) -> dict:
    """One frozen hypothesis exactly as stored, with its baseline, derivation and state. Reads only."""
    if not SHA.fullmatch(hypothesis_id or ""):
        raise LifecycleRefused(404, "Unknown hypothesis")
    connection = _reader(folders)
    try:
        row = connection.execute("SELECT recorded_at, request_hash, payload FROM hypotheses WHERE id=?",
                                 (hypothesis_id,)).fetchone()
        if row is None:
            raise LifecycleRefused(404, "No such frozen hypothesis in this store")
        stored = json.loads(row[2])
        hypothesis = Hypothesis.model_validate_json(row[2])
        bound = connection.execute("SELECT baseline_snapshot_id, bound_at FROM freeze_bindings WHERE hypothesis_id=?",
                                   (hypothesis_id,)).fetchone() if store_schema(connection) in (2, 3, 4) else None
        baseline = baseline_summary(load_snapshot(connection, bound[0])) if bound else None
        action = _action(connection, hypothesis_id)
        count = _evaluations(connection, hypothesis_id)
    finally:
        connection.close()
    if digest(stored) != hypothesis_id:
        raise LifecycleRefused(500, "The stored hypothesis does not match its ID; it is not shown")
    origin = action["binding"]["origin"] if action else None
    return {"lifecycle_version": LIFECYCLE_VERSION, "hypothesis_id": hypothesis_id, "hypothesis": stored,
            "recorded_at": row[0], "frozen_at": stored["frozen_at"], "bound_at": bound[1] if bound else None,
            "baseline": baseline, "status": _status(count), "evaluations": count,
            "origin": origin or {"kind": "outside_interface",
                                 "note": "Frozen outside this interface (for example by the freeze helper command); "
                                         "its derivation is not recorded here."},
            "effective_sha256": action["effective_sha256"] if action else None,
            "action_id": action["action_id"] if action else None,
            "freshness": action["freshness"] if action else None,
            "scoring": action["scoring"] if action else scoring_window(hypothesis, ny_date(hypothesis.frozen_at)),
            "measurement_convention": DAILY_CONVENTION_NOTE,
            "classification": CLASSIFICATION if stored["usage"] == "showcase" else None,
            "limitations": list(LIMITATIONS) if baseline and baseline["provider"] == BOARD_H15 else [],
            "written": False}
