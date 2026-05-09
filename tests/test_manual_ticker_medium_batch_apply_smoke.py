"""Tests for ``scripts/manual_ticker_medium_batch_apply_smoke.py``.

Pin the contract:

* Default mode is ``dry-run`` — no copy, no apply, no DB writes,
  no provider call, no clean-cohort import.
* Write mode requires ALL of ``--write --confirm --backup-path
  --csv-path``; any missing flag → fail closed.
* Apply phase mutates events in the temp copy; mechanism_family
  decisions land alongside.
* Price-cache backfill is OFF by default — provider seam is NEVER
  probed unless ``--with-price-backfill`` is set.
* Mechanism-family decisions can come from the CSV's
  ``proposed_mechanism_family`` column AND/OR repeatable
  ``--mechanism-family-decision`` flags; CLI overrides CSV for
  the same event_id.
* Fail-closed precedence:
    - Empty CSV (no exclusions, no retags, no decisions) → fail
      closed.
    - Schema missing low_signal + exclusion rows → fail closed,
      no apply.
    - Schema missing mechanism_family + decisions → fail closed,
      no apply.
    - --with-price-backfill + retag rows + provider unavailable
      → fail closed BEFORE copy.
* Live ``--db-path`` and input ``--backup-path`` are SHA-256
  byte-identical before/after every run, including every fail-
  closed path.
* Output dict carries EXACTLY the 12 keys.
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
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import manual_ticker_medium_batch_apply_smoke as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "mode",
    "rows_read",
    "rows_excluded",
    "rows_retagged",
    "mechanism_family_updates",
    "before_clean_fully_ready",
    "after_clean_fully_ready",
    "live_db_unchanged",
    "input_backup_unchanged",
    "errors",
    "warnings",
    # Manual-aware clean-cohort metrics.  The smoke surfaces these so an
    # operator can see which events are eligible for the aggregate claim
    # AFTER the operator's exclusions / retags / mechanism-family
    # decisions land — the raw report's clean-cohort math doesn't know
    # about operator exclusions and can leave repaired rows blocked by
    # duplicate_date_ticker against an operator-excluded counterpart.
    "operator_excluded_event_ids",
    "raw_after_clean_fully_ready",
    "adjusted_after_clean_fully_ready",
    "adjusted_clean_fully_ready_delta",
    "remaining_contamination_reasons",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_PRICE_CACHE_DDL = """
CREATE TABLE price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()


def _events_ddl(
    *, with_low_signal: bool = True, with_mechanism_family: bool = True,
) -> str:
    cols = [
        "id              INTEGER PRIMARY KEY AUTOINCREMENT",
        "headline        TEXT",
        "event_date      TEXT",
        "market_tickers  TEXT",
    ]
    if with_low_signal:
        cols.append("low_signal      INTEGER DEFAULT 0")
    if with_mechanism_family:
        cols.append("mechanism_family TEXT DEFAULT 'none'")
    return "CREATE TABLE events (\n  " + ",\n  ".join(cols) + "\n)"


