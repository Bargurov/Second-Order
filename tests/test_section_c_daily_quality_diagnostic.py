"""Tests for ``scripts/section_c_daily_quality_diagnostic.py``.

Pin the contract:

* Read-only diagnostic over the local ``news_inbox.json`` (or any
  file supplied via ``--input``).  No DB writes, no provider, no
  ``yfinance``, no LLM, no FastAPI surface.  The inbox file is
  opened in read mode only — byte identity is preserved.
* Output dict has EXACTLY these 12 keys::

    ok, candidates_checked, accepted_like_candidates,
    junk_headlines, raw_legal_text_cases, off_topic_cases,
    vague_cases, duplicate_cases, missing_mechanism_cases,
    recommended_daily_filter_rules, warnings, errors

* Each category list contains candidate dicts with EXACTLY these
  9 fields::

    event_id, headline, event_date, primary_ticker,
    mechanism_family, market_relevance_score, diagnostic_tags,
    inclusion_reason, exclusion_reason

* A candidate is placed in the FIRST category that fits, in this
  priority order:
    junk → raw_legal_text → off_topic → vague → duplicate →
    missing_mechanism → accepted_like.
* The diagnostic describes shape only; it never claims the filter
  is broken, never asserts causality, and never calls a record
  "validated".  Conservative wording.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import section_c_daily_quality_diagnostic as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "candidates_checked",
    "accepted_like_candidates",
    "junk_headlines",
    "raw_legal_text_cases",
    "off_topic_cases",
    "vague_cases",
    "duplicate_cases",
    "missing_mechanism_cases",
    "recommended_daily_filter_rules",
    "warnings",
    "errors",
)


_CANDIDATE_FIELDS = (
    "event_id",
    "headline",
    "event_date",
    "primary_ticker",
    "mechanism_family",
    "market_relevance_score",
    "diagnostic_tags",
    "inclusion_reason",
    "exclusion_reason",
)


_CATEGORY_LIST_KEYS = (
    "accepted_like_candidates",
    "junk_headlines",
    "raw_legal_text_cases",
    "off_topic_cases",
    "vague_cases",
    "duplicate_cases",
    "missing_mechanism_cases",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "validated",
    "guaranteed",
    "automatically",
    "alpha generated",
    "correct ticker",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _entry(
    title: str,
    *,
    published_at: str = "2026-04-08T10:00:00",
    source: str = "local",
    url: str = "",
    **extra: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title":        title,
        "source":       source,
        "published_at": published_at,
        "url":          url,
    }
    base.update(extra)
    return base


def _write_inbox(entries: list[dict[str, Any]]) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"section_c_inbox_{uuid.uuid4().hex}.json",
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh)
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# A canonical relevant headline (clears is_relevant).
_GOOD_HEADLINE = (
    "OPEC members agree to extend voluntary oil output cuts through "
    "next quarter"
)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema(unittest.TestCase):
    def test_required_keys_on_empty_inbox(self) -> None:
        path = _write_inbox([])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
            self.assertTrue(report["ok"])
            self.assertEqual(report["candidates_checked"], 0)
            for key in _CATEGORY_LIST_KEYS:
                self.assertEqual(report[key], [],
                                 f"{key!r} must be empty list on empty inbox")
        finally:
            os.unlink(path)

    def test_each_candidate_has_required_fields(self) -> None:
        path = _write_inbox([_entry(_GOOD_HEADLINE)])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            # Walk every category list — every candidate must carry the
            # 9 fields regardless of which bucket it lands in.
            for key in _CATEGORY_LIST_KEYS:
                for c in report[key]:
                    self.assertEqual(
                        set(c.keys()), set(_CANDIDATE_FIELDS),
                        f"candidate in {key!r} has unexpected fields: "
                        f"{sorted(c.keys())}",
                    )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Default inbox source
# ---------------------------------------------------------------------------


class TestDefaultInboxSource(unittest.TestCase):
    def test_default_inbox_path_resolves(self) -> None:
        # No --input passed — defaults to news_inbox.json.  We don't
        # care about the actual content, only that the resolver returns
        # SOME non-None path.
        self.assertIsNotNone(cli._default_input_path())

    def test_missing_inbox_path_returns_failure(self) -> None:
        report = cli.run_section_c_daily_quality_diagnostic(
            input_path="/nonexistent/news_inbox.json",
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["candidates_checked"], 0)
        self.assertTrue(any(
            "does not exist" in e.lower() or "not found" in e.lower()
            for e in report["errors"]
        ))

    def test_malformed_inbox_returns_failure(self) -> None:
        path = os.path.join(
            tempfile.gettempdir(),
            f"section_c_bad_{uuid.uuid4().hex}.json",
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not-json")
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                "json" in e.lower() for e in report["errors"]
            ))
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Categorisation
# ---------------------------------------------------------------------------


class TestCategorisation(unittest.TestCase):
    def test_relevant_headline_lands_in_accepted_like(self) -> None:
        path = _write_inbox([
            _entry(_GOOD_HEADLINE, mechanism_family="supply_shock"),
        ])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(len(report["accepted_like_candidates"]), 1)
            self.assertEqual(len(report["junk_headlines"]), 0)
            self.assertEqual(len(report["off_topic_cases"]), 0)
            c = report["accepted_like_candidates"][0]
            self.assertIn(c["inclusion_reason"], (None, "passes_filters")) \
                if c["inclusion_reason"] is None \
                else self.assertEqual(c["inclusion_reason"], "passes_filters")
            self.assertIsNone(c["exclusion_reason"])
        finally:
            os.unlink(path)

    def test_empty_headline_lands_in_junk(self) -> None:
        path = _write_inbox([
            _entry(""),
            _entry("   "),
        ])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(len(report["junk_headlines"]), 2)
            for c in report["junk_headlines"]:
                self.assertIn("junk", c["diagnostic_tags"])
                self.assertIsNotNone(c["exclusion_reason"])
        finally:
            os.unlink(path)

    def test_single_token_headline_lands_in_junk(self) -> None:
        path = _write_inbox([_entry("Breaking")])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(len(report["junk_headlines"]), 1)
        finally:
            os.unlink(path)

    def test_raw_legal_text_lands_in_legal_bucket(self) -> None:
        # Multi-token legal docket / case-citation language.
        path = _write_inbox([
            _entry(
                "Smith v. Jones LLC, Case No. 2026-CV-12345, "
                "petitioner files subpoena per docket entry no. 17."
            ),
            _entry(
                "In re: Acme Holdings Inc., respondent's reply to "
                "indictment filed in case no. 2026-CR-89."
            ),
        ])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(len(report["raw_legal_text_cases"]), 2)
            for c in report["raw_legal_text_cases"]:
                self.assertIn("raw_legal_text", c["diagnostic_tags"])
        finally:
            os.unlink(path)

    def test_off_topic_headline_lands_in_off_topic(self) -> None:
        # Lifestyle/sports — passes news_relevance.is_relevant() as
        # False, has no economic channel.
        path = _write_inbox([
            _entry("Local soccer team wins regional cup against rivals"),
            _entry("Cooking show debuts new season featuring chef interviews"),
        ])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(len(report["off_topic_cases"]), 2)
            for c in report["off_topic_cases"]:
                self.assertIn("off_topic", c["diagnostic_tags"])
        finally:
            os.unlink(path)

    def test_vague_short_headline_lands_in_vague(self) -> None:
        path = _write_inbox([
            _entry("Market update"),
            _entry("Today's top stories"),
            _entry("Market wrap"),
        ])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertGreaterEqual(len(report["vague_cases"]), 1)
            for c in report["vague_cases"]:
                self.assertIn("vague", c["diagnostic_tags"])
        finally:
            os.unlink(path)

    def test_duplicate_headlines_land_in_duplicates(self) -> None:
        path = _write_inbox([
            _entry(_GOOD_HEADLINE),
            _entry(_GOOD_HEADLINE),    # exact duplicate
            _entry(_GOOD_HEADLINE.upper()),  # case-only duplicate
        ])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(len(report["accepted_like_candidates"]), 1)
            self.assertEqual(len(report["duplicate_cases"]), 2)
            for c in report["duplicate_cases"]:
                self.assertIn("duplicate", c["diagnostic_tags"])
        finally:
            os.unlink(path)

    def test_missing_mechanism_when_explicit_field_is_none(self) -> None:
        # An inbox entry that DOES carry a mechanism_family field but
        # the value is null/empty must land in missing_mechanism — the
        # entry presents itself as classified, but its label is empty.
        path = _write_inbox([
            _entry(_GOOD_HEADLINE, mechanism_family="none"),
            _entry(_GOOD_HEADLINE + " (rev)", mechanism_family=""),
            _entry(_GOOD_HEADLINE + " (rev2)", mechanism_family=None),
        ])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(
                len(report["missing_mechanism_cases"]), 3,
                report["missing_mechanism_cases"],
            )
            for c in report["missing_mechanism_cases"]:
                self.assertIn(
                    "missing_mechanism", c["diagnostic_tags"],
                )
        finally:
            os.unlink(path)

    def test_inbox_without_mechanism_field_emits_warning(self) -> None:
        # When NO entries carry a mechanism_family field at all, the
        # diagnostic must surface a warning instead of false-flagging
        # every candidate as missing_mechanism.  (news_inbox.json
        # doesn't carry this field in production.)
        path = _write_inbox([_entry(_GOOD_HEADLINE)])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(len(report["missing_mechanism_cases"]), 0)
            joined = " | ".join(report["warnings"]).lower()
            self.assertIn("mechanism_family", joined)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Priority order
# ---------------------------------------------------------------------------


class TestPriorityOrder(unittest.TestCase):
    def test_junk_beats_off_topic(self) -> None:
        # Empty headline AND no economic channel — junk wins.
        path = _write_inbox([_entry("")])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(len(report["junk_headlines"]), 1)
            self.assertEqual(len(report["off_topic_cases"]), 0)
        finally:
            os.unlink(path)

    def test_legal_beats_off_topic(self) -> None:
        # Pure legal text with no economic keyword — legal bucket wins
        # over off-topic.
        path = _write_inbox([
            _entry(
                "Smith v. Jones LLC, Case No. 2026-CV-12345, "
                "petitioner files reply per docket entry no. 17."
            ),
        ])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(len(report["raw_legal_text_cases"]), 1)
            self.assertEqual(len(report["off_topic_cases"]), 0)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Market relevance score
# ---------------------------------------------------------------------------


class TestMarketRelevanceScore(unittest.TestCase):
    def test_score_in_unit_interval(self) -> None:
        path = _write_inbox([
            _entry(_GOOD_HEADLINE),
            _entry(""),
            _entry("Local festival opens this weekend"),
        ])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            for key in _CATEGORY_LIST_KEYS:
                for c in report[key]:
                    self.assertIsInstance(c["market_relevance_score"], float)
                    self.assertGreaterEqual(c["market_relevance_score"], 0.0)
                    self.assertLessEqual(c["market_relevance_score"], 1.0)
        finally:
            os.unlink(path)

    def test_junk_headline_scores_zero(self) -> None:
        path = _write_inbox([_entry("")])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(len(report["junk_headlines"]), 1)
            self.assertEqual(
                report["junk_headlines"][0]["market_relevance_score"], 0.0,
            )
        finally:
            os.unlink(path)

    def test_relevant_headline_scores_above_zero(self) -> None:
        path = _write_inbox([_entry(_GOOD_HEADLINE)])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(len(report["accepted_like_candidates"]), 1)
            self.assertGreater(
                report["accepted_like_candidates"][0]["market_relevance_score"],
                0.0,
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Recommended daily filter rules
# ---------------------------------------------------------------------------


class TestRecommendedRules(unittest.TestCase):
    def test_rules_are_emitted_only_when_count_above_threshold(self) -> None:
        # A single vague headline alone should NOT trigger a recommended
        # rule (signal too thin).  Two or more should.
        path = _write_inbox([_entry("Market update")])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertEqual(report["recommended_daily_filter_rules"], [])
        finally:
            os.unlink(path)

    def test_rules_emitted_when_pattern_repeats(self) -> None:
        path = _write_inbox([
            _entry("Market update"),
            _entry("Market wrap"),
            _entry("Today's top stories"),
        ])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            self.assertGreaterEqual(
                len(report["recommended_daily_filter_rules"]), 1,
            )
            # Conservative language pin: rules must be descriptive,
            # never imperative claims of broken-ness.
            joined = " ".join(
                r if isinstance(r, str) else r.get("note", "")
                for r in report["recommended_daily_filter_rules"]
            ).lower()
            for forbidden in ("broken", "always fails", "never works"):
                self.assertNotIn(forbidden, joined)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnly(unittest.TestCase):
    def test_inbox_byte_identity_preserved(self) -> None:
        path = _write_inbox([
            _entry(_GOOD_HEADLINE),
            _entry("Local festival opens this weekend"),
        ])
        try:
            before = _sha256(path)
            cli.run_section_c_daily_quality_diagnostic(input_path=path)
            after = _sha256(path)
            self.assertEqual(
                before, after,
                "diagnostic must not mutate the inbox file",
            )
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _build(self) -> dict[str, Any]:
        path = _write_inbox([
            _entry(_GOOD_HEADLINE),
            _entry(""),
            _entry("Local festival opens this weekend"),
            _entry("Market update"),
            _entry("Market wrap"),
            _entry("Today's top stories"),
            _entry(
                "Smith v. Jones LLC, Case No. 2026-CV-12345, "
                "petitioner files reply per docket entry no. 17."
            ),
        ])
        try:
            return cli.run_section_c_daily_quality_diagnostic(input_path=path)
        finally:
            os.unlink(path)

    def test_no_banned_words_in_json_render(self) -> None:
        report = self._build()
        blob = cli._render_json(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(
                term, blob,
                f"banned token {term!r} in JSON render",
            )

    def test_no_banned_words_in_text_render(self) -> None:
        report = self._build()
        text = cli._render_text(report).lower()
        for term in _BANNED_WORDS:
            self.assertNotIn(
                term, text,
                f"banned token {term!r} in text render",
            )


# ---------------------------------------------------------------------------
# No-paid-surface import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_provider_attrs(self) -> None:
        for attr in ("yfinance", "anthropic", "openai", "fastapi"):
            self.assertFalse(
                hasattr(cli, attr),
                f"diagnostic must not bind {attr} as a module attr",
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_json_emits_required_keys(self) -> None:
        path = _write_inbox([_entry(_GOOD_HEADLINE)])
        try:
            rc, output = self._run(["--input", path, "--json"])
            parsed = json.loads(output)
            self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
            self.assertTrue(parsed["ok"])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(path)

    def test_text_render_does_not_crash(self) -> None:
        path = _write_inbox([_entry(_GOOD_HEADLINE)])
        try:
            rc, output = self._run(["--input", path])
            self.assertEqual(rc, 0)
            self.assertIn("section c", output.lower())
        finally:
            os.unlink(path)

    def test_main_returns_nonzero_when_input_missing(self) -> None:
        rc, output = self._run([
            "--input", "/nonexistent/inbox.json", "--json",
        ])
        self.assertEqual(rc, 1)
        parsed = json.loads(output)
        self.assertFalse(parsed["ok"])


# ---------------------------------------------------------------------------
# Live inbox sanity (no assertion, smoke only)
# ---------------------------------------------------------------------------


class TestLiveInboxSmoke(unittest.TestCase):
    def test_runs_against_live_inbox_without_crashing(self) -> None:
        live = Path("news_inbox.json")
        if not live.exists():
            self.skipTest("no live news_inbox.json present")
        report = cli.run_section_c_daily_quality_diagnostic(
            input_path=str(live),
        )
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        # We don't assert ok=True here — the inbox may be empty or carry
        # entries that legitimately bucket as off-topic.  We do assert
        # the envelope shape and that errors is a list.
        self.assertIsInstance(report["errors"], list)


# ---------------------------------------------------------------------------
# Optional --artifact-dir audit — adds per-candidate artifact-presence
# fields without altering default behavior.
# ---------------------------------------------------------------------------


def _write_artifact(
    artifact_dir: Path, candidate_id: str, body: dict[str, Any],
) -> Path:
    """Write one analyzed_event_artifact_<candidate_id>.json under
    ``artifact_dir`` for the tests below.  The file lives in pytest's
    tmp_path / a tempfile dir — never under live ``artifacts/``."""
    path = artifact_dir / f"analyzed_event_artifact_{candidate_id}.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _flatten_candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in _CATEGORY_LIST_KEYS:
        out.extend(report.get(key) or [])
    return out


def _candidate_with_id(report: dict[str, Any], cid: str) -> dict[str, Any]:
    for c in _flatten_candidates(report):
        if c.get("candidate_id") == cid:
            return c
    raise AssertionError(
        f"no candidate with candidate_id={cid!r} found in report; "
        f"available={[c.get('candidate_id') for c in _flatten_candidates(report)]}",
    )


class TestArtifactAuditDefaultIsNoop(unittest.TestCase):
    """Default behavior (no --artifact-dir) must remain byte-compatible."""

    def test_no_artifact_dir_means_no_audit_fields(self) -> None:
        path = _write_inbox([_entry(_GOOD_HEADLINE, candidate_id="abc123")])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            for c in _flatten_candidates(report):
                # 9-field invariant must hold — no artifact-audit
                # fields when artifact_dir is not passed.
                self.assertEqual(
                    set(c.keys()), set(_CANDIDATE_FIELDS),
                    f"default candidate dict gained an artifact-audit "
                    f"field; got keys={sorted(c.keys())}",
                )
        finally:
            os.unlink(path)

    def test_no_artifact_dir_does_not_add_envelope_keys(self) -> None:
        path = _write_inbox([_entry(_GOOD_HEADLINE)])
        try:
            report = cli.run_section_c_daily_quality_diagnostic(
                input_path=path,
            )
            # Strict envelope-key invariant — no new top-level keys
            # appear when artifact_dir is not passed.
            self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS))
        finally:
            os.unlink(path)


class TestArtifactAuditComplete(unittest.TestCase):
    """A row whose artifact is present and complete is reported as such."""

    def test_present_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            cid = "fslr-ira-001"
            _write_artifact(
                artifact_dir, cid,
                {
                    "artifact_type":    "analyzed_event_artifact",
                    "candidate_id":     cid,
                    "headline":         _GOOD_HEADLINE,
                    "event_date":       "2022-07-28",
                    "mechanism_family": "policy_driven_direct_beneficiary",
                    "primary_ticker":   "FSLR",
                    "benchmark_ticker": "SPY",
                },
            )
            inbox_path = _write_inbox(
                [_entry(_GOOD_HEADLINE, candidate_id=cid)],
            )
            try:
                report = cli.run_section_c_daily_quality_diagnostic(
                    input_path=inbox_path,
                    artifact_dir=str(artifact_dir),
                )
                cand = _candidate_with_id(report, cid)
                self.assertEqual(cand["candidate_id"], cid)
                self.assertTrue(cand["artifact_present"])
                self.assertTrue(cand["artifact_fields_complete"])
                self.assertEqual(
                    cand["artifact_filename"],
                    f"analyzed_event_artifact_{cid}.json",
                )
                # Conditional fields absent on the happy path.
                self.assertNotIn("artifact_missing_reason", cand)
                self.assertNotIn("artifact_incomplete_fields", cand)
            finally:
                os.unlink(inbox_path)


class TestArtifactAuditMissing(unittest.TestCase):
    """A row with candidate_id but no on-disk artifact reports missing."""

    def test_missing_artifact_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            cid = "no-artifact-on-disk-002"
            inbox_path = _write_inbox(
                [_entry(_GOOD_HEADLINE, candidate_id=cid)],
            )
            try:
                report = cli.run_section_c_daily_quality_diagnostic(
                    input_path=inbox_path,
                    artifact_dir=str(artifact_dir),
                )
                cand = _candidate_with_id(report, cid)
                self.assertEqual(cand["candidate_id"], cid)
                self.assertFalse(cand["artifact_present"])
                self.assertFalse(cand["artifact_fields_complete"])
                reason = cand.get("artifact_missing_reason", "")
                self.assertTrue(
                    isinstance(reason, str) and reason,
                    f"expected non-empty artifact_missing_reason; got {reason!r}",
                )
                # Filename + incomplete-fields keys absent when not on disk.
                self.assertNotIn("artifact_filename", cand)
                self.assertNotIn("artifact_incomplete_fields", cand)
            finally:
                os.unlink(inbox_path)


class TestArtifactAuditIncomplete(unittest.TestCase):
    """A present-but-incomplete artifact reports the missing field(s)."""

    def test_missing_required_field_listed_in_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            cid = "incomplete-003"
            _write_artifact(
                artifact_dir, cid,
                {
                    "artifact_type":    "analyzed_event_artifact",
                    "candidate_id":     cid,
                    "headline":         _GOOD_HEADLINE,
                    "event_date":       "2022-07-28",
                    # mechanism_family deliberately missing
                    "primary_ticker":   "FSLR",
                    "benchmark_ticker": "SPY",
                },
            )
            inbox_path = _write_inbox(
                [_entry(_GOOD_HEADLINE, candidate_id=cid)],
            )
            try:
                report = cli.run_section_c_daily_quality_diagnostic(
                    input_path=inbox_path,
                    artifact_dir=str(artifact_dir),
                )
                cand = _candidate_with_id(report, cid)
                self.assertTrue(cand["artifact_present"])
                self.assertFalse(cand["artifact_fields_complete"])
                self.assertIn("artifact_filename", cand)
                incomplete = cand.get("artifact_incomplete_fields")
                self.assertEqual(incomplete, ["mechanism_family"])
                # missing_reason absent when the artifact is present.
                self.assertNotIn("artifact_missing_reason", cand)
            finally:
                os.unlink(inbox_path)

    def test_mechanism_family_none_sentinel_treated_as_incomplete(self) -> None:
        # The gate treats mechanism_family == "none" as missing; the
        # diagnostic mirrors that.
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            cid = "none-sentinel-004"
            _write_artifact(
                artifact_dir, cid,
                {
                    "artifact_type":    "analyzed_event_artifact",
                    "candidate_id":     cid,
                    "headline":         _GOOD_HEADLINE,
                    "event_date":       "2022-07-28",
                    "mechanism_family": "none",
                    "primary_ticker":   "FSLR",
                    "benchmark_ticker": "SPY",
                },
            )
            inbox_path = _write_inbox(
                [_entry(_GOOD_HEADLINE, candidate_id=cid)],
            )
            try:
                report = cli.run_section_c_daily_quality_diagnostic(
                    input_path=inbox_path,
                    artifact_dir=str(artifact_dir),
                )
                cand = _candidate_with_id(report, cid)
                self.assertTrue(cand["artifact_present"])
                self.assertFalse(cand["artifact_fields_complete"])
                self.assertEqual(
                    cand.get("artifact_incomplete_fields"),
                    ["mechanism_family"],
                )
            finally:
                os.unlink(inbox_path)


class TestArtifactAuditNoCandidateId(unittest.TestCase):
    """A row without a candidate_id can't resolve an artifact path."""

    def test_no_candidate_id_reports_missing_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            inbox_path = _write_inbox(
                # _entry helper doesn't set candidate_id by default.
                [_entry(_GOOD_HEADLINE)],
            )
            try:
                report = cli.run_section_c_daily_quality_diagnostic(
                    input_path=inbox_path,
                    artifact_dir=str(artifact_dir),
                )
                # Flatten and grab the single candidate — there's only
                # one entry in the inbox.
                cands = _flatten_candidates(report)
                self.assertEqual(len(cands), 1)
                cand = cands[0]
                self.assertIsNone(cand["candidate_id"])
                self.assertFalse(cand["artifact_present"])
                self.assertFalse(cand["artifact_fields_complete"])
                reason = cand.get("artifact_missing_reason", "")
                self.assertIn("candidate_id", reason)
                self.assertNotIn("artifact_filename", cand)
                self.assertNotIn("artifact_incomplete_fields", cand)
            finally:
                os.unlink(inbox_path)

    def test_blank_candidate_id_string_treated_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            inbox_path = _write_inbox(
                [_entry(_GOOD_HEADLINE, candidate_id="   ")],
            )
            try:
                report = cli.run_section_c_daily_quality_diagnostic(
                    input_path=inbox_path,
                    artifact_dir=str(artifact_dir),
                )
                cand = _flatten_candidates(report)[0]
                self.assertIsNone(cand["candidate_id"])
                self.assertFalse(cand["artifact_present"])
                self.assertIn(
                    "candidate_id",
                    cand.get("artifact_missing_reason", ""),
                )
            finally:
                os.unlink(inbox_path)


