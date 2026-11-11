"""Economic meaning kept wherever a figure, a category or a reference appears (econ-fidelity-0.5).

The 28 October fresh update (docs/news-econ-fidelity-2026-10-28.md (private; not in the public repository)) showed
meaning lost at the boundaries between the evidence, the structured content and what readers see. Each rule below is
deterministic: it reads stated metadata, words and numbers, never economics, and passing it does not show that a brief is
right.

- **A figure keeps its qualifiers.** New home sales of 676,000 were a seasonally adjusted annual rate, recorded so in
  the figure, yet the development sentence and the compact references showed "676,000 houses", which reads as one
  month's count; the change of -0.6% carried a margin of +/- 13.8% in its quote that no surface showed. ``qualifiers``
  derives, from the figure's stated metadata only, what changes the kind of number it is: an annual rate (with its
  seasonal adjustment), a seasonal adjustment, a nominal or inflation-adjusted basis the figure states, a summary
  statistic of survey answers, and a margin the quote writes beside the number, with whether it is wider than a
  change. ``render`` writes them beside each figure in a text (leaving out what the same sentence already says) and
  ``reference`` in each compact reference. "Not stated" is never written inline, and nominal or real is not labelled
  "not stated" for a quantity that is not money (``shows_basis``).
- **A reference resolves or stops publication.** {f1} and {c1} are rendered only in the explanation's texts.
  ``reference_findings`` stops publication of one in the brief's own texts, of any reference in a name or an
  observable (shown as written), and of anything that looks like a reference but names none ("{F1}", "{f 1}",
  "figure:f1").
- **A goods classification is the evidence's.** ``category_findings`` stops publication of a classification of goods
  by durability or use (durable, nondurable, capital, consumer, intermediate, investment, manufactured, finished or
  producer goods) that the evidence does not name, so durable goods never become capital goods or all manufactured
  goods. A classification the evidence names passes: the rule asks for support, it forbids no word. Other categories
  (sectors, components) and inference stages (orders and shipments or output, output and employment, an aggregate and
  its components) are kept apart by the request contract (brief_stages) and remain an editor's semantic check.
- **A scale word stays with its number.** ``scale_problem`` finds a figure whose quote writes "4.9 million" while its
  unit leaves out "million" (a millionfold error the quote check alone passes), whose unit names a scale its quote does
  not write, or whose value converts the quoted number ("4.9 million" given as 4900000, found by exact decimal
  arithmetic) instead of keeping it as written. The two-stage contract refuses such a figure (brief-evidence-2);
  ``findings`` stops publication of one saved any other way.

- **A net percentage stays a balance of answers** (0.2, econ-calc-0.3). A survey's net percentage, the share of
  respondents reporting one direction minus the share reporting the other, is written with "net percentage of
  respondents" wherever it appears, and ``findings`` stop publication of a text that writes one as the size of a change
  ("lending fell by {f1}", "a {f1} decline"), as level_as_change does for a level: a net tightening reported by banks
  is not a fall in lending.

- **A net percentage stays a balance of answers in every text** (0.3, after the ECB stage 1 of 29 October 2026,
  docs/news-net-balance-prose-2026-10-29.md (private; not in the public repository)). 0.2 read only the explanation's
  {f1} references, so a first stage's theme "Net demand for housing loans fell by 27% net, driven by interest rates"
  passed every check although its figure was typed a net percentage of -27%, and assembly kept it in the brief.
  ``balance_findings`` reads every text of a version (``prose_places``: the brief's own, where numbers are written as
  numbers, the explanation's and its names) against the version's typed figures (``typed_rows``). A number is read as a
  net percentage by its reference, or, written as a percentage or in points, by its magnitude when every typed figure and
  calculation of that magnitude is a net percentage; a magnitude also typed as anything else is ambiguous and left alone.
  Publication stops for such a number written as the size of a change ("fell by 12%", "by a net 12%", "down 12 points",
  "a 12% decline"; "a net 12% of banks" is a proportion of respondents, never a change), and for a sentence carrying one
  that gives a reason (the guard's causal words, the other forms of "drive", "lead to" and "result in", "owing to")
  without saying who gives it (the guard's reporting words or their other forms). The first stage refuses either in its
  own texts from brief-evidence-4 (brief_stages), because assembly keeps them unchanged.

  0.4 (review of 0.3, which no saved version recorded): 0.3 let any "of" after the number pass before reading what
  came before it, so "fell by 12% of last quarter's level" passed. A change verb just before the number now makes it a
  change whatever follows; "of" still marks a proportion of respondents after no construction ("a net 12% of banks
  reported …") and after "by" following any other word ("cited by a net 9% of banks").

  What it cannot establish: that a number it does not read as a balance (one the version did not type, a rounded one,
  one also typed otherwise) is described rightly; that words for a balance's direction or size ("higher demand",
  "most banks") match it; that the respondents, the category or the period are named rightly; or that an attributed
  reason is the one the source gives. A matched number is not shown to be interpreted correctly, only not written as
  one of these misreadings; it reads typed metadata, words and numbers, never economics. Two errors it makes, stated:
  an untyped figure of a typed balance's size, even one its source states ("industrial output fell by 12%" beside a
  balance of -12%), is read as the balance and stops publication, or refuses a first stage (typing that figure makes
  the size ambiguous, and it is left alone); and a change verb outside its list followed by "of" ("cut by 12% of its
  level") is read as naming who answered.

- **Whose claim, and a headline's bound** (0.5,
  docs/news-claims-conditions-2026-10-29.md (private; not in the public repository)). A version that records claims
  (brief_claims) is checked for numbers the evidence writes only inside claims that are not stated as so
  (``claim_only_number``, brief_claims.findings): never leading a headline when they are questions, conditions or views,
  and cited wherever a fact or an explanation text with a basis writes them. A figure bound to such a claim is written
  with what it is (``qualifiers``: "a stated expectation, plan or scenario, not an observed outcome", "conditional: …").
  ``bound_findings`` stops a headline that writes a number equal, in value and scale, to a typed figure stated only as a
  bound ("more than", "up to", "about") without a bound of that kind just before it: the audit's "$5 billion" for "more
  than $5 billion". It reads the headline only. On the 43 publications current when it was written it stops one headline,
  that error; applied to every text it would also have stopped four correct wordings (a bound governing a coordinated
  number, "the 24% … figure") and three back-references to an aim, so it is not. It cannot read a bound written after the
  number ("$5 billion-plus", stopped), an untyped or rounded number, or a scale abbreviation ("$5bn").

- **Plain text** (0.6, docs/news-plain-names-2026-11-01.md (private; not in the public repository)). The refused von der
  Leyen first stage of 29 October 2026 ended a fact with "</br>", and no check stopped it; readers would have seen the
  tag as written. ``markup_findings`` stops publication of an HTML-like tag (a "<" followed by a letter or "/", up to a
  ">") in any text a reader sees: the brief's own texts and an explanation's texts and names (``prose_places``). Claim
  quotes are the material's own words and are not read. "<2%", "x < y" and "AT&T" are no tags. It stops publication only;
  a first stage is not refused for it, since an assisted correction repairs a saved version without another paid request.

``findings`` are recorded with each new version beside the guards (story_briefs.add_version); they stop publication
only and never change a version saved before them.
"""
from decimal import Decimal
import re

