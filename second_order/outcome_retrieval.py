"""Outcome data for frozen hypotheses: planning and sending one explicitly approved download of the Board's H.15
release package, from the Hypotheses page.

A lifecycle plan (PLAN_VERSION) is its own approval scope, separate from the market-context plans of events (whose
windows are fourteen days either side of a context date and do not cover a late freeze or a longer horizon). For the
selected frozen hypotheses it lists every expected session (SIFMA calendar) from each publication date through its
latest expected target date, and splits them:
- future: on or after today's New York date. They are not requested and never presented as data a download can
  already obtain: a date-only observation is complete only after its date ends.
- awaiting release: dates that have ended but that the Board's release cannot state yet. The Board posts H.15 on
  business days at 4:15 p.m. New York time with the previous business day's values (h15_release, the rule research
  readiness uses for baselines), so a session can first be obtained at 4:15 p.m. on the next weekday. They are not
  requested; the plan says from when they can be.
- held: classified by a verified store snapshot that can serve as the hypothesis's outcome, or stated by a kept,
  accepted package received after its baseline (which then needs only a local import).
- missing: the rest, which the Board can already have posted. Missing sessions need one request for the whole
  release package, whatever their number, and that one package serves every selected hypothesis; a covered selection
  needs none. A session awaiting release never blocks a request that missing sessions of other hypotheses justify: the
  package simply will not state it yet.
Held is decided first, from the verified local data only, so a value the Board posted early is used; the timing rule
only decides what is worth requesting.
Only Board H.15-bound hypotheses are planned: a FRED-bound hypothesis is refused with its reason, and nothing here
fetches FRED data.

Sending reuses the market retrieval's fetcher and keep-and-validate path (market_retrieval._send) with every safeguard:
the server must be started with market retrieval enabled; the plan is recomputed from local data under the market
store's cross-process write lock immediately before sending, and any difference refuses with nothing sent; the
attempt's start is recorded before the request (each attempt number once, in market-context/lifecycle-attempts), its
outcome after; no redirect, retry or fallback; transfer and archive limits; and failed or uncertain outcomes stay
visible. A kept package is never imported or evaluated by this: those are separate explicit actions. Reads only read.
"""
from datetime import date, datetime
import hashlib
import json

from . import market_package, market_store
from .assessment import FRED_OUTCOME, _frozen, candidates, expected
from .data import ny_date
from .freeze_origins import Folders, LifecycleRefused
from .h15_release import POSTING, earliest_release, may_be_posted, release_words
from .lifecycle import SHA, _reader, now
from .market_calendar import expected_sessions
from .market_retrieval import REQUEST_HEADERS, SOURCE, USER_AGENT, ReleaseFetcher, _precise, _send, retrieval_status
from .registry import BOARD_H15
from .schema import utc
from .snapshots import verify_snapshot
from .store import canonical

PLAN_VERSION = "lifecycle-outcome-plan-0.2"  # 0.2: sessions awaiting the Board's release are not requested.
ATTEMPT_VERSION = "lifecycle-retrieval-attempt-0.1"
RESULT_VERSION = "lifecycle-retrieval-result-0.1"
MAX_HYPOTHESES = 20
NOTE = ("One approved request downloads the Board's whole release package once; it serves every selected hypothesis, "
        "and later selections reuse it locally. It holds only what the Board has published when it is received. "
        "Sessions on or after today are never requested, nor sessions the Board cannot have posted yet. A kept package "
        "is then imported as a hypothesis's outcome only by an explicit import, and assessed only by an explicit "
        "approval.")


