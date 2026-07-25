"""analysis-provenance-v1 — the immutable basis of one saved Event Analysis.

WHAT THIS IS
------------
A provenance snapshot records what an analysis *used*: which strict Inbox
candidate, which records the candidate owned, the exact context and prompts
that went to the provider, and which provider / model / contract versions were
in force.  It is reconstruction evidence, nothing more.

WHAT THIS IS NOT
----------------
A verifying hash says the stored inputs are intact.  It says nothing about
whether the model's reading of those inputs was right.  Never present a
matching hash as support for a thesis.

NAMING — read this before touching the database
-----------------------------------------------
The pre-existing ``event_provenance`` table is a DIFFERENT, older concept
(D1A source provenance: publisher, URL, intake path).  This module owns
``analysis_provenance`` and never reads or writes that table.

DESIGN NOTES
------------
* The candidate snapshot is rebuilt SERVER-SIDE from ``(parent_cluster_id,
  title_key)``.  A caller-supplied source list is never authoritative — that
  is the whole point of provenance.
* Hashes are SHA-256 over canonical JSON.  Python's ``hash()`` is
  process-randomized and would make stored hashes unverifiable across runs.
* ``candidate_id`` is re-derived on every read, never trusted from storage.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from event_inbox import candidate_event_id, derive_cluster_times, partition_records_by_identity

# ---------------------------------------------------------------------------
# Contract versions
# ---------------------------------------------------------------------------
# These IDENTIFY the current analysis contract; they do not define it.  Bump a
# version deliberately, in the same change that alters what it names:
#   ANALYSIS_PROMPT_VERSION -> when prompts.SYSTEM_PROMPT or
#                              prompts.EVENT_ANALYSIS_PROMPT changes meaning;
#   ANALYSIS_SCHEMA_VERSION -> when the AnalysisResult field contract changes.
# A saved analysis whose stored version differs from the live one reads as
# SAVED_WITH_OLDER_BASIS rather than silently passing as current.

ANALYSIS_PROMPT_VERSION = "event-analysis-prompt-v1"
ANALYSIS_SCHEMA_VERSION = "analysis-result-v1"
PROVENANCE_CONTRACT_VERSION = "analysis-provenance-v1"

PROVENANCE_STATES: tuple[str, ...] = (
    "VERIFIED_CURRENT",
    "SAVED_WITH_OLDER_BASIS",
    "LEGACY_PROVENANCE_UNAVAILABLE",
    "PROVENANCE_INVALID",
)

#: The one non-claim the surface must carry alongside any provenance readout.
PROVENANCE_NON_CLAIM = (
    "This basis records what the analysis used. It does not verify that the "
    "model's interpretation is correct."
)

#: Every field of the persisted object, excluding the seal itself.
_SEALED_FIELDS: tuple[str, ...] = (
    "provenance_contract_version",
    "analysis_event_id", "candidate_id", "parent_cluster_id", "title_key",
    "candidate_headline", "candidate_first_seen_at", "candidate_last_updated_at",
    "candidate_snapshot", "candidate_context_snapshot", "macro_context_snapshot",
    "stage", "persistence",
    "provider", "model",
    "analysis_prompt_version", "analysis_schema_version",
    "system_prompt_snapshot", "rendered_user_prompt_snapshot",
    "candidate_snapshot_hash", "prompt_snapshot_hash", "analysis_input_hash",
    "created_at",
)

#: The dimensions a saved analysis is compared on.  Deliberately excludes
#: anything volatile (market data, clock, event id) — those are not the basis
#: the provider saw.
_BASIS_DIMENSIONS: tuple[str, ...] = (
    "candidate_records", "candidate_context", "provider", "model",
    "prompt_version", "schema_version",
)


# ---------------------------------------------------------------------------
# Deterministic serialization + hashing
# ---------------------------------------------------------------------------

def canonical_json(obj: object) -> str:
    """Stable JSON: sorted keys, no incidental whitespace, unicode preserved.

    Two structurally equal objects must serialize byte-identically or every
    hash below becomes meaningless.
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)


def sha256_of(obj: object) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Candidate snapshot — server-side reconstruction
# ---------------------------------------------------------------------------

def _iso(value: object) -> str:
    """Normalize a timestamp to one ISO string BEFORE it reaches a hash.

    ``derive_cluster_times`` hands back ``datetime`` objects.  Letting one
    reach ``canonical_json``'s ``default=str`` fallback would hash a repr
    whose format is not part of any contract, so the conversion is explicit
    and lossless here instead.
    """
    if value is None or value == "":
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat(timespec="seconds")
    return str(value)


