"""Figures and derived calculations of an economic explanation (econ-calc-0.2).

A figure is a number quoted from the explanation's evidence: a report of the story's material, or an item of its
context bundle (econ_context). It keeps what the number is: its unit, the period it covers, whether it is nominal or
real, whether it is seasonally adjusted (or an annual rate), whether it measures prices, its vintage (the source and the
time it was published), whether it is exact or a bound ("more than 95%"), which summary statistic it is (an observed
value, a mean, a median), and, for a level, whether it is a stock or a flow over a stated period. Its quote must appear
in that evidence and hold the number, so no figure comes from a drafter's memory.

Direction (0.2, reproduced 2026-10-26: a positive 5.2 was accepted against "output growth was -5.2%"). Numbers are read
with their signs (ASCII and Unicode minus signs, a plus sign, "+/-" margins; a dash inside a range such as 2021-2025 is
no sign). A figure states how its sign is established: ``as_quoted`` (the number as written; no sign is positive, and a
quoted sign must match), or ``from_words`` (an unsigned magnitude whose direction the quote states in words the figure
cites, as in "fell by 5.2%"). Cited words that say the opposite direction are refused; words whose direction cannot be
read are recorded as ``unclear``, and a positive reading of a magnitude the quote calls a decline as ``contradicted``,
so that the guard stops publication instead of silently accepting either direction.

A derived figure is computed here, never written by a drafter: a drafter names the operation and its inputs, and the
result, its unit, its bound and its formula are this module's. The operations refuse what does not compare: a percent
change is of two levels (growth rates differ in percentage points); nominal and real, seasonally adjusted and
unadjusted, means and medians, stocks and flows are never combined; a nominal growth rate is deflated only by a price
change of the same period and only for observed values (summaries of separate survey answers do not deflate into the
same summary of real values); a share is a part of a whole of the same kind and period; a stock against a flow is the
number of periods of that flow ("1.33 months of sales"), never a percentage. A bound stays a bound, and two bounds in the
same direction bound nothing. Texts name figures and calculations by placeholders ({f1}, {c1}) rendered from these values.

0.3 (2026-10-28, docs/news-econ-form-subject-2026-10-28.md (private; not in the public repository)). A survey's net
percentage (the share of respondents reporting one direction minus the share reporting the other, such as the ECB bank
lending survey's "net percentage of -27%") was recorded as a share, so a negative "share" passed and could read as a fall
of 27%. ``net_percentage`` is now its own measure: in percent, a summary of answers (statistic other_summary), neither a
stock nor a flow, and no calculation takes one, since what a difference or ratio of such balances means is not established
here. A share lies between 0% and 100%. Figures and calculations checked under an earlier version are checked as they were
then (``version``), so an earlier refusal or acceptance reproduces.

0.4 (2026-10-29, docs/news-econ-consistency-2026-10-29.md (private; not in the public repository)). A level could be a
stock or a flow over a month, a quarter, a year or at an annual rate, and nothing else: a trade deficit over the first half
of a year and exports over twelve months were recorded as levels of no kind, so they lost what they were and combined with
any other level of no kind. ``flow_other_period`` is a flow over another or an unstated period (``period`` says which). It
is never combined with another kind, and it gives no unit of periods for a stock set against it. Two such flows compare,
and the result names both periods; whether those periods are of equal length is not read from their words (a stated limit).
Figures saved under 0.2 and 0.3 are checked with the kinds they had (STOCK_FLOW_OF).

0.5 (2026-10-29, docs/news-flow-lengths-2026-10-29.md (private; not in the public repository)). Codex reproduced against
0.4 a one-day total of 3 billion euros and a one-year total of 900 billion euros, both typed ``flow_other_period``,
accepted as a difference of +897 billion euros and a change of +29,900%. A comparison of flow totals needs a common length
of time, and only a flow's kind establishes one: a month, a quarter, a year (any twelve consecutive months), or a rate per
year (PERIODS_OF). Its ``period`` says which dates it covers, and a change compares totals of the same length at different
dates. A flow over another or an unstated period has no established length: its figure is quoted and kept, but it enters no
difference, percent change or share (LENGTH_CHECKED), as a stock already could not be read as periods of it. No length is
read from a period's words, no value is annualised and no unstated period is assumed. Two flows of the same established
kind are taken to last equally long (a month is a month); that a share's part and whole cover the same dates still rests on
their identical period. Calculations under 0.4 replay as they were.

0.6 (2026-11-01, docs/news-space-thousands-2026-11-01.md (private; not in the public repository)). Thousands were
recognised only with commas, so the Commission's "annual quota of 350 000 hybrid vehicles" read as 350 and 0: the approved
von der Leyen trial's correct value 350,000 would have been refused, and a wrong value of 350 accepted. A space, a no-break
space, a narrow no-break space or a thin space now groups thousands too (SIGNED), and every reader of numbers (figure
quotes and their qualifiers, claims, and the stops for a number the evidence does not state) reads them so. A run of digit
groups is joined only when it can be one number: each group after the first has exactly three digits, and no digit group
stands directly before it, or after it by a space or a hyphen, so press contacts such as "+32 2 295 75 01" and "+32
229-69776" read as they did; a grouped number written straight after another number ("2025 350 000") also stays apart, a
stated limit. Figures checked under 0.2 to 0.5 read numbers as those versions did (SPACE_GROUPED), so a refusal or
acceptance recorded under them reproduces.

0.7 (2026-11-04, docs/news-number-boundaries-2026-11-04.md (private; not in the public repository)). Codex reproduced
against 0.6 two quotes in which a fragment passed and the whole number was refused: "a quota of 350 000-400 000 vehicles"
(350 accepted, 350000 refused) and "In 2025 350 000 vehicles" (the same). A token of four or more digits cannot be a group
of thousands, so a grouped number written after it is read whole, unless that token itself follows a digit group (a
telephone number such as "+49 6221 123 456"); and a hyphen between two complete grouped numbers is a range, read as its two
ends, not a sign. A figure is then never read from a run of digit groups that could also be one number and is not joined (a
telephone number, "350 000 12"): every number of such a run is refused as a figure (RUNS_CHECKED). A range written with a
dash (a hyphen, an en dash or another minus, spaced or not) gives two ends, not a point: a figure that the quote writes
only as one end is a bound, lower_bound for the lower end of a positive value and upper_bound for its upper end (reversed
for a negative value read from words, as "fell by 3-4%" is a fall of at least 3%), never exact or approximate. Numbers
joined by words ("from 3% to 4%", which may be a change) are not read as a range. Figures checked under 0.2 to 0.6 read
numbers as those versions did (READING_OF), and the other readers of numbers (qualifiers, claims and the stops for a
number the evidence does not state) read the two new shapes whole, as figures do.
"""
from decimal import ROUND_HALF_UP, Decimal
import math
import re
import unicodedata

