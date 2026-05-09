"""Tests for the ``portfolio_view`` saved-study type.

Covers:
  * save → read round-trip with mover filters
  * update-by-id does not recreate rows (rename preserves the id)
  * research export honours mover_window + queue filters
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _isolated_db() -> tuple[str, dict[str, str]]:
    """Create a fresh sqlite file, initialise the saved_studies schema,
    and point the module-level ``DB_FILE`` at it.

    Returns ``(path, originals)`` — ``path`` is the per-test sqlite
    file the test should ``os.unlink`` in tearDown; ``originals`` is
    the snapshot of ``db.DB_FILE`` and ``saved_studies.DB_FILE`` taken
    BEFORE the swap so tearDown can restore them via
    :func:`_restore_db_constants`.

    Restoration matters because ``tests/conftest.py`` redirects
    ``db.DB_FILE`` (and the snapshot modules' copies) to a per-session
    temp path at collection time.  A test that swaps without
    restoring leaks its per-test temp path into the session module
    state — every subsequent test then sees ``db.DB_FILE`` pointing at
    a deleted file, while the snapshot modules still hold the session
    path.  ``test_test_db_isolation`` pins this contract.
    """
    import db
    import saved_studies as _ss
    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_portfolio_view_")
    os.close(fd)
    originals = {
        "db.DB_FILE":            db.DB_FILE,
        "saved_studies.DB_FILE": _ss.DB_FILE,
    }
    db.DB_FILE = path
    _ss.DB_FILE = path
    db.init_db()
    return path, originals


def _restore_db_constants(originals: dict[str, str]) -> None:
    """Restore ``db.DB_FILE`` and ``saved_studies.DB_FILE`` to the
    snapshot taken in :func:`_isolated_db`.  See that helper's
    docstring for why restoration is required."""
    import db
    import saved_studies as _ss
    db.DB_FILE     = originals["db.DB_FILE"]
    _ss.DB_FILE    = originals["saved_studies.DB_FILE"]


# ---------------------------------------------------------------------------
# Validator — closed-key config, per-filter enum validation
# ---------------------------------------------------------------------------

class TestValidator(unittest.TestCase):
    def test_empty_config_is_valid(self):
        from saved_studies import _validate_config
        self.assertEqual(_validate_config("portfolio_view", {}), {})

    def test_all_filters_round_trip(self):
        from saved_studies import _validate_config
        out = _validate_config("portfolio_view", {
            "mover_window":    "weekly",
            "queue":           "watch_falsifiers",
            "thesis_state":    "confirming",
            "proof_quality":   "proof_backed",
            "low_information": False,
        })
        self.assertEqual(out, {
            "mover_window":    "weekly",
            "queue":           "watch_falsifiers",
            "thesis_state":    "confirming",
            "proof_quality":   "proof_backed",
            "low_information": False,
        })

    def test_unknown_key_rejected(self):
        from saved_studies import _validate_config
        with self.assertRaises(ValueError):
            _validate_config("portfolio_view", {"not_a_filter": "x"})

    def test_bad_mover_window_rejected(self):
        from saved_studies import _validate_config
        with self.assertRaises(ValueError):
            _validate_config("portfolio_view", {"mover_window": "yearly"})

    def test_bad_queue_rejected(self):
        from saved_studies import _validate_config
        with self.assertRaises(ValueError):
            _validate_config("portfolio_view", {"queue": "not_a_queue"})

    def test_bad_thesis_state_rejected(self):
        from saved_studies import _validate_config
        with self.assertRaises(ValueError):
            _validate_config("portfolio_view", {"thesis_state": "mystery"})

    def test_bad_proof_quality_rejected(self):
        from saved_studies import _validate_config
        with self.assertRaises(ValueError):
            _validate_config("portfolio_view", {"proof_quality": "mystery"})

    def test_bad_low_information_rejected(self):
        from saved_studies import _validate_config
        with self.assertRaises(ValueError):
            _validate_config("portfolio_view", {"low_information": "yes"})

    def test_empty_string_filter_is_dropped(self):
        """Empty-string filters from form posts should be treated as
        "no filter", not rejected."""
        from saved_studies import _validate_config
        out = _validate_config("portfolio_view", {
            "mover_window": "", "queue": "",
            "thesis_state": "", "proof_quality": "",
        })
        self.assertEqual(out, {})


# ---------------------------------------------------------------------------
# Save → read round-trip
# ---------------------------------------------------------------------------

class TestSaveReadRoundTrip(unittest.TestCase):
    def setUp(self):
        self.db_path, self._db_originals = _isolated_db()

    def tearDown(self):
        _restore_db_constants(self._db_originals)
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_round_trip_mover_filters(self):
        from saved_studies import load_study, save_study
        stored = save_study(
            "portfolio_view",
            "Confirming weekly view",
            {
                "mover_window":    "weekly",
                "queue":           "confirming_now",
                "thesis_state":    "confirming",
                "proof_quality":   "proof_backed",
                "low_information": False,
            },
        )
        loaded = load_study(stored["id"])
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["study_type"], "portfolio_view")
        self.assertEqual(loaded["name"], "Confirming weekly view")
        self.assertEqual(loaded["config"], {
            "mover_window":    "weekly",
            "queue":           "confirming_now",
            "thesis_state":    "confirming",
            "proof_quality":   "proof_backed",
            "low_information": False,
        })

    def test_round_trip_partial_filters(self):
        from saved_studies import load_study, save_study
        stored = save_study(
            "portfolio_view", "Just the queue",
            {"queue": "watch_falsifiers"},
        )
        loaded = load_study(stored["id"])
        self.assertEqual(loaded["config"], {"queue": "watch_falsifiers"})


# ---------------------------------------------------------------------------
# Update-by-id — rename must not recreate a row
# ---------------------------------------------------------------------------

class TestUpdateByIdPreservesRow(unittest.TestCase):
    def setUp(self):
        self.db_path, self._db_originals = _isolated_db()

    def tearDown(self):
        _restore_db_constants(self._db_originals)
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_rename_keeps_same_id(self):
        from saved_studies import list_studies, load_study, save_study, update_study
        stored = save_study(
            "portfolio_view", "Original name",
            {"queue": "watch_falsifiers"},
        )
        original_id = stored["id"]
        renamed = update_study(original_id, name="Renamed view")
        self.assertIsNotNone(renamed)
        self.assertEqual(renamed["id"], original_id)
        self.assertEqual(renamed["name"], "Renamed view")
        # And no duplicate was introduced.
        studies = list_studies("portfolio_view")
        self.assertEqual(len(studies), 1)
        self.assertEqual(studies[0]["id"], original_id)

    def test_config_update_preserves_other_fields(self):
        from saved_studies import save_study, update_study
        stored = save_study(
            "portfolio_view", "Weekly confirming",
            {"mover_window": "weekly", "queue": "confirming_now"},
            description="pinned review",
        )
        updated = update_study(
            stored["id"],
            config={"mover_window": "today", "queue": "confirming_now"},
        )
        self.assertEqual(updated["id"], stored["id"])
        self.assertEqual(updated["name"], "Weekly confirming")
        self.assertEqual(updated["description"], "pinned review")
        self.assertEqual(
            updated["config"],
            {"mover_window": "today", "queue": "confirming_now"},
        )

    def test_update_missing_id_returns_none(self):
        from saved_studies import update_study
        self.assertIsNone(update_study(9999, name="x"))

    def test_bad_config_on_update_rejected(self):
        from saved_studies import save_study, update_study
        stored = save_study(
            "portfolio_view", "seed",
            {"queue": "watch_falsifiers"},
        )
        with self.assertRaises(ValueError):
            update_study(stored["id"], config={"queue": "not_a_queue"})

    def test_update_study_id_must_be_int(self):
        from saved_studies import update_study
        with self.assertRaises(ValueError):
            update_study("not_an_int")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PATCH route — end-to-end rename does not spawn duplicate
# ---------------------------------------------------------------------------

class TestPatchRouteRename(unittest.TestCase):
    def setUp(self):
        self.db_path, self._db_originals = _isolated_db()
        from fastapi.testclient import TestClient
        import api as _api_mod
        self.client = TestClient(_api_mod.app)

    def tearDown(self):
        _restore_db_constants(self._db_originals)
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_rename_via_patch_keeps_single_row(self):
        resp = self.client.post(
            "/portfolio/saved-studies",
            json={
                "study_type": "portfolio_view",
                "name":       "Initial view",
                "config":     {"queue": "confirming_now"},
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        sid = resp.json()["id"]

        patched = self.client.patch(
            f"/portfolio/saved-studies/{sid}",
            json={"name": "Renamed view"},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(patched.json()["id"], sid)
        self.assertEqual(patched.json()["name"], "Renamed view")

        listed = self.client.get(
            "/portfolio/saved-studies?study_type=portfolio_view",
        )
        studies = listed.json()["studies"]
        self.assertEqual(len(studies), 1)
        self.assertEqual(studies[0]["id"], sid)


# ---------------------------------------------------------------------------
# Research export honours the saved filters
# ---------------------------------------------------------------------------

class TestResearchExportHonoursFilters(unittest.TestCase):
    def _ticker(self, symbol: str, *, return_5d: float = 3.0,
                direction_tag: str = "supports up",
                evidence_score: float | None = None,
                evidence_label: str | None = None) -> dict:
        t = {
            "symbol": symbol, "role": "beneficiary",
            "return_5d": return_5d, "direction_tag": direction_tag,
        }
        if evidence_score is not None:
            t["evidence_score"] = evidence_score
        if evidence_label is not None:
            t["evidence_label"] = evidence_label
        return t

    def _event(self, event_id: int, **overrides) -> dict:
        now = datetime.now()
        base = {
            "id":                 event_id,
            "headline":           f"Event {event_id}",
            "event_date":         now.date().isoformat(),
            "timestamp":          (now - timedelta(hours=4)).isoformat(timespec="seconds"),
            "mechanism_family":   "commodity_squeeze",
            "mechanism_summary":  "Refinery outage tightens Gulf Coast capacity.",
            "confidence":         "medium",
            "rating":              "good",
            "minimum_proof_set":  [{"observation": "WCS spread widens",
                                    "channel": "commodities"}],
            "key_falsifiers":     [{"observation": "OPEC walks back",
                                    "channel": "commodities"}],
            "market_tickers":     [
                self._ticker("USO", evidence_score=0.85,
                             evidence_label="supportive"),
                self._ticker("XLE", evidence_score=0.80,
                             evidence_label="supportive"),
            ],
            "last_market_check_at":
                (now - timedelta(hours=1)).isoformat(timespec="seconds"),
            "regime_snapshot":    {"available": False},
        }
        base.update(overrides)
        return base

    def _low_info(self, event_id: int) -> dict:
        return self._event(
            event_id,
            confidence="low",
            mechanism_summary="Insufficient evidence to characterise.",
            minimum_proof_set=[], key_falsifiers=[],
            market_tickers=[self._ticker("USO", evidence_score=0.1,
                                         evidence_label="mixed")],
        )

    def test_empty_filters_returns_every_event(self):
        from research_export import replay_study
        events = [self._event(1), self._event(2)]
        out = replay_study("portfolio_view", {}, events)
        self.assertIsNone(out["error"])
        body = out["output"]
        self.assertEqual(body["total_considered"], 2)
        self.assertEqual(body["total_matched"], 2)

    def test_low_information_filter_honoured(self):
        from research_export import replay_study
        events = [self._event(1), self._low_info(2)]
        out = replay_study(
            "portfolio_view",
            {"low_information": True},
            events,
        )
        self.assertIsNone(out["error"])
        ids = {item["id"] for item in out["output"]["items"]}
        self.assertEqual(ids, {2})

    def test_queue_filter_honoured(self):
        from research_export import replay_study
        events = [self._event(1), self._low_info(2)]
        out = replay_study(
            "portfolio_view",
            {"queue": "low_information_cleanup"},
            events,
        )
        self.assertIsNone(out["error"])
        ids = {item["id"] for item in out["output"]["items"]}
        self.assertEqual(ids, {2})

    def test_mover_window_filter_honoured_via_injected_index(self):
        """The mover_window filter uses whatever the live mover slices
        expose; in the export pipeline we degrade to no-op when
        slices aren't reachable.  We exercise the filter path by
        monkey-patching ``build_event_window_index`` so the test is
        deterministic without booting the mover cache."""
        from unittest.mock import patch
        from research_export import replay_study
        events = [self._event(1), self._event(2)]
        index = {1: ["today"], 2: ["weekly"]}
        with patch("mover_context.build_event_window_index",
                   return_value=index):
            out = replay_study(
                "portfolio_view",
                {"mover_window": "today"},
                events,
            )
        self.assertIsNone(out["error"])
        ids = {item["id"] for item in out["output"]["items"]}
        self.assertEqual(ids, {1})

    def test_multiple_filters_anded(self):
        from unittest.mock import patch
        from research_export import replay_study
        events = [self._event(1), self._event(2), self._low_info(3)]
        index = {1: ["today"], 2: ["weekly"], 3: ["today"]}
        with patch("mover_context.build_event_window_index",
                   return_value=index):
            out = replay_study(
                "portfolio_view",
                {"mover_window": "today", "low_information": False},
                events,
            )
        self.assertIsNone(out["error"])
        ids = {item["id"] for item in out["output"]["items"]}
        self.assertEqual(ids, {1})

    def test_export_reports_filters_and_counts(self):
        from research_export import replay_study
        events = [self._event(1), self._low_info(2)]
        out = replay_study(
            "portfolio_view",
            {"low_information": True},
            events,
        )
        body = out["output"]
        self.assertEqual(body["total_considered"], 2)
        self.assertEqual(body["total_matched"], 1)
        self.assertEqual(body["filters"], {"low_information": True})


# ---------------------------------------------------------------------------
# Engine-phase filters — quality_tier / tradable / mechanism_subtype
# ---------------------------------------------------------------------------


class TestEngineFilterValidator(unittest.TestCase):
    """Validator must accept the three engine-phase filters, round-trip
    them unchanged, and reject malformed values with the same
    precision the legacy filters get."""

    def test_engine_filters_round_trip(self):
        from saved_studies import _validate_config
        out = _validate_config("portfolio_view", {
            "quality_tier":      "actionable",
            "tradable":          True,
            "mechanism_subtype": "tariff",
        })
        self.assertEqual(out, {
            "quality_tier":      "actionable",
            "tradable":          True,
            "mechanism_subtype": "tariff",
        })

    def test_quality_tier_enum_check(self):
        from saved_studies import _validate_config
        with self.assertRaises(ValueError):
            _validate_config("portfolio_view", {"quality_tier": "mystery"})

    def test_quality_tier_must_be_string(self):
        from saved_studies import _validate_config
        with self.assertRaises(ValueError):
            _validate_config("portfolio_view", {"quality_tier": 1})

    def test_tradable_must_be_bool(self):
        from saved_studies import _validate_config
        with self.assertRaises(ValueError):
            _validate_config("portfolio_view", {"tradable": "true"})

    def test_mechanism_subtype_open_string_accepted(self):
        """Open-ended subtype — any string is accepted; replay simply
        yields zero results on no-match."""
        from saved_studies import _validate_config
        out = _validate_config(
            "portfolio_view", {"mechanism_subtype": "anything_goes"},
        )
        self.assertEqual(out, {"mechanism_subtype": "anything_goes"})

    def test_mechanism_subtype_must_be_string(self):
        from saved_studies import _validate_config
        with self.assertRaises(ValueError):
            _validate_config(
                "portfolio_view", {"mechanism_subtype": 42},
            )

    def test_empty_string_engine_filters_dropped(self):
        from saved_studies import _validate_config
        out = _validate_config("portfolio_view", {
            "quality_tier": "", "mechanism_subtype": "",
        })
        self.assertEqual(out, {})


class TestEngineFilterRoundTripPersist(unittest.TestCase):
    """Save → load round-trip with engine-phase filters preserved
    exactly, and update-by-id rewrites them in place without spawning a
    duplicate row."""

    def setUp(self):
        self.db_path, self._db_originals = _isolated_db()

    def tearDown(self):
        _restore_db_constants(self._db_originals)
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_save_load_preserves_engine_filters(self):
        from saved_studies import load_study, save_study
        stored = save_study(
            "portfolio_view", "Actionable tariffs only",
            {
                "quality_tier":      "actionable",
                "tradable":          True,
                "mechanism_subtype": "tariff",
            },
        )
        loaded = load_study(stored["id"])
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["config"], {
            "quality_tier":      "actionable",
            "tradable":          True,
            "mechanism_subtype": "tariff",
        })

    def test_update_engine_filter_preserves_id(self):
        from saved_studies import save_study, update_study
        stored = save_study(
            "portfolio_view", "Engine view",
            {"quality_tier": "actionable"},
        )
        updated = update_study(
            stored["id"],
            config={"quality_tier": "watch_only", "tradable": False},
        )
        self.assertEqual(updated["id"], stored["id"])
        self.assertEqual(updated["config"], {
            "quality_tier": "watch_only", "tradable": False,
        })

    def test_update_replaces_does_not_merge_engine_filters(self):
        """An update with a new config must REPLACE the previous config
        wholesale — not union with stale fields.  If we save
        ``{quality_tier, tradable, mechanism_subtype}`` and then update
        with just ``{quality_tier}``, the loaded config must drop the
        other two."""
        from saved_studies import load_study, save_study, update_study
        stored = save_study(
            "portfolio_view", "All three",
            {
                "quality_tier":      "actionable",
                "tradable":          True,
                "mechanism_subtype": "tariff",
            },
        )
        update_study(
            stored["id"],
            config={"quality_tier": "watch_only"},
        )
        loaded = load_study(stored["id"])
        self.assertEqual(loaded["config"], {"quality_tier": "watch_only"})

    def test_update_with_empty_config_clears_filters(self):
        """``config={}`` is a valid portfolio_view config (no filters);
        passing it on update must clear every previously-pinned engine
        filter, not preserve stale values."""
        from saved_studies import load_study, save_study, update_study
        stored = save_study(
            "portfolio_view", "Pinned",
            {
                "quality_tier":      "actionable",
                "tradable":          True,
                "mechanism_subtype": "tariff",
            },
        )
        update_study(stored["id"], config={})
        self.assertEqual(load_study(stored["id"])["config"], {})

    def test_update_with_invalid_engine_filter_is_atomic(self):
        """A failed ``_validate_config`` must NOT write a partial state.
        After the ValueError the stored config must be byte-identical
        to what was saved."""
        from saved_studies import load_study, save_study, update_study
        stored = save_study(
            "portfolio_view", "Pinned",
            {
                "quality_tier":      "actionable",
                "tradable":          True,
                "mechanism_subtype": "tariff",
            },
        )
        before = load_study(stored["id"])["config"]
        with self.assertRaises(ValueError):
            update_study(stored["id"], config={"quality_tier": "mystery"})
        after = load_study(stored["id"])["config"]
        self.assertEqual(before, after)

    def test_update_omitting_config_preserves_engine_filters(self):
        """The ``_UNCHANGED`` sentinel is the *only* way to keep the
        previous config — explicitly passing the same config (or any
        new config) triggers the replace path.  This test pins the
        sentinel contract so a future "fix" doesn't accidentally start
        merging on the no-config-supplied path."""
        from saved_studies import load_study, save_study, update_study
        stored = save_study(
            "portfolio_view", "Untouched filters",
            {
                "quality_tier":      "actionable",
                "tradable":          True,
                "mechanism_subtype": "tariff",
            },
        )
        # Rename only — ``config`` not supplied → sentinel path.
        update_study(stored["id"], name="Renamed view")
        loaded = load_study(stored["id"])
        self.assertEqual(loaded["name"], "Renamed view")
        self.assertEqual(loaded["config"], {
            "quality_tier":      "actionable",
            "tradable":          True,
            "mechanism_subtype": "tariff",
        })

    def test_save_load_replay_round_trip_engine_filters(self):
        """Catches config-serialisation drift between save and replay
        that the in-memory replay tests miss: persist a study, reload
        it from the DB, then drive ``replay_study`` with the reloaded
        config.  The filter must still apply exactly."""
        from unittest.mock import patch
        from research_export import replay_study
        from saved_studies import load_study, save_study

        stored = save_study(
            "portfolio_view", "Tariff actionable",
            {
                "quality_tier":      "actionable",
                "tradable":          True,
                "mechanism_subtype": "tariff",
            },
        )
        loaded = load_study(stored["id"])

        events = [
            {"id": 1, "headline": "h1", "mechanism_summary": "x"},
            {"id": 2, "headline": "h2", "mechanism_summary": "x"},
        ]

        def _fake_compact(ev: dict) -> dict:
            return {
                1: {
                    "quality_tier":        "actionable",
                    "actionability_check": {"tradable": True},
                    "mechanism_subtype":   "tariff",
                },
                2: {
                    "quality_tier":        "watch_only",
                    "actionability_check": {"tradable": False},
                    "mechanism_subtype":   "supply_shock",
                },
            }[ev["id"]]

        with patch(
            "engine_phase_surface.decorate_compact",
            side_effect=_fake_compact,
        ):
            out = replay_study("portfolio_view", loaded["config"], events)

        self.assertIsNone(out["error"])
        ids = {item["id"] for item in out["output"]["items"]}
        self.assertEqual(ids, {1})
        self.assertEqual(
            out["output"]["filters"],
            {
                "quality_tier":      "actionable",
                "tradable":          True,
                "mechanism_subtype": "tariff",
            },
        )


class TestEngineFilterReplay(unittest.TestCase):
    """Replay must apply the three engine-phase filters exactly,
    surface them in the ``filters`` echo, and AND them with the
    legacy filters.

    Standalone (not inheriting ``TestResearchExportHonoursFilters``)
    so the pre-existing inherited mover_window failures don't pollute
    this class's pass/fail count.  The minimal event helpers below
    duplicate the ones above on purpose — every test in this class
    patches ``decorate_compact`` to drive the filter, so the synthetic
    event prose is irrelevant.
    """

    def _ticker(self, symbol: str) -> dict:
        return {
            "symbol": symbol, "role": "beneficiary",
            "return_5d": 3.0, "direction_tag": "supports up",
        }

    def _event(self, event_id: int, **overrides) -> dict:
        now = datetime.now()
        base = {
            "id":                event_id,
            "headline":          f"Event {event_id}",
            "event_date":        now.date().isoformat(),
            "timestamp":         (now - timedelta(hours=4)).isoformat(timespec="seconds"),
            "mechanism_family":  "commodity_squeeze",
            "mechanism_summary": "Refinery outage tightens Gulf Coast capacity.",
            "confidence":        "medium",
            "rating":            "good",
            "minimum_proof_set": [{"observation": "WCS spread widens",
                                   "channel": "commodities"}],
            "key_falsifiers":    [{"observation": "OPEC walks back",
                                   "channel": "commodities"}],
            "market_tickers":    [self._ticker("USO"), self._ticker("XLE")],
            "last_market_check_at":
                (now - timedelta(hours=1)).isoformat(timespec="seconds"),
            "regime_snapshot":   {"available": False},
        }
        base.update(overrides)
        return base

    def _low_info(self, event_id: int) -> dict:
        return self._event(
            event_id, confidence="low",
            mechanism_summary="Insufficient evidence to characterise.",
            minimum_proof_set=[], key_falsifiers=[],
        )

    def _patch_compact(self, mapping: dict):
        """Patch ``decorate_compact`` on the replay module so each
        event yields a deterministic engine-phase surface keyed by
        ``id``.  Mirrors how the existing mover_window test stubs
        ``build_event_window_index``."""
        from unittest.mock import patch

        def _fake(ev: dict) -> dict:
            return mapping.get(ev.get("id"), {
                "quality_tier":        "low_information",
                "actionability_check": {"tradable": False},
                "mechanism_subtype":   None,
            })
        # ``research_export._replay_portfolio_view`` does
        # ``from engine_phase_surface import decorate_compact`` inside
        # the function body, so the symbol must be patched on its
        # source module — patching ``research_export.decorate_compact``
        # would target a non-existent attribute.
        return patch(
            "engine_phase_surface.decorate_compact", side_effect=_fake,
        )

    def test_quality_tier_filter_honoured(self):
        from research_export import replay_study
        events = [self._event(1), self._event(2), self._low_info(3)]
        compact_by_id = {
            1: {"quality_tier": "actionable",
                "actionability_check": {"tradable": True},
                "mechanism_subtype": "tariff"},
            2: {"quality_tier": "watch_only",
                "actionability_check": {"tradable": True},
                "mechanism_subtype": "supply_shock"},
            3: {"quality_tier": "low_information",
                "actionability_check": {"tradable": False},
                "mechanism_subtype": None},
        }
        with self._patch_compact(compact_by_id):
            out = replay_study(
                "portfolio_view",
                {"quality_tier": "actionable"},
                events,
            )
        self.assertIsNone(out["error"])
        ids = {item["id"] for item in out["output"]["items"]}
        self.assertEqual(ids, {1})
        self.assertEqual(
            out["output"]["filters"], {"quality_tier": "actionable"},
        )

    def test_tradable_true_filter_honoured(self):
        from research_export import replay_study
        events = [self._event(1), self._event(2)]
        compact_by_id = {
            1: {"quality_tier": "actionable",
                "actionability_check": {"tradable": True},
                "mechanism_subtype": None},
            2: {"quality_tier": "watch_only",
                "actionability_check": {"tradable": False},
                "mechanism_subtype": None},
        }
        with self._patch_compact(compact_by_id):
            out = replay_study(
                "portfolio_view", {"tradable": True}, events,
            )
        ids = {item["id"] for item in out["output"]["items"]}
        self.assertEqual(ids, {1})

    def test_mechanism_subtype_filter_honoured(self):
        from research_export import replay_study
        events = [self._event(1), self._event(2)]
        compact_by_id = {
            1: {"quality_tier": "actionable",
                "actionability_check": {"tradable": True},
                "mechanism_subtype": "tariff"},
            2: {"quality_tier": "actionable",
                "actionability_check": {"tradable": True},
                "mechanism_subtype": "supply_shock"},
        }
        with self._patch_compact(compact_by_id):
            out = replay_study(
                "portfolio_view",
                {"mechanism_subtype": "tariff"},
                events,
            )
        ids = {item["id"] for item in out["output"]["items"]}
        self.assertEqual(ids, {1})

    def test_engine_filters_combine_with_legacy_filters(self):
        from research_export import replay_study
        events = [self._event(1), self._event(2), self._low_info(3)]
        compact_by_id = {
            1: {"quality_tier": "actionable",
                "actionability_check": {"tradable": True},
                "mechanism_subtype": "tariff"},
            2: {"quality_tier": "actionable",
                "actionability_check": {"tradable": True},
                "mechanism_subtype": "supply_shock"},
            3: {"quality_tier": "low_information",
                "actionability_check": {"tradable": False},
                "mechanism_subtype": None},
        }
        with self._patch_compact(compact_by_id):
            out = replay_study(
                "portfolio_view",
                {
                    "quality_tier":    "actionable",
                    "tradable":        True,
                    "low_information": False,
                },
                events,
            )
        ids = {item["id"] for item in out["output"]["items"]}
        # Both id=1 and id=2 are actionable + tradable + non-low-info.
        self.assertEqual(ids, {1, 2})

    def test_emitted_items_carry_engine_phase_fields(self):
        from research_export import replay_study
        events = [self._event(1)]
        compact_by_id = {
            1: {"quality_tier": "actionable",
                "actionability_check": {"tradable": True},
                "mechanism_subtype": "tariff"},
        }
        with self._patch_compact(compact_by_id):
            out = replay_study("portfolio_view", {}, events)
        item = out["output"]["items"][0]
        self.assertEqual(item["quality_tier"],      "actionable")
        self.assertEqual(item["tradable"],          True)
        self.assertEqual(item["mechanism_subtype"], "tariff")


if __name__ == "__main__":
    unittest.main()
