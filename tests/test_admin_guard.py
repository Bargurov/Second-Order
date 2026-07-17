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

P0 cross-provider parity: the paid guard resolves the SELECTED analysis
provider (``ANALYSIS_PROVIDER``: anthropic default, openai, invalid →
anthropic fallback) and that provider's key through one source of truth
shared with dispatch (``analyze_event.resolve_provider_configuration``).
A real OpenAI key is guarded exactly like a real Anthropic key on BOTH
``/analyze`` and ``/analyze/stream``; local/mock mode stays open only
when the selected provider's key is empty or a placeholder.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
# Explicit-empty BEFORE the first application import: python-dotenv fills
# only variables MISSING from the environment, so an empty string here
# prevents a maintainer .env from loading billable keys (or a provider
# selection) into the test process at import time.  Per-test values are
# then pinned with run-window mock.patch.dict — that is the authoritative
# mechanism; these defaults only close the import-order window.
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("ANALYSIS_PROVIDER", "")

import api  # noqa: E402
import analyze_event  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_TOKEN = "test-admin-token-xyz"
_HDR = {"X-Second-Order-Admin-Token": _TOKEN}

# Real-SHAPED but unmistakably fake fixtures — never live secrets.  The
# guard rejects before any provider call and every dispatch seam is
# monkeypatched, so no billing can occur from these tests.
_FAKE_ANTHROPIC_KEY = "sk-ant-fake-not-a-real-key-do-not-use"
_FAKE_OPENAI_KEY = "sk-fake-openai-guard-parity-not-a-real-key"


def _guard_env(provider: str, *, anthropic_key: str = "",
               openai_key: str = "", paid: str = "",
               admin: str = "") -> dict[str, str]:
    """A fully pinned guard environment — every variable the provider
    resolution and paid guard read is set explicitly (empty = absent),
    so ambient shell state and the maintainer .env can never leak in."""
    return {
        "ANALYSIS_PROVIDER": provider,
        "ANTHROPIC_API_KEY": anthropic_key,
        "OPENAI_API_KEY": openai_key,
        "ENABLE_PAID_ANALYSIS": paid,
        "SECOND_ORDER_ADMIN_TOKEN": admin,
    }


@contextmanager
def _dispatch_seams():
    """Patch BOTH provider dispatch seams (recorders, no network) plus the
    DB/cache/macro seams so the real analyze pipeline can run to the
    provider boundary without touching a provider, database, or market
    data.  Yields (openai_seam, anthropic_seam, persist)."""
    with mock.patch("analyze_event._call_openai",
                    return_value=None) as openai_seam, \
            mock.patch("analyze_event._call_anthropic",
                       return_value=None) as anthropic_seam, \
            mock.patch("api.build_macro_context_for_prompt",
                       return_value=""), \
            mock.patch("api.find_cached_analysis", return_value=None), \
            mock.patch("api.load_event_by_id", return_value=None), \
            mock.patch("api._persist_event", return_value=None) as persist, \
            mock.patch("api.classify_stage", return_value="developing"), \
            mock.patch("api.classify_persistence", return_value="medium"):
        yield openai_seam, anthropic_seam, persist


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


