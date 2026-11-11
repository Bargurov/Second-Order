"""The stories routes of user-api-0.5 (docs/news-stories-contract.md), added to the app by create_app.

Every route needs a signed-in, approved user and a published usage policy, like the rest of the news
(docs/news-usage-contract.md); the access check, the account binding and the protective request limits run before any
route. Reads (the stories, a story with its shared brief, the topics, a topic, and what Go deeper would use) only read
saved records (news_views): no publisher is contacted, no model is called, nothing is counted or charged. The one write
is Go deeper (story_deeper): the person's explicit action, which saves the story's permitted material as their own
source and prepares its analysis, each counted once under the existing limits; it quotes, sends and charges nothing.
"""
from typing import Callable

from fastapi import FastAPI, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import auth, news_api, news_views, story_deeper, usage, user_research
from .accounts import AccountsRefused, Identity

CONTRACT = user_research.CONTRACT
MAX_BODY = 1_024


def add_routes(app: FastAPI, context: user_research.UserResearch | None, check_write: Callable, read_body: Callable,
               desk: news_views.Desk | None) -> None:

    def user(request: Request) -> Identity:
        identity = auth.identity_of(request)
        if context is None or desk is None:
            raise auth.ContractError(503, "accounts_unavailable")
        if identity is None or identity.role != "user":  # The access check already refused; this is a second guard.
            raise auth.ContractError(403, "forbidden")
        return identity

    def call(action):
        try:
            if usage.current_policy(context.accounts) is None:
                raise AccountsRefused(409, "no_usage_policy", usage.NO_POLICY)
            return action()
        except AccountsRefused as exc:
            raise auth.ContractError(exc.status, exc.code, str(exc), **exc.extra) from None

    @app.get("/api/user/news/stories")
    def get_stories(request: Request, view: str = Query(default="hot")) -> dict:
        identity = user(request)

        def read():
            chosen = news_api.interests_state(context.accounts, identity.user_id)["selected"]
            return news_views.stories_view(desk, view, chosen, context.clock())
        return {"contract": CONTRACT, "stories": call(read)}

    @app.get("/api/user/news/stories/{story_id}")
    def get_story(story_id: str, request: Request) -> dict:
        user(request)
        return {"contract": CONTRACT, "story": call(lambda: news_views.story_view(desk, story_id, context.clock()))}

    @app.get("/api/user/news/stories/{story_id}/deeper")
    def get_deeper(story_id: str, request: Request) -> dict:
        identity = user(request)
        return {"contract": CONTRACT, "deeper": call(lambda: story_deeper.preview(desk, context, identity, story_id,
                                                                                  context.clock()))}

    @app.post("/api/user/news/stories/{story_id}/deeper")
    async def post_deeper(story_id: str, request: Request) -> Response:
        check_write(request, auth.USER_HEADER, "Account actions")
        identity = user(request)
        body = await read_body(request, MAX_BODY, "deeper analysis")
        done, created = await run_in_threadpool(call, lambda: story_deeper.start(desk, context, identity, story_id,
                                                                                 body, context.clock()))
        return JSONResponse({"contract": CONTRACT, "deeper": done, "created": created},
                            status_code=201 if created else 200)

    @app.get("/api/user/news/topics")
    def get_topics(request: Request) -> dict:
        user(request)
        return {"contract": CONTRACT, "topics": call(lambda: news_views.topics_view(desk, context.clock()))}

    @app.get("/api/user/news/topics/{topic_id}")
    def get_topic(topic_id: str, request: Request) -> dict:
        user(request)
        return {"contract": CONTRACT, "topic": call(lambda: news_views.topic_view(desk, topic_id, context.clock()))}
