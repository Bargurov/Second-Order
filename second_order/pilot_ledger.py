"""The FOMC pilot's ledger: one case per scheduled statement, counted deterministically from the store. Reads only.

The pilot is defined in content/pilot/fomc-pilot.json:
- its scheduled statement dates (New York), each with its story ID (fomc-<date>);
- its fixed legs, by observable ID and horizon;
- the start timestamp, once the owner approves the protocol (null until then);
- the owner's notes on a statement that was not held or was missed.

This module reads that file and the research store, opened read-only, and returns the ledger. It never writes,
freezes, assesses, imports or fetches anything.

Counting rules (the protocol's, docs/pilot/fomc-pilot-protocol.md):
- Story group and order. A statement's story group is every stored hypothesis whose story_id is that statement's. Its
  versions are ordered by freeze time, then hypothesis ID, so the order never depends on how rows were stored or read.
- The first version is the case. Every later version is kept and listed as an extra freeze. It never adds a case,
  never replaces the first, and its assessments are listed but never counted. A changed direction or form is a later
  version like any other.
- The start is an exact instant. start_utc is a UTC timestamp before the first statement's expected publication (2:00
  p.m. New York time on its date). A case counts only when its stated publication time is at or after that instant;
  times are compared as instants, whatever their offsets. A case published earlier is before the start and is never
  included afterwards. While the start is null, nothing is included, whatever the store holds.
- Inclusion rules. The case must be published on the statement's New York date, frozen after publication on that same
  New York date, and be a prospective showcase. If the first version fails any of these, the statement is missed, and
  a later version cannot repair it.
- Conformity. The case must have exactly the definition's legs: its primary observable marked primary, its secondary
  observable marked secondary, each with the defined horizon, and no other leg. Legs are identified by the
  definition's observable IDs, not by a record's primary flag alone. A nonconforming case stays the case: it is frozen,
  covered and shown with its reasons and any assessment, but it never enters the summary of results. A later
  conforming version does not replace it.
- Not held. A statement the owner marks as not held is listed with its reason and never included.
- No case. A statement is scheduled before its New York date, open on it, and missed after it, with the owner's reason
  or "no freeze recorded inside the window".
- Labels. A conforming assessed case is labelled by its first recorded evaluation (later reassessments are listed).
  Its primary label is the verdict of the definition's primary observable, and the secondary label is reported beside
  it. The two maturities are one case.

Counts reconcile:
- scheduled = not held + not started + before start + upcoming + included;
- included = frozen + missed;
- frozen = pending + assessed + nonconforming.

The summary (labels, eligible, the headline) is built from the assessed, conforming cases only. Hypotheses published
on a statement date under another story ID are listed as unmatched, never counted, so a mistyped story ID is visible.
The freeze window shown for each statement uses the release rule of baseline readiness (h15_release), and converts New
York times to Israel time per date.
"""
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from .data import NEW_YORK, ny_date
from .h15_release import earliest_release, release_words
from .store import connect_read_only, last_session_before

LEDGER_VERSION = "fomc-pilot-ledger-0.3"  # 0.3: the pilot's phase. 0.2: conformity; the start is an instant.
PILOT_VERSION = "fomc-pilot-0.1"
ROOT = Path(__file__).resolve().parent.parent
DEFINITION = ROOT / "content" / "pilot" / "fomc-pilot.json"
ISRAEL = ZoneInfo("Asia/Jerusalem")
STATEMENT_TIME = time(14, 0)  # A scheduled FOMC statement's usual publication time, New York; the record's own decides.
FIELDS = {"pilot_version", "status", "protocol", "start_utc", "family", "primary", "secondary", "statements"}
STATEMENT_FIELDS = {"date", "story_id", "not_held", "missed_reason", "note"}
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
COUNTED = ("supported", "contradicted", "inconclusive")
LABELS = ("supported", "contradicted", "inconclusive", "unavailable", "excluded", "pending")
NO_FREEZE = "no freeze recorded inside the window"
SECOND_ORDER = "Not measured: no operational second-order observable"


class DefinitionRefused(ValueError):
    pass


def _text_or_null(value: object, label: str) -> str | None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise DefinitionRefused(f"{label} must be null or a non-empty text")
    return value


