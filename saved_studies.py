"""Persistent saved study definitions — CRUD only, no execution.

Stores deterministic inputs (filters / config) for four research workflows:

    * ``cohort_comparison``      — paired-cohort diff over the archive
    * ``correlation_study``      — ``cross_event_studies`` slice
    * ``scenario_pack_research`` — ``cohort_research.run_batch_research`` over
      a named pack from ``cohort_research.SCENARIO_PACKS``
    * ``cascade_view``           — ``event_graph.build_event_graph`` focus

A saved study is *just the configuration*.  The caller re-runs the
composer on load; nothing here snapshots computed output.  That keeps
saved views replayable as the archive grows and avoids storing stale
numbers that drift out of sync with the live tape.

The per-type config schemas are closed — unknown keys raise
``ValueError`` — so a mistyped filter never silently matches every
event at replay time.  ``UNIQUE(study_type, name)`` is enforced at the
DB level; callers must pass ``overwrite=True`` to reuse a name.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from db import DB_FILE


# ---------------------------------------------------------------------------
# Enum — the closed set of study kinds callers may persist.
# ---------------------------------------------------------------------------

STUDY_TYPE_IDS: tuple[str, ...] = (
    "cohort_comparison",
    "correlation_study",
    "scenario_pack_research",
    "cascade_view",
    "portfolio_view",
)

_STUDY_TYPE_ENUM: frozenset[str] = frozenset(STUDY_TYPE_IDS)


# ---------------------------------------------------------------------------
# Per-type config validators.  Each returns a NORMALISED copy of the
# config dict.  Raises ``ValueError`` on unknown keys, missing required
# keys, or invalid values.
# ---------------------------------------------------------------------------

def _require_dict(config: Any, *, study_type: str) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError(
            f"config for study_type={study_type!r} must be a dict, "
            f"got {type(config).__name__}"
        )
    return dict(config)


def _validate_cohort_comparison(config: Any) -> dict[str, Any]:
    cfg = _require_dict(config, study_type="cohort_comparison")
    allowed = {"filter_a", "filter_b", "label_a", "label_b"}
    unknown = set(cfg.keys()) - allowed
    if unknown:
        raise ValueError(
            f"cohort_comparison config has unknown keys: {sorted(unknown)}; "
            f"allowed: {sorted(allowed)}"
        )
    if "filter_a" not in cfg or "filter_b" not in cfg:
        raise ValueError(
            "cohort_comparison config requires 'filter_a' and 'filter_b'"
        )
    # Delegate filter-shape validation to cohort_comparison — single source
    # of truth for the allowed filter keys so we never drift.
    from cohort_comparison import _validate_filter_spec
    out: dict[str, Any] = {
        "filter_a": _validate_filter_spec(cfg["filter_a"], which="a"),
        "filter_b": _validate_filter_spec(cfg["filter_b"], which="b"),
    }
    for opt in ("label_a", "label_b"):
        val = cfg.get(opt)
        if val is None or val == "":
            continue
        if not isinstance(val, str):
            raise ValueError(f"{opt!r} must be a string if provided")
        out[opt] = val.strip()
    return out


def _validate_correlation_study(config: Any) -> dict[str, Any]:
    cfg = _require_dict(config, study_type="correlation_study")
    allowed = {"limit"}
    unknown = set(cfg.keys()) - allowed
    if unknown:
        raise ValueError(
            f"correlation_study config has unknown keys: {sorted(unknown)}; "
            f"allowed: {sorted(allowed)}"
        )
    out: dict[str, Any] = {}
    if "limit" in cfg and cfg["limit"] is not None:
        limit = cfg["limit"]
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("correlation_study.limit must be an int")
        if limit < 50 or limit > 1000:
            raise ValueError(
                "correlation_study.limit must be in [50, 1000]"
            )
        out["limit"] = limit
    return out


def _validate_scenario_pack_research(config: Any) -> dict[str, Any]:
    cfg = _require_dict(config, study_type="scenario_pack_research")
    allowed = {"pack_name", "limit"}
    unknown = set(cfg.keys()) - allowed
    if unknown:
        raise ValueError(
            f"scenario_pack_research config has unknown keys: "
            f"{sorted(unknown)}; allowed: {sorted(allowed)}"
        )
    if "pack_name" not in cfg:
        raise ValueError(
            "scenario_pack_research config requires 'pack_name'"
        )
    from cohort_research import SCENARIO_PACKS
    pack = cfg["pack_name"]
    if not isinstance(pack, str) or pack not in SCENARIO_PACKS:
        raise ValueError(
            f"scenario_pack_research.pack_name={pack!r} is not a known "
            f"scenario pack; allowed: {sorted(SCENARIO_PACKS.keys())}"
        )
    out: dict[str, Any] = {"pack_name": pack}
    if "limit" in cfg and cfg["limit"] is not None:
        limit = cfg["limit"]
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("scenario_pack_research.limit must be an int")
        if limit < 50 or limit > 1000:
            raise ValueError(
                "scenario_pack_research.limit must be in [50, 1000]"
            )
        out["limit"] = limit
    return out


def _validate_cascade_view(config: Any) -> dict[str, Any]:
    cfg = _require_dict(config, study_type="cascade_view")
    allowed = {"focal_event_id", "family", "min_weight", "active_only"}
    unknown = set(cfg.keys()) - allowed
    if unknown:
        raise ValueError(
            f"cascade_view config has unknown keys: {sorted(unknown)}; "
            f"allowed: {sorted(allowed)}"
        )
    out: dict[str, Any] = {}
    if "focal_event_id" in cfg and cfg["focal_event_id"] is not None:
        fid = cfg["focal_event_id"]
        if not isinstance(fid, int) or isinstance(fid, bool):
            raise ValueError("cascade_view.focal_event_id must be an int")
        out["focal_event_id"] = fid
    if "family" in cfg and cfg["family"]:
        fam = cfg["family"]
        if not isinstance(fam, str):
            raise ValueError("cascade_view.family must be a string")
        from mechanism_family import FAMILY_IDS
        if fam not in FAMILY_IDS:
            raise ValueError(
                f"cascade_view.family={fam!r} is not a known mechanism "
                f"family; allowed: {sorted(FAMILY_IDS)}"
            )
        out["family"] = fam
    if "min_weight" in cfg and cfg["min_weight"] is not None:
        mw = cfg["min_weight"]
        if isinstance(mw, bool) or not isinstance(mw, (int, float)):
            raise ValueError("cascade_view.min_weight must be a number")
        if not 0.0 <= float(mw) <= 1.0:
            raise ValueError("cascade_view.min_weight must be in [0, 1]")
        out["min_weight"] = float(mw)
    if "active_only" in cfg and cfg["active_only"] is not None:
        ao = cfg["active_only"]
        if not isinstance(ao, bool):
            raise ValueError("cascade_view.active_only must be a bool")
        out["active_only"] = ao
    return out


def _validate_portfolio_view(config: Any) -> dict[str, Any]:
    """Validate a ``portfolio_view`` config — the mover-aware
    filter set that reproduces a Portfolio page view on replay.

    All keys are optional; a config with zero filters is valid (it
    simply reproduces the default portfolio).  Each filter that is
    present is validated against the same enum the live /portfolio
    route accepts, so saved views can't pin a value the route itself
    would reject.
    """
    cfg = _require_dict(config, study_type="portfolio_view")
    allowed = {
        "mover_window", "queue", "thesis_state",
        "proof_quality", "low_information",
        # Engine-phase filters — surfaced by ``engine_phase_surface``
        # on every /portfolio row; saveable so a view that pinned
        # "actionable + tradable + tariff" replays the same set on
        # any tape.
        "quality_tier", "tradable", "mechanism_subtype",
    }
    unknown = set(cfg.keys()) - allowed
    if unknown:
        raise ValueError(
            f"portfolio_view config has unknown keys: {sorted(unknown)}; "
            f"allowed: {sorted(allowed)}"
        )
    out: dict[str, Any] = {}

    mw = cfg.get("mover_window")
    if mw is not None and mw != "":
        if not isinstance(mw, str):
            raise ValueError("portfolio_view.mover_window must be a string")
        from mover_card_normalizer import MOVER_WINDOWS
        if mw not in MOVER_WINDOWS:
            raise ValueError(
                f"portfolio_view.mover_window={mw!r} is not one of "
                f"{list(MOVER_WINDOWS)}"
            )
        out["mover_window"] = mw

    q = cfg.get("queue")
    if q is not None and q != "":
        if not isinstance(q, str):
            raise ValueError("portfolio_view.queue must be a string")
        from portfolio_flags import QUEUE_IDS
        if q not in QUEUE_IDS:
            raise ValueError(
                f"portfolio_view.queue={q!r} is not one of {list(QUEUE_IDS)}"
            )
        out["queue"] = q

    ts = cfg.get("thesis_state")
    if ts is not None and ts != "":
        if not isinstance(ts, str):
            raise ValueError("portfolio_view.thesis_state must be a string")
        from thesis_state import THESIS_STATES
        if ts not in THESIS_STATES:
            raise ValueError(
                f"portfolio_view.thesis_state={ts!r} is not one of "
                f"{list(THESIS_STATES)}"
            )
        out["thesis_state"] = ts

    pq = cfg.get("proof_quality")
    if pq is not None and pq != "":
        if not isinstance(pq, str):
            raise ValueError("portfolio_view.proof_quality must be a string")
        from portfolio_flags import PROOF_QUALITY_BUCKETS
        if pq not in PROOF_QUALITY_BUCKETS:
            raise ValueError(
                f"portfolio_view.proof_quality={pq!r} is not one of "
                f"{list(PROOF_QUALITY_BUCKETS)}"
            )
        out["proof_quality"] = pq

    if "low_information" in cfg and cfg["low_information"] is not None:
        li = cfg["low_information"]
        if not isinstance(li, bool):
            raise ValueError(
                "portfolio_view.low_information must be a bool or omitted"
            )
        out["low_information"] = li

    qt = cfg.get("quality_tier")
    if qt is not None and qt != "":
        if not isinstance(qt, str):
            raise ValueError("portfolio_view.quality_tier must be a string")
        from low_information_gate import EVIDENCE_QUALITY_TIERS
        if qt not in EVIDENCE_QUALITY_TIERS:
            raise ValueError(
                f"portfolio_view.quality_tier={qt!r} is not one of "
                f"{list(EVIDENCE_QUALITY_TIERS)}"
            )
        out["quality_tier"] = qt

    if "tradable" in cfg and cfg["tradable"] is not None:
        tr = cfg["tradable"]
        if not isinstance(tr, bool):
            raise ValueError(
                "portfolio_view.tradable must be a bool or omitted"
            )
        out["tradable"] = tr

    sub = cfg.get("mechanism_subtype")
    if sub is not None and sub != "":
        # Open-ended (per-family registry); the live route accepts any
        # string and yields zero results on no-match.  Mirror that
        # contract here — string type only, no enum check.
        if not isinstance(sub, str):
            raise ValueError("portfolio_view.mechanism_subtype must be a string")
        out["mechanism_subtype"] = sub

    return out


_VALIDATORS = {
    "cohort_comparison":      _validate_cohort_comparison,
    "correlation_study":      _validate_correlation_study,
    "scenario_pack_research": _validate_scenario_pack_research,
    "cascade_view":           _validate_cascade_view,
    "portfolio_view":         _validate_portfolio_view,
}


def _validate_config(study_type: str, config: Any) -> dict[str, Any]:
    if study_type not in _STUDY_TYPE_ENUM:
        raise ValueError(
            f"unknown study_type={study_type!r}; "
            f"allowed: {sorted(STUDY_TYPE_IDS)}"
        )
    return _VALIDATORS[study_type](config)


# ---------------------------------------------------------------------------
# CRUD — thin SQLite layer over the ``saved_studies`` table.  See
# ``db.py`` for the schema; UNIQUE(study_type, name) means name collisions
# surface here as sqlite3.IntegrityError unless overwrite=True is passed.
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_study(row: sqlite3.Row | tuple) -> dict[str, Any]:
    return {
        "id":          row[0],
        "study_type":  row[1],
        "name":        row[2],
        "description": row[3] or "",
        "config":      json.loads(row[4]) if row[4] else {},
        "created_at":  row[5],
        "updated_at":  row[6],
    }


def save_study(
    study_type: str,
    name: str,
    config: Any,
    *,
    description: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Persist a study definition.  Returns the stored row as a dict.

    Raises ``ValueError`` on unknown ``study_type``, invalid config, blank
    ``name``, or duplicate ``(study_type, name)`` when ``overwrite=False``.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    if not isinstance(description, str):
        raise ValueError("description must be a string")
    normalised = _validate_config(study_type, config)
    name = name.strip()
    now = _utcnow_iso()
    payload = json.dumps(normalised, sort_keys=True)

    with sqlite3.connect(DB_FILE) as conn:
        existing = conn.execute(
            "SELECT id, created_at FROM saved_studies "
            "WHERE study_type = ? AND name = ?",
            (study_type, name),
        ).fetchone()
        if existing is None:
            cur = conn.execute(
                "INSERT INTO saved_studies "
                "(study_type, name, description, config_json, "
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (study_type, name, description, payload, now, now),
            )
            study_id = cur.lastrowid
        else:
            if not overwrite:
                raise ValueError(
                    f"saved study {(study_type, name)!r} already exists; "
                    f"pass overwrite=True to update it"
                )
            study_id = existing[0]
            conn.execute(
                "UPDATE saved_studies "
                "SET description = ?, config_json = ?, updated_at = ? "
                "WHERE id = ?",
                (description, payload, now, study_id),
            )

    return load_study(study_id)  # round-trip so the caller sees DB state


def load_study(study_id: int) -> Optional[dict[str, Any]]:
    """Return the stored study row by id, or ``None`` when missing."""
    if not isinstance(study_id, int) or isinstance(study_id, bool):
        raise ValueError("study_id must be an int")
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            "SELECT id, study_type, name, description, config_json, "
            "       created_at, updated_at "
            "FROM saved_studies WHERE id = ?",
            (study_id,),
        ).fetchone()
    return _row_to_study(row) if row else None


def list_studies(study_type: Optional[str] = None) -> list[dict[str, Any]]:
    """Return every saved study, newest first.  Optionally filter by type."""
    if study_type is not None and study_type not in _STUDY_TYPE_ENUM:
        raise ValueError(
            f"unknown study_type={study_type!r}; "
            f"allowed: {sorted(STUDY_TYPE_IDS)}"
        )
    with sqlite3.connect(DB_FILE) as conn:
        if study_type is None:
            rows = conn.execute(
                "SELECT id, study_type, name, description, config_json, "
                "       created_at, updated_at "
                "FROM saved_studies ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, study_type, name, description, config_json, "
                "       created_at, updated_at "
                "FROM saved_studies WHERE study_type = ? "
                "ORDER BY updated_at DESC, id DESC",
                (study_type,),
            ).fetchall()
    return [_row_to_study(r) for r in rows]


def delete_study(study_id: int) -> bool:
    """Delete by id.  Returns True when a row was removed, else False."""
    if not isinstance(study_id, int) or isinstance(study_id, bool):
        raise ValueError("study_id must be an int")
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute(
            "DELETE FROM saved_studies WHERE id = ?", (study_id,)
        )
        return cur.rowcount > 0


_UNCHANGED = object()   # sentinel for update_study "field not supplied"


def update_study(
    study_id: int,
    *,
    name: Any = _UNCHANGED,
    description: Any = _UNCHANGED,
    config: Any = _UNCHANGED,
) -> Optional[dict[str, Any]]:
    """Update a saved study in place by ``study_id``.

    Unlike ``save_study`` — which looks up by ``(study_type, name)``
    and INSERTs when no match is found — this function always operates
    on the row identified by ``study_id``.  A rename therefore updates
    the existing row rather than spawning a duplicate under the new
    name.

    Only the fields the caller supplies are rewritten; omitted fields
    keep their previous values.  ``_UNCHANGED`` is the sentinel that
    distinguishes "caller omitted" from "caller explicitly passed
    None / empty".  Returns the updated row as a dict or ``None``
    when ``study_id`` does not exist.
    """
    if not isinstance(study_id, int) or isinstance(study_id, bool):
        raise ValueError("study_id must be an int")

    existing = load_study(study_id)
    if existing is None:
        return None

    new_name: str
    if name is _UNCHANGED:
        new_name = existing["name"]
    else:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        new_name = name.strip()

    new_description: str
    if description is _UNCHANGED:
        new_description = existing["description"]
    else:
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        new_description = description

    if config is _UNCHANGED:
        normalised = existing["config"]
    else:
        normalised = _validate_config(existing["study_type"], config)

    payload = json.dumps(normalised, sort_keys=True)
    now = _utcnow_iso()
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "UPDATE saved_studies "
            "SET name = ?, description = ?, config_json = ?, updated_at = ? "
            "WHERE id = ?",
            (new_name, new_description, payload, now, study_id),
        )
    return load_study(study_id)
