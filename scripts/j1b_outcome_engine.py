"""J1B pre-outcome statistical engine (Mission J, j0-v1 contracts).

Pure in-memory implementation of the frozen 12-cell J1 pipeline: symmetric
response extraction, mid-rank event percentiles, MEMP, era-matched placement
calibration, the four frozen node states, role modifiers, and the inherited
LOYO/LOEO/F3 stability overlays - built and verified on synthetic fixtures
ONLY, before any real Mission J outcome exists.

Hard boundaries:

- This module performs no I/O of any kind: no cache, no database, no
  provider, no network, no file writes. It consumes plain in-memory
  ``EngineInputs`` and returns plain in-memory results.
- Execution requires an authorization object. Live execution requires the
  result of the (externally owned) J1A frozen-input verification gate via
  ``authorize_from_verification`` - this module deliberately implements no
  competing hash verifier. Synthetic runs require an explicit
  ``SyntheticFixtureAuthorization`` acknowledging the banner below, and
  their outputs always carry that banner.
- The cross-cell calibration RNG policy is the frozen J0 clarification
  ``grouped_shared_calendar_single_stream``: exactly one local
  ``numpy.random.default_rng(20180101)`` stream for the whole 12-cell
  family, consumed over three frozen placement groups in fixed order,
  with one drawn calendar reused across every cell of a group and exact
  identity-set equality asserted per group before any draw. No runtime
  alternative exists.
- Graph-edge adjudication belongs to J3 and does not exist here.
"""

from __future__ import annotations

import bisect
import math
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

import numpy as np

J1B_CONTRACT = "j1b-preoutcome-engine-v1"

SYNTHETIC_BANNER = "SYNTHETIC ENGINE VERIFICATION - NOT RESEARCH EVIDENCE"

ERA_START = "2018-01-01"
ERA_END = "2025-12-31"

BETA_ESTIMATION_RETURNS = 252
BETA_EMBARGO_SESSIONS = 20
BETA_HISTORY_PREREQ = BETA_ESTIMATION_RETURNS + BETA_EMBARGO_SESSIONS + 1
MAX_GAP_CALENDAR_DAYS = 5  # the shipped equity contiguity guard

CALIBRATION_B = 2000
CALIBRATION_SEED = 20180101
# The frozen J0 clarification: the ONLY calibration policy that exists.
CALIBRATION_RNG_POLICY = "grouped_shared_calendar_single_stream"
# Frozen placement groups (J0 clarification), processed in this exact
# order with one continuing RNG stream. Group membership is by frozen
# cell number; cell 12 (SHY raw return) belongs to the raw-ETF group
# despite its manifest position, and cells 10-11 share Treasury
# geometry (a calibration-geometry decision only - 2s10s stays
# contextual, outside every panel and all edge adjudication).
PLACEMENT_GROUPS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("rolling_beta_equity", (1, 2, 3, 4, 5)),
    ("raw_etf_returns", (6, 7, 8, 9, 12)),
    ("treasury_rates_geometry", (10, 11)),
)

NODE_STATES = ("ELEVATED", "ORDINARY_UNRESOLVED", "LOWER_MAGNITUDE",
               "DISCORDANT")

# J3-owned edge states: these strings must never appear in any J1B result.
EDGE_STATE_NAMES = ("PROPAGATED", "TRANSMISSION BREAK",
                    "UPSTREAM NOT ACTIVATED", "DOWNSTREAM WITHOUT UPSTREAM",
                    "MEASUREMENT UNRESOLVED")

CONTEXTUAL_MEASUREMENT = "2S10S_CMT"

PANELS: dict[str, tuple[str, ...]] = {
    "policy_rates_repricing": ("2Y_CMT", "SHY"),
    "balance_sheet_sensitive_second_order": ("KRE", "IAT", "KBE"),
    "broad_financial_sector": ("XLF", "VFH"),
}

_ROLE_BANK = "balance_sheet_sensitive_second_order"
_ROLE_SECTOR = "broad_financial_sector"
_ROLE_RATES = "policy_rates_repricing"
_ROLE_CURVE = "curve_shape_contextual_layer"

