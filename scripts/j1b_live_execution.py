"""J1B live execution: read-only loader, frozen-input gate, orchestrator.

Contract: ``j1b-live-execution-v1``. This is the ONLY authorized path from
the frozen J1A input snapshot to the frozen J1B engine:

``j1a.verify_frozen_inputs (0 failures) -> authorize_from_verification ->
read-only load into EngineInputs -> eng.run_engine -> frozen-order report``

The loader opens the frozen SQLite caches strictly read-only (URI
``mode=ro``), loads only the frozen symbols/series, preserves exact source
dates, bases, and missingness, and performs no fetch, repair,
normalization, interpolation, forward-fill, or mutation of any kind. The
gate runs BEFORE any input byte is loaded for outcome use; any verifier
failure stops execution with no refetch and no repair.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from scripts import i1_candidate_universe as i1  # noqa: E402
from scripts import j1a_data_readiness as j1a  # noqa: E402
from scripts import j1b_outcome_engine as eng  # noqa: E402

J1B_LIVE_CONTRACT = "j1b-live-execution-v1"

REQUIRED_INPUT_FILES = tuple(sorted(j1a.FROZEN_INPUTS))

# The frozen symbol -> frozen file map (J1A freeze manifest). Only these
# symbols are ever loaded; other tickers present in a cache are ignored.
LIVE_EQUITY_SOURCES: dict[str, str] = {
    "KRE": "g3_price_cache.db",
    "XLF": "g3_price_cache.db",
    "SPY": "g3_price_cache.db",
    "SHY": "j1a_price_cache.db",
    "IAT": "j1a_price_cache.db",
    "KBE": "j1a_price_cache.db",
    "VFH": "j1a_price_cache.db",
}

REPORT_PATH = ROOT / "stats" / "J1B_FOMC_ROBUSTNESS_RESULTS.md"

# Inherited Mission I FOMC 1d surface (Class A, outcome-exposed), quoted
# verbatim from the tracked stats/I2C_CALIBRATION.md / I2C_FALSIFIERS.md
# tables for the bounded comparison section. Never recomputed here.
INHERITED_MISSION_I_FOMC_1D = (
    ("raw_return", 0.674559, 0.997000),
    ("spy_relative_ar (beta=1)", 0.672357, 0.999500),
    ("sector_relative_ar (beta=1)", 0.662996, 0.997000),
    ("sar", 0.725771, 1.000000),
)


class LiveLoadError(RuntimeError):
    """The frozen inputs could not be loaded under the read-only contract."""


def _read_ticker(db_path: Path, ticker: str
                 ) -> dict[str, dict[str, float]]:
    """Read one frozen symbol's raw and adjusted closes, strictly read-only."""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        out: dict[str, dict[str, float]] = {"raw": {}, "adjusted": {}}
        for d, c, adj in conn.execute(
                "SELECT date, close, auto_adjust FROM price_cache "
                "WHERE ticker = ?", (ticker,)):
            out["adjusted" if adj else "raw"][d] = float(c)
    finally:
        conn.close()
    if not out["raw"] or not out["adjusted"]:
        raise LiveLoadError(
            f"{ticker}: missing basis in {db_path.name} "
            f"(raw {len(out['raw'])}, adjusted {len(out['adjusted'])})")
    return out


def load_engine_inputs(cache_dir: Path = j1a.CACHE_DIR
                       ) -> "eng.EngineInputs":
    """Convert the frozen J1A snapshot into the engine's input contract.

    Read-only; exact source dates and values; missing observations stay
    missing. No gate here - callers must use :func:`gate_and_load`.
    """
    cache_dir = Path(cache_dir)
    closes: dict[str, dict[str, dict[str, float]]] = {}
    for ticker in sorted(LIVE_EQUITY_SOURCES):
        db = cache_dir / LIVE_EQUITY_SOURCES[ticker]
        closes[ticker] = _read_ticker(db, ticker)
    treasury_payload = json.loads(
        (cache_dir / "j1a_treasury.json").read_text(encoding="utf-8"))
    dup = treasury_payload.get("meta", {}).get("duplicate_dates")
    if dup != {}:
        raise LiveLoadError(
            f"frozen Treasury snapshot reports duplicate source dates "
            f"{dup!r} - refusing")
    treasury = {
        "two_yr": {d: float(v) for d, v in
                   treasury_payload["series"]["two_yr"].items()},
        "spread_2s10s": {d: float(v) for d, v in
                         treasury_payload["series"]
                         ["spread_2s10s"].items()},
    }
    event_dates = i1.parse_fomc_frame_dates()
    if len(event_dates) != 65:
        raise LiveLoadError(
            f"FOMC frame drifted: {len(event_dates)} != 65 - refusing")
    return eng.EngineInputs(closes=closes, treasury=treasury,
                            event_dates=tuple(event_dates),
                            synthetic=False)


