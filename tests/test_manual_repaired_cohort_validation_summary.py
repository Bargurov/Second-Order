"""Tests for ``scripts/manual_repaired_cohort_validation_summary.py``.

Pin the contract:

* Output dict carries EXACTLY 8 keys: ``repaired_clean_event_ids``,
  ``events_evaluated``, ``records_count``, ``significant_count``,
  ``top_abs_sar``, ``by_event_verdict``, ``limitations``,
  ``recommended_next_action``.
* Verdict vocabulary (conservative):
    - ``validated_raw_only`` — at least one record cleared raw
      ``p_value <= alpha``.  Lumps FDR-significant in too because
      the vocabulary lacks a stronger label and the user said
      "do not claim alpha."
    - ``contradicted`` — operator supplied a direction expectation
      AND at least one record has a raw-p signal in the opposite
      direction.  Default: never assigned (no direction map).
    - ``inconclusive_fdr`` — no raw-p signal, but at least one
      record with ``|SAR| >= 1``.  "Some signal, didn't clear."
    - ``insufficient`` — no records, OR every record has
      ``|SAR| < 1`` AND no raw-p signal.
* Order of evaluation: validated_raw_only → contradicted →
  inconclusive_fdr → insufficient.  First match wins.
* ``top_abs_sar`` sorted by ``abs(sar)`` desc; ties broken by
  ``(event_id asc, horizon asc)``; ``sar is None`` rows sink to
  the bottom; capped at ``limit``.
* Read-only — the seam consumes
  ``manual_repaired_cohort_validation_run`` and the summary never
  opens the live DB.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import manual_repaired_cohort_validation_summary as cli  # noqa: E402


_REQUIRED_KEYS = (
    "repaired_clean_event_ids",
    "events_evaluated",
    "records_count",
    "significant_count",
    "top_abs_sar",
    "by_event_verdict",
    "limitations",
    "recommended_next_action",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _example(
    *, event_id: int, horizon: int = 5,
    primary_ticker: str = "MS", benchmark: str = "SPY",
    mechanism_family: str | None = "supply_shock",
    abnormal_return: float | None = 0.012, sar: float | None = 1.5,
    ci_low: float | None = 0.001, ci_high: float | None = 0.022,
    p_value: float | None = 0.04, fdr_q: float | None = 0.08,
    interpretation: str = "not_significant",
    headline: str = "h",
) -> dict[str, Any]:
    return {
        "event_id":         event_id,
        "headline":         headline,
        "primary_ticker":   primary_ticker,
        "benchmark":        benchmark,
        "mechanism_family": mechanism_family,
        "horizon":          horizon,
        "abnormal_return":  abnormal_return,
        "sar":              sar,
        "ci_low":           ci_low,
        "ci_high":          ci_high,
        "p_value":          p_value,
        "fdr_q":            fdr_q,
        "interpretation":   interpretation,
    }


def _validation_run_payload(
    *,
    repaired_clean_event_ids: list[int] | None = None,
    examples: list[dict[str, Any]] | None = None,
    significant_count: int = 0,
    errors: list[str] | None = None,
    live_db_unchanged: bool = True,
    input_backup_unchanged: bool = True,
) -> dict[str, Any]:
    repaired_clean_event_ids = repaired_clean_event_ids or []
    examples = examples or []
    by_horizon: dict[str, dict[str, int]] = {}
    by_family: dict[str, dict[str, int]] = {}
    for ex in examples:
        h_key = str(ex.get("horizon"))
        by_horizon.setdefault(h_key, {"records_count": 0, "significant_count": 0})
        by_horizon[h_key]["records_count"] += 1
        fam = ex.get("mechanism_family")
        if isinstance(fam, str) and fam:
            by_family.setdefault(fam, {"events_evaluated": 0,
                                       "records_count":     0,
                                       "significant_count": 0})
            by_family[fam]["records_count"] += 1
    return {
        "ok":                       not (errors or []),
        "repaired_clean_event_ids": list(repaired_clean_event_ids),
        "events_evaluated":         len({ex["event_id"] for ex in examples}),
        "records_count":            len(examples),
        "significant_count":        significant_count,
        "by_horizon":               by_horizon,
        "by_mechanism_family":      by_family,
        "examples":                 list(examples),
        "excluded_event_ids":       [],
        "remaining_blockers":       {},
        "live_db_unchanged":        live_db_unchanged,
        "input_backup_unchanged":   input_backup_unchanged,
        "errors":                   list(errors or []),
        "warnings":                 [],
    }


def _patch_seam(payload: dict[str, Any]):
    def fake(*, backup_path, high_priority_csv, medium_csv,
             mechanism_family_csv=None, db_path, limit):
        return payload
    return patch.object(cli, "_run_validation_run", side_effect=fake)


def _summarize(payload: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Run the summary by patching the seam.  Saves callers from
    repeating the patch boilerplate."""
    with _patch_seam(payload):
        return cli.summarize_repaired_cohort_validation(
            backup_path="/dev/null/backup.db",
            high_priority_csv="/dev/null/high.csv",
            medium_csv="/dev/null/medium.csv",
            db_path=None,
            limit=kwargs.pop("limit", 50),
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_returns_dict_with_exactly_8_keys(self) -> None:
        result = _summarize(_validation_run_payload())
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))

    def test_required_keys_present_when_runner_errors(self) -> None:
        payload = _validation_run_payload(errors=["something blew up"])
        result = _summarize(payload)
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))
        # Runner errors fold into limitations — that's the only escape
        # hatch since the contract has no errors envelope key.
        self.assertTrue(
            any("something blew up" in lim for lim in result["limitations"]),
            f"limitations: {result['limitations']!r}",
        )


