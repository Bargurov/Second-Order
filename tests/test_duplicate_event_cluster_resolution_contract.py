"""Contract tests for duplicate-event-cluster resolution.

Status — design only
--------------------
No duplicate-event-cluster resolution writer, planner, or CLI exists
yet.  The read-only diagnostic
(``routes.archive_diagnostics.compute_archive_consistency`` →
``duplicate_headline_event_date_clusters``, surfaced at
``GET /diagnostics/archive-consistency``) is live.

This file pins the safety contract from
``docs/duplicate_event_cluster_resolution_design.md`` so any future
writer cannot ship without satisfying it.

What this file pins
-------------------
* ``TestWriteSurfaceAbsent`` — there is no resolution module, no CLI
  script, and no write-shaped public callable on the obvious archive
  surfaces.  These guards flip red as soon as someone imports the
  writer name from anywhere; that is the desired signal.
* ``TestReadOnlyDiagnosticIsReadOnly`` — the cluster diagnostic
  remains read-only: its source imports no paid surfaces and the
  router exposes no write helper.
* ``TestWriteContractWhenLanded`` — future-behavior contract gated by
  a sentinel.  Skipped today; auto-activates when
  ``duplicate_event_cluster_resolution.apply_duplicate_event_cluster_resolution``
  ships.

When the writer lands, the absence pins in ``TestWriteSurfaceAbsent``
will need to be replaced by their flipped counterparts (CLI gate
tests, planner-shape tests) just as the event_date backfill
contract did.  This is intentional — the test changes are the
checklist for "is this writer safe to ship".
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db                                           # noqa: E402
from routes import archive_diagnostics              # noqa: E402


# ---------------------------------------------------------------------------
# Sentinel — does the future writer exist yet?
# ---------------------------------------------------------------------------

_RESOLUTION_MODULE_NAME = "duplicate_event_cluster_resolution"
_PLAN_FN_NAME           = "plan_duplicate_event_cluster_resolution"
_APPLY_FN_NAME          = "apply_duplicate_event_cluster_resolution"
_CLI_SCRIPT_REL_PATH    = (
    "scripts", "duplicate_event_cluster_resolution.py",
)


def _maybe_import_resolution_module():
    try:
        return importlib.import_module(_RESOLUTION_MODULE_NAME)
    except ImportError:
        return None


_RESOLUTION_MODULE = _maybe_import_resolution_module()
_APPLY_FN = (
    getattr(_RESOLUTION_MODULE, _APPLY_FN_NAME, None)
    if _RESOLUTION_MODULE is not None
    else None
)
_HAS_WRITER = callable(_APPLY_FN)
_SKIP_REASON = (
    "Duplicate-cluster writer not implemented yet; see "
    "docs/duplicate_event_cluster_resolution_design.md.  Add "
    f"{_RESOLUTION_MODULE_NAME}.{_APPLY_FN_NAME} to activate this contract."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Search for write-shaped names that target *event* clusters specifically,
# so this contract does not trip on adjacent unrelated helpers (e.g.
# ``db.delete_news_cluster`` lives in a different domain — news clusters
# are not events).
_EVENT_CLUSTER_WRITE_NEEDLES: tuple[str, ...] = (
    "duplicate_event",
    "event_cluster_resolution",
    "event_cluster_apply",
    "event_cluster_merge",
    "event_cluster_dedupe",
    "resolve_duplicate_event",
    "merge_duplicate_event",
    "dedupe_duplicate_event",
    "apply_duplicate_event",
)


_FORBIDDEN_PAID_MODULES: tuple[str, ...] = (
    "price_cache", "market_data", "market_check", "yfinance",
)


def _module_top_level_imports(module) -> set[str]:
    """Return the top-level module names this module imports.

    Parses the module source with ``ast`` so we only look at real
    ``import``/``from`` statements — docstring prose that mentions a
    module name (e.g. "never imports ``price_cache``") is ignored,
    which is exactly what makes this a load-bearing import check
    instead of a fragile substring sniff.
    """
    source = inspect.getsource(module)
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return imports


def _public_event_cluster_write_callables(module) -> list[str]:
    found: list[str] = []
    for name in dir(module):
        if name.startswith("_"):
            continue
        if not callable(getattr(module, name, None)):
            continue
        lowered = name.lower()
        if any(needle in lowered for needle in _EVENT_CLUSTER_WRITE_NEEDLES):
            found.append(name)
    return found


def _seed_event(*, headline: str, event_date, symbols=None,
                timestamp=None) -> None:
    ev = {
        "headline":       headline,
        "stage":          "realized",
        "persistence":    "medium",
        "event_date":     event_date,
        "market_tickers": [{"symbol": s.upper()} for s in (symbols or [])],
    }
    if timestamp is not None:
        ev["timestamp"] = timestamp
    db.save_event(ev)


class _DBBase(unittest.TestCase):
    """Isolated SQLite DB per test.  Mirrors the pattern in
    ``tests/test_event_date_backfill_write_contract.py`` so seed and
    snapshot semantics line up with the existing write-contract tests."""

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_dup_cluster_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db._db_ready = False
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        db._db_ready = False
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


def _snapshot_events(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute("SELECT * FROM events ORDER BY id"))


def _snapshot_price_cache(db_path: str) -> list[tuple] | None:
    """Return price_cache rows ordered, or ``None`` if the table is
    absent.  Pinning ``None`` accepts archives that don't materialise
    the table on init.  Pinning the row list catches any silent write."""
    with sqlite3.connect(db_path) as conn:
        try:
            return list(conn.execute(
                "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
                "FROM price_cache ORDER BY ticker, date, auto_adjust"
            ))
        except sqlite3.OperationalError:
            return None


# ---------------------------------------------------------------------------
# Current-state guards — assert no write/merge surface exists yet.
# ---------------------------------------------------------------------------


class TestWriteSurfaceAbsent(unittest.TestCase):
    """Pin the absence of a duplicate-event-cluster writer.

    Each test maps to a row in the design doc's safety contract: the
    writer cannot exist (Rule 1: planner-first), the CLI cannot exist
    (Rule 4: --write --confirm gate), and no write-shaped helper can
    have leaked onto the diagnostic or archive surfaces."""

    def test_resolution_module_does_not_exist(self) -> None:
        # Rule 1 — read-only preview must ship before the writer.
        # The writer module simply must not be importable today.
        self.assertIsNone(
            _RESOLUTION_MODULE,
            f"module {_RESOLUTION_MODULE_NAME!r} must not exist yet; "
            "design lives in docs/duplicate_event_cluster_resolution_design.md",
        )

    def test_resolution_cli_script_does_not_exist(self) -> None:
        # Rule 4 — the CLI gate is the only future write surface.
        # Until the planner ships, the CLI must not exist either.
        repo_root = Path(__file__).resolve().parents[1]
        cli_path = repo_root.joinpath(*_CLI_SCRIPT_REL_PATH)
        self.assertFalse(
            cli_path.exists(),
            f"CLI script {cli_path} must not exist yet",
        )

    def test_no_write_helper_on_archive_diagnostics(self) -> None:
        # Rule 8 — the read-only diagnostic stays read-only; no
        # write-shaped event-cluster callable may leak onto it.
        write_attrs = _public_event_cluster_write_callables(archive_diagnostics)
        self.assertEqual(
            write_attrs, [],
            "routes.archive_diagnostics must not expose a duplicate-"
            f"event-cluster write helper.  Found: {write_attrs}",
        )

    def test_no_write_helper_on_db_module(self) -> None:
        # Rule 5/8 — db.py must not gain a duplicate-event-cluster
        # write helper.  Existing news-cluster helpers (different
        # domain) are intentionally excluded by the needle list.
        write_attrs = _public_event_cluster_write_callables(db)
        self.assertEqual(
            write_attrs, [],
            "db must not expose a duplicate-event-cluster write helper.  "
            f"Found: {write_attrs}",
        )

    def test_apply_callable_is_unbound(self) -> None:
        # Cross-check the sentinel: the apply function name resolves
        # to None today; if a future change accidentally exposes it
        # before the contract is updated, this test fails fast.
        self.assertFalse(
            _HAS_WRITER,
            f"{_RESOLUTION_MODULE_NAME}.{_APPLY_FN_NAME} must not be "
            "callable yet; update the contract before exposing it.",
        )


# ---------------------------------------------------------------------------
# Read-only diagnostic — pin Rule 5 (no paid surfaces) for today's code.
# ---------------------------------------------------------------------------


class TestReadOnlyDiagnosticIsReadOnly(unittest.TestCase):
    """The duplicate-cluster diagnostic must remain a pure read."""

    def test_diagnostic_returns_count_and_examples_for_cluster_bucket(
        self,
    ) -> None:
        body = archive_diagnostics.compute_archive_consistency(
            db_path=":memory:",
        )
        bucket = body.get("duplicate_headline_event_date_clusters")
        self.assertIsInstance(bucket, dict)
        self.assertIn("count", bucket)
        self.assertIn("examples", bucket)
        self.assertIsInstance(bucket["count"], int)
        self.assertIsInstance(bucket["examples"], list)

    def test_archive_diagnostics_does_not_import_paid_surfaces(
        self,
    ) -> None:
        # Rule 5 — never touch price_cache.  Inspect actual import
        # statements (not docstring prose) so a future refactor that
        # adds a real ``import price_cache`` is caught immediately.
        imports = _module_top_level_imports(archive_diagnostics)
        for forbidden in _FORBIDDEN_PAID_MODULES:
            self.assertNotIn(
                forbidden, imports,
                f"routes.archive_diagnostics must not import "
                f"{forbidden!r} (Rule 5)",
            )

    def test_diagnostic_router_exposes_only_get_route(self) -> None:
        # Rule 8 — the read-only diagnostic does not gain a write
        # route.  The router should expose at most GET methods on the
        # archive-consistency path.
        router = archive_diagnostics.router
        for route in router.routes:
            methods = getattr(route, "methods", None) or set()
            path = getattr(route, "path", "")
            if path == "/diagnostics/archive-consistency":
                self.assertEqual(
                    set(methods), {"GET"},
                    f"archive-consistency route must be GET-only, got {methods}",
                )


# ---------------------------------------------------------------------------
# Future-behavior contract — auto-activates when the writer ships.
# Each test maps to a numbered rule in
# docs/duplicate_event_cluster_resolution_design.md.
# ---------------------------------------------------------------------------


@unittest.skipUnless(_HAS_WRITER, _SKIP_REASON)
class TestWriteContractWhenLanded(_DBBase):

    # Rule 2 — no deletion by default ----------------------------------

    def test_apply_default_confirm_is_false(self) -> None:
        sig = inspect.signature(_APPLY_FN)
        confirm = sig.parameters.get("confirm")
        self.assertIsNotNone(
            confirm,
            "apply_duplicate_event_cluster_resolution must accept a "
            "`confirm` keyword argument (Rule 2)",
        )
        self.assertEqual(
            confirm.default, False,
            "Rule 2 — `confirm` must default to False so the function "
            "writes nothing unless explicitly opted into",
        )

    def test_apply_without_confirm_writes_nothing(self) -> None:
        # Seed an exact-duplicate cluster so a future writer would
        # have something to merge.  Without confirm=True the writer
        # must leave the table byte-identical.
        _seed_event(
            headline="dup", event_date="2026-04-15", symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        _seed_event(
            headline="dup", event_date="2026-04-15", symbols=["AAPL"],
            timestamp="2026-04-15T13:30:00",
        )
        before_events = _snapshot_events(self._tmp)
        before_cache  = _snapshot_price_cache(self._tmp)
        _APPLY_FN(db_path=self._tmp, confirm=False)
        after_events  = _snapshot_events(self._tmp)
        after_cache   = _snapshot_price_cache(self._tmp)
        self.assertEqual(
            before_events, after_events,
            "Rule 2 — apply(confirm=False) must not mutate `events`",
        )
        self.assertEqual(
            before_cache, after_cache,
            "Rule 5 — apply must never touch price_cache",
        )

    # Rule 5 — never touch price_cache --------------------------------

    def test_resolution_module_does_not_import_paid_surfaces(self) -> None:
        imports = _module_top_level_imports(_RESOLUTION_MODULE)
        for forbidden in _FORBIDDEN_PAID_MODULES:
            self.assertNotIn(
                forbidden, imports,
                f"Rule 5 — {_RESOLUTION_MODULE_NAME} must not import "
                f"{forbidden!r}",
            )

    # Rule 1 — planner ships first ------------------------------------

    def test_planner_function_exists(self) -> None:
        plan_fn = getattr(_RESOLUTION_MODULE, _PLAN_FN_NAME, None)
        self.assertTrue(
            callable(plan_fn),
            f"Rule 1 — {_RESOLUTION_MODULE_NAME}.{_PLAN_FN_NAME} must "
            "ship before any writer code can be considered green",
        )


if __name__ == "__main__":
    unittest.main()