def gate_and_load(cache_dir: Path = j1a.CACHE_DIR, *,
                  expectations: Mapping[str, Mapping[str, Any]]
                  = j1a.FROZEN_INPUTS
                  ) -> tuple[Any, "eng.EngineInputs", dict[str, Any]]:
    """The pre-run gate: verify frozen inputs, mint the live authorization,
    then (and only then) load. Any failure stops before any outcome use."""
    cache_dir = Path(cache_dir)
    failures = j1a.verify_frozen_inputs(cache_dir, expectations)
    authorization = eng.authorize_from_verification(
        failures, detail=f"{J1B_LIVE_CONTRACT}: frozen-input verification "
                         f"0 failures over {len(expectations)} files")
    files: dict[str, dict[str, Any]] = {}
    for name in sorted(expectations):
        p = cache_dir / name
        import hashlib
        files[name] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                       "bytes": p.stat().st_size}
    record = {"failure_count": len(failures), "files": files,
              "verifier": "scripts/j1a_data_readiness.py::"
                          "verify_frozen_inputs"}
    inputs = load_engine_inputs(cache_dir)
    return authorization, inputs, record


def run_live(cache_dir: Path = j1a.CACHE_DIR, *,
             expectations: Mapping[str, Mapping[str, Any]]
             = j1a.FROZEN_INPUTS
             ) -> tuple["eng.EngineResult", dict[str, Any]]:
    """Gate, load, and execute the frozen 12-cell engine on live inputs."""
    authorization, inputs, record = gate_and_load(
        cache_dir, expectations=expectations)
    result = eng.run_engine(inputs, authorization)
    return result, record


# ---------------------------------------------------------------------------
# Deterministic live report (complete surface, frozen order, no ranking)
# ---------------------------------------------------------------------------


def _fmt(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.6f}"


