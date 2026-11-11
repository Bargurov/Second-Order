"""Treasury findings pilot: one explicit local check, write-once records, and reads (insight-view-0.1).

A check (POST, explicit, local, $0: no provider, model or network) reads the newest accepted kept H.15 package
(insight_evidence), the retained events (insight_events) and evaluates each dated occasion (insight_rules). Nothing
runs automatically: a newer package is used only by the next explicit check.

Records under data/insights/ (private), each created once and never rewritten (market_store.write_exclusive):
- results/<id>.json: one occasion's evaluation. Its ID is the SHA-256 of what it depends on: the result and rules
  versions with the definitions' SHA-256, the occasion's New York date, and the exact observations read (insight_rules.
  inputs plus the discount-rate rows of its window). Which events share the date, their order, the package that
  supplied the observations and every timestamp are not part of it, so they never invalidate a result: unchanged
  inputs reuse it, and only changed observations, a different date or new definitions make a new one. The record keeps
  the package it was first computed from.
- comparisons/<id>.json: the rule checks' frequency on comparison sessions (a recorded seed over a fixed range), keyed
  by the same kind of inputs; separate from results, shown beside them.
- checks/<id>.json: what one check found: the package it read (so a result reused from an earlier package keeps the
  newer package's provenance too), each event with its originating records, date and date basis, and the result each
  occasion maps to. Its ID excludes its timestamp, so repeating an unchanged check writes nothing.
Reads (GET) only read these files and the retained sources; they never extract a package, fetch or write. They
verify what they show: check and comparison records against their IDs, and each result by recomputing its evaluation
and policy context from its own stored inputs (a result that differs is refused, never shown).
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Callable

from . import case_library, event_inbox, event_intake, insight_evidence, insight_events, insight_rules, market_store
from .insight_text import render
from .store import digest

ROOT = Path(__file__).resolve().parent.parent
INSIGHTS_DIR = ROOT / "data" / "insights"
VIEW_VERSION = "insight-view-0.1"
RESULT_VERSION = "insight-result-0.1"
CHECK_VERSION = "insight-check-0.1"
COMPARISON_VERSION = "insight-comparison-0.1"
COMPARISON = {"seed": "insight-comparison-0.1", "size": 200, "first": date(2005, 1, 3), "last": date(2025, 12, 31)}
DISCOUNT = "RIFSRP_F02_N.B"
# The fields a comparison record's ID is the SHA-256 of. Its counts are derived from observations it keeps only as a
# SHA-256, so a read verifies the identity, not the counts.
COMPARISON_IDENTITY = ("version", "definitions_sha256", *COMPARISON, "excluded", "observations_sha256")
SCOPE = ("Retrospective, single-market pilot: daily Treasury yields from the Board's H.15 around retained official "
         "releases. It is not cross-sector discovery, not research evidence and not a measure of forecasting "
         "performance; nothing here enters research summaries.")
LIMITATIONS = (
    "Daily date-only data: a window shows everything that moved yields across its sessions, including other news; it "
    "never isolates a response to one announcement, and the event-date windows include the event date's session.",
    "A breakeven (nominal minus inflation-indexed yield) is not expected inflation: inflation-risk and liquidity "
    "premiums and indexation lags move it too.",
    "Constant-maturity yields are points on the Treasury's fitted curves, republished by the Board (and again by "
    "FRED): one lineage, so series compared here never corroborate each other independently.",
    "The package has no vintage: values are as the Board published them when it was received.",
    "R1 to R4 are exploratory rules designed after inspecting this dataset; ranks and comparison-session counts are "
    "descriptive, not significance tests, chance probabilities or causal evidence.",
)


class InsightRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Folders:
    insights: Path = INSIGHTS_DIR
    market: Path = market_store.STORE_DIR
    inbox: Path = event_inbox.INBOX_DIR
    intake: Path = event_intake.INTAKE_DIR
    library: Path = case_library.LIBRARY_DIR


def now() -> datetime:
    return datetime.now(timezone.utc)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_once(path: Path, record: dict) -> bool:
    """Create the record unless it exists; True when this call created it."""
    if path.exists():
        return False
    try:
        market_store.write_exclusive(path, record)
    except FileExistsError:  # Another check created the same record first; its content is keyed by the same inputs.
        return False
    return True


# ---------------------------------------------------------------- the explicit check

def _discount_rows(evidence: insight_evidence.Evidence, first: str, last: str) -> list[list]:
    return [[day.isoformat(), text] for day, text, _ in evidence.grids[DISCOUNT] if first <= day.isoformat() <= last
            and text not in (None, "ND")]


def _policy_changes(rows: list[list]) -> list[dict]:
    return [{"date": day, "from": previous, "to": text} for (_, previous), (day, text) in zip(rows, rows[1:])
            if previous != text]


def _comparison(grid, excluded: set[date], folders: Folders, package: dict) -> dict:
    first, last = COMPARISON["first"], COMPARISON["last"]
    low, high = first.replace(year=first.year - 2), last + timedelta(days=21)  # Reference history and late windows.
    observed = {series_id: [[day.isoformat(), grid.texts[series_id].get(day)] for day in grid.dates
                            if low <= day <= high] for series_id in insight_rules.YIELDS}
    identity = {"version": COMPARISON_VERSION, "definitions_sha256": insight_rules.DEFINITIONS_SHA256,
                **{key: str(value) for key, value in COMPARISON.items()},
                "excluded": sorted(day.isoformat() for day in excluded),
                "observations_sha256": insight_rules.inputs_sha256(observed)}
    comparison_id = digest(identity)
    path = folders.insights / "comparisons" / f"{comparison_id}.json"
    if not path.exists():
        counts = insight_rules.comparison(grid, excluded, COMPARISON["seed"], COMPARISON["size"], first, last)
        _write_once(path, {**identity, "comparison_id": comparison_id, "counts": counts,
                           "computed_from": package})
    return {"comparison_id": comparison_id}


def check(body: bytes, folders: Folders, clock: Callable[[], datetime] = now, cutoff: date | None = None) -> dict:
    """Evaluate every dated occasion from the newest accepted package. Explicit and local; reuses unchanged work."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        payload = None
    if payload != {"check_retained_evidence": True}:
        raise InsightRefused(422, "A check is requested with exactly {\"check_retained_evidence\": true}")
    folder = insight_evidence.newest_accepted(folders.market)
    if folder is None:
        raise InsightRefused(409, "No accepted H.15 release package is kept, so there is nothing to measure. Retrieving "
                                  "one is a separate, approved action; this check never downloads.")
    try:
        evidence = insight_evidence.extract(folder, cutoff)
    except insight_evidence.EvidenceRefused as exc:
        raise InsightRefused(409, f"The package could not be read as evidence: {exc}") from None
    grid = insight_rules.Grid({series_id: insight_evidence.grid_values(evidence, series_id)
                               for series_id in insight_rules.YIELDS})
    package = {**evidence.package, "extract_version": insight_evidence.EXTRACT_VERSION, "cutoff": evidence.cutoff,
               "last_date": grid.dates[-1].isoformat() if grid.dates else None}
    found = insight_events.events(folders.intake, folders.market, folders.inbox, folders.library)
    grouped = insight_events.occasions(found)
    results, created = {}, 0
    for day, members in sorted(grouped.items()):
        event_date = date.fromisoformat(day)
        observed = insight_rules.inputs(grid, event_date)
        if observed is None:
            points = insight_rules.endpoints(grid, event_date)
            results[day] = {"state": "unavailable", "result_id": None, "problem": points["problem"],
                            "detail": points["detail"]}
            continue
        points = insight_rules.endpoints(grid, event_date)
        span = [grid.dates[points["B6"]].isoformat(), grid.dates[points["A5"]].isoformat()]
        observed[DISCOUNT] = _discount_rows(evidence, *span)
        inputs_sha = insight_rules.inputs_sha256(observed)
        result_id = digest({"result_version": RESULT_VERSION, "definitions_sha256": insight_rules.DEFINITIONS_SHA256,
                            "context_date": day, "inputs_sha256": inputs_sha})
        path = folders.insights / "results" / f"{result_id}.json"
        if not path.exists():
            evaluation = insight_rules.evaluate(grid, event_date)
            created += _write_once(path, {
                "result_version": RESULT_VERSION, "result_id": result_id, "rules_version": insight_rules.RULES_VERSION,
                "definitions_sha256": insight_rules.DEFINITIONS_SHA256, "definitions": insight_rules.DEFINITIONS,
                "context_date": day, "inputs_sha256": inputs_sha, "inputs": observed, "span": span,
                "policy_changes": _policy_changes(observed[DISCOUNT]), "evaluation": evaluation,
                "series": evidence.descriptions, "computed_from": package,
                "computed_at": clock().astimezone(timezone.utc).isoformat()})
        results[day] = {"state": "measured", "result_id": result_id}
    excluded = {date.fromisoformat(day) for day in grouped}
    comparison = _comparison(grid, excluded, folders, package)
    record = {"check_version": CHECK_VERSION, "package": package, "comparison_id": comparison["comparison_id"],
              "definitions_sha256": insight_rules.DEFINITIONS_SHA256,
              "events": [{key: event[key] for key in ("key", "identity", "title", "link", "publisher", "family",
                                                      "family_label", "records", "date", "state", "detail")}
                         for event in found],
              "occasions": results}
    check_id = digest(record)
    written = _write_once(folders.insights / "checks" / f"{check_id}.json",
                          {**record, "check_id": check_id, "checked_at": clock().astimezone(timezone.utc).isoformat()})
    return {"view_version": VIEW_VERSION, "check_id": check_id, "created": written, "results_created": created,
            "occasions": len(results), "package": package, "provider_called": False}


