"""Tests for the Mission G research contract (H2).

Contract under test:

* the structured summary is built at request time by PARSING the tracked
  Mission G artifacts (stats/G*.md) - no local events.db, no price cache,
  no provider, no committed generated JSON, and no hand-copied computed
  number anywhere in the module;
* evidence lanes stay separate: accepted 86 and historical 97 (65 FOMC +
  32 OPEC) are distinct subtrees with an explicit pooling prohibition,
  and no field ever carries their sum;
* the bounded OPEC association uses the exact approved wording and is
  verified present in the tracked artifact at build time;
* the failure ledger stays visible: broad FOMC null, 44/120 LOEO and
  76/120 LOYO stability reversals, era-bounded secondary credit (36/97,
  9/12 fragile), and the G3B mechanism-comparability failure;
* the six representative cases are labeled illustrations, never proof;
* artifact drift fails loudly rather than serving stale or wrong numbers.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import mission_g_evidence as mge  # noqa: E402

STATS = ROOT / "stats"

APPROVED_OPEC_WORDING = ("stable descriptive association with unresolved "
                         "calendar-time confounding")

FROZEN_CASE_IDS = {
    "opec-2024-11-03-one-month-delay",
    "opec-2023-11-30-voluntary-2p2",
    "opec-2025-09-07-oct-137k",
    "opec-2024-03-03-q2-extension",
    "fomc-policy-decision-2019-09-18",
    "fomc-policy-decision-2018-05-02",
}

BANNED_VOCABULARY = ("validated", "causal", "predictive", "signal",
                     "strongest", "top findings", "winner", "alpha",
                     "buy", "sell")


def _build():
    return mge.build_mission_g_evidence_summary()


def _all_numbers(obj, out=None):
    if out is None:
        out = []
    if isinstance(obj, dict):
        for v in obj.values():
            _all_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _all_numbers(v, out)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append(obj)
    return out


class LaneSeparationTests(unittest.TestCase):
    def test_denominators_are_exact_and_separate(self):
        s = _build()
        lanes = s["lanes"]
        self.assertEqual(lanes["accepted_track_record"]["count"], 86)
        hist = lanes["historical"]
        self.assertEqual(hist["total"], 97)
        self.assertEqual(hist["fomc_frame_complete"], 65)
        self.assertEqual(hist["opec_designed_contrast"], 32)
        self.assertEqual(hist["fomc_frame_complete"]
                         + hist["opec_designed_contrast"], hist["total"])

    def test_lanes_are_never_pooled(self):
        s = _build()
        self.assertIn("never pooled",
                      s["lanes"]["pooling_prohibition"].lower())
        self.assertNotIn(183, _all_numbers(s))  # 86 + 97 must exist nowhere

    def test_accepted_lane_carries_its_own_scope_note(self):
        s = _build()
        note = s["lanes"]["accepted_track_record"]["lane_note"].lower()
        self.assertIn("separate", note)


class MainResultTests(unittest.TestCase):
    def test_fomc_null_is_present_with_parsed_max_rho(self):
        s = _build()
        null = s["main_result"]["fomc_null"]
        self.assertEqual(null["max_abs_full_sample_rho"], 0.2746)
        self.assertIn("null", s["main_result"]["headline"].lower()
                      + null["statement"].lower())

    def test_stability_diagnostics_are_parsed(self):
        s = _build()
        st = s["stability"]
        self.assertEqual(st["continuous_associations"], 120)
        self.assertEqual(st["loeo_sign_reversals"], 44)
        self.assertEqual(st["loyo_sign_reversals"], 76)


class BoundedOpecTests(unittest.TestCase):
    def test_exact_approved_wording(self):
        s = _build()
        self.assertEqual(s["bounded_opec_association"]["wording"],
                         APPROVED_OPEC_WORDING)

    def test_per_horizon_facts_are_parsed_from_g6b(self):
        s = _build()
        rows = s["bounded_opec_association"]["per_horizon"]
        self.assertEqual([r["horizon"] for r in rows], [1, 5, 20])
        for r in rows:
            self.assertLess(r["rho"], 0)
            self.assertEqual(r["loeo_sign_reversals"], 0)
            self.assertEqual(r["loyo_sign_reversals"], 0)
        self.assertEqual(rows[0]["rho"], -0.4564)

    def test_no_banned_vocabulary_anywhere(self):
        dumped = json.dumps(_build()).lower()
        for banned in BANNED_VOCABULARY:
            self.assertNotIn(banned, dumped, banned)


class CreditAndFailureTests(unittest.TestCase):
    def test_credit_limitation_fields(self):
        s = _build()
        c = s["credit_limitation"]
        self.assertEqual(c["available"], 36)
        self.assertEqual(c["of"], 97)
        self.assertEqual(c["fomc_subset"], 20)
        self.assertEqual(c["opec_subset"], 16)
        self.assertTrue(c["era_bounded"])
        self.assertEqual(c["status"], "secondary")
        self.assertEqual(c["fragile_associations"], 9)
        self.assertEqual(c["of_associations"], 12)

    def test_mechanism_comparability_failure_stays_visible(self):
        s = _build()
        f = s["failed_thesis_mechanism_comparability"]
        cov = f["classification_coverage_percent"]
        self.assertEqual(cov["accepted_news_headlines"], 79.1)
        self.assertEqual(cov["fomc_official_text"], 0.0)
        self.assertEqual(cov["opec_official_text"], 3.1)
        self.assertIn("not", f["statement"].lower())


class RepresentativeCaseTests(unittest.TestCase):
    def test_six_cases_labeled_illustrative(self):
        s = _build()
        rc = s["representative_cases"]
        self.assertEqual(rc["role_slots"], 6)
        self.assertEqual(rc["unique_cases"], 6)
        self.assertIn("illustrations, never proof", rc["status"])
        ids = {c["candidate_id"] for c in rc["cases"]}
        self.assertEqual(ids, FROZEN_CASE_IDS)
        for c in rc["cases"]:
            self.assertIn(c["role"], ("A", "B", "C"))
            self.assertIn(c["quantile"], ("q25", "q75"))


class DriftAndSafetyTests(unittest.TestCase):
    def test_artifact_drift_fails_loudly(self):
        text = (STATS / "G6B_STABILITY_AND_FALSIFIERS.md").read_text(
            encoding="utf-8")
        tampered = text.replace(
            "associations with at least one LOEO sign reversal", "GONE")
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "g6b.md"
            bad.write_text(tampered, encoding="utf-8")
            with self.assertRaises(ValueError):
                mge.build_mission_g_evidence_summary(g6b_path=bad)

    def test_missing_approved_wording_fails_loudly(self):
        text = (STATS / "G6C_REPRESENTATIVE_CASES.md").read_text(
            encoding="utf-8")
        tampered = text.replace("unresolved calendar-time confounding",
                                "resolved confounding")
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "g6c.md"
            bad.write_text(tampered, encoding="utf-8")
            with self.assertRaises(ValueError):
                mge.build_mission_g_evidence_summary(g6c_path=bad)

    def test_module_imports_no_db_and_no_network(self):
        src = Path(mge.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for banned in ("db", "sqlite3", "urllib", "requests", "httpx",
                       "market_data", "yfinance", "price_cache"):
            self.assertNotIn(banned, imported, banned)

    def test_module_source_carries_no_hardcoded_research_numbers(self):
        # every computed research number must be PARSED from the artifacts,
        # never written into the module source (interpretation prose only).
        src = Path(mge.__file__).read_text(encoding="utf-8")
        body = re.sub(r'("""[\s\S]*?"""|#[^\n]*)', "", src)
        for banned in (r"\b86\b", r"\b97\b", r"\b65\b", r"\b44\b",
                       r"\b76\b", r"\b120\b", r"0\.2746", r"79\.1",
                       r"\b36\b"):
            self.assertIsNone(re.search(banned, body),
                              f"hardcoded research number {banned}")

    def test_build_is_deterministic(self):
        a = _build()
        b = _build()
        self.assertEqual(a, copy.deepcopy(b))


class EndpointTests(unittest.TestCase):
    def test_get_evidence_mission_g_serves_builder_output(self):
        from fastapi.testclient import TestClient

        import api as api_mod

        with TestClient(api_mod.app) as client:
            resp = client.get("/evidence/mission-g")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         json.loads(json.dumps(_build())))


if __name__ == "__main__":
    unittest.main()
