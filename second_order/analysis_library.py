"""My analyses: a private, local work library of the Tracker's analyses and their human reviews. Reads only.

An entry is a capture from Analyze an event whose one recorded attempt has a published review view. Everything shown
comes from the existing verified readers, never from raw files joined here:

- the capture: ``event_intake.verified`` (its headline, source URL and publication time as supplied and in UTC);
- the attempt and its view: ``analysis_flow.attempt_state``, which rebuilds the view from the attempt's own records
  and compares it with the published bytes, then those bytes as the review screen serves them (``draft_catalog``);
- the reviews: ``human_review.history``, the verified chain of versions, read against the fingerprint of the view
  served now. A version saved against another fingerprint is about an earlier view, so it never makes the current
  view count as reviewed.

The response mode is the attempt's recorded mode, and it must agree with the run the view records (the local mock or
the paid run) or the entry is reported as unreadable. A record that does not verify is listed with its reason, never
dropped or repaired, and never shown as unreviewed. Captures with no published view stay in Saved events and are only
counted, as are the prepared pilot drafts, which are not Tracker analyses.

"Human reviewed" is a person's judgment of the content. It does not confirm a mechanism, make a draft eligible for
research, freeze or evaluate it, or recommend a trade. Nothing here writes, sends, fetches or calls a provider.
"""
import json
from pathlib import Path

from . import draft_catalog, human_review
from .analysis_flow import MOCK_RUN, FlowRefused, attempt_state
from .event_intake import IntakeRefused, listing, verified
from .paid_drafts import PAID_RUN

LIBRARY_VIEW_VERSION = "analysis-library-view-0.1"
NOTES_EXCERPT = 400  # Characters of the latest note sent for preview and search; the review screen shows all of it.
RUNS = {"mock": (MOCK_RUN, True), "paid": (PAID_RUN, False)}  # Recorded mode -> (the view's run, synthetic_case).
NOT_LISTED_STATES = ("none", "incomplete", "awaiting_publication")


def _model_output(view: dict) -> dict:
    """The model's own words for a preview, by outcome: its summary, its public explanation, or the recorded problem."""
    if view["outcome"] == "draft":
        return {"kind": "summary", "text": view["draft"]["summary"]}
    if view["outcome"] == "no_draft":
        explanation = view["explanation"]
        said = " ".join(paragraph.strip() for paragraph in explanation["text"] if paragraph.strip())
        return {"kind": "explanation", "text": said or explanation.get("provider_explanation") or None}
    return {"kind": "problem", "text": view["problem"]}


def _corrected_fields(corrections: object) -> int:
    if not isinstance(corrections, dict):
        raise ValueError("corrections")
    legs = corrections.get("legs")
    if not isinstance(legs, dict) or not all(isinstance(fields, dict) for fields in legs.values()):
        raise ValueError("corrections")
    return (corrections.get("summary") is not None) + sum(len(fields) for fields in legs.values())


def review_state(reviews_dir: Path, draft_id: str, current: str) -> dict:
    """The human-review state of the view whose fingerprint is ``current``, from the verified version history.

    - none: no version is saved;
    - current: the latest version was saved against this exact view; its status (or none) is the current judgment;
    - stale: the latest version was saved against another view, so this view has no current review;
    - invalid: the history does not verify; it is reported, never read as "not reviewed"."""
    try:
        records = human_review.history(reviews_dir, draft_id)
    except (human_review.ReviewRefused, OSError) as exc:
        return {"state": "invalid", "problem": str(exc), "versions": None}
    if not records:
        return {"state": "none", "versions": 0}
    latest = records[-1]
    binding, status, notes = latest.get("binding"), latest.get("status"), latest.get("notes")
    try:
        bound = binding["draft_view_sha256"] if isinstance(binding, dict) else None
        if not isinstance(bound, str) or status not in (None, *human_review.STATUSES) or not isinstance(notes, str) \
                or not isinstance(latest.get("saved_at"), str):
            raise ValueError("fields")
        corrected = _corrected_fields(latest.get("corrections"))
    except (KeyError, ValueError):
        return {"state": "invalid", "versions": None,
                "problem": f"The latest saved review of {draft_id} does not have the expected fields"}
    if bound != current:
        return {"state": "stale", "versions": len(records), "latest_saved_at": latest["saved_at"]}
    return {"state": "current", "versions": len(records), "status": status, "latest_saved_at": latest["saved_at"],
            "notes_excerpt": notes[:NOTES_EXCERPT], "notes_truncated": len(notes) > NOTES_EXCERPT,
            "corrected_fields": corrected}


