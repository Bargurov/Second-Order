"""analysis-request-identity-v1 — the exact basis of one analysis invocation.

WHAT THIS IDENTIFIES
--------------------
``request_hash`` identifies ONE exact analysis REQUEST: the provider, the
model, the two prompt snapshots, the two contract versions, and the event
date.  Two runs share a hash only when they would have produced the same saved
result — which is precisely what makes reusing one safe and unlimited in time.

WHAT IT IS NOT
--------------
Not an event identity, not a thesis identity, and not a claim that the saved
analysis is correct.  It is deliberately distinct from the three identities
that already exist:

    candidate_id         strict Inbox candidate handle (``aei-*``)
    analysis_event_id    numeric ``events.id``
    analysis_input_hash  A1-2 Inbox provenance INPUT identity

``analysis_input_hash`` covers the candidate snapshot and context for
provenance comparison; this hash covers the literal provider request.  They
answer different questions and must never be substituted for one another.

WHY THE PROMPT IS THE BASIS
---------------------------
Headline, event context, macro context, stage and persistence all flow into
the rendered user prompt through the ONE shared renderer
(``analyze_event.render_analysis_prompt``).  Hashing the rendered prompt
therefore covers every one of them without maintaining a second, driftable
list of prompt inputs.  Provider, model and the contract versions are not in
the prompt text, so they are included explicitly.

SECRETS
-------
The basis is the declared fields in ``REQUEST_BASIS_FIELDS`` and nothing
else.  No API key, admin token, authorization header or environment value is
read here or can enter the hash.
"""

from __future__ import annotations

import hashlib
import json

REQUEST_IDENTITY_VERSION = "analysis-request-identity-v1"

#: The complete request basis.  Anything absent from this tuple is, by
#: definition, NOT part of request identity — timestamps, cache age, market
#: overlays, provenance-comparison state, route origin, the numeric event id
#: and candidate registry status all deliberately fall outside.
#:
#: ``event_date`` is included even though it never reaches the prompt: it
#: selects the market-check window and is stored on the row, so two requests
#: differing only by date produce materially different SAVED results.  A hash
#: over the prompt alone would collide them and serve the second request the
#: first request's answer.  A reuse key must cover every input that changes
#: the saved result, not only the ones the provider sees.
REQUEST_BASIS_FIELDS: tuple[str, ...] = (
    "provider",
    "model",
    "system_prompt",
    "rendered_user_prompt",
    "prompt_version",
    "schema_version",
    "event_date",
)


def canonical_request_json(basis: dict) -> str:
    """Deterministic serialization of exactly the declared basis fields.

    Extra keys on *basis* are ignored rather than hashed, so a caller that
    passes a whole request object cannot accidentally make volatile state part
    of the identity.  A missing declared field is an error, not a default —
    silently hashing ``None`` would let two different requests collide.
    """
    missing = [f for f in REQUEST_BASIS_FIELDS if f not in basis]
    if missing:
        raise ValueError(
            f"analysis request basis is missing required field(s): {missing}")
    payload = {"v": REQUEST_IDENTITY_VERSION}
    for field in REQUEST_BASIS_FIELDS:
        value = basis[field]
        if not isinstance(value, str):
            raise TypeError(
                f"analysis request basis field {field!r} must be a string, "
                f"got {type(value).__name__}")
        payload[field] = value
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def request_hash(basis: dict) -> str:
    """SHA-256 over the canonical basis.

    Never Python's ``hash()`` — that is process-randomized, so a stored hash
    would stop matching after a restart and every saved analysis would silently
    become unreusable (and re-billable).
    """
    return hashlib.sha256(
        canonical_request_json(basis).encode("utf-8")).hexdigest()


def build_request_basis(
    *, provider: str, model: str, system_prompt: str,
    rendered_user_prompt: str, prompt_version: str, schema_version: str,
    event_date: str,
) -> dict:
    """Assemble a basis dict with only the declared fields present."""
    return {
        "provider": provider,
        "model": model,
        "system_prompt": system_prompt,
        "rendered_user_prompt": rendered_user_prompt,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "event_date": event_date,
    }


def request_mapping_record(basis: dict) -> dict:
    """The durable mapping row for one request basis.

    Stores the hash plus the contract metadata a reviewer needs to understand
    WHY a cache entry exists.  The prompts themselves are deliberately NOT
    duplicated here: for an Inbox analysis A1-2 provenance already stores them,
    and for a direct analysis the analytical output lives in the A1-3 result
    snapshot.  Storing them a third time would create three copies that could
    disagree.
    """
    return {
        "request_hash": request_hash(basis),
        "provider": basis["provider"],
        "model": basis["model"],
        "prompt_version": basis["prompt_version"],
        "schema_version": basis["schema_version"],
    }
