# macro_surprise.py
# Enrich macro_calendar release entries with a surprise signal.
#
# Two data paths, in order of preference:
#   1. Stored release facts (``actual`` + ``consensus`` from the
#      ``macro_release_facts`` cache — populated by a feed).  When both
#      are present on the release dict we compute beat / miss / in_line
#      numerically, so the signal no longer depends on whether a
#      journalist used the word "beat" in a headline.
#   2. Headline inference (legacy): keyword match of indicator name
#      then direction words in news clusters.
#
# Pure function — no I/O, no caching.  The facts path consumes fields
# the caller already put on each release dict (see
# ``macro_calendar.get_macro_releases``); it does not hit SQLite.

_WINDOW_DAYS = 3  # releases within [-3, 0] days_until are eligible

_INDICATOR_KEYWORDS: dict[str, list[str]] = {
    "CPI":          ["cpi", "consumer price", "inflation data"],
    "PPI":          ["ppi", "producer price"],
    "NFP":          ["nonfarm payroll", "nfp", "jobs report", "payrolls"],
    "Unemployment": ["unemployment rate", "jobless rate"],
    "PCE":          ["pce", "personal consumption", "core pce"],
}

_BEAT_KEYWORDS:    list[str] = ["beat", "above", "hotter", "stronger than expected", "tops", "exceeds"]
_MISS_KEYWORDS:    list[str] = ["miss", "below", "cooler", "weaker than expected", "falls short", "disappoints"]
_INLINE_KEYWORDS:  list[str] = ["in line", "as expected", "meets estimates", "matches"]

# "inline" band for the numeric path: |actual − consensus| within this
# fraction of |consensus| counts as in-line regardless of sign.
# Matches the 5 % guard used by macro_surprises.compute_surprise.
_INLINE_RELATIVE_BAND: float = 0.05


def classify_macro_surprise(
    releases: list[dict],
    clusters: list[dict],
) -> list[dict]:
    """Return releases enriched with surprise_signal + provenance.

    Parameters
    ----------
    releases : output of macro_calendar.get_macro_releases()
    clusters : news cluster list, each with a 'headline' field

    Each release gains:
        surprise_signal   — "beat" | "miss" | "in_line" | "unknown" | None
        headline_evidence — str | None
        signal_source     — "official" | "headline" | None

    None surprise_signal / signal_source when the release is outside
    the [-3, 0] day window.  ``signal_source="official"`` when the
    signal was computed from stored release facts; ``"headline"`` when
    derived from the news-cluster heuristic.  ``"unknown"`` remains
    ``"headline"``-sourced — the absence of a confirmed beat/miss is a
    property of the headline scan, not the official feed.
    """
    out = []
    for release in releases:
        days_until = release.get("days_until", 1)
        if not (-_WINDOW_DAYS <= days_until <= 0):
            out.append({
                **release,
                "surprise_signal": None,
                "headline_evidence": None,
                "signal_source": None,
            })
            continue

        official = _signal_from_facts(release)
        if official is not None:
            out.append({
                **release,
                "surprise_signal": official,
                "headline_evidence": None,
                "signal_source": "official",
            })
            continue

        signal, evidence = _scan_clusters(release["name"], clusters)
        out.append({
            **release,
            "surprise_signal": signal,
            "headline_evidence": evidence,
            "signal_source": "headline",
        })
    return out


def attach_cluster_macro_blocks(
    releases: list[dict],
    clusters: list[dict],
) -> list[dict]:
    """Attach a per-cluster ``macro_surprise`` block when stored facts exist.

    Walks every release whose surprise signal came from stored facts
    (``signal_source == "official"``) and stamps the matching news
    clusters with a compact block:

        {
          release_key, release_time, actual, prior, revised_prior,
          consensus, surprise_label, source
        }

    Matching reuses the same indicator-keyword scan ``classify_macro_surprise``
    uses, so a CPI release stamps clusters whose headline mentions
    "cpi" / "consumer price" / "inflation data".  Clusters with no
    matching official release are left exactly as-is — no key is added,
    so the response shape stays stable for callers that don't read it.

    Returns a new list of cluster dicts; the inputs are not mutated.
    Releases lacking ``signal_source == "official"`` are ignored,
    which preserves the "fall back to headline behaviour when no
    stored facts exist" contract.
    """
    out: list[dict] = [dict(c) if isinstance(c, dict) else c for c in clusters or []]

    official = [
        r for r in (releases or [])
        if isinstance(r, dict) and r.get("signal_source") == "official"
    ]
    if not official:
        return out

    for release in official:
        kws = _INDICATOR_KEYWORDS.get(release.get("name", ""), [])
        if not kws:
            continue
        block = _release_to_cluster_block(release)
        if block is None:
            continue
        for cluster in out:
            if not isinstance(cluster, dict):
                continue
            if "macro_surprise" in cluster:
                continue  # first matching official release wins
            headline = (cluster.get("headline") or "").lower()
            if any(kw in headline for kw in kws):
                cluster["macro_surprise"] = block
    return out


def _release_to_cluster_block(release: dict) -> dict | None:
    """Build the per-cluster macro block from an enriched release dict.

    Returns ``None`` when the release is missing the join fields the
    block contract requires (``release_key`` / ``release_time``).
    """
    release_key = release.get("release_key")
    release_time = release.get("release_time")
    if not isinstance(release_key, str) or not release_key:
        return None
    if not isinstance(release_time, str) or not release_time:
        return None
    return {
        "release_key":    release_key,
        "release_time":   release_time,
        "actual":         release.get("actual"),
        "prior":          release.get("prior"),
        "revised_prior":  release.get("revised_prior"),
        "consensus":      release.get("consensus"),
        "surprise_label": release.get("surprise_signal"),
        "source":         release.get("release_facts_source") or "",
    }


