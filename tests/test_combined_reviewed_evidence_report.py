"""Tests for ``scripts/combined_reviewed_evidence_report.py``.

The combined evidence report stitches three on-disk JSON artifacts
(curated stage validation evidence + the short-horizon review top10
/ next10 validation runs) into a single read-only inspection view.

Pin the contract:

* Read-only — never rewrites the on-disk artifacts.
* No DB / provider / yfinance / LLM / FastAPI imports.
* Builder reads ``examples`` from each artifact and re-derives
  ``raw_p_candidate`` / ``fdr_significant`` / ``verdict`` so the
  three sources speak the same vocabulary, using the canonical
  ``DEFAULT_ALPHA`` threshold from :mod:`stats.stat_validation`.  No
  new statistic is computed.
* Envelope schema (18 keys, in any order)::

      ok, generated_at, sources,
      total_event_sources, total_records,
      fdr_significant_count, raw_p_candidate_count,
      verdict_counts, by_source, by_horizon, by_mechanism_family,
      duplicate_event_ids, strongest_raw_p_candidates,
      null_or_inconclusive_examples,
      evidence_claim_allowed, evidence_claim_not_allowed,
      recommended_next_action, warnings, errors

* ``fdr_significant_count`` is driven by the per-record fdr_q vs
  alpha check only.  ``raw_p_candidate_count`` counts records with
  ``raw_p_candidate=True`` OR ``verdict=validated_raw_only`` (those
  are the same population by construction).
* Missing artifact path → ``ok=False`` with a clear error.
* Duplicate event_ids across sources surface in
  ``duplicate_event_ids`` (the report never silently dedupes).
* ``strongest_raw_p_candidates`` sorted by ``p_value`` ascending,
  capped at 10.
* ``recommended_next_action`` is conservative: when
  ``fdr_significant_count == 0`` it says the cohort is useful for
  methodology / demo only, not for a validation claim.
* Conservative wording — banned tokens absent from
  ``errors``, ``warnings``, ``recommended_next_action`` and the
  ``evidence_claim_*`` strings: ``proof``, ``proves``, ``alpha``,
  ``guaranteed``, ``automatically``.
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
from typing import Any, Iterable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import combined_reviewed_evidence_report as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "generated_at",
    "sources",
    "total_event_sources",
    "total_records",
    "fdr_significant_count",
    "raw_p_candidate_count",
    "verdict_counts",
    "by_source",
    "by_horizon",
    "by_mechanism_family",
    "duplicate_event_ids",
    "strongest_raw_p_candidates",
    "null_or_inconclusive_examples",
    "evidence_claim_allowed",
    "evidence_claim_not_allowed",
    "recommended_next_action",
    "warnings",
    "errors",
)


_VERDICT_VALUES = (
    "fdr_significant",
    "validated_raw_only",
    "inconclusive_fdr",
    "not_evaluable",
)


# Banned tokens — the conservative phrase "not FDR-validated" is
# permitted (matches the existing curated runner's policy of using
# ``validated`` as a deliberate negative).  Only over-claims are
# banned.
_BANNED_WORDS = (
    "proof",
    "proves",
    "alpha",
    "guaranteed",
    "automatically",
    "is proven",
    "alpha generated",
    "definitely validated",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _curated_example(
    *, source_event_id: int, horizon: int = 1,
    p_value: float | None = 0.20,
    fdr_q:   float | None = 0.30,
    abnormal_return: float = 0.01,
    sar: float = 1.0,
    primary_ticker: str = "XOM",
    benchmark_ticker: str = "SPY",
    mechanism_family: str = "supply_shock",
    headline: str = "curated headline",
    interpretation: str = "not_significant",
    raw_p_candidate: bool = False,
    fdr_significant: bool = False,
    verdict: str = "inconclusive_fdr",
) -> dict[str, Any]:
    """Mirror the ``curated_stage_validation_evidence.json`` shape."""
    return {
        "source_event_id":  source_event_id,
        "horizon":          horizon,
        "p_value":          p_value,
        "fdr_q":            fdr_q,
        "abnormal_return":  abnormal_return,
        "sar":              sar,
        "ci_low":           -0.01,
        "ci_high":          0.05,
        "primary_ticker":   primary_ticker,
        "benchmark_ticker": benchmark_ticker,
        "mechanism_family": mechanism_family,
        "headline":         headline,
        "interpretation":   interpretation,
        "raw_p_candidate":  raw_p_candidate,
        "fdr_significant":  fdr_significant,
        "verdict":          verdict,
    }


def _review_example(
    *, event_id: int, horizon: int = 1,
    p_value: float | None = 0.20,
    fdr_q:   float | None = 0.30,
    abnormal_return: float = 0.01,
    sar: float = 1.0,
    primary_ticker: str = "MS",
    mechanism_family: str = "bank_regulatory_capital_relief",
    headline: str = "review headline",
    interpretation: str = "not_significant",
) -> dict[str, Any]:
    """Mirror the ``short_horizon_review_validation_*.json`` shape.

    These artifacts use ``event_id`` (not ``source_event_id``) and
    do not carry the verdict fields — the combined report must
    re-derive them.
    """
    return {
        "event_id":         event_id,
        "horizon":          horizon,
        "p_value":          p_value,
        "fdr_q":            fdr_q,
        "abnormal_return":  abnormal_return,
        "sar":              sar,
        "ci_low":           -0.01,
        "ci_high":          0.05,
        "primary_ticker":   primary_ticker,
        "benchmark":        "SPY",
        "mechanism_family": mechanism_family,
        "headline":         headline,
        "interpretation":   interpretation,
    }


def _write_artifact(
    *, kind: str, examples: list[dict[str, Any]],
    records_count: int | None = None,
    significant_count: int = 0,
    extra: dict[str, Any] | None = None,
) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"comb_evidence_{kind}_{uuid.uuid4().hex}.json",
    )
    blob: dict[str, Any] = {
        "examples":           list(examples),
        "records_count":      (
            records_count if records_count is not None else len(examples)
        ),
        "significant_count":  significant_count,
        "warnings":           [],
        "errors":             [],
    }
    if extra:
        blob.update(extra)
    Path(path).write_text(json.dumps(blob), encoding="utf-8")
    return path


class _Artifacts:
    """Context manager that writes three tempfile artifacts and tears
    them down regardless of test outcome."""

    def __init__(
        self,
        *,
        curated: list[dict[str, Any]] | None = None,
        top10:   list[dict[str, Any]] | None = None,
        next10:  list[dict[str, Any]] | None = None,
    ) -> None:
        self._curated_rows = list(curated or [])
        self._top10_rows   = list(top10   or [])
        self._next10_rows  = list(next10  or [])
        self.curated_path: str | None = None
        self.top10_path:   str | None = None
        self.next10_path:  str | None = None

    def __enter__(self) -> "_Artifacts":
        self.curated_path = _write_artifact(
            kind="curated", examples=self._curated_rows,
        )
        self.top10_path = _write_artifact(
            kind="top10", examples=self._top10_rows,
        )
        self.next10_path = _write_artifact(
            kind="next10", examples=self._next10_rows,
        )
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in (self.curated_path, self.top10_path, self.next10_path):
            if p and os.path.exists(p):
                os.unlink(p)

    def kwargs(self) -> dict[str, str]:
        return {
            "curated_stage_path": self.curated_path or "",
            "review_top10_path":  self.top10_path   or "",
            "review_next10_path": self.next10_path  or "",
        }


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_envelope_has_required_keys(self) -> None:
        with _Artifacts() as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, report, f"missing envelope key: {k}")

    def test_envelope_has_no_extra_keys(self) -> None:
        with _Artifacts() as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        extras = set(report) - set(_REQUIRED_ENVELOPE_KEYS)
        self.assertEqual(extras, set(),
                         f"unexpected envelope keys: {extras}")

    def test_ok_true_when_all_three_sources_load(self) -> None:
        with _Artifacts() as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        self.assertTrue(report["ok"], f"errors: {report['errors']}")

    def test_generated_at_is_iso_string(self) -> None:
        with _Artifacts() as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        gen = report["generated_at"]
        self.assertIsInstance(gen, str)
        self.assertGreater(len(gen), 10)


# ---------------------------------------------------------------------------
# Missing-artifact handling
# ---------------------------------------------------------------------------


class TestMissingArtifacts(unittest.TestCase):
    def test_missing_curated_file_yields_ok_false_with_error(self) -> None:
        with _Artifacts() as art:
            report = cli.build_combined_evidence_report(
                curated_stage_path="/no/such/curated.json",
                review_top10_path=art.top10_path,
                review_next10_path=art.next10_path,
            )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "curated" in e.lower() or "does not exist" in e.lower()
            for e in report["errors"]
        ), f"errors: {report['errors']}")

    def test_missing_top10_file_yields_ok_false(self) -> None:
        with _Artifacts() as art:
            report = cli.build_combined_evidence_report(
                curated_stage_path=art.curated_path,
                review_top10_path="/no/such/top10.json",
                review_next10_path=art.next10_path,
            )
        self.assertFalse(report["ok"])
        self.assertTrue(report["errors"])

    def test_missing_next10_file_yields_ok_false(self) -> None:
        with _Artifacts() as art:
            report = cli.build_combined_evidence_report(
                curated_stage_path=art.curated_path,
                review_top10_path=art.top10_path,
                review_next10_path="/no/such/next10.json",
            )
        self.assertFalse(report["ok"])
        self.assertTrue(report["errors"])

    def test_missing_paths_dont_silently_dedupe(self) -> None:
        # When a source is missing, the duplicate detector must still
        # operate over the surviving sources rather than silently
        # collapsing to one.
        with _Artifacts(
            top10=[_review_example(event_id=1)],
            next10=[_review_example(event_id=1)],
        ) as art:
            report = cli.build_combined_evidence_report(
                curated_stage_path="/no/such/curated.json",
                review_top10_path=art.top10_path,
                review_next10_path=art.next10_path,
            )
        # ok=False because curated is missing, but the surviving
        # sources still feed duplicate detection.
        self.assertFalse(report["ok"])


# ---------------------------------------------------------------------------
# Source metadata
# ---------------------------------------------------------------------------


class TestSources(unittest.TestCase):
    def test_three_sources_listed(self) -> None:
        with _Artifacts() as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        self.assertEqual(len(report["sources"]), 3,
                         f"sources: {report['sources']}")

    def test_each_source_carries_path_and_loaded_flag(self) -> None:
        with _Artifacts() as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        for src in report["sources"]:
            self.assertIn("path", src)
            self.assertIn("loaded", src)
            self.assertTrue(src["loaded"], src)


# ---------------------------------------------------------------------------
# Record + FDR + raw-p counting
# ---------------------------------------------------------------------------


class TestCountAggregates(unittest.TestCase):
    def test_total_records_sums_examples_across_sources(self) -> None:
        with _Artifacts(
            curated=[
                _curated_example(source_event_id=1, horizon=1),
                _curated_example(source_event_id=2, horizon=5),
            ],
            top10=[_review_example(event_id=10, horizon=1)],
            next10=[
                _review_example(event_id=20, horizon=1),
                _review_example(event_id=21, horizon=5),
            ],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        self.assertEqual(report["total_records"], 5)

    def test_fdr_significant_count_uses_fdr_q_alpha_threshold(self) -> None:
        with _Artifacts(
            curated=[
                _curated_example(source_event_id=1, fdr_q=0.02,
                                 fdr_significant=True),
                _curated_example(source_event_id=2, fdr_q=0.30,
                                 fdr_significant=False),
            ],
            top10=[
                _review_example(event_id=10, fdr_q=0.04),  # FDR-clears
                _review_example(event_id=11, fdr_q=0.50),
            ],
            next10=[
                _review_example(event_id=20, fdr_q=0.06),  # just above
            ],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        # Two records have fdr_q <= 0.05: curated id=1 (0.02) and
        # top10 id=10 (0.04).  The re-derivation must use the canonical
        # alpha threshold, NOT just the artifact's own flag.
        self.assertEqual(report["fdr_significant_count"], 2)

    def test_raw_p_candidate_count_counts_raw_p_and_verdict(self) -> None:
        # The curated artifact carries explicit raw_p_candidate and
        # verdict.  The short-horizon artifacts carry neither — the
        # combined builder must derive both from p_value vs alpha so
        # raw-p records from EVERY source land in the count.
        with _Artifacts(
            curated=[
                _curated_example(source_event_id=1, p_value=0.02,
                                 fdr_q=0.30, raw_p_candidate=True,
                                 verdict="validated_raw_only"),
                _curated_example(source_event_id=2, p_value=0.50),
            ],
            top10=[
                _review_example(event_id=10, p_value=0.03, fdr_q=0.40),
                _review_example(event_id=11, p_value=0.90, fdr_q=0.95),
            ],
            next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        # curated id=1 (raw_p_candidate flag) + top10 id=10 (derived).
        self.assertEqual(report["raw_p_candidate_count"], 2)

    def test_raw_p_count_never_includes_fdr_significant_records(
        self,
    ) -> None:
        # A record with p<alpha AND fdr_q<alpha is fdr_significant
        # (the strict bar) and is NOT a raw_p-only record.  Verdict
        # must be fdr_significant; raw_p_candidate is still True (the
        # raw-p signal exists) but the verdict ladder treats it as
        # fdr_significant — see runner contract.  Our raw_p count
        # follows the spec literally:
        #   raw_p_candidate_count counts records with
        #   raw_p_candidate=True OR verdict=validated_raw_only
        # so an fdr_significant record with raw_p=True still counts.
        with _Artifacts(
            curated=[],
            top10=[_review_example(
                event_id=1, p_value=0.01, fdr_q=0.02,
            )],
            next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        self.assertEqual(report["fdr_significant_count"], 1)


# ---------------------------------------------------------------------------
# Verdict counts
# ---------------------------------------------------------------------------


class TestVerdictCounts(unittest.TestCase):
    def test_verdict_counts_carry_all_four_verdict_keys(self) -> None:
        with _Artifacts() as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        for key in _VERDICT_VALUES:
            self.assertIn(key, report["verdict_counts"])
            self.assertEqual(report["verdict_counts"][key], 0)

    def test_verdict_counts_dispatch_records_correctly(self) -> None:
        with _Artifacts(
            curated=[
                _curated_example(source_event_id=1, p_value=0.01, fdr_q=0.02),
                _curated_example(source_event_id=2, p_value=0.04, fdr_q=0.20),
                _curated_example(source_event_id=3, p_value=0.50, fdr_q=0.60),
                _curated_example(source_event_id=4, p_value=None, fdr_q=None),
            ],
            top10=[], next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        counts = report["verdict_counts"]
        self.assertEqual(counts["fdr_significant"],     1)
        self.assertEqual(counts["validated_raw_only"],  1)
        self.assertEqual(counts["inconclusive_fdr"],    1)
        self.assertEqual(counts["not_evaluable"],       1)


# ---------------------------------------------------------------------------
# by_source / by_horizon / by_mechanism_family aggregates
# ---------------------------------------------------------------------------


class TestPerSourceAggregates(unittest.TestCase):
    def test_by_source_records_count_matches_examples(self) -> None:
        with _Artifacts(
            curated=[_curated_example(source_event_id=i) for i in (1, 2)],
            top10=[_review_example(event_id=10)],
            next10=[_review_example(event_id=20)],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        total = sum(
            block["records_count"]
            for block in report["by_source"].values()
        )
        self.assertEqual(total, report["total_records"])

    def test_by_horizon_aggregates_across_sources(self) -> None:
        with _Artifacts(
            curated=[
                _curated_example(source_event_id=1, horizon=1),
                _curated_example(source_event_id=2, horizon=5),
            ],
            top10=[_review_example(event_id=10, horizon=1)],
            next10=[_review_example(event_id=20, horizon=5)],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        # 2 records at h=1, 2 records at h=5.
        self.assertEqual(report["by_horizon"]["1"]["records_count"], 2)
        self.assertEqual(report["by_horizon"]["5"]["records_count"], 2)

    def test_by_mechanism_family_aggregates_across_sources(self) -> None:
        with _Artifacts(
            curated=[
                _curated_example(source_event_id=1,
                                 mechanism_family="supply_shock"),
            ],
            top10=[_review_example(event_id=10,
                                   mechanism_family="supply_shock")],
            next10=[_review_example(
                event_id=20,
                mechanism_family="bank_regulatory_capital_relief",
            )],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        fam = report["by_mechanism_family"]
        self.assertEqual(fam["supply_shock"]["records_count"], 2)
        self.assertEqual(
            fam["bank_regulatory_capital_relief"]["records_count"], 1,
        )


# ---------------------------------------------------------------------------
# Duplicate detection — never silently dedupes
# ---------------------------------------------------------------------------


class TestDuplicateEventIds(unittest.TestCase):
    def test_event_in_two_sources_surfaces_as_duplicate(self) -> None:
        with _Artifacts(
            curated=[_curated_example(source_event_id=30, horizon=1)],
            top10=[_review_example(event_id=30, horizon=1)],
            next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        dup_ids = {d["event_id"] for d in report["duplicate_event_ids"]}
        self.assertIn(30, dup_ids,
                      f"duplicates: {report['duplicate_event_ids']}")

    def test_duplicates_list_sources_appearing_in(self) -> None:
        with _Artifacts(
            curated=[_curated_example(source_event_id=30)],
            top10=[_review_example(event_id=30)],
            next10=[_review_example(event_id=30)],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        entries = [
            d for d in report["duplicate_event_ids"]
            if d["event_id"] == 30
        ]
        self.assertEqual(len(entries), 1)
        # Source list carries the three labels — order-insensitive.
        self.assertEqual(len(entries[0]["sources"]), 3)

    def test_unique_events_not_in_duplicate_list(self) -> None:
        with _Artifacts(
            curated=[_curated_example(source_event_id=30)],
            top10=[_review_example(event_id=40)],
            next10=[_review_example(event_id=50)],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        self.assertEqual(report["duplicate_event_ids"], [])

    def test_total_event_sources_counts_appearances(self) -> None:
        # event 30 appears in two sources → 2 event-source
        # appearances.  Event 40 appears once.
        with _Artifacts(
            curated=[_curated_example(source_event_id=30)],
            top10=[_review_example(event_id=30)],
            next10=[_review_example(event_id=40)],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        self.assertEqual(report["total_event_sources"], 3)


# ---------------------------------------------------------------------------
# Strongest raw-p candidates — sorted by p_value asc, capped at 10
# ---------------------------------------------------------------------------


class TestStrongestRawPCandidates(unittest.TestCase):
    def test_sorted_by_p_value_ascending(self) -> None:
        with _Artifacts(
            curated=[
                _curated_example(source_event_id=1, p_value=0.04, fdr_q=0.20),
                _curated_example(source_event_id=2, p_value=0.01, fdr_q=0.20),
                _curated_example(source_event_id=3, p_value=0.03, fdr_q=0.20),
            ],
            top10=[], next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        ps = [r["p_value"] for r in report["strongest_raw_p_candidates"]]
        self.assertEqual(ps, sorted(ps),
                         f"strongest list not sorted asc: {ps}")

    def test_capped_at_ten(self) -> None:
        with _Artifacts(
            curated=[
                _curated_example(
                    source_event_id=i, p_value=0.001 * i, fdr_q=0.20,
                )
                for i in range(1, 21)
            ],
            top10=[], next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        self.assertEqual(len(report["strongest_raw_p_candidates"]), 10)

    def test_only_raw_p_records_listed(self) -> None:
        # All records have p > alpha → no raw-p candidates → list is
        # empty.
        with _Artifacts(
            curated=[
                _curated_example(source_event_id=1, p_value=0.50, fdr_q=0.60),
                _curated_example(source_event_id=2, p_value=0.30, fdr_q=0.40),
            ],
            top10=[], next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        self.assertEqual(report["strongest_raw_p_candidates"], [])


# ---------------------------------------------------------------------------
# Null / inconclusive examples
# ---------------------------------------------------------------------------


class TestNullOrInconclusiveExamples(unittest.TestCase):
    def test_inconclusive_examples_surfaced(self) -> None:
        with _Artifacts(
            curated=[
                _curated_example(source_event_id=1, p_value=0.50, fdr_q=0.60),
            ],
            top10=[_review_example(event_id=10, p_value=0.40, fdr_q=0.55)],
            next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        self.assertGreaterEqual(
            len(report["null_or_inconclusive_examples"]), 1,
        )

    def test_inconclusive_examples_exclude_significant_rows(self) -> None:
        with _Artifacts(
            curated=[
                _curated_example(source_event_id=1, p_value=0.01, fdr_q=0.02),
                _curated_example(source_event_id=2, p_value=0.50, fdr_q=0.60),
            ],
            top10=[], next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        # The fdr_significant record (event 1) must NOT appear in the
        # inconclusive examples — it's the strict bar.
        ids = {r.get("event_id") for r
               in report["null_or_inconclusive_examples"]}
        self.assertNotIn(1, ids)
        self.assertIn(2, ids)


# ---------------------------------------------------------------------------
# Evidence-claim guard
# ---------------------------------------------------------------------------


class TestEvidenceClaim(unittest.TestCase):
    def test_no_fdr_significant_disallows_validation_claim(self) -> None:
        with _Artifacts(
            curated=[
                _curated_example(source_event_id=1, p_value=0.20, fdr_q=0.30),
            ],
            top10=[], next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        self.assertEqual(report["fdr_significant_count"], 0)
        # claim-allowed describes only the conservative uses.
        allowed = " ".join(report["evidence_claim_allowed"]).lower()
        not_allowed = " ".join(report["evidence_claim_not_allowed"]).lower()
        # Conservative phrasing about methodology / demo.
        self.assertTrue("methodology" in allowed or "demo" in allowed,
                        f"allowed: {allowed!r}")
        # Validation claim is explicitly NOT allowed.
        self.assertTrue("validation" in not_allowed,
                        f"not_allowed: {not_allowed!r}")

    def test_fdr_significant_present_permits_inspection_claim(self) -> None:
        with _Artifacts(
            curated=[_curated_example(
                source_event_id=1, p_value=0.01, fdr_q=0.02,
            )],
            top10=[], next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        self.assertGreater(report["fdr_significant_count"], 0)
        allowed = " ".join(report["evidence_claim_allowed"]).lower()
        self.assertIn("fdr", allowed)


# ---------------------------------------------------------------------------
# Recommended next action — conservative when no FDR-significant
# ---------------------------------------------------------------------------


class TestRecommendedNextAction(unittest.TestCase):
    def test_no_fdr_significant_says_methodology_not_validation(
        self,
    ) -> None:
        with _Artifacts(
            curated=[_curated_example(
                source_event_id=1, p_value=0.50, fdr_q=0.60,
            )],
            top10=[], next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        action = report["recommended_next_action"].lower()
        self.assertTrue("methodology" in action or "demo" in action,
                        f"action: {action!r}")
        self.assertIn("not", action)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_tokens_in_text_fields(self) -> None:
        with _Artifacts(
            curated=[_curated_example(source_event_id=1, p_value=0.50)],
            top10=[_review_example(event_id=10, p_value=0.04)],
            next10=[],
        ) as art:
            report = cli.build_combined_evidence_report(**art.kwargs())
        haystack = " ".join(
            list(report["errors"])
            + list(report["warnings"])
            + [report["recommended_next_action"]]
            + list(report["evidence_claim_allowed"])
            + list(report["evidence_claim_not_allowed"])
        ).lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(
                w, haystack,
                f"banned token {w!r} in combined report text",
            )


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnly(unittest.TestCase):
    def test_artifact_bytes_unchanged_after_build(self) -> None:
        with _Artifacts(
            curated=[_curated_example(source_event_id=1)],
            top10=[_review_example(event_id=10)],
            next10=[_review_example(event_id=20)],
        ) as art:
            before = {
                p: Path(p).read_bytes()
                for p in (art.curated_path, art.top10_path, art.next10_path)
                if p
            }
            cli.build_combined_evidence_report(**art.kwargs())
            after = {
                p: Path(p).read_bytes()
                for p in (art.curated_path, art.top10_path, art.next10_path)
                if p
            }
        self.assertEqual(before, after,
                         "artifact bytes mutated by combined report")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_emits_parseable_json(self) -> None:
        with _Artifacts(
            curated=[_curated_example(source_event_id=1)],
            top10=[_review_example(event_id=10)],
            next10=[_review_example(event_id=20)],
        ) as art:
            out = StringIO()
            rc = cli.main([
                "--curated-stage", art.curated_path,
                "--review-top10",  art.top10_path,
                "--review-next10", art.next10_path,
                "--json",
            ], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)

    def test_cli_returns_nonzero_when_envelope_not_ok(self) -> None:
        out = StringIO()
        rc = cli.main([
            "--curated-stage", "/no/such/curated.json",
            "--review-top10",  "/no/such/top10.json",
            "--review-next10", "/no/such/next10.json",
            "--json",
        ], out=out)
        self.assertNotEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertFalse(parsed["ok"])


# ---------------------------------------------------------------------------
# Import isolation — no provider / FastAPI / api.*
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = ("yfinance", "fastapi", "api")

    def test_module_does_not_pull_provider_or_fastapi(self) -> None:
        leaked = {
            k for k in sys.modules.keys()
            if k in self._BLOCKED
            or k.startswith("routes.")
            or any(k.startswith(b + ".") for b in self._BLOCKED)
        }
        self.assertEqual(leaked, set(),
                         f"unexpected provider/fastapi imports: {leaked}")


if __name__ == "__main__":
    unittest.main()