def _record_entry(record: dict, title_key: str) -> dict:
    """One snapshot row.

    ``record_id`` comes from the pipeline's per-record ``candidate_id`` field.
    That field is a RECORD hash from the news layer and is unrelated to the
    Inbox candidate's ``aei-*`` identity — the names collide upstream, so the
    snapshot renames it to keep the two apart.
    """
    return {
        "source": str(record.get("source") or ""),
        "title": str(record.get("title") or ""),
        "title_key": title_key,
        "published_at": str(record.get("published_at") or ""),
        "url": str(record.get("url") or ""),
        "record_id": str(record.get("candidate_id") or ""),
    }


def build_candidate_snapshot(
    rows: list[dict], parent_cluster_id: object, title_key: str,
) -> Optional[dict]:
    """Rebuild one strict candidate's owned records from stored cluster rows.

    Returns ``None`` when the candidate cannot be resolved — a missing parent
    cluster, a partition that no longer exists, or an empty store.  Callers
    must fail closed on ``None`` rather than substituting current state.
    """
    if not rows or not title_key or parent_cluster_id is None:
        return None
    try:
        parent = int(parent_cluster_id)
    except (TypeError, ValueError):
        return None

    row = next((r for r in rows if r.get("id") == parent), None)
    if row is None:
        return None

    # partition_records_by_identity is the SAME primitive the Inbox uses, so a
    # snapshot can never disagree with the candidate the operator opened.
    partitions = partition_records_by_identity(row.get("records"))
    owned = next((recs for key, recs in partitions if key == title_key), None)
    if not owned:
        return None

    times = derive_cluster_times(owned)
    entries = [_record_entry(r, title_key) for r in owned]

    # Deterministic order: a re-ingested cluster must hash the same.
    entries.sort(key=lambda e: (e["published_at"], e["source"], e["title"],
                                e["url"], e["record_id"]))
    headline = ""
    if owned:
        newest = times.newest_record or owned[-1]
        headline = str(newest.get("title") or "")
    return {
        "headline": headline,
        "first_seen_at": _iso(times.first_seen),
        "last_updated_at": _iso(times.last_updated),
        "record_count": len(entries),
        "records": entries,
        "sources": sorted({e["source"] for e in entries if e["source"]}),
    }


# ---------------------------------------------------------------------------
# Building the sealed object
# ---------------------------------------------------------------------------

def _prompt_snapshot_payload(prov: dict) -> dict:
    return {
        "system": prov.get("system_prompt_snapshot"),
        "user": prov.get("rendered_user_prompt_snapshot"),
        "prompt_version": prov.get("analysis_prompt_version"),
        "schema_version": prov.get("analysis_schema_version"),
    }


def _input_payload(prov: dict) -> dict:
    """Exactly the dimensions that define the analysis basis."""
    return {
        "candidate_snapshot_hash": prov.get("candidate_snapshot_hash"),
        "candidate_context": prov.get("candidate_context_snapshot"),
        "macro_context": prov.get("macro_context_snapshot"),
        "provider": prov.get("provider"),
        "model": prov.get("model"),
        "prompt_snapshot_hash": prov.get("prompt_snapshot_hash"),
        "prompt_version": prov.get("analysis_prompt_version"),
        "schema_version": prov.get("analysis_schema_version"),
    }


def provenance_hash_of(prov: dict) -> str:
    """Seal over every persisted field except the seal itself."""
    return sha256_of({k: prov.get(k) for k in _SEALED_FIELDS})


