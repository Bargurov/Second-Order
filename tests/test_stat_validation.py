"""Tests for ``stats/stat_validation.py``.

Pure schema module — no DB, no UI, no provider.  The tests pin the
contract of the validation record (field set, derived fields, vocabulary)
and the layered sub-schemas that compose it: event-study, confidence
interval, and FDR.

What we pin
-----------
* ``STAT_VALIDATION_FIELDS`` is the canonical 9-field tuple every
  payload exposes — order matters because downstream consumers may
  iterate it for stable rendering.
* Each sub-schema (``make_event_study_fields``, ``make_ci_fields``,
  ``make_fdr_fields``) returns its slice of the record so a caller
  with partial data can still build a valid envelope.
* ``make_stat_validation_record`` composes the three slices and adds
  the two derived fields (``statistically_significant``,
  ``interpretation``) using a fixed vocabulary.
* Significance is mechanical: ``fdr_q < alpha`` (default 0.05).  CI
  bounds are ancillary — they do not feed the bool.
* Interpretation has exactly four labels — the
  ``INTERPRETATIONS`` tuple is pinned so a downstream consumer can
  branch deterministically.
* The factory rejects malformed inputs (negative horizon, ci_low >
  ci_high, p_value or fdr_q outside [0, 1], non-positive alpha).
* NaN is normalized to ``None`` so the record stays JSON-serializable
  without ``allow_nan=True``.
"""
from __future__ import annotations

import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stats import stat_validation as sv  # noqa: E402


# ---------------------------------------------------------------------------
# Fixed-shape contract
# ---------------------------------------------------------------------------


class TestFieldShape(unittest.TestCase):
    def test_canonical_field_set_is_pinned(self) -> None:
        # The 9 fields the spec lists must be present in this exact
        # order — downstream consumers iterate this tuple for stable
        # rendering and the order is part of the contract.
        self.assertEqual(sv.STAT_VALIDATION_FIELDS, (
            "horizon",
            "abnormal_return",
            "sar",
            "car",
            "ci_low",
            "ci_high",
            "p_value",
            "fdr_q",
            "statistically_significant",
            "interpretation",
        ))

    def test_default_alpha_is_five_percent(self) -> None:
        self.assertEqual(sv.DEFAULT_ALPHA, 0.05)

    def test_interpretation_vocabulary_is_pinned(self) -> None:
        # Exactly four labels — significant_positive,
        # significant_negative, not_significant, insufficient_data.
        # Adding a label is a contract change, not a quiet rollout.
        self.assertEqual(set(sv.INTERPRETATIONS), {
            "significant_positive",
            "significant_negative",
            "not_significant",
            "insufficient_data",
        })


# ---------------------------------------------------------------------------
# Sub-schemas — event-study slice
# ---------------------------------------------------------------------------


class TestEventStudyFields(unittest.TestCase):
    def test_returns_three_keys(self) -> None:
        fields = sv.make_event_study_fields(
            horizon=20, abnormal_return=0.034, sar=2.1,
        )
        self.assertEqual(set(fields.keys()), {"horizon", "abnormal_return", "sar"})

    def test_values_pass_through(self) -> None:
        fields = sv.make_event_study_fields(
            horizon=20, abnormal_return=0.034, sar=2.1,
        )
        self.assertEqual(fields["horizon"],         20)
        self.assertAlmostEqual(fields["abnormal_return"], 0.034)
        self.assertAlmostEqual(fields["sar"],             2.1)

    def test_horizon_must_be_positive_int(self) -> None:
        for bad_horizon in (0, -1, -5):
            with self.assertRaises(ValueError, msg=f"horizon={bad_horizon}"):
                sv.make_event_study_fields(
                    horizon=bad_horizon, abnormal_return=0.0, sar=0.0,
                )

    def test_horizon_must_be_int_not_float(self) -> None:
        # Horizons are bar counts — fractional bars are nonsense.
        with self.assertRaises(ValueError):
            sv.make_event_study_fields(
                horizon=1.5, abnormal_return=0.0, sar=0.0,
            )

    def test_optional_numeric_fields_accept_none(self) -> None:
        fields = sv.make_event_study_fields(
            horizon=20, abnormal_return=None, sar=None,
        )
        self.assertIsNone(fields["abnormal_return"])
        self.assertIsNone(fields["sar"])

    def test_nan_normalized_to_none(self) -> None:
        # JSON does not natively support NaN — we normalize so a
        # downstream ``json.dumps`` works without ``allow_nan=True``.
        fields = sv.make_event_study_fields(
            horizon=20, abnormal_return=float("nan"), sar=float("nan"),
        )
        self.assertIsNone(fields["abnormal_return"])
        self.assertIsNone(fields["sar"])