class PaidAnalysisFailClosedUnit(unittest.TestCase):
    """AP1 — fail CLOSED when a real (billable) key is present.

    The old guard returned early when ``SECOND_ORDER_ADMIN_TOKEN`` was unset
    ("inert"), so a real Anthropic key + no admin token left ``/analyze``
    unprotected.  A missing admin token must never be a free pass when the
    process can actually bill.  No-real-key (mock) mode stays open so local
    dev / the test suite are unaffected.
    """

    # Real-SHAPED but fake key — never a live secret.  The guard rejects
    # before any provider call, so no billing can occur from these tests.
    _REAL_KEY = "sk-ant-fake-not-a-real-key-do-not-use"

    def test_real_key_no_admin_token_rejected(self):
        with mock.patch.dict(os.environ, {
            "ANALYSIS_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": self._REAL_KEY,
            "SECOND_ORDER_ADMIN_TOKEN": "",
            "ENABLE_PAID_ANALYSIS": "",
        }):
            with self.assertRaises(HTTPException) as ctx:
                api.require_paid_analysis(x_admin_token=None)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_real_key_paid_disabled_rejected(self):
        with mock.patch.dict(os.environ, {
            "ANALYSIS_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": self._REAL_KEY,
            "SECOND_ORDER_ADMIN_TOKEN": "",
            "ENABLE_PAID_ANALYSIS": "false",
        }):
            with self.assertRaises(HTTPException) as ctx:
                api.require_paid_analysis(x_admin_token=None)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_real_key_paid_enabled_but_no_admin_token_rejected(self):
        # Even with paid explicitly enabled, no CONFIGURED admin token means
        # there is nothing to authenticate against → fail closed.
        with mock.patch.dict(os.environ, {
            "ANALYSIS_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": self._REAL_KEY,
            "SECOND_ORDER_ADMIN_TOKEN": "",
            "ENABLE_PAID_ANALYSIS": "true",
        }):
            with self.assertRaises(HTTPException) as ctx:
                api.require_paid_analysis(x_admin_token=None)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_real_key_with_admin_paid_and_header_allowed(self):
        with mock.patch.dict(os.environ, {
            "ANALYSIS_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": self._REAL_KEY,
            "SECOND_ORDER_ADMIN_TOKEN": _TOKEN,
            "ENABLE_PAID_ANALYSIS": "true",
        }):
            self.assertIsNone(api.require_paid_analysis(x_admin_token=_TOKEN))

    def test_no_real_key_no_admin_allowed_mock_safe(self):
        # Local mock mode: no billable key, no admin token → allowed (the
        # /analyze path returns a mock and never bills).
        with mock.patch.dict(os.environ, {
            "ANALYSIS_PROVIDER": "",
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "SECOND_ORDER_ADMIN_TOKEN": "",
            "ENABLE_PAID_ANALYSIS": "",
        }):
            self.assertIsNone(api.require_paid_analysis(x_admin_token=None))


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


# ---------------------------------------------------------------------------
# P0 — cross-provider paid-guard parity.
# ---------------------------------------------------------------------------


class OpenAIGuardBypassReproduction(unittest.TestCase):
    """P0 reproduction — the intended safe contract.

    ``ANALYSIS_PROVIDER=openai`` with a real-shaped OpenAI key, paid
    analysis disabled, and no admin token must be rejected before either
    provider dispatch seam is reached — exactly like the Anthropic
    equivalent.  The pre-fix guard resolved billability from
    ``ANTHROPIC_API_KEY`` alone, treated this configuration as local
    mock mode, and let the request reach OpenAI dispatch.
    """

    _ENV = _guard_env("openai", openai_key=_FAKE_OPENAI_KEY,
                      paid="false", admin="")

    def test_unit_guard_rejects_openai_real_key_paid_disabled(self):
        with mock.patch.dict(os.environ, self._ENV):
            with self.assertRaises(HTTPException) as ctx:
                api.require_paid_analysis(x_admin_token=None)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_analyze_rejects_before_openai_dispatch(self):
        client = TestClient(api.app)
        with mock.patch.dict(os.environ, self._ENV), \
                _dispatch_seams() as (openai_seam, anthropic_seam, persist):
            r = client.post("/analyze",
                            json={"headline": "P0 openai bypass repro"})
        self.assertEqual(r.status_code, 403)
        openai_seam.assert_not_called()
        anthropic_seam.assert_not_called()
        persist.assert_not_called()

    def test_analyze_stream_rejects_before_openai_dispatch(self):
        client = TestClient(api.app)
        with mock.patch.dict(os.environ, self._ENV), \
                _dispatch_seams() as (openai_seam, anthropic_seam, persist):
            r = client.post("/analyze/stream",
                            json={"headline": "P0 openai stream repro"})
        self.assertEqual(r.status_code, 403)
        openai_seam.assert_not_called()
        anthropic_seam.assert_not_called()
        persist.assert_not_called()


