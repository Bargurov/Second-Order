#!/usr/bin/env python3
"""Refresh-price-cache failure report parser.

Reads JSON output from ``scripts/refresh_price_cache.py`` (or any
payload with an ``errors[]`` list) and groups per-symbol failures
into a small fixed taxonomy:

  * ``operational_error``       — SQLite ``OperationalError`` from the
    cache or provider store ("unable to open database file",
    "database is locked", etc.).
  * ``invalid_ticker``           — ticker is delisted / no longer
    exists / explicitly invalid.
  * ``empty_provider_result``    — provider returned no data /
    empty dataframe / no rows.
  * ``unknown``                  — anything else.

Pure stdlib.  Read-only.  Never imports a provider, ``yfinance``, the
LLM, the project DB, or FastAPI — the parser is a transform over
already-emitted JSON.

Usage::

    cat refresh.json | python scripts/refresh_failure_report.py
    python scripts/refresh_failure_report.py --input refresh.json --json
    jq '.errors' refresh.json | python scripts/refresh_failure_report.py
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable, Sequence


CATEGORIES: tuple[str, ...] = (
    "operational_error",
    "invalid_ticker",
    "empty_provider_result",
    "unknown",
)

_EXAMPLES_LIMIT = 10

_INVALID_TICKER_NEEDLES = (
    "delisted",
    "invalid ticker",
    "no longer exists",
)

_EMPTY_PROVIDER_NEEDLES = (
    "no data",
    "no price data",
    "empty data",
    "empty dataframe",
    "no rows",
)


_RECOMMENDED_ACTIONS = {
    "operational_error": (
        "Provider/cache OperationalError dominates — fix the SQLite "
        "store path or permissions (typically a cwd issue on the "
        "price cache or events DB) and rerun the refresh."
    ),
    "invalid_ticker": (
        "Invalid/delisted tickers dominate — verify the symbols at the "
        "provider, exclude or remap them in the next refresh plan."
    ),
    "empty_provider_result": (
        "Provider returned empty data — widen the date range or verify "
        "ticker coverage at the provider for the requested interval."
    ),
    "unknown": (
        "Unclassified errors dominate — inspect the raw error strings "
        "and triage manually before rerunning."
    ),
}

_RECOMMENDED_OK = "No errors reported — refresh succeeded."


# ---------------------------------------------------------------------------
# Pure parser
# ---------------------------------------------------------------------------


def classify_error(error_text: str) -> str:
    """Map an error string to one of :data:`CATEGORIES`.

    Pure substring match (case-insensitive).  Order matters:
    ``operational_error`` is checked first (the SQLite signal is
    unambiguous), then ``invalid_ticker`` (delisted-ticker cues
    dominate over generic "no data" wording when both appear), then
    ``empty_provider_result``, otherwise ``unknown``.
    """
    text = (error_text or "").lower()
    if "operationalerror" in text:
        return "operational_error"
    if any(needle in text for needle in _INVALID_TICKER_NEEDLES):
        return "invalid_ticker"
    if any(needle in text for needle in _EMPTY_PROVIDER_NEEDLES):
        return "empty_provider_result"
    return "unknown"


def _coerce_errors(payload: Any) -> list[Any]:
    """Accept a refresh-script payload OR a raw ``errors[]`` list.

    Tolerates non-dict / non-list shapes by returning ``[]`` so the
    parser never raises on operator-level malformed input.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list):
            return errors
    return []


def parse_failures(
    payload: Any,
    *,
    examples_limit: int = _EXAMPLES_LIMIT,
) -> dict[str, Any]:
    """Group ``payload['errors']`` into the fixed taxonomy.

    Returns a dict with the contract keys ``ok``, ``total_errors``,
    ``grouped_counts``, ``affected_tickers``, ``examples``,
    ``recommended_next_action``.  The ``recommended_next_action``
    string tracks the dominant bucket; ties resolve to the first
    bucket in :data:`CATEGORIES` order.
    """
    errors = _coerce_errors(payload)
    grouped: dict[str, int] = {cat: 0 for cat in CATEGORIES}
    affected: set[str] = set()
    examples: list[dict[str, Any]] = []

    for entry in errors:
        if not isinstance(entry, dict):
            continue
        error_text = str(entry.get("error") or "")
        category = classify_error(error_text)
        grouped[category] += 1

        symbol = entry.get("symbol")
        if isinstance(symbol, str) and symbol:
            affected.add(symbol.upper())

        if len(examples) < examples_limit:
            examples.append({
                "event_id": entry.get("event_id"),
                "symbol":   entry.get("symbol"),
                "error":    error_text,
                "category": category,
            })

    total = sum(grouped.values())
    return {
        "ok":                       total == 0,
        "total_errors":             total,
        "grouped_counts":           grouped,
        "affected_tickers":         sorted(affected),
        "examples":                 examples,
        "recommended_next_action":  _recommend(grouped),
    }


def _recommend(grouped: dict[str, int]) -> str:
    if sum(grouped.values()) == 0:
        return _RECOMMENDED_OK
    dominant = max(CATEGORIES, key=lambda c: grouped[c])
    return _RECOMMENDED_ACTIONS[dominant]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Refresh failure report", ""]
    lines.append(f"Total errors: {report['total_errors']}")
    lines.append("")
    lines.append("Grouped counts:")
    for cat in CATEGORIES:
        lines.append(f"  {cat}: {report['grouped_counts'][cat]}")
    lines.append("")
    if report["affected_tickers"]:
        lines.append(
            "Affected tickers ("
            f"{len(report['affected_tickers'])}): "
            + ", ".join(report["affected_tickers"])
        )
    else:
        lines.append("Affected tickers: -")
    lines.append("")
    if report["examples"]:
        lines.append(f"First {len(report['examples'])} examples:")
        for index, ex in enumerate(report["examples"], start=1):
            sym = ex.get("symbol") or "-"
            cat = ex.get("category")
            lines.append(
                f"  {index:>2}. [{cat}] {sym}: {ex.get('error')}"
            )
    else:
        lines.append("Examples: -")
    lines.append("")
    lines.append(f"Recommended: {report['recommended_next_action']}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Group per-symbol failures from a refresh_price_cache.py "
            "JSON payload into a fixed taxonomy.  Read-only; pure "
            "stdlib transform."
        ),
    )
    parser.add_argument(
        "--input",
        dest="input",
        default=None,
        help=(
            "Path to a JSON file (refresh_price_cache.py payload or a "
            "raw errors[] list).  Reads stdin when omitted."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(
    argv: Sequence[str] | None = None,
    *,
    out: Any = None,
    stdin: Any = None,
) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    source = stdin if stdin is not None else sys.stdin

    try:
        if args.input:
            with open(args.input, "r", encoding="utf-8") as f:
                payload = json.load(f)
        else:
            payload = json.load(source)
    except json.JSONDecodeError as exc:
        print(f"refresh_failure_report: invalid JSON: {exc}",
              file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"refresh_failure_report: cannot read input: {exc}",
              file=sys.stderr)
        return 2

    report = parse_failures(payload)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