# ---------------------------------------------------------------- reads

def _records(folder: Path) -> list[dict]:
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*.json")):
        try:
            found.append(_read(path))
        except (OSError, ValueError):
            continue  # An unreadable record is skipped here and reported by the verifying reads below.
    return found


def _verified_checks(folders: Folders) -> list[dict]:
    """Check records of this version whose content hashes to their ID; any other record is ignored."""
    return [record for record in _records(folders.insights / "checks") if record.get("check_version") == CHECK_VERSION
            and record.get("check_id") == digest({key: value for key, value in record.items()
                                                  if key not in ("check_id", "checked_at")})]


def latest_check(folders: Folders) -> dict | None:
    checks = _verified_checks(folders)
    return max(checks, key=lambda record: (record["checked_at"], record["check_id"])) if checks else None


def _result(folders: Folders, result_id: str) -> dict:
    path = folders.insights / "results" / f"{result_id}.json"
    try:
        record = _read(path)
    except (OSError, ValueError):
        raise InsightRefused(409, f"Result {result_id[:12]} cannot be read") from None
    expected = digest({"result_version": RESULT_VERSION, "definitions_sha256": record.get("definitions_sha256"),
                       "context_date": record.get("context_date"),
                       "inputs_sha256": insight_rules.inputs_sha256(record.get("inputs", {}))})
    if record.get("result_version") != RESULT_VERSION or record.get("result_id") != result_id or expected != result_id:
        raise InsightRefused(409, f"Result {result_id[:12]} does not match its inputs; it is not shown")
    if record.get("definitions_sha256") != insight_rules.DEFINITIONS_SHA256:
        raise InsightRefused(409, f"Result {result_id[:12]} was computed under other definitions; it is not shown "
                                  "until a new check computes it")
    # The ID binds the inputs. They hold every observation the evaluation reads (from the earliest reference window
    # to A5), so the evaluation and the policy context are recomputed from them on every read and must equal what is
    # stored: a stored result that does not follow from its own inputs is never shown.
    inputs = record.get("inputs") or {}
    try:
        grid = insight_rules.Grid({series_id: [(date.fromisoformat(day), text) for day, text in inputs[series_id]]
                                   for series_id in insight_rules.YIELDS})
        evaluation = json.loads(json.dumps(insight_rules.evaluate(grid, date.fromisoformat(record["context_date"]))))
        policy = _policy_changes(inputs[DISCOUNT])
    except (KeyError, TypeError, ValueError, ArithmeticError):
        evaluation = policy = None
    windows = (evaluation or {}).get("windows") or {}
    span = [windows.get("PRE", {}).get("start"), windows.get("W5", {}).get("end")]
    if evaluation is None or evaluation != record.get("evaluation") or policy != record.get("policy_changes") \
            or span != record.get("span"):
        raise InsightRefused(409, f"Result {result_id[:12]} does not follow from its own inputs; it is not shown")
    return record


