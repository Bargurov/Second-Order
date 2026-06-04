"""
cross_event_studies.py

Archive-native cross-event correlation studies.

Why this module
---------------
``track_record_breakdown`` answers "how well has each family / regime
performed over the archive?".  This module answers the questions one
level up — *across* events rather than *within* a family bucket:

  * Which mechanism families cluster in time?
  * Which sector exposures co-appear across events?
  * Which transmission-path shapes recur?
  * Which family × sector combinations tend to persist or fail together?

Pure composer.  Takes already-loaded event rows in the same shape
``track_record_breakdown`` consumes (the caller runs one query; both
composers share the read).  No DB access, no external I/O.

Design choices
--------------
  * Co-occurrence window is **baked at 7 days**.  Not a parameter.
    Extending the window multiplies the false-positive pair count; a
    user who needs a different window runs a different study.
  * ``transmission_path_clusters`` uses **channel-only signatures**
    (actors dropped).  Raw `(actor, channel)` tuples have cardinality
    close to event count — clustering them yields N=1 buckets.
    Channel sequences are bounded by the enum and actually repeat.
  * **No overlap with ``track_record_breakdown``.**  This module does
    NOT emit per-family hit rates — that's the breakdown's job.  It
    only emits cross-cuts the breakdown doesn't cover (family × sector,
    co-occurrence, path shape).
  * Country / geography is **not** surfaced — the archive has no
    reliable structured country field.  Could be added once
    ``event_context.geography`` is populated.  Deferred.

Output discipline
-----------------
  * Every list is capped at a top-N so long-tail noise doesn't leak
    into research outputs.
  * A minimum-count threshold filters singletons — a single occurrence
    is not a cluster.
  * Every row carries ``event_ids`` (top 5 representative) so the
    caller can drill into the underlying events.
  * Empty archive returns a shaped empty block, not ``{}`` — UI consumers
    don't need a membership check.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

_COOCCURRENCE_WINDOW_DAYS: int = 7

# Caps for the top-N lists.  Keeps research outputs compact; long-tail
# correlations are rarely interpretable.
_TOP_N_COOCCURRENCE_PAIRS: int = 12
_TOP_N_SECTOR_PAIRS:       int = 12
_TOP_N_PATH_CLUSTERS:      int = 8
_TOP_N_COMBINATIONS:       int = 12

# Minimum count thresholds — single occurrences are not clusters.
_MIN_PAIR_COUNT:    int = 2
_MIN_CLUSTER_COUNT: int = 2
_MIN_COMBO_COUNT:   int = 3  # outcome stats need a floor to be meaningful

# How many representative event IDs to attach per cluster for drill-in.
_MAX_EVENT_IDS_PER_ROW: int = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _loads(raw: Any, default: Any) -> Any:
    """JSON-decode a string payload or pass through a decoded value."""
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return default
    return default


def _parse_event_date(raw: Any) -> Optional[datetime]:
    """Accept ISO-like date strings or datetime objects; None on failure."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    # Accept "YYYY-MM-DD" or full ISO timestamps.
    try:
        if "T" in s or " " in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _score_outcome(event: dict) -> str:
    """Re-use the canonical outcome scoring from track_record_breakdown."""
    from track_record_breakdown import _score_event as _score
    market_tickers = _loads(event.get("market_tickers"), [])
    revisit_snaps  = _loads(event.get("revisit_snapshots"), [])
    if not isinstance(market_tickers, list):
        market_tickers = []
    if not isinstance(revisit_snaps, list):
        revisit_snaps = []
    scored = _score(market_tickers, revisit_snaps)
    return scored["outcome"]


def _event_tickers(event: dict, key: str) -> list[str]:
    """Extract a list of upper-cased ticker symbols from the event."""
    raw = _loads(event.get(key), [])
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            s = item.strip().upper()
            if s:
                out.append(s)
    return out


# ---------------------------------------------------------------------------
# Sector mapping — reuse the single source of truth
# ---------------------------------------------------------------------------

def _ticker_sector(symbol: str) -> Optional[str]:
    """Return a canonical sector label for ``symbol``, or None.

    Leans on ``asset_selection._ticker_channel`` for ETF → channel
    bucketing, then maps channel back to a sector label.  Single-name
    tickers (no channel mapping) drop out of the sector studies —
    better to lose a row than invent an "unknown" bucket.
    """
    from asset_selection import _ticker_channel

    channel = _ticker_channel(symbol)
    if channel is None:
        return None
    # Channel-to-sector surface mapping.  Kept narrow — these are the
    # labels that appear in scenario_packs.sector_consequences so the
    # cross-event studies speak the same vocabulary.
    return {
        "commodities": "commodities",
        "rates":       "rates",
        "credit":      "credit",
        "fx":          "fx",
        "equities":    "equities",
        "vol":         "vol",
    }.get(channel)


def _event_sectors(event: dict) -> set[str]:
    """Union the sectors implied by an event's beneficiary + loser tickers."""
    sectors: set[str] = set()
    for key in ("beneficiary_tickers", "loser_tickers"):
        for sym in _event_tickers(event, key):
            sec = _ticker_sector(sym)
            if sec is not None:
                sectors.add(sec)
    return sectors


