"""QA check that a research-quality rubric version arrives as one compatible checkpoint (written by the QA chat).

A rubric change is a new version (research-quality-0.3 and on), adopted by Admin with the canonical Client constant,
the regenerated fixtures and the documents in the same commit (ACTIVE_LOCAL_LIVE_HANDOFF, 15 October 2026). The Client's
reader refuses a quality payload of any other version (frontend/src/contracts/news.ts), so a version named in one place
and not another would hide every check from the user. Nothing here judges the rubric itself; the measurements are in
test_qa_research_quality, test_qa_quality_fresh, test_qa_quality_released_1 and a private check kept outside the public tree.

- One version everywhere: research_quality.RUBRIC_VERSION, the Client's QUALITY_VERSION, both quality fixtures, the news
  contract's Quality heading and SPEC's description of the rubric.
- Every news-contract fixture is what tests/news_contract_fixtures.build() makes from the current backend, so flags
  that move with a new version cannot be left stale in the Client's fixtures.
"""
import json
from pathlib import Path
import re
import unittest

import news_contract_fixtures
from second_order import research_quality

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
VERSION = re.compile(r"research-quality-\d+\.\d+")


class QualityVersions(unittest.TestCase):
    def test_one_rubric_version_everywhere(self):
        version = research_quality.RUBRIC_VERSION
        self.assertRegex(version, rf"^{VERSION.pattern}$")
        news_ts = (ROOT / "frontend" / "src" / "contracts" / "news.ts").read_text(encoding="utf-8")
        named = {
            "frontend/src/contracts/news.ts QUALITY_VERSION":
                re.findall(r'QUALITY_VERSION\s*=\s*"([^"]+)"', news_ts),
            "docs/news-usage-contract.md Quality heading": re.findall(
                rf"^### Quality \(({VERSION.pattern})", (ROOT / "docs" / "news-usage-contract.md").read_text(
                    encoding="utf-8"), re.M),
            "SPEC.md rubric description": re.findall(
                rf"research-quality rubric \(({VERSION.pattern})", (ROOT / "SPEC.md").read_text(encoding="utf-8")),
        }
        for name in ("news-contract-quality", "news-contract-quality-flagged"):
            fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
            named[f"frontend/tests/fixtures/{name}.json"] = [fixture["quality"]["rubric_version"]]
        for place, found in named.items():
            with self.subTest(place):
                self.assertEqual(found, [version], f"{place} names {found}, the backend serves {version}")

    def test_every_news_fixture_is_what_the_backend_builds_now(self):
        built = news_contract_fixtures.build()
        self.assertIn("news-contract-quality-flagged", built)
        for name, payload in built.items():
            with self.subTest(name):
                committed = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
                self.assertEqual(committed, payload, f"frontend/tests/fixtures/{name}.json is stale; regenerate it "
                                                     "with tests/news_contract_fixtures.py in the owner's commit")


if __name__ == "__main__":
    unittest.main()