# ---------------------------------------------------------------------------
# Verdict bucket — order: validated_raw_only → contradicted →
# inconclusive_fdr → insufficient.  First match wins.
# ---------------------------------------------------------------------------


class TestValidatedRawOnly(unittest.TestCase):
    def test_raw_p_significant_record_yields_validated_raw_only(self) -> None:
        examples = [
            _example(event_id=73, horizon=5, primary_ticker="XOM",
                     mechanism_family="supply_shock",
                     abnormal_return=-0.107, sar=-2.27,
                     p_value=0.023, fdr_q=0.205),
        ]
        payload = _validation_run_payload(
            repaired_clean_event_ids=[73], examples=examples,
        )
        result = _summarize(payload)
        self.assertEqual(result["by_event_verdict"]["73"],
                         "validated_raw_only")

    def test_fdr_significant_also_lumps_into_validated_raw_only(self) -> None:
        # The conservative vocabulary lacks a stronger label.  An
        # FDR-significant record still maps to validated_raw_only
        # because we never claim alpha.
        examples = [
            _example(event_id=46, horizon=5,
                     p_value=0.001, fdr_q=0.01),
        ]
        payload = _validation_run_payload(
            repaired_clean_event_ids=[46], examples=examples,
            significant_count=1,
        )
        result = _summarize(payload)
        self.assertEqual(result["by_event_verdict"]["46"],
                         "validated_raw_only")


class TestInconclusiveFdr(unittest.TestCase):
    def test_no_raw_p_but_strong_sar_yields_inconclusive(self) -> None:
        examples = [
            _example(event_id=60, horizon=5, primary_ticker="XOM",
                     abnormal_return=-0.082, sar=-1.59,
                     p_value=0.113, fdr_q=0.263),
        ]
        payload = _validation_run_payload(
            repaired_clean_event_ids=[60], examples=examples,
        )
        result = _summarize(payload)
        self.assertEqual(result["by_event_verdict"]["60"],
                         "inconclusive_fdr")

    def test_borderline_sar_at_threshold(self) -> None:
        # |SAR| == 1.0 exactly counts as inconclusive (>= 1.0).
        examples = [
            _example(event_id=46, horizon=5,
                     sar=1.0, abnormal_return=0.012,
                     p_value=0.20, fdr_q=0.40),
        ]
        result = _summarize(_validation_run_payload(
            repaired_clean_event_ids=[46], examples=examples))
        self.assertEqual(result["by_event_verdict"]["46"],
                         "inconclusive_fdr")


class TestInsufficient(unittest.TestCase):
    def test_event_in_cohort_but_no_records_is_insufficient(self) -> None:
        # Event 99 is in repaired_clean_event_ids but the validation
        # pipeline filtered it out (no examples).
        payload = _validation_run_payload(
            repaired_clean_event_ids=[99], examples=[],
        )
        result = _summarize(payload)
        self.assertEqual(result["by_event_verdict"]["99"], "insufficient")

    def test_weak_sar_no_p_signal_is_insufficient(self) -> None:
        examples = [
            _example(event_id=46, horizon=5,
                     sar=0.2, abnormal_return=0.001,
                     p_value=0.80, fdr_q=0.95),
        ]
        result = _summarize(_validation_run_payload(
            repaired_clean_event_ids=[46], examples=examples))
        self.assertEqual(result["by_event_verdict"]["46"], "insufficient")

    def test_sar_none_with_no_p_signal_is_insufficient(self) -> None:
        examples = [
            _example(event_id=46, horizon=5,
                     sar=None, abnormal_return=None,
                     p_value=0.95, fdr_q=0.99,
                     interpretation="insufficient_data"),
        ]
        result = _summarize(_validation_run_payload(
            repaired_clean_event_ids=[46], examples=examples))
        self.assertEqual(result["by_event_verdict"]["46"], "insufficient")


