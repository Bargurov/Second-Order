"""Coverage baselines (news-baseline-0.1): the listed stories and their brief and explanation states at a fixed cutoff,
recorded once, so the completion of a piece of preparation work is reported on the stories selected then, and stories
that arrive or are listed later stay apart from it.

``record`` writes data/newsroom/baselines/<baseline ID>.json, write-once: the cutoff, the operator's label and, for
every story listed among the news then, its title, times, material (SHA-256 and coverage), published version, brief
state (news_batches) and explanation state (news_explanations). ``progress`` reads a baseline beside the stories as
they are now: each baseline story's states then and now (a story merged since is followed to the story it joined), the
counts of both, and the stories listed now that the baseline does not hold, apart, with whether they were first
reported after the cutoff. Both read and write local files only; nothing is requested from a publisher.
"""
from datetime import datetime
import json
from pathlib import Path
import re

from . import market_store, news_batches, news_explanations, news_rank, news_views, newsroom_store as ns
from .accounts import AccountsRefused

BASELINE_VERSION = "news-baseline-0.1"
BASELINE_ID = re.compile(r"baseline-[0-9a-f]{16}")
MAX_LABEL = 200


def _folder(desk: news_views.Desk) -> Path:
    return desk.newsroom.path.parent / "baselines"


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _row(found: dict, story: dict, failed: dict) -> dict:
    return {"story_id": story["story_id"], "title": story["title"], "first_at": story["first_at"],
            "latest_at": story["latest_at"], "material_sha256": story["material"]["material_sha256"],
            "material_coverage": story["material"]["coverage"],
            "published_version": story["brief"]["version"] if story["brief"] else None,
            "brief_state": news_batches.state_of(found["folded"], story),
            "explanation_state": news_explanations.state_of(found["folded"], story, failed)}


def _counts(rows: list[dict]) -> dict[str, int]:
    return {state: sum(1 for row in rows if row and row["explanation_state"] == state)
            for state in news_explanations.STATES}


def record(desk: news_views.Desk, now: datetime, actor: str, label: object) -> tuple[dict, bool]:
    """Record the listed stories and their states as they are at ``now`` (once)."""
    if not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL:
        raise AccountsRefused(422, "invalid_request", f"A baseline's label is 1 to {MAX_LABEL} characters.")
    found = news_views.world(desk, now)
    failed = news_explanations.failures(desk.newsroom.path.parent)
    rows = sorted((_row(found, story, failed) for story in found["stories"].values() if news_rank.listed(story)),
                  key=lambda row: (row["latest_at"], row["story_id"]), reverse=True)
    body = {"baseline_version": BASELINE_VERSION, "cutoff": ns.stamp(now), "label": label.strip(), "stories": rows}
    baseline_id = "baseline-" + ns.sha256_of(body)[:16]
    record = {**body, "baseline_id": baseline_id, "recorded_by": actor, "counts": _counts(rows), "statement": (
        "Every story listed among the news at the cutoff, with its brief and explanation states then. Progress is "
        "reported on these stories; stories listed later are shown apart.")}
    folder = _folder(desk)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        market_store.write_exclusive(folder / f"{baseline_id}.json", record)
    except FileExistsError:
        return _read(folder / f"{baseline_id}.json"), False
    return record, True


def load(desk: news_views.Desk, baseline_id: object) -> dict:
    if not isinstance(baseline_id, str) or not BASELINE_ID.fullmatch(baseline_id):
        raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
    found = _read(_folder(desk) / f"{baseline_id}.json")
    if found is None:
        raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
    return found


def listing(desk: news_views.Desk) -> list[dict]:
    """The recorded baselines, oldest first (reads only)."""
    folder = _folder(desk)
    rows = [_read(path) for path in sorted(folder.glob("baseline-*.json"))] if folder.is_dir() else []
    return sorted(({key: row[key] for key in ("baseline_id", "cutoff", "label", "counts")} for row in rows if row),
                  key=lambda row: (row["cutoff"], row["baseline_id"]))


def progress(desk: news_views.Desk, baseline_id: str, now: datetime) -> dict:
    """A baseline's stories then and now, and the stories listed now that it does not hold (reads only)."""
    baseline = load(desk, baseline_id)
    found = news_views.world(desk, now)
    failed = news_explanations.failures(desk.newsroom.path.parent)
    held, rows = set(), []
    for then in baseline["stories"]:
        target = ns.resolve_story(found["folded"], then["story_id"])
        story = found["stories"].get(target or "")
        current = _row(found, story, failed) if story is not None else None
        if current is not None:
            held.add(story["story_id"])
            current["listed"] = news_rank.listed(story)
        rows.append({"story_id": then["story_id"], "title": then["title"], "then": then, "now": current,
                     "merged_into": target if target not in (None, then["story_id"]) else None,
                     "material_changed": current is not None and current["material_sha256"] != then["material_sha256"],
                     "new_version": current is not None and current["published_version"] != then["published_version"]})
    later = sorted((_row(found, story, failed) for story in found["stories"].values()
                    if news_rank.listed(story) and story["story_id"] not in held),
                   key=lambda row: (row["latest_at"], row["story_id"]), reverse=True)
    for row in later:
        row["first_reported_after_cutoff"] = row["first_at"] > baseline["cutoff"]
    return {"baseline_version": BASELINE_VERSION, "baseline_id": baseline_id, "cutoff": baseline["cutoff"],
            "label": baseline["label"], "as_of": ns.stamp(now), "counts_then": baseline["counts"],
            "counts_now": _counts([row["now"] for row in rows]), "stories": rows,
            "gone": [row["story_id"] for row in rows if row["now"] is None],
            "outside_baseline": {"stories": len(later), "counts": _counts(later), "rows": later},
            "statement": ("The baseline's stories as they were at the cutoff and as they are now; stories listed now "
                          "that it does not hold are counted apart, never in its progress.")}
