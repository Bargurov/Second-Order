"""Bagdad's later company statement for the copper tools, read from the verified FCX research package.

The copper tools' project table shows Bagdad twice: the earlier statement from the fiscal 2025 10-K, whose figures stay
in the copper inputs catalogue, and the company's later statement on the board's approval, whose records this
module reads from research/fcx through company_research_view.resolved(), the same read the FCX page uses: each
retained document is checked against its acquisition record on every read. Nothing is copied into the catalogue, so
its digest, and every saved scenario record bound to it, stays as it was.

FIGURES and PASSAGES are the fixed table of what the current row uses. Numeric records have a value, its printed figure,
a unit code of the copper tools and a page; passages have quoted words only (the start of production stays a passage,
never a value). The block is all or nothing: if a document it rests on is not verified, a table entry is not as listed
here (a capital or capacity that is not positive included), or the FCX package cannot be read at all, every entry is
withheld with one reason, and the copper tools still serve everything else. Only that read is guarded here; nothing else
is wrapped.

Every number, date and quote comes from the records and the sources' metadata at read time; none is written here.
Nothing here writes, fetches or calls a model.
"""
from decimal import Decimal
from pathlib import Path

from . import company_research_view as crv

# Record id -> (role, the FCX unit as committed, the copper tools' unit code, source id, page, stated as approximate).
FIGURES = {
    "nr-bagdad-capex-estimate": ("capital", "USD billions", "usd_billion", "news-2026-11-04", 2, True),
    "nr-bagdad-cu-increment": ("capacity", "million pounds per year", "mlb_per_year", "news-2026-11-04", 2, True),
    "nr-bagdad-breakeven-cu": ("break_even", "USD per pound", "usd_per_lb", "news-2026-11-04", 2, True),
    "nr-bagdad-breakeven-mo": ("break_even_condition", "USD per pound", "usd_per_lb", "news-2026-11-04", 2, False),
    "nr-bagdad-construction-years": ("construction", "years", "years", "news-2026-11-04", 2, True),
}
# Passage id -> (role, source id, page).
PASSAGES = {
    "nr-p-board-approval": ("decision", "news-2026-11-04", 1),
    "q3-p-bagdad-approval": ("decision", "10q-2026q3", 23),
    "nr-p-schedule": ("start", "news-2026-11-04", 2),
    "nr-p-cost-risk": ("caveat", "news-2026-11-04", 2),
    "nr-p-estimates-change": ("caveat", "news-2026-11-04", 3),
}
SOURCE_IDS = tuple(dict.fromkeys([item[3] for item in FIGURES.values()] + [item[1] for item in PASSAGES.values()]))
SOURCE_FIELDS = ("id", "title", "form", "date", "date_kind", "state")
# Besides CompanyRefused, at the FCX read only: a malformed record anywhere in the package (a missing field, inputs
# that are a list) must not take the copper tools down.
PACKAGE_ERRORS = (OSError, KeyError, ValueError, TypeError, AttributeError)


def _table(rid: str, field: str) -> str:
    return f"Not shown: {rid} is not as the copper tools expect ({field})"


def table_problems(records: dict, passages: dict) -> list[str]:
    """Each table entry that is missing or differs in kind, unit, source or page. Works on withheld records, which
    keep these identifying fields."""
    problems = []
    for rid, (_, unit, _, source, page, _) in FIGURES.items():
        record = records.get(rid)
        if record is None:
            problems.append(_table(rid, "missing"))
            continue
        wrong = next((field for field, want in (("kind", "published"), ("unit", unit), ("source", source),
                                                 ("page", page)) if record.get(field) != want), None)
        if wrong:
            problems.append(_table(rid, wrong))
    for pid, (_, source, page) in PASSAGES.items():
        passage = passages.get(pid)
        if passage is None:
            problems.append(_table(pid, "missing"))
            continue
        wrong = next((field for field, want in (("source", source), ("page", page)) if passage.get(field) != want),
                     None)
        if wrong:
            problems.append(_table(pid, wrong))
    return problems


def _entries(records: dict | None = None, passages: dict | None = None) -> dict:
    """Every table entry; with records and passages given, available entries carry their value, printed figure and
    quote, otherwise all of them are withheld."""
    out = {}
    for rid, (role, _, code, source, page, approximate) in FIGURES.items():
        record = (records or {}).get(rid)
        out[rid] = {"id": rid, "kind": "figure", "role": role, "state": "available" if record else "withheld",
                    "value": record["value"] if record else None, "display": record["display"] if record else None,
                    "unit": code, "approximate": approximate, "source": source, "page": page,
                    "quote": record["quote"] if record else None, "problem": None}
    for pid, (role, source, page) in PASSAGES.items():
        passage = (passages or {}).get(pid)
        out[pid] = {"id": pid, "kind": "passage", "role": role, "state": "available" if passage else "withheld",
                    "value": None, "display": None, "unit": None, "approximate": False, "source": source,
                    "page": page, "quote": passage["quote"] if passage else None, "problem": None}
    return out


def _withheld(problem: str, sources: dict) -> dict:
    entries = _entries()
    for entry in entries.values():
        entry["problem"] = problem
    return {"state": "withheld", "problem": problem, "sources": sources, "records": entries}


def linked(research: Path, sources_root: Path) -> dict:
    """{"state", "problem", "sources", "records"}: the current Bagdad statement, all available or all withheld."""
    try:
        sources, records, passages = crv.resolved(research, sources_root)
        problems = table_problems(records, passages)
        shown = {sid: {field: sources[sid].get(field) for field in SOURCE_FIELDS} for sid in SOURCE_IDS
                 if sid in sources}
        if problems:
            return _withheld(problems[0], shown)
        unverified = [sid for sid in SOURCE_IDS if sources[sid]["state"] != "verified"]
        if unverified:
            sid = unverified[0]
            return _withheld(f"Not shown: {crv.SHORT_NAMES[sid]} is {sources[sid]['state']}", shown)
        not_shown = [rid for rid in FIGURES if records[rid]["state"] != "available"]
        not_shown += [pid for pid in PASSAGES if passages[pid]["state"] != "available"]
        if not_shown:
            return _withheld(_table(not_shown[0], "state"), shown)
        # The producers divide by the capital and the capacity: one that is not positive is a fault of the package.
        not_positive = [rid for rid, item in FIGURES.items()
                        if item[0] in ("capital", "capacity") and Decimal(records[rid]["value"]) <= 0]
        if not_positive:
            return _withheld(_table(not_positive[0], "value"), shown)
        return {"state": "available", "problem": None, "sources": shown,
                "records": _entries({rid: records[rid] for rid in FIGURES}, {pid: passages[pid] for pid in PASSAGES})}
    except crv.CompanyRefused as exc:
        return _withheld(f"Not shown: the FCX research package cannot be read ({exc.status})", {})
    except PACKAGE_ERRORS as exc:
        return _withheld(f"Not shown: the FCX research package cannot be read ({type(exc).__name__})", {})


def linked_values(block: dict) -> dict[str, Decimal]:
    """The available figures' exact values, for the producers' computations; empty when the block is withheld."""
    if block["state"] != "available":
        return {}
    return {rid: Decimal(entry["value"]) for rid, entry in block["records"].items()
            if entry["kind"] == "figure" and entry["value"] is not None}
