"""G3A mechanical-eligibility grinder (Mission G, g0-v1).

Turns the 97 identity-valid historical candidates (65 FOMC frame-complete +
32 OPEC designed-reservoir) into an OUTCOME-BLIND mechanical-eligibility
funnel under two FROZEN, family-level transmission lenses.

Frozen mapping (``g3-transmission-map-v1``)
-------------------------------------------
* FOMC family:  primary ``KRE``, market ``SPY``, sector ``XLF``
* OPEC family:  primary ``XOP``, market ``SPY``, sector ``XLE``

The mapping is a pure function of the candidate's FAMILY. It never depends on
the individual event, its date, or remembered historical importance; there is
no per-event override path. A future mapping change requires a version bump
and a full re-run across the family (G0 governance).

Reuse, never reimplement
------------------------
The canonical (market-relative) and sector-relative event-study eligibility
stages call the SHIPPED gate
``event_study_validation.build_event_study_validation`` under its default
canonical basis policy (F3): matched adjusted/adjusted preferred, matched
raw/raw as the only disclosed fallback, and NO cross-basis pair. This module
contains no second event-study or basis implementation. The gate reads a
``price_cache`` table through ``db.DB_FILE``; the grinder rebinds that pointer
at a gitignored G3 price cache, so neither ``events.db`` nor the root
``price_cache.db`` is read or mutated.

Outcome-blindness firewall
--------------------------
The gate mechanically computes AR/SAR/CAR as a side effect of the availability
check. Before the G4 freeze this module persists and displays ONLY mechanical
status and audit metadata (mapped assets, basis used, availability flags,
failure codes) - never a return, sign, direction, magnitude, or outcome
label. The persisted-field whitelist is enforced by tests.

Usage (read-only unless --fetch)::

    python scripts/g3_mechanical_grinder.py --probe-sources   # per-ticker health
    python scripts/g3_mechanical_grinder.py --fetch           # build g3 price cache
    python scripts/g3_mechanical_grinder.py --grind [--json]  # 97-candidate funnel
    python scripts/g3_mechanical_grinder.py --emit-report     # write tracked report
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import g_state_acquisition as gsa  # noqa: E402
import db as _db  # noqa: E402
import event_study_validation as esv  # noqa: E402

MAPPING_VERSION = "g3-transmission-map-v1"

REPORT_PATH = ROOT / "stats" / "G3_MECHANICAL_ELIGIBILITY.md"


# ---------------------------------------------------------------------------
# Frozen family-level transmission mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransmissionLens:
    """One frozen, family-level second-order transmission lens."""
    family: str
    family_label: str
    primary: str
    market: str
    sector: str
    interpretation: str
    claim_ceiling: str


TRANSMISSION_MAP: dict[str, TransmissionLens] = {
    "fomc": TransmissionLens(
        family="fomc",
        family_label="FOMC",
        primary="KRE",
        market="SPY",
        sector="XLF",
        interpretation=("policy decision -> policy path / funding and curve "
                        "conditions -> regional-bank equities"),
        claim_ceiling=(
            "KRE is one predeclared second-order equity transmission lens for "
            "FOMC decisions. It is not the complete market reaction to "
            "monetary policy and does not imply every FOMC decision should "
            "move regional banks in one direction."),
    ),
    "opec": TransmissionLens(
        family="opec",
        family_label="OPEC production-policy",
        primary="XOP",
        market="SPY",
        sector="XLE",
        interpretation=("collective production policy -> crude supply "
                        "expectations -> producer cash flows -> "
                        "exploration-and-production equities"),
        claim_ceiling=(
            "XOP is one predeclared producer-equity transmission lens for "
            "collective OPEC/OPEC+ production policy. It is not a complete "
            "measure of oil-market consequences."),
    ),
}

# Lane is the family authority (the 65/32 partition key); the id prefix is a
# cross-check, so a mislabeled row fails loudly instead of being reclassified.
_LANE_TO_FAMILY = {
    "frame_complete_historical": "fomc",
    "designed_contrast": "opec",
}
_FAMILY_ID_PREFIX = {"fomc": "fomc-", "opec": "opec-"}


def candidate_family(candidate: Mapping[str, Any]) -> str:
    """Resolve a candidate's frozen family, or raise ValueError.

    Fails loudly on an unknown lane (no mapping / unknown family) and on an
    id whose prefix disagrees with the lane's family (a mislabeled row).
    """
    lane = candidate.get("lane")
    family = _LANE_TO_FAMILY.get(lane)
    if family is None:
        raise ValueError(f"unknown family for lane {lane!r} "
                         f"(candidate {candidate.get('candidate_id')!r})")
    cid = candidate.get("candidate_id") or ""
    prefix = _FAMILY_ID_PREFIX[family]
    if not cid.startswith(prefix):
        raise ValueError(
            f"id/lane family mismatch: id {cid!r} does not start with "
            f"{prefix!r} expected for family {family!r}")
    return family


def map_candidate(candidate: Mapping[str, Any]) -> TransmissionLens:
    """Return the frozen transmission lens for a candidate's family.

    Pure function of the family alone: no override parameter, no dependence
    on the individual event or its date.
    """
    return TRANSMISSION_MAP[candidate_family(candidate)]


def map_all(candidates: Sequence[Mapping[str, Any]]) -> dict[str, TransmissionLens]:
    """Map every candidate by id, raising on an unknown family, an id/lane
    mismatch, or a duplicate id that would receive conflicting mappings."""
    out: dict[str, TransmissionLens] = {}
    for cand in candidates:
        cid = cand.get("candidate_id") or ""
        lens = map_candidate(cand)
        if cid in out and out[cid] != lens:
            raise ValueError(f"duplicate id {cid!r} with conflicting mapping")
        out[cid] = lens
    return out


def load_candidates() -> list[dict[str, str]]:
    """The 97 identity-valid candidates from the two G1 ledgers (deterministic)."""
    return (gsa.parse_g1a_candidates(str(gsa.G1A_PATH))
            + gsa.parse_g1b_candidates(str(gsa.G1B_PATH)))


def reconcile(candidates: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Input-gate reconciliation. Raises loudly on a duplicate id, an unknown
    family, or an id/lane mismatch; otherwise returns lane counts."""
    ids = [c.get("candidate_id") or "" for c in candidates]
    total = len(ids)
    unique = len(set(ids))
    map_all(candidates)  # raises on unknown family / mismatch / conflict
    if unique != total:
        raise ValueError(f"duplicate candidate ids: {total} rows, "
                         f"{unique} unique")
    g1a = sum(1 for c in candidates
              if c.get("lane") == "frame_complete_historical")
    g1b = sum(1 for c in candidates if c.get("lane") == "designed_contrast")
    return {"g1a": g1a, "g1b": g1b, "total": total, "unique": unique}