def expected_publication(day: date) -> datetime:
    """2:00 p.m. New York time on a statement date: the usual time, used only where no record states one."""
    return datetime.combine(day, STATEMENT_TIME, NEW_YORK)


def load_definition(path: Path = DEFINITION) -> dict:
    """The pilot definition, checked strictly. Raises DefinitionRefused."""
    try:
        definition = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DefinitionRefused(f"The pilot definition cannot be read ({type(exc).__name__})") from None
    if not isinstance(definition, dict) or set(definition) != FIELDS:
        raise DefinitionRefused(f"The pilot definition must have exactly {', '.join(sorted(FIELDS))}")
    if definition["pilot_version"] != PILOT_VERSION:
        raise DefinitionRefused(f"The pilot definition is not {PILOT_VERSION}")
    start = definition["start_utc"]
    approved = definition["status"] == "approved"
    if definition["status"] not in ("proposed", "approved") or approved != (start is not None):
        raise DefinitionRefused("status is proposed with no start_utc, or approved with the start_utc the owner set")
    for key in ("primary", "secondary"):
        leg = definition[key]
        if not isinstance(leg, dict) or set(leg) != {"observable_id", "horizon"} or \
                not isinstance(leg["observable_id"], str) or leg["horizon"] not in (1, 5, 20):
            raise DefinitionRefused(f"{key} must name an observable and a horizon of 1, 5 or 20")
    if definition["primary"]["observable_id"] == definition["secondary"]["observable_id"]:
        raise DefinitionRefused("The primary and secondary legs must be different observables")
    statements = definition["statements"]
    if not isinstance(statements, list) or not 1 <= len(statements) <= 20:
        raise DefinitionRefused("statements must list 1 to 20 scheduled statements")
    previous = None
    for entry in statements:
        if not isinstance(entry, dict) or set(entry) != STATEMENT_FIELDS:
            raise DefinitionRefused(f"Each statement must have exactly {', '.join(sorted(STATEMENT_FIELDS))}")
        try:
            day = date.fromisoformat(entry["date"]) if isinstance(entry["date"], str) and \
                DAY.fullmatch(entry["date"]) else None
        except ValueError:
            day = None
        if day is None or (previous is not None and day <= previous):
            raise DefinitionRefused("Statement dates must be real dates, YYYY-MM-DD, in increasing order")
        if entry["story_id"] != f"fomc-{entry['date']}":
            raise DefinitionRefused(f"The statement of {entry['date']} must use story ID fomc-{entry['date']}")
        for key in ("not_held", "missed_reason", "note"):
            _text_or_null(entry[key], f"{entry['date']}: {key}")
        previous = day
    if start is not None:
        _check_start(start, date.fromisoformat(statements[0]["date"]))
    return definition


def _check_start(start: object, first: date) -> datetime:
    """The protocol's limits on the start: a UTC timestamp, before the first statement's expected publication."""
    try:
        moment = datetime.fromisoformat(start) if isinstance(start, str) else None
    except ValueError:
        moment = None
    if moment is None or moment.utcoffset() is None or moment.utcoffset() != timedelta(0):
        raise DefinitionRefused("start_utc must be an ISO date and time in UTC, with the offset +00:00")
    limit = expected_publication(first)
    if moment >= limit:
        local, utc = f"{limit:%Y-%m-%d %H:%M}", limit.astimezone(timezone.utc).isoformat()
        raise DefinitionRefused(f"start_utc must be before the first statement's expected publication, {local} New "
                                f"York time ({utc})")
    return moment


def freeze_window(day: date) -> dict:
    """Statement day ``day``: from when a fresh baseline can exist (the Board's release of the session before it) to New
    York midnight, in New York time and in Israel time."""
    opens = earliest_release(last_session_before(day))
    closes = datetime.combine(day + timedelta(days=1), time(0, 0), NEW_YORK)

    def israel(moment: datetime) -> str:
        local = moment.astimezone(ISRAEL)
        return f"{local.date().isoformat()} {local:%H:%M}"

    return {"new_york": {"baseline_obtainable_from": release_words(opens),
                         "closes": f"{closes.date().isoformat()} 00:00 New York time"},
            "israel": {"baseline_obtainable_from": israel(opens), "closes": israel(closes)},
            "rule": ("Freeze on the statement's New York date, after publication and after the Board's release of the "
                     "session before it (freshness policy B). A freeze after New York midnight falls on the next date "
                     "and is not the case.")}


