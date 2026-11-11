"""The whole fuels view (fuels-view-0.5): one read that joins the committed source record, the verified snapshots, the
exact barrel and the committed notes. Reads never fetch; this module imports no importer and no network client.
0.3: the prices come from EIA (fuels-sources-0.2, fuels-snapshot-0.2); the reply carries EIA's credit instead of FRED's
notice, each series its data vendor where EIA names one, and each snapshot its retrieval date and provider. A snapshot
from FRED (fuels-snapshot-0.1) still verifies and is listed, but its values are withheld.
0.4: a fuels-note-0.2 note carries its analysis, filled from the barrel and the Situation Now windows of the snapshot it
was written for, each statement naming the title of the mechanism it draws on.
0.5: a verified series whose latest observation is more than ten days older than the newest on the page is behind. It
keeps its price, its own date and its history, now with how far behind it is ("behind"): an old price is still a
verified price. Whatever is computed from a series that is behind is withheld instead (the barrel, its crack history
and Situation Now, when it is Brent, gasoline or diesel; nothing on the page is computed from WTI or Henry Hub), and
so is a note bound to a snapshot whose barrel input was behind.

Rules (SPEC): a snapshot set that is not verified withholds every value; a refused series, or one whose committed
terms changed after the snapshot, is withheld; a missing input withholds every output that depends on it. A history is
never padded: it holds only the observations the snapshot covers, and a gap stays a gap. Prices from different dates
are never combined: the barrel uses one date all three inputs share, and none of them may be behind."""
from datetime import date, timedelta
from pathlib import Path

from . import fuels_crack, fuels_mechanisms, fuels_notes, fuels_situation, fuels_snapshots, fuels_sources

VIEW_VERSION = "fuels-view-0.5"
HISTORY_DAYS = 365
BEHIND_DAYS = 10  # one EIA weekly cycle plus the usual publication lag, as Situation Now's staleness rule
PINK_PROBLEM = "Its source and terms for personal use are not yet read and recorded"
HELIUM_PROBLEM = ("Not yet retained. USGS gives an annual price estimate for one grade and market, not a current "
                  "spot quote")
EXAMPLE = {"gasoline": "2.50", "diesel": "3.00", "brent": "80", "basket": "112", "crack": "32",
           "label": "Synthetic unit example, not market data"}
LABELS = {"kinds": {"published": "Published by the source", "missing": "Not available"},
          "series_states": {"verified": "Verified snapshot", "missing": "No verified snapshot",
                            "refused": "Refused at retrieval", "terms_changed": "Source terms changed"}}
TERMS_CHANGED = "The source-terms record changed after this snapshot; refresh to apply it"
PROVIDER = "eia"
OLD_PROVIDER = ("This snapshot came from FRED, which this page no longer reads; it is kept as it was, and a refresh "
                "from EIA shows prices")
UNIT_TEXT = "US dollars per barrel of crude"
EVENTS = {"state": "not_connected", "schema": "fuels-event-0.1",
          "text": "No verified current events are connected to this page yet. The drivers above are general possible "
                  "explanations, not statements about current events."}
_BARREL_ROLES = ("brent", "gasoline", "diesel")
COVERAGE = [
    {"id": "wti", "label": "WTI crude", "cadence": "daily", "source": "EIA", "series_id": "RWTC",
     "state": "missing", "problem": None},
    {"id": "henry_hub", "label": "Henry Hub natural gas", "cadence": "daily", "source": "EIA",
     "series_id": "RNGWHHD", "state": "missing", "problem": None},
    {"id": "europe_gas", "label": "Europe natural gas", "cadence": "monthly",
     "source": "World Bank commodity prices (Pink Sheet)", "series_id": None, "state": "missing",
     "problem": PINK_PROBLEM},
    {"id": "urea", "label": "Urea", "cadence": "monthly", "source": "World Bank commodity prices (Pink Sheet)",
     "series_id": None, "state": "missing", "problem": PINK_PROBLEM},
    {"id": "helium", "label": "Helium", "cadence": "yearly", "source": "USGS Mineral Commodity Summaries",
     "series_id": None, "state": "missing", "problem": HELIUM_PROBLEM}]


