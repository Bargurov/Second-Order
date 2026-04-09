"""
tests/test_deploy_runtime_config.py

Pin down the deployed-runtime configuration contract.

Three things this file proves:

  1. **Backend CORS is env-driven.** ``api._resolve_cors_origins``
     parses ``CORS_ALLOWED_ORIGINS`` correctly for every documented
     shape (unset, empty, wildcard, comma list, whitespace noise),
     and the FastAPI app registers CORSMiddleware if and only if the
     parsed list is non-empty.  Preflight OPTIONS requests surface
     ``Access-Control-Allow-Origin`` only for allowed origins.

  2. **Frontend API base is env-driven with a safe same-origin
     fallback.** ``resolveApiBase`` in ``frontend/src/lib/api.ts``
     reads ``VITE_API_BASE_URL`` and falls back to ``"/api"``.  No
     hardcoded localhost / 127.0.0.1 leaks survive anywhere in the
     frontend source tree.

  3. **Deployment templates stay aligned.** ``render.yaml`` carries
     the deployment env var declarations the codebase now depends on,
     and ``frontend/.env.example`` + ``.env.example`` document the
     same vars so a fresh-clone user can run ``cp .env.example .env``
     and have a working configuration.
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Cluster A — _resolve_cors_origins pure helper
# ---------------------------------------------------------------------------


class TestResolveCorsOrigins(unittest.TestCase):
    """Pure env-parsing helper.  No FastAPI, no network."""

    def setUp(self):
        self._orig = os.environ.get("CORS_ALLOWED_ORIGINS")
        # Importing ``api`` is expensive — it drags in the whole app.
        # We only need the pure helper, so grab it once.
        import api
        self._resolve = api._resolve_cors_origins

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        else:
            os.environ["CORS_ALLOWED_ORIGINS"] = self._orig

    def test_unset_returns_empty_list(self):
        os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        self.assertEqual(self._resolve(), [])

    def test_empty_string_returns_empty_list(self):
        os.environ["CORS_ALLOWED_ORIGINS"] = ""
        self.assertEqual(self._resolve(), [])

    def test_whitespace_only_returns_empty_list(self):
        os.environ["CORS_ALLOWED_ORIGINS"] = "   \t  "
        self.assertEqual(self._resolve(), [])

    def test_wildcard_returns_single_star(self):
        os.environ["CORS_ALLOWED_ORIGINS"] = "*"
        self.assertEqual(self._resolve(), ["*"])

    def test_single_origin(self):
        os.environ["CORS_ALLOWED_ORIGINS"] = "https://app.example.com"
        self.assertEqual(self._resolve(), ["https://app.example.com"])

    def test_comma_list_trimmed(self):
        os.environ["CORS_ALLOWED_ORIGINS"] = (
            "https://app.example.com, https://staging.example.com"
        )
        self.assertEqual(
            self._resolve(),
            ["https://app.example.com", "https://staging.example.com"],
        )

    def test_empty_items_filtered(self):
        """Trailing commas and whitespace-only fragments are dropped."""
        os.environ["CORS_ALLOWED_ORIGINS"] = (
            "https://a.example.com,,  ,https://b.example.com,"
        )
        self.assertEqual(
            self._resolve(),
            ["https://a.example.com", "https://b.example.com"],
        )


# ---------------------------------------------------------------------------
# Cluster B — CORSMiddleware wiring against a real TestClient
# ---------------------------------------------------------------------------


def _reload_api_with_env(**env_vars: str):
    """Re-import ``api`` with the supplied env vars set.

    Module-level code in ``api.py`` reads ``CORS_ALLOWED_ORIGINS`` at
    import time to decide whether to register ``CORSMiddleware`` on
    the shared ``app`` object.  We reload the module to observe both
    branches in a single test run without leaking state.
    """
    prior_env = {k: os.environ.get(k) for k in env_vars}
    for k, v in env_vars.items():
        os.environ[k] = v
    try:
        if "api" in sys.modules:
            api = importlib.reload(sys.modules["api"])
        else:
            import api as api  # noqa: F401
        return api
    finally:
        for k, v in prior_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestCorsMiddlewareWiring(unittest.TestCase):
    """When CORS_ALLOWED_ORIGINS is set, the middleware surfaces the
    expected headers on preflight and actual requests.  When it's
    unset, no CORS headers appear at all — that's the safe default
    for same-origin deploys."""

    def tearDown(self):
        # Restore a clean api module so subsequent tests see the
        # default (no-CORS) wiring.
        os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        if "api" in sys.modules:
            importlib.reload(sys.modules["api"])

    def test_no_cors_header_when_env_unset(self):
        os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        api = _reload_api_with_env()
        from fastapi.testclient import TestClient

        client = TestClient(api.app)
        r = client.get(
            "/health",
            headers={"Origin": "https://other.example.com"},
        )
        self.assertEqual(r.status_code, 200)
        # No middleware registered → no Allow-Origin echo.
        self.assertNotIn("access-control-allow-origin", r.headers)

    def test_cors_header_echoes_allowed_origin(self):
        api = _reload_api_with_env(
            CORS_ALLOWED_ORIGINS="https://app.example.com"
        )
        from fastapi.testclient import TestClient

        client = TestClient(api.app)
        r = client.get(
            "/health",
            headers={"Origin": "https://app.example.com"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.headers.get("access-control-allow-origin"),
            "https://app.example.com",
        )

    def test_cors_preflight_surfaces_allowed_methods(self):
        api = _reload_api_with_env(
            CORS_ALLOWED_ORIGINS="https://app.example.com"
        )
        from fastapi.testclient import TestClient

        client = TestClient(api.app)
        r = client.options(
            "/events",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.headers.get("access-control-allow-origin"),
            "https://app.example.com",
        )
        # The allowlist-with-credentials mode sets this to "true".
        self.assertEqual(
            r.headers.get("access-control-allow-credentials"), "true",
        )

    def test_cors_header_absent_for_unknown_origin(self):
        api = _reload_api_with_env(
            CORS_ALLOWED_ORIGINS="https://app.example.com"
        )
        from fastapi.testclient import TestClient

        client = TestClient(api.app)
        r = client.get(
            "/health",
            headers={"Origin": "https://evil.example.com"},
        )
        # Request still succeeds (the server can't see the Origin
        # restriction — that's the browser's job) but the Allow-Origin
        # header is NOT echoed, so the browser will block it.
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(
            "https://evil.example.com",
            r.headers.get("access-control-allow-origin", ""),
        )

    def test_wildcard_disables_credentials(self):
        """Wildcard ``*`` must not set allow-credentials — per the CORS spec
        a credentialed response cannot use a wildcard origin."""
        api = _reload_api_with_env(CORS_ALLOWED_ORIGINS="*")
        from fastapi.testclient import TestClient

        client = TestClient(api.app)
        r = client.get(
            "/health", headers={"Origin": "https://anywhere.example.com"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.headers.get("access-control-allow-origin"), "*",
        )
        self.assertNotEqual(
            r.headers.get("access-control-allow-credentials"), "true",
        )


# ---------------------------------------------------------------------------
# Cluster C — frontend api.ts resolveApiBase contract (structural grep)
# ---------------------------------------------------------------------------


class TestFrontendApiBaseResolution(unittest.TestCase):
    """``resolveApiBase`` in ``frontend/src/lib/api.ts`` is the single
    source of truth for the API base URL.  The structural-grep pattern
    used here mirrors the existing no-Sparkline test — there is no JS
    runner in the repo, so we assert the source contains every
    contract-level marker the hardening pass relies on."""

    def setUp(self):
        self.path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "frontend",
            "src",
            "lib",
            "api.ts",
        )
        with open(self.path, "r", encoding="utf-8") as f:
            self.src = f.read()

    def test_exports_resolve_api_base(self):
        self.assertIn("export function resolveApiBase", self.src)

    def test_reads_vite_env(self):
        self.assertIn("VITE_API_BASE_URL", self.src)
        self.assertIn("import.meta.env.VITE_API_BASE_URL", self.src)

    def test_fallback_is_same_origin_api_prefix(self):
        """Empty / unset env → ``/api`` (same-origin default)."""
        self.assertIn('return "/api"', self.src)

    def test_strips_trailing_slash(self):
        """Path composition depends on a base without a trailing slash."""
        self.assertIn("replace(/\\/+$/", self.src)

    def test_no_hardcoded_localhost_in_frontend_source(self):
        """No leftover localhost / 127.0.0.1 string literals in src/.

        Walk every tracked file under ``frontend/src``.  Dev-time
        tooling files (``vite.config.ts``, ``.env.example``) are
        excluded — they're allowed to mention 127.0.0.1 as the
        default dev proxy target."""
        src_root = os.path.join(
            os.path.dirname(__file__), "..", "frontend", "src",
        )
        offenders: list[str] = []
        for dirpath, _, filenames in os.walk(src_root):
            for name in filenames:
                if not name.endswith((".ts", ".tsx", ".js", ".jsx")):
                    continue
                p = os.path.join(dirpath, name)
                with open(p, "r", encoding="utf-8") as f:
                    body = f.read()
                if "localhost" in body or "127.0.0.1" in body:
                    offenders.append(p)
        self.assertEqual(
            offenders,
            [],
            f"Hardcoded localhost found in: {offenders}",
        )


# ---------------------------------------------------------------------------
# Cluster D — deployment templates document the new env vars
# ---------------------------------------------------------------------------


class TestDeploymentTemplatesAligned(unittest.TestCase):
    """render.yaml and the two .env.example files must stay in sync
    with the runtime config the code actually reads."""

    def _read(self, *parts: str) -> str:
        path = os.path.join(os.path.dirname(__file__), "..", *parts)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_render_yaml_declares_cors_env(self):
        src = self._read("render.yaml")
        self.assertIn("CORS_ALLOWED_ORIGINS", src)

    def test_render_yaml_declares_anthropic_key(self):
        src = self._read("render.yaml")
        self.assertIn("ANTHROPIC_API_KEY", src)

    def test_render_yaml_uses_0_0_0_0_host(self):
        """Render injects $PORT; the server must bind on 0.0.0.0 to
        accept external connections.  A 127.0.0.1 bind would serve
        only loopback and the platform health-check would fail."""
        src = self._read("render.yaml")
        self.assertIn("0.0.0.0", src)
        self.assertIn("$PORT", src)

    def test_backend_env_example_documents_cors(self):
        src = self._read(".env.example")
        self.assertIn("CORS_ALLOWED_ORIGINS", src)

    def test_frontend_env_example_exists(self):
        src = self._read("frontend", ".env.example")
        self.assertIn("VITE_API_BASE_URL", src)

    def test_vite_config_keeps_dev_proxy(self):
        """The dev proxy at ``/api`` is what makes the same default work
        locally and in prod.  Deleting it would break dev."""
        src = self._read("frontend", "vite.config.ts")
        self.assertIn("/api", src)
        self.assertIn("proxy", src)


if __name__ == "__main__":
    unittest.main()