from .accounts import AccountsRefused

CALC_VERSION = "econ-calc-0.7"
MEASURES = ("level", "change", "growth_rate", "rate", "share", "net_percentage")
MEASURES_OF = {"econ-calc-0.2": MEASURES[:5], "econ-calc-0.3": MEASURES, "econ-calc-0.4": MEASURES,
               "econ-calc-0.5": MEASURES, "econ-calc-0.6": MEASURES, "econ-calc-0.7": MEASURES}
PERCENT_MEASURES = ("growth_rate", "rate", "share", "net_percentage")
BASES = ("nominal", "real", "not_applicable", "not_stated")
SEASONAL = ("seasonally_adjusted", "not_seasonally_adjusted", "not_applicable", "not_stated")
SIGN_BASES = ("as_quoted", "from_words")
BOUNDS = ("exact", "lower_bound", "upper_bound", "approximate")
STATISTICS = ("observed", "mean", "median", "other_summary", "not_stated")
STOCK_FLOW_03 = ("stock", "flow_per_month", "flow_per_quarter", "flow_per_year", "flow_annual_rate", "not_applicable")
# 0.4: a flow over another or an unstated period (a day, a half-year, a programme's life; ``period`` says which), which
# up to 0.3 could only be recorded as a level of no kind. From 0.5 any twelve consecutive months are a year.
STOCK_FLOW = (*STOCK_FLOW_03[:-1], "flow_other_period", "not_applicable")
STOCK_FLOW_OF = {"econ-calc-0.2": STOCK_FLOW_03, "econ-calc-0.3": STOCK_FLOW_03, "econ-calc-0.4": STOCK_FLOW,
                 "econ-calc-0.5": STOCK_FLOW, "econ-calc-0.6": STOCK_FLOW, "econ-calc-0.7": STOCK_FLOW}
PERIODS_OF = {"flow_per_month": "months", "flow_per_quarter": "quarters", "flow_per_year": "years",
              "flow_annual_rate": "years"}
