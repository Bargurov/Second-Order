"""Tests for ``scripts/short_horizon_review_workflow_smoke.py``.

Pin the contract:

* Runs validator -> apply -> validate end-to-end against either a
  built-in fixture (default) or an operator-supplied worksheet.
* Read-only against the live archive — every run propagates the apply
  smoke's ``live_db_unchanged`` byte-identity guard.  No FastAPI / LLM
  / provider / yfinance imports on the smoke surface.
* Output dict has EXACTLY these 14 keys::

    ok, worksheet_path, validator_ok, apply_ok, validate_ok,
    accepted_count, staged_count, events_evaluated, records_count,
    significant_count, live_db_unchanged, errors, warnings,
    recommended_next_action

* Fixture mode is explicit in the envelope (warning + recommended-
  next-action prefix) and never claims market evidence.  Real
  worksheet mode is similarly labelled.
* ``--output`` writes the envelope on every code path; default
  invocation has no filesystem side effect outside the auto-cleaned
  fixture scratch files.
* CLI ``main`` returns 0 iff envelope ``ok`` is True.
* Conservative wording: banned tokens absent from any text the smoke
  emits.
"""
from __future__ import annotations

import csv as csv_module
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import short_horizon_review_workflow_smoke as cli  # noqa: E402
from scripts import short_horizon_review_apply_smoke as apply_cli  # noqa: E402
from scripts import short_horizon_review_validate_smoke as validate_cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "worksheet_path",
    "validator_ok",
    "apply_ok",
    "validate_ok",
    "accepted_count",
    "staged_count",
    "events_evaluated",
    "records_count",
    "significant_count",
    "live_db_unchanged",
    "errors",
    "warnings",
    "recommended_next_action",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "validated",
    "automatically",
    "alpha generated",
    "correct ticker",
)


_WORKSHEET_COLUMNS = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "current_mechanism_family",
    "repair_type",
    "repair_priority",
    "operator_decision_needed",
    "reason_for_review",
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "include_in_short_horizon_validation",
    "exclude_reason",
    "operator_notes",
)


_EVENTS_DDL = """
CREATE TABLE events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    headline         TEXT,
    event_date       TEXT,
    market_tickers   TEXT,
    low_signal       INTEGER DEFAULT 0,
    mechanism_family TEXT DEFAULT 'none'
)
""".strip()


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _row(**fields: Any) -> dict[str, Any]:
    return {c: fields.get(c, "") for c in _WORKSHEET_COLUMNS}


def _accepted_row(
    *, event_id: int,
    proposed_primary_ticker: str = "XOM",
    proposed_benchmark_ticker: str = "SPY",
    proposed_mechanism_family: str = "supply_shock",
    predicted_direction: str = "up",
    event_date: str = "2026-04-15",
    headline: str = "h",
) -> dict[str, Any]:
    return _row(
        event_id=event_id,
        include_in_short_horizon_validation="yes",
        headline=headline,
        event_date=event_date,
        proposed_primary_ticker=proposed_primary_ticker,
        proposed_benchmark_ticker=proposed_benchmark_ticker,
        proposed_mechanism_family=proposed_mechanism_family,
        predicted_direction=predicted_direction,
    )


def _excluded_row(
    *, event_id: int, exclude_reason: str = "off-topic",
) -> dict[str, Any]:
    return _row(
        event_id=event_id,
        include_in_short_horizon_validation="no",
        exclude_reason=exclude_reason,
    )


def _pending_row(*, event_id: int) -> dict[str, Any]:
    return _row(
        event_id=event_id,
        include_in_short_horizon_validation="",
    )


def _write_worksheet(rows: list[dict[str, Any]]) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"sh_review_workflow_test_ws_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv_module.writer(fh, lineterminator="\n")
        w.writerow(_WORKSHEET_COLUMNS)
        for r in rows:
            w.writerow([str(r.get(c, "")) for c in _WORKSHEET_COLUMNS])
    return path