# ---------------------------------------------------------------------------
# Sub-schemas — CI slice
# ---------------------------------------------------------------------------


class TestCiFields(unittest.TestCase):
    def test_returns_two_keys(self) -> None:
        fields = sv.make_ci_fields(ci_low=-0.01, ci_high=0.05)
        self.assertEqual(set(fields.keys()), {"ci_low", "ci_high"})

    def test_values_pass_through(self) -> None:
        fields = sv.make_ci_fields(ci_low=-0.01, ci_high=0.05)
        self.assertAlmostEqual(fields["ci_low"],  -0.01)
        self.assertAlmostEqual(fields["ci_high"],  0.05)

    def test_low_above_high_raises(self) -> None:
        with self.assertRaises(ValueError):
            sv.make_ci_fields(ci_low=0.10, ci_high=0.05)

    def test_equal_bounds_accepted(self) -> None:
        # Degenerate but well-formed — a point estimate with zero
        # variance still has ci_low == ci_high.
        fields = sv.make_ci_fields(ci_low=0.05, ci_high=0.05)
        self.assertEqual(fields["ci_low"], fields["ci_high"])

    def test_either_bound_may_be_none(self) -> None:
        # Partial data still composes — the upstream may have a low
        # bound estimate but no upper.  Bound comparison is skipped
        # when either side is missing.
        fields = sv.make_ci_fields(ci_low=None, ci_high=0.05)
        self.assertIsNone(fields["ci_low"])
        self.assertEqual(fields["ci_high"], 0.05)
        fields = sv.make_ci_fields(ci_low=-0.01, ci_high=None)
        self.assertEqual(fields["ci_low"], -0.01)
        self.assertIsNone(fields["ci_high"])

    def test_nan_bounds_normalized_to_none(self) -> None:
        fields = sv.make_ci_fields(
            ci_low=float("nan"), ci_high=float("nan"),
        )
        self.assertIsNone(fields["ci_low"])
        self.assertIsNone(fields["ci_high"])


# ---------------------------------------------------------------------------
# Sub-schemas — FDR slice
# ---------------------------------------------------------------------------


class TestFdrFields(unittest.TestCase):
    def test_returns_two_keys(self) -> None:
        fields = sv.make_fdr_fields(p_value=0.01, fdr_q=0.03)
        self.assertEqual(set(fields.keys()), {"p_value", "fdr_q"})

    def test_values_pass_through(self) -> None:
        fields = sv.make_fdr_fields(p_value=0.01, fdr_q=0.03)
        self.assertAlmostEqual(fields["p_value"], 0.01)
        self.assertAlmostEqual(fields["fdr_q"],   0.03)

    def test_p_value_outside_unit_interval_raises(self) -> None:
        for bad in (-0.01, 1.5, 2.0):
            with self.assertRaises(ValueError, msg=f"p_value={bad}"):
                sv.make_fdr_fields(p_value=bad, fdr_q=0.05)

    def test_fdr_q_outside_unit_interval_raises(self) -> None:
        for bad in (-0.01, 1.5, 2.0):
            with self.assertRaises(ValueError, msg=f"fdr_q={bad}"):
                sv.make_fdr_fields(p_value=0.05, fdr_q=bad)

    def test_boundary_values_accepted(self) -> None:
        # p == 0 and p == 1 are valid extreme cases.  Same for q.
        fields = sv.make_fdr_fields(p_value=0.0, fdr_q=0.0)
        self.assertEqual(fields["p_value"], 0.0)
        self.assertEqual(fields["fdr_q"],   0.0)
        fields = sv.make_fdr_fields(p_value=1.0, fdr_q=1.0)
        self.assertEqual(fields["p_value"], 1.0)
        self.assertEqual(fields["fdr_q"],   1.0)

    def test_either_field_may_be_none(self) -> None:
        fields = sv.make_fdr_fields(p_value=None, fdr_q=None)
        self.assertIsNone(fields["p_value"])
        self.assertIsNone(fields["fdr_q"])


