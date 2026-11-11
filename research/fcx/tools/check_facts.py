"""Check every record in research/fcx/facts.json. Reads local files only; changes nothing.

Published figures:
- the retained file matches its SHA-256 in sources.json;
- the quote occurs on the stated page of that file (page texts from source_text.py);
- the printed figure occurs in the quote and reads as the stated value.

Computed figures:
- the formula, evaluated on its inputs, gives the stated value at the stated rounding;
- inputs share one basis and one period, unless the record names the mix and why.

Names: no figure's name, unit, basis, location or period label carries a percentage. What names a figure is sent even
when its document is not verified, so a share or rate from a document (FCX's ownership of a mine, for one) is a figure of
its own record. A measure's definition ("per $0.10/lb change") is not a percentage and stays.

Assumptions must say what they assume and which records use them. Ids are unique, and every id a document cites in
backticks exists.

When the retained files are absent (a checkout without data/), the source checks are reported as skipped, and the
rest still runs. Exit status 0 means no failure.

Run: python -I research/fcx/tools/check_facts.py
"""
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_text  # noqa: E402

FOLDER = Path(__file__).resolve().parents[1]
BASES = {"consolidated", "attributable_to_common_stock", "noncontrolling_interests", "net_of_noncontrolling_interests",
         "company_definition"}
BASIS_PREFIXES = ("segment:", "division:", "mine:")
PERIOD_KINDS = {"quarter", "half_year", "nine_months", "year", "as_of", "outlook"}
KINDS = {"published", "computed", "assumption"}
DOCS = ["README.md", "business.md", "comparison.md", "mechanisms.md", "gaps.md", "sources.md", "extraction-notes.md",
        "data-table.md", "scenarios-spec.md", "sec-match.md",
        "page-spec.md"]  # page-spec.md (private; not in the public repository) is checked where it exists
PERCENT = re.compile(r"\d\s*%")


def names(record: dict) -> dict:
    """What names a figure and is sent even when it is withheld."""
    named = {key: record[key] for key in ("metric", "unit", "basis", "location") if isinstance(record.get(key), str)}
    return {**named, "period label": str((record.get("period") or {}).get("label") or "")}


def number(display: str) -> float:
    if display == "—":
        return 0.0
    negative = display.startswith("(") and display.endswith(")")
    return (-1 if negative else 1) * float(display.strip("()").replace(",", "").rstrip("%"))


def evaluate(formula: str, values: dict) -> float:
    """Arithmetic only: + - * / and parentheses over named inputs and numbers."""
    tree = ast.parse(formula, mode="eval")

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = walk(node.left), walk(node.right)
            return {ast.Add: left + right, ast.Sub: left - right, ast.Mult: left * right,
                    ast.Div: left / right if right else float("nan")}[type(node.op)]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"not allowed in a formula: {ast.dump(node)}")

    return walk(tree)


def basis_ok(basis: str) -> bool:
    return basis in BASES or basis.startswith(BASIS_PREFIXES) or basis == "segment"


