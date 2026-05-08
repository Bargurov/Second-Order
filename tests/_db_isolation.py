"""Test-suite DB-isolation helper.

Redirects ``db.DB_FILE`` (and any module-top snapshot of it carried by
``macro_release_facts``, ``macro_surprises``, ``saved_studies``) to a
per-process temp path so a stray ``init_db()``, raw
``sqlite3.connect(db.DB_FILE)``, or FastAPI ``TestClient`` lifespan
cannot mutate the project-root ``events.db``.

The redirect is invoked from BOTH:

* ``tests/conftest.py``  — pytest collection-time entry point
* ``tests/__init__.py``  — ``python -m unittest tests.<X>`` entry point

Either path lands in the same idempotent :func:`redirect_db_constants`
so a mixed pytest+unittest workflow stays consistent.

What this module is NOT
-----------------------
* Not a per-test DB.  Tests that need a clean per-test DB still
  create their own temp file and swap ``db.DB_FILE`` (existing
  pattern); this module's job is only to make the *baseline*
  ``db.DB_FILE`` safe so tests that forget to swap don't accidentally
  hit the live archive.
* Not a writer.  We never call ``init_db()`` or ``sqlite3.connect``
  ourselves — that's the test's job.
* Not a deleter.  We never touch the live ``events.db``.
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path


__all__ = (
    "TEMP_DB_DIR",
    "TEMP_DB_PATH",
    "redirect_db_constants",
    "live_db_path",
)


_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _make_temp_db_dir() -> Path:
    """Per-process temp directory.

    Uses pid + a module-level uuid so a single ``pytest`` or
    ``unittest`` run gets a stable directory across all tests in that
    session, but two parallel runs cannot collide.
    """
    suffix = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    out = Path(tempfile.gettempdir()) / f"geo_mechanism_test_session_{suffix}"
    out.mkdir(parents=True, exist_ok=True)
    return out


TEMP_DB_DIR:  Path = _make_temp_db_dir()
TEMP_DB_PATH: str  = str(TEMP_DB_DIR / "events.db")


# Modules that snapshot ``DB_FILE`` at module top-level via
# ``from db import DB_FILE``.  Listed explicitly (not discovered by
# scanning ``sys.modules``) so we don't accidentally rebind a
# legitimately different ``DB_FILE`` attribute owned by some unrelated
# module — and so adding a new snapshot site is a deliberate edit here.
_SNAPSHOT_MODULES: tuple[str, ...] = (
    "macro_release_facts",
    "macro_surprises",
    "saved_studies",
)


_REDIRECTED: bool = False


def live_db_path() -> str:
    """Project-root ``events.db`` (the file we MUST NOT touch)."""
    return str(_PROJECT_ROOT / "events.db")


def redirect_db_constants() -> str:
    """Point ``db.DB_FILE`` at :data:`TEMP_DB_PATH` and re-bind the
    snapshot-module copies.  Idempotent — repeat calls are no-ops.

    Returns the redirected path so a caller that wants to log it can.
    """
    global _REDIRECTED
    if _REDIRECTED:
        return TEMP_DB_PATH

    # Make sure the project root is on ``sys.path`` so ``import db``
    # resolves to the live module (test files already do this, but a
    # bare ``python -m unittest tests.<X>`` invocation may not have
    # added the root yet by the time __init__.py runs).
    root_str = str(_PROJECT_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    import db  # noqa: E402 — deliberate late import; see comment above
    db.DB_FILE = TEMP_DB_PATH
    # ``_db_ready`` is the gate save_event / load_recent_events check
    # before touching the DB.  init_db() flips it; we reset to False
    # so a test that has not yet called init_db() against the
    # redirected path doesn't accidentally read with the old flag.
    db._db_ready = False

    # If any of the snapshot modules were already imported (eg pytest
    # collected a test module that pulled them in before the conftest
    # ran), rebind their cached ``DB_FILE`` so they too see the temp
    # path.  Modules that have not yet been imported will pick up the
    # new ``db.DB_FILE`` automatically when they finally do.
    for mod_name in _SNAPSHOT_MODULES:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "DB_FILE"):
            setattr(mod, "DB_FILE", TEMP_DB_PATH)

    _REDIRECTED = True
    return TEMP_DB_PATH
