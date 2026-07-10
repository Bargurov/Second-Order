"""J2 - frozen timing and exact-window collision challenge (Mission J).

Contract ``j2-timing-collision-v1`` executing the locked j0-v1 constitution
(sections 10, 11, and 13). This module implements exactly the predeclared
J2 program and nothing else:

- the four frozen state-bearing ``[-5, -1]`` timing cells (cells 13-16:
  raw return, SPY-relative beta-1 AR, sector-relative beta-1 AR, SAR on
  the inherited KRE / SPY / XLF specification);
- the four frozen descriptive-only ``[-20, -1]`` diagnostics (D1-D4,
  same metrics) - no ordinary reference, no MEMP, no calibration, no
  node state, plus the fail-loud empty-funnel documentation;
- exact ``[t, t+1]`` collision classification (C1 finite family / C2
  tracked OPEC register / C3 background-context-only) and the
  denominator-preserving sensitivity re-reads of the existing J1B
  12-cell surface.

Reuse, not reimplementation: the statistical primitives (mid-rank rule,
MEMP, calibration percentile, node states, canonical decimation, flip
convention, grouped single-stream RNG draws) are imported from the frozen
J1B engine; frame/register geometry comes from the frozen I1 universe
module; the interior-gap guard is the shipped event-study guard. No second
event-study framework exists here, and no timing window other than the two
frozen windows can be evaluated.

Hard boundaries: no provider fetch, no DB mutation (the frozen caches are
opened read-only by the J1B loader), fail-closed authorization identical
to J1B, and a deterministic report renderer with no sorting, no ranking,
and no hypothesis-test vocabulary.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

import event_study_validation as esv  # noqa: E402
from scripts import i1_candidate_universe as i1  # noqa: E402
from scripts import j1a_data_readiness as j1a  # noqa: E402
from scripts import j1b_live_execution as live  # noqa: E402
from scripts import j1b_outcome_engine as eng  # noqa: E402

J2_CONTRACT = "j2-timing-collision-v1"

# ---------------------------------------------------------------------------
# Frozen J2 manifest (J0 sections 10 and 13) - 4 + 4, no ninth statistic
# ---------------------------------------------------------------------------

STATE_BEARING_WINDOW: tuple[int, int] = (-5, -1)
DIAGNOSTIC_WINDOW: tuple[int, int] = (-20, -1)
FROZEN_WINDOWS = (STATE_BEARING_WINDOW, DIAGNOSTIC_WINDOW)

# The inherited Mission I metric order (I2A METRICS, frozen).
METRICS: tuple[str, ...] = ("raw_return", "spy_relative_ar",
                            "sector_relative_ar", "sar")

_ROLE = "balance_sheet_sensitive_second_order"
_EVID = "A instrument; B statistic"

TIMING_CELLS: tuple[dict[str, Any], ...] = tuple(
    {"cell": 13 + k, "measurement": "KRE", "metric": m,
     "window": STATE_BEARING_WINDOW, "role": _ROLE, "m_class": "M3",
     "evidence_class": _EVID}
    for k, m in enumerate(METRICS))

TIMING_DIAGNOSTICS: tuple[dict[str, Any], ...] = tuple(
    {"diagnostic": f"D{k + 1}", "measurement": "KRE", "metric": m,
     "window": DIAGNOSTIC_WINDOW}
    for k, m in enumerate(METRICS))

# The frozen J2 placement group: the four metrics share ONE cell geometry
# (one window, one event set, one reference), so the J0-clarified
# grouped_shared_calendar_single_stream policy has exactly one group.
J2_PLACEMENT_GROUPS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("timing_pre_event_minus5_minus1", (13, 14, 15, 16)),
)

# Frozen section-11 vocabulary.
INSUFFICIENT_SUBSET_PHRASE = "insufficient subset under the frozen procedure"
DIAGNOSTIC_SENTENCE = ("descriptive timing diagnostic only; no "
                       "ordinary-reference state is assigned under the "
                       "frozen procedure")
PRERUN_GATE_BANNER = ("J2 PRE-RUN GATE PASSED — FIRST REAL TIMING "
                      "EXECUTION AUTHORIZED")

ESTIMATION_AR_COUNT = 60  # the shipped SAR estimation rule, transplanted

REPORT_PATH = ROOT / "stats" / "J2_TIMING_COLLISION_RESULTS.md"
J1B_PUBLISHED_PATH = ROOT / "stats" / "J1B_FOMC_ROBUSTNESS_RESULTS.md"

# ---------------------------------------------------------------------------
# Reused frozen primitives (identical semantics; never reimplemented)
# ---------------------------------------------------------------------------

mid_rank_percentile = eng.mid_rank_percentile
sorted_abs_percentile = eng._sorted_abs_percentile
memp = eng.memp
calibration_percentile = eng.calibration_percentile
classify_node_state = eng.classify_node_state
canonical_disjoint = eng.canonical_disjoint
CALIBRATION_B = eng.CALIBRATION_B
CALIBRATION_SEED = eng.CALIBRATION_SEED
CALIBRATION_RNG_POLICY = eng.CALIBRATION_RNG_POLICY
build_opec_register = i1.build_opec_register
_flips = eng._flips
_sign = eng._sign


class J2IntegrityError(RuntimeError):
    """A frozen J2 invariant failed - refuse, never repair silently."""


class FrameConsistencyError(RuntimeError):
    """Pairwise and triple joint frames disagree - refusing (no repair)."""


# ---------------------------------------------------------------------------
# Frame (the inherited Mission I KRE / SPY / XLF joint specification)
# ---------------------------------------------------------------------------


def triple_joint_frame(closes: Mapping[str, Mapping[str, Any]]
                       ) -> tuple[list[str], str, bool]:
    """Sorted triple intersection under the frozen F3 basis policy.

    Adjusted/adjusted/adjusted preferred; matched raw/raw/raw as the only
    disclosed fallback; never a cross-basis mix. Additionally asserts that
    both pairwise intersections (KRE&SPY, KRE&XLF) equal the triple joint,
    so the I1 funnel geometry and the shipped pairwise response geometry
    are provably the same frame; any disagreement refuses loudly.
    """
    tickers = ("KRE", "SPY", "XLF")

    def _sets(basis: str) -> Optional[list[set[str]]]:
        out = []
        for t in tickers:
            s = closes[t].get(basis)
            if not s:
                return None
            out.append(set(s))
        return out

    for basis, fallback in (("adjusted", False), ("raw", True)):
        sets = _sets(basis)
        if sets is None:
            continue
        kre, spy, xlf = sets
        triple = kre & spy & xlf
        if (kre & spy) != triple or (kre & xlf) != triple:
            raise FrameConsistencyError(
                "pairwise joint frames disagree with the triple "
                "KRE/SPY/XLF joint frame - refusing (no silent repair)")
        return sorted(triple), basis, fallback
    raise eng.BasisError(
        "no matched triple basis exists for KRE/SPY/XLF (cross-basis "
        "pairing is forbidden by the frozen policy)")


# ---------------------------------------------------------------------------
# The single membership-free timing response (J0 section 10)
# ---------------------------------------------------------------------------


def timing_response(kre: Mapping[str, float], spy: Mapping[str, float],
                    xlf: Mapping[str, float], frame: Sequence[str],
                    idx: int, window: tuple[int, int]
                    ) -> tuple[Optional[dict[str, float]], Optional[str]]:
    """All four inherited metrics for window [a, b] at anchor index idx.

    Window notation is frozen: [a, b] is the hold-period response from the
    session-(idx+a) close to the session-(idx+b) close. Only the two
    frozen J2 windows exist. The anchor session and every future session
    are structurally outside the window (b < 0). SAR follows the shipped
    rule transplanted to the shifted window: sigma_ar_daily from the 60
    daily SPY-relative abnormal returns ending at the window-start
    session, ddof = 1, sqrt(span) scaling. One gate for all four metrics
    (the shipped all-or-nothing per-anchor readiness, transplanted).
    """
    if tuple(window) not in FROZEN_WINDOWS:
        raise ValueError(
            f"window {window!r} is not a frozen J2 window; only "
            f"{FROZEN_WINDOWS} exist (no ninth timing statistic)")
    a, b = window
    span = b - a
    s, e = idx + a, idx + b
    if s - ESTIMATION_AR_COUNT < 0:
        return None, "insufficient_history_60_before_window"
    if idx > len(frame) - 1:
        return None, "anchor_beyond_frame"
    consumed = list(frame[s - ESTIMATION_AR_COUNT: e + 1])
    if not esv._is_contiguous(consumed):
        return None, "window_gap"
    d_start, d_end = frame[s], frame[e]
    k0, k1 = kre[d_start], kre[d_end]
    s0, s1 = spy[d_start], spy[d_end]
    x0, x1 = xlf[d_start], xlf[d_end]
    eng._require_finite(k0, k1, s0, s1, x0, x1)
    if 0.0 in (k0, s0, x0):
        raise eng.EngineNumericalError("zero price at window start")
    raw = k1 / k0 - 1.0
    spy_ret = s1 / s0 - 1.0
    xlf_ret = x1 / x0 - 1.0
    spy_ar = raw - spy_ret
    sector_ar = raw - xlf_ret
    est_dates = frame[s - ESTIMATION_AR_COUNT: s + 1]
    ka = np.array([kre[d] for d in est_dates], dtype=float)
    sa = np.array([spy[d] for d in est_dates], dtype=float)
    if not (np.all(np.isfinite(ka)) and np.all(np.isfinite(sa))):
        raise eng.EngineNumericalError("non-finite estimation price")
    if np.any(ka <= 0) or np.any(sa <= 0):
        raise eng.EngineNumericalError("non-positive estimation price")
    daily_ar = (ka[1:] / ka[:-1] - 1.0) - (sa[1:] / sa[:-1] - 1.0)
    sigma = float(np.std(daily_ar, ddof=1))
    if not math.isfinite(sigma) or sigma <= 0.0:
        return None, "sigma_nonpositive"
    sar = spy_ar / (sigma * math.sqrt(span))
    return {"raw_return": raw, "spy_relative_ar": spy_ar,
            "sector_relative_ar": sector_ar, "sar": sar}, None


# ---------------------------------------------------------------------------
# Timing substrate (event and reference through the ONE shared path)
# ---------------------------------------------------------------------------


@dataclass
class TimingSubstrate:
    window: tuple[int, int]
    frame: list[str]
    basis: str
    basis_fallback: bool
    attempted_event_n: int
    events: list[dict[str, Any]]  # date, anchor_idx, values, reason
    event_anchor_indices: list[int]
    event_percentiles: dict[str, dict[str, float]]   # metric -> date -> pct
    event_year_vector: dict[str, int]
    event_failure_counts: dict[str, int]
    reference_indices: list[int]
    reference_sessions: list[str]
    reference_values: dict[str, dict[str, float]]    # metric -> sess -> val
    sorted_abs_reference: dict[str, list[float]]
    self_pct: dict[str, dict[str, float]]
    excluded_event_proximity: int
    era_candidates: int
    gate_casualties: int
    pool_by_year: dict[str, list[str]]

    def observed_memp(self, metric: str) -> Optional[float]:
        pcts = list(self.event_percentiles[metric].values())
        return memp(pcts) if pcts else None

    @property
    def available_event_dates(self) -> tuple[str, ...]:
        return tuple(sorted(self.event_percentiles[METRICS[0]]))


def _era_indices(frame: Sequence[str], era: tuple[str, str]) -> list[int]:
    lo, hi = era
    return [i for i, d in enumerate(frame) if lo <= d <= hi]


def build_timing_substrate(inputs: "eng.EngineInputs",
                           window: tuple[int, int], *,
                           with_reference: bool = True) -> TimingSubstrate:
    """One symmetric build: membership is metadata, not mathematics.

    Events and ordinary reference anchors route through the identical
    :func:`timing_response` gate; the reference side additionally applies
    the era bound and the frozen span-buffer exclusion (no 65-frame event
    within span(w) indices - the I0 buffer = h geometry transplanted).
    ``with_reference=False`` (the frozen [-20, -1] diagnostic path) keeps
    the eligibility FUNNEL COUNTS for fail-loud documentation but builds
    no reference value, percentile, or statistic of any kind.
    """
    frame, basis, fallback = triple_joint_frame(inputs.closes)
    kre = inputs.closes["KRE"][basis]
    spy = inputs.closes["SPY"][basis]
    xlf = inputs.closes["XLF"][basis]
    a, b = window
    span = b - a

    events: list[dict[str, Any]] = []
    failures: dict[str, int] = {}
    anchor_indices: list[int] = []
    for d in sorted(inputs.event_dates):
        idx = eng.last_index_le(frame, d)
        if idx is None:
            events.append({"date": d, "anchor_idx": None, "values": None,
                           "reason": "date_precedes_frame"})
            failures["date_precedes_frame"] = (
                failures.get("date_precedes_frame", 0) + 1)
            continue
        values, reason = timing_response(kre, spy, xlf, frame, idx, window)
        events.append({"date": d, "anchor_idx": idx, "values": values,
                       "reason": reason})
        if reason is not None:
            failures[reason] = failures.get(reason, 0) + 1
        anchor_indices.append(idx)
    avail = [ev for ev in events if ev["reason"] is None]
    if len({ev["anchor_idx"] for ev in avail}) != len(avail):
        raise J2IntegrityError("duplicate available event anchors - "
                               "refusing")

    era_idx = _era_indices(frame, inputs.era)
    anchor_set = set(anchor_indices)
    survivors: list[int] = []
    survivor_values: dict[int, dict[str, float]] = {}
    for i in era_idx:
        values, reason = timing_response(kre, spy, xlf, frame, i, window)
        if reason is None:
            survivors.append(i)
            survivor_values[i] = values
    eligible = [i for i in survivors
                if not any(abs(i - e) <= span for e in anchor_set)]
    excluded = len(survivors) - len(eligible)
    gate_casualties = len(era_idx) - len(survivors)

    sessions = [frame[i] for i in eligible]
    pool: dict[str, list[str]] = {}
    for s in sessions:
        pool.setdefault(s[:4], []).append(s)
    pool = {y: sorted(v) for y, v in sorted(pool.items())}
    year_vec: dict[str, int] = {}
    for ev in avail:
        y = frame[ev["anchor_idx"]][:4]
        year_vec[y] = year_vec.get(y, 0) + 1
    year_vec = dict(sorted(year_vec.items()))

    ref_values: dict[str, dict[str, float]] = {m: {} for m in METRICS}
    sorted_abs: dict[str, list[float]] = {m: [] for m in METRICS}
    self_pct: dict[str, dict[str, float]] = {m: {} for m in METRICS}
    ev_pct: dict[str, dict[str, float]] = {m: {} for m in METRICS}
    if with_reference:
        for m in METRICS:
            vals = {frame[i]: survivor_values[i][m] for i in eligible}
            ref_values[m] = vals
            sa = sorted(abs(v) for v in vals.values())
            sorted_abs[m] = sa
            self_pct[m] = {s: sorted_abs_percentile(sa, vals[s])
                           for s in sessions}
            ev_pct[m] = {ev["date"]: sorted_abs_percentile(
                sa, ev["values"][m]) for ev in avail}

    return TimingSubstrate(
        window=tuple(window), frame=frame, basis=basis,
        basis_fallback=fallback,
        attempted_event_n=len(inputs.event_dates), events=events,
        event_anchor_indices=sorted(anchor_set),
        event_percentiles=ev_pct, event_year_vector=year_vec,
        event_failure_counts=dict(sorted(failures.items())),
        reference_indices=eligible, reference_sessions=sessions,
        reference_values=ref_values, sorted_abs_reference=sorted_abs,
        self_pct=self_pct, excluded_event_proximity=excluded,
        era_candidates=len(era_idx), gate_casualties=gate_casualties,
        pool_by_year=pool)


def build_state_bearing_substrate(inputs: "eng.EngineInputs"
                                  ) -> TimingSubstrate:
    return build_timing_substrate(inputs, STATE_BEARING_WINDOW,
                                  with_reference=True)


# ---------------------------------------------------------------------------
# Stability overlays (re-rank only; overlays never rewrite a state)
# ---------------------------------------------------------------------------


def _rerank(sub: TimingSubstrate, metric: str,
            reduced_sorted: Sequence[float], *,
            skip_year: Optional[str] = None) -> list[float]:
    pcts = []
    for ev in sub.events:
        if ev["reason"] is not None:
            continue
        year = sub.frame[ev["anchor_idx"]][:4]
        if skip_year is not None and year == skip_year:
            continue
        pcts.append(sorted_abs_percentile(reduced_sorted,
                                          ev["values"][metric]))
    return pcts


def _loyo(sub: TimingSubstrate, metric: str) -> dict[str, Any]:
    """F1-style: remove each year's events AND reference dates, re-rank."""
    full = sub.observed_memp(metric)
    years = sorted({s[:4] for s in sub.reference_sessions}
                   | set(sub.event_year_vector))
    flips = 0
    for y in years:
        reduced = sorted(abs(sub.reference_values[metric][s])
                         for s in sub.reference_sessions if s[:4] != y)
        pcts = _rerank(sub, metric, reduced, skip_year=y)
        m = memp(pcts) if pcts else None
        if m is not None and _flips(full, m):
            flips += 1
    return {"runs": len(years), "flips": flips}


