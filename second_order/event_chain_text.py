"""Text checks for event chains: claim words and price direction (English and Hebrew) for the assistant's text, the
six-word overlap with source quotes, step references, figure masking, and the owner's line and notes.

The owner's own words (a reading line, review notes, research notes) are held to no word list: by the owner's decision
of 2026-11-10 they may state a view, a price's direction included. The rules that stay on them protect sources, not
opinions: no six consecutive words of a source, numbers in the digits 0 to 9, a line's figures from its sources, and
figures masked while a document they rest on does not verify."""
import re
import unicodedata
from typing import Iterable

from . import thesis_rules, thesis_rules_he
from .policy_research import DIGITS

OVERLAP_WORDS = 6
MASK = "[figure withheld]"
# Only the digits 0 to 9 make a figure or a step number, here and in the page's reader (frontend/src/eventChains.ts,
# FIGURE and STEP), which refuses a reply that still shows a figure it expects masked. Python's \d also takes the
# digits of other scripts and a browser's does not, so neither pattern uses it; the two sides share one table of
# texts, frontend/tests/fixtures/event-chain-masking.json.
FIGURE = re.compile(r"[0-9]+(?:[.,][0-9]+)*%?")
# "step", "steps", or "שלב"/"שלבים" with up to three of the Hebrew prefix letters (as in "בשלב 2", "ובשלב 3").
STEP = re.compile(rf"(?<!\w)(?:steps?|[{thesis_rules_he.PREFIXES}]{{0,3}}(?:שלבים|שלב))\s+([0-9]+)", re.I)
# A decimal digit of another script (as in "٠3" or "３"). Neither rule reads it, so the owner's text may not hold one.
OTHER_DIGIT = re.compile(r"[^\D0-9]")
# A line break of any kind: control characters (Cc) and the line and paragraph separators U+2028 and U+2029.
BREAKS = ("Cc", "Zl", "Zp")
MAX_LINE, MAX_NOTES = 280, 1000


class TextRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def rule_problem(text: str) -> str | None:
    found = thesis_rules.BANNED.search(text)
    if found:
        return f"uses {found.group(0)!r}, a claim word"
    found = thesis_rules.PRICE_DIRECTION.search(text)
    if found:
        return f"uses {found.group(0)!r}, a view on a price's direction"
    word = thesis_rules_he.claim_word(text)
    if word:
        return f"uses {word!r}, a claim word"
    word = thesis_rules_he.price_direction(text)
    if word:
        return f"uses {word!r}, a view on a price's direction"
    return None


def one_line(text: str) -> bool:
    """Whether text holds no control character and no line or paragraph separator."""
    return not any(unicodedata.category(char) in BREAKS for char in text)


def _plain(text: str) -> str:
    """Text as the overlap rule compares it, before any word is split: NFKC (which also takes a pointed presentation
    form apart), niqqud and cantillation removed and the maqaf turned into a space (thesis_rules_he.normalise, as the
    Hebrew rules read text), casefolded, with plain quotation marks and dashes."""
    text = thesis_rules_he.normalise(unicodedata.normalize("NFKC", text)).casefold()
    text = re.sub("[‘’‚‛]", "'", text)
    text = re.sub("[“”„‟]", '"', text)
    return re.sub("[‐-―−]", "-", text)


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", _plain(text))


def overlap(text: str, quotes: Iterable[str], n: int = OVERLAP_WORDS) -> str | None:
    """The first run of n words of text that also appears in one of the quotes, or None."""
    words = _words(text)
    runs = set()
    for quote in quotes:
        quoted = _words(quote)
        runs.update(" ".join(quoted[i:i + n]) for i in range(len(quoted) - n + 1))
    for i in range(len(words) - n + 1):
        run = " ".join(words[i:i + n])
        if run in runs:
            return run
    return None


