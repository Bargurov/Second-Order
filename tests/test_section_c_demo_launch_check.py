"""Tests for ``scripts/section_c_demo_launch_check.py``.

The launch helper is a local pre-launch wrapper that combines:

1. A read-only inspection of the stable demo artifact bundle on
   disk (``evidence_artifacts/section_c_v1/``).
2. The seven local acceptance checks already run by
   ``scripts.run_section_c_demo_checks.run_section_c_demo_checks``.

It must be read-only:

* never start a server
* never connect to a DB or import yfinance / market_data / paid
  provider / LLM / FastAPI surfaces
* never mutate any artifact (only ``--output`` writes, and only
  when explicitly passed)

The helper tells the operator whether the demo is ready to open
and rehearse — it never claims the demo is final research
evidence.

Pinned contract:

* JSON envelope has EXACTLY these 7 keys::

    ok, demo_artifact_bundle_status, checks, failed_checks,
    warnings, errors, recommended_next_action

* ``demo_artifact_bundle_status`` carries EXACTLY::

    ok, bundle_path, expected_files, present_files,
    missing_files, reason

* ``checks`` mirrors the inner runner's per-check shape — the
  helper passes it through verbatim.

* ``failed_checks`` lists every inner check that did not pass.

* When the bundle is missing, ``ok`` is ``False`` and
  ``recommended_next_action`` points the operator at the bundle.

* When everything passes, ``recommended_next_action`` tells the
  operator to start backend + frontend and rehearse — and reminds
  them the demo is a rehearsal aid, not research evidence.

* Conservative wording — banned tokens absent from every rendered
  string.

* Source carries no DB / paid-provider / LLM / FastAPI / server-
  start surface.
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import section_c_demo_launch_check as cli  # noqa: E402


# ---------------------------------------------------------------------------
# Canonical fixtures
# ---------------------------------------------------------------------------


_REQUIRED_TOP_KEYS = (
    "ok",
    "demo_artifact_bundle_status",
    "checks",
    "failed_checks",
    "warnings",
    "errors",
    "recommended_next_action",
)


_REQUIRED_BUNDLE_KEYS = (
    "ok",
    "bundle_path",
    "expected_files",
    "present_files",
    "missing_files",
    "reason",
)


_REQUIRED_BUNDLE_FILES = (
    "analyzed_event_artifact_daily-demo-001.json",
    "analyzed_event_artifact_daily-demo-002.json",
    "analyzed_event_artifact_daily-demo-003.json",
    "freeze_candidate_evidence.json",
    "daily_reviewed_candidates.csv",
)


_REQUIRED_CHECK_IDS = (
    "demo_api_smoke",
    "no_paid_smoke",
    "frontend_typecheck",
    "frontend_build",
    "frontend_evidence_summary_panel_test",
    "frontend_section_c_demo_test",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "guaranteed",
    "automatically",
    "validated",
    "approved",
    "production ready",
    "production-ready",
    "definitely",
    # The helper checks readiness for a rehearsal — never for
    # research truth.
    "final research evidence",
    "research truth",
    "ready to ship",
    "fit to ship",
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _all_pass_envelope() -> dict[str, Any]:
    """A fake inner-runner envelope where every check passes."""
    checks: list[dict[str, Any]] = []
    for cid in _REQUIRED_CHECK_IDS:
        checks.append({
            "check_id":         cid,
            "description":      f"description for {cid}",
            "command":          ["python", "-c", "''"],
            "ok":               True,
            "returncode":       0,
            "duration_seconds": 0.01,
            "stdout_tail":      "",
            "stderr_tail":      "",
            "error":            None,
        })
    return {
        "ok":            True,
        "checks":        checks,
        "failed_checks": [],
        "warnings":      [],
        "errors":        [],
    }


def _one_fail_envelope(failing_check_id: str) -> dict[str, Any]:
    env = _all_pass_envelope()
    for entry in env["checks"]:
        if entry["check_id"] == failing_check_id:
            entry["ok"] = False
            entry["returncode"] = 1
            entry["error"] = "synthetic failure"
            entry["stderr_tail"] = "synthetic failure"
            break
    env["failed_checks"] = [failing_check_id]
    env["ok"] = False
    return env


def _make_bundle(repo_root: Path) -> Path:
    """Create the stable demo bundle inside ``repo_root``."""
    bundle = repo_root / "evidence_artifacts" / "section_c_v1"
    bundle.mkdir(parents=True, exist_ok=True)
    for name in _REQUIRED_BUNDLE_FILES:
        (bundle / name).write_text("{}", encoding="utf-8")
    return bundle


def _run(
    *,
    repo_root: Path,
    inner_envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if inner_envelope is None:
        inner_envelope = _all_pass_envelope()

    def _stub_demo_check_runner(**_kwargs: Any) -> dict[str, Any]:
        return inner_envelope

    return cli.run_section_c_demo_launch_check(
        repo_root=str(repo_root),
        demo_check_runner=_stub_demo_check_runner,
    )


def _all_strings(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for k, v in node.items():
            out.append(str(k))
            out.extend(_all_strings(v))
    elif isinstance(node, (list, tuple)):
        for item in node:
            out.extend(_all_strings(item))
    return out


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class TestEnvelopeShape(unittest.TestCase):

    def test_top_level_keys_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(repo_root=root)
        self.assertEqual(
            sorted(report.keys()), sorted(_REQUIRED_TOP_KEYS),
            f"expected {_REQUIRED_TOP_KEYS}, got {sorted(report.keys())}",
        )

    def test_ok_true_when_bundle_present_and_checks_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(repo_root=root)
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["failed_checks"], [])

    def test_bundle_status_keys_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(repo_root=root)
        bundle_status = report["demo_artifact_bundle_status"]
        self.assertIsInstance(bundle_status, dict)
        self.assertEqual(
            sorted(bundle_status.keys()),
            sorted(_REQUIRED_BUNDLE_KEYS),
            f"bundle_status keys mismatch: {sorted(bundle_status.keys())}",
        )

    def test_checks_passes_through_inner_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(repo_root=root)
        check_ids = [c["check_id"] for c in report["checks"]]
        for cid in _REQUIRED_CHECK_IDS:
            self.assertIn(cid, check_ids)


# ---------------------------------------------------------------------------
# Bundle inspection
# ---------------------------------------------------------------------------


class TestBundleInspection(unittest.TestCase):

    def test_bundle_present_marks_ok_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(repo_root=root)
        bs = report["demo_artifact_bundle_status"]
        self.assertTrue(bs["ok"])
        self.assertEqual(bs["missing_files"], [])
        self.assertEqual(
            sorted(bs["present_files"]),
            sorted(_REQUIRED_BUNDLE_FILES),
        )
        self.assertEqual(
            sorted(bs["expected_files"]),
            sorted(_REQUIRED_BUNDLE_FILES),
        )

    def test_bundle_missing_marks_ok_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # No bundle created on purpose.
            report = _run(repo_root=root)
        bs = report["demo_artifact_bundle_status"]
        self.assertFalse(bs["ok"])
        self.assertEqual(
            sorted(bs["missing_files"]),
            sorted(_REQUIRED_BUNDLE_FILES),
        )
        self.assertEqual(bs["present_files"], [])
        self.assertGreater(len(bs["reason"]), 5)
        self.assertFalse(report["ok"])

    def test_bundle_partial_marks_ok_false_with_listed_misses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _make_bundle(root)
            # Delete one of the required files.
            (bundle / "freeze_candidate_evidence.json").unlink()
            report = _run(repo_root=root)
        bs = report["demo_artifact_bundle_status"]
        self.assertFalse(bs["ok"])
        self.assertIn(
            "freeze_candidate_evidence.json", bs["missing_files"],
        )
        self.assertFalse(report["ok"])

    def test_bundle_path_is_under_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(repo_root=root)
        bs = report["demo_artifact_bundle_status"]
        self.assertIn("evidence_artifacts", bs["bundle_path"])
        self.assertIn("section_c_v1", bs["bundle_path"])


# ---------------------------------------------------------------------------
# Failure surfacing
# ---------------------------------------------------------------------------


class TestFailureSurfacing(unittest.TestCase):

    def test_failed_check_marks_envelope_not_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(
                repo_root=root,
                inner_envelope=_one_fail_envelope("frontend_build"),
            )
        self.assertFalse(report["ok"])
        self.assertIn("frontend_build", report["failed_checks"])

    def test_failed_check_appears_in_failed_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(
                repo_root=root,
                inner_envelope=_one_fail_envelope("demo_api_smoke"),
            )
        self.assertEqual(
            report["failed_checks"], ["demo_api_smoke"],
        )

    def test_bundle_failure_alone_does_not_falsify_checks_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # No bundle → bundle failure, but inner checks all pass.
            report = _run(repo_root=root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["failed_checks"], [])
        check_ids = [c["check_id"] for c in report["checks"]]
        for cid in _REQUIRED_CHECK_IDS:
            self.assertIn(cid, check_ids)


# ---------------------------------------------------------------------------
# Recommended next action
# ---------------------------------------------------------------------------


class TestRecommendedNextAction(unittest.TestCase):

    def test_all_clear_mentions_start_backend_and_frontend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(repo_root=root)
        action = report["recommended_next_action"].lower()
        self.assertIn("backend", action)
        self.assertIn("frontend", action)
        self.assertIn("rehearse", action)

    def test_all_clear_reminds_demo_is_a_rehearsal_not_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(repo_root=root)
        action = report["recommended_next_action"].lower()
        # The helper must remind the operator the demo is a rehearsal
        # aid, not research truth.
        self.assertTrue(
            "rehearsal" in action or "demo aid" in action
            or "not research" in action or "demo input" in action,
            f"recommended_next_action does not flag the demo as "
            f"a rehearsal aid: {report['recommended_next_action']!r}",
        )

    def test_missing_bundle_action_points_at_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = _run(repo_root=root)
        action = report["recommended_next_action"].lower()
        self.assertIn("bundle", action)
        self.assertIn("evidence_artifacts", action)

    def test_failed_check_action_points_at_failed_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(
                repo_root=root,
                inner_envelope=_one_fail_envelope("frontend_build"),
            )
        action = report["recommended_next_action"].lower()
        self.assertIn("frontend_build", action)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):

    def test_banned_tokens_absent_from_every_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            report = _run(repo_root=root)
        for s in _all_strings(report):
            lower = s.lower()
            for banned in _BANNED_WORDS:
                self.assertNotIn(
                    banned, lower,
                    f"banned token {banned!r} in string: {s!r}",
                )

    def test_banned_tokens_absent_when_bundle_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = _run(repo_root=root)
        for s in _all_strings(report):
            lower = s.lower()
            for banned in _BANNED_WORDS:
                self.assertNotIn(
                    banned, lower,
                    f"banned token {banned!r} in string: {s!r}",
                )


# ---------------------------------------------------------------------------
# Read-only — source-level assertions
# ---------------------------------------------------------------------------


class TestReadOnlySourceLevel(unittest.TestCase):

    def _source(self) -> str:
        path = (
            Path(__file__).resolve().parents[1]
            / "scripts" / "section_c_demo_launch_check.py"
        )
        return path.read_text(encoding="utf-8")

    def test_source_has_no_db_or_paid_or_llm_surface(self) -> None:
        text = self._source().lower()
        for banned in (
            "import yfinance",
            "from yfinance",
            "import market_data",
            "from market_data",
            "from fastapi",
            "import fastapi",
            "openai",
            "anthropic",
            "sqlite3.connect",
            "engine.connect(",
        ):
            self.assertNotIn(
                banned, text,
                f"forbidden surface seen in script: {banned!r}",
            )

    def test_source_has_no_server_start_call_site(self) -> None:
        text = self._source()
        # The runbook the helper delegates to never starts a server;
        # the helper itself must not either.
        for banned in (
            "uvicorn.run",
            "uvicorn run",
            ".serve(",
            "TestClient(",
            "subprocess.Popen",
        ):
            self.assertNotIn(
                banned, text,
                f"forbidden server-start call site seen: {banned!r}",
            )

    def test_source_has_no_artifact_mutation_call_site(self) -> None:
        text = self._source()
        # The helper inspects the bundle read-only; it must not
        # write, copy, or delete anything inside ``evidence_artifacts/``
        # or ``artifacts/``.
        for banned in (
            "shutil.copy(",
            "shutil.copytree(",
            "shutil.move(",
            "shutil.rmtree(",
            "os.remove(",
            "os.unlink(",
            ".unlink(",
            "Path.unlink",
        ):
            self.assertNotIn(
                banned, text,
                f"forbidden mutation call site seen: {banned!r}",
            )


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):

    def test_main_json_exit_zero_when_all_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            buf = StringIO()
            rc = cli.main(
                ["--json", "--repo-root", str(root)],
                out=buf,
                demo_check_runner=lambda **_: _all_pass_envelope(),
            )
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(
                sorted(payload.keys()), sorted(_REQUIRED_TOP_KEYS),
            )
            self.assertTrue(payload["ok"])

    def test_main_exit_one_when_bundle_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            buf = StringIO()
            rc = cli.main(
                ["--json", "--repo-root", str(root)],
                out=buf,
                demo_check_runner=lambda **_: _all_pass_envelope(),
            )
            self.assertEqual(rc, 1)
            payload = json.loads(buf.getvalue())
            self.assertFalse(payload["ok"])

    def test_main_exit_one_when_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            buf = StringIO()
            rc = cli.main(
                ["--json", "--repo-root", str(root)],
                out=buf,
                demo_check_runner=lambda **_: _one_fail_envelope("no_paid_smoke"),
            )
            self.assertEqual(rc, 1)
            payload = json.loads(buf.getvalue())
            self.assertFalse(payload["ok"])
            self.assertIn("no_paid_smoke", payload["failed_checks"])

    def test_text_render_mentions_bundle_and_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_bundle(root)
            buf = StringIO()
            rc = cli.main(
                ["--repo-root", str(root)],
                out=buf,
                demo_check_runner=lambda **_: _all_pass_envelope(),
            )
            self.assertEqual(rc, 0)
            text = buf.getvalue().lower()
            self.assertIn("bundle", text)
            for cid in _REQUIRED_CHECK_IDS:
                self.assertIn(cid, text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