def _loeo(percentiles: Sequence[float]) -> dict[str, Any]:
    """F2-style: remove one event at a time; the reference is untouched."""
    full = memp(percentiles)
    flips = 0
    for i in range(len(percentiles)):
        rest = list(percentiles[:i]) + list(percentiles[i + 1:])
        if rest and _flips(full, memp(rest)):
            flips += 1
    return {"runs": len(percentiles), "flips": flips}


def _f3(sub: TimingSubstrate, metric: str, span: int) -> dict[str, Any]:
    """F3: canonical greedy earliest-first disjoint decimation."""
    full = sub.observed_memp(metric)
    picks = canonical_disjoint(sub.reference_indices, span=span)
    reduced = sorted(abs(sub.reference_values[metric][sub.frame[i]])
                     for i in picks)
    pcts = _rerank(sub, metric, reduced)
    m = memp(pcts) if pcts else None
    return {"decimated_reference_n": len(picks), "decimated_memp": m,
            "change": None if (m is None or full is None) else m - full,
            "sign_flip": bool(m is not None and full is not None
                              and _flips(full, m))}


# ---------------------------------------------------------------------------
# State-bearing runner (cells 13-16)
# ---------------------------------------------------------------------------


def _calibrate_timing(sub: TimingSubstrate, *, b: int = None,
                      seed: int = None) -> dict[str, Any]:
    """The frozen grouped_shared_calendar_single_stream policy with the
    single J2 placement group: one local RNG seeded 20180101, one drawn
    calendar per placement reused across all four metrics."""
    b = CALIBRATION_B if b is None else b
    seed = CALIBRATION_SEED if seed is None else seed
    rng = np.random.default_rng(seed)
    draws = eng._draw_group_placements(rng, sub.pool_by_year,
                                       sub.event_year_vector, b)
    out: dict[str, Any] = {"draws": draws, "per_metric": {}}
    for m in METRICS:
        lut = sub.self_pct[m]
        dist = [memp([lut[s] for s in drawn]) for drawn in draws]
        obs = sub.observed_memp(m)
        out["per_metric"][m] = calibration_percentile(obs, dist)
    return out