def conformity(record: dict, definition: dict) -> list[str]:
    """Why a hypothesis does not have exactly the definition's legs (empty when it does). Legs are identified by the
    definition's observable IDs; a record's primary flag is checked against the role the definition gives them."""
    legs = record.get("legs") or []
    ids = [leg.get("observable_id") for leg in legs]
    wanted = {definition["primary"]["observable_id"]: ("primary", definition["primary"]["horizon"]),
              definition["secondary"]["observable_id"]: ("secondary", definition["secondary"]["horizon"])}
    found = []
    for observable_id, (role, _) in wanted.items():
        if observable_id not in ids:
            found.append(f"no {role} leg on {observable_id}")
    for observable_id in ids:
        if observable_id not in wanted:
            found.append(f"an extra leg on {observable_id}")
    if len(set(ids)) != len(ids):
        found.append("an observable appears in more than one leg")
    for leg in legs:
        if leg.get("observable_id") not in wanted:
            continue
        role, horizon = wanted[leg["observable_id"]]
        if (leg.get("primary") is True) != (role == "primary"):
            found.append(f"{leg['observable_id']} is marked {'secondary' if role == 'primary' else 'primary'}; the "
                         f"definition makes it the {role} leg")
        if leg.get("horizon") != horizon:
            found.append(f"{leg['observable_id']} has horizon {leg.get('horizon')}, not {horizon}")
    return found


def _rows(connection: sqlite3.Connection) -> tuple[list[dict], dict[str, list[dict]]]:
    hypotheses = []
    for identity, recorded_at, payload in connection.execute("SELECT id, recorded_at, payload FROM hypotheses"):
        record = json.loads(payload)
        hypotheses.append({"id": identity, "recorded_at": recorded_at, "record": record,
                           "frozen_at": datetime.fromisoformat(record["frozen_at"]),
                           "published_at": datetime.fromisoformat(record["event"]["published_at"])})
    evaluations: dict[str, list[dict]] = {}
    for identity, hypothesis_id, recorded_at, payload in connection.execute(
            "SELECT id, hypothesis_id, recorded_at, payload FROM evaluations"):
        evaluations.setdefault(hypothesis_id, []).append({"id": identity, "recorded_at": recorded_at,
                                                          "payload": json.loads(payload)})
    for items in evaluations.values():
        items.sort(key=lambda item: (item["recorded_at"], item["id"]))
    return hypotheses, evaluations


def _outside_rules(item: dict, day: date) -> list[str]:
    record, problems = item["record"], []
    if ny_date(item["published_at"]) != day:
        problems.append(f"published on {ny_date(item['published_at']).isoformat()}, not on {day.isoformat()}")
    if ny_date(item["frozen_at"]) != day:
        problems.append(f"frozen on {ny_date(item['frozen_at']).isoformat()} (New York), not on the statement date")
    if item["frozen_at"] < item["published_at"]:
        problems.append("frozen before publication")
    if record.get("evidence_class") != "prospective" or record.get("usage") != "showcase":
        problems.append(f"{record.get('evidence_class')} {record.get('usage')}, not a prospective showcase")
    return problems


def _labels(evaluation: dict | None, definition: dict) -> dict:
    """The recorded verdicts of the definition's primary and secondary observables (never by a primary flag)."""
    if evaluation is None:
        return {"primary": None, "secondary": None}
    verdicts = {leg.get("observable_id"): leg.get("verdict") for leg in evaluation["payload"].get("legs", [])}
    return {"primary": verdicts.get(definition["primary"]["observable_id"]),
            "secondary": verdicts.get(definition["secondary"]["observable_id"])}


def _version(item: dict, role: str, evaluations: dict, definition: dict) -> dict:
    record = item["record"]
    return {"hypothesis_id": item["id"], "role": role, "frozen_at": record["frozen_at"],
            "published_at": record["event"]["published_at"],
            "directions": {leg.get("observable_id"): leg.get("expected") for leg in record.get("legs", [])},
            "nonconforming": conformity(record, definition),
            "evaluations": [{"evaluation_id": entry["id"], "recorded_at": entry["recorded_at"],
                             **_labels(entry, definition)} for entry in evaluations.get(item["id"], [])]}