class TestArtifactAuditMultipleRows(unittest.TestCase):
    """Each candidate is audited independently and shares dict identity
    across category lists, so the in-place audit propagates cleanly."""

    def test_three_rows_independent_audits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            # Row A: full artifact present + complete
            cid_a = "row-a-complete"
            _write_artifact(
                artifact_dir, cid_a,
                {
                    "artifact_type":    "analyzed_event_artifact",
                    "candidate_id":     cid_a,
                    "headline":         _GOOD_HEADLINE,
                    "event_date":       "2022-07-28",
                    "mechanism_family": "supply_shock",
                    "primary_ticker":   "XOM",
                    "benchmark_ticker": "XLE",
                },
            )
            # Row B: artifact present but missing primary_ticker
            cid_b = "row-b-incomplete"
            _write_artifact(
                artifact_dir, cid_b,
                {
                    "artifact_type":    "analyzed_event_artifact",
                    "candidate_id":     cid_b,
                    "headline":         _GOOD_HEADLINE,
                    "event_date":       "2022-07-28",
                    "mechanism_family": "supply_shock",
                    # primary_ticker absent
                    "benchmark_ticker": "XLE",
                },
            )
            # Row C: no artifact file on disk
            cid_c = "row-c-missing"
            inbox_path = _write_inbox([
                _entry(_GOOD_HEADLINE, candidate_id=cid_a),
                _entry(_GOOD_HEADLINE + " (variant B)", candidate_id=cid_b),
                _entry(_GOOD_HEADLINE + " (variant C)", candidate_id=cid_c),
            ])
            try:
                report = cli.run_section_c_daily_quality_diagnostic(
                    input_path=inbox_path,
                    artifact_dir=str(artifact_dir),
                )
                a = _candidate_with_id(report, cid_a)
                b = _candidate_with_id(report, cid_b)
                c = _candidate_with_id(report, cid_c)
                # A: present + complete
                self.assertTrue(a["artifact_present"])
                self.assertTrue(a["artifact_fields_complete"])
                # B: present but incomplete (primary_ticker)
                self.assertTrue(b["artifact_present"])
                self.assertFalse(b["artifact_fields_complete"])
                self.assertEqual(
                    b.get("artifact_incomplete_fields"),
                    ["primary_ticker"],
                )
                # C: missing file
                self.assertFalse(c["artifact_present"])
                self.assertFalse(c["artifact_fields_complete"])
                self.assertIn(
                    "no analyzed_event_artifact",
                    c.get("artifact_missing_reason", ""),
                )
            finally:
                os.unlink(inbox_path)


