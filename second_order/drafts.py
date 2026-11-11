"""Freeze helper for manual prospective showcase drafts: it stamps the real freeze time.

A draft is a hypothesis without a freeze time. The helper validates it strictly, stamps the
current UTC time, and stores it with its baseline snapshot through the ordinary append-only
freeze (readiness, possession and backdating checks included). It never writes to the draft and
never restamps: a draft whose request is already frozen is refused.
"""
from datetime import datetime, timezone
import sqlite3
from typing import Callable
from .schema import Hypothesis, utc
from .store import freeze, request_identity

STAMPED_FIELDS = ("frozen_at", "replay_as_of", "supersedes")


def freeze_draft(connection: sqlite3.Connection, draft: dict, baseline_snapshot_id: str | None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    if not isinstance(draft, dict):
        raise ValueError("A draft must be a JSON object")
    carried = [field for field in STAMPED_FIELDS if field in draft]
    if carried:
        raise ValueError(f"A draft must not carry {', '.join(carried)}; the helper stamps the freeze time")
    if draft.get("evidence_class") != "prospective" or draft.get("usage") != "showcase":
        raise ValueError("The freeze helper accepts only prospective showcase drafts; research intake is closed")
    if not isinstance(draft.get("engine"), dict) or draft["engine"].get("provider") != "manual":
        raise ValueError("The freeze helper accepts only manual drafts")
    frozen_at = utc(clock())
    hypothesis = Hypothesis.model_validate({**draft, "frozen_at": frozen_at})
    existing = connection.execute("SELECT id, recorded_at FROM hypotheses WHERE request_hash=?",
                                  (request_identity(hypothesis),)).fetchone()
    if existing:
        raise ValueError(f"This draft was already frozen as {existing[0]} at {existing[1]}; "
                         "frozen records are never restamped")
    identity = freeze(connection, hypothesis, frozen_at, baseline_snapshot_id)
    recorded_at = connection.execute("SELECT recorded_at FROM hypotheses WHERE id=?", (identity,)).fetchone()[0]
    bound_at = connection.execute("SELECT bound_at FROM freeze_bindings WHERE hypothesis_id=?",
                                  (identity,)).fetchone()
    return {"hypothesis_id": identity, "frozen_at": hypothesis.frozen_at.isoformat(), "recorded_at": recorded_at,
            "baseline_snapshot_id": baseline_snapshot_id, "bound_at": bound_at[0] if bound_at else None}
