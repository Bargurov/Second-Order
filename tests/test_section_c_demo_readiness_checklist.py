"""Tests for ``scripts/section_c_demo_readiness_checklist.py``.

The checklist asks six narrow questions about Section C's state in
the repo today and surfaces a conservative readiness verdict.  It
must never claim demo readiness on its own and must never run a
DB / provider / LLM / FastAPI surface.

Pin the contract:

* Read-only.  No DB writes; no ``yfinance``, ``market_data``,
  LLM, paid provider, or FastAPI surface imported at module load.
* Output dict has EXACTLY these 9 keys::

    ok, readiness_status, blockers, passed_checks, partial_checks,
    required_before_demo, optional_before_demo, warnings, errors

* The six required checks are always present and use their
  spec-pinned check_id strings.
* ``readiness_status`` is one of:
    blocked | required_checks_pending | required_checks_passed
  The checklist never emits a flat ``"demo_ready"`` token.
* When any required check is blocked, readiness_status is
  ``"blocked"``; when at least one required check is partial and
  none are blocked, readiness_status is
  ``"required_checks_pending"``; only when every required check
  is passed does readiness_status become
  ``"required_checks_passed"``.
* Conservative wording — banned tokens absent from every rendered
  output.
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

from scripts import section_c_demo_readiness_checklist as cli  # noqa: E402


_REQUIRED_TOP_KEYS = (
    "ok",
    "readiness_status",
    "blockers",
    "passed_checks",
    "partial_checks",
    "required_before_demo",
    "optional_before_demo",
    "warnings",
    "errors",
)


_CHECK_KEYS = (
    "check_id",
    "description",
    "required",
    "status",
    "evidence",
    "next_action",
)


_REQUIRED_CHECK_IDS = (
    "weekly_duplicate_canonicalization_landed",
    "still_moving_sector_etf_primary_gate_landed",
    "daily_mechanism_family_enrichment_resolved",
    "freeze_candidate_evidence_artifact_validates",
    "benchmark_sensitivity_event_60_honest_representation",
    "no_paid_smoke_available",
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
    # The strongest readiness claim is "required_checks_passed".
    # A flat "demo_ready" or "demo-ready" claim is banned.
    "demo_ready",
    "demo-ready",
)


# ---------------------------------------------------------------------------
# Synthetic repo fixture
# ---------------------------------------------------------------------------


def _write_freeze_artifact(
    artifacts_dir: Path,
    *,
    event_60_in_changed: bool = True,
    changed_count:       int = 1,
    event_60_records_significant: bool = False,
    no_fdr_caveat:       bool = True,
) -> Path:
    """Write a small synthetic freeze-candidate evidence artifact.

    The four signals are tunable so tests can pin honesty checks
    against each combination.
    """
    artifact = {
        "artifact_type": "freeze_candidate_evidence",
        "cohort_summary": {
            "fdr_significant_count": 0,
            "total_records":         3,
        },
        "records": [
            {
                "source":           "synthetic",
                "event_id":         60,
                "headline":         "Stub event 60",
                "primary_ticker":   "XOM",
                "benchmark":        "XLE",
                "mechanism_family": "stub_family",
                "horizon":          5,
                "p_value":          0.3,
                "fdr_q":            0.3,
                "raw_p_candidate":  False,
                "fdr_significant":  bool(event_60_records_significant),
                "verdict":          "inconclusive_fdr",
            },
        ],
        "benchmark_sensitivity_status": {
            "status":                       "comparison_available",
            "changed_event_ids":            [60] if event_60_in_changed else [],
            "changed_interpretation_count": int(changed_count),
        },
        "duplicate_event_ids": [],
        "limitations": (
            [
                "freeze-candidate only — awaiting operator approval.",
                "no FDR-significant validation claim is supported by "
                "this evidence set.",
            ]
            if no_fdr_caveat
            else ["freeze-candidate only — awaiting operator approval."]
        ),
    }
    path = artifacts_dir / "freeze_candidate_evidence.json"
    path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return path


# Default body the fixture writes for valid analyzed_event_artifact
# files — mirrors the three required fields the Daily Section C
# gate enforces.  Tests that want invalid bodies on disk pass
# ``invalid_artifacts_count`` instead.
_DEFAULT_VALID_ARTIFACT_BODY: dict[str, Any] = {
    "mechanism_family":  "supply_shock",
    "primary_ticker":    "XOM",
    "benchmark_ticker":  "XLE",
}


def _make_fake_repo(
    root: Path,
    *,
    weekly_helper:             bool = True,
    weekly_wired_in_movers:    bool = True,
    sector_etf_helper:         bool = True,
    sector_etf_called:         bool = True,
    analyzed_artifacts_count:  int  = 0,
    invalid_artifacts_count:   int  = 0,
    artifact_gate_wired:       bool = False,
    fixture_smoke_present:     bool = False,
    fixture_smoke_test_present: bool = False,
    no_paid_smoke_present:     bool = True,
    write_freeze_artifact:     bool = True,
    **freeze_kwargs:           Any,
) -> Path:
    """Materialise a fake repo skeleton on disk for the checklist
    to walk.  Returns the freeze-artifact path (when written).

    ``analyzed_artifacts_count`` writes that many
    ``analyzed_event_artifact_valid_<idx>.json`` files carrying
    the three required fields (mechanism_family, primary_ticker,
    benchmark_ticker).  ``invalid_artifacts_count`` writes that
    many ``analyzed_event_artifact_invalid_<idx>.json`` files
    whose body is an empty JSON object — exercising the gate's
    missing-required-fields branch.

    ``fixture_smoke_present`` controls whether
    ``scripts/daily_artifact_gate_fixture_smoke.py`` exists on
    disk; ``fixture_smoke_test_present`` controls whether
    ``tests/test_daily_artifact_gate_fixture_smoke.py`` exists.
    Both default to ``False`` so existing test fixtures keep
    their behaviour and only the new tests opt into the fixture-
    backed signal.
    """
    (root / "routes").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)

    if weekly_helper:
        (root / "routes" / "weekly_canonicalization.py").write_text(
            "def collapse_weekly_duplicates(items):\n    return list(items)\n",
            encoding="utf-8",
        )

    movers_lines = []
    if weekly_wired_in_movers:
        movers_lines.append(
            "from routes.weekly_canonicalization import "
            "collapse_weekly_duplicates"
        )
        movers_lines.append(
            "def _weekly_route(envelope):\n"
            "    envelope['items'] = collapse_weekly_duplicates(envelope['items'])\n"
            "    return envelope"
        )
    else:
        movers_lines.append("# weekly canonicalization not wired in\n")
    if artifact_gate_wired:
        movers_lines.append(
            "# analyzed_event_artifact gate placeholder"
        )
    (root / "routes" / "movers.py").write_text(
        "\n".join(movers_lines) + "\n",
        encoding="utf-8",
    )

    norm_lines: list[str] = []
    if sector_etf_helper:
        norm_lines.append(
            "def primary_is_sector_etf(card):\n    return False\n"
        )
    if sector_etf_called:
        norm_lines.append(
            "def is_high_conviction_persistent(card):\n"
            "    if primary_is_sector_etf(card):\n"
            "        return False\n"
            "    return True\n"
        )
    if not norm_lines:
        norm_lines.append("# sector ETF gate missing\n")
    (root / "mover_card_normalizer.py").write_text(
        "\n".join(norm_lines), encoding="utf-8",
    )

    for i in range(int(analyzed_artifacts_count)):
        (root / "artifacts"
         / f"analyzed_event_artifact_valid_{i:04d}.json"
         ).write_text(
            json.dumps(_DEFAULT_VALID_ARTIFACT_BODY),
            encoding="utf-8",
        )
    for i in range(int(invalid_artifacts_count)):
        (root / "artifacts"
         / f"analyzed_event_artifact_invalid_{i:04d}.json"
         ).write_text("{}", encoding="utf-8")

    if fixture_smoke_present:
        (root / "scripts"
         / "daily_artifact_gate_fixture_smoke.py").write_text(
            "# stub daily artifact gate fixture smoke\n",
            encoding="utf-8",
        )
    if fixture_smoke_test_present:
        (root / "tests"
         / "test_daily_artifact_gate_fixture_smoke.py").write_text(
            "# stub fixture-smoke unit-test\n",
            encoding="utf-8",
        )

    if no_paid_smoke_present:
        (root / "scripts" / "no_paid_smoke.py").write_text(
            "# stub no-paid smoke\n", encoding="utf-8",
        )

    freeze_path = root / "artifacts" / "freeze_candidate_evidence.json"
    if write_freeze_artifact:
        _write_freeze_artifact(root / "artifacts", **freeze_kwargs)
    return freeze_path


# Default validator stub that returns a clean envelope; tests patch
# this directly so they never hit the real validator (which would
# enforce all 11 schema checks on our synthetic artifact).
def _ok_validator_payload(records_count: int = 3) -> dict[str, Any]:
    return {
        "ok":            True,
        "artifact_path": "synthetic",
        "records_count": records_count,
        "errors":        [],
        "warnings":      [],
    }


def _patch_validator(payload: dict[str, Any]):
    return patch.object(
        cli, "_run_freeze_validator",
        return_value=payload,
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_required_keys_on_clean_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=2,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertIn(report["readiness_status"], _VALID_READINESS_VALUES)

    def test_every_check_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=1,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        all_checks = (
            report["passed_checks"]
            + report["partial_checks"]
            + report["blockers"]
        )
        for c in all_checks:
            self.assertEqual(set(c.keys()), set(_CHECK_KEYS),
                             f"check fields drifted: {c.get('check_id')}")

    def test_all_six_required_check_ids_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        all_checks = (
            report["passed_checks"]
            + report["partial_checks"]
            + report["blockers"]
        )
        ids = {c["check_id"] for c in all_checks}
        self.assertEqual(ids, set(_REQUIRED_CHECK_IDS))


# ---------------------------------------------------------------------------
# Per-check verdicts
# ---------------------------------------------------------------------------


def _find_check(
    report: dict[str, Any], check_id: str,
) -> dict[str, Any]:
    for bucket in ("passed_checks", "partial_checks", "blockers"):
        for c in report[bucket]:
            if c["check_id"] == check_id:
                return c
    raise AssertionError(f"check {check_id!r} missing from report")


class TestWeeklyCanonicalizationCheck(unittest.TestCase):
    def test_passes_when_helper_and_wiring_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=1,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "weekly_duplicate_canonicalization_landed")
        self.assertEqual(c["status"], "passed")

    def test_blocked_when_helper_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, weekly_helper=False)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "weekly_duplicate_canonicalization_landed")
        self.assertEqual(c["status"], "blocked")

    def test_blocked_when_movers_not_wired_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, weekly_wired_in_movers=False)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "weekly_duplicate_canonicalization_landed")
        self.assertEqual(c["status"], "blocked")


class TestSectorEtfGateCheck(unittest.TestCase):
    def test_passes_when_helper_defined_and_called(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=1,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(
            report, "still_moving_sector_etf_primary_gate_landed",
        )
        self.assertEqual(c["status"], "passed")

    def test_blocked_when_helper_not_called(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, sector_etf_called=False)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(
            report, "still_moving_sector_etf_primary_gate_landed",
        )
        self.assertEqual(c["status"], "blocked")


class TestDailyEnrichmentCheck(unittest.TestCase):
    def test_blocked_when_no_artifacts_and_no_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=0,
                            artifact_gate_wired=False)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        self.assertEqual(c["status"], "blocked")
        # The next-action prose must mention the artifact gate path.
        self.assertIn("artifact", c["next_action"].lower())

    def test_partial_when_only_artifacts_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=2,
                            artifact_gate_wired=False)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        self.assertEqual(c["status"], "partial")

    def test_partial_when_only_gate_wired_no_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=0,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        self.assertEqual(c["status"], "partial")

    def test_passed_when_gate_wired_and_artifacts_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=3,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        self.assertEqual(c["status"], "passed")

    # ----- Three-state distinction for the Daily artifact gate -----

    def test_partial_when_gate_wired_no_fixture_no_artifacts(self) -> None:
        # State A: gate wired into routes/ but no fixture smoke and
        # no real analyzed_event_artifact files.  The check stays
        # partial and the readiness status stays
        # required_checks_pending.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=0,
                            artifact_gate_wired=True,
                            fixture_smoke_present=False,
                            fixture_smoke_test_present=False)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        self.assertEqual(c["status"], "partial")
        self.assertEqual(report["readiness_status"],
                         "required_checks_pending")

    def test_partial_when_fixture_smoke_present_no_real_artifacts(self) -> None:
        # State B: gate wired AND fixture-backed smoke present, but
        # zero real analyzed_event_artifact files.  Mechanics can be
        # exercised by the fixture smoke, but the check stays
        # partial — the readiness must NOT advance to
        # required_checks_passed on the strength of fixture
        # coverage alone.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=0,
                            artifact_gate_wired=True,
                            fixture_smoke_present=True,
                            fixture_smoke_test_present=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        self.assertEqual(c["status"], "partial")

        # Evidence must surface the fixture-backed smoke script so
        # the operator can see that gate mechanics can be exercised.
        joined_evidence = " | ".join(c["evidence"]).lower()
        self.assertIn("fixture", joined_evidence)
        self.assertIn(
            "scripts/daily_artifact_gate_fixture_smoke.py",
            joined_evidence,
        )

        # Next-action must require real artifact-backed Daily
        # candidates before the demo and must not claim that
        # fixture coverage settles the Daily path.
        action = c["next_action"].lower()
        self.assertIn("analyzed_event_artifact", action)
        self.assertIn("real", action)
        self.assertIn(
            "scripts/daily_artifact_gate_fixture_smoke.py",
            action,
        )
        # No fixture-only claim of readiness.
        self.assertNotIn("demo-ready", action)
        self.assertNotIn("demo_ready", action)

        # Readiness must remain pending — never required_checks_passed
        # — when fixture is present but real artifacts are absent.
        self.assertEqual(report["readiness_status"],
                         "required_checks_pending")
        self.assertNotEqual(report["readiness_status"],
                            "required_checks_passed")

    def test_passed_with_real_artifacts_regardless_of_fixture(self) -> None:
        # State C: gate wired AND real analyzed_event_artifact files
        # present.  The check passes regardless of whether the
        # fixture smoke is present (real candidates are the
        # authoritative signal).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=2,
                            artifact_gate_wired=True,
                            fixture_smoke_present=True,
                            fixture_smoke_test_present=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        self.assertEqual(c["status"], "passed")

    # ----- Validity-aware artifact handling -----

    def test_evidence_surfaces_three_artifact_counts(self) -> None:
        # Mixed cohort: 2 valid + 1 invalid + gate wired.  At least
        # one valid artifact lifts the check to passed, and the
        # evidence list must surface artifact_count,
        # valid_artifact_count, and invalid_artifact_count so the
        # operator can see the cohort shape.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=2,
                            invalid_artifacts_count=1,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        self.assertEqual(c["status"], "passed")
        joined = " | ".join(c["evidence"])
        self.assertIn("artifact_count: 3", joined)
        self.assertIn("valid_artifact_count: 2", joined)
        self.assertIn("invalid_artifact_count: 1", joined)

    def test_partial_when_only_invalid_artifacts_with_gate(self) -> None:
        # Three invalid artifacts under artifacts/ but zero valid
        # ones plus the gate wired in routes/ → status stays
        # partial, next_action calls out the repair path, and the
        # readiness status remains required_checks_pending.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=0,
                            invalid_artifacts_count=3,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        self.assertEqual(c["status"], "partial")
        joined_evidence = " | ".join(c["evidence"])
        self.assertIn("artifact_count: 3", joined_evidence)
        self.assertIn("valid_artifact_count: 0", joined_evidence)
        self.assertIn("invalid_artifact_count: 3", joined_evidence)

        # Next-action must mention repair + the required-field
        # names so the operator knows what is missing.
        action = c["next_action"].lower()
        self.assertIn("repair", action)
        self.assertIn("mechanism_family", action)
        self.assertIn("primary_ticker", action)
        self.assertIn("benchmark_ticker", action)
        # Conservative wording — no demo-ready claim.
        self.assertNotIn("demo-ready", action)
        self.assertNotIn("demo_ready", action)

        self.assertEqual(report["readiness_status"],
                         "required_checks_pending")
        self.assertNotEqual(report["readiness_status"],
                            "required_checks_passed")

    def test_passed_when_at_least_one_valid_artifact_among_invalid(self) -> None:
        # 1 valid + 2 invalid with the gate wired → the check
        # passes because at least one real artifact carries the
        # three required fields.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=1,
                            invalid_artifacts_count=2,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        self.assertEqual(c["status"], "passed")

    def test_invalid_artifact_evidence_lists_missing_fields(self) -> None:
        # An invalid artifact (empty JSON object) lacks all three
        # required fields.  The evidence list must mention the
        # filename and at least one of the missing field names so
        # the operator knows exactly what to repair.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=0,
                            invalid_artifacts_count=1,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        joined = " | ".join(c["evidence"])
        # The invalid example line mentions the file name + the
        # missing-fields reason text.
        self.assertIn("analyzed_event_artifact_invalid_0000.json",
                      joined)
        self.assertIn("missing required fields", joined)
        # At least one of the three required fields is named.
        self.assertTrue(
            "mechanism_family" in joined
            or "primary_ticker" in joined
            or "benchmark_ticker" in joined,
            f"no required-field name in evidence: {joined!r}",
        )

    def test_invalid_artifact_with_none_sentinel_is_rejected(self) -> None:
        # Custom artifact: every required field present but
        # mechanism_family is the "none" sentinel string.  The
        # gate rejects this artifact, so the validity check must
        # too.  Place it manually rather than going through the
        # helper to exercise the sentinel branch.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=0,
                            invalid_artifacts_count=0,
                            artifact_gate_wired=True)
            sentinel_body = {
                "mechanism_family":  "none",
                "primary_ticker":    "XOM",
                "benchmark_ticker":  "XLE",
            }
            (root / "artifacts"
             / "analyzed_event_artifact_sentinel.json").write_text(
                json.dumps(sentinel_body),
                encoding="utf-8",
            )
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        # Sentinel-body artifact must NOT count as valid.
        self.assertEqual(c["status"], "partial")
        joined = " | ".join(c["evidence"])
        self.assertIn("valid_artifact_count: 0", joined)
        self.assertIn("invalid_artifact_count: 1", joined)
        # The sentinel-rejection reason surfaces in evidence.
        self.assertIn("none-sentinel", joined)

    def test_evidence_marks_fixture_missing_when_absent(self) -> None:
        # When the fixture-backed smoke is not on disk, the
        # evidence list says so explicitly so the operator can
        # tell the two partial states apart.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=0,
                            artifact_gate_wired=True,
                            fixture_smoke_present=False,
                            fixture_smoke_test_present=False)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "daily_mechanism_family_enrichment_resolved")
        joined_evidence = " | ".join(c["evidence"]).lower()
        self.assertIn("fixture-backed gate smoke missing", joined_evidence)


class TestFreezeArtifactCheck(unittest.TestCase):
    def test_passes_when_validator_returns_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "freeze_candidate_evidence_artifact_validates")
        self.assertEqual(c["status"], "passed")

    def test_blocked_when_validator_returns_errors(self) -> None:
        bad_payload = {
            "ok":            False,
            "artifact_path": "synthetic",
            "records_count": 0,
            "errors":        ["records is not a list"],
            "warnings":      [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root)
            with _patch_validator(bad_payload):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "freeze_candidate_evidence_artifact_validates")
        self.assertEqual(c["status"], "blocked")
        # The overall readiness must collapse to blocked too.
        self.assertEqual(report["readiness_status"], "blocked")

    def test_blocked_when_validator_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root)
            with patch.object(
                cli, "_run_freeze_validator",
                side_effect=RuntimeError("boom"),
            ):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "freeze_candidate_evidence_artifact_validates")
        self.assertEqual(c["status"], "blocked")
        joined = " | ".join(report["errors"]).lower()
        self.assertIn("validator", joined)


class TestEvent60HonestyCheck(unittest.TestCase):
    def test_passes_when_all_four_signals_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(
                root,
                analyzed_artifacts_count=1, artifact_gate_wired=True,
                event_60_in_changed=True,
                changed_count=1,
                event_60_records_significant=False,
                no_fdr_caveat=True,
            )
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(
            report,
            "benchmark_sensitivity_event_60_honest_representation",
        )
        self.assertEqual(c["status"], "passed")

    def test_partial_when_one_signal_missing(self) -> None:
        # Drop the no-FDR caveat — three of four signals still hold.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(
                root,
                event_60_in_changed=True,
                changed_count=1,
                event_60_records_significant=False,
                no_fdr_caveat=False,
            )
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(
            report,
            "benchmark_sensitivity_event_60_honest_representation",
        )
        self.assertEqual(c["status"], "partial")

    def test_blocked_when_all_signals_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(
                root,
                event_60_in_changed=False,
                changed_count=0,
                event_60_records_significant=True,
                no_fdr_caveat=False,
            )
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(
            report,
            "benchmark_sensitivity_event_60_honest_representation",
        )
        self.assertEqual(c["status"], "blocked")

    def test_blocked_when_artifact_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, write_freeze_artifact=False)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(
            report,
            "benchmark_sensitivity_event_60_honest_representation",
        )
        self.assertEqual(c["status"], "blocked")


class TestNoPaidSmokeCheck(unittest.TestCase):
    def test_partial_when_smoke_script_present(self) -> None:
        # The checklist does not run the smoke — it surfaces a
        # partial verdict and a next_action telling the operator to
        # run it separately.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, no_paid_smoke_present=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "no_paid_smoke_available")
        self.assertEqual(c["status"], "partial")
        self.assertIn("no_paid_smoke", c["next_action"])

    def test_blocked_when_smoke_script_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, no_paid_smoke_present=False)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        c = _find_check(report, "no_paid_smoke_available")
        self.assertEqual(c["status"], "blocked")


# ---------------------------------------------------------------------------
# Readiness classification
# ---------------------------------------------------------------------------


class TestReadinessClassification(unittest.TestCase):
    def test_blocked_when_any_required_check_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, weekly_helper=False,
                            analyzed_artifacts_count=2,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        self.assertEqual(report["readiness_status"], "blocked")
        self.assertFalse(report["ok"])

    def test_pending_when_only_partials_no_blockers(self) -> None:
        # Default repo has the no-paid smoke present (partial) and
        # daily enrichment blocked unless we provide artifacts AND
        # gate.  Provide both so daily enrichment passes, leaving
        # the no-paid smoke as the only partial.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=2,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        # With the standard fixture the no-paid smoke is partial.
        self.assertEqual(report["readiness_status"],
                         "required_checks_pending")
        self.assertTrue(report["ok"])

    def test_no_required_check_collapses_to_partial(self) -> None:
        # Even a single required partial keeps the readiness from
        # the strongest "required_checks_passed" claim.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=3,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        self.assertIn(
            report["readiness_status"],
            ("required_checks_pending", "required_checks_passed"),
        )

    def test_never_claims_flat_demo_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=2,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        self.assertNotIn(report["readiness_status"],
                         ("demo_ready", "demo-ready"))


# ---------------------------------------------------------------------------
# required_before_demo / optional_before_demo
# ---------------------------------------------------------------------------


class TestActionLists(unittest.TestCase):
    def test_required_before_demo_collects_blocker_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, weekly_helper=False,
                            analyzed_artifacts_count=2,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        # The weekly canonicalization blocker carries a next_action
        # that mentions collapse_weekly_duplicates.
        joined = " | ".join(report["required_before_demo"]).lower()
        self.assertIn("collapse_weekly_duplicates", joined)

    def test_optional_before_demo_is_empty_in_default_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        self.assertEqual(report["optional_before_demo"], [])


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _build(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=2,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                return cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )

    def test_no_banned_words_in_json_render(self) -> None:
        report = self._build()
        blob = cli._render_json(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, blob,
                             f"banned token {term!r} in JSON render")

    def test_no_banned_words_in_text_render(self) -> None:
        report = self._build()
        text = cli._render_text(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(term, text,
                             f"banned token {term!r} in text render")

    def test_no_banned_words_in_invalid_artifact_state_renders(self) -> None:
        # State with gate wired + invalid-only artifacts on disk
        # exercises the "repair the invalid artifact(s)" next-
        # action prose, which names specific required fields.
        # Pin it against banned-token drift through both render
        # paths so a future copy edit cannot reintroduce words
        # like "proven" or "demo-ready" via this branch.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=0,
                            invalid_artifacts_count=2,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        blob_json = cli._render_json(report).lower()
        blob_text = cli._render_text(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(
                term, blob_json,
                f"banned token {term!r} in JSON render "
                f"(invalid-artifact state)",
            )
            self.assertNotIn(
                term, blob_text,
                f"banned token {term!r} in text render "
                f"(invalid-artifact state)",
            )

    def test_no_banned_words_in_fixture_state_renders(self) -> None:
        # State B (gate wired + fixture smoke present + no real
        # artifacts) introduces the longest next-action prose in the
        # checklist.  Pin it against banned-token drift through both
        # render paths so a future copy edit cannot reintroduce
        # words like "proven" or "demo-ready" via this branch.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=0,
                            artifact_gate_wired=True,
                            fixture_smoke_present=True,
                            fixture_smoke_test_present=True)
            with _patch_validator(_ok_validator_payload()):
                report = cli.run_section_c_demo_readiness_checklist(
                    repo_root=str(root),
                )
        blob_json = cli._render_json(report).lower()
        blob_text = cli._render_text(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(
                term, blob_json,
                f"banned token {term!r} in JSON render (fixture state)",
            )
            self.assertNotIn(
                term, blob_text,
                f"banned token {term!r} in text render (fixture state)",
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
                f"checklist must not bind {attr} as a module attr",
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
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, analyzed_artifacts_count=2,
                            artifact_gate_wired=True)
            with _patch_validator(_ok_validator_payload()):
                rc, output = self._run([
                    "--json", "--repo-root", str(root),
                ])
        parsed = json.loads(output)
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_TOP_KEYS))
        # OK is True because no required check is blocked in this
        # fixture (some are partial, which is still ok=True).
        self.assertTrue(parsed["ok"])
        self.assertEqual(rc, 0)

    def test_blocked_fixture_yields_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root, weekly_helper=False)
            with _patch_validator(_ok_validator_payload()):
                rc, _ = self._run([
                    "--json", "--repo-root", str(root),
                ])
        self.assertNotEqual(rc, 0)

    def test_text_render_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_fake_repo(root)
            with _patch_validator(_ok_validator_payload()):
                rc, output = self._run(["--repo-root", str(root)])
        self.assertIn("checklist", output.lower())
        # Exit may be 0 or 1 depending on partials/blockers; we just
        # confirm the renderer ran end-to-end.
        self.assertIn(rc, (0, 1))


if __name__ == "__main__":
    unittest.main()
