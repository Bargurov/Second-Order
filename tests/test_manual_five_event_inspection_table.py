"""Tests for ``scripts/manual_five_event_inspection_table.py``.

The inspection table consumes the read-only output of
:mod:`scripts.manual_five_event_validation_smoke` and re-shapes it
into an operator decision table.  It does not re-run the
event-study, it does not merge into any cohort, it does not write
to disk by itself, and it does not claim validation or proof.

Pinned contract:

* Envelope top keys: ``ok``, ``rows``, ``summary``, ``warnings``,
  ``errors``.
* Each row carries: ``candidate_id``, ``event_date``, ``headline``,
  ``mechanism_family``, ``primary_ticker``, ``benchmark_ticker``,
  ``records_count``, ``raw_p_count``, ``fdr_count``,
  ``horizons_available``, ``missing_coverage_note``,
  ``suggested_operator_decision``, ``decision_reason``.
* ``suggested_operator_decision`` is one of:

  - ``coverage_blocked``           (no records produced)
  - ``inspect_do_not_merge``       (records but no raw-p / FDR signal)
  - ``inspect_candidate``          (raw-p or FDR-significant horizons)
  - ``revise_ticker_or_benchmark`` (primary == benchmark → degenerate)

* Conservative wording — banned overclaim tokens are absent from any
  rendered output.
* Import isolation — no provider / yfinance / LLM / FastAPI / api /
  routes.* import at module load.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_REPO_ROOT = Path(__file__).resolve().parents[1]

from scripts import manual_five_event_inspection_table as cli  # noqa: E402


_REQUIRED_TOP_KEYS = (
    "ok",
    "rows",
    "summary",
    "warnings",
    "errors",
)


_REQUIRED_ROW_KEYS = (
    "candidate_id",
    "event_date",
    "headline",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "records_count",
    "raw_p_count",
    "fdr_count",
    "horizons_available",
    "missing_coverage_note",
    "suggested_operator_decision",
    "decision_reason",
)


_DECISION_COVERAGE_BLOCKED:        str = "coverage_blocked"
_DECISION_INSPECT_DO_NOT_MERGE:    str = "inspect_do_not_merge"
_DECISION_INSPECT_CANDIDATE:       str = "inspect_candidate"
_DECISION_REVISE_TICKER_BENCHMARK: str = "revise_ticker_or_benchmark"


_BANNED_TOKENS = (
    "proof",
    "proven",
    "guaranteed",
    "automatically",
    "validated",
    "alpha generated",
    "correct ticker",
    "definitely",
    "approved",
    "production ready",
    "production-ready",
    "demo_ready",
    "demo-ready",
)


# ---------------------------------------------------------------------------
# Envelope fixtures — hand-built so the inspection's tests never depend
# on the validation smoke executing.
# ---------------------------------------------------------------------------


def _record(
    *,
    candidate_id:     str,
    row_index:        int,
    horizon:          int,
    event_date:       str = "2021-05-10",
    headline:         str = "synthetic headline",
    primary_ticker:   str = "ASSET",
    benchmark_ticker: str = "BENCH",
    mechanism_family: str = "synth_family",
    p_value:          float | None = 0.50,
    fdr_q:            float | None = 0.50,
    fdr_significant:  bool = False,
    raw_p_candidate:  bool = False,
    sar:              float | None = 0.10,
    abnormal_return:  float | None = 0.01,
) -> dict[str, Any]:
    return {
        "candidate_id":     candidate_id,
        "row_index":        row_index,
        "headline":         headline,
        "event_date":       event_date,
        "primary_ticker":   primary_ticker,
        "benchmark_ticker": benchmark_ticker,
        "mechanism_family": mechanism_family,
        "horizon":          int(horizon),
        "abnormal_return":  abnormal_return,
        "sar":              sar,
        "p_value":          p_value,
        "fdr_q":            fdr_q,
        "fdr_significant":  bool(fdr_significant),
        "raw_p_candidate":  bool(raw_p_candidate),
        "interpretation":   "not_significant",
        "source":           "manual_five_event_batch",
    }


def _coverage(
    *,
    candidate_id:     str,
    row_index:        int,
    event_date:       str = "2021-05-10",
    headline:         str = "synthetic headline",
    primary_ticker:   str = "ASSET",
    benchmark_ticker: str = "BENCH",
    mechanism_family: str = "synth_family",
    reason:           str = "no cached bars for ASSET in the requested window",
) -> dict[str, Any]:
    return {
        "row_index":        int(row_index),
        "candidate_id":     candidate_id,
        "primary_ticker":   primary_ticker,
        "benchmark_ticker": benchmark_ticker,
        "event_date":       event_date,
        "headline":         headline,
        "mechanism_family": mechanism_family,
        "reason":           reason,
    }


def _envelope(
    *,
    records:          list[dict[str, Any]] | None = None,
    missing_coverage: list[dict[str, Any]] | None = None,
    warnings:         list[str] | None = None,
    errors:           list[str] | None = None,
    horizons:         tuple[int, ...] = (1, 5, 20),
    alpha:            float = 0.05,
) -> dict[str, Any]:
    recs = list(records or [])
    miss = list(missing_coverage or [])
    return {
        "ok":                          not (errors or []),
        "input_csv":                   "examples/manual_five_event_expansion_batch.csv",
        "horizons":                    list(horizons),
        "alpha":                       float(alpha),
        "rows_loaded":                 max(
            len({r["row_index"] for r in recs})
            + len({m["row_index"] for m in miss}),
            0,
        ),
        "events_evaluated":            len({r["row_index"] for r in recs}),
        "records_count":               len(recs),
        "fdr_significant_count":       sum(
            1 for r in recs if r.get("fdr_significant")
        ),
        "raw_p_only_candidate_count":  sum(
            1 for r in recs
            if r.get("raw_p_candidate") and not r.get("fdr_significant")
        ),
        "event_records":               recs,
        "missing_coverage":            miss,
        "warnings":                    list(warnings or []),
        "errors":                      list(errors or []),
    }


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class EnvelopeShapeTests(unittest.TestCase):

    def test_top_level_keys_match_pinned_set(self) -> None:
        env = cli.build_inspection_table(_envelope())
        self.assertEqual(set(env.keys()), set(_REQUIRED_TOP_KEYS))

    def test_empty_validation_envelope_yields_no_rows_and_ok_true(self) -> None:
        env = cli.build_inspection_table(_envelope())
        self.assertEqual(env["rows"], [])
        self.assertTrue(env["ok"])

    def test_validation_errors_are_propagated_and_ok_is_false(self) -> None:
        env = cli.build_inspection_table(_envelope(errors=["input CSV missing"]))
        self.assertFalse(env["ok"])
        self.assertIn("input CSV missing", env["errors"])


# ---------------------------------------------------------------------------
# Row shape
# ---------------------------------------------------------------------------


class RowShapeTests(unittest.TestCase):

    def test_each_row_carries_required_keys(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[_record(candidate_id="manual-five-001", row_index=0, horizon=h)
                     for h in (1, 5, 20)],
        ))
        self.assertEqual(len(env["rows"]), 1)
        for row in env["rows"]:
            self.assertEqual(
                set(row.keys()),
                set(_REQUIRED_ROW_KEYS),
                msg=f"row key drift: {sorted(row.keys())}",
            )

    def test_records_count_equals_horizon_count(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[_record(candidate_id="manual-five-001", row_index=0, horizon=h)
                     for h in (1, 5, 20)],
        ))
        self.assertEqual(env["rows"][0]["records_count"], 3)

    def test_row_propagates_metadata_from_first_record(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[_record(
                candidate_id="manual-five-002",
                row_index=1,
                horizon=h,
                event_date="2022-10-07",
                headline="export controls",
                mechanism_family="export_controls_sanctions",
                primary_ticker="NVDA",
                benchmark_ticker="SMH",
            ) for h in (1, 5, 20)],
        ))
        row = env["rows"][0]
        self.assertEqual(row["candidate_id"],     "manual-five-002")
        self.assertEqual(row["event_date"],       "2022-10-07")
        self.assertEqual(row["headline"],         "export controls")
        self.assertEqual(row["mechanism_family"], "export_controls_sanctions")
        self.assertEqual(row["primary_ticker"],   "NVDA")
        self.assertEqual(row["benchmark_ticker"], "SMH")


# ---------------------------------------------------------------------------
# Decision rules
# ---------------------------------------------------------------------------


class DecisionRuleTests(unittest.TestCase):

    def test_no_records_only_missing_coverage_yields_coverage_blocked(self) -> None:
        env = cli.build_inspection_table(_envelope(
            missing_coverage=[_coverage(
                candidate_id="manual-five-001",
                row_index=0,
                reason="no cached bars for ASSET in the requested window",
            )],
        ))
        self.assertEqual(len(env["rows"]), 1)
        row = env["rows"][0]
        self.assertEqual(
            row["suggested_operator_decision"], _DECISION_COVERAGE_BLOCKED,
        )
        self.assertEqual(row["records_count"], 0)
        self.assertEqual(row["raw_p_count"],   0)
        self.assertEqual(row["fdr_count"],     0)
        self.assertEqual(row["horizons_available"], [])
        self.assertIn("no cached bars for ASSET", row["missing_coverage_note"])

    def test_records_but_no_signal_yields_inspect_do_not_merge(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[_record(
                candidate_id="manual-five-001",
                row_index=0,
                horizon=h,
                p_value=0.50,
                fdr_q=0.50,
                fdr_significant=False,
                raw_p_candidate=False,
            ) for h in (1, 5, 20)],
        ))
        self.assertEqual(
            env["rows"][0]["suggested_operator_decision"],
            _DECISION_INSPECT_DO_NOT_MERGE,
        )

    def test_raw_p_only_records_yield_inspect_candidate(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[
                _record(
                    candidate_id="manual-five-001",
                    row_index=0,
                    horizon=1,
                    p_value=0.02,
                    fdr_q=0.30,
                    fdr_significant=False,
                    raw_p_candidate=True,
                ),
                _record(
                    candidate_id="manual-five-001",
                    row_index=0,
                    horizon=5,
                    p_value=0.40,
                    fdr_q=0.45,
                    fdr_significant=False,
                    raw_p_candidate=False,
                ),
            ],
        ))
        row = env["rows"][0]
        self.assertEqual(
            row["suggested_operator_decision"],
            _DECISION_INSPECT_CANDIDATE,
        )
        self.assertEqual(row["raw_p_count"], 1)
        self.assertEqual(row["fdr_count"],   0)

    def test_fdr_significant_records_yield_inspect_candidate(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[_record(
                candidate_id="manual-five-001",
                row_index=0,
                horizon=1,
                p_value=0.001,
                fdr_q=0.01,
                fdr_significant=True,
                raw_p_candidate=False,
            )],
        ))
        row = env["rows"][0]
        self.assertEqual(
            row["suggested_operator_decision"],
            _DECISION_INSPECT_CANDIDATE,
        )
        self.assertEqual(row["fdr_count"], 1)

    def test_primary_equals_benchmark_yields_revise_ticker_or_benchmark(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[_record(
                candidate_id="manual-five-001",
                row_index=0,
                horizon=h,
                primary_ticker="USO",
                benchmark_ticker="USO",
                p_value=0.001,
                fdr_q=0.01,
                fdr_significant=True,
            ) for h in (1, 5, 20)],
        ))
        row = env["rows"][0]
        self.assertEqual(
            row["suggested_operator_decision"],
            _DECISION_REVISE_TICKER_BENCHMARK,
        )
        self.assertIn("benchmark", row["decision_reason"].lower())

    def test_revise_overrides_coverage_blocked_when_primary_equals_benchmark(
        self,
    ) -> None:
        env = cli.build_inspection_table(_envelope(
            missing_coverage=[_coverage(
                candidate_id="manual-five-001",
                row_index=0,
                primary_ticker="USO",
                benchmark_ticker="USO",
                reason="no cached bars",
            )],
        ))
        self.assertEqual(
            env["rows"][0]["suggested_operator_decision"],
            _DECISION_REVISE_TICKER_BENCHMARK,
        )

    def test_decision_reason_is_non_empty(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[_record(
                candidate_id="manual-five-001",
                row_index=0,
                horizon=1,
                p_value=0.001,
                fdr_q=0.01,
                fdr_significant=True,
            )],
        ))
        self.assertTrue(env["rows"][0]["decision_reason"].strip())


# ---------------------------------------------------------------------------
# Horizons-available
# ---------------------------------------------------------------------------


class HorizonsAvailableTests(unittest.TestCase):

    def test_lists_horizons_with_finite_p_value_in_ascending_order(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[
                _record(candidate_id="manual-five-001", row_index=0,
                        horizon=20, p_value=0.10, fdr_q=0.20),
                _record(candidate_id="manual-five-001", row_index=0,
                        horizon=1,  p_value=0.05, fdr_q=0.10),
                _record(candidate_id="manual-five-001", row_index=0,
                        horizon=5,  p_value=None, fdr_q=None),
            ],
        ))
        self.assertEqual(env["rows"][0]["horizons_available"], [1, 20])


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------


class RowOrderingTests(unittest.TestCase):

    def test_rows_are_sorted_by_row_index_not_by_records_then_missing(self) -> None:
        # Validation envelope: records for rows 0, 2, 4 and missing
        # coverage for rows 1 and 3.  Naive discovery order (records
        # first) would emit 0, 2, 4, 1, 3; the inspection table
        # should sort by row_index so the operator reads 0..4.
        env = cli.build_inspection_table(_envelope(
            records=[
                _record(candidate_id="manual-five-001", row_index=0, horizon=1),
                _record(candidate_id="manual-five-003", row_index=2, horizon=1),
                _record(candidate_id="manual-five-005", row_index=4, horizon=1),
            ],
            missing_coverage=[
                _coverage(candidate_id="manual-five-002", row_index=1),
                _coverage(candidate_id="manual-five-004", row_index=3),
            ],
        ))
        self.assertEqual(
            [row["candidate_id"] for row in env["rows"]],
            [
                "manual-five-001",
                "manual-five-002",
                "manual-five-003",
                "manual-five-004",
                "manual-five-005",
            ],
        )


class SummaryTests(unittest.TestCase):

    def test_summary_counts_total_candidates_and_decisions(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[
                _record(candidate_id="manual-five-001", row_index=0,
                        horizon=h, p_value=0.001, fdr_q=0.01,
                        fdr_significant=True) for h in (1, 5, 20)
            ] + [
                _record(candidate_id="manual-five-002", row_index=1,
                        primary_ticker="X", benchmark_ticker="X",
                        horizon=h) for h in (1, 5, 20)
            ],
            missing_coverage=[
                _coverage(candidate_id="manual-five-003", row_index=2,
                          primary_ticker="ZIM", benchmark_ticker="IYT"),
            ],
        ))
        summary = env["summary"]
        self.assertEqual(summary["total_candidates"], 3)
        self.assertEqual(
            summary["by_decision"].get(_DECISION_INSPECT_CANDIDATE), 1,
        )
        self.assertEqual(
            summary["by_decision"].get(_DECISION_REVISE_TICKER_BENCHMARK), 1,
        )
        self.assertEqual(
            summary["by_decision"].get(_DECISION_COVERAGE_BLOCKED), 1,
        )


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class ConservativeWordingTests(unittest.TestCase):

    def test_json_render_carries_no_banned_tokens(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[_record(
                candidate_id="manual-five-001",
                row_index=0,
                horizon=h,
                p_value=0.001,
                fdr_q=0.01,
                fdr_significant=True,
            ) for h in (1, 5, 20)],
            missing_coverage=[_coverage(candidate_id="manual-five-002",
                                        row_index=1)],
        ))
        rendered = json.dumps(env, default=str).lower()
        for token in _BANNED_TOKENS:
            self.assertNotIn(token, rendered, msg=f"banned token {token!r}")

    def test_text_render_carries_no_banned_tokens(self) -> None:
        env = cli.build_inspection_table(_envelope(
            records=[_record(
                candidate_id="manual-five-001",
                row_index=0,
                horizon=h,
                p_value=0.001,
                fdr_q=0.01,
                fdr_significant=True,
            ) for h in (1, 5, 20)],
        ))
        text = cli._render_text(env).lower()
        for token in _BANNED_TOKENS:
            self.assertNotIn(token, text, msg=f"banned token {token!r}")


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class ImportIsolationTests(unittest.TestCase):

    _BANNED_MODULE_SUBSTRINGS = (
        "yfinance",
        "market_data",
        "llm",
        "openai",
        "anthropic",
    )

    _BANNED_FASTAPI_TOPLEVEL = (
        "api",
        "routes.",
        "fastapi",
        "uvicorn",
    )

    def test_module_top_level_imports_no_paid_or_fastapi(self) -> None:
        # Source-level check: the module's text must not contain a
        # paid / LLM / FastAPI top-level import.  We deliberately do
        # NOT inspect global ``sys.modules`` — by the time this test
        # runs other test modules in the suite may already have
        # imported price_cache / yfinance through unrelated paths.
        with open(cli.__file__, "r", encoding="utf-8") as _fh:
            src = _fh.read()
        low_src = src.lower()
        for banned in (
            "import yfinance",
            "from yfinance",
            "import market_data",
            "from market_data",
            "from api ",
            "import api\n",
            "from routes",
            "import routes",
            "import fastapi",
            "from fastapi",
            "import openai",
            "from openai",
            "import anthropic",
            "from anthropic",
        ):
            self.assertNotIn(
                banned, low_src,
                msg=f"banned top-level import token: {banned!r}",
            )

    def test_fresh_subprocess_import_does_not_load_paid_modules(self) -> None:
        # Import the inspection module in a fresh interpreter and
        # confirm none of the banned modules end up in sys.modules.
        # This is the strongest no-paid check available without a
        # network-blocked sandbox.
        import subprocess
        import textwrap
        snippet = textwrap.dedent(
            """
            import sys, json
            sys.path.insert(0, %r)
            import scripts.manual_five_event_inspection_table  # noqa: F401
            banned = ("yfinance", "market_data", "openai", "anthropic",
                      "fastapi", "uvicorn")
            hits = sorted(
                m for m in sys.modules
                if any(b in m.lower() for b in banned)
            )
            print(json.dumps(hits))
            """
        ) % (str(_REPO_ROOT),)
        proc = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        hits = json.loads(proc.stdout.strip() or "[]")
        self.assertEqual(hits, [], msg=f"paid imports leaked: {hits}")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class CLITests(unittest.TestCase):

    def test_cli_json_runs_against_patched_smoke(self) -> None:
        fake_envelope = _envelope(
            records=[_record(
                candidate_id="manual-five-001",
                row_index=0,
                horizon=1,
                p_value=0.001,
                fdr_q=0.01,
                fdr_significant=True,
            )],
        )
        out = io.StringIO()
        with patch.object(
            cli, "_run_validation_smoke", return_value=fake_envelope,
        ):
            rc = cli.main(["--json"], out=out)
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(set(payload.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertEqual(len(payload["rows"]), 1)

    def test_cli_text_runs_against_patched_smoke(self) -> None:
        fake_envelope = _envelope(
            missing_coverage=[_coverage(
                candidate_id="manual-five-001",
                row_index=0,
                reason="no cached bars",
            )],
        )
        out = io.StringIO()
        with patch.object(
            cli, "_run_validation_smoke", return_value=fake_envelope,
        ):
            rc = cli.main([], out=out)
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("coverage_blocked", text)

    def test_cli_exit_code_nonzero_when_envelope_errors(self) -> None:
        fake_envelope = _envelope(errors=["input CSV missing"])
        out = io.StringIO()
        with patch.object(
            cli, "_run_validation_smoke", return_value=fake_envelope,
        ):
            rc = cli.main(["--json"], out=out)
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# Pure-compute entry point
# ---------------------------------------------------------------------------


class PureBuildTests(unittest.TestCase):

    def test_build_inspection_table_does_not_mutate_input_envelope(self) -> None:
        envelope = _envelope(
            records=[_record(
                candidate_id="manual-five-001",
                row_index=0,
                horizon=1,
                p_value=0.001,
                fdr_q=0.01,
                fdr_significant=True,
            )],
        )
        original = json.dumps(envelope, sort_keys=True, default=str)
        cli.build_inspection_table(envelope)
        after = json.dumps(envelope, sort_keys=True, default=str)
        self.assertEqual(original, after)


if __name__ == "__main__":
    unittest.main()