from . import brief_claims, econ_calc

FIDELITY_VERSION = "econ-fidelity-0.6"
# 0.6: an HTML-like tag: "<" then a letter (or "/" and a letter), an optional run of attributes, an optional "/", ">".
MARKUP = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
IN_MARKUP = ("A text readers see is plain words: they would see this markup as written. An assisted correction removes "
             "it and keeps the version's history.")

# ---------------------------------------------------------------- what a figure is

SEASONAL_WORDS = {"seasonally_adjusted": "seasonally adjusted", "not_seasonally_adjusted": "not seasonally adjusted"}
STATISTIC_WORDS = {"mean": "a mean of survey answers", "median": "a median of survey answers",
                   "other_summary": "a summary statistic"}
# Units of money: nominal or real describes them. A count (houses, people) or a physical quantity is neither.
MONEY = re.compile(r"[$€£¥]|\b(?:dollars?|euros?|eur|usd|gbp|pounds? sterling|sterling|yen|jpy|yuan|"
                   r"renminbi|cny|rmb|francs?|chf|cad|aud|rupees?|inr|won|krw|kronor|krona|kroner|krone|sek|nok|dkk|"
                   r"zloty|pln|forints?|huf|rand|zar|pesos?|mxn|lira|rubles?|roubles?|reais|brl)\b", re.IGNORECASE)
