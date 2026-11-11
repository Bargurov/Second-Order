"""``python -m second_order news relevance ...``: the operator's relevance commands (news_relevance, relevance_batches,
relevance_eval).

Reading only: ``queue`` (every current story's relevance and the next batch's candidates), ``status`` and ``packet`` of
a batch, and ``eval packet`` / ``eval baseline``. Local writes: ``preview`` (records a batch; a paid one saves each exact
request), ``import`` (an assistant's annotations, checked), ``review`` (an editor's judgement with a reason) and ``eval
measure --record``. A billed request: only ``approve``, with the batch's total repeated, --approve-paid-requests and the
key in the environment; each request is sent at most once, ever.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets

from . import news_relevance, news_views, relevance_batches, relevance_eval
from .accounts import AccountsRefused

CLI_ACTOR = "local-operator"


def add_commands(actions: argparse._SubParsersAction) -> None:
    relevance = actions.add_parser("relevance", help="Economic relevance: queue, batches, editor judgements, evaluation")
    steps = relevance.add_subparsers(dest="relevance_action", required=True)
    steps.add_parser("queue", help="Every current story's relevance and what a batch would assess (read-only)")
    preview = steps.add_parser("preview", help="Select and record an assessment batch; a paid one saves each request")
    preview.add_argument("--method", choices=relevance_batches.METHODS, required=True)
    preview.add_argument("--limit", type=int, default=relevance_batches.DEFAULT_LIMIT)
    preview.add_argument("--story", action="append", default=[], help="A story ID (repeatable) instead of the queue")
    preview.add_argument("--retry-failed", action="store_true", help="Also select stories whose last attempt failed")
    for name, text in (("status", "Each item's state now (read-only)"),
                       ("packet", "The rules, format and material an assistant annotates from (read-only)")):
        steps.add_parser(name, help=text).add_argument("batch_id")
    approve = steps.add_parser("approve", help="Send each saved request once (paid; needs the key)")
    approve.add_argument("batch_id")
    approve.add_argument("--estimated-max-usd-total", type=float, required=True)
    approve.add_argument("--approve-paid-requests", action="store_true", required=True)
    annotations = steps.add_parser("import", help="Save an assistant's annotations, checked against the material")
    annotations.add_argument("batch_id")
    annotations.add_argument("--annotations", type=Path, required=True)
    annotations.add_argument("--assistant-tool", required=True, help="The AI assistant the annotations were made with")
    annotations.add_argument("--assistant-model", default=None, help="Its model, only when you know it")
    judge = steps.add_parser("review", help="Record an editor's judgement of a story's relevance, with a reason")
    judge.add_argument("story_id")
    judge.add_argument("--verdict", choices=news_relevance.REVIEW_VERDICTS, required=True)
    judge.add_argument("--reason", required=True)
    evaluation = steps.add_parser("eval", help="The labelled evaluation sets (content/news-relevance)")
    evaluation.add_argument("eval_action", choices=("packet", "baseline", "measure"))
    evaluation.add_argument("--set", choices=relevance_eval.SET_NAMES, required=True,
                            help="holdout is a private option and needs its own file (SECOND_ORDER_RELEVANCE_HOLDOUT)")
    evaluation.add_argument("--annotations", type=Path, help="measure: the annotator's reply to the packet")
    evaluation.add_argument("--annotator", help="measure: who annotated (a tool, a person)")
    evaluation.add_argument("--annotator-model", default=None, help="measure: its model, only when known")
    evaluation.add_argument("--record", action="store_true", help="measure: keep the measurement (write-once)")


def run(args: argparse.Namespace, desk: news_views.Desk, now: datetime) -> dict:
    clock = lambda: datetime.now(timezone.utc)  # noqa: E731
    action = args.relevance_action
    try:
        if action == "queue":
            return relevance_batches.queue(desk, now)
        if action == "preview":
            batch, created = relevance_batches.preview(desk, now, args.method, args.limit, args.story or None,
                                                       args.retry_failed, CLI_ACTOR)
            return {"created": created, "batch": batch}
        if action == "status":
            return relevance_batches.status(desk, args.batch_id, now)
        if action == "packet":
            return relevance_batches.packet(desk, args.batch_id, now)
        if action == "approve":
            return _approve(args, desk, clock)
        if action == "import":
            reply = json.loads(args.annotations.read_text(encoding="utf-8"))
            return relevance_batches.import_annotations(desk, args.batch_id, reply, args.assistant_tool,
                                                        args.assistant_model, CLI_ACTOR, clock)
        if action == "review":
            story = news_views.world(desk, now)["stories"].get(args.story_id)
            if story is None:
                raise AccountsRefused(404, "not_found", f"{args.story_id} is not a current story.")
            result, created = news_relevance.review(desk.newsroom, args.story_id, {
                "verdict": args.verdict, "reason": args.reason,
                "idempotency_key": f"cli-relevance-{secrets.token_hex(8)}"},
                story["material"]["material_sha256"], CLI_ACTOR, now)
            return {"created": created, "review": result}
        return _evaluate(args, desk, now)
    except AccountsRefused as exc:
        raise SystemExit(json.dumps({"error": str(exc), "code": exc.code, **exc.extra}, indent=2)) from None
    except (OSError, ValueError) as exc:
        raise SystemExit(json.dumps({"error": str(exc)})) from None


def _approve(args: argparse.Namespace, desk: news_views.Desk, clock) -> dict:
    if desk.drafting is None:
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
    return relevance_batches.approve(desk, args.batch_id, {
        "batch_id": args.batch_id, "approve_paid_requests": args.approve_paid_requests,
        "estimated_max_usd_total": args.estimated_max_usd_total}, story_now, CLI_ACTOR, clock)


def _evaluate(args: argparse.Namespace, desk: news_views.Desk, now: datetime) -> dict:
    found = relevance_eval.load(args.set)
    if args.eval_action == "packet":
        return relevance_eval.packet(found)
    if args.eval_action == "baseline":
        reply = {"set": found["set"], "set_sha256": found["set_sha256"], "annotations": []}
        result = relevance_eval.measure(found, reply, {"tool": "none: the keyword rule only", "model": None})
        return {key: result[key] for key in ("set", "set_sha256", "cases", "label_status", "keyword_rule")} | {
            "keyword_disagreements": [{key: row[key] for key in ("case_id", "label", "keyword", "title")}
                                      for row in result["rows"]
                                      if (row["keyword"] == "relevant") != (row["label"] == "relevant")]}
    if args.annotations is None or not args.annotator:
        raise SystemExit(json.dumps({"error": "measure needs --annotations and --annotator."}))
    reply = json.loads(args.annotations.read_text(encoding="utf-8"))
    result = relevance_eval.measure(found, reply, {"tool": args.annotator, "model": args.annotator_model,
                                                   "annotations_sha256": relevance_eval.hashlib.sha256(
                                                       args.annotations.read_bytes()).hexdigest()})
    if args.record:
        result["recorded"] = str(relevance_eval.record_run(desk.newsroom.path.parent, result, now))
    return result
