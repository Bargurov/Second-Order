"""SYNTHETIC H.15 release packages holding the Treasury findings pilot's seven series. Not a test module.

Values are invented patterns in the Board's data-entry format, with the attributes and descriptions the pilot requires
(insight_evidence.SERIES); the two series market context validates keep their exact form, so a package is accepted by
the existing validation. ``overrides`` maps (series ID, date) to the text to state ("ND" for no value, None for no
row). Nothing here is an H.15 observation.
"""
from datetime import date, datetime, timedelta

from market_fakes import (DATASET_OPEN, DISCONTINUED_OPEN, MESSAGE_OPEN, keep_package, release_zip, series_xml,
                          target_xml)
from second_order import insight_evidence, market_retrieval
from second_order.market_calendar import expected_sessions

TARGETS = ("RIFLGFCY02_N.B", "RIFLGFCY10_N.B")
BASE = {"RIFLGFCM03_N.B": 4.0, "RIFLGFCY02_N.B": 3.5, "RIFLGFCY05_N.B": 3.7, "RIFLGFCY10_N.B": 4.1,
        "RIFLGFCY05_XII_N.B": 1.4, "RIFLGFCY10_XII_N.B": 1.8}


def pattern(series_id: str, day: date) -> str:
    """An invented value: a base level plus a varied daily wobble, so reference windows have a spread of changes."""
    if series_id == "RIFSRP_F02_N.B":
        return "4.25"
    number = day.toordinal()
    wobble = ((number * 7 + len(series_id) * 3) % 23 - 11) / 100
    return f"{BASE[series_id] + wobble:.2f}"


def rows(series_id: str, start: date, end: date, overrides: dict | None = None) -> list[tuple[str, str, str]]:
    sessions = expected_sessions(start, end)
    found, day = [], start
    while day <= end:
        if day.weekday() < 5:
            text = (overrides or {}).get((series_id, day), pattern(series_id, day) if day in sessions or
                                         series_id == "RIFSRP_F02_N.B" else "ND")
            if text is not None:
                found.append((day.isoformat(), "ND", "-9999") if text == "ND" else (day.isoformat(), "A", text))
        day += timedelta(days=1)
    return found


def data(start: date, end: date, overrides: dict | None = None, prepared: str = "2026-10-08T15:40:02",
         attributes: dict | None = None, omit: tuple = ()) -> bytes:
    """``attributes`` replaces some attributes of a non-target series; ``omit`` leaves non-target series out."""
    parts = [MESSAGE_OPEN.format(prepared=prepared), DATASET_OPEN]
    for series_id in TARGETS:
        parts.append(target_xml(series_id, rows(series_id, start, end, overrides)))
    for series_id, spec in insight_evidence.SERIES.items():
        if series_id in TARGETS or series_id in omit:
            continue
        stated = {**spec["attributes"], **(attributes or {}).get(series_id, {})}
        parts.append(series_xml(series_id, rows(series_id, start, end, overrides), stated, spec["short"],
                                spec["long"]))
    parts += ["  </frb:DataSet>\r\n", DISCONTINUED_OPEN,
              series_xml("H0.RIFSPDCNSM01_N.B", [("2000-01-03", "A", "5.80")]), "  </frb:DataSet>\r\n",
              "</message:MessageGroup>"]
    return "".join(parts).encode("utf-8")


def keep(market, end: date, requested: datetime, overrides: dict | None = None, start: date = date(2023, 1, 2),
         **changes) -> str:
    """Keep and validate one SYNTHETIC package; returns its ID."""
    package_id = keep_package(market, release_zip(data(start, end, overrides, **changes)), requested)
    market_retrieval.validate_packages(market, lambda: requested + timedelta(minutes=1))
    return package_id
