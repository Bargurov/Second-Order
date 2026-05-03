"""Batch research runs across event cohorts.

Turns the archive into a research engine: given a cohort (by
mechanism family, scenario pack, or transmission-path cluster),
produce deterministic batch scoring of what similar events actually
did over time — persistence, repricing path, and falsification — plus
a compact one-paragraph summary suitable for UI / print output.

Design notes
------------
* Pure composer: no I/O, never raises on malformed input.  Callers
  pass in a list of stored event dicts (as returned by
  ``db.load_recent_events`` / ``db.query_events_filtered``).
* Three independent scoring axes:
    - Persistence: did the move hold at the 20d mark?
    - Repricing path: how did it travel (accelerating, holding,
      fading, reversed, negligible, mixed)?
    - Falsification: beneficiary tickers that went down + loser
      tickers that went up → the cohort's real failure rate.
* Confidence basis: a cohort needs at least a few members with
  scoreable returns before claims like "tariff cycles typically fade"
  are trustworthy.  `confidence_basis ∈ {deep, medium, thin}` makes
  that explicit so the caller never overstates a 3-event pattern.
* Cohort selection is orthogonal to scoring: a caller can select by
  family today and by transmission cluster tomorrow without touching
  the scoring layer.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Scenario packs
# ---------------------------------------------------------------------------
# Named bundles of mechanism families that tend to move markets in
# similar ways — lets callers ask "how do tariff cycles usually
# reprice?" without having to know the exact family enums.

SCENARIO_PACKS: dict[str, tuple[str, ...]] = {
    "tariff_cycle":        ("tariff",),
    "sanction_cycle":      ("sanction",),
    "supply_squeeze":      ("supply_shock", "commodity_squeeze"),
    "supply_relief":       ("supply_normalization",),
    "funding_squeeze":     ("bank_stress",),
    "policy_surprise":     ("policy_surprise", "fiscal_issuance"),
    "inflation_pressure":  ("labor_inflation",),
    "de_escalation":       ("ceasefire_deescalation", "supply_normalization"),
}


# ---------------------------------------------------------------------------
# Constants — pin magic numbers so calibrate_thresholds can audit them.
# ---------------------------------------------------------------------------

# Absolute 20d return above which we say the move "held" at horizon.
# Below this the move has decayed into noise even if it didn't reverse.
_HOLD_THRESHOLD_PCT: float = 0.5

# Cohort-size gates for confidence_basis.  Below `_THIN_SIZE` the
# research output is tagged ``thin`` and the caller should avoid
# drawing conclusions.
_THIN_SIZE: int = 3
_DEEP_SIZE: int = 10

# Threshold for calling a cohort's repricing path "typical": at least
# this fraction of members must share the dominant decay label.
_TYPICAL_SHARE: float = 0.5

REPRICING_LABELS: tuple = (
    "Accelerating", "Holding", "Fading", "Reversed",
    "Negligible", "Unknown",
)


# ---------------------------------------------------------------------------
# Cohort selection
# ---------------------------------------------------------------------------

def _in_date_range(event: dict, start: Optional[str], end: Optional[str]) -> bool:
    d = event.get("event_date") or event.get("timestamp")
    if not isinstance(d, str):
        return False
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


def _regime_field(ev: dict, path: tuple[str, ...]) -> Optional[str]:
    """Pull a dotted field from the event's regime_snapshot JSON blob."""
    raw = ev.get("regime_snapshot")
    if isinstance(raw, str):
        try:
            import json as _json
            raw = _json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None
    cur: Any = raw
    for part in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur if isinstance(cur, str) and cur else None