def _make_live_db(*, seed_event_ids: list[int] | None = None) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"sh_review_workflow_test_live_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_EVENTS_DDL)
        for ev_id in (seed_event_ids or []):
            conn.execute(
                "INSERT INTO events (id, headline, event_date) "
                "VALUES (?, ?, ?)",
                (ev_id, f"headline {ev_id}", "2026-04-15"),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _empty_validate_payload(records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"ok": True, "records": records or [], "errors": []}


def _patched_validate_seam(records: list[dict[str, Any]] | None = None):
    return patch.object(
        validate_cli, "_run_short_horizon_validation_on_temp_db",
        return_value=_empty_validate_payload(records),
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_has_exactly_fourteen_keys_in_fixture_mode(self) -> None:
        report = cli.run_short_horizon_review_workflow_smoke()
        self.assertEqual(
            set(report.keys()), set(_REQUIRED_KEYS),
            f"unexpected keys: {sorted(report.keys())}",
        )

    def test_has_exactly_fourteen_keys_in_real_mode(self) -> None:
        live = _make_live_db()
        ws = _write_worksheet([])
        try:
            with _patched_validate_seam():
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=ws, db_path=live,
                )
            self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        finally:
            os.unlink(ws)
            os.unlink(live)


# ---------------------------------------------------------------------------
# Fixture mode
# ---------------------------------------------------------------------------


class TestFixtureMode(unittest.TestCase):
    def test_default_invocation_runs_fixture_chain_cleanly(self) -> None:
        report = cli.run_short_horizon_review_workflow_smoke()
        self.assertTrue(report["ok"], report.get("errors"))
        self.assertTrue(report["validator_ok"])
        self.assertTrue(report["apply_ok"])
        self.assertTrue(report["validate_ok"])
        # The canonical fixture has 4 rows: 2 yes, 1 no, 1 pending.
        self.assertEqual(report["accepted_count"], 2)
        self.assertEqual(report["staged_count"], 2)
        # The synthetic validate payload carries 2 events x 2 horizons.
        self.assertEqual(report["events_evaluated"], 2)
        self.assertEqual(report["records_count"], 4)
        self.assertEqual(report["significant_count"], 0)
        self.assertTrue(report["live_db_unchanged"])

    def test_fixture_mode_labels_run_in_warnings(self) -> None:
        report = cli.run_short_horizon_review_workflow_smoke()
        joined = " ".join(report["warnings"]).lower()
        self.assertIn("fixture", joined)

    def test_fixture_mode_labels_run_in_recommended_next_action(self) -> None:
        report = cli.run_short_horizon_review_workflow_smoke()
        self.assertIn(
            "fixture",
            report["recommended_next_action"].lower(),
        )

    def test_fixture_mode_explicit_no_market_evidence(self) -> None:
        # The fixture's first warning must clearly state that the run
        # does NOT carry market evidence — otherwise an operator could
        # mis-read the staged + records counts as a finding.
        report = cli.run_short_horizon_review_workflow_smoke()
        warn_text = " ".join(report["warnings"]).lower()
        self.assertIn("does not establish market evidence", warn_text)

    def test_fixture_mode_cleans_up_scratch_files(self) -> None:
        # The fixture's worksheet + DB live in tempdir and must be
        # unlinked after the run.  The envelope echoes the worksheet
        # path so we can probe it after the call returns.
        report = cli.run_short_horizon_review_workflow_smoke()
        ws_path = report.get("worksheet_path")
        self.assertIsNotNone(ws_path)
        self.assertFalse(
            os.path.exists(ws_path),
            f"fixture worksheet should be auto-cleaned, still at {ws_path}",
        )


# ---------------------------------------------------------------------------
# Real worksheet mode
# ---------------------------------------------------------------------------


class TestRealWorksheetMode(unittest.TestCase):
    def test_real_mode_uses_supplied_worksheet(self) -> None:
        live = _make_live_db()
        ws = _write_worksheet([
            _accepted_row(event_id=500),
            _excluded_row(event_id=501),
            _pending_row(event_id=502),
        ])
        try:
            with _patched_validate_seam([
                {
                    "event_id": 500, "headline": "h",
                    "ticker": "XOM", "horizon": 1, "sar": 1.0,
                    "mechanism_family": "supply_shock",
                    "statistically_significant": True,
                    "abnormal_return": 0.02, "ci_low": -0.01,
                    "ci_high": 0.05, "p_value": 0.04, "fdr_q": 0.04,
                    "interpretation": "significant",
                },
            ]):
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=ws, db_path=live,
                )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["accepted_count"], 1)
            self.assertEqual(report["staged_count"], 1)
            self.assertEqual(report["events_evaluated"], 1)
            self.assertEqual(report["records_count"], 1)
            self.assertEqual(report["significant_count"], 1)
            self.assertEqual(report["worksheet_path"], ws)
        finally:
            os.unlink(ws)
            os.unlink(live)

    def test_real_mode_labels_run_in_recommended_next_action(self) -> None:
        live = _make_live_db()
        ws = _write_worksheet([_pending_row(event_id=600)])
        try:
            with _patched_validate_seam():
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=ws, db_path=live,
                )
            self.assertIn(
                "real-worksheet",
                report["recommended_next_action"].lower(),
            )
        finally:
            os.unlink(ws)
            os.unlink(live)

    def test_real_mode_with_all_pending_rows_is_ok_with_zero_accepted(
        self,
    ) -> None:
        # Mirrors the current operator worksheet: every row is
        # pending.  The chain should report ok=True with zero counts
        # and a recommended next action that asks for filled gates.
        live = _make_live_db()
        ws = _write_worksheet([
            _pending_row(event_id=601),
            _pending_row(event_id=602),
        ])
        try:
            with _patched_validate_seam():
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=ws, db_path=live,
                )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["accepted_count"], 0)
            self.assertEqual(report["staged_count"], 0)
            self.assertEqual(report["events_evaluated"], 0)
            self.assertIn(
                "fill yes/no gates",
                report["recommended_next_action"].lower(),
            )
        finally:
            os.unlink(ws)
            os.unlink(live)


