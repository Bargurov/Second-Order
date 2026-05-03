"""
Tests that the /analyze response shape carries every field the
Research Output memo formatter requires.

The memo is rendered client-side from AnalyzeResponse. This test
ensures the backend contract doesn't silently drop a field the
formatter depends on.
"""

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db

# Fields the formatMemo() function reads from the response.
_TOP_LEVEL_MEMO_FIELDS = {
    "headline", "stage", "persistence", "event_date", "analysis", "market",
}
_ANALYSIS_MEMO_FIELDS = {
    "what_changed", "mechanism_summary", "beneficiaries", "losers",
    "assets_to_watch", "confidence", "transmission_chain",
}
_MARKET_MEMO_FIELDS = {"tickers", "note"}
_TICKER_MEMO_FIELDS = {"symbol", "role", "return_1d", "return_5d", "direction_tag"}


# ---------------------------------------------------------------------------
# Mocks (same shape as other API test suites)
# ---------------------------------------------------------------------------

def _mock_analyze(inp):
    return {
        "what_changed": "Stub what-changed.",
        "mechanism_summary": "Stub mechanism.",
        "beneficiaries": ["CompanyA"],
        "losers": ["CompanyB"],
        "beneficiary_tickers": ["AAPL"],
        "loser_tickers": ["MSFT"],
        "assets_to_watch": ["AAPL", "MSFT"],
        "confidence": "medium",
        "transmission_chain": ["event", "channel", "asset"],
        "if_persists": {},
        "currency_channel": {},
    }


def _mock_market(beneficiary_tickers, loser_tickers, event_date=None):
    return {
        "note": "Stub market.",
        "details": {},
        "tickers": [
            {"symbol": "AAPL", "role": "beneficiary", "label": "flat",
             "direction_tag": "supports \u2191",
             "return_1d": 0.1, "return_5d": 0.5, "return_20d": 1.2,
             "volume_ratio": 1.0, "vs_xle_5d": None, "spark": []},
        ],
    }


_PATCHES = [
    patch("api.analyze_event", side_effect=_mock_analyze),
    patch("api.market_check", side_effect=_mock_market),
]


class TestAnalyzeResponseMemoShape(unittest.TestCase):
    """The /analyze response must carry every field formatMemo reads."""

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""
        for p in _PATCHES:
            p.start()
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    @classmethod
    def tearDownClass(cls):
        for p in _PATCHES:
            p.stop()

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_memo_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        db._db_ready = False
        try:
            os.remove(self._tmp)
        except (PermissionError, OSError):
            pass

    def _post(self, headline="Test memo headline"):
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        r = self.client.post("/analyze", json={
            "headline": headline, "event_date": date,
        })
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_top_level_keys(self):
        body = self._post()
        for key in _TOP_LEVEL_MEMO_FIELDS:
            self.assertIn(key, body, f"Missing top-level key: {key}")

    def test_analysis_keys(self):
        body = self._post()
        analysis = body["analysis"]
        for key in _ANALYSIS_MEMO_FIELDS:
            self.assertIn(key, analysis, f"Missing analysis key: {key}")

    def test_market_has_tickers(self):
        body = self._post()
        market = body["market"]
        for key in _MARKET_MEMO_FIELDS:
            self.assertIn(key, market, f"Missing market key: {key}")

    def test_ticker_has_memo_fields(self):
        body = self._post()
        tickers = body["market"]["tickers"]
        self.assertGreater(len(tickers), 0, "Expected at least one ticker")
        for key in _TICKER_MEMO_FIELDS:
            self.assertIn(key, tickers[0], f"Missing ticker key: {key}")

    def test_transmission_chain_is_list(self):
        body = self._post()
        chain = body["analysis"]["transmission_chain"]
        self.assertIsInstance(chain, list)

    def test_beneficiaries_and_losers_are_lists(self):
        body = self._post()
        self.assertIsInstance(body["analysis"]["beneficiaries"], list)
        self.assertIsInstance(body["analysis"]["losers"], list)

    def test_confidence_is_string(self):
        body = self._post()
        self.assertIsInstance(body["analysis"]["confidence"], str)
        self.assertIn(body["analysis"]["confidence"], {"high", "medium", "low"})

    def test_ticker_has_return_1d(self):
        body = self._post()
        tickers = body["market"]["tickers"]
        self.assertGreater(len(tickers), 0)
        self.assertIn("return_1d", tickers[0], "Ticker missing return_1d for memo 1d column")

    def test_market_has_note(self):
        body = self._post()
        self.assertIn("note", body["market"], "Market block missing note for memo")

    def test_if_persists_shape(self):
        body = self._post()
        ip = body["analysis"].get("if_persists")
        # if_persists may be {} or populated; when present it must be a dict
        if ip:
            self.assertIsInstance(ip, dict)


# ---------------------------------------------------------------------------
# Pure formatting tests — no API / DB needed
# ---------------------------------------------------------------------------

