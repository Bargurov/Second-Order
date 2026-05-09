#!/usr/bin/env python3
"""Read-only sector benchmark suggestion report for manual candidates.

Wraps the manual ticker repair packet and emits a per-row sector
benchmark hint drawn from a small conservative ETF universe.  The
report's only judgement axis is which of the ten allowed benchmarks
plausibly matches the candidate; everything else is operator work.

The conservative ETF universe is::

    energy                    XLE
    financials                XLF
    tech                      XLK
    industrials               XLI
    materials                 XLB
    healthcare                XLV
    real_estate               XLRE
    consumer_discretionary    XLY
    utilities                 XLU
    broad                     SPY    # fallback when no sector hit

A suggestion is a HINT, not a correction.  The report never writes to
the archive, never claims the operator's existing primary ticker is
wrong, never calls a provider, an LLM, ``yfinance``, or any FastAPI
surface.  Whenever the classifier cannot place the candidate
confidently, it falls back to ``broad``/``SPY`` with
``confidence="none"`` and per-row ``needs_manual_review=true`` — the
operator must decide by hand.

Output contract (JSON)::

    {
      "ok":                      bool,
      "candidate_count":         int,    # full upstream packet count
      "suggestions": [                     # truncated by --limit
        {
          "event_id":               int,
          "headline":               str | None,
          "event_date":             str | None,
          "current_primary_ticker": str | None,
          "manual_review_priority": str,
          "flags":                  list[str],
          "suggested_sector":       str,   # one of the ten sector keys
          "suggested_benchmark":    str,   # one of the ten ETFs
          "confidence":             "high" | "medium" | "low" | "none",
          "rationale":              str,   # pipe-joined safe tokens
          "needs_manual_review":    bool,
        },
        ...
      ],
      "confidence":   { "high": int, "medium": int, "low": int, "none": int },
      "needs_manual_review":      int,    # count of rows flagged
      "recommended_next_action":  str,
    }

Confidence tiers:

* ``high``   — the candidate's ``current_primary_ticker`` is in a
               small known-sector universe.  Direct match.
* ``medium`` — no ticker hit, but the headline carries a single
               sector's worth of keywords.
* ``low``    — the headline carries hints from multiple sectors at
               once and no ticker resolves the tie.  Fallback to
               broad/SPY; needs manual review.
* ``none``   — no ticker, no recognisable keyword, no signal.
               Fallback to broad/SPY; needs manual review.

Patchable seam
--------------

  * ``_run_repair_packet`` — wraps
    :func:`scripts.manual_ticker_repair_packet.summarize_repair_packet`
    with ``priority="all"`` so every shortlisted candidate carries a
    suggestion.  Tests patch this attribute directly.

Out of scope (deliberately)
---------------------------
* Read-only.  The script issues no SQL of its own; every DB read flows
  through the upstream packet's SELECT-only path.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI surface — never imports ``api`` or ``routes.*``.
* Never assigns benchmarks into the archive; suggestions are hints.

Usage::

    python scripts/sector_benchmark_suggestion_report.py
    python scripts/sector_benchmark_suggestion_report.py --json --limit 50
    python scripts/sector_benchmark_suggestion_report.py --json --db-path ./events.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT: int = 25


# Effectively unlimited per-event cap when delegating to the upstream
# packet.  Aggregate counts must reflect every shortlisted row;
# operator ``--limit`` only truncates the emitted suggestions list.
_PACKET_FETCH_ALL: int = 10**12


# ---------------------------------------------------------------------------
# Conservative ETF universe — pinned in tests as a closed set.
# ---------------------------------------------------------------------------


_SECTOR_BENCHMARK: dict[str, str] = {
    "energy":                 "XLE",
    "financials":             "XLF",
    "tech":                   "XLK",
    "industrials":            "XLI",
    "materials":              "XLB",
    "healthcare":             "XLV",
    "real_estate":            "XLRE",
    "consumer_discretionary": "XLY",
    "utilities":              "XLU",
    "broad":                  "SPY",
}


_ALLOWED_CONFIDENCE: tuple[str, ...] = ("high", "medium", "low", "none")


# Ticker -> sector lookup.  Deliberately small and conservative —
# additions should only land here when the ticker's sector membership
# is unambiguous.  ``DRIV`` / ``LIT`` are intentionally absent: those
# thematic ETFs are exactly the symbols flagged by the upstream
# contamination report as off-topic, so a ticker-based suggestion would
# echo the bug.
_TICKER_TO_SECTOR: dict[str, str] = {
    # Sector ETFs — self-classify into their own sector.
    "XLE":  "energy",
    "XLF":  "financials",
    "XLK":  "tech",
    "XLI":  "industrials",
    "XLB":  "materials",
    "XLV":  "healthcare",
    "XLRE": "real_estate",
    "XLY":  "consumer_discretionary",
    "XLU":  "utilities",

    # Energy.
    "XOM":  "energy", "CVX":  "energy", "COP":  "energy",
    "OXY":  "energy", "SLB":  "energy", "MPC":  "energy",
    "VLO":  "energy", "PSX":  "energy", "EOG":  "energy",

    # Financials.
    "JPM":  "financials", "BAC":  "financials", "WFC":  "financials",
    "GS":   "financials", "MS":   "financials", "SCHW": "financials",
    "BLK":  "financials", "C":    "financials", "USB":  "financials",
    "PNC":  "financials", "AXP":  "financials",

    # Tech.
    "AAPL": "tech", "MSFT": "tech", "GOOG": "tech", "GOOGL": "tech",
    "META": "tech", "NVDA": "tech", "ORCL": "tech", "CRM":  "tech",
    "ADBE": "tech", "AMD":  "tech", "INTC": "tech", "CSCO": "tech",
    "AVGO": "tech", "QCOM": "tech",

    # Healthcare.
    "JNJ":  "healthcare", "PFE":  "healthcare", "UNH":  "healthcare",
    "MRK":  "healthcare", "LLY":  "healthcare", "ABBV": "healthcare",
    "TMO":  "healthcare", "ABT":  "healthcare", "BMY":  "healthcare",
    "GILD": "healthcare",

    # Industrials.
    "CAT":  "industrials", "DE":   "industrials", "HON":  "industrials",
    "UNP":  "industrials", "GE":   "industrials", "BA":   "industrials",
    "EMR":  "industrials", "ETN":  "industrials", "LMT":  "industrials",
    "RTX":  "industrials", "NOC":  "industrials",

    # Materials.
    "FCX":  "materials", "NEM":  "materials", "NUE":  "materials",
    "DOW":  "materials", "LIN":  "materials", "SHW":  "materials",
    "APD":  "materials",

    # Real estate.
    "PLD":  "real_estate", "AMT":  "real_estate", "EQIX": "real_estate",
    "PSA":  "real_estate", "SPG":  "real_estate", "O":    "real_estate",
    "WELL": "real_estate",

    # Consumer discretionary.
    "AMZN": "consumer_discretionary", "TSLA": "consumer_discretionary",
    "HD":   "consumer_discretionary", "MCD":  "consumer_discretionary",
    "NKE":  "consumer_discretionary", "LOW":  "consumer_discretionary",
    "SBUX": "consumer_discretionary", "BKNG": "consumer_discretionary",

    # Utilities.
    "NEE":  "utilities", "DUK":  "utilities", "SO":   "utilities",
    "AEP":  "utilities", "SRE":  "utilities", "D":    "utilities",
    "EXC":  "utilities", "XEL":  "utilities",
}


# Headline keyword -> sector lookup.  Each phrase is matched as a
# lowercase substring against the headline text.  Phrases are tuned to
# avoid the conservative-wording deny-list (no ``correct``, ``replace``,
# ``propose``, ``assign``, ``fix the``, ``automatic``, ``delete``,
# ``auto-correct``, ``auto fix``).
_HEADLINE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "energy": (
        "oil", "crude", "opec", "refinery", "refineries", "gasoline",
        "drilling", "natural gas", "lng", "shale", "petroleum",
    ),
    "financials": (
        "bank", "banks", "lender", "lending", "deposit",
        "mortgage", "federal reserve", "credit card",
    ),
    "tech": (
        "software", "semiconductor", "chip", "chipmaker", "cloud",
        "artificial intelligence",
    ),
    "healthcare": (
        "pharma", "pharmaceutical", "drug", "vaccine", "clinical",
        "biotech", " fda ",
    ),
    "industrials": (
        "airline", "airlines", "defense contractor", "manufacturing",
        "machinery", "freight", "rail ", "railroad", "logistics",
    ),
    "materials": (
        "mining", "miner", "metals", "gold ", "copper", "steel",
        "lithium", "fertilizer",
    ),
    "real_estate": (
        "reit", "real estate",
    ),
    "consumer_discretionary": (
        "retailer", "retail sales", "e-commerce", "apparel",
        "automaker",
    ),
    "utilities": (
        "utility", "utilities", "electric utility", "power grid",
    ),
}


# ---------------------------------------------------------------------------
# Recommended-next-action wording — banned-word-free.
# ---------------------------------------------------------------------------


_RECOMMENDED_EMPTY = (
    "No manual candidates returned by the upstream packet — sector "
    "benchmark suggestion is not required for this slice."
)
_RECOMMENDED_HAS_CANDIDATES = (
    "{n} candidate(s) carry sector benchmark suggestions for operator "
    "review.  Each suggestion is a hint only — the operator must "
    "inspect the headline by hand and decide on the final benchmark."
)


# ---------------------------------------------------------------------------
# Patchable seam
# ---------------------------------------------------------------------------


def _run_repair_packet(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the manual ticker repair packet with ``priority="all"``
    and an effectively unlimited per-row cap.  Tests patch this
    attribute directly so the import only resolves on the un-patched
    path.
    """
    from scripts.manual_ticker_repair_packet import (
        summarize_repair_packet,
    )

    return summarize_repair_packet(
        db_path=db_path, limit=_PACKET_FETCH_ALL, priority="all",
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_sector_benchmark_suggestions(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Build the sector benchmark suggestion payload.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)

    packet = _safe_dict(_run_repair_packet(db_path=db_path))
    raw_candidates = packet.get("candidates")
    if not isinstance(raw_candidates, list):
        raw_candidates = []

    suggestions: list[dict[str, Any]] = []
    for c in raw_candidates:
        if not isinstance(c, dict):
            continue
        ev_id = c.get("event_id")
        if not isinstance(ev_id, int):
            continue
        flags_raw = c.get("flags") or []
        flags = [f for f in flags_raw if isinstance(f, str)] \
            if isinstance(flags_raw, list) else []
        sector, benchmark, confidence, rationale = _classify(
            ticker=c.get("current_primary_ticker"),
            headline=c.get("headline"),
        )
        suggestions.append({
            "event_id":               ev_id,
            "headline":               c.get("headline"),
            "event_date":             c.get("event_date"),
            "current_primary_ticker": c.get("current_primary_ticker"),
            "manual_review_priority": c.get("manual_review_priority"),
            "flags":                  flags,
            "suggested_sector":       sector,
            "suggested_benchmark":    benchmark,
            "confidence":             confidence,
            "rationale":              rationale,
            "needs_manual_review":    confidence in ("low", "none"),
        })

    candidate_count = len(suggestions)
    confidence_agg = {k: 0 for k in _ALLOWED_CONFIDENCE}
    needs_manual_review = 0
    for entry in suggestions:
        confidence_agg[entry["confidence"]] += 1
        if entry["needs_manual_review"]:
            needs_manual_review += 1

    truncated = suggestions[:capped_limit]

    return {
        "ok":                       True,
        "candidate_count":          candidate_count,
        "suggestions":              truncated,
        "confidence":               confidence_agg,
        "needs_manual_review":      needs_manual_review,
        "recommended_next_action":  _recommend(candidate_count),
    }


def _classify(
    *, ticker: Any, headline: Any,
) -> tuple[str, str, str, str]:
    """Classify a single candidate into ``(sector, benchmark, confidence,
    rationale)``.

    Resolution order:

      1. Direct ticker match against :data:`_TICKER_TO_SECTOR`
         → ``high`` confidence.
      2. Headline keyword scan — if exactly one sector matches, return
         it at ``medium`` confidence.
      3. Headline keyword scan — if multiple sectors match, fall back
         to ``broad``/``SPY`` at ``low`` confidence
         (``needs_manual_review=true`` upstream).
      4. No signal at all → ``broad``/``SPY``/``none``
         (``needs_manual_review=true`` upstream).
    """
    if isinstance(ticker, str) and ticker.strip():
        sym = ticker.strip().upper()
        sector = _TICKER_TO_SECTOR.get(sym)
        if sector is not None:
            return (
                sector,
                _SECTOR_BENCHMARK[sector],
                "high",
                f"ticker_match_{sector}",
            )

    if isinstance(headline, str) and headline.strip():
        text = headline.lower()
        matched_sectors: list[str] = []
        for sector, kws in _HEADLINE_KEYWORDS.items():
            for kw in kws:
                if kw in text:
                    matched_sectors.append(sector)
                    break
        if len(matched_sectors) == 1:
            sector = matched_sectors[0]
            return (
                sector,
                _SECTOR_BENCHMARK[sector],
                "medium",
                f"headline_keyword_{sector}",
            )
        if len(matched_sectors) > 1:
            return (
                "broad",
                _SECTOR_BENCHMARK["broad"],
                "low",
                "multi_sector_keywords|fallback_broad_market",
            )

    return (
        "broad",
        _SECTOR_BENCHMARK["broad"],
        "none",
        "no_signal|fallback_broad_market",
    )


def _recommend(candidate_count: int) -> str:
    if candidate_count <= 0:
        return _RECOMMENDED_EMPTY
    return _RECOMMENDED_HAS_CANDIDATES.format(n=candidate_count)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Sector benchmark suggestion report", ""]
    lines.append(f"Candidate count:          {report['candidate_count']}")
    agg = report.get("confidence") or {}
    lines.append("Confidence buckets:")
    for k in _ALLOWED_CONFIDENCE:
        lines.append(f"  {k:<7} {agg.get(k, 0)}")
    lines.append(f"Manual review needed:     {report['needs_manual_review']}")
    lines.append("")

    suggestions = report.get("suggestions") or []
    lines.append(f"Suggestions listed ({len(suggestions)}):")
    if suggestions:
        for entry in suggestions:
            headline = entry.get("headline") or "-"
            lines.append(
                f"  id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"priority={entry.get('manual_review_priority')} "
                f"ticker={entry.get('current_primary_ticker') or '-'} "
                f"=> sector={entry.get('suggested_sector')} "
                f"benchmark={entry.get('suggested_benchmark')} "
                f"confidence={entry.get('confidence')} "
                f"manual_review={entry.get('needs_manual_review')}"
            )
            lines.append(f"      headline:  {headline[:120]}")
            lines.append(f"      rationale: {entry.get('rationale')}")
    else:
        lines.append("  -")
    lines.append("")
    lines.append(f"Recommended next action: {report['recommended_next_action']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only sector benchmark suggestion report.  Wraps the "
            "manual ticker repair packet and emits a per-row sector "
            "benchmark hint drawn from a small conservative ETF "
            "universe (XLE / XLF / XLK / XLI / XLB / XLV / XLRE / XLY "
            "/ XLU / SPY).  Each suggestion is a hint only — the "
            "report never writes to the archive, never claims the "
            "operator's existing primary ticker is wrong, no provider, "
            "no LLM, no FastAPI surface."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--limit",
        type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced suggestions list at N entries (default "
            f"{_DEFAULT_LIMIT}).  ``candidate_count`` always reflects "
            f"every shortlisted candidate."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path", default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the report follows the project's "
            "configured archive."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_sector_benchmark_suggestions(
        db_path=args.db_path, limit=args.limit,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
