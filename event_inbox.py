"""automatic-event-inbox-v1 — read-only inbox over the persisted news clusters.

Derives the Automatic Event Inbox from the EXISTING local pipeline state:
``news_clusters`` rows written by ``news_cluster_store.refresh_clusters``
(the sole writer, owned by ``POST /news/refresh``).  Everything here is
local-state-only: the store is opened through a read-only SQLite connection
(``mode=ro``), and no function in this module fetches, refreshes, clusters,
or writes anything.

Cluster time identity (A0-R1)
-----------------------------
Every time-dependent field is derived by ``derive_cluster_times`` from the
publication timestamps of the records the cluster OWNS — first/last seen,
publication ordering, 14-day window eligibility and lifecycle age all read
that one rule.  The stored ``latest_published_at`` column is NOT consulted:
it is maintained by the refresh writer from the in-memory clusterer output
and was observed drifting in both directions (ahead of every owned record,
which promoted a nine-day-old notice to the top of the inbox; and behind a
fresh owned record, which counted a cluster holding yesterday's article as
``beyond_window``).  Records with a missing or unparsable ``published_at``
contribute nothing and are never back-filled with the current time; a
cluster where no owned record carries a parsable timestamp keeps null
stamps, stays visible, and is disclosed as PARTIAL/WATCH.

Reused pipeline primitives (no second clustering system, no new identity):
  * cluster identity      — the ``news_clusters`` integer primary key
  * headline dedup key    — ``news_sources._dedup_key`` (same normalizer the
                            store uses for repeat detection)
  * source tiers          — ``news_fetch.source_tier``
  * family mapping        — ``family_inference.resolve_effective_family``
  * event stage           — ``classify.classify_stage``

Frozen deterministic rules and their empirical basis
----------------------------------------------------
Grounded in a read-only scan of the full local store on 2026-07-24
(13,529 clusters):

* ``RESOLVED_AFTER_HOURS = 48`` — reuses ``news_cluster_store._RECENCY_HOURS``,
  the store's own calibrated "story stops picking up sources" archive window.
  No new threshold is invented for quiescence.
* ``DEVELOPING_WAVE_GAP_HOURS = 6`` — 20.2% of stored clusters gained a later
  record with a DIFFERENT dedup title key.  The observed gap from first
  publication to that later distinct-key record: p10=1.8h, p25=9.1h,
  p50=33.7h; same-wave rewordings concentrate at a span of ~0h (p75 of
  cluster span = 0h).  A 6-hour wave gap therefore separates same-cycle
  rewrites from follow-on coverage while keeping ~80% of genuine
  later-distinct-key updates classified as developments.  A repeated title
  key NEVER counts as a development regardless of timing.
* ``INBOX_WINDOW_DAYS = 14`` — payload bound only (7x the archive window):
  clusters whose last publication is older are excluded from the event list
  but explicitly counted (``counts.beyond_window``), never silently dropped.
* Source-count / diversity facts observed: 84% of stored clusters are
  single-source; official-agency feeds appear in 9.6%; headline-only family
  inference resolves a family for ~9% (so ``event_family`` is usually null,
  disclosed per event).

Lifecycle (workflow states only — never market direction or outcome):
  RESOLVED    last publication older than the 48h archive window.
  WATCH       facts insufficiently resolved: missing publication timestamps,
              a single non-official source, mixed agreement, or high
              source-derived uncertainty.
  DEVELOPING  a later record with a new dedup title key arrived at least
              6h after the cluster's first publication.
  NEW         everything else inside the archive window.
Precedence: RESOLVED, then WATCH, then DEVELOPING, then NEW.

Materiality gate: an event is surfaced only when the documented keyword rule
below maps its headline+summary to at least one explicit economic channel.
The vocabulary is adapted from the ingestion relevance allowlist
(``news_relevance.py``) so surfacing uses the same domain vocabulary that
admitted the headline, extended with per-channel terms.  Clusters matching no
channel are excluded but counted (``counts.excluded_no_material_channel``).
No opaque score exists anywhere in this contract.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple, Optional

from news_cluster_store import _RECENCY_HOURS

_log = logging.getLogger("second_order.event_inbox")

CONTRACT_VERSION = "automatic-event-inbox-v1"

GENERATED_FROM = "local news_clusters store (read-only SQLite)"

LIFECYCLE_STATES: tuple[str, ...] = ("NEW", "DEVELOPING", "WATCH", "RESOLVED")

RESOLVED_AFTER_HOURS: int = _RECENCY_HOURS  # 48h — store's calibrated window
DEVELOPING_WAVE_GAP_HOURS: float = 6.0
INBOX_WINDOW_DAYS: int = 14

# Official-agency feeds in the configured feed set (news_fetch._SOURCE_TIERS).
OFFICIAL_SOURCES: frozenset[str] = frozenset({
    "Fed Press Releases", "ECB Press Releases", "OFAC Sanctions",
    "USTR Trade Policy", "EIA Energy", "FDA Press Releases",
    "USDA News", "IMF News", "World Bank",
})

NON_CLAIM = (
    "Events are surfaced through explicit source, identity and "
    "economic-channel rules. Inclusion is not a prediction of price "
    "direction, significance or tradeability."
)

ABSENCE_NOTE = (
    "Absence from the inbox does not prove that an event is economically "
    "irrelevant."
)

# ---------------------------------------------------------------------------
# Material channels — canonical order + deterministic keyword rule
# ---------------------------------------------------------------------------
# Each entry: (channel, substring keywords, word-boundary keywords).
# Substrings are multi-word phrases or long stems; short/ambiguous words use
# word-boundary matching (mirrors the news_relevance two-tier convention).

_CHANNEL_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("GROWTH",
     ("gdp", "recession", "economic growth", "industrial production",
      "industrial output", "retail sales", "consumer spending",
      "factory output", "economic slowdown"),
     ("pmi",)),
    ("INFLATION",
     ("inflation", "deflation", "consumer price", "producer price",
      "price index", "cost of living", "wage growth"),
     ("cpi", "ppi")),
    ("RATES",
     ("interest rate", "rate hike", "rate cut", "rate decision",
      "central bank", "federal reserve", "monetary policy", "basis points",
      "bond yield", "treasury yield", "yield curve", "policy rate"),
     ("fed", "ecb", "boj", "pboc", "fomc")),
    ("LIQUIDITY",
     ("liquidity", "quantitative easing", "quantitative tightening",
      "balance sheet runoff", "money market", "funding stress",
      "repo market", "lender of last resort", "bank run",
      "deposit outflow"),
     ()),
    ("CREDIT",
     ("credit spread", "credit condition", "credit rating", "default",
      "downgrade", "bankruptc", "debt restructur", "high-yield",
      "nonperforming", "insolven"),
     ()),
    ("CURRENCY",
     ("currency", "devaluation", "exchange rate", "capital control",
      "depreciat", "dollar"),
     ("fx", "yen", "yuan", "euro", "peso", "rupee", "lira")),
    ("TRADE",
     ("tariff", "trade deal", "trade war", "trade agreement",
      "export control", "import dut", "sanction", "embargo",
      "protectionis", "free trade", "dumping", "trade talks"),
     ()),
    ("SUPPLY_CHAIN",
     ("supply chain", "shortage", "chokepoint", "shipping", "freight",
      "blockade", "red sea", "suez", "strait of hormuz", "reroute",
      "logistics", "supply disruption"),
     ("tanker", "port")),
    ("FISCAL_POLICY",
     ("fiscal", "budget deficit", "debt ceiling", "sovereign debt",
      "government spending", "government shutdown", "stimulus",
      "treasury issuance", "tax cut", "tax hike", "tax credit",
      "public debt", "bond issuance", "austerity"),
     ()),
    ("REGULATION",
     ("regulat", "deregulat", "antitrust", "merger review", "merger block",
      "capital requirement", "stress test", "disclosure rule",
      "dodd-frank", "basel", "consent decree", "compliance order",
      "enforcement action"),
     ()),
    ("CORPORATE_EARNINGS",
     ("earnings", "guidance", "profit warning", "quarterly results",
      "revenue forecast", "profit fell", "profit rose", "outlook cut",
      "outlook raised"),
     ()),
    ("TECHNOLOGY_PRODUCTIVITY",
     ("semiconductor", "artificial intelligence", "data center",
      "datacenter", "chips act", "productivity", "cloud computing",
      "export controls on chips", "ai model", "ai chip"),
     ("ai", "chip", "chips")),
    ("ENERGY_COMMODITIES",
     ("crude", "opec", "natural gas", "petroleum", "refiner", "pipeline",
      "rare earth", "lithium", "cobalt", "copper", "steel", "alumin",
      "wheat", "grain", "commodit", "power grid", "electricity",
      "uranium", "oil price", "oil output", "oil export",
      "oil production", "energy price"),
     ("oil", "lng", "gold", "coal")),
    ("GEOPOLITICAL_RISK",
     ("invasion", "missile", "military", "ceasefire", "truce", "escalat",
      "de-escalat", "conflict", "drone strike", "air strike", "troops",
      "coup", "hostage", "terror", "insurgen", "annex", "border clash",
      "election", "geopolit", "attack"),
     ("war", "nato")),
)

MATERIAL_CHANNELS: tuple[str, ...] = tuple(c for c, _, _ in _CHANNEL_RULES)

_WHY_BY_CHANNEL: dict[str, str] = {
    "GROWTH":                  "Potential effect on growth expectations",
    "INFLATION":               "Potential effect on inflation expectations",
    "RATES":                   "Potential effect on short-term rate expectations or yields",
    "LIQUIDITY":               "Potential effect on funding and liquidity conditions",
    "CREDIT":                  "Potential effect on credit conditions",
    "CURRENCY":                "Potential effect on exchange rates",
    "TRADE":                   "May alter trade flows, tariffs or sanctions exposure",
    "SUPPLY_CHAIN":            "May alter supply-chain constraints",
    "FISCAL_POLICY":           "May affect fiscal issuance or sovereign yields",
    "REGULATION":              "May change the regulatory or antitrust regime",
    "CORPORATE_EARNINGS":      "Bears on corporate earnings or guidance",
    "TECHNOLOGY_PRODUCTIVITY": "May alter technology supply or productivity constraints",
    "ENERGY_COMMODITIES":      "Potential effect on energy or commodity supply and prices",
    "GEOPOLITICAL_RISK":       "Geopolitical escalation or de-escalation channel",
}


def derive_channels(text: str) -> list[str]:
    """Map free text onto material channels via the documented keyword rule.

    Deterministic, case-insensitive; returns channels in canonical order.
    Output is always a subset of ``MATERIAL_CHANNELS``.
    """
    low = (text or "").lower()
    out: list[str] = []
    for channel, substrings, boundary_words in _CHANNEL_RULES:
        hit = any(kw in low for kw in substrings)
        if not hit and boundary_words:
            hit = any(re.search(rf"\b{re.escape(w)}\b", low)
                      for w in boundary_words)
        if hit:
            out.append(channel)
    return out


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

class ClusterTimes(NamedTuple):
    """Publication-time identity of ONE cluster, derived from its own records."""

    first_seen: Optional[datetime]
    last_updated: Optional[datetime]
    newest_record: Optional[dict]
    valid_count: int
    record_count: int


def derive_cluster_times(records: object) -> ClusterTimes:
    """The single publication-time rule for a cluster (A0-R1).

    ``first_seen`` / ``last_updated`` are the earliest / latest parsable
    ``published_at`` among the records the cluster OWNS.  Nothing else is
    consulted: not the stored ``latest_published_at`` metadata column, not
    ``updated_at``, not the refresh or ingestion clock, and never another
    cluster's records.  The stored metadata column is maintained by the
    refresh writer from the in-memory clusterer output and is known to drift
    both ahead of and behind the cluster's own articles, so the inbox does
    not read it.

    ``newest_record`` is the record that supplies ``last_updated``; when
    several records share that timestamp the tie-break is the smallest
    ``(title, source)`` pair, so the choice is deterministic.

    Records whose ``published_at`` is missing, blank or unparsable contribute
    nothing and are NEVER back-filled with the current time.  When no owned
    record carries a parsable timestamp both bounds are ``None`` — the caller
    surfaces that as explicit missingness rather than inventing a time.
    """
    recs = records if isinstance(records, list) else []
    dated: list[tuple[datetime, str, str, dict]] = []
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        dt = _parse_dt(rec.get("published_at"))
        if dt is None:
            continue
        dated.append((dt, rec.get("title") or "", rec.get("source") or "", rec))
    if not dated:
        return ClusterTimes(None, None, None, 0, len(recs))
    first = min(dt for dt, _, _, _ in dated)
    last = max(dt for dt, _, _, _ in dated)
    newest = min((d for d in dated if d[0] == last),
                 key=lambda d: (d[1], d[2]))[3]
    return ClusterTimes(first, last, newest, len(dated), len(recs))


def _parse_dt(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except ValueError:
        return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat()


def _now() -> datetime:
    """Clock seam — patched in tests so the payload is deterministic."""
    return datetime.now()


# ---------------------------------------------------------------------------
# Per-cluster derivation
# ---------------------------------------------------------------------------

def _lifecycle(*, last_pub: Optional[datetime], now: datetime,
               source_count: int, official: bool, agreement: str,
               uncertainty: str, has_late_new_fact: bool) -> tuple[str, bool]:
    """Return (lifecycle, timestamps_missing) under the frozen rules."""
    if last_pub is None:
        return "WATCH", True
    if (now - last_pub) > timedelta(hours=RESOLVED_AFTER_HOURS):
        return "RESOLVED", False
    if (source_count == 1 and not official) or agreement == "mixed" \
            or uncertainty == "high":
        return "WATCH", False
    if has_late_new_fact:
        return "DEVELOPING", False
    return "NEW", False


def _late_new_fact(records: list[dict]) -> bool:
    """True when a record with a NEW dedup title key arrived at least
    ``DEVELOPING_WAVE_GAP_HOURS`` after the cluster's first publication.

    A repeated title key never counts, whatever its timing — article count
    alone is not a development.
    """
    from news_sources import _dedup_key
    pubs: list[tuple[datetime, str]] = []
    for rec in records:
        dt = _parse_dt(rec.get("published_at"))
        if dt is not None:
            pubs.append((dt, _dedup_key(rec.get("title", "") or "")))
    if len(pubs) < 2:
        return False
    pubs.sort(key=lambda p: (p[0], p[1]))
    first_dt, first_key = pubs[0]
    gap = timedelta(hours=DEVELOPING_WAVE_GAP_HOURS)
    return any(key != first_key and (dt - first_dt) >= gap
               for dt, key in pubs[1:])


def _build_context(payload: dict, source_names: list[str],
                   source_count: int) -> str:
    """Compact analysis context — same fields the existing cluster→Analyze
    handoff uses (sources, summary, agreement, consensus)."""
    parts: list[str] = []
    if source_count > 1 and source_names:
        parts.append(f"Sources ({source_count}): {', '.join(source_names)}")
    summary = payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        parts.append(f"Summary: {summary.strip()}")
    agreement = payload.get("agreement")
    if isinstance(agreement, str) and agreement:
        parts.append(f"Agreement: {agreement}")
    con = payload.get("consensus")
    if isinstance(con, dict):
        fields: list[str] = []
        for label, key in (("Actors", "actors"), ("Action", "action"),
                           ("Sector", "sector"), ("Geography", "geography"),
                           ("Uncertainty", "uncertainty")):
            v = con.get(key)
            if v in (None, "", [], {}):
                continue
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            fields.append(f"{label}: {v}")
        if fields:
            parts.append(" | ".join(fields))
    return "\n".join(parts)


def _derive_event(row: dict, *, now: datetime) -> Optional[dict]:
    """Derive one inbox event from a news_clusters row, or None when the
    materiality gate finds no explicit channel (caller counts it)."""
    from classify import classify_stage
    from family_inference import resolve_effective_family

    stored_headline: str = row.get("headline") or ""
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    records = row.get("records") if isinstance(row.get("records"), list) else []

    # One time identity for this cluster, owned records only.
    times = derive_cluster_times(records)
    first_seen = times.first_seen
    last_pub = times.last_updated

    # Headline ownership.  The clusterer's representative-headline policy
    # (most central / highest-tier member) is a selection rule, not a recency
    # rule, and an owned representative is left exactly as stored.  What must
    # not survive is a displayed headline the cluster does not own at all —
    # the same foreign-metadata leak as the timestamp defect — so that case
    # falls back to the cluster's newest owned record.
    owned_titles = {(r.get("title") or "").strip()
                    for r in records if isinstance(r, dict)}
    headline = stored_headline
    headline_repointed = False
    if stored_headline.strip() not in owned_titles and times.newest_record is not None:
        newest_title = (times.newest_record.get("title") or "").strip()
        if newest_title:
            headline = newest_title
            headline_repointed = True

    summary = payload.get("summary")
    summary = summary.strip() if isinstance(summary, str) and summary.strip() else None

    text = headline if summary is None else f"{headline} {summary}"
    channels = derive_channels(text)
    if not channels:
        return None

    payload_sources = payload.get("sources")
    if isinstance(payload_sources, list) and payload_sources:
        source_entries = [
            {"name": s.get("name", ""), "tier": s.get("tier", "low")}
            for s in payload_sources if isinstance(s, dict) and s.get("name")
        ]
    else:
        from news_fetch import source_tier
        seen: set[str] = set()
        source_entries = []
        for r in records:
            name = r.get("source") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            source_entries.append({"name": name, "tier": source_tier(name)})
    record_sources = {r.get("source") for r in records if r.get("source")}
    official_names = sorted(
        ({s["name"] for s in source_entries} | record_sources) & OFFICIAL_SOURCES)
    official = bool(official_names)
    sources = [{"name": s["name"], "tier": s["tier"],
                "official": s["name"] in OFFICIAL_SOURCES}
               for s in source_entries]
    source_count = len(sources)

    consensus = payload.get("consensus") if isinstance(payload.get("consensus"), dict) else {}
    agreement = payload.get("agreement") if isinstance(payload.get("agreement"), str) else ""
    uncertainty = consensus.get("uncertainty") if isinstance(consensus.get("uncertainty"), str) else ""

    lifecycle, ts_missing = _lifecycle(
        last_pub=last_pub, now=now, source_count=source_count,
        official=official, agreement=agreement, uncertainty=uncertainty,
        has_late_new_fact=_late_new_fact(records),
    )

    family = resolve_effective_family({"headline": headline,
                                       "mechanism_summary": summary or ""})
    event_family = family if family and family != "none" else None
    action = consensus.get("action")
    event_type = action if isinstance(action, str) and action not in ("", "unknown") else None

    why: list[str] = [_WHY_BY_CHANNEL[c] for c in channels]
    if official:
        why.append(f"Official source present: {', '.join(official_names)}")
    if source_count >= 2:
        why.append(f"Corroborated across {source_count} independent sources")

    unknowns: list[str] = []
    if ts_missing:
        unknowns.append("Publication timestamps missing; timing unresolved")
    if not official:
        unknowns.append("No official source in the cluster")
    if source_count == 1:
        unknowns.append("Single source; independent corroboration missing")
    if agreement == "mixed":
        unknowns.append("Conflicting source descriptions across the cluster")
    if uncertainty == "high":
        unknowns.append("High source-derived uncertainty")
    if event_family is None:
        unknowns.append("No event-family mapping for this cluster")
    if headline_repointed:
        unknowns.append("Stored representative headline was not among this "
                        "cluster's records; the cluster's newest article is "
                        "shown instead")
    try:
        stage = classify_stage(headline)
    except Exception:
        stage = ""
    if stage == "anticipation":
        unknowns.append("Announced or anticipated action; implementation "
                        "details remain unresolved")

    missing_bits: list[str] = []
    if ts_missing:
        missing_bits.append("publication timestamps unavailable")
    if summary is None:
        missing_bits.append("no stored summary")
    availability_status = "PARTIAL" if missing_bits else "AVAILABLE"
    missing_reason = "; ".join(missing_bits) if missing_bits else None

    return {
        "event_id": f"aei-{row.get('id')}",
        "cluster_id": row.get("id"),
        "headline": headline,
        "event_summary": summary,
        "first_seen_at": _iso(first_seen),
        "last_updated_at": _iso(last_pub),
        "lifecycle": lifecycle,
        "source_count": source_count,
        "sources": sources,
        "official_source_present": official,
        "event_family": event_family,
        "event_type": event_type,
        "material_channels": channels,
        "why_surfaced": why,
        "known_unknowns": unknowns,
        "analysis_target": {
            "headline": headline,
            "context": _build_context(payload, [s["name"] for s in sources],
                                      source_count),
        },
        "availability_status": availability_status,
        "missing_reason": missing_reason,
    }


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------

def _empty_counts() -> dict:
    return {
        "clusters_total": 0,
        "surfaced": 0,
        "beyond_window": 0,
        "excluded_no_material_channel": 0,
        "malformed_rows": 0,
        "by_lifecycle": {state: 0 for state in LIFECYCLE_STATES},
    }


def build_inbox(rows: list[dict], *, now: datetime) -> dict:
    """Pure derivation: news_clusters rows + clock in, inbox payload out."""
    counts = _empty_counts()
    counts["clusters_total"] = len(rows or [])
    events: list[dict] = []
    window = timedelta(days=INBOX_WINDOW_DAYS)

    for row in rows or []:
        if not isinstance(row, dict) or not (row.get("headline") or "").strip() \
                or not isinstance(row.get("payload"), dict):
            counts["malformed_rows"] += 1
            continue
        # Window eligibility reads the SAME owned-record rule the event body
        # uses, so a fresh owned article can never be windowed out by an older
        # stored ``latest_published_at``.
        last_pub = derive_cluster_times(row.get("records")).last_updated
        # A cluster with NO parsable timestamp cannot be proven old — it stays
        # visible (as PARTIAL/WATCH) rather than being silently windowed out.
        if last_pub is not None and (now - last_pub) > window:
            counts["beyond_window"] += 1
            continue
        event = _derive_event(row, now=now)
        if event is None:
            counts["excluded_no_material_channel"] += 1
            continue
        events.append(event)

    events.sort(key=lambda ev: (ev["last_updated_at"] or "", ev["cluster_id"] or 0),
                reverse=True)
    counts["surfaced"] = len(events)
    for ev in events:
        counts["by_lifecycle"][ev["lifecycle"]] += 1

    limitations = [ABSENCE_NOTE]
    limitations.append(
        "Materiality channels are assigned by a documented deterministic "
        "keyword rule; the semantic novelty of an update is not verified.")
    limitations.append(
        "Event-family mapping is an optional enrichment; clusters without a "
        "mapping show that explicitly.")
    if counts["beyond_window"]:
        limitations.append(
            f"{counts['beyond_window']} stored clusters last updated more than "
            f"{INBOX_WINDOW_DAYS} days ago are outside the inbox window "
            "(counted, not shown).")
    if counts["excluded_no_material_channel"]:
        limitations.append(
            f"{counts['excluded_no_material_channel']} clusters matched no "
            "explicit material channel and are excluded (counted, not shown).")
    if counts["malformed_rows"]:
        limitations.append(
            f"{counts['malformed_rows']} stored rows were malformed and could "
            "not be represented.")
    if events:
        energy = sum(1 for ev in events
                     if "ENERGY_COMMODITIES" in ev["material_channels"])
        if energy * 2 > len(events):
            limitations.append(
                f"Observed concentration: {energy} of {len(events)} surfaced "
                "events carry the energy/commodities channel — the local feed "
                "state is not a diversified event universe.")

    return {
        "contract": CONTRACT_VERSION,
        "generated_from": GENERATED_FROM,
        "as_of": now.replace(microsecond=0).isoformat(),
        "availability": "AVAILABLE",
        "events": events,
        "counts": counts,
        "limitations": limitations,
        "non_claim": NON_CLAIM,
    }


def _unavailable_payload(reason: str, *, now: datetime) -> dict:
    return {
        "contract": CONTRACT_VERSION,
        "generated_from": GENERATED_FROM,
        "as_of": now.replace(microsecond=0).isoformat(),
        "availability": "UNAVAILABLE",
        "events": [],
        "counts": _empty_counts(),
        "limitations": [ABSENCE_NOTE, reason],
        "non_claim": NON_CLAIM,
    }


# ---------------------------------------------------------------------------
# Read-only store access + route entry point
# ---------------------------------------------------------------------------

def read_cluster_rows(db_path: str) -> tuple[Optional[list[dict]], Optional[str]]:
    """Read every news_clusters row through a READ-ONLY SQLite connection.

    Returns (rows, None) on success or (None, reason) when the local store is
    missing or unreadable.  ``mode=ro`` makes a write structurally impossible
    on this path.
    """
    if not db_path or not os.path.exists(db_path):
        return None, "No local database file — the news store has never been created."
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            cur = conn.execute(
                "SELECT id, headline, payload_json, records_json, "
                "       latest_published_at, updated_at "
                "FROM news_clusters ORDER BY id")
            raw = cur.fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None, ("Local news cluster store is unreadable or missing its "
                      "table — the inbox cannot be derived.")
    rows: list[dict] = []
    for (cid, headline, payload_json, records_json, latest, updated) in raw:
        try:
            payload = json.loads(payload_json or "{}")
        except (TypeError, ValueError):
            payload = None
        try:
            records = json.loads(records_json or "[]")
        except (TypeError, ValueError):
            records = []
        rows.append({
            "id": cid,
            "headline": headline,
            "payload": payload,
            "records": records,
            "latest_published_at": latest or "",
            "updated_at": updated or "",
        })
    return rows, None


def build_inbox_response() -> dict:
    """GET /news/inbox entry point — local-state-only by construction."""
    import db as _db
    now = _now()
    rows, reason = read_cluster_rows(_db.DB_FILE)
    if rows is None:
        return _unavailable_payload(reason or "Local store unavailable.", now=now)
    return build_inbox(rows, now=now)


# ---------------------------------------------------------------------------
# Fail-closed payload validator (shared by tests)
# ---------------------------------------------------------------------------

_EVENT_FIELDS: tuple[str, ...] = (
    "event_id", "cluster_id", "headline", "event_summary",
    "first_seen_at", "last_updated_at", "lifecycle",
    "source_count", "sources", "official_source_present",
    "event_family", "event_type", "material_channels",
    "why_surfaced", "known_unknowns", "analysis_target",
    "availability_status", "missing_reason",
)

_TOP_FIELDS: tuple[str, ...] = (
    "contract", "generated_from", "as_of", "availability",
    "events", "counts", "limitations", "non_claim",
)

_BANNED_FIELD_TOKENS: tuple[str, ...] = (
    "score", "priority", "urgency", "conviction", "importance",
    "impact", "direction", "buy", "sell", "tradeab", "signal",
)


def validate_inbox_payload(payload: dict) -> list[str]:
    """Return a list of contract violations; empty means valid.

    Fail-closed and cross-sectional: field sets are exact, enums are closed,
    counts must reconcile with the event list, ordering must hold, and no
    score-like or directional field may exist anywhere.
    """
    problems: list[str] = []
    if not isinstance(payload, dict):
        return ["payload is not an object"]
    if set(payload.keys()) != set(_TOP_FIELDS):
        problems.append(f"top-level fields differ: {sorted(payload.keys())}")
        return problems
    if payload["contract"] != CONTRACT_VERSION:
        problems.append(f"contract is {payload['contract']!r}")
    if payload["availability"] not in ("AVAILABLE", "UNAVAILABLE"):
        problems.append(f"availability {payload['availability']!r} not in enum")
    events = payload["events"]
    if not isinstance(events, list):
        return problems + ["events is not a list"]
    for ev in events:
        if not isinstance(ev, dict) or set(ev.keys()) != set(_EVENT_FIELDS):
            problems.append(f"event field set differs: {ev}")
            continue
        if ev["lifecycle"] not in LIFECYCLE_STATES:
            problems.append(f"lifecycle {ev['lifecycle']!r} not in enum")
        chans = ev["material_channels"]
        if not isinstance(chans, list) or not chans:
            problems.append(f"event {ev['event_id']} has no material channel")
        else:
            for ch in chans:
                if ch not in MATERIAL_CHANNELS:
                    problems.append(f"unknown material channel {ch!r}")
        if not isinstance(ev["why_surfaced"], list) or not ev["why_surfaced"]:
            problems.append(f"event {ev['event_id']} has no why_surfaced reason")
        if ev["availability_status"] not in ("AVAILABLE", "PARTIAL"):
            problems.append(
                f"availability_status {ev['availability_status']!r} not in enum")
        if ev["availability_status"] == "PARTIAL" and not ev["missing_reason"]:
            problems.append(
                f"event {ev['event_id']} is PARTIAL without a missing_reason")
        target = ev["analysis_target"]
        if not isinstance(target, dict) or set(target.keys()) != {"headline", "context"}:
            problems.append(f"event {ev['event_id']} analysis_target malformed")

    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                lk = k.lower()
                for token in _BANNED_FIELD_TOKENS:
                    if token in lk:
                        problems.append(f"score-like/directional field {k!r}")
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(payload)

    counts = payload["counts"]
    if not isinstance(counts, dict):
        problems.append("counts is not an object")
    else:
        if counts.get("surfaced") != len(events):
            problems.append("counts.surfaced does not equal len(events)")
        by_lc = counts.get("by_lifecycle") or {}
        if set(by_lc.keys()) != set(LIFECYCLE_STATES):
            problems.append("counts.by_lifecycle keys differ from the enum")
        elif sum(by_lc.values()) != len(events):
            problems.append("counts.by_lifecycle does not sum to len(events)")
        accounted = (len(events) + counts.get("beyond_window", 0)
                     + counts.get("excluded_no_material_channel", 0)
                     + counts.get("malformed_rows", 0))
        if counts.get("clusters_total") != accounted:
            problems.append("counts do not reconcile with clusters_total")
    stamps = [(ev.get("last_updated_at") or "", ev.get("cluster_id") or 0)
              for ev in events if isinstance(ev, dict)]
    if stamps != sorted(stamps, reverse=True):
        problems.append("events are not in publication order")
    if not isinstance(payload["limitations"], list) or \
            ABSENCE_NOTE not in payload["limitations"]:
        problems.append("absence disclosure missing from limitations")
    if payload["non_claim"] != NON_CLAIM:
        problems.append("non_claim wording drifted")
    return problems
