"""
tests/test_bot_api_client.py

Focused tests for telegram_bot._api_get() and _api_post().

Contract these functions have:
  - They make a single HTTP call and decode the JSON response.
  - They have NO exception handling — all errors propagate to callers.
  - callers (handlers / call_analyze / call_news) are responsible for
    catching URLError / Exception before they reach the user.

Covers:
  1. _api_get success: correct URL, decoded JSON returned
  2. _api_get failure: URLError / HTTPError / parse error all propagate
  3. _api_post success: correct URL + body + Content-Type, decoded JSON
  4. _api_post failure: same propagation contract
  5. call_analyze: propagates errors (no swallowed exceptions)
  6. call_news: propagates errors
"""

import json
import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call
from urllib.error import HTTPError, URLError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telegram_bot
from telegram_bot import _api_get, _api_post, call_analyze, call_news, API_URL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Minimal context-manager wrapping a JSON payload."""
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_urlopen(return_value=None, side_effect=None):
    """Return a patcher for telegram_bot.urllib.request.urlopen."""
    if side_effect is not None:
        return patch("telegram_bot.urllib.request.urlopen", side_effect=side_effect)
    return patch("telegram_bot.urllib.request.urlopen", return_value=return_value)


# ---------------------------------------------------------------------------
# 1. _api_get success path
# ---------------------------------------------------------------------------

class TestApiGetSuccess(unittest.TestCase):

    def test_returns_decoded_json(self):
        payload = {"status": "ok", "count": 3}
        with _patch_urlopen(return_value=_FakeResponse(payload)):
            result = _api_get("/news")
        self.assertEqual(result, payload)

    def test_builds_url_from_api_url(self):
        captured = {}

        def _spy(req, timeout=None):
            captured["url"] = req.full_url
            return _FakeResponse({"ok": True})

        with _patch_urlopen(side_effect=_spy):
            _api_get("/news")

        self.assertTrue(captured["url"].startswith(API_URL), captured["url"])
        self.assertIn("/news", captured["url"])

    def test_appends_path_to_base_url(self):
        captured = {}

        def _spy(req, timeout=None):
            captured["url"] = req.full_url
            return _FakeResponse({})

        with _patch_urlopen(side_effect=_spy):
            _api_get("/market-context?highlight_limit=5")

        self.assertIn("/market-context", captured["url"])
        self.assertIn("highlight_limit=5", captured["url"])

    def test_timeout_is_set(self):
        captured = {}

        def _spy(req, timeout=None):
            captured["timeout"] = timeout
            return _FakeResponse({})

        with _patch_urlopen(side_effect=_spy):
            _api_get("/news")

        self.assertIsNotNone(captured.get("timeout"))
        self.assertGreater(captured["timeout"], 0)


# ---------------------------------------------------------------------------
# 2. _api_get failure propagation
# ---------------------------------------------------------------------------

class TestApiGetFailurePropagation(unittest.TestCase):
    """_api_get has no try/except — all errors must propagate."""

    def test_url_error_propagates(self):
        with _patch_urlopen(side_effect=URLError("connection refused")):
            with self.assertRaises(URLError):
                _api_get("/news")

    def test_http_error_propagates(self):
        def _raise(req, timeout=None):
            raise HTTPError(url="http://x", code=500, msg="Server Error",
                            hdrs={}, fp=None)

        with _patch_urlopen(side_effect=_raise):
            with self.assertRaises(HTTPError):
                _api_get("/news")

    def test_http_401_propagates(self):
        def _raise(req, timeout=None):
            raise HTTPError(url="http://x", code=401, msg="Unauthorized",
                            hdrs={}, fp=None)

        with _patch_urlopen(side_effect=_raise):
            with self.assertRaises(HTTPError):
                _api_get("/news")

    def test_json_parse_error_propagates(self):
        class _BadResp:
            def read(self): return b"not valid json {"
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with _patch_urlopen(return_value=_BadResp()):
            with self.assertRaises(json.JSONDecodeError):
                _api_get("/news")

    def test_generic_exception_propagates(self):
        with _patch_urlopen(side_effect=RuntimeError("timeout")):
            with self.assertRaises(RuntimeError):
                _api_get("/news")


# ---------------------------------------------------------------------------
# 3. _api_post success path
# ---------------------------------------------------------------------------

class TestApiPostSuccess(unittest.TestCase):

    def test_returns_decoded_json(self):
        payload = {"id": 42, "stage": "emerging"}
        with _patch_urlopen(return_value=_FakeResponse(payload)):
            result = _api_post("/analyze", {"headline": "Test"})
        self.assertEqual(result, payload)

    def test_sends_json_content_type(self):
        captured = {}

        def _spy(req, timeout=None):
            captured["headers"] = dict(req.headers)
            return _FakeResponse({})

        with _patch_urlopen(side_effect=_spy):
            _api_post("/analyze", {"headline": "Test"})

        ct = captured["headers"].get("Content-type") or captured["headers"].get("Content-Type", "")
        self.assertIn("application/json", ct)

    def test_sends_json_encoded_body(self):
        captured = {}

        def _spy(req, timeout=None):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse({})

        body = {"headline": "Fed raises rates", "extra": 123}
        with _patch_urlopen(side_effect=_spy):
            _api_post("/analyze", body)

        self.assertEqual(captured["body"], body)

    def test_uses_post_method(self):
        captured = {}

        def _spy(req, timeout=None):
            captured["method"] = req.method
            return _FakeResponse({})

        with _patch_urlopen(side_effect=_spy):
            _api_post("/analyze", {})

        self.assertEqual(captured["method"], "POST")

    def test_builds_url_with_path(self):
        captured = {}

        def _spy(req, timeout=None):
            captured["url"] = req.full_url
            return _FakeResponse({})

        with _patch_urlopen(side_effect=_spy):
            _api_post("/analyze", {})

        self.assertIn("/analyze", captured["url"])


# ---------------------------------------------------------------------------
# 4. _api_post failure propagation
# ---------------------------------------------------------------------------

class TestApiPostFailurePropagation(unittest.TestCase):

    def test_url_error_propagates(self):
        with _patch_urlopen(side_effect=URLError("refused")):
            with self.assertRaises(URLError):
                _api_post("/analyze", {"headline": "X"})

    def test_http_error_propagates(self):
        def _raise(req, timeout=None):
            raise HTTPError(url="http://x", code=422, msg="Unprocessable",
                            hdrs={}, fp=None)

        with _patch_urlopen(side_effect=_raise):
            with self.assertRaises(HTTPError):
                _api_post("/analyze", {"headline": "X"})

    def test_json_parse_error_propagates(self):
        class _BadResp:
            def read(self): return b"<html>502 Bad Gateway</html>"
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with _patch_urlopen(return_value=_BadResp()):
            with self.assertRaises(json.JSONDecodeError):
                _api_post("/analyze", {})


# ---------------------------------------------------------------------------
# 5. call_analyze — no try/except, errors propagate
# ---------------------------------------------------------------------------

class TestCallAnalyzePropagation(unittest.TestCase):
    """call_analyze() has no error handling; handlers must wrap it."""

    def test_url_error_propagates_to_caller(self):
        with _patch_urlopen(side_effect=URLError("api down")):
            with self.assertRaises(URLError):
                call_analyze("US imposes tariffs on steel")

    def test_http_error_propagates_to_caller(self):
        def _raise(req, timeout=None):
            raise HTTPError(url="http://x", code=503, msg="Unavailable",
                            hdrs={}, fp=None)

        with _patch_urlopen(side_effect=_raise):
            with self.assertRaises(HTTPError):
                call_analyze("US imposes tariffs on steel")

    def test_posts_to_analyze_endpoint(self):
        captured = {}

        def _spy(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse({"stage": "emerging"})

        with _patch_urlopen(side_effect=_spy):
            call_analyze("Fed signals rate cut")

        self.assertIn("/analyze", captured["url"])
        self.assertEqual(captured["body"], {"headline": "Fed signals rate cut"})

    def test_returns_decoded_response(self):
        fake = {"stage": "realized", "persistence": "structural"}
        with _patch_urlopen(return_value=_FakeResponse(fake)):
            result = call_analyze("OPEC cuts production")
        self.assertEqual(result, fake)


# ---------------------------------------------------------------------------
# 6. call_news — no try/except, errors propagate
# ---------------------------------------------------------------------------

class TestCallNewsPropagation(unittest.TestCase):
    """call_news() has no error handling; callers must wrap it."""

    def test_url_error_propagates(self):
        with _patch_urlopen(side_effect=URLError("refused")):
            with self.assertRaises(URLError):
                call_news()

    def test_gets_news_endpoint(self):
        captured = {}

        def _spy(req, timeout=None):
            captured["url"] = req.full_url
            return _FakeResponse({"clusters": []})

        with _patch_urlopen(side_effect=_spy):
            call_news()

        self.assertIn("/news", captured["url"])

    def test_returns_decoded_response(self):
        fake = {"clusters": [{"headline": "Test"}], "total_headlines": 1}
        with _patch_urlopen(return_value=_FakeResponse(fake)):
            result = call_news()
        self.assertEqual(result, fake)


if __name__ == "__main__":
    unittest.main()