FROZEN_CELLS: tuple[dict[str, Any], ...] = (
    {"cell": 1, "measurement": "KRE", "lens": "rolling_beta_ar",
     "role": _ROLE_BANK, "m_class": "M3",
     "evidence_class": "A instrument; B statistic"},
    {"cell": 2, "measurement": "IAT", "lens": "rolling_beta_ar",
     "role": _ROLE_BANK, "m_class": "M3",
     "evidence_class": "B instrument; B statistic"},
    {"cell": 3, "measurement": "KBE", "lens": "rolling_beta_ar",
     "role": _ROLE_BANK, "m_class": "M3",
     "evidence_class": "B instrument; B statistic"},
    {"cell": 4, "measurement": "XLF", "lens": "rolling_beta_ar",
     "role": _ROLE_SECTOR, "m_class": "M3",
     "evidence_class": "A instrument; B statistic"},
    {"cell": 5, "measurement": "VFH", "lens": "rolling_beta_ar",
     "role": _ROLE_SECTOR, "m_class": "M3",
     "evidence_class": "B instrument; B statistic"},
    {"cell": 6, "measurement": "IAT", "lens": "raw_return",
     "role": _ROLE_BANK, "m_class": "M3",
     "evidence_class": "B instrument; B statistic"},
    {"cell": 7, "measurement": "KBE", "lens": "raw_return",
     "role": _ROLE_BANK, "m_class": "M3",
     "evidence_class": "B instrument; B statistic"},
    {"cell": 8, "measurement": "XLF", "lens": "raw_return",
     "role": _ROLE_SECTOR, "m_class": "M3",
     "evidence_class": "A instrument; B statistic"},
    {"cell": 9, "measurement": "VFH", "lens": "raw_return",
     "role": _ROLE_SECTOR, "m_class": "M3",
     "evidence_class": "B instrument; B statistic"},
    {"cell": 10, "measurement": "2Y_CMT", "lens": "raw_change",
     "role": _ROLE_RATES, "m_class": "M2",
     "evidence_class": "B statistic"},
    {"cell": 11, "measurement": "2S10S_CMT", "lens": "raw_change",
     "role": _ROLE_CURVE, "m_class": "M2",
     "evidence_class": "B statistic (underlying series A as a state)"},
    {"cell": 12, "measurement": "SHY", "lens": "raw_return",
     "role": _ROLE_RATES, "m_class": "M3",
     "evidence_class": "B instrument; B statistic"},
)


class AuthorizationError(RuntimeError):
    """Execution attempted without a valid input authorization."""


class BasisError(RuntimeError):
    """The frozen basis policy cannot produce a matched pair."""


class EngineNumericalError(RuntimeError):
    """Invalid numerical state (NaN/inf/zero price) - never propagated."""


class CalibrationInfeasibleError(RuntimeError):
    """Year-matched placement cannot execute under the frozen procedure."""


class CalibrationGeometryError(RuntimeError):
    """A frozen placement group's members do not share exact geometry.

    Identity sets must be exactly equal; counts alone are insufficient.
    No automatic split, no per-cell fallback, no new seed.
    """


# ---------------------------------------------------------------------------
# Authorization (fail-closed execution boundary)
# ---------------------------------------------------------------------------


_LIVE_STAMP: object = object()


@dataclass(frozen=True)
class FrozenInputAuthorization:
    """Proof that the externally owned frozen-input gate succeeded.

    Only :func:`authorize_from_verification` can mint a valid instance;
    direct construction lacks the module-private stamp and is rejected.
    """
    detail: str
    _stamp: Any = None


@dataclass(frozen=True)
class SyntheticFixtureAuthorization:
    """Explicit synthetic-run acknowledgement; never confusable with live."""
    acknowledgement: str

    def validate(self) -> None:
        if self.acknowledgement != SYNTHETIC_BANNER:
            raise AuthorizationError(
                "synthetic authorization requires the exact banner "
                "acknowledgement")


def authorize_from_verification(failures: Sequence[str], *,
                                detail: str) -> FrozenInputAuthorization:
    """Convert a frozen-input verification outcome into an authorization.

    ``failures`` is the failure list returned by the J1A verifier (owned
    elsewhere; this module never re-implements hashing). Any failure, or a
    non-list sentinel, refuses authorization.
    """
    if failures is None or len(list(failures)) != 0:
        raise AuthorizationError(
            f"frozen-input verification did not succeed: {list(failures)!r}")
    return FrozenInputAuthorization(detail=detail, _stamp=_LIVE_STAMP)


def _check_authorization(inputs: "EngineInputs", authorization: Any) -> bool:
    """Returns True when the run is synthetic; raises when not authorized."""
    if isinstance(authorization, SyntheticFixtureAuthorization):
        authorization.validate()
        if inputs.synthetic is not True:
            raise AuthorizationError(
                "synthetic authorization presented with inputs not marked "
                "synthetic - refusing")
        return True
    if isinstance(authorization, FrozenInputAuthorization):
        if authorization._stamp is not _LIVE_STAMP:
            raise AuthorizationError(
                "frozen-input authorization was not minted by "
                "authorize_from_verification - refusing")
        if inputs.synthetic:
            raise AuthorizationError(
                "live authorization presented with synthetic-flagged "
                "inputs - refusing")
        return False
    raise AuthorizationError(
        "no valid input authorization: live J1B requires the successful "
        "J1A frozen-input verification gate before any response value is "
        "computed")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineInputs:
    """Plain in-memory substrate. The engine performs no I/O to build it."""
    closes: Mapping[str, Mapping[str, Optional[Mapping[str, float]]]]
    treasury: Mapping[str, Mapping[str, float]]
    event_dates: Sequence[str]
    era: tuple[str, str] = (ERA_START, ERA_END)
    synthetic: bool = False


def last_index_le(sorted_dates: Sequence[str], target_iso: str
                  ) -> Optional[int]:
    """Largest index i with sorted_dates[i] <= target_iso (frozen anchor)."""
    idx = bisect.bisect_right(list(sorted_dates), target_iso) - 1
    return idx if idx >= 0 else None


