"""The current-news routes of user-api-0.4 (docs/news-usage-contract.md), added to the app by create_app.

Every route needs a signed-in, approved user (the app's access check, the account binding and the protective request
limits run before any route). The news, search, import and research-check payloads are the data owner's modules'
(user_news, publication_import, research_quality), called with the server-derived identity; this module adds the
interests (an account preference, kept as append-only versions in the accounts store), the counted search with its
request key, the counted import preview with the server's shared publication-request budget, and the limits view. A
read or a search never contacts a publisher or a model; only an explicit import preview may request one allowlisted
page, and only on a server started with publication import enabled.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Callable

from fastapi import FastAPI, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import accounts as acc, auth, publication_import, research_quality, usage, user_news, user_research
from .accounts import Accounts, AccountsRefused, Identity
from .analysis_flow import FlowRefused, strict_object
from .model_draft import strict_json
from .store import canonical

CONTRACT = user_research.CONTRACT
REQUEST_KEY = re.compile(r"[A-Za-z0-9_-]{8,80}")
SEARCH_FIELDS = ("query", "interests", "sources", "listing", "request_key")
MAX_SEARCH_BODY = 4_096
MAX_SMALL_BODY = 2_048
# The preview refusals that come after a request to the publisher, when the data module does not say (`requested`).
AFTER_REQUEST = ("publication_unavailable", "publication_unreadable", "publication_too_long",
                 "publication_time_conflict")
NO_FETCHER = ("This server is not set up to request publications, so nothing was requested. You can open the official "
              "page and paste its text into a new source instead.")


@dataclass(frozen=True)
class News:
    """The cached inbox and the import records, and the publication fetcher (None unless the server was started with
    publication import enabled; the transport is chosen at startup, never through the API). ``stories`` gives each
    grouped entry's story (news_views.story_index), so an entry's headline can open its story page."""
    folders: publication_import.Folders
    fetcher: publication_import.PublicationFetcher | None = None
    stories: Callable[[], dict[str, str]] | None = None


# ---------------------------------------------------------------- interests (an account preference)

def interests_state(accounts: Accounts, user_id: str) -> dict:
    vocabulary = user_news.vocabulary()
    with accounts.reading() as connection:
        row = connection.execute("SELECT * FROM news_interests WHERE user_id = ? ORDER BY version DESC LIMIT 1",
                                 (user_id,)).fetchone()
    return {"vocabulary_version": vocabulary["vocabulary_version"], "rule": vocabulary["rule"],
            "vocabulary": vocabulary["interests"], "selected": json.loads(row["interests"]) if row else [],
            "version": row["version"] if row else None, "saved_at": row["saved_at"] if row else None}


def save_interests(accounts: Accounts, user_id: str, form: dict, moment) -> tuple[dict, bool]:
    """Save the whole selection as a new version, unless another save happened since the page loaded
    (expected_version) or nothing changed."""
    selected = user_news.validate_interests(form["interests"])
    expected = form["expected_version"]
    if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int) or expected < 1):
        raise AccountsRefused(422, "invalid_request", "expected_version is null or the version the page loaded.")
    with accounts.writing() as connection:
        row = connection.execute("SELECT version, interests FROM news_interests WHERE user_id = ? ORDER BY version "
                                 "DESC LIMIT 1", (user_id,)).fetchone()
        current = row["version"] if row else None
        if current != expected:
            changed = AccountsRefused(409, "interests_changed", "Your interests were changed in another tab since this "
                                                                "page loaded. Nothing was saved.")
        elif row is not None and json.loads(row["interests"]) == selected:
            return None, False
        else:
            connection.execute("INSERT INTO news_interests (user_id, version, interests, saved_at) VALUES (?, ?, ?, ?)",
                               (user_id, (current or 0) + 1, json.dumps(selected), acc.stamp(moment)))
            return None, True
    changed.extra["interests"] = interests_state(accounts, user_id)
    raise changed


# ---------------------------------------------------------------- routes

def add_routes(app: FastAPI, context: user_research.UserResearch | None, check_write: Callable, read_body: Callable,
               news: News | None) -> None:
    accounts: Accounts | None = context.accounts if context else None

    def user(request: Request) -> Identity:
        identity = auth.identity_of(request)
        if context is None or news is None:
            raise auth.ContractError(503, "accounts_unavailable")
        if identity is None or identity.role != "user":  # The access check already refused; this is a second guard.
            raise auth.ContractError(403, "forbidden")
        return identity

    def call(action):
        try:
            return action()
        except AccountsRefused as exc:
            raise auth.ContractError(exc.status, exc.code, str(exc), **exc.extra) from None

    def gated() -> None:
        """News, interests and searches need a usage policy: without one nothing counted is allowed."""
        if usage.current_policy(accounts) is None:
            raise AccountsRefused(409, "no_usage_policy", usage.NO_POLICY)

    def form_of(body: bytes, fields: tuple[str, ...], label: str) -> dict:
        try:
            return strict_object(body, fields, label)
        except FlowRefused:
            raise auth.ContractError(422, "invalid_request", f"A {label} has exactly {', '.join(fields)}.") from None

    @app.get("/api/user/news")
    def get_news(request: Request, scope: str = Query(default="interests")) -> dict:
        identity = user(request)

        def read():
            gated()
            chosen = interests_state(accounts, identity.user_id)["selected"]
            return user_news.view(news.folders, identity, chosen, scope, news.stories() if news.stories else {})
        return {"contract": CONTRACT, "news": call(read)}

    @app.get("/api/user/news/interests")
    def get_interests(request: Request) -> dict:
        identity = user(request)
        call(gated)
        return {"contract": CONTRACT, "interests": interests_state(accounts, identity.user_id)}

    @app.post("/api/user/news/interests")
    async def post_interests(request: Request) -> Response:
        check_write(request, auth.USER_HEADER, "Account actions")
        identity = user(request)
        form = form_of(await read_body(request, MAX_SMALL_BODY, "interests"), ("interests", "expected_version"),
                       "interests selection")

        def save():
            gated()
            return save_interests(accounts, identity.user_id, form, context.clock())
        _, changed = await run_in_threadpool(call, save)
        return JSONResponse({"contract": CONTRACT, "interests": interests_state(accounts, identity.user_id),
                             "changed": changed}, status_code=201 if changed else 200)

    @app.post("/api/user/news/searches")
    async def post_search(request: Request) -> Response:
        check_write(request, auth.USER_HEADER, "Account actions")
        identity = user(request)
        form = form_of(await read_body(request, MAX_SEARCH_BODY, "search"), SEARCH_FIELDS, "search")
        key = form.pop("request_key")
        if not isinstance(key, str) or not REQUEST_KEY.fullmatch(key):
            raise auth.ContractError(422, "invalid_request", "request_key must be 8 to 80 letters, digits, - or _.")

        def search():
            user_news.validate_search(form)  # A refused query is never counted.
            digest = hashlib.sha256(canonical(form).encode("utf-8")).hexdigest()
            reservation = usage.reserve(accounts, identity.user_id, "search", context.clock(), request_key=key,
                                        payload_sha256=digest)
            try:
                found = user_news.search(news.folders, identity, form, news.stories() if news.stories else {})
            except BaseException:
                usage.release(accounts, reservation, "the search did not complete", context.clock())
                raise
            return found, not reservation.duplicate
        found, counted = await run_in_threadpool(call, search)
        quota = usage.quota_now(accounts, identity.user_id, "search", context.clock())
        return JSONResponse({"contract": CONTRACT, **found, "counted": counted, "quota": quota},
                            status_code=201 if counted else 200)

    @app.post("/api/user/news/imports")
    async def post_import(request: Request) -> Response:
        check_write(request, auth.USER_HEADER, "Account actions")
        identity = user(request)
        form = form_of(await read_body(request, MAX_SMALL_BODY, "import"), ("entry_id", "version_sha256"), "import")

        def preview():
            gated()
            # Refusals for an unknown, changed or unsupported entry come first, before anything is counted or requested;
            # like every preview refusal they say so (`requested`).
            try:
                needs = publication_import.needs_fetch(news.folders, form["entry_id"], form["version_sha256"])
            except AccountsRefused as exc:
                exc.extra.setdefault("requested", False)
                raise
            if needs and news.fetcher is None:
                raise AccountsRefused(409, "publication_unavailable", NO_FETCHER, paste_instead=True, requested=False)
            reservation = usage.reserve(accounts, identity.user_id, "import", context.clock(), fetch=needs)
            try:
                view, created = publication_import.prepare(news.folders, identity, form["entry_id"],
                                                           form["version_sha256"], news.fetcher, context.clock)
            except AccountsRefused as exc:
                requested = exc.extra.get("requested", needs and exc.code in AFTER_REQUEST)
                if not requested:
                    usage.release(accounts, reservation, f"refused before any request ({exc.code})", context.clock())
                raise
            if not created:
                usage.release(accounts, reservation, "the account's earlier preview of this version", context.clock())
            elif view["publication"]["retrieval"] == "reused":
                usage.release(accounts, reservation, "a kept copy was read; no request", context.clock(),
                              operations={"publication_fetch"})
            return view, created
        view, created = await run_in_threadpool(call, preview)
        quota = usage.quota_now(accounts, identity.user_id, "import", context.clock())
        return JSONResponse({"contract": CONTRACT, "import": view, "created": created, "quota": quota},
                            status_code=201 if created else 200)

    @app.get("/api/user/news/imports/{import_id}")
    def get_import(import_id: str, request: Request) -> dict:
        identity = user(request)
        return {"contract": CONTRACT,
                "import": call(lambda: publication_import.read(news.folders, identity, import_id, context.clock))}

    @app.post("/api/user/news/imports/{import_id}/confirmation")
    async def post_confirmation(import_id: str, request: Request) -> Response:
        check_write(request, auth.USER_HEADER, "Account actions")
        identity = user(request)
        body = await read_body(request, MAX_SMALL_BODY, "confirmation")
        try:
            payload = strict_json(body)
        except Exception:
            raise auth.ContractError(422, "invalid_request", "A confirmation is a JSON object.") from None
        done, created = await run_in_threadpool(call, lambda: publication_import.confirm(
            news.folders, context, identity, import_id, payload, context.clock))  # The source is counted there.
        return JSONResponse({"contract": CONTRACT, **done, "created": created}, status_code=201 if created else 200)

    @app.get("/api/user/limits")
    def get_limits(request: Request) -> dict:
        identity = user(request)
        return {"contract": CONTRACT,
                "limits": usage.limits_view(accounts, context.intake, identity.user_id, context.clock())}

    @app.get("/api/user/analyses/{analysis_id}/quality")
    def get_quality(analysis_id: str, request: Request) -> dict:
        identity = user(request)
        analysis = call(lambda: user_research.read_analysis(context, identity, analysis_id))["analysis"]
        return {"contract": CONTRACT, "quality": research_quality.for_user_analysis(analysis)}


def default_folders(inbox: Path, intake: Path) -> publication_import.Folders:
    """The import records beside the intake folder, so a server over another intake folder never reads this machine's
    import records."""
    return publication_import.Folders(inbox=inbox, imports=intake.parent / publication_import.IMPORTS_DIR.name)
