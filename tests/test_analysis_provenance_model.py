"""A1-2 — the immutable analysis-provenance snapshot.

Provenance records what an analysis USED.  It is not evidence that the
analysis is correct, and nothing here validates a thesis: every assertion is
about inputs, identity and tamper-detection.

Three things are pinned:
  * the candidate snapshot is rebuilt SERVER-SIDE from the strict identity
    ``(parent_cluster_id, title_key)`` — never from a caller-supplied list;
  * every hash is deterministic SHA-256 over canonical JSON (never Python's
    process-randomized ``hash()``);
  * any change to a basis input moves ``analysis_input_hash``, and any edit to
    a stored record moves ``provenance_hash`` and fails verification.

No provider is reached and no live database is touched.
"""

import json
import os
import sqlite3
import tempfile
import unittest
import uuid

import analysis_provenance as ap
import db as _db
from news_sources import _dedup_key

_TITLE_A = "Oil prices climb after pipeline outage"
_TITLE_B = "Central bank holds policy rate steady"
_KEY_A = _dedup_key(_TITLE_A)
_KEY_B = _dedup_key(_TITLE_B)
_PARENT = 4211


def _rec(source: str, title: str, published_at: str, url: str = "") -> dict:
    return {"source": source, "title": title, "published_at": published_at,
            "url": url or f"https://example.test/{source}".replace(" ", "-"),
            "candidate_id": f"rec-{source}-{title}"[:24]}


def _rows() -> list[dict]:
    """One parent cluster owning TWO strict partitions.

    The B-partition exists so every test can prove that a cross-partition
    record never leaks into the A-partition's provenance.
    """
    records = [
        _rec("Reuters World", _TITLE_A, "2026-07-07T09:00:00"),
        _rec("BBC Business", _TITLE_A, "2026-07-07T11:30:00"),
        _rec("AP Wire", _TITLE_A, "2026-07-07T08:15:00"),
        _rec("CNBC World", _TITLE_B, "2026-07-07T12:00:00"),
    ]
    return [{"id": _PARENT, "headline": _TITLE_A, "payload": {},
             "records": records, "latest_published_at": "2026-07-07T11:30:00",
             "updated_at": "2026-07-07T12:00:00"}]


def _basis(**over) -> dict:
    base = {
        "candidate_snapshot": ap.build_candidate_snapshot(_rows(), _PARENT, _KEY_A),
        "candidate_context_snapshot": "Sources (3): Reuters World, BBC Business, AP Wire",
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
        "system_prompt_snapshot": "SYSTEM",
        "rendered_user_prompt_snapshot": "USER PROMPT BODY",
        "analysis_prompt_version": ap.ANALYSIS_PROMPT_VERSION,
        "analysis_schema_version": ap.ANALYSIS_SCHEMA_VERSION,
    }
    base.update(over)
    return base


def _provenance(**over) -> dict:
    return ap.build_provenance(
        analysis_event_id=over.pop("analysis_event_id", 77),
        parent_cluster_id=over.pop("parent_cluster_id", _PARENT),
        title_key=over.pop("title_key", _KEY_A),
        created_at=over.pop("created_at", "2026-07-26T10:00:00"),
        **_basis(**over))


# ---------------------------------------------------------------------------
# Schema: additive, one row per analysis, never silently overwritten
# ---------------------------------------------------------------------------

