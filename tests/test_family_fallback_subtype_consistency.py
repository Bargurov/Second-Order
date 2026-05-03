"""
tests/test_family_fallback_subtype_consistency.py

Covers the contract between ``_post_parse_family_fallback`` and
``_normalize_mechanism_subtype`` in ``analyze_event._normalize_schema``.

The first-pass family resolver runs over the headline + mechanism
summary; if it can't commit to anything it returns ``"none"``.  A
second-pass fallback (``family_inference.resolve_effective_family``)
then consults the transmission_path, asset buckets, and hidden_mechanism
block — and may upgrade ``mechanism_family`` from ``"none"`` to a real
canonical id.

When that upgrade fires, any LLM-committed ``mechanism_subtype`` was
authored against the *old* family ("none" — i.e. the broad subtype set
``FAMILY_SUBTYPES.get("none", {})`` which is empty).
``_normalize_mechanism_subtype`` runs AFTER the fallback so the subtype
is revalidated against the *upgraded* family:

  * Valid subtype for upgraded family       → kept
  * Invalid subtype for upgraded family     → dropped + warning logged
  * No LLM subtype but inference matches    → set against new family
  * Family fallback does NOT fire           → stored subtype untouched

Plus the invariants: the top-level ``mechanism_family`` field is always
in the canonical ``FAMILY_IDS`` enum (no invented tokens) and the DB
read path never re-runs the fallback on stored rows.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db as db_module
from db import _decode_event_row, init_db, load_event_by_id, save_event
from mechanism_family import FAMILY_IDS, FAMILY_SUBTYPES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bank_stress_raw(
    *,
    llm_family: str = "none",
    llm_subtype: str | None = None,
) -> dict:
    """Synthetic LLM output that the second-pass fallback resolves to
    ``bank_stress`` deterministically.

    The keyword tier in ``family_inference`` matches ``bank failure``
    + ``deposit run`` → ``bank_stress``.  The subtype inference path
    matches ``regional bank`` + ``deposit run`` → ``regional_bank_stress``.
    Both are stable against the current registry; if either drifts,
    these tests will surface it.
    """
    raw: dict = {
        "what_changed": (
            "Silicon Valley Bank fails on a deposit run; regional bank "
            "depositors flee KRE-listed names."
        ),
        "mechanism_summary": (
            "Regional bank deposit run accelerates the bank failure "
            "cascade; midsize banks repriced as counterparty risk."
        ),
        "mechanism_family": llm_family,
        "transmission_path": [
            {"hop":     "Depositors withdraw from regional banks",
             "action":  "Depositors withdraw from regional banks",
             "actor":   "depositors",
             "channel": "capital_flow",
             "expected_market_effect": "KRE / IAT sell off as deposits flee.",
             "timing":  "1d"},
        ],
        "beneficiaries":      [],
        "losers":             ["KRE", "IAT"],
        "beneficiary_tickers": [],
        "loser_tickers":       ["KRE", "IAT"],
    }
    if llm_subtype is not None:
        raw["mechanism_subtype"] = llm_subtype
    return raw


def _normalize(raw: dict, headline: str = "Bank failure cascades") -> dict:
    """Run the analyze_event normaliser the way analyze_event itself
    invokes it.  Imported lazily so test discovery doesn't pull
    ``analyze_event`` if a test class doesn't need it."""
    from analyze_event import _normalize_schema
    return _normalize_schema(raw, headline)


# ---------------------------------------------------------------------------
# Sanity check: the bank_stress fixture actually triggers a fallback
# upgrade.  If ``family_inference`` keyword priorities drift, every
# downstream test would silently fail for the wrong reason — anchor
# the assumption here so the failure reads as fixture drift, not as
# a contract violation in the code under test.
# ---------------------------------------------------------------------------


class FixtureUpgradesToBankStress(unittest.TestCase):

    def test_bank_stress_fixture_upgrades_from_none(self) -> None:
        result = _normalize(_bank_stress_raw(llm_family="none"))
        self.assertEqual(
            result["mechanism_family"], "bank_stress",
            "fixture drift: bank_stress fallback fixture no longer "
            "resolves to 'bank_stress' — keyword priorities may have "
            "changed.  Other tests in this file depend on this anchor.",
        )


