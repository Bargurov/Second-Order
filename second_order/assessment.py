"""Outcome readiness and one explicit assessment of one frozen hypothesis, from the interface (A3).

Readiness reads only. The expected dates come from the freeze's scoring window on the SIFMA calendar; the dates an
assessment would measure come from the engine's own anchors (evaluation.scored_window) on the series pinned from the
baseline bound at freeze and one outcome snapshot. States are kept apart:
- horizon_not_elapsed: a target date has not ended in New York. A date-only observation counts only after its date
  ends; when the publisher supplies it is not known, and nothing is requested meanwhile.
- outcome_missing: no compatible outcome snapshot covers the dates (from the publication date through each target).
- missing_values: an outcome covers them, but the source states no value for a session a leg needs, or another
  stated reason applies; that leg will be recorded as unavailable. Nothing is filled.
- ready: an outcome covers every leg with values.
- recorded: an assessment is already stored.
A compatible outcome is a snapshot of the hypothesis's own provider that verifies (snapshots.verify_snapshot),
classifies every leg's series from on or before the publication date, and was received after the baseline and before
now. The baseline is never an outcome, and outcome data never fill or replace baseline history (pinned_series). A
FRED-bound hypothesis is measured only on local FRED snapshots: nothing here fetches FRED data or substitutes H.15.

An outcome snapshot is imported explicitly from a kept, accepted release package (package_snapshots), from the
hypothesis's publication date; an existing snapshot of that package that already serves is reused, and repeating an
import reuses its snapshot.

Preview writes and evaluates nothing. It binds the hypothesis (its ID is the SHA-256 of the stored record), the
baseline and the outcome, the active rules and their hash (the freeze record pins no rules, and the preview says so),
the cutoff, each leg's dates, state and gaps, the assessments already recorded, and whether this is a reassessment.
The cutoff is set by the server from those inputs alone (CUTOFF_RULE), so a preview has no time-based expiry: normal
elapsed seconds change nothing, while any change in what it binds changes its SHA-256. It shows what will be assessed,
not the result: the verdict and measured moves are computed only when an approval is recorded, so a result cannot be
previewed and then left unrecorded.

Assessment is one explicit approval of one preview ("Evaluate and prepare Dossier"). The server recomputes the preview
and refuses any difference with the new preview; it evaluates only the selected hypothesis on the bound inputs, and
store.record_assessment writes the evaluation and its action in one transaction (repeats return the original; a
changed set of recorded assessments refuses). Then that one assessment's Dossier is prepared (assessment_records); if
that fails, the evaluation stays saved and the reply says "Evaluation saved; Dossier not prepared". A lost reply is
resolved by reading the action's outcome, never by sending again.

Everything assessed here is a prospective showcase: no success rates, research denominators or claims of validated
forecasting performance.
"""
from dataclasses import asdict
from datetime import date, datetime
import json
import sqlite3
from typing import Callable

from . import market_store
from .anchors import DataPending, DataUnavailable
from .assessment_records import (DOSSIER_VERSION, PreparationFailed, dossier_path, dossier_state, prepare_dossier,
                                 recorded_assessments)
from .data import daily_observation_time, ny_date
from .evaluation import DAILY_CONVENTION_NOTE, scored_window
from .freeze_origins import Folders, LifecycleRefused
from .lifecycle import (CLASSIFICATION, LIMITATIONS, SHA, _reader, baseline_summary, hypotheses_listing, now,
                        scoring_window, store_state, strict_body)
from .package_snapshots import PackageImportRefused, import_package
from .registry import BOARD_H15, FRED, binding
from .schema import Hypothesis, utc
from .scoring import Rules
from .snapshots import Snapshot, evaluate_bound, load_snapshot, pinned_series, verify_snapshot
from .store import digest, open_store, record_assessment, store_schema

ASSESSMENT_VERSION = "lifecycle-assessment-0.1"
INPUT_FIELDS = ("hypothesis_id", "outcome_snapshot_id")
CUTOFF_RULE = ("The assessment cutoff is set by the server from the inputs, never by a client: the latest of the outcome "
               "snapshot's receipt time, the freeze time and the end (23:59:59, America/New_York) of each leg's target "
               "date in the outcome data. A date-only observation counts only once its New York date has ended. The "
               "cutoff does not move with the time an approval arrives, and it is never later than the server's clock "
               "when the assessment is recorded.")
STATE_LABELS = {
    "horizon_not_elapsed": "Horizon not elapsed",
    "outcome_missing": "Outcome data missing",
    "outcome_held": "Outcome data held",
    "outcome_in_package": "Outcome data in a kept package · import it",
    "missing_values": "Outcome data held · a leg will be unavailable",
    "ready": "Ready for an explicit assessment",
    "recorded": "Assessment recorded",
}
SHOWCASE = ("Prospective showcase under the daily date convention: excluded from research summaries, rates and "
            "denominators. Observations are dated, not timed, so they do not meet the research timestamp gate. No "
            "success rate or claim of validated forecasting performance is made.")
EVALUATION_NOTE = ("This preview shows what will be assessed, not its result. The verdict and measured moves are "
                   "computed only when an approval is recorded, so a result is never seen before it is kept.")
