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

import dataclasses
import json
import logging
import os
import re
import time
from typing import Any, TypedDict

_log = logging.getLogger("second_order.analyze_event")


# ---------------------------------------------------------------------------
# AnalysisResult — canonical field registry for the analysis pipeline.
#
# Three field groups document the full lifecycle of an analysis dict:
#   LLM_CORE_FIELDS      — returned verbatim by analyze_event()
#   PERSISTED_OVERLAY_FIELDS — computed in routes/analyze.py, saved to DB
#   OVERLAY_FIELDS       — superset of PERSISTED_OVERLAY_FIELDS + ephemeral
#                          fields that are NOT persisted (historical_analogs)
#
# The TypedDict is intentionally total=False so partial dicts (stubs, mocks,
# test fixtures) remain valid without filling every field.
# ---------------------------------------------------------------------------

class AnalysisResult(TypedDict, total=False):
    # Core LLM output
    what_changed: str
    mechanism_summary: str
    beneficiaries: list
    losers: list
    beneficiary_tickers: list
    loser_tickers: list
    assets_to_watch: list
    confidence: str
    confidence_rationale: str
    counterfactual_check: dict
    actionability_check: dict
    transmission_chain: list
    transmission_path: list
    substitution_barriers: list
    counterforces: list
    adversarial_challenge: str
    horizon_checkpoints: dict
    mechanism_family: str
    hidden_mechanism: dict
    competing_thesis: dict
    monitor_plan: dict
    expected_first_order_channels: list
    expected_second_order_channels: list
    regime_conditioned_caveat: str
    if_persists: dict
    currency_channel: dict
    # Institutional research fields — ranked structured replacements for
    # the legacy "just a flat list of tickers" approach.  Optional: sanitizer
    # tolerates either a list of {symbol, rank, rationale} dicts or the
    # literal string "insufficient_evidence".  All three asset buckets get
    # merged back into ``assets_to_watch`` for backward compat.
    primary_assets: list
    secondary_assets: list
    hedge_or_signal_assets: list
    key_falsifiers: list
    minimum_proof_set: list
    # Validation / quality flags — populated by _validate_result and the
    # degraded fallback path.  Optional: only present when set.
    validation_warnings: list
    degraded: bool
    # Engine-level evidence-quality tier the event landed in.  Closed
    # set: "low_information" / "watch_only" / "actionable".  Stamped at
    # the end of ``_finalize_analysis`` (and on the degraded fallback
    # path) so consumers can branch on the field directly instead of
    # parsing the ``evidence_quality:`` tag from validation_warnings.
    quality_tier: str
    # Compact machine-readable failure-mode tags from
    # ``low_information_gate.QUALITY_WARNING_TAGS``.  Stamped only on
    # watch_only / low_information / degraded outputs; field absence
    # signals "no warnings" (clean actionable).
    quality_warnings: list
    # Traceability — list of structured source attributions composed by
    # ``evidence_sources.make_source`` and surfaced by various engine
    # producers (evidence_attribution, evidence_ladder,
    # reaction_function_divergence).  Top-level analysis dicts may
    # carry this field when an upstream producer attaches it; the
    # nested ``competing_thesis.evidence_sources`` is a separate read.
    evidence_sources: list
    # Overlay fields — computed post-LLM, persisted to DB
    policy_sensitivity: dict
    real_yield_context: dict
    policy_constraint: dict
    shock_decomposition: dict
    reaction_function_divergence: dict
    regime_snapshot: dict
    inventory_context: dict
    surprise_vs_anticipation: dict
    terms_of_trade: dict
    reserve_stress: dict
    narrative_divergence: dict
    credit_regime: dict
    credit_transmission: dict
    # Ephemeral — computed but NOT persisted
    historical_analogs: list
    cross_asset_confirmation: dict  # compute-on-read from shock_decomposition + thesis
    sector_passthrough: dict        # compute-on-read from tickers + mechanism + shock


# Fields returned directly by analyze_event() (LLM output layer).
LLM_CORE_FIELDS: tuple[str, ...] = (
    "what_changed", "mechanism_summary", "beneficiaries", "losers",
    "beneficiary_tickers", "loser_tickers", "assets_to_watch", "confidence",
    "confidence_rationale", "counterfactual_check", "actionability_check",
    "transmission_chain", "transmission_path", "substitution_barriers",
    "counterforces", "adversarial_challenge", "horizon_checkpoints",
    "mechanism_family", "hidden_mechanism", "competing_thesis",
    "monitor_plan", "expected_first_order_channels",
    "expected_second_order_channels", "regime_conditioned_caveat",
    "if_persists", "currency_channel",
    # Institutional research fields — ranked asset buckets, flat falsifier
    # list, flat minimum-proof list.  Stored alongside the legacy ticker
    # lists and merged back into ``assets_to_watch`` by _finalize_analysis.
    "primary_assets", "secondary_assets", "hedge_or_signal_assets",
    "key_falsifiers", "minimum_proof_set",
)

# Overlay fields that are computed in routes/analyze.py AND saved to the DB.
# Keep this in sync with save_event's INSERT columns and _persist_event.
PERSISTED_OVERLAY_FIELDS: tuple[str, ...] = (
    "policy_sensitivity", "real_yield_context", "policy_constraint",
    "shock_decomposition", "reaction_function_divergence", "regime_snapshot",
    "inventory_context", "surprise_vs_anticipation", "terms_of_trade",
    "reserve_stress", "narrative_divergence", "credit_regime",
    "credit_transmission",
)

# All overlay fields (persisted + ephemeral).
OVERLAY_FIELDS: tuple[str, ...] = PERSISTED_OVERLAY_FIELDS + (
    "historical_analogs",
    "cross_asset_confirmation",
    "sector_passthrough",
)


# Default shape per LLM core field — used by build_analysis_dict so a missing
# field never becomes None and breaks downstream string / list ops.
_LLM_CORE_DEFAULTS: dict[str, object] = {
    "what_changed":        "",
    "mechanism_summary":   "",
    "beneficiaries":       [],
    "losers":              [],
    "beneficiary_tickers": [],
    "loser_tickers":       [],
    "assets_to_watch":     [],
    "confidence":          "low",
    "confidence_rationale":   "",
    "counterfactual_check":   {},
    "actionability_check":    {},
    "transmission_chain":     [],
    "transmission_path":      [],
    "substitution_barriers":  [],
    "counterforces":          [],
    "adversarial_challenge":  "",
    "horizon_checkpoints":    {},
    "mechanism_family":                 "none",
    "hidden_mechanism":                 {},
    "competing_thesis":                 {},
    "monitor_plan":                     {},
    "expected_first_order_channels":    [],
    "expected_second_order_channels":   [],
    "regime_conditioned_caveat":        "",
    "if_persists":            {},
    "currency_channel":       {},
    "primary_assets":             [],
    "secondary_assets":           [],
    "hedge_or_signal_assets":     [],
    "key_falsifiers":             [],
    "minimum_proof_set":          [],
}


def build_analysis_dict(
    source: dict,
    overlay_overrides: dict | None = None,
) -> dict:
    """Assemble a full analysis dict from a source dict + optional overlay overrides.

    Emits every field in ``LLM_CORE_FIELDS`` and ``PERSISTED_OVERLAY_FIELDS``.
    Missing LLM-core fields fall back to ``_LLM_CORE_DEFAULTS``; missing overlay
    fields fall back to ``{}``.  Overlay values from ``overlay_overrides`` take
    precedence over ``source`` — used by the cache-reconstruction path to
    substitute freshly-recomputed overlays into an otherwise cached event.

    This is the single-source-of-truth assembler shared by the persistence /
    save path and the cache reconstruction path.  New fields added to the
    field registry automatically flow through both without further edits.
    """
    overrides = overlay_overrides or {}
    result: dict = {}
    for f in LLM_CORE_FIELDS:
        result[f] = source.get(f, _LLM_CORE_DEFAULTS.get(f))
    for f in PERSISTED_OVERLAY_FIELDS:
        if f in overrides:
            result[f] = overrides[f]
        else:
            raw = source.get(f)
            result[f] = raw if isinstance(raw, dict) else {}

    # Compute-on-read: derive confidence_rationale and counterfactual_check
    # from the assembled fields so cached / frozen events get a current
    # read without requiring DB columns for the derived shape.  Inputs
    # (mechanism_summary, key_falsifiers, hidden_mechanism, etc.) are
    # all persisted, so the recompute matches what _finalize_analysis
    # produced when the event was originally analyzed.
    from low_information_gate import (
        compose_actionability_check,
        compose_confidence_rationale,
        compose_counterfactual_check,
    )
    result["confidence_rationale"] = compose_confidence_rationale(result)
    result["counterfactual_check"] = compose_counterfactual_check(result)
    result["actionability_check"] = compose_actionability_check(result)
    return result


# ---------------------------------------------------------------------------
# AnalyzeEventInput — structured input for the analysis pipeline.
#
# Replaces the growing positional/keyword arg list on analyze_event() so that
# adding new context (e.g. portfolio_context, geopolitical_backdrop) is a
# one-field change here, not a signature change that cascades to every caller
# and mock.
#
# Backward compat: analyze_event() still accepts the old positional string
# args so that legacy callers (app.py, eval.py, main.py, test_analyze_retry)
# continue to work without modification.
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class AnalyzeEventInput:
    """All context required to run one analysis cycle through the LLM."""
    headline: str
    stage: str
    persistence: str
    event_context: str = ""
    macro_context: str = ""
    model: str | None = None
    provider: str | None = None

# ---------------------------------------------------------------------------
# Retry configuration for transient LLM provider failures
# ---------------------------------------------------------------------------
# Only OverloadedError (529), RateLimitError (429), ServiceUnavailableError
# (503), APITimeoutError, and APIConnectionError are retried.  Hard failures
# (auth, validation, parse) are never retried.
#
# Bounded: 2 retries = 3 total attempts.  Backoff: 1s, 2s (geometric).
# Total worst-case wall time: ~3s of sleep + 3 × API timeout.

RETRY_MAX_ATTEMPTS: int = 3
RETRY_BACKOFF_BASE: float = 1.0  # seconds; doubles each retry

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


