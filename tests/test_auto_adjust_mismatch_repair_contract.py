"""Contract tests for a future auto-adjust mismatch repair writer.

Status — design only / not yet specified
----------------------------------------
The auto-adjust mismatch surface is *read-only* today:

  * ``routes.diagnostics._classify_no_forward_20d_subreason`` →
    ``auto_adjust_mismatch_for_20d`` bucket on
    ``GET /diagnostics/no-forward-20d-blockers``.
  * ``price_cache_refresh.plan_refresh`` (gap-mode-20d) surfaces the
    ``auto_adjust_mismatch_20d`` skip bucket; the planner counts the
    case but issues no provider call and writes nothing.

No repair *writer*, planner, or CLI exists.  This file pins the
safety contract any future writer must satisfy before it can ship.

What this file pins
-------------------
* ``TestRepairSurfaceAbsent`` — the writer module, the CLI script,
  and any write-shaped public callable on the obvious diagnostic /
  refresh / cache / db surfaces are absent.  These guards flip red
  the moment someone exposes the writer name from anywhere; that is
  the desired signal.
* ``TestReadOnlyDiagnosticIsReadOnly`` — the existing diagnostic
  bucket name does not drift, the diagnostics router does not import
  the future writer module, and the route stays GET-only.
* ``TestRepairContractWhenLanded`` — full safety contract, gated by
  a sentinel.  Skipped today; auto-activates when
  ``auto_adjust_mismatch_repair.apply_auto_adjust_mismatch_repair``
  ships.  Each test pins one rule from the constraints recorded in
  the docstring of that class.

When the writer lands, the absence pins in
``TestRepairSurfaceAbsent`` will need to be replaced by their flipped
counterparts (CLI gate tests, planner-shape tests, audit-log tests)
just as the event_date backfill contract was updated.  The test
changes are intentional — they are the checklist for "is this writer
safe to ship".
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
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db                                              # noqa: E402
# ``routes.diagnostics`` imports ``api`` which in turn imports
# ``routes.diagnostics.router``.  Importing ``api`` first breaks the
# circular-import init order so the diagnostics module is fully
# populated by the time we reference it.
import api  # noqa: E402,F401
import price_cache as _price_cache_mod                 # noqa: E402
import price_cache_refresh as _refresh_mod             # noqa: E402
from routes import diagnostics as _diagnostics_route   # noqa: E402


# ---------------------------------------------------------------------------
# Sentinel — does the future writer exist yet?
# ---------------------------------------------------------------------------

# NAMING ASSUMPTION — the future writer is expected to land at module
# ``auto_adjust_mismatch_repair`` and CLI ``scripts/auto_adjust_mismatch_repair.py``,
# matching the precedent set by ``event_date_backfill`` and
# ``refresh_price_cache`` (preview + writer share one module / script).
# If a future author picks a different name (e.g. ``auto_adjust_flag_fix``)
# the absence guards below will silently keep passing and the sentinel
# will never activate — update the four constants as the first step of
# any rename.
_REPAIR_MODULE_NAME = "auto_adjust_mismatch_repair"
_PLAN_FN_NAME       = "plan_auto_adjust_mismatch_repair"
_APPLY_FN_NAME      = "apply_auto_adjust_mismatch_repair"
_CLI_SCRIPT_REL_PATH = ("scripts", "auto_adjust_mismatch_repair.py")


def _maybe_import_repair_module():
    try:
        return importlib.import_module(_REPAIR_MODULE_NAME)
    except ImportError:
        return None


_REPAIR_MODULE = _maybe_import_repair_module()
_APPLY_FN = (
    getattr(_REPAIR_MODULE, _APPLY_FN_NAME, None)
    if _REPAIR_MODULE is not None
    else None
)
_HAS_WRITER = callable(_APPLY_FN)
_SKIP_REASON = (
    "auto-adjust mismatch repair writer not implemented yet.  Add "
    f"{_REPAIR_MODULE_NAME}.{_APPLY_FN_NAME} to activate this contract."
)


# Search for write-shaped names that target *auto_adjust mismatch*
# repair specifically, so this contract does not trip on adjacent
# helpers.  Bare "fix" / "apply" / "repair" intentionally are not
# matched alone — they collide with too many existing benign
# helpers.  The needles below all carry the domain anchor.
_REPAIR_WRITE_NEEDLES: tuple[str, ...] = (
    "auto_adjust_mismatch_repair",
    "auto_adjust_mismatch_apply",
    "auto_adjust_mismatch_fix",
    "auto_adjust_mismatch_write",
    "repair_auto_adjust_mismatch",
    "apply_auto_adjust_mismatch",
    "fix_auto_adjust_mismatch",
    "write_auto_adjust_mismatch",
)


# ``price_cache`` is *not* listed here — the future writer
# legitimately needs to manipulate the price_cache table.  What the
# writer must not do is reach the network or call a paid provider /
# LLM seam.  These three top-level imports prove that contract.
_FORBIDDEN_PAID_MODULES: tuple[str, ...] = (
    "market_data",
    "market_check",
    "yfinance",
    "analyze_event",
    "auto_backfill_runner",
)


def _module_top_level_imports(module) -> set[str]:
    """Return the top-level module names this module imports.

    Parses the module source with ``ast`` so we only look at real
    ``import``/``from`` statements — docstring prose that mentions a
    module name (e.g. "never imports ``market_data``") is ignored,
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