def build_event_macro_release_context(
    event: dict,
    calendar_releases: list[dict] | None = None,
) -> dict:
    """Return the ``macro_release_context`` block for an analyzed event.

    Maps an event to a macro release via the same indicator-keyword
    scan used on news clusters: if the event's ``headline`` contains
    any keyword for an in-window release (``-3 ≤ days_until ≤ 0``) we
    stamp the event with that release.  The first match wins — the
    calendar is already sorted chronologically so this biases toward
    the closest release.

    Numeric fields (``actual / prior / revised_prior / consensus``)
    and ``surprise_label`` come **only** from stored release facts.
    When the facts cache has no row for the match we still record the
    ``release_key`` so a later refresh (after a feed populates the
    cache) can flip the other fields in place without re-running the
    headline scan.

    Returns ``{}`` when the headline doesn't map — callers should rely
    on the route-side ``coerce_macro_release_context`` helper for a
    fully-keyed default shape at the HTTP boundary.

    ``calendar_releases`` defaults to a fresh
    ``macro_calendar.get_macro_releases()`` lookup; pass a prepared
    list to avoid re-querying the store when batching.
    """
    headline = (event.get("headline") or "").lower()
    if not headline:
        return {}
    if calendar_releases is None:
        try:
            from macro_calendar import get_macro_releases
            calendar_releases = get_macro_releases()
        except Exception:
            return {}

    for r in calendar_releases or []:
        if not isinstance(r, dict):
            continue
        du = r.get("days_until")
        if not isinstance(du, int) or not (-_WINDOW_DAYS <= du <= 0):
            continue
        kws = _INDICATOR_KEYWORDS.get(r.get("name", ""), [])
        if not kws or not any(kw in headline for kw in kws):
            continue

        has_facts = bool(r.get("has_release_facts"))
        label = _signal_from_facts(r) if has_facts else None
        return {
            "release_key":   r.get("release_key") or (
                f"{r.get('name')}:{r.get('release_date')}"
                if r.get("name") and r.get("release_date") else None
            ),
            "release_time":  r.get("release_time") if has_facts else None,
            "actual":        r.get("actual"),
            "prior":         r.get("prior"),
            "revised_prior": r.get("revised_prior"),
            "consensus":     r.get("consensus"),
            "surprise_label": label,
            "source":        r.get("release_facts_source") or "",
        }
    return {}


_EMPTY_MACRO_RELEASE_CONTEXT: dict = {
    "release_key":    None,
    "release_time":   None,
    "actual":         None,
    "prior":          None,
    "revised_prior":  None,
    "consensus":      None,
    "surprise_label": None,
    "source":         "",
}


def coerce_macro_release_context(block: dict | None) -> dict:
    """Return the canonical ``macro_release_context`` shape.

    ``{}`` / ``None`` / any non-dict input collapses to the stable
    empty-shape dict (every key present, all values ``None`` / ``""``).
    Populated blocks keep their values; missing keys are filled with
    the defaults so downstream consumers can rely on a stable keyset
    regardless of schema version or population state.
    """
    if not isinstance(block, dict) or not block:
        return dict(_EMPTY_MACRO_RELEASE_CONTEXT)
    out = dict(_EMPTY_MACRO_RELEASE_CONTEXT)
    for key in _EMPTY_MACRO_RELEASE_CONTEXT:
        if key in block and block[key] is not None:
            out[key] = block[key]
    # ``source`` coerces to "" (never None).
    if out.get("source") is None:
        out["source"] = ""
    return out


def _signal_from_facts(release: dict) -> str | None:
    """Compute beat / miss / in_line from stored ``actual`` vs ``consensus``.

    Returns ``None`` when either fact is missing so the caller can
    fall back to the headline heuristic.  Requires both values to be
    real numbers and the release to carry the "facts present" marker
    the calendar layer sets so stray ``0.0`` defaults on legacy rows
    don't accidentally short-circuit the heuristic.
    """
    if not release.get("has_release_facts"):
        return None
    actual = release.get("actual")
    consensus = release.get("consensus")
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return None
    if not isinstance(consensus, (int, float)) or isinstance(consensus, bool):
        return None
    diff = float(actual) - float(consensus)
    mag = abs(float(consensus))
    inline_floor = _INLINE_RELATIVE_BAND * mag if mag > 0 else 0.0
    if abs(diff) <= inline_floor:
        return "in_line"
    return "beat" if diff > 0 else "miss"


def _scan_clusters(indicator: str, clusters: list[dict]) -> tuple[str, str | None]:
    """Scan clusters for an indicator match then a direction match.

    Returns (signal, headline_evidence).
    """
    kws = _INDICATOR_KEYWORDS.get(indicator, [])

    for cluster in clusters:
        headline = (cluster.get("headline") or "").lower()
        if not any(kw in headline for kw in kws):
            continue
        # Indicator matched — check direction
        if any(kw in headline for kw in _BEAT_KEYWORDS):
            return "beat", cluster.get("headline")
        if any(kw in headline for kw in _MISS_KEYWORDS):
            return "miss", cluster.get("headline")
        if any(kw in headline for kw in _INLINE_KEYWORDS):
            return "in_line", cluster.get("headline")
        # Indicator matched but no direction keyword — keep scanning
        # (another cluster may have the direction)

    return "unknown", None
