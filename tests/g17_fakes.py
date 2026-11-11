"""SYNTHETIC G.17 release pages and acquisition records for tests, shaped like the retained Board pages: header cells
with ids, rows whose `headers` name their section and ancestors, indent classes, subheads, date and update statements
and the Table 1 notes. The values are invented. Nothing here reads or writes outside the folder it is given.
"""
from datetime import date
import hashlib
import json
from pathlib import Path

MONTH_NAMES = {1: "Jan.", 2: "Feb.", 3: "Mar.", 4: "Apr.", 5: "May", 6: "June", 7: "July", 8: "Aug.", 9: "Sept.",
               10: "Oct.", 11: "Nov.", 12: "Dec."}
RELEASES = {"20260717": date(2026, 6, 1), "20260818": date(2026, 7, 1), "20260918": date(2026, 8, 1)}
DURABLE = "INDUSTRY GROUP / Manufacturing / Manufacturing (NAICS) / Durable manufacturing"
NONDURABLE = "INDUSTRY GROUP / Manufacturing / Manufacturing (NAICS) / Nondurable manufacturing"
MACHINERY, VEHICLES, MINING = DURABLE + " / Machinery", DURABLE + " / Motor vehicles and parts", "INDUSTRY GROUP / Mining"
# Invented values that create one case of each kind; everything else is a small positive rate, unchanged across releases.
SCENARIO = {
    ("20260818", DURABLE, "2026-07"): ".7", ("20260818", VEHICLES, "2026-07"): "-2.1",
    ("20260918", DURABLE, "2026-07"): ".6", ("20260918", VEHICLES, "2026-07"): "-.8",
    ("20260717", MACHINERY, "2026-06"): "-.7", ("20260818", MACHINERY, "2026-06"): ".1",
    ("20260918", MACHINERY, "2026-06"): ".4",
    (None, NONDURABLE, "2026-08"): ".0",
    ("20260717", MINING, "2026-05"): ".1", ("20260818", MINING, "2026-05"): ".0", ("20260918", MINING, "2026-05"): ".0",
}
# Breadth (browser scenario): in the September 18 release, April 2026 has 10 of the 19 subsectors printed down while
# Manufacturing (NAICS) is printed up; the August 18 release prints April with every subsector up.
BREADTH_DOWN = ["Wood products", "Nonmetallic mineral products", "Primary metals", "Fabricated metal products",
                "Machinery", "Computer and electronic products", "Electrical equip., appliances, and components",
                "Motor vehicles and parts", "Aerospace and miscellaneous transportation equipment",
                "Furniture and related products"]
BREADTH = {("20260918", "INDUSTRY GROUP / Manufacturing / Manufacturing (NAICS)", "2026-04"): ".3",
           **{("20260918", f"{DURABLE} / {label}", "2026-04"): "-.2" for label in BREADTH_DOWN}}
# (section, labels from the top of the section, NAICS code, proportion). The 19 NAICS manufacturing subsectors
# are all present, with the labels, codes and proportions the Board's Table 1 prints; the values are invented.
ROWS = [
    (None, ("Total IP",), None, "100.00"),
    ("MARKET GROUP", ("Final products and nonindustrial supplies",), None, "56.57"),
    ("MARKET GROUP", ("Final products and nonindustrial supplies", "Consumer goods"), None, "27.85"),
    ("MARKET GROUP", ("Materials",), None, "43.43"),
    ("MARKET GROUP", ("Materials", "Non-energy"), None, "27.18"),
    ("MARKET GROUP", ("Materials", "Non-energy", "Paper"), None, "1.14"),
    ("INDUSTRY GROUP", ("Manufacturing",), None, "75.89"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)"), "31-33", "74.37"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing"), None, "39.04"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing", "Wood products"), "321", "1.64"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing", "Nonmetallic mineral products"), "327", "2.38"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing", "Primary metals"), "331", "2.45"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing", "Fabricated metal products"), "332", "6.27"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing", "Machinery"), "333", "5.50"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing", "Computer and electronic products"), "334", "4.98"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing", "Electrical equip., appliances, and components"), "335", "2.31"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing", "Motor vehicles and parts"), "3361-3", "5.80"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing", "Aerospace and miscellaneous transportation equipment"), "3364-9", "4.31"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing", "Furniture and related products"), "337", "1.04"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Durable manufacturing", "Miscellaneous"), "339", "2.36"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Nondurable manufacturing"), None, "35.34"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Nondurable manufacturing", "Food, beverage, and tobacco products"), "311,2", "12.58"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Nondurable manufacturing", "Textile and product mills"), "313,4", ".51"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Nondurable manufacturing", "Apparel and leather"), "315,6", ".19"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Nondurable manufacturing", "Paper"), "322", "2.18"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Nondurable manufacturing", "Printing and support"), "323", "1.37"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Nondurable manufacturing", "Petroleum and coal products"), "324", "3.01"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Nondurable manufacturing", "Chemicals"), "325", "11.93"),
    ("INDUSTRY GROUP", ("Manufacturing", "Manufacturing (NAICS)", "Nondurable manufacturing", "Plastics and rubber products"), "326", "3.56"),
    ("INDUSTRY GROUP", ("Manufacturing", "Other manufacturing (non-NAICS)"), "1133,5131pt.", "1.51"),
    ("INDUSTRY GROUP", ("Mining",), "21", "11.71"),
    ("INDUSTRY GROUP", ("Utilities",), "2211,2", "12.40"),
    ("INDUSTRY GROUP", ("Utilities", "Electric"), "2211", "10.81"),
    ("INDUSTRY GROUP", ("Utilities", "Natural gas"), "2212", "1.59"),
]


