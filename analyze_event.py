"""
analyze_event.py
================

LLM-driven event analyzer.

Responsibilities, in order:

1. Call the Anthropic API with the ``EVENT_ANALYSIS_PROMPT`` contract.
2. Extract JSON from a potentially messy response (``_extract_json``).
3. Normalize the raw dict into a strict schema (types, null-like filler
   stripped, vague placeholders rejected, enums enforced).
4. Sanitize ticker lists — US-listed discipline, inverse-proxy fallback
   for losers, beneficiary/loser overlap removal.
5. Run contradiction-aware validation (``_validate_result``) which can
   downgrade confidence, clear incompatible sections, and surface
   warnings.
6. If the output is too thin to be usable, return a clearly-labelled
   ``_degraded_fallback`` instead of passing thin text through as "valid".

External output shape stays stable: the only new optional key is
``degraded`` (boolean, only present when True).  Every other consumer
(api.py, app.py, telegram_bot.py, tests) sees the same fields as before.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# Ticker sanitizer (unchanged core, slightly expanded coverage)
# ---------------------------------------------------------------------------

# Known-bad tickers: indices, price benchmarks, and symbols observed to fail
# in eval runs. Add any new bad symbol the eval surfaces here.
_BAD_TICKERS = {
    # Volatility / macro indices
    "VIX", "DXY", "VX", "SPX", "NDX", "RUT", "MOVE", "VVIX", "VXN",
    # European and Asian energy benchmarks (not ETFs)
    "TTF", "JKM", "NBP", "HH",
    # Observed in live eval runs as unreliable or unlisted
    "ISDX", "GULF", "ALTM",
    # Single-letter and ambiguous tickers with poor yfinance coverage
    # X  = US Steel (acquisition/delisting issues → no reliable price data)
    # FM = First Quantum Minerals (primary listing is TSX: FM.TO, not US)
    "X", "FM",
    # Delisted or bankrupt tickers observed in eval runs
    # EURN = Euronav (delisted after 2023 merger with Frontline → use FRO instead)
    # TELL = Tellurian (filed bankruptcy 2024 → use LNG or UNG instead)
    # ARCH = Arch Resources (merged into CEIX 2024, ticker retired)
    "EURN", "TELL", "ARCH",
    # OTC pink-sheet ADRs with unreliable yfinance coverage
    # PCRFY = Porsche AG ADR (OTC only, spotty data)
    "PCRFY",
    # Foreign-primary listings the model sometimes returns without a suffix
    # LGES = LG Energy Solution (KRX:373220, not US-listed)
    # SMIC = Semiconductor Manufacturing International (HKEx, OTC ADR is SMICY)
    "LGES", "SMIC",
    # Thin-float or low-AUM tickers with unreliable yfinance data
    # ARNC = Arconic Corp (inconsistent coverage after Howmet spinoff)
    # EGPT = VanEck Egypt ETF (very low volume, frequently returns empty data)
    "ARNC", "EGPT",
    # Defense/shipping tickers the model sometimes hallucinates
    # BAE = BAE Systems (LSE-primary, no US-listed common stock)
    # RHMT = Rheinmetall (FRA-primary, not US-listed)
    "BAE", "RHMT",
    # Additional foreign-primary or observed bad tickers
    # CXMT / YMTC = Chinese DRAM/NAND foundries, not US-listed
    # NAURA / AMEC = Chinese equipment makers, not US-listed
    # HAL (London) vs HAL (NYSE: Halliburton) — skip to avoid confusion when
    # the model emits the wrong region; callers can pass HAL explicitly.
    "CXMT", "YMTC", "NAURA",
}

# Keyword → US-proxy-ETF fallback map.
# Used only when too few clean tickers survive filtering.
# Keywords are matched against the lowercased headline + mechanism text.
_PROXY_MAP = [
    # Semiconductors — expanded to cover supply-chain breadth
    (["semiconductor", "chip", "foundry", "lithography", "wafer", "fab",
      "asml", "tsmc", "euv", "packaging", "hbm", "dram", "nand"],         ["SMH", "SOXX", "TSM"]),
    # Defense & aerospace
    (["defense", "defence", "military", "weapon", "nato", "arms",
      "missile", "rearm", "munition", "fighter jet", "warship",
      "pentagon", "defense spend", "defence spend"],                        ["ITA", "XAR", "LMT"]),
    # Shipping & logistics
    (["shipping", "tanker", "freight", "vessel", "maritime", "chokepoint",
      "dry bulk", "container", "suez", "strait of hormuz", "red sea",
      "port closure", "blockade"],                                          ["BDRY", "FRO", "STNG"]),
    # Energy — kept for backward compat
    (["oil", "crude", "opec", "petroleum", "refin", "brent", "barrel"],     ["XLE", "USO", "BNO"]),
    (["lng", "liquefied natural gas", "gas export", "gas terminal"],        ["LNG", "UNG"]),
    # Metals & mining
    (["palladium", "platinum", "pgm", "precious metal"],                    ["PALL", "PPLT"]),
    (["metal", "mining", "copper", "nickel", "aluminum", "steel"],          ["XME", "COPX"]),
    # Safe-haven & macro
    (["gold", "safe haven", "geopolit", "conflict", "war risk"],            ["GLD"]),
    (["treasury", "rate cut", "rate hike", "central bank", "yield"],        ["TLT", "IEF"]),
    # EV & battery
    (["ev", "electric vehicle", "battery", "lithium"],                      ["DRIV", "LIT"]),
    # Agriculture
    (["wheat", "grain", "agriculture", "soybean", "corn"],                  ["WEAT", "DBA"]),
    # Country exposure
    (["china", "chinese"],                                                   ["FXI", "KWEB"]),
    (["taiwan", "taiwanese"],                                                ["EWT"]),
    (["south korea", "korean"],                                              ["EWY"]),
]

# Loser-side fallback proxies — inverse/short ETFs by theme.
# Used only when ALL loser tickers are removed by sanitization.
# Each proxy is tagged with "(proxy)" in the output so downstream
# consumers know it's a sector-level fallback, not direct company exposure.
_LOSER_PROXY_MAP = [
    (["oil", "crude", "opec", "petroleum", "refin", "brent", "barrel",
      "energy", "fuel", "pipeline", "lng"],                                  ["DUG"]),      # ProShares UltraShort Oil & Gas
    (["semiconductor", "chip", "foundry", "lithography", "wafer", "fab",
      "asml", "tsmc", "euv", "hbm", "dram", "nand"],                        ["SOXS"]),     # Direxion Daily Semiconductor Bear 3x
    (["metal", "mining", "copper", "nickel", "aluminum", "steel",
      "rare earth", "lithium", "cobalt"],                                    ["SMN"]),      # ProShares UltraShort Basic Materials
    (["defense", "defence", "military", "weapon", "nato", "arms"],           ["SH"]),       # ProShares Short S&P 500 (broad short)
    (["shipping", "tanker", "freight", "vessel", "maritime"],                ["SH"]),
    (["china", "chinese", "beijing"],                                        ["YANG"]),     # Direxion Daily FTSE China Bear 3x
    (["treasury", "rate cut", "rate hike", "central bank", "yield",
      "bond", "bonds"],                                                      ["TBT"]),      # ProShares UltraShort 20+ Year Treasury
    (["gold", "safe haven"],                                                 ["GLL"]),      # ProShares UltraShort Gold
    (["wheat", "grain", "agriculture", "soybean", "corn", "food"],           ["SH"]),
    (["auto", "carmaker", "automaker"],                                      ["SH"]),
    (["bank", "financial"],                                                  ["SKF"]),      # ProShares UltraShort Financials
]


def _is_bad_ticker(ticker: str) -> bool:
    """Return True if the ticker is an index, benchmark, or otherwise unusable.

    Catches: known-bad symbols, foreign-exchange suffixes (.T .L .TO),
    index/special characters (^ = / space), empty strings, and tokens
    too long to be a realistic US listing (> 5 chars, with a narrow
    exception for 'ASML' and a handful of 4-letter tickers that are
    already US-listed).
    """
    t = ticker.strip().upper()
    if not t:
        return True
    if t in _BAD_TICKERS:
        return True
    # Foreign exchange suffixes: 8035.T, FM.TO, VOD.L, etc.
    if "." in t:
        return True
    # Index prefixes or Yahoo Finance special formatting
    if any(c in t for c in ["^", "=", " ", "/"]):
        return True
    # Anything longer than 5 chars is almost certainly not a US common
    # stock or ETF — US tickers are at most 5 chars (rare), and most are 1-4.
    if len(t) > 5:
        return True
    return False


def _clean_assets(assets: list, context: str = "") -> list:
    """Sanitize and backfill assets_to_watch from the LLM response.

    Steps:
    1. Normalise each entry to stripped uppercase.
    2. Remove entries that fail _is_bad_ticker().
    3. Deduplicate while preserving order.
    4. Backfill from _PROXY_MAP if fewer than 3 usable tickers remain.
    5. Return at most 5 tickers.
    """
    # 1. Normalise
    normalized = [t.strip().upper() for t in assets if isinstance(t, str) and t.strip()]
    # 2. Filter
    cleaned = [t for t in normalized if not _is_bad_ticker(t)]
    # 3. Deduplicate
    seen: set = set()
    deduped = []
    for t in cleaned:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    cleaned = deduped

    # 4. Backfill when too few tickers survived
    if len(cleaned) < 3 and context:
        ctx = context.lower()
        for keywords, proxies in _PROXY_MAP:
            if any(kw in ctx for kw in keywords):
                for proxy in proxies:
                    if proxy not in cleaned:
                        cleaned.append(proxy)
                    if len(cleaned) >= 3:
                        break
            if len(cleaned) >= 3:
                break

    # 5. Cap at 5
    return cleaned[:5]


def _backfill_losers(cleaned: list[str], context: str) -> list[str]:
    """Add inverse/short ETF proxies when the loser list is empty after sanitization.

    Only fires when cleaned is empty and context is non-empty.
    Returns the tickers with a "(proxy)" suffix so the UI/storage can distinguish
    fallback proxies from direct company tickers.
    """
    if cleaned or not context:
        return cleaned
    ctx = context.lower()
    for keywords, proxies in _LOSER_PROXY_MAP:
        if any(kw in ctx for kw in keywords):
            return [f"{p} (proxy)" for p in proxies]
    return cleaned


def _dedupe_ticker_overlap(
    beneficiaries: list[str], losers: list[str],
) -> tuple[list[str], list[str]]:
    """Ensure beneficiary_tickers and loser_tickers are disjoint.

    A ticker that appears in both lists is removed from the loser list —
    beneficiary wins by convention, since the beneficiary side is usually
    the stronger directional call from the prompt.  Proxy-suffixed losers
    ('SH (proxy)') are never matched against clean beneficiary tickers.
    """
    ben_set = {t.upper() for t in beneficiaries}
    new_losers = [
        t for t in losers
        if t.upper().split()[0] not in ben_set or "(proxy)" in t.lower()
    ]
    return beneficiaries, new_losers


# ---------------------------------------------------------------------------
# Model / prompt setup
# ---------------------------------------------------------------------------

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from prompts import SYSTEM_PROMPT, EVENT_ANALYSIS_PROMPT

_PLACEHOLDER = "your_api_key_here"
_DEFAULT_MODEL = "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# JSON extraction (handles messy, self-correcting model responses)
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict | None:
    """Extract the last valid JSON object from a messy model response.

    Handles all known failure modes:
    - Fenced blocks: ```json { ... } ``` or ``` { ... } ```
    - Extra prose before or after the JSON
    - Multiple JSON attempts (e.g. model self-corrects): returns the LAST
      valid one, because when Claude appends a revised block the last
      block is the intended answer.

    Returns None if no valid JSON object is found anywhere in the text.
    """
    candidates: list[dict] = []

    # Pass 1: try every fenced code block (```json ... ``` or ``` ... ```)
    for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", text):
        try:
            obj = json.loads(block.strip())
            if isinstance(obj, dict):
                candidates.append(obj)
        except json.JSONDecodeError:
            pass

    # Pass 2: scan the full text for any JSON objects, fenced or not.
    # raw_decode parses from each { it finds and correctly handles nested braces.
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        brace = text.find("{", idx)
        if brace == -1:
            break
        try:
            obj, end = decoder.raw_decode(text, brace)
            if isinstance(obj, dict):
                candidates.append(obj)
            idx = end
        except json.JSONDecodeError:
            idx = brace + 1

    # Return the last valid candidate — when the model self-corrects, the last
    # JSON block is the intended final answer.
    return candidates[-1] if candidates else None


# ---------------------------------------------------------------------------
# Strict schema normalization
# ---------------------------------------------------------------------------

# Strings that should be treated as absent/null regardless of where they
# appear.  Lowercase comparison, trimmed.
_NULL_LIKE: frozenset[str] = frozenset({
    "", "null", "none", "n/a", "na", "nil", "nan", "tbd", "tba",
    "unknown", "undetermined", "unclear", "to be determined",
    "not applicable", "no credible fx channel", "no fx channel",
    "not specified", "not available",
})

# Phrases that mark beneficiaries/losers as vague placeholders rather than
# concrete entities.  Rejected by ``_clean_entity_list``.
_VAGUE_ENTITY_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bvarious (companies|firms|entities|sectors|players)\b", re.I),
    re.compile(r"\bmultiple (companies|firms|entities|sectors|players)\b", re.I),
    re.compile(r"\bseveral (companies|firms|entities|sectors|players)\b", re.I),
    re.compile(r"\bthe market\b", re.I),
    re.compile(r"\bglobal markets?\b", re.I),
    re.compile(r"\ball investors\b", re.I),
    re.compile(r"^investors$", re.I),
    re.compile(r"\bdepends on (outcome|response|reaction)\b", re.I),
    re.compile(r"\b(tbd|to be determined)\b", re.I),
    re.compile(r"\bunknown\b", re.I),
    re.compile(r"^unclear( impact)?$", re.I),
    re.compile(r"^none$", re.I),
)

# Exact horizon enum expected by the contract.
_HORIZON_ENUM: frozenset[str] = frozenset({"weeks", "months", "quarters"})

# Confidence enum.
_CONFIDENCE_ENUM: frozenset[str] = frozenset({"low", "medium", "high"})


def _is_null_like(value: Any) -> bool:
    """Return True when ``value`` represents null/missing in any form."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _NULL_LIKE
    return False