def matched_basis_frame(asset: Mapping[str, Optional[Mapping[str, float]]],
                        bench: Optional[Mapping[str, Optional[
                            Mapping[str, float]]]] = None
                        ) -> tuple[list[str], str, bool]:
    """Frozen basis policy: adjusted/adjusted preferred; matched raw/raw as
    the only disclosed fallback; a cross-basis pair never exists."""
    def _series(side, key):
        s = side.get(key)
        return s if s else None

    a_adj = _series(asset, "adjusted")
    a_raw = _series(asset, "raw")
    if bench is None:
        if a_adj:
            return sorted(a_adj), "adjusted", False
        if a_raw:
            return sorted(a_raw), "raw", True
        raise BasisError("no usable basis for single-asset frame")
    b_adj = _series(bench, "adjusted")
    b_raw = _series(bench, "raw")
    if a_adj and b_adj:
        return sorted(set(a_adj) & set(b_adj)), "adjusted", False
    if a_raw and b_raw:
        return sorted(set(a_raw) & set(b_raw)), "raw", True
    raise BasisError(
        "no matched basis pair exists (cross-basis pairing is forbidden "
        "by the frozen policy)")


# ---------------------------------------------------------------------------
# Membership-free response functions (identical for event/reference/placebo)
# ---------------------------------------------------------------------------


_RESPONSE_EVALUATIONS = [0]  # architecture counter (no-recompute proof)


def _require_finite(*values: float) -> None:
    for v in values:
        if v is None or not math.isfinite(v):
            raise EngineNumericalError(
                f"non-finite value in response inputs: {v!r}")


def _window_gap_ok(frame: Sequence[str], idx: int) -> bool:
    a, b = frame[idx], frame[idx + 1]
    try:
        from datetime import date as _date
        gap = (_date.fromisoformat(b) - _date.fromisoformat(a)).days
    except (ValueError, TypeError):
        return False
    return gap <= MAX_GAP_CALENDAR_DAYS


def raw_return_response(closes: Mapping[str, float], frame: Sequence[str],
                        idx: int) -> tuple[Optional[float], Optional[str]]:
    """P[t+1]/P[t] - 1 on the matched-basis frame (frozen [t, t+1])."""
    _RESPONSE_EVALUATIONS[0] += 1
    if idx + 1 > len(frame) - 1:
        return None, "no_forward_session"
    if not _window_gap_ok(frame, idx):
        return None, "response_window_gap"
    p0, p1 = closes[frame[idx]], closes[frame[idx + 1]]
    _require_finite(p0, p1)
    if p0 == 0.0:
        raise EngineNumericalError("zero price at anchor session")
    return p1 / p0 - 1.0, None


def raw_change_response(levels: Sequence[float], idx: int
                        ) -> tuple[Optional[float], Optional[str]]:
    """y[t+1] - y[t] in level units on the series' own calendar."""
    _RESPONSE_EVALUATIONS[0] += 1
    if idx + 1 > len(levels) - 1:
        return None, "no_forward_session"
    y0, y1 = levels[idx], levels[idx + 1]
    _require_finite(y0, y1)
    return y1 - y0, None


def _ols_alpha_beta(x: Sequence[float], y: Sequence[float]
                    ) -> tuple[Optional[tuple[float, float]], Optional[str]]:
    n = float(len(x))
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((v - mx) * (v - mx) for v in x)
    if sxx == 0.0:
        return None, "zero_variance_benchmark"
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    beta = sxy / sxx
    alpha = my - beta * mx
    return (alpha, beta), None


def rolling_beta_response(asset_closes: Mapping[str, float],
                          bench_closes: Mapping[str, float],
                          frame: Sequence[str], idx: int
                          ) -> tuple[Optional[float], Optional[str],
                                     dict[str, Any]]:
    """The frozen 252/20 OLS-with-intercept abnormal return at [t, t+1].

    Estimation returns are r_j for j in {i-272, ..., i-21} (exactly 252
    paired observations, prices back to session i-273); the embargo is the
    20 sessions i-20 .. i-1; the 1d response is the single daily abnormal
    return at session i+1. No alternative window, embargo, or no-intercept
    variant exists anywhere in this module.
    """
    _RESPONSE_EVALUATIONS[0] += 1
    n = len(frame)
    if idx < BETA_HISTORY_PREREQ:
        return None, "insufficient_history_252_20", {}
    if idx + 1 > n - 1:
        return None, "no_forward_session", {}
    if not _window_gap_ok(frame, idx):
        return None, "response_window_gap", {}
    px_a = [asset_closes[frame[j]] for j in range(idx - 273, idx - 20)]
    px_b = [bench_closes[frame[j]] for j in range(idx - 273, idx - 20)]
    _require_finite(*px_a)
    _require_finite(*px_b)
    if any(p == 0.0 for p in px_a) or any(p == 0.0 for p in px_b):
        raise EngineNumericalError("zero price inside estimation sample")
    ra = [px_a[k] / px_a[k - 1] - 1.0 for k in range(1, len(px_a))]
    rb = [px_b[k] / px_b[k - 1] - 1.0 for k in range(1, len(px_b))]
    assert len(ra) == BETA_ESTIMATION_RETURNS  # structural, not data-driven
    coeffs, reason = _ols_alpha_beta(rb, ra)
    if coeffs is None:
        return None, reason, {}
    alpha, beta = coeffs
    a0, a1 = asset_closes[frame[idx]], asset_closes[frame[idx + 1]]
    b0, b1 = bench_closes[frame[idx]], bench_closes[frame[idx + 1]]
    _require_finite(a0, a1, b0, b1)
    r_asset = a1 / a0 - 1.0
    r_bench = b1 / b0 - 1.0
    ar = r_asset - (alpha + beta * r_bench)
    meta = {
        "n_estimation_returns": BETA_ESTIMATION_RETURNS,
        "estimation_first_session": frame[idx - 273],
        "estimation_last_session": frame[idx - 21],
        "embargo_sessions": BETA_EMBARGO_SESSIONS,
        "embargo_first_session": frame[idx - 20],
        "embargo_last_session": frame[idx - 1],
        "alpha": alpha,
        "beta": beta,
    }
    return ar, None, meta