def render_live_report(result: "eng.EngineResult",
                       gate_record: Mapping[str, Any],
                       provenance: Mapping[str, str],
                       conclusions_md: str = "") -> str:
    rd = eng.result_as_dict(result)
    L: list[str] = []
    L.append("# J1B FOMC robustness results - the frozen 12-cell surface "
             "(Mission J)")
    L.append("")
    L.append(f"Contract: `{J1B_LIVE_CONTRACT}` executing "
             f"`{eng.J1B_CONTRACT}` under the locked j0-v1 constitution "
             "and its outcome-blind clarifications. This is the **first "
             "real J1B execution**: no Mission J outcome value existed "
             "before this run.")
    L.append("")
    L.append(f"- execution commit: `{provenance['head']}`")
    L.append(f"- executed at: {provenance['timestamp']}")
    L.append(f"- frozen-input verification: **0 failures** "
             f"(gate: {gate_record['verifier']}; "
             f"{gate_record['failure_count']} recorded)")
    for name in sorted(gate_record["files"]):
        f = gate_record["files"][name]
        L.append(f"  - `{name}`: sha256 `{f['sha256']}` "
                 f"({f['bytes']} bytes)")
    L.append(f"- calibration: B = {rd['calibration']['B']}, "
             f"seed {rd['calibration']['seed']}, RNG policy "
             f"`{rd['calibration']['rng_policy']}`")
    L.append("- events: 65 frame-complete FOMC decisions (G1A); era "
             "2018-01-01 .. 2025-12-31; window [t, t+1]")
    L.append("")
    L.append("Cells appear in frozen J0 order; none is highlighted, none "
             "is ordered by value, and no hypothesis-test vocabulary "
             "appears. MEMPs from cells with different references or "
             "event sets are positioned per cell and are **not "
             "value-comparable** across cells. Edge adjudication belongs "
             "to J3 and does not appear here.")
    L.append("")
    L.append("## Complete 12-cell surface (frozen order)")
    L.append("")
    L.append("| # | measurement | lens | role | M | evid. | events avail/"
             "att | ref N | MEMP | calib pct | node state |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for c in rd["cells"]:
        L.append(
            f"| {c['cell']} | {c['measurement']} | {c['lens']} | "
            f"{c['role']} | {c['m_class']} | {c['evidence_class']} | "
            f"{c['available_event_n']} / {c['attempted_event_n']} | "
            f"{c['reference_n']} | {_fmt(c['memp'])} | "
            f"{_fmt(c['calibration_percentile'])} | {c['node_state']} |")
    L.append("")
    L.append("### Stability overlays (frozen order)")
    L.append("")
    L.append("| # | measurement/lens | LOYO flips/runs | LOEO flips/runs "
             "| F3 ref N -> canonical N | F3 decimated MEMP | F3 sign "
             "flip |")
    L.append("|---|---|---|---|---|---|---|")
    for c in rd["cells"]:
        L.append(
            f"| {c['cell']} | {c['measurement']} {c['lens']} | "
            f"{c['loyo_flips']}/{c['loyo_runs']} | "
            f"{c['loeo_flips']}/{c['loeo_runs']} | "
            f"{c['reference_n']} -> {c['f3_reference_n']} | "
            f"{_fmt(c['f3_memp'])} | {c['f3_sign_flip']} |")
    L.append("")
    L.append("### Per-cell denominators and availability (frozen order)")
    for c in rd["cells"]:
        L.append("")
        L.append(f"- **Cell {c['cell']} - {c['measurement']} "
                 f"({c['lens']})**: basis {c['basis']}"
                 + (" (disclosed raw/raw fallback)" if c["basis_fallback"]
                    else "")
                 + f"; attempted {c['attempted_event_n']}, available "
                 f"{c['available_event_n']}; event-year vector "
                 f"{json.dumps(c['event_year_vector'])}; reference "
                 f"{c['reference_n']} (excluded by event proximity "
                 f"{c['excluded_event_proximity']}); placement group "
                 f"year vector {json.dumps(c['placement_year_vector'])}")
        for date, reason in c["unavailable_events"]:
            L.append(f"  - unavailable event {date}: {reason}")
    L.append("")
    L.append("## Role-level panel summaries (frozen modifiers; no edge "
             "adjudication)")
    for role, s in rd["panel_summaries"].items():
        L.append("")
        L.append(f"### {role}")
        L.append(f"- members: {', '.join(s['members'])} (primary: "
                 f"{s['members'][0]})")
        for mm, st in s["states"].items():
            L.append(f"- {mm}: {st}")
        L.append(f"- role modifier: **{s['modifier']}**")
    L.append("")
    L.append("## Curve-shape contextual layer (cell 11)")
    L.append("")
    L.append(f"- 2S10S_CMT: **{rd['contextual']['node_state']}** - "
             "state-bearing and contextual; outside the rates-repricing "
             "proxy panel, outside role modifiers, outside edge "
             "adjudication (J0 section 12.2). It neither rescues nor "
             "contradicts the rates-role panel.")
    L.append("")
    L.append("## Bounded comparison with the inherited Mission I "
             "specification")
    L.append("")
    L.append("Question (J0 section 13): does the inherited FOMC 1d "
             "finding appear dependent on the already-observed KRE asset "
             "choice or the fixed beta=1 benchmark treatment?")
    L.append("")
    L.append("The inherited Mission I FOMC 1d surface (**Class A: "
             "outcome-exposed before Mission J existed**; KRE / XLF / "
             "SPY specification, 65 events, reference 1816, quoted from "
             "the tracked I2C artifacts, not recomputed):")
    L.append("")
    L.append("| inherited Mission I metric | MEMP | calibration pct |")
    L.append("|---|---|---|")
    for name, m, c in INHERITED_MISSION_I_FOMC_1D:
        L.append(f"| {name} | {m:.6f} | {c:.6f} |")
    L.append("")
    L.append("All four inherited 1d cells carried 0/8 LOYO, 0/65 LOEO, "
             "and 0/4 F3 flips (I2C-B). The J1B cells above are **Class "
             "B: post-outcome robustness statistics under prospectively "
             "frozen new tests** - same-sample evidence that may "
             "strengthen, weaken, localize, or break the inherited "
             "reading, never independent historical confirmation. "
             "Denominator differences are preserved: the rolling-beta "
             "cells cover fewer events than the inherited 65 (the "
             "252/20 history boundary excludes 2018-01-31) and use "
             "their own reference sets; the inherited and new MEMPs are "
             "not value-comparable and are never merged into one "
             "family.")
    if conclusions_md:
        L.append("")
        L.append(conclusions_md.rstrip())
    L.append("")
    return "\n".join(L)


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate", action="store_true",
                    help="run the frozen-input gate only (no outcome)")
    ap.add_argument("--execute", action="store_true",
                    help="gate, load, execute, and write the report")
    ap.add_argument("--verify", action="store_true",
                    help="re-execute and byte-compare against the report")
    ap.add_argument("--head", default="UNSET")
    ap.add_argument("--timestamp", default="UNSET")
    ap.add_argument("--out", default=str(REPORT_PATH))
    args = ap.parse_args(argv)
    if args.gate:
        failures = j1a.verify_frozen_inputs()
        payload = {"failure_count": len(failures), "failures": failures}
        sys.stdout.buffer.write(json.dumps(
            payload, indent=1, sort_keys=True).encode("utf-8") + b"\n")
        return 0 if not failures else 1
    if args.execute or args.verify:
        result, record = run_live()
        prov = {"head": args.head, "timestamp": args.timestamp}
        text = render_live_report(result, record, prov,
                                  conclusions_md=CONCLUSIONS_MD)
        out = Path(args.out)
        if args.verify:
            existing = out.read_text(encoding="utf-8")
            same = existing == text
            sys.stdout.buffer.write(
                f"deterministic rerun byte-identical: {same}\n"
                .encode("utf-8"))
            return 0 if same else 1
        out.write_text(text, encoding="utf-8")
        sys.stdout.buffer.write(
            f"wrote {out}\n".encode("utf-8"))
        return 0
    ap.print_help()
    return 2


