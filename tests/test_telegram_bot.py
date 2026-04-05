"""
Tests for the Telegram bot formatting and parsing logic.
No network calls, no bot token needed.
"""

import sys
import unittest

sys.path.insert(0, ".")
from telegram_bot import (
    format_analysis, format_brief, format_alert, _esc,
    parse_time, build_morning_brief, check_watchlist_alerts, _alerted,
    extract_headline,
)
import datetime
from unittest.mock import patch


class TestEscape(unittest.TestCase):
    def test_escapes_html(self):
        self.assertEqual(_esc("A & B"), "A &amp; B")
        self.assertEqual(_esc("<script>"), "&lt;script&gt;")

    def test_plain_text_unchanged(self):
        self.assertEqual(_esc("US imposes tariffs"), "US imposes tariffs")


class TestFormatAnalysis(unittest.TestCase):

    def _make_result(self, **overrides) -> dict:
        base = {
            "headline": "US imposes new tariffs on steel",
            "stage": "realized",
            "persistence": "structural",
            "analysis": {
                "what_changed": "The US imposed 25% tariffs on steel imports.",
                "mechanism_summary": "Steel importers face higher costs.",
                "beneficiaries": ["US Steel producers"],
                "losers": ["European auto OEMs"],
                "beneficiary_tickers": ["NUE", "X"],
                "loser_tickers": ["VWAGY"],
                "confidence": "medium",
            },
            "market": {"note": "", "details": {}, "tickers": []},
            "is_mock": False,
            "event_date": "2025-04-05",
        }
        base.update(overrides)
        return base

    def test_contains_headline(self):
        reply = format_analysis(self._make_result())
        self.assertIn("US imposes new tariffs on steel", reply)

    def test_contains_stage_and_persistence(self):
        reply = format_analysis(self._make_result())
        self.assertIn("realized", reply)
        self.assertIn("structural", reply)

    def test_contains_confidence(self):
        reply = format_analysis(self._make_result())
        self.assertIn("medium", reply)

    def test_contains_tickers(self):
        reply = format_analysis(self._make_result())
        self.assertIn("NUE", reply)
        self.assertIn("VWAGY", reply)

    def test_contains_beneficiaries_and_losers(self):
        reply = format_analysis(self._make_result())
        self.assertIn("US Steel producers", reply)
        self.assertIn("European auto OEMs", reply)

    def test_contains_mechanism(self):
        reply = format_analysis(self._make_result())
        self.assertIn("Steel importers face higher costs", reply)

    def test_contains_event_date(self):
        reply = format_analysis(self._make_result())
        self.assertIn("2025-04-05", reply)

    def test_mock_flag_shown(self):
        reply = format_analysis(self._make_result(is_mock=True))
        self.assertIn("mock", reply)
        # Mock should NOT show confidence
        self.assertNotIn("confidence:", reply)

    def test_truncates_long_mechanism(self):
        long_mech = "A" * 500
        result = self._make_result()
        result["analysis"]["mechanism_summary"] = long_mech
        reply = format_analysis(result)
        self.assertIn("...", reply)
        # Should not exceed ~300 chars for the mechanism
        mech_line = [l for l in reply.split("\n") if "Mechanism" in l][0]
        self.assertLess(len(mech_line), 350)

    def test_escapes_html_in_headline(self):
        result = self._make_result(headline="A & B <test>")
        reply = format_analysis(result)
        self.assertIn("A &amp; B &lt;test&gt;", reply)

    def test_empty_analysis_fields(self):
        result = self._make_result()
        result["analysis"]["beneficiaries"] = []
        result["analysis"]["losers"] = []
        result["analysis"]["beneficiary_tickers"] = []
        result["analysis"]["loser_tickers"] = []
        reply = format_analysis(result)
        # Should not crash, should still have headline
        self.assertIn("US imposes", reply)
        self.assertNotIn("Beneficiaries", reply)
        self.assertNotIn("Tickers", reply)