class ProviderResolutionContract(unittest.TestCase):
    """One source of truth: analyze_event.resolve_provider_configuration.

    The guard and the dispatch layer must never disagree about the
    selected provider, its key, the key state, or billability.
    """

    def _resolve(self, env):
        with mock.patch.dict(os.environ, env):
            return analyze_event.resolve_provider_configuration()

    def test_openai_real_key(self):
        cfg = self._resolve(_guard_env("openai",
                                       openai_key=_FAKE_OPENAI_KEY))
        self.assertEqual((cfg.provider, cfg.key, cfg.key_state,
                          cfg.billable),
                         ("openai", _FAKE_OPENAI_KEY, "real", True))

    def test_anthropic_real_key(self):
        cfg = self._resolve(_guard_env("anthropic",
                                       anthropic_key=_FAKE_ANTHROPIC_KEY))
        self.assertEqual((cfg.provider, cfg.key_state, cfg.billable),
                         ("anthropic", "real", True))

    def test_empty_and_placeholder_keys_not_billable(self):
        for provider, key_kw in (("openai", "openai_key"),
                                 ("anthropic", "anthropic_key")):
            with self.subTest(provider=provider, state="empty"):
                cfg = self._resolve(_guard_env(provider))
                self.assertEqual((cfg.key_state, cfg.billable),
                                 ("empty", False))
            for placeholder in ("your_api_key_here", "placeholder",
                                "changeme",
                                f"your_{provider}_api_key_here"):
                with self.subTest(provider=provider, key=placeholder):
                    cfg = self._resolve(
                        _guard_env(provider, **{key_kw: placeholder}))
                    self.assertEqual((cfg.key_state, cfg.billable),
                                     ("placeholder", False))

    def test_unset_and_invalid_provider_follow_dispatch_fallback(self):
        # Unset → anthropic default; invalid → the existing explicit
        # anthropic fallback (_selected_provider) — the guard must land
        # on the SAME provider dispatch would use.
        for raw in ("", "not-a-provider", "gemini"):
            with self.subTest(provider=raw):
                cfg = self._resolve(_guard_env(
                    raw, anthropic_key=_FAKE_ANTHROPIC_KEY,
                    openai_key=_FAKE_OPENAI_KEY))
                self.assertEqual(cfg.provider, "anthropic")
                with mock.patch.dict(os.environ, {
                        "ANALYSIS_PROVIDER": raw}):
                    self.assertEqual(cfg.provider,
                                     analyze_event._selected_provider())

    def test_case_and_whitespace_normalization(self):
        cfg = self._resolve(_guard_env("  OpenAI  ",
                                       openai_key=_FAKE_OPENAI_KEY))
        self.assertEqual((cfg.provider, cfg.billable), ("openai", True))

    def test_non_selected_real_key_never_makes_billable(self):
        # A real key for the NON-selected provider must not flip
        # billability: dispatch would never use it.
        cfg = self._resolve(_guard_env("anthropic",
                                       openai_key=_FAKE_OPENAI_KEY))
        self.assertEqual((cfg.provider, cfg.key, cfg.key_state,
                          cfg.billable),
                         ("anthropic", "", "empty", False))
        cfg = self._resolve(_guard_env("openai",
                                       anthropic_key=_FAKE_ANTHROPIC_KEY))
        self.assertEqual((cfg.provider, cfg.key_state, cfg.billable),
                         ("openai", "empty", False))

    def test_billable_agrees_with_has_real_api_key(self):
        for env in (_guard_env("openai", openai_key=_FAKE_OPENAI_KEY),
                    _guard_env("openai", openai_key="changeme"),
                    _guard_env("anthropic",
                               anthropic_key=_FAKE_ANTHROPIC_KEY),
                    _guard_env("anthropic")):
            with self.subTest(env=env):
                cfg = self._resolve(env)
                self.assertEqual(cfg.billable,
                                 analyze_event._has_real_api_key(cfg.key))


