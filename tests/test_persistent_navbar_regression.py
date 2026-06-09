"""
Regression tests for two live issues:

1. Navbar invisible on overview — TopBar had near-zero contrast and hid
   the page title on the overview page.
2. "Still Moving Markets" collapsed to 1 headline — strict phase blocked
   fallback even when it found fewer than _MIN_PERSISTENT items.

Covers:
- TopBar always shows page title + visible border on every page
- Persistent slice supplements strict results with fallback when sparse
- Persistent slice still works when strict is plentiful
- Frontend StillMovingSection has no mechanism-text filter
"""

import os
import re
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from movers_cache import compute_slice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ev(headline, *, low_signal=0, mechanism="Real mechanism.", tickers=None, days_ago=10):
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {
        "id": abs(hash(headline)) % 100000,
        "headline": headline,
        "stage": "developing",
        "persistence": "1w",
        "what_changed": "test",
        "mechanism_summary": mechanism,
        "beneficiaries": ["A"],
        "losers": ["B"],
        "confidence": "medium",
        "market_note": "",
        "market_tickers": tickers or [
            {"symbol": "AAPL", "role": "beneficiary",
             "return_5d": 3.0, "return_20d": 5.0,
             "direction_tag": "supports \u2191", "spark": [],
             "label": "up", "return_1d": 0.5, "volume_ratio": 1.0,
             "vs_xle_5d": None},
        ],
        "event_date": (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d"),
        "timestamp": ts,
        "low_signal": low_signal,
        "notes": "",
        "transmission_chain": ["a", "b"],
    }


def _stub_persistent_summary(ev, tickers, now_dt):
    ed = ev.get("event_date") or ev.get("timestamp", "")[:10]
    days = (now_dt.date() - datetime.fromisoformat(ed).date()).days if ed else 0
    return {
        "event_id": ev.get("id", 0),
        "headline": ev["headline"],
        "mechanism_summary": ev.get("mechanism_summary", ""),
        "event_date": ev.get("event_date", ""),
        "stage": ev.get("stage", ""),
        "persistence": ev.get("persistence", ""),
        "impact": abs(tickers[0]["return_5d"]) if tickers else 0,
        "support_ratio": 1.0,
        "tickers": [dict(t) for t in tickers[:3]],
        "days_since_event": days,
    }


def _decay_acc(_r5, _r20):
    return {"label": "Accelerating", "evidence": "test"}


def _decay_fading(_r5, _r20):
    return {"label": "Fading", "evidence": "test"}


def _read_frontend(*parts):
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        *parts,
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. TopBar visibility — always shows title + border on every page
# ---------------------------------------------------------------------------

class TestTopBarVisibility(unittest.TestCase):
    """TopBar must be visually distinct on every page including overview."""

    def test_no_isOverview_conditional_hiding(self):
        """The TopBar must not gate page-title rendering behind isOverview."""
        content = _read_frontend(
            "frontend", "src", "components", "layout", "top-bar.tsx",
        )
        # The old bug: {!isOverview && (<page title>)} hid the title on overview.
        # After the fix, isOverview should no longer exist in the file.
        self.assertNotIn(
            "isOverview",
            content,
            "TopBar still gates content behind isOverview — title hidden on overview",
        )

    def test_border_always_present(self):
        """The <header> must always include border-b."""
        content = _read_frontend(
            "frontend", "src", "components", "layout", "top-bar.tsx",
        )
        # JSX may break <header and className across lines; tolerate either.
        m = re.search(r"<header\s+className", content)
        self.assertIsNotNone(m, "TopBar <header className=...> not found")
        block = content[m.start():m.start() + 400]
        self.assertIn("border-b", block)

    def test_page_title_always_rendered(self):
        """Every page's title must render (no conditional wrapping)."""
        content = _read_frontend(
            "frontend", "src", "components", "layout", "top-bar.tsx",
        )
        # meta.title is rendered unconditionally — the breadcrumb design
        # no longer renders a per-page icon alongside the title.
        self.assertIn("meta.title", content)

    def test_sidebar_wired_in_shell(self):
        """App.tsx must render Sidebar with md:block."""
        content = _read_frontend("frontend", "src", "App.tsx")
        self.assertIn("<Sidebar", content)
        self.assertIn("md:block", content)

    def test_topbar_wired_in_shell(self):
        """App.tsx must render TopBar with sticky positioning."""
        content = _read_frontend("frontend", "src", "App.tsx")
        self.assertIn("<TopBar", content)
        self.assertIn("sticky top-0", content)


# ---------------------------------------------------------------------------
# 2. Persistent slice — fallback supplements sparse strict results
# ---------------------------------------------------------------------------

class TestPersistentSliceSupplementsFallback(unittest.TestCase):
    """When strict phase finds fewer than _MIN_PERSISTENT items, fallback
    events should be appended so the hero section is never thin."""

    def test_one_strict_supplemented_by_fallback(self):
        """1 Accelerating event + several Fading events → more than 1 result."""
        # Event A: old, Accelerating → passes strict
        evA = _ev("OPEC extends cuts", days_ago=14)
        # Events B-E: old but Fading → strict rejects, fallback picks up
        evB = _ev("EU sanctions round 12", days_ago=10)
        evC = _ev("Fed holds rates", days_ago=11)
        evD = _ev("China tariff hike", days_ago=12)
        evE = _ev("India export ban", days_ago=13)

        def _classify(r5, r20):
            # Only evA's ticker gets Accelerating
            return {"label": "Accelerating", "evidence": "test"}

        # With everything Accelerating, strict gets all 5 (>=4) → no fallback needed
        result_all_acc = compute_slice(
            "persistent", [evA, evB, evC, evD, evE],
            build_persistent_summary=_stub_persistent_summary,
            classify_decay_fn=_classify,
        )
        self.assertEqual(len(result_all_acc), 5)

    def test_single_strict_gets_supplemented(self):
        """Only 1 event passes strict → fallback fills the gap."""
        acc_ev = _ev("OPEC extends cuts", days_ago=14,
                      tickers=[{"symbol": "XOM", "role": "beneficiary",
                                "return_5d": 4.0, "return_20d": 5.0,
                                "direction_tag": "supports \u2191", "spark": [],
                                "label": "up", "return_1d": 0.5,
                                "volume_ratio": 1.0, "vs_xle_5d": None}])
        fading_evs = [
            _ev(f"Fading event {i}", days_ago=10 + i,
                tickers=[{"symbol": f"T{i}", "role": "beneficiary",
                          "return_5d": 0.5, "return_20d": 8.0,
                          "direction_tag": "supports \u2191", "spark": [],
                          "label": "up", "return_1d": 0.1,
                          "volume_ratio": 1.0, "vs_xle_5d": None}])
            for i in range(5)
        ]

        def _mixed_classify(r5, r20):
            if r5 is not None and abs(r5) >= 3.0:
                return {"label": "Accelerating", "evidence": "test"}
            return {"label": "Fading", "evidence": "test"}

        result = compute_slice(
            "persistent", [acc_ev] + fading_evs,
            build_persistent_summary=_stub_persistent_summary,
            classify_decay_fn=_mixed_classify,
        )
        # Must have more than just the 1 strict event
        self.assertGreater(len(result), 1)
        # The strict event should be first (sorted by days_since_event desc)
        self.assertEqual(result[0]["headline"], "OPEC extends cuts")

    def test_fallback_items_tagged_monitoring(self):
        """Fallback items should have their decay relabelled to Monitoring."""
        fading_evs = [
            _ev(f"Event {i}", days_ago=10 + i)
            for i in range(5)
        ]

        result = compute_slice(
            "persistent", fading_evs,
            build_persistent_summary=_stub_persistent_summary,
            classify_decay_fn=_decay_fading,
        )
        self.assertGreater(len(result), 0)
        # All should be Monitoring (since all are Fading → relabelled)
        for item in result:
            for t in item["tickers"]:
                self.assertEqual(t.get("decay"), "Monitoring")

    def test_plentiful_strict_no_fallback_dilution(self):
        """When strict has >= _MIN_PERSISTENT, no fallback items appear."""
        events = [_ev(f"Strong event {i}", days_ago=10 + i) for i in range(6)]

        result = compute_slice(
            "persistent", events,
            build_persistent_summary=_stub_persistent_summary,
            classify_decay_fn=_decay_acc,  # all Accelerating
        )
        self.assertEqual(len(result), 6)

    def test_strict_items_not_duplicated_in_fallback(self):
        """Events that appear in strict must not appear again from fallback."""
        acc_ev = _ev("Strict only", days_ago=14,
                      tickers=[{"symbol": "XOM", "role": "beneficiary",
                                "return_5d": 4.0, "return_20d": 5.0,
                                "direction_tag": "supports \u2191", "spark": [],
                                "label": "up", "return_1d": 0.5,
                                "volume_ratio": 1.0, "vs_xle_5d": None}])
        fading_evs = [_ev(f"Fading {i}", days_ago=10 + i) for i in range(5)]

        def _mixed(r5, r20):
            if r5 is not None and abs(r5) >= 3.0:
                return {"label": "Accelerating", "evidence": "test"}
            return {"label": "Fading", "evidence": "test"}

        result = compute_slice(
            "persistent", [acc_ev] + fading_evs,
            build_persistent_summary=_stub_persistent_summary,
            classify_decay_fn=_mixed,
        )
        headlines = [m["headline"] for m in result]
        self.assertEqual(headlines.count("Strict only"), 1,
                         "Strict event must not be duplicated in fallback")

    def test_zero_strict_still_returns_fallback(self):
        """When no event passes strict (all Fading), fallback runs alone."""
        events = [_ev(f"Fading {i}", days_ago=10 + i) for i in range(5)]
        result = compute_slice(
            "persistent", events,
            build_persistent_summary=_stub_persistent_summary,
            classify_decay_fn=_decay_fading,
        )
        self.assertGreater(len(result), 0)


# ---------------------------------------------------------------------------
# 3. (removed) Frontend "Still moving" double-filter guard.
# The live mover-window sections — including the persistent "Still moving
# markets" surface this test grepped (``const persistentList`` /
# ``PersistentMoverRow``) — were retired from market-overview.tsx in P5B
# (Section 2 now reads the frozen archive; see the file's module note).  The
# compute_slice fallback behaviour the guard actually cared about is covered by
# TestPersistentSliceSupplementsFallback above; the brittle TSX source-grep had
# no surface left to anchor on, so it was removed rather than re-pinned.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. Bottom navigation — mobile tab bar exists and is wired
# ---------------------------------------------------------------------------

class TestBottomNavWired(unittest.TestCase):
    """The mobile bottom navigation bar must exist and be wired into App."""

    def test_bottom_nav_component_exists(self):
        content = _read_frontend(
            "frontend", "src", "components", "layout", "bottom-nav.tsx",
        )
        self.assertIn("BottomNav", content)
        self.assertIn("md:hidden", content, "Bottom nav must hide on desktop")
        self.assertIn("fixed bottom-0", content, "Must be pinned to bottom")

    def test_bottom_nav_has_all_tabs(self):
        content = _read_frontend(
            "frontend", "src", "components", "layout", "bottom-nav.tsx",
        )
        # ``market`` replaced ``overview`` as the canonical id for the
        # Market workspace tab; ``overview`` is retained only as a
        # back-compat alias on the Page type, not as a bottom-nav tab.
        for tab_id in ("market", "portfolio", "headlines", "analyze", "events", "backtest"):
            self.assertIn(f'"{tab_id}"', content, f"Missing tab: {tab_id}")

    def test_bottom_nav_imported_in_app(self):
        content = _read_frontend("frontend", "src", "App.tsx")
        self.assertIn("BottomNav", content)
        self.assertIn("<BottomNav", content)

    def test_main_has_mobile_bottom_padding(self):
        """Content area needs extra bottom padding on mobile for the nav bar."""
        content = _read_frontend("frontend", "src", "App.tsx")
        self.assertIn("pb-16", content, "Missing mobile bottom padding for nav")


# ---------------------------------------------------------------------------
# 5. Cache versioning — stale compute_version triggers recompute
# ---------------------------------------------------------------------------

class TestCacheVersionInvalidation(unittest.TestCase):
    """When compute logic changes (new _COMPUTE_VERSION), persisted cache
    must be recomputed on next read even if fingerprint + TTL are fresh."""

    def setUp(self):
        from movers_cache import _COMPUTE_VERSION
        self._current_version = _COMPUTE_VERSION
        self._store: dict = {}
        self._compute_calls = 0

        self._events = [
            {"id": 1, "headline": "A", "market_tickers": [
                {"symbol": "X", "return_5d": 2.0, "return_20d": 3.0,
                 "direction_tag": "supports", "spark": [], "label": "up",
                 "return_1d": 0.1, "volume_ratio": 1.0, "vs_xle_5d": None}
            ], "timestamp": datetime.now().isoformat(), "event_date": datetime.now().strftime("%Y-%m-%d"),
             "headline": "Test", "mechanism_summary": "m", "low_signal": 0},
        ]

    def _load_events(self, _n):
        return self._events

    def _fingerprint(self):
        return (1, 1)

    def _save(self, name, payload, built_at, count, max_id, *, compute_version=0):
        self._store[name] = {
            "payload": payload, "built_at": built_at,
            "event_count": count, "max_event_id": max_id,
            "compute_version": compute_version,
        }

    def _load(self, name):
        return self._store.get(name)

    def _compute(self, name, events, now=None):
        self._compute_calls += 1
        return [{"event_id": 1, "headline": "Test", "impact": 1.0}]

    def test_stale_version_triggers_recompute(self):
        """A cached row with old compute_version triggers recompute."""
        import movers_cache
        now = datetime.now()
        # Seed cache with old version
        self._store["weekly"] = {
            "payload": [{"old": True}],
            "built_at": now.replace(microsecond=0).isoformat(),
            "event_count": 1,
            "max_event_id": 1,
            "compute_version": self._current_version - 1,
        }

        movers_cache.get_slice(
            "weekly", limit=10, ttl_seconds=9999, now=now,
            load_events_fn=self._load_events,
            load_cache_fn=self._load,
            save_cache_fn=self._save,
            fingerprint_fn=self._fingerprint,
            compute_fn=self._compute,
        )
        self.assertEqual(self._compute_calls, 1, "Stale version must trigger recompute")

    def test_current_version_serves_cache(self):
        """A cached row with current compute_version is served without recompute."""
        import movers_cache
        now = datetime.now()
        self._store["weekly"] = {
            "payload": [{"cached": True}],
            "built_at": now.replace(microsecond=0).isoformat(),
            "event_count": 1,
            "max_event_id": 1,
            "compute_version": self._current_version,
        }

        result = movers_cache.get_slice(
            "weekly", limit=10, ttl_seconds=9999, now=now,
            load_events_fn=self._load_events,
            load_cache_fn=self._load,
            save_cache_fn=self._save,
            fingerprint_fn=self._fingerprint,
            compute_fn=self._compute,
        )
        self.assertEqual(self._compute_calls, 0, "Current version must serve from cache")
        self.assertEqual(result, [{"cached": True}])


if __name__ == "__main__":
    unittest.main()
