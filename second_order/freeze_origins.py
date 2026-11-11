"""The two origins of an interface freeze, and the folders a freeze reads. Reads only; nothing here writes.

- manual: the structured form on the registered H.15 observables, with honest engine provenance (provider "manual",
  the stated authoring as its model text, and the SHA-256 of the exact submitted input as its prompt_hash);
- model: a reviewed draft of the Tracker's paid run under the H.15 drafting contract, with only the corrections the
  review workflow permits applied, its engine record unchanged, and its derivation returned for the freeze record.

See lifecycle for the preview and the freeze that use them.
"""
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Callable
import unicodedata

from . import analysis_library, draft_catalog, event_intake, human_review, market_store
from .analysis_flow import ATTEMPTS_DIR, FlowRefused, explicit_publication_time
from .draft_views import DRAFTS_DIR
from .model_draft import H15_PROMPT_VERSION, DraftRefused, operator_event
from .registry import BOARD_H15, binding, source_bound
from .store import digest

LIFECYCLE_VERSION = "lifecycle-freeze-0.1"
MANUAL_INPUT_VERSION = "manual-hypothesis-input-0.1"
ROOT = Path(__file__).resolve().parent.parent
STORE_PATH = ROOT / "data" / "real" / "second-order.db"  # The local store; the server is started with its path.
H15_IDS = tuple(sorted(source_bound(BOARD_H15)))
LEGS = {"yield:ust2y_cmt_h15": ("two", "two-year", "2-year Treasury yield (Board H.15)"),
        "yield:ust10y_cmt_h15": ("ten", "ten-year", "10-year Treasury yield (Board H.15)")}
MANUAL_FIELDS = ("headline", "source_url", "published_at", "story_id", "summary", "authoring", "legs")
LEG_FIELDS = ("observable_id", "primary", "expected", "horizon", "link", "channel", "rationale", "falsifier",
              "headline_reports_move")

