"""Who claims what, and on what condition (brief-claims-0.1: story-brief-0.4, econ-explanation-0.5, econ-fidelity-0.5).

The economic-quality audit of 29 October 2026 (data/local-checks/economic-quality-audit-2026-10-29/, and the
preparation in data/local-checks/claims-conditions-preparation-2026-10-29/) found that published briefs lost whose
claim something was and the condition attached to it:

- an interviewer's conditional premise (as in a fictional test interview: "If parliament signs off on the amendment
  this year, might the old notes be pulled from tills as early as 2029?") became the official's own plan in a headline;
- an executive order's conditional duty ("shall, if he determines that it is in the best interests of …, direct the
  Enterprises to establish a pilot program") became "directs", as the White House fact sheet put it;
- a claimed future effect ("Reducing exports by around 45%") and a modelled scenario (in a fictional test speech,
  "could leave as much as 24% of container volume waiting offshore") were typed and shown like observed figures.

Every one of them passed every check, because the record kept what was said but not who said it or how.

From story-brief-0.4 a brief may record its **claims** (at most six, ``k1``, ``k2``, … by position): the statements a
fact, the development or a figure relies on whose holder or force matters. Each records

- ``holder``: whose claim it is (HOLDERS): the publisher's own statement, the speaker of a speech or interview, an
  interviewer's question or premise, the operative text of an order, law or notice itself, survey respondents, or
  another party the material quotes; and ``holder_name``, as the material names it;
- ``modality``: how it is put (MODALITIES): stated as so, conditional, a plan, aim, expectation or scenario, a personal
  view, or a question or premise put to someone;
- ``quote``: the claim's exact words in its ``source`` (``report:<ID>`` or ``context:<ID>``), found there as figure
  quotes are (econ_calc.normalized);
- ``condition``: the exact words of a condition the claim states, inside its quote; required for a conditional claim,
  allowed for a question or a prospective claim, otherwise null.

Facts of a version that records claims cite the claims they rest on (``facts[].claims``), and from econ-explanation-0.5
an explanation's bases may cite ``claim:kN``.

What is checked here, deterministically:

- **K1-K3** (``checked``, ``fact_claims``): the quote is in its source, the condition in the quote, every reference
  resolves, the holder's name is one the evidence names;
- **K7** (``findings``, a publication stop): a number the evidence writes *only* inside the quotes of claims that are
  not stated as so (``claim_only``) never leads a headline when those claims are questions, conditions or views, and
  appears in a fact or an explanation text with a basis only where that text cites one of them (or a figure bound to
  one). A speaker's or publisher's own plan may lead a headline;
- a figure whose quote and a claim's quote, in the same source, contain one another is **bound** to that claim
  (``bindings``), and is shown with what the claim is (``note``): never as an observed outcome when it is a plan, an
  aim or a scenario.

What it cannot establish: that the holder or the modality was recorded rightly (a speaker's line recorded as the
interviewer's, or the reverse, passes every check: the retained text does not mark who speaks); that every condition
was recorded; that prose without numbers keeps a claim's condition, holder, tense or scope (the summary, implications,
uncertainties, missing items and themes cite no claims and are not read by K7); or that a claim is true. A quote found
in its source shows only that the words are there. These remain the model's instructions and an editor's check;
readers are shown the record itself ("Who says what") beside the brief.
"""
from . import econ_calc
from .accounts import AccountsRefused

CLAIMS_VERSION = "brief-claims-0.1"
HOLDERS = {"issuer": "The publisher's own statement",
           "speaker": "The speaker",
           "interviewer": "The interviewer's question or premise",
           "operative_text": "The text of the order, law or notice itself",
           "respondents": "Survey respondents",
           "other_party": "Another party the material quotes"}
MODALITIES = {"asserted": "Stated as so",
              "conditional": "Only if its condition is met",
              "prospective": "A plan, aim, expectation or scenario, not an observed outcome",
              "view": "A personal view",
              "question": "A question or premise put to someone, not their statement"}
NON_ASSERTED = ("conditional", "prospective", "view", "question")
HEADLINE_BARRED = ("conditional", "view", "question")  # A plan may lead a headline; these never do.
CONDITION_ALLOWED = ("conditional", "question", "prospective")
UNREALISED = ("conditional", "prospective", "view")  # Never the basis of something implemented or observed.
LIMITS = {"name": 80, "quote": 400, "condition": 400}
MAX_CLAIMS = 6
FIELDS = ("id", "holder", "holder_name", "modality", "quote", "condition", "source")
CLAIM_ONLY = ("This number is written in the evidence only inside the claims {claims}, which are not stated as so "
              "({modalities}). {where}")