# ---------------------------------------------------------------------------
# Mechanical grinder (outcome-blind): 7 stages, multi-code failure ledger
# ---------------------------------------------------------------------------

# The seven mechanical stages, in funnel order (stage 1 first).
_STAGE_ORDER = (
    "identity_valid",
    "mapped",
    "primary_price_available",
    "market_benchmark_available",
    "canonical_event_study_available",
    "sector_benchmark_available",
    "sector_relative_available",
)
STAGE_FLAGS = frozenset(_STAGE_ORDER)

# The full failure-code vocabulary. ``mapping_missing`` is enumerated for the
# ledger but is guaranteed zero in a real run: the input gate raises loudly on
# an unknown family long before the grinder is reached.
FAILURE_CODES = (
    "mapping_missing",
    "primary_price_missing",
    "market_benchmark_missing",
    "canonical_event_study_unavailable",
    "sector_benchmark_missing",
    "sector_relative_unavailable",
)

# Whitelisted persisted-row fields (outcome-blindness firewall): mechanical
# status and audit metadata ONLY - never a return, sign, magnitude, or label.
G3_ROW_FIELDS = frozenset({
    "candidate_id", "lane", "family", "family_label", "event_date",
    "primary_asset", "market_benchmark", "sector_benchmark",
    "canonical_basis", "availability", "failure_codes", "mapping_version",
})