def _clean_assets(
    assets: list,
    context: str = "",
    *,
    skip_proxy_backfill: bool = False,
) -> list:
    """Sanitize and backfill assets_to_watch from the LLM response.

    When ``skip_proxy_backfill`` is True the thematic-ETF padding from
    ``_PROXY_MAP`` is suppressed — used when the analysis is too thin or
    too blended to justify broad-sector proxies.
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

    # 4. Backfill when too few tickers survived (unless explicitly skipped).
    if not skip_proxy_backfill and len(cleaned) < 3 and context:
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
_API_KEY_PLACEHOLDERS = {
    _PLACEHOLDER,
    "your_anthropic_api_key_here",
    "your_openai_api_key_here",
    "placeholder",
    "changeme",
}
_DEFAULT_PROVIDER = "anthropic"
_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_PROVIDERS = {"anthropic", "openai"}


def _env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _selected_provider(input_provider: str | None = None) -> str:
    provider = (input_provider or _env_value("ANALYSIS_PROVIDER") or _DEFAULT_PROVIDER)
    provider = provider.strip().lower()
    return provider if provider in _PROVIDERS else _DEFAULT_PROVIDER


def _selected_model(input_model: str | None = None, provider: str | None = None) -> str:
    if input_model:
        model = input_model.strip()
        if model:
            return model
    selected_provider = _selected_provider(provider)
    if selected_provider == "openai":
        return _env_value("OPENAI_MODEL") or _DEFAULT_OPENAI_MODEL
    return _env_value("ANTHROPIC_MODEL") or _DEFAULT_MODEL


def _has_real_api_key(api_key: str) -> bool:
    key = (api_key or "").strip()
    return bool(key and key.lower() not in _API_KEY_PLACEHOLDERS)


def _api_key_for_provider(provider: str) -> str:
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY", "")
    return os.getenv("ANTHROPIC_API_KEY", "")


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


# ---------------------------------------------------------------------------
# Structured mechanism fields
# ---------------------------------------------------------------------------

# Enum values for transmission_path[*].channel.  Extra values passed by the
# model are preserved as "unclassified" — we don't reject unknowns because
# the prompt examples may drift; we just don't promise semantics for them.
_TRANSMISSION_CHANNELS = frozenset({
    "policy_gate", "supply", "demand", "pricing_power", "capital_flow",
    "substitution", "regulatory", "sanction", "tariff", "rate_transmission",
})

# Optional ``timing`` enum on transmission_path hop dicts.  Mirrors the
# discriminator timing enum but carries the slower 5-20d / 20d+ buckets
# because a chain hop describes when the next leg of the cascade plays
# out, not just the immediate resolver.
_TRANSMISSION_HOP_TIMING_ENUM: frozenset[str] = frozenset(
    {"1d", "1-5d", "5-20d", "20d+"},
)

# Vague hop patterns — phrases the LLM reaches for when it cannot
# commit to a concrete causal step.  Hops matching any of these in
# ``action`` / ``hop`` / ``expected_market_effect`` are dropped by
# ``_clean_transmission_path`` before validation.
_VAGUE_HOP_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bmarkets?\s+(react|respond|move|adjust)\b", re.I),
    re.compile(r"\binvestors?\s+(react|respond|price|adjust|reposition)\b", re.I),
    re.compile(r"\bripple\s+effects?\b", re.I),
    re.compile(r"\bmarket\s+participants?\b", re.I),
    re.compile(r"\b(broader|general)\s+market\s+(reaction|reacts|moves)\b", re.I),
    re.compile(r"\bstakeholders?\s+(react|respond)\b", re.I),
    re.compile(r"\bsentiment\s+(shifts?|changes?)\b", re.I),
    re.compile(r"\bimpacts\s+global\s+trade\b", re.I),
)


def _is_vague_hop(text: str) -> bool:
    """Return True when a hop / action / effect line is a generic
    placeholder rather than a concrete causal step."""
    if not text:
        return True
    for pat in _VAGUE_HOP_PATTERNS:
        if pat.search(text):
            return True
    return False


# Asset / proxy hint tokens: presence in the LAST hop's
# expected_market_effect satisfies the "ends in an asset/proxy
# implication" rule.  Cheap heuristic — the strict-validator pairs it
# with a ticker-like token check so a last-hop effect is accepted
# either by naming a ticker or by referencing a market proxy noun.
_ASSET_PROXY_TOKENS: tuple[str, ...] = (
    "equit", "spread", "yield", "credit", "etf", "share", "stock",
    "bond", "tnote", "treasury", "futures", "swap", "vix", "vol",
    "fx", "currenc", "dollar", "rate ", "rates", "basket",
    "premium", "discount", "margin",
)


def _hop_text(item: dict) -> str:
    """Return the hop's action text, accepting either ``action`` (new
    structured field) or the legacy ``hop`` field.  Stripped, never
    None — empty string when neither is set."""
    for key in ("action", "hop"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _references_asset(text: str) -> bool:
    """True when ``text`` contains an asset/proxy hint or a
    ticker-like token (1-5 uppercase letters)."""
    if not isinstance(text, str) or not text:
        return False
    low = text.lower()
    if any(tok in low for tok in _ASSET_PROXY_TOKENS):
        return True
    for raw in re.split(r"[\s,;:/().\[\]]+", text):
        token = raw.strip("'\"")
        if 1 <= len(token) <= 5 and token.isalpha() and token.isupper():
            return True
    return False


def _is_valid_transmission_chain(path: Any) -> bool:
    """Strict structural validity check used by the low-information gate.

    A chain is valid when:
      * it has at least 2 hops;
      * every hop carries actor + action (or legacy hop) + channel
        (canonical, not "unclassified") + expected_market_effect, and
        none of those text fields are vague-hop placeholders;
      * the last hop's expected_market_effect names an asset / ticker /
        market-proxy token — the chain has to land somewhere tradable.

    Returned bool — does NOT mutate the path.  Sanitizers may have
    already dropped invalid hops; the validator simply tells the gate
    whether what survived is finance-real.
    """
    if not isinstance(path, list) or len(path) < 2:
        return False

    for hop in path:
        if not isinstance(hop, dict):
            return False
        actor = (hop.get("actor") or "").strip() if isinstance(hop.get("actor"), str) else ""
        if not actor or _is_vague_hop(actor):
            return False
        action = _hop_text(hop)
        if not action or _is_vague_hop(action):
            return False
        channel = hop.get("channel")
        if not isinstance(channel, str) or channel not in _TRANSMISSION_CHANNELS:
            return False
        effect = hop.get("expected_market_effect")
        if not isinstance(effect, str) or not effect.strip() or _is_vague_hop(effect):
            return False

    last = path[-1]
    last_effect = (last.get("expected_market_effect") or "").strip() \
        if isinstance(last.get("expected_market_effect"), str) else ""
    if not _references_asset(last_effect):
        return False

    return True

# Enum values for substitution_barriers[*].kind.
_SUBSTITUTION_BARRIER_KINDS = frozenset({
    "physical_sole_source", "regulatory", "capital_intensity",
    "skill_scarcity", "contractual_lockin", "demand_inelastic",
    "geographic", "capacity",
})

_SEVERITY_ENUM = frozenset({"low", "medium", "high"})
_LIKELIHOOD_ENUM = frozenset({"low", "medium", "high"})

_ADVERSARIAL_PLACEHOLDER: str = "No credible challenge identified."


# Enum values for horizon_checkpoints.timing_profile.  fast_shock = first
# moves inside 1d; delayed_pass_through = 1d quiet, material 5-20d reaction;
# slow_grind = builds over 20d+ as physical / contract / balance-sheet
# transmission plays out; unknown = LLM declined to commit or inputs too thin.
_TIMING_PROFILE_ENUM = frozenset({
    "fast_shock", "delayed_pass_through", "slow_grind", "unknown",
})

# Canonical horizons for checkpoint entries.  Fixed at 1d / 5d / 20d to stay
# aligned with the existing revisit_snapshot cadence and the ticker return
# windows surfaced everywhere else in the app.
_CANONICAL_HORIZONS: tuple[str, ...] = ("1d", "5d", "20d")


def _clean_string_list(raw: Any, cap: int = 4) -> list[str]:
    """Return a deduped list of non-empty trimmed strings, capped at ``cap``."""
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
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= cap:
            break
    return out


def _clean_horizon_checkpoints(raw: Any) -> dict:
    """Coerce horizon_checkpoints into a stable ``{timing_profile, horizons}`` dict.

    Output shape:
        {
          "timing_profile": "fast_shock" | "delayed_pass_through" | "slow_grind" | "unknown",
          "horizons": [
            {
              "horizon": "1d" | "5d" | "20d",
              "expected":     list[str],
              "confirms_if":  list[str],
              "falsifies_if": list[str],
            },
            ...
          ],
        }

    The horizons list is canonicalized to always contain entries for 1d / 5d /
    20d in that order.  Missing horizons from the LLM fill in with empty
    string lists so the downstream renderer never needs to branch on "did the
    model emit this horizon?".  Extra horizons from the LLM (e.g. "60d") are
    dropped — the cadence is deliberately fixed.

    Returns ``{"timing_profile": "unknown", "horizons": [...]}`` when the raw
    input is absent or unparseable.
    """
    timing: str = "unknown"
    raw_horizons: list = []

    if isinstance(raw, dict):
        timing = _normalize_enum(
            raw.get("timing_profile"), _TIMING_PROFILE_ENUM, "unknown",
        )
        hz = raw.get("horizons")
        if isinstance(hz, list):
            raw_horizons = hz
        elif isinstance(hz, dict):
            # Tolerate a dict keyed by horizon label — flatten into the list form.
            for key, payload in hz.items():
                if isinstance(payload, dict):
                    item = dict(payload)
                    item.setdefault("horizon", str(key))
                    raw_horizons.append(item)

    # Index raw horizons by their label so missing canonical ones can be filled.
    by_label: dict[str, dict] = {}
    for item in raw_horizons:
        if not isinstance(item, dict):
            continue
        label = str(item.get("horizon") or "").strip().lower()
        if label not in _CANONICAL_HORIZONS:
            continue
        by_label[label] = {
            "horizon":      label,
            "expected":     _clean_string_list(item.get("expected"), cap=4),
            "confirms_if":  _clean_string_list(item.get("confirms_if"), cap=4),
            "falsifies_if": _clean_string_list(item.get("falsifies_if"), cap=4),
        }

    horizons = []
    for label in _CANONICAL_HORIZONS:
        horizons.append(
            by_label.get(label, {
                "horizon":      label,
                "expected":     [],
                "confirms_if":  [],
                "falsifies_if": [],
            })
        )

    return {"timing_profile": timing, "horizons": horizons}


# ---------------------------------------------------------------------------
# Mechanism family + expected channel packs
# ---------------------------------------------------------------------------

from mechanism_family import (  # noqa: E402
    FAMILY_IDS as _MECH_FAMILY_IDS,
    CHANNEL_IDS as _MECH_CHANNEL_IDS,
    classify_family as _classify_family_fallback,
    get_default_channel_pack as _default_channel_pack,
    normalize_family_alias as _normalize_family_alias,
)

_MECH_FAMILY_ENUM: frozenset[str] = frozenset(_MECH_FAMILY_IDS)
_MECH_CHANNEL_ENUM: frozenset[str] = frozenset(_MECH_CHANNEL_IDS)

_REGIME_CAVEAT_PLACEHOLDER: str = "No regime-conditioned caveat."


def _clean_mechanism_family(raw: Any) -> str:
    """Coerce a mechanism_family string to one of _MECH_FAMILY_IDS.

    Unknown / null-like values fall back to ``"none"``.  Tolerates
    punctuation, case, compound forms ("tariff/sanction" → "tariff"),
    and LLM-emitted synonyms via ``normalize_family_alias``
    ("antitrust" → "regulation", "chips_act" → "industrial_policy").
    """
    if not isinstance(raw, str):
        return "none"
    v = raw.strip().lower()
    # Split compounds on /, ,, + or — keep the first usable token.
    for sep in ("/", ",", "+", "|", "&"):
        if sep in v:
            v = v.split(sep)[0].strip()
    # Strip trailing punctuation.
    while v and not v[-1].isalpha() and not v[-1] == "_":
        v = v[:-1]
    if not v or v in _NULL_LIKE:
        return "none"
    if v in _MECH_FAMILY_ENUM:
        return v
    # Alias pass — map synonym → canonical id before giving up.
    aliased = _normalize_family_alias(v)
    if aliased and aliased in _MECH_FAMILY_ENUM:
        return aliased
    return "none"


def _clean_channel_list(raw: Any, *, cap: int = 4) -> list[str]:
    """Return a deduped list of channel ids, preserving input order.

    Unknown tokens are dropped silently.  Case-insensitive match.
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        v = item.strip().lower()
        if v in _MECH_CHANNEL_ENUM and v not in seen:
            seen.add(v)
            out.append(v)
            if len(out) >= cap:
                break
    return out


def _clean_regime_caveat(raw: Any) -> str:
    """Coerce a regime_conditioned_caveat to a single non-empty string.

    Null-like filler collapses to empty.  The canonical placeholder
    ``"No regime-conditioned caveat."`` is preserved verbatim.
    """
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    if not text or text.lower() in _NULL_LIKE:
        return ""
    return text


def _resolve_mechanism_family(
    raw_family: Any,
    headline: str,
    mechanism_text: str,
) -> str:
    """Take the LLM's family, fall back to the keyword classifier if empty.

    Preserves a committed valid LLM family (including alias-normalised
    ones — see ``_clean_mechanism_family``).  Only falls through to
    ``classify_family`` when the LLM says "none" or emits something
    unparseable.  This is the *first-pass* resolver; a richer
    structured fallback runs at the end of ``_normalize_schema`` via
    ``_post_parse_family_fallback``, which can consult transmission
    chains, asset buckets, and hidden_mechanism fields that aren't
    available yet at this call site.
    """
    family = _clean_mechanism_family(raw_family)
    if family != "none":
        return family
    return _classify_family_fallback(headline, mechanism_text)


# Mapping from forensic-bottleneck primitives to the most natural
# mechanism family.  These are strong priors — an ``export_control_carveout``
# event with no LLM family commitment is overwhelmingly a sanction; a
# ``reserve_bop_stress`` bottleneck is external_balance.  Kept
# conservative: only bottlenecks with a single dominant family are listed.
_BOTTLENECK_TO_FAMILY: dict[str, str] = {
    "reserve_bop_stress":      "external_balance",
    "refinancing_channel":     "bank_stress",
    "shipping_chokepoint":     "commodity_squeeze",
    "sole_source_physical":    "supply_shock",
    "export_control_carveout": "sanction",
    "input_cost_passthrough":  "labor_inflation",
    "capacity_bottleneck":     "supply_shock",
}

# Asset-bucket signature markers.  An asset list concentrated in these
# names is a strong hint toward the family even when keyword matching
# turns up nothing.  Each set is used as a *dominance* signal — the
# bucket must be mostly-composed of the markers, not merely contain one.
_EM_STRESS_MARKERS:      frozenset[str] = frozenset({
    "EMB", "EEM", "EWZ", "EWY", "EEMA", "EMLC", "CEMB",
})
_BANK_STRESS_MARKERS:    frozenset[str] = frozenset({
    "KRE", "KBE", "XLF", "HYG", "JNK",
})
_SEMI_SUBSIDY_MARKERS:   frozenset[str] = frozenset({
    "SMH", "SOXX", "TSM", "INTC", "ITA", "XAR", "ICLN", "KWEB",
})


def _post_parse_family_fallback(
    normalized: dict,
    headline: str,
) -> str:
    """Reduce false ``mechanism_family="none"`` using post-parse evidence.

    Runs at the tail of ``_normalize_schema`` — every upstream sanitizer
    has finished, so the function sees the full transmission chain,
    asset buckets, and hidden_mechanism block.  Delegates to
    ``family_inference.resolve_effective_family`` so save-time and
    read-time fallbacks share a single rule set — the two paths can't
    drift apart on which evidence implies which family.
    """
    current = normalized.get("mechanism_family") or "none"
    if current != "none":
        return current

    from family_inference import resolve_effective_family
    candidate = dict(normalized)
    if headline and not candidate.get("headline"):
        candidate["headline"] = headline
    shared = resolve_effective_family(candidate)
    return shared if shared in _MECH_FAMILY_ENUM else "none"


def _resolve_channel_packs(
    family: str,
    raw_first: Any,
    raw_second: Any,
) -> tuple[list[str], list[str]]:
    """Return (first_order, second_order) channel lists for the family.

    LLM values win when valid.  When a side is empty / missing, the
    canonical pack for the family is used so the UI always has a
    non-trivial expected-channel read even on thin LLM output.
    """
    first = _clean_channel_list(raw_first)
    second = _clean_channel_list(raw_second)
    if not first and not second:
        default = _default_channel_pack(family)
        return default["first"], default["second"]
    # Respect partial commits: fill the empty side from the canonical pack.
    if not first:
        first = _default_channel_pack(family)["first"]
    if not second:
        second = _default_channel_pack(family)["second"]
    # De-dupe: a channel in first-order should not also appear in second-order.
    second = [c for c in second if c not in first]
    return first, second


def _normalize_enum(raw: Any, allowed: frozenset[str], default: str) -> str:
    """Coerce a raw enum value to one of the allowed tokens (lower-cased).

    Unknown values fall back to ``default``.  Tolerates trailing punctuation
    ("medium.", "HIGH!"), embedded modifiers ("low-medium" → "low"), and case.
    """
    if not isinstance(raw, str):
        return default
    v = raw.strip().lower()
    v = v.split("-")[0].split()[0] if v else ""
    # Strip any trailing non-letter characters (punctuation, ! ? emoji, etc.).
    while v and not v[-1].isalpha():
        v = v[:-1]
    return v if v in allowed else default


def _clean_transmission_path(raw: Any) -> list[dict]:
    """Coerce transmission_path into a list of structured hop dicts.

    Each preserved hop carries the legacy ``{hop, channel, actor}``
    triplet PLUS, when the LLM provided them, the new optional
    ``action`` / ``expected_market_effect`` / ``timing`` fields the
    structural-chain contract adds.  Adding new optional keys inside
    an existing dict is a non-breaking change for callers that only
    read the legacy three.

    Drops:
      * non-dict entries (legacy strings can't carry the structured
        fields the contract now requires);
      * dicts without a usable ``hop`` / ``action`` text;
      * hops whose action / hop / expected_market_effect text is a
        vague-hop placeholder ("markets react", "investors price
        risk", "ripple effects") — these aren't real causal steps.
    Capped at 6 entries to keep the UI compact.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if not text or text.lower() in _NULL_LIKE or _is_vague_hop(text):
                continue
            out.append({
                "hop": text, "channel": "unclassified", "actor": "",
            })
            continue
        if not isinstance(item, dict):
            continue

        hop = str(item.get("hop") or "").strip()
        action_raw = str(item.get("action") or "").strip()
        # Accept ``action`` as an alias for ``hop`` when the LLM moved
        # to the new structured field; carry both keys forward when the
        # LLM emitted them distinctly so consumers can pick either.
        if not hop and action_raw:
            hop = action_raw
        if not hop or hop.lower() in _NULL_LIKE:
            continue
        if _is_vague_hop(hop) or (action_raw and _is_vague_hop(action_raw)):
            continue

        channel_raw = str(item.get("channel") or "").strip().lower()
        channel = (
            channel_raw if channel_raw in _TRANSMISSION_CHANNELS
            else "unclassified"
        )
        actor = str(item.get("actor") or "").strip()
        cleaned: dict = {"hop": hop, "channel": channel, "actor": actor}

        if action_raw:
            cleaned["action"] = action_raw

        effect_raw = item.get("expected_market_effect")
        if isinstance(effect_raw, str):
            effect = effect_raw.strip()
            if effect and effect.lower() not in _NULL_LIKE \
                    and not _is_vague_hop(effect):
                cleaned["expected_market_effect"] = effect

        timing_raw = item.get("timing")
        if isinstance(timing_raw, str):
            t = timing_raw.strip().lower()
            if t in _TRANSMISSION_HOP_TIMING_ENUM:
                cleaned["timing"] = t

        out.append(cleaned)
    return out[:6]


def _clean_substitution_barriers(raw: Any) -> list[dict]:
    """Coerce substitution_barriers into a list of {barrier, kind, severity} dicts.

    Strings are lifted into ``{barrier, kind='unclassified', severity='medium'}``.
    Capped at 5 entries.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if not text or text.lower() in _NULL_LIKE:
                continue
            out.append({"barrier": text, "kind": "unclassified",
                        "severity": "medium"})
        elif isinstance(item, dict):
            barrier = str(item.get("barrier") or "").strip()
            if not barrier or barrier.lower() in _NULL_LIKE:
                continue
            kind_raw = str(item.get("kind") or "").strip().lower()
            kind = kind_raw if kind_raw in _SUBSTITUTION_BARRIER_KINDS else "unclassified"
            severity = _normalize_enum(item.get("severity"), _SEVERITY_ENUM, "medium")
            out.append({"barrier": barrier, "kind": kind, "severity": severity})
    return out[:5]