def path_of(section, labels) -> str:
    return " / ".join(([section] if section else []) + list(labels))


def months(release: str) -> list[date]:
    """The six reference months a release prints, ending at its preliminary month."""
    last, out = RELEASES[release], []
    for back in range(5, -1, -1):
        year, month = last.year, last.month - back
        while month <= 0:
            year, month = year - 1, month + 12
        out.append(date(year, month, 1))
    return out


def key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def default(path: str, month: str) -> str:
    """A small positive invented rate, the same in every release (so nothing is revised unless a test says so)."""
    return f".{int(hashlib.sha256(f'{path}|{month}'.encode()).hexdigest(), 16) % 5 + 1}"


def value(release: str, path: str, month: str, overrides: dict) -> str:
    for candidate in ((release, path, month), (None, path, month)):
        if candidate in overrides:
            return overrides[candidate]
    return default(path, month)


def column(release: str, path: str, name: str, overrides: dict) -> str:
    """A fourth-quarter ("q4:<year>") or 12-month ("12m") value: 1.0 unless a test overrides it."""
    for candidate in ((release, path, name), (None, path, name)):
        if candidate in overrides:
            return overrides[candidate]
    return "1.0"


def _stated(release: str) -> str:
    day = date(int(release[:4]), int(release[4:6]), int(release[6:]))
    return f"{day.strftime('%B')} {day.day}, {day.year}"


def _page(release: str, body: str, last_update: str | None = None) -> str:
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>FRB: G.17</title></head><body>\n'
            f'<div class="container"><h2>Industrial Production and Capacity Utilization - G.17</h2>\n'
            f'<h3>Current Release <a href="#">PDF</a></h3>\n<div class="dates">Release Date: {_stated(release)}</div>\n'
            f'{body}\n<div class="row"><div class="lastUpdate" id="lastUpdate">Last Update: '
            f'{last_update or _stated(release)} </div></div></div></body></html>\n')


