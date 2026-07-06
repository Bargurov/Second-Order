"""I2A - deterministic symmetric response substrate (Mission I).

Computes the frozen response metrics (raw return, SPY-relative AR,
sector-relative AR, SAR at the feasible horizons) for BOTH memberships -
the frozen study events and the I1 ordinary reference candidates - through
ONE shared computation path: the shipped event-study gate
(`event_study_validation.build_event_study_validation`) under the frozen
F3 basis policy. There is no event-specific or reference-specific formula
anywhere in this module; membership is metadata, not mathematics.

Boundaries (I2A contract): this module computes and accounts for response
records. It never compares event and reference distributions, never
computes MEMP/percentiles/calibration/falsifiers, never ranks or filters
by magnitude, and its tracked report carries coverage, failure, and basis
provenance only. The substrate is returned in memory, uncurated, in
deterministic family/membership/identity/horizon/metric order, for the
later I2B comparison slice.

Inputs: the I1 candidate universe (`scripts/i1_candidate_universe.py`,
which fail-loud-verifies the frozen session pins) and the gitignored local
G3 price cache, read-only. No provider fetch, no DB mutation; a missing or
incomplete cache fails loudly.

Usage:

    python -m scripts.i2a_response_substrate --emit   # tracked report
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as _db  # noqa: E402
import event_study_validation as esv  # noqa: E402
from scripts import g_state_acquisition as gsa  # noqa: E402
from scripts import i1_candidate_universe as i1  # noqa: E402
from scripts.g3_mechanical_grinder import _basis_label  # noqa: E402

SUBSTRATE_VERSION = "i2a-response-substrate-v1"
REPORT_PATH = ROOT / "stats" / "I2A_RESPONSE_SUBSTRATE.md"

# Frozen feasible primary cells (I0 sections 8 and 12): the FOMC 20d
# primary cell is structurally infeasible on the reference side and gets
# no I2A substrate.
FEASIBLE_HORIZONS: dict[str, tuple[int, ...]] = {
    "FOMC": (1, 5),
    "OPEC": (1, 5, 20),
}

# Frozen metric order (also the deterministic record order within a
# horizon). Raw/SPY-relative/SAR come from the canonical (market) gate
# run; sector-relative from the sector gate run. CAR is deliberately
# never extracted (G6A precedent).
METRICS = ("raw_return", "spy_relative_ar", "sector_relative_ar", "sar")

_CANONICAL_FIELD = {"raw_return": "raw_return",
                    "spy_relative_ar": "abnormal_return",
                    "sar": "sar"}

RECORD_FIELDS = (
    "family", "membership", "identity", "source_date", "anchor_session",
    "horizon", "metric", "value", "basis", "primary_ticker",
    "benchmark_used", "contract_version", "status", "failure_reason",
)

_MEMBERSHIP_ORDER = {"event": 0, "reference": 1}


@dataclass(frozen=True)
class LaneAssets:
    family: str
    primary: str
    benchmark: str
    sector: str


@dataclass(frozen=True)
class AttemptItem:
    identity: str
    source_date: str
    anchor_session: str
    horizons: tuple[int, ...]


# ---------------------------------------------------------------------------
# The single symmetric response path
# ---------------------------------------------------------------------------


def _run_gate(anchor_date: str, primary: str, benchmark: str,
              gate: Callable[..., dict], horizons: tuple[int, ...]
              ) -> dict[str, Any]:
    """Run the shipped gate for a SINGLE requested horizon window.

    ``horizons`` is passed through to the gate so readiness (estimation +
    forward + interior-gap) is judged against exactly the requested horizon,
    not the maximum shipped horizon. The gate remains the sole authoritative
    source of every metric; this module never recomputes a return.
    """
    payload = gate({"event_date": anchor_date,
                    "market_tickers": [{"symbol": primary}]},
                   benchmark_ticker=benchmark, horizons=horizons)
    if payload.get("status") == esv.STATUS_AVAILABLE:
        per_h = {int(p["horizon"]): p for p in payload["per_horizon"]}
        return {"ok": True, "basis": _basis_label(payload),
                "per_horizon": per_h}
    reasons = payload.get("blocking_reasons") or ["unavailable"]
    return {"ok": False, "basis": None,
            "failure_reason": ";".join(str(r) for r in reasons)}


def compute_membership_records(
        assets: LaneAssets,
        membership: str,
        items: Sequence[AttemptItem],
        *,
        db_path: Path | str | None = None,
        gate: Optional[Callable[..., dict]] = None,
) -> list[dict[str, Any]]:
    """Response records for one membership through the ONE shared path.

    Events and references both route through this function with identical
    mathematics; only the metadata carried on each record differs. The
    shipped gate is called once per anchor against the market benchmark
    (raw return, SPY-relative AR, SAR) and once against the sector
    comparator (sector-relative AR), under the frozen basis policy.
    """
    if membership not in ("event", "reference"):
        raise ValueError(f"unknown membership {membership!r}")
    use_shipped = gate is None
    if use_shipped:
        gate = esv.build_event_study_validation
        if db_path is None:
            db_path = i1.default_db_path()
        if not Path(db_path).exists():
            raise FileNotFoundError(
                f"price substrate missing: {db_path} - I2A refuses to run "
                "without the local price cache (no provider fetch)")
        saved = _db.DB_FILE
        _db.DB_FILE = str(db_path)
    try:
        records: list[dict[str, Any]] = []
        for item in items:
            for h in item.horizons:
                # Per-horizon readiness (I2A-1): each requested horizon is
                # judged on its OWN forward window, so a valid 1d/5d response
                # never depends on the 20d tail. Same shared gate, same
                # formulas; only the requested horizon differs.
                canonical = _run_gate(item.anchor_session, assets.primary,
                                      assets.benchmark, gate, (h,))
                sector = _run_gate(item.anchor_session, assets.primary,
                                   assets.sector, gate, (h,))
                for metric in METRICS:
                    if metric == "sector_relative_ar":
                        run, bench = sector, assets.sector
                        field = "abnormal_return"
                    else:
                        run, bench = canonical, assets.benchmark
                        field = _CANONICAL_FIELD[metric]
                    if run["ok"]:
                        value = run["per_horizon"][h].get(field)
                        status = ("available" if value is not None
                                  else "unavailable")
                        failure = (None if value is not None
                                   else f"missing_{field}_{h}d")
                        basis = run["basis"] if value is not None else None
                        value = float(value) if value is not None else None
                    else:
                        value, basis = None, None
                        status = "unavailable"
                        failure = run["failure_reason"]
                    records.append({
                        "family": assets.family,
                        "membership": membership,
                        "identity": item.identity,
                        "source_date": item.source_date,
                        "anchor_session": item.anchor_session,
                        "horizon": h,
                        "metric": metric,
                        "value": value,
                        "basis": basis,
                        "primary_ticker": assets.primary,
                        "benchmark_used": bench,
                        "contract_version": SUBSTRATE_VERSION,
                        "status": status,
                        "failure_reason": failure,
                    })
        records.sort(key=lambda r: (
            r["family"], _MEMBERSHIP_ORDER[r["membership"]], r["identity"],
            r["horizon"], METRICS.index(r["metric"])))
        return records
    finally:
        if use_shipped:
            _db.DB_FILE = saved


# ---------------------------------------------------------------------------
# Substrate assembly over the frozen I1 universe
# ---------------------------------------------------------------------------


def _event_items(lane: i1.LaneResult, family: str,
                 horizons: tuple[int, ...]) -> list[AttemptItem]:
    if family == "FOMC":
        parsed = gsa.parse_g1a_candidates(str(gsa.G1A_PATH))
    else:
        parsed = gsa.parse_g1b_candidates(str(gsa.G1B_PATH))
    if sorted(p["event_date"] for p in parsed) != lane.study_event_dates:
        raise ValueError(
            f"{family}: G1 ledger event dates disagree with the I1 lane "
            "study dates; refusing to build an inconsistent substrate")
    items = []
    for p in sorted(parsed, key=lambda x: x["candidate_id"]):
        idx = i1.session_index(lane.joint_sessions, p["event_date"])
        if idx is None:
            raise ValueError(f"{family}: no anchor session at or before "
                             f"{p['event_date']}")
        items.append(AttemptItem(identity=p["candidate_id"],
                                 source_date=p["event_date"],
                                 anchor_session=lane.joint_sessions[idx],
                                 horizons=horizons))
    return items


def _reference_items(lane: i1.LaneResult,
                     horizons: tuple[int, ...]) -> list[AttemptItem]:
    by_date: dict[str, set[int]] = {}
    for h in horizons:
        for idx in lane.cells[h].candidate_indices:
            by_date.setdefault(lane.joint_sessions[idx], set()).add(h)
    return [AttemptItem(identity=d, source_date=d, anchor_session=d,
                        horizons=tuple(sorted(hs)))
            for d, hs in sorted(by_date.items())]


def build_substrate(db_path: Path | str | None = None,
                    gate: Optional[Callable[..., dict]] = None
                    ) -> dict[str, Any]:
    """The full uncurated I2A substrate plus reconciliation and funnel."""
    lanes = i1.build_universe(
        Path(db_path) if db_path is not None else None)
    records: list[dict[str, Any]] = []
    reconciliation: dict[str, Any] = {}
    for family in ("FOMC", "OPEC"):
        lane = lanes[family]
        assets = LaneAssets(family, lane.primary, lane.benchmark,
                            lane.sector)
        horizons = FEASIBLE_HORIZONS[family]
        ev_items = _event_items(lane, family, horizons)
        ref_items = _reference_items(lane, horizons)
        register_overlap = 0
        if lane.register is not None:
            study = set(lane.study_event_dates)
            extras = set(lane.register.dates) - study
            register_overlap = len(
                {i.source_date for i in ev_items} & extras)
        records += compute_membership_records(
            assets, "event", ev_items, db_path=db_path, gate=gate)
        records += compute_membership_records(
            assets, "reference", ref_items, db_path=db_path, gate=gate)
        reconciliation[family] = {
            "event_identities": len(ev_items),
            "reference_attempts": {
                h: lane.cells[h].final_count for h in horizons},
            "reference_anchor_dates": len(ref_items),
            "register_event_overlap": register_overlap,
        }
        expected = {h: lane.cells[h].final_count for h in horizons}
        actual: dict[int, int] = {h: 0 for h in horizons}
        for item in ref_items:
            for h in item.horizons:
                actual[h] += 1
        if actual != expected:
            raise ValueError(f"{family}: reference attempts {actual} do "
                             f"not reconcile to the I1 manifests "
                             f"{expected}")
    records.sort(key=lambda r: (
        r["family"], _MEMBERSHIP_ORDER[r["membership"]], r["identity"],
        r["horizon"], METRICS.index(r["metric"])))
    return {"substrate_version": SUBSTRATE_VERSION,
            "records": records,
            "reconciliation": reconciliation,
            "funnel": _funnel(records)}


def _funnel(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in records:
        cell = out.setdefault(
            (r["family"], r["membership"], r["horizon"], r["metric"]),
            {"attempted": 0, "available": 0, "unavailable": 0,
             "basis": {"adjusted": 0, "raw_fallback": 0},
             "failure_reasons": {}})
        cell["attempted"] += 1
        if r["status"] == "available":
            cell["available"] += 1
            cell["basis"][r["basis"]] += 1
        else:
            cell["unavailable"] += 1
            reason = r["failure_reason"]
            cell["failure_reasons"][reason] = (
                cell["failure_reasons"].get(reason, 0) + 1)
    return out


# ---------------------------------------------------------------------------
# Coverage-only tracked report
# ---------------------------------------------------------------------------


def render_report(substrate: Mapping[str, Any]) -> str:
    rec = substrate["reconciliation"]
    funnel = substrate["funnel"]
    L = [
        "# I2A response substrate - coverage and integrity (Mission I)",
        "",
        f"Contract: `{SUBSTRATE_VERSION}`, executing the locked i0-v1 "
        "protocol over the I1 candidate universe. This report accounts "
        "for coverage, failures, and basis provenance ONLY. It contains "
        "no event-versus-reference comparison, no estimand computation, "
        "no ranking, and no interpretation; those belong to later slices "
        "under the frozen protocol.",
        "",
        "## Symmetric path statement",
        "",
        "Every record - study event and ordinary reference alike - was "
        "computed by `compute_membership_records`, one shared boundary "
        "over the shipped event-study gate under the frozen F3 basis "
        "policy (adjusted/adjusted preferred, matched raw/raw disclosed "
        "fallback, never cross-basis). Membership is metadata, not "
        "mathematics; the symmetry is regression-tested (identical "
        "values and identical failures for identical inputs).",
        "",
        "Readiness is per horizon: each requested response window (1d, 5d, "
        "20d) is judged on its own forward tail, so a 1d or 5d response never "
        "depends on 20d availability. The 60-session estimation requirement, "
        "the interior-gap guard, and the basis policy are unchanged; each "
        "horizon is requested from the shipped gate individually.",
        "",
        "## Denominator reconciliation",
        "",
        "| family | event identities | reference attempts (per horizon) | "
        "distinct reference anchors | register/event overlap |",
        "|---|---|---|---|---|",
    ]
    for family in ("FOMC", "OPEC"):
        r = rec[family]
        attempts = " / ".join(f"{h}d: {n}"
                              for h, n in r["reference_attempts"].items())
        L.append(f"| {family} | {r['event_identities']} | {attempts} | "
                 f"{r['reference_anchor_dates']} | "
                 f"{r['register_event_overlap']} |")
    L += [
        "",
        "The FOMC event denominator is 65 and the OPEC study denominator "
        "is 32, exactly the frozen ledgers; reference attempts equal the "
        "I1 manifests (drift raises before any record is built). The "
        "OPEC known-date register remains exclusion-only: zero of its "
        "non-study dates appear in event membership. The FOMC 20d "
        "primary cell is structurally infeasible and has no substrate.",
        "",
        "## Coverage and basis provenance "
        "(family x membership x horizon x metric)",
        "",
        "| family | membership | h | metric | attempted | available | "
        "adjusted | raw fallback | unavailable |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key in sorted(funnel, key=lambda k: (k[0], _MEMBERSHIP_ORDER[k[1]],
                                             k[2], METRICS.index(k[3]))):
        c = funnel[key]
        family, membership, h, metric = key
        L.append(f"| {family} | {membership} | {h}d | {metric} | "
                 f"{c['attempted']} | {c['available']} | "
                 f"{c['basis']['adjusted']} | "
                 f"{c['basis']['raw_fallback']} | {c['unavailable']} |")
    L += ["", "## Failure accounting", ""]
    any_fail = False
    for key in sorted(funnel, key=lambda k: (k[0], _MEMBERSHIP_ORDER[k[1]],
                                             k[2], METRICS.index(k[3]))):
        c = funnel[key]
        if not c["failure_reasons"]:
            continue
        any_fail = True
        family, membership, h, metric = key
        reasons = "; ".join(f"{k}: {v}" for k, v in
                            sorted(c["failure_reasons"].items()))
        L.append(f"- {family}/{membership}/{h}d/{metric}: {reasons}")
    if not any_fail:
        L.append("- none: every attempted record is available (the era "
                 "sits fully inside the price frame, so the I1 gates "
                 "already guaranteed computability).")
    L += [
        "",
        "## Reproducibility posture",
        "",
        "Event universes and the I1 manifests are deterministic from "
        "tracked artifacts; response extraction additionally requires the "
        "LOCAL gitignored price substrate (read-only; no provider fetch; "
        "missing cache fails loudly). Full fresh-clone execution is "
        "therefore not claimed. The in-memory substrate is uncurated and "
        "deterministically ordered; no response value is duplicated into "
        "this report.",
        "",
        "## Reproduction",
        "",
        "```",
        "python -m scripts.i2a_response_substrate --emit",
        "python -m unittest tests.test_i2a_response_substrate",
        "```",
    ]
    return "\n".join(L) + "\n"


def emit_report() -> None:
    text = render_report(build_substrate())
    REPORT_PATH.write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.buffer.write(
        f"I2A report written -> {REPORT_PATH.relative_to(ROOT)}\n".encode())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="I2A symmetric response substrate (read-only).")
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args(argv)
    if args.emit:
        emit_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
