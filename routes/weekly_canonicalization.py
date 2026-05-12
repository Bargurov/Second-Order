"""Weekly Section C post-cache canonicalization helper.

A small read-only helper that collapses Weekly Market cards sharing
a normalised headline into a single canonical card with
``duplicate_count`` and ``grouped_event_ids`` attached.  Called by
``routes.movers.movers_weekly`` exactly once, between the
``_sanitize_movers_with_meta`` step and ``_project``.

Read-only by construction
-------------------------

* The helper takes a list of already-sanitised UI card dicts and
  returns a new list — the input list is never mutated in place.
* No DB connection, no event-row mutation, no cache write, no
  filesystem side effect.  The underlying ``events.db`` rows are
  untouched.
* No ``yfinance``, ``market_data``, LLM, or paid provider import.
  The module is small on purpose so the Weekly surface change
  carries the smallest possible production surface.

Daily and Still Moving Market never call this helper.  The
canonicalization is scoped to the Weekly route by construction —
``routes.movers.movers_weekly`` is the only caller.

Algorithm
---------

For each input card with a non-empty headline:

1. Normalise the headline to a canonical token sequence
   (lowercase letters/digits joined by single spaces).
2. Group cards by their normalised headline.
3. For each group of ≥2 cards:

   * Pick the *canonical* card: the longest non-truncated headline,
     tie-breaking on lowest ``event_id``.  Truncated / mid-feed /
     mid-sentence headlines are skipped where possible; if every
     candidate looks truncated, fall back to the lowest-``event_id``
     card without claiming any pick is the only reasonable one.
   * Copy the canonical card; set ``duplicate_count`` to
     ``len(group) - 1`` and ``grouped_event_ids`` to the sorted list
     of every group member's ``event_id``.
   * Drop the non-canonical group members from the output.

4. Cards whose headline is empty or non-string pass through
   unchanged.  Singleton-group cards pass through unchanged
   (``duplicate_count`` is NOT added — the canonicalization
   metadata is only added when a real collapse happened).

Order is preserved: the canonical card surfaces at the position of
the *first* group member in the input order, so a downstream ranker
sees the collapsed list in the same ranking order it would have
seen the duplicates.

Conservative wording — the module emits no operator-facing prose,
only structured fields.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = ("collapse_weekly_duplicates",)


# Token bands the canonical-pick treats as "looks truncated" or
# "looks mid-feed".  Mirror the planner's heuristic in spirit.
_ELLIPSIS_SUFFIXES: tuple[str, ...] = ("…", "...")


def collapse_weekly_duplicates(
    items: Any,
) -> list[dict[str, Any]]:
    """Collapse same-headline duplicate clusters in a Weekly card list.

    See module docstring for the algorithm and contract.

    The function is defensive: a non-list input returns an empty
    list; non-dict entries pass through unchanged in position.
    """
    if not isinstance(items, list):
        return []
    if not items:
        return []

    # Group cards by normalised headline.  The group is collected
    # in input order so the canonical's emission position matches
    # the first occurrence of the group.
    groups: dict[str, list[dict[str, Any]]] = {}
    for card in items:
        if not isinstance(card, dict):
            continue
        norm = _normalise(card.get("headline"))
        if not norm:
            continue
        groups.setdefault(norm, []).append(card)

    # Walk the input in order; for each card decide whether to emit
    # the canonical (first time we see the group) or drop (subsequent
    # group members), or pass through (no group / non-dict / no
    # headline).
    out: list[dict[str, Any]] = []
    emitted: set[str] = set()
    for card in items:
        if not isinstance(card, dict):
            out.append(card)
            continue
        norm = _normalise(card.get("headline"))
        if not norm:
            out.append(card)
            continue
        group = groups.get(norm, [])
        if len(group) <= 1:
            out.append(card)
            continue
        if norm in emitted:
            # A later occurrence of the same group — drop.
            continue
        canonical_card = _pick_canonical(group)
        out.append(_with_duplicate_meta(canonical_card, group))
        emitted.add(norm)
    return out


# ---------------------------------------------------------------------------
# Internal helpers — pure functions, all stdlib
# ---------------------------------------------------------------------------


def _normalise(headline: Any) -> str:
    """Tokenise a headline into space-joined lowercase alnum tokens.
    Returns an empty string for non-strings, empty strings, or strings
    with no alnum content."""
    if not isinstance(headline, str):
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", headline.lower()))


def _looks_truncated(headline: Any) -> bool:
    """Return True if the headline looks raw / mid-feed / truncated.

    Conservative: returns False when in doubt so a clean candidate
    can win the canonical-pick.
    """
    if not isinstance(headline, str):
        return True
    h = headline.strip()
    if not h:
        return True
    if any(h.endswith(s) for s in _ELLIPSIS_SUFFIXES):
        return True
    if "..." in h and not h.endswith("..."):
        # Mid-string ellipsis is a strong truncation signal.
        return True
    if h[0].isalpha() and h[0].islower():
        # Mid-sentence leak.
        return True
    return False


def _event_id_for_sort(card: dict[str, Any]) -> int:
    """Coerce ``event_id`` to an int for tie-breaking.  Cards
    without a usable event_id sort to the end so they lose the
    tie-break to cards that have a stable id."""
    v = card.get("event_id")
    if isinstance(v, bool):
        return 1_000_000_000
    if isinstance(v, int):
        return v
    return 1_000_000_000


def _pick_canonical(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the canonical card from a same-headline group.

    Priority:
      1. Longest non-truncated headline; tie-break on lowest
         ``event_id``.
      2. If every candidate looks truncated, fall back to the
         lowest-``event_id`` member of the group.
    """
    clean = [
        c for c in group
        if isinstance(c.get("headline"), str)
        and not _looks_truncated(c.get("headline"))
    ]
    if clean:
        return max(
            clean,
            key=lambda c: (len(c.get("headline") or ""),
                           -_event_id_for_sort(c)),
        )
    return min(group, key=_event_id_for_sort)


def _grouped_event_ids(group: list[dict[str, Any]]) -> list[int]:
    """Sorted unique ``event_id`` list across a group, ignoring
    cards without a usable ``event_id``."""
    out: set[int] = set()
    for c in group:
        if not isinstance(c, dict):
            continue
        v = c.get("event_id")
        if isinstance(v, int) and not isinstance(v, bool):
            out.add(v)
    return sorted(out)


def _with_duplicate_meta(
    canonical: dict[str, Any],
    group: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a shallow copy of ``canonical`` with
    ``duplicate_count`` and ``grouped_event_ids`` attached."""
    out = dict(canonical)
    out["duplicate_count"]   = max(0, len(group) - 1)
    out["grouped_event_ids"] = _grouped_event_ids(group)
    return out
