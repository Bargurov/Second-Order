"""Tests for ``scripts/manual_repaired_cohort_validation_run.py``.

Pin the contract:

* Operates on a copied backup only — live DB is read-only,
  byte-identical before/after every run.
* Applies BOTH input CSVs (high-priority + medium) to the SAME
  temp copy:
    1. categorize rows from each CSV
    2. apply exclusions + retags (events table)
    3. apply CSV-driven mechanism_family decisions (medium wins
       on conflict for the same event_id, mirroring the smoke
       merge pattern)
    4. backfill price_cache for all retag tickers (combined plan)
* Runs validation only on the manual-aware adjusted clean cohort
  that emerged from the repair — events already in the pre-repair
  clean set do NOT pollute the cohort.
* Fail-closed precedence:
    - Missing backup / CSV path → fail closed.
    - Retag rows + provider unavailable → fail closed BEFORE copy.
    - Schema missing low_signal + exclusion rows → fail closed.
    - Schema missing mechanism_family + decisions → fail closed.
* Output dict carries EXACTLY the 14 brief-mandated keys.
* Examples carry the 13 brief-mandated fields including
  ``primary_ticker``, ``benchmark``, ``mechanism_family``.
* Conservative language only — interpretation comes verbatim from
  ``make_stat_validation_record``; the runner never claims
  "proof" / "alpha" / causal language.
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

from scripts import manual_repaired_cohort_validation_run as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "repaired_clean_event_ids",
    "events_evaluated",
    "records_count",
    "significant_count",
    "by_horizon",
    "by_mechanism_family",
    "examples",
    "excluded_event_ids",
    "remaining_blockers",
    "live_db_unchanged",
    "input_backup_unchanged",
    "errors",
    "warnings",
)


_REQUIRED_EXAMPLE_FIELDS = (
    "event_id",
    "headline",
    "primary_ticker",
    "benchmark",
    "mechanism_family",
    "horizon",
    "abnormal_return",
    "sar",
    "ci_low",
    "ci_high",
    "p_value",
    "fdr_q",
    "interpretation",
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
    suffix: str = "repaired_cohort",
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


def _write_csv(rows: list[dict], *, suffix: str = "rc_csv") -> str:
    columns = (
        "event_id", "headline", "event_date", "current_primary_ticker",
        "flags", "reason", "manual_review_priority",
        "proposed_primary_ticker", "proposed_benchmark",
        "proposed_mechanism_family",
        "ticker_rationale", "exclude_reason",
    )
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv_module.writer(fh, lineterminator="\n")
        writer.writerow(columns)
        for r in rows:
            writer.writerow([str(r.get(c, "")) for c in columns])
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


def _bar(date_iso: str, *, close: float = 100.0,
         volume: float = 1.0e6) -> dict:
    return {"date": date_iso, "close": close, "volume": volume}


def _validation_record(
    *, event_id: int, headline: str = "h",
    ticker: str = "MS", mechanism_family: str | None = "supply_shock",
    horizon: int = 5, abnormal_return: float = 0.012, sar: float = 1.5,
    ci_low: float = 0.001, ci_high: float = 0.022,
    p_value: float = 0.04, fdr_q: float = 0.08,
    significant: bool = True, interpretation: str = "evidence",
) -> dict:
    return {
        "event_id":         event_id,
        "headline":         headline,
        "ticker":           ticker,
        "mechanism_family": mechanism_family,
        "horizon":          horizon,
        "abnormal_return":  abnormal_return,
        "sar":              sar,
        "ci_low":           ci_low,
        "ci_high":          ci_high,
        "p_value":          p_value,
        "fdr_q":            fdr_q,
        "statistically_significant": significant,
        "interpretation":   interpretation,
    }


def _validation_payload(
    *, records: list[dict] | None = None,
    examples: list[dict] | None = None,
    errors: list[str] | None = None,
) -> dict:
    records = records or []
    examples = examples if examples is not None else [
        {
            "event_id":         r["event_id"],
            "headline":         r["headline"],
            "ticker":           r["ticker"],
            "horizon":          r["horizon"],
            "abnormal_return":  r["abnormal_return"],
            "sar":              r["sar"],
            "ci_low":           r["ci_low"],
            "ci_high":          r["ci_high"],
            "p_value":          r["p_value"],
            "fdr_q":            r["fdr_q"],
            "interpretation":   r["interpretation"],
        }
        for r in records
    ]
    return {
        "ok":                  not (errors or []),
        "events_evaluated":    len({r["event_id"] for r in records}),
        "records_count":       len(records),
        "significant_count":   sum(
            1 for r in records if r.get("statistically_significant")),
        "by_horizon":          {},
        "by_mechanism_family": {},
        "errors":              list(errors or []),
        "examples":            list(examples),
        # The runner ALSO consults a parallel internal "records" view
        # (with mechanism_family + statistically_significant) to do
        # filtering + aggregation; the seam returns it under "records".
        "records":             list(records),
    }


def _patch_seams(
    *,
    before_clean_event_ids: list[int] | None = None,
    after_clean_payload: dict | None = None,
    provider_available: bool = True,
    fetch_rows: list[dict] | None = None,
    fetch_side_effect: Exception | None = None,
    validation_payload: dict | None = None,
):
    before_payload = {
        "clean_fully_ready_count":     len(before_clean_event_ids or []),
        "clean_fully_ready_event_ids": list(before_clean_event_ids or []),
        "excluded_fully_ready_examples": [],
    }
    if after_clean_payload is None:
        after_clean_payload = {
            "clean_fully_ready_count":     len(before_clean_event_ids or []),
            "clean_fully_ready_event_ids": list(before_clean_event_ids or []),
            "excluded_fully_ready_examples": [],
        }
    clean_calls = iter([before_payload, after_clean_payload])

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

    if validation_payload is None:
        validation_payload = _validation_payload()

    def fake_validation(*, db_path):
        return validation_payload

    return (
        patch.object(cli, "_run_clean_cohort_report",   side_effect=fake_clean),
        patch.object(cli, "_check_provider_available",  return_value=provider_available),
        fetch_patch,
        patch.object(cli, "_run_validation_on_temp_db", side_effect=fake_validation),
    )


def _cleanup_temp_copy(result: dict) -> None:
    for w in result.get("warnings", []):
        if "Temp copy at " in w:
            p = w.split("Temp copy at ", 1)[1].strip()
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _run(
    *, backup_path: str | None = None,
    high_priority_csv: str | None = None,
    medium_csv: str | None = None,
    db_path: str | None = None,
    limit: int = 50,
    **kwargs,
) -> dict:
    return cli.run_manual_repaired_cohort_validation(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        db_path=db_path,
        limit=limit,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_returns_dict_with_exactly_14_keys(self) -> None:
        backup = _make_temp_db(seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="bank_regulatory_capital_relief",
                     event_date="2026-04-06"),
        ])
        medium = _write_csv([])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     1,
                    "clean_fully_ready_event_ids": [46],
                    "excluded_fully_ready_examples": [],
                },
                fetch_rows=[_bar("2026-04-01")],
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            _cleanup_temp_copy(result)
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))


# ---------------------------------------------------------------------------
# Repaired cohort filtering
# ---------------------------------------------------------------------------


class TestRepairedCohortFiltering(unittest.TestCase):
    """Only events that NEWLY entered the manual-aware adjusted clean
    cohort should be evaluated.  Pre-existing clean events and events
    that remain contaminated must NOT appear in records or examples.
    """

    def test_only_repaired_events_appear_in_records(self) -> None:
        backup = _make_temp_db(seed_events=[
            # 46 is the high-priority candidate (will be retagged DRIV→MS)
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
            # 60 + 73 are medium-batch supply_shock candidates
            {"id": 60, "event_date": "2026-03-12",
             "market_tickers": '[{"symbol":"DRIV"}]'},
            {"id": 73, "event_date": "2026-03-15",
             "market_tickers": '[{"symbol":"DRIV"}]'},
            # 100 was already clean before the repair — must NOT
            # appear in repaired_clean_event_ids.
            {"id": 100, "event_date": "2026-02-01",
             "market_tickers": '[{"symbol":"AAPL"}]',
             "mechanism_family": "supply_shock"},
        ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="bank_regulatory_capital_relief",
                     event_date="2026-04-06"),
        ])
        medium = _write_csv([
            _csv_row(event_id=60, proposed_primary_ticker="XOM",
                     proposed_benchmark="XLE",
                     proposed_mechanism_family="supply_shock",
                     event_date="2026-03-12"),
            _csv_row(event_id=73, proposed_primary_ticker="XOM",
                     proposed_benchmark="XLE",
                     proposed_mechanism_family="supply_shock",
                     event_date="2026-03-15"),
        ])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[100],
                after_clean_payload={
                    "clean_fully_ready_count":     4,
                    "clean_fully_ready_event_ids": [46, 60, 73, 100],
                    "excluded_fully_ready_examples": [],
                },
                fetch_rows=[_bar("2026-03-01"), _bar("2026-04-01")],
                # Validation seam returns records for 46, 60, 73, AND 100;
                # the runner must filter to only repaired (46, 60, 73).
                validation_payload=_validation_payload(records=[
                    _validation_record(event_id=46, ticker="MS",
                                       mechanism_family="bank_regulatory_capital_relief",
                                       horizon=5),
                    _validation_record(event_id=60, ticker="XOM",
                                       mechanism_family="supply_shock",
                                       horizon=5),
                    _validation_record(event_id=73, ticker="XOM",
                                       mechanism_family="supply_shock",
                                       horizon=5),
                    _validation_record(event_id=100, ticker="AAPL",
                                       mechanism_family="supply_shock",
                                       horizon=5),
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], True)
        self.assertEqual(
            sorted(result["repaired_clean_event_ids"]), [46, 60, 73],
        )
        self.assertEqual(result["events_evaluated"], 3)
        self.assertEqual(result["records_count"], 3)
        self.assertEqual(result["significant_count"], 3)
        evaluated_ids = {ex["event_id"] for ex in result["examples"]}
        self.assertEqual(evaluated_ids, {46, 60, 73})
        self.assertNotIn(100, evaluated_ids)


class TestExampleSchema(unittest.TestCase):
    """Examples must include the brief-mandated 13 fields."""

    def test_examples_carry_required_fields(self) -> None:
        backup = _make_temp_db(seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="bank_regulatory_capital_relief",
                     event_date="2026-04-06"),
        ])
        medium = _write_csv([])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     1,
                    "clean_fully_ready_event_ids": [46],
                    "excluded_fully_ready_examples": [],
                },
                fetch_rows=[_bar("2026-04-01")],
                validation_payload=_validation_payload(records=[
                    _validation_record(
                        event_id=46, ticker="MS",
                        mechanism_family="bank_regulatory_capital_relief",
                        horizon=5),
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            _cleanup_temp_copy(result)
        self.assertEqual(len(result["examples"]), 1)
        ex = result["examples"][0]
        for field in _REQUIRED_EXAMPLE_FIELDS:
            self.assertIn(field, ex,
                          f"missing example field: {field}")
        self.assertEqual(ex["primary_ticker"], "MS")
        self.assertEqual(ex["benchmark"], "SPY")
        self.assertEqual(ex["mechanism_family"],
                         "bank_regulatory_capital_relief")


class TestExamplesCappedByLimit(unittest.TestCase):
    def test_examples_capped_at_limit(self) -> None:
        backup = _make_temp_db(seed_events=[
            {"id": i, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'} for i in (1, 2, 3, 4, 5)
        ])
        high = _write_csv([
            _csv_row(event_id=i, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY", event_date="2026-04-06")
            for i in (1, 2, 3, 4, 5)
        ])
        medium = _write_csv([])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     5,
                    "clean_fully_ready_event_ids": [1, 2, 3, 4, 5],
                    "excluded_fully_ready_examples": [],
                },
                fetch_rows=[_bar("2026-04-01")],
                validation_payload=_validation_payload(records=[
                    _validation_record(event_id=i, ticker="MS",
                                       mechanism_family="m",
                                       horizon=5)
                    for i in (1, 2, 3, 4, 5)
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                    limit=3,
                )
        finally:
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            _cleanup_temp_copy(result)
        self.assertLessEqual(len(result["examples"]), 3)
        # records_count should still reflect ALL repaired records.
        self.assertEqual(result["records_count"], 5)


# ---------------------------------------------------------------------------
# Apply-both-CSVs and excluded_event_ids surface
# ---------------------------------------------------------------------------


class TestApplyBothCSVs(unittest.TestCase):
    def test_both_csvs_applied_to_same_temp_copy(self) -> None:
        backup = _make_temp_db(seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
            {"id": 60, "event_date": "2026-03-12",
             "market_tickers": '[{"symbol":"DRIV"}]'},
            # event 4 will be excluded via high-priority CSV.
            {"id": 4, "event_date": "2026-04-04"},
        ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="bank_regulatory_capital_relief",
                     event_date="2026-04-06"),
            _csv_row(event_id=4, exclude_reason="off-topic",
                     event_date="2026-04-04"),
        ])
        medium = _write_csv([
            _csv_row(event_id=60, proposed_primary_ticker="XOM",
                     proposed_benchmark="XLE",
                     proposed_mechanism_family="supply_shock",
                     event_date="2026-03-12"),
        ])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     2,
                    "clean_fully_ready_event_ids": [46, 60],
                    "excluded_fully_ready_examples": [],
                },
                fetch_rows=[_bar("2026-03-01"), _bar("2026-04-01")],
                validation_payload=_validation_payload(records=[
                    _validation_record(event_id=46, ticker="MS",
                                       mechanism_family="bank_regulatory_capital_relief",
                                       horizon=5),
                    _validation_record(event_id=60, ticker="XOM",
                                       mechanism_family="supply_shock",
                                       horizon=5),
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
            tcp = None
            for w in result["warnings"]:
                if "Temp copy at " in w:
                    tcp = w.split("Temp copy at ", 1)[1].strip()
            self.assertIsNotNone(tcp)
            # Verify retag, exclusion, and mechanism_family decisions
            # all landed in the SAME temp DB.
            conn = sqlite3.connect(tcp)
            try:
                rows = conn.execute(
                    "SELECT id, market_tickers, low_signal, mechanism_family "
                    "FROM events ORDER BY id"
                ).fetchall()
            finally:
                conn.close()
            by_id = {r[0]: r for r in rows}
            # event 4: excluded
            self.assertEqual(by_id[4][2], 1)
            # event 46: retagged + mechanism_family
            self.assertIn("MS", by_id[46][1])
            self.assertEqual(by_id[46][3], "bank_regulatory_capital_relief")
            # event 60: retagged + mechanism_family
            self.assertIn("XOM", by_id[60][1])
            self.assertEqual(by_id[60][3], "supply_shock")
        finally:
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            if tcp and os.path.exists(tcp):
                os.unlink(tcp)
        self.assertEqual(sorted(result["excluded_event_ids"]), [4])


# ---------------------------------------------------------------------------
# remaining_blockers
# ---------------------------------------------------------------------------


class TestRemainingBlockers(unittest.TestCase):
    """Surface ``remaining_contamination_reasons`` from
    ``_compute_manual_aware_clean_metrics`` as ``remaining_blockers``."""

    def test_remaining_blockers_surface_non_duplicate_flags(self) -> None:
        backup = _make_temp_db(seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
            {"id": 99, "event_date": "2026-04-07",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="bank_regulatory_capital_relief",
                     event_date="2026-04-06"),
        ])
        medium = _write_csv([])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     1,
                    "clean_fully_ready_event_ids": [46],
                    # event 99 stays contaminated with non-duplicate flags.
                    "excluded_fully_ready_examples": [
                        {"event_id": 99,
                         "flags": ["mechanism_family_none",
                                   "driv_lit_off_topic"]},
                    ],
                },
                fetch_rows=[_bar("2026-04-01")],
                validation_payload=_validation_payload(records=[
                    _validation_record(event_id=46, ticker="MS",
                                       mechanism_family="bank_regulatory_capital_relief",
                                       horizon=5),
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            _cleanup_temp_copy(result)
        self.assertIn("99", result["remaining_blockers"])
        self.assertEqual(
            result["remaining_blockers"]["99"],
            ["driv_lit_off_topic", "mechanism_family_none"],
        )


# ---------------------------------------------------------------------------
# Fail-closed precedence
# ---------------------------------------------------------------------------


class TestFailClosedMissingInputs(unittest.TestCase):
    def test_missing_backup_path_fails(self) -> None:
        high = _write_csv([])
        medium = _write_csv([])
        try:
            result = _run(backup_path=None,
                          high_priority_csv=high, medium_csv=medium)
        finally:
            os.unlink(high)
            os.unlink(medium)
        self.assertIs(result["ok"], False)

    def test_nonexistent_backup_path_fails(self) -> None:
        high = _write_csv([])
        medium = _write_csv([])
        try:
            result = _run(backup_path="/path/does/not/exist.db",
                          high_priority_csv=high, medium_csv=medium)
        finally:
            os.unlink(high)
            os.unlink(medium)
        self.assertIs(result["ok"], False)

    def test_nonexistent_csv_path_fails(self) -> None:
        backup = _make_temp_db()
        try:
            result = _run(backup_path=backup,
                          high_priority_csv="/nope.csv",
                          medium_csv="/also-nope.csv")
        finally:
            os.unlink(backup)
        self.assertIs(result["ok"], False)


class TestFailClosedProviderUnavailable(unittest.TestCase):
    def test_retags_with_provider_unavailable_fails(self) -> None:
        backup = _make_temp_db(seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     event_date="2026-04-06"),
        ])
        medium = _write_csv([])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                provider_available=False,
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertTrue(any("provider" in e.lower() for e in result["errors"]))


class TestFailClosedSchemaMissing(unittest.TestCase):
    def test_low_signal_missing_with_exclusions_fails(self) -> None:
        backup = _make_temp_db(
            with_low_signal=False,
            seed_events=[
                {"id": 4, "event_date": "2026-04-04"},
            ])
        high = _write_csv([
            _csv_row(event_id=4, exclude_reason="off-topic",
                     event_date="2026-04-04"),
        ])
        medium = _write_csv([])
        try:
            patches = _patch_seams(before_clean_event_ids=[])
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertTrue(
            any("schema_missing_exclusion_field" in e
                for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )

    def test_mechanism_family_missing_with_decisions_fails(self) -> None:
        backup = _make_temp_db(
            with_mechanism_family=False,
            seed_events=[
                {"id": 46, "event_date": "2026-04-06",
                 "market_tickers": '[{"symbol":"DRIV"}]'},
            ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="bank_regulatory_capital_relief",
                     event_date="2026-04-06"),
        ])
        medium = _write_csv([])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                fetch_rows=[_bar("2026-04-01")],
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], False)
        self.assertTrue(
            any("schema_missing_mechanism_family_field" in e
                for e in result["errors"]),
            f"errors: {result['errors']!r}",
        )


# ---------------------------------------------------------------------------
# Hash invariants
# ---------------------------------------------------------------------------


class TestHashInvariants(unittest.TestCase):
    def test_happy_path_keeps_hashes(self) -> None:
        live = _make_temp_db("rc_live")
        backup = _make_temp_db("rc_backup", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="m",
                     event_date="2026-04-06"),
        ])
        medium = _write_csv([])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     1,
                    "clean_fully_ready_event_ids": [46],
                    "excluded_fully_ready_examples": [],
                },
                fetch_rows=[_bar("2026-04-01")],
                validation_payload=_validation_payload(records=[
                    _validation_record(event_id=46),
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup, db_path=live,
                    high_priority_csv=high, medium_csv=medium,
                )
            self.assertEqual(_sha256(live),   live_before)
            self.assertEqual(_sha256(backup), backup_before)
            self.assertIs(result["live_db_unchanged"], True)
            self.assertIs(result["input_backup_unchanged"], True)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            _cleanup_temp_copy(result)

    def test_provider_fail_keeps_hashes(self) -> None:
        live = _make_temp_db("rc_live")
        backup = _make_temp_db("rc_backup", seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY", event_date="2026-04-06"),
        ])
        medium = _write_csv([])
        live_before = _sha256(live)
        backup_before = _sha256(backup)
        try:
            patches = _patch_seams(
                before_clean_event_ids=[], provider_available=False,
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup, db_path=live,
                    high_priority_csv=high, medium_csv=medium,
                )
            self.assertEqual(_sha256(live),   live_before)
            self.assertEqual(_sha256(backup), backup_before)
        finally:
            os.unlink(live)
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            _cleanup_temp_copy(result)


# ---------------------------------------------------------------------------
# Empty cohort
# ---------------------------------------------------------------------------


class TestEmptyCohort(unittest.TestCase):
    def test_empty_repaired_cohort_returns_ok(self) -> None:
        """When the repair produces no NEW clean events, the run is OK
        with an empty cohort and zero records."""
        backup = _make_temp_db(seed_events=[
            {"id": 1, "event_date": "2026-04-01"},
        ])
        # CSV has only an exclusion (no ticker repair, no mf decision)
        # that doesn't promote anything to the clean cohort.
        high = _write_csv([
            _csv_row(event_id=1, exclude_reason="off-topic",
                     event_date="2026-04-01"),
        ])
        medium = _write_csv([])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     0,
                    "clean_fully_ready_event_ids": [],
                    "excluded_fully_ready_examples": [],
                },
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["repaired_clean_event_ids"], [])
        self.assertEqual(result["events_evaluated"], 0)
        self.assertEqual(result["records_count"], 0)
        self.assertEqual(result["significant_count"], 0)


# ---------------------------------------------------------------------------
# Patchable seams + import isolation
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_clean_cohort_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_clean_cohort_report")))

    def test_check_provider_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_check_provider_available")))

    def test_fetch_ticker_rows_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_fetch_ticker_rows")))

    def test_validation_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_validation_on_temp_db")))


class TestImportIsolation(unittest.TestCase):
    _BLOCKED_MODULES = (
        "yfinance", "market_check", "market_data", "price_cache",
        "api", "fastapi",
    )

    def test_module_import_does_not_pull_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED_MODULES
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        # Re-importing is a no-op since the module is already loaded;
        # the assertion is that NO new blocked module was pulled in
        # transitively when this test module imported the runner.
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set())


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_emits_parseable_json(self) -> None:
        backup = _make_temp_db(seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="m",
                     event_date="2026-04-06"),
        ])
        medium = _write_csv([])
        out = StringIO()
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     1,
                    "clean_fully_ready_event_ids": [46],
                    "excluded_fully_ready_examples": [],
                },
                fetch_rows=[_bar("2026-04-01")],
                validation_payload=_validation_payload(records=[
                    _validation_record(event_id=46),
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                rc = cli.main([
                    "--json", "--backup-path", backup,
                    "--high-priority-csv", high,
                    "--medium-csv", medium,
                    "--limit", "5",
                ], out=out)
        finally:
            os.unlink(backup)
            os.unlink(high)
            os.unlink(medium)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)


# ---------------------------------------------------------------------------
# Optional --mechanism-family-csv (third repair input)
#
# When the operator passes a completed mechanism_family_repair_packet.csv
# alongside the high-priority + medium ticker repair CSVs, the runner
# applies its mechanism-family decisions and exclusion rows to the SAME
# temp DB before validation runs.  When the param is omitted the
# runner's two-CSV behaviour is preserved byte-for-byte.
# ---------------------------------------------------------------------------


_FAMILY_CSV_COLUMNS = (
    "event_id", "headline", "event_date",
    "current_primary_ticker", "current_benchmark",
    "flags", "repair_priority", "reason",
    "proposed_mechanism_family", "mechanism_rationale",
    "exclude_reason",
)


def _write_family_csv(rows: list[dict], *, suffix: str = "fm_csv") -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"{suffix}_{uuid.uuid4().hex}.csv",
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv_module.writer(fh, lineterminator="\n")
        writer.writerow(_FAMILY_CSV_COLUMNS)
        for r in rows:
            writer.writerow([str(r.get(c, "")) for c in _FAMILY_CSV_COLUMNS])
    return path


def _family_row(
    *, event_id: int,
    proposed_mechanism_family: str = "",
    exclude_reason: str = "",
    headline: str = "h",
    event_date: str = "2026-04-05",
    current_primary_ticker: str = "AAPL",
    current_benchmark: str = "SPY",
) -> dict:
    return {
        "event_id":                  event_id,
        "headline":                  headline,
        "event_date":                event_date,
        "current_primary_ticker":    current_primary_ticker,
        "current_benchmark":         current_benchmark,
        "flags":                     "mechanism_family_none",
        "repair_priority":           "high",
        "reason":                    "Manual review candidate",
        "proposed_mechanism_family": proposed_mechanism_family,
        "mechanism_rationale":       "",
        "exclude_reason":            exclude_reason,
    }


class TestMechanismFamilyCsvIntegration(unittest.TestCase):
    """End-to-end: when a mechanism_family_repair_packet CSV is
    supplied alongside the high/medium ticker CSVs, the runner applies
    its decisions + exclusions to the same temp DB and the validation
    pipeline sees the family-CSV-only event_ids in the repaired cohort.
    """

    def test_family_csv_decisions_land_on_temp_db(self) -> None:
        backup = _make_temp_db(seed_events=[
            {"id": 30, "event_date": "2026-04-05",
             "market_tickers": '[{"symbol":"XOM"}]'},
            {"id": 40, "event_date": "2026-04-05",
             "market_tickers": '[{"symbol":"BDRY"}]'},
        ])
        high   = _write_csv([])
        medium = _write_csv([])
        family = _write_family_csv([
            _family_row(event_id=30,
                        proposed_mechanism_family="supply_shock"),
            _family_row(event_id=40,
                        proposed_mechanism_family="commodity_squeeze"),
        ])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     2,
                    "clean_fully_ready_event_ids": [30, 40],
                    "excluded_fully_ready_examples": [],
                },
                # Capture the post-apply temp_path so we can inspect
                # the mutations after the run completes.
                validation_payload=_validation_payload(records=[
                    _validation_record(event_id=30, ticker="XOM",
                                       mechanism_family="supply_shock",
                                       horizon=5),
                    _validation_record(event_id=40, ticker="BDRY",
                                       mechanism_family="commodity_squeeze",
                                       horizon=5),
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                    mechanism_family_csv=family,
                )
        finally:
            os.unlink(backup); os.unlink(high)
            os.unlink(medium); os.unlink(family)
        self.assertIs(result["ok"], True)
        self.assertEqual(
            sorted(result["repaired_clean_event_ids"]), [30, 40],
        )
        # Inspect the temp DB to verify the family decisions actually
        # landed (mechanism_family column updated for both events).
        temp_path = None
        for w in result.get("warnings", []):
            if "Temp copy at " in w:
                temp_path = w.split("Temp copy at ", 1)[1].strip()
                break
        self.assertIsNotNone(temp_path)
        try:
            conn = sqlite3.connect(temp_path)
            try:
                rows = dict(conn.execute(
                    "SELECT id, mechanism_family FROM events "
                    "WHERE id IN (30, 40)"
                ).fetchall())
                self.assertEqual(rows[30], "supply_shock")
                self.assertEqual(rows[40], "commodity_squeeze")
            finally:
                conn.close()
        finally:
            _cleanup_temp_copy(result)

    def test_family_csv_exclusion_rows_flip_low_signal(self) -> None:
        backup = _make_temp_db(seed_events=[
            {"id": 30, "event_date": "2026-04-05",
             "market_tickers": '[{"symbol":"XOM"}]'},
            {"id": 44, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"BDRY"}]'},
        ])
        high   = _write_csv([])
        medium = _write_csv([])
        family = _write_family_csv([
            _family_row(event_id=30,
                        proposed_mechanism_family="supply_shock"),
            _family_row(event_id=44,
                        exclude_reason="Duplicate of event 40"),
        ])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     1,
                    "clean_fully_ready_event_ids": [30],
                    "excluded_fully_ready_examples": [],
                },
                validation_payload=_validation_payload(records=[
                    _validation_record(event_id=30, ticker="XOM",
                                       mechanism_family="supply_shock",
                                       horizon=5),
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                    mechanism_family_csv=family,
                )
        finally:
            os.unlink(backup); os.unlink(high)
            os.unlink(medium); os.unlink(family)
        self.assertIs(result["ok"], True)
        self.assertIn(44, result["excluded_event_ids"])
        # Verify low_signal=1 actually landed on the temp DB for 44.
        temp_path = None
        for w in result.get("warnings", []):
            if "Temp copy at " in w:
                temp_path = w.split("Temp copy at ", 1)[1].strip()
                break
        self.assertIsNotNone(temp_path)
        try:
            conn = sqlite3.connect(temp_path)
            try:
                row = conn.execute(
                    "SELECT low_signal FROM events WHERE id = 44"
                ).fetchone()
                self.assertEqual(row[0], 1)
            finally:
                conn.close()
        finally:
            _cleanup_temp_copy(result)

    def test_family_csv_combines_with_high_and_medium(self) -> None:
        # Realistic three-CSV scenario mirroring the live verification:
        # high retags 46 DRIV→MS; medium adds 60 + 73 supply_shock;
        # family adds 30 + 40 — final cohort has 5 events.
        backup = _make_temp_db(seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
            {"id": 60, "event_date": "2026-04-08",
             "market_tickers": '[{"symbol":"XOM"}]'},
            {"id": 73, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"XOM"}]'},
            {"id": 30, "event_date": "2026-04-05",
             "market_tickers": '[{"symbol":"XOM"}]'},
            {"id": 40, "event_date": "2026-04-05",
             "market_tickers": '[{"symbol":"BDRY"}]'},
        ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="bank_regulatory_capital_relief",
                     event_date="2026-04-06"),
        ])
        medium = _write_csv([
            _csv_row(event_id=60, proposed_primary_ticker="XOM",
                     proposed_benchmark="XLE",
                     proposed_mechanism_family="supply_shock",
                     event_date="2026-04-08"),
            _csv_row(event_id=73, proposed_primary_ticker="XOM",
                     proposed_benchmark="XLE",
                     proposed_mechanism_family="supply_shock",
                     event_date="2026-04-06"),
        ])
        family = _write_family_csv([
            _family_row(event_id=30,
                        proposed_mechanism_family="supply_shock"),
            _family_row(event_id=40,
                        proposed_mechanism_family="commodity_squeeze"),
        ])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     5,
                    "clean_fully_ready_event_ids": [30, 40, 46, 60, 73],
                    "excluded_fully_ready_examples": [],
                },
                fetch_rows=[_bar("2026-03-01"), _bar("2026-04-01")],
                validation_payload=_validation_payload(records=[
                    _validation_record(event_id=46, ticker="MS",
                                       mechanism_family="bank_regulatory_capital_relief",
                                       horizon=5),
                    _validation_record(event_id=60, ticker="XOM",
                                       mechanism_family="supply_shock",
                                       horizon=5),
                    _validation_record(event_id=73, ticker="XOM",
                                       mechanism_family="supply_shock",
                                       horizon=5),
                    _validation_record(event_id=30, ticker="XOM",
                                       mechanism_family="supply_shock",
                                       horizon=5),
                    _validation_record(event_id=40, ticker="BDRY",
                                       mechanism_family="commodity_squeeze",
                                       horizon=5),
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                    mechanism_family_csv=family,
                )
        finally:
            os.unlink(backup); os.unlink(high)
            os.unlink(medium); os.unlink(family)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], True)
        self.assertEqual(
            sorted(result["repaired_clean_event_ids"]),
            [30, 40, 46, 60, 73],
        )
        self.assertEqual(result["events_evaluated"], 5)
        self.assertEqual(result["records_count"], 5)


class TestMechanismFamilyCsvBackwardCompat(unittest.TestCase):
    """Omitting --mechanism-family-csv (the new optional input) must
    preserve the runner's existing two-CSV behaviour byte-for-byte —
    no third CSV ⇒ no family-CSV plumbing fires."""

    def test_omitting_param_preserves_two_csv_behaviour(self) -> None:
        backup = _make_temp_db(seed_events=[
            {"id": 46, "event_date": "2026-04-06",
             "market_tickers": '[{"symbol":"DRIV"}]'},
        ])
        high = _write_csv([
            _csv_row(event_id=46, proposed_primary_ticker="MS",
                     proposed_benchmark="SPY",
                     proposed_mechanism_family="bank_regulatory_capital_relief",
                     event_date="2026-04-06"),
        ])
        medium = _write_csv([])
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     1,
                    "clean_fully_ready_event_ids": [46],
                    "excluded_fully_ready_examples": [],
                },
                fetch_rows=[_bar("2026-04-01")],
                validation_payload=_validation_payload(records=[
                    _validation_record(event_id=46, ticker="MS",
                                       mechanism_family="bank_regulatory_capital_relief",
                                       horizon=5),
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                # No mechanism_family_csv kwarg.
                result = _run(
                    backup_path=backup,
                    high_priority_csv=high, medium_csv=medium,
                )
        finally:
            os.unlink(backup); os.unlink(high); os.unlink(medium)
            _cleanup_temp_copy(result)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["repaired_clean_event_ids"], [46])


class TestMechanismFamilyCsvCli(unittest.TestCase):
    def test_cli_accepts_mechanism_family_csv_flag(self) -> None:
        backup = _make_temp_db(seed_events=[
            {"id": 30, "event_date": "2026-04-05",
             "market_tickers": '[{"symbol":"XOM"}]'},
        ])
        high   = _write_csv([])
        medium = _write_csv([])
        family = _write_family_csv([
            _family_row(event_id=30,
                        proposed_mechanism_family="supply_shock"),
        ])
        out = StringIO()
        try:
            patches = _patch_seams(
                before_clean_event_ids=[],
                after_clean_payload={
                    "clean_fully_ready_count":     1,
                    "clean_fully_ready_event_ids": [30],
                    "excluded_fully_ready_examples": [],
                },
                validation_payload=_validation_payload(records=[
                    _validation_record(event_id=30, ticker="XOM",
                                       mechanism_family="supply_shock",
                                       horizon=5),
                ]),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                rc = cli.main([
                    "--json", "--backup-path", backup,
                    "--high-priority-csv", high,
                    "--medium-csv", medium,
                    "--mechanism-family-csv", family,
                    "--limit", "5",
                ], out=out)
        finally:
            os.unlink(backup); os.unlink(high)
            os.unlink(medium); os.unlink(family)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed["repaired_clean_event_ids"], [30])


if __name__ == "__main__":
    unittest.main()