# ---------------------------------------------------------------------------
# is_statistically_significant
# ---------------------------------------------------------------------------


class TestSignificance(unittest.TestCase):
    def test_below_alpha_is_significant(self) -> None:
        self.assertTrue(sv.is_statistically_significant(0.01))
        self.assertTrue(sv.is_statistically_significant(0.049))

    def test_at_alpha_is_significant(self) -> None:
        # ``q <= alpha`` matches the BH discovery rule used elsewhere
        # in this package (see ``stats/fdr.py`` where the discovery
        # flag is ``adj <= alpha_f``).  Aligning here keeps the two
        # surfaces consistent so a row flagged as a BH discovery is
        # never relabeled "not significant" by this module.
        self.assertTrue(sv.is_statistically_significant(0.05))

    def test_above_alpha_is_not_significant(self) -> None:
        # Use a value just past the boundary — Python's float layout
        # makes 0.05 + 1e-12 strictly greater than 0.05.
        self.assertFalse(sv.is_statistically_significant(0.05 + 1e-12))
        self.assertFalse(sv.is_statistically_significant(0.10))
        self.assertFalse(sv.is_statistically_significant(0.99))

    def test_none_q_is_not_significant(self) -> None:
        self.assertFalse(sv.is_statistically_significant(None))

    def test_nan_q_is_not_significant(self) -> None:
        self.assertFalse(sv.is_statistically_significant(float("nan")))

    def test_custom_alpha_overrides_default(self) -> None:
        self.assertTrue(sv.is_statistically_significant(0.06, alpha=0.10))
        self.assertFalse(sv.is_statistically_significant(0.06, alpha=0.05))

    def test_alpha_outside_unit_interval_raises(self) -> None:
        # Half-open ``(0, 1]`` matches ``stats.fdr._validate_alpha``.
        # alpha == 1.0 is degenerate (every q passes) but accepted so
        # the two modules agree.
        for bad in (0.0, -0.1, 1.1, float("nan"), float("inf")):
            with self.assertRaises(ValueError, msg=f"alpha={bad}"):
                sv.is_statistically_significant(0.01, alpha=bad)

    def test_alpha_at_unit_upper_bound_accepted(self) -> None:
        # alpha=1.0 always declares significance for any valid q.
        self.assertTrue(sv.is_statistically_significant(0.99, alpha=1.0))


# ---------------------------------------------------------------------------
# Interpretation derivation
# ---------------------------------------------------------------------------


class TestInterpretation(unittest.TestCase):
    def test_significant_positive(self) -> None:
        label = sv.derive_interpretation(
            abnormal_return=0.05, statistically_significant=True,
        )
        self.assertEqual(label, "significant_positive")

    def test_significant_negative(self) -> None:
        label = sv.derive_interpretation(
            abnormal_return=-0.05, statistically_significant=True,
        )
        self.assertEqual(label, "significant_negative")

    def test_not_significant_positive_ar(self) -> None:
        label = sv.derive_interpretation(
            abnormal_return=0.05, statistically_significant=False,
        )
        self.assertEqual(label, "not_significant")

    def test_not_significant_negative_ar(self) -> None:
        label = sv.derive_interpretation(
            abnormal_return=-0.05, statistically_significant=False,
        )
        self.assertEqual(label, "not_significant")

    def test_insufficient_data_when_ar_is_none(self) -> None:
        label = sv.derive_interpretation(
            abnormal_return=None, statistically_significant=False,
        )
        self.assertEqual(label, "insufficient_data")

    def test_insufficient_data_overrides_significance(self) -> None:
        # Even if a caller force-passes statistically_significant=True
        # with a missing AR, we cannot label direction — fall back to
        # ``insufficient_data`` so the operator sees the absence.
        label = sv.derive_interpretation(
            abnormal_return=None, statistically_significant=True,
        )
        self.assertEqual(label, "insufficient_data")

    def test_insufficient_data_for_nan_ar(self) -> None:
        label = sv.derive_interpretation(
            abnormal_return=float("nan"), statistically_significant=True,
        )
        self.assertEqual(label, "insufficient_data")

    def test_zero_ar_with_significance_is_not_significant(self) -> None:
        # Significant test stat with a literal zero point estimate is
        # essentially impossible — picking ``not_significant`` is the
        # least-misleading label because there's no direction to
        # report.
        label = sv.derive_interpretation(
            abnormal_return=0.0, statistically_significant=True,
        )
        self.assertEqual(label, "not_significant")

    def test_returned_label_is_in_pinned_vocabulary(self) -> None:
        for ar in (0.05, -0.05, 0.0, None, float("nan")):
            for sig in (True, False):
                label = sv.derive_interpretation(
                    abnormal_return=ar, statistically_significant=sig,
                )
                self.assertIn(label, sv.INTERPRETATIONS)


