"""Update runs (news-update-0.1): one operator-controlled pass from fresh source material to published stories and
their economic explanations, through the desk's existing steps, with a record of what each step did.

The operator acts step by step. Planning a run and reading it contact nothing and write nothing:

- ``plan``: the sources a refresh would request now (each connected, permitted publisher feed and, unless left out,
  the Event Inbox's official feeds), the ones it would not and why (a contact the publisher requires, a request less
  than COOLDOWN_MINUTES ago, an unreadable record), each step's request limits, the reference time, and whether paid
  preparation is enabled, with the part of a paid request's planning estimate that is known before its bytes are.
- ``start``: records the run, write-once (data/newsroom/updates/<run ID>/run.json): its cutoff (now), its reference
  time (the previous run's cutoff, else the latest coverage baseline's, else the newest successful retrieval), a
  coverage baseline of the listed stories (news_baseline), and the reports and stories held at the cutoff, so that what
  arrives later stays apart from what was held. The run ID comes from the operator's idempotency key, so a repeated
  start finds the same run; a second run cannot start while the latest one has not refreshed.
- ``refresh``: requests each planned source once (no retry; the plan's skips are decided again at that moment), then
  groups the new reports (news_stories.group, keyed by the run). Once per run, and only for the latest run: a second
  refresh is refused and requests nothing; one interrupted before its record was written is reported, never repeated.
- ``texts``: the permitted official publications' full texts for the run's stories (news_texts: each page once ever, at
  most news_texts.MAX_PER_RUN requests), once per run and before relevance and drafting, since a text changes a story's
  material and so outdates what was prepared from it.
- ``relevance``, ``context`` and ``briefs``: the existing batches and context bundles, for the run's stories only.
  Relevance (relevance_batches) is previewed for those not yet assessed for their current material, never for one whose
  last assessment failed (an operator retries that explicitly); a context bundle (econ_context) is built only from the
  structural options econ_context.candidates finds (a methodology series, the previous release, a topic's earlier
  developments), never from shared words; a brief batch (news_batches) holds those listed that need a brief or an
  explanation. A model batch saves each exact request with its planning estimate and sends nothing; its approval, an
  assisted batch's import and every publication stay the batches' own explicit actions, under their protections (each
  request at most once, ever; a failed or unknown attempt is never sent again).

run_stories classifies what a run brought, read beside the saved records now (the report, with its counts, steps, paid
plan and next actions, is news_update_report's). Arrivals are the reports first held after the cutoff, each by what its
feed states about its publication: after the reference time; before it (an older report discovered late); or not stated,
which stays unknown (a retrieval time never stands for a publication time). Each story an arrival reached is a new
development, a new development of an ongoing topic, additional reporting on a story held before, a story of older
reports discovered late, or one whose publication time is unknown; a held report whose words changed makes a revised
story. For each, the report gives its relevance, brief and explanation states and the next action; then what completed,
what needs attention (an editor's judgement, a publication decision, a paid approval, a limit) and what failed (a
source, an assessment, a draft, an import or a paid attempt: technical failures, never editorial judgements); the counts
before and after, apart from any earlier baseline; and the paid plan: every saved request of the run's model batches
with its planning estimate (not a billing ceiling) and its attempt's state.
"""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from . import (analysis_flow, brief_drafting, brief_stages, econ_context, event_inbox, market_store, news_baseline,
               news_batches, news_explanations, news_feeds, news_rank, news_reports, news_stories, news_texts,
               news_views, newsroom_store as ns, relevance_batches, relevance_requests as rr)
from .accounts import AccountsRefused