# What may stand between a number and the margin the quote writes for it: "0.6 percent (+/- 13.8%)".
BETWEEN = re.compile(r"\s*(?:%|percent|per cent|percentage points?)?\s*[(\[]?\s*", re.IGNORECASE)
PERCENT_AFTER = re.compile(r"\s*(?:%|percent\b|per cent\b)", re.IGNORECASE)
SENTENCE_END = re.compile(r"[.;!?](?=\s|$)")
NET = "net percentage of respondents"
CHANGE_VERBS = (r"rose|rise[sn]?|fell|fall(?:s|en)?|increased?|increases|decreased?|decreases|declined?|declines|grew|"
                r"grow(?:s|n)?|dropped|drops?|climbed|jumped|up|down|gained|lost")
CHANGE_NOUNS = r"rise|increase|decline|drop|fall|gain|growth|jump"
# A figure written as the size of a change ("rose by {f1}", "a {f1} decline"); story_economics' level_as_change too.
CHANGE_OF = re.compile(r"\b(?:" + CHANGE_VERBS + r")\s+(?:by\s+)?\{(f\d{1,2})\}|\{(f\d{1,2})\}\s+(?:" + CHANGE_NOUNS +
                       r")\b", re.IGNORECASE)
# 0.3: a balance written as the size of a change: "by" just before its number ("fell by 12%", "by a net 12%"), a change
# verb just before it ("fell 12%", "down 12 points") or a change noun just after it ("a 12% decline"), never "12% of"
# (a proportion of respondents). A number written as a number is read only as a percentage or in points.
PERCENT_OR_POINTS = re.compile(r"\s?(?:%|per ?cent\b|percentage points?\b|points?\b|pp\b)", re.IGNORECASE)
BY_BEFORE = re.compile(r"\bby\s+(?:a\s+)?(?:net\s+)?$", re.IGNORECASE)
VERB_BEFORE = re.compile(r"\b(?:" + CHANGE_VERBS + r")\s+(?:a\s+)?(?:net\s+)?$", re.IGNORECASE)
CHANGED_BY = re.compile(r"\b(?:" + CHANGE_VERBS + r")\s+by\s+(?:a\s+)?(?:net\s+)?$", re.IGNORECASE)  # 0.4
NOUN_AFTER = re.compile(r"[\s-]*(?:net\s+)?(?:" + CHANGE_NOUNS + r")\b", re.IGNORECASE)
OF_AFTER = re.compile(r"\s+of\b", re.IGNORECASE)
# A reason given for a balance, beyond the guard's causal words (story_briefs.CAUSAL), and who gives it, beyond its
# reporting words (story_briefs.ATTRIBUTED): the other forms of the same verbs.
REASON = re.compile(r"\b(?:driven|driving|drivers?|leading to|resulting in|owing to)\b", re.IGNORECASE)
REPORTED = re.compile(r"\b(?:report|say|cite|cites|citing)\b", re.IGNORECASE)
AS_CHANGE = ("A net percentage is the share of respondents reporting one direction minus the share reporting the "
             "other, not the size of a change: say what they reported, never that a quantity rose or fell by it.")
UNATTRIBUTED = ("A net percentage counts respondents' answers; a reason given for it is theirs or the publisher's, so "
                "the sentence says who gives it (\"banks reported …\", \"the ECB says …\"), never states it as an "
                "established cause.")


def _number(match: re.Match) -> tuple[str, float, int]:
    """(the number as written without separators, its value, its decimals) of an econ_calc.SIGNED match."""
    whole, part = match.group(3), match.group(4)
    lexeme = econ_calc.ungrouped(whole) + (f".{part}" if part else "")
    return lexeme, float(lexeme), len(part or "")


