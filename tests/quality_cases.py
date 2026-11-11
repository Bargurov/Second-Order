"""SYNTHETIC research-quality regression cases: two invented sources (an output release and a port authority's monthly
report), and replies with explicit expected findings. Every reply quotes its source exactly, so the existing research
contract accepts it; each planted mistake is named with the rubric findings it must produce, and clean replies must
produce none. Two known misses (a swapped period and an interpretation the statements do not support) record what
lexical checks cannot see; they stay for human review. No case copies a real publication, a private pilot record, a
real reply or a QA case.

The cases marked "0.2" reproduce, on this source, the shapes QA's independent corpus found research-quality-0.1 got
wrong (two false flags on correct replies, and faults with no flag at the fault); "a negation" was 0.1's own known miss.
The cases marked "0.3" reproduce, on the port source, the shapes QA's fresh cases found 0.2 got wrong: a correct date
that the quote's own sentence gives its figure (flagged), a level stated as a change, an added negation and a speaker
taken from another sentence (all missed). "0.3 guard" cases pin that the narrower reading of those checks still flags
a period that belongs to another figure and stays silent on faithful wording. QA's corpora stay in QA's tests and are
not counted here.
"""
HEADLINE = "Synthetic Board releases industrial output estimates"
SOURCE = """October 16, 2026

Synthetic Board releases industrial output estimates

Industrial production rose 0.3 percent in September after declining 0.2 percent in August.

Manufacturing output increased 0.4 percent, and the output of utilities fell 1.1 percent.

Capacity utilization edged up to 77.5 percent in September, a rate that is 2.1 percentage points below its long-run \
average.

The Board judges that conditions in manufacturing remain soft.

The Board expects output growth to moderate in the fourth quarter of 2026."""

PRODUCTION = "Industrial production rose 0.3 percent in September after declining 0.2 percent in August."
UTILITIES = "Manufacturing output increased 0.4 percent, and the output of utilities fell 1.1 percent."
CAPACITY = ("Capacity utilization edged up to 77.5 percent in September, a rate that is 2.1 percentage points below "
            "its long-run average.")
SOFT = "The Board judges that conditions in manufacturing remain soft."
EXPECTS = "The Board expects output growth to moderate in the fourth quarter of 2026."


def statement(text: str, quote: str, basis: str = "data") -> dict:
    return {"statement": text, "basis": basis, "quotes": [quote]}


CLEAN = [statement("Industrial production rose 0.3 percent in September.", PRODUCTION),
         statement("Capacity utilization was 77.5 percent in September.", CAPACITY),
         statement("The Board expects output growth to moderate in the fourth quarter of 2026.", EXPECTS, "forecast")]


def reply(established: list[dict] | None = None, interpretation: str = "Production and utilization both rose in "
          "September, as the release states for each.", missing: list[str] | None = None,
          tests: list[dict] | None = None) -> dict:
    return {"established": established or CLEAN,
            "interpretation": {"kind": "finding", "based_on": [1, 2], "text": interpretation},
            "assumptions": ["The September estimates are not yet revised."],
            "competing_explanations": [{"explanation": "A one-month rebound in utilities.",
                                        "would_distinguish": "The next release's revision of September."}],
            "missing_information": ["The release does not give output by region."] if missing is None else missing,
            "tests": [{"check": "Compare with the next monthly release's revision of September.",
                       "counts_against_if": "The revision reverses the reported increase."}] if tests is None else tests}


def swap(number: int, item: dict) -> list[dict]:
    """CLEAN with established statement `number` (from 1) replaced."""
    return [item if index == number else original for index, original in enumerate(CLEAN, start=1)]


PORT_HEADLINE = "Synthetic Port Authority reports September container traffic"
PORT = """October 9, 2026

Synthetic Port Authority reports September container traffic

The Synthetic Port Authority said container volumes rose by 4,100 units in the month ending September 30, 2026, to \
96,300 units.

Average dwell time fell to 3.2 days in September from 3.6 days in August.

Harbour Master Ana Ruiz said berth delays had shortened in September. Deputy Director Tomas Bell said the authority \
would not expand night shifts before the first quarter of 2027. He said overtime would be reviewed in November.

The authority does not expect the new crane to be operating before December."""

VOLUMES = "container volumes rose by 4,100 units"
LEVEL = "to 96,300 units"
DWELL = "fell to 3.2 days"
DELAYS = "berth delays had shortened in September"
SHIFTS = "the authority would not expand night shifts before the first quarter of 2027"
CRANE = "expect the new crane to be operating before December"  # Its sentence's "does not" is outside the quote.