def _entry(capture_id: str, record: dict, mode: str, data: bytes, reviews_dir: Path) -> dict:
    view = json.loads(data)
    provenance = view["provenance"]
    if mode not in RUNS or (provenance["pilot"], provenance["synthetic_case"]) != RUNS[mode]:
        raise ValueError(f"the attempt records the {mode or 'unknown'} mode, but its view records the run "
                         f"{provenance['pilot']!r}")
    if provenance["case"] != capture_id:
        raise ValueError("its published view names another capture")
    current = human_review.fingerprint(data)
    return {
        "draft_id": view["id"], "capture_id": capture_id, "draft_view_sha256": current,
        "event": {"headline": record["event"]["headline"], "source_url": record["event"]["source_url"],
                  "published_at": record["times"]["published_at"],
                  "published_at_as_supplied": record["times"]["published_at_as_supplied"]},
        "captured_at": record["times"]["captured_at"],
        "outcome": view["outcome"], "recorded_outcome": provenance["recorded_outcome"], "mode": mode,
        "provenance": {key: provenance[key] for key in ("model", "effort", "prompt_version", "sent_at", "received_at",
                                                        "http_status", "request_id")},
        "model_output": _model_output(view),
        "review": review_state(reviews_dir, view["id"], current),
    }


def capture_analysis(capture_id: str, intake_dir: Path, attempts_dir: Path, drafts_dir: Path, published_dir: Path,
                     reviews_dir: Path) -> dict:
    """One capture's analysis, read as My analyses reads it (the event overview uses the same reader). Reads only.

    {"state": "listed", "entry"}; or one of NOT_LISTED_STATES with the attempt's own detail; or "unreadable" with the
    problem. ``claimed`` names the published view the attempt points to, when it names one."""
    state = None
    try:
        state = attempt_state(capture_id, intake_dir, attempts_dir, drafts_dir, published_dir)
        if state["state"] in NOT_LISTED_STATES:
            return {"state": state["state"], "draft_id": state.get("draft_id"), "claimed": None,
                    "mode": state.get("mode"), "detail": state["detail"]}
        if state["state"] != "ready":
            return {"state": "unreadable", "draft_id": state.get("draft_id"), "claimed": state.get("draft_id"),
                    "problem": state["detail"]}
        data = draft_catalog.locate(drafts_dir, published_dir, state["draft_id"])
        if state["draft_id"] not in draft_catalog.tracker_files(published_dir):
            raise ValueError("its view is not in the Tracker's own draft folder")
        return {"state": "listed", "draft_id": state["draft_id"], "claimed": state["draft_id"],
                "entry": _entry(capture_id, verified(intake_dir, capture_id), state["mode"], data, reviews_dir)}
    except (FlowRefused, IntakeRefused, draft_catalog.CatalogRefused, OSError, ValueError, KeyError,
            TypeError) as exc:
        return {"state": "unreadable", "draft_id": None, "claimed": (state or {}).get("draft_id"),
                "problem": f"Capture {capture_id}: the recorded analysis could not be read ({exc})"}


def library_view(intake_dir: Path, attempts_dir: Path, drafts_dir: Path, published_dir: Path,
                 reviews_dir: Path) -> dict:
    """Every Tracker analysis with a published review view, every record that could not be read, and what is not
    listed. Reads only."""
    entries, damaged, claimed = [], [], set()
    not_listed = {state: 0 for state in NOT_LISTED_STATES}
    for row in listing(intake_dir):
        capture_id = row["capture_id"]
        if row["state"] == "refused":
            if (attempts_dir / capture_id).exists():  # An analysis was recorded for a capture that no longer verifies.
                damaged.append({"capture_id": capture_id, "draft_id": None, "problem": row["problem"]})
            continue
        analysis = capture_analysis(capture_id, intake_dir, attempts_dir, drafts_dir, published_dir, reviews_dir)
        if analysis["state"] in NOT_LISTED_STATES:
            not_listed[analysis["state"]] += 1
            continue
        if analysis["claimed"]:
            claimed.add(analysis["claimed"])
        if analysis["state"] == "unreadable":
            damaged.append({"capture_id": capture_id, "draft_id": analysis["draft_id"], "problem": analysis["problem"]})
        else:
            entries.append(analysis["entry"])
    named = {item["capture_id"] for item in damaged}
    for draft_id, path in draft_catalog.tracker_files(published_dir).items():
        if draft_id in claimed:
            continue
        try:  # Only to say which capture the file names; nothing it states is shown as a fact.
            case = json.loads(path.read_bytes())["provenance"]["case"]
            case = case if isinstance(case, str) else None
        except (OSError, ValueError, KeyError, TypeError):
            case = None
        if case in named:
            continue
        damaged.append({"capture_id": case, "draft_id": draft_id,
                        "problem": ("A published Tracker view is not backed by a verified capture and attempt; it is "
                                    "reported, never repaired")})
    try:
        prepared = draft_catalog.prepared_rows(drafts_dir)
        prepared_count = None if prepared is None else len(prepared)
    except (OSError, ValueError, KeyError, TypeError):
        prepared_count = None
    return {"view_version": LIBRARY_VIEW_VERSION, "provider_called": False,
            "entries": sorted(entries, key=lambda entry: (entry["provenance"]["sent_at"], entry["draft_id"]),
                              reverse=True),
            "damaged": damaged,
            "not_listed": {"saved_events": not_listed, "prepared_drafts": prepared_count}}