# Conclusions are interpretation authored AFTER the complete surface
# existed (full-surface-first rule); they carry no number not present in
# the mechanical surface above and use only the frozen vocabulary.
CONCLUSIONS_MD = """## What survived

Every frozen state and overlay rule supports one reading: the inherited
FOMC 1d response-magnitude elevation survived the frozen challenge on
every axis this surface tests.

- Not asset-specific: the elevation is not a KRE artifact. IAT and KBE
  are ELEVATED under both frozen lenses, and the regional-bank panel is
  BROAD MEASUREMENT CONSISTENCY.
- Not benchmark-sensitive: replacing the inherited beta=1 treatment with
  the frozen 252/20 OLS-with-intercept market model left every equity
  cell ELEVATED (cells 1-5). The frozen model did not reverse the
  inherited result.
- The broad financial sector carried the state (XLF and VFH, both
  lenses; BROAD MEASUREMENT CONSISTENCY).
- The rates-repricing role is ELEVATED on its frozen two-member panel
  (2Y CMT, M2 primary; SHY, M3 alternate; BROAD MEASUREMENT
  CONSISTENCY) - a role-consistent reading under the frozen modifier
  rules, subject to the measurement limitation below.
- Perturbation stability: 0 LOYO flips across 96 runs, 0 LOEO flips
  across 775 runs, 0 F3 sign flips across all 12 cells.

## What weakened or broke

Under the frozen rules, nothing on this surface weakened or broke: no
benchmark sensitivity, no asset specificity, no panel measurement
disagreement, and no overlay fragility was observed. A null,
lower-magnitude, or fragile cell would have been reported here with
identical completeness; none occurred.

## What remains unresolved

- The ideal M1 policy-repricing measure (fed funds futures / OIS) is
  unavailable in the frozen substrate; the rates-role reading rests on
  an M2 official series plus an M3 investable proxy, and the 2Y CMT
  blends policy expectations with term premium (J0 section 8). The
  rates-role elevation is measurement-limited accordingly.
- Daily close-to-close data cannot resolve whether the response is
  anticipated before or concentrated at the official anchor; the frozen
  timing challenge belongs to J2 and has not been run.
- Known-register collision structure is untested; the frozen [t, t+1]
  collision work also belongs to J2.
- All of this is same-sample Class B evidence: post-outcome robustness
  under prospectively frozen new tests. It may never be described as
  independent historical confirmation of the Mission I finding.
- Denominator differences persist by design: the five rolling-beta
  cells cover 64 of the inherited 65 events and their own 1797-anchor
  reference; MEMPs across cells are not value-comparable.
- The 12 frozen cells are correlated robustness views over overlapping
  events, assets, benchmarks, and reference structures. They are not 12
  independent replications or 12 independent statistical tests.

## What J1B does not establish

- causality;
- prediction;
- tradeability;
- alpha;
- independent historical confirmation;
- mechanism proof (edge adjudication belongs to J3 under the frozen
  five-state rules; no edge state is asserted here);
- intraday timing;
- graph propagation;
- any hypothesis-test conclusion (calibration percentiles are placement
  positions, not test outcomes)."""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