# ---------------------------------------------------------------------------
# Composed record
# ---------------------------------------------------------------------------


class TestComposedRecord(unittest.TestCase):
    def _full_inputs(self, **overrides) -> dict:
        base = dict(
            horizon=20,
            abnormal_return=0.034,
            sar=2.1,
            ci_low=0.005,
            ci_high=0.063,
            p_value=0.012,
            fdr_q=0.03,
        )
        base.update(overrides)
        return base

    def test_record_contains_every_canonical_field(self) -> None:
        record = sv.make_stat_validation_record(**self._full_inputs())
        self.assertEqual(set(record.keys()), set(sv.STAT_VALIDATION_FIELDS))

    def test_record_key_order_matches_canonical_tuple(self) -> None:
        # Iteration order (Python 3.7+ preserves insertion) is the
        # contract — downstream consumers may stream key/value pairs
        # for stable rendering.
        record = sv.make_stat_validation_record(**self._full_inputs())
        self.assertEqual(
            tuple(record.keys()),
            sv.STAT_VALIDATION_FIELDS,
        )

    def test_event_study_slice_passes_through(self) -> None:
        record = sv.make_stat_validation_record(**self._full_inputs())
        self.assertEqual(record["horizon"],         20)
        self.assertAlmostEqual(record["abnormal_return"], 0.034)
        self.assertAlmostEqual(record["sar"],             2.1)

    def test_ci_slice_passes_through(self) -> None:
        record = sv.make_stat_validation_record(**self._full_inputs())
        self.assertAlmostEqual(record["ci_low"],  0.005)
        self.assertAlmostEqual(record["ci_high"], 0.063)

    def test_fdr_slice_passes_through(self) -> None:
        record = sv.make_stat_validation_record(**self._full_inputs())
        self.assertAlmostEqual(record["p_value"], 0.012)
        self.assertAlmostEqual(record["fdr_q"],   0.03)

    def test_significance_derived_from_fdr_q_and_default_alpha(self) -> None:
        record = sv.make_stat_validation_record(**self._full_inputs())
        # fdr_q = 0.03 < 0.05 → True
        self.assertTrue(record["statistically_significant"])

    def test_significance_false_when_q_above_alpha(self) -> None:
        record = sv.make_stat_validation_record(
            **self._full_inputs(fdr_q=0.20),
        )
        self.assertFalse(record["statistically_significant"])

    def test_significance_uses_q_not_p(self) -> None:
        # FDR-adjusted ``q`` controls significance.  The raw ``p``
        # may still be < alpha but a high q must dominate (this is
        # the whole point of FDR control).
        record = sv.make_stat_validation_record(
            **self._full_inputs(p_value=0.001, fdr_q=0.40),
        )
        self.assertFalse(record["statistically_significant"])

    def test_significance_respects_custom_alpha(self) -> None:
        # q=0.06 is significant at alpha=0.10 but not at default 0.05.
        record = sv.make_stat_validation_record(
            **self._full_inputs(fdr_q=0.06),
        )
        self.assertFalse(record["statistically_significant"])
        record = sv.make_stat_validation_record(
            **self._full_inputs(fdr_q=0.06), alpha=0.10,
        )
        self.assertTrue(record["statistically_significant"])

    def test_interpretation_significant_positive(self) -> None:
        record = sv.make_stat_validation_record(**self._full_inputs())
        self.assertEqual(record["interpretation"], "significant_positive")

    def test_interpretation_significant_negative(self) -> None:
        record = sv.make_stat_validation_record(
            **self._full_inputs(abnormal_return=-0.034,
                                ci_low=-0.063, ci_high=-0.005),
        )
        self.assertEqual(record["interpretation"], "significant_negative")

    def test_interpretation_not_significant(self) -> None:
        record = sv.make_stat_validation_record(
            **self._full_inputs(fdr_q=0.40),
        )
        self.assertEqual(record["interpretation"], "not_significant")

    def test_interpretation_insufficient_data(self) -> None:
        record = sv.make_stat_validation_record(
            **self._full_inputs(abnormal_return=None),
        )
        self.assertEqual(record["interpretation"], "insufficient_data")

    def test_car_passes_through_when_provided(self) -> None:
        record = sv.make_stat_validation_record(
            **self._full_inputs(), car=0.045,
        )
        self.assertAlmostEqual(record["car"], 0.045)

    def test_car_defaults_to_none_when_absent(self) -> None:
        record = sv.make_stat_validation_record(**self._full_inputs())
        self.assertIsNone(record["car"])

    def test_car_does_not_affect_significance_or_interpretation(self) -> None:
        base = self._full_inputs(fdr_q=0.03)
        record_no_car = sv.make_stat_validation_record(**base)
        record_with_car = sv.make_stat_validation_record(**base, car=0.12)
        self.assertEqual(
            record_no_car["statistically_significant"],
            record_with_car["statistically_significant"],
        )
        self.assertEqual(
            record_no_car["interpretation"],
            record_with_car["interpretation"],
        )

    def test_car_nan_normalized_to_none(self) -> None:
        record = sv.make_stat_validation_record(
            **self._full_inputs(), car=float("nan"),
        )
        self.assertIsNone(record["car"])

    def test_record_is_json_serializable_with_nans_normalized(self) -> None:
        record = sv.make_stat_validation_record(
            horizon=5,
            abnormal_return=float("nan"),
            sar=float("nan"),
            car=float("nan"),
            ci_low=float("nan"),
            ci_high=float("nan"),
            p_value=float("nan"),
            fdr_q=float("nan"),
        )
        text = json.dumps(record, allow_nan=False)
        decoded = json.loads(text)
        self.assertEqual(decoded["horizon"], 5)
        for k in (
            "abnormal_return", "sar", "car", "ci_low", "ci_high",
            "p_value", "fdr_q",
        ):
            self.assertIsNone(decoded[k])
        self.assertFalse(decoded["statistically_significant"])
        self.assertEqual(decoded["interpretation"], "insufficient_data")

    def test_horizon_validation_propagates(self) -> None:
        with self.assertRaises(ValueError):
            sv.make_stat_validation_record(
                **self._full_inputs(horizon=0),
            )

    def test_ci_validation_propagates(self) -> None:
        # ci_low > ci_high must surface as ValueError on the composer
        # too — defense in depth so a caller cannot bypass the slice
        # check by going straight to the composer.
        with self.assertRaises(ValueError):
            sv.make_stat_validation_record(
                **self._full_inputs(ci_low=0.10, ci_high=0.05),
            )

    def test_p_value_validation_propagates(self) -> None:
        with self.assertRaises(ValueError):
            sv.make_stat_validation_record(
                **self._full_inputs(p_value=1.5),
            )

    def test_fdr_q_validation_propagates(self) -> None:
        with self.assertRaises(ValueError):
            sv.make_stat_validation_record(
                **self._full_inputs(fdr_q=-0.01),
            )


