"""Tests for ``scripts/stat_validation_smoke.py``.

Read-only pipeline smoke over deterministic synthetic data:

    event_study → bootstrap CI → p-value → FDR → stat_validation

The smoke never touches the DB, a provider, ``yfinance``, an LLM, or
the FastAPI app — every dependency is in ``stats/*``.

What we pin
-----------
* The smoke runs without errors on default deterministic inputs.
* The output JSON carries the required four keys: ``ok``,
  ``records_count``, ``significant_count``, ``errors``.
* ``records_count`` equals ``len(horizons)``.
* ``significant_count`` is bounded by ``records_count``.
* Each record exposes every canonical stat-validation field in the
  pinned order — the smoke never invents or drops keys.
* Determinism: same seed → byte-equal payload, byte-equal CLI output.
* Different seeds produce different payloads (so the seed flag is
  actually load-bearing, not a no-op).
* Banned-import guard: the smoke does not pull in DB / provider / UI /
  LLM seams.
* CLI exit code matches ``payload["ok"]`` and ``--json`` emits valid
  JSON with the four required keys.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import stat_validation_smoke as smoke  # noqa: E402
from stats.stat_validation import STAT_VALIDATION_FIELDS  # noqa: E402


# ---------------------------------------------------------------------------
# Pipeline shape
# ---------------------------------------------------------------------------


class TestRunSmoke(unittest.TestCase):
    def test_default_run_is_ok(self) -> None:
        payload = smoke.run_smoke()
        self.assertTrue(
            payload["ok"], f"errors={payload.get('errors')}",
        )

    def test_required_top_level_keys_present(self) -> None:
        payload = smoke.run_smoke()
        for key in ("ok", "records_count", "significant_count", "errors"):
            self.assertIn(key, payload, f"missing top-level key: {key}")

    def test_top_level_field_types(self) -> None:
        payload = smoke.run_smoke()
        self.assertIsInstance(payload["ok"], bool)
        self.assertIsInstance(payload["records_count"], int)
        self.assertIsInstance(payload["significant_count"], int)
        self.assertIsInstance(payload["errors"], list)

    def test_records_count_equals_horizons(self) -> None:
        payload = smoke.run_smoke(horizons=(1, 5, 20))
        self.assertEqual(payload["records_count"], 3)
        payload = smoke.run_smoke(horizons=(5,))
        self.assertEqual(payload["records_count"], 1)

    def test_significant_count_bounded_by_records_count(self) -> None:
        payload = smoke.run_smoke()
        self.assertGreaterEqual(payload["significant_count"], 0)
        self.assertLessEqual(
            payload["significant_count"], payload["records_count"],
        )

    def test_records_have_canonical_stat_validation_fields(self) -> None:
        # Every record must expose every canonical key — the smoke
        # MUST funnel through ``make_stat_validation_record`` so the
        # schema contract is enforced row-for-row.
        payload = smoke.run_smoke()
        self.assertEqual(payload["records_count"], len(payload["records"]))
        for record in payload["records"]:
            self.assertEqual(
                set(record.keys()), set(STAT_VALIDATION_FIELDS),
                f"record schema drift: {sorted(record.keys())}",
            )

    def test_records_horizons_match_input(self) -> None:
        horizons = (1, 5, 20)
        payload = smoke.run_smoke(horizons=horizons)
        seen = tuple(r["horizon"] for r in payload["records"])
        self.assertEqual(seen, horizons)

    def test_records_carry_pipeline_outputs(self) -> None:
        # The smoke is wired end-to-end iff every numeric pipeline
        # output (AR, SAR, CAR, CI bounds, p, q) is populated for at
        # least one horizon.  Pure stub paths would leave them all None.
        payload = smoke.run_smoke()
        any_ar    = any(r["abnormal_return"] is not None for r in payload["records"])
        any_sar   = any(r["sar"]             is not None for r in payload["records"])
        any_car   = any(r.get("car")         is not None for r in payload["records"])
        any_ci    = any(r["ci_low"]          is not None for r in payload["records"])
        any_p     = any(r["p_value"]         is not None for r in payload["records"])
        any_fdr_q = any(r["fdr_q"]           is not None for r in payload["records"])
        self.assertTrue(any_ar)
        self.assertTrue(any_sar)
        self.assertTrue(any_car)
        self.assertTrue(any_ci)
        self.assertTrue(any_p)
        self.assertTrue(any_fdr_q)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    def test_same_seed_yields_byte_equal_payload(self) -> None:
        a = smoke.run_smoke(seed=123)
        b = smoke.run_smoke(seed=123)
        self.assertEqual(a, b)

    def test_different_seeds_yield_different_payloads(self) -> None:
        # Sanity: the seed flag must actually drive output variation,
        # otherwise it's a no-op flag and the determinism guarantee
        # above means nothing.
        a = smoke.run_smoke(seed=111)
        b = smoke.run_smoke(seed=222)
        self.assertNotEqual(a, b)

    def test_payload_is_json_serializable_without_nan(self) -> None:
        payload = smoke.run_smoke()
        text = json.dumps(payload, allow_nan=False)
        self.assertEqual(json.loads(text), payload)


# ---------------------------------------------------------------------------
# Significance — strong synthetic shock should produce at least one hit
# ---------------------------------------------------------------------------


class TestSignal(unittest.TestCase):
    def test_strong_default_shock_yields_at_least_one_significant(self) -> None:
        # The default synthetic generator embeds a positive shock at
        # the event date.  With the cohort size and shock magnitude
        # baked into the smoke, at least one horizon must be
        # statistically significant — otherwise the pipeline is not
        # actually wired through (a stubbed FDR step would produce
        # zero discoveries here).
        payload = smoke.run_smoke()
        self.assertGreaterEqual(payload["significant_count"], 1)

    def test_zero_shock_pipeline_still_runs_cleanly(self) -> None:
        # Pure-noise synthetic data: AR is close to zero, SAR small,
        # FDR rarely fires.  The pipeline must still produce a valid
        # JSON-shaped payload and never crash.  We do NOT assert
        # ``significant_count == 0`` because pure noise can deliver
        # false positives — the bound is records_count.
        payload = smoke.run_smoke(event_shock=0.0, seed=42)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["records_count"], 3)
        self.assertGreaterEqual(payload["significant_count"], 0)
        self.assertLessEqual(
            payload["significant_count"], payload["records_count"],
        )


# ---------------------------------------------------------------------------
# Configuration knobs the CLI exposes
# ---------------------------------------------------------------------------


class TestParameterSurface(unittest.TestCase):
    def test_run_with_smaller_cohort_still_succeeds(self) -> None:
        # Bootstrap CI gracefully reports insufficient_data when the
        # cohort is too small; the smoke must still emit a valid
        # payload — significance simply collapses to False for those
        # rows.
        payload = smoke.run_smoke(n_events=4)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["records_count"], 3)

    def test_alpha_threshold_propagates(self) -> None:
        # Significance is gated by alpha — a permissive alpha yields
        # at least as many discoveries as a strict alpha on the same
        # synthetic data.
        permissive = smoke.run_smoke(seed=42, alpha=0.20)
        strict     = smoke.run_smoke(seed=42, alpha=0.001)
        self.assertGreaterEqual(
            permissive["significant_count"],
            strict["significant_count"],
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(unittest.TestCase):
    def test_json_flag_emits_valid_json(self) -> None:
        out = StringIO()
        rc = smoke.main(["--json"], out=out)
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        for key in ("ok", "records_count", "significant_count", "errors"):
            self.assertIn(key, payload)

    def test_text_output_renders_summary(self) -> None:
        out = StringIO()
        rc = smoke.main([], out=out)
        self.assertEqual(rc, 0)
        text = out.getvalue()
        for token in ("records", "significant"):
            self.assertIn(token, text.lower())

    def test_text_output_includes_car_line(self) -> None:
        out = StringIO()
        smoke.main([], out=out)
        text = out.getvalue()
        self.assertIn("car:", text.lower())

    def test_seed_flag_forwards_through_cli(self) -> None:
        a = StringIO()
        b = StringIO()
        smoke.main(["--json", "--seed", "777"], out=a)
        smoke.main(["--json", "--seed", "777"], out=b)
        self.assertEqual(a.getvalue(), b.getvalue())

    def test_different_cli_seeds_produce_different_output(self) -> None:
        a = StringIO()
        b = StringIO()
        smoke.main(["--json", "--seed", "777"], out=a)
        smoke.main(["--json", "--seed", "888"], out=b)
        self.assertNotEqual(a.getvalue(), b.getvalue())

    def test_horizons_flag_changes_records_count(self) -> None:
        out = StringIO()
        smoke.main(["--json", "--horizons", "5"], out=out)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["records_count"], 1)


# ---------------------------------------------------------------------------
# Banned imports — pipeline smoke must not pull in DB / UI / provider seams
# ---------------------------------------------------------------------------


class TestNoBannedImports(unittest.TestCase):
    def test_smoke_module_does_not_import_banned_seams(self) -> None:
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(smoke))
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
            f"stat_validation_smoke must not import: {imported & banned}",
        )


if __name__ == "__main__":
    unittest.main()
