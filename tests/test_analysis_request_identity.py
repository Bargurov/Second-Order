"""A1-4 — durable analysis request identity.

``analysis_request_hash`` identifies ONE exact analysis invocation basis: the
provider, the model, the two prompt snapshots and the contract versions.  It
is not an event identity and not a thesis identity — two different events can
share a request hash only if they were produced from a byte-identical request,
which is exactly what makes reuse safe.

Kept deliberately distinct from the three identities that already exist:
    candidate_id        strict Inbox candidate (aei-*)
    analysis_event_id   numeric events.id
    analysis_input_hash A1-2 Inbox provenance input identity

The hash is derived from the SHARED prompt renderer, so a prompt change can
never silently keep an old cache entry alive.
"""

import hashlib
import os
import sqlite3
import tempfile
import unittest
import uuid

import analysis_request_identity as ari
import db as _db
from analyze_event import SYSTEM_PROMPT, render_analysis_prompt


def _basis(**over) -> dict:
    base = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
        "system_prompt": SYSTEM_PROMPT,
        "rendered_user_prompt": render_analysis_prompt(
            headline="Refinery outage cuts regional diesel supply",
            stage="breaking", persistence="transient",
            event_context="Sources (2): Reuters World, BBC Business",
            macro_context="Regime: Mixed"),
        "prompt_version": "event-analysis-prompt-v1",
        "schema_version": "analysis-result-v1",
        "event_date": "2026-07-20",
    }
    base.update(over)
    return base


def _prompt(**over) -> str:
    kw = {"headline": "Refinery outage cuts regional diesel supply",
          "stage": "breaking", "persistence": "transient",
          "event_context": "Sources (2): Reuters World, BBC Business",
          "macro_context": "Regime: Mixed"}
    kw.update(over)
    return render_analysis_prompt(**kw)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestRequestHashDeterminism(unittest.TestCase):

    def test_identical_bases_produce_the_same_hash(self):
        self.assertEqual(ari.request_hash(_basis()), ari.request_hash(_basis()))

    def test_the_hash_is_a_sha256_digest(self):
        self.assertRegex(ari.request_hash(_basis()), r"^[0-9a-f]{64}$")

    def test_serialization_is_canonical_and_key_order_independent(self):
        a = dict(_basis())
        b = {k: a[k] for k in reversed(list(a))}
        self.assertEqual(ari.request_hash(a), ari.request_hash(b))

    def test_the_module_never_uses_python_hash(self):
        import inspect
        src = inspect.getsource(ari)
        self.assertNotIn(" hash(", src)
        self.assertIn("sha256", src)

    def test_the_hash_matches_an_independent_sha256_of_the_canonical_form(self):
        basis = _basis()
        expected = hashlib.sha256(
            ari.canonical_request_json(basis).encode("utf-8")).hexdigest()
        self.assertEqual(ari.request_hash(basis), expected)


# ---------------------------------------------------------------------------
# Every dimension that must move the hash
# ---------------------------------------------------------------------------

class TestRequestHashDimensions(unittest.TestCase):

    def setUp(self):
        self.base = ari.request_hash(_basis())

    def test_each_prompt_input_moves_the_hash(self):
        cases = {
            "headline": _prompt(headline="A different refinery event"),
            "event_context": _prompt(event_context="Sources (3): A, B, C"),
            "macro_context": _prompt(macro_context="Regime: Tight"),
            "stage": _prompt(stage="developing"),
            "persistence": _prompt(persistence="structural"),
        }
        for name, rendered in cases.items():
            with self.subTest(dimension=name):
                self.assertNotEqual(
                    ari.request_hash(_basis(rendered_user_prompt=rendered)),
                    self.base)

    def test_each_contract_dimension_moves_the_hash(self):
        cases = {
            "provider": _basis(provider="openai"),
            "model": _basis(model="claude-opus-4"),
            "prompt_version": _basis(prompt_version="event-analysis-prompt-v2"),
            "schema_version": _basis(schema_version="analysis-result-v2"),
            "event_date": _basis(event_date="2026-07-21"),
            "system_prompt": _basis(system_prompt=SYSTEM_PROMPT + " extra"),
            "rendered_user_prompt": _basis(rendered_user_prompt="entirely different"),
        }
        for name, basis in cases.items():
            with self.subTest(dimension=name):
                self.assertNotEqual(ari.request_hash(basis), self.base)

    def test_volatile_context_never_moves_the_hash(self):
        # A basis carrying extra volatile keys must hash the same: the hash is
        # built from the declared contract, not from whatever the caller
        # happened to pass.
        noisy = _basis()
        noisy.update({
            "created_at": "2026-07-26T10:00:00",
            "cache_age_seconds": 999999,
            "market": {"tickers": [{"symbol": "VLO", "return_1d": 3.2}]},
            "provenance_status": "VERIFIED_CURRENT",
            "route_origin": "inbox",
            "analysis_event_id": 412,
            "candidate_registry_state": "analyzed",
        })
        self.assertEqual(ari.request_hash(noisy), self.base)

    def test_a_missing_required_dimension_is_refused(self):
        for field in ari.REQUEST_BASIS_FIELDS:
            basis = _basis()
            basis.pop(field)
            with self.subTest(missing=field):
                with self.assertRaises(Exception):
                    ari.request_hash(basis)


