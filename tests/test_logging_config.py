"""tests/test_logging_config.py

Format-shape tests for ``logging_config`` — the shared structured
logging setup.  Asserts the formatter renders a logfmt-style line
with the documented fields and that ``setup_logging()`` is idempotent
(repeated calls don't stack handlers).
"""

from __future__ import annotations

import io
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from logging_config import (
    KeyValueFormatter,
    log_event,
    setup_logging,
)


def _make_record(
    *, name: str = "second_order.test",
    level: int = logging.INFO,
    msg: str = "hello world",
    extra: dict | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name, level=level, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )
    for k, v in (extra or {}).items():
        setattr(record, k, v)
    return record


class TestKeyValueFormatterShape(unittest.TestCase):

    def test_required_fields_are_present(self) -> None:
        line = KeyValueFormatter().format(_make_record())
        for token in ("time=", "level=INFO", "logger=second_order.test"):
            self.assertIn(token, line, f"missing token: {token}")
        # ``hello world`` contains a space → quoted.
        self.assertIn('event="hello world"', line)

    def test_simple_event_string_is_unquoted(self) -> None:
        line = KeyValueFormatter().format(
            _make_record(msg="market_context_built"),
        )
        self.assertIn("event=market_context_built", line)

    def test_extra_context_appears_as_key_value_pairs(self) -> None:
        line = KeyValueFormatter().format(_make_record(
            msg="market_context_built",
            extra={"highlights": 3, "source": "yfinance"},
        ))
        self.assertIn("highlights=3", line)
        self.assertIn("source=yfinance", line)

    def test_value_with_spaces_is_quoted_and_escaped(self) -> None:
        line = KeyValueFormatter().format(_make_record(
            msg="event_with_quotes",
            extra={"note": 'has "quoted" words'},
        ))
        self.assertIn(r'note="has \"quoted\" words"', line)

    def test_log_event_emits_structured_line(self) -> None:
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(KeyValueFormatter())
        logger = logging.getLogger("second_order.test.log_event")
        # Local handler so we don't depend on global setup state.
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        log_event(logger, "snapshot_refreshed", count=8, source="yfinance")
        out = buf.getvalue()
        self.assertIn("event=snapshot_refreshed", out)
        self.assertIn("count=8", out)
        self.assertIn("source=yfinance", out)


class TestSetupLoggingIdempotent(unittest.TestCase):

    def test_repeat_calls_do_not_stack_handlers(self) -> None:
        # Use force=True for the first call to start from a clean slate
        # without disturbing the suite-wide root handler set elsewhere.
        setup_logging(force=True)
        baseline = len(logging.getLogger().handlers)
        setup_logging()
        setup_logging()
        setup_logging()
        self.assertEqual(
            len(logging.getLogger().handlers), baseline,
            "setup_logging must not stack handlers on repeat calls",
        )


if __name__ == "__main__":
    unittest.main()
