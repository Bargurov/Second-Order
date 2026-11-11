"""Research readiness: what can be frozen prospectively now, what is missing, and the next explicit action.

A read-only preflight over the registry, the research store, the kept H.15 release packages, the committed demonstration
fixture and INCLUSION.md. It keeps three questions apart:
- Freeze readiness, now: for each observable, whether a prospective freeze could bind a baseline the freeze itself
  would accept. That needs a source binding; a verified snapshot of that provider received before now; freshness policy
  B for the publication date (Snapshot.coverage, the same test store.check_freshness applies); and the scorer's own
  reference windows under the active rules (snapshots.snapshot_readiness, as store.check_history uses it). No other
  threshold is applied.
- Outcome readiness, later: the expected scoring window on the SIFMA calendar for a freeze on the New York freeze date
  (the lifecycle's own rule). Outcome data cannot exist before a target date ends, so their absence never blocks a
  freeze.
- When the Board can first state a session: the shared rule of h15_release (4:15 p.m. New York time on the weekday
  after the session; a holiday or a closed Board only delays it), the same rule the outcome plans use. Before that
  moment this check says to wait for the release instead of proposing a download that could only return an earlier
  session. What is held is still decided by the verified snapshots alone.
- Research use: a separate gate. Dated-only observations do not meet the research timestamp gate
  (evaluation.evaluate_leg records such a research leg as unavailable), the freeze-draft command and the Hypotheses
  page freeze prospective showcase drafts only, and INCLUSION.md states whether research intake has started. Nothing
  here changes any of them.

A registry concept without a source binding (yield:us2y, yield:us10y, index:dxy, fx:usdils, the futures and the
us_equity and us_etf families) is never presented as operational: no provider supplies any observation for it, and no
data for it are held. The offline demo's FICTIONAL demonstration series (fixtures/demo-market.json) are reported apart,
as demonstration series that cover no registry concept; a research hypothesis cannot name them.

Reads only: nothing is imported, validated, migrated, frozen, evaluated or fetched, and no key, token or contact is
read from the environment.
"""
from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import Callable

from . import market_store
from .data import daily_observation_time, ny_date
from .demo import DEMO_MARKET
from .freeze_origins import LIFECYCLE_VERSION, Folders, LifecycleRefused
from .h15_release import POSTING as H15_POSTING, earliest_release, release_words
from .lifecycle import _sessions_after, now, store_state
from .market_calendar import calendar_identity, load_exceptions
from .registry import BOARD_H15, FRED, binding, registry_ids, resolve
from .schema import utc
from .scoring import Rules
from .snapshots import Snapshot, list_snapshots, snapshot_readiness, verify_snapshot
from .store import FRESHNESS_POLICY, connect_read_only, last_session_before

READINESS_VERSION = "research-readiness-0.2"  # 0.2: the demo fixture is reported apart; concept rows hold no fixture.
ROOT = Path(__file__).resolve().parent.parent
INCLUSION_PATH = ROOT / "INCLUSION.md"
HORIZONS = (1, 5, 20)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
SAMPLE_TICKER = "SPY"  # Resolves a family placeholder to its shared measurement; never a selection.

LABELS = {
    "yield:us2y": "2-year Treasury yield (concept)",
    "yield:us10y": "10-year Treasury yield (concept)",
    "index:dxy": "US dollar index (DXY)",
    "fx:usdils": "US dollar / Israeli shekel",
    "futures:wti": "WTI crude oil futures",
    "futures:brent": "Brent crude oil futures",
    "yield:ust2y_cmt": "2-year Treasury yield (FRED DGS2)",
    "yield:ust10y_cmt": "10-year Treasury yield (FRED DGS10)",
    "yield:ust2y_cmt_h15": "2-year Treasury yield (Board H.15)",
    "yield:ust10y_cmt_h15": "10-year Treasury yield (Board H.15)",
    "us_equity:<TICKER>": "US equities, any ticker",
    "us_etf:<TICKER>": "US exchange-traded funds, any ticker",
}