# ---------------------------------------------------------------------------
# No secret may enter the identity
# ---------------------------------------------------------------------------

class TestNoSecretsInRequestIdentity(unittest.TestCase):

    def test_the_basis_carries_no_key_token_or_environment_value(self):
        basis = _basis()
        blob = ari.canonical_request_json(basis)
        for token in ("sk-ant-", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                      "SECOND_ORDER_ADMIN_TOKEN", "Authorization", "Bearer"):
            self.assertNotIn(token, blob)

    def test_the_declared_basis_fields_are_exactly_the_approved_set(self):
        # The six provider-relevant fields plus event_date, which never
        # reaches the prompt but selects the market-check window and is
        # stored on the row — two requests differing only by date produce
        # different saved results and must not collide.
        self.assertEqual(set(ari.REQUEST_BASIS_FIELDS), {
            "provider", "model", "system_prompt", "rendered_user_prompt",
            "prompt_version", "schema_version", "event_date"})


# ---------------------------------------------------------------------------
# Schema + mapping storage
# ---------------------------------------------------------------------------

class TestRequestMappingStorage(unittest.TestCase):

    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_ari_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()

    def tearDown(self):
        _db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _mapping(self, **over) -> dict:
        m = {"request_hash": ari.request_hash(_basis()),
             "provider": "anthropic", "model": "claude-sonnet-4-20250514",
             "prompt_version": "event-analysis-prompt-v1",
             "schema_version": "analysis-result-v1"}
        m.update(over)
        return m

    def test_the_table_is_additive_at_the_existing_schema_version(self):
        conn = sqlite3.connect(self._tmp)
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        self.assertIn("analysis_request_cache", names)
        # The A1-2 / A1-3 tables are different concepts and must survive.
        self.assertIn("analysis_provenance", names)
        self.assertIn("analysis_result_snapshot", names)
        self.assertEqual(version, _db.SCHEMA_VERSION)

    def test_an_existing_database_gains_the_table_without_data_loss(self):
        conn = sqlite3.connect(self._tmp)
        conn.execute("DROP TABLE analysis_request_cache")
        conn.execute("INSERT INTO events (timestamp, headline, stage, persistence)"
                     " VALUES ('2026-01-01T00:00:00','legacy','s','p')")
        conn.commit()
        conn.close()
        _db.init_db()
        conn = sqlite3.connect(self._tmp)
        has = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                           " AND name='analysis_request_cache'").fetchone()[0]
        rows = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        self.assertEqual((has, rows), (1, 1))

    def test_one_request_hash_maps_to_exactly_one_event(self):
        _db.save_analysis_request_mapping(11, self._mapping(),
                                          created_at="2026-07-26T10:00:00")
        with self.assertRaises(Exception):
            _db.save_analysis_request_mapping(12, self._mapping(),
                                              created_at="2026-07-26T10:00:00")

    def test_one_event_maps_to_exactly_one_request_hash(self):
        _db.save_analysis_request_mapping(13, self._mapping(),
                                          created_at="2026-07-26T10:00:00")
        other = self._mapping(request_hash=ari.request_hash(_basis(model="other")))
        with self.assertRaises(Exception):
            _db.save_analysis_request_mapping(13, other,
                                              created_at="2026-07-26T10:00:00")

    def test_an_existing_mapping_is_never_silently_overwritten(self):
        m = self._mapping()
        _db.save_analysis_request_mapping(14, m, created_at="2026-07-26T10:00:00")
        try:
            _db.save_analysis_request_mapping(
                99, dict(m, model="swapped"), created_at="2026-07-26T11:00:00")
        except Exception:
            pass
        found = _db.find_event_id_by_request_hash(m["request_hash"])
        self.assertEqual(found, 14)

    def test_an_unknown_request_hash_reads_as_none(self):
        self.assertIsNone(_db.find_event_id_by_request_hash("0" * 64))

    def test_an_absent_or_unusable_hash_fails_closed(self):
        for bad in (None, "", 42, object()):
            with self.subTest(value=repr(bad)):
                self.assertIsNone(_db.find_event_id_by_request_hash(bad))

    def test_reading_the_mapping_performs_no_write(self):
        m = self._mapping()
        _db.save_analysis_request_mapping(15, m, created_at="2026-07-26T10:00:00")
        conn = sqlite3.connect(self._tmp)
        before = conn.execute(
            "SELECT COUNT(*) FROM analysis_request_cache").fetchone()[0]
        conn.close()
        for _ in range(3):
            _db.find_event_id_by_request_hash(m["request_hash"])
            _db.find_event_id_by_request_hash("f" * 64)
        conn = sqlite3.connect(self._tmp)
        after = conn.execute(
            "SELECT COUNT(*) FROM analysis_request_cache").fetchone()[0]
        conn.close()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
