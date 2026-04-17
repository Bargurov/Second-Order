"""
policy_tracker.py

Static registry of tracked regulatory and trade-policy items.

Each item carries:
  name             — short human label
  policy_type      — "tariff" | "sanction" | "regulation" | "executive_order" | "rate_decision"
  jurisdiction     — "US" | "EU" | "US/China" | "Global" | …
  effective_date   — ISO date; when the policy takes effect
  announcement_date — ISO date; when the policy was announced/published
  revisit_date     — ISO date; suggested monitoring checkpoint
  description      — one-line context note
  status           — derived: "announced" | "pre_effective" | "active" | "revisit_due" | "past"
  days_until         — days until effective_date (negative = already in effect)
  days_until_revisit — days until revisit_date (negative = past due)

Display window:
  get_policy_items() returns items where effective_date is within
  days_before days in the past, or revisit_date is within days_after
  days in the future.  Fully past items (revisit_date > PAST_GRACE_DAYS
  ago) are excluded.
"""

from datetime import date, timedelta
from typing import Literal, Optional

PolicyStatus = Literal["announced", "pre_effective", "active", "revisit_due", "past"]
PolicyType   = Literal["tariff", "sanction", "regulation", "executive_order", "rate_decision"]

# Mark "revisit_due" when the revisit date is this many days away or fewer.
_REVISIT_WARN_DAYS = 14

# Suppress items whose revisit date is more than this many days in the past.
_PAST_GRACE_DAYS = 30

# Pre-effective window: mark "pre_effective" when effective date is within this many days.
# Threshold is policy-type-specific — rate decisions move fast; regulations give more lead time.
_PRE_EFFECTIVE_DAYS: dict[str, int] = {
    "rate_decision":   3,
    "tariff":          7,
    "sanction":        7,
    "executive_order": 7,
    "regulation":     30,
}

# ---------------------------------------------------------------------------
# Canonical registry
# (name, policy_type, jurisdiction, effective_date, announcement_date, revisit_date, description)
# Dates are approximate and based on published policy schedules; verify annually.
# ---------------------------------------------------------------------------

_ITEMS: list[tuple[str, str, str, str, str, str, str]] = [
    # ── US Trade / Tariffs ──────────────────────────────────────────────────
    (
        "US Reciprocal Tariffs — 10% Baseline",
        "tariff", "US",
        "2026-04-05", "2026-04-02", "2026-07-04",
        "Universal 10% tariff floor on most trading partners; 90-day review window",
    ),
    (
        "US-China Tariffs — 145%",
        "tariff", "US/China",
        "2026-04-09", "2026-04-07", "2026-07-09",
        "Escalated to 145% on Chinese imports after tit-for-tat retaliation",
    ),
    (
        "EU Retaliatory Tariffs on US Goods",
        "tariff", "EU",
        "2026-04-15", "2026-04-09", "2026-07-15",
        "EU counter-measures on selected US exports; 90-day sunset review",
    ),
    (
        "USTR Section 301 — China Tech Review",
        "executive_order", "US",
        "2025-12-01", "2025-09-01", "2026-06-01",
        "180-day statutory review of Section 301 tariff rates on Chinese technology",
    ),
    # ── Central bank rate decisions ──────────────────────────────────────────
    (
        "ECB Rate Decision",
        "rate_decision", "EU",
        "2026-04-17", "2026-03-06", "2026-06-05",
        "Governing council rate decision; next scheduled meeting 5 June 2026",
    ),
    (
        "Fed FOMC Decision",
        "rate_decision", "US",
        "2026-05-07", "2026-03-19", "2026-06-18",
        "Federal Open Market Committee rate decision; next meeting 17-18 June 2026",
    ),
    # ── Sanctions ───────────────────────────────────────────────────────────
    (
        "OFAC Russia Sanctions — Energy Expansion",
        "sanction", "US",
        "2026-01-15", "2026-01-10", "2026-07-15",
        "Expanded SDN designations covering Russian energy-sector entities",
    ),
    # ── Regulation ──────────────────────────────────────────────────────────
    (
        "EU Carbon Border Adjustment (CBAM)",
        "regulation", "EU",
        "2026-01-01", "2023-05-16", "2026-10-01",
        "Full reporting obligations in force; transitional phase ends Q4 review",
    ),
    (
        "US AI / Chip Export Controls (BIS)",
        "regulation", "US",
        "2025-10-01", "2025-07-01", "2026-10-01",
        "BIS controls on advanced AI/HPC semiconductor exports to restricted entities",
    ),
    (
        "Basel III Endgame — US Implementation",
        "regulation", "US",
        "2026-07-01", "2026-03-15", "2027-01-01",
        "US bank capital and liquidity rule compliance deadline",
    ),
    (
        "EU AI Act — High-Risk System Requirements",
        "regulation", "EU",
        "2026-08-02", "2024-05-21", "2027-02-02",
        "Compliance deadline for EU AI Act high-risk system obligations",
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_policy_items(
    today: Optional[date] = None,
    days_before: int = 90,
    days_after: int = 120,
) -> list[dict]:
    """Return policy items active or upcoming within the display window.

    Parameters
    ----------
    today:
        Reference date.  Defaults to ``date.today()``.
    days_before:
        Include items whose *effective_date* is at most this many days in the
        past (prevents showing ancient policy history).
    days_after:
        Include items whose *effective_date* is at most this many days ahead.

    Returns
    -------
    List of dicts, sorted by effective_date then name.  Items whose
    revisit_date is more than ``_PAST_GRACE_DAYS`` in the past are excluded.
    """
    if today is None:
        today = date.today()

    cutoff_effective_past   = today - timedelta(days=days_before)
    cutoff_effective_future = today + timedelta(days=days_after)
    cutoff_past_revisit     = today - timedelta(days=_PAST_GRACE_DAYS)

    results: list[dict] = []

    for name, policy_type, jurisdiction, eff_iso, ann_iso, rev_iso, description in _ITEMS:
        effective_date = date.fromisoformat(eff_iso)
        revisit_date   = date.fromisoformat(rev_iso)

        # Exclude items that are entirely in the past (revisit long over)
        if revisit_date < cutoff_past_revisit:
            continue

        # Exclude items too far in the future to be actionable
        if effective_date > cutoff_effective_future:
            continue

        # Exclude items whose effective date is ancient and revisit is near
        # (edge case: effective far in the past but revisit still in range)
        if effective_date < cutoff_effective_past and revisit_date < cutoff_past_revisit:
            continue

        days_until         = (effective_date - today).days
        days_until_revisit = (revisit_date   - today).days

        # Derive status
        pre_eff_threshold = _PRE_EFFECTIVE_DAYS.get(policy_type, 7)

        if days_until > pre_eff_threshold:
            status: PolicyStatus = "announced"
        elif days_until > 0:
            status = "pre_effective"
        elif days_until_revisit > _REVISIT_WARN_DAYS:
            status = "active"
        elif days_until_revisit < 0 and abs(days_until_revisit) > _PAST_GRACE_DAYS:
            status = "past"  # will be filtered out
        else:
            status = "revisit_due"

        results.append({
            "name":               name,
            "policy_type":        policy_type,
            "jurisdiction":       jurisdiction,
            "effective_date":     eff_iso,
            "announcement_date":  ann_iso,
            "revisit_date":       rev_iso,
            "description":        description,
            "status":             status,
            "days_until":         days_until,
            "days_until_revisit": days_until_revisit,
        })

    results.sort(key=lambda r: (r["effective_date"], r["name"]))
    return results
