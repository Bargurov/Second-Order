"""Research-quality rubric (research-quality-0.3): deterministic checks of a structurally accepted analysis against its
source, for a reader and for regression tests. It is separate from the result: it reads a source text and an analysis
as the research reader resolved them, writes nothing, changes no outcome, result, fingerprint or review, and has
nothing to do with forecasting evaluation, frozen hypotheses or evidence pools. It is computed on read, so a new
version changes what is shown for every analysis and nothing that is stored.

0.2 against 0.1, each change measured on QA's independent synthetic corpus and pinned in tests/quality_cases.py:
words of the source sentence a quote comes from count as held (a faithful paraphrase of a short quote was flagged); a
missing-information item asking why, how, who or when something happened is not compared (only its terms were, so a
present fact made the unknown look contradicted); size, change, extent, magnitude and scale are not key terms of a
missing item; and two checks are new: a direction (rose, fell, unchanged; or negated) that the quotes do not state, and
a named speaker the source does not contain.

0.3 against 0.2, measured on QA's fresh synthetic cases (now development cases) and pinned on this branch's own port
source: a date's day and year are periods, not figures; a period counts as held when the sentence of a quote gives it
to a figure inside that quote (a correct date just outside a short quote was flagged), never one the sentence gives
another figure; words shorter than five letters match their inflections ("ease", "eased"), as PREFIX always intended;
and three checks are new: a figure given as a change where its quote's sentence gives it as a level (or the reverse),
a negation added to or dropped from a word of the quotes, and a speaker other than the one the quote's sentence names.
Numbers stay tied to the quotes themselves. The interpretation is still checked only for figures: whether it follows
from its statements is left to a person.

Three levels, kept apart:

- rejected: only what the existing research contract already refuses (strict schema, a quote not found in the source).
  This rubric adds no rejection: a matched quote shows that the words are in the source, not that a statement follows
  from them, so everything below is a flag.
- flagged: a deterministic, reproducible finding that needs a person to look: a number, unit, period or date in a
  statement that its own quotes do not contain (or the source does not contain), a figure's change or level role
  reversed, a forecast or assessment not attributed to its publisher, a forecast labelled as data or action, content
  words of a statement that its quotes and their sentences do not hold, a direction its quotes do not state, a
  negation added or dropped, a speaker the source does not name (or that the quote's own sentence does not, when it
  names its speaker), a "missing" item whose terms the source does contain, an analysis with no unknowns or tests, and
  a source that looks like a headline, an excerpt or a cut-off text.
- human review: what no check here establishes: whether the statements are accurate paraphrases, whether the
  interpretation follows, whether the competing explanations and tests are apt, and whether anything important was
  left out. Always listed.

The checks are lexical. A flag is not a verdict and its absence is not a confirmation; no confidence percentage is
computed. Which checks fire on which planted mistakes is pinned by the regression cases in tests/quality_cases.py.
"""
import re
import unicodedata

from .research_reading import paragraphs

RUBRIC_VERSION = "research-quality-0.3"
MIN_SOURCE_WORDS = 30
MIN_UNSUPPORTED = 3  # A statement is flagged when at least this many of its content words are not in its quotes ...
UNSUPPORTED_SHARE = 0.4  # ... and they are at least this share of its content words.
PREFIX = 5  # Words match on their first five letters, so "raised" meets "raise" and "rates" meets "rate".

NUMBER = re.compile(r"(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?(?:-\d+/\d+)?)(?![\w])")
# "statement 2", "statements 1 and 3": the analysis's own references to its statements are not figures.
REFERENCE = re.compile(r"\bstatements?\s+\d+(?:\s*(?:,|and|or|to)\s*\d+)*", re.IGNORECASE)
UNIT = re.compile(r"\s*(%|percentage points?|percent|basis points?|bps|billion|million|thousand|trillion)\b",
                  re.IGNORECASE)
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
          "december")
# A month (with its day, as in "October 2"), a quarter or a year. The day and year of a date are periods, not figures.
PERIOD = re.compile(r"\b(?:((?:" + "|".join(MONTHS) + r")(?:\s+\d{1,2}(?!\d|[.,]\d))?)|(first|second|third|fourth) "
                    r"quarter|(q[1-4])|((?:19|20)\d{2}))\b", re.IGNORECASE)