def _selected(ids: object, folders: Folders, moment: datetime) -> list[dict]:
    """The selected frozen hypotheses with what each needs and which verified snapshots can serve it. Reads only."""
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_HYPOTHESES or len(set(map(str, ids))) != len(ids) or \
            not all(isinstance(item, str) and SHA.fullmatch(item) for item in ids):
        raise LifecycleRefused(422, f"Select between 1 and {MAX_HYPOTHESES} different frozen hypotheses")
    connection = _reader(folders)
    try:
        items = []
        for hypothesis_id in sorted(ids):
            hypothesis, stored, baseline_id, _ = _frozen(connection, hypothesis_id)
            try:
                baseline = verify_snapshot(connection, baseline_id)
            except ValueError as exc:
                raise LifecycleRefused(409, f"{stored['event']['headline']}: the baseline bound at freeze does not "
                                            f"verify ({exc})") from None
            if baseline.provider != BOARD_H15:
                raise LifecycleRefused(409, f"{stored['event']['headline']}: {FRED_OUTCOME}")
            window = expected(hypothesis, moment)
            serving = [(item["snapshot_id"], {sid: (entry["classified_from"], entry["classified_through"])
                                              for sid, entry in item["summary"]["coverage"].items()})
                       for item in candidates(connection, hypothesis, baseline, moment) if item["usable"]]
            items.append({"hypothesis_id": hypothesis_id, "headline": stored["event"]["headline"],
                          "published_date": ny_date(hypothesis.event.published_at),
                          "latest_target": date.fromisoformat(window["latest_expected_target"]),
                          "baseline_received_at": baseline.retrieved_at, "serving": serving})
        return items
    finally:
        connection.close()


def _snapshot_holds(coverage: dict, day: date) -> bool:
    return all(start <= day.isoformat() <= through for start, through in coverage.values())


def plan(items: list[dict], found: list, moment: datetime, sessions=expected_sessions) -> dict:
    """The missing past sessions of these hypotheses and the one request (or none) that covers them."""
    today = ny_date(moment)
    packages = [retrieval for retrieval in found if retrieval.origin == "package"]
    rows, missing, future, awaiting = [], set(), set(), set()
    reused_snapshots, reused_packages = {}, {}
    for item in items:
        days = sorted(day for day in sessions(item["published_date"], item["latest_target"])
                      if item["published_date"] <= day <= item["latest_target"])
        past = [day for day in days if day < today]
        held, lacking, unposted = [], [], []
        for day in past:
            snapshot = next((sid for sid, coverage in item["serving"] if _snapshot_holds(coverage, day)), None)
            package = None if snapshot else next(
                (retrieval for retrieval in packages if retrieval.states(day) and
                 datetime.fromisoformat(retrieval.provenance["received_at"]) >= item["baseline_received_at"]), None)
            if snapshot:
                reused_snapshots.setdefault(snapshot, set()).add(item["hypothesis_id"])
                held.append(day)
            elif package:
                reused_packages.setdefault(package.provenance["package_id"], set()).add(item["hypothesis_id"])
                held.append(day)
            elif may_be_posted(day, moment):
                lacking.append(day)
            else:
                unposted.append(day)
        missing |= set(lacking)
        awaiting |= set(unposted)
        future |= {day for day in days if day >= today}
        rows.append({"hypothesis_id": item["hypothesis_id"], "headline": item["headline"],
                     "required_from": item["published_date"].isoformat(),
                     "required_through": item["latest_target"].isoformat(), "past_sessions": len(past),
                     "held_sessions": len(held), "missing_sessions": [day.isoformat() for day in lacking],
                     "awaiting_release": [day.isoformat() for day in unposted],
                     "future_sessions": [day.isoformat() for day in days if day >= today]})
    missing_days, awaiting_days = sorted(missing), sorted(awaiting)
    request = None
    if missing_days:  # The whole release, whatever is missing: there is no smaller download of this source.
        request = {"url": market_package.PACKAGE_URL, "download": "full_release_package",
                   "missing_sessions": len(missing_days), "missing_from": missing_days[0].isoformat(),
                   "missing_to": missing_days[-1].isoformat()}
    identity = {"plan_version": PLAN_VERSION, "source": SOURCE["id"],
                "hypotheses": [{key: row[key] for key in ("hypothesis_id", "required_from", "required_through")}
                               for row in rows],
                "missing": [day.isoformat() for day in missing_days],
                "awaiting": [day.isoformat() for day in awaiting_days], "url": request["url"] if request else None}
    plan_sha = hashlib.sha256(canonical(identity).encode("utf-8")).hexdigest()
    return {"plan_version": PLAN_VERSION, "plan_sha256": plan_sha, "as_of": today.isoformat(), "source": SOURCE,
            "hypotheses": rows, "missing_sessions": [day.isoformat() for day in missing_days],
            "awaiting_release": [{"session": day.isoformat(), "obtainable_from": release_words(earliest_release(day))}
                                 for day in awaiting_days],
            "release_rule": f"{POSTING[0].upper()}{POSTING[1:]}; a holiday or a closed Board delays it.",
            "future_sessions": sorted(day.isoformat() for day in future),
            "reuse": {"snapshots": [{"snapshot_id": sid, "hypotheses": sorted(ids)}
                                    for sid, ids in sorted(reused_snapshots.items())],
                      "packages": [{"package_id": pid, "hypotheses": sorted(ids), "needs_import": True}
                                   for pid, ids in sorted(reused_packages.items())]},
            "requests": 1 if request else 0, "request": request, "note": NOTE}


