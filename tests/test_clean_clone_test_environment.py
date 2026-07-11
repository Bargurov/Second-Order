"""T1 — canonical clean-clone test environment regression guard.

Pins the three governance contracts the independent full-test audit found
broken:

1. **Declared dependencies** — every third-party package imported by the
   backend (runtime + tests) is declared in the canonical manifests
   (``requirements.txt`` for runtime, ``requirements-test.txt`` for the
   test environment), so a clean clone collects the full suite with::

       python -m pip install -r requirements-test.txt

2. **Stable default universe** — no default-suite test activates or
   deactivates because an incidental local file (a root ``events.db``)
   happens to exist.  Local/live-archive checks run only behind the
   explicit shared opt-in gate (``tests/_local_data_gate.py``) with an
   explicitly declared, validated path, and never fall back to the root
   archive.

3. **Deterministic preflight** — ``scripts/test_environment_preflight.py``
   gives CI and operators one repeatable environment probe.

Subprocess-based wherever import order or collection state matters.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

REQ_RUNTIME = REPO / "requirements.txt"
REQ_TEST = REPO / "requirements-test.txt"
PREFLIGHT = REPO / "scripts" / "test_environment_preflight.py"

# Import-name -> distribution-name mapping for packages whose names differ.
_DIST_NAME = {
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "telegram": "python-telegram-bot",
}

# The modules the audit found uncollectable in a clean clone (missing
# pytest), plus the calibration-report module added since.
FORMERLY_UNCOLLECTABLE = (
    "tests.test_news_clustering",
    "tests.test_reviewer_front_door",
    "tests.test_robust_diagnostics",
    "tests.test_track_record_scoring",
    "tests.test_reaction_profile_calibration_report",
)

# The default-suite modules whose live-archive checks were activated by
# mere root events.db presence (161 tests, measured by collection-time
# skip-map diff at the T1 starting commit).
ROOT_PRESENCE_MODULES = (
    "tests.test_basis_integrity_report",
    "tests.test_case_library_reaction_matrix",
    "tests.test_effective_independent_evidence_report",
    "tests.test_event_date_quality_distribution_report",
    "tests.test_expanded_case_notes_report",
    "tests.test_materiality_annotation",
    "tests.test_mechanism_family_comparison_report",
    "tests.test_mechanism_family_evidence_inventory",
    "tests.test_representative_case_expansion_report",
    "tests.test_sector_relative_readout",
    "tests.test_transmission_case_selection_stress_report",
)


def _declared_names(*req_paths: Path) -> set[str]:
    """Requirement names declared across the given manifests (lowercased,
    extras and bounds stripped; ``-r`` includes are NOT followed — pass
    every file explicitly)."""
    names: set[str] = set()
    for path in req_paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith(("-r", "-c", "--")):
                continue
            name = re.split(r"[<>=!\[;\s]", line, 1)[0].strip().lower()
            if name:
                names.add(name)
    return names


def _third_party_imports(paths: list[Path]) -> dict[str, set[str]]:
    stdlib = set(sys.stdlib_module_names)
    local = {p.stem for p in REPO.glob("*.py")}
    local |= {"routes", "scripts", "tests", "stats", "tools"}
    local |= {p.stem for p in (REPO / "tests").glob("*.py")}
    local |= {p.stem for p in (REPO / "stats").glob("*.py")}
    out: dict[str, set[str]] = {}
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                mods = [node.module.split(".")[0]]
            for mod in mods:
                if mod in stdlib or mod in local:
                    continue
                out.setdefault(mod, set()).add(path.name)
    return out


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None,
         timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd or REPO), env=env, capture_output=True,
        text=True, timeout=timeout,
    )


def _gate_stripped_env(extra: dict | None = None) -> dict:
    env = os.environ.copy()
    env.pop("SECOND_ORDER_RUN_LOCAL_DATA_TESTS", None)
    env.pop("SECOND_ORDER_LOCAL_EVENTS_DB", None)
    if extra:
        env.update(extra)
    return env


_SKIPMAP_SNIPPET = r"""
import json, sys, unittest
sys.path.insert(0, {repo!r})
loader = unittest.TestLoader()
suite = loader.loadTestsFromNames({modules!r})
rows = []
def walk(s):
    for item in s:
        if isinstance(item, unittest.TestSuite):
            walk(item); continue
        cls = type(item)
        method = getattr(cls, getattr(item, "_testMethodName", ""), None)
        rows.append((item.id(), bool(
            getattr(cls, "__unittest_skip__", False)
            or getattr(method, "__unittest_skip__", False))))