class TestFormatBrief(unittest.TestCase):

    def _cluster(self, headline="Test headline", summary="Summary text.",
                 sector="energy", action="tariffs", source_count=2) -> dict:
        return {
            "headline": headline,
            "summary": summary,
            "consensus": {"sector": sector, "action": action},
            "sources": [{"name": "BBC"}, {"name": "Reuters"}][:source_count],
            "source_count": source_count,
            "agreement": "consistent",
        }

    def test_renders_up_to_5_items(self):
        clusters = [self._cluster(f"Headline {i}") for i in range(10)]
        reply = format_brief(clusters)
        # Should contain items 1-5 but not 6+
        self.assertIn("1.", reply)
        self.assertIn("5.", reply)
        self.assertNotIn("6.", reply)

    def test_contains_headline_and_summary(self):
        reply = format_brief([self._cluster()])
        self.assertIn("Test headline", reply)
        self.assertIn("Summary text.", reply)

    def test_contains_sector_and_action_tags(self):
        reply = format_brief([self._cluster(sector="energy", action="tariffs")])
        self.assertIn("energy", reply)
        self.assertIn("tariffs", reply)

    def test_multi_source_shown(self):
        reply = format_brief([self._cluster(source_count=3)])
        self.assertIn("3 sources", reply)

    def test_single_source_no_count(self):
        reply = format_brief([self._cluster(source_count=1)])
        self.assertNotIn("1 sources", reply)

    def test_empty_clusters_returns_fallback(self):
        reply = format_brief([])
        self.assertIn("No headlines available", reply)

    def test_skips_malformed_and_notes_count(self):
        good = self._cluster("Good headline")
        bad = {"headline": "", "summary": "no headline"}
        reply = format_brief([bad, good])
        self.assertIn("Good headline", reply)
        self.assertIn("skipped", reply)

    def test_truncates_long_summary(self):
        long_summary = "A" * 500
        reply = format_brief([self._cluster(summary=long_summary)])
        self.assertIn("...", reply)

    def test_unknown_sector_hidden(self):
        reply = format_brief([self._cluster(sector="unknown", action="unknown")])
        self.assertNotIn("unknown", reply)

    def test_escapes_html(self):
        reply = format_brief([self._cluster(headline="A & B <test>")])
        self.assertIn("&amp;", reply)
        self.assertIn("&lt;", reply)

    def test_max_items_param(self):
        clusters = [self._cluster(f"H{i}") for i in range(10)]
        reply = format_brief(clusters, max_items=3)
        self.assertIn("3.", reply)
        self.assertNotIn("4.", reply)


class TestParseTime(unittest.TestCase):

    def test_valid_time(self):
        t = parse_time("08:00")
        self.assertEqual(t, datetime.time(8, 0))

    def test_valid_time_afternoon(self):
        t = parse_time("14:30")
        self.assertEqual(t, datetime.time(14, 30))

    def test_invalid_format(self):
        self.assertIsNone(parse_time("8am"))

    def test_empty_string(self):
        self.assertIsNone(parse_time(""))

    def test_out_of_range(self):
        self.assertIsNone(parse_time("25:00"))

    def test_whitespace_stripped(self):
        t = parse_time("  09:15  ")
        self.assertEqual(t, datetime.time(9, 15))

    def test_no_colon(self):
        self.assertIsNone(parse_time("0800"))


class TestBuildMorningBrief(unittest.TestCase):

    def test_returns_string_on_success(self):
        from unittest.mock import patch
        fake_news = {
            "clusters": [
                {"headline": "Test", "summary": "S", "consensus": {}, "sources": [], "source_count": 1},
            ],
            "total_headlines": 1,
        }
        with patch("telegram_bot.call_news", return_value=fake_news):
            result = build_morning_brief()
        self.assertIsNotNone(result)
        self.assertIn("Test", result)

    def test_returns_none_on_empty_clusters(self):
        from unittest.mock import patch
        with patch("telegram_bot.call_news", return_value={"clusters": []}):
            result = build_morning_brief()
        self.assertIsNone(result)

    def test_returns_none_on_api_failure(self):
        from unittest.mock import patch
        with patch("telegram_bot.call_news", side_effect=Exception("down")):
            result = build_morning_brief()
        self.assertIsNone(result)


