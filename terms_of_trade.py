"""
terms_of_trade.py

Terms-of-Trade / External Vulnerability Layer.

What it adds
------------
Every macro shock runs through a country's balance sheet.  A crude price
spike is a transfer from importers to exporters; a dollar rally is a
funding-cost shock to anyone with dollar liabilities; a grain-supply
shock concentrates pain in net food importers.

Until now the analysis layer identified the *mechanism* (inventory,
currency channel, policy stance) but left the *external vulnerability
question* — who actually gets hit through their external accounts —
implicit.  This module answers it as a compact structured block.

Output shape
------------
    {
      "exposures": [
          {"country": "Japan",   "region": "DM Asia",
           "role": "loser",  "channel": "oil_import",
           "rationale": "net oil importer; energy dominates the import bill"},
          ...
      ],
      "external_winners":   ["Saudi Arabia", "Norway", ...],
      "external_losers":    ["Japan", "India", "Turkey", ...],
      "dominant_channel":   "oil_import" | "oil_export" | "usd_funding" |
                            "food_import" | "industrial_metal" | "mixed",
      "dominant_channel_label": "Oil importers squeezed",
      "rationale":          str,   # one-line institutional read
      "key_markets":        ["CL", "DXY", ...],
      "available":          bool,
      "stale":              bool,
      "signals": {
          "crude_5d":        float | None,
          "dxy_5d":          float | None,
          "matched_theme":   str,
          "thresholds":      str,
      },
    }

Design notes
------------
- Pure composer.  No I/O.  Caller passes the already-fetched snapshots
  (DXY, CL/GC) plus the event text and the inventory-context output.
- Country taxonomy is a compact static table of ~15 high-liquidity
  names keyed by the external channel they're vulnerable to.  Not a
  world model — just the ones a macro desk watches on a shock.
- Two trigger paths:
    1. Theme match via inventory-context proxy or keyword scan
       (oil, gas, food, metals).
    2. FX stress via DXY 5d move ≥ 1.0 → funding-cost read.
- When both triggers fire we pick whichever has the stronger move and
  mark channel as "mixed" if the overlap is ambiguous.
- Degrades cleanly: no theme match AND no DXY move → ``{}`` and the
  caller skips rendering.  Partial inputs mark stale=True.
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Channel metadata
# ---------------------------------------------------------------------------

CHANNEL_IDS: tuple[str, ...] = (
    "oil_import",
    "oil_export",
    "usd_funding",
    "food_import",
    "industrial_metal",
    "mixed",
    "none",
)

_CHANNEL_LABEL: dict[str, str] = {
    "oil_import":       "Oil importers squeezed",
    "oil_export":       "Oil exporters lifted",
    "usd_funding":      "USD funding stress",
    "food_import":      "Food importers exposed",
    "industrial_metal": "Metal exporters / importers repriced",
    "mixed":            "Mixed external exposure",
    "none":             "No clear external channel",
}

# Canonical liquid markets / proxies per channel.
_CHANNEL_MARKETS: dict[str, list[str]] = {
    "oil_import":       ["CL", "DXY", "EWJ", "INDA"],
    "oil_export":       ["CL", "DXY", "EWW", "EWC"],
    "usd_funding":      ["DXY", "EEM", "EMB", "TLT"],
    "food_import":      ["WEAT", "DXY", "EGPT", "INDA"],
    "industrial_metal": ["COPX", "DXY", "EWA", "EWZ"],
    "mixed":            ["CL", "DXY", "EEM", "GC"],
    "none":             ["DXY", "CL", "GC", "EEM"],
}


# ---------------------------------------------------------------------------
# Country exposure taxonomy
# ---------------------------------------------------------------------------
#
# Each entry is keyed by the external channel the country is most
# exposed to, and carries:
#   - country / region label
#   - role on the shock (winner / loser) — interpreted in the scorer
#     against the actual sign of the commodity/FX move
#   - one-line rationale that renders verbatim in the UI
#
# This is deliberately small and opinionated.  Add names sparingly —
# the goal is a dense institutional read, not a world index.

_COUNTRY_TAXONOMY: dict[str, list[dict]] = {
    # --- Oil importers: hit when crude rises, helped when it falls ---
    "oil_import": [
        {"country": "Japan",       "region": "DM Asia",
         "rationale": "net oil importer; energy dominates the import bill"},
        {"country": "South Korea", "region": "DM Asia",
         "rationale": "net oil importer with heavy energy-intensive exports"},
        {"country": "India",       "region": "EM Asia",
         "rationale": "~85% of crude consumption imported; twin-deficit sensitivity"},
        {"country": "Turkey",      "region": "EM EMEA",
         "rationale": "near-total oil import dependence; current-account fragile"},
        {"country": "Eurozone",    "region": "DM Europe",
         "rationale": "structurally short energy; external balance sensitive to crude"},
    ],
    # --- Oil exporters: lifted when crude rises, hit when it falls ---
    "oil_export": [
        {"country": "Saudi Arabia", "region": "GCC",
         "rationale": "marginal-barrel exporter; fiscal breakeven priced off crude"},
        {"country": "Norway",       "region": "DM Europe",
         "rationale": "oil export windfall feeds the sovereign wealth fund and NOK"},
        {"country": "Canada",       "region": "DM Americas",
         "rationale": "energy is the swing component of the trade balance and CAD"},
        {"country": "Russia",       "region": "EM EMEA",
         "rationale": "oil and gas dominate export revenue and the fiscal position"},
        {"country": "Brazil",       "region": "LatAm",
         "rationale": "Petrobras-linked terms-of-trade tailwind on crude"},
    ],
    # --- USD funding stress: EM/frontier with dollar liabilities ---
    "usd_funding": [
        {"country": "Turkey",     "region": "EM EMEA",
         "rationale": "high external debt and thin reserves; acute FX sensitivity"},
        {"country": "Argentina",  "region": "LatAm",
         "rationale": "dollar-indexed liabilities and reserve scarcity"},
        {"country": "Egypt",      "region": "EM EMEA",
         "rationale": "sizeable FX debt and structural dollar shortage"},
        {"country": "Indonesia",  "region": "EM Asia",
         "rationale": "current-account sensitive to DXY via portfolio outflows"},
        {"country": "South Africa","region": "EM EMEA",
         "rationale": "rand historically leads the EM-FX selloff on DXY spikes"},
    ],
    # --- Food importers: hit when grain/food prices rise ---
    "food_import": [
        {"country": "Egypt",      "region": "EM EMEA",
         "rationale": "world's largest wheat importer; subsidy regime passes the shock through"},
        {"country": "Philippines","region": "EM Asia",
         "rationale": "net rice/wheat importer; CPI weight on food is high"},
        {"country": "North Africa","region": "EM EMEA",
         "rationale": "structural grain deficit; import bill scales directly with wheat"},
        {"country": "South Korea","region": "DM Asia",
         "rationale": "near-total grain import dependence"},
    ],
    # --- Industrial metals: exporters lifted, importers squeezed ---
    "industrial_metal": [
        {"country": "Chile",     "region": "LatAm",
         "rationale": "copper dominates the export basket and the CLP"},
        {"country": "Peru",      "region": "LatAm",
         "rationale": "copper/zinc exporter; fiscal position tied to metals"},
        {"country": "Australia", "region": "DM Asia-Pac",
         "rationale": "iron ore / base-metal exports drive the terms of trade"},
        {"country": "Zambia",    "region": "EM EMEA",
         "rationale": "copper export concentration; reserves tied to the price"},
    ],
}


# ---------------------------------------------------------------------------
# Theme / keyword detection
# ---------------------------------------------------------------------------
#
# Map the most common inventory proxy tickers *and* a lightweight keyword
# set onto one of the known channels.  Keywords are a safety net when
# inventory-context didn't fire (mock analyses, sparse mechanism text).

_PROXY_TO_THEME: dict[str, str] = {
    "USO":  "oil",
    "UNG":  "gas",
    "WEAT": "food",
    "COPX": "metal",
    "SMH":  "none",   # semiconductors — not a terms-of-trade channel
    "BDRY": "none",   # shipping  — not a terms-of-trade channel
}

_KEYWORD_THEMES: list[tuple[set[str], str]] = [
    ({"oil", "crude", "petroleum", "opec", "barrel", "refin", "pipeline",
      "brent", "wti", "gasoline", "diesel"}, "oil"),
    ({"natural gas", "lng", "gas export", "gas terminal"}, "gas"),
    ({"wheat", "grain", "food", "corn", "soybean", "rice",
      "fertiliz", "fertilizer"}, "food"),
    ({"copper", "aluminum", "nickel", "zinc", "iron ore",
      "base metal", "industrial metal"}, "metal"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _snap_change_5d(snapshots: Optional[list[dict]], market: str) -> Optional[float]:
    if not snapshots:
        return None
    target = market.upper()
    for s in snapshots:
        if not isinstance(s, dict):
            continue
        if (s.get("market") or "").upper() != target:
            continue
        if s.get("value") is None or s.get("error"):
            return None
        return _f(s.get("change_5d"))
    return None


def _dxy_from_stress(stress_regime: Optional[dict]) -> Optional[float]:
    """Fallback: derive DXY 5d from stress_regime.detail.safe_haven.assets.Dollar.

    compute_stress_regime already fetches DXY as part of the safe-haven
    signal; reusing that value means we avoid a parallel data path in
    the analyze flow when snapshots are unavailable.
    """
    if not stress_regime or not isinstance(stress_regime, dict):
        return None
    detail = stress_regime.get("detail") or {}
    safe_haven = detail.get("safe_haven") if isinstance(detail, dict) else None
    if not isinstance(safe_haven, dict):
        return None
    assets = safe_haven.get("assets") or {}
    if not isinstance(assets, dict):
        return None
    return _f(assets.get("Dollar"))


def _words(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())


def _detect_theme(
    text: str,
    inventory_context: Optional[dict],
) -> str:
    """Detect the dominant commodity theme for the event.

    Checks the inventory proxy first (already computed upstream), then
    falls back to a simple keyword scan over headline + mechanism text.
    Returns one of: "oil", "gas", "food", "metal", "none".
    """
    proxy = ""
    if inventory_context and isinstance(inventory_context, dict):
        proxy = (inventory_context.get("proxy") or "").upper()
    theme = _PROXY_TO_THEME.get(proxy, "")
    if theme and theme != "none":
        return theme

    words = _words(text)
    for keywords, theme in _KEYWORD_THEMES:
        if any(kw in words for kw in keywords):
            return theme
    return "none"


# ---------------------------------------------------------------------------
# Channel resolution
# ---------------------------------------------------------------------------

def _resolve_channel(
    theme: str,
    crude_5d: Optional[float],
    dxy_5d: Optional[float],
) -> tuple[str, str]:
    """Pick the dominant transmission channel.

    Returns (channel_id, rationale_fragment).

    Logic:
      - Oil theme + crude move → oil_import or oil_export depending on sign.
      - Food/metal themes → food_import / industrial_metal.
      - Strong DXY rally with no commodity catalyst → usd_funding.
      - Any strong DXY move in parallel with a commodity shock → mixed
        when the FX leg is large enough to dominate.
      - Nothing meaningful → "none".
    """
    strong_dxy = dxy_5d is not None and abs(dxy_5d) >= 1.0
    moderate_dxy = dxy_5d is not None and abs(dxy_5d) >= 0.5
    strong_crude = crude_5d is not None and abs(crude_5d) >= 3.0

    if theme == "oil" and crude_5d is not None:
        # Commodity leg is the anchor; DXY just adds stress.
        base = "oil_import" if crude_5d > 0 else "oil_export"
        if strong_dxy and strong_crude and (dxy_5d or 0) > 0 and base == "oil_import":
            # Rising crude AND rising dollar = classic squeeze on importers.
            return "oil_import", (
                f"crude +{crude_5d:.1f}/5d with DXY +{dxy_5d:.1f}/5d — "
                f"double squeeze on net importers"
            )
        if strong_crude:
            direction = "rally" if crude_5d > 0 else "selloff"
            return base, f"crude {direction} ({crude_5d:+.1f}/5d) dominates the external read"
        return base, f"crude bias ({crude_5d:+.1f}/5d)"

    if theme == "oil":
        # Theme detected but crude price missing — default to the importer
        # channel with a stale bias.  The channel is still useful for the
        # UI; the signal strip will show crude as unavailable.
        if strong_dxy and (dxy_5d or 0) > 0:
            return "oil_import", (
                f"oil theme with DXY {dxy_5d:+.2f}/5d — importers pressured "
                f"via FX channel (crude print unavailable)"
            )
        return "oil_import", "oil theme detected; crude print unavailable"

    if theme == "food":
        return "food_import", "food / grain shock; import-heavy countries carry the shock"

    if theme == "metal":
        return "industrial_metal", "industrial-metal move repriced exporter / importer split"

    if theme == "gas":
        # Gas maps onto oil-importer logic for the countries we track.
        if crude_5d is not None and crude_5d > 0:
            return "oil_import", "gas shock rides the energy-import channel"
        return "oil_import", "gas supply stress for net energy importers"

    # No commodity theme — look for pure FX stress.
    if strong_dxy and (dxy_5d or 0) > 0:
        return "usd_funding", f"DXY +{dxy_5d:.1f}/5d without a commodity catalyst — pure funding-cost shock"
    if moderate_dxy:
        return "usd_funding", f"DXY {dxy_5d:+.1f}/5d — funding channel in play"

    return "none", "no clear commodity or FX catalyst"


# ---------------------------------------------------------------------------
# Exposure builder
# ---------------------------------------------------------------------------

def _build_exposures(
    channel: str,
    crude_5d: Optional[float],
    dxy_5d: Optional[float],
) -> list[dict]:
    """Turn a resolved channel into a list of winner/loser country entries."""
    out: list[dict] = []

    if channel == "oil_import":
        # Positive crude = importers lose, exporters win.
        losers = _COUNTRY_TAXONOMY["oil_import"]
        winners = _COUNTRY_TAXONOMY["oil_export"]
        if crude_5d is not None and crude_5d < 0:
            losers, winners = winners, losers
        for entry in losers:
            out.append({**entry, "role": "loser", "channel": "oil_import"})
        for entry in winners:
            out.append({**entry, "role": "winner", "channel": "oil_export"})

    elif channel == "oil_export":
        winners = _COUNTRY_TAXONOMY["oil_export"]
        losers = _COUNTRY_TAXONOMY["oil_import"]
        if crude_5d is not None and crude_5d < 0:
            winners, losers = losers, winners
        for entry in winners:
            out.append({**entry, "role": "winner", "channel": "oil_export"})
        for entry in losers:
            out.append({**entry, "role": "loser", "channel": "oil_import"})

    elif channel == "food_import":
        for entry in _COUNTRY_TAXONOMY["food_import"]:
            out.append({**entry, "role": "loser", "channel": "food_import"})

    elif channel == "industrial_metal":
        for entry in _COUNTRY_TAXONOMY["industrial_metal"]:
            out.append({**entry, "role": "winner", "channel": "industrial_metal"})

    elif channel == "usd_funding":
        for entry in _COUNTRY_TAXONOMY["usd_funding"]:
            out.append({**entry, "role": "loser", "channel": "usd_funding"})

    # "mixed" / "none" → no explicit country list; caller will render a
    # short fallback message.  We still return an empty list cleanly.
    return out


def _dedupe_ranked(names: list[str]) -> list[str]:
    """Stable dedupe preserving first occurrence."""
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


# ---------------------------------------------------------------------------
# Rationale
# ---------------------------------------------------------------------------

def _rationale(
    channel: str,
    theme: str,
    crude_5d: Optional[float],
    dxy_5d: Optional[float],
    channel_basis: str,
) -> str:
    crude_txt = f"crude {crude_5d:+.1f}/5d" if crude_5d is not None else "crude flat"
    dxy_txt = f"DXY {dxy_5d:+.2f}/5d" if dxy_5d is not None else "DXY unavailable"

    if channel == "oil_import":
        return (
            f"Net oil importers carry the external cost — {channel_basis}. "
            f"{crude_txt}, {dxy_txt}."
        )
    if channel == "oil_export":
        return (
            f"Oil exporters take the windfall — {channel_basis}. "
            f"{crude_txt}, {dxy_txt}."
        )
    if channel == "usd_funding":
        return (
            f"Dollar move is the binding channel — {channel_basis}. "
            f"EM with dollar liabilities and thin reserves take the hit first. "
            f"{dxy_txt}."
        )
    if channel == "food_import":
        return (
            f"Food-price shock is the binding channel — {channel_basis}. "
            f"Net food importers with high food CPI weight carry the pass-through."
        )
    if channel == "industrial_metal":
        return (
            f"Industrial-metal move repriced exporter baskets — {channel_basis}."
        )
    return (
        f"No clear external vulnerability channel from the current inputs "
        f"({crude_txt}, {dxy_txt})."
    )


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_terms_of_trade(
    headline: str,
    mechanism_text: str,
    inventory_context: Optional[dict] = None,
    snapshots: Optional[list[dict]] = None,
    stress_regime: Optional[dict] = None,
) -> dict:
    """Classify external-vulnerability exposure for the event.

    Pure composer — no I/O.  The caller passes the already-computed
    inventory-context block (for proxy hints), the snapshots list (for
    CL / DXY 5d moves) and the stress regime (purely for the stale flag,
    not currently read into the score).

    Returns ``{}`` when there is genuinely nothing to classify: no
    commodity theme AND no meaningful DXY move AND no headline / text.
    Otherwise returns the full block with ``stale=True`` when snapshot
    inputs are degraded but we still have a theme to report.
    """
    text = f"{headline or ''} {mechanism_text or ''}".strip()
    theme = _detect_theme(text, inventory_context)

    crude_5d = _snap_change_5d(snapshots, "CL")
    dxy_5d = _snap_change_5d(snapshots, "DXY")
    # Fallback: reuse the DXY 5d move that compute_stress_regime already
    # fetched as part of the safe-haven signal.  Same number, no extra I/O.
    # We track whether the fallback was used so that we can mark the block
    # stale (partial snapshots) even when the fallback filled in DXY.
    dxy_from_fallback = False
    if dxy_5d is None:
        fallback_dxy = _dxy_from_stress(stress_regime)
        if fallback_dxy is not None:
            dxy_5d = fallback_dxy
            dxy_from_fallback = True

    has_text = bool(text)
    has_snaps = bool(snapshots)
    has_price_signal = crude_5d is not None or dxy_5d is not None

    # Nothing to say at all.
    if not has_text and not has_price_signal:
        return {}

    channel, channel_basis = _resolve_channel(theme, crude_5d, dxy_5d)

    # If channel resolution came up empty and we have no price signal
    # AND no commodity theme, skip rendering entirely.
    if channel == "none" and theme == "none" and not has_price_signal:
        return {}

    exposures = _build_exposures(channel, crude_5d, dxy_5d)
    winners = _dedupe_ranked([e["country"] for e in exposures if e["role"] == "winner"])
    losers = _dedupe_ranked([e["country"] for e in exposures if e["role"] == "loser"])

    rationale = _rationale(channel, theme, crude_5d, dxy_5d, channel_basis)

    # Stale whenever we couldn't read from a proper snapshot list, or when
    # a commodity-themed event has no crude print at all.
    stale = (
        not has_snaps
        or dxy_from_fallback
        or not has_price_signal
        or (theme in ("oil", "gas") and crude_5d is None)
    )

    return {
        "exposures":              exposures,
        "external_winners":       winners,
        "external_losers":        losers,
        "dominant_channel":       channel,
        "dominant_channel_label": _CHANNEL_LABEL[channel],
        "rationale":              rationale,
        "key_markets":            list(_CHANNEL_MARKETS[channel]),
        "available":              True,
        "stale":                  stale,
        "signals": {
            "crude_5d":      crude_5d,
            "dxy_5d":        dxy_5d,
            "matched_theme": theme,
            "thresholds":    "crude |5d|≥3% / DXY |5d|≥1.0",
        },
    }
