"""Tests for ``scripts/xle_online_backfill_preview.py``.

The XLE online backfill preview fetches the exact missing XLE dates
from the benchmark backfill request packet into a TEMP DB copy and
re-runs the benchmark-sensitivity preflight before / after so the
operator can see whether events 60 and 73 become benchmark-ready
WITHOUT touching the live DB.

Pin the contract:

* Read-only against the live DB — hashed before / after; the
  preview never opens the live DB for writes.
* The online market-data fetch fires ONLY when the operator passes
  ``--confirm-online``.  Without that flag the script does not call
  a provider, does not copy the live DB, and emits ``ok=False`` with
  a clear error.
* The fetch surface is a patchable seam (``_fetch_xle_rows_online``)
  so tests never invoke a real network call.
* Fetches ONLY ticker ``XLE`` and ONLY the dates listed in the
  request packet's ``required_dates`` — never any other ticker, never
  dates outside the list.
* No fabricated prices — every inserted temp row carries the close
  the provider returned.
* Output dict carries EXACTLY these 16 keys::

    ok, confirm_online, required_dates, fetched_rows,
    inserted_temp_rows, preflight_before, preflight_after,
    ready_before, ready_after, blocked_before, blocked_after,
    still_missing_dates, live_db_unchanged, warnings, errors,
    recommended_next_action

* Conservative wording — banned tokens (``proof``, ``proves``,
  ``alpha``, ``guaranteed``, ``automatically``,
  ``definitely validated``) absent from any text the preview emits.
  The preview never asserts an SPY-vs-XLE conclusion.
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

from scripts import xle_online_backfill_preview as cli  # noqa: E402


_REQUIRED_KEYS = (
    "ok",
    "confirm_online",
    "required_dates",
    "fetched_rows",
    "inserted_temp_rows",
    "preflight_before",
    "preflight_after",
    "ready_before",
    "ready_after",
    "blocked_before",
    "blocked_after",
    "still_missing_dates",
    "live_db_unchanged",
    "warnings",
    "errors",
    "recommended_next_action",
)


_BANNED_WORDS = (
    "proof",
    "proves",
    "alpha",
    "guaranteed",
    "automatically",
    "definitely validated",
    "is proven",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_PRICE_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()


def _make_fixture_db() -> str:
    """Create a minimal events.db-shaped fixture file with just the
    price_cache table.  The preflight seam is patched in tests so we
    don't need events / curated_candidates here — the temp copy of
    this file is what the INSERT seam writes against.
    """
    path = os.path.join(
        tempfile.gettempdir(),
        f"xle_online_fix_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(_PRICE_CACHE_DDL)
        conn.commit()
    finally:
        conn.close()
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _packet(*, required_dates: list[str] | None = None) -> dict[str, Any]:
    """Synthetic request-packet payload — mirrors the shape returned
    by ``build_xle_benchmark_backfill_request_packet``.
    """
    dates = list(required_dates or [])
    return {
        "ok":               True,
        "benchmark_ticker": "XLE",
        "blocked_events":   [
            {"event_id": 60, "event_date": "2026-04-08",
             "primary_ticker": "XOM", "benchmark_ticker": "XLE",
             "blocker_reason": "missing_estimation_window"},
            {"event_id": 73, "event_date": "2026-04-06",
             "primary_ticker": "XOM", "benchmark_ticker": "XLE",
             "blocker_reason": "missing_estimation_window"},
        ],
        "required_dates":   dates,
        "date_ranges":      [],
        "reason":           "estimation_window_short",
        "warnings":         [],
        "errors":           [],
    }


def _preflight_report(
    *, ready: int, blocked: int,
) -> dict[str, Any]:
    """Synthetic preflight summary payload."""
    return {
        "ok":             True,
        "checked_events": ready + blocked,
        "ready_count":    ready,
        "blocked_count":  blocked,
        "rows":           [],
        "recommended_next_action": "synthetic",
    }


def _provider_row(
    *, date: str, close: float = 100.0, volume: float = 1.0e6,
) -> dict[str, Any]:
    return {
        "ticker":     "XLE",
        "date":       date,
        "close":      close,
        "volume":     volume,
        "auto_adjust": 1,
        "fetched_at": "2026-05-12T00:00:00+00:00",
    }


class _PreflightSeam:
    """Returns a sequence of preflight payloads on successive calls.

    Used to drive ``preflight_before`` and ``preflight_after`` from a
    single test fixture so the test pinpoints the before/after split.
    """

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = list(payloads)
        self.call_count = 0

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        idx = min(self.call_count, len(self._payloads) - 1)
        self.call_count += 1
        return self._payloads[idx]


# ---------------------------------------------------------------------------
# --confirm-online gate
# ---------------------------------------------------------------------------


class TestConfirmOnlineGate(unittest.TestCase):
    def test_without_confirm_online_returns_ok_false_with_clear_error(
        self,
    ) -> None:
        # No --confirm-online → no copy, no fetch, no insert.  The
        # envelope must still surface required_dates from the packet
        # so the operator sees what would be needed.
        with patch.object(
            cli, "_build_request_packet",
            return_value=_packet(required_dates=["2026-01-12", "2026-01-13"]),
        ) as packet_seam, patch.object(
            cli, "_copy_live_db_to_temp",
        ) as copy_seam, patch.object(
            cli, "_fetch_xle_rows_online",
        ) as fetch_seam:
            report = cli.run_xle_online_backfill_preview(
                confirm_online=False, db_path=None,
            )
        self.assertFalse(report["ok"])
        self.assertFalse(report["confirm_online"])
        self.assertEqual(report["required_dates"],
                         ["2026-01-12", "2026-01-13"])
        # Error message must explicitly cite --confirm-online so the
        # operator knows the fix.
        joined = " ".join(report["errors"]).lower()
        self.assertIn("confirm-online", joined,
                      f"errors: {report['errors']}")
        # No copy, no fetch.
        copy_seam.assert_not_called()
        fetch_seam.assert_not_called()
        # Packet seam DOES run — it's read-only, no network.
        self.assertEqual(packet_seam.call_count, 1)

    def test_without_confirm_online_live_db_unchanged_true(self) -> None:
        with patch.object(
            cli, "_build_request_packet",
            return_value=_packet(required_dates=[]),
        ):
            report = cli.run_xle_online_backfill_preview(
                confirm_online=False, db_path=None,
            )
        # The script never touched the live DB → unchanged is True
        # (vacuously when no path is supplied).
        self.assertTrue(report["live_db_unchanged"])


# ---------------------------------------------------------------------------
# --confirm-online flow — full preview pipeline
# ---------------------------------------------------------------------------


class TestConfirmOnlineFlow(unittest.TestCase):
    def test_full_flow_runs_when_confirm_online_is_set(self) -> None:
        fixture = _make_fixture_db()
        try:
            preflight = _PreflightSeam([
                _preflight_report(ready=0, blocked=2),
                _preflight_report(ready=2, blocked=0),
            ])
            dates = ["2026-01-12", "2026-01-13", "2026-01-14"]
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=dates),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date=d) for d in dates], []),
            ) as fetch_seam, patch.object(
                cli, "_run_preflight",
                side_effect=preflight,
            ):
                report = cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
            self.assertTrue(report["confirm_online"])
            self.assertTrue(report["ok"], report.get("errors"))
            self.assertEqual(report["required_dates"], dates)
            self.assertEqual(report["fetched_rows"], 3)
            self.assertEqual(report["inserted_temp_rows"], 3)
            # Both preflights ran (before + after).
            self.assertEqual(preflight.call_count, 2)
            self.assertEqual(report["ready_before"],   0)
            self.assertEqual(report["blocked_before"], 2)
            self.assertEqual(report["ready_after"],    2)
            self.assertEqual(report["blocked_after"],  0)
            self.assertEqual(report["still_missing_dates"], [])
            # Fetch seam called with the required_dates list verbatim.
            self.assertEqual(fetch_seam.call_count, 1)
            self.assertEqual(
                fetch_seam.call_args.kwargs.get("dates"), dates,
            )
        finally:
            os.unlink(fixture)

    def test_fetch_only_xle_and_only_required_dates(self) -> None:
        # Pin the constraint: even when the seam is patched, the
        # caller must invoke it with EXACTLY the required_dates from
        # the packet — never additional dates, never a wildcard.
        fixture = _make_fixture_db()
        try:
            dates = ["2026-01-15", "2026-01-16"]
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=dates),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date=d) for d in dates], []),
            ) as fetch_seam, patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=2, blocked=0),
                ]),
            ):
                cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
            kwargs = fetch_seam.call_args.kwargs
            self.assertEqual(kwargs["dates"], dates,
                             "fetch seam must receive only required_dates")
        finally:
            os.unlink(fixture)


# ---------------------------------------------------------------------------
# Temp DB insertion
# ---------------------------------------------------------------------------


class TestTempDbInsertion(unittest.TestCase):
    def test_inserted_rows_land_in_temp_price_cache(self) -> None:
        fixture = _make_fixture_db()
        captured_temp_path: dict[str, str] = {}

        def fake_preflight(**kwargs):
            captured_temp_path["path"] = kwargs.get("db_path") or ""
            return _preflight_report(ready=0, blocked=2)

        try:
            dates = ["2026-01-20", "2026-01-21"]
            rows = [_provider_row(date=d, close=42.0 + i)
                    for i, d in enumerate(dates)]
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=dates),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=(rows, []),
            ), patch.object(
                cli, "_run_preflight", side_effect=fake_preflight,
            ):
                report = cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
            self.assertTrue(report["ok"], report.get("errors"))
            temp_path = captured_temp_path["path"]
            self.assertNotEqual(temp_path, fixture,
                                "preflight must run on the temp copy")
            conn = sqlite3.connect(temp_path)
            try:
                fetched = conn.execute(
                    "SELECT ticker, date, close FROM price_cache "
                    "WHERE ticker='XLE' ORDER BY date"
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual(len(fetched), 2)
            self.assertEqual({r[1] for r in fetched}, set(dates))
            self.assertEqual({r[0] for r in fetched}, {"XLE"})
        finally:
            os.unlink(fixture)


# ---------------------------------------------------------------------------
# still_missing_dates — provider returns fewer rows than requested
# ---------------------------------------------------------------------------


class TestStillMissingDates(unittest.TestCase):
    def test_dates_with_no_provider_row_surface_as_still_missing(
        self,
    ) -> None:
        fixture = _make_fixture_db()
        try:
            dates = ["2026-01-12", "2026-01-13", "2026-01-14"]
            # Provider returns rows for the first two only.
            partial = [
                _provider_row(date="2026-01-12"),
                _provider_row(date="2026-01-13"),
            ]
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=dates),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=(partial, []),
            ), patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=1, blocked=1),
                ]),
            ):
                report = cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
            self.assertEqual(report["fetched_rows"], 2)
            self.assertEqual(report["still_missing_dates"], ["2026-01-14"])
            # Conservative: surface still-missing without claiming
            # validation cannot proceed; the recommendation handles
            # the verdict.
            self.assertGreater(report["inserted_temp_rows"], 0)
        finally:
            os.unlink(fixture)

    def test_empty_provider_response_marks_every_required_date_missing(
        self,
    ) -> None:
        fixture = _make_fixture_db()
        try:
            dates = ["2026-01-12", "2026-01-13"]
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=dates),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([], []),
            ), patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=0, blocked=2),
                ]),
            ):
                report = cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
            self.assertEqual(report["fetched_rows"], 0)
            self.assertEqual(report["inserted_temp_rows"], 0)
            self.assertEqual(sorted(report["still_missing_dates"]),
                             sorted(dates))
        finally:
            os.unlink(fixture)


# ---------------------------------------------------------------------------
# Live DB byte identity
# ---------------------------------------------------------------------------


class TestLiveDbByteIdentity(unittest.TestCase):
    def test_live_db_bytes_unchanged_after_full_flow(self) -> None:
        fixture = _make_fixture_db()
        try:
            before = _sha256(fixture)
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=["2026-01-12"]),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-01-12")], []),
            ), patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=2, blocked=0),
                ]),
            ):
                report = cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
            after = _sha256(fixture)
            self.assertEqual(before, after,
                             "live DB bytes mutated by preview")
            self.assertTrue(report["live_db_unchanged"])
        finally:
            os.unlink(fixture)


# ---------------------------------------------------------------------------
# Empty required_dates — short-circuit but still ok=True
# ---------------------------------------------------------------------------


class TestEmptyRequiredDates(unittest.TestCase):
    def test_no_required_dates_short_circuits_without_fetch(self) -> None:
        fixture = _make_fixture_db()
        try:
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=[]),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
            ) as fetch_seam, patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=2, blocked=0),
                    _preflight_report(ready=2, blocked=0),
                ]),
            ):
                report = cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
            self.assertTrue(report["ok"])
            self.assertEqual(report["required_dates"], [])
            self.assertEqual(report["fetched_rows"], 0)
            self.assertEqual(report["inserted_temp_rows"], 0)
            self.assertEqual(report["still_missing_dates"], [])
            fetch_seam.assert_not_called()
        finally:
            os.unlink(fixture)


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_envelope_has_exactly_required_keys(self) -> None:
        with patch.object(
            cli, "_build_request_packet",
            return_value=_packet(required_dates=[]),
        ):
            report = cli.run_xle_online_backfill_preview(
                confirm_online=False, db_path=None,
            )
        self.assertEqual(set(report.keys()), set(_REQUIRED_KEYS),
                         f"unexpected keys: {sorted(report.keys())}")


# ---------------------------------------------------------------------------
# Recommended next action
# ---------------------------------------------------------------------------


class TestRecommendedNextAction(unittest.TestCase):
    def test_without_confirm_online_points_to_the_flag(self) -> None:
        with patch.object(
            cli, "_build_request_packet",
            return_value=_packet(required_dates=["2026-01-12"]),
        ):
            report = cli.run_xle_online_backfill_preview(
                confirm_online=False, db_path=None,
            )
        action = report["recommended_next_action"].lower()
        self.assertIn("--confirm-online", action,
                      f"action: {action!r}")

    def test_full_unblock_recommends_inspect_then_freeze_or_extend(
        self,
    ) -> None:
        fixture = _make_fixture_db()
        try:
            dates = ["2026-01-12"]
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=dates),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-01-12")], []),
            ), patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=2, blocked=0),
                ]),
            ):
                report = cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
            action = report["recommended_next_action"].lower()
            # Mention that events became benchmark-ready in the temp
            # preview — operator can decide next step.
            self.assertIn("benchmark-ready", action,
                          f"action: {action!r}")
        finally:
            os.unlink(fixture)

    def test_still_missing_dates_mentioned_in_recommendation(self) -> None:
        fixture = _make_fixture_db()
        try:
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(
                    required_dates=["2026-01-12", "2026-01-13"],
                ),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([], []),
            ), patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=0, blocked=2),
                ]),
            ):
                report = cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
            action = report["recommended_next_action"].lower()
            self.assertIn("still", action, f"action: {action!r}")
        finally:
            os.unlink(fixture)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_no_banned_tokens_in_any_text_field(self) -> None:
        fixture = _make_fixture_db()
        try:
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=["2026-01-12"]),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-01-12")], []),
            ), patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=2, blocked=0),
                ]),
            ):
                report = cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
            haystack = " ".join(
                list(report["errors"])
                + list(report["warnings"])
                + [report["recommended_next_action"]]
            ).lower()
            for w in _BANNED_WORDS:
                self.assertNotIn(w, haystack,
                                 f"banned word {w!r} in preview text")
        finally:
            os.unlink(fixture)

    def test_no_spy_vs_xle_conclusion_in_recommendation(self) -> None:
        # The spec forbids inferring an SPY-vs-XLE sensitivity verdict
        # before the missing rows exist.  The recommendation must
        # neither claim XLE is "better" / "worse" than SPY nor declare
        # a benchmark sensitivity result.
        fixture = _make_fixture_db()
        try:
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=["2026-01-12"]),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-01-12")], []),
            ), patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=2, blocked=0),
                ]),
            ):
                report = cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
            action = report["recommended_next_action"].lower()
            for forbidden in (
                "spy is better than xle",
                "xle is better than spy",
                "spy outperforms",
                "xle outperforms",
                "spy beats xle",
                "xle beats spy",
            ):
                self.assertNotIn(forbidden, action,
                                 f"premature verdict in action: {action!r}")
        finally:
            os.unlink(fixture)


# ---------------------------------------------------------------------------
# Promotion-gate wording (post calendar fix)
# ---------------------------------------------------------------------------


class TestPromotionGateWording(unittest.TestCase):
    """The preview is a *temp-only* exercise.  Whether it cleared or
    not, the recommendation must steer the operator unambiguously
    toward (or away from) live promotion.

    * All cleared (ready_after = checked, blocked_after = 0):
      mention live promotion AND a backup AND an explicit, separate
      live-confirmation step.  Conservative language — no claims
      that the preview "proves" anything.

    * Still blocked (blocked_after > 0): explicit do-not-promote
      direction and a pointer to inspect the per-event blockers.
    """

    def _run_all_cleared(self) -> dict[str, Any]:
        fixture = _make_fixture_db()
        try:
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=["2026-01-12"]),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-01-12")], []),
            ), patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=2, blocked=0),
                ]),
            ):
                return cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
        finally:
            os.unlink(fixture)

    def _run_still_blocked(self) -> dict[str, Any]:
        fixture = _make_fixture_db()
        try:
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(
                    required_dates=["2026-01-12", "2026-01-13"],
                ),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-01-12")], []),
            ), patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=1, blocked=1),
                ]),
            ):
                return cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                )
        finally:
            os.unlink(fixture)

    def test_all_cleared_mentions_live_promotion(self) -> None:
        report = self._run_all_cleared()
        self.assertEqual(report["ready_after"],   2)
        self.assertEqual(report["blocked_after"], 0)
        action = report["recommended_next_action"].lower()
        self.assertIn("live promotion", action, f"action: {action!r}")

    def test_all_cleared_mentions_backup(self) -> None:
        report = self._run_all_cleared()
        action = report["recommended_next_action"].lower()
        self.assertIn("backup", action, f"action: {action!r}")

    def test_all_cleared_mentions_explicit_live_confirmation(self) -> None:
        # An explicit live-confirmation flag must be flagged as a
        # separate gate so a casual rerun cannot promote by accident.
        report = self._run_all_cleared()
        action = report["recommended_next_action"].lower()
        self.assertIn("live-confirmation", action, f"action: {action!r}")

    def test_all_cleared_does_not_assert_proof(self) -> None:
        # Conservative language guard, restated here so the intent
        # behind the new wording is pinned alongside the wording itself.
        report = self._run_all_cleared()
        action = report["recommended_next_action"].lower()
        for banned in ("proof", "proves", "proven"):
            self.assertNotIn(banned, action, f"action: {action!r}")

    def test_still_blocked_explicitly_forbids_live_promotion(self) -> None:
        report = self._run_still_blocked()
        self.assertGreater(report["blocked_after"], 0)
        action = report["recommended_next_action"].lower()
        self.assertIn("do not promote", action, f"action: {action!r}")

    def test_still_blocked_points_at_blockers(self) -> None:
        report = self._run_still_blocked()
        action = report["recommended_next_action"].lower()
        self.assertIn("blocker", action, f"action: {action!r}")
        # And the existing 'still_missing_dates' pointer is preserved.
        self.assertIn("still_missing_dates", action, f"action: {action!r}")


# ---------------------------------------------------------------------------
# Import isolation — no provider / FastAPI by default
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = ("yfinance", "fastapi", "api", "market_data")

    def test_module_import_does_not_pull_provider(self) -> None:
        # Subprocess-isolated: an in-process scan reads sys.modules
        # state polluted by prior tests in the same discovery run.
        from tests._import_isolation_check import (
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name="scripts.xle_online_backfill_preview",
            blocked=self._BLOCKED,
        )

    def test_without_confirm_online_provider_seam_never_called(
        self,
    ) -> None:
        with patch.object(
            cli, "_build_request_packet",
            return_value=_packet(required_dates=["2026-01-12"]),
        ), patch.object(
            cli, "_fetch_xle_rows_online",
        ) as fetch_seam:
            cli.run_xle_online_backfill_preview(
                confirm_online=False, db_path=None,
            )
        fetch_seam.assert_not_called()


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------


class TestOutputFile(unittest.TestCase):
    def test_output_file_written_when_path_passed(self) -> None:
        fixture = _make_fixture_db()
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"xle_online_out_{uuid.uuid4().hex}.json",
        )
        try:
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=["2026-01-12"]),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-01-12")], []),
            ), patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=2, blocked=0),
                ]),
            ):
                cli.run_xle_online_backfill_preview(
                    confirm_online=True, db_path=fixture,
                    output_path=out_path,
                )
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
            for k in _REQUIRED_KEYS:
                self.assertIn(k, parsed)
        finally:
            os.unlink(fixture)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_output_file_written_on_failure_envelope_too(self) -> None:
        out_path = os.path.join(
            tempfile.gettempdir(),
            f"xle_online_fail_{uuid.uuid4().hex}.json",
        )
        try:
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=["2026-01-12"]),
            ):
                report = cli.run_xle_online_backfill_preview(
                    confirm_online=False, db_path=None,
                    output_path=out_path,
                )
            self.assertFalse(report["ok"])
            self.assertTrue(os.path.exists(out_path))
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_cli_without_confirm_online_returns_nonzero_and_valid_json(
        self,
    ) -> None:
        with patch.object(
            cli, "_build_request_packet",
            return_value=_packet(required_dates=["2026-01-12"]),
        ):
            out = StringIO()
            rc = cli.main(["--json"], out=out)
        self.assertNotEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        for k in _REQUIRED_KEYS:
            self.assertIn(k, parsed)
        self.assertFalse(parsed["ok"])
        self.assertFalse(parsed["confirm_online"])

    def test_cli_with_confirm_online_runs_full_flow(self) -> None:
        fixture = _make_fixture_db()
        try:
            with patch.object(
                cli, "_build_request_packet",
                return_value=_packet(required_dates=["2026-01-12"]),
            ), patch.object(
                cli, "_fetch_xle_rows_online",
                return_value=([_provider_row(date="2026-01-12")], []),
            ), patch.object(
                cli, "_run_preflight",
                side_effect=_PreflightSeam([
                    _preflight_report(ready=0, blocked=2),
                    _preflight_report(ready=2, blocked=0),
                ]),
            ):
                out = StringIO()
                rc = cli.main(
                    ["--json", "--confirm-online",
                     "--db-path", fixture],
                    out=out,
                )
            self.assertEqual(rc, 0, f"output: {out.getvalue()}")
            parsed = json.loads(out.getvalue())
            self.assertTrue(parsed["ok"])
            self.assertTrue(parsed["confirm_online"])
            self.assertEqual(parsed["fetched_rows"], 1)
        finally:
            os.unlink(fixture)


if __name__ == "__main__":
    unittest.main()
