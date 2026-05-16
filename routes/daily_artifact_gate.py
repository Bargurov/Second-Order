"""Daily Section C analyzed_event_artifact gate.

Read-only predicate the Daily branch of the movers route applies to
each candidate mover card before it surfaces in Section C.  A card
is admitted only when a reviewed
``analyzed_event_artifact_<candidate_id>.json`` file is present
under the caller-supplied ``artifact_dir`` and carries the three
artifact-backed fields the planner pins:

* ``mechanism_family`` — non-empty string, not the ``"none"``
  sentinel emitted by the mover-card normalizer when the field is
  missing upstream;
* ``primary_ticker`` — non-empty string;
* ``benchmark_ticker`` — non-empty string.

The fourth planner field, ``market_relevance``, is operator-supplied
at review time and is not enforced by this v1 gate.

A card without a ``candidate_id`` — or whose ``candidate_id`` points
at no artifact, an unreadable artifact, or an artifact missing one
of the three required fields — is *held for review*.  The mover
route surfaces the held count under
``envelope.meta.daily_artifact_gate.held_for_review_count`` rather
than dropping it silently.

Read-only by construction
-------------------------

* No DB writes, no ``yfinance`` / ``market_data`` / paid provider /
  LLM call, no FastAPI surface imported at module load.
* No mutation of the inbox, the news cache, the events DB, or the
  artifact directory.  The gate reads
  ``analyzed_event_artifact_<cid>.json`` and returns a verdict.
* The gate never assigns ``mechanism_family``; the field must
  already be on a reviewed artifact for the card to be admitted.
* The weekly canonicalization helper
  (:mod:`routes.weekly_canonicalization`) is not touched.  The
  Still Moving persistent gate
  (:func:`mover_card_normalizer.is_high_conviction_persistent`) is
  not touched.

See :mod:`scripts.section_c_daily_artifact_gate_plan` for the
design write-up this implementation pins.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


# Pinned by the planner — also referenced in the meta block so the
# operator can correlate an empty / partial Daily surface with the
# gate that produced it.
GATE_ID: str = "daily_section_c_requires_analyzed_event_artifact"


# Three artifact-backed fields the gate enforces.  ``market_relevance``
# stays operator-supplied at review time and is not enforced here.
_REQUIRED_ARTIFACT_FIELDS: tuple[str, ...] = (
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
)


_NONE_SENTINEL: str = "none"


def _artifact_path_for(
    *, candidate_id: str, artifact_dir: Path,
) -> Path:
    """Resolve the ``analyzed_event_artifact_<cid>.json`` file path."""
    return Path(artifact_dir) / f"analyzed_event_artifact_{candidate_id}.json"


def _read_artifact_doc(path: Path) -> dict[str, Any] | None:
    """Read the artifact as a JSON object.

    Returns the parsed dict on success, or ``None`` if the file is
    missing, unreadable, parses to a non-dict, or fails to parse.
    Read-only: the caller's filesystem is not modified.
    """
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(doc, dict):
        return None
    return doc


def _artifact_has_required_fields(doc: dict[str, Any]) -> bool:
    """Return ``True`` when every required field is a non-empty,
    non-``"none"`` string on the artifact body.
    """
    for field in _REQUIRED_ARTIFACT_FIELDS:
        value = doc.get(field)
        if not isinstance(value, str):
            return False
        stripped = value.strip()
        if not stripped:
            return False
        if field == "mechanism_family" and stripped.lower() == _NONE_SENTINEL:
            return False
    return True


def is_artifact_backed_daily_card(
    card: Any,
    *,
    artifact_dir: Path,
) -> bool:
    """Return ``True`` when the Daily card may be promoted to Section C.

    Admission rule (strict):

    * ``card`` is a dict;
    * ``card['candidate_id']`` is a non-empty string;
    * ``<artifact_dir>/analyzed_event_artifact_<candidate_id>.json``
      exists, parses as a JSON object, and carries non-empty
      ``mechanism_family`` / ``primary_ticker`` / ``benchmark_ticker``
      (with ``mechanism_family != "none"``).

    Any failed condition returns ``False`` so the card is held for
    review.  The gate never raises on bad input — it returns
    ``False`` instead so the route is not destabilised by a single
    malformed row.
    """
    if not isinstance(card, dict):
        return False
    cid_raw = card.get("candidate_id")
    if not isinstance(cid_raw, str):
        return False
    candidate_id = cid_raw.strip()
    if not candidate_id:
        return False
    path = _artifact_path_for(
        candidate_id=candidate_id, artifact_dir=Path(artifact_dir),
    )
    doc = _read_artifact_doc(path)
    if doc is None:
        return False
    return _artifact_has_required_fields(doc)


def filter_daily_section_c_cards(
    cards: Iterable[Any] | None,
    *,
    artifact_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply the gate to a list of Daily cards.

    Returns a ``(admitted, meta)`` tuple where:

    * ``admitted`` is the list of cards that passed the gate, in
      the original order.
    * ``meta`` is the dict that lands under
      ``envelope.meta.daily_artifact_gate`` — carries the gate id,
      the admitted count, and the held-for-review count so the
      operator can see, in the route response itself, how many rows
      the gate dropped.

    The function does not mutate the input list.  Non-dict entries
    (a defensive guard for upstream bugs) are treated as held for
    review.
    """
    raw: list[Any] = list(cards) if cards else []
    admitted: list[dict[str, Any]] = []
    for c in raw:
        if is_artifact_backed_daily_card(c, artifact_dir=artifact_dir):
            admitted.append(c)
    held = len(raw) - len(admitted)
    meta: dict[str, Any] = {
        "gate_id":               GATE_ID,
        "admitted_count":        len(admitted),
        "held_for_review_count": held,
    }
    return admitted, meta


__all__ = (
    "GATE_ID",
    "is_artifact_backed_daily_card",
    "filter_daily_section_c_cards",
)
