"""Mission I research contract - tracked-artifact-backed evidence record.

Builds the structured, read-only representation of the completed Mission I
ordinary-period comparison (``mission-i-evidence-v1``) for application
consumers.

Sources of truth: the seven tracked Mission I publications, parsed at
request time. Canonical ownership: I0 owns the frozen question, estimand,
and falsifier definitions; I1 owns the executed universe funnels and the
FOMC 20d structural infeasibility; I2A owns attempted/available coverage;
I2B owns the frozen 20-cell order, MEMP, and signed-percentile median;
I2C-A owns the calibration percentiles, B, seed, and year vectors; I2C-B
owns the published falsifier values; the closeout owns interpretation,
fragility synthesis, the whole-mission conclusion, and the permanent
non-claims. Downstream repetitions are reconciliation copies - any
disagreement between copies refuses service.

This endpoint PUBLISHES closed results. It reruns no statistic, no
calibration, no placement draw, and no falsifier; every research number
is extracted from the tracked publications (drift-tested), and the two
families are never pooled. Artifact drift (missing file, malformed
cardinality, changed identity, diverging repeated copy, lost frozen
wording) raises rather than serving stale, partial, or reinterpreted
numbers.

Fresh-clone contract: reads only tracked repository files; imports no
database module, opens no sqlite connection, performs no network I/O.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_STATS = _ROOT / "stats"

CONTRACT_VERSION = "mission-i-evidence-v1"

I0_PATH = _STATS / "I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md"
I1_PATH = _STATS / "I1_ORDINARY_PERIOD_CANDIDATE_UNIVERSE.md"
I2A_PATH = _STATS / "I2A_RESPONSE_SUBSTRATE.md"
I2B_PATH = _STATS / "I2B_MEMP_PRIMARY_COMPARISON.md"
I2C_CALIBRATION_PATH = _STATS / "I2C_CALIBRATION.md"
I2C_FALSIFIERS_PATH = _STATS / "I2C_FALSIFIERS.md"
CLOSEOUT_PATH = _STATS / "MISSION_I_CLOSEOUT.md"

# Frozen identity manifest (identities only - never research values).
_METRICS: tuple[str, ...] = ("raw_return", "spy_relative_ar",
                             "sector_relative_ar", "sar")
_FAMILY_HORIZONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("FOMC", ("1d", "5d")),
    ("OPEC", ("1d", "5d", "20d")),
)
_CELL_IDENTITY: tuple[tuple[str, str, str], ...] = tuple(
    (family, horizon, metric)
    for family, horizons in _FAMILY_HORIZONS
    for horizon in horizons
    for metric in _METRICS)
_ALL_HORIZONS: tuple[str, ...] = ("1d", "5d", "20d")
_FAMILY_ASSETS_EXPECTED = ("KRE", "XOP")  # identity check only

# Closeout display names for metrics (its LOYO table uses prose labels).
_DISPLAY_METRIC = {"raw_return": "raw_return", "SAR": "sar",
                   "SPY-relative AR": "spy_relative_ar",
                   "sector-relative AR": "sector_relative_ar"}

_DIRECTION_LABEL = {1: "above_ordinary_midpoint",
                    -1: "below_ordinary_midpoint",
                    0: "at_ordinary_midpoint"}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"mission-i artifact unreadable: {path.name}: {exc}") from exc


def _drift(message: str) -> ValueError:
    return ValueError(f"mission-i artifact drift: {message}; refusing to "
                      "serve")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise _drift(message)


def _search(pattern: str, text: str, artifact: str) -> re.Match:
    m = re.search(pattern, text, re.MULTILINE)
    if m is None:
        raise _drift(f"{artifact} no longer matches required pattern "
                     f"{pattern!r}")
    return m


def _sentence_with(text: str, marker: str, artifact: str) -> str:
    """The single-spaced sentence/paragraph fragment containing marker."""
    flat = re.sub(r"\s+", " ", text)
    idx = flat.find(marker)
    _require(idx >= 0, f"{artifact} lost frozen wording {marker!r}")
    start = flat.rfind(". ", 0, idx)
    start = start + 2 if start >= 0 else max(flat.rfind("\n", 0, idx), 0)
    end = flat.find(". ", idx)
    end = end + 1 if end >= 0 else len(flat)
    return flat[start:end].strip().replace("**", "")


def _paragraph_with(text: str, marker: str, artifact: str) -> str:
    """The blank-line-delimited paragraph containing marker, flattened.

    Markers are matched on the flattened paragraph so frozen wording that
    wraps across source lines is still found.
    """
    for para in text.split("\n\n"):
        flat = re.sub(r"\s+", " ", para).strip()
        if marker in flat:
            return flat.replace("**", "")
    raise _drift(f"{artifact} lost frozen wording {marker!r}")


def _blockquote_after(text: str, heading: str, artifact: str) -> str:
    idx = text.find(heading)
    _require(idx >= 0, f"{artifact} section {heading!r} missing")
    lines = []
    in_quote = False
    for line in text[idx:].splitlines():
        if line.startswith("> "):
            in_quote = True
            lines.append(line[2:].strip())
        elif in_quote:
            break
    _require(bool(lines), f"{artifact} carries no blockquote under "
                          f"{heading!r}")
    return " ".join(lines)


def _bullets_after(text: str, heading: str, artifact: str) -> list[str]:
    idx = text.find(heading)
    _require(idx >= 0, f"{artifact} section {heading!r} missing")
    bullets: list[str] = []
    started = False
    for line in text[idx + len(heading):].splitlines():
        if line.startswith("## "):
            break
        if line.startswith("- "):
            started = True
            bullets.append(line[2:].strip())
        elif started and line.startswith("  ") and line.strip():
            bullets[-1] += " " + line.strip()
        elif started and not line.strip():
            continue
    _require(bool(bullets), f"{artifact} section {heading!r} carries no "
                            "bullets")
    return [b.replace("**", "") for b in bullets]


# ---------------------------------------------------------------------------
# Per-publication parsers
# ---------------------------------------------------------------------------


def _parse_i0(text: str) -> dict[str, Any]:
    art = I0_PATH.name
    version = _search(r"locked, (i0-v\d+)", text, art).group(1)
    q_idx = text.find("## 1. Research question")
    _require(q_idx >= 0, f"{art} research-question section missing")
    question = re.sub(r"\s+", " ", text[q_idx:].split("\n\n")[1]).strip()
    estimand_def = _sentence_with(
        text, "The primary statistic is", art)
    midpoint = _search(r"MEMP is approximately\s+(0\.5)", text,
                       art).group(1)
    defs_raw = _bullets_after(
        text, "## 15. Falsifiers", art)
    _require(len(defs_raw) == 6,
             f"{art} section 15 does not carry exactly six falsifier "
             "definitions")
    definitions = {}
    for i, bullet in enumerate(defs_raw, start=1):
        key = f"f{i}"
        _require(bullet.lower().startswith(f"f{i} "),
                 f"{art} falsifier definition order drifted at {key}")
        definitions[key] = bullet
    return {"version": version, "frozen_question": question,
            "estimand_definition": estimand_def,
            "ordinary_reference_midpoint": midpoint,
            "falsifier_definitions": definitions}


_I1_FUNNEL_ROW = re.compile(
    r"^\| (\d+d) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| "
    r"\*\*(\d+)\*\* \| (\d+) \| (\w+) \|", re.MULTILINE)


def _parse_i1(text: str) -> dict[str, Any]:
    art = I1_PATH.name
    version = _search(r"Version `(i1-[a-z-]+-v\d+)`", text, art).group(1)
    lanes: dict[str, dict[str, Any]] = {}
    for family in ("FOMC", "OPEC"):
        idx = text.find(f"## {family} lane")
        _require(idx >= 0, f"{art} lane {family} missing")
        nxt = text.find("## ", idx + 4)
        section = text[idx:nxt if nxt > idx else len(text)]
        assets = _search(
            r"- Primary asset `(\w+)`; market benchmark `(\w+)`; sector "
            r"benchmark `(\w+)`", section, art)
        joint = int(_search(r"sessions: \*\*(\d+)\*\*", section,
                            art).group(1))
        era = int(_search(r"era 2018.2025 sessions: \*\*(\d+)\*\*",
                          section, art).group(1))
        study = int(_search(
            r"- Study denominator \(promoted events\): \*\*(\d+)\*\*",
            section, art).group(1))
        basis = _sentence_with(section, "uniformly adjusted", art)
        horizons: dict[str, dict[str, Any]] = {}
        for m in _I1_FUNNEL_ROW.finditer(section):
            horizons[m.group(1)] = {
                "era": int(m.group(2)),
                "estimation_cut": int(m.group(3)),
                "forward_cut": int(m.group(4)),
                "gap_cut": int(m.group(5)),
                "exclusion_cut": int(m.group(6)),
                "eligible": int(m.group(7)),
                "blocks": int(m.group(8)),
                "status": m.group(9),
            }
        _require(sorted(horizons) == sorted(_ALL_HORIZONS),
                 f"{art} lane {family} funnel rows incomplete")
        lane: dict[str, Any] = {
            "primary": assets.group(1), "market_benchmark": assets.group(2),
            "sector_benchmark": assets.group(3), "joint_sessions": joint,
            "era_sessions": era, "study_denominator": study,
            "price_basis_policy": basis, "horizons": horizons,
        }
        if family == "FOMC":
            lane["exclusion_text"] = _sentence_with(
                section, "Exclusion set: the complete", art)
        else:
            reg = _search(
                r"\(`(opec-known-date-exclusion-register@i0-v\d+)`\): "
                r"\*\*(\d+)\*\* calendar dates", section, art)
            anchors = int(_search(
                r"\*\*(\d+)\*\* anchor\s+sessions", section, art).group(1))
            lane["register"] = {
                "name": reg.group(1),
                "calendar_dates": int(reg.group(2)),
                "anchor_sessions": anchors,
                "note": _sentence_with(section,
                                       "contamination-control set", art),
            }
        lanes[family] = lane
    blocks_note = _sentence_with(
        text, "an independent, effective, or degrees-of-freedom", art)
    infeasible_note = _sentence_with(text, "not a data gap", art)
    return {"version": version, "lanes": lanes,
            "blocks_note": blocks_note,
            "fomc_20d_limitation": infeasible_note}


_I2A_ROW = re.compile(
    r"^\| (FOMC|OPEC) \| (event|reference) \| (\d+d) \| (\w+) \| (\d+) \| "
    r"(\d+) \| (\d+) \| (\d+) \| (\d+) \|", re.MULTILINE)


def _parse_i2a(text: str) -> dict[str, Any]:
    art = I2A_PATH.name
    version = _search(r"Contract: `(i2a-[a-z-]+-v\d+)`", text,
                      art).group(1)
    coverage: dict[tuple[str, str, str, str], dict[str, int]] = {}
    for m in _I2A_ROW.finditer(text):
        coverage[(m.group(1), m.group(2), m.group(3), m.group(4))] = {
            "attempted": int(m.group(5)), "available": int(m.group(6)),
            "unavailable": int(m.group(9))}
    _require(len(coverage) == 2 * len(_CELL_IDENTITY),
             f"{art} coverage table incomplete "
             f"(found {len(coverage)} rows)")
    _require("none: every attempted record is available" in text,
             f"{art} zero-unavailable accounting wording missing")
    _require(all(v["attempted"] == v["available"] and v["unavailable"] == 0
                 for v in coverage.values()),
             f"{art} reports unavailable records; contract expectations "
             "drifted")
    # The only canonically recorded reproduction path in the seven
    # publications: I2A's fenced "## Reproduction" block, exposed parsed
    # (never hand-copied), plus the tracked fresh-clone limit.
    repro_block = _search(r"## Reproduction\s*\n+```\n((?:[^\n`][^\n]*\n)+)```",
                          text, art).group(1)
    commands = [line.strip() for line in repro_block.splitlines()
                if line.strip()]
    _require(bool(commands)
             and all(c.startswith("python ") for c in commands),
             f"{art} reproduction commands drifted")
    posture = _sentence_with(
        text, "fresh-clone execution is therefore not claimed", art)
    return {"version": version, "coverage": coverage,
            "reproduction_commands": commands,
            "reproducibility_posture": posture}


_I2B_ROW = re.compile(
    r"^\| (FOMC|OPEC) \| (\d+d) \| (\w+) \| (\d+) \| (\d+) \| ([0-9.]+) "
    r"\| ([0-9.]+) \|", re.MULTILINE)


def _parse_i2b(text: str) -> dict[str, Any]:
    art = I2B_PATH.name
    version = _search(r"Contract: `(i2b-[a-z-]+-v\d+)`", text,
                      art).group(1)
    head = text.split("## Per-event percentile surface", 1)[0]
    rows: list[dict[str, Any]] = []
    for m in _I2B_ROW.finditer(head):
        rows.append({"family": m.group(1), "horizon": m.group(2),
                     "metric": m.group(3), "event_n": int(m.group(4)),
                     "reference_n": int(m.group(5)), "memp": m.group(6),
                     "signed": m.group(7)})
    count = int(_search(r"Exactly \*\*(\d+) primary statistics\*\*", text,
                        art).group(1))
    per_event_rows = int(_search(
        r"Full per-event surface: \*\*(\d+)\*\* rows", text, art).group(1))
    honesty = _sentence_with(
        text, "does not remove multiple-comparison exposure", art)
    _require([tuple((r["family"], r["horizon"], r["metric"]))
              for r in rows] == list(_CELL_IDENTITY),
             f"{art} primary table identities or order drifted")
    _require(count == len(_CELL_IDENTITY),
             f"{art} frozen-count marker disagrees with the manifest")
    return {"version": version, "rows": rows,
            "per_event_rows": per_event_rows,
            "multiplicity_honesty": honesty}


_I2C_A_ROW = re.compile(
    r"^\| (FOMC|OPEC) \| (\d+d) \| (\w+) \| (\d+) \| (\d+) \| ([0-9.]+) "
    r"\| ([0-9.]+) \|")
_PLACEMENT_ROW = re.compile(
    r"^\| (FOMC|OPEC) \| (\d+d) \| (\d+) \| (\d+) \| ([0-9:, ]+) \|")


def _parse_i2c_calibration(text: str) -> dict[str, Any]:
    art = I2C_CALIBRATION_PATH.name
    version = _search(r"Contract: `(i2c-calibration-v\d+)`", text,
                      art).group(1)
    b = int(_search(r"\*\*B = ([\d,]+)\*\*", text,
                    art).group(1).replace(",", ""))
    seed = int(_search(r"fixed seed \*\*(\d+)\*\*", text, art).group(1))
    rows: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = _I2C_A_ROW.match(line)
        if m and m.group(3) in _METRICS:
            rows.append({"family": m.group(1), "horizon": m.group(2),
                         "metric": m.group(3), "event_n": int(m.group(4)),
                         "reference_n": int(m.group(5)),
                         "memp": m.group(6), "calib": m.group(7)})
            continue
        pm = _PLACEMENT_ROW.match(line)
        if pm:
            years = {}
            for pair in pm.group(5).split(","):
                year, n = pair.strip().split(":")
                years[year] = int(n)
            groups.append({"family": pm.group(1), "horizon": pm.group(2),
                           "expected_placements": int(pm.group(3)),
                           "completed_placements": int(pm.group(4)),
                           "per_year_event_counts": years})
    _require([tuple((r["family"], r["horizon"], r["metric"]))
              for r in rows] == list(_CELL_IDENTITY),
             f"{art} calibrated table identities or order drifted")
    _require([(g["family"], g["horizon"]) for g in groups]
             == [(f, h) for f, hs in _FAMILY_HORIZONS for h in hs],
             f"{art} placement reconciliation rows drifted")
    ceiling = _sentence_with(text, "percentile-of-placements only", art)
    method = _paragraph_with(text, "One placement reproduces", art)
    no_failure = _sentence_with(text, "no failure, no replacement", art)
    return {"version": version, "b": b, "seed": seed, "rows": rows,
            "groups": groups, "interpretation_ceiling": ceiling,
            "method": method, "no_failure_statement": no_failure}


_I2C_B_ROW = re.compile(
    r"^\| (FOMC|OPEC) \| (\d+d) \| (\w+) \| ([0-9.]+) \| ([0-9.]+) \| "
    r"(\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| ([0-9.]+) \| "
    r"([+-][0-9.]+) \| (no|yes) \| (inside|outside) \|", re.MULTILINE)
_F4_ROW = re.compile(
    r"^\| (FOMC|OPEC) \| (\d+d) \| ([+-]1|0) \| ([+-]1|0) \| ([+-]1|0) "
    r"\| ([+-]1|0) \| (\d+) \| (\d+) \| (\d+) \|", re.MULTILINE)
_F5_ROW = re.compile(
    r"^\| (FOMC|OPEC) \| (\w+) \| ([+-]1|n/a) \| ([+-]1|n/a) \| "
    r"([+-]1|n/a) \| (yes|no) \|", re.MULTILINE)


def _parse_i2c_falsifiers(text: str) -> dict[str, Any]:
    art = I2C_FALSIFIERS_PATH.name
    version = _search(r"Contract: `(i2c-falsifiers-v\d+)`", text,
                      art).group(1)
    cells: list[dict[str, Any]] = []
    for m in _I2C_B_ROW.finditer(text):
        cells.append({
            "family": m.group(1), "horizon": m.group(2),
            "metric": m.group(3), "memp": m.group(4), "calib": m.group(5),
            "loyo_runs": int(m.group(6)), "loyo_flips": int(m.group(7)),
            "loeo_runs": int(m.group(8)), "loeo_flips": int(m.group(9)),
            "f3_original_n": int(m.group(10)),
            "f3_canonical_n": int(m.group(11)),
            "f3_memp": m.group(12), "f3_change": m.group(13),
            "f3_flip": m.group(14) == "yes",
            "f6_position": m.group(15)})
    _require([tuple((c["family"], c["horizon"], c["metric"]))
              for c in cells] == list(_CELL_IDENTITY),
             f"{art} section-A identities or order drifted")
    f4: list[dict[str, Any]] = []
    for m in _F4_ROW.finditer(text):
        f4.append({"family": m.group(1), "horizon": m.group(2),
                   "signs": {metric: int(m.group(3 + i))
                             for i, metric in enumerate(_METRICS)},
                   "positive": int(m.group(7)), "zero": int(m.group(8)),
                   "negative": int(m.group(9))})
    _require([(r["family"], r["horizon"]) for r in f4]
             == [(f, h) for f, hs in _FAMILY_HORIZONS for h in hs],
             f"{art} F4 rows drifted")
    f5: list[dict[str, Any]] = []
    for m in _F5_ROW.finditer(text):
        signs = {h: (None if m.group(3 + i) == "n/a"
                     else int(m.group(3 + i)))
                 for i, h in enumerate(_ALL_HORIZONS)}
        f5.append({"family": m.group(1), "metric": m.group(2),
                   "signs": signs, "agree": m.group(6) == "yes"})
    _require([(r["family"], r["metric"]) for r in f5]
             == [(f, metric) for f, _hs in _FAMILY_HORIZONS
                 for metric in _METRICS],
             f"{art} F5 rows drifted")
    _require("stand separately" in text,
             f"{art} battery-separation wording missing")
    return {"version": version, "cells": cells, "f4": f4, "f5": f5}


_CLOSEOUT_LOYO_ROW = re.compile(
    r"^\| (FOMC|OPEC) (\d+d) ([^|]+?) \| (\d+) \|", re.MULTILINE)


def _parse_closeout(text: str) -> dict[str, Any]:
    art = CLOSEOUT_PATH.name
    headlines = {
        ("FOMC", "1d"): _blockquote_after(text, "### FOMC 1d", art),
        ("FOMC", "5d"): _blockquote_after(text, "### FOMC 5d", art),
        ("OPEC", "1d"): _blockquote_after(text, "### OPEC 1d", art),
        ("OPEC", "5d"): _blockquote_after(text, "### OPEC 5d", art),
        ("OPEC", "20d"): _blockquote_after(text, "### OPEC 20d", art),
    }
    conclusion = _blockquote_after(text, "## 4. Whole-mission conclusion",
                                   art)
    clarifier = _paragraph_with(
        text, "not a formal hypothesis test", art)
    loyo_idx = text.find("### LOYO (leave-one-year-out)")
    _require(loyo_idx >= 0, f"{art} LOYO synthesis section missing")
    loyo_block = text[loyo_idx:text.find("###", loyo_idx + 4)]
    loyo_cells: dict[tuple[str, str, str], int] = {}
    for m in _CLOSEOUT_LOYO_ROW.finditer(loyo_block):
        display = m.group(3).strip()
        metric = _DISPLAY_METRIC.get(display)
        _require(metric is not None,
                 f"{art} LOYO table carries unknown metric label "
                 f"{display!r}")
        loyo_cells[(m.group(1), m.group(2), metric)] = int(m.group(4))
    loyo_total = _search(r"Total: \*\*`(\d+) / (\d+)`\*\* LOYO", text, art)
    loeo_total = _search(r"Total: \*\*`(\d+) / (\d+)`\*\* LOEO", text, art)
    f3_line = _search(r"`(\d+) / (\d+)` sign flips", text, art)
    f3_reading = _blockquote_after(text, "### F3", art)
    f3_limitation = _sentence_with(text, "not an independence proof", art)
    f6 = _search(r"`(\d+) inside`, `(\d+) outside`", text, art)
    f6_upper = int(_search(r"`(\d+)` are on the \*\*upper\*\* side", text,
                           art).group(1))
    f6_lower = int(_search(r"`(\d+)` are on the \*\*lower\*\* side", text,
                           art).group(1))
    f6_limitation = _sentence_with(
        text, "calibration-position diagnostic", art)
    battery = _sentence_with(text, "stand separately", art)
    knife_edge = _paragraph_with(
        text, "LOEO fragility is concentrated", art)
    signed = _bullets_after(
        text, "## 7. Signed-percentile diagnostic", art)
    _require(len(signed) == 3,
             f"{art} signed-diagnostic disclaimers drifted")
    signed_directional = _sentence_with(
        text, "directional or net-return", art)
    non_claims = _bullets_after(text, "## 8. Permanent non-claims", art)
    _require(len(non_claims) >= 11,
             f"{art} permanent non-claims list drifted "
             f"({len(non_claims)} items)")
    preamble = _sentence_with(text, "later robustness questions", art)
    boundary = _sentence_with(text, "future work", art)
    # The knife-edge caveat is quoted at its structural boundary — the
    # closeout's blank-line-delimited paragraph — never by punctuation-
    # scanning the flattened document, which spliced the preceding
    # section heading and F4/F5 tables into the quoted field and cut the
    # paragraph at its first period.
    f5_caveat = _paragraph_with(
        text, "formal sign agreement here is weak evidence", art)
    # The evidence-chain line must still exist in the closeout; the
    # payload carries an authored restatement with no research number.
    _require("I0 protocol" in text,
             f"{art} evidence-chain line missing")
    chain = ("I0 protocol -> I1 candidate universe -> I2A symmetric "
             "response substrate -> I2B frozen MEMP family -> I2C-A "
             "era-matched calibration -> I2C-B falsifier battery -> "
             "closeout")
    return {"headlines": headlines, "conclusion": conclusion,
            "clarifier": clarifier, "loyo_cells": loyo_cells,
            "loyo_total": (int(loyo_total.group(1)),
                           int(loyo_total.group(2))),
            "loeo_total": (int(loeo_total.group(1)),
                           int(loeo_total.group(2))),
            "f3_total": (int(f3_line.group(1)), int(f3_line.group(2))),
            "f3_reading": f3_reading, "f3_limitation": f3_limitation,
            "f6_inside": int(f6.group(1)), "f6_outside": int(f6.group(2)),
            "f6_upper": f6_upper, "f6_lower": f6_lower,
            "f6_limitation": f6_limitation,
            "battery_disclosure": battery,
            "knife_edge_explanation": knife_edge,
            "signed_disclaimers": signed,
            "signed_directional": signed_directional,
            "non_claims": non_claims, "limits_preamble": preamble,
            "boundary": boundary, "f5_caveat": f5_caveat,
            "chain": chain}


# ---------------------------------------------------------------------------
# Contract builder (parse -> reconcile -> assemble; never partial)
# ---------------------------------------------------------------------------


def _provenance_entry(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"artifact": f"stats/{path.name}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data)}


def build_mission_i_evidence_summary(
        *,
        i0_path: Path | str = I0_PATH,
        i1_path: Path | str = I1_PATH,
        i2a_path: Path | str = I2A_PATH,
        i2b_path: Path | str = I2B_PATH,
        i2c_calibration_path: Path | str = I2C_CALIBRATION_PATH,
        i2c_falsifiers_path: Path | str = I2C_FALSIFIERS_PATH,
        closeout_path: Path | str = CLOSEOUT_PATH,
) -> dict[str, Any]:
    """The published Mission I record as a structured, read-only contract.

    Raises ``ValueError`` on any artifact drift; the complete payload is
    validated before anything is returned (no partial record).
    """
    paths = {k: Path(v) for k, v in (
        ("i0_protocol", i0_path), ("i1_universe", i1_path),
        ("i2a_substrate", i2a_path), ("i2b_memp", i2b_path),
        ("i2c_calibration", i2c_calibration_path),
        ("i2c_falsifiers", i2c_falsifiers_path),
        ("closeout", closeout_path))}
    i0 = _parse_i0(_read(paths["i0_protocol"]))
    i1 = _parse_i1(_read(paths["i1_universe"]))
    i2a = _parse_i2a(_read(paths["i2a_substrate"]))
    i2b = _parse_i2b(_read(paths["i2b_memp"]))
    cal = _parse_i2c_calibration(_read(paths["i2c_calibration"]))
    fal = _parse_i2c_falsifiers(_read(paths["i2c_falsifiers"]))
    close = _parse_closeout(_read(paths["closeout"]))

    # ---- Cross-file reconciliation (published values only) ---------------
    for i, identity in enumerate(_CELL_IDENTITY):
        family, horizon, metric = identity
        b_row, a_row, f_row = i2b["rows"][i], cal["rows"][i], \
            fal["cells"][i]
        _require(b_row["memp"] == a_row["memp"] == f_row["memp"],
                 f"MEMP copies disagree for {family}|{horizon}|{metric}")
        _require(a_row["calib"] == f_row["calib"],
                 "calibration copies disagree for "
                 f"{family}|{horizon}|{metric}")
        _require(b_row["event_n"] == a_row["event_n"],
                 f"event-N copies disagree for {family}|{horizon}")
        _require(b_row["reference_n"] == a_row["reference_n"]
                 == f_row["f3_original_n"],
                 f"reference-N copies disagree for {family}|{horizon}")
        cov_e = i2a["coverage"][(family, "event", horizon, metric)]
        cov_r = i2a["coverage"][(family, "reference", horizon, metric)]
        _require(cov_e["available"] == b_row["event_n"],
                 f"I2A event coverage disagrees for {family}|{horizon}")
        _require(cov_r["available"] == b_row["reference_n"],
                 f"I2A reference coverage disagrees for "
                 f"{family}|{horizon}")
        lane_h = i1["lanes"][family]["horizons"][horizon]
        _require(lane_h["eligible"] == b_row["reference_n"],
                 f"I1 eligible count disagrees for {family}|{horizon}")
        _require(i1["lanes"][family]["study_denominator"]
                 == b_row["event_n"],
                 f"I1 study denominator disagrees for {family}")
        sign = (1 if float(b_row["memp"]) > 0.5
                else -1 if float(b_row["memp"]) < 0.5 else 0)
        f4_row = next(r for r in fal["f4"] if r["family"] == family
                      and r["horizon"] == horizon)
        _require(f4_row["signs"][metric] == sign,
                 f"F4 sign disagrees with published MEMP for "
                 f"{family}|{horizon}|{metric}")

    loyo_flips = sum(c["loyo_flips"] for c in fal["cells"])
    loyo_runs = sum(c["loyo_runs"] for c in fal["cells"])
    loeo_flips = sum(c["loeo_flips"] for c in fal["cells"])
    loeo_runs = sum(c["loeo_runs"] for c in fal["cells"])
    _require((loyo_flips, loyo_runs) == close["loyo_total"],
             "closeout LOYO totals disagree with per-cell counts")
    _require((loeo_flips, loeo_runs) == close["loeo_total"],
             "closeout LOEO totals disagree with per-cell counts")
    _require(loeo_runs == i2b["per_event_rows"],
             "per-event row count disagrees with LOEO run total")
    f3_flip_count = sum(1 for c in fal["cells"] if c["f3_flip"])
    _require((f3_flip_count, len(fal["cells"])) == close["f3_total"],
             "closeout F3 totals disagree with per-cell flags")
    inside = sum(1 for c in fal["cells"] if c["f6_position"] == "inside")
    outside = len(fal["cells"]) - inside
    _require(inside == close["f6_inside"]
             and outside == close["f6_outside"],
             "closeout F6 totals disagree with per-cell positions")
    _require(close["f6_upper"] + close["f6_lower"] == outside,
             "closeout F6 upper/lower split does not sum to outside")
    published_loyo = {(c["family"], c["horizon"], c["metric"]):
                      c["loyo_flips"] for c in fal["cells"]
                      if c["loyo_flips"] > 0}
    _require(published_loyo == close["loyo_cells"],
             "closeout LOYO-affected cells disagree with per-cell counts")
    _require((i1["lanes"]["FOMC"]["primary"],
              i1["lanes"]["OPEC"]["primary"]) == _FAMILY_ASSETS_EXPECTED,
             "family primary-asset identities drifted")
    fomc_20d = i1["lanes"]["FOMC"]["horizons"]["20d"]
    _require(fomc_20d["eligible"] == 0
             and fomc_20d["status"] == "structurally_infeasible",
             "FOMC 20d structural-infeasibility row drifted")

    # ---- Assemble ---------------------------------------------------------
    def _lane_payload(family: str) -> dict[str, Any]:
        lane = i1["lanes"][family]
        horizons = []
        for h in _ALL_HORIZONS:
            row = lane["horizons"][h]
            feasible = row["status"] == "feasible"
            horizons.append({
                "horizon": h,
                "funnel": {"era": row["era"],
                           "estimation_cut": row["estimation_cut"],
                           "forward_cut": row["forward_cut"],
                           "gap_cut": row["gap_cut"],
                           "exclusion_cut": row["exclusion_cut"]},
                "reference_n_attempted": row["eligible"],
                "reference_n_available": row["eligible"],
                "non_overlapping_reference_n": row["blocks"],
                "status": row["status"],
                "limitation": (None if feasible
                               else i1["fomc_20d_limitation"]),
            })
        payload: dict[str, Any] = {
            "family": family,
            "primary": lane["primary"],
            "market_benchmark": lane["market_benchmark"],
            "sector_benchmark": lane["sector_benchmark"],
            "study_event_n_attempted": lane["study_denominator"],
            "study_event_n_available": lane["study_denominator"],
            "joint_sessions": lane["joint_sessions"],
            "era_sessions": lane["era_sessions"],
            "price_basis_policy": lane["price_basis_policy"],
            "horizons": horizons,
        }
        if family == "FOMC":
            payload["exclusion"] = {"description": lane["exclusion_text"]}
        else:
            payload["exclusion"] = {"register": lane["register"]}
        return payload

    cells = []
    for i, (family, horizon, metric) in enumerate(_CELL_IDENTITY):
        b_row, a_row, f_row = i2b["rows"][i], cal["rows"][i], \
            fal["cells"][i]
        f4_row = next(r for r in fal["f4"] if r["family"] == family
                      and r["horizon"] == horizon)
        cells.append({
            "cell": i + 1,
            "cell_key": f"{family}|{horizon}|{metric}",
            "family": family,
            "horizon": horizon,
            "metric": metric,
            "event_n_attempted": b_row["event_n"],
            "event_n_available": b_row["event_n"],
            "reference_n_attempted": b_row["reference_n"],
            "reference_n_available": b_row["reference_n"],
            "memp": b_row["memp"],
            "signed_percentile_median": b_row["signed"],
            "calibration_percentile": a_row["calib"],
            "state": {
                "memp_direction":
                    _DIRECTION_LABEL[f4_row["signs"][metric]],
                "f6_position": f_row["f6_position"],
            },
            "f1_loyo": {"runs": f_row["loyo_runs"],
                        "flips": f_row["loyo_flips"]},
            "f2_loeo": {"runs": f_row["loeo_runs"],
                        "flips": f_row["loeo_flips"]},
            "f3_overlap_decimation": {
                "original_reference_n": f_row["f3_original_n"],
                "canonical_reference_n": f_row["f3_canonical_n"],
                "decimated_memp": f_row["f3_memp"],
                "change": f_row["f3_change"],
                "sign_flip": f_row["f3_flip"],
            },
        })

    knife = next(c for c in cells
                 if (c["family"], c["horizon"], c["metric"])
                 == ("FOMC", "5d", "raw_return"))
    loyo_affected = [
        {"cell_key": f"{family}|{horizon}|{metric}", "flips": flips,
         "of": next(c["f1_loyo"]["runs"] for c in cells
                    if c["cell_key"] == f"{family}|{horizon}|{metric}")}
        for (family, horizon, metric), flips
        in sorted(close["loyo_cells"].items(),
                  key=lambda kv: _CELL_IDENTITY.index(kv[0]))]

    return {
        "contract_version": CONTRACT_VERSION,
        "provenance": {
            "sources": {k: _provenance_entry(p) for k, p in paths.items()},
            "publication_versions": {
                "i0_protocol": i0["version"],
                "i1_universe": i1["version"],
                "i2a_substrate": i2a["version"],
                "i2b_memp": i2b["version"],
                "i2c_calibration": cal["version"],
                "i2c_falsifiers": fal["version"],
            },
            "publication_chain": close["chain"],
            "no_recompute_statement": (
                "This endpoint exposes published results and computes no "
                "research statistic: no percentile, no median, no "
                "calibration, no placement draw, and no falsifier "
                "perturbation; repeated copies across publications are "
                "reconciled, never re-derived."),
            # Canonically recorded reproduction path (I2A "## Reproduction",
            # parsed) with its tracked fresh-clone limit; computation dates
            # and execution commits are recorded in NO Mission I publication
            # and are stated as null rather than inferred from the current
            # checkout.
            "reproduction": {
                "commands": i2a["reproduction_commands"],
                "reproducibility_limits": i2a["reproducibility_posture"],
                "source": f"stats/{paths['i2a_substrate'].name}",
            },
            "computation_dates": None,
            "execution_commits": None,
        },
        "constitution": {
            "protocol_version": i0["version"],
            "frozen_question": i0["frozen_question"],
            "estimand": {
                "name": "MEMP",
                "definition": i0["estimand_definition"],
                "ordinary_reference_midpoint":
                    i0["ordinary_reference_midpoint"],
            },
            "evidence_class": {"descriptive": True, "comparative": True,
                               "frozen_before_outcome_comparison": True},
            "primary_cell_count": len(_CELL_IDENTITY),
            "family_pooling_prohibition": (
                "the two families keep entirely separate ledgers; their "
                "denominators, exclusion sets, and funnels are never "
                "pooled"),
            "signed_percentile_disclosure": {
                "status": "subordinate descriptive context",
                "disclaimers": close["signed_disclaimers"]
                + [close["signed_directional"]],
            },
        },
        "universe": {
            "families": [_lane_payload("FOMC"), _lane_payload("OPEC")],
            "blocks_note": i1["blocks_note"],
        },
        "primary_cells": cells,
        "calibration": {
            "placements_per_group": cal["b"],
            "seed": cal["seed"],
            "groups": cal["groups"],
            "method": cal["method"],
            "no_failure_statement": cal["no_failure_statement"],
            "interpretation_ceiling": cal["interpretation_ceiling"],
        },
        "falsifiers": {
            "definitions": i0["falsifier_definitions"],
            "battery_disclosure": close["battery_disclosure"],
            "f1_loyo": {"runs_total": close["loyo_total"][1],
                        "flips_total": close["loyo_total"][0],
                        "affected_cells": loyo_affected},
            "f2_loeo": {"runs_total": close["loeo_total"][1],
                        "flips_total": close["loeo_total"][0],
                        "affected_cells": [
                            {"cell_key": c["cell_key"],
                             "flips": c["f2_loeo"]["flips"],
                             "of": c["f2_loeo"]["runs"]}
                            for c in cells
                            if c["f2_loeo"]["flips"] > 0],
                        "knife_edge_explanation":
                            close["knife_edge_explanation"]},
            "f3_overlap_decimation": {
                "sign_flips": close["f3_total"][0],
                "of_cells": close["f3_total"][1],
                "reading": close["f3_reading"],
                "limitation": close["f3_limitation"]},
            "f4_cross_metric": fal["f4"],
            "f5_cross_horizon": [
                dict(r, caveat=(close["f5_caveat"]
                                if r["family"] == "FOMC"
                                and r["metric"] == "raw_return"
                                else None))
                for r in fal["f5"]],
            "f6_calibration_position": {
                "inside": close["f6_inside"],
                "outside": close["f6_outside"],
                "outside_upper": close["f6_upper"],
                "outside_lower": close["f6_lower"],
                "limitation": close["f6_limitation"]},
        },
        "family_horizon_readout": [
            {"family": family, "horizon": horizon,
             "headline": close["headlines"][(family, horizon)]}
            for family, horizons in _FAMILY_HORIZONS
            for horizon in horizons],
        "fragility": {
            "knife_edge": {
                "cell_key": knife["cell_key"],
                "memp": knife["memp"],
                "calibration_percentile": knife["calibration_percentile"],
                "f1_loyo": knife["f1_loyo"],
                "f2_loeo": knife["f2_loeo"],
                "explanation": close["knife_edge_explanation"],
            },
            "loyo_affected_cells": loyo_affected,
        },
        "whole_mission_conclusion": {
            "statement": close["conclusion"],
            "clarifier": close["clarifier"],
        },
        "unresolved_or_limits": [
            close["limits_preamble"],
            close["boundary"],
            i2b["multiplicity_honesty"],
        ],
        "non_claims": close["non_claims"],
    }