PATHS = {
    BOARD_H15: {
        "name": "Federal Reserve Board H.15 release package",
        "connection": ("Connected through one explicitly approved, keyless download of the Board's H.15 release "
                       "package (Market context, on a server started with --enable-market-retrieval). The kept "
                       "package is then validated and imported into the store, locally; reads never download."),
        "freeze_path": ("Freeze on the Hypotheses page (baseline, preview, one approval), or a manual draft with the "
                        "freeze-draft command."),
        "outcome_path": ("After the target dates end: one approved outcome download from the Hypotheses page (Outcome "
                         "data) or a newer kept package, imported explicitly from the publication date, then the "
                         "assessment approval."),
    },
    FRED: {
        "name": "FRED (Federal Reserve Bank of St. Louis API)",
        "connection": ("Connected through the explicit network command `market import`, which needs FRED_API_KEY in "
                       "the environment. This check reads no key, so it cannot say whether one is set."),
        "freeze_path": "Freeze a manual draft with the freeze-draft command; the Hypotheses page freezes H.15 only.",
        "outcome_path": ("After the target dates end: a later `market import` received after them, then an assessment "
                         "on the Hypotheses page or `evaluate --outcome`."),
    },
}
DAILY_GATE = ("Its observations are dated, not timed (the daily date convention), so a research-usage leg on it is "
              "recorded as unavailable: research requires verified observation timestamps.")
NO_PROVIDER_GATE = "No provider supplies it, so a research leg on it could never be measured."
SHOWCASE_PATHS = ("The freeze-draft command and the Hypotheses page freeze prospective showcase drafts only; the general "
                  "freeze command stores any valid hypothesis, but a research-usage leg on a dated-only observable is "
                  "recorded as unavailable.")
RESEARCH_DECISIONS = (
    "Record a start timestamp and an allowed source list in INCLUSION.md and commit the rule before any research "
    "hypothesis (owner decision).",
    "Decide how dated-only observations meet the research timestamp gate: connect a source with verified observation "
    "times, or adopt a new rules version that defines a separate daily-date research class. Neither is made here.",
)
CONCEPT_ACTION = ("Owner decision: bind a provider series under a new source-bound registry ID (an adapter, an approved "
                  "acquisition and the source's terms checked). A concept ID is never re-pointed to another series.")
UPGRADE_ACTION = ("Upgrade the store to schema 4 before a freeze on the Hypotheses page (its upgrade action, or "
                  "`python -m second_order store migrate --db <store>`): it only adds tables and proves every record "
                  "unchanged. The freeze-draft command accepts the current schema.")


def parse_published(text: str | None) -> date | None:
    """The publication date a reader asks about (YYYY-MM-DD, New York), or None for today."""
    if text is None:
        return None
    try:
        if not DATE.fullmatch(text):
            raise ValueError
        return date.fromisoformat(text)
    except ValueError:
        raise LifecycleRefused(422, "published must be a date, YYYY-MM-DD") from None


def inclusion_status(path: Path = INCLUSION_PATH) -> str | None:
    """INCLUSION.md's Status line exactly as written (its text after "Status:"), or None when there is none."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return next((line[len("Status:"):].strip() for line in lines if line.startswith("Status:")), None)


def _demonstration(path: Path = DEMO_MARKET) -> dict | None:
    """The committed FICTIONAL demonstration series of the offline demo: what they cover, and that no registry concept
    is among them."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    series = [{"observable_id": key, "provider": row["provider"], "ticker": row["ticker"],
               "first_date": row["rows"][0][0], "last_date": row["rows"][-1][0], "rows": len(row["rows"])}
              for key, row in payload["rows"].items() if row["rows"]]
    covered = sorted(set(payload["rows"]) & set(registry_ids()))
    names = ", ".join(item["observable_id"] for item in series)
    return {"fixture": path.name, "version": payload["version"], "generator": payload["generator"],
            "timestamp_basis": payload["timestamp_basis"], "series": series, "registry_concepts_covered": covered,
            "plain": (f"The offline demo's two showcase replays of fictional events use FICTIONAL demonstration series "
                      f"({names}; {payload['version']}), invented by {payload['generator']}; nothing in them is a "
                      "market observation. " + ("They cover no registry concept, and a research hypothesis cannot "
                                                "name them." if not covered else
                                                f"They also name registry IDs: {', '.join(covered)}."))}


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