walk(suite)
print(json.dumps({{"skipped": sorted(t for t, s in rows if s),
                   "total": len(rows)}}))
"""


def _skip_map(modules: tuple[str, ...], env: dict) -> dict:
    code = _SKIPMAP_SNIPPET.format(repo=str(REPO), modules=list(modules))
    proc = _run([sys.executable, "-c", code], env=env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestDeclaredDependencyContract(unittest.TestCase):
    """Every third-party import must be declared in the canonical
    manifests; the test environment installs with one command."""

    def test_canonical_test_manifest_exists_and_includes_runtime(self) -> None:
        self.assertTrue(
            REQ_TEST.exists(),
            "requirements-test.txt (canonical test manifest) is missing",
        )
        text = REQ_TEST.read_text(encoding="utf-8")
        self.assertIn(
            "-r requirements.txt", text,
            "the test manifest must include the runtime requirements",
        )

    def test_test_manifest_declares_pytest(self) -> None:
        self.assertIn(
            "pytest", _declared_names(REQ_TEST),
            "pytest is imported by test modules and must be declared in "
            "requirements-test.txt",
        )

    def test_runtime_manifest_declares_pyyaml(self) -> None:
        # yaml is imported by tracked runtime scripts; today it installs
        # only as a transitive extra of uvicorn[standard], which is not a
        # declaration.
        self.assertIn(
            "pyyaml", _declared_names(REQ_RUNTIME),
            "PyYAML is imported by runtime scripts and must be declared",
        )

    def test_every_backend_import_is_declared(self) -> None:
        paths = list((REPO / "tests").glob("*.py"))
        paths += list(REPO.glob("*.py"))
        paths += list((REPO / "routes").glob("*.py"))
        paths += list((REPO / "scripts").glob("*.py"))
        imports = _third_party_imports(paths)
        declared = _declared_names(REQ_RUNTIME, REQ_TEST)
        missing = {
            mod: sorted(files)[:3]
            for mod, files in imports.items()
            if _DIST_NAME.get(mod, mod).lower() not in declared
        }
        self.assertEqual(
            missing, {},
            f"undeclared third-party imports found: {missing}",
        )

    def test_fastapi_constrained_below_route_representation_change(self) -> None:
        # Evidence (T1 bisect in a clean venv): route-enumeration tests
        # pass on fastapi 0.135.3 and 0.136.3 and fail on 0.137.2,
        # 0.138.2 and 0.139.0 under both starlette 1.0.0 and 1.3.1.
        text = REQ_TEST.read_text(encoding="utf-8") if REQ_TEST.exists() else ""
        match = re.search(r"^fastapi\s*([<>=,.\d\s]+)", text, re.M)
        self.assertIsNotNone(
            match, "requirements-test.txt must carry the fastapi bound",
        )
        spec = match.group(1).replace(" ", "")
        self.assertIn("<0.137", spec)
        self.assertIn(">=0.135", spec)

    def test_formerly_uncollectable_modules_import_in_subprocess(self) -> None:
        code = (
            "import sys; sys.path.insert(0, {repo!r})\n"
            "import importlib\n"
            "for mod in {mods!r}:\n"
            "    importlib.import_module(mod)\n"
            "print('IMPORTS-OK')\n"
        ).format(repo=str(REPO), mods=list(FORMERLY_UNCOLLECTABLE))
        proc = _run([sys.executable, "-c", code], env=_gate_stripped_env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("IMPORTS-OK", proc.stdout)


class TestLocalDataGateContract(unittest.TestCase):
    """The shared explicit local/live-data opt-in gate."""

    def _gate(self):
        from tests import _local_data_gate
        return _local_data_gate

    def test_gate_disabled_by_default(self) -> None:
        gate = self._gate()
        self.assertFalse(gate.local_data_opt_in(environ={}))
        self.assertIsNone(gate.local_events_db_or_none(environ={}))

    def test_file_presence_alone_never_enables(self) -> None:
        gate = self._gate()
        # A real, existing path in the path variable is NOT enough
        # without the enable flag.
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as fh:
            path = fh.name
        try:
            env = {"SECOND_ORDER_LOCAL_EVENTS_DB": path}
            self.assertIsNone(gate.local_events_db_or_none(environ=env))
        finally:
            os.unlink(path)

    def test_enabled_without_path_fails_closed(self) -> None:
        gate = self._gate()
        env = {"SECOND_ORDER_RUN_LOCAL_DATA_TESTS": "1"}
        self.assertIsNone(gate.local_events_db_or_none(environ=env))
        reason = gate.local_data_skip_reason(environ=env)
        self.assertIn("SECOND_ORDER_LOCAL_EVENTS_DB", reason)

    def test_enabled_with_missing_path_fails_closed(self) -> None:
        gate = self._gate()
        env = {
            "SECOND_ORDER_RUN_LOCAL_DATA_TESTS": "1",
            "SECOND_ORDER_LOCAL_EVENTS_DB": os.path.join(
                tempfile.gettempdir(), "definitely_missing_t1.db"),
        }
        self.assertIsNone(gate.local_events_db_or_none(environ=env))
        self.assertIn("does not exist", gate.local_data_skip_reason(environ=env))

    def test_enabled_with_valid_path_resolves(self) -> None:
        gate = self._gate()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as fh:
            path = fh.name
        try:
            env = {
                "SECOND_ORDER_RUN_LOCAL_DATA_TESTS": "1",
                "SECOND_ORDER_LOCAL_EVENTS_DB": path,
            }
            resolved = gate.local_events_db_or_none(environ=env)
            self.assertIsNotNone(resolved)
            self.assertEqual(Path(path).resolve(), resolved)
        finally:
            os.unlink(path)

    def test_gate_never_falls_back_to_root_events_db(self) -> None:
        gate = self._gate()
        # Enabled with no path, while a root events.db exists in the
        # repository: the gate must NOT silently supply it.
        env = {"SECOND_ORDER_RUN_LOCAL_DATA_TESTS": "1"}
        resolved = gate.local_events_db_or_none(environ=env)
        self.assertIsNone(
            resolved,
            "the gate must never fall back to the root archive",
        )

    def test_skip_reason_names_the_missing_opt_in(self) -> None:
        gate = self._gate()
        reason = gate.local_data_skip_reason(environ={})
        self.assertIn("SECOND_ORDER_RUN_LOCAL_DATA_TESTS", reason)


class TestDefaultUniverseInvariance(unittest.TestCase):
    """Root events.db presence must not change the default universe."""

    def test_migrated_modules_do_not_condition_on_root_presence(self) -> None:
        offenders: dict[str, list[str]] = {}
        for module in ROOT_PRESENCE_MODULES + (
            "tests.test_reaction_profile_calibration_report",
        ):
            path = REPO / (module.replace(".", os.sep) + ".py")
            text = path.read_text(encoding="utf-8")
            hits = [
                line.strip()
                for line in text.splitlines()
                # Root-anchored constructions only: temp-dir fixture DBs
                # (os.path.join(dtmp, "events.db")) are legitimate.
                if re.search(
                    r"""(\bROOT\b|\b_ROOT\b|\b_REPO\b|\bREPO\b|parents\[1\])"""
                    r"""\s*[,/]\s*["']events\.db["']""",
                    line,
                )
                or re.search(r"""Path\(["']events\.db["']\)""", line)
            ]
            if hits:
                offenders[module] = hits[:3]
            if "_local_data_gate" not in text:
                offenders.setdefault(module, []).append(
                    "does not import tests._local_data_gate")
        self.assertEqual(
            offenders, {},
            f"modules still condition on root events.db presence: {offenders}",
        )

    def test_gate_off_skips_live_tests_even_when_root_db_present(self) -> None:
        # The live checkout carries a root events.db.  With the gate off
        # (default), the formerly presence-activated live tests must be
        # skip-flagged at collection time.
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as fh:
            synthetic = fh.name
        try:
            off = _skip_map(ROOT_PRESENCE_MODULES, _gate_stripped_env())
            on = _skip_map(ROOT_PRESENCE_MODULES, _gate_stripped_env({
                "SECOND_ORDER_RUN_LOCAL_DATA_TESTS": "1",
                "SECOND_ORDER_LOCAL_EVENTS_DB": synthetic,
            }))
        finally:
            os.unlink(synthetic)
        self.assertEqual(off["total"], on["total"],
                         "the gate must not add or remove tests")
        activated = sorted(set(off["skipped"]) - set(on["skipped"]))
        self.assertGreater(
            len(activated), 0,
            "the explicit opt-in must activate the migrated live tests",
        )
        deactivated = set(on["skipped"]) - set(off["skipped"])
        self.assertEqual(
            deactivated, set(),
            "enabling the gate must never skip a default test",
        )
        # Test ids look like tests.test_x.Class.method.
        touched_modules = {t.split(".")[1] for t in activated}
        for module in ROOT_PRESENCE_MODULES:
            self.assertIn(
                module.split(".")[-1], touched_modules,
                f"{module} has no gate-controlled live tests",
            )

    def test_gate_off_map_is_deterministic(self) -> None:
        first = _skip_map(ROOT_PRESENCE_MODULES[:3], _gate_stripped_env())
        second = _skip_map(ROOT_PRESENCE_MODULES[:3], _gate_stripped_env())
        self.assertEqual(first, second)


