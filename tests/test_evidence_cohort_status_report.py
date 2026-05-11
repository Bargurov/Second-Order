"""Tests for ``scripts/evidence_cohort_status_report.py``.

The evidence cohort status report is a read-only "where do we stand"
artifact: it composes existing local report scripts (repaired-cohort
validation summary, curated_candidate_status, short_horizon_repair_packet,
and a price_cache XLE-presence probe for benchmark sensitivity) into a
single 10-key JSON envelope so a reviewer can see demo-readiness truth in
one place.

Pin the contract:

* Read-only.  No DB writes, no provider calls, no LLM, no FastAPI.
* Composes via patchable seams; tests never invoke the real pipelines.
* 10-key envelope::

    {
      "ok":                            bool,
      "current_repaired_cohort":       {...},
      "curated_candidate_status":      {...},
      "short_horizon_expansion_status":{...},
      "benchmark_sensitivity_status":  {...},
      "evidence_claim_allowed":        [str, ...],
      "evidence_claim_not_allowed":    [str, ...],
      "next_best_action":              str,
      "warnings":                      [str, ...],
      "errors":                        [str, ...],
    }

* Conservative wording — banned tokens absent from every emitted string.
* When the operator does not supply --backup-path / CSVs, the repaired
  cohort surfaces ``status="not_sourced"`` rather than running anything
  heavy.  The 5-event truth claim only fires when sourced from the
  upstream summary.
* When the curated_candidates table has no rows, the curated section
  surfaces ``staged_candidate_count == 0`` and a ready-to-stage hint —
  not a failure.
* Short-horizon candidates surface the candidate count and explicitly
  request operator review.
* When ``benchmark_sensitivity_preflight`` reports any blocked events,
  the benchmark sensitivity block surfaces ``status="blocked"`` so the
  report stays one-for-one with the preflight; it never flips to a
  negative claim about significance.
* When the preflight runner raises or returns ``ok=False``/non-empty
  ``errors``, the block reports ``status="unknown"`` with the upstream
  errors surfaced verbatim.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import evidence_cohort_status_report as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "current_repaired_cohort",
    "curated_candidate_status",
    "short_horizon_expansion_status",
    "benchmark_sensitivity_status",
    "evidence_claim_allowed",
    "evidence_claim_not_allowed",
    "next_best_action",
    "warnings",
    "errors",
)


# Banned tokens — every emitted string must avoid these.  The report is
# evidence-only; nothing it emits should imply causation, alpha, or proof.
_BANNED_WORDS = (
    "proof",
    "alpha",
    "automatic",
    "predictive",
    "causal",
)


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


def _empty_repaired_summary() -> dict[str, Any]:
    return {
        "repaired_clean_event_ids":  [],
        "events_evaluated":          0,
        "records_count":             0,
        "significant_count":         0,
        "top_abs_sar":               [],
        "by_event_verdict":          {},
        "limitations":               [],
        "recommended_next_action":   "",
    }


def _five_event_repaired_summary() -> dict[str, Any]:
    return {
        "repaired_clean_event_ids":  [44, 51, 60, 73, 220],
        "events_evaluated":          5,
        "records_count":             15,
        "significant_count":         0,
        "top_abs_sar":               [],
        "by_event_verdict": {
            "44":  "insufficient",
            "51":  "insufficient",
            "60":  "insufficient",
            "73":  "validated_raw_only",
            "220": "insufficient",
        },
        "limitations":               [],
        "recommended_next_action":   "",
    }


def _empty_curated_status() -> dict[str, Any]:
    return {
        "ok":                          True,
        "total":                       0,
        "counts_by_status":            {},
        "counts_by_mechanism_family":  {},
        "counts_by_ticker":            {},
        "missing_field_counts":        {},
        "errors":                      [],
    }


def _populated_curated_status(total: int = 3) -> dict[str, Any]:
    return {
        "ok":                          True,
        "total":                       total,
        "counts_by_status":            {"draft": total},
        "counts_by_mechanism_family":  {"supply_shock": total},
        "counts_by_ticker":            {"MS": total},
        "missing_field_counts":        {},
        "errors":                      [],
    }


def _empty_short_horizon_packet() -> dict[str, Any]:
    return {
        "ok":                            True,
        "excluded_reviewed_event_ids":   [],
        "reviewed_exclusion_set_count":  24,
        "excluded_reviewed_count":       0,
        "total_short_ready":             0,
        "delta_vs_full_ready":           0,
        "total_candidates_after_filter": 0,
        "candidates":                    [],
        "export_summary":                {
            "candidate_count":              0,
            "reviewed_exclusion_set_count": 24,
            "top_candidates":               [],
        },
        "recommended_next_action":       "",
    }


def _short_horizon_packet_with_candidates(n: int = 7) -> dict[str, Any]:
    candidates = [
        {
            "event_id":               1000 + i,
            "headline":               f"h{i}",
            "event_date":             "2026-04-01",
            "current_primary_ticker": "MS",
            "flags":                  ["mechanism_family_none"],
            "repair_type":            "mechanism_family_only",
            "repair_priority":        "high",
        }
        for i in range(n)
    ]
    return {
        "ok":                            True,
        "excluded_reviewed_event_ids":   [],
        "reviewed_exclusion_set_count":  24,
        "excluded_reviewed_count":       0,
        "total_short_ready":             50,
        "delta_vs_full_ready":           5,
        "total_candidates_after_filter": n,
        "candidates":                    candidates,
        "export_summary":                {
            "candidate_count":              n,
            "reviewed_exclusion_set_count": 24,
            "top_candidates":               candidates,
        },
        "recommended_next_action":       "",
    }


def _no_local_inputs() -> dict[str, Any]:
    """Default seam stand-in: nothing on disk to auto-source from."""
    return {
        "backup_path":          None,
        "high_priority_csv":    None,
        "medium_csv":           None,
        "mechanism_family_csv": None,
        "missing":              [
            "backup_path",
            "high_priority_csv",
            "medium_csv",
        ],
    }


def _ready_preflight(*, n: int = 2) -> dict[str, Any]:
    """Preflight payload where all ``n`` events report ready.

    Mirrors the shape of
    ``summarize_benchmark_sensitivity_preflight`` for n events that
    pass both the primary-ticker and benchmark-ticker cache checks.
    """
    return {
        "ok":             True,
        "checked_events": n,
        "ready_count":    n,
        "blocked_count":  0,
        "rows": [
            {
                "event_id":                  100 + i,
                "primary_ticker":            "XOM",
                "benchmark_ticker":          "XLE",
                "event_date":                "2026-04-01",
                "required_horizons":         [1, 5, 20],
                "primary_cache_available":   True,
                "benchmark_cache_available": True,
                "missing_primary_ranges":    [],
                "missing_benchmark_ranges":  [],
                "can_run_sensitivity":       True,
                "blocker_reason":            "ready",
            }
            for i in range(n)
        ],
        "recommended_next_action": "",
    }


def _blocked_preflight(*, blocked: int = 2) -> dict[str, Any]:
    """Preflight payload where every checked event is blocked by the
    benchmark estimation-window cache short fall.  Mirrors the live
    preflight output for events 60/73 against XLE.
    """
    return {
        "ok":             True,
        "checked_events": blocked,
        "ready_count":    0,
        "blocked_count":  blocked,
        "rows": [
            {
                "event_id":                  60 + i,
                "primary_ticker":            "XOM",
                "benchmark_ticker":          "XLE",
                "event_date":                "2026-04-01",
                "required_horizons":         [1, 5, 20],
                "primary_cache_available":   True,
                "benchmark_cache_available": False,
                "missing_primary_ranges":    [],
                "missing_benchmark_ranges":  [
                    {
                        "start":  "2026-01-01",
                        "end":    "2026-01-02",
                        "reason": "estimation_window_short",
                    },
                ],
                "can_run_sensitivity":       False,
                "blocker_reason":            (
                    "benchmark XLE: estimation_window_short"
                ),
            }
            for i in range(blocked)
        ],
        "recommended_next_action": "",
    }


def _preflight_with_errors() -> dict[str, Any]:
    """Preflight payload where the upstream runner reports failure."""
    return {
        "ok":             False,
        "checked_events": 0,
        "ready_count":    0,
        "blocked_count":  0,
        "rows":           [],
        "errors":         ["preflight could not open archive"],
        "recommended_next_action": "",
    }


def _all_local_inputs(
    *, mechanism_family: bool = True,
) -> dict[str, Any]:
    """Seam stand-in: every canonical input exists on disk."""
    return {
        "backup_path":          "backups/events-20260507T095609.db",
        "high_priority_csv":    "manual_ticker_repair_high_priority.csv",
        "medium_csv":           "manual_ticker_repair_medium_production_like.csv",
        "mechanism_family_csv": (
            "mechanism_family_repair_packet.csv"
            if mechanism_family else None
        ),
        "missing":              [],
    }


def _summarize(
    *,
    repaired_summary: dict[str, Any] | None = None,
    curated_status: dict[str, Any] | None = None,
    short_horizon: dict[str, Any] | None = None,
    preflight_payload: dict[str, Any] | None = None,
    preflight_raises: bool = False,
    backup_path: str | None = None,
    high_priority_csv: str | None = None,
    medium_csv: str | None = None,
    mechanism_family_csv: str | None = None,
    db_path: str | None = None,
    discover_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repaired = repaired_summary or _empty_repaired_summary()
    curated = curated_status or _empty_curated_status()
    sh = short_horizon or _empty_short_horizon_packet()
    preflight = (
        preflight_payload if preflight_payload is not None
        else _ready_preflight()
    )
    discover = discover_payload if discover_payload is not None else (
        _no_local_inputs()
    )

    if preflight_raises:
        preflight_patch_kw: dict[str, Any] = {
            "side_effect": RuntimeError("preflight crashed"),
        }
    else:
        preflight_patch_kw = {"return_value": preflight}

    with patch.object(cli, "_run_repaired_cohort_summary",
                      return_value=repaired), \
         patch.object(cli, "_run_curated_candidate_status",
                      return_value=curated), \
         patch.object(cli, "_run_short_horizon_repair_packet",
                      return_value=sh), \
         patch.object(cli, "_run_benchmark_sensitivity_preflight",
                      **preflight_patch_kw), \
         patch.object(cli, "_discover_local_repaired_inputs",
                      return_value=discover):
        return cli.build_evidence_cohort_status(
            backup_path=backup_path,
            high_priority_csv=high_priority_csv,
            medium_csv=medium_csv,
            mechanism_family_csv=mechanism_family_csv,
            db_path=db_path,
        )


def _flatten_strings(value: Any) -> list[str]:
    """Recursively pull every string in a JSON-shaped value."""
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_flatten_strings(v))
    elif isinstance(value, list):
        for v in value:
            out.extend(_flatten_strings(v))
    return out


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class TestEnvelopeShape(unittest.TestCase):
    def test_returns_dict_with_exactly_ten_keys(self) -> None:
        result = _summarize()
        self.assertEqual(set(result.keys()), set(_REQUIRED_KEYS))
        self.assertEqual(len(result), 10)

    def test_warnings_and_errors_are_lists(self) -> None:
        result = _summarize()
        self.assertIsInstance(result["warnings"], list)
        self.assertIsInstance(result["errors"], list)

    def test_evidence_claim_lists_are_lists_of_strings(self) -> None:
        result = _summarize()
        self.assertIsInstance(result["evidence_claim_allowed"], list)
        self.assertIsInstance(result["evidence_claim_not_allowed"], list)
        for s in result["evidence_claim_allowed"]:
            self.assertIsInstance(s, str)
        for s in result["evidence_claim_not_allowed"]:
            self.assertIsInstance(s, str)

    def test_ok_is_true_when_no_errors(self) -> None:
        result = _summarize()
        self.assertTrue(result["ok"])
        self.assertEqual(result["errors"], [])

    def test_next_best_action_is_string(self) -> None:
        result = _summarize()
        self.assertIsInstance(result["next_best_action"], str)
        self.assertGreater(len(result["next_best_action"]), 0)


# ---------------------------------------------------------------------------
# current_repaired_cohort
# ---------------------------------------------------------------------------


class TestCurrentRepairedCohort(unittest.TestCase):
    def test_not_sourced_when_no_backup_path_provided(self) -> None:
        # Default seam is patched but the runner is only invoked when
        # the operator supplies --backup-path/CSVs.  Without them, we
        # surface a "not_sourced" status instead of running.
        result = _summarize()
        block = result["current_repaired_cohort"]
        self.assertIsInstance(block, dict)
        self.assertEqual(block.get("status"), "not_sourced")
        self.assertIn("repaired_clean_event_count", block)
        self.assertEqual(block["repaired_clean_event_count"], 0)

    def test_five_event_truth_when_sourced(self) -> None:
        # When backup-path + both CSVs are supplied, the seam runs and
        # the 5-event truth surfaces as a sourced status.
        result = _summarize(
            repaired_summary=_five_event_repaired_summary(),
            backup_path="backups/events-20260507T095609.db",
            high_priority_csv="manual_ticker_repair_high_priority.csv",
            medium_csv="manual_ticker_repair_medium_production_like.csv",
        )
        block = result["current_repaired_cohort"]
        self.assertEqual(block.get("status"), "sourced")
        self.assertEqual(block["repaired_clean_event_count"], 5)
        self.assertEqual(
            block["repaired_clean_event_ids"], [44, 51, 60, 73, 220],
        )
        self.assertEqual(block["records_count"], 15)
        self.assertEqual(block["fdr_significant_count"], 0)

    def test_summary_seam_not_called_when_no_inputs_anywhere(self) -> None:
        # When neither explicit args nor local files supply inputs,
        # the heavy summary seam must not run — we surface
        # ``status="not_sourced"`` instead.
        with patch.object(cli, "_run_repaired_cohort_summary",
                          return_value=_empty_repaired_summary()) as m_summary, \
             patch.object(cli, "_run_curated_candidate_status",
                          return_value=_empty_curated_status()), \
             patch.object(cli, "_run_short_horizon_repair_packet",
                          return_value=_empty_short_horizon_packet()), \
             patch.object(cli, "_run_benchmark_sensitivity_preflight",
                          return_value=_ready_preflight()), \
             patch.object(cli, "_discover_local_repaired_inputs",
                          return_value=_no_local_inputs()):
            cli.build_evidence_cohort_status()
            m_summary.assert_not_called()


# ---------------------------------------------------------------------------
# curated_candidate_status
# ---------------------------------------------------------------------------


class TestCuratedCandidateStatus(unittest.TestCase):
    def test_zero_when_table_empty(self) -> None:
        result = _summarize(curated_status=_empty_curated_status())
        block = result["curated_candidate_status"]
        self.assertEqual(block.get("staged_candidate_count"), 0)

    def test_propagates_count_when_populated(self) -> None:
        result = _summarize(
            curated_status=_populated_curated_status(total=4),
        )
        block = result["curated_candidate_status"]
        self.assertEqual(block.get("staged_candidate_count"), 4)
        self.assertEqual(
            block.get("counts_by_status"), {"draft": 4},
        )

    def test_curated_errors_propagate_to_envelope_errors(self) -> None:
        bad = _empty_curated_status()
        bad["ok"] = False
        bad["errors"] = ["curated_candidates table missing: no such table"]
        result = _summarize(curated_status=bad)
        # Curated errors land on the envelope's errors list.
        joined = " ".join(result["errors"])
        self.assertIn("curated_candidates table missing", joined)
        # ok should flip when we have errors.
        self.assertFalse(result["ok"])


# ---------------------------------------------------------------------------
# short_horizon_expansion_status
# ---------------------------------------------------------------------------


class TestShortHorizonExpansionStatus(unittest.TestCase):
    def test_reports_zero_when_no_candidates(self) -> None:
        result = _summarize(short_horizon=_empty_short_horizon_packet())
        block = result["short_horizon_expansion_status"]
        self.assertEqual(block.get("candidate_count"), 0)
        self.assertFalse(block.get("operator_review_required"))

    def test_reports_count_and_operator_review_when_candidates_present(
        self,
    ) -> None:
        result = _summarize(
            short_horizon=_short_horizon_packet_with_candidates(n=7),
        )
        block = result["short_horizon_expansion_status"]
        self.assertEqual(block.get("candidate_count"), 7)
        self.assertTrue(block.get("operator_review_required"))
        # Some operator-review-y wording must surface.
        joined = " ".join(_flatten_strings(block)).lower()
        self.assertIn("operator", joined)
        self.assertIn("review", joined)


# ---------------------------------------------------------------------------
# benchmark_sensitivity_status — preflight-sourced readiness
#
# The block is sourced directly from
# ``benchmark_sensitivity_preflight.summarize_benchmark_sensitivity_preflight``
# so the status report stays one-for-one with the preflight: any blocked
# event flips the report to ``status="blocked"``; ready is reserved for
# the case where the preflight checked at least one event and reported
# zero blockers; preflight failures surface as ``status="unknown"``.
# ---------------------------------------------------------------------------


class TestBenchmarkSensitivityStatus(unittest.TestCase):
    def test_blocked_when_preflight_reports_blocked(self) -> None:
        result = _summarize(
            preflight_payload=_blocked_preflight(blocked=2),
        )
        block = result["benchmark_sensitivity_status"]
        self.assertEqual(block.get("status"), "blocked")
        self.assertEqual(block.get("blocked_count"), 2)
        self.assertEqual(block.get("checked_events"), 2)
        joined = " ".join(_flatten_strings(block)).lower()
        # Must read as a blocker, not a negative significance claim.
        self.assertIn("blocked", joined)
        for forbidden in ("not significant", "significant", "negative"):
            self.assertNotIn(forbidden, joined)

    def test_ready_when_preflight_reports_all_ready(self) -> None:
        result = _summarize(preflight_payload=_ready_preflight(n=2))
        block = result["benchmark_sensitivity_status"]
        self.assertEqual(block.get("status"), "ready")
        self.assertEqual(block.get("ready_count"), 2)
        self.assertEqual(block.get("blocked_count"), 0)
        self.assertEqual(block.get("checked_events"), 2)

    def test_unknown_when_preflight_raises(self) -> None:
        result = _summarize(preflight_raises=True)
        block = result["benchmark_sensitivity_status"]
        self.assertEqual(block.get("status"), "unknown")
        errors = block.get("errors")
        self.assertIsInstance(errors, list)
        self.assertGreater(len(errors), 0)

    def test_unknown_when_preflight_returns_not_ok(self) -> None:
        result = _summarize(preflight_payload=_preflight_with_errors())
        block = result["benchmark_sensitivity_status"]
        self.assertEqual(block.get("status"), "unknown")
        errors = block.get("errors")
        self.assertIsInstance(errors, list)
        self.assertGreater(len(errors), 0)

    def test_unknown_when_no_events_checked(self) -> None:
        # blocked_count == 0 alone is not enough — readiness requires
        # at least one event actually checked.
        result = _summarize(preflight_payload=_ready_preflight(n=0))
        block = result["benchmark_sensitivity_status"]
        self.assertEqual(block.get("status"), "unknown")
        self.assertEqual(block.get("checked_events"), 0)

    def test_rows_carry_blocker_reasons_per_event(self) -> None:
        result = _summarize(
            preflight_payload=_blocked_preflight(blocked=2),
        )
        block = result["benchmark_sensitivity_status"]
        rows = block.get("rows")
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn("event_id",            row)
            self.assertIn("blocker_reason",      row)
            self.assertIn("can_run_sensitivity", row)
            self.assertFalse(row["can_run_sensitivity"])
            self.assertIn("estimation_window_short", row["blocker_reason"])

    def test_seam_receives_db_path(self) -> None:
        captured: dict[str, Any] = {}

        def fake_preflight(**kwargs):
            captured.update(kwargs)
            return _ready_preflight(n=2)

        with patch.object(cli, "_run_repaired_cohort_summary",
                          return_value=_empty_repaired_summary()), \
             patch.object(cli, "_run_curated_candidate_status",
                          return_value=_empty_curated_status()), \
             patch.object(cli, "_run_short_horizon_repair_packet",
                          return_value=_empty_short_horizon_packet()), \
             patch.object(cli, "_run_benchmark_sensitivity_preflight",
                          side_effect=fake_preflight), \
             patch.object(cli, "_discover_local_repaired_inputs",
                          return_value=_no_local_inputs()):
            cli.build_evidence_cohort_status(db_path="/tmp/custom.db")
        # The seam must receive the operator-supplied db_path verbatim
        # so live --json output agrees with benchmark_sensitivity_preflight.
        self.assertEqual(captured.get("db_path"), "/tmp/custom.db")


# ---------------------------------------------------------------------------
# evidence_claim_allowed / evidence_claim_not_allowed
# ---------------------------------------------------------------------------


class TestEvidenceClaims(unittest.TestCase):
    def test_allowed_claims_non_empty_and_string_typed(self) -> None:
        result = _summarize()
        self.assertGreater(len(result["evidence_claim_allowed"]), 0)
        for s in result["evidence_claim_allowed"]:
            self.assertIsInstance(s, str)
            self.assertGreater(len(s), 0)

    def test_not_allowed_enumerates_excluded_claim_kinds(self) -> None:
        result = _summarize()
        joined = " ".join(result["evidence_claim_not_allowed"]).lower()
        # The not-allowed list must enumerate every reserved claim kind:
        self.assertIn("alpha", joined)
        self.assertIn("predictive", joined)
        self.assertIn("causal", joined)
        self.assertIn("proof", joined)


# ---------------------------------------------------------------------------
# Conservative wording — banned tokens absent from anything else the
# report emits.  The "not allowed" list is the only place banned tokens
# may appear (since it must enumerate them).
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_banned_tokens_absent_outside_not_allowed_list(self) -> None:
        for preflight in (_ready_preflight(n=2), _blocked_preflight(blocked=2)):
            result = _summarize(
                repaired_summary=_five_event_repaired_summary(),
                backup_path="backups/events-20260507T095609.db",
                high_priority_csv="manual_ticker_repair_high_priority.csv",
                medium_csv="manual_ticker_repair_medium_production_like.csv",
                short_horizon=_short_horizon_packet_with_candidates(n=3),
                preflight_payload=preflight,
            )
            scrub = dict(result)
            scrub.pop("evidence_claim_not_allowed", None)
            joined = " ".join(_flatten_strings(scrub)).lower()
            for token in _BANNED_WORDS:
                self.assertNotIn(
                    token, joined,
                    f"banned token {token!r} surfaced in non-not-allowed text",
                )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def test_main_emits_valid_json_with_required_keys(self) -> None:
        import json as _json
        buf = StringIO()
        with patch.object(cli, "_run_repaired_cohort_summary",
                          return_value=_empty_repaired_summary()), \
             patch.object(cli, "_run_curated_candidate_status",
                          return_value=_empty_curated_status()), \
             patch.object(cli, "_run_short_horizon_repair_packet",
                          return_value=_empty_short_horizon_packet()), \
             patch.object(cli, "_run_benchmark_sensitivity_preflight",
                          return_value=_ready_preflight()):
            rc = cli.main(["--json"], out=buf)
        self.assertEqual(rc, 0)
        payload = _json.loads(buf.getvalue())
        self.assertEqual(set(payload.keys()), set(_REQUIRED_KEYS))

    def test_main_text_mode_emits_text_not_json(self) -> None:
        buf = StringIO()
        with patch.object(cli, "_run_repaired_cohort_summary",
                          return_value=_empty_repaired_summary()), \
             patch.object(cli, "_run_curated_candidate_status",
                          return_value=_empty_curated_status()), \
             patch.object(cli, "_run_short_horizon_repair_packet",
                          return_value=_empty_short_horizon_packet()), \
             patch.object(cli, "_run_benchmark_sensitivity_preflight",
                          return_value=_ready_preflight()):
            rc = cli.main([], out=buf)
        self.assertEqual(rc, 0)
        body = buf.getvalue()
        # Text mode must be human-readable, not raw JSON.
        self.assertNotEqual(body.lstrip()[:1], "{")


# ---------------------------------------------------------------------------
# source_mode + auto-sourcing
#
# The default no-args run must auto-discover local repaired-cohort inputs
# (the canonical CSVs + the most recent ``backups/events-*.db`` file) and
# materialize the 5-event repaired cohort truth when those files exist.
# Explicit CLI args win when supplied.  When neither path produces
# inputs, the block surfaces ``source_mode="not_sourced"`` with a list
# of exactly which inputs are missing.
# ---------------------------------------------------------------------------


class TestSourceModeAutoSourced(unittest.TestCase):
    def test_auto_sourced_when_local_inputs_exist(self) -> None:
        result = _summarize(
            repaired_summary=_five_event_repaired_summary(),
            discover_payload=_all_local_inputs(),
        )
        block = result["current_repaired_cohort"]
        self.assertEqual(block.get("status"), "sourced")
        self.assertEqual(block.get("source_mode"), "auto_sourced")
        self.assertEqual(block["repaired_clean_event_count"], 5)
        self.assertEqual(
            block["repaired_clean_event_ids"], [44, 51, 60, 73, 220],
        )

    def test_auto_sourced_invokes_summary_seam_with_discovered_paths(
        self,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_summary(**kwargs):
            captured.update(kwargs)
            return _five_event_repaired_summary()

        with patch.object(cli, "_run_repaired_cohort_summary",
                          side_effect=fake_summary), \
             patch.object(cli, "_run_curated_candidate_status",
                          return_value=_empty_curated_status()), \
             patch.object(cli, "_run_short_horizon_repair_packet",
                          return_value=_empty_short_horizon_packet()), \
             patch.object(cli, "_run_benchmark_sensitivity_preflight",
                          return_value=_ready_preflight()), \
             patch.object(cli, "_discover_local_repaired_inputs",
                          return_value=_all_local_inputs()):
            cli.build_evidence_cohort_status()
        # The discovered paths landed on the seam call — proves the
        # auto-source path actually wired discovery → summary.
        self.assertEqual(
            captured.get("backup_path"),
            "backups/events-20260507T095609.db",
        )
        self.assertEqual(
            captured.get("high_priority_csv"),
            "manual_ticker_repair_high_priority.csv",
        )
        self.assertEqual(
            captured.get("medium_csv"),
            "manual_ticker_repair_medium_production_like.csv",
        )

    def test_auto_sourced_works_without_optional_mechanism_family(
        self,
    ) -> None:
        result = _summarize(
            repaired_summary=_five_event_repaired_summary(),
            discover_payload=_all_local_inputs(mechanism_family=False),
        )
        block = result["current_repaired_cohort"]
        self.assertEqual(block.get("status"), "sourced")
        self.assertEqual(block.get("source_mode"), "auto_sourced")


class TestSourceModeExplicitArgs(unittest.TestCase):
    def test_explicit_args_set_source_mode_explicit_args(self) -> None:
        # Even when local files would auto-source, explicit args win.
        result = _summarize(
            repaired_summary=_five_event_repaired_summary(),
            backup_path="explicit/backup.db",
            high_priority_csv="explicit/high.csv",
            medium_csv="explicit/medium.csv",
            discover_payload=_all_local_inputs(),
        )
        block = result["current_repaired_cohort"]
        self.assertEqual(block.get("status"), "sourced")
        self.assertEqual(block.get("source_mode"), "explicit_args")

    def test_explicit_args_pass_through_explicit_paths(self) -> None:
        # The seam must receive the operator's paths verbatim, not
        # the discovered ones.
        captured: dict[str, Any] = {}

        def fake_summary(**kwargs):
            captured.update(kwargs)
            return _five_event_repaired_summary()

        with patch.object(cli, "_run_repaired_cohort_summary",
                          side_effect=fake_summary), \
             patch.object(cli, "_run_curated_candidate_status",
                          return_value=_empty_curated_status()), \
             patch.object(cli, "_run_short_horizon_repair_packet",
                          return_value=_empty_short_horizon_packet()), \
             patch.object(cli, "_run_benchmark_sensitivity_preflight",
                          return_value=_ready_preflight()), \
             patch.object(cli, "_discover_local_repaired_inputs",
                          return_value=_all_local_inputs()):
            cli.build_evidence_cohort_status(
                backup_path="explicit/backup.db",
                high_priority_csv="explicit/high.csv",
                medium_csv="explicit/medium.csv",
            )
        self.assertEqual(captured.get("backup_path"), "explicit/backup.db")
        self.assertEqual(
            captured.get("high_priority_csv"), "explicit/high.csv",
        )
        self.assertEqual(captured.get("medium_csv"), "explicit/medium.csv")


class TestSourceModeNotSourced(unittest.TestCase):
    def test_not_sourced_source_mode_when_nothing_found(self) -> None:
        result = _summarize(discover_payload=_no_local_inputs())
        block = result["current_repaired_cohort"]
        self.assertEqual(block.get("status"), "not_sourced")
        self.assertEqual(block.get("source_mode"), "not_sourced")

    def test_not_sourced_includes_missing_inputs_list(self) -> None:
        result = _summarize(discover_payload=_no_local_inputs())
        block = result["current_repaired_cohort"]
        missing = block.get("missing_inputs")
        self.assertIsInstance(missing, list)
        # All three required input names must appear.
        self.assertIn("backup_path", missing)
        self.assertIn("high_priority_csv", missing)
        self.assertIn("medium_csv", missing)


# ---------------------------------------------------------------------------
# _discover_local_repaired_inputs — read-only file-system probe
# ---------------------------------------------------------------------------


class TestDiscoverLocalRepairedInputs(unittest.TestCase):
    def test_returns_dict_with_expected_keys(self) -> None:
        # The seam must always return a dict carrying the four input
        # slots and a missing list — even when nothing exists on disk.
        # We isolate by pointing project root at a fresh temp dir
        # with no relevant files.
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(cli, "_PROJECT_ROOT", os.fspath(tmp)):
                payload = cli._discover_local_repaired_inputs()
        self.assertIsInstance(payload, dict)
        for key in (
            "backup_path", "high_priority_csv", "medium_csv",
            "mechanism_family_csv", "missing",
        ):
            self.assertIn(key, payload)

    def test_picks_most_recent_backup_when_multiple_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backups_dir = os.path.join(tmp, "backups")
            os.makedirs(backups_dir)
            # Older + newer ISO-timestamped names; the discovery must
            # pick the lex-greatest (newest by ISO timestamp).
            for name in (
                "events-20260101T000000.db",
                "events-20260507T095609.db",
                "events-20260306T010101.db",
            ):
                with open(os.path.join(backups_dir, name), "wb") as fh:
                    fh.write(b"fake-sqlite-bytes")
            for fname in (
                "manual_ticker_repair_high_priority.csv",
                "manual_ticker_repair_medium_production_like.csv",
            ):
                with open(os.path.join(tmp, fname), "w",
                          encoding="utf-8") as fh:
                    fh.write("event_id\n")
            with patch.object(cli, "_PROJECT_ROOT", os.fspath(tmp)):
                payload = cli._discover_local_repaired_inputs()
        self.assertIsNotNone(payload["backup_path"])
        self.assertTrue(
            payload["backup_path"].endswith("events-20260507T095609.db"),
            f"unexpected backup chosen: {payload['backup_path']!r}",
        )
        self.assertEqual(payload["missing"], [])

    def test_lists_missing_inputs_when_files_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Create only the medium CSV; others are missing.
            with open(
                os.path.join(
                    tmp, "manual_ticker_repair_medium_production_like.csv",
                ),
                "w", encoding="utf-8",
            ) as fh:
                fh.write("event_id\n")
            with patch.object(cli, "_PROJECT_ROOT", os.fspath(tmp)):
                payload = cli._discover_local_repaired_inputs()
        self.assertIn("backup_path", payload["missing"])
        self.assertIn("high_priority_csv", payload["missing"])
        self.assertNotIn("medium_csv", payload["missing"])


if __name__ == "__main__":
    unittest.main()
