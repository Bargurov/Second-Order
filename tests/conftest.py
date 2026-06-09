"""pytest collection-time entry point for the test-suite DB isolation.

Importing this file is the FIRST thing pytest does when it discovers
tests under ``tests/``.  Running the redirect at module top — before
any test fixture or test module is imported — guarantees that
modules which snapshot ``DB_FILE`` via ``from db import DB_FILE`` at
module top capture the redirected path, not the project-root
``events.db``.

A session-scoped autouse fixture below runs as belt-and-suspenders:
if anything in the test code accidentally rebinds ``db.DB_FILE`` to
the live path, the fixture re-asserts the redirect at the start of
the session.  See ``tests/_db_isolation.py`` for the full design.
"""
from __future__ import annotations

import os
import sys

# Test safety (AP1): pin a mock (empty) Anthropic key for the whole pytest
# session BEFORE any module imports ``load_dotenv()`` — otherwise the real
# ``.env`` key leaks into ``os.environ`` and the fail-closed paid-analysis
# guard 403s every tokenless /analyze test.  Mirrors tests/__init__.py for the
# unittest path.  Tests needing a real-shaped key set it locally.
os.environ["ANTHROPIC_API_KEY"] = ""

# Make the project root importable BEFORE we resolve ``tests``.  Some
# test files use ``sys.path.insert`` themselves; this just guarantees
# the early redirect path works even if pytest is invoked from a
# directory where the project isn't already on the path.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests._db_isolation import (
    redirect_db_constants,
    live_db_path,
    TEMP_DB_PATH,
)

# Run the redirect immediately at collection time.  This happens BEFORE
# any test module is imported, which is the only window that catches
# module-top ``from db import DB_FILE`` snapshots.
redirect_db_constants()


import pytest  # noqa: E402 — imported after the redirect on purpose


@pytest.fixture(autouse=True, scope="session")
def _enforce_db_isolation():
    """Re-assert the redirect at session start, then yield.

    If a test or fixture has already rebound ``db.DB_FILE`` back to
    the live path (eg by misusing the test seam), this raises before
    any test gets a chance to write to the live archive.
    """
    import db
    redirect_db_constants()
    live = os.path.realpath(live_db_path())
    actual = os.path.realpath(db.DB_FILE)
    assert actual != live, (
        f"db.DB_FILE was rebound to the live archive {live!r}; refusing "
        f"to run the test session"
    )
    yield