# ---------------------------------------------------------------------------
# Failure propagation
# ---------------------------------------------------------------------------


class TestFailurePropagation(unittest.TestCase):
    def test_validator_failure_surfaces_with_prefix(self) -> None:
        # Missing required columns -> validator hard fails.
        bad_ws = os.path.join(
            tempfile.gettempdir(),
            f"sh_review_workflow_bad_{uuid.uuid4().hex}.csv",
        )
        live = _make_live_db()
        try:
            with open(bad_ws, "w", newline="", encoding="utf-8") as fh:
                w = csv_module.writer(fh, lineterminator="\n")
                w.writerow(["event_id", "headline"])
                w.writerow(["1", "h"])
            with _patched_validate_seam():
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=bad_ws, db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertFalse(report["validator_ok"])
            self.assertTrue(any(
                e.startswith("validator:") for e in report["errors"]
            ), f"errors: {report['errors']}")
        finally:
            os.unlink(bad_ws)
            os.unlink(live)

    def test_apply_failure_surfaces_with_prefix(self) -> None:
        # Missing live DB -> apply fails closed.
        ws = _write_worksheet([_accepted_row(event_id=700)])
        try:
            with _patched_validate_seam():
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=ws,
                    db_path="/nonexistent/events.db",
                )
            self.assertFalse(report["ok"])
            self.assertFalse(report["apply_ok"])
            self.assertTrue(any(
                e.startswith("apply:") for e in report["errors"]
            ), f"errors: {report['errors']}")
        finally:
            os.unlink(ws)

    def test_validate_failure_surfaces_with_prefix(self) -> None:
        # Force the validate seam to raise -> the validate smoke
        # surfaces "validation seam raised:" inside its own errors.
        live = _make_live_db()
        ws = _write_worksheet([_accepted_row(event_id=701)])
        try:
            def _boom(*, db_path: str | None) -> dict[str, Any]:
                raise RuntimeError("seam blew up")
            with patch.object(
                validate_cli,
                "_run_short_horizon_validation_on_temp_db",
                side_effect=_boom,
            ):
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=ws, db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertFalse(report["validate_ok"])
            self.assertTrue(any(
                e.startswith("validate:") for e in report["errors"]
            ), f"errors: {report['errors']}")
        finally:
            os.unlink(ws)
            os.unlink(live)


# ---------------------------------------------------------------------------
# Live DB byte-identity
# ---------------------------------------------------------------------------


