"""Tests for ``scripts/archive_stat_validation_run.py``.

The runner is a read-only archive walker that runs the
``stats.event_study → bootstrap_ar_ci → p_value_from_sar → bh_adjust →
make_stat_validation_record`` pipeline end-to-end over events the
:mod:`scripts.stat_validation_readiness_report` predicate marks as
``fully_ready``.  These tests pin:

  * the read-only contract (no DB writes, no provider/yfinance/LLM);
  * the readiness gating (events that fail any readiness check are
    not evaluated, even when other readiness columns succeed);
  * the canonical output envelope (``ok``, ``events_evaluated``,
    ``records_count``, ``significant_count``, ``by_horizon``,
    ``by_mechanism_family``, ``errors``, ``examples``);
  * the per-example schema (``event_id``, ``headline``, ``ticker``,
    ``horizon``, ``abnormal_return``, ``sar``, ``ci_low``, ``ci_high``,
    ``p_value``, ``fdr_q``, ``interpretation``);
  * the conservative-language constraint (no "proof", "alpha generated"
    or causal language anywhere in the surfaced text);
  * a deterministic significance signal: a strong fixed shock injected
    into a synthetic asset series produces at least one
    ``statistically_significant`` record over a cohort.

No live network, no LLM, no yfinance, no FastAPI app surface — every
test runs against a per-test temp SQLite file that imitates the
events + price_cache schema exactly.
"""
from __future__ import annotations

import io
import json
import os
import random
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date as _date, timedelta as _timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import archive_stat_validation_run  # noqa: E402


# ---------------------------------------------------------------------------
# Test fixtures — a per-test temp SQLite file with the events +
# price_cache schema and a deterministic synthetic-prices helper.
# ---------------------------------------------------------------------------


_BENCHMARK_TICKER = "SPY"


def _tmp_db_path() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"test_archive_stat_validation_run_{uuid.uuid4().hex}.db",
    )


def _init_schema(path: str) -> None:
    """Create an events + price_cache schema that mirrors db.py's
    minimum surface.  Only the columns the runner reads are populated;
    everything else is left at SQLite defaults.
    """
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE events ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  headline TEXT,"
            "  event_date TEXT,"
            "  market_tickers TEXT,"
            "  mechanism_family TEXT"
            ")"
        )
        conn.execute(
            "CREATE TABLE price_cache ("
            "  ticker TEXT NOT NULL,"
            "  date TEXT NOT NULL,"
            "  close REAL,"
            "  volume REAL,"
            "  auto_adjust INTEGER NOT NULL,"
            "  fetched_at TEXT NOT NULL,"
            "  PRIMARY KEY (ticker, date, auto_adjust)"
            ")"
        )


def _business_days_back(anchor: _date, n: int) -> list[_date]:
    """Return ``n`` business days strictly before ``anchor``, ascending."""
    out: list[_date] = []
    cursor = anchor
    while len(out) < n:
        cursor = cursor - _timedelta(days=1)
        if cursor.weekday() < 5:
            out.append(cursor)
    return list(reversed(out))


def _business_days_forward(anchor: _date, n: int) -> list[_date]:
    """Return ``n`` business days starting from ``anchor`` (inclusive),
    ascending.  ``anchor`` must itself be a business day; if it isn't,
    the first weekday on or after ``anchor`` is used."""
    out: list[_date] = []
    cursor = anchor
    while cursor.weekday() >= 5:
        cursor = cursor + _timedelta(days=1)
    while len(out) < n:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor = cursor + _timedelta(days=1)
    return out


def _seed_event(
    path: str,
    *,
    headline: str,
    event_date: _date,
    primary_ticker: str,
    mechanism_family: str | None = None,
) -> int:
    market_tickers = json.dumps([{"symbol": primary_ticker, "role": "beneficiary"}])
    with sqlite3.connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO events "
            "(headline, event_date, market_tickers, mechanism_family) "
            "VALUES (?, ?, ?, ?)",
            (headline, event_date.isoformat(), market_tickers, mechanism_family),
        )
        return int(cursor.lastrowid)


def _seed_event_raw(
    path: str,
    *,
    headline: str,
    event_date: str | None,
    market_tickers: str | None,
    mechanism_family: str | None = None,
) -> int:
    """Seed an event with arbitrary raw values for the unhappy paths."""
    with sqlite3.connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO events "
            "(headline, event_date, market_tickers, mechanism_family) "
            "VALUES (?, ?, ?, ?)",
            (headline, event_date, market_tickers, mechanism_family),
        )
        return int(cursor.lastrowid)


