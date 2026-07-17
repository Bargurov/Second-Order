"""Tests for the Mission J research contract (mission-j-evidence-v1).

Contract under test:

* the structured summary is built at request time by PARSING the tracked
  final publications (stats/J1B_FOMC_ROBUSTNESS_RESULTS.md,
  stats/J2_TIMING_COLLISION_RESULTS.md,
  stats/J3_MECHANISM_TRANSMISSION_READOUT.md) - no events.db, no price
  cache, no provider, no network, and no hand-copied research number
  anywhere in the module;
* the production path performs NO research computation and NO node/edge
  re-adjudication: the final published J3 states are parsed from the J3
  publication, never re-derived (the frozen assembler is a test-time
  cross-check only);
* J1B, J2, and J3 remain separate, non-pooled sections; null,
  ordinary/unresolved, descriptive-only, unadjudicable, and
  measurement-limited results are first-class fields;
* artifact drift (missing file, malformed cardinality, changed identity)
  fails loudly rather than serving stale, partial, or reinterpreted
  numbers.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import mission_j_evidence as mje  # noqa: E402

STATS = ROOT / "stats"
J1B_PATH = STATS / "J1B_FOMC_ROBUSTNESS_RESULTS.md"
J2_PATH = STATS / "J2_TIMING_COLLISION_RESULTS.md"
J3_PATH = STATS / "J3_MECHANISM_TRANSMISSION_READOUT.md"

INSUFFICIENT_PHRASE = "insufficient subset under the frozen procedure"

# Assertive claim vocabulary that must never appear in the payload.
# Negated non-claims (e.g. "- alpha;" under "does not establish") are
# frozen research wording and are NOT in this list.
BANNED_VOCABULARY = ("validated", "mechanism confirmed", "proven",
                     "winner", "strongest", "top finding", "buy", "sell")

POOLED_KEY_FRAGMENTS = ("score", "rank", "probabilit", "strength",
                        "combined", "merged", "average", "pooled",
                        "mission_g", "mission_i", "accepted_track_record")


def _build(**kwargs):
    return mje.build_mission_j_evidence_summary(**kwargs)


_PAYLOAD_CACHE: dict = {}


def _payload():
    if "p" not in _PAYLOAD_CACHE:
        _PAYLOAD_CACHE["p"] = _build()
    return _PAYLOAD_CACHE["p"]


def _tampered(path: Path, old: str, new: str, td: str) -> Path:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"fixture precondition missing: {old!r}"
    bad = Path(td) / path.name
    bad.write_text(text.replace(old, new), encoding="utf-8")
    return bad


def _all_keys(obj, out=None):
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k).lower())
            _all_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _all_keys(v, out)
    return out


# ---------------------------------------------------------------------------
# Contract integrity (1-4)
# ---------------------------------------------------------------------------


class ContractIntegrityTests(unittest.TestCase):
    def test_1_contract_version(self):
        self.assertEqual(_payload()["contract_version"],
                         "mission-j-evidence-v1")

    def test_2_exact_top_level_sections(self):
        self.assertEqual(sorted(_payload()),
                         ["contract_version", "j1b", "j2", "j3",
                          "provenance"])

    def test_3_exact_cardinalities(self):
        p = _payload()
        self.assertEqual(len(p["j1b"]["cells"]), 12)
        self.assertEqual(len(p["j2"]["state_bearing"]), 4)
        self.assertEqual(len(p["j2"]["diagnostics"]), 4)
        self.assertEqual(len(p["j3"]["nodes"]), 4)
        self.assertEqual(len(p["j3"]["edges"]), 3)
        self.assertEqual(len(p["j1b"]["panels"]), 3)

    def test_4_frozen_ordering(self):
        p = _payload()
        self.assertEqual([c["cell"] for c in p["j1b"]["cells"]],
                         list(range(1, 13)))
        self.assertEqual([c["cell"] for c in p["j2"]["state_bearing"]],
                         [13, 14, 15, 16])
        self.assertEqual([d["id"] for d in p["j2"]["diagnostics"]],
                         ["D1", "D2", "D3", "D4"])
        self.assertEqual([n["node"] for n in p["j3"]["nodes"]],
                         ["N0", "N1", "N2", "N3"])
        self.assertEqual([e["edge"] for e in p["j3"]["edges"]],
                         ["E1", "E2", "E3"])

    def test_4b_provenance_carries_immutable_sources(self):
        prov = _payload()["provenance"]
        for key, path in (("j1b", J1B_PATH), ("j2", J2_PATH),
                          ("j3", J3_PATH)):
            src = prov["sources"][key]
            self.assertEqual(src["artifact"], path.name)
            self.assertEqual(
                src["sha256"],
                hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(src["bytes"], path.stat().st_size)
        self.assertIn("closed", prov["publication_status"])
        self.assertIn("computes no research statistic",
                      prov["no_recompute_statement"])


# ---------------------------------------------------------------------------
# Published-value fidelity (5-14)
# ---------------------------------------------------------------------------


class J1BFidelityTests(unittest.TestCase):
    def test_5_exact_denominators_and_decimal_precision(self):
        cells = {c["cell"]: c for c in _payload()["j1b"]["cells"]}
        c1 = cells[1]
        self.assertEqual((c1["measurement"], c1["lens"]),
                         ("KRE", "rolling_beta_ar"))
        self.assertEqual(c1["attempted_event_n"], 65)
        self.assertEqual(c1["available_event_n"], 64)
        self.assertEqual(c1["reference_n"], 1797)
        self.assertEqual(c1["memp"], "0.664719")
        self.assertEqual(c1["calibration_percentile"], "0.998000")
        self.assertEqual(c1["node_state"], "ELEVATED")
        self.assertEqual(c1["loyo"], "0/8")
        self.assertEqual(c1["loeo"], "0/64")
        self.assertEqual(c1["f3_reference_n"], 1797)
        self.assertEqual(c1["f3_canonical_n"], 917)
        self.assertEqual(c1["f3_memp"], "0.655398")
        self.assertIs(c1["f3_sign_flip"], False)
        self.assertEqual(c1["unavailable_events"],
                         [["2018-01-31", "insufficient_history_252_20"]])
        # Exact published trailing zeros survive (cell 2 calibration).
        self.assertEqual(cells[2]["calibration_percentile"], "1.000000")
        self.assertEqual(cells[6]["reference_n"], 1816)
        self.assertEqual(cells[6]["available_event_n"], 65)
        self.assertEqual(cells[10]["reference_n"], 1804)
        self.assertEqual(cells[12]["memp"], "0.579295")
        for c in cells.values():
            self.assertEqual(c["node_state"], "ELEVATED")
            self.assertIn("m_class", c)
            self.assertIn("role", c)
            self.assertIn("evidence_class", c)

    def test_6_exact_panel_modifiers(self):
        panels = {p["role"]: p for p in _payload()["j1b"]["panels"]}
        self.assertEqual(sorted(panels), [
            "balance_sheet_sensitive_second_order",
            "broad_financial_sector", "policy_rates_repricing"])
        for p in panels.values():
            self.assertEqual(p["modifier"],
                             "BROAD MEASUREMENT CONSISTENCY")
        self.assertEqual(panels["policy_rates_repricing"]["members"],
                         ["2Y_CMT", "SHY"])
        self.assertEqual(panels["policy_rates_repricing"]["primary"],
                         "2Y_CMT")
        self.assertEqual(
            panels["balance_sheet_sensitive_second_order"]["members"],
            ["KRE", "IAT", "KBE"])

    def test_6b_j1b_qualifications_present(self):
        j1b = _payload()["j1b"]
        self.assertEqual(j1b["contextual_2s10s"]["measurement"],
                         "2S10S_CMT")
        self.assertEqual(j1b["contextual_2s10s"]["state"], "ELEVATED")
        self.assertIn("measurement-limited",
                      j1b["measurement_limited"]["statement"])
        self.assertIn("M1", j1b["measurement_limited"]["statement"])
        self.assertIn("correlated",
                      j1b["correlated_views_disclosure"])
        self.assertTrue(any("independent historical confirmation" in n
                            for n in j1b["non_claims"]))


class J2FidelityTests(unittest.TestCase):
    def test_7_exact_states_and_denominators(self):
        cells = {c["cell"]: c for c in _payload()["j2"]["state_bearing"]}
        self.assertEqual(
            [cells[n]["node_state"] for n in (13, 14, 15, 16)],
            ["ORDINARY_UNRESOLVED", "ORDINARY_UNRESOLVED",
             "ELEVATED", "ELEVATED"])
        for n in (13, 14, 15, 16):
            self.assertEqual(cells[n]["attempted_event_n"], 65)
            self.assertEqual(cells[n]["available_event_n"], 65)
            self.assertEqual(cells[n]["reference_n"], 1427)
        self.assertEqual(cells[13]["memp"], "0.491240")
        self.assertEqual(cells[13]["loyo"], "4/8")
        self.assertEqual(cells[13]["loeo"], "32/65")
        self.assertEqual(cells[13]["f3_canonical_n"], 297)
        self.assertEqual(cells[16]["calibration_percentile"], "0.889000")
        frag = _payload()["j2"]["raw_cell_fragility"]
        self.assertEqual(frag["loyo"], "4/8")
        self.assertEqual(frag["loeo"], "32/65")

    def test_8_diagnostics_descriptive_only_and_stateless(self):
        diags = _payload()["j2"]["diagnostics"]
        for d in diags:
            self.assertIs(d["descriptive_only"], True)
            self.assertIn("no ordinary-reference state",
                          d["status_wording"])
            for banned in ("memp", "calibration_percentile", "node_state",
                           "loyo", "loeo", "f3_memp", "f3_sign_flip"):
                self.assertNotIn(banned, d, banned)
            self.assertEqual(d["attempted_event_n"], 65)
            self.assertEqual(d["available_event_n"], 65)
        by_id = {d["id"]: d for d in diags}
        self.assertEqual(by_id["D1"]["median_response"], "0.003612")
        self.assertEqual(by_id["D4"]["direction"], "negative")

    def test_9_c1_remains_unadjudicable_with_reason(self):
        c1 = _payload()["j2"]["collisions"]["c1"]
        self.assertEqual(c1["status"], "unadjudicable")
        self.assertIn("source-pinned", c1["reason"])
        self.assertIn("BLS", c1["families"])

    def test_10_c2_zero_of_65_and_subset_status(self):
        col = _payload()["j2"]["collisions"]
        self.assertEqual(col["interval"], "[t, t+1]")
        self.assertEqual(col["primary_n"], 65)
        self.assertEqual(col["collision_free_n"], 65)
        c2 = col["c2"]
        self.assertEqual(c2["tagged_n"], 0)
        self.assertEqual(c2["of"], 65)
        self.assertEqual(c2["register"],
                         "opec-known-date-exclusion-register@i0-v1")
        self.assertEqual(c2["register_dates"], 41)
        self.assertEqual(c2["subset_status"], INSUFFICIENT_PHRASE)
        self.assertIn("outside known-register collisions",
                      col["limitation"])
        self.assertEqual(col["fomc_self"]["min_anchor_spacing"], 8)
        self.assertEqual(col["fomc_self"]["violations"], 0)

    def test_10b_timing_interpretation_carried_per_cell(self):
        lines = _payload()["j2"]["timing_interpretation"]
        self.assertEqual(len(lines), 4)
        self.assertIn("more concentrated around the official anchor",
                      lines[0])
        self.assertIn("do not isolate", lines[2])


class J3FidelityTests(unittest.TestCase):
    def test_11_exact_node_readings(self):
        nodes = {n["node"]: n for n in _payload()["j3"]["nodes"]}
        for node_id in ("N0", "N1", "N2", "N3"):
            self.assertEqual(nodes[node_id]["reading"], "ACTIVATED")
            self.assertTrue(nodes[node_id]["rule_path"])
        self.assertEqual(nodes["N1"]["role"], "policy_rates_repricing")
        self.assertEqual(nodes["N1"]["m_class"], "M2")
        self.assertEqual(nodes["N2"]["modifier"],
                         "BROAD MEASUREMENT CONSISTENCY")
        members = {m["member"]: m for m in nodes["N2"]["panel"]}
        self.assertEqual(sorted(members), ["IAT", "KBE", "KRE"])
        self.assertIs(members["KRE"]["primary"], True)
        self.assertIs(members["IAT"]["primary"], False)
        self.assertEqual(members["KRE"]["state"], "ELEVATED")

    def test_12_exact_three_propagated_edges(self):
        edges = _payload()["j3"]["edges"]
        self.assertEqual([e["state"] for e in edges],
                         ["PROPAGATED", "PROPAGATED", "PROPAGATED"])
        self.assertEqual(edges[1]["from"], "policy_rates_repricing")
        self.assertEqual(edges[1]["to"],
                         "balance_sheet_sensitive_second_order")

    def test_13_exact_explanation_paths(self):
        edges = _payload()["j3"]["edges"]
        for e in edges:
            self.assertIn("precedence step 3", e["rule_path"])
            self.assertTrue(e["upstream_reading"])
            self.assertTrue(e["upstream_path"])
        self.assertIn("definitional", edges[0]["upstream_path"])
        self.assertIn("Route A", edges[0]["rule_path"])

    def test_13b_qualifiers_and_ceilings_carried(self):
        j3 = _payload()["j3"]
        self.assertIn("lens-dependent under daily measurement",
                      j3["timing_qualifier"])
        self.assertIn("outside known-register collisions",
                      j3["collision_qualifier"])
        self.assertTrue(any("mechanism-consistent descriptive pattern"
                            in s for s in j3["supports"]))
        self.assertTrue(any("Class B" in s for s in j3["supports"]))
        self.assertTrue(any("measurement-limited" in s
                            for s in j3["supports"]))
        self.assertTrue(j3["unresolved"])
        self.assertTrue(any("causality" in n for n in j3["non_claims"]))

    def test_14_2s10s_remains_contextual_everywhere(self):
        p = _payload()
        for n in p["j3"]["nodes"]:
            for m in n["panel"]:
                self.assertNotEqual(m["member"], "2S10S_CMT")
        for e in p["j3"]["edges"]:
            blob = json.dumps(e)
            self.assertNotIn("2S10S", blob)
        self.assertIn("context",
                      p["j1b"]["contextual_2s10s"]["isolation_note"])


# ---------------------------------------------------------------------------
# No re-adjudication (15-18)
# ---------------------------------------------------------------------------


def _module_body_source() -> str:
    src = Path(mje.__file__).read_text(encoding="utf-8")
    return re.sub(r'("""[\s\S]*?"""|#[^\n]*)', "", src)


class NoReAdjudicationTests(unittest.TestCase):
    def test_15_route_never_references_the_assembler(self):
        body = _module_body_source()
        self.assertNotIn("assemble_readout", body)
        self.assertNotIn("reconcile_published_evidence", body)

    def test_16_route_never_references_execution_functions(self):
        body = _module_body_source()
        for banned in ("run_engine", "run_live", "run_state_bearing",
                       "run_diagnostics", "build_cell_substrate",
                       "timing_response", "edge_state(", "role_reading(",
                       "calibrate", "default_rng", "numpy"):
            self.assertNotIn(banned, body, banned)

    def test_15b_builder_succeeds_with_assembler_disabled(self):
        from scripts import j3_mechanism_readout as j3r

        def boom(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("production path re-adjudicated")

        with patch.object(j3r, "assemble_readout", boom), \
                patch.object(j3r, "edge_state", boom), \
                patch.object(j3r, "role_reading", boom):
            payload = _build()
        self.assertEqual([e["state"] for e in payload["j3"]["edges"]],
                         ["PROPAGATED", "PROPAGATED", "PROPAGATED"])

    def test_17_tampered_j3_fails_rather_than_readjudicating(self):
        with tempfile.TemporaryDirectory() as td:
            bad = _tampered(J3_PATH, "- final edge state: **PROPAGATED**",
                            "- edge verdict: PROPAGATED", td)
            with self.assertRaises(ValueError):
                _build(j3_path=bad)

    def test_18_published_states_agree_with_frozen_assembler(self):
        # Test-time integrity cross-check ONLY: the assembler re-derives
        # the readout from J1B/J2 and must agree with the published J3
        # states the route parsed. The assembler is not the payload source.
        from scripts import j3_mechanism_readout as j3r
        readout = j3r.assemble_readout(j3r.load_published_surfaces())
        payload = _payload()
        self.assertEqual(
            [e["state"] for e in payload["j3"]["edges"]],
            [e["state"] for e in readout["edges"]])
        self.assertEqual(
            [n["reading"] for n in payload["j3"]["nodes"]],
            [n["reading"] for n in readout["nodes"]])


# ---------------------------------------------------------------------------
# Artifact drift (19-23)
# ---------------------------------------------------------------------------


class ArtifactDriftTests(unittest.TestCase):
    def test_19_missing_artifact_fails_loudly(self):
        with self.assertRaises(ValueError):
            _build(j2_path=STATS / "DOES_NOT_EXIST.md")

    def test_20_malformed_cardinality_fails_loudly(self):
        text = J2_PATH.read_text(encoding="utf-8")
        row = next(line for line in text.splitlines()
                   if line.startswith("| 15 | KRE | sector_relative_ar"))
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / J2_PATH.name
            bad.write_text(text.replace(row + "\n", ""), encoding="utf-8")
            with self.assertRaises(ValueError):
                _build(j2_path=bad)

    def test_21_changed_cell_identity_fails_loudly(self):
        with tempfile.TemporaryDirectory() as td:
            bad = _tampered(
                J1B_PATH,
                "| 1 | KRE | rolling_beta_ar |",
                "| 1 | ZZZ | rolling_beta_ar |", td)
            with self.assertRaises(ValueError):
                _build(j1b_path=bad)

    def test_22_changed_edge_identity_fails_loudly(self):
        with tempfile.TemporaryDirectory() as td:
            bad = _tampered(
                J3_PATH,
                "### E2 `policy_rates_repricing` -> "
                "`balance_sheet_sensitive_second_order`",
                "### E2 `broad_financial_sector` -> "
                "`policy_rates_repricing`", td)
            with self.assertRaises(ValueError):
                _build(j3_path=bad)

    def test_23_no_partial_payload_on_drift(self):
        # The builder validates every section before returning anything;
        # a J3 drift must not leak a payload with valid J1B/J2 sections.
        with tempfile.TemporaryDirectory() as td:
            bad = _tampered(J3_PATH, "### N2", "### NX", td)
            try:
                out = _build(j3_path=bad)
            except ValueError:
                out = None
            self.assertIsNone(out)


# ---------------------------------------------------------------------------
# Read-only / GET boundary (24-29)
# ---------------------------------------------------------------------------


class ReadOnlyBoundaryTests(unittest.TestCase):
    def test_24_to_26_no_db_provider_or_network_import(self):
        for module in (mje,):
            src = Path(module.__file__).read_text(encoding="utf-8")
            tree = ast.parse(src)
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            for banned in ("db", "sqlite3", "urllib", "requests", "httpx",
                           "socket", "market_data", "market_check",
                           "yfinance", "price_cache"):
                self.assertNotIn(banned, imported, banned)

    def test_27_28_no_network_call_during_build(self):
        import socket

        def boom(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("network call during mission-j build")

        saved = socket.socket
        socket.socket = boom
        try:
            payload = _build()
        finally:
            socket.socket = saved
        self.assertEqual(payload["contract_version"],
                         "mission-j-evidence-v1")

    def test_29_source_artifacts_byte_identical_after_build(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (J1B_PATH, J2_PATH, J3_PATH)}
        _build()
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (J1B_PATH, J2_PATH, J3_PATH)}
        self.assertEqual(before, after)

    def test_29b_no_hardcoded_research_numbers_in_module(self):
        body = _module_body_source()
        for banned in (r"\b1797\b", r"\b1816\b", r"\b1804\b", r"\b1427\b",
                       r"\b917\b", r"\b297\b", r"0\.664719", r"0\.491240",
                       r"0\.998", r"\b64\b", r"\b65\b", r"\b41\b"):
            self.assertIsNone(re.search(banned, body),
                              f"hardcoded research number {banned}")

    def test_29c_deterministic_build(self):
        self.assertEqual(_build(), copy.deepcopy(_build()))

    def test_29d_no_pooled_summary_fields(self):
        keys = _all_keys(_payload())
        for fragment in POOLED_KEY_FRAGMENTS:
            self.assertFalse(
                any(fragment in k for k in keys),
                f"pooled/ranking key fragment {fragment!r} present")

    def test_29e_no_assertive_claim_vocabulary(self):
        # Word-boundary match so legitimate keys (e.g. "provenance") are
        # not false positives; multi-word phrases stay exact.
        dumped = json.dumps(_payload()).lower()
        for banned in BANNED_VOCABULARY:
            pattern = r"\b" + re.escape(banned.lower()) + r"\b"
            self.assertIsNone(re.search(pattern, dumped), banned)


# ---------------------------------------------------------------------------
# API behavior (30-32)
# ---------------------------------------------------------------------------


class EndpointTests(unittest.TestCase):
    def test_30_get_serves_builder_output(self):
        from fastapi.testclient import TestClient

        import api as api_mod

        with TestClient(api_mod.app) as client:
            resp = client.get("/evidence/mission-j")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), json.loads(json.dumps(_payload())))

    def test_31_32_drift_returns_stable_envelope_without_leaking(self):
        from fastapi.testclient import TestClient

        import api as api_mod

        def boom(**_k):
            raise ValueError(
                "mission-j artifact drift: C:\\secret\\local\\path.md")

        with patch.object(mje, "build_mission_j_evidence_summary", boom):
            with TestClient(api_mod.app) as client:
                resp = client.get("/evidence/mission-j")
        self.assertEqual(resp.status_code, 503)
        detail = resp.json()["detail"]
        self.assertIn("mission-j research record unavailable", detail)
        self.assertNotIn("secret", detail)
        self.assertNotIn("Traceback", resp.text)


# ---------------------------------------------------------------------------
# Execution provenance (V1): recorded in every Mission J publication,
# exposed consistently — parsed from the tracked files, never inferred.
# ---------------------------------------------------------------------------

# Frozen published values (verbatim from the tracked publications).
FROZEN_EXECUTION = {
    "j1b": {"execution_commit": "2ec68108affc1d3e084c7242e5b13669e3c5d76d",
            "executed_at": "2026-07-07T00:11:57Z"},
    "j2": {"execution_commit": "f7a9c799b5e5c7966d712362778734219a0558f3",
           "executed_at": "2026-07-10T16:27:14Z"},
    "j3": {"execution_commit": "3d6a9af80a20854c88a43af5e952c5276711a125",
           "executed_at": "2026-07-10T17:23:47Z"},
}


class ExecutionProvenanceTests(unittest.TestCase):
    def test_23_execution_metadata_exposed_for_all_three_publications(self):
        execution = _payload()["provenance"]["execution"]
        self.assertEqual(execution, FROZEN_EXECUTION)

    def test_24_values_come_from_the_tracked_files(self):
        # Independent extraction: the same lines the publications record.
        for key, path in (("j1b", J1B_PATH), ("j2", J2_PATH),
                          ("j3", J3_PATH)):
            text = path.read_text(encoding="utf-8")
            commit = re.search(
                r"^- execution commit: `([0-9a-f]{40})`$", text,
                re.MULTILINE).group(1)
            executed = re.search(
                r"^- executed at: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)$",
                text, re.MULTILINE).group(1)
            execution = _payload()["provenance"]["execution"][key]
            self.assertEqual(execution["execution_commit"], commit)
            self.assertEqual(execution["executed_at"], executed)

    def test_25_tampered_commit_changes_parsed_result(self):
        with tempfile.TemporaryDirectory() as td:
            bad = _tampered(J2_PATH,
                            "f7a9c799b5e5c7966d712362778734219a0558f3",
                            "a" * 40, td)
            payload = _build(j2_path=bad)
        self.assertEqual(
            payload["provenance"]["execution"]["j2"]["execution_commit"],
            "a" * 40)

    def test_26_missing_execution_commit_fails_loudly(self):
        text = J1B_PATH.read_text(encoding="utf-8")
        tampered = re.sub(r"^- execution commit: `[0-9a-f]{40}`\n", "",
                          text, flags=re.MULTILINE)
        self.assertNotEqual(tampered, text)
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / J1B_PATH.name
            bad.write_text(tampered, encoding="utf-8")
            with self.assertRaises(ValueError):
                _build(j1b_path=bad)

    def test_27_malformed_commit_or_timestamp_fails_loudly(self):
        with tempfile.TemporaryDirectory() as td:
            bad = _tampered(J3_PATH,
                            "3d6a9af80a20854c88a43af5e952c5276711a125",
                            "not-a-commit", td)
            with self.assertRaises(ValueError):
                _build(j3_path=bad)
        with tempfile.TemporaryDirectory() as td:
            bad = _tampered(J3_PATH, "2026-07-10T17:23:47Z",
                            "sometime in July", td)
            with self.assertRaises(ValueError):
                _build(j3_path=bad)

    def test_28_no_current_head_inference(self):
        src = Path(mje.__file__).read_text(encoding="utf-8")
        for banned in ("subprocess", "git rev-parse", "GITHUB_SHA",
                       "datetime.now", "date.today"):
            self.assertNotIn(banned, src)

    def test_29_reproduction_stays_honestly_unrecorded(self):
        # No Mission J publication records a reproduction command block;
        # the contract must state that as null, never fabricate one.
        prov = _payload()["provenance"]
        self.assertIsNone(prov["reproduction"])

    def test_30_research_sections_unchanged_by_execution_addition(self):
        payload = _payload()
        self.assertEqual(sorted(payload),
                         ["contract_version", "j1b", "j2", "j3",
                          "provenance"])
        self.assertEqual(len(payload["j1b"]["cells"]), 12)
        self.assertEqual(len(payload["j2"]["state_bearing"]), 4)
        self.assertEqual(len(payload["j3"]["edges"]), 3)


if __name__ == "__main__":
    unittest.main()
