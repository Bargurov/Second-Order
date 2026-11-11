"""Match every record and passage resting on the three re-sourced FCX documents against their SEC EDGAR copies.

The 10-Q (10q-2026q3), the results release (release-2026q3) and the Bagdad release (news-2026-11-04) were first read
from investor-relations PDFs; their SEC EDGAR copies are retained under approval fcx-sec-docs-02. This compares two
states of facts.json: BEFORE (the file as it stood on the investor-relations PDFs, given as the first argument) and
AFTER (research/fcx/facts.json now). Each published record and passage of the three documents gets one class:

- exact: the BEFORE quote occurs on the SEC page (after whitespace normalization) and AFTER keeps it;
- typography: it occurs there only when quotes, dashes, minus signs and spaces are ignored, and AFTER holds the SEC
  page's own wording at that place, verbatim;
- relaid: it does not occur even then, and the AFTER quote occurs on the SEC page holding the same row label and
  printed figure;
- not_found: anything else, or any check below failing.

Checks on every item:
- the AFTER quote occurs on its AFTER page of the SEC copy;
- a printed figure sits in that quote as a whole figure (not inside a longer number), so it is on that page;
- the SEC page prints the item's printed page (at its foot; at its head for the Bagdad release), or prints none
  where the item has none;
- the earlier PDF page and the SEC page hold the same words and figures in the same order, apart from LAYOUT tokens,
  so every heading, unit line ("(In millions...)"), column label and row label of the old page is on the new one;
- what defines an item (metric, unit, basis, period, row, column, value, printed figure; a passage's topic) is the
  same in BEFORE and AFTER.

An item whose page moved is reported for review (not_found) rather than compared against another page.

Reads local files only (the SEC copies, and the PDFs through source_text.ir_pdf_pages, for comparison only). Prints
the counts; with --write it also writes research/fcx/sec-match.json. Exit status 0 means no item is not_found.

Run: python -I research/fcx/tools/sec_match.py <facts.json as it stood on the PDFs> [--write]
"""
import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_text  # noqa: E402

FOLDER = Path(__file__).resolve().parents[1]
DOCUMENTS = ("10q-2026q3", "release-2026q3", "news-2026-11-04")
DEFINING = ("metric", "unit", "basis", "period", "row", "column", "kind", "value", "display", "topic")
FOLD = str.maketrans({chr(c): "'" for c in (0x2018, 0x2019)} | {chr(c): '"' for c in (0x201C, 0x201D)}
                     | {chr(c): "-" for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212)} | {chr(0xA0): " "})
TOKEN = re.compile(r"[A-Za-z]+|\d+(?:[.,]\d+)*|[^\sA-Za-z\d]")
# Tokens one copy has and the other lacks without any change of wording: the 10-Q's running "Table of Contents" link
# (top of each SEC page, foot of each PDF page), and the EDGAR envelope and file title before page 1 of the SEC copies.
LAYOUT = {
    "10q-2026q3": [r"^Table of Contents ", r" Table of Contents(?= \S+$)", r"^fcx-20260930 "],
    "release-2026q3": [r"^EX-99\.1 2 a3q2026exhibit991\.htm EX-99\.1 Document "],
    "news-2026-11-04": [r"^EX-99\.1 2 fcx_261104\.htm EX-99\.1 fcx_261104 "],
}
PRINTED_AT_HEAD = {"news-2026-11-04"}


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text)


def without_layout(source: str, text: str) -> str:
    for pattern in LAYOUT[source]:
        text = re.sub(pattern, " ", text).strip()
    return text


def printed_page(source: str, text: str) -> str | None:
    """The page number the SEC page prints: its last token, or for the Bagdad release its first after the file's
    envelope and document tag."""
    text = without_layout(source, text)
    if source in PRINTED_AT_HEAD:
        match = re.match(r"(?:\{N\d+\.\d+\} )?(\d+) ", text)
    else:
        match = re.search(r" (\d+|[IVXL]+|S-\d+)$", text)
    return match.group(1) if match else None


def folded_find(quote: str, page: str) -> str | None:
    """The page's own text at the place where ``quote`` occurs once quotes, dashes, minus signs and spaces are
    ignored; None when it does not occur so."""
    keep = [i for i, ch in enumerate(page) if not ch.isspace()]
    flat = "".join(page[i] for i in keep).translate(FOLD)
    wanted = re.sub(r"\s+", "", quote).translate(FOLD)
    at = flat.find(wanted) if wanted else -1
    if at < 0:
        return None
    return page[keep[at]:keep[at + len(wanted) - 1] + 1]


def whole_figure(display: str, quote: str) -> bool:
    return re.search(r"(?<![\d.,])" + re.escape(display) + r"(?![\d]|[.,]\d)", quote) is not None


def differences(old: str, new: str) -> str:
    """Where two quotes differ, as 'old' -> 'new' pieces with a little context."""
    pieces = []
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            a, b = max(0, i1 - 8), max(0, j1 - 8)
            pieces.append(f"{old[a:i2 + 8]!r} -> {new[b:j2 + 8]!r}")
    return "; ".join(pieces)


def page_agreement(source: str, old: str, new: str) -> tuple[bool, str]:
    """Whether the PDF page and the SEC page hold the same words and figures in the same order, apart from layout."""
    a, b = tokens(without_layout(source, old)), tokens(without_layout(source, new))
    if a == b:
        return True, "same words and figures in the same order as the PDF page"
    ops = [(tag, " ".join(a[i1:i2]), " ".join(b[j1:j2]))
           for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
           if tag != "equal"]
    if all(tag == "replace" and x.replace(" ", "") == y.replace(" ", "") for tag, x, y in ops):
        return True, ("same words and figures in the same order as the PDF page, whose text splits "
                      + ", ".join(f"'{y}' as '{x}'" for _, x, y in ops))
    return False, "differs: " + "; ".join(f"{tag} {x!r} -> {y!r}" for tag, x, y in ops[:6])