# ---------------------------------------------------------------------------
# Frozen mid-rank percentile and MEMP (I0 section 13 verbatim)
# ---------------------------------------------------------------------------


def mid_rank_percentile(value: float, reference: Sequence[float], *,
                        absolute: bool) -> float:
    """pct = (#{r < v} + 0.5 * #{r = v}) / |R|; duplicates preserved."""
    if not reference:
        raise ValueError("empty reference multiset")
    v = abs(value) if absolute else value
    lt = eq = 0
    for r in reference:
        rr = abs(r) if absolute else r
        if rr < v:
            lt += 1
        elif rr == v:
            eq += 1
    return (lt + 0.5 * eq) / len(reference)


def memp(percentiles: Sequence[float]) -> float:
    """MEMP: the median across events of their magnitude percentiles."""
    return statistics.median(percentiles)


def calibration_percentile(observed: float,
                           placements: Sequence[float]) -> float:
    """Mid-rank position of the observed MEMP within the B placements;
    the observed value is external and the denominator is exactly B."""
    return mid_rank_percentile(observed, placements, absolute=False)


def _sorted_abs_percentile(sorted_abs: Sequence[float], value: float
                           ) -> float:
    a = abs(value)
    lo = bisect.bisect_left(sorted_abs, a)
    hi = bisect.bisect_right(sorted_abs, a)
    return (lo + 0.5 * (hi - lo)) / len(sorted_abs)


def classify_node_state(m: float, c: float) -> str:
    """The four frozen J0 section-4.2 states; [0.25, 0.75] inclusive."""
    if 0.25 <= c <= 0.75:
        return "ORDINARY_UNRESOLVED"
    if m > 0.5 and c > 0.75:
        return "ELEVATED"
    if m < 0.5 and c < 0.25:
        return "LOWER_MAGNITUDE"
    return "DISCORDANT"


def role_modifier(panel: Sequence[str], states: Mapping[str, str]) -> str:
    """Frozen J0 section-6.5 modifiers, primary-anchored (panel[0]).

    BROAD when every member shares the primary state; ROLE-CONSISTENT when
    at least one alternate shares it; PROXY-SPECIFIC when no alternate
    shares it but the alternates agree among themselves (the J0 section-5
    worked example); MEASUREMENT DISAGREEMENT otherwise.
    """
    primary = panel[0]
    s_p = states[primary]
    alt_states = [states[m] for m in panel[1:]]
    if all(s == s_p for s in alt_states):
        return "BROAD MEASUREMENT CONSISTENCY"
    if any(s == s_p for s in alt_states):
        return "ROLE-CONSISTENT"
    if len(set(alt_states)) == 1:
        return "PROXY-SPECIFIC"
    return "MEASUREMENT DISAGREEMENT"


def canonical_disjoint(indices: Sequence[int], *, span: int) -> list[int]:
    """Greedy earliest-first disjoint [t, t+span] windows: starts must be
    at least span+1 apart (the frozen I0 section-9 canonical geometry)."""
    picks: list[int] = []
    last: Optional[int] = None
    for i in sorted(indices):
        if last is None or i >= last + span + 1:
            picks.append(i)
            last = i
    return picks


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _flips(full_memp: float, perturbed: float) -> bool:
    """Frozen G6B convention: strict opposite signs of (MEMP - 0.5)."""
    return _sign(full_memp - 0.5) * _sign(perturbed - 0.5) == -1


# ---------------------------------------------------------------------------
# Cell substrate (responses built once; downstream consumes maps)
# ---------------------------------------------------------------------------


@dataclass
class CellSubstrate:
    cell: dict[str, Any]
    frame: list[str]
    basis: str
    basis_fallback: bool
    attempted_event_n: int
    events: list[dict[str, Any]]           # date, anchor_idx, value, reason
    event_percentiles: dict[str, float]    # event date -> percentile
    event_year_vector: dict[str, int]
    event_failure_counts: dict[str, int]
    reference_sessions: list[str]
    reference_values: dict[str, float]     # session -> response value
    sorted_abs_reference: list[float]
    self_pct: dict[str, float]             # session -> self-included pct
    reference_indices: list[int]
    excluded_event_proximity: int
    pool_by_year: dict[str, list[str]]

    @property
    def available_event_n(self) -> int:
        return len(self.event_percentiles)

    @property
    def available_event_dates(self) -> tuple[str, ...]:
        return tuple(sorted(self.event_percentiles))

    @property
    def observed_memp(self) -> Optional[float]:
        if not self.event_percentiles:
            return None
        return memp(list(self.event_percentiles.values()))