class TestContradicted(unittest.TestCase):
    def test_no_direction_map_default_never_contradicts(self) -> None:
        # Even with raw-p significant + AR sign that an operator
        # might call wrong, no verdict change without direction map.
        examples = [
            _example(event_id=73, horizon=5,
                     mechanism_family="supply_shock",
                     abnormal_return=-0.107, sar=-2.27,
                     p_value=0.023, fdr_q=0.205),
        ]
        result = _summarize(_validation_run_payload(
            repaired_clean_event_ids=[73], examples=examples))
        # Default direction map is empty → validated_raw_only, not contradicted.
        self.assertEqual(result["by_event_verdict"]["73"],
                         "validated_raw_only")

    def test_direction_map_with_opposite_sign_yields_contradicted(self) -> None:
        examples = [
            _example(event_id=73, horizon=5,
                     mechanism_family="supply_shock",
                     abnormal_return=-0.107, sar=-2.27,
                     p_value=0.023, fdr_q=0.205),
        ]
        # Operator says supply_shock should be POSITIVE for affected
        # firm; record is raw-p significant with negative AR ⇒ contradicted.
        result = _summarize(
            _validation_run_payload(
                repaired_clean_event_ids=[73], examples=examples),
            mechanism_direction={"supply_shock": +1},
        )
        self.assertEqual(result["by_event_verdict"]["73"], "contradicted")

    def test_direction_map_matching_sign_keeps_validated_raw_only(self) -> None:
        examples = [
            _example(event_id=46, horizon=5,
                     mechanism_family="bank_regulatory_capital_relief",
                     abnormal_return=+0.046, sar=+1.5,
                     p_value=0.04, fdr_q=0.08),
        ]
        result = _summarize(
            _validation_run_payload(
                repaired_clean_event_ids=[46], examples=examples),
            mechanism_direction={"bank_regulatory_capital_relief": +1},
        )
        self.assertEqual(result["by_event_verdict"]["46"],
                         "validated_raw_only")


# ---------------------------------------------------------------------------
# top_abs_sar
# ---------------------------------------------------------------------------


class TestTopAbsSar(unittest.TestCase):
    def test_sorted_by_abs_sar_descending(self) -> None:
        examples = [
            _example(event_id=46, horizon=1, sar=+0.5),
            _example(event_id=73, horizon=5, sar=-2.27),
            _example(event_id=60, horizon=5, sar=-1.59),
            _example(event_id=46, horizon=5, sar=+1.21),
        ]
        result = _summarize(_validation_run_payload(
            repaired_clean_event_ids=[46, 60, 73], examples=examples))
        sars = [abs(rec["sar"]) for rec in result["top_abs_sar"]]
        self.assertEqual(sars, sorted(sars, reverse=True))

    def test_capped_at_limit(self) -> None:
        examples = [
            _example(event_id=i, horizon=5, sar=float(i))
            for i in range(1, 21)
        ]
        result = _summarize(
            _validation_run_payload(
                repaired_clean_event_ids=list(range(1, 21)), examples=examples),
            limit=5,
        )
        self.assertEqual(len(result["top_abs_sar"]), 5)
        # Top entry should be the highest |SAR| (event_id=20).
        self.assertEqual(result["top_abs_sar"][0]["event_id"], 20)

    def test_ties_broken_deterministically(self) -> None:
        examples = [
            _example(event_id=10, horizon=20, sar=+1.0),
            _example(event_id=10, horizon=5,  sar=-1.0),
            _example(event_id=5,  horizon=5,  sar=+1.0),
        ]
        result = _summarize(_validation_run_payload(
            repaired_clean_event_ids=[5, 10], examples=examples))
        # All |SAR|==1; tie-break by (event_id asc, horizon asc).
        order = [(rec["event_id"], rec["horizon"])
                 for rec in result["top_abs_sar"]]
        self.assertEqual(order, [(5, 5), (10, 5), (10, 20)])

    def test_sar_none_sinks_to_bottom(self) -> None:
        examples = [
            _example(event_id=1, horizon=5, sar=None),
            _example(event_id=2, horizon=5, sar=+0.1),
            _example(event_id=3, horizon=5, sar=-3.0),
        ]
        result = _summarize(_validation_run_payload(
            repaired_clean_event_ids=[1, 2, 3], examples=examples))
        # Last entry must be the SAR=None row.
        self.assertIsNone(result["top_abs_sar"][-1]["sar"])
        self.assertEqual(result["top_abs_sar"][0]["event_id"], 3)