PRECEDING = re.compile(r"([^\W\d_]+)\s*$")
# The word just before a figure says whether it is the size of a change or a level reached: "rose by 2.3", "fell 2.3"
# and "down 1.1" against "to 412.6". Any other word ("at", "was", "averaged") says neither, and is not compared.
CHANGE_WORDS = {"by", "up", "down"}  # The rise and fall words of DIRECTIONS are added below.
LEVEL_WORDS = {"to"}
WORD = re.compile(r"[^\W\d_]+")
ATTRIBUTING = {"expects", "expected", "expect", "projects", "projected", "project", "projection", "projections",
               "anticipates", "anticipated", "forecasts", "forecast", "intends", "intend", "plans", "plan", "sees",
               "says", "said", "states", "stated", "according", "judges", "judged", "assesses", "assessed",
               "describes", "described", "characterizes", "characterized", "characterises", "characterised", "views",
               "considers", "considered", "notes", "noted", "indicates", "indicated", "reports", "reported", "estimates",
               "estimated", "believes", "believed", "outlook", "anticipate", "aims", "seeks", "commits", "committed"}
FUTURE = {"will", "would", "expects", "expected", "projected", "projects", "forecast", "forecasts", "anticipates",
          "anticipated", "intends", "plans", "outlook"}
ABSENCE = re.compile(r"\b(does not|doesn't|did not|do not|is not|are not|no|not|without|lacks?|omits?|missing|absent|"
                     r"unstated|unspecified|silent)\b", re.IGNORECASE)
STOP = {"the", "and", "that", "this", "with", "from", "were", "was", "for", "are", "has", "have", "had", "its", "their",
        "they", "them", "than", "then", "into", "onto", "also", "which", "while", "been", "being", "about", "over",
        "under", "after", "before", "more", "less", "most", "such", "some", "other", "what", "when", "where", "whether",
        "would", "could", "should", "will", "does", "did", "not", "nor", "but", "any", "all", "each", "both", "only",
        "very", "much", "many", "same", "these", "those", "there", "here", "publisher", "source", "release",
        "publication", "statement", "states", "stated", "says", "said", "reports", "reported", "text", "information",
        "data", "figure", "figures", "detail", "details", "give", "gives", "given", "provide", "provides", "provided",
        "include", "includes", "included", "specify", "specifies", "mention", "mentions", "state", "report",
        "level", "levels", "amount", "number", "missing", "absent", "lacks", "omits", "without", "unstated",
        "unspecified", "silent", "how", "why", "who", "whom"}
# A missing item that asks about an aspect (why something rose, who decided it) is not contradicted by its terms being
# present, and words naming a size or a change are not key terms of what it says is missing.
QUESTION = {"why", "how", "who", "whom", "whose", "when", "where", "which", "what", "whether", "reason", "reasons",
            "cause", "causes", "caused", "explanation", "drove", "driver", "drivers"}
ASPECT = {"size", "sizes", "change", "changes", "extent", "magnitude", "scale"}
DIRECTIONS = {
    "up": {"rose", "rise", "rises", "rising", "risen", "increase", "increased", "increases", "increasing", "grew",
           "grow", "grows", "growing", "gain", "gained", "gains", "higher", "raise", "raised", "raises", "climbed"},
    "down": {"fell", "falls", "falling", "fallen", "decline", "declined", "declines", "declining", "decrease",
             "decreased", "decreases", "decreasing", "dropped", "drop", "drops", "lower", "lowered", "lowers", "cut",
             "cuts", "reduced", "reduce", "contracted", "shrank"},
    "flat": {"unchanged", "steady", "flat", "stable"},
}
CHANGE_WORDS |= DIRECTIONS["up"] | DIRECTIONS["down"]
TOKEN = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
NEGATION = {"not", "no", "never", "neither", "nor", "without"}
NEGATION_REACH = 3  # A direction word is negated by a negation among the three words before it.
# Any other word is negated when it is the first word after a negation that is not one of these.
AUXILIARY = {"a", "an", "the", "any", "be", "been", "being", "is", "are", "was", "were", "am", "do", "does", "did",
             "have", "has", "had", "will", "would", "shall", "should", "can", "could", "may", "might", "must", "yet",
             "also", "even", "ever"}
# A speaker named before one of these verbs (or after "according to") must be in the source or its headline.
SPEAKING = re.compile(r"\b(said|says|stated|reported|announced|announces|noted|indicated|expects|judged|judges|"
                      r"believes|sees)\b|\baccording to\b")
