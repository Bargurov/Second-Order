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
* Not a schema writer.  We never call ``init_db()`` ourselves; that's
  the test's job.  We do create the redirected temp SQLite file so
  filesystem preflights can validate the safe path without falling
  back to the live archive.
* Not a deleter.  We never touch the live ``events.db``.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path


__all__ = (
    "TEMP_DB_DIR",
    "TEMP_DB_PATH",
    "TEMPFILE_TEMP_DIR",
    "redirect_db_constants",
    "live_db_path",
)


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SESSION_SUFFIX = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
_TEST_TEMP_ROOT = _PROJECT_ROOT / "tests" / f"test_events_session_{_SESSION_SUFFIX}"
_ORIGINAL_MKDTEMP = tempfile.mkdtemp
_MKDTEMP_PATCHED = False
_YFINANCE_PATCHED = False


def _make_temp_db_dir() -> Path:
    """Per-process temp directory.

    Uses pid + a module-level uuid so a single ``pytest`` or
    ``unittest`` run gets a stable directory across all tests in that
    session, but two parallel runs cannot collide.
    """
    out = _TEST_TEMP_ROOT / "db"
    out.mkdir(parents=True, exist_ok=True)
    return out


TEMP_DB_DIR:  Path = _make_temp_db_dir()
TEMP_DB_PATH: str  = str(TEMP_DB_DIR / "events.db")
TEMP_YFINANCE_CACHE_DIR: str = str(TEMP_DB_DIR / "py-yfinance")
TEMPFILE_TEMP_DIR: str = str(_TEST_TEMP_ROOT)


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


def _ensure_temp_db_file() -> None:
    """Create an empty redirected SQLite file if it is missing."""
    if Path(TEMP_DB_PATH).exists():
        return
    with sqlite3.connect(TEMP_DB_PATH):
        pass


def _ensure_tempfile_dir() -> None:
    """Route stdlib temp files into the writable workspace sandbox."""
    global _MKDTEMP_PATCHED

    Path(TEMPFILE_TEMP_DIR).mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = TEMPFILE_TEMP_DIR
    os.environ["TEMP"] = TEMPFILE_TEMP_DIR
    os.environ["TMPDIR"] = TEMPFILE_TEMP_DIR
    tempfile.tempdir = TEMPFILE_TEMP_DIR

    if _MKDTEMP_PATCHED:
        return

    def _workspace_mkdtemp(
        suffix: str | bytes | None = None,
        prefix: str | bytes | None = None,
        dir: str | bytes | os.PathLike[str] | os.PathLike[bytes] | None = None,
    ) -> str | bytes:
        if isinstance(suffix, bytes) or isinstance(prefix, bytes) or isinstance(dir, bytes):
            return _ORIGINAL_MKDTEMP(suffix=suffix, prefix=prefix, dir=dir)

        suffix_s = "" if suffix is None else os.fspath(suffix)
        prefix_s = tempfile.gettempprefix() if prefix is None else os.fspath(prefix)
        dir_s = TEMPFILE_TEMP_DIR if dir is None else os.fspath(dir)
        Path(dir_s).mkdir(parents=True, exist_ok=True)

        names = tempfile._get_candidate_names()  # type: ignore[attr-defined]
        for _ in range(100):
            candidate = Path(dir_s) / f"{prefix_s}{next(names)}{suffix_s}"
            try:
                # Avoid tempfile's restrictive 0o700 mkdir mode, which
                # becomes unreadable in this Windows sandbox.  Inheriting
                # the workspace ACL keeps the directory usable by tests.
                os.mkdir(candidate)
            except FileExistsError:
                continue
            return str(candidate)
        raise FileExistsError("no usable temporary directory name found")

    tempfile.mkdtemp = _workspace_mkdtemp
    _MKDTEMP_PATCHED = True


def _ensure_temp_yfinance_cache_dir() -> None:
    """Point yfinance cache probes at a writable temp directory."""
    global _YFINANCE_PATCHED

    Path(TEMP_YFINANCE_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    os.environ["SECOND_ORDER_YFINANCE_CACHE_DIR"] = TEMP_YFINANCE_CACHE_DIR
    try:
        import yfinance as yf  # type: ignore

        set_tz_cache_location = getattr(yf, "set_tz_cache_location", None)
        if callable(set_tz_cache_location):
            set_tz_cache_location(TEMP_YFINANCE_CACHE_DIR)

        if not _YFINANCE_PATCHED:
            try:
                import pandas as pd  # type: ignore
            except Exception:
                pd = None  # type: ignore

            def _empty_download(*args, **kwargs):
                return pd.DataFrame() if pd is not None else None

            class _EmptyTicker:
                def __init__(self, *args, **kwargs) -> None:
                    pass

                @property
                def info(self) -> dict:
                    return {}

                def history(self, *args, **kwargs):
                    return pd.DataFrame() if pd is not None else None

            yf.download = _empty_download
            yf.Ticker = _EmptyTicker
            _YFINANCE_PATCHED = True
    except Exception:
        # Tests that do not need yfinance should not fail just because
        # the optional provider is absent or changes its cache API.
        pass


def redirect_db_constants() -> str:
    """Point ``db.DB_FILE`` at :data:`TEMP_DB_PATH` and re-bind the
    snapshot-module copies.  Idempotent — repeat calls preserve the
    same path while reasserting the binding in case an earlier test
    patched it and failed to restore cleanly.

    Returns the redirected path so a caller that wants to log it can.
    """
    global _REDIRECTED

    # Make sure the project root is on ``sys.path`` so ``import db``
    # resolves to the live module (test files already do this, but a
    # bare ``python -m unittest tests.<X>`` invocation may not have
    # added the root yet by the time __init__.py runs).
    root_str = str(_PROJECT_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    _ensure_tempfile_dir()

    import db  # noqa: E402 — deliberate late import; see comment above
    db.DB_FILE = TEMP_DB_PATH
    _ensure_temp_db_file()
    _ensure_temp_yfinance_cache_dir()
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