def _public_repair_write_callables(module) -> list[str]:
    found: list[str] = []
    for name in dir(module):
        if name.startswith("_"):
            continue
        if not callable(getattr(module, name, None)):
            continue
        lowered = name.lower()
        if any(needle in lowered for needle in _REPAIR_WRITE_NEEDLES):
            found.append(name)
    return found


# ---------------------------------------------------------------------------
# Helpers — DB scaffolding, mirroring the precedent set by the
# event_date backfill / duplicate-cluster contract tests.
# ---------------------------------------------------------------------------


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


def _insert_price_cache_row(
    db_path: str,
    *,
    ticker: str,
    date_str: str,
    close: float,
    volume: int,
    auto_adjust: int,
    fetched_at: str,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO price_cache "
            "(ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticker, date_str, close, volume, auto_adjust, fetched_at),
        )
        conn.commit()


def _snapshot_events(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute("SELECT * FROM events ORDER BY id"))


def _snapshot_market_tickers(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute(
            "SELECT id, market_tickers FROM events ORDER BY id"
        ))


def _snapshot_price_cache(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute(
            "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
            "FROM price_cache ORDER BY ticker, date, auto_adjust"
        ))


class _DBBase(unittest.TestCase):
    """Isolated SQLite DB per test.  Mirrors the pattern in
    ``tests/test_event_date_backfill_write_contract.py`` and
    ``tests/test_duplicate_event_cluster_resolution_contract.py`` so
    seed and snapshot semantics line up with the existing
    write-contract tests."""

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_aa_repair_{uuid.uuid4().hex}.db",
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

    # When the writer ships it will accept some subset of
    # ``db_path`` / ``confirm`` / a backup-target kwarg.  Build the
    # call-time kwargs against the live signature so this test file
    # does not have to be edited if the writer adds further keyword
    # arguments down the line — the contract pins the *required*
    # kwargs, not the full signature.
    def _build_apply_kwargs(
        self, *, confirm: bool, with_backup: bool,
    ) -> dict:
        sig = inspect.signature(_APPLY_FN)
        kwargs: dict = {}
        if "db_path" in sig.parameters:
            kwargs["db_path"] = self._tmp
        if "confirm" in sig.parameters:
            kwargs["confirm"] = confirm
        if with_backup:
            for kw in sig.parameters:
                if "backup" in kw.lower():
                    kwargs[kw] = os.path.join(
                        tempfile.gettempdir(),
                        f"aa_repair_backup_{uuid.uuid4().hex}.db",
                    )
        return kwargs


# ---------------------------------------------------------------------------
# Current-state guards — assert no repair surface exists yet.
# ---------------------------------------------------------------------------