class TestProvenanceSchema(unittest.TestCase):

    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_ap_schema_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()

    def tearDown(self):
        _db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def test_table_is_created_without_bumping_the_schema_version(self):
        conn = sqlite3.connect(self._tmp)
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        self.assertIn("analysis_provenance", names)
        # The existing D1A source-provenance sidecar is a DIFFERENT table and
        # must survive untouched.
        self.assertIn("event_provenance", names)
        # A bump would rename every existing local database to .bak.
        self.assertEqual(version, _db.SCHEMA_VERSION)

    def test_an_existing_database_gains_the_table_additively(self):
        conn = sqlite3.connect(self._tmp)
        conn.execute("DROP TABLE analysis_provenance")
        conn.execute("INSERT INTO events (timestamp, headline, stage, persistence) "
                     "VALUES ('2026-01-01T00:00:00', 'legacy row', 's', 'p')")
        conn.commit()
        conn.close()
        _db.init_db()
        conn = sqlite3.connect(self._tmp)
        rows = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        has = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='analysis_provenance'").fetchone()[0]
        conn.close()
        self.assertEqual(has, 1)
        self.assertEqual(rows, 1, "pre-existing rows must survive the migration")

    def test_one_analysis_event_accepts_exactly_one_snapshot(self):
        _db.save_analysis_provenance(_provenance(analysis_event_id=5))
        with self.assertRaises(Exception):
            _db.save_analysis_provenance(_provenance(analysis_event_id=5))

    def test_an_existing_snapshot_is_never_silently_overwritten(self):
        first = _provenance(analysis_event_id=6, model="model-one")
        _db.save_analysis_provenance(first)
        try:
            _db.save_analysis_provenance(_provenance(analysis_event_id=6,
                                                     model="model-two"))
        except Exception:
            pass
        stored = _db.load_analysis_provenance(6)
        self.assertEqual(stored["model"], "model-one")

    def test_a_missing_snapshot_reads_as_none_not_a_fabrication(self):
        self.assertIsNone(_db.load_analysis_provenance(999))


# ---------------------------------------------------------------------------
# Candidate snapshot — server-side, complete, partition-pure, deterministic
# ---------------------------------------------------------------------------

class TestCandidateSnapshot(unittest.TestCase):

    def test_includes_every_record_the_candidate_owns(self):
        snap = ap.build_candidate_snapshot(_rows(), _PARENT, _KEY_A)
        self.assertEqual(len(snap["records"]), 3)
        self.assertEqual({r["source"] for r in snap["records"]},
                         {"Reuters World", "BBC Business", "AP Wire"})

    def test_excludes_every_record_from_another_partition(self):
        snap = ap.build_candidate_snapshot(_rows(), _PARENT, _KEY_A)
        self.assertNotIn("CNBC World", {r["source"] for r in snap["records"]})
        for r in snap["records"]:
            self.assertEqual(r["title_key"], _KEY_A)

    def test_records_are_sorted_deterministically(self):
        rows = _rows()
        shuffled = _rows()
        shuffled[0]["records"] = list(reversed(shuffled[0]["records"]))
        self.assertEqual(ap.build_candidate_snapshot(rows, _PARENT, _KEY_A),
                         ap.build_candidate_snapshot(shuffled, _PARENT, _KEY_A))

    def test_carries_the_server_side_headline_and_owned_timestamps(self):
        snap = ap.build_candidate_snapshot(_rows(), _PARENT, _KEY_A)
        self.assertEqual(snap["first_seen_at"], "2026-07-07T08:15:00")
        self.assertEqual(snap["last_updated_at"], "2026-07-07T11:30:00")
        self.assertEqual(snap["headline"], _TITLE_A)

    def test_sources_are_deduplicated_and_ordered(self):
        snap = ap.build_candidate_snapshot(_rows(), _PARENT, _KEY_A)
        self.assertEqual(snap["sources"], sorted(set(snap["sources"])))

    def test_an_unresolvable_candidate_returns_none_rather_than_a_guess(self):
        self.assertIsNone(ap.build_candidate_snapshot(_rows(), _PARENT, _dedup_key("nope")))
        self.assertIsNone(ap.build_candidate_snapshot(_rows(), 999999, _KEY_A))
        self.assertIsNone(ap.build_candidate_snapshot([], _PARENT, _KEY_A))


# ---------------------------------------------------------------------------
# Identity, versions and exact context
# ---------------------------------------------------------------------------

