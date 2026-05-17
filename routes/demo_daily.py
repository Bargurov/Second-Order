"""Demo Daily Market source.

Read-only demo source that walks an operator-supplied artifact
directory, parses each ``analyzed_event_artifact_<candidate_id>
.json`` file, and emits a list of Daily demo items whose
mechanism / ticker fields come verbatim from the artifact body.

The module pairs with the Daily Section C artifact gate
(:mod:`routes.daily_artifact_gate`).  Where the gate decides
admit-vs-hold for live mover cards, this source supplies the
artifact-backed items the gate would admit — with the three
operator review fields (``market_relevance`` / ``inclusion_reason``
/ ``operator_notes``) surfaced verbatim from the artifact body.

The module is NOT registered in ``api.py``.  It is a pure-Python
source other callers (an operator script, a future demo route)
can import.

Read-only by construction
-------------------------

* No DB reads or writes at module load.  No DB call from
  :func:`build_demo_daily_market`.
* No ``yfinance``, ``market_data``, ``price_cache.fetch_*``, LLM,
  or paid provider call.  No network access.
* No FastAPI surface is imported at module load.
* No mutation of the events DB, the headlines inbox file, the
  news cache, or the artifact directory.  The supplied artifact
  directory is walked read-only.
* The source never opens any artifact for writes; it never
  removes or renames a file.
* The source never reads the headlines inbox file.  Its only
  filesystem source is the caller-supplied artifact directory.
* When ``artifact_dir`` is not supplied, the source does not
  default to the real ``artifacts/`` directory and never treats a
  fixture/temp directory as a real source — it surfaces a warning
  and an empty ``items`` list.
* The source never invents a field.  Optional review fields
  default to ``""`` when the artifact body omits them; required
  fields' absence forces the artifact into ``skipped_artifacts``
  with a clear reason.

Output contract::

    {
      "ok":                bool,
      "section":           "daily",
      "items":             [item, ...],
      "count":             int,
      "skipped_artifacts": [{"path": str, "reason": str}, ...],
      "warnings":          [str, ...],
      "errors":            [str, ...],
    }

Each item carries::

    {
      "candidate_id":     str,
      "headline":         str,
      "event_date":       str,
      "mechanism_family": str,
      "primary_ticker":   str,
      "benchmark_ticker": str,
      "market_relevance": str,
      "inclusion_reason": str,
      "operator_notes":   str,
      "caution_label":    str,
    }

Conservative wording — every item carries a ``caution_label``
marking it as a demo row that requires operator review before it
can be relied on.  The source never claims a card is proven,
validated, fit to trade, or production-ready.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SECTION_NAME: str = "daily"

# Uniform label attached to every demo item so downstream consumers
# can never confuse a demo row with a production-graded one.
CAUTION_LABEL: str = (
    "demo Daily Market source; operator review required before use"
)

_FILENAME_PREFIX: str = "analyzed_event_artifact_"
_FILENAME_SUFFIX: str = ".json"
_FILENAME_GLOB:   str = f"{_FILENAME_PREFIX}*{_FILENAME_SUFFIX}"
_NONE_SENTINEL:   str = "none"

# Three artifact-backed fields the gate enforces.
_REQUIRED_GATE_FIELDS: tuple[str, ...] = (
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
)
# Two card-content fields a Daily item cannot be rendered without.
_REQUIRED_ITEM_FIELDS: tuple[str, ...] = (
    "headline",
    "event_date",
)
# Operator review fields — surfaced verbatim when present, ``""`` when
# absent.  Never inferred.
_OPTIONAL_REVIEW_FIELDS: tuple[str, ...] = (
    "market_relevance",
    "inclusion_reason",
    "operator_notes",
)


def build_demo_daily_market(
    *,
    artifact_dir: str | Path | None,
) -> dict[str, Any]:
    """Walk ``artifact_dir`` and return the demo Daily envelope.

    The source does not default to any directory: when
    ``artifact_dir`` is ``None`` the envelope returns an empty
    ``items`` list with a warning so a fixture or stale temp path
    never silently enters the demo.
    """
    errors:   list[str] = []
    warnings: list[str] = []
    items:    list[dict[str, Any]] = []
    skipped:  list[dict[str, str]] = []

    if artifact_dir is None:
        warnings.append(
            "no artifact_dir supplied; the demo Daily Market source "
            "does not default to the real artifacts/ directory — "
            "supply artifact_dir explicitly to load any items"
        )
        return _envelope(
            ok=True, items=items, skipped=skipped,
            warnings=warnings, errors=errors,
        )

    d = Path(artifact_dir)
    if not d.is_dir():
        errors.append(
            f"artifact_dir does not exist or is not a directory: {d}"
        )
        return _envelope(
            ok=False, items=items, skipped=skipped,
            warnings=warnings, errors=errors,
        )

    files = sorted(d.glob(_FILENAME_GLOB))
    if not files:
        warnings.append(
            f"no analyzed_event_artifact_*.json files found under "
            f"artifact_dir: {d}"
        )

    for path in files:
        candidate_id = _candidate_id_from_path(path)
        if not candidate_id:
            skipped.append({
                "path":   str(path),
                "reason": "filename has no candidate_id segment",
            })
            continue

        doc, read_err = _read_artifact_doc(path)
        if read_err is not None:
            skipped.append({"path": str(path), "reason": read_err})
            continue

        missing = _missing_required_fields(doc)
        if missing:
            skipped.append({
                "path":   str(path),
                "reason": (
                    f"missing or invalid required field(s): "
                    f"{', '.join(missing)}"
                ),
            })
            continue

        items.append(_build_item(candidate_id=candidate_id, doc=doc))

    items.sort(key=lambda it: (it["event_date"], it["candidate_id"]))

    return _envelope(
        ok=not errors, items=items, skipped=skipped,
        warnings=warnings, errors=errors,
    )


def _envelope(
    *,
    ok:       bool,
    items:    list[dict[str, Any]],
    skipped:  list[dict[str, str]],
    warnings: list[str],
    errors:   list[str],
) -> dict[str, Any]:
    return {
        "ok":                ok,
        "section":           SECTION_NAME,
        "items":             items,
        "count":             len(items),
        "skipped_artifacts": skipped,
        "warnings":          warnings,
        "errors":            errors,
    }


def _candidate_id_from_path(path: Path) -> str:
    name = path.name
    if not name.startswith(_FILENAME_PREFIX) or not name.endswith(
        _FILENAME_SUFFIX,
    ):
        return ""
    middle = name[len(_FILENAME_PREFIX): -len(_FILENAME_SUFFIX)]
    return middle.strip()


def _read_artifact_doc(
    path: Path,
) -> tuple[dict[str, Any], str | None]:
    """Read ``path`` and return ``(doc, err)``.

    ``err`` is a one-line operator-readable reason on failure;
    ``doc`` is an empty dict on failure.  Read-only.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return {}, f"read failed: {e}"
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        return {}, f"invalid json: {e}"
    if not isinstance(doc, dict):
        return {}, "artifact root is not a json object"
    return doc, None


