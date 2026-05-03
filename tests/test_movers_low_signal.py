"""
Tests that low-signal / insufficient-evidence events are suppressed
from weekly and persistent movers slices.

Covers:
- Weekly slice excludes events with low_signal=1
- Weekly slice excludes events with "insufficient evidence" mechanism
- Persistent slice excludes low-signal events (both strict and fallback)
- Legitimate high-signal events still surface normally
"""

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from movers_cache import compute_slice, _is_event_low_signal


def _ev(headline, *, low_signal=0, mechanism="Real mechanism.", tickers=None, days_ago=1):
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {
        "id": hash(headline) % 10000,
        "headline": headline,
        "stage": "developing",
        "persistence": "1w",
        "what_changed": "test",
        "mechanism_summary": mechanism,
        "beneficiaries": ["A"] if not low_signal else [],
        "losers": ["B"] if not low_signal else [],
        "confidence": "medium" if not low_signal else "low",
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


def _stub_mover_summary(ev, tickers, support_ratio):
    return {
        "event_id": ev.get("id", 0),
        "headline": ev["headline"],
        "mechanism_summary": ev.get("mechanism_summary", ""),
        "event_date": ev.get("event_date", ""),
        "stage": ev.get("stage", ""),
        "persistence": ev.get("persistence", ""),
        "impact": abs(tickers[0]["return_5d"]) if tickers else 0,
        "support_ratio": support_ratio,
        "tickers": tickers[:3],
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
        "tickers": tickers[:3],
        "days_since_event": days,
    }


class TestIsEventLowSignal(unittest.TestCase):

    def test_low_signal_column(self):
        self.assertTrue(_is_event_low_signal({"low_signal": 1}))

    def test_low_signal_truthy(self):
        self.assertTrue(_is_event_low_signal({"low_signal": True}))

    def test_insufficient_evidence_mechanism_suppresses(self):
        """Events with 'Insufficient evidence' mechanism are suppressed."""
        self.assertTrue(_is_event_low_signal({
            "headline": "OPEC cuts output by 500k bpd",
            "mechanism_summary": "Insufficient evidence to identify mechanism.",
        }))

    def test_normal_event(self):
        self.assertFalse(_is_event_low_signal({
            "low_signal": 0,
            "headline": "Fed holds rates steady amid inflation concerns",
            "mechanism_summary": "Real mechanism summary.",
        }))

    def test_empty_event(self):
        self.assertFalse(_is_event_low_signal({}))

    def test_irrelevant_headline_suppressed(self):
        """Irrelevant headline (entertainment) is caught even with low_signal=0."""
        self.assertTrue(_is_event_low_signal({
            "low_signal": 0,
            "headline": "India stage-queens dazzle at Bollywood awards",
        }))

    def test_relevant_headline_passes(self):
        """Relevant geopolitical headline with low_signal=0 passes."""
        self.assertFalse(_is_event_low_signal({
            "low_signal": 0,
            "headline": "EU imposes new sanctions on Russia",
        }))


class TestWeeklySliceLowSignalSuppression(unittest.TestCase):

    def test_low_signal_excluded(self):
        events = [
            _ev("OPEC cuts output by 500k bpd", days_ago=1),
            _ev("Junk noise event", low_signal=1, days_ago=1),
        ]
        result = compute_slice(
            "weekly", events,
            build_mover_summary=_stub_mover_summary,
        )
        headlines = [m["headline"] for m in result]
        self.assertIn("OPEC cuts output by 500k bpd", headlines)
        self.assertNotIn("Junk noise event", headlines)

    def test_insufficient_evidence_with_flag_excluded(self):
        """Only events with low_signal=1 are suppressed, not mechanism text alone."""
        events = [
            _ev("US imposes new tariff on steel imports", days_ago=1),
            _ev("Noise event", low_signal=1, days_ago=1),
        ]
        result = compute_slice(
            "weekly", events,
            build_mover_summary=_stub_mover_summary,
        )
        headlines = [m["headline"] for m in result]
        self.assertIn("US imposes new tariff on steel imports", headlines)
        self.assertNotIn("Noise event", headlines)

    def test_real_mechanism_text_preserved(self):
        """Event with a real mechanism (not 'Insufficient evidence') is kept."""
        events = [
            _ev("EU sanctions review targets energy exports", mechanism="EU sanctions on Russian energy reduce supply.",
                low_signal=0, days_ago=1),
        ]
        result = compute_slice(
            "weekly", events,
            build_mover_summary=_stub_mover_summary,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["headline"], "EU sanctions review targets energy exports")

    def test_all_low_signal_returns_empty(self):
        events = [
            _ev("Junk A", low_signal=1, days_ago=1),
            _ev("Junk B", low_signal=1, days_ago=1),
        ]
        result = compute_slice(
            "weekly", events,
            build_mover_summary=_stub_mover_summary,
        )
        self.assertEqual(result, [])


class TestPersistentSliceLowSignalSuppression(unittest.TestCase):

    def _decay_accelerating(self, r5, r20):
        return {"label": "Accelerating", "evidence": "test"}

    def test_low_signal_kept_in_strict(self):
        """Persistent slice does not filter low-signal — keeps everything
        with valid ticker data and a persistent trajectory."""
        events = [
            _ev("OPEC extends production cuts through Q3", days_ago=10),
            _ev("Persistent junk", low_signal=1, days_ago=10),
        ]
        result = compute_slice(
            "persistent", events,
            build_persistent_summary=_stub_persistent_summary,
            classify_decay_fn=self._decay_accelerating,
        )
        headlines = [m["headline"] for m in result]
        self.assertIn("OPEC extends production cuts through Q3", headlines)
        self.assertIn("Persistent junk", headlines)

    def test_low_signal_kept_in_fallback(self):
        """Persistent fallback does not filter low-signal events."""
        # All events are recent (< 7d) so strict is empty → fallback runs
        events = [
            _ev("Fed signals rate pause amid inflation data", days_ago=2),
            _ev("Recent junk", low_signal=1, days_ago=2),
        ]
        result = compute_slice(
            "persistent", events,
            build_persistent_summary=_stub_persistent_summary,
            classify_decay_fn=self._decay_accelerating,
        )
        headlines = [m["headline"] for m in result]
        self.assertIn("Fed signals rate pause amid inflation data", headlines)
        self.assertIn("Recent junk", headlines)

    def test_high_signal_with_mixed_support_still_eligible(self):
        """A real event with mixed support ratio should still surface."""
        tickers = [
            {"symbol": "AAPL", "role": "beneficiary",
             "return_5d": 2.0, "return_20d": 3.0,
             "direction_tag": "supports \u2191", "spark": [],
             "label": "up", "return_1d": 0.3, "volume_ratio": 1.0, "vs_xle_5d": None},
            {"symbol": "MSFT", "role": "loser",
             "return_5d": 1.5, "return_20d": 2.0,
             "direction_tag": "contradicts \u2191", "spark": [],
             "label": "up", "return_1d": 0.2, "volume_ratio": 1.0, "vs_xle_5d": None},
        ]
        events = [_ev("US tariff on Chinese semiconductors sparks mixed reaction", days_ago=10, tickers=tickers)]
        result = compute_slice(
            "persistent", events,
            build_persistent_summary=_stub_persistent_summary,
            classify_decay_fn=self._decay_accelerating,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["headline"], "US tariff on Chinese semiconductors sparks mixed reaction")


# ---------------------------------------------------------------------------
# Regression: sections must not collapse when valid events exist
# ---------------------------------------------------------------------------

class TestSectionsDontCollapse(unittest.TestCase):

    def _decay_acc(self, r5, r20):
        return {"label": "Accelerating", "evidence": "test"}

    def test_weekly_not_empty_with_real_events(self):
        """Weekly section returns events when valid macro items exist."""
        events = [
            _ev("OPEC cuts output by 500k bpd", days_ago=2),
            _ev("Federal Reserve holds interest rate steady", days_ago=3),
        ]
        result = compute_slice("weekly", events, build_mover_summary=_stub_mover_summary)
        self.assertEqual(len(result), 2)

    def test_persistent_not_empty_with_real_events(self):
        """Persistent section returns events when valid items exist."""
        events = [
            _ev("Tariffs on steel imports", days_ago=10),
            _ev("China retaliatory sanctions", days_ago=12),
        ]
        result = compute_slice(
            "persistent", events,
            build_persistent_summary=_stub_persistent_summary,
            classify_decay_fn=self._decay_acc,
        )
        self.assertGreaterEqual(len(result), 2)

    def test_weekly_mixed_junk_and_real(self):
        """Weekly section keeps real events and drops only flagged junk."""
        events = [
            _ev("EU imposes new sanctions on Russia", days_ago=1),
            _ev("Junk noise 1", low_signal=1, days_ago=1),
            _ev("Oil prices surge on supply disruption", days_ago=2),
            _ev("Junk noise 2", low_signal=1, days_ago=2),
        ]
        result = compute_slice("weekly", events, build_mover_summary=_stub_mover_summary)
        headlines = [m["headline"] for m in result]
        self.assertIn("EU imposes new sanctions on Russia", headlines)
        self.assertIn("Oil prices surge on supply disruption", headlines)
        self.assertNotIn("Junk noise 1", headlines)
        self.assertNotIn("Junk noise 2", headlines)
        self.assertEqual(len(result), 2)

    def test_event_with_low_confidence_but_real_mechanism_preserved(self):
        """Low confidence alone does not suppress — only low_signal flag does."""
        events = [
            _ev("Uncertain geopolitical event", low_signal=0, days_ago=1),
        ]
        # Manually set confidence low but keep real mechanism
        events[0]["confidence"] = "low"
        events[0]["mechanism_summary"] = "Trade disruption via Hormuz straits."
        result = compute_slice("weekly", events, build_mover_summary=_stub_mover_summary)
        self.assertEqual(len(result), 1)

    def test_event_with_zero_support_ratio_preserved(self):
        """0% support ratio does NOT suppress the event from movers."""
        tickers = [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": -5.0, "return_20d": -8.0,
             "direction_tag": "contradicts \u2193", "spark": [],
             "label": "down", "return_1d": -1.0, "volume_ratio": 2.0, "vs_xle_5d": None},
        ]
        events = [_ev("Oil event with wrong direction", days_ago=2, tickers=tickers)]
        result = compute_slice("weekly", events, build_mover_summary=_stub_mover_summary)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["headline"], "Oil event with wrong direction")


