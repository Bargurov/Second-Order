#!/usr/bin/env python3
"""Daily artifact-backed demo card source.

Read-only loader that walks an operator-supplied artifact
directory, parses each ``analyzed_event_artifact_<candidate_id>
.json`` file, and emits a list of Daily demo cards whose
mechanism / ticker fields come verbatim from the artifact body.

The loader pairs with the Daily Section C artifact gate
(:mod:`routes.daily_artifact_gate`).  Where the gate decides
admit-vs-hold, this loader supplies the artifact-backed cards
the gate would admit — with the three operator review fields
(``market_relevance`` / ``inclusion_reason`` / ``operator_notes``)
surfaced through to the operator narrative.

Read-only by construction
-------------------------

* No DB reads, no DB writes.
* No ``yfinance``, ``market_data``, ``price_cache.fetch_*``, LLM,
  or paid provider call.  No network access.
* No FastAPI surface — never imports ``api`` or ``routes``.
* The loader never opens any artifact for writes; it never
  removes or renames a file.  The supplied artifact directory is
  walked read-only.
* The loader never opens the headlines inbox file.  Its only
  filesystem source is the caller-supplied artifact directory.
* When ``--artifact-dir`` is not supplied, the loader does not
  default to the real ``artifacts/`` directory and never treats
  a fixture/temp directory as a real source — it surfaces a
  warning and an empty ``cards`` list.
* The loader never invents a field.  Optional review fields
  default to ``""`` when the artifact body omits them; required
  fields' absence forces the artifact into ``skipped_artifacts``
  with a clear reason.

Output contract (JSON)::

    {
      "ok":                bool,
      "cards":             [
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
          "source":           "analyzed_event_artifact",
        }, ...
      ],
      "skipped_artifacts": [
        {"path": str, "reason": str}, ...
      ],
      "warnings":          [str, ...],
      "errors":            [str, ...],
    }

The envelope carries EXACTLY these 5 keys.

Conservative wording
--------------------

The loader surfaces a row as an "artifact-backed demo card"; it
never claims the card is a trading signal, a reviewed
recommendation, or fit for inclusion in any cohort beyond the
operator's own demo narrative.  Banned tokens (``proof``,
``proven``, ``guaranteed``, ``automatically``, ``validated``,
``alpha generated``, ``correct ticker``, ``definitely``,
``approved``, ``production ready``, ``demo_ready``) never appear
in any text or JSON the loader emits.

Usage::

    python scripts/daily_artifact_backed_card_source.py
    python scripts/daily_artifact_backed_card_source.py --json \\
        --artifact-dir artifacts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
# Two card-content fields a Daily card cannot be rendered without.
_REQUIRED_CARD_FIELDS: tuple[str, ...] = (
    "headline",
    "event_date",
)
# Operator review fields — surfaced verbatim when present, "" when
# absent.  Never inferred.
_OPTIONAL_REVIEW_FIELDS: tuple[str, ...] = (
    "market_relevance",
    "inclusion_reason",
    "operator_notes",
)

_SOURCE_LITERAL: str = "analyzed_event_artifact"


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_daily_artifact_backed_cards(
    *,
    artifact_dir: str | Path | None,
) -> dict[str, Any]:
    """Walk ``artifact_dir`` and emit the 5-key envelope.

    The loader does not default to any directory: when
    ``artifact_dir`` is ``None`` the envelope returns an empty
    ``cards`` list with a warning so a fixture or a stale temp
    path never silently enters the demo.
    """
    errors:   list[str] = []
    warnings: list[str] = []
    cards:    list[dict[str, Any]] = []
    skipped:  list[dict[str, str]] = []

    if artifact_dir is None:
        warnings.append(
            "no --artifact-dir supplied; the loader does not default "
            "to the real artifacts directory — supply --artifact-dir "
            "explicitly to load any cards"
        )
        return _envelope(
            ok=True, cards=cards, skipped=skipped,
            warnings=warnings, errors=errors,
        )

    d = Path(artifact_dir)
    if not d.is_dir():
        errors.append(
            f"--artifact-dir does not exist or is not a directory: {d}"
        )
        return _envelope(
            ok=False, cards=cards, skipped=skipped,
            warnings=warnings, errors=errors,
        )

    for path in sorted(d.glob(_FILENAME_GLOB)):
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

        cards.append(_build_card(candidate_id=candidate_id, doc=doc))

    cards.sort(key=lambda c: (c["event_date"], c["candidate_id"]))

    return _envelope(
        ok=not errors, cards=cards, skipped=skipped,
        warnings=warnings, errors=errors,
    )


def _envelope(
    *,
    ok:       bool,
    cards:    list[dict[str, Any]],
    skipped:  list[dict[str, str]],
    warnings: list[str],
    errors:   list[str],
) -> dict[str, Any]:
    return {
        "ok":                ok,
        "cards":             cards,
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
    """Read ``path`` and return ``(doc, err)``.  ``err`` is a
    one-line operator-readable reason on failure; ``doc`` is an
    empty dict on failure.  Read-only.
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
    for field in _REQUIRED_CARD_FIELDS:
        v = doc.get(field)
        if not isinstance(v, str) or not v.strip():
            missing.append(field)
    return missing


def _build_card(
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
        "source":           _SOURCE_LITERAL,
    }


def _str_or_blank(value: Any) -> str:
    return value if isinstance(value, str) else ""


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_card(card: dict[str, Any]) -> str:
    return (
        f"{card['event_date']} {card['candidate_id']} "
        f"[mechanism_family={card['mechanism_family']}, "
        f"primary_ticker={card['primary_ticker']}, "
        f"benchmark_ticker={card['benchmark_ticker']}] "
        f"{card['headline']}"
    )


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Daily artifact-backed card source", ""]
    lines.append(f"OK:    {report['ok']}")
    lines.append(f"Cards: {len(report['cards'])}")
    for card in report["cards"]:
        lines.append(f"  - {_fmt_card(card)}")
    lines.append(f"Skipped artifacts: {len(report['skipped_artifacts'])}")
    for entry in report["skipped_artifacts"]:
        lines.append(
            f"  - {entry.get('path', '')} :: {entry.get('reason', '')}"
        )
    if report.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    if report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in report["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Daily artifact-backed demo card source.  "
            "Walks a caller-supplied artifact directory, parses "
            "each analyzed_event_artifact_<candidate_id>.json file, "
            "and emits Daily demo cards whose mechanism / ticker "
            "fields come verbatim from the artifact body.  Skips "
            "invalid artifacts with a clear reason; never invents "
            "a field.  Without --artifact-dir the loader returns an "
            "empty card list with a warning so a fixture or stale "
            "temp path never silently enters the demo."
        ),
    )
    parser.add_argument(
        "--artifact-dir", dest="artifact_dir", default=None,
        help=(
            "Directory of analyzed_event_artifact_<cid>.json files. "
            "Required to load any cards; the loader does not default "
            "to the real artifacts directory."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text view.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_daily_artifact_backed_cards(
        artifact_dir=args.artifact_dir,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "build_daily_artifact_backed_cards",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