def _make_temp_db(
    suffix: str = "medium_batch",
    *,
    with_low_signal: bool = True,
    with_mechanism_family: bool = True,
    seed_events: list[dict] | None = None,
) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_events_ddl(
            with_low_signal=with_low_signal,
            with_mechanism_family=with_mechanism_family,
        ))
        conn.execute(_PRICE_CACHE_DDL)
        if seed_events:
            for e in seed_events:
                cols = ["id", "headline", "event_date", "market_tickers"]
                vals = [
                    e["id"], e.get("headline"), e.get("event_date"),
                    e.get("market_tickers", "[]"),
                ]
                if with_low_signal:
                    cols.append("low_signal")
                    vals.append(int(e.get("low_signal", 0)))
                if with_mechanism_family:
                    cols.append("mechanism_family")
                    vals.append(e.get("mechanism_family", "none"))
                placeholders = ", ".join(["?"] * len(cols))
                conn.execute(
                    f"INSERT INTO events ({', '.join(cols)}) "
                    f"VALUES ({placeholders})",
                    vals,
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


def _write_csv(
    rows: list[dict],
    *, suffix: str = "mb_csv",
    with_mechanism_family_column: bool = True,
) -> str:
    base_columns = [
        "event_id", "headline", "event_date", "current_primary_ticker",
        "flags", "reason", "manual_review_priority",
        "proposed_primary_ticker", "proposed_benchmark",
    ]
    if with_mechanism_family_column:
        base_columns.append("proposed_mechanism_family")
    base_columns.extend(["ticker_rationale", "exclude_reason"])
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv_module.writer(fh, lineterminator="\n")
        writer.writerow(base_columns)
        for r in rows:
            writer.writerow([str(r.get(c, "")) for c in base_columns])
    return path


def _csv_row(
    *, event_id: int,
    proposed_primary_ticker: str = "",
    proposed_benchmark: str = "",
    proposed_mechanism_family: str = "",
    exclude_reason: str = "",
    event_date: str = "2026-04-06",
    headline: str = "h",
) -> dict:
    return {
        "event_id":                  event_id,
        "headline":                  headline,
        "event_date":                event_date,
        "current_primary_ticker":    "DRIV",
        "flags":                     "",
        "reason":                    "contaminated_fully_ready",
        "manual_review_priority":    "high",
        "proposed_primary_ticker":   proposed_primary_ticker,
        "proposed_benchmark":        proposed_benchmark,
        "proposed_mechanism_family": proposed_mechanism_family,
        "ticker_rationale":          "",
        "exclude_reason":            exclude_reason,
    }


def _spy_row(date_iso: str, *, close: float = 100.0,
             volume: float = 1.0e6) -> dict:
    return {"date": date_iso, "close": close, "volume": volume}


def _patch_seams(
    *,
    clean_before: int = 0,
    clean_after: int | None = None,
    after_payload: dict | None = None,
    before_payload: dict | None = None,
    provider_available: bool = True,
    fetch_rows: list[dict] | None = None,
    fetch_side_effect: Exception | None = None,
):
    """Patch the clean-cohort + provider seams.

    Two fake-payload styles are supported:

      * Bare scalar form (``clean_before`` / ``clean_after``) — returns
        ``{"clean_fully_ready_count": N}`` with no event_ids list and no
        excluded_examples.  Backward-compatible for tests that don't
        pin the manual-aware adjustment fields.
      * Rich payload form (``before_payload`` / ``after_payload``) —
        returns the full dict the smoke needs to compute
        ``adjusted_after_clean_fully_ready`` and
        ``remaining_contamination_reasons``.  When supplied, the rich
        payload wins.  Use this in tests that pin the adjustment.
    """
    if before_payload is None:
        before_payload = {"clean_fully_ready_count": clean_before}
    if after_payload is None:
        eff_after = clean_after if clean_after is not None else clean_before
        after_payload = {"clean_fully_ready_count": eff_after}
    clean_calls = iter([before_payload, after_payload])

    def fake_clean(*, db_path):
        return next(clean_calls)

    if fetch_side_effect is not None:
        fetch_patch = patch.object(
            cli, "_fetch_ticker_rows", side_effect=fetch_side_effect)
    else:
        rows = fetch_rows if fetch_rows is not None else []

        def fake_fetch(*, ticker, start, end):
            return rows
        fetch_patch = patch.object(
            cli, "_fetch_ticker_rows", side_effect=fake_fetch)

    return (
        patch.object(cli, "_run_clean_cohort_report",  side_effect=fake_clean),
        patch.object(cli, "_check_provider_available", return_value=provider_available),
        fetch_patch,
    )


def _run(*, csv_path: str | None = None, **kwargs) -> dict:
    return cli.smoke_medium_batch_apply(csv_path=csv_path, **kwargs)


def _cleanup_temp_copy(result: dict) -> None:
    for w in result.get("warnings", []):
        if "Temp copy at " in w:
            p = w.split("Temp copy at ", 1)[1].strip()
            if os.path.exists(p):
                os.unlink(p)


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_dry_run_returns_dict_with_exactly_12_keys(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))

    def test_no_additive_fields_on_write_mode(self) -> None:
        backup = _make_temp_db("mb_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-01"),
        ])
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))


# ---------------------------------------------------------------------------
# Default dry-run
# ---------------------------------------------------------------------------