def calibration_placement_probe(inputs: "eng.EngineInputs", *,
                                b: int) -> dict[str, Any]:
    """Bounded synthetic probe exposing the drawn calendars, so the
    year-matched / without-replacement / shared-calendar semantics are
    directly observable in tests."""
    sub = build_state_bearing_substrate(inputs)
    calib = _calibrate_timing(sub, b=b)
    return {"group_cells": J2_PLACEMENT_GROUPS[0][1],
            "calendars": [tuple(d) for d in calib["draws"]]}


def run_state_bearing(inputs: "eng.EngineInputs",
                      authorization: Any) -> dict[str, Any]:
    """The complete frozen four-cell [-5, -1] surface (cells 13-16)."""
    synthetic = eng._check_authorization(inputs, authorization)
    sub = build_state_bearing_substrate(inputs)
    span = STATE_BEARING_WINDOW[1] - STATE_BEARING_WINDOW[0]
    # The four metrics share ONE substrate by construction; assert the
    # shared-geometry precondition of the frozen placement group anyway.
    for m in METRICS:
        if sorted(sub.event_percentiles[m]) != list(
                sub.available_event_dates):
            raise eng.CalibrationGeometryError(
                "timing metrics do not share the available-event "
                "identity set - refusing")
    calib = _calibrate_timing(sub)
    cells: list[dict[str, Any]] = []
    for spec in TIMING_CELLS:
        m = spec["metric"]
        observed = sub.observed_memp(m)
        cp = calib["per_metric"][m]
        state = classify_node_state(observed, cp)
        loyo = _loyo(sub, m)
        loeo = _loeo(list(sub.event_percentiles[m].values()))
        f3 = _f3(sub, m, span)
        cells.append({
            "cell": spec["cell"],
            "measurement": spec["measurement"],
            "metric": m,
            "window": list(STATE_BEARING_WINDOW),
            "role": spec["role"],
            "m_class": spec["m_class"],
            "evidence_class": spec["evidence_class"],
            "basis": sub.basis,
            "basis_fallback": sub.basis_fallback,
            "attempted_event_n": sub.attempted_event_n,
            "available_event_n": len(sub.event_percentiles[m]),
            "event_year_vector": dict(sub.event_year_vector),
            "event_failure_counts": dict(sub.event_failure_counts),
            "unavailable_events": [[ev["date"], ev["reason"]]
                                   for ev in sub.events
                                   if ev["reason"] is not None],
            "reference_n": len(sub.reference_sessions),
            "excluded_event_proximity": sub.excluded_event_proximity,
            "memp": observed,
            "calibration_percentile": cp,
            "placement_year_vector": dict(sub.event_year_vector),
            "node_state": state,
            "loyo_runs": loyo["runs"], "loyo_flips": loyo["flips"],
            "loeo_runs": loeo["runs"], "loeo_flips": loeo["flips"],
            "f3_reference_n": f3["decimated_reference_n"],
            "f3_memp": f3["decimated_memp"],
            "f3_change": f3["change"],
            "f3_sign_flip": f3["sign_flip"],
        })
    banner = eng.SYNTHETIC_BANNER if synthetic else (
        "J2 state-bearing timing surface (live)")
    return {
        "window": list(STATE_BEARING_WINDOW),
        "cells": cells,
        "calibration": {"B": CALIBRATION_B, "seed": CALIBRATION_SEED,
                        "rng_policy": CALIBRATION_RNG_POLICY,
                        "groups": [[g, list(nos)] for g, nos in
                                   J2_PLACEMENT_GROUPS]},
        "synthetic": synthetic,
        "banner": banner,
    }


# ---------------------------------------------------------------------------
# Descriptive-only diagnostics (D1-D4; J0 sections 10 and 13)
# ---------------------------------------------------------------------------


