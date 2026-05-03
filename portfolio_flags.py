"""Proof-discipline flags surfaced on the portfolio response.

Three additive booleans per event:

* ``has_proof_set``   — the analysis committed to a minimum proof set
  (``minimum_proof_set`` non-empty with real observation entries).
* ``has_falsifiers``  — the analysis named at least one falsifier
  (``key_falsifiers`` or ``critical_breakpoints`` non-empty).
* ``low_information`` — low / very_low confidence **and** a mechanism
  summary that is empty or contains an explicit insufficient-evidence
  marker.  Both signals required so a tentatively-phrased high-conf
  analysis isn't silently demoted.

Pure composer.  No I/O.  Never raises.
"""

from __future__ import annotations

from typing import Any


_LOW_INFO_MARKERS: tuple[str, ...] = (
    "insufficient evidence",
    "insufficient data",
    "not enough evidence",
    "unclear mechanism",
    "no clear mechanism",
    "mechanism is unclear",
)


# Delegate to the canonical ``low_information_gate`` rule so save-time
# normalisation and read-time flag classification agree on what counts
# as low-information.  The legacy marker set above is kept for the
# localised ``_is_low_information`` path this module already exposes,
# but the shared gate is the single source of truth.
try:
    from low_information_gate import is_low_information_mechanism as _shared_low_info_text  # noqa: E501
except Exception:     # pragma: no cover - only trips during circular import debug
    _shared_low_info_text = None


def _nonempty_list(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return any(
        (isinstance(x, dict) and x)
        or (isinstance(x, str) and x.strip())
        for x in value
    )


def _is_low_information(event: dict) -> bool:
    """Low-information flag for response-path classification.

    Preserves the historical "confidence low + insufficient mechanism
    text" rule this function was added with, so legacy consumers that
    read ``portfolio_flags.low_information`` directly don't shift
    semantics.  New code paths that want the full gate (including the
    concrete-asset prong) should call
    ``low_information_gate.evaluate_low_information`` instead.
    """
    conf_raw = str(event.get("confidence") or "").strip().lower()
    if conf_raw not in ("low", "very_low"):
        return False
    mech_raw = str(event.get("mechanism_summary") or "")
    if _shared_low_info_text is not None:
        return bool(_shared_low_info_text(mech_raw))
    low_mech = mech_raw.strip().lower()
    if not low_mech:
        return True
    return any(m in low_mech for m in _LOW_INFO_MARKERS)


def portfolio_flags(event: Any) -> dict[str, bool]:
    """Return the three proof-discipline booleans for ``event``."""
    if not isinstance(event, dict):
        return {
            "has_proof_set":   False,
            "has_falsifiers":  False,
            "low_information": False,
        }
    return {
        "has_proof_set":   _nonempty_list(event.get("minimum_proof_set")),
        "has_falsifiers":  (
            _nonempty_list(event.get("key_falsifiers"))
            or _nonempty_list(event.get("critical_breakpoints"))
        ),
        "low_information": _is_low_information(event),
    }


# Proof-quality bucket enum — same vocabulary as the track-record
# breakdown but derived here from the portfolio-decorated signals
# (flags + weighted evidence label).  No market-validation recompute.
PROOF_QUALITY_BUCKETS: tuple[str, ...] = (
    "proof_backed",
    "partial_proof",
    "no_proof",
    "falsified",
    "low_information",
)


def proof_quality_bucket(event: Any) -> str:
    """Classify ``event`` into one of ``PROOF_QUALITY_BUCKETS``.

    Uses:
      * ``portfolio_flags`` (proof set / falsifiers / low info)
      * ``event['weighted_evidence']['evidence_label']`` if present
        (optional — a missing label simply disables the ``falsified``
        override).

    Precedence: low_information → falsified → proof_backed →
    partial_proof → no_proof.
    """
    flags = portfolio_flags(event)
    if flags["low_information"]:
        return "low_information"

    evidence_label: str | None = None
    if isinstance(event, dict):
        block = event.get("weighted_evidence")
        if isinstance(block, dict):
            raw = block.get("evidence_label")
            if isinstance(raw, str):
                evidence_label = raw

    has_proof = flags["has_proof_set"]
    has_fals  = flags["has_falsifiers"]

    if has_fals and evidence_label == "contradictory":
        return "falsified"
    if has_proof and has_fals:
        return "proof_backed"
    if has_proof or has_fals:
        return "partial_proof"
    return "no_proof"


# ---------------------------------------------------------------------------
# Actionable research queues
# ---------------------------------------------------------------------------
#
# A single event can belong to more than one queue (e.g. a stale event
# with named falsifiers sits in both ``watch_falsifiers`` and
# ``refresh_needed``).  Membership is derived from the already-computed
# signals ``thesis_state`` / ``low_information`` / ``stale_signal`` /
# ``has_falsifiers`` — no market-validation recompute.

QUEUE_IDS: tuple[str, ...] = (
    "confirming_now",
    "watch_falsifiers",
    "refresh_needed",
    "low_information_cleanup",
)

_STALE_STATUSES: frozenset[str] = frozenset({"stale", "legacy"})


def _queue_context(event_or_ctx: dict) -> dict:
    """Normalise the signals queue classification needs.

    Accepts either the raw event (in which case flags / thesis_state
    are lazy-computed) or the pre-decorated context dict the route
    already builds.  Returns the four booleans we actually branch on.
    """
    thesis = event_or_ctx.get("thesis_state")
    if thesis is None:
        try:
            from thesis_state import derive_thesis_state
            thesis = derive_thesis_state(event_or_ctx)
        except Exception:
            thesis = "watching"

    low_info = bool(event_or_ctx.get("low_information"))
    has_fals = bool(event_or_ctx.get("has_falsifiers"))
    stale_raw = event_or_ctx.get("stale_signal")
    is_stale = isinstance(stale_raw, str) and stale_raw in _STALE_STATUSES

    return {
        "thesis_state":   thesis,
        "low_information": low_info,
        "has_falsifiers": has_fals,
        "is_stale":       is_stale,
    }


def classify_queues(event_or_ctx: dict) -> list[str]:
    """Return the list of queue ids ``event_or_ctx`` belongs to.

    Rules:
      * ``confirming_now``         — thesis_state ∈ {confirming, partial}
                                      AND not low_information AND not stale
      * ``watch_falsifiers``        — named falsifiers present AND thesis
                                      hasn't been falsified AND not low_info
      * ``refresh_needed``          — stale / legacy market check on an
                                      otherwise meaningful thesis
      * ``low_information_cleanup`` — low_information flag set
    """
    if not isinstance(event_or_ctx, dict):
        return []
    ctx = _queue_context(event_or_ctx)
    out: list[str] = []
    thesis = ctx["thesis_state"]

    if (
        thesis in ("confirming", "partial")
        and not ctx["low_information"]
        and not ctx["is_stale"]
    ):
        out.append("confirming_now")

    if (
        ctx["has_falsifiers"]
        and thesis != "falsified"
        and not ctx["low_information"]
    ):
        out.append("watch_falsifiers")

    if (
        ctx["is_stale"]
        and not ctx["low_information"]
        and thesis != "falsified"
    ):
        out.append("refresh_needed")

    if ctx["low_information"]:
        out.append("low_information_cleanup")

    return out