# 0.5: only flows whose kind establishes how long they last (those of PERIODS_OF) combine with one another.
# Calculation versions that refuse flows of no established length; whose figure checks read space-grouped thousands as
# one number; and that take no figure from an unjoined run of digit groups, nor a point from one end of a range (0.7).
LENGTH_CHECKED = ("econ-calc-0.5", "econ-calc-0.6", "econ-calc-0.7")
SPACE_GROUPED = ("econ-calc-0.6", "econ-calc-0.7")
RUNS_CHECKED = ("econ-calc-0.7",)
OPERATIONS = ("difference", "percent_change", "share", "stock_to_flow", "deflate")
UNSIGNED_OPERATIONS = ("ratio", "share", "stock_to_flow")  # "ratio": econ-calc-0.1, kept for reading old versions.
FIGURE_ID = re.compile(r"f\d{1,2}")
CALC_ID = re.compile(r"c\d{1,2}")
PLACEHOLDER = re.compile(r"\{([fc]\d{1,2})\}")
MINUS = r"\-\u2212\u2013\u2012\ufe63\uff0d"  # The hyphen escaped and first: inside a class, never a range.
MINUS_CHARS = "-\u2212\u2013\u2012\ufe63\uff0d"
# An optional margin ("+/-", a space allowed after it) or a sign written against the number, an optional currency
# symbol, then the number. A spaced minus is read in signed_numbers, where a range can be told apart.
SPACES = " \u00a0\u202f\u2009"  # 0.6: a space, a no-break space, a narrow no-break space or a thin space groups thousands.
_LEAD = r"(?<![\w.])(?:(\+/-|\u00b1)\s?|([+" + MINUS + r"]))?[$\u20ac\u00a3\u00a5]?(?<![\w.])"
_COMMAS = r"\d{1,3}(?:,\d{3})+"
# 0.6: joined only as a whole number: no digit group directly before it, none after it by a space or a hyphen.
_SPACED_06 = r"(?<!\d[" + SPACES + r"])\d{1,3}(?:[" + SPACES + r"]\d{3})+(?![" + SPACES + r"]?\d)(?!-\d)"
_TAIL = r"(?:\.(\d+))?(?!\w)"
# 0.7: joined as 0.6 does, and also after a lone token of four or more digits, which is never a group of thousands (a
# year: "In 2025 350 000"), unless that token itself follows a digit group (a telephone number, "+49 6221 123 456"); and
# before a hyphen that joins a second complete grouped number ("350 000-400 000", a range).
_SPACE = "[" + SPACES + "]"
_GROUPS = r"\d{1,3}(?:" + _SPACE + r"\d{3})+"  # A first group of one to three digits, then groups of exactly three.
_ENDS = r"(?!" + _SPACE + r"?\d)"  # No digit group after it by a space.
_AFTER_LONG = "|".join(r"(?<=(?<![\w.,])(?<!\d" + _SPACE + r")\d{" + str(digits) + "}" + _SPACE + ")"
                       for digits in range(4, 16))  # Lookbehinds have a fixed width: one per token length.
_SPACED = (r"(?:(?<!\d" + _SPACE + r")|" + _AFTER_LONG + ")" + _GROUPS + _ENDS +
           r"(?!-(?!" + _GROUPS + _ENDS + r"(?!-\d))\d)")
SIGNED = re.compile(_LEAD + "(" + _COMMAS + "|" + _SPACED + r"|\d+)" + _TAIL)  # The current reading (econ-calc-0.7).
SIGNED_06 = re.compile(_LEAD + "(" + _COMMAS + "|" + _SPACED_06 + r"|\d+)" + _TAIL)  # econ-calc-0.6, as committed.
SIGNED_COMMAS = re.compile(_LEAD + "(" + _COMMAS + r"|\d+)" + _TAIL)  # Up to econ-calc-0.5: commas only.
READING_OF = {"econ-calc-0.2": SIGNED_COMMAS, "econ-calc-0.3": SIGNED_COMMAS, "econ-calc-0.4": SIGNED_COMMAS,
              "econ-calc-0.5": SIGNED_COMMAS, "econ-calc-0.6": SIGNED_06, "econ-calc-0.7": SIGNED}
_IN_RUN = re.compile(_SPACE + "|-")  # What joins two numbers into one run of digit groups: one space, or a hyphen.
_DASH = re.compile("%?" + _SPACE + "*[" + MINUS + "]" + _SPACE + "*")  # A range's dash, spaced or not.
DECREASE = re.compile(r"\b(fell|falls?|fallen|falling|declin\w*|decreas\w*|drop\w*|down|below|lower|shr[aiu]nk\w*|"
                      r"contract\w*|lost|loses?|losing|cut|cuts|reduc\w*|negative|minus|slump\w*|plung\w*|tumbl\w*)\b",
                      re.IGNORECASE)
INCREASE = re.compile(r"\b(rose|rises?|risen|rising|increas\w*|grew|grows?|grown|growing|up|above|higher|gain\w*|"
                      r"expand\w*|expansion|positive|plus|climb\w*|jump\w*|surg\w*|soar\w*)\b", re.IGNORECASE)
MAX_FIGURES, MAX_CALCULATIONS = 8, 4
LIMITS = {"label": 80, "unit": 30, "period": 60, "quote": 300, "vintage_label": 60, "sign_words": 60}
FORMULA = {"difference": "{a} − {b}", "percent_change": "({a} ÷ {b} − 1) × 100", "share": "{a} ÷ {b} × 100",
           "stock_to_flow": "{a} ÷ {b}", "deflate": "((1 + {a}/100) ÷ (1 + {b}/100) − 1) × 100"}
FIGURE_FIELDS = {"id", "label", "value", "unit", "measure", "period", "basis", "seasonal", "price", "source", "quote",
                 "vintage_label", "sign", "sign_words", "bound", "statistic", "stock_flow"}