def attempts(folders: Folders, plan_sha: str | None = None) -> list[dict]:
    """Recorded lifecycle attempts, oldest first (one plan's when named). Reads only."""
    return [entry for entry in market_store.read_attempts(folders.market, market_store.LIFECYCLE_ATTEMPTS,
                                                         (ATTEMPT_VERSION,))
            if plan_sha is None or entry["plan_sha256"] == plan_sha]


def plan_view(body: dict, folders: Folders, fetcher: ReleaseFetcher | None, clock=now) -> dict:
    """The plan for the selected hypotheses, its next attempt number, its attempts and whether sending is enabled."""
    if not isinstance(body, dict) or set(body) != {"hypotheses"}:
        raise LifecycleRefused(422, "A retrieval preview names exactly the selected hypotheses")
    moment = utc(clock())
    items = _selected(body["hypotheses"], folders, moment)
    found, problems, _ = market_store.local_data(folders.market, None)
    result = plan(items, found, moment)
    used = market_store.numbers_used(folders.market, result["plan_sha256"], market_store.LIFECYCLE_ATTEMPTS)
    return {**result, "next_attempt": len(used) + 1, "attempts": attempts(folders, result["plan_sha256"]),
            "retrieval": retrieval_status(fetcher), "store_problems": problems, "provider_called": False,
            "written": False}