def margin(row: dict) -> dict | None:
    """The margin the quote writes beside the figure's own number ("0.6 percent (+/- 13.8%)"), as written, with
    whether it is wider than the figure when the figure is a change in the same unit; None when the quote states none
    (a calculation has none)."""
    quote, value = row.get("quote"), row.get("value")
    if not isinstance(quote, str) or row.get("op") is not None or isinstance(value, bool) or \
            not isinstance(value, (int, float)):
        return None
    found = list(econ_calc.SIGNED.finditer(quote))
    for index, match in enumerate(found[:-1]):
        if match.group(1) or abs(_number(match)[1] - abs(value)) > 1e-9:
            continue
        after = found[index + 1]
        if not after.group(1) or not BETWEEN.fullmatch(quote[match.end():after.start()]):
            continue
        _, size, decimals = _number(after)
        percent = bool(PERCENT_AFTER.match(quote, after.end()))
        shown = f"±{size:,.{decimals}f}" + ("%" if percent else f" {row['unit']}")
        same_unit = percent == (row.get("unit") == "percent")
        wider = row.get("measure") in ("change", "growth_rate") and same_unit and size >= abs(value)
        return {"value": size, "display": shown, "wider_than_change": wider,
                "text": f"stated margin {shown}" + (", wider than the change" if wider else "")}
    return None


def _annual_rate(row: dict, rows: dict[str, dict] | None) -> bool:
    if row.get("stock_flow") == "flow_annual_rate":
        return True  # A difference of two annual rates is at an annual rate too.
    return row.get("op") == "difference" and bool(rows) and all(
        (rows.get(name) or {}).get("stock_flow") == "flow_annual_rate" for name in row.get("inputs", []))


def qualifiers(row: dict, rows: dict[str, dict] | None = None) -> list[str]:
    """What changes the kind of number a figure or calculation is, from its stated metadata only (``rows``: the
    explanation's figures and calculations by ID, for a calculation's inputs)."""
    words = []
    seasonal = row.get("seasonal")
    if _annual_rate(row, rows):
        words.append("seasonally adjusted annual rate" if seasonal == "seasonally_adjusted" else
                     "annual rate, not seasonally adjusted" if seasonal == "not_seasonally_adjusted" else "annual rate")
    elif seasonal in SEASONAL_WORDS:
        words.append(SEASONAL_WORDS[seasonal])
    if row.get("basis") == "nominal":
        words.append("nominal")
    elif row.get("basis") == "real":
        words.append("inflation-adjusted")
    if row.get("measure") == "net_percentage":
        words.append(NET)
    elif row.get("statistic") in STATISTIC_WORDS:
        words.append(STATISTIC_WORDS[row["statistic"]])
    stated = margin(row)
    if stated:
        words.append(stated["text"])
    if row.get("claim_note"):  # 0.5: set by story_economics.reader_view for a figure bound to a claim.
        words.append(row["claim_note"])
    return words


def shows_basis(row: dict) -> bool:
    """Whether a figure's nominal or real basis is worth stating: always when the figure states it; "not stated" only
    for money, or a change or growth rate in percent (of something that may be money). A count is neither."""
    if row.get("basis") != "not_stated":
        return True
    unit = row.get("unit", "")
    return bool(MONEY.search(unit)) or (unit in ("percent", "percentage points") and
                                        row.get("measure") in ("change", "growth_rate"))


def _sentence(text: str, start: int, end: int) -> str:
    left = max((match.end() for match in SENTENCE_END.finditer(text, 0, start)), default=0)
    right = SENTENCE_END.search(text, end)
    return text[left:right.end() if right else len(text)]


def _said(phrase: str, sentence: str) -> bool:
    """Whether a sentence already states a qualifier (its words before any comma; "not seasonally adjusted" does not
    state "seasonally adjusted"; a sentence that speaks of the margin states it)."""
    if phrase.startswith("stated margin") and re.search(r"\bmargins?\b", sentence, re.IGNORECASE):
        return True
    if phrase == NET:
        return re.search(r"\bnet (?:percentages?|balances?)\b", sentence, re.IGNORECASE) is not None
    head = econ_calc.normalized(phrase.split(",")[0])
    return re.search(r"(?<!not )\b" + re.escape(head) + r"(?![\w])", econ_calc.normalized(sentence)) is not None