class TestFormatAlert(unittest.TestCase):

    def test_contains_symbol_and_move(self):
        alert = {
            "event_id": 1, "headline": "OPEC cuts output",
            "symbol": "XLE", "role": "beneficiary",
            "return_5d": 4.5, "direction": "supports ↑",
        }
        reply = format_alert(alert)
        self.assertIn("XLE", reply)
        self.assertIn("+4.50%", reply)
        self.assertIn("up", reply)

    def test_negative_move(self):
        alert = {
            "event_id": 1, "headline": "Tariffs imposed",
            "symbol": "VWAGY", "role": "loser",
            "return_5d": -3.2, "direction": "supports ↓",
        }
        reply = format_alert(alert)
        self.assertIn("VWAGY", reply)
        self.assertIn("-3.20%", reply)
        self.assertIn("down", reply)

    def test_contains_headline_context(self):
        alert = {
            "event_id": 1, "headline": "US steel tariffs",
            "symbol": "NUE", "role": "beneficiary",
            "return_5d": 5.0, "direction": "supports ↑",
        }
        reply = format_alert(alert)
        self.assertIn("US steel tariffs", reply)

    def test_escapes_html(self):
        alert = {
            "event_id": 1, "headline": "A & B <test>",
            "symbol": "TST", "role": "beneficiary",
            "return_5d": 3.0, "direction": "",
        }
        reply = format_alert(alert)
        self.assertIn("&amp;", reply)


class TestCheckWatchlistAlerts(unittest.TestCase):

    def setUp(self):
        _alerted.clear()

    def _fake_events(self):
        return [
            {"id": 1, "headline": "H1", "event_date": "2025-03-01",
             "market_tickers": [{"symbol": "GLD", "role": "beneficiary"}]},
            {"id": 2, "headline": "H2", "event_date": "2025-03-02",
             "market_tickers": [{"symbol": "USO", "role": "loser"}]},
        ]

    def _fake_batch(self):
        return [
            {"event_id": 1, "outcomes": [
                {"symbol": "GLD", "role": "beneficiary",
                 "return_5d": 5.0, "direction": "supports ↑"},
            ], "score": {"supporting": 1, "total": 1}},
            {"event_id": 2, "outcomes": [
                {"symbol": "USO", "role": "loser",
                 "return_5d": -1.0, "direction": "supports ↓"},
            ], "score": {"supporting": 1, "total": 1}},
        ]

    def test_returns_alerts_above_threshold(self):
        with patch("telegram_bot._api_get", return_value=self._fake_events()), \
             patch("telegram_bot._api_post", return_value=self._fake_batch()):
            alerts = check_watchlist_alerts(threshold=3.0)
        # GLD moved +5% (above 3% threshold), USO moved -1% (below)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["symbol"], "GLD")

    def test_deduplicates_on_second_poll(self):
        with patch("telegram_bot._api_get", return_value=self._fake_events()), \
             patch("telegram_bot._api_post", return_value=self._fake_batch()):
            alerts1 = check_watchlist_alerts(threshold=3.0)
            alerts2 = check_watchlist_alerts(threshold=3.0)
        self.assertEqual(len(alerts1), 1)
        self.assertEqual(len(alerts2), 0)  # already alerted

    def test_returns_empty_on_api_failure(self):
        with patch("telegram_bot._api_get", side_effect=Exception("down")):
            alerts = check_watchlist_alerts()
        self.assertEqual(alerts, [])

    def test_skips_events_without_date(self):
        no_date = [{"id": 1, "headline": "H1", "market_tickers": [{"symbol": "GLD"}]}]
        with patch("telegram_bot._api_get", return_value=no_date):
            alerts = check_watchlist_alerts()
        self.assertEqual(alerts, [])