def run_diagnostics(inputs: "eng.EngineInputs",
                    authorization: Any) -> dict[str, Any]:
    """The four frozen [-20, -1] descriptive diagnostics.

    Frozen consequence (J0 section 10): the ordinary-reference and
    per-year calibration construction is structurally infeasible under
    the frozen geometry, so these carry event-side responses and the
    fail-loud eligibility funnel ONLY - no reference statistic, no MEMP,
    no calibration, no node state, no stability overlay, regardless of
    runtime pool counts.
    """
    synthetic = eng._check_authorization(inputs, authorization)
    sub = build_timing_substrate(inputs, DIAGNOSTIC_WINDOW,
                                 with_reference=False)
    diagnostics: list[dict[str, Any]] = []
    for spec in TIMING_DIAGNOSTICS:
        m = spec["metric"]
        values = [ev["values"][m] for ev in sub.events
                  if ev["reason"] is None]
        med = statistics.median(values) if values else None
        med_abs = (statistics.median(abs(v) for v in values)
                   if values else None)
        direction = (None if med is None else
                     "positive" if med > 0 else
                     "negative" if med < 0 else "zero")
        diagnostics.append({
            "diagnostic": spec["diagnostic"],
            "measurement": spec["measurement"],
            "metric": m,
            "window": list(DIAGNOSTIC_WINDOW),
            "basis": sub.basis,
            "attempted_event_n": sub.attempted_event_n,
            "available_event_n": len(values),
            "event_failure_counts": dict(sub.event_failure_counts),
            "unavailable_events": [[ev["date"], ev["reason"]]
                                   for ev in sub.events
                                   if ev["reason"] is not None],
            "median_response": med,
            "median_abs_response": med_abs,
            "direction": direction,
        })
    pool_counts = {y: len(v) for y, v in sub.pool_by_year.items()}
    matching = all(pool_counts.get(y, 0) >= n
                   for y, n in sub.event_year_vector.items())
    funnel = {
        "era_candidates": sub.era_candidates,
        "gate_casualties": sub.gate_casualties,
        "exclusion_casualties": sub.excluded_event_proximity,
        "eligible_total": len(sub.reference_indices),
        "eligible_per_year": pool_counts,
        "event_year_vector": dict(sub.event_year_vector),
        "per_year_matching_executable": bool(matching),
        "frozen_descriptive_only": True,
        "note": DIAGNOSTIC_SENTENCE,
    }
    banner = eng.SYNTHETIC_BANNER if synthetic else (
        "J2 descriptive timing diagnostics (live)")
    return {"window": list(DIAGNOSTIC_WINDOW), "diagnostics": diagnostics,
            "reference_funnel": funnel, "synthetic": synthetic,
            "banner": banner}


# ---------------------------------------------------------------------------
# Exact [t, t+1] collision constitution (J0 section 11)
# ---------------------------------------------------------------------------


def fomc_self_collision_invariant(event_indices: Sequence[int]
                                  ) -> dict[str, Any]:
    """C1 family 1: frozen as a CHECKED invariant, not an assumption.

    Two [t, t+1] intervals share a session iff anchor spacing <= 1."""
    idx = sorted(event_indices)
    diffs = [b - a for a, b in zip(idx, idx[1:])]
    violations = [[idx[k], idx[k + 1]] for k, d in enumerate(diffs)
                  if d <= 1]
    return {"min_anchor_spacing": min(diffs) if diffs else None,
            "violations": violations}


def c1_macro_register_support(releases: Optional[Sequence[tuple]] = None,
                              era_years: Sequence[int] = range(2018, 2026)
                              ) -> dict[str, Any]:
    """Mechanical source-support adjudication for the C1 macro families.

    The frozen C1 families 2 and 3 (BLS CPI, BLS Employment Situation)
    require a source-pinned register built from the official BLS calendar
    covering the frozen era. The only in-repo macro calendar
    (``macro_calendar._RELEASES``) is an app-layer display list that its
    own header declares approximate; this check is purely mechanical on
    era-year coverage and refuses when any era year is uncovered. No
    substitute calendar is fetched.
    """
    if releases is None:
        from macro_calendar import _RELEASES as releases  # type: ignore
    covered: dict[str, set[int]] = {"CPI": set(), "NFP": set()}
    for name, date_iso, _period in releases:
        if name in covered:
            covered[name].add(int(date_iso[:4]))
    missing: dict[str, list[int]] = {}
    for fam, years in covered.items():
        gap = [y for y in era_years if y not in years]
        if gap:
            missing[fam] = gap
    adjudicable = not missing
    reason = ("" if adjudicable else
              "no source-pinned BLS release register covers the frozen "
              "era: the in-repo macro calendar is an app-layer display "
              "list (self-declared approximate) missing era years "
              f"{missing}; the C1 CPI / Employment Situation branch is "
              "unadjudicable in this execution and no substitute "
              "calendar is fetched")
    return {"adjudicable": adjudicable,
            "missing_era_years": missing,
            "families": {k: sorted(v) for k, v in covered.items()},
            "reason": reason}


def tag_exact_interval_collisions(frame: Sequence[str],
                                  event_dates: Sequence[str],
                                  competing_dates: Sequence[str]
                                  ) -> dict[str, list[dict[str, Any]]]:
    """Tag events whose exact [t, t+1] response interval is overlapped.

    A competing calendar date resolves to its anchor session (the last
    joint session at or before the date - the frozen project-wide
    semantics); it collides with event e iff that resolved session is one
    of the two sessions the 1d response consumes: {e, e+1}. No proximity
    buffer of any width exists here.
    """
    tags: dict[str, list[dict[str, Any]]] = {}
    frame = list(frame)
    ev_idx: dict[str, int] = {}
    for d in event_dates:
        idx = eng.last_index_le(frame, d)
        if idx is None:
            raise J2IntegrityError(f"event date {d} precedes the frame")
        ev_idx[d] = idx
    for cd in sorted(set(competing_dates)):
        o = eng.last_index_le(frame, cd)
        if o is None:
            continue
        for d, e in ev_idx.items():
            if o in (e, e + 1):
                tags.setdefault(d, []).append({
                    "competing_date": cd,
                    "competing_anchor_session": frame[o],
                    "overlap_basis": (
                        f"resolved anchor session index {o} is inside the "
                        f"exact response interval sessions "
                        f"[{frame[e]}, {frame[min(e + 1, len(frame) - 1)]}]"
                    ),
                })
    return {d: tags[d] for d in sorted(tags)}


def build_collision_register(frame: Sequence[str],
                             event_dates: Sequence[str], *,
                             opec_dates: Sequence[str],
                             c1_support: Mapping[str, Any]
                             ) -> dict[str, Any]:
    """The complete frozen collision register: C1 / C2 tags, C3 context.

    Collision status is metadata only; the primary denominator is never
    reduced here or anywhere downstream.
    """
    frame = list(frame)
    ev_idx: dict[str, int] = {}
    for d in event_dates:
        idx = eng.last_index_le(frame, d)
        if idx is None:
            raise J2IntegrityError(f"event date {d} precedes the frame")
        ev_idx[d] = idx
    invariant = fomc_self_collision_invariant(list(ev_idx.values()))
    if invariant["violations"]:
        raise J2IntegrityError(
            "FOMC self-collision invariant violated: frame events share "
            f"a [t, t+1] interval ({invariant['violations']}) - frame "
            "drift, refusing")
    c1_tags: dict[str, list[dict[str, Any]]] = {}
    if c1_support.get("adjudicable"):
        raise J2IntegrityError(
            "C1 macro tagging requested but no frozen source-pinned "
            "register implementation exists in this contract - refusing "
            "to invent one")
    c2_tags = tag_exact_interval_collisions(frame, event_dates,
                                            list(opec_dates))
    events: dict[str, dict[str, Any]] = {}
    for d, e in sorted(ev_idx.items()):
        classes = []
        if d in c1_tags:
            classes.append("C1")
        if d in c2_tags:
            classes.append("C2")
        events[d] = {
            "anchor_session": frame[e],
            "anchor_idx": e,
            "interval_sessions": [frame[e],
                                  frame[e + 1] if e + 1 < len(frame)
                                  else None],
            "classes": classes,
        }
    return {
        "interval": "[t, t+1]",
        "fomc_self": invariant,
        "c1": {"adjudicable": bool(c1_support.get("adjudicable")),
               "reason": c1_support.get("reason", ""),
               "families": ("BLS CPI", "BLS Employment Situation"),
               "tags": c1_tags},
        "c2": {"register": f"opec-known-date-exclusion-register@"
                           f"{i1.I0_PROTOCOL}",
               "register_dates": len(set(opec_dates)),
               "tags": c2_tags},
        "c3": {"note": ("background environment; context only - C3 is "
                        "never an exclusion rule and no attempt is made "
                        "to clean the world"),
               "excludes": False},
        "events": events,
    }


