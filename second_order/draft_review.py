"""Offline review kit for the drafting adapter: synthetic cases, their rubrics and a runner.

Run it with `python -m second_order.draft_review`. The runner reads only the response files it is
given, validates each with the existing adapter (`draft_from_saved_response`) and lays the case's
rubric beside the result. It never calls a model, freezes a draft or opens a database.

Two judgments stay separate:
- structural validation (code): the response submitted one draft that passed the adapter's strict
  checks, submitted no draft, or was refused. The runner reports the adapter's decision unchanged.
- reasoning review (a person): whether the reasoning suits the case, judged against its rubric. The
  runner never scores it, and a structurally valid draft is not thereby acceptable.

Every case is synthetic. A response is labelled synthetic (written to exercise the kit, not model
output) or saved (its origin, model and pairing with the case's request are unverified). Nothing
here demonstrates model quality.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Callable
from .model_draft import (DEFAULT_MODEL, PROMPT_VERSION, STOP_REASONS, DraftRefused, build_request, digest,
                          draft_from_saved_response, envelope, operator_event, prospective_observables, strict_json)

KIT_VERSION = "draft-review-kit-1"
CASES_DIR = Path(__file__).resolve().parent.parent / "draft_review" / "cases"
CASE_FIELDS = ("id", "title", "probes", "synthetic", "operator", "source_text", "rubric")
RUBRIC_FIELDS = ("declining_to_draft", "defensible_directions", "direction_note", "acceptable_reasoning",
                 "required_uncertainties", "leakage_flags", "unacceptable_claims")
RUBRIC_LISTS = ("acceptable_reasoning", "required_uncertainties", "unacceptable_claims")
DECLINING = ("preferred", "acceptable", "allowed")
DIRECTIONS = ("up", "down")
# The adapter's own wording for a reply that stopped without submitting a draft.
NO_DRAFT = tuple(f"No draft: {STOP_REASONS[stop]}" for stop in ("end_turn", "refusal"))
PROVENANCE = {
    "synthetic": "Synthetic: written to exercise the kit, not produced by a model. Its model field and content were "
                 "authored, so it says nothing about any model's reasoning.",
    "saved": "Saved response, unverified: the runner cannot verify that a model produced it, which model did, or "
             "that it answers this case's request. No model was called.",
}
OUTCOMES = {
    "draft": "The response submitted one draft and it passed the adapter's strict checks (envelope, single tool "
             "call, schema, registry, offered observables, map rules). This is structure only, not the quality "
             "or truth of the reasoning.",
    "no draft": "The response submitted no draft: the model ended without calling the draft tool, or declined. "
                "Whether declining suits this case belongs to the reasoning review.",
    "refused": "The adapter refused the response as invalid or unusable, so there is no draft to review. A "
               "refusal is not a decline.",
}
REVIEW_STATUS = {
    "draft": "Not reviewed. A person judges the draft against the rubric; the runner does not score reasoning.",
    "no draft": "Not reviewed. A person judges whether declining suits this case (rubric.declining_to_draft), "
                "reading any text the response gave in response_text.",
    "refused": "Nothing to review: there is no draft. The rubric is shown for reference.",
}
# Reasoning criteria for any submitted draft, beside each case's own rubric. A person applies them; they
# are not checked by code, and a draft can satisfy the schema while failing every one.
COMMON_CRITERIA = (
    "Link: a yield that responds to a channel (the expected policy path, inflation expectations, term premium) "
    "is a proxy for it; direct only when the observable is itself the quantity the channel names.",
    "Magnitude: no comparison of move sizes across legs (such as 'falls by less') without support in the source. "
    "Legs may use different horizons; each is ranked against its own history.",
    "Competing influences: each one names its channel and the direction it would push the affected observable, "
    "consistent with that channel; a generic list of risks does not count.",
    "Unrelated news: the uncertainties include that other news or data during the scored window can move the "
    "observables.",
    "Survey versus pricing: a forecaster survey is not market pricing; a decision that differs from a survey "
    "forecast is not shown to be an unpriced market surprise.",
)
NOTICE = ("Offline: no model was called, nothing was frozen and no database was opened.",
          "Structural validation is the adapter's decision; reasoning review is a person's judgment against each "
          "case's rubric. They are reported separately and never combined into a score.",
          "Every case is synthetic and no response here is verified model output, so this report does not "
          "demonstrate model quality.")


def text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_case(case: object, name: str, clock: Callable[[], datetime]) -> dict:
    """A case is validated strictly; the adapter itself checks its operator event and source text."""
    def problem(detail: str) -> ValueError:
        return ValueError(f"Case {name}: {detail}")

    if not isinstance(case, dict) or set(case) != set(CASE_FIELDS):
        raise problem(f"a case must be an object with exactly {', '.join(CASE_FIELDS)}")
    if case["id"] != name:
        raise problem("its id must match its file name")
    if case["synthetic"] is not True:
        raise problem("every case in this kit must be synthetic")
    if not (text(case["title"]) and text(case["probes"])):
        raise problem("title and probes must be non-empty strings")
    try:
        event, _ = operator_event(case["operator"], clock)
        build_request(event, case["source_text"])
    except DraftRefused as exc:
        raise problem(str(exc)) from None
    rubric = case["rubric"]
    if not isinstance(rubric, dict) or set(rubric) != set(RUBRIC_FIELDS):
        raise problem(f"the rubric must have exactly {', '.join(RUBRIC_FIELDS)}")
    declining = rubric["declining_to_draft"]
    if not (isinstance(declining, dict) and set(declining) == {"stance", "guidance"}
            and declining["stance"] in DECLINING and text(declining["guidance"])):
        raise problem(f"declining_to_draft needs a stance ({', '.join(DECLINING)}) and guidance")
    for field in RUBRIC_LISTS:
        if not (isinstance(rubric[field], list) and rubric[field] and all(text(item) for item in rubric[field])):
            raise problem(f"{field} must be a non-empty list of non-empty strings")
    if not text(rubric["direction_note"]):
        raise problem("direction_note must be a non-empty string")
    offered = set(prospective_observables())
    directions, flags = rubric["defensible_directions"], rubric["leakage_flags"]
    if not (isinstance(directions, dict) and set(directions) == offered and all(
            isinstance(listed, list) and all(item in DIRECTIONS for item in listed) and len(set(listed)) == len(listed)
            for listed in directions.values())):
        raise problem("defensible_directions must list up, down, both or neither for each offered observable")
    if not (isinstance(flags, dict) and set(flags) == offered and all(
            isinstance(flag, dict) and set(flag) == {"headline_reports_move", "reason"}
            and isinstance(flag["headline_reports_move"], bool) and text(flag["reason"]) for flag in flags.values())):
        raise problem("leakage_flags must give headline_reports_move and a reason for each offered observable")
    return case


def load_cases(folder: Path = CASES_DIR,
               clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict[str, dict]:
    cases = {}
    for path in sorted(folder.glob("*.json")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Case {path.stem}: not valid JSON ({exc.msg})") from None
        cases[path.stem] = check_case(case, path.stem, clock)
    if not cases:
        raise ValueError(f"No case files in {folder}")
    return cases


def pick(cases: dict[str, dict], case_id: str) -> dict:
    if case_id not in cases:
        raise ValueError(f"Unknown case {case_id!r}; known cases: {', '.join(sorted(cases))}")
    return cases[case_id]


def case_request(case: dict, model: str | None, clock: Callable[[], datetime]) -> dict:
    event, _ = operator_event(case["operator"], clock)
    return build_request(event, case["source_text"], model)


def response_text(body: bytes) -> dict:
    """Text a reply gave instead of a draft, shown to the reviewer. The adapter accepted this envelope
    before its stop-reason check; the text is untrusted and is never read as a draft."""
    content = envelope(strict_json(body))["content"]
    return {"note": "Verbatim and untrusted. It is never read as a draft and does not change the structural outcome.",
            "blocks": [block["text"] for block in content if isinstance(block, dict)
                       and block.get("type") == "text" and isinstance(block.get("text"), str)]}


def review(case: dict, path: Path, provenance: str, model: str | None = None,
           clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    """Validate one response file with the adapter and lay the case's rubric beside the outcome."""
    body = path.read_bytes()
    request = case_request(case, model, clock)
    draft, said, message = None, None, None
    try:
        draft = draft_from_saved_response(body, case["operator"], case["source_text"], model, clock)
        outcome = "draft"
    except DraftRefused as exc:
        message = str(exc)
        outcome = "no draft" if message.startswith(NO_DRAFT) else "refused"
        if outcome == "no draft":
            said = response_text(body)
    rubric = case["rubric"]
    # Values side by side for the reviewer; nothing here is compared or scored.
    beside = [{"leg_id": leg["leg_id"], "primary": leg["primary"], "observable_id": leg["observable_id"],
               "draft_link": leg["link"], "draft_horizon": leg["horizon"], "draft_expected": leg["expected"],
               "rubric_defensible_directions": rubric["defensible_directions"][leg["observable_id"]],
               "draft_headline_reports_move": leg["headline_reports_move"],
               "rubric_headline_reports_move": rubric["leakage_flags"][leg["observable_id"]]["headline_reports_move"]}
              for leg in (draft["review"]["measured_implications"] if draft else [])]
    return {
        "case": {"id": case["id"], "title": case["title"], "probes": case["probes"], "synthetic": True,
                 "case_sha256": digest(case), "prompt_hash": digest(request)},
        "response": {"file": str(path), "sha256": hashlib.sha256(body).hexdigest(), "provenance": provenance,
                     "label": PROVENANCE[provenance]},
        "structural_validation": {"checked_by": "second_order.model_draft.draft_from_saved_response",
                                  "outcome": outcome, "meaning": OUTCOMES[outcome], "adapter_message": message},
        "draft": draft,
        "response_text": said,
        "reasoning_review": {"status": REVIEW_STATUS[outcome], "legs_beside_rubric": beside, "rubric": rubric,
                             "common_criteria": list(COMMON_CRITERIA)},
    }


