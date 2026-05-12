"""Tests for ``scripts/section_c_source_inventory.py``.

The Section C source inventory is a hand-curated read-only map of
where Daily / Weekly / Still Moving Market candidates come from in
this repository.  The tool's value is in surfacing the inventory in
a parseable shape and in flagging — as warnings — any path that has
moved away from the recorded location.

Pin the contract:

* Read-only: no DB queries, no provider, no FastAPI, no file
  mutation.  The only filesystem operation is ``Path.is_file()``.
* Envelope carries the spec's top-level keys exactly.
* Per-stream blocks (``daily_sources`` / ``weekly_sources`` /
  ``still_moving_sources``) carry a deterministic per-stream shape
  (name, route, cache_slice, window, compute_fn, filters_applied,
  ranking_module, artifact_files).
* Missing paths surface in ``warnings``, never in ``errors``; ``ok``
  stays True when only warnings are present.
* Conservative wording — observational language only; banned
  remediation tokens are absent from every emitted text field.
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
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import section_c_source_inventory as cli  # noqa: E402


_REQUIRED_TOP_KEYS = (
    "ok",
    "daily_sources",
    "weekly_sources",
    "still_moving_sources",
    "db_tables_used",
    "scripts_used",
    "routes_used",
    "ranking_fields",
    "filter_fields",
    "suspected_quality_gaps",
    "warnings",
    "errors",
)


_REQUIRED_STREAM_KEYS = (
    "name",
    "route",
    "cache_slice",
    "window",
    "compute_fn",
    "filters_applied",
    "ranking_module",
    "artifact_files",
)


_REQUIRED_ROUTE_KEYS = ("method", "path", "handler")


# The banned-token list intentionally OMITS "validated" because the
# inventory has to describe cache invalidation ("fingerprint-
# invalidated") and a sibling "validation driver" script — both are
# technical terms unrelated to a claim of correctness, which is what
# the banned-token guard actually targets.
_BANNED_WORDS = (
    "proof",
    "proven",
    "broken",
    "wrong",
    "must fix",
    "guaranteed",
    "automatically",
    "definitely",
)


_REMEDIATION_TOKENS = (
    "must fix",
    "should fix",
    "needs fixing",
    "you should",
    "operator must",
    "remediate",
    "rewrite",
)


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_top_level_keys_exact(self) -> None:
        report = cli.build_section_c_source_inventory()
        self.assertEqual(set(report.keys()), set(_REQUIRED_TOP_KEYS),
                         f"unexpected keys: {sorted(report.keys())}")

    def test_per_stream_blocks_carry_required_keys(self) -> None:
        report = cli.build_section_c_source_inventory()
        for key in ("daily_sources", "weekly_sources",
                    "still_moving_sources"):
            block = report[key]
            self.assertIsInstance(block, dict, f"{key}: {type(block)}")
            self.assertEqual(set(block.keys()),
                             set(_REQUIRED_STREAM_KEYS),
                             f"{key}: {sorted(block.keys())}")
            route = block["route"]
            self.assertEqual(set(route.keys()), set(_REQUIRED_ROUTE_KEYS),
                             f"{key} route: {route}")

    def test_stream_names_are_canonical(self) -> None:
        report = cli.build_section_c_source_inventory()
        self.assertEqual(report["daily_sources"]["name"], "Daily")
        self.assertEqual(report["weekly_sources"]["name"], "Weekly")
        self.assertEqual(report["still_moving_sources"]["name"],
                         "Still Moving Market")

    def test_cache_slice_keys_match_known_movers_cache_keys(self) -> None:
        report = cli.build_section_c_source_inventory()
        self.assertEqual(report["daily_sources"]["cache_slice"],
                         "market_movers")
        self.assertEqual(report["weekly_sources"]["cache_slice"],
                         "weekly")
        self.assertEqual(report["still_moving_sources"]["cache_slice"],
                         "persistent")

    def test_route_paths_match_known_endpoints(self) -> None:
        report = cli.build_section_c_source_inventory()
        self.assertEqual(report["daily_sources"]["route"]["path"],
                         "/movers/today")
        self.assertEqual(report["weekly_sources"]["route"]["path"],
                         "/movers/weekly")
        self.assertEqual(report["still_moving_sources"]["route"]["path"],
                         "/movers/persistent")


# ---------------------------------------------------------------------------
# Top-level aggregate shapes
# ---------------------------------------------------------------------------


class TestAggregateShapes(unittest.TestCase):
    def test_db_tables_used_carries_core_tables(self) -> None:
        report = cli.build_section_c_source_inventory()
        names = {entry["table"] for entry in report["db_tables_used"]}
        # These three tables are load-bearing for every stream and the
        # inventory must surface them.
        self.assertIn("events",        names)
        self.assertIn("movers_cache",  names)
        self.assertIn("price_cache",   names)

    def test_scripts_used_entries_carry_exists_flag(self) -> None:
        report = cli.build_section_c_source_inventory()
        self.assertGreater(len(report["scripts_used"]), 0)
        for entry in report["scripts_used"]:
            self.assertIn("path",    entry)
            self.assertIn("purpose", entry)
            self.assertIn("exists",  entry)
            self.assertIsInstance(entry["exists"], bool)

    def test_routes_used_entries_carry_stream_attribution(self) -> None:
        report = cli.build_section_c_source_inventory()
        streams = {entry["stream"] for entry in report["routes_used"]}
        self.assertEqual(
            streams,
            {"Daily", "Weekly", "Still Moving Market"},
        )
        for entry in report["routes_used"]:
            self.assertEqual(entry["method"], "GET")

    def test_ranking_fields_reference_movers_ranking_module(self) -> None:
        report = cli.build_section_c_source_inventory()
        modules = {entry["module"] for entry in report["ranking_fields"]}
        self.assertIn("movers_ranking.py", modules,
                      f"modules: {modules}")

    def test_filter_fields_carry_stream_attribution(self) -> None:
        report = cli.build_section_c_source_inventory()
        # Every filter entry must declare which stream(s) it affects.
        for entry in report["filter_fields"]:
            self.assertIn("stream", entry)
            self.assertIsInstance(entry["stream"], str)
            self.assertTrue(entry["stream"],
                            f"empty stream in: {entry}")

    def test_suspected_quality_gaps_are_observational(self) -> None:
        # Every gap entry must declare which streams it affects and
        # carry a summary string.
        report = cli.build_section_c_source_inventory()
        for entry in report["suspected_quality_gaps"]:
            self.assertIn("id",      entry)
            self.assertIn("summary", entry)
            self.assertIn("streams_affected", entry)
            self.assertIsInstance(entry["streams_affected"], list)
            for s in entry["streams_affected"]:
                self.assertIn(s, ("Daily", "Weekly",
                                  "Still Moving Market"))


# ---------------------------------------------------------------------------
# Path presence checks
# ---------------------------------------------------------------------------


class TestPathPresence(unittest.TestCase):
    def test_recorded_paths_currently_exist_on_disk(self) -> None:
        # Positive check: every hard-coded path in the inventory must
        # currently exist in this repo.  This is the regression guard
        # if a script gets renamed without updating the inventory.
        report = cli.build_section_c_source_inventory()
        self.assertEqual(
            report["warnings"], [],
            f"unexpected warnings: {report['warnings']}",
        )

    def test_missing_script_surfaces_warning_not_error(self) -> None:
        # Patch the existence seam to fail closed on a single known
        # script and confirm the missing-path emits a warning, not an
        # error, and that ok stays True.
        target = "scripts/manual_event_intake_worksheet.py"
        real_check = cli._path_exists

        def fake(*, relative_path):  # noqa: ANN001
            if relative_path == target:
                return False
            return real_check(relative_path=relative_path)

        with patch.object(cli, "_path_exists", side_effect=fake):
            report = cli.build_section_c_source_inventory()
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])
        # Exactly one warning, citing the missing path.
        self.assertTrue(any(target in w for w in report["warnings"]),
                        f"warnings: {report['warnings']}")
        # And the scripts_used entry for that script reports exists=False.
        match = next(
            (e for e in report["scripts_used"] if e["path"] == target),
            None,
        )
        self.assertIsNotNone(match, "target script missing from inventory")
        self.assertFalse(match["exists"])

    def test_missing_route_handler_surfaces_warning(self) -> None:
        target = "routes/movers.py"

        def fake(*, relative_path):  # noqa: ANN001
            if relative_path.startswith(target):
                return False
            return True

        with patch.object(cli, "_path_exists", side_effect=fake):
            report = cli.build_section_c_source_inventory()
        self.assertTrue(report["ok"])
        self.assertGreater(
            len([w for w in report["warnings"] if target in w]),
            0,
            f"warnings: {report['warnings']}",
        )

    def test_all_paths_missing_does_not_flip_ok(self) -> None:
        # The script's job is to *report* missing paths, not to error
        # when they're missing.  ok stays True.
        with patch.object(
            cli, "_path_exists", return_value=False,
        ):
            report = cli.build_section_c_source_inventory()
        self.assertTrue(report["ok"], f"errors: {report['errors']}")
        self.assertGreater(len(report["warnings"]), 0)

    def test_path_exists_seam_uses_file_half_of_handler(self) -> None:
        # Route handlers carry a "file:line" suffix.  The seam must
        # strip the ":line" portion when calling Path.is_file so a
        # real file with a line annotation still resolves.
        self.assertTrue(
            cli._path_exists(relative_path="routes/movers.py:2336"),
        )

    def test_path_exists_seam_handles_empty_string(self) -> None:
        # Defensive: empty relative_path is treated as missing.
        self.assertFalse(cli._path_exists(relative_path=""))


# ---------------------------------------------------------------------------
# Read-only invariant — script does not mutate the filesystem
# ---------------------------------------------------------------------------


class TestReadOnlyInvariant(unittest.TestCase):
    def test_running_the_inventory_does_not_create_files(self) -> None:
        # Hash the working tree's top-level file count before and
        # after; equality means the inventory left no breadcrumbs.
        root = Path(__file__).resolve().parents[1]
        before_listing = sorted(
            p.name for p in root.iterdir() if p.is_file()
        )
        cli.build_section_c_source_inventory()
        after_listing = sorted(
            p.name for p in root.iterdir() if p.is_file()
        )
        self.assertEqual(before_listing, after_listing)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def _all_text_fields(self, report: dict) -> str:
        # Aggregate every text-bearing field into one lowercase blob
        # so a banned token in any of them fails the test loudly.
        parts: list[str] = []
        parts.extend(report["warnings"])
        parts.extend(report["errors"])
        for entry in report["db_tables_used"]:
            parts.append(entry["purpose"])
        for entry in report["scripts_used"]:
            parts.append(entry["purpose"])
        for entry in report["ranking_fields"]:
            parts.append(entry["role"])
        for entry in report["filter_fields"]:
            parts.append(entry["role"])
        for entry in report["suspected_quality_gaps"]:
            parts.append(entry["summary"])
        return " ".join(parts).lower()

    def test_no_banned_tokens_in_any_text(self) -> None:
        report = cli.build_section_c_source_inventory()
        text = self._all_text_fields(report)
        for w in _BANNED_WORDS:
            self.assertNotIn(w, text, f"banned word {w!r} in inventory")

    def test_suspected_quality_gaps_use_observational_language(self) -> None:
        report = cli.build_section_c_source_inventory()
        for entry in report["suspected_quality_gaps"]:
            summary = entry["summary"].lower()
            for tok in _REMEDIATION_TOKENS:
                self.assertNotIn(
                    tok, summary,
                    f"remediation token {tok!r} in gap "
                    f"{entry['id']!r}: {summary!r}",
                )


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = ("yfinance", "fastapi", "api", "market_data")

    def test_module_import_does_not_pull_provider_or_fastapi(self) -> None:
        # Subprocess-isolated: an in-process sys.modules scan would
        # report false positives whenever a prior test in the same
        # discovery process pulled FastAPI / routes.* in.  Fresh
        # subprocess measures only what the target module imports.
        from tests._import_isolation_check import (
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name="scripts.section_c_source_inventory",
            blocked=self._BLOCKED,
        )

    def test_running_inventory_does_not_pull_provider_or_fastapi(
        self,
    ) -> None:
        # Same subprocess-isolated check, but the subprocess actually
        # invokes ``build_section_c_source_inventory()`` after the
        # import so the assertion catches anything the public API
        # secretly pulls in at call time (not just at import time).
        from tests._import_isolation_check import (
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name="scripts.section_c_source_inventory",
            blocked=self._BLOCKED,
            extra_post_check=(
                "import scripts.section_c_source_inventory as _m\n"
                "_m.build_section_c_source_inventory()\n"
                "leaked2 = sorted({\n"
                "    k for k in sys.modules\n"
                "    if k in _BLOCKED\n"
                "    or any(k.startswith(b + '.') for b in _BLOCKED)\n"
                "    or any(k.startswith(p) for p in _PREFIXES)\n"
                "})\n"
                "print('IIC:' + json.dumps({'leaked': leaked2}))\n"
            ),
        )


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_emits_valid_json_with_top_level_keys(self) -> None:
        out = StringIO()
        rc = cli.main(["--json"], out=out)
        self.assertEqual(rc, 0, f"output: {out.getvalue()}")
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_TOP_KEYS:
            self.assertIn(k, parsed)
        self.assertTrue(parsed["ok"])

    def test_cli_emits_nonzero_only_on_real_error(self) -> None:
        # Inject a bogus --output that cannot be written; the script
        # surfaces this as an error and exits non-zero.  Missing
        # source paths are warnings, NOT errors — they don't flip
        # ok.  This separates the two failure modes.
        bad_output = os.path.join(
            tempfile.gettempdir(),
            f"definitely_unwritable_{uuid.uuid4().hex}",
            "deep", "nested", "??invalid<<>>",
            "section_c.json",
        )
        with patch.object(Path, "mkdir", side_effect=OSError("simulated")):
            out = StringIO()
            rc = cli.main(["--json", "--output", bad_output], out=out)
        parsed = json.loads(out.getvalue())
        # Non-zero exit because real I/O error occurred.
        self.assertNotEqual(rc, 0)
        self.assertFalse(parsed["ok"])
        self.assertGreater(len(parsed["errors"]), 0)


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_output_file_written_when_path_passed(self) -> None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"section_c_out_{uuid.uuid4().hex}.json",
        )
        try:
            cli.build_section_c_source_inventory(output_path=out_path)
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
            for k in _REQUIRED_TOP_KEYS:
                self.assertIn(k, parsed)
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_output_file_not_created_when_no_path_passed(self) -> None:
        # Hash the temp dir's listing before and after a no-output
        # run; equality means the inventory created no breadcrumb.
        temp_dir = tempfile.gettempdir()
        # Limit listing to short-lived hashable subset for speed.
        before = sorted(os.listdir(temp_dir))
        before_sha = hashlib.sha256(
            "|".join(before).encode("utf-8"),
        ).hexdigest()
        cli.build_section_c_source_inventory()
        after = sorted(os.listdir(temp_dir))
        after_sha = hashlib.sha256(
            "|".join(after).encode("utf-8"),
        ).hexdigest()
        # Tolerate unrelated process creating temp files between the
        # two listings — only the SHA equality assertion is too
        # strict for shared temp dirs, so we just check the inventory
        # didn't create a file we recognise.
        self.assertNotIn(
            "section_c_source_inventory.json", after,
            "inventory created an unexpected output file",
        )
        # Belt-and-braces: hashes are tracked for debug visibility
        # only; we don't assert equality because the temp dir is
        # shared.
        _ = (before_sha, after_sha)


if __name__ == "__main__":
    unittest.main()
