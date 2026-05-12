"""Shared helper for testing module-level import isolation under full
unittest discovery.

The naive in-process check ``set(sys.modules.keys()) & banned`` is
brittle: when an earlier test in the same discovery process imports
``routes.movers`` or ``api`` (which load FastAPI), those keys stay
in ``sys.modules`` for every later test.  A later "this module does
not pull in FastAPI" test then reads the polluted ``sys.modules``
and fails — even when the module under test has no FastAPI import
in its own source or transitive chain.

This helper runs the import in a *fresh Python subprocess* so the
``sys.modules`` snapshot the check reads measures only what the
target module's import actually pulled in.  No prior in-process
pollution can affect the result, so the assertion is robust under
full discovery and under single-test isolation.

The subprocess inherits ``PYTHONPATH`` set to the project root so
the target module resolves cleanly without depending on the test
runner's working directory.

This module imports stdlib only (``json``, ``os``, ``subprocess``,
``sys``) — no FastAPI, no provider, no LLM.  Tests can import this
helper without affecting their own import-isolation invariants.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Iterable


_PROJECT_ROOT: str = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)


def assert_module_import_does_not_leak(
    test_case,
    *,
    module_name:         str,
    blocked:             Iterable[str] = ("yfinance", "fastapi", "api"),
    blocked_starts_with: Iterable[str] = ("routes.",),
    extra_pre_import:    str = "",
    extra_post_check:    str = "",
) -> dict[str, list[str]]:
    """Import ``module_name`` in a fresh Python subprocess and assert
    that no banned module ends up in ``sys.modules``.

    Parameters
    ----------
    test_case:
        The ``unittest.TestCase`` instance the assertion belongs to.
        Used for ``test_case.fail`` and ``test_case.assertEqual`` so
        failure messages route through the standard unittest report.
    module_name:
        Fully-qualified name of the module to import — for example
        ``"scripts.combined_reviewed_evidence_report"`` or
        ``"scripts.xle_online_backfill_preview"``.
    blocked:
        Bare module names that must not end up in ``sys.modules``.
        Both exact matches and submodule matches (``yfinance.foo``)
        are flagged.  Defaults to ``("yfinance", "fastapi", "api")``.
    blocked_starts_with:
        Module-name prefixes that must not end up in ``sys.modules``.
        Defaults to ``("routes.",)`` so any ``routes.movers`` /
        ``routes.events`` import is caught.
    extra_pre_import:
        Python statements run BEFORE the target import.  Useful for
        tests that want to import a sibling module first (for
        example, a fixture that should NOT be loaded by the target).
        The leaked-modules check still excludes prefixes the helper
        adds itself; if a caller's pre-import legitimately adds a
        prefix that should be allowed, pass an explicit
        ``blocked_starts_with`` override that excludes it.
    extra_post_check:
        Python statements run AFTER the target import and AFTER
        printing the leaked-modules JSON line.  Useful for tests
        that want to additionally invoke the imported module's
        public API and confirm it still doesn't pull anything in.

    Returns
    -------
    ``{"leaked": [...], "modules": [...]}``
        ``leaked`` is the sorted list of banned modules found in the
        subprocess's ``sys.modules``; the helper asserts this is
        empty, but the return value is exposed for callers that want
        to make additional assertions.
    """
    blocked_list   = tuple(blocked)
    prefix_list    = tuple(blocked_starts_with)

    code = (
        "import json, sys\n"
        f"{extra_pre_import}\n"
        f"import {module_name}  # noqa\n"
        f"_BLOCKED  = {blocked_list!r}\n"
        f"_PREFIXES = {prefix_list!r}\n"
        "leaked = sorted({\n"
        "    k for k in sys.modules\n"
        "    if k in _BLOCKED\n"
        "    or any(k.startswith(b + '.') for b in _BLOCKED)\n"
        "    or any(k.startswith(p) for p in _PREFIXES)\n"
        "})\n"
        "print('IIC:' + json.dumps({'leaked': leaked}))\n"
        f"{extra_post_check}\n"
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = _PROJECT_ROOT
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        cwd=_PROJECT_ROOT, env=env,
    )
    if result.returncode != 0:
        test_case.fail(
            f"subprocess failed to import {module_name!r}: "
            f"rc={result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    # Parse the LAST ``IIC:`` line in the subprocess's stdout so an
    # ``extra_post_check`` that re-runs the leaked-modules scan after
    # invoking the target module's public API can override the
    # initial post-import scan.  Callers that don't pass
    # ``extra_post_check`` just see the single import-time scan line.
    payload: dict[str, list[str]] | None = None
    for line in result.stdout.splitlines():
        if line.startswith("IIC:"):
            try:
                payload = json.loads(line[len("IIC:"):])
            except ValueError:
                continue
    if payload is None:
        test_case.fail(
            f"could not parse import-isolation payload from "
            f"subprocess output for {module_name!r}: "
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    test_case.assertEqual(
        payload.get("leaked"), [],
        f"importing {module_name!r} leaked banned modules into a "
        f"fresh subprocess's sys.modules: "
        f"{payload.get('leaked')!r}",
    )
    return payload


__all__ = ("assert_module_import_does_not_leak",)