def collision_subsets(register: Mapping[str, Any],
                      event_dates: Sequence[str]) -> dict[str, Any]:
    """The predeclared section-11 subsets. No numeric event floor exists;
    subsets are governed by frozen algorithmic feasibility only."""
    all_dates = tuple(sorted(event_dates))
    c2_dates = tuple(sorted(register["c2"]["tags"]))
    c1 = register["c1"]
    tagged = set(c2_dates) | set(c1["tags"])
    free = tuple(d for d in all_dates if d not in tagged)
    out: dict[str, Any] = {
        "all": {"dates": all_dates, "n": len(all_dates)},
        "collision_free": {
            "dates": free, "n": len(free),
            "basis": ("outside known-register collisions under the "
                      "adjudicable registers (C2 OPEC known-date "
                      "register; C1 FOMC-self by checked invariant); "
                      "the C1 CPI / Employment Situation branch is "
                      "unadjudicable in this execution, so freedom from "
                      "those releases is NOT certified")},
        "c2_tagged": {"dates": c2_dates, "n": len(c2_dates)},
    }
    if c1["adjudicable"]:
        c1_dates = tuple(sorted(c1["tags"]))
        out["c1_tagged"] = {"dates": c1_dates, "n": len(c1_dates)}
    else:
        out["c1_tagged"] = {"status": "unadjudicable",
                            "reason": c1["reason"]}
    return out


# ---------------------------------------------------------------------------
# Collision sensitivity re-reads of the existing J1B 12-cell surface
# ---------------------------------------------------------------------------


def subset_reread(substrates: Sequence["eng.CellSubstrate"],
                  subset_dates: Sequence[str], *, label: str,
                  b: int = None) -> dict[str, Any]:
    """A denominator-preserving subset re-read of existing J1B cells.

    Event percentiles and reference sets are carried UNCHANGED from the
    primary substrates; only the event set entering the median is
    restricted. Calibration re-runs the frozen I2C-A mechanics against
    the subset's year vector under the frozen policy: one fresh local
    ``default_rng(20180101)`` per sensitivity family, the frozen J1B
    placement groups in their fixed order, one drawn calendar reused
    across each group's members. A subset whose frozen mechanics cannot
    execute is reported with the exact frozen phrase. The primary states
    are never rewritten; the per-cell classification here is a
    sensitivity read only.
    """
    b = CALIBRATION_B if b is None else b
    subset = set(subset_dates)
    by_no = {sub.cell["cell"]: sub for sub in substrates}
    rng = np.random.default_rng(CALIBRATION_SEED)
    cells: list[dict[str, Any]] = []
    for group_name, cell_nos in eng.PLACEMENT_GROUPS:
        members = [by_no[no] for no in cell_nos if no in by_no]
        if not members:
            continue
        eng.assert_group_geometry(group_name, members)
        anchor = members[0]
        sub_dates = tuple(d for d in anchor.available_event_dates
                          if d in subset)
        for member in members[1:]:
            if tuple(d for d in member.available_event_dates
                     if d in subset) != sub_dates:
                raise eng.CalibrationGeometryError(
                    f"group {group_name}: members disagree on subset "
                    "availability - refusing")
        if not sub_dates:
            for member in members:
                cells.append({
                    "cell": member.cell["cell"],
                    "measurement": member.cell["measurement"],
                    "lens": member.cell["lens"],
                    "available_n": 0,
                    "status": INSUFFICIENT_SUBSET_PHRASE,
                    "reason": ("empty available-event subset for the "
                               "frozen comparison"),
                })
            continue
        date_year = {d: anchor.frame[
            next(ev["anchor_idx"] for ev in anchor.events
                 if ev["date"] == d)][:4] for d in sub_dates}
        year_vec: dict[str, int] = {}
        for d in sub_dates:
            year_vec[date_year[d]] = year_vec.get(date_year[d], 0) + 1
        year_vec = dict(sorted(year_vec.items()))
        try:
            draws = eng._draw_group_placements(
                rng, anchor.pool_by_year, year_vec, b)
        except eng.CalibrationInfeasibleError as exc:
            for member in members:
                cells.append({
                    "cell": member.cell["cell"],
                    "measurement": member.cell["measurement"],
                    "lens": member.cell["lens"],
                    "available_n": len(sub_dates),
                    "status": INSUFFICIENT_SUBSET_PHRASE,
                    "reason": str(exc),
                })
            continue
        for member in members:
            pcts = [member.event_percentiles[d] for d in sub_dates]
            observed = memp(pcts)
            lut = member.self_pct
            dist = [memp([lut[s] for s in drawn]) for drawn in draws]
            cp = calibration_percentile(observed, dist)
            loyo = _subset_loyo(member, sub_dates)
            loeo = _loeo(pcts)
            cells.append({
                "cell": member.cell["cell"],
                "measurement": member.cell["measurement"],
                "lens": member.cell["lens"],
                "available_n": len(sub_dates),
                "year_vector": dict(year_vec),
                "memp": observed,
                "calibration_percentile": cp,
                "sensitivity_read": classify_node_state(observed, cp),
                "loyo_runs": loyo["runs"], "loyo_flips": loyo["flips"],
                "loeo_runs": loeo["runs"], "loeo_flips": loeo["flips"],
            })
    cells.sort(key=lambda c: c["cell"])
    return {"label": label, "subset_n": len(set(subset_dates)),
            "cells": cells,
            "calibration": {"B": b, "seed": CALIBRATION_SEED,
                            "rng_policy": CALIBRATION_RNG_POLICY}}


def _subset_loyo(sub: "eng.CellSubstrate",
                 subset_dates: Sequence[str]) -> dict[str, Any]:
    """Subset LOYO: drop each year's reference dates AND subset events."""
    date_year: dict[str, str] = {}
    date_value: dict[str, float] = {}
    for ev in sub.events:
        if ev["reason"] is None and ev["date"] in set(subset_dates):
            date_year[ev["date"]] = sub.frame[ev["anchor_idx"]][:4]
            date_value[ev["date"]] = ev["value"]
    full = memp([sub.event_percentiles[d] for d in subset_dates])
    years = sorted({s[:4] for s in sub.reference_sessions}
                   | set(date_year.values()))
    flips = 0
    for y in years:
        reduced = sorted(abs(sub.reference_values[s])
                         for s in sub.reference_sessions if s[:4] != y)
        pcts = [eng._sorted_abs_percentile(reduced, date_value[d])
                for d in subset_dates if date_year[d] != y]
        m = memp(pcts) if pcts else None
        if m is not None and _flips(full, m):
            flips += 1
    return {"runs": len(years), "flips": flips}


# ---------------------------------------------------------------------------
# Published-J1B anchor (the all-events sensitivity IS the published result)
# ---------------------------------------------------------------------------


def parse_published_j1b_table(text: str) -> dict[int, dict[str, str]]:
    """Parse the tracked J1B 12-cell surface table (fail-loud on drift)."""
    import re
    rows: dict[int, dict[str, str]] = {}
    pat = re.compile(
        r"^\|\s*(\d+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|[^|]+\|[^|]+\|[^|]+\|"
        r"[^|]+\|\s*(\d+)\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)\s*\|"
        r"\s*([A-Z_]+)\s*\|\s*$")
    for line in text.splitlines():
        m = pat.match(line.strip())
        if m:
            rows[int(m.group(1))] = {
                "measurement": m.group(2), "lens": m.group(3),
                "reference_n": m.group(4), "memp": m.group(5),
                "calib": m.group(6), "state": m.group(7)}
    return rows


