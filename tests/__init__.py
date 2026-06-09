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
import os

# Test safety (AP1): the suite must never run with a real (billable) Anthropic
# key — /analyze stays in mock mode so the fail-closed paid-analysis guard's
# "no real key -> allow" path is the suite default.  Pin BEFORE importing
# modules that call ``load_dotenv()`` (which would otherwise pull the real
# ``.env`` key into ``os.environ`` and make tokenless /analyze tests 403).
# A test that genuinely needs a real-shaped key sets it locally (e.g. via
# ``mock.patch.dict``); see tests/test_admin_guard.py::PaidAnalysisFailClosedUnit.
os.environ["ANTHROPIC_API_KEY"] = ""

from tests._db_isolation import redirect_db_constants

redirect_db_constants()
