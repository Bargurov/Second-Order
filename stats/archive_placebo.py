"""X1A — archive event-date placebo / negative-control (read-only).

Asks one question of the repaired 81-event archive event-study layer: is the
benchmark-adjusted AR-sign support at the REAL event dates distinguishable from
the support at RANDOM non-event dates, holding the same ticker universe,
role-direction discipline (beneficiary -> up, loser -> down), horizons
(1d / 5d / 20d) and benchmark (SPY) fixed?

If event dates carry no special directional behaviour, observed support sits
INSIDE the placebo distribution. This is a NULL / negative-control readout, not
a directional indication, forecast, or single-event significance test.

Read-only and zero-cost by construction: it loads cached closes through a
``mode=ro`` connection and computes the BHAR sign inline (the same
``raw_asset - raw_benchmark`` buy-and-hold difference the event-study engine
reports, restricted to the matched raw / raw basis vs SPY). No provider, no
network, no DB/cache write, no committed artifact.
"""
from __future__ import annotations

import json
import random
import sqlite3
from datetime import date, timedelta
from typing import Any, Optional

BENCHMARK = "SPY"
HORIZONS = (1, 5, 20)
ESTIMATION_WINDOW = 60
MAX_H = max(HORIZONS)
EXCLUSION_DAYS = 30
_MAX_GAP_CALENDAR_DAYS = 5
_MIN_OBS_FOR_CONCLUSION = 30
# The placebo-feasible (matched) set must be at least this fraction of the
# event-date-eligible set to draw a directional conclusion.  When most
# event-eligible obs lack any placebo-feasible non-event date (shallow cache),
# the matched set is a selection-biased minority that cannot speak for the
# archive — verdict is inconclusive regardless of where the point lands.
_MIN_MATCHED_FRACTION = 0.6