BOUND_WORD = {"exact": "", "lower_bound": "at least ", "upper_bound": "at most ", "approximate": "about "}
# A result's bound, for operations that rise with their first input and fall with their second.
BOUND_OF = {("exact", "exact"): "exact", ("lower_bound", "exact"): "lower_bound", ("exact", "lower_bound"): "upper_bound",
            ("upper_bound", "exact"): "upper_bound", ("exact", "upper_bound"): "lower_bound",
            ("lower_bound", "upper_bound"): "lower_bound", ("upper_bound", "lower_bound"): "upper_bound",
            ("approximate", "exact"): "approximate", ("exact", "approximate"): "approximate",
            ("approximate", "approximate"): "approximate"}


def _refuse(detail: str) -> AccountsRefused:
    return AccountsRefused(422, "invalid_brief", detail)


def normalized(text: str) -> str:
    """Text as quotes are matched: NFKC, plain quotes and dashes, one space, case-folded."""
    text = unicodedata.normalize("NFKC", text)
    for plain, fancy in (("'", "‘’‛′"), ('"', "“”„″"), ("-", "‐‑‒–—−")):
        for char in fancy:
            text = text.replace(char, plain)
    return " ".join(text.split()).casefold()


def ungrouped(whole: str) -> str:
    """A matched number's digits without its thousands separators ("350 000" and "350,000" are "350000")."""
    return re.sub("[," + SPACES + "]", "", whole)


def _matches(text: str, pattern: re.Pattern | None = None):
    """(match, magnitude, decimals, sign) for each number of a text; sign None, "+", "-" or "\u00b1". ``pattern``: the
    reading of a calculation version (READING_OF); the current one when None."""
    for match in (pattern or SIGNED).finditer(text):
        margin, mark, whole, part = match.groups()
        sign = "\u00b1" if margin else "+" if mark == "+" else "-" if mark else None
        if sign is None:  # A minus set apart by a space after a word ("was \u2013 5.2"), not between two numbers.
            before = text[:match.start()]
            spaced = before.endswith(" ") and before.rstrip(" ")[-1:] in tuple(MINUS_CHARS)
            prefix = before.rstrip(" ")[:-1]
            if spaced and (prefix == "" or prefix.endswith((" ", "(", ":"))) and not prefix.rstrip(" ")[-1:].isdigit():
                sign = "-"
        yield match, float(ungrouped(whole) + (f".{part}" if part else "")), len(part or ""), sign


def signed_numbers(text: str, pattern: re.Pattern | None = None) -> list[tuple[float, int, str | None]]:
    """The numbers written in a text, each with its sign as written: (value, decimals, sign), sign one of None, "+",
    "-" (any minus sign; the value is negative) and "\u00b1" (a margin, "+/-"). A dash between two numbers, spaced or
    not, is a range, not a sign. ``pattern``: as in _matches."""
    return [(-value if sign == "-" else value, decimals, sign) for _, value, decimals, sign in _matches(text, pattern)]


def numbers(text: str, pattern: re.Pattern | None = None) -> list[tuple[float, int]]:
    """The magnitudes written in a text, with their decimals ("1,221,000" and "1 221 000" are 1221000; "3.1" has one
    decimal). ``pattern``: as in _matches."""
    return [(abs(value), decimals) for value, decimals, _ in signed_numbers(text, pattern)]


def _plain(match: re.Match, digits: tuple[int, int]) -> bool:
    """Digits alone, as many as ``digits`` allows (fewest, most), with no separator or decimal part."""
    whole = match.group(3)
    return whole.isdigit() and match.group(4) is None and digits[0] <= len(whole) <= digits[1]


def _unjoined(text: str, rows: list) -> dict[int, str]:
    """0.7: the numbers (by index in ``rows``, _matches' output) of each run of digit groups, written one space or a
    hyphen apart, that holds two neighbours which could also be one grouped number (one to three digits, a space, then
    exactly three) but were not joined, as a telephone number or "350 000 12" is; each -> its run as written."""
    marked, run = {}, []

    def close() -> None:
        if any(re.fullmatch(_SPACE, text[rows[a][0].end():rows[b][0].start()]) and _plain(rows[a][0], (1, 3)) and
               rows[b][0].start() == rows[b][0].start(3) and _plain(rows[b][0], (3, 3)) for a, b in zip(run, run[1:])):
            written = text[rows[run[0]][0].start(3):rows[run[-1]][0].end()]
            marked.update((index, written) for index in run)

    for index in range(len(rows)):
        if run and _IN_RUN.fullmatch(text[rows[run[-1]][0].end():rows[index][0].start()]):
            run.append(index)
        else:
            close()
            run = [index]
    close()
    return marked


def _range_ends(text: str, rows: list, unjoined: dict[int, str]) -> dict[int, tuple[str, str]]:
    """0.7: the numbers (by index in ``rows``) that end a range written with a dash between two unsigned numbers, spaced
    or not ("350 000-400 000", "3-4%", "350,000 \u2013 400,000"); each -> ("lower" or "upper", the range as written)."""
    ends = {}
    for first, second in zip(range(len(rows)), range(1, len(rows))):
        (a, low, _, a_sign), (b, high, _, b_sign) = rows[first], rows[second]
        if a_sign is None and b_sign is None and low != high and first not in unjoined and second not in unjoined \
                and _DASH.fullmatch(text[a.end():b.start()]):
            written = text[a.start(3):b.end()]
            lower, upper = (first, second) if low < high else (second, first)
            ends.setdefault(lower, ("lower", written))
            ends.setdefault(upper, ("upper", written))
    return ends


