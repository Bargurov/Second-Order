"""Tests for ``scripts/stat_validation_demo_report.py``.

The demo report sits on top of two seams:

* ``scripts.stat_validation_smoke`` provides the deterministic synthetic
  asset/benchmark generator (private ``_make_synthetic_pair``).
* ``stats.validation_pipeline.run_validation_pipeline`` composes the
  canonical ``stat_validation`` records from the cohort's event-study
  outputs.

What we pin
-----------
* The required top-level JSON keys: ``records_count``,
  ``significant_count``, ``horizons``, ``methodology_summary``,
  ``interpretation_summary``.
* Methodology and interpretation summaries use conservative language —
  no "proof" or "alpha" claim language.  These are interview/CV
  artifacts; the words an external reader would interpret as
  market-edge claims must NOT appear.
* The methodology references the underlying surfaces (event-study,
  bootstrap CI, FDR, validation_pipeline, smoke) so an external reader
  can trace the report back to the modules.
* The interpretation summary reflects the run's actual counts so a
  reader sees the live numbers, not a stale string.
* Determinism: same seed yields byte-equal JSON output.
* CLI exit code matches ``payload["ok"]`` and both ``--json`` and the
  default text mode emit a usable rendering.
* Banned-imports guard: the report does not pull in DB / provider /
  yfinance / LLM / UI seams.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import re
import sys
import unittest
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import stat_validation_demo_report as demo  # noqa: E402
from stats.stat_validation import STAT_VALIDATION_FIELDS  # noqa: E402


# ---------------------------------------------------------------------------
# Required JSON shape
# ---------------------------------------------------------------------------


class TestReportShape(unittest.TestCase):
    def test_required_top_level_keys_present(self) -> None:
        report = demo.build_demo_report()
        for key in (
            "records_count",
            "significant_count",
            "horizons",
            "methodology_summary",
            "interpretation_summary",
        ):
            self.assertIn(key, report, f"missing required key: {key}")

    def test_records_count_matches_horizons_length(self) -> None:
        report = demo.build_demo_report(horizons=(1, 5, 20))
        self.assertEqual(report["records_count"], 3)
        self.assertEqual(len(report["horizons"]), 3)

    def test_horizons_is_list_of_ints(self) -> None:
        report = demo.build_demo_report(horizons=(1, 5, 20))
        self.assertIsInstance(report["horizons"], list)
        for h in report["horizons"]:
            self.assertIsInstance(h, int)
        self.assertEqual(report["horizons"], [1, 5, 20])

    def test_significant_count_bounded_by_records_count(self) -> None:
        report = demo.build_demo_report()
        self.assertGreaterEqual(report["significant_count"], 0)
        self.assertLessEqual(
            report["significant_count"], report["records_count"],
        )

    def test_methodology_summary_is_nonempty_string(self) -> None:
        report = demo.build_demo_report()
        self.assertIsInstance(report["methodology_summary"], str)
        self.assertGreater(
            len(report["methodology_summary"].strip()), 50,
            "methodology summary must be substantive, not a stub",
        )

    def test_interpretation_summary_is_nonempty_string(self) -> None:
        report = demo.build_demo_report()
        self.assertIsInstance(report["interpretation_summary"], str)
        self.assertGreater(
            len(report["interpretation_summary"].strip()), 30,
            "interpretation summary must be substantive, not a stub",
        )

    def test_records_use_canonical_stat_validation_schema(self) -> None:
        report = demo.build_demo_report()
        self.assertIn("records", report)
        self.assertEqual(report["records_count"], len(report["records"]))
        for record in report["records"]:
            self.assertEqual(
                set(record.keys()), set(STAT_VALIDATION_FIELDS),
                f"record schema drift: {sorted(record.keys())}",
            )

    def test_payload_is_json_serializable_without_nan(self) -> None:
        report = demo.build_demo_report()
        text = json.dumps(report, allow_nan=False)
        self.assertEqual(json.loads(text), report)


# ---------------------------------------------------------------------------
# Conservative language — interview/CV evidence guard
# ---------------------------------------------------------------------------


_BANNED_LANGUAGE = ("proof", "alpha")


def _scan_for_banned(text: str) -> list[str]:
    """Return any banned token (case-insensitive, word-boundary) found in text."""
    found: list[str] = []
    lowered = text.lower()
    for token in _BANNED_LANGUAGE:
        # Word boundary on both sides so e.g. "betalpha" wouldn't trip
        # but "alpha" / "Alpha" / " alpha." would.
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            found.append(token)
    return found


class TestConservativeLanguage(unittest.TestCase):
    def test_methodology_does_not_claim_proof_or_alpha(self) -> None:
        report = demo.build_demo_report()
        hits = _scan_for_banned(report["methodology_summary"])
        self.assertEqual(
            hits, [],
            f"methodology_summary uses banned language: {hits}",
        )

    def test_interpretation_does_not_claim_proof_or_alpha(self) -> None:
        report = demo.build_demo_report()
        hits = _scan_for_banned(report["interpretation_summary"])
        self.assertEqual(
            hits, [],
            f"interpretation_summary uses banned language: {hits}",
        )

    def test_methodology_uses_synthetic_smoke_phrase(self) -> None:
        # Conservative framing — "synthetic smoke" must appear so a
        # reader cannot mistake the report for a backtest claim.
        report = demo.build_demo_report()
        self.assertIn(
            "synthetic smoke",
            report["methodology_summary"].lower(),
            "methodology_summary must label this run as a 'synthetic smoke'",
        )

    def test_interpretation_acknowledges_synthetic(self) -> None:
        report = demo.build_demo_report()
        self.assertIn(
            "synthetic",
            report["interpretation_summary"].lower(),
            "interpretation_summary must acknowledge synthetic data",
        )

    def test_text_mode_does_not_claim_proof_or_alpha(self) -> None:
        # Defense in depth: the rendered text mode is what an
        # interviewer will actually read.  Make sure the rendering
        # itself does not slip in banned language via headers, labels,
        # or footers.
        out = StringIO()
        demo.main([], out=out)
        hits = _scan_for_banned(out.getvalue())
        self.assertEqual(
            hits, [],
            f"text rendering uses banned language: {hits}",
        )


# ---------------------------------------------------------------------------
# Methodology substance — must reference the actual machinery
# ---------------------------------------------------------------------------


class TestMethodologySubstance(unittest.TestCase):
    def _methodology(self) -> str:
        return demo.build_demo_report()["methodology_summary"].lower()

    def test_methodology_mentions_event_study(self) -> None:
        self.assertIn("event_study", self._methodology())

    def test_methodology_mentions_bootstrap(self) -> None:
        self.assertIn("bootstrap", self._methodology())

    def test_methodology_mentions_fdr_or_benjamini_hochberg(self) -> None:
        text = self._methodology()
        self.assertTrue(
            "fdr" in text or "benjamini" in text,
            "methodology_summary must mention FDR / Benjamini-Hochberg",
        )

    def test_methodology_mentions_validation_pipeline(self) -> None:
        self.assertIn("validation_pipeline", self._methodology())

    def test_methodology_mentions_smoke_module(self) -> None:
        # Trace the report back to ``stat_validation_smoke`` so a
        # reviewer following the citation chain lands at the right
        # synthetic-data generator.
        self.assertIn(
            "stat_validation_smoke",
            self._methodology(),
        )


# ---------------------------------------------------------------------------
# Interpretation substance — must reflect live counts
# ---------------------------------------------------------------------------


class TestInterpretationSubstance(unittest.TestCase):
    def test_interpretation_reflects_live_significant_count(self) -> None:
        report = demo.build_demo_report()
        self.assertIn(
            str(report["significant_count"]),
            report["interpretation_summary"],
            "interpretation must surface the live significant_count number",
        )

    def test_interpretation_reflects_live_records_count(self) -> None:
        report = demo.build_demo_report()
        self.assertIn(
            str(report["records_count"]),
            report["interpretation_summary"],
            "interpretation must surface the live records_count number",
        )

    def test_interpretation_changes_when_counts_change(self) -> None:
        # A small cohort that fails the bootstrap min_samples gate
        # produces ``significant_count == 0``; the interpretation
        # string should not be byte-equal to the default-cohort case.
        big = demo.build_demo_report(n_events=12)
        small = demo.build_demo_report(n_events=4)
        self.assertNotEqual(
            big["interpretation_summary"],
            small["interpretation_summary"],
            "interpretation summary must vary with the live result",
        )


# ---------------------------------------------------------------------------
# Determinism + parameter surface
# ---------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    def test_same_seed_yields_byte_equal_payload(self) -> None:
        a = demo.build_demo_report(seed=123)
        b = demo.build_demo_report(seed=123)
        self.assertEqual(a, b)

    def test_different_seeds_yield_different_payloads(self) -> None:
        a = demo.build_demo_report(seed=111)
        b = demo.build_demo_report(seed=222)
        self.assertNotEqual(a, b)


class TestParameterSurface(unittest.TestCase):
    def test_strong_default_shock_yields_at_least_one_significant(self) -> None:
        # Default shock is large enough that at least one horizon
        # clears the FDR threshold under the default seed.  If this
        # ever fails the demo's signal-to-noise has regressed.
        report = demo.build_demo_report()
        self.assertGreaterEqual(report["significant_count"], 1)


# ---------------------------------------------------------------------------
# CLI plumbing — JSON mode, text mode, exit code, seed flag
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def test_json_mode_emits_valid_json_with_required_keys(self) -> None:
        out = StringIO()
        rc = demo.main(["--json"], out=out)
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        for key in (
            "records_count",
            "significant_count",
            "horizons",
            "methodology_summary",
            "interpretation_summary",
        ):
            self.assertIn(key, payload)

    def test_text_mode_renders_methodology_and_interpretation_sections(self) -> None:
        out = StringIO()
        rc = demo.main([], out=out)
        self.assertEqual(rc, 0)
        text = out.getvalue().lower()
        # Tokens an operator scanning the text mode would expect.
        for token in ("methodology", "interpretation", "records", "horizons"):
            self.assertIn(
                token, text,
                f"text mode output missing section/token: {token!r}",
            )

    def test_text_mode_surfaces_live_counts(self) -> None:
        out = StringIO()
        demo.main([], out=out)
        report = demo.build_demo_report()
        text = out.getvalue()
        self.assertIn(str(report["records_count"]),     text)
        self.assertIn(str(report["significant_count"]), text)

    def test_seed_flag_forwards_through_cli(self) -> None:
        a = StringIO()
        b = StringIO()
        demo.main(["--json", "--seed", "777"], out=a)
        demo.main(["--json", "--seed", "777"], out=b)
        self.assertEqual(a.getvalue(), b.getvalue())

    def test_different_cli_seeds_change_output(self) -> None:
        a = StringIO()
        b = StringIO()
        demo.main(["--json", "--seed", "777"], out=a)
        demo.main(["--json", "--seed", "888"], out=b)
        self.assertNotEqual(a.getvalue(), b.getvalue())


# ---------------------------------------------------------------------------
# Build-on guard — both upstream surfaces must be load-bearing
# ---------------------------------------------------------------------------


class TestBuildsOnUpstreams(unittest.TestCase):
    def test_imports_validation_pipeline(self) -> None:
        tree = ast.parse(inspect.getsource(demo))
        from_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                from_modules.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    from_modules.add(alias.name)
        self.assertTrue(
            any("validation_pipeline" in m for m in from_modules),
            f"demo report must build on stats.validation_pipeline; "
            f"saw imports: {sorted(from_modules)}",
        )

    def test_imports_stat_validation_smoke(self) -> None:
        tree = ast.parse(inspect.getsource(demo))
        from_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                from_modules.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    from_modules.add(alias.name)
        self.assertTrue(
            any("stat_validation_smoke" in m for m in from_modules),
            f"demo report must build on scripts.stat_validation_smoke; "
            f"saw imports: {sorted(from_modules)}",
        )


# ---------------------------------------------------------------------------
# Banned imports — pipeline demo must stay clear of DB / UI / provider seams
# ---------------------------------------------------------------------------


class TestNoBannedImports(unittest.TestCase):
    def test_module_does_not_import_banned_seams(self) -> None:
        tree = ast.parse(inspect.getsource(demo))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])
        banned = {
            "db", "sqlite3",
            "yfinance", "openai", "anthropic",
            "market_data", "market_check", "price_cache",
            "api", "routes", "fastapi",
        }
        self.assertEqual(
            imported & banned, set(),
            f"stat_validation_demo_report must not import: "
            f"{imported & banned}",
        )


if __name__ == "__main__":
    unittest.main()
