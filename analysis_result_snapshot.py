"""analysis-result-snapshot-v1 — the immutable saved OUTPUT of one analysis.

WHAT THIS IS
------------
The exact structured mechanism-and-resolution fields a successful analysis
produced, stored so a reopened analysis renders what the run actually
reported.  Before this record existed, ``_build_event_record`` dropped most of
the validated result, and reopening displayed "Not reported" for information
the analysis HAD produced — persistence loss wearing the costume of honest
missingness.

WHAT THIS IS NOT
----------------
Not evidence that the output is correct.  Not an input to any research
statistic: no track-record, evidence, Mission or event-study consumer reads it
(pinned by a static consumer scan in the tests).

RELATIONSHIP TO analysis_provenance
-----------------------------------
Deliberately separate, and the separation is the point:

    analysis_provenance      = what went IN  (candidate, context, prompts,
                               provider, contract versions)
    analysis_result_snapshot = what came OUT (the validated readout fields)

Nothing here reads or writes the provenance table, and output never enters it.

INCLUSION BOUNDARY
------------------
Only the A1-3 readout fields listed in ``RESULT_SNAPSHOT_FIELDS``, taken from
the FINAL validated analysis object — after overlay enrichment, asset
selection and normalization, i.e. exactly what the operator received.

Deliberately EXCLUDED, because they are retrieval state rather than saved
analytical output and are recomputed per read by design:
  * ``confidence_calibration``  — derived from the live archive
  * ``validation_status_v2`` / ``reaction_profile_v1`` — detail-read blocks
  * market, freshness and provenance-comparison metadata
  * the macro overlay blocks already persisted in their own columns, whose
    frozen-vs-live behaviour the event-age freeze policy owns

Restoring merges ONLY these fields onto a cached analysis block, so every
other cached-path behaviour is untouched.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

RESULT_SNAPSHOT_VERSION = "analysis-result-snapshot-v1"

#: The exact A1-3 readout surface.  Adding a field here changes what is saved;
#: it must never be widened to smuggle in a new analytical concept.
RESULT_SNAPSHOT_FIELDS: tuple[str, ...] = (
    # mechanism and transmission
    "mechanism_summary", "transmission_chain", "transmission_path",
    "hidden_mechanism",
    # exposure roles
    "beneficiaries", "losers",
    "primary_assets", "secondary_assets", "hedge_or_signal_assets",
    "expected_second_order_channels",
    # counterforces and competing explanations
    "counterforces", "substitution_barriers", "competing_thesis",
    "adversarial_challenge",
    # falsifiers and minimum proof
    "key_falsifiers", "minimum_proof_set", "proof_status", "falsifier_status",
    # next evidence and resolution points
    "horizon_checkpoints", "monitor_plan",
    # evidence limits
    "quality_tier", "quality_warnings", "validation_warnings", "degraded",
    "regime_conditioned_caveat",
)


def serialize_snapshot(obj: object) -> str:
    """Stable JSON.  Two equal snapshots must serialize byte-identically or
    the integrity hash below is meaningless."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)


def snapshot_hash(result: object) -> str:
    return hashlib.sha256(serialize_snapshot(result).encode("utf-8")).hexdigest()


def build_result_snapshot(analysis: object) -> dict:
    """Capture the readout subset of one FINAL validated analysis object.

    A field the analysis did not carry stays ABSENT rather than being filled
    with an empty default: absent means "the run did not report this", which
    is the honest state the readout renders.  An explicit ``False`` or ``0``
    is preserved — only genuine absence is dropped.
    """
    src = analysis if isinstance(analysis, dict) else {}
    result = {f: src[f] for f in RESULT_SNAPSHOT_FIELDS if f in src}
    return {
        "schema_version": RESULT_SNAPSHOT_VERSION,
        "result": result,
        "result_hash": snapshot_hash(result),
    }


def validate_snapshot(snapshot: object) -> list[str]:
    """Return integrity problems; empty means the snapshot is usable.

    Fails closed: a caller that gets problems must fall back to the legacy
    columns rather than serving a partially-trusted result.
    """
    if not isinstance(snapshot, dict):
        return ["snapshot is not an object"]
    if not isinstance(snapshot.get("result"), dict):
        return ["snapshot result is not an object"]
    if snapshot.get("schema_version") != RESULT_SNAPSHOT_VERSION:
        return [f"unknown snapshot schema_version: {snapshot.get('schema_version')!r}"]
    stored_hash = snapshot.get("result_hash")
    if not isinstance(stored_hash, str) or len(stored_hash) != 64:
        return ["snapshot result_hash is not a sha256 digest"]
    if snapshot_hash(snapshot["result"]) != stored_hash:
        return ["snapshot result_hash does not verify — the record was altered"]
    return []


def apply_result_snapshot(
    analysis_block: dict, snapshot: Optional[dict],
) -> dict:
    """Merge a validated snapshot's fields onto a cached analysis block.

    Returns a NEW dict; neither argument is mutated, and nested values are
    deep-copied so a caller cannot reach back into stored state.

    An absent, malformed or tampered snapshot returns the block unchanged —
    the legacy columns then speak for themselves, honestly and read-only.
    Only the snapshot's own fields are touched, so every other cached-path
    behaviour (macro overlay freeze policy, detail-read blocks) is preserved.
    """
    if not isinstance(analysis_block, dict):
        return analysis_block
    if validate_snapshot(snapshot):
        return analysis_block
    merged = dict(analysis_block)
    saved = snapshot["result"] if isinstance(snapshot, dict) else {}
    for key, value in saved.items():
        merged[key] = json.loads(json.dumps(value, default=str)) \
            if isinstance(value, (dict, list)) else value
    return merged
