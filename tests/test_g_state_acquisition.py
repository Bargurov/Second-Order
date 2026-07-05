"""Tests for the G2 point-in-time state-data acquisition substrate.

Contract under test (G0 protocol, g0-v1):

* conservative cutoff = last completed trading session STRICTLY before the
  source-pinned event date (weekends/holidays resolve to the prior session);
* per-series availability semantics: same-day series (closes, policy
  decisions) are eligible when observation date <= cutoff; next-day series
  (Treasury curve) require observation date strictly BEFORE the cutoff;
* trailing windows (252-session percentile, 200-session moving average) use
  only history at or before the cutoff, never shorten silently, and are
  immune to future observations;
* the Fed policy path uses the frame-derived target-range timeline with
  same-day availability, so a candidate's OWN decision never enters its
  pre-event lookback;
* missing or blocked sources produce explicit unavailable states, never a
  proxy value;
* readiness artifacts carry ONLY whitelisted non-outcome fields;
* the two G1 candidate ledgers reconcile deterministically to 65 + 32 = 97.

Pure fixtures only; no network. Live-ledger reconciliation tests are skipped
when the artifacts are absent.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import g_state_acquisition as gsa  # noqa: E402

G1A = ROOT / "stats" / "G1A_FOMC_FRAME_INVENTORY.md"
G1B = ROOT / "stats" / "G1B_OPEC_DESIGNED_RESERVOIR.md"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A tiny session calendar: Mon 2020-01-06 .. Fri 2020-01-10, then a gap
# (holiday Mon 2020-01-13 removed), resuming Tue 2020-01-14.
SESSIONS = ["2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09",
            "2020-01-10", "2020-01-14", "2020-01-15"]


def _series(dates, start=10.0, step=1.0):
    return {d: start + i * step for i, d in enumerate(dates)}


def _long_sessions(n, year=2019):
    """n synthetic consecutive weekday sessions ending 2020-01-10."""
    from datetime import date, timedelta
    out = []
    cur = date(2020, 1, 10)
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur -= timedelta(days=1)
    return sorted(out)


# ---------------------------------------------------------------------------
# 1. Conservative cutoff
# ---------------------------------------------------------------------------


class CutoffTests(unittest.TestCase):
    def test_monday_event_resolves_to_prior_friday(self):
        self.assertEqual(gsa.conservative_cutoff("2020-01-13", SESSIONS),
                         "2020-01-10")

    def test_sunday_event_resolves_to_prior_friday(self):
        self.assertEqual(gsa.conservative_cutoff("2020-01-12", SESSIONS),
                         "2020-01-10")

    def test_event_on_session_uses_strictly_prior_session(self):
        self.assertEqual(gsa.conservative_cutoff("2020-01-08", SESSIONS),
                         "2020-01-07")

    def test_event_after_holiday_gap_resolves_to_pre_gap_session(self):
        self.assertEqual(gsa.conservative_cutoff("2020-01-14", SESSIONS),
                         "2020-01-10")

    def test_event_before_first_session_is_unresolvable(self):
        self.assertIsNone(gsa.conservative_cutoff("2020-01-06", SESSIONS[:1]))


# ---------------------------------------------------------------------------
# 2. Per-series availability semantics
# ---------------------------------------------------------------------------


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.series = _series(SESSIONS)

    def test_same_day_series_includes_cutoff_observation(self):
        obs, val = gsa.latest_eligible(self.series, "2020-01-09",
                                       availability="same_day")
        self.assertEqual(obs, "2020-01-09")

    def test_next_day_series_excludes_cutoff_dated_observation(self):
        # the value DATED at the cutoff is published after the cutoff close
        obs, val = gsa.latest_eligible(self.series, "2020-01-09",
                                       availability="next_day")
        self.assertEqual(obs, "2020-01-08")

    def test_empty_series_yields_none(self):
        self.assertIsNone(gsa.latest_eligible({}, "2020-01-09",
                                              availability="same_day"))


# ---------------------------------------------------------------------------
# 3. Trailing windows: no lookahead, no silent shortening
# ---------------------------------------------------------------------------


class TrailingWindowTests(unittest.TestCase):
    def test_percentile_requires_full_window(self):
        dates = _long_sessions(251)
        out = gsa.trailing_percentile(_series(dates), "2020-01-10", window=252)
        self.assertIsNone(out["value"])
        self.assertEqual(out["reason"], "insufficient_history")

    def test_percentile_of_maximum_is_one(self):
        dates = _long_sessions(252)
        out = gsa.trailing_percentile(_series(dates), "2020-01-10", window=252)
        self.assertAlmostEqual(out["value"], 1.0)

    def test_future_observations_cannot_change_the_percentile(self):
        dates = _long_sessions(252)
        s = _series(dates)
        base = gsa.trailing_percentile(s, "2020-01-10", window=252)["value"]
        s["2020-02-03"] = 99999.0  # far above everything, strictly after cutoff
        after = gsa.trailing_percentile(s, "2020-01-10", window=252)["value"]
        self.assertEqual(base, after)

    def test_ma_distance_requires_full_window(self):
        dates = _long_sessions(199)
        out = gsa.ma_distance(_series(dates), "2020-01-10", window=200)
        self.assertIsNone(out["value"])
        self.assertEqual(out["reason"], "insufficient_history")

    def test_ma_distance_ignores_future_observations(self):
        dates = _long_sessions(200)
        s = _series(dates, start=100.0, step=0.0)  # flat: distance == 0
        base = gsa.ma_distance(s, "2020-01-10", window=200)["value"]
        s["2020-02-03"] = 500.0
        after = gsa.ma_distance(s, "2020-01-10", window=200)["value"]
        self.assertAlmostEqual(base, 0.0)
        self.assertEqual(base, after)


# ---------------------------------------------------------------------------
# 4. Fed policy path from the frame timeline
# ---------------------------------------------------------------------------


class FedPathTests(unittest.TestCase):
    TIMELINE = [("2017-06-14", 1.125), ("2017-12-13", 1.375),
                ("2018-03-21", 1.625), ("2018-06-13", 1.875),
                ("2018-09-26", 2.125)]

    def test_net_change_over_six_months(self):
        out = gsa.fed_net_change(self.TIMELINE, "2018-06-20", months=6)
        # level 1.875 at cutoff; level 1.375 six months earlier (2017-12-20)
        self.assertAlmostEqual(out["value"], 0.50)

    def test_own_decision_day_is_excluded_by_the_cutoff(self):
        # a candidate whose event IS the 2018-06-13 decision has cutoff
        # 2018-06-12: the 06-13 hike must not appear in its own lookback.
        # level at cutoff = 1.625 (NOT 1.875); six months earlier
        # (2017-12-12) = 1.125 -> +0.50. Were the own-day hike wrongly
        # included, the result would be 1.875 - 1.125 = 0.75.
        out = gsa.fed_net_change(self.TIMELINE, "2018-06-12", months=6)
        self.assertAlmostEqual(out["value"], 1.625 - 1.125)

    def test_decision_dated_at_cutoff_counts_same_day(self):
        # decisions publish 2 p.m. ET, before the close: same-day eligible
        out = gsa.fed_net_change(self.TIMELINE, "2018-06-13", months=6)
        self.assertAlmostEqual(out["value"], 1.875 - 1.375)

    def test_lookback_before_timeline_start_is_insufficient(self):
        # cutoff 2017-08-01 -> lookback 2017-02-01, before the first anchor:
        # the level then is UNKNOWN to the timeline -> never guessed
        out = gsa.fed_net_change(self.TIMELINE, "2017-08-01", months=6)
        self.assertIsNone(out["value"])
        self.assertEqual(out["reason"], "insufficient_history")


# ---------------------------------------------------------------------------
# 5. Missing / blocked sources are explicit, never proxied
# ---------------------------------------------------------------------------


class MissingSourceTests(unittest.TestCase):
    def _candidate(self):
        return {"candidate_id": "x-2020-01-13", "lane": "designed_contrast",
                "event_date": "2020-01-13"}

    def test_blocked_source_is_reported_not_proxied(self):
        sources = gsa.SourceBundle(
            sessions=SESSIONS, vix=_series(SESSIONS), spy=_series(SESSIONS),
            curve_2s10s=None, hy_oas=None,
            fed_timeline=FedPathTests.TIMELINE,
            blocked={"hy_oas": "source_blocked", "curve_2s10s": "source_blocked"},
        )
        row = gsa.candidate_readiness(self._candidate(), sources)
        self.assertFalse(row["dimensions"]["credit_hy_oas"]["available"])
        self.assertEqual(row["dimensions"]["credit_hy_oas"]["reason"],
                         "source_blocked")
        self.assertFalse(row["dimensions"]["curve_2s10s"]["available"])
        # no value sneaks in anywhere
        self.assertNotIn("value", json.dumps(row))


# ---------------------------------------------------------------------------
# 6. Outcome-blindness whitelist
# ---------------------------------------------------------------------------


class WhitelistTests(unittest.TestCase):
    def test_readiness_rows_carry_only_whitelisted_fields(self):
        sources = gsa.SourceBundle(
            sessions=SESSIONS, vix=_series(SESSIONS), spy=_series(SESSIONS),
            curve_2s10s=_series(SESSIONS), hy_oas=_series(SESSIONS),
            fed_timeline=FedPathTests.TIMELINE, blocked={},
        )
        row = gsa.candidate_readiness(
            {"candidate_id": "y", "lane": "frame_complete_historical",
             "event_date": "2020-01-09"}, sources)
        self.assertTrue(set(row).issubset(gsa.READINESS_FIELDS), set(row))
        dumped = json.dumps(row).lower()
        for banned in ("abnormal", "outcome", "sar", "car",
                       "raw_return", "readout", "sector_relative"):
            self.assertNotIn(banned, dumped, banned)


# ---------------------------------------------------------------------------
# 7. Authenticated HY OAS acquisition (G2C): credential handling, pinned
#    series identity, key-free cache metadata, no proxy fallback.
# ---------------------------------------------------------------------------


_FAKE_KEY = "0123456789abcdef0123456789abcdef"

_FRED_PAYLOAD = json.dumps({
    "observations": [
        {"date": "2016-05-31", "value": "6.01"},   # before substrate window
        {"date": "2023-07-04", "value": "."},      # FRED missing marker
        {"date": "2023-07-05", "value": "3.90"},
        {"date": "2023-07-06", "value": "3.86"},
    ]
}).encode("utf-8")


class HyOasCredentialTests(unittest.TestCase):
    def test_api_key_prefers_environment_over_dotenv(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            dotenv = Path(td) / ".env"
            dotenv.write_text("FRED_API_KEY=from-file\n", encoding="utf-8")
            got = gsa._fred_api_key({"FRED_API_KEY": "from-env"}, dotenv)
        self.assertEqual(got, "from-env")

    def test_api_key_falls_back_to_dotenv_line(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            dotenv = Path(td) / ".env"
            dotenv.write_text(
                "# secrets live here\nPOLYGON_API_KEY=zzz\n"
                "FRED_API_KEY= abc123 \n", encoding="utf-8")
            got = gsa._fred_api_key({}, dotenv)
        self.assertEqual(got, "abc123")

    def test_api_key_absent_returns_none(self):
        got = gsa._fred_api_key({}, Path("Z:/nonexistent/.env"))
        self.assertIsNone(got)


class HyOasRequestContractTests(unittest.TestCase):
    def test_request_url_pins_series_window_and_embeds_key(self):
        url = gsa._hy_oas_request_url(_FAKE_KEY)
        self.assertIn("api.stlouisfed.org/fred/series/observations", url)
        self.assertIn("series_id=BAMLH0A0HYM2", url)
        self.assertIn(f"observation_start={gsa.FETCH_START}", url)
        self.assertIn(f"observation_end={gsa.FETCH_END}", url)
        self.assertIn("file_type=json", url)
        self.assertIn(f"api_key={_FAKE_KEY}", url)

    def test_redacted_url_never_contains_key(self):
        url = gsa._hy_oas_request_url(_FAKE_KEY)
        redacted = gsa._redact_api_key(url)
        self.assertNotIn(_FAKE_KEY, redacted)
        self.assertIn("api_key=REDACTED", redacted)
        self.assertIn("series_id=BAMLH0A0HYM2", redacted)

    def test_parse_observations_skips_missing_markers_and_clamps_window(self):
        series = gsa._parse_fred_observations(
            json.loads(_FRED_PAYLOAD.decode("utf-8")))
        self.assertEqual(series, {"2023-07-05": 3.90, "2023-07-06": 3.86})


class HyOasFetchTests(unittest.TestCase):
    def test_fetch_meta_is_key_free_and_series_parsed(self):
        seen: list[str] = []

        def fake_get(url: str, timeout: int = 30) -> bytes:
            seen.append(url)
            return _FRED_PAYLOAD

        series, meta = gsa.fetch_hy_oas(_FAKE_KEY, getter=fake_get)
        self.assertEqual(len(seen), 1)
        self.assertIn(f"api_key={_FAKE_KEY}", seen[0])  # authenticated call
        self.assertEqual(series["2023-07-05"], 3.90)
        dumped = json.dumps(meta)
        self.assertNotIn(_FAKE_KEY, dumped)  # cache metadata stays key-free
        self.assertIn("BAMLH0A0HYM2", dumped)

    def test_fetch_without_key_never_touches_network(self):
        calls: list[str] = []

        def tripwire(url: str, timeout: int = 30) -> bytes:
            calls.append(url)
            raise AssertionError("network must not be touched without a key")

        with self.assertRaises(ValueError):
            gsa.fetch_hy_oas(None, getter=tripwire)
        self.assertEqual(calls, [])  # no unauthenticated call, no proxy

    def test_truncated_series_head_is_missing_tail_is_available(self):
        # Pins existing generic behavior against the real-world FRED
        # truncation shape: history exists only from 2023-07-04 onward, so
        # earlier cutoffs stay source_missing (never proxied) while later
        # cutoffs resolve under the next_day class.
        sessions = ["2023-07-03", "2023-07-05", "2023-07-06", "2023-07-07"]
        hy = {"2023-07-05": 3.90, "2023-07-06": 3.86}
        bundle = gsa.SourceBundle(
            sessions=SESSIONS + sessions, vix=None, spy=None,
            curve_2s10s=None, hy_oas=hy,
            fed_timeline=[("2016-12-14", 0.625)], blocked={})
        head = gsa.candidate_readiness(
            {"candidate_id": "h", "lane": "designed_contrast",
             "event_date": "2020-01-09"}, bundle)
        self.assertFalse(head["dimensions"]["credit_hy_oas"]["available"])
        self.assertEqual(head["dimensions"]["credit_hy_oas"]["reason"],
                         "source_missing")
        tail = gsa.candidate_readiness(
            {"candidate_id": "t", "lane": "designed_contrast",
             "event_date": "2023-07-07"}, bundle)
        self.assertTrue(tail["dimensions"]["credit_hy_oas"]["available"])


# ---------------------------------------------------------------------------
# 8. Deterministic candidate-ledger reconciliation (live artifacts)
# ---------------------------------------------------------------------------


@unittest.skipUnless(G1A.exists() and G1B.exists(), "G1 artifacts required")
class LedgerReconciliationTests(unittest.TestCase):
    def test_g1a_parses_to_65_candidates(self):
        rows = gsa.parse_g1a_candidates(str(G1A))
        self.assertEqual(len(rows), 65)
        self.assertTrue(all(r["lane"] == "frame_complete_historical"
                            for r in rows))

    def test_g1b_parses_to_32_reservoir_ready(self):
        rows = gsa.parse_g1b_candidates(str(G1B))
        self.assertEqual(len(rows), 32)
        self.assertTrue(all(r["lane"] == "designed_contrast" for r in rows))

    def test_total_is_97_with_unique_ids(self):
        rows = (gsa.parse_g1a_candidates(str(G1A))
                + gsa.parse_g1b_candidates(str(G1B)))
        self.assertEqual(len(rows), 97)
        self.assertEqual(len({r["candidate_id"] for r in rows}), 97)
        for r in rows:
            self.assertRegex(r["event_date"], r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