def _cell_series(cell: Mapping[str, Any], inputs: EngineInputs
                 ) -> tuple[list[str], str, bool, Any]:
    m, lens = str(cell["measurement"]), str(cell["lens"])
    if lens == "raw_change":
        key = "two_yr" if m == "2Y_CMT" else "spread_2s10s"
        series = dict(inputs.treasury[key])
        frame = sorted(series)
        levels = [series[d] for d in frame]
        return frame, "official_level", False, levels
    if lens == "rolling_beta_ar":
        frame, basis, fb = matched_basis_frame(inputs.closes[m],
                                               inputs.closes["SPY"])
        a = inputs.closes[m][basis]
        b = inputs.closes["SPY"][basis]
        return frame, basis, fb, (a, b)
    frame, basis, fb = matched_basis_frame(inputs.closes[m])
    return frame, basis, fb, inputs.closes[m][basis]


def _respond(lens: str, payload: Any, frame: Sequence[str], idx: int
             ) -> tuple[Optional[float], Optional[str]]:
    if lens == "rolling_beta_ar":
        a, b = payload
        v, reason, _meta = rolling_beta_response(a, b, frame, idx)
        return v, reason
    if lens == "raw_return":
        return raw_return_response(payload, frame, idx)
    return raw_change_response(payload, idx)


def build_cell_substrate(cell: Mapping[str, Any], inputs: EngineInputs
                         ) -> CellSubstrate:
    frame, basis, fallback, payload = _cell_series(cell, inputs)
    lens = str(cell["lens"])
    era_lo, era_hi = inputs.era

    # Event side (the response function never learns membership).
    events: list[dict[str, Any]] = []
    failures: Counter = Counter()
    anchor_indices: list[int] = []
    for d in sorted(inputs.event_dates):
        idx = last_index_le(frame, d)
        if idx is None:
            events.append({"date": d, "anchor_idx": None, "value": None,
                           "reason": "date_precedes_frame"})
            failures["date_precedes_frame"] += 1
            continue
        v, reason = _respond(lens, payload, frame, idx)
        events.append({"date": d, "anchor_idx": idx, "value": v,
                       "reason": reason})
        if reason is not None:
            failures[reason] += 1
        anchor_indices.append(idx)
    avail = [e for e in events if e["reason"] is None]
    avail_idx = [e["anchor_idx"] for e in avail]
    if len(set(avail_idx)) != len(avail_idx):
        raise RuntimeError("duplicate available event anchors - refusing")

    # Reference side: identical response gate, then era + exclusion.
    era_indices = [i for i, d in enumerate(frame) if era_lo <= d <= era_hi]
    anchor_set = set(anchor_indices)
    survivors: list[int] = []
    ref_values: dict[str, float] = {}
    for i in era_indices:
        v, reason = _respond(lens, payload, frame, i)
        if reason is None:
            survivors.append(i)
            ref_values[frame[i]] = v
    excluded = [i for i in survivors
                if any(abs(i - e) <= 1 for e in anchor_set)]
    eligible = [i for i in survivors
                if not any(abs(i - e) <= 1 for e in anchor_set)]
    sessions = [frame[i] for i in eligible]
    values = [ref_values[s] for s in sessions]
    sorted_abs = sorted(abs(v) for v in values)
    self_pct = {s: _sorted_abs_percentile(sorted_abs, ref_values[s])
                for s in sessions}
    ev_pct = {e["date"]: _sorted_abs_percentile(sorted_abs, e["value"])
              for e in avail}
    year_vec = Counter(frame[e["anchor_idx"]][:4] for e in avail)
    pool: dict[str, list[str]] = defaultdict(list)
    for s in sessions:
        pool[s[:4]].append(s)
    return CellSubstrate(
        cell=dict(cell), frame=frame, basis=basis, basis_fallback=fallback,
        attempted_event_n=len(inputs.event_dates), events=events,
        event_percentiles=ev_pct,
        event_year_vector=dict(sorted(year_vec.items())),
        event_failure_counts=dict(sorted(failures.items())),
        reference_sessions=sessions, reference_values=ref_values,
        sorted_abs_reference=sorted_abs, self_pct=self_pct,
        reference_indices=eligible,
        excluded_event_proximity=len(excluded),
        pool_by_year={y: sorted(v) for y, v in sorted(pool.items())})


# ---------------------------------------------------------------------------
# Calibration (I2C-A mechanics; cross-cell RNG policy must be explicit)
# ---------------------------------------------------------------------------


def _draw_group_placements(rng: np.random.Generator,
                           pool_by_year: Mapping[str, Sequence[str]],
                           year_vector: Mapping[str, int],
                           b: int) -> list[tuple[str, ...]]:
    years = sorted(year_vector)
    for y in years:
        have = len(pool_by_year.get(y, ()))
        if have < year_vector[y]:
            raise CalibrationInfeasibleError(
                f"year {y}: eligible pool {have} < required placement "
                f"count {year_vector[y]} - insufficient subset under the "
                "frozen procedure")
    arrays = {y: np.array(pool_by_year[y]) for y in years}
    draws: list[tuple[str, ...]] = []
    for _ in range(b):
        drawn: list[str] = []
        for y in years:
            pick = rng.choice(arrays[y], size=year_vector[y],
                              replace=False)
            drawn.extend(pick.tolist())
        draws.append(tuple(drawn))
    return draws