def _state_of(loaded: dict, record: dict, entry: dict | None, provider: str | None) -> tuple[str, str | None]:
    if loaded["state"] != "verified":
        return "missing", loaded["problem"]
    if provider != PROVIDER:
        return "terms_changed", OLD_PROVIDER
    if entry is None:
        return "missing", "The snapshot holds no entry for this series"
    if entry["state"] != "stored":
        return "refused", entry.get("problem")
    if entry["terms"] != record:
        return "terms_changed", TERMS_CHANGED
    return "verified", None


def _states(loaded: dict, sources: dict, snapshot: dict | None) -> dict[str, tuple[str, str | None, dict | None]]:
    out = {}
    for record in sources["series"]:
        entry = snapshot["series"].get(record["series_id"]) if snapshot else None
        state, problem = _state_of(loaded, record, entry, snapshot.get("provider") if snapshot else PROVIDER)
        out[record["role"]] = (state, problem, entry)
    return out


def _inputs_of(states: dict) -> dict:
    return {role: fuels_snapshots.values(states[role][2]) if states[role][0] == "verified" else None
            for role in _BARREL_ROLES}


def _iso(day: date | None) -> str | None:
    return None if day is None else day.isoformat()


def _latest(entry: dict, unit: str) -> dict | None:
    observed = {day: value for day, value in fuels_snapshots.values(entry).items() if value is not None}
    if not observed:
        return None
    day = max(observed)
    return {"date": day.isoformat(), "value": fuels_crack.exact_text(observed[day]),
            "shown": fuels_crack.shown(observed[day], fuels_sources.UNITS[unit]),
            "published_on": _iso(fuels_snapshots.published_on(entry, day))}


def _history(entry: dict, latest_day: date) -> list[list]:
    cutoff = latest_day - timedelta(days=HISTORY_DAYS)
    return [[day.isoformat(), None if value is None else fuels_crack.exact_text(value)]
            for day, value in sorted(fuels_snapshots.values(entry).items()) if day > cutoff]


def _series_row(record: dict, state: str, problem: str | None, entry: dict | None, snapshot: dict | None) -> dict:
    latest = _latest(entry, record["unit"]) if state == "verified" else None
    if state == "verified" and latest is None:
        state, problem = "missing", "No observation in the snapshot has a value"
    verified = state == "verified"
    retrieved = date.fromisoformat(fuels_snapshots.retrieved_on(snapshot)) if verified else None
    return {"series_id": record["series_id"], "role": record["role"], "label": record["label"],
            "unit": record["unit"], "cadence": record["cadence"], "publication": record["publication"],
            "scope": record["scope"], "basis": record["basis"], "public": record["public"],
            "state": state, "problem": problem, "kind": "published" if verified else "missing",
            "attribution": fuels_sources.attribution(record, retrieved), "url": record["url"],
            "data_vendor": record["data_vendor"], "release": entry.get("release") if verified else None,
            "latest": latest, "behind": None,
            "history": _history(entry, date.fromisoformat(latest["date"])) if latest else []}


def behind(latest: dict[str, date | None]) -> dict[str, dict | None]:
    """Each role's lag behind the newest latest observation among the roles that have one: {"days", "newest"} when it is
    more than BEHIND_DAYS, else None; None for a role with no latest observation (not verified, or no value)."""
    known = [day for day in latest.values() if day is not None]
    newest = max(known) if known else None
    return {role: {"days": (newest - day).days, "newest": newest.isoformat()}
            if day is not None and (newest - day).days > BEHIND_DAYS else None for role, day in latest.items()}


def _date_text(day: date) -> str:
    return f"{day.day} {fuels_situation._MONTHS[day.month - 1]} {day.year}"


def _barrel(inputs: dict, latest: dict[str, date | None], labels: dict[str, str]) -> dict:
    """The barrel, or why it is withheld: a barrel input that is behind withholds it, since its other inputs would
    otherwise be pinned to an old date or combined with prices from another date."""
    lags = behind(latest)
    late = [role for role in _BARREL_ROLES if lags[role]]
    if not late:
        return fuels_crack.barrel(inputs)
    newest = date.fromisoformat(lags[late[0]]["newest"])
    said = " ".join(f"{labels[role]}'s latest price, {_date_text(latest[role])}, is {lags[role]['days']} days older "
                    f"than the newest price on this page, {_date_text(newest)}." for role in late)
    return fuels_crack.withheld(f"{said} The barrel needs Brent, gasoline and diesel on one date, none of them more "
                                f"than {BEHIND_DAYS} days behind the newest price, and prices from different dates are "
                                "never combined, so it is not computed.")