class LifecycleRefused(ValueError):
    def __init__(self, status: int, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status, self.extra = status, extra or {}


@dataclass(frozen=True)
class Folders:
    store: Path = STORE_PATH
    market: Path = market_store.STORE_DIR
    intake: Path = event_intake.INTAKE_DIR
    attempts: Path = ATTEMPTS_DIR
    drafts: Path = DRAFTS_DIR
    published: Path | None = None
    reviews: Path = human_review.REVIEWS_DIR

    @property
    def tracker(self) -> Path:
        return self.published or draft_catalog.tracker_dir(self.drafts)

    @property
    def dossiers(self) -> Path:
        """Where this store's assessments are prepared as Dossiers, one file each; created only by preparation."""
        return self.store.parent / f"{self.store.stem}-dossiers"


def plain(value: object, field: str, limit: int = 4000, line: bool = False) -> str:
    """Non-empty text without leading or trailing spaces or control characters (one line when ``line``)."""
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > limit:
        raise LifecycleRefused(422, f"{field} must be non-empty text of at most {limit} characters, without leading or "
                                    "trailing spaces")
    allowed = () if line else ("\n",)
    if any(unicodedata.category(char) in ("Cc", "Zl", "Zp") and char not in allowed for char in value):
        raise LifecycleRefused(422, f"{field} contains a control character" + (" or line break" if line else ""))
    return value


# ---------------------------------------------------------------- the two origins

def manual_draft(manual: dict, clock: Callable[[], datetime]) -> tuple[dict, dict]:
    """The effective hypothesis (without a freeze time) of the structured form, and its manual-input provenance."""
    if set(manual) != set(MANUAL_FIELDS):
        raise LifecycleRefused(422, f"The form must contain exactly {', '.join(MANUAL_FIELDS)}")
    try:
        explicit_publication_time(manual["published_at"] if isinstance(manual["published_at"], str) else "")
    except FlowRefused as exc:
        raise LifecycleRefused(exc.status, str(exc)) from None
    headline = plain(manual["headline"], "The headline", 1500, line=True)
    story = plain(manual["story_id"], "The story ID", 200, line=True)
    summary = plain(manual["summary"], "The summary")
    authoring = plain(manual["authoring"], "How the content was authored", 600, line=True)
    try:
        event, story = operator_event({"headline": headline, "source_url": manual["source_url"],
                                       "published_at": manual["published_at"], "story_id": story}, clock)
    except DraftRefused as exc:
        raise LifecycleRefused(422, str(exc)) from None
    legs = manual["legs"]
    if not isinstance(legs, list) or len(legs) != len(H15_IDS) or not all(isinstance(leg, dict) for leg in legs):
        raise LifecycleRefused(422, f"Give one leg for each H.15 observable ({', '.join(H15_IDS)})")
    built, channels = [], []
    for leg in legs:
        if set(leg) != set(LEG_FIELDS):
            raise LifecycleRefused(422, f"Each leg must contain exactly {', '.join(LEG_FIELDS)}")
        if leg["observable_id"] not in LEGS:
            raise LifecycleRefused(422, f"A leg's observable must be one of {', '.join(H15_IDS)}")
        if type(leg["primary"]) is not bool or type(leg["headline_reports_move"]) is not bool:
            raise LifecycleRefused(422, "primary and headline_reports_move must be true or false; neither has a default")
        if type(leg["horizon"]) is not int or leg["horizon"] not in (1, 5, 20):
            raise LifecycleRefused(422, "A leg's horizon must be 1, 5 or 20 observations")
        if leg["expected"] not in ("up", "down") or leg["link"] not in ("direct", "proxy"):
            raise LifecycleRefused(422, "A leg's direction must be up or down, and its link direct or proxy")
        channel = plain(leg["channel"], "A leg's channel", 200, line=True)
        node, leg_id, _ = LEGS[leg["observable_id"]]
        if channel not in channels:
            channels.append(channel)
        built.append({"id": leg_id, "node_id": node, "primary": leg["primary"], "channel": channel,
                      "observable_id": leg["observable_id"], "link": leg["link"], "expected": leg["expected"],
                      "horizon": leg["horizon"], "falsifier": plain(leg["falsifier"], "A leg's falsifier"),
                      "rationale": plain(leg["rationale"], "A leg's rationale"),
                      "headline_reports_move": leg["headline_reports_move"]})
    if {leg["observable_id"] for leg in built} != set(H15_IDS):
        raise LifecycleRefused(422, "Use each H.15 observable exactly once")
    if sum(leg["primary"] for leg in built) != 1:
        raise LifecycleRefused(422, "Choose exactly one primary leg")
    channel_ids = {channel: f"channel-{number}" for number, channel in enumerate(channels, start=1)}
    nodes = [{"id": "event", "label": "Published event", "kind": "event"},
             *({"id": channel_ids[channel], "label": channel, "kind": "channel"} for channel in channels),
             *({"id": LEGS[leg["observable_id"]][0], "label": LEGS[leg["observable_id"]][2], "kind": "observable"}
               for leg in built)]
    edges = [*({"source": "event", "target": channel_ids[channel]} for channel in channels),
             *({"source": channel_ids[leg["channel"]], "target": leg["node_id"]} for leg in built)]
    record = {"input_version": MANUAL_INPUT_VERSION, **manual}
    engine = {"provider": "manual", "model": f"Entered in the Second Order interface form; authoring as stated: {authoring}",
              "prompt_hash": digest(record), "schema_version": "0.2"}
    draft = {"event": event, "evidence_class": "prospective", "usage": "showcase", "story_id": story,
             "engine": engine, "summary": summary, "nodes": nodes, "edges": edges,
             "legs": sorted(built, key=lambda leg: leg["id"], reverse=True)}
    origin = {"kind": "manual", "manual_input": record, "manual_input_sha256": digest(record),
              "published_at_as_supplied": manual["published_at"],
              "publication_precision": "a time with an explicit UTC offset, as supplied in the form"}
    return draft, origin


def _capture_story(folders: Folders, capture_id: str) -> str:
    manifest_bytes, _, _ = event_intake.load(folders.intake, capture_id)
    story = json.loads(manifest_bytes).get("story_id")
    if not isinstance(story, str) or not story:
        raise LifecycleRefused(409, f"Capture {capture_id} records no story ID")
    return story


def draft_eligibility(entry: dict) -> list[str]:
    """Why a verified Tracker analysis cannot be frozen (empty when it can)."""
    reasons = []
    if entry["mode"] != "paid":
        reasons.append("It was generated by the local mock, a synthetic fixture; only a real provider draft can be "
                       "frozen.")
    if entry["outcome"] != "draft":
        reasons.append({"no_draft": "The model declined to draft, so there is no hypothesis.",
                        "invalid": "The response did not pass the adapter's validation.",
                        "technical_failure": "The attempt failed technically."}.get(entry["outcome"],
                                                                                   "There is no draft."))
    if entry["provenance"]["prompt_version"] != H15_PROMPT_VERSION:
        reasons.append(f"Its request was saved under {entry['provenance']['prompt_version']}, which offers FRED IDs; "
                       f"only {H15_PROMPT_VERSION} requests (H.15 IDs) can be frozen here, and a saved request is "
                       "never rebuilt or remapped.")
    review = entry["review"]
    if review["state"] == "none":
        reasons.append("No human review is saved.")
    elif review["state"] == "stale":
        reasons.append("Its latest review was saved against an earlier view, so this view has no current review.")
    elif review["state"] == "invalid":
        reasons.append(f"Its review history does not verify ({review.get('problem')}).")
    elif review.get("status") != "human_reviewed":
        reasons.append("Its current review does not have the status Human-reviewed.")
    return reasons


def drafts_listing(folders: Folders) -> dict:
    """Every Tracker analysis with its freeze eligibility and reasons. Reads only."""
    library = analysis_library.library_view(folders.intake, folders.attempts, folders.drafts, folders.tracker,
                                            folders.reviews)
    rows = []
    for entry in library["entries"]:
        reasons = draft_eligibility(entry)
        rows.append({"draft_id": entry["draft_id"], "capture_id": entry["capture_id"],
                     "headline": entry["event"]["headline"], "published_at": entry["event"]["published_at"],
                     "published_at_as_supplied": entry["event"]["published_at_as_supplied"], "mode": entry["mode"],
                     "outcome": entry["outcome"], "prompt_version": entry["provenance"]["prompt_version"],
                     "model": entry["provenance"]["model"], "review": entry["review"],
                     "eligible": not reasons, "reasons": reasons})
    return {"lifecycle_version": LIFECYCLE_VERSION, "contract": H15_PROMPT_VERSION, "drafts": rows,
            "unreadable": library["damaged"],
            "note": "Human review is a person's judgment of the content; it is not approval to freeze."}


def model_draft(draft_id: str, folders: Folders) -> tuple[dict, dict]:
    """The effective hypothesis of an eligible reviewed model draft, and its derivation. Reads only."""
    try:
        data = draft_catalog.locate(folders.drafts, folders.tracker, draft_id)
    except draft_catalog.CatalogRefused as exc:
        raise LifecycleRefused(exc.status, str(exc)) from None
    if draft_id not in draft_catalog.tracker_files(folders.tracker):
        raise LifecycleRefused(409, "Only the Tracker's own drafts can be frozen; prepared pilot drafts are synthetic")
    view = json.loads(data)
    capture_id = view["provenance"]["case"]
    analysis = analysis_library.capture_analysis(capture_id, folders.intake, folders.attempts, folders.drafts,
                                                 folders.tracker, folders.reviews)
    if analysis["state"] != "listed" or analysis["entry"]["draft_id"] != draft_id:
        raise LifecycleRefused(409, f"The draft's analysis cannot be read as verified: "
                                    f"{analysis.get('problem') or analysis.get('detail') or analysis['state']}")
    entry = analysis["entry"]
    reasons = draft_eligibility(entry)
    if reasons:
        raise LifecycleRefused(409, "This draft is not eligible for a freeze: " + " ".join(reasons))
    records = human_review.history(folders.reviews, draft_id)
    latest = records[-1]
    if latest["binding"]["draft_view_sha256"] != human_review.fingerprint(data) or latest["status"] != "human_reviewed":
        raise LifecycleRefused(409, "The draft's review changed while it was read; reload and preview again")
    record = event_intake.verified(folders.intake, capture_id)
    source = view["source"]
    if {key: source[key] for key in ("headline", "source_url", "published_at")} != record["event"] \
            or view["provenance"]["prompt_hash"] != record["request"]["sha256"]:
        raise LifecycleRefused(409, "The draft's view does not match its capture; it cannot be frozen")
    proposal = view["draft"]
    corrections = latest["corrections"]
    legs = []
    for leg in proposal["legs"]:
        if binding(leg["observable_id"]) is None or binding(leg["observable_id"])[0] != BOARD_H15:
            raise LifecycleRefused(409, f"The draft's leg {leg['id']} is not bound to the Board's H.15 data")
        legs.append({**leg, **corrections["legs"].get(leg["id"], {})})
    engine = {"provider": "anthropic", "model": view["provenance"]["model"],
              "prompt_hash": view["provenance"]["prompt_hash"], "schema_version": "0.2"}
    draft = {"event": record["event"], "evidence_class": "prospective", "usage": "showcase",
             "story_id": _capture_story(folders, capture_id), "engine": engine,
             "summary": corrections["summary"] if corrections["summary"] is not None else proposal["summary"],
             "nodes": proposal["nodes"], "edges": proposal["edges"], "legs": legs}
    origin = {"kind": "model", "draft_id": draft_id, "capture_id": capture_id,
              "draft_view_sha256": human_review.fingerprint(data), "prompt_version": view["provenance"]["prompt_version"],
              "request_sha256": view["provenance"]["prompt_hash"], "response_sha256": view["provenance"]["response_sha256"],
              "request_id": view["provenance"]["request_id"], "model": view["provenance"]["model"],
              "model_output_sha256": digest(proposal),
              "review": {key: latest[key] for key in ("review_id", "sequence", "status", "saved_at", "attributed_to")},
              "corrections": corrections,
              "published_at_as_supplied": record["times"]["published_at_as_supplied"],
              "publication_precision": "a time with an explicit UTC offset, as supplied when the event was captured"}
    return draft, origin