def render(text: str, rows: dict[str, dict]) -> str:
    """A text with each figure and calculation written as its value (without a bound word the sentence states just
    before it, as econ_calc.render) and, in brackets, the qualifiers its sentence does not already state."""
    def one(match: re.Match) -> str:
        row = rows[match.group(1)]
        value = econ_calc.shown(row)
        before = " " + " ".join(text[:match.start()].lower().split())
        for word, phrases in econ_calc.STATED_BOUND.items():
            if value.startswith(word) and any(before.endswith(" " + phrase) for phrase in phrases):
                value = value[len(word):]
                break
        sentence = _sentence(text, match.start(), match.end())
        extra = [phrase for phrase in qualifiers(row, rows) if not _said(phrase, sentence)]
        return f"{value} ({'; '.join(extra)})" if extra else value
    return econ_calc.PLACEHOLDER.sub(one, text)


def reference(row: dict, rows: dict[str, dict] | None = None) -> str:
    """A figure or calculation as a compact reference: its value with every qualifier, its label, and for a figure its
    period and any vintage."""
    words = qualifiers(row, rows)
    head = econ_calc.shown(row) + (f" ({'; '.join(words)})" if words else "")
    if row.get("op") is not None:
        return f"{head}: {row['label']}"
    vintage = (row.get("vintage") or {}).get("label")
    return f"{head}: {row['label']} ({row['period']}{'; ' + vintage if vintage else ''})"


# ---------------------------------------------------------------- where a reference may stand

BRACED = re.compile(r"\{[^{}\n]{0,40}\}")
NAMED = re.compile(r"\b(?:figure|calc):[a-z]?\d{1,2}\b", re.IGNORECASE)
PLACEHOLDER_IN_BRIEF = ("A brief's text states what was reported in words; figures are shown by name only in the "
                        "explanation.")
UNRESOLVED = ("Something here looks like a reference to a figure or calculation but names none, so readers would see it "
              "as written; write {f1} or {c1} for one the explanation holds, or the words themselves.")
IN_LABEL = ("A name or an observable is shown as written: refer to figures only in the explanation's texts, where they "
            "are rendered with their units and qualifiers.")


def brief_places(content: dict) -> list[tuple[str, str]]:
    """The brief's own texts, shown as written (never rendered), with where each is."""
    places = [("headline", content["headline"]), ("summary", content["summary"])]
    places += [(f"facts[{index}]", row["text"]) for index, row in enumerate(content["facts"])]
    places += [(f"implications[{index}]", row["text"]) for index, row in enumerate(content["implications"])]
    places += [(f"themes[{index}]", f"{row['name']} {row['basis']}") for index, row in enumerate(content["themes"])]
    places += [(f"uncertainties[{index}]", row) for index, row in enumerate(content["uncertainties"])]
    places += [(f"missing[{index}]", row) for index, row in enumerate(content["missing"])]
    return places


def label_places(economics: dict) -> list[tuple[str, str]]:
    """An explanation's names and observables: shown as written."""
    places = [(f"channels[{index}].affected[{n}].name", party["name"])
              for index, row in enumerate(economics["channels"]) for n, party in enumerate(row["affected"])]
    return places + [(f"watch[{index}].observable", row["observable"]) for index, row in enumerate(economics["watch"])]


def text_places(economics: dict) -> list[tuple[str, str]]:
    """An explanation's texts, each rendered for readers with its figures and calculations."""
    places = [("change", economics["change"]["text"]), ("significance", economics["significance"]["text"]),
              ("main_uncertainty", economics["main_uncertainty"])]
    places += [(f"assumptions[{index}]", row["text"]) for index, row in enumerate(economics["assumptions"])]
    for index, row in enumerate(economics["channels"]):
        places += [(f"channels[{index}]", row["text"])]
        places += [(f"channels[{index}].steps[{step}]", text) for step, text in enumerate(row["steps"])]
        places += [(f"channels[{index}].affected[{n}].how", party["how"]) for n, party in enumerate(row["affected"])]
        places += [(f"channels[{index}].conditions", row["conditions"])] if row["conditions"] else []
    for index, row in enumerate(economics["second_order"]):
        places += [(f"second_order[{index}]", row["text"]), (f"second_order[{index}].conditions", row["conditions"])]
    places += [(f"alternatives[{index}]", row["text"]) for index, row in enumerate(economics["alternatives"])]
    return places + [(f"watch[{index}].text", row["text"]) for index, row in enumerate(economics["watch"])]


def _explained(content: dict) -> dict | None:
    economics = content.get("economics")
    return economics if isinstance(economics, dict) and economics.get("status") == "explained" else None


