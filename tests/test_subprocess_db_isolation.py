"""AB1 Lane C — subprocess DB isolation.

AA1 found the test-suite isolation harness monkeypatched ``db.DB_FILE`` in
process but did NOT export ``EVENTS_DB_FILE``, so a child process (a CLI test or
a spawned tool) doing a fresh ``import db`` resolved ``DB_FILE`` to the LIVE
``events.db`` — escaping isolation.  ``redirect_db_constants`` now also exports
``EVENTS_DB_FILE`` pointing at the per-process temp DB, so children inherit the
same isolated path.

The probe is READ-ONLY: the child imports ``db`` and prints ``get_db_path()`` —
it never calls ``init_db()``, so no DB file is created or written and the live
archive is never touched, even when this test is red.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import _db_isolation  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROBE = "import db; print('DBPATH=' + db.get_db_path())"


class SubprocessInheritsDbIsolation(unittest.TestCase):
    def test_redirect_exports_isolated_path_env(self) -> None:
        # The in-process redirect must publish EVENTS_DB_FILE so a child
        # process inherits the same isolated temp DB.
        self.assertEqual(
            os.environ.get("EVENTS_DB_FILE"), _db_isolation.TEMP_DB_PATH,
        )

    def test_child_resolves_isolated_db_not_live(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", _PROBE],
            cwd=_ROOT,
            env=dict(os.environ),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        dbpath = next(
            (
                ln.partition("=")[2]
                for ln in result.stdout.splitlines()
                if ln.startswith("DBPATH=")
            ),
            None,
        )
        self.assertEqual(dbpath, _db_isolation.TEMP_DB_PATH)
        self.assertNotEqual(
            os.path.realpath(dbpath or ""),
            os.path.realpath(_db_isolation.live_db_path()),
            msg="child resolved the LIVE archive — subprocess isolation broken",
        )


if __name__ == "__main__":
    unittest.main()