UPDATE_VERSION = "news-update-0.1"
RUN_ID = re.compile(r"update-[0-9a-f]{16}")
KEY = re.compile(r"[A-Za-z0-9_-]{8,70}")
COOLDOWN_MINUTES = 30
MAX_LABEL = 200
ARRIVALS = {
    "published_since": "Published after the reference time, as its feed states",
    "published_before": "Published before the reference time and first held now: an older report discovered late",
    "time_unknown": "Its feed states no usable publication time: first held now, published at an unknown time",
}
KINDS = {
    "new_development": "A new story, first reported after the reference time",
    "topic_development": "A new development in an ongoing topic",
    "additional_reporting": "Additional reporting on a story held before this run",
    "discovered_late": "A new story of reports published before the reference time, discovered now",
    "time_unknown": "A new story whose sources state no publication time",
    "revised": "A report held before changed its headline or excerpt",
}
PAID_STATEMENT = ("Planning, starting, refreshing, previewing and reading send nothing billed. A model batch saves each "
                  "exact request with a planning estimate: an upper bound on output at max_tokens with an estimated "
                  "input count, not a billing ceiling (prices can change, and a refused or failed reply may still be "
                  "billed). Sending needs the batch's own approval repeating its total; each request is sent at most "
                  "once, ever, and a failed or unknown attempt is never sent again. A brief and its explanation take "
                  "two requests: stage 2 is prepared from a validated stage 1 and approved in a later batch.")


def _root(desk: news_views.Desk) -> Path:
    return desk.newsroom.path.parent / "updates"


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------- the plan

def _source_row(source: event_inbox.Source, kind: str, folder: Path, now: datetime, contact: bool) -> dict:
    state, record, problem = event_inbox.read_record(folder, source.key, source)
    attempt = (record or {}).get("last_attempt")
    success = (record or {}).get("last_success")
    last = (attempt["finished_at"] or attempt["started_at"]) if attempt else None
    row = {"source": source.key, "label": source.label, "publisher": source.publisher, "kind": kind,
           "last_attempt_at": last, "last_success_at": success["retrieved_at"] if success else None,
           "terms_url": source.terms_url, "action": "request", "reason": None}
    if state == "unreadable":
        row.update(action="unreadable", reason=f"Its record cannot be read ({problem}); move it aside to refresh it.")
    elif source.contact_required and not contact:
        row.update(action="needs_contact", reason=(
            f"{source.publisher} asks automated requests to carry a contact; set {event_inbox.CONTACT_ENV} first."))
    elif last and attempt["outcome"] != "not_requested" and now - _at(last) < timedelta(minutes=COOLDOWN_MINUTES):
        allowed = _at(last) + timedelta(minutes=COOLDOWN_MINUTES)
        row.update(action="cooldown", reason=(f"Requested at {last}; an update requests a source at most once every "
                                              f"{COOLDOWN_MINUTES} minutes (next from {ns.stamp(allowed)})."))
    return row


def sources(desk: news_views.Desk, now: datetime, official: bool = True,
            inbox_contact: bool | None = None) -> list[dict]:
    """Each source an update's refresh would consider, in order: the official feeds, then the publisher feeds."""
    environment = bool(os.environ.get(event_inbox.CONTACT_ENV, "").strip())
    feeds_contact = bool(desk.fetcher.contact) if desk.fetcher is not None else environment
    rows = [_source_row(source, "official", desk.inbox, now, environment if inbox_contact is None else inbox_contact)
            for source in event_inbox.SOURCES.values() if official and source.key in desk.publishers]
    rows += [_source_row(publisher.feed, "publisher", desk.feeds, now, feeds_contact)
             for publisher in news_feeds.refreshable(desk.publishers)]
    return rows


def reference(desk: news_views.Desk) -> dict:
    """The time arrivals are compared with: the previous run's cutoff, else the latest baseline's, else the newest
    successful retrieval held."""
    runs = listing(desk)
    if runs:
        return {"at": runs[-1]["started_at"], "basis": "run", "id": runs[-1]["run_id"],
                "statement": f"The previous update run's cutoff ({runs[-1]['run_id']})."}
    baselines = news_baseline.listing(desk)
    if baselines:
        return {"at": baselines[-1]["cutoff"], "basis": "baseline", "id": baselines[-1]["baseline_id"],
                "statement": f"The latest coverage baseline's cutoff ({baselines[-1]['baseline_id']})."}
    pool = news_reports.pool(desk.inbox, desk.feeds, desk.publishers, desk.index)
    held = sorted(row["last_success_at"] for row in pool["sources"] if row["last_success_at"])
    if held:
        return {"at": held[-1], "basis": "retrieval", "id": None,
                "statement": "The newest successful retrieval held before this run."}
    return {"at": None, "basis": "none", "id": None, "statement": "Nothing was held before this run."}