def _stray(text: str) -> str | None:
    """The first thing in a text that looks like a reference but is not a placeholder."""
    for match in BRACED.finditer(text):
        if not econ_calc.PLACEHOLDER.fullmatch(match.group(0)):
            return match.group(0)
    named = NAMED.search(text)
    return named.group(0) if named else None


def reference_findings(content: dict) -> list[dict]:
    """Publication stops for references readers would see unrendered."""
    rows = []
    for where, text in brief_places(content):
        names = econ_calc.placeholders(text)
        if names:
            rows.append({"where": where, "rule": "placeholder_in_brief", "matched": "{" + names[0] + "}",
                         "detail": PLACEHOLDER_IN_BRIEF})
        stray = _stray(text)
        if stray:
            rows.append({"where": where, "rule": "unresolved_reference", "matched": stray, "detail": UNRESOLVED})
    economics = _explained(content)
    if economics is None:
        return rows
    for where, text in label_places(economics):
        found = BRACED.search(text) or NAMED.search(text)
        if found:
            rows.append({"where": f"economics.{where}", "rule": "reference_in_label", "matched": found.group(0),
                         "detail": IN_LABEL})
    for where, text in text_places(economics):
        stray = _stray(text)
        if stray:
            rows.append({"where": f"economics.{where}", "rule": "unresolved_reference", "matched": stray,
                         "detail": UNRESOLVED})
    return rows


# ---------------------------------------------------------------- goods classifications

CLASSIFIED = re.compile(r"\b(non-?durable|durable|capital|consumer|intermediate|investment|manufactured|finished|"
                        r"producer)\s+goods\b", re.IGNORECASE)
CATEGORY = ("A classification of goods is named as the evidence names it: durable, capital and manufactured goods are "
            "different categories, and one is never put for another. This one is not in the evidence.")


def _plain(text: str) -> str:
    text = econ_calc.normalized(text).replace("-", " ")
    return " ".join(text.replace("non durable", "nondurable").split())


def category_findings(content: dict, found: dict) -> list[dict]:
    """Publication stops for a goods classification the evidence (story_economics.evidence) does not name."""
    evidence = _plain(found["text"])
    places = brief_places(content)
    economics = _explained(content)
    if economics is not None:
        places += [(f"economics.{where}", text) for where, text in text_places(economics) + label_places(economics)]
    rows = []
    for where, text in places:
        for match in CLASSIFIED.finditer(text):
            if _plain(match.group(0)) not in evidence:
                rows.append({"where": where, "rule": "category_not_in_evidence", "matched": match.group(0),
                             "detail": CATEGORY})
                break
    return rows


# ---------------------------------------------------------------- scale words

EXPONENT = {"thousand": 3, "million": 6, "billion": 9, "trillion": 12}
SHORT = {"bn": "billion", "mn": "million", "tn": "trillion", "trn": "trillion"}
SCALE_AFTER = re.compile(r"\s*(thousands?|millions?|billions?|trillions?|bn|mn|tn|trn)\b", re.IGNORECASE)
SCALE_IN = re.compile(r"\b(thousands?|millions?|billions?|trillions?|bn|mn|tn|trn)\b", re.IGNORECASE)


def _scale(word: str) -> str:
    word = word.lower()
    return SHORT.get(word, word.rstrip("s"))


def _plain_number(value: float | int) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def scale_problem(row: dict, where: str) -> str | None:
    """Why a figure's value, unit and quote disagree on scale, or None. The value is the number as the quote writes it
    and the unit carries a scale word written after it ("4.9 million Afghans": 4.9 in "million people")."""
    quote, value, unit = row.get("quote"), row.get("value"), row.get("unit")
    if not isinstance(quote, str) or not isinstance(unit, str) or isinstance(value, bool) or \
            not isinstance(value, (int, float)):
        return None
    in_unit = SCALE_IN.search(unit)
    stated = _scale(in_unit.group(1)) if in_unit else None
    held, converted = [], None
    for match in econ_calc.SIGNED.finditer(quote):
        if match.group(1):
            continue  # A margin ("+/- 13.8%"), never the figure's own number.
        lexeme, number, _ = _number(match)
        after = SCALE_AFTER.match(quote, match.end())
        written = _scale(after.group(1)) if after else None
        if abs(number - abs(value)) < 1e-9:
            held.append(written)
        elif written and converted is None and \
                Decimal(lexeme) * Decimal(10) ** EXPONENT[written] == abs(Decimal(str(value))):
            converted = (lexeme, written)
    if not held:
        if converted is None:
            return None  # econ_calc's quote check refuses a value its quote does not hold.
        lexeme, written = converted
        return (f"{where} gives {_plain_number(value)} for the quoted “{lexeme} {written}”: a figure keeps "
                f"the number as its quote writes it ({lexeme}), with the scale in its unit (“{written} …”), "
                "and is never converted.")
    if stated in held:
        return None
    written = next((word for word in held if word), None)
    if written is not None:
        return (f"{where}'s quote writes its number with “{written}”, but its unit “{unit}” "
                + (f"says {stated}" if stated else "leaves the scale out") +
                f": the unit carries the scale as written (“{written} …”).")
    return (f"{where}'s unit “{unit}” says {stated}, but its quote writes the number without that scale.")