def table1(release: str, overrides: dict | None = None, rows=ROWS) -> str:
    overrides = overrides or {}
    days = months(release)
    month_ids = [f"hdr{20 + i}" for i in range(6)]
    marker = ["revised"] * 5 + ["preliminary"]
    head = ('<thead>\n<tr>\n<th colspan=1  rowspan=5  id=hdr11> Item </th>\n<th colspan=1  rowspan=5  id=hdr12> NAICS '
            '</th>\n<th colspan=1  rowspan=5  id=hdr6> 2025<br>Proportion<a href="#fn1_1_1">[1]</a> </th>\n'
            '<th colspan=3  rowspan=3  id=hdr1> Fourth&nbsp;quarter&nbsp;to<br>fourth&nbsp;quarter </th>\n'
            '<th colspan=3  rowspan=3  id=hdr3> Annual&nbsp;rate </th>\n<th colspan=6  rowspan=3  id=hdr4> Monthly&nbsp;'
            f"rate </th>\n<th colspan=1  rowspan=5  id=hdr5> {MONTH_NAMES[days[-1].month]}&nbsp;'25<br>to<br>"
            f"{MONTH_NAMES[days[-1].month]}&nbsp;'26 </th>\n</tr>\n<tr>\n</tr>\n<tr>\n</tr>\n<tr>\n<th> &nbsp; </th>\n"
            '<th> &nbsp; </th>\n<th> &nbsp; </th>\n<th colspan=1  rowspan=2  id=hdr7> 2025<br>Q4 </th>\n'
            f'<th  colspan=2  id=hdr8> 2026 </th>\n<th      colspan=6  id=hdr9> {days[0].year} </th>\n</tr>\n<tr>\n'
            '<th colspan=1  id=hdr14> 2023 </th>\n<th colspan=1  id=hdr15> 2024 </th>\n<th colspan=1  id=hdr16> 2025 '
            '</th>\n<th colspan=1  id=hdr18> Q1<abbr title="revised">[r]</abbr> </th>\n<th colspan=1  id=hdr19> '
            'Q2<abbr title="revised">[r]</abbr> </th>\n' +
            "".join(f'<th colspan=1  id={mid}> {MONTH_NAMES[day.month]}<abbr title="{mark}">[{mark[0]}]</abbr> </th>\n'
                    for mid, day, mark in zip(month_ids, days, marker)) + "</tr>\n</thead>\n")
    out, ids, section_id, section_seen, counter = [head], {}, None, None, 100
    for section, labels, naics, share in rows:
        if section != section_seen:
            section_seen = section
            if section:
                counter += 1
                section_id = f"hdr{counter}"
                out.append(f'<tr>\n<th id= {section_id} colspan=16 class="subhead">{section.replace(" ", "&nbsp;")}'
                           '</th>\n</tr>\n')
            else:
                section_id = None
        counter += 1
        own = f"hdr{counter}"
        path = path_of(section, labels)
        ids[path] = own
        ancestors = [ids[path_of(section, labels[:i])] for i in range(1, len(labels))]
        context = " ".join(([section_id] if section_id else []) + ancestors)
        depth = len(labels) - 1
        css = f'class="indent{depth}"  ' if depth else ""
        row_heads = f" {context} {own}".replace("  ", " ")
        cells = [f'<th {css}headers=" hdr11 {context + " " if context else ""}" id={own}>'
                 f'{labels[-1].replace(" ", "&nbsp;")}</th>',
                 f'<td headers=" hdr12{row_heads}">{naics or "&nbsp;"}</td>',
                 f'<td headers=" hdr6{row_heads}">{share}</td>']
        for h, year in ((14, "2023"), (15, "2024"), (16, "2025")):
            text = column(release, path, f"q4:{year}", overrides)
            cells.append(f'<td headers=" hdr1 hdr{h}{row_heads}">{text if text != "" else "&nbsp;"}</td>')
        cells += [f'<td headers=" hdr3 hdr7{row_heads}">1.0</td>', f'<td headers=" hdr3 hdr8 hdr18{row_heads}">1.0</td>',
                  f'<td headers=" hdr3 hdr8 hdr19{row_heads}">1.0</td>']
        for mid, day in zip(month_ids, days):
            text = value(release, path, key(day), overrides)
            cells.append(f'<td headers=" hdr4 hdr9 {mid}{row_heads}">{text if text != "" else "&nbsp;"}</td>')
        text = column(release, path, "12m", overrides)
        cells.append(f'<td headers=" hdr5{row_heads}">{text if text != "" else "&nbsp;"}</td>')
        out.append("<tr>\n" + "\n".join(cells) + "\n</tr>\n")
    title = "Table 1 Industrial Production: Market and Industry Group Summary"
    body = (f'<h5 class="tablehead">{title}</h5><div id="data-table-1" class="data-table"><span class="tableunit">'
            f'Percent change, seasonally adjusted</span>\n<table title="{title}" class="statistics pubtables">\n'
            + "".join(out) + "</table>\n[r]  Revised.  [p]  Preliminary.\n<br>     <a name=\"fn1_1_1\"></a>[1]  The "
            "proportion data are the relative weights for the rates of change for each series in the computation of the "
            "change in total industrial production in the following year.\n<br>     Note.  Under industry groups, the "
            "figures to the right of the series descriptions are 2017 North American Industry Classification System "
            "(NAICS) codes.  The abbreviation pt\ndenotes part of a NAICS code.  SYNTHETIC test page.\n</div>")
    return _page(release, body)


SUMMARY_ROWS = [(None, "Total index", "Total IP"), ("Major market groups", "Final Products", None),
                ("Major industry groups", "Manufacturing (see note below)", "INDUSTRY GROUP / Manufacturing"),
                ("Major industry groups", "Mining", "INDUSTRY GROUP / Mining"),
                ("Major industry groups", "Utilities", "INDUSTRY GROUP / Utilities")]