class TestDryRunDefault(unittest.TestCase):
    def test_default_mode_is_dry_run(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["mode"], "dry-run")

    def test_dry_run_does_not_call_seams(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     proposed_mechanism_family="bank_regulatory_capital_relief"),
            _csv_row(event_id=2, exclude_reason="off-topic"),
        ])
        try:
            with patch.object(cli, "_check_provider_available") as check:
                with patch.object(cli, "_fetch_ticker_rows") as fetch:
                    with patch.object(cli, "_run_clean_cohort_report") as clean:
                        _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertFalse(check.called)
        self.assertFalse(fetch.called)
        self.assertFalse(clean.called)

    def test_dry_run_counts_categories_and_mf(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS"),
            _csv_row(event_id=2, proposed_primary_ticker="MS"),
            _csv_row(event_id=3, proposed_primary_ticker="JPM"),
            _csv_row(event_id=4, exclude_reason="off-topic"),
            _csv_row(event_id=5, exclude_reason="off-topic"),
            _csv_row(event_id=6, exclude_reason="off-topic",
                     proposed_mechanism_family="tariff"),
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["rows_read"],     6)
        self.assertEqual(result["rows_excluded"], 3)
        self.assertEqual(result["rows_retagged"], 3)
        # mf is orthogonal to exclude/retag — row 6 is excluded AND
        # carries an mf decision; both land independently.
        self.assertEqual(result["mechanism_family_updates"], 1)

    def test_dry_run_before_after_are_null(self) -> None:
        csv_path = _write_csv([_csv_row(event_id=1,
                                        proposed_primary_ticker="MS")])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertIsNone(result["before_clean_fully_ready"])
        self.assertIsNone(result["after_clean_fully_ready"])


# ---------------------------------------------------------------------------
# Write-mode flag validation
# ---------------------------------------------------------------------------


class TestWriteFlagValidation(unittest.TestCase):
    def test_write_without_confirm_rejected(self) -> None:
        result = _run(write=True, confirm=False,
                      backup_path="/tmp/x.db", csv_path="/tmp/x.csv")
        self.assertIs(result["ok"], False)

    def test_write_without_backup_path_rejected(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(
                write=True, confirm=True, csv_path=csv_path, backup_path=None)
        finally:
            os.unlink(csv_path)
        self.assertIs(result["ok"], False)

    def test_write_without_csv_path_rejected(self) -> None:
        backup = _make_temp_db()
        try:
            result = _run(
                write=True, confirm=True, backup_path=backup, csv_path=None)
        finally:
            os.unlink(backup)
        self.assertIs(result["ok"], False)

    def test_backup_equals_db_path_rejected(self) -> None:
        live = _make_temp_db("mb_live")
        csv_path = _write_csv([])
        try:
            result = _run(
                write=True, confirm=True,
                db_path=live, backup_path=live, csv_path=csv_path)
        finally:
            os.unlink(live)
            os.unlink(csv_path)
        self.assertIs(result["ok"], False)


# ---------------------------------------------------------------------------
# Fail-closed precedence
# ---------------------------------------------------------------------------


class TestFailClosedEmptyCSV(unittest.TestCase):
    def test_empty_csv_fails_closed_no_temp_copy(self) -> None:
        backup = _make_temp_db("mb_backup")
        csv_path = _write_csv([])
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["rows_excluded"], 0)
        self.assertEqual(result["rows_retagged"], 0)
        self.assertEqual(result["mechanism_family_updates"], 0)
        self.assertFalse(
            any("Temp copy at " in w for w in result["warnings"]),
            f"warnings: {result['warnings']!r}",
        )


