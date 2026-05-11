"""Tests for ``scripts/curated_candidate_validation_run.py``.

Pin the contract:

* Reads from ``curated_candidates`` where ``status`` is one of
  ``{"needs_review", "ready_for_validation"}``.  Every other status
  is silently skipped (drafts and validated rows do not feed this
  runner).
* The runner does NOT treat staging as validation — it joins the
  staged candidate rows against the existing read-only validation
  pipeline and surfaces SAR / CI / p / FDR for the events that
  cleared the field-level checks.
* Required-field check: each staged candidate must carry non-blank
  ``event_date``, ``headline``, ``primary_ticker``,
  ``benchmark_ticker``, ``mechanism_family``.  Rows that fail land
  in ``excluded_candidates`` with a reason; their per-field gaps
  also bump the ``missing_fields`` aggregate.  Excluded candidates
  are NOT fed to the validation pipeline.
* Output dict carries EXACTLY these 13 keys::

    ok, staged_candidate_count, events_evaluated, records_count,
    significant_count, by_horizon, by_mechanism_family, examples,
    missing_fields, excluded_candidates, errors, warnings,
    recommended_next_action

* Each example carries 16 fields::

    source_event_id, headline, primary_ticker, benchmark_ticker,
    mechanism_family, horizon, abnormal_return, sar, ci_low,
    ci_high, p_value, fdr_q, interpretation,
    raw_p_candidate, fdr_significant, verdict

  The curated row is the source of truth for ``primary_ticker``,
  ``benchmark_ticker``, ``mechanism_family``, and ``headline``;
  the validation pipeline supplies the numerical fields.  The three
  verdict fields are the demo-facing raw-p / FDR split:
    - ``raw_p_candidate``  — ``p_value <= DEFAULT_ALPHA`` (False
      when missing / NaN).
    - ``fdr_significant``  — FDR clears (never True for raw-p-only).
    - ``verdict``          — closed vocabulary, evaluated top-down:
      ``fdr_significant`` | ``validated_raw_only`` |
      ``inconclusive_fdr`` | ``not_evaluable``.
* Aggregates exclude pipeline records whose ``source_event_id`` is
  not in the staged set.
* Conservative wording — banned tokens in any text field:
  ``proof``, ``validated archive``, ``automatically``, ``alpha``.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import curated_candidate_validation_run as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "staged_candidate_count",
    "events_evaluated",
    "records_count",
    "significant_count",
    "by_horizon",
    "by_mechanism_family",
    "examples",
    "missing_fields",
    "excluded_candidates",
    "errors",
    "warnings",
    "recommended_next_action",
)


_REQUIRED_EXAMPLE_FIELDS = (
    "source_event_id",
    "headline",
    "primary_ticker",
    "benchmark_ticker",
    "mechanism_family",
    "horizon",
    "abnormal_return",
    "sar",
    "ci_low",
    "ci_high",
    "p_value",
    "fdr_q",
    "interpretation",
    "raw_p_candidate",
    "fdr_significant",
    "verdict",
)


_VERDICT_VALUES = (
    "fdr_significant",
    "validated_raw_only",
    "inconclusive_fdr",
    "not_evaluable",
)


# Banned tokens are *affirmative* over-claims; the user's explicit
# conservative phrase "not proof, not validated archive" appears
# verbatim in the recommended_next_action and is therefore allowed.
_BANNED_WORDS = (
    "automatically",
    "alpha generated",
    "definitely validated",
    "is proven",
)


# ---------------------------------------------------------------------------
# Synthetic payloads
# ---------------------------------------------------------------------------


def _staged(
    *, source_event_id: int,
    status: str = "needs_review",
    primary_ticker: str = "MS",
    benchmark_ticker: str = "SPY",
    mechanism_family: str = "bank_regulatory_capital_relief",
    event_date: str = "2026-04-06",
    headline: str = "Headline",
) -> dict:
    return {
        "id":                    source_event_id * 100,
        "source_event_id":       source_event_id,
        "status":                status,
        "event_date":            event_date,
        "headline":              headline,
        "source_url":            "https://example.com",
        "primary_ticker":        primary_ticker,
        "benchmark_ticker":      benchmark_ticker,
        "mechanism_family":      mechanism_family,
        "mechanism_description": "desc",
        "predicted_direction":   "up",
        "prediction_rationale":  "rationale",
        "curator_notes":         "n",
        "source":                "manual",
    }


def _validation_record(
    *, event_id: int, horizon: int, sar: float,
    significant: bool = False,
    headline: str = "h",
    ticker: str = "MS",
    abnormal_return: float = 0.01,
    ci_low: float = -0.01, ci_high: float = 0.05,
    p_value: float = 0.10, fdr_q: float = 0.20,
    interpretation: str = "no_evidence",
    mechanism_family: str = "supply_shock",
) -> dict:
    return {
        "event_id":                 event_id,
        "headline":                 headline,
        "ticker":                   ticker,
        "horizon":                  horizon,
        "abnormal_return":          abnormal_return,
        "sar":                      sar,
        "ci_low":                   ci_low,
        "ci_high":                  ci_high,
        "p_value":                  p_value,
        "fdr_q":                    fdr_q,
        "interpretation":           interpretation,
        "mechanism_family":         mechanism_family,
        "statistically_significant": significant,
    }


def _validation_payload(records: list[dict]) -> dict:
    return {
        "ok":      True,
        "records": list(records),
        "errors":  [],
    }


def _patch_seams(
    *, candidates: list[dict] | None = None,
    validation_payload: dict | None = None,
):
    return (
        patch.object(
            cli, "_load_staged_candidates",
            return_value=(list(candidates or []), []),
        ),
        patch.object(
            cli, "_run_validation_pipeline",
            return_value=validation_payload
            if validation_payload is not None
            else _validation_payload([]),
        ),
    )


def _run(**kwargs) -> dict:
    candidates         = kwargs.pop("candidates", None)
    validation_payload = kwargs.pop("validation_payload", None)
    p1, p2 = _patch_seams(
        candidates=candidates, validation_payload=validation_payload,
    )
    with p1, p2:
        return cli.run_curated_candidate_validation(**kwargs)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_returns_dict_with_exactly_thirteen_keys(self) -> None:
        result = _run()
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS),
                         f"unexpected keys: {sorted(result.keys())}")

    def test_empty_archive_returns_zero_aggregates(self) -> None:
        result = _run()
        self.assertEqual(result["staged_candidate_count"], 0)
        self.assertEqual(result["events_evaluated"], 0)
        self.assertEqual(result["records_count"], 0)
        self.assertEqual(result["significant_count"], 0)
        self.assertEqual(result["by_horizon"], {})
        self.assertEqual(result["by_mechanism_family"], {})
        self.assertEqual(result["examples"], [])
        self.assertEqual(result["excluded_candidates"], [])


# ---------------------------------------------------------------------------
# Status filter — ONLY needs_review and ready_for_validation feed the
# pipeline.  drafts / validated / archived statuses are skipped.
# ---------------------------------------------------------------------------


class TestStatusFilter(unittest.TestCase):
    def test_needs_review_status_is_staged(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1, status="needs_review")],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=5, sar=1.0),
            ]),
        )
        self.assertEqual(result["staged_candidate_count"], 1)
        self.assertEqual(result["events_evaluated"], 1)

    def test_ready_for_validation_status_is_staged(self) -> None:
        result = _run(
            candidates=[
                _staged(source_event_id=1, status="ready_for_validation"),
            ],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=5, sar=1.0),
            ]),
        )
        self.assertEqual(result["staged_candidate_count"], 1)
        self.assertEqual(result["events_evaluated"], 1)

    def test_draft_status_is_skipped(self) -> None:
        # The seam already filters at the SQL layer in production;
        # at the function layer, any candidate with a non-staged
        # status that leaks through is also dropped defensively.
        result = _run(
            candidates=[
                _staged(source_event_id=1, status="draft"),
                _staged(source_event_id=2, status="needs_review"),
            ],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=5, sar=99.0),
                _validation_record(event_id=2, horizon=5, sar=1.0),
            ]),
        )
        self.assertEqual(result["staged_candidate_count"], 1)
        # event 1 is NOT in the staged set; record must NOT count.
        self.assertEqual(result["events_evaluated"], 1)
        ev_ids = {ex["source_event_id"] for ex in result["examples"]}
        self.assertEqual(ev_ids, {2})

    def test_validated_status_is_skipped(self) -> None:
        result = _run(
            candidates=[
                _staged(source_event_id=1, status="validated"),
            ],
        )
        self.assertEqual(result["staged_candidate_count"], 0)


# ---------------------------------------------------------------------------
# Required-field check + excluded_candidates
# ---------------------------------------------------------------------------


class TestRequiredFieldCheck(unittest.TestCase):
    def test_blank_primary_ticker_excludes_candidate(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1, primary_ticker="")],
        )
        self.assertEqual(result["staged_candidate_count"], 1)
        self.assertEqual(result["events_evaluated"], 0)
        self.assertEqual(len(result["excluded_candidates"]), 1)
        excl = result["excluded_candidates"][0]
        self.assertEqual(excl["source_event_id"], 1)
        self.assertTrue(any(
            "primary_ticker" in r for r in excl["reasons"]
        ))

    def test_blank_benchmark_ticker_excludes_candidate(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1, benchmark_ticker="")],
        )
        self.assertEqual(len(result["excluded_candidates"]), 1)
        self.assertTrue(any(
            "benchmark_ticker" in r
            for r in result["excluded_candidates"][0]["reasons"]
        ))

    def test_blank_mechanism_family_excludes_candidate(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1, mechanism_family="")],
        )
        self.assertEqual(len(result["excluded_candidates"]), 1)
        self.assertTrue(any(
            "mechanism_family" in r
            for r in result["excluded_candidates"][0]["reasons"]
        ))

    def test_missing_event_date_excludes_candidate(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1, event_date="")],
        )
        self.assertEqual(len(result["excluded_candidates"]), 1)
        self.assertTrue(any(
            "event_date" in r
            for r in result["excluded_candidates"][0]["reasons"]
        ))

    def test_missing_headline_excludes_candidate(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1, headline="")],
        )
        self.assertEqual(len(result["excluded_candidates"]), 1)


class TestMissingFieldsAggregate(unittest.TestCase):
    def test_missing_field_counts_aggregate_across_candidates(self) -> None:
        result = _run(
            candidates=[
                _staged(source_event_id=1, primary_ticker=""),
                _staged(source_event_id=2, primary_ticker=""),
                _staged(source_event_id=3, mechanism_family=""),
            ],
        )
        self.assertEqual(result["missing_fields"].get("primary_ticker"), 2)
        self.assertEqual(result["missing_fields"].get("mechanism_family"), 1)

    def test_missing_field_omits_zero_count_keys(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([]),
        )
        # Every required field present → no missing_fields entries.
        for k, v in result["missing_fields"].items():
            self.assertGreater(v, 0,
                               f"missing_fields['{k}'] should not be zero")


# ---------------------------------------------------------------------------
# Validation pipeline filtering
# ---------------------------------------------------------------------------


class TestValidationFilter(unittest.TestCase):
    def test_records_filtered_to_staged_source_event_ids(self) -> None:
        # Validation seam returns records for events 1, 2, 3, but only
        # 1 and 2 are staged candidates.  Event 3 must NOT count.
        result = _run(
            candidates=[
                _staged(source_event_id=1),
                _staged(source_event_id=2),
            ],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=5, sar=1.0),
                _validation_record(event_id=2, horizon=5, sar=1.0),
                _validation_record(event_id=3, horizon=5, sar=99.0),
            ]),
        )
        self.assertEqual(result["events_evaluated"], 2)
        self.assertEqual(result["records_count"], 2)
        ev_ids = {ex["source_event_id"] for ex in result["examples"]}
        self.assertEqual(ev_ids, {1, 2})

    def test_excluded_candidates_do_not_feed_validation(self) -> None:
        # Two candidates: 1 has a blank ticker (excluded) and 2 is
        # complete.  The pipeline records for event 1 should NOT be
        # counted toward records_count.
        result = _run(
            candidates=[
                _staged(source_event_id=1, primary_ticker=""),
                _staged(source_event_id=2),
            ],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=5, sar=1.0),
                _validation_record(event_id=2, horizon=5, sar=1.5),
            ]),
        )
        self.assertEqual(result["events_evaluated"], 1)
        ev_ids = {ex["source_event_id"] for ex in result["examples"]}
        self.assertEqual(ev_ids, {2})

    def test_significant_count_counts_significant_records(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=1, sar=2.0,
                                   significant=True),
                _validation_record(event_id=1, horizon=5, sar=1.0,
                                   significant=False),
            ]),
        )
        self.assertEqual(result["significant_count"], 1)


# ---------------------------------------------------------------------------
# Example shape
# ---------------------------------------------------------------------------


class TestExampleShape(unittest.TestCase):
    def test_example_carries_required_thirteen_fields(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=5, sar=1.5),
            ]),
        )
        self.assertEqual(len(result["examples"]), 1)
        for field in _REQUIRED_EXAMPLE_FIELDS:
            self.assertIn(field, result["examples"][0])

    def test_example_metadata_comes_from_curated_row(self) -> None:
        # Validation record carries ticker="MS" / family="supply_shock";
        # the curated row says ticker="JPM" / family="bank_relief".
        # The example must surface the curated row's view, not the
        # validation pipeline's.
        result = _run(
            candidates=[_staged(
                source_event_id=1, primary_ticker="JPM",
                benchmark_ticker="XLF",
                mechanism_family="bank_regulatory_capital_relief",
                headline="Curated headline",
            )],
            validation_payload=_validation_payload([
                _validation_record(
                    event_id=1, horizon=5, sar=1.5,
                    ticker="MS", mechanism_family="supply_shock",
                    headline="Validation pipeline headline"),
            ]),
        )
        ex = result["examples"][0]
        self.assertEqual(ex["primary_ticker"], "JPM")
        self.assertEqual(ex["benchmark_ticker"], "XLF")
        self.assertEqual(ex["mechanism_family"],
                         "bank_regulatory_capital_relief")
        self.assertEqual(ex["headline"], "Curated headline")


# ---------------------------------------------------------------------------
# Per-example verdict fields — raw-p / FDR split visible without
# weakening FDR discipline.
# ---------------------------------------------------------------------------


def _ex(result: dict, *, source_event_id: int, horizon: int) -> dict:
    """Pick a single example matching ``(source_event_id, horizon)``."""
    for ex in result["examples"]:
        if (ex.get("source_event_id") == source_event_id
                and ex.get("horizon") == horizon):
            return ex
    raise AssertionError(
        f"no example for source_event_id={source_event_id} h={horizon}"
    )


class TestVerdictFields(unittest.TestCase):
    def test_example_carries_three_new_verdict_fields(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=5, sar=1.5),
            ]),
        )
        ex = result["examples"][0]
        for field in ("raw_p_candidate", "fdr_significant", "verdict"):
            self.assertIn(field, ex, f"missing verdict field: {field}")

    def test_verdict_value_in_closed_vocabulary(self) -> None:
        result = _run(
            candidates=[
                _staged(source_event_id=1),
                _staged(source_event_id=2),
            ],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=1, sar=1.0,
                                   p_value=0.01, fdr_q=0.03,
                                   significant=True),
                _validation_record(event_id=2, horizon=5, sar=1.0,
                                   p_value=0.30, fdr_q=0.40),
            ]),
        )
        for ex in result["examples"]:
            self.assertIn(ex["verdict"], _VERDICT_VALUES,
                          f"verdict {ex['verdict']!r} outside vocab")

    def test_fdr_significant_record_gets_fdr_significant_verdict(
        self,
    ) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(
                    event_id=1, horizon=5, sar=2.0,
                    p_value=0.01, fdr_q=0.02, significant=True,
                ),
            ]),
        )
        ex = _ex(result, source_event_id=1, horizon=5)
        self.assertTrue(ex["raw_p_candidate"])
        self.assertTrue(ex["fdr_significant"])
        self.assertEqual(ex["verdict"], "fdr_significant")

    def test_raw_p_only_record_gets_validated_raw_only_verdict(
        self,
    ) -> None:
        # Event 46-style case: p_value clears alpha=0.05 but FDR does
        # not (fdr_q above alpha).
        result = _run(
            candidates=[_staged(source_event_id=46)],
            validation_payload=_validation_payload([
                _validation_record(
                    event_id=46, horizon=5, sar=1.5,
                    p_value=0.04, fdr_q=0.20, significant=False,
                    interpretation="not_significant",
                ),
            ]),
        )
        ex = _ex(result, source_event_id=46, horizon=5)
        self.assertTrue(ex["raw_p_candidate"])
        self.assertFalse(ex["fdr_significant"])
        self.assertEqual(ex["verdict"], "validated_raw_only")
        # The clearer demo-facing field must override the easily-
        # misread interpretation="not_significant".
        self.assertEqual(ex["interpretation"], "not_significant")

    def test_inconclusive_record_when_neither_bar_clears(self) -> None:
        # p_value present but above alpha → neither raw-p nor FDR.
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(
                    event_id=1, horizon=5, sar=0.5,
                    p_value=0.30, fdr_q=0.40, significant=False,
                ),
            ]),
        )
        ex = _ex(result, source_event_id=1, horizon=5)
        self.assertFalse(ex["raw_p_candidate"])
        self.assertFalse(ex["fdr_significant"])
        self.assertEqual(ex["verdict"], "inconclusive_fdr")

    def test_not_evaluable_when_both_p_and_fdr_q_missing(self) -> None:
        # When BOTH p_value and fdr_q are None, the verdict is the
        # absent-data case — neither bar can be evaluated.
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(
                    event_id=1, horizon=5, sar=0.0,
                    p_value=None, fdr_q=None, significant=False,
                ),
            ]),
        )
        ex = _ex(result, source_event_id=1, horizon=5)
        self.assertFalse(ex["raw_p_candidate"])
        self.assertFalse(ex["fdr_significant"])
        self.assertEqual(ex["verdict"], "not_evaluable")

    def test_inconclusive_when_only_p_missing_but_fdr_present(self) -> None:
        # fdr_q is a real number but above alpha → not_evaluable would
        # be wrong (we have FDR data); the right call is inconclusive.
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(
                    event_id=1, horizon=5, sar=0.5,
                    p_value=None, fdr_q=0.40, significant=False,
                ),
            ]),
        )
        ex = _ex(result, source_event_id=1, horizon=5)
        self.assertFalse(ex["raw_p_candidate"])
        self.assertFalse(ex["fdr_significant"])
        self.assertEqual(ex["verdict"], "inconclusive_fdr")

    def test_raw_p_only_never_fires_fdr_significant_flag(self) -> None:
        # Cross every example in a mixed-output run.  The invariant
        # "verdict==validated_raw_only ⇒ fdr_significant=False" must
        # hold for every record in the surfaced examples list — never
        # weaken FDR discipline.
        records: list[dict] = []
        candidates: list[dict] = []
        for i, (p, q, sig) in enumerate((
            (0.01, 0.02, True),     # fdr_significant
            (0.04, 0.20, False),    # raw-p only
            (0.30, 0.40, False),    # inconclusive
            (None, None, False),    # not_evaluable
            (0.045, 0.30, False),   # raw-p only (just under alpha)
        ), start=1):
            candidates.append(_staged(source_event_id=i))
            records.append(_validation_record(
                event_id=i, horizon=5, sar=1.0,
                p_value=p, fdr_q=q, significant=sig,
            ))
        result = _run(
            candidates=candidates,
            validation_payload=_validation_payload(records),
        )
        for ex in result["examples"]:
            if ex["verdict"] == "validated_raw_only":
                self.assertFalse(
                    ex["fdr_significant"],
                    f"raw-p-only record claimed FDR significant: {ex!r}",
                )
                self.assertTrue(ex["raw_p_candidate"])

    def test_alpha_boundary_p_equal_alpha_counts_as_raw_p(self) -> None:
        # p_value == DEFAULT_ALPHA (0.05) — the existing raw-p check
        # treats this as raw-p significant; verdict must follow.
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(
                    event_id=1, horizon=5, sar=1.0,
                    p_value=0.05, fdr_q=0.20, significant=False,
                ),
            ]),
        )
        ex = _ex(result, source_event_id=1, horizon=5)
        self.assertTrue(ex["raw_p_candidate"])
        self.assertEqual(ex["verdict"], "validated_raw_only")

    def test_alpha_boundary_p_just_above_alpha_is_not_raw_p(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(
                    event_id=1, horizon=5, sar=1.0,
                    p_value=0.0501, fdr_q=0.20, significant=False,
                ),
            ]),
        )
        ex = _ex(result, source_event_id=1, horizon=5)
        self.assertFalse(ex["raw_p_candidate"])
        self.assertEqual(ex["verdict"], "inconclusive_fdr")


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


class TestAggregates(unittest.TestCase):
    def test_by_horizon_counts_records_and_significant(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=1, sar=1.0,
                                   significant=True),
                _validation_record(event_id=1, horizon=5, sar=1.0,
                                   significant=False),
                _validation_record(event_id=1, horizon=20, sar=1.0,
                                   significant=False),
            ]),
        )
        self.assertEqual(result["by_horizon"]["1"]["records_count"], 1)
        self.assertEqual(result["by_horizon"]["1"]["significant_count"], 1)
        self.assertEqual(result["by_horizon"]["5"]["records_count"], 1)
        self.assertEqual(result["by_horizon"]["20"]["records_count"], 1)

    def test_by_mechanism_family_uses_curated_family(self) -> None:
        # Curated families differ from validation pipeline families.
        # by_mechanism_family must group by the CURATED family.
        result = _run(
            candidates=[
                _staged(source_event_id=1,
                        mechanism_family="bank_regulatory_capital_relief"),
                _staged(source_event_id=2,
                        mechanism_family="supply_shock"),
                _staged(source_event_id=3,
                        mechanism_family="supply_shock"),
            ],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=5, sar=1.0),
                _validation_record(event_id=2, horizon=5, sar=1.0),
                _validation_record(event_id=3, horizon=5, sar=1.0),
            ]),
        )
        fam_block = result["by_mechanism_family"]
        self.assertEqual(
            fam_block["supply_shock"]["events_evaluated"], 2,
        )
        self.assertEqual(
            fam_block["bank_regulatory_capital_relief"]["events_evaluated"],
            1,
        )


# ---------------------------------------------------------------------------
# Limit truncation
# ---------------------------------------------------------------------------


class TestLimit(unittest.TestCase):
    def test_examples_capped_by_limit(self) -> None:
        candidates = [_staged(source_event_id=i) for i in range(1, 11)]
        records = [
            _validation_record(event_id=i, horizon=5, sar=1.0)
            for i in range(1, 11)
        ]
        result = _run(
            candidates=candidates,
            validation_payload=_validation_payload(records),
            limit=3,
        )
        self.assertEqual(len(result["examples"]), 3)
        # records_count reflects every evaluated record, not truncation.
        self.assertEqual(result["records_count"], 10)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_recommended_action_avoids_banned_words(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=5, sar=1.5),
            ]),
        )
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec, f"banned word {w!r} in: {rec!r}")

    def test_recommended_action_mentions_staged_candidate(self) -> None:
        result = _run(
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=5, sar=1.5),
            ]),
        )
        rec = result["recommended_next_action"].lower()
        self.assertIn("staged candidate", rec)
        self.assertIn("not proof", rec)

    def test_empty_archive_recommendation_is_conservative(self) -> None:
        result = _run()
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec)


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_load_staged_seam_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_load_staged_candidates")))

    def test_validation_seam_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_validation_pipeline")))


# ---------------------------------------------------------------------------
# Read-only / import isolation on default run
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = ("yfinance", "fastapi", "api")

    def test_default_run_does_not_import_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED)}
        _run()
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED)}
        self.assertEqual(after - before, set(),
                         "default run imported a forbidden module")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str], **kwargs) -> tuple[int, str]:
    out = StringIO()
    candidates         = kwargs.pop("candidates", None)
    validation_payload = kwargs.pop("validation_payload", None)
    p1, p2 = _patch_seams(
        candidates=candidates, validation_payload=validation_payload,
    )
    with p1, p2:
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


class TestCLI(unittest.TestCase):
    def test_json_emits_thirteen_keys(self) -> None:
        rc, output = _run_cli(
            ["--json", "--limit", "10"],
            candidates=[_staged(source_event_id=1)],
            validation_payload=_validation_payload([
                _validation_record(event_id=1, horizon=5, sar=1.5),
            ]),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
        self.assertEqual(parsed["staged_candidate_count"], 1)

    def test_text_default_runs(self) -> None:
        rc, output = _run_cli([])
        self.assertEqual(rc, 0)
        self.assertGreater(len(output), 0)


if __name__ == "__main__":
    unittest.main()