class TestLiveDBByteIdentity(unittest.TestCase):
    def test_live_db_bytes_unchanged_in_real_mode(self) -> None:
        live = _make_live_db(seed_event_ids=[800, 801])
        ws = _write_worksheet([
            _accepted_row(event_id=800),
            _accepted_row(event_id=801),
            _excluded_row(event_id=802),
        ])
        try:
            before = _sha256(live)
            with _patched_validate_seam([]):
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=ws, db_path=live,
                )
            after = _sha256(live)
            self.assertEqual(
                before, after,
                "live DB bytes mutated by workflow smoke",
            )
            self.assertTrue(report["live_db_unchanged"])
        finally:
            os.unlink(ws)
            os.unlink(live)

    def test_live_db_unchanged_propagated_from_apply(self) -> None:
        # The apply smoke owns the byte-identity guard; the workflow
        # smoke must propagate its verdict rather than re-deriving it.
        live = _make_live_db()
        ws = _write_worksheet([_accepted_row(event_id=810)])
        try:
            # Force apply to claim the live DB changed; verify it
            # propagates into the workflow envelope.
            real_apply = apply_cli.smoke_short_horizon_review_apply
            def _patched(**kwargs):
                report = real_apply(**kwargs)
                report["live_db_unchanged"] = False
                report["errors"] = list(report.get("errors") or [])
                report["errors"].append("synthetic byte-drift")
                report["ok"] = False
                return report
            with patch.object(
                apply_cli, "smoke_short_horizon_review_apply",
                side_effect=_patched,
            ), _patched_validate_seam([]):
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=ws, db_path=live,
                )
            self.assertFalse(report["live_db_unchanged"])
            self.assertFalse(report["apply_ok"])
            self.assertFalse(report["ok"])
        finally:
            os.unlink(ws)
            os.unlink(live)


# ---------------------------------------------------------------------------
# Cross-stage divergence warnings
# ---------------------------------------------------------------------------


class TestCrossStageDivergence(unittest.TestCase):
    def test_apply_drops_rows_after_validator_accepts_them(self) -> None:
        # A yes row that passes the validator's column-shape check
        # but fails the apply smoke's stricter per-row checks
        # (validator does NOT check event_date format; apply does):
        # validator include_count == apply accepted_count == 1, but
        # staged_count is 0 because the date check fails at apply.
        # The chain surfaces "apply:"-prefixed errors and the
        # workflow envelope reports ok=False with both accepted_count
        # and staged_count populated.
        live = _make_live_db()
        ws = _write_worksheet([
            _accepted_row(
                event_id=820, event_date="2026/04/15",   # apply will reject
            ),
        ])
        try:
            with _patched_validate_seam([]):
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=ws, db_path=live,
                )
            self.assertFalse(report["ok"])
            self.assertEqual(report["accepted_count"], 1)
            self.assertEqual(report["staged_count"], 0)
            self.assertTrue(any(
                e.startswith("apply:") and "event_date" in e
                for e in report["errors"]
            ), f"errors: {report['errors']}")
        finally:
            os.unlink(ws)
            os.unlink(live)


# ---------------------------------------------------------------------------
# --output filesystem side effects
# ---------------------------------------------------------------------------


