"""
tests/test_analyze_retry.py

Focused tests for bounded retry/backoff on transient LLM provider failures.

  1) Transient overload retries then succeeds.
  2) Hard failure does not retry.
  3) Exhausted retries returns current failure shape (mock).
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ANTHROPIC_API_KEY"] = "test-key-for-retry-tests"

import anthropic
from analyze_event import (
    analyze_event,
    is_mock,
    _is_transient_error,
    RETRY_MAX_ATTEMPTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_overloaded_error():
    """Build a 529 overloaded error via APIStatusError."""
    resp = MagicMock()
    resp.status_code = 529
    resp.headers = {}
    return anthropic.APIStatusError(
        message="Overloaded",
        response=resp,
        body={"error": {"type": "overloaded_error", "message": "Overloaded"}},
    )


def _make_rate_limit_error():
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {}
    return anthropic.RateLimitError(
        message="Rate limited",
        response=resp,
        body={"error": {"type": "rate_limit_error", "message": "Rate limited"}},
    )


def _make_auth_error():
    resp = MagicMock()
    resp.status_code = 401
    resp.headers = {}
    return anthropic.AuthenticationError(
        message="Invalid API key",
        response=resp,
        body={"error": {"type": "authentication_error", "message": "Invalid API key"}},
    )


def _make_bad_request_error():
    resp = MagicMock()
    resp.status_code = 400
    resp.headers = {}
    return anthropic.BadRequestError(
        message="Bad request",
        response=resp,
        body={"error": {"type": "invalid_request_error", "message": "Bad request"}},
    )


def _make_success_message(text: str = '{"what_changed": "Test", "mechanism_summary": "Mechanism"}'):
    msg = MagicMock()
    block = MagicMock()
    block.text = text
    msg.content = [block]
    return msg


# ---------------------------------------------------------------------------
# Unit: _is_transient_error
# ---------------------------------------------------------------------------

class TestIsTransientError(unittest.TestCase):

    def test_overloaded_is_transient(self):
        self.assertTrue(_is_transient_error(_make_overloaded_error()))

    def test_rate_limit_is_transient(self):
        self.assertTrue(_is_transient_error(_make_rate_limit_error()))

    def test_timeout_is_transient(self):
        exc = anthropic.APITimeoutError(request=MagicMock())
        self.assertTrue(_is_transient_error(exc))

    def test_connection_error_is_transient(self):
        exc = anthropic.APIConnectionError(request=MagicMock())
        self.assertTrue(_is_transient_error(exc))

    def test_auth_error_not_transient(self):
        self.assertFalse(_is_transient_error(_make_auth_error()))

    def test_bad_request_not_transient(self):
        self.assertFalse(_is_transient_error(_make_bad_request_error()))

    def test_generic_exception_not_transient(self):
        self.assertFalse(_is_transient_error(ValueError("some error")))

    def test_import_error_not_transient(self):
        self.assertFalse(_is_transient_error(ImportError("no module")))


# ---------------------------------------------------------------------------
# 1) Transient overload retries then succeeds
# ---------------------------------------------------------------------------

class TestTransientRetryThenSuccess(unittest.TestCase):

    @patch("time.sleep")
    def test_overload_then_success(self, mock_sleep):
        """First call raises OverloadedError, second succeeds."""
        client_mock = MagicMock()
        client_mock.messages.create.side_effect = [
            _make_overloaded_error(),
            _make_success_message(),
        ]

        with patch("anthropic.Anthropic", return_value=client_mock):
            result = analyze_event("Test headline", "developing", "medium")

        self.assertFalse(is_mock(result))
        self.assertEqual(client_mock.messages.create.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("time.sleep")
    def test_rate_limit_then_success(self, mock_sleep):
        """First call raises RateLimitError, second succeeds."""
        client_mock = MagicMock()
        client_mock.messages.create.side_effect = [
            _make_rate_limit_error(),
            _make_success_message(),
        ]

        with patch("anthropic.Anthropic", return_value=client_mock):
            result = analyze_event("Test headline", "developing", "medium")

        self.assertFalse(is_mock(result))
        self.assertEqual(client_mock.messages.create.call_count, 2)

    @patch("time.sleep")
    def test_two_overloads_then_success(self, mock_sleep):
        """Two transient failures, third attempt succeeds."""
        client_mock = MagicMock()
        client_mock.messages.create.side_effect = [
            _make_overloaded_error(),
            _make_overloaded_error(),
            _make_success_message(),
        ]

        with patch("anthropic.Anthropic", return_value=client_mock):
            result = analyze_event("Test headline", "developing", "medium")

        self.assertFalse(is_mock(result))
        self.assertEqual(client_mock.messages.create.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)


# ---------------------------------------------------------------------------
# 2) Hard failure does not retry
# ---------------------------------------------------------------------------

class TestHardFailureNoRetry(unittest.TestCase):

    @patch("time.sleep")
    def test_auth_error_immediate_mock(self, mock_sleep):
        """AuthenticationError should fail immediately, no retries."""
        client_mock = MagicMock()
        client_mock.messages.create.side_effect = _make_auth_error()

        with patch("anthropic.Anthropic", return_value=client_mock):
            result = analyze_event("Test headline", "developing", "medium")

        self.assertTrue(is_mock(result))
        self.assertEqual(client_mock.messages.create.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_bad_request_immediate_mock(self, mock_sleep):
        client_mock = MagicMock()
        client_mock.messages.create.side_effect = _make_bad_request_error()

        with patch("anthropic.Anthropic", return_value=client_mock):
            result = analyze_event("Test headline", "developing", "medium")

        self.assertTrue(is_mock(result))
        self.assertEqual(client_mock.messages.create.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_generic_exception_immediate_mock(self, mock_sleep):
        """Non-Anthropic exceptions (e.g. ValueError) should not retry."""
        client_mock = MagicMock()
        client_mock.messages.create.side_effect = ValueError("bad data")

        with patch("anthropic.Anthropic", return_value=client_mock):
            result = analyze_event("Test headline", "developing", "medium")

        self.assertTrue(is_mock(result))
        self.assertEqual(client_mock.messages.create.call_count, 1)
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# 3) Exhausted retries returns current failure shape
# ---------------------------------------------------------------------------

class TestExhaustedRetries(unittest.TestCase):

    @patch("time.sleep")
    def test_all_attempts_overloaded(self, mock_sleep):
        """All attempts fail with overload → returns mock."""
        client_mock = MagicMock()
        client_mock.messages.create.side_effect = [
            _make_overloaded_error() for _ in range(RETRY_MAX_ATTEMPTS)
        ]

        with patch("anthropic.Anthropic", return_value=client_mock):
            result = analyze_event("Test headline", "developing", "medium")

        self.assertTrue(is_mock(result))
        self.assertIn("[mock:", result.get("what_changed", ""))
        self.assertEqual(client_mock.messages.create.call_count, RETRY_MAX_ATTEMPTS)
        # Backoff sleeps: one between each attempt (not after the last)
        self.assertEqual(mock_sleep.call_count, RETRY_MAX_ATTEMPTS - 1)

    @patch("time.sleep")
    def test_exhausted_mock_has_reason(self, mock_sleep):
        """The mock failure includes the original error message."""
        client_mock = MagicMock()
        client_mock.messages.create.side_effect = [
            _make_overloaded_error() for _ in range(RETRY_MAX_ATTEMPTS)
        ]

        with patch("anthropic.Anthropic", return_value=client_mock):
            result = analyze_event("Test headline", "developing", "medium")

        self.assertIn("Overloaded", result.get("what_changed", ""))

    @patch("time.sleep")
    def test_backoff_is_geometric(self, mock_sleep):
        """Sleep durations should follow geometric backoff."""
        client_mock = MagicMock()
        client_mock.messages.create.side_effect = [
            _make_overloaded_error() for _ in range(RETRY_MAX_ATTEMPTS)
        ]

        with patch("anthropic.Anthropic", return_value=client_mock):
            analyze_event("Test headline", "developing", "medium")

        # With base=1.0: sleep(1.0), sleep(2.0)
        sleeps = [c.args[0] for c in mock_sleep.call_args_list]
        self.assertEqual(len(sleeps), RETRY_MAX_ATTEMPTS - 1)
        for i, s in enumerate(sleeps):
            expected = 1.0 * (2 ** i)
            self.assertAlmostEqual(s, expected, places=1)


# ---------------------------------------------------------------------------
# 4) Fallback prints encode under a cp1252 (Windows redirected) stdout
# ---------------------------------------------------------------------------

class TestFallbackPrintsCp1252Safe(unittest.TestCase):
    """The no-API-key fallback prints guidance to stdout.  Under `python -m
    unittest` with stdout redirected to a file on Windows the stream encoding is
    cp1252, and a non-ASCII arrow in that guidance raised UnicodeEncodeError —
    crashing analyze_event before it could return its mock (AA1: 9 errored
    retry tests).  Reproduce the cp1252 stream and assert the path returns a
    mock instead of raising.
    """

    def test_no_api_key_path_encodes_under_cp1252_stdout(self):
        import io

        cp1252_stdout = io.TextIOWrapper(
            io.BytesIO(), encoding="cp1252", errors="strict", newline="",
        )
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": ""}), \
                patch.object(sys, "stdout", cp1252_stdout):
            result = analyze_event("Cp1252 guard headline", "developing", "medium")
        self.assertTrue(is_mock(result))


if __name__ == "__main__":
    unittest.main()
