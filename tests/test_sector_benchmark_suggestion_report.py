"""Tests for ``scripts/sector_benchmark_suggestion_report.py``.

Pin the contract:

* The report builds on
  :func:`scripts.manual_ticker_repair_packet.summarize_repair_packet`
  through the patchable seam ``_run_repair_packet`` so unit tests can
  drive it with synthetic packet payloads.  No real DB is touched.
* Output JSON has these top-level keys:
  ``ok``, ``candidate_count``, ``suggestions``, ``confidence``,
  ``needs_manual_review``, ``recommended_next_action``.
* Each per-row suggestion carries:
  ``event_id``, ``headline``, ``event_date``,
  ``current_primary_ticker``, ``manual_review_priority``, ``flags``,
  ``suggested_sector``, ``suggested_benchmark``, ``confidence``,
  ``rationale``, ``needs_manual_review``.
* ``suggested_benchmark`` is ALWAYS one of the conservative ETF set
  ``{XLE, XLF, XLK, XLI, XLB, XLV, XLRE, XLY, XLU, SPY}`` — the
  closed set is the report's only judgement axis.
* ``suggested_sector`` is ALWAYS one of
  ``{energy, financials, tech, industrials, materials, healthcare,
  real_estate, consumer_discretionary, utilities, broad}``.
* ``confidence`` is ALWAYS one of ``{high, medium, low, none}``.
* When the classifier cannot place the candidate confidently, the
  fallback is ``broad``/``SPY`` with ``confidence="none"`` and
  per-row ``needs_manual_review=true`` — the report never invents a
  sector it isn't sure about.
* ``high`` confidence is reserved for direct ticker matches against
  a small known-sector universe; ``medium`` for headline keyword
  matches; ``low`` for ambiguous (multiple competing keyword hits);
  ``none`` for no match at all.
* Suggestions are SUGGESTIONS, not corrections — the report never
  writes to the archive and never claims the operator's primary
  ticker is wrong.  Conservative wording: banned tokens include
  ``delete``, ``auto-correct``, ``auto fix``, ``automatic``,
  ``assign``, ``fix the``, ``propose``, ``replace``, ``correct``.
* Read-only: default run does not import yfinance / market_check /
  market_data / price_cache / api / fastapi / routes.*.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from io import StringIO
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import sector_benchmark_suggestion_report as cli  # noqa: E402


_SUGGESTION_KEYS = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "manual_review_priority",
    "flags",
    "suggested_sector",
    "suggested_benchmark",
    "confidence",
    "rationale",
    "needs_manual_review",
)


_ALLOWED_BENCHMARKS = frozenset({
    "XLE", "XLF", "XLK", "XLI", "XLB", "XLV", "XLRE", "XLY", "XLU", "SPY",
})


_ALLOWED_SECTORS = frozenset({
    "energy", "financials", "tech", "industrials", "materials",
    "healthcare", "real_estate", "consumer_discretionary", "utilities",
    "broad",
})


_ALLOWED_CONFIDENCE = frozenset({"high", "medium", "low", "none"})


_BANNED_WORDS = (
    "delete",
    "auto-correct",
    "auto fix",
    "automatic",
    "assign",
    "fix the",
    "propose",
    "replace",
    "correct",
)


# ---------------------------------------------------------------------------
# Synthetic packet payloads
# ---------------------------------------------------------------------------


def _packet_candidate(
    *,
    event_id: int,
    headline: str | None = "Some headline",
    event_date: str | None = "2026-04-01",
    current_primary_ticker: str | None = "AAPL",
    manual_review_priority: str = "medium",
    flags: list[str] | None = None,
    reason: str = "contaminated_fully_ready",
    fast_to_clean_score: int = 5,
    fast_to_clean_reason: str = "has_event_date|plausible_headline",
) -> dict:
    return {
        "event_id":                  event_id,
        "headline":                  headline,
        "event_date":                event_date,
        "current_primary_ticker":    current_primary_ticker,
        "flags":                     flags if flags is not None else ["driv_lit_off_topic"],
        "reason":                    reason,
        "manual_review_priority":    manual_review_priority,
        "fast_to_clean_score":       fast_to_clean_score,
        "fast_to_clean_reason":      fast_to_clean_reason,
        "proposed_primary_ticker":   "",
        "proposed_benchmark":        "",
        "proposed_mechanism_family": "",
        "ticker_rationale":          "",
        "exclude_reason":            "",
    }


def _packet_payload(candidates: list[dict]) -> dict:
    return {
        "ok":                          True,
        "priority_filter":             "all",
        "total_candidates_in_filter":  len(candidates),
        "candidates":                  list(candidates),
        "recommended_next_action":     "synthetic",
    }


def _patch_seam(*, packet: dict):
    return patch.object(cli, "_run_repair_packet", return_value=packet)


def _run(*, packet: dict | None = None, **kwargs) -> dict:
    packet = packet if packet is not None else _packet_payload([])
    with _patch_seam(packet=packet):
        return cli.summarize_sector_benchmark_suggestions(**kwargs)


def _run_cli(argv: list[str], *, packet: dict | None = None) -> tuple[int, str]:
    packet = packet if packet is not None else _packet_payload([])
    out = StringIO()
    with _patch_seam(packet=packet):
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Top-level output contract
# ---------------------------------------------------------------------------


class TestTopLevelContract(unittest.TestCase):
    def test_top_level_keys_pinned(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM"),
            ]),
        )
        for k in (
            "ok",
            "candidate_count",
            "suggestions",
            "confidence",
            "needs_manual_review",
            "recommended_next_action",
        ):
            self.assertIn(k, result, f"missing top-level key {k!r}")

    def test_ok_is_true(self) -> None:
        result = _run(packet=_packet_payload([]))
        self.assertTrue(result["ok"])

    def test_candidate_count_reflects_full_packet(self) -> None:
        # candidate_count counts every shortlisted row from the upstream
        # packet, NOT just the truncated suggestions list.
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=i, current_primary_ticker="XOM")
                for i in range(1, 11)
            ]),
            limit=3,
        )
        self.assertEqual(result["candidate_count"], 10)
        self.assertEqual(len(result["suggestions"]), 3)

    def test_confidence_aggregate_is_dict_of_ints(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM"),
            ]),
        )
        agg = result["confidence"]
        self.assertIsInstance(agg, dict)
        for k in ("high", "medium", "low", "none"):
            self.assertIn(k, agg)
            self.assertIsInstance(agg[k], int)

    def test_needs_manual_review_top_level_is_int_count(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM"),
                _packet_candidate(event_id=2, current_primary_ticker=None,
                                  headline=None),
            ]),
        )
        self.assertIsInstance(result["needs_manual_review"], int)
        self.assertGreaterEqual(result["needs_manual_review"], 0)


# ---------------------------------------------------------------------------
# Per-row suggestion contract
# ---------------------------------------------------------------------------


class TestPerRowContract(unittest.TestCase):
    def test_each_row_has_pinned_keys(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM"),
                _packet_candidate(event_id=2, current_primary_ticker="AAPL"),
            ]),
        )
        self.assertGreater(len(result["suggestions"]), 0)
        for entry in result["suggestions"]:
            self.assertEqual(set(entry.keys()), set(_SUGGESTION_KEYS),
                             f"unexpected keys: {entry.keys()!r}")

    def test_event_date_passes_through(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM",
                                  event_date="2026-03-01"),
            ]),
        )
        self.assertEqual(result["suggestions"][0]["event_date"], "2026-03-01")

    def test_event_date_none_passes_through(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM",
                                  event_date=None),
            ]),
        )
        self.assertIsNone(result["suggestions"][0]["event_date"])

    def test_flags_pass_through(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM",
                                  flags=["driv_lit_off_topic", "duplicate_date_ticker"]),
            ]),
        )
        self.assertEqual(
            result["suggestions"][0]["flags"],
            ["driv_lit_off_topic", "duplicate_date_ticker"],
        )

    def test_manual_review_priority_passes_through(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM",
                                  manual_review_priority="high"),
            ]),
        )
        self.assertEqual(result["suggestions"][0]["manual_review_priority"], "high")


# ---------------------------------------------------------------------------
# Closed set: benchmarks, sectors, confidence values
# ---------------------------------------------------------------------------


class TestClosedSets(unittest.TestCase):
    """Most important defensive test — the conservative ETF map is the
    *only* valid output universe.  Any drift toward arbitrary tickers
    must break a test.
    """
    def test_suggested_benchmark_is_in_allowed_set(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM"),
                _packet_candidate(event_id=2, current_primary_ticker="JPM"),
                _packet_candidate(event_id=3, current_primary_ticker="AAPL"),
                _packet_candidate(event_id=4, current_primary_ticker=None,
                                  headline=None),
                _packet_candidate(event_id=5, current_primary_ticker="UNKNOWN1",
                                  headline="some unrelated text"),
            ]),
        )
        for entry in result["suggestions"]:
            self.assertIn(entry["suggested_benchmark"], _ALLOWED_BENCHMARKS,
                          f"benchmark {entry['suggested_benchmark']!r} "
                          f"not in conservative set")

    def test_suggested_sector_is_in_allowed_set(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM"),
                _packet_candidate(event_id=2, current_primary_ticker=None,
                                  headline=None),
            ]),
        )
        for entry in result["suggestions"]:
            self.assertIn(entry["suggested_sector"], _ALLOWED_SECTORS)

    def test_confidence_is_in_allowed_set(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM"),
                _packet_candidate(event_id=2, current_primary_ticker=None,
                                  headline=None),
                _packet_candidate(event_id=3, current_primary_ticker=None,
                                  headline="oil prices surge"),
            ]),
        )
        for entry in result["suggestions"]:
            self.assertIn(entry["confidence"], _ALLOWED_CONFIDENCE)

    def test_broad_sector_maps_to_spy(self) -> None:
        # Whenever the suggested_sector is "broad", suggested_benchmark
        # must be SPY — the broad-market fallback is the only path that
        # reaches the SPY symbol.
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker=None,
                                  headline=None),
            ]),
        )
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "broad")
        self.assertEqual(entry["suggested_benchmark"], "SPY")


# ---------------------------------------------------------------------------
# Classifier behavior — ticker matches, headline keywords, fallbacks
# ---------------------------------------------------------------------------


class TestTickerClassifier(unittest.TestCase):
    """High-confidence direct ticker matches against the conservative
    sector universe.
    """
    def test_xom_classifies_as_energy(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(event_id=1, current_primary_ticker="XOM"),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "energy")
        self.assertEqual(entry["suggested_benchmark"], "XLE")
        self.assertEqual(entry["confidence"], "high")

    def test_jpm_classifies_as_financials(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(event_id=1, current_primary_ticker="JPM"),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "financials")
        self.assertEqual(entry["suggested_benchmark"], "XLF")
        self.assertEqual(entry["confidence"], "high")

    def test_msft_classifies_as_tech(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(event_id=1, current_primary_ticker="MSFT"),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "tech")
        self.assertEqual(entry["suggested_benchmark"], "XLK")
        self.assertEqual(entry["confidence"], "high")

    def test_jnj_classifies_as_healthcare(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(event_id=1, current_primary_ticker="JNJ"),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "healthcare")
        self.assertEqual(entry["suggested_benchmark"], "XLV")
        self.assertEqual(entry["confidence"], "high")

    def test_etf_self_classifies(self) -> None:
        # The sector ETF itself should be classified into its own sector
        # (e.g., XLE → energy).
        for ticker, sector, etf in (
            ("XLE", "energy", "XLE"),
            ("XLF", "financials", "XLF"),
            ("XLK", "tech", "XLK"),
            ("XLI", "industrials", "XLI"),
            ("XLB", "materials", "XLB"),
            ("XLV", "healthcare", "XLV"),
            ("XLRE", "real_estate", "XLRE"),
            ("XLY", "consumer_discretionary", "XLY"),
            ("XLU", "utilities", "XLU"),
        ):
            result = _run(packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker=ticker),
            ]))
            entry = result["suggestions"][0]
            self.assertEqual(entry["suggested_sector"], sector,
                             f"{ticker} should classify as {sector}")
            self.assertEqual(entry["suggested_benchmark"], etf)


class TestHeadlineKeywordClassifier(unittest.TestCase):
    """Medium-confidence headline keyword matches when the ticker is
    unknown / missing.
    """
    def test_oil_headline_with_unknown_ticker_classifies_as_energy(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(
                event_id=1,
                current_primary_ticker=None,
                headline="OPEC announces fresh crude oil production cuts",
            ),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "energy")
        self.assertEqual(entry["suggested_benchmark"], "XLE")
        self.assertEqual(entry["confidence"], "medium")

    def test_bank_headline_classifies_as_financials(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(
                event_id=1,
                current_primary_ticker=None,
                headline="Regional bank reports loan loss provisions surge",
            ),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "financials")
        self.assertEqual(entry["confidence"], "medium")

    def test_pharma_headline_classifies_as_healthcare(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(
                event_id=1,
                current_primary_ticker=None,
                headline="Pharma trial data reads out for new diabetes drug",
            ),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "healthcare")
        self.assertEqual(entry["confidence"], "medium")

    def test_ticker_takes_precedence_over_headline(self) -> None:
        # Known ticker (energy: XOM) wins even if headline mentions a
        # different sector.  The ticker is concrete; the headline is
        # weaker evidence.
        result = _run(packet=_packet_payload([
            _packet_candidate(
                event_id=1,
                current_primary_ticker="XOM",
                headline="bank quarterly results beat estimates",
            ),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "energy")
        self.assertEqual(entry["confidence"], "high")


class TestAmbiguityFallback(unittest.TestCase):
    def test_ambiguous_headline_with_two_sector_hints_falls_back(self) -> None:
        # Headline has both "oil" (energy) and "bank" (financials) hints
        # AND no known ticker.  The classifier cannot choose; fallback
        # to broad/SPY at low confidence with manual_review flagged.
        result = _run(packet=_packet_payload([
            _packet_candidate(
                event_id=1,
                current_primary_ticker=None,
                headline="oil bank consortium issues joint statement",
            ),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "broad")
        self.assertEqual(entry["suggested_benchmark"], "SPY")
        self.assertIn(entry["confidence"], ("low", "none"))
        self.assertTrue(entry["needs_manual_review"])

    def test_no_match_falls_back_to_broad_none_manual_review(self) -> None:
        # No ticker, no recognisable keyword → broad/SPY/none/manual.
        result = _run(packet=_packet_payload([
            _packet_candidate(
                event_id=1,
                current_primary_ticker=None,
                headline="quiet trading session ahead of holiday weekend",
            ),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "broad")
        self.assertEqual(entry["suggested_benchmark"], "SPY")
        self.assertEqual(entry["confidence"], "none")
        self.assertTrue(entry["needs_manual_review"])

    def test_no_ticker_no_headline_falls_back(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(
                event_id=1, current_primary_ticker=None, headline=None,
            ),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "broad")
        self.assertEqual(entry["confidence"], "none")
        self.assertTrue(entry["needs_manual_review"])

    def test_unknown_ticker_with_relevant_headline_uses_keyword(self) -> None:
        # Unknown ticker but headline carries a clear single-sector hint
        # → fall through ticker step, classify on headline (medium).
        result = _run(packet=_packet_payload([
            _packet_candidate(
                event_id=1,
                current_primary_ticker="UNKNOWN1",
                headline="OPEC announces fresh crude oil production cuts",
            ),
        ]))
        entry = result["suggestions"][0]
        self.assertEqual(entry["suggested_sector"], "energy")
        self.assertEqual(entry["confidence"], "medium")


class TestNeedsManualReview(unittest.TestCase):
    def test_high_confidence_does_not_need_manual_review(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(event_id=1, current_primary_ticker="XOM"),
        ]))
        self.assertFalse(result["suggestions"][0]["needs_manual_review"])

    def test_medium_confidence_does_not_need_manual_review(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(
                event_id=1, current_primary_ticker=None,
                headline="OPEC announces crude oil production cuts",
            ),
        ]))
        self.assertFalse(result["suggestions"][0]["needs_manual_review"])

    def test_none_confidence_needs_manual_review(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(
                event_id=1, current_primary_ticker=None, headline=None,
            ),
        ]))
        self.assertTrue(result["suggestions"][0]["needs_manual_review"])

    def test_top_level_needs_manual_review_count_matches_per_row(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(event_id=1, current_primary_ticker="XOM"),  # high
            _packet_candidate(event_id=2, current_primary_ticker=None,
                              headline=None),                              # none
            _packet_candidate(event_id=3, current_primary_ticker=None,
                              headline=None),                              # none
        ]))
        per_row = sum(1 for e in result["suggestions"] if e["needs_manual_review"])
        self.assertEqual(result["needs_manual_review"], per_row)
        self.assertEqual(result["needs_manual_review"], 2)


# ---------------------------------------------------------------------------
# Conservative wording — banned tokens absent from rationale + recommendation
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_recommended_action_avoids_banned_words(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(event_id=1, current_primary_ticker="XOM"),
        ]))
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec, f"banned word {w!r} in: {rec!r}")

    def test_empty_recommendation_avoids_banned_words(self) -> None:
        result = _run(packet=_packet_payload([]))
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec, f"banned word {w!r} in: {rec!r}")

    def test_rationale_is_banned_word_free_across_paths(self) -> None:
        scenarios = [
            _packet_candidate(event_id=1, current_primary_ticker="XOM"),
            _packet_candidate(event_id=2, current_primary_ticker="JPM"),
            _packet_candidate(event_id=3, current_primary_ticker=None,
                              headline="OPEC announces fresh crude oil cuts"),
            _packet_candidate(event_id=4, current_primary_ticker=None,
                              headline=None),
            _packet_candidate(event_id=5, current_primary_ticker="UNKNOWN9",
                              headline="oil bank consortium issues joint statement"),
            _packet_candidate(event_id=6, current_primary_ticker="XLE"),
            _packet_candidate(event_id=7, current_primary_ticker="UNKNOWN9",
                              headline="some completely unrelated headline"),
        ]
        result = _run(packet=_packet_payload(scenarios))
        for entry in result["suggestions"]:
            rationale = entry["rationale"].lower()
            for w in _BANNED_WORDS:
                self.assertNotIn(w, rationale,
                                 f"rationale {rationale!r} contains banned {w!r}")

    def test_rationale_is_string(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(event_id=1, current_primary_ticker="XOM"),
        ]))
        rationale = result["suggestions"][0]["rationale"]
        self.assertIsInstance(rationale, str)
        self.assertGreater(len(rationale), 0)


# ---------------------------------------------------------------------------
# Limit truncation
# ---------------------------------------------------------------------------


class TestLimitTruncation(unittest.TestCase):
    def test_limit_truncates_suggestions_only(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=i, current_primary_ticker="XOM")
                for i in range(1, 11)
            ]),
            limit=4,
        )
        self.assertEqual(len(result["suggestions"]), 4)
        self.assertEqual(result["candidate_count"], 10)

    def test_limit_zero_yields_empty_suggestions(self) -> None:
        result = _run(
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM"),
            ]),
            limit=0,
        )
        self.assertEqual(result["suggestions"], [])
        self.assertEqual(result["candidate_count"], 1)


# ---------------------------------------------------------------------------
# Patchable seam
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_run_repair_packet_seam_exists(self) -> None:
        self.assertTrue(callable(getattr(cli, "_run_repair_packet")))

    def test_seam_called_with_db_path(self) -> None:
        captured: dict = {}

        def fake_packet(*, db_path):
            captured["db_path"] = db_path
            return _packet_payload([])

        with patch.object(cli, "_run_repair_packet", side_effect=fake_packet):
            cli.summarize_sector_benchmark_suggestions(db_path="/sentinel/path.db")
        self.assertEqual(captured.get("db_path"), "/sentinel/path.db")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_flag_emits_parsable_json(self) -> None:
        rc, output = _run_cli(
            ["--json", "--limit", "20"],
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM"),
            ]),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertIn("suggestions", parsed)
        self.assertEqual(parsed["candidate_count"], 1)
        self.assertEqual(parsed["suggestions"][0]["event_id"], 1)
        self.assertEqual(parsed["suggestions"][0]["suggested_benchmark"], "XLE")

    def test_default_text_run_does_not_raise(self) -> None:
        rc, output = _run_cli(
            [],
            packet=_packet_payload([
                _packet_candidate(event_id=1, current_primary_ticker="XOM"),
            ]),
        )
        self.assertEqual(rc, 0)
        lower = output.lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, lower,
                             f"text rendering used banned word {w!r}")

    def test_db_path_flag_threads_through(self) -> None:
        captured: dict = {}

        def fake_packet(*, db_path):
            captured["db_path"] = db_path
            return _packet_payload([])

        out = StringIO()
        with patch.object(cli, "_run_repair_packet", side_effect=fake_packet):
            try:
                rc = cli.main(["--json", "--db-path", "/sentinel/path.db"], out=out)
            except SystemExit as exc:
                rc = exc.code
        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("db_path"), "/sentinel/path.db")


# ---------------------------------------------------------------------------
# Read-only / import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED_MODULES = (
        "yfinance",
        "market_check",
        "market_data",
        "price_cache",
        "api",
        "fastapi",
    )

    def test_default_run_does_not_import_provider_or_fastapi(self) -> None:
        before = {k for k in sys.modules.keys()
                  if k in self._BLOCKED_MODULES
                  or k.startswith("routes.")
                  or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        with patch.object(cli, "_run_repair_packet",
                          return_value=_packet_payload([])):
            cli.summarize_sector_benchmark_suggestions()
        after = {k for k in sys.modules.keys()
                 if k in self._BLOCKED_MODULES
                 or k.startswith("routes.")
                 or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)}
        self.assertEqual(after - before, set(),
                         "default run imported a forbidden module")


# ---------------------------------------------------------------------------
# Confidence aggregate accuracy
# ---------------------------------------------------------------------------


class TestConfidenceAggregate(unittest.TestCase):
    def test_aggregate_counts_match_per_row(self) -> None:
        result = _run(packet=_packet_payload([
            _packet_candidate(event_id=1, current_primary_ticker="XOM"),       # high
            _packet_candidate(event_id=2, current_primary_ticker="JPM"),       # high
            _packet_candidate(event_id=3, current_primary_ticker=None,
                              headline="OPEC oil supply shock hits market"),   # medium
            _packet_candidate(event_id=4, current_primary_ticker=None,
                              headline=None),                                    # none
        ]))
        agg = result["confidence"]
        per_row_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0, "none": 0}
        for e in result["suggestions"]:
            per_row_counts[e["confidence"]] = per_row_counts.get(e["confidence"], 0) + 1
        self.assertEqual(agg, per_row_counts)
        self.assertEqual(agg["high"], 2)
        self.assertEqual(agg["medium"], 1)
        self.assertEqual(agg["none"], 1)


if __name__ == "__main__":
    unittest.main()
