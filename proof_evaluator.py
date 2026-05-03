"""Pure composers for proof-set and falsifier evaluation.

Given a saved event dict, derive two blocks from *already observed*
evidence (market_tickers, revisit_snapshots):

  * ``proof_status`` — verdict per ``minimum_proof_set`` entry, rolled
    up to a three-state ``status`` (``met`` / ``partial`` / ``unmet``).
  * ``falsifier_status`` — three-state read over ``key_falsifiers``
    (``triggered`` / ``watch`` / ``none``).

No I/O, no provider calls, no new fetches.  Evaluation reads only
what the event already carries — so callers at the save / refresh /
revisit hooks can compute these in-band without changing
``weighted_evidence`` or ``validation_outcome``.

Proof-set semantics
-------------------
Each proof entry has ``{observation, channel, threshold, timing}``.
We match the entry against the event's ``market_tickers`` by the
``channel`` token:

  * Tickers that map to the entry's channel via
    ``asset_selection._ticker_channel`` are the candidate evidence set.
  * A ticker's ``direction_tag`` carries the verdict — the same
    ``supports…`` / ``contradicts…`` prefix check the shared
    ``validation_outcome`` helper uses.
  * Entry ``matched`` when ≥1 supporting tag AND no contradicting tag
    on the same channel.  Mixed / contradicting-only / no tagged
    tickers → unmet.

This mirrors ``validation_outcome``'s classification rules without
re-using the helper directly (which scans the whole ticker list);
here we scope per-channel so an entry on ``rates`` isn't met by a
supporting ``equities`` tag elsewhere.

Falsifier semantics
-------------------
``key_falsifiers`` are flat strings with no parseable channel.  We
defer to the event-wide validation label (``score_validation_label``)
as the best-available read on whether the thesis is holding:

  * Label ``contradicted`` → every falsifier is surfaced under
    ``triggered``.
  * Label ``unresolved`` / ambiguous → surfaced under ``watching``.
  * Label ``validated`` → ``none``; nothing is firing.

This reuses the shared validation signal rather than introducing a
second classifier that could drift from it.
"""

from __future__ import annotations

from typing import Any, Optional

from asset_selection import _ticker_channel
from validation_outcome import score_validation_label, score_validation_outcome


# ---------------------------------------------------------------------------
# Output shapes — kept as module-level factories so every caller sees
# identical empty defaults.  "Available: False" is the signal consumers
# read to decide whether to render the block at all.
# ---------------------------------------------------------------------------


def _empty_proof_status() -> dict[str, Any]:
    return {
        "available":     False,
        "status":        "none",
        "matched_count": 0,
        "total_count":   0,
        "matched_items": [],
        "unmet_items":   [],
        # ``items`` is the item-level evaluation row list — one entry
        # per input ``minimum_proof_set`` element.  Present (empty) on
        # every returned block so consumers can unconditionally iterate
        # over it, including on old rows that pre-date this field.
        "items":         [],
    }


def _empty_falsifier_status() -> dict[str, Any]:
    return {
        "available": False,
        "status":    "none",
        "triggered": [],
        "watching":  [],
        # See ``_empty_proof_status.items`` — same contract for
        # falsifier item-level rows.
        "items":     [],
    }


# Per-item proof status vocabulary (task contract).
_PROOF_ITEM_STATUS_IDS: tuple[str, ...] = ("met", "unmet", "insufficient")
# Per-item falsifier status vocabulary (task contract).
_FALSIFIER_ITEM_STATUS_IDS: tuple[str, ...] = (
    "triggered", "watch", "clear", "insufficient",
)


# Public aliases for the empty-shape factories.  Callers at the API /
# serialization boundary use these to coerce missing or empty blocks
# into the canonical shape so ``/events/{event_id}`` never emits a
# bare ``{}`` for these two fields.
def empty_proof_status() -> dict[str, Any]:
    """Public factory for the shaped empty ``proof_status`` default."""
    return _empty_proof_status()


def empty_falsifier_status() -> dict[str, Any]:
    """Public factory for the shaped empty ``falsifier_status`` default."""
    return _empty_falsifier_status()