FRED_OUTCOME = ("This hypothesis is bound to FRED's series. Only local FRED snapshots can serve as its outcome: nothing "
                "here fetches FRED data, and the Board's H.15 data are never substituted for FRED-bound legs. A FRED "
                "snapshot is stored only by the `market import` command, outside this interface.")


def _classification(stored: dict, provider: str) -> str | None:
    if stored["usage"] != "showcase":
        return None
    return CLASSIFICATION if provider == BOARD_H15 else SHOWCASE


# ---------------------------------------------------------------- reading a frozen hypothesis

def _frozen(connection: sqlite3.Connection, hypothesis_id: object) -> tuple[Hypothesis, dict, str, str]:
    """The stored hypothesis, verified against its ID, its stored record, its baseline and its request identity."""
    if not isinstance(hypothesis_id, str) or not SHA.fullmatch(hypothesis_id):
        raise LifecycleRefused(404, "Unknown hypothesis")
    row = connection.execute("SELECT payload, request_hash FROM hypotheses WHERE id=?", (hypothesis_id,)).fetchone()
    if row is None:
        raise LifecycleRefused(404, "No such frozen hypothesis in this store")
    stored = json.loads(row[0])
    if digest(stored) != hypothesis_id:
        raise LifecycleRefused(500, "The stored hypothesis does not match its ID; it is not used")
    bound = connection.execute("SELECT baseline_snapshot_id FROM freeze_bindings WHERE hypothesis_id=?",
                               (hypothesis_id,)).fetchone() if store_schema(connection) in (2, 3, 4) else None
    if bound is None:
        raise LifecycleRefused(409, "This hypothesis has no baseline snapshot bound at freeze; it is not assessed here")
    return Hypothesis.model_validate_json(row[0]), stored, bound[0], row[1]


def _freeze_action(connection: sqlite3.Connection, hypothesis_id: str) -> dict | None:
    if store_schema(connection) not in (3, 4):
        return None
    row = connection.execute("SELECT payload FROM freeze_actions WHERE hypothesis_id=?", (hypothesis_id,)).fetchone()
    return json.loads(row[0]) if row else None


def expected(hypothesis: Hypothesis, moment: datetime) -> dict:
    """The expected scoring window (SIFMA calendar, from the New York freeze date) and whether its last target date
    has ended in New York. Expected, not measured."""
    window = scoring_window(hypothesis, ny_date(hypothesis.frozen_at))
    targets = [leg["expected_target"] for leg in window["legs"].values()]
    latest = date.fromisoformat(max(targets)) if all(targets) else None
    counts_after = daily_observation_time(latest) if latest else None
    return {**window, "latest_expected_target": latest.isoformat() if latest else None,
            "counts_after": counts_after.isoformat() if counts_after else None,
            "elapsed": bool(counts_after and moment >= counts_after)}


def _day(series, index: int) -> str:
    return ny_date(series.observations[index].at).isoformat()


def leg_readiness(hypothesis: Hypothesis, leg, baseline: Snapshot, outcome: Snapshot, moment: datetime) -> dict:
    """What an assessment would measure for one leg on these snapshots: dates, state and gaps. Values are not read,
    except whether the source states one."""
    series_id = binding(leg.observable_id)[1]
    series = pinned_series(leg.observable_id, series_id, baseline, outcome, ny_date(hypothesis.event.published_at))
    entry = {"leg_id": leg.id, "observable_id": leg.observable_id, "series_id": series_id, "primary": leg.primary,
             "horizon": leg.horizon, "event_anchor": None, "score_anchor": None, "target": None,
             "target_counts_after": None, "gaps": [], "detail": None}
    try:
        anchor, target = scored_window(hypothesis, leg, series)
    except DataPending as exc:
        return {**entry, "state": "outcome_missing", "detail": f"{exc}."}
    except DataUnavailable as exc:
        return {**entry, "state": "missing_values", "detail": f"This leg will be unavailable: {exc}."}
    entry.update(event_anchor=_day(series, anchor.event_index), score_anchor=_day(series, anchor.score_index))
    if hypothesis.usage == "research" and series.timestamp_basis != "observed":
        return {**entry, "state": "missing_values",
                "detail": "This leg will be unavailable: research requires verified observation timestamps."}
    if target >= len(series.observations):
        through = _day(series, len(series.observations) - 1)
        return {**entry, "state": "outcome_missing",
                "detail": f"The outcome data end on {through}; the target, {leg.horizon} observation(s) after the "
                          "scoring anchor, is not in them yet."}
    target_at = series.observations[target].at
    entry.update(target=_day(series, target), target_counts_after=target_at.isoformat())
    if target_at > moment:
        return {**entry, "state": "horizon_not_elapsed",
                "detail": f"The target date {entry['target']} has not ended in New York yet."}
    statuses = {day.isoformat(): status for day, _, status in outcome.classified[series_id]}
    gaps = [{"date": _day(series, i), "status": statuses.get(_day(series, i), "not_listed")}
            for i in range(anchor.score_index, target + 1) if series.observations[i].value is None]
    if gaps:
        return {**entry, "state": "missing_values", "gaps": gaps,
                "detail": (f"The source states no value for {len(gaps)} session(s) in this leg's window; the leg will "
                           "be unavailable. Nothing is filled.")}
    return {**entry, "state": "ready"}