class TestSchemaMissingLowSignal(unittest.TestCase):
    def test_schema_missing_low_signal_fails_closed(self) -> None:
        backup = _make_temp_db("mb_no_ls",
                               with_low_signal=False,
                               seed_events=[
                                   {"id": 1, "event_date": "2026-04-01"},
                               ])
        csv_path = _write_csv([
            _csv_row(event_id=1, exclude_reason="off-topic"),
        ])
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertTrue(
            any("schema_missing_exclusion_field" in e for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )
        self.assertEqual(result["rows_excluded"], 0)


class TestSchemaMissingMechanismFamily(unittest.TestCase):
    def test_schema_missing_mf_fails_closed(self) -> None:
        backup = _make_temp_db("mb_no_mf",
                               with_mechanism_family=False,
                               seed_events=[
                                   {"id": 46, "event_date": "2026-04-06",
                                    "market_tickers":
                                        '[{"symbol":"DRIV"}]'},
                               ])
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="bank_regulatory_capital_relief",
                     event_date="2026-04-06"),
        ])
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertTrue(
            any("schema_missing_mechanism_family_field" in e
                for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )
        # Fail-closed precedence: NEITHER apply NOR mf landed.
        self.assertEqual(result["rows_excluded"], 0)
        self.assertEqual(result["rows_retagged"], 0)
        self.assertEqual(result["mechanism_family_updates"], 0)


# ---------------------------------------------------------------------------
# Provider OFF by default — no probe, no fetch on retag rows
# ---------------------------------------------------------------------------


class TestProviderDisabledByDefault(unittest.TestCase):
    def test_retag_rows_dont_probe_provider_when_backfill_off(self) -> None:
        backup = _make_temp_db("mb_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-01"),
        ])
        try:
            with patch.object(cli, "_check_provider_available") as check:
                with patch.object(cli, "_fetch_ticker_rows") as fetch:
                    with patch.object(cli, "_run_clean_cohort_report",
                                      return_value={"clean_fully_ready_count": 0}):
                        result = _run(
                            csv_path=csv_path, backup_path=backup,
                            write=True, confirm=True,
                        )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["rows_retagged"], 1)
        self.assertFalse(
            check.called,
            "provider must NOT be probed when --with-price-backfill is off",
        )
        self.assertFalse(
            fetch.called,
            "fetch must NOT be called when --with-price-backfill is off",
        )


class TestBackfillOptInProviderUnavailable(unittest.TestCase):
    def test_backfill_on_with_provider_unavailable_fails_closed(self) -> None:
        backup = _make_temp_db("mb_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-01"),
        ])
        try:
            patches = _patch_seams(provider_available=False)
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                    with_price_backfill=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertTrue(
            any("provider" in e.lower() for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )
        # No temp copy written.
        self.assertEqual(result["rows_retagged"], 0)
        self.assertFalse(
            any("Temp copy at " in w for w in result["warnings"]),
            f"warnings: {result['warnings']!r}",
        )


class TestBackfillOptInHappyPath(unittest.TestCase):
    def test_backfill_on_writes_price_rows_into_same_temp(self) -> None:
        backup = _make_temp_db("mb_backup", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV","weight":1.0}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY", event_date="2026-04-06"),
        ])
        try:
            patches = _patch_seams(
                fetch_rows=[_spy_row("2026-03-01"), _spy_row("2026-04-10")],
            )
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                    with_price_backfill=True,
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            conn = sqlite3.connect(tcp)
            try:
                ms_rows = conn.execute(
                    "SELECT date FROM price_cache WHERE ticker = 'MS' "
                    "ORDER BY date"
                ).fetchall()
            finally:
                conn.close()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual([r[0] for r in ms_rows],
                         ["2026-03-01", "2026-04-10"])


# ---------------------------------------------------------------------------
# Apply + mechanism_family happy path (no backfill)
# ---------------------------------------------------------------------------


class TestApplyHappyPath(unittest.TestCase):
    def test_apply_lands_retag_and_mf_decision_in_temp(self) -> None:
        backup = _make_temp_db("mb_backup", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV","weight":1.0}]',
             "mechanism_family": "none"},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="bank_regulatory_capital_relief",
                     event_date="2026-04-06"),
        ])
        try:
            patches = _patch_seams(clean_before=0, clean_after=1)
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            conn = sqlite3.connect(tcp)
            try:
                row = conn.execute(
                    "SELECT mechanism_family, market_tickers "
                    "FROM events WHERE id = 46"
                ).fetchone()
            finally:
                conn.close()
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(row[0], "bank_regulatory_capital_relief")
        parsed = json.loads(row[1])
        self.assertEqual(parsed[0]["symbol"], "MS")
        self.assertEqual(parsed[0]["weight"], 1.0)  # extras preserved
        self.assertEqual(result["rows_retagged"], 1)
        self.assertEqual(result["mechanism_family_updates"], 1)
        self.assertIsInstance(
            result["mechanism_family_updates"], int,
            "mechanism_family_updates must be a bare int — _apply_"
            "mechanism_family_decisions returns (count, ids); the "
            "smoke must unpack to surface only the count",
        )
        self.assertEqual(result["before_clean_fully_ready"], 0)
        self.assertEqual(result["after_clean_fully_ready"], 1)


# ---------------------------------------------------------------------------
# CSV proposed_mechanism_family + CLI flag merging
# ---------------------------------------------------------------------------