def coerce_proof_status(block: Any) -> dict[str, Any]:
    """Normalise an arbitrary stored/decoded value into the shaped default.

    Any missing top-level key is filled from ``empty_proof_status()``;
    ``items`` is guaranteed to be a list.  A non-dict / empty-dict
    input produces the full empty shape rather than leaking ``{}`` to
    the HTTP response.
    """
    out = empty_proof_status()
    if isinstance(block, dict) and block:
        for k, v in block.items():
            out[k] = v
    if not isinstance(out.get("items"), list):
        out["items"] = []
    # Legacy paired lists — also guarantee list type so downstream
    # iterations can't blow up on a stray null.
    for list_key in ("matched_items", "unmet_items"):
        if not isinstance(out.get(list_key), list):
            out[list_key] = []
    return out


def coerce_falsifier_status(block: Any) -> dict[str, Any]:
    """Normalise an arbitrary stored/decoded value into the shaped default.

    Same contract as ``coerce_proof_status`` for the falsifier block.
    """
    out = empty_falsifier_status()
    if isinstance(block, dict) and block:
        for k, v in block.items():
            out[k] = v
    if not isinstance(out.get("items"), list):
        out["items"] = []
    for list_key in ("triggered", "watching"):
        if not isinstance(out.get(list_key), list):
            out[list_key] = []
    return out


# ---------------------------------------------------------------------------
# Per-channel evidence counts
# ---------------------------------------------------------------------------


def _channel_tag_counts(tickers: list) -> dict[str, dict[str, int]]:
    """Return ``{channel: {"supports": N, "contradicts": M}}`` for an event.

    Walks ``market_tickers`` once.  Each ticker is routed to its
    channel via ``_ticker_channel``; unknown-channel tickers are
    dropped.  Uses the same ``startswith`` convention as
    ``validation_outcome`` so the two classifiers can't drift on
    direction-tag prefix handling.
    """
    out: dict[str, dict[str, int]] = {}
    if not isinstance(tickers, list):
        return out
    for t in tickers:
        if not isinstance(t, dict):
            continue
        sym = t.get("symbol")
        tag = t.get("direction_tag") or ""
        if not isinstance(sym, str) or not isinstance(tag, str) or not tag:
            continue
        channel = _ticker_channel(sym.strip().upper())
        if channel is None:
            continue
        bucket = out.setdefault(channel, {"supports": 0, "contradicts": 0})
        if tag.startswith("supports"):
            bucket["supports"] += 1
        elif tag.startswith("contradicts"):
            bucket["contradicts"] += 1
    return out


# ---------------------------------------------------------------------------
# Proof-set evaluation
# ---------------------------------------------------------------------------


def _rollup_status(matched: int, total: int) -> str:
    """Three-state rollup per task contract."""
    if total == 0:
        return "none"
    if matched == total:
        return "met"
    if matched == 0:
        return "unmet"
    return "partial"


def _evaluate_one_proof_item(
    entry: dict,
    by_channel: dict[str, dict[str, int]],
) -> tuple[str, str]:
    """Classify one proof entry against observed per-channel counts.

    Returns ``(status, matched_evidence)``.  Status vocab matches the
    task contract: ``met`` / ``unmet`` / ``insufficient``.  The
    ``insufficient`` state is new vs the rollup summary (which uses
    ``partial``) — it marks proof entries for which no directional
    evidence exists at all, separately from entries with contradicting
    evidence.  Rollup still bucket ``insufficient`` under ``unmet_items``
    so the summary counts remain stable.
    """
    channel = entry.get("channel")
    if not isinstance(channel, str):
        return "unmet", "no channel on proof entry"

    counts = by_channel.get(
        channel.lower(), {"supports": 0, "contradicts": 0},
    )
    supports = counts["supports"]
    contradicts = counts["contradicts"]

    if supports == 0 and contradicts == 0:
        return "insufficient", (
            f"no direction-tagged tickers observed on {channel} channel"
        )
    if supports >= 1 and contradicts == 0:
        return "met", (
            f"{supports} supporting ticker tag(s) on {channel} "
            f"channel; no contradictions"
        )
    if contradicts >= 1 and supports == 0:
        return "unmet", (
            f"{contradicts} contradicting ticker tag(s) on {channel} channel"
        )
    return "unmet", (
        f"mixed evidence on {channel} channel "
        f"({supports} support / {contradicts} contradict)"
    )


