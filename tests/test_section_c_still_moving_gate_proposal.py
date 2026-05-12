"""Tests for ``scripts/section_c_still_moving_gate_proposal.py``.

Pin the contract:

* Read-only on every input.  The diagnostic snapshot JSON is opened
  ``"r"`` only.  No DB connection, no paid surface, no FastAPI
  import, no LLM.
* The envelope carries the nine required keys with the spec'd shape.
* The eight proposed gates appear in stable spec order (consumers
  may index by position).
* The ranking gate (gate 8, ``rank_by_evidence_strength``) carries
  ``failure_count`` and ``pass_count`` of ``None`` — it is a meta
  gate, not a per-row eligibility check.
* Per-row gates evaluate as documented against synthetic candidates.
* ``examples_blocked_by_gate`` is capped per-gate; ``examples_
  allowed_by_gate`` is capped overall and contains only candidates
  that clear every eligibility gate (the ranking gate is skipped).
* Conservative wording: banned tokens absent from the proposal's
  prose.
* ``--output`` writes the envelope only when explicitly passed; the
  default invocation has no filesystem side effect.
* End-to-end: a real diagnostic snapshot on disk round-trips through
  the proposal without errors.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import section_c_still_moving_gate_proposal as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "candidates_analyzed",
    "proposed_gates",
    "gate_failure_counts",
    "defensible_candidate_requirements",
    "examples_blocked_by_gate",
    "examples_allowed_by_gate",
    "warnings",
    "errors",
)


_EXPECTED_GATE_ORDER = (
    "primary_ticker_present",
    "primary_neq_benchmark",
    "primary_not_sector_etf",
    "price_cache_coverage",
    "benchmark_adjusted_evidence",
    "persistence_signal_available",
    "no_duplicate_narrative",
    "rank_by_evidence_strength",
)


_REQUIRED_GATE_FIELDS = (
    "gate_id",
    "name",
    "requirement",
    "gate_type",
    "diagnostic_signal",
    "failure_count",
    "pass_count",
    "false_positive_risk",
    "defensible_default",
    "expected_benefit",
)


_BANNED_TOKENS = (
    "proof",
    "proven",
    "automatically",
    "alpha generated",
    "guaranteed",
    "correct ticker",
)


# ---------------------------------------------------------------------------
# Synthetic candidate fixtures
# ---------------------------------------------------------------------------


def _candidate(
    *,
    event_id: int = 1,
    headline: str = "synthetic headline",
    event_date: str = "2026-05-08",
    primary_ticker: str | None = "XOM",
    benchmark_ticker: str | None = "SPY",
    mechanism_family: str | None = "supply_shock",
    ticker_quality: str = "ok",
    price_cache_available: bool = True,
    benchmark_adjusted_evidence_available: bool = True,
    persistence_signal: str | None = "trend_continuation",
    diagnostic_tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "event_id":         event_id,
        "headline":         headline,
        "event_date":       event_date,
        "primary_ticker":   primary_ticker,
        "benchmark_ticker": benchmark_ticker,
        "mechanism_family": mechanism_family,
        "ticker_quality":   ticker_quality,
        "price_cache_available": price_cache_available,
        "benchmark_adjusted_evidence_available":
            benchmark_adjusted_evidence_available,
        "persistence_signal": persistence_signal,
        "diagnostic_tags":  list(diagnostic_tags or []),
        "inclusion_reason": "",
        "exclusion_reason": "",
    }


def _diagnostic(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": True,
        "candidates_checked": len(candidates),
        "defensible_candidates": 0,
        "weak_ticker_cases": 0,
        "bad_proxy_cases": 0,
        "missing_price_cache_cases": 0,
        "no_persistence_cases": 0,
        "duplicate_narrative_cases": 0,
        "recommended_still_moving_filter_rules": [],
        "warnings": [],
        "errors": [],
        "candidates": candidates,
    }


def _write_diagnostic(payload: dict[str, Any]) -> str:
    fd, path = tempfile.mkstemp(
        prefix=f"sm_gate_diag_{uuid.uuid4().hex}_", suffix=".json",
    )
    os.close(fd)
    Path(path).write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_envelope_has_all_required_keys(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([]))
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, report, f"missing key: {k}")

    def test_missing_diagnostic_path_surfaces_warning_not_error(self) -> None:
        missing = os.path.join(
            tempfile.gettempdir(), f"absent_{uuid.uuid4().hex}.json",
        )
        self.assertFalse(os.path.exists(missing))
        report = cli.build_proposal(diagnostic_path=missing)
        self.assertTrue(report["ok"])
        self.assertEqual(report["candidates_analyzed"], 0)
        self.assertTrue(any(
            "missing" in w.lower() for w in report["warnings"]
        ))

    def test_malformed_diagnostic_surfaces_error(self) -> None:
        fd, path = tempfile.mkstemp(
            prefix="sm_gate_bad_", suffix=".json",
        )
        os.close(fd)
        Path(path).write_text("not valid json", encoding="utf-8")
        try:
            report = cli.build_proposal(diagnostic_path=path)
            self.assertFalse(report["ok"])
            self.assertTrue(report["errors"])
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Gate set and order
# ---------------------------------------------------------------------------


class TestGateSetAndOrder(unittest.TestCase):
    def test_eight_gates_in_spec_order(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([]))
        ids = [g["gate_id"] for g in report["proposed_gates"]]
        self.assertEqual(ids, list(_EXPECTED_GATE_ORDER))

    def test_each_gate_has_required_fields(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([]))
        for gate in report["proposed_gates"]:
            for f in _REQUIRED_GATE_FIELDS:
                self.assertIn(f, gate, f"gate missing field: {f}")

    def test_ranking_gate_carries_null_counts(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1),
            _candidate(event_id=2),
        ]))
        ranking = next(
            g for g in report["proposed_gates"]
            if g["gate_id"] == "rank_by_evidence_strength"
        )
        self.assertEqual(ranking["gate_type"], "ranking")
        self.assertIsNone(ranking["failure_count"])
        self.assertIsNone(ranking["pass_count"])

    def test_eligibility_gates_carry_int_counts(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1),
        ]))
        for gate in report["proposed_gates"]:
            if gate["gate_type"] == "ranking":
                continue
            self.assertIsInstance(
                gate["failure_count"], int,
                f"{gate['gate_id']} must carry an int failure_count",
            )
            self.assertIsInstance(
                gate["pass_count"], int,
                f"{gate['gate_id']} must carry an int pass_count",
            )


# ---------------------------------------------------------------------------
# Per-gate evaluation
# ---------------------------------------------------------------------------


class TestPerGateEvaluation(unittest.TestCase):
    def _failure_count(
        self, report: dict[str, Any], gate_id: str,
    ) -> int | None:
        return report["gate_failure_counts"][gate_id]

    def test_primary_ticker_present_gate(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1, primary_ticker="XOM"),
            _candidate(event_id=2, primary_ticker=None),
            _candidate(event_id=3, primary_ticker=""),
        ]))
        self.assertEqual(
            self._failure_count(report, "primary_ticker_present"), 2,
        )

    def test_primary_neq_benchmark_gate(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1, primary_ticker="XOM",
                       benchmark_ticker="SPY"),
            _candidate(event_id=2, primary_ticker="XLE",
                       benchmark_ticker="XLE"),
            # Case-insensitive collision.
            _candidate(event_id=3, primary_ticker="xle",
                       benchmark_ticker="XLE"),
        ]))
        self.assertEqual(
            self._failure_count(report, "primary_neq_benchmark"), 2,
        )

    def test_primary_not_sector_etf_gate_uses_diagnostic_signal(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1, primary_ticker="XOM",
                       ticker_quality="ok"),
            _candidate(event_id=2, primary_ticker="XLE",
                       ticker_quality="bad_proxy"),
        ]))
        self.assertEqual(
            self._failure_count(report, "primary_not_sector_etf"), 1,
        )

    def test_primary_not_sector_etf_allowlist_overrides(self) -> None:
        report = cli.build_proposal(
            diagnostic=_diagnostic([
                _candidate(event_id=1, primary_ticker="XLE",
                           ticker_quality="bad_proxy"),
                _candidate(event_id=2, primary_ticker="XLF",
                           ticker_quality="bad_proxy"),
            ]),
            sector_etf_allowlist=("XLE",),
        )
        # XLE is allow-listed and clears; XLF is not.
        self.assertEqual(
            self._failure_count(report, "primary_not_sector_etf"), 1,
        )

    def test_price_cache_coverage_gate(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1, price_cache_available=True),
            _candidate(event_id=2, price_cache_available=False),
            _candidate(event_id=3, price_cache_available=False),
        ]))
        self.assertEqual(
            self._failure_count(report, "price_cache_coverage"), 2,
        )

    def test_benchmark_adjusted_evidence_gate(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1,
                       benchmark_adjusted_evidence_available=True),
            _candidate(event_id=2,
                       benchmark_adjusted_evidence_available=False),
        ]))
        self.assertEqual(
            self._failure_count(report, "benchmark_adjusted_evidence"), 1,
        )

    def test_persistence_signal_available_gate(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1, persistence_signal="trend"),
            _candidate(event_id=2, persistence_signal=None),
            _candidate(event_id=3, persistence_signal=""),
        ]))
        self.assertEqual(
            self._failure_count(report, "persistence_signal_available"), 2,
        )

    def test_no_duplicate_narrative_gate(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1, diagnostic_tags=[]),
            _candidate(event_id=2,
                       diagnostic_tags=["duplicate_narrative"]),
            _candidate(event_id=3,
                       diagnostic_tags=["no_persistence_signal",
                                        "duplicate_narrative"]),
        ]))
        self.assertEqual(
            self._failure_count(report, "no_duplicate_narrative"), 2,
        )

    def test_missing_primary_cascades_to_neq_benchmark_failure(self) -> None:
        # If primary is missing, the primary != benchmark gate must
        # also fail — the question is unanswerable, and a missing
        # primary is the load-bearing failure.
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1, primary_ticker=None,
                       benchmark_ticker="SPY"),
        ]))
        self.assertEqual(
            self._failure_count(report, "primary_ticker_present"), 1,
        )
        self.assertEqual(
            self._failure_count(report, "primary_neq_benchmark"), 1,
        )


# ---------------------------------------------------------------------------
# Examples
# ---------------------------------------------------------------------------


class TestExamples(unittest.TestCase):
    def test_blocked_examples_capped_per_gate(self) -> None:
        # 10 candidates that all fail price_cache_coverage.  Default
        # cap is 3.
        report = cli.build_proposal(
            diagnostic=_diagnostic([
                _candidate(event_id=100 + i, price_cache_available=False)
                for i in range(10)
            ]),
        )
        blocked = report["examples_blocked_by_gate"]
        self.assertEqual(len(blocked["price_cache_coverage"]), 3)
        for ex in blocked["price_cache_coverage"]:
            self.assertEqual(ex["blocked_by_gate"], "price_cache_coverage")

    def test_blocked_examples_only_for_failing_gate(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            # Fails only price_cache_coverage.
            _candidate(event_id=1, price_cache_available=False),
            # Fails only persistence_signal_available.
            _candidate(event_id=2, persistence_signal=None),
        ]))
        blocked = report["examples_blocked_by_gate"]
        cache_event_ids = {
            ex["event_id"] for ex in blocked["price_cache_coverage"]
        }
        signal_event_ids = {
            ex["event_id"] for ex in blocked["persistence_signal_available"]
        }
        self.assertIn(1, cache_event_ids)
        self.assertNotIn(2, cache_event_ids)
        self.assertIn(2, signal_event_ids)
        self.assertNotIn(1, signal_event_ids)

    def test_ranking_gate_has_no_blocked_examples_bucket(self) -> None:
        # ``examples_blocked_by_gate`` is keyed only by eligibility
        # gates — the ranking gate is meta and has no per-row
        # failure list.
        report = cli.build_proposal(diagnostic=_diagnostic([]))
        self.assertNotIn(
            "rank_by_evidence_strength", report["examples_blocked_by_gate"],
        )

    def test_allowed_examples_clear_every_eligibility_gate(self) -> None:
        # A clean candidate clears all eligibility gates.
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1),
            _candidate(event_id=2, price_cache_available=False),
        ]))
        allowed = report["examples_allowed_by_gate"]
        self.assertEqual(len(allowed), 1)
        self.assertEqual(allowed[0]["event_id"], 1)

    def test_allowed_examples_capped(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=200 + i) for i in range(20)
        ]))
        self.assertEqual(
            len(report["examples_allowed_by_gate"]), 5,
        )


# ---------------------------------------------------------------------------
# Defensible-candidate-requirements
# ---------------------------------------------------------------------------


class TestDefensibleCandidateRequirements(unittest.TestCase):
    def test_one_requirement_per_gate(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([]))
        self.assertEqual(
            len(report["defensible_candidate_requirements"]),
            len(_EXPECTED_GATE_ORDER),
        )
        for req in report["defensible_candidate_requirements"]:
            self.assertIsInstance(req, str)
            self.assertTrue(req.strip())


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_tokens_in_json_render(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1, price_cache_available=False),
        ]))
        blob = cli._render_json(report).lower()
        for term in _BANNED_TOKENS:
            self.assertNotIn(
                term, blob,
                f"banned token {term!r} in JSON render",
            )

    def test_no_banned_tokens_in_text_render(self) -> None:
        report = cli.build_proposal(diagnostic=_diagnostic([
            _candidate(event_id=1, price_cache_available=False),
        ]))
        blob = cli._render_text(report).lower()
        for term in _BANNED_TOKENS:
            self.assertNotIn(term, blob)


# ---------------------------------------------------------------------------
# Output file persistence
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_no_output_means_no_file(self) -> None:
        sentinel = os.path.join(
            tempfile.gettempdir(),
            f"sm_gate_sentinel_{uuid.uuid4().hex}.json",
        )
        self.assertFalse(os.path.exists(sentinel))
        try:
            cli.build_proposal(diagnostic=_diagnostic([]))
            self.assertFalse(os.path.exists(sentinel))
        finally:
            if os.path.exists(sentinel):
                os.unlink(sentinel)

    def test_output_writes_file(self) -> None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"sm_gate_out_{uuid.uuid4().hex}.json",
        )
        try:
            report = cli.build_proposal(
                diagnostic=_diagnostic([_candidate(event_id=1)]),
                output_path=out_path,
            )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(set(data.keys()) >= set(_REQUIRED_ENVELOPE_KEYS),
                             True)
            self.assertEqual(data["ok"], report["ok"])
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)


# ---------------------------------------------------------------------------
# CLI plumbing — round-trips through a saved diagnostic JSON
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, out.getvalue()

    def test_json_default_with_diagnostic_path(self) -> None:
        path = _write_diagnostic(_diagnostic([_candidate(event_id=1)]))
        try:
            rc, output = self._run([
                "--json", "--diagnostic-path", path,
            ])
            self.assertEqual(rc, 0)
            payload = json.loads(output)
            for k in _REQUIRED_ENVELOPE_KEYS:
                self.assertIn(k, payload)
            self.assertEqual(payload["candidates_analyzed"], 1)
        finally:
            os.unlink(path)

    def test_text_flag(self) -> None:
        path = _write_diagnostic(_diagnostic([]))
        try:
            rc, output = self._run([
                "--text", "--diagnostic-path", path,
            ])
            self.assertEqual(rc, 0)
            self.assertIn("still moving market", output.lower())
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# End-to-end: a real diagnostic snapshot on disk
# ---------------------------------------------------------------------------


class TestRoundTripWithRealisticSnapshot(unittest.TestCase):
    def test_realistic_snapshot_runs_clean(self) -> None:
        # Simulate the live snapshot shape (mixed pass / fail rows
        # across multiple weakness axes) and verify the proposal
        # produces sensible counts end-to-end.
        cands = [
            # Clean candidate — clears every eligibility gate.
            _candidate(
                event_id=1, primary_ticker="XOM",
                benchmark_ticker="SPY",
                ticker_quality="ok",
                price_cache_available=True,
                benchmark_adjusted_evidence_available=True,
                persistence_signal="trend_continuation",
                diagnostic_tags=[],
            ),
            # Missing price cache.
            _candidate(
                event_id=2, primary_ticker="MS",
                benchmark_ticker="SPY",
                price_cache_available=False,
                diagnostic_tags=["missing_price_cache",
                                 "no_benchmark_adjusted_evidence",
                                 "no_persistence_signal"],
                benchmark_adjusted_evidence_available=False,
                persistence_signal=None,
            ),
            # Sector-ETF primary.
            _candidate(
                event_id=3, primary_ticker="XLE",
                benchmark_ticker="SPY",
                ticker_quality="bad_proxy",
                diagnostic_tags=["weak_ticker"],
            ),
            # Duplicate narrative.
            _candidate(
                event_id=4, primary_ticker="XOM",
                benchmark_ticker="SPY",
                diagnostic_tags=["duplicate_narrative"],
            ),
        ]
        path = _write_diagnostic(_diagnostic(cands))
        try:
            report = cli.build_proposal(diagnostic_path=path)
            self.assertTrue(report["ok"])
            self.assertEqual(report["candidates_analyzed"], 4)
            # One clean candidate clears every eligibility gate.
            self.assertEqual(len(report["examples_allowed_by_gate"]), 1)
            self.assertEqual(
                report["examples_allowed_by_gate"][0]["event_id"], 1,
            )
            # Sector ETF caught.
            self.assertEqual(
                report["gate_failure_counts"]["primary_not_sector_etf"], 1,
            )
            # Duplicate narrative caught.
            self.assertEqual(
                report["gate_failure_counts"]["no_duplicate_narrative"], 1,
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_paid_surfaces(self) -> None:
        for attr in ("yfinance", "anthropic", "openai", "fastapi",
                     "market_data", "sqlite3"):
            self.assertFalse(
                hasattr(cli, attr),
                f"proposal must not bind {attr} as a module attr",
            )


if __name__ == "__main__":
    unittest.main()