# ---------------------------------------------------------------------------
# Aggregate fields + limitations + recommended_next_action
# ---------------------------------------------------------------------------


class TestAggregateFields(unittest.TestCase):
    def test_aggregates_passthrough_from_runner(self) -> None:
        examples = [
            _example(event_id=46, horizon=1, sar=+0.5),
            _example(event_id=46, horizon=5, sar=+1.21),
            _example(event_id=46, horizon=20, sar=+0.6),
        ]
        payload = _validation_run_payload(
            repaired_clean_event_ids=[46], examples=examples,
            significant_count=0,
        )
        result = _summarize(payload)
        self.assertEqual(result["repaired_clean_event_ids"], [46])
        self.assertEqual(result["events_evaluated"], 1)
        self.assertEqual(result["records_count"], 3)
        self.assertEqual(result["significant_count"], 0)


class TestLimitations(unittest.TestCase):
    def test_limitations_is_non_empty_list_of_strings(self) -> None:
        result = _summarize(_validation_run_payload(
            repaired_clean_event_ids=[46], examples=[
                _example(event_id=46, sar=1.5, p_value=0.04, fdr_q=0.08),
            ]))
        self.assertIsInstance(result["limitations"], list)
        self.assertTrue(result["limitations"])
        for lim in result["limitations"]:
            self.assertIsInstance(lim, str)

    def test_limitations_mention_conservative_vocabulary(self) -> None:
        result = _summarize(_validation_run_payload())
        joined = " | ".join(result["limitations"]).lower()
        # The summary MUST not claim "proof" / "alpha" — limitations
        # call out the conservative vocabulary explicitly.
        self.assertIn("not proof", joined)


class TestRecommendedNextAction(unittest.TestCase):
    def test_recommended_action_is_non_empty_string(self) -> None:
        result = _summarize(_validation_run_payload(
            repaired_clean_event_ids=[46], examples=[
                _example(event_id=46, sar=1.5, p_value=0.04, fdr_q=0.08),
            ]))
        self.assertIsInstance(result["recommended_next_action"], str)
        self.assertTrue(result["recommended_next_action"])

    def test_recommended_action_matches_raw_only_without_fdr_claim(
        self,
    ) -> None:
        result = _summarize(_validation_run_payload(
            repaired_clean_event_ids=[73], examples=[
                _example(event_id=73, primary_ticker="XOM",
                         abnormal_return=-0.107, sar=-2.27,
                         p_value=0.0233, fdr_q=0.205),
            ], significant_count=0))
        text = result["recommended_next_action"].lower()
        self.assertIn("raw-p candidate evidence exists", text)
        self.assertIn("no fdr-significant aggregate claim yet", text)
        self.assertNotIn("no record cleared the raw p-value threshold", text)

    def test_recommended_action_avoids_proof_alpha(self) -> None:
        result = _summarize(_validation_run_payload(
            repaired_clean_event_ids=[46], examples=[
                _example(event_id=46, sar=2.5, p_value=0.001, fdr_q=0.01),
            ], significant_count=1))
        text = result["recommended_next_action"].lower()
        # Conservative language only — NEVER claim proof or alpha.
        self.assertNotIn("proof", text)
        self.assertNotIn("alpha generated", text)


# ---------------------------------------------------------------------------
# Empty cohort
# ---------------------------------------------------------------------------


class TestEmptyCohort(unittest.TestCase):
    def test_empty_cohort_returns_zero_aggregates(self) -> None:
        result = _summarize(_validation_run_payload())
        self.assertEqual(result["repaired_clean_event_ids"], [])
        self.assertEqual(result["events_evaluated"], 0)
        self.assertEqual(result["records_count"], 0)
        self.assertEqual(result["significant_count"], 0)
        self.assertEqual(result["top_abs_sar"], [])
        self.assertEqual(result["by_event_verdict"], {})


# ---------------------------------------------------------------------------
# Patchable seam + read-only enforcement
# ---------------------------------------------------------------------------