def plan(desk: news_views.Desk, now: datetime, official: bool = True) -> dict:
    """What an update would request and prepare now, with its limits. Reads only."""
    rows = sources(desk, now, official)
    drafting = brief_drafting.status(desk.drafting)
    output = lambda tokens: round(tokens * analysis_flow.PRICES["output_usd_per_mtok"] / 1_000_000, 4)  # noqa: E731
    latest = latest_run(desk)
    return {"update_version": UPDATE_VERSION, "as_of": ns.stamp(now), "official": official, "sources": rows,
            "requests": {"feeds": sum(1 for row in rows if row["action"] == "request"),
                         "skipped": sum(1 for row in rows if row["action"] != "request")},
            "limits": {"feed_requests_per_source": 1, "retries": 0, "cooldown_minutes": COOLDOWN_MINUTES,
                       "text_requests": news_texts.MAX_PER_RUN, "relevance_batch": relevance_batches.MAX_LIMIT,
                       "brief_batch": news_batches.MAX_LIMIT},
            "reference": reference(desk),
            "paid": {"enabled": drafting["enabled"], "detail": drafting["detail"], "model": drafting["model"],
                     "prices": {key: analysis_flow.PRICES[key] for key in ("input_usd_per_mtok", "output_usd_per_mtok",
                                                                           "read_on")},
                     "relevance": {"max_tokens": rr.MAX_TOKENS, "output_at_max_usd": output(rr.MAX_TOKENS)},
                     "briefs": {"max_tokens": sum(brief_stages.MAX_TOKENS.values()),
                                "output_at_max_usd": output(sum(brief_stages.MAX_TOKENS.values())),
                                "stages": [{"stage": stage, "name": brief_stages.NAMES[stage], "max_tokens": tokens,
                                            "output_at_max_usd": output(tokens)}
                                           for stage, tokens in brief_stages.MAX_TOKENS.items()]},
                     "statement": PAID_STATEMENT},
            "open_run": latest["run_id"] if latest and not latest["refreshed"] else None,
            "statement": ("Planning reads saved records only: nothing is requested, sent or written. Each request's "
                          "input part is estimated from its exact bytes when its batch is previewed.")}


# ---------------------------------------------------------------- runs

def listing(desk: news_views.Desk) -> list[dict]:
    """The recorded runs, oldest first (reads only)."""
    root = _root(desk)
    rows = []
    for folder in sorted(root.glob("update-*")) if root.is_dir() else []:
        run = _read(folder / "run.json")
        if run is not None:
            rows.append({"run_id": run["run_id"], "label": run["label"], "started_at": run["started_at"],
                         "refreshed": (folder / "refresh-started.json").exists(),
                         "reference": run["reference"]["at"]})
    return sorted(rows, key=lambda row: (row["started_at"], row["run_id"]))


def latest_run(desk: news_views.Desk) -> dict | None:
    runs = listing(desk)
    return runs[-1] if runs else None


def load(desk: news_views.Desk, run_id: object) -> dict:
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
    run = _read(_root(desk) / run_id / "run.json")
    if run is None:
        raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
    return run


def run_id_for(key: str) -> str:
    """A run's stable ID, from the idempotency key of the action that started it."""
    return "update-" + hashlib.sha256(f"{UPDATE_VERSION}|{key}".encode("utf-8")).hexdigest()[:16]