class PaidGuardProviderMatrixUnit(unittest.TestCase):
    """The full guard matrix, per provider, at the dependency level."""

    def _key_env(self, provider, key_value, paid, admin):
        key_kw = ("openai_key" if provider == "openai"
                  else "anthropic_key")
        return _guard_env(provider, **{key_kw: key_value},
                          paid=paid, admin=admin)

    def _reject(self, env, header, detail):
        with mock.patch.dict(os.environ, env):
            with self.assertRaises(HTTPException) as ctx:
                api.require_paid_analysis(x_admin_token=header)
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertEqual(ctx.exception.detail, detail)

    def test_local_mock_allowed_for_empty_and_placeholder(self):
        for provider in ("anthropic", "openai"):
            for key_value in ("", "your_api_key_here"):
                with self.subTest(provider=provider, key=key_value):
                    env = self._key_env(provider, key_value, "", "")
                    with mock.patch.dict(os.environ, env):
                        self.assertIsNone(
                            api.require_paid_analysis(x_admin_token=None))

    def test_real_key_paid_disabled_rejected_any_admin_state(self):
        for provider, key in (("anthropic", _FAKE_ANTHROPIC_KEY),
                              ("openai", _FAKE_OPENAI_KEY)):
            for admin, header in (("", None), (_TOKEN, None),
                                  (_TOKEN, _TOKEN)):
                with self.subTest(provider=provider, admin=admin,
                                  header=header):
                    self._reject(
                        self._key_env(provider, key, "false", admin),
                        header,
                        "paid analysis disabled "
                        "(set ENABLE_PAID_ANALYSIS=true)")

    def test_real_key_paid_enabled_admin_unconfigured_rejected(self):
        for provider, key in (("anthropic", _FAKE_ANTHROPIC_KEY),
                              ("openai", _FAKE_OPENAI_KEY)):
            with self.subTest(provider=provider):
                self._reject(
                    self._key_env(provider, key, "true", ""),
                    None,
                    "paid analysis requires SECOND_ORDER_ADMIN_TOKEN")

    def test_real_key_missing_or_wrong_header_rejected(self):
        for provider, key in (("anthropic", _FAKE_ANTHROPIC_KEY),
                              ("openai", _FAKE_OPENAI_KEY)):
            for header in (None, "wrong-token"):
                with self.subTest(provider=provider, header=header):
                    self._reject(
                        self._key_env(provider, key, "true", _TOKEN),
                        header, "admin token required")

    def test_real_key_fully_authorized_allowed(self):
        for provider, key in (("anthropic", _FAKE_ANTHROPIC_KEY),
                              ("openai", _FAKE_OPENAI_KEY)):
            with self.subTest(provider=provider):
                env = self._key_env(provider, key, "true", _TOKEN)
                with mock.patch.dict(os.environ, env):
                    self.assertIsNone(
                        api.require_paid_analysis(x_admin_token=_TOKEN))

    def test_invalid_provider_with_real_anthropic_key_fails_closed(self):
        # Invalid values follow the existing dispatch fallback (anthropic),
        # so a real Anthropic key still locks the route.
        env = _guard_env("not-a-provider",
                         anthropic_key=_FAKE_ANTHROPIC_KEY, paid="false")
        with mock.patch.dict(os.environ, env):
            with self.assertRaises(HTTPException) as ctx:
                api.require_paid_analysis(x_admin_token=None)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_whitespace_case_provider_with_real_openai_key_rejected(self):
        env = _guard_env("  OpenAI  ", openai_key=_FAKE_OPENAI_KEY,
                         paid="false")
        with mock.patch.dict(os.environ, env):
            with self.assertRaises(HTTPException) as ctx:
                api.require_paid_analysis(x_admin_token=None)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_non_selected_real_key_stays_local_mock(self):
        # Only the SELECTED provider's key state matters — dispatch never
        # consults the other key.
        for provider, other_key_kw in (("anthropic", "openai_key"),
                                       ("openai", "anthropic_key")):
            with self.subTest(provider=provider):
                env = _guard_env(provider, **{
                    other_key_kw: _FAKE_OPENAI_KEY
                    if other_key_kw == "openai_key"
                    else _FAKE_ANTHROPIC_KEY})
                with mock.patch.dict(os.environ, env):
                    self.assertIsNone(
                        api.require_paid_analysis(x_admin_token=None))


