"""Economic framework notes (econ-framework-0.2): a small, sourced set of general mechanisms an explanation may name.

A note says how a kind of development usually works through an economy (a tariff's pass-through, monetary policy's
transmission, an electricity shortage's effect on firms), for which kinds of instrument it applies and where it does
not, with the sources it rests on. A note is general reasoning, never evidence about a particular event: it holds no
current figure, and an explanation cites it only as the mechanism of a channel, apart from the event's facts, figures
and context. A channel may name a note only when the note applies to the story's instrument, so a domestic service's
price is never explained through an import tariff's mechanism.

The notes live in econ_framework.json, versioned with their SHA-256; they were written with an AI assistant from the
sources they cite and have not been reviewed by an economist or an editor, and readers are told so.

History (0.2, reproduced 2026-10-26: an explanation saved under one wording of a note was shown with the note's later
wording and stayed "ready"). An explanation now keeps a ``snapshot`` of the exact notes it used, with their sources and
digests, so a later change to a note never changes what an earlier explanation says; its currentness is judged against
the notes it used (``changed``), not against unrelated ones. Every framework version that explanations were prepared
with is kept in econ_framework_archive/<SHA-256>.json, and ``archived`` returns one only when its content still has the
recorded SHA-256, so an explanation saved before snapshots existed is read with the notes it was prepared with, or is
said to be unrecoverable, never shown with today's notes.

0.3 (2026-10-28, docs/news-econ-form-subject-2026-10-28.md (private; not in the public repository)). A development was
classified by one ``instrument`` that mixed how its evidence was produced (``official_statistic``) with what it
describes (credit conditions, prices), so a bank lending survey and a survey of firms' access to finance were offered
the same notes. A note now states three things its reasoning assumes: the subjects it applies to (``applies_to``, from
SUBJECTS, or ``any`` for a note about the form of evidence itself), the forms of evidence it rests on (``forms``) and,
for a survey, whose answers it describes (``respondents``). It applies only where all three match (econ_classification).
The earlier notes' reasoning is unchanged; a note is added for the bank lending survey. ``changed`` compares what
readers read of a note (its title, scope, mechanism, limits and sources); whether a note still applies to an earlier
explanation is decided by econ_classification's explicit compatibility rule. Frameworks before 0.3 are read in their own
shape (INSTRUMENTS, no forms).
"""
from functools import lru_cache
import json
from pathlib import Path

from . import newsroom_store as ns

FRAMEWORK_VERSION = "econ-framework-0.3"
LEGACY_VERSIONS = ("econ-framework-0.1", "econ-framework-0.2")  # Notes apply to INSTRUMENTS; no forms or respondents.
# The framework an analysis version was last checked against, for one that is no longer current.
FRAMEWORK_OF = {"econ-explanation-0.3": "a2646115201c7e5afb24435a1c101cc38cd3f2cccbf2b304de13557489fe4c15",
                # econ-framework-0.3, unchanged when econ-explanation-0.5 and then 0.6 became current (29 October 2026).
                "econ-explanation-0.4": "b8029a9db8167c1b3a91743160b2d1b94e1f066529b31d56604b3a818d4f6c63",
                "econ-explanation-0.5": "b8029a9db8167c1b3a91743160b2d1b94e1f066529b31d56604b3a818d4f6c63"}