# ---------------------------------------------------------------- what the store holds

def _candidate(snapshot: Snapshot, moment: datetime, published: date, required: date) -> dict:
    """One verified snapshot: per series, its coverage of the required session and, when it could serve as a baseline,
    the scorer's reference windows for each horizon."""
    received_before = snapshot.retrieved_at <= moment
    readiness = None
    series = {}
    for series_id in sorted(snapshot.classified):
        coverage = snapshot.coverage(series_id, required)
        entry = {"classified_from": _iso(coverage["classified_from"]),
                 "classified_through": _iso(coverage["classified_through"]),
                 "covers_required_session": coverage["covered"], "required_session_status": coverage["status"],
                 "history_checked": False, "scorable_horizons": [], "horizons": {}}
        if coverage["covered"] and received_before:
            readiness = readiness or snapshot_readiness(snapshot, before=published)
            item = readiness["series"].get(series_id)
            if item:
                entry.update(history_checked=True, scorable_horizons=item["scorable_horizons"],
                             history_sessions=item["history_sessions"],
                             horizons={key: {name: value[name] for name in ("reference_windows",
                                                                             "required_reference_windows", "scorable")}
                                       | ({"reason": value["reason"]} if "reason" in value else {})
                                       for key, value in item["horizons"].items()})
        series[series_id] = entry
    source = snapshot.payload.get("source") if snapshot.provider == BOARD_H15 else None
    return {"snapshot_id": snapshot.id, "provider": snapshot.provider, "verified": True, "problem": None,
            "retrieved_at": snapshot.payload["retrieved_at"], "received_before_now": received_before,
            "package_id": source.get("package_id") if isinstance(source, dict) else None, "series": series}


def _candidates(folders: Folders, state: dict, moment: datetime, published: date, required: date) -> list[dict]:
    if not state["exists"] or state["schema"] not in (2, 3, 4):
        return []
    connection = connect_read_only(str(folders.store))
    try:
        found = []
        for row in list_snapshots(connection):
            try:
                snapshot = verify_snapshot(connection, row["snapshot_id"])
            except ValueError as exc:
                found.append({"snapshot_id": row["snapshot_id"], "provider": row["provider"], "verified": False,
                              "problem": str(exc), "retrieved_at": row["retrieved_at"], "received_before_now": None,
                              "package_id": None, "series": {}})
                continue
            found.append(_candidate(snapshot, moment, published, required))
        return found
    finally:
        connection.close()


def _packages(folders: Folders, moment: datetime, required: date, candidates: list[dict]) -> tuple[list[dict], list]:
    """Kept H.15 release packages: status, coverage, whether it reaches the required session and what holds it."""
    _, problems, kept = market_store.local_data(folders.market, None)
    rows = []
    for package in kept:
        coverage = package["coverage"]
        imported = [item["snapshot_id"] for item in candidates if item["package_id"] == package["package_id"]]
        rows.append({"package_id": package["package_id"], "status": package["status"],
                     "received_at": package["received_at"], "coverage": coverage,
                     "received_before_now": datetime.fromisoformat(package["received_at"]) <= moment,
                     "reaches_required_session": bool(coverage) and date.fromisoformat(coverage["last"]) >= required,
                     "imported_as": imported})
    return rows, problems


# ---------------------------------------------------------------- one observable

def _held_through(candidates: list[dict], series_id: str) -> tuple[str | None, str | None]:
    """The latest classified date any verified snapshot holds for a series, and that snapshot."""
    best = (None, None)
    for item in candidates:
        through = item["series"].get(series_id, {}).get("classified_through")
        if item["verified"] and through and (best[0] is None or through > best[0]):
            best = (through, item["snapshot_id"])
    return best