# ---------------------------------------------------------------------------
# Transmission-path signature
# ---------------------------------------------------------------------------

def _path_signature(event: dict) -> Optional[tuple[str, ...]]:
    """Reduce an event's transmission_path to a channel-only signature.

    Drops actors deliberately — raw (actor, channel) pairs have cardinality
    close to event count and cluster into singletons.  Channel sequences
    are bounded by the enum (~10 values) and actually repeat across
    events.  Returns None when the path is empty or unparseable.
    """
    raw = _loads(event.get("transmission_path"), [])
    if not isinstance(raw, list):
        return None
    channels: list[str] = []
    for hop in raw:
        if not isinstance(hop, dict):
            continue
        ch = hop.get("channel")
        if isinstance(ch, str) and ch.strip():
            channels.append(ch.strip().lower())
    if len(channels) < 2:
        return None
    return tuple(channels)


# ---------------------------------------------------------------------------
# Study 1: family co-occurrence in a 7-day window
# ---------------------------------------------------------------------------

def _compute_family_cooccurrence(events: list[dict]) -> list[dict]:
    """Pairs of mechanism families that appear within the bake-in window.

    Two-pointer sweep over events sorted by date; O(n²) worst case but
    bounded by the window so typically linear.
    """
    rows: list[tuple[datetime, str, Any]] = []
    for ev in events:
        dt = _parse_event_date(ev.get("event_date"))
        fam = (ev.get("mechanism_family") or "").strip()
        if dt is None or not fam or fam == "none":
            continue
        rows.append((dt, fam, ev.get("id")))
    rows.sort(key=lambda r: r[0])

    window = timedelta(days=_COOCCURRENCE_WINDOW_DAYS)
    counter: Counter[tuple[str, str]] = Counter()
    event_ids: dict[tuple[str, str], list[Any]] = defaultdict(list)

    for i, (dt_i, fam_i, id_i) in enumerate(rows):
        for j in range(i + 1, len(rows)):
            dt_j, fam_j, id_j = rows[j]
            if dt_j - dt_i > window:
                break
            if fam_i == fam_j:
                # Same family co-occurrence is not informative here —
                # that's just the family's frequency.
                continue
            key = tuple(sorted((fam_i, fam_j)))
            counter[key] += 1
            # Keep a small set of representative event IDs per pair.
            if len(event_ids[key]) < _MAX_EVENT_IDS_PER_ROW:
                event_ids[key].extend([id_i, id_j])

    out: list[dict] = []
    for (fam_a, fam_b), cnt in counter.most_common():
        if cnt < _MIN_PAIR_COUNT:
            continue
        ids = []
        seen_ids: set[Any] = set()
        for eid in event_ids[(fam_a, fam_b)]:
            if eid is None or eid in seen_ids:
                continue
            seen_ids.add(eid)
            ids.append(eid)
            if len(ids) >= _MAX_EVENT_IDS_PER_ROW:
                break
        out.append({
            "family_a":   fam_a,
            "family_b":   fam_b,
            "count":      cnt,
            "window_days": _COOCCURRENCE_WINDOW_DAYS,
            "event_ids":  ids,
        })
        if len(out) >= _TOP_N_COOCCURRENCE_PAIRS:
            break
    return out


# ---------------------------------------------------------------------------
# Study 2: sector-pair clusters within events
# ---------------------------------------------------------------------------

def _compute_sector_clusters(events: list[dict]) -> list[dict]:
    """Sector pairs that co-appear in the same event's beneficiary + loser
    universe.  Sectors come from ``asset_selection._ticker_channel`` so
    the taxonomy matches the rest of the codebase."""
    counter: Counter[tuple[str, str]] = Counter()
    event_ids: dict[tuple[str, str], list[Any]] = defaultdict(list)

    for ev in events:
        sectors = _event_sectors(ev)
        if len(sectors) < 2:
            continue
        eid = ev.get("id")
        for pair in combinations(sorted(sectors), 2):
            counter[pair] += 1
            if len(event_ids[pair]) < _MAX_EVENT_IDS_PER_ROW and eid is not None:
                event_ids[pair].append(eid)

    out: list[dict] = []
    for (sa, sb), cnt in counter.most_common():
        if cnt < _MIN_PAIR_COUNT:
            continue
        out.append({
            "sector_a":  sa,
            "sector_b":  sb,
            "count":     cnt,
            "event_ids": list(event_ids[(sa, sb)]),
        })
        if len(out) >= _TOP_N_SECTOR_PAIRS:
            break
    return out


# ---------------------------------------------------------------------------
# Study 3: transmission-path clusters (channel-only signatures)
# ---------------------------------------------------------------------------

