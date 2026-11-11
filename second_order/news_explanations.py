"""Whether each story has a shared economic explanation, and if not, why (news-explanations-0.1).

An explanation is part of a story's brief (story_economics). A story's state says what a reader opening it gets:
``ready`` (a published explanation of the story's material as it is now, under the current analysis method),
``insufficient`` (the evidence was judged insufficient for one, or the material is too thin for a brief),
``drafted`` (a saved version with an explanation awaits publication), ``failed`` (the latest preparation for this
material was refused or failed, and nothing was saved since), ``outdated`` (the published explanation was prepared from
earlier material or under an earlier method), ``pending`` (none yet), ``restricted`` (no report whose publisher allows a
summary or analysis) and ``not_listed`` (not in the economic news, so none is prepared). Reading a state reads files.

0.2: a published explanation is current only when its material is the story's material as it is now, it was prepared
under the current analysis, calculation and guard versions, and none of the framework notes it used has been revised
or removed since (econ_framework.changed, against the notes it recorded or the archived framework it names); a revised
note it does not use leaves it current. ``reasons`` says why one is outdated.

0.3: a context bundle built for the story's current material after the explanation was prepared (econ_context) makes
it outdated too, so the next batch prepares it again with the newer context; a bundle it was prepared with, or one
built before it, does not.

0.4 (econ-explanation-0.4, econ-calc-0.3, econ-framework-0.3;
docs/news-econ-form-subject-2026-10-28.md (private; not in the public repository)): an explanation saved under
econ-explanation-0.3 and econ-calc-0.2 is read under that contract and is not outdated for its version alone
(econ_classification.READ_AS_CURRENT); it is outdated only when a rule of 0.4 can be shown, from what it recorded, to
affect it (econ_classification.reassessment: a share outside 0% to 100%, or a note it used that no longer applies to its
recorded subject or stage). A note counts as revised when what readers read of it changed (econ_framework.changed). An
explanation of 0.4 is outdated when a note it uses no longer applies to its subject, form and respondents. Any other
earlier version is outdated, as before.

0.5 and 0.6 (docs/news-claims-conditions-2026-10-29.md (private; not in the public repository),
docs/news-econ-consistency-2026-10-29.md (private; not in the public repository)): explanations of econ-explanation-0.4
and 0.5, with econ-calc-0.3, are read as current; only 0.3 is reassessed. """
import json
from pathlib import Path

from . import econ_calc, econ_classification, econ_framework, news_rank, story_economics

EXPLANATIONS_VERSION = "news-explanations-0.4"
STATES = ("ready", "insufficient", "drafted", "failed", "outdated", "pending", "restricted", "not_listed")
DRAFT_FAILURES = ("invalid", "provider_error", "unknown")
READER_TEXT = {
    "ready": None,
    "insufficient": "Its sources do not give enough evidence for an economic explanation.",
    "drafted": "An economic explanation has been prepared and awaits publication.",
    "failed": "Preparing an economic explanation for this story did not succeed, so none is published.",
    "outdated": ("This economic explanation was prepared from earlier material or under an earlier method; an updated "
                 "one is pending."),
    "pending": "No economic explanation has been prepared for this story yet.",
    "restricted": "Its publishers' terms allow no summary or analysis, so no economic explanation is prepared.",
    "not_listed": ("Economic explanations are prepared for stories in the economic news; this story is not listed "
                   "there."),
}


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def failures(newsroom_folder: Path) -> dict[str, list[dict]]:
    """Each story's recorded failed preparations: refused assisted imports and failed model drafts (reads only)."""
    rows: dict[str, list[dict]] = {}
    for path in sorted(newsroom_folder.glob("batches/batch-*/imports/*.json")):
        record = _read(path) or {}
        for item in record.get("items", []):
            if item.get("failed"):
                rows.setdefault(item["story_id"], []).append({
                    "material_sha256": item["material_sha256"], "at": record["at"], "detail": item.get("detail"),
                    "source": record["batch_id"]})
    for path in sorted(newsroom_folder.glob("drafting/brief-*/outcome.json")):
        outcome, preview = _read(path), _read(path.parent / "preview.json")
        if outcome and preview and outcome.get("outcome") in DRAFT_FAILURES:
            rows.setdefault(preview["story_id"], []).append({
                "material_sha256": preview["material_sha256"], "at": outcome["finished_at"],
                "detail": outcome.get("detail"), "source": preview["draft_id"]})
    return rows


