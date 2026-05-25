"""Tests for ``scripts/demo_readiness_blocker_inspection.py``.

The inspection wraps the Section C demo-readiness checklist and
reorganises its verdicts into a blocker / solved / partial narrative.
It must never re-derive a verdict, never claim demo readiness, and
never run a DB / provider / LLM / FastAPI surface.

Pin the contract:

* Read-only.  No DB writes; no ``yfinance``, ``market_data``, LLM,
  paid provider, or FastAPI surface imported at module load.
* Output dict has EXACTLY these 11 keys::

    ok, readiness_status, blockers, solved_items, partial_items,
    next_required_actions, not_required_yet, comparison_available,
    recommended_next_implementation_target, warnings, errors

* Conservative wording — banned tokens absent from every rendered
  output.
* When the checklist says daily_mechanism_family_enrichment_resolved
  is blocked, the inspection surfaces it as a blocker with a
  non-empty explanation.
* When the checklist says weekly canonicalization or the sector-ETF
  gate is solved, the inspection lands those items in solved_items.
* When the freeze artifact reports
  ``benchmark_sensitivity_status.status == 'comparison_available'``,
  the inspection surfaces ``comparison_available == True``.
* The inspection recommends the next implementation target without
  applying it (the recommended string is informational).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import demo_readiness_blocker_inspection as cli  # noqa: E402


_REQUIRED_TOP_KEYS = (
    "ok",
    "readiness_status",
    "blockers",
    "solved_items",
    "partial_items",
    "next_required_actions",
    "not_required_yet",
    "comparison_available",
    "recommended_next_implementation_target",
    "warnings",
    "errors",
)


_ITEM_KEYS = (
    "check_id",
    "status",
    "explanation",
    "evidence",
    "next_action",
)


_VALID_READINESS_VALUES = (
    "blocked",
    "required_checks_pending",
    "required_checks_passed",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "guaranteed",
    "automatically",
    "validated",
    "alpha generated",
    "correct ticker",
    "definitely",
    "approved",
    "production ready",
    "production-ready",
    "demo_ready",
    "demo-ready",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _checklist_envelope(
    *,
    readiness:        str = "required_checks_pending",
    ok:               bool = True,
    passed_ids:       tuple[str, ...] = (
        "weekly_duplicate_canonicalization_landed",
        "still_moving_sector_etf_primary_gate_landed",
        "freeze_candidate_evidence_artifact_validates",
        "benchmark_sensitivity_event_60_honest_representation",
    ),
    partial_ids:      tuple[str, ...] = ("no_paid_smoke_available",),
    blocker_ids:      tuple[str, ...] = (),
    required_actions: tuple[str, ...] = (
        "run `python scripts/no_paid_smoke.py --json` separately before demo",
    ),
    optional_actions: tuple[str, ...] = (),
    warnings:         tuple[str, ...] = (),
    errors:           tuple[str, ...] = (),
) -> dict[str, Any]:
    """Fabricate a checklist envelope so the inspection has a
    deterministic input to reorganise.
    """
    def _mk(check_id: str, status: str) -> dict[str, Any]:
        return {
            "check_id":    check_id,
            "description": f"description for {check_id}",
            "required":    True,
            "status":      status,
            "evidence":    [f"evidence for {check_id}"],
            "next_action": (
                f"next action for {check_id}" if status != "passed" else ""
            ),
        }
    return {
        "ok":                   ok,
        "readiness_status":     readiness,
        "blockers":             [_mk(c, "blocked") for c in blocker_ids],
        "passed_checks":        [_mk(c, "passed")  for c in passed_ids],
        "partial_checks":       [_mk(c, "partial") for c in partial_ids],
        "required_before_demo": list(required_actions),
        "optional_before_demo": list(optional_actions),
        "warnings":             list(warnings),
        "errors":               list(errors),
    }


def _patch_checklist(payload: dict[str, Any]):
    return patch.object(
        cli, "_run_demo_readiness_checklist",
        return_value=payload,
    )


def _write_freeze_artifact(
    dest: Path,
    *,
    status: str = "comparison_available",
) -> Path:
    artifact = {
        "artifact_type": "freeze_candidate_evidence",
        "benchmark_sensitivity_status": {
            "status": status,
            "changed_event_ids": [60],
            "changed_interpretation_count": 1,
        },
        "records":     [],
        "limitations": [],
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(artifact), encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_required_keys_on_clean_input(self) -> None:
        payload = _checklist_envelope()
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertIn(report["readiness_status"], _VALID_READINESS_VALUES)

    def test_every_item_has_required_fields(self) -> None:
        payload = _checklist_envelope(
            blocker_ids=("daily_mechanism_family_enrichment_resolved",),
            readiness="blocked",
            ok=False,
        )
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        all_items = (
            report["blockers"]
            + report["solved_items"]
            + report["partial_items"]
        )
        for item in all_items:
            self.assertEqual(set(item.keys()), set(_ITEM_KEYS),
                             f"item drift: {item.get('check_id')}")

    def test_checklist_exception_is_surfaced_as_error(self) -> None:
        with patch.object(
            cli, "_run_demo_readiness_checklist",
            side_effect=RuntimeError("boom"),
        ):
            report = cli.run_demo_readiness_blocker_inspection()
        self.assertFalse(report["ok"])
        self.assertEqual(report["readiness_status"], "blocked")
        joined = " | ".join(report["errors"]).lower()
        self.assertIn("checklist", joined)


# ---------------------------------------------------------------------------
# Blocker / solved / partial reshape
# ---------------------------------------------------------------------------


class TestReshape(unittest.TestCase):
    def test_daily_enrich_blocker_is_explained(self) -> None:
        payload = _checklist_envelope(
            blocker_ids=("daily_mechanism_family_enrichment_resolved",),
            readiness="blocked",
            ok=False,
        )
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        ids = {b["check_id"] for b in report["blockers"]}
        self.assertIn(
            "daily_mechanism_family_enrichment_resolved", ids,
        )
        item = next(
            b for b in report["blockers"]
            if b["check_id"] == "daily_mechanism_family_enrichment_resolved"
        )
        self.assertEqual(item["status"], "blocked")
        # Explanation must be non-empty and mention the gate.
        self.assertTrue(item["explanation"])
        self.assertIn("section c", item["explanation"].lower())

    def test_weekly_solved_lands_in_solved_items(self) -> None:
        payload = _checklist_envelope()
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        ids = {s["check_id"] for s in report["solved_items"]}
        self.assertIn(
            "weekly_duplicate_canonicalization_landed", ids,
        )

    def test_sector_etf_solved_lands_in_solved_items(self) -> None:
        payload = _checklist_envelope()
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        ids = {s["check_id"] for s in report["solved_items"]}
        self.assertIn(
            "still_moving_sector_etf_primary_gate_landed", ids,
        )

    def test_no_paid_smoke_partial_lands_in_partial_items(self) -> None:
        payload = _checklist_envelope()
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        ids = {p["check_id"] for p in report["partial_items"]}
        self.assertIn("no_paid_smoke_available", ids)

    def test_next_required_actions_passthrough(self) -> None:
        payload = _checklist_envelope(
            required_actions=(
                "wire the artifact gate before demo",
                "run no-paid smoke before demo",
            ),
        )
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        self.assertEqual(
            report["next_required_actions"],
            [
                "wire the artifact gate before demo",
                "run no-paid smoke before demo",
            ],
        )

    def test_not_required_yet_passthrough(self) -> None:
        payload = _checklist_envelope(
            optional_actions=("optional follow-up x",),
        )
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        self.assertEqual(
            report["not_required_yet"], ["optional follow-up x"],
        )


# ---------------------------------------------------------------------------
# comparison_available signal
# ---------------------------------------------------------------------------


class TestComparisonAvailableSignal(unittest.TestCase):
    def test_true_when_artifact_reports_comparison_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = _write_freeze_artifact(
                root / "artifacts" / "freeze_candidate_evidence.json",
                status="comparison_available",
            )
            payload = _checklist_envelope()
            with _patch_checklist(payload):
                report = cli.run_demo_readiness_blocker_inspection(
                    repo_root=str(root),
                    freeze_artifact=str(artifact),
                )
        self.assertTrue(report["comparison_available"])

    def test_false_when_artifact_status_not_comparison_available(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = _write_freeze_artifact(
                root / "artifacts" / "freeze_candidate_evidence.json",
                status="benchmark_not_present",
            )
            payload = _checklist_envelope()
            with _patch_checklist(payload):
                report = cli.run_demo_readiness_blocker_inspection(
                    repo_root=str(root),
                    freeze_artifact=str(artifact),
                )
        self.assertFalse(report["comparison_available"])

    def test_false_when_artifact_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _checklist_envelope()
            with _patch_checklist(payload):
                report = cli.run_demo_readiness_blocker_inspection(
                    repo_root=str(root),
                    freeze_artifact=str(
                        root / "artifacts" / "does_not_exist.json"
                    ),
                )
        self.assertFalse(report["comparison_available"])

    def test_unparseable_artifact_surfaces_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "artifacts" / "freeze_candidate_evidence.json"
            bad.parent.mkdir(parents=True, exist_ok=True)
            bad.write_text("{not json", encoding="utf-8")
            payload = _checklist_envelope()
            with _patch_checklist(payload):
                report = cli.run_demo_readiness_blocker_inspection(
                    repo_root=str(root),
                    freeze_artifact=str(bad),
                )
        self.assertFalse(report["comparison_available"])
        joined = " | ".join(report["warnings"]).lower()
        self.assertIn("freeze artifact", joined)


# ---------------------------------------------------------------------------
# Recommended next implementation target
# ---------------------------------------------------------------------------


class TestRecommendation(unittest.TestCase):
    def test_recommends_daily_enrich_when_blocker(self) -> None:
        payload = _checklist_envelope(
            blocker_ids=("daily_mechanism_family_enrichment_resolved",),
            readiness="blocked",
            ok=False,
        )
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        rec = report["recommended_next_implementation_target"]
        self.assertIn("artifact", rec.lower())
        # Recommendation must not promise we already implemented it.
        self.assertNotIn("applied", rec.lower())

    def test_recommends_a_partial_when_no_blocker(self) -> None:
        payload = _checklist_envelope(
            blocker_ids=(),
            partial_ids=("no_paid_smoke_available",),
            readiness="required_checks_pending",
        )
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        rec = report["recommended_next_implementation_target"]
        self.assertTrue(rec)
        self.assertIn("no_paid_smoke", rec)

    def test_empty_when_everything_passes(self) -> None:
        payload = _checklist_envelope(
            blocker_ids=(),
            partial_ids=(),
            passed_ids=(
                "weekly_duplicate_canonicalization_landed",
                "still_moving_sector_etf_primary_gate_landed",
                "daily_mechanism_family_enrichment_resolved",
                "freeze_candidate_evidence_artifact_validates",
                "benchmark_sensitivity_event_60_honest_representation",
                "no_paid_smoke_available",
            ),
            readiness="required_checks_passed",
            required_actions=(),
        )
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        self.assertEqual(
            report["recommended_next_implementation_target"], "",
        )


# ---------------------------------------------------------------------------
# Readiness pass-through and ok flag
# ---------------------------------------------------------------------------


class TestReadinessPassthrough(unittest.TestCase):
    def test_blocked_passthrough(self) -> None:
        payload = _checklist_envelope(
            blocker_ids=("daily_mechanism_family_enrichment_resolved",),
            readiness="blocked",
            ok=False,
        )
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        self.assertEqual(report["readiness_status"], "blocked")
        self.assertFalse(report["ok"])

    def test_pending_passthrough(self) -> None:
        payload = _checklist_envelope(
            readiness="required_checks_pending",
            ok=True,
        )
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        self.assertEqual(
            report["readiness_status"], "required_checks_pending",
        )
        self.assertTrue(report["ok"])

    def test_never_emits_flat_demo_ready_token(self) -> None:
        payload = _checklist_envelope(
            readiness="required_checks_passed",
            partial_ids=(),
            blocker_ids=(),
            passed_ids=(
                "weekly_duplicate_canonicalization_landed",
                "still_moving_sector_etf_primary_gate_landed",
                "daily_mechanism_family_enrichment_resolved",
                "freeze_candidate_evidence_artifact_validates",
                "benchmark_sensitivity_event_60_honest_representation",
                "no_paid_smoke_available",
            ),
            required_actions=(),
        )
        with _patch_checklist(payload):
            report = cli.run_demo_readiness_blocker_inspection()
        self.assertNotIn(
            report["readiness_status"], ("demo_ready", "demo-ready"),
        )


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _build(self) -> dict[str, Any]:
        payload = _checklist_envelope(
            blocker_ids=("daily_mechanism_family_enrichment_resolved",),
            partial_ids=("no_paid_smoke_available",),
            readiness="blocked",
            ok=False,
        )
        with _patch_checklist(payload):
            return cli.run_demo_readiness_blocker_inspection()

    def test_no_banned_words_in_json_render(self) -> None:
        report = self._build()
        blob = cli._render_json(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(
                term, blob, f"banned token {term!r} in JSON render",
            )

    def test_no_banned_words_in_text_render(self) -> None:
        report = self._build()
        text = cli._render_text(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(
                term, text, f"banned token {term!r} in text render",
            )


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_provider_attrs(self) -> None:
        for attr in (
            "yfinance", "anthropic", "openai", "fastapi",
            "FastAPI", "APIRouter", "market_data", "sqlite3",
        ):
            self.assertFalse(
                hasattr(cli, attr),
                f"inspection must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_json_emits_required_keys(self) -> None:
        payload = _checklist_envelope()
        with _patch_checklist(payload):
            rc, output = self._run(["--json"])
        parsed = json.loads(output)
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertEqual(rc, 0)

    def test_blocked_input_yields_nonzero_exit(self) -> None:
        payload = _checklist_envelope(
            blocker_ids=("daily_mechanism_family_enrichment_resolved",),
            readiness="blocked",
            ok=False,
        )
        with _patch_checklist(payload):
            rc, _ = self._run(["--json"])
        self.assertNotEqual(rc, 0)

    def test_text_render_does_not_crash(self) -> None:
        payload = _checklist_envelope()
        with _patch_checklist(payload):
            rc, output = self._run([])
        self.assertIn("inspection", output.lower())
        self.assertIn(rc, (0, 1))

    def test_output_file_written_when_requested(self) -> None:
        payload = _checklist_envelope()
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.json"
            with _patch_checklist(payload):
                rc, _ = self._run([
                    "--json", "--output", str(out_path),
                ])
            self.assertTrue(out_path.is_file())
            data = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(set(data.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