SPEAKER_WORDS = 6
SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*(?=\s|$)")
SOURCE_CUT =re.compile(r"(…|\.\.\.|\[…\]|\[\.\.\.\])\s*$|\b(read more|continue reading|click here)\b", re.IGNORECASE)
CHECKS = {
    "source_too_short": ("The source has fewer than 30 words or no words beyond its headline, so it may be a headline "
                         "or a feed excerpt rather than a publication."),
    "source_may_be_cut": ("The source ends with an ellipsis or a 'read more' marker, or without closing punctuation, "
                          "so it may be cut off."),
    "number_not_in_source": "A number in a statement does not appear anywhere in the source text.",
    "number_not_in_quotes": "A number in a statement appears in the source, but not in that statement's own quotes.",
    "unit_differs": ("A number in a statement carries another unit than the same number in its quotes (percent "
                     "against percentage points, millions against billions)."),
    "level_change_differs": ("A figure a statement gives as the size of a change ('by', or after a rise or fall word) "
                             "is a level reached ('to') where its quote's sentence states it, or the reverse."),
    "period_not_in_source": "A month, quarter, year or date in a statement does not appear in the source text.",
    "period_not_in_quotes": ("A month, quarter, year or date in a statement is neither in that statement's own quotes "
                             "nor the one their sentence gives a figure they quote."),
    "forecast_unattributed": "A statement with basis forecast names no expectation or attribution word.",
    "assessment_unattributed": "A statement with basis assessment names no attribution word.",
    "basis_mismatch": "A statement with basis data or action uses future or expectation wording.",
    "beyond_quotes": ("Several content words of a statement are not in its quotes or the source sentences they come "
                      "from, so it may say more than they do."),
    "direction_differs": ("A statement says something rose, fell or was unchanged (or did not) where its quotes state "
                          "another direction."),
    "negation_differs": ("A statement negates a word that its quotes and their sentences state with no negation, or "
                         "states without a negation a word that they negate."),
    "speaker_not_in_source": "A statement attributes its content to a speaker the source and headline do not name.",
    "speaker_differs": ("A statement attributes its content to a speaker that the sentence its quotes come from does "
                        "not name, although that sentence names its own speaker (the headline counts for the "
                        "publisher)."),
    "interpretation_number_not_in_source": "A number in the interpretation does not appear in the source text.",
    "absence_contradicted": ("A missing-information item says something is absent, but every key term of it appears "
                             "together in one paragraph of the source."),
    "no_unknowns": "The analysis lists no missing information and no tests.",
}
HUMAN_REVIEW = (
    "Whether each statement is an accurate paraphrase of its quotes, beyond the words and figures checked here.",
    "Whether the interpretation follows from the statements it names.",
    "Whether the assumptions, competing explanations and tests are apt and complete.",
    "Whether the analysis left out something the source establishes that matters.",
)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").casefold()


def _numbers(text: str) -> list[tuple[str, str | None]]:
    """(number without thousands separators, its unit or None) for every number in the text, apart from references to
    the analysis's own statements by number."""
    found = []
    folded = REFERENCE.sub(" ", _fold(text))
    for match in NUMBER.finditer(folded):
        unit = UNIT.match(folded, match.end())
        name = None
        if unit:
            name = unit.group(1).lower()
            name = {"%": "percent", "percentage points": "percentage point", "basis points": "basis point",
                    "bps": "basis point"}.get(name, name)
        found.append((match.group(1).replace(",", ""), name))
    return found


def _period(match: re.Match) -> str:
    return " ".join(match.group(0).casefold().split())


def _periods(text: str) -> list[str]:
    return sorted({_period(match) for match in PERIOD.finditer(text)})


def _implied(periods: set[str]) -> set[str]:
    """The periods with the month of each dated day added: a text that says "October 2" also says "October"."""
    return periods | {period.split()[0] for period in periods if period.split()[0] in MONTHS}


def _undated(text: str) -> str:
    """The text with each period blanked out, keeping every other character's position."""
    return PERIOD.sub(lambda match: " " * len(match.group(0)), text)


