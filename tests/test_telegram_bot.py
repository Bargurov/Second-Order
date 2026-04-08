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
    extract_headline, format_benchmarks,
    format_market_context, call_market_context,
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


# ---------------------------------------------------------------------------
# format_benchmarks — the new liquid benchmarks block
# ---------------------------------------------------------------------------

class TestFormatBenchmarks(unittest.TestCase):
    """Tests for the new format_benchmarks() function."""

    EXPECTED_MARKETS = ("ES", "NQ", "RTY", "CL", "GC", "DXY", "2Y", "10Y")

    def _snap(self, market: str, value: float | None = 100.0,
              change_5d: float | None = 1.5, unit: str = "idx",
              stale: bool = False, error: str | None = None,
              source: str = "yfinance") -> dict:
        return {
            "market": market,
            "symbol": f"{market}-SYM",
            "label": f"{market} label",
            "unit": unit,
            "asset_class": "equity_index",
            "source": source,
            "value": value,
            "change_1d": 0.5,
            "change_5d": change_5d,
            "fetched_at": "2026-04-07T12:00:00+00:00",
            "error": error,
            "stale": stale,
        }

    def _all_fresh(self) -> list[dict]:
        return [self._snap(m, value=100.0 + i, change_5d=1.0 + i * 0.1)
                for i, m in enumerate(self.EXPECTED_MARKETS)]

    # -- Empty / unavailable cases --------------------------------------

    def test_empty_list_returns_empty_string(self):
        self.assertEqual(format_benchmarks([]), "")

    def test_none_returns_empty_string(self):
        self.assertEqual(format_benchmarks(None), "")  # type: ignore

    def test_all_unavailable_returns_empty(self):
        """If every market has no value, the block should be omitted entirely."""
        snaps = [self._snap(m, value=None, error="no data")
                 for m in self.EXPECTED_MARKETS]
        self.assertEqual(format_benchmarks(snaps), "")

    # -- Full data path --------------------------------------------------

    def test_full_data_includes_all_markets(self):
        result = format_benchmarks(self._all_fresh())
        for market in self.EXPECTED_MARKETS:
            self.assertIn(market, result, f"Missing {market} in benchmark block")

    def test_full_data_has_header(self):
        result = format_benchmarks(self._all_fresh())
        self.assertIn("Liquid Benchmarks", result)

    def test_full_data_shows_values_and_changes(self):
        result = format_benchmarks(self._all_fresh())
        # First snapshot: value=100.0, change=+1.00%
        self.assertIn("100.00", result)
        self.assertIn("+1.00%", result)

    def test_canonical_order_in_output(self):
        """Markets should appear in canonical order regardless of input order."""
        # Provide reversed
        snaps = list(reversed(self._all_fresh()))
        result = format_benchmarks(snaps)
        positions = [result.find(m) for m in self.EXPECTED_MARKETS]
        # Each position should be greater than the previous
        for i in range(1, len(positions)):
            self.assertLess(positions[i - 1], positions[i],
                            f"{self.EXPECTED_MARKETS[i]} out of order")

    def test_html_escaping_in_footer(self):
        """The footer text should be HTML-escaped."""
        snaps = self._all_fresh()
        result = format_benchmarks(snaps)
        # Source label appears via _esc; ensure no raw < or > leak in
        self.assertNotIn("<script", result.lower())

    def test_signed_change_formatting(self):
        snaps = [
            self._snap("ES", value=4500.0, change_5d=2.5),
            self._snap("NQ", value=15000.0, change_5d=-1.25),
        ]
        # Pad to all markets so block isn't empty
        snaps += [self._snap(m, value=100.0, change_5d=0.0)
                  for m in ("RTY", "CL", "GC", "DXY", "2Y", "10Y")]
        result = format_benchmarks(snaps)
        self.assertIn("+2.50%", result)
        self.assertIn("-1.25%", result)

    def test_percent_unit_formatting(self):
        """The 10Y / yield-style markets should render with % suffix on value."""
        snaps = [self._snap(m, value=100.0, change_5d=0.5)
                 for m in self.EXPECTED_MARKETS]
        # Override 10Y to use % unit
        for s in snaps:
            if s["market"] == "10Y":
                s["unit"] = "%"
                s["value"] = 4.50
        result = format_benchmarks(snaps)
        self.assertIn("4.50%", result)

    def test_thousand_separators(self):
        snaps = [self._snap("ES", value=4523.75)]
        snaps += [self._snap(m) for m in self.EXPECTED_MARKETS if m != "ES"]
        result = format_benchmarks(snaps)
        self.assertIn("4,523.75", result)

    def test_source_in_footer(self):
        snaps = self._all_fresh()
        result = format_benchmarks(snaps)
        self.assertIn("yfinance", result)

    # -- Stale snapshots -------------------------------------------------

    def test_stale_snapshot_tagged(self):
        snaps = self._all_fresh()
        snaps[0]["stale"] = True
        result = format_benchmarks(snaps)
        # The stale tag should appear inline
        self.assertIn("stale", result)
        # The value should still be present
        self.assertIn("100.00", result)

    def test_stale_count_in_footer(self):
        snaps = self._all_fresh()
        snaps[0]["stale"] = True
        snaps[2]["stale"] = True
        result = format_benchmarks(snaps)
        self.assertIn("2 stale", result)

    def test_all_stale_still_renders_data(self):
        """Every market stale → block still renders (degraded but visible)."""
        snaps = self._all_fresh()
        for s in snaps:
            s["stale"] = True
        result = format_benchmarks(snaps)
        self.assertIn("Liquid Benchmarks", result)
        self.assertIn("8 stale", result)

    # -- Partial availability --------------------------------------------

    def test_one_market_unavailable(self):
        snaps = self._all_fresh()
        snaps[3]["value"] = None
        snaps[3]["error"] = "no data"
        result = format_benchmarks(snaps)
        self.assertIn("n/a", result)
        self.assertIn("1 n/a", result)
        # Other markets still rendered
        self.assertIn("100.00", result)

    def test_missing_market_shown_as_na(self):
        """If a market is entirely absent from the response, show n/a."""
        snaps = self._all_fresh()
        # Drop the last two
        snaps = snaps[:-2]
        result = format_benchmarks(snaps)
        # Last two markets ("2Y", "10Y") should be marked n/a
        self.assertIn("2Y", result)
        self.assertIn("10Y", result)
        self.assertIn("n/a", result)

    def test_partial_availability_keeps_block(self):
        """As long as at least one market is usable, render the block."""
        snaps = [self._snap("ES", value=4500.0, change_5d=1.0)]
        snaps += [self._snap(m, value=None, error="no data")
                  for m in self.EXPECTED_MARKETS if m != "ES"]
        result = format_benchmarks(snaps)
        self.assertIn("Liquid Benchmarks", result)
        self.assertIn("4,500.00", result)
        self.assertIn("7 n/a", result)

    def test_mixed_stale_and_unavailable(self):
        snaps = self._all_fresh()
        snaps[0]["stale"] = True
        snaps[1]["value"] = None
        snaps[1]["error"] = "no data"
        result = format_benchmarks(snaps)
        self.assertIn("1 stale", result)
        self.assertIn("1 n/a", result)

    # -- Integration with build_morning_brief ---------------------------

