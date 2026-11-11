"""Local HTTP API and static Dossier client.

GET routes only read prepared files: they never evaluate, call a model or fetch market data.
Preparation is the explicit `python -m second_order prepare` action, and `python -m second_order
prepare-drafts` for saved drafts. Drafts are served whether or not Dossiers have been prepared.

Six explicit local actions write: capture an operator event, dispatch one zero-cost mock response,
send one explicitly approved paid request (only when the server was started with paid sending enabled;
see paid_drafts), publish an already recorded response for review, append a human review version, and
refresh the Event Inbox (see event_inbox: five fixed publisher feeds, requested once each; a refresh never
triages anything). Headline triage adds three (see triage_plan, triage_flow and triage_api): preview a selection of
inbox entries, which saves a request only when missing work needs one, approve one local simulated
response, and send one explicitly approved paid Claude Haiku 5.5 request (only when the server was
started with --enable-paid-triage). All of them accept only JSON from this server's own local page:
the Host must be a local address, the Origin must be this server's, and a route-specific custom header
that a cross-site page cannot send without a CORS preflight (never granted here) is required. GET routes
remain read-only and never contact a provider or a feed.
Every route, including GETs and static files, checks the local Host before reading anything. Plain local reads need
no Origin or custom action header; the additional same-origin checks remain mandatory for writes.

Drafts come from two sources with one owner each (see draft_catalog): prepare-drafts' folder and the
Tracker's tracker-drafts folder beside it. Reads merge them.

The case library (see case_library) is committed editorial content, read from content/case-library/ and served
read-only. It needs no prepared files or runtime records, and it never touches the store or research summaries.
Its market context (see market_context) is read from content/market-context/ and verified on every read: daily
Treasury yields shown as description, never fetched, refreshed or scored here. A case's enrichment (see
case_enrichments) is a separate committed file bound to the case's bytes, read with the record of its privately
retained sources; the retained copies are checked when present and never served.

Private market context for selected macro events (see event_context, market_store and market_retrieval) adds two
writes: confirming an Event Inbox entry's context date, and sending one explicitly approved request for the Board's
complete H.15 release package, from which the 2-year and 10-year yields are read, which only a server started with
--enable-market-retrieval sends. Their GET routes read the saved events, verified retrievals and kept packages only;
they never contact the Board, validate a package or write anything.

The lifecycle (see lifecycle and lifecycle_api) adds four explicit writes for one store, whose path the server is
started with (a client never chooses it): upgrading an older store to schema 4, importing a kept H.15 package as a
baseline snapshot, previewing a freeze (which writes nothing) and approving one freeze, which the server stamps and
stores atomically.
Assessment (see assessment_api) adds importing an outcome snapshot, previewing and approving one assessment of one
frozen hypothesis (evaluated, recorded and its Dossier prepared), preparing a stored assessment's Dossier, and
previewing and approving one outcome-data download (sent only by a server started with --enable-market-retrieval).
Their GET routes read the store, the drafts, the reviews, the prepared Dossiers and the kept packages only; they never
import, migrate, freeze, evaluate, prepare or fetch anything.

The Treasury findings pilot (see insight_api) adds one explicit local check that measures retained events against the
newest accepted H.15 package and stores write-once records under data/insights/; its GET routes only read them. The
industry findings (see g17_api) add one explicit local check of retained G.17 releases, with write-once records under
data/insights/g17/ and GET routes that only read and verify them. The electricity findings (see electricity_api) add
one explicit local check of the retained EIA Table 7.6 files, with a write-once result under data/insights/electricity/
and a GET route that only reads and verifies it. The cross-source comparisons (see crosssource_api) set those two
retained sources side by side, with one explicit local computation, a write-once result under
data/insights/cross-source/ and a GET route that only reads and verifies it.

Related Cases (see related_api) serves two committed historical cases and adds one explicit local write: finding the
cases related to one Inbox entry or capture by a fixed word list (no model, network or score), stored once under
data/related-cases/. Its GET routes read and verify only. Related research (see related_research) adds one GET route
that selects an event's links to existing library cases from local records; it writes and stores nothing.

The research views (see research_api and policy_research) add one GET route that serves a committed comparison of
retained publications, checking every quoted passage against the retained sources in memory; nothing is written or
fetched, and there is no POST.

The evidence-first research analysis (see research_analysis and research_analysis_api) is a second analysis mode for
a saved event, with its own request, result and review contracts. It adds four explicit local writes: preparing one
capture's research request (nothing is sent), approving one local mock response, sending one explicitly approved paid
request (only on a server started with --enable-paid-drafts) and appending a review version. Its GET routes read and
verify only.

My analyses (see analysis_library) is a read-only view of the Tracker's published analyses and their review state,
built only from the verified capture, attempt and review readers.

The event overview (see event_overview) reads one Inbox entry or capture with its triage, draft and review, market
context and processing history (see event_history), joined only through stable IDs and explicit links (see
event_links). Capturing an event may name the Inbox entry version that filled its form; that origin is checked before
capturing and recorded beside the capture, never in its request. The overview's GET routes, and the processing index
the Inbox list reads, write, fetch and approve nothing.

A draft is served with the fingerprint of its exact bytes in the X-Draft-View-SHA256 header; a review
save must name it, so a review is bound to the view the page actually loaded.

Who is asking (see auth, accounts and docs/admin-user-contract.md): a server built with an accounts store (every
`serve`) authenticates every request by its session and enforces roles before any route runs. Every route is
admin-only unless auth lists it as public (the session routes) or user (/api/user/*, see user_api and user_research);
the admin build is served only to admins, the client build to users and to signed-out visitors (its sign-in page).
The administrator's routes (see admin_api and admin_views) manage accounts, credits, daily limits, the credit policy,
ownership and attempts under review. A server built in code without an accounts store is in local-operator mode: every
request is the local operator with the admin role, exactly as before accounts existed; the user routes then answer 503.
"""
import json
import re
import threading
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from . import (accounts as acc, admin_api, analysis_library, auth, library_api, lifecycle_api, news_admin_api, news_api,
               news_feeds, news_index, news_texts, news_views, newsroom_store, onboarding_api, publication_import, stories_api, story_deeper,
               usage, user_api, user_research, assessment_api, bis_snapshot, case_enrichments, case_library,
               crosssource_api, crosssource_insights, draft_catalog, electricity_api, inbox_imports, snapshot_api,
               policy_research, rate_context, rate_context_api, research_analysis, research_analysis_api, research_api,
               electricity_evidence, electricity_insights, event_history, event_inbox, event_links, event_overview,
               g17_api, g17_evidence, g17_insights, insight_api, insights, lifecycle, market_context,
               market_retrieval, market_store, related_api, related_cases, related_matches, triage_api, triage_flow,
               thesis_api, thesis_schema, thesis_sources, copper_inputs, copper_scenarios, copper_tools_api,
               event_chain_api, event_chain_evidence, copper_research_api, metals_api, metals_view, fuels_api, fuels_sources, company_research_api, company_research_view)