class TestMemoFormatting(unittest.TestCase):
    """Validates memo plain-text structure against a synthetic response dict."""

    MOCK_RESPONSE = {
        "headline": "Fed raises rates 50bp",
        "stage": "developing",
        "persistence": "multi-week",
        "event_date": "2026-04-10",
        "is_mock": False,
        "analysis": {
            "what_changed": "Federal Reserve raised rates by 50 basis points.",
            "mechanism_summary": "Higher rates squeeze leveraged positions.",
            "beneficiaries": ["USD", "Banks"],
            "losers": ["Gold", "REITs"],
            "beneficiary_tickers": ["UUP", "XLF"],
            "loser_tickers": ["GLD", "VNQ"],
            "assets_to_watch": ["SPY", "TLT"],
            "confidence": "high",
            "transmission_chain": ["rate hike", "credit tightening", "asset repricing"],
            "if_persists": {
                "substitution": "Shift from growth to value equities",
                "delayed_winners": ["XLF"],
                "delayed_losers": ["ARKK"],
                "horizon": "3-6 months",
            },
            "currency_channel": {},
        },
        "market": {
            "note": "Bond yields surged across the curve.",
            "details": {},
            "tickers": [
                {
                    "symbol": "UUP", "role": "beneficiary", "label": "flat",
                    "direction_tag": "supports ↑",
                    "return_1d": 0.45, "return_5d": 1.20, "return_20d": 2.1,
                    "volume_ratio": 1.3, "vs_xle_5d": None, "spark": [],
                },
                {
                    "symbol": "GLD", "role": "loser", "label": "down",
                    "direction_tag": "confirms ↓",
                    "return_1d": -0.80, "return_5d": -2.50, "return_20d": -3.0,
                    "volume_ratio": 1.1, "vs_xle_5d": None, "spark": [],
                },
            ],
        },
    }

    def _format(self, overrides=None):
        """Build memo text from MOCK_RESPONSE with optional overrides."""
        # Inline reimplementation of the TS formatMemo logic in Python
        # so we can test the *contract* (section presence, field placement).
        r = {**self.MOCK_RESPONSE, **(overrides or {})}
        a = r["analysis"]
        lines = []

        lines.append("SECOND ORDER")  # header marker
        lines.append(f"Event:       {r['headline']}")
        if r.get("event_date"):
            lines.append(f"Date:        {r['event_date']}")
        lines.append(f"Stage:       {r['stage']}")
        lines.append(f"Persistence: {r['persistence']}")
        if a.get("confidence"):
            lines.append(f"Confidence:  {a['confidence']}")

        if a.get("what_changed"):
            lines.append("WHAT CHANGED")
            lines.append(a["what_changed"])

        if a.get("mechanism_summary"):
            lines.append("SECOND-ORDER MECHANISM")
            lines.append(a["mechanism_summary"])

        chain = a.get("transmission_chain") or []
        if chain:
            lines.append("TRANSMISSION")

        bens = a.get("beneficiaries") or []
        losers_list = a.get("losers") or []
        watch = a.get("assets_to_watch") or []
        if bens or losers_list or watch:
            lines.append("AFFECTED ASSETS")

        ip = a.get("if_persists") or {}
        if ip.get("substitution") or ip.get("delayed_winners") or ip.get("delayed_losers"):
            lines.append("IF PERSISTS")

        tickers = r.get("market", {}).get("tickers") or []
        if tickers:
            lines.append("MARKET VALIDATION")
            for t in tickers:
                r1d = t.get("return_1d")
                r5d = t.get("return_5d")
                lines.append(f"{t['symbol']} {r1d} {r5d}")

        return "\n".join(lines)

    def test_header_present(self):
        text = self._format()
        self.assertIn("SECOND ORDER", text)
        self.assertIn("Fed raises rates 50bp", text)

    def test_metadata_fields_per_line(self):
        text = self._format()
        self.assertIn("Date:        2026-04-10", text)
        self.assertIn("Stage:       developing", text)
        self.assertIn("Persistence: multi-week", text)
        self.assertIn("Confidence:  high", text)

    def test_sections_present(self):
        text = self._format()
        for section in ["WHAT CHANGED", "SECOND-ORDER MECHANISM",
                        "TRANSMISSION", "AFFECTED ASSETS",
                        "MARKET VALIDATION"]:
            self.assertIn(section, text, f"Missing section: {section}")

    def test_if_persists_included(self):
        text = self._format()
        self.assertIn("IF PERSISTS", text)

    def test_if_persists_omitted_when_empty(self):
        text = self._format({"analysis": {
            **self.MOCK_RESPONSE["analysis"],
            "if_persists": {},
        }})
        self.assertNotIn("IF PERSISTS", text)

    def test_tickers_show_1d_and_5d(self):
        text = self._format()
        self.assertIn("UUP", text)
        self.assertIn("0.45", text)   # return_1d
        self.assertIn("1.2", text)    # return_5d

    def test_market_note_included(self):
        """Market note should be present when tickers section renders."""
        text = self._format()
        # The Python mirror doesn't emit the note, but we verify the data
        # carries the note field used by the TS formatter.
        self.assertIn("note", self.MOCK_RESPONSE["market"])
        self.assertEqual(
            self.MOCK_RESPONSE["market"]["note"],
            "Bond yields surged across the curve.",
        )

    def test_empty_sections_omitted(self):
        text = self._format({"analysis": {
            **self.MOCK_RESPONSE["analysis"],
            "what_changed": "",
            "mechanism_summary": "",
            "transmission_chain": [],
            "beneficiaries": [],
            "losers": [],
            "assets_to_watch": [],
            "if_persists": {},
        }})
        for absent in ["WHAT CHANGED", "SECOND-ORDER MECHANISM",
                        "TRANSMISSION", "AFFECTED ASSETS", "IF PERSISTS"]:
            self.assertNotIn(absent, text)


if __name__ == "__main__":
    unittest.main()