def _cached_dates(ticker: str) -> set[str]:
    """Distinct cached price dates for a ticker (either auto_adjust basis).

    Read-only single SELECT through ``db.connect_db()`` (the pointer tests and
    the grinder rebind at a gitignored G3 cache). Any DB error - missing
    table, unreachable file - degrades to an empty set.
    """
    out: set[str] = set()
    try:
        conn = _db.connect_db()
    except sqlite3.Error:
        return out
    try:
        rows = conn.execute(
            "SELECT DISTINCT date FROM price_cache "
            "WHERE ticker = ? AND close IS NOT NULL",
            (ticker.upper(),),
        ).fetchall()
    except sqlite3.Error:
        return out
    finally:
        conn.close()
    for row in rows:
        d = row[0]
        if isinstance(d, str):
            out.add(d[:10])
    return out


def _basis_label(es: Mapping[str, Any]) -> str:
    """Reduce the gate payload to the canonical basis actually used.

    Under the default (canonical) policy the gate only ever returns a MATCHED
    pair: adjusted/adjusted -> ``"adjusted"``, or the disclosed raw/raw
    fallback -> ``"raw_fallback"``. A cross pair is structurally impossible in
    default mode; ``"cross"`` is surfaced only so a policy violation would be
    visible rather than silently absorbed.
    """
    aab = es.get("auto_adjust_basis") or {}
    asset, bench = aab.get("asset"), aab.get("benchmark")
    if asset and bench:
        return "adjusted"
    if es.get("basis_fallback") == "matched_raw_fallback":
        return "raw_fallback"
    if asset == bench:  # defensive: matched raw without the disclosure flag
        return "raw_fallback"
    return "cross"