def assert_group_geometry(group_name: str,
                          members: Sequence[CellSubstrate]) -> None:
    """Frozen J0 clarification: exact identity-set equality per group.

    Every member must share (1) the eligible ordinary-anchor identity
    set, (2) the available-event identity set, and (3) the
    available-event year-count vector. Counts alone are insufficient;
    any difference fails loudly with the offending cells named.
    """
    anchor = members[0]
    a_no = anchor.cell["cell"]
    for sub in members[1:]:
        s_no = sub.cell["cell"]
        if list(sub.reference_sessions) != list(anchor.reference_sessions):
            raise CalibrationGeometryError(
                f"group {group_name}: cells {a_no} and {s_no} do not share "
                "the exact eligible ordinary-anchor identity set - "
                "refusing (no split, no fallback, no new seed)")
        if sub.available_event_dates != anchor.available_event_dates:
            raise CalibrationGeometryError(
                f"group {group_name}: cells {a_no} and {s_no} do not share "
                "the exact available-event identity set - refusing")
        if sub.event_year_vector != anchor.event_year_vector:
            raise CalibrationGeometryError(
                f"group {group_name}: cells {a_no} and {s_no} do not share "
                "the exact available-event year-count vector - refusing")


def calibrate_cells(substrates: Sequence[CellSubstrate], *,
                    b: int = CALIBRATION_B, seed: int = CALIBRATION_SEED
                    ) -> dict[int, dict[str, Any]]:
    """The frozen ``grouped_shared_calendar_single_stream`` calibration.

    Exactly one local numpy Generator seeded at 20180101 serves the whole
    12-cell family; the three frozen placement groups are processed in
    their fixed order; within a group one drawn calendar per placement is
    reused across every member cell; the stream continues across groups
    with no reset. No other policy exists.
    """
    by_no = {sub.cell["cell"]: sub for sub in substrates}
    rng = np.random.default_rng(seed)  # the ONE stream, never reset
    out: dict[int, dict[str, Any]] = {}
    for group_name, cell_nos in PLACEMENT_GROUPS:
        members = [by_no[no] for no in cell_nos if no in by_no]
        if not members:
            continue
        assert_group_geometry(group_name, members)
        year_vector = members[0].event_year_vector
        draws = _draw_group_placements(rng, members[0].pool_by_year,
                                       year_vector, b)
        for sub in members:
            lut = sub.self_pct
            dist = [memp([lut[s] for s in drawn]) for drawn in draws]
            obs = sub.observed_memp
            out[sub.cell["cell"]] = {
                "calibration_percentile": calibration_percentile(obs, dist),
                "placement_year_vector": dict(year_vector),
                "placement_pool_sizes": {y: len(v) for y, v in
                                         sub.pool_by_year.items()},
                "placement_group": group_name,
            }
    return out


def calibration_placement_probe(inputs: EngineInputs, *, cell_no: int,
                                b: int) -> dict[str, Any]:
    """Bounded synthetic probe: runs the REAL frozen grouped sequence at
    the given b and returns the requested cell's group calendars, so the
    continuing-stream and shared-calendar semantics are observable."""
    subs = [build_cell_substrate(c, inputs) for c in FROZEN_CELLS]
    by_no = {sub.cell["cell"]: sub for sub in subs}
    rng = np.random.default_rng(CALIBRATION_SEED)
    for group_name, cell_nos in PLACEMENT_GROUPS:
        members = [by_no[no] for no in cell_nos]
        assert_group_geometry(group_name, members)
        draws = _draw_group_placements(rng, members[0].pool_by_year,
                                       members[0].event_year_vector, b)
        if cell_no in cell_nos:
            return {"group": group_name, "sessions": draws}
    raise ValueError(f"unknown cell {cell_no}")


# ---------------------------------------------------------------------------
# Stability overlays (re-rank only; never a response recomputation)
# ---------------------------------------------------------------------------


def _rerank_events(sub: CellSubstrate, sorted_abs: Sequence[float],
                   *, skip_year: Optional[str] = None) -> list[float]:
    pcts = []
    for e in sub.events:
        if e["reason"] is not None:
            continue
        year = sub.frame[e["anchor_idx"]][:4]
        if skip_year is not None and year == skip_year:
            continue
        pcts.append(_sorted_abs_percentile(sorted_abs, e["value"]))
    return pcts


def loyo_overlay(sub: CellSubstrate) -> dict[str, Any]:
    """F1-style: remove each year's EVENTS AND ordinary reference dates
    (the pinned I0 section-15 / I2C-B convention), re-rank survivors."""
    full = sub.observed_memp
    years = sorted({s[:4] for s in sub.reference_sessions}
                   | set(sub.event_year_vector))
    flips = 0
    detail: dict[str, dict[str, Any]] = {}
    for y in years:
        reduced_vals = [abs(sub.reference_values[s])
                        for s in sub.reference_sessions if s[:4] != y]
        reduced_sorted = sorted(reduced_vals)
        pcts = _rerank_events(sub, reduced_sorted, skip_year=y)
        m = memp(pcts) if pcts else None
        flipped = m is not None and _flips(full, m)
        flips += 1 if flipped else 0
        detail[y] = {"memp": m, "flip": flipped,
                     "full_reference_n": len(sub.reference_sessions),
                     "reduced_reference_n": len(reduced_sorted),
                     "removed_reference_dates_year": y}
    return {"runs": len(years), "flips": flips, "detail": detail}


