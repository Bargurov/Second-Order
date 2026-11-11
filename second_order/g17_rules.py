"""Industry divergence and revision comparisons on verified G.17 extracts (g17-rules-0.1). No I/O.

Rows are identified by their full Table 1 path (section and ancestor rows) and, where the table prints one, their NAICS
code; never by label alone. Broad Manufacturing (which includes other, non-NAICS manufacturing) and Manufacturing (NAICS)
are different rows. Values are the published, seasonally adjusted monthly rates as printed (one decimal), compared with
exact decimal arithmetic; nothing is inferred from index levels and no contribution to a total is computed.

Direction. A printed rate above 0.0 is up and below is down. A printed 0.0 gives no resolvable direction (the unrounded
change may be small either way): it is not treated as exactly zero, and a comparison involving it is "no direction".
A blank is a missing observation and makes the comparison unavailable.

Release-level comparisons (one release, the same reference month for both rows):
- each broad industry group (Manufacturing, Mining, Utilities) against Total IP;
- each NAICS subsector (a coded child of Durable or Nondurable manufacturing) against that parent.
Relation: "opposing" (both directions known and different), "same", "no_direction" (either printed 0.0, with which
side), or "unavailable" (either missing). The gap is row minus parent in percentage points.

Revision comparisons (two releases, the same row path and code, the same reference month): "reversal" (both printed
directions known and opposite), "to_printed_zero" / "from_printed_zero" (one side printed 0.0), "same_direction"
(both known and equal, value changed), "unchanged" (equal printed values) or "unavailable". The revision is the later
printed rate minus the earlier one, in percentage points. These are changes in published estimates, not activity between
release dates.
"""
from decimal import Decimal

from .store import digest

RULES_VERSION = "g17-rules-0.1"
TOTAL = "Total IP"
SECTORS = {"INDUSTRY GROUP / Manufacturing": None, "INDUSTRY GROUP / Mining": "21",
           "INDUSTRY GROUP / Utilities": "2211,2"}
NAICS_MANUFACTURING = ("INDUSTRY GROUP / Manufacturing / Manufacturing (NAICS)", "31-33")
PARENTS = (NAICS_MANUFACTURING[0] + " / Durable manufacturing", NAICS_MANUFACTURING[0] + " / Nondurable manufacturing")
DEFINITIONS = {
    "version": RULES_VERSION,
    "values": "Published seasonally adjusted monthly rates (percent change) as printed in Table 1; exact decimals.",
    "direction": "Above 0.0 up, below 0.0 down; a printed 0.0 has no resolvable direction; a blank is missing.",
    "release_pairs": {"broad groups against the total": {"rows": SECTORS, "parent": TOTAL},
                      "NAICS subsectors against their parent": {"parents": list(PARENTS),
                                                               "children": "coded rows one level below the parent"}},
    "release_relations": ["opposing", "same", "no_direction", "unavailable"],
    "revision_rows": "Total IP and every row of the INDUSTRY GROUP section, matched by path and NAICS code",
    "revision_kinds": ["reversal", "to_printed_zero", "from_printed_zero", "same_direction", "unchanged",
                       "unavailable"],
    "units": "Differences between rates are percentage points.",
}
DEFINITIONS_SHA256 = digest(DEFINITIONS)


class RulesRefused(ValueError):
    pass


def direction(text: str | None) -> int | None:
    """+1 up, -1 down, 0 printed 0.0 (no resolvable direction), None missing."""
    if text is None:
        return None
    value = Decimal(text)
    return 0 if value == 0 else (1 if value > 0 else -1)


def pp(value: Decimal) -> str:
    """A difference between two one-decimal rates, exact at one decimal, as text: 1.2, -0.4, 0.0."""
    text = format(value.quantize(Decimal("0.1")), "f")
    return "0.0" if text == "-0.0" else text


