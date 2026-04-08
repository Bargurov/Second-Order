"""
tools/reserve_stress_overlay_validation.py

Empirical validation for the Current Account + FX Reserve Stress overlay.

Goal
----
The overlay introduces a small number of scoring weights and movement
thresholds in ``reserve_stress_overlay`` (DXY moderate/strong/extreme,
crude moderate/strong, credit widening, real-yield rise, dual-squeeze
bonus, risk-off regime bonus).  This script runs the module against a
representative scenario bank covering every institutional stress
pattern the overlay is supposed to surface, and asserts each scenario
lands in the expected pressure bucket + channel.

If any assertion fails, the weights must be retuned before the changes
ship — the validation run is part of the overlay's definition.

Scenario bank
-------------
The nine scenarios below are drawn from actual market regimes:

    1. 2022 OPEC+ cut            -> dual_oil_dollar, elevated
    2. Mild crude rally only     -> oil_import_squeeze, moderate
    3. Oil crash                 -> commodity_exporter_cushion, contained
    4. 2015 EM-FX squeeze        -> usd_funding_stress, elevated
    5. Mild dollar firming       -> usd_funding_stress, contained
    6. Disinflation / DXY down   -> commodity_exporter_cushion, contained
    7. Wheat export ban          -> food_importer_stress, moderate
    8. Benign tape               -> none, contained
    9. Dual squeeze (crude+DXY+credit+real-yield+risk-off) -> dual_oil_dollar, elevated
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reserve_stress_overlay as rs  # noqa: E402


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Scenario:
    name: str
    headline: str
    crude_5d: Optional[float]
    dxy_5d: Optional[float]
    credit_5d: Optional[float]
    tip_5d: Optional[float]         # TIP price move; real-yield move = -tip_5d
    theme: str
    stress_regime_label: str
    expected_channel: str
    expected_label: str             # "elevated" / "moderate" / "contained"
    expected_score_min: int
    expected_score_max: int


_SCENARIOS: list[_Scenario] = [
    # 1. Classic oil + dollar dual squeeze
    _Scenario(
        name="2022 OPEC+ cut + dollar rally",
        headline="OPEC+ surprise cut triggers crude rally alongside dollar strength",
        crude_5d=6.0, dxy_5d=1.5, credit_5d=0.7, tip_5d=-0.35,
        theme="oil",
        stress_regime_label="Systemic Stress",
        expected_channel="dual_oil_dollar",
        expected_label="elevated",
        expected_score_min=80, expected_score_max=100,
    ),
    # 2. Mild oil rally, no dollar leg.  Grounded: a lone 3.5% crude
    # print without any reinforcing signal (no DXY, no credit widening,
    # no real-yield rise, no risk-off label) registers as "contained"
    # external-balance pressure — exactly one driver firing, weight +20.
    # This is the correct institutional read: one commodity print does
    # not itself trigger a reserve-stress alert.
    _Scenario(
        name="Mild crude rally only",
        headline="Crude firms on inventory draw",
        crude_5d=3.5, dxy_5d=0.2, credit_5d=0.1, tip_5d=0.0,
        theme="oil",
        stress_regime_label="Mixed",
        expected_channel="oil_import_squeeze",
        expected_label="contained",
        expected_score_min=15, expected_score_max=29,
    ),
    # 3. Oil crash — relief channel
    _Scenario(
        name="Oil crash on demand fears",
        headline="Crude prices tumble 6%",
        crude_5d=-6.0, dxy_5d=0.1, credit_5d=0.0, tip_5d=0.2,
        theme="oil",
        stress_regime_label="Mixed",
        expected_channel="commodity_exporter_cushion",
        expected_label="contained",
        expected_score_min=0, expected_score_max=20,
    ),
    # 4. Classic EM-FX funding squeeze
    _Scenario(
        name="EM-FX funding squeeze",
        headline="Dollar broad rally on hawkish Fed",
        crude_5d=0.0, dxy_5d=1.8, credit_5d=0.9, tip_5d=-0.5,
        theme="none",
        stress_regime_label="Systemic Stress",
        expected_channel="usd_funding_stress",
        expected_label="elevated",
        expected_score_min=70, expected_score_max=100,
    ),
    # 5. Mild dollar firming
    _Scenario(
        name="Mild dollar firming",
        headline="Dollar firms against G10",
        crude_5d=0.0, dxy_5d=0.7, credit_5d=0.0, tip_5d=0.0,
        theme="none",
        stress_regime_label="Mixed",
        expected_channel="usd_funding_stress",
        expected_label="contained",
        expected_score_min=0, expected_score_max=29,
    ),
    # 6. Disinflation + dollar retreat
    _Scenario(
        name="Disinflation + dollar retreat",
        headline="Cooler CPI drives dollar weakness",
        crude_5d=-0.3, dxy_5d=-1.4, credit_5d=-0.3, tip_5d=0.4,
        theme="none",
        stress_regime_label="Calm",
        expected_channel="commodity_exporter_cushion",
        expected_label="contained",
        expected_score_min=0, expected_score_max=20,
    ),
    # 7. Wheat export ban
    _Scenario(
        name="Wheat export ban",
        headline="Major exporter announces wheat export ban",
        crude_5d=0.1, dxy_5d=0.3, credit_5d=0.1, tip_5d=0.0,
        theme="food",
        stress_regime_label="Mixed",
        expected_channel="food_importer_stress",
        expected_label="contained",
        expected_score_min=0, expected_score_max=29,
    ),
    # 8. Benign tape
    _Scenario(
        name="Benign tape",
        headline="Tech earnings beat",
        crude_5d=0.2, dxy_5d=0.1, credit_5d=0.0, tip_5d=0.05,
        theme="none",
        stress_regime_label="Calm",
        expected_channel="none",
        expected_label="contained",
        expected_score_min=0, expected_score_max=15,
    ),
    # 9. Extreme multi-driver shock
    _Scenario(
        name="Extreme multi-driver shock",
        headline="Oil rally coincides with dollar surge and credit widening",
        crude_5d=7.0, dxy_5d=2.5, credit_5d=1.2, tip_5d=-0.8,
        theme="oil",
        stress_regime_label="Systemic Stress",
        expected_channel="dual_oil_dollar",
        expected_label="elevated",
        expected_score_min=90, expected_score_max=100,
    ),
]


# ---------------------------------------------------------------------------
# Replay harness
# ---------------------------------------------------------------------------


def _tot(crude_5d, dxy_5d, theme):
    return {
        "available": True, "stale": False,
        "signals": {
            "crude_5d": crude_5d, "dxy_5d": dxy_5d,
            "matched_theme": theme, "thresholds": "",
        },
    }


def _rates(tip_5d):
    return {
        "regime": "Mixed",
        "real_proxy": {"label": "TIP", "value": 108.0, "change_5d": tip_5d},
        "nominal": {"label": "10Y", "value": 4.2, "change_5d": 0.1},
        "breakeven_proxy": {"label": "BE", "change_5d": None},
    }


def _stress(dollar_5d, credit_5d, regime_label):
    """Synthesise a stress_regime payload matching the shape
    ``market_check.compute_stress_regime`` emits — including the
    boolean signals the overlay's structured parser now reads.

    ``signals.credit_widening`` is set iff ``credit_5d >= 0.5`` (the
    same rule the live classifier applies on HY/SHY divergence).
    This lets the overlay's funding-pressure detection land on a
    structured flag instead of scraping the regime label string.
    """
    signals: dict = {}
    if credit_5d is not None and credit_5d >= 0.5:
        signals["credit_widening"] = True
    return {
        "regime": regime_label,
        "signals": signals,
        "detail": {
            "safe_haven": {
                "assets": {"Gold": None, "Dollar": dollar_5d, "Long Bonds": None},
            },
            "credit": {"spread_5d": credit_5d},
        },
    }


def _run(scenario: _Scenario) -> dict:
    return rs.compute_reserve_stress(
        headline=scenario.headline,
        mechanism_text="",
        terms_of_trade=_tot(scenario.crude_5d, scenario.dxy_5d, scenario.theme),
        rates_context=_rates(scenario.tip_5d),
        stress_regime=_stress(scenario.dxy_5d, scenario.credit_5d,
                              scenario.stress_regime_label),
    )


def _fmt_row(scenario: _Scenario, out: dict, ok: bool) -> str:
    score = out.get("pressure_score", 0)
    channel = out.get("dominant_channel", "?")
    label = out.get("pressure_label", "?")
    mark = "OK " if ok else "FAIL"
    return (
        f"  {mark}  {scenario.name:<38}  "
        f"channel={channel:<28}  "
        f"score={score:>3}  label={label:<10}  "
        f"(expected: {scenario.expected_channel} / "
        f"{scenario.expected_label} / "
        f"{scenario.expected_score_min}-{scenario.expected_score_max})"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print("Reserve Stress Overlay — Scenario Validation")
    print("=" * 96)
    print(f"Scoring weights (from reserve_stress_overlay.py):")
    print(f"  DXY moderate / strong / extreme   "
          f"-> +{rs._W_DXY_MODERATE} / +{rs._W_DXY_STRONG} / +{rs._W_DXY_EXTREME}")
    print(f"  Credit widening (>= {rs._CREDIT_WIDENING_5D_PCT}%)         "
          f"-> +{rs._W_CREDIT_WIDENING}")
    print(f"  Oil squeeze + strong-crude bonus  "
          f"-> +{rs._W_CRUDE_OIL_THEME} / +{rs._W_CRUDE_STRONG}")
    print(f"  Real-yield rise (>= {rs._REAL_YIELD_RISE_5D_PCT}%)         "
          f"-> +{rs._W_REAL_YIELD_RISE}")
    print(f"  Dual squeeze bonus                "
          f"-> +{rs._W_DUAL_SQUEEZE}")
    print(f"  Risk-off regime bonus             "
          f"-> +{rs._W_STRESS_REGIME_HIT}")
    print(f"Pressure bucket boundaries: "
          f"contained <{rs._PRESSURE_MODERATE_MIN} / "
          f"moderate <{rs._PRESSURE_ELEVATED_MIN} / "
          f"elevated >={rs._PRESSURE_ELEVATED_MIN}")
    print()

    failures: list[str] = []
    for scenario in _SCENARIOS:
        out = _run(scenario)
        channel = out.get("dominant_channel")
        label = out.get("pressure_label")
        score = out.get("pressure_score", 0)

        ok = (
            channel == scenario.expected_channel
            and label == scenario.expected_label
            and scenario.expected_score_min <= score <= scenario.expected_score_max
        )
        print(_fmt_row(scenario, out, ok))
        if not ok:
            failures.append(
                f"{scenario.name}: got channel={channel} label={label} "
                f"score={score}; expected "
                f"{scenario.expected_channel}/{scenario.expected_label}/"
                f"{scenario.expected_score_min}-{scenario.expected_score_max}"
            )

    print()
    if failures:
        print("FAIL — scenarios out of expected ranges:")
        for msg in failures:
            print(f"  - {msg}")
        print()
        print("Retune reserve_stress_overlay weights/thresholds and re-run.")
        return 1

    print("OK - all scenarios landed in expected channel + pressure bucket.")
    print(f"     Weights locked.  {len(_SCENARIOS)}/{len(_SCENARIOS)} scenarios passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
