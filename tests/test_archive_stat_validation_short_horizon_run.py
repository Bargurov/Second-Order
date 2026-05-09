"""Tests for ``scripts/archive_stat_validation_short_horizon_run.py``.

The short-horizon runner is a sibling of
:mod:`scripts.archive_stat_validation_run` restricted to the 1d/5d
horizon pair.  These tests pin:

  * the read-only contract (no DB writes, no provider/yfinance/LLM);
  * horizons are EXACTLY ``(1, 5)`` — no 20d compute path;
  * the readiness gate matches the
    :mod:`scripts.stat_validation_short_horizon_readiness_report`
    relaxed predicate, NOT the full-readiness predicate — events with
    1d/5d cache but no 20d cache must be evaluated;
  * the canonical output envelope:
    ``ok``, ``events_evaluated``, ``records_count``,
    ``significant_count``, ``by_horizon``, ``by_mechanism_family``,
    ``examples``, ``errors``, ``recommended_next_action``;
  * the per-example schema:
    ``event_id``, ``headline``, ``primary_ticker``, ``benchmark``,
    ``horizon``, ``abnormal_return``, ``sar``, ``ci_low``, ``ci_high``,
    ``p_value``, ``fdr_q``, ``interpretation``;
  * the conservative-language constraint:  banned phrases include
    ``alpha generated``, ``alpha-generated``, ``generates alpha``,
    ``claim alpha``, ``alpha capture``, ``proof of``, ``proves that``,
    ``proven``, ``guaranteed``, ``causal proof``;
  * null / negative results are NOT hidden — examples remain non-empty
    even when ``significant_count == 0``;
  * a deterministic significance signal: a strong fixed shock injected
    on the synthetic asset series produces at least one
    ``statistically_significant`` record over a 1d/5d cohort.

No live network, no LLM, no yfinance, no FastAPI — every test runs
against a per-test temp SQLite file imitating the events + price_cache
schema.
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

from scripts import archive_stat_validation_short_horizon_run as runner  # noqa: E402
from scripts import archive_stat_validation_run as full_runner  # noqa: E402


# ---------------------------------------------------------------------------
# Test fixtures — per-test temp SQLite + deterministic synthetic prices.
# ---------------------------------------------------------------------------


_BENCHMARK_TICKER = "SPY"
_FIXED_EVENT_DATE = _date(2026, 1, 15)


def _tmp_db_path() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"test_archive_stat_validation_short_horizon_run_{uuid.uuid4().hex}.db",
    )


def _init_schema(path: str) -> None:
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
    out: list[_date] = []
    cursor = anchor
    while len(out) < n:
        cursor = cursor - _timedelta(days=1)
        if cursor.weekday() < 5:
            out.append(cursor)
    return list(reversed(out))


def _business_days_forward(anchor: _date, n: int) -> list[_date]:
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


def _seed_event_with_coverage(
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
    """Seed an event with ``n_pre`` business-day pre-event closes and
    ``n_post`` post-event business-day closes (inclusive of event day).

    ``n_post`` controls horizon coverage:
      - n_post >= 21: full readiness (covers 1d, 5d, AND 20d horizons)
      - 6 <= n_post < 21: short-horizon only (1d/5d ready, 20d not)
      - n_post < 6: not even short-horizon ready
    """
    pre_days  = _business_days_back(event_date, n_pre)
    post_days = _business_days_forward(event_date, n_post)
    all_days  = pre_days + post_days

    asset_prices, bench_prices = _synthetic_pair(
        n_pre=n_pre, n_post=n_post - 1,
        event_shock=event_shock,
        seed=seed,
    )
    assert len(all_days) == len(asset_prices) == len(bench_prices)

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


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


class TestModuleSurface(unittest.TestCase):

    def test_module_exposes_main(self) -> None:
        self.assertTrue(callable(runner.main))

    def test_module_exposes_runner_function(self) -> None:
        # Tests + the --json smoke runner depend on a top-level callable.
        self.assertTrue(
            callable(getattr(runner, "run_archive_short_horizon_stat_validation",
                             None)),
            "run_archive_short_horizon_stat_validation must exist as the "
            "importable seam for tests + smoke driver",
        )


# ---------------------------------------------------------------------------
# Empty-archive degraded path — pin the by_horizon keyset.
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
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertTrue(payload["ok"])

    def test_empty_db_returns_zero_counts(self) -> None:
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(payload["events_evaluated"], 0)
        self.assertEqual(payload["records_count"], 0)
        self.assertEqual(payload["significant_count"], 0)

    def test_empty_db_returns_empty_examples_and_errors(self) -> None:
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(payload["examples"], [])
        self.assertEqual(payload["errors"], [])

    def test_by_horizon_keyset_is_strictly_one_and_five(self) -> None:
        # Critical defense: the runner must NEVER expose a 20d horizon
        # block.  Pin the keyset literally so any drift toward the full
        # runner's horizons breaks the test.
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(set(payload["by_horizon"].keys()), {"1", "5"})


# ---------------------------------------------------------------------------
# Output envelope — pin every spec-required top-level key.
# ---------------------------------------------------------------------------


_REQUIRED_TOP_LEVEL_KEYS = (
    "ok",
    "events_evaluated",
    "records_count",
    "significant_count",
    "by_horizon",
    "by_mechanism_family",
    "examples",
    "errors",
    "recommended_next_action",
)


class TestOutputEnvelope(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_payload_carries_all_spec_required_keys(self) -> None:
        _seed_event_with_coverage(
            self.path,
            headline="Envelope event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.0,
            seed=11,
            n_post=30,
        )
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=5,
        )
        for key in _REQUIRED_TOP_LEVEL_KEYS:
            self.assertIn(key, payload, f"missing top-level key {key!r}")


# ---------------------------------------------------------------------------
# Readiness gating — events failing readiness checks must be skipped.
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
        payload = runner.run_archive_short_horizon_stat_validation(
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
        payload = runner.run_archive_short_horizon_stat_validation(
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
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(payload["events_evaluated"], 0)


# ---------------------------------------------------------------------------
# Differentiator — short-horizon ready BUT NOT full-horizon ready.
#
# This is the critical test that proves the runner uses the relaxed
# predicate from the short-horizon readiness report, not a copy of the
# full-readiness predicate.  An event with 1d/5d cache but missing 20d
# cache MUST be evaluated by this runner and skipped by the full runner.
# ---------------------------------------------------------------------------


class TestShortHorizonOnlyReadiness(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)
        # n_post=10 covers 1d + 5d horizons but is short of 20d.
        self.event_id = _seed_event_with_coverage(
            self.path,
            headline="Short-horizon-only event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.0,
            seed=17,
            n_post=10,
        )

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_short_horizon_runner_evaluates_event(self) -> None:
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(
            payload["events_evaluated"], 1,
            f"short-horizon runner must evaluate the n_post=10 event "
            f"that the full predicate skips; errors={payload.get('errors')!r}",
        )

    def test_full_runner_skips_event(self) -> None:
        payload = full_runner.run_archive_stat_validation(
            db_path=self.path, limit=5,
        )
        self.assertEqual(
            payload["events_evaluated"], 0,
            f"full runner should skip n_post=10 events (no 20d cache); "
            f"got {payload['events_evaluated']} evaluated; "
            f"errors={payload.get('errors')!r}",
        )

    def test_short_runner_yields_two_records_per_event(self) -> None:
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=5,
        )
        # 2 horizons × 1 event = 2 records.
        self.assertEqual(payload["records_count"], 2,
                         f"errors={payload.get('errors')!r}")


# ---------------------------------------------------------------------------
# Per-example schema — primary_ticker + benchmark required by spec.
# ---------------------------------------------------------------------------


_REQUIRED_EXAMPLE_FIELDS = (
    "event_id",
    "headline",
    "primary_ticker",
    "benchmark",
    "horizon",
    "abnormal_return",
    "sar",
    "ci_low",
    "ci_high",
    "p_value",
    "fdr_q",
    "interpretation",
)


class TestExampleSchema(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)
        self.event_id = _seed_event_with_coverage(
            self.path,
            headline="Schema test event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            mechanism_family="policy_constraint",
            event_shock=0.0,
            seed=23,
            n_post=30,
        )

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_examples_carry_all_required_fields(self) -> None:
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        self.assertGreaterEqual(len(payload["examples"]), 1)
        for example in payload["examples"]:
            for field in _REQUIRED_EXAMPLE_FIELDS:
                self.assertIn(field, example,
                              f"missing field {field!r}: {example!r}")

    def test_examples_use_primary_ticker_field_name(self) -> None:
        # Spec uses ``primary_ticker`` (NOT ``ticker``).  Pin literally.
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        first = payload["examples"][0]
        self.assertEqual(first["primary_ticker"], "AAPL")
        self.assertEqual(first["event_id"], self.event_id)
        self.assertEqual(first["headline"], "Schema test event")

    def test_examples_carry_spy_benchmark(self) -> None:
        # SPY is the only benchmark the runner uses; every example must
        # echo it explicitly so downstream consumers don't have to
        # infer it.
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        self.assertGreaterEqual(len(payload["examples"]), 1)
        for example in payload["examples"]:
            self.assertEqual(example["benchmark"], "SPY",
                             f"example benchmark != SPY: {example!r}")

    def test_examples_only_carry_horizon_one_or_five(self) -> None:
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        for example in payload["examples"]:
            self.assertIn(example["horizon"], (1, 5),
                          f"example horizon outside (1, 5): {example!r}")


# ---------------------------------------------------------------------------
# Aggregates — by_horizon counts sum to total; records_count = events × 2.
# ---------------------------------------------------------------------------


class TestAggregates(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)
        _seed_event_with_coverage(
            self.path,
            headline="Aggregate event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.0,
            seed=29,
            n_post=30,
        )

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_records_count_equals_events_times_two(self) -> None:
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        # Two horizons × one event = two records.
        self.assertEqual(payload["records_count"], 2,
                         f"errors={payload.get('errors')!r}")

    def test_by_horizon_records_sum_to_total(self) -> None:
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        total = sum(
            block["records_count"] for block in payload["by_horizon"].values()
        )
        self.assertEqual(total, payload["records_count"])

    def test_by_horizon_significant_counts_sum_to_total(self) -> None:
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        total = sum(
            block["significant_count"]
            for block in payload["by_horizon"].values()
        )
        self.assertEqual(total, payload["significant_count"])

    def test_horizon_keys_are_strings(self) -> None:
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        for key in payload["by_horizon"].keys():
            self.assertIsInstance(key, str)


# ---------------------------------------------------------------------------
# Significance signal — strong shock yields at least one significant
# record under the 1d/5d cohort.
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
        _seed_event_with_coverage(
            self.path,
            headline="Strong shock short-horizon event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.06,
            seed=31,
            n_post=30,
        )
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        self.assertGreaterEqual(
            payload["significant_count"], 1,
            f"expected at least one significant record under +6% shock; "
            f"got {payload['significant_count']}, errors={payload['errors']!r}",
        )


# ---------------------------------------------------------------------------
# Null / negative results not hidden — under no shock, examples must
# remain non-empty so operators can inspect insignificant rows too.
# ---------------------------------------------------------------------------


class TestNullResultsNotHidden(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_examples_non_empty_under_zero_shock(self) -> None:
        _seed_event_with_coverage(
            self.path,
            headline="No-signal event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.0,
            seed=37,
            n_post=30,
        )
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        # records_count > 0 but significant_count is likely 0 — examples
        # must still surface the insignificant rows.
        self.assertGreater(payload["records_count"], 0,
                           f"errors={payload.get('errors')!r}")
        self.assertGreater(
            len(payload["examples"]), 0,
            "examples must not be filtered to significant-only rows",
        )


# ---------------------------------------------------------------------------
# Mechanism-family aggregation — present when at least one evaluated
# event carries a non-empty mechanism_family.
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

    def test_block_present_when_event_has_family(self) -> None:
        _seed_event_with_coverage(
            self.path,
            headline="Family event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            mechanism_family="policy_constraint",
            event_shock=0.0,
            seed=41,
            n_post=30,
        )
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        self.assertIn("by_mechanism_family", payload)
        self.assertIn("policy_constraint", payload["by_mechanism_family"])
        block = payload["by_mechanism_family"]["policy_constraint"]
        for key in ("events_evaluated", "records_count", "significant_count"):
            self.assertIn(key, block, f"missing key {key!r}: {block!r}")

    def test_block_empty_when_no_event_has_family(self) -> None:
        _seed_event_with_coverage(
            self.path,
            headline="No-family event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            mechanism_family=None,
            event_shock=0.0,
            seed=43,
            n_post=30,
        )
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        block = payload.get("by_mechanism_family", {})
        self.assertEqual(block, {})


# ---------------------------------------------------------------------------
# Conservative-language constraint.
# ---------------------------------------------------------------------------


_FORBIDDEN_PHRASES = (
    "alpha generated",
    "alpha-generated",
    "generates alpha",
    "claim alpha",
    "alpha capture",
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

    def test_recommended_action_avoids_forbidden_phrases(self) -> None:
        _seed_event_with_coverage(
            self.path,
            headline="Conservative phrasing event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.06,
            seed=47,
            n_post=30,
        )
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        action = payload.get("recommended_next_action", "") or ""
        lowered = action.lower()
        for phrase in _FORBIDDEN_PHRASES:
            self.assertNotIn(
                phrase, lowered,
                f"recommended_next_action used forbidden phrasing "
                f"{phrase!r}; got {action!r}",
            )

    def test_render_text_avoids_forbidden_phrases(self) -> None:
        _seed_event_with_coverage(
            self.path,
            headline="Phrase scan event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.06,
            seed=53,
            n_post=30,
        )
        out = io.StringIO()
        runner.main(
            ["--limit", "5", "--db-path", self.path], out=out,
        )
        rendered = out.getvalue().lower()
        for phrase in _FORBIDDEN_PHRASES:
            self.assertNotIn(
                phrase, rendered,
                f"text rendering used forbidden phrasing {phrase!r}",
            )

    def test_recommended_action_mentions_short_horizon_evidence(self) -> None:
        # Per spec, conservative wording should call out
        # "short-horizon statistical evidence" + "candidate" + "not proof".
        _seed_event_with_coverage(
            self.path,
            headline="Wording event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.06,
            seed=59,
            n_post=30,
        )
        payload = runner.run_archive_short_horizon_stat_validation(
            db_path=self.path, limit=10,
        )
        action = (payload.get("recommended_next_action") or "").lower()
        self.assertIn("short-horizon", action)
        self.assertIn("candidate", action)
        self.assertIn("not proof", action)


# ---------------------------------------------------------------------------
# CLI surface — --json, --limit, --db-path.
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):

    def setUp(self) -> None:
        self.path = _tmp_db_path()
        _init_schema(self.path)
        _seed_event_with_coverage(
            self.path,
            headline="CLI smoke event",
            event_date=_FIXED_EVENT_DATE,
            primary_ticker="AAPL",
            event_shock=0.0,
            seed=61,
            n_post=30,
        )

    def tearDown(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_main_json_emits_valid_payload(self) -> None:
        out = io.StringIO()
        code = runner.main(
            ["--json", "--limit", "5", "--db-path", self.path], out=out,
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertIn("events_evaluated", payload)
        self.assertIn("records_count", payload)
        self.assertIn("by_horizon", payload)
        self.assertIn("examples", payload)
        # JSON top-level keyset must include exactly the spec-required
        # surface; horizons are str-keyed at "1" / "5" only.
        self.assertEqual(set(payload["by_horizon"].keys()), {"1", "5"})

    def test_main_text_runs_without_error(self) -> None:
        out = io.StringIO()
        code = runner.main(
            ["--limit", "5", "--db-path", self.path], out=out,
        )
        self.assertEqual(code, 0)
        self.assertIn("events_evaluated", out.getvalue())


# ---------------------------------------------------------------------------
# Read-only contract — runner must never mutate the archive.
# ---------------------------------------------------------------------------


class TestReadOnlyContract(unittest.TestCase):

    def test_runner_does_not_mutate_db(self) -> None:
        path = _tmp_db_path()
        try:
            _init_schema(path)
            _seed_event_with_coverage(
                path,
                headline="No-mutation event",
                event_date=_FIXED_EVENT_DATE,
                primary_ticker="AAPL",
                mechanism_family="policy_constraint",
                event_shock=0.04,
                seed=67,
                n_post=30,
            )
            before = _snapshot_db(path)
            runner.run_archive_short_horizon_stat_validation(
                db_path=path, limit=10,
            )
            after = _snapshot_db(path)
            self.assertEqual(
                before, after,
                "runner must be strictly read-only; archive contents must "
                "be byte-identical before and after the run",
            )
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