class TestExtractHeadline(unittest.TestCase):

    def test_plain_headline(self):
        r = extract_headline(text="US imposes new tariffs on steel")
        self.assertEqual(r, "US imposes new tariffs on steel")

    def test_forwarded_text_takes_priority(self):
        r = extract_headline(
            text="wow check this out",
            forward_text="OPEC agrees surprise production cut",
        )
        self.assertEqual(r, "OPEC agrees surprise production cut")

    def test_caption_used_when_no_text(self):
        r = extract_headline(text=None, caption="Fed signals rate cut amid recession fears")
        self.assertEqual(r, "Fed signals rate cut amid recession fears")

    def test_url_plus_commentary(self):
        r = extract_headline(text="https://reuters.com/article/xyz EU tariffs on steel")
        self.assertEqual(r, "EU tariffs on steel")

    def test_url_only_returns_url(self):
        r = extract_headline(text="https://reuters.com/article/tariffs-on-steel")
        self.assertEqual(r, "https://reuters.com/article/tariffs-on-steel")

    def test_strips_noise_prefix(self):
        r = extract_headline(text="look at this!! US imposes tariffs")
        self.assertEqual(r, "US imposes tariffs")

    def test_strips_multiple_noise_prefixes(self):
        r = extract_headline(text="omg wow check this: OPEC cuts output")
        self.assertEqual(r, "OPEC cuts output")

    def test_strips_trailing_emoji_commentary(self):
        r = extract_headline(text="Fed raises rates\n\U0001F525\U0001F525\U0001F525")
        self.assertEqual(r, "Fed raises rates")

    def test_empty_returns_none(self):
        self.assertIsNone(extract_headline(text=""))
        self.assertIsNone(extract_headline(text=None))

    def test_too_short_returns_none(self):
        self.assertIsNone(extract_headline(text="hi"))
        self.assertIsNone(extract_headline(text="lol"))

    def test_emoji_only_returns_none(self):
        self.assertIsNone(extract_headline(text="\U0001F525\U0001F525\U0001F525"))

    def test_caps_at_500(self):
        long = "A" * 600
        r = extract_headline(text=long)
        self.assertEqual(len(r), 500)

    def test_preserves_real_headline_with_noise(self):
        r = extract_headline(text="fyi: Germany ramps up defence spending in NATO push")
        self.assertEqual(r, "Germany ramps up defence spending in NATO push")

    # -- URL + commentary: headline before URL --

    def test_headline_before_url(self):
        r = extract_headline(
            text="EU imposes retaliatory tariffs on US steel https://reuters.com/article/xyz"
        )
        self.assertEqual(r, "EU imposes retaliatory tariffs on US steel")

    def test_headline_before_url_with_noise_prefix(self):
        r = extract_headline(
            text="check this: OPEC cuts output by 500k bpd https://reuters.com/article/opec"
        )
        self.assertEqual(r, "OPEC cuts output by 500k bpd")

    # -- URL + commentary: headline after URL --

    def test_headline_after_url(self):
        r = extract_headline(
            text="https://ft.com/content/abc123 Germany ramps up defence spending in NATO push"
        )
        self.assertEqual(r, "Germany ramps up defence spending in NATO push")

    # -- URL + opinion: prefers headline over opinion --

    def test_headline_preferred_over_opinion(self):
        r = extract_headline(
            text="US sanctions Russian oil exports https://reuters.com/x this feels big for oil and shipping"
        )
        # Should pick the headline-like segment, not the opinion
        self.assertIn("US sanctions Russian oil exports", r)
        self.assertNotIn("this feels", r)

    def test_opinion_before_url_headline_after(self):
        r = extract_headline(
            text="this looks important https://bbc.com/news/xyz Fed signals rate cut amid recession"
        )
        self.assertEqual(r, "Fed signals rate cut amid recession")

    # -- commentary-only + URL falls back cleanly --

    def test_opinion_only_with_url_falls_back_to_opinion(self):
        """When no headline-like segment exists, return whatever text we have."""
        r = extract_headline(
            text="this could be huge https://reuters.com/article/abc thoughts?"
        )
        # "thoughts?" is too short; "this could be huge" starts with opinion marker
        # but it's the only usable text. Should return something, not None.
        self.assertIsNotNone(r)

    def test_url_with_short_opinion_only(self):
        r = extract_headline(text="wow https://reuters.com/article/abc lol")
        # Both segments are too short after noise strip → fall back to URL
        self.assertIn("reuters.com", r)


if __name__ == "__main__":
    unittest.main()