def step_spans(text: str, steps: int) -> list[tuple[int, int]]:
    """Spans of the step numbers in text that name a step from 1 to steps."""
    return [m.span(1) for m in STEP.finditer(text) if 1 <= int(m.group(1)) <= steps]


def _outside_steps(text: str, steps: int):
    spans = step_spans(text, steps)
    return [m for m in FIGURE.finditer(text) if not any(s <= m.start() and m.end() <= e for s, e in spans)]


def figure_runs(text: str, steps: int) -> set[str]:
    return {run for m in _outside_steps(text, steps) for run in DIGITS.findall(m.group(0))}


def masked(text: str, steps: int) -> str:
    out, last = [], 0
    for m in _outside_steps(text, steps):
        out += [text[last:m.start()], MASK]
        last = m.end()
    return "".join(out) + text[last:]


def _refuse(message: str) -> TextRefused:
    return TextRefused(422, message)


def _other_digit(text: str, hold: str) -> None:
    found = OTHER_DIGIT.search(text)
    if found:
        raise _refuse(f"{hold} the digit {found.group(0)!r}; write numbers with the digits 0 to 9")


# Characters that Python's strip() removes at an end and a browser's trim() keeps (the saved text would then differ
# from the text the page sent), and a lone surrogate, which cannot be written as UTF-8.
STRIPPED_HERE_ONLY = frozenset(map(chr, (0x1C, 0x1D, 0x1E, 0x1F, 0x85)))


def _unstorable(value: str) -> bool:
    """Whether the owner's text, as sent, could not be stored as it is: it is then refused, never changed silently."""
    return any(char in STRIPPED_HERE_ONLY or unicodedata.category(char) == "Cs" for char in value)


def owner_line(value: object, *, quotes: list[str], allowed: str, steps: int) -> str:
    if not isinstance(value, str):
        raise _refuse("the line must be text")
    text = value.strip()
    if not 1 <= len(text) <= MAX_LINE or not one_line(text) or _unstorable(value):
        raise _refuse(f"the line must be one line of 1 to {MAX_LINE} characters")
    _other_digit(text, "the line holds")
    shared = overlap(text, quotes)
    if shared:
        raise _refuse(f"the line repeats {OVERLAP_WORDS} words of a source: {shared!r}")
    extra = figure_runs(text, steps) - set(DIGITS.findall(allowed))
    if extra:
        raise _refuse(f"the line states figures its sources do not: {sorted(extra)}")
    return text


def owner_notes(value: object, *, quotes: list[str], steps: int) -> str:
    if not isinstance(value, str):
        raise _refuse("the notes must be text")
    text = value.strip()
    if not 1 <= len(text) <= MAX_NOTES or any(c != "\n" and unicodedata.category(c) == "Cc" for c in text) \
            or _unstorable(value):
        raise _refuse(f"the notes must be 1 to {MAX_NOTES} characters, with no control characters")
    _other_digit(text, "the notes hold")
    shared = overlap(text, quotes)
    if shared:
        raise _refuse(f"the notes repeat {OVERLAP_WORDS} words of a source: {shared!r}")
    return text


def owner_text(value: object, *, quotes: list[str], limit: int, name: str) -> str:
    """Free text of the owner's in a research note (``name``: "the note", "the expectation", "the question"), held to
    what review notes are: its length, no control character but a line break, the digits 0 to 9 and no six
    consecutive words of a source. No word list applies."""
    if not isinstance(value, str):
        raise _refuse(f"{name} must be text")
    text = value.strip()
    if not 1 <= len(text) <= limit or any(c != "\n" and unicodedata.category(c) == "Cc" for c in text) \
            or _unstorable(value):
        raise _refuse(f"{name} must be 1 to {limit} characters, with no control characters")
    _other_digit(text, f"{name} holds")
    shared = overlap(text, quotes)
    if shared:
        raise _refuse(f"{name} repeats {OVERLAP_WORDS} words of a source: {shared!r}")
    return text