def _statement(entry: dict, group: list[dict], evaluations: dict, definition: dict, start: datetime | None,
               today: date) -> dict:
    day = date.fromisoformat(entry["date"])
    group = sorted(group, key=lambda item: (item["frozen_at"], item["id"]))
    first = group[0] if group else None
    versions = [_version(item, "extra", evaluations, definition) for item in group]
    row = {"date": entry["date"], "story_id": entry["story_id"], "note": entry["note"], "window": freeze_window(day),
           "state": None, "reason": None, "case": None, "in_summary": False,
           "labels": {"primary": None, "secondary": None}, "versions": versions,
           "extra_freezes": max(len(group) - 1, 0), "reassessments": 0}
    if entry["not_held"]:
        return {**row, "state": "not_held", "reason": entry["not_held"], "extra_freezes": len(group)}
    if start is None:
        return {**row, "state": "not_started", "reason": "The pilot has no start timestamp yet",
                "extra_freezes": len(group)}
    published = first["published_at"] if first is not None else expected_publication(day)
    if published < start:
        stated = "its first freeze states publication at" if first is not None else "expected publication"
        return {**row, "state": "before_start", "extra_freezes": len(group),
                "reason": f"Before the pilot's start: {stated} {published.isoformat()}, before {start.isoformat()}"}
    if first is not None:
        problems = _outside_rules(first, day)
        if problems:
            versions[0]["role"] = "first_outside_rules"
            return {**row, "state": "missed", "reason": entry["missed_reason"] or
                    "The first freeze is outside the rules: " + "; ".join(problems), "extra_freezes": len(group) - 1}
        versions[0]["role"] = "case"
        assessed = evaluations.get(first["id"], [])
        labels = _labels(assessed[0] if assessed else None, definition)
        common = {"case": first["id"], "labels": labels, "reassessments": max(len(assessed) - 1, 0)}
        reasons = versions[0]["nonconforming"]
        if reasons:
            return {**row, **common, "state": "nonconforming",
                    "reason": "Not in the summary of results: " + "; ".join(reasons)}
        return {**row, **common, "state": "assessed" if assessed else "pending", "in_summary": bool(assessed)}
    if today < day:
        return {**row, "state": "scheduled"}
    if today == day:
        return {**row, "state": "open", "reason": "The freeze window is today (New York date)"}
    return {**row, "state": "missed", "reason": entry["missed_reason"] or NO_FREEZE}


def _counts(rows: list[dict]) -> dict:
    states = [row["state"] for row in rows]
    summary = [row for row in rows if row["in_summary"]]
    primary = {label: sum(row["labels"]["primary"] == label for row in summary) for label in LABELS}
    secondary = {label: sum(row["labels"]["secondary"] == label for row in summary) for label in LABELS}
    frozen = states.count("pending") + states.count("assessed") + states.count("nonconforming")
    included = frozen + states.count("missed")
    counts = {"scheduled": len(rows), "not_held": states.count("not_held"), "not_started": states.count("not_started"),
              "before_start": states.count("before_start"),
              "upcoming": states.count("scheduled") + states.count("open"), "included": included,
              "missed": states.count("missed"), "frozen": frozen, "pending": states.count("pending"),
              "assessed": states.count("assessed"), "nonconforming": states.count("nonconforming"),
              "extra_freezes": sum(row["extra_freezes"] for row in rows)}
    if counts["scheduled"] != (counts["not_held"] + counts["not_started"] + counts["before_start"] + counts["upcoming"]
                               + counts["included"]):
        raise ValueError("The ledger's counts do not reconcile")  # Every state above is counted exactly once.
    eligible = sum(primary[label] for label in COUNTED)
    return {**counts, "summary_cases": len(summary), "primary_labels": primary, "eligible": eligible,
            "secondary_labels": secondary, "second_order": SECOND_ORDER,
            "headline": (f"{primary['supported']} of {eligible} eligible primary legs had observations consistent with "
                         "the frozen hypothesis")}


