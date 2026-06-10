"""Read-only loader for Second Order Phase 1 + Phase 2 candidate evidence.

Normalizes the two tracked evidence artifacts into a single per-record
shape so backend / platform code can consume the cohort without
re-implementing the JSON walk every time.

Two artifacts, two scopes
-------------------------

* Phase 1 — ``evidence_artifacts/section_c_v2/freeze_candidate_evidence.json``.
  Five-row freeze-candidate cohort (WHR / TXT / FSLR / RIO / LITE)
  with frozen BH q-values computed against a five-row Phase 1
  denominator.
* Phase 2 — ``evidence_artifacts/section_c_v2/phase2_pool_v1.json``. Closed
  Phase 2 BH/FDR pool (BA / ALB / NVDA / AMAT / CF) with q-values
  computed against an independent five-row Phase 2 denominator.

The two pools are SEPARATE FDR scopes. This loader returns Phase 1
and Phase 2 records labelled with their phase; q-values are NEVER
mixed, recomputed, or compared across scopes. Callers that want to
present a row's BH significance must use the ``phase`` field to
identify which denominator the ``q_bh`` was drawn from.

Read-only by construction
-------------------------

* No DB reads or writes. No provider / yfinance / market_data /
  ``price_cache.fetch_*``. No FastAPI / ``api`` / ``routes.*``. No LLM.
  Imports limited to ``json``, ``pathlib``, ``typing``, and
  ``__future__``.
* Source artifacts are opened in ``"r"`` mode only. Byte identity of
  every loaded file is preserved across a load call (verified by the
  tests' hash-invariance check).
* No artifact mutation, no side-effect filesystem writes, no implicit
  cache population.

Public surface
--------------

* :func:`load_phase1` — list of normalized Phase 1 records. Raises
  :class:`FileNotFoundError` if the artifact is missing.
* :func:`load_phase2` — list of normalized Phase 2 records, or ``None``
  if the Phase 2 pool artifact is missing. The None return is the
  documented "Phase 2 may not exist for older snapshots" path.
* :func:`load_tracked_evidence` — combined ``{"phase1": ..., "phase2": ...}``
  payload for callers that want both phases in one read.
* :func:`summarize` — per-phase counts and BH pass/fail counts, plus
  the deferred-methodology-lesson count from the rejection log when
  available.
* :func:`summarize_tracked_evidence` — summarize a combined payload
  returned by ``load_tracked_evidence``.

Normalized record shape
-----------------------

Every record returned by the loaders has the same keys::

    {
      "phase":            "phase1" | "phase2",
      "candidate_id":     str,
      "primary_ticker":   str,
      "benchmark_ticker": str,
      "event_date":       str,    # ISO YYYY-MM-DD
      "mechanism_family": str,
      "raw_p":            float | None,
      "q_bh":             float | None,
      "passes_bh_at_005": bool,
      "status":           str,
      "caveat":           str,
    }

Asymmetry note: ``status`` is the Phase 1 ``freeze_status`` for Phase 1
rows (e.g. ``freeze_ready_pending_operator_review``) and the Phase 2
``graduation_status`` (falling back to ``graduation_decision``) for
Phase 2 rows (e.g. ``with_caveat``, ``reject``). Callers needing a
homogeneous status taxonomy must build it themselves; the loader
preserves what the underlying artifacts say.

``caveat`` is similarly asymmetric: Phase 1 returns the full operator-
authored ``caveat`` text from the freeze artifact (typically multi-
paragraph). Phase 2 returns the short ``phase2_pool_role_note`` for
failed-G5 rows, or a synthesized ``graduation_status=...,
borderline_gate=...`` string for graduated rows. Callers that need a
uniform length should truncate themselves.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


__all__ = [
    "DEFAULT_PHASE1_PATH",
    "DEFAULT_PHASE2_PATH",
    "DEFAULT_REJECTION_PATH",
    "PHASE1_LABEL",
    "PHASE2_LABEL",
    "RECORD_KEYS",
    "load_phase1",
    "load_phase2",
    "load_tracked_evidence",
    "summarize",
    "summarize_tracked_evidence",
]


_THIS_DIR = Path(__file__).resolve().parent
_SECTION_C_DIR = _THIS_DIR / "evidence_artifacts" / "section_c_v2"


DEFAULT_PHASE1_PATH: str = str(_SECTION_C_DIR / "freeze_candidate_evidence.json")
DEFAULT_PHASE2_PATH: str = str(_SECTION_C_DIR / "phase2_pool_v1.json")
DEFAULT_REJECTION_PATH: str = str(_SECTION_C_DIR / "rejection_log_summary_v1.json")


PHASE1_LABEL: str = "phase1"
PHASE2_LABEL: str = "phase2"


RECORD_KEYS: tuple[str, ...] = (
    "phase",
    "candidate_id",
    "primary_ticker",
    "benchmark_ticker",
    "event_date",
    "mechanism_family",
    "raw_p",
    "q_bh",
    "passes_bh_at_005",
    "status",
    "caveat",
)


_BH_ALPHA: float = 0.05


# ---------------------------------------------------------------------------
# I/O helper
# ---------------------------------------------------------------------------


def _read_json(path: str) -> dict[str, Any]:
    """Read one JSON file and return the parsed top-level object.

    Read-only: opens in ``"r"`` mode and never writes. Raises
    :class:`FileNotFoundError` when the path does not exist, with the
    path included in the message for diagnostic clarity. Raises
    :class:`ValueError` when the artifact root is not a JSON object.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"cohort_evidence: artifact not found at {path!r}"
        )
    with open(p, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(
            f"cohort_evidence: artifact root must be a JSON object, got "
            f"{type(payload).__name__}: {path!r}"
        )
    return payload


def _is_real_number(x: Any) -> bool:
    """Return True iff ``x`` is a real-valued number suitable for q/p.

    Excludes ``bool`` (a subclass of ``int`` in Python) so an accidental
    ``True``/``False`` does not silently coerce to ``1.0``/``0.0``.
    """
    if isinstance(x, bool):
        return False
    return isinstance(x, (int, float))


# ---------------------------------------------------------------------------
# Phase 1 normalization
# ---------------------------------------------------------------------------


def _phase1_event_date(entry: dict[str, Any]) -> str:
    """Pick the canonical Phase 1 event date.

    Prefers ``event_anchor_close`` (the BHAR anchor convention used to
    compute h=1). Falls back to ``announcement_date`` when the anchor
    is absent.
    """
    anchor = entry.get("event_anchor_close")
    if isinstance(anchor, str) and anchor.strip():
        return anchor
    announcement = entry.get("announcement_date")
    if isinstance(announcement, str) and announcement.strip():
        return announcement
    return ""


def _phase1_candidate_id(entry: dict[str, Any]) -> str:
    """Synthesize a stable Phase 1 candidate id.

    The Phase 1 freeze artifact does not carry a per-row
    ``candidate_id`` field; we construct one from the primary ticker
    and the canonical event date so downstream callers have a stable
    join key.
    """
    ticker = str(entry.get("primary_ticker", "")).lower()
    date = _phase1_event_date(entry)
    parts = [p for p in ("phase1", ticker, date) if p]
    return "-".join(parts)


def _normalize_phase1(entry: dict[str, Any]) -> dict[str, Any]:
    """Convert one Phase 1 freeze-cohort entry to the normalized shape.

    Does not mutate the input dict. ``passes_bh_at_005`` is derived
    from ``h1_q_bh`` against the standard 0.05 threshold; the Phase 1
    artifact does not carry an explicit pass flag.
    """
    raw_p = entry.get("h1_p")
    q_bh = entry.get("h1_q_bh")
    passes = _is_real_number(q_bh) and float(q_bh) <= _BH_ALPHA
    return {
        "phase":            PHASE1_LABEL,
        "candidate_id":     _phase1_candidate_id(entry),
        "primary_ticker":   str(entry.get("primary_ticker", "")),
        "benchmark_ticker": str(entry.get("benchmark_ticker", "")),
        "event_date":       _phase1_event_date(entry),
        "mechanism_family": str(entry.get("mechanism_family", "")),
        "raw_p":            float(raw_p) if _is_real_number(raw_p) else None,
        "q_bh":             float(q_bh) if _is_real_number(q_bh) else None,
        "passes_bh_at_005": bool(passes),
        "status":           str(entry.get("freeze_status", "")),
        "caveat":           str(entry.get("caveat", "") or ""),
    }


# ---------------------------------------------------------------------------
# Phase 2 normalization
# ---------------------------------------------------------------------------


def _phase2_status(entry: dict[str, Any]) -> str:
    """Return the Phase 2 status string.

    Prefers ``graduation_status`` (e.g. ``with_caveat``) when present;
    falls back to ``graduation_decision`` (``graduate`` / ``reject`` /
    ``hold``). Returns the empty string only when neither is set.
    """
    status = entry.get("graduation_status")
    if isinstance(status, str) and status.strip():
        return status
    decision = entry.get("graduation_decision")
    if isinstance(decision, str) and decision.strip():
        return decision
    return ""


def _phase2_caveat(entry: dict[str, Any]) -> str:
    """Return the Phase 2 caveat text.

    Prefers the explicit ``phase2_pool_role_note`` (set on failed-G5
    rows). Falls back to a synthesized
    ``graduation_status=..., borderline_gate=...`` summary for
    graduated rows. Returns the empty string when neither is available.
    """
    note = entry.get("phase2_pool_role_note")
    if isinstance(note, str) and note.strip():
        return note
    status = entry.get("graduation_status")
    border = entry.get("borderline_gate")
    if isinstance(status, str) and status.strip():
        if isinstance(border, str) and border.strip():
            return f"graduation_status={status}, borderline_gate={border}"
        return f"graduation_status={status}"
    return ""


def _normalize_phase2(entry: dict[str, Any]) -> dict[str, Any]:
    """Convert one Phase 2 pool entry to the normalized shape.

    Does not mutate the input dict. ``passes_bh_at_005`` is read from
    the artifact's explicit ``passes_bh_at_005`` field (the pool
    computation is the source of truth); if that field is missing or
    not a bool, falls back to the same q_bh <= 0.05 derivation used
    for Phase 1.
    """
    raw_p = entry.get("raw_p")
    q_bh = entry.get("q_bh")
    artifact_pass = entry.get("passes_bh_at_005")
    if isinstance(artifact_pass, bool):
        passes = artifact_pass
    else:
        passes = _is_real_number(q_bh) and float(q_bh) <= _BH_ALPHA
    return {
        "phase":            PHASE2_LABEL,
        "candidate_id":     str(entry.get("candidate_id", "")),
        "primary_ticker":   str(entry.get("primary_ticker", "")),
        "benchmark_ticker": str(entry.get("benchmark_ticker", "")),
        "event_date":       str(entry.get("event_date", "") or ""),
        "mechanism_family": str(entry.get("mechanism_family", "")),
        "raw_p":            float(raw_p) if _is_real_number(raw_p) else None,
        "q_bh":             float(q_bh) if _is_real_number(q_bh) else None,
        "passes_bh_at_005": bool(passes),
        "status":           _phase2_status(entry),
        "caveat":           _phase2_caveat(entry),
    }


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------


def load_phase1(path: str | None = None) -> list[dict[str, Any]]:
    """Load and normalize the Phase 1 freeze-candidate cohort.

    Parameters
    ----------
    path:
        Optional override path to the Phase 1 artifact. When ``None``,
        uses :data:`DEFAULT_PHASE1_PATH`.

    Returns
    -------
    list of normalized record dicts (one per candidate in the
    artifact's ``candidates`` list, preserving input order).

    Raises
    ------
    FileNotFoundError
        The Phase 1 artifact does not exist at the resolved path.
    ValueError
        The artifact is not a JSON object, or it does not contain a
        ``candidates`` list.
    """
    resolved = path if path is not None else DEFAULT_PHASE1_PATH
    payload = _read_json(resolved)
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError(
            f"cohort_evidence: Phase 1 artifact at {resolved!r} has no "
            f"'candidates' list"
        )
    return [
        _normalize_phase1(entry)
        for entry in raw_candidates
        if isinstance(entry, dict)
    ]


def load_phase2(path: str | None = None) -> list[dict[str, Any]] | None:
    """Load and normalize the closed Phase 2 BH/FDR pool.

    Parameters
    ----------
    path:
        Optional override path to the Phase 2 artifact. When ``None``,
        uses :data:`DEFAULT_PHASE2_PATH`.

    Returns
    -------
    list of normalized record dicts when the artifact exists; ``None``
    when the artifact does not exist (Phase 2 may not yet be declared
    in older project snapshots). Callers distinguish "Phase 2 absent"
    from "Phase 2 declared with zero rows" by the None vs ``[]``.

    Raises
    ------
    ValueError
        The artifact exists but is not a JSON object, or it does not
        contain a ``candidates`` list. A missing file is NOT an error.
    """
    resolved = path if path is not None else DEFAULT_PHASE2_PATH
    if not Path(resolved).exists():
        return None
    payload = _read_json(resolved)
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError(
            f"cohort_evidence: Phase 2 artifact at {resolved!r} has no "
            f"'candidates' list"
        )
    return [
        _normalize_phase2(entry)
        for entry in raw_candidates
        if isinstance(entry, dict)
    ]


def load_tracked_evidence(
    *,
    phase1_path: str | None = None,
    phase2_path: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load Phase 1 and Phase 2 evidence as one read-only payload.

    Phase 2 absence is represented as an empty list, matching the
    summary convention that missing Phase 2 has zero rows.
    """
    return {
        PHASE1_LABEL: load_phase1(phase1_path),
        PHASE2_LABEL: load_phase2(phase2_path) or [],
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _deferred_count_from_rejection_log(path: str) -> int | None:
    """Return the deferred-methodology-lesson count from the rejection log.

    Returns ``None`` when the file is missing, when the JSON cannot be
    parsed, or when the expected
    ``summary.decision_counts.deferred_methodology_lesson`` key path
    is absent or non-integer. Read-only.
    """
    if not Path(path).exists():
        return None
    try:
        payload = _read_json(path)
    except (ValueError, json.JSONDecodeError):
        return None
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return None
    counts = summary.get("decision_counts")
    if not isinstance(counts, dict):
        return None
    value = counts.get("deferred_methodology_lesson")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def summarize(
    *,
    phase1_path: str | None = None,
    phase2_path: str | None = None,
    rejection_path: str | None = None,
) -> dict[str, Any]:
    """Return per-phase counts plus BH pass/fail counts.

    Parameters
    ----------
    phase1_path, phase2_path, rejection_path:
        Optional path overrides. ``None`` resolves to the corresponding
        DEFAULT_* constant.

    Returns
    -------
    Dict with the following keys::

        {
          "phase1_count":      int,           # rows in the freeze cohort
          "phase2_count":      int,           # 0 when Phase 2 missing
          "phase2_pass_count": int,           # rows with passes_bh_at_005
          "phase2_fail_count": int,
          "deferred_count":    int | None,    # None when rejection log absent
        }

    Behaviour on missing Phase 2:
        Missing Phase 2 is not an error. ``phase2_count`` /
        ``phase2_pass_count`` / ``phase2_fail_count`` are all ``0``.

    Behaviour on missing rejection log:
        Missing rejection log is not an error. ``deferred_count`` is
        ``None``, distinguishing "no log" from "log with zero
        deferrals" (which would be ``0``).
    """
    phase1 = load_phase1(phase1_path)
    phase2 = load_phase2(phase2_path) or []
    resolved_rej = (
        rejection_path if rejection_path is not None else DEFAULT_REJECTION_PATH
    )
    deferred_count = _deferred_count_from_rejection_log(resolved_rej)
    phase2_pass = sum(1 for r in phase2 if r.get("passes_bh_at_005"))
    phase2_fail = sum(1 for r in phase2 if not r.get("passes_bh_at_005"))
    return {
        "phase1_count":      len(phase1),
        "phase2_count":      len(phase2),
        "phase2_pass_count": phase2_pass,
        "phase2_fail_count": phase2_fail,
        "deferred_count":    deferred_count,
    }


def summarize_tracked_evidence(
    data: dict[str, list[dict[str, Any]]] | None = None,
    *,
    rejection_path: str | None = None,
) -> dict[str, Any]:
    """Summarize a payload from :func:`load_tracked_evidence`.

    When ``data`` is ``None``, loads the default tracked artifacts and
    returns the same result as :func:`summarize`.
    """
    if data is None:
        return summarize(rejection_path=rejection_path)

    phase1 = data.get(PHASE1_LABEL, [])
    phase2 = data.get(PHASE2_LABEL, [])
    resolved_rej = (
        rejection_path if rejection_path is not None else DEFAULT_REJECTION_PATH
    )
    deferred_count = _deferred_count_from_rejection_log(resolved_rej)
    phase2_pass = sum(1 for r in phase2 if r.get("passes_bh_at_005"))
    phase2_fail = sum(1 for r in phase2 if not r.get("passes_bh_at_005"))
    return {
        "phase1_count":      len(phase1),
        "phase2_count":      len(phase2),
        "phase2_pass_count": phase2_pass,
        "phase2_fail_count": phase2_fail,
        "deferred_count":    deferred_count,
    }