def assert_allevents_reproduction(substrates: Sequence["eng.CellSubstrate"],
                                  published: Mapping[int, Mapping[str, str]]
                                  ) -> None:
    """Recompute the all-events family via the frozen J1B calibration and
    require exact 6-decimal agreement with the tracked published surface.
    Any disagreement is a mechanical defect or input drift - refuse."""
    calib = eng.calibrate_cells(substrates)
    for sub in substrates:
        no = sub.cell["cell"]
        pub = published.get(no)
        if pub is None:
            raise J2IntegrityError(
                f"published J1B table lacks cell {no} - refusing")
        got_memp = f"{sub.observed_memp:.6f}"
        got_cp = f"{calib[no]['calibration_percentile']:.6f}"
        if got_memp != pub["memp"] or got_cp != pub["calib"]:
            raise J2IntegrityError(
                f"cell {no}: recomputed (MEMP {got_memp}, calibration "
                f"{got_cp}) does not reproduce the published J1B surface "
                f"(MEMP {pub['memp']}, calibration {pub['calib']}) - "
                "refusing")


# ---------------------------------------------------------------------------
# Deterministic report renderer (frozen order; no ranking; no highlighting)
# ---------------------------------------------------------------------------


def _fmt(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.6f}"


def render_j2_report(*, state_bearing: Mapping[str, Any],
                     diagnostics: Mapping[str, Any],
                     register: Mapping[str, Any],
                     subsets: Mapping[str, Any],
                     sensitivity: Mapping[str, Any],
                     published_j1b: Optional[Mapping[int, Mapping[str, str]]],
                     gate_record: Mapping[str, Any],
                     provenance: Mapping[str, str],
                     conclusions_md: str = "") -> str:
    L: list[str] = []
    L.append("# J2 timing and collision results - the frozen challenge "
             "to the published FOMC 1d readout (Mission J)")
    L.append("")
    L.append(f"Contract: `{J2_CONTRACT}` under the locked j0-v1 "
             "constitution (sections 10, 11, 13). This is the **first "
             "real J2 timing execution**: no Mission J timing or "
             "collision outcome value existed before this run.")
    L.append("")
    if state_bearing["synthetic"]:
        L.append(f"**{eng.SYNTHETIC_BANNER}**")
        L.append("")
    L.append("## 1. Contract and provenance")
    L.append("")
    L.append(f"- execution commit: `{provenance['head']}`")
    L.append(f"- executed at: {provenance['timestamp']}")
    L.append(f"- frozen-input verification: **"
             f"{gate_record['failure_count']} failures** (gate: "
             f"{gate_record['verifier']})")
    for name in sorted(gate_record["files"]):
        f = gate_record["files"][name]
        L.append(f"  - `{name}`: sha256 `{f['sha256']}` "
                 f"({f['bytes']} bytes)")
    L.append(f"- calibration: B = {state_bearing['calibration']['B']}, "
             f"seed {state_bearing['calibration']['seed']}, RNG policy "
             f"`{state_bearing['calibration']['rng_policy']}` (single J2 "
             "placement group: cells 13-16 share one drawn calendar per "
             "placement)")
    L.append("- frozen J2 manifest: exactly 4 state-bearing `[-5, -1]` "
             "cells (13-16: raw_return, spy_relative_ar, "
             "sector_relative_ar, sar on the inherited KRE / SPY / XLF "
             "specification) and exactly 4 descriptive `[-20, -1]` "
             "diagnostics (D1-D4, same metrics). No ninth timing "
             "statistic exists.")
    L.append("- timing windows: state-bearing `[-5, -1]` (span 4); "
             "descriptive `[-20, -1]` (span 19); the official anchor "
             "mapping is the inherited last-session-at-or-before rule, "
             "unchanged; the anchor session is outside both windows.")
    L.append("- collision boundary: the exact `[t, t+1]` sessions "
             "consumed by the existing 1d response - no proximity "
             "buffer of any width. C1 = frozen finite family (FOMC "
             "self, checked invariant; BLS CPI; BLS Employment "
             "Situation). C2 = the tracked "
             f"`{register['c2']['register']}`. C3 = background "
             "environment, context only, never an exclusion rule.")
    L.append("- collision status is metadata: the primary denominator "
             "retains all frozen FOMC events in every primary readout.")
    L.append("- non-claims: see section 9; no hypothesis-test "
             "vocabulary appears anywhere; calibration percentiles are "
             "placement positions only; MEMPs from different windows, "
             "references, or availability sets are not "
             "value-comparable.")
    L.append("")
    L.append("## 2. State-bearing [-5, -1] surface (cells 13-16, frozen "
             "order)")
    L.append("")
    L.append("| # | measurement | metric | window | events avail/att | "
             "ref N | MEMP | calib pct | node state |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for c in state_bearing["cells"]:
        L.append(
            f"| {c['cell']} | {c['measurement']} | {c['metric']} | "
            f"[{c['window'][0]}, {c['window'][1]}] | "
            f"{c['available_event_n']} / {c['attempted_event_n']} | "
            f"{c['reference_n']} | {_fmt(c['memp'])} | "
            f"{_fmt(c['calibration_percentile'])} | {c['node_state']} |")
    L.append("")
    L.append("### Stability overlays (overlays never rewrite a state)")
    L.append("")
    L.append("| # | metric | LOYO flips/runs | LOEO flips/runs | F3 ref "
             "N -> canonical N | F3 decimated MEMP | F3 sign flip |")
    L.append("|---|---|---|---|---|---|---|")
    for c in state_bearing["cells"]:
        L.append(
            f"| {c['cell']} | {c['metric']} | "
            f"{c['loyo_flips']}/{c['loyo_runs']} | "
            f"{c['loeo_flips']}/{c['loeo_runs']} | "
            f"{c['reference_n']} -> {c['f3_reference_n']} | "
            f"{_fmt(c['f3_memp'])} | {c['f3_sign_flip']} |")
    L.append("")
    L.append("### Per-cell denominators and availability")
    for c in state_bearing["cells"]:
        L.append("")
        L.append(f"- **Cell {c['cell']} - {c['measurement']} "
                 f"{c['metric']}**: basis {c['basis']}"
                 + (" (disclosed raw/raw fallback)" if c["basis_fallback"]
                    else "")
                 + f"; attempted {c['attempted_event_n']}, available "
                 f"{c['available_event_n']}; event-year vector "
                 f"{json.dumps(c['event_year_vector'])}; reference "
                 f"{c['reference_n']} (excluded by event proximity "
                 f"{c['excluded_event_proximity']}); placement year "
                 f"vector {json.dumps(c['placement_year_vector'])}")
        for date, reason in c["unavailable_events"]:
            L.append(f"  - unavailable event {date}: {reason}")
    L.append("")
    L.append("## 3. Descriptive [-20, -1] diagnostics (D1-D4, frozen "
             "order; explicitly no state)")
    L.append("")
    L.append(f"Frozen rule: {DIAGNOSTIC_SENTENCE}. The "
             "ordinary-reference and per-year calibration construction "
             "is structurally infeasible under the frozen geometry "
             "(j0-v1 section 10); no pseudo-calibration is invented, "
             "and no node state (ELEVATED, ORDINARY / UNRESOLVED, "
             "LOWER-MAGNITUDE, DISCORDANT) may be assigned.")
    L.append("")
    L.append("| diag | metric | window | events avail/att | median "
             "response | median |response| | direction |")
    L.append("|---|---|---|---|---|---|---|")
    for d in diagnostics["diagnostics"]:
        L.append(
            f"| {d['diagnostic']} | {d['metric']} | "
            f"[{d['window'][0]}, {d['window'][1]}] | "
            f"{d['available_event_n']} / {d['attempted_event_n']} | "
            f"{_fmt(d['median_response'])} | "
            f"{_fmt(d['median_abs_response'])} | {d['direction']} |")
    for d in diagnostics["diagnostics"]:
        L.append("")
        L.append(f"- **{d['diagnostic']} - {d['metric']}**: "
                 f"{DIAGNOSTIC_SENTENCE}.")
        for date, reason in d["unavailable_events"]:
            L.append(f"  - unavailable event {date}: {reason}")
    fun = diagnostics["reference_funnel"]
    L.append("")
    L.append("### Fail-loud reference funnel (documentation only)")
    L.append("")
    L.append(f"- era ordinary candidates: {fun['era_candidates']}; "
             f"response-gate casualties: {fun['gate_casualties']}; "
             f"span-19 exclusion casualties: "
             f"{fun['exclusion_casualties']}; eligible total: "
             f"{fun['eligible_total']}")
    L.append(f"- eligible per year: "
             f"{json.dumps(fun['eligible_per_year'])}")
    L.append(f"- event year vector: "
             f"{json.dumps(fun['event_year_vector'])}")
    L.append(f"- per-year placement matching mechanically executable: "
             f"{fun['per_year_matching_executable']} - and regardless, "
             "the frozen design assigns these diagnostics no reference, "
             "no MEMP, no calibration, and no state.")
    L.append("")
    L.append("## 4. Timing comparison with the published J1B result")
    L.append("")
    L.append("The published J1B 12-cell `[t, t+1]` surface is the "
             "post-anchor robustness result (Class B; tracked in "
             "`stats/J1B_FOMC_ROBUSTNESS_RESULTS.md`); the inherited "
             "Mission I 1d cells are Class A facts. The J2 `[-5, -1]` "
             "cells are a different statistical family with their own "
             "reference geometry: MEMPs are **not value-comparable** "
             "across the families and are never merged; the comparison "
             "below is state-based only, under the frozen "
             "interpretation rules of j0-v1 section 10.")
    L.append("")
    if published_j1b:
        L.append("| published J1B cell | lens | node state |")
        L.append("|---|---|---|")
        for no in sorted(published_j1b):
            p = published_j1b[no]
            L.append(f"| {no} {p['measurement']} | {p['lens']} | "
                     f"{p['state']} |")
        L.append("")
    for c in state_bearing["cells"]:
        st = c["node_state"]
        if st == "ELEVATED":
            line = ("the daily data do not isolate whether the response "
                    "began before or continued through the official "
                    "event window")
        elif st in ("ORDINARY_UNRESOLVED", "LOWER_MAGNITUDE"):
            line = ("the result is more concentrated around the "
                    "official anchor under daily measurement")
        else:
            line = ("the frozen response measures do not support a "
                    "single directional classification; the timing read "
                    "is unresolved for this metric")
        L.append(f"- cell {c['cell']} ({c['metric']}): pre-event state "
                 f"{st} beside the published post-anchor ELEVATED "
                 f"surface - {line}.")
    L.append("")
    L.append("Scheduled-event limitation (frozen): FOMC is a scheduled "
             "event family; anticipation is structurally plausible; "
             "daily close-to-close data cannot resolve intraday "
             "repricing, and the 2 p.m. ET statement release sits "
             "before the anchor-session close, so part of the "
             "same-session reaction is outside every daily window. No "
             "intraday timing claim is made.")
    L.append("")
    L.append("## 5. Collision register (exact [t, t+1] overlap only)")
    L.append("")
    inv = register["fomc_self"]
    L.append(f"- C1 family 1 - FOMC self-collision: checked invariant "
             f"holds (minimum anchor spacing "
             f"{inv['min_anchor_spacing']} sessions; 0 violations); no "
             "frame event shares another's [t, t+1] interval.")
    c1 = register["c1"]
    if not c1["adjudicable"]:
        L.append("- C1 families 2-3 - BLS CPI and BLS Employment "
                 "Situation: **unadjudicable in this execution**. "
                 f"{c1['reason']}.")
    else:  # pragma: no cover - no frozen register exists in this contract
        L.append("- C1 families 2-3: adjudicated from the frozen "
                 "register.")
    c2 = register["c2"]
    L.append(f"- C2 - cross-channel compound events: the tracked "
             f"`{c2['register']}` ({c2['register_dates']} calendar "
             f"dates) yields **{len(c2['tags'])}** tagged FOMC "
             "event(s).")
    for d in sorted(c2["tags"]):
        for entry in c2["tags"][d]:
            L.append(f"  - {d} (anchor "
                     f"{register['events'][d]['anchor_session']}): C2 "
                     f"via register date {entry['competing_date']} - "
                     f"{entry['overlap_basis']}; source support: "
                     "tracked G1B ledger / I0 section-8 register.")
    L.append(f"- C3: {register['c3']['note']}.")
    L.append("- Events outside the adjudicable registers are described "
             "as outside known-register collisions only; no stronger "
             "clean-window claim exists.")
    L.append("")
    L.append("## 6. Collision sensitivity (denominator-preserving "
             "re-reads of the existing J1B cells)")
    L.append("")
    L.append("The primary J1B result keeps all frozen FOMC events; "
             "these subset re-reads qualify it and never replace it. No "
             "numeric event floor governs any subset; feasibility is "
             "algorithmic only.")
    L.append("")
    for key in ("all", "collision_free", "c1_tagged", "c2_tagged"):
        block = subsets[key]
        if "status" in block:
            L.append(f"- **{key}**: {block['status']} - "
                     f"{block['reason']}.")
            continue
        extra = f" ({block['basis']})" if "basis" in block else ""
        L.append(f"- **{key}**: exact N = {block['n']}{extra}.")
    L.append("")
    for key in ("all", "collision_free", "c1_tagged", "c2_tagged"):
        sens = sensitivity.get(key)
        if sens is None:
            continue
        L.append(f"### Sensitivity re-read: {key}")
        L.append("")
        if "status" in sens:
            L.append(f"- {sens['status']}: {sens['reason']}.")
            L.append("")
            continue
        if sens.get("quoted_from_published"):
            L.append("- The all-events family IS the published J1B "
                     "surface (section 4 table); it was recomputed "
                     "through the identical frozen machinery and "
                     "reproduced exactly (6-decimal MEMP and "
                     "calibration agreement asserted before this "
                     "report was written). It is not restated as a new "
                     "statistic.")
            L.append("")
            continue
        L.append(f"- subset N = {sens['subset_n']}; calibration B = "
                 f"{sens['calibration']['B']}, seed "
                 f"{sens['calibration']['seed']}, policy "
                 f"`{sens['calibration']['rng_policy']}` (fresh stream "
                 "per sensitivity family; frozen J1B groups in fixed "
                 "order).")
        L.append("")
        L.append("| cell | measurement | lens | avail N | MEMP | calib "
                 "pct | sensitivity read | LOYO | LOEO |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for c in sens["cells"]:
            if "status" in c:
                L.append(f"| {c['cell']} | {c['measurement']} | "
                         f"{c['lens']} | {c['available_n']} | "
                         f"{c['status']} | - | - | - | - |")
            else:
                L.append(
                    f"| {c['cell']} | {c['measurement']} | {c['lens']} "
                    f"| {c['available_n']} | {_fmt(c['memp'])} | "
                    f"{_fmt(c['calibration_percentile'])} | "
                    f"{c['sensitivity_read']} | "
                    f"{c['loyo_flips']}/{c['loyo_runs']} | "
                    f"{c['loeo_flips']}/{c['loeo_runs']} |")
        if any("year_vector" in c for c in sens["cells"]):
            yv = next(c["year_vector"] for c in sens["cells"]
                      if "year_vector" in c)
            L.append("")
            L.append(f"- subset event-year distribution: "
                     f"{json.dumps(yv)}")
        L.append("")
    if conclusions_md:
        L.append(conclusions_md.rstrip())
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Live orchestration (gate -> load -> execute -> deterministic report)
# ---------------------------------------------------------------------------


def run_live_j2() -> dict[str, Any]:
    """The only authorized live path: J1A frozen-input gate -> read-only
    load -> pins -> J2 program. Returns every surface plus the gate
    record; report rendering is separate and deterministic."""
    authorization, inputs, record = live.gate_and_load()
    frame, basis, fallback = triple_joint_frame(inputs.closes)
    era_count = len(_era_indices(frame, inputs.era))
    i1.verify_pins(len(frame), era_count)

    state_bearing = run_state_bearing(inputs, authorization)
    diagnostics = run_diagnostics(inputs, authorization)

    opec = build_opec_register()
    c1_support = c1_macro_register_support()
    register = build_collision_register(
        frame, list(inputs.event_dates), opec_dates=list(opec.dates),
        c1_support=c1_support)
    subsets = collision_subsets(register, list(inputs.event_dates))

    published = parse_published_j1b_table(
        J1B_PUBLISHED_PATH.read_text(encoding="utf-8"))
    if len(published) != 12:
        raise J2IntegrityError(
            f"published J1B table parsed {len(published)} rows, "
            "expected 12 - refusing")
    substrates = [eng.build_cell_substrate(c, inputs)
                  for c in eng.FROZEN_CELLS]
    assert_allevents_reproduction(substrates, published)

    sensitivity: dict[str, Any] = {
        "all": {"label": "all", "quoted_from_published": True},
        "c1_tagged": {"status": "unadjudicable",
                      "reason": c1_support["reason"]},
        "collision_free": subset_reread(
            substrates, subsets["collision_free"]["dates"],
            label="collision_free"),
        "c2_tagged": subset_reread(
            substrates, subsets["c2_tagged"]["dates"], label="c2_tagged"),
    }
    return {"state_bearing": state_bearing, "diagnostics": diagnostics,
            "register": register, "subsets": subsets,
            "sensitivity": sensitivity, "published_j1b": published,
            "gate_record": record}


def _emit(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate", action="store_true",
                    help="run the frozen-input gate + manifest "
                         "reconciliation only (no outcome)")
    ap.add_argument("--execute", action="store_true",
                    help="gate, execute the frozen J2 program, write the "
                         "report")
    ap.add_argument("--verify", action="store_true",
                    help="re-execute and byte-compare against the report")
    ap.add_argument("--head", default="UNSET")
    ap.add_argument("--timestamp", default="UNSET")
    ap.add_argument("--out", default=str(REPORT_PATH))
    args = ap.parse_args(argv)
    if args.gate:
        failures = j1a.verify_frozen_inputs()
        manifest_ok = (len(TIMING_CELLS) == 4
                       and len(TIMING_DIAGNOSTICS) == 4)
        payload = {"failure_count": len(failures), "failures": failures,
                   "manifest_state_bearing": len(TIMING_CELLS),
                   "manifest_diagnostics": len(TIMING_DIAGNOSTICS),
                   "manifest_ok": manifest_ok}
        _emit(json.dumps(payload, indent=1, sort_keys=True) + "\n")
        return 0 if (not failures and manifest_ok) else 1
    if args.execute or args.verify:
        failures = j1a.verify_frozen_inputs()
        if failures or len(TIMING_CELLS) != 4 or len(
                TIMING_DIAGNOSTICS) != 4:
            _emit("J2 PRE-RUN GATE FAILED - refusing\n")
            return 1
        _emit(PRERUN_GATE_BANNER + "\n")
        surfaces = run_live_j2()
        prov = {"head": args.head, "timestamp": args.timestamp}
        text = render_j2_report(
            state_bearing=surfaces["state_bearing"],
            diagnostics=surfaces["diagnostics"],
            register=surfaces["register"],
            subsets=surfaces["subsets"],
            sensitivity=surfaces["sensitivity"],
            published_j1b=surfaces["published_j1b"],
            gate_record=surfaces["gate_record"],
            provenance=prov,
            conclusions_md=CONCLUSIONS_MD)
        out = Path(args.out)
        if args.verify:
            existing = out.read_text(encoding="utf-8")
            same = existing == text
            _emit(f"deterministic rerun byte-identical: {same}\n")
            return 0 if same else 1
        out.write_text(text, encoding="utf-8", newline="\n")
        _emit(f"wrote {out}\n")
        return 0
    ap.print_help()
    return 2


# Conclusions are interpretation authored AFTER the complete surface
# existed (full-surface-first rule); they carry no number not present in
# the mechanical surface above and use only the frozen vocabulary.
CONCLUSIONS_MD = """## 7. What the timing challenge supports

The frozen timing evidence is mixed, with cross-metric disagreement
inside the four-cell [-5, -1] surface:

- On the raw-return and SPY-relative lenses (cells 13-14, both
  ORDINARY / UNRESOLVED), the published post-anchor elevation is not
  accompanied by comparable frozen pre-event elevation: under the
  frozen interpretation rule, the result is more concentrated around
  the official anchor under daily measurement.
- On the sector-relative and SAR lenses (cells 15-16, both ELEVATED,
  0 LOYO / 0 LOEO / 0 F3 flips), the pre-event window carries the
  elevated state beside the elevated post-anchor surface: the daily
  data do not isolate whether the response began before or continued
  through the official event window.
- The response is not primarily pre-event on any lens, so the frozen
  section-15 withdrawal condition for the 1d concentration claim is
  not triggered; the concentration reading is lens-dependent as stated
  above.
- Collision qualification: under the adjudicable frozen registers, no
  FOMC event carries an exact [t, t+1] collision tag (FOMC-self holds
  as a checked invariant at minimum spacing 8; the C2 OPEC register
  tags 0 of 65). The known-register collision-free subset is therefore
  the full frozen frame, and its re-read reproduces the published J1B
  surface by construction - the published readout survives the
  collision-free sensitivity vacuously, because the adjudicable
  registers identify no collision to remove.

## 8. What weakened or remained unresolved

- The raw-return pre-event cell (13) is knife-edge fragile: MEMP
  0.491240 sits essentially at the 0.5 boundary, and the direction of
  (MEMP - 0.5) flips under 4/8 LOYO and 32/65 LOEO perturbations. Its
  ORDINARY / UNRESOLVED state is assigned once from the full-sample
  pair and is never rewritten by overlays, but the fragility is
  disclosed and mirrors the Mission I FOMC 5d raw knife-edge pattern.
- The four-cell surface disagrees across metrics (two ORDINARY /
  UNRESOLVED, two ELEVATED); no single pre-event reading exists.
- The C1 BLS CPI / Employment Situation branch is unadjudicable in
  this execution: the repository contains no source-pinned BLS release
  register covering the frozen era, so freedom from those releases is
  not certified for any event, and the C1-tagged sensitivity cannot
  execute. No substitute calendar was fetched.
- The C2-tagged subset is empty: insufficient subset under the frozen
  procedure; the C2-tagged descriptive comparison cannot execute.
- The [-20, -1] diagnostics remain descriptive-only by frozen design;
  the fail-loud funnel (1 eligible anchor, 2018 only; per-year
  matching not executable) mechanically confirms the pre-declared
  structural infeasibility. Their signed medians are small and mixed
  in direction and carry no ordinary-reference position.
- All of this is same-sample Class B evidence: post-outcome robustness
  under prospectively frozen new tests, never independent historical
  confirmation.

## 9. What J2 does not establish

- an anticipation mechanism;
- information leakage;
- insider activity of any kind;
- causality;
- prediction;
- tradeability;
- alpha;
- independent historical confirmation of Mission I or J1B;
- intraday response timing (daily close-to-close data cannot resolve
  it, and the 2 p.m. ET release sits before the anchor-session close);
- graph propagation (edge adjudication belongs to J3);
- any hypothesis-test conclusion (calibration percentiles are
  placement positions, not test outcomes);
- that any window is free of competing events (only outside
  known-register collisions, and the C1 macro branch is unadjudicable
  here);
- that MEMPs from different windows, references, or availability sets
  are value-comparable."""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