def phase(definition: dict, moment: datetime) -> dict:
    """Where the pilot stands at ``moment``: proposed, approved but not started, running, or intake ended."""
    start = datetime.fromisoformat(definition["start_utc"]) if definition["start_utc"] else None
    last = date.fromisoformat(definition["statements"][-1]["date"])
    intake_ends = datetime.combine(last + timedelta(days=1), time(0, 0), NEW_YORK)
    if start is None:
        return {"phase": "proposed", "text": "Proposed: not approved, so nothing is counted"}
    if moment < start:
        return {"phase": "approved_not_started",
                "text": f"Approved; starts at {start.isoformat()}, in the future: nothing is counted before then"}
    if moment < intake_ends:
        return {"phase": "running", "text": f"Running since {start.isoformat()}; intake is open through the last "
                                            f"statement ({last.isoformat()})"}
    return {"phase": "intake_ended", "text": f"Intake ended with the last statement ({last.isoformat()}); outcomes are "
                                             "tracked until every frozen case is assessed"}


def ledger(definition: dict, store: Path | None, clock=lambda: datetime.now(NEW_YORK)) -> dict:
    """The ledger for this definition and store (None or a missing file: no hypotheses). Reads only."""
    moment = clock()
    today = ny_date(moment)
    hypotheses, evaluations = [], {}
    if store is not None and store.is_file():
        connection = connect_read_only(str(store))
        try:
            hypotheses, evaluations = _rows(connection)
        finally:
            connection.close()
    start = datetime.fromisoformat(definition["start_utc"]) if definition["start_utc"] else None
    stories = {entry["story_id"] for entry in definition["statements"]}
    dates = {entry["date"] for entry in definition["statements"]}
    rows = [_statement(entry, [item for item in hypotheses if item["record"].get("story_id") == entry["story_id"]],
                       evaluations, definition, start, today) for entry in definition["statements"]]
    unmatched = sorted(({"hypothesis_id": item["id"], "story_id": item["record"].get("story_id"),
                         "published_date": ny_date(item["published_at"]).isoformat(),
                         "reason": "Published on a statement date under another story ID: not counted"}
                        for item in hypotheses if item["record"].get("story_id") not in stories
                        and ny_date(item["published_at"]).isoformat() in dates),
                       key=lambda row: (row["published_date"], row["hypothesis_id"]))
    return {"ledger_version": LEDGER_VERSION, "pilot_version": definition["pilot_version"],
            "status": definition["status"], "start_utc": definition["start_utc"], "today_new_york": today.isoformat(),
            "phase": phase(definition, moment),
            "counts": _counts(rows), "statements": rows, "unmatched": unmatched,
            "store": str(store) if store is not None else None, "written": False, "provider_called": False}


def table(result: dict) -> str:
    """The ledger as a plain text table, one row per scheduled statement, then the counts."""
    lines = [f"FOMC pilot ledger ({result['pilot_version']}, {result['status']}; start "
             f"{result['start_utc'] or 'not set'}; New York date {result['today_new_york']})",
             f"Phase: {result['phase']['text']}.", "",
             f"{'Date':<11} {'State':<14} {'Case':<13} {'Extra':>5}  {'2y':<13} {'10y':<13} Reason"]
    for row in result["statements"]:
        lines.append(f"{row['date']:<11} {row['state']:<14} {(row['case'] or '-')[:12]:<13} {row['extra_freezes']:>5}  "
                     f"{row['labels']['primary'] or '-':<13} {row['labels']['secondary'] or '-':<13} "
                     f"{row['reason'] or ''}")
    counts = result["counts"]
    lines += ["",
              f"Scheduled {counts['scheduled']} = not held {counts['not_held']} + not started {counts['not_started']} "
              f"+ before start {counts['before_start']} + upcoming {counts['upcoming']} + included "
              f"{counts['included']}",
              f"Included {counts['included']} = frozen {counts['frozen']} + missed {counts['missed']}; frozen "
              f"{counts['frozen']} = pending {counts['pending']} + assessed {counts['assessed']} + nonconforming "
              f"{counts['nonconforming']}; extra freezes {counts['extra_freezes']} (never counted)",
              f"Summary (assessed, conforming cases only): {counts['headline']}.",
              f"Second order: {counts['second_order']}."]
    if result["unmatched"]:
        lines.append("Unmatched (not counted): " + ", ".join(f"{row['hypothesis_id'][:12]} ({row['story_id']})"
                                                            for row in result["unmatched"]))
    return "\n".join(lines)