class TestProvenanceIdentityAndVersions(unittest.TestCase):

    def test_candidate_id_recomputes_from_parent_and_title_key(self):
        from event_inbox import candidate_event_id
        p = _provenance()
        self.assertEqual(p["candidate_id"],
                         candidate_event_id(_PARENT, _KEY_A))

    def test_required_identity_fields_are_validated(self):
        for missing in ("analysis_event_id", "candidate_id",
                        "parent_cluster_id", "title_key"):
            p = _provenance()
            p.pop(missing)
            self.assertTrue(ap.verify_provenance(p),
                            f"missing {missing} must be reported")

    def test_persists_the_exact_context_it_was_given(self):
        exact = "Summary: X.\nAgreement: consistent\nActors: Y"
        p = _provenance(candidate_context_snapshot=exact)
        self.assertEqual(p["candidate_context_snapshot"], exact)

    def test_persists_provider_model_and_both_contract_versions(self):
        p = _provenance()
        self.assertEqual(p["provider"], "anthropic")
        self.assertEqual(p["model"], "claude-sonnet-4-20250514")
        self.assertEqual(p["analysis_prompt_version"], ap.ANALYSIS_PROMPT_VERSION)
        self.assertEqual(p["analysis_schema_version"], ap.ANALYSIS_SCHEMA_VERSION)

    def test_persists_the_exact_prompt_snapshots(self):
        p = _provenance(system_prompt_snapshot="SYS TEXT",
                        rendered_user_prompt_snapshot="USER TEXT")
        self.assertEqual(p["system_prompt_snapshot"], "SYS TEXT")
        self.assertEqual(p["rendered_user_prompt_snapshot"], "USER TEXT")

    def test_version_constants_are_non_empty_strings(self):
        self.assertIsInstance(ap.ANALYSIS_PROMPT_VERSION, str)
        self.assertIsInstance(ap.ANALYSIS_SCHEMA_VERSION, str)
        self.assertTrue(ap.ANALYSIS_PROMPT_VERSION)
        self.assertTrue(ap.ANALYSIS_SCHEMA_VERSION)

    def test_a_bumped_version_constant_is_actually_picked_up(self):
        # A signature default would bind once at import, so a deliberate bump
        # would be silently ignored and every stale analysis would keep
        # reading as current.  Both entry points must resolve at call time.
        from unittest.mock import patch
        with patch.object(ap, "ANALYSIS_PROMPT_VERSION", "prompt-v99"), \
                patch.object(ap, "ANALYSIS_SCHEMA_VERSION", "schema-v99"):
            p = _provenance()
            basis = ap.current_analysis_basis(
                candidate_snapshot=ap.build_candidate_snapshot(_rows(), _PARENT, _KEY_A),
                candidate_context_snapshot="x", provider="anthropic",
                model="m", system_prompt_snapshot="s",
                rendered_user_prompt_snapshot="u")
        self.assertEqual(p["analysis_prompt_version"], "prompt-v99")
        self.assertEqual(p["analysis_schema_version"], "schema-v99")
        self.assertEqual(basis["analysis_prompt_version"], "prompt-v99")
        self.assertEqual(basis["analysis_schema_version"], "schema-v99")


# ---------------------------------------------------------------------------
# Hashing — deterministic, basis-sensitive, tamper-evident
# ---------------------------------------------------------------------------

class TestProvenanceHashing(unittest.TestCase):

    def test_hashes_are_deterministic_across_calls(self):
        a, b = _provenance(), _provenance()
        for field in ("candidate_snapshot_hash", "prompt_snapshot_hash",
                      "analysis_input_hash", "provenance_hash"):
            self.assertEqual(a[field], b[field], field)

    def test_hashes_are_sha256_hex(self):
        p = _provenance()
        for field in ("candidate_snapshot_hash", "prompt_snapshot_hash",
                      "analysis_input_hash", "provenance_hash"):
            self.assertRegex(p[field], r"^[0-9a-f]{64}$", field)

    def test_every_basis_dimension_moves_the_input_hash(self):
        base = _provenance()["analysis_input_hash"]
        variants = {
            "candidate_records": _provenance(
                candidate_snapshot=ap.build_candidate_snapshot(
                    _rows(), _PARENT, _KEY_B)),
            "candidate_context": _provenance(
                candidate_context_snapshot="different context"),
            "provider": _provenance(provider="openai"),
            "model": _provenance(model="other-model"),
            "prompt_snapshot": _provenance(
                rendered_user_prompt_snapshot="different prompt"),
            "prompt_version": _provenance(analysis_prompt_version="v99"),
            "schema_version": _provenance(analysis_schema_version="v99"),
        }
        for name, p in variants.items():
            with self.subTest(dimension=name):
                self.assertNotEqual(p["analysis_input_hash"], base)

    def test_input_hash_ignores_fields_outside_the_analysis_basis(self):
        # Creation time and the event id are recorded but are not the basis:
        # the same inputs must hash identically whenever they were run.
        a = _provenance(analysis_event_id=1, created_at="2026-01-01T00:00:00")
        b = _provenance(analysis_event_id=2, created_at="2026-09-09T09:09:09")
        self.assertEqual(a["analysis_input_hash"], b["analysis_input_hash"])
        self.assertNotEqual(a["provenance_hash"], b["provenance_hash"])

    def test_a_valid_object_verifies_clean(self):
        self.assertEqual(ap.verify_provenance(_provenance()), [])

    def test_tampering_with_any_stored_field_fails_verification(self):
        for field, value in (("model", "swapped-model"),
                             ("candidate_context_snapshot", "rewritten"),
                             ("rendered_user_prompt_snapshot", "rewritten"),
                             ("analysis_input_hash", "0" * 64),
                             ("title_key", _KEY_B)):
            with self.subTest(field=field):
                p = _provenance()
                p[field] = value
                self.assertTrue(ap.verify_provenance(p),
                                f"tampered {field} must fail verification")

    def test_a_conflicting_candidate_identity_fails_verification(self):
        p = _provenance()
        p["candidate_id"] = "aei-1-deadbeef"
        p["provenance_hash"] = ap.provenance_hash_of(p)  # re-seal the tamper
        problems = ap.verify_provenance(p)
        self.assertTrue(problems, "candidate_id must be re-derived, not trusted")

    def test_canonical_json_is_stable_under_key_order(self):
        self.assertEqual(ap.canonical_json({"b": 1, "a": [2, 3]}),
                         ap.canonical_json({"a": [2, 3], "b": 1}))
        self.assertEqual(json.loads(ap.canonical_json({"a": 1})), {"a": 1})


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

