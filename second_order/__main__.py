"""Explicit offline commands. There is no provider call or automatic fallback."""
import argparse
from datetime import date, datetime, timezone
import json
import os
import sqlite3
from pathlib import Path
import sys
from pydantic import ValidationError
from .demo import demo_only, load_market, run_demo
from .dossier import PREPARED_DIR, prepare
from .draft_views import DRAFTS_DIR, prepare_drafts
from .drafts import freeze_draft
from .evaluation import evaluate, rules_configurations, scoreboard
from .schema import Hypothesis, parse_output
from .data import ny_date
from .snapshots import evaluate_bound, list_snapshots, load_snapshot, snapshot_readiness, snapshot_revisions
from .store import connect_read_only, freeze, migrate_store, open_store, read_evaluations, save_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Second Order offline research core")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run two showcase replays of fictional events on the invented "
                                             "demonstration series, without an API key")
    demo.add_argument("--db", default=":memory:")
    commands.add_parser("schema", help="Print the strict hypothesis JSON Schema")
    freeze_command = commands.add_parser("freeze", help="Append a validated hypothesis to a new v2 database")
    freeze_command.add_argument("hypothesis", type=Path)
    freeze_command.add_argument("--db", required=True)
    freeze_command.add_argument("--baseline", help="Existing snapshot to bind for source-bound legs")
    drafting = commands.add_parser("freeze-draft",
                                   help="Freeze a manual prospective showcase draft at the current UTC time")
    drafting.add_argument("draft", type=Path, help="Draft JSON without a freeze time; it is never modified")
    drafting.add_argument("--db", required=True)
    drafting.add_argument("--baseline", required=True, help="Existing snapshot to bind at freeze")
    drafting_model = commands.add_parser(
        "model-draft", help="Offline: preview a model drafting request or validate a saved response; never calls a model")
    drafting_model.add_argument("--event", type=Path, required=True,
                                help="Operator JSON with headline, source_url, published_at and story_id")
    drafting_model.add_argument("--source", type=Path, required=True, help="Source text file (UTF-8)")
    drafting_model.add_argument("--model", help="Model ID recorded in the request (default: the adapter default)")
    drafting_mode = drafting_model.add_mutually_exclusive_group(required=True)
    drafting_mode.add_argument("--print-request", action="store_true", help="Print the exact request and its hash")
    drafting_mode.add_argument("--response", type=Path, help="Saved Messages API response to validate offline")
    evaluation = commands.add_parser("evaluate", help="Explicitly evaluate stored hypotheses: baseline-bound ones with "
                                     "--outcome, and those on the fictional demonstration series against the demo "
                                     "fixture; every other one is skipped")
    evaluation.add_argument("--db", required=True)
    evaluation.add_argument("--as-of", required=True, help="Timezone-aware ISO timestamp")
    evaluation.add_argument("--outcome", help="Outcome snapshot for hypotheses bound to a baseline at freeze")
    preparation = commands.add_parser("prepare", help="Explicitly write read-only Dossier views")
    preparation.add_argument("--out", type=Path, default=PREPARED_DIR)
    preparation.add_argument("--db", help="Also prepare frozen store cases (opened read-only)")
    preparation.add_argument("--evaluation", action="append", default=[], metavar="HYPOTHESIS=EVALUATION",
                             help="Stored evaluation to show when a case has several")
    drafting_views = commands.add_parser(
        "prepare-drafts", help="Explicitly write read-only review views of selected saved draft attempts")
    drafting_views.add_argument("--attempt", type=Path, action="append", required=True,
                                help="A saved pilot attempt directory (repeatable); it is only read")
    drafting_views.add_argument("--out", type=Path, default=DRAFTS_DIR)
    serve = commands.add_parser("serve", help="Serve the local review UI; never evaluates, freezes or fetches")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--prepared", type=Path, default=PREPARED_DIR)
    serve.add_argument("--static", type=Path, default=None,
                       help="The admin build, served to administrators only (default: frontend/dist)")
    serve.add_argument("--client-static", type=Path, default=None,
                       help="The user client build, served to users and to the sign-in page (default: "
                            "frontend/dist-client)")
    serve.add_argument("--accounts", type=Path, default=None,
                       help="The accounts store: identities, roles, sessions, credits and limits (default: "
                            "data/accounts/accounts.db). It must exist; see `accounts add-admin`")
    serve.add_argument("--drafts", type=Path, default=DRAFTS_DIR, help="Prepared draft review views")
    serve.add_argument("--store", type=Path, default=None,
                       help="The research store the lifecycle pages read and, on explicit approval, write (default: "
                            "data/real/second-order.db). Pages never choose another path")
    serve.add_argument("--enable-paid-drafts", action="store_true",
                       help="Allow the Tracker to send one explicitly approved, billed Claude request per capture. "
                            "Needs the key in SECOND_ORDER_ANTHROPIC_API_KEY; off by default (local mock only)")
    serve.add_argument("--enable-paid-triage", action="store_true",
                       help="Allow the Event Inbox to send one explicitly approved, billed Claude Haiku 5.5 headline "
                            "triage request per prepared selection. Needs the key in SECOND_ORDER_ANTHROPIC_API_KEY; "
                            "off by default (local simulation only)")
    serve.add_argument("--enable-market-retrieval", action="store_true",
                       help="Allow market context to send one explicitly approved request per previewed plan for the "
                            "Federal Reserve Board's complete H.15 release package, from which the 2-year and 10-year "
                            "yields are read (keyless, free). Off by default: local data only")
    serve.add_argument("--enable-publication-import", action="store_true",
                       help="With accounts, allow a user's explicit import preview to request one allowlisted official "
                            "publication page (keyless, free; no redirects or retries), counted against the usage "
                            "policy's daily publication fetches. Off by default: nothing is requested, and users paste "
                            "the text instead")
    from . import fuels_snapshots  # Local files only, like the fuels commands below.
    serve.add_argument("--fuels-snapshots", type=Path, default=fuels_snapshots.SNAPSHOTS_DIR, metavar="PATH",
                       help="The fuels page's snapshot folder (default: this checkout's data/fuels/snapshots). "
                            "Snapshots are per checkout: a worktree's server can read the main checkout's folder")
    serve.add_argument("--enable-paid-briefs", action="store_true",
                       help="Allow the News desk to send one explicitly approved, billed Claude request per previewed "
                            "brief draft. Needs the key in SECOND_ORDER_ANTHROPIC_API_KEY; off by default (briefs are "
                            "written by the editors or compiled from the reports' own words at $0)")
    research_readiness = commands.add_parser(
        "research-readiness", help="Read-only: what can be frozen prospectively now, what is missing and the next "
                                   "explicit action, per registry entry (never fetches, imports or freezes)")
    research_readiness.add_argument("--db", type=Path, default=None,
                                    help="The research store, opened read-only (default: data/real/second-order.db)")
    research_readiness.add_argument("--published", type=date.fromisoformat, default=None,
                                    help="Publication date (New York) of the event considered (default: today)")
    research_readiness.add_argument("--packages-dir", type=Path, default=None,
                                    help="Market-context folder holding packages/ (default: data/market-context)")
    pilot = commands.add_parser("pilot-ledger", help="Read-only: the FOMC pilot's ledger, one case per scheduled "
                                                     "statement (its first freeze), from the store and the pilot "
                                                     "definition; never writes")
    pilot.add_argument("--db", type=Path, default=None,
                       help="The research store, opened read-only (default: data/real/second-order.db)")
    pilot.add_argument("--definition", type=Path, default=None,
                       help="The pilot definition (default: content/pilot/fomc-pilot.json)")
    pilot.add_argument("--table", action="store_true", help="Print a plain text table instead of JSON")
    board = commands.add_parser("scoreboard", help="Read-only research summaries for one rules configuration")
    board.add_argument("--db", required=True)
    board.add_argument("--rules-hash", help="Configuration to summarize; omit to list the stored configurations")
    store = commands.add_parser("store", help="Explicit store maintenance")
    store_actions = store.add_subparsers(dest="store_action", required=True)
    migration = store_actions.add_parser("migrate", help="Bring a schema-1, 2 or 3 store to schema 4 by adding "
                                                         "tables; existing rows are untouched")
    migration.add_argument("--db", required=True)
    packages = commands.add_parser("market-packages",
                                   help="Kept H.15 release packages of market context: list them, or validate them "
                                        "locally (never fetches)")
    package_actions = packages.add_subparsers(dest="package_action", required=True)
    package_actions.add_parser("list", help="Every kept package and its validation status (read-only)")
    package_actions.add_parser("validate", help="Validate each kept package that has no validation record for the "
                                                "current parser version; writes that record once, fetches nothing")
    market = commands.add_parser("market", help="Market snapshots: two explicit imports (FRED over the network, a kept "
                                                "H.15 package locally); every other action reads")
    market_actions = market.add_subparsers(dest="market_action", required=True)
    importer = market_actions.add_parser("import", help="Fetch DGS2/DGS10 from FRED (needs FRED_API_KEY in the environment)")
    importer.add_argument("--db", required=True)
    importer.add_argument("--start", required=True, type=date.fromisoformat, help="First observation date")
    importer.add_argument("--vintage", type=date.fromisoformat, help="FRED real-time date (default: today, New York)")
    package_importer = market_actions.add_parser(
        "import-package", help="Copy the 2- and 10-year series of a kept, validated H.15 release package into a store "
                               "snapshot (local only: never fetches; repeating it reuses the snapshot)")
    package_importer.add_argument("--db", required=True)
    package_importer.add_argument("--package", required=True, help="Kept package ID (see `market-packages list`)")
    package_importer.add_argument("--start", required=True, type=date.fromisoformat, help="First observation date")
    package_importer.add_argument("--packages-dir", type=Path, default=None,
                                  help="Market-context folder holding packages/ (default: data/market-context)")
    listing = market_actions.add_parser("snapshots", help="List stored snapshots (read-only)")
    listing.add_argument("--db", required=True)
    comparison = market_actions.add_parser("diff", help="Revisions between two stored snapshots (read-only)")
    comparison.add_argument("--db", required=True)
    comparison.add_argument("old")
    comparison.add_argument("new")
    readiness = market_actions.add_parser("readiness", help="History a snapshot of either provider offers the scorer "
                                                           "(read-only)")
    readiness.add_argument("--db", required=True)
    readiness.add_argument("--snapshot", required=True)
    readiness.add_argument("--published", type=date.fromisoformat,
                           help="Publication date (New York); history must be dated before it")
    accounts_command = commands.add_parser("accounts", help="The accounts store: create the first administrator, "
                                                            "list the accounts (read-only) or upgrade the store")
    accounts_actions = accounts_command.add_subparsers(dest="accounts_action", required=True)
    first_admin = accounts_actions.add_parser("add-admin", help="Create an administrator account; the password is "
                                                                "typed at a prompt, never read from a file, argument "
                                                                "or the environment. Creates the store if missing")
    first_admin.add_argument("--username", required=True)
    first_admin.add_argument("--display-name", default=None)
    accounts_listing = accounts_actions.add_parser("list", help="Every account with its role and status (read-only)")
    accounts_upgrade = accounts_actions.add_parser("upgrade", help="Bring an accounts-1 or accounts-2 store to the "
                                                                  "current version; every existing account and "
                                                                  "record is kept")
    for command in (first_admin, accounts_listing, accounts_upgrade):
        command.add_argument("--accounts", type=Path, default=None,
                             help="The accounts store (default: data/accounts/accounts.db)")
    rate = commands.add_parser("rate-context",
                               help="Market-implied rate path from an Atlanta Fed MPT workbook you already hold: keep it "
                                    "and prepare a saved event's context, locally (never fetches)")
    rate_actions = rate.add_subparsers(dest="rate_action", required=True)
    retaining = rate_actions.add_parser("retain", help="Verify a workbook against the SHA-256 you name and keep it "
                                                       "privately with its acquisition and validation records")
    retaining.add_argument("--workbook", type=Path, required=True, help="The downloaded workbook; it is only read")
    retaining.add_argument("--sha256", required=True, help="The SHA-256 you expect; any other file is refused")
    retaining.add_argument("--obtained-on", required=True, type=date.fromisoformat, help="The date it was obtained")
    retaining.add_argument("--method", required=True, help="How it was obtained, in words (kept with the record)")
    preparing = rate_actions.add_parser("prepare", help="Write a saved event's rate-path context from the retained "
                                                        "workbook; run again, it derives it again and compares")
    preparing.add_argument("--capture", required=True, help="The saved event's capture ID")
    preparing.add_argument("--source", help="The retained workbook's source ID, when more than one is kept")
    showing = rate_actions.add_parser("show", help="The verified view the event pages read (read-only)")
    showing.add_argument("--capture", required=True, help="The saved event's capture ID")
    for command in (retaining, preparing, showing):
        command.add_argument("--data-dir", type=Path, default=None,
                             help="Folder holding intake/, event-links/ and rate-context/ (default: data)")
    from . import news_cli
    news_cli.add_commands(commands)
    from . import fuels_cli
    fuels_cli.add_commands(commands)
    from . import event_chain_cli  # Working session only: pins a written chain version's evidence from local files.
    event_chain_cli.add_commands(commands)
    from . import publication_comparison_cli  # Working session only: pins a written comparison version's evidence.
    publication_comparison_cli.add_commands(commands)
    args = parser.parse_args()
    try:
        if args.command == "schema":
            result = Hypothesis.model_json_schema()
        elif args.command == "demo":
            result = run_demo(args.db)
        elif args.command == "prepare":
            selections = {}
            for choice in args.evaluation:
                hypothesis_id, separator, evaluation_id = choice.partition("=")
                if not separator or not hypothesis_id or not evaluation_id:
                    raise ValueError("--evaluation takes HYPOTHESIS=EVALUATION")
                selections[hypothesis_id] = evaluation_id
            if selections and args.db is None:
                raise ValueError("--evaluation selects among stored evaluations; name the store with --db")
            result = prepare(args.out, args.db, selections)
        elif args.command == "prepare-drafts":
            result = prepare_drafts(args.attempt, args.out)
        elif args.command == "store":
            result = migrate_store(args.db)
        elif args.command == "freeze-draft":
            draft = json.loads(args.draft.read_text(encoding="utf-8"))
            connection = open_store(args.db)
            try:
                result = freeze_draft(connection, draft, args.baseline)
            finally:
                connection.close()
        elif args.command == "model-draft":
            # Offline only: this command never constructs an HTTP client, so no model can be called.
            from .model_draft import PROMPT_VERSION, build_request, digest, draft_from_saved_response, operator_event
            operator = json.loads(args.event.read_text(encoding="utf-8"))
            source_text = args.source.read_bytes().decode("utf-8")  # Exact text; line endings are not rewritten.
            if args.print_request:
                event, _ = operator_event(operator, lambda: datetime.now(timezone.utc))
                request = build_request(event, source_text, args.model)
                result = {"prompt_version": PROMPT_VERSION, "prompt_hash": digest(request), "request": request,
                          "note": "Preview only; nothing was sent."}
            else:
                result = draft_from_saved_response(args.response.read_bytes(), operator, source_text, args.model)
        elif args.command == "market-packages":
            from . import market_retrieval, market_store  # Local files only; no fetcher is constructed here.
            if args.package_action == "list":
                _, problems, kept = market_store.local_data(market_store.STORE_DIR, None)
                result = {"packages": kept, "problems": problems}
            else:
                result = {"validated": market_retrieval.validate_packages(market_store.STORE_DIR),
                          "note": "Local work only: nothing was fetched."}
        elif args.command == "accounts":
            from . import accounts
            path = args.accounts or accounts.ACCOUNTS_PATH
            if args.accounts_action == "list":
                result = {"accounts": accounts.list_users(accounts.Accounts.open(path)), "store": str(path)}
            elif args.accounts_action == "upgrade":
                result = {"upgraded": accounts.upgrade_store(path), "schema": accounts.store_version(path),
                          "store": str(path)}
            else:
                import getpass
                password = getpass.getpass("New administrator password: ")
                if getpass.getpass("Repeat the password: ") != password:
                    raise ValueError("The passwords differ; no account was created")
                if not path.exists():
                    accounts.create_store(path)
                created = accounts.create_user(accounts.Accounts.open(path), args.username,
                                               args.display_name or args.username, "admin", password, "local-command")
                result = {"created": created, "store": str(path)}
        elif args.command == "news":  # Only `news refresh` requests anything: each connected publisher feed once.
            result = news_cli.run(args)
        elif args.command == "fuels":
            result = fuels_cli.run(args)
        elif args.command == "event-chains":
            result = event_chain_cli.run(args)
        elif args.command == "comparisons":
            result = publication_comparison_cli.run(args)
        elif args.command == "rate-context":
            from . import rate_context  # Local files only; nothing on this path fetches or sends.
            folders = rate_context.folders_in(args.data_dir or rate_context.RATE_DIR.parent)
            if args.rate_action == "retain":
                result = rate_context.retain(args.workbook, args.sha256, args.obtained_on, args.method, folders.rate)
            elif args.rate_action == "prepare":
                result = rate_context.prepare(args.capture, folders, args.source)
            else:
                result = rate_context.view(args.capture, folders)
        elif args.command == "research-readiness":
            from . import market_store
            from .freeze_origins import STORE_PATH, Folders
            from .research_readiness import report  # Reads only; no fetcher or writer is constructed.
            result = report(Folders(store=args.db or STORE_PATH, market=args.packages_dir or market_store.STORE_DIR),
                            published=args.published)
        elif args.command == "pilot-ledger":
            from .freeze_origins import STORE_PATH
            from .pilot_ledger import DEFINITION, ledger, load_definition, table  # Reads only.
            result = ledger(load_definition(args.definition or DEFINITION), args.db or STORE_PATH)
            if args.table:
                print(table(result))
                return 0
        elif args.command == "market" and args.market_action == "import-package":
            from . import market_store
            from .package_snapshots import import_package  # Reads a kept package; no network path is loaded.
            connection = open_store(args.db)
            try:
                stored = import_package(connection, args.package, args.start, args.packages_dir or market_store.STORE_DIR)
                result = {"stored": stored,
                          "readiness": snapshot_readiness(load_snapshot(connection, stored["snapshot_id"]))}
            finally:
                connection.close()
        elif args.command == "market" and args.market_action == "import":
            from .fred import ImportRefused, import_and_report  # The only network path; loaded only here.
            api_key = os.environ.get("FRED_API_KEY", "")
            if not api_key:
                raise ImportRefused("FRED_API_KEY is not set; only the import command reads it")
            connection = open_store(args.db)
            try:
                result = import_and_report(connection, api_key, args.start, args.vintage)
            finally:
                connection.close()
        elif args.command == "market":
            connection = connect_read_only(args.db)
            try:
                if args.market_action == "snapshots":
                    result = list_snapshots(connection)
                elif args.market_action == "readiness":
                    result = snapshot_readiness(load_snapshot(connection, args.snapshot), before=args.published)
                else:
                    result = snapshot_revisions(load_snapshot(connection, args.old), load_snapshot(connection, args.new))
            finally:
                connection.close()
        elif args.command == "scoreboard":
            evaluations = read_evaluations(args.db)
            if args.rules_hash is None:
                result = {"configurations": rules_configurations(evaluations),
                          "note": "Select one configuration with --rules-hash; configurations are never pooled."}
            else:
                result = {kind: scoreboard(evaluations, kind, args.rules_hash) for kind in ("prospective", "replay")}
        elif args.command == "serve":
            import uvicorn
            from . import accounts
            from .api import CLIENT_STATIC_DIR, STATIC_DIR, create_app
            from .paid_drafts import PaidSender, key_problem
            from .triage_flow import TriageSenders
            paid, paid_triage = None, None
            if args.enable_paid_drafts:  # Explicit per run; the key is checked for shape only and never printed.
                paid = PaidSender.from_environment()
                problem = key_problem(paid.api_key())
                if problem:
                    print(json.dumps({"error": f"{problem}; the server was not started with paid sending"}),
                          file=sys.stderr)
                    return 1
            if args.enable_paid_triage:  # A separate opt-in: enabling paid drafts never enables paid triage.
                paid_triage = PaidSender.from_environment()
                problem = key_problem(paid_triage.api_key())
                if problem:
                    print(json.dumps({"error": f"{problem}; the server was not started with paid triage"}),
                          file=sys.stderr)
                    return 1
            accounts_path = args.accounts or accounts.ACCOUNTS_PATH
            if not accounts_path.is_file():  # Accounts are never created by starting a server.
                print(json.dumps({"error": f"No accounts store exists at {accounts_path}. Create the first administrator "
                                           "with: python -m second_order accounts add-admin --username NAME"}),
                      file=sys.stderr)
                return 2
            from .market_retrieval import ReleaseFetcher
            market_fetcher = ReleaseFetcher() if args.enable_market_retrieval else None  # Never a key: none is needed.
            from .publication_import import PublicationFetcher
            publication_fetcher = PublicationFetcher() if args.enable_publication_import else None  # Keyless.
            desk = None
            if args.enable_paid_briefs:  # A separate opt-in, like paid triage.
                from dataclasses import replace
                desk = replace(news_cli.default_desk(), drafting=PaidSender.from_environment())
                problem = key_problem(desk.drafting.api_key())
                if problem:
                    print(json.dumps({"error": f"{problem}; the server was not started with paid brief drafting"}),
                          file=sys.stderr)
                    return 1
            from .lifecycle import STORE_PATH
            uvicorn.run(create_app(args.prepared, args.static or STATIC_DIR, args.drafts, paid=paid,
                                   triage_senders=TriageSenders(paid=paid_triage), market_fetcher=market_fetcher,
                                   store=args.store or STORE_PATH, accounts=accounts_path,
                                   client_static=args.client_static or CLIENT_STATIC_DIR,
                                   publication_fetcher=publication_fetcher, desk=desk,
                                   fuels_snapshots=args.fuels_snapshots),
                        host=args.host, port=args.port)
            return 0
        else:
            now = datetime.now(timezone.utc)
            hypothesis = parse_output(args.hypothesis.read_text(encoding="utf-8")) if args.command == "freeze" else None
            connection = open_store(args.db)
            try:
                if args.command == "freeze":
                    result = {"hypothesis_id": freeze(connection, hypothesis, now, args.baseline)}
                    if args.baseline:
                        result["baseline_readiness"] = snapshot_readiness(
                            load_snapshot(connection, args.baseline), before=ny_date(hypothesis.event.published_at))
                else:
                    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
                    market = load_market()
                    bound = {row[0] for row in connection.execute("SELECT hypothesis_id FROM freeze_bindings")}
                    result = []
                    for identity, payload in connection.execute(
                            "SELECT id,payload FROM hypotheses ORDER BY recorded_at").fetchall():
                        if identity in bound:
                            if args.outcome is None:
                                result.append({"hypothesis_id": identity,
                                               "skipped": "Bound to a baseline snapshot at freeze; pass --outcome"})
                                continue
                            outcome = evaluate_bound(connection, identity, args.outcome, as_of)
                        else:
                            stored = parse_output(payload)
                            if not demo_only(stored):  # The demo fixture holds only the fictional series.
                                result.append({"hypothesis_id": identity,
                                               "skipped": "Not bound to a baseline snapshot, and not every leg is a "
                                                          "fictional demonstration series; nothing supplies its "
                                                          "data, so no evaluation is appended"})
                                continue
                            outcome = evaluate(stored, market, as_of)
                        save_evaluation(connection, identity, outcome, now)
                        result.append({"hypothesis_id": identity, **outcome})
            finally:
                connection.close()
        # A console shows Unicode directly. Piped or redirected output is ASCII JSON: a Windows pipe uses a
        # legacy code page, and Windows PowerShell re-decodes native output with the console code page, so raw
        # non-ASCII text either fails to encode or arrives corrupted. JSON escapes decode to the same value.
        print(json.dumps(result, indent=2, ensure_ascii=not sys.stdout.isatty()))
        return 0
    except (ValueError, ValidationError, OSError, sqlite3.Error) as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