# ---------------------------------------------------------------------------
# 1. Fallback upgrades family + valid subtype survives
# ---------------------------------------------------------------------------


class ValidSubtypePreservedAfterUpgrade(unittest.TestCase):

    def test_valid_subtype_for_upgraded_family_kept(self) -> None:
        raw = _bank_stress_raw(
            llm_family="none", llm_subtype="regional_bank_stress",
        )
        result = _normalize(raw)
        self.assertEqual(result["mechanism_family"], "bank_stress")
        self.assertEqual(result.get("mechanism_subtype"), "regional_bank_stress")
        warnings = result.get("validation_warnings") or []
        self.assertFalse(any(
            "mechanism_subtype dropped" in w for w in warnings
        ), warnings)

    def test_subtype_lives_inside_family_subtype_registry(self) -> None:
        raw = _bank_stress_raw(
            llm_family="none", llm_subtype="regional_bank_stress",
        )
        result = _normalize(raw)
        family = result["mechanism_family"]
        subtype = result.get("mechanism_subtype")
        self.assertIn(subtype, FAMILY_SUBTYPES.get(family, {}))


# ---------------------------------------------------------------------------
# 2. Fallback upgrades family + invalid subtype dropped + warning
# ---------------------------------------------------------------------------


class InvalidSubtypeDroppedAfterUpgrade(unittest.TestCase):

    def test_subtype_for_other_family_dropped(self) -> None:
        # ``oil_supply_shock`` is registered under supply_shock, NOT
        # bank_stress.  After the family upgrades to bank_stress the
        # subtype is no longer valid and must be dropped with a warning.
        raw = _bank_stress_raw(
            llm_family="none", llm_subtype="oil_supply_shock",
        )
        result = _normalize(raw)
        self.assertEqual(result["mechanism_family"], "bank_stress")
        # Subtype dropped — either absent OR replaced by a valid
        # subtype the inference fallback found in the same prose.
        # Both are acceptable per the contract; what's required is
        # that ``oil_supply_shock`` is not the surviving value.
        self.assertNotEqual(
            result.get("mechanism_subtype"), "oil_supply_shock",
            "stale subtype must not survive a family upgrade",
        )
        warnings = result.get("validation_warnings") or []
        self.assertTrue(any(
            "mechanism_subtype dropped" in w
            and "oil_supply_shock" in w
            and "bank_stress" in w
            for w in warnings
        ), f"expected drop-warning, got {warnings!r}")

    def test_drop_warning_names_offending_subtype_and_target_family(self) -> None:
        raw = _bank_stress_raw(
            llm_family="none",
            # ``hawkish_surprise`` belongs to policy_surprise.
            llm_subtype="hawkish_surprise",
        )
        result = _normalize(raw)
        warnings = result.get("validation_warnings") or []
        msg = next(
            (w for w in warnings if "mechanism_subtype dropped" in w),
            None,
        )
        self.assertIsNotNone(msg)
        self.assertIn("hawkish_surprise", msg)
        self.assertIn("bank_stress", msg)


# ---------------------------------------------------------------------------
# 3. No-subtype path: inference re-runs against the UPGRADED family
# ---------------------------------------------------------------------------


class InferenceReRunsAgainstUpgradedFamily(unittest.TestCase):

    def test_inference_finds_subtype_after_upgrade(self) -> None:
        # No LLM subtype.  Family upgrades to bank_stress; the
        # inference fallback should match ``regional bank`` /
        # ``deposit run`` → ``regional_bank_stress``.
        raw = _bank_stress_raw(llm_family="none", llm_subtype=None)
        result = _normalize(raw)
        self.assertEqual(result["mechanism_family"], "bank_stress")
        self.assertEqual(
            result.get("mechanism_subtype"), "regional_bank_stress",
            "inference must re-run against the upgraded family and "
            "pick a subtype that matches the prose",
        )


# ---------------------------------------------------------------------------
# 4. No fallback: pre-committed family + subtype both survive untouched
# ---------------------------------------------------------------------------


