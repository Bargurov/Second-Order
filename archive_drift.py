"""Archive drift — theme trends + regime drift summaries over time.

Buckets stored events by ``event_date`` into rolling windows and
reports:

* Theme trends: how each mechanism family's share of the archive has
  shifted between the most-recent window and the window just before.
* Regime drift: how the dominant value on each regime axis
  (``inflation``, ``policy_stance``, ``fx``, ``growth_stress``,
  ``credit``, ``curve_shape``, ``inflation_path``) has changed
  window-to-window.

Turns the archive from a static analytics page into a surface that
shows *how the macro structure itself is moving*.

Design notes
------------
* Pure composer: no I/O, never raises on malformed input.
* Windows are configurable but default to a sensible 3-window layout
  (0–30d, 30–90d, 90–180d) — enough to see what's changing without
  over-fitting on small archives.
* All date math uses the event's ``event_date`` when available,
  falling back to ``timestamp`` so legacy rows without a market
  anchor still participate.
* The composer is deliberately separated from the route handler so
  every scoring decision is unit-testable without booting FastAPI.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Constants — pinned so calibrate_thresholds can audit.
# ---------------------------------------------------------------------------

# Default window offsets in days from "now". Each entry is the upper
# bound; the lower bound is the previous entry (or 0 for the first).
DEFAULT_WINDOWS_DAYS: tuple[int, ...] = (30, 90, 180)

# Regime axes we surface in the drift block.  Limited to the axes the
# regime vector actually emits today — new axes can be added as the
# vector grows without touching the composer shape.
REGIME_AXES: tuple[str, ...] = (
    "inflation", "policy_stance", "fx", "growth_stress",
    "credit", "curve_shape", "inflation_path",
)

# Share-delta thresholds for trend magnitudes (percentage points).
_TREND_LARGE: float = 0.15
_TREND_MEDIUM: float = 0.07
_TREND_SMALL: float = 0.03

# Minimum cohort size in a window before its drift reading is
# considered reliable.  Below this, the window is surfaced but the
# confidence field flags the thinness.
_WINDOW_THIN_SIZE: int = 3


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_event_date(ev: dict) -> Optional[date]:
    """Extract a usable ``date`` from an event's ``event_date`` or ``timestamp``.

    Tolerates legacy rows where only ``timestamp`` is set; returns
    ``None`` when neither field parses.
    """
    raw = ev.get("event_date") or ""
    if isinstance(raw, str) and raw:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    ts = ev.get("timestamp") or ""
    if isinstance(ts, str) and ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return None


def _window_label(lo_days: int, hi_days: int) -> str:
    if lo_days == 0:
        return f"last_{hi_days}d"
    return f"{lo_days}_{hi_days}d"


def _compute_window_ranges(
    now: date, offsets: Iterable[int],
) -> list[tuple[str, date, date]]:
    """Turn day offsets into (label, start, end) bounds, newest first."""
    offsets = list(offsets)
    bounds: list[tuple[str, date, date]] = []
    prev = 0
    for off in offsets:
        start = now - timedelta(days=off)
        end = now - timedelta(days=prev)
        bounds.append((_window_label(prev, off), start, end))
        prev = off
    return bounds


# ---------------------------------------------------------------------------
# Per-window aggregation
# ---------------------------------------------------------------------------

def _window_breakdown(members: list[dict]) -> dict[str, Any]:
    """Family + regime distributions for one window's events."""
    fam: dict[str, int] = {}
    regime_dists: dict[str, dict[str, int]] = {axis: {} for axis in REGIME_AXES}

    for ev in members:
        if not isinstance(ev, dict):
            continue
        fam_key = (ev.get("mechanism_family") or "none")
        fam[fam_key] = fam.get(fam_key, 0) + 1

        snap = ev.get("regime_snapshot")
        if not isinstance(snap, dict):
            continue
        for axis in REGIME_AXES:
            val = snap.get(axis)
            if not isinstance(val, str) or not val:
                continue
            bucket = regime_dists[axis]
            bucket[val] = bucket.get(val, 0) + 1

    regime_dominant = {}
    for axis, dist in regime_dists.items():
        if not dist:
            regime_dominant[axis] = {
                "dominant": None, "share": 0.0, "distribution": {},
            }
            continue
        top_key = max(dist.items(), key=lambda kv: (kv[1], kv[0]))[0]
        total = sum(dist.values())
        regime_dominant[axis] = {
            "dominant":     top_key,
            "share":        round(dist[top_key] / total, 3),
            "distribution": dist,
        }

    return {
        "size":                len(members),
        "family_distribution": fam,
        "regime":              regime_dominant,
    }