# ---------------------------------------------------------------- a headline's bound (0.5)

# A bound written just before a number: the renderer's (econ_calc.STATED_BOUND) and a few of the same kind.
BOUND_PHRASES = {
    "lower_bound": (*econ_calc.STATED_BOUND["at least "], "upwards of", "in excess of", "greater than"),
    "upper_bound": (*econ_calc.STATED_BOUND["at most "], "as much as", "as many as", "not more than", "fewer than",
                    "nearly"),
    "approximate": (*econ_calc.STATED_BOUND["about "], "close to", "an estimated", "estimated", "almost"),
}
CURRENCY_BEFORE = re.compile(r"(?:\b(?:eur|usd|us|gbp|chf|jpy)\b|[$€£¥])\s*$")
BOUND_DROPPED = ("The headline writes a number the evidence states only as a bound ({bound}: “{quote}”) without that "
                 "bound: write it as the source does (“more than”, “up to”, “about”, …) just before the number.")


def bound_findings(content: dict) -> list[dict]:
    """Publication stops for a headline number equal in value and scale to a typed figure or calculation stated only
    as a bound (no exact one of that value), written without a bound phrase of that kind just before it."""
    economics = _explained(content)
    if economics is None:
        return []
    typed = {}
    for row in economics["figures"] + economics["calculations"]:
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        unit = SCALE_IN.search(row.get("unit") or "")
        typed.setdefault((round(abs(value), 9), _scale(unit.group(1)) if unit else None), []).append(row)
    text = content["headline"]
    found = []
    for match in econ_calc.SIGNED.finditer(text):
        if match.group(1):
            continue
        after = SCALE_AFTER.match(text, match.end())
        rows = typed.get((round(abs(_number(match)[1]), 9), _scale(after.group(1)) if after else None)) or []
        bounds = {row.get("bound", "exact") for row in rows}
        if not rows or "exact" in bounds or len(bounds) != 1:
            continue
        bound = bounds.pop()
        before = CURRENCY_BEFORE.sub("", " " + " ".join(text[:match.start()].lower().split())).rstrip()
        if not any(before.endswith(" " + phrase.strip()) for phrase in BOUND_PHRASES[bound]):
            found.append({"where": "headline", "rule": "bound_dropped", "matched": match.group(0),
                          "detail": BOUND_DROPPED.format(bound=bound.replace("_", " "),
                                                         quote=rows[0].get("quote") or rows[0].get("label"))})
    return found


# ---------------------------------------------------------------- all of it

def prose_places(content: dict) -> list[tuple[str, str]]:
    """Every text of a version a reader sees: the brief's own, and an explanation's texts and names."""
    economics = _explained(content)
    if economics is None:
        return brief_places(content)
    return brief_places(content) + [(f"economics.{where}", text)
                                     for where, text in text_places(economics) + label_places(economics)]


def typed_rows(content: dict) -> list[dict]:
    """The figures and calculations a version's explanation types (none without an explanation)."""
    economics = _explained(content)
    return economics["figures"] + economics["calculations"] if economics is not None else []


def _balances(rows: list[dict]) -> tuple[set[str], set[float]]:
    """(the IDs of the typed net percentages, the magnitudes that only net percentages have)."""
    ids = {row["id"] for row in rows if row.get("measure") == "net_percentage"}
    valued = [row for row in rows if isinstance(row.get("value"), (int, float)) and not isinstance(row["value"], bool)]
    sizes = {round(abs(row["value"]), 9) for row in valued if row["id"] in ids}
    return ids, sizes - {round(abs(row["value"]), 9) for row in valued if row["id"] not in ids}


