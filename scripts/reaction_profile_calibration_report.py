"""reaction_profile_calibration_report.py

READ-ONLY empirical calibration audit of the production
``reaction_profile_v1`` classification rules (the per-ticker
``flat / hold / fade / reverse / insufficient`` labels composed by
``reaction_profile.compute_reaction_profile`` and hydrated by
``reaction_profile_hydration``).

What this does
--------------
It answers one question: do the current noise floors (1.0% / 2.0% / 3.0%
at 5d / 20d / 60d), the 0.70 hold-retention threshold, the 2dp rounding
order, the raw-price basis and the horizon surface produce a stable,
honest description of the archived price paths, or are the labels
materially driven by those unvalidated conventions?  It does NOT test
whether any label is "accurate" - there is no independent ground truth
for whether a reaction truly held, faded or reversed - and it changes no
production behaviour or label.  The production classifier is reproduced
audit-side and compared observation-by-observation; any mismatch is a
blocker, never a silent recalibration.

Safety boundary
---------------
* reads from a caller-supplied ``--db-path`` over ``mode=ro`` SQLite
  connections only (events, price_cache, event_hygiene);
* the canonical hydrator ``hydrate_per_ticker_profile`` is invoked with
  an injected read-only cache reader that byte-mirrors
  ``price_cache.read_window_no_fetch`` (same SQL, same frame builder) so
  the production seam (which would run ``CREATE TABLE IF NOT EXISTS`` on
  first use) never touches the live file;
* never mutates the database, never calls a provider, never touches the
  network, never triggers paid analysis, never refreshes prices;
* the accepted denominator is the established accepted-track-record gate
  (``db.NON_THESIS_STAGES`` stage exclusion + ``db.synthetic_seed_ids``),
  never a hand-picked event list;
* clustering reuses the canonical K2 market-story rules
  (``scripts.effective_independent_evidence_report.build_clusters``) and
  the established primary-ticker resolution
  (``scripts.event_date_quality_report._primary_ticker``).

Reproduce:
    python -m scripts.reaction_profile_calibration_report --db-path events.db
    python -m scripts.reaction_profile_calibration_report --db-path events.db --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import date as _date
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import db  # noqa: E402
import reaction_profile as _rp  # noqa: E402
from reaction_profile_hydration import (  # noqa: E402
    _closes_from_frame,
    _coerce_anchor,
    _quarantined_horizons,
    hydrate_per_ticker_profile,
)
from scripts.effective_independent_evidence_report import (  # noqa: E402
    _parse_duplicate_ids,
    build_clusters,
)
from scripts.event_date_quality_report import _primary_ticker  # noqa: E402

CONTRACT_VERSION = "reaction-profile-calibration-v1"

# ---------------------------------------------------------------------------
# Production rule, read from the production module so the audit always
# characterizes the rule that actually ships (a drift in production
# constants is then visible in the report, never silently re-pinned here).
# ---------------------------------------------------------------------------

PEAK_HORIZONS: tuple[str, ...] = ("5d", "20d", "60d")
_HORIZON_BARS = {"5d": 5, "20d": 20, "60d": 60}
AUDIT_NOISE_FLOORS = {
    "5d": _rp._NOISE_5D_PCT,
    "20d": _rp._NOISE_20D_PCT,
    "60d": _rp._NOISE_60D_PCT,
}
AUDIT_RETENTION_THRESHOLD = _rp._FADE_HOLD_THRESHOLD
_ROUND_DP = _rp._ROUND_DP
LABELS: tuple[str, ...] = ("hold", "fade", "reverse", "flat")

# ---------------------------------------------------------------------------
# Audit conventions (documented guard constants).  These are review
# conventions for THIS audit, not new production thresholds: they bound
# when the empirical surface is too thin, too boundary-dense or too
# unstable to support a calibration conclusion, and when a data-derived
# candidate is even admissible.  Every input they consume is printed in
# the report so a reviewer can dispute the branch taken.
# ---------------------------------------------------------------------------

_MIN_SCORABLE_EVENTS_20D = 15   # fewer scorable events than this at the
                                # consumer-privileged horizon cannot
                                # characterize the rule
_MIN_ELIGIBLE_HOLDFADE = 15     # fewer hold/fade-eligible observations
                                # cannot characterize the 0.70 threshold
_DENSE_BOUNDARY_SHARE = 0.30    # this share of eligible ratios within
                                # +/-0.05 of 0.70 makes any threshold
                                # conclusion arbitrary
_ROUNDING_FLIP_SHARE_MAX = 0.10  # labels this rounding-driven are a
                                 # calibration problem in themselves
_DENSE_MIN_OBS = 5              # observations inside the boundary band
                                # before the current value counts as
                                # sitting in a dense region
_GAP_DOMINANCE = 3.0            # a candidate plateau must be this many
                                # times wider than the gap around the
                                # current value
_MIN_PLATEAU_WIDTH_RATIO = 0.10   # minimum visible plateau, ratio units
_MIN_PLATEAU_WIDTH_FLOOR_PP = 0.5  # minimum visible plateau, percent pts
_RATIO_BAND = 0.05              # boundary band around 0.70
_FLOOR_BAND_PP = 0.25           # boundary band around a noise floor
_INTERIOR_LO_Q = 0.10           # plateau search is restricted to the
_INTERIOR_HI_Q = 0.90           # interior of the observed support
_VOL_MIN_OBS = 15               # pre-anchor bars needed on this many
                                # observations before a volatility-scaled
                                # floor could even be evaluated locally
_VOL_MIN_SHARE = 0.5
_EPS = 1e-9


# ---------------------------------------------------------------------------
# Audit-side reproduction of the production classifier.
# Byte-equivalent by construction: the same expressions as
# ``reaction_profile._pct_from_anchor`` / ``_peak_in_window`` /
# ``_fade_or_hold_label``, with rounding applied as a separate final step
# so both the rounded (production) and unrounded labels are observable.
# ---------------------------------------------------------------------------


def _is_finite_number(v: Any) -> bool:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    f = float(v)
    if f != f:
        return False
    if f == float("inf") or f == float("-inf"):
        return False
    return True


def audit_pct_from_anchor(closes: Any, n: int) -> Optional[float]:
    """Unrounded twin of ``reaction_profile._pct_from_anchor``."""
    if not isinstance(closes, (list, tuple)):
        return None
    if len(closes) < n + 1:
        return None
    anchor = closes[0]
    if not _is_finite_number(anchor) or anchor == 0:
        return None
    target = closes[n]
    if not _is_finite_number(target):
        return None
    return (float(target) / float(anchor) - 1.0) * 100.0


def audit_peak_in_window(
    closes: Any, n: int,
) -> tuple[Optional[float], Optional[int]]:
    """Unrounded twin of ``reaction_profile._peak_in_window``.

    Same selection rule: largest absolute PRICE deviation from the
    anchor, strict ``>`` so ties keep the earliest bar.
    """
    if not isinstance(closes, (list, tuple)):
        return (None, None)
    if len(closes) < n + 1:
        return (None, None)
    anchor = closes[0]
    if not _is_finite_number(anchor) or anchor == 0:
        return (None, None)
    best_idx: Optional[int] = None
    best_abs = -1.0
    for i in range(1, n + 1):
        c = closes[i]
        if not _is_finite_number(c):
            continue
        diff_abs = abs(float(c) - float(anchor))
        if diff_abs > best_abs:
            best_abs = diff_abs
            best_idx = i
    if best_idx is None:
        return (None, None)
    peak = (float(closes[best_idx]) / float(anchor) - 1.0) * 100.0
    return (peak, best_idx)


def audit_label(
    peak: Optional[float], final: Optional[float], noise: float,
) -> str:
    """The production decision table, verbatim order.

    1. insufficient - peak or final missing
    2. flat         - |peak| below the horizon noise floor
    3. reverse      - peak and final disagree on sign (final == 0 is NOT
                      a sign flip; it falls through to the ratio branch)
    4. flat         - |peak| == 0 (defensive; unreachable with positive
                      floors)
    5. hold         - |final| / |peak| at or above the retention
                      threshold (inclusive)
    6. fade         - otherwise
    """
    if peak is None or final is None:
        return "insufficient"
    if abs(peak) < noise:
        return "flat"
    if (peak > 0 and final < 0) or (peak < 0 and final > 0):
        return "reverse"
    if abs(peak) == 0:
        return "flat"
    if abs(final) / abs(peak) >= AUDIT_RETENTION_THRESHOLD:
        return "hold"
    return "fade"


def classify_observation(closes: Any) -> dict:
    """Rounded + unrounded classification of one close path, per horizon."""
    out: dict[str, dict] = {}
    for h in PEAK_HORIZONS:
        n = _HORIZON_BARS[h]
        noise = AUDIT_NOISE_FLOORS[h]
        final_u = audit_pct_from_anchor(closes, n)
        peak_u, ttp = audit_peak_in_window(closes, n)
        peak_r = None if peak_u is None else round(peak_u, _ROUND_DP)
        final_r = None if final_u is None else round(final_u, _ROUND_DP)
        label_r = audit_label(peak_r, final_r, noise)
        label_u = audit_label(peak_u, final_u, noise)
        ratio_u = ratio_r = None
        if label_r in ("hold", "fade"):
            if peak_u is not None and final_u is not None and abs(peak_u) > 0:
                ratio_u = abs(final_u) / abs(peak_u)
            if peak_r and final_r is not None:
                ratio_r = abs(final_r) / abs(peak_r)
        out[h] = {
            "peak_unrounded": peak_u,
            "final_unrounded": final_u,
            "peak_rounded": peak_r,
            "final_rounded": final_r,
            "time_to_peak": ttp,
            "label_rounded": label_r,
            "label_unrounded": label_u,
            "retention_ratio_unrounded": ratio_u,
            "retention_ratio_rounded_inputs": ratio_r,
        }
    return out


def _relative_observation(
    closes: list[float], bench: list[float], n: int, noise: float,
) -> Optional[dict]:
    """Audit-only benchmark-relative path, classified with the same rule.

    Positional bar alignment (index i of the ticker window against index
    i of the benchmark window), mirroring the production composer's
    index-aligned ``benchmark_relative_return_*`` convention.  Unrounded
    arithmetic; this lens has no production counterpart label.
    """
    if not closes or not bench:
        return None
    if len(closes) < n + 1 or len(bench) < n + 1:
        return None
    a, b = closes[0], bench[0]
    if not _is_finite_number(a) or a == 0:
        return None
    if not _is_finite_number(b) or b == 0:
        return None
    rel: dict[int, float] = {}
    for i in range(1, n + 1):
        c, d = closes[i], bench[i]
        if not _is_finite_number(c) or not _is_finite_number(d):
            continue
        rel[i] = ((float(c) / float(a) - 1.0) * 100.0
                  - (float(d) / float(b) - 1.0) * 100.0)
    if n not in rel:
        return None
    best_i = None
    best = -1.0
    for i in sorted(rel):
        if abs(rel[i]) > best:
            best = abs(rel[i])
            best_i = i
    peak, final = rel[best_i], rel[n]
    return {"peak": peak, "final": final,
            "label": audit_label(peak, final, noise)}


# ---------------------------------------------------------------------------
# Read-only data access
# ---------------------------------------------------------------------------


def make_ro_cache_reader(db_path: str, memo: Optional[dict] = None) -> Callable:
    """Read-only mirror of ``price_cache.read_window_no_fetch``.

    Same input coercion, same SQL, same frame builder
    (``price_cache._df_from_rows``), but over a ``mode=ro`` URI
    connection so the production ``_ensure_table`` seam (which issues a
    ``CREATE TABLE IF NOT EXISTS`` on first use) is never exercised
    against the audited file.  Frames are memoized per window.
    """
    from price_cache import _df_from_rows  # pure frame builder, no I/O

    cache: dict = {} if memo is None else memo

    def reader(ticker, *, start, end=None, auto_adjust=False):
        if not ticker or not isinstance(ticker, str):
            return None
        if not start or not isinstance(start, str):
            return None
        try:
            start_d = _date.fromisoformat(start[:10])
        except (ValueError, TypeError):
            return None
        if end is not None:
            try:
                end_d = _date.fromisoformat(end[:10])
            except (ValueError, TypeError):
                return None
        else:
            end_d = _date(9999, 12, 31)
        if start_d > end_d:
            return _df_from_rows([])
        key = (ticker.upper(), start_d.isoformat(), end_d.isoformat(),
               1 if auto_adjust else 0)
        if key in cache:
            return cache[key]
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.Error:
            return None
        try:
            rows = conn.execute(
                """
                SELECT date, close, volume
                FROM price_cache
                WHERE ticker = ? AND auto_adjust = ?
                  AND date >= ? AND date <= ?
                ORDER BY date
                """,
                (ticker.upper(), 1 if auto_adjust else 0,
                 start_d.isoformat(), end_d.isoformat()),
            ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        frame = _df_from_rows(rows)
        cache[key] = frame
        return frame

    return reader


def _first_close_date(frame: Any) -> Optional[str]:
    """First bar date a close series would anchor on, mirroring the
    NaN-drop in ``reaction_profile_hydration._closes_from_frame``.

    Production's benchmark-relative convention aligns bars positionally
    and never checks dates; the audit's benchmark-relative lens
    additionally requires the two series to open on the same session so
    a benchmark window cached for a different date range is reported as
    misaligned instead of silently compared."""
    try:
        if frame is None or frame.empty or "Close" not in frame.columns:
            return None
        series = frame["Close"].dropna()
        if series.empty:
            return None
        return str(series.index[0].date())
    except Exception:
        return None


def _pre_anchor_bar_count(db_path: str, symbol: str, anchor: str,
                          memo: dict) -> int:
    key = (symbol.upper(), anchor)
    if key in memo:
        return memo[key]
    n = 0
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM price_cache"
                " WHERE ticker = ? AND auto_adjust = 0 AND date < ?",
                (symbol.upper(), anchor),
            ).fetchone()
            n = int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        n = 0
    memo[key] = n
    return n


def _load_rows(db_path: str) -> tuple[list[dict], frozenset]:
    """Read-only decode of every archived event + the synthetic-seed set."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
        try:
            synthetic = db.synthetic_seed_ids(conn)
        except Exception:
            synthetic = frozenset()
    finally:
        conn.close()
    decoded: list[dict] = []
    for r in rows:
        try:
            ev = db._decode_event_row(r)
        except Exception:
            ev = dict(r)
        mt = ev.get("market_tickers")
        if isinstance(mt, str):
            try:
                ev["market_tickers"] = json.loads(mt or "[]")
            except (json.JSONDecodeError, TypeError):
                ev["market_tickers"] = []
        decoded.append(ev)
    return decoded, synthetic


