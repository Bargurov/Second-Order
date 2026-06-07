"""Q4 — admin-token guard for the paid /analyze and mutation routes.

The guard activates only when ``SECOND_ORDER_ADMIN_TOKEN`` is configured (a
public deploy).  Unconfigured (local dev / the existing test suite) it is
inert, so nothing else changes.  When configured:

  * mutation routes (events delete/review/refresh/revisit, portfolio
    save/update/delete, curated stage) require the ``X-Second-Order-Admin-Token``
    header — else 403;
  * ``/analyze`` requires that header AND ``ENABLE_PAID_ANALYSIS=true``,
    returning 403 **before any provider call**.

Public read-only routes stay open with no token.
"""
from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import api  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_TOKEN = "test-admin-token-xyz"
_HDR = {"X-Second-Order-Admin-Token": _TOKEN}


@contextmanager
def _analyze_seams(provider_return=None):
    """Patch the analyze pipeline seams so no provider / network / DB is hit.

    Yields the patched ``_call_analyze_event`` mock so tests can assert
    whether the provider boundary was reached.
    """
    if provider_return is None:
        provider_return = {"_mock": True}
    with mock.patch("routes.analyze._call_analyze_event", return_value=provider_return) as prov, \
         mock.patch("routes.analyze._is_mock_analysis", return_value=True), \
         mock.patch("api.build_macro_context_for_prompt", return_value=""), \
         mock.patch("api.find_cached_analysis", return_value=None), \
         mock.patch("api.load_event_by_id", return_value=None), \
         mock.patch("api.classify_stage", return_value="developing"), \
         mock.patch("api.classify_persistence", return_value="medium"):
        yield prov


# ---------------------------------------------------------------------------
# Dependency logic (unit) — no app, no DB.
# ---------------------------------------------------------------------------


class AdminTokenGuardUnit(unittest.TestCase):
    def test_inert_when_unconfigured(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": ""}):
            self.assertIsNone(api.require_admin_token(x_admin_token=None))

    def test_rejects_missing_header(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}):
            with self.assertRaises(HTTPException) as ctx:
                api.require_admin_token(x_admin_token=None)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_rejects_wrong_header(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}):
            with self.assertRaises(HTTPException) as ctx:
                api.require_admin_token(x_admin_token="wrong")
            self.assertEqual(ctx.exception.status_code, 403)

    def test_accepts_correct_header(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}):
            self.assertIsNone(api.require_admin_token(x_admin_token=_TOKEN))


class PaidAnalysisGuardUnit(unittest.TestCase):
    def test_inert_when_unconfigured(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": "", "ENABLE_PAID_ANALYSIS": "false"}):
            self.assertIsNone(api.require_paid_analysis(x_admin_token=None))

    def test_rejects_when_paid_disabled(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN, "ENABLE_PAID_ANALYSIS": "false"}):
            with self.assertRaises(HTTPException) as ctx:
                api.require_paid_analysis(x_admin_token=_TOKEN)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_rejects_missing_token_even_if_paid_enabled(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN, "ENABLE_PAID_ANALYSIS": "true"}):
            with self.assertRaises(HTTPException) as ctx:
                api.require_paid_analysis(x_admin_token=None)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_passes_with_token_and_paid_enabled(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN, "ENABLE_PAID_ANALYSIS": "true"}):
            self.assertIsNone(api.require_paid_analysis(x_admin_token=_TOKEN))


# ---------------------------------------------------------------------------
# /analyze route (integration) — guard wired + provider never called when blocked.
# ---------------------------------------------------------------------------


class AnalyzeRouteGuardIntegration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)

    def test_unauthenticated_403_and_no_provider_call(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN, "ENABLE_PAID_ANALYSIS": "true"}), \
                _analyze_seams() as prov:
            r = self.client.post("/analyze", json={"headline": "Guard test headline"})
        self.assertEqual(r.status_code, 403)
        prov.assert_not_called()

    def test_wrong_token_403(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN, "ENABLE_PAID_ANALYSIS": "true"}), \
                _analyze_seams() as prov:
            r = self.client.post("/analyze", json={"headline": "Guard test headline"},
                                 headers={"X-Second-Order-Admin-Token": "wrong"})
        self.assertEqual(r.status_code, 403)
        prov.assert_not_called()

    def test_paid_disabled_403_even_with_token(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN, "ENABLE_PAID_ANALYSIS": "false"}), \
                _analyze_seams() as prov:
            r = self.client.post("/analyze", json={"headline": "Guard test headline"}, headers=_HDR)
        self.assertEqual(r.status_code, 403)
        prov.assert_not_called()

    def test_correct_token_and_paid_reaches_provider(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN, "ENABLE_PAID_ANALYSIS": "true"}), \
                _analyze_seams() as prov:
            r = self.client.post("/analyze", json={"headline": "Fresh guard headline abc"}, headers=_HDR)
        self.assertNotEqual(r.status_code, 403)
        prov.assert_called_once()


# ---------------------------------------------------------------------------
# Representative mutation route (integration).
# ---------------------------------------------------------------------------


class MutationRouteGuardIntegration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)

    def test_delete_requires_token(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}), \
                mock.patch("routes.events.delete_event") as del_mock:
            r = self.client.delete("/events/999999")
        self.assertEqual(r.status_code, 403)
        del_mock.assert_not_called()

    def test_delete_accepts_correct_token(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}), \
                mock.patch("routes.events.delete_event", return_value=False) as del_mock:
            r = self.client.delete("/events/999999", headers=_HDR)
        # Guard passed → handler ran → 404 (event missing), never 403.
        self.assertNotEqual(r.status_code, 403)
        del_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Public read-only route stays open.
# ---------------------------------------------------------------------------


class PublicRouteUnaffected(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)

    def test_health_public_without_token(self):
        with mock.patch.dict(os.environ, {"SECOND_ORDER_ADMIN_TOKEN": _TOKEN}):
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