def combine(legs: list[dict]) -> str:
    states = {leg["state"] for leg in legs}
    for state in ("horizon_not_elapsed", "outcome_missing", "missing_values"):
        if state in states:
            return state
    return "ready"


def outcome_problems(hypothesis: Hypothesis, baseline: Snapshot, outcome: Snapshot, moment: datetime) -> list[str]:
    """Why a verified snapshot cannot serve as this hypothesis's outcome (empty when it can)."""
    if outcome.provider != baseline.provider:
        return [f"It comes from {outcome.provider}, but every leg is bound to {baseline.provider}; a leg is never "
                "measured on another provider's data."]
    problems = []
    if outcome.id == baseline.id:
        problems.append("It is the baseline bound at freeze; outcome data come from another snapshot.")
    if outcome.retrieved_at < baseline.retrieved_at:
        problems.append("It was received before the baseline.")
    if outcome.retrieved_at > moment:
        problems.append("It was received after this moment.")
    published = ny_date(hypothesis.event.published_at)
    for leg in hypothesis.legs:
        series_id = binding(leg.observable_id)[1]
        if series_id not in outcome.classified:
            problems.append(f"It does not contain {series_id}.")
        elif outcome.classified_from(series_id) > published:
            problems.append(f"It classifies {series_id} only from {outcome.classified_from(series_id).isoformat()}, "
                            f"after the publication date {published.isoformat()}; the sessions between would be "
                            "invisible.")
    return list(dict.fromkeys(problems))


def candidate(connection: sqlite3.Connection, hypothesis: Hypothesis, baseline: Snapshot, snapshot_id: str,
              moment: datetime) -> dict:
    try:
        outcome = verify_snapshot(connection, snapshot_id)
    except ValueError as exc:
        return {"snapshot_id": snapshot_id, "summary": None, "usable": False, "state": None, "legs": [],
                "problems": [f"It does not verify: {exc}. It is never used."]}
    problems = outcome_problems(hypothesis, baseline, outcome, moment)
    legs = [] if problems else [leg_readiness(hypothesis, leg, baseline, outcome, moment) for leg in hypothesis.legs]
    return {"snapshot_id": snapshot_id, "summary": baseline_summary(outcome), "usable": not problems,
            "state": combine(legs) if legs else None, "legs": legs, "problems": problems}


def candidates(connection: sqlite3.Connection, hypothesis: Hypothesis, baseline: Snapshot, moment: datetime) -> list:
    """Every other snapshot of the baseline's provider, oldest receipt first, with what it would allow."""
    ids = [row[0] for row in connection.execute("SELECT id FROM market_snapshots WHERE provider=? AND id<>? ORDER BY "
                                                "retrieved_at, id", (baseline.provider, baseline.id))]
    return [candidate(connection, hypothesis, baseline, snapshot_id, moment) for snapshot_id in ids]


def outcome_packages(folders: Folders, hypothesis: Hypothesis, baseline: Snapshot, latest: str | None,
                     found: list[dict]) -> tuple[list[dict], list[dict]]:
    """Kept H.15 release packages that could be imported as this hypothesis's outcome, and the problems of those
    that do not verify. Reads only."""
    _, problems, packages = market_store.local_data(folders.market, None)
    published = ny_date(hypothesis.event.published_at)
    serving = {item["summary"]["package"]["package_id"]: item["snapshot_id"] for item in found
               if item["usable"] and (item["summary"] or {}).get("package")}
    rows = []
    for package in packages:
        reasons, coverage = [], package["coverage"]
        if package["status"] != "accepted":
            reasons.append(f"Its status is {package['status']}; only an accepted package is used.")
        elif datetime.fromisoformat(package["received_at"]) < baseline.retrieved_at:
            reasons.append("It was received before the baseline.")
        elif date.fromisoformat(coverage["first"]) > published or date.fromisoformat(coverage["last"]) < published:
            reasons.append(f"It states both series from {coverage['first']} to {coverage['last']}, which does not "
                           f"include the publication date {published.isoformat()}.")
        rows.append({"package_id": package["package_id"], "status": package["status"],
                     "received_at": package["received_at"], "coverage": coverage,
                     "covers_expected_targets": bool(coverage and latest and coverage["last"] >= latest),
                     "importable": not reasons and package["package_id"] not in serving,
                     "serving_snapshot": serving.get(package["package_id"]), "reasons": reasons,
                     "start": published.isoformat()})
    return rows, problems


def _state(window: dict, found: list[dict], assessments: list[dict]) -> str:
    if assessments:
        return "recorded"
    if not window["elapsed"]:
        return "horizon_not_elapsed"
    usable = {item["state"] for item in found if item["usable"]}
    for state in ("ready", "missing_values", "horizon_not_elapsed"):
        if state in usable:
            return state
    return "outcome_missing"


