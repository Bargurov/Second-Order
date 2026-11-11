"""Evaluation of the relevance decision (relevance-eval-0.1): labelled cases, kept apart from the feed, measured both ways.

The public sets live in content/news-relevance/: ``dev`` (cases the prompt and the decision may be developed against) and
``sample`` (a public, fictional sample for testing this tooling; it is NOT a held-out set). A ``holdout`` (cases kept
for measuring a version once it is settled: a change is never tuned on them) is a private option: it is read only from
the file the environment variable SECOND_ORDER_RELEVANCE_HOLDOUT names or, when present, from
content/news-relevance/private/holdout.json, which a public checkout does not contain. Each case is the
material an annotator would read (real official reports whose terms allow use by a model, as their feeds gave them, or
SYNTHETIC reports written for the set and marked as such; never a report whose publisher's terms forbid it), its
categories (paired cases share a ``pair``: similar words, different economic meaning) and a label: ``relevant``,
``outside_scope`` or ``insufficient_information``, with its status. ``provisional`` labels are the set author's
unreviewed judgement; only an editor's review makes a label ``reviewed``. Corrections the editors record on live
stories (news_relevance.review) are kept with their reasons; turning one into a case is an explicit, versioned edit of a
set, and nothing here learns or adjusts by itself.

``packet`` gives an annotator the cases' material and the same rules and format as a live assessment, without the
labels. ``measure`` checks each returned annotation (the schema, and its quotes against the case's material), applies
the relevance decision (news_relevance.decide) and counts, against the labels: irrelevant items admitted (labelled
outside the scope or insufficient, decided relevant), relevant items excluded (labelled relevant, decided outside the
scope) and relevant items held back (labelled relevant, decided needs review, insufficient or not annotated), with every
disagreement listed. It measures the earlier keyword rule (news-rank-0.2: a publisher's own topic or a subject's
keyword admitted a story) on the same cases. A model's confidence is never read as a probability: there is none in the
annotation, and agreement here is measured on a small set with provisional labels.
"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

from . import market_store, news_relevance as nr, relevance_requests as rr, user_news
from .news_registry import PUBLISHERS
from .newsroom_store import ROOT, stamp

EVAL_VERSION = "relevance-eval-0.1"
EVAL_DIR = ROOT / "content" / "news-relevance"
SETS = {"dev": "dev.json", "sample": "sample.json"}
HOLDOUT = "holdout"
HOLDOUT_ENV = "SECOND_ORDER_RELEVANCE_HOLDOUT"
SET_NAMES = (*SETS, HOLDOUT)
LABELS = ("relevant", "outside_scope", "insufficient_information")
LABEL_STATUS = ("provisional", "reviewed")
CATEGORIES = ("relevant", "irrelevant", "ambiguous", "similar_vocabulary", "no_financial_terms", "consumer_company",
              "official", "synthetic")


class EvalRefused(ValueError):
    pass


def holdout_path(folder: Path = EVAL_DIR) -> Path | None:
    """The private holdout file: the one SECOND_ORDER_RELEVANCE_HOLDOUT names, else the private folder's, else None."""
    named = os.environ.get(HOLDOUT_ENV)
    if named:
        return Path(named)
    default = folder / "private" / "holdout.json"
    return default if default.is_file() else None


def load(name: str, folder: Path = EVAL_DIR) -> dict:
    """A set as written, checked, with the SHA-256 of its exact bytes."""
    if name == HOLDOUT:
        path = holdout_path(folder)
        if path is None or not path.is_file():
            raise EvalRefused(f"There is no private holdout here: set {HOLDOUT_ENV} to its file. "
                              "The public sets are dev and sample.")
    elif name in SETS:
        path = folder / SETS[name]
    else:
        raise EvalRefused(f"The set is one of {', '.join(SET_NAMES)}.")
    data = path.read_bytes()
    found = json.loads(data.decode("utf-8"))
    cases = found.get("cases") if isinstance(found, dict) else None
    if found.get("set") != name or found.get("eval_version") != EVAL_VERSION or not isinstance(cases, list):
        raise EvalRefused(f"{path.name} is not a {EVAL_VERSION} {name} set.")
    seen = set()
    for case in cases:
        label = case.get("label") or {}
        if case.get("case_id") in seen or label.get("verdict") not in LABELS or \
                label.get("status") not in LABEL_STATUS or not case.get("reports") or \
                not set(case.get("categories") or []) <= set(CATEGORIES):
            raise EvalRefused(f"Case {case.get('case_id')} is malformed.")
        seen.add(case["case_id"])
        for report in case["reports"]:
            key = report.get("source")
            if not report.get("synthetic") and (key not in PUBLISHERS or PUBLISHERS[key].material != "permitted"):
                raise EvalRefused(f"Case {case['case_id']} holds a report whose publisher allows no use by a model.")
    return {**found, "set_sha256": hashlib.sha256(data).hexdigest()}


def _reports(case: dict) -> list[dict]:
    return [{"entry_id": row["id"], "publisher": row["publisher"], "role": row["role"],
             "published": row.get("published"), "title": row["title"], "excerpt": row.get("excerpt")}
            for row in case["reports"]]


