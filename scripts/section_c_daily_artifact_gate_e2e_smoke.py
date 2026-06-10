#!/usr/bin/env python3
"""Section C Daily artifact-gate end-to-end smoke.

Proves the full read-only workflow that connects the inbox candidate_id
contract to the Daily Section C gate decision:

  1. ``news_fetch._make_record`` produces a deterministic
     ``candidate_id`` on a fake inbox row.
  2. ``scripts.manual_event_intake_worksheet.build_manual_event_intake_worksheet``
     emits ``analyzed_event_artifact_<candidate_id>.json`` for a
     filled worksheet row whose ``candidate_id`` matches the inbox
     row.
  3. ``scripts.section_c_daily_quality_diagnostic.run_section_c_daily_quality_diagnostic``
     with ``--artifact-dir`` reports ``artifact_present`` /
     ``artifact_fields_complete`` per row.
  4. ``routes.daily_artifact_gate.filter_daily_section_c_cards``
     admits a card whose artifact carries every required field and
     holds cards whose artifact is missing or incomplete.

Read-only by construction
-------------------------

* Every file the smoke writes lives under a single
  :class:`tempfile.TemporaryDirectory` that is destroyed when the
  smoke exits.  The live ``artifacts/``, ``events.db``,
  ``price_cache``, ``backups/``, ``evidence_artifacts/``, ``frontend/``,
  and operator-note paths are never opened for writing.
* No provider call, no LLM call, no FastAPI surface (the gate module
  imports stdlib only at module load — see its docstring).
* No DB read or write.  ``news_fetch._make_record`` is pure-Python;
  the diagnostic loads only the temp inbox JSON; the gate reads only
  the temp artifact JSON files.

Output contract (JSON)::

    {
      "ok":                                  bool,
      "temp_only":                           true,
      "candidate_id":                        str,    # complete-scenario id
      "emitted_artifact_count":              int,    # number of artifacts written
      "diagnostic_artifact_present":         bool,   # complete-scenario row
      "diagnostic_artifact_fields_complete": bool,   # complete-scenario row
      "gate_admitted_count":                 int,    # filter_daily_section_c_cards
      "gate_held_count":                     int,    # filter_daily_section_c_cards
      "gate_id":                             str,
      "scenarios": [
        {
          "name":                                    str,
          "candidate_id":                            str,
          "diagnostic_artifact_present":             bool | null,
          "diagnostic_artifact_fields_complete":     bool | null,
          "diagnostic_artifact_missing_reason":      str | null,
          "diagnostic_artifact_incomplete_fields":   [str, ...] | null,
          "gate_admitted":                           bool,
          "expected_admit":                          bool,
          "ok":                                      bool,
        },
        ...
      ],
      "errors":                              [str, ...],
    }

Usage::

    python scripts/section_c_daily_artifact_gate_e2e_smoke.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_SMOKE_GENERATED_AT_DEFAULT: str = "2026-05-24T00:00:00Z"

# Headlines were picked so each clears ``news_relevance.is_relevant``
# (sanctions / oil / tariff / semiconductor terms) and so the three
# scenarios land in distinct rows under ``_dedup_key`` /
# ``_normalised_for_duplicate_check``.  Headlines never change; only
# the (source, url, published_at) tuple drives the deterministic
# ``candidate_id`` derived by ``news_fetch._candidate_id``.
_SCENARIO_INPUTS: tuple[dict[str, str], ...] = (
    {
        "name":          "complete",
        "title":         "OPEC members agree to extend voluntary oil output cuts through next quarter",
        "published_at": "2026-04-01T10:00:00",
        "url":           "https://test.example.com/smoke/a",
        "event_date":    "2026-04-01",
        "mechanism_family": "supply_shock",
        "primary_ticker":  "XOM",
        "benchmark_ticker": "XLE",
    },
    {
        "name":          "missing_artifact",
        "title":         "OFAC announces sanctions targeting Russian aluminum producer",
        "published_at": "2026-04-02T10:00:00",
        "url":           "https://test.example.com/smoke/b",
        "event_date":    "2026-04-02",
        "mechanism_family": "sanctions_or_forced_divestiture",
        "primary_ticker":  "AA",
        "benchmark_ticker": "XME",
    },
    {
        "name":          "incomplete_artifact",
        "title":         "USTR announces new tariff investigation on semiconductor imports",
        "published_at": "2026-04-03T10:00:00",
        "url":           "https://test.example.com/smoke/c",
        "event_date":    "2026-04-03",
        "mechanism_family": "tariffs_industrial_policy",
        # primary_ticker intentionally omitted for the incomplete row
        "benchmark_ticker": "XLI",
    },
)


def run_section_c_daily_artifact_gate_e2e_smoke(
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Run the four-stage end-to-end smoke and return a verdict envelope.

    See module docstring for the full output contract.  The smoke
    never touches the live filesystem outside a single ``TemporaryDirectory``.
    """
    errors: list[str] = []

    # Lazy imports so any one of these failing surfaces a single
    # error string rather than a hard crash at module-import time.
    try:
        from news_fetch import _make_record  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return _failure_envelope(
            f"failed to import news_fetch._make_record: {exc!r}",
        )
    try:
        from scripts.manual_event_intake_worksheet import (  # noqa: PLC0415
            build_manual_event_intake_worksheet,
        )
    except Exception as exc:  # noqa: BLE001
        return _failure_envelope(
            f"failed to import manual_event_intake_worksheet: {exc!r}",
        )
    try:
        from scripts.section_c_daily_quality_diagnostic import (  # noqa: PLC0415
            run_section_c_daily_quality_diagnostic,
        )
    except Exception as exc:  # noqa: BLE001
        return _failure_envelope(
            f"failed to import section_c_daily_quality_diagnostic: {exc!r}",
        )
    try:
        from routes.daily_artifact_gate import (  # noqa: PLC0415
            filter_daily_section_c_cards,
            GATE_ID,
        )
    except Exception as exc:  # noqa: BLE001
        return _failure_envelope(
            f"failed to import routes.daily_artifact_gate: {exc!r}",
        )

    generated_at_iso = generated_at or _SMOKE_GENERATED_AT_DEFAULT

    with tempfile.TemporaryDirectory() as tmp_root:
        tmp_root_p = Path(tmp_root)
        inbox_path = tmp_root_p / "smoke_inbox.json"
        artifact_dir = tmp_root_p / "smoke_artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # --- Stage 1: synthesize three inbox rows with deterministic ids ---
        inbox_rows: list[dict[str, Any]] = []
        scenario_meta: list[dict[str, Any]] = []
        for scen in _SCENARIO_INPUTS:
            rec = _make_record(
                source="local",
                title=scen["title"],
                published_at=scen["published_at"],
                url=scen["url"],
            )
            inbox_rows.append(rec)
            scenario_meta.append({
                "name":         scen["name"],
                "candidate_id": rec["candidate_id"],
                "spec":         scen,
            })

        cid_complete   = scenario_meta[0]["candidate_id"]
        cid_missing    = scenario_meta[1]["candidate_id"]
        cid_incomplete = scenario_meta[2]["candidate_id"]

        inbox_path.write_text(
            json.dumps(inbox_rows, indent=2),
            encoding="utf-8",
        )

        # --- Stage 2: emit artifacts for the complete + incomplete rows ---
        # Build a worksheet over two filled rows and ask the intake
        # worksheet to emit per-row artifacts.  The "missing" scenario
        # row is intentionally absent from the worksheet so no file
        # lands on disk for its candidate_id.
        worksheet_rows = [
            {
                "candidate_id":     cid_complete,
                "event_date":       _SCENARIO_INPUTS[0]["event_date"],
                "headline":         _SCENARIO_INPUTS[0]["title"],
                "mechanism_family": _SCENARIO_INPUTS[0]["mechanism_family"],
                "primary_ticker":   _SCENARIO_INPUTS[0]["primary_ticker"],
                "benchmark_ticker": _SCENARIO_INPUTS[0]["benchmark_ticker"],
            },
            {
                "candidate_id":     cid_incomplete,
                "event_date":       _SCENARIO_INPUTS[2]["event_date"],
                "headline":         _SCENARIO_INPUTS[2]["title"],
                "mechanism_family": _SCENARIO_INPUTS[2]["mechanism_family"],
                # primary_ticker intentionally absent
                "benchmark_ticker": _SCENARIO_INPUTS[2]["benchmark_ticker"],
            },
        ]
        emit_report = build_manual_event_intake_worksheet(
            worksheet_rows=worksheet_rows,
            emit_artifacts=True,
            output_dir=str(artifact_dir),
            generated_at=generated_at_iso,
        )
        emitted_artifacts = emit_report.get("emitted_artifacts") or []
        emitted_count = len(emitted_artifacts)
        if emitted_count != 2:
            errors.append(
                f"expected 2 emitted artifacts (complete + incomplete), "
                f"got {emitted_count}: {emitted_artifacts!r}"
            )

        # --- Stage 3: run the read-only quality diagnostic ---
        diag = run_section_c_daily_quality_diagnostic(
            input_path=str(inbox_path),
            artifact_dir=str(artifact_dir),
        )
        diag_by_cid = _index_by_candidate_id(diag)

        diag_complete   = diag_by_cid.get(cid_complete, {})
        diag_missing    = diag_by_cid.get(cid_missing, {})
        diag_incomplete = diag_by_cid.get(cid_incomplete, {})

        # --- Stage 4: apply the gate to three minimal cards ---
        cards = [
            {"candidate_id": cid_complete,   "headline": _SCENARIO_INPUTS[0]["title"]},
            {"candidate_id": cid_missing,    "headline": _SCENARIO_INPUTS[1]["title"]},
            {"candidate_id": cid_incomplete, "headline": _SCENARIO_INPUTS[2]["title"]},
        ]
        admitted, gate_meta = filter_daily_section_c_cards(
            cards, artifact_dir=artifact_dir,
        )
        admitted_ids = {c.get("candidate_id") for c in admitted}

        # --- Compose per-scenario verdicts ---
        scenarios: list[dict[str, Any]] = []
        for meta, diag_row, expected_admit in (
            (scenario_meta[0], diag_complete,   True),
            (scenario_meta[1], diag_missing,    False),
            (scenario_meta[2], diag_incomplete, False),
        ):
            cid = meta["candidate_id"]
            gate_admitted = cid in admitted_ids
            scen_errors: list[str] = []
            if gate_admitted != expected_admit:
                scen_errors.append(
                    f"gate verdict mismatch: gate_admitted="
                    f"{gate_admitted} expected_admit={expected_admit}",
                )
            scenarios.append({
                "name":          meta["name"],
                "candidate_id":  cid,
                "diagnostic_artifact_present":
                    diag_row.get("artifact_present"),
                "diagnostic_artifact_fields_complete":
                    diag_row.get("artifact_fields_complete"),
                "diagnostic_artifact_missing_reason":
                    diag_row.get("artifact_missing_reason"),
                "diagnostic_artifact_incomplete_fields":
                    diag_row.get("artifact_incomplete_fields"),
                "gate_admitted":   gate_admitted,
                "expected_admit":  expected_admit,
                "ok":              not scen_errors,
            })
            errors.extend(
                f"scenario {meta['name']!r}: {e}" for e in scen_errors
            )

        # --- Cross-stage invariants the smoke explicitly pins ---
        if diag_complete.get("artifact_present") is not True:
            errors.append(
                "complete scenario: diagnostic_artifact_present "
                f"!= True (got {diag_complete.get('artifact_present')!r})"
            )
        if diag_complete.get("artifact_fields_complete") is not True:
            errors.append(
                "complete scenario: diagnostic_artifact_fields_complete "
                f"!= True (got {diag_complete.get('artifact_fields_complete')!r})"
            )
        if diag_missing.get("artifact_present") is not False:
            errors.append(
                "missing scenario: diagnostic_artifact_present should "
                "be False when no artifact file is on disk"
            )
        incomplete_fields = diag_incomplete.get("artifact_incomplete_fields") or []
        if "primary_ticker" not in incomplete_fields:
            errors.append(
                "incomplete scenario: 'primary_ticker' not in "
                f"artifact_incomplete_fields (got {incomplete_fields!r})"
            )
        if diag_incomplete.get("artifact_present") is not True:
            errors.append(
                "incomplete scenario: diagnostic_artifact_present "
                "should be True (file exists, just missing a field)"
            )

        envelope: dict[str, Any] = {
            "ok":                                  not errors,
            "temp_only":                           True,
            "candidate_id":                        cid_complete,
            "emitted_artifact_count":              emitted_count,
            "diagnostic_artifact_present":
                diag_complete.get("artifact_present"),
            "diagnostic_artifact_fields_complete":
                diag_complete.get("artifact_fields_complete"),
            "gate_admitted_count":                 gate_meta.get("admitted_count"),
            "gate_held_count":                     gate_meta.get("held_for_review_count"),
            "gate_id":                             gate_meta.get("gate_id") or GATE_ID,
            "scenarios":                           scenarios,
            "errors":                              errors,
        }

    # The TemporaryDirectory is destroyed on context exit; no file the
    # smoke wrote survives this point.
    return envelope