def _proof_item_row(entry: dict, status: str, evidence: str) -> dict[str, Any]:
    """Build the public per-item row with the task-spec fields."""
    channel = entry.get("channel") if isinstance(entry, dict) else None
    timing = entry.get("timing") if isinstance(entry, dict) else None
    # LLM-emitted items don't carry these fields; fall back to the
    # deterministic defaults so every row has the contract shape.
    why = (
        entry.get("why_it_matters")
        or entry.get("rationale")
        or entry.get("observation")
        or ""
    ) if isinstance(entry, dict) else ""
    direction = (
        entry.get("expected_direction") if isinstance(entry, dict) else None
    )
    return {
        "channel":            channel if isinstance(channel, str) else "",
        "expected_direction": direction if isinstance(direction, str) else "mixed",
        "timing":             timing if isinstance(timing, str) else "",
        "why_it_matters":     why if isinstance(why, str) else "",
        "status":             status,
        "matched_evidence":   evidence,
    }


def evaluate_proof_status(event: dict) -> dict[str, Any]:
    """Return the ``proof_status`` block for one event.

    Contract (existing + new):
      * ``available`` — False when ``minimum_proof_set`` is missing/empty.
      * ``status`` — ``met`` / ``partial`` / ``unmet`` / ``none``.
      * ``matched_count`` / ``total_count`` — counts over valid entries.
      * ``matched_items`` / ``unmet_items`` — the proof entries carried
        through, each augmented with an ``evidence`` string.
      * ``items`` — item-level evaluation rows (one per input proof
        entry) with keys ``{channel, expected_direction, timing,
        why_it_matters, status, matched_evidence}`` where
        ``status`` ∈ ``{met, unmet, insufficient}``.
    """
    proof_set = event.get("minimum_proof_set") if isinstance(event, dict) else None
    if not isinstance(proof_set, list) or not proof_set:
        return _empty_proof_status()

    tickers = event.get("market_tickers") or []
    by_channel = _channel_tag_counts(tickers)

    matched_items: list[dict] = []
    unmet_items:   list[dict] = []
    items:         list[dict] = []

    for entry in proof_set:
        if not isinstance(entry, dict):
            continue
        status, evidence = _evaluate_one_proof_item(entry, by_channel)
        items.append(_proof_item_row(entry, status, evidence))
        # Keep the legacy matched_items / unmet_items split: ``met``
        # lands in matched; everything else (``unmet`` / ``insufficient``)
        # lands in unmet so rollup counts stay back-compat.
        if status == "met":
            matched_items.append({**entry, "evidence": evidence})
        else:
            unmet_items.append({**entry, "evidence": evidence})

    total = len(matched_items) + len(unmet_items)
    matched = len(matched_items)
    return {
        "available":     True,
        "status":        _rollup_status(matched, total),
        "matched_count": matched,
        "total_count":   total,
        "matched_items": matched_items,
        "unmet_items":   unmet_items,
        "items":         items,
    }


# ---------------------------------------------------------------------------
# Falsifier evaluation
# ---------------------------------------------------------------------------


def _falsifier_item_row(
    entry: Any, item_status: str, evidence: str,
) -> dict[str, Any]:
    """Build the per-item falsifier row with the task-spec fields.

    Tolerates both shapes: the saved-event flat-string form
    (``["signal text", …]``) and the deterministic dict form emitted by
    ``mechanism_family.falsifier_set_for_family`` (``{channel,
    trigger_condition, timing, why_it_breaks_thesis}``).
    """
    if isinstance(entry, dict):
        channel = entry.get("channel") or ""
        timing = entry.get("timing") or ""
        trigger = (
            entry.get("trigger_condition")
            or entry.get("signal")
            or entry.get("observation")
            or ""
        )
        why = entry.get("why_it_breaks_thesis") or ""
    else:
        channel = ""
        timing = ""
        trigger = str(entry).strip() if entry else ""
        why = ""

    return {
        "channel":              channel if isinstance(channel, str) else "",
        "trigger_condition":    trigger if isinstance(trigger, str) else "",
        "timing":               timing if isinstance(timing, str) else "",
        "why_it_breaks_thesis": why if isinstance(why, str) else "",
        "status":               item_status,
        "matched_evidence":     evidence,
    }