class FallbackNoOpPreservesSubtype(unittest.TestCase):

    def test_committed_family_skips_fallback_and_keeps_subtype(self) -> None:
        # When the LLM commits a family, the second-pass fallback is a
        # no-op (the function early-returns the committed value).  A
        # valid subtype carried alongside must survive.
        raw = _bank_stress_raw(
            llm_family="bank_stress", llm_subtype="regional_bank_stress",
        )
        result = _normalize(raw)
        self.assertEqual(result["mechanism_family"], "bank_stress")
        self.assertEqual(result.get("mechanism_subtype"), "regional_bank_stress")
        warnings = result.get("validation_warnings") or []
        self.assertFalse(any(
            "mechanism_subtype dropped" in w for w in warnings
        ))


# ---------------------------------------------------------------------------
# 5. Top-level family enum is never an invented token
# ---------------------------------------------------------------------------


class TopLevelFamilyEnumIntegrity(unittest.TestCase):

    def test_post_normalize_family_is_always_canonical(self) -> None:
        for llm_family in ("none", "bank_stress", ""):
            raw = _bank_stress_raw(llm_family=llm_family)
            result = _normalize(raw)
            self.assertIn(
                result["mechanism_family"], FAMILY_IDS,
                f"family produced a non-canonical token: "
                f"{result['mechanism_family']!r}",
            )

    def test_committed_subtype_is_in_family_registry_or_absent(self) -> None:
        raw = _bank_stress_raw(
            llm_family="none", llm_subtype="regional_bank_stress",
        )
        result = _normalize(raw)
        family = result["mechanism_family"]
        subtype = result.get("mechanism_subtype")
        if subtype is not None:
            self.assertIn(subtype, FAMILY_SUBTYPES.get(family, {}))


# ---------------------------------------------------------------------------
# 6. Old DB rows are NOT mutated on read
# ---------------------------------------------------------------------------


class OldRowsNotMutatedOnReadTests(unittest.TestCase):
    """The fallback / subtype-revalidation pipeline runs only inside
    ``_normalize_schema`` during fresh analysis.  DB reads must never
    silently rewrite the stored family / subtype, even when the
    legacy row carries a subtype that would now be considered invalid
    for its family — that's a data point the desk needs to see, not
    an error to paper over."""

    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._orig_db = db_module.DB_FILE
        db_module.DB_FILE = self._tmp.name
        db_module._db_ready = False
        init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._orig_db
        db_module._db_ready = False
        try:
            os.unlink(self._tmp.name)
        except (PermissionError, OSError):
            pass

    def _save_minimal(self, *, family: str) -> int:
        ev = {
            "headline":          "saved row",
            "stage":              "test",
            "persistence":        "1d",
            "what_changed":       "Silicon Valley Bank deposit run.",
            "mechanism_summary":  "Regional bank failure cascade.",
            "beneficiaries":      [],
            "losers":             ["KRE"],
            "assets_to_watch":    [],
            "confidence":         "medium",
            "market_note":        "",
            "market_tickers":     [],
            "event_date":         "2025-01-15",
            "notes":              "",
            "model":              "test-model",
            "mechanism_family":   family,
        }
        save_event(ev)
        with sqlite3.connect(db_module.DB_FILE) as conn:
            (row_id,) = conn.execute(
                "SELECT id FROM events ORDER BY id DESC LIMIT 1",
            ).fetchone()
        return row_id

    def test_load_event_by_id_returns_stored_family_verbatim(self) -> None:
        """Even when the stored family is ``"none"`` and the prose
        would imply a fallback upgrade, the read path must surface
        ``"none"`` — the upgrade only fires during fresh analysis."""
        row_id = self._save_minimal(family="none")
        loaded = load_event_by_id(row_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["mechanism_family"], "none")

    def test_decode_event_row_does_not_call_family_inference(self) -> None:
        """Sanity: decoding a row gives us the stored family verbatim."""
        self._save_minimal(family="none")
        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM events LIMIT 1").fetchone()
        ev = _decode_event_row(row)
        self.assertEqual(ev["mechanism_family"], "none")

    def test_committed_family_on_disk_is_not_re_resolved(self) -> None:
        row_id = self._save_minimal(family="bank_stress")
        loaded = load_event_by_id(row_id)
        self.assertEqual(loaded["mechanism_family"], "bank_stress")


if __name__ == "__main__":
    unittest.main()