# Generic-uncertainty patterns the counterforces / blockers discipline
# must reject — none of these are concrete enough for a desk to watch
# in price, filings, or policy feeds.  Substring match (case-insensitive)
# against the ``force`` text.
_GENERIC_UNCERTAINTY_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bgeopolitical\s+(tensions?|risks?|uncertainty)\b", re.I),
    re.compile(r"\bmacro\s+(headwinds?|uncertainty|risks?)\b", re.I),
    re.compile(r"\bmarket\s+(volatility|uncertainty|conditions?)\b", re.I),
    re.compile(r"\beconomic\s+(uncertainty|conditions?|risks?)\b", re.I),
    re.compile(r"\bbroader\s+risk[-\s]?off\b", re.I),
    re.compile(r"\bchanging\s+conditions?\b", re.I),
    re.compile(r"\brisk\s+factors?\b", re.I),
    re.compile(r"\b(uncertainty|risk)\s+(rises?|increases?|grows?)\b", re.I),
    re.compile(r"\bsentiment\s+(shifts?|fades?)\b", re.I),
)

# Counterforce kind discriminator — "counterforce" (default) is a force
# that materially weakens the thesis after it transmits; "blocker" is a
# force that interrupts the transmission chain itself.  Keeps both
# shapes in the existing top-level ``counterforces`` list so we add
# optional fields only inside an existing structure.
_COUNTERFORCE_KIND_ENUM: frozenset[str] = frozenset(
    {"counterforce", "blocker"},
)


def _is_generic_uncertainty_force(text: str) -> bool:
    """True when a counterforce / blocker line is a generic-uncertainty
    placeholder rather than a concrete blocker a desk can watch."""
    if not text:
        return True
    for pat in _GENERIC_UNCERTAINTY_PATTERNS:
        if pat.search(text):
            return True
    return False