def _figures(text: str) -> list[tuple[int, str, str | None]]:
    """(position, number without thousands separators, "change" | "level" | None) for every figure in the text: a
    number that is not part of a period (a date's day, a year) or a reference to the analysis's own statements. The
    role comes from the word just before it (CHANGE_WORDS, LEVEL_WORDS)."""
    blank = _undated(REFERENCE.sub(lambda match: " " * len(match.group(0)), text))
    found = []
    for match in NUMBER.finditer(blank):
        before = PRECEDING.search(blank, 0, match.start())
        word = before.group(1).casefold() if before else ""
        role = "change" if word in CHANGE_WORDS else "level" if word in LEVEL_WORDS else None
        found.append((match.start(), match.group(1).replace(",", ""), role))
    return found


def _content(text: str) -> list[str]:
    return [word for word in WORD.findall(_fold(text)) if len(word) >= 4 and word not in STOP]


def _meets(word: str, held: set[str]) -> bool:
    """Whether the word matches a held word on their first five letters, or on all of the shorter one's letters when
    either has four; a word of three letters or fewer matches only itself."""
    for other in held:
        size = min(PREFIX, len(word), len(other))
        if word[:size] == other[:size] and (size >= 4 or word == other):
            return True
    return False


def _sentences(source: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence: a paragraph split after a full stop, question or exclamation mark followed by
    a space, so a decimal point does not end one."""
    spans = []
    for start, end in paragraphs(source):
        for match in SENTENCE_END.finditer(source, start, end):
            spans.append((start, match.end()))
            start = match.end()
        if source[start:end].strip():
            spans.append((start, end))
    return spans


def _directions(text: str) -> set[tuple[str, bool]]:
    """(rose/fell/unchanged family, negated) for every direction word in the text."""
    words = TOKEN.findall(_fold(text))
    found = set()
    for index, word in enumerate(words):
        for family, members in DIRECTIONS.items():
            if word in members:
                before = words[max(0, index - NEGATION_REACH):index]
                found.add((family, any(other in NEGATION or other.endswith(("n't", "n’t")) for other in before)))
    return found


def _negated(text: str) -> list[str]:
    """The word each negation in the text applies to: the first word after it that is not an auxiliary or article."""
    words = TOKEN.findall(_fold(text))
    heads = []
    for index, word in enumerate(words):
        if word in NEGATION or word.endswith(("n't", "n’t")):
            following = [other for other in words[index + 1:] if other not in AUXILIARY]
            if following:
                heads.append(following[0])
    return heads


def _negation_changed(statement: str, evidence: str) -> tuple[str, list[str]]:
    """Words other than rise/fall words (the direction check covers those) whose negation the statement adds or drops:
    the statement negates a word its evidence (its quotes and their sentences) states with no negation anywhere, or
    states with no negation a word its evidence negates. ("", []) when neither."""
    said, held = _negated(statement), _negated(evidence)
    directions = set().union(*DIRECTIONS.values())
    if said and not held:
        words = set(WORD.findall(_fold(evidence)))
        return "added", sorted({word for word in said if word not in directions and _meets(word, words)})
    if held and not said:
        words = set(WORD.findall(_fold(statement)))
        return "dropped", sorted({word for word in held if word not in directions and _meets(word, words)})
    return "", []


def _named(pairs: set[tuple[str, bool]]) -> str:
    return ", ".join(("not " if negated else "") + family for family, negated in sorted(pairs))


def _speaker(statement: str) -> list[str]:
    """Content words of the speaker a statement names: up to six words before its first speaking verb (back to a
    comma, semicolon, colon or "that"), or after "according to" up to the clause's end."""
    folded = _fold(statement)
    match = SPEAKING.search(folded)
    if not match:
        return []
    if match.group(1) is None:
        words = WORD.findall(re.split(r"[,;:.]", folded[match.end():], maxsplit=1)[0])[:SPEAKER_WORDS]
    else:
        words = WORD.findall(re.split(r"[,;:]|\bthat\b", folded[:match.start()])[-1])[-SPEAKER_WORDS:]
    return _content(" ".join(words))


def _given(source: str, spans: list[tuple[int, int]],
           quotes: list[dict]) -> tuple[set[str], list[tuple[str, str | None]]]:
    """What the quotes' own sentences (spans) give the figures inside those quotes: their periods, and each figure's
    role. A period belongs to the nearest figure before it in its sentence ("rose 0.3 percent in September after
    declining 0.2 percent in August"), or to the sentence's first figure when no figure comes before it."""
    periods, roles = set(), []
    for start, end in spans:
        figures = [(start + at, value, role) for at, value, role in _figures(source[start:end])]
        inside = {at for at, _, _ in figures if any(quote["start"] <= at < quote["end"] for quote in quotes)}
        roles += [(value, role) for at, value, role in figures if at in inside]
        for match in PERIOD.finditer(source, start, end):
            before = [at for at, _, _ in figures if at < match.start()]
            owner = before[-1] if before else figures[0][0] if figures else None
            if owner in inside:
                periods.add(_period(match))
    return periods, roles


def _finding(check: str, where: str, detail: str) -> dict:
    return {"check": check, "level": "flagged", "where": where, "detail": detail, "rule": CHECKS[check]}


def source_checks(headline: str, source: str) -> list[dict]:
    """Flags about the source itself: possibly a headline or excerpt, possibly cut off."""
    found = []
    words = WORD.findall(_fold(source))
    if len(words) < MIN_SOURCE_WORDS or set(words) <= set(WORD.findall(_fold(headline))):
        found.append(_finding("source_too_short", "source", f"The source has {len(words)} words."))
    tail = source.rstrip()
    if SOURCE_CUT.search(source) or (tail and tail[-1] not in ".!?:;\"')]”’"):
        found.append(_finding("source_may_be_cut", "source", f"The source ends with: {tail[-60:]!r}."))
    return found


def _statement_checks(number: int, item: dict, source: str, sentences: list[tuple[int, int]], named: set[str],
                      titled: set[str]) -> list[dict]:
    where = f"established[{number}]"
    statement = item["statement"]
    quoted = " ".join(quote["source_passage"] for quote in item["quotes"])
    located = [quote for quote in item["quotes"] if quote.get("start") is not None]
    spans = sorted({(start, end) for quote in located for start, end in sentences
                    if start < quote["end"] and quote["start"] < end})
    around = " ".join(source[start:end] for start, end in spans)
    given_periods, given_roles = _given(source, spans, located)
    found = []
    held = _numbers(quoted)
    in_source = {value for value, _ in _numbers(source)}
    for value, unit in _numbers(_undated(statement)):
        same = [other for number_, other in held if number_ == value]
        if not same:
            check = "number_not_in_quotes" if value in in_source else "number_not_in_source"
            found.append(_finding(check, where, f"{value}{' ' + unit if unit else ''} is in the statement."))
        elif unit and all(other is not None and other != unit for other in same):
            found.append(_finding("unit_differs", where, f"The statement says {value} {unit}; its quotes say "
                                                         f"{value} {same[0]}."))
    for _, value, role in _figures(statement):
        same = [other for number_, other in given_roles if number_ == value]
        if role and same and all(other is not None and other != role for other in same):
            found.append(_finding("level_change_differs", where, f"The statement gives {value} as a {role}; the "
                                                                 f"sentence of its quote gives it as a {same[0]}."))
    quoted_periods, source_periods = _implied(set(_periods(quoted)) | given_periods), _implied(set(_periods(source)))
    for period in _periods(statement):
        if period not in quoted_periods:
            check = "period_not_in_quotes" if period in source_periods else "period_not_in_source"
            found.append(_finding(check, where, f"{period!r} is in the statement."))
    words = set(WORD.findall(_fold(statement)))
    if item["basis"] == "forecast" and not words & ATTRIBUTING:
        found.append(_finding("forecast_unattributed", where, "No expectation or attribution word."))
    if item["basis"] == "assessment" and not words & ATTRIBUTING:
        found.append(_finding("assessment_unattributed", where, "No attribution word."))
    if item["basis"] in ("data", "action") and words & FUTURE:
        found.append(_finding("basis_mismatch", where, f"Basis {item['basis']} with: "
                                                       f"{', '.join(sorted(words & FUTURE))}."))
    said, held_directions = _directions(statement), _directions(quoted)
    if held_directions and said - held_directions:
        found.append(_finding("direction_differs", where, f"The statement says {_named(said - held_directions)}; its "
                                                          f"quotes say {_named(held_directions)}."))
    change, negated = _negation_changed(statement, quoted + " " + around)
    if negated:
        found.append(_finding("negation_differs", where, (
            f"The statement negates {', '.join(negated)}; its quotes and their sentences hold no negation."
            if change == "added" else
            f"Its quotes or their sentences negate {', '.join(negated)}; the statement holds no negation.")))
    speaker = _speaker(statement)
    unnamed = sorted({word for word in speaker if not _meets(word, named)})
    if unnamed:
        found.append(_finding("speaker_not_in_source", where, f"Not in the source: {', '.join(unnamed)}."))
    elif speaker and any(_speaker(source[start:end]) for start, end in spans):
        # A quote's sentence that names its own speaker binds the statement to that speaker (or the headline's
        # publisher); a speaker named only elsewhere in the source is someone else. A sentence whose speaker is only
        # a pronoun ("He said") names nobody, so it binds nothing.
        context = set(WORD.findall(_fold(around))) | titled
        elsewhere = sorted({word for word in speaker if not _meets(word, context)})
        if elsewhere:
            found.append(_finding("speaker_differs", where, f"Not in the sentence its quotes come from, which names "
                                                            f"its own speaker: {', '.join(elsewhere)}."))
    content = _content(statement)
    quote_words = set(WORD.findall(_fold(quoted + " " + around)))
    missing = sorted({word for word in content if not _meets(word, quote_words) and word not in ATTRIBUTING})
    if content and len(missing) >= MIN_UNSUPPORTED and len(missing) / len(set(content)) >= UNSUPPORTED_SHARE:
        found.append(_finding("beyond_quotes", where, f"Not in its quotes or their sentences: {', '.join(missing)}."))
    return found


def _absence_checks(analysis: dict, source: str) -> list[dict]:
    found = []
    spans = paragraphs(source)
    blocks = [set(WORD.findall(_fold(source[start:end]))) for start, end in spans]
    numbers = [{value for value, _ in _numbers(source[start:end])} for start, end in spans]
    for index, item in enumerate(analysis["missing_information"], start=1):
        if not ABSENCE.search(item) or set(WORD.findall(_fold(item))) & QUESTION:
            continue
        terms = sorted(set(_content(ABSENCE.sub(" ", item))) - ASPECT)
        values = {value for value, _ in _numbers(item)}
        if len(terms) + len(values) < 2:
            continue
        for paragraph, (held, figures) in enumerate(zip(blocks, numbers), start=1):
            if all(_meets(term, held) for term in terms) and values <= figures:
                found.append(_finding("absence_contradicted", f"missing_information[{index}]",
                                      f"Paragraph {paragraph} of the source holds: {', '.join(terms)}."))
                break
    return found


def for_user_analysis(analysis: dict) -> dict | None:
    """The rubric for a user's Analysis payload (user-api-0.2): its source's headline and text and its result's
    analysis. None when no analysis was recorded (prepared, running, declined, incomplete or invalid). Reads only; the
    payload, its result and result_sha256 are not changed."""
    result = analysis.get("result")
    if not result or result.get("analysis") is None:
        return None
    return assess(analysis["source"]["headline"], analysis["source"]["text"], result["analysis"])


def assess(headline: str, source: str, analysis: dict | None) -> dict:
    """The rubric for one analysis (as research_reading resolves it) and its source. Reads only."""
    findings = source_checks(headline, source)
    if analysis is not None:
        sentences, named = _sentences(source), set(WORD.findall(_fold(headline + " " + source)))
        titled = set(WORD.findall(_fold(headline)))
        for item in analysis["established"]:
            findings += _statement_checks(item["number"], item, source, sentences, named, titled)
        in_source = {value for value, _ in _numbers(source)}
        for value, unit in _numbers(analysis["interpretation"]["text"]):
            if value not in in_source:
                findings.append(_finding("interpretation_number_not_in_source", "interpretation",
                                         f"{value}{' ' + unit if unit else ''} is in the interpretation."))
        findings += _absence_checks(analysis, source)
        if not analysis["missing_information"] and not analysis["tests"]:
            findings.append(_finding("no_unknowns", "analysis", "No missing information and no tests are listed."))
    return {"rubric_version": RUBRIC_VERSION, "rejected": [],
            "rejected_note": ("Rejection belongs to the research contract (schema, every quote found); an analysis "
                              "that reached this rubric passed it, and this rubric rejects nothing."),
            "findings": findings, "flagged": len(findings), "checks": CHECKS, "human_review": list(HUMAN_REVIEW),
            "statement": ("Lexical checks of words, figures, units, periods and attribution. A flag asks a person to "
                          "look; no flag is not a confirmation that the analysis is correct.")}