def dispatch(body: bytes, folders: Folders, fetcher: ReleaseFetcher | None, clock=now) -> dict:
    """Send one approved request, at most once per attempt number, after checking the plan again under the lock."""
    try:
        approval = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        approval = None
    if not isinstance(approval, dict) or set(approval) != {"plan_sha256", "hypotheses", "attempt"} or \
            not isinstance(approval["plan_sha256"], str) or not SHA.fullmatch(approval["plan_sha256"]) or \
            type(approval["attempt"]) is not int or approval["attempt"] < 1:
        raise LifecycleRefused(422, "An approval names exactly the plan's SHA-256, its hypotheses and the attempt number")
    if fetcher is None:
        raise LifecycleRefused(409, retrieval_status(None)["detail"])
    store = folders.market
    store.mkdir(parents=True, exist_ok=True)
    try:
        with market_store.write_lock(store):
            moment = utc(clock())
            items = _selected(approval["hypotheses"], folders, moment)  # The local data immediately before.
            found, _ = market_store.retrievals(store, None)
            current = plan(items, found, moment)
            if current["plan_sha256"] != approval["plan_sha256"]:
                raise LifecycleRefused(409, "The local data or the plan changed since the preview, so nothing was "
                                            "requested; preview the retrieval again")
            if current["requests"] == 0 and current["awaiting_release"]:
                first = current["awaiting_release"][0]
                raise LifecycleRefused(409, f"Nothing can be obtained yet: {first['session']} has ended, but the "
                                            f"Board's release can state it no earlier than {first['obtainable_from']}, "
                                            "so nothing was requested")
            if current["requests"] == 0:
                raise LifecycleRefused(409, "Nothing is missing: every past session the selected hypotheses need is "
                                            "already held, so nothing was requested")
            plan_sha, number = current["plan_sha256"], approval["attempt"]
            used = market_store.numbers_used(store, plan_sha, market_store.LIFECYCLE_ATTEMPTS)
            if number != len(used) + 1:
                raise LifecycleRefused(409, f"Attempt {number} of this work was already started; nothing was requested "
                                            "again. Read its outcome; another attempt needs its own approval")
            request = current["request"]
            selected = [row["hypothesis_id"] for row in current["hypotheses"]]
            started_at = clock()
            client = {"user_agent": USER_AGENT, "transport": fetcher.label, "request_headers": REQUEST_HEADERS}
            try:
                market_store.write_exclusive(market_store.started_path(store, plan_sha, number,
                                                                       market_store.LIFECYCLE_ATTEMPTS), {
                    "attempt_version": ATTEMPT_VERSION, "plan_sha256": plan_sha, "number": number,
                    "plan_version": PLAN_VERSION, "hypotheses": selected, "source": SOURCE["id"], "url": request["url"],
                    "download": request["download"], "missing_sessions": request["missing_sessions"],
                    "missing_from": request["missing_from"], "missing_to": request["missing_to"],
                    "started_at": _precise(started_at), "client": client, "note": "Recorded before the request was sent."})
            except FileExistsError:
                raise LifecycleRefused(409, f"Attempt {number} of this work was already started; nothing was "
                                            "requested again") from None
            method = (f"Approved in this app's Hypotheses page: attempt {number} of lifecycle outcome plan {plan_sha}, "
                      "sent by its market retrieval (httpx; TLS verified, no redirect, no retry, no cookie).")
            outcome = _send(fetcher, store, plan_sha, number, {"plan_version": PLAN_VERSION, "plan_sha256": plan_sha,
                                                               "attempt": number, "hypotheses": selected},
                            method, started_at, client, clock)
            outcome["attempt_version"] = ATTEMPT_VERSION
            market_store.write_exclusive(market_store.outcome_path(store, plan_sha, number,
                                                                   market_store.LIFECYCLE_ATTEMPTS), outcome)
    except market_store.StoreRefused as exc:
        raise LifecycleRefused(exc.status, str(exc)) from None
    return {"result_version": RESULT_VERSION, "plan_sha256": plan_sha, "attempt": number, "hypotheses": selected,
            "outcome": outcome["outcome"], "detail": outcome["detail"], "package_id": outcome["package_id"],
            "validation": outcome["validation"], "provider_called": True, "retries": 0, "imported": False,
            "evaluated": False}


def attempt_state(plan_sha: str, number: str, folders: Folders) -> dict:
    """One attempt's records, for a lost reply: started or not, and its outcome or that none is recorded. Reads only."""
    if not isinstance(plan_sha, str) or not SHA.fullmatch(plan_sha) or not str(number).isdigit():
        raise LifecycleRefused(404, "Unknown retrieval attempt")
    found = next((entry for entry in attempts(folders, plan_sha) if entry["number"] == int(number)), None)
    if found is None:
        return {"result_version": RESULT_VERSION, "plan_sha256": plan_sha, "attempt": int(number),
                "state": "not_started", "detail": "No attempt with this number was started; nothing was requested by "
                                                  "it.", "written": False}
    if found["outcome"] is None:
        return {"result_version": RESULT_VERSION, "plan_sha256": plan_sha, "attempt": int(number), "state": "uncertain",
                "started": found["started"], "problem": found["problem"], "written": False,
                "detail": ("The attempt was started, but no outcome is recorded: whether the Board's server received "
                           "the request is not known. Nothing is sent again by itself.")}
    return {"result_version": RESULT_VERSION, "plan_sha256": plan_sha, "attempt": int(number), "state": "finished",
            "started": found["started"], "outcome": found["outcome"], "problem": found["problem"], "written": False,
            "detail": found["outcome"]["detail"]}