class AnalyzeRoutesProviderMatrixIntegration(unittest.TestCase):
    """Both route contracts: rejection happens before any dispatch seam,
    and authorized requests reach ONLY the selected provider seam."""

    _ROUTES = ("/analyze", "/analyze/stream")

    def setUp(self):
        self.client = TestClient(api.app)

    def _post(self, route, headline, headers=None):
        return self.client.post(route, json={"headline": headline},
                                headers=headers or {})

    def test_rejected_states_never_reach_either_seam(self):
        cases = [
            ("paid-disabled", _guard_env(
                "openai", openai_key=_FAKE_OPENAI_KEY, paid="false"), {}),
            ("paid-disabled", _guard_env(
                "anthropic", anthropic_key=_FAKE_ANTHROPIC_KEY,
                paid="false"), {}),
            ("admin-unconfigured", _guard_env(
                "openai", openai_key=_FAKE_OPENAI_KEY, paid="true"), {}),
            ("missing-header", _guard_env(
                "openai", openai_key=_FAKE_OPENAI_KEY, paid="true",
                admin=_TOKEN), {}),
            ("wrong-header", _guard_env(
                "openai", openai_key=_FAKE_OPENAI_KEY, paid="true",
                admin=_TOKEN),
             {"X-Second-Order-Admin-Token": "wrong"}),
            ("wrong-header", _guard_env(
                "anthropic", anthropic_key=_FAKE_ANTHROPIC_KEY,
                paid="true", admin=_TOKEN),
             {"X-Second-Order-Admin-Token": "wrong"}),
        ]
        for route in self._ROUTES:
            for label, env, headers in cases:
                with self.subTest(route=route, case=label,
                                  provider=env["ANALYSIS_PROVIDER"]):
                    with mock.patch.dict(os.environ, env), \
                            _dispatch_seams() as (openai_seam,
                                                  anthropic_seam,
                                                  persist):
                        r = self._post(route,
                                       f"P0 matrix {label} {route}",
                                       headers)
                    self.assertEqual(r.status_code, 403)
                    openai_seam.assert_not_called()
                    anthropic_seam.assert_not_called()
                    persist.assert_not_called()

    def test_authorized_reaches_only_selected_seam(self):
        # Both real keys present, one provider selected: exactly the
        # selected seam is reached, the other stays at zero.
        for route in self._ROUTES:
            for provider in ("anthropic", "openai"):
                with self.subTest(route=route, provider=provider):
                    env = _guard_env(
                        provider, anthropic_key=_FAKE_ANTHROPIC_KEY,
                        openai_key=_FAKE_OPENAI_KEY, paid="true",
                        admin=_TOKEN)
                    with mock.patch.dict(os.environ, env), \
                            _dispatch_seams() as (openai_seam,
                                                  anthropic_seam,
                                                  persist):
                        r = self._post(
                            route,
                            f"P0 authorized {provider} {route}", _HDR)
                    self.assertEqual(r.status_code, 200)
                    if provider == "openai":
                        openai_seam.assert_called_once()
                        anthropic_seam.assert_not_called()
                    else:
                        anthropic_seam.assert_called_once()
                        openai_seam.assert_not_called()

    def test_local_mock_stays_open_on_both_routes(self):
        # Empty selected key, no admin, paid off → allowed; the mock
        # path serves without touching either provider seam.
        for route in self._ROUTES:
            for provider in ("anthropic", "openai"):
                with self.subTest(route=route, provider=provider):
                    with mock.patch.dict(os.environ,
                                         _guard_env(provider)), \
                            _dispatch_seams() as (openai_seam,
                                                  anthropic_seam,
                                                  persist):
                        r = self._post(route,
                                       f"P0 mock {provider} {route}")
                    self.assertEqual(r.status_code, 200)
                    openai_seam.assert_not_called()
                    anthropic_seam.assert_not_called()
                    persist.assert_not_called()

    def test_non_selected_real_key_serves_mock_without_dispatch(self):
        # provider=anthropic with ONLY a real OpenAI key: local mock is
        # allowed and the real-keyed (non-selected) provider is never
        # dispatched.
        env = _guard_env("anthropic", openai_key=_FAKE_OPENAI_KEY)
        with mock.patch.dict(os.environ, env), \
                _dispatch_seams() as (openai_seam, anthropic_seam,
                                      persist):
            r = self._post("/analyze", "P0 non-selected real key")
        self.assertEqual(r.status_code, 200)
        openai_seam.assert_not_called()
        anthropic_seam.assert_not_called()