class TestRepairSurface(unittest.TestCase):
    """Pin the presence of the auto-adjust mismatch repair writer.

    The writer has shipped: the module ``auto_adjust_mismatch_repair``
    exposes ``plan_*`` and ``apply_*`` callables and the CLI gate at
    ``scripts/auto_adjust_mismatch_repair.py`` enforces ``--write
    --confirm --backup-path``.  These three tests are the flipped
    counterparts of the original absence guards (see this file's
    module docstring for context); the six "no write helper on X
    module" tests below stay as-is and continue to guard against the
    writer leaking onto adjacent modules where it could bypass the
    contract.
    """

    def test_repair_module_exists(self) -> None:
        self.assertIsNotNone(
            _REPAIR_MODULE,
            f"module {_REPAIR_MODULE_NAME!r} must be importable now "
            "that the writer has shipped",
        )

    def test_repair_cli_script_exists(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        cli_path = repo_root.joinpath(*_CLI_SCRIPT_REL_PATH)
        self.assertTrue(
            cli_path.exists(),
            f"CLI script {cli_path} must exist now that the writer "
            "has shipped — it is the only sanctioned write surface.",
        )

    def test_apply_callable_is_bound(self) -> None:
        self.assertTrue(
            _HAS_WRITER,
            f"{_REPAIR_MODULE_NAME}.{_APPLY_FN_NAME} must be callable "
            "now that the writer has shipped.",
        )

    def test_no_write_helper_on_diagnostics_route(self) -> None:
        write_attrs = _public_repair_write_callables(_diagnostics_route)
        self.assertEqual(
            write_attrs, [],
            "routes.diagnostics must not expose an auto-adjust mismatch "
            f"repair helper.  Found: {write_attrs}",
        )

    def test_no_write_helper_on_price_cache_module(self) -> None:
        write_attrs = _public_repair_write_callables(_price_cache_mod)
        self.assertEqual(
            write_attrs, [],
            "price_cache must not expose an auto-adjust mismatch repair "
            f"helper.  Found: {write_attrs}",
        )

    def test_no_write_helper_on_price_cache_refresh_module(self) -> None:
        write_attrs = _public_repair_write_callables(_refresh_mod)
        self.assertEqual(
            write_attrs, [],
            "price_cache_refresh must not expose an auto-adjust mismatch "
            f"repair helper.  Found: {write_attrs}",
        )

    def test_no_write_helper_on_db_module(self) -> None:
        write_attrs = _public_repair_write_callables(db)
        self.assertEqual(
            write_attrs, [],
            "db must not expose an auto-adjust mismatch repair helper.  "
            f"Found: {write_attrs}",
        )


# ---------------------------------------------------------------------------
# Read-only diagnostic — pin "diagnostic stays read-only" for today's code.
# ---------------------------------------------------------------------------


class TestReadOnlyDiagnosticIsReadOnly(unittest.TestCase):
    """The existing auto-adjust mismatch surface must remain a pure read."""

    def test_diagnostic_bucket_name_is_stable(self) -> None:
        # If the bucket name drifts, every contract test below
        # silently goes off the rails; pin it explicitly.
        self.assertIn(
            "auto_adjust_mismatch_for_20d",
            _diagnostics_route._NF20_REASON_KEYS,
        )

    def test_classifier_returns_mismatch_when_other_flag_covers_target(
        self,
    ) -> None:
        # Sanity-check the classifier returns the bucket name we are
        # contracting against.  If a future refactor renames the
        # bucket, this test fails before the writer is even built,
        # surfacing the rename for the operator to reconcile.
        sub = _diagnostics_route._classify_no_forward_20d_subreason(
            event_d=_date(2026, 1, 5),
            today=_date(2026, 5, 7),
            aa_false_max=_date(2026, 1, 6),
            aa_true_max=_date(2026, 5, 7),
        )
        self.assertEqual(sub, "auto_adjust_mismatch_for_20d")

    def test_diagnostics_module_does_not_import_repair_module(self) -> None:
        imports = _module_top_level_imports(_diagnostics_route)
        self.assertNotIn(
            _REPAIR_MODULE_NAME, imports,
            f"routes.diagnostics must not import {_REPAIR_MODULE_NAME!r} — "
            "the diagnostic stays a pure read",
        )

    def test_no_forward_20d_blockers_route_is_get_only(self) -> None:
        router = _diagnostics_route.router
        for route in router.routes:
            path = getattr(route, "path", "")
            if path == "/diagnostics/no-forward-20d-blockers":
                methods = getattr(route, "methods", None) or set()
                self.assertEqual(
                    set(methods), {"GET"},
                    f"no-forward-20d-blockers route must be GET-only; "
                    f"got {methods}",
                )


# ---------------------------------------------------------------------------
# Future-behavior contract — auto-activates when the writer ships.
# Every test maps to one rule the future design doc must record.
# ---------------------------------------------------------------------------


@unittest.skipUnless(_HAS_WRITER, _SKIP_REASON)
class TestRepairContractWhenLanded(_DBBase):
    """Sentinel-gated contract.  Skipped today; activates the moment
    ``auto_adjust_mismatch_repair.apply_auto_adjust_mismatch_repair``
    becomes callable.  Each test pins one rule:

      Rule 1 — planner ships first (preview mode).
      Rule 2 — ``confirm`` defaults to False; preview is the default.
      Rule 3 — writer enforces a backup target.
      Rule 4 — never call provider, ``yfinance``, or LLM seams.
      Rule 5 — never mutate ``events.market_tickers``.
      Rule 6 — every applied repair appends to a tamper-evident
                audit log surfaced in the result.
      Rule 7 — no FastAPI route surface for writes.
    """

    # Rule 1 — planner ships first ------------------------------------

    def test_planner_function_exists(self) -> None:
        plan_fn = getattr(_REPAIR_MODULE, _PLAN_FN_NAME, None)
        self.assertTrue(
            callable(plan_fn),
            f"Rule 1 — {_REPAIR_MODULE_NAME}.{_PLAN_FN_NAME} must "
            "ship before any writer code can be considered green",
        )

    # Rule 2 — confirm defaults to False; preview is the default mode -

    def test_apply_default_confirm_is_false(self) -> None:
        sig = inspect.signature(_APPLY_FN)
        confirm = sig.parameters.get("confirm")
        self.assertIsNotNone(
            confirm,
            f"Rule 2 — {_APPLY_FN_NAME} must accept a `confirm` "
            "keyword argument",
        )
        self.assertEqual(
            confirm.default, False,
            "Rule 2 — `confirm` must default to False so the function "
            "writes nothing unless explicitly opted into",
        )

    def test_apply_without_confirm_writes_nothing(self) -> None:
        # Materialise a true auto_adjust_mismatch_for_20d state: an
        # event whose 20d horizon is past today, with cache rows
        # only at auto_adjust=1.  A future writer would have work to
        # do here; without confirm=True it must do none of it.
        _seed_event(
            headline="mismatch repair candidate",
            event_date="2026-01-05",
            symbols=["AAPL"],
            timestamp="2026-01-05T13:30:00",
        )
        _insert_price_cache_row(
            self._tmp, ticker="AAPL", date_str="2026-02-02",
            close=180.0, volume=1000, auto_adjust=1,
            fetched_at="2026-02-02T20:00:00Z",
        )
        before_events = _snapshot_events(self._tmp)
        before_cache  = _snapshot_price_cache(self._tmp)
        kwargs = self._build_apply_kwargs(confirm=False, with_backup=False)
        _APPLY_FN(**kwargs)
        after_events  = _snapshot_events(self._tmp)
        after_cache   = _snapshot_price_cache(self._tmp)
        self.assertEqual(
            before_events, after_events,
            "Rule 2 — apply(confirm=False) must not mutate `events`",
        )
        self.assertEqual(
            before_cache, after_cache,
            "Rule 2 — apply(confirm=False) must not mutate `price_cache`",
        )

    # Rule 3 — backup required ----------------------------------------

    def test_apply_signature_carries_backup_kwarg(self) -> None:
        # The writer must surface a backup-target kwarg so an
        # operator cannot run a repair without naming the backup
        # snapshot.  We accept any kwarg containing "backup" in its
        # name (e.g. ``backup_path``, ``backup_db_path``,
        # ``backup_dir``) — the contract is the *intent*, not a
        # specific spelling.
        sig = inspect.signature(_APPLY_FN)
        backup_kwargs = [n for n in sig.parameters if "backup" in n.lower()]
        self.assertTrue(
            backup_kwargs,
            f"Rule 3 — {_APPLY_FN_NAME} must accept a backup-target "
            "kwarg so the operator cannot run a write without naming "
            "a snapshot file",
        )

    # Rule 4 — never call provider / yfinance / LLM seams -------------

    def test_repair_module_does_not_import_paid_surfaces(self) -> None:
        imports = _module_top_level_imports(_REPAIR_MODULE)
        for forbidden in _FORBIDDEN_PAID_MODULES:
            self.assertNotIn(
                forbidden, imports,
                f"Rule 4 — {_REPAIR_MODULE_NAME} must not import "
                f"{forbidden!r}",
            )

    def test_apply_does_not_call_provider_yfinance_or_llm(self) -> None:
        # Belt-and-braces: even if the import check is satisfied,
        # patch every paid seam we can find so a transitive call
        # surfaces as an AssertionError.  Mirrors the seam list used
        # by ``test_event_date_backfill_write_contract``.
        from contextlib import ExitStack
        from unittest.mock import patch

        _seed_event(
            headline="paid-surface guard",
            event_date="2026-01-05",
            symbols=["AAPL"],
            timestamp="2026-01-05T13:30:00",
        )
        _insert_price_cache_row(
            self._tmp, ticker="AAPL", date_str="2026-02-02",
            close=180.0, volume=1000, auto_adjust=1,
            fetched_at="2026-02-02T20:00:00Z",
        )

        candidate_seams = (
            ("market_check", "_fetch"),
            ("market_check", "_fetch_since"),
            ("market_check", "market_check"),
            ("market_check", "_check_one_ticker"),
            ("market_data",  "get_provider"),
            ("market_data",  "reload_provider_from_env"),
            ("price_cache",  "fetch_daily_cached"),
            ("analyze_event",      "analyze_event"),
            ("auto_backfill_runner", "execute_paid_candidate"),
        )
        with ExitStack() as stack:
            for module_name, attr in candidate_seams:
                try:
                    mod = __import__(module_name)
                except Exception:
                    continue
                if not hasattr(mod, attr):
                    continue
                stack.enter_context(patch.object(
                    mod, attr,
                    side_effect=AssertionError(
                        f"{_APPLY_FN_NAME} must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        f"{_APPLY_FN_NAME} must not call yfinance",
                    ),
                ))
            except ImportError:
                pass

            kwargs = self._build_apply_kwargs(
                confirm=True, with_backup=True,
            )
            _APPLY_FN(**kwargs)

    # Rule 5 — never mutate market_tickers ----------------------------

    def test_apply_does_not_mutate_market_tickers(self) -> None:
        _seed_event(
            headline="market_tickers guard",
            event_date="2026-01-05",
            symbols=["AAPL", "MSFT"],
            timestamp="2026-01-05T13:30:00",
        )
        _insert_price_cache_row(
            self._tmp, ticker="AAPL", date_str="2026-02-02",
            close=180.0, volume=1000, auto_adjust=1,
            fetched_at="2026-02-02T20:00:00Z",
        )
        before = _snapshot_market_tickers(self._tmp)
        kwargs = self._build_apply_kwargs(confirm=True, with_backup=True)
        _APPLY_FN(**kwargs)
        after = _snapshot_market_tickers(self._tmp)
        self.assertEqual(
            before, after,
            "Rule 5 — apply must never mutate events.market_tickers; "
            "the repair touches price_cache only",
        )

    # Rule 6 — audit log required -------------------------------------

    def test_apply_surfaces_audit_log_path(self) -> None:
        _seed_event(
            headline="audit-log guard",
            event_date="2026-01-05",
            symbols=["AAPL"],
            timestamp="2026-01-05T13:30:00",
        )
        _insert_price_cache_row(
            self._tmp, ticker="AAPL", date_str="2026-02-02",
            close=180.0, volume=1000, auto_adjust=1,
            fetched_at="2026-02-02T20:00:00Z",
        )
        kwargs = self._build_apply_kwargs(confirm=True, with_backup=True)
        result = _APPLY_FN(**kwargs)

        self.assertIsInstance(
            result, dict,
            "Rule 6 — apply must return a dict carrying an audit-log key",
        )
        audit_keys = [k for k in result if "audit" in k.lower()]
        self.assertTrue(
            audit_keys,
            "Rule 6 — apply result must surface an audit-log key "
            f"(e.g. `audit_log_path`).  Got keys: {sorted(result)}",
        )

        # If at least one repair landed, the audit log file must
        # exist on disk.  We do not pin the JSONL schema here — the
        # design doc that accompanies the writer pins the fields —
        # only that the file is materialised when a write happens.
        applied = result.get("applied_count")
        if isinstance(applied, int) and applied > 0:
            audit_path = result.get(audit_keys[0])
            self.assertIsInstance(
                audit_path, str,
                "Rule 6 — audit-log key must carry a str path",
            )
            self.assertTrue(
                os.path.exists(audit_path),
                f"Rule 6 — audit log must exist at {audit_path}",
            )

    # Rule 7 — no FastAPI route surface for writes --------------------

    def test_repair_module_does_not_expose_fastapi_app_or_router(self) -> None:
        self.assertFalse(
            hasattr(_REPAIR_MODULE, "app"),
            "Rule 7 — repair module must not host a FastAPI app",
        )
        self.assertFalse(
            hasattr(_REPAIR_MODULE, "router"),
            "Rule 7 — repair module must not host a FastAPI router",
        )


if __name__ == "__main__":
    unittest.main()