def main() -> int:
    facts = json.loads((FOLDER / "facts.json").read_bytes().decode("utf-8"))["records"]
    sources = {s["id"]: s for s in json.loads((FOLDER / "sources.json").read_bytes().decode("utf-8"))["sources"]}
    failures, notes = [], []
    by_id = {}
    for record in facts:
        if record["id"] in by_id:
            failures.append(f"duplicate id {record['id']}")
        by_id[record["id"]] = record

    texts, retained = {}, {}
    for sid, source in sources.items():
        path = source_text.SOURCES.get(sid)
        if path is None or not path.exists():
            retained[sid] = False
            notes.append(f"{sid}: retained file absent here; its quotes were not checked")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != source["sha256"]:
            failures.append(f"{sid}: SHA-256 {digest} differs from sources.json {source['sha256']}")
            retained[sid] = False
            continue
        retained[sid] = True
        texts[sid] = source_text.pages(sid)

    counts = {"published": 0, "computed": 0, "assumption": 0, "quotes_checked": 0}
    for record in facts:
        rid, kind = record["id"], record.get("kind")
        if kind not in KINDS:
            failures.append(f"{rid}: kind {kind!r}")
            continue
        counts[kind] += 1
        if kind == "assumption":
            if not record.get("statement") or not record.get("used_by"):
                failures.append(f"{rid}: an assumption needs a statement and used_by")
            if not isinstance(record.get("rests_on"), list) or any(s not in sources for s in record["rests_on"]):
                failures.append(f"{rid}: an assumption names the documents its statement describes in rests_on "
                                "(a list of source ids, empty for a statement of method)")
            for used in record.get("used_by", []):
                if used not in by_id:
                    failures.append(f"{rid}: used_by names unknown id {used}")
            continue
        period = record.get("period") or {}
        if period.get("kind") not in PERIOD_KINDS or not period.get("end"):
            failures.append(f"{rid}: period {period}")
        if not basis_ok(record.get("basis", "")):
            failures.append(f"{rid}: basis {record.get('basis')!r}")
        if not record.get("unit"):
            failures.append(f"{rid}: no unit")
        for field, text in names(record).items():
            if PERCENT.search(text):
                failures.append(f"{rid}: {field} carries a percentage; a share or rate from a document is a figure of "
                                "its own record, not part of what names this one")
        if kind == "published":
            sid = record.get("source")
            if sid not in sources:
                failures.append(f"{rid}: unknown source {sid}")
                continue
            display, quote = record["display"], record["quote"]
            if display not in quote:
                failures.append(f"{rid}: display {display!r} not in its quote")
            if abs(number(display) - float(record["value"])) > 1e-9:
                failures.append(f"{rid}: display {display!r} does not read as value {record['value']}")
            if retained.get(sid):
                page = record["page"]
                pages = texts[sid]
                if not 1 <= page <= len(pages):
                    failures.append(f"{rid}: page {page} outside 1..{len(pages)}")
                elif source_text.normal(quote) not in pages[page - 1]:
                    failures.append(f"{rid}: quote not found on {sid} page {page}: {quote[:80]!r}")
                else:
                    counts["quotes_checked"] += 1
        if kind == "computed":
            inputs = record.get("inputs", {})
            missing = [i for i in inputs.values() if i not in by_id]
            if missing:
                failures.append(f"{rid}: unknown inputs {missing}")
                continue
            values = {name: float(by_id[i]["value"]) for name, i in inputs.items()}
            result = evaluate(record["formula"], values)
            places = record.get("decimals", 0)
            if round(result, places) != round(float(record["value"]), places):
                failures.append(f"{rid}: {record['formula']} = {result:.6f}, stated {record['value']}")
            used = [by_id[i] for i in inputs.values()]
            bases = {u.get("basis") for u in used}
            if len(bases) > 1 and not record.get("basis_mix"):
                failures.append(f"{rid}: mixes bases {sorted(bases)} without basis_mix")
            labels = {u["period"]["label"] for u in used}
            if len(labels) > 1 and not record.get("period_mix"):
                failures.append(f"{rid}: mixes periods {sorted(labels)} without period_mix")
            units = {u.get("unit") for u in used}
            if len(units) > 1 and not record.get("unit_mix"):
                failures.append(f"{rid}: mixes units {sorted(units)} without unit_mix")
            for assumption in record.get("assumptions", []):
                if by_id.get(assumption, {}).get("kind") != "assumption":
                    failures.append(f"{rid}: {assumption} is not an assumption record")

    passages = json.loads((FOLDER / "facts.json").read_bytes().decode("utf-8")).get("passages", [])
    for passage in passages:
        pid, sid = passage["id"], passage["source"]
        if pid in by_id:
            failures.append(f"duplicate id {pid}")
        by_id[pid] = passage
        if len(passage["quote"].split()) > 40:
            failures.append(f"{pid}: passage longer than 40 words")
        if retained.get(sid):
            pages = texts[sid]
            if not 1 <= passage["page"] <= len(pages) or \
                    source_text.normal(passage["quote"]) not in pages[passage["page"] - 1]:
                failures.append(f"{pid}: passage not found on {sid} page {passage['page']}")
            else:
                counts["quotes_checked"] += 1

    checks = json.loads((FOLDER / "facts.json").read_bytes().decode("utf-8")).get("cross_checks", {})
    for a, b in checks.get("pairs", []):
        if a not in by_id or b not in by_id:
            failures.append(f"cross check names unknown id {a if a not in by_id else b}")
        elif float(by_id[a]["value"]) != float(by_id[b]["value"]) or by_id[a]["unit"] != by_id[b]["unit"]:
            failures.append(f"cross check: {a} ({by_id[a]['value']} {by_id[a]['unit']}) differs from {b} "
                            f"({by_id[b]['value']} {by_id[b]['unit']})")
    counts["cross_checks"] = len(checks.get("pairs", []))

    cited = set()
    for name in DOCS:
        path = FOLDER / name
        if path.exists():
            cited |= set(re.findall(r"`((?:r3|q3|k25|nr|c|a)-[a-z0-9-]+)`", path.read_bytes().decode("utf-8")))
    for rid in sorted(cited - set(by_id)):
        failures.append(f"a document cites unknown id {rid}")

    print(f"records: {len(facts)} ({counts['published']} published, {counts['computed']} computed, "
          f"{counts['assumption']} assumptions); passages: {len(passages)}; quotes checked against the retained "
          f"files: {counts['quotes_checked']}; same figure in two reports: {counts['cross_checks']} pairs; "
          f"ids cited in documents: {len(cited)}")
    for note in notes:
        print("note:", note)
    for failure in failures:
        print("FAIL:", failure)
    print("OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