def summary(release: str, overrides: dict | None = None) -> str:
    overrides = overrides or {}
    days = months(release)
    marker = ["revised"] * 5 + ["preliminary"]
    level_ids, rate_ids = [f"hdr{7 + i}" for i in range(6)], [f"hdr{13 + i}" for i in range(6)]
    head = ('<thead>\n<tr>\n<th colspan=1  rowspan=3  id=hdr6> Industrial&nbsp;production </th>\n<th colspan=6  id=hdr1>'
            ' 2017=100 </th>\n<th colspan=7  id=hdr2> Percent&nbsp;change </th>\n</tr>\n<tr>\n<th      colspan=6  '
            f'id=hdr3> {days[0].year} </th>\n<th      colspan=6  id=hdr4> {days[0].year} </th>\n<th colspan=1  rowspan=2'
            "  id=hdr5> 12-month </th>\n</tr>\n<tr>\n" +
            "".join(f'<th colspan=1  id={mid}> {MONTH_NAMES[day.month]}<abbr title="{mark}">[{mark[0]}]</abbr> </th>\n'
                    for mid, day, mark in zip(level_ids + rate_ids, days + days, marker + marker)) + "</tr>\n</thead>\n")
    out, counter, section_seen, section_id = [head], 20, None, None
    for section, label, table_path in SUMMARY_ROWS:
        if section != section_seen and section:
            counter += 1
            section_id, section_seen = f"hdr{counter}", section
            out.append(f'<tr>\n<th id= {section_id} colspan=14 class="subhead">{section.replace(" ", "&nbsp;")}'
                       "</th>\n</tr>\n")
        counter += 1
        own = f"hdr{counter}"
        context = f" {section_id}" if section_id else ""
        cells = [f'<th headers=" hdr6{context} " id={own}>{label.replace(" ", "&nbsp;")}</th>']
        cells += [f'<td headers=" hdr1 hdr3 {mid}{context} {own}">100.0</td>' for mid in level_ids]
        for mid, day in zip(rate_ids, days):
            text = value(release, table_path, key(day), overrides) if table_path else ".1"
            cells.append(f'<td headers=" hdr2 hdr4 {mid}{context} {own}">{text}</td>')
        cells.append(f'<td headers=" hdr2 hdr5{context} {own}">1.0</td>')
        out.append("<tr>\n" + "\n".join(cells) + "\n</tr>\n")
        if label in ("Total index", "Manufacturing (see note below)"):
            counter += 1
            prev = f"hdr{counter}"
            cells = [f'<th class="indent1"  headers=" hdr6{context} {own} " id={prev}>Previous&nbsp;estimates</th>']
            cells += [f'<td headers=" hdr1 hdr3 {mid}{context} {own} {prev}">100.0</td>' for mid in level_ids]
            cells += [f'<td headers=" hdr2 hdr4 {mid}{context} {own} {prev}">.1</td>' for mid in rate_ids]
            cells.append(f'<td headers=" hdr2 hdr5{context} {own} {prev}">&nbsp;</td>')
            out.append("<tr>\n" + "\n".join(cells) + "\n</tr>\n")
    title = "Industrial Production and Capacity Utilization: Summary"
    body = (f'<p>SYNTHETIC test release text.</p>\n<h5 class="tablehead">{title}</h5><div class="data-table"><span '
            f'class="tableunit">Seasonally adjusted</span>\n<table title="{title}" class="statistics pubtables">\n'
            + "".join(out) + '</table></div>\n<h5 class="tablehead">Capacity Utilization</h5><table title="Capacity '
            'Utilization"><tr><td>76.0</td></tr></table>')
    return _page(release, body)


def keep(root: Path, releases=tuple(RELEASES), overrides: dict | None = None, pages: dict | None = None) -> None:
    """Writes each release's table1.htm and release.html with outcome records of both approvals, as the acquisitions
    did. `pages` may replace a page's text: {(release, file name): text}."""
    pages = pages or {}
    for approval, name in (("g17-industry-tables-01", "table1.htm"), ("g17-release-tables-01", "release.html")):
        run = root / "acquisitions" / approval
        run.mkdir(parents=True, exist_ok=True)
        start = len(list(run.glob("outcome-*.json")))
        for n, release in enumerate(releases, start=start + 1):
            text = pages.get((release, name))
            if text is None:
                text = table1(release, overrides) if name == "table1.htm" else summary(release, overrides)
            data = text.encode("utf-8")
            (root / release).mkdir(parents=True, exist_ok=True)
            (root / release / name).write_bytes(data)
            sha = hashlib.sha256(data).hexdigest()
            base = f"https://www.federalreserve.gov/releases/g17/{release}/"
            (run / f"outcome-{n}.json").write_text(json.dumps({
                "approval_id": approval, "n": n, "url": base if name == "release.html" else base + name,
                "http_status": 200, "outcome": "complete", "hash_kind": "complete_response", "sha256": sha,
                "retained_sha256": sha, "bytes": len(data), "retained": f"data/sector-sources/g17/{release}/{name}",
                "dispatched_at": "2026-10-11T17:00:00+00:00",
                "named_headers": {"last-modified": "SYNTHETIC"}}), encoding="utf-8")
