"""Shared explicit opt-in gate for local/live-archive tests.

The default backend test universe must never change because an
incidental local file (most importantly a root ``events.db``) happens to
exist.  Tests that genuinely need the maintainer's local archive opt in
through this single gate:

    SECOND_ORDER_RUN_LOCAL_DATA_TESTS=1
    SECOND_ORDER_LOCAL_EVENTS_DB=<explicit path to the archive>

Contract (pinned by ``tests/test_clean_clone_test_environment.py``):

* disabled by default — both variables must be set;
* file presence alone never enables anything;
* the path is resolved and validated (must exist and be a file);
* the gate NEVER falls back to the root ``events.db`` silently — an
  operator who wants the live archive must name it explicitly;
* skip reasons state exactly which opt-in piece is missing;
* subprocesses inherit the same contract automatically (plain
  environment variables, read at call time);
* consumers must open the archive read-only (``read_only_uri`` helper).

Every function accepts an explicit ``environ`` mapping for pure unit
testing; production callers use the process environment.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

ENABLE_VAR = "SECOND_ORDER_RUN_LOCAL_DATA_TESTS"
PATH_VAR = "SECOND_ORDER_LOCAL_EVENTS_DB"


def _env(environ: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def local_data_opt_in(environ: Optional[Mapping[str, str]] = None) -> bool:
    """True only when the enable flag is explicitly ``"1"``."""
    return (_env(environ).get(ENABLE_VAR) or "").strip() == "1"


def local_events_db_or_none(
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """The explicitly declared local archive path, or ``None``.

    ``None`` whenever the opt-in flag is absent, the path variable is
    unset, or the named file does not exist.  No default, no fallback,
    no repository-root probing.
    """
    if not local_data_opt_in(environ):
        return None
    raw = (_env(environ).get(PATH_VAR) or "").strip()
    if not raw:
        return None
    path = Path(raw).resolve()
    if not path.is_file():
        return None
    return path


def local_data_skip_reason(
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """Precise reason for skipping a gated test in this environment."""
    if not local_data_opt_in(environ):
        return (
            f"local/live-archive tests are disabled by default; set "
            f"{ENABLE_VAR}=1 and {PATH_VAR}=<path> to run them"
        )
    raw = (_env(environ).get(PATH_VAR) or "").strip()
    if not raw:
        return (
            f"{ENABLE_VAR}=1 but {PATH_VAR} is unset; refusing to fall "
            f"back to the root events.db — declare the path explicitly"
        )
    path = Path(raw).resolve()
    if not path.is_file():
        return f"{PATH_VAR} does not exist or is not a file: {path}"
    return "local data gate satisfied"


def read_only_uri(path: Path) -> str:
    """SQLite URI opening the gated archive strictly read-only."""
    return f"file:{path}?mode=ro"


__all__ = (
    "ENABLE_VAR",
    "PATH_VAR",
    "local_data_opt_in",
    "local_events_db_or_none",
    "local_data_skip_reason",
    "read_only_uri",
)
