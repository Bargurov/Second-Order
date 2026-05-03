"""Engine-phase field surfacing for HTTP responses.

The engine (``analyze_event._finalize_analysis``) emits a richer set of
fields than what gets persisted as DB columns:

  * ``mechanism_subtype`` — keyword-inferred from family + summary text
  * ``quality_tier``      — derived from the low-information gate
  * ``quality_warnings``  — short failure-mode tags for non-actionable
                            outputs
  * ``actionability_check`` / ``counterfactual_check`` /
    ``confidence_rationale`` — composed at finalize-time, not stored
  * ``thesis_timing``     — sub-block of ``competing_thesis``
  * ``critical_breakpoints`` — sub-list of ``hidden_mechanism``
  * ``evidence_sources``  — top-level when stamped, else nested under
                            ``competing_thesis``

The save / read path keeps only the underlying data; the derived
fields above are absent on a freshly-loaded event.  ``decorate_full``
re-derives them on read so ``GET /events/{id}`` returns a stable
shape consumers can branch on.  ``decorate_compact`` returns the
short subset surfaced on every ``GET /portfolio`` row.

All composers / inference calls are pure reads — never write to the
DB.  Every defensive ``except`` falls back to the documented default
for that field so a transient import / composer error cannot collapse
the response shape.
"""

from __future__ import annotations

from typing import Any


_FULL_DEFAULTS: dict[str, Any] = {
    "mechanism_subtype":     None,
    "quality_tier":          "low_information",
    "quality_warnings":      [],
    "actionability_check":   {},
    "counterfactual_check":  {},
    "thesis_timing":         {},
    "critical_breakpoints":  [],
    "evidence_sources":      [],
    "confidence_rationale":  "",
    "validation_rationale":  "",
}

_COMPACT_DEFAULTS: dict[str, Any] = {
    "quality_tier":        "low_information",
    "quality_warnings":    [],
    "actionability_check": {"tradable": False},
    "mechanism_subtype":   None,
}


def decorate_full(ev: dict) -> dict:
    """In-place: surface every engine-phase field on ``ev`` with stable defaults.

    Composers re-run against the loaded event so a row read from the DB
    carries the same engine-derived blocks the analysis pipeline emits
    at finalize time.  Nested fields (``thesis_timing``,
    ``critical_breakpoints``, ``evidence_sources``) are lifted to top
    level when present and otherwise filled with the documented empty
    default.

    Caller contract: ``ev`` must be a decoded event dict (the output of
    ``db._decode_event_row``).  ``validation_rationale`` is left for the
    route handler to set — this helper only ensures the key exists with
    a stable default if no upstream produced one.
    """
    if not isinstance(ev, dict):
        return ev

    # Compose-on-read derivations — none of these keys are persisted as
    # DB columns, so always-recompute is purely additive (never
    # clobbers a stored value).
    try:
        from low_information_gate import (
            compose_actionability_check,
            compose_confidence_rationale,
            compose_counterfactual_check,
            evidence_quality_tier,
            quality_warnings as _quality_warnings_fn,
        )
        ev["actionability_check"]  = compose_actionability_check(ev)
        ev["counterfactual_check"] = compose_counterfactual_check(ev)
        ev["confidence_rationale"] = compose_confidence_rationale(ev)
        tier = evidence_quality_tier(ev)
        ev["quality_tier"] = tier
        ev["quality_warnings"] = (
            _quality_warnings_fn(ev)
            if tier in ("watch_only", "low_information")
            else []
        )
    except Exception:
        for k in (
            "actionability_check", "counterfactual_check",
            "confidence_rationale", "quality_tier", "quality_warnings",
        ):
            ev.setdefault(k, _FULL_DEFAULTS[k])

    # mechanism_subtype — keyword inference over the persisted prose
    # signal blob.  ``None`` is the documented default when family is
    # ``"none"`` or no subtype keyword matches.
    if not ev.get("mechanism_subtype"):
        try:
            from mechanism_family import infer_mechanism_subtype
            ev["mechanism_subtype"] = infer_mechanism_subtype(
                ev.get("mechanism_family"),
                ev.get("mechanism_summary"),
                ev.get("what_changed", "") or "",
            )
        except Exception:
            ev["mechanism_subtype"] = None

    competing = ev.get("competing_thesis")
    if not isinstance(competing, dict):
        competing = {}

    # thesis_timing — lifted from competing_thesis when the engine
    # stamped it there; empty dict otherwise.
    if not isinstance(ev.get("thesis_timing"), dict) or not ev.get("thesis_timing"):
        nested = competing.get("thesis_timing")
        ev["thesis_timing"] = nested if isinstance(nested, dict) else {}

    # critical_breakpoints — lifted from hidden_mechanism; empty list
    # when no breakpoints were emitted.
    if not isinstance(ev.get("critical_breakpoints"), list) or not ev.get("critical_breakpoints"):
        hidden = ev.get("hidden_mechanism")
        nested = (
            hidden.get("critical_breakpoints")
            if isinstance(hidden, dict) else None
        )
        ev["critical_breakpoints"] = nested if isinstance(nested, list) else []

    # evidence_sources — top-level when an upstream producer attached
    # it; else lifted from the nested competing_thesis block.
    top = ev.get("evidence_sources")
    if not isinstance(top, list) or not top:
        nested = competing.get("evidence_sources")
        ev["evidence_sources"] = nested if isinstance(nested, list) else []

    # validation_rationale — defaulted only.  The route handler runs
    # ``derive_validation_rationale`` after this helper and overwrites
    # the empty default with the real value when one is derivable.
    ev.setdefault("validation_rationale", "")

    return ev


def decorate_compact(ev: dict) -> dict:
    """Return the compact engine-phase subset surfaced on each
    ``/portfolio`` row.

    Pure read — never mutates ``ev``.  Returned dict carries:

      * ``quality_tier``         — closed enum
      * ``quality_warnings``     — list of failure-mode tags
      * ``actionability_check``  — ``{"tradable": bool}`` only (full
                                   block lives on ``/events/{id}``)
      * ``mechanism_subtype``    — string or ``None``

    Defaults match ``_COMPACT_DEFAULTS`` so a non-dict input or a
    composer failure still returns the documented shape.
    """
    if not isinstance(ev, dict):
        return dict(_COMPACT_DEFAULTS)

    try:
        from low_information_gate import (
            compose_actionability_check,
            evidence_quality_tier,
            quality_warnings as _quality_warnings_fn,
        )
        tier = evidence_quality_tier(ev)
        warnings = (
            _quality_warnings_fn(ev)
            if tier in ("watch_only", "low_information")
            else []
        )
        ac = compose_actionability_check(ev)
        tradable = bool(ac.get("tradable", False)) if isinstance(ac, dict) else False
    except Exception:
        tier, warnings, tradable = "low_information", [], False

    subtype = ev.get("mechanism_subtype")
    if not subtype:
        try:
            from mechanism_family import infer_mechanism_subtype
            subtype = infer_mechanism_subtype(
                ev.get("mechanism_family"),
                ev.get("mechanism_summary"),
                ev.get("what_changed", "") or "",
            )
        except Exception:
            subtype = None

    return {
        "quality_tier":        tier,
        "quality_warnings":    list(warnings),
        "actionability_check": {"tradable": tradable},
        "mechanism_subtype":   subtype,
    }
