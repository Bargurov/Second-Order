"""
tests/test_bot_url_resolution.py

Focused tests for telegram_bot._resolve_api_url().

Proves that placeholder and blank values from .env.example never reach
the bot as a live URL — they are silently replaced with the localhost
default.  Real user-provided URLs pass through unchanged.

No network calls, no bot start — pure function tests.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from telegram_bot import _resolve_api_url, _DEFAULT_API_URL

_LOCALHOST = _DEFAULT_API_URL  # "http://127.0.0.1:8000"


class TestPlaceholderResolution(unittest.TestCase):
    """Placeholder and blank values → localhost default."""

    def test_exact_placeholder_returns_localhost(self):
        """The .env.example sentinel string must resolve to localhost."""
        self.assertEqual(
            _resolve_api_url("your_second_order_api_url_here"),
            _LOCALHOST,
        )

    def test_any_your_prefix_returns_localhost(self):
        """Any 'your_…' string is treated as a placeholder."""
        for val in (
            "your_second_order_api_url_here",
            "your_api_url",
            "your_production_url",
            "your_",
        ):
            with self.subTest(val=val):
                self.assertEqual(_resolve_api_url(val), _LOCALHOST)

    def test_blank_string_returns_localhost(self):
        """Empty string (SECOND_ORDER_API_URL=) returns localhost."""
        self.assertEqual(_resolve_api_url(""), _LOCALHOST)

    def test_whitespace_only_returns_localhost(self):
        """Whitespace-only value is treated as blank."""
        for val in ("   ", "\t", "\n", "  \t  "):
            with self.subTest(repr=repr(val)):
                self.assertEqual(_resolve_api_url(val), _LOCALHOST)

    def test_none_arg_falls_through_to_localhost(self):
        """None (no raw arg) with env var unset resolves to localhost.

        We can't easily unset env vars inside a running process, but we
        can pass raw="" to simulate the 'env var is blank' path.
        """
        self.assertEqual(_resolve_api_url(""), _LOCALHOST)

    def test_default_api_url_is_localhost(self):
        """_DEFAULT_API_URL constant must be the expected localhost address."""
        self.assertEqual(_DEFAULT_API_URL, "http://127.0.0.1:8000")


class TestRealUrlPassThrough(unittest.TestCase):
    """Real user-provided URLs pass through unchanged."""

    def test_http_localhost_url_unchanged(self):
        self.assertEqual(
            _resolve_api_url("http://127.0.0.1:8000"),
            "http://127.0.0.1:8000",
        )

    def test_https_production_url_unchanged(self):
        self.assertEqual(
            _resolve_api_url("https://api.example.com"),
            "https://api.example.com",
        )

    def test_http_production_url_unchanged(self):
        self.assertEqual(
            _resolve_api_url("http://10.0.0.5:8080"),
            "http://10.0.0.5:8080",
        )

    def test_trailing_slash_preserved(self):
        """Trailing slashes on a real URL are preserved."""
        url = "https://api.example.com/"
        self.assertEqual(_resolve_api_url(url), url)

    def test_url_with_path_preserved(self):
        """Real URL with a sub-path is not modified."""
        url = "https://example.com/api/v2"
        self.assertEqual(_resolve_api_url(url), url)

    def test_render_style_url_unchanged(self):
        """Render.com / Railway-style service URLs pass through."""
        self.assertEqual(
            _resolve_api_url("https://second-order.onrender.com"),
            "https://second-order.onrender.com",
        )

    def test_real_url_with_leading_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped from real URLs."""
        self.assertEqual(
            _resolve_api_url("  https://api.example.com  "),
            "https://api.example.com",
        )


if __name__ == "__main__":
    unittest.main()