def grind_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the seven mechanical eligibility stages for one candidate.

    Reuses the SHIPPED gate ``build_event_study_validation`` twice - once vs
    the market benchmark (canonical, stage 5) and once vs the sector benchmark
    (sector-relative, stage 7) - under the default canonical basis policy. The
    two layers are INDEPENDENT: a missing sector-relative layer never implies a
    canonical failure. Returns only whitelisted, outcome-blind fields; all
    applicable failure codes are captured, not just the first.
    """
    lens = map_candidate(candidate)  # input-gate guarantee: always mapped
    cid = candidate.get("candidate_id") or ""
    ev = candidate.get("event_date") or ""
    lane = candidate.get("lane") or ""
    event = {"event_date": ev, "market_tickers": [{"symbol": lens.primary}]}

    availability = {flag: False for flag in _STAGE_ORDER}
    codes: list[str] = []

    availability["identity_valid"] = bool(cid and ev)
    availability["mapped"] = True

    prim = _cached_dates(lens.primary)
    availability["primary_price_available"] = bool(prim)
    if not prim:
        codes.append("primary_price_missing")

    mkt = _cached_dates(lens.market)
    availability["market_benchmark_available"] = bool(mkt)
    if not mkt:
        codes.append("market_benchmark_missing")

    es = esv.build_event_study_validation(event, benchmark_ticker=lens.market)
    canonical_ok = es.get("status") == esv.STATUS_AVAILABLE
    availability["canonical_event_study_available"] = canonical_ok
    canonical_basis = _basis_label(es) if canonical_ok else None
    if not canonical_ok:
        codes.append("canonical_event_study_unavailable")

    sec = _cached_dates(lens.sector)
    availability["sector_benchmark_available"] = bool(sec)
    if not sec:
        codes.append("sector_benchmark_missing")

    es_sec = esv.build_event_study_validation(event,
                                              benchmark_ticker=lens.sector)
    sector_ok = es_sec.get("status") == esv.STATUS_AVAILABLE
    availability["sector_relative_available"] = sector_ok
    if not sector_ok:
        codes.append("sector_relative_unavailable")

    return {
        "candidate_id": cid,
        "lane": lane,
        "family": lens.family,
        "family_label": lens.family_label,
        "event_date": ev,
        "primary_asset": lens.primary,
        "market_benchmark": lens.market,
        "sector_benchmark": lens.sector,
        "canonical_basis": canonical_basis,
        "availability": availability,
        "failure_codes": codes,
        "mapping_version": MAPPING_VERSION,
    }


# ---------------------------------------------------------------------------
# Aggregation (pure)
# ---------------------------------------------------------------------------

# The report's 5-node monotone funnel (a strict subset chain). Presence of the
# market and sector benchmarks folds into the canonical / sector-relative
# availability nodes; the independent per-stage flags and failure codes keep
# the honest partial picture in the failure-composition section.
FUNNEL_NODES = (
    "identity_valid",
    "mapped",
    "primary_price_available",
    "canonical_event_study_available",
    "sector_relative_available",
)


def _funnel_bools(row: Mapping[str, Any]) -> list[bool]:
    a = row["availability"]
    n1 = bool(a["identity_valid"])
    n2 = n1 and bool(a["mapped"])
    n3 = n2 and bool(a["primary_price_available"])
    n4 = n3 and bool(a["canonical_event_study_available"])
    n5 = n4 and bool(a["sector_relative_available"])
    return [n1, n2, n3, n4, n5]


def _accumulate(counts: list[int], bools: list[bool]) -> None:
    for i, b in enumerate(bools):
        if b:
            counts[i] += 1


def _year_counts(dates: set[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in dates:
        out[d[:4]] = out.get(d[:4], 0) + 1
    return dict(sorted(out.items()))


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate grinder rows into the outcome-blind funnel/failure/basis/date
    structure. Pure; no response value is read (only ``canonical_basis`` labels,
    availability flags, and failure codes)."""
    total = [0] * 5
    by_lane: dict[str, list[int]] = {}
    by_family: dict[str, list[int]] = {}
    by_year: dict[str, list[int]] = {}
    by_code: dict[str, int] = {c: 0 for c in FAILURE_CODES}
    multi = 0
    fail_by_lane: dict[str, dict[str, int]] = {}
    fail_by_year: dict[str, dict[str, int]] = {}
    fail_by_family: dict[str, dict[str, int]] = {}
    basis = {"adjusted": 0, "raw_fallback": 0, "unavailable": 0, "cross": 0}
    entering: set[str] = set()
    surviving: set[str] = set()

    for row in rows:
        lane, fam = row["lane"], row["family"]
        yr = (row["event_date"] or "")[:4]
        bools = _funnel_bools(row)
        _accumulate(total, bools)
        _accumulate(by_lane.setdefault(lane, [0] * 5), bools)
        _accumulate(by_family.setdefault(fam, [0] * 5), bools)
        _accumulate(by_year.setdefault(yr, [0] * 5), bools)

        cb = row["canonical_basis"]
        if cb in ("adjusted", "raw_fallback", "cross"):
            basis[cb] += 1
        else:
            basis["unavailable"] += 1

        codes = row["failure_codes"]
        for c in codes:
            by_code[c] = by_code.get(c, 0) + 1
            fail_by_lane.setdefault(lane, {})[c] = \
                fail_by_lane.setdefault(lane, {}).get(c, 0) + 1
            fail_by_year.setdefault(yr, {})[c] = \
                fail_by_year.setdefault(yr, {}).get(c, 0) + 1
            fail_by_family.setdefault(fam, {})[c] = \
                fail_by_family.setdefault(fam, {}).get(c, 0) + 1
        if len(codes) > 1:
            multi += 1

        d = row["event_date"]
        if d:
            entering.add(d)
            if row["availability"]["canonical_event_study_available"]:
                surviving.add(d)

    return {
        "n": len(rows),
        "funnel": {
            "nodes": list(FUNNEL_NODES),
            "total": total,
            "by_lane": dict(sorted(by_lane.items())),
            "by_family": dict(sorted(by_family.items())),
            "by_year": dict(sorted(by_year.items())),
        },
        "failure": {
            "by_code": by_code,
            "multi_failure": multi,
            "by_lane": dict(sorted(fail_by_lane.items())),
            "by_year": dict(sorted(fail_by_year.items())),
            "by_family": dict(sorted(fail_by_family.items())),
        },
        "basis": basis,
        "dates": {
            "entering_unique": len(entering),
            "surviving_unique": len(surviving),
            "entering_by_year": _year_counts(entering),
            "surviving_by_year": _year_counts(surviving),
        },
        "mapping_version": MAPPING_VERSION,
    }