class TestArtifactAuditDoesNotWriteFiles(unittest.TestCase):
    """The audit is read-only — no file under artifact_dir is created
    or modified by the diagnostic."""

    def test_artifact_dir_is_not_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            cid = "readonly-check"
            artifact_path = _write_artifact(
                artifact_dir, cid,
                {
                    "artifact_type":    "analyzed_event_artifact",
                    "candidate_id":     cid,
                    "headline":         _GOOD_HEADLINE,
                    "event_date":       "2022-07-28",
                    "mechanism_family": "supply_shock",
                    "primary_ticker":   "XOM",
                    "benchmark_ticker": "XLE",
                },
            )
            before_hash = _sha256(str(artifact_path))
            before_files = sorted(p.name for p in artifact_dir.iterdir())
            inbox_path = _write_inbox(
                [_entry(_GOOD_HEADLINE, candidate_id=cid)],
            )
            try:
                cli.run_section_c_daily_quality_diagnostic(
                    input_path=inbox_path,
                    artifact_dir=str(artifact_dir),
                )
                after_hash = _sha256(str(artifact_path))
                after_files = sorted(p.name for p in artifact_dir.iterdir())
                self.assertEqual(before_hash, after_hash,
                                 "audit must not mutate artifact bytes")
                self.assertEqual(before_files, after_files,
                                 "audit must not create or remove files")
            finally:
                os.unlink(inbox_path)