def packet(found: dict) -> dict:
    """The cases' material, rules and format for an annotator, without the labels."""
    return {"eval_version": EVAL_VERSION, "set": found["set"], "set_sha256": found["set_sha256"],
            "versions": rr.versions(), "rules": rr.system_prompt(), "format": nr.response_schema(),
            "items": [{"case_id": case["case_id"],
                       "material": rr.payload(case["case_id"], case["reports"][0]["title"], _reports(case), {})}
                      for case in found["cases"]],
            "reply": {"set": found["set"], "set_sha256": found["set_sha256"],
                      "annotations": [{"case_id": "...", "annotation": {"report_kind": "...", "...": "..."}}]}}


def keyword_admits(case: dict) -> bool:
    """The earlier rule (news-rank-0.2): a report's publisher topic, or any subject keyword in its words, admitted it."""
    for row in case["reports"]:
        key = row.get("source")
        feed_topic = row.get("feed_topic") if row.get("synthetic") else PUBLISHERS[key].interest
        if feed_topic or user_news.topics(key or "synthetic", row["title"], row.get("excerpt")):
            return True
    return False


def _outcome(label: str, decided: str) -> str:
    if label == "relevant":
        return "admitted" if decided == "relevant" else "excluded" if decided == "outside_scope" else "held"
    return "irrelevant_admitted" if decided == "relevant" else "kept_out"


def _counts(rows: list[dict], field: str) -> dict:
    relevant = [row for row in rows if row["label"] == "relevant"]
    others = [row for row in rows if row["label"] != "relevant"]
    outcomes = [_outcome(row["label"], row[field]) for row in rows]
    count = {name: outcomes.count(name) for name in ("admitted", "excluded", "held", "irrelevant_admitted",
                                                     "kept_out")}
    return {**count, "labelled_relevant": len(relevant), "labelled_not_relevant": len(others),
            "irrelevant_admitted_share": round(count["irrelevant_admitted"] / len(others), 3) if others else None,
            "relevant_not_admitted_share": round((count["excluded"] + count["held"]) / len(relevant), 3)
            if relevant else None}


def measure(found: dict, reply: object, annotator: dict) -> dict:
    """Each case's decision from the returned annotation, against its label, and the earlier keyword rule's."""
    if not isinstance(reply, dict) or reply.get("set") != found["set"] or \
            reply.get("set_sha256") != found["set_sha256"] or not isinstance(reply.get("annotations"), list):
        raise EvalRefused("The annotations must name this set and its SHA-256, as the packet gave them.")
    given = {row.get("case_id"): row.get("annotation") for row in reply["annotations"] if isinstance(row, dict)}
    rows = []
    for case in found["cases"]:
        label = case["label"]["verdict"]
        row = {"case_id": case["case_id"], "label": label, "label_status": case["label"]["status"],
               "categories": case["categories"], "pair": case.get("pair"), "title": case["reports"][0]["title"],
               "keyword": "relevant" if keyword_admits(case) else "outside_scope"}
        if case["case_id"] not in given:
            rows.append({**row, "decided": "unavailable", "detail": "No annotation was returned."})
            continue
        try:
            annotation = nr.validated(given[case["case_id"]])
        except nr.AnnotationRejected as exc:
            rows.append({**row, "decided": "unavailable", "detail": str(exc)})
            continue
        checked = nr.check_evidence(annotation, rr.sources(_reports(case), {}))
        decision = nr.decide(annotation, checked)
        rows.append({**row, "decided": decision["state"], "verdict": annotation["verdict"],
                     "report_kind": annotation["report_kind"], "reasons": decision["reasons"],
                     "explanation": annotation["explanation"], "quotes_found": checked["found"],
                     "quotes_not_found": checked["not_found"]})
    for row in rows:
        row["agrees"] = _outcome(row["label"], row["decided"]) in ("admitted", "kept_out") and \
            (row["label"] != "insufficient_information" or row["decided"] != "relevant")
    statuses = {status: sum(1 for case in found["cases"] if case["label"]["status"] == status)
                for status in LABEL_STATUS}
    return {"eval_version": EVAL_VERSION, "set": found["set"], "set_sha256": found["set_sha256"],
            "cases": len(rows), "label_status": statuses, "versions": rr.versions(),
            "decision_version": nr.DECISION_VERSION, "annotator": annotator,
            "decision": _counts(rows, "decided"), "keyword_rule": _counts(rows, "keyword"),
            "disagreements": [row for row in rows if not row["agrees"]], "rows": rows,
            "statement": ("Counts against the set's labels"
                          + (", which are provisional (not reviewed by an editor)" if statuses["provisional"] else "")
                          + ". irrelevant_admitted: labelled outside the scope or insufficient, decided relevant. "
                          "excluded: labelled relevant, decided outside the scope. held: labelled relevant, decided "
                          "needs review, insufficient or unavailable (not admitted, not rejected). A small set measures "
                          "agreement with its labels, not accuracy in general; no confidence is calibrated here.")}


def record_run(folder: Path, result: dict, moment: datetime) -> Path:
    """Keep a measurement, write-once, under the newsroom's folder (relevance-evals/)."""
    body = {**result, "measured_at": stamp(moment)}
    run_id = "reval-" + hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    target = folder / "relevance-evals" / f"{run_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    market_store.write_exclusive(target, {**body, "run_id": run_id})
    return target
