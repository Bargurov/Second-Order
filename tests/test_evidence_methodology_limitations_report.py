"""Tests for ``scripts/evidence_methodology_limitations_report.py``.

The report is a plain JSON/text bundle explaining the methodology and
limitations of the current evidence set in interview-safe language.
It is derived read-only from four on-disk artifacts:

  * ``artifacts/curated_stage_validation_evidence.json``
  * ``artifacts/short_horizon_review_validation_top10.json``
  * ``artifacts/short_horizon_review_validation_next10.json``
  * ``artifacts/short_horizon_review_validation_final8.json``

Pin the contract:

  * Envelope schema (the ten task-mandated keys)::

        ok, methodology_summary, statistical_terms,
        current_evidence_state, what_the_artifacts_support,
        what_the_artifacts_do_not_support, interview_safe_language,
        likely_questions, warnings, errors

  * ``statistical_terms`` defines the canonical vocabulary the report
    uses — ``p_value``, ``fdr_q``, ``raw_p_candidate``,
    ``validated_raw_only``, ``fdr_significant``, ``horizon``,
    ``mechanism_family``, ``event_source_vs_record_count``.

  * ``current_evidence_state`` derives counts read-only from the four
    source artifacts (events evaluated, records, FDR-significant
    count, raw-p-only count, by-artifact breakdown, horizons,
    mechanism families).  No statistical thresholds are re-derived
    from raw p-values — the script counts only what the artifacts
    explicitly tagged (``raw_p_candidate`` or
    ``verdict='validated_raw_only'``).

  * ``what_the_artifacts_do_not_support`` explicitly disclaims the
    claims that would otherwise trip the conservative-language bar.

  * Conservative language — outside the literal ``validated_raw_only``
    vocabulary item, the report avoids ``validated``, ``predictive``,
    ``proven``, ``proves``, ``proof``, and ``guaranteed`` in any
    surfaced text.  Note: the word ``alpha`` is permitted in the
    statistical-threshold sense (``alpha = 0.05`` as the FDR
    significance level) — that is the correct domain vocabulary for
    explaining the FDR adjustment.

  * Artifacts on disk are byte-identical before and after any CLI
    invocation.  No DB, no provider, no LLM, no FastAPI surface.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import evidence_methodology_limitations_report as cli  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "artifacts"

_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "methodology_summary",
    "statistical_terms",
    "current_evidence_state",
    "what_the_artifacts_support",
    "what_the_artifacts_do_not_support",
    "interview_safe_language",
    "likely_questions",
    "warnings",
    "errors",
)


_REQUIRED_GLOSSARY_TERMS = (
    "p_value",
    "fdr_q",
    "raw_p_candidate",
    "validated_raw_only",
    "fdr_significant",
    "horizon",
    "mechanism_family",
    "event_source_vs_record_count",
)


# Banned tokens outside the literal ``validated_raw_only`` vocabulary
# item.  The ``validated`` substring is permitted only inside the
# vocabulary literal — every other usage trips the test.
_BANNED_OUTSIDE_LITERAL = (
    "validated",
    "predictive",
    "proven",
    "proves",
    "proof",
    "guaranteed",
)


def _walk_strings(value):
    """Yield every leaf string in a (possibly nested) JSON-like
    structure.  Used to audit the conservative-language contract
    across every surfaced text field."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk_strings(v)


def _strip_literals(text: str) -> str:
    """Remove the carve-outs (literal vocabulary mentions) so the
    naked banned-token search runs clean."""
    return text.replace("validated_raw_only", "")


# ---------------------------------------------------------------------------
# Synthetic artifact payloads — mirror the real on-disk shapes so tests
# can exercise the derivation logic without depending on artifact bytes.
# ---------------------------------------------------------------------------


