"""Provider default repair — the retired Anthropic runtime default.

A2-2 proved with the live Models API and four authorized generations that
``claude-sonnet-4-20250514`` is retired (404 model_not_found) and
``claude-sonnet-4-6`` is served.  This module pins the repair contract:

  * with no ``ANTHROPIC_MODEL`` override the runtime resolves the verified
    replacement, and an explicit override stays authoritative verbatim;
  * the resolved model remains a durable-identity dimension, so a mapping
    generated under the retired model is never reused by a replacement-model
    request;
  * historical saved analyses keep their original model on numeric reopen,
    provider-free and write-free — nothing is rewritten;
  * new persistence records the resolved replacement on both routes;
  * a provider error never triggers automatic model substitution.

Every environment mutation is scoped to its own run window (patch.dict), so
discovery order cannot leak model state across modules.  No real provider is
reachable: the analysis seam is always patched or armed.
"""

import os
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

import analysis_request_identity as ari
import analyze_event as ae
import api as _api
import db as _db

RETIRED = "claude-sonnet-4-20250514"
REPLACEMENT = "claude-sonnet-4-6"

_ANALYSIS = {
    "what_changed": "The policy rate was held.",
    "mechanism_summary": "The expected path is unchanged.",
    "beneficiaries": ["banks"], "losers": ["borrowers"],
    "beneficiary_tickers": [], "loser_tickers": [], "assets_to_watch": [],
    "confidence": "medium", "transmission_chain": ["hold"],
    "key_falsifiers": ["A cut within two meetings"], "primary_assets": ["XLF"],
    "if_persists": {}, "currency_channel": {},
}


def _no_model_env():
    """A run-window env with the Anthropic model override REMOVED."""
    env = {k: v for k, v in os.environ.items()}
    env.pop("ANTHROPIC_MODEL", None)
    env.pop("ANALYSIS_PROVIDER", None)
    return patch.dict(os.environ, env, clear=True)


class TestRuntimeModelResolution(unittest.TestCase):

    def test_missing_override_resolves_the_verified_replacement(self):
        with _no_model_env():
            self.assertEqual(ae._selected_model(), REPLACEMENT)

    def test_missing_override_never_resolves_the_retired_model(self):
        with _no_model_env():
            self.assertNotEqual(ae._selected_model(), RETIRED)

    def test_explicit_override_stays_authoritative_verbatim(self):
        with patch.dict(os.environ, {"ANTHROPIC_MODEL": "claude-custom-x"}):
            self.assertEqual(ae._selected_model(), "claude-custom-x")

    def test_the_retired_id_is_no_longer_the_module_default(self):
        self.assertEqual(ae._DEFAULT_MODEL, REPLACEMENT)

    def test_active_model_delegates_to_the_same_resolution(self):
        with _no_model_env():
            self.assertEqual(_api._active_model(), REPLACEMENT)


class TestDurableIdentitySeparation(unittest.TestCase):

    def _basis(self, model):
        return ari.build_request_basis(
            provider="anthropic", model=model, system_prompt="s",
            rendered_user_prompt="p", prompt_version="pv",
            schema_version="sv", event_date="2026-07-28")

    def test_retired_and_replacement_models_hash_differently(self):
        self.assertNotEqual(ari.request_hash(self._basis(RETIRED)),
                            ari.request_hash(self._basis(REPLACEMENT)))


class _RouteBase(unittest.TestCase):
    """Temp DB per test; analysis seam patched; env scoped per run."""

    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_mdr_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()
        self.client = TestClient(_api.app)
        self.provider_calls: list = []
        self._env = _no_model_env()
        self._env.start()

    def tearDown(self):
        self._env.stop()
        _db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _provider(self, *a, **k):
        self.provider_calls.append(1)
        return dict(_ANALYSIS)

    def _post(self, body, provider=None):
        with patch("routes.analyze._call_analyze_event",
                   provider or self._provider), \
             patch.object(_api, "build_macro_context_for_prompt",
                          return_value="Macro backdrop: fixed"), \
             patch.object(_api, "market_check",
                          return_value={"note": "", "tickers": []}):
            return self.client.post("/analyze", json=body)

    def _row(self, eid, col):
        conn = sqlite3.connect(self._tmp)
        try:
            return conn.execute(f"SELECT {col} FROM events WHERE id = ?",
                                (eid,)).fetchone()[0]
        finally:
            conn.close()


class TestDurableMappingIsNotCrossModelReused(_RouteBase):

    def test_a_retired_model_mapping_misses_for_a_replacement_request(self):
        """The pre-repair failure mode: with the retired id still the
        default, the request hash matched the old mapping and the retired
        analysis was silently reused."""
        headline = "Central bank leaves policy rate unchanged"
        # Persist a saved analysis whose durable mapping was computed with
        # the RETIRED model — exactly what the route would have written
        # before this repair (same renderer, same versions, retired model).
        import analysis_provenance as ap
        import analysis_result_snapshot as ars
        from analyze_event import SYSTEM_PROMPT, render_analysis_prompt

        stage = _api.classify_stage(headline)
        persistence = _api.classify_persistence(headline)
        basis = ari.build_request_basis(
            provider="anthropic", model=RETIRED,
            system_prompt=SYSTEM_PROMPT,
            rendered_user_prompt=render_analysis_prompt(
                headline=headline, stage=stage, persistence=persistence,
                event_context="", macro_context="Macro backdrop: fixed"),
            prompt_version=ap.ANALYSIS_PROMPT_VERSION,
            schema_version=ap.ANALYSIS_SCHEMA_VERSION,
            event_date="2026-07-28")
        eid, _ = _db.save_event_with_analysis_provenance(
            {"headline": headline, "stage": stage, "persistence": persistence,
             "event_date": "2026-07-28", "mechanism_summary": "old",
             "what_changed": "old", "confidence": "medium", "model": RETIRED},
            None,
            lambda i: ars.build_result_snapshot(_ANALYSIS),
            lambda i: ari.request_mapping_record(basis))
        self.assertIsInstance(eid, int)

        resp = self._post({"headline": headline,
                           "event_date": "2026-07-28"}).json()
        self.assertEqual(
            resp.get("status"), "paid_confirmation_required",
            "a Sonnet 4.6 request reused a retired-model durable mapping")
        self.assertEqual(self.provider_calls, [])