def _bound_blockers(candidates: list[dict], series_id: str, required: date, published: date) -> list[str]:
    held = [item for item in candidates if series_id in item["series"] or not item["verified"]]
    if not held:
        return ["No snapshot of this provider is in the store."]
    blockers = []
    for item in held:
        label = f"Snapshot {item['snapshot_id'][:12]}"
        entry = item["series"].get(series_id)
        if not item["verified"]:
            blockers.append(f"{label} does not verify and is never used: {item['problem']}")
        elif not item["received_before_now"]:
            blockers.append(f"{label} was received after this moment.")
        elif not entry["covers_required_session"]:
            blockers.append(f"{label} classifies it from {entry['classified_from']} through "
                            f"{entry['classified_through']}; a baseline must classify {required.isoformat()}, the last "
                            f"expected session before {published.isoformat()} (freshness policy B).")
        elif not entry["scorable_horizons"]:
            windows = ", ".join(f"{value['reference_windows']} at horizon {key}"
                                for key, value in entry["horizons"].items())
            blockers.append(f"{label} covers {required.isoformat()}, but its history before {published.isoformat()} "
                            f"gives too few usable reference windows ({windows}); the rules require "
                            f"{Rules().min_windows}.")
    return blockers


def _bound_action(provider: str, status: str, series_id: str, packages: list[dict], candidates: list[dict],
                  required: date, moment: datetime) -> str:
    if status == "freeze_ready":
        return f"Nothing is missing for a prospective showcase freeze. {PATHS[provider]['freeze_path']}"
    if status == "waiting_for_session" and provider == BOARD_H15:
        return (f"Wait until {required.isoformat()} has ended and the Board's H.15 release states it, no earlier than "
                f"{release_words(earliest_release(required))} ({H15_POSTING}). No held data can classify it before "
                "then. Then run this check again.")
    if status == "waiting_for_session":
        return (f"Wait until {required.isoformat()} has ended and its value is published; no held data can classify it "
                "before then. Then run this check again.")
    short = [item for item in candidates if item["verified"] and item["received_before_now"]
             and item["series"].get(series_id, {}).get("covers_required_session")]
    if provider == BOARD_H15:
        importable = [row for row in packages if row["status"] == "accepted" and row["reaches_required_session"]
                      and row["received_before_now"]]
        if importable:
            package = importable[-1]["package_id"]
            again = " again with an earlier start" if short else ""
            return (f"Import kept package {package}{again} into the store, locally: on the Hypotheses page, or "
                    f"`python -m second_order market import-package --db <store> --package {package} --start "
                    "<YYYY-MM-DD>`, with a start early enough for the reference windows the rules require. Then run "
                    "this check again.")
        if any(row["status"] == "acquired_unvalidated" for row in packages):
            return ("Validate the kept package locally: `python -m second_order market-packages validate` (it writes "
                    "the validation record once and fetches nothing). Then run this check again.")
        release = earliest_release(required)
        if moment < release:
            return (f"Wait until {release_words(release)} before downloading ({H15_POSTING}): {required.isoformat()} "
                    "can appear no earlier than that release, and a download before then returns data through an "
                    "earlier session. Then approve one download of the Board's H.15 release package (Market context, "
                    "on a server started with --enable-market-retrieval), and validate and import it locally.")
        return ("Approve one download of the Board's H.15 release package (Market context, on a server started with "
                "--enable-market-retrieval). Nothing here requests it. Then validate and import it locally.")
    again = " again with an earlier start" if short else ""
    return (f"Run `python -m second_order market import --db <store> --start <YYYY-MM-DD>`{again}: an explicit network "
            "request that needs FRED_API_KEY and your approval, with a start early enough for the reference windows "
            "the rules require.")


