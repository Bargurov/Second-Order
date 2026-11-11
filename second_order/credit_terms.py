"""The public credit terms (docs/onboarding-contract.md, sections 2 and 3) and the administrator's policy preview.

The examples are three fixed SYNTHETIC plain-text sources, quoted at every offered Effort by the code a real quote
uses: the form becomes an event as a captured source does (model_draft.operator_event), the request is the research
request for that event and text (research_analysis.build_request), its exact bytes give the planning estimate's
assumed input tokens (research_analysis.research_cost), and the active policy's formula gives the credits
(entitlements.credits_for). An example is therefore the quote this server would issue now for that source; there is no
static price to fall out of step. Reading the terms writes, sends and fetches nothing.

The public terms carry points, Effort and source size only: no money, currency, model or provider name, token count or
planning estimate. The preview, for administrators, adds the planning estimate and whether the policy's per-request
limit would refuse each example.

The operator's selected pilot terms are presets here, shown only to administrators. A preset fills a draft or a form and
nothing more: startup, a page load, registration and approval never apply one, and nothing refills credits.
"""
from functools import lru_cache

from . import entitlements, research_analysis as ra
from .accounts import Accounts
from .analysis_flow import story_id
from .model_draft import operator_event
from .schema import utc
from .store import canonical
from .user_research import EFFORT_LABEL, EFFORT_NOTE

CONTRACT = "onboarding-api-0.1"
EXAMPLES = (("short", "Short synthetic source", 2_000), ("medium", "Medium synthetic source", 12_000),
            ("long", "Long synthetic source", 48_000))
PUBLISHED = "2026-01-05T09:00:00+00:00"  # A fixed past time: the examples never depend on the clock.
SENTENCE = "SYNTHETIC EXAMPLE TEXT, written only to show how a quote grows with the amount of text. "
# The planning estimate counts the saved request's UTF-8 bytes, 2 per token, so 1,000 tokens are 2,000 bytes: 2,000
# characters of plain English text, about 1,000 of Hebrew (2 bytes each) and about 500 emoji (4 bytes each).
CHARACTERS_PER_1K = 2_000
RULES = [
    "A credit is one point of application usage on this server. It has no fixed money value and cannot be bought, "
    "sold or exchanged here.",
    "Before an analysis runs you get a quote: the exact number of points for that prepared analysis, its Effort and "
    "its source, under one credit-policy version, valid until the time it states. Nothing runs until you approve it.",
    "Approving reserves the quoted points and one run of today's daily allowance. When a result is recorded the quoted "
    "points are charged; if nothing was sent they are returned. If the server cannot tell whether a run was sent, the "
    "points stay held until an administrator settles them. You are never charged more than the quote you approved.",
    "The daily allowance counts new analysis runs per calendar day and is separate from points: a run uses one slot "
    "whatever its points, and a run that is returned gives its slot back.",
    "Points do not buy a running time or a better result. Higher Effort lets the analysis spend more of its output "
    "allowance on reasoning and can need more points.",
    "Reading, reviewing and exporting saved results, adding a source, preparing an analysis and asking for a quote use "
    "no points and no allowance.",
]
# The operator's selected pilot terms (14 October 2026), mapped onto the existing formula: flat points by Effort for any
# accepted source. The preset is rates and Effort extras only; the model, which Efforts are offered, the quote validity
# and the per-request planning limit stay the administrator's choices in the version they publish (no limit was chosen).
PILOT_POLICY_PRESET = {
    "preset": "pilot-flat-1", "label": "Selected pilot terms: flat points by Effort",
    "note": ("Low 10, Medium 15, High 20, Extra High 25 and Maximum 30 points per accepted analysis, whatever the "
             "source's length or language; the source limits still apply. Choosing it fills this draft only: "
             "publishing a version is a separate action, and the per-request planning limit stays your decision."),
    "credits": {"base": 10, "per_1k_input_tokens": 0, "per_1k_output_tokens": 0},
    "efforts": {"low": {"extra_credits": 0}, "medium": {"extra_credits": 5}, "high": {"extra_credits": 10},
                "xhigh": {"extra_credits": 15}, "max": {"extra_credits": 20}},
}
INITIAL_ALLOCATION_PRESET = {
    "preset": "pilot-initial-1", "label": "Selected initial allocation: 100 credits once, 3 analyses a day",
    "note": ("For an approved account with nothing allocated yet. It fills the credit and daily-limit forms; each is "
             "still its own action with its own reason, and either value can be changed first. Nothing is refilled."),
    "credits": 100, "daily_limit": 3,
}
NOT_CONFIGURED = {
    "no_credit_policy": "No credit terms are set on this server yet, so no analysis can be quoted.",
    "no_effort_enabled": "No Effort is offered on this server yet, so no analysis can be quoted.",
}


