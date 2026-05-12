"""Tests for ``scripts/section_c_weekly_duplicate_diagnostic.py``.

Pin the contract:

* Read-only on every input.  Never mutates the events DB; reopening
  the DB after a run and hashing the file shows the bytes unchanged.
* The connection is opened in SQLite URI ``mode=ro`` form so any
  attempted write would fail at the driver level — verified with a
  monkey-patched ``sqlite3.connect`` that records the URI it received.
* Output envelope carries the full set of required keys with the
  spec'd shape; each duplicate-group dict carries the required eight
  fields.
* Detection axes work in isolation: (date, ticker) groups, headline-
  equality groups, and headline-prefix groups all fire on synthetic
  inputs that exhibit only one pattern.
* Conservative wording: banned tokens absent from every surfaced
  prose stream.
* No DB writes — round-trip the temp DB through the diagnostic and
  verify byte equality before/after.
* No paid-surface imports.
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
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import section_c_weekly_duplicate_diagnostic as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "candidates_checked",
    "duplicate_groups",
    "repeated_date_ticker_groups",
    "repeated_headline_groups",
    "mechanism_theme_candidates",
    "canonical_headline_suggestions",
    "recommended_weekly_filter_rules",
    "warnings",
    "errors",
)


_REQUIRED_GROUP_FIELDS = (
    "duplicate_group_id",
    "event_ids",
    "headlines",
    "dates",
    "tickers",
    "mechanism_families",
    "suggested_canonical_event_id",
    "reason",
)


_BANNED_TOKENS = (
    "proof",
    "proven",
    "automatically",
    "alpha generated",
    "guaranteed",
    "correct ticker",
)


# ---------------------------------------------------------------------------
# Synthetic temp-DB builder
# ---------------------------------------------------------------------------


_EVENTS_SCHEMA = """
CREATE TABLE events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    headline          TEXT NOT NULL,
    stage             TEXT NOT NULL,
    persistence       TEXT NOT NULL,
    market_tickers    TEXT DEFAULT '[]',
    event_date        TEXT DEFAULT NULL,
    mechanism_family  TEXT DEFAULT 'none'
)
"""


def _write_temp_db(rows: list[dict[str, Any]]) -> str:
    """Build a temp SQLite DB carrying a minimal ``events`` table.

    Only the columns the diagnostic queries are populated; the rest
    of the production schema is intentionally omitted to keep the
    fixture small.  Returns the absolute path.
    """
    fd, path = tempfile.mkstemp(
        prefix=f"section_c_diag_{uuid.uuid4().hex}_", suffix=".db",
    )
    os.close(fd)
    conn = sqlite3.connect(path)
    try:
        conn.execute(_EVENTS_SCHEMA)
        for r in rows:
            conn.execute(
                "INSERT INTO events "
                "(id, timestamp, headline, stage, persistence, "
                " market_tickers, event_date, mechanism_family) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r.get("id"),
                    r.get("timestamp", "2026-05-08T00:00:00Z"),
                    r.get("headline", ""),
                    r.get("stage",       "stage_main"),
                    r.get("persistence", "persistent"),
                    r.get("market_tickers", "[]"),
                    r.get("event_date"),
                    r.get("mechanism_family", "none"),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _row(
    *, event_id: int, headline: str, event_date: str = "2026-05-08",
    market_tickers: str = "[]", mechanism_family: str = "none",
) -> dict[str, Any]:
    return {
        "id":               event_id,
        "headline":         headline,
        "event_date":       event_date,
        "market_tickers":   market_tickers,
        "mechanism_family": mechanism_family,
    }


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_envelope_has_all_required_keys(self) -> None:
        db = _write_temp_db([])
        try:
            report = cli.build_diagnostic(
                db_path=db,
                reference_date="2026-05-08",
            )
            for k in _REQUIRED_ENVELOPE_KEYS:
                self.assertIn(k, report, f"missing key: {k}")
        finally:
            os.unlink(db)

    def test_ok_true_when_db_loads_cleanly(self) -> None:
        db = _write_temp_db([_row(
            event_id=1, headline="Hello world",
            event_date="2026-05-08",
        )])
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["candidates_checked"], 1)
        finally:
            os.unlink(db)

    def test_missing_db_surfaces_warning_not_error(self) -> None:
        missing = os.path.join(
            tempfile.gettempdir(), f"absent_{uuid.uuid4().hex}.db",
        )
        self.assertFalse(os.path.exists(missing))
        report = cli.build_diagnostic(
            db_path=missing, reference_date="2026-05-08",
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["candidates_checked"], 0)
        self.assertTrue(any(
            "missing" in w.lower() for w in report["warnings"]
        ))


# ---------------------------------------------------------------------------
# Read-only enforcement
# ---------------------------------------------------------------------------


class TestReadOnlyEnforcement(unittest.TestCase):
    def test_connection_opens_with_mode_ro_uri(self) -> None:
        """The diagnostic must open the DB with the URI ``mode=ro``
        flag so the read-only contract is enforced at the driver
        level, not just by inspection of the SQL strings."""
        db = _write_temp_db([_row(
            event_id=1, headline="x", event_date="2026-05-08",
        )])
        try:
            recorded: dict[str, Any] = {}
            real_connect = sqlite3.connect

            def _spy_connect(*args, **kwargs):
                recorded["args"]   = args
                recorded["kwargs"] = kwargs
                return real_connect(*args, **kwargs)

            with patch.object(cli, "sqlite3", create=False) as mod:
                mod.connect = _spy_connect
                mod.Error   = sqlite3.Error
                cli.build_diagnostic(
                    db_path=db, reference_date="2026-05-08",
                )
            uri_arg = recorded["args"][0]
            self.assertIsInstance(uri_arg, str)
            self.assertTrue(
                uri_arg.startswith("file:") and "mode=ro" in uri_arg,
                f"connection URI must enforce read-only; got {uri_arg!r}",
            )
            self.assertTrue(recorded["kwargs"].get("uri") is True)
        finally:
            os.unlink(db)

    def test_run_does_not_change_db_bytes(self) -> None:
        db = _write_temp_db([
            _row(event_id=1, headline="A", event_date="2026-05-08"),
            _row(event_id=2, headline="A", event_date="2026-05-08"),
            _row(event_id=3, headline="A different story",
                 event_date="2026-05-08"),
        ])
        try:
            before = _sha256(db)
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            self.assertTrue(report["ok"])
            after = _sha256(db)
            self.assertEqual(
                before, after,
                "diagnostic must not modify the events DB on disk",
            )
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Axis 1: (date, ticker) groups
# ---------------------------------------------------------------------------


class TestRepeatedDateTickerGroups(unittest.TestCase):
    def test_identical_date_and_tickers_group_together(self) -> None:
        rows = [
            _row(event_id=1, headline="Tariff news A",
                 event_date="2026-05-08",
                 market_tickers='[{"symbol":"XLE"},{"symbol":"SPY"}]'),
            _row(event_id=2, headline="Tariff news B",
                 event_date="2026-05-08",
                 market_tickers='[{"symbol":"XLE"},{"symbol":"SPY"}]'),
            _row(event_id=3, headline="Unrelated", event_date="2026-05-08",
                 market_tickers='[{"symbol":"GM"}]'),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            groups = report["repeated_date_ticker_groups"]
            self.assertEqual(len(groups), 1)
            g = groups[0]
            self.assertEqual(g["event_ids"], [1, 2])
            self.assertEqual(g["tickers"], ["SPY", "XLE"])
            self.assertIn(g, report["duplicate_groups"])
        finally:
            os.unlink(db)

    def test_empty_tickers_are_not_grouped_on_this_axis(self) -> None:
        # The (date, tickers) axis must NOT collapse every empty-
        # ticker row into one mega-group.
        rows = [
            _row(event_id=1, headline="X", event_date="2026-05-08",
                 market_tickers="[]"),
            _row(event_id=2, headline="Y", event_date="2026-05-08",
                 market_tickers="[]"),
            _row(event_id=3, headline="Z", event_date="2026-05-08",
                 market_tickers="[]"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            self.assertEqual(report["repeated_date_ticker_groups"], [])
        finally:
            os.unlink(db)

    def test_different_dates_do_not_group_even_with_same_tickers(self) -> None:
        rows = [
            _row(event_id=1, headline="X", event_date="2026-05-07",
                 market_tickers='[{"symbol":"XLE"}]'),
            _row(event_id=2, headline="X", event_date="2026-05-08",
                 market_tickers='[{"symbol":"XLE"}]'),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            self.assertEqual(report["repeated_date_ticker_groups"], [])
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Axis 2: headline equality + prefix
# ---------------------------------------------------------------------------


class TestRepeatedHeadlineGroups(unittest.TestCase):
    def test_exact_headline_repeat_groups_events(self) -> None:
        rows = [
            _row(event_id=1, headline="Turkey lira weakens",
                 event_date="2026-05-08"),
            _row(event_id=2, headline="Turkey lira weakens",
                 event_date="2026-05-08"),
            _row(event_id=3, headline="Unrelated story",
                 event_date="2026-05-08"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            groups = report["repeated_headline_groups"]
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["event_ids"], [1, 2])
        finally:
            os.unlink(db)

    def test_prefix_headline_groups_with_longer_variant(self) -> None:
        # "Fed speakers rotate" should cluster with "Fed speakers
        # rotate on inflation commentary" — the shorter is a strict
        # token-prefix of the longer.
        rows = [
            _row(event_id=10, headline="Fed speakers rotate",
                 event_date="2026-05-08"),
            _row(event_id=11,
                 headline="Fed speakers rotate on inflation commentary",
                 event_date="2026-05-08"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            groups = report["repeated_headline_groups"]
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["event_ids"], [10, 11])
        finally:
            os.unlink(db)

    def test_prefix_requires_token_boundary_not_substring(self) -> None:
        # "Fed" must NOT swallow "Federal Reserve" — a prefix match
        # requires the anchor + a space.
        rows = [
            _row(event_id=20, headline="Fed", event_date="2026-05-08"),
            _row(event_id=21, headline="Federal Reserve hikes",
                 event_date="2026-05-08"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            self.assertEqual(report["repeated_headline_groups"], [])
        finally:
            os.unlink(db)

    def test_different_event_dates_do_not_cross_cluster(self) -> None:
        rows = [
            _row(event_id=30, headline="Turkey lira weakens",
                 event_date="2026-05-07"),
            _row(event_id=31, headline="Turkey lira weakens",
                 event_date="2026-05-08"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            self.assertEqual(report["repeated_headline_groups"], [])
        finally:
            os.unlink(db)

    def test_each_event_lands_in_at_most_one_headline_group(self) -> None:
        rows = [
            _row(event_id=40, headline="A B C", event_date="2026-05-08"),
            _row(event_id=41, headline="A B C", event_date="2026-05-08"),
            _row(event_id=42, headline="A B C D", event_date="2026-05-08"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            groups = report["repeated_headline_groups"]
            seen: set[int] = set()
            for g in groups:
                for eid in g["event_ids"]:
                    self.assertNotIn(
                        eid, seen,
                        f"event_id {eid} appears in multiple "
                        f"headline groups",
                    )
                    seen.add(eid)
            self.assertEqual(seen, {40, 41, 42})
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Suggested canonical & headline suggestions
# ---------------------------------------------------------------------------


class TestSuggestedCanonical(unittest.TestCase):
    def test_canonical_is_longest_headline(self) -> None:
        rows = [
            _row(event_id=50, headline="Short", event_date="2026-05-08"),
            _row(event_id=51, headline="Short with more detail",
                 event_date="2026-05-08"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            g = report["repeated_headline_groups"][0]
            # Longer headline (51) is the suggestion.
            self.assertEqual(g["suggested_canonical_event_id"], 51)
            # And the canonical_headline_suggestions list matches.
            self.assertEqual(len(report["canonical_headline_suggestions"]), 1)
            suggestion = report["canonical_headline_suggestions"][0]
            self.assertEqual(
                suggestion["canonical_headline"], "Short with more detail",
            )
            self.assertEqual(suggestion["event_ids"], [50, 51])
        finally:
            os.unlink(db)

    def test_canonical_field_is_a_suggestion_not_a_directive(self) -> None:
        # The field name itself enforces the "suggestion" framing:
        # the diagnostic must NEVER write a 'canonical_event_id'
        # (without the 'suggested_' prefix) into a group dict.
        rows = [
            _row(event_id=60, headline="X", event_date="2026-05-08"),
            _row(event_id=61, headline="X", event_date="2026-05-08"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            for g in report["duplicate_groups"]:
                self.assertIn("suggested_canonical_event_id", g)
                self.assertNotIn("canonical_event_id", g)
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Mechanism theme candidates
# ---------------------------------------------------------------------------


class TestMechanismThemeCandidates(unittest.TestCase):
    def test_family_recurring_at_or_above_threshold_surfaced(self) -> None:
        rows = [
            _row(event_id=70 + i, headline=f"h{i}",
                 event_date="2026-05-08",
                 mechanism_family="supply_shock")
            for i in range(3)
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
                theme_threshold=3,
            )
            self.assertEqual(len(report["mechanism_theme_candidates"]), 1)
            entry = report["mechanism_theme_candidates"][0]
            self.assertEqual(entry["mechanism_family"], "supply_shock")
            self.assertEqual(entry["event_count"], 3)
            self.assertEqual(sorted(entry["event_ids"]), [70, 71, 72])
        finally:
            os.unlink(db)

    def test_family_below_threshold_not_surfaced(self) -> None:
        rows = [
            _row(event_id=80, headline="h", event_date="2026-05-08",
                 mechanism_family="supply_shock"),
            _row(event_id=81, headline="h", event_date="2026-05-08",
                 mechanism_family="supply_shock"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
                theme_threshold=3,
            )
            self.assertEqual(report["mechanism_theme_candidates"], [])
        finally:
            os.unlink(db)

    def test_placeholder_none_family_is_skipped(self) -> None:
        rows = [
            _row(event_id=90 + i, headline=f"h{i}",
                 event_date="2026-05-08", mechanism_family="none")
            for i in range(5)
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
                theme_threshold=3,
            )
            self.assertEqual(report["mechanism_theme_candidates"], [])
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Duplicate group shape
# ---------------------------------------------------------------------------


class TestDuplicateGroupShape(unittest.TestCase):
    def test_each_group_has_eight_required_fields(self) -> None:
        rows = [
            _row(event_id=100, headline="repeating story",
                 event_date="2026-05-08",
                 market_tickers='[{"symbol":"XLE"}]'),
            _row(event_id=101, headline="repeating story",
                 event_date="2026-05-08",
                 market_tickers='[{"symbol":"XLE"}]'),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            self.assertTrue(report["duplicate_groups"])
            for g in report["duplicate_groups"]:
                for f in _REQUIRED_GROUP_FIELDS:
                    self.assertIn(f, g, f"group missing field: {f}")
        finally:
            os.unlink(db)

    def test_duplicate_group_ids_are_unique(self) -> None:
        rows = [
            _row(event_id=110, headline="story alpha",
                 event_date="2026-05-08",
                 market_tickers='[{"symbol":"XLE"}]'),
            _row(event_id=111, headline="story alpha",
                 event_date="2026-05-08",
                 market_tickers='[{"symbol":"XLE"}]'),
            _row(event_id=112, headline="story beta",
                 event_date="2026-05-08",
                 market_tickers='[{"symbol":"SPY"}]'),
            _row(event_id=113, headline="story beta",
                 event_date="2026-05-08",
                 market_tickers='[{"symbol":"SPY"}]'),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            ids = [g["duplicate_group_id"] for g in report["duplicate_groups"]]
            self.assertEqual(len(ids), len(set(ids)))
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Window filtering
# ---------------------------------------------------------------------------


class TestWindowFiltering(unittest.TestCase):
    def test_events_outside_window_are_excluded(self) -> None:
        rows = [
            _row(event_id=200, headline="inside",
                 event_date="2026-05-08"),
            _row(event_id=201, headline="outside (too old)",
                 event_date="2026-04-01"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
                window_days=7,
            )
            self.assertEqual(report["candidates_checked"], 1)
            self.assertEqual(
                report["window"]["window_start"], "2026-05-01",
            )
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_tokens_in_json_render(self) -> None:
        rows = [
            _row(event_id=300, headline="repeating", event_date="2026-05-08"),
            _row(event_id=301, headline="repeating", event_date="2026-05-08"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            blob = cli._render_json(report).lower()
            for term in _BANNED_TOKENS:
                self.assertNotIn(
                    term, blob,
                    f"banned token {term!r} in JSON render",
                )
        finally:
            os.unlink(db)

    def test_no_banned_tokens_in_text_render(self) -> None:
        rows = [
            _row(event_id=310, headline="repeating", event_date="2026-05-08"),
            _row(event_id=311, headline="repeating", event_date="2026-05-08"),
        ]
        db = _write_temp_db(rows)
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            blob = cli._render_text(report).lower()
            for term in _BANNED_TOKENS:
                self.assertNotIn(term, blob)
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Recommended filter rules
# ---------------------------------------------------------------------------


class TestRecommendedRules(unittest.TestCase):
    def test_rules_are_present_and_phrased_as_suggestions(self) -> None:
        db = _write_temp_db([])
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            rules = report["recommended_weekly_filter_rules"]
            self.assertGreaterEqual(len(rules), 3)
            for rule in rules:
                self.assertIsInstance(rule, str)
                # Every rule is phrased as a suggestion / does not
                # describe the diagnostic as having applied a change.
                self.assertIn("suggested", rule.lower())
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Output file persistence
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_no_output_means_no_file(self) -> None:
        db = _write_temp_db([])
        sentinel = os.path.join(
            tempfile.gettempdir(),
            f"section_c_sentinel_{uuid.uuid4().hex}.json",
        )
        try:
            self.assertFalse(os.path.exists(sentinel))
            cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
            )
            self.assertFalse(os.path.exists(sentinel))
        finally:
            os.unlink(db)
            if os.path.exists(sentinel):
                os.unlink(sentinel)

    def test_output_writes_file(self) -> None:
        db = _write_temp_db([_row(
            event_id=400, headline="hi", event_date="2026-05-08",
        )])
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"section_c_out_{uuid.uuid4().hex}.json",
        )
        try:
            report = cli.build_diagnostic(
                db_path=db, reference_date="2026-05-08",
                output_path=out_path,
            )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(set(data.keys()) >= set(_REQUIRED_ENVELOPE_KEYS),
                             True)
            self.assertEqual(data["ok"], report["ok"])
        finally:
            os.unlink(db)
            if os.path.exists(out_path):
                os.unlink(out_path)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        return rc, out.getvalue()

    def test_json_default(self) -> None:
        db = _write_temp_db([])
        try:
            rc, output = self._run([
                "--db-path", db, "--reference-date", "2026-05-08",
            ])
            self.assertEqual(rc, 0)
            payload = json.loads(output)
            for k in _REQUIRED_ENVELOPE_KEYS:
                self.assertIn(k, payload)
        finally:
            os.unlink(db)

    def test_text_flag(self) -> None:
        db = _write_temp_db([])
        try:
            rc, output = self._run([
                "--text", "--db-path", db,
                "--reference-date", "2026-05-08",
            ])
            self.assertEqual(rc, 0)
            self.assertIn("weekly market", output.lower())
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    def test_module_does_not_bind_paid_surfaces(self) -> None:
        for attr in ("yfinance", "anthropic", "openai", "fastapi",
                     "market_data"):
            self.assertFalse(
                hasattr(cli, attr),
                f"diagnostic must not bind {attr} as a module attr",
            )


if __name__ == "__main__":
    unittest.main()