def _latest_days(states: dict) -> dict[str, date | None]:
    """Each role's latest observation date with a value in its verified entry, else None."""
    out = {}
    for role, (state, _, entry) in states.items():
        observed = ([day for day, value in fuels_snapshots.values(entry).items() if value is not None]
                    if state == "verified" else [])
        out[role] = max(observed) if observed else None
    return out


def _published_on(barrel: dict, states: dict) -> str | None:
    if barrel["state"] != "computed":
        return None
    day = date.fromisoformat(barrel["date"])
    found = [fuels_snapshots.published_on(states[role][2], day) for role in _BARREL_ROLES]
    return None if None in found else max(found).isoformat()


def _coverage(rows: dict) -> list[dict]:
    """Copies of COVERAGE; wti and henry_hub take their state and problem from this read's series."""
    out = []
    for entry in COVERAGE:
        row = rows.get(entry["id"])
        out.append(dict(entry) if row is None else dict(entry, state=row["state"], problem=row["problem"]))
    return out


def _titles(drivers: dict | None, transmission: dict | None) -> dict[str, str]:
    """Each committed mechanism by the id an analysis names it with ("drivers:<id>", "transmission:<id>")."""
    titles = {f"drivers:{item['id']}": item["title"] for item in (drivers or {}).get("items", [])}
    return titles | {f"transmission:{item['id']}": item["sector"] for item in (transmission or {}).get("items", [])}


def _with_titles(note: dict, titles: dict[str, str]) -> dict:
    """An analysis' statements with the title of the mechanism each names; one that names no committed mechanism is a
    content error (500), like any other invalid note."""
    if "analysis" not in note:
        return note
    analysis = dict(note["analysis"])
    for section in fuels_notes.SECTIONS:
        items = []
        for index, item in enumerate(analysis[section]):
            mechanism = item["mechanism"]
            if mechanism is not None and mechanism not in titles:
                raise fuels_sources.FuelsRefused(500, f"note {note['number']}.analysis.{section}[{index}].mechanism: "
                                                      "names no committed mechanism")
            items.append({**item, "mechanism_title": titles.get(mechanism) if mechanism else None})
        analysis[section] = items
    return {**note, "analysis": analysis}


def _bound(loaded: dict, sources: dict, bound: dict | None) -> tuple[dict | None, dict | None]:
    """The barrel and Situation Now of the snapshot a note was written for (None, None when it is not verified)."""
    if bound is None:
        return None, None
    states = _states(loaded, sources, bound)
    inputs = _inputs_of(states)
    barrel = _barrel(inputs, _latest_days(states), {r["role"]: r["label"] for r in sources["series"]})
    usable = None if barrel["state"] != "computed" or any(value is None for value in inputs.values()) else inputs
    retrieved_on = date.fromisoformat(bound["retrieved_at"][:10])
    return barrel, fuels_situation.situation(usable, {}, retrieved_on)


def _notes(content: Path, loaded: dict, sources: dict, latest: dict | None, latest_barrel: dict,
           titles: dict[str, str]) -> tuple:
    by_id = {s["snapshot_id"]: s for s in loaded["snapshots"]}
    latest_id = latest["snapshot_id"] if latest else None
    placed = []
    for note in fuels_notes.load_notes(content):
        bound_barrel, bound_situation = _bound(loaded, sources, by_id.get(note["snapshot_id"]))
        placed.append(fuels_notes.placed(_with_titles(note, titles), latest_id, latest_barrel, bound_barrel,
                                         bound_situation))
    rows = [{"number": n["number"], "state": n["state"], "written_on": n["written_on"],
             "snapshot_id": n["snapshot_id"], "observation_date": n["observation_date"], "review": n["review"]}
            for n in placed]
    return (placed[-1] if placed else {"state": "none"}), rows


def _mechanism(loaded: dict | None) -> dict:
    return {"state": "not_written"} if loaded is None else {"state": "written", **loaded}


def _situation(inputs: dict, rows: dict, latest: dict | None, late: bool) -> dict:
    """Situation Now from the barrel's verified series; withheld when any of the three is not verified or is behind."""
    usable = None if late or any(value is None for value in inputs.values()) else inputs
    days = {role: date.fromisoformat(row["latest"]["date"]) if row["latest"] else None for role, row in rows.items()}
    retrieved_on = date.fromisoformat(latest["retrieved_at"][:10]) if latest else None
    return fuels_situation.situation(usable, days, retrieved_on)