def build_provenance(
    *, analysis_event_id: int, parent_cluster_id: int, title_key: str,
    candidate_snapshot: dict, candidate_context_snapshot: str,
    provider: str, model: str,
    system_prompt_snapshot: str, rendered_user_prompt_snapshot: str,
    created_at: str,
    macro_context_snapshot: str = "",
    stage: str = "", persistence: str = "",
    analysis_prompt_version: Optional[str] = None,
    analysis_schema_version: Optional[str] = None,
) -> dict:
    """Assemble one immutable provenance object with all four hashes.

    The contract versions default to the module constants, resolved HERE
    rather than in the signature: a default argument binds once at definition
    time, which would freeze the version at import and silently ignore a
    deliberate bump made at runtime.
    """
    if analysis_prompt_version is None:
        analysis_prompt_version = ANALYSIS_PROMPT_VERSION
    if analysis_schema_version is None:
        analysis_schema_version = ANALYSIS_SCHEMA_VERSION
    prov: dict = {
        "provenance_contract_version": PROVENANCE_CONTRACT_VERSION,
        "analysis_event_id": int(analysis_event_id),
        "candidate_id": candidate_event_id(parent_cluster_id, title_key),
        "parent_cluster_id": int(parent_cluster_id),
        "title_key": title_key,
        "candidate_headline": (candidate_snapshot or {}).get("headline", ""),
        "candidate_first_seen_at": (candidate_snapshot or {}).get("first_seen_at", ""),
        "candidate_last_updated_at": (candidate_snapshot or {}).get("last_updated_at", ""),
        "candidate_snapshot": candidate_snapshot,
        "candidate_context_snapshot": candidate_context_snapshot,
        "macro_context_snapshot": macro_context_snapshot,
        "stage": stage,
        "persistence": persistence,
        "provider": provider,
        "model": model,
        "analysis_prompt_version": analysis_prompt_version,
        "analysis_schema_version": analysis_schema_version,
        "system_prompt_snapshot": system_prompt_snapshot,
        "rendered_user_prompt_snapshot": rendered_user_prompt_snapshot,
        "created_at": created_at,
    }
    prov["candidate_snapshot_hash"] = sha256_of(candidate_snapshot)
    prov["prompt_snapshot_hash"] = sha256_of(_prompt_snapshot_payload(prov))
    prov["analysis_input_hash"] = sha256_of(_input_payload(prov))
    prov["provenance_hash"] = provenance_hash_of(prov)
    return prov


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

_REQUIRED_IDENTITY = ("analysis_event_id", "candidate_id",
                      "parent_cluster_id", "title_key")


def verify_provenance(prov: object) -> list[str]:
    """Return a list of integrity problems; empty means the object verifies.

    Fails closed on anything unexpected.  A caller that gets a non-empty list
    must surface PROVENANCE_INVALID — never downgrade it to "unavailable",
    which would hide a tampered or corrupt record behind a benign label.
    """
    if not isinstance(prov, dict):
        return ["provenance is not an object"]

    problems: list[str] = []
    for field in _REQUIRED_IDENTITY:
        if prov.get(field) in (None, ""):
            problems.append(f"missing required identity field: {field}")
    if problems:
        return problems

    for field in ("candidate_snapshot_hash", "prompt_snapshot_hash",
                  "analysis_input_hash", "provenance_hash"):
        value = prov.get(field)
        if not isinstance(value, str) or len(value) != 64:
            problems.append(f"{field} is not a sha256 digest")
    if problems:
        return problems

    # Identity is derived, never asserted.
    try:
        expected_id = candidate_event_id(prov["parent_cluster_id"],
                                         prov["title_key"])
    except Exception:
        return ["candidate identity could not be recomputed"]
    if prov["candidate_id"] != expected_id:
        problems.append("candidate_id does not recompute from "
                        "parent_cluster_id and title_key")

    if sha256_of(prov.get("candidate_snapshot")) != prov["candidate_snapshot_hash"]:
        problems.append("candidate_snapshot_hash does not match the snapshot")
    if sha256_of(_prompt_snapshot_payload(prov)) != prov["prompt_snapshot_hash"]:
        problems.append("prompt_snapshot_hash does not match the prompts")
    if sha256_of(_input_payload(prov)) != prov["analysis_input_hash"]:
        problems.append("analysis_input_hash does not match the recorded basis")
    if provenance_hash_of(prov) != prov["provenance_hash"]:
        problems.append("provenance_hash does not verify — the record was altered")
    return problems


# ---------------------------------------------------------------------------
# Current basis + comparison
# ---------------------------------------------------------------------------

def current_analysis_basis(
    *, candidate_snapshot: Optional[dict], candidate_context_snapshot: str,
    provider: str, model: str,
    system_prompt_snapshot: str, rendered_user_prompt_snapshot: str,
    macro_context_snapshot: str = "",
    analysis_prompt_version: Optional[str] = None,
    analysis_schema_version: Optional[str] = None,
) -> Optional[dict]:
    """The basis a re-run WOULD use right now, for comparison only.

    ``None`` when the candidate can no longer be resolved.  Building this
    reads local state only — it never contacts a provider.

    Contract versions resolve in the body for the same reason as
    :func:`build_provenance`: a signature default would pin them at import.
    """
    if candidate_snapshot is None:
        return None
    if analysis_prompt_version is None:
        analysis_prompt_version = ANALYSIS_PROMPT_VERSION
    if analysis_schema_version is None:
        analysis_schema_version = ANALYSIS_SCHEMA_VERSION
    basis = {
        "candidate_snapshot": candidate_snapshot,
        "candidate_snapshot_hash": sha256_of(candidate_snapshot),
        "candidate_context_snapshot": candidate_context_snapshot,
        "macro_context_snapshot": macro_context_snapshot,
        "provider": provider,
        "model": model,
        "analysis_prompt_version": analysis_prompt_version,
        "analysis_schema_version": analysis_schema_version,
        "system_prompt_snapshot": system_prompt_snapshot,
        "rendered_user_prompt_snapshot": rendered_user_prompt_snapshot,
    }
    basis["prompt_snapshot_hash"] = sha256_of(_prompt_snapshot_payload(basis))
    basis["analysis_input_hash"] = sha256_of(_input_payload(basis))
    return basis