def _index_by_candidate_id(diag: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten every category list in the diagnostic envelope and key
    by ``candidate_id``.  Rows without a ``candidate_id`` are dropped.
    """
    out: dict[str, dict[str, Any]] = {}
    for key in (
        "accepted_like_candidates",
        "junk_headlines",
        "raw_legal_text_cases",
        "off_topic_cases",
        "vague_cases",
        "duplicate_cases",
        "missing_mechanism_cases",
    ):
        for cand in diag.get(key) or []:
            if not isinstance(cand, dict):
                continue
            cid = cand.get("candidate_id")
            if isinstance(cid, str) and cid:
                out[cid] = cand
    return out


def _failure_envelope(reason: str) -> dict[str, Any]:
    """Return a fully-shaped envelope describing an early-abort failure."""
    return {
        "ok":                                  False,
        "temp_only":                           True,
        "candidate_id":                        "",
        "emitted_artifact_count":              0,
        "diagnostic_artifact_present":         None,
        "diagnostic_artifact_fields_complete": None,
        "gate_admitted_count":                 0,
        "gate_held_count":                     0,
        "gate_id":                             "",
        "scenarios":                           [],
        "errors":                              [reason],
    }


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only, tempdir-only end-to-end smoke of the Section "
            "C Daily artifact-gate workflow.  Synthesizes a fake "
            "inbox row, emits the matching analyzed_event_artifact "
            "file via the manual intake worksheet, runs the daily "
            "quality diagnostic against the temp artifact dir, and "
            "applies the daily artifact gate.  No DB, no provider, "
            "no LLM, no live filesystem write."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help=(
            "Accepted for ergonomic parity with sibling smoke "
            "scripts.  Output is always JSON."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    _ = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_section_c_daily_artifact_gate_e2e_smoke()
    print(
        json.dumps(report, indent=2, sort_keys=True, default=str),
        file=output,
    )
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_daily_artifact_gate_e2e_smoke",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