# NOTE: legacy build_morning_brief tests that exercised the old
# call_snapshots / format_benchmarks composition were removed when /brief
# migrated to call_market_context.  See TestFormatMarketContext below for
# the replacement coverage that hits the unified path.


# ---------------------------------------------------------------------------
# call_market_context — graceful failure
# ---------------------------------------------------------------------------

class TestCallMarketContext(unittest.TestCase):

    def test_returns_dict_on_success(self):
        fake = {
            "built_at": "2026-04-07T12:00:00+00:00",
            "source": "yfinance",
            "snapshots": [],
            "snapshots_meta": {"total": 0, "fresh": 0, "stale": 0, "unavailable": 0},
            "stress": {"regime": "Calm", "available": True, "signals": {}, "summary": "ok"},
            "highlights": [],
            "highlights_meta": {"count": 0, "source": "movers/today"},
        }
        with patch("telegram_bot._api_get", return_value=fake):
            result = call_market_context()
        self.assertEqual(result, fake)

    def test_returns_empty_dict_on_failure(self):
        with patch("telegram_bot._api_get", side_effect=Exception("network down")):
            result = call_market_context()
        self.assertEqual(result, {})

    def test_returns_empty_dict_on_non_dict_response(self):
        """A malformed response (e.g. list) should not break the bot."""
        with patch("telegram_bot._api_get", return_value=[1, 2, 3]):
            result = call_market_context()
        self.assertEqual(result, {})

    def test_highlight_limit_in_url(self):
        captured = {}

        def _spy(path):
            captured["path"] = path
            return {"snapshots": [], "stress": {}, "highlights": []}

        with patch("telegram_bot._api_get", side_effect=_spy):
            call_market_context(highlight_limit=7)
        self.assertIn("highlight_limit=7", captured["path"])


