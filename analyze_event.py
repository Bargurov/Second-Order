import os
import json
import re

# ---------------------------------------------------------------------------
# Ticker sanitizer
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
    "LGES",
    # Thin-float or low-AUM tickers with unreliable yfinance data
    # ARNC = Arconic Corp (inconsistent coverage after Howmet spinoff)
    # EGPT = VanEck Egypt ETF (very low volume, frequently returns empty data)
    "ARNC", "EGPT",
}

# Keyword → US-proxy-ETF fallback map.
# Used only when too few clean tickers survive filtering.
# Keywords are matched against the lowercased headline + mechanism text.
_PROXY_MAP = [
    (["semiconductor", "chip", "foundry", "lithography", "wafer", "fab"],  ["SMH", "SOXX"]),
    (["palladium", "platinum", "pgm", "precious metal"],                    ["PALL", "PPLT"]),
    (["metal", "mining", "copper", "nickel", "aluminum", "steel"],          ["XME", "COPX"]),
    (["lng", "liquefied natural gas", "gas export", "gas terminal"],        ["LNG", "UNG"]),
    (["oil", "crude", "opec", "petroleum", "refin", "brent", "barrel"],     ["XLE", "USO", "BNO"]),
    (["shipping", "tanker", "freight", "vessel", "maritime", "chokepoint"], ["FRO", "STNG"]),
    (["gold", "safe haven", "geopolit", "conflict", "war risk"],            ["GLD"]),
    (["treasury", "rate cut", "rate hike", "central bank", "yield"],        ["TLT", "IEF"]),
    (["ev", "electric vehicle", "battery", "lithium"],                      ["DRIV", "LIT"]),
    (["wheat", "grain", "agriculture", "soybean", "corn"],                  ["WEAT", "DBA"]),
    (["defense", "military", "weapon", "nato", "arms"],                     ["ITA", "XAR"]),
    (["china", "chinese"],                                                   ["FXI", "KWEB"]),
]


def _is_bad_ticker(ticker: str) -> bool:
    """Return True if the ticker is an index, benchmark, or otherwise unusable.

    Catches: known-bad symbols, foreign-exchange suffixes (.T .L .TO),
    index/special characters (^ = / space), and empty strings.
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

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from prompts import SYSTEM_PROMPT, EVENT_ANALYSIS_PROMPT

_PLACEHOLDER = "your_api_key_here"


def _extract_json(text: str) -> dict | None:
    """Extract the last valid JSON object from a messy model response.

    Handles all known failure modes:
    - Fenced blocks: ```json { ... } ``` or ``` { ... } ```
    - Extra prose before or after the JSON
    - Multiple JSON attempts (e.g. model self-corrects): returns the LAST valid one,
      because when Claude appends a revised block, the last block is the intended answer.

    Returns None if no valid JSON object is found anywhere in the text.

    How raw_decode works (useful to know):
      json.JSONDecoder().raw_decode(s, idx) parses one JSON value starting at
      position idx, ignoring any text that follows. It returns (object, end_pos).
      This lets us find JSON objects embedded in prose without any regex tricks.
    """
    candidates = []

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


def _validate_result(result: dict, stage: str) -> dict:
    """Apply post-parse validation rules and attach warnings to the result.

    Rules:
    1. beneficiary_tickers must be a non-empty list after sanitization.
    2. mechanism_summary must be a string longer than 20 characters.
    3. If stage is "anticipation" and confidence is "high", downgrade to "medium"
       (belt-and-suspenders in case the prompt rule was ignored).

    The result is never rejected — warnings are collected in
    result["validation_warnings"]. The key is only added when at least one
    rule fires, so clean results stay uncluttered.
    """
    warnings = []

    # Rule 1: at least one beneficiary ticker must survive sanitization
    beneficiary_tickers = result.get("beneficiary_tickers", [])
    if not isinstance(beneficiary_tickers, list) or len(beneficiary_tickers) == 0:
        warnings.append("beneficiary_tickers is empty after sanitization")

    # Rule 2: mechanism_summary must be a real sentence, not a placeholder
    summary = result.get("mechanism_summary", "")
    if not isinstance(summary, str) or len(summary.strip()) <= 20:
        warnings.append("mechanism_summary is too short or missing")

    # Rule 3: anticipation + high confidence is logically inconsistent
    if stage == "anticipation" and result.get("confidence") == "high":
        result["confidence"] = "medium"
        warnings.append("confidence downgraded high → medium (stage is anticipation)")

    if warnings:
        result["validation_warnings"] = warnings

    return result


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
    }


def _coerce_ticker_field(value) -> list[str]:
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


def analyze_event(headline: str, stage: str, persistence: str,
                   event_context: str = "") -> dict:
    """
    Call the LLM and return a structured analysis of the event.
    Falls back to a mock response if the key is missing or the call fails.

    event_context: optional multi-source context string.  When provided it is
    injected into the prompt so the model can weigh corroboration, source
    reliability, and inter-source disagreement.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")

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
            model="claude-opus-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        # Guard: API can return an empty content list on rare errors
        if not message.content:
            print("[analyze_event] API returned empty content list.")
            return _mock("empty API response")

        raw = message.content[0].text
        result = _extract_json(raw)

        if result is None:
            print("[analyze_event] Could not parse LLM response as JSON.")
            print(f"  → Raw response: {raw}\n")
            return _mock("JSON parse error")

        # Ensure every expected key exists — the LLM occasionally omits one.
        result.setdefault("what_changed", "")
        result.setdefault("mechanism_summary", "")
        result.setdefault("beneficiaries", [])
        result.setdefault("losers", [])
        result.setdefault("confidence", "low")

        # Sanitize both ticker lists separately, then merge into assets_to_watch
        # for backward-compatible db storage.
        context = f"{headline} {result.get('mechanism_summary', '')}"

        raw_ben = _coerce_ticker_field(result.get("beneficiary_tickers"))
        raw_los = _coerce_ticker_field(result.get("loser_tickers"))

        beneficiary_tickers = _clean_assets(raw_ben, context=context)
        loser_tickers = _clean_assets(raw_los, context=context)
        # Merge while preserving order and removing duplicates
        seen: set = set()
        assets_to_watch = []
        for t in beneficiary_tickers + loser_tickers:
            if t not in seen:
                seen.add(t)
                assets_to_watch.append(t)

        result["beneficiary_tickers"] = beneficiary_tickers
        result["loser_tickers"] = loser_tickers
        result["assets_to_watch"] = assets_to_watch
        result = _validate_result(result, stage)
        return result

    except ImportError:
        print("[analyze_event] 'anthropic' package not installed.")
        print("  → Run: pip install anthropic python-dotenv\n")
        return _mock("anthropic not installed")

    except Exception as e:
        print(f"[analyze_event] API call failed: {e}\n")
        return _mock(str(e))