class TestHistoricalReopenPreservesModel(_RouteBase):

    def test_numeric_reopen_keeps_the_retired_model_and_calls_nothing(self):
        eid = _db.save_event({
            "headline": "A historical analysis from the retired model",
            "stage": "breaking", "persistence": "transient",
            "event_date": "2026-04-10", "mechanism_summary": "stored",
            "what_changed": "stored", "confidence": "medium",
            "model": RETIRED})
        self.assertIsInstance(eid, int)

        def armed(*a, **k):
            raise AssertionError("provider called on a numeric reopen")

        resp = self._post({"headline": "A historical analysis from the "
                                       "retired model", "event_id": eid},
                          provider=armed).json()
        self.assertEqual(resp.get("analysis_event_id") or resp.get("id"), eid)
        self.assertEqual(self._row(eid, "model"), RETIRED,
                         "historical saved model must not be rewritten")


class TestNewPersistenceRecordsTheReplacement(_RouteBase):

    def test_a_new_direct_analysis_records_the_replacement_everywhere(self):
        resp = self._post({"headline": "Port authority suspends container "
                                       "throughput", "confirm_paid": True}).json()
        eid = resp.get("analysis_event_id")
        self.assertIsInstance(eid, int)
        self.assertEqual(self._row(eid, "model"), REPLACEMENT)
        conn = sqlite3.connect(self._tmp)
        try:
            mapped = conn.execute(
                "SELECT model FROM analysis_request_cache WHERE"
                " analysis_event_id = ?", (eid,)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(mapped, REPLACEMENT)

    def test_direct_and_inbox_routes_resolve_the_same_default(self):
        import json as _json
        from event_inbox import candidate_event_id
        from news_sources import _dedup_key
        headline = "Refinery outage cuts regional diesel supply"
        key = _dedup_key(headline)
        parent = 9911
        conn = sqlite3.connect(self._tmp)
        recs = [{"source": "Reuters World", "title": headline,
                 "published_at": "2026-07-20T09:00:00", "url": "u1"},
                {"source": "BBC Business", "title": headline,
                 "published_at": "2026-07-20T11:30:00", "url": "u2"}]
        conn.execute("INSERT OR REPLACE INTO news_clusters (id, headline,"
                     " payload_json, records_json, latest_published_at,"
                     " updated_at) VALUES (?,?,?,?,?,?)",
                     (parent, headline, _json.dumps({}), _json.dumps(recs),
                      "2026-07-20T11:30:00", "2026-07-20T11:30:00"))
        for s in ("Reuters World", "BBC Business"):
            conn.execute("INSERT OR REPLACE INTO headline_registry (source,"
                         " title_key, cluster_id, event_id, state,"
                         " first_seen_at, last_seen_at)"
                         " VALUES (?,?,?,NULL,'seen','t','t')", (s, key, parent))
        conn.commit()
        conn.close()

        direct = self._post({"headline": "A direct default-model probe",
                             "confirm_paid": True}).json()
        inbox = self._post({"headline": headline, "event_context": "Sources (2)",
                            "candidate_id": candidate_event_id(parent, key),
                            "parent_cluster_id": parent, "title_key": key,
                            "confirm_paid": True}).json()
        d_model = self._row(direct["analysis_event_id"], "model")
        i_model = self._row(inbox["analysis_event_id"], "model")
        self.assertEqual(d_model, i_model)
        self.assertEqual(d_model, REPLACEMENT)


class TestNoAutomaticSubstitutionOnProviderError(unittest.TestCase):

    def test_a_provider_error_never_switches_models(self):
        """The engine may fail closed to a mock, but it must never re-request
        with a DIFFERENT model id."""
        requested: list = []

        class _Boom(Exception):
            pass

        def fake_create(self, *a, **k):
            requested.append(k.get("model"))
            raise _Boom("model_not_found-alike failure")

        env = {k: v for k, v in os.environ.items()}
        env.pop("ANTHROPIC_MODEL", None)
        env["ANTHROPIC_API_KEY"] = "sk-ant-test-not-a-real-key-000"
        from anthropic.resources.messages import Messages
        with patch.dict(os.environ, env, clear=True), \
             patch.object(Messages, "create", fake_create):
            result = ae.analyze_event("A headline for the substitution probe",
                                      "breaking", "transient")
        self.assertTrue(requested, "provider seam never reached")
        self.assertEqual(set(requested), {ae._selected_model()},
                         "engine re-requested with a substituted model id")
        self.assertTrue(ae.is_mock(result))


if __name__ == "__main__":
    unittest.main()