# ---------------------------------------------------------------------------
# Trend + drift computation
# ---------------------------------------------------------------------------

def _trend_magnitude(delta: float) -> str:
    a = abs(delta)
    if a >= _TREND_LARGE:
        return "large"
    if a >= _TREND_MEDIUM:
        return "medium"
    if a >= _TREND_SMALL:
        return "small"
    return "noise"


def _theme_trends(
    recent: dict, prior: dict,
) -> list[dict[str, Any]]:
    """Per-family share delta between the two most-recent windows."""
    r_fam = recent.get("family_distribution") or {}
    p_fam = prior.get("family_distribution") or {}
    r_total = sum(r_fam.values()) or 0
    p_total = sum(p_fam.values()) or 0
    all_families = sorted(set(r_fam) | set(p_fam))

    trends: list[dict[str, Any]] = []
    for fam in all_families:
        if fam == "none":
            continue
        r_share = (r_fam.get(fam, 0) / r_total) if r_total else 0.0
        p_share = (p_fam.get(fam, 0) / p_total) if p_total else 0.0
        delta = r_share - p_share
        if r_total == 0 and p_total == 0:
            mag = "noise"
        else:
            mag = _trend_magnitude(delta)
        trends.append({
            "family":       fam,
            "recent_share": round(r_share, 3),
            "prior_share":  round(p_share, 3),
            "delta":        round(delta, 3),
            "direction":    "up" if delta > 0 else "down" if delta < 0 else "flat",
            "magnitude":    mag,
            "recent_count": r_fam.get(fam, 0),
            "prior_count":  p_fam.get(fam, 0),
        })

    # Deterministic ordering: large deltas first (by |delta|), then
    # family name for ties so the output is stable across runs.
    trends.sort(key=lambda t: (-abs(t["delta"]), t["family"]))
    return trends


def _regime_drift(
    recent: dict, prior: dict,
) -> list[dict[str, Any]]:
    """Per-axis drift between the two most-recent windows.

    A ``drift`` entry carries whether the dominant value changed (and
    to what), plus the share each value held, so the UI can render the
    same structure whether or not the regime actually shifted.
    """
    r_reg = recent.get("regime") or {}
    p_reg = prior.get("regime") or {}
    drift: list[dict[str, Any]] = []
    for axis in REGIME_AXES:
        r_axis = r_reg.get(axis) or {}
        p_axis = p_reg.get(axis) or {}
        r_dom = r_axis.get("dominant")
        p_dom = p_axis.get("dominant")
        r_share = float(r_axis.get("share") or 0.0)
        p_share = float(p_axis.get("share") or 0.0)

        if r_dom is None and p_dom is None:
            direction = "unavailable"
            magnitude = "noise"
        elif r_dom == p_dom:
            direction = "stable"
            magnitude = _trend_magnitude(r_share - p_share)
        else:
            direction = "shifted"
            # Treat a shifted dominant value as at least "small" — the
            # category changed.  Scale up when the new regime's share
            # is decisive.
            magnitude = "large" if r_share >= 0.60 else "medium"

        drift.append({
            "axis":          axis,
            "recent":        r_dom,
            "recent_share":  round(r_share, 3),
            "prior":         p_dom,
            "prior_share":   round(p_share, 3),
            "direction":     direction,
            "magnitude":     magnitude,
        })
    return drift


# ---------------------------------------------------------------------------
# Summary prose
# ---------------------------------------------------------------------------