def start(desk: news_views.Desk, now: datetime, actor: str, form: dict) -> tuple[dict, bool]:
    """Record a run (once per idempotency key): its cutoff, reference time, baseline and what was held."""
    label, key, official = form.get("label"), form.get("idempotency_key"), form.get("official", True)
    if not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL:
        raise AccountsRefused(422, "invalid_request", f"A run's label is 1 to {MAX_LABEL} characters.")
    if not isinstance(key, str) or not KEY.fullmatch(key) or not isinstance(official, bool):
        raise AccountsRefused(422, "invalid_request", "idempotency_key is 8 to 70 letters, digits, - or _; official "
                                                      "is true or false.")
    run_id = run_id_for(key)
    folder = _root(desk) / run_id
    existing = _read(folder / "run.json")
    if existing is not None:
        return existing, False
    latest = latest_run(desk)
    if latest is not None and not latest["refreshed"]:
        raise AccountsRefused(409, "update_open", f"Update run {latest['run_id']} has not refreshed yet: refresh it "
                                                  "before starting another. Nothing was recorded.",
                              run_id=latest["run_id"])
    since = reference(desk)
    planned = plan(desk, now, official)
    found = news_views.world(desk, now)
    baseline, _ = news_baseline.record(desk, now, actor, f"Before update run {run_id}: {label.strip()}"[:MAX_LABEL])
    record = {"update_version": UPDATE_VERSION, "run_id": run_id, "label": label.strip(), "started_at": ns.stamp(now),
              "started_by": actor, "official": official, "reference": since, "baseline_id": baseline["baseline_id"],
              "reports_before": {entry: report["version_sha256"] for entry, report in found["pool"]["reports"].items()},
              "stories_before": {story_id: story["material"]["material_sha256"]
                                 for story_id, story in found["stories"].items()},
              "plan": {key: planned[key] for key in ("sources", "requests", "limits", "paid")},
              "statement": ("The run's cutoff, reference time and what was held then. Reports held later are this "
                            "run's arrivals; nothing held before is counted as one.")}
    try:
        market_store.write_exclusive(folder / "run.json", record)
    except FileExistsError:
        return _read(folder / "run.json"), False
    return record, True


def refresh(desk: news_views.Desk, run_id: str, actor: str, clock,
            inbox_fetcher: event_inbox.FeedFetcher | None = None) -> dict:
    """Request each planned source once and group what arrived: once per run, for the latest run only."""
    run = load(desk, run_id)
    latest = latest_run(desk)
    if latest is None or latest["run_id"] != run_id:
        raise AccountsRefused(409, "not_latest_run", "Only the latest update run refreshes; start a new run. Nothing "
                                                     "was requested.")
    folder = _root(desk) / run_id
    done = _read(folder / "refresh.json")
    if done is not None:
        raise AccountsRefused(409, "already_refreshed", "This run has refreshed its sources; a run refreshes once. "
                                                        "Nothing was requested.")
    official = inbox_fetcher or (event_inbox.FeedFetcher.from_environment() if run["official"] else None)
    feeds = desk.fetcher or news_feeds.fetcher_for(news_feeds.refreshable(desk.publishers))
    try:
        market_store.write_exclusive(folder / "refresh-started.json", {"run_id": run_id, "by": actor,
                                                                       "started_at": ns.stamp(clock())})
    except FileExistsError:
        raise AccountsRefused(409, "refresh_interrupted", "This run's refresh started earlier and recorded no outcome; "
                                                          "it is never repeated. Start a new run.") from None
    rows = sources(desk, clock(), run["official"], bool(official.contact) if official else None)
    outcomes = []
    for row in rows:
        shown = {key: row[key] for key in ("source", "publisher", "kind")}
        if row["action"] != "request":
            outcomes.append({**shown, "requested": False, "outcome": row["action"], "detail": row["reason"]})
            continue
        official_source = row["kind"] == "official"
        source = event_inbox.SOURCES[row["source"]] if official_source else desk.publishers[row["source"]].feed
        target, fetcher = (desk.inbox, official) if official_source else (desk.feeds, feeds)
        try:
            result = event_inbox.refresh_source(source, fetcher, target, clock)
        except (OSError, ValueError) as exc:  # One source's failure never stops the others.
            result = {"outcome": "failed", "detail": f"The refresh of this source stopped ({type(exc).__name__})."}
        outcomes.append({**shown, "requested": result["outcome"] not in ("not_requested", "skipped_unreadable"),
                         "outcome": result["outcome"], "detail": result.get("detail")})
    pool = news_reports.pool(desk.inbox, desk.feeds, desk.publishers, desk.index)["reports"]
    grouping, _ = news_stories.group(desk.newsroom, pool, news_reports.publisher_names(desk.publishers), actor,
                                     clock(), f"update-{run_id[7:]}-group")
    record = {"run_id": run_id, "by": actor, "finished_at": ns.stamp(clock()), "sources": outcomes,
              "requests": sum(1 for row in outcomes if row["requested"]),
              "grouping": {key: grouping[key] for key in ("new_stories", "grouped", "at")} | {
                  "joined": len(grouping["joined"])},
              "statement": "Each source was requested at most once, with no retry; grouping requested nothing."}
    market_store.write_exclusive(folder / "refresh.json", record)
    return record