# ---------------------------------------------------------------------------
# format_market_context — the unified bot composer
# ---------------------------------------------------------------------------

class TestFormatMarketContext(unittest.TestCase):
    """Tests for the unified format_market_context() function consuming
    the /market-context payload."""

    EXPECTED_MARKETS = ("ES", "NQ", "RTY", "CL", "GC", "DXY", "2Y", "10Y")

    def _snap(self, market, value=100.0, change=1.5, stale=False, error=None):
        return {
            "market": market,
            "symbol": f"{market}-SYM",
            "label": f"{market} label",
            "unit": "idx",
            "asset_class": "equity_index",
            "source": "yfinance",
            "value": value,
            "change_1d": 0.5,
            "change_5d": change,
            "fetched_at": "2026-04-07T12:00:00+00:00",
            "error": error,
            "stale": stale,
        }

    def _full_snapshots(self):
        return [self._snap(m, value=100.0 + i, change=1.0 + i * 0.1)
                for i, m in enumerate(self.EXPECTED_MARKETS)]

    def _stress(self, regime="Calm", active=0, summary="Markets stable"):
        signals = {
            "vix_elevated": active > 0,
            "term_inversion": active > 1,
            "credit_widening": active > 2,
            "safe_haven_bid": active > 3,
            "breadth_deterioration": active > 4,
        }
        return {
            "regime": regime,
            "summary": summary,
            "signals": signals,
            "raw": {},
            "detail": {},
            "available": True,
        }

    def _highlights(self):
        return [
            {
                "event_id": 1,
                "headline": "OPEC announces surprise production cut",
                "impact": 4.5,
                "support_ratio": 1.0,
                "tickers": [
                    {"symbol": "USO", "return_5d": 3.20, "role": "beneficiary"},
                ],
            },
            {
                "event_id": 2,
                "headline": "EU imposes new tariffs on US steel imports",
                "impact": 3.2,
                "support_ratio": 0.5,
                "tickers": [
                    {"symbol": "X", "return_5d": -2.10, "role": "loser"},
                ],
            },
        ]

    def _full_context(self):
        return {
            "built_at": "2026-04-07T12:00:00+00:00",
            "source": "yfinance",
            "snapshots": self._full_snapshots(),
            "snapshots_meta": {"total": 8, "fresh": 8, "stale": 0, "unavailable": 0},
            "stress": self._stress(regime="Geopolitical Stress", active=2),
            "highlights": self._highlights(),
            "highlights_meta": {"count": 2, "source": "movers/today"},
        }

    # -- Empty / degraded cases ----------------------------------------

    def test_empty_dict_returns_empty_string(self):
        self.assertEqual(format_market_context({}), "")

    def test_none_returns_empty_string(self):
        self.assertEqual(format_market_context(None), "")  # type: ignore

    def test_all_sections_empty_returns_empty_string(self):
        ctx = {
            "built_at": "2026-04-07T12:00:00+00:00",
            "source": "yfinance",
            "snapshots": [],
            "snapshots_meta": {"total": 0, "fresh": 0, "stale": 0, "unavailable": 0},
            "stress": {"regime": "Unknown", "available": False, "signals": {}},
            "highlights": [],
            "highlights_meta": {"count": 0, "source": "movers/today"},
        }
        self.assertEqual(format_market_context(ctx), "")

    # -- Full data path -------------------------------------------------

    def test_full_context_includes_benchmarks(self):
        result = format_market_context(self._full_context())
        self.assertIn("Liquid Benchmarks", result)
        for m in self.EXPECTED_MARKETS:
            self.assertIn(m, result)

    def test_full_context_includes_regime(self):
        result = format_market_context(self._full_context())
        self.assertIn("Market Regime", result)
        self.assertIn("Geopolitical Stress", result)
        self.assertIn("2 signals active", result)

    def test_full_context_includes_highlights(self):
        result = format_market_context(self._full_context())
        self.assertIn("Today's Movers", result)
        self.assertIn("OPEC", result)
        self.assertIn("EU imposes new tariffs", result)

    def test_full_context_section_order(self):
        """Benchmarks come first, then regime, then highlights."""
        result = format_market_context(self._full_context())
        bench_pos = result.index("Liquid Benchmarks")
        regime_pos = result.index("Market Regime")
        movers_pos = result.index("Today's Movers")
        self.assertLess(bench_pos, regime_pos)
        self.assertLess(regime_pos, movers_pos)

    def test_highlights_show_top_ticker(self):
        result = format_market_context(self._full_context())
        self.assertIn("USO", result)
        self.assertIn("+3.20%", result)
        self.assertIn("-2.10%", result)

    def test_highlights_truncate_long_headline(self):
        long = "A" * 200
        ctx = self._full_context()
        ctx["highlights"] = [{
            "event_id": 1, "headline": long, "tickers": [],
        }]
        result = format_market_context(ctx)
        # Truncated to 70 chars
        self.assertNotIn("A" * 100, result)
        self.assertIn("...", result)

    # -- Partial availability -------------------------------------------

    def test_only_benchmarks_available(self):
        ctx = self._full_context()
        ctx["stress"] = {"regime": "Unknown", "available": False, "signals": {}}
        ctx["highlights"] = []
        ctx["highlights_meta"]["count"] = 0
        result = format_market_context(ctx)
        self.assertIn("Liquid Benchmarks", result)
        self.assertNotIn("Market Regime", result)
        self.assertNotIn("Today's Movers", result)

    def test_only_stress_available(self):
        ctx = self._full_context()
        ctx["snapshots"] = []
        ctx["snapshots_meta"] = {"total": 0, "fresh": 0, "stale": 0, "unavailable": 0}
        ctx["highlights"] = []
        result = format_market_context(ctx)
        self.assertNotIn("Liquid Benchmarks", result)
        self.assertIn("Market Regime", result)
        self.assertIn("Geopolitical Stress", result)

    def test_only_highlights_available(self):
        ctx = self._full_context()
        ctx["snapshots"] = []
        ctx["snapshots_meta"] = {"total": 0, "fresh": 0, "stale": 0, "unavailable": 0}
        ctx["stress"] = {"regime": "Unknown", "available": False, "signals": {}}
        result = format_market_context(ctx)
        self.assertNotIn("Liquid Benchmarks", result)
        self.assertNotIn("Market Regime", result)
        self.assertIn("Today's Movers", result)

    def test_some_snapshots_unavailable(self):
        ctx = self._full_context()
        ctx["snapshots"][0]["value"] = None
        ctx["snapshots"][0]["error"] = "no data"
        ctx["snapshots_meta"] = {"total": 8, "fresh": 7, "stale": 0, "unavailable": 1}
        result = format_market_context(ctx)
        self.assertIn("Liquid Benchmarks", result)
        self.assertIn("n/a", result)

    def test_stress_unknown_regime_omitted(self):
        ctx = self._full_context()
        ctx["stress"]["regime"] = "Unknown"
        result = format_market_context(ctx)
        self.assertNotIn("Market Regime", result)
        # Benchmarks and highlights still rendered
        self.assertIn("Liquid Benchmarks", result)
        self.assertIn("Today's Movers", result)

    def test_stress_unavailable_flag_skips_section(self):
        ctx = self._full_context()
        ctx["stress"]["available"] = False
        result = format_market_context(ctx)
        self.assertNotIn("Market Regime", result)

    # -- Stale-state formatting -----------------------------------------

    def test_stale_snapshot_tagged_inline(self):
        ctx = self._full_context()
        ctx["snapshots"][0]["stale"] = True
        ctx["snapshots_meta"] = {"total": 8, "fresh": 7, "stale": 1, "unavailable": 0}
        result = format_market_context(ctx)
        self.assertIn("stale", result)
        # Value still rendered
        self.assertIn("100.00", result)

    def test_stale_count_in_benchmarks_footer(self):
        ctx = self._full_context()
        ctx["snapshots"][0]["stale"] = True
        ctx["snapshots"][2]["stale"] = True
        ctx["snapshots_meta"] = {"total": 8, "fresh": 6, "stale": 2, "unavailable": 0}
        result = format_market_context(ctx)
        self.assertIn("2 stale", result)

    def test_all_stale_still_renders(self):
        ctx = self._full_context()
        for s in ctx["snapshots"]:
            s["stale"] = True
        ctx["snapshots_meta"] = {"total": 8, "fresh": 0, "stale": 8, "unavailable": 0}
        result = format_market_context(ctx)
        self.assertIn("Liquid Benchmarks", result)
        self.assertIn("8 stale", result)

    def test_mixed_stale_and_unavailable(self):
        ctx = self._full_context()
        ctx["snapshots"][0]["stale"] = True
        ctx["snapshots"][1]["value"] = None
        ctx["snapshots"][1]["error"] = "no data"
        ctx["snapshots_meta"] = {"total": 8, "fresh": 6, "stale": 1, "unavailable": 1}
        result = format_market_context(ctx)
        self.assertIn("1 stale", result)
        self.assertIn("1 n/a", result)

    # -- HTML escaping --------------------------------------------------

    def test_html_escaping_in_highlights(self):
        ctx = self._full_context()
        ctx["highlights"][0]["headline"] = "A & B <script> attack"
        result = format_market_context(ctx)
        self.assertIn("&amp;", result)
        self.assertIn("&lt;script&gt;", result)
        self.assertNotIn("<script>", result)

    # -- Integration with build_morning_brief ----------------------------

    def test_morning_brief_uses_market_context(self):
        """build_morning_brief should call call_market_context, not call_snapshots."""
        fake_news = {
            "clusters": [
                {"headline": "Test event", "summary": "S",
                 "consensus": {}, "sources": [], "source_count": 1},
            ],
            "total_headlines": 1,
        }
        with patch("telegram_bot.call_news", return_value=fake_news), \
             patch("telegram_bot.call_market_context", return_value=self._full_context()):
            result = build_morning_brief()
        self.assertIsNotNone(result)
        self.assertIn("Liquid Benchmarks", result)
        self.assertIn("Market Regime", result)
        self.assertIn("Today's Movers", result)
        self.assertIn("Test event", result)
        # Context block appears BEFORE the news brief
        self.assertLess(result.index("Liquid Benchmarks"), result.index("Test event"))

    def test_morning_brief_without_context(self):
        """When /market-context is empty, brief still renders without the block."""
        fake_news = {
            "clusters": [
                {"headline": "Test event", "summary": "S",
                 "consensus": {}, "sources": [], "source_count": 1},
            ],
            "total_headlines": 1,
        }
        with patch("telegram_bot.call_news", return_value=fake_news), \
             patch("telegram_bot.call_market_context", return_value={}):
            result = build_morning_brief()
        self.assertIsNotNone(result)
        self.assertNotIn("Liquid Benchmarks", result)
        self.assertNotIn("Market Regime", result)
        self.assertIn("Test event", result)

    def test_morning_brief_with_partial_context(self):
        """Partial context produces a degraded block but the news brief still renders."""
        fake_news = {
            "clusters": [
                {"headline": "Test event", "summary": "S",
                 "consensus": {}, "sources": [], "source_count": 1},
            ],
            "total_headlines": 1,
        }
        ctx = self._full_context()
        # Make snapshots partial
        ctx["snapshots"] = [self._snap("ES", value=4500.0, change=1.0)]
        ctx["snapshots"] += [self._snap(m, value=None, error="no data")
                             for m in self.EXPECTED_MARKETS if m != "ES"]
        ctx["snapshots_meta"] = {"total": 8, "fresh": 1, "stale": 0, "unavailable": 7}
        # Drop highlights
        ctx["highlights"] = []
        ctx["highlights_meta"]["count"] = 0
        with patch("telegram_bot.call_news", return_value=fake_news), \
             patch("telegram_bot.call_market_context", return_value=ctx):
            result = build_morning_brief()
        self.assertIsNotNone(result)
        self.assertIn("Liquid Benchmarks", result)
        self.assertIn("4,500.00", result)
        self.assertIn("7 n/a", result)
        # Stress still rendered
        self.assertIn("Market Regime", result)
        # Highlights omitted
        self.assertNotIn("Today's Movers", result)
        self.assertIn("Test event", result)

    def test_morning_brief_stale_snapshots(self):
        fake_news = {
            "clusters": [
                {"headline": "Test event", "summary": "S",
                 "consensus": {}, "sources": [], "source_count": 1},
            ],
            "total_headlines": 1,
        }
        ctx = self._full_context()
        for s in ctx["snapshots"]:
            s["stale"] = True
        ctx["snapshots_meta"] = {"total": 8, "fresh": 0, "stale": 8, "unavailable": 0}
        with patch("telegram_bot.call_news", return_value=fake_news), \
             patch("telegram_bot.call_market_context", return_value=ctx):
            result = build_morning_brief()
        self.assertIsNotNone(result)
        self.assertIn("Liquid Benchmarks", result)
        self.assertIn("8 stale", result)
        self.assertIn("Test event", result)

    def test_morning_brief_context_failure_does_not_break_news(self):
        """If call_market_context raises, the morning brief should still bail safely."""
        fake_news = {
            "clusters": [
                {"headline": "Test event", "summary": "S",
                 "consensus": {}, "sources": [], "source_count": 1},
            ],
            "total_headlines": 1,
        }
        with patch("telegram_bot.call_news", return_value=fake_news), \
             patch("telegram_bot.call_market_context", side_effect=Exception("ctx down")):
            result = build_morning_brief()
        # build_morning_brief catches and returns None on internal failure
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