class TestProvenanceStates(unittest.TestCase):

    def _current(self, **over):
        return ap.current_analysis_basis(
            candidate_snapshot=over.pop(
                "candidate_snapshot",
                ap.build_candidate_snapshot(_rows(), _PARENT, _KEY_A)),
            candidate_context_snapshot=over.pop(
                "candidate_context_snapshot",
                "Sources (3): Reuters World, BBC Business, AP Wire"),
            provider=over.pop("provider", "anthropic"),
            model=over.pop("model", "claude-sonnet-4-20250514"),
            system_prompt_snapshot=over.pop("system_prompt_snapshot", "SYSTEM"),
            rendered_user_prompt_snapshot=over.pop(
                "rendered_user_prompt_snapshot", "USER PROMPT BODY"),
            **over)

    def test_matching_basis_is_verified_current(self):
        state = ap.derive_provenance_state(_provenance(), self._current())
        self.assertEqual(state["status"], "VERIFIED_CURRENT")
        self.assertEqual(state["changed_dimensions"], [])

    def test_absent_provenance_is_legacy(self):
        state = ap.derive_provenance_state(None, self._current())
        self.assertEqual(state["status"], "LEGACY_PROVENANCE_UNAVAILABLE")

    def test_malformed_or_tampered_provenance_is_invalid_not_legacy(self):
        p = _provenance()
        p["model"] = "swapped"
        state = ap.derive_provenance_state(p, self._current())
        self.assertEqual(state["status"], "PROVENANCE_INVALID")

    def test_each_changed_dimension_is_named(self):
        cases = {
            "candidate_records": self._current(
                candidate_snapshot=ap.build_candidate_snapshot(
                    _rows(), _PARENT, _KEY_B)),
            "candidate_context": self._current(
                candidate_context_snapshot="changed"),
            "provider": self._current(provider="openai"),
            "model": self._current(model="newer-model"),
            "prompt_version": self._current(
                analysis_prompt_version="event-analysis-prompt-v2"),
            "schema_version": self._current(
                analysis_schema_version="analysis-result-v2"),
        }
        for dimension, current in cases.items():
            with self.subTest(dimension=dimension):
                state = ap.derive_provenance_state(_provenance(), current)
                self.assertEqual(state["status"], "SAVED_WITH_OLDER_BASIS")
                self.assertIn(dimension, state["changed_dimensions"])

    def test_an_unresolvable_candidate_cannot_read_as_current(self):
        state = ap.derive_provenance_state(_provenance(), None)
        self.assertEqual(state["status"], "SAVED_WITH_OLDER_BASIS")
        self.assertIn("candidate_unresolved", state["changed_dimensions"])

    def test_every_status_is_in_the_closed_vocabulary(self):
        for current in (self._current(), None):
            for stored in (_provenance(), None):
                state = ap.derive_provenance_state(stored, current)
                self.assertIn(state["status"], ap.PROVENANCE_STATES)


if __name__ == "__main__":
    unittest.main()