def items(facts: dict) -> list[dict]:
    return [dict(r, item="record") for r in facts["records"] if r.get("source") in DOCUMENTS] + \
           [dict(p, item="passage") for p in facts["passages"] if p["source"] in DOCUMENTS]


def match(before: dict, after: dict) -> list[dict]:
    sec = {sid: source_text.sec_pages(sid) for sid in DOCUMENTS}
    pdf = {sid: source_text.ir_pdf_pages(sid) for sid in DOCUMENTS}
    later = {item["id"]: item for item in items(after)}
    agreement = {}
    out = []
    for old in items(before):
        rid, sid = old["id"], old["source"]
        new = later.get(rid)
        problems, notes = [], []
        if new is None:
            out.append({"id": rid, "item": old["item"], "source": sid, "class": "not_found",
                        "old": {k: old.get(k) for k in ("page", "printed_page", "location")}, "new": None,
                        "quote_changed": None, "note": "not in the re-pointed facts.json"})
            continue
        page_text = sec[sid][old["page"] - 1] if 1 <= old["page"] <= len(sec[sid]) else ""
        before_q, after_q = source_text.normal(old["quote"]), source_text.normal(new["quote"])
        if before_q in page_text:
            kind = "exact" if after_q == before_q else "not_found"
            if kind == "not_found":
                problems.append("the quote was changed although the earlier one occurs on the SEC page")
        else:
            found = folded_find(before_q, page_text)
            if found is not None:
                kind = "typography" if after_q == found else "not_found"
                what = "spaces" if re.sub(r"\s", "", before_q) == re.sub(r"\s", "", found) else \
                    "quotes, dashes, minus signs or spaces"
                notes.append(f"the SEC text differs from the PDF text only in {what}: "
                             + differences(before_q, found))
                if kind == "not_found":
                    problems.append(f"the quote is not the SEC page's wording at that place: {found!r}")
            else:
                kind = "relaid"
        new_page = new["page"]
        new_text = sec[sid][new_page - 1] if 1 <= new_page <= len(sec[sid]) else ""
        if after_q not in new_text:
            problems.append(f"the quote does not occur on SEC page {new_page}")
        if old["item"] == "record" and not whole_figure(new["display"], after_q):
            problems.append(f"the printed figure {new['display']!r} is not a whole figure in the quote")
        label = re.match(r"\D*?(?=[$(]?\s*\d)", before_q)
        if kind == "relaid" and label and label.group(0).strip() not in after_q:
            problems.append(f"the new quote does not hold the earlier row label {label.group(0).strip()!r}")
        printed = printed_page(sid, new_text)
        if printed != new.get("printed_page"):
            problems.append(f"SEC page {new_page} prints {printed!r}, the item says {new.get('printed_page')!r}")
        key = (sid, old["page"], new_page)  # a moved item must not inherit an unmoved item's result
        if key not in agreement:
            agreement[key] = page_agreement(sid, pdf[sid][new_page - 1], new_text) \
                if new_page == old["page"] else (False, "the page changed")
        same, how = agreement[key]
        if not same:
            problems.append(f"the SEC page and the PDF page {how}")
        changed = [field for field in DEFINING if old.get(field) != new.get(field)]
        if changed:
            problems.append("definition changed: " + ", ".join(changed))
        if problems:
            kind = "not_found"
        notes.append(f"page {how}")
        out.append({"id": rid, "item": old["item"], "source": sid, "class": kind,
                    "old": {k: old.get(k) for k in ("page", "printed_page", "location")},
                    "new": {k: new.get(k) for k in ("page", "printed_page", "location")},
                    "quote_changed": after_q != before_q, "definition_changed": changed,
                    "note": "; ".join(problems + notes)})
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--write"]
    if len(args) != 1:
        print(__doc__.strip().splitlines()[-1])
        return 2
    before = json.loads(Path(args[0]).read_bytes().decode("utf-8"))
    after = json.loads((FOLDER / "facts.json").read_bytes().decode("utf-8"))
    result = match(before, after)
    counts = Counter((r["source"], r["class"]) for r in result)
    summary = {sid: {c: counts[(sid, c)] for c in ("exact", "typography", "relaid", "not_found")}
               for sid in DOCUMENTS}
    for sid, row in summary.items():
        print(sid, row)
    for r in result:
        if r["class"] == "not_found" or r.get("definition_changed"):
            print("NOT FOUND:" if r["class"] == "not_found" else "DEFINITION:", r["id"], r["note"])
    if "--write" in sys.argv[1:]:
        report = {"about": "Every record and passage resting on the three re-sourced documents, matched against their "
                           "SEC EDGAR copies (approval fcx-sec-docs-02) by tools/sec_match.py. 'old' is the place on "
                           "the investor-relations PDF, 'new' the place on the SEC copy (file page, printed page, "
                           "location).",
                  "counts": summary, "items": result}
        (FOLDER / "sec-match.json").write_bytes((json.dumps(report, indent=1, ensure_ascii=False) + "\n")
                                                .encode("utf-8"))
    return 1 if counts and any(c == "not_found" for _, c in counts) else 0


if __name__ == "__main__":
    sys.exit(main())
