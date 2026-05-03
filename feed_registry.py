"""
feed_registry.py

Sector/region tagging for RSS feeds and config-driven filtering.

Config file: ``feed_config.json`` (optional, at project root).
Override location via the ``FEED_CONFIG_PATH`` env var.

Example config:
  {
    "active_sectors": ["macro", "energy", "trade"],
    "active_regions": ["global", "americas", "europe"]
  }

Omit ``active_sectors`` or ``active_regions`` to leave that dimension
unconstrained (all feeds pass it).  If the file is absent or invalid,
all feeds are returned — identical to current behavior.
"""

import json
import logging
import os

_log = logging.getLogger("second_order.feed_registry")

_CONFIG_PATH = os.environ.get("FEED_CONFIG_PATH", "feed_config.json")

# ---------------------------------------------------------------------------
# Valid values (documented here so users know what strings are accepted)
# ---------------------------------------------------------------------------

ALL_SECTORS: frozenset[str] = frozenset({
    "macro",        # Wire services, central banks, general economic
    "financials",   # MarketWatch, CNBC, Yahoo Finance, Investing.com
    "energy",       # OilPrice, Rigzone, S&P Global Commodities, EIA
    "trade",        # OFAC Sanctions, USTR Trade Policy
    "defense",      # Defense News
    "geopolitical", # Al Jazeera, AFP, BBC World, The Guardian World
    "commodities",  # Mining.com, freight/shipping, agricultural
    "tech",         # Semiconductor supply chain, export controls
})

ALL_REGIONS: frozenset[str] = frozenset({
    "global",        # Reuters, AP, FT, Bloomberg, WSJ, Investing.com
    "americas",      # NPR, Fed, USTR, MarketWatch, CNBC, Yahoo Finance
    "europe",        # BBC, The Guardian, ECB
    "asia",          # Nikkei, SCMP
    "middle_east",   # Al Jazeera, OFAC
    "south_asia",    # Economic Times (India), RBI
    "latin_america", # LatAm macro, Brazil, Mexico, Colombia
    "africa",        # Sub-Saharan Africa, African Union
})

# ---------------------------------------------------------------------------
# Per-feed metadata
# ---------------------------------------------------------------------------
# A feed may belong to multiple sectors; regions are typically one but could
# be broadened in future.  Feeds not listed here pass all filters by default
# (conservative: unknown feeds are never silently dropped).