class TestCSVMechanismFamilyDecisions(unittest.TestCase):
    def test_csv_column_supplies_decisions(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_mechanism_family="tariff"),
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["mechanism_family_updates"], 1)

    def test_cli_overrides_csv_for_same_event_id(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_mechanism_family="tariff"),
        ])
        try:
            result = _run(
                csv_path=csv_path,
                mechanism_family_decisions=["46=bank_regulatory_capital_relief"],
            )
        finally:
            os.unlink(csv_path)
        # Still exactly one decision (CLI overrode CSV value).
        self.assertEqual(result["mechanism_family_updates"], 1)

    def test_csv_without_mf_column_is_tolerated(self) -> None:
        # CSV variant without the proposed_mechanism_family column —
        # the apply-only packet emits this format.
        csv_path = _write_csv(
            [_csv_row(event_id=1, proposed_primary_ticker="MS")],
            with_mechanism_family_column=False,
        )
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["mechanism_family_updates"], 0)
        self.assertEqual(result["rows_retagged"], 1)
        self.assertIs(result["ok"], True)

    def test_malformed_cli_decision_fails_closed(self) -> None:
        csv_path = _write_csv([])
        try:
            result = _run(
                csv_path=csv_path,
                mechanism_family_decisions=["no-equals-sign"],
            )
        finally:
            os.unlink(csv_path)
        self.assertIs(result["ok"], False)


# ---------------------------------------------------------------------------
# Hash invariants on every fail path
# ---------------------------------------------------------------------------


class TestHashInvariantsAllPaths(unittest.TestCase):
    def test_empty_csv_keeps_hashes(self) -> None:
        live = _make_temp_db("mb_live")
        backup = _make_temp_db("mb_backup")
        csv_path = _write_csv([])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, db_path=live, backup_path=backup,
                    write=True, confirm=True,
                )
            self.assertEqual(_sha256(live),   live_before)
            self.assertEqual(_sha256(backup), backup_before)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)

    def test_schema_missing_keeps_hashes(self) -> None:
        live = _make_temp_db("mb_live")
        backup = _make_temp_db("mb_no_ls",
                               with_low_signal=False,
                               seed_events=[
                                   {"id": 1, "event_date": "2026-04-01"},
                               ])
        csv_path = _write_csv([
            _csv_row(event_id=1, exclude_reason="off-topic"),
        ])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, db_path=live, backup_path=backup,
                    write=True, confirm=True,
                )
            self.assertEqual(_sha256(live),   live_before)
            self.assertEqual(_sha256(backup), backup_before)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)

    def test_success_path_keeps_hashes(self) -> None:
        live = _make_temp_db("mb_live")
        backup = _make_temp_db("mb_backup", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, db_path=live, backup_path=backup,
                    write=True, confirm=True,
                )
            self.assertEqual(_sha256(live),   live_before)
            self.assertEqual(_sha256(backup), backup_before)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)

    def test_backfill_provider_unavailable_keeps_hashes(self) -> None:
        live = _make_temp_db("mb_live")
        backup = _make_temp_db("mb_backup", seed_events=[
            {"id": 1, "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS",
                     event_date="2026-04-01"),
        ])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams(provider_available=False)
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, db_path=live, backup_path=backup,
                    write=True, confirm=True,
                    with_price_backfill=True,
                )
            self.assertEqual(_sha256(live),   live_before)
            self.assertEqual(_sha256(backup), backup_before)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)


# ---------------------------------------------------------------------------
# Patchable seams + import isolation
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_clean_cohort_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_clean_cohort_report")))

    def test_check_provider_available_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_check_provider_available")))

    def test_fetch_ticker_rows_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_fetch_ticker_rows")))


class TestImportIsolation(unittest.TestCase):
    _BLOCKED_MODULES = (
        "yfinance", "market_check", "market_data", "price_cache",
        "api", "fastapi",
    )

    def test_default_dry_run_does_not_import_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED_MODULES
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        csv_path = _write_csv([])
        try:
            cli.smoke_medium_batch_apply(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set())


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _cli(self, argv: list[str], **patch_kwargs) -> tuple[int, str]:
        out = StringIO()
        patches = _patch_seams(**patch_kwargs)
        with patches[0], patches[1], patches[2]:
            try:
                rc = cli.main(argv, out=out)
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue()

    def test_dry_run_default_emits_parseable_json(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=1, proposed_primary_ticker="MS"),
        ])
        try:
            rc, output = self._cli([
                "--dry-run", "--json", "--csv-path", csv_path,
            ])
        finally:
            os.unlink(csv_path)
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(parsed["mode"], "dry-run")

    def test_no_flag_defaults_to_dry_run(self) -> None:
        csv_path = _write_csv([])
        try:
            rc, output = self._cli([
                "--json", "--csv-path", csv_path,
            ])
        finally:
            os.unlink(csv_path)
        parsed = json.loads(output)
        self.assertEqual(parsed["mode"], "dry-run")

    def test_with_price_backfill_flag_parses(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     event_date="2026-04-06"),
        ])
        try:
            rc, output = self._cli([
                "--dry-run", "--json", "--csv-path", csv_path,
                "--with-price-backfill",
            ])
        finally:
            os.unlink(csv_path)
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["mode"], "dry-run")