# ---------------------------------------------------------------------------
# Multi-horizon composer
# ---------------------------------------------------------------------------


class TestComposeValidationRecords(unittest.TestCase):
    def test_returns_one_record_per_input(self) -> None:
        rows = sv.compose_validation_records([
            dict(horizon=1,  abnormal_return=0.001, sar=0.5,
                 ci_low=-0.001, ci_high=0.003,
                 p_value=0.30, fdr_q=0.40),
            dict(horizon=5,  abnormal_return=0.010, sar=1.5,
                 ci_low=0.001, ci_high=0.019,
                 p_value=0.06, fdr_q=0.08),
            dict(horizon=20, abnormal_return=0.030, sar=2.5,
                 ci_low=0.005, ci_high=0.055,
                 p_value=0.005, fdr_q=0.01),
        ])
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(set(row.keys()), set(sv.STAT_VALIDATION_FIELDS))

    def test_records_preserve_input_order(self) -> None:
        rows = sv.compose_validation_records([
            dict(horizon=20, abnormal_return=0.030, sar=2.5,
                 ci_low=0.005, ci_high=0.055,
                 p_value=0.005, fdr_q=0.01),
            dict(horizon=1,  abnormal_return=0.001, sar=0.5,
                 ci_low=-0.001, ci_high=0.003,
                 p_value=0.30, fdr_q=0.40),
        ])
        # Order is preserved — the caller decides whether to sort.
        self.assertEqual(rows[0]["horizon"], 20)
        self.assertEqual(rows[1]["horizon"], 1)

    def test_records_apply_significance_per_row(self) -> None:
        rows = sv.compose_validation_records([
            dict(horizon=1,  abnormal_return=0.001, sar=0.5,
                 ci_low=-0.001, ci_high=0.003,
                 p_value=0.30, fdr_q=0.40),
            dict(horizon=20, abnormal_return=0.030, sar=2.5,
                 ci_low=0.005, ci_high=0.055,
                 p_value=0.005, fdr_q=0.01),
        ])
        self.assertFalse(rows[0]["statistically_significant"])
        self.assertTrue(rows[1]["statistically_significant"])
        self.assertEqual(rows[0]["interpretation"], "not_significant")
        self.assertEqual(rows[1]["interpretation"], "significant_positive")

    def test_empty_input_returns_empty_list(self) -> None:
        self.assertEqual(sv.compose_validation_records([]), [])

    def test_alpha_forwarded_to_each_record(self) -> None:
        rows = sv.compose_validation_records(
            [
                dict(horizon=1,  abnormal_return=0.001, sar=0.5,
                     ci_low=-0.001, ci_high=0.003,
                     p_value=0.06, fdr_q=0.06),
            ],
            alpha=0.10,
        )
        # q=0.06 < alpha=0.10 → significant.
        self.assertTrue(rows[0]["statistically_significant"])

    def test_bad_input_propagates_value_error(self) -> None:
        # A single bad row aborts the whole composition — composing
        # half a list and silently dropping one is a worse contract
        # than failing loudly.
        with self.assertRaises(ValueError):
            sv.compose_validation_records([
                dict(horizon=1,  abnormal_return=0.001, sar=0.5,
                     ci_low=-0.001, ci_high=0.003,
                     p_value=0.30, fdr_q=0.40),
                dict(horizon=0,  abnormal_return=0.030, sar=2.5,  # bad
                     ci_low=0.005, ci_high=0.055,
                     p_value=0.005, fdr_q=0.01),
            ])


# ---------------------------------------------------------------------------
# No-side-effect contract — module must not import DB / UI / provider seams
# ---------------------------------------------------------------------------


class TestNoBannedImports(unittest.TestCase):
    def test_module_does_not_import_banned_seams(self) -> None:
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(sv))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])

        # The schema module is meant to be free of DB / UI / provider
        # / LLM dependencies so it can be imported from any layer
        # (research notebook, test fixture, backfill script, future
        # API route) without dragging the world along with it.
        banned = {
            "db", "sqlite3",
            "yfinance", "openai", "anthropic",
            "market_data", "market_check", "price_cache",
            "api", "routes", "fastapi",
        }
        self.assertEqual(
            imported & banned, set(),
            f"stat_validation must not import: {imported & banned}",
        )


if __name__ == "__main__":
    unittest.main()