def published(story: dict) -> dict | None:
    """The published brief's explanation, or None."""
    brief = story["brief"]
    return (brief["content"].get("economics") if brief else None) or None


def reasons(brief: dict, material_sha256: str | None = None, context: dict | None = None) -> list[str]:
    """Why a published explanation is not current: earlier material, an earlier method, a framework note it used
    that has been revised or removed, or newer context (``context``: the story's current bundle, econ_context.summary)
    gathered since it was prepared (empty when it is current)."""
    economics = brief["content"].get("economics")
    if not economics:
        return []
    analysis = brief["preparation"].get("analysis") or {}
    rows = []
    if material_sha256 is not None and brief["material_sha256"] != material_sha256:
        rows.append("it was prepared from earlier material")
    for name, now, then in (("analysis", story_economics.ANALYSIS_VERSION, economics["analysis_version"]),
                            ("calculation", econ_calc.CALC_VERSION, analysis.get("calc_version")),
                            ("guard", story_economics.GUARD_VERSION, analysis.get("guard_version"))):
        if then != now and then not in econ_classification.READ_AS_CURRENT.get(name, ()):
            rows.append(f"it was prepared under an earlier {name} method ({then or 'unrecorded'}; now {now})")
    if economics["status"] == "explained":
        found = story_economics.background(economics, analysis)
        if found["state"] == "unavailable":
            rows.append("the framework notes it used cannot be recovered")
        for row in econ_framework.changed(found["notes"]):
            rows.append(f"the framework note “{row['title']}” it uses has been {row['change']}")
        if economics["analysis_version"] == econ_classification.CLASSIFIED:
            current = econ_framework.framework()["notes"]
            for name in dict.fromkeys(row["note"] for row in economics["channels"] if row["note"]):
                reason = econ_classification.mismatch(current[name], economics["change"]) if name in current else None
                if reason:
                    rows.append(f"the framework note “{current[name]['title']}” it uses no longer applies: it {reason}")
        elif economics["analysis_version"] == "econ-explanation-0.3":  # Its explicit reassessment under 0.4's rules.
            rows += econ_classification.reassessment(economics, found["notes"])
    used = (analysis.get("context") or {}).get("bundle_id")
    if context and context["bundle_id"] != used and context.get("built_at", "") > brief["at"]:
        rows.append("newer context was gathered for this story after it was prepared")
    return rows


def state_of(folded: dict, story: dict, failed: dict[str, list[dict]]) -> str:
    if not story["material"]["reports"]:
        return "restricted"
    if not news_rank.listed(story):
        return "not_listed"
    material = story["material"]["material_sha256"]
    brief, economics = story["brief"], published(story)
    if economics and not reasons(brief, material, story.get("context_bundle")):
        return "ready" if economics["status"] == "explained" else "insufficient"
    newer = [row for row in folded["briefs"].get(story["story_id"], [])
             if row["material_sha256"] == material and "economics" in row["content"] and
             (brief is None or row["version"] > brief["version"])]
    since = newer[-1]["at"] if newer else ""
    if any(row["material_sha256"] == material and row["at"] > since for row in failed.get(story["story_id"], [])):
        return "failed"
    if newer:
        return "drafted"
    if story.get("insufficient"):
        return "insufficient"
    return "outdated" if economics else "pending"


def view(folded: dict, story: dict, failed: dict[str, list[dict]]) -> dict:
    """What a reader is told of the story's explanation when it is not ready."""
    state = state_of(folded, story, failed)
    economics = published(story)
    reason = None
    if state == "outdated":
        reason = "Outdated because " + "; ".join(reasons(story["brief"], story["material"]["material_sha256"],
                                                          story.get("context_bundle"))) + "."
    if state == "insufficient":
        reason = economics["insufficient_reason"] if economics and economics["status"] != "explained" else \
            story.get("insufficient")
    return {"state": state, "statement": READER_TEXT[state], "reason": reason}