PATH = Path(__file__).with_name("econ_framework.json")
ARCHIVE = Path(__file__).with_name("econ_framework_archive")
# What a development changes, as an explanation up to econ-explanation-0.3 classified it: one value for both the form of
# its evidence (an official statistic) and its subject. Kept to read those explanations and their frameworks.
INSTRUMENTS = {
    "import_tariff": "a tariff or duty on imports",
    "trade_remedy": "a trade-remedy or safeguard step",
    "trade_flow": "a change in trade flows or trade routes",
    "domestic_price": "a price charged for domestic goods or services",
    "tax_or_subsidy": "a tax or a subsidy",
    "monetary_policy": "monetary policy",
    "financial_conditions": "credit or financing conditions",
    "competition_enforcement": "competition enforcement",
    "consumer_regulation": "consumer or platform regulation",
    "labor_enforcement": "labour-standards enforcement",
    "fiscal_spending": "public spending or transfers",
    "official_statistic": "an official statistic",
    "energy_supply": "energy supply",
    "industrial_policy": "industrial or security policy",
    "other": "another kind of development",
}
# econ-explanation-0.4: what a development changes or describes (its subject), apart from the form of its evidence.
# An official statistic is a form; what it measures is its subject.
SUBJECTS = {**{name: label for name, label in INSTRUMENTS.items() if name not in ("official_statistic", "other")},
            "economic_activity": "output, sales, orders or inventories",
            "labour_market": "employment, hours or wages",
            "housing": "housing sales, construction or house prices",
            "inflation": "inflation or the general price level",
            "other": "another kind of development"}
FORMS = {"reported_observation": "a reported observation or measurement",
         "survey_answers": "respondents' answers in a survey",
         "forecast_or_scenario": "a forecast, projection or scenario",
         "announcement_or_decision": "an announced or adopted decision, proposal or measure",
         "statement": "a statement of views or arguments",
         "unclear": "evidence of an unclear form"}
RESPONDENTS = {"banks": "banks", "firms": "firms", "households": "households or individuals",
               "other": "other respondents", "not_stated": "respondents not stated"}
NOTE_RESPONDENTS = ("banks", "firms", "households")  # A note describes the answers of a named population.
ANY = "any"  # A note about the form of evidence itself, whatever it measures.
SCOPES = ("macro", "micro", "both")
LEGACY_NOTE_FIELDS = {"id", "title", "scope", "applies_to", "mechanism", "limits", "sources"}
NOTE_FIELDS = LEGACY_NOTE_FIELDS | {"forms", "respondents"}
READ_FIELDS = ("title", "scope", "mechanism", "limits", "sources")  # What readers read of a note.
SOURCE_FIELDS = {"title", "publisher", "year", "url"}


class FrameworkProblem(ValueError):
    pass


def _applicability(note: dict) -> None:
    """econ-framework-0.3: the subjects, forms and respondents a note's reasoning assumes."""
    if not note["applies_to"] or any(row not in SUBJECTS and row != ANY for row in note["applies_to"]) or \
            (ANY in note["applies_to"] and len(note["applies_to"]) > 1):
        raise FrameworkProblem(f"Note {note['id']} applies to known subjects (or to {ANY} subject alone).")
    if not isinstance(note["forms"], list) or not note["forms"] or \
            any(row not in FORMS or row == "unclear" for row in note["forms"]):
        raise FrameworkProblem(f"Note {note['id']} rests on known forms of evidence (never an unclear one).")
    survey = "survey_answers" in note["forms"]
    if not isinstance(note["respondents"], list) or bool(note["respondents"]) != survey or \
            any(row not in NOTE_RESPONDENTS for row in note["respondents"]):
        raise FrameworkProblem(f"Note {note['id']} names the respondents whose answers it describes "
                               f"({', '.join(NOTE_RESPONDENTS)}) exactly when it rests on survey answers.")