def _bound_row(observable_id: str, candidates: list[dict], packages: list[dict], required: date,
               required_ended: bool, published: date, outcome: dict, moment: datetime) -> dict:
    observable = resolve(observable_id)
    provider, series_id = binding(observable_id)
    mine = [item for item in candidates if item["provider"] == provider]
    usable = [item for item in mine if item["verified"] and item["received_before_now"]
              and item["series"].get(series_id, {}).get("covers_required_session")
              and item["series"][series_id]["scorable_horizons"]]
    status = "freeze_ready" if usable else "waiting_for_session" if not required_ended else "needs_baseline"
    blockers = [] if usable else _bound_blockers(mine, series_id, required, published)
    held, held_in = _held_through(mine, series_id)
    if status == "freeze_ready":
        best = usable[-1]
        horizons = ", ".join(str(h) for h in best["series"][series_id]["scorable_horizons"])
        plain = (f"Snapshot {best['snapshot_id'][:12]} classifies {required.isoformat()}, the last expected session "
                 f"before {published.isoformat()}, and gives enough history for horizon(s) {horizons}.")
    elif status == "waiting_for_session":
        plain = (f"The last expected session before {published.isoformat()} is {required.isoformat()}, which has not "
                 "ended, so no held data can classify it yet.")
    else:
        plain = (f"A baseline must classify {required.isoformat()}, the last expected session before "
                 f"{published.isoformat()}; " + (f"the newest held data end on {held}." if held else
                                                 "no snapshot of this provider is in the store."))
    retained = {"snapshots": [{"snapshot_id": item["snapshot_id"], "verified": item["verified"],
                               "problem": item["problem"], "retrieved_at": item["retrieved_at"],
                               "received_before_now": item["received_before_now"], "package_id": item["package_id"],
                               **item["series"].get(series_id, {})} for item in mine],
                "newest_classified_date": held, "newest_in_snapshot": held_in}
    if provider == BOARD_H15:
        retained["packages"] = packages
    return {"observable_id": observable_id, "label": LABELS.get(observable_id, observable_id), "kind": "source_bound",
            "status": status, "plain": plain,
            "registry": {"source": observable.source, "unit": observable.unit, "measurement": observable.measurement,
                         "anchor_policy": observable.anchor_policy},
            "provider": {"id": provider, "series_id": series_id, **PATHS[provider]},
            "retained": retained,
            "freeze": {"ready": bool(usable), "baselines": [item["snapshot_id"] for item in usable],
                       "scorable_horizons": usable[-1]["series"][series_id]["scorable_horizons"] if usable else [],
                       "blockers": blockers},
            "outcome": {**outcome, "path": PATHS[provider]["outcome_path"]},
            "research": {"eligible": False, "reasons": [DAILY_GATE] if observable.anchor_policy == "daily_ny_date"
                         else []},
            "next_action": _bound_action(provider, status, series_id, packages, mine, required, moment)}


def _concept_row(observable_id: str) -> dict:
    family = "<TICKER>" in observable_id
    observable = resolve(observable_id.replace("<TICKER>", SAMPLE_TICKER) if family else observable_id)
    needs = (" It would also need observed regular-session close times, a session calendar and the SPY benchmark for "
             "its market model." if observable.anchor_policy == "us_regular_session" else "")
    return {"observable_id": observable_id, "label": LABELS.get(observable_id, observable_id), "kind": "concept_only",
            "status": "concept_only",
            "plain": f"Registry concept only: no provider is connected. No data for it are held anywhere in the "
                     f"project.{needs}",
            "registry": {"source": None, "unit": observable.unit, "measurement": observable.measurement,
                         "anchor_policy": observable.anchor_policy, "benchmark": observable.benchmark,
                         "requires_contract": observable.requires_contract},
            "provider": None,
            "retained": {},
            "freeze": {"ready": False, "baselines": [], "scorable_horizons": [],
                       "blockers": ["No provider series is bound to it: no baseline can be bound, and no observation "
                                    "after a freeze would ever be supplied, so every leg on it would be recorded as "
                                    "unavailable."]},
            "outcome": None,
            "research": {"eligible": False, "reasons": [NO_PROVIDER_GATE]},
            "next_action": CONCEPT_ACTION}


# ---------------------------------------------------------------- the report

