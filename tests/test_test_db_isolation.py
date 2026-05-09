"""Proof that the test suite cannot mutate the live ``events.db``.

The isolation layer (``tests/conftest.py`` + ``tests/__init__.py`` +
``tests/_db_isolation.py``) redirects ``db.DB_FILE`` to a per-session
temp path BEFORE any test module is imported.  This file pins the
contract so a future regression — someone removes the conftest, or
adds a module-level snapshot of ``DB_FILE`` we don't patch — is caught
immediately.

What we pin
-----------
* ``db.DB_FILE`` is NOT the project-root ``events.db``.
* ``db.DB_FILE`` lives under the user's temp directory.
* The redirect fixed-points: importing ``_db_isolation`` again does
  not change the path.
* The three modules that snapshot ``DB_FILE`` at module top
  (``macro_release_facts``, ``macro_surprises``, ``saved_studies``)
  see the redirected path when imported.
* ``db.init_db()`` against the redirected path leaves the live DB
  byte-identical (covers the lowest level: a real sqlite write).
* A FastAPI ``TestClient`` lifespan (which fires ``init_db()``) plus
  a write-through entry point leaves the live DB byte-identical.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import unittest
from pathlib import Path

# Add project root so ``import db`` resolves the live module — tests
# elsewhere already use this pattern.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests import _db_isolation  # noqa: E402


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_LIVE_DB_PATH = _PROJECT_ROOT / "events.db"


# ---------------------------------------------------------------------------
# Live-DB snapshot helpers — deliberately tolerant to "live DB does
# not exist" so the suite does not require any specific archive state.
# ---------------------------------------------------------------------------


def _snapshot_live_db() -> tuple[bool, int, int, str | None]:
    """Return ``(exists, size, mtime_ns, sha256_hex)`` for the live DB.

    When the file does not exist returns
    ``(False, 0, 0, None)`` — equality is then a meaningful "still
    doesn't exist" assertion rather than a precondition failure.
    """
    if not _LIVE_DB_PATH.exists():
        return (False, 0, 0, None)
    st = _LIVE_DB_PATH.stat()
    h = hashlib.sha256()
    with open(_LIVE_DB_PATH, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return (True, st.st_size, st.st_mtime_ns, h.hexdigest())


# ---------------------------------------------------------------------------
# 1. Path redirection
# ---------------------------------------------------------------------------


class TestDbFileRedirected(unittest.TestCase):
    def test_db_file_is_not_live_path(self) -> None:
        import db
        live = str(_LIVE_DB_PATH.resolve())
        actual = str(Path(db.DB_FILE).resolve())
        self.assertNotEqual(
            actual, live,
            f"db.DB_FILE is still pointing at the live archive: {actual!r}",
        )

    def test_db_file_lives_under_tempdir(self) -> None:
        import db
        import tempfile
        temp_root = Path(tempfile.gettempdir()).resolve()
        actual = Path(db.DB_FILE).resolve()
        try:
            actual.relative_to(temp_root)
        except ValueError:  # pragma: no cover — only fires if redirect broke
            self.fail(
                f"db.DB_FILE must live under {temp_root}; got {actual}",
            )

    def test_helper_exposes_live_and_temp_paths(self) -> None:
        # The helper is the source of truth for what's redirected to
        # what; any test that needs to compare paths reads from here.
        self.assertEqual(
            Path(_db_isolation.live_db_path()).resolve(),
            _LIVE_DB_PATH.resolve(),
        )
        self.assertTrue(str(_db_isolation.TEMP_DB_PATH))

    def test_redirect_is_idempotent(self) -> None:
        import db
        before = db.DB_FILE
        _db_isolation.redirect_db_constants()
        _db_isolation.redirect_db_constants()
        self.assertEqual(db.DB_FILE, before)

    def test_db_file_equals_session_redirect_path(self) -> None:
        """``db.DB_FILE`` is the per-session redirect path (and stays
        that way across tests).  The looser
        ``test_db_file_lives_under_tempdir`` check above passes if any
        test has swapped ``db.DB_FILE`` to a per-test temp file under
        ``tempfile.gettempdir()`` and forgotten to restore — this
        sentinel pins the stricter "no intra-session drift" contract.

        Order-dependent.  Pytest collects tests alphabetically, so this
        module runs after ``test_portfolio_view_persistence``,
        ``test_macro_release_facts`` and ``test_macro_surprises``; any
        leak from those files surfaces here.  A future reorder of the
        verification command (or pytest config) that put this module
        first would silently disarm the check, so keep this in mind
        when adjusting test order.
        """
        import db
        self.assertEqual(
            Path(db.DB_FILE).resolve(),
            Path(_db_isolation.TEMP_DB_PATH).resolve(),
            "db.DB_FILE has drifted off the session redirect — an "
            "earlier test swapped it to a per-test temp file and did "
            "not restore in tearDown",
        )


# ---------------------------------------------------------------------------
# 2. Module-top snapshot modules
# ---------------------------------------------------------------------------


class TestSnapshotModulesSeeRedirect(unittest.TestCase):
    """``macro_release_facts``, ``macro_surprises``, ``saved_studies``
    do ``from db import DB_FILE`` at module top-level — once imported,
    their local ``DB_FILE`` is frozen.  The isolation layer must (a)
    redirect ``db.DB_FILE`` BEFORE these modules first import, AND (b)
    re-bind their attribute if they were already imported when the
    redirect ran."""

    _MODULES = (
        "macro_release_facts",
        "macro_surprises",
        "saved_studies",
    )

    def test_each_snapshot_module_sees_redirected_db_file(self) -> None:
        import db
        live = str(_LIVE_DB_PATH.resolve())
        for mod_name in self._MODULES:
            with self.subTest(module=mod_name):
                mod = __import__(mod_name)
                self.assertTrue(
                    hasattr(mod, "DB_FILE"),
                    f"{mod_name} must expose DB_FILE at module level",
                )
                self.assertEqual(
                    mod.DB_FILE, db.DB_FILE,
                    f"{mod_name}.DB_FILE diverged from db.DB_FILE",
                )
                actual = str(Path(mod.DB_FILE).resolve())
                self.assertNotEqual(
                    actual, live,
                    f"{mod_name}.DB_FILE still points at live: {actual!r}",
                )


# ---------------------------------------------------------------------------
# 3. Lowest-level write proof — ``db.init_db()`` against the redirect
# ---------------------------------------------------------------------------


class TestInitDbDoesNotTouchLive(unittest.TestCase):
    def test_init_db_writes_to_redirected_path_only(self) -> None:
        import db
        before = _snapshot_live_db()
        # Idempotent: if a previous test already created the temp DB,
        # init_db() simply opens it and runs its migrations — that
        # still exercises the sqlite write path against the redirected
        # location, which is exactly what this test checks.
        db.init_db()
        after = _snapshot_live_db()
        self.assertEqual(
            before, after,
            "live events.db must be byte-identical after db.init_db()",
        )
        self.assertTrue(
            Path(db.DB_FILE).exists(),
            "init_db() should have created/preserved the redirected DB",
        )

    def test_save_event_round_trip_against_redirect(self) -> None:
        import db
        before = _snapshot_live_db()
        # Ensure the redirected DB is initialised — idempotent if a
        # prior test already ran init_db().  We deliberately don't
        # ``os.remove`` first: on Windows the temp file may still be
        # held by a lingering sqlite handle, and the assertion this
        # test pins ("live DB unchanged") doesn't need a fresh temp.
        db.init_db()
        # Direct sqlite write to the redirected path — exercises the
        # raw ``sqlite3.connect(DB_FILE)`` path used everywhere in db.py.
        with sqlite3.connect(db.DB_FILE) as conn:
            conn.execute(
                "INSERT INTO events "
                "(timestamp, headline, stage, persistence) "
                "VALUES (?, ?, ?, ?)",
                ("2026-05-08T00:00:00", "isolation_proof",
                 "stage", "persistence"),
            )
            conn.commit()
        after = _snapshot_live_db()
        self.assertEqual(
            before, after,
            "live events.db must be byte-identical after a write to the "
            "redirected DB",
        )


# ---------------------------------------------------------------------------
# 4. FastAPI TestClient lifespan write proof
# ---------------------------------------------------------------------------


class TestFastApiLifespanDoesNotTouchLive(unittest.TestCase):
    def test_test_client_lifespan_init_db_lands_on_redirect(self) -> None:
        # ``api.app`` lifespan calls ``init_db()`` on TestClient enter.
        # Without the redirect, that call writes to the live archive;
        # with the redirect, it must land on the temp path only.
        from fastapi.testclient import TestClient
        import api  # noqa: F401 — ensures api module is loaded
        import db

        before = _snapshot_live_db()

        with TestClient(api.app) as client:
            # Issue a trivial request so the lifespan is fully entered.
            try:
                client.get("/health")
            except Exception:
                pass
            self.assertTrue(
                Path(db.DB_FILE).exists(),
                "TestClient lifespan should have initialised the "
                "redirected DB",
            )

        after = _snapshot_live_db()
        self.assertEqual(
            before, after,
            "live events.db must be byte-identical after a TestClient "
            "lifespan",
        )


# ---------------------------------------------------------------------------
# 5. Defence-in-depth: a write inside a TestClient request lands on
#     the redirect.  The exact endpoint is irrelevant — we use the
#     same direct sqlite write done in section 3, but issued AFTER the
#     TestClient is up to confirm the lifespan didn't quietly restore
#     the live path.
# ---------------------------------------------------------------------------


class TestWritesUnderTestClientStayRedirected(unittest.TestCase):
    def test_direct_sqlite_write_during_request_stays_on_redirect(self) -> None:
        from fastapi.testclient import TestClient
        import api
        import db

        before = _snapshot_live_db()
        with TestClient(api.app) as client:
            try:
                client.get("/health")
            except Exception:
                pass
            with sqlite3.connect(db.DB_FILE) as conn:
                conn.execute(
                    "INSERT INTO events "
                    "(timestamp, headline, stage, persistence) "
                    "VALUES (?, ?, ?, ?)",
                    ("2026-05-08T00:00:01", "isolation_proof_2",
                     "stage", "persistence"),
                )
                conn.commit()
        after = _snapshot_live_db()
        self.assertEqual(
            before, after,
            "live events.db must be byte-identical even when a write is "
            "issued from inside a TestClient context",
        )


if __name__ == "__main__":
    unittest.main()