# ---------------------------------------------------------------------------
# Manual-aware clean-cohort adjustment
#
# The raw clean-cohort report does not know about operator exclusions.
# An event excluded by the operator can still appear as the duplicate
# counterpart of a repaired row in the report's contamination set,
# leaving the repaired row blocked by ``duplicate_date_ticker`` even
# though every contamination signal hangs on a row the operator already
# excluded.  These tests pin the smoke layer's adjustment that honors
# operator exclusions so an operator can read a manual-aware clean
# count without weakening the underlying contamination report.
# ---------------------------------------------------------------------------


def _excluded_example(
    *, event_id: int, flags: list[str],
    primary_ticker: str = "XOM", event_date: str = "2026-04-08",
    headline: str = "h", mechanism_family: str | None = "supply_shock",
) -> dict:
    return {
        "event_id":         event_id,
        "event_date":       event_date,
        "primary_ticker":   primary_ticker,
        "headline":         headline,
        "mechanism_family": mechanism_family,
        "flags":            list(flags),
    }


class TestOperatorExcludedEventIds(unittest.TestCase):
    def test_dry_run_populates_operator_excluded_event_ids(self) -> None:
        # Operator-excluded ids are CSV-derived and don't need a DB
        # read — they should populate even in dry-run so the operator
        # can inspect them before the temp copy lands.
        csv_path = _write_csv([
            _csv_row(event_id=10, exclude_reason="off-topic"),
            _csv_row(event_id=3,  exclude_reason="off-topic"),
            _csv_row(event_id=7,  exclude_reason="off-topic"),
            _csv_row(event_id=5,  proposed_primary_ticker="XOM"),  # retag
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["operator_excluded_event_ids"], [3, 7, 10],
                         "ids should be sorted ascending")

    def test_write_mode_mirrors_csv(self) -> None:
        backup = _make_temp_db("mb_op_excl", seed_events=[
            {"id": 1, "event_date": "2026-04-01"},
            {"id": 2, "event_date": "2026-04-02"},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=1, exclude_reason="off-topic"),
            _csv_row(event_id=2, exclude_reason="off-topic"),
        ])
        try:
            patches = _patch_seams()
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        self.assertEqual(result["operator_excluded_event_ids"], [1, 2])

    def test_empty_when_no_exclusions(self) -> None:
        csv_path = _write_csv([
            _csv_row(event_id=5, proposed_primary_ticker="XOM"),
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertEqual(result["operator_excluded_event_ids"], [])


class TestAdjustedCleanCohort(unittest.TestCase):
    """Pin the narrow adjustment heuristic: an event in
    ``excluded_fully_ready_examples`` whose ONLY contamination flag is
    ``duplicate_date_ticker`` AND that is NOT operator-excluded is
    treated as adjusted-clean (the duplicate counterpart is presumed
    operator-excluded, and the smoke surfaces the operator-aware view
    without weakening the underlying contamination report)."""
    def _build(
        self, csv_rows: list[dict], after_payload: dict,
    ) -> dict:
        backup = _make_temp_db("mb_adj", seed_events=[
            {"id": int(r["event_id"]), "event_date": "2026-04-01",
             "market_tickers": '[{"symbol":"DRIV"}]'}
            for r in csv_rows
        ])
        csv_path = _write_csv(csv_rows)
        try:
            patches = _patch_seams(after_payload=after_payload)
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        return result

    def test_duplicate_only_flag_enters_adjusted_clean(self) -> None:
        # Repaired event (60) has duplicate_date_ticker only; its
        # duplicate counterpart (153) is operator-excluded.  Adjusted
        # clean count should include 60.
        result = self._build(
            csv_rows=[
                _csv_row(event_id=60, proposed_primary_ticker="XOM",
                         proposed_mechanism_family="supply_shock"),
                _csv_row(event_id=153, exclude_reason="off-topic"),
            ],
            after_payload={
                "clean_fully_ready_count":     0,
                "clean_fully_ready_event_ids": [],
                "excluded_fully_ready_examples": [
                    _excluded_example(event_id=60, flags=["duplicate_date_ticker"]),
                ],
            },
        )
        self.assertEqual(result["raw_after_clean_fully_ready"], 0)
        self.assertEqual(result["adjusted_after_clean_fully_ready"], 1)
        self.assertEqual(result["adjusted_clean_fully_ready_delta"], 1)

    def test_multi_flag_stays_in_remaining(self) -> None:
        # Repaired event (60) carries duplicate_date_ticker AND
        # mechanism_family_none — too many flags to safely move to
        # adjusted-clean.  Stays in remaining_contamination_reasons.
        result = self._build(
            csv_rows=[
                _csv_row(event_id=60, proposed_primary_ticker="XOM"),
                _csv_row(event_id=153, exclude_reason="off-topic"),
            ],
            after_payload={
                "clean_fully_ready_count":     0,
                "clean_fully_ready_event_ids": [],
                "excluded_fully_ready_examples": [
                    _excluded_example(
                        event_id=60,
                        flags=["duplicate_date_ticker", "mechanism_family_none"],
                    ),
                ],
            },
        )
        self.assertEqual(result["adjusted_after_clean_fully_ready"], 0)
        self.assertEqual(result["adjusted_clean_fully_ready_delta"], 0)
        self.assertEqual(
            result["remaining_contamination_reasons"],
            {"60": ["duplicate_date_ticker", "mechanism_family_none"]},
        )

    def test_operator_excluded_neither_adjusted_nor_remaining(self) -> None:
        # Event 153 is operator-excluded.  Even with duplicate-only
        # flag, it must NOT enter adjusted-clean and must NOT surface
        # in remaining_contamination_reasons (operator already decided).
        result = self._build(
            csv_rows=[
                _csv_row(event_id=153, exclude_reason="off-topic"),
            ],
            after_payload={
                "clean_fully_ready_count":     0,
                "clean_fully_ready_event_ids": [],
                "excluded_fully_ready_examples": [
                    _excluded_example(event_id=153,
                                      flags=["duplicate_date_ticker"]),
                ],
            },
        )
        self.assertEqual(result["adjusted_after_clean_fully_ready"], 0)
        self.assertEqual(result["adjusted_clean_fully_ready_delta"], 0)
        self.assertEqual(result["remaining_contamination_reasons"], {})

    def test_adjusted_delta_is_adjusted_minus_raw(self) -> None:
        # raw=2, adjusted should = raw + 1 (one duplicate-only repaired
        # event added).  delta = +1.
        result = self._build(
            csv_rows=[
                _csv_row(event_id=60, proposed_primary_ticker="XOM"),
                _csv_row(event_id=153, exclude_reason="off-topic"),
            ],
            after_payload={
                "clean_fully_ready_count":     2,
                "clean_fully_ready_event_ids": [100, 101],
                "excluded_fully_ready_examples": [
                    _excluded_example(event_id=60,
                                      flags=["duplicate_date_ticker"]),
                ],
            },
        )
        self.assertEqual(result["raw_after_clean_fully_ready"], 2)
        self.assertEqual(result["adjusted_after_clean_fully_ready"], 3)
        self.assertEqual(result["adjusted_clean_fully_ready_delta"], 1)

    def test_operator_excluded_in_raw_clean_subtracted(self) -> None:
        # Defensive: an operator-excluded event somehow appears in the
        # raw clean cohort.  Adjusted view must drop it from the
        # aggregate-claim eligible set.
        result = self._build(
            csv_rows=[
                _csv_row(event_id=42, exclude_reason="off-topic"),
            ],
            after_payload={
                "clean_fully_ready_count":     2,
                "clean_fully_ready_event_ids": [42, 100],
                "excluded_fully_ready_examples": [],
            },
        )
        self.assertEqual(result["raw_after_clean_fully_ready"], 2)
        # 42 is operator-excluded → drop from aggregate claim → 1.
        self.assertEqual(result["adjusted_after_clean_fully_ready"], 1)
        self.assertEqual(result["adjusted_clean_fully_ready_delta"], -1)

    def test_remaining_keys_are_string_event_ids(self) -> None:
        # JSON object keys are strings; pin the str(event_id) projection
        # so a future refactor doesn't drift to int keys.
        result = self._build(
            csv_rows=[
                _csv_row(event_id=63, proposed_primary_ticker="CVX"),
            ],
            after_payload={
                "clean_fully_ready_count":     0,
                "clean_fully_ready_event_ids": [],
                "excluded_fully_ready_examples": [
                    _excluded_example(event_id=63,
                                      flags=["mechanism_family_none"]),
                ],
            },
        )
        self.assertIn("63", result["remaining_contamination_reasons"])
        self.assertNotIn(63, result["remaining_contamination_reasons"])

    def test_remaining_flags_sorted_ascending(self) -> None:
        result = self._build(
            csv_rows=[
                _csv_row(event_id=49, proposed_primary_ticker="XOM"),
            ],
            after_payload={
                "clean_fully_ready_count":     0,
                "clean_fully_ready_event_ids": [],
                "excluded_fully_ready_examples": [
                    _excluded_example(event_id=49,
                                      flags=["mechanism_family_none",
                                             "driv_lit_off_topic",
                                             "duplicate_date_ticker"]),
                ],
            },
        )
        self.assertEqual(
            result["remaining_contamination_reasons"]["49"],
            ["driv_lit_off_topic", "duplicate_date_ticker",
             "mechanism_family_none"],
        )

    def test_dry_run_count_fields_null_remaining_empty_dict(self) -> None:
        # In dry-run, the four count fields are None (no DB report
        # available); remaining_contamination_reasons is an EMPTY DICT
        # (not None) so consumers can iterate it unconditionally.
        csv_path = _write_csv([
            _csv_row(event_id=153, exclude_reason="off-topic"),
            _csv_row(event_id=60,  proposed_primary_ticker="XOM"),
        ])
        try:
            result = _run(csv_path=csv_path)
        finally:
            os.unlink(csv_path)
        self.assertIsNone(result["raw_after_clean_fully_ready"])
        self.assertIsNone(result["adjusted_after_clean_fully_ready"])
        self.assertIsNone(result["adjusted_clean_fully_ready_delta"])
        self.assertEqual(result["remaining_contamination_reasons"], {})
        self.assertEqual(result["operator_excluded_event_ids"], [153])


# ---------------------------------------------------------------------------
# Conservative-language ban — the new fields carry only structured data,
# but warnings should never adopt forbidden vocabulary.
# ---------------------------------------------------------------------------


_FORBIDDEN_WORDS = (
    "delete",
    "auto-correct",
    "auto fix",
    "automatic",
    "fix the",
    "correct the",
)


class TestConservativeWording(unittest.TestCase):
    def test_warnings_avoid_forbidden_phrases(self) -> None:
        result = self._run_full_smoke()
        joined = " ".join(result.get("warnings", [])).lower()
        for phrase in _FORBIDDEN_WORDS:
            self.assertNotIn(
                phrase, joined,
                f"warning text used forbidden phrasing {phrase!r}",
            )

    def _run_full_smoke(self) -> dict:
        backup = _make_temp_db("mb_lang", seed_events=[
            {"id": 60, "event_date": "2026-04-08",
             "market_tickers": '[{"symbol":"DRIV"}]'},
            {"id": 153, "event_date": "2026-04-29"},
        ])
        csv_path = _write_csv([
            _csv_row(event_id=60, proposed_primary_ticker="XOM",
                     proposed_mechanism_family="supply_shock",
                     event_date="2026-04-08"),
            _csv_row(event_id=153, exclude_reason="off-topic",
                     event_date="2026-04-29"),
        ])
        try:
            patches = _patch_seams(after_payload={
                "clean_fully_ready_count":     0,
                "clean_fully_ready_event_ids": [],
                "excluded_fully_ready_examples": [
                    _excluded_example(event_id=60,
                                      flags=["duplicate_date_ticker"]),
                ],
            })
            with patches[0], patches[1], patches[2]:
                result = _run(
                    csv_path=csv_path, backup_path=backup,
                    write=True, confirm=True,
                )
        finally:
            os.unlink(backup)
            os.unlink(csv_path)
            _cleanup_temp_copy(result)
        return result


if __name__ == "__main__":
    unittest.main()
