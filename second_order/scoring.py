"""OLS, signed percentile ranks and verdicts. No I/O or model calls."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Literal
import numpy as np
from .anchors import DataUnavailable
from .data import Series
from .registry import Observable

Verdict = Literal["supported", "contradicted", "inconclusive", "unavailable", "excluded", "pending"]


@dataclass(frozen=True)
class Rules:
    version: str = "0.5.0"
    upper: float = 0.80
    lower: float = 0.20
    reference_days: int = 250
    min_windows: int = 120
    estimation_days: int = 250
    estimation_gap: int = 10
    placebo_dates: int = 50

    def __post_init__(self) -> None:
        if not (0 < self.lower < self.upper < 1):
            raise ValueError("Invalid percentile thresholds")
        if not (0 < self.min_windows <= self.reference_days):
            raise ValueError("Invalid reference availability gate")
        if self.estimation_days < 3 or self.estimation_gap < 0 or self.placebo_dates < 1:
            raise ValueError("Invalid estimation or placebo configuration")

    @property
    def hash(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Model:
    alpha: float
    beta: float
    start: int  # First and last price index of the fitting window.
    end: int


@dataclass(frozen=True)
class Score:
    verdict: Verdict
    measured_change: float | None = None
    signed_move: float | None = None
    percentile_rank: float | None = None
    reference_windows: int = 0
    non_overlapping_reference_windows: int = 0
    reason: str = ""
    model: Model | None = None  # The fitted market model, for equity legs only.


def rank_counts(value: float, reference: list[float]) -> tuple[int, int, int]:
    """Reference windows below, equal to and above value; the percentile rank is built from these."""
    if not reference:
        raise DataUnavailable("No reference windows")
    if not math.isfinite(value) or any(not math.isfinite(x) for x in reference):
        raise ValueError("Ranks require finite values")
    below, equal = sum(x < value for x in reference), sum(x == value for x in reference)
    return below, equal, len(reference) - below - equal


def percentile_rank(value: float, reference: list[float]) -> float:
    below, equal, _ = rank_counts(value, reference)
    return (below + 0.5 * equal) / len(reference)


def verdict(signed_move: float, rank: float, rules: Rules) -> Verdict:
    if not math.isfinite(signed_move) or not math.isfinite(rank) or not 0 <= rank <= 1:
        raise ValueError("Verdict requires a finite move and a valid percentile")
    if signed_move > 0 and rank >= rules.upper:
        return "supported"
    if signed_move < 0 and rank <= rules.lower:
        return "contradicted"
    return "inconclusive"


def values(series: Series, start: int, end: int) -> np.ndarray:
    points = series.observations[start:end + 1]
    if start < 0 or end >= len(series.observations) or any(p.value is None for p in points):
        raise DataUnavailable("Missing observation inside the required window")
    return np.asarray([p.value for p in points], dtype=float)


def fit_market_model(asset: Series, benchmark: Series | None, anchor: int, rules: Rules) -> Model:
    """OLS over estimation_days returns ending estimation_gap observations before anchor."""
    if benchmark is None or [p.at for p in asset.observations] != [p.at for p in benchmark.observations]:
        raise DataUnavailable("Aligned SPY observation grid required")
    end = anchor - rules.estimation_gap
    start = end - rules.estimation_days
    if start < 0:
        raise DataUnavailable("Insufficient pre-event history for the market-model estimation window")
    asset_prices, market_prices = values(asset, start, end), values(benchmark, start, end)
    if np.any(asset_prices <= 0) or np.any(market_prices <= 0):
        raise DataUnavailable("Market model requires positive adjusted prices")
    y, x = np.diff(asset_prices) / asset_prices[:-1], np.diff(market_prices) / market_prices[:-1]
    design = np.column_stack([np.ones(len(x)), x])
    if np.linalg.matrix_rank(design) < 2:
        raise DataUnavailable("Market model has a constant benchmark")
    alpha, beta = np.linalg.lstsq(design, y, rcond=None)[0]
    return Model(float(alpha), float(beta), start, end)


def measure(series: Series, observable: Observable, start: int, horizon: int,
            model: Model | None = None, benchmark: Series | None = None) -> float:
    end = start + horizon
    prices = values(series, start, end)
    if observable.requires_contract:
        contracts = {p.contract for p in series.observations[start:end + 1]}
        if None in contracts or len(contracts) != 1:
            raise DataUnavailable("Verified same-contract window required; no unknown rolls")
    if observable.measurement == "yield_bp":
        return float((prices[-1] - prices[0]) * 100)
    if np.any(prices <= 0):
        raise DataUnavailable("Returns require positive prices")
    if observable.measurement == "return_pct":
        return float((prices[-1] / prices[0] - 1) * 100)
    if model is None or benchmark is None:
        raise DataUnavailable("Market model required")
    market_prices = values(benchmark, start, end)
    if np.any(market_prices <= 0):
        raise DataUnavailable("Benchmark prices must be positive")
    actual = np.diff(prices) / prices[:-1]
    market = np.diff(market_prices) / market_prices[:-1]
    return float(np.sum(actual - model.alpha - model.beta * market) * 100)


def reference_moves(series: Series, observable: Observable, reference_end: int, horizon: int, direction: int,
                    rules: Rules, model: Model | None = None,
                    benchmark: Series | None = None) -> tuple[list[float], list[int]]:
    """Signed moves of every usable same-horizon window ending at or before reference_end."""
    reference, starts = [], []
    for start in range(max(0, reference_end - rules.reference_days), reference_end - horizon + 1):
        try:
            reference.append(direction * measure(series, observable, start, horizon, model, benchmark))
            starts.append(start)
        except DataUnavailable:
            continue
    return reference, starts


def non_overlapping(starts: list[int], horizon: int) -> int:
    disjoint, next_start = 0, -1
    for start in starts:
        if start >= next_start:
            disjoint += 1
            next_start = start + horizon
    return disjoint


def score_at(series: Series, observable: Observable, anchor: int, reference_end: int,
             horizon: int, expected: str, rules: Rules, benchmark: Series | None = None,
             available_end: int | None = None, reference_out: list[float] | None = None,
             estimation_anchor: int | None = None) -> Score:
    """Score the move from anchor; reference windows end at reference_end.

    The market model is fitted before estimation_anchor (default reference_end, the pre-publication
    event anchor), never before the scoring anchor, and never past available_end. reference_out, when
    given, receives the exact signed reference moves this call ranks against.
    """
    if expected not in {"up", "down"} or horizon not in {1, 5, 20}:
        raise ValueError("Unknown direction or scored horizon")
    available_end = reference_end if available_end is None else available_end
    estimation_anchor = reference_end if estimation_anchor is None else estimation_anchor
    try:
        if observable.measurement == "market_model":
            if estimation_anchor - rules.estimation_gap > available_end:
                raise DataUnavailable("Model estimation would use an observation after the freeze")
            if series.basis != "adjusted" or benchmark is None or benchmark.basis != "adjusted":
                raise DataUnavailable("Equity research requires adjusted asset and SPY prices")
            model = fit_market_model(series, benchmark, estimation_anchor, rules)
        else:
            model = None
        move = measure(series, observable, anchor, horizon, model, benchmark)
        direction = 1 if expected == "up" else -1
        reference, starts = reference_moves(series, observable, reference_end, horizon, direction, rules,
                                            model, benchmark)
        if reference_out is not None:
            reference_out[:] = reference
        disjoint = non_overlapping(starts, horizon)
        if len(reference) < rules.min_windows:
            return Score("unavailable", move, reference_windows=len(reference),
                         non_overlapping_reference_windows=disjoint, reason="Insufficient reference windows",
                         model=model)
        signed = direction * move
        rank = percentile_rank(signed, reference)
        return Score(verdict(signed, rank, rules), move, signed, rank, len(reference), disjoint, model=model)
    except DataUnavailable as exc:
        return Score("unavailable", reason=str(exc))
