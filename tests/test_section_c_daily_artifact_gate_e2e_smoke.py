"""Tests for ``scripts/section_c_daily_artifact_gate_e2e_smoke.py``.

Pin the contract:

* The smoke is read-only by construction.  Every file it writes lives
  under an internal ``tempfile.TemporaryDirectory``; the live
  ``artifacts/`` directory is never opened for writing.
* The envelope has the documented top-level keys (``ok``, ``temp_only``,
  ``candidate_id``, ``emitted_artifact_count``,
  ``diagnostic_artifact_present``,
  ``diagnostic_artifact_fields_complete``, ``gate_admitted_count``,
  ``gate_held_count``, ``gate_id``, ``scenarios``, ``errors``).
* The happy-path scenario (``complete``) has its artifact found and
  fields complete; the gate admits the matching card.
* The ``missing_artifact`` scenario reports ``artifact_present=False``
  with a descriptive ``artifact_missing_reason``; the gate holds.
* The ``incomplete_artifact`` scenario reports
  ``artifact_present=True`` but ``artifact_fields_complete=False``
  with ``primary_ticker`` in ``artifact_incomplete_fields``; the gate
  holds.
* The gate ``admitted_count`` is exactly 1 and ``held_for_review_count``
  is exactly 2 — the smoke proves the full workflow against three
  distinct cards.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from io import StringIO
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import section_c_daily_artifact_gate_e2e_smoke as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "temp_only",
    "candidate_id",
    "emitted_artifact_count",
    "diagnostic_artifact_present",
    "diagnostic_artifact_fields_complete",
    "gate_admitted_count",
    "gate_held_count",
    "gate_id",
    "scenarios",
    "errors",
)


_REQUIRED_SCENARIO_KEYS = (
    "name",
    "candidate_id",
    "diagnostic_artifact_present",
    "diagnostic_artifact_fields_complete",
    "diagnostic_artifact_missing_reason",
    "diagnostic_artifact_incomplete_fields",
    "gate_admitted",
    "expected_admit",
    "ok",
)


_EXPECTED_SCENARIO_NAMES = (
    "complete",
    "missing_artifact",
    "incomplete_artifact",
)


# ---------------------------------------------------------------------------
# Envelope schema + happy-path verdict
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_envelope_has_all_required_keys(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_e2e_smoke(
            generated_at="2026-05-24T00:00:00Z",
        )
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, report, f"missing envelope key: {k}")

    def test_envelope_top_level_types(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_e2e_smoke(
            generated_at="2026-05-24T00:00:00Z",
        )
        self.assertIsInstance(report["ok"], bool)
        self.assertIs(report["temp_only"], True)
        self.assertIsInstance(report["candidate_id"], str)
        self.assertIsInstance(report["emitted_artifact_count"], int)
        self.assertIsInstance(report["gate_admitted_count"], int)
        self.assertIsInstance(report["gate_held_count"], int)
        self.assertIsInstance(report["gate_id"], str)
        self.assertIsInstance(report["scenarios"], list)
        self.assertIsInstance(report["errors"], list)

    def test_happy_path_envelope_is_ok(self) -> None:
        report = cli.run_section_c_daily_artifact_gate_e2e_smoke(
            generated_at="2026-05-24T00:00:00Z",
        )
        self.assertTrue(report["ok"], f"errors: {report['errors']}")
        self.assertEqual(report["errors"], [])
        # Happy-path scenario verdicts.
        self.assertTrue(report["diagnostic_artifact_present"])
        self.assertTrue(report["diagnostic_artifact_fields_complete"])
        # Three scenarios → one admit, two hold.
        self.assertEqual(report["gate_admitted_count"], 1)
        self.assertEqual(report["gate_held_count"], 2)
        # candidate_id is the 16-char hex prefix produced by
        # news_fetch._candidate_id; deterministic across runs.
        self.assertEqual(len(report["candidate_id"]), 16)
        self.assertTrue(all(
            c in "0123456789abcdef" for c in report["candidate_id"]
        ))


# ---------------------------------------------------------------------------
# Scenarios — each individual verdict the smoke pins
# ---------------------------------------------------------------------------


class TestScenarios(unittest.TestCase):
    def _scenarios(self) -> list[dict[str, Any]]:
        report = cli.run_section_c_daily_artifact_gate_e2e_smoke(
            generated_at="2026-05-24T00:00:00Z",
        )
        return report["scenarios"]

    def test_three_named_scenarios_in_canonical_order(self) -> None:
        scenarios = self._scenarios()
        self.assertEqual(len(scenarios), 3)
        names = tuple(s["name"] for s in scenarios)
        self.assertEqual(names, _EXPECTED_SCENARIO_NAMES)

    def test_every_scenario_has_required_keys(self) -> None:
        for s in self._scenarios():
            for k in _REQUIRED_SCENARIO_KEYS:
                self.assertIn(k, s, f"missing scenario key: {k} in {s['name']}")

    def test_complete_scenario_admits(self) -> None:
        scenarios = {s["name"]: s for s in self._scenarios()}
        s = scenarios["complete"]
        self.assertTrue(s["diagnostic_artifact_present"])
        self.assertTrue(s["diagnostic_artifact_fields_complete"])
        self.assertIsNone(s["diagnostic_artifact_missing_reason"])
        self.assertIsNone(s["diagnostic_artifact_incomplete_fields"])
        self.assertTrue(s["gate_admitted"])
        self.assertTrue(s["expected_admit"])
        self.assertTrue(s["ok"])

    def test_missing_artifact_scenario_holds(self) -> None:
        scenarios = {s["name"]: s for s in self._scenarios()}
        s = scenarios["missing_artifact"]
        self.assertFalse(s["diagnostic_artifact_present"])
        self.assertFalse(s["diagnostic_artifact_fields_complete"])
        # The diagnostic surfaces a non-empty missing-reason string.
        reason = s.get("diagnostic_artifact_missing_reason")
        self.assertIsInstance(reason, str)
        self.assertTrue(reason)
        self.assertFalse(s["gate_admitted"])
        self.assertFalse(s["expected_admit"])
        self.assertTrue(s["ok"])

    def test_incomplete_artifact_scenario_holds(self) -> None:
        scenarios = {s["name"]: s for s in self._scenarios()}
        s = scenarios["incomplete_artifact"]
        # File is present...
        self.assertTrue(s["diagnostic_artifact_present"])
        # ...but a required gate field is missing.
        self.assertFalse(s["diagnostic_artifact_fields_complete"])
        incomplete = s.get("diagnostic_artifact_incomplete_fields")
        self.assertIsInstance(incomplete, list)
        self.assertIn("primary_ticker", incomplete)
        self.assertFalse(s["gate_admitted"])
        self.assertFalse(s["expected_admit"])
        self.assertTrue(s["ok"])


# ---------------------------------------------------------------------------
# Determinism — same inputs always produce the same candidate_id
# ---------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    def test_candidate_id_stable_across_runs(self) -> None:
        a = cli.run_section_c_daily_artifact_gate_e2e_smoke(
            generated_at="2026-05-24T00:00:00Z",
        )
        b = cli.run_section_c_daily_artifact_gate_e2e_smoke(
            generated_at="2026-05-24T00:00:00Z",
        )
        # The deterministic news_fetch._candidate_id keys on (source,
        # title, published_at, url) — none of those vary across runs,
        # so the complete-scenario id must match exactly.
        self.assertEqual(a["candidate_id"], b["candidate_id"])
        # And every per-scenario id matches across runs.
        ids_a = [s["candidate_id"] for s in a["scenarios"]]
        ids_b = [s["candidate_id"] for s in b["scenarios"]]
        self.assertEqual(ids_a, ids_b)


# ---------------------------------------------------------------------------
# Read-only invariant — live artifacts/ is not touched
# ---------------------------------------------------------------------------


class TestNoLiveArtifactWrite(unittest.TestCase):
    def _live_artifacts_snapshot(self) -> dict[str, str]:
        """Return a {filename: sha256} map of the live artifacts/ dir.

        When the directory doesn't exist (e.g. fresh checkout) the
        snapshot is an empty dict — the smoke must keep it that way.
        """
        live = Path("artifacts")
        if not live.is_dir():
            return {}
        out: dict[str, str] = {}
        for p in sorted(live.iterdir()):
            if not p.is_file():
                continue
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            out[p.name] = h.hexdigest()
        return out

    def test_live_artifacts_directory_unchanged(self) -> None:
        before = self._live_artifacts_snapshot()
        report = cli.run_section_c_daily_artifact_gate_e2e_smoke(
            generated_at="2026-05-24T00:00:00Z",
        )
        after = self._live_artifacts_snapshot()
        self.assertEqual(
            before, after,
            "smoke must not create / modify / delete files under live "
            "artifacts/",
        )
        # And the envelope flags this contract explicitly.
        self.assertIs(report["temp_only"], True)


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_provider_attrs(self) -> None:
        for attr in ("yfinance", "anthropic", "openai", "fastapi"):
            self.assertFalse(
                hasattr(cli, attr),
                f"smoke must not bind {attr} as a module attr",
            )

    def test_smoke_does_not_bind_db_attr(self) -> None:
        # The smoke is read-only and must not pull in the project db
        # module at import time.
        self.assertFalse(hasattr(cli, "db"))


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_json_flag_emits_valid_envelope(self) -> None:
        rc, output = self._run(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)
        self.assertTrue(parsed["ok"])

    def test_default_emits_json_too(self) -> None:
        # Output is always JSON — --json is a no-op compatibility flag.
        rc, output = self._run([])
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["ok"], True)
        self.assertEqual(parsed["gate_admitted_count"], 1)
        self.assertEqual(parsed["gate_held_count"], 2)


if __name__ == "__main__":
    unittest.main()
