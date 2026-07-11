"""T3A — order-independence of the paid-analysis guard tests.

``test_admin_guard.PaidAnalysisGuardUnit.test_inert_when_unconfigured``
passed standalone but ERRORED in full ``unittest discover`` runs.  Building
the discovery suite imports every test module before any test runs, and
``tests/test_analyze_retry.py`` used to assign a fake non-placeholder
``ANTHROPIC_API_KEY`` at module level (import time).  The fail-closed guard
then saw a "billable" key while the admin token was unconfigured and
correctly raised 403 — the guard was right, the test ordering was broken.
``tearDownModule`` could not contain the leak: it runs only after that
module's *tests*, which sort long after test_admin_guard.

These tests pin the corrected contract:

  * the retry module confines its fake key to its own run window
    (``setUpModule``/``tearDownModule`` + ``mock.patch.dict``);
  * importing the module mutates nothing;
  * restoration is exact — a missing key stays missing, an empty key stays
    empty, a prior value comes back byte-for-byte;
  * cleanup still runs when a test body raises inside the patched window;
  * no network / provider / paid call is possible: the key is fake and
    non-billable-shaped, the provider client is fully mocked, and a DNS
    guard proves no resolution is even attempted.

Subprocess runs use ``sys.executable`` against this repo only, with the
canonical ``tests/__init__`` bootstrap (which pins ``ANTHROPIC_API_KEY``
to "") — deterministic in any parent environment.
"""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGET = "tests.test_admin_guard.PaidAnalysisGuardUnit.test_inert_when_unconfigured"
_RETRY_MODULE = "tests.test_analyze_retry"
_RETRY_FAST_TEST = "tests.test_analyze_retry.TestIsTransientError.test_overloaded_is_transient"


def _run_unittest(*names: str) -> subprocess.CompletedProcess:
    """Run ``python -m unittest <names>`` in a fresh process at repo root."""
    return subprocess.run(
        [sys.executable, "-m", "unittest", *names],
        cwd=_REPO_ROOT, capture_output=True, text=True, timeout=180,
    )


def _run_inner_suite(name: str) -> unittest.TestResult:
    """Run one test (or module) in-process; module fixtures fire normally."""
    suite = unittest.defaultTestLoader.loadTestsFromName(name)
    runner = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0)
    return runner.run(suite)


# ---------------------------------------------------------------------------
# Process-order contract — the exact contaminating sequence and its reverses.
# ---------------------------------------------------------------------------


class AdminGuardOrderIndependence(unittest.TestCase):

    def _assert_green(self, proc: subprocess.CompletedProcess) -> None:
        self.assertEqual(
            proc.returncode, 0,
            f"expected green run, got rc={proc.returncode}\n"
            f"stderr tail:\n{proc.stderr[-2000:]}",
        )

    def test_standalone_contract_clean_process(self):
        """Unconfigured paid mode stays inert in a clean process."""
        self._assert_green(_run_unittest(_TARGET))

    def test_contaminator_loaded_target_runs_first(self):
        """The exact full-discovery failure: the retry module is IMPORTED
        while the suite is built, then the target runs first.  Before the
        repair this errored with the guard's fail-closed 403."""
        self._assert_green(_run_unittest(_TARGET, _RETRY_MODULE))

    def test_contaminator_runs_before_target(self):
        """Reverse order: retry module's tests (and teardown) run first."""
        self._assert_green(_run_unittest(_RETRY_MODULE, _TARGET))

    def test_target_twice_with_contaminator_loaded(self):
        """Repeated execution in one process — identical result both times."""
        self._assert_green(_run_unittest(_TARGET, _TARGET, _RETRY_MODULE))


# ---------------------------------------------------------------------------
# Import hygiene — importing the retry module must mutate nothing.
# ---------------------------------------------------------------------------


class RetryModuleImportHygiene(unittest.TestCase):

    def test_import_does_not_mutate_environment(self):
        script = (
            "import tests\n"                      # canonical bootstrap first
            "import json, os\n"
            "before = dict(os.environ)\n"
            "import tests.test_analyze_retry\n"
            "after = dict(os.environ)\n"
            "keys = set(before) | set(after)\n"
            "delta = {k: [before.get(k), after.get(k)]\n"
            "         for k in keys if before.get(k) != after.get(k)}\n"
            "print(json.dumps(delta))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=_REPO_ROOT, capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        delta = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(
            delta, {},
            f"importing {_RETRY_MODULE} mutated os.environ: {delta}",
        )


# ---------------------------------------------------------------------------
# Run confinement — exact restoration after the module's run window.
# ---------------------------------------------------------------------------


class RetryModuleRunConfinement(unittest.TestCase):

    def test_run_restores_prior_value_exactly_and_repeatably(self):
        sentinel = "sentinel-prior-value-t3a"
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": sentinel}):
            for attempt in (1, 2):
                result = _run_inner_suite(_RETRY_FAST_TEST)
                self.assertTrue(result.wasSuccessful())
                self.assertEqual(
                    os.environ.get("ANTHROPIC_API_KEY"), sentinel,
                    f"run {attempt}: prior key value not restored exactly",
                )

    def test_run_restores_missing_key_as_missing(self):
        prior = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            result = _run_inner_suite(_RETRY_FAST_TEST)
            self.assertTrue(result.wasSuccessful())
            self.assertNotIn(
                "ANTHROPIC_API_KEY", os.environ,
                "a missing key must be restored as MISSING, not as a value",
            )
        finally:
            if prior is not None:
                os.environ["ANTHROPIC_API_KEY"] = prior


# ---------------------------------------------------------------------------
# Failure cleanup — restoration must survive a raising test body.
# ---------------------------------------------------------------------------


class RetryModuleFailureCleanup(unittest.TestCase):

    def test_cleanup_runs_when_test_body_raises(self):
        import tests.test_analyze_retry as retry_mod

        def _boom(self):  # noqa: ANN001 — unittest method signature
            raise RuntimeError("forced failure inside the patched window")

        sentinel = "sentinel-cleanup-t3a"
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": sentinel}):
            with mock.patch.object(
                retry_mod.TestIsTransientError, "test_overloaded_is_transient", _boom,
            ):
                result = _run_inner_suite(_RETRY_FAST_TEST)
            self.assertEqual(len(result.errors), 1)  # the raise happened
            self.assertEqual(
                os.environ.get("ANTHROPIC_API_KEY"), sentinel,
                "cleanup did not run after an in-test exception",
            )


# ---------------------------------------------------------------------------
# Provider safety — fake key only, and not even a DNS lookup is attempted.
# ---------------------------------------------------------------------------


class RetryModuleProviderSafety(unittest.TestCase):

    def test_fake_key_is_not_billable_shaped(self):
        import tests.test_analyze_retry as retry_mod

        fake = retry_mod._FAKE_RETRY_KEY
        self.assertTrue(fake)
        self.assertFalse(fake.startswith("sk-"),
                         "retry tests must never use a real-shaped secret")

    def test_no_name_resolution_during_full_retry_module_run(self):
        sentinel = "sentinel-net-t3a"
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": sentinel}):
            with mock.patch.object(
                socket, "getaddrinfo",
                side_effect=AssertionError("network resolution attempted"),
            ) as dns_guard:
                result = _run_inner_suite(_RETRY_MODULE)
            self.assertTrue(result.wasSuccessful())
            self.assertEqual(dns_guard.call_count, 0)
            self.assertEqual(os.environ.get("ANTHROPIC_API_KEY"), sentinel)


if __name__ == "__main__":
    unittest.main()