class DotenvExplicitEmptyImportSafety(unittest.TestCase):
    """Step 7 — explicit-empty keys survive application import.

    ``analyze_event`` runs ``load_dotenv()`` at import time and
    python-dotenv fills only variables MISSING from the environment.  A
    planted sentinel .env stands in for the maintainer's real one so the
    proof is deterministic on any machine (including a clean clone).
    """

    _DOTENV = ("OPENAI_API_KEY=dotenv-sentinel-openai-key\n"
               "ANTHROPIC_API_KEY=dotenv-sentinel-anthropic-key\n"
               "ANALYSIS_PROVIDER=openai\n")

    def _run_child(self, preset_empty: bool) -> dict:
        script = (
            "import os, json\n"
            + ("os.environ['OPENAI_API_KEY'] = ''\n"
               "os.environ['ANTHROPIC_API_KEY'] = ''\n"
               if preset_empty else "")
            + "import analyze_event\n"
            "cfg = analyze_event.resolve_provider_configuration()\n"
            "print(json.dumps({"
            "'openai_env': os.environ.get('OPENAI_API_KEY'), "
            "'provider': cfg.provider, 'key_state': cfg.key_state, "
            "'billable': cfg.billable}))\n")
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, ".env"), "w",
                      encoding="utf-8") as fh:
                fh.write(self._DOTENV)
            child_env = {k: v for k, v in os.environ.items()
                         if k not in ("OPENAI_API_KEY",
                                      "ANTHROPIC_API_KEY",
                                      "ANALYSIS_PROVIDER")}
            child_env["PYTHONPATH"] = _ROOT
            proc = subprocess.run(
                [sys.executable, "-c", script], cwd=td, env=child_env,
                capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_control_dotenv_fills_missing_key_as_billable(self):
        # Without the explicit empty, the planted .env key loads and the
        # configuration resolves billable — proving the hazard is real.
        out = self._run_child(preset_empty=False)
        self.assertEqual(out["openai_env"], "dotenv-sentinel-openai-key")
        self.assertEqual(out["provider"], "openai")
        self.assertEqual(out["key_state"], "real")
        self.assertTrue(out["billable"])

    def test_explicit_empty_key_survives_import(self):
        # An explicitly empty key must remain empty after import: dotenv
        # cannot silently repopulate it, and resolution stays unbillable.
        out = self._run_child(preset_empty=True)
        self.assertEqual(out["openai_env"], "")
        self.assertEqual(out["provider"], "openai")
        self.assertEqual(out["key_state"], "empty")
        self.assertFalse(out["billable"])


if __name__ == "__main__":
    unittest.main()