def loeo_overlay(sub: CellSubstrate) -> dict[str, Any]:
    """F2-style: remove one event at a time; the reference is untouched."""
    full = sub.observed_memp
    pcts = list(sub.event_percentiles.values())
    flips = 0
    for i in range(len(pcts)):
        rest = pcts[:i] + pcts[i + 1:]
        if rest and _flips(full, memp(rest)):
            flips += 1
    return {"runs": len(pcts), "flips": flips,
            "reference_n_constant": True}


def f3_overlay(sub: CellSubstrate) -> dict[str, Any]:
    """F3: canonical greedy earliest-first disjoint decimation (span 1)."""
    full = sub.observed_memp
    picks = canonical_disjoint(sub.reference_indices, span=1)
    pick_set = set(picks)
    frame = sub.frame
    reduced_sorted = sorted(abs(sub.reference_values[frame[i]])
                            for i in picks)
    pcts = _rerank_events(sub, reduced_sorted)
    m = memp(pcts) if pcts else None
    return {"original_reference_n": len(sub.reference_indices),
            "decimated_reference_n": len(pick_set),
            "decimated_memp": m,
            "change": None if (m is None or full is None) else m - full,
            "sign_flip": bool(m is not None and full is not None
                              and _flips(full, m))}


def loyo_probe(inputs: EngineInputs, *, cell_no: int) -> dict[str, Any]:
    sub = build_cell_substrate(FROZEN_CELLS[cell_no - 1], inputs)
    return loyo_overlay(sub)["detail"]


def loeo_probe(inputs: EngineInputs, *, cell_no: int) -> dict[str, Any]:
    sub = build_cell_substrate(FROZEN_CELLS[cell_no - 1], inputs)
    return loeo_overlay(sub)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class EngineResult:
    cells: list[dict[str, Any]]
    panel_summaries: dict[str, dict[str, Any]]
    contextual: dict[str, Any]
    calibration: dict[str, Any]
    synthetic: bool
    banner: str
    metadata: dict[str, Any] = field(default_factory=dict)


def run_engine(inputs: EngineInputs, authorization: Any) -> EngineResult:
    """The complete frozen 12-cell pipeline (responses built exactly once).

    Fail-closed: refuses to run without a valid authorization object.
    Live authorization additionally requires non-synthetic inputs;
    synthetic authorization requires synthetic-flagged inputs. The
    calibration policy is the frozen grouped_shared_calendar_single_stream
    clarification; no runtime selector exists.
    """
    synthetic = _check_authorization(inputs, authorization)
    eval_before = _RESPONSE_EVALUATIONS[0]
    t0 = time.perf_counter()
    substrates = [build_cell_substrate(c, inputs) for c in FROZEN_CELLS]
    t1 = time.perf_counter()
    substrate_count = _RESPONSE_EVALUATIONS[0] - eval_before
    calib = calibrate_cells(substrates)
    t2 = time.perf_counter()

    cells: list[dict[str, Any]] = []
    states: dict[tuple[str, str], str] = {}
    for sub in substrates:
        c = sub.cell
        no = c["cell"]
        m = sub.observed_memp
        cp = calib[no]["calibration_percentile"]
        state = classify_node_state(m, cp)
        loyo = loyo_overlay(sub)
        loeo = loeo_overlay(sub)
        f3 = f3_overlay(sub)
        states[(c["measurement"], c["lens"])] = state
        cells.append({
            "cell": no,
            "measurement": c["measurement"],
            "lens": c["lens"],
            "role": c["role"],
            "m_class": c["m_class"],
            "evidence_class": c["evidence_class"],
            "basis": sub.basis,
            "basis_fallback": sub.basis_fallback,
            "attempted_event_n": sub.attempted_event_n,
            "available_event_n": sub.available_event_n,
            "event_year_vector": sub.event_year_vector,
            "event_failure_counts": sub.event_failure_counts,
            "unavailable_events": [[e["date"], e["reason"]]
                                   for e in sub.events
                                   if e["reason"] is not None],
            "reference_n": len(sub.reference_sessions),
            "excluded_event_proximity": sub.excluded_event_proximity,
            "memp": m,
            "calibration_percentile": cp,
            "placement_year_vector": calib[no]["placement_year_vector"],
            "node_state": state,
            "loyo_runs": loyo["runs"], "loyo_flips": loyo["flips"],
            "loeo_runs": loeo["runs"], "loeo_flips": loeo["flips"],
            "f3_reference_n": f3["decimated_reference_n"],
            "f3_memp": f3["decimated_memp"],
            "f3_change": f3["change"],
            "f3_sign_flip": f3["sign_flip"],
        })
    total_evals = _RESPONSE_EVALUATIONS[0] - eval_before

    # Panel summaries use the frozen node-state lens per J0: the rolling
    # 252/20 AR for equity roles, the raw change for the rates panel
    # primary (2Y) with SHY's raw return as the alternate.
    panel_state_lens = {
        "policy_rates_repricing": {"2Y_CMT": "raw_change",
                                   "SHY": "raw_return"},
        "balance_sheet_sensitive_second_order": {
            "KRE": "rolling_beta_ar", "IAT": "rolling_beta_ar",
            "KBE": "rolling_beta_ar"},
        "broad_financial_sector": {"XLF": "rolling_beta_ar",
                                   "VFH": "rolling_beta_ar"},
    }
    panel_summaries: dict[str, dict[str, Any]] = {}
    for role, members in PANELS.items():
        lens_map = panel_state_lens[role]
        member_states = {mm: states[(mm, lens_map[mm])] for mm in members}
        panel_summaries[role] = {
            "members": list(members),
            "states": member_states,
            "modifier": role_modifier(members, member_states),
        }
    ctx_state = states[(CONTEXTUAL_MEASUREMENT, "raw_change")]
    contextual = {
        "measurement": CONTEXTUAL_MEASUREMENT,
        "node_state": ctx_state,
        "note": ("curve-shape contextual layer: standalone reference, "
                 "calibration, and state; outside every proxy panel and "
                 "outside all edge adjudication (J3)"),
    }
    banner = SYNTHETIC_BANNER if synthetic else (
        "J1B result surface (live)")
    return EngineResult(
        cells=cells, panel_summaries=panel_summaries, contextual=contextual,
        calibration={"B": CALIBRATION_B, "seed": CALIBRATION_SEED,
                     "rng_policy": CALIBRATION_RNG_POLICY},
        synthetic=synthetic, banner=banner,
        metadata={
            "contract": J1B_CONTRACT,
            "substrate_seconds": t1 - t0,
            "calibration_seconds": t2 - t1,
            "substrate_response_count": substrate_count,
            "response_evaluations": total_evals,
        })