FEED_METADATA: dict[str, dict[str, list[str]]] = {
    "Reuters World":          {"sectors": ["macro"],                  "regions": ["global"]},
    "The Guardian Business":  {"sectors": ["macro"],                  "regions": ["europe"]},
    "BBC Business":           {"sectors": ["macro"],                  "regions": ["europe"]},
    "WSJ World News":         {"sectors": ["macro", "financials"],    "regions": ["global"]},
    "AP News":                {"sectors": ["macro"],                  "regions": ["global"]},
    "FT World":               {"sectors": ["macro", "financials"],    "regions": ["global"]},
    "OFAC Sanctions":         {"sectors": ["trade"],                  "regions": ["global"]},
    "EIA Energy":             {"sectors": ["energy"],                 "regions": ["americas"]},
    "USTR Trade Policy":      {"sectors": ["trade"],                  "regions": ["americas"]},
    "AFP World":              {"sectors": ["macro"],                  "regions": ["global"]},
    "Al Jazeera Economy":     {"sectors": ["geopolitical"],           "regions": ["middle_east"]},
    "BBC World":              {"sectors": ["geopolitical"],           "regions": ["europe"]},
    "NPR World":              {"sectors": ["macro"],                  "regions": ["americas"]},
    "The Guardian World":     {"sectors": ["geopolitical"],           "regions": ["europe"]},
    "MarketWatch":            {"sectors": ["financials"],             "regions": ["americas"]},
    "CNBC World":             {"sectors": ["financials"],             "regions": ["americas"]},
    "Yahoo Finance":          {"sectors": ["financials"],             "regions": ["americas"]},
    "Investing.com":          {"sectors": ["financials"],             "regions": ["global"]},
    "OilPrice.com":           {"sectors": ["energy"],                 "regions": ["global"]},
    "Rigzone":                {"sectors": ["energy"],                 "regions": ["global"]},
    "S&P Global Commodities": {"sectors": ["energy"],                 "regions": ["global"]},
    "Fed Press Releases":     {"sectors": ["macro"],                  "regions": ["americas"]},
    "ECB Press Releases":     {"sectors": ["macro"],                  "regions": ["europe"]},
    "Bloomberg Markets":      {"sectors": ["macro", "financials"],    "regions": ["global"]},
    "Nikkei Asia":            {"sectors": ["macro"],                  "regions": ["asia"]},
    "SCMP Economy":           {"sectors": ["macro", "geopolitical"],  "regions": ["asia"]},
    "Defense News":           {"sectors": ["defense"],                "regions": ["global"]},
    # Expanded coverage — commodities, tech, emerging markets
    "Mining.com":             {"sectors": ["commodities"],              "regions": ["global"]},
    "Freight & Shipping":     {"sectors": ["commodities"],              "regions": ["global"]},
    "Economic Times":         {"sectors": ["macro", "financials"],      "regions": ["south_asia"]},
    "LatAm Economy":          {"sectors": ["macro", "geopolitical"],    "regions": ["latin_america"]},
    "IMF News":               {"sectors": ["macro"],                    "regions": ["global"]},
    "World Bank":             {"sectors": ["macro"],                    "regions": ["global"]},
    "Semiconductor Trade":    {"sectors": ["tech", "trade"],            "regions": ["global"]},
    "Africa Economy":         {"sectors": ["macro", "geopolitical"],    "regions": ["africa"]},
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_config(path: str = _CONFIG_PATH) -> dict | None:
    """Load feed_config.json. Returns None if absent or unreadable."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        _log.warning("[feed_registry] Cannot read %s: %s — using all feeds", path, exc)
        return None


def _feed_passes(
    name: str,
    active_sectors: frozenset[str] | None,
    active_regions: frozenset[str] | None,
) -> bool:
    """Return True if the named feed satisfies the active dimension filters."""
    if active_sectors is None and active_regions is None:
        return True
    meta = FEED_METADATA.get(name)
    if meta is None:
        # Unknown feed — include by default so nothing disappears silently.
        return True
    if active_sectors is not None:
        if not any(s in active_sectors for s in meta["sectors"]):
            return False
    if active_regions is not None:
        if not any(r in active_regions for r in meta["regions"]):
            return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_active_feeds(
    feeds: list[dict] | None = None,
    config_path: str = _CONFIG_PATH,
) -> list[dict]:
    """Return the filtered feed list according to feed_config.json.

    Parameters
    ----------
    feeds:
        Base feed list to filter.  Defaults to ``DEFAULT_FEEDS`` from
        ``news_fetch`` when None.
    config_path:
        Path to the JSON config file.  Defaults to ``feed_config.json``
        in the working directory (overridable via ``FEED_CONFIG_PATH``).

    Returns
    -------
    Filtered list of feed dicts.  Falls back to the full base list when
    the config is absent, invalid, or produces an empty result.
    """
    from news_fetch import DEFAULT_FEEDS as _DEFAULT_FEEDS
    if feeds is None:
        feeds = _DEFAULT_FEEDS

    cfg = _load_config(config_path)
    if cfg is None:
        return feeds

    raw_sectors = cfg.get("active_sectors")
    raw_regions = cfg.get("active_regions")

    active_sectors: frozenset[str] | None = None
    active_regions: frozenset[str] | None = None

    if raw_sectors is not None:
        active_sectors = frozenset(str(s).lower() for s in raw_sectors)
        unknown = active_sectors - ALL_SECTORS
        if unknown:
            _log.warning("[feed_registry] Unrecognised sectors in config: %s", sorted(unknown))

    if raw_regions is not None:
        active_regions = frozenset(str(r).lower() for r in raw_regions)
        unknown = active_regions - ALL_REGIONS
        if unknown:
            _log.warning("[feed_registry] Unrecognised regions in config: %s", sorted(unknown))

    filtered = [f for f in feeds if _feed_passes(f["name"], active_sectors, active_regions)]

    if not filtered:
        _log.warning(
            "[feed_registry] Config filtered out all feeds — falling back to full list "
            "(sectors=%s, regions=%s)",
            sorted(active_sectors) if active_sectors else "all",
            sorted(active_regions) if active_regions else "all",
        )
        return feeds

    _log.info(
        "[feed_registry] %d/%d feeds active — sectors=%s regions=%s",
        len(filtered), len(feeds),
        sorted(active_sectors) if active_sectors else "all",
        sorted(active_regions) if active_regions else "all",
    )
    return filtered
