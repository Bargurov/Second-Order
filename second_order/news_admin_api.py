"""The News desk's routes (admin-api-0.4, docs/news-stories-contract.md section 6), added to the app by create_app.

Administrators only (the app's access check refuses anyone else first; a server without accounts is the local
operator's, as for every operator route). The desk view only reads. Each write is one explicit action from this
server's own page with the X-Second-Order-Admin header, recorded in the newsroom with the acting administrator, the
time, a reason where it decides something, and an idempotency key, so a double click or a lost reply never acts twice.
Only the feed refresh contacts anything: each connected publisher feed once, under the usage policy's refresh cooldown
and daily budget when the server has accounts. A model draft of a brief is brief_drafting's, behind its own cost
preview and approval.
"""
import threading
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import (accounts as acc, auth, brief_drafting, news_batch_api, news_desk, news_feeds, news_matching, news_reports,
               news_stories, news_texts, news_topics, news_update_api, news_views, relevance_api, story_briefs, usage)
from .accounts import AccountsRefused
from .analysis_flow import FlowRefused, strict_object

CONTRACT = auth.ADMIN_CONTRACT
MAX_BODY = 32_768


def refreshable(desk: news_views.Desk) -> list:
    """The publisher feeds a refresh requests: the registry's connected ones (and SYNTHETIC ones a test installed)."""
    return news_feeds.refreshable(desk.publishers)


