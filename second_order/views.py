"""Shared pieces of prepared Dossier views: the scorer's reference distribution and the chart series."""
from datetime import datetime
import numpy as np
from .data import DAILY_DATE_CONVENTION, Series, ny_date
from .registry import resolve
from .scoring import rank_counts

CHART_BEFORE = 60  # Observations shown before the event anchor.
CHART_AFTER = 10  # Observations shown after the horizon end, within the evaluation clock.
HISTOGRAM_BINS = 24
QUOTE_UNITS = {"yield_bp": "yield, %", "return_pct": "level", "market_model": "adjusted price"}


def reference_view(values: tuple[float, ...], result: dict) -> dict:
    """The exact reference moves the scorer ranked against, with counts and display bins."""
    signed = result["signed_move"]
    below, equal, above = rank_counts(signed, list(values))
    if len(values) != result["reference_windows"] or (below + 0.5 * equal) / len(values) != result["percentile_rank"]:
        raise ValueError("Prepared reference does not reproduce the recorded rank")
    counts, edges = np.histogram(values, bins=HISTOGRAM_BINS, range=(min(*values, signed), max(*values, signed)))
    return {"values": list(values), "event_signed_move": signed, "below": below, "equal": equal, "above": above,
            "histogram": {"edges": [float(edge) for edge in edges], "counts": [int(count) for count in counts]}}


def series_view(series: Series, result: dict, label: str, provenance: dict | None, as_of: datetime,
                caption: str | None = None, attribution: str | None = None) -> dict | None:
    """Observations around the event. Date-only series are labelled by New York date, never by a time."""
    times = [point.at.isoformat() for point in series.observations]
    event = times.index(result["event_anchor"]) if result.get("event_anchor") in times else None
    if event is None:
        return None
    last = max(i for i, point in enumerate(series.observations) if point.at <= as_of)
    shown_until = next((times.index(result[key]) for key in ("target_at", "score_anchor") if result.get(key) in times),
                       event)
    start, end = max(0, event - CHART_BEFORE), min(last, shown_until + CHART_AFTER)
    daily = series.timestamp_basis == DAILY_DATE_CONVENTION
    stamp = (lambda i: ny_date(series.observations[i].at).isoformat()) if daily else (lambda i: times[i])
    if caption is None and provenance is not None:
        caption = (f"{provenance['provider']} · {provenance['ticker']} · {provenance['price_basis']} values · "
                   f"invented by {provenance['version']}")
    return {"label": label, "quote_unit": QUOTE_UNITS[resolve(series.observable_id).measurement],
            "time_basis": "daily_date" if daily else "timestamp",
            "points": [[stamp(i), series.observations[i].value] for i in range(start, end + 1)],
            "provenance": provenance, "caption": caption, "attribution": attribution}
