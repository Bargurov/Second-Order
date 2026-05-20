"""Tests for ``scripts/xle_benchmark_sensitivity_compare_smoke.py``.

Pin the contract:

* Read-only by construction.  No DB writes, no provider, no
  ``yfinance``, no LLM, no FastAPI surface.  The compare smoke calls
  the preflight (which itself only issues ``SELECT``) and a single
  patchable seam for the per-(event, benchmark) sensitivity result.
* ``--db-path`` is required.  No fall-through to ``db.DB_FILE``.
* The smoke is **gated** by the preflight.  If preflight reports
  ``blocked_count > 0`` for either SPY or XLE, the smoke returns
  ``ok=False`` with the blocker reasons surfaced verbatim in
  ``errors``; ``comparisons`` is empty.
* When the preflight clears, the smoke calls the seam twice per event
  (once with SPY, once with XLE) and reports descriptive sensitivity
  only.  Causality, validation, or alpha claims are forbidden.
* Output dict has EXACTLY these 9 keys::

    ok, db_path, checked_events, blocked_count, comparisons,
    interpretation_changes, warnings, errors, recommended_next_action

* Each comparison has EXACTLY these 9 keys::

    event_id, primary_ticker, event_date,
    spy_result, xle_result, spy_blocker, xle_blocker,
    changed_interpretation, note

  ``spy_blocker`` / ``xle_blocker`` are ``None`` when the seam
  produced a result, and a structured 6-field dict
  (``event_id``, ``benchmark_ticker``, ``missing_ticker``,
  ``missing_dates``, ``missing_range``, ``horizon``, ``reason``)
  when it did not.

* Conservative wording — banned tokens absent from any text the
  smoke emits.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date as _date, timedelta as _timedelta
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import xle_benchmark_sensitivity_compare_smoke as cli  # noqa: E402
from scripts import benchmark_sensitivity_preflight as preflight_cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "db_path",
    "checked_events",
    "blocked_count",
    "comparisons",
    "interpretation_changes",
    "warnings",
    "errors",
    "recommended_next_action",
)


_COMPARISON_KEYS = (
    "event_id",
    "primary_ticker",
    "event_date",
    "spy_result",
    "xle_result",
    "spy_blocker",
    "xle_blocker",
    "changed_interpretation",
    "note",
)


_BLOCKER_KEYS = (
    "event_id",
    "benchmark_ticker",
    "missing_ticker",
    "missing_dates",
    "missing_range",
    "horizon",
    "reason",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "validated",
    "automatically",
    "alpha generated",
    "correct ticker",
    "guaranteed",
    # No-causality / no-validation guardrails.
    "causes",
    "caused",
    "proves",
    "confirms",
    "validates",
)


# ---------------------------------------------------------------------------
# Synthetic preflight payloads
# ---------------------------------------------------------------------------


def _ready_row(event_id: int, event_date: str, benchmark: str) -> dict[str, Any]:
    return {
        "event_id":                  event_id,
        "primary_ticker":            "XOM",
        "benchmark_ticker":          benchmark,
        "event_date":                event_date,
        "required_horizons":         [1, 5, 20],
        "primary_cache_available":   True,
        "benchmark_cache_available": True,
        "missing_primary_ranges":    [],
        "missing_benchmark_ranges":  [],
        "can_run_sensitivity":       True,
        "blocker_reason":            "ready",
    }


def _blocked_row(
    event_id: int, event_date: str, benchmark: str,
    blocker_reason: str = "benchmark XLE: estimation_window_short",
) -> dict[str, Any]:
    return {
        "event_id":                  event_id,
        "primary_ticker":            "XOM",
        "benchmark_ticker":          benchmark,
        "event_date":                event_date,
        "required_horizons":         [1, 5, 20],
        "primary_cache_available":   True,
        "benchmark_cache_available": False,
        "missing_primary_ranges":    [],
        "missing_benchmark_ranges":  [
            {"start": "2026-01-01", "end": "2026-01-02",
             "reason": "estimation_window_short"},
        ],
        "can_run_sensitivity":       False,
        "blocker_reason":            blocker_reason,
    }


def _cleared_payload(benchmark: str) -> dict[str, Any]:
    return {
        "ok":            True,
        "checked_events": 2,
        "ready_count":   2,
        "blocked_count": 0,
        "rows": [
            _ready_row(60, "2026-04-08", benchmark),
            _ready_row(73, "2026-04-06", benchmark),
        ],
        "recommended_next_action": "",
    }


def _blocked_payload(benchmark: str) -> dict[str, Any]:
    return {
        "ok":            True,
        "checked_events": 2,
        "ready_count":   0,
        "blocked_count": 2,
        "rows": [
            _blocked_row(60, "2026-04-08", benchmark),
            _blocked_row(73, "2026-04-06", benchmark),
        ],
        "recommended_next_action": "",
    }


def _make_preflight_side_effect(
    *,
    spy_payload: dict[str, Any] | None = None,
    xle_payload: dict[str, Any] | None = None,
):
    """Return a side_effect callable that dispatches the patched
    preflight on the ``benchmark`` kwarg so the smoke can be exercised
    with independent SPY / XLE payloads in a single run."""
    spy_payload = spy_payload or _cleared_payload("SPY")
    xle_payload = xle_payload or _cleared_payload("XLE")

    def _side(*args, **kwargs):
        bench = (kwargs.get("benchmark") or "").strip().upper()
        if bench == "SPY":
            return spy_payload
        if bench == "XLE":
            return xle_payload
        # Anything else — return a clean empty payload so the smoke
        # produces no rows for it.
        return {
            "ok":            True,
            "checked_events": 0,
            "ready_count":   0,
            "blocked_count": 0,
            "rows":          [],
            "recommended_next_action": "",
        }

    return _side


def _patch_preflight(side_effect):
    return patch.object(
        preflight_cli,
        "summarize_benchmark_sensitivity_preflight",
        side_effect=side_effect,
    )


def _make_seam_side_effect(
    *,
    spy_results: dict[int, dict[str, Any] | None] | None = None,
    xle_results: dict[int, dict[str, Any] | None] | None = None,
):
    """Return a side_effect callable for the sensitivity seam keyed by
    (event_id, benchmark)."""
    spy_results = spy_results or {}
    xle_results = xle_results or {}

    def _side(*, db_path, event_id, event_date, primary_ticker,
              benchmark, horizons, estimation_window):
        bench = (benchmark or "").strip().upper()
        if bench == "SPY":
            return spy_results.get(event_id)
        if bench == "XLE":
            return xle_results.get(event_id)
        return None

    return _side


def _patch_seam(side_effect):
    return patch.object(
        cli, "_compute_sensitivity_for_benchmark",
        side_effect=side_effect,
    )


def _result(*, raw_p, fdr_q, significant, sar=None) -> dict[str, Any]:
    return {
        "raw_p":       raw_p,
        "fdr_q":       fdr_q,
        "significant": significant,
        "sar":         sar,
    }


def _stub_db_path() -> str:
    """A tempfile that exists on disk so the `--db-path` existence
    guard passes.  Compare smoke never reads it: the preflight is
    patched, and so is the seam."""
    path = os.path.join(
        tempfile.gettempdir(),
        f"xle_compare_stub_{uuid.uuid4().hex}.db",
    )
    with open(path, "wb") as fh:
        fh.write(b"")
    return path


# ---------------------------------------------------------------------------
# --db-path is required
# ---------------------------------------------------------------------------


class TestDbPathRequired(unittest.TestCase):
    def test_missing_db_path_returns_failure_envelope(self) -> None:
        report = cli.run_xle_benchmark_sensitivity_compare_smoke(
            db_path=None,
        )
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "--db-path" in e or "db_path" in e for e in report["errors"]
        ), f"errors: {report['errors']}")

    def test_nonexistent_db_path_returns_failure_envelope(self) -> None:
        report = cli.run_xle_benchmark_sensitivity_compare_smoke(
            db_path="/nonexistent/events.db",
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "db_path" in e.lower() or "does not exist" in e.lower()
            for e in report["errors"]
        ))

    def test_cli_without_db_path_exits_nonzero(self) -> None:
        # argparse should mark --db-path as required and reject the run.
        buf = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            cli.main(["--json"], out=buf)
        # argparse exits 2 on missing required args.
        self.assertNotEqual(ctx.exception.code, 0)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_cleared_run_has_required_keys(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.10, fdr_q=0.12, significant=False),
                        73: _result(raw_p=0.10, fdr_q=0.12, significant=False),
                    },
                    xle_results={
                        60: _result(raw_p=0.20, fdr_q=0.25, significant=False),
                        73: _result(raw_p=0.20, fdr_q=0.25, significant=False),
                    },
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60, 73),
                )
            self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
            self.assertEqual(report["db_path"], db)
            self.assertEqual(report["checked_events"], 2)
            self.assertEqual(report["blocked_count"], 0)
        finally:
            os.unlink(db)

    def test_each_comparison_has_required_keys(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.10, fdr_q=0.12, significant=False),
                        73: _result(raw_p=0.10, fdr_q=0.12, significant=False),
                    },
                    xle_results={
                        60: _result(raw_p=0.20, fdr_q=0.25, significant=False),
                        73: _result(raw_p=0.20, fdr_q=0.25, significant=False),
                    },
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60, 73),
                )
            self.assertEqual(len(report["comparisons"]), 2)
            for c in report["comparisons"]:
                self.assertEqual(set(c.keys()), set(_COMPARISON_KEYS))
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Preflight gating
# ---------------------------------------------------------------------------


class TestPreflightGate(unittest.TestCase):
    def test_xle_preflight_blocked_returns_ok_false(self) -> None:
        db = _stub_db_path()
        try:
            side = _make_preflight_side_effect(
                spy_payload=_cleared_payload("SPY"),
                xle_payload=_blocked_payload("XLE"),
            )
            with _patch_preflight(side), \
                 _patch_seam(_make_seam_side_effect()):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60, 73),
                )
            self.assertFalse(report["ok"])
            self.assertEqual(report["blocked_count"], 2)
            self.assertEqual(report["comparisons"], [])
        finally:
            os.unlink(db)

    def test_blocker_reasons_surfaced_in_errors(self) -> None:
        db = _stub_db_path()
        try:
            side = _make_preflight_side_effect(
                spy_payload=_cleared_payload("SPY"),
                xle_payload=_blocked_payload("XLE"),
            )
            with _patch_preflight(side), \
                 _patch_seam(_make_seam_side_effect()):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60, 73),
                )
            joined = " | ".join(report["errors"]).lower()
            self.assertIn("estimation_window_short", joined)
            self.assertIn("xle", joined)
        finally:
            os.unlink(db)

    def test_spy_preflight_blocked_also_gates(self) -> None:
        # The gate is *combined* — SPY-side blockers must also fail.
        db = _stub_db_path()
        try:
            side = _make_preflight_side_effect(
                spy_payload=_blocked_payload("SPY"),
                xle_payload=_cleared_payload("XLE"),
            )
            with _patch_preflight(side), \
                 _patch_seam(_make_seam_side_effect()):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60, 73),
                )
            self.assertFalse(report["ok"])
            self.assertGreaterEqual(report["blocked_count"], 2)
            self.assertEqual(report["comparisons"], [])
        finally:
            os.unlink(db)

    def test_seam_not_invoked_when_blocked(self) -> None:
        db = _stub_db_path()
        try:
            side = _make_preflight_side_effect(
                spy_payload=_cleared_payload("SPY"),
                xle_payload=_blocked_payload("XLE"),
            )

            seam_calls: list[Any] = []

            def _seam_spy(**kwargs):
                seam_calls.append(kwargs)
                return None

            with _patch_preflight(side), \
                 _patch_seam(_seam_spy):
                cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60, 73),
                )
            self.assertEqual(
                seam_calls, [],
                "seam must not be invoked when preflight blocked",
            )
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Changed-interpretation logic
# ---------------------------------------------------------------------------


class TestChangedInterpretation(unittest.TestCase):
    def test_fdr_significance_flip_marks_changed(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.20, fdr_q=0.25, significant=False),
                    },
                    xle_results={
                        60: _result(raw_p=0.02, fdr_q=0.04, significant=True),
                    },
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60,),
                )
            c = report["comparisons"][0]
            self.assertTrue(c["changed_interpretation"])
            self.assertEqual(report["interpretation_changes"], 1)
        finally:
            os.unlink(db)

    def test_raw_p_threshold_flip_marks_changed(self) -> None:
        # raw_p flips across alpha=0.05 even though FDR-significance is
        # the same on both sides (both non-significant).
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.20, fdr_q=0.40, significant=False),
                    },
                    xle_results={
                        60: _result(raw_p=0.01, fdr_q=0.40, significant=False),
                    },
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60,),
                )
            c = report["comparisons"][0]
            self.assertTrue(c["changed_interpretation"])
        finally:
            os.unlink(db)

    def test_no_flip_marks_unchanged(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.10, fdr_q=0.20, significant=False),
                    },
                    xle_results={
                        60: _result(raw_p=0.12, fdr_q=0.22, significant=False),
                    },
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60,),
                )
            c = report["comparisons"][0]
            self.assertFalse(c["changed_interpretation"])
            self.assertEqual(report["interpretation_changes"], 0)
            self.assertIn(
                "benchmark choice did not change",
                c["note"].lower(),
            )
        finally:
            os.unlink(db)

    def test_uncomputable_side_marks_unchanged_with_note(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.10, fdr_q=0.20, significant=False),
                    },
                    xle_results={60: None},
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60,),
                )
            c = report["comparisons"][0]
            self.assertFalse(c["changed_interpretation"])
            self.assertIn("uncomputable", c["note"].lower())
        finally:
            os.unlink(db)

    def test_all_uncomputable_does_not_claim_agreement(self) -> None:
        # When every comparison is uncomputable (e.g. live seam returns
        # None on both sides), the top-level recommendation must NOT
        # falsely claim the events "agree" across SPY and XLE.
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={60: None, 73: None},
                    xle_results={60: None, 73: None},
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60, 73),
                )
            self.assertEqual(report["interpretation_changes"], 0)
            recommended = report["recommended_next_action"].lower()
            self.assertNotIn("agree", recommended,
                             "recommendation must not claim agreement "
                             "when every comparison is uncomputable")
            self.assertIn("uncomputable", recommended)
        finally:
            os.unlink(db)

    def test_partial_uncomputable_mentions_both_axes(self) -> None:
        # 1 of 2 events uncomputable, the other agreeing — the
        # recommendation must mention both states, not claim full
        # agreement.
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.10, fdr_q=0.20, significant=False),
                        73: None,
                    },
                    xle_results={
                        60: _result(raw_p=0.12, fdr_q=0.22, significant=False),
                        73: _result(raw_p=0.30, fdr_q=0.40, significant=False),
                    },
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60, 73),
                )
            recommended = report["recommended_next_action"].lower()
            self.assertIn("uncomputable", recommended)
        finally:
            os.unlink(db)

    def test_comparison_metadata_echoes_primary_ticker_and_date(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.10, fdr_q=0.20, significant=False),
                    },
                    xle_results={
                        60: _result(raw_p=0.12, fdr_q=0.22, significant=False),
                    },
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60,),
                )
            c = report["comparisons"][0]
            self.assertEqual(c["event_id"], 60)
            self.assertEqual(c["primary_ticker"], "XOM")
            self.assertEqual(c["event_date"], "2026-04-08")
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _build_report(self) -> dict[str, Any]:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.20, fdr_q=0.25, significant=False),
                        73: _result(raw_p=0.20, fdr_q=0.25, significant=False),
                    },
                    xle_results={
                        60: _result(raw_p=0.02, fdr_q=0.04, significant=True),
                        73: _result(raw_p=0.20, fdr_q=0.25, significant=False),
                    },
                 )):
                return cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60, 73),
                )
        finally:
            os.unlink(db)

    def test_no_banned_words_in_text_render(self) -> None:
        report = self._build_report()
        text = cli._render_text(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(
                term, text,
                f"banned token {term!r} in text render",
            )

    def test_no_banned_words_in_json_render(self) -> None:
        report = self._build_report()
        blob = cli._render_json(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(
                term, blob,
                f"banned token {term!r} in JSON render",
            )

    def test_notes_do_not_assert_causality(self) -> None:
        report = self._build_report()
        for c in report["comparisons"]:
            note = c["note"].lower()
            for token in ("because", "due to", "causes", "caused"):
                self.assertNotIn(
                    token, note,
                    f"causal token {token!r} found in note: {note!r}",
                )


# ---------------------------------------------------------------------------
# No-paid-surface import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_compare_module_does_not_bind_provider_attrs(self) -> None:
        for attr in ("yfinance", "anthropic", "openai", "fastapi"):
            self.assertFalse(
                hasattr(cli, attr),
                f"compare smoke must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_json_emits_required_keys_on_cleared_run(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.10, fdr_q=0.20, significant=False),
                        73: _result(raw_p=0.10, fdr_q=0.20, significant=False),
                    },
                    xle_results={
                        60: _result(raw_p=0.12, fdr_q=0.22, significant=False),
                        73: _result(raw_p=0.12, fdr_q=0.22, significant=False),
                    },
                 )):
                rc, output = self._run([
                    "--db-path", db, "--json",
                    "--event-ids", "60,73",
                ])
            parsed = json.loads(output)
            self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
            self.assertTrue(parsed["ok"])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(db)

    def test_text_render_does_not_crash(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.10, fdr_q=0.20, significant=False),
                    },
                    xle_results={
                        60: _result(raw_p=0.12, fdr_q=0.22, significant=False),
                    },
                 )):
                rc, output = self._run([
                    "--db-path", db,
                    "--event-ids", "60",
                ])
            self.assertEqual(rc, 0)
            self.assertIn(
                "SPY vs XLE benchmark sensitivity",
                output,
            )
        finally:
            os.unlink(db)

    def test_main_returns_nonzero_when_blocked(self) -> None:
        db = _stub_db_path()
        try:
            side = _make_preflight_side_effect(
                spy_payload=_cleared_payload("SPY"),
                xle_payload=_blocked_payload("XLE"),
            )
            with _patch_preflight(side), \
                 _patch_seam(_make_seam_side_effect()):
                rc, output = self._run([
                    "--db-path", db, "--json",
                    "--event-ids", "60,73",
                ])
            parsed = json.loads(output)
            self.assertFalse(parsed["ok"])
            self.assertEqual(rc, 1)
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Per-side blocker fields
# ---------------------------------------------------------------------------


class TestComparisonBlockerFields(unittest.TestCase):
    """When the seam returns ``None`` for a side, the comparison must
    carry a structured blocker for that side; when it returns a result,
    the blocker must be ``None``.  Both blocker shapes are pinned to
    the same 6-field contract."""

    def test_blockers_none_when_both_sides_computed(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.10, fdr_q=0.12, significant=False),
                    },
                    xle_results={
                        60: _result(raw_p=0.20, fdr_q=0.25, significant=False),
                    },
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60,),
                )
            c = report["comparisons"][0]
            self.assertIsNone(c["spy_blocker"])
            self.assertIsNone(c["xle_blocker"])
        finally:
            os.unlink(db)

    def test_xle_blocker_structured_when_xle_uncomputable(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={
                        60: _result(raw_p=0.10, fdr_q=0.12, significant=False),
                    },
                    xle_results={60: None},
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60,),
                )
            c = report["comparisons"][0]
            self.assertIsNone(c["spy_blocker"])
            self.assertIsNotNone(c["xle_blocker"])
            blk = c["xle_blocker"]
            self.assertEqual(set(blk.keys()), set(_BLOCKER_KEYS))
            self.assertEqual(blk["event_id"], 60)
            self.assertEqual(blk["benchmark_ticker"], "XLE")
            self.assertIsInstance(blk["missing_ticker"], str)
            self.assertEqual(blk["missing_ticker"], "XLE")
            self.assertEqual(blk["missing_dates"], [])
            self.assertIsNone(blk["missing_range"])
            self.assertEqual(blk["horizon"], 20)  # max of default horizons
            self.assertEqual(
                blk["reason"],
                "sensitivity_seam_uncomputable_despite_preflight_clear",
            )
        finally:
            os.unlink(db)

    def test_spy_blocker_structured_when_spy_uncomputable(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={60: None},
                    xle_results={
                        60: _result(raw_p=0.10, fdr_q=0.12, significant=False),
                    },
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60,),
                )
            c = report["comparisons"][0]
            self.assertIsNotNone(c["spy_blocker"])
            self.assertIsNone(c["xle_blocker"])
            blk = c["spy_blocker"]
            self.assertEqual(set(blk.keys()), set(_BLOCKER_KEYS))
            self.assertEqual(blk["benchmark_ticker"], "SPY")
            self.assertEqual(blk["missing_ticker"], "SPY")
        finally:
            os.unlink(db)

    def test_both_blockers_structured_when_both_uncomputable(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={60: None},
                    xle_results={60: None},
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60,),
                )
            c = report["comparisons"][0]
            for blk in (c["spy_blocker"], c["xle_blocker"]):
                self.assertIsNotNone(blk)
                self.assertEqual(set(blk.keys()), set(_BLOCKER_KEYS))
                self.assertIsInstance(blk["missing_ticker"], str)
                self.assertNotEqual(blk["missing_ticker"], "")
        finally:
            os.unlink(db)

    def test_blocker_horizon_uses_max_of_supplied_horizons(self) -> None:
        db = _stub_db_path()
        try:
            with _patch_preflight(_make_preflight_side_effect()), \
                 _patch_seam(_make_seam_side_effect(
                    spy_results={60: None}, xle_results={60: None},
                 )):
                report = cli.run_xle_benchmark_sensitivity_compare_smoke(
                    db_path=db, event_ids=(60,), horizons=(1, 3, 7),
                )
            c = report["comparisons"][0]
            self.assertEqual(c["spy_blocker"]["horizon"], 7)
            self.assertEqual(c["xle_blocker"]["horizon"], 7)
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Un-patched seam against a real SQLite price_cache
# ---------------------------------------------------------------------------


def _seed_price_cache_db(
    *,
    tickers:    tuple[str, ...],
    start_date: _date,
    n_days:     int,
) -> str:
    """Create a temp SQLite with a populated ``price_cache`` table.

    Walks the *calendar* one day at a time from ``start_date`` for
    ``n_days`` days, inserting a row for every trading day (skipping
    weekends and the preflight's market-holiday set).  Prices follow
    a small deterministic drift per ticker so daily abnormal returns
    vary day to day — sigma is strictly positive without random noise.
    """
    from scripts import benchmark_sensitivity_preflight as _pf

    path = os.path.join(
        tempfile.gettempdir(),
        f"xle_compare_real_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE price_cache ("
            "ticker TEXT NOT NULL, "
            "date TEXT NOT NULL, "
            "close REAL, "
            "volume INTEGER, "
            "auto_adjust INTEGER, "
            "fetched_at TEXT, "
            "PRIMARY KEY (ticker, date, auto_adjust))"
        )
        # Deterministic per-ticker drift + small daily wiggle so the
        # daily-return series is non-degenerate (sigma > 0).
        base = {"XOM": 100.0, "SPY": 400.0, "XLE": 80.0}
        drift = {"XOM": 0.5, "SPY": 0.4, "XLE": 0.3}
        wiggle_phase = {"XOM": 0, "SPY": 2, "XLE": 3}

        cur = start_date
        i = 0
        while i < n_days:
            if _pf._is_trading_day(cur):
                iso = cur.isoformat()
                for t in tickers:
                    close = base[t] + drift[t] * i \
                        + ((i + wiggle_phase[t]) % 5) * 0.1
                    conn.execute(
                        "INSERT INTO price_cache "
                        "(ticker, date, close, volume, auto_adjust, fetched_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (t, iso, close, 1_000_000, 1, "2026-01-01T00:00:00Z"),
                    )
                i += 1
            cur = cur + _timedelta(days=1)
        conn.commit()
    finally:
        conn.close()
    return path


class TestUnpatchedSeamWithRealSqlite(unittest.TestCase):
    """Exercises ``_compute_sensitivity_for_benchmark`` against a real
    SQLite ``price_cache`` table without patching the seam.

    Pins:

    * The live (un-patched) computation path actually executes — every
      other test in this file patches the seam, so without this case
      the live code path would have zero test coverage.
    * The seam reads ``price_cache`` rows read-only (no provider, no
      network) and returns the canonical 4-key result dict.
    * Estimation-window stddev is computed from primary-minus-benchmark
      daily abnormal returns and ``raw_p`` is derived from a two-tail
      normal test on the BHAR z-statistic.
    """

    def test_returns_non_none_result_with_full_cache(self) -> None:
        # Seed enough trading days that a 60-day estimation window and
        # a 20-day forward horizon are both fully covered around the
        # chosen event date.
        start = _date(2026, 1, 2)        # First trading day after Jan-1 holiday
        db = _seed_price_cache_db(
            tickers=("XOM", "SPY", "XLE"),
            start_date=start, n_days=110,
        )
        try:
            result = cli._compute_sensitivity_for_benchmark(
                db_path=db,
                event_id=60,
                event_date="2026-04-30",   # well inside the seeded range
                primary_ticker="XOM",
                benchmark="SPY",
                horizons=(1, 5, 20),
                estimation_window=60,
            )
            self.assertIsNotNone(
                result,
                "seam returned None despite full primary+benchmark cache",
            )
            self.assertEqual(
                set(result.keys()),
                {"raw_p", "fdr_q", "significant", "sar"},
            )
            self.assertIsInstance(result["raw_p"], float)
            self.assertGreaterEqual(result["raw_p"], 0.0)
            self.assertLessEqual(result["raw_p"], 1.0)
            self.assertEqual(result["fdr_q"], result["raw_p"])
            self.assertIsInstance(result["significant"], bool)
            self.assertEqual(
                result["significant"], result["raw_p"] <= 0.05,
            )
            self.assertIsInstance(result["sar"], float)
        finally:
            os.unlink(db)

    def test_returns_none_for_unknown_benchmark_ticker(self) -> None:
        # primary present, but benchmark ticker has no rows — the seam
        # must return None and surface uncomputable rather than crash.
        start = _date(2026, 1, 2)
        db = _seed_price_cache_db(
            tickers=("XOM", "SPY"),    # No XLE rows.
            start_date=start, n_days=110,
        )
        try:
            result = cli._compute_sensitivity_for_benchmark(
                db_path=db,
                event_id=60,
                event_date="2026-04-30",
                primary_ticker="XOM",
                benchmark="XLE",
                horizons=(1, 5, 20),
                estimation_window=60,
            )
            self.assertIsNone(result)
        finally:
            os.unlink(db)

    def test_returns_none_when_event_date_unparseable(self) -> None:
        start = _date(2026, 1, 2)
        db = _seed_price_cache_db(
            tickers=("XOM", "SPY", "XLE"),
            start_date=start, n_days=110,
        )
        try:
            result = cli._compute_sensitivity_for_benchmark(
                db_path=db,
                event_id=60,
                event_date="not-a-date",
                primary_ticker="XOM",
                benchmark="SPY",
                horizons=(1, 5, 20),
                estimation_window=60,
            )
            self.assertIsNone(result)
        finally:
            os.unlink(db)

    def test_returns_none_when_primary_ticker_missing(self) -> None:
        start = _date(2026, 1, 2)
        db = _seed_price_cache_db(
            tickers=("XOM", "SPY", "XLE"),
            start_date=start, n_days=110,
        )
        try:
            result = cli._compute_sensitivity_for_benchmark(
                db_path=db,
                event_id=60,
                event_date="2026-04-30",
                primary_ticker=None,
                benchmark="SPY",
                horizons=(1, 5, 20),
                estimation_window=60,
            )
            self.assertIsNone(result)
        finally:
            os.unlink(db)

    def test_seam_is_read_only_no_new_rows(self) -> None:
        # After a non-None seam call, the price_cache row count must be
        # exactly what we seeded — no INSERT / UPDATE / DELETE side
        # effect from the seam.
        start = _date(2026, 1, 2)
        db = _seed_price_cache_db(
            tickers=("XOM", "SPY", "XLE"),
            start_date=start, n_days=110,
        )
        try:
            conn = sqlite3.connect(db)
            try:
                before = conn.execute(
                    "SELECT COUNT(*) FROM price_cache"
                ).fetchone()[0]
            finally:
                conn.close()

            cli._compute_sensitivity_for_benchmark(
                db_path=db,
                event_id=60,
                event_date="2026-04-30",
                primary_ticker="XOM",
                benchmark="SPY",
                horizons=(1, 5, 20),
                estimation_window=60,
            )

            conn = sqlite3.connect(db)
            try:
                after = conn.execute(
                    "SELECT COUNT(*) FROM price_cache"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(before, after)
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Pure-helper smoke (sqlite-free)
# ---------------------------------------------------------------------------


class TestPureHelpers(unittest.TestCase):
    def test_two_tail_normal_p_at_zero_is_one(self) -> None:
        self.assertAlmostEqual(cli._two_tail_normal_p(0.0), 1.0, places=12)

    def test_two_tail_normal_p_decreases_with_z(self) -> None:
        # |z| larger → smaller p.  Sanity check, not a tight numeric
        # spec.
        p0 = cli._two_tail_normal_p(0.5)
        p1 = cli._two_tail_normal_p(1.5)
        p2 = cli._two_tail_normal_p(3.0)
        self.assertGreater(p0, p1)
        self.assertGreater(p1, p2)
        self.assertGreater(p2, 0.0)

    def test_is_positive_number_rejects_bool(self) -> None:
        self.assertFalse(cli._is_positive_number(True))
        self.assertFalse(cli._is_positive_number(False))
        self.assertFalse(cli._is_positive_number(0))
        self.assertFalse(cli._is_positive_number(-1.0))
        self.assertTrue(cli._is_positive_number(0.5))
        self.assertTrue(cli._is_positive_number(1))


if __name__ == "__main__":
    unittest.main()