def _sha256_file(path: str) -> Optional[str]:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Eligibility gate (established accepted-track-record denominator)
# ---------------------------------------------------------------------------


def classify_eligibility(event: dict, *, synthetic_ids, non_thesis_stages) -> str:
    """Accepted/excluded class for one event.  Stage is checked before
    synthetic membership so a doubly-flagged row counts once, under the
    stage reason."""
    stage = event.get("stage")
    if isinstance(stage, str) and stage.strip() in non_thesis_stages:
        return "excluded_non_thesis_stage"
    if event.get("id") in synthetic_ids:
        return "excluded_synthetic_seed"
    return "accepted"


# ---------------------------------------------------------------------------
# Small numeric helpers (deterministic, JSON-safe)
# ---------------------------------------------------------------------------


def _r6(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(float(v), 6)


def _percentile(sorted_vals: list[float], q: float) -> Optional[float]:
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    if n == 1:
        return _r6(sorted_vals[0])
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return _r6(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _quantiles(values: list[float]) -> dict:
    vals = sorted(values)
    return {
        "n": len(vals),
        "min": _r6(vals[0]) if vals else None,
        "p10": _percentile(vals, 0.10),
        "p25": _percentile(vals, 0.25),
        "p50": _percentile(vals, 0.50),
        "p75": _percentile(vals, 0.75),
        "p90": _percentile(vals, 0.90),
        "max": _r6(vals[-1]) if vals else None,
    }


def _gap_around(values: list[float], current: float) -> dict:
    """The observed-empty interval containing ``current``.

    ``gap_width`` is 0.0 when an observation sits on the current value,
    and None when the current value falls outside the observed support
    on either side (no bounded empty interval exists).
    """
    uniq = sorted(set(values))
    below = [v for v in uniq if v < current - _EPS]
    at = [v for v in uniq if abs(v - current) <= _EPS]
    above = [v for v in uniq if v > current + _EPS]
    nearest_below = below[-1] if below else None
    nearest_at_or_above = at[0] if at else (above[0] if above else None)
    if at:
        width: Optional[float] = 0.0
    elif below and above:
        width = above[0] - below[-1]
    else:
        width = None
    return {
        "nearest_below": _r6(nearest_below),
        "nearest_at_or_above": _r6(nearest_at_or_above),
        "gap_width": _r6(width),
        "on_observed_value": bool(at),
    }


def widest_interior_gap(values: list[float]) -> Optional[dict]:
    """Widest gap between consecutive observed values, restricted to the
    interior (p10..p90) of the observed support.  A candidate threshold
    may only ever come from such a visible empirical plateau."""
    uniq = sorted(set(values))
    if len(uniq) < 3:
        return None
    lo_q = _percentile(uniq, _INTERIOR_LO_Q)
    hi_q = _percentile(uniq, _INTERIOR_HI_Q)
    best: Optional[dict] = None
    for a, b in zip(uniq, uniq[1:]):
        if a < lo_q - _EPS or b > hi_q + _EPS:
            continue
        width = b - a
        if best is None or width > best["width"] + _EPS:
            best = {"low": _r6(a), "high": _r6(b), "width": _r6(width),
                    "midpoint": _r6((a + b) / 2.0)}
    return best


def _share_map(counts: dict, denom: int) -> dict:
    if not denom:
        return {lab: 0.0 for lab in LABELS}
    return {lab: _r6(counts.get(lab, 0) / denom) for lab in LABELS}


def _modal(share: dict) -> Optional[str]:
    if not share or all(v == 0 for v in share.values()):
        return None
    best = max(share.values())
    for lab in LABELS:  # deterministic tie-break: LABELS order
        if share.get(lab) == best:
            return lab
    return None


# ---------------------------------------------------------------------------
# Transition curves over observed breakpoints only
# ---------------------------------------------------------------------------


def retention_transition_curve(rows: list[dict]) -> list[dict]:
    """One point per unique observed retention ratio.  ``hold`` at
    threshold t means ratio >= t (the production inclusive rule)."""
    if not rows:
        return []
    thresholds = sorted({r["ratio"] for r in rows})
    curve = []
    for t in thresholds:
        hold = sum(1 for r in rows if r["ratio"] >= t)
        changed = [r for r in rows
                   if (r["ratio"] >= t) != (r["label"] == "hold")]
        curve.append({
            "threshold": t,
            "hold": hold,
            "fade": len(rows) - hold,
            "changed_vs_current": len(changed),
            "events_changed": len({r["event_id"] for r in changed}),
        })
    return curve


def floor_transition_curve(rows: list[dict]) -> list[dict]:
    """One point per unique observed absolute peak.  ``flat`` at floor f
    means |peak| < f (the production strict rule)."""
    if not rows:
        return []
    floors = sorted({r["abs_peak"] for r in rows})
    curve = []
    for f in floors:
        flat = sum(1 for r in rows if r["abs_peak"] < f)
        changed = [r for r in rows
                   if (r["abs_peak"] < f) != (r["label"] == "flat")]
        curve.append({
            "floor": f,
            "flat": flat,
            "non_flat": len(rows) - flat,
            "changed_vs_current": len(changed),
            "events_changed": len({r["event_id"] for r in changed}),
        })
    return curve


# ---------------------------------------------------------------------------
# Data-derived candidate rules
# ---------------------------------------------------------------------------


def derive_candidates(retention_ratios: list[float],
                      floor_values_by_horizon: dict) -> list[dict]:
    """Admissible alternative rules, derived ONLY from observed
    breakpoints.

    A candidate enters iff (a) the current value sits in a dense
    boundary region (at least ``_DENSE_MIN_OBS`` observations within the
    band) AND (b) a visible interior plateau exists that is at least
    ``_GAP_DOMINANCE`` times wider than the empty interval around the
    current value and at least the minimum plateau width.  The proposed
    value is the plateau midpoint - never an intuition number.
    """
    out: list[dict] = []
    vals = [float(v) for v in retention_ratios]
    if vals:
        dense = sum(1 for v in vals
                    if abs(v - AUDIT_RETENTION_THRESHOLD) <= _RATIO_BAND + _EPS)
        gap = widest_interior_gap(vals)
        around = _gap_around(vals, AUDIT_RETENTION_THRESHOLD)
        cur_width = around["gap_width"]
        if (dense >= _DENSE_MIN_OBS and gap is not None
                and cur_width is not None
                and gap["width"] >= _MIN_PLATEAU_WIDTH_RATIO - _EPS
                and gap["width"] >= _GAP_DOMINANCE * cur_width - _EPS):
            out.append({
                "kind": "retention_threshold",
                "current": AUDIT_RETENTION_THRESHOLD,
                "proposed": gap["midpoint"],
                "gap_low": gap["low"],
                "gap_high": gap["high"],
                "gap_width": gap["width"],
                "dense_obs_at_current": dense,
                "why": ("0.70 sits in a dense observed region while a "
                        "wider empty plateau exists in the interior of "
                        "the observed retention-ratio support"),
            })
    for h in PEAK_HORIZONS:
        vals = [float(v) for v in (floor_values_by_horizon.get(h) or [])]
        if not vals:
            continue
        floor = AUDIT_NOISE_FLOORS[h]
        dense = sum(1 for v in vals if abs(v - floor) <= _FLOOR_BAND_PP + _EPS)
        gap = widest_interior_gap(vals)
        around = _gap_around(vals, floor)
        cur_width = around["gap_width"]
        if (dense >= _DENSE_MIN_OBS and gap is not None
                and cur_width is not None
                and gap["width"] >= _MIN_PLATEAU_WIDTH_FLOOR_PP - _EPS
                and gap["width"] >= _GAP_DOMINANCE * cur_width - _EPS):
            out.append({
                "kind": f"noise_floor_{h}",
                "current": floor,
                "proposed": gap["midpoint"],
                "gap_low": gap["low"],
                "gap_high": gap["high"],
                "gap_width": gap["width"],
                "dense_obs_at_current": dense,
                "why": (f"the {h} floor sits in a dense observed |peak| "
                        "region while a wider empty plateau exists in "
                        "the interior of the observed support"),
            })
    return out


# ---------------------------------------------------------------------------
# Recommendation (objective guards; every input is printed in the report)
# ---------------------------------------------------------------------------


def recommend(metrics: dict) -> dict:
    """Deterministic verdict from the documented audit conventions."""
    reasons: list[str] = []
    if int(metrics.get("equivalence_mismatches", 0)) > 0:
        return {
            "verdict": "BLOCKED_RULE_REPRODUCTION_MISMATCH",
            "blocker": True,
            "reasons": ["audit-side classifier disagreed with production "
                        "labels; calibration must not proceed"],
        }
    not_ready = False
    if int(metrics.get("accepted_n", 0)) <= 0:
        not_ready = True
        reasons.append("empty accepted archive")
    if int(metrics.get("events_scorable_20d", 0)) < _MIN_SCORABLE_EVENTS_20D:
        not_ready = True
        reasons.append(
            f"events scorable at 20d below the audit floor of "
            f"{_MIN_SCORABLE_EVENTS_20D}")
    if int(metrics.get("eligible_holdfade_total", 0)) < _MIN_ELIGIBLE_HOLDFADE:
        not_ready = True
        reasons.append(
            f"hold/fade-eligible observations below the audit floor of "
            f"{_MIN_ELIGIBLE_HOLDFADE}")
    if float(metrics.get("boundary_share_pm005", 0.0)) >= _DENSE_BOUNDARY_SHARE:
        not_ready = True
        reasons.append(
            "retention ratios are too concentrated at the 0.70 boundary "
            f"(share within +/-0.05 at or above {_DENSE_BOUNDARY_SHARE})")
    if float(metrics.get("rounding_flip_share", 0.0)) >= _ROUNDING_FLIP_SHARE_MAX:
        not_ready = True
        reasons.append(
            "labels are materially rounding-driven (flip share at or "
            f"above {_ROUNDING_FLIP_SHARE_MAX})")
    if bool(metrics.get("loeo_modal_flip")) or bool(metrics.get("loco_modal_flip")):
        not_ready = True
        reasons.append(
            "a single left-out event or market-story cluster changes the "
            "modal 20d label - the interpretation is not stable")
    n_cand = int(metrics.get("admissible_candidates", 0))
    if not_ready:
        return {"verdict": "NOT_CALIBRATION_READY", "blocker": False,
                "reasons": reasons}
    if n_cand == 1:
        return {"verdict": "ADJUST_ONE_RULE", "blocker": False,
                "reasons": ["exactly one data-derived candidate has a "
                            "visible empirical plateau basis"]}
    if n_cand > 1:
        return {"verdict": "NOT_CALIBRATION_READY", "blocker": False,
                "reasons": ["more than one rule shows boundary instability; "
                            "no single bounded adjustment is defensible"]}
    return {"verdict": "KEEP_CURRENT_RULE", "blocker": False,
            "reasons": ["coverage adequate for the descriptive consumer; "
                        "current values sit in stable observed regions; "
                        "no data-derived alternative is admissible"]}


# ---------------------------------------------------------------------------
# Observation assembly (the only place the archive is walked)
# ---------------------------------------------------------------------------


def _resolve_benchmark_symbol(symbol: str) -> Optional[str]:
    try:
        from market_check import resolve_benchmark
        etf, _sector = resolve_benchmark(symbol)
    except Exception:
        return None
    return etf if isinstance(etf, str) and etf else None


def _assemble(accepted: list[dict], db_path: str) -> dict:
    reader = make_ro_cache_reader(db_path)
    pre_anchor_memo: dict = {}
    observations: list[dict] = []
    per_event: dict[int, dict] = {}
    equivalence = {"checked": 0, "mismatches": 0, "mismatch_examples": []}
    tf = {
        "stored_entries": 0,
        "non_dict_entries": 0,
        "missing_symbol_entries": 0,
        "valid_ticker_dicts": 0,
        "hydration_status_counts": Counter(),
        "basis_counts": Counter(),
    }

    for ev in accepted:
        eid = ev.get("id")
        event_date = ev.get("event_date")
        tickers = ev.get("market_tickers")
        tickers = list(tickers) if isinstance(tickers, list) else []
        primary_symbol = _primary_ticker(tickers)
        info = per_event.setdefault(eid, {
            "event_id": eid,
            "event_date": event_date,
            "stored": 0, "valid": 0, "statuses": [],
            "primary_symbol": primary_symbol,
        })
        for t in tickers:
            info["stored"] += 1
            tf["stored_entries"] += 1
            if not isinstance(t, dict):
                tf["non_dict_entries"] += 1
                continue
            raw_symbol = t.get("symbol")
            if not isinstance(raw_symbol, str) or not raw_symbol:
                tf["missing_symbol_entries"] += 1
                continue
            symbol = raw_symbol
            info["valid"] += 1
            tf["valid_ticker_dicts"] += 1

            profile = hydrate_per_ticker_profile(
                t, event_date=event_date, cache_reader=reader)
            basis = profile.get("reaction_profile_basis")
            status = profile.get("hydration_status")
            tf["basis_counts"][basis] += 1
            tf["hydration_status_counts"][status] += 1
            info["statuses"].append(status)

            anchor = _coerce_anchor(event_date, t.get("anchor_date"))
            quarantined = bool(_quarantined_horizons(t))

            closes: list[float] = []
            bench_closes: list[float] = []
            adj_closes: list[float] = []
            bench_aligned = False
            if basis == "forward_anchored" and symbol and anchor:
                frame = reader(symbol, start=anchor, auto_adjust=False)
                closes = _closes_from_frame(frame)
                bench_symbol = _resolve_benchmark_symbol(symbol) if closes else None
                if bench_symbol:
                    bench_frame = reader(bench_symbol, start=anchor,
                                         auto_adjust=False)
                    bench_closes = _closes_from_frame(bench_frame)
                    first = _first_close_date(frame)
                    bench_aligned = (
                        first is not None
                        and first == _first_close_date(bench_frame))
                adj_closes = _closes_from_frame(
                    reader(symbol, start=anchor, auto_adjust=True))

            audit = classify_observation(closes) if closes else None
            adj_audit = classify_observation(adj_closes) if adj_closes else None

            obs = {
                "event_id": eid,
                "symbol": symbol,
                "anchor": anchor,
                "basis": basis,
                "hydration_status": status,
                "quarantined": quarantined,
                "is_primary": (
                    isinstance(primary_symbol, str)
                    and symbol.strip().upper() == primary_symbol
                ),
                "labels": {}, "labels_unrounded": {},
                "peak_unrounded": {}, "final_unrounded": {},
                "peak_rounded": {}, "final_rounded": {},
                "ratio_unrounded": {}, "ratio_rounded_inputs": {},
                "bench_available": {}, "bench_misaligned": {},
                "relative": {},
                "adjusted_labels": {},
                "pre_anchor_bars": (
                    _pre_anchor_bar_count(db_path, symbol, anchor,
                                          pre_anchor_memo)
                    if (basis == "forward_anchored" and anchor) else None
                ),
            }

            for h in PEAK_HORIZONS:
                n = _HORIZON_BARS[h]
                noise = AUDIT_NOISE_FLOORS[h]
                prod_label = profile.get(f"fade_or_hold_label_{h}")
                obs["labels"][h] = prod_label
                if basis == "forward_anchored" and audit is not None:
                    a = audit[h]
                    equivalence["checked"] += 1
                    mismatch = (
                        a["label_rounded"] != prod_label
                        or a["peak_rounded"] != profile.get(f"peak_move_{h}")
                        or a["final_rounded"] != profile.get(f"return_{h}")
                        or a["time_to_peak"] != profile.get(f"time_to_peak_{h}")
                    )
                    if mismatch:
                        equivalence["mismatches"] += 1
                        if len(equivalence["mismatch_examples"]) < 5:
                            equivalence["mismatch_examples"].append({
                                "event_id": eid, "symbol": symbol,
                                "horizon": h,
                                "audit_label": a["label_rounded"],
                                "production_label": prod_label,
                            })
                    obs["labels_unrounded"][h] = a["label_unrounded"]
                    obs["peak_unrounded"][h] = _r6(a["peak_unrounded"])
                    obs["final_unrounded"][h] = _r6(a["final_unrounded"])
                    obs["peak_rounded"][h] = a["peak_rounded"]
                    obs["final_rounded"][h] = a["final_rounded"]
                    obs["ratio_unrounded"][h] = _r6(
                        a["retention_ratio_unrounded"])
                    obs["ratio_rounded_inputs"][h] = _r6(
                        a["retention_ratio_rounded_inputs"])
                else:
                    obs["labels_unrounded"][h] = "insufficient"
                    obs["peak_unrounded"][h] = None
                    obs["final_unrounded"][h] = None
                    obs["peak_rounded"][h] = None
                    obs["final_rounded"][h] = None
                    obs["ratio_unrounded"][h] = None
                    obs["ratio_rounded_inputs"][h] = None

                bench_len_ok = (
                    basis == "forward_anchored"
                    and len(closes) >= n + 1 and len(bench_closes) >= n + 1
                )
                obs["bench_available"][h] = bench_len_ok and bench_aligned
                obs["bench_misaligned"][h] = bench_len_ok and not bench_aligned
                rel = None
                if bench_len_ok and bench_aligned and not quarantined:
                    rel = _relative_observation(closes, bench_closes, n, noise)
                obs["relative"][h] = (
                    {"label": rel["label"], "peak": _r6(rel["peak"]),
                     "final": _r6(rel["final"])} if rel else None
                )
                obs["adjusted_labels"][h] = (
                    adj_audit[h]["label_rounded"] if adj_audit else None
                )

            observations.append(obs)

    tf["hydration_status_counts"] = dict(sorted(
        tf["hydration_status_counts"].items()))
    tf["basis_counts"] = dict(sorted(tf["basis_counts"].items()))
    return {
        "observations": observations,
        "per_event": per_event,
        "ticker_funnel": tf,
        "equivalence": equivalence,
    }


def _scorable(obs: dict, h: str) -> bool:
    return obs["basis"] == "forward_anchored" and obs["labels"][h] in LABELS


# ---------------------------------------------------------------------------
# Lens computations
# ---------------------------------------------------------------------------


def _event_vectors(observations: list[dict], h: str) -> dict:
    """Per-event within-event label share vectors at one horizon."""
    by_event: dict[int, list[str]] = {}
    for o in observations:
        if _scorable(o, h):
            by_event.setdefault(o["event_id"], []).append(o["labels"][h])
    vecs: dict[int, dict] = {}
    for eid in sorted(by_event):
        labels = by_event[eid]
        share = {lab: _r6(labels.count(lab) / len(labels)) for lab in LABELS}
        vecs[eid] = {"share": share, "n": len(labels),
                     "agree": len(set(labels)) == 1}
    return vecs


def _mean_share(share_maps: list[dict]) -> dict:
    if not share_maps:
        return {lab: 0.0 for lab in LABELS}
    return {
        lab: _r6(sum(s[lab] for s in share_maps) / len(share_maps))
        for lab in LABELS
    }


def _label_distributions(observations: list[dict], per_event: dict,
                         cluster_of: dict) -> dict:
    out: dict[str, dict] = {}
    for h in PEAK_HORIZONS:
        scorable = [o for o in observations if _scorable(o, h)]
        counts = Counter(o["labels"][h] for o in scorable)
        insufficient_forward = sum(
            1 for o in observations
            if o["basis"] == "forward_anchored"
            and o["labels"][h] == "insufficient")
        non_forward = sum(
            1 for o in observations if o["basis"] != "forward_anchored")
        vecs = _event_vectors(observations, h)
        ew_share = _mean_share([v["share"] for v in vecs.values()])
        primary_counts = Counter()
        primary_unscorable = 0
        for eid in sorted(per_event):
            info = per_event[eid]
            if not info["primary_symbol"]:
                continue
            primary_obs = [
                o for o in observations
                if o["event_id"] == eid and o["is_primary"]
            ]
            if primary_obs and _scorable(primary_obs[0], h):
                primary_counts[primary_obs[0]["labels"][h]] += 1
            else:
                primary_unscorable += 1
        cluster_shares: dict[str, list[dict]] = {}
        for eid, vec in vecs.items():
            cid = cluster_of.get(eid)
            if cid is not None:
                cluster_shares.setdefault(cid, []).append(vec["share"])
        cw_share = _mean_share([
            _mean_share(shares)
            for cid, shares in sorted(cluster_shares.items())
        ])
        out[h] = {
            "ticker_weighted": {
                "denominator_scorable": len(scorable),
                "counts": {lab: counts.get(lab, 0) for lab in LABELS},
                "share": _share_map(counts, len(scorable)),
                "insufficient_forward": insufficient_forward,
                "non_forward_basis": non_forward,
            },
            "event_weighted": {
                "events": len(vecs),
                "share": ew_share,
                "all_agree": sum(1 for v in vecs.values() if v["agree"]),
                "mixed": sum(1 for v in vecs.values() if not v["agree"]),
            },
            "primary_only": {
                "events_with_primary_scorable": sum(primary_counts.values()),
                "counts": {lab: primary_counts.get(lab, 0) for lab in LABELS},
                "primary_unscorable": primary_unscorable,
            },
            "cluster_weighted": {
                "clusters": len(cluster_shares),
                "share": cw_share,
            },
        }
    return out


def _eligible_rows(observations: list[dict]) -> list[dict]:
    rows = []
    for o in observations:
        for h in PEAK_HORIZONS:
            if not _scorable(o, h):
                continue
            if o["labels"][h] not in ("hold", "fade"):
                continue
            ratio = o["ratio_unrounded"].get(h)
            if ratio is None:
                continue
            rows.append({
                "event_id": o["event_id"],
                "symbol": o["symbol"],
                "horizon": h,
                "ratio": _r6(ratio),
                "ratio_rounded_inputs": o["ratio_rounded_inputs"].get(h),
                "label": o["labels"][h],
                "label_unrounded": o["labels_unrounded"][h],
            })
    return rows


def _retention_section(observations: list[dict], cluster_of: dict) -> dict:
    rows = _eligible_rows(observations)
    for r in rows:
        r["cluster_id"] = cluster_of.get(r["event_id"])
    ratios = [r["ratio"] for r in rows]
    uniq = sorted(set(ratios))
    value_counts = Counter(ratios)
    top_values = [
        {"ratio": v, "observations": c}
        for v, c in sorted(value_counts.items(),
                           key=lambda kv: (-kv[1], kv[0]))[:5]
    ]
    thr = AUDIT_RETENTION_THRESHOLD
    boundary_rows = [r for r in rows if abs(r["ratio"] - thr) <= _RATIO_BAND + _EPS]
    exactly = sum(
        1 for r in rows
        if r["ratio_rounded_inputs"] is not None
        and abs(r["ratio_rounded_inputs"] - thr) <= _EPS)
    rounding_dependent = sum(
        1 for r in rows
        if r["label"] != r["label_unrounded"]
        and {r["label"], r["label_unrounded"]} <= {"hold", "fade"})
    by_h = Counter(r["horizon"] for r in rows)
    final_zero = sum(1 for r in rows if r["ratio"] == 0.0)
    return {
        "eligible_total": len(rows),
        "eligible_by_horizon": {h: by_h.get(h, 0) for h in PEAK_HORIZONS},
        "final_zero_count": final_zero,
        "quantiles": _quantiles(ratios),
        "n_unique": len(uniq),
        "top_values": top_values,
        "boundary": {
            **_gap_around(ratios, thr),
            "within_002": sum(1 for r in rows
                              if abs(r["ratio"] - thr) <= 0.02 + _EPS),
            "within_005": len(boundary_rows),
            "within_010": sum(1 for r in rows
                              if abs(r["ratio"] - thr) <= 0.10 + _EPS),
            "exactly_070_rounded": exactly,
            "boundary_observations": sorted(
                boundary_rows,
                key=lambda r: (r["event_id"], r["symbol"], r["horizon"])),
            "boundary_cluster_counts": dict(sorted(Counter(
                r["cluster_id"] for r in boundary_rows
                if r["cluster_id"]).items())),
        },
        "curve": retention_transition_curve(rows),
        "widest_interior_gap": widest_interior_gap(ratios),
        "rounding_dependent_count": rounding_dependent,
        "ratios": sorted(rows, key=lambda r: (r["event_id"], r["symbol"],
                                              r["horizon"])),
    }


def _noise_floor_section(observations: list[dict], per_event: dict) -> dict:
    out: dict[str, Any] = {}
    for h in PEAK_HORIZONS:
        floor = AUDIT_NOISE_FLOORS[h]
        rows = []
        for o in observations:
            if not _scorable(o, h):
                continue
            peak_u = o["peak_unrounded"].get(h)
            peak_r = o["peak_rounded"].get(h)
            if peak_u is None or peak_r is None:
                continue
            rows.append({
                "event_id": o["event_id"],
                "symbol": o["symbol"],
                "abs_peak": _r6(abs(peak_u)),
                "abs_peak_rounded": _r6(abs(peak_r)),
                "label": o["labels"][h],
            })
        values = [r["abs_peak"] for r in rows]
        flips = sum(
            1 for r in rows
            if (r["abs_peak"] < floor) != (r["abs_peak_rounded"] < floor))
        ev_flat_shares = []
        by_event: dict[int, list[str]] = {}
        for o in observations:
            if _scorable(o, h):
                by_event.setdefault(o["event_id"], []).append(o["labels"][h])
        for eid in sorted(by_event):
            labels = by_event[eid]
            ev_flat_shares.append(labels.count("flat") / len(labels))
        out[h] = {
            "current_floor": floor,
            "n": len(rows),
            "quantiles": _quantiles(values),
            "below_floor": sum(1 for r in rows if r["label"] == "flat"),
            "exactly_at_floor_rounded": sum(
                1 for r in rows
                if abs(r["abs_peak_rounded"] - floor) <= _EPS),
            "within_025pp": sum(
                1 for r in rows
                if abs(r["abs_peak"] - floor) <= _FLOOR_BAND_PP + _EPS),
            "rounding_flips": flips,
            "boundary": _gap_around(values, floor) if values else None,
            "curve": floor_transition_curve(rows),
            "widest_interior_gap": widest_interior_gap(values),
            "event_weighted_flat_share": (
                _r6(sum(ev_flat_shares) / len(ev_flat_shares))
                if ev_flat_shares else None),
        }
    return out


def _scale_bias_section(observations: list[dict]) -> dict:
    """Descriptive probe: do raw percent floors flatten quiet tickers and
    never flatten volatile ones?  Split tickers by their median |peak_20d|
    and compare flat shares.  Descriptive only; tiny denominators."""
    per_ticker: dict[str, dict] = {}
    for o in observations:
        if not _scorable(o, "20d"):
            continue
        peak_u = o["peak_unrounded"].get("20d")
        if peak_u is None:
            continue
        d = per_ticker.setdefault(o["symbol"].upper(),
                                  {"peaks": [], "flat": 0, "n": 0})
        d["peaks"].append(abs(peak_u))
        d["n"] += 1
        if o["labels"]["20d"] == "flat":
            d["flat"] += 1
    if len(per_ticker) < 2:
        return {"available": False, "tickers": len(per_ticker),
                "note": "fewer than 2 tickers scorable at 20d; the "
                        "scale-bias probe has no contrast to show"}
    meds = sorted(
        (sorted(d["peaks"])[len(d["peaks"]) // 2], sym)
        for sym, d in per_ticker.items()
    )
    half = len(meds) // 2
    low, high = meds[:half], meds[half:]

    def _agg(pairs):
        n = sum(per_ticker[sym]["n"] for _, sym in pairs)
        flat = sum(per_ticker[sym]["flat"] for _, sym in pairs)
        return {
            "tickers": len(pairs),
            "observations": n,
            "flat_share": _r6(flat / n) if n else None,
            "median_abs_peak_min": _r6(pairs[0][0]) if pairs else None,
            "median_abs_peak_max": _r6(pairs[-1][0]) if pairs else None,
        }

    return {"available": True, "tickers": len(per_ticker),
            "low_half": _agg(low), "high_half": _agg(high),
            "note": "descriptive probe only; a raw percent floor tends to "
                    "label quiet series flat and volatile series never-flat "
                    "regardless of information content"}


def _rounding_section(observations: list[dict], cluster_of: dict) -> dict:
    flips = []
    checked = 0
    by_h = Counter()
    transitions = Counter()
    for o in observations:
        if o["basis"] != "forward_anchored":
            continue
        for h in PEAK_HORIZONS:
            lr = o["labels"][h]
            lu = o["labels_unrounded"][h]
            if lr not in LABELS and lu not in LABELS:
                continue
            checked += 1
            if lr != lu:
                by_h[h] += 1
                transitions[f"{lu}->{lr}"] += 1
                flips.append({
                    "event_id": o["event_id"], "symbol": o["symbol"],
                    "horizon": h, "unrounded_label": lu, "rounded_label": lr,
                    "cluster_id": cluster_of.get(o["event_id"]),
                })
    at_flat = sum(1 for f in flips
                  if "flat" in (f["unrounded_label"], f["rounded_label"]))
    at_hold = sum(
        1 for f in flips
        if {f["unrounded_label"], f["rounded_label"]} == {"hold", "fade"})

    def _shares_20d(label_key):
        scorable = [o for o in observations if _scorable(o, "20d")]
        counts = Counter(o[label_key]["20d"] for o in scorable
                         if o[label_key]["20d"] in LABELS)
        return _share_map(counts, sum(counts.values()))

    rounded_share = _shares_20d("labels")
    unrounded_share = _shares_20d("labels_unrounded")
    max_delta = max(
        (abs(rounded_share[lab] - unrounded_share[lab]) for lab in LABELS),
        default=0.0)
    return {
        "scorable_checked": checked,
        "total_flips": len(flips),
        "flip_share": _r6(len(flips) / checked) if checked else 0.0,
        "by_horizon": {h: by_h.get(h, 0) for h in PEAK_HORIZONS},
        "transitions": dict(sorted(transitions.items())),
        "at_flat_floor": at_flat,
        "at_hold_threshold": at_hold,
        "affected_observations": sorted(
            flips, key=lambda f: (f["event_id"], f["symbol"], f["horizon"])),
        "ticker_share_20d_max_delta": _r6(max_delta),
    }


def _benchmark_section(observations: list[dict]) -> dict:
    matched = Counter()
    unavailable = Counter()
    misaligned = Counter()
    change = Counter()
    sign_flip = Counter()
    hold_fade = Counter()
    matrices: dict[str, Counter] = {h: Counter() for h in PEAK_HORIZONS}
    quarantined = sum(1 for o in observations if o["quarantined"])
    for o in observations:
        for h in PEAK_HORIZONS:
            if not _scorable(o, h):
                continue
            if o["bench_misaligned"].get(h):
                misaligned[h] += 1
            rel = o["relative"].get(h)
            if rel is None:
                if not o["quarantined"]:
                    unavailable[h] += 1
                continue
            matched[h] += 1
            raw_label = o["labels"][h]
            rel_label = rel["label"]
            matrices[h][f"{raw_label}->{rel_label}"] += 1
            if raw_label != rel_label:
                change[h] += 1
                if "reverse" in (raw_label, rel_label):
                    sign_flip[h] += 1
                if {raw_label, rel_label} == {"hold", "fade"}:
                    hold_fade[h] += 1
    return {
        "matched_by_horizon": {h: matched.get(h, 0) for h in PEAK_HORIZONS},
        "unavailable_by_horizon": {h: unavailable.get(h, 0)
                                   for h in PEAK_HORIZONS},
        "misaligned_by_horizon": {h: misaligned.get(h, 0)
                                  for h in PEAK_HORIZONS},
        "alignment_note": (
            "the audit lens requires the ticker and benchmark windows to "
            "open on the same session; production's positional "
            "benchmark_relative_return_* convention does not check dates, "
            "so misaligned pairs are reported here instead of compared"),
        "label_change_count": {h: change.get(h, 0) for h in PEAK_HORIZONS},
        "sign_flip_count": {h: sign_flip.get(h, 0) for h in PEAK_HORIZONS},
        "hold_fade_change_count": {h: hold_fade.get(h, 0)
                                   for h in PEAK_HORIZONS},
        "transition_matrix": {h: dict(sorted(matrices[h].items()))
                              for h in PEAK_HORIZONS},
        "quarantined_observations": quarantined,
    }


def _adjusted_section(observations: list[dict]) -> dict:
    matched = Counter()
    change = Counter()
    matrices: dict[str, Counter] = {h: Counter() for h in PEAK_HORIZONS}
    adj_scorable = Counter()
    for o in observations:
        for h in PEAK_HORIZONS:
            adj = o["adjusted_labels"].get(h)
            if adj in LABELS:
                adj_scorable[h] += 1
            if not _scorable(o, h) or adj not in LABELS:
                continue
            matched[h] += 1
            raw_label = o["labels"][h]
            matrices[h][f"{raw_label}->{adj}"] += 1
            if raw_label != adj:
                change[h] += 1
    total_matched = sum(matched.values())
    return {
        "available": total_matched > 0,
        "raw_scorable_by_horizon": {
            h: sum(1 for o in observations if _scorable(o, h))
            for h in PEAK_HORIZONS},
        "adjusted_scorable_by_horizon": {h: adj_scorable.get(h, 0)
                                         for h in PEAK_HORIZONS},
        "matched_by_horizon": {h: matched.get(h, 0) for h in PEAK_HORIZONS},
        "label_change_count": {h: change.get(h, 0) for h in PEAK_HORIZONS},
        "transition_matrix": {h: dict(sorted(matrices[h].items()))
                              for h in PEAK_HORIZONS},
        "note": ("audit-only sensitivity over cached adjusted rows; the "
                 "production hydrator reads raw (auto_adjust=0) closes "
                 "only" if total_matched
                 else "basis sensitivity unavailable: no observation has "
                      "both raw and adjusted cached paths at any horizon"),
    }


def _horizon_section(observations: list[dict], clusters: list[dict],
                     cluster_of: dict) -> dict:
    def _matrix(h1, h2):
        m = Counter()
        agree = 0
        matched = 0
        for o in observations:
            if _scorable(o, h1) and _scorable(o, h2):
                matched += 1
                a, b = o["labels"][h1], o["labels"][h2]
                m[f"{a}->{b}"] += 1
                if a == b:
                    agree += 1
        return {"matched": matched, "agree": agree,
                "matrix": dict(sorted(m.items()))}

    valid = [o for o in observations]
    displayed_insufficient_with_signal = 0
    hides_disagreement = 0
    sixtyd_only = 0
    from_20d = 0
    for o in valid:
        l5, l20, l60 = (o["labels"]["5d"], o["labels"]["20d"],
                        o["labels"]["60d"])
        displayed = l20 if l20 is not None else (
            l5 if l5 is not None else l60)
        if displayed == l20 and l20 is not None:
            from_20d += 1
        if displayed == "insufficient" and (l5 in LABELS or l60 in LABELS):
            displayed_insufficient_with_signal += 1
        if displayed in LABELS:
            others = [x for x in (l5, l60) if x in LABELS and x != displayed]
            if others:
                hides_disagreement += 1
        if l60 in LABELS and l20 == "insufficient" and l5 == "insufficient":
            sixtyd_only += 1

    labeled_20d = [o for o in valid if o["labels"]["20d"] in LABELS]
    histogram = Counter(o["labels"]["20d"] for o in labeled_20d)
    largest_share = None
    if clusters and labeled_20d:
        largest_ids = set(clusters[0]["event_ids"])
        largest_share = _r6(
            sum(1 for o in labeled_20d if o["event_id"] in largest_ids)
            / len(labeled_20d))
    return {
        "t5_vs_t20": _matrix("5d", "20d"),
        "t20_vs_t60": _matrix("20d", "60d"),
        "frontend_priority": {
            "tickers_with_block": len(valid),
            "displayed_from_20d": from_20d,
            "displayed_insufficient_with_other_signal":
                displayed_insufficient_with_signal,
            "displayed_hides_disagreement": hides_disagreement,
            "sixtyd_only_information": sixtyd_only,
        },
        "track_record": {
            "histogram_20d": {lab: histogram.get(lab, 0) for lab in LABELS},
            "insufficient_excluded": sum(
                1 for o in valid if o["labels"]["20d"] == "insufficient"),
            "largest_cluster_share": largest_share,
        },
    }


# ---------------------------------------------------------------------------
# Leave-out analyses (event-weighted 20d shares are the interpretive core)
# ---------------------------------------------------------------------------


def _shares_excluding(vecs: dict, excluded: set) -> dict:
    remaining = [v["share"] for eid, v in sorted(vecs.items())
                 if eid not in excluded]
    return _mean_share(remaining)


def _range_tracker(runs: list[dict]) -> dict:
    if not runs:
        return {}
    return {
        lab: {"min": _r6(min(r[lab] for r in runs)),
              "max": _r6(max(r[lab] for r in runs))}
        for lab in LABELS
    }


def _leave_out_section(observations: list[dict], per_event: dict,
                       clusters: list[dict], cluster_of: dict) -> dict:
    vecs = _event_vectors(observations, "20d")
    base_share = _shares_excluding(vecs, set())
    base_modal = _modal(base_share)

    loeo_runs = []
    loeo_flip = False
    for eid in sorted(vecs):
        share = _shares_excluding(vecs, {eid})
        loeo_runs.append(share)
        if _modal(share) != base_modal:
            loeo_flip = True

    years = sorted({
        str(per_event[eid]["event_date"])[:4]
        for eid in vecs if per_event.get(eid, {}).get("event_date")
    })
    loyo_runs = []
    loyo_flip = False
    if len(years) >= 2:
        for year in years:
            excluded = {
                eid for eid in vecs
                if str(per_event.get(eid, {}).get("event_date"))[:4] == year}
            share = _shares_excluding(vecs, excluded)
            loyo_runs.append(share)
            if _modal(share) != base_modal:
                loyo_flip = True

    cluster_ids = sorted({
        cluster_of[eid] for eid in vecs if eid in cluster_of})
    members_of = {c["cluster_id"]: set(c["event_ids"]) for c in clusters}
    loco_runs = []
    loco_flip = False
    for cid in cluster_ids:
        share = _shares_excluding(vecs, members_of.get(cid, set()))
        loco_runs.append(share)
        if _modal(share) != base_modal:
            loco_flip = True

    without_largest = None
    if clusters:
        without_largest = _shares_excluding(
            vecs, set(clusters[0]["event_ids"]))

    def _obs_share_20d(filtered):
        counts = Counter(o["labels"]["20d"] for o in filtered
                         if _scorable(o, "20d"))
        return _share_map(counts, sum(counts.values()))

    no_sdf_obs = [o for o in observations
                  if o["basis"] != "same_day_fallback"]
    no_sdf_vecs = _event_vectors(no_sdf_obs, "20d")
    no_quarantine = [o for o in observations if not o["quarantined"]]
    no_q_vecs = _event_vectors(no_quarantine, "20d")

    multi_ticker_eids = {
        eid for eid, info in per_event.items() if info["valid"] >= 2}
    multi_vecs = {eid: v for eid, v in vecs.items()
                  if eid in multi_ticker_eids}

    all_share = _obs_share_20d(observations)
    primary_counts = Counter(
        o["labels"]["20d"] for o in observations
        if o["is_primary"] and _scorable(o, "20d"))
    primary_share = _share_map(primary_counts, sum(primary_counts.values()))
    max_delta = max(
        (abs(all_share[lab] - primary_share[lab]) for lab in LABELS),
        default=0.0)

    return {
        "base": {"share": base_share, "modal": base_modal,
                 "events": len(vecs)},
        "loeo": {"runs": len(loeo_runs),
                 "share_ranges_20d": _range_tracker(loeo_runs),
                 "modal_flip": loeo_flip},
        "loyo": {"years": years,
                 "share_ranges_20d": _range_tracker(loyo_runs),
                 "modal_flip": loyo_flip,
                 "note": ("single event-date year in the scorable set; "
                          "leave-one-year-out has no second year to keep"
                          if len(years) < 2 else None)},
        "loco": {"runs": len(loco_runs),
                 "share_ranges_20d": _range_tracker(loco_runs),
                 "modal_flip": loco_flip,
                 "without_largest": without_largest},
        "no_sdf": {"observations": len(no_sdf_obs),
                   "events": len(no_sdf_vecs),
                   "share_20d": _shares_excluding(no_sdf_vecs, set())},
        "no_quarantine": {"events": len(no_q_vecs),
                          "share_20d": _shares_excluding(no_q_vecs, set())},
        "no_single_ticker": {
            "events": len(multi_vecs),
            "share_20d": _shares_excluding(multi_vecs, set()),
        },
        "primary_vs_all": {
            "primary_share_20d": primary_share,
            "all_ticker_share_20d": all_share,
            "max_abs_delta": _r6(max_delta),
        },
    }


# ---------------------------------------------------------------------------
# Candidate evaluation (bounded: at most current + two data-derived)
# ---------------------------------------------------------------------------


def _evaluate_candidates(cands: list[dict], observations: list[dict],
                         retention_rows: list[dict],
                         cluster_of: dict) -> list[dict]:
    out = []
    for cand in cands:
        entry = dict(cand)
        changed = []
        if cand["kind"] == "retention_threshold":
            t = cand["proposed"]
            for r in retention_rows:
                new_label = "hold" if r["ratio"] >= t else "fade"
                if new_label != r["label"]:
                    changed.append({
                        "event_id": r["event_id"], "symbol": r["symbol"],
                        "horizon": r["horizon"], "from": r["label"],
                        "to": new_label,
                        "cluster_id": cluster_of.get(r["event_id"]),
                    })
            entry["denominator"] = len(retention_rows)
        else:
            h = cand["kind"].rsplit("_", 1)[-1]
            f = cand["proposed"]
            rows = [o for o in observations if _scorable(o, h)]
            for o in rows:
                peak_u = o["peak_unrounded"].get(h)
                if peak_u is None:
                    continue
                now_flat = o["labels"][h] == "flat"
                new_flat = abs(peak_u) < f
                if now_flat != new_flat:
                    changed.append({
                        "event_id": o["event_id"], "symbol": o["symbol"],
                        "horizon": h,
                        "from": o["labels"][h],
                        "to": "flat" if new_flat else "non_flat",
                        "cluster_id": cluster_of.get(o["event_id"]),
                    })
            entry["denominator"] = len(rows)
        entry["changed_count"] = len(changed)
        entry["events_changed"] = len({c["event_id"] for c in changed})
        entry["changed_observations"] = sorted(
            changed, key=lambda c: (c["event_id"], c["symbol"], c["horizon"]))
        entry["cluster_concentration"] = dict(sorted(Counter(
            c["cluster_id"] for c in changed if c["cluster_id"]).items()))
        entry["complexity"] = ("same rule shape, one constant changes; no "
                               "new inputs")
        entry["non_claim"] = ("a candidate is a stability observation only; "
                              "it asserts nothing about which labels are "
                              "more accurate")
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Static audit context (consumer map, doc reconciliation, non-claims)
# ---------------------------------------------------------------------------


def _consumer_map() -> list[dict]:
    return [
        {
            "consumer": "GET /events/{id} + cached POST /analyze restore",
            "where": "routes/events.py + api._build_cached_response",
            "reads": "whole reaction_profile_v1 block (available, reason, "
                     "n_tickers, per-ticker profile incl. basis and "
                     "hydration_status)",
            "horizon_privileged": "none (full surface)",
            "exposes_denominator_and_basis": True,
            "distinguishes_missing_states": True,
            "description_status": "current",
        },
        {
            "consumer": "ReactionProfileCard",
            "where": "frontend/src/components/pages/analysis-view.tsx",
            "reads": "available, reason, n_tickers, first 4 tickers: "
                     "symbol, reaction_profile_basis, fade_or_hold_label_*",
            "horizon_privileged": "20d via null-coalescing "
                     "(label_20d ?? label_5d ?? label_60d); composer labels "
                     "are always strings, so a 20d 'insufficient' wins over "
                     "a scorable 5d label",
            "exposes_denominator_and_basis": True,
            "distinguishes_missing_states": True,
            "description_status": "current",
        },
        {
            "consumer": "GET /diagnostics/track-record",
            "where": "routes/diagnostics.py",
            "reads": "per-ticker hydrated return_5d, peak_move_20d, "
                     "fade_or_hold_label_20d (insufficient excluded), "
                     "joined to validation_status_v2 counts",
            "horizon_privileged": "20d for labels, 5d for average returns; "
                     "ticker-weighted, all clusters pooled",
            "exposes_denominator_and_basis": "coverage notes but no basis "
                     "split",
            "distinguishes_missing_states": "partially (coverage notes)",
            "description_status": "current; no mounted frontend consumer "
                     "(lib/api.ts method is an orphan)",
        },
        {
            "consumer": "GET /diagnostics/reaction-profile-stats",
            "where": "routes/diagnostics.py",
            "reads": "stored scalar returns only (_ticker_has_return); "
                     "never invokes the hydrator",
            "horizon_privileged": "none",
            "exposes_denominator_and_basis": "event-level pseudo-basis "
                     "(scalar_returns_only / unscorable) not in "
                     "REACTION_PROFILE_BASES",
            "distinguishes_missing_states": False,
            "description_status": "STALE - see stale_diagnostics_contract",
        },
        {
            "consumer": "GET /diagnostics/reaction-profile-blockers",
            "where": "routes/diagnostics.py",
            "reads": "canonical hydrator per ticker; mutually exclusive "
                     "blocker buckets",
            "horizon_privileged": "20d (success bucket = hydrated through "
                     "20d; no 60d bucket)",
            "exposes_denominator_and_basis": True,
            "distinguishes_missing_states": True,
            "description_status": "current",
        },
        {
            "consumer": "tests",
            "where": "tests/test_reaction_profile.py, "
                     "tests/test_reaction_profile_hydration.py, "
                     "tests/test_events_reaction_profile_wiring.py",
            "reads": "full composer + hydrator + wiring contracts",
            "horizon_privileged": "none",
            "exposes_denominator_and_basis": True,
            "distinguishes_missing_states": True,
            "description_status": "current",
        },
    ]


def _doc_disagreements() -> list[str]:
    return [
        "docs/reaction_profile_design.md section 3.6 recommends reusing the "
        "relative_return_* field family; the shipped composer emits "
        "benchmark_relative_return_* instead. Production wins; the doc is "
        "historical.",
        "docs/reaction_profile_design.md section 6 sketches event-level "
        "rollups (basket_return_*, direction_consistency); none are "
        "implemented. build_reaction_profile_v1 is per-ticker plus counts.",
        "docs/reaction_profile_design.md section 3.5 phrases reverse as "
        "sign(final) != sign(peak); production explicitly treats "
        "final == 0 as NOT a sign flip (falls through to fade).",
        "docs/reaction_profile_hydration_plan.md section 2 states stale and "
        "same_day_fallback are already on saved ticker blocks; on the "
        "audited archive no stored ticker dict carries either key (the "
        "hydrator's bool(...) default of False is what actually runs).",
    ]


def _stale_diagnostics_contract() -> dict:
    return {
        "endpoint": "GET /diagnostics/reaction-profile-stats",
        "finding": (
            "The endpoint's docstring and computation still claim the "
            "archive stores only per-ticker scalar returns and that "
            "compute_reaction_profile 'cannot actually run' on archived "
            "rows, classifying readiness via _ticker_has_return into "
            "scalar_returns_only / unscorable. Since the hydration layer "
            "shipped, reaction_profile_v1 hydrates raw close paths from "
            "the local price_cache (used by /diagnostics/track-record and "
            "/diagnostics/reaction-profile-blockers), so this endpoint "
            "understates real readiness and reports a basis vocabulary "
            "that does not exist in REACTION_PROFILE_BASES."),
        "affects_this_audit": (
            "No. The audit reads the canonical hydrator directly and "
            "never consults this endpoint."),
        "classification": "bounded future consumer debt; not repaired here",
    }


def _non_claims() -> list[str]:
    return [
        "No claim that any label is accurate: there is no independent "
        "ground truth for whether a reaction truly held, faded or "
        "reversed. This audit characterizes stability, coverage and "
        "boundary behaviour only.",
        "No predictive validation is performed or implied.",
        "Labels are descriptive tape reads, not thesis outcomes; no "
        "mapping from hold/fade/reverse to validated/contradicted is "
        "asserted, and none should be inferred.",
        "Cluster counts are an independence caution, not an effective "
        "statistical sample size.",
        "The benchmark-relative and adjusted-basis lenses are audit-only "
        "sensitivity views, not proposed production rules.",
        "Not a recommendation, forecast, or trading signal; no buy or "
        "sell framing exists or is implied anywhere in this audit.",
    ]


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _floor_coherence() -> dict:
    out = {
        "reaction_profile": {"1d": _rp._NOISE_1D_PCT,
                             "5d": _rp._NOISE_5D_PCT,
                             "20d": _rp._NOISE_20D_PCT,
                             "60d": _rp._NOISE_60D_PCT},
        "validation_evidence": None,
        "match_1d": None, "match_5d": None, "match_20d": None,
        "note": ("the 60d floor exists only in reaction_profile.py; the "
                 "borrowed layer (validation_evidence) has no 60d floor "
                 "to stay coherent with"),
    }
    try:
        import validation_evidence as _ve
        ve = {"1d": _ve._NOISE_1D_PCT, "5d": _ve._NOISE_5D_PCT,
              "20d": _ve._NOISE_20D_PCT}
        out["validation_evidence"] = ve
        out["match_1d"] = ve["1d"] == _rp._NOISE_1D_PCT
        out["match_5d"] = ve["5d"] == _rp._NOISE_5D_PCT
        out["match_20d"] = ve["20d"] == _rp._NOISE_20D_PCT
    except Exception:
        out["note"] = "validation_evidence constants unavailable"
    return out


def _cluster_rows(accepted: list[dict], db_path: str) -> tuple[list[dict], dict]:
    """Rows for the canonical K2 clustering + edq reconciliation info."""
    links: dict[int, list[int]] = {}
    edq_accepted: set = set()
    edq_ok = False
    try:
        from scripts.event_date_quality_report import build_report as _edq
        edq = _edq(db_path=db_path)
        for e in edq.get("events", []):
            eid = e.get("event_id")
            if e.get("corpus_status") == "accepted":
                edq_accepted.add(eid)
            links[eid] = _parse_duplicate_ids(e.get("thread_independence"))
        edq_ok = True
    except Exception:
        pass
    rows = []
    for ev in accepted:
        eid = ev.get("id")
        rows.append({
            "event_id": eid,
            "date": (ev.get("event_date") or "")[:10] or None,
            "primary_ticker": _primary_ticker(ev.get("market_tickers")),
            "duplicate_of": links.get(eid, []),
        })
    accepted_ids = {ev.get("id") for ev in accepted}
    recon = {
        "edq_available": edq_ok,
        "edq_accepted_count": len(edq_accepted),
        "reconciles_with_edq": edq_ok and edq_accepted == accepted_ids,
    }
    return rows, recon


def build_report(*, db_path: str) -> dict:
    """Build the calibration audit dict.  Read-only; never mutates data."""
    db_sha_before = _sha256_file(db_path)
    decoded, synthetic = _load_rows(db_path)
    non_thesis = getattr(db, "NON_THESIS_STAGES", frozenset())

    excl_stage = excl_syn = 0
    accepted: list[dict] = []
    for ev in decoded:
        cls = classify_eligibility(ev, synthetic_ids=synthetic,
                                   non_thesis_stages=non_thesis)
        if cls == "excluded_non_thesis_stage":
            excl_stage += 1
        elif cls == "excluded_synthetic_seed":
            excl_syn += 1
        else:
            accepted.append(ev)

    assembled = _assemble(accepted, db_path)
    observations = assembled["observations"]
    per_event = assembled["per_event"]
    tf = assembled["ticker_funnel"]
    equivalence = assembled["equivalence"]

    cluster_rows, cluster_recon = _cluster_rows(accepted, db_path)
    clusters = build_clusters(cluster_rows)
    cluster_of: dict[int, str] = {}
    for c in clusters:
        for eid in c["event_ids"]:
            cluster_of[eid] = c["cluster_id"]

    # Event-level funnel.
    events_scorable = {h: 0 for h in PEAK_HORIZONS}
    hydrated_events = 0
    reasons = Counter()
    stored_events = 0
    valid_dict_events = 0
    for eid in sorted(per_event):
        info = per_event[eid]
        if info["stored"] > 0:
            stored_events += 1
        if info["valid"] > 0:
            valid_dict_events += 1
        ev_obs = [o for o in observations if o["event_id"] == eid]
        if any(o["hydration_status"] == "hydrated" for o in ev_obs):
            hydrated_events += 1
        else:
            if info["stored"] == 0:
                reasons["no_stored_tickers"] += 1
            elif info["valid"] == 0:
                reasons["no_valid_ticker_dicts"] += 1
            else:
                statuses = set(info["statuses"])
                if statuses == {"cache_miss"}:
                    reasons["all_cache_miss"] += 1
                elif statuses == {"stale"}:
                    reasons["all_stale"] += 1
                elif statuses == {"same_day_fallback"}:
                    reasons["all_same_day_fallback"] += 1
                elif statuses == {"insufficient_window"}:
                    reasons["all_insufficient_window"] += 1
                else:
                    reasons["mixed_non_hydrated"] += 1
        for h in PEAK_HORIZONS:
            if any(_scorable(o, h) for o in ev_obs):
                events_scorable[h] += 1

    funnel = {
        "archive_rows": len(decoded),
        "excluded_non_thesis_stage": excl_stage,
        "excluded_synthetic_seed": excl_syn,
        "accepted": len(accepted),
        "accepted_with_stored_tickers": stored_events,
        "accepted_with_valid_ticker_dicts": valid_dict_events,
        "accepted_with_hydrated_profile": hydrated_events,
        "events_scorable_5d": events_scorable["5d"],
        "events_scorable_20d": events_scorable["20d"],
        "events_scorable_60d": events_scorable["60d"],
        "events_without_hydrated_profile_reasons": dict(sorted(
            reasons.items())),
    }

    tf["scorable_by_horizon"] = {
        h: sum(1 for o in observations if _scorable(o, h))
        for h in PEAK_HORIZONS}
    tf["holdfade_eligible_by_horizon"] = {
        h: sum(1 for o in observations
               if _scorable(o, h) and o["labels"][h] in ("hold", "fade"))
        for h in PEAK_HORIZONS}
    tf["benchmark_path_by_horizon"] = {
        h: sum(1 for o in observations
               if _scorable(o, h) and o["bench_available"][h])
        for h in PEAK_HORIZONS}
    tf["quarantined_benchmark_tickers"] = sum(
        1 for o in observations if o["quarantined"])

    forward_obs = [o for o in observations
                   if o["basis"] == "forward_anchored"]
    pre_counts = [o["pre_anchor_bars"] for o in forward_obs
                  if o["pre_anchor_bars"] is not None]
    n_20plus = sum(1 for n in pre_counts if n >= 20)
    volatility = {
        "local_point_in_time_volatility_module": False,
        "forward_anchored_observations": len(forward_obs),
        "observations_with_any_pre_anchor_bars": sum(
            1 for n in pre_counts if n > 0),
        "observations_with_20plus_pre_anchor_bars": n_20plus,
        "evaluable": (n_20plus >= _VOL_MIN_OBS
                      and len(forward_obs) > 0
                      and n_20plus >= _VOL_MIN_SHARE * len(forward_obs)),
        "note": ("a volatility-scaled floor would need a point-in-time "
                 "pre-event volatility estimate; the cache is anchored "
                 "forward from each event, so pre-anchor bars exist only "
                 "incidentally"),
    }

    label_distributions = _label_distributions(
        observations, per_event, cluster_of)
    retention = _retention_section(observations, cluster_of)
    noise_floors = _noise_floor_section(observations, per_event)
    scale_bias = _scale_bias_section(observations)
    rounding = _rounding_section(observations, cluster_of)
    benchmark_relative = _benchmark_section(observations)
    adjusted_basis = _adjusted_section(observations)
    horizon = _horizon_section(observations, clusters, cluster_of)
    leave_out = _leave_out_section(observations, per_event, clusters,
                                   cluster_of)

    # Floor value lists from the observations (unrounded |peak|).
    floor_values: dict[str, list[float]] = {h: [] for h in PEAK_HORIZONS}
    for o in observations:
        for h in PEAK_HORIZONS:
            if _scorable(o, h) and o["peak_unrounded"].get(h) is not None:
                floor_values[h].append(_r6(abs(o["peak_unrounded"][h])))

    retention_values = [r["ratio"] for r in retention["ratios"]]
    raw_candidates = derive_candidates(retention_values, floor_values)
    candidates = _evaluate_candidates(
        raw_candidates, observations, retention["ratios"], cluster_of)

    eligible_total = retention["eligible_total"]
    boundary_share = (retention["boundary"]["within_005"] / eligible_total
                      if eligible_total else 0.0)
    metrics = {
        "equivalence_mismatches": equivalence["mismatches"],
        "accepted_n": len(accepted),
        "events_scorable_20d": funnel["events_scorable_20d"],
        "eligible_holdfade_total": eligible_total,
        "boundary_share_pm005": _r6(boundary_share),
        "rounding_flip_share": rounding["flip_share"],
        "loeo_modal_flip": leave_out["loeo"]["modal_flip"],
        "loco_modal_flip": leave_out["loco"]["modal_flip"],
        "admissible_candidates": len(candidates),
    }
    recommendation = recommend(metrics)
    recommendation["guards"] = metrics

    unavailable = []
    if volatility["evaluable"]:
        unavailable.append(
            "volatility-scaled noise floors: pre-anchor cached bars exist "
            f"for {n_20plus} of {len(forward_obs)} forward-anchored "
            "observations, so the data side is evaluable, but no local "
            "point-in-time volatility measure module exists and none was "
            "built here; classified as future research, not performed")
    else:
        unavailable.append(
            "volatility-scaled noise floors: no local point-in-time "
            "volatility measure exists and pre-anchor cached bars cover "
            f"only {n_20plus} of {len(forward_obs)} forward-anchored "
            "observations; classified as future research")
    if not adjusted_basis["available"]:
        unavailable.append("adjusted/raw basis sensitivity: no matched "
                           "raw+adjusted observation exists in the cache")
    if funnel["events_scorable_60d"] == 0:
        unavailable.append("60d calibration surface: zero events are "
                           "scorable at 60d on this archive")
    if len(leave_out["loyo"]["years"]) < 2:
        unavailable.append("leave-one-year-out: fewer than two event-date "
                           "years in the 20d-scorable set")
    unavailable.append(
        "independent ground-truth labels for hold/fade/reverse: none "
        "exist; accuracy calibration is permanently out of scope for "
        "this data")

    db_sha_after = _sha256_file(db_path)
    return {
        "contract_version": CONTRACT_VERSION,
        "db_basename": Path(db_path).name,
        "db_sha256": db_sha_before,
        "db_sha256_after": db_sha_after,
        "db_unchanged": db_sha_before == db_sha_after,
        "production_rule": {
            "noise_floors_pct": dict(AUDIT_NOISE_FLOORS),
            "retention_threshold": AUDIT_RETENTION_THRESHOLD,
            "round_dp": _ROUND_DP,
            "label_order": ["insufficient (missing peak/final)",
                            "flat (|peak| < floor)",
                            "reverse (opposite signs; final==0 is not a "
                            "flip)",
                            "hold (|final|/|peak| >= threshold, inclusive)",
                            "fade (otherwise)"],
            "peak_definition": "largest absolute deviation from anchor; "
                               "ties select the earliest bar",
            "rounding_order": "peak and final are rounded to 2dp before "
                              "the label is produced",
            "basis": "raw closes (auto_adjust=0) from the local "
                     "price_cache; no provider fetch",
        },
        "floor_coherence": _floor_coherence(),
        "consumer_map": _consumer_map(),
        "doc_disagreements": _doc_disagreements(),
        "stale_diagnostics_contract": _stale_diagnostics_contract(),
        "funnel": funnel,
        "ticker_funnel": tf,
        "equivalence": equivalence,
        "label_distributions": label_distributions,
        "retention": retention,
        "noise_floors": noise_floors,
        "scale_bias": scale_bias,
        "volatility_floor_evaluability": volatility,
        "rounding": rounding,
        "benchmark_relative": benchmark_relative,
        "adjusted_basis": adjusted_basis,
        "horizon": horizon,
        "clusters": {
            "nominal_events": len(accepted),
            "cluster_count": len(clusters),
            "singletons": sum(1 for c in clusters if c["size"] == 1),
            "multi": sum(1 for c in clusters if c["size"] >= 2),
            "largest_size": clusters[0]["size"] if clusters else 0,
            "largest_id": clusters[0]["cluster_id"] if clusters else None,
            "assignment": {str(eid): cid
                           for eid, cid in sorted(cluster_of.items())},
            **cluster_recon,
        },
        "leave_out": leave_out,
        "candidates": candidates,
        "recommendation": recommendation,
        "unavailable_analyses": unavailable,
        "non_claims": _non_claims(),
        "observations": [
            {
                "event_id": o["event_id"], "symbol": o["symbol"],
                "basis": o["basis"],
                "hydration_status": o["hydration_status"],
                "labels": o["labels"],
                "labels_unrounded": o["labels_unrounded"],
                "ratio_unrounded": o["ratio_unrounded"],
                "cluster_id": cluster_of.get(o["event_id"]),
            }
            for o in observations
        ],
        "reproduce": {
            "commands": [
                "python -m scripts.reaction_profile_calibration_report "
                "--db-path events.db",
                "python -m scripts.reaction_profile_calibration_report "
                "--db-path events.db --json",
            ],
        },
    }


# ---------------------------------------------------------------------------
# Deterministic Markdown rendering (compact; row detail lives in --json)
# ---------------------------------------------------------------------------


def _fmt_share(share: dict) -> str:
    return "; ".join(f"{lab} {share.get(lab, 0)}" for lab in LABELS)


def _fmt_counts(counts: dict) -> str:
    return "; ".join(f"{lab} {counts.get(lab, 0)}" for lab in LABELS)


def render_markdown(report: dict) -> str:
    L: list[str] = []
    f = report["funnel"]
    tf = report["ticker_funnel"]
    ret = report["retention"]
    rec = report["recommendation"]

    L.append("# Reaction-profile classification calibration (read-only)")
    L.append("")
    L.append(f"Contract: `{report['contract_version']}`. Verdict: "
             f"**{rec['verdict']}**.")
    for r in rec["reasons"]:
        L.append(f"- {r}")
    L.append("")
    L.append(f"- source database: `{report['db_basename']}`")
    L.append(f"- database sha256: `{report['db_sha256']}`")
    L.append(f"- database unchanged during run: {report['db_unchanged']}")
    L.append("- note: the snapshot sha is a whole-file hash covering "
             "volatile non-research tables; it is a same-run safety proof, "
             "not a reproduction key.")
    L.append("")

    L.append("## Question and non-claim")
    L.append("")
    L.append("Do the current labels describe the archived price paths "
             "stably, or are they materially driven by the unvalidated "
             "noise floors, the 0.70 retention threshold, 2dp rounding, "
             "the raw-price basis, the horizon surface or duplicated "
             "market stories? No accuracy claim is possible: there is no "
             "independent ground truth for hold/fade/reverse.")
    L.append("")

    L.append("## Current production rule")
    L.append("")
    pr = report["production_rule"]
    L.append(f"- noise floors (percent): {pr['noise_floors_pct']}")
    L.append(f"- retention threshold: {pr['retention_threshold']} "
             "(inclusive)")
    L.append(f"- rounding: {pr['rounding_order']}")
    L.append(f"- peak: {pr['peak_definition']}")
    L.append(f"- basis: {pr['basis']}")
    fc = report["floor_coherence"]
    L.append(f"- floor coherence with validation_evidence: 1d "
             f"{fc['match_1d']}, 5d {fc['match_5d']}, 20d {fc['match_20d']}; "
             f"{fc['note']}")
    L.append("")

    L.append("## Consumer map")
    L.append("")
    for c in report["consumer_map"]:
        L.append(f"- **{c['consumer']}** ({c['where']}): reads "
                 f"{c['reads']}. Horizon: {c['horizon_privileged']}. "
                 f"Status: {c['description_status']}.")
    L.append("")
    sd = report["stale_diagnostics_contract"]
    L.append(f"Stale contract recorded (not repaired): {sd['endpoint']} - "
             f"{sd['finding']} {sd['classification']}.")
    L.append("")
    L.append("Historical design docs reconciled against production:")
    for d in report["doc_disagreements"]:
        L.append(f"- {d}")
    L.append("")

    L.append("## Eligibility funnel")
    L.append("")
    L.append(f"- archive rows: {f['archive_rows']}")
    L.append(f"- excluded, non-thesis stage: {f['excluded_non_thesis_stage']}")
    L.append(f"- excluded, synthetic seed: {f['excluded_synthetic_seed']}")
    L.append(f"- accepted (denominator): **{f['accepted']}**")
    L.append(f"- accepted with stored tickers: "
             f"{f['accepted_with_stored_tickers']}")
    L.append(f"- accepted with a hydrated profile: "
             f"{f['accepted_with_hydrated_profile']}")
    L.append(f"- events scorable at 5d / 20d / 60d: "
             f"{f['events_scorable_5d']} / {f['events_scorable_20d']} / "
             f"{f['events_scorable_60d']}")
    L.append(f"- events without a hydrated profile, by reason: "
             f"{f['events_without_hydrated_profile_reasons']}")
    L.append("- the scorable subset is never used as the accepted "
             "denominator; unavailable events stay visible above.")
    L.append("")

    L.append("## Ticker-level coverage")
    L.append("")
    L.append(f"- stored entries {tf['stored_entries']}; non-dict "
             f"{tf['non_dict_entries']}; missing symbol "
             f"{tf['missing_symbol_entries']}; valid "
             f"{tf['valid_ticker_dicts']}")
    L.append(f"- hydration status: {tf['hydration_status_counts']}")
    L.append(f"- basis: {tf['basis_counts']}")
    L.append(f"- scorable by horizon: {tf['scorable_by_horizon']}")
    L.append(f"- hold/fade-eligible by horizon: "
             f"{tf['holdfade_eligible_by_horizon']}")
    L.append(f"- benchmark path available by horizon: "
             f"{tf['benchmark_path_by_horizon']}")
    L.append(f"- quarantined benchmark observations: "
             f"{tf['quarantined_benchmark_tickers']}")
    L.append("")

    L.append("## Classifier reproduction")
    L.append("")
    eq = report["equivalence"]
    L.append(f"- audit-side reproduction checked {eq['checked']} "
             f"(observation, horizon) pairs; mismatches: "
             f"**{eq['mismatches']}**")
    L.append("")

    L.append("## Label distributions")
    L.append("")
    for h in PEAK_HORIZONS:
        d = report["label_distributions"][h]
        twc = d["ticker_weighted"]
        L.append(f"### {h}")
        L.append(f"- ticker-weighted (n={twc['denominator_scorable']}): "
                 f"{_fmt_counts(twc['counts'])}; insufficient (forward) "
                 f"{twc['insufficient_forward']}; non-forward basis "
                 f"{twc['non_forward_basis']}")
        ew = d["event_weighted"]
        L.append(f"- event-weighted (events={ew['events']}): "
                 f"{_fmt_share(ew['share'])}; all-agree {ew['all_agree']}, "
                 f"mixed {ew['mixed']}")
        po = d["primary_only"]
        L.append(f"- primary-ticker-only "
                 f"(n={po['events_with_primary_scorable']}): "
                 f"{_fmt_counts(po['counts'])}")
        cw = d["cluster_weighted"]
        L.append(f"- cluster-weighted (clusters={cw['clusters']}): "
                 f"{_fmt_share(cw['share'])}")
    L.append("")

    L.append("## Retention-ratio behaviour (0.70 threshold)")
    L.append("")
    L.append(f"- eligible observations: {ret['eligible_total']} "
             f"({ret['eligible_by_horizon']}); final-zero "
             f"{ret['final_zero_count']}; unique values {ret['n_unique']}")
    L.append(f"- quantiles: {ret['quantiles']}")
    b = ret["boundary"]
    L.append(f"- around 0.70: nearest below {b['nearest_below']}, nearest "
             f"at/above {b['nearest_at_or_above']}, gap "
             f"{b['gap_width']}; within +/-0.02: {b['within_002']}, "
             f"+/-0.05: {b['within_005']}, +/-0.10: {b['within_010']}; "
             f"exactly 0.70 after rounding: {b['exactly_070_rounded']}")
    if b["boundary_observations"]:
        rows = ", ".join(
            f"{r['event_id']}/{r['symbol']}/{r['horizon']} ({r['ratio']})"
            for r in b["boundary_observations"][:8])
        L.append(f"- boundary observations (+/-0.05): {rows}")
        L.append(f"- boundary cluster concentration: "
                 f"{b['boundary_cluster_counts']}")
    wig = ret["widest_interior_gap"]
    L.append(f"- widest interior plateau: {wig}")
    L.append(f"- labels that depend on 2dp rounding at this boundary: "
             f"{ret['rounding_dependent_count']}")
    L.append("- the full transition curve over every observed breakpoint "
             "is in the --json output.")
    L.append("")

    L.append("## Noise floors")
    L.append("")
    for h in PEAK_HORIZONS:
        nf = report["noise_floors"][h]
        L.append(f"- **{h}** (floor {nf['current_floor']}%): n={nf['n']}, "
                 f"|peak| quantiles {nf['quantiles']}; flat "
                 f"{nf['below_floor']}; within +/-0.25pp of the floor "
                 f"{nf['within_025pp']}; rounding flips "
                 f"{nf['rounding_flips']}; boundary {nf['boundary']}; "
                 f"widest interior plateau {nf['widest_interior_gap']}")
    sb = report["scale_bias"]
    if sb.get("available"):
        L.append(f"- scale-bias probe (20d, {sb['tickers']} tickers): "
                 f"low-half flat share {sb['low_half']['flat_share']} "
                 f"({sb['low_half']['observations']} obs), high-half "
                 f"{sb['high_half']['flat_share']} "
                 f"({sb['high_half']['observations']} obs). {sb['note']}.")
    else:
        L.append(f"- scale-bias probe: {sb.get('note')}")
    vol = report["volatility_floor_evaluability"]
    L.append(f"- volatility-scaled floor evaluability: {vol['evaluable']} "
             f"({vol['observations_with_20plus_pre_anchor_bars']} of "
             f"{vol['forward_anchored_observations']} forward observations "
             f"have 20+ pre-anchor bars). {vol['note']}.")
    L.append("")

    L.append("## Rounding sensitivity")
    L.append("")
    rd = report["rounding"]
    L.append(f"- checked {rd['scorable_checked']} labels; flips "
             f"{rd['total_flips']} (share {rd['flip_share']}); by horizon "
             f"{rd['by_horizon']}; transitions {rd['transitions']}")
    L.append(f"- at the flat floor: {rd['at_flat_floor']}; at the hold "
             f"threshold: {rd['at_hold_threshold']}; max 20d ticker-share "
             f"delta {rd['ticker_share_20d_max_delta']}")
    L.append("")

    L.append("## Raw vs benchmark-relative sensitivity")
    L.append("")
    br = report["benchmark_relative"]
    L.append(f"- matched {br['matched_by_horizon']}; unavailable "
             f"{br['unavailable_by_horizon']}; misaligned "
             f"{br['misaligned_by_horizon']}; quarantined "
             f"{br['quarantined_observations']}")
    L.append(f"- {br['alignment_note']}")
    L.append(f"- label changes {br['label_change_count']}; sign flips "
             f"{br['sign_flip_count']}; hold/fade swaps "
             f"{br['hold_fade_change_count']}")
    for h in PEAK_HORIZONS:
        m = br["transition_matrix"][h]
        if m:
            L.append(f"- {h} transitions: {m}")
    ab = report["adjusted_basis"]
    L.append(f"- adjusted-basis lens: available {ab['available']}; matched "
             f"{ab['matched_by_horizon']}; changes "
             f"{ab['label_change_count']}. {ab['note']}.")
    L.append("")

    L.append("## Horizon and consumer sensitivity")
    L.append("")
    hz = report["horizon"]
    t520 = hz["t5_vs_t20"]
    L.append(f"- 5d vs 20d: matched {t520['matched']}, agree "
             f"{t520['agree']}; matrix {t520['matrix']}")
    t2060 = hz["t20_vs_t60"]
    L.append(f"- 20d vs 60d: matched {t2060['matched']}, agree "
             f"{t2060['agree']}")
    fp = hz["frontend_priority"]
    L.append(f"- frontend 20d-first display: {fp['displayed_from_20d']} of "
             f"{fp['tickers_with_block']} shown from 20d; shows "
             f"'insufficient' while another horizon has a label: "
             f"{fp['displayed_insufficient_with_other_signal']}; hides a "
             f"disagreeing horizon label: "
             f"{fp['displayed_hides_disagreement']}; cases where only 60d "
             f"carries information: {fp['sixtyd_only_information']}")
    tr = hz["track_record"]
    L.append(f"- /diagnostics/track-record composition (20d, "
             f"ticker-weighted): {tr['histogram_20d']}; insufficient "
             f"excluded {tr['insufficient_excluded']}; largest-cluster "
             f"share {tr['largest_cluster_share']}")
    L.append("")

    L.append("## Independence-aware view")
    L.append("")
    cl = report["clusters"]
    L.append(f"- {cl['nominal_events']} accepted events group into "
             f"{cl['cluster_count']} market-story clusters "
             f"({cl['singletons']} singletons, {cl['multi']} multi-row; "
             f"largest {cl['largest_size']}); reconciles with the K2 lens: "
             f"{cl['reconciles_with_edq']}")
    L.append("")

    L.append("## Leave-out tests")
    L.append("")
    lo = report["leave_out"]
    L.append(f"- base event-weighted 20d shares: "
             f"{_fmt_share(lo['base']['share'])} (modal "
             f"{lo['base']['modal']}, events {lo['base']['events']})")
    L.append(f"- leave-one-event-out ({lo['loeo']['runs']} runs): ranges "
             f"{lo['loeo']['share_ranges_20d']}; modal flip "
             f"{lo['loeo']['modal_flip']}")
    L.append(f"- leave-one-year-out (years {lo['loyo']['years']}): "
             f"{lo['loyo']['share_ranges_20d'] or lo['loyo']['note']}")
    L.append(f"- leave-one-cluster-out ({lo['loco']['runs']} runs): ranges "
             f"{lo['loco']['share_ranges_20d']}; modal flip "
             f"{lo['loco']['modal_flip']}; without largest cluster: "
             f"{lo['loco']['without_largest']}")
    L.append(f"- no same-day fallback: share "
             f"{lo['no_sdf']['share_20d']}")
    L.append(f"- no quarantined benchmark rows: share "
             f"{lo['no_quarantine']['share_20d']}")
    L.append(f"- multi-ticker events only ({lo['no_single_ticker']['events']}"
             f" events): {lo['no_single_ticker']['share_20d']}")
    L.append(f"- primary vs all-ticker (20d): primary "
             f"{lo['primary_vs_all']['primary_share_20d']}, all "
             f"{lo['primary_vs_all']['all_ticker_share_20d']}, max delta "
             f"{lo['primary_vs_all']['max_abs_delta']}")
    L.append("")

    L.append("## Candidate comparison")
    L.append("")
    if report["candidates"]:
        for c in report["candidates"]:
            L.append(f"- **{c['kind']}**: current {c['current']} -> "
                     f"proposed {c['proposed']} (plateau {c['gap_low']}.."
                     f"{c['gap_high']}); why: {c['why']}; changes "
                     f"{c['changed_count']} observation(s) across "
                     f"{c['events_changed']} event(s); cluster "
                     f"concentration {c['cluster_concentration']}; "
                     f"{c['non_claim']}")
    else:
        L.append("- no candidate rule is admissible: no visible empirical "
                 "plateau dominates the current values under the "
                 "documented conventions. The current rule remains the "
                 "only rule in the comparison.")
    L.append("")

    L.append("## Recommendation")
    L.append("")
    g = rec["guards"]
    L.append(f"- guard inputs: {g}")
    L.append(f"- audit conventions: minimum {_MIN_SCORABLE_EVENTS_20D} "
             f"scorable 20d events; minimum {_MIN_ELIGIBLE_HOLDFADE} "
             f"hold/fade-eligible observations; dense-boundary share "
             f"{_DENSE_BOUNDARY_SHARE}; rounding-flip share "
             f"{_ROUNDING_FLIP_SHARE_MAX}; candidate admissibility needs "
             f"{_DENSE_MIN_OBS}+ observations at the boundary and a "
             f"plateau {_GAP_DOMINANCE}x wider than the current gap.")
    L.append("")
    L.append("### Falsifier / reopen condition")
    L.append("")
    L.append("- Reopen this calibration when any of: the accepted archive "
             "grows enough that the guard inputs above cross their "
             "documented floors; a validator or the equivalence check in "
             "this report fails; the production constants in "
             "reaction_profile.py change; or the 60d surface gains its "
             "first scorable events.")
    L.append("")

    L.append("## Unavailable analyses")
    L.append("")
    for u in report["unavailable_analyses"]:
        L.append(f"- {u}")
    L.append("")

    L.append("## Permanent non-claims")
    L.append("")
    for nc in report["non_claims"]:
        L.append(f"- {nc}")
    L.append("")

    L.append("## Reproduce (read-only)")
    L.append("")
    L.append("```")
    for cmd in report["reproduce"]["commands"]:
        L.append(cmd)
    L.append("```")
    L.append("")
    L.append(f"### {rec['verdict']}")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only reaction-profile classification calibration "
                    "audit.")
    ap.add_argument("--db-path", required=True,
                    help="path to events.db (opened read-only)")
    ap.add_argument("--json", action="store_true",
                    help="emit the full report dict as JSON instead of "
                         "Markdown")
    ap.add_argument("--out", default=None,
                    help="write output here (default: stdout)")
    args = ap.parse_args(argv)

    report = build_report(db_path=args.db_path)
    if args.json:
        out = json.dumps(report, indent=2, sort_keys=True)
    else:
        out = render_markdown(report)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
