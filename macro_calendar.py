"""
macro_calendar.py

Static macro release calendar for key US economic data releases.
Surfaces upcoming and recent scheduled catalysts as a separate tracked stream
alongside news clusters in the /news response.

Indicators covered:
  CPI         — BLS Consumer Price Index (mid-month)
  PPI         — BLS Producer Price Index (1-2 days before CPI)
  NFP         — BLS Employment Situation: Nonfarm Payrolls (first Friday)
  Unemployment — BLS Employment Situation: Unemployment Rate (same release as NFP)
  PCE         — BEA Personal Income and Outlays (last week of month)

NOTE: Dates below are sourced from published BLS/BEA annual schedules and are
approximate for future months. Verify and update at the start of each calendar
year from:
  https://www.bls.gov/schedule/
  https://www.bea.gov/news/schedule
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, Optional

MacroStatus = Literal["upcoming", "today", "recent", "past"]

# ---------------------------------------------------------------------------
# Static release calendar
# Each entry: (indicator_name, release_date_iso, period_label)
# ---------------------------------------------------------------------------

_RELEASES: list[tuple[str, str, str]] = [
    # ── CPI (Consumer Price Index) ──────────────────────────────────────────
    ("CPI", "2025-01-15", "Dec 2024"),
    ("CPI", "2025-02-12", "Jan 2025"),
    ("CPI", "2025-03-12", "Feb 2025"),
    ("CPI", "2025-04-10", "Mar 2025"),
    ("CPI", "2025-05-13", "Apr 2025"),
    ("CPI", "2025-06-11", "May 2025"),
    ("CPI", "2025-07-11", "Jun 2025"),
    ("CPI", "2025-08-12", "Jul 2025"),
    ("CPI", "2025-09-10", "Aug 2025"),
    ("CPI", "2025-10-15", "Sep 2025"),
    ("CPI", "2025-11-13", "Oct 2025"),
    ("CPI", "2025-12-10", "Nov 2025"),
    ("CPI", "2026-01-14", "Dec 2025"),
    ("CPI", "2026-02-11", "Jan 2026"),
    ("CPI", "2026-03-11", "Feb 2026"),
    ("CPI", "2026-04-10", "Mar 2026"),
    ("CPI", "2026-05-13", "Apr 2026"),
    ("CPI", "2026-06-10", "May 2026"),
    ("CPI", "2026-07-15", "Jun 2026"),
    ("CPI", "2026-08-12", "Jul 2026"),
    ("CPI", "2026-09-09", "Aug 2026"),
    ("CPI", "2026-10-14", "Sep 2026"),
    ("CPI", "2026-11-11", "Oct 2026"),
    ("CPI", "2026-12-09", "Nov 2026"),

    # ── PPI (Producer Price Index) ──────────────────────────────────────────
    ("PPI", "2025-01-14", "Dec 2024"),
    ("PPI", "2025-02-13", "Jan 2025"),
    ("PPI", "2025-03-13", "Feb 2025"),
    ("PPI", "2025-04-11", "Mar 2025"),
    ("PPI", "2025-05-14", "Apr 2025"),
    ("PPI", "2025-06-12", "May 2025"),
    ("PPI", "2025-07-12", "Jun 2025"),
    ("PPI", "2025-08-13", "Jul 2025"),
    ("PPI", "2025-09-11", "Aug 2025"),
    ("PPI", "2025-10-14", "Sep 2025"),
    ("PPI", "2025-11-14", "Oct 2025"),
    ("PPI", "2025-12-11", "Nov 2025"),
    ("PPI", "2026-01-15", "Dec 2025"),
    ("PPI", "2026-02-12", "Jan 2026"),
    ("PPI", "2026-03-12", "Feb 2026"),
    ("PPI", "2026-04-09", "Mar 2026"),
    ("PPI", "2026-05-12", "Apr 2026"),
    ("PPI", "2026-06-11", "May 2026"),
    ("PPI", "2026-07-14", "Jun 2026"),
    ("PPI", "2026-08-13", "Jul 2026"),
    ("PPI", "2026-09-10", "Aug 2026"),
    ("PPI", "2026-10-13", "Sep 2026"),
    ("PPI", "2026-11-12", "Oct 2026"),
    ("PPI", "2026-12-10", "Nov 2026"),

    # ── NFP (Employment Situation — Nonfarm Payrolls) ───────────────────────
    # Same release as Unemployment Rate. First Friday of each month.
    ("NFP", "2025-01-10", "Dec 2024"),
    ("NFP", "2025-02-07", "Jan 2025"),
    ("NFP", "2025-03-07", "Feb 2025"),
    ("NFP", "2025-04-04", "Mar 2025"),
    ("NFP", "2025-05-02", "Apr 2025"),
    ("NFP", "2025-06-06", "May 2025"),
    ("NFP", "2025-07-03", "Jun 2025"),
    ("NFP", "2025-08-01", "Jul 2025"),
    ("NFP", "2025-09-05", "Aug 2025"),
    ("NFP", "2025-10-03", "Sep 2025"),
    ("NFP", "2025-11-07", "Oct 2025"),
    ("NFP", "2025-12-05", "Nov 2025"),
    ("NFP", "2026-01-09", "Dec 2025"),
    ("NFP", "2026-02-06", "Jan 2026"),
    ("NFP", "2026-03-06", "Feb 2026"),
    ("NFP", "2026-04-03", "Mar 2026"),
    ("NFP", "2026-05-01", "Apr 2026"),
    ("NFP", "2026-06-05", "May 2026"),
    ("NFP", "2026-07-10", "Jun 2026"),  # shifted: Jul 3 too close to July 4
    ("NFP", "2026-08-07", "Jul 2026"),
    ("NFP", "2026-09-04", "Aug 2026"),
    ("NFP", "2026-10-02", "Sep 2026"),
    ("NFP", "2026-11-06", "Oct 2026"),
    ("NFP", "2026-12-04", "Nov 2026"),

    # ── Unemployment Rate (same BLS release as NFP) ─────────────────────────
    ("Unemployment", "2025-01-10", "Dec 2024"),
    ("Unemployment", "2025-02-07", "Jan 2025"),
    ("Unemployment", "2025-03-07", "Feb 2025"),
    ("Unemployment", "2025-04-04", "Mar 2025"),
    ("Unemployment", "2025-05-02", "Apr 2025"),
    ("Unemployment", "2025-06-06", "May 2025"),
    ("Unemployment", "2025-07-03", "Jun 2025"),
    ("Unemployment", "2025-08-01", "Jul 2025"),
    ("Unemployment", "2025-09-05", "Aug 2025"),
    ("Unemployment", "2025-10-03", "Sep 2025"),
    ("Unemployment", "2025-11-07", "Oct 2025"),
    ("Unemployment", "2025-12-05", "Nov 2025"),
    ("Unemployment", "2026-01-09", "Dec 2025"),
    ("Unemployment", "2026-02-06", "Jan 2026"),
    ("Unemployment", "2026-03-06", "Feb 2026"),
    ("Unemployment", "2026-04-03", "Mar 2026"),
    ("Unemployment", "2026-05-01", "Apr 2026"),
    ("Unemployment", "2026-06-05", "May 2026"),
    ("Unemployment", "2026-07-10", "Jun 2026"),
    ("Unemployment", "2026-08-07", "Jul 2026"),
    ("Unemployment", "2026-09-04", "Aug 2026"),
    ("Unemployment", "2026-10-02", "Sep 2026"),
    ("Unemployment", "2026-11-06", "Oct 2026"),
    ("Unemployment", "2026-12-04", "Nov 2026"),

    # ── PCE (BEA Personal Income and Outlays) ───────────────────────────────
    # Typically released last Friday or close to it, ~4-5 weeks after reference period.
    ("PCE", "2025-01-31", "Dec 2024"),
    ("PCE", "2025-02-28", "Jan 2025"),
    ("PCE", "2025-03-28", "Feb 2025"),
    ("PCE", "2025-04-30", "Mar 2025"),
    ("PCE", "2025-05-30", "Apr 2025"),
    ("PCE", "2025-06-27", "May 2025"),
    ("PCE", "2025-07-31", "Jun 2025"),
    ("PCE", "2025-08-29", "Jul 2025"),
    ("PCE", "2025-09-26", "Aug 2025"),
    ("PCE", "2025-10-31", "Sep 2025"),
    ("PCE", "2025-11-26", "Oct 2025"),
    ("PCE", "2025-12-19", "Nov 2025"),
    ("PCE", "2026-01-30", "Dec 2025"),
    ("PCE", "2026-02-27", "Jan 2026"),
    ("PCE", "2026-03-27", "Feb 2026"),
    ("PCE", "2026-04-30", "Mar 2026"),
    ("PCE", "2026-05-29", "Apr 2026"),
    ("PCE", "2026-06-26", "May 2026"),
    ("PCE", "2026-07-31", "Jun 2026"),
    ("PCE", "2026-08-28", "Jul 2026"),
    ("PCE", "2026-09-25", "Aug 2026"),
    ("PCE", "2026-10-30", "Sep 2026"),
    ("PCE", "2026-11-20", "Oct 2026"),  # shifted: Thanksgiving proximity
    ("PCE", "2026-12-18", "Nov 2026"),
]


def get_macro_releases(
    today: Optional[date] = None,
    days_before: int = 5,
    days_after: int = 45,
) -> list[dict]:
    """Return macro release entries within [today - days_before, today + days_after].

    Each returned dict:
      name           — indicator name ("CPI", "PPI", "NFP", "Unemployment", "PCE")
      release_date   — ISO date string ("YYYY-MM-DD")
      period         — human label for the measured period ("Mar 2026")
      status         — "upcoming" | "today" | "recent" | "past"
      days_until     — integer days from today (negative = past)
      release_key    — stable join key against ``macro_release_facts``
      actual         — official released value (None when unstored)
      prior          — official prior value     (None when unstored)
      revised_prior  — official revised prior  (None when unstored)
      consensus      — pre-release consensus    (None when unstored)
      release_facts_source — provenance label, "" when no row stored
      has_release_facts    — bool — True when a row exists in the cache

    The fact fields are always present in the output (None / "" / False
    when the cache has nothing for the row) so consumers can rely on a
    stable shape regardless of whether a feed has populated the store.
    The store lookup is best-effort; any backend error degrades to "no
    facts present" without raising, so the calendar keeps rendering on
    a missing or unmigrated DB.

    status thresholds:
      today    — days_until == 0
      upcoming — days_until > 0
      recent   — -2 <= days_until < 0  (released 1–2 days ago)
      past     — days_until < -2        (still within the window; callers may filter)
    """
    if today is None:
        today = date.today()

    cutoff_past = today - timedelta(days=days_before)
    cutoff_future = today + timedelta(days=days_after)

    results: list[dict] = []
    for name, release_date_iso, period in _RELEASES:
        release_date = date.fromisoformat(release_date_iso)
        if release_date < cutoff_past or release_date > cutoff_future:
            continue
        days_until = (release_date - today).days
        if days_until > 0:
            status: MacroStatus = "upcoming"
        elif days_until == 0:
            status = "today"
        elif days_until >= -2:
            status = "recent"
        else:
            status = "past"
        results.append({
            "name": name,
            "release_date": release_date_iso,
            "period": period,
            "status": status,
            "days_until": days_until,
            "release_key": f"{name}:{release_date_iso}",
            "release_time": None,
            "actual": None,
            "prior": None,
            "revised_prior": None,
            "consensus": None,
            "release_facts_source": "",
            "has_release_facts": False,
        })

    results.sort(key=lambda r: (r["release_date"], r["name"]))
    _attach_release_facts(results)
    return results


def _attach_release_facts(rows: list[dict]) -> None:
    """Fill ``actual / prior / revised_prior / consensus / source`` on
    rows whose ``release_key`` has a corresponding cached fact.

    Best-effort: a missing table or any other backend error leaves the
    pre-populated default-None shape on every row.  Imported lazily so
    a fresh calendar lookup never pulls SQLite for nothing.
    """
    if not rows:
        return
    try:
        from macro_release_facts import get_release_facts_map
        facts = get_release_facts_map([r["release_key"] for r in rows])
    except Exception:
        return
    if not facts:
        return
    for row in rows:
        fact = facts.get(row["release_key"])
        if fact is None:
            continue
        row["release_time"] = fact.get("release_time")
        row["actual"] = fact.get("actual")
        row["prior"] = fact.get("prior")
        row["revised_prior"] = fact.get("revised_prior")
        row["consensus"] = fact.get("consensus")
        row["release_facts_source"] = fact.get("source") or ""
        row["has_release_facts"] = True