def _clean_text(value: Any) -> str | None:
    """Return a stripped non-empty string, or None for null-like input."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped.lower() in _NULL_LIKE:
        return None
    return stripped


def _is_vague_entity(text: str) -> bool:
    """Return True when an entity string is a vague placeholder."""
    if not text or len(text.strip()) < 3:
        return True
    for pat in _VAGUE_ENTITY_PATTERNS:
        if pat.search(text):
            return True
    return False


def _clean_entity_list(raw: Any) -> list[str]:
    """Coerce a raw beneficiaries/losers field into a clean list of strings.

    - Accepts a list of strings; everything else collapses to [].
    - Strips each entry and drops null-like / vague placeholders.
    - Deduplicates while preserving order.
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or text.lower() in _NULL_LIKE:
            continue
        if _is_vague_entity(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _clean_transmission_chain(raw: Any) -> list[str]:
    """Coerce the transmission chain into a list of non-empty strings.

    - Accepts a list.  Strings are cleaned; dicts are flattened into a
      single string of their values; everything else is dropped.
    - Drops null-like entries.
    - Returns at most 6 entries to keep the UI compact.
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if text and text.lower() not in _NULL_LIKE:
                out.append(text)
        elif isinstance(item, dict):
            # Sometimes the model emits {"step": "..."} for each step.
            parts = [str(v).strip() for v in item.values() if v]
            joined = " — ".join(p for p in parts if p)
            if joined:
                out.append(joined)
        # Anything else (int, None, list) is skipped silently.
    return out[:6]


def _normalize_confidence(raw: Any) -> str:
    """Normalize confidence to low/medium/high (defaults to low)."""
    if not isinstance(raw, str):
        return "low"
    v = raw.strip().lower()
    # Strip common suffixes: "medium confidence", "low-medium", "medium."
    v = v.split()[0] if v else ""
    v = v.rstrip(".,;:")
    if v in _CONFIDENCE_ENUM:
        return v
    # Treat any fuzzy value as "low" — safer than fabricating medium.
    return "low"


def _normalize_if_persists(raw: Any) -> dict:
    """Sanitize the if_persists value from LLM output.

    Horizon is coerced to the weeks|months|quarters enum; anything else
    is dropped.  Empty/null-like fields are stripped.  Returns {} when
    no usable field remains.
    """
    if not isinstance(raw, dict):
        return {}

    # substitution
    sub = _clean_text(raw.get("substitution"))

    # delayed_winners / delayed_losers
    def _coerce_list(val: Any) -> list[str]:
        if not isinstance(val, list):
            return []
        return _clean_entity_list(val)

    winners = _coerce_list(raw.get("delayed_winners"))
    losers = _coerce_list(raw.get("delayed_losers"))

    # horizon — strict enum
    horizon_raw = raw.get("horizon")
    horizon = None
    if isinstance(horizon_raw, str):
        h = horizon_raw.strip().lower()
        h = h.split()[0] if h else ""
        # Allow a few near-synonyms for robustness
        _alias = {
            "week": "weeks", "weeks": "weeks",
            "month": "months", "months": "months",
            "quarter": "quarters", "quarters": "quarters",
            "q": "quarters", "q1": "quarters", "q2": "quarters",
        }
        if h in _HORIZON_ENUM:
            horizon = h
        elif h in _alias:
            horizon = _alias[h]

    out: dict = {}
    if sub:
        out["substitution"] = sub
    if winners:
        out["delayed_winners"] = winners
    if losers:
        out["delayed_losers"] = losers
    if horizon:
        out["horizon"] = horizon
    return out


def _normalize_currency_channel(raw: Any) -> dict:
    """Sanitize the currency_channel value from LLM output.

    Returns a dict with pair/mechanism/beneficiaries/squeezed, or {} if
    no credible FX channel exists.  Requires both pair and mechanism to
    be present and concrete for the whole section to be kept.
    """
    if not isinstance(raw, dict):
        return {}

    pair = _clean_text(raw.get("pair"))
    mechanism = _clean_text(raw.get("mechanism"))
    beneficiaries = _clean_text(raw.get("beneficiaries"))
    squeezed = _clean_text(raw.get("squeezed"))

    # Only return if at least pair + mechanism are present AND mechanism
    # is specific enough to be useful (>20 chars and not a placeholder).
    if not pair or not mechanism:
        return {}
    if len(mechanism) < 20:
        return {}

    out: dict = {"pair": pair, "mechanism": mechanism}
    if beneficiaries:
        out["beneficiaries"] = beneficiaries
    if squeezed:
        out["squeezed"] = squeezed
    return out


def _coerce_ticker_field(value: Any) -> list[str]:
    """Normalize a raw ticker field from LLM JSON into a list of strings.

    Handles: list, str, None, int, dict, and lists containing non-strings.
    Anything that isn't a string or a list of strings is dropped.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str) and item.strip()]
    # int, float, dict, bool, etc. — discard
    return []


# ---------------------------------------------------------------------------
# Weakness detection and degraded fallback
# ---------------------------------------------------------------------------

# Thresholds for declaring an output "too thin to pass through".  All three
# must hold simultaneously to trigger degradation — we want to tolerate
# short-but-specific outputs, not force verbosity for its own sake.
_DEGRADE_MIN_MECHANISM_CHARS = 40
_DEGRADE_MIN_WHAT_CHANGED_CHARS = 15


def _detect_weak_output(result: dict) -> str | None:
    """Return a reason string when ``result`` is too thin to be usable.

    The rule is intentionally conservative: only flag outputs that are
    simultaneously thin on mechanism AND lacking any structural content.
    """
    mech = result.get("mechanism_summary") or ""
    wc = result.get("what_changed") or ""
    chain = result.get("transmission_chain") or []
    ben = result.get("beneficiaries") or []
    los = result.get("losers") or []

    mech_thin = (
        not mech
        or len(mech.strip()) < _DEGRADE_MIN_MECHANISM_CHARS
        or "insufficient evidence" in mech.lower()
    )
    wc_thin = not wc or len(wc.strip()) < _DEGRADE_MIN_WHAT_CHANGED_CHARS
    no_chain = not isinstance(chain, list) or len(chain) < 2
    no_entities = len(ben) == 0 and len(los) == 0

    # All three structural signals must be missing — a thin mechanism with
    # a real transmission chain is still usable.
    if mech_thin and no_chain and (wc_thin or no_entities):
        if "insufficient evidence" in mech.lower():
            return "mechanism=insufficient_evidence + no_chain + no_entities"
        return "thin mechanism + no chain + no entities"
    return None


def _degraded_fallback(
    headline: str, stage: str, persistence: str, reason: str,
    preserved_tickers: list[str] | None = None,
) -> dict:
    """Return a clearly-labelled but still-useful analysis object.

    The fallback is different from ``_mock``:
      * It is called when the LLM *did* respond but the response was
        too thin to be trusted.
      * It keeps any usable tickers the sanitizer recovered, so the
        downstream market check still has something to work with.
      * It clears rich downstream sections (if_persists, currency_channel,
        transmission_chain) to avoid leaking stale templates.
      * It sets ``degraded: True`` so the UI/telegram bot can render a
        'low-quality analysis' badge.
      * ``is_mock`` still returns False — this is a real (if thin) LLM
        output, not a missing-API-key stub.
    """
    ctx = f"{headline}"
    tickers = preserved_tickers or []
    if not tickers:
        tickers = _clean_assets([], context=ctx)

    return {
        "what_changed": (
            f"Model returned a thin response for this headline ({reason}). "
            f"Confidence forced to low and structured sections cleared."
        ),
        "mechanism_summary": (
            "Insufficient evidence to identify a specific transmission "
            "mechanism from the model response. Downstream sections are "
            "intentionally empty to avoid showing stale templates."
        ),
        "beneficiaries": [],
        "losers": [],
        "beneficiary_tickers": tickers,
        "loser_tickers": [],
        "assets_to_watch": tickers,
        "confidence": "low",
        "transmission_chain": [],
        "if_persists": {},
        "currency_channel": {},
        "degraded": True,
        "validation_warnings": [f"degraded: {reason}"],
    }


# ---------------------------------------------------------------------------
# Contradiction-aware validation
# ---------------------------------------------------------------------------

def _validate_result(result: dict, stage: str) -> dict:
    """Apply contradiction-aware post-parse validation.

    Rules (each fires independently; warnings accumulate):
      1. mechanism_summary must be longer than 20 chars.
      2. At least one beneficiary_ticker must survive sanitization.
      3. anticipation stage forbids high confidence (downgraded to medium).
      4. 'insufficient evidence' in mechanism forces confidence to low.
      5. high confidence requires both beneficiary and loser tickers to be
         non-empty — otherwise downgraded to medium.
      6. high confidence requires a transmission chain with ≥3 steps.
      7. If mechanism is thin (<20 chars) but downstream rich sections
         (if_persists, currency_channel) are populated, clear those
         sections as incompatible with the thin mechanism.
      8. If beneficiaries and losers are both empty, confidence cannot
         exceed medium.
      9. beneficiary_tickers and loser_tickers must be disjoint — any
         overlap is removed from the loser side (done in analyze_event).

    The result is never rejected — warnings are collected in
    result["validation_warnings"].  The key is only added when at least
    one rule fires, so clean results stay uncluttered.
    """
    warnings: list[str] = []

    # Rule 1: mechanism_summary length floor
    summary = result.get("mechanism_summary", "")
    if not isinstance(summary, str) or len(summary.strip()) <= 20:
        warnings.append("mechanism_summary is too short or missing")

    # Rule 2: beneficiary ticker survival
    beneficiary_tickers = result.get("beneficiary_tickers", [])
    if not isinstance(beneficiary_tickers, list) or len(beneficiary_tickers) == 0:
        warnings.append("beneficiary_tickers is empty after sanitization")

    # Rule 3: anticipation + high confidence → downgrade
    if stage == "anticipation" and result.get("confidence") == "high":
        result["confidence"] = "medium"
        warnings.append("confidence downgraded high → medium (stage is anticipation)")

    # Rule 4: insufficient evidence → force low
    if isinstance(summary, str) and "insufficient evidence" in summary.lower():
        if result.get("confidence") != "low":
            result["confidence"] = "low"
            warnings.append("confidence forced to low (insufficient evidence in mechanism)")

    # Rule 5: high confidence needs both ticker lists populated
    loser_tickers = result.get("loser_tickers", [])
    if result.get("confidence") == "high" and (
        not beneficiary_tickers or not loser_tickers
    ):
        result["confidence"] = "medium"
        warnings.append(
            "confidence downgraded high → medium (missing beneficiary or loser tickers)"
        )

    # Rule 6: high confidence needs a real transmission chain
    chain = result.get("transmission_chain", [])
    if result.get("confidence") == "high" and (
        not isinstance(chain, list) or len(chain) < 3
    ):
        result["confidence"] = "medium"
        warnings.append(
            "confidence downgraded high → medium (transmission chain <3 steps)"
        )

    # Rule 7: thin mechanism + rich downstream → clear downstream
    if isinstance(summary, str) and len(summary.strip()) <= 20:
        if result.get("if_persists"):
            result["if_persists"] = {}
            warnings.append("if_persists cleared (incompatible with thin mechanism)")
        if result.get("currency_channel"):
            result["currency_channel"] = {}
            warnings.append("currency_channel cleared (incompatible with thin mechanism)")

    # Rule 8: both beneficiaries and losers empty → cap confidence at medium
    ben = result.get("beneficiaries", []) or []
    los = result.get("losers", []) or []
    if not ben and not los and result.get("confidence") == "high":
        result["confidence"] = "medium"
        warnings.append(
            "confidence downgraded high → medium (both beneficiaries and losers empty)"
        )

    if warnings:
        existing = result.get("validation_warnings", [])
        if not isinstance(existing, list):
            existing = []
        result["validation_warnings"] = existing + warnings

    return result


# ---------------------------------------------------------------------------
# Mock / is_mock helpers
# ---------------------------------------------------------------------------

def is_mock(analysis: dict) -> bool:
    """Return True if the analysis is a mock/fallback, not a real LLM result."""
    return "[mock:" in (analysis.get("what_changed") or "")


def _mock(reason: str) -> dict:
    """Return a clearly-labelled mock so the pipeline never crashes."""
    return {
        "what_changed": f"[mock: {reason}]",
        "mechanism_summary": f"[mock: {reason}]",
        "beneficiaries": ["[mock]"],
        "losers": ["[mock]"],
        "beneficiary_tickers": ["GLD"],
        "loser_tickers": ["USO"],
        "assets_to_watch": ["GLD", "USO"],
        "confidence": "low",
        "transmission_chain": [],
        "if_persists": {},
        "currency_channel": {},
    }


# ---------------------------------------------------------------------------
# Schema normalization entry point
# ---------------------------------------------------------------------------

def _normalize_schema(raw: dict, headline: str) -> dict:
    """Coerce a raw LLM dict into the strict analysis schema.

    Types, enums, and null-like filler are cleaned up here.  Ticker
    sanitization and contradiction validation are applied by the caller.
    """
    result: dict = {}

    result["what_changed"] = _clean_text(raw.get("what_changed")) or ""
    result["mechanism_summary"] = _clean_text(raw.get("mechanism_summary")) or ""

    result["beneficiaries"] = _clean_entity_list(raw.get("beneficiaries"))
    result["losers"] = _clean_entity_list(raw.get("losers"))

    result["transmission_chain"] = _clean_transmission_chain(
        raw.get("transmission_chain"),
    )
    result["confidence"] = _normalize_confidence(raw.get("confidence"))
    result["if_persists"] = _normalize_if_persists(raw.get("if_persists"))
    result["currency_channel"] = _normalize_currency_channel(
        raw.get("currency_channel"),
    )

    # Ticker lists stay as coerced strings here; the caller applies
    # _clean_assets + _backfill_losers + _dedupe_ticker_overlap so the
    # sanitizer context (headline + mechanism) is fresh.
    result["_raw_beneficiary_tickers"] = _coerce_ticker_field(
        raw.get("beneficiary_tickers"),
    )
    result["_raw_loser_tickers"] = _coerce_ticker_field(raw.get("loser_tickers"))

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_event(headline: str, stage: str, persistence: str,
                   event_context: str = "", model: str | None = None) -> dict:
    """Call the LLM and return a strict, validated analysis of the event.

    Falls back to a mock response if the key is missing or the call fails.
    Falls back to a degraded analysis object if the LLM returns a thin or
    unusable response.

    event_context: optional multi-source context string.  When provided it
    is injected into the prompt so the model can weigh corroboration,
    source reliability, and inter-source disagreement.

    model: Anthropic model ID to use. Defaults to ANTHROPIC_MODEL env var,
    then _DEFAULT_MODEL. Pass explicitly to A/B test in eval runs.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    model = model or os.getenv("ANTHROPIC_MODEL", _DEFAULT_MODEL)

    if not api_key or api_key == _PLACEHOLDER:
        print("[analyze_event] No API key found. Returning mock response.")
        print("  → Set ANTHROPIC_API_KEY in your .env file to get real analysis.\n")
        return _mock("no API key")

    prompt = EVENT_ANALYSIS_PROMPT.format(
        headline=headline,
        stage=stage,
        persistence=persistence,
        event_context=event_context,
    )

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        if not message.content:
            print("[analyze_event] API returned empty content list.")
            return _mock("empty API response")

        raw = message.content[0].text
        parsed = _extract_json(raw)

        if parsed is None:
            print("[analyze_event] Could not parse LLM response as JSON.")
            print(f"  → Raw response: {raw}\n")
            return _mock("JSON parse error")

        return _finalize_analysis(parsed, headline, stage, persistence)

    except ImportError:
        print("[analyze_event] 'anthropic' package not installed.")
        print("  → Run: pip install anthropic python-dotenv\n")
        return _mock("anthropic not installed")

    except Exception as e:
        print(f"[analyze_event] API call failed: {e}\n")
        return _mock(str(e))


def _finalize_analysis(
    parsed: dict, headline: str, stage: str, persistence: str,
) -> dict:
    """Take a parsed-but-raw LLM dict and produce the final analysis.

    This is the shared normalization pipeline used by both the live API
    path and the test/eval paths.  It guarantees the same strict output
    regardless of how ``parsed`` was obtained.

    Steps:
      1. Strict schema normalization (types, enums, null-like stripped).
      2. Ticker sanitization + inverse-proxy fallback + overlap dedupe.
      3. Weak-output detection → degraded fallback.
      4. Contradiction-aware validation.
    """
    normalized = _normalize_schema(parsed, headline=headline)

    context = f"{headline} {normalized.get('mechanism_summary', '')}"
    raw_ben = normalized.pop("_raw_beneficiary_tickers", [])
    raw_los = normalized.pop("_raw_loser_tickers", [])

    beneficiary_tickers = _clean_assets(raw_ben, context=context)
    # Losers: sanitize without long-proxy backfill, then add inverse
    # proxies only if nothing survived.
    loser_tickers = _clean_assets(raw_los, context="")
    loser_tickers = _backfill_losers(loser_tickers, context)

    # Guarantee the two lists are disjoint before downstream code sees them.
    beneficiary_tickers, loser_tickers = _dedupe_ticker_overlap(
        beneficiary_tickers, loser_tickers,
    )

    # Merge while preserving order and removing duplicates
    seen: set[str] = set()
    assets_to_watch: list[str] = []
    for t in beneficiary_tickers + loser_tickers:
        if t not in seen:
            seen.add(t)
            assets_to_watch.append(t)

    normalized["beneficiary_tickers"] = beneficiary_tickers
    normalized["loser_tickers"] = loser_tickers
    normalized["assets_to_watch"] = assets_to_watch

    # Weak-output detection → degraded fallback
    weak_reason = _detect_weak_output(normalized)
    if weak_reason is not None:
        return _degraded_fallback(
            headline, stage, persistence, weak_reason,
            preserved_tickers=beneficiary_tickers,
        )

    return _validate_result(normalized, stage)