from .model_draft import strict_json
from .event_context import confirm as confirm_context
from .analysis_flow import (ATTEMPTS_DIR, FLOW_VERSION, MAX_FORM_BYTES, FlowRefused, attempt_state,
                            capture_from_form, dispatch_mock, preview_capture, publish_recorded)
from .dossier import PREPARED_DIR
from .draft_views import DRAFTS_DIR
from .event_intake import INTAKE_DIR, IntakeRefused, listing
from .human_review import MAX_BODY, REVIEWS_DIR, ReviewRefused, fingerprint, history_view, save_review
from .paid_drafts import PaidSender, dispatch_paid, paid_status

STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"  # The admin build.
CLIENT_STATIC_DIR = STATIC_DIR.parent / "dist-client"  # The user client build (and its sign-in page).
CLIENT_INDEX = "client.html"
DOSSIER_ID = re.compile(r"[a-f0-9]{64}")
NOT_PREPARED = "Dossiers have not been prepared. Run: python -m second_order prepare"
DRAFTS_NOT_PREPARED = draft_catalog.NOT_PREPARED
NOT_BUILT = "The Dossier client is not built. Run `npm ci` and `npm run build` in frontend/."
REVIEW_HEADER = "x-second-order-review"
INTAKE_HEADER = "x-second-order-intake"
INBOX_HEADER = "x-second-order-inbox"
CONTEXT_HEADER = "x-second-order-context"
VIEW_HASH_HEADER = "X-Draft-View-SHA256"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def check_local_host(request: Request) -> str:
    """Guard reads as well as writes against foreign, missing or malformed Host headers."""
    hosts = request.headers.getlist("host")
    host = hosts[0] if len(hosts) == 1 else ""
    if host not in LOCAL_HOSTS:
        name, _, port = host.rpartition(":")
        if name not in LOCAL_HOSTS or not 1 <= len(port) <= 5 or not port.isascii() or not port.isdecimal() \
                or not 1 <= int(port) <= 65535:
            raise HTTPException(403, "This server is available only through a local address")
    return host


def check_local_write(request: Request, header: str = REVIEW_HEADER, subject: str = "Reviews") -> None:
    """Refuse anything but a same-origin JSON request from this local page (CSRF and DNS rebinding)."""
    host = check_local_host(request)
    if request.headers.get("origin") != f"{request.url.scheme}://{host}":
        raise HTTPException(403, f"{subject} are handled only from this server's own page")
    if request.headers.get("sec-fetch-site", "same-origin") != "same-origin":
        raise HTTPException(403, f"{subject} are handled only from this server's own page")
    if request.headers.get(header) != "1":
        raise HTTPException(403, f"The {subject.lower()} action header is missing")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, f"{subject} must be sent as application/json")


