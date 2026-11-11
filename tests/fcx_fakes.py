"""A SYNTHETIC FCX research package for default test runs (made-up documents; the records are the committed ones).

synthetic_package(target, variant) copies the committed research/fcx below ``target`` and writes four SYNTHETIC
documents in place of the private retained ones, then rewrites each sources.json entry and its acquisition outcome to
the synthetic file's size and SHA-256. company_research_view.resolved() checks files by size and hash only, so the
committed records then read as verified, as the copper suite does with its SYNTHETIC sources. The variants break one
thing each, for the failure checks. The committed folder is only read.
"""
import json
from hashlib import sha256
from pathlib import Path
import shutil

from second_order import company_research_view as crv

VARIANTS = ("verified", "news-changed", "news-missing", "10q-changed", "10q-missing", "facts-missing",
            "facts-broken", "unit-changed", "record-no-value", "inputs-list", "record-missing", "page-changed",
            "display-mismatch", "capacity-zero")
RECORD_VARIANTS = ("facts-broken", "unit-changed", "record-no-value", "inputs-list", "record-missing", "page-changed",
                   "display-mismatch", "capacity-zero")
DOCUMENT_VARIANTS = {"news-changed": ("news-2026-11-04", "changed"), "news-missing": ("news-2026-11-04", "missing"),
                     "10q-changed": ("10q-2026q3", "changed"), "10q-missing": ("10q-2026q3", "missing")}
UNRELATED = "k25-copper-sales-fy2025"  # A record no copper tool reads.


def _json(path: Path):
    return json.loads(path.read_bytes().decode("utf-8"))


def _write(path: Path, data) -> None:
    path.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


def document_bytes(source_id: str) -> bytes:
    line = f"SYNTHETIC FCX document {source_id}: made-up bytes for tests, not a company document.\n".encode("ascii")
    return line * (1024 // len(line) + 1)


def synthetic_package(target: Path, variant: str = "verified") -> tuple[Path, Path]:
    """(research folder, documents folder) below ``target``: see the module docstring."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    target = Path(target)
    research, documents = target / "research", target / "sources"
    shutil.copytree(crv.RESEARCH_DIR, research, ignore=shutil.ignore_patterns("__pycache__"))
    listing = _json(research / "sources.json")
    for entry in listing["sources"]:
        raw = document_bytes(entry["id"])
        path = documents / entry["folder"] / entry["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        entry["bytes"], entry["sha256"] = len(raw), sha256(raw).hexdigest()
        outcome_path = research / "acquisition" / entry["approval_id"] / f"outcome-{entry['attempt']}.json"
        outcome = _json(outcome_path)
        outcome["bytes"], outcome["sha256"] = entry["bytes"], entry["sha256"]
        _write(outcome_path, outcome)
    _write(research / "sources.json", listing)
    if variant in DOCUMENT_VARIANTS:
        sid, how = DOCUMENT_VARIANTS[variant]
        entry = next(item for item in listing["sources"] if item["id"] == sid)
        path = documents / entry["folder"] / entry["name"]
        if how == "missing":
            path.unlink()
        else:
            raw = bytearray(path.read_bytes())
            raw[len(raw) // 2] ^= 1
            path.write_bytes(bytes(raw))
    elif variant == "facts-missing":
        (research / "facts.json").unlink()
    elif variant in RECORD_VARIANTS:
        facts = _json(research / "facts.json")
        by_id = {record["id"]: record for record in facts["records"]}
        if variant == "facts-broken":
            by_id[UNRELATED]["metric"] += " (1%)"
        elif variant == "unit-changed":
            by_id["nr-bagdad-cu-increment"]["unit"] = "million pounds"
        elif variant == "record-no-value":
            del by_id[UNRELATED]["value"]
        elif variant == "inputs-list":  # Inputs that are a list, not a mapping, on a record no copper tool reads.
            by_id[UNRELATED]["inputs"] = [UNRELATED]
        elif variant == "record-missing":
            facts["records"] = [record for record in facts["records"] if record["id"] != "nr-bagdad-construction-years"]
        elif variant == "page-changed":
            by_id["nr-bagdad-cu-increment"]["page"] = 3
        elif variant == "display-mismatch":  # The printed figure no longer reads as its value: the record is withheld.
            by_id["nr-bagdad-capex-estimate"]["display"] = "4.6"
        else:  # capacity-zero: verified, but no capital per tonne can be computed on it.
            by_id["nr-bagdad-cu-increment"]["value"], by_id["nr-bagdad-cu-increment"]["display"] = 0, "0"
        _write(research / "facts.json", facts)
    return research, documents