def _write_price_rows(
    path: str,
    *,
    ticker: str,
    series: list[tuple[_date, float]],
    auto_adjust: int = 1,
) -> None:
    rows = [
        (ticker, d.isoformat(), close, 0.0, auto_adjust, "2026-05-09T00:00:00")
        for d, close in series
    ]
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO price_cache "
            "(ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )


def _synthetic_pair(
    *,
    n_pre: int,
    n_post: int,
    event_shock: float,
    seed: int,
    drift: float = 0.0001,
    market_vol: float = 0.010,
    idio_vol: float = 0.005,
    return_floor: float = -0.40,
) -> tuple[list[float], list[float]]:
    """Return aligned asset / benchmark close-price arrays of length
    ``n_pre + 1 + n_post`` with the event shock applied on the bar
    immediately AFTER the event close (``index = n_pre + 1``)."""
    rng = random.Random(seed)
    asset = [100.0]
    bench = [100.0]
    total = n_pre + 1 + n_post
    for t in range(1, total):
        market = rng.gauss(0.0, market_vol)
        idio_a = rng.gauss(0.0, idio_vol)
        idio_b = rng.gauss(0.0, idio_vol)
        ret_asset = drift + market + idio_a
        ret_bench = drift + market + idio_b
        if t == n_pre + 1:
            ret_asset += event_shock
        if ret_asset < return_floor:
            ret_asset = return_floor
        if ret_bench < return_floor:
            ret_bench = return_floor
        asset.append(asset[-1] * (1.0 + ret_asset))
        bench.append(bench[-1] * (1.0 + ret_bench))
    return asset, bench


def _seed_fully_ready_event(
    path: str,
    *,
    headline: str,
    event_date: _date,
    primary_ticker: str,
    mechanism_family: str | None = None,
    event_shock: float = 0.0,
    seed: int = 1,
    n_pre: int = 80,
    n_post: int = 30,
) -> int:
    """Seed an event plus enough cache coverage to clear every readiness
    check.  ``n_pre`` is the count of estimation-window business days
    written before ``event_date``; ``n_post`` is the count of
    horizon-window business days written from ``event_date`` forward
    (inclusive of the event-day close)."""
    pre_days  = _business_days_back(event_date, n_pre)
    post_days = _business_days_forward(event_date, n_post)
    all_days  = pre_days + post_days

    asset_prices, bench_prices = _synthetic_pair(
        n_pre=n_pre, n_post=n_post - 1,  # event-day occupies n_pre slot
        event_shock=event_shock,
        seed=seed,
    )
    assert len(all_days) == len(asset_prices) == len(bench_prices), (
        f"alignment mismatch: {len(all_days)} dates, "
        f"{len(asset_prices)} asset prices, {len(bench_prices)} bench prices"
    )

    asset_series = list(zip(all_days, asset_prices))
    bench_series = list(zip(all_days, bench_prices))

    _write_price_rows(path, ticker=primary_ticker, series=asset_series)
    _write_price_rows(path, ticker=_BENCHMARK_TICKER, series=bench_series)

    return _seed_event(
        path,
        headline=headline,
        event_date=event_date,
        primary_ticker=primary_ticker,
        mechanism_family=mechanism_family,
    )


def _snapshot_db(path: str) -> dict[str, list[tuple]]:
    with sqlite3.connect(path) as conn:
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        snapshot: dict[str, list[tuple]] = {}
        for table in tables:
            rows = conn.execute(
                f"SELECT * FROM \"{table}\" ORDER BY rowid"
            ).fetchall()
            snapshot[table] = list(rows)
        return snapshot


# Far enough back that all the synthetic business-day shifts stay in
# the past (so the readiness predicate's "forward cache" check, which
# counts business days forward from event_date, has a chance to be
# satisfied by the seeded rows).
_FIXED_EVENT_DATE = _date(2026, 1, 15)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


class TestModuleSurface(unittest.TestCase):

    def test_module_exposes_main(self) -> None:
        self.assertTrue(callable(archive_stat_validation_run.main))

    def test_module_exposes_runner_function(self) -> None:
        self.assertTrue(
            callable(archive_stat_validation_run.run_archive_stat_validation),
            "run_archive_stat_validation must be the importable seam tests "
            "and the smoke runner can patch",
        )


# ---------------------------------------------------------------------------
# Empty-archive degraded path
# ---------------------------------------------------------------------------


