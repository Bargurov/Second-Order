"""SYNTHETIC EIA Monthly Energy Review Table 7.6 files shaped like the retained ones, with acquisition records, for the
electricity findings tests and the browser check. Values are invented; nothing here is EIA data.

The CSV has the eight published series identities, monthly rows from January 2023 to June 2026 and annual rows for
2023-2025. Every month up to June 2025 has the same prior values; each month from July 2025 applies the percentages in
CHANGES, so the classes are known in advance (2025-08 sits exactly on +1% and -1%, 2025-09 just inside the band). The
PDF is a stand-in: tests bind the definitions to its hash (PDF_SHA256) instead of the real PDF's.
"""
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from second_order import electricity_evidence as evidence

PRIOR = {"ESRCPUS": Decimal("100000.000"), "ESCCPUS": Decimal("100000.000"), "ESICPUS": Decimal("80000.000"),
         "ESACPUS": Decimal("600.000")}
DIRECT, EV = Decimal("11000.000"), Decimal("2000.000")
# Month -> percentage change against a year earlier for (residential, commercial, industrial, transportation).
CHANGES = {
    "2025-07": ("2", "-2", "0.5", "0"),          # residential up, commercial down
    "2025-08": ("1", "-1", "0", "0"),            # exactly on both bounds: up and down
    "2025-09": ("0.999", "-0.999", "0", "0"),    # just inside the band: no finding
    "2025-10": ("3", "2", "1.5", "0"),           # all up
    "2025-11": ("-2", "-3", "-1", "0"),          # all down
    "2025-12": ("0.5", "0.2", "-0.4", "0"),      # all little changed
    "2026-01": ("4", "1.5", "-2.5", "1"),        # two up, one down
    "2026-02": ("-1.5", "2", "0", "0"),
    "2026-03": ("1", "1", "-1", "0"),
    "2026-04": ("1", "1", "-1", "0"),
    "2026-05": ("1", "1", "-1", "0"),
    "2026-06": ("1", "1", "-1", "0"),
}
FINDING_MONTHS = ["2026-06", "2026-05", "2026-04", "2026-03", "2026-02", "2026-01", "2025-08", "2025-07"]
ALL_UP = {month: ("2", "3", "1.5", "0") for month in CHANGES}  # A scenario with no finding.
PDF = b"%PDF-1.6\n% SYNTHETIC stand-in for Table 7.6; not an EIA document.\n1 0 obj << >> endobj\ntrailer\n%%EOF\n"
PDF_SHA256 = hashlib.sha256(PDF).hexdigest()
LANDING = ('<!DOCTYPE html><html><head><title>Total Energy Monthly Data</title></head><body><h1>Monthly Energy Review'
           '</h1><div class="release-dates"><span class="responsive-container"><span class="label">Release Date:</span>'
           ' <span class="date">\n  September 29, 2026  </span></span><span class="responsive-container"><span '
           'class="label">Next Release Date:</span> <span class="date"> October 2026 </span></span></div>'
           '<p>SYNTHETIC page shaped like the retained one.</p></body></html>').encode("utf-8")


def months(first: str = "2023-01", last: str = "2026-06") -> list[str]:
    out, year, month = [], int(first[:4]), int(first[5:])
    while f"{year:04d}-{month:02d}" <= last:
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def values(changes: dict = CHANGES, first: str = "2023-01") -> dict:
    """(code, YYYY-MM) -> exact value, the four sectors summing to the total in every month, from `first`."""
    out = {}
    for key in months(first):
        for code, base in PRIOR.items():
            pct = Decimal(changes[key][list(PRIOR).index(code)]) if key in changes else Decimal(0)
            out[(code, key)] = (base * (1 + pct / 100)).quantize(Decimal("0.001"))
        total = sum(out[(code, key)] for code in PRIOR)
        out[("ESTCPUS", key)] = total
        out[("ELDUPUS", key)] = DIRECT if key >= "2024-01" else None
        out[("ELTCPUS", key)] = total + (DIRECT if key >= "2024-01" else 0)
        out[("ESVHPUS", key)] = EV if key >= "2025-01" else None
    return out


