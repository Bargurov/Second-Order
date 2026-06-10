"""Tests for ``scripts/validate_phase2_pool.py``.

Pin the contract:

* Read-only validator.  No DB writes, no provider, no LLM, no
  ``yfinance``, no FastAPI surface.  The artifact file is never
  mutated by validation.
* Validates ``evidence_artifacts/section_c_v2/phase2_pool_v1.json``
  (or any artifact passed via ``--artifact``) against the
  ``phase2_pool`` schema.
* Output dict has EXACTLY these 5 keys::

    ok, artifact_path, records_count, errors, warnings

* ``ok`` is True iff ``errors`` is empty.
* The validator must accept the live tracked artifact at
  ``evidence_artifacts/section_c_v2/phase2_pool_v1.json``.  Rejection of
  the live artifact means the validator is the suspect, not the
  artifact (the live artifact is in the immutable list for this task).
* The validator recomputes BH q-values from candidate ``raw_p``
  values using ``stats.fdr.bh_adjust`` and fails on disagreement.
* No banned overclaim tokens in prose fields:
  ``proof``, ``proven``, ``validated``, ``alpha``, ``prediction``,
  ``predicted``, ``confirms the mechanism``, ``fdr pending``,
  ``hypothetical``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import validate_phase2_pool as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "artifact_path",
    "records_count",
    "errors",
    "warnings",
)


_LIVE_ARTIFACT_PATH = str(
    Path(__file__).resolve().parents[1]
    / "evidence_artifacts" / "section_c_v2" / "phase2_pool_v1.json"
)


# ---------------------------------------------------------------------------
# Fixture helpers — derived from the live phase2_pool_v1.json shape
# ---------------------------------------------------------------------------


def _good_candidate_ba() -> dict[str, Any]:
    return {
        "candidate_id": "BA_737MAX_CRASH_MAR2019",
        "primary_ticker": "BA",
        "benchmark_ticker": "SPY",
        "event_date": "2019-03-08",
        "claimed_horizon": 1,
        "raw_p": 3.2e-08,
        "bh_rank": 1,
        "q_bh": 1.6e-07,
        "passes_bh_at_005": True,
        "phase2_pool_count": True,
        "phase2_pool_role": "passes_bh",
    }


def _good_candidate_alb() -> dict[str, Any]:
    return {
        "candidate_id": "ALB_CHILE_LITHIUM_APR2023",
        "primary_ticker": "ALB",
        "benchmark_ticker": "SPY",
        "event_date": "2023-04-20",
        "claimed_horizon": 1,
        "raw_p": 4.4e-05,
        "bh_rank": 2,
        "q_bh": 0.00011,
        "passes_bh_at_005": True,
        "phase2_pool_count": True,
        "phase2_pool_role": "passes_bh",
    }


def _good_candidate_nvda() -> dict[str, Any]:
    return {
        "candidate_id": "phase2-export-control-nvda-oct17-2023-bis",
        "primary_ticker": "NVDA",
        "benchmark_ticker": "SMH",
        "event_date": "2023-10-16",
        "claimed_horizon": 1,
        "raw_p": 0.0081,
        "bh_rank": 3,
        "q_bh": 0.0135,
        "passes_bh_at_005": True,
        "phase2_pool_count": True,
        "phase2_pool_role": "passes_bh",
    }


def _good_candidate_amat() -> dict[str, Any]:
    return {
        "candidate_id": "AMAT_BIS_OCT2022",
        "primary_ticker": "AMAT",
        "benchmark_ticker": "SPY",
        "event_date": "2022-10-06",
        "claimed_horizon": 1,
        "raw_p": 0.0527,
        "bh_rank": 4,
        "q_bh": 0.065875,
        "passes_bh_at_005": False,
        "phase2_pool_count": True,
        "phase2_pool_role": "denominator_only_failed_g5_and_bh",
    }


def _good_candidate_cf() -> dict[str, Any]:
    return {
        "candidate_id": "CF_UKRAINE_FERTILIZER_FEB2022",
        "primary_ticker": "CF",
        "benchmark_ticker": "SPY",
        "event_date": "2022-02-23",
        "claimed_horizon": 1,
        "raw_p": 0.161,
        "bh_rank": 5,
        "q_bh": 0.161,
        "passes_bh_at_005": False,
        "phase2_pool_count": True,
        "phase2_pool_role": "denominator_only_failed_g5_and_bh",
    }


def _good_pool(**overrides: Any) -> dict[str, Any]:
    """Build a minimum-viable phase2 pool artifact that the validator
    should accept."""
    base: dict[str, Any] = {
        "artifact_type": "phase2_pool",
        "schema_version": "v1",
        "pool_id": "phase2_pool_v1",
        "bh_alpha": 0.05,
        "denominator_count": 5,
        "fdr_method": "Benjamini-Hochberg",
        "policy_reference":
            "evidence_artifacts/section_c_v2/phase2_fdr_policy_v1.md",
        "phase1_freeze_artifact_reference":
            "evidence_artifacts/section_c_v2/freeze_candidate_evidence.json",
        "phase1_scope_note":
            "Phase 1 q-values are frozen and are NOT recomputed.",
        "candidates": [
            _good_candidate_ba(),
            _good_candidate_alb(),
            _good_candidate_nvda(),
            _good_candidate_amat(),
            _good_candidate_cf(),
        ],
        "limitations": [
            "Five-row pool with mixed mechanism families.",
        ],
    }
    base.update(overrides)
    return base


def _write_artifact(payload: dict[str, Any]) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"phase2_pool_test_{uuid.uuid4().hex}.json",
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Output schema & --artifact required
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_required_keys_on_good_pool(self) -> None:
        path = _write_artifact(_good_pool())
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
            self.assertTrue(report["ok"], report["errors"])
            self.assertEqual(report["records_count"], 5)
            self.assertEqual(report["artifact_path"], path)
        finally:
            os.unlink(path)

    def test_required_keys_on_failure(self) -> None:
        report = cli.run_validate_phase2_pool(
            artifact_path="/missing/phase2_pool.json",
        )
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))


class TestArtifactPathRequired(unittest.TestCase):
    def test_missing_path_returns_failure(self) -> None:
        report = cli.run_validate_phase2_pool(artifact_path=None)
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "artifact" in e.lower() for e in report["errors"]
        ))

    def test_nonexistent_path_returns_failure(self) -> None:
        report = cli.run_validate_phase2_pool(
            artifact_path="/nonexistent/phase2.json",
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["records_count"], 0)

    def test_malformed_json_returns_failure(self) -> None:
        path = os.path.join(
            tempfile.gettempdir(),
            f"phase2_bad_{uuid.uuid4().hex}.json",
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not-json")
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            self.assertEqual(report["records_count"], 0)
            self.assertTrue(any(
                "json" in e.lower() for e in report["errors"]
            ))
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Top-level pinned fields
# ---------------------------------------------------------------------------


class TestTopLevelPinnedFields(unittest.TestCase):
    def test_artifact_type_must_be_phase2_pool(self) -> None:
        pool = _good_pool()
        pool["artifact_type"] = "phase2_pool_v1"   # close but wrong
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "artifact_type" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_schema_version_must_be_v1(self) -> None:
        pool = _good_pool()
        pool["schema_version"] = "v2"
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "schema_version" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_pool_id_must_be_phase2_pool_v1(self) -> None:
        pool = _good_pool()
        pool["pool_id"] = "phase2_pool_v2"
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "pool_id" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_bh_alpha_must_be_005(self) -> None:
        pool = _good_pool()
        pool["bh_alpha"] = 0.10
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "bh_alpha" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_fdr_method_must_be_benjamini_hochberg(self) -> None:
        pool = _good_pool()
        pool["fdr_method"] = "Bonferroni"
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "fdr_method" in e for e in report["errors"]
            ))
        finally:
            os.unlink(path)

    def test_missing_required_top_level_key_fails(self) -> None:
        for key in (
            "artifact_type", "schema_version", "pool_id",
            "denominator_count", "bh_alpha", "fdr_method",
            "candidates",
        ):
            with self.subTest(missing=key):
                pool = _good_pool()
                pool.pop(key, None)
                path = _write_artifact(pool)
                try:
                    report = cli.run_validate_phase2_pool(artifact_path=path)
                    self.assertFalse(
                        report["ok"],
                        f"validator accepted pool missing {key!r}",
                    )
                    joined = " | ".join(report["errors"]).lower()
                    self.assertIn(key, joined)
                finally:
                    os.unlink(path)


# ---------------------------------------------------------------------------
# Denominator count
# ---------------------------------------------------------------------------


class TestDenominatorCount(unittest.TestCase):
    def test_wrong_denominator_value_fails(self) -> None:
        pool = _good_pool()
        pool["denominator_count"] = 7
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("denominator_count", joined)
        finally:
            os.unlink(path)

    def test_denominator_disagrees_with_candidate_count_fails(self) -> None:
        # Six candidates but denominator_count still 5 — the validator
        # must surface the disagreement.  We add a duplicate to push
        # candidate count to 6, but the duplicate test (separate) will
        # also fire, which is fine: both errors should be present.
        pool = _good_pool()
        sixth = copy.deepcopy(_good_candidate_ba())
        sixth["candidate_id"] = "BA_SECOND_COPY_DIFFERENT_ID"
        pool["candidates"].append(sixth)
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("denominator_count", joined)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Exact candidate set
# ---------------------------------------------------------------------------


class TestExactCandidateSet(unittest.TestCase):
    def test_missing_candidate_fails(self) -> None:
        pool = _good_pool()
        # Drop NVDA.
        pool["candidates"] = [
            c for c in pool["candidates"]
            if c["primary_ticker"] != "NVDA"
        ]
        # Keep denominator_count consistent with the candidate count
        # so the missing-candidate error is what fires, not the
        # denominator-mismatch error.
        pool["denominator_count"] = len(pool["candidates"])
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"])
            self.assertIn("NVDA", joined)
        finally:
            os.unlink(path)

    def test_extra_candidate_fails(self) -> None:
        pool = _good_pool()
        # Add a sixth row that isn't in the expected set.
        extra = copy.deepcopy(_good_candidate_ba())
        extra["candidate_id"] = "TSLA_PHANTOM_EVENT"
        extra["primary_ticker"] = "TSLA"
        pool["candidates"].append(extra)
        pool["denominator_count"] = 6   # avoid denominator error noise
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
        finally:
            os.unlink(path)

    def test_duplicate_candidate_fails(self) -> None:
        pool = _good_pool()
        # Replace AMAT with a duplicate BA — now BA appears twice and
        # AMAT is missing.  The validator must reject this.
        pool["candidates"][3] = copy.deepcopy(_good_candidate_ba())
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"])
            self.assertTrue(
                "duplicate" in joined.lower() or "BA" in joined,
                f"expected duplicate-or-BA error, got {report['errors']}",
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Phase2 pool count flag
# ---------------------------------------------------------------------------


class TestPhase2PoolCountFlag(unittest.TestCase):
    def test_candidate_with_pool_count_false_fails(self) -> None:
        pool = _good_pool()
        pool["candidates"][2]["phase2_pool_count"] = False    # NVDA
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("phase2_pool_count", joined)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# BH recompute — q_bh, bh_rank, passes_bh_at_005
# ---------------------------------------------------------------------------


class TestBhRecompute(unittest.TestCase):
    def test_wrong_q_bh_value_fails(self) -> None:
        pool = _good_pool()
        # Bump NVDA's q to a wildly wrong value.
        pool["candidates"][2]["q_bh"] = 0.99
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("q_bh", joined)
        finally:
            os.unlink(path)

    def test_wrong_bh_rank_fails(self) -> None:
        pool = _good_pool()
        # Swap BA's rank to 3 — wrong since it has the smallest raw_p.
        pool["candidates"][0]["bh_rank"] = 3
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("bh_rank", joined)
        finally:
            os.unlink(path)

    def test_wrong_pass_flag_fails(self) -> None:
        pool = _good_pool()
        # AMAT must fail; mark it as passing.
        pool["candidates"][3]["passes_bh_at_005"] = True
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("passes_bh_at_005", joined)
        finally:
            os.unlink(path)

    def test_three_passes_two_fail_exact(self) -> None:
        # Confirm the validator pins which three pass and which two
        # fail.  Flipping CF to pass=True must be caught.
        pool = _good_pool()
        pool["candidates"][4]["passes_bh_at_005"] = True   # CF
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
        finally:
            os.unlink(path)

    def test_q_bh_off_by_tiny_amount_within_tolerance_passes(self) -> None:
        # Floating-point round-trip: nudge q_bh by ~5e-13 (well inside
        # the tolerance).  The validator must accept.
        pool = _good_pool()
        pool["candidates"][2]["q_bh"] = 0.0135 + 5e-13
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertTrue(report["ok"], report["errors"])
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


class TestReferences(unittest.TestCase):
    def test_missing_policy_reference_fails(self) -> None:
        pool = _good_pool()
        pool.pop("policy_reference")
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("policy_reference", joined)
        finally:
            os.unlink(path)

    def test_wrong_policy_reference_fails(self) -> None:
        pool = _good_pool()
        pool["policy_reference"] = "evidence_artifacts/some_other_file.md"
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("policy_reference", joined)
        finally:
            os.unlink(path)

    def test_missing_phase1_freeze_artifact_reference_fails(self) -> None:
        pool = _good_pool()
        pool.pop("phase1_freeze_artifact_reference")
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("phase1_freeze_artifact_reference", joined)
        finally:
            os.unlink(path)

    def test_wrong_phase1_freeze_artifact_reference_fails(self) -> None:
        pool = _good_pool()
        pool["phase1_freeze_artifact_reference"] = "other/path.json"
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("phase1_freeze_artifact_reference", joined)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Banned-overclaim prose
# ---------------------------------------------------------------------------


class TestBannedLanguage(unittest.TestCase):
    def test_proof_in_summary_language_fails(self) -> None:
        pool = _good_pool()
        pool["summary"] = {
            "summary_language": "BA proof of the mechanism.",
        }
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
        finally:
            os.unlink(path)

    def test_validated_in_limitations_fails(self) -> None:
        pool = _good_pool()
        pool["limitations"].append("Mechanism is validated.")
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
        finally:
            os.unlink(path)

    def test_alpha_in_prose_fails_but_bh_alpha_key_is_fine(self) -> None:
        # "alpha" as a bare word in prose is banned, but the bh_alpha
        # field name (numeric value) must not trigger a false positive.
        pool = _good_pool()
        pool["fdr_method_note"] = "Run at fixed alpha across the pool."
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
        finally:
            os.unlink(path)

    def test_bh_alpha_token_in_prose_does_not_false_positive(self) -> None:
        # The live artifact's fdr_method_note says "q_bh <= bh_alpha".
        # The substring "alpha" appears inside "bh_alpha" but is not a
        # standalone word — \balpha\b must not match.
        pool = _good_pool()
        pool["fdr_method_note"] = (
            "Step-up procedure with monotone running-min adjustment "
            "(matches R's p.adjust(p, method='BH')). "
            "Discovery rule: q_bh <= bh_alpha."
        )
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertTrue(report["ok"], report["errors"])
        finally:
            os.unlink(path)

    def test_prediction_in_pool_role_note_fails(self) -> None:
        pool = _good_pool()
        pool["candidates"][0]["phase2_pool_role_note"] = (
            "BA confirms the prediction."
        )
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
        finally:
            os.unlink(path)

    def test_confirms_the_mechanism_phrase_fails(self) -> None:
        pool = _good_pool()
        pool["pool_lock_note"] = "Pool closure confirms the mechanism."
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
        finally:
            os.unlink(path)

    def test_fdr_pending_phrase_fails(self) -> None:
        pool = _good_pool()
        pool["limitations"].append("FDR pending downstream review.")
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
        finally:
            os.unlink(path)

    def test_hypothetical_phrase_fails(self) -> None:
        pool = _good_pool()
        pool["denominator_inclusion_note"] = (
            "All entries are hypothetical until reviewed."
        )
        path = _write_artifact(pool)
        try:
            report = cli.run_validate_phase2_pool(artifact_path=path)
            self.assertFalse(report["ok"])
        finally:
            os.unlink(path)

    def test_each_banned_token_caught_in_a_prose_field(self) -> None:
        for token in (
            "proof", "proven", "validated", "alpha",
            "prediction", "predicted",
            "confirms the mechanism", "fdr pending", "hypothetical",
        ):
            with self.subTest(token=token):
                pool = _good_pool()
                pool["pool_lock_note"] = f"This pool is {token}."
                path = _write_artifact(pool)
                try:
                    report = cli.run_validate_phase2_pool(artifact_path=path)
                    self.assertFalse(
                        report["ok"],
                        f"banned token {token!r} accepted in pool_lock_note",
                    )
                finally:
                    os.unlink(path)


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnly(unittest.TestCase):
    def test_artifact_byte_identity_preserved(self) -> None:
        pool = _good_pool()
        path = _write_artifact(pool)
        try:
            before = _sha256(path)
            cli.run_validate_phase2_pool(artifact_path=path)
            after = _sha256(path)
            self.assertEqual(
                before, after,
                "validator must not mutate the artifact file",
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Live artifact — the tracked pool must validate cleanly
# ---------------------------------------------------------------------------


class TestLiveArtifactPasses(unittest.TestCase):
    def test_live_pool_exists(self) -> None:
        self.assertTrue(
            Path(_LIVE_ARTIFACT_PATH).exists(),
            f"tracked phase2_pool_v1 missing at {_LIVE_ARTIFACT_PATH}",
        )

    def test_live_pool_validates(self) -> None:
        if not Path(_LIVE_ARTIFACT_PATH).exists():
            self.skipTest("live pool artifact not present")
        report = cli.run_validate_phase2_pool(
            artifact_path=_LIVE_ARTIFACT_PATH,
        )
        self.assertTrue(
            report["ok"],
            f"validator rejected the live pool — likely a validator "
            f"bug: {report['errors']}",
        )
        self.assertEqual(report["records_count"], 5)


# ---------------------------------------------------------------------------
# Import isolation — no paid surface bound
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_provider_attrs(self) -> None:
        for attr in ("yfinance", "anthropic", "openai", "fastapi"):
            self.assertFalse(
                hasattr(cli, attr),
                f"validator must not bind {attr} as a module attr",
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
        path = _write_artifact(_good_pool())
        try:
            rc, output = self._run(["--artifact", path, "--json"])
            parsed = json.loads(output)
            self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
            self.assertTrue(parsed["ok"], parsed.get("errors"))
            self.assertEqual(rc, 0)
        finally:
            os.unlink(path)

    def test_text_render_does_not_crash(self) -> None:
        path = _write_artifact(_good_pool())
        try:
            rc, _ = self._run(["--artifact", path])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(path)

    def test_main_returns_nonzero_when_invalid(self) -> None:
        pool = _good_pool()
        pool["artifact_type"] = "not_phase2_pool"
        path = _write_artifact(pool)
        try:
            rc, output = self._run(["--artifact", path, "--json"])
            parsed = json.loads(output)
            self.assertFalse(parsed["ok"])
            self.assertEqual(rc, 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