def _comparison_record(folders: Folders, comparison_id: str) -> dict | None:
    path = folders.insights / "comparisons" / f"{comparison_id}.json"
    try:
        record = _read(path)
    except (OSError, ValueError):
        return None
    identity = {key: record.get(key) for key in COMPARISON_IDENTITY}
    return record if record.get("comparison_id") == comparison_id == digest(identity) else None


def _attested(folders: Folders, result_id: str) -> list[dict]:
    """Every package a check used whose observations gave this result (the provenance of reuse)."""
    packages = {}
    for record in _verified_checks(folders):
        if any(item.get("result_id") == result_id for item in (record.get("occasions") or {}).values()):
            package = record.get("package") or {}
            packages[(package.get("package_id"), package.get("cutoff"))] = {
                key: package.get(key) for key in ("package_id", "sha256", "received_at", "cutoff", "last_date")}
    return sorted(packages.values(), key=lambda item: (item["received_at"] or "", item["package_id"] or ""))


def _summary(result: dict) -> dict:
    evaluation = result["evaluation"]
    met = [check for check in evaluation["checks"] if check["outcome"] == "met"]
    return {"state": evaluation["state"], "findings": len(met),
            "evaluable": sum(1 for check in evaluation["checks"] if check["outcome"] != "not_evaluable"),
            "checks": len(evaluation["checks"]), "problem": evaluation.get("problem")}


