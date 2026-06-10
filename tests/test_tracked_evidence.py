"""Tests for ``routes/tracked_evidence.py`` and the
``GET /evidence/summary`` endpoint.

Pin the contract:

* Source module envelope has exactly the documented key set.
* ``summary`` counts match the tracked artifacts (5 / 5 / 3 / 2 / 3).
* ``phase1`` and ``phase2`` are separate top-level arrays — no flat
  combined candidate list, no cross-phase q-value field.
* Each record's key set matches
  :data:`cohort_evidence.RECORD_KEYS`; the per-record ``phase`` field
  matches the array key.
* Missing Phase 1 artifact → ``ok=False`` with a clear, path-bearing
  error; no raw exception escapes.
* Missing Phase 2 artifact → ``ok=True`` with ``phase2=[]`` and
  ``phase2_count=0``.
* Missing rejection-log summary → ``ok=True`` with
  ``deferred_count=None``.
* Source module imports only stdlib + ``cohort_evidence``; the
  forbidden modules (``db``, ``price_cache``, ``market_data``,
  ``movers_cache``, ``yfinance``, ``requests``, ``httpx``,
  ``anthropic``, ``openai``, ``api``, ``fastapi``) must not appear.
* Building the envelope does not mutate the three source artifacts
  (SHA-256 hash invariance).
* The FastAPI endpoint ``GET /evidence/summary`` is a pass-through:
  the JSON body equals what the source module returns when called
  with the same paths.
* The existing ``GET /demo/evidence-summary`` endpoint continues to
  return its v1 envelope.
* Banned overclaim tokens are absent from any prose emitted by the
  source module.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cohort_evidence  # noqa: E402
from routes import tracked_evidence  # noqa: E402


_EXPECTED_SUMMARY = {
    "phase1_count":      5,
    "phase2_count":      5,
    "phase2_pass_count": 3,
    "phase2_fail_count": 2,
    "deferred_count":    3,
}

_PHASE2_EXPECTED_PASS_TICKERS = {"BA", "ALB", "NVDA"}
_PHASE2_EXPECTED_FAIL_TICKERS = {"AMAT", "CF"}
_PHASE1_EXPECTED_TICKERS = {"WHR", "TXT", "FSLR", "RIO", "LITE"}


def _make_minimal_rejection_log(path: Path, deferred: int = 3) -> None:
    payload = {
        "summary": {
            "decision_counts": {
                "deferred_methodology_lesson": deferred,
            }
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_minimal_phase1(path: Path) -> None:
    payload = {
        "artifact_type": "freeze_candidate_evidence",
        "candidates":    [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_minimal_phase2(path: Path) -> None:
    payload = {
        "artifact_type": "phase2_pool",
        "candidates":    [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class TestEnvelopeShape(unittest.TestCase):
    def test_section_constant_is_exact(self) -> None:
        self.assertEqual(tracked_evidence.SECTION, "tracked_evidence")

    def test_schema_version_constant_is_v1(self) -> None:
        self.assertEqual(tracked_evidence.SCHEMA_VERSION, "v1")

    def test_envelope_keys_exact(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        self.assertEqual(
            set(env.keys()),
            set(tracked_evidence.ENVELOPE_KEYS),
        )

    def test_summary_keys_exact(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        self.assertEqual(
            set(env["summary"].keys()),
            set(tracked_evidence.SUMMARY_KEYS),
        )

    def test_ok_iff_no_errors_when_default_artifacts_present(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        self.assertEqual(env["ok"], env["errors"] == [])
        self.assertTrue(env["ok"])
        self.assertEqual(env["errors"], [])


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------


class TestSummaryCounts(unittest.TestCase):
    def test_summary_counts_match_tracked_artifacts(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        self.assertEqual(env["summary"], _EXPECTED_SUMMARY)

    def test_section_value(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        self.assertEqual(env["section"], "tracked_evidence")
        self.assertEqual(env["schema_version"], "v1")

    def test_phase1_array_length_matches_count(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        self.assertEqual(len(env["phase1"]), env["summary"]["phase1_count"])

    def test_phase2_array_length_matches_count(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        self.assertEqual(len(env["phase2"]), env["summary"]["phase2_count"])


# ---------------------------------------------------------------------------
# Scope separation
# ---------------------------------------------------------------------------


class TestScopeSeparation(unittest.TestCase):
    def test_phase1_and_phase2_are_separate_top_level_arrays(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        self.assertIsInstance(env["phase1"], list)
        self.assertIsInstance(env["phase2"], list)

    def test_no_flat_combined_candidate_list_key(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        flat_like_keys = {
            "candidates",
            "all_candidates",
            "rows",
            "combined",
            "combined_candidates",
            "combined_phase",
        }
        self.assertEqual(set(env.keys()) & flat_like_keys, set())

    def test_no_cross_phase_fdr_field(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        cross_phase_keys = {
            "combined_q_bh",
            "combined_denominator",
            "total_discoveries",
            "cross_phase_fdr",
            "merged_q",
            "global_q_bh",
        }
        for k in cross_phase_keys:
            self.assertNotIn(k, env)
            self.assertNotIn(k, env["summary"])

    def test_per_record_phase_matches_array_key(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        for r in env["phase1"]:
            self.assertEqual(r["phase"], cohort_evidence.PHASE1_LABEL)
        for r in env["phase2"]:
            self.assertEqual(r["phase"], cohort_evidence.PHASE2_LABEL)

    def test_no_ticker_appears_in_both_arrays(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        p1 = {r["primary_ticker"] for r in env["phase1"]}
        p2 = {r["primary_ticker"] for r in env["phase2"]}
        self.assertEqual(p1 & p2, set())

    def test_phase_ticker_sets_match_expectations(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        self.assertEqual(
            {r["primary_ticker"] for r in env["phase1"]},
            _PHASE1_EXPECTED_TICKERS,
        )
        self.assertEqual(
            {r["primary_ticker"] for r in env["phase2"]},
            _PHASE2_EXPECTED_PASS_TICKERS | _PHASE2_EXPECTED_FAIL_TICKERS,
        )
        passes = {
            r["primary_ticker"] for r in env["phase2"]
            if r["passes_bh_at_005"]
        }
        fails = {
            r["primary_ticker"] for r in env["phase2"]
            if not r["passes_bh_at_005"]
        }
        self.assertEqual(passes, _PHASE2_EXPECTED_PASS_TICKERS)
        self.assertEqual(fails, _PHASE2_EXPECTED_FAIL_TICKERS)

    def test_fdr_scope_note_is_non_empty_string(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        self.assertIsInstance(env["fdr_scope_note"], str)
        self.assertGreater(len(env["fdr_scope_note"]), 50)
        # Mentions both phases by name so machine consumers can route on it.
        self.assertIn("Phase 1", env["fdr_scope_note"])
        self.assertIn("Phase 2", env["fdr_scope_note"])


# ---------------------------------------------------------------------------
# Record normalization passthrough
# ---------------------------------------------------------------------------


class TestRecordKeys(unittest.TestCase):
    def test_records_have_cohort_evidence_record_keys(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        expected = set(cohort_evidence.RECORD_KEYS)
        for r in env["phase1"]:
            self.assertEqual(set(r.keys()), expected)
        for r in env["phase2"]:
            self.assertEqual(set(r.keys()), expected)

    def test_phase2_q_bh_values_match_pool_artifact(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        by_ticker = {r["primary_ticker"]: r["q_bh"] for r in env["phase2"]}
        self.assertAlmostEqual(by_ticker["BA"],   1.6e-07,   places=10)
        self.assertAlmostEqual(by_ticker["ALB"],  0.00011,   places=8)
        self.assertAlmostEqual(by_ticker["NVDA"], 0.0135,    places=6)
        self.assertAlmostEqual(by_ticker["AMAT"], 0.065875,  places=6)
        self.assertAlmostEqual(by_ticker["CF"],   0.161,     places=6)


# ---------------------------------------------------------------------------
# Missing-file behaviour
# ---------------------------------------------------------------------------


class TestMissingPhase1(unittest.TestCase):
    def test_missing_phase1_returns_ok_false_with_path_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bogus_phase1 = str(Path(tmp) / "absent_phase1.json")
            phase2 = Path(tmp) / "phase2.json"
            _make_minimal_phase2(phase2)
            rejection = Path(tmp) / "rejection.json"
            _make_minimal_rejection_log(rejection, deferred=0)
            env = tracked_evidence.build_tracked_evidence_summary(
                phase1_path=bogus_phase1,
                phase2_path=str(phase2),
                rejection_path=str(rejection),
            )
        self.assertFalse(env["ok"])
        self.assertTrue(env["errors"], "errors must be non-empty")
        joined = " || ".join(env["errors"])
        # Compare on the filename only — Path() repr() escapes
        # backslashes on Windows, which would mismatch a literal
        # path-string containment test.
        self.assertIn("absent_phase1.json", joined)
        self.assertIn("Phase 1", joined)
        # Envelope shape is still complete even on failure.
        self.assertEqual(
            set(env.keys()),
            set(tracked_evidence.ENVELOPE_KEYS),
        )
        self.assertEqual(env["phase1"], [])
        self.assertEqual(env["summary"]["phase1_count"], 0)

    def test_missing_phase1_no_stack_trace_escapes(self) -> None:
        """No 'Traceback' substring in any error string."""
        with tempfile.TemporaryDirectory() as tmp:
            env = tracked_evidence.build_tracked_evidence_summary(
                phase1_path=str(Path(tmp) / "absent.json"),
                phase2_path=str(Path(tmp) / "absent_phase2.json"),
                rejection_path=str(Path(tmp) / "absent_rejection.json"),
            )
        for line in env["errors"] + env["warnings"]:
            self.assertNotIn("Traceback", line)
            self.assertNotIn("File \"", line)


class TestMissingPhase2(unittest.TestCase):
    def test_missing_phase2_returns_ok_true_with_empty_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            phase1 = Path(tmp) / "phase1.json"
            _make_minimal_phase1(phase1)
            bogus_phase2 = str(Path(tmp) / "absent_phase2.json")
            rejection = Path(tmp) / "rejection.json"
            _make_minimal_rejection_log(rejection, deferred=0)
            env = tracked_evidence.build_tracked_evidence_summary(
                phase1_path=str(phase1),
                phase2_path=bogus_phase2,
                rejection_path=str(rejection),
            )
        self.assertTrue(env["ok"])
        self.assertEqual(env["errors"], [])
        self.assertEqual(env["phase2"], [])
        self.assertEqual(env["summary"]["phase2_count"], 0)
        self.assertEqual(env["summary"]["phase2_pass_count"], 0)
        self.assertEqual(env["summary"]["phase2_fail_count"], 0)


class TestMissingRejectionSummary(unittest.TestCase):
    def test_missing_rejection_returns_ok_true_with_null_deferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            phase1 = Path(tmp) / "phase1.json"
            _make_minimal_phase1(phase1)
            phase2 = Path(tmp) / "phase2.json"
            _make_minimal_phase2(phase2)
            bogus_rejection = str(Path(tmp) / "absent_rejection.json")
            env = tracked_evidence.build_tracked_evidence_summary(
                phase1_path=str(phase1),
                phase2_path=str(phase2),
                rejection_path=bogus_rejection,
            )
        self.assertTrue(env["ok"])
        self.assertIsNone(env["summary"]["deferred_count"])


# ---------------------------------------------------------------------------
# Import / module isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    """The source module must not pull in DB / cache / provider / FastAPI."""

    _ALLOWED_TOP_LEVEL_IMPORTS: frozenset[str] = frozenset({
        "__future__",
        "copy",
        "json",
        "pathlib",
        "typing",
        "cohort_evidence",
    })

    _FORBIDDEN_TOP_LEVEL_IMPORTS: tuple[str, ...] = (
        "db",
        "price_cache",
        "market_data",
        "movers_cache",
        "yfinance",
        "requests",
        "httpx",
        "anthropic",
        "openai",
        "api",
        "fastapi",
    )

    def _module_source(self) -> str:
        return Path(tracked_evidence.__file__).read_text(encoding="utf-8")

    def _observed_top_level_imports(self) -> set[str]:
        tree = ast.parse(self._module_source())
        observed: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    observed.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    observed.add(node.module.split(".")[0])
        return observed

    def test_only_whitelisted_top_level_imports(self) -> None:
        observed = self._observed_top_level_imports()
        unexpected = observed - self._ALLOWED_TOP_LEVEL_IMPORTS
        self.assertEqual(
            unexpected,
            set(),
            f"routes/tracked_evidence.py must import only the stdlib "
            f"whitelist + cohort_evidence; unexpected: {sorted(unexpected)}",
        )

    def test_forbidden_modules_not_imported(self) -> None:
        observed = self._observed_top_level_imports()
        for forbidden in self._FORBIDDEN_TOP_LEVEL_IMPORTS:
            self.assertNotIn(
                forbidden,
                observed,
                f"routes/tracked_evidence.py must not import {forbidden!r}",
            )


# ---------------------------------------------------------------------------
# Read-only hash invariance
# ---------------------------------------------------------------------------


class TestHashInvariance(unittest.TestCase):
    """Building the envelope must not mutate the source artifacts."""

    def test_default_artifacts_byte_identity_preserved(self) -> None:
        paths = [
            cohort_evidence.DEFAULT_PHASE1_PATH,
            cohort_evidence.DEFAULT_PHASE2_PATH,
            cohort_evidence.DEFAULT_REJECTION_PATH,
        ]
        before: dict[str, str] = {}
        for p in paths:
            if Path(p).exists():
                before[p] = hashlib.sha256(Path(p).read_bytes()).hexdigest()
        _ = tracked_evidence.build_tracked_evidence_summary()
        after: dict[str, str] = {}
        for p in paths:
            if Path(p).exists():
                after[p] = hashlib.sha256(Path(p).read_bytes()).hexdigest()
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Banned overclaim tokens
# ---------------------------------------------------------------------------


class TestNoOverclaimTokens(unittest.TestCase):
    """Banned tokens must not appear in any prose the source emits."""

    _BANNED_TOKENS: tuple[str, ...] = (
        "proof",
        "proven",
        "validated",
        "alpha",
        "prediction",
        "predicted",
        "interview",
        "pitch",
    )

    def _all_emitted_strings(self, env: dict[str, Any]) -> list[str]:
        out: list[str] = []
        out.append(env.get("fdr_scope_note", ""))
        out.extend(env.get("limitations", []))
        out.extend(env.get("warnings", []))
        out.extend(env.get("errors", []))
        return [s for s in out if isinstance(s, str)]

    def test_no_banned_tokens_on_good_artifacts(self) -> None:
        env = tracked_evidence.build_tracked_evidence_summary()
        for s in self._all_emitted_strings(env):
            lowered = s.lower()
            for tok in self._BANNED_TOKENS:
                self.assertNotIn(
                    f" {tok} ", f" {lowered} ",
                    f"banned token {tok!r} in emitted prose: {s!r}",
                )
            self.assertNotIn("confirms the mechanism", lowered)

    def test_no_banned_tokens_on_missing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = tracked_evidence.build_tracked_evidence_summary(
                phase1_path=str(Path(tmp) / "absent.json"),
                phase2_path=str(Path(tmp) / "absent_p2.json"),
                rejection_path=str(Path(tmp) / "absent_rej.json"),
            )
        for s in self._all_emitted_strings(env):
            lowered = s.lower()
            for tok in self._BANNED_TOKENS:
                self.assertNotIn(
                    f" {tok} ", f" {lowered} ",
                    f"banned token {tok!r} in emitted prose: {s!r}",
                )
            self.assertNotIn("confirms the mechanism", lowered)


# ---------------------------------------------------------------------------
# FastAPI endpoint smoke + isolation
# ---------------------------------------------------------------------------


class TestFastAPISmoke(unittest.TestCase):
    """In-process TestClient against ``GET /evidence/summary``."""

    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient  # noqa: PLC0415
        import api  # noqa: PLC0415
        cls._client = TestClient(api.app)
        cls._api = api

    def test_get_returns_200_and_documented_shape(self) -> None:
        resp = self._client.get("/evidence/summary")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(
            set(body.keys()),
            set(tracked_evidence.ENVELOPE_KEYS),
        )
        self.assertEqual(body["section"], "tracked_evidence")
        self.assertEqual(body["schema_version"], "v1")
        self.assertEqual(body["ok"], body["errors"] == [])

    def test_endpoint_matches_source_module_envelope(self) -> None:
        """The HTTP layer must be a pure pass-through."""
        resp = self._client.get("/evidence/summary")
        body = resp.json()
        direct = tracked_evidence.build_tracked_evidence_summary(
            phase1_path=str(
                self._api._TRACKED_EVIDENCE_DIR_DEFAULT
                / self._api._TRACKED_EVIDENCE_FREEZE_FILENAME
            ),
            phase2_path=str(
                self._api._TRACKED_EVIDENCE_DIR_DEFAULT
                / self._api._TRACKED_EVIDENCE_PHASE2_FILENAME
            ),
            rejection_path=str(
                self._api._TRACKED_EVIDENCE_DIR_DEFAULT
                / self._api._TRACKED_EVIDENCE_REJECTION_FILENAME
            ),
        )
        self.assertEqual(body, direct)

    def test_summary_counts_via_http(self) -> None:
        resp = self._client.get("/evidence/summary")
        body = resp.json()
        self.assertEqual(body["summary"], _EXPECTED_SUMMARY)


class TestExistingDemoEndpointUntouched(unittest.TestCase):
    """The existing ``/demo/evidence-summary`` must keep its v1 envelope."""

    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient  # noqa: PLC0415
        import api  # noqa: PLC0415
        cls._client = TestClient(api.app)

    def test_demo_evidence_summary_responds_200(self) -> None:
        resp = self._client.get("/demo/evidence-summary")
        self.assertEqual(resp.status_code, 200)

    def test_demo_evidence_summary_section_is_evidence_summary(self) -> None:
        """The v1 contract pins section == 'evidence_summary' — not the
        new 'tracked_evidence' value."""
        resp = self._client.get("/demo/evidence-summary")
        body = resp.json()
        self.assertEqual(body.get("section"), "evidence_summary")

    def test_demo_evidence_summary_does_not_carry_tracked_keys(self) -> None:
        """Sanity: the v1 demo envelope must not gain the new endpoint's
        keys (``phase1`` / ``phase2`` / ``fdr_scope_note``).
        """
        resp = self._client.get("/demo/evidence-summary")
        body = resp.json()
        self.assertNotIn("phase1", body)
        self.assertNotIn("phase2", body)
        self.assertNotIn("fdr_scope_note", body)


# ---------------------------------------------------------------------------
# Tracked-only enforcement: env-var override must be IGNORED
# ---------------------------------------------------------------------------


class TestTrackedOnlyEnforcement(unittest.TestCase):
    """The Phase 4 contract requires ``/evidence/summary`` to read only
    from the tracked ``evidence_artifacts/section_c_v2/`` bundle.

    The endpoint must NOT honor ``SECOND_ORDER_DEMO_ARTIFACT_DIR``.
    Setting that env var to a tempdir with different (or empty)
    artifacts must produce the same response as if the env var were
    unset — proving the override is ignored.

    The tempdir is the override target in these tests; the local
    ``artifacts/`` directory is never used as a target.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient  # noqa: PLC0415
        import api  # noqa: PLC0415
        cls._client = TestClient(api.app)
        cls._api = api

    def test_env_var_pointing_at_tempdir_is_ignored(self) -> None:
        """Set the env var to a tempdir whose artifacts (if honored)
        would produce different counts. Assert the response still
        reports the tracked-default counts (5 / 5 / 3 / 2 / 3).
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _make_minimal_phase1(
                tmp_dir / self._api._TRACKED_EVIDENCE_FREEZE_FILENAME,
            )
            _make_minimal_phase2(
                tmp_dir / self._api._TRACKED_EVIDENCE_PHASE2_FILENAME,
            )
            _make_minimal_rejection_log(
                tmp_dir / self._api._TRACKED_EVIDENCE_REJECTION_FILENAME,
                deferred=0,
            )
            with mock.patch.dict(
                os.environ,
                {self._api._DEMO_ARTIFACT_DIR_ENV_VAR: str(tmp_dir)},
            ):
                resp = self._client.get("/evidence/summary")
            body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["ok"])
        # Counts come from the tracked default, not from the tempdir.
        self.assertEqual(body["summary"], _EXPECTED_SUMMARY)

    def test_env_var_pointing_at_nonexistent_path_is_ignored(self) -> None:
        """A bogus env-var value would surface a ``not found`` error if
        the route honored it. The route must ignore the env var and
        return the tracked-default ok envelope.
        """
        bogus = str(Path(tempfile.gettempdir()) / "no-such-bundle-xyz")
        with mock.patch.dict(
            os.environ,
            {self._api._DEMO_ARTIFACT_DIR_ENV_VAR: bogus},
        ):
            resp = self._client.get("/evidence/summary")
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["summary"], _EXPECTED_SUMMARY)
        # The bogus path must not appear anywhere in the response —
        # if it did, the route had consulted the env var.
        body_str = json.dumps(body)
        self.assertNotIn(bogus, body_str)

    def test_endpoint_module_has_no_tracked_evidence_resolver(self) -> None:
        """``api._resolve_tracked_evidence_dir`` must not exist. The
        endpoint pins the directory at the tracked-default constant
        directly, so there is no resolver to honor any env var.
        """
        import api  # noqa: PLC0415
        self.assertFalse(
            hasattr(api, "_resolve_tracked_evidence_dir"),
            "_resolve_tracked_evidence_dir must not be defined; the "
            "tracked-evidence endpoint must pin evidence_artifacts/section_c_v2",
        )

    def test_tracked_default_points_at_section_c_v2(self) -> None:
        """Sanity-pin the default so a future refactor cannot silently
        repoint it.
        """
        import api  # noqa: PLC0415
        default = self._api._TRACKED_EVIDENCE_DIR_DEFAULT
        # Path object; compare on the last two segments for portability.
        parts = default.parts
        self.assertEqual(parts[-2], "evidence_artifacts")
        self.assertEqual(parts[-1], "section_c_v2")

    def test_env_var_does_not_make_route_read_local_artifacts(self) -> None:
        """Belt-and-suspenders: even if a future regression made the
        route honor the env var, pointing it at a path that does NOT
        exist on disk must still not silently fall back to the local
        ``artifacts/`` directory. We assert that no ``artifacts/``
        path is referenced in the response body.
        """
        bogus = str(Path(tempfile.gettempdir()) / "tracked-route-canary")
        with mock.patch.dict(
            os.environ,
            {self._api._DEMO_ARTIFACT_DIR_ENV_VAR: bogus},
        ):
            resp = self._client.get("/evidence/summary")
        body_str = json.dumps(resp.json())
        # The route should never reference the local artifacts/ tree.
        self.assertNotIn("artifacts/freeze_candidate_evidence.json", body_str)
        self.assertNotIn("artifacts\\freeze_candidate_evidence.json", body_str)


if __name__ == "__main__":
    unittest.main()
