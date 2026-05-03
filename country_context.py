"""country_context.py

Compact per-country vulnerability backdrop for the analysis prompt.

When a headline clearly maps to a country that has a cached profile in
``country_backdrop.COUNTRY_BACKDROP_FIXTURE``, this module produces a
short multi-line text block the analyze route appends to the prompt's
``{macro_context}`` slot.  The LLM sees a deterministic, grounded
description of:

    external_balance_risk  — reserves + CA + ext debt read
    import_shock_risk      — fuel/food import dependence
    commodity_dependence   — commodity-export share tier
    overall_vulnerability  — worst-of cap
    rationale              — one-line numeric context

sharpening mechanism wording and asset selection on import-shock /
reserve-stress / external-balance cases without changing any saved
event shape.

Design contract:

* Pure composer — no I/O, no network, no DB.  Consumes only the
  in-process fixture via ``normalize_country_backdrop``.
* Matching is deterministic: fixture keys are scanned first by
  descending name length so ``"South Africa"`` wins over a short
  alias collision.  Case-insensitive whole-word match only, to
  avoid false positives on country codes that share a prefix with
  common English words.
* Returns ``""`` when no match exists so the caller can simply
  ``f"{base}\\n\\n{country_ctx}"`` without branching on emptiness
  and the prompt degrades to the pre-existing behaviour.
"""

from __future__ import annotations

import re
from typing import Optional

from country_backdrop import (
    COUNTRY_BACKDROP_FIXTURE,
    normalize_country_backdrop,
)


# Distinctive aliases → canonical fixture key.  Kept deliberately
# small: a multi-letter code is only admitted when it's
# distinguishable from common English words under a word-boundary
# match (``KSA`` yes; ``US`` no — it would hit "business", "trust").
_ALIASES: dict[str, str] = {
    "turkiye": "Turkey",
    "ksa":     "Saudi Arabia",
}


def _word_pattern(phrase: str) -> "re.Pattern[str]":
    """Case-insensitive word-bounded regex for a country phrase."""
    return re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)


def _build_patterns() -> list[tuple[str, "re.Pattern[str]"]]:
    """Return ``[(canonical, compiled_pattern), ...]`` used by the matcher.

    Fixture keys sorted by descending length so longer multi-word
    names (``South Africa``, ``Saudi Arabia``) win over any shorter
    substring match.  Aliases follow in registration order.
    """
    out: list[tuple[str, "re.Pattern[str]"]] = []
    fixture_keys = sorted(
        COUNTRY_BACKDROP_FIXTURE.keys(), key=lambda k: -len(k),
    )
    for name in fixture_keys:
        out.append((name, _word_pattern(name)))
    for alias, canonical in _ALIASES.items():
        if canonical in COUNTRY_BACKDROP_FIXTURE:
            out.append((canonical, _word_pattern(alias)))
    return out


_PATTERNS = _build_patterns()


def find_country_in_headline(headline: Optional[str]) -> Optional[str]:
    """Return the canonical fixture name a headline maps to, or ``None``.

    First match wins, evaluated over the patterns registered in
    ``_build_patterns``.  A headline that mentions multiple countries
    resolves to the first-seen fixture key under that sort order.
    """
    if not isinstance(headline, str) or not headline.strip():
        return None
    for canonical, pat in _PATTERNS:
        if pat.search(headline):
            return canonical
    return None


def build_country_backdrop_for_prompt(headline: Optional[str]) -> str:
    """Return the compact prompt block for a headline, or ``""``.

    Uses only the five task-pinned fields from
    ``normalize_country_backdrop``: ``external_balance_risk``,
    ``import_shock_risk``, ``commodity_dependence``,
    ``overall_vulnerability``, ``rationale``.  Emits a terse list
    (one dash-prefixed line per field) so the LLM treats it as
    structured context rather than prose.

    Returns ``""`` when:
      * ``headline`` is empty / non-string;
      * no fixture key matches the headline;
      * the fixture lookup returns ``None`` (belt-and-suspenders).

    The caller appends this to the existing ``macro_context`` when
    non-empty; when empty, the prompt is byte-identical to the
    pre-enrichment behaviour — preserving the "no profile → keep
    current behavior unchanged" contract.
    """
    country = find_country_in_headline(headline)
    if country is None:
        return ""
    block = normalize_country_backdrop(country)
    if block is None:
        return ""
    lines = [
        f"Country vulnerability backdrop for {block['country']} "
        f"(from cached profile):",
        f"- External balance risk: {block['external_balance_risk']}",
        f"- Import shock risk: {block['import_shock_risk']}",
        f"- Commodity dependence: {block['commodity_dependence']}",
        f"- Overall vulnerability: {block['overall_vulnerability']}",
    ]
    rationale = (block.get("rationale") or "").strip()
    if rationale:
        lines.append(f"- Rationale: {rationale}")
    return "\n".join(lines)