class TestEmptyArchive(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_empty_db_returns_ok_true(self) -> None:
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertTrue(payload["ok"])

    def test_empty_db_returns_zero_counts(self) -> None:
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(payload["events_evaluated"], 0)
        self.assertEqual(payload["records_count"], 0)
        self.assertEqual(payload["significant_count"], 0)

    def test_empty_db_returns_empty_examples_and_errors(self) -> None:
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(payload["examples"], [])
        self.assertEqual(payload["errors"], [])

    def test_empty_db_by_horizon_keyset(self) -> None:
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(set(payload["by_horizon"].keys()), {"1", "5", "20"})


# ---------------------------------------------------------------------------
# Readiness gating — events failing any readiness check must not be
# evaluated.  Each test seeds one event missing exactly one readiness
# column, and asserts the runner reports zero evaluations.
# ---------------------------------------------------------------------------


class TestReadinessGating(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_event_without_event_date_not_evaluated(self) -> None:
        _seed_event_raw(
            self.path,
            headline="No event_date",
            event_date=None,
            market_tickers=json.dumps([{"symbol": "AAPL"}]),
        )
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(payload["events_evaluated"], 0)

    def test_event_without_market_tickers_not_evaluated(self) -> None:
        _seed_event_raw(
            self.path,
            headline="No tickers",
            event_date="2026-01-15",
            market_tickers=None,
        )
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(payload["events_evaluated"], 0)

    def test_event_with_no_cache_coverage_not_evaluated(self) -> None:
        _seed_event(
            self.path,
            headline="Ticker but no cache",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
        )
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(payload["events_evaluated"], 0)


# ---------------------------------------------------------------------------
# Fully-ready evaluation — pin shape, counts, and per-record fields.
# ---------------------------------------------------------------------------


_REQUIRED_EXAMPLE_FIELDS = (
    "event_id",
    "headline",
    "ticker",
    "horizon",
    "abnormal_return",
    "sar",
    "ci_low",
    "ci_high",
    "p_value",
    "fdr_q",
    "interpretation",
)


class TestFullyReadyEvaluation(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)
        self.event_id = _seed_fully_ready_event(
            self.path,
            headline="Test fully-ready event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            mechanism_family="policy_constraint",
            event_shock=0.0,  # noise only
            seed=11,
        )

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_fully_ready_event_evaluated_once(self) -> None:
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        self.assertEqual(payload["events_evaluated"], 1, payload.get("errors"))

    def test_records_count_equals_events_times_horizons(self) -> None:
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        # Default horizons are (1, 5, 20) — three records per event.
        self.assertEqual(payload["records_count"], 3, payload.get("errors"))

    def test_examples_carry_all_required_fields(self) -> None:
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        self.assertGreaterEqual(len(payload["examples"]), 1)
        for example in payload["examples"]:
            for field in _REQUIRED_EXAMPLE_FIELDS:
                self.assertIn(field, example, f"missing field {field!r}: {example!r}")

    def test_examples_carry_event_metadata(self) -> None:
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        first = payload["examples"][0]
        self.assertEqual(first["event_id"], self.event_id)
        self.assertEqual(first["ticker"], "AAPL")
        self.assertEqual(first["headline"], "Test fully-ready event")

    def test_horizon_keys_returned_as_strings_in_by_horizon(self) -> None:
        # JSON object keys must be strings; the by_horizon block is
        # part of the JSON envelope, so its keys must be string-typed.
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        for key in payload["by_horizon"].keys():
            self.assertIsInstance(key, str)

    def test_by_horizon_record_counts_sum_to_total(self) -> None:
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        total = sum(
            block["records_count"] for block in payload["by_horizon"].values()
        )
        self.assertEqual(total, payload["records_count"])

    def test_by_horizon_significant_counts_sum_to_total(self) -> None:
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        total = sum(
            block["significant_count"]
            for block in payload["by_horizon"].values()
        )
        self.assertEqual(total, payload["significant_count"])

    def test_examples_limit_caps_emitted_records(self) -> None:
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=2,
        )
        # records_count counts evaluated records (= 3), but examples
        # are capped at limit.
        self.assertEqual(payload["records_count"], 3)
        self.assertLessEqual(len(payload["examples"]), 2)


# ---------------------------------------------------------------------------
# Significance signal — under a strong fixed shock, at least one
# record must be flagged statistically_significant after BH adjustment.
# ---------------------------------------------------------------------------


class TestSignificanceSignal(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_strong_shock_yields_at_least_one_significant_record(self) -> None:
        # A strong +6% asset-only shock on the post-event bar produces
        # an SAR far enough out in the tail that p_value_from_sar
        # returns a tiny p, BH adjustment leaves it below the default
        # alpha=0.05, and the record's statistically_significant flag
        # flips to True.
        _seed_fully_ready_event(
            self.path,
            headline="Strong shock event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.06,
            seed=23,
        )
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        self.assertGreaterEqual(
            payload["significant_count"], 1,
            f"expected at least one significant record under +6% shock; "
            f"got {payload['significant_count']}, errors={payload['errors']!r}",
        )


# ---------------------------------------------------------------------------
# Mechanism-family aggregation — emitted only when at least one
# evaluated event carries a non-empty ``mechanism_family``.
# ---------------------------------------------------------------------------


class TestMechanismFamilyAggregation(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_by_mechanism_family_present_when_event_has_family(self) -> None:
        _seed_fully_ready_event(
            self.path,
            headline="Family event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            mechanism_family="policy_constraint",
            event_shock=0.0,
            seed=31,
        )
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        self.assertIn("by_mechanism_family", payload)
        self.assertIn("policy_constraint", payload["by_mechanism_family"])

    def test_by_mechanism_family_block_carries_required_keys(self) -> None:
        _seed_fully_ready_event(
            self.path,
            headline="Family event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            mechanism_family="policy_constraint",
            event_shock=0.0,
            seed=31,
        )
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        block = payload["by_mechanism_family"]["policy_constraint"]
        for key in ("events_evaluated", "records_count", "significant_count"):
            self.assertIn(key, block, f"missing key {key!r}: {block!r}")

    def test_by_mechanism_family_omitted_when_no_event_has_family(self) -> None:
        _seed_fully_ready_event(
            self.path,
            headline="No-family event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            mechanism_family=None,
            event_shock=0.0,
            seed=37,
        )
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        # Either omitted entirely or an explicit empty dict — both
        # signal "no per-family aggregation available".  Emitting a
        # populated block here would be a regression.
        block = payload.get("by_mechanism_family", {})
        self.assertEqual(block, {})


# ---------------------------------------------------------------------------
# Conservative-language constraint — the report must not use
# alpha-extraction or proof-of-causality phrasing anywhere in the
# operator-facing text or the per-example interpretation labels.
# ---------------------------------------------------------------------------


_FORBIDDEN_PHRASES = (
    "alpha generated",
    "alpha-generated",
    "generates alpha",
    "proof of",
    "proves that",
    "proven",
    "guaranteed",
    "causal proof",
)


class TestConservativeLanguage(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_recommended_next_action_avoids_forbidden_phrases(self) -> None:
        _seed_fully_ready_event(
            self.path,
            headline="Conservative phrasing event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.06,
            seed=41,
        )
        payload = archive_stat_validation_run.run_archive_stat_validation(
            db_path=self.path, limit=10,
        )
        action = payload.get("recommended_next_action", "") or ""
        lowered = action.lower()
        for phrase in _FORBIDDEN_PHRASES:
            self.assertNotIn(
                phrase, lowered,
                f"recommended_next_action must not use forbidden phrasing "
                f"{phrase!r}; got {action!r}",
            )

    def test_render_text_avoids_forbidden_phrases(self) -> None:
        _seed_fully_ready_event(
            self.path,
            headline="Phrase scan target",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.06,
            seed=43,
        )
        out = io.StringIO()
        archive_stat_validation_run.main(["--limit", "5"], out=out)
        rendered = out.getvalue().lower()
        for phrase in _FORBIDDEN_PHRASES:
            self.assertNotIn(
                phrase, rendered,
                f"text rendering must not use forbidden phrasing "
                f"{phrase!r}",
            )


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)
        _seed_fully_ready_event(
            self.path,
            headline="CLI smoke event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.0,
            seed=53,
        )

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_main_json_emits_valid_payload(self) -> None:
        out = io.StringIO()
        code = archive_stat_validation_run.main(
            ["--json", "--limit", "5", "--db-path", self.path], out=out,
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertIn("events_evaluated", payload)
        self.assertIn("records_count", payload)
        self.assertIn("by_horizon", payload)
        self.assertIn("examples", payload)

    def test_main_text_runs_without_error(self) -> None:
        out = io.StringIO()
        code = archive_stat_validation_run.main(
            ["--limit", "5", "--db-path", self.path], out=out,
        )
        self.assertEqual(code, 0)
        self.assertIn("events_evaluated", out.getvalue())


# ---------------------------------------------------------------------------
# Read-only contract — the runner must never mutate the archive.
# ---------------------------------------------------------------------------


class TestReadOnlyContract(unittest.TestCase):

    def test_runner_does_not_mutate_db(self) -> None:
        path = _tmp_db_path()
        try:
            _init_schema(path)
            _seed_fully_ready_event(
                path,
                headline="No-mutation event",
                event_date=_FIXED_EVENT_DATE,
                primary_ticker="AAPL",
                mechanism_family="policy_constraint",
                event_shock=0.04,
                seed=61,
            )
            before = _snapshot_db(path)
            archive_stat_validation_run.run_archive_stat_validation(
                db_path=path, limit=10,
            )
            after = _snapshot_db(path)
            self.assertEqual(
                before, after,
                "runner must be strictly read-only; archive contents "
                "must be byte-identical before and after the run",
            )
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