class TestOutputPersistence(unittest.TestCase):
    def test_no_output_means_no_filesystem_side_effect(self) -> None:
        # Default fixture invocation has no --output: no envelope JSON
        # written anywhere.  The fixture scratch files are auto-cleaned.
        before_listing = set(os.listdir(tempfile.gettempdir()))
        report = cli.run_short_horizon_review_workflow_smoke()
        after_listing = set(os.listdir(tempfile.gettempdir()))
        # Allow only ephemeral *apply* / *fresh_temp* temp dbs (apply
        # smoke leaves its temp DB on disk by design — that's its
        # contract, not the workflow smoke's filesystem side effect).
        leaked = (after_listing - before_listing)
        unexpected = [
            f for f in leaked
            if "workflow" in f.lower()
            and not f.startswith("sh_review_apply_")
        ]
        self.assertEqual(
            unexpected, [],
            f"workflow smoke leaked files: {unexpected}",
        )
        self.assertTrue(report["ok"])

    def test_output_path_writes_envelope(self) -> None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"sh_review_workflow_out_{uuid.uuid4().hex}.json",
        )
        try:
            report = cli.run_short_horizon_review_workflow_smoke(
                output_path=out_path,
            )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            self.assertEqual(set(blob.keys()), set(_REQUIRED_KEYS))
            self.assertEqual(blob["ok"], report["ok"])
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_output_path_writes_envelope_even_on_failure(self) -> None:
        # Apply fails -> envelope still written.
        ws = _write_worksheet([_accepted_row(event_id=830)])
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"sh_review_workflow_out_{uuid.uuid4().hex}.json",
        )
        try:
            with _patched_validate_seam():
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=ws,
                    db_path="/nonexistent/events.db",
                    output_path=out_path,
                )
            self.assertFalse(report["ok"])
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            self.assertFalse(blob["ok"])
        finally:
            os.unlink(ws)
            if os.path.exists(out_path):
                os.unlink(out_path)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_tokens_in_text_render_fixture_mode(self) -> None:
        report = cli.run_short_horizon_review_workflow_smoke()
        text = cli._render_text(report).lower()
        for token in _BANNED_WORDS:
            self.assertNotIn(
                token, text,
                f"banned token {token!r} in text render: {text}",
            )

    def test_no_banned_tokens_in_json_render_fixture_mode(self) -> None:
        report = cli.run_short_horizon_review_workflow_smoke()
        blob = cli._render_json(report).lower()
        for token in _BANNED_WORDS:
            self.assertNotIn(
                token, blob,
                f"banned token {token!r} in JSON render",
            )

    def test_no_banned_tokens_in_real_mode_envelope(self) -> None:
        live = _make_live_db()
        ws = _write_worksheet([
            _accepted_row(event_id=900),
            _excluded_row(event_id=901),
            _pending_row(event_id=902),
        ])
        try:
            with _patched_validate_seam():
                report = cli.run_short_horizon_review_workflow_smoke(
                    worksheet_path=ws, db_path=live,
                )
            blob = cli._render_json(report).lower()
            for token in _BANNED_WORDS:
                self.assertNotIn(
                    token, blob,
                    f"banned token {token!r} in real-mode JSON",
                )
        finally:
            os.unlink(ws)
            os.unlink(live)

    def test_fixture_recommendation_does_not_claim_evidence(self) -> None:
        # The fixture run should never describe itself as carrying
        # evidence about the market — only about workflow mechanics.
        report = cli.run_short_horizon_review_workflow_smoke()
        prose = report["recommended_next_action"].lower()
        self.assertNotIn("market evidence", prose.replace(
            "no market evidence", "",
        ))


# ---------------------------------------------------------------------------
# Provider / paid-surface isolation
# ---------------------------------------------------------------------------


class TestNoPaidSurfaceImports(unittest.TestCase):
    def test_workflow_smoke_module_does_not_import_yfinance(self) -> None:
        # Loaded by the test header; just confirm it didn't pull in
        # yfinance / market_data / api / routes.
        self.assertNotIn("yfinance", sys.modules,
                         "workflow smoke should not import yfinance")
        # market_data / api / routes may legitimately be loaded by
        # other test files in the same process, so we don't assert
        # their absence here — only the smoke's direct surface
        # constraint.  Confirm the smoke module itself has no such
        # references via attribute lookup.
        for attr in ("yfinance", "anthropic", "openai"):
            self.assertFalse(
                hasattr(cli, attr),
                f"workflow smoke must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLIEntryPoint(unittest.TestCase):
    def test_main_json_prints_valid_envelope(self) -> None:
        buf = StringIO()
        rc = cli.main(["--json"], out=buf)
        payload = json.loads(buf.getvalue())
        self.assertEqual(set(payload.keys()), set(_REQUIRED_KEYS))
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])

    def test_main_returns_nonzero_on_failure(self) -> None:
        # Force apply failure via bad worksheet path; --worksheet to
        # disable fixture mode.
        ws = _write_worksheet([_accepted_row(event_id=1000)])
        try:
            buf = StringIO()
            with _patched_validate_seam():
                rc = cli.main(
                    ["--worksheet", ws, "--db-path",
                     "/nonexistent/events.db", "--json"],
                    out=buf,
                )
            self.assertEqual(rc, 1)
        finally:
            os.unlink(ws)

    def test_main_text_render_does_not_crash(self) -> None:
        buf = StringIO()
        rc = cli.main([], out=buf)
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("Short-horizon reviewed workflow", text)


if __name__ == "__main__":
    unittest.main()