def _made_up(snapshot: dict | None) -> bool:
    """Whether a snapshot came from a test fake: tests/fuels_fakes.py answers as API version "SYNTHETIC-…" (EIA's
    versions are numbers), and its FRED-era fake titled every series "SYNTHETIC …"."""
    def marked(entry: dict) -> bool:
        metadata = entry.get("metadata") or {}
        return any(str(metadata.get(key) or "").startswith("SYNTHETIC") for key in ("api_version", "title"))
    return snapshot is not None and any(marked(entry) for entry in snapshot["series"].values())


def view(content: Path, snapshots: Path | None, synthetic: bool = False) -> dict:
    """The whole reply. It carries ``"synthetic": true`` when the review server says its world is SYNTHETIC
    (``synthetic``) or the shown snapshot came from the test fake, so the page marks every price as test data wherever
    it is served. Otherwise the key is absent."""
    sources, sha = fuels_sources.load_sources(content)
    loaded = fuels_snapshots.load_all(snapshots)
    latest = loaded["snapshots"][-1] if loaded["state"] == "verified" and loaded["snapshots"] else None
    synthetic = synthetic or _made_up(latest)
    first = _states(loaded, sources, latest)
    records = {r["role"]: r for r in sources["series"]}
    rows = {role: _series_row(records[role], *first[role], latest) for role in fuels_sources.ROLES}
    states = {role: (rows[role]["state"], rows[role]["problem"], first[role][2]) for role in rows}
    inputs = _inputs_of(states)
    days = {role: date.fromisoformat(row["latest"]["date"]) if row["latest"] else None for role, row in rows.items()}
    for role, lag in behind(days).items():
        rows[role]["behind"] = lag
    barrel = _barrel(inputs, days, {role: rows[role]["label"] for role in rows})
    late = any(rows[role]["behind"] for role in _BARREL_ROLES)
    computed = barrel["state"] == "computed"
    # The crack history covers exactly the dates the three shown input histories cover.
    since = max(date.fromisoformat(rows[role]["history"][0][0]) for role in _BARREL_ROLES) if computed else None
    history = fuels_crack.crack_history(inputs, since) if computed else []
    barrel |= {"published_on": _published_on(barrel, states),
               "retrieved_at": latest["retrieved_at"] if latest else None,
               "definition": {"basket": fuels_crack.BASKET_TEXT, "crack": fuels_crack.CRACK_TEXT, "unit": UNIT_TEXT}}
    drivers, transmission = fuels_mechanisms.load_drivers(content), fuels_mechanisms.load_transmission(content)
    note, note_rows = _notes(content, loaded, sources, latest, barrel, _titles(drivers, transmission))
    log = [{"id": s["snapshot_id"], "retrieved_at": s["retrieved_at"], "retrieved_on": fuels_snapshots.retrieved_on(s),
            "provider": s.get("provider"), "stored": sum(e["state"] == "stored" for e in s["series"].values()),
            "refused": sum(e["state"] != "stored" for e in s["series"].values())}
           for s in reversed(loaded["snapshots"])]
    snapshot = {"state": loaded["state"], "problem": loaded["problem"], "id": None, "retrieved_at": None,
                "retrieved_on": None, "provider": None, "adapter_version": None}
    if latest:
        snapshot |= {"id": latest["snapshot_id"], "retrieved_at": latest["retrieved_at"],
                     "retrieved_on": fuels_snapshots.retrieved_on(latest), "provider": latest.get("provider"),
                     "adapter_version": latest["adapter_version"]}
    return {"view_version": VIEW_VERSION, "provider_called": False, **({"synthetic": True} if synthetic else {}),
            "page_label": sources["page_label"],
            "credit": sources["credit"], "terms": sources["terms"],
            "sources": {"version": sources["sources_version"], "sha256": sha}, "snapshot": snapshot,
            "snapshots": log, "series": [rows[role] for role in fuels_sources.ROLES], "barrel": barrel,
            "crack_history": history, "note": note, "notes": note_rows, "coverage": _coverage(rows),
            "example": EXAMPLE, "labels": LABELS, "situation": _situation(inputs, rows, latest, late),
            "drivers": _mechanism(drivers), "transmission": _mechanism(transmission), "events": dict(EVENTS)}
