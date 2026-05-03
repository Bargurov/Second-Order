"""Tests for track_record_breakdown — mechanism/regime/compound breakdowns."""

import json
import os
import sqlite3
import sys
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
from track_record_breakdown import (
    compute_track_record_breakdown,
    _score_event,
    _family_key,
    _regime_key,
    _compound_key,
    _policy_status_key,
    _vulnerability_key,
    _FAMILY_LABELS,
    _COMPOUND_LABELS,
    POLICY_STATUS_BUCKETS,
    VULNERABILITY_BUCKETS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ticker(symbol: str, direction: str, r5: float | None = None,
            r20: float | None = None) -> dict:
    return {
        "symbol": symbol, "role": "beneficiary",
        "direction_tag": direction,
        "return_5d": r5, "return_20d": r20,
    }


def _regime(**overrides) -> dict:
    base = {
        "available": True,
        "inflation":     "hot",
        "policy_stance": "hawkish",
        "fx":            "dollar_strong",
        "growth_stress": "calm",
        "credit":        "risk_on",
    }
    base.update(overrides)
    return base


def _event(
    family: str = "supply_shock",
    tickers: list[dict] | None = None,
    revisit: list[dict] | None = None,
    regime: dict | None = None,
) -> dict:
    return {
        "mechanism_family":   family,
        "market_tickers":     tickers if tickers is not None else
                               [_ticker("SPY", "supports_thesis", 2.0, 4.0)],
        "revisit_snapshots":  revisit or [],
        "regime_snapshot":    regime if regime is not None else _regime(),
    }


# ---------------------------------------------------------------------------
# _score_event — delegates to db._score_directions
# ---------------------------------------------------------------------------


class TestScoreEvent(unittest.TestCase):
    def test_validated_on_supports_tag(self):
        ev = _event()
        out = _score_event(ev["market_tickers"], ev["revisit_snapshots"])
        self.assertEqual(out["outcome"], "validated")
        self.assertTrue(out["has_direction"])

    def test_contradicted_on_contradicts_tag(self):
        ev = _event(tickers=[_ticker("SPY", "contradicts_thesis")])
        out = _score_event(ev["market_tickers"], ev["revisit_snapshots"])
        self.assertEqual(out["outcome"], "contradicted")

    def test_unresolved_when_no_direction_tags(self):
        ev = _event(tickers=[_ticker("SPY", "")])
        out = _score_event(ev["market_tickers"], ev["revisit_snapshots"])
        self.assertEqual(out["outcome"], "unresolved")
        self.assertFalse(out["has_direction"])

    def test_revisit_snapshot_preferred_when_present(self):
        """A 20d revisit with a contradicts direction overrides a
        supports direction on the initial market_tickers."""
        initial = [_ticker("SPY", "supports_thesis", 2.0)]
        revisit = [{
            "day": 20, "captured_at": "2026-01-01",
            "tickers": [{"symbol": "SPY", "direction": "contradicts_thesis",
                         "return_20d": -1.5}],
        }]
        out = _score_event(initial, revisit)
        self.assertEqual(out["outcome"], "contradicted")
        self.assertTrue(out["revisit_scored"])
        # Returns come from the revisit source (same priority).
        self.assertAlmostEqual(out["best_return_20d"], -1.5)

    def test_best_return_picks_largest_absolute(self):
        tickers = [
            _ticker("A", "supports_thesis", 1.0, 2.0),
            _ticker("B", "supports_thesis", -3.5, -0.5),
        ]
        out = _score_event(tickers, [])
        self.assertAlmostEqual(out["best_return_5d"],  -3.5)
        self.assertAlmostEqual(out["best_return_20d"],  2.0)

    def test_support_ratio_reflects_mix(self):
        tickers = [
            _ticker("A", "supports_thesis"),
            _ticker("B", "contradicts_thesis"),
            _ticker("C", "supports_thesis"),
        ]
        out = _score_event(tickers, [])
        self.assertAlmostEqual(out["support_ratio"], 2 / 3)


# ---------------------------------------------------------------------------
# Key extraction
# ---------------------------------------------------------------------------


class TestKeyExtraction(unittest.TestCase):
    def test_family_key_defaults_to_unclassified(self):
        self.assertEqual(_family_key({}), "unclassified")
        self.assertEqual(_family_key({"mechanism_family": ""}), "unclassified")
        self.assertEqual(_family_key({"mechanism_family": "supply_shock"}),
                         "supply_shock")

    def test_regime_key_only_returns_meaningful_pairs(self):
        self.assertEqual(_regime_key(_regime()), ("hot", "hawkish"))
        self.assertIsNone(_regime_key({"available": False}))
        self.assertIsNone(_regime_key(_regime(inflation="neutral")))
        self.assertIsNone(_regime_key(None))
        self.assertIsNone(_regime_key({}))

    def test_compound_key_passes_through_real_labels(self):
        r = _regime()
        r["compound"] = {"label": "stagflation_pulse", "confidence": 0.8}
        self.assertEqual(_compound_key(r), "stagflation_pulse")

    def test_compound_key_none_on_unavailable_or_empty(self):
        self.assertIsNone(_compound_key(_regime()))  # no compound key
        r = _regime()
        r["compound"] = {"label": "none"}
        self.assertIsNone(_compound_key(r))
        r["compound"] = {"label": ""}
        self.assertIsNone(_compound_key(r))


# ---------------------------------------------------------------------------
# compute_track_record_breakdown — the headline composer
# ---------------------------------------------------------------------------


class TestBreakdownComposer(unittest.TestCase):

    def test_empty_input_returns_stable_shape(self):
        out = compute_track_record_breakdown([])
        self.assertEqual(out["total_events"], 0)
        self.assertEqual(out["by_mechanism_family"], [])
        self.assertEqual(out["by_regime"], [])
        self.assertEqual(out["by_compound_regime"], [])
        self.assertIsNone(out["hit_rate"])

    def test_single_event_populates_every_breakdown_bucket(self):
        r = _regime()
        r["compound"] = {"label": "reflation", "confidence": 0.8}
        events = [_event(regime=r)]
        out = compute_track_record_breakdown(events)

        self.assertEqual(out["total_events"], 1)
        self.assertEqual(out["validated_total"], 1)

        self.assertEqual(len(out["by_mechanism_family"]), 1)
        self.assertEqual(out["by_mechanism_family"][0]["family"], "supply_shock")
        self.assertEqual(out["by_mechanism_family"][0]["total"], 1)
        self.assertEqual(out["by_mechanism_family"][0]["validated"], 1)

        self.assertEqual(len(out["by_regime"]), 1)
        self.assertEqual(out["by_regime"][0]["regime_key"], "hot/hawkish")

        self.assertEqual(len(out["by_compound_regime"]), 1)
        self.assertEqual(out["by_compound_regime"][0]["state"], "reflation")

    def test_hit_rate_is_validated_over_directional(self):
        events = [
            _event(family="tariff", tickers=[_ticker("A", "supports_thesis", 2.0)]),
            _event(family="tariff", tickers=[_ticker("A", "supports_thesis", 3.0)]),
            _event(family="tariff", tickers=[_ticker("A", "contradicts_thesis", -1.0)]),
            _event(family="tariff", tickers=[_ticker("A", "")]),
        ]
        out = compute_track_record_breakdown(events)
        fam = next(g for g in out["by_mechanism_family"] if g["family"] == "tariff")
        # 2 validated + 1 contradicted = 3 directional; 2/3 hit rate.
        self.assertEqual(fam["validated"], 2)
        self.assertEqual(fam["contradicted"], 1)
        self.assertEqual(fam["unresolved"], 1)
        self.assertAlmostEqual(fam["hit_rate"], round(2 / 3, 3))
        # Coverage = directional / total.
        self.assertAlmostEqual(fam["coverage"], round(3 / 4, 3))

    def test_avg_returns_are_means_of_best_ticker_returns(self):
        events = [
            _event(family="tariff", tickers=[_ticker("A", "supports_thesis", 4.0, 6.0)]),
            _event(family="tariff", tickers=[_ticker("A", "supports_thesis", 2.0, 4.0)]),
        ]
        out = compute_track_record_breakdown(events)
        fam = next(g for g in out["by_mechanism_family"] if g["family"] == "tariff")
        self.assertAlmostEqual(fam["avg_return_5d"],  3.0)
        self.assertAlmostEqual(fam["avg_return_20d"], 5.0)

    def test_json_string_fields_are_decoded(self):
        """The composer must tolerate raw sqlite3.Row-style strings on
        market_tickers / revisit_snapshots / regime_snapshot."""
        r = _regime()
        r["compound"] = {"label": "reflation"}
        ev = {
            "mechanism_family":  "supply_shock",
            "market_tickers":    json.dumps([_ticker("A", "supports_thesis", 2.0)]),
            "revisit_snapshots": json.dumps([]),
            "regime_snapshot":   json.dumps(r),
        }
        out = compute_track_record_breakdown([ev])
        self.assertEqual(out["total_events"], 1)
        self.assertEqual(out["validated_total"], 1)
        self.assertEqual(len(out["by_regime"]), 1)
        self.assertEqual(out["by_regime"][0]["inflation"], "hot")

    def test_regime_bucket_skips_unavailable_snapshots(self):
        events = [
            _event(regime={"available": False}),
            _event(),  # valid default regime
        ]
        out = compute_track_record_breakdown(events)
        # Every event lands in family totals (2), but only the valid one
        # lands in the regime breakdown.
        self.assertEqual(out["total_events"], 2)
        fam = out["by_mechanism_family"][0]
        self.assertEqual(fam["total"], 2)
        self.assertEqual(len(out["by_regime"]), 1)
        self.assertEqual(out["by_regime"][0]["total"], 1)

    def test_groups_sorted_by_sample_size_descending(self):
        events = [
            # 3 tariff events
            _event(family="tariff"),
            _event(family="tariff"),
            _event(family="tariff"),
            # 1 sanction event
            _event(family="sanction"),
        ]
        out = compute_track_record_breakdown(events)
        families = [g["family"] for g in out["by_mechanism_family"]]
        self.assertEqual(families, ["tariff", "sanction"])

    def test_family_label_uses_canonical_name(self):
        out = compute_track_record_breakdown([_event(family="supply_shock")])
        fam = out["by_mechanism_family"][0]
        self.assertEqual(fam["family_label"],
                         _FAMILY_LABELS["supply_shock"])

    def test_compound_label_uses_canonical_name(self):
        r = _regime()
        r["compound"] = {"label": "reflation"}
        out = compute_track_record_breakdown([_event(regime=r)])
        self.assertEqual(out["by_compound_regime"][0]["label"],
                         _COMPOUND_LABELS["reflation"])

    def test_finalized_groups_dont_carry_private_accumulator_keys(self):
        out = compute_track_record_breakdown([_event()])
        fam = out["by_mechanism_family"][0]
        for k in fam:
            self.assertFalse(k.startswith("_"),
                             f"Private accumulator key leaked: {k!r}")


# ---------------------------------------------------------------------------
# Endpoint wiring — hits the real DB
# ---------------------------------------------------------------------------


class TestEndpointWiring(unittest.TestCase):
    """Verify /stats/track-record/breakdown routes through the composer
    and returns the documented shape against a freshly-seeded DB."""

    def setUp(self):
        self._orig = db.DB_FILE
        db.DB_FILE = os.path.join(
            os.path.dirname(__file__),
            f"test_trb_{uuid.uuid4().hex}.db",
        )
        db.init_db()
        from fastapi.testclient import TestClient
        from api import app
        self.client = TestClient(app)

    def tearDown(self):
        try:
            os.remove(db.DB_FILE)
        except (OSError, PermissionError):
            pass
        db.DB_FILE = self._orig

    def test_empty_db_returns_stable_shape(self):
        r = self.client.get("/stats/track-record/breakdown")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["total_events"], 0)
        self.assertEqual(body["by_mechanism_family"], [])
        self.assertEqual(body["by_regime"], [])
        self.assertEqual(body["by_compound_regime"], [])

    def test_seeded_events_surface_in_family_breakdown(self):
        # Seed two tariff events: one validated, one contradicted.
        regime_payload = _regime()
        regime_payload["compound"] = {"label": "reflation", "confidence": 0.8}
        db.save_event({
            "headline":         "Seed tariff validated",
            "stage":            "realized",
            "persistence":      "medium",
            "mechanism_family": "tariff",
            "event_date":       "2026-03-01",
            "regime_snapshot":  regime_payload,
            "market_tickers":   [_ticker("SPY", "supports_thesis", 2.5, 4.0)],
        })
        db.save_event({
            "headline":         "Seed tariff contradicted",
            "stage":            "realized",
            "persistence":      "medium",
            "mechanism_family": "tariff",
            "event_date":       "2026-03-02",
            "regime_snapshot":  regime_payload,
            "market_tickers":   [_ticker("SPY", "contradicts_thesis", -2.0, -1.0)],
        })

        # Ensure the column actually carries mechanism_family for sanity.
        with sqlite3.connect(db.DB_FILE) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
        self.assertIn("mechanism_family", cols)

        r = self.client.get("/stats/track-record/breakdown")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["total_events"], 2)
        fam = next(g for g in body["by_mechanism_family"]
                   if g["family"] == "tariff")
        self.assertEqual(fam["validated"], 1)
        self.assertEqual(fam["contradicted"], 1)
        self.assertAlmostEqual(fam["hit_rate"], 0.5)
        self.assertEqual(fam["total"], 2)

        # Regime breakdown picks up the shared regime snapshot.
        self.assertEqual(len(body["by_regime"]), 1)
        self.assertEqual(body["by_regime"][0]["inflation"], "hot")
        self.assertEqual(body["by_regime"][0]["total"], 2)

        # Compound regime picks up reflation.
        self.assertEqual(len(body["by_compound_regime"]), 1)
        self.assertEqual(body["by_compound_regime"][0]["state"], "reflation")


