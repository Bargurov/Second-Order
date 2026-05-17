"""Tests for ``scripts/demo_api_smoke.py``.

The smoke is exercised via three seams:

* The ``fetch`` callable parameter — drives the per-endpoint shape
  check against deterministic ``(status, body_text)`` tuples,
  isolating the test from the FastAPI app entirely.
* ``patch.object`` on the four demo source modules — pins the
  in-process TestClient path against deterministic envelopes so the
  smoke's default mode is exercisable in CI.
* CLI invocation via ``main(["--json"])`` — covers the JSON / text
  rendering and the ``--output`` writer.

Pin the contract:

* Envelope carries EXACTLY these 7 keys::

    ok, base_url, mode, endpoints_checked, results, warnings, errors

* Each result carries EXACTLY these 8 keys::

    path, status_code, ok, section, count, required_keys_present,
    missing_keys, error

* ``mode`` is the literal ``"in_process"`` when no ``--base-url`` is
  supplied, and ``"base_url"`` when one is.
* ``count`` is surfaced as an int when the endpoint body carries one,
  ``None`` otherwise (e.g., Evidence Summary, which has no ``count``).
* HTTP 200 with valid envelope ``items`` + correct ``section`` is the
  shape-OK floor; body-level ``errors`` from the endpoint (e.g.,
  Evidence Summary missing artifact) surface verbatim under
  ``result['error']`` without flipping ``result['ok']``.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import demo_api_smoke as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "base_url",
    "mode",
    "endpoints_checked",
    "results",
    "warnings",
    "errors",
)


_REQUIRED_RESULT_KEYS = (
    "path",
    "status_code",
    "ok",
    "section",
    "count",
    "required_keys_present",
    "missing_keys",
    "error",
)


# ---------------------------------------------------------------------------
# Deterministic per-endpoint payloads.  These mirror the envelope
# shape each source module emits so a passing smoke run requires the
# smoke to follow the same shape contract the production endpoints do.
# ---------------------------------------------------------------------------


def _daily_body(count: int = 1, errors: list | None = None) -> dict[str, Any]:
    return {
        "ok":                not errors,
        "section":           "daily",
        "items":             [],
        "count":             count,
        "skipped_artifacts": [],
        "warnings":          [],
        "errors":            list(errors or []),
    }


def _weekly_body(count: int = 0) -> dict[str, Any]:
    return {
        "ok":                         True,
        "section":                    "weekly",
        "items":                      [],
        "count":                      count,
        "duplicate_groups_collapsed": 0,
        "warnings":                   [],
        "errors":                     [],
    }


def _still_moving_body(count: int = 0) -> dict[str, Any]:
    return {
        "ok":                True,
        "section":           "still_moving",
        "items":             [],
        "count":             count,
        "rejected_count":    0,
        "rejection_summary": {},
        "warnings":          [],
        "errors":            [],
    }


def _evidence_body(*, errors: list | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ok":                           not errors,
        "section":                      "evidence_summary",
        "cohort_summary":               {},
        "verdict_counts":               {},
        "fdr_significant_count":        0,
        "raw_p_candidate_count":        0,
        "benchmark_sensitivity_status": "unknown",
        "limitations":                  [],
        "warnings":                     [],
        "errors":                       list(errors or []),
    }
    return body


_PATH_TO_DEFAULT_BODY: dict[str, Any] = {
    "/demo/daily-market":        _daily_body(count=1),
    "/demo/weekly-market":       _weekly_body(),
    "/demo/still-moving-market": _still_moving_body(),
    "/demo/evidence-summary":    _evidence_body(),
}


def _fake_fetch_factory(bodies: dict[str, dict[str, Any]] | None = None):
    """Build a ``fetch(path) -> (status, body_text)`` callable backed
    by an in-memory ``{path: body_dict}`` table.  Unknown paths
    return ``(404, "")`` so the smoke surfaces the miss without
    crashing.
    """
    table = dict(_PATH_TO_DEFAULT_BODY)
    if bodies:
        table.update(bodies)

    def fetch(path: str) -> tuple[int, str]:
        if path not in table:
            return 404, ""
        return 200, json.dumps(table[path])

    return fetch


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_top_level_keys_exact(self) -> None:
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory())
        self.assertEqual(
            set(envelope.keys()), set(_REQUIRED_ENVELOPE_KEYS),
            f"unexpected envelope keys: {sorted(envelope.keys())}",
        )

    def test_each_result_has_required_keys(self) -> None:
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory())
        self.assertEqual(len(envelope["results"]), 4)
        for r in envelope["results"]:
            self.assertEqual(
                set(r.keys()), set(_REQUIRED_RESULT_KEYS),
                f"unexpected result keys for {r.get('path')}: "
                f"{sorted(r.keys())}",
            )

    def test_endpoints_checked_equals_four(self) -> None:
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory())
        self.assertEqual(envelope["endpoints_checked"], 4)


# ---------------------------------------------------------------------------
# Section value pins
# ---------------------------------------------------------------------------


class TestSectionPins(unittest.TestCase):
    def test_each_endpoint_returns_expected_section(self) -> None:
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory())
        sections = {r["path"]: r["section"] for r in envelope["results"]}
        self.assertEqual(sections["/demo/daily-market"],        "daily")
        self.assertEqual(sections["/demo/weekly-market"],       "weekly")
        self.assertEqual(sections["/demo/still-moving-market"], "still_moving")
        self.assertEqual(sections["/demo/evidence-summary"],    "evidence_summary")

    def test_section_mismatch_surfaces_as_error_and_failure(self) -> None:
        wrong = dict(_PATH_TO_DEFAULT_BODY)
        wrong["/demo/daily-market"] = {**_daily_body(), "section": "weekly"}
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory(wrong))
        result = next(
            r for r in envelope["results"]
            if r["path"] == "/demo/daily-market"
        )
        self.assertFalse(result["ok"])
        self.assertIn("section_mismatch", result["error"] or "")
        self.assertFalse(envelope["ok"])


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath(unittest.TestCase):
    def test_all_four_results_pass_when_bodies_are_well_shaped(self) -> None:
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory())
        self.assertTrue(envelope["ok"], envelope)
        for r in envelope["results"]:
            self.assertTrue(
                r["ok"], f"{r['path']} failed: {r['error']}",
            )
            self.assertEqual(r["status_code"], 200)
            self.assertEqual(r["missing_keys"], [])
            self.assertTrue(r["required_keys_present"])

    def test_count_surfaced_when_endpoint_carries_it(self) -> None:
        bodies = dict(_PATH_TO_DEFAULT_BODY)
        bodies["/demo/daily-market"] = _daily_body(count=7)
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory(bodies))
        daily = next(
            r for r in envelope["results"]
            if r["path"] == "/demo/daily-market"
        )
        self.assertEqual(daily["count"], 7)

    def test_count_is_none_for_evidence_summary(self) -> None:
        # Evidence Summary's contract has no ``count`` field.  The
        # smoke must surface ``count=None`` instead of inventing one.
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory())
        evidence = next(
            r for r in envelope["results"]
            if r["path"] == "/demo/evidence-summary"
        )
        self.assertIsNone(evidence["count"])


# ---------------------------------------------------------------------------
# Empty Daily — not a failure
# ---------------------------------------------------------------------------


class TestEmptyDailyIsNotFailure(unittest.TestCase):
    def test_zero_count_daily_keeps_result_ok_true(self) -> None:
        bodies = dict(_PATH_TO_DEFAULT_BODY)
        bodies["/demo/daily-market"] = _daily_body(count=0)
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory(bodies))
        daily = next(
            r for r in envelope["results"]
            if r["path"] == "/demo/daily-market"
        )
        self.assertEqual(daily["count"], 0)
        self.assertTrue(daily["ok"])
        self.assertIsNone(daily["error"])
        self.assertTrue(envelope["ok"])


# ---------------------------------------------------------------------------
# Endpoint-declared errors — surfaced without crashing
# ---------------------------------------------------------------------------


class TestEndpointErrorsSurfacedNotCrashed(unittest.TestCase):
    def test_evidence_missing_artifact_error_surfaces_in_result_error(self) -> None:
        bodies = dict(_PATH_TO_DEFAULT_BODY)
        bodies["/demo/evidence-summary"] = _evidence_body(
            errors=["evidence artifact not found at artifacts/...json"],
        )
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory(bodies))
        evidence = next(
            r for r in envelope["results"]
            if r["path"] == "/demo/evidence-summary"
        )
        self.assertEqual(evidence["status_code"], 200)
        # Envelope shape is still valid (all required keys present
        # + correct section) so result['ok'] stays True.
        self.assertTrue(evidence["ok"])
        self.assertTrue(evidence["required_keys_present"])
        self.assertIn("evidence artifact not found", evidence["error"] or "")


# ---------------------------------------------------------------------------
# Bad-response shape handling
# ---------------------------------------------------------------------------


class TestBadResponseShape(unittest.TestCase):
    def test_non_200_surfaces_as_unexpected_status(self) -> None:
        def fetch(path: str) -> tuple[int, str]:
            return 503, '{"error": "down"}'

        envelope = cli.run_demo_api_smoke(fetch=fetch)
        self.assertFalse(envelope["ok"])
        for r in envelope["results"]:
            self.assertEqual(r["status_code"], 503)
            self.assertFalse(r["ok"])
            self.assertIn("unexpected_status", r["error"] or "")

    def test_non_json_body_surfaces_as_decode_failure(self) -> None:
        def fetch(path: str) -> tuple[int, str]:
            return 200, "<html>not json</html>"

        envelope = cli.run_demo_api_smoke(fetch=fetch)
        self.assertFalse(envelope["ok"])
        for r in envelope["results"]:
            self.assertEqual(r["status_code"], 200)
            self.assertFalse(r["ok"])
            self.assertIn("json_decode_failed", r["error"] or "")

    def test_missing_required_key_surfaces_in_missing_keys(self) -> None:
        bodies = dict(_PATH_TO_DEFAULT_BODY)
        broken = _weekly_body()
        broken.pop("duplicate_groups_collapsed")
        bodies["/demo/weekly-market"] = broken
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory(bodies))
        weekly = next(
            r for r in envelope["results"]
            if r["path"] == "/demo/weekly-market"
        )
        self.assertFalse(weekly["ok"])
        self.assertIn("duplicate_groups_collapsed", weekly["missing_keys"])
        self.assertFalse(weekly["required_keys_present"])

    def test_fetch_exception_surfaces_as_fetch_failed(self) -> None:
        def fetch(path: str) -> tuple[int, str]:
            raise ConnectionError("simulated network failure")

        envelope = cli.run_demo_api_smoke(fetch=fetch)
        self.assertFalse(envelope["ok"])
        for r in envelope["results"]:
            self.assertIsNone(r["status_code"])
            self.assertFalse(r["ok"])
            self.assertIn("fetch_failed", r["error"] or "")


# ---------------------------------------------------------------------------
# Mode field
# ---------------------------------------------------------------------------


class TestModeField(unittest.TestCase):
    def test_default_mode_is_in_process(self) -> None:
        envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory())
        self.assertEqual(envelope["mode"], "in_process")
        self.assertEqual(envelope["base_url"], "")

    def test_base_url_mode_is_reported(self) -> None:
        envelope = cli.run_demo_api_smoke(
            base_url="http://127.0.0.1:9999",
            fetch=_fake_fetch_factory(),
        )
        self.assertEqual(envelope["mode"], "base_url")
        self.assertEqual(envelope["base_url"], "http://127.0.0.1:9999")


# ---------------------------------------------------------------------------
# In-process TestClient mode — exercise the default path with the
# demo source modules patched to deterministic envelopes.
# ---------------------------------------------------------------------------


class TestInProcessTestClientPath(unittest.TestCase):
    def test_in_process_mode_runs_against_patched_app(self) -> None:
        import api  # noqa: PLC0415

        with patch.object(
            api._demo_daily_mod, "build_demo_daily_market",
            return_value=_daily_body(count=2),
        ), patch.object(
            api._demo_weekly_mod, "build_demo_weekly_market",
            return_value=_weekly_body(count=3),
        ), patch.object(
            api._demo_still_moving_mod, "build_demo_still_moving_market",
            return_value=_still_moving_body(count=1),
        ), patch.object(
            api._demo_evidence_summary_mod, "build_demo_evidence_summary",
            return_value=_evidence_body(),
        ), patch.object(
            api.movers_cache, "get_slice",
            return_value=[],
        ):
            envelope = cli.run_demo_api_smoke()
        self.assertEqual(envelope["mode"], "in_process")
        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(envelope["endpoints_checked"], 4)
        counts = {r["path"]: r["count"] for r in envelope["results"]}
        self.assertEqual(counts["/demo/daily-market"],        2)
        self.assertEqual(counts["/demo/weekly-market"],       3)
        self.assertEqual(counts["/demo/still-moving-market"], 1)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_json_emits_valid_envelope(self) -> None:
        with patch.object(
            cli, "run_demo_api_smoke",
            return_value=cli.run_demo_api_smoke(fetch=_fake_fetch_factory()),
        ):
            out = StringIO()
            rc = cli.main(["--json"], out=out)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_ENVELOPE_KEYS:
            self.assertIn(k, parsed)
        self.assertEqual(rc, 0)
        self.assertTrue(parsed["ok"])

    def test_cli_text_render_does_not_crash(self) -> None:
        with patch.object(
            cli, "run_demo_api_smoke",
            return_value=cli.run_demo_api_smoke(fetch=_fake_fetch_factory()),
        ):
            out = StringIO()
            rc = cli.main([], out=out)
        text = out.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Demo API smoke", text)
        self.assertIn("/demo/daily-market",        text)
        self.assertIn("/demo/weekly-market",       text)
        self.assertIn("/demo/still-moving-market", text)
        self.assertIn("/demo/evidence-summary",    text)

    def test_cli_nonzero_exit_on_failed_endpoint(self) -> None:
        bad = dict(_PATH_TO_DEFAULT_BODY)
        bad["/demo/daily-market"] = {**_daily_body(), "section": "wrong"}

        # Pre-compute the bad envelope through the real implementation
        # so the patched ``run_demo_api_smoke`` can just return it —
        # patching it to call itself recursively (``cli.run_demo_api_smoke``)
        # would re-enter the mock and recurse forever.
        bad_envelope = cli.run_demo_api_smoke(fetch=_fake_fetch_factory(bad))
        self.assertFalse(bad_envelope["ok"])

        with patch.object(
            cli, "run_demo_api_smoke", return_value=bad_envelope,
        ):
            out = StringIO()
            rc = cli.main(["--json"], out=out)
        self.assertEqual(rc, 1)

    def test_cli_output_path_writes_json_and_refuses_overwrite(self) -> None:
        with patch.object(
            cli, "run_demo_api_smoke",
            return_value=cli.run_demo_api_smoke(fetch=_fake_fetch_factory()),
        ):
            out_path = os.path.join(
                tempfile.gettempdir(),
                f"demo_api_smoke_{uuid.uuid4().hex}.json",
            )
            try:
                # First write succeeds.
                out = StringIO()
                rc = cli.main(["--json", "--output", out_path], out=out)
                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(out_path))
                with open(out_path, "r", encoding="utf-8") as fh:
                    parsed = json.load(fh)
                self.assertTrue(parsed["ok"])
                # Second write refuses to overwrite.
                out2 = StringIO()
                rc2 = cli.main(["--json", "--output", out_path], out=out2)
                self.assertEqual(rc2, 1)
                parsed2 = json.loads(out2.getvalue())
                self.assertFalse(parsed2["ok"])
                self.assertTrue(
                    any("refusing to overwrite" in e for e in parsed2["errors"]),
                    f"errors: {parsed2['errors']}",
                )
            finally:
                if os.path.exists(out_path):
                    os.unlink(out_path)


# ---------------------------------------------------------------------------
# Import isolation — no provider / LLM / network pulled in at module load
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = (
        "yfinance",
        "market_data",
        # ``urllib`` is allowed (stdlib HTTP for --base-url mode), but
        # the smoke must not pull in ``api`` / ``fastapi`` at module
        # load — those are lazily imported only when the in-process
        # fetch factory is built.
        "api",
        "fastapi",
    )

    def test_module_import_does_not_pull_provider_fastapi_or_api(self) -> None:
        from tests._import_isolation_check import (  # noqa: PLC0415
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name="scripts.demo_api_smoke",
            blocked=self._BLOCKED,
        )


if __name__ == "__main__":
    unittest.main()