class TestBootstrapParityAndSafety(unittest.TestCase):
    """pytest and unittest entry paths share the same safety policy."""

    def _probe(self, runner_code: str) -> dict:
        code = (
            "import sys; sys.path.insert(0, {repo!r})\n"
            "{runner}\n"
            "import json, os, db\n"
            "from tests import _local_data_gate as gate\n"
            "print(json.dumps({{\n"
            "  'db_file_is_root': db.DB_FILE == 'events.db',\n"
            "  'events_db_file_env_set': bool(os.environ.get('EVENTS_DB_FILE')),\n"
            "  'gate_enabled': gate.local_data_opt_in(),\n"
            "}}))\n"
        ).format(repo=str(REPO), runner=runner_code)
        proc = _run([sys.executable, "-c", code], env=_gate_stripped_env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_unittest_and_pytest_bootstrap_share_safety_policy(self) -> None:
        unittest_state = self._probe("import tests")
        pytest_state = self._probe(
            "import tests.conftest" if (REPO / "tests" / "conftest.py").exists()
            else "import tests")
        self.assertEqual(unittest_state, pytest_state)
        self.assertFalse(unittest_state["db_file_is_root"],
                         "bootstrap must redirect db.DB_FILE off the root")
        self.assertTrue(unittest_state["events_db_file_env_set"])
        self.assertFalse(unittest_state["gate_enabled"])

    def test_collection_does_not_create_root_db_in_clean_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code = (
                "import sys; sys.path.insert(0, {repo!r})\n"
                "import unittest\n"
                "unittest.TestLoader().loadTestsFromName("
                "'tests.test_track_record_scoring')\n"
                "print('COLLECT-OK')\n"
            ).format(repo=str(REPO))
            env = _gate_stripped_env()
            env.pop("EVENTS_DB_FILE", None)
            proc = _run([sys.executable, "-c", code], cwd=Path(tmp), env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse(
                (Path(tmp) / "events.db").exists(),
                "collection must not create a root events.db",
            )


class TestEnvironmentPreflight(unittest.TestCase):
    """The canonical environment preflight is valid and repeatable."""

    def test_preflight_exists(self) -> None:
        self.assertTrue(PREFLIGHT.exists(),
                        "scripts/test_environment_preflight.py is missing")

    def test_preflight_json_ok_and_repeatable(self) -> None:
        runs = []
        for _ in range(2):
            proc = _run(
                [sys.executable, str(PREFLIGHT), "--json"],
                env=_gate_stripped_env(),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            runs.append(json.loads(proc.stdout))
        self.assertEqual(runs[0], runs[1],
                         "preflight output must be deterministic")
        payload = runs[0]
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["local_data_gate_disabled"])
        self.assertEqual(payload["module_import_failures"], [])
        self.assertTrue(payload["fastapi_within_supported_bound"])
        self.assertTrue(payload["root_db_untouched"])


if __name__ == "__main__":
    unittest.main()