# ---------------------------------------------------------------------------
# Deterministic-context dimensions — policy_timing + country_vulnerability
# ---------------------------------------------------------------------------


class TestDeterministicContextKeys(unittest.TestCase):
    """Bucket-key extractors must read stored context only and reject any
    value outside the canonical enum so unknown / placeholder strings
    never pollute the breakdown."""

    def test_policy_status_passes_through_canonical_values(self):
        for status in POLICY_STATUS_BUCKETS:
            self.assertEqual(_policy_status_key({"status": status}), status)

    def test_policy_status_none_on_empty_or_unknown(self):
        self.assertIsNone(_policy_status_key(None))
        self.assertIsNone(_policy_status_key({}))
        self.assertIsNone(_policy_status_key({"status": ""}))
        self.assertIsNone(_policy_status_key({"status": "garbage"}))

    def test_vulnerability_passes_through_canonical_tiers(self):
        for tier in VULNERABILITY_BUCKETS:
            self.assertEqual(
                _vulnerability_key({"overall_vulnerability": tier}), tier,
            )

    def test_vulnerability_none_on_empty_or_unknown(self):
        self.assertIsNone(_vulnerability_key(None))
        self.assertIsNone(_vulnerability_key({}))
        self.assertIsNone(_vulnerability_key({"overall_vulnerability": None}))
        self.assertIsNone(_vulnerability_key({"overall_vulnerability": "elite"}))


