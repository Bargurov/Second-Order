"""L2B-0 materiality-hygiene annotation path (descriptive, denominator-safe).

Reuses the existing ``event_hygiene`` sidecar (``event_id`` PRIMARY KEY,
``override_class`` / ``override_reason`` / ``created_at``) to record the L2A-1
materiality adjudication (source: ``stats/L2_MATERIALITY_ADJUDICATION.md``,
commit 7c6f6b9).  Two descriptive tiers are annotated by this slice:

* **firm hygiene** -- re-ingestions decided from stored fields in fully-clean,
  un-flagged groups: events ``49`` (G2), ``51`` (G3), ``44`` (G5);
* **held / leaning hygiene** -- grounded but sitting inside groups the operator
  flagged for hold: ``50`` (G6), ``54`` / ``64`` / ``70`` (G4), ``48`` (G9).

Unresolved rows (G1, G7, G8, and the G4/G9 conflict members 39/53/61) are
deliberately NOT annotated by this slice.

Why NEW ``override_class`` values, and why not the existing ``real_duplicate``
class:

* ``real_duplicate`` carries ``excluded_from_research_denominator`` and feeds the
  reported ``distinct_real_event_total`` / ``redundant_real_duplicate_rows``
  denominators in ``data_hygiene_report``.  Reusing it would move a
  duplicate-adjusted denominator, which L2B-0 forbids.
* The tiers below are **deliberately outside**
  ``data_hygiene_report._VALID_HYGIENE_CLASSES`` and are NOT
  ``db.SYNTHETIC_SEED_OVERRIDE``.  The authoritative hygiene derivation ignores
  unknown override classes, and ``db.synthetic_seed_ids`` (the single accepted-
  corpus exclusion source) matches only ``synthetic_seed`` -- so these
  annotations move NO denominator (accepted, coverage, or distinct-real-event).
  DO NOT add these values to ``_VALID_HYGIENE_CLASSES``: that would silently
  shift a denominator.

Nothing here mutates the live database.  ``apply_annotations`` writes to whatever
connection it is given (a temp copy for the L2B-0 temp-DB verification);
``load_annotations`` and ``overlay_summary`` open the database read-only.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional, Sequence

# Descriptive tiers -- deliberately OUTSIDE data_hygiene_report._VALID_HYGIENE_CLASSES
# and never db.SYNTHETIC_SEED_OVERRIDE, so no denominator moves.  See module docstring.
TIER_FIRM = "materiality_hygiene_firm"
TIER_HELD = "materiality_hygiene_held"
MATERIALITY_HYGIENE_CLASSES = frozenset({TIER_FIRM, TIER_HELD})

SOURCE_ARTIFACT = "stats/L2_MATERIALITY_ADJUDICATION.md"

# The L2B-0 annotation set, verbatim from the pushed adjudication (7c6f6b9).
L2B0_ANNOTATIONS: list[dict[str, Any]] = [
    {"event_id": 49, "tier": TIER_FIRM, "group": "G2", "canonical_event_id": 2,
     "descriptor": "insufficient-mechanism re-ingestion of the Artemis milestone, same outcome"},
    {"event_id": 51, "tier": TIER_FIRM, "group": "G3", "canonical_event_id": 9,
     "descriptor": "insufficient-mechanism re-ingestion of the Barnsley item, same ticker and outcome"},
    {"event_id": 44, "tier": TIER_FIRM, "group": "G5", "canonical_event_id": 40,
     "descriptor": "byte-identical tanker re-ingestion, same ticker and outcome (nearest to an exact copy)"},
    {"event_id": 50, "tier": TIER_HELD, "group": "G6", "canonical_event_id": 25,
     "descriptor": "insufficient-mechanism re-ingestion of the Foxconn item; no attribution contest"},
    {"event_id": 54, "tier": TIER_HELD, "group": "G4", "canonical_event_id": 39,
     "descriptor": "same-date discuss re-ingestion; event-date-quality already flags it duplicate_or_deferred"},
    {"event_id": 64, "tier": TIER_HELD, "group": "G4", "canonical_event_id": 39,
     "descriptor": "later discuss-headline re-ingestion after the OPEC decision"},
    {"event_id": 70, "tier": TIER_HELD, "group": "G4", "canonical_event_id": 39,
     "descriptor": "later discuss-headline re-ingestion after the OPEC decision"},
    {"event_id": 48, "tier": TIER_HELD, "group": "G9", "canonical_event_id": 26,
     "descriptor": "same-ticker, same-outcome coal re-ingestion one day after the anchor"},
]

_TIER_LABEL = {TIER_FIRM: "firm", TIER_HELD: "held / leaning"}

OVERLAY_NOTE = (
    "Descriptive materiality-hygiene annotations (L2, source "
    f"{SOURCE_ARTIFACT}). Firm = re-ingestions decided from stored fields in "
    "fully-clean groups; held = leaning-hygiene rows inside groups flagged for "
    "hold. These annotations are descriptive only: they exclude no row, change "
    "no accepted-row count and no denominator, and are not an effective sample "
    "size."
)


def _reason_text(annotation: dict[str, Any]) -> str:
    """Human- and audit-readable rationale stored in ``override_reason``."""
    label = _TIER_LABEL.get(annotation["tier"], annotation["tier"])
    return (
        f"L2 {label} materiality-hygiene near-duplicate of canonical event "
        f"{annotation['canonical_event_id']} (group {annotation['group']}); "
        f"{annotation['descriptor']}; descriptive only, does not change any "
        "accepted-row count."
    )


class HygieneAnnotationConflict(Exception):
    """Raised when ``apply_annotations`` would overwrite an unrelated hygiene row.

    Two cases: a target event already carries a *different* materiality tier
    (re-tiering must be explicit, never silent) or a *non-materiality* hygiene
    class such as ``synthetic_seed`` (must never be clobbered).
    """


def apply_annotations(conn: sqlite3.Connection,
                      annotations: Optional[Sequence[dict[str, Any]]] = None,
                      *, created_at: str) -> int:
    """Write the materiality-hygiene annotations to ``event_hygiene`` on ``conn``.

    Safe against the ``event_id`` PRIMARY KEY overwrite hazard.  Every target is
    inspected BEFORE any write (so a conflict aborts atomically, with no partial
    write):

    * no existing row -> insert;
    * existing row with the SAME materiality tier -> idempotent reapply (updates
      the reason / ``created_at``);
    * existing row with a DIFFERENT materiality tier -> raise
      ``HygieneAnnotationConflict`` (re-tiering must be explicit);
    * existing row with a NON-materiality class (e.g. ``synthetic_seed``,
      ``real_duplicate``) -> raise ``HygieneAnnotationConflict`` before writing
      anything.

    The caller owns the transaction (commit / rollback).  Never call this against
    the live database in this slice -- pass a connection to a temp copy.  Returns
    the number of annotations written.
    """
    anns = list(annotations) if annotations is not None else L2B0_ANNOTATIONS

    # Pre-flight: inspect every target first so a conflict leaves NO partial write.
    for a in anns:
        row = conn.execute(
            "SELECT override_class FROM event_hygiene WHERE event_id = ?",
            (a["event_id"],),
        ).fetchone()
        if row is None:
            continue  # new target -- safe to insert
        existing = row[0]
        if existing == a["tier"]:
            continue  # same materiality tier -- idempotent reapply allowed
        if existing in MATERIALITY_HYGIENE_CLASSES:
            raise HygieneAnnotationConflict(
                f"event {a['event_id']} already annotated as materiality tier "
                f"{existing!r}; refusing to silently re-tier to {a['tier']!r}")
        raise HygieneAnnotationConflict(
            f"event {a['event_id']} carries non-materiality hygiene class "
            f"{existing!r}; refusing to overwrite it with {a['tier']!r}")

    for a in anns:
        conn.execute(
            "INSERT OR REPLACE INTO event_hygiene "
            "(event_id, override_class, override_reason, created_at) VALUES (?,?,?,?)",
            (a["event_id"], a["tier"], _reason_text(a), created_at),
        )
    return len(anns)


def _readonly_conn(db_path: str) -> sqlite3.Connection:
    uri = Path(db_path).absolute().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def load_annotations(db_path: str) -> list[dict[str, Any]]:
    """Read the materiality-hygiene annotations from a database (read-only).

    Returns a list of ``{event_id, tier, reason}`` dicts, or ``[]`` if the
    ``event_hygiene`` table is absent.  Only the materiality tiers are returned;
    ``synthetic_seed`` and other hygiene classes are ignored.
    """
    conn = _readonly_conn(db_path)
    try:
        try:
            rows = conn.execute(
                "SELECT event_id, override_class, override_reason FROM event_hygiene "
                "WHERE override_class IN (?, ?)",
                (TIER_FIRM, TIER_HELD),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [{"event_id": int(r[0]), "tier": r[1], "reason": r[2] or ""}
                for r in rows]
    finally:
        conn.close()


def _overlay_from_loaded(loaded: Sequence[dict[str, Any]]) -> dict[str, Any]:
    firm = sorted(r["event_id"] for r in loaded if r["tier"] == TIER_FIRM)
    held = sorted(r["event_id"] for r in loaded if r["tier"] == TIER_HELD)
    return {
        "source": SOURCE_ARTIFACT,
        "firm_hygiene_ids": firm,
        "held_hygiene_ids": held,
        "firm_count": len(firm),
        "held_count": len(held),
        "annotated_total": len(firm) + len(held),
        "affects_accepted_denominator": False,
        "note": OVERLAY_NOTE,
    }


def overlay_summary(db_path: str) -> dict[str, Any]:
    """A descriptive overlay of the materiality-hygiene annotations in a database.

    Denominator-safe by construction: it reports which rows are annotated firm /
    held, but asserts (and does not compute) any change to accepted-row counts --
    ``affects_accepted_denominator`` is always ``False``.
    """
    return _overlay_from_loaded(load_annotations(db_path))


def empty_overlay() -> dict[str, Any]:
    """The zero-state overlay (no database read) for empty-report parity."""
    return _overlay_from_loaded([])
