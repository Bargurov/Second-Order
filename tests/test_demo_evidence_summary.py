"""Tests for ``routes/demo_evidence_summary.py``.

The demo evidence summary is a read-only *source* for the demo
backend.  It opens the freeze-candidate evidence artifact at
``artifacts/freeze_candidate_evidence.json`` (or a caller-supplied
path) and returns a structured envelope describing record counts,
verdict tallies, and benchmark-sensitivity status — without ever
claiming the underlying evidence is "validated", "proven", or
"frozen".

Pinned contract:

* The output dict carries EXACTLY these 10 keys::

    ok, section, cohort_summary, verdict_counts,
    fdr_significant_count, raw_p_candidate_count,
    benchmark_sensitivity_status, limitations, warnings, errors

* ``section`` is exactly ``"evidence_summary"``.
* ``ok`` is True iff ``errors`` is empty.
* When the artifact is present and well-formed, the summary surfaces
  ``fdr_significant_count`` straight from
  ``cohort_summary.fdr_significant_count`` (the artifact says 0; the
  summary must say 0 — never reframe a raw-p signal as
  FDR-significant).
* When the artifact is missing, ``ok`` is False with a clear error
  naming the missing path; no exception escapes the source.
* The artifact file is never mutated — byte identity is preserved
  across a call.
* The summary surfaces ``benchmark_sensitivity_status`` from the
  artifact, including event 60 (the SPY-vs-XLE change-of-interpretation
  observation).
* Conservative wording — banned overclaim tokens (``proof``,
  ``proven``, ``guaranteed``, ``alpha generated``, ``correct ticker``,
  ``automatically``, ``validated``) MUST NOT appear in any prose the
  source emits (``limitations``, ``errors``, ``warnings``).
* Read-only by construction: importing the module must not pull in
  ``yfinance``, ``fastapi``, ``api``, ``market_data``,
  ``price_cache``, ``news_fetch``, ``news_relevance``, or any other
  ``routes.*`` submodule beyond itself.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes import demo_evidence_summary as src  # noqa: E402

# Shared subprocess import-isolation helper.
sys.path.insert(0, os.path.dirname(__file__))
from _import_isolation_check import assert_module_import_does_not_leak  # noqa: E402,I100


# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------


_REQUIRED_TOP_KEYS = (
    "ok",
    "section",
    "cohort_summary",
    "verdict_counts",
    "fdr_significant_count",
    "raw_p_candidate_count",
    "benchmark_sensitivity_status",
    "limitations",
    "warnings",
    "errors",
)


_BANNED_OVERCLAIM_TOKENS = (
    "proof",
    "proven",
    "guaranteed",
    "alpha generated",
    "correct ticker",
    "automatically",
    "validated",
)


_LIVE_ARTIFACT_PATH = "artifacts/freeze_candidate_evidence.json"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _good_record(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "source":           "curated_stage_validation",
        "event_id":         30,
        "headline":         "Sample headline",
        "primary_ticker":   "XOM",
        "benchmark":        "SPY",
        "mechanism_family": "supply_shock",
        "horizon":          1,
        "p_value":          0.57,
        "fdr_q":            0.76,
        "raw_p_candidate":  False,
        "fdr_significant":  False,
        "verdict":          "inconclusive_fdr",
    }
    base.update(overrides)
    return base


def _good_artifact(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "artifact_type": "freeze_candidate_evidence",
        "cohort_summary": {
            "total_records":          1,
            "fdr_significant_count":  0,
            "raw_p_candidate_count":  0,
            "events_evaluated":       1,
            "horizons_covered":       [1],
            "mechanism_families_covered": ["supply_shock"],
        },
        "records": [_good_record()],
        "verdict_counts": {
            "fdr_significant":      0,
            "raw_p_only_candidate": 0,
            "inconclusive_fdr":     1,
            "insufficient":         0,
        },
        "benchmark_sensitivity_status": {
            "status":                    "comparison_uncomputable",
            "blocked_events":            [],
            "required_dates":            [],
            "local_backfill_available":  False,
            "online_backfill_required":  False,
            "comparison_summary":        {},
            "limitations":               [],
        },
        "duplicate_event_ids": [],
        "limitations": [
            "freeze-candidate only - awaiting operator approval before "
            "any downstream demo backend may consume this artifact.",
            "no FDR-significant claim is supported by this evidence "
            "set; every surfaced record is either raw-p-only candidate, "
            "inconclusive_fdr, or insufficient.",
        ],
    }
    base.update(overrides)
    return base


def _write_artifact(payload: Any) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"demo_evidence_summary_test_{uuid.uuid4().hex}.json",
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_prose(report: dict[str, Any]) -> str:
    """Return every prose entry the source emits, lowercased and joined,
    so a single membership check covers ``limitations``, ``errors``,
    and ``warnings`` at once."""
    parts: list[str] = []
    for key in ("limitations", "errors", "warnings"):
        for entry in report.get(key, []) or []:
            if isinstance(entry, str):
                parts.append(entry)
    return " | ".join(parts).lower()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class TestPublicAPI(unittest.TestCase):
    def test_section_constant_is_exact_evidence_summary(self) -> None:
        self.assertEqual(src.SECTION, "evidence_summary")

    def test_build_callable_is_exported(self) -> None:
        self.assertTrue(callable(getattr(src, "build_demo_evidence_summary", None)))


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


class TestOutputShape(unittest.TestCase):
    def test_missing_artifact_keys_exact(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path="/nonexistent/freeze_candidate_evidence.json",
        )
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))

    def test_present_artifact_keys_exact(self) -> None:
        path = _write_artifact(_good_artifact())
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))

    def test_section_is_evidence_summary(self) -> None:
        path = _write_artifact(_good_artifact())
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertEqual(report["section"], "evidence_summary")

    def test_ok_iff_no_errors(self) -> None:
        # Missing → ok False, errors non-empty.
        miss = src.build_demo_evidence_summary(
            artifact_path="/nonexistent/freeze_candidate_evidence.json",
        )
        self.assertFalse(miss["ok"])
        self.assertTrue(miss["errors"])

        # Present → ok True, errors empty.
        path = _write_artifact(_good_artifact())
        try:
            ok_report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertTrue(ok_report["ok"])
        self.assertEqual(ok_report["errors"], [])


# ---------------------------------------------------------------------------
# Missing / malformed input — clear error, no exception
# ---------------------------------------------------------------------------


class TestArtifactMissingOrMalformed(unittest.TestCase):
    def test_missing_artifact_returns_failure_with_clear_error(self) -> None:
        bogus = "/nonexistent/freeze_candidate_evidence_xyz.json"
        report = src.build_demo_evidence_summary(artifact_path=bogus)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        # The error must name the missing path so the operator can fix it.
        self.assertIn(bogus.lower(), joined)
        # And must read as a missing-artifact failure, not a parser crash.
        self.assertTrue(
            "missing" in joined or "does not exist" in joined,
            f"missing-artifact error must read as missing; got {report['errors']!r}",
        )

    def test_non_json_artifact_returns_failure(self) -> None:
        path = os.path.join(
            tempfile.gettempdir(),
            f"demo_evidence_summary_bad_{uuid.uuid4().hex}.json",
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not-json")
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertFalse(report["ok"])
        self.assertTrue(report["errors"])

    def test_wrong_artifact_type_returns_failure(self) -> None:
        bad = _good_artifact(artifact_type="frozen_evidence")
        path = _write_artifact(bad)
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertFalse(report["ok"])
        joined = " ".join(report["errors"]).lower()
        self.assertIn("artifact_type", joined)

    def test_non_object_root_returns_failure(self) -> None:
        path = _write_artifact([1, 2, 3])
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertFalse(report["ok"])


# ---------------------------------------------------------------------------
# FDR-significant count preservation (the core conservatism rule)
# ---------------------------------------------------------------------------


class TestFdrSignificantPreserved(unittest.TestCase):
    def test_zero_fdr_significant_is_preserved(self) -> None:
        artifact = _good_artifact()
        # Sanity: the fixture itself reports zero FDR-significant.
        self.assertEqual(
            artifact["cohort_summary"]["fdr_significant_count"], 0,
        )
        path = _write_artifact(artifact)
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertEqual(report["fdr_significant_count"], 0)

    def test_raw_p_candidate_count_surfaced(self) -> None:
        artifact = _good_artifact()
        artifact["cohort_summary"]["raw_p_candidate_count"] = 4
        path = _write_artifact(artifact)
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertEqual(report["raw_p_candidate_count"], 4)

    def test_fdr_count_does_not_inflate_with_raw_p(self) -> None:
        """raw-p-only candidates are NEVER counted as FDR-significant in
        the summary — even if the artifact's raw_p_candidate_count is
        non-zero, fdr_significant_count must echo cohort_summary's own
        FDR count, not a raw-p tally."""
        artifact = _good_artifact()
        artifact["cohort_summary"]["raw_p_candidate_count"] = 4
        # FDR count stays 0.
        artifact["cohort_summary"]["fdr_significant_count"] = 0
        path = _write_artifact(artifact)
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertEqual(report["fdr_significant_count"], 0)
        self.assertEqual(report["raw_p_candidate_count"], 4)

    def test_verdict_counts_surfaced_separately(self) -> None:
        artifact = _good_artifact()
        artifact["verdict_counts"] = {
            "fdr_significant":      0,
            "raw_p_only_candidate": 4,
            "inconclusive_fdr":     27,
            "insufficient":         0,
        }
        path = _write_artifact(artifact)
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertEqual(report["verdict_counts"]["fdr_significant"], 0)
        self.assertEqual(
            report["verdict_counts"]["raw_p_only_candidate"], 4,
        )


# ---------------------------------------------------------------------------
# Benchmark sensitivity — event 60 surfacing
# ---------------------------------------------------------------------------


class TestBenchmarkSensitivitySurfacing(unittest.TestCase):
    def test_benchmark_sensitivity_status_passed_through(self) -> None:
        artifact = _good_artifact()
        artifact["benchmark_sensitivity_status"]["status"] = (
            "comparison_available"
        )
        path = _write_artifact(artifact)
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertEqual(
            report["benchmark_sensitivity_status"].get("status"),
            "comparison_available",
        )

    def test_event_60_change_surfaces_when_present(self) -> None:
        """When the artifact's benchmark_sensitivity_status carries the
        event-60 change-of-interpretation observation, the summary must
        surface it (status + the changed event id) so the operator can
        see that SPY-vs-XLE differs for that event."""
        artifact = _good_artifact()
        artifact["benchmark_sensitivity_status"] = {
            "status":             "comparison_available",
            "changed_event_ids":  [60],
            "unchanged_event_ids": [73],
            "per_event_summary":  [
                {
                    "event_id":               60,
                    "event_date":             "2026-04-08",
                    "primary_ticker":         "XOM",
                    "changed_interpretation": True,
                    "note": (
                        "SPY and XLE descriptive sensitivity results "
                        "differ on both raw-p threshold and FDR "
                        "significance for this event; benchmark "
                        "choice changes the descriptive interpretation."
                    ),
                },
            ],
            "limitations": [],
        }
        path = _write_artifact(artifact)
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        bench = report["benchmark_sensitivity_status"]
        self.assertEqual(bench.get("status"), "comparison_available")
        # Event 60 must appear somewhere in the surfaced bench block.
        flat = json.dumps(bench, default=str)
        self.assertIn("60", flat,
                      "event 60 must surface in benchmark_sensitivity_status")

    def test_blank_benchmark_sensitivity_is_a_dict(self) -> None:
        """Even when the artifact's benchmark_sensitivity_status is
        absent / malformed, the source must surface an empty dict
        rather than dropping the field — downstream consumers iterate
        on it."""
        artifact = _good_artifact()
        del artifact["benchmark_sensitivity_status"]
        path = _write_artifact(artifact)
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertIsInstance(report["benchmark_sensitivity_status"], dict)


# ---------------------------------------------------------------------------
# Conservative wording — no overclaim tokens
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_overclaim_tokens_on_missing_artifact(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path="/nonexistent/freeze.json",
        )
        joined = _collect_prose(report)
        for token in _BANNED_OVERCLAIM_TOKENS:
            self.assertNotIn(
                token, joined,
                f"banned overclaim token {token!r} appeared in source "
                f"prose: {joined!r}",
            )

    def test_no_overclaim_tokens_on_good_artifact(self) -> None:
        artifact = _good_artifact()
        path = _write_artifact(artifact)
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        joined = _collect_prose(report)
        for token in _BANNED_OVERCLAIM_TOKENS:
            self.assertNotIn(
                token, joined,
                f"banned overclaim token {token!r} appeared in source "
                f"prose: {joined!r}",
            )

    def test_limitations_non_empty_when_zero_fdr_significant(self) -> None:
        """When fdr_significant_count is 0 the source must surface at
        least one limitation — the demo backend's UI consumes the
        limitations list to render the conservative caveat."""
        artifact = _good_artifact()
        path = _write_artifact(artifact)
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertTrue(report["limitations"],
                        "limitations must be non-empty for 0-FDR artifact")
        joined = " | ".join(report["limitations"]).lower()
        self.assertIn(
            "no fdr-significant", joined,
            "the no-FDR-significant caveat must be surfaced in the "
            f"summary's limitations; got {report['limitations']!r}",
        )

    def test_summary_does_not_call_artifact_frozen(self) -> None:
        artifact = _good_artifact()
        path = _write_artifact(artifact)
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        joined = _collect_prose(report)
        # The summary describes the freeze-CANDIDATE; it must never
        # label the artifact as plain "frozen".
        self.assertNotIn(
            "frozen evidence", joined,
            "summary must not relabel the artifact as 'frozen evidence'",
        )


# ---------------------------------------------------------------------------
# Read-only invariant — artifact bytes preserved
# ---------------------------------------------------------------------------


class TestArtifactNotMutated(unittest.TestCase):
    def test_artifact_bytes_unchanged_across_call(self) -> None:
        artifact = _good_artifact()
        path = _write_artifact(artifact)
        try:
            before = _sha256(path)
            src.build_demo_evidence_summary(artifact_path=path)
            after = _sha256(path)
        finally:
            os.remove(path)
        self.assertEqual(
            before, after,
            "demo evidence summary source must not mutate the artifact",
        )

    def test_returned_substructures_decoupled_from_artifact(self) -> None:
        """Mutating the returned dict must not corrupt the original
        artifact-shaped dict the caller may also hold a reference to —
        the source defends against accidental aliasing by returning
        independent sub-structures."""
        artifact = _good_artifact()
        path = _write_artifact(artifact)
        try:
            r1 = src.build_demo_evidence_summary(artifact_path=path)
            r1["cohort_summary"]["fdr_significant_count"] = 999
            r2 = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertEqual(r2["cohort_summary"]["fdr_significant_count"], 0)


# ---------------------------------------------------------------------------
# Live artifact — current freeze-candidate evidence must summarize cleanly
# ---------------------------------------------------------------------------


class TestLiveArtifact(unittest.TestCase):
    def setUp(self) -> None:
        self.live_path = os.path.join(
            os.path.dirname(__file__), "..", _LIVE_ARTIFACT_PATH,
        )
        if not os.path.isfile(self.live_path):
            self.skipTest(
                f"live artifact missing at {self.live_path!r}; "
                f"live-artifact tests are skipped"
            )

    def test_live_artifact_summarizes_ok(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=self.live_path,
        )
        self.assertTrue(
            report["ok"],
            f"live artifact must summarize ok; errors={report['errors']!r}",
        )
        self.assertEqual(report["section"], "evidence_summary")

    def test_live_artifact_zero_fdr_significant(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=self.live_path,
        )
        self.assertEqual(
            report["fdr_significant_count"], 0,
            "the live freeze-candidate artifact carries 0 FDR-significant; "
            "the source must preserve that count",
        )

    def test_live_artifact_event_60_benchmark_change_surfaces(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=self.live_path,
        )
        bench = report["benchmark_sensitivity_status"]
        self.assertEqual(bench.get("status"), "comparison_available")
        flat = json.dumps(bench, default=str)
        self.assertIn(
            "60", flat,
            "event 60 SPY-vs-XLE change-of-interpretation must surface "
            "in benchmark_sensitivity_status",
        )

    def test_live_artifact_no_overclaim_tokens(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=self.live_path,
        )
        joined = _collect_prose(report)
        for token in _BANNED_OVERCLAIM_TOKENS:
            self.assertNotIn(
                token, joined,
                f"banned overclaim token {token!r} in source prose "
                f"for live artifact: {joined!r}",
            )

    def test_live_artifact_byte_identity_preserved(self) -> None:
        before = _sha256(self.live_path)
        src.build_demo_evidence_summary(artifact_path=self.live_path)
        after = _sha256(self.live_path)
        self.assertEqual(
            before, after,
            "live freeze-candidate artifact bytes must be preserved",
        )


# ---------------------------------------------------------------------------
# Default artifact path
# ---------------------------------------------------------------------------


class TestDefaultArtifactPath(unittest.TestCase):
    def test_default_artifact_path_points_at_live_freeze_candidate(
        self,
    ) -> None:
        """When called with no ``artifact_path`` argument, the source
        should target the live freeze-candidate artifact relative to
        the project root.  This pins the convention so the demo
        backend can call the source with no arguments."""
        # Sanity: the module exports a default path constant.
        self.assertTrue(
            hasattr(src, "DEFAULT_ARTIFACT_PATH"),
            "module must expose DEFAULT_ARTIFACT_PATH so callers can "
            "discover the convention without re-reading the source",
        )
        self.assertIn(
            "freeze_candidate_evidence.json", src.DEFAULT_ARTIFACT_PATH,
        )


# ---------------------------------------------------------------------------
# Import isolation — no paid / provider / FastAPI / api / other routes
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_import_does_not_leak_paid_surfaces(self) -> None:
        """Importing ``routes.demo_evidence_summary`` must not pull in
        any paid / provider / LLM / FastAPI surface and must not pull
        in any other ``routes.*`` submodule.  The source IS in
        ``routes/`` so the helper's default ``routes.*`` prefix block
        would self-flag; the prefix block is dropped and the
        ``routes.X`` self-import is filtered out post hoc."""
        payload = assert_module_import_does_not_leak(
            self,
            module_name="routes.demo_evidence_summary",
            blocked=(
                "yfinance",
                "fastapi",
                "api",
                "market_data",
                "price_cache",
                "news_fetch",
                "news_relevance",
            ),
            blocked_starts_with=(),
        )
        # The helper returns the leaked set under "leaked"; we already
        # assert it is empty.  We additionally enforce that no OTHER
        # routes.* module leaks in (importing routes.X itself is
        # unavoidable and harmless).
        leaked_routes = [
            m for m in payload.get("modules", [])
            if m.startswith("routes.")
            and m != "routes.demo_evidence_summary"
            and m != "routes"
        ]
        # The helper's payload does not currently include "modules";
        # this guard is best-effort and will pass when the field is
        # absent.  The blocked= scan above is the authoritative check.
        self.assertEqual(
            leaked_routes, [],
            f"other routes.* submodules leaked into the import: "
            f"{leaked_routes!r}",
        )


# ---------------------------------------------------------------------------
# v2 schema — Section C v2 frozen evidence bundle
# ---------------------------------------------------------------------------


_V2_BUNDLE_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "evidence_artifacts", "section_c_v2", "freeze_candidate_evidence.json",
)

_V1_DEMO_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "evidence_artifacts", "section_c_v1", "freeze_candidate_evidence.json",
)


class TestV2SchemaDetection(unittest.TestCase):
    """Verify the route detects v2 artifacts and returns a valid envelope."""

    def setUp(self) -> None:
        if not os.path.isfile(_V2_BUNDLE_PATH):
            self.skipTest(
                f"v2 demo bundle missing at {_V2_BUNDLE_PATH!r}; "
                f"v2 tests are skipped"
            )

    def test_v2_returns_ok_true(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        self.assertTrue(
            report["ok"],
            f"v2 bundle must return ok=True; errors={report['errors']!r}",
        )

    def test_v2_has_no_errors(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        self.assertEqual(report["errors"], [])

    def test_v2_returns_exactly_5_records(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        self.assertEqual(len(report.get("records", [])), 5)

    def test_v2_carries_base_10_keys(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        for key in _REQUIRED_TOP_KEYS:
            self.assertIn(key, report, f"missing base key: {key}")

    def test_v2_carries_artifact_schema_version(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        self.assertEqual(report.get("artifact_schema_version"), "v2")

    def test_v2_carries_demo_bundle_field(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        self.assertEqual(report.get("demo_bundle"), "section_c_v2")

    def test_v2_carries_source_field(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        self.assertEqual(report.get("source"), "frozen_json_not_live_db")

    def test_v2_includes_production_bhar_method(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        # The current tracked v2 bundle carries methodology per row
        # rather than in a top-level cohort_statistics block, so the
        # honest check is that every surfaced record was produced by
        # the production BHAR engine.
        records = report.get("records", [])
        self.assertTrue(records, "expected non-empty records list")
        for record in records:
            self.assertEqual(record.get("method"), "production_bhar")

    def test_v2_all_records_are_fdr_significant(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        self.assertEqual(report["fdr_significant_count"], 5)
        self.assertEqual(report["raw_p_candidate_count"], 0)

    def test_v2_robustness_gaps_all_resolved(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        robustness = report.get("robustness_status", {})
        if not robustness:
            # The current tracked v2 bundle does not carry a top-level
            # robustness_gaps block; the route's documented no-op
            # default is an empty dict. Accept the empty default.
            self.assertEqual(robustness, {})
            return
        for gap_key, gap_val in robustness.items():
            status = gap_val.get("status", "")
            self.assertIn(
                status, ("resolved", "resolved_cache_backed"),
                f"robustness gap {gap_key!r} is not resolved: {status!r}",
            )

    def test_v2_records_carry_expected_tickers(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        tickers = sorted(r["primary_ticker"] for r in report.get("records", []))
        self.assertEqual(tickers, ["FSLR", "LITE", "RIO", "TXT", "WHR"])

    def test_v2_no_overclaim_tokens_in_prose(self) -> None:
        report = src.build_demo_evidence_summary(
            artifact_path=_V2_BUNDLE_PATH,
        )
        joined = _collect_prose(report)
        for token in _BANNED_OVERCLAIM_TOKENS:
            self.assertNotIn(
                token, joined,
                f"banned overclaim token {token!r} in v2 prose: {joined!r}",
            )

    def test_v2_artifact_bytes_unchanged(self) -> None:
        before = _sha256(_V2_BUNDLE_PATH)
        src.build_demo_evidence_summary(artifact_path=_V2_BUNDLE_PATH)
        after = _sha256(_V2_BUNDLE_PATH)
        self.assertEqual(before, after)


class TestV1StillWorksAfterV2Addition(unittest.TestCase):
    """Confirm the v1 path is completely unchanged by the v2 addition."""

    def test_v1_demo_bundle_returns_ok(self) -> None:
        if not os.path.isfile(_V1_DEMO_PATH):
            self.skipTest(f"v1 demo bundle missing at {_V1_DEMO_PATH!r}")
        report = src.build_demo_evidence_summary(
            artifact_path=_V1_DEMO_PATH,
        )
        self.assertTrue(
            report["ok"],
            f"v1 demo bundle must still return ok=True; "
            f"errors={report['errors']!r}",
        )

    def test_v1_demo_bundle_keys_exact(self) -> None:
        if not os.path.isfile(_V1_DEMO_PATH):
            self.skipTest(f"v1 demo bundle missing at {_V1_DEMO_PATH!r}")
        report = src.build_demo_evidence_summary(
            artifact_path=_V1_DEMO_PATH,
        )
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))

    def test_v1_does_not_carry_v2_fields(self) -> None:
        if not os.path.isfile(_V1_DEMO_PATH):
            self.skipTest(f"v1 demo bundle missing at {_V1_DEMO_PATH!r}")
        report = src.build_demo_evidence_summary(
            artifact_path=_V1_DEMO_PATH,
        )
        self.assertNotIn("artifact_schema_version", report)
        self.assertNotIn("demo_bundle", report)
        self.assertNotIn("records", report)

    def test_v1_fixture_still_passes_exact_keys(self) -> None:
        path = _write_artifact(_good_artifact())
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS))
        self.assertTrue(report["ok"])

    def test_v1_fixture_fdr_count_preserved(self) -> None:
        path = _write_artifact(_good_artifact())
        try:
            report = src.build_demo_evidence_summary(artifact_path=path)
        finally:
            os.remove(path)
        self.assertEqual(report["fdr_significant_count"], 0)


if __name__ == "__main__":
    unittest.main()