def _outcome(freeze_date: date, moment: datetime) -> dict:
    """The expected scoring window for a freeze on ``freeze_date`` (the lifecycle's SIFMA rule): expected, not measured."""
    sessions = _sessions_after(freeze_date, 1 + max(HORIZONS))
    targets = {str(h): {"expected_target": sessions[h].isoformat(),
                        "counts_after": daily_observation_time(sessions[h]).isoformat()} for h in HORIZONS}
    due = [h for h in HORIZONS if daily_observation_time(sessions[h]) <= moment]
    dates = ", ".join(targets[str(h)]["expected_target"] for h in HORIZONS)
    return {"freeze_date_new_york": freeze_date.isoformat(), "expected_score_anchor": sessions[0].isoformat(),
            "targets": targets, "state": "not_due" if not due else "due", "blocks_freeze": False,
            "plain": (f"A freeze on {freeze_date.isoformat()} would score from {sessions[0].isoformat()}; the 1-, 5- "
                      f"and 20-observation targets are expected on {dates} (SIFMA calendar: expected, not measured). "
                      "Outcome data for a target can exist only after its date ends, so their absence never blocks "
                      "a freeze.")}


def _provider(provider: str, rows: list[dict]) -> dict:
    """One provider as a hypothesis meets it: every leg of a source-bound hypothesis is bound to one provider and one
    baseline snapshot (store.bound_provider, check_baseline), and the schema needs at least two distinct observables,
    so a freeze needs one snapshot that serves every leg."""
    mine = [row for row in rows if row["provider"] and row["provider"]["id"] == provider]
    shared = set.intersection(*(set(row["freeze"]["baselines"]) for row in mine)) if mine else set()
    baselines = [snapshot for snapshot in mine[0]["freeze"]["baselines"] if snapshot in shared] if mine else []
    statuses = {row["status"] for row in mine}
    status = ("freeze_ready" if baselines else "waiting_for_session" if "waiting_for_session" in statuses
              else "needs_baseline")
    if baselines:
        action = mine[0]["next_action"]
    elif statuses == {"freeze_ready"}:
        action = ("No single snapshot serves every observable of this provider; import one baseline that covers them "
                  "all, then run this check again.")
    else:
        action = next(row["next_action"] for row in mine if row["status"] != "freeze_ready")
    labels = [row["label"] for row in mine]
    return {"provider": provider, "name": PATHS[provider]["name"], "status": status, "observables": labels,
            "baselines": baselines,
            "scorable_horizons": {row["observable_id"]: row["freeze"]["scorable_horizons"] for row in mine},
            "composition": (f"A hypothesis on this provider needs at least two distinct observables of it and cannot "
                            f"mix providers; this provider has {len(mine)}: {', '.join(labels)}."),
            "action": action}


def _freeze_answer(rows: list[dict], providers: list[dict], published: date, required: date,
                   packages: list[dict]) -> str:
    concepts = sum(row["kind"] == "concept_only" for row in rows)
    ready = [item for item in providers if item["status"] == "freeze_ready"]
    if ready:
        return (f"You can freeze a prospective showcase hypothesis for {published.isoformat()} on the " +
                " or the ".join(f"{' and '.join(item['observables'])}, with baseline {item['baselines'][-1][:12]}"
                                for item in ready) +
                f". The other {concepts} registry entries are concepts with no provider.")
    held = [f"{row['label']} through {row['retained']['newest_classified_date']}" for row in rows
            if row["kind"] == "source_bound" and row["retained"]["newest_classified_date"]]
    unimported = [f"kept H.15 package {row['package_id']} through {row['coverage']['last']}, not imported"
                  for row in packages if row["coverage"] and not row["imported_as"]]
    bound = sum(row["kind"] == "source_bound" for row in rows)
    return (f"Nothing can be frozen prospectively for {published.isoformat()} yet. The {bound} connected observables "
            f"need a baseline that classifies {required.isoformat()}, the last expected session before "
            f"{published.isoformat()}. Held now: " + ("; ".join(held + unimported) or "nothing") +
            f". The other {concepts} registry entries are concepts with no provider.")