def listing(folders: Folders) -> dict:
    """The latest check, its occasions and events, and retained events not yet checked. Reads only."""
    latest = latest_check(folders)
    base = {"view_version": VIEW_VERSION, "scope": SCOPE, "limitations": list(LIMITATIONS),
            "definitions": insight_rules.DEFINITIONS, "bases": insight_events.BASES,
            "origins": insight_events.ORIGIN_LABELS, "written": False, "provider_called": False}
    current = insight_events.events(folders.intake, folders.market, folders.inbox, folders.library)
    if latest is None:
        return {**base, "check": None, "occasions": [], "events": [_event_row(event, None) for event in current],
                "unchecked": [event["key"] for event in current if event["state"] == "dated"], "comparison": None}
    occasions = []
    for day, outcome in sorted(latest["occasions"].items()):
        row = {"date": day, "state": outcome["state"], "result_id": outcome.get("result_id"),
               "detail": outcome.get("detail"), "events": [event["key"] for event in latest["events"]
                                                            if event["date"] == day and event["state"] == "dated"]}
        if outcome.get("result_id"):
            try:
                row.update(_summary(_result(folders, outcome["result_id"])))
            except InsightRefused as exc:
                row.update(state="problem", detail=str(exc))
        occasions.append(row)
    checked = {event["key"] for event in latest["events"]}
    unchecked = [event for event in current if event["key"] not in checked and event["state"] == "dated"]
    comparison = _comparison_record(folders, latest["comparison_id"])
    return {**base, "check": {key: latest[key] for key in ("check_id", "checked_at", "package")},
            "occasions": occasions, "events": [_event_row(event, latest) for event in latest["events"]] +
            [_event_row(event, None) for event in unchecked], "unchecked": [event["key"] for event in unchecked],
            "comparison": {"comparison_id": comparison["comparison_id"], "seed": comparison["seed"],
                           "size": comparison["counts"]["size"], "range": comparison["counts"]["range"],
                           "candidates": comparison["counts"]["candidates"],
                           "any": comparison["counts"]["any"]} if comparison else None}