def _rules_note(action: dict | None, rules: Rules) -> str:
    active = f"the active rules {rules.version} (SHA-256 {rules.hash})"
    if action is None:
        return (f"The freeze record does not pin scoring rules, and no readiness check under named rules was recorded "
                f"at freeze (it was frozen outside this interface). An assessment applies {active} and records them.")
    at_freeze = action["readiness"]
    same = at_freeze["rules_hash"] == rules.hash
    return (f"The freeze record does not pin scoring rules. Its baseline readiness was checked under rules "
            f"{at_freeze['rules_version']} (SHA-256 {at_freeze['rules_hash']}). An assessment applies {active} and "
            f"records them; {'the same configuration' if same else 'a different configuration'}.")


def readiness(hypothesis_id: str, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    """One frozen hypothesis: its expected dates, the outcome snapshots and packages that could serve, and its
    recorded assessments. Reads only: nothing is imported, evaluated, prepared or fetched."""
    moment = utc(clock())
    connection = _reader(folders)
    try:
        hypothesis, stored, baseline_id, _ = _frozen(connection, hypothesis_id)
        try:
            baseline, baseline_problem = verify_snapshot(connection, baseline_id), None
        except ValueError as exc:
            baseline, baseline_problem = None, f"The baseline bound at freeze does not verify: {exc}"
        provider = baseline.provider if baseline else None
        window = expected(hypothesis, moment)
        found = candidates(connection, hypothesis, baseline, moment) if baseline else []
        assessments = recorded_assessments(connection, folders, hypothesis_id)
        action = _freeze_action(connection, hypothesis_id)
        schema = store_schema(connection)
    finally:
        connection.close()
    packages, problems = (outcome_packages(folders, hypothesis, baseline, window["latest_expected_target"], found)
                          if provider == BOARD_H15 else ([], []))
    state = "outcome_missing" if baseline_problem else _state(window, found, assessments)
    return {"assessment_version": ASSESSMENT_VERSION, "hypothesis_id": hypothesis_id,
            "headline": stored["event"]["headline"], "published_at": stored["event"]["published_at"],
            "frozen_at": stored["frozen_at"], "provider": provider, "state": state, "state_label": STATE_LABELS[state],
            "baseline_problem": baseline_problem, "expected": window, "candidates": found, "packages": packages,
            "package_problems": problems, "assessments": assessments, "store_schema": schema,
            "assessable_store": schema == 4, "rules_note": _rules_note(action, Rules()),
            "fred_note": FRED_OUTCOME if provider == FRED else None,
            "default_selection": ("None: an outcome snapshot is chosen explicitly. Assessments are listed by record "
                                  "time; none is selected for its result."),
            "classification": _classification(stored, provider), "measurement_convention": DAILY_CONVENTION_NOTE,
            "written": False, "provider_called": False}


# ---------------------------------------------------------------- explicit outcome import

def import_outcome(body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    """Import a kept, accepted release package as one hypothesis's outcome, from its publication date. Local only."""
    payload = strict_body(body, ("hypothesis_id", "package_id"), "outcome import")
    if not isinstance(payload["package_id"], str):
        raise LifecycleRefused(422, "package_id must be text")
    moment = utc(clock())
    connection = _reader(folders)
    try:
        hypothesis, _, baseline_id, _ = _frozen(connection, payload["hypothesis_id"])
        try:
            baseline = verify_snapshot(connection, baseline_id)
        except ValueError as exc:
            raise LifecycleRefused(409, f"The baseline bound at freeze does not verify: {exc}") from None
        if baseline.provider != BOARD_H15:
            raise LifecycleRefused(409, FRED_OUTCOME)
        found = candidates(connection, hypothesis, baseline, moment)
    finally:
        connection.close()
    serving = next((item for item in found if item["usable"] and
                    (item["summary"]["package"] or {}).get("package_id") == payload["package_id"]), None)
    if serving is not None:
        return {"assessment_version": ASSESSMENT_VERSION, "created": False, "reused": True,
                "snapshot": serving["summary"], "usable": True, "problems": [], "provider_called": False}
    rows, problems = outcome_packages(folders, hypothesis, baseline, None, found)
    package = next((row for row in rows if row["package_id"] == payload["package_id"]), None)
    if package is None:
        problem = next((item["problem"] for item in problems if item["retrieval"] == f"package:{payload['package_id']}"),
                       None)
        if problem:
            raise LifecycleRefused(409, f"This package does not verify, so it is never used: {problem}")
        raise LifecycleRefused(404, "No kept package has this ID")
    if package["reasons"]:
        raise LifecycleRefused(409, "This package cannot serve as this hypothesis's outcome: " +
                               " ".join(package["reasons"]))
    try:
        writer = open_store(str(folders.store))
    except ValueError as exc:
        raise LifecycleRefused(409, str(exc)) from None
    try:
        stored = import_package(writer, payload["package_id"], ny_date(hypothesis.event.published_at), folders.market,
                                clock)
        result = candidate(writer, hypothesis, baseline, stored["snapshot_id"], moment)
    except PackageImportRefused as exc:
        raise LifecycleRefused(409, str(exc)) from None
    finally:
        writer.close()
    return {"assessment_version": ASSESSMENT_VERSION, "created": stored["created"], "reused": not stored["created"],
            "snapshot": result["summary"], "usable": result["usable"], "problems": result["problems"],
            "provider_called": False}


# ---------------------------------------------------------------- preview and assessment

def parse_inputs(payload: object) -> dict:
    if not isinstance(payload, dict) or set(payload) != set(INPUT_FIELDS) or \
            not all(isinstance(payload[key], str) and SHA.fullmatch(payload[key]) for key in INPUT_FIELDS):
        raise LifecycleRefused(422, "An assessment names exactly a hypothesis_id and an outcome_snapshot_id")
    return payload


def preview(inputs: dict, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    """What one approval would assess and record. Writes nothing, evaluates nothing and contacts nothing."""
    inputs = parse_inputs(inputs)
    moment = utc(clock())
    if not store_state(folders)["exists"]:
        raise LifecycleRefused(409, "No store exists yet")
    connection = _reader(folders)
    try:
        hypothesis, stored, baseline_id, request_hash = _frozen(connection, inputs["hypothesis_id"])
        try:
            baseline = verify_snapshot(connection, baseline_id)
        except ValueError as exc:
            raise LifecycleRefused(409, f"The baseline bound at freeze does not verify: {exc}") from None
        try:
            outcome = verify_snapshot(connection, inputs["outcome_snapshot_id"])
        except ValueError as exc:
            if str(exc).startswith("No market snapshot"):
                raise LifecycleRefused(404, "No such outcome snapshot in this store") from None
            raise LifecycleRefused(409, f"The outcome snapshot does not verify: {exc}. It is never used") from None
        if outcome.provider != baseline.provider:
            raise LifecycleRefused(422, outcome_problems(hypothesis, baseline, outcome, moment)[0])
        problems = outcome_problems(hypothesis, baseline, outcome, moment)
        legs = [] if problems else [leg_readiness(hypothesis, leg, baseline, outcome, moment) for leg in hypothesis.legs]
        prior = recorded_assessments(connection, folders, inputs["hypothesis_id"])
        action = _freeze_action(connection, inputs["hypothesis_id"])
        schema = store_schema(connection)
    finally:
        connection.close()
    window = expected(hypothesis, moment)
    rules = Rules()
    state = combine(legs) if legs else "outcome_missing"
    if not window["elapsed"] and state in ("outcome_missing", "horizon_not_elapsed"):
        state = "horizon_not_elapsed"
    blockers = list(problems)
    cutoff = None
    if state in ("ready", "missing_values"):
        cutoff = utc(max([outcome.retrieved_at, hypothesis.effective_freeze] +
                         [datetime.fromisoformat(leg["target_counts_after"]) for leg in legs]))
        if cutoff > moment:
            blockers.append("The cutoff these inputs set has not been reached yet.")
    elif not problems:
        details = [leg["detail"] for leg in legs if leg["state"] == state and leg["detail"]]
        if state == "horizon_not_elapsed" and not window["elapsed"]:
            details.append(f"The latest expected target date is {window['latest_expected_target']}; its observation "
                           f"counts only after that New York date ends ({window['counts_after']}), and when the "
                           "publisher supplies it is not known.")
        blockers.append(f"{STATE_LABELS[state]}. " + " ".join(dict.fromkeys(details)))
    same = [row for row in prior if cutoff and (row["outcome_snapshot_id"], row["rules_hash"], row["as_of"]) ==
            (outcome.id, rules.hash, cutoff.isoformat())]
    if same:
        state = "recorded"
        blockers.append(f"This assessment is already recorded as {same[0]['evaluation_id']} (at "
                        f"{same[0]['recorded_at']}); open it instead. Repeating it would record nothing new.")
    if schema != 4:
        blockers.append(f"This store uses schema {schema}. Assessments need schema 4 (an added assessment-action "
                        "table); upgrading is an explicit action that only adds tables.")
    bound = {"assessment_version": ASSESSMENT_VERSION, "hypothesis_id": inputs["hypothesis_id"],
             "hypothesis_sha256": digest(stored), "request_identity": request_hash, "provider": baseline.provider,
             "baseline_snapshot_id": baseline.id, "outcome_snapshot_id": outcome.id, "rules": asdict(rules),
             "rules_hash": rules.hash, "cutoff": cutoff.isoformat() if cutoff else None, "cutoff_rule": CUTOFF_RULE,
             "state": state, "legs": [{key: leg[key] for key in ("leg_id", "state", "event_anchor", "score_anchor",
                                                                  "target", "gaps")} for leg in legs],
             "prior_assessments": sorted(row["evaluation_id"] for row in prior), "reassessment": bool(prior),
             "dossier": {"dossier_version": DOSSIER_VERSION}}
    path = dossier_path(folders, inputs["hypothesis_id"], "<evaluation id>")
    return {"assessment_version": ASSESSMENT_VERSION, "preview_sha256": digest(bound), "binding": bound,
            "assessable": not blockers, "blockers": blockers, "state": state, "state_label": STATE_LABELS[state],
            "previewed_at": moment.isoformat(),
            "hypothesis": {"hypothesis_id": inputs["hypothesis_id"], "headline": stored["event"]["headline"],
                           "published_at": stored["event"]["published_at"], "frozen_at": stored["frozen_at"],
                           "evidence_class": stored["evidence_class"], "usage": stored["usage"],
                           "effective_sha256": action["effective_sha256"] if action else None,
                           "origin": action["binding"]["origin"]["kind"] if action else "outside_interface"},
            "baseline": baseline_summary(baseline), "outcome": baseline_summary(outcome), "outcome_problems": problems,
            "legs": legs, "expected": window,
            "rules": {"version": rules.version, "hash": rules.hash, "configuration": asdict(rules),
                      "note": _rules_note(action, rules)},
            "cutoff": {"at": cutoff.isoformat() if cutoff else None, "rule": CUTOFF_RULE},
            "prior_assessments": prior,
            "creates": [f"One evaluation in the store's append-only evaluations table, for hypothesis "
                        f"{inputs['hypothesis_id'][:12]} only.",
                        "One assessment-action record binding this approval to that evaluation, in the same "
                        "transaction.",
                        f"One prepared Dossier file, {folders.dossiers.name}/{path.parent.name}/<evaluation ID>.json, "
                        "created once and never rewritten."],
            "evaluation_note": EVALUATION_NOTE, "classification": _classification(stored, baseline.provider),
            "limitations": list(LIMITATIONS) if baseline.provider == BOARD_H15 else [],
            "measurement_convention": DAILY_CONVENTION_NOTE, "provider_called": False, "written": False,
            "evaluated": False}


def _changed(previewed: object, current: dict) -> list[str]:
    if not isinstance(previewed, dict):
        return []
    labels = {"outcome_snapshot_id": "the outcome snapshot", "baseline_snapshot_id": "the baseline",
              "rules_hash": "the rules", "cutoff": "the cutoff", "state": "the readiness", "legs": "the leg dates or gaps",
              "prior_assessments": "the recorded assessments", "hypothesis_sha256": "the hypothesis",
              "assessment_version": "the workflow version"}
    return [label for key, label in labels.items() if previewed.get(key) != current.get(key)]


def action_state(action_id: str, folders: Folders) -> dict:
    """Whether an approval recorded an assessment: the read-only check after a lost reply. Never sends again."""
    if not isinstance(action_id, str) or not SHA.fullmatch(action_id):
        raise LifecycleRefused(404, "Unknown assessment action")
    base = {"assessment_version": ASSESSMENT_VERSION, "action_id": action_id, "written": False}
    if not folders.store.is_file():
        return {**base, "state": "not_recorded", "detail": "No store exists, so nothing was recorded."}
    connection = _reader(folders)
    try:
        row = connection.execute("SELECT hypothesis_id, evaluation_id, recorded_at FROM assessment_actions WHERE "
                                 "action_id=?", (action_id,)).fetchone() if store_schema(connection) == 4 else None
    finally:
        connection.close()
    if row is None:
        return {**base, "state": "not_recorded",
                "detail": "No assessment is recorded for this approval; nothing was recorded by it. Preview again to "
                          "decide."}
    return {**base, "state": "recorded", "hypothesis_id": row[0], "evaluation_id": row[1], "recorded_at": row[2],
            "dossier": dossier_state(folders, row[0], row[1]),
            "detail": "This approval recorded the assessment below. It is never recorded again."}


def assess(body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    """Evaluate and prepare Dossier: one explicit approval of one preview. Repeating it returns the original."""
    payload = strict_body(body, ("inputs", "preview_sha256", "approve_assessment", "reassessment",
                                 "previewed_binding"), "approval")
    if payload["approve_assessment"] is not True:
        raise LifecycleRefused(422, "approve_assessment must be true: an assessment needs an explicit approval")
    if type(payload["reassessment"]) is not bool:
        raise LifecycleRefused(422, "reassessment must be true or false")
    action_id = payload["preview_sha256"]
    if not isinstance(action_id, str) or not SHA.fullmatch(action_id):
        raise LifecycleRefused(422, "preview_sha256 must be the SHA-256 of the preview being approved")
    done = action_state(action_id, folders)
    if done["state"] == "recorded":
        return _reply(done, created=False)
    moment = utc(clock())
    current = preview(payload["inputs"], folders, lambda: moment)
    if current["preview_sha256"] != action_id:
        done = action_state(action_id, folders)  # Another tab or worker may have just recorded this same approval.
        if done["state"] == "recorded":
            return _reply(done, created=False)
        changed = _changed(payload["previewed_binding"], current["binding"])
        raise LifecycleRefused(409, "The preview has changed since it was approved" +
                               (f" ({', '.join(changed)})" if changed else "") +
                               ". Nothing was evaluated or recorded; review the new preview and approve it if it is "
                               "right.", {"preview": current})
    bound = current["binding"]
    if payload["reassessment"] != bound["reassessment"]:
        raise LifecycleRefused(422, "This hypothesis already has recorded assessments; a further one must be approved "
                                    "as a reassessment" if bound["reassessment"] else
                               "There is no earlier assessment to reassess", {"preview": current})
    if not current["assessable"]:
        done = action_state(action_id, folders)  # Another tab or worker may have just recorded this same approval.
        if done["state"] == "recorded":
            return _reply(done, created=False)
        raise LifecycleRefused(409, "Nothing was evaluated or recorded: " + " ".join(current["blockers"]),
                               {"preview": current})
    connection = _reader(folders)
    try:
        result = evaluate_bound(connection, bound["hypothesis_id"], bound["outcome_snapshot_id"],
                                datetime.fromisoformat(bound["cutoff"]), Rules(**bound["rules"]))
    except ValueError as exc:
        raise LifecycleRefused(409, f"Nothing was recorded: the assessment could not be computed ({exc})") from None
    finally:
        connection.close()
    measured = {leg["leg_id"]: tuple(ny_date(datetime.fromisoformat(leg[key])).isoformat() if leg.get(key) else None
                                     for key in ("score_anchor", "target_at")) for leg in result["legs"]}
    if any(leg["verdict"] == "pending" for leg in result["legs"]) or             any(measured[leg["leg_id"]] != (leg["score_anchor"], leg["target"]) for leg in bound["legs"]):
        raise LifecycleRefused(409, "Nothing was recorded: the computed assessment does not match the previewed dates")
    action = {"assessment_version": ASSESSMENT_VERSION, "action_id": action_id, "binding": bound,
              "approval": {"approve_assessment": True, "reassessment": payload["reassessment"],
                           "attributed_to": "local interface user", "received_at": moment.isoformat()}}
    try:
        writer = open_store(str(folders.store))
    except ValueError as exc:
        raise LifecycleRefused(409, str(exc)) from None
    try:
        recorded = record_assessment(writer, bound["hypothesis_id"], result, moment, action_id, action,
                                     bound["prior_assessments"])
    except ValueError as exc:
        raise LifecycleRefused(409, f"Nothing was recorded: {exc}") from None
    finally:
        writer.close()
    state = {"state": "recorded", "action_id": action_id, "hypothesis_id": bound["hypothesis_id"],
             "evaluation_id": recorded["evaluation_id"], "recorded_at": recorded["recorded_at"]}
    if not recorded["created"]:  # Another request recorded this approval first; its preparation is its own.
        return _reply({**state, "dossier": dossier_state(folders, bound["hypothesis_id"], recorded["evaluation_id"])},
                      created=False)
    try:
        prepared = prepare_dossier(folders, bound["hypothesis_id"], recorded["evaluation_id"], clock)
        dossier = {"state": "prepared", "detail": None, "prepared_at": prepared["prepared_at"], "file": prepared["file"]}
    except (PreparationFailed, LifecycleRefused, OSError, sqlite3.Error) as exc:
        dossier = {"state": "not_prepared", "prepared_at": None, "file": None,
                   "detail": f"Preparation failed ({exc if isinstance(exc, ValueError) else type(exc).__name__}). The "
                             "evaluation is saved; prepare its Dossier explicitly from the assessment's page."}
    return _reply({**state, "dossier": dossier}, created=True)


def _reply(state: dict, created: bool) -> dict:
    prepared = state["dossier"]["state"] == "prepared"
    headline = ("Evaluation saved and Dossier prepared" if prepared else "Evaluation saved; Dossier not prepared") \
        if created else ("Already recorded by this approval" + ("" if prepared else "; Dossier not prepared"))
    return {"assessment_version": ASSESSMENT_VERSION, "state": "recorded", "created": created, "headline": headline,
            "action_id": state["action_id"], "hypothesis_id": state["hypothesis_id"],
            "evaluation_id": state["evaluation_id"], "recorded_at": state["recorded_at"], "dossier": state["dossier"],
            "provider_called": False}


def prepare(body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    """Prepare the Dossier of one stored assessment, explicitly; it records no new assessment."""
    payload = strict_body(body, ("hypothesis_id", "evaluation_id", "approve_preparation"), "preparation")
    if payload["approve_preparation"] is not True:
        raise LifecycleRefused(422, "approve_preparation must be true")
    try:
        prepared = prepare_dossier(folders, payload["hypothesis_id"], payload["evaluation_id"], clock)
    except PreparationFailed as exc:
        raise LifecycleRefused(409, f"The Dossier was not prepared: {exc}") from None
    return {"assessment_version": ASSESSMENT_VERSION, "hypothesis_id": payload["hypothesis_id"],
            "evaluation_id": payload["evaluation_id"], "created": prepared["created"],
            "dossier": {"state": "prepared", "detail": None, "prepared_at": prepared["prepared_at"],
                        "file": prepared["file"]},
            "evaluated": False, "provider_called": False}


def assessment_view(hypothesis_id: str, evaluation_id: str, folders: Folders) -> dict:
    """One recorded assessment exactly as stored, with what its approval bound and its Dossier's state. Reads only."""
    if not isinstance(evaluation_id, str) or not SHA.fullmatch(evaluation_id):
        raise LifecycleRefused(404, "Unknown assessment")
    connection = _reader(folders)
    try:
        _, stored, baseline_id, _ = _frozen(connection, hypothesis_id)
        row = connection.execute("SELECT recorded_at, payload FROM evaluations WHERE id=? AND hypothesis_id=?",
                                 (evaluation_id, hypothesis_id)).fetchone()
        if row is None:
            raise LifecycleRefused(404, "No such assessment of this hypothesis in this store")
        result = json.loads(row[1])
        if digest(result) != evaluation_id:
            raise LifecycleRefused(500, "The stored assessment does not match its ID; it is not shown")
        action = connection.execute("SELECT payload FROM assessment_actions WHERE evaluation_id=?",
                                    (evaluation_id,)).fetchone() if store_schema(connection) == 4 else None
        baseline = load_snapshot(connection, baseline_id)
        outcome_id = (result.get("snapshots") or {}).get("outcome")
        outcome = baseline_summary(load_snapshot(connection, outcome_id)) if outcome_id else None
        listed = recorded_assessments(connection, folders, hypothesis_id)
    finally:
        connection.close()
    # Each leg's recorded anchors as the New York dates they stand for (a stored time is a date's end-of-day
    # placeholder under the daily convention, so its UTC date can be the next day).
    anchor_dates = {leg["leg_id"]: {key: ny_date(datetime.fromisoformat(leg[key])).isoformat()
                                    for key in ("event_anchor", "score_anchor", "target_at") if leg.get(key)}
                    for leg in result["legs"]}
    return {"assessment_version": ASSESSMENT_VERSION, "hypothesis_id": hypothesis_id, "evaluation_id": evaluation_id,
            "headline": stored["event"]["headline"], "published_at": stored["event"]["published_at"],
            "frozen_at": stored["frozen_at"], "recorded_at": row[0], "evaluation": result,
            "anchor_dates": anchor_dates,
            "action": json.loads(action[0]) if action else None,
            "recorded_by": "interface approval" if action else "outside this interface (offline command)",
            "dossier": dossier_state(folders, hypothesis_id, evaluation_id), "baseline": baseline_summary(baseline),
            "outcome": outcome, "position": [item["evaluation_id"] for item in listed].index(evaluation_id) + 1,
            "assessments": len(listed), "classification": _classification(stored, baseline.provider),
            "limitations": list(LIMITATIONS) if baseline.provider == BOARD_H15 else [],
            "measurement_convention": DAILY_CONVENTION_NOTE, "written": False}


# ---------------------------------------------------------------- the journal

def _quick_state(connection: sqlite3.Connection, hypothesis: Hypothesis, baseline_id: str, window: dict,
                 assessments: list[dict], kept: list) -> str:
    """The journal's state from recorded metadata only (the hypothesis page checks readiness in full)."""
    if assessments:
        return "recorded"
    if not window["elapsed"]:
        return "horizon_not_elapsed"
    row = connection.execute("SELECT provider, retrieved_at FROM market_snapshots WHERE id=?", (baseline_id,)).fetchone()
    published = ny_date(hypothesis.event.published_at).isoformat()
    needed = {binding(leg.observable_id)[1] for leg in hypothesis.legs}
    for (payload,) in connection.execute("SELECT payload FROM market_snapshots WHERE provider=? AND id<>? AND "
                                         "retrieved_at>=?", (row[0], baseline_id, row[1])):
        series = json.loads(payload)["series"]
        if all(sid in series and series[sid].get("classified_from", series[sid]["first_date"]) <= published and
               series[sid]["classified_through"] >= window["latest_expected_target"] for sid in needed):
            return "outcome_held"
    if row[0] == BOARD_H15:  # An accepted kept package received after the baseline that states every needed date.
        start = ny_date(hypothesis.event.published_at)
        latest = date.fromisoformat(window["latest_expected_target"])
        if any(retrieval.origin == "package" and retrieval.states(start) and retrieval.states(latest) and
               datetime.fromisoformat(retrieval.provenance["received_at"]) >= datetime.fromisoformat(row[1])
               for retrieval in kept):
            return "outcome_in_package"
    return "outcome_missing"


def journal(folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    """The Hypotheses page's journal: every frozen hypothesis, newest first, with its lifecycle state, origin,
    provider, recorded assessments and their Dossiers. Reads only."""
    moment = utc(clock())
    listing = hypotheses_listing(folders)
    if not listing["hypotheses"]:
        return {**listing, "assessment_version": ASSESSMENT_VERSION}
    kept, _, _ = market_store.local_data(folders.market, None)
    connection = _reader(folders)
    try:
        rows = []
        for row in listing["hypotheses"]:
            extra = {"provider": None, "state": None, "state_label": None, "expected_target": None, "assessments": []}
            if row["baseline_snapshot_id"]:
                hypothesis = Hypothesis.model_validate_json(connection.execute(
                    "SELECT payload FROM hypotheses WHERE id=?", (row["hypothesis_id"],)).fetchone()[0])
                window = expected(hypothesis, moment)
                assessments = recorded_assessments(connection, folders, row["hypothesis_id"])
                state = _quick_state(connection, hypothesis, row["baseline_snapshot_id"], window, assessments, kept)
                provider = connection.execute("SELECT provider FROM market_snapshots WHERE id=?",
                                              (row["baseline_snapshot_id"],)).fetchone()[0]
                extra = {"provider": provider, "state": state, "state_label": STATE_LABELS[state],
                         "expected_target": window["latest_expected_target"], "assessments": assessments}
            rows.append({**row, **extra})
    finally:
        connection.close()
    return {**listing, "hypotheses": rows, "assessment_version": ASSESSMENT_VERSION,
            "order": "Newest freeze first. Each hypothesis's assessments are listed by record time; none is selected "
                     "for its result."}
