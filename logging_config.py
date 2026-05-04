"""Shared structured-logging setup for the backend.

Single ``setup_logging()`` entrypoint installs a logfmt-style root
handler so log lines stay readable AND grep cleanly:

    time=2026-05-05T12:34:56 level=INFO logger=second_order.api event="market_context_built" highlights=3 source=yfinance

Existing ``logger.info("message")`` calls keep working unchanged —
their message lands in the ``event`` field verbatim, no rewrite
required.  Callers that want structured context can pass it via the
standard ``extra=`` kwarg or via ``log_event(...)`` below.

The setup is idempotent — repeated calls don't stack handlers.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

# Built-in attributes Python attaches to every LogRecord.  The
# formatter ignores these when scanning for user-supplied context so
# only true ``extra=`` kwargs become key=value pairs.
_LOGRECORD_BUILTINS: frozenset[str] = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
})

_INSTALLED_FLAG: str = "_second_order_logging_installed"


def _quote(value: Any) -> str:
    """Render ``value`` as a logfmt token: bare when safe, quoted when not.

    The quoting rule is the standard logfmt one — wrap the token if it
    contains whitespace, an ``=`` sign, or a double quote, and escape
    embedded backslashes/quotes inside the wrap.
    """
    s = str(value) if value is not None else ""
    if not s:
        return '""'
    if any(c in s for c in (" ", "\t", '"', "=")) or s[0] == '"':
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


class KeyValueFormatter(logging.Formatter):
    """Logfmt-style formatter — ``time=... level=... logger=... event=...``.

    Any user-supplied attributes on the record (passed via ``extra=``
    or ``log_event(**ctx)``) are appended in insertion order as
    ``key=value`` pairs.  Unknown types are str()-coerced.
    """

    default_time_format = "%Y-%m-%dT%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        time_str = self.formatTime(record, self.default_time_format)
        parts: list[str] = [
            f"time={time_str}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"event={_quote(record.message)}",
        ]
        for key, value in record.__dict__.items():
            if key in _LOGRECORD_BUILTINS or key.startswith("_"):
                continue
            parts.append(f"{key}={_quote(value)}")
        line = " ".join(parts)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def setup_logging(
    level: int | str | None = None,
    *,
    force: bool = False,
    stream=None,
) -> logging.Logger:
    """Install the shared key=value formatter on the root logger.

    Idempotent: a second call without ``force=True`` is a no-op so
    importing this module from multiple entry points (``api.py``,
    tests, scripts) doesn't stack handlers and double-print log lines.

    Args:
        level: Log level (``str`` or ``int``).  Defaults to the
            ``LOG_LEVEL`` env var (case-insensitive) or ``INFO``.
        force: Reinstall even when setup has already run.  Test fixtures
            that need to capture log output use this.
        stream: Output stream for the handler.  Default ``sys.stderr``.

    Returns: the root logger.
    """
    root = logging.getLogger()
    if getattr(root, _INSTALLED_FLAG, False) and not force:
        return root
    if force:
        for h in list(root.handlers):
            root.removeHandler(h)
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(KeyValueFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    setattr(root, _INSTALLED_FLAG, True)
    return root


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **context: Any,
) -> None:
    """Emit a structured log record.

    ``event`` becomes the LogRecord's message; ``**context`` becomes
    record attributes the formatter renders as ``key=value`` pairs.

    Equivalent to ``logger.log(level, event, extra=context)`` but
    spares the caller the ``extra=`` boilerplate and short-circuits
    when the level is disabled.
    """
    if not logger.isEnabledFor(level):
        return
    logger.log(level, event, extra=context)