def _event_row(event: dict, check_record: dict | None) -> dict:
    return {key: event[key] for key in ("key", "title", "link", "publisher", "family_label", "date", "state",
                                        "detail")} | {
        "records": [{key: record.get(key) for key in ("origin", "origin_id", "title", "basis", "as_stated", "problem",
                                                        "href", "note")} for record in event["records"]],
        "checked": check_record is not None}


def occasion_view(day: str, folders: Folders) -> dict:
    """One occasion of the latest check: its events, its measured table, its findings and checks. Reads only."""
    latest = latest_check(folders)
    if latest is None or day not in latest["occasions"]:
        raise InsightRefused(404, "This date has no checked occasion")
    outcome = latest["occasions"][day]
    events = [_event_row(event, latest) for event in latest["events"] if event["date"] == day
              and event["state"] == "dated"]
    base = {"view_version": VIEW_VERSION, "date": day, "events": events, "scope": SCOPE,
            "limitations": list(LIMITATIONS), "bases": insight_events.BASES, "origins": insight_events.ORIGIN_LABELS,
            "written": False}
    if not outcome.get("result_id"):
        return {**base, "state": "unavailable", "detail": outcome.get("detail"), "result": None}
    result = _result(folders, outcome["result_id"])
    comparison = _comparison_record(folders, latest["comparison_id"])
    nearby = [{"date": event["date"], "title": event["title"], "key": event["key"]} for event in latest["events"]
              if event["date"] and event["date"] != day and result["span"][0] <= event["date"] <= result["span"][1]]
    return {**base, "state": result["evaluation"]["state"], "detail": result["evaluation"].get("detail"),
            "result": render(result, comparison, nearby), "provenance": {
                "computed_from": result["computed_from"], "attested_by": _attested(folders, result["result_id"]),
                "result_id": result["result_id"], "inputs_sha256": result["inputs_sha256"],
                "definitions_sha256": result["definitions_sha256"]}}


def event_band(kind: str, item_id: str, folders: Folders) -> dict:
    """The findings state of the event an Inbox entry or capture belongs to, for its overview page. Reads only."""
    latest = latest_check(folders)
    base = {"view_version": VIEW_VERSION, "kind": kind, "id": item_id, "scope": SCOPE, "written": False}
    if latest is None:
        return {**base, "state": "not_checked", "event": None, "occasion": None}
    event = next((event for event in latest["events"] for record in event["records"]
                  if (record["origin"], record["origin_id"]) == (kind, item_id)), None)
    if event is None:
        return {**base, "state": "not_checked", "event": None, "occasion": None}
    occasion = latest["occasions"].get(event["date"]) if event["state"] == "dated" else None
    summary = None
    if occasion and occasion.get("result_id"):
        try:
            summary = _summary(_result(folders, occasion["result_id"]))
        except InsightRefused as exc:
            summary = {"state": "problem", "problem": str(exc)}
    return {**base, "state": event["state"] if event["state"] != "dated" else (summary or {}).get("state",
                                                                                                 "unavailable"),
            "event": _event_row(event, latest), "occasion": {"date": event["date"], **(occasion or {}),
                                                             **(summary or {})} if event["state"] == "dated" else None}