def scope(extract: dict) -> list[dict]:
    """The comparison pairs of one extract, each row and parent identified by path (and code); refused if the hierarchy
    the definitions name is not there."""
    rows = {row["path"]: row for row in extract["rows"]}
    if TOTAL not in rows:
        raise RulesRefused(f"Table 1 has no {TOTAL!r} row")
    pairs = []
    for path, code in SECTORS.items():
        if path not in rows or rows[path]["naics"] != code or rows[path]["depth"] != 0:
            raise RulesRefused(f"Table 1 has no top-level row {path!r} with NAICS {code}")
        pairs.append({"kind": "group_vs_total", "row": path, "parent": TOTAL})
    manufacturing = rows.get(NAICS_MANUFACTURING[0])
    if not manufacturing or manufacturing["naics"] != NAICS_MANUFACTURING[1]:
        raise RulesRefused(f"Table 1 has no {NAICS_MANUFACTURING[0]!r} row coded {NAICS_MANUFACTURING[1]}")
    for parent in PARENTS:
        if parent not in rows or rows[parent]["depth"] != manufacturing["depth"] + 1:
            raise RulesRefused(f"Table 1 has no {parent!r} row under Manufacturing (NAICS)")
        children = [row for row in extract["rows"] if row["path"].startswith(parent + " / ")
                    and row["depth"] == rows[parent]["depth"] + 1]
        if not children or any(not child["naics"] for child in children):
            raise RulesRefused(f"The rows under {parent!r} are missing or not all NAICS-coded")
        codes = [child["naics"] for child in children]
        if len(set(codes)) != len(codes):
            raise RulesRefused(f"Two subsectors under {parent!r} share a NAICS code")
        pairs.extend({"kind": "subsector_vs_parent", "row": child["path"], "parent": parent} for child in children)
    return pairs


def release_comparisons(extract: dict) -> dict:
    """Every pair in every month of one release, as published in that release."""
    rows = {row["path"]: row for row in extract["rows"]}
    out = []
    for month in extract["months"]:
        for pair in scope(extract):
            row, parent = rows[pair["row"]], rows[pair["parent"]]
            a, b = row["rates"][month["key"]], parent["rates"][month["key"]]
            da, db = direction(a), direction(b)
            if da is None or db is None:
                relation, side = "unavailable", "row" if da is None else "parent"
            elif da == 0 or db == 0:
                relation, side = "no_direction", "both" if da == db == 0 else ("row" if da == 0 else "parent")
            else:
                relation, side = ("same" if da == db else "opposing"), None
            out.append({"kind": pair["kind"], "row": pair["row"], "row_naics": row["naics"], "parent": pair["parent"],
                        "month": month["key"], "column": month["column"], "marker": month["marker"],
                        "row_rate": a, "parent_rate": b, "relation": relation, "printed_zero_or_missing": side,
                        "gap_pp": pp(Decimal(a) - Decimal(b)) if a is not None and b is not None else None})
    counts = {name: sum(1 for item in out if item["relation"] == name) for name in DEFINITIONS["release_relations"]}
    return {"release": extract["release"], "comparisons": out, "counts": counts}


def revision_rows(extract: dict) -> list[dict]:
    return [row for row in extract["rows"] if row["path"] == TOTAL or row["section"] == "INDUSTRY GROUP"]


def revision_comparisons(earlier: dict, later: dict) -> dict:
    """The same row (path and code) and reference month in two releases, earlier first."""
    if earlier["release_date"] >= later["release_date"]:
        raise RulesRefused("Revision comparisons need the earlier release first")
    before = {row["path"]: row for row in revision_rows(earlier)}
    after = {row["path"]: row for row in revision_rows(later)}
    months_a = {m["key"]: m for m in earlier["months"]}
    months_b = {m["key"]: m for m in later["months"]}
    shared = [key for key in months_a if key in months_b]
    out, unmatched = [], sorted(set(before) ^ set(after))
    for path, row in before.items():
        other = after.get(path)
        if other is None:
            continue
        if other["naics"] != row["naics"]:
            unmatched.append(path)
            continue
        for key in shared:
            a, b = row["rates"][key], other["rates"][key]
            da, db = direction(a), direction(b)
            if da is None or db is None:
                kind = "unavailable"
            elif Decimal(a) == Decimal(b):
                kind = "unchanged"
            elif da != 0 and db != 0 and da != db:
                kind = "reversal"
            elif da != 0 and db == 0:
                kind = "to_printed_zero"
            elif da == 0 and db != 0:
                kind = "from_printed_zero"
            else:
                kind = "same_direction"
            out.append({"row": path, "naics": row["naics"], "month": key,
                        "earlier": {"rate": a, "marker": months_a[key]["marker"], "column": months_a[key]["column"]},
                        "later": {"rate": b, "marker": months_b[key]["marker"], "column": months_b[key]["column"]},
                        "kind": kind,
                        "revision_pp": pp(Decimal(b) - Decimal(a)) if a is not None and b is not None else None})
    counts = {name: sum(1 for item in out if item["kind"] == name) for name in DEFINITIONS["revision_kinds"]}
    return {"earlier": earlier["release"], "later": later["release"], "months": shared,
            "unmatched_rows": sorted(set(unmatched)), "comparisons": out, "counts": counts}