def _direction(words: str) -> str | None:
    down, up = bool(DECREASE.search(words)), bool(INCREASE.search(words))
    return "decrease" if down and not up else "increase" if up and not down else None


def _hint(quote: str, rows: list, held: list[int]) -> str | None:
    """The direction the words around the first unsigned number of ``held`` (indexes in ``rows``, _matches' output)
    state, or None (a reading for the guard, never a rule)."""
    for index in held:
        match, _, _, sign = rows[index]
        if sign is None:
            before = " ".join(quote[:match.start()].split()[-5:])
            after = " ".join(quote[match.end():].split()[:5])
            return _direction(f"{before} {after}")
    return None


def _text(value: object, limit: int, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise _refuse(f"{label} is text of 1 to {limit} characters.")
    return " ".join(value.split())


def display(value: float, unit: str, decimals: int, signed: bool = False, bound: str = "exact") -> str:
    """A value as readers see it: its bound, its decimals, thousands separated, a true minus sign, and its unit."""
    rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    text = f"{abs(rounded):,.{decimals}f}"
    sign = "−" if rounded < 0 else "+" if signed and rounded > 0 else ""
    word = BOUND_WORD.get(bound, "")
    if unit == "percent":
        return f"{word}{sign}{text}%"
    if abs(rounded) == 1 and (unit.endswith(" points") or unit in ("months", "quarters", "years")):
        unit = unit[:-1]  # "1 percentage point", "1.00 month".
    return f"{word}{sign}{text} {unit}"


def shown(row: dict) -> str:
    """A stored figure or calculation as readers see it, formatted now from its value (so a version saved before a
    formatting fix reads correctly; its stored display stays as it was recorded)."""
    signed = row.get("op") is not None and row["op"] not in UNSIGNED_OPERATIONS
    return display(row["value"], row["unit"], row["decimals"], signed, row.get("bound", "exact"))


def _sign(row: dict, quote: str, where: str, version: str = CALC_VERSION) -> tuple[int, str]:
    """(the decimals of the quoted number that holds the value, the direction check), or refused. ``version``: the
    calculation version the figure is checked under: its reading of numbers (READING_OF) and, from 0.7, its rules for
    runs of digit groups and for the ends of a range (RUNS_CHECKED)."""
    value = row["value"]
    rows = list(_matches(quote, READING_OF[version]))
    unjoined = _unjoined(quote, rows) if version in RUNS_CHECKED else {}
    held = [index for index, (_, number, _, _) in enumerate(rows) if abs(number - abs(value)) < 1e-9]
    if not held:
        runs = "; ".join(f"“{run}”" for run in dict.fromkeys(unjoined.values()))
        raise _refuse(f"{where}'s quote does not hold its value ({value})" +
                      (f" (it writes digit groups that do not read as one number: {runs})." if runs else "."))
    whole = [index for index in held if index not in unjoined]
    if not whole:
        raise _refuse(f"{where}: its quote writes {value} only inside “{unjoined[held[0]]}”, digit groups that could "
                      "also be read as one number, so no figure is read from them; quote a passage that writes the "
                      "number unambiguously.")
    ends = _range_ends(quote, rows, unjoined) if version in RUNS_CHECKED else {}
    if all(index in ends for index in whole):  # The lower end of a positive value is its lower bound.
        needed = sorted({"lower_bound" if (ends[index][0] == "lower") == (value >= 0) else "upper_bound"
                         for index in whole})
        if row["bound"] not in needed:
            raise _refuse(f"{where}: its quote writes {value} only as an end of the range “{ends[whole[0]][1]}”, so "
                          f"the figure is a bound, never one exact or approximate point: bound {' or '.join(needed)}.")
    found = [(-number if sign == "-" else number, decimals, sign)
             for index, (_, number, decimals, sign) in enumerate(rows) if index in whole]
    if row["sign"] == "as_quoted":
        if row["sign_words"] is not None:
            raise _refuse(f"{where}: a sign as quoted cites no words.")
        same = [(decimals, sign) for number, decimals, sign in found
                if (sign == "±" and value >= 0) or (sign != "±" and abs(number - value) < 1e-9)]
        if not same:
            if any(sign in ("-", "+") for _, _, sign in found):
                stated = next(number for number, _, sign in found if sign in ("-", "+"))
                raise _refuse(f"{where}: the quote states {stated:+g}; a value of {value:g} has the opposite sign.")
            raise _refuse(f"{where}: the quote gives {abs(value):g} without a sign, so a negative value needs sign "
                          "from_words and the words of the quote that state its direction.")
        decimals, sign = same[0]
        if sign is not None or row["measure"] not in ("change", "growth_rate"):
            return decimals, "as_quoted"
        hint = _hint(quote, rows, whole)
        return decimals, "contradicted" if hint == "decrease" and value > 0 else "consistent" if hint else "unstated"
    if row["sign"] != "from_words":
        raise _refuse(f"{where}'s sign is {' or '.join(SIGN_BASES)}.")
    words = _text(row["sign_words"], LIMITS["sign_words"], f"{where}'s sign words")
    if normalized(words) not in normalized(quote):
        raise _refuse(f"{where}'s sign words were not found in its quote.")
    unsigned = [decimals for _, decimals, sign in found if sign is None]
    if not unsigned:
        raise _refuse(f"{where}: the quote states the number's sign itself; use sign as_quoted.")
    direction = _direction(words)
    if (direction == "decrease" and value > 0) or (direction == "increase" and value < 0):
        raise _refuse(f"{where}: the words “{words}” state a {direction}; the value's sign states the opposite "
                      "direction.")
    return unsigned[0], "consistent" if direction else "unclear"


def checked_figures(rows: object, sources: dict[str, dict], version: str = CALC_VERSION) -> list[dict]:
    """The figures in their exact shape, each quoted from its evidence with its direction (``sources``: a reference
    such as ``report:<entry ID>`` or ``context:<item ID>`` -> its text, publisher and publication time); refused
    otherwise. ``version``: the calculation version they are checked under (an earlier one as it was)."""
    measures, kinds = MEASURES_OF[version], STOCK_FLOW_OF[version]
    if not isinstance(rows, list) or len(rows) > MAX_FIGURES:
        raise _refuse(f"figures holds at most {MAX_FIGURES} figures.")
    figures, seen = [], set()
    for index, row in enumerate(rows, start=1):
        where = f"Figure {index}"
        if not isinstance(row, dict) or set(row) != FIGURE_FIELDS:
            raise _refuse(f"{where} has exactly: {', '.join(sorted(FIGURE_FIELDS))}.")
        if not isinstance(row["id"], str) or not FIGURE_ID.fullmatch(row["id"]) or row["id"] in seen:
            raise _refuse(f"{where}'s ID is f1, f2, … and used once.")
        seen.add(row["id"])
        value = row["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise _refuse(f"{where}'s value is a number.")
        if row["measure"] not in measures or row["basis"] not in BASES or row["seasonal"] not in SEASONAL or \
                not isinstance(row["price"], bool):
            raise _refuse(f"{where} names its measure ({', '.join(measures)}), basis ({', '.join(BASES)}), seasonal "
                          f"adjustment ({', '.join(SEASONAL)}) and whether it measures prices.")
        if row["bound"] not in BOUNDS or row["statistic"] not in STATISTICS or row["stock_flow"] not in kinds:
            raise _refuse(f"{where} names its bound ({', '.join(BOUNDS)}), statistic ({', '.join(STATISTICS)}) and "
                          f"stock or flow ({', '.join(kinds)}).")
        if row["measure"] in PERCENT_MEASURES and row["stock_flow"] != "not_applicable":
            raise _refuse(f"{where}: a rate, growth rate, share or net percentage is neither a stock nor a flow.")
        unit = _text(row["unit"], LIMITS["unit"], f"{where}'s unit")
        if (row["measure"] in PERCENT_MEASURES) != (unit == "percent") and \
                not (row["measure"] == "change" and unit in ("percent", "percentage points")):
            raise _refuse(f"{where}: a growth rate, rate, share or net percentage is in percent, and only they (or a "
                          "change of one, in percentage points) are.")
        if row["measure"] == "net_percentage" and row["statistic"] != "other_summary":
            raise _refuse(f"{where}: a net percentage summarises respondents' answers (statistic other_summary).")
        if version != "econ-calc-0.2" and row["measure"] == "share" and \
                not (isinstance(row["value"], (int, float)) and 0 <= row["value"] <= 100):
            raise _refuse(f"{where}: a share lies between 0% and 100%; {row['value']:g}% is none (a survey's balance of "
                          "answers is a net_percentage).")
        if unit == "percentage points" and row["measure"] != "change":
            raise _refuse(f"{where}: percentage points measure a change.")
        source = sources.get(row["source"]) if isinstance(row["source"], str) else None
        if source is None:
            raise _refuse(f"{where} cites evidence this explanation does not hold ({row['source']}).")
        quote = _text(row["quote"], LIMITS["quote"], f"{where}'s quote")
        if normalized(quote) not in normalized(source["text"]):
            raise _refuse(f"{where}'s quote was not found in its evidence.")
        decimals, direction = _sign(row, quote, where, version)
        label = row["vintage_label"]
        if label is not None:
            label = _text(label, LIMITS["vintage_label"], f"{where}'s vintage label")
        figure = {"id": row["id"], "label": _text(row["label"], LIMITS["label"], f"{where}'s label"),
                  "value": value, "decimals": decimals, "unit": unit, "measure": row["measure"],
                  "period": _text(row["period"], LIMITS["period"], f"{where}'s period"), "basis": row["basis"],
                  "seasonal": row["seasonal"], "price": row["price"], "source": row["source"], "quote": quote,
                  "sign": row["sign"], "sign_words": None if row["sign"] == "as_quoted" else " ".join(
                      row["sign_words"].split()), "direction_check": direction, "bound": row["bound"],
                  "statistic": row["statistic"], "stock_flow": row["stock_flow"],
                  "vintage": {"source": source["publisher"], "published": source["published"], "label": label}}
        figure["display"] = display(value, unit, decimals, bound=row["bound"])
        figures.append(figure)
    return figures


def _same(a: dict, b: dict, keys: tuple, what: str) -> None:
    for key, words in (("unit", "units"), ("basis", "nominal or real bases"), ("seasonal", "seasonal adjustments"),
                       ("price", "kinds (prices against quantities)"), ("measure", "measures"),
                       ("statistic", "summary statistics"), ("stock_flow", "stocks and flows")):
        if key in keys and a.get(key) != b.get(key):
            raise _refuse(f"{what} combines figures of different {words}: {a['id']} is {a.get(key)}, {b['id']} is "
                          f"{b.get(key)}.")


ALL = ("unit", "basis", "seasonal", "price", "statistic", "stock_flow")


def _lengths(a: dict, b: dict, op: str, where: str) -> None:
    """econ-calc-0.5: two flows of the same kind combine only if that kind establishes how long they last."""
    if a.get("stock_flow") == b.get("stock_flow") == "flow_other_period":
        needs = ("a share's part and whole are flows over one period" if op == "share" else
                 "two flow totals compare only over the same length of time, whatever dates they cover")
        raise _refuse(f"{where}: {needs}, which their kind establishes (a month, a quarter or a year, or a rate per "
                      f"year). {a['id']} ({a['period']}) and {b['id']} ({b['period']}) are flows over another or an "
                      "unstated period, so their lengths are not established: quote them without this calculation.")


def _result(op: str, a: dict, b: dict, version: str = CALC_VERSION) -> dict:
    where = f"{op} of {a['id']} and {b['id']}"
    checked = version in LENGTH_CHECKED
    if op == "difference":
        _same(a, b, ALL + ("measure",), where)
        if checked:
            _lengths(a, b, op, where)
        unit = "percentage points" if a["unit"] == "percent" else a["unit"]
        return {"value": a["value"] - b["value"], "unit": unit, "measure": "change", "basis": a["basis"],
                "seasonal": a["seasonal"], "decimals": max(a["decimals"], b["decimals"]), "signed": True,
                "period": a["period"] if a["period"] == b["period"] else f"{a['period']} against {b['period']}"}
    if op in ("percent_change", "share", "stock_to_flow") and (a["measure"] != "level" or b["measure"] != "level"):
        raise _refuse(f"{where}: a {op.replace('_', ' ')} is of two levels; growth rates, rates and shares differ in "
                      "percentage points (use a difference).")
    if op == "percent_change":
        _same(a, b, ALL, where)
        if checked:
            _lengths(a, b, op, where)
        if b["value"] <= 0 or a["value"] < 0:
            raise _refuse(f"{where}: a percent change needs a positive base.")
        return {"value": (a["value"] / b["value"] - 1) * 100, "unit": "percent", "measure": "growth_rate",
                "basis": a["basis"], "seasonal": a["seasonal"], "decimals": 1, "signed": True,
                "period": f"{a['period']} against {b['period']}"}
    if op == "share":
        _same(a, b, ALL, where)
        if checked:
            _lengths(a, b, op, where)
        if a["period"] != b["period"]:
            raise _refuse(f"{where}: a share is a part of a whole of the same period.")
        if b["value"] <= 0 or not 0 <= a["value"] <= b["value"]:
            raise _refuse(f"{where}: a share's part lies between zero and its whole.")
        return {"value": a["value"] / b["value"] * 100, "unit": "percent", "measure": "share",
                "basis": "not_applicable", "seasonal": a["seasonal"], "decimals": 1, "signed": False,
                "period": a["period"]}
    if op == "stock_to_flow":
        if a["stock_flow"] == "stock" and b["stock_flow"] == "flow_other_period":  # econ-calc-0.4
            raise _refuse(f"{where}: a stock is read as periods of a flow over a month, quarter or year; {b['id']} is a "
                          "flow over another period, which gives no such unit.")
        if a["stock_flow"] != "stock" or b["stock_flow"] not in PERIODS_OF:
            raise _refuse(f"{where}: a stock is set against a flow over a stated period ({a['id']} must be a stock "
                          f"and {b['id']} a flow).")
        _same(a, b, ("unit", "basis", "seasonal", "price", "statistic"), where)
        if a["period"] != b["period"] or b["value"] <= 0:
            raise _refuse(f"{where}: a stock and the flow it is set against cover the same period, with a positive "
                          "flow.")
        return {"value": a["value"] / b["value"], "unit": PERIODS_OF[b["stock_flow"]], "measure": "stock_to_flow",
                "basis": "not_applicable", "seasonal": a["seasonal"], "decimals": 2, "signed": False,
                "period": a["period"]}
    if not (a["measure"] == b["measure"] == "growth_rate" and a["basis"] == "nominal" and not a["price"] and
            b["price"]):
        raise _refuse(f"{where}: deflating divides a nominal growth rate by a price change (inflation).")
    if a["period"] != b["period"]:
        raise _refuse(f"{where}: the growth rate and the price change cover different periods.")
    if a.get("statistic", "observed") != "observed" or b.get("statistic", "observed") != "observed":
        raise _refuse(f"{where}: summaries of separate survey answers (a mean, a median) do not deflate into the same "
                      "summary of real values; only observed values are deflated.")
    _same(a, b, ("seasonal",), where)
    return {"value": ((1 + a["value"] / 100) / (1 + b["value"] / 100) - 1) * 100, "unit": "percent",
            "measure": "growth_rate", "basis": "real", "seasonal": a["seasonal"], "decimals": 1, "signed": True,
            "period": a["period"]}


def computed(rows: object, figures: dict[str, dict], version: str = CALC_VERSION) -> list[dict]:
    """Each named calculation with its result and bound computed here; refused when its inputs do not compare.
    ``version``: the calculation version they are checked under (an earlier one as it was)."""
    if not isinstance(rows, list) or len(rows) > MAX_CALCULATIONS:
        raise _refuse(f"calculations holds at most {MAX_CALCULATIONS} calculations.")
    done, seen = [], set()
    for index, row in enumerate(rows, start=1):
        where = f"Calculation {index}"
        if not isinstance(row, dict) or set(row) != {"id", "op", "inputs", "label"}:
            raise _refuse(f"{where} has exactly: id, op, inputs, label (its result is computed here).")
        if not isinstance(row["id"], str) or not CALC_ID.fullmatch(row["id"]) or row["id"] in seen:
            raise _refuse(f"{where}'s ID is c1, c2, … and used once.")
        seen.add(row["id"])
        if row["op"] not in OPERATIONS:
            raise _refuse(f"{where}'s operation is one of {', '.join(OPERATIONS)}.")
        inputs = row["inputs"]
        if not isinstance(inputs, list) or len(inputs) != 2 or any(name not in figures for name in inputs):
            raise _refuse(f"{where} names two of this explanation's figures.")
        a, b = (figures[name] for name in inputs)
        if version != "econ-calc-0.2" and "net_percentage" in (a.get("measure"), b.get("measure")):
            raise _refuse(f"{where}: a net percentage is the share of respondents reporting one direction minus the "
                          "share reporting the other; no calculation takes one (what a difference or ratio of such "
                          "balances means is not established here).")
        bound = BOUND_OF.get((a.get("bound", "exact"), b.get("bound", "exact")))
        if bound is None:
            raise _refuse(f"{where}: {a['id']} is {a['bound'].replace('_', ' ')} and {b['id']} is "
                          f"{b['bound'].replace('_', ' ')}; their {row['op'].replace('_', ' ')} has no bound.")
        result = _result(row["op"], a, b, version)
        value = round(result.pop("value"), 6)
        signed = result.pop("signed")
        done.append({"id": row["id"], "label": _text(row["label"], LIMITS["label"], f"{where}'s label"),
                     "op": row["op"], "inputs": list(inputs), "value": value, **result, "bound": bound,
                     "formula": FORMULA[row["op"]].format(a=inputs[0], b=inputs[1]),
                     "display": display(value, result["unit"], result["decimals"], signed, bound),
                     "calc_version": version})
    return done


def displays(figures: dict[str, dict], calculations: list[dict]) -> dict[str, str]:
    return {**{key: shown(row) for key, row in figures.items()}, **{row["id"]: shown(row) for row in calculations}}


def placeholders(text: str) -> list[str]:
    return PLACEHOLDER.findall(text)


# Words a sentence may already put before a bounded value ("up to {f1}"); the value then reads without its own bound
# word, so a text never says "up to at most". The figure keeps its bound, shown with it wherever it stands alone.
STATED_BOUND = {"at most ": ("up to", "at most", "no more than", "less than", "almost", "under", "below"),
                "at least ": ("at least", "more than", "over", "above", "no less than"),
                "about ": ("about", "around", "roughly", "approximately", "nearly", "some")}


def render(text: str, shown_values: dict[str, str]) -> str:
    """A text with each placeholder replaced by its value as computed or quoted, without repeating a bound the sentence
    states just before it."""
    def one(match: re.Match) -> str:
        value = shown_values[match.group(1)]
        before = " " + " ".join(text[:match.start()].lower().split())
        for word, phrases in STATED_BOUND.items():
            if value.startswith(word) and any(before.endswith(" " + phrase) for phrase in phrases):
                return value[len(word):]
        return value
    return PLACEHOLDER.sub(one, text)