def select_cohort(
    events: Optional[list[dict]],
    mechanism_family: Optional[str | Iterable[str]] = None,
    scenario_pack: Optional[str] = None,
    transmission_cluster: Optional[dict] = None,
    stage: Optional[str] = None,
    persistence: Optional[str] = None,
    date_range: Optional[tuple[Optional[str], Optional[str]]] = None,
    regime_inflation: Optional[str] = None,
    regime_policy_stance: Optional[str] = None,
    compound_regime: Optional[str] = None,
) -> dict[str, Any]:
    """Select a cohort from a list of events using the given filters.

    Filters compose via AND.  Any filter left as ``None`` is ignored.
    Passing ``transmission_cluster`` narrows the pool to the events
    listed in that cluster's ``members`` (by event_id / headline), so
    callers can feed output from ``transmission_cluster`` directly.

    Returns:
        {
          "filter":  {... filter dict for provenance ...},
          "members": [events that passed],
          "size":    int,
        }
    """
    events = events or []
    applied: dict[str, Any] = {}

    families: Optional[set[str]] = None
    if scenario_pack:
        pack = SCENARIO_PACKS.get(scenario_pack)
        if pack:
            families = set(pack)
            applied["scenario_pack"] = scenario_pack
    if mechanism_family:
        if isinstance(mechanism_family, str):
            fams = {mechanism_family}
        else:
            fams = {f for f in mechanism_family if isinstance(f, str)}
        families = (families | fams) if families else fams
        applied["mechanism_family"] = sorted(fams)

    cluster_ids: Optional[set] = None
    cluster_headlines: Optional[set[str]] = None
    if isinstance(transmission_cluster, dict):
        cluster_ids = set()
        cluster_headlines = set()
        for m in transmission_cluster.get("members") or []:
            if not isinstance(m, dict):
                continue
            if m.get("event_id") is not None:
                cluster_ids.add(m["event_id"])
            hl = m.get("headline")
            if isinstance(hl, str):
                cluster_headlines.add(hl)
        applied["transmission_cluster"] = {
            "cluster_id": transmission_cluster.get("cluster_id"),
            "kind":       transmission_cluster.get("kind"),
            "family":     transmission_cluster.get("family"),
            "size":       transmission_cluster.get("size"),
        }

    start, end = (date_range or (None, None))

    members: list[dict] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if families is not None:
            if (ev.get("mechanism_family") or "none") not in families:
                continue
        if cluster_ids is not None and (cluster_ids or cluster_headlines):
            ev_id = ev.get("id") or ev.get("event_id")
            if ev_id not in cluster_ids:
                if ev.get("headline") not in (cluster_headlines or set()):
                    continue
        if stage and ev.get("stage") != stage:
            continue
        if persistence and ev.get("persistence") != persistence:
            continue
        if (start or end) and not _in_date_range(ev, start, end):
            continue
        # Regime filters pull from the persisted regime_snapshot blob.
        # Any of the three axes can be filtered independently; AND
        # semantics with every other filter.
        if regime_inflation and _regime_field(ev, ("inflation",)) != regime_inflation:
            continue
        if regime_policy_stance and _regime_field(ev, ("policy_stance",)) != regime_policy_stance:
            continue
        if compound_regime and _regime_field(ev, ("compound", "label")) != compound_regime:
            continue
        members.append(ev)

    if stage:
        applied["stage"] = stage
    if persistence:
        applied["persistence"] = persistence
    if start or end:
        applied["date_range"] = {"start": start, "end": end}
    if regime_inflation:
        applied["regime_inflation"] = regime_inflation
    if regime_policy_stance:
        applied["regime_policy_stance"] = regime_policy_stance
    if compound_regime:
        applied["compound_regime"] = compound_regime

    return {
        "filter":  applied,
        "members": members,
        "size":    len(members),
    }


# ---------------------------------------------------------------------------
# Per-event scoring helpers
# ---------------------------------------------------------------------------

def _dominant_ticker_return(tickers: list, horizon: str) -> Optional[float]:
    """Largest-magnitude return at the requested horizon from a ticker list."""
    if not isinstance(tickers, list):
        return None
    best: Optional[float] = None
    key = "return_5d" if horizon == "5d" else "return_20d"
    for t in tickers:
        if not isinstance(t, dict):
            continue
        r = t.get(key)
        if not isinstance(r, (int, float)):
            continue
        if best is None or abs(r) > abs(best):
            best = float(r)
    return best


def _classify_persistence(r20: Optional[float]) -> str:
    """Classify whether the move held at the 20d horizon."""
    if r20 is None:
        return "unknown"
    if abs(r20) >= _HOLD_THRESHOLD_PCT:
        return "held"
    return "faded"