class TestDeterministicContextBreakdown(unittest.TestCase):
    """compute_track_record_breakdown must surface the two new dimensions
    in fixed-enum order and skip events whose context block is empty."""

    def _ev(self, *, status=None, vuln=None, direction="supports_thesis",
            r5=2.0, r20=4.0):
        ev = _event(tickers=[_ticker("SPY", direction, r5, r20)])
        if status is not None:
            ev["policy_timing_context"] = {"status": status}
        if vuln is not None:
            ev["country_vulnerability_context"] = {
                "overall_vulnerability": vuln,
            }
        return ev

    def test_empty_input_emits_zeroed_buckets_in_canonical_order(self):
        out = compute_track_record_breakdown([])
        statuses = [g["status"] for g in out["by_policy_status"]]
        tiers = [g["tier"] for g in out["by_overall_vulnerability"]]
        self.assertEqual(tuple(statuses), POLICY_STATUS_BUCKETS)
        self.assertEqual(tuple(tiers), VULNERABILITY_BUCKETS)
        for g in out["by_policy_status"]:
            self.assertEqual(g["total"], 0)
            self.assertIsNone(g["hit_rate"])
        for g in out["by_overall_vulnerability"]:
            self.assertEqual(g["total"], 0)

    def test_buckets_assigned_from_stored_context(self):
        events = [
            self._ev(status="effective", vuln="vulnerable",
                     direction="supports_thesis"),
            self._ev(status="effective", vuln="vulnerable",
                     direction="contradicts_thesis", r5=-1.0),
            self._ev(status="announced", vuln="moderate",
                     direction="supports_thesis"),
        ]
        out = compute_track_record_breakdown(events)

        ps = {g["status"]: g for g in out["by_policy_status"]}
        self.assertEqual(ps["effective"]["total"], 2)
        self.assertEqual(ps["effective"]["validated"], 1)
        self.assertEqual(ps["effective"]["contradicted"], 1)
        self.assertEqual(ps["announced"]["total"], 1)
        self.assertEqual(ps["under_review"]["total"], 0)
        self.assertEqual(ps["expired"]["total"], 0)

        vt = {g["tier"]: g for g in out["by_overall_vulnerability"]}
        self.assertEqual(vt["vulnerable"]["total"], 2)
        self.assertEqual(vt["moderate"]["total"], 1)
        self.assertEqual(vt["resilient"]["total"], 0)
        self.assertEqual(vt["fragile"]["total"], 0)

    def test_events_with_empty_context_are_skipped_cleanly(self):
        """Events without a tracked-policy match (`{}`) or without a
        profiled country must still count in the family totals but
        contribute zero to either deterministic-context dimension."""
        events = [
            self._ev(status="effective", vuln="vulnerable"),
            self._ev(),  # no policy_timing_context, no country_vulnerability_context
        ]
        out = compute_track_record_breakdown(events)
        self.assertEqual(out["total_events"], 2)
        # Family totals see both events.
        self.assertEqual(out["by_mechanism_family"][0]["total"], 2)
        # Deterministic-context dimensions see only the event with context.
        ps_total = sum(g["total"] for g in out["by_policy_status"])
        vt_total = sum(g["total"] for g in out["by_overall_vulnerability"])
        self.assertEqual(ps_total, 1)
        self.assertEqual(vt_total, 1)

    def test_unknown_status_or_tier_treated_as_missing(self):
        """A context block with an off-enum status / tier must not
        introduce a new bucket — the dimension keeps its canonical
        shape."""
        events = [
            self._ev(status="phased", vuln="extreme"),
        ]
        out = compute_track_record_breakdown(events)
        self.assertEqual(tuple(g["status"] for g in out["by_policy_status"]),
                         POLICY_STATUS_BUCKETS)
        self.assertEqual(
            tuple(g["tier"] for g in out["by_overall_vulnerability"]),
            VULNERABILITY_BUCKETS,
        )
        self.assertEqual(sum(g["total"] for g in out["by_policy_status"]), 0)
        self.assertEqual(
            sum(g["total"] for g in out["by_overall_vulnerability"]), 0,
        )

    def test_existing_response_keys_remain_stable(self):
        """Adding the two new dimensions must not drop the established
        breakdown keys older consumers rely on."""
        out = compute_track_record_breakdown([_event()])
        for k in (
            "total_events", "validated_total", "contradicted_total",
            "revisit_scored", "hit_rate",
            "by_mechanism_family", "by_regime", "by_compound_regime",
            "by_proof_quality",
        ):
            self.assertIn(k, out)


if __name__ == "__main__":
    unittest.main()