async def limited_body(request: Request, limit: int = MAX_BODY, subject: str = "review") -> bytes:
    if int(request.headers.get("content-length") or 0) > limit:
        raise HTTPException(413, f"A {subject} is limited to {limit} bytes")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, f"A {subject} is limited to {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def create_app(prepared: Path = PREPARED_DIR, static: Path | None = STATIC_DIR, drafts: Path = DRAFTS_DIR,
               reviews: Path = REVIEWS_DIR, intake: Path = INTAKE_DIR,
               attempts: Path = ATTEMPTS_DIR, published: Path | None = None,
               paid: PaidSender | None = None, library: Path = case_library.LIBRARY_DIR,
               context: Path = market_context.BUNDLE_DIR, inbox: Path = event_inbox.INBOX_DIR,
               feeds: event_inbox.FeedFetcher | None = None, triage: Path = triage_flow.TRIAGE_DIR,
               triage_senders: triage_flow.TriageSenders | None = None,
               market: Path = market_store.STORE_DIR, market_fetcher: market_retrieval.ReleaseFetcher | None = None,
               market_clock=market_retrieval.now, links: Path = event_links.LINKS_DIR,
               store: Path | None = None, lifecycle_clock=lifecycle.now,
               insights_dir: Path = insights.INSIGHTS_DIR, insights_clock=insights.now,
               g17_sources: Path = g17_evidence.SOURCES_DIR,
               electricity_sources: Path = electricity_evidence.SOURCES_DIR,
               related: Path = related_cases.CASES_DIR, related_sources: Path = related_cases.SOURCES_DIR,
               related_records: Path = related_matches.RECORDS_DIR, related_clock=related_matches.now,
               enrichment_sources: Path = case_enrichments.SOURCES_DIR,
               snapshot_sources: Path = bis_snapshot.SOURCES_DIR, snapshot_index: Path = bis_snapshot.INDEX_DIR,
               snapshot_clock=inbox_imports.now, research: Path = policy_research.RESEARCH_DIR,
               research_analyses: Path | None = None, rate_context_dir: Path | None = None,
               theses: Path = thesis_schema.THESES_DIR, thesis_sources_dir: Path = thesis_sources.SOURCES_DIR,
               copper_inputs_dir: Path = copper_inputs.INPUTS_DIR, copper_sources_dir: Path | None = None,
               copper_scenarios_dir: Path = copper_scenarios.SCENARIOS_DIR, copper_clock=copper_scenarios.now,
               metals_dir: Path = metals_view.METALS_DIR, metals_sources_dir: Path | None = None,
               fuels_content: Path = fuels_sources.CONTENT_DIR, fuels_snapshots: Path | None = None,
               fuels_synthetic: bool = False,
               company_research_dir: Path = company_research_view.RESEARCH_DIR,
               company_sources_dir: Path = company_research_view.SOURCES_DIR,
               event_chain_records: Path = event_chain_api.RECORDS_DIR,
               research_notes_dir: Path = copper_research_api.NOTES_DIR, accounts: Path | None = None,
               client_static: Path | None = CLIENT_STATIC_DIR, accounts_clock=acc.now,
               session_hours: int = acc.SESSION_HOURS,
               publication_imports: Path | None = None,
               publication_fetcher: publication_import.PublicationFetcher | None = None,
               request_ticks=None, desk: news_views.Desk | None = None) -> FastAPI:
    """``drafts`` is the folder prepare-drafts owns; ``published`` (default: tracker-drafts beside it) is the
    Tracker's own draft folder. Reads merge both; see draft_catalog. ``paid`` is None unless the server was
    explicitly started with paid sending enabled; without it every paid action is refused. ``inbox`` is the Event
    Inbox cache; ``feeds`` (default: the real network, with the operator's contact from the environment at each
    refresh) is chosen at startup only, so a simulated network is a test-server concern, never an API feature.
    ``triage`` holds headline-triage records; ``triage_senders`` (default: the local simulation only, paid triage
    off) is likewise chosen at startup only. ``market`` holds private market context (confirmed events, retrievals,
    kept packages, attempts); ``market_fetcher`` is None unless the server was started with market retrieval enabled, and like the
    other fetchers it is chosen at startup only. ``context``, the committed bundle, is also read as retrievals to
    reuse. ``links`` holds the recorded Inbox origins of captures (see event_links). ``store`` is the one research
    store the lifecycle reads and, on explicit approval, writes; it is chosen at startup only (``serve`` passes
    data/real/second-order.db unless told otherwise), and without it every lifecycle route answers 503.
    ``insights_dir`` holds the findings pilot's records (see insights) and, in its g17/ folder, the industry
    findings' records (see g17_insights); ``g17_sources`` is the retained G.17 folder they read. Its electricity/
    folder holds the electricity findings' result (see electricity_insights), read from ``electricity_sources``, the
    retained EIA Monthly Energy Review folder. Its cross-source/ folder holds the cross-source comparisons' result (see
    crosssource_insights), read from both of those source folders. ``related`` holds the committed historical cases
    (see related_cases), checked against their retained copies in ``related_sources`` when present; ``related_records``
    holds the write-once Related Cases matches (see related_matches). ``enrichment_sources`` is the retained BIS folder
    that case enrichments (see case_enrichments) are checked against when present. ``snapshot_sources`` holds the
    retained BIS snapshot (see bis_snapshot), read only after it verifies against its acquisition record;
    ``snapshot_index`` holds its derived index, written only by the explicit open; imported records go to ``inbox``
    (see inbox_imports). ``research`` holds the committed research views (see policy_research), checked on each read
    against the retained snapshot in ``snapshot_sources`` and the release pages in ``snapshot_sources`` and
    ``related_sources``. ``research_analyses`` holds the evidence-first research requests, attempts and reviews (see
    research_analysis); by default it is the research-analyses folder beside ``intake``, so a server over another
    intake folder never reads this machine's research records. ``rate_context_dir`` holds the retained rate-path
    workbooks and saved events' rate-path records (see rate_context), only read here; by default it is the
    rate-context folder beside ``intake``, for the same reason. ``accounts`` is the accounts store (see accounts):
    with it every request is authenticated and every route checks the role (``serve`` always passes one); without it the
    server is the local operator's, as before accounts existed. ``static`` is the admin build, ``client_static`` the
    user client build. ``paid`` also sends users' approved analyses (see user_research). With accounts, the current-news
    routes (news_api, docs/news-usage-contract.md) read the Event Inbox cache ``inbox`` and keep import records in
    ``publication_imports`` (default: the publication-imports folder beside ``intake``); ``publication_fetcher`` is None
    unless the server was started with publication import enabled (chosen at startup only, like every fetcher), and then
    an explicit import preview may request one allowlisted page. The usage policy's protective request limits run
    around every user route (``request_ticks``, a monotonic clock, is for tests), and the operator's feed refresh waits
    its cooldown and counts against the day's refresh budget. ``desk`` is where the stories live (news_views.Desk: the
    newsroom store, the publisher-feed cache and the Go deeper records beside ``intake``, the registry, the publisher
    fetcher and the paid brief sender, all chosen at startup); see stories_api and news_admin_api.
    ``copper_inputs_dir`` holds the copper tools' committed inputs catalogue, checked on every read against
    ``copper_sources_dir`` (default: ``thesis_sources_dir``, the same retained copper folder);
    ``copper_scenarios_dir`` holds their write-once scenario records (see copper_tools_api);
    ``metals_dir`` holds the metals page's committed sources file, checked on every read against
    ``metals_sources_dir`` (default: ``thesis_sources_dir``; see metals_api).
    ``fuels_content`` holds the fuels page's committed source-terms record and notes, and ``fuels_snapshots`` its
    retrieved price snapshots; by default no snapshot is read, so only an explicit folder (as ``serve`` passes) shows
    prices (see fuels_api). ``fuels_synthetic`` is for the review server's SYNTHETIC world only (``serve`` never sets
    it): the reply then says so and the page marks its prices as test data. company_research_dir holds the committed FCX
    research package and company_sources_dir its retained documents, verified on every read (see
    company_research_api). ``research_notes_dir`` holds the owner's research notes, the only files the copper
    research routes write (see copper_research_api)."""
    research_analyses = research_analyses or intake.parent / research_analysis.RESEARCH_DIR.name
    rate_context_dir = rate_context_dir or intake.parent / rate_context.RATE_DIR.name
    store_of_accounts = acc.Accounts.open(accounts) if accounts is not None else None

    def check_access(request: Request) -> None:
        """Who is asking (from the session cookie, never from the client's word), and whether the route allows it."""
        if store_of_accounts is None:
            request.state.identity = auth.LOCAL_IDENTITY
            return
        identity, why = acc.identify(store_of_accounts, request.cookies.get(auth.SESSION_COOKIE), accounts_clock())
        request.state.identity, request.state.signed_out = identity, why
        method, path = request.method, request.url.path
        kind = auth.route_kind(method, path)
        if kind == "page":
            return
        sent = auth.bound_account(request.headers.getlist(auth.ACCOUNT_HEADER))
        if kind == "public":  # Sign-out checks a sent binding; the other public routes ignore it.
            auth.check_binding(method, path, sent, identity, require=False)
            return
        if identity is None:  # Refusals about the session are in the user contract, which every client reads.
            raise auth.ContractError(401, why, contract=auth.USER_CONTRACT)
        # A page opened for another account learns that before anything else; a missing binding after the role check.
        auth.check_binding(method, path, sent, identity, require=False)
        if identity.role != ("user" if kind == "user" else "admin"):
            raise auth.ContractError(403, "forbidden", contract=auth.USER_CONTRACT)
        auth.check_binding(method, path, sent, identity, require=True)

    throttle = usage.Throttle(request_ticks) if request_ticks else usage.Throttle()

    async def limit_requests(request: Request):
        """The usage policy's protective limits (requests per minute and in progress) around every user route, after
        the access check; protective only, never a charge (docs/news-usage-contract.md, section 3)."""
        identity, held = getattr(request.state, "identity", None), None
        if store_of_accounts is not None and identity is not None and identity.role == "user" and \
                auth.route_kind(request.method, request.url.path) == "user":
            policy = await run_in_threadpool(usage.current_policy, store_of_accounts)
            if policy is not None:
                try:
                    throttle.enter(identity.user_id, policy["account"]["requests_per_minute"],
                                   policy["account"]["concurrent_requests"])
                except acc.AccountsRefused as exc:
                    raise auth.ContractError(exc.status, exc.code, str(exc), contract=auth.USER_CONTRACT,
                                             **exc.extra) from None
                held = identity.user_id
        try:
            yield
        finally:
            if held is not None:
                throttle.leave(held)

    app = FastAPI(title="Second Order local research API", openapi_url=None, docs_url=None, redoc_url=None,
                  dependencies=[Depends(check_local_host), Depends(check_access), Depends(limit_requests)])

    @app.exception_handler(auth.ContractError)
    def contract_error(request: Request, exc: auth.ContractError) -> Response:
        return auth.error_response(request.url.path, exc.status, exc.code, exc.detail, exc.contract, **exc.extra)

    @app.exception_handler(acc.AccountsRefused)
    def accounts_refused(request: Request, exc: acc.AccountsRefused) -> Response:
        return auth.error_response(request.url.path, exc.status, exc.code, str(exc), **exc.extra)

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        """The contract routes answer in the contract's shape; every other route keeps its {"detail": ...}."""
        if not auth.contract_route(request.url.path):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        code = auth.STATUS_CODES.get(exc.status_code, "internal_error")
        detail = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else auth.MESSAGES.get(code, code)
        return auth.error_response(request.url.path, exc.status_code, code, detail)

    @app.exception_handler(Exception)
    def unexpected(request: Request, exc: Exception) -> Response:
        if auth.contract_route(request.url.path):  # Nothing internal reaches a contract reply.
            return auth.error_response(request.url.path, 500, "internal_error", auth.MESSAGES["internal_error"])
        return PlainTextResponse("Internal Server Error", status_code=500)
    published = published or draft_catalog.tracker_dir(drafts)
    overview_folders = event_overview.folders_for(inbox, intake, attempts, drafts, published, reviews, triage, links,
                                                  market, context, store, research_analyses)
    refreshing = threading.Lock()  # One inbox refresh at a time; a second is refused, never queued.
    folders = lifecycle.Folders(store=store, market=market, intake=intake, attempts=attempts, drafts=drafts,
                                published=published, reviews=reviews) if store is not None else None
    # The one statement of what this server offers. Offering a mode is not an approval.
    def with_modes(preview: dict) -> dict:
        return {**preview, "modes": {"mock": {"enabled": True, "detail": "Local mock: $0, no provider contacted."},
                                     "paid": paid_status(paid)}}

    def prepared_file(name: str) -> Path:
        path = prepared / name
        if not path.is_file():
            raise HTTPException(503, NOT_PREPARED)
        return path

    def index() -> dict:
        return json.loads(prepared_file("index.json").read_text(encoding="utf-8"))

    @app.get("/api/dossiers")
    def list_dossiers() -> Response:
        return Response(prepared_file("index.json").read_bytes(), media_type="application/json")

    @app.get("/api/dossiers/{dossier_id}")
    def get_dossier(dossier_id: str) -> Response:
        if not DOSSIER_ID.fullmatch(dossier_id) or dossier_id not in {row["id"] for row in index()["dossiers"]}:
            raise HTTPException(404, "Unknown dossier ID")
        return Response(prepared_file(f"{dossier_id}.json").read_bytes(), media_type="application/json")

    @app.get("/api/drafts")
    def list_drafts() -> Response:
        try:
            listed = draft_catalog.listing(drafts, published)
        except draft_catalog.CatalogRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        if listed is None:
            raise HTTPException(503, DRAFTS_NOT_PREPARED)
        return JSONResponse(listed)

    @app.get("/api/drafts/{draft_id}")
    def get_draft(draft_id: str) -> Response:
        try:
            data = draft_catalog.locate(drafts, published, draft_id)
        except draft_catalog.CatalogRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        return Response(data, media_type="application/json", headers={VIEW_HASH_HEADER: fingerprint(data)})

    @app.get("/api/drafts/{draft_id}/reviews")
    def get_reviews(draft_id: str) -> dict:
        try:
            return history_view(drafts, reviews, draft_id, published)
        except ReviewRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @app.post("/api/drafts/{draft_id}/reviews")
    async def post_review(draft_id: str, request: Request) -> Response:
        check_local_write(request)
        body = await limited_body(request)
        try:
            record = save_review(drafts, reviews, draft_id, body, published_dir=published)
        except ReviewRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        return JSONResponse(record, status_code=201)

    @app.get("/api/intake")
    def list_intake() -> dict:
        return {"flow_version": FLOW_VERSION, "captures": listing(intake)}

    @app.post("/api/intake")
    async def post_intake(request: Request) -> Response:
        check_local_write(request, INTAKE_HEADER, "Event-intake actions")
        body = await limited_body(request, MAX_FORM_BYTES, "event intake")
        origin = None
        try:
            payload = strict_json(body)
        except Exception:
            payload = None  # capture_from_form refuses it with its own message.
        if isinstance(payload, dict) and "origin" in payload:  # The Inbox entry version that filled the form.
            try:
                origin = event_links.check_origin(payload.pop("origin"), inbox)
            except event_links.LinkRefused as exc:
                raise HTTPException(exc.status, str(exc)) from None
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")  # The form alone builds the request.
        try:
            result = capture_from_form(body, intake)
        except FlowRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The event could not be captured locally ({type(exc).__name__})") from None
        if origin is not None:
            try:
                result["origin"] = {"recorded": True, "problem": None,
                                    "link": event_links.record_origin(links, result["capture_id"], intake, origin,
                                                                      market_clock)}
            except (OSError, IntakeRefused) as exc:
                result["origin"] = {"recorded": False, "link": None,
                                    "problem": f"The event was captured, but its Inbox origin could not be recorded "
                                               f"({type(exc).__name__}); the capture has no origin link"}
        return JSONResponse(with_modes(result), status_code=201)

    @app.get("/api/intake/{capture_id}")
    def get_intake(capture_id: str) -> dict:
        try:
            return with_modes(preview_capture(capture_id, intake))
        except (IntakeRefused, OSError) as exc:
            raise HTTPException(404, str(exc)) from None

    @app.post("/api/intake/{capture_id}/mock-drafts")
    async def post_mock_draft(capture_id: str, request: Request) -> Response:
        check_local_write(request, INTAKE_HEADER, "Event-intake actions")
        body = await limited_body(request, MAX_FORM_BYTES, "mock confirmation")
        try:
            result = dispatch_mock(capture_id, body, intake, attempts, drafts, published_dir=published)
        except FlowRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:  # Raised only before an attempt is reserved; afterwards dispatch reports it.
            raise HTTPException(500, f"The mock attempt could not be started locally ({type(exc).__name__}); "
                                     "check the attempt state before approving again") from None
        return JSONResponse(result, status_code=201)

    @app.post("/api/intake/{capture_id}/paid-drafts")
    async def post_paid_draft(capture_id: str, request: Request) -> Response:
        check_local_write(request, INTAKE_HEADER, "Event-intake actions")
        if paid is None:
            raise HTTPException(409, paid_status(None)["detail"])
        body = await limited_body(request, MAX_FORM_BYTES, "paid approval")
        try:  # In a worker thread: a send can take minutes, and reads such as the attempt state must still answer.
            result = await run_in_threadpool(dispatch_paid, capture_id, body, paid, intake, attempts, drafts,
                                             published_dir=published)
        except FlowRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:  # Raised only before an attempt is reserved; afterwards dispatch reports it.
            raise HTTPException(500, f"The paid attempt could not be started locally ({type(exc).__name__}); "
                                     "check the attempt state before approving again") from None
        return JSONResponse(result, status_code=201)

    @app.get("/api/intake/{capture_id}/attempt")
    def get_attempt(capture_id: str) -> dict:
        try:
            return attempt_state(capture_id, intake, attempts, drafts, published)
        except FlowRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @app.post("/api/intake/{capture_id}/publish")
    async def post_publication(capture_id: str, request: Request) -> Response:
        check_local_write(request, INTAKE_HEADER, "Event-intake actions")
        body = await limited_body(request, MAX_FORM_BYTES, "publication")
        try:
            result = publish_recorded(capture_id, body, intake, attempts, drafts, published)
        except FlowRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        return JSONResponse(result, status_code=201)

    @app.get("/api/analyses")
    def get_analyses() -> dict:
        """My analyses: the Tracker's analyses with a published review view, read through the verified readers (see
        analysis_library). Reads only: nothing is written, sent or fetched."""
        try:
            return analysis_library.library_view(intake, attempts, drafts, published, reviews)
        except OSError as exc:
            raise HTTPException(500, f"The saved analyses could not be read ({type(exc).__name__})") from None

    @app.get("/api/inbox")
    def get_inbox() -> dict:
        """The cached inbox as it is: no feed is requested and nothing is written or repaired."""
        return event_inbox.inbox_view(inbox)

    @app.post("/api/inbox/refresh")
    async def post_inbox_refresh(request: Request) -> Response:
        check_local_write(request, INBOX_HEADER, "Inbox refreshes")
        body = await limited_body(request, 64, "refresh request")
        try:  # No options: the feeds are fixed in event_inbox, so no address can come from a request.
            options = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            options = None
        if options != {}:
            raise HTTPException(422, "A refresh takes no options; send an empty JSON object")
        if not refreshing.acquire(blocking=False):
            raise HTTPException(409, "A refresh is already running; wait for it to finish")
        try:
            refresh = None
            if store_of_accounts is not None:  # One shared refresh for every user: the usage policy's cooldown and budget.
                try:
                    refresh = await run_in_threadpool(usage.reserve_refresh, store_of_accounts,
                                                      auth.identity_of(request).user_id, accounts_clock())
                except acc.AccountsRefused as exc:
                    raise HTTPException(409, str(exc)) from None
            try:
                fetcher = feeds or event_inbox.FeedFetcher.from_environment()
            except ValueError as exc:
                if refresh is not None:  # Nothing was requested.
                    await run_in_threadpool(usage.release, store_of_accounts, refresh, "the refresh did not start",
                                            accounts_clock())
                raise HTTPException(500, str(exc)) from None
            result = await run_in_threadpool(event_inbox.refresh, inbox, fetcher)
        finally:
            refreshing.release()
        return JSONResponse(result)

    triage_api.add_routes(app, inbox, triage, triage_senders, check_local_write, limited_body)

    def market_read(read):
        """Market-context reads: saved events and verified retrievals only, never the Board."""
        try:
            return read()
        except (market_context.ContextRefused, market_store.StoreRefused) as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local market context could not be read ({type(exc).__name__})") from None

    @app.get("/api/events/processing")
    def get_processing_index() -> dict:
        """Per Inbox entry, whether saved triage or a verified capture exists; local records only, nothing written."""
        try:
            return event_history.processing_index(triage, links, intake)
        except OSError as exc:
            raise HTTPException(500, f"The saved processing records could not be read ({type(exc).__name__})") from None

    @app.get("/api/events/{kind}/{event_id}")
    def get_event_overview(kind: str, event_id: str) -> dict:
        """One event's source, triage, draft and review, market context and processing history, from local records
        only."""
        if kind not in ("inbox", "capture"):
            raise HTTPException(404, "Unknown kind of event")
        read = event_overview.inbox_overview if kind == "inbox" else event_overview.capture_overview
        return market_read(lambda: read(event_id, overview_folders, market_clock))

    @app.get("/api/market-context")
    def get_market_contexts() -> dict:
        return market_read(lambda: market_retrieval.listing(market, context, inbox, intake, market_fetcher,
                                                            market_clock))

    @app.get("/api/market-context/plan")
    def get_market_plan(event: list[str] = Query(default=[])) -> dict:
        """The retrieval one or more saved events would need. Reads only: nothing is requested or written."""
        return market_read(lambda: market_retrieval.plan_view(event, market, context, inbox, intake, market_fetcher,
                                                              market_clock))

    @app.get("/api/market-context/{kind}/{event_id}")
    def get_event_context(kind: str, event_id: str) -> dict:
        if kind not in ("inbox", "capture"):
            raise HTTPException(404, "Unknown kind of event")
        return market_read(lambda: market_retrieval.event_page(kind, event_id, market, context, inbox, intake,
                                                               market_fetcher, market_clock))

    @app.post("/api/market-context/inbox/{item_id}/confirm")
    async def post_context_confirmation(item_id: str, request: Request) -> Response:
        """Save the user's confirmation of an Inbox entry's context date and its convention. Nothing is fetched."""
        check_local_write(request, CONTEXT_HEADER, "Market-context actions")
        body = await limited_body(request, market_retrieval.MAX_BODY, "confirmation")
        try:
            result = confirm_context(item_id, body, market, inbox, market_clock)
        except market_context.ContextRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The confirmation could not be saved locally ({type(exc).__name__})") from None
        return JSONResponse(result, status_code=201 if result["saved_now"] else 200)

    @app.post("/api/market-context/retrievals")
    async def post_market_retrieval(request: Request) -> Response:
        """Send one explicitly approved request for the Board's release package; see market_retrieval.dispatch."""
        check_local_write(request, CONTEXT_HEADER, "Market-context actions")
        body = await limited_body(request, market_retrieval.MAX_BODY, "retrieval approval")
        try:  # In a worker thread: the request can take a while, and reads must still answer.
            result = await run_in_threadpool(market_retrieval.dispatch, body, market, context, inbox, intake,
                                             market_fetcher, market_clock)
        except (market_context.ContextRefused, market_store.StoreRefused) as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The retrieval could not be recorded locally ({type(exc).__name__}); read the "
                                     "event again before approving anything") from None
        return JSONResponse(result, status_code=201)

    lifecycle_call = lifecycle_api.caller(folders)
    lifecycle_api.add_routes(app, folders, lifecycle_call, check_local_write, limited_body, lifecycle_clock)
    assessment_api.add_routes(app, folders, lifecycle_call, check_local_write, limited_body,
                              lifecycle_api.LIFECYCLE_HEADER, lifecycle_clock, market_fetcher)
    insight_api.add_routes(app, insights.Folders(insights=insights_dir, market=market, inbox=inbox, intake=intake,
                                                 library=library), check_local_write, limited_body, insights_clock)
    g17_api.add_routes(app, g17_insights.Folders(sources=g17_sources, records=insights_dir / "g17", library=library),
                       check_local_write, limited_body, insights_clock)
    electricity_api.add_routes(app, electricity_insights.Folders(sources=electricity_sources,
                                                                 records=insights_dir / "electricity"),
                               check_local_write, limited_body, insights_clock)
    crosssource_api.add_routes(app, crosssource_insights.Folders(g17_sources=g17_sources, eia_sources=electricity_sources,
                                                                 records=insights_dir / "cross-source"),
                               check_local_write, limited_body, insights_clock)
    related_api.add_routes(app, related_matches.Folders(cases=related, records=related_records, inbox=inbox,
                                                        intake=intake, triage=triage, links=links),
                           related_sources, check_local_write, limited_body, related_clock, library)
    snapshot_api.add_routes(app, inbox, snapshot_sources, snapshot_index, check_local_write, limited_body,
                            snapshot_clock)
    # Go deeper's origin records, where the desk writes them: research requests bind their publishers' passages.
    deeper = desk.deeper if desk is not None else intake.parent / story_deeper.DEEPER_DIR.name
    research_folders = research_analysis.Folders(research=research_analyses, intake=intake, links=links,
                                                 deeper=deeper)
    research_analysis_api.add_routes(app, research_folders, paid, check_local_write, limited_body)
    rate_context_api.add_routes(app, rate_context.Folders(rate=rate_context_dir, intake=intake, links=links))
    user_context = user_research.UserResearch(store_of_accounts, research_folders, paid, accounts_clock) \
        if store_of_accounts else None
    user_api.add_routes(app, user_context, check_local_write, limited_body, session_hours)
    news_folders = publication_import.Folders(inbox=inbox, imports=publication_imports or
                                              intake.parent / publication_import.IMPORTS_DIR.name)
    desk = desk or news_views.Desk(newsroom_store.open_at(intake.parent / newsroom_store.NEWSROOM_DIR.name), inbox,
                                   intake.parent / news_feeds.FEEDS_DIR.name, deeper,
                                   texts=intake.parent / news_texts.TEXTS_DIR.name,
                                   index=intake.parent / news_index.INDEX_DIR.name)
    news_api.add_routes(app, user_context, check_local_write, limited_body, news_api.News(
        news_folders, publication_fetcher, lambda: news_views.story_index(desk)) if user_context else None)
    stories_api.add_routes(app, user_context, check_local_write, limited_body, desk if user_context else None)
    news_admin_api.add_routes(app, store_of_accounts, desk, check_local_write, limited_body, accounts_clock,
                              feeds)
    admin_api.add_routes(app, store_of_accounts, research_folders, check_local_write, limited_body, accounts_clock)
    onboarding_api.add_routes(app, store_of_accounts, check_local_write, limited_body, accounts_clock)
    research_api.add_routes(app, research, {"bis-semis-sources-01": snapshot_sources,
                                            "related-cases-sources-01": related_sources}, library, related)
    thesis_api.add_routes(app, theses, thesis_sources_dir)
    # The copper tools read the thesis's retained copper folder; saving a scenario writes only its records folder.
    copper_tools_api.add_routes(app, copper_inputs_dir, copper_sources_dir or thesis_sources_dir, copper_scenarios_dir,
                                check_local_write, limited_body, copper_clock, research=company_research_dir,
                                company_sources=company_sources_dir)
    copper_folders = event_chain_evidence.Folders(
        theses, thesis_sources_dir, metals_dir, metals_sources_dir or thesis_sources_dir, company_research_dir,
        company_sources_dir, event_chain_records)
    event_chain_api.add_routes(app, copper_folders, check_local_write, limited_body, copper_clock,
                               store_of_accounts is not None)
    # The copper desk, the publication comparisons and the owner's notes; a save writes only the notes folder.
    copper_research_api.add_routes(app, copper_folders, research_notes_dir, check_local_write, limited_body,
                                   copper_clock, store_of_accounts is not None)
    metals_api.add_routes(app, metals_dir, metals_sources_dir or thesis_sources_dir, theses,
                         company_research_dir, company_sources_dir)
    fuels_api.add_routes(app, fuels_content, fuels_snapshots, fuels_synthetic)
    company_research_api.add_routes(app, company_research_dir, company_sources_dir, check_local_write, limited_body)

    library_api.add_routes(app, library, context, enrichment_sources, related)

    @app.get("/api/{rest:path}")
    def unknown_api(rest: str) -> Response:
        raise HTTPException(404, "Unknown API route")

    @app.get("/{path:path}", include_in_schema=False)
    def client(path: str, request: Request) -> Response:
        """The role's own build: the admin build to admins (and to the local operator), the client build to users and
        signed-out visitors. A user can never load an admin file: it is not in the folder served to them."""
        identity = auth.identity_of(request)
        admin_build = identity is not None and identity.role == "admin"
        folder, index_name = (static, "index.html") if admin_build else (client_static, CLIENT_INDEX)
        if folder is None or not (folder / index_name).is_file():
            return PlainTextResponse(NOT_BUILT, status_code=503)
        root = folder.resolve()
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        # Client routes such as /h/<id> load the app shell; the client asks the API for the data.
        return FileResponse(root / index_name, headers={"Cache-Control": "no-cache"})

    return app
