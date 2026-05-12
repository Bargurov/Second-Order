"""Tests for ``scripts/section_c_daily_mechanism_enrichment_diagnostic.py``.

The Daily mechanism-enrichment diagnostic asks, per inbox row,
whether an exact or normalized headline match exists among events
whose ``mechanism_family`` is set to a usable value.  It NEVER
assigns mechanism_family, NEVER calls an LLM, and NEVER performs
fuzzy matching.

Pin the contract:

* Read-only: no DB writes; no provider, LLM, FastAPI; no mutation
  of news_inbox / events / artifacts.
* Output envelope carries the spec's top-level keys exactly, and
  every per-match dict carries the spec's eight keys.
* Matching is exact-or-normalized only.  The normalization is
  case-fold + collapse whitespace + strip + drop trailing period —
  pinned directly so a future drift gets caught here.
* Events with ``mechanism_family`` set to ``'none'`` / ``''`` /
  ``None`` are filtered out at the seam; they never appear as
  match candidates.
* Multiple events with the same normalized headline surface as an
  ambiguity warning (the diagnostic picks one for the match record
  but the operator sees the audit signal).
* Inbox rows with empty / missing ``title`` are skipped with a
  warning, NOT counted as candidates.
* Inbox file missing → warning, empty matches and gaps, ``ok`` stays
  True.
* Conservative wording — banned tokens absent; the ``caution``
  reminder is present on every match.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import (  # noqa: E402
    section_c_daily_mechanism_enrichment_diagnostic as cli,
)


_REQUIRED_TOP_KEYS = (
    "ok",
    "daily_candidates_checked",
    "candidates_without_mechanism_family",
    "possible_event_matches",
    "enrichment_sources_available",
    "enrichment_gaps",
    "recommended_enrichment_path",
    "warnings",
    "errors",
)


_REQUIRED_MATCH_KEYS = (
    "inbox_headline",
    "matched_event_id",
    "event_headline",
    "match_type",
    "event_mechanism_family",
    "event_primary_ticker",
    "confidence_label",
    "caution",
)


_BANNED_WORDS = (
    "proof",
    "proven",
    "broken",
    "wrong",
    "must fix",
    "guaranteed",
    "automatically",
    "definitely",
    "causes",
    "causation",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_inbox(rows: list[dict[str, Any]]) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"section_c_inbox_{uuid.uuid4().hex}.json",
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh)
    return path


def _make_events_db(
    *, rows: list[dict[str, Any]],
) -> str:
    """Build a SQLite fixture carrying events + curated_candidates
    tables with mechanism_family columns.  Used by the read-only
    seam tests so we don't have to mock at the SQL level.
    """
    path = os.path.join(
        tempfile.gettempdir(),
        f"section_c_fix_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute("""
            CREATE TABLE events (
                id               INTEGER PRIMARY KEY,
                headline         TEXT,
                market_tickers   TEXT,
                mechanism_family TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE curated_candidates (
                id               INTEGER PRIMARY KEY,
                mechanism_family TEXT
            )
        """)
        for r in rows:
            conn.execute(
                "INSERT INTO events "
                "(id, headline, market_tickers, mechanism_family) "
                "VALUES (?, ?, ?, ?)",
                (
                    r["id"], r["headline"],
                    json.dumps(r.get("market_tickers") or []),
                    r.get("mechanism_family"),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _event_dict(
    *,
    event_id:         int,
    headline:         str,
    primary_ticker:   str | None = None,
    mechanism_family: str = "demand_shock",
) -> dict[str, Any]:
    """Helper for the patched seam — returns the shape the real
    seam emits.
    """
    return {
        "event_id":         event_id,
        "headline":         headline,
        "primary_ticker":   primary_ticker,
        "mechanism_family": mechanism_family,
        "source":           "events.mechanism_family",
    }


def _enrichment_seam(
    *,
    rows: list[dict[str, Any]] | None = None,
    sources: dict[str, int] | None = None,
    warnings: list[str] | None = None,
):
    """Build a callable suitable for patching
    ``cli._load_events_with_mechanism``.
    """
    rows_ = list(rows or [])
    if sources is None:
        sources = {
            "events.mechanism_family":             len(rows_),
            "curated_candidates.mechanism_family": 0,
        }
    warnings_ = list(warnings or [])
    def _seam(*, db_path):  # noqa: ANN001
        return rows_, dict(sources), list(warnings_)
    return _seam


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization(unittest.TestCase):
    def test_identity(self) -> None:
        self.assertEqual(
            cli._normalize_headline("OPEC keeps output steady"),
            "opec keeps output steady",
        )

    def test_case_and_whitespace_variant(self) -> None:
        self.assertEqual(
            cli._normalize_headline("  OPEC   keeps OUTPUT steady  "),
            "opec keeps output steady",
        )

    def test_trailing_period_stripped(self) -> None:
        self.assertEqual(
            cli._normalize_headline("OPEC keeps output steady."),
            "opec keeps output steady",
        )

    def test_internal_period_preserved(self) -> None:
        # The normalization strips only a trailing period — never
        # internal punctuation, otherwise it would creep toward fuzzy
        # matching.
        self.assertEqual(
            cli._normalize_headline("U.S. Treasury issues licence"),
            "u.s. treasury issues licence",
        )


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_top_level_keys(self) -> None:
        inbox = _write_inbox([])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS),
                             f"unexpected keys: {sorted(report.keys())}")
        finally:
            os.unlink(inbox)

    def test_match_record_keys(self) -> None:
        inbox = _write_inbox([{"title": "OPEC keeps output steady"}])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(rows=[
                    _event_dict(
                        event_id=42,
                        headline="OPEC keeps output steady",
                        primary_ticker="XOM",
                        mechanism_family="supply_shock",
                    ),
                ]),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            self.assertEqual(len(report["possible_event_matches"]), 1)
            self.assertEqual(
                set(report["possible_event_matches"][0].keys()),
                set(_REQUIRED_MATCH_KEYS),
            )
        finally:
            os.unlink(inbox)


# ---------------------------------------------------------------------------
# Exact match path
# ---------------------------------------------------------------------------


class TestExactMatch(unittest.TestCase):
    def test_exact_match_surfaces_as_possible_event_match(self) -> None:
        inbox = _write_inbox([
            {"title": "OPEC keeps output steady"},
        ])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(rows=[
                    _event_dict(
                        event_id=42,
                        headline="OPEC keeps output steady",
                        primary_ticker="XOM",
                        mechanism_family="supply_shock",
                    ),
                ]),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["daily_candidates_checked"], 1)
            self.assertEqual(report["candidates_without_mechanism_family"], 1)
            self.assertEqual(report["enrichment_gaps"], [])
            match = report["possible_event_matches"][0]
            self.assertEqual(match["match_type"], "exact")
            self.assertEqual(match["matched_event_id"], 42)
            self.assertEqual(match["event_mechanism_family"], "supply_shock")
            self.assertEqual(match["event_primary_ticker"], "XOM")
            self.assertEqual(match["confidence_label"],
                             "exact_headline_match")
            self.assertIn("operator review", match["caution"].lower())
        finally:
            os.unlink(inbox)


# ---------------------------------------------------------------------------
# Normalized match path
# ---------------------------------------------------------------------------


class TestNormalizedMatch(unittest.TestCase):
    def test_normalized_match_surfaces_when_exact_fails(self) -> None:
        inbox = _write_inbox([
            {"title": "  OPEC  KEEPS output STEADY.  "},
        ])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(rows=[
                    _event_dict(
                        event_id=11,
                        headline="OPEC keeps output steady",
                        mechanism_family="supply_shock",
                    ),
                ]),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            match = report["possible_event_matches"][0]
            self.assertEqual(match["match_type"], "normalized")
            self.assertEqual(match["confidence_label"],
                             "normalized_headline_match")
        finally:
            os.unlink(inbox)

    def test_exact_match_preferred_over_normalized(self) -> None:
        inbox = _write_inbox([
            {"title": "Headline X"},
        ])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(rows=[
                    _event_dict(event_id=1, headline="headline x"),
                    _event_dict(event_id=2, headline="Headline X"),
                ]),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            match = report["possible_event_matches"][0]
            self.assertEqual(match["match_type"], "exact")
            self.assertEqual(match["matched_event_id"], 2)
        finally:
            os.unlink(inbox)


# ---------------------------------------------------------------------------
# Enrichment gaps
# ---------------------------------------------------------------------------


class TestEnrichmentGaps(unittest.TestCase):
    def test_no_match_lands_in_enrichment_gaps(self) -> None:
        inbox = _write_inbox([
            {"title": "An unmatched headline"},
        ])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(rows=[
                    _event_dict(
                        event_id=99,
                        headline="A completely different headline",
                    ),
                ]),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            self.assertEqual(report["possible_event_matches"], [])
            self.assertEqual(len(report["enrichment_gaps"]), 1)
            gap = report["enrichment_gaps"][0]
            self.assertEqual(gap["inbox_headline"], "An unmatched headline")
            self.assertIn("enrichment gap", gap["gap_reason"].lower())
        finally:
            os.unlink(inbox)

    def test_empty_title_skipped_with_warning(self) -> None:
        inbox = _write_inbox([
            {"title": ""},
            {"title": "   "},
            {"source": "no-title-field"},
            {"title": "Real headline"},
        ])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(rows=[
                    _event_dict(event_id=1, headline="Real headline"),
                ]),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            # Three rows skipped → only ONE candidate counted.
            self.assertEqual(report["daily_candidates_checked"], 1)
            self.assertEqual(
                report["candidates_without_mechanism_family"], 1,
            )
            # Three warnings about skipped rows (one per empty title).
            empty_title_warnings = [
                w for w in report["warnings"]
                if "empty or missing title" in w.lower()
            ]
            self.assertEqual(len(empty_title_warnings), 3)
        finally:
            os.unlink(inbox)


# ---------------------------------------------------------------------------
# Enrichment sources
# ---------------------------------------------------------------------------


class TestEnrichmentSources(unittest.TestCase):
    def test_sources_present_when_events_have_mechanism_family(self) -> None:
        inbox = _write_inbox([{"title": "X"}])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(
                    rows=[_event_dict(event_id=1, headline="X")],
                    sources={
                        "events.mechanism_family":              1,
                        "curated_candidates.mechanism_family":  3,
                    },
                ),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            names = {
                s["source"]: s
                for s in report["enrichment_sources_available"]
            }
            self.assertTrue(names["events.mechanism_family"]["present"])
            self.assertEqual(
                names["events.mechanism_family"]["rows_with_value"], 1,
            )
            self.assertTrue(
                names["curated_candidates.mechanism_family"]["present"],
            )
            self.assertEqual(
                names["curated_candidates.mechanism_family"]["rows_with_value"],
                3,
            )
        finally:
            os.unlink(inbox)

    def test_no_sources_path_recommendation(self) -> None:
        inbox = _write_inbox([{"title": "X"}])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(
                    rows=[],
                    sources={
                        "events.mechanism_family":              0,
                        "curated_candidates.mechanism_family":  0,
                    },
                ),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            for s in report["enrichment_sources_available"]:
                self.assertFalse(s["present"])
            action = report["recommended_enrichment_path"].lower()
            self.assertIn("no enrichment source", action,
                          f"action: {action!r}")
        finally:
            os.unlink(inbox)


# ---------------------------------------------------------------------------
# Ambiguity handling
# ---------------------------------------------------------------------------


class TestAmbiguity(unittest.TestCase):
    def test_duplicate_exact_headline_warning(self) -> None:
        inbox = _write_inbox([{"title": "Same headline"}])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(rows=[
                    _event_dict(event_id=1, headline="Same headline"),
                    _event_dict(event_id=2, headline="Same headline"),
                ]),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            self.assertEqual(len(report["possible_event_matches"]), 1)
            joined = " ".join(report["warnings"]).lower()
            self.assertIn("duplicate event headline", joined,
                          f"warnings: {report['warnings']}")
        finally:
            os.unlink(inbox)

    def test_multiple_normalized_matches_warn(self) -> None:
        # Two events whose headlines normalize to the same string but
        # differ in case/whitespace — the diagnostic picks one and
        # surfaces an ambiguity warning.
        inbox = _write_inbox([{"title": "Output steady"}])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(rows=[
                    _event_dict(event_id=1, headline="output steady"),
                    _event_dict(event_id=2, headline="OUTPUT STEADY"),
                ]),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            self.assertEqual(len(report["possible_event_matches"]), 1)
            joined = " ".join(report["warnings"]).lower()
            self.assertIn("normalized headline", joined,
                          f"warnings: {report['warnings']}")
        finally:
            os.unlink(inbox)


# ---------------------------------------------------------------------------
# Filter out unusable mechanism_family values via the real seam
# ---------------------------------------------------------------------------


class TestRealSeamFilter(unittest.TestCase):
    def test_real_seam_drops_none_and_empty_mechanism_family(self) -> None:
        db_path = _make_events_db(rows=[
            {"id": 1, "headline": "Real headline",
             "mechanism_family": "supply_shock",
             "market_tickers": ["XOM"]},
            {"id": 2, "headline": "Default-none headline",
             "mechanism_family": "none",
             "market_tickers": ["XYZ"]},
            {"id": 3, "headline": "Empty-string headline",
             "mechanism_family": "",
             "market_tickers": []},
        ])
        try:
            rows, sources, warnings = cli._load_events_with_mechanism(
                db_path=db_path,
            )
            ids = {r["event_id"] for r in rows}
            self.assertEqual(ids, {1},
                             f"unexpected ids returned: {ids}")
            self.assertEqual(sources["events.mechanism_family"], 1)
            # No warnings on a clean run.
            self.assertEqual(warnings, [])
        finally:
            os.unlink(db_path)

    def test_real_seam_is_read_only(self) -> None:
        # Hash the DB file before/after the seam call; equality means
        # the seam issued only SELECT.
        db_path = _make_events_db(rows=[
            {"id": 1, "headline": "Real headline",
             "mechanism_family": "supply_shock",
             "market_tickers": ["XOM"]},
        ])
        try:
            def sha256(p):  # noqa: ANN001
                h = hashlib.sha256()
                with open(p, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
                return h.hexdigest()
            before = sha256(db_path)
            cli._load_events_with_mechanism(db_path=db_path)
            self.assertEqual(sha256(db_path), before)
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Inbox file missing / malformed
# ---------------------------------------------------------------------------


class TestInboxMissing(unittest.TestCase):
    def test_missing_inbox_warns_and_returns_empty(self) -> None:
        missing = os.path.join(
            tempfile.gettempdir(),
            f"missing_inbox_{uuid.uuid4().hex}.json",
        )
        # Do NOT create the file.
        with patch.object(
            cli, "_load_events_with_mechanism",
            side_effect=_enrichment_seam(),
        ):
            report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                inbox_path=missing,
            )
        self.assertTrue(report["ok"])
        self.assertEqual(report["daily_candidates_checked"], 0)
        self.assertEqual(report["possible_event_matches"], [])
        self.assertEqual(report["enrichment_gaps"], [])
        joined = " ".join(report["warnings"]).lower()
        self.assertIn("inbox file not found", joined)

    def test_malformed_inbox_json_warns(self) -> None:
        path = os.path.join(
            tempfile.gettempdir(),
            f"bad_inbox_{uuid.uuid4().hex}.json",
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not valid json}")
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=path,
                )
            self.assertTrue(report["ok"])
            joined = " ".join(report["warnings"]).lower()
            self.assertIn("failed to parse", joined)
        finally:
            os.unlink(path)

    def test_inbox_not_a_list_warns(self) -> None:
        path = os.path.join(
            tempfile.gettempdir(),
            f"obj_inbox_{uuid.uuid4().hex}.json",
        )
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"not": "a list"}, fh)
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=path,
                )
            self.assertTrue(report["ok"])
            joined = " ".join(report["warnings"]).lower()
            self.assertIn("json array", joined)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _all_text(self, report: dict) -> str:
        parts: list[str] = []
        parts.extend(report["warnings"])
        parts.extend(report["errors"])
        parts.append(report["recommended_enrichment_path"])
        for m in report["possible_event_matches"]:
            parts.append(m.get("caution", ""))
        for g in report["enrichment_gaps"]:
            parts.append(g.get("gap_reason", ""))
        return " ".join(parts).lower()

    def test_no_banned_tokens_on_any_path(self) -> None:
        # Exercise three branches: all matched, partial, none matched.
        cases = [
            # all matched
            (
                [{"title": "A"}, {"title": "B"}],
                [_event_dict(event_id=1, headline="A"),
                 _event_dict(event_id=2, headline="B")],
            ),
            # partial
            (
                [{"title": "A"}, {"title": "X"}],
                [_event_dict(event_id=1, headline="A")],
            ),
            # none
            (
                [{"title": "X"}, {"title": "Y"}],
                [],
            ),
        ]
        for titles, events in cases:
            inbox = _write_inbox(titles)
            try:
                with patch.object(
                    cli, "_load_events_with_mechanism",
                    side_effect=_enrichment_seam(rows=events),
                ):
                    report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                        inbox_path=inbox,
                    )
                haystack = self._all_text(report)
                for w in _BANNED_WORDS:
                    self.assertNotIn(
                        w, haystack,
                        f"banned word {w!r} in text",
                    )
            finally:
                os.unlink(inbox)

    def test_every_match_carries_explicit_caution(self) -> None:
        inbox = _write_inbox([{"title": "Match me"}])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(rows=[
                    _event_dict(event_id=1, headline="Match me"),
                ]),
            ):
                report = cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox,
                )
            for m in report["possible_event_matches"]:
                self.assertIn("operator review", m["caution"].lower())
                self.assertIn("does not assign mechanism_family",
                              m["caution"].lower())
        finally:
            os.unlink(inbox)


# ---------------------------------------------------------------------------
# Import isolation — no LLM, no provider, no FastAPI
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = (
        "yfinance",
        "fastapi",
        "api",
        "market_data",
        "anthropic",
        "openai",
    )

    def test_module_import_does_not_pull_provider_llm_or_fastapi(
        self,
    ) -> None:
        # Subprocess-isolated check: prior tests in a full discovery
        # run may have already loaded ``routes.movers`` / FastAPI /
        # anthropic into sys.modules, so an in-process scan would
        # report false positives.  Fresh subprocess sees only what
        # importing the target module actually pulls in.
        from tests._import_isolation_check import (
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name=(
                "scripts.section_c_daily_mechanism_enrichment_diagnostic"
            ),
            blocked=self._BLOCKED,
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_emits_valid_json(self) -> None:
        inbox = _write_inbox([{"title": "X"}])
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(rows=[
                    _event_dict(event_id=1, headline="X"),
                ]),
            ):
                out = StringIO()
                rc = cli.main(
                    ["--json", "--inbox-path", inbox],
                    out=out,
                )
            self.assertEqual(rc, 0, f"output: {out.getvalue()}")
            parsed = json.loads(out.getvalue())
            for k in _REQUIRED_TOP_KEYS:
                self.assertIn(k, parsed)
            self.assertTrue(parsed["ok"])
        finally:
            os.unlink(inbox)


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_output_file_written_when_path_passed(self) -> None:
        inbox = _write_inbox([{"title": "X"}])
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"section_c_daily_out_{uuid.uuid4().hex}.json",
        )
        try:
            with patch.object(
                cli, "_load_events_with_mechanism",
                side_effect=_enrichment_seam(rows=[
                    _event_dict(event_id=1, headline="X"),
                ]),
            ):
                cli.run_section_c_daily_mechanism_enrichment_diagnostic(
                    inbox_path=inbox, output_path=out_path,
                )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
            for k in _REQUIRED_TOP_KEYS:
                self.assertIn(k, parsed)
        finally:
            os.unlink(inbox)
            if os.path.exists(out_path):
                os.unlink(out_path)


if __name__ == "__main__":
    unittest.main()
