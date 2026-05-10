"""Tests for ``scripts/repaired_cohort_demo_memo.py``.

Pin the contract:

* Memo dict carries the required keys: ``headline``,
  ``evidence_state``, ``supported_claims``, ``unsupported_claims``,
  ``next_target``, ``underpowered``, ``limitations``,
  ``source_summary``.
* States exactly what the current 5-event evidence supports:
    - 5 repaired clean events
    - 15 (event, horizon) records
    - 0 FDR-significant aggregate results
    - event 73 carries the validated_raw_only verdict
    - the evidence is underpowered
* Next target: expand repaired cohort to 10–15 events.
* Conservative language only — the memo NEVER asserts "proof",
  "alpha", or "predictive edge".  Disclaimers in
  ``unsupported_claims`` ARE allowed to mention those words to
  explicitly negate them.
* Read-only — the seam consumes
  ``manual_repaired_cohort_validation_summary``; the memo never
  opens the live DB or backup.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import repaired_cohort_demo_memo as memo_cli  # noqa: E402


_REQUIRED_KEYS = (
    "headline",
    "evidence_state",
    "supported_claims",
    "unsupported_claims",
    "next_target",
    "underpowered",
    "limitations",
    "source_summary",
)


_FORBIDDEN_IN_SUPPORTED_CLAIMS = (
    "proof",
    "alpha generated",
    "produces alpha",
    "alpha-generation",
    "predictive edge",
    "market edge",
    "out-of-sample edge",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _summary_payload(
    *,
    repaired_clean_event_ids: list[int]            | None = None,
    records_count:            int                          = 0,
    significant_count:        int                          = 0,
    by_event_verdict:         dict[str, str]       | None = None,
    top_abs_sar:              list[dict[str, Any]] | None = None,
    limitations:              list[str]            | None = None,
    recommended_next_action:  str                         = (
        "stub recommended next action"
    ),
) -> dict[str, Any]:
    """Build a stand-in for the upstream summary's 8-key dict."""
    repaired_clean_event_ids = repaired_clean_event_ids or []
    by_event_verdict         = by_event_verdict         or {}
    return {
        "repaired_clean_event_ids":  list(repaired_clean_event_ids),
        "events_evaluated":          len(repaired_clean_event_ids),
        "records_count":             records_count,
        "significant_count":         significant_count,
        "top_abs_sar":               list(top_abs_sar or []),
        "by_event_verdict":          dict(by_event_verdict),
        "limitations":               list(limitations or []),
        "recommended_next_action":   recommended_next_action,
    }


def _five_event_summary() -> dict[str, Any]:
    """The current 5-event repaired-cohort evidence state.

    Mirrors the spec: 5 repaired clean events, 15 (event, horizon)
    records, 0 FDR-significant aggregate results, event 73 carrying
    the validated_raw_only verdict.
    """
    return _summary_payload(
        repaired_clean_event_ids=[30, 40, 46, 60, 73],
        records_count=15,
        significant_count=0,
        by_event_verdict={
            "30": "insufficient",
            "40": "inconclusive_fdr",
            "46": "insufficient",
            "60": "inconclusive_fdr",
            "73": "validated_raw_only",
        },
    )


def _patch_seam(payload: dict[str, Any]):
    def fake(*, backup_path, high_priority_csv, medium_csv,
             mechanism_family_csv=None, db_path, limit, alpha):
        return payload
    return patch.object(
        memo_cli, "_run_validation_summary", side_effect=fake,
    )


def _build_memo(payload: dict[str, Any], **kwargs) -> dict[str, Any]:
    """Run the memo by patching the seam.  Saves callers from
    repeating the patch boilerplate."""
    with _patch_seam(payload):
        return memo_cli.build_repaired_cohort_demo_memo(
            backup_path="/dev/null/backup.db",
            high_priority_csv="/dev/null/high.csv",
            medium_csv="/dev/null/medium.csv",
            db_path=None,
            limit=kwargs.pop("limit", 50),
            **kwargs,
        )


def _all_supported_claim_text(memo: dict[str, Any]) -> str:
    return " | ".join(memo["supported_claims"]).lower()