def synthetic_text(characters: int) -> str:
    paragraph = (SENTENCE * 6).strip() + "\n\n"
    return (paragraph * (characters // len(paragraph) + 1))[:characters]


def example_form(slug: str, characters: int) -> dict:
    """The source form of one example, as a user would type it."""
    return {"headline": f"Synthetic example source ({characters:,} characters)",
            "source_url": f"https://example.invalid/synthetic/{slug}", "published_at": PUBLISHED,
            "source_text": synthetic_text(characters)}


@lru_cache(maxsize=None)
def _estimate(slug: str, characters: int, effort: str) -> dict:
    """The planning estimate of an example's exact request at one Effort (it depends only on the bytes)."""
    form = example_form(slug, characters)
    event, _ = operator_event({"headline": form["headline"], "source_url": form["source_url"],
                               "published_at": form["published_at"], "story_id": story_id(form)},
                              lambda: utc(ra.now()))
    request = ra.build_request(event, form["source_text"], effort)
    return ra.research_cost(canonical(request).encode("utf-8"))


def _examples(policy: dict, efforts: list[str], admin: bool) -> list[dict]:
    rows = []
    for slug, label, characters in EXAMPLES:
        quotes = []
        for effort in efforts:
            estimate = _estimate(slug, characters, effort)
            quote = {"effort": effort, "credits": entitlements.credits_for(
                policy, effort, estimate["input_tokens_assumed"], ra.MAX_TOKENS)}
            if admin:
                planning = estimate["estimated_real_run_if_output_reaches_max_usd"]
                quote |= {"input_tokens_assumed": estimate["input_tokens_assumed"], "planning_estimate_usd": planning,
                          "refused_over_budget": planning > policy["max_request_usd"]}
            quotes.append(quote)
        rows.append({"example": slug, "label": label, "characters": characters, "quotes": quotes})
    return rows


def size_note(policy: dict) -> str:
    rate = policy["credits"]["per_1k_input_tokens"]
    if rate == 0:
        return "Under the current terms the amount of source text does not change the quote."
    points = "one more point" if rate == 1 else f"{rate} more points"
    return (f"Longer sources need more points: about {points} for each {CHARACTERS_PER_1K:,} characters of plain "
            "English text. Characters of other scripts count more (Hebrew letters about twice as much, emoji about "
            "four times), and your own quote gives the exact number.")


def public_terms(accounts: Accounts) -> dict:
    """GET /api/public/credit-terms: the active policy's terms in points, or why there are none."""
    policy = entitlements.current_policy(accounts)
    efforts = entitlements.offered_efforts(policy, ra.MODEL)
    state = "no_credit_policy" if policy is None else "no_effort_enabled" if not efforts else "configured"
    shown = {"contract": CONTRACT, "state": state, "detail": NOT_CONFIGURED.get(state),
             "policy_version": None, "efforts": [], "effort_note": EFFORT_NOTE, "size_note": None,
             "quote_valid_seconds": None, "examples": [], "rules": RULES}
    if state == "configured":
        shown |= {"policy_version": policy["policy_version"], "quote_valid_seconds": policy["quote_valid_seconds"],
                  "efforts": [{"effort": effort, "label": EFFORT_LABEL[effort]} for effort in efforts],
                  "size_note": size_note(policy), "examples": _examples(policy, efforts, admin=False)}
    return shown


def preview(body: object) -> dict:
    """An administrator's draft policy checked exactly as a new version would be, with the examples it would quote.
    Nothing is recorded: activating it is the separate, explicit new-version action."""
    policy = entitlements.checked_policy(body)
    efforts = [effort for effort in entitlements.EFFORT_ORDER if effort in policy["efforts"]]
    return {"policy": policy, "size_note": size_note(policy), "examples": _examples(policy, efforts, admin=True),
            "recorded": False}