# ---------------------------------------------------------------------------
# Deterministic report render (timestamp-free except cache retrieval stamp)
# ---------------------------------------------------------------------------


def _funnel_table(nodes: Sequence[str], counts: list[int]) -> list[str]:
    short = {
        "identity_valid": "identity-valid",
        "mapped": "mapped",
        "primary_price_available": "primary-price available",
        "canonical_event_study_available": "canonical event-study available",
        "sector_relative_available": "sector-relative available",
    }
    return [f"- {short[n]}: {c}" for n, c in zip(nodes, counts)]


def render_report(summary: Mapping[str, Any], *,
                  cache_meta: Mapping[str, Any],
                  cache_sha256: Optional[str]) -> str:
    """Deterministic markdown for the tracked G3 eligibility report.

    Carries no generation timestamp - only the price cache's retrieval stamp -
    so the report regenerates byte-identically from a fixed cache.
    """
    nodes = summary["funnel"]["nodes"]
    f = summary["funnel"]
    fail = summary["failure"]
    basis = summary["basis"]
    dates = summary["dates"]
    retrieved = cache_meta.get("retrieved_at")

    L: list[str] = [
        "# G3 mechanical eligibility (Mission G, g0-v1)",
        "",
        "Status: G3A mechanical-eligibility funnel. This slice turns the 97 "
        "identity-valid historical candidates (65 FOMC frame-complete + 32 "
        "OPEC designed-reservoir) into an OUTCOME-BLIND eligibility funnel "
        "under two frozen, family-level transmission lenses. It reuses the "
        "shipped event-study gate and canonical basis policy; it computes no "
        "persisted outcome, creates no state tag, promotes no candidate, and "
        "mutates neither `events.db` nor the root `price_cache.db`. Prices "
        "live only in a gitignored local cache "
        "(`g_state_cache/g3_price_cache.db`).",
        "",
        "## 1. Mapping contract (frozen, family-level)",
        "",
        f"Mapping version: `{MAPPING_VERSION}`. Mapping is a pure function of "
        "the candidate FAMILY. No candidate receives an asset because of "
        "remembered historical importance; no response value influences the "
        "mapping; there is no event-specific override rule. A future mapping "
        "change requires a version bump and a full re-run across the family.",
        "",
        "| family | primary | market | sector | transmission interpretation |",
        "|---|---|---|---|---|",
    ]
    for key in ("fomc", "opec"):
        lens = TRANSMISSION_MAP[key]
        L.append(f"| {lens.family_label} | `{lens.primary}` | "
                 f"`{lens.market}` | `{lens.sector}` | {lens.interpretation} |")
    L += [
        "",
        "Claim ceilings (predeclared, bounded):",
        "",
        f"- FOMC / `{TRANSMISSION_MAP['fomc'].primary}`: "
        f"{TRANSMISSION_MAP['fomc'].claim_ceiling}",
        f"- OPEC / `{TRANSMISSION_MAP['opec'].primary}`: "
        f"{TRANSMISSION_MAP['opec'].claim_ceiling}",
        "",
        "The canonical (market-relative) event study reuses "
        "`event_study_validation.build_event_study_validation` under its "
        "default basis policy: matched adjusted/adjusted preferred, matched "
        "raw/raw as the only disclosed fallback, never a cross-basis pair. The "
        "sector-relative layer reuses the SAME gate with the family sector ETF "
        "as the benchmark. No second event-study or basis implementation "
        "exists in this slice.",
        "",
        "## 2. Funnel (all 97)",
        "",
        "Monotone eligibility chain (each node a subset of the previous):",
        "",
    ]
    L += _funnel_table(nodes, f["total"])
    L += ["", "### By lane", "",
          "| lane | " + " | ".join(_funnel_headers(nodes)) + " |",
          "|" + "---|" * (len(nodes) + 1)]
    for lane, counts in f["by_lane"].items():
        L.append(f"| {lane} | " + " | ".join(str(c) for c in counts) + " |")
    L += ["", "### By family", "",
          "| family | " + " | ".join(_funnel_headers(nodes)) + " |",
          "|" + "---|" * (len(nodes) + 1)]
    for fam, counts in f["by_family"].items():
        L.append(f"| {fam} | " + " | ".join(str(c) for c in counts) + " |")
    L += ["", "### By calendar year", "",
          "| year | " + " | ".join(_funnel_headers(nodes)) + " |",
          "|" + "---|" * (len(nodes) + 1)]
    for yr, counts in f["by_year"].items():
        L.append(f"| {yr} | " + " | ".join(str(c) for c in counts) + " |")

    L += [
        "",
        "## 3. Failure composition",
        "",
        "A candidate may carry more than one mechanical failure; all "
        "applicable codes are captured. A missing sector-relative layer is "
        "NOT counted as a complete event-study failure - the two layers are "
        "evaluated independently. This is structural accounting, not a causal "
        "claim about attrition.",
        "",
        "| failure code | candidates |",
        "|---|---|",
    ]
    for code in FAILURE_CODES:
        L.append(f"| {code} | {fail['by_code'].get(code, 0)} |")
    L += ["", f"- candidates with more than one failure code: "
          f"{fail['multi_failure']}"]
    L += ["", "Failure codes by lane:", ""]
    L += _nested_code_lines(fail["by_lane"])
    L += ["", "Failure codes by family:", ""]
    L += _nested_code_lines(fail["by_family"])
    L += ["", "Failure codes by calendar year:", ""]
    L += _nested_code_lines(fail["by_year"])

    L += [
        "",
        "## 4. Basis integrity (no response values)",
        "",
        f"- adjusted canonical (matched adjusted/adjusted): {basis['adjusted']}",
        f"- disclosed raw fallback (matched raw/raw): {basis['raw_fallback']}",
        f"- canonical event study unavailable: {basis['unavailable']}",
        f"- cross-basis canonical pairs: {basis['cross']} (must be 0; the "
        "default policy never mixes bases)",
        "",
        "## 5. Date structure",
        "",
        f"- unique candidate dates entering the grinder: "
        f"{dates['entering_unique']}",
        f"- unique dates surviving canonical event-study eligibility: "
        f"{dates['surviving_unique']}",
        "",
        "Entering dates by calendar year: "
        + ", ".join(f"{y}:{n}" for y, n in dates["entering_by_year"].items()),
        "",
        "Surviving dates by calendar year: "
        + ", ".join(f"{y}:{n}" for y, n in dates["surviving_by_year"].items()),
        "",
        "This is structural evidence for the later G4 freeze, not a "
        "comparison result.",
        "",
        "## 6. Non-claims and firewall",
        "",
        "No market response of any kind appears in this report, in the "
        "persisted rows, or in any G3 artifact: no absolute return, no "
        "abnormal return, no SAR, no CAR, no sector-relative return, no sign, "
        "no direction, no effect magnitude, and no outcome label. The engine "
        "mechanically computes those values only as a side effect of the "
        "availability check and discards them; a tested field whitelist "
        "enforces the persisted rows. The six-code failure machinery is "
        "validated by isolated unit fixtures (one per code, plus a multi-code "
        "case), so an all-pass funnel here reflects real coverage, not a "
        "silently broken detector. This is not a trading, prediction, or "
        "recommendation surface.",
        "",
        "## 7. Provenance and reproduction (zero-cost)",
        "",
        f"- price cache retrieval timestamp: {retrieved}",
        f"- price cache SHA256 (`g_state_cache/g3_price_cache.db`, gitignored): "
        f"`{cache_sha256}`",
        "- prices: KRE, XLF, XOP, XLE, SPY daily raw close + adjusted close "
        "from the Yahoo public chart endpoint (zero-cost), fetched by "
        "series/range (five requests, not one per candidate).",
        "",
        "```",
        "python scripts/g3_mechanical_grinder.py --probe-sources",
        "python scripts/g3_mechanical_grinder.py --fetch",
        "python scripts/g3_mechanical_grinder.py --grind",
        "python -m unittest tests.test_g3_mechanical_grinder",
        "```",
    ]
    return "\n".join(L) + "\n"