def _all_headline_and_next_target(memo: dict[str, Any]) -> str:
    return f"{memo['headline']} | {memo['next_target']}".lower()


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    def test_returns_dict_with_required_keys(self) -> None:
        memo = _build_memo(_five_event_summary())
        self.assertEqual(set(memo.keys()), set(_REQUIRED_KEYS))

    def test_evidence_state_has_required_subkeys(self) -> None:
        memo = _build_memo(_five_event_summary())
        state = memo["evidence_state"]
        for k in (
            "repaired_clean_event_count",
            "repaired_clean_event_ids",
            "records_count",
            "fdr_significant_count",
            "validated_raw_only_event_ids",
            "validated_raw_only_count",
            "by_event_verdict",
        ):
            self.assertIn(k, state)

    def test_source_summary_passes_through_upstream_dict(self) -> None:
        upstream = _five_event_summary()
        memo = _build_memo(upstream)
        # The full upstream summary is preserved for audit drill-in.
        self.assertEqual(memo["source_summary"], upstream)


# ---------------------------------------------------------------------------
# Five-event evidence state — the memo MUST state these facts.
# ---------------------------------------------------------------------------


class TestFiveEventEvidence(unittest.TestCase):
    def test_states_five_repaired_clean_events(self) -> None:
        memo = _build_memo(_five_event_summary())
        self.assertEqual(
            memo["evidence_state"]["repaired_clean_event_count"], 5,
        )
        self.assertEqual(
            memo["evidence_state"]["repaired_clean_event_ids"],
            [30, 40, 46, 60, 73],
        )

    def test_states_fifteen_records(self) -> None:
        memo = _build_memo(_five_event_summary())
        self.assertEqual(memo["evidence_state"]["records_count"], 15)

    def test_states_zero_fdr_significant(self) -> None:
        memo = _build_memo(_five_event_summary())
        self.assertEqual(
            memo["evidence_state"]["fdr_significant_count"], 0,
        )

    def test_event_73_validated_raw_only(self) -> None:
        memo = _build_memo(_five_event_summary())
        state = memo["evidence_state"]
        self.assertIn(73, state["validated_raw_only_event_ids"])
        self.assertEqual(state["by_event_verdict"]["73"],
                         "validated_raw_only")
        self.assertEqual(state["validated_raw_only_count"], 1)

    def test_evidence_is_underpowered(self) -> None:
        memo = _build_memo(_five_event_summary())
        self.assertTrue(memo["underpowered"])

    def test_headline_states_underpowered_and_core_numbers(self) -> None:
        memo = _build_memo(_five_event_summary())
        headline = memo["headline"].lower()
        self.assertIn("underpowered", headline)
        self.assertIn("5", headline)
        self.assertIn("15", headline)
        self.assertIn("0", headline)

    def test_supported_claims_cite_event_73(self) -> None:
        memo = _build_memo(_five_event_summary())
        text = _all_supported_claim_text(memo)
        self.assertIn("73", text)
        self.assertIn("validated_raw_only", text)

    def test_supported_claims_cite_zero_fdr_aggregate(self) -> None:
        memo = _build_memo(_five_event_summary())
        text = _all_supported_claim_text(memo)
        self.assertIn("0", text)
        self.assertIn("fdr", text)


# ---------------------------------------------------------------------------
# Next target — must say "expand to 10-15".
# ---------------------------------------------------------------------------


class TestNextTarget(unittest.TestCase):
    def test_next_target_says_expand_to_10_to_15(self) -> None:
        memo = _build_memo(_five_event_summary())
        target = memo["next_target"].lower()
        self.assertIn("expand", target)
        self.assertIn("10", target)
        self.assertIn("15", target)

    def test_next_target_mentions_current_cohort_size(self) -> None:
        memo = _build_memo(_five_event_summary())
        # Surfacing "currently 5" reinforces the gap to the goal.
        self.assertIn("5", memo["next_target"])

    def test_next_target_not_an_aggregate_claim(self) -> None:
        memo = _build_memo(_five_event_summary())
        target = memo["next_target"].lower()
        # The next target is operational guidance, not a statistical
        # claim — it must NOT slip into any of the same forbidden
        # phrases the supported_claims and headline are screened for.
        for forbidden in _FORBIDDEN_IN_SUPPORTED_CLAIMS:
            self.assertNotIn(
                forbidden, target,
                f"next_target must NEVER assert {forbidden!r}; "
                f"text: {memo['next_target']!r}",
            )