IN_HEADLINE = ("A headline never states as news what is only a question, a condition or a personal view: write it in "
               "a fact that cites the claim, or in the summary with who says it.")
IN_TEXT = ("A text that writes it cites the claim it comes from (a fact's claims, or claim:kN in a basis), so readers "
           "see whose claim it is and how it was put.")


def _refuse(detail: str) -> AccountsRefused:
    return AccountsRefused(422, "invalid_brief", detail)


def _text(value: object, limit: int, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise _refuse(f"{label} is text of 1 to {limit} characters.")
    return " ".join(value.split())


def checked(rows: object, sources: dict[str, dict]) -> list[dict]:
    """A brief's claims in their exact shape, each found in its source (K1), its condition in its quote (K2) and its
    holder named by the evidence; refused otherwise. ``sources``: story_economics.evidence(...)["sources"]."""
    from .story_economics import _named_in  # The company-name test, applied to a holder's name.
    if not isinstance(rows, list) or len(rows) > MAX_CLAIMS:
        raise _refuse(f"claims holds 0 to {MAX_CLAIMS} items.")
    everything = "\n".join(row["text"] for row in sources.values())
    claims = []
    for index, row in enumerate(rows, start=1):
        where = f"Claim k{index}"
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise _refuse(f"{where} has exactly: {', '.join(FIELDS)}.")
        if row["id"] != f"k{index}":
            raise _refuse(f"{where}'s ID is k{index}: claims are numbered k1, k2, … in the order given.")
        if row["holder"] not in HOLDERS or row["modality"] not in MODALITIES:
            raise _refuse(f"{where} names its holder ({', '.join(HOLDERS)}) and modality ({', '.join(MODALITIES)}).")
        name = _text(row["holder_name"], LIMITS["name"], f"{where}'s holder_name")
        quote = _text(row["quote"], LIMITS["quote"], f"{where}'s quote")
        source = sources.get(row["source"]) if isinstance(row["source"], str) else None
        if source is None:
            raise _refuse(f"{where} cites {row['source']!r}, which this brief's evidence does not hold "
                          "(report:<entry ID> or context:<item ID>).")
        if econ_calc.normalized(quote) not in econ_calc.normalized(source["text"]):
            raise _refuse(f"{where}'s quote is not in {row['source']}: a claim quotes its source's exact words.")
        condition = None if row["condition"] is None else _text(row["condition"], LIMITS["condition"],
                                                                  f"{where}'s condition")
        if condition is not None and econ_calc.normalized(condition) not in econ_calc.normalized(quote):
            raise _refuse(f"{where}'s condition is not inside its quote: it is the claim's own words.")
        if row["modality"] == "conditional" and condition is None:
            raise _refuse(f"{where} is conditional, so it gives its condition (the words of the quote that state it).")
        if condition is not None and row["modality"] not in CONDITION_ALLOWED:
            raise _refuse(f"{where} is {row['modality']}: only a conditional, prospective or question claim states a "
                          "condition.")
        if not _named_in(name, everything):
            raise _refuse(f"{where}'s holder_name “{name}” is not named in the evidence.")
        claims.append({"id": row["id"], "holder": row["holder"], "holder_name": name, "modality": row["modality"],
                       "quote": quote, "condition": condition, "source": row["source"]})
    return claims


def fact_claims(value: object, claims: list[dict], where: str) -> list[str]:
    """The claims a fact cites (K3): IDs of this brief's claims, each once."""
    known = {row["id"] for row in claims}
    if not isinstance(value, list) or any(name not in known for name in value) or len(set(value)) != len(value):
        raise _refuse(f"{where} cites only this brief's claims (k1, k2, …), each once.")
    return list(value)


def by_id(claims: list[dict] | None) -> dict[str, dict]:
    return {row["id"]: row for row in claims or []}


def cited(refs: list[str], claims: list[dict] | None, facts: list[dict] | None = None,
          direct: bool = False) -> list[dict]:
    """The claims a basis rests on: those it cites (claim:kN) and, unless ``direct``, those recorded with the facts it
    cites (fact:N), since a fact carries the claim it rests on."""
    found, rows = by_id(claims), {}
    for ref in refs:
        if not isinstance(ref, str):
            continue  # A malformed reference is refused where the basis is checked (story_economics._basis).
        kind, _, name = ref.partition(":")
        if kind == "claim" and name in found:
            rows[name] = found[name]
        elif kind == "fact" and not direct and facts and name.isdigit() and 1 <= int(name) <= len(facts):
            rows.update({cid: found[cid] for cid in facts[int(name) - 1].get("claims") or [] if cid in found})
    return list(rows.values())


def unrealised_only(refs: list[str], claims: list[dict] | None, facts: list[dict] | None) -> bool:
    """Whether a basis rests only on claims that are conditional, planned or someone's view: it cites such claims,
    every fact it cites records one, and it cites no report directly (a report or a fact without a claim states what
    was reported)."""
    refs = [ref for ref in refs if isinstance(ref, str)]
    resting = cited(refs, claims, facts)
    plain = any(ref.startswith("report:") for ref in refs) or any(
        ref.startswith("fact:") and ref[5:].isdigit() and 1 <= int(ref[5:]) <= len(facts or []) and
        not (facts[int(ref[5:]) - 1].get("claims")) for ref in refs)
    return bool(resting) and not plain and all(row["modality"] in UNREALISED for row in resting)


# ---------------------------------------------------------------- figures bound to claims

def bindings(figures: list[dict], claims: list[dict] | None) -> dict[str, list[dict]]:
    """Each figure's non-asserted claims: those whose quote and the figure's, in the same source, contain one
    another."""
    rows = {}
    for row in figures:
        quote = econ_calc.normalized(row.get("quote") or "")
        bound = [claim for claim in claims or [] if claim["modality"] in NON_ASSERTED
                 and claim["source"] == row.get("source") and quote
                 and (quote in econ_calc.normalized(claim["quote"]) or econ_calc.normalized(claim["quote"]) in quote)]
        if bound:
            rows[row["id"]] = bound
    return rows


def note(claim: dict) -> str:
    """What a bound figure is, in the words a reader is shown beside it."""
    if claim["modality"] == "prospective":
        return "a stated expectation, plan or scenario, not an observed outcome"
    if claim["modality"] == "conditional":
        return f"conditional: {claim['condition']}"
    if claim["modality"] == "question":
        return "from a question or premise, not a statement"
    return f"{claim['holder_name']}'s view"


def notes(figures: list[dict], claims: list[dict] | None) -> dict[str, str]:
    """Each bound figure's note (its claims' notes, once each)."""
    return {fid: "; ".join(dict.fromkeys(note(claim) for claim in bound))
            for fid, bound in bindings(figures, claims).items()}


# ---------------------------------------------------------------- K7: numbers that are only someone's claim

def _magnitudes(text: str) -> list[tuple[float, int, str]]:
    """(magnitude, start, the number as written) of each number in a text (a margin is never one)."""
    rows = []
    for match in econ_calc.SIGNED.finditer(text):
        if match.group(1):
            continue
        whole, part = match.group(3), match.group(4)
        written = match.group(0) + ("%" if text[match.end():match.end() + 1] == "%" else "")
        rows.append((round(abs(float(econ_calc.ungrouped(whole) + (f".{part}" if part else ""))), 9), match.start(),
                     written))
    return rows


def claim_only(value: float, sources: dict[str, dict], claims: list[dict] | None) -> list[dict] | None:
    """The non-asserted claims covering every place the evidence writes this magnitude, or None when it writes it
    anywhere else (or nowhere)."""
    covering, seen = {}, False
    for ref, source in sources.items():
        text = econ_calc.normalized(source["text"])
        spans = []
        for claim in claims or []:
            if claim["source"] == ref and claim["modality"] in NON_ASSERTED:
                quote = econ_calc.normalized(claim["quote"])
                start = text.find(quote)
                while start >= 0:
                    spans.append((start, start + len(quote), claim))
                    start = text.find(quote, start + 1)
        for magnitude, at, _ in _magnitudes(text):
            if magnitude != value:
                continue
            seen = True
            inside = [claim for start, end, claim in spans if start <= at < end]
            if not inside:
                return None
            for claim in inside:
                covering[claim["id"]] = claim
    return list(covering.values()) if seen else None


def _basis_places(economics: dict) -> list[tuple[str, str, list[str]]]:
    """An explanation's texts that rest on a basis, with it: what changed, why it matters, each channel's texts, each
    second-order effect's and each alternative's."""
    places = [("change", economics["change"]["text"], economics["change"]["basis"]),
              ("significance", economics["significance"]["text"], economics["significance"]["basis"])]
    for index, row in enumerate(economics["channels"]):
        texts = [(f"channels[{index}]", row["text"])]
        texts += [(f"channels[{index}].steps[{n}]", step) for n, step in enumerate(row["steps"])]
        texts += [(f"channels[{index}].affected[{n}].how", party["how"]) for n, party in enumerate(row["affected"])]
        texts += [(f"channels[{index}].conditions", row["conditions"])] if row["conditions"] else []
        places += [(where, text, row["basis"]) for where, text in texts]
    for index, row in enumerate(economics["second_order"]):
        places += [(f"second_order[{index}]", row["text"], row["basis"]),
                   (f"second_order[{index}].conditions", row["conditions"], row["basis"])]
    places += [(f"alternatives[{index}]", row["text"], row["basis"])
               for index, row in enumerate(economics["alternatives"])]
    return places


def _finding(where: str, matched: str, claims: list[dict], detail: str) -> dict:
    return {"where": where, "rule": "claim_only_number", "matched": matched,
            "detail": CLAIM_ONLY.format(claims=", ".join(row["id"] for row in claims),
                                        modalities=", ".join(dict.fromkeys(row["modality"] for row in claims)),
                                        where=detail)}


def findings(content: dict, sources: dict[str, dict]) -> list[dict]:
    """K7, publication stops for a version that records claims (none for one that records none)."""
    claims = content.get("claims")
    if not claims:
        return []
    rows = []
    numbers = lambda text: [(value, written) for value, _, written in _magnitudes(text)]  # noqa: E731
    for value, written in numbers(econ_calc.PLACEHOLDER.sub(" ", content["headline"])):
        covering = claim_only(value, sources, claims)
        if covering and all(row["modality"] in HEADLINE_BARRED for row in covering):
            rows.append(_finding("headline", written, covering, IN_HEADLINE))
    for index, fact in enumerate(content["facts"]):
        for value, written in numbers(fact["text"]):
            covering = claim_only(value, sources, claims)
            if covering and not set(fact.get("claims") or []) & {row["id"] for row in covering}:
                rows.append(_finding(f"facts[{index}]", written, covering, IN_TEXT))
    economics = content.get("economics")
    if not economics or economics.get("status") != "explained":
        return rows
    bound = bindings(economics["figures"], claims)
    for where, text, basis in _basis_places(economics):
        cites = {row["id"] for row in cited(basis, claims, content["facts"])}
        for name in econ_calc.placeholders(text):
            if name in bound and not (cites & {row["id"] for row in bound[name]} or f"figure:{name}" in basis):
                rows.append(_finding(f"economics.{where}", "{" + name + "}", bound[name], IN_TEXT))
        for value, written in numbers(econ_calc.PLACEHOLDER.sub(" ", text)):
            covering = claim_only(value, sources, claims)
            if not covering:
                continue
            ids = {row["id"] for row in covering}
            through = any(f"figure:{fid}" in basis and ids & {row["id"] for row in claims_of}
                          for fid, claims_of in bound.items())
            if not (cites & ids or through):
                rows.append(_finding(f"economics.{where}", written, covering, IN_TEXT))
    return rows


# ---------------------------------------------------------------- what readers see

def reader_view(content: dict, material: dict) -> dict | None:
    """'Who says what': every claim a version records, with its holder, how it was put, its condition, its exact words
    and its source, and the facts that cite it. None for a version that records no claims (story-brief-0.3 and
    earlier, or one that recorded none), so its page is shown exactly as before."""
    claims = content.get("claims")
    if claims is None:
        return None
    links = {row["entry_id"]: row.get("link") for row in material.get("reports", [])}
    rows = []
    for claim in claims:
        kind, _, name = claim["source"].partition(":")
        rows.append({**claim, "holder_label": HOLDERS[claim["holder"]],
                     "modality_label": MODALITIES[claim["modality"]],
                     "reports": [name] if kind == "report" else [],
                     "link": links.get(name) if kind == "report" else None,
                     "facts": [index + 1 for index, fact in enumerate(content["facts"])
                               if claim["id"] in (fact.get("claims") or [])]})
    return {"claims_version": CLAIMS_VERSION, "claims": rows,
            "statement": ("Who says what, as recorded with this brief: each claim's exact words in its source, whose "
                          "they are and how they were put. A quote found in its source shows that the words are there, "
                          "not that the claim is true.")}