def _compose_summary(
    windows: list[dict],
    theme_trends: list[dict],
    regime_drift: list[dict],
) -> str:
    if not windows or windows[0]["size"] == 0:
        return "No recent events in the archive — nothing to track yet."

    recent = windows[0]
    size = recent["size"]
    parts: list[str] = [
        f"Last window: {size} event(s)",
    ]

    rising = [t for t in theme_trends if t["direction"] == "up" and t["magnitude"] != "noise"]
    falling = [t for t in theme_trends if t["direction"] == "down" and t["magnitude"] != "noise"]
    if rising:
        parts.append(f"rising themes: {', '.join(t['family'] for t in rising[:3])}")
    if falling:
        parts.append(f"fading themes: {', '.join(t['family'] for t in falling[:3])}")

    shifted = [d for d in regime_drift if d["direction"] == "shifted"]
    if shifted:
        shift_desc = ", ".join(
            f"{d['axis']}: {d['prior']}→{d['recent']}"
            for d in shifted[:3]
        )
        parts.append(f"regime shifts: {shift_desc}")

    if not rising and not falling and not shifted:
        parts.append("archive is quiet — no material drift")

    return "; ".join(parts) + "."


def _confidence_basis(windows: list[dict]) -> str:
    if not windows:
        return "thin"
    recent_size = windows[0]["size"] if windows else 0
    prior_size = windows[1]["size"] if len(windows) > 1 else 0
    if recent_size < _WINDOW_THIN_SIZE or prior_size < _WINDOW_THIN_SIZE:
        return "thin"
    if recent_size >= 10 and prior_size >= 10:
        return "deep"
    return "medium"


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def build_archive_drift(
    events: Optional[list[dict]],
    *,
    now: Optional[date] = None,
    windows_days: Optional[Iterable[int]] = None,
) -> dict[str, Any]:
    """Produce theme-trend + regime-drift summaries over rolling windows.

    Args:
        events: Stored event dicts.  Rows lacking ``event_date`` and
                ``timestamp`` are skipped.
        now:    Anchor date for window math.  Defaults to today's UTC
                date.  Override for deterministic tests.
        windows_days: Upper-bound offsets for each window in days.
                      Defaults to ``DEFAULT_WINDOWS_DAYS``.

    Returns:
        {
          "available": bool,
          "anchor_date": "YYYY-MM-DD",
          "windows": [
            {label, start, end, size, family_distribution, regime},
          ],
          "theme_trends":   [...],
          "regime_drift":   [...],
          "confidence_basis": "deep" | "medium" | "thin",
          "summary": str,
        }

    Never raises.  Empty / malformed input returns a well-formed result
    with ``available: False`` and the summary flagging thinness.
    """
    events = events or []
    anchor = now or datetime.utcnow().date()
    offsets = tuple(windows_days) if windows_days else DEFAULT_WINDOWS_DAYS
    bounds = _compute_window_ranges(anchor, offsets)

    # Bucket events into the first window they fall into.  Events
    # older than the last window's start get dropped — they belong to
    # a longer-horizon view.
    by_window: dict[str, list[dict]] = {label: [] for label, _, _ in bounds}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        d = _parse_event_date(ev)
        if d is None:
            continue
        for label, start, end in bounds:
            if start <= d < end:
                by_window[label].append(ev)
                break

    windows: list[dict[str, Any]] = []
    for label, start, end in bounds:
        br = _window_breakdown(by_window[label])
        windows.append({
            "label":                label,
            "start":                start.isoformat(),
            "end":                  end.isoformat(),
            "size":                 br["size"],
            "family_distribution":  br["family_distribution"],
            "regime":               br["regime"],
        })

    # Theme trends + regime drift compare the first two windows.  When
    # there's only one window we emit empty blocks rather than an
    # error — the UI treats empty as "not enough history".
    if len(windows) >= 2:
        trends = _theme_trends(windows[0], windows[1])
        drift = _regime_drift(windows[0], windows[1])
    else:
        trends, drift = [], []

    basis = _confidence_basis(windows)
    summary = _compose_summary(windows, trends, drift)
    available = any(w["size"] > 0 for w in windows)

    return {
        "available":         available,
        "anchor_date":       anchor.isoformat(),
        "windows":           windows,
        "theme_trends":      trends,
        "regime_drift":      drift,
        "confidence_basis":  basis,
        "summary":           summary,
    }