# ---------------------------------------------------------------------------
# Conservative language enforcement.
# ---------------------------------------------------------------------------


class TestConservativeLanguage(unittest.TestCase):
    def test_supported_claims_avoid_forbidden_phrases(self) -> None:
        memo = _build_memo(_five_event_summary())
        for claim in memo["supported_claims"]:
            lower = claim.lower()
            for forbidden in _FORBIDDEN_IN_SUPPORTED_CLAIMS:
                self.assertNotIn(
                    forbidden, lower,
                    f"supported_claims must NEVER assert {forbidden!r}; "
                    f"offending claim: {claim!r}",
                )

    def test_headline_avoids_forbidden_phrases(self) -> None:
        memo = _build_memo(_five_event_summary())
        lower = memo["headline"].lower()
        for forbidden in _FORBIDDEN_IN_SUPPORTED_CLAIMS:
            self.assertNotIn(forbidden, lower)

    def test_unsupported_claims_disclaim_proof_and_predictive_edge(
        self,
    ) -> None:
        # The unsupported_claims list MUST explicitly negate "proof"
        # and "predictive" so a reader sees the framing called out.
        memo = _build_memo(_five_event_summary())
        joined = " | ".join(memo["unsupported_claims"]).lower()
        self.assertIn("causal", joined)
        self.assertIn("predictive", joined)
        self.assertIn("proof", joined)


# ---------------------------------------------------------------------------
# Underpowered flag.
# ---------------------------------------------------------------------------


class TestUnderpoweredFlag(unittest.TestCase):
    def test_below_target_min_is_underpowered(self) -> None:
        # 5 events < target_min_events=10 ⇒ underpowered.
        memo = _build_memo(_five_event_summary())
        self.assertTrue(memo["underpowered"])

    def test_zero_events_is_underpowered(self) -> None:
        memo = _build_memo(_summary_payload())
        self.assertTrue(memo["underpowered"])

    def test_at_target_with_no_fdr_is_still_underpowered(self) -> None:
        # 12 events but 0 FDR-significant aggregate ⇒ still underpowered
        # for an aggregate claim.
        ids = list(range(1, 13))
        payload = _summary_payload(
            repaired_clean_event_ids=ids,
            records_count=36, significant_count=0,
            by_event_verdict={str(i): "insufficient" for i in ids},
        )
        memo = _build_memo(payload)
        self.assertTrue(memo["underpowered"])

    def test_at_target_with_fdr_clearance_is_not_underpowered(self) -> None:
        ids = list(range(1, 13))
        payload = _summary_payload(
            repaired_clean_event_ids=ids,
            records_count=36, significant_count=4,
            by_event_verdict={str(i): "validated_raw_only" for i in ids},
        )
        memo = _build_memo(payload)
        self.assertFalse(memo["underpowered"])


# ---------------------------------------------------------------------------
# Empty cohort.
# ---------------------------------------------------------------------------


class TestEmptyCohort(unittest.TestCase):
    def test_empty_cohort_does_not_crash(self) -> None:
        memo = _build_memo(_summary_payload())
        state = memo["evidence_state"]
        self.assertEqual(state["repaired_clean_event_count"], 0)
        self.assertEqual(state["records_count"], 0)
        self.assertEqual(state["fdr_significant_count"], 0)
        self.assertEqual(state["validated_raw_only_event_ids"], [])
        self.assertEqual(state["validated_raw_only_count"], 0)
        self.assertEqual(state["by_event_verdict"], {})
        self.assertTrue(memo["underpowered"])


# ---------------------------------------------------------------------------
# Limitations passthrough.
# ---------------------------------------------------------------------------


class TestLimitations(unittest.TestCase):
    def test_limitations_passthrough_from_summary(self) -> None:
        memo = _build_memo(_summary_payload(
            limitations=["operator note: small pilot",
                         "validation runner error: stub"],
        ))
        self.assertIn(
            "operator note: small pilot", memo["limitations"],
        )
        self.assertIn(
            "validation runner error: stub", memo["limitations"],
        )


# ---------------------------------------------------------------------------
# Patchable seam + read-only enforcement.
# ---------------------------------------------------------------------------