# ---------------------------------------------------------------------------
# Headline relevance gate — irrelevant headlines suppressed even with
# low_signal=0 and valid tickers
# ---------------------------------------------------------------------------

class TestHeadlineRelevanceGate(unittest.TestCase):

    def _decay_acc(self, r5, r20):
        return {"label": "Accelerating", "evidence": "test"}

    def test_irrelevant_headline_excluded_from_weekly(self):
        """Entertainment headline with valid tickers must not appear in weekly."""
        events = [
            _ev("India stage-queens dazzle at Bollywood awards", low_signal=0, days_ago=1),
            _ev("OPEC cuts output by 500k bpd", days_ago=1),
        ]
        result = compute_slice("weekly", events, build_mover_summary=_stub_mover_summary)
        headlines = [m["headline"] for m in result]
        self.assertNotIn("India stage-queens dazzle at Bollywood awards", headlines)
        self.assertIn("OPEC cuts output by 500k bpd", headlines)

    def test_irrelevant_headline_kept_in_persistent(self):
        """Persistent slice does not filter by headline relevance."""
        events = [
            _ev("Ecuador agreement on cultural exchange program", low_signal=0, days_ago=10),
            _ev("US tariff on steel imports takes effect", days_ago=10),
        ]
        result = compute_slice(
            "persistent", events,
            build_persistent_summary=_stub_persistent_summary,
            classify_decay_fn=self._decay_acc,
        )
        headlines = [m["headline"] for m in result]
        self.assertIn("Ecuador agreement on cultural exchange program", headlines)
        self.assertIn("US tariff on steel imports takes effect", headlines)

    def test_sports_headline_excluded(self):
        """Sports headline must not surface in movers."""
        events = [
            _ev("World Cup qualifying match results surprise fans", low_signal=0, days_ago=1),
        ]
        result = compute_slice("weekly", events, build_mover_summary=_stub_mover_summary)
        self.assertEqual(result, [])

    def test_celebrity_headline_excluded(self):
        """Celebrity news must not surface in movers."""
        events = [
            _ev("Pop star announces world tour dates for 2026", low_signal=0, days_ago=1),
        ]
        result = compute_slice("weekly", events, build_mover_summary=_stub_mover_summary)
        self.assertEqual(result, [])

    def test_real_geopolitical_event_preserved(self):
        """Geopolitical event with relevant headline passes through."""
        events = [
            _ev("NATO allies agree to increase defense spending", low_signal=0, days_ago=1),
        ]
        result = compute_slice("weekly", events, build_mover_summary=_stub_mover_summary)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["headline"], "NATO allies agree to increase defense spending")

    def test_energy_event_preserved(self):
        """Energy/commodity event passes through."""
        events = [
            _ev("Natural gas prices surge on cold weather forecast", low_signal=0, days_ago=1),
        ]
        result = compute_slice("weekly", events, build_mover_summary=_stub_mover_summary)
        self.assertEqual(len(result), 1)

    def test_trade_event_preserved(self):
        """Trade policy event passes through."""
        events = [
            _ev("China announces retaliatory tariffs on US agriculture", low_signal=0, days_ago=1),
        ]
        result = compute_slice("weekly", events, build_mover_summary=_stub_mover_summary)
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
