"""The news desk's explicit commands (python -m second_order news ...).

Reading only: ``status`` (each source's freshness and the newsroom's counts), ``stories`` (IDs, material and brief
state), ``draft`` (the desk's $0 starting draft from a story's material), ``coverage`` (whether the important stories
have a current brief, and why not), ``baseline progress`` / ``baseline list`` and ``batch status`` / ``batch packet``.
Requesting a publisher, each explicitly and free: ``refresh`` (each connected publisher feed once; ``--official`` also
the Event Inbox's feeds, BLS only with the operator's contact) and ``texts`` (official publications' full text for named
or Hot now stories, at most 30 requests a run, each page once ever; ``--check`` requests nothing). Local writes:
``group``, ``upgrade`` (to the current version, after ``backup``), ``curate`` (a curation plan; ``--check`` writes
nothing), ``batch preview`` (records a batch; a paid one saves each exact request), ``batch import`` (an assistant's
drafts as AI-assisted versions), ``batch publish`` and ``baseline record`` (the listed stories' states at a cutoff,
write-once) and ``drafting preview`` (one story's two-stage model draft, brief-prompt-10: each stage's estimate and
state, and the next stage's exact request recorded, not sent). A billed request: only ``batch approve``, with the
batch's total repeated, and ``drafting approve``, with the one request's SHA-256 and estimate repeated, each with its
--approve-… flag and the key in the environment; each request is sent at most once, ever. A draft takes two such
approvals: stage 1 (the evidence and figures), then stage 2 (the interpretation and brief), prepared from the validated
stage 1. Like
the Admin desk's actions, these are the local operator's and are not counted against a server's usage policy.

Economic explanations are prepared by the same batches (``batch preview --backfill`` selects every listed story that
needs one, newest first, instead of Hot now's). ``context build`` records a story's context bundle from saved records,
the methodology library and the operator's own file (local; nothing is requested); ``context suggest`` (what a bundle
could hold, and why), ``context show`` and ``framework`` only read.

An update run (``update``, news_updates) connects these steps for fresh material: ``plan``, ``report`` and ``list`` only
read; ``start`` records the run's cutoff and what is held; ``refresh`` requests each planned source once and groups the
arrivals; ``texts`` retrieves the run's permitted publication texts once; ``relevance`` and ``briefs`` preview the
existing batches for the run's stories (sending nothing) and ``context`` builds bundles from structural options. Paid
approvals, imports and publication stay the batches' own commands, which the report names.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sqlite3

from . import event_inbox, news_admin_api, news_curation, news_feeds, news_reports, news_stories, news_views
from . import news_batches, news_index, news_matching, news_relevance_cli, news_texts, newsroom_store, story_briefs
from . import brief_drafting, econ_context, econ_framework, news_baseline, news_update_report, news_updates
from . import story_deeper
from .accounts import AccountsRefused

CLI_ACTOR = "local-operator"


def add_commands(commands: argparse._SubParsersAction) -> None:
    news = commands.add_parser("news", help="The news desk: status, stories, refresh, grouping, curation and backup")
    actions = news.add_subparsers(dest="news_action", required=True)
    actions.add_parser("status", help="Each source's freshness and the newsroom's counts (read-only)")
    stories = actions.add_parser("stories", help="The stories with their IDs, material and brief state (read-only)")
    stories.add_argument("--view", choices=("latest", "hot"), default="latest")
    stories.add_argument("--limit", type=int, default=40)
    draft = actions.add_parser("draft", help="A story's $0 starting draft from its material's own words (read-only)")
    draft.add_argument("story_id")
    curate = actions.add_parser("curate", help="Apply a curation plan file as the local operator (see news_curation)")
    curate.add_argument("--plan", type=Path, required=True, help="A news-curation-plan-0.1 JSON file")
    curate.add_argument("--check", action="store_true", help="Only check the plan; write nothing")
    refresh = actions.add_parser("refresh", help="Request each connected publisher feed once (explicit; keyless, free)")
    refresh.add_argument("--official", action="store_true",
                         help="Also request the Event Inbox's official feeds once each, as the Admin Inbox does")
    actions.add_parser("group", help="Put every report not yet in a story into one (local; nothing is requested)")
    actions.add_parser("upgrade", help=f"Bring an older newsroom store to {newsroom_store.SCHEMA_VERSION} "
                                       "(adds tables; keeps every row)")
    actions.add_parser("coverage", help="Brief coverage of Hot now's stories and of every story (read-only)")
    baseline = actions.add_parser("baseline", help="Record the listed stories' states at a cutoff; report progress")
    baseline_steps = baseline.add_subparsers(dest="baseline_action", required=True)
    baseline_steps.add_parser("record", help="Record a baseline now (write-once)").add_argument(
        "--label", required=True, help="What the baseline is for")
    baseline_steps.add_parser("progress", help="A baseline's stories then and now (read-only)").add_argument(
        "baseline_id")
    baseline_steps.add_parser("list", help="The recorded baselines (read-only)")
    batch = actions.add_parser("batch", help="Prepare briefs for the important stories in a bounded batch")
    steps = batch.add_subparsers(dest="batch_action", required=True)
    preview = steps.add_parser("preview", help="Select and record a batch; a paid one saves each exact request")
    preview.add_argument("--method", choices=("model", "assisted"), required=True)
    preview.add_argument("--limit", type=int, default=10)
    preview.add_argument("--story", action="append", default=[], help="A story ID (repeatable) instead of Hot now")
    preview.add_argument("--backfill", action="store_true",
                         help="Every listed story needing a brief or an economic explanation, newest first")
    for name, text in (("status", "Each item's state now (read-only)"),
                       ("packet", "The rules and material an assistant writes the drafts from (read-only)")):
        steps.add_parser(name, help=text).add_argument("batch_id")
    approve = steps.add_parser("approve", help="Send each saved request once (paid; needs the key)")
    approve.add_argument("batch_id")
    approve.add_argument("--estimated-max-usd-total", type=float, required=True)
    approve.add_argument("--approve-paid-requests", action="store_true", required=True)
    drafts = steps.add_parser("import", help="Save an assistant's drafts as AI-assisted versions")
    drafts.add_argument("batch_id")
    drafts.add_argument("--drafts", type=Path, required=True)
    drafts.add_argument("--assistant-tool", required=True, help="The AI assistant the drafts were written with")
    drafts.add_argument("--assistant-model", default=None, help="Its model, only when you know it")
    drafts.add_argument("--check", action="store_true", help="Check the drafts as an import would; save nothing")
    publish = steps.add_parser("publish", help="Publish each item's publishable new version")
    publish.add_argument("batch_id")
    publish.add_argument("--reason", required=True)
    publish.add_argument("--reviewed", action="store_true", help="Only if you read every version published here")
    context = actions.add_parser("context", help="A story's context bundle for its economic explanation (local)")
    context_steps = context.add_subparsers(dest="context_action", required=True)
    build = context_steps.add_parser("build", help="Record a bundle from saved records and your own items (once)")
    build.add_argument("story_id")
    build.add_argument("--with-story", action="append", default=[], help="Another story's permitted material")
    build.add_argument("--why", action="append", default=[], help="Why each --with-story is relevant (in order)")
    build.add_argument("--topic-history", action="store_true", help="The earlier developments of its topics")
    build.add_argument("--earlier-release", action="store_true", help="The previous release of the same series")
    build.add_argument("--methodology", action="store_true", help="The methodology library's passages for its series")
    build.add_argument("--supplied", type=Path, default=None, help=(
        "A JSON file {items: [{kind, role, source, url, published, as_of, retrieved, text, terms, relevance}]}"))
    context_steps.add_parser("show", help="The bundles built for a story (read-only)").add_argument("story_id")
    context_steps.add_parser("suggest", help="What a bundle could hold for a story, and why (read-only)"
                             ).add_argument("story_id")
    actions.add_parser("framework", help="The economic framework notes and their sources (read-only)")
    texts = actions.add_parser("texts", help="Retrieve official publications' full text for stories (explicit)")
    texts.add_argument("--story", action="append", default=[], help="A story ID (repeatable)")
    texts.add_argument("--hot", action="store_true", help="The stories in Hot now")
    texts.add_argument("--limit", type=int, default=news_texts.MAX_PER_RUN, help="Requests in this run, at most 30")
    texts.add_argument("--check", action="store_true", help="Say what would be reused or requested; request nothing")
    news_relevance_cli.add_commands(actions)
    index = actions.add_parser("index", help="Other publishers' coverage of a story, from the GDELT news index")
    index_steps = index.add_subparsers(dest="index_action", required=True)
    find = index_steps.add_parser("lookup", help="One request per story to the GDELT index (explicit; keyless, free)")
    find.add_argument("--story", action="append", required=True, help="A story ID (repeatable; 6 seconds apart)")
    find.add_argument("--words", nargs="+", default=None,
                      help="With one story: the query's words, chosen from its own headline or excerpt (2 or 3)")
    show = index_steps.add_parser("lookups", help="A story's lookups and what the matching rule accepted (read-only)")
    show.add_argument("story_id")
    index_steps.add_parser("status", help="The cooldown after GDELT's 429s and each story's kept coverage (read-only)")
    join = index_steps.add_parser("attach", help="Add a lookup's accepted articles to the story (local)")
    join.add_argument("story_id")
    join.add_argument("lookup_id")
    join.add_argument("--reason", required=True)
    match = actions.add_parser("match", help="Stories that may report one development: suggestions and decisions")
    match_steps = match.add_subparsers(dest="match_action", required=True)
    match_steps.add_parser("suggestions", help="Candidate pairs with their evidence (read-only)")
    decide = match_steps.add_parser("decide", help="Record a decision: same (merge), related (topic) or different")
    decide.add_argument("story_a")
    decide.add_argument("story_b")
    decide.add_argument("--decision", choices=news_matching.DECISIONS, required=True)
    decide.add_argument("--reason", required=True)
    decide.add_argument("--topic-id", default=None, help="related: an existing topic")
    decide.add_argument("--topic-title", default=None, help="related: a new topic's title")
    decide.add_argument("--assistant-tool", default=None, help="Decided with this AI assistant (both stories' material "
                                                                  "must allow use by a model)")
    decide.add_argument("--assistant-model", default=None, help="Its model, only when you know it")
    update = actions.add_parser("update", help="An update run: plan, refresh, arrivals, preparation and its report")
    update_steps = update.add_subparsers(dest="update_action", required=True)
    update_steps.add_parser("plan", help="What a run would request and prepare now (read-only)").add_argument(
        "--publishers-only", action="store_true", help="Leave out the Event Inbox's official feeds")
    begin = update_steps.add_parser("start", help="Record a run: its cutoff, reference time and what is held (once)")
    begin.add_argument("--label", required=True, help="What the run is for")
    begin.add_argument("--publishers-only", action="store_true", help="Leave out the Event Inbox's official feeds")
    update_steps.add_parser("list", help="The recorded runs (read-only)")
    for name, text in (("report", "The run's arrivals, stories, steps, counts, paid plan and next actions (read-only)"),
                       ("refresh", "Request each planned source once and group the arrivals (explicit; free; once)"),
                       ("context", "Context bundles for the run's stories from structural options (local)")):
        update_steps.add_parser(name, help=text).add_argument("run_id")
    run_texts = update_steps.add_parser("texts", help="The run's permitted publication texts (explicit; once)")
    run_texts.add_argument("run_id")
    run_texts.add_argument("--check", action="store_true", help="Say what would be requested; request nothing")
    for name, text, ceiling in (("relevance", "A relevance batch of the run's unassessed stories (records; sends "
                                              "nothing)", 40),
                                ("briefs", "A brief batch of the run's listed stories that need one (records; sends "
                                           "nothing)", 25)):
        step = update_steps.add_parser(name, help=text)
        step.add_argument("run_id")
        step.add_argument("--method", choices=("model", "assisted"), required=True)
        step.add_argument("--limit", type=int, default=ceiling, help=f"At most this many stories (1 to {ceiling})")
    drafting = actions.add_parser("drafting", help="One story's two-stage model draft: preview, approve each stage")
    drafting_steps = drafting.add_subparsers(dest="drafting_action", required=True)
    drafting_steps.add_parser("preview", help="Show both stages and record the next stage's exact request (sends "
                                              "nothing)").add_argument("story_id")
    send = drafting_steps.add_parser("approve", help="Send one previewed stage's request once (paid; needs the key)")
    send.add_argument("draft_id")
    send.add_argument("--request-sha256", required=True, help="The request's SHA-256, as the preview showed it")
    send.add_argument("--estimated-max-usd", type=float, required=True, help="The planning estimate the preview showed")
    send.add_argument("--approve-paid-request", action="store_true", required=True)
    backup = actions.add_parser("backup", help="Copy the newsroom store into a new file (SQLite online backup)")
    backup.add_argument("--to", type=Path, required=True, help="A file that does not exist yet")


def default_desk() -> news_views.Desk:
    return news_views.Desk(newsroom_store.open_at(newsroom_store.NEWSROOM_DIR), event_inbox.INBOX_DIR,
                           news_feeds.FEEDS_DIR, story_deeper.DEEPER_DIR, texts=news_texts.TEXTS_DIR,
                           index=news_index.INDEX_DIR)


def run(args: argparse.Namespace, desk: news_views.Desk | None = None,
        inbox_fetcher: event_inbox.FeedFetcher | None = None) -> dict:
    desk = desk or default_desk()
    now = datetime.now(timezone.utc)
    if args.news_action == "refresh":
        official = []
        if getattr(args, "official", False):
            done = event_inbox.refresh(desk.inbox, inbox_fetcher or event_inbox.FeedFetcher.from_environment())
            official = [{key: row[key] for key in ("source", "outcome", "detail")} for row in done["refreshed"]]
        publishers = news_admin_api.refreshable(desk)
        result = news_feeds.refresh(desk.feeds, desk.fetcher or news_feeds.fetcher_for(publishers), publishers)
        return {"official": official, "refreshed": result["refreshed"],
                "sources": [{key: row[key] for key in ("key", "state")} for row in result["sources"]]}
    if args.news_action == "group":
        reports = news_reports.pool(desk.inbox, desk.feeds, desk.publishers, desk.index)["reports"]
        summary, _ = news_stories.group(desk.newsroom, reports, news_reports.publisher_names(desk.publishers),
                                        CLI_ACTOR, now, f"cli-group-{secrets.token_hex(8)}")
        return {key: summary[key] for key in ("match_version", "grouped", "new_stories", "at")} | {
            "joined": len(summary["joined"])}
    if args.news_action == "stories":
        return news_curation.story_rows(desk, now, args.view, max(1, args.limit))
    if args.news_action == "draft":
        try:
            return news_curation.draft(desk, args.story_id, now)
        except AccountsRefused as exc:
            raise SystemExit(json.dumps({"error": str(exc)})) from None
    if args.news_action == "curate":
        try:
            actions = news_curation.read_plan(json.loads(args.plan.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise SystemExit(json.dumps({"error": f"The plan was not read: {exc}"})) from None
        if args.check:
            result = news_curation.check(desk, actions, now)
            failed = not all(row["ok"] for row in result["checked"])
        else:
            result = news_curation.apply(desk, actions, CLI_ACTOR, lambda: datetime.now(timezone.utc))
            failed = result["stopped"] is not None
        if failed:
            raise SystemExit(json.dumps(result, indent=2))
        return result
    if args.news_action == "texts":
        if not args.story and not args.hot:
            raise SystemExit(json.dumps({"error": "Name stories with --story, or choose --hot."}))
        found = news_views.world(desk, now)
        try:
            reports = news_texts.story_reports(found, args.story, args.hot, now)
        except ValueError as exc:
            raise SystemExit(json.dumps({"error": str(exc)})) from None
        if desk.texts is None:
            raise SystemExit(json.dumps({"error": "This desk keeps no publication texts."}))
        if args.check:
            rows = news_texts.plan(desk.texts, reports)
            return {"texts_version": news_texts.TEXTS_VERSION, "checked": rows, "requests": sum(
                1 for row in rows if row["action"] == "request"), "statement": "Checked only: nothing was requested."}
        limit = max(0, min(args.limit, news_texts.MAX_PER_RUN))
        done = news_texts.retrieve_all(desk.texts, reports, {key: publisher.attribution for key, publisher in
                                                             desk.publishers.items()},
                                       desk.text_fetcher or news_texts.fetcher(), limit=limit)
        return {"texts_version": news_texts.TEXTS_VERSION, "outcomes": done,
                "requests": sum(1 for row in done if row["requested"])}
    if args.news_action == "coverage":
        return news_batches.coverage(desk, now, _accounts())
    if args.news_action == "baseline":
        try:
            if args.baseline_action == "record":
                record, created = news_baseline.record(desk, now, CLI_ACTOR, args.label)
                return {"created": created, "baseline": record}
            if args.baseline_action == "progress":
                return news_baseline.progress(desk, args.baseline_id, now)
            return {"baselines": news_baseline.listing(desk)}
        except AccountsRefused as exc:
            raise SystemExit(json.dumps({"error": str(exc), "code": exc.code}, indent=2)) from None
    if args.news_action == "batch":
        return _batch(args, desk, now)
    if args.news_action == "context":
        return _context(args, desk, now)
    if args.news_action == "framework":
        found = econ_framework.framework()
        return {"framework_version": found["framework_version"], "framework_sha256": found["framework_sha256"],
                "statement": found["statement"], "subjects": econ_framework.SUBJECTS,
                "forms": econ_framework.FORMS, "respondents": econ_framework.RESPONDENTS,
                "notes": list(found["notes"].values())}
    if args.news_action == "relevance":
        return news_relevance_cli.run(args, desk, now)
    if args.news_action == "match":
        return _match(args, desk, now)
    if args.news_action == "update":
        return _update(args, desk, now, inbox_fetcher)
    if args.news_action == "drafting":
        return _drafting(args, desk)
    if args.news_action == "index":
        return _index(args, desk, now)
    if args.news_action == "upgrade":
        try:
            return desk.newsroom.upgrade()
        except AccountsRefused as exc:
            raise SystemExit(json.dumps({"error": str(exc)})) from None
    if args.news_action == "backup":
        if not desk.newsroom.exists():
            raise SystemExit(json.dumps({"error": f"No newsroom store exists at {desk.newsroom.path}"}))
        if args.to.exists():
            raise SystemExit(json.dumps({"error": f"{args.to} exists; a backup never overwrites a file"}))
        args.to.parent.mkdir(parents=True, exist_ok=True)
        source, target = sqlite3.connect(desk.newsroom.path), sqlite3.connect(args.to)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        return {"backup": str(args.to), "from": str(desk.newsroom.path)}
    found = news_views.world(desk, now)
    return {"sources": [{key: row[key] for key in ("source", "state", "last_success_at", "reports")}
                        for row in found["pool"]["sources"]],
            "newsroom": {"exists": found["folded"]["exists"], "path": str(desk.newsroom.path),
                         "stories": len(found["stories"]), "topics": len(found["topics"]),
                         "ungrouped_reports": len(found["ungrouped"]),
                         "published_briefs": sum(1 for story in found["stories"].values() if story["brief"])}}


def _context(args: argparse.Namespace, desk: news_views.Desk, now: datetime) -> dict:
    try:
        if args.context_action == "show":
            return {"context_version": econ_context.CONTEXT_VERSION, "story_id": args.story_id,
                    "bundles": econ_context.bundles(desk, args.story_id)}
        if args.context_action == "suggest":
            return econ_context.candidates(desk, news_views.world(desk, now), args.story_id)
        if len(args.why) != len(args.with_story):
            raise SystemExit(json.dumps({"error": "Give one --why for each --with-story, in the same order.",
                                         "code": "invalid_request"}, indent=2))
        supplied = json.loads(args.supplied.read_text(encoding="utf-8")) if args.supplied else None
        bundle, created = econ_context.build(desk, news_views.world(desk, now), args.story_id, now, CLI_ACTOR,
                                             list(zip(args.with_story, args.why)), args.topic_history, supplied,
                                             use_methodology=args.methodology,
                                             use_earlier_release=args.earlier_release)
    except AccountsRefused as exc:
        raise SystemExit(json.dumps({"error": str(exc), "code": exc.code}, indent=2)) from None
    except (OSError, ValueError) as exc:
        raise SystemExit(json.dumps({"error": str(exc)})) from None
    return {"created": created, "bundle": bundle}


def _index(args: argparse.Namespace, desk: news_views.Desk, now: datetime) -> dict:
    try:
        if args.index_action == "lookup":
            if args.words is not None and len(args.story) != 1:
                raise SystemExit(json.dumps({"error": "--words chooses the query of one story: name one --story.",
                                             "code": "invalid_request"}, indent=2))
            return {"index_version": news_index.INDEX_VERSION, "lookups": news_index.lookup_many(
                desk, args.story, lambda: datetime.now(timezone.utc), chosen=args.words)}
        if args.index_action == "lookups":
            return {"story_id": args.story_id, "lookups": news_index.lookups(desk.index, args.story_id)}
        if args.index_action == "status":
            return news_index.status(desk.index, now)
        result, created = news_index.attach(desk, args.story_id, args.lookup_id, {
            "reason": args.reason, "idempotency_key": f"cli-index-{secrets.token_hex(8)}"}, CLI_ACTOR, now)
    except AccountsRefused as exc:
        raise SystemExit(json.dumps({"error": str(exc), "code": exc.code}, indent=2)) from None
    return {"created": created, "attached": result}


def _match(args: argparse.Namespace, desk: news_views.Desk, now: datetime) -> dict:
    if args.match_action == "suggestions":
        return {"match_version": news_matching.MATCH_VERSION,
                "candidates": news_matching.candidates(news_views.world(desk, now), now)}
    try:
        if args.assistant_tool:
            method, preparation = "assisted", story_briefs.assistant_preparation(args.assistant_tool,
                                                                                args.assistant_model, CLI_ACTOR)
        else:
            method, preparation = "editor", {"editor": True}
        result, created = news_matching.decide(desk, args.story_a, args.story_b, {
            "decision": args.decision, "reason": args.reason, "topic_id": args.topic_id,
            "topic_title": args.topic_title, "idempotency_key": f"cli-match-{secrets.token_hex(8)}"},
            method, preparation, CLI_ACTOR, now)
    except AccountsRefused as exc:
        raise SystemExit(json.dumps({"error": str(exc), "code": exc.code}, indent=2)) from None
    return {"created": created, "decision": result}


def _update(args: argparse.Namespace, desk: news_views.Desk, now: datetime,
            inbox_fetcher: event_inbox.FeedFetcher | None) -> dict:
    clock = lambda: datetime.now(timezone.utc)  # noqa: E731
    action = args.update_action
    try:
        if action == "plan":
            return news_updates.plan(desk, now, not args.publishers_only)
        if action == "list":
            return {"runs": news_updates.listing(desk)}
        if action == "start":
            run, created = news_updates.start(desk, now, CLI_ACTOR, {
                "label": args.label, "idempotency_key": f"cli-update-{secrets.token_hex(8)}",
                "official": not args.publishers_only})
            return {"created": created, "run": {key: value for key, value in run.items()
                                                if key not in ("reports_before", "stories_before")}}
        if action == "report":
            return news_update_report.report(desk, args.run_id, now)
        if action == "refresh":
            return news_updates.refresh(desk, args.run_id, CLI_ACTOR, clock, inbox_fetcher)
        if action == "texts":
            return news_updates.texts(desk, args.run_id, CLI_ACTOR, clock, check=args.check)
        if action == "context":
            return news_updates.context(desk, args.run_id, CLI_ACTOR, now)
        step = news_updates.relevance if action == "relevance" else news_updates.briefs
        return step(desk, args.run_id, args.method, args.limit, CLI_ACTOR, now)
    except AccountsRefused as exc:
        raise SystemExit(json.dumps({"error": str(exc), "code": exc.code, **exc.extra}, indent=2)) from None


def _paid(desk: news_views.Desk) -> news_views.Desk:
    """The desk with the paid sender from the environment, or a refusal before anything is reserved or sent."""
    if desk.drafting is not None:
        return desk
    from dataclasses import replace
    from .paid_drafts import PaidSender, key_problem
    sender = PaidSender.from_environment()
    problem = key_problem(sender.api_key())
    if problem:
        raise SystemExit(json.dumps({"error": f"{problem}; nothing was sent."}))
    return replace(desk, drafting=sender)


def _story_now(desk: news_views.Desk, clock):
    def story_now(story_id: str) -> dict:
        found = news_views.world(desk, clock())
        if story_id not in found["stories"]:
            raise AccountsRefused(404, "not_found", f"{story_id} is not a current story.")
        return found["stories"][story_id]
    return story_now


def _drafting(args: argparse.Namespace, desk: news_views.Desk) -> dict:
    """One story's two-stage model draft (brief_drafting), as the desk's story panel does it: the preview records the
    next stage's exact request and sends nothing; an approval repeats that request's SHA-256 and estimate and sends it
    once, ever."""
    clock = lambda: datetime.now(timezone.utc)  # noqa: E731
    try:
        if args.drafting_action == "preview":
            return brief_drafting.preview(desk, _story_now(desk, clock)(args.story_id))
        desk = _paid(desk)
        result, sent = brief_drafting.approve(desk, args.draft_id, {
            "request_sha256": args.request_sha256, "approve_paid_request": args.approve_paid_request,
            "estimated_max_usd": args.estimated_max_usd}, _story_now(desk, clock), CLI_ACTOR, clock)
        return {**result, "sent": sent}
    except AccountsRefused as exc:
        raise SystemExit(json.dumps({"error": str(exc), "code": exc.code, **exc.extra}, indent=2)) from None


def _accounts():
    """The accounts store, when one exists and opens, for the readiness of credit terms (only read)."""
    from . import accounts
    if not accounts.ACCOUNTS_PATH.exists():
        return None
    try:
        return accounts.Accounts.open(accounts.ACCOUNTS_PATH)
    except AccountsRefused:
        return None


def _batch(args: argparse.Namespace, desk: news_views.Desk, now: datetime) -> dict:
    clock = lambda: datetime.now(timezone.utc)  # noqa: E731
    try:
        if args.batch_action == "preview":
            batch, created = news_batches.preview(desk, now, args.method, args.limit, args.story or None, CLI_ACTOR,
                                                  backfill=getattr(args, "backfill", False))
            return {"created": created, "batch": batch}
        if args.batch_action == "status":
            return news_batches.status(desk, args.batch_id, now)
        if args.batch_action == "packet":
            return news_batches.packet(desk, args.batch_id, now)
        if args.batch_action == "approve":
            if desk.drafting is None:
                from dataclasses import replace
                from .paid_drafts import PaidSender, key_problem
                sender = PaidSender.from_environment()
                problem = key_problem(sender.api_key())
                if problem:
                    raise SystemExit(json.dumps({"error": f"{problem}; nothing was sent."}))
                desk = replace(desk, drafting=sender)

            def story_now(story_id: str) -> dict:
                found = news_views.world(desk, clock())
                if story_id not in found["stories"]:
                    raise AccountsRefused(404, "not_found", f"{story_id} is not a current story.")
                return found["stories"][story_id]
            return news_batches.approve(desk, args.batch_id, {
                "batch_id": args.batch_id, "approve_paid_requests": args.approve_paid_requests,
                "estimated_max_usd_total": args.estimated_max_usd_total}, story_now, CLI_ACTOR, clock)
        if args.batch_action == "import":
            drafts = json.loads(args.drafts.read_text(encoding="utf-8"))
            return news_batches.import_drafts(desk, args.batch_id, drafts, args.assistant_tool, args.assistant_model,
                                              CLI_ACTOR, clock, check=getattr(args, "check", False))
        return news_batches.publish(desk, args.batch_id, {"reason": args.reason, "reviewed": args.reviewed},
                                    CLI_ACTOR, clock)
    except AccountsRefused as exc:
        raise SystemExit(json.dumps({"error": str(exc), "code": exc.code, **exc.extra}, indent=2)) from None
    except (OSError, ValueError) as exc:
        raise SystemExit(json.dumps({"error": str(exc)})) from None