def compare_basis(stored: dict, current: dict) -> list[str]:
    """Name every dimension on which the current basis differs from the saved one."""
    changed: list[str] = []
    if stored.get("candidate_snapshot_hash") != current.get("candidate_snapshot_hash"):
        changed.append("candidate_records")
    if stored.get("candidate_context_snapshot") != current.get("candidate_context_snapshot"):
        changed.append("candidate_context")
    if stored.get("provider") != current.get("provider"):
        changed.append("provider")
    if stored.get("model") != current.get("model"):
        changed.append("model")
    if stored.get("analysis_prompt_version") != current.get("analysis_prompt_version"):
        changed.append("prompt_version")
    if stored.get("analysis_schema_version") != current.get("analysis_schema_version"):
        changed.append("schema_version")
    return changed


def derive_provenance_state(
    stored: Optional[dict], current: Optional[dict],
) -> dict:
    """Resolve one saved analysis into an explicit, closed provenance state.

    Order matters: an invalid record is reported as invalid even when the
    candidate is also unresolvable, because integrity failure is the more
    serious fact and must never be masked by a softer label.
    """
    if stored is None:
        return {"status": "LEGACY_PROVENANCE_UNAVAILABLE",
                "changed_dimensions": [],
                "problems": [],
                "non_claim": PROVENANCE_NON_CLAIM}

    problems = verify_provenance(stored)
    if problems:
        return {"status": "PROVENANCE_INVALID",
                "changed_dimensions": [],
                "problems": problems,
                "non_claim": PROVENANCE_NON_CLAIM}

    if current is None:
        return {"status": "SAVED_WITH_OLDER_BASIS",
                "changed_dimensions": ["candidate_unresolved"],
                "problems": [],
                "non_claim": PROVENANCE_NON_CLAIM}

    changed = compare_basis(stored, current)
    if changed:
        return {"status": "SAVED_WITH_OLDER_BASIS",
                "changed_dimensions": changed,
                "problems": [],
                "non_claim": PROVENANCE_NON_CLAIM}
    return {"status": "VERIFIED_CURRENT",
            "changed_dimensions": [],
            "problems": [],
            "non_claim": PROVENANCE_NON_CLAIM}


def summarize_for_response(stored: Optional[dict], state: dict) -> dict:
    """The compact, reviewable summary the analysis response carries.

    Deliberately excludes the full prompt bodies: they are large, and the
    surface only needs enough to identify the basis.  The full captured
    context and record identities travel in ``candidate_snapshot`` /
    ``candidate_context_snapshot``, which the UI discloses on request.
    """
    summary: dict = {
        "status": state["status"],
        "changed_dimensions": list(state.get("changed_dimensions") or []),
        "problems": list(state.get("problems") or []),
        "non_claim": PROVENANCE_NON_CLAIM,
        "candidate_id": None,
        "parent_cluster_id": None,
        "source_count": None,
        "candidate_first_seen_at": None,
        "candidate_last_updated_at": None,
        "provider": None,
        "model": None,
        "analysis_prompt_version": None,
        "analysis_schema_version": None,
        "created_at": None,
        "provenance_hash": None,
        "candidate_context_snapshot": None,
        "candidate_records": [],
    }
    if not isinstance(stored, dict):
        return summary
    snapshot = stored.get("candidate_snapshot") or {}
    summary.update({
        "candidate_id": stored.get("candidate_id"),
        "parent_cluster_id": stored.get("parent_cluster_id"),
        "source_count": len(snapshot.get("sources") or []),
        "candidate_first_seen_at": stored.get("candidate_first_seen_at"),
        "candidate_last_updated_at": stored.get("candidate_last_updated_at"),
        "provider": stored.get("provider"),
        "model": stored.get("model"),
        "analysis_prompt_version": stored.get("analysis_prompt_version"),
        "analysis_schema_version": stored.get("analysis_schema_version"),
        "created_at": stored.get("created_at"),
        "provenance_hash": stored.get("provenance_hash"),
        "candidate_context_snapshot": stored.get("candidate_context_snapshot"),
        "candidate_records": list(snapshot.get("records") or []),
    })
    return summary