def _held(text: str, ids: set[str], sizes: set[float]) -> list[tuple[int, int]]:
    """Where a text writes a balance: (start, end) of its reference, or of its number written as a percentage or in
    points with that unit."""
    spans = [match.span() for match in econ_calc.PLACEHOLDER.finditer(text) if match.group(1) in ids]
    for match in econ_calc.SIGNED.finditer(text):
        unit = PERCENT_OR_POINTS.match(text, match.end())
        if not match.group(1) and unit and round(_number(match)[1], 9) in sizes:
            spans.append((match.start(), unit.end()))
    return sorted(spans)


def _as_change(text: str, start: int, end: int) -> str | None:
    """The words that write the balance at text[start:end] as the size of a change, or None (0.4). A change verb just
    before it, with or without "by", makes it one whatever follows ("fell by 12% of last quarter's level"). "by" after
    any other word makes it one unless "of" follows, where "by" names who answered ("cited by a net 9% of banks").
    With neither, "of" after it is a proportion ("a net 12% of banks"), and a change noun after it a change ("a 12%
    decline")."""
    before = text[max(0, start - 40):start]
    found = BY_BEFORE.search(before) or VERB_BEFORE.search(before)
    proportion = OF_AFTER.match(text, end) is not None
    if found and (not proportion or VERB_BEFORE.search(before) or CHANGED_BY.search(before)):
        return text[start - len(before) + found.start():end]
    if found or proportion:
        return None
    noun = NOUN_AFTER.match(text, end)
    return text[start:noun.end()] if noun else None


def balance_findings(places: list[tuple[str, str]], rows: list[dict]) -> list[dict]:
    """Publication stops (0.3) for a net percentage written as the size of a change, and for a sentence carrying one
    that gives a reason without saying who gives it, in any of ``places`` ((where, text)); ``rows`` are the version's
    typed figures and calculations, which alone say what a number is."""
    from .story_briefs import ATTRIBUTED, CAUSAL
    ids, sizes = _balances(rows)
    found = []
    for where, text in places if ids else []:
        held = _held(text, ids, sizes)
        for start, end in held:
            written = _as_change(text, start, end)
            if written:
                found.append({"where": where, "rule": "net_percentage_as_change", "matched": written,
                              "detail": AS_CHANGE})
        left = 0
        for stop in [match.end() for match in SENTENCE_END.finditer(text)] + [len(text)]:
            sentence, carries = text[left:stop], any(left <= start < stop for start, _ in held)
            reason = CAUSAL.search(sentence) or REASON.search(sentence)
            if carries and reason and not (ATTRIBUTED.search(sentence) or REPORTED.search(sentence)):
                found.append({"where": where, "rule": "net_percentage_reason_unattributed",
                              "matched": reason.group(0), "detail": UNATTRIBUTED})
            left = stop
    return found


def markup_findings(places: list[tuple[str, str]]) -> list[dict]:
    """Publication stops (0.6) for markup in any of ``places`` ((where, text)), the first tag of each text."""
    found = []
    for where, text in places:
        tag = MARKUP.search(text)
        if tag:
            found.append({"where": where, "rule": "markup_in_text", "matched": tag.group(0), "detail": IN_MARKUP})
    return found


def findings(content: dict, found: dict | None) -> list[dict]:
    """econ-fidelity's publication stops for a version (``found``: story_economics.evidence for a version with an
    explanation or claims; None otherwise, when only references and markup are checked)."""
    rows = reference_findings(content) + markup_findings(prose_places(content))
    if found is None:
        return rows
    rows += brief_claims.findings(content, found["sources"])
    rows += bound_findings(content)
    rows += balance_findings(prose_places(content), typed_rows(content))
    rows += category_findings(content, found)
    for row in (content.get("economics") or {}).get("figures") or []:
        problem = scale_problem(row, f"Figure {row['id']}")
        if problem:
            rows.append({"where": f"economics.figures[{row['id']}]", "rule": "scale_mismatch",
                         "matched": row["quote"][:60], "detail": problem})
    return rows
