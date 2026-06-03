# tests/test_db_path_env.py
"""Tests for the ``EVENTS_DB_FILE`` dev / verification DB-safety seam.

The contract (see README "Dev / verification DB safety"):

* ``EVENTS_DB_FILE`` is resolved ONCE, at import time, into ``db.DB_FILE``.
* When it is unset (or blank) the backend falls back to the live
  ``events.db`` default.
* api's startup logs a warning when the active binding is the live archive,
  so the live binding is never silent.

These tests exercise the pure resolver / override / binding helpers directly
(no in-process ``importlib.reload`` — that would leave ``db.DB_FILE`` pointing
at the live archive and defeat the test-suite isolation harness), plus one
subprocess probe that proves the import-time wiring end to end.  Nothing here
calls ``init_db()``, opens the live DB, or touches the network.
"""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import db

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ResolveEventsDbFileTests(unittest.TestCase):
    """``resolve_events_db_file`` maps an environment to a DB path."""

    def test_env_override_wins(self):
        self.assertEqual(
            db.resolve_events_db_file({"EVENTS_DB_FILE": "events.dev.db"}),
            "events.dev.db",
        )

    def test_unset_falls_back_to_live(self):
        self.assertEqual(db.resolve_events_db_file({}), db.LIVE_DB_FILE)

    def test_blank_override_falls_back_to_live(self):
        self.assertEqual(
            db.resolve_events_db_file({"EVENTS_DB_FILE": ""}), db.LIVE_DB_FILE
        )

    def test_whitespace_override_falls_back_to_live(self):
        self.assertEqual(
            db.resolve_events_db_file({"EVENTS_DB_FILE": "   "}), db.LIVE_DB_FILE
        )

    def test_override_is_stripped(self):
        self.assertEqual(
            db.resolve_events_db_file({"EVENTS_DB_FILE": "  events.dev.db  "}),
            "events.dev.db",
        )


class EventsDbOverrideTests(unittest.TestCase):
    """``events_db_override`` reports the explicit override, or None."""

    def test_reports_override_when_set(self):
        self.assertEqual(
            db.events_db_override({"EVENTS_DB_FILE": "events.dev.db"}),
            "events.dev.db",
        )

    def test_none_when_unset(self):
        self.assertIsNone(db.events_db_override({}))

    def test_none_when_blank(self):
        self.assertIsNone(db.events_db_override({"EVENTS_DB_FILE": ""}))
        self.assertIsNone(db.events_db_override({"EVENTS_DB_FILE": "   "}))


class DbBindingIsLiveTests(unittest.TestCase):
    """``db_binding_is_live`` recognises the live archive by realpath."""

    def test_live_default_path_is_live(self):
        self.assertTrue(db.db_binding_is_live(db.LIVE_DB_FILE))
        self.assertTrue(db.db_binding_is_live("events.db"))

    def test_other_path_is_not_live(self):
        other = os.path.join(_ROOT, "tests", "not_the_live_archive.db")
        self.assertFalse(db.db_binding_is_live(other))

    def test_harness_redirected_default_is_not_live(self):
        # Under the test-suite isolation harness ``db.DB_FILE`` is rebound to
        # a per-process temp path, so the no-arg default binding is NOT live —
        # this is exactly what keeps api's startup warning quiet under tests.
        self.assertFalse(db.db_binding_is_live())


class LiveDbConstantTests(unittest.TestCase):
    def test_live_db_file_constant(self):
        self.assertEqual(db.LIVE_DB_FILE, "events.db")


class ImportTimeBindingTests(unittest.TestCase):
    """A fresh ``import db`` resolves ``DB_FILE`` from ``EVENTS_DB_FILE``.

    Run in a subprocess so the parent process's ``db`` module (and the
    isolation harness's temp redirect) are never disturbed.  The child only
    imports ``db`` and prints two values — it never calls ``init_db()`` so no
    DB file is created or mutated.
    """

    _PROBE = (
        "import db;"
        "print('DBFILE=' + db.DB_FILE);"
        "print('OVERRIDE=' + repr(db.events_db_override()))"
    )

    def _run(self, env_value):
        env = dict(os.environ)
        if env_value is None:
            env.pop("EVENTS_DB_FILE", None)
        else:
            env["EVENTS_DB_FILE"] = env_value
        result = subprocess.run(
            [sys.executable, "-c", self._PROBE],
            cwd=_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        out = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                out[key] = val
        return out

    def test_import_binds_to_env_override(self):
        out = self._run("events.probe.db")
        self.assertEqual(out.get("DBFILE"), "events.probe.db")
        self.assertEqual(out.get("OVERRIDE"), "'events.probe.db'")

    def test_import_falls_back_to_live_when_unset(self):
        out = self._run(None)
        self.assertEqual(out.get("DBFILE"), "events.db")
        self.assertEqual(out.get("OVERRIDE"), "None")


class StartupWarningEmissionTests(unittest.TestCase):
    """api's lifespan logs the live-binding warning — never silent.

    Booting ``api.app`` is safe under the test harness: ``init_db()`` runs
    against the redirected temp DB, no provider / paid call fires.  We patch
    the two decision helpers on the ``api`` namespace so the warning branch is
    exercised without ever actually binding to the live archive.
    """

    def test_warns_when_bound_to_live(self):
        import api
        from fastapi.testclient import TestClient

        with mock.patch.object(api, "db_binding_is_live", return_value=True), \
                mock.patch.object(api, "events_db_override", return_value=None):
            with self.assertLogs("second_order.api", level="WARNING") as cm:
                with TestClient(api.app):
                    pass
        self.assertTrue(
            any("EVENTS_DB_FILE is unset" in line for line in cm.output),
            msg=f"expected live-binding warning, got: {cm.output}",
        )

    def test_quiet_when_not_bound_to_live(self):
        import api
        from fastapi.testclient import TestClient

        # The harness default: db_binding_is_live() is False, so the warning
        # branch must stay silent (no false "bound to live" on every boot).
        with mock.patch.object(api, "db_binding_is_live", return_value=False):
            with self.assertNoLogs("second_order.api", level="WARNING"):
                with TestClient(api.app):
                    pass


if __name__ == "__main__":
    unittest.main()