class TestSeam(unittest.TestCase):
    def test_seam_exists_and_is_callable(self) -> None:
        self.assertTrue(
            callable(getattr(memo_cli, "_run_validation_summary")),
        )

    def test_seam_receives_all_args(self) -> None:
        captured: dict[str, Any] = {}

        def fake(*, backup_path, high_priority_csv, medium_csv,
                 mechanism_family_csv=None, db_path, limit, alpha):
            captured["backup_path"]          = backup_path
            captured["high_priority_csv"]    = high_priority_csv
            captured["medium_csv"]           = medium_csv
            captured["mechanism_family_csv"] = mechanism_family_csv
            captured["db_path"]              = db_path
            captured["limit"]                = limit
            captured["alpha"]                = alpha
            return _summary_payload()

        with patch.object(
            memo_cli, "_run_validation_summary", side_effect=fake,
        ):
            memo_cli.build_repaired_cohort_demo_memo(
                backup_path="/x/backup.db",
                high_priority_csv="/x/high.csv",
                medium_csv="/x/medium.csv",
                mechanism_family_csv="/x/family.csv",
                db_path="/x/live.db",
                limit=17,
                alpha=0.01,
            )

        self.assertEqual(captured["backup_path"],          "/x/backup.db")
        self.assertEqual(captured["high_priority_csv"],    "/x/high.csv")
        self.assertEqual(captured["medium_csv"],           "/x/medium.csv")
        self.assertEqual(captured["mechanism_family_csv"], "/x/family.csv")
        self.assertEqual(captured["db_path"],              "/x/live.db")
        self.assertEqual(captured["limit"],                17)
        self.assertEqual(captured["alpha"],                0.01)

    def test_mechanism_family_csv_defaults_to_none_when_omitted(
        self,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake(*, backup_path, high_priority_csv, medium_csv,
                 mechanism_family_csv=None, db_path, limit, alpha):
            captured["mechanism_family_csv"] = mechanism_family_csv
            return _summary_payload()

        with patch.object(
            memo_cli, "_run_validation_summary", side_effect=fake,
        ):
            memo_cli.build_repaired_cohort_demo_memo(
                backup_path="/x/backup.db",
                high_priority_csv="/x/high.csv",
                medium_csv="/x/medium.csv",
                db_path=None,
                limit=10,
            )
        self.assertIsNone(captured["mechanism_family_csv"])


# ---------------------------------------------------------------------------
# CLI plumbing — `--json` and `--text` MUST both work for verification.
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_json_emits_parseable_json(self) -> None:
        out = StringIO()
        with _patch_seam(_five_event_summary()):
            rc = memo_cli.main([
                "--json",
                "--backup-path", "/x/backup.db",
                "--high-priority-csv", "/x/high.csv",
                "--medium-csv", "/x/medium.csv",
                "--limit", "50",
            ], out=out)
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(
            parsed["evidence_state"]["repaired_clean_event_count"], 5,
        )
        self.assertEqual(
            parsed["evidence_state"]["records_count"], 15,
        )
        self.assertEqual(
            parsed["evidence_state"]["fdr_significant_count"], 0,
        )
        self.assertIn(
            73, parsed["evidence_state"]["validated_raw_only_event_ids"],
        )
        self.assertTrue(parsed["underpowered"])

    def test_cli_text_runs_and_surfaces_facts(self) -> None:
        out = StringIO()
        with _patch_seam(_five_event_summary()):
            rc = memo_cli.main(["--text", "--limit", "50"], out=out)
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertTrue(text)
        self.assertIn("Repaired Cohort Demo Evidence Memo", text)
        # The 5-event facts surface in the text rendering.
        self.assertIn("5", text)
        self.assertIn("15", text)
        self.assertIn("73", text)
        self.assertIn("underpowered", text.lower())
        self.assertIn("expand", text.lower())

    def test_cli_default_renders_text(self) -> None:
        out = StringIO()
        with _patch_seam(_five_event_summary()):
            rc = memo_cli.main([], out=out)
        self.assertEqual(rc, 0)
        # No --json flag → text rendering, NOT a JSON object.
        self.assertNotEqual(out.getvalue().lstrip()[:1], "{")

    def test_cli_json_and_text_are_mutually_exclusive(self) -> None:
        with _patch_seam(_five_event_summary()):
            with self.assertRaises(SystemExit):
                memo_cli.main(["--json", "--text"], out=StringIO())


if __name__ == "__main__":
    unittest.main()
