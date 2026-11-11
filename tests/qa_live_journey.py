"""QA connected journey over RETAINED real official records (LOCAL_LIVE_SCOPE claim 3 on the backend), kept apart from
what is synthetic.

What is real: the Event Inbox cache and one Federal Reserve press-release page, both retrieved once by the data owner's
controlled smoke run (second-order-v2-live-data/data/live-smoke/run-1, 14 October 2026). This script never requests
anything: it copies that run's event-inbox/ and the page's kept bytes and retrieval record into a new temporary folder
(the run is only read, and checked against its manifest before and after), and gives the server a publication fetcher
whose transport refuses and records any request. The page is therefore read again from its retained bytes ("reused"),
with the retrieval time the record states.

What is synthetic: the accounts, credit policy, usage limits and grants (typed here for the test), the clock, and the
model: a fake provider answers the one approved run with a reply quoting the request's own text. Nothing measures a
model's quality.

The journey: register -> pending (no sign-in, no news) -> an administrator approves and, separately, allocates credits
and a daily limit -> no usage policy (news refused, nothing counted) -> the administrator publishes one -> interests ->
news by interests and all -> a deliberate counted search (and its repeat) -> an unsupported entry offers paste -> a full
preview of the retained page with its provenance -> exact confirmation into an owned source -> Effort, quote, approval
-> one fake send -> the result, its research checks, an own review and the export. Every GET and the search are checked
to reach neither the publisher nor the provider.

    python tests/qa_live_journey.py --records <run-1 folder> [--manifest <run-1.manifest.json>] [--out <summary.json>]
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from account_fakes import ACCOUNT, ADMIN_WRITE, BASE, POLICY, SESSION_WRITE, USAGE_POLICY, USER_WRITE, Clock, \
    ProviderFake  # noqa: E402
from model_fixtures import FAKE_KEY  # noqa: E402
from second_order import accounts as acc, publication_import  # noqa: E402
from second_order.api import create_app  # noqa: E402
from second_order.paid_drafts import PaidSender  # noqa: E402

ADMIN = ("admin-live", "synthetic-admin-live-qa")
READER = {"username": "reader-live", "display_name": "Reader Live (synthetic)", "password": "synthetic-reader-live-qa",
          "note": "SYNTHETIC registration for the QA live journey."}
START = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)  # The test's own clock, after the retained retrieval.


class Refusing:
    """A publisher transport that records and refuses every request: the journey must make none."""

    def __init__(self):
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        raise httpx.ConnectError("QA: no request is allowed in the retained-records journey")


def digests(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    records = args.records.resolve()
    checks: list[tuple[str, bool, str]] = []
    seen: dict = {}

    def check(label: str, passed: object, detail: object = "") -> None:
        checks.append((label, bool(passed), json.dumps(detail, default=str)[:400] if detail != "" else ""))

    before = digests(records)
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))["files"]
        used = {name: row for name, row in manifest.items() if name.startswith(("event-inbox/", "imports/raw/",
                                                                               "imports/retrievals/"))}
        check("the retained files used here match their manifest", all(before.get(name) == row["sha256"]
                                                                        for name, row in used.items()),
              [name for name, row in used.items() if before.get(name) != row["sha256"]])
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        shutil.copytree(records / "event-inbox", root / "event-inbox")
        for part in ("raw", "retrievals"):
            shutil.copytree(records / "imports" / part, root / "publication-imports" / part)
        store = root / "accounts" / "accounts.db"
        acc.create_store(store)
        accounts = acc.Accounts.open(store)
        clock, provider, publisher = Clock(START), ProviderFake(), Refusing()
        acc.create_user(accounts, ADMIN[0], "Live admin (synthetic)", "admin", ADMIN[1], "qa-setup", clock())
        app = create_app(root / "no-dossiers", None, root / "prepared-drafts", root / "reviews", root / "intake",
                         root / "attempts", paid=PaidSender(api_key=lambda: FAKE_KEY, client_factory=provider.factory),
                         links=root / "links", research_analyses=root / "research-analyses", accounts=store,
                         accounts_clock=clock, inbox=root / "event-inbox",
                         publication_fetcher=publication_import.PublicationFetcher(httpx.MockTransport(publisher)))
        visitor, admin, user = (TestClient(app, base_url=BASE) for _ in range(3))

        def quiet(label: str, reply) -> dict:
            """A reply that reached neither the publisher nor the provider."""
            check(f"{label}: no publisher or provider request", not publisher.requests and not provider.requests,
                  {"publisher": publisher.requests, "provider": len(provider.requests)})
            return reply.json()

        def used(operation: str) -> int:
            limits = user.get("/api/user/limits").json()["limits"]
            return next(row["used"] for row in limits["operations"] if row["operation"] == operation)

        # Register, pending.
        terms = visitor.get("/api/public/credit-terms")
        check("public credit terms are readable before anything is published", terms.status_code == 200,
              terms.text[:120])
        registered = visitor.post("/api/public/registrations", headers=SESSION_WRITE, json=READER)
        check("registration is accepted as pending", registered.status_code == 201, registered.text[:200])
        pending = user.post("/api/session/login", headers=SESSION_WRITE,
                            json={"username": READER["username"], "password": READER["password"]})
        check("a pending account cannot sign in", pending.status_code != 200, pending.text[:200])
        check("a pending visitor gets no news", visitor.get("/api/user/news").status_code == 401)
        # Approve, then allocate separately.
        signed = admin.post("/api/session/login", headers=SESSION_WRITE,
                            json={"username": ADMIN[0], "password": ADMIN[1]})
        admin.headers[ACCOUNT] = signed.json()["user"]["user_id"]
        reader_id = next(row["user_id"] for row in acc.list_users(accounts) if row["username"] == READER["username"])
        decided = admin.post(f"/api/admin/registrations/{reader_id}/decision", headers=ADMIN_WRITE,
                             json={"decision": "approve", "reason": "SYNTHETIC approval for the QA live journey"})
        check("the administrator approves the registration", decided.status_code in (200, 201), decided.text[:200])
        signed = user.post("/api/session/login", headers=SESSION_WRITE,
                           json={"username": READER["username"], "password": READER["password"]})
        check("the approved reader signs in", signed.status_code == 200, signed.text[:200])
        user.headers[ACCOUNT] = reader_id
        account = user.get("/api/user/account").json()
        seen["account_before_allocation"] = account.get("account", account)
        # No usage policy yet: news, interests and searches refused, nothing counted.
        no_policy = user.get("/api/user/news")
        check("without a usage policy news is refused", (no_policy.status_code, no_policy.json().get("code")) ==
              (409, "no_usage_policy"), no_policy.text[:200])
        limits = user.get("/api/user/limits").json()["limits"]
        check("without a usage policy the limits say no_policy", limits["state"] == "no_policy", limits)
        refused_search = user.post("/api/user/news/searches", headers=USER_WRITE, json={
            "query": "discount rate", "interests": None, "sources": None, "listing": "all",
            "request_key": "qa-live-before-policy"})
        check("without a usage policy a search is refused", refused_search.json().get("code") == "no_usage_policy",
              refused_search.text[:200])
        # The administrator's explicit, separate actions (SYNTHETIC values typed for this test).
        steps = {
            "credit policy": admin.post("/api/admin/policy", headers=ADMIN_WRITE, json={
                "policy": POLICY, "reason": "SYNTHETIC credit policy", "idempotency_key": "qa-live-credit-0001"}),
            "usage policy": admin.post("/api/admin/usage-policy", headers=ADMIN_WRITE, json={
                "policy": USAGE_POLICY, "reason": "SYNTHETIC usage limits", "idempotency_key": "qa-live-usage-0001"}),
            "credits": admin.post(f"/api/admin/users/{reader_id}/credits", headers=ADMIN_WRITE, json={
                "kind": "grant", "credits": 40, "reason": "SYNTHETIC grant", "idempotency_key": "qa-live-grant-0001"}),
            "daily limit": admin.post(f"/api/admin/users/{reader_id}/daily-limit", headers=ADMIN_WRITE, json={
                "limit": 3, "reason": "SYNTHETIC daily limit"}),
        }
        for label, reply in steps.items():
            check(f"the administrator sets the {label}", reply.status_code in (200, 201), reply.text[:200])
        # Interests and news (cache only).
        vocabulary = quiet("interests read", user.get("/api/user/news/interests"))["interests"]
        saved = user.post("/api/user/news/interests", headers=USER_WRITE, json={
            "interests": ["monetary-policy", "energy"], "expected_version": vocabulary["version"]})
        check("interests are saved", saved.status_code == 201, saved.text[:200])
        mine = quiet("news by interests", user.get("/api/user/news?scope=interests"))["news"]
        every = quiet("all news", user.get("/api/user/news?scope=all"))["news"]
        sources = {row["source"]: row for row in every["sources"]}
        seen["sources"] = {key: {name: row[name] for name in ("state", "last_success_at", "entries", "stale",
                                                               "importable")} for key, row in sources.items()}
        states: dict[str, dict[str, int]] = {}
        for entry in every["entries"]:
            states.setdefault(entry["source"], {}).setdefault(entry["published"]["state"], 0)
            states[entry["source"]][entry["published"]["state"]] += 1
        seen["publication_time_states"] = states
        check("the two BLS feeds are shown as not requested",
              all(sources[key]["state"] == "not_requested" for key in ("bls-empsit", "bls-cpi")),
              {key: sources[key]["state"] for key in ("bls-empsit", "bls-cpi")})
        check("only entries with a stated time carry a UTC time",
              all((entry["published"]["utc"] is not None) == (entry["published"]["state"] == "stated")
                  for entry in every["entries"]))
        retrieval_times = {entry["first_retrieved_at"] for entry in every["entries"]} | \
            {entry["last_retrieved_at"] for entry in every["entries"]}
        check("no publication time is a retrieval time",
              not any(entry["published"]["utc"] in retrieval_times for entry in every["entries"]))
        check("news by interests holds only matching entries",
              mine["entries"] and all(entry["matches_interests"] for entry in mine["entries"]),
              len(mine["entries"]))
        seen["entries"] = {"all": len(every["entries"]), "by_interests": len(mine["entries"])}
        # A deliberate, counted search, and its repeat.
        form = {"query": "discount rate", "interests": None, "sources": None, "listing": "all",
                "request_key": "qa-live-search-0001"}
        first = user.post("/api/user/news/searches", headers=USER_WRITE, json=form)
        check("a search is counted once", first.status_code == 201 and first.json()["counted"], first.text[:200])
        quiet("the search", first)
        repeat = user.post("/api/user/news/searches", headers=USER_WRITE, json=form)
        check("the same search key and body is answered without a count",
              repeat.status_code == 200 and not repeat.json()["counted"], repeat.text[:200])
        reused = user.post("/api/user/news/searches", headers=USER_WRITE, json=form | {"query": "inflation"})
        check("the same key with another body is refused", reused.json().get("code") == "request_key_reused",
              reused.text[:200])
        check("searches used: 1", used("search") == 1, used("search"))
        found = first.json()["entries"]
        seen["search"] = {"matched": first.json()["search"]["matched"], "titles": [row["title"] for row in found]}
        kept = json.loads((records / "imports" / "retrievals" / "000001.json").read_text(encoding="utf-8"))
        target = next((row for row in every["entries"] if row["link"] == kept["url"]), None)
        check("the retained page's entry is in the news", target is not None, kept["url"])
        # An unsupported entry offers paste and counts nothing.
        other = next(row for row in every["entries"] if row["import"]["state"] == "unsupported")
        unsupported = user.post("/api/user/news/imports", headers=USER_WRITE, json={
            "entry_id": other["entry_id"], "version_sha256": other["version_sha256"]})
        body = unsupported.json()
        check("an unsupported entry is refused with a paste offer and not counted",
              (unsupported.status_code, body.get("code"), body.get("paste_instead"), body.get("requested")) ==
              (409, "import_unsupported", True, False) and used("import") == 0, unsupported.text[:240])
        seen["unsupported"] = {"source": other["source"], "reason": other["import"]["reason"]}
        # The full preview of the retained page.
        preview_reply = user.post("/api/user/news/imports", headers=USER_WRITE, json={
            "entry_id": target["entry_id"], "version_sha256": target["version_sha256"]})
        check("the preview is created from the retained page", preview_reply.status_code == 201,
              preview_reply.text[:240])
        preview = quiet("the preview", preview_reply)["import"]
        publication, proposed = preview["publication"], preview["proposed_source"]
        seen["preview"] = {"retrieval": publication["retrieval"], "retrieved_at": publication["retrieved_at"],
                           "bytes": publication["bytes"], "sha256": publication["sha256"],
                           "last_modified": publication["last_modified"], "published_at": proposed["published_at"],
                           "published_basis": proposed["published_basis"], "characters": proposed["characters"],
                           "headline": proposed["headline"], "left_out": [row["kind"] for row in preview["left_out"]],
                           "linked_documents": preview["linked_documents"], "statements": preview["statements"]}
        check("the page is reused with the retained retrieval time and bytes",
              publication["retrieval"] == "reused" and publication["sha256"] == kept["body"]["sha256"] and
              publication["retrieved_at"] in (kept["started_at"], kept["finished_at"]), seen["preview"])
        check("the publication time is the feed's stated instant, not a retrieval time",
              proposed["published_at"] == target["published"]["utc"] and
              proposed["published_at"] not in (kept["started_at"], kept["finished_at"]),
              [proposed["published_at"], target["published"]["utc"]])
        check("linked documents are named and not retrieved", preview["linked_documents"] and not publisher.requests,
              preview["linked_documents"])
        check("an import preview counts once; the server's fetch budget is untouched (no request)",
              used("import") == 1 and
              admin.get("/api/admin/usage").json()["server"]["publication_fetches"]["used"] == 0)
        # Exact confirmation into an owned source.
        confirm = {"text_sha256": proposed["text_sha256"], "confirm": True}
        changed = user.post(f"/api/user/news/imports/{preview['import_id']}/confirmation", headers=USER_WRITE,
                            json={"text_sha256": "0" * 64, "confirm": True})
        check("a confirmation of another text is refused", changed.json().get("code") == "publication_changed",
              changed.text[:200])
        confirmed = user.post(f"/api/user/news/imports/{preview['import_id']}/confirmation", headers=USER_WRITE,
                              json=confirm)
        check("the exact text is confirmed into one owned source", confirmed.status_code == 201, confirmed.text[:200])
        again = user.post(f"/api/user/news/imports/{preview['import_id']}/confirmation", headers=USER_WRITE,
                          json=confirm)
        check("a repeated confirmation creates nothing", again.status_code == 200 and not again.json()["created"])
        source = confirmed.json()["source"]
        stored = user.get(f"/api/user/sources/{source['source_id']}").json()["source"]
        check("the saved source is exactly the previewed text",
              stored.get("text") == proposed["text"] and used("source") == 1, used("source"))
        # Effort, quote, approval, one fake send.
        prepared = user.post("/api/user/analyses", headers=USER_WRITE,
                             json={"source_id": source["source_id"], "effort": "medium"})
        check("the analysis is prepared and counted", prepared.status_code == 201 and used("preparation") == 1,
              prepared.text[:200])
        analysis_id = prepared.json()["analysis"]["analysis_id"]
        reopened = user.post("/api/user/analyses", headers=USER_WRITE,
                             json={"source_id": source["source_id"], "effort": "medium"})
        check("reopening it counts nothing", reopened.status_code == 200 and used("preparation") == 1)
        quote = user.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={}).json()["quote"]
        ran = user.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE, json={
            "quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"], "approve": True})
        check("one approved run sends once to the fake provider and records",
              ran.status_code == 201 and len(provider.requests) == 1 and
              ran.json()["analysis"]["state"] == "recorded", ran.text[:200])
        recorded = ran.json()["analysis"]
        sent = json.loads(provider.requests[0])["messages"][0]["content"]
        sent_text = sent if isinstance(sent, str) else "".join(block.get("text", "") for block in sent)
        check("the request carries the imported publication's text", proposed["text"] in sent_text,
              [proposed["text"][:80], sent_text[:200]])
        quality = user.get(f"/api/user/analyses/{analysis_id}/quality").json()["quality"]
        seen["quality"] = {"rubric_version": quality["rubric_version"], "flagged": quality["flagged"],
                           "checks": [row["check"] for row in quality["findings"]]}
        check("research checks are flags for a person, never a score", quality["rejected"] == [] and
              "score" not in json.dumps(quality).lower() and len(quality["human_review"]) == 4)
        review = user.post(f"/api/user/analyses/{analysis_id}/reviews", headers=USER_WRITE, json={
            "parent_review_id": None, "result_sha256": recorded["result_sha256"], "status": "needs_revision",
            "notes": "SYNTHETIC review: the reply is a fake provider's, not a model reading."})
        check("the reader saves an own review", review.status_code == 201, review.text[:200])
        export = user.get(f"/api/user/analyses/{analysis_id}/export")
        check("the export is served", export.status_code == 200 and analysis_id in export.text, export.status_code)
        check("the whole journey made no publisher request and one provider request",
              publisher.requests == [] and len(provider.requests) == 1)
        seen["clock"] = {"start": START.isoformat(), "note": "synthetic; account, policy, quota and run times"}
        for client in (visitor, admin, user):
            client.close()
    check("the retained run folder is byte-identical afterwards", digests(records) == before)
    for label, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}  {label}" + (f"  {detail}" if detail and not passed else ""))
    failed = sum(1 for _, passed, _ in checks if not passed)
    print(f"{len(checks) - failed}/{len(checks)} passed")
    summary = {"journey": "qa-live-journey-1", "records": str(records), "observed": seen,
               "checks": [{"label": label, "passed": passed, "detail": detail} for label, passed, detail in checks]}
    print(json.dumps(seen, indent=1, default=str)[:6000])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=1, default=str, ensure_ascii=False) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