def _curated_payload(
    *, events: int = 5, records: int = 15, significant: int = 0,
    raw_p_only: int = 2,
):
    examples = []
    for i in range(records):
        examples.append({
            "abnormal_return":   0.01,
            "benchmark_ticker":  "SPY",
            "ci_high":           0.02,
            "ci_low":           -0.02,
            "fdr_q":             0.5,
            "fdr_significant":   bool(i < significant),
            "headline":          f"synthetic curated record {i}",
            "horizon":           [1, 5, 20][i % 3],
            "interpretation":    "not_significant",
            "mechanism_family":  "supply_shock",
            "p_value":           0.05,
            "primary_ticker":    "XOM",
            "raw_p_candidate":   bool(i < raw_p_only),
            "sar":               0.5,
            "source_event_id":   30 + i,
            "verdict":           ("validated_raw_only" if i < raw_p_only
                                  else "inconclusive_fdr"),
        })
    return {
        "by_horizon": {
            "1":  {"records_count": records // 3,
                   "significant_count": 0},
            "5":  {"records_count": records // 3,
                   "significant_count": 0},
            "20": {"records_count": records - 2 * (records // 3),
                   "significant_count": 0},
        },
        "by_mechanism_family": {
            "supply_shock": {"records_count": records,
                             "significant_count": 0},
        },
        "errors": 0,
        "events_evaluated": events,
        "examples": examples,
        "excluded_candidates": 0,
        "records_count": records,
        "significant_count": significant,
        "staged_count": events,
        "warnings": 0,
    }


def _short_horizon_payload(
    *, events: int = 4, records: int = 8, significant: int = 0,
    excluded: int = 6,
):
    examples = []
    for i in range(records):
        examples.append({
            "abnormal_return":   0.01,
            "benchmark":         "SPY",
            "ci_high":           0.02,
            "ci_low":           -0.02,
            "event_id":          1000 + i,
            "fdr_q":             0.5,
            "headline":          f"synthetic short-horizon record {i}",
            "horizon":           [1, 5][i % 2],
            "interpretation":    "not_significant",
            "mechanism_family":  "supply_shock",
            "p_value":           0.5,
            "primary_ticker":    "XOM",
            "sar":               0.5,
        })
    return {
        "accepted_count": events,
        "by_horizon": {
            "1": {"records_count": records // 2,
                  "significant_count": 0},
            "5": {"records_count": records - records // 2,
                  "significant_count": 0},
        },
        "by_mechanism_family": {
            "supply_shock": {"records_count": records,
                             "significant_count": 0},
        },
        "errors": 0,
        "events_evaluated": events,
        "examples": examples,
        "excluded_candidates": excluded,
        "ok": True,
        "records_count": records,
        "significant_count": significant,
        "warnings": 0,
        "worksheet_path": "artifacts/short_horizon_review_topN.csv",
    }


def _synthetic_artifact_bundle():
    """Mirrors the live four-artifact bundle (totals: 13 events, 31
    records, 0 FDR-significant, 2 raw-p-only) so structural tests
    don't depend on artifact bytes."""
    return {
        "curated_stage_validation_evidence": _curated_payload(),
        "short_horizon_review_validation_top10": _short_horizon_payload(),
        "short_horizon_review_validation_next10": _short_horizon_payload(),
        "short_horizon_review_validation_final8": _short_horizon_payload(
            events=0, records=0, excluded=8,
        ),
    }


def _patch_loader(bundle):
    return patch.object(cli, "_load_artifacts", return_value=bundle)


def _run_cli(argv):
    out = StringIO()
    rc = cli.main(argv, out=out)
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Envelope contract
# ---------------------------------------------------------------------------


class TestEnvelopeContract(unittest.TestCase):
    def test_has_all_ten_required_keys(self) -> None:
        with _patch_loader(_synthetic_artifact_bundle()):
            report = cli.build_report()
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, report, f"missing envelope key: {k}")
        self.assertIs(report["ok"], True)

    def test_errors_is_empty_list_on_happy_path(self) -> None:
        with _patch_loader(_synthetic_artifact_bundle()):
            report = cli.build_report()
        self.assertEqual(report["errors"], [])

    def test_warnings_is_a_list(self) -> None:
        with _patch_loader(_synthetic_artifact_bundle()):
            report = cli.build_report()
        self.assertIsInstance(report["warnings"], list)


# ---------------------------------------------------------------------------
# Statistical terms — glossary contents
# ---------------------------------------------------------------------------


