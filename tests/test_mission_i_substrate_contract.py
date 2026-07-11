"""T2 — Mission I clean-clone substrate contract regression guard.

The independent full-test audit found 27 clean-clone errors in
``tests/test_i1_candidate_universe``: every test touching the shared
``universe()`` memo recomputed the whole Mission I candidate universe
from the gitignored ``g_state_cache/g3_price_cache.db`` substrate, whose
absence trips the builder's (correct) fail-loud session pins.

The repaired contract keeps three input layers distinct:

* **logic** — pure date/session/count mechanics on minimal fixtures,
  default-run;
* **publication** — tracked Mission I artifacts (G1A/G1B ledgers, the
  tracked I1 report), default-run;
* **local recomputation** — rebuilding the real 2,385-session universe
  from the maintainer's substrate, opt-in only via::

      SECOND_ORDER_RUN_LOCAL_DATA_TESTS=1
      SECOND_ORDER_LOCAL_MISSION_I_SUBSTRATE=<path to g3_price_cache.db>

File presence alone must never activate the local layer, a tiny fixture
must never impersonate the historical universe (the builder's pins
refuse it), and a clean clone must run the module with zero errors.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests import _local_data_gate as gate  # noqa: E402
from tests import test_i1_candidate_universe as i1_tests  # noqa: E402

I1_MODULE = "tests.test_i1_candidate_universe"


def _stripped_env(extra: dict | None = None) -> dict:
    env = os.environ.copy()
    env.pop("SECOND_ORDER_RUN_LOCAL_DATA_TESTS", None)
    env.pop("SECOND_ORDER_LOCAL_EVENTS_DB", None)
    env.pop("SECOND_ORDER_LOCAL_MISSION_I_SUBSTRATE", None)
    if extra:
        env.update(extra)
    return env


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None,
         timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd or REPO), env=env, capture_output=True,
        text=True, timeout=timeout,
    )


_SKIPMAP_SNIPPET = r"""
import json, sys, unittest
sys.path.insert(0, {repo!r})
loader = unittest.TestLoader()
suite = loader.loadTestsFromName({module!r})
rows = []
def walk(s):
    for item in s:
        if isinstance(item, unittest.TestSuite):
            walk(item); continue
        cls = type(item)
        method = getattr(cls, getattr(item, "_testMethodName", ""), None)
        skip = bool(getattr(cls, "__unittest_skip__", False)
                    or getattr(method, "__unittest_skip__", False))
        rows.append((f"{{cls.__name__}}.{{item._testMethodName}}", skip))
walk(suite)
print(json.dumps({{"skipped": sorted(t for t, s in rows if s),
                   "all": sorted(t for t, _ in rows)}}))