def checked(value: object, version: str | None = FRAMEWORK_VERSION) -> dict:
    """The notes file in its exact shape: every note sourced, applying to known subjects, forms and respondents (to
    known instruments, for a framework before 0.3); raises otherwise. ``version``: the version it must have (None: any
    econ-framework version, for an archived one)."""
    if not isinstance(value, dict) or not isinstance(value.get("notes"), list) or \
            not isinstance(value.get("statement"), str) or \
            not str(value.get("framework_version", "")).startswith("econ-framework-") or \
            (version is not None and value["framework_version"] != version):
        raise FrameworkProblem(f"The framework file is {{framework_version: {version or 'econ-framework-…'}, "
                               "statement, notes}.")
    legacy = value["framework_version"] in LEGACY_VERSIONS
    fields = LEGACY_NOTE_FIELDS if legacy else NOTE_FIELDS
    notes = {}
    for note in value["notes"]:
        if not isinstance(note, dict) or set(note) != fields or note["scope"] not in SCOPES or \
                not isinstance(note["id"], str) or note["id"] in notes:
            raise FrameworkProblem(f"A note has exactly {sorted(fields)}, a known scope and a unique ID.")
        if legacy and (not note["applies_to"] or any(row not in INSTRUMENTS for row in note["applies_to"])):
            raise FrameworkProblem(f"Note {note['id']} applies to known instruments.")
        if not legacy:
            _applicability(note)
        if not note["sources"] or not all(isinstance(row, dict) and set(row) == SOURCE_FIELDS and
                                          str(row["url"]).startswith("https://") for row in note["sources"]):
            raise FrameworkProblem(f"Note {note['id']} cites at least one source with an https address.")
        if any(char.isdigit() for char in note["mechanism"]):
            raise FrameworkProblem(f"Note {note['id']} is general reasoning and holds no figure.")
        notes[note["id"]] = note
    return {"framework_version": value["framework_version"], "framework_sha256": ns.sha256_of(value),
            "statement": value["statement"], "notes": notes}


@lru_cache(maxsize=1)
def framework() -> dict:
    return checked(json.loads(PATH.read_text(encoding="utf-8")))


def for_analysis(version: str) -> dict:
    """The framework an analysis version is checked against: today's for the current one; for an earlier one, the
    archived framework it was last checked against (FRAMEWORK_OF)."""
    sha = FRAMEWORK_OF.get(version)
    found = archived(sha) if sha else framework()
    if found is None:
        raise FrameworkProblem(f"The framework of {version} cannot be recovered.")
    return found


def summary() -> dict:
    found = framework()
    return {"framework_version": found["framework_version"], "framework_sha256": found["framework_sha256"]}


def note_digest(note: dict) -> str:
    return ns.sha256_of(note)


def snapshot(note_ids: list[str], found: dict | None = None) -> dict:
    """The exact notes an explanation uses, with their sources and digests, and the framework they came from."""
    found = found or framework()
    notes = {name: found["notes"][name] for name in dict.fromkeys(note_ids) if name in found["notes"]}
    return {"framework_version": found["framework_version"], "framework_sha256": found["framework_sha256"],
            "statement": found["statement"], "notes": notes,
            "digests": {name: note_digest(note) for name, note in notes.items()}}


def archived(sha256: str | None) -> dict | None:
    """The framework version with this SHA-256, from the archive (or the current file) only when its content still
    has that SHA-256; None when it cannot be recovered."""
    if not isinstance(sha256, str) or len(sha256) != 64 or not all(char in "0123456789abcdef" for char in sha256):
        return None
    current = framework()
    if current["framework_sha256"] == sha256:
        return current
    path = ARCHIVE / f"{sha256}.json"
    try:
        found = checked(json.loads(path.read_text(encoding="utf-8")), version=None)
    except (OSError, ValueError):
        return None
    return found if found["framework_sha256"] == sha256 else None


def read_digest(note: dict) -> str:
    """What readers read of a note (its title, scope, mechanism, limits and sources), as one digest."""
    return ns.sha256_of({field: note[field] for field in READ_FIELDS})


def changed(snapshot_notes: dict, found: dict | None = None) -> list[dict]:
    """The notes an explanation used that the current framework has revised (in what readers read of them) or
    removed. Where a note applies is econ_classification's question, not this one."""
    found = found or framework()
    rows = []
    for name, note in snapshot_notes.items():
        now = found["notes"].get(name)
        if now is None:
            rows.append({"note": name, "title": note["title"], "change": "removed"})
        elif read_digest(now) != read_digest(note):
            rows.append({"note": name, "title": note["title"], "change": "revised"})
    return rows
