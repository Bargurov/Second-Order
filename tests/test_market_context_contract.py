"""Backend contract tests for Market Context + movers data integrity.

Pins the wire-shape rules the Market Context surface depends on:

  * /market-context returns a dict whose floats are all finite and
    whose missing sub-blocks are explicitly marked (``available=False``,
    ``error="not_refreshed"``, etc.) rather than fabricated.
  * /movers/{today,weekly,persistent} + /market-movers return the
    pinned ``{"items": [...], "meta": {...}}`` envelope, never NaN/Inf
    or placeholder/sample fact strings.
  * /movers/persistent enforces the high-impact-only "Still Moving
    Markets" rule — non-conviction or low-impact rows must NOT leak.
  * /movers/persistent returns an empty items list cleanly when the
    cache is empty; the response stays a 200 with the same envelope.

No live network, no LLM, no yfinance.  External seams are stubbed in
the same style as ``tests/test_smoke_integration.py``.
"""

import json
import math
import os
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402


# ---------------------------------------------------------------------------
# Numeric / placeholder integrity helpers.
# ---------------------------------------------------------------------------

def _walk_floats(obj, path="root"):
    """Yield every float (with path) found inside *obj*, recursively."""
    if isinstance(obj, float):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_floats(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _walk_floats(v, f"{path}[{i}]")


def _walk_strings(obj, path="root"):
    """Yield every string (with path) found inside *obj*, recursively."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{path}[{i}]")


def _assert_finite(test, body, label=""):
    try:
        json.dumps(body)
    except (TypeError, ValueError) as exc:
        test.fail(f"Response not JSON-serializable ({label}): {exc}")
    bad = [
        f"{p} = {v}" for p, v in _walk_floats(body) if not math.isfinite(v)
    ]
    if bad:
        test.fail(f"Non-finite numeric in response ({label}):\n" + "\n".join(bad))


# Strings that would indicate a placeholder/sample value being shipped
# to the wire as if it were a live fact.  Conservative: each token is
# unambiguously fake and would never legitimately appear in a real
# market-context payload.  Case-insensitive substring match.
_PLACEHOLDER_TOKENS: tuple[str, ...] = (
    "lorem ipsum",
    "placeholder",
    "todo:",
    "fixme",
    "sample data",
)


def _assert_no_placeholder_strings(test, body, label=""):
    hits = []
    for path, s in _walk_strings(body):
        s_lower = s.lower()
        for tok in _PLACEHOLDER_TOKENS:
            if tok in s_lower:
                hits.append(f"{path}: {s!r} contains {tok!r}")
                break
    if hits:
        test.fail(f"Placeholder/sample value leaked ({label}):\n" + "\n".join(hits))


# ---------------------------------------------------------------------------
# Stubs — kept aligned with the rest of the smoke / contract suite.
# ---------------------------------------------------------------------------

_STUB_STRESS = {
    "regime": "Undercurrent",
    "signals": {
        "vix_elevated": False, "term_inversion": False,
        "credit_widening": False, "safe_haven_bid": False,
        "breadth_deterioration": False,
    },
    "raw": {"vix": 18.5},
    "detail": {},
    "summary": "Markets calm.",
}

_STUB_RATES = {
    "regime": "Neutral",
    "nominal": {"label": "10Y Treasury", "value": 4.25, "change_5d": 0.05},
    "real_proxy": {"label": "10Y TIPS", "value": 1.9, "change_5d": 0.02},
    "breakeven_proxy": {"label": "Breakeven", "value": 2.35, "change_5d": 0.03},
    "raw": {},
}

_STUB_REGIME_VEC = {"available": False}

_STUB_SECTOR_UNCERTAINTY = {"available": False}


# A high-impact, fully-conviction persistent card — the ONLY shape that
# should survive the /movers/persistent gate.  Use this as the positive
# fixture and mutate one field at a time for the negative fixtures so
# each test isolates exactly one disqualifier.
def _high_impact_persistent_card(event_id: int = 1, **overrides) -> dict:
    card = {
        "event_id":         event_id,
        "headline":         "OPEC cuts oil supply",
        "mechanism_family": "commodity_squeeze",
        "thesis_state":     "confirming",
        "stale_signal":     "fresh",
        "weighted_evidence": {
            "evidence_label":   "supportive",
            "evidence_score":   0.7,
            "evidence_reasons": [],
            "scored_tickers":   2,
            "total_tickers":    2,
            "tag_only_tickers": 0,
            "evidence_basis":   "evidence_scores",
        },
        "has_proof_set":    True,
        "has_falsifiers":   True,
        "low_information":  False,
        "tickers": [
            {"symbol": "USO", "role": "beneficiary", "return_5d": 4.0},
            {"symbol": "XLE", "role": "beneficiary", "return_5d": 3.2},
        ],
        "conviction": {
            "conviction_class": "conviction",
            "impact_level":     "high",
            "persistence_quality": 0.4,
        },
    }
    card.update(overrides)
    return card


_STUB_NEWS_UNCERTAINTY = {
    "uncertainty_scope": "global",
    "sector_uncertainty": [],
    "lead_sector": None,
}


def _stub_snapshot_objects():
    from market_snapshots import MarketSnapshot
    from market_universe import LIQUID_MARKETS, LIQUID_MARKET_INFO, resolve_symbol

    rows = []
    for idx, market in enumerate(LIQUID_MARKETS):
        info = LIQUID_MARKET_INFO[market]
        rows.append(MarketSnapshot(
            market=market,
            symbol=resolve_symbol(market),
            label=info["label"],
            unit=info["unit"],
            asset_class=info["asset_class"],
            source="test",
            value=100.0 + idx,
            change_1d=0.1,
            change_5d=0.5,
            fetched_at="2026-04-29T00:00:00+00:00",
        ))
    return rows


_BASE_PATCHES = [
    patch("api.compute_stress_regime", return_value=_STUB_STRESS),
    patch("api.compute_rates_context", return_value=_STUB_RATES),
    patch("api.build_regime_vector", return_value=_STUB_REGIME_VEC),
    patch("market_snapshots.get_all_snapshots", return_value=[]),
    patch("market_snapshots.refresh_all", return_value=[]),
    patch("sector_uncertainty.compute_sector_uncertainty",
          return_value=_STUB_SECTOR_UNCERTAINTY),
    # compute_news_uncertainty otherwise lazy-fetches the full news pipeline
    # (live network) on cache miss; pin it so tests stay offline.
    patch("api.compute_news_uncertainty", return_value=_STUB_NEWS_UNCERTAINTY),
    # Persistent slice empty by default — overridden per test as needed.
    patch("movers_cache.get_slice", return_value=[]),
    # /movers/today reads its own cached candidate list — keep it empty
    # by default so the highlights block stays deterministic.
    patch("api.movers_today", return_value=[]),
]


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for p in _BASE_PATCHES:
            p.start()
        from fastapi.testclient import TestClient
        from api import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        for p in _BASE_PATCHES:
            p.stop()

    def setUp(self):
        import api as _api_mod
        self._orig_db = db.DB_FILE
        self._tmp_db = os.path.join(
            os.path.dirname(__file__),
            f"test_market_context_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp_db
        db.init_db()
        _api_mod._news_cache["data"] = None
        _api_mod._news_cache["ts"] = 0.0
        _api_mod._last_refresh_at = 0.0
        _api_mod._last_refresh_payload = None

    def tearDown(self):
        db.DB_FILE = self._orig_db
        try:
            os.remove(self._tmp_db)
        except (OSError, PermissionError):
            pass

    def _get_ok(self, path, **params):
        r = self.client.get(path, params=params)
        self.assertEqual(r.status_code, 200, f"{path}: {r.text}")
        return r.json()


# ---------------------------------------------------------------------------
# /market-context — section availability + numeric integrity.
# ---------------------------------------------------------------------------

class TestMarketContextDataIntegrity(_Base):
    def test_response_is_dict_with_all_top_blocks(self):
        body = self._get_ok("/market-context")
        self.assertIsInstance(body, dict)
        for key in (
            "built_at", "source",
            "snapshots", "snapshots_meta",
            "stress", "rates", "regime_vector",
            "highlights", "highlights_meta",
            "uncertainty_concentration",
            "credit_regime", "funding_stress_mode",
            "sector_rotation", "finance_playbook",
        ):
            self.assertIn(key, body, f"Missing /market-context key: {key}")

    def test_all_numerics_finite(self):
        body = self._get_ok("/market-context")
        _assert_finite(self, body, "GET /market-context")

    def test_no_placeholder_strings(self):
        body = self._get_ok("/market-context")
        _assert_no_placeholder_strings(self, body, "GET /market-context")

    def test_empty_warm_store_marks_snapshots_not_refreshed(self):
        """When the warm SnapshotStore is empty, every padded row must
        carry value=None + error='not_refreshed' so the frontend never
        renders a placeholder as a live print."""
        body = self._get_ok("/market-context")
        snaps = body["snapshots"]
        self.assertIsInstance(snaps, list)
        self.assertGreater(len(snaps), 0,
                           "padded payload always returns one row per liquid market")
        for row in snaps:
            # Either we have a real value (with no error and finite floats)
            # or the row is explicitly marked missing.
            if row.get("value") is None:
                self.assertEqual(
                    row.get("error"), "not_refreshed",
                    f"missing snapshot must mark error='not_refreshed': {row}",
                )
            else:
                # If a value is present, it must be a finite float.
                self.assertTrue(
                    math.isfinite(row["value"]),
                    f"non-finite value on snapshot: {row}",
                )

    def test_market_context_cold_store_does_not_refresh_on_get(self):
        """/market-context must NOT provider-refresh on a GET, even on a
        cold store.  K1B moved provider-backed refresh off every GET path
        (the no-provider-fetch boundary): a cold or empty SnapshotStore is
        served as explicit ``not_refreshed`` placeholder rows plus
        unavailable metadata, never a silent synchronous warm.  Populating
        the store stays the non-GET snapshot warmer's job
        (``market_snapshots.refresh_all``) — that the warmer still reaches
        the provider off the GET path is covered by
        ``tests/test_get_provider_boundary.py`` and the no-paid smoke's GET
        boundary rows, so this contract test does not re-exercise it."""
        with patch("market_snapshots.get_all_snapshots", return_value=[]), \
             patch("market_snapshots.refresh_all") as refresh_mock:
            body = self._get_ok("/market-context")

        # Core K1B contract: a GET request never triggers the
        # provider-backed warmer.  (On the old contract this was
        # asserted the other way — refresh_all called once.)
        refresh_mock.assert_not_called()

        # The normal market-context payload shape is still returned
        # (HTTP 200 asserted by _get_ok) with the snapshots contract
        # present and never collapsed to an empty list.
        self.assertIsInstance(body, dict)
        self.assertIn("snapshots", body)
        self.assertIn("snapshots_meta", body)
        snaps = body["snapshots"]
        self.assertIsInstance(snaps, list)
        self.assertGreater(
            len(snaps), 0,
            "padded payload always returns one row per liquid market",
        )

        # Cold rows are explicit placeholders — never fabricated fresh
        # values that could be mis-rendered as a live print.
        for row in snaps:
            self.assertIsNone(
                row.get("value"),
                f"cold-store row must not carry a fabricated value: {row}",
            )
            self.assertEqual(
                row.get("error"), "not_refreshed",
                f"cold-store row must be marked not_refreshed: {row}",
            )

        # snapshots_meta reflects the fully-unavailable cold store.
        meta = body["snapshots_meta"]
        self.assertEqual(meta["total"], len(snaps))
        self.assertEqual(meta["unavailable"], meta["total"])
        self.assertEqual(meta["fresh"], 0)
        self.assertEqual(meta["stale"], 0)

    def test_snapshots_meta_counts_match_rows(self):
        body = self._get_ok("/market-context")
        meta = body["snapshots_meta"]
        for k in ("total", "fresh", "stale", "unavailable"):
            self.assertIn(k, meta)
            self.assertIsInstance(meta[k], int)
        self.assertEqual(
            meta["total"],
            meta["fresh"] + meta["stale"] + meta["unavailable"],
        )
        self.assertEqual(meta["total"], len(body["snapshots"]))

    def test_failed_blocks_marked_available_false(self):
        """When stress + rates fail, /market-context degrades the
        affected sub-blocks to ``available=False`` instead of returning
        partial values that could be mis-rendered as live data."""
        with patch("api.compute_stress_regime", side_effect=RuntimeError("boom")), \
             patch("api.compute_rates_context", side_effect=RuntimeError("boom")):
            body = self._get_ok("/market-context")
        # Stress falls back to the documented degraded shape.
        self.assertFalse(body["stress"].get("available", True))
        self.assertEqual(body["stress"].get("regime"), "Unknown")
        # Rates falls back to ``{"available": False, ...}``.
        self.assertFalse(body["rates"].get("available", True))
        # Regime vector + uncertainty also default to available=False.
        self.assertIn("available", body["regime_vector"])
        self.assertIn("available", body["uncertainty_concentration"])


# ---------------------------------------------------------------------------
# /movers/* — bare-list contract by default; opt-in envelope via
# ``?include_meta=true``.
# ---------------------------------------------------------------------------

class TestMoversBareListContract(_Base):
    def test_movers_today_default_is_bare_list(self):
        body = self._get_ok("/movers/today")
        self.assertIsInstance(body, list)
        _assert_finite(self, body, "GET /movers/today")
        _assert_no_placeholder_strings(self, body, "GET /movers/today")

    def test_movers_weekly_default_is_bare_list(self):
        body = self._get_ok("/movers/weekly")
        self.assertIsInstance(body, list)
        _assert_finite(self, body, "GET /movers/weekly")

    def test_market_movers_default_is_bare_list(self):
        body = self._get_ok("/market-movers")
        self.assertIsInstance(body, list)
        _assert_finite(self, body, "GET /market-movers")

    def test_movers_today_include_meta_returns_envelope(self):
        body = self._get_ok("/movers/today", include_meta="true")
        self.assertIsInstance(body, dict)
        self.assertIn("items", body)
        self.assertIn("meta", body)
        self.assertIsInstance(body["items"], list)
        self.assertIsInstance(body["meta"], dict)


# ---------------------------------------------------------------------------
# /movers/persistent — high-impact-only rule + empty-cache behaviour.
# ---------------------------------------------------------------------------

class TestPersistentMoversContract(_Base):
    def test_empty_cache_returns_bare_empty_list(self):
        """An empty persistent slice returns a clean bare list (no 5xx).
        The diagnostics envelope is opt-in via ``?include_meta=true``."""
        body = self._get_ok("/movers/persistent")
        self.assertEqual(body, [])

    def test_high_conviction_card_survives_route_gate(self):
        """A card that satisfies every persistent gate clause must
        actually surface — confirms the route is not over-filtering."""
        good = _high_impact_persistent_card(event_id=42)
        with patch("movers_cache.get_slice", return_value=[good]):
            body = self._get_ok("/movers/persistent")
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["id"], 42)

    def test_low_impact_dropped_even_when_otherwise_eligible(self):
        """High-impact-only rule: a card with everything else right but
        ``conviction.impact_level`` other than ``high`` must NOT appear
        on /movers/persistent.  This is the rule the task forbids
        loosening."""
        for impact in ("medium", "low", None):
            conviction = {"conviction_class": "conviction"}
            if impact is not None:
                conviction["impact_level"] = impact
            card = _high_impact_persistent_card(
                event_id=2, conviction=conviction,
            )
            with patch("movers_cache.get_slice", return_value=[card]):
                body = self._get_ok("/movers/persistent")
            self.assertEqual(
                body, [],
                f"impact_level={impact!r} leaked through the persistent gate",
            )

    def test_non_conviction_class_dropped(self):
        """The high-impact rule layers on top of the conviction-class
        gate.  A high-impact card whose conviction_class is anything
        other than ``conviction`` must still be filtered out."""
        for cls in ("secondary", "lagging", "noisy_mix", "breaking", "pending"):
            card = _high_impact_persistent_card(
                event_id=3,
                conviction={"conviction_class": cls, "impact_level": "high"},
            )
            with patch("movers_cache.get_slice", return_value=[card]):
                body = self._get_ok("/movers/persistent")
            self.assertEqual(
                body, [],
                f"conviction_class={cls!r} leaked through the persistent gate",
            )

    def test_route_filters_mixed_input_to_only_high_impact(self):
        """When the slice contains a mix of conviction levels, only the
        high-impact rows survive — the others are dropped silently
        (filter, not demote, on the persistent surface)."""
        keep = _high_impact_persistent_card(event_id=10)
        drop_low = _high_impact_persistent_card(
            event_id=11,
            conviction={"conviction_class": "conviction", "impact_level": "low"},
        )
        drop_lagging = _high_impact_persistent_card(
            event_id=12,
            conviction={"conviction_class": "lagging", "impact_level": "high"},
        )
        with patch(
            "movers_cache.get_slice",
            return_value=[drop_low, keep, drop_lagging],
        ):
            body = self._get_ok("/movers/persistent")
        ids = [c.get("id") for c in body]
        self.assertEqual(ids, [10])

    def test_persistent_response_numerics_finite(self):
        good = _high_impact_persistent_card(event_id=99)
        with patch("movers_cache.get_slice", return_value=[good]):
            body = self._get_ok("/movers/persistent")
        _assert_finite(self, body, "GET /movers/persistent")
        _assert_no_placeholder_strings(self, body, "GET /movers/persistent")


if __name__ == "__main__":
    unittest.main()