def result_as_dict(result: EngineResult) -> dict[str, Any]:
    """Deterministic plain-dict view (volatile timings excluded)."""
    return {
        "cells": result.cells,
        "panel_summaries": result.panel_summaries,
        "contextual": result.contextual,
        "calibration": result.calibration,
        "synthetic": result.synthetic,
        "banner": result.banner,
    }


# ---------------------------------------------------------------------------
# Deterministic report renderer (frozen order; no highlighting)
# ---------------------------------------------------------------------------


def render_report(result: EngineResult) -> str:
    L: list[str] = []
    L.append(f"# J1B 12-cell result surface ({J1B_CONTRACT})")
    L.append("")
    if result.synthetic:
        L.append(f"**{SYNTHETIC_BANNER}**")
        L.append("")
        L.append("Every value below derives from deterministic synthetic "
                 "fixtures; nothing here is a Mission J research result.")
        L.append("")
    L.append("Cells appear in the frozen J0 order; none is highlighted, "
             "none is ordered by value, and no hypothesis-test vocabulary "
             "appears. Edge adjudication is out of scope here (it belongs "
             "to J3).")
    for c in result.cells:
        L.append("")
        L.append(f"## Cell {c['cell']} - {c['measurement']} ({c['lens']})")
        L.append("")
        L.append(f"- role: {c['role']}; M-class: {c['m_class']}; evidence "
                 f"class: {c['evidence_class']}")
        L.append(f"- basis: {c['basis']}"
                 + (" (disclosed raw/raw fallback)" if c["basis_fallback"]
                    else ""))
        L.append(f"- attempted event N: {c['attempted_event_n']}; "
                 f"available event N: {c['available_event_n']}")
        L.append(f"- event-year vector: {c['event_year_vector']}")
        L.append(f"- event failures: {c['event_failure_counts']}")
        L.append(f"- reference N: {c['reference_n']} (excluded by event "
                 f"proximity: {c['excluded_event_proximity']})")
        L.append(f"- MEMP: {c['memp']}")
        L.append(f"- calibration percentile: "
                 f"{c['calibration_percentile']} (B placements, observed "
                 f"external)")
        L.append(f"- node state: {c['node_state']}")
        L.append(f"- LOYO: {c['loyo_flips']} flips / {c['loyo_runs']} "
                 f"runs; LOEO: {c['loeo_flips']} flips / "
                 f"{c['loeo_runs']} runs")
        L.append(f"- F3: reference {c['reference_n']} -> canonical "
                 f"{c['f3_reference_n']}; decimated MEMP {c['f3_memp']}; "
                 f"sign flip: {c['f3_sign_flip']}")
    L.append("")
    L.append("## Panel state summaries (no edge adjudication)")
    for role, s in result.panel_summaries.items():
        L.append("")
        L.append(f"### {role}")
        L.append(f"- members: {', '.join(s['members'])}")
        for mm, st in s["states"].items():
            L.append(f"- {mm}: {st}")
        L.append(f"- role modifier: {s['modifier']}")
    L.append("")
    L.append("## Curve-shape contextual layer")
    L.append("")
    L.append(f"- {result.contextual['measurement']}: "
             f"{result.contextual['node_state']}")
    L.append(f"- {result.contextual['note']}")
    L.append("")
    L.append(f"Calibration: B = {result.calibration['B']}, seed = "
             f"{result.calibration['seed']}, cross-cell RNG policy = "
             f"{result.calibration['rng_policy']}.")
    L.append("")
    return "\n".join(L)
