"""Early unittest-discovery bootstrap for shared test isolation.

``python -m unittest discover -s tests`` imports test modules as
top-level ``test_*`` modules, so ``tests/__init__.py`` is not guaranteed
to run before the first production import.  Keep this file first in the
discovery order so the same redirect used by targeted ``tests.*`` runs
is active for full discovery too.
"""
from __future__ import annotations

import unittest
import tempfile

from tests import _db_isolation


_db_isolation.redirect_db_constants()


class TestDbIsolationBootstrap(unittest.TestCase):
    def test_db_path_is_redirected(self) -> None:
        import db

        self.assertEqual(db.get_db_path(), _db_isolation.TEMP_DB_PATH)

    def test_stdlib_tempdir_is_workspace_redirected(self) -> None:
        self.assertEqual(tempfile.gettempdir(), _db_isolation.TEMPFILE_TEMP_DIR)