def _falsifier_item_status(label: str) -> tuple[str, str]:
    """Map event-wide validation label to a per-item status + evidence.

    Labels drive the per-item verdict (the summary-level status uses the
    existing ``triggered`` / ``watch`` / ``none`` vocabulary).
    """
    if label == "contradicted":
        return "triggered", "event-wide validation: contradicted"
    if label == "unresolved":
        return "watch", "event-wide validation: unresolved / ambiguous"
    if label == "no_data":
        return "insufficient", "no direction-tagged tickers observed"
    # label == "validated"
    return "clear", "event-wide validation: validated"


def evaluate_falsifier_status(event: dict) -> dict[str, Any]:
    """Return the ``falsifier_status`` block for one event.

    Contract (existing + new):
      * ``available`` — False when ``key_falsifiers`` is missing/empty.
      * ``status`` — ``triggered`` / ``watch`` / ``none``.
      * ``triggered`` — falsifier strings currently firing.
      * ``watching`` — falsifier strings on watch.
      * ``items`` — item-level evaluation rows (one per input
        falsifier) with keys ``{channel, trigger_condition, timing,
        why_it_breaks_thesis, status, matched_evidence}`` where
        ``status`` ∈ ``{triggered, watch, clear, insufficient}``.
    """
    falsifiers = event.get("key_falsifiers") if isinstance(event, dict) else None
    if not isinstance(falsifiers, list) or not falsifiers:
        return _empty_falsifier_status()

    # Keep a parallel view of "non-empty entries" — defensive in case
    # of legacy rows; the sanitizer enforces min-length but tolerate
    # here.
    usable: list[Any] = []
    for f in falsifiers:
        if isinstance(f, dict) and (
            (f.get("trigger_condition") or f.get("signal") or f.get("observation"))
        ):
            usable.append(f)
        elif isinstance(f, str) and f.strip():
            usable.append(f)
    if not usable:
        return _empty_falsifier_status()

    tickers = event.get("market_tickers") or []
    # Use the raw outcome (``score_validation_outcome``) here rather
    # than the label-only helper: we need to distinguish ``no_data``
    # from ``unresolved`` so per-item status can emit ``insufficient``
    # on rows with no direction-tagged tickers at all.
    raw_label, _ = score_validation_outcome(tickers)
    item_status, item_evidence = _falsifier_item_status(raw_label)
    # The summary-level ``status`` vocabulary preserves back-compat with
    # the label-only helper below (collapses ``no_data`` into ``watch``).
    label = score_validation_label(tickers)

    items: list[dict] = [
        _falsifier_item_row(entry, item_status, item_evidence)
        for entry in usable
    ]

    # Legacy summary fields — preserved byte-for-byte so consumers that
    # read ``triggered`` / ``watching`` still work.  The summary-level
    # status vocabulary is intentionally ``triggered`` / ``watch`` /
    # ``none`` (NOT the four-item vocabulary) per the task contract.
    flat_strings = [i["trigger_condition"] for i in items if i["trigger_condition"]]

    if label == "contradicted":
        summary_status = "triggered"
        triggered_list = flat_strings
        watching_list:  list[str] = []
    elif label in ("unresolved", "no_data"):
        summary_status = "watch"
        triggered_list = []
        watching_list = flat_strings
    else:
        summary_status = "none"
        triggered_list = []
        watching_list = []

    return {
        "available": True,
        "status":    summary_status,
        "triggered": triggered_list,
        "watching":  watching_list,
        "items":     items,
    }


# ---------------------------------------------------------------------------
# Convenience composite
# ---------------------------------------------------------------------------


def compute_statuses(event: dict) -> dict[str, dict[str, Any]]:
    """Return both status blocks at once — the common call shape for
    the save / refresh-market / revisit persistence hooks."""
    return {
        "proof_status":     evaluate_proof_status(event),
        "falsifier_status": evaluate_falsifier_status(event),
    }