class TestArtifactAuditCLI(unittest.TestCase):
    """The CLI exposes --artifact-dir and threads it through main."""

    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = StringIO()
        try:
            rc = cli.main(argv, out=buf)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, buf.getvalue()

    def test_cli_with_artifact_dir_emits_audit_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            cid = "cli-test-005"
            _write_artifact(
                artifact_dir, cid,
                {
                    "artifact_type":    "analyzed_event_artifact",
                    "candidate_id":     cid,
                    "headline":         _GOOD_HEADLINE,
                    "event_date":       "2022-07-28",
                    "mechanism_family": "supply_shock",
                    "primary_ticker":   "XOM",
                    "benchmark_ticker": "XLE",
                },
            )
            inbox_path = _write_inbox(
                [_entry(_GOOD_HEADLINE, candidate_id=cid)],
            )
            try:
                rc, output = self._run([
                    "--input", inbox_path, "--json",
                    "--artifact-dir", str(artifact_dir),
                ])
                self.assertEqual(rc, 0)
                parsed = json.loads(output)
                # Envelope still satisfies the strict key set; audit
                # fields appear on candidates only.
                self.assertEqual(set(parsed.keys()), set(_REQUIRED_KEYS))
                cands = _flatten_candidates(parsed)
                self.assertEqual(len(cands), 1)
                cand = cands[0]
                self.assertEqual(cand["candidate_id"], cid)
                self.assertTrue(cand["artifact_present"])
                self.assertTrue(cand["artifact_fields_complete"])
            finally:
                os.unlink(inbox_path)


if __name__ == "__main__":
    unittest.main()
