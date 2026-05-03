"""
tests/test_validation_outcome_coverage.py

Closes the remaining direct ``validation_outcome`` coverage gap and
locks in the regression for the ``_has_broad_beta_only`` fix.

The other six bullets from the contract — eligibility-tier transitions,
confidence ceilings, direction-tag enum branches, rejected-asset
exclusion, signal-vs-primary weighting, and explicit-primary > secondary
ordering — are already covered by ``tests/test_weighted_evidence.py``
and ``tests/test_primary_weighting_safety.py``.  This file adds the
missing seventh bullet (unknown / unmapped → not primary by default)
and a focused regression test for the edge case it surfaced:
``low_information_gate._has_broad_beta_only`` was calling
``_ticker_contribution`` without ``explicit_primary``, so unknown
alpha-only tickers silently inherited the legacy heuristic's "primary"
tier and masked the broad-beta-tape-following warning.

Plus a label / shape stability check covering the public output of
``score_weighted_evidence`` so this hardening cannot accidentally drop
or rename a documented field.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from low_information_gate import _has_broad_beta_only
from validation_outcome import (
    EVIDENCE_LABELS,
    _eligibility_tier,
    _extract_primary_set,
    _ticker_contribution,
    score_weighted_evidence,
)


# ---------------------------------------------------------------------------
# 1. Unknown / unmapped tickers must not become primary by default
# ---------------------------------------------------------------------------
# An event whose ``primary_assets`` block names no symbols (analyst did
# not commit a direct-name pick) still goes through the same scoring
# path.  An unknown alpha-only ticker like ``ZZZX`` must NOT be
# silently promoted to primary tier because the legacy back-compat
# heuristic treats any 1-5 char alpha string as a single name.


class UnknownNotPrimaryByDefaultTests(unittest.TestCase):

    def test_unknown_alpha_with_explicit_empty_set_lands_secondary(self) -> None:
        """When the event explicitly supplies an empty ``primary_assets``
        set, an unknown alpha ticker must land in ``secondary`` (or
        ``rejected`` if the shape fails) — never ``primary``."""
        self.assertEqual(
            _eligibility_tier("ZZZX", explicit_primary=set()),
            "secondary",
        )
        self.assertEqual(
            _eligibility_tier("FAKE", explicit_primary=set()),
            "secondary",
        )

    def test_unknown_dotted_with_explicit_set_rejected(self) -> None:
        self.assertEqual(
            _eligibility_tier("ABC.XYZ", explicit_primary=set()),
            "rejected",
        )
        self.assertEqual(
            _eligibility_tier("^GSPC", explicit_primary=set()),
            "rejected",
        )

    def test_explicit_set_required_for_primary_tier(self) -> None:
        explicit = {"CVX"}
        # Symbol in set → primary.
        self.assertEqual(
            _eligibility_tier("CVX", explicit_primary=explicit),
            "primary",
        )
        # Same shape but absent from set → secondary, NOT primary.
        self.assertEqual(
            _eligibility_tier("XOM", explicit_primary=explicit),
            "secondary",
        )
        # Off-shape unknown outside the set → rejected.
        self.assertEqual(
            _eligibility_tier("BRK.B", explicit_primary=explicit),
            "rejected",
        )

    def test_extract_primary_set_returns_none_when_field_absent(self) -> None:
        """Legacy events without the ``primary_assets`` field return
        ``None`` so the call site can decide whether to apply the
        tightened legacy heuristic.  A returned ``None`` here means the
        caller is responsible for deciding the strict-mode fallback."""
        self.assertIsNone(_extract_primary_set({}))
        # Non-list value is also legacy / corrupt — same contract.
        self.assertIsNone(_extract_primary_set({"primary_assets": None}))
        self.assertIsNone(_extract_primary_set({"primary_assets": "a string"}))

    def test_extract_primary_set_returns_empty_set_when_field_empty(self) -> None:
        """An explicit empty list signals "analyst named no primary
        picks" and engages strict mode — distinct from the legacy
        ``None`` case."""
        self.assertEqual(_extract_primary_set({"primary_assets": []}), set())


# ---------------------------------------------------------------------------
# 2. _has_broad_beta_only regression — explicit_primary now threaded
# ---------------------------------------------------------------------------
# Before the fix, the gate called ``_ticker_contribution(t)`` with no
# event context.  Two unknown alpha tickers ``"ZZZX"`` and ``"YYYW"``
# would silently land in ``primary`` tier via the legacy heuristic, the
# aggregate score would clear the supportive band, and the gate would
# read ``primary_supports = True`` — concluding the basket was NOT
# broad-beta-only when in fact it was.
# After the fix the gate threads ``_extract_primary_set(event)``;
# when the analyst supplied no primary picks, the unknown supporters
# stay in secondary and the gate fires as intended.


class BroadBetaOnlyExplicitPrimaryTests(unittest.TestCase):

    def _event(
        self,
        *,
        symbols: list[str],
        primary_assets: list | None,
        contribution: float = 0.7,
    ) -> dict:
        ev: dict = {
            "market_tickers": [
                {"symbol": s, "evidence_score": contribution,
                 "direction_tag": "supports up"}
                for s in symbols
            ],
        }
        if primary_assets is not None:
            ev["primary_assets"] = primary_assets
        return ev

    def test_unknown_supporters_with_empty_primary_assets_fires_broad_beta(
        self,
    ) -> None:
        """Analyst named no primary picks; unknown alpha tickers must
        not be silently treated as primary supports."""
        ev = self._event(
            symbols=["ZZZX", "YYYW"],
            primary_assets=[],
        )
        self.assertTrue(
            _has_broad_beta_only(ev),
            "broad-beta gate must fire when no analyst-named primary "
            "supports the thesis — unknown tickers don't count",
        )

    def test_named_primary_support_does_not_fire_broad_beta(self) -> None:
        """Sanity check on the gate: a basket with a named primary
        supporter and ETF backing must NOT fire broad-beta."""
        ev = self._event(
            symbols=["CVX", "XLE"],
            primary_assets=[{"symbol": "CVX", "rationale": "direct"}],
        )
        self.assertFalse(_has_broad_beta_only(ev))

    def test_etf_only_basket_with_no_primary_picks_fires_broad_beta(
        self,
    ) -> None:
        """ETF tickers (XLE / USO) are mapped to channels and land in
        secondary tier regardless of explicit_primary — a basket of
        them with no primary support is the canonical broad-beta-only
        situation the gate exists to flag."""
        ev = self._event(
            symbols=["XLE", "USO"],
            primary_assets=[],
        )
        self.assertTrue(_has_broad_beta_only(ev))

    def test_legacy_event_no_primary_assets_field_uses_legacy_heuristic(
        self,
    ) -> None:
        """When the event predates the ``primary_assets`` field
        entirely, ``_extract_primary_set`` returns ``None`` and the
        legacy back-compat heuristic applies.  Behaviour for those
        events is preserved — the fix only tightens the explicit-set
        path."""
        ev = self._event(
            symbols=["ZZZX", "YYYW"],
            primary_assets=None,  # field absent
        )
        # Legacy heuristic treats alpha-only symbols as primary, so
        # the gate does NOT fire.  This documents the back-compat
        # boundary; new rows always carry primary_assets and use the
        # explicit path.
        self.assertFalse(_has_broad_beta_only(ev))


# ---------------------------------------------------------------------------
# 3. Output label / shape stability
# ---------------------------------------------------------------------------


class OutputShapeStabilityTests(unittest.TestCase):
    """The contract pins ``score_weighted_evidence``'s public keys.
    Hardening rules around tier weighting must never accidentally
    rename or drop one of the documented response fields."""

    _EXPECTED_KEYS = {
        "evidence_label",
        "evidence_score",
        "evidence_reasons",
        "scored_tickers",
        "total_tickers",
        "tag_only_tickers",
        "evidence_basis",
    }

    def test_supportive_basket_has_canonical_keys(self) -> None:
        out = score_weighted_evidence(
            [
                {"symbol": "CVX", "evidence_score": 0.7,
                 "direction_tag": "supports up"},
                {"symbol": "XOM", "evidence_score": 0.7,
                 "direction_tag": "supports up"},
            ],
            explicit_primary={"CVX", "XOM"},
        )
        self.assertEqual(set(out.keys()), self._EXPECTED_KEYS)
        self.assertIn(out["evidence_label"], EVIDENCE_LABELS)

    def test_insufficient_basket_has_canonical_keys(self) -> None:
        out = score_weighted_evidence([])
        self.assertEqual(set(out.keys()), self._EXPECTED_KEYS)
        self.assertEqual(out["evidence_label"], "insufficient")
        self.assertEqual(out["scored_tickers"], 0)

    def test_evidence_label_always_in_canonical_enum(self) -> None:
        for basket in (
            None,
            [],
            [{"symbol": "CVX", "evidence_score": 0.99}],
            [{"symbol": "CVX", "evidence_score": -0.99},
             {"symbol": "XOM", "evidence_score": -0.99}],
        ):
            out = score_weighted_evidence(basket, explicit_primary={"CVX", "XOM"})
            self.assertIn(out["evidence_label"], EVIDENCE_LABELS)


# ---------------------------------------------------------------------------
# 4. _ticker_contribution direct contract — explicit_primary thread
# ---------------------------------------------------------------------------


class TickerContributionExplicitPrimaryTests(unittest.TestCase):
    """Direct unit-level coverage of the threading boundary the
    broad-beta fix relies on.  A symbol's tier — and therefore its
    contribution weight — must respond to the supplied explicit set."""

    def test_unknown_alpha_secondary_under_explicit_set(self) -> None:
        row = _ticker_contribution(
            {"symbol": "ZZZX", "direction_tag": "supports up"},
            explicit_primary=set(),
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["eligibility_tier"], "secondary")

    def test_unknown_alpha_primary_via_legacy_path(self) -> None:
        row = _ticker_contribution(
            {"symbol": "ZZZX", "direction_tag": "supports up"},
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["eligibility_tier"], "primary")

    def test_named_primary_outweighs_secondary_contribution(self) -> None:
        primary_row = _ticker_contribution(
            {"symbol": "CVX", "evidence_score": 0.6},
            explicit_primary={"CVX"},
        )
        secondary_row = _ticker_contribution(
            {"symbol": "ZZZX", "evidence_score": 0.6},
            explicit_primary={"CVX"},
        )
        self.assertGreater(
            primary_row["contribution"],
            secondary_row["contribution"],
        )


if __name__ == "__main__":
    unittest.main()
