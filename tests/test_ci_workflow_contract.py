"""CI enforcement contract for the published evidence layer (V1).

The tracked GitHub Actions workflow must protect the already-published
Mission G / Mission I / Mission J contracts, the provider boundary, the
reproduction-safety suite, and the frontend evidence consumers (reviewer
guide, research-record memo/export, Mission evidence cards) — without
adding full backend unittest discovery.

Deterministic text inspection of the tracked workflow file only: no YAML
dependency, no network, no subprocess.  Each missing requirement fails
with a message naming the absent contract.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

REQUIRED_BACKEND_MODULES = (
    "tests.test_mission_g_evidence",
    "tests.test_mission_i_evidence",
    "tests.test_mission_j_evidence",
    "tests.test_get_provider_boundary",
    "tests.test_news_get_boundary",
    "tests.test_admin_guard",
    "tests.test_track_record_reproduction_safety",
    "tests.test_ci_workflow_contract",
)


class CiWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_exists(self):
        self.assertTrue(WORKFLOW.is_file(),
                        "tracked workflow .github/workflows/ci.yml missing")

    def test_backend_evidence_modules_enforced(self):
        for module in REQUIRED_BACKEND_MODULES:
            self.assertIn(
                module, self.text,
                f"CI does not run {module}: the published evidence "
                "contract it protects is unenforced")

    def test_frontend_evidence_coverage_enforced(self):
        # The full frontend suite covers the reviewer-guide pure/UI tests,
        # the research-record memo/export tests, the Mission G/I/J card
        # contract tests, and the provenance-parity suite.
        self.assertIn("npm ci", self.text,
                      "CI does not install the frontend workspace")
        self.assertIn("npm test", self.text,
                      "CI does not run the frontend evidence suites")
        self.assertIn("npm run build", self.text,
                      "CI does not run the frontend typecheck + build "
                      "(npm run build = tsc -b && vite build)")

    def test_no_full_backend_discovery(self):
        self.assertNotIn(
            "unittest discover", self.text,
            "CI must stay targeted: full backend discovery is not part "
            "of the safe-health workflow")
        # A YAML folded scalar (run: >-) legitimately puts the module list
        # on continuation lines, so a line ending in "-m unittest [-v]" is
        # bare discovery only when no "tests.<module>" continuation follows.
        lines = self.text.splitlines()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.endswith("python -m unittest") \
                    or stripped.endswith("python -m unittest -v"):
                following = next(
                    (nxt.strip() for nxt in lines[idx + 1:] if nxt.strip()),
                    "")
                if not following.startswith("tests."):
                    self.fail(
                        "CI runs bare python -m unittest with no module "
                        f"list (implicit discovery): {stripped!r}")

    def test_existing_safe_health_steps_preserved(self):
        # The V1 extension must not replace the existing workflow.
        for kept in ("scripts/test_environment_preflight.py",
                     "scripts/repo_hygiene_check.py",
                     "scripts/no_paid_smoke.py",
                     "tests.test_tracked_evidence"):
            self.assertIn(kept, self.text,
                          f"existing safe-health step {kept} was removed")


if __name__ == "__main__":
    unittest.main()