def _research(rows: list[dict]) -> dict:
    status = inclusion_status()
    dated = [row["label"] for row in rows if DAILY_GATE in row["research"]["reasons"]]
    concepts = [row["label"] for row in rows if NO_PROVIDER_GATE in row["research"]["reasons"]]
    eligible = [row["observable_id"] for row in rows if not row["research"]["reasons"]]
    reasons = [f"INCLUSION.md: {status}" if status else "INCLUSION.md states no status.", SHOWCASE_PATHS]
    if dated:
        reasons.append(f"The {len(dated)} connected observables are dated, not timed (the daily date convention): a "
                       "research-usage leg on them is recorded as unavailable, because research requires verified "
                       "observation timestamps.")
    if concepts:
        reasons.append(f"The {len(concepts)} registry concepts have no provider, so a research leg on them could never "
                       "be measured.")
    plain = ("Not possible now. " if not eligible else
             f"Research legs could be measured on {', '.join(eligible)}, but a research freeze still needs the steps "
             "below. ") + " ".join(reasons)
    return {"measurable_observables": eligible, "inclusion_status": status, "reasons": reasons,
            "decisions": list(RESEARCH_DECISIONS), "plain": plain}


def report(folders: Folders, clock: Callable[[], datetime] = now, published: date | None = None) -> dict:
    """Freeze readiness, outcome readiness and research use, per registry entry, for one publication date (default:
    today in New York). Reads only."""
    moment = utc(clock())
    today = ny_date(moment)
    published = published or today
    try:
        required = last_session_before(published)
    except ValueError as exc:
        raise LifecycleRefused(422, str(exc)) from None
    required_ended = daily_observation_time(required) <= moment
    state = store_state(folders)
    candidates = _candidates(folders, state, moment, published, required)
    packages, package_problems = _packages(folders, moment, required, candidates)
    outcome = _outcome(max(today, published), moment)
    rows = []
    for observable_id in registry_ids():
        if "<TICKER>" not in observable_id and binding(observable_id) is not None:
            rows.append(_bound_row(observable_id, candidates, packages, required, required_ended, published, outcome,
                                   moment))
        else:
            rows.append(_concept_row(observable_id))
    # H.15 first: it needs no key, and the Hypotheses page covers its whole lifecycle.
    providers = [_provider(provider, rows) for provider in (BOARD_H15, FRED)]
    actions = [{key: item[key] for key in ("provider", "name", "status", "action")} for item in providers]
    if not state["interface_freezes"]:
        actions.append({"provider": None, "name": "Research store", "status": "interface_freeze_unavailable",
                        "action": UPGRADE_ACTION if state["exists"] else
                        "No store exists yet: importing a baseline (Hypotheses page) creates one at schema 4."})
    first = next((item for item in providers if item["status"] == "freeze_ready"), providers[0])
    research = _research(rows)
    rules = Rules()
    return {
        "readiness_version": READINESS_VERSION, "lifecycle_version": LIFECYCLE_VERSION,
        "answer": {"freeze_now": _freeze_answer(rows, providers, published, required, packages),
                   "outcomes": outcome["plain"], "research": research["plain"], "next_action": first["action"]},
        "published_date": published.isoformat(), "required_session": required.isoformat(),
        "required_session_ended": required_ended,
        "providers": providers, "observables": rows, "next_actions": actions, "research": research,
        "demonstration": _demonstration(), "store": state,
        "provenance": {"checked_at": moment.isoformat(), "today_new_york": today.isoformat(),
                       "required_session_rule": ("Freshness policy B: the baseline must classify the last expected "
                                                 "SIFMA session dated before the publication date."),
                       "freshness_policy": FRESHNESS_POLICY,
                       "rules": {"version": rules.version, "hash": rules.hash, "min_windows": rules.min_windows},
                       "calendar": calendar_identity(load_exceptions()), "package_problems": package_problems,
                       "fixture": DEMO_MARKET.name},
        "provider_called": False, "written": False,
    }