def _clean_counterforces(raw: Any) -> list[dict]:
    """Coerce counterforces / blockers into a list of structured dicts.

    Each preserved entry carries the legacy ``{force, actor, likelihood}``
    triplet PLUS, when the LLM provided them, the optional ``kind``
    discriminator (``counterforce`` | ``blocker``) and ``chain_hop``
    pointer (free text describing which transmission_path step the
    blocker hits).  Adding these as optional keys inside the existing
    dict shape is non-breaking for callers that only read the legacy
    three.

    Drops:
      * non-string / null-like ``force`` text;
      * generic-uncertainty placeholders ("macro headwinds",
        "geopolitical tensions", "broader risk-off") — these can't be
        watched in market terms.
    Capped at 6 entries (room for 3 counterforces + 3 blockers).
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if not text or text.lower() in _NULL_LIKE:
                continue
            if _is_generic_uncertainty_force(text):
                continue
            out.append({"force": text, "actor": "", "likelihood": "medium"})
            continue
        if not isinstance(item, dict):
            continue

        force = str(item.get("force") or "").strip()
        if not force or force.lower() in _NULL_LIKE:
            continue
        if _is_generic_uncertainty_force(force):
            continue

        actor = str(item.get("actor") or "").strip()
        likelihood = _normalize_enum(
            item.get("likelihood"), _LIKELIHOOD_ENUM, "medium",
        )
        cleaned: dict = {
            "force": force, "actor": actor, "likelihood": likelihood,
        }
        kind_raw = item.get("kind")
        if isinstance(kind_raw, str):
            k = kind_raw.strip().lower()
            if k in _COUNTERFORCE_KIND_ENUM:
                cleaned["kind"] = k

        chain_hop = item.get("chain_hop")
        if isinstance(chain_hop, str) and chain_hop.strip():
            cleaned["chain_hop"] = chain_hop.strip()[:160]

        out.append(cleaned)
    return out[:6]


def _clean_adversarial_challenge(raw: Any) -> str:
    """Coerce adversarial_challenge to a single non-empty string.

    Null-like fillers → empty string.  The canonical placeholder
    ``"No credible challenge identified."`` is passed through verbatim.
    """
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    if not text:
        return ""
    if text.lower() in _NULL_LIKE:
        return ""
    return text


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


_PROOF_CHANNEL_ENUM: frozenset[str] = frozenset({
    "rates", "fx", "commodities", "vol", "credit", "equities",
})

_PROOF_TIMING_ENUM: frozenset[str] = frozenset({
    "1d", "1-5d", "5-20d", "20d+",
})

# critical_breakpoints are FAST falsifiers only — slower falsifiers
# live in horizon_checkpoints.falsifies_if.
_BREAKPOINT_TIMING_ENUM: frozenset[str] = frozenset({"1d", "1-5d"})


def _clean_proof_entry(raw: Any, *, require_threshold: bool,
                        timing_enum: frozenset[str]) -> dict | None:
    """Normalise a single minimum-proof / breakpoint entry.

    Expects ``{observation|signal, channel, threshold, timing}``.  Returns
    None when the entry is too thin to be useful (missing observation or
    channel), so the caller can filter without emitting an empty row.
    """
    if not isinstance(raw, dict):
        return None
    obs = _clean_text(raw.get("observation") or raw.get("signal"))
    if not obs:
        return None
    channel_raw = raw.get("channel")
    channel = None
    if isinstance(channel_raw, str):
        c = channel_raw.strip().lower()
        if c in _PROOF_CHANNEL_ENUM:
            channel = c
    if not channel:
        return None
    timing_raw = raw.get("timing")
    timing = None
    if isinstance(timing_raw, str):
        t = timing_raw.strip().lower()
        if t in timing_enum:
            timing = t
    threshold = _clean_text(raw.get("threshold"))
    if require_threshold and not threshold:
        # No numeric/operational bar → too thin to score against.
        return None
    key_label = "signal" if "signal" in raw and "observation" not in raw else "observation"
    out = {key_label: obs[:200], "channel": channel}
    if threshold:
        out["threshold"] = threshold[:160]
    if timing:
        out["timing"] = timing
    # Optional back-reference to a critical_breakpoints entry — lets a
    # proof / falsifier item declare which breakpoint it tests so the
    # UI / audit can render the link both ways.  Reference tokens
    # like ``"critical_breakpoints:0"`` are legitimately short, so
    # this passthrough skips the generic-signal length floor; just
    # require non-empty + non-null-like.  Reject obvious prose
    # filler ("market sentiment changes" etc.) by checking the term
    # set, not the length.
    link = raw.get("linked_breakpoint")
    if isinstance(link, str):
        text = link.strip()
        if text and text.lower() not in _NULL_LIKE:
            try:
                from mechanism_family import _GENERIC_SIGNAL_TERMS
                terms = _GENERIC_SIGNAL_TERMS
            except Exception:
                terms = ()
            low = text.lower()
            if not any(term in low for term in terms):
                out["linked_breakpoint"] = text[:160]
    return out


def _clean_breakpoint_entry(raw: Any) -> dict | None:
    """Normalise a critical_breakpoints entry — the existing
    ``{signal/observation, channel, threshold, timing}`` shape PLUS
    four optional fields the user contract requires:

      * ``condition``                 — the conditional trigger
        ("if WCS-WTI discount widens >3pp within 5d").
      * ``threshold_or_observation``  — the concrete numeric / event
        observation that resolves the condition.
      * ``why_it_changes_thesis``     — short rationale tying the
        breakpoint to the thesis flip.
      * ``linked_proof_or_falsifier`` — back-reference to a proof or
        falsifier item ("minimum_proof_set:0", "key_falsifiers:1",
        or a substring of the linked item's text).

    Generic strings ("market sentiment changes", "narrative shifts",
    etc.) are rejected via the shared ``_is_generic_signal`` gate.
    A breakpoint with any of the new fields supplied AND generic
    content gets dropped entirely — the user contract is explicit
    that breakpoints must be concrete and observable.
    """
    base = _clean_proof_entry(
        raw, require_threshold=False, timing_enum=_BREAKPOINT_TIMING_ENUM,
    )
    if base is None:
        return None
    if not isinstance(raw, dict):
        return base

    try:
        from mechanism_family import _is_generic_signal
    except Exception:
        def _is_generic_signal(s):  # type: ignore[no-redef]
            return False

    def _clean_specific(value: Any) -> str | None:
        """Return the cleaned string OR None (skipped, value missing
        / not a string).  Returns sentinel empty string when the
        field is present but generic — caller drops the whole entry."""
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text or text.lower() in _NULL_LIKE:
            return None
        if _is_generic_signal(text):
            return ""
        return text[:240]

    out = dict(base)
    has_optional = False
    for field in (
        "condition",
        "threshold_or_observation",
        "why_it_changes_thesis",
    ):
        cleaned = _clean_specific(raw.get(field))
        if cleaned == "":
            return None
        if cleaned is not None:
            out[field] = cleaned
            has_optional = True

    # ``linked_proof_or_falsifier`` is a back-reference, not prose —
    # short tokens like ``"minimum_proof_set:0"`` are legitimate and
    # would trip the generic-signal length floor.  Skip the generic
    # check; just require non-empty + non-null-like.
    link_raw = raw.get("linked_proof_or_falsifier")
    if isinstance(link_raw, str):
        link_text = link_raw.strip()
        if link_text and link_text.lower() not in _NULL_LIKE:
            out["linked_proof_or_falsifier"] = link_text[:160]
            has_optional = True

    if not has_optional:
        return base
    return out


def _clean_optional_evidence_entry(raw: Any) -> dict | None:
    """Normalise an optional-confirming-evidence entry.

    Only observation + channel are required — these are strengtheners,
    not validation gates, so a threshold or timing isn't required.
    """
    if not isinstance(raw, dict):
        return None
    obs = _clean_text(raw.get("observation"))
    if not obs:
        return None
    channel_raw = raw.get("channel")
    if not isinstance(channel_raw, str):
        return None
    c = channel_raw.strip().lower()
    if c not in _PROOF_CHANNEL_ENUM:
        return None
    return {"observation": obs[:200], "channel": c}


# Source-quality enums for ``hidden_mechanism.source_quality``.  The
# sanitizer validates LLM-emitted values against these closed sets;
# unknown tokens collapse the offending field rather than smuggling
# arbitrary text into a downstream consumer.
_SOURCE_TYPE_ENUM: frozenset[str] = frozenset({
    "official_release", "policy_action", "data_print",
    "reported_disruption", "analyst_view", "secondhand",
    "rumor", "speculation",
})

_SOURCE_SPECIFICITY_ENUM: frozenset[str] = frozenset({"low", "medium", "high"})

_SOURCE_UNCERTAINTY_ENUM: frozenset[str] = frozenset({"low", "medium", "high"})

# Lowercase keyword sets used by ``_infer_source_quality`` when the
# LLM doesn't emit a source_quality block.  Anchored to the
# headline / what_changed prose: high-specificity verbs name a
# concrete instrument; low-specificity verbs hedge.
_HIGH_SPECIFICITY_MARKERS: tuple[str, ...] = (
    "announces", "announced", "issued", "issues",
    "signs", "signed", "ratified", "ratifies",
    "filed", "files", "published", "publishes", "release",
    "released", "approves", "approved", "rejects", "rejected",
    "vetoes", "vetoed", "imposes", "imposed", "lifts", "lifted",
    "raises", "raised", "cuts", "cut by",
    "decree", "executive order", "fomc statement",
    "cpi prints", "ppi prints", "nfp", "data print",
    "earnings beat", "earnings miss", "guides", "guidance",
)

_LOW_SPECIFICITY_MARKERS: tuple[str, ...] = (
    "rumor", "rumored", "reportedly", "anonymous sources",
    "sources say", "sources said", "reported to be",
    "may be considering", "could potentially", "speculation",
    "speculated", "speculating", "hint", "hints at",
    "suggest that", "suggests that", "suggesting",
    "weighing", "considering whether", "exploring whether",
    "no formal announcement", "denied", "denies",
)


def _infer_source_quality(
    headline: Any, what_changed: Any,
) -> dict[str, str]:
    """Cheap keyword-based source-quality inference.

    Reads only the headline + ``what_changed`` text and returns the
    four canonical keys.  When neither high- nor low-specificity
    markers match, falls back to medium / medium / ``analyst_view``
    — the neutral midpoint a desk would assign to an unmarked report.
    """
    parts: list[str] = []
    for v in (headline, what_changed):
        if isinstance(v, str):
            parts.append(v)
    blob = " ".join(parts).lower()
    if not blob.strip():
        return {
            "source_type":          "analyst_view",
            "specificity":          "medium",
            "uncertainty_level":    "medium",
            "evidence_limitations": "",
        }

    has_high = any(marker in blob for marker in _HIGH_SPECIFICITY_MARKERS)
    has_low  = any(marker in blob for marker in _LOW_SPECIFICITY_MARKERS)

    if has_low and not has_high:
        return {
            "source_type":          "rumor",
            "specificity":          "low",
            "uncertainty_level":    "high",
            "evidence_limitations":
                "Headline relies on unconfirmed reports / speculation; "
                "no concrete actor or instrument named.",
        }
    if has_high and not has_low:
        return {
            "source_type":          "official_release",
            "specificity":          "high",
            "uncertainty_level":    "low",
            "evidence_limitations": "",
        }
    return {
        "source_type":          "analyst_view",
        "specificity":          "medium",
        "uncertainty_level":    "medium",
        "evidence_limitations": "",
    }


def _clean_source_quality(raw: Any) -> dict:
    """Sanitize the optional ``hidden_mechanism.source_quality`` block.

    Required keys: ``source_type``, ``specificity``, ``uncertainty_level``
    — each validated against the closed enums above.  Optional:
    ``evidence_limitations`` (free text, length-capped).  Returns
    ``{}`` when the required-field set can't be assembled.
    """
    if not isinstance(raw, dict):
        return {}
    src = raw.get("source_type")
    if not isinstance(src, str) or src.strip().lower() not in _SOURCE_TYPE_ENUM:
        return {}
    spec = raw.get("specificity")
    if not isinstance(spec, str) or spec.strip().lower() not in _SOURCE_SPECIFICITY_ENUM:
        return {}
    unc = raw.get("uncertainty_level")
    if not isinstance(unc, str) or unc.strip().lower() not in _SOURCE_UNCERTAINTY_ENUM:
        return {}

    out: dict = {
        "source_type":       src.strip().lower(),
        "specificity":       spec.strip().lower(),
        "uncertainty_level": unc.strip().lower(),
    }
    limits_raw = raw.get("evidence_limitations")
    if isinstance(limits_raw, str):
        text = limits_raw.strip()
        if text and text.lower() not in _NULL_LIKE:
            out["evidence_limitations"] = text[:240]
    return out


# Regime-domain enum for ``hidden_mechanism.regime_caveats[*].domain``.
# Closed set: only the macro regimes the thesis can hinge on.  When the
# LLM emits an unknown domain we drop the field rather than guess.
_REGIME_DOMAIN_ENUM: frozenset[str] = frozenset({
    "inflation", "rates", "credit", "fx", "liquidity",
})

# Generic-uncertainty patterns that disqualify a regime caveat — the
# caveat must name a CONCRETE condition, not a placeholder.  Reuses
# the same shapes the mechanism / counterforce gates already reject.
_REGIME_CAVEAT_VAGUE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bgeneral\s+macro(\s+conditions?)?\b", re.I),
    re.compile(r"\bbroader\s+(market|economy)\s+conditions?\b", re.I),
    re.compile(r"\bmarket\s+(volatility|conditions?)\b", re.I),
    re.compile(r"\beconomic\s+(uncertainty|conditions?)\b", re.I),
    re.compile(r"\b(macro|policy|geopolitical)\s+uncertainty\b", re.I),
    re.compile(r"\brisk\s+factors?\b", re.I),
    re.compile(r"\bsentiment\s+(shifts?|fades?)\b", re.I),
    re.compile(r"\bdepends?\s+on\s+(outcome|response|reaction)\b", re.I),
)


def _clean_regime_caveats(raw: Any) -> list[dict]:
    """Sanitize ``hidden_mechanism.regime_caveats``.

    Each entry is a dict with the three required fields:
      * ``condition``           — the regime state the thesis depends on
      * ``effect_on_thesis``    — how that condition modifies the read
      * ``evidence_to_revisit`` — what observable change would force
                                  re-reading the thesis

    Plus an OPTIONAL ``domain`` field (one of inflation / rates /
    credit / fx / liquidity).  Capped at 3 entries; vague placeholders
    are dropped (the contract requires concrete language anchored to a
    macro regime, not generic "broader market conditions").
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        condition = _clean_text(item.get("condition"))
        effect    = _clean_text(item.get("effect_on_thesis"))
        evidence  = _clean_text(item.get("evidence_to_revisit"))
        if not (condition and effect and evidence):
            continue
        # Vague-text rejection — applies to all three required fields.
        if any(
            any(p.search(text) for p in _REGIME_CAVEAT_VAGUE_PATTERNS)
            for text in (condition, effect, evidence)
        ):
            continue
        cleaned: dict = {
            "condition":           condition[:200],
            "effect_on_thesis":    effect[:200],
            "evidence_to_revisit": evidence[:200],
        }
        domain_raw = item.get("domain")
        if isinstance(domain_raw, str):
            d = domain_raw.strip().lower()
            if d in _REGIME_DOMAIN_ENUM:
                cleaned["domain"] = d
        out.append(cleaned)
        if len(out) >= 3:
            break
    return out


def _clean_hidden_mechanism(raw: Any, valid_tickers: set[str]) -> dict:
    """Sanitize the hidden_mechanism block from LLM output.

    Enforces the three taxonomy enums (bottleneck_type / transmission_type
    / channel_domain) against ``mechanism_family``'s registries — invalid
    values fall back to ``"none"`` rather than polluting downstream.  The
    forensic_note is length-capped and null-like placeholders are stripped.
    asset_rationales is filtered to tickers that actually appear in the
    event's beneficiary / loser lists so the LLM can't smuggle in extra
    tickers via this field.

    Also normalises the proof / breakpoints / regime_dependency /
    substitution_escape_path sub-fields:
      * minimum_proof_set   — 2-4 entries, observation/channel/threshold/timing
      * optional_confirming — 0-3 entries, observation/channel only
      * critical_breakpoints — 1-3 entries, timing restricted to 1d / 1-5d
      * regime_dependency / substitution_escape_path — single-line strings

    Returns ``{}`` when nothing usable remains (missing or all-invalid).
    """
    if not isinstance(raw, dict):
        return {}

    # Lazy import so the analyzer module stays importable even if the
    # taxonomy module is partially broken on upgrade.
    from mechanism_family import (
        BOTTLENECK_IDS, TRANSMISSION_TYPE_IDS, CHANNEL_DOMAIN_IDS,
    )

    def _enum_or_none(value: Any, valid: tuple[str, ...]) -> str:
        if isinstance(value, str):
            v = value.strip().lower().replace(" ", "_").replace("-", "_")
            if v in valid:
                return v
        return "none"

    bottleneck   = _enum_or_none(raw.get("bottleneck_type"),   BOTTLENECK_IDS)
    transmission = _enum_or_none(raw.get("transmission_type"), TRANSMISSION_TYPE_IDS)
    channel_dom  = _enum_or_none(raw.get("channel_domain"),    CHANNEL_DOMAIN_IDS)

    # forensic_note — short, concrete sentence.  Placeholder string kept
    # verbatim; null-like filler dropped.
    note_raw = raw.get("forensic_note")
    forensic_note = ""
    if isinstance(note_raw, str):
        text = note_raw.strip()
        if text and text.lower() not in _NULL_LIKE:
            # Hard cap at 200 chars so a model that runs long doesn't
            # blow past the UI budget.
            forensic_note = text[:200]

    # asset_rationales — filter keys to the allowed ticker universe so
    # the LLM can't introduce new tickers through this channel.  Values
    # are _clean_text'd so null-like filler is stripped.
    rationales_raw = raw.get("asset_rationales")
    asset_rationales: dict[str, str] = {}
    if isinstance(rationales_raw, dict):
        for key, val in rationales_raw.items():
            if not isinstance(key, str) or not isinstance(val, str):
                continue
            sym = key.strip().upper()
            if not sym or sym not in valid_tickers:
                continue
            cleaned = _clean_text(val)
            if not cleaned:
                continue
            # One-line discipline: hard-cap per-rationale at 240 chars.
            asset_rationales[sym] = cleaned[:240]

    # --- minimum_proof_set — must-see signals ---
    proof_raw = raw.get("minimum_proof_set")
    minimum_proof_set: list[dict] = []
    if isinstance(proof_raw, list):
        for item in proof_raw:
            entry = _clean_proof_entry(
                item, require_threshold=False, timing_enum=_PROOF_TIMING_ENUM,
            )
            if entry is not None:
                minimum_proof_set.append(entry)
        # Cap at 4 entries — the MUST-SEE list is meant to be minimal.
        minimum_proof_set = minimum_proof_set[:4]

    # --- optional_confirming_evidence — strengtheners, not gates ---
    optional_raw = raw.get("optional_confirming_evidence")
    optional_evidence: list[dict] = []
    if isinstance(optional_raw, list):
        for item in optional_raw:
            entry = _clean_optional_evidence_entry(item)
            if entry is not None:
                optional_evidence.append(entry)
        optional_evidence = optional_evidence[:3]

    # --- critical_breakpoints — FAST falsifiers only ---
    # ``_clean_breakpoint_entry`` extends the legacy shape with the
    # optional {condition, threshold_or_observation, why_it_changes_thesis,
    # linked_proof_or_falsifier} fields and rejects entries with
    # generic content on those fields.
    break_raw = raw.get("critical_breakpoints")
    critical_breakpoints: list[dict] = []
    if isinstance(break_raw, list):
        for item in break_raw:
            entry = _clean_breakpoint_entry(item)
            if entry is not None:
                critical_breakpoints.append(entry)
        critical_breakpoints = critical_breakpoints[:3]

    # --- regime_dependency / substitution_escape_path — single-line ---
    def _clean_one_liner(value: Any, cap: int = 200) -> str:
        if not isinstance(value, str):
            return ""
        text = value.strip()
        if not text or text.lower() in _NULL_LIKE:
            return ""
        return text[:cap]

    regime_dependency        = _clean_one_liner(raw.get("regime_dependency"))
    substitution_escape_path = _clean_one_liner(raw.get("substitution_escape_path"))

    # --- regime_caveats — structured list of regime conditioning ---
    # Optional sub-field: 1-3 entries, each carrying ``condition``,
    # ``effect_on_thesis``, ``evidence_to_revisit`` (the three required
    # fields) plus an optional ``domain`` enum.  Adding inside the
    # already-optional ``hidden_mechanism`` block keeps the response
    # shape stable — no new top-level field, no new DB column.
    regime_caveats = _clean_regime_caveats(raw.get("regime_caveats"))

    # --- source_quality — describes the headline / report itself ---
    # Optional dict naming source_type / specificity / uncertainty_level
    # / evidence_limitations.  Lives inside hidden_mechanism so we add
    # a sub-field, not a new top-level key.  The tier classifier reads
    # specificity to cap low-specificity headlines at watch_only.
    source_quality = _clean_source_quality(raw.get("source_quality"))

    # If nothing substantive remains, return an empty dict so the UI
    # renders the field as "not available" rather than an empty-shell
    # block with all "none" values.
    all_none = (
        bottleneck == "none"
        and transmission == "none"
        and channel_dom == "none"
        and not forensic_note
        and not asset_rationales
        and not minimum_proof_set
        and not optional_evidence
        and not critical_breakpoints
        and not regime_dependency
        and not substitution_escape_path
        and not regime_caveats
        and not source_quality
    )
    if all_none:
        return {}

    out: dict = {
        "bottleneck_type":   bottleneck,
        "transmission_type": transmission,
        "channel_domain":    channel_dom,
    }
    if forensic_note:
        out["forensic_note"] = forensic_note
    if asset_rationales:
        out["asset_rationales"] = asset_rationales
    if minimum_proof_set:
        out["minimum_proof_set"] = minimum_proof_set
    if optional_evidence:
        out["optional_confirming_evidence"] = optional_evidence
    if critical_breakpoints:
        out["critical_breakpoints"] = critical_breakpoints
    if regime_dependency:
        out["regime_dependency"] = regime_dependency
    if substitution_escape_path:
        out["substitution_escape_path"] = substitution_escape_path
    if regime_caveats:
        out["regime_caveats"] = regime_caveats
    if source_quality:
        out["source_quality"] = source_quality
    return out


_DISCRIMINATOR_TIMING_ENUM: frozenset[str] = frozenset({"1d", "1-5d"})


def _clean_evidence_list(raw: Any) -> list[dict]:
    """Normalise a list of {observation, channel} evidence entries.

    Drops entries without both a concrete observation AND a valid channel
    token.  Caps at 3 — more than that and the model pads.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        obs = _clean_text(item.get("observation"))
        if not obs:
            continue
        channel_raw = item.get("channel")
        if not isinstance(channel_raw, str):
            continue
        c = channel_raw.strip().lower()
        if c not in _PROOF_CHANNEL_ENUM:
            continue
        out.append({"observation": obs[:200], "channel": c})
    return out[:3]


def _clean_discriminator(raw: Any) -> dict:
    """Normalise a competing_thesis.discriminator entry.

    Requires observation + channel + outcome_if_primary +
    outcome_if_alternative — if any is missing or thin, returns {}.
    Also rejects:
      * a vague observation ("markets may react differently")
      * vague outcomes ("outcome depends on response")
      * outcomes that are reworded duplicates (incompatible outcomes
        are the whole point — two hedges saying the same thing aren't
        a discriminator).

    Timing is optional but, if present, must be "1d" or "1-5d"
    (slower resolutions aren't discriminators).
    """
    if not isinstance(raw, dict):
        return {}
    obs = _clean_text(raw.get("observation"))
    if_primary = _clean_text(raw.get("outcome_if_primary"))
    if_alt     = _clean_text(raw.get("outcome_if_alternative"))
    channel_raw = raw.get("channel")
    if not (obs and if_primary and if_alt and isinstance(channel_raw, str)):
        return {}
    if _is_vague_thesis(obs):
        return {}
    if _is_vague_thesis(if_primary) or _is_vague_thesis(if_alt):
        return {}
    if not _alt_materially_distinct(if_primary, if_alt):
        return {}
    c = channel_raw.strip().lower()
    if c not in _PROOF_CHANNEL_ENUM:
        return {}
    out: dict = {
        "observation":            obs[:240],
        "channel":                c,
        "outcome_if_primary":     if_primary[:240],
        "outcome_if_alternative": if_alt[:240],
    }
    timing_raw = raw.get("timing")
    if isinstance(timing_raw, str):
        t = timing_raw.strip().lower()
        if t in _DISCRIMINATOR_TIMING_ENUM:
            out["timing"] = t
    return out


def _clean_first_decisive_tell(raw: Any) -> dict:
    """Normalise monitor_plan.first_decisive_tell.

    Requires observation + channel + what_it_means.  Missing any of
    the three returns {} so the monitor-plan block doesn't render a
    tell with nothing to say.  The tell is always single-day by
    definition, so we don't accept a timing override.
    """
    if not isinstance(raw, dict):
        return {}
    obs = _clean_text(raw.get("observation"))
    meaning = _clean_text(raw.get("what_it_means"))
    channel_raw = raw.get("channel")
    if not (obs and meaning and isinstance(channel_raw, str)):
        return {}
    c = channel_raw.strip().lower()
    if c not in _PROOF_CHANNEL_ENUM:
        return {}
    return {
        "observation":   obs[:200],
        "channel":       c,
        "what_it_means": meaning[:160],
        "timing":        "1d",
    }


def _clean_no_call_signal(raw: Any) -> dict | None:
    """Normalise a single no_call_signals entry."""
    if not isinstance(raw, dict):
        return None
    obs = _clean_text(raw.get("observation"))
    why = _clean_text(raw.get("why_no_call"))
    channel_raw = raw.get("channel")
    if not (obs and why and isinstance(channel_raw, str)):
        return None
    c = channel_raw.strip().lower()
    if c not in _PROOF_CHANNEL_ENUM:
        return None
    return {
        "observation": obs[:200],
        "channel":     c,
        "why_no_call": why[:180],
    }


def _clean_monitor_plan(raw: Any) -> dict:
    """Sanitize the monitor_plan block from LLM output.

    Preserves only the two NET-NEW fields the monitor-plan view adds
    beyond horizon_checkpoints / competing_thesis / hidden_mechanism:
    a single-object first_decisive_tell and a small no_call_signals
    list.  Returns {} when both collapse.
    """
    if not isinstance(raw, dict):
        return {}
    tell = _clean_first_decisive_tell(raw.get("first_decisive_tell"))

    no_call_raw = raw.get("no_call_signals")
    no_call: list[dict] = []
    if isinstance(no_call_raw, list):
        for item in no_call_raw:
            entry = _clean_no_call_signal(item)
            if entry is not None:
                no_call.append(entry)
        no_call = no_call[:3]

    if not tell and not no_call:
        return {}

    out: dict = {}
    if tell:
        out["first_decisive_tell"] = tell
    if no_call:
        out["no_call_signals"] = no_call
    return out


# Phrases that mark a competing-thesis line (alternative_thesis or a
# discriminator observation/outcome) as a generic placeholder rather
# than a real, falsifiable claim.  Anchored to the kinds of hedges the
# model reaches for when it can't commit — "markets may react
# differently", "outcome depends", "could go either way".
_VAGUE_THESIS_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bmarkets?\s+(may|might|could)\s+react\b", re.I),
    re.compile(r"\bcould\s+go\s+either\s+way\b", re.I),
    re.compile(r"\boutcome\s+(may|might|could)\s+(vary|differ)\b", re.I),
    re.compile(r"\b(results?|reaction)\s+(may|might|could)\s+differ\b", re.I),
    re.compile(r"\bdepends?\s+on\s+(outcome|response|reaction|conditions?)\b", re.I),
    re.compile(r"\b(broader|general)\s+market\s+reaction\b", re.I),
    re.compile(r"\b(macro|policy|geopolitical)\s+uncertainty\b", re.I),
    re.compile(r"\brisk[-\s]?(on|off)\b", re.I),
    re.compile(r"\bvolatility\s+(may|might|could)\b", re.I),
    re.compile(r"\bsentiment\s+(shifts?|changes?)\b", re.I),
)


def _is_vague_thesis(text: str) -> bool:
    """Return True when a thesis or discriminator line is a generic
    hedge rather than a concrete, falsifiable claim.

    Used by the competing_thesis sanitizer to drop alternatives like
    "markets may react differently" and discriminator wording like
    "outcome depends on market response".
    """
    if not text:
        return True
    for pat in _VAGUE_THESIS_PATTERNS:
        if pat.search(text):
            return True
    return False


def _content_tokens(text: str) -> set[str]:
    """Return the set of meaningful content tokens in ``text``.

    Tokens are lowercase words of length >= 4, which strips the
    grammatical glue ('the', 'and', 'with') that would otherwise
    inflate overlap between two unrelated theses.
    """
    return {w for w in re.split(r"\W+", text.lower()) if len(w) >= 4}


def _alt_materially_distinct(primary: str, alternative: str) -> bool:
    """Return False when alternative_thesis is a near-clone of primary.

    Three-stage filter: exact match / prefix overlap on the normalized
    string, then a content-token Jaccard test against the primary so a
    rewording that swaps connectives but keeps every meaningful noun is
    rejected.  Real "materially distinct" enforcement still lives in
    the prompt; the sanitizer just blocks the obvious failures.
    """
    na = " ".join(primary.lower().split())
    nb = " ".join(alternative.lower().split())
    if not nb or na == nb:
        return False
    if na.startswith(nb) or nb.startswith(na):
        return False

    p_t = _content_tokens(primary)
    a_t = _content_tokens(alternative)
    if a_t and p_t:
        # If almost every meaningful word in the alternative also
        # appears in the primary, the alternative is just a reworded
        # primary — not a different mechanism.
        if len(a_t & p_t) / len(a_t) >= 0.85:
            return False
    return True


# Timing enum reused for first/second-order effect windows — same
# four-token vocabulary the proof / breakpoint / discriminator
# entries already use.
_WAVE_TIMING_ENUM: frozenset[str] = frozenset(
    {"1d", "1-5d", "5-20d", "20d+"},
)


def _is_vague_wave_text(text: str) -> bool:
    """Combined vague-text check used by the first/second-order
    sanitizers — covers both the thesis-line shapes ('markets may
    react', 'sentiment shifts') and the hop-line shapes ('markets
    react', 'investors price risk', 'ripple effects')."""
    return _is_vague_thesis(text) or _is_vague_hop(text)


def _clean_first_order_effect(raw: Any) -> dict:
    """Normalise the optional ``first_order_effect`` sub-field.

    Required: ``description`` (non-empty, not vague).  Optional:
    ``channel`` (must be in the canonical channel enum) and
    ``expected_window`` (must be in the timing enum).  Returns ``{}``
    when ``description`` is missing or vague — first-order claims must
    be concrete.
    """
    if not isinstance(raw, dict):
        return {}
    description = _clean_text(raw.get("description"))
    if not description or _is_vague_wave_text(description):
        return {}
    out: dict = {"description": description[:240]}
    channel_raw = raw.get("channel")
    if isinstance(channel_raw, str):
        c = channel_raw.strip().lower()
        if c in _PROOF_CHANNEL_ENUM:
            out["channel"] = c
    window_raw = raw.get("expected_window")
    if isinstance(window_raw, str):
        w = window_raw.strip().lower()
        if w in _WAVE_TIMING_ENUM:
            out["expected_window"] = w
    return out


def _clean_second_order_effects(raw: Any) -> list[dict]:
    """Normalise the optional ``second_order_effects`` list.

    Each entry MUST carry ``trigger`` (the first-order outcome that
    sets it off), ``intermediate_channel`` (the named route the
    cascade travels — without it, the second-order claim skips the
    transmission step and is dropped), ``affected_actor`` (named
    entity / ticker / market the cascade lands on), and ``timing``
    (one of 1d / 1-5d / 5-20d / 20d+).  Vague text on any of those
    fields drops the entry.

    Capped at 3 entries.  The ``intermediate_channel`` rejection rule
    is the core discipline: a second-order effect without a named
    intermediate channel is just a first-order claim with extra
    distance, not a real cascade.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        trigger    = _clean_text(item.get("trigger"))
        channel    = _clean_text(item.get("intermediate_channel"))
        actor      = _clean_text(item.get("affected_actor"))
        timing_raw = item.get("timing")
        timing = (
            timing_raw.strip().lower()
            if isinstance(timing_raw, str) else ""
        )
        if not (trigger and channel and actor):
            continue
        if timing not in _WAVE_TIMING_ENUM:
            continue
        if (
            _is_vague_wave_text(trigger)
            or _is_vague_wave_text(channel)
            or _is_vague_wave_text(actor)
        ):
            continue
        out.append({
            "trigger":              trigger[:240],
            "intermediate_channel": channel[:160],
            "affected_actor":       actor[:160],
            "timing":               timing,
        })
        if len(out) >= 3:
            break
    return out


def _infer_thesis_timing(
    stage: Any,
    persistence: Any,
    family: Any = None,
    subtype: Any = None,
) -> dict:
    """Derive a four-field thesis_timing dict from stage + persistence
    (+ family / subtype hints).

    Stage drives the reaction window: ``anticipation`` waits longer
    (5-20d) because the event hasn't happened; ``realized`` /
    ``surprise`` reacts on day one.  Persistence drives the
    follow-through and stale-after windows.  Family carries small
    overrides for fast-shock vs slow-grind cases.

    Always returns the full four-key dict — callers can ``_clean``
    the output to validate the enum tokens.
    """
    s = (stage or "").strip().lower() if isinstance(stage, str) else ""
    p = (persistence or "").strip().lower() if isinstance(persistence, str) else ""
    f = (family or "").strip().lower() if isinstance(family, str) else ""
    sub = (subtype or "").strip().lower() if isinstance(subtype, str) else ""

    # Reaction window — stage is the primary driver.
    if s == "anticipation":
        reaction = "5-20d"
    elif s in ("realized", "surprise"):
        reaction = "1d"
    else:
        reaction = "1-5d"

    # Family-specific overrides on the realized/surprise leg.  Slow-
    # grind families push the reaction out to 5-20d even when the
    # event has already happened; fast-shock families compress it.
    if s != "anticipation":
        if f in (
            "industrial_policy", "labor_inflation",
            "external_balance", "fiscal_issuance",
        ):
            reaction = "5-20d"
        elif f in (
            "policy_surprise", "sanction", "supply_shock",
            "supply_normalization", "bank_stress",
            "commodity_squeeze", "regulation",
        ):
            reaction = "1d"

    # Follow-through and stale_after — persistence is the primary
    # driver.  Structural events compound; one-off events fade.
    if p == "structural":
        follow_through = "5-20d"
        stale_after = "20d+"
    elif p in ("medium", "moderate"):
        follow_through = "1-5d"
        stale_after = "5-20d"
    elif p in ("one_off", "low", "ephemeral", "short"):
        follow_through = "1-5d"
        stale_after = "1-5d"
    else:
        follow_through = "1-5d"
        stale_after = "5-20d"

    rationale_bits: list[str] = []
    rationale_bits.append(s or "stage=unknown")
    rationale_bits.append(p or "persistence=unknown")
    if f and f != "none":
        rationale_bits.append(f"family={f}")
    if sub:
        rationale_bits.append(f"subtype={sub}")
    rationale = " + ".join(rationale_bits)

    return {
        "expected_reaction_window": reaction,
        "follow_through_window":    follow_through,
        "stale_after":              stale_after,
        "timing_rationale":         rationale,
    }


def _clean_thesis_timing(
    raw: Any, *, stage: Any = None,
) -> dict:
    """Sanitize the optional ``thesis_timing`` block.

    Each window field must be one of ``_WAVE_TIMING_ENUM``
    (1d / 1-5d / 5-20d / 20d+).  A valid block requires at least
    ``expected_reaction_window``; the other two windows are optional
    but enum-validated when present.

    When ``stage`` is ``"anticipation"`` and the reaction window is
    ``"1d"``, the block is rejected — anticipation events can't share
    the realized-event timing.  Callers fall back to inference to
    re-derive a stage-appropriate block.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for key in (
        "expected_reaction_window",
        "follow_through_window",
        "stale_after",
    ):
        v = raw.get(key)
        if isinstance(v, str):
            t = v.strip().lower()
            if t in _WAVE_TIMING_ENUM:
                out[key] = t
    rationale = raw.get("timing_rationale")
    if isinstance(rationale, str):
        text = rationale.strip()
        if text and text.lower() not in _NULL_LIKE:
            out["timing_rationale"] = text[:240]

    if "expected_reaction_window" not in out:
        return {}

    if isinstance(stage, str) and stage.strip().lower() == "anticipation":
        if out["expected_reaction_window"] == "1d":
            # Anticipation events can't use realized-event timing —
            # drop the block so inference re-derives it.
            return {}

    return out


def _clean_scenario_conditions(raw: Any) -> list[dict]:
    """Normalise the optional ``scenario_conditions`` list.

    Each entry MUST carry three required text fields:
      * ``condition``        — the specific scenario the thesis depends on
      * ``why_it_matters``   — how the condition modifies the read
      * ``evidence_to_watch`` — the observable signal that confirms the
                                condition holds (data print, price move,
                                filing, policy event)

    Vague text on any field drops the entry — scenario conditions
    must be concrete enough that a desk could watch the named
    signal.  Capped at 3 entries; output shape stays a flat list of
    dicts with consistent keys so downstream consumers can branch
    cleanly.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        condition = _clean_text(item.get("condition"))
        why       = _clean_text(item.get("why_it_matters"))
        evidence  = _clean_text(item.get("evidence_to_watch"))
        if not (condition and why and evidence):
            continue
        if (
            _is_vague_wave_text(condition)
            or _is_vague_wave_text(why)
            or _is_vague_wave_text(evidence)
        ):
            continue
        out.append({
            "condition":         condition[:200],
            "why_it_matters":    why[:200],
            "evidence_to_watch": evidence[:200],
        })
        if len(out) >= 3:
            break
    return out


def _build_thesis_evidence_sources(block: dict) -> list[dict]:
    """Compose the ``evidence_sources`` traceability list for a sanitized
    competing_thesis block.

    Each entry wraps an existing ``evidence_favoring_*`` line with its
    source path, direction, and a substantive limitation (if any).  No
    new data is fetched — every source maps back to a field already on
    the analysis dict.  Returns ``[]`` when the block carries no
    evidence the desk could audit.
    """
    try:
        from evidence_sources import make_source
    except Exception:
        return []

    out: list[dict] = []

    primary_evidence = block.get("evidence_favoring_primary") or []
    if isinstance(primary_evidence, list):
        if len(primary_evidence) == 1:
            single_limit = "single supporting line — no cross-confirmation"
        else:
            single_limit = ""
        for entry in primary_evidence:
            if not isinstance(entry, dict):
                continue
            channel = entry.get("channel") or "unclassified"
            limitation = single_limit
            if channel == "unclassified":
                limitation = (
                    "channel unspecified — transmission can't be audited"
                )
            src = make_source(
                source_type="internal_field",
                field_used=f"competing_thesis.evidence_favoring_primary[{channel}]",
                supports_or_contradicts="supports",
                limitation=limitation,
            )
            if src:
                out.append(src)

    alt_evidence = block.get("evidence_favoring_alternative") or []
    if isinstance(alt_evidence, list):
        for entry in alt_evidence:
            if not isinstance(entry, dict):
                continue
            channel = entry.get("channel") or "unclassified"
            limitation = ""
            if channel == "unclassified":
                limitation = (
                    "channel unspecified — transmission can't be audited"
                )
            src = make_source(
                source_type="internal_field",
                field_used=(
                    f"competing_thesis.evidence_favoring_alternative[{channel}]"
                ),
                supports_or_contradicts="contradicts",
                limitation=limitation,
            )
            if src:
                out.append(src)

    discriminator = block.get("discriminator")
    if isinstance(discriminator, dict) and discriminator.get("channel"):
        timing = discriminator.get("timing") or "unspecified"
        limitation = (
            "" if timing in ("1d", "1-5d")
            else "discriminator timing unspecified — resolution window unclear"
        )
        src = make_source(
            source_type="internal_field",
            field_used=(
                f"competing_thesis.discriminator[{discriminator['channel']}]"
            ),
            supports_or_contradicts="neutral",
            limitation=limitation,
        )
        if src:
            out.append(src)

    return out


def _clean_competing_thesis(raw: Any) -> dict:
    """Sanitize the competing_thesis block from LLM output.

    primary_thesis is the single load-bearing field. Without it the
    block collapses to {}. alternative_thesis and discriminator are
    optional layers that only attach when they add information:

      * alternative_thesis  — only when materially distinct from primary.
      * evidence_favoring_alternative — only alongside alternative_thesis.
      * discriminator       — only when both theses are present and the
                              resolver is structurally complete; without
                              two theses to discriminate it is incoherent.
      * first_order_effect  — optional dict; describes the direct
                              market / economic impact when committed.
      * second_order_effects — optional list of cascade dicts; each
                              entry must name trigger + intermediate
                              channel + affected actor + timing.
      * scenario_conditions — optional list of conditional-thesis
                              dicts; each entry names the condition
                              the read depends on, why it matters,
                              and the observable evidence to watch.

    Output shape stays the same — missing optional fields are simply
    absent from the returned dict (downstream consumers already check
    for keys before rendering).
    """
    if not isinstance(raw, dict):
        return {}

    primary = _clean_text(raw.get("primary_thesis"))
    if not primary:
        return {}

    out: dict = {
        "primary_thesis":            primary[:360],
        "evidence_favoring_primary": _clean_evidence_list(
            raw.get("evidence_favoring_primary"),
        ),
    }

    alternative = _clean_text(raw.get("alternative_thesis"))
    if (
        alternative
        and not _is_vague_thesis(alternative)
        and _alt_materially_distinct(primary, alternative)
    ):
        out["alternative_thesis"] = alternative[:240]
        out["evidence_favoring_alternative"] = _clean_evidence_list(
            raw.get("evidence_favoring_alternative"),
        )
        discriminator = _clean_discriminator(raw.get("discriminator"))
        if discriminator:
            out["discriminator"] = discriminator

    first_order = _clean_first_order_effect(raw.get("first_order_effect"))
    if first_order:
        out["first_order_effect"] = first_order
    second_order = _clean_second_order_effects(raw.get("second_order_effects"))
    if second_order:
        out["second_order_effects"] = second_order

    scenario_conditions = _clean_scenario_conditions(
        raw.get("scenario_conditions"),
    )
    if scenario_conditions:
        out["scenario_conditions"] = scenario_conditions

    sources = _build_thesis_evidence_sources(out)
    if sources:
        out["evidence_sources"] = sources

    # thesis_timing is sanitized stage-aware later in _finalize_analysis
    # (which has access to the stage / persistence / family / subtype
    # context).  Pass through any LLM-emitted dict without stage
    # validation here — the finalize step re-cleans with stage so the
    # anticipation-vs-realized rule fires.
    thesis_timing_raw = raw.get("thesis_timing")
    if isinstance(thesis_timing_raw, dict) and thesis_timing_raw:
        # Light-touch enum check; the strict stage-aware check happens
        # in _finalize_analysis.
        cleaned = _clean_thesis_timing(thesis_timing_raw)
        if cleaned:
            out["thesis_timing"] = cleaned

    return out


# ---------------------------------------------------------------------------
# Institutional research-field sanitizers
# ---------------------------------------------------------------------------
# All three asset buckets (primary / secondary / hedge_or_signal) share the
# same shape: a list of ``{symbol, rank, rationale}`` dicts.  The LLM is
# also allowed to emit the literal string ``"insufficient_evidence"`` at
# the whole-field level when it genuinely cannot rank anything concrete.
# We collapse that to an empty list so downstream code always iterates a
# list — the "insufficient_evidence" signal is a semantic one the UI can
# read off ``assets_to_watch`` length vs beneficiary_tickers length.

_INSUFFICIENT_EVIDENCE_SENTINEL: str = "insufficient_evidence"
_MAX_RANKED_ASSETS: int = 4
_MAX_HEDGE_ASSETS:  int = 3
_MAX_KEY_FALSIFIERS: int = 5
_MAX_PROOF_ENTRIES:  int = 5


# ---------------------------------------------------------------------------
# Mechanism-specificity / asset-discipline helpers
# ---------------------------------------------------------------------------
# A ranked asset entry is only useful when its rationale ties the symbol to
# the chosen mechanism.  Whole-string filler templates ("Direct beneficiary",
# "Broad sector exposure") add no information and are dropped here so the
# bucket stays mechanism-coherent.
#
# Patterns are anchored with ``^`` / ``$`` so that real specific rationales
# that happen to contain the word "exposure" or "sector" survive — only the
# bare-template forms are filtered.

_GENERIC_RATIONALE_TEMPLATES: tuple[re.Pattern, ...] = (
    re.compile(
        r"^(direct|key|major|primary|main|broad|broader|general)\s+"
        r"(beneficiary|exposure|proxy|play|player)\b\.?$",
        re.I,
    ),
    re.compile(
        r"^(direct|key|major|primary|main|broad|broader|general)\s+"
        r"(beneficiary|exposure|proxy|play|player)\s+"
        r"(of|to|in|for|on)\s+(the\s+)?"
        r"(sector|theme|trend|industry|space|market|story|move|event|news)\b\.?$",
        re.I,
    ),
    re.compile(
        r"^broad(er)?\s+(market|sector|theme|industry)\s+"
        r"(exposure|proxy|play|tailwind|reaction|beneficiary)\b\.?$",
        re.I,
    ),
    re.compile(
        r"^pure[- ]play\s+(exposure|proxy)"
        r"(\s+(on|to|for|in)\s+(the\s+)?"
        r"(sector|theme|trend|industry|space|story))?\b\.?$",
        re.I,
    ),
    re.compile(
        r"^thematic\s+(play|proxy|exposure|tailwind)"
        r"(\s+(on|to|for|in)\s+(the\s+)?"
        r"(sector|theme|trend|industry|space|story))?\b\.?$",
        re.I,
    ),
    re.compile(
        r"^indirect\s+exposure"
        r"(\s+(on|to|for|in)\s+(the\s+)?"
        r"(sector|theme|trend|industry|space|story|broader[\s\w]*))?\b\.?$",
        re.I,
    ),
    re.compile(r"^sector\s+(proxy|tailwind|etf|play|exposure|reaction)\b\.?$", re.I),
    re.compile(
        r"^(key|major|leading)\s+player\s+(in|of)\s+(the\s+)?"
        r"(sector|industry|space|theme|story)\b\.?$",
        re.I,
    ),
    re.compile(r"^diversified\s+(sector|industry|theme)\s+(etf|exposure|proxy)\b\.?$", re.I),
    re.compile(
        r"^general\s+sector\s+"
        r"(beneficiary|exposure|tailwind|tail-wind|proxy)\b\.?$",
        re.I,
    ),
    re.compile(
        r"^exposure\s+to\s+the\s+"
        r"(sector|theme|trend|industry|space|story|broader[\s\w]*)\b\.?$",
        re.I,
    ),
)


def _is_generic_rationale(text: Any) -> bool:
    """True when ``text`` is a whole-string filler template with no
    mechanism-specific anchor.  Specific rationales that mention the
    same words within a longer sentence are preserved."""
    if not isinstance(text, str):
        return True
    s = text.strip()
    if not s:
        return True
    return any(pat.match(s) for pat in _GENERIC_RATIONALE_TEMPLATES)


# Mechanism-summary text that mashes multiple primary channels together
# without committing to one.  When detected, the pipeline coerces the
# study to a low-information shape so the UI doesn't surface a fake
# "confident" multi-channel read.
_BLENDED_MECHANISM_MARKERS: tuple[re.Pattern, ...] = (
    re.compile(
        r"\bacross\s+(multiple|various|several|many)\s+"
        r"(channels|mechanisms|pathways|markets|sectors|industries)\b",
        re.I,
    ),
    re.compile(
        r"\b(multiple|various|several)\s+(transmission\s+)?"
        r"(channels|mechanisms|pathways)\b",
        re.I,
    ),
    re.compile(
        r"\bripple\s+effects?\s+(across|spread|throughout|propagat)",
        re.I,
    ),
    re.compile(
        r"\bbroad[- ]based\s+(impacts?|effects?|reactions?|repricings?)\b",
        re.I,
    ),
    re.compile(r"\bblended\s+(impacts?|effects?|exposures?|repricings?)\b", re.I),
    re.compile(r"\bdiffuse\s+(impacts?|effects?|reactions?|repricings?)\b", re.I),
    re.compile(r"\bwide[- ]ranging\s+(impacts?|effects?|implications?)\b", re.I),
    re.compile(
        r"\b(many|multiple|various|several)\s+(sectors|industries|markets|channels|pathways)\b",
        re.I,
    ),
)


def _is_blended_mechanism(text: Any) -> bool:
    """True when ``mechanism_summary`` reads as a multi-channel mash
    rather than committing to one primary transmission channel."""
    if not isinstance(text, str):
        return False
    s = text.strip()
    if not s:
        return False
    return any(pat.search(s) for pat in _BLENDED_MECHANISM_MARKERS)

_PROOF_CHANNEL_ENUM: frozenset[str] = frozenset({
    "rates", "fx", "commodities", "vol", "credit", "equities",
})
_PROOF_TIMING_ENUM: frozenset[str] = frozenset({
    "1d", "1-5d", "5-20d", "20d+",
})


def _is_insufficient_evidence(raw: Any) -> bool:
    """Spot the whole-field 'insufficient_evidence' sentinel."""
    return (
        isinstance(raw, str)
        and raw.strip().lower().replace(" ", "_") == _INSUFFICIENT_EVIDENCE_SENTINEL
    )


def _clean_ranked_asset_list(raw: Any, *, max_items: int) -> list[dict]:
    """Normalise a ranked-asset bucket into a list of clean dicts.

    Accepts either a list of ``{symbol, rank, rationale}`` dicts or the
    literal string ``"insufficient_evidence"`` — the latter collapses
    to an empty list so downstream code always iterates.

    Empty/None/malformed entries are dropped silently.  Ranks are
    reassigned to a strict 1..N sequence so a sloppy LLM that emits
    ``[rank=1, rank=1, rank=3]`` gets turned into ``[1, 2, 3]``
    preserving input order rather than propagating the clash.  Duplicate
    symbols are dropped (first occurrence wins).
    """
    if raw is None or _is_insufficient_evidence(raw):
        return []
    if not isinstance(raw, list):
        return []

    seen_symbols: set[str] = set()
    cleaned: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        sym_raw = entry.get("symbol")
        if not isinstance(sym_raw, str):
            continue
        symbol = sym_raw.strip().upper()
        if not symbol or symbol in seen_symbols:
            continue
        rationale = _clean_text(entry.get("rationale")) or ""
        # A ranked entry with no rationale is just a ticker — the whole
        # point of this schema is the rationale; drop it.
        if not rationale:
            continue
        # Reject filler rationales — generic sector sentences carry no
        # mechanism tie and pad the bucket without information.
        if _is_generic_rationale(rationale):
            continue
        seen_symbols.add(symbol)
        cleaned.append({
            "symbol":    symbol,
            "rank":      len(cleaned) + 1,   # re-indexed to 1..N
            "rationale": rationale[:200],
        })
        if len(cleaned) >= max_items:
            break
    return cleaned


def _clean_key_falsifiers(raw: Any) -> list[str]:
    """Normalise the flat key_falsifiers list.

    Each entry must be a non-trivial string; entries shorter than 15
    chars are dropped as they can't possibly be price-checkable.  A raw
    value that isn't a list or is the "insufficient_evidence" sentinel
    collapses to ``[]``.
    """
    if raw is None or _is_insufficient_evidence(raw):
        return []
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        text = _clean_text(entry)
        if not text or len(text) < 15:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text[:280])
        if len(cleaned) >= _MAX_KEY_FALSIFIERS:
            break
    return cleaned


def _clean_top_level_proof_set(raw: Any) -> list[dict]:
    """Normalise the top-level minimum_proof_set list.

    Each entry must carry ``observation``, ``channel``, ``threshold``,
    ``timing``.  Channel is coerced to the 6-token vocabulary; timing
    to the 4-token vocabulary; malformed entries are dropped rather
    than repaired.
    """
    if raw is None or _is_insufficient_evidence(raw):
        return []
    if not isinstance(raw, list):
        return []
    cleaned: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        obs = _clean_text(entry.get("observation"))
        if not obs or len(obs) < 10:
            continue
        ch_raw = entry.get("channel")
        channel = ch_raw.strip().lower() if isinstance(ch_raw, str) else ""
        if channel not in _PROOF_CHANNEL_ENUM:
            continue
        tm_raw = entry.get("timing")
        timing = tm_raw.strip() if isinstance(tm_raw, str) else ""
        if timing not in _PROOF_TIMING_ENUM:
            continue
        threshold = _clean_text(entry.get("threshold")) or ""
        cleaned.append({
            "observation": obs[:240],
            "channel":     channel,
            "threshold":   threshold[:160],
            "timing":      timing,
        })
        if len(cleaned) >= _MAX_PROOF_ENTRIES:
            break
    return cleaned


# ---------------------------------------------------------------------------
# Backward-compat derivation — legacy lists from the ranked structure
# ---------------------------------------------------------------------------
# When the LLM commits to rich ``primary_assets`` / ``secondary_assets``
# entries but leaves ``beneficiary_tickers`` or ``beneficiaries`` thin,
# we backfill the legacy shape from the richer one so existing consumers
# (telegram bot, downstream charts, main.py CLI) continue to see populated
# lists.  This preserves the backward-compat contract stated in the task:
# "preserve existing beneficiaries / losers / assets_to_watch by deriving
# them from the richer structure where needed."
#
# Derivation is guarded — it never overwrites a populated legacy list.
# An LLM that emits both shapes sees its existing lists preserved
# byte-for-byte; only thin-legacy + rich-ranked events get backfilled.


def _derive_legacy_tickers_from_ranked(
    beneficiary_tickers: list[str],
    loser_tickers: list[str],
    *,
    primary_assets: list[dict],
    secondary_assets: list[dict],
    context: str,
) -> tuple[list[str], list[str]]:
    """Backfill ``beneficiary_tickers`` from ``primary_assets`` when empty.

    The primary bucket is the ranked "winners" side by contract — every
    entry's rationale should name a reason the thesis LIFTS that asset.
    If the legacy ``beneficiary_tickers`` list is empty we hoist symbols
    out of the primary bucket (and, only as a fallback, the secondary
    bucket) through the same ``_clean_assets`` sanitizer the raw LLM
    output passes through, so derived tickers obey the same validity
    rules (no index symbols, no foreign suffixes, etc.).
    """
    if beneficiary_tickers:
        return beneficiary_tickers, loser_tickers

    # Walk primary first, then secondary, preserving rank order.  Hedge
    # bucket is intentionally skipped — hedge/signal proxies (DXY, VIX,
    # inverse ETFs) are never beneficiaries of the thesis.
    candidate_syms: list[str] = []
    for bucket in (primary_assets, secondary_assets):
        for entry in bucket:
            if not isinstance(entry, dict):
                continue
            sym = entry.get("symbol")
            if isinstance(sym, str) and sym.strip():
                candidate_syms.append(sym.strip())

    if not candidate_syms:
        return beneficiary_tickers, loser_tickers

    # Run through the same sanitizer so index symbols / foreign suffixes
    # get rejected; ``context`` carries the headline + mechanism so the
    # cleaner's suffix heuristics still apply.
    derived = _clean_assets(candidate_syms, context=context)
    if not derived:
        return beneficiary_tickers, loser_tickers

    # Ensure the derived tickers don't collide with the loser list —
    # loser_tickers is the committed list the LLM *did* emit so it wins
    # any overlap.  Same-order dedupe.
    loser_set = {t.upper() for t in loser_tickers}
    derived = [t for t in derived if t.upper() not in loser_set]
    return derived, loser_tickers


def _derive_legacy_beneficiaries(
    beneficiaries: list,
    *,
    primary_assets: list[dict],
) -> list[str]:
    """Backfill ``beneficiaries`` (named entities) from primary rationales.

    When the LLM leaves ``beneficiaries`` empty but commits to ranked
    ``primary_assets`` with rationales, we synthesise a compact entity
    line per ranked asset of the form ``"SYMBOL — <rationale snippet>"``.
    This keeps the legacy Telegram render + CLI output populated while
    surfacing the richer rationale text the ranked structure carries.
    """
    if beneficiaries:
        return list(beneficiaries)
    if not primary_assets:
        return []

    derived: list[str] = []
    for entry in primary_assets[:4]:
        if not isinstance(entry, dict):
            continue
        sym = entry.get("symbol")
        rationale = entry.get("rationale") or ""
        if not isinstance(sym, str) or not sym.strip():
            continue
        if isinstance(rationale, str) and rationale.strip():
            # Truncate the rationale to a headline-compatible length so
            # the derived entity list stays readable in chat / card UI.
            snippet = rationale.strip()
            if len(snippet) > 120:
                snippet = snippet[:117].rstrip() + "…"
            derived.append(f"{sym.strip()} — {snippet}")
        else:
            derived.append(sym.strip())
    return derived


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
) -> AnalysisResult:
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
        # A degraded fallback already represents a thin model response;
        # do not pad with broad-sector proxies — that would manufacture
        # confidence the analysis cannot carry.
        tickers = _clean_assets([], context=ctx, skip_proxy_backfill=True)

    result: AnalysisResult = {
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
        # Derived blocks below are filled by the composers at the end of
        # this function so the degraded path returns the same shapes as
        # ``compose_*`` low_information outputs — single source of truth.
        "confidence_rationale":   "",
        "counterfactual_check":   {},
        "actionability_check":    {},
        "transmission_chain": [],
        "transmission_path": [],
        "substitution_barriers": [],
        "counterforces": [],
        "adversarial_challenge": "",
        "horizon_checkpoints": _clean_horizon_checkpoints(None),
        "mechanism_family": "none",
        "expected_first_order_channels": [],
        "expected_second_order_channels": [],
        "regime_conditioned_caveat": "",
        "if_persists": {},
        "currency_channel": {},
        "primary_assets":             [],
        "secondary_assets":           [],
        "hedge_or_signal_assets":     [],
        "key_falsifiers":             [],
        "minimum_proof_set":          [],
        "degraded": True,
        "validation_warnings": [
            f"degraded: {reason}",
            "evidence_quality: low_information",
        ],
        # Degraded outputs are low_information by definition — stamp
        # the engine tier and the canonical weak_mechanism warning so
        # consumers branching on ``quality_tier`` / ``quality_warnings``
        # see a stable read regardless of which path produced the
        # low-info verdict.
        "quality_tier":      "low_information",
        "quality_warnings":  ["weak_mechanism"],
    }
    from low_information_gate import (
        compose_actionability_check,
        compose_confidence_rationale,
        compose_counterfactual_check,
    )
    result["confidence_rationale"] = compose_confidence_rationale(result)
    result["counterfactual_check"] = compose_counterfactual_check(result)
    result["actionability_check"] = compose_actionability_check(result)
    return result


# ---------------------------------------------------------------------------
# Contradiction-aware validation
# ---------------------------------------------------------------------------

def _validate_result(result: dict, stage: str) -> AnalysisResult:
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

    # Rule 9: weak source traceability on competing_thesis caps high
    # confidence — if the desk can't audit which fields the thesis is
    # leaning on, the read can't ship as high-conviction.  The check
    # only fires when an evidence_sources block was actually composed
    # (i.e. the thesis emitted at least one auditable line); a
    # competing_thesis without any evidence is already covered by the
    # mechanism / proof rules above.
    competing = result.get("competing_thesis") or {}
    if isinstance(competing, dict):
        sources = competing.get("evidence_sources")
        if sources is not None and result.get("confidence") == "high":
            try:
                from evidence_sources import is_weak_traceability
            except Exception as exc:
                _log.warning(
                    "evidence_sources traceability hook unavailable: %s — "
                    "skipping high-confidence cap on weak traceability",
                    exc,
                )
            else:
                if is_weak_traceability(sources):
                    result["confidence"] = "medium"
                    warnings.append(
                        "confidence downgraded high → medium "
                        "(weak source traceability on competing_thesis)"
                    )

    if warnings:
        existing = result.get("validation_warnings", [])
        if not isinstance(existing, list):
            existing = []
        result["validation_warnings"] = existing + warnings

    return _strip_scratch_fields(result)


# ---------------------------------------------------------------------------
# Scratch-field cleanup
# ---------------------------------------------------------------------------

def _strip_scratch_fields(result: dict) -> dict:
    """Remove any internal scratch fields before returning a finalized
    analysis dict.

    Pipeline stages stash transient state under underscore-prefixed
    keys (``_raw_beneficiary_tickers``, ``_raw_loser_tickers``, etc.)
    so later steps can re-derive sanitized lists without re-parsing.
    Those fields must never reach a returned analysis: consumers
    (api.py, db.py, eval.py) read AnalysisResult and the underscore
    prefix carries no semantic guarantee in the response contract.
    Defensive final-pass guard — drops every ``_*`` key in place.
    """
    if not isinstance(result, dict):
        return result
    for key in [k for k in result if isinstance(k, str) and k.startswith("_")]:
        result.pop(key, None)
    return result


# ---------------------------------------------------------------------------
# Mock / is_mock helpers
# ---------------------------------------------------------------------------

def is_mock(analysis: dict) -> bool:
    """Return True if the analysis is a mock/fallback, not a real LLM result."""
    return "[mock:" in (analysis.get("what_changed") or "")


def _mock(reason: str) -> AnalysisResult:
    """Return a clearly-labelled mock so the pipeline never crashes.

    Shape parity with ``_degraded_fallback`` and the normal
    low-information path: every block downstream consumers branch
    on (``actionability_check``, ``counterfactual_check``,
    ``confidence_rationale``, ``quality_warnings``, ``quality_tier``)
    is populated here so a ``_mock`` result drops into any consumer
    that expects a low-information output.

    Derived blocks (``confidence_rationale``, ``counterfactual_check``,
    ``actionability_check``) are filled by the composers — single
    source of truth with the other low-info paths.
    """
    result: AnalysisResult = {
        "what_changed": f"[mock: {reason}]",
        "mechanism_summary": f"[mock: {reason}]",
        "beneficiaries": ["[mock]"],
        "losers": ["[mock]"],
        "beneficiary_tickers": ["GLD"],
        "loser_tickers": ["USO"],
        "assets_to_watch": ["GLD", "USO"],
        "confidence": "low",
        "confidence_rationale":   "",
        "counterfactual_check":   {},
        "actionability_check":    {},
        "transmission_chain": [],
        "transmission_path": [],
        "substitution_barriers": [],
        "counterforces": [],
        "adversarial_challenge": "",
        "horizon_checkpoints": _clean_horizon_checkpoints(None),
        "mechanism_family": "none",
        "expected_first_order_channels": [],
        "expected_second_order_channels": [],
        "regime_conditioned_caveat": "",
        "if_persists": {},
        "currency_channel": {},
        "primary_assets":             [],
        "secondary_assets":           [],
        "hedge_or_signal_assets":     [],
        "key_falsifiers":             [],
        "minimum_proof_set":          [],
        # Low-information stamps — match _degraded_fallback so consumers
        # branching on quality_tier / quality_warnings see the same
        # field set across every low-information path.
        "quality_tier":      "low_information",
        "quality_warnings":  ["weak_mechanism"],
    }
    from low_information_gate import (
        compose_actionability_check,
        compose_confidence_rationale,
        compose_counterfactual_check,
    )
    result["confidence_rationale"] = compose_confidence_rationale(result)
    result["counterfactual_check"] = compose_counterfactual_check(result)
    result["actionability_check"] = compose_actionability_check(result)
    return result


def _is_transient_error(exc: Exception, provider: str = "anthropic") -> bool:
    """Return True if the exception is a transient provider error worth retrying.

    Retryable: OverloadedError (529), RateLimitError (429),
    ServiceUnavailableError (503), APITimeoutError, APIConnectionError.
    Everything else (auth, validation, parse, import) → not retryable.
    """
    if provider == "openai":
        try:
            import openai
        except ImportError:
            return False
        transient = tuple(
            cls for cls in (
                getattr(openai, "RateLimitError", None),
                getattr(openai, "InternalServerError", None),
                getattr(openai, "APITimeoutError", None),
                getattr(openai, "APIConnectionError", None),
            )
            if cls is not None
        )
        return (transient and isinstance(exc, transient)) or (
            hasattr(exc, "status_code")
            and getattr(exc, "status_code", 0) in (429, 500, 503, 529)
        )

    try:
        import anthropic
    except ImportError:
        return False
    return isinstance(exc, (
        anthropic.RateLimitError,        # 429
        anthropic.InternalServerError,   # 500
        anthropic.APITimeoutError,
        anthropic.APIConnectionError,
    )) or (
        # OverloadedError (529) and ServiceUnavailableError (503) are
        # subclasses of APIStatusError; catch them by status_code so
        # we don't need to handle SDK version differences.
        isinstance(exc, anthropic.APIStatusError)
        and getattr(exc, "status_code", 0) in (429, 500, 503, 529)
    )


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
    result["transmission_path"] = _clean_transmission_path(
        raw.get("transmission_path"),
    )
    result["substitution_barriers"] = _clean_substitution_barriers(
        raw.get("substitution_barriers"),
    )
    result["counterforces"] = _clean_counterforces(raw.get("counterforces"))
    result["adversarial_challenge"] = _clean_adversarial_challenge(
        raw.get("adversarial_challenge"),
    )
    result["horizon_checkpoints"] = _clean_horizon_checkpoints(
        raw.get("horizon_checkpoints"),
    )
    # Mechanism family: LLM-committed value preferred; keyword-based
    # fallback kicks in only when the LLM emits "none" or nothing usable.
    family = _resolve_mechanism_family(
        raw.get("mechanism_family"),
        headline,
        result.get("mechanism_summary", ""),
    )
    result["mechanism_family"] = family
    first_ch, second_ch = _resolve_channel_packs(
        family,
        raw.get("expected_first_order_channels"),
        raw.get("expected_second_order_channels"),
    )
    result["expected_first_order_channels"] = first_ch
    result["expected_second_order_channels"] = second_ch
    result["regime_conditioned_caveat"] = _clean_regime_caveat(
        raw.get("regime_conditioned_caveat"),
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

    # hidden_mechanism — gated to the tickers the LLM just listed, so
    # asset_rationales can't smuggle in a ticker outside the event's
    # declared universe.  Symbols filter against the pre-sanitization
    # raw lists; the post-sanitization step may drop a few more, and
    # any rationale for a dropped ticker simply won't be referenced.
    valid_tickers: set[str] = {
        s.strip().upper() for s in (
            result["_raw_beneficiary_tickers"] + result["_raw_loser_tickers"]
        )
        if isinstance(s, str) and s.strip()
    }
    result["hidden_mechanism"] = _clean_hidden_mechanism(
        raw.get("hidden_mechanism"),
        valid_tickers,
    )

    # competing_thesis — single primary read with optional rival layer.
    # Always carries primary_thesis when emitted; alternative_thesis +
    # discriminator attach only when the rival is materially distinct
    # and the resolver is decisive (see _clean_competing_thesis).
    # Downstream consumers check key presence before rendering.
    result["competing_thesis"] = _clean_competing_thesis(
        raw.get("competing_thesis"),
    )

    # monitor_plan — operational monitoring layer.  Only the two
    # net-new fields are LLM-emitted; the unified 5-field monitor view
    # is assembled on read by ``validation_plan.compute_monitor_plan``
    # from horizon_checkpoints + competing_thesis + this block.
    result["monitor_plan"] = _clean_monitor_plan(raw.get("monitor_plan"))

    # Institutional research fields — ranked asset buckets and flat
    # falsifier / proof-set lists.  Each sanitizer tolerates the
    # "insufficient_evidence" sentinel by collapsing to []; the merge
    # into assets_to_watch happens in _finalize_analysis.
    result["primary_assets"] = _clean_ranked_asset_list(
        raw.get("primary_assets"), max_items=_MAX_RANKED_ASSETS,
    )
    result["secondary_assets"] = _clean_ranked_asset_list(
        raw.get("secondary_assets"), max_items=_MAX_RANKED_ASSETS,
    )
    result["hedge_or_signal_assets"] = _clean_ranked_asset_list(
        raw.get("hedge_or_signal_assets"), max_items=_MAX_HEDGE_ASSETS,
    )
    result["key_falsifiers"] = _clean_key_falsifiers(raw.get("key_falsifiers"))
    result["minimum_proof_set"] = _clean_top_level_proof_set(
        raw.get("minimum_proof_set"),
    )

    # Second-pass family fallback — reduce false ``mechanism_family="none"``
    # by consulting the now-populated transmission chain, asset buckets,
    # and hidden_mechanism block.  Only fires when the first pass (LLM +
    # keyword classifier over headline / mechanism_summary) returned
    # "none"; a committed family is preserved byte-for-byte.  If the
    # evidence remains genuinely weak, the result stays "none" and
    # channels refresh against the canonical-none pack in
    # ``_resolve_channel_packs``.
    upgraded = _post_parse_family_fallback(result, headline)
    if upgraded != result["mechanism_family"]:
        result["mechanism_family"] = upgraded
        # If the channel packs were empty because the first-pass family
        # was "none", rebuild them against the upgraded family so the
        # downstream validation matrix lines up with the resolved family.
        if not result.get("expected_first_order_channels") and not result.get(
            "expected_second_order_channels"
        ):
            first, second = _resolve_channel_packs(
                upgraded,
                raw.get("expected_first_order_channels"),
                raw.get("expected_second_order_channels"),
            )
            result["expected_first_order_channels"] = first
            result["expected_second_order_channels"] = second

    # Mechanism subtype — derive / validate against the (possibly
    # upgraded) family.  Runs AFTER the second-pass fallback so a
    # corrected family gets the right subtype set.  Three paths:
    #   1. LLM provided a subtype string → validate against
    #      FAMILY_SUBTYPES[family]; keep if valid, drop + warn if not.
    #   2. LLM did not provide one → run keyword inference over the
    #      richer signal blob (primary_thesis + transmission_chain +
    #      mechanism_summary + what_changed + transmission_path hops).
    #   3. Family is "none" / nothing matches → field stays absent.
    _normalize_mechanism_subtype(result, raw)

    return result


def _gather_subtype_signal_blob(result: dict) -> str:
    """Concatenate the prose fields used for subtype keyword inference.

    Pulls primary_thesis (when committed), transmission_chain steps,
    transmission_path hop / action / expected_market_effect text, and
    mechanism_summary so the inference sees the richer signal the
    task names — not just the summary line.
    """
    parts: list[str] = []
    summary = result.get("mechanism_summary")
    if isinstance(summary, str):
        parts.append(summary)

    chain = result.get("transmission_chain")
    if isinstance(chain, list):
        for step in chain:
            if isinstance(step, str):
                parts.append(step)

    path = result.get("transmission_path")
    if isinstance(path, list):
        for hop in path:
            if not isinstance(hop, dict):
                continue
            for k in ("hop", "action", "expected_market_effect"):
                v = hop.get(k)
                if isinstance(v, str):
                    parts.append(v)

    ct = result.get("competing_thesis")
    if isinstance(ct, dict):
        pt = ct.get("primary_thesis")
        if isinstance(pt, str):
            parts.append(pt)

    return " ".join(parts)


def _normalize_mechanism_subtype(result: dict, raw: dict) -> None:
    """Validate / infer ``mechanism_subtype`` in place on ``result``.

    Decisions:
      * LLM-provided subtype valid for the resolved family → kept.
      * LLM-provided subtype NOT valid for the family → dropped, a
        validation warning is appended, AND the inference fallback
        runs so a correct subtype can replace it when one matches.
      * No LLM subtype → inference runs over the richer signal blob
        (mechanism_summary + transmission_chain + transmission_path +
        competing_thesis.primary_thesis + what_changed).
      * No match anywhere → ``mechanism_subtype`` stays absent so
        family-level behaviour is preserved.

    Output shape stays stable: the field is set only when a valid
    subtype is committed.
    """
    family = result.get("mechanism_family") or "none"
    try:
        from mechanism_family import (
            FAMILY_SUBTYPES,
            infer_mechanism_subtype,
        )
    except Exception:
        return

    raw_subtype = raw.get("mechanism_subtype") if isinstance(raw, dict) else None
    valid_for_family = FAMILY_SUBTYPES.get(family, {})

    candidate: str | None = None
    if isinstance(raw_subtype, str) and raw_subtype.strip():
        token = raw_subtype.strip()
        if token in valid_for_family:
            candidate = token
        else:
            warnings = list(result.get("validation_warnings") or [])
            warnings.append(
                f"mechanism_subtype dropped — '{token}' not valid for "
                f"family '{family}'",
            )
            result["validation_warnings"] = warnings

    if candidate is None and valid_for_family:
        # Inference fallback — runs whether the LLM omitted a subtype
        # OR emitted an invalid one (so a corrected family still
        # gets the subtype from the prose signals).
        blob = _gather_subtype_signal_blob(result)
        inferred = infer_mechanism_subtype(
            family, blob,
            result.get("what_changed", "") or "",
        )
        if inferred:
            candidate = inferred

    if candidate:
        result["mechanism_subtype"] = candidate
    else:
        # Drop any stale value left over from earlier passes — keeps
        # the field absent when family is "none" or nothing matches.
        result.pop("mechanism_subtype", None)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _call_anthropic(api_key: str, model: str, prompt: str) -> str | None:
    try:
        import anthropic
    except ImportError:
        print("[analyze_event] 'anthropic' package not installed.")
        print("  → Run: pip install anthropic python-dotenv\n")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    if not message.content:
        return ""
    return message.content[0].text


def _call_openai(api_key: str, model: str, prompt: str) -> str | None:
    try:
        from openai import OpenAI
    except ImportError:
        print("[analyze_event] 'openai' package not installed.")
        print("  → Run: pip install openai python-dotenv\n")
        return None

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        max_output_tokens=8192,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    text = getattr(response, "output_text", None)
    if text:
        return text
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            value = getattr(content, "text", None)
            if value:
                chunks.append(value)
    return "\n".join(chunks)


def _call_llm_provider(provider: str, api_key: str, model: str, prompt: str) -> str | None:
    if provider == "openai":
        return _call_openai(api_key, model, prompt)
    return _call_anthropic(api_key, model, prompt)

def analyze_event(
    inp_or_headline: "AnalyzeEventInput | str",
    stage: str = "", persistence: str = "",
    event_context: str = "", macro_context: str = "",
    model: str | None = None,
    provider: str | None = None,
) -> AnalysisResult:
    """Call the LLM and return a strict, validated analysis of the event.

    Accepts either an AnalyzeEventInput object (preferred) or the legacy
    positional arg style (headline, stage, persistence, ...) for backward
    compatibility with existing callers and test stubs.

    Falls back to a mock response if the key is missing or the call fails.
    Falls back to a degraded analysis object if the LLM returns a thin or
    unusable response.
    """
    if isinstance(inp_or_headline, AnalyzeEventInput):
        inp = inp_or_headline
    else:
        inp = AnalyzeEventInput(
            headline=inp_or_headline, stage=stage, persistence=persistence,
            event_context=event_context, macro_context=macro_context,
            model=model, provider=provider,
        )

    headline = inp.headline
    stage = inp.stage
    persistence = inp.persistence
    event_context = inp.event_context
    macro_context = inp.macro_context

    provider = _selected_provider(inp.provider)
    api_key = _api_key_for_provider(provider)
    model = _selected_model(inp.model, provider)

    if not _has_real_api_key(api_key):
        print(f"[analyze_event] No {provider} API key found. Returning mock response.")
        key_name = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
        print(f"  → Set {key_name} in your .env file to get real analysis.\n")
        return _mock(f"no {provider} API key")

    prompt = EVENT_ANALYSIS_PROMPT.format(
        headline=headline,
        stage=stage,
        persistence=persistence,
        event_context=event_context,
        macro_context=macro_context,
    )

    last_exc: Exception | None = None

    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            raw = _call_llm_provider(provider, api_key, model, prompt)

            if raw is None:
                return _mock(f"{provider} package not installed")

            if not raw:
                print("[analyze_event] API returned empty content list.")
                return _mock("empty API response")

            parsed = _extract_json(raw)

            if parsed is None:
                print("[analyze_event] Could not parse LLM response as JSON.")
                print(f"  → Raw response: {raw}\n")
                return _mock("JSON parse error")

            return _finalize_analysis(parsed, headline, stage, persistence)

        except Exception as e:
            last_exc = e
            if not _is_transient_error(e, provider):
                # Hard failure — do not retry
                print(f"[analyze_event] API call failed (non-retryable): {e}\n")
                return _mock(str(e))

            # Transient failure — retry with backoff
            remaining = RETRY_MAX_ATTEMPTS - attempt - 1
            backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
            _log.warning(
                "analyze_event: transient error (attempt %d/%d, %d left): %s — "
                "retrying in %.1fs",
                attempt + 1, RETRY_MAX_ATTEMPTS, remaining, e, backoff,
            )
            if remaining > 0:
                time.sleep(backoff)

    # All retries exhausted
    reason = str(last_exc) if last_exc else "unknown transient failure"
    print(f"[analyze_event] All {RETRY_MAX_ATTEMPTS} attempts failed: {reason}\n")
    return _mock(reason)


def _finalize_analysis(
    parsed: dict, headline: str, stage: str, persistence: str,
) -> AnalysisResult:
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

    mechanism_summary = normalized.get("mechanism_summary", "")
    context = f"{headline} {mechanism_summary}"
    raw_ben = normalized.pop("_raw_beneficiary_tickers", [])
    raw_los = normalized.pop("_raw_loser_tickers", [])

    # Mechanism-discipline check.  When the mechanism is filler or blends
    # multiple primary channels, suppress thematic-ETF / inverse-proxy
    # backfill so a weak analysis stays low-information instead of
    # padding with broad-sector proxies.
    from low_information_gate import is_low_information_mechanism
    mech_blended = _is_blended_mechanism(mechanism_summary)
    mech_filler = is_low_information_mechanism(mechanism_summary)
    skip_backfill = mech_blended or mech_filler

    beneficiary_tickers = _clean_assets(
        raw_ben, context=context, skip_proxy_backfill=skip_backfill,
    )
    # Losers: sanitize without long-proxy backfill, then add inverse
    # proxies only if nothing survived AND the mechanism is strong enough.
    loser_tickers = _clean_assets(raw_los, context="")
    if not skip_backfill:
        loser_tickers = _backfill_losers(loser_tickers, context)

    # Backward-compat derivation — when the LLM populates the new ranked
    # ``primary_assets`` structure but leaves the legacy ticker/entity
    # lists thin, derive the legacy shape from the richer one so every
    # downstream consumer that reads ``beneficiary_tickers`` /
    # ``beneficiaries`` continues to see populated output.  Does nothing
    # when the legacy lists are already rich — no upgrade path shadows
    # existing LLM output.
    beneficiary_tickers, loser_tickers = _derive_legacy_tickers_from_ranked(
        beneficiary_tickers,
        loser_tickers,
        primary_assets=normalized.get("primary_assets") or [],
        secondary_assets=normalized.get("secondary_assets") or [],
        context=context,
    )
    normalized["beneficiaries"] = _derive_legacy_beneficiaries(
        normalized.get("beneficiaries") or [],
        primary_assets=normalized.get("primary_assets") or [],
    )

    # Guarantee the two lists are disjoint before downstream code sees them.
    beneficiary_tickers, loser_tickers = _dedupe_ticker_overlap(
        beneficiary_tickers, loser_tickers,
    )

    # Merge while preserving order and removing duplicates.  The
    # committed universe (beneficiary + loser tickers) goes FIRST so
    # existing consumers that read ``assets_to_watch[0]`` still see a
    # beneficiary, not a hedge signal.  Then the ranked institutional
    # buckets extend with any net-new symbols in primary → secondary →
    # hedge_or_signal order.  Duplicates are silently skipped.
    seen: set[str] = set()
    assets_to_watch: list[str] = []
    for t in beneficiary_tickers + loser_tickers:
        if t not in seen:
            seen.add(t)
            assets_to_watch.append(t)
    for bucket in (
        normalized.get("primary_assets") or [],
        normalized.get("secondary_assets") or [],
        normalized.get("hedge_or_signal_assets") or [],
    ):
        for entry in bucket:
            sym = entry.get("symbol") if isinstance(entry, dict) else None
            if isinstance(sym, str) and sym not in seen:
                seen.add(sym)
                assets_to_watch.append(sym)

    normalized["beneficiary_tickers"] = beneficiary_tickers
    normalized["loser_tickers"] = loser_tickers
    normalized["assets_to_watch"] = assets_to_watch

    # Cross-field consistency audit — runs BEFORE the low-info gate so
    # the gate sees the post-filter shape.  Drops asset entries and
    # proof / falsifier items that don't share content tokens with the
    # primary thesis + mechanism narrative.  When too much of the
    # structure is off-thesis, the audit signals a downgrade to
    # ``low_information`` (we follow up by calling normalize); a
    # ``watch_only`` downgrade is advisory and surfaces naturally
    # through ``evidence_quality_tier``.
    from low_information_gate import (
        apply_low_information_gate,
        clear_weak_chain_proof,
        compute_causal_strength,
        enforce_thesis_consistency,
        evaluate_blocker_discipline,
        evaluate_chain_family_consistency,
        normalize_low_information,
    )
    consistency = enforce_thesis_consistency(normalized)
    if consistency["downgrade"] == "low_information":
        normalize_low_information(normalized)
        warnings = list(normalized.get("validation_warnings") or [])
        warnings.append("cross-field consistency collapsed — coerced to low-information")
        normalized["validation_warnings"] = warnings

    # Counterforce / blocker discipline — high-likelihood blockers
    # need proof or falsifier coverage; without it the chain has a
    # known interruption that the desk cannot watch.  Coerces to
    # low-information when the thesis is structurally untestable;
    # ``watch_only`` is advisory and surfaces via
    # ``evidence_quality_tier``.
    blocker_audit = evaluate_blocker_discipline(normalized)
    if blocker_audit["downgrade"] == "low_information":
        normalize_low_information(normalized)
        warnings = list(normalized.get("validation_warnings") or [])
        warnings.append("uncovered high-risk blocker(s) — coerced to low-information")
        normalized["validation_warnings"] = warnings
    elif blocker_audit["downgrade"] == "watch_only":
        warnings = list(normalized.get("validation_warnings") or [])
        warnings.append("high-risk blocker without proof coverage — capped to watch_only")
        normalized["validation_warnings"] = warnings
        # Cap confidence at medium so the UI can't ship the call as
        # high-confidence with an uncovered blocker.
        if normalized.get("confidence") == "high":
            normalized["confidence"] = "medium"

    # Causal-strength check — when the chain is below the proof-
    # retention floor (≥2 prongs missing), strip the proof / falsifier /
    # critical_breakpoints lists so a thin mechanism doesn't ship with
    # an elaborate test plan it never earned.  Score-driven; the
    # tier / low-info classification reads the same score downstream.
    if clear_weak_chain_proof(normalized):
        warnings = list(normalized.get("validation_warnings") or [])
        warnings.append(
            "weak causal chain — proof / falsifier structure cleared",
        )
        normalized["validation_warnings"] = warnings

    # Mechanism subtype is normalised inside ``_normalize_schema`` so
    # the family-fallback step has already run.  No extra work here.

    # Source quality — populate the optional hidden_mechanism block
    # from headline + what_changed when the LLM didn't emit one.  The
    # tier classifier reads specificity to cap low-specificity
    # headlines at watch_only; without an inferred default, legacy
    # analyses would never hit that gate even on speculative reports.
    hm = normalized.get("hidden_mechanism") or {}
    if isinstance(hm, dict) and not hm.get("source_quality"):
        inferred_quality = _infer_source_quality(
            headline, normalized.get("what_changed", ""),
        )
        cleaned_quality = _clean_source_quality(inferred_quality)
        if cleaned_quality:
            hm = {**hm, "source_quality": cleaned_quality}
            normalized["hidden_mechanism"] = hm

    # Thesis timing — derive expected_reaction_window /
    # follow_through_window / stale_after / timing_rationale from
    # stage + persistence (+ family / subtype hints).  Stage-aware
    # re-clean fires on any LLM-emitted block so anticipation events
    # can't smuggle in realized-event timing; when no LLM block
    # survives, inference fills the slot.
    ct = normalized.get("competing_thesis")
    if isinstance(ct, dict) and ct:
        existing_timing = ct.get("thesis_timing")
        if isinstance(existing_timing, dict):
            re_cleaned = _clean_thesis_timing(existing_timing, stage=stage)
            if re_cleaned:
                ct["thesis_timing"] = re_cleaned
            else:
                ct.pop("thesis_timing", None)
        if not ct.get("thesis_timing"):
            inferred_timing = _infer_thesis_timing(
                stage,
                persistence,
                normalized.get("mechanism_family"),
                normalized.get("mechanism_subtype"),
            )
            cleaned_timing = _clean_thesis_timing(inferred_timing, stage=stage)
            if cleaned_timing:
                ct["thesis_timing"] = cleaned_timing

    # Chain-family consistency — transmission_path hops must use
    # channels the committed mechanism_family supports.  A mostly-
    # off-family chain coerces the study to low-information; a
    # partial conflict caps the call at watch_only.
    chain_family = evaluate_chain_family_consistency(normalized)
    if chain_family["downgrade"] == "low_information":
        normalize_low_information(normalized)
        warnings = list(normalized.get("validation_warnings") or [])
        warnings.append(
            f"transmission_path conflicts with mechanism_family "
            f"({chain_family['off_family']}/"
            f"{chain_family['checked']} hops off-family) — coerced to low-information",
        )
        normalized["validation_warnings"] = warnings
    elif chain_family["downgrade"] == "watch_only":
        warnings = list(normalized.get("validation_warnings") or [])
        warnings.append(
            f"transmission_path partially off-family "
            f"({chain_family['off_family']}/"
            f"{chain_family['checked']} hops) — capped to watch_only",
        )
        normalized["validation_warnings"] = warnings
        if normalized.get("confidence") == "high":
            normalized["confidence"] = "medium"

    # Strict low-information gate — runs here, after ticker buckets
    # are finalised, so the concrete-asset prong sees the real
    # ``beneficiary_tickers`` / ``loser_tickers`` / ``assets_to_watch``
    # lists.  When the gate fires, the study is coerced to a clean
    # low-information shape (confidence=low, empty proof / falsifier,
    # family=none, vague narrative assets stripped).
    gate = apply_low_information_gate(normalized)
    if gate["is_low_info"]:
        normalized["mechanism_family"] = "none"
        first, second = _resolve_channel_packs("none", [], [])
        normalized["expected_first_order_channels"] = first
        normalized["expected_second_order_channels"] = second

    # Blended-mechanism gate — separate from the filler-text gate but
    # routes to the same low-information shape so a multi-channel mash
    # doesn't surface as a confident analysis.  Ranked asset buckets
    # are cleared because their rationales can't be trusted to tie to
    # any single chosen mechanism.
    if not gate["is_low_info"] and mech_blended:
        from low_information_gate import normalize_low_information
        normalize_low_information(normalized)
        normalized["mechanism_family"] = "none"
        first, second = _resolve_channel_packs("none", [], [])
        normalized["expected_first_order_channels"] = first
        normalized["expected_second_order_channels"] = second
        normalized["primary_assets"] = []
        normalized["secondary_assets"] = []
        normalized["hedge_or_signal_assets"] = []
        warnings = list(normalized.get("validation_warnings") or [])
        warnings.append("blended mechanism — coerced to low-information")
        normalized["validation_warnings"] = warnings

    # Evidence-quality tier — internal three-state classification
    # (actionable / watch_only / low_information) that gates how
    # confidently the output ships.  ``low_information`` was already
    # coerced above by ``apply_low_information_gate``; we re-read here
    # so the tier reflects the post-coercion shape.  Surfaced via
    # ``validation_warnings`` (existing list field) so the tier is
    # observable downstream without adding a new top-level enum.
    from low_information_gate import calibrate_confidence, evidence_quality_tier
    tier = evidence_quality_tier(normalized)

    # Confidence is now DERIVED from evidence quality rather than the
    # LLM's prose.  ``calibrate_confidence`` reads the tier + proof /
    # falsifier coverage and returns one of low / medium / high:
    #   * low_information → "low"
    #   * watch_only      → "medium"  (never "high")
    #   * actionable + proof + falsifier → "high"
    #   * actionable but thin coverage  → "medium"
    # Replaces the previous one-sided "watch_only caps high → medium"
    # rule and unifies the per-gate confidence caps higher up.
    calibrated = calibrate_confidence(normalized)
    if normalized.get("confidence") != calibrated:
        warnings = list(normalized.get("validation_warnings") or [])
        warnings.append(
            f"confidence calibrated → {calibrated} (from evidence quality)",
        )
        normalized["validation_warnings"] = warnings
    normalized["confidence"] = calibrated

    # Optional derived fields — confidence_rationale explains the
    # calibrated confidence in concrete factor language; counterfactual_check
    # surfaces the explicit "what would break this" block linked back to
    # key_falsifiers.  Both are pure reads of the post-calibration shape.
    from low_information_gate import (
        compose_actionability_check,
        compose_confidence_rationale,
        compose_counterfactual_check,
    )
    normalized["confidence_rationale"] = compose_confidence_rationale(normalized)
    normalized["counterfactual_check"] = compose_counterfactual_check(normalized)
    normalized["actionability_check"] = compose_actionability_check(normalized)

    warnings = list(normalized.get("validation_warnings") or [])
    tier_tag = f"evidence_quality: {tier}"
    if tier_tag not in warnings:
        warnings.append(tier_tag)
        normalized["validation_warnings"] = warnings

    # Top-level engine-tier field — closed set (low_information /
    # watch_only / actionable).  Mirrors the ``evidence_quality:`` tag
    # in ``validation_warnings`` so consumers can branch on a real
    # field instead of parsing prose.
    normalized["quality_tier"] = tier

    # Compact failure-mode tags — short machine-readable strings the UI
    # / audit can branch on without parsing prose.  Only stamp the
    # ``quality_warnings`` field on ``watch_only`` / ``low_information``
    # outputs; clean actionable outputs get nothing so the field
    # absence itself signals "no warnings".
    if tier in ("watch_only", "low_information"):
        from low_information_gate import quality_warnings
        tags = quality_warnings(normalized)
        if tags:
            normalized["quality_warnings"] = tags

    # Weak-output detection → degraded fallback
    weak_reason = _detect_weak_output(normalized)
    if weak_reason is not None:
        return _strip_scratch_fields(_degraded_fallback(
            headline, stage, persistence, weak_reason,
            preserved_tickers=beneficiary_tickers,
        ))

    return _strip_scratch_fields(_validate_result(normalized, stage))