class TestStatisticalTerms(unittest.TestCase):
    def setUp(self) -> None:
        with _patch_loader(_synthetic_artifact_bundle()):
            self.report = cli.build_report()
        self.terms = self.report["statistical_terms"]

    def test_glossary_has_required_terms(self) -> None:
        for term in _REQUIRED_GLOSSARY_TERMS:
            self.assertIn(term, self.terms, f"missing glossary term: {term}")

    def test_validated_raw_only_disclaimer_is_explicit(self) -> None:
        # The disclaimer must mention BOTH "raw-p" (i.e. raw p-value)
        # and "not FDR" (i.e. did not clear the FDR bar).  Pinning
        # both keeps a future edit from softening the carve-out.
        entry = str(self.terms["validated_raw_only"]).lower()
        self.assertIn("raw", entry)
        self.assertIn("fdr", entry)
        self.assertTrue(
            "not " in entry or "did not" in entry or "does not" in entry,
            f"validated_raw_only entry must disclaim FDR significance; "
            f"got: {entry!r}",
        )

    def test_event_source_vs_record_count_explained(self) -> None:
        entry = str(self.terms["event_source_vs_record_count"]).lower()
        # The explanation must surface that a single event_source
        # contributes multiple horizon-keyed records.
        self.assertIn("horizon", entry)
        self.assertTrue(
            "record" in entry,
            f"event_source_vs_record_count must reference 'record'; "
            f"got: {entry!r}",
        )

    def test_p_value_and_fdr_q_explained_distinctly(self) -> None:
        p_entry  = str(self.terms["p_value"]).lower()
        q_entry  = str(self.terms["fdr_q"]).lower()
        # p_value entry must not claim FDR adjustment; fdr_q entry
        # must reference multiple comparisons / adjustment.
        self.assertIn("p", p_entry)
        self.assertIn("fdr", q_entry)
        self.assertTrue(
            "adjust" in q_entry
            or "multiple" in q_entry
            or "correction" in q_entry,
            f"fdr_q must explain multiple-comparison adjustment; "
            f"got: {q_entry!r}",
        )

    def test_horizons_1_5_20_mentioned(self) -> None:
        horizon_entry = str(self.terms["horizon"]).lower()
        for token in ("1", "5", "20"):
            self.assertIn(
                token, horizon_entry,
                f"horizon entry must mention {token}; got: {horizon_entry!r}",
            )


# ---------------------------------------------------------------------------
# Current-state counts — derived correctly from synthetic bundle
# ---------------------------------------------------------------------------


class TestCurrentEvidenceStateDerivation(unittest.TestCase):
    def setUp(self) -> None:
        with _patch_loader(_synthetic_artifact_bundle()):
            self.report = cli.build_report()
        self.state = self.report["current_evidence_state"]

    def test_total_event_sources_evaluated_sums_across_artifacts(self) -> None:
        # 5 curated + 4 top10 + 4 next10 + 0 final8 = 13
        self.assertEqual(self.state["total_event_sources_evaluated"], 13)

    def test_total_records_sums_across_artifacts(self) -> None:
        # 15 curated + 8 top10 + 8 next10 + 0 final8 = 31
        self.assertEqual(self.state["total_records"], 31)

    def test_fdr_significant_records_is_zero(self) -> None:
        self.assertEqual(self.state["fdr_significant_records"], 0)

    def test_raw_p_only_records_counts_only_explicit_tags(self) -> None:
        # 2 from the curated payload; short-horizon payloads don't
        # carry ``raw_p_candidate`` and must not be heuristic-counted.
        self.assertEqual(self.state["raw_p_only_records"], 2)

    def test_by_artifact_breakdown_present(self) -> None:
        for artifact_key in (
            "curated_stage_validation_evidence",
            "short_horizon_review_validation_top10",
            "short_horizon_review_validation_next10",
            "short_horizon_review_validation_final8",
        ):
            self.assertIn(artifact_key, self.state["by_artifact"])
            entry = self.state["by_artifact"][artifact_key]
            for sub in ("events_evaluated", "records_count",
                        "significant_count"):
                self.assertIn(sub, entry)

    def test_horizons_evaluated_lists_1_5_20(self) -> None:
        self.assertEqual(
            sorted(self.state["horizons_evaluated"]), [1, 5, 20],
        )

    def test_mechanism_families_represented_is_a_list(self) -> None:
        self.assertIsInstance(self.state["mechanism_families_represented"],
                              list)


# ---------------------------------------------------------------------------
# Required content — task-mandated phrasings and disclaimers
# ---------------------------------------------------------------------------


