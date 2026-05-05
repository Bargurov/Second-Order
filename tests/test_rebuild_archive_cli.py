"""Tests pinning the safety contract of ``scripts/rebuild_archive.py``.

The CLI is a thin wrapper around
``archive_rebuild.run_archive_rebuild`` (which already has direct
unit coverage in ``tests/test_archive_rebuild.py``).  These tests
focus on the *operator-facing* surface — the bits that protect a
careless invocation from mutating the archive:

  1. ``--help`` exits with code 0 and produces usage text.
  2. The default invocation (no flags) propagates ``write=False`` to
     the composer.  A dry-run report is built, and the persist seam
     is never asked to fire.
  3. ``--write`` propagates ``write=True``.  This is the only path a
     real archive mutation can take.

Hermetic by design: ``_load_events`` and ``run_archive_rebuild`` are
both patched so the test never touches SQLite, never imports
``frozen_overlay_refresh``, and never reaches the price-cache /
provider seams (yfinance, anthropic, openai).  The exit-code
contract is asserted directly off ``main()``'s return value.
"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "rebuild_archive.py"
)


def _load_script_module():
    """Load ``scripts/rebuild_archive.py`` as a module without requiring
    ``scripts/`` to be a Python package.  A fresh module per test keeps
    monkeypatched imports isolated.
    """
    spec = importlib.util.spec_from_file_location(
        "rebuild_archive_cli_under_test", str(_SCRIPT_PATH),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestHelpFlag(unittest.TestCase):
    def test_help_exits_cleanly(self) -> None:
        module = _load_script_module()
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                module.main(["--help"])
        # argparse exits 0 on --help.
        self.assertEqual(cm.exception.code, 0)
        out = buf.getvalue()
        self.assertIn("usage:", out)
        # Surface the safety semantics in the help text — operators
        # reading ``--help`` should immediately see the dry-run default.
        self.assertIn("--write", out)
        self.assertIn("dry-run", out.lower())


class TestDryRunIsDefault(unittest.TestCase):
    """The default invocation must propagate ``write=False`` to the
    composer.  We patch the composer entry point so the assertion is
    independent of any composer-side filter or eligibility plumbing.
    """

    def test_default_invocation_calls_run_with_write_false(self) -> None:
        module = _load_script_module()
        fake_report = {
            "dry_run":    True,
            "write":      {"attempted": 0, "written": 0, "errored": 0,
                           "results": []},
            "validation": {"counts": {}, "by_reason": {}, "samples": {},
                           "rows": []},
            "selection":  {"filter": {}, "total_considered": 0,
                           "candidate_count": 0},
            "operation":  "overlays",
            "generated_at": "2026-05-05T00:00:00",
        }
        with patch.object(module, "_load_events", return_value=[]) as load_mock, \
             patch.object(module, "run_archive_rebuild",
                          return_value=fake_report) as run_mock, \
             redirect_stdout(io.StringIO()):
            # Pass an explicit no-op flag (default operation) instead of
            # ``[]`` — ``main()``'s ``argv or sys.argv[1:]`` collapses an
            # empty list back to ``sys.argv``, so a literal ``[]`` would
            # pick up the unittest harness's own argv.  Functionally
            # identical to "no flags" for the dry-run-default contract.
            rc = module.main(["--operation", "overlays"])
        self.assertEqual(rc, 0)
        load_mock.assert_called_once()
        run_mock.assert_called_once()
        kwargs = run_mock.call_args.kwargs
        self.assertIn("write", kwargs)
        self.assertFalse(
            kwargs["write"],
            "default invocation must propagate write=False to the composer",
        )

    def test_write_flag_propagates_write_true(self) -> None:
        module = _load_script_module()
        fake_report = {
            "dry_run":    False,
            "write":      {"attempted": 0, "written": 0, "errored": 0,
                           "results": []},
            "validation": {"counts": {}, "by_reason": {}, "samples": {},
                           "rows": []},
            "selection":  {"filter": {}, "total_considered": 0,
                           "candidate_count": 0},
            "operation":  "overlays",
            "generated_at": "2026-05-05T00:00:00",
        }
        with patch.object(module, "_load_events", return_value=[]), \
             patch.object(module, "run_archive_rebuild",
                          return_value=fake_report) as run_mock, \
             redirect_stdout(io.StringIO()):
            rc = module.main(["--write"])
        self.assertEqual(rc, 0)
        kwargs = run_mock.call_args.kwargs
        self.assertTrue(
            kwargs["write"],
            "--write must propagate write=True to the composer",
        )


class TestExitCode(unittest.TestCase):
    """Pin the documented exit-code contract — CI / shell wrappers
    branch on the integer rather than parsing markdown.
    """

    def test_dry_run_exits_zero_even_when_validation_lists_failures(
        self,
    ) -> None:
        module = _load_script_module()
        # A dry-run with composer rejections should still exit 0:
        # nothing was written, so there's no remediation to flag.
        report = {
            "dry_run":    True,
            "write":      {"attempted": 0, "written": 0, "errored": 0,
                           "results": []},
            "validation": {"counts": {"eligible": 0, "ineligible": 3},
                           "by_reason": {}, "samples": {}, "rows": []},
            "selection":  {"filter": {}, "total_considered": 3,
                           "candidate_count": 3},
            "operation":  "overlays",
            "generated_at": "2026-05-05T00:00:00",
        }
        with patch.object(module, "_load_events", return_value=[]), \
             patch.object(module, "run_archive_rebuild", return_value=report), \
             redirect_stdout(io.StringIO()):
            # Pass an explicit no-op flag (default operation) instead of
            # ``[]`` — ``main()``'s ``argv or sys.argv[1:]`` collapses an
            # empty list back to ``sys.argv``, so a literal ``[]`` would
            # pick up the unittest harness's own argv.  Functionally
            # identical to "no flags" for the dry-run-default contract.
            rc = module.main(["--operation", "overlays"])
        self.assertEqual(rc, 0)

    def test_write_exits_nonzero_when_any_event_errored(self) -> None:
        module = _load_script_module()
        report = {
            "dry_run":    False,
            "write":      {"attempted": 2, "written": 1, "errored": 1,
                           "results": []},
            "validation": {"counts": {}, "by_reason": {}, "samples": {},
                           "rows": []},
            "selection":  {"filter": {}, "total_considered": 2,
                           "candidate_count": 2},
            "operation":  "overlays",
            "generated_at": "2026-05-05T00:00:00",
        }
        with patch.object(module, "_load_events", return_value=[]), \
             patch.object(module, "run_archive_rebuild", return_value=report), \
             redirect_stdout(io.StringIO()):
            rc = module.main(["--write"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
