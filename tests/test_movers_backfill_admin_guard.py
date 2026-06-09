"""AB1 Lane D — admin-token guard on the paid ``/movers`` backfill POST routes.

AA1 found ``POST /movers/backfill-recent`` and ``POST /movers/backfill-candidate``
carried neither ``require_admin_token`` nor ``require_paid_analysis`` — unlike
``/analyze`` — so on a configured (public) deploy they stayed anonymously
reachable.  These tests pin that the admin guard now gates both routes, while
the existing inline paid gates (``max_llm_calls`` requirement, ``confirm_paid``,
the ``ENABLE_PAID_ANALYSIS`` kill-switch) are unchanged.

The guard is inert when ``SECOND_ORDER_ADMIN_TOKEN`` is unset (local dev), so
the existing suite and local use are unaffected.

DB-isolated + token-gated: no live DB, no LLM, no network — every request is
rejected by the guard or short-circuits at an inline 400 paid gate.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import api  # noqa: E402
import db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_TOKEN = "test-admin-token-xyz"
_HDR = {"X-Second-Order-Admin-Token": _TOKEN}


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_movers_guard_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        try:
            os.remove(self._tmp)
        except OSError:
            pass


class BackfillRecentGuard(_Base):
    def test_missing_token_rejected_when_configured(self) -> None:
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}):
            r = self.client.post("/movers/backfill-recent")
        self.assertEqual(r.status_code, 403)
        self.assertIn("admin token", (r.json().get("detail") or "").lower())

    def test_wrong_token_rejected_when_configured(self) -> None:
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}):
            r = self.client.post(
                "/movers/backfill-recent",
                headers={"X-Second-Order-Admin-Token": "wrong"},
            )
        self.assertEqual(r.status_code, 403)

    def test_valid_token_passes_guard_paid_gate_intact(self) -> None:
        # Guard passes → reaches the handler, which still enforces the
        # max_llm_calls requirement (400).  Proves the inline paid gate is
        # unchanged and no spend path is reachable without it.
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}):
            r = self.client.post("/movers/backfill-recent", headers=_HDR)
        self.assertEqual(r.status_code, 400)
        self.assertIn("max_llm_calls", (r.json().get("detail") or "").lower())

    def test_guard_inert_when_unconfigured(self) -> None:
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": ""}):
            r = self.client.post("/movers/backfill-recent")
        self.assertEqual(r.status_code, 400)  # reaches handler's max_llm_calls gate, not 403


class BackfillCandidateGuard(_Base):
    def test_missing_token_rejected_when_configured(self) -> None:
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}):
            r = self.client.post("/movers/backfill-candidate?headline=Steel+tariff")
        self.assertEqual(r.status_code, 403)
        self.assertIn("admin token", (r.json().get("detail") or "").lower())

    def test_wrong_token_rejected_when_configured(self) -> None:
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}):
            r = self.client.post(
                "/movers/backfill-candidate?headline=Steel+tariff",
                headers={"X-Second-Order-Admin-Token": "wrong"},
            )
        self.assertEqual(r.status_code, 403)

    def test_valid_token_passes_guard_paid_gate_intact(self) -> None:
        # Guard passes → handler still requires confirm_paid (400).
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}):
            r = self.client.post(
                "/movers/backfill-candidate?headline=Steel+tariff", headers=_HDR,
            )
        self.assertEqual(r.status_code, 400)
        self.assertIn("confirm_paid", (r.json().get("detail") or "").lower())

    def test_guard_inert_when_unconfigured(self) -> None:
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": ""}):
            r = self.client.post("/movers/backfill-candidate?headline=Steel+tariff")
        self.assertEqual(r.status_code, 400)  # reaches confirm_paid gate, not 403


if __name__ == "__main__":
    unittest.main()