class TestSeam(unittest.TestCase):
    def test_seam_exists_and_is_callable(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_validation_run")))

    def test_seam_receives_all_args(self) -> None:
        captured: dict[str, Any] = {}

        def fake(*, backup_path, high_priority_csv, medium_csv,
                 mechanism_family_csv=None, db_path, limit):
            captured["backup_path"] = backup_path
            captured["high_priority_csv"] = high_priority_csv
            captured["medium_csv"] = medium_csv
            captured["mechanism_family_csv"] = mechanism_family_csv
            captured["db_path"] = db_path
            captured["limit"] = limit
            return _validation_run_payload()

        with patch.object(cli, "_run_validation_run", side_effect=fake):
            cli.summarize_repaired_cohort_validation(
                backup_path="/x/backup.db",
                high_priority_csv="/x/high.csv",
                medium_csv="/x/medium.csv",
                mechanism_family_csv="/x/family.csv",
                db_path="/x/live.db",
                limit=17,
            )
        self.assertEqual(captured["backup_path"], "/x/backup.db")
        self.assertEqual(captured["high_priority_csv"], "/x/high.csv")
        self.assertEqual(captured["medium_csv"], "/x/medium.csv")
        self.assertEqual(captured["mechanism_family_csv"], "/x/family.csv")
        self.assertEqual(captured["db_path"], "/x/live.db")
        self.assertEqual(captured["limit"], 17)

    def test_mechanism_family_csv_defaults_to_none_when_omitted(self) -> None:
        captured: dict[str, Any] = {}

        def fake(*, backup_path, high_priority_csv, medium_csv,
                 mechanism_family_csv=None, db_path, limit):
            captured["mechanism_family_csv"] = mechanism_family_csv
            return _validation_run_payload()

        with patch.object(cli, "_run_validation_run", side_effect=fake):
            cli.summarize_repaired_cohort_validation(
                backup_path="/x/backup.db",
                high_priority_csv="/x/high.csv",
                medium_csv="/x/medium.csv",
                db_path=None,
                limit=10,
            )
        self.assertIsNone(captured["mechanism_family_csv"])


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_emits_parseable_json(self) -> None:
        out = StringIO()
        examples = [
            _example(event_id=46, horizon=5, sar=+1.21,
                     p_value=0.04, fdr_q=0.08),
        ]
        with _patch_seam(_validation_run_payload(
                repaired_clean_event_ids=[46], examples=examples)):
            rc = cli.main([
                "--json",
                "--backup-path", "/x/backup.db",
                "--high-priority-csv", "/x/high.csv",
                "--medium-csv", "/x/medium.csv",
                "--limit", "3",
            ], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(parsed["repaired_clean_event_ids"], [46])

    def test_cli_text_mode_runs_without_error(self) -> None:
        out = StringIO()
        with _patch_seam(_validation_run_payload()):
            rc = cli.main([
                "--backup-path", "/x/backup.db",
                "--high-priority-csv", "/x/high.csv",
                "--medium-csv", "/x/medium.csv",
            ], out=out)
        self.assertEqual(rc, 0)
        self.assertTrue(out.getvalue())

    def test_cli_accepts_mechanism_family_csv_flag(self) -> None:
        captured: dict[str, Any] = {}

        def fake(*, backup_path, high_priority_csv, medium_csv,
                 mechanism_family_csv=None, db_path, limit):
            captured["mechanism_family_csv"] = mechanism_family_csv
            return _validation_run_payload(
                repaired_clean_event_ids=[30, 40, 46, 60, 73],
                examples=[
                    _example(event_id=30, sar=+1.4),
                    _example(event_id=40, sar=+2.1),
                    _example(event_id=46, sar=+0.5),
                    _example(event_id=60, sar=+1.2),
                    _example(event_id=73, sar=-0.8),
                ],
            )

        out = StringIO()
        with patch.object(cli, "_run_validation_run", side_effect=fake):
            rc = cli.main([
                "--json",
                "--backup-path", "/x/backup.db",
                "--high-priority-csv", "/x/high.csv",
                "--medium-csv", "/x/medium.csv",
                "--mechanism-family-csv", "/x/family.csv",
                "--limit", "5",
            ], out=out)
        self.assertEqual(rc, 0)
        self.assertEqual(captured["mechanism_family_csv"], "/x/family.csv")
        parsed = json.loads(out.getvalue())
        self.assertEqual(
            sorted(parsed["repaired_clean_event_ids"]),
            [30, 40, 46, 60, 73],
        )


if __name__ == "__main__":
    unittest.main()
