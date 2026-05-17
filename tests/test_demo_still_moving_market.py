"""Tests for ``routes/demo_still_moving.py``.

The demo Still Moving Market source is a read-only projection over an
existing persistent / still-moving candidate stream.  It surfaces only
strict eligible Still Moving candidates and refuses weak sector / index
primary reads.

Read-only contract:

* No DB writes, no ``yfinance`` / ``market_data`` / paid provider /
  LLM import, no FastAPI surface imported at module load.
* No mutation of the input candidate list.
* Not registered in ``api.py``.

What the tests pin:

* Output envelope keys:
  ``ok``, ``section`` (== ``"still_moving"``), ``items``, ``count``,
  ``rejected_count``, ``rejection_summary``, ``warnings``, ``errors``.
* Each surfaced item carries ``event_id``, ``headline``, ``event_date``,
  a primary-ticker identifier (``primary_ticker`` or ``top_mover``),
  ``persistence_signal`` when available on the source card,
  ``evidence_reason`` (from the pinned ``SURFACED_REASONS`` vocabulary),
  and a non-empty ``caution_label``.
* Sector-ETF primary reads (XLE, SPY, ...) are rejected with reason
  ``sector_etf_as_primary``.
* Non-supportive / falsified / low-info / stale / lower-conviction /
  non-high-impact candidates are rejected and never surface.
* Empty input → ``ok=True``, ``count=0``, ``rejection_summary={}``.
* All-rejected input → ``ok=True``, ``count=0``, non-empty
  ``rejection_summary``.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mover_card_normalizer import SURFACED_REASONS  # noqa: E402
from routes import demo_still_moving as dsm  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _we(label: str = "supportive", score: float = 0.7) -> dict:
    return {
        "evidence_label":    label,
        "evidence_score":    score,
        "evidence_reasons":  [],
        "scored_tickers":    2,
        "total_tickers":     2,
        "tag_only_tickers":  0,
        "evidence_basis":    "evidence_scores",
    }


def _eligible_card(**overrides) -> dict:
    """A card that passes ``is_high_conviction_persistent`` end-to-end."""
    base: dict = {
        "event_id":          1,
        "headline":          "OPEC cuts oil supply, prices rip higher",
        "event_date":        "2025-04-12",
        "mechanism_family":  "commodity_squeeze",
        "thesis_state":      "confirming",
        "stale_signal":      "fresh",
        "weighted_evidence": _we("supportive", 0.8),
        "has_proof_set":     True,
        "has_falsifiers":    True,
        "low_information":   False,
        "tickers": [
            {"symbol": "XOM", "role": "beneficiary", "return_5d": 5.0},
            {"symbol": "CVX", "role": "beneficiary", "return_5d": 3.0},
        ],
        "conviction": {"conviction_class": "conviction", "impact_level": "high"},
        "persistence_signal": "Holding",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


_REQUIRED_TOP_KEYS = (
    "ok",
    "section",
    "items",
    "count",
    "rejected_count",
    "rejection_summary",
    "warnings",
    "errors",
)


class TestEnvelopeShape(unittest.TestCase):
    def test_required_top_keys_present(self):
        env = dsm.build_demo_still_moving_market(candidates=[_eligible_card()])
        for key in _REQUIRED_TOP_KEYS:
            self.assertIn(key, env, f"missing top-level key {key!r}")

    def test_no_extra_top_keys(self):
        env = dsm.build_demo_still_moving_market(candidates=[_eligible_card()])
        self.assertEqual(set(env.keys()), set(_REQUIRED_TOP_KEYS))

    def test_section_is_still_moving(self):
        env = dsm.build_demo_still_moving_market(candidates=[])
        self.assertEqual(env["section"], "still_moving")

    def test_empty_candidates_returns_ok_true_count_zero(self):
        env = dsm.build_demo_still_moving_market(candidates=[])
        self.assertTrue(env["ok"])
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["items"], [])
        self.assertEqual(env["rejected_count"], 0)
        self.assertEqual(env["rejection_summary"], {})
        self.assertEqual(env["errors"], [])
        self.assertEqual(env["warnings"], [])

    def test_none_candidates_treated_as_empty(self):
        env = dsm.build_demo_still_moving_market(candidates=None)
        self.assertTrue(env["ok"])
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["items"], [])

    def test_all_rejected_still_ok_with_summary(self):
        env = dsm.build_demo_still_moving_market(
            candidates=[_eligible_card(stale_signal="stale")],
        )
        self.assertTrue(env["ok"])
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["rejected_count"], 1)
        self.assertGreater(sum(env["rejection_summary"].values()), 0)

    def test_count_matches_items_length(self):
        env = dsm.build_demo_still_moving_market(candidates=[
            _eligible_card(event_id=1),
            _eligible_card(event_id=2),
        ])
        self.assertEqual(env["count"], len(env["items"]))


# ---------------------------------------------------------------------------
# Eligibility — strict high-conviction gate
# ---------------------------------------------------------------------------


class TestEligibility(unittest.TestCase):
    def test_eligible_card_surfaces(self):
        env = dsm.build_demo_still_moving_market(candidates=[_eligible_card()])
        self.assertEqual(env["count"], 1)
        self.assertEqual(env["rejected_count"], 0)
        self.assertEqual(env["items"][0]["event_id"], 1)

    def test_sector_etf_primary_rejected(self):
        # XLE is the strongest |return_5d| → sector-ETF primary read.
        card = _eligible_card(tickers=[
            {"symbol": "XLE", "role": "beneficiary", "return_5d": 4.0},
            {"symbol": "XOM", "role": "beneficiary", "return_5d": 2.0},
        ])
        env = dsm.build_demo_still_moving_market(candidates=[card])
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["rejected_count"], 1)
        self.assertEqual(
            env["rejection_summary"].get("sector_etf_as_primary"), 1,
        )

    def test_spy_primary_rejected(self):
        card = _eligible_card(tickers=[
            {"symbol": "SPY", "role": "beneficiary", "return_5d": 3.5},
        ])
        env = dsm.build_demo_still_moving_market(candidates=[card])
        self.assertEqual(env["count"], 0)
        self.assertEqual(
            env["rejection_summary"].get("sector_etf_as_primary"), 1,
        )

    def test_sector_etf_when_not_top_mover_does_not_reject(self):
        # XLE is on the card but XOM is the stronger mover — the read
        # is a single-name story so the demo surface admits it.
        card = _eligible_card(tickers=[
            {"symbol": "XOM", "role": "beneficiary", "return_5d": 5.0},
            {"symbol": "XLE", "role": "beneficiary", "return_5d": 4.0},
        ])
        env = dsm.build_demo_still_moving_market(candidates=[card])
        self.assertEqual(env["count"], 1)
        self.assertEqual(env["rejected_count"], 0)

    def test_non_supportive_evidence_rejected(self):
        for label in ("mixed", "insufficient", "contradictory"):
            card = _eligible_card(weighted_evidence=_we(label, 0.0))
            env = dsm.build_demo_still_moving_market(candidates=[card])
            self.assertEqual(env["count"], 0,
                             f"label={label!r} should not surface")

    def test_falsified_thesis_rejected(self):
        card = _eligible_card(
            thesis_state="falsified",
            weighted_evidence=_we("contradictory", -0.6),
        )
        env = dsm.build_demo_still_moving_market(candidates=[card])
        self.assertEqual(env["count"], 0)
        self.assertGreater(env["rejected_count"], 0)

    def test_low_information_rejected(self):
        card = _eligible_card(low_information=True)
        env = dsm.build_demo_still_moving_market(candidates=[card])
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["rejection_summary"].get("low_information"), 1)

    def test_stale_rejected(self):
        card = _eligible_card(stale_signal="stale")
        env = dsm.build_demo_still_moving_market(candidates=[card])
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["rejection_summary"].get("stale"), 1)

    def test_legacy_rejected(self):
        card = _eligible_card(stale_signal="legacy")
        env = dsm.build_demo_still_moving_market(candidates=[card])
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["rejection_summary"].get("legacy"), 1)

    def test_lower_conviction_class_rejected(self):
        card = _eligible_card(
            conviction={"conviction_class": "secondary", "impact_level": "high"},
        )
        env = dsm.build_demo_still_moving_market(candidates=[card])
        self.assertEqual(env["count"], 0)
        self.assertEqual(
            env["rejection_summary"].get("not_conviction_class"), 1,
        )

    def test_non_high_impact_rejected(self):
        card = _eligible_card(
            conviction={"conviction_class": "conviction", "impact_level": "medium"},
        )
        env = dsm.build_demo_still_moving_market(candidates=[card])
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["rejection_summary"].get("not_high_impact"), 1)

    def test_missing_conviction_rejected(self):
        card = _eligible_card()
        card.pop("conviction", None)
        env = dsm.build_demo_still_moving_market(candidates=[card])
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["rejection_summary"].get("missing_conviction"), 1)

    def test_non_dict_candidate_does_not_crash(self):
        env = dsm.build_demo_still_moving_market(
            candidates=[None, "garbage", 42, _eligible_card()],
        )
        # The one eligible card surfaces; the three garbage entries are
        # rejected as malformed.
        self.assertEqual(env["count"], 1)
        self.assertEqual(env["rejected_count"], 3)
        self.assertEqual(env["rejection_summary"].get("malformed_card"), 3)

    def test_mix_of_eligible_and_rejected(self):
        ok = _eligible_card(event_id=10)
        sector_etf = _eligible_card(event_id=20, tickers=[
            {"symbol": "XLE", "role": "beneficiary", "return_5d": 4.0},
        ])
        weak = _eligible_card(
            event_id=30, weighted_evidence=_we("insufficient", 0.0),
        )
        env = dsm.build_demo_still_moving_market(
            candidates=[ok, sector_etf, weak],
        )
        self.assertEqual(env["count"], 1)
        self.assertEqual(env["items"][0]["event_id"], 10)
        self.assertEqual(env["rejected_count"], 2)


# ---------------------------------------------------------------------------
# Item shape
# ---------------------------------------------------------------------------


class TestItemShape(unittest.TestCase):
    def _surface_one(self, **overrides) -> dict:
        env = dsm.build_demo_still_moving_market(
            candidates=[_eligible_card(**overrides)],
        )
        self.assertEqual(env["count"], 1, f"expected 1 surfaced item: {env!r}")
        return env["items"][0]

    def test_item_carries_event_id(self):
        item = self._surface_one(event_id=7)
        self.assertEqual(item["event_id"], 7)

    def test_item_carries_headline_and_event_date(self):
        item = self._surface_one(
            headline="OPEC cuts oil supply, prices rip higher",
            event_date="2025-04-12",
        )
        self.assertEqual(item["headline"], "OPEC cuts oil supply, prices rip higher")
        self.assertEqual(item["event_date"], "2025-04-12")

    def test_item_primary_ticker_or_top_mover_identifies_single_name(self):
        item = self._surface_one()
        sym = item.get("primary_ticker") or item.get("top_mover")
        self.assertEqual(sym, "XOM", f"unexpected primary: {item!r}")

    def test_persistence_signal_passthrough_when_present(self):
        item = self._surface_one(persistence_signal="Holding")
        self.assertEqual(item.get("persistence_signal"), "Holding")

    def test_persistence_signal_none_when_absent(self):
        # When the source card carries no persistence_signal, the item
        # must report ``None`` — never invent one.
        card = _eligible_card()
        card.pop("persistence_signal", None)
        env = dsm.build_demo_still_moving_market(candidates=[card])
        self.assertIsNone(env["items"][0]["persistence_signal"])

    def test_evidence_reason_from_pinned_vocabulary(self):
        item = self._surface_one()
        self.assertIn(item["evidence_reason"], SURFACED_REASONS)

    def test_caution_label_non_empty_string(self):
        item = self._surface_one()
        self.assertIsInstance(item["caution_label"], str)
        self.assertTrue(item["caution_label"].strip(),
                        f"caution_label empty: {item!r}")


# ---------------------------------------------------------------------------
# Conservative language — no strong-claim tokens anywhere in the output
# ---------------------------------------------------------------------------


class TestConservativeLanguage(unittest.TestCase):
    _BANNED = (
        "demo-ready", "guaranteed", "must-buy", "must buy",
        "winner", "winners", "stunning", "amazing",
        "definitely", "100%",
    )

    def _all_strings(self, obj) -> list[str]:
        if isinstance(obj, dict):
            out: list[str] = []
            for v in obj.values():
                out.extend(self._all_strings(v))
            return out
        if isinstance(obj, list):
            out = []
            for v in obj:
                out.extend(self._all_strings(v))
            return out
        if isinstance(obj, str):
            return [obj]
        return []

    def test_no_banned_tokens_in_envelope(self):
        env = dsm.build_demo_still_moving_market(
            candidates=[_eligible_card()],
        )
        joined = " ".join(self._all_strings(env)).lower()
        for token in self._BANNED:
            self.assertNotIn(token, joined,
                             f"banned token {token!r} in output")


# ---------------------------------------------------------------------------
# Read-only contract — no mutation, no DB / paid / FastAPI imports
# ---------------------------------------------------------------------------


_BANNED_TOP_LEVEL_IMPORTS = frozenset({
    "yfinance",
    "market_data",
    "db",
    "openai",
    "anthropic",
    "fastapi",
    "providers",
})


def _module_top_level_imports(src_path: Path) -> set[str]:
    """Return the top-level module names imported by the file at ``src_path``.

    AST-based so the test never imports the module and never triggers
    a transitive paid / DB module load itself.
    """
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    seen.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                seen.add(node.module.split(".")[0])
    return seen


class TestReadOnlyContract(unittest.TestCase):
    def setUp(self) -> None:
        self.src_path = (
            Path(__file__).resolve().parents[1] / "routes" / "demo_still_moving.py"
        )

    def test_input_candidates_not_mutated(self):
        card = _eligible_card()
        snapshot = json.loads(json.dumps(card))
        dsm.build_demo_still_moving_market(candidates=[card])
        self.assertEqual(card, snapshot,
                         "demo source must not mutate its input cards")

    def test_input_list_not_mutated(self):
        cards = [_eligible_card(event_id=1), _eligible_card(event_id=2)]
        before_len = len(cards)
        dsm.build_demo_still_moving_market(candidates=cards)
        self.assertEqual(len(cards), before_len)

    def test_module_top_level_imports_are_clean(self):
        seen = _module_top_level_imports(self.src_path)
        leaked = seen & _BANNED_TOP_LEVEL_IMPORTS
        self.assertFalse(
            leaked,
            f"demo source must not import {sorted(leaked)} at module load",
        )

    def test_registered_under_demo_namespace_in_api(self):
        """The demo Still Moving source is wired in ``api.py`` under
        ``/demo/still-moving-market``.  This pin replaces the earlier
        "not-yet-registered" pin once the wiring landed.
        """
        api_text = (
            Path(__file__).resolve().parents[1] / "api.py"
        ).read_text(encoding="utf-8")
        self.assertIn("/demo/still-moving-market", api_text)
        self.assertIn("demo_still_moving", api_text)


if __name__ == "__main__":
    unittest.main()