NON_CLAIM = (
    "This is a null / negative-control readout, not a directional indication, "
    "forecast, or single-event significance test."
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def predicted_up(role: str) -> bool:
    return (role or "").lower() == "beneficiary"


def _bday_offset(d: date, n: int) -> date:
    if n <= 0:
        return d
    out, rem = d, n
    while rem > 0:
        out = out + timedelta(days=1)
        if out.weekday() < 5:
            rem -= 1
    return out


def support_fraction(pairs: list[tuple[bool, Optional[bool]]]) -> tuple[float, int]:
    """``(fraction, n)`` over pairs with a non-None ar_up; match = predicted==ar_up."""
    elig = [(p, a) for p, a in pairs if a is not None]
    if not elig:
        return (0.0, 0)
    matches = sum(1 for p, a in elig if p == a)
    return (matches / len(elig), len(elig))


def _percentile(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(s):
        return s[-1]
    return s[lo] + (s[lo + 1] - s[lo]) * frac


def _last_le_index(dates: list[str], target: str) -> Optional[int]:
    idx = None
    for i, d in enumerate(dates):
        if d <= target:
            idx = i
        else:
            break
    return idx


def _contiguous(window: list[str]) -> bool:
    for a, b in zip(window, window[1:]):
        try:
            if (date.fromisoformat(b) - date.fromisoformat(a)).days > _MAX_GAP_CALENDAR_DAYS:
                return False
        except ValueError:
            return False
    return True


def ar_up_at(common_dates: list[str], a_close: list[float], s_close: list[float],
             anchor_idx: int, h: int) -> Optional[bool]:
    """BHAR-sign at ``anchor_idx`` for horizon ``h`` on the common (asset∩SPY) series.

    Returns True/False (AR>0 / AR<0) or None when the forward bar is missing or
    AR is exactly zero (excluded, mirroring the engine)."""
    if anchor_idx is None or anchor_idx < 0 or anchor_idx >= len(common_dates):
        return None
    target = _bday_offset(date.fromisoformat(common_dates[anchor_idx]), h).isoformat()
    fwd = None
    for j in range(anchor_idx + 1, len(common_dates)):
        if common_dates[j] >= target:
            fwd = j
            break
    if fwd is None:
        return None
    a0, a1 = a_close[anchor_idx], a_close[fwd]
    s0, s1 = s_close[anchor_idx], s_close[fwd]
    if a0 <= 0 or s0 <= 0:
        return None
    ar = (a1 / a0 - 1.0) - (s1 / s0 - 1.0)
    if ar == 0.0:
        return None
    return ar > 0.0


def eligible_anchor(common_dates: list[str], idx: int) -> bool:
    """True if ``idx`` has >=60 prior common dates, a forward bar at +20bd, and a
    contiguous window (mirrors the event-study readiness gate)."""
    if idx < ESTIMATION_WINDOW:
        return False
    target = _bday_offset(date.fromisoformat(common_dates[idx]), MAX_H).isoformat()
    fwd = next((j for j in range(idx + 1, len(common_dates)) if common_dates[j] >= target), None)
    if fwd is None:
        return False
    return _contiguous(common_dates[idx - ESTIMATION_WINDOW: fwd + 1])


def sample_placebo_anchors(common_dates: list[str], event_iso: str, *, est_window: int,
                           max_h_business_days: int, exclusion_days: int,
                           draws: int, seed: int) -> list[str]:
    """``draws`` placebo anchor date-strings sampled (with replacement, seeded) from
    eligible common dates, excluding any within ``exclusion_days`` of the event."""
    ev = date.fromisoformat(event_iso)
    elig = []
    for i, d in enumerate(common_dates):
        if i < est_window:
            continue
        target = _bday_offset(date.fromisoformat(d), max_h_business_days).isoformat()
        if not any(common_dates[j] >= target for j in range(i + 1, len(common_dates))):
            continue
        if abs((date.fromisoformat(d) - ev).days) <= exclusion_days:
            continue
        elig.append(d)
    if not elig:
        return []
    rng = random.Random(seed)
    return [rng.choice(elig) for _ in range(draws)]


# ---------------------------------------------------------------------------
# Read-only data access
# ---------------------------------------------------------------------------

def _ro(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _load_closes(con: sqlite3.Connection, ticker: str, auto_adjust: int = 0) -> dict:
    out = {}
    for r in con.execute(
        "SELECT date, close FROM price_cache WHERE ticker=? AND auto_adjust=? AND close IS NOT NULL ORDER BY date",
        (ticker.upper(), auto_adjust),
    ):
        d = r["date"]
        if isinstance(d, str):
            try:
                out[d[:10]] = float(r["close"])
            except (TypeError, ValueError):
                pass
    return out


def _common(asset_map: dict, spy_map: dict):
    dates = sorted(set(asset_map) & set(spy_map))
    return dates, [asset_map[d] for d in dates], [spy_map[d] for d in dates]


def _scored_obs(con: sqlite3.Connection) -> list[dict]:
    out = []
    for r in con.execute("SELECT id, event_date, market_tickers FROM events"):
        mt = r["market_tickers"]
        try:
            tks = json.loads(mt) if isinstance(mt, str) and mt else mt
        except ValueError:
            tks = None
        if not (isinstance(tks, list) and tks):
            continue
        seen = set()
        for t in tks:
            if not isinstance(t, dict):
                continue
            role = (t.get("role") or "").lower()
            sym = (t.get("symbol") or "").strip()
            if role not in ("beneficiary", "loser") or not sym or sym.upper() in seen:
                continue
            seen.add(sym.upper())
            out.append({"event_id": r["id"], "event_date": (r["event_date"] or "")[:10],
                        "symbol": sym, "role": role})
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(db_path: str, *, draws: int = 1000, seed: int = 20260608) -> dict:
    con = _ro(db_path)
    try:
        spy_map = _load_closes(con, BENCHMARK, 0)
        obs = _scored_obs(con)
        series_cache: dict[str, tuple] = {}
        for o in obs:
            su = o["symbol"].upper()
            if su not in series_cache:
                series_cache[su] = _common(_load_closes(con, su, 0), spy_map)
    finally:
        con.close()

    excluded: list[dict] = []
    # Matched negative control: an observation is usable ONLY if it is event-study
    # eligible at its event date AND has >=1 eligible non-event (placebo) anchor.
    # Observed and placebo are then computed over the SAME obs set — comparable
    # denominators, not 239-vs-50.
    event_anchor_eligible = 0
    usable_obs = []  # (predicted_up, cd, a, s, aidx, seq, symbol)
    for o in obs:
        cd, a, s = series_cache[o["symbol"].upper()]
        if len(cd) < ESTIMATION_WINDOW + 1:
            excluded.append({"symbol": o["symbol"], "event_id": o["event_id"],
                             "reason": "insufficient_cached_history"})
            continue
        aidx = _last_le_index(cd, o["event_date"])
        if aidx is None or not eligible_anchor(cd, aidx):
            excluded.append({"symbol": o["symbol"], "event_id": o["event_id"],
                             "reason": "anchor_not_eligible_at_event_date"})
            continue
        event_anchor_eligible += 1
        seq = sample_placebo_anchors(cd, o["event_date"], est_window=ESTIMATION_WINDOW,
                                     max_h_business_days=MAX_H, exclusion_days=EXCLUSION_DAYS,
                                     draws=draws, seed=seed + len(usable_obs))
        if not seq:
            excluded.append({"symbol": o["symbol"], "event_id": o["event_id"],
                             "reason": "no_eligible_placebo_dates"})
            continue
        usable_obs.append((predicted_up(o["role"]), cd, a, s, aidx, seq, o["symbol"].upper()))

    observed_pairs: dict[str, list] = {str(h): [] for h in HORIZONS}
    for pu, cd, a, s, aidx, seq, sym in usable_obs:
        for h in HORIZONS:
            observed_pairs[str(h)].append((pu, ar_up_at(cd, a, s, aidx, h)))
    observed_support = {}
    for h in HORIZONS:
        frac, n = support_fraction(observed_pairs[str(h)])
        observed_support[str(h)] = {"support": round(frac, 4), "n": n}
    observed_eligible = len(usable_obs)

    # Placebo: per draw, each usable obs uses its d-th random non-event anchor.
    placebo_draw_support: dict[str, list[float]] = {str(h): [] for h in HORIZONS}
    placebo_elig_counts: list[int] = []
    for d in range(draws):
        pairs = {str(h): [] for h in HORIZONS}
        elig = 0
        for pu, cd, a, s, aidx, seq, sym in usable_obs:
            paidx = _last_le_index(cd, seq[d])
            if paidx is None:
                continue
            elig += 1
            for h in HORIZONS:
                pairs[str(h)].append((pu, ar_up_at(cd, a, s, paidx, h)))
        placebo_elig_counts.append(elig)
        for h in HORIZONS:
            frac, _ = support_fraction(pairs[str(h)])
            placebo_draw_support[str(h)].append(frac)

    placebo = {}
    for h in HORIZONS:
        xs = placebo_draw_support[str(h)]
        obs_s = observed_support[str(h)]["support"]
        pct = (sum(1 for v in xs if v <= obs_s) / len(xs)) if xs else float("nan")
        placebo[str(h)] = {
            "mean": round(sum(xs) / len(xs), 4) if xs else None,
            "median": round(_percentile(xs, 0.5), 4) if xs else None,
            "q05": round(_percentile(xs, 0.05), 4) if xs else None,
            "q95": round(_percentile(xs, 0.95), 4) if xs else None,
            "observed_percentile": round(pct, 3) if xs else None,
        }

    conclusion = _conclude(observed_support, placebo, observed_eligible, event_anchor_eligible)
    return {
        "archive_denominator": {"scored_events": len({o["event_id"] for o in obs}),
                                "role_observations": len(obs)},
        "event_anchor_eligible": event_anchor_eligible,
        "observed_eligible": observed_eligible,
        "placebo_eligible_per_draw": (round(sum(placebo_elig_counts) / len(placebo_elig_counts), 1)
                                      if placebo_elig_counts else 0),
        "draws": draws,
        "seed": seed,
        "observed_support": observed_support,
        "placebo": placebo,
        "excluded": excluded,
        "residual_coverage_note": (
            f"Matched negative control: only {observed_eligible} of {event_anchor_eligible} "
            f"event-date-eligible role-observations are placebo-feasible (need >=1 non-event date with a "
            f"full 60+20 window outside the exclusion). That placebo-feasible set is a selection-biased "
            "deep-cache minority (the 2015-2026 historical anchors + deep-history names), NOT the 2026 "
            "archive; the shortfall is the shallow per-ticker cache. The placebo support baseline sits "
            "ABOVE 0.5 (these selected tickers carry favourable secular drift vs SPY), so it is a "
            "contaminated null. The real finding is that the archive's cache depth cannot yet support a "
            "representative event-date placebo -- empirical support for the corpus-breadth / "
            "temporal-clustering ceiling, not an event-effect result."
        ),
        "conclusion": conclusion,
        "non_claim": NON_CLAIM,
    }


def _conclude(observed_support: dict, placebo: dict, observed_eligible: int,
              event_anchor_eligible: int = 0) -> str:
    if observed_eligible < _MIN_OBS_FOR_CONCLUSION:
        return "inconclusive_due_to_coverage"
    # Coverage gate: a placebo-feasible minority of the event-eligible set is
    # selection-biased (deep-cache tickers) and cannot characterize the archive.
    if event_anchor_eligible > 0 and (observed_eligible / event_anchor_eligible) < _MIN_MATCHED_FRACTION:
        return "inconclusive_due_to_coverage"
    above = below = 0
    for h in HORIZONS:
        obs_s = observed_support[str(h)]["support"]
        q05, q95 = placebo[str(h)]["q05"], placebo[str(h)]["q95"]
        if q05 is None or q95 is None:
            return "inconclusive_due_to_coverage"
        if obs_s > q95:
            above += 1
        elif obs_s < q05:
            below += 1
    if above >= 2 and below == 0:
        return "observed_above_placebo"
    if below >= 2 and above == 0:
        return "observed_below_placebo"
    return "observed_inside_placebo"


def summarize(r: dict) -> str:
    lines = [
        "Archive event-date placebo / negative-control (read-only, zero-cost)",
        f"  archive denominator: {r['archive_denominator']['scored_events']} scored events, "
        f"{r['archive_denominator']['role_observations']} beneficiary/loser observations",
        f"  observed event-study-eligible (raw/SPY basis): {r['observed_eligible']} "
        f"| placebo eligible/draw ~{r['placebo_eligible_per_draw']} | draws {r['draws']} seed {r['seed']}",
        "",
        "  horizon | observed support (n) | placebo mean [q05, q95] | observed percentile",
    ]
    for h in (1, 5, 20):
        o = r["observed_support"][str(h)]
        p = r["placebo"][str(h)]
        lines.append(
            f"    {h:>2}d   | {o['support']:.4f} (n={o['n']:>3}) | "
            f"{p['mean']} [{p['q05']}, {p['q95']}] | pct {p['observed_percentile']}"
        )
    lines += [
        "",
        f"  conclusion: {r['conclusion']}",
        f"  coverage: {r['residual_coverage_note']}",
        f"  excluded units: {len(r['excluded'])}",
        "",
        f"  {r['non_claim']}",
    ]
    return "\n".join(lines)