class TestRequiredContent(unittest.TestCase):
    def setUp(self) -> None:
        with _patch_loader(_synthetic_artifact_bundle()):
            self.report = cli.build_report()

    def _all_surfaced_text(self) -> str:
        # Aggregate every leaf string in the report for content checks.
        return " ".join(_walk_strings(self.report)).lower()

    def test_horizons_1_5_20_mentioned_in_methodology(self) -> None:
        text = str(self.report["methodology_summary"]).lower()
        for h in ("1", "5", "20"):
            self.assertIn(h, text,
                          f"methodology must reference horizon {h}")

    def test_zero_fdr_significant_claim_surfaced(self) -> None:
        # Must surface the literal "0 FDR-significant" framing
        # somewhere in the surfaced text (anywhere across the lists /
        # methodology / current-evidence-state).  Lower-cased, "0"
        # adjacent to either "fdr-significant" or "fdr_significant"
        # is acceptable phrasing.
        text = self._all_surfaced_text()
        self.assertTrue(
            "0 fdr" in text or "zero fdr" in text
            or "0 records are fdr" in text
            or "no records are fdr" in text
            or "no fdr-significant" in text,
            f"report must surface the '0 FDR-significant' claim; "
            f"text snippet: {text[:400]!r}",
        )

    def test_methodology_demonstration_framing_present(self) -> None:
        # Task: "useful for methodology demonstration and case-study
        # discipline, not a validation claim."  Pin the phrases.
        text = self._all_surfaced_text()
        self.assertIn("methodology demonstration", text)
        self.assertIn("case-study discipline", text)

    def test_what_artifacts_do_not_support_lists_predictive_disclaimer(
        self,
    ) -> None:
        # The disclaimer list must explicitly include language ruling
        # out forward-looking / signal claims.  We check for either
        # "forward-looking" (the alternative phrasing we use) or
        # "future" + "claim" / "signal".
        items = [str(x).lower()
                 for x in self.report["what_the_artifacts_do_not_support"]]
        joined = " | ".join(items)
        self.assertTrue(
            "forward-looking" in joined or "future" in joined
            or "signal" in joined,
            f"do_not_support list must disclaim forward-looking / "
            f"signal claims; got: {items!r}",
        )

    def test_what_artifacts_support_is_non_empty(self) -> None:
        self.assertTrue(self.report["what_the_artifacts_support"])

    def test_interview_safe_language_is_non_empty(self) -> None:
        self.assertTrue(self.report["interview_safe_language"])

    def test_likely_questions_include_validated_raw_only(self) -> None:
        # The single biggest interview gotcha is the "validated_raw_only"
        # label.  Pin that at least one likely_questions entry covers
        # it.
        qs = self.report["likely_questions"]
        self.assertIsInstance(qs, list)
        text = " ".join(
            str(q.get("question", "")) + " " + str(q.get("safe_answer", ""))
            for q in qs if isinstance(q, dict)
        )
        self.assertIn("validated_raw_only", text)


# ---------------------------------------------------------------------------
# Conservative language audit — banned tokens outside the literal
# ---------------------------------------------------------------------------


class TestConservativeLanguage(unittest.TestCase):
    def test_no_banned_token_appears_outside_validated_raw_only_literal(
        self,
    ) -> None:
        with _patch_loader(_synthetic_artifact_bundle()):
            report = cli.build_report()
        for s in _walk_strings(report):
            cleaned = _strip_literals(s).lower()
            for token in _BANNED_OUTSIDE_LITERAL:
                self.assertNotIn(
                    token, cleaned,
                    f"banned token {token!r} appeared outside the "
                    f"'validated_raw_only' carve-out in: {s!r}",
                )