def _missing_required_fields(doc: dict[str, Any]) -> list[str]:
    """Return the list of required field names that are missing,
    blank, or set to the ``"none"`` sentinel.  Order matches the
    spec so the operator-facing reason is deterministic.
    """
    missing: list[str] = []
    for field in _REQUIRED_GATE_FIELDS:
        v = doc.get(field)
        if not isinstance(v, str) or not v.strip():
            missing.append(field)
            continue
        if (
            field == "mechanism_family"
            and v.strip().lower() == _NONE_SENTINEL
        ):
            missing.append(field)
    for field in _REQUIRED_ITEM_FIELDS:
        v = doc.get(field)
        if not isinstance(v, str) or not v.strip():
            missing.append(field)
    return missing


def _build_item(
    *, candidate_id: str, doc: dict[str, Any],
) -> dict[str, Any]:
    return {
        "candidate_id":     candidate_id,
        "headline":         doc["headline"],
        "event_date":       doc["event_date"],
        "mechanism_family": doc["mechanism_family"],
        "primary_ticker":   doc["primary_ticker"],
        "benchmark_ticker": doc["benchmark_ticker"],
        "market_relevance": _str_or_blank(doc.get("market_relevance")),
        "inclusion_reason": _str_or_blank(doc.get("inclusion_reason")),
        "operator_notes":   _str_or_blank(doc.get("operator_notes")),
        "caution_label":    CAUTION_LABEL,
    }


def _str_or_blank(value: Any) -> str:
    return value if isinstance(value, str) else ""


__all__ = (
    "SECTION_NAME",
    "CAUTION_LABEL",
    "build_demo_daily_market",
)