def port(*established: dict) -> tuple[str, str, dict]:
    """A reply on the port source with these statements; its interpretation cites the first."""
    return PORT_HEADLINE, PORT, {
        "established": list(established),
        "interpretation": {"kind": "finding", "based_on": [1], "text": "Container traffic grew in September, as the "
                                                                       "authority reports."},
        "assumptions": ["The September figures are not yet revised."],
        "competing_explanations": [{"explanation": "Cargo moved from a closed neighbouring port.",
                                    "would_distinguish": "The neighbouring port's reopening month."}],
        "missing_information": ["The authority does not give volumes by vessel type."],
        "tests": [{"check": "The October report's container volumes.", "counts_against_if": "Volumes fall in October."}]}


# name -> (headline, source, reply, expected {(check, where)}, kind)
CASES = {
    "clean": (HEADLINE, SOURCE, reply(), set(), "clean"),
    "clean, assessment attributed": (HEADLINE, SOURCE, reply(swap(2, statement(
        "The Board judges that manufacturing conditions remain soft.", SOFT, "assessment"))), set(), "clean"),
    "clean, statements cited by number": (HEADLINE, SOURCE, reply(interpretation="Statements 1 and 2 show production "
                                                                                  "and utilization rising together."),
        set(), "clean"),
    "clean, an unknown asking why (0.2)": (HEADLINE, SOURCE, reply(missing=[
        "Why industrial production rose in September is not stated."]), set(), "clean"),
    "clean, a short quote within its sentence (0.2)": (HEADLINE, SOURCE, reply(swap(2, statement(
        "Capacity utilization edged up to 77.5 percent in September, below its long-run average.",
        "77.5 percent in September"))), set(), "clean"),
    "a number not in the source": (HEADLINE, SOURCE, reply(swap(1, statement(
        "Industrial production rose 0.5 percent in September.", PRODUCTION))),
        {("number_not_in_source", "established[1]")}, "planted"),
    "a number from elsewhere in the source": (HEADLINE, SOURCE, reply(swap(1, statement(
        "Industrial production rose 0.4 percent in September.", PRODUCTION))),
        {("number_not_in_quotes", "established[1]")}, "planted"),
    "percent for percentage points": (HEADLINE, SOURCE, reply(swap(2, statement(
        "Capacity utilization was 2.1 percent below its long-run average.", CAPACITY))),
        {("unit_differs", "established[2]")}, "planted"),
    "a month from elsewhere in the source": (HEADLINE, SOURCE, reply(swap(1, statement(
        "Industrial production rose 0.3 percent in October.", PRODUCTION))),
        {("period_not_in_quotes", "established[1]")}, "planted"),
    "a month not in the source": (HEADLINE, SOURCE, reply(swap(1, statement(
        "Industrial production rose 0.3 percent in July.", PRODUCTION))),
        {("period_not_in_source", "established[1]")}, "planted"),
    "a forecast labelled as data": (HEADLINE, SOURCE, reply(swap(3, statement(
        "Output growth will moderate in the fourth quarter of 2026.", EXPECTS, "data"))),
        {("basis_mismatch", "established[3]")}, "planted"),
    "a forecast stated as fact": (HEADLINE, SOURCE, reply(swap(3, statement(
        "Output growth moderates in the fourth quarter of 2026.", EXPECTS, "forecast"))),
        {("forecast_unattributed", "established[3]")}, "planted"),
    "an assessment stated as fact": (HEADLINE, SOURCE, reply(swap(2, statement(
        "Conditions in manufacturing remain soft.", SOFT, "assessment"))),
        {("assessment_unattributed", "established[2]")}, "planted"),
    "a cause the quotes do not hold": (HEADLINE, SOURCE, reply(swap(1, statement(
        "Industrial production rose 0.3 percent in September because energy prices fell sharply.", PRODUCTION))),
        {("beyond_quotes", "established[1]")}, "planted"),
    "a direction the quotes do not state (0.2)": (HEADLINE, SOURCE, reply(swap(2, statement(
        "Manufacturing output fell 0.4 percent.", "Manufacturing output increased 0.4 percent"))),
        {("direction_differs", "established[2]")}, "planted"),
    "a negation": (HEADLINE, SOURCE, reply(swap(1, statement(
        "Manufacturing output did not increase.", UTILITIES))), {("direction_differs", "established[1]")}, "planted"),
    "a speaker the source does not name (0.2)": (HEADLINE, SOURCE, reply(swap(1, statement(
        "The central bank reported that industrial production rose 0.3 percent in September.", PRODUCTION))),
        {("speaker_not_in_source", "established[1]")}, "planted"),
    "an interpretation with a new figure": (HEADLINE, SOURCE, reply(interpretation="Production rose about 0.6 percent "
                                                                                   "across the two months."),
        {("interpretation_number_not_in_source", "interpretation")}, "planted"),
    "missing information the source holds": (HEADLINE, SOURCE, reply(missing=[
        "The release does not state the output of utilities."]),
        {("absence_contradicted", "missing_information[1]")}, "planted"),
    "a stated size listed as missing (0.2)": (HEADLINE, SOURCE, reply(missing=[
        "The size of the August change in production is not stated."]),
        {("absence_contradicted", "missing_information[1]")}, "planted"),
    "no unknowns or tests": (HEADLINE, SOURCE, reply(missing=[], tests=[]), {("no_unknowns", "analysis")}, "planted"),
    "a headline instead of a publication": (HEADLINE, HEADLINE, reply([statement(
        "The title names industrial output estimates.", HEADLINE, "action")], interpretation="Only a title is given.",
        missing=["The text of the release is not supplied."]) | {"interpretation": {
            "kind": "no_additional_finding", "based_on": [], "text": "Only a title is given."}},
        {("source_too_short", "source"), ("source_may_be_cut", "source")}, "planted"),
    "a cut-off source": (HEADLINE, SOURCE.rsplit(" to moderate", 1)[0] + " to moder…", reply(CLEAN[:2]),
        {("source_may_be_cut", "source")}, "planted"),
    "an excerpt ending in a link label": (HEADLINE, SOURCE + "\n\nRead more", reply(),
        {("source_may_be_cut", "source")}, "planted"),
    "clean, a date its quote's sentence gives the quoted figure (0.3)": (*port(statement(
        "Container volumes rose by 4,100 units in the month ending September 30, 2026.", VOLUMES)), set(), "clean"),
    "clean, a month its quote's sentence gives the quoted figure (0.3)": (*port(statement(
        "Average dwell time fell to 3.2 days in September.", DWELL)), set(), "clean"),
    "clean, a level kept as a level (0.3 guard)": (*port(statement("Container volumes reached 96,300 units.", LEVEL)),
        set(), "clean"),
    "clean, a negation kept with its speaker (0.3 guard)": (*port(statement(
        "Deputy Director Tomas Bell said the authority would not expand night shifts before the first quarter of "
        "2027.", SHIFTS, "forecast")), set(), "clean"),
    "clean, the speaker its quote's sentence names (0.3 guard)": (*port(statement(
        "Harbour Master Ana Ruiz said berth delays had shortened in September.", DELAYS)), set(), "clean"),
    "clean, a speaker its quote's sentence gives only as a pronoun (0.3 guard)": (*port(statement(
        "Tomas Bell said overtime would be reviewed in November.", "overtime would be reviewed in November",
        "forecast")), set(), "clean"),
    "clean, the publisher for a sentence that names no speaker (0.3 guard)": (*port(statement(
        "The Synthetic Port Authority reported that average dwell time fell to 3.2 days in September.",
        "Average dwell time fell to 3.2 days in September")), set(), "clean"),
    "a level stated as a change (0.3)": (*port(statement("Container volumes rose by 96,300 units.", LEVEL)),
        {("level_change_differs", "established[1]")}, "planted"),
    "a change stated as a level (0.3)": (*port(statement("Container volumes rose to 4,100 units.", VOLUMES)),
        {("level_change_differs", "established[1]")}, "planted"),
    "a month its quote's sentence gives another figure (0.3 guard)": (*port(statement(
        "Average dwell time fell to 3.2 days in August.", DWELL)), {("period_not_in_quotes", "established[1]")},
        "planted"),
    "a negation added (0.3)": (*port(statement(
        "Harbour Master Ana Ruiz said berth delays had not shortened in September.", DELAYS)),
        {("negation_differs", "established[1]")}, "planted"),
    "a negation its quote leaves outside, dropped (0.3)": (*port(statement(
        "The authority expects the new crane to be operating before December.", CRANE, "forecast")),
        {("negation_differs", "established[1]")}, "planted"),
    "a speaker from another sentence (0.3)": (*port(statement(
        "Tomas Bell said berth delays had shortened in September.", DELAYS)),
        {("speaker_differs", "established[1]")}, "planted"),
    # Known misses: wrong, but every word, figure and direction is in the quotes, or the error is an inference.
    # Lexical checks pass them; human review remains.
    "a period swapped within its quote": (HEADLINE, SOURCE, reply(swap(1, statement(
        "Industrial production declined 0.2 percent in September.", PRODUCTION))), set(), "known_miss"),
    "an interpretation the statements do not support": (HEADLINE, SOURCE, reply(
        interpretation="Manufacturing is entering a recession."), set(), "known_miss"),
}

# A reply the existing contract rejects before any rubric: its quote is not in the source.
UNRESOLVED = reply(swap(1, statement("Industrial production rose 0.3 percent in September.",
                                     "Industrial production rose sharply in the third quarter.")))