def _compute_path_clusters(events: list[dict]) -> list[dict]:
    """Top-N recurring channel-only transmission-path signatures.

    Each cluster carries the family distribution of the events that
    produced the signature — useful for spotting "this path shape
    recurs across families X and Y" patterns.
    """
    counter: Counter[tuple[str, ...]] = Counter()
    family_dist: dict[tuple[str, ...], Counter] = defaultdict(Counter)
    event_ids: dict[tuple[str, ...], list[Any]] = defaultdict(list)

    for ev in events:
        sig = _path_signature(ev)
        if sig is None:
            continue
        counter[sig] += 1
        fam = (ev.get("mechanism_family") or "").strip() or "none"
        family_dist[sig][fam] += 1
        if len(event_ids[sig]) < _MAX_EVENT_IDS_PER_ROW:
            eid = ev.get("id")
            if eid is not None:
                event_ids[sig].append(eid)

    out: list[dict] = []
    for sig, cnt in counter.most_common():
        if cnt < _MIN_CLUSTER_COUNT:
            continue
        out.append({
            "signature":    list(sig),
            "count":        cnt,
            "families":     dict(family_dist[sig]),
            "event_ids":    list(event_ids[sig]),
        })
        if len(out) >= _TOP_N_PATH_CLUSTERS:
            break
    return out


# ---------------------------------------------------------------------------
# Study 4: family × sector combination outcomes
# ---------------------------------------------------------------------------

def _compute_combination_outcomes(events: list[dict]) -> list[dict]:
    """Hit-rate per (mechanism_family, sector) combination.

    Net-new vs ``track_record_breakdown``: that module slices by family
    OR regime; this slice is the cross-cut.  A family that wins on
    commodities and loses on credit has two distinct rows here.

    Only combinations with ≥ _MIN_COMBO_COUNT directional events are
    emitted — smaller samples aren't meaningful.

    This is a thesis-OUTCOME aggregation, so ``db.NON_THESIS_STAGES`` rows
    (``curated_observation`` research observations and ``curated_intake``
    stubs) are excluded by stage membership — never by ticker shape. They
    still appear in the descriptive cross-cuts above.
    """
    import db  # NON_THESIS_STAGES — local import keeps this a pure composer

    stats: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"total": 0, "validated": 0, "contradicted": 0, "event_ids": []},
    )

    for ev in events:
        stage = (ev.get("stage") or "").strip()
        if stage in db.NON_THESIS_STAGES:
            continue
        fam = (ev.get("mechanism_family") or "").strip()
        if not fam or fam == "none":
            continue
        sectors = _event_sectors(ev)
        if not sectors:
            continue
        outcome = _score_outcome(ev)
        eid = ev.get("id")

        for sector in sectors:
            key = (fam, sector)
            row = stats[key]
            row["total"] += 1
            if outcome == "validated":
                row["validated"] += 1
            elif outcome == "contradicted":
                row["contradicted"] += 1
            if len(row["event_ids"]) < _MAX_EVENT_IDS_PER_ROW and eid is not None:
                row["event_ids"].append(eid)

    out: list[dict] = []
    for (fam, sector), row in stats.items():
        directional = row["validated"] + row["contradicted"]
        if directional < _MIN_COMBO_COUNT:
            continue
        hit_rate = (row["validated"] / directional) if directional > 0 else None
        out.append({
            "mechanism_family": fam,
            "sector":           sector,
            "total":            row["total"],
            "validated":        row["validated"],
            "contradicted":     row["contradicted"],
            "hit_rate":         round(hit_rate, 3) if hit_rate is not None else None,
            "event_ids":        row["event_ids"],
        })

    # Sort by signal strength — combinations with the most distinctive
    # hit rates (far from 0.5) rank first, then by total count.
    def _rank(row: dict) -> tuple[float, int]:
        hr = row.get("hit_rate")
        signal = abs((hr or 0.5) - 0.5)
        return (-signal, -row["total"])
    out.sort(key=_rank)
    return out[:_TOP_N_COMBINATIONS]


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_cross_event_studies(events: Iterable[dict]) -> dict[str, Any]:
    """Run every cross-event study over the archive rows in ``events``.

    Returns::

        {
          "generated_at":        iso8601 timestamp,
          "window_days":         int (baked-in 7d),
          "total_events":        int,
          "family_cooccurrence": [...],
          "sector_clusters":     [...],
          "path_clusters":       [...],
          "combination_outcomes": [...],
        }

    An empty archive returns a shaped block with empty lists — callers
    don't need a membership check.  Never raises.
    """
    event_list: list[dict] = [e for e in (events or []) if isinstance(e, dict)]
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not event_list:
        return {
            "generated_at":        generated_at,
            "window_days":         _COOCCURRENCE_WINDOW_DAYS,
            "total_events":        0,
            "family_cooccurrence": [],
            "sector_clusters":     [],
            "path_clusters":       [],
            "combination_outcomes": [],
        }

    return {
        "generated_at":         generated_at,
        "window_days":          _COOCCURRENCE_WINDOW_DAYS,
        "total_events":         len(event_list),
        "family_cooccurrence":  _compute_family_cooccurrence(event_list),
        "sector_clusters":      _compute_sector_clusters(event_list),
        "path_clusters":        _compute_path_clusters(event_list),
        "combination_outcomes": _compute_combination_outcomes(event_list),
    }