"""


def _skip_map(env: dict) -> dict:
    code = _SKIPMAP_SNIPPET.format(repo=str(REPO), module=I1_MODULE)
    proc = _run([sys.executable, "-c", code], env=env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _make_synthetic_substrate(path: Path) -> None:
    """A tiny, obviously-not-historical price-cache fixture (a handful of
    sessions) — enough to prove the explicit path is consumed, never
    enough to satisfy the 2,385-session pins."""
    import sqlite3
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE price_cache ("
        " ticker TEXT NOT NULL, date TEXT NOT NULL, close REAL, volume REAL,"
        " auto_adjust INTEGER NOT NULL, fetched_at TEXT NOT NULL,"
        " PRIMARY KEY (ticker, date, auto_adjust))"
    )
    for ticker in ("KRE", "SPY", "XLF", "XOP", "XLE"):
        for day in ("2024-03-05", "2024-03-06", "2024-03-07"):
            conn.execute(
                "INSERT INTO price_cache VALUES (?, ?, 100.0, 1.0, 1, 't')",
                (ticker, day),
            )
    conn.commit()
    conn.close()


class TestMissionISubstrateGate(unittest.TestCase):
    """The explicit opt-in contract for the Mission I substrate path."""

    def test_gate_disabled_by_default(self) -> None:
        self.assertIsNone(gate.local_mission_i_substrate_or_none(environ={}))

    def test_file_presence_alone_never_enables(self) -> None:
        # The maintainer repository carries the real substrate at the
        # default location; without the opt-in the gate must not see it.
        real = REPO / "g_state_cache" / "g3_price_cache.db"
        self.assertIsNone(gate.local_mission_i_substrate_or_none(environ={}))
        if real.exists():
            env = {"SECOND_ORDER_LOCAL_MISSION_I_SUBSTRATE": str(real)}
            self.assertIsNone(
                gate.local_mission_i_substrate_or_none(environ=env),
                "path without the enable flag must not activate",
            )

    def test_enabled_without_path_fails_closed(self) -> None:
        env = {"SECOND_ORDER_RUN_LOCAL_DATA_TESTS": "1"}
        self.assertIsNone(gate.local_mission_i_substrate_or_none(environ=env))
        reason = gate.mission_i_skip_reason(environ=env)
        self.assertIn("SECOND_ORDER_LOCAL_MISSION_I_SUBSTRATE", reason)

    def test_enabled_with_missing_path_fails_closed(self) -> None:
        env = {
            "SECOND_ORDER_RUN_LOCAL_DATA_TESTS": "1",
            "SECOND_ORDER_LOCAL_MISSION_I_SUBSTRATE": os.path.join(
                tempfile.gettempdir(), "definitely_missing_t2.db"),
        }
        self.assertIsNone(gate.local_mission_i_substrate_or_none(environ=env))
        self.assertIn(
            "does not exist", gate.mission_i_skip_reason(environ=env))

    def test_enabled_with_valid_path_resolves(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as fh:
            path = fh.name
        try:
            env = {
                "SECOND_ORDER_RUN_LOCAL_DATA_TESTS": "1",
                "SECOND_ORDER_LOCAL_MISSION_I_SUBSTRATE": path,
            }
            resolved = gate.local_mission_i_substrate_or_none(environ=env)
            self.assertEqual(Path(path).resolve(), resolved)
        finally:
            os.unlink(path)

    def test_gate_never_falls_back_to_default_substrate(self) -> None:
        # Enabled with no path while the real substrate exists at the
        # conventional location: no silent fallback.
        env = {"SECOND_ORDER_RUN_LOCAL_DATA_TESTS": "1"}
        self.assertIsNone(gate.local_mission_i_substrate_or_none(environ=env))

    def test_skip_reason_names_the_missing_opt_in(self) -> None:
        reason = gate.mission_i_skip_reason(environ={})
        self.assertIn("SECOND_ORDER_RUN_LOCAL_DATA_TESTS", reason)


class TestCategoryClassification(unittest.TestCase):
    """Every i1 test is pinned to exactly one category, and the local
    category cannot silently absorb default coverage (or vice versa)."""

    def test_categories_partition_the_module(self) -> None:
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromModule(i1_tests)
        collected: set[str] = set()

        def walk(s):
            for item in s:
                if isinstance(item, unittest.TestSuite):
                    walk(item)
                else:
                    collected.add(
                        f"{type(item).__name__}.{item._testMethodName}")

        walk(suite)
        logic = set(i1_tests.CATEGORY_LOGIC)
        publication = set(i1_tests.CATEGORY_PUBLICATION)
        local = set(i1_tests.CATEGORY_LOCAL_RECOMPUTATION)
        self.assertEqual(logic & publication, set())
        self.assertEqual(logic & local, set())
        self.assertEqual(publication & local, set())
        self.assertEqual(
            collected, logic | publication | local,
            "every i1 test must be classified in exactly one category",
        )

    def test_frozen_counts_and_pins_are_local_recomputation(self) -> None:
        # Anti-fabrication pin: the frozen historical counts, the frame
        # pins and the tracked-report byte-reconciliation can only ever
        # run against the real substrate — a minimal fixture proves
        # logic, never the 2,385-session historical universe.
        local = set(i1_tests.CATEGORY_LOCAL_RECOMPUTATION)
        for required in (
            "FrozenCandidateCountTest.test_fomc_counts_1816_1299_0",
            "FrozenCandidateCountTest.test_opec_counts_1903_1631_889",
            "FramePinTest.test_real_frames_are_2385_joint_and_2011_era",
            "DeterminismTest.test_tracked_report_matches_builder_output",
            "GateEquivalenceTest.test_preexclusion_h20_equals_shipped_gate_and",
        ):
            self.assertIn(required, local)

    def test_logic_and_publication_stay_default(self) -> None:
        # Structural coverage floor: the default categories are not empty
        # shells after the migration.
        self.assertGreaterEqual(len(i1_tests.CATEGORY_LOGIC), 10)
        self.assertGreaterEqual(len(i1_tests.CATEGORY_PUBLICATION), 10)


class TestCleanCloneBehavior(unittest.TestCase):
    """Default (gate-off) behavior of the i1 module."""

    def test_gate_off_zero_errors_zero_failures(self) -> None:
        proc = _run(
            [sys.executable, "-m", "unittest", I1_MODULE],
            env=_stripped_env(),
        )
        tail = proc.stderr.strip().splitlines()
        self.assertNotIn("errors=", tail[-1] if tail else "",
                         f"module errored under gate-off:\n{proc.stderr[-1500:]}")
        self.assertNotIn("failures=", tail[-1] if tail else "")
        self.assertEqual(proc.returncode, 0, proc.stderr[-1500:])

    def test_gate_off_skips_exactly_the_local_category(self) -> None:
        skip_map = _skip_map(_stripped_env())
        self.assertEqual(
            sorted(skip_map["skipped"]),
            sorted(i1_tests.CATEGORY_LOCAL_RECOMPUTATION),
            "gate-off skips must be exactly the local-recomputation set",
        )

    def test_incidental_substrate_presence_does_not_activate(self) -> None:
        # The maintainer checkout HAS the real substrate at the default
        # location; the collection-time skip set must be identical to a
        # clean clone's (presence alone never enables).
        skip_map = _skip_map(_stripped_env())
        self.assertEqual(
            sorted(skip_map["skipped"]),
            sorted(i1_tests.CATEGORY_LOCAL_RECOMPUTATION),
        )

    def test_gate_off_map_is_deterministic(self) -> None:
        self.assertEqual(_skip_map(_stripped_env()),
                         _skip_map(_stripped_env()))


class TestExplicitOptIn(unittest.TestCase):
    """Opt-in activates exactly the local category and consumes the
    explicitly supplied path."""

    def test_opt_in_with_synthetic_path_activates_local_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            synthetic = Path(tmp) / "tiny_substrate.db"
            _make_synthetic_substrate(synthetic)
            on = _skip_map(_stripped_env({
                "SECOND_ORDER_RUN_LOCAL_DATA_TESTS": "1",
                "SECOND_ORDER_LOCAL_MISSION_I_SUBSTRATE": str(synthetic),
            }))
        off = _skip_map(_stripped_env())
        self.assertEqual(on["all"], off["all"],
                         "the gate must not add or remove tests")
        self.assertEqual(on["skipped"], [],
                         "opt-in must activate the local tests")
        self.assertEqual(
            sorted(off["skipped"]),
            sorted(i1_tests.CATEGORY_LOCAL_RECOMPUTATION),
        )

    def test_small_fixture_cannot_impersonate_the_historical_universe(
        self,
    ) -> None:
        # The builder consumes the explicit path and REFUSES a fixture
        # that does not carry the pinned 2,385-session frame — no
        # fabricated publication proof is possible by construction.
        from scripts import i1_candidate_universe as i1
        with tempfile.TemporaryDirectory() as tmp:
            synthetic = Path(tmp) / "tiny_substrate.db"
            _make_synthetic_substrate(synthetic)
            with self.assertRaisesRegex(RuntimeError, "pin broken"):
                i1.build_universe(db_path=synthetic)

    def test_module_run_creates_no_root_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = _stripped_env({"PYTHONPATH": str(REPO)})
            env.pop("EVENTS_DB_FILE", None)
            proc = _run(
                [sys.executable, "-m", "unittest", I1_MODULE],
                cwd=Path(tmp), env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-1500:])
            leftovers = sorted(
                name for name in os.listdir(tmp)
                if name.startswith("events.db"))
            self.assertEqual(leftovers, [],
                             "module run must not create a root events.db "
                             "or SQLite sidecar")


class TestPytestParity(unittest.TestCase):
    def test_pytest_gate_off_zero_errors(self) -> None:
        proc = _run(
            [sys.executable, "-m", "pytest",
             "tests/test_i1_candidate_universe.py", "-q"],
            env=_stripped_env(),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout[-1500:])
        self.assertNotIn("error", proc.stdout.lower().split("\n")[-2])


if __name__ == "__main__":
    unittest.main()