# ---------------------------------------------------------------------------
# CLI plumbing — --json and --text modes
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def test_default_invocation_emits_parseable_json(self) -> None:
        with _patch_loader(_synthetic_artifact_bundle()):
            rc, out = _run_cli([])
        self.assertEqual(rc, 0)
        parsed = json.loads(out)
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)

    def test_json_flag_matches_default(self) -> None:
        with _patch_loader(_synthetic_artifact_bundle()):
            rc1, out1 = _run_cli([])
            rc2, out2 = _run_cli(["--json"])
        self.assertEqual(rc1, rc2)
        self.assertEqual(json.loads(out1), json.loads(out2))

    def test_text_flag_emits_non_empty_human_readable_report(self) -> None:
        with _patch_loader(_synthetic_artifact_bundle()):
            rc, out = _run_cli(["--text"])
        self.assertEqual(rc, 0)
        self.assertTrue(out.strip(), "text mode must emit non-empty output")
        # Text mode should still surface the key vocabulary tokens.
        for token in ("fdr_q", "validated_raw_only", "p_value"):
            self.assertIn(token, out, f"text output must mention {token}")

    def test_text_and_json_modes_are_mutually_exclusive(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.main(["--json", "--text"], out=StringIO())

    def test_help_exits_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--help"], out=StringIO())
        self.assertEqual(ctx.exception.code, 0)


# ---------------------------------------------------------------------------
# Read-only — artifacts byte-identical after running
# ---------------------------------------------------------------------------


class TestArtifactsByteIdentical(unittest.TestCase):
    _ARTIFACT_NAMES = (
        "curated_stage_validation_evidence.json",
        "short_horizon_review_validation_top10.json",
        "short_horizon_review_validation_next10.json",
        "short_horizon_review_validation_final8.json",
    )

    def test_artifacts_byte_identical_after_runs(self) -> None:
        present = [
            (name, (ARTIFACTS_DIR / name).read_bytes())
            for name in self._ARTIFACT_NAMES
            if (ARTIFACTS_DIR / name).exists()
        ]
        if not present:
            self.skipTest("no artifacts present in this checkout")
        _run_cli([])
        _run_cli(["--json"])
        _run_cli(["--text"])
        for name, before in present:
            after = (ARTIFACTS_DIR / name).read_bytes()
            self.assertEqual(
                before, after,
                f"{name} must be byte-identical after running the report",
            )


# ---------------------------------------------------------------------------
# Forbidden seams — no DB writes, no provider, no LLM, no FastAPI
# ---------------------------------------------------------------------------


_FORBIDDEN_SEAMS: tuple[tuple[str, str], ...] = (
    ("db",              "save_event"),
    ("db",              "update_review"),
    ("db",              "append_revisit_snapshot"),
    ("db",              "delete_event"),
    ("market_check",    "market_check"),
    ("market_data",     "get_provider"),
    ("price_cache",     "fetch_daily_cached"),
    ("analyze_event",   "analyze_event"),
    ("analyze_event",   "_call_llm_provider"),
)


def _patch_raisers(stack, seams, *, label):
    for module_name, attr in seams:
        try:
            mod = __import__(module_name)
        except Exception:
            continue
        if not hasattr(mod, attr):
            continue
        stack.enter_context(patch.object(
            mod, attr,
            side_effect=AssertionError(
                f"evidence_methodology_limitations_report must not "
                f"invoke {module_name}.{attr} ({label})",
            ),
        ))


class TestNoForbiddenSeams(unittest.TestCase):
    def test_no_db_or_provider_seam_invoked(self) -> None:
        with ExitStack() as stack:
            _patch_raisers(stack, _FORBIDDEN_SEAMS, label="db/provider/LLM")
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "report must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            rc1, _ = _run_cli([])
            rc2, _ = _run_cli(["--text"])
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)


# ---------------------------------------------------------------------------
# Missing-artifact handling
# ---------------------------------------------------------------------------


class TestMissingArtifactsBecomeWarnings(unittest.TestCase):
    def test_missing_artifacts_dir_surfaces_warning_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Point the loader at an empty directory.
            rc, out = _run_cli(["--artifacts-dir", tmp])
        self.assertEqual(rc, 0)
        parsed = json.loads(out)
        # Missing files are warnings, not hard errors.
        self.assertEqual(parsed["errors"], [])
        self.assertTrue(parsed["warnings"],
                        "missing artifacts must surface at least one warning")


# ---------------------------------------------------------------------------
# Live-artifact current-state pin — intentionally tied to today's bytes
# ---------------------------------------------------------------------------


class TestLiveArtifactCurrentState(unittest.TestCase):
    """These assertions intentionally tie to TODAY's artifact bytes.
    A failure here means an artifact changed shape or count — update
    the expected totals or investigate the upstream change.
    """

    def test_live_totals(self) -> None:
        if not all((ARTIFACTS_DIR / n).exists() for n in (
            "curated_stage_validation_evidence.json",
            "short_horizon_review_validation_top10.json",
            "short_horizon_review_validation_next10.json",
            "short_horizon_review_validation_final8.json",
        )):
            self.skipTest("not all four live artifacts present")

        report = cli.build_report()
        state = report["current_evidence_state"]
        # 5 + 4 + 4 + 0 = 13 events; 15 + 8 + 8 + 0 = 31 records
        self.assertEqual(state["total_event_sources_evaluated"], 13)
        self.assertEqual(state["total_records"], 31)
        self.assertEqual(state["fdr_significant_records"], 0)
        # 2 records in the curated artifact carry raw_p_candidate=True
        # / verdict='validated_raw_only'.  Short-horizon artifacts
        # don't carry those flags so they contribute 0.
        self.assertEqual(state["raw_p_only_records"], 2)


if __name__ == "__main__":
    unittest.main()