def run_review(cases: dict[str, dict], supplied: list[tuple[str, str, Path]], model: str | None = None,
               clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    """Review (provenance, case ID, response file) triples in the order given."""
    reviews = [review(pick(cases, case_id), path, provenance, model, clock) for provenance, case_id, path in supplied]
    return {"kit": KIT_VERSION, "prompt_version": PROMPT_VERSION, "requested_model": model or DEFAULT_MODEL,
            "notice": list(NOTICE),
            "responses": {kind: sum(item["response"]["provenance"] == kind for item in reviews) for kind in PROVENANCE},
            "reviews": reviews}


def supplied_as(provenance: str) -> Callable[[str], tuple[str, str, Path]]:
    def parse(value: str) -> tuple[str, str, Path]:
        case_id, separator, file = value.partition("=")
        if not separator or not case_id or not file:
            raise argparse.ArgumentTypeError("expected CASE=FILE")
        return provenance, case_id, Path(file)
    return parse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m second_order.draft_review",
        description="Offline drafting review kit: validate supplied response files with the adapter and show each "
                    "case's rubric beside the result. It never calls a model.")
    parser.add_argument("--list", action="store_true", help="List the synthetic cases")
    parser.add_argument("--print-request", metavar="CASE",
                        help="Print a case's exact request and hash; nothing is sent")
    parser.add_argument("--response", dest="supplied", action="append", type=supplied_as("saved"), metavar="CASE=FILE",
                        help="Saved Messages API response, labelled unverified (repeatable)")
    parser.add_argument("--synthetic", dest="supplied", action="append", type=supplied_as("synthetic"),
                        metavar="CASE=FILE", help="Synthetic response written for testing, labelled not model output "
                                                  "(repeatable)")
    parser.add_argument("--model", help="Model ID the request names and responses must match (default: the adapter's)")
    args = parser.parse_args(argv)
    supplied = args.supplied or []
    if args.list + (args.print_request is not None) + bool(supplied) != 1:
        parser.error("choose one: --list, --print-request CASE, or --response/--synthetic CASE=FILE")
    now = datetime.now(timezone.utc)
    try:
        cases = load_cases(clock=lambda: now)
        if args.list:
            result = [{"id": case["id"], "title": case["title"], "probes": case["probes"],
                       "declining_to_draft": case["rubric"]["declining_to_draft"]["stance"]} for case in cases.values()]
        elif args.print_request is not None:
            request = case_request(pick(cases, args.print_request), args.model, lambda: now)
            result = {"case": args.print_request, "prompt_version": PROMPT_VERSION, "prompt_hash": digest(request),
                      "request": request, "note": "Preview only; nothing was sent."}
        else:
            result = run_review(cases, supplied, args.model, lambda: now)
    except (ValueError, OSError) as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    # As in the main CLI: Unicode on a console, ASCII JSON when piped, which no Windows code page can corrupt.
    print(json.dumps(result, indent=2, ensure_ascii=not sys.stdout.isatty()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