def csv_text(changes: dict = CHANGES, overrides: dict | None = None, extra: list[list[str]] | None = None,
             first: str = "2023-01") -> str:
    """The CSV, in the published column layout, with monthly rows from `first` to June 2026 and annual rows for every
    complete year. ``overrides`` maps (code, YYYYMM) to a value text, or to None to drop the row; ``extra`` rows are
    appended as given."""
    found = values(changes, first)
    rows = [evidence.HEADER]
    for code, (order, description) in evidence.SERIES.items():
        for key in months(first):
            value = found[(code, key)]
            rows.append([code, key.replace("-", ""), "Not Available" if value is None else format(value, "f"), order,
                         description, evidence.UNIT])
        for year in (str(y) for y in range(int(first[:4]) + (first[5:] != "01"), 2026)):
            parts = [found[(code, f"{year}-{m:02d}")] for m in range(1, 13)]
            total = "Not Available" if any(p is None for p in parts) else format(sum(parts), "f")
            rows.append([code, f"{year}13", total, order, description, evidence.UNIT])
    for code_period, value in (overrides or {}).items():
        index = next((i for i, row in enumerate(rows) if (row[0], row[1]) == code_period), None)
        if value is None and index is not None:
            rows.pop(index)
        elif index is not None:
            rows[index][2] = value
    rows.extend(extra or [])
    return "".join(",".join(f'"{cell}"' if "," in cell else cell for cell in row) + "\r\n" for row in rows)


def _record(approval: str, folder: str, name: str, url: str, data: bytes, n: int, checked: bool,
            headers: dict) -> tuple[str, dict]:
    sha = hashlib.sha256(data).hexdigest()
    record = {"approval_id": approval, "n": n, "url": url, "outcome": "complete", "http_status": 200,
              "hash_kind": "complete_response", "retained": f"data/sector-sources/eia-mer/{folder}/{name}",
              "retained_sha256": sha, "sha256": sha, "bytes": len(data),
              "dispatched_at": f"2026-10-11T21:4{n}:13.000000+00:00",
              "body_completed_at": f"2026-10-11T21:4{n}:15.000000+00:00", "named_headers": headers}
    if checked:
        record["content_check"] = {"state": "format_ok", "reasons": []}
    return f"acquisitions/{approval}/outcome-{n}.json", record


def keep(root: Path, csv: str | None = None, pdf: bytes = PDF, landing: bytes | None = LANDING,
         record_changes: dict | None = None) -> None:
    """Writes the three files and their acquisition records under root (a stand-in for data/sector-sources/eia-mer)."""
    data = (csv if csv is not None else csv_text()).encode("utf-8")
    files = [("eia-mer-table76-01", "table76", "T07.06.csv", evidence.CSV_URL, data, 1, True,
              {"content-type": "text/csv; charset=utf-8", "last-modified": None,
               "content-disposition": "attachment; filename=MER_T07_06.csv"}),
             ("eia-mer-table76-01", "table76", "sec7_19.pdf", evidence.PDF_URL, pdf, 2, True,
              {"content-type": "application/pdf", "last-modified": "Tue, 29 Sep 2026 13:57:57 GMT"})]
    if landing is not None:
        files.append(("eia-mer-inspection-01", "inspection", "landing.html", evidence.LANDING_URL, landing, 1, False,
                      {"content-type": "text/html; charset=UTF-8", "last-modified": None}))
    for approval, folder, name, url, content, n, checked, headers in files:
        path = root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        relative, record = _record(approval, folder, name, url, content, n, checked, headers)
        record.update((record_changes or {}).get(name, {}))
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record, indent=1), encoding="utf-8")
