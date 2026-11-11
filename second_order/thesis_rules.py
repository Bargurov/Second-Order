"""Text rules for the committed thesis (thesis-0.1): what author text may say, and where its figures must come from.

Author text is refused when it uses a claim word (policy_research.BANNED) or states a view on a price's direction
(PRICE_DIRECTION): this project describes balances, sources and exposure, never where a price goes. Neutral wording
such as "a change in the price" is allowed. Figures in author text must appear in the sources the text cites (the
digit-run rule of policy_research); plain notes carry none. Quotes, source titles and company names are not scanned.
"""
import re

from . import policy_research

BANNED = policy_research.BANNED
DIGITS = policy_research.DIGITS
MAX_TEXT = 900

_PRICE = r"(?:prices?|pricing)"
_AFTER = (r"ris(?:e|es|ing|en)|rose|fall(?:s|ing|en)?|fell|increas\w*|decreas\w*|declin\w*|climb\w*|drop\w*|jump\w*|"
          r"surg\w*|soar\w*|spik\w*|slump\w*|plung\w*|higher|lower|up|down|pressure|tight\w*|support\w*|gains?")
_BEFORE = r"higher|lower|rising|falling|upward|downward|pressure on|support for|tighter|firmer|weaker|stronger"
PRICE_DIRECTION = re.compile(
    rf"\b(?:up-?side|down-?side|bullish|bearish|rall(?:y|ies)|over-?valued|under-?valued|over-?priced|under-?priced|"
    rf"price target|target price|fair value)\b"
    rf"|\b{_PRICE}\b\W+(?:\w+\W+){{0,4}}?(?:{_AFTER})\b"
    rf"|\b(?:{_BEFORE})\b\W+(?:\w+\W+){{0,4}}?{_PRICE}\b", re.I)

CONFIDENCE = ("low", "medium", "high")
STATEMENT_STATUSES = {"stated": "Source statement", "interpretation": "Author's reading",
                      "not_stated": "Not stated in the sources"}
REASON_STATES = ("strengthening", "weakening", "unchanged")
RISK_STATES = ("materialising", "receding", "unchanged", "not_tracked")
CONDITION_STATES = ("happened", "not_happened")
SOURCE_STATES = policy_research.PUBLICATION_STATES
ELEMENT_STATES = policy_research.COMPARISON_STATES


class ThesisRefused(ValueError):
    """The thesis cannot be served; ``status`` is the HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def invalid(where: str, problem: str) -> ThesisRefused:
    return ThesisRefused(500, f"The thesis file is invalid ({where}: {problem}); nothing is served")


def check(condition: bool, where: str, problem: str) -> None:
    if not condition:
        raise invalid(where, problem)


def free_text(value: object, where: str, limit: int) -> str:
    """One line of text (non-empty, stripped, no control characters, at most ``limit`` characters); no scans."""
    check(isinstance(value, str) and bool(value) and value == value.strip() and len(value) <= limit and
          not any(ord(char) < 32 for char in value), where, f"expected one line of text of at most {limit} characters")
    return value


def author_text(value: object, where: str, limit: int = MAX_TEXT) -> str:
    """Author text: free_text, with no claim word and no statement about a price's direction."""
    text = free_text(value, where, limit)
    found = BANNED.search(text)
    check(found is None, where, f"uses {found.group(0)!r}, which belongs only to the list of claims not made"
          if found else "")
    found = PRICE_DIRECTION.search(text)
    check(found is None, where, f"uses {found.group(0)!r}, which states a view on a price's direction"
          if found else "")
    return text


def no_figures(value: str, where: str) -> str:
    check(not DIGITS.search(value), where, "plain notes state no figures")
    return value


def held_to(text: str, allowed: str, where: str) -> None:
    extra = policy_research._figures(text) - policy_research._figures(allowed)
    check(not extra, where, f"states figures its cited sources do not: {sorted(extra)}")
