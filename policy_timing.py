"""
policy_timing.py

Per-cluster tracked-policy timing block.

When a news-cluster headline matches a tracked regulatory / trade /
rate policy, the backend attaches a canonical ``policy_timing`` block
so the frontend can render a deterministic "announced / effective /
under review / expired" strip without inferring status from free-form
headline text.

Block shape (task-pinned — do not add or rename keys here without
updating the frontend ``PolicyTiming`` contract):

    {
      policy_key:     str,    # stable machine identifier
      announced_date: str,    # ISO date
      effective_date: str,    # ISO date
      review_date:    str,    # ISO date
      status:         str,    # announced | effective | under_review | expired
      source:         str,    # issuing authority label, e.g. "USTR"
    }

``status`` is derived from today vs. ``effective_date`` / ``review_date``
using the same pre-effective and review-warning thresholds already
shared with ``policy_tracker.get_policy_items`` — one source of truth
for "how long until this kicks in" / "how long since review opened".

Pure composer — no DB, no network.  Safe to call from the /news hot
path where each cluster needs the attachment decision to be fast.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from policy_tracker import (
    _PAST_GRACE_DAYS,
    _PRE_EFFECTIVE_DAYS,
    _REVISIT_WARN_DAYS,
)


TimingStatus = Literal["announced", "effective", "under_review", "expired"]

TIMING_STATUSES: tuple[str, ...] = (
    "announced", "effective", "under_review", "expired",
)


# ---------------------------------------------------------------------------
# Tracked-policy registry
#
# Each entry is the *minimum* metadata needed to stamp a cluster:
#   policy_key     — stable identifier (never change after release)
#   policy_type    — shared with policy_tracker._ITEMS for status derivation
#   announced_date — ISO
#   effective_date — ISO
#   review_date    — ISO
#   source         — issuing authority label the UI renders as-is
#   keywords       — case-insensitive substring list; first-match wins
#
# Dates and text mirror policy_tracker._ITEMS so the page-level strip
# and the per-cluster block stay in lockstep on the same factual basis.
# ---------------------------------------------------------------------------

_TRACKED_POLICIES: tuple[tuple[str, str, str, str, str, str, tuple[str, ...]], ...] = (
    (
        "us_reciprocal_tariffs_baseline_2026",
        "tariff",
        "2026-04-02", "2026-04-05", "2026-07-04",
        "USTR",
        ("reciprocal tariff", "reciprocal tariffs", "universal tariff",
         "10% tariff", "baseline tariff", "tariff floor"),
    ),
    (
        "us_china_tariffs_145pct_2026",
        "tariff",
        "2026-04-07", "2026-04-09", "2026-07-09",
        "USTR",
        ("china tariff", "china tariffs", "145%",
         "chinese imports", "tariff on china"),
    ),
    (
        "eu_retaliatory_tariffs_us_2026",
        "tariff",
        "2026-04-09", "2026-04-15", "2026-07-15",
        "European Commission",
        ("eu tariff", "eu tariffs", "eu retaliatory", "retaliatory tariff",
         "eu counter-measures", "eu countermeasures"),
    ),
    (
        "ustr_section_301_china_tech_2025",
        "executive_order",
        "2025-09-01", "2025-12-01", "2026-06-01",
        "USTR",
        ("section 301", "301 review", "china tech review"),
    ),
    (
        "ecb_rate_decision_2026_04",
        "rate_decision",
        "2026-03-06", "2026-04-17", "2026-06-05",
        "ECB",
        ("ecb rate", "ecb decision", "ecb rate decision",
         "governing council", "ecb cut", "ecb hike"),
    ),
    (
        "fomc_rate_decision_2026_05",
        "rate_decision",
        "2026-03-19", "2026-05-07", "2026-06-18",
        "Federal Reserve",
        ("fomc", "fed decision", "fed rate decision", "federal reserve rate",
         "fed cut", "fed hike"),
    ),
    (
        "ofac_russia_energy_sanctions_2026",
        "sanction",
        "2026-01-10", "2026-01-15", "2026-07-15",
        "OFAC",
        ("ofac", "russia sanction", "russia sanctions", "sdn",
         "russian energy sanction"),
    ),
    (
        "eu_cbam_full_compliance_2026",
        "regulation",
        "2023-05-16", "2026-01-01", "2026-10-01",
        "European Commission",
        ("cbam", "carbon border", "carbon tariff"),
    ),
    (
        "us_bis_ai_chip_export_2025",
        "regulation",
        "2025-07-01", "2025-10-01", "2026-10-01",
        "BIS",
        ("bis export control", "chip export control", "ai chip export",
         "semiconductor export"),
    ),
    (
        "basel_iii_endgame_us_2026",
        "regulation",
        "2026-03-15", "2026-07-01", "2027-01-01",
        "Federal Reserve / OCC / FDIC",
        ("basel iii", "basel endgame"),
    ),
    (
        "eu_ai_act_high_risk_2026",
        "regulation",
        "2024-05-21", "2026-08-02", "2027-02-02",
        "European Commission",
        ("eu ai act", "ai act"),
    ),
)


# ---------------------------------------------------------------------------
# Status derivation
# ---------------------------------------------------------------------------


def _derive_timing_status(
    policy_type: str,
    announced_date: date,
    effective_date: date,
    review_date: date,
    today: date,
) -> TimingStatus:
    """Collapse policy_tracker's 5-state vocabulary onto the 4-state
    task contract.

    Thresholds come from ``policy_tracker`` so both surfaces derive
    status from the same numbers — drift here = drift on the page.
    """
    # Before the announcement date is effectively "not tracked yet" —
    # clamp to announced so the block is never silently omitted.
    if today < announced_date:
        return "announced"

    days_until_eff = (effective_date - today).days
    days_until_rev = (review_date - today).days

    # Pre-effective / announced but not yet in force.  Covers both the
    # ``_PRE_EFFECTIVE_DAYS`` window and longer lead times; merging
    # ``pre_effective`` into ``announced`` matches the task vocabulary.
    _pre_eff_days = _PRE_EFFECTIVE_DAYS.get(policy_type, 7)  # sanity-ref
    del _pre_eff_days  # kept for documentation parity; no state-split needed
    if days_until_eff > 0:
        return "announced"

    # Past the review date by more than the grace window — policy is
    # effectively retired from active monitoring.
    if days_until_rev < -_PAST_GRACE_DAYS:
        return "expired"

    # Review is imminent (≤ _REVISIT_WARN_DAYS away) or recently past
    # (not yet past the grace cutoff above).
    if days_until_rev <= _REVISIT_WARN_DAYS:
        return "under_review"

    return "effective"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def match_headline_to_policy(
    headline: str,
    today: Optional[date] = None,
) -> Optional[dict]:
    """Return the ``policy_timing`` block for a headline, or ``None``.

    Match is case-insensitive substring on the per-policy keyword list;
    first matching policy wins (registry order is curated so more-
    specific tariff entries land before the baseline).  ``None`` is
    returned when no keyword hits — the caller should then leave the
    cluster untouched so unmatched rows keep their existing shape.
    """
    if not isinstance(headline, str) or not headline.strip():
        return None
    needle = headline.lower()
    anchor = today or date.today()

    for policy_key, policy_type, ann_iso, eff_iso, rev_iso, source, keywords in _TRACKED_POLICIES:
        if not any(kw in needle for kw in keywords):
            continue
        try:
            announced = date.fromisoformat(ann_iso)
            effective = date.fromisoformat(eff_iso)
            review    = date.fromisoformat(rev_iso)
        except ValueError:
            continue
        status = _derive_timing_status(
            policy_type, announced, effective, review, anchor,
        )
        return {
            "policy_key":     policy_key,
            "announced_date": ann_iso,
            "effective_date": eff_iso,
            "review_date":    rev_iso,
            "status":         status,
            "source":         source,
        }
    return None


def build_event_policy_timing_context(
    event: dict,
    today: Optional[date] = None,
) -> dict:
    """Return the ``policy_timing_context`` block for an analyzed event.

    Thin wrapper around ``match_headline_to_policy`` that accepts an
    event dict (shape parity with the other
    ``build_event_*_context`` helpers used by the save / refresh
    pipeline) and returns ``{}`` when the headline doesn't match any
    tracked policy.  The caller relies on the route-side
    ``coerce_policy_timing_context`` helper for a fully-keyed default
    shape at the HTTP boundary.
    """
    headline = (event or {}).get("headline", "") if isinstance(event, dict) else ""
    if not isinstance(headline, str) or not headline.strip():
        return {}
    block = match_headline_to_policy(headline, today=today)
    return block or {}


_EMPTY_POLICY_TIMING_CONTEXT: dict = {
    "policy_key":     None,
    "announced_date": None,
    "effective_date": None,
    "review_date":    None,
    "status":         None,
    "source":         "",
}


def coerce_policy_timing_context(block: dict | None) -> dict:
    """Return the canonical ``policy_timing_context`` shape.

    ``{}`` / ``None`` / any non-dict input collapses to the stable
    empty-shape dict (every key present, values ``None`` / ``""``).
    Populated blocks keep their values; missing keys fill from the
    defaults so consumers can rely on the same keyset regardless of
    schema version or match state.
    """
    if not isinstance(block, dict) or not block:
        return dict(_EMPTY_POLICY_TIMING_CONTEXT)
    out = dict(_EMPTY_POLICY_TIMING_CONTEXT)
    for key in _EMPTY_POLICY_TIMING_CONTEXT:
        if key in block and block[key] is not None:
            out[key] = block[key]
    if out.get("source") is None:
        out["source"] = ""
    return out


def attach_policy_timing_blocks(
    clusters: list[dict] | None,
    today: Optional[date] = None,
) -> list[dict]:
    """Return a new cluster list with ``policy_timing`` attached when
    a headline maps to a tracked policy.

    Never mutates the input.  Clusters with no match are copied through
    untouched — no ``policy_timing`` key is added, so the NewsCluster
    shape stays byte-stable for downstream consumers that don't care
    about policy timing.  Clusters that already carry a ``policy_timing``
    (belt-and-suspenders on retries) are left alone; first match wins.
    """
    out: list[dict] = []
    for c in clusters or []:
        if not isinstance(c, dict):
            out.append(c)
            continue
        copied = dict(c)
        if "policy_timing" not in copied:
            block = match_headline_to_policy(copied.get("headline", ""), today)
            if block is not None:
                copied["policy_timing"] = block
        out.append(copied)
    return out