def _classify_event_repricing(event: dict) -> str:
    """Return the decay label for an event using its dominant ticker pair.

    Delegates to ``market_check.classify_decay`` so the label is the
    same one the analog path uses — no drift between modules.  Returns
    "Unknown" when return data is missing.
    """
    tickers = event.get("market_tickers") or []
    r5 = _dominant_ticker_return(tickers, "5d")
    r20 = _dominant_ticker_return(tickers, "20d")
    try:
        from market_check import classify_decay as _classify_decay
        return _classify_decay(r5, r20).get("label") or "Unknown"
    except Exception:
        return "Unknown"


def _count_contradictions(event: dict) -> tuple[int, int]:
    """Count tickers that moved opposite to their assigned role.

    Returns ``(contradictions, total_scored)``.  A beneficiary is a
    contradiction when its 20d return is negative below the hold
    threshold; a loser is a contradiction when it rose above it.
    Unscorable tickers (no return_20d) are excluded from the total.
    """
    tickers = event.get("market_tickers") or []
    if not isinstance(tickers, list):
        return 0, 0
    contradictions = 0
    total = 0
    for t in tickers:
        if not isinstance(t, dict):
            continue
        role = t.get("role")
        r20 = t.get("return_20d")
        if not isinstance(r20, (int, float)):
            continue
        if role not in ("beneficiary", "loser"):
            continue
        total += 1
        if role == "beneficiary" and r20 <= -_HOLD_THRESHOLD_PCT:
            contradictions += 1
        elif role == "loser" and r20 >= _HOLD_THRESHOLD_PCT:
            contradictions += 1
    return contradictions, total


# ---------------------------------------------------------------------------
# Aggregate scoring
# ---------------------------------------------------------------------------