def _funnel_headers(nodes: Sequence[str]) -> list[str]:
    return ["identity", "mapped", "primary", "canonical", "sector-rel"][:len(nodes)]


def _nested_code_lines(mapping: Mapping[str, Mapping[str, int]]) -> list[str]:
    if not mapping:
        return ["- (none)"]
    out: list[str] = []
    for key in sorted(mapping):
        inner = mapping[key]
        parts = ", ".join(f"{c}:{inner[c]}" for c in sorted(inner))
        out.append(f"- {key}: {parts}")
    return out


# ---------------------------------------------------------------------------
# Zero-cost price acquisition (bounded; writes only the gitignored G3 cache)
# ---------------------------------------------------------------------------

CACHE_DIR = gsa.CACHE_DIR                      # g_state_cache/ (gitignored)
G3_PRICE_DB = CACHE_DIR / "g3_price_cache.db"
G3_META_PATH = CACHE_DIR / "g3_price_meta.json"
G3_TICKERS = ("KRE", "XLF", "XOP", "XLE", "SPY")
G3_FETCH_START = "2017-01-01"                  # >=60 bars before earliest 2018 event
G3_FETCH_END = "2026-06-30"                    # covers +20d window of the last 2025 event


def _yahoo_chart_url(ticker: str, *, start: str, end: str) -> str:
    p1 = int(datetime(int(start[:4]), int(start[5:7]), int(start[8:10]),
                      tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(int(end[:4]), int(end[5:7]), int(end[8:10]),
                      tzinfo=timezone.utc).timestamp()) + 86400
    return (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?period1={p1}&period2={p2}&interval=1d")


def fetch_yahoo_ohlc(ticker: str, *, start: str = G3_FETCH_START,
                     end: str = G3_FETCH_END, getter=gsa._get
                     ) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
    """Return (raw_close, adjusted_close, meta) for one ticker over the range.

    Reads both the raw close (``quote.close``) and the adjusted close
    (``adjclose``) from a single chart request - one network call per ticker,
    not one per candidate.
    """
    url = _yahoo_chart_url(ticker, start=start, end=end)
    payload = json.loads(getter(url).decode("utf-8"))
    result = payload["chart"]["result"][0]
    stamps = result.get("timestamp") or []
    quote = (result["indicators"]["quote"][0] or {}).get("close") or []
    adjblock = result["indicators"].get("adjclose") or [{}]
    adj = (adjblock[0] or {}).get("adjclose") or []
    raw_series: dict[str, float] = {}
    adj_series: dict[str, float] = {}
    for i, ts in enumerate(stamps):
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        if not (start <= iso <= end):
            continue
        c = quote[i] if i < len(quote) else None
        if c is not None:
            raw_series[iso] = float(c)
        a = adj[i] if i < len(adj) else None
        if a is not None:
            adj_series[iso] = float(a)
    meta = {"ticker": ticker, "source": "Yahoo chart endpoint", "url": url}
    return raw_series, adj_series, meta


def probe_source_health(ticker: str) -> dict[str, Any]:
    """Bounded per-ticker source-health probe (one small range, no build)."""
    url = _yahoo_chart_url(ticker, start="2024-01-01", end="2024-01-31")
    try:
        payload = json.loads(gsa._get(url, timeout=15).decode("utf-8"))
        result = payload["chart"]["result"][0]
        n = len(result.get("timestamp") or [])
        has_adj = bool(result["indicators"].get("adjclose"))
        return {"ticker": ticker, "ok": n > 0, "observations": n,
                "has_adjclose": has_adj}
    except Exception as exc:  # noqa: BLE001 - bounded evidence capture
        return {"ticker": ticker, "ok": False,
                "error": f"{type(exc).__name__}: {exc}"}


def build_price_db(path: Any, series_by_ticker: Mapping[str, tuple],
                   *, fetched_at: str) -> None:
    """Write a gitignored price_cache DB (both auto_adjust bases) for the gate.

    ``series_by_ticker``: ``{ticker: (raw_dict, adj_dict)}``. Fresh file each
    time; never opens ``events.db`` or the root ``price_cache.db``.
    """
    p = Path(path)
    if p.exists():
        p.unlink()
    conn = sqlite3.connect(str(p))
    try:
        conn.execute(
            "CREATE TABLE price_cache (ticker TEXT, date TEXT, close REAL, "
            "volume REAL, auto_adjust INTEGER, fetched_at TEXT, "
            "source_provider TEXT, PRIMARY KEY (ticker, date, auto_adjust))")
        rows: list[tuple] = []
        for ticker, (raw, adj) in series_by_ticker.items():
            up = ticker.upper()
            for d, c in raw.items():
                rows.append((up, d, c, None, 0, fetched_at, "yahoo_chart"))
            for d, c in adj.items():
                rows.append((up, d, c, None, 1, fetched_at, "yahoo_chart"))
        conn.executemany(
            "INSERT OR REPLACE INTO price_cache (ticker, date, close, volume, "
            "auto_adjust, fetched_at, source_provider) VALUES (?,?,?,?,?,?,?)",
            rows)
        conn.commit()
    finally:
        conn.close()


def run_fetch(*, db_path: Any = G3_PRICE_DB,
              meta_path: Any = G3_META_PATH) -> dict[str, Any]:
    """Acquire the five series and build the gitignored G3 price cache."""
    CACHE_DIR.mkdir(exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()
    series: dict[str, tuple] = {}
    counts: dict[str, dict[str, int]] = {}
    for ticker in G3_TICKERS:
        raw, adj, _ = fetch_yahoo_ohlc(ticker)
        series[ticker] = (raw, adj)
        counts[ticker] = {"raw": len(raw), "adjusted": len(adj)}
        print(f"{ticker}: raw {len(raw)} obs, adjusted {len(adj)} obs")
    build_price_db(db_path, series, fetched_at=fetched_at)
    meta = {
        "retrieved_at": fetched_at,
        "tickers": counts,
        "start": G3_FETCH_START,
        "end": G3_FETCH_END,
        "source": "Yahoo public chart endpoint (raw close + adjusted close)",
    }
    Path(meta_path).write_text(json.dumps(meta, sort_keys=True),
                               encoding="utf-8")
    return meta


# ---------------------------------------------------------------------------
# Real 97-candidate run (rebinds db.DB_FILE at the gitignored G3 cache)
# ---------------------------------------------------------------------------


def run_grinder(*, db_path: Any = G3_PRICE_DB
                ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Grind all 97 candidates against the G3 price cache. Rebinds
    ``db.DB_FILE`` in-process for the run only; restores it afterward, so
    ``events.db`` and the root ``price_cache.db`` are never touched."""
    candidates = load_candidates()
    reconcile(candidates)  # loud input gate
    saved = _db.DB_FILE
    _db.DB_FILE = str(db_path)
    try:
        rows = [grind_candidate(c) for c in candidates]
    finally:
        _db.DB_FILE = saved
    return rows, summarize(rows)


def emit_report(*, db_path: Any = G3_PRICE_DB,
                meta_path: Any = G3_META_PATH) -> dict[str, Any]:
    """Run the grinder and write the tracked eligibility report."""
    _, summary = run_grinder(db_path=db_path)
    p = Path(db_path)
    sha = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    mp = Path(meta_path)
    meta = (json.loads(mp.read_text(encoding="utf-8")) if mp.exists()
            else {"retrieved_at": None, "tickers": {}})
    text = render_report(summary, cache_meta=meta, cache_sha256=sha)
    REPORT_PATH.write_text(text, encoding="utf-8", newline="\n")
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="G3A mechanical-eligibility grinder (zero-cost prices; "
                    "no events.db or price_cache mutation).")
    parser.add_argument("--probe-sources", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--grind", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--emit-report", action="store_true")
    args = parser.parse_args(argv)

    if args.probe_sources:
        for ticker in G3_TICKERS:
            print(json.dumps(probe_source_health(ticker), sort_keys=True))
    if args.fetch:
        run_fetch()
    if args.emit_report:
        summary = emit_report()
        print(f"report -> {REPORT_PATH.relative_to(ROOT)} "
              f"(funnel {summary['funnel']['total']})")
    if args.grind:
        _, summary = run_grinder()
        if args.json:
            print(json.dumps(summary, indent=1, sort_keys=True))
        else:
            print(f"candidates: {summary['n']}  funnel "
                  f"{summary['funnel']['nodes']} = {summary['funnel']['total']}")
            print(f"basis: {summary['basis']}")
            print(f"failures: {summary['failure']['by_code']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
