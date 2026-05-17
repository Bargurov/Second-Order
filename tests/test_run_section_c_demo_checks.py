"""Tests for ``scripts/run_section_c_demo_checks.py``.

The runbook script aggregates six demo-acceptance checks an operator
runs locally before the Section C demo rehearsal:

* ``demo_api_smoke``           — ``python scripts/demo_api_smoke.py --json``
* ``no_paid_smoke``            — ``python scripts/no_paid_smoke.py --json``
* ``frontend_typecheck``       — ``npm run typecheck`` in ``frontend/``
* ``frontend_build``           — ``npm run build``     in ``frontend/``
* ``frontend_evidence_summary_panel_test`` — vitest filter on the
  evidence-summary-panel test file
* ``frontend_section_c_demo_test``         — vitest filter on the
  section-c-demo page test file

Pinned by these tests:

* Top-level envelope keys: ``ok``, ``checks``, ``failed_checks``,
  ``warnings``, ``errors`` — exactly these five.
* Every check entry carries: ``check_id``, ``description``,
  ``command``, ``ok``, ``returncode``, ``duration_seconds``,
  ``stdout_tail``, ``stderr_tail``, ``error``.
* The six pinned check_ids are present in the configured order.
* ``failed_checks`` is a list of ``check_id`` strings.
* All-pass case → ``ok == True`` and ``failed_checks == []`` and CLI
  exit code 0.
* Any failed sub-command → ``ok == False``, the failing id lands in
  ``failed_checks``, and CLI exit code is 1.
* Missing tooling (FileNotFoundError from the seam) → check lands as
  failed with ``error`` populated; the script does not crash.
* Conservative wording — banned tokens absent from any rendered output.
* No DB / yfinance / market_data / paid provider / LLM / FastAPI seam
  is imported at module load.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import run_section_c_demo_checks as cli  # noqa: E402


_REQUIRED_TOP_KEYS = (
    "ok",
    "checks",
    "failed_checks",
    "warnings",
    "errors",
)


_CHECK_KEYS = (
    "check_id",
    "description",
    "command",
    "ok",
    "returncode",
    "duration_seconds",
    "stdout_tail",
    "stderr_tail",
    "error",
)


_EXPECTED_CHECK_IDS = (
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
    "alpha generated",
    "correct ticker",
    "definitely",
    "approved",
    "production ready",
    "production-ready",
    "demo_ready",
    "demo-ready",
)


_OK_RESULT = {
    "ok":               True,
    "returncode":       0,
    "duration_seconds": 0.01,
    "stdout_tail":      "",
    "stderr_tail":      "",
    "error":            None,
}


def _make_pass_runner():
    """Return a fake ``_run_command`` that reports success for every
    command and records call order so tests can assert behaviour.
    """
    calls: list[dict[str, Any]] = []

    def fake(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return dict(_OK_RESULT)

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


def _make_failing_runner(failing_check_id: str, *, error: str | None = None):
    """Return a fake runner that fails exactly one ``check_id``."""
    calls: list[dict[str, Any]] = []

    def fake(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        if kwargs.get("check_id") == failing_check_id:
            return {
                "ok":               False,
                "returncode":       1,
                "duration_seconds": 0.02,
                "stdout_tail":      "boom",
                "stderr_tail":      "stderr boom",
                "error":            error,
            }
        return dict(_OK_RESULT)

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class EnvelopeShapeTests(unittest.TestCase):

    def test_envelope_carries_exactly_required_top_keys(self) -> None:
        with patch.object(cli, "_run_command", side_effect=_make_pass_runner()):
            env = cli.run_section_c_demo_checks()
        self.assertEqual(set(env.keys()), set(_REQUIRED_TOP_KEYS))

    def test_envelope_check_ids_appear_in_pinned_order(self) -> None:
        with patch.object(cli, "_run_command", side_effect=_make_pass_runner()):
            env = cli.run_section_c_demo_checks()
        ids = tuple(c["check_id"] for c in env["checks"])
        self.assertEqual(ids, _EXPECTED_CHECK_IDS)

    def test_each_check_entry_carries_required_keys(self) -> None:
        with patch.object(cli, "_run_command", side_effect=_make_pass_runner()):
            env = cli.run_section_c_demo_checks()
        for entry in env["checks"]:
            self.assertEqual(
                set(entry.keys()),
                set(_CHECK_KEYS),
                msg=f"check {entry.get('check_id')!r} key drift",
            )

    def test_check_command_is_a_non_empty_string_list(self) -> None:
        with patch.object(cli, "_run_command", side_effect=_make_pass_runner()):
            env = cli.run_section_c_demo_checks()
        for entry in env["checks"]:
            cmd = entry["command"]
            self.assertIsInstance(cmd, list)
            self.assertGreater(len(cmd), 0)
            for arg in cmd:
                self.assertIsInstance(arg, str)
                self.assertGreater(len(arg), 0)


# ---------------------------------------------------------------------------
# All-pass / failure aggregation
# ---------------------------------------------------------------------------


class AggregationTests(unittest.TestCase):

    def test_all_pass_sets_ok_true_and_empty_failed_checks(self) -> None:
        with patch.object(cli, "_run_command", side_effect=_make_pass_runner()):
            env = cli.run_section_c_demo_checks()
        self.assertTrue(env["ok"])
        self.assertEqual(env["failed_checks"], [])
        self.assertEqual(env["errors"], [])

    def test_single_failure_flips_ok_and_lifts_check_id(self) -> None:
        runner = _make_failing_runner("frontend_typecheck")
        with patch.object(cli, "_run_command", side_effect=runner):
            env = cli.run_section_c_demo_checks()
        self.assertFalse(env["ok"])
        self.assertIn("frontend_typecheck", env["failed_checks"])
        # The other five remain absent from failed_checks.
        for other in _EXPECTED_CHECK_IDS:
            if other == "frontend_typecheck":
                continue
            self.assertNotIn(other, env["failed_checks"])

    def test_every_check_can_fail(self) -> None:
        for cid in _EXPECTED_CHECK_IDS:
            runner = _make_failing_runner(cid)
            with patch.object(cli, "_run_command", side_effect=runner):
                env = cli.run_section_c_demo_checks()
            self.assertFalse(
                env["ok"],
                msg=f"failure of {cid!r} did not flip ok=False",
            )
            self.assertEqual(
                env["failed_checks"],
                [cid],
                msg=f"failed_checks drift for {cid!r}",
            )

    def test_failed_checks_is_a_list_of_strings(self) -> None:
        runner = _make_failing_runner("no_paid_smoke")
        with patch.object(cli, "_run_command", side_effect=runner):
            env = cli.run_section_c_demo_checks()
        self.assertIsInstance(env["failed_checks"], list)
        for entry in env["failed_checks"]:
            self.assertIsInstance(entry, str)


# ---------------------------------------------------------------------------
# Missing tooling
# ---------------------------------------------------------------------------


class MissingToolingTests(unittest.TestCase):

    def test_filenotfound_does_not_crash_and_marks_check_failed(self) -> None:
        """If ``_run_command`` reports a missing executable, the runbook
        still emits a well-shaped envelope and the affected check is
        marked failed with an ``error`` string."""
        def fake(**kwargs: Any) -> dict[str, Any]:
            if kwargs.get("check_id") == "frontend_build":
                return {
                    "ok":               False,
                    "returncode":       None,
                    "duration_seconds": 0.0,
                    "stdout_tail":      "",
                    "stderr_tail":      "",
                    "error":            "command not found: npm",
                }
            return dict(_OK_RESULT)

        with patch.object(cli, "_run_command", side_effect=fake):
            env = cli.run_section_c_demo_checks()

        self.assertFalse(env["ok"])
        self.assertIn("frontend_build", env["failed_checks"])
        entry = next(c for c in env["checks"] if c["check_id"] == "frontend_build")
        self.assertEqual(entry["returncode"], None)
        self.assertIsNotNone(entry["error"])

    def test_seam_raising_unexpected_exception_is_caught(self) -> None:
        """An unexpected exception from the seam must not escape; the
        runbook converts it into a failed check with the error string
        populated and ``ok=False`` at the envelope level."""
        def boom(**kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("seam blew up")

        with patch.object(cli, "_run_command", side_effect=boom):
            env = cli.run_section_c_demo_checks()

        self.assertFalse(env["ok"])
        # Every check failed because the seam raised on every call.
        self.assertEqual(
            sorted(env["failed_checks"]),
            sorted(_EXPECTED_CHECK_IDS),
        )
        for entry in env["checks"]:
            self.assertIsNotNone(entry["error"])


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class CliTests(unittest.TestCase):

    def test_json_output_is_valid_json(self) -> None:
        buf = StringIO()
        with patch.object(cli, "_run_command", side_effect=_make_pass_runner()):
            rc = cli.main(["--json"], out=buf)
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertTrue(parsed["ok"])

    def test_exit_code_one_when_a_check_fails(self) -> None:
        buf = StringIO()
        runner = _make_failing_runner("frontend_section_c_demo_test")
        with patch.object(cli, "_run_command", side_effect=runner):
            rc = cli.main(["--json"], out=buf)
        self.assertEqual(rc, 1)
        parsed = json.loads(buf.getvalue())
        self.assertFalse(parsed["ok"])
        self.assertIn("frontend_section_c_demo_test", parsed["failed_checks"])

    def test_text_output_when_json_flag_omitted(self) -> None:
        buf = StringIO()
        with patch.object(cli, "_run_command", side_effect=_make_pass_runner()):
            rc = cli.main([], out=buf)
        self.assertEqual(rc, 0)
        # Text output should not be JSON-parsable (it is the compact form).
        text = buf.getvalue()
        self.assertIn("demo_api_smoke", text)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class ConservativeWordingTests(unittest.TestCase):

    def test_rendered_text_carries_no_banned_tokens(self) -> None:
        buf = StringIO()
        with patch.object(cli, "_run_command", side_effect=_make_pass_runner()):
            cli.main([], out=buf)
        text = buf.getvalue().lower()
        for token in _BANNED_WORDS:
            self.assertNotIn(token, text, msg=f"banned token {token!r} appeared in text output")

    def test_rendered_json_carries_no_banned_tokens(self) -> None:
        buf = StringIO()
        with patch.object(cli, "_run_command", side_effect=_make_pass_runner()):
            cli.main(["--json"], out=buf)
        text = buf.getvalue().lower()
        for token in _BANNED_WORDS:
            self.assertNotIn(token, text, msg=f"banned token {token!r} appeared in JSON output")

    def test_module_docstring_avoids_banned_tokens(self) -> None:
        doc = (cli.__doc__ or "").lower()
        for token in _BANNED_WORDS:
            self.assertNotIn(
                token, doc,
                msg=f"banned token {token!r} appeared in module docstring",
            )


# ---------------------------------------------------------------------------
# Read-only / no-side-effect contract
# ---------------------------------------------------------------------------


class ReadOnlyContractTests(unittest.TestCase):

    def test_module_does_not_import_paid_or_provider_seams(self) -> None:
        """The runbook script must not pull any paid / provider / LLM /
        FastAPI module at import time.  This pins the read-only
        contract."""
        forbidden = (
            "yfinance",
            "market_data",
            "api",                 # FastAPI app
            "anthropic",
            "openai",
            "routes.movers",
        )
        # Confirm the module file does not statically import any of these.
        import inspect
        src = inspect.getsource(cli)
        for token in forbidden:
            self.assertNotIn(
                f"import {token}", src,
                msg=f"unexpected import of {token!r} in runbook module",
            )
            self.assertNotIn(
                f"from {token} import", src,
                msg=f"unexpected import of {token!r} in runbook module",
            )


if __name__ == "__main__":
    unittest.main()