def _step(desk: news_views.Desk, run_id: str, name: str, record: dict) -> dict:
    """Keep what a step did (write-once per name)."""
    try:
        market_store.write_exclusive(_root(desk) / run_id / "steps" / f"{name}.json", record)
    except FileExistsError:
        return _read(_root(desk) / run_id / "steps" / f"{name}.json") or record
    return record


def _steps(desk: news_views.Desk, run_id: str) -> list[dict]:
    folder = _root(desk) / run_id / "steps"
    rows = [_read(path) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []
    return sorted((row for row in rows if row), key=lambda row: (row["at"], row["step"]))


# ---------------------------------------------------------------- arrivals and the run's stories

def time_class(report: dict, since: str | None) -> str:
    """What a report's feed states about its publication, against the reference time."""
    if report["at_basis"] == "published":
        return "published_since" if since is None or _at(report["at"]) > _at(since) else "published_before"
    day = news_reports.stated_day(report["published"]) if report["at_basis"] == "dated" else None
    if day is not None:
        start = datetime.combine(date.fromisoformat(day), time(0), timezone.utc)
        if since is None or start > _at(since):
            return "published_since"
        if start + timedelta(days=1) <= _at(since):
            return "published_before"
    return "time_unknown"


def _arrival(report: dict, since: str | None) -> dict:
    return {**{key: report[key] for key in ("entry_id", "publisher", "role", "title", "link", "at", "at_basis",
                                            "first_seen_at")},
            "published": report["published"].get("utc") or report["published"].get("as_stated"),
            "class": time_class(report, since)}


def _next(story: dict, folded: dict, failed: dict) -> tuple[str, str, str | None]:
    """(tone, what happens next in words, the step that does it) for one of the run's stories."""
    relevance = story["relevance"]
    if not story["material"]["reports"]:
        return "attention", "An editor judges it: its publishers' terms allow no model to read it.", "editor"
    if relevance["failure"] is not None:  # Even when an earlier material's annotation still decides its state.
        return "failed", (f"Its assessment of its current material failed ({relevance['failure']['detail']}); it is "
                          "not retried by itself."), None
    if relevance_batches.why_selected(story) and relevance["basis"] != "editor":
        return "todo", "Assess its economic relevance.", "relevance"
    if relevance["state"] in ("needs_review", "insufficient"):
        return "attention", f"An editor decides its relevance: {relevance['explanation']}", "editor"
    if not news_rank.listed(story):
        return "done", "Assessed as outside the economic news; not listed.", None
    brief, explanation = news_batches.state_of(folded, story), news_explanations.state_of(folded, story, failed)
    if explanation == "failed":
        return "failed", "Its latest preparation failed; nothing is sent or imported again by itself.", None
    if brief == "drafted" or explanation == "drafted":
        return "attention", "A prepared version awaits the publication decision.", "publication"
    if news_batches.needs(folded, story, failed):
        return "todo", "Prepare its brief and economic explanation.", "briefs"
    if brief == "insufficient" or explanation == "insufficient":
        return "done", "Judged too thin for an explanation; the reason is shown to readers.", None
    return "done", "Published for its current material.", None


def run_stories(run: dict, found: dict, failed: dict) -> dict:
    """The run's arrivals and revisions, and every story they reached, classified, with its progress."""
    folded, since = found["folded"], run["reference"]["at"]
    before = run["reports_before"]
    reports = found["pool"]["reports"]
    arrivals = [_arrival(report, since) for entry, report in reports.items() if entry not in before]
    revised = [_arrival(report, since) for entry, report in reports.items()
               if entry in before and before[entry] != report["version_sha256"]]

    def story_of(entry_id: str) -> str | None:
        story_id = folded["entry_story"].get(entry_id)
        return ns.resolve_story(folded, story_id) if story_id else None

    held: dict[str, dict] = {}
    ungrouped = []
    for name, rows in (("arrivals", arrivals), ("revised", revised)):
        for row in rows:
            story_id = story_of(row["entry_id"])
            if story_id is None or story_id not in found["stories"]:
                if name == "arrivals":
                    ungrouped.append(row)
                continue
            held.setdefault(story_id, {"arrivals": [], "revised": []})[name].append(row)
    stories = []
    for story_id, rows in held.items():
        story = found["stories"][story_id]
        classes = {row["class"] for row in rows["arrivals"]}
        existed = story_id in run["stories_before"] or any(row["entry_id"] in before for row in story["reports"])
        if not rows["arrivals"]:
            kind = "revised"
        elif existed:
            kind = "additional_reporting"
        elif "published_before" in classes:
            kind = "discovered_late"
        elif "published_since" in classes:
            kind = "topic_development" if any(row["previous_at"] for row in story["topics"]) else "new_development"
        else:
            kind = "time_unknown"
        tone, action, step = _next(story, folded, failed)
        publication = story["publication"]
        stories.append({
            "story_id": story_id, "title": story["title"], "kind": kind, "kind_label": KINDS[kind],
            "first_at": story["first_at"], "first_basis": story["first_basis"], "latest_at": story["latest_at"],
            "latest_basis": story["latest_basis"], "arrivals": rows["arrivals"], "revised": rows["revised"],
            "newly_published": "published_since" in classes,
            "publishers": sorted({row["publisher"] for row in story["reports"]}),
            "topics": [{"topic_id": row["topic_id"], "title": row["title"]} for row in story["topics"]],
            "material": {"coverage": story["material"]["coverage"], "reports": len(story["material"]["reports"])},
            "relevance": {"state": story["relevance"]["state"], "basis": story["relevance"]["basis"]},
            "listed": news_rank.listed(story), "hot": story["rank"]["hot"],
            "brief_state": news_batches.state_of(folded, story),
            "explanation_state": news_explanations.state_of(folded, story, failed),
            "published_version": story["brief"]["version"] if story["brief"] else None,
            "authorship": story["brief"]["method"] if story["brief"] else None,
            "published_in_run": bool(story["brief"] and publication and publication["at"] > run["started_at"]),
            "tone": tone, "next": action, "step": step})
    stories.sort(key=lambda row: (row["latest_at"], row["story_id"]), reverse=True)
    return {"arrivals": arrivals, "revised": revised, "ungrouped": ungrouped, "stories": stories}


def _chosen(rows: list[dict], step: str, limit: int) -> tuple[list[str], list[str]]:
    wanted = [row["story_id"] for row in rows if row["step"] == step]
    return wanted[:limit], wanted[limit:]


def _limit(value: object, ceiling: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= ceiling:
        raise AccountsRefused(422, "invalid_request", f"A batch holds 1 to {ceiling} stories.")
    return value


# ---------------------------------------------------------------- the run's steps

def _context_of(desk: news_views.Desk, run_id: str, now: datetime) -> tuple[dict, dict, dict]:
    run = load(desk, run_id)
    if not (_root(desk) / run_id / "refresh.json").exists():
        raise AccountsRefused(409, "not_refreshed", "This run has not refreshed its sources yet.")
    found = news_views.world(desk, now)
    return run, found, run_stories(run, found, news_explanations.failures(desk.newsroom.path.parent))


def texts(desk: news_views.Desk, run_id: str, actor: str, clock, fetch=None, check: bool = False) -> dict:
    """The run's stories' permitted publication texts: what would be requested (``check``), or one retrieval."""
    run, found, held = _context_of(desk, run_id, clock())
    if desk.texts is None:
        raise AccountsRefused(409, "texts_unavailable", "This desk keeps no publication texts.")
    story_ids = [row["story_id"] for row in held["stories"] if row["material"]["reports"]]
    reports = news_texts.story_reports(found, story_ids, False, clock()) if story_ids else []
    planned = news_texts.plan(desk.texts, reports)
    requests = sum(1 for row in planned if row["action"] == "request")
    if check:
        return {"run_id": run_id, "plan": planned, "requests": requests, "limit": news_texts.MAX_PER_RUN,
                "statement": "Checked only: nothing was requested."}
    if (_root(desk) / run_id / "steps" / "texts.json").exists():
        raise AccountsRefused(409, "already_retrieved", "This run retrieved its texts once; use `news texts` for more.")
    done = news_texts.retrieve_all(desk.texts, reports, {key: publisher.attribution for key, publisher in
                                                         desk.publishers.items()},
                                   fetch or desk.text_fetcher or news_texts.fetcher(), clock)
    return _step(desk, run_id, "texts", {"step": "texts", "at": ns.stamp(clock()), "by": actor,
                                         "requests": sum(1 for row in done if row["requested"]),
                                         "outcomes": [{key: row.get(key) for key in ("entry_id", "outcome", "requested",
                                                                                     "detail")} for row in done]})


def relevance(desk: news_views.Desk, run_id: str, method: str, limit: int, actor: str, now: datetime) -> dict:
    """A relevance batch of the run's stories not yet assessed for their current material (never a failed one)."""
    _, found, held = _context_of(desk, run_id, now)
    chosen, left = _chosen(held["stories"], "relevance", _limit(limit, relevance_batches.MAX_LIMIT))
    if not chosen:
        raise AccountsRefused(409, "nothing_to_prepare", "None of this run's stories awaits a relevance assessment.")
    batch, created = relevance_batches.preview(desk, now, method, len(chosen), chosen, False, actor)
    step = _step(desk, run_id, f"relevance-{batch['batch_id']}", {
        "step": "relevance", "at": ns.stamp(now), "by": actor, "batch_id": batch["batch_id"], "method": method,
        "stories": chosen, "left": left, "estimated_max_usd_total": batch.get("estimated_max_usd_total")})
    return {"batch": batch, "created": created, "step": step}


def context(desk: news_views.Desk, run_id: str, actor: str, now: datetime) -> dict:
    """Context bundles for the run's stories that are listed and need a brief, from structural options only."""
    _, found, held = _context_of(desk, run_id, now)
    built, none = [], []
    for row in held["stories"]:
        story = found["stories"][row["story_id"]]
        if row["step"] != "briefs" or econ_context.current(desk, story) is not None:
            continue
        options = {item["option"] for item in econ_context.candidates(desk, found, row["story_id"])["candidates"]}
        if not options:
            none.append(row["story_id"])
            continue
        bundle, _ = econ_context.build(desk, found, row["story_id"], now, actor, [], "--topic-history" in options,
                                       None, use_methodology="--methodology" in options,
                                       use_earlier_release="--earlier-release" in options)
        built.append({"story_id": row["story_id"], "bundle_id": bundle["bundle_id"], "options": sorted(options),
                      "items": len(bundle["items"])})
    name = "context-" + ns.sha256_of([row["bundle_id"] for row in built] or [ns.stamp(now)])[:12]
    return _step(desk, run_id, name, {"step": "context", "at": ns.stamp(now), "by": actor, "built": built,
                                      "without_options": none, "statement": (
                                          "Built only from structural options (a methodology series, the previous "
                                          "release, a topic's earlier developments); a story without one has none.")})


def briefs(desk: news_views.Desk, run_id: str, method: str, limit: int, actor: str, now: datetime) -> dict:
    """A brief batch of the run's listed stories that need a brief or an economic explanation."""
    _, found, held = _context_of(desk, run_id, now)
    chosen, left = _chosen(held["stories"], "briefs", _limit(limit, news_batches.MAX_LIMIT))
    if not chosen:
        raise AccountsRefused(409, "nothing_to_prepare", "None of this run's listed stories needs a brief or an "
                                                         "explanation now.")
    batch, created = news_batches.preview(desk, now, method, len(chosen), chosen, actor)
    step = _step(desk, run_id, f"briefs-{batch['batch_id']}", {
        "step": "briefs", "at": ns.stamp(now), "by": actor, "batch_id": batch["batch_id"], "method": method,
        "stories": chosen, "left": left, "estimated_max_usd_total": batch.get("estimated_max_usd_total")})
    return {"batch": batch, "created": created, "step": step}