def _score_persistence(members: list[dict]) -> dict[str, Any]:
    dist = {"held": 0, "faded": 0, "unknown": 0}
    r20s: list[float] = []
    for ev in members:
        r20 = _dominant_ticker_return(ev.get("market_tickers") or [], "20d")
        label = _classify_persistence(r20)
        dist[label] += 1
        if r20 is not None:
            r20s.append(r20)

    scored = dist["held"] + dist["faded"]
    hold_rate = dist["held"] / scored if scored else 0.0

    mean_20d = (sum(r20s) / len(r20s)) if r20s else None
    median_abs_20d = None
    if r20s:
        absvals = sorted(abs(x) for x in r20s)
        n = len(absvals)
        median_abs_20d = absvals[n // 2] if n % 2 == 1 else (absvals[n // 2 - 1] + absvals[n // 2]) / 2

    return {
        "distribution":    dist,
        "scored":          scored,
        "hold_rate":       round(hold_rate, 3),
        "mean_20d":        round(mean_20d, 2) if mean_20d is not None else None,
        "median_abs_20d":  round(median_abs_20d, 2) if median_abs_20d is not None else None,
    }


def _score_repricing_path(members: list[dict]) -> dict[str, Any]:
    dist = {label: 0 for label in REPRICING_LABELS}
    for ev in members:
        label = _classify_event_repricing(ev)
        if label not in dist:
            dist["Unknown"] += 1
        else:
            dist[label] += 1

    scored = sum(v for k, v in dist.items() if k != "Unknown")
    if scored == 0:
        return {
            "distribution": dist,
            "scored":       0,
            "typical":      "unknown",
            "typical_share": 0.0,
        }

    # Ignore Unknown when picking the typical path — we want the
    # modal behaviour across scoreable events, not "we didn't have
    # data on most of them."
    scored_dist = {k: v for k, v in dist.items() if k != "Unknown"}
    top_label, top_count = max(scored_dist.items(), key=lambda kv: (kv[1], kv[0]))
    top_share = top_count / scored
    typical = top_label.lower() if top_share >= _TYPICAL_SHARE else "mixed"

    return {
        "distribution":  dist,
        "scored":        scored,
        "typical":       typical,
        "typical_share": round(top_share, 3),
    }


def _build_composition(members: list[dict]) -> dict[str, Any]:
    """Distributional breakdown across structural axes.

    Emits counts by mechanism family, stage, persistence label, and —
    when the members carry a regime_snapshot — an inflation × policy
    stance slot used as a compact regime key.  Missing axes simply
    don't appear in the corresponding dict, so downstream
    comparison code can treat an empty distribution as "no signal".
    """
    fam: dict[str, int] = {}
    stage: dict[str, int] = {}
    persistence: dict[str, int] = {}
    regime: dict[str, int] = {}

    for ev in members:
        fam_key = (ev.get("mechanism_family") or "none")
        fam[fam_key] = fam.get(fam_key, 0) + 1

        stg = ev.get("stage") or "unknown"
        stage[stg] = stage.get(stg, 0) + 1

        per = ev.get("persistence") or "unknown"
        persistence[per] = persistence.get(per, 0) + 1

        snap = ev.get("regime_snapshot")
        if isinstance(snap, dict):
            inf = snap.get("inflation") or snap.get("inflation_path") or ""
            pol = snap.get("policy_stance") or ""
            if inf or pol:
                key = f"{inf}|{pol}"
                regime[key] = regime.get(key, 0) + 1

    return {
        "mechanism_family":  fam,
        "stage":             stage,
        "persistence_label": persistence,
        "regime":            regime,
    }


def _score_falsification(members: list[dict]) -> dict[str, Any]:
    events_with_contradiction = 0
    total_scored_events = 0
    total_tickers_scored = 0
    total_ticker_contradictions = 0
    for ev in members:
        contradictions, n = _count_contradictions(ev)
        if n == 0:
            continue
        total_scored_events += 1
        total_tickers_scored += n
        total_ticker_contradictions += contradictions
        if contradictions / n >= _TYPICAL_SHARE:
            events_with_contradiction += 1

    event_failure_rate = (
        events_with_contradiction / total_scored_events
        if total_scored_events else 0.0
    )
    ticker_failure_rate = (
        total_ticker_contradictions / total_tickers_scored
        if total_tickers_scored else 0.0
    )

    return {
        "scored_events":               total_scored_events,
        "failed_events":               events_with_contradiction,
        "event_failure_rate":          round(event_failure_rate, 3),
        "scored_tickers":              total_tickers_scored,
        "ticker_contradictions":       total_ticker_contradictions,
        "ticker_failure_rate":         round(ticker_failure_rate, 3),
    }


def _confidence_basis(size: int, scored: int) -> str:
    """Cohort confidence: deep / medium / thin."""
    if size < _THIN_SIZE or scored < _THIN_SIZE:
        return "thin"
    if size >= _DEEP_SIZE and scored >= _DEEP_SIZE:
        return "deep"
    return "medium"


# ---------------------------------------------------------------------------
# Summary prose
# ---------------------------------------------------------------------------

def _compose_summary(
    cohort_label: str,
    size: int,
    persistence: dict,
    repricing: dict,
    falsification: dict,
    basis: str,
) -> str:
    """One-paragraph, research-style cohort note."""
    if size == 0:
        return f"No events matched {cohort_label}."

    if basis == "thin":
        return (
            f"{cohort_label}: only {size} event(s) in cohort — too few "
            "to draw a pattern.  Scorecard disclosed but treated as "
            "indicative."
        )

    path = repricing.get("typical", "unknown")
    share = repricing.get("typical_share", 0.0)
    hold = persistence.get("hold_rate", 0.0)
    fail = falsification.get("event_failure_rate", 0.0)
    mean20 = persistence.get("mean_20d")

    move_line = (
        f"typically {path} at 20d ({int(round(share * 100))}%)"
        if path != "mixed" and path != "unknown"
        else "mixed repricing path"
    )
    hold_line = f"held in {int(round(hold * 100))}% of scored events"
    fail_line = (
        f"contradicted outright in {int(round(fail * 100))}%"
        if fail > 0 else "no wholesale contradictions"
    )
    drift_line = (
        f"; average 20d drift {mean20:+.1f}%"
        if mean20 is not None else ""
    )

    return (
        f"{cohort_label}: {size} events — {move_line}, {hold_line}, "
        f"{fail_line}{drift_line}.  Confidence: {basis}."
    )


# ---------------------------------------------------------------------------
# Top-level composer
# ---------------------------------------------------------------------------

def run_batch_research(
    events: Optional[list[dict]],
    *,
    mechanism_family: Optional[str | Iterable[str]] = None,
    scenario_pack: Optional[str] = None,
    transmission_cluster: Optional[dict] = None,
    stage: Optional[str] = None,
    persistence: Optional[str] = None,
    date_range: Optional[tuple[Optional[str], Optional[str]]] = None,
    regime_inflation: Optional[str] = None,
    regime_policy_stance: Optional[str] = None,
    compound_regime: Optional[str] = None,
    cohort_label: Optional[str] = None,
) -> dict[str, Any]:
    """Build a cohort and return a compact batch research report.

    All filter arguments are keyword-only so callers read the call
    site as self-documenting.  Selection composes via AND; supplying
    no filters scores the full input list.

    Returns:
        {
          "cohort_label": str,
          "filter": {...},
          "size": int,
          "members": [{headline, event_date, mechanism_family, ...}],
          "persistence": {...},
          "repricing_path": {...},
          "falsification": {...},
          "confidence_basis": "deep" | "medium" | "thin",
          "summary": str,
          "rationale": str,
        }
    """
    sel = select_cohort(
        events,
        mechanism_family=mechanism_family,
        scenario_pack=scenario_pack,
        transmission_cluster=transmission_cluster,
        stage=stage,
        persistence=persistence,
        date_range=date_range,
        regime_inflation=regime_inflation,
        regime_policy_stance=regime_policy_stance,
        compound_regime=compound_regime,
    )

    label = cohort_label or _derive_label(sel["filter"])
    size = sel["size"]

    persistence_block = _score_persistence(sel["members"])
    repricing_block = _score_repricing_path(sel["members"])
    falsification_block = _score_falsification(sel["members"])
    composition_block = _build_composition(sel["members"])

    scored = max(
        persistence_block["scored"],
        repricing_block["scored"],
        falsification_block["scored_events"],
    )
    basis = _confidence_basis(size, scored)

    summary = _compose_summary(
        label, size, persistence_block, repricing_block, falsification_block, basis,
    )

    member_rows = [
        {
            "event_id":         ev.get("id") or ev.get("event_id"),
            "headline":         ev.get("headline"),
            "event_date":       ev.get("event_date"),
            "mechanism_family": ev.get("mechanism_family") or "none",
            "stage":            ev.get("stage"),
            "persistence":      ev.get("persistence"),
        }
        for ev in sel["members"]
    ]

    return {
        "cohort_label":      label,
        "filter":            sel["filter"],
        "size":              size,
        "members":           member_rows,
        "persistence":       persistence_block,
        "repricing_path":    repricing_block,
        "falsification":     falsification_block,
        "composition":       composition_block,
        "confidence_basis":  basis,
        "summary":           summary,
        "rationale":         _derive_rationale(sel["filter"], size, basis),
    }


def _derive_label(f: dict) -> str:
    """Best-effort human label for a cohort from its filter dict.

    When regime filters are present alongside a family filter, compose
    them so a comparison like ``tariff in reflation vs tariff in
    stagflation`` reads cleanly without the caller supplying labels.
    """
    if not f:
        return "all events"

    parts: list[str] = []
    if f.get("scenario_pack"):
        parts.append(f["scenario_pack"])
    else:
        fams = f.get("mechanism_family")
        if fams:
            parts.append(fams[0] if len(fams) == 1 else " + ".join(fams))
        else:
            tc = f.get("transmission_cluster")
            if tc:
                kind = tc.get("kind", "cluster")
                fam = tc.get("family", "")
                parts.append(f"{fam} {kind}".strip() if fam else kind)

    regime_bits: list[str] = []
    if f.get("compound_regime"):
        regime_bits.append(f["compound_regime"])
    if f.get("regime_inflation"):
        regime_bits.append(f"inf={f['regime_inflation']}")
    if f.get("regime_policy_stance"):
        regime_bits.append(f"policy={f['regime_policy_stance']}")
    if regime_bits:
        parts.append(" / ".join(regime_bits))

    if not parts:
        return "filtered cohort"
    return " · ".join(parts)


def _derive_rationale(f: dict, size: int, basis: str) -> str:
    parts: list[str] = []
    if not f:
        parts.append("all events")
    if f.get("scenario_pack"):
        parts.append(f"scenario={f['scenario_pack']}")
    if f.get("mechanism_family"):
        parts.append(f"families={','.join(f['mechanism_family'])}")
    if f.get("transmission_cluster"):
        parts.append("from transmission cluster")
    if f.get("stage"):
        parts.append(f"stage={f['stage']}")
    if f.get("persistence"):
        parts.append(f"persistence={f['persistence']}")
    if f.get("date_range"):
        parts.append("within date range")
    return f"n={size}, basis={basis}: " + ", ".join(parts or ["no filter"])
