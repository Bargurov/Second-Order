"""Test package init — runs the DB isolation redirect for unittest.

``python -m unittest tests.<module>`` imports the ``tests`` package
before importing any test module, so this file is the earliest hook
we have to redirect ``db.DB_FILE`` away from the project-root
``events.db``.  It mirrors what ``tests/conftest.py`` does for the
pytest path; both end up calling the same idempotent helper.

Keep this file deliberately tiny — no other side effects, no
``__all__``, no test-collection logic.  Anything beyond the redirect
risks changing pytest's package-import semantics relative to the
prior namespace-package layout.
"""
from tests._db_isolation import redirect_db_constants

redirect_db_constants()