def add_routes(app: FastAPI, accounts: acc.Accounts | None, desk: news_views.Desk, check_write: Callable,
               read_body: Callable, clock: Callable = acc.now, inbox_fetcher=None) -> None:
    refreshing = threading.Lock()  # One publisher refresh at a time; a second is refused, never queued.
    texting = threading.Lock()  # One publication-text retrieval at a time; a second is refused, never queued.

    def admin(request: Request) -> acc.Identity:
        identity = auth.identity_of(request)
        if identity is None or identity.role != "admin":  # The access check already refused; this is a second guard.
            raise auth.ContractError(403, "forbidden")
        return identity

    def call(action):
        try:
            return action()
        except AccountsRefused as exc:
            raise auth.ContractError(exc.status, exc.code, str(exc), **exc.extra) from None

    async def write(request: Request, fields: tuple[str, ...], label: str) -> tuple[acc.Identity, dict]:
        check_write(request, auth.ADMIN_HEADER, "Administrator actions")
        identity = admin(request)
        body = await read_body(request, MAX_BODY, label)
        try:
            return identity, strict_object(body, fields, label, MAX_BODY)
        except FlowRefused:
            raise auth.ContractError(422, "invalid_request", f"A {label} has exactly {', '.join(fields)}.") from None

    def reports() -> dict:
        return news_reports.pool(desk.inbox, desk.feeds, desk.publishers, desk.index)["reports"]

    def replied(result: dict, created: bool, name: str) -> Response:
        return JSONResponse({"contract": CONTRACT, name: result, "created": created},
                            status_code=201 if created else 200)

    @app.get("/api/admin/news")
    def get_desk(request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, "desk": call(lambda: news_desk.desk_view(
            desk, clock(), brief_drafting.status(desk.drafting)))}

    @app.post("/api/admin/news/feeds/refresh")
    async def post_refresh(request: Request) -> Response:
        identity, _ = await write(request, (), "refresh request")
        if not refreshing.acquire(blocking=False):
            raise auth.ContractError(409, "refresh_in_progress", "A refresh is already running; wait for it to finish.")
        try:
            reservation = None
            if accounts is not None:  # The usage policy's refresh cooldown and daily budget, shared with the Inbox.
                reservation = await run_in_threadpool(call, lambda: usage.reserve_refresh(accounts, identity.user_id,
                                                                                          clock()))
            publishers = refreshable(desk)
            fetcher = desk.fetcher or news_feeds.fetcher_for(publishers)
            result = await run_in_threadpool(news_feeds.refresh, desk.feeds, fetcher, publishers)
            if reservation is not None and not publishers:
                await run_in_threadpool(usage.release, accounts, reservation, "no publisher feed is connected", clock())
        finally:
            refreshing.release()
        return JSONResponse({"contract": CONTRACT, "refresh": result})

    @app.post("/api/admin/news/group")
    async def post_group(request: Request) -> Response:
        identity, form = await write(request, ("idempotency_key",), "grouping")
        result, created = await run_in_threadpool(call, lambda: news_stories.group(
            desk.newsroom, reports(), news_reports.publisher_names(desk.publishers), identity.user_id, clock(),
            form["idempotency_key"]))
        return replied(result, created, "grouping")

    @app.post("/api/admin/news/stories/{story_id}/merge")
    async def post_merge(story_id: str, request: Request) -> Response:
        identity, form = await write(request, ("into", "reason", "idempotency_key"), "merge")
        result, created = await run_in_threadpool(call, lambda: news_stories.merge(
            desk.newsroom, story_id, form, identity.user_id, clock()))
        return replied(result, created, "merge")

    @app.post("/api/admin/news/matches")
    async def post_match(request: Request) -> Response:
        identity, form = await write(request, ("story_a", "story_b", "decision", "reason", "topic_id", "topic_title",
                                               "idempotency_key"), "match decision")
        result, created = await run_in_threadpool(call, lambda: news_matching.decide(
            desk, form["story_a"], form["story_b"], form, "editor", {"editor": True}, identity.user_id, clock()))
        return replied(result, created, "match")

    @app.post("/api/admin/news/stories/{story_id}/detach")
    async def post_detach(story_id: str, request: Request) -> Response:
        identity, form = await write(request, ("entry_id", "reason", "idempotency_key"), "detach")
        result, created = await run_in_threadpool(call, lambda: news_stories.detach(
            desk.newsroom, story_id, form, reports(), identity.user_id, clock()))
        return replied(result, created, "detach")

    @app.post("/api/admin/news/stories/{story_id}/title")
    async def post_title(story_id: str, request: Request) -> Response:
        identity, form = await write(request, ("title", "reason", "idempotency_key"), "headline")
        result, created = await run_in_threadpool(call, lambda: news_stories.retitle(
            desk.newsroom, story_id, form, identity.user_id, clock()))
        return replied(result, created, "title")

    def story_now(story_id: str) -> dict:
        found = news_views.world(desk, clock())
        if story_id not in found["stories"]:
            raise AccountsRefused(404, "not_found", news_views.NOT_FOUND)
        return found["stories"][story_id]

    @app.get("/api/admin/news/stories/{story_id}/draft")
    def get_draft(story_id: str, request: Request) -> dict:
        """A $0 starting draft from the material's own words; nothing is recorded."""
        admin(request)

        def draft():
            story = story_now(story_id)
            return {"content": story_briefs.extract_draft(story, story["material"]), "method": "extract",
                    "material": story["material"], "recorded": False}
        return {"contract": CONTRACT, "draft": call(draft)}

    @app.post("/api/admin/news/stories/{story_id}/briefs")
    async def post_brief(story_id: str, request: Request) -> Response:
        identity, form = await write(request, ("content", "method", "based_on", "idempotency_key"), "brief version")
        result, created = await run_in_threadpool(call, lambda: story_briefs.add_version(
            desk.newsroom, story_id, form, story_now(story_id)["material"], identity.user_id, clock()))
        return replied(result, created, "brief")

    @app.post("/api/admin/news/stories/{story_id}/publication")
    async def post_publication(story_id: str, request: Request) -> Response:
        identity, form = await write(request, ("version", "reason", "idempotency_key"), "publication")
        result, created = await run_in_threadpool(call, lambda: story_briefs.publish(
            desk.newsroom, story_id, form, identity.user_id, clock()))
        return replied(result, created, "publication")

    @app.get("/api/admin/news/stories/{story_id}/texts")
    def get_texts(story_id: str, request: Request) -> dict:
        """What retrieving this story's publication texts would reuse or request; requests nothing."""
        admin(request)

        def planned():
            found = news_views.world(desk, clock())
            if desk.texts is None:
                raise AccountsRefused(409, "texts_unavailable", "This server keeps no publication texts.")
            reports = news_texts.story_reports(found, [story_now(story_id)["story_id"]], False, clock())
            return {"texts_version": news_texts.TEXTS_VERSION, "plan": news_texts.plan(desk.texts, reports)}
        return {"contract": CONTRACT, "texts": call(planned)}

    @app.post("/api/admin/news/stories/{story_id}/texts")
    async def post_texts(story_id: str, request: Request) -> Response:
        """One explicit retrieval of this story's publication texts: each needed page once, counted against the
        server's daily publication requests (refused whole, requesting nothing, when they do not fit)."""
        identity, _ = await write(request, (), "text retrieval")
        if not texting.acquire(blocking=False):
            raise auth.ContractError(409, "retrieval_in_progress", "A retrieval is already running; wait for it.")
        try:
            def run():
                if desk.texts is None:
                    raise AccountsRefused(409, "texts_unavailable", "This server keeps no publication texts.")
                found = news_views.world(desk, clock())
                reports = news_texts.story_reports(found, [story_now(story_id)["story_id"]], False, clock())
                needed = sum(1 for row in news_texts.plan(desk.texts, reports) if row["action"] == "request")
                reservation = usage.reserve_server_fetches(accounts, identity.user_id, needed, clock()) \
                    if accounts is not None and needed else None
                done = news_texts.retrieve_all(desk.texts, reports, {key: publisher.attribution for key, publisher
                                                                     in desk.publishers.items()},
                                               desk.text_fetcher or news_texts.fetcher(), clock)
                made = sum(1 for row in done if row["requested"])
                if reservation is not None and made < needed:  # Uncount the requests a kept copy made unneeded.
                    usage.release(accounts, usage.Reservation(reservation.event_ids[made:]),
                                  "fewer publication pages were requested than reserved", clock())
                return {"texts_version": news_texts.TEXTS_VERSION, "outcomes": done, "requests": made}
            result = await run_in_threadpool(call, run)
        finally:
            texting.release()
        return JSONResponse({"contract": CONTRACT, "texts": result})

    @app.post("/api/admin/news/stories/{story_id}/reviews")
    async def post_review(story_id: str, request: Request) -> Response:
        identity, form = await write(request, ("version", "note", "idempotency_key"), "review")
        result, created = await run_in_threadpool(call, lambda: story_briefs.review(
            desk.newsroom, story_id, form, identity.user_id, clock()))
        return replied(result, created, "review")

    @app.post("/api/admin/news/stories/{story_id}/assessment")
    async def post_assessment(story_id: str, request: Request) -> Response:
        identity, form = await write(request, ("material_sha256", "verdict", "reason", "idempotency_key"),
                                     "assessment")
        result, created = await run_in_threadpool(call, lambda: story_briefs.assess(
            desk.newsroom, story_id, form, story_now(story_id)["material"], identity.user_id, clock()))
        return replied(result, created, "assessment")

    @app.post("/api/admin/news/topics")
    async def post_topic(request: Request) -> Response:
        identity, form = await write(request, ("title", "summary", "reason", "idempotency_key"), "topic")
        result, created = await run_in_threadpool(call, lambda: news_topics.create(
            desk.newsroom, form, identity.user_id, clock()))
        return replied(result, created, "topic")

    @app.post("/api/admin/news/topics/{topic_id}/links")
    async def post_link(topic_id: str, request: Request) -> Response:
        identity, form = await write(request, ("story_id", "action", "label", "reason", "idempotency_key"), "link")
        result, created = await run_in_threadpool(call, lambda: news_topics.link(
            desk.newsroom, topic_id, form, identity.user_id, clock()))
        return replied(result, created, "link")

    @app.post("/api/admin/news/priorities")
    async def post_priority(request: Request) -> Response:
        identity, form = await write(request, ("target_kind", "target_id", "level", "until", "reason",
                                               "idempotency_key"), "priority")
        result, created = await run_in_threadpool(call, lambda: news_topics.prioritise(
            desk.newsroom, form, identity.user_id, clock()))
        return replied(result, created, "priority")

    brief_drafting.add_routes(app, desk, admin, call, write, story_now, clock)
    news_batch_api.add_routes(app, accounts, desk, admin, call, write, story_now, clock)
    relevance_api.add_routes(app, desk, admin, call, write, story_now, clock)
    news_update_api.add_routes(app, accounts, desk, admin, call, write, clock, refreshing, texting, inbox_fetcher)
