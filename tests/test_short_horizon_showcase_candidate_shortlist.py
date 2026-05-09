"""Tests for ``scripts/short_horizon_showcase_candidate_shortlist.py``.

Pin the contract:

* Two patchable seams compose the shortlist:

  - ``_run_archive_stat_validation_short_horizon`` — short-horizon
    (1d / 5d) per-event-per-horizon stat-validation payload
    (``records_count``, ``examples``).
  - ``_run_short_horizon_contamination_report`` — short-horizon
    contamination payload (``examples`` of contaminated event_ids).

  Both seams are lazy-imported in the script body so unit tests can
  patch the module attributes directly with synthetic fixtures.
  This test suite NEVER resolves the un-patched path — the upstream
  modules may not exist yet.

* Top-level keys: ``ok``, ``candidate_count``, ``candidates``,
  ``excluded_contaminated_count``, ``top_abs_sar``,
  ``recommended_next_action``.
* Per-candidate keys (exactly nine): ``event_id``, ``headline``,
  ``ticker``, ``horizon``, ``sar``, ``p_value``, ``fdr_q``,
  ``reason``, ``showcase_score``.
* Restrict to horizons in ``{1, 5}``; any other horizon is ignored
  defensively even if upstream leaks it.
* Per-event aggregation picks the horizon with the largest absolute
  ``sar`` as the representative; ``p_value`` / ``fdr_q`` /
  ``interpretation`` are carried forward from that representative
  record.
* ``showcase_score = round(|sar| + (0.5 if any_significant else 0.0),
  4)``.
* Sort: ``showcase_score`` descending, ``event_id`` ascending tiebreak.
* ``excluded_contaminated_count`` counts only contaminated event_ids
  that ALSO appear in the archive records — not the full
  contamination set.
* ``top_abs_sar`` is the maximum ``|sar|`` across every candidate, or
  ``None`` when the candidate list is empty.
* Conservative wording: ``"candidate"``, ``"short-horizon evidence"``,
  ``"manual review required"``; banned tokens include ``delete``,
  ``fix the``, ``automatic``, ``assign``, ``propose``, ``replace``,
  ``correct``, ``auto-correct``, ``auto fix``.
* Read-only: default-path import isolation — the patched (default)
  path must not import yfinance / market_check / market_data /
  price_cache / api / fastapi / routes.*.
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

from scripts import short_horizon_showcase_candidate_shortlist as cli  # noqa: E402


_CANDIDATE_KEYS = (
    "event_id",
    "headline",
    "ticker",
    "horizon",
    "sar",
    "p_value",
    "fdr_q",
    "reason",
    "showcase_score",
)


_TOP_LEVEL_KEYS = (
    "ok",
    "candidate_count",
    "candidates",
    "excluded_contaminated_count",
    "top_abs_sar",
    "recommended_next_action",
)


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
# Synthetic upstream payload helpers
# ---------------------------------------------------------------------------


def _record(
    *, event_id: int, horizon: int, sar: float | None,
    headline: str | None = "Sample headline for event",
    ticker: str | None = "AAPL",
    p_value: float | None = 0.05, fdr_q: float | None = 0.10,
    interpretation: str = "not_significant",
) -> dict[str, Any]:
    return {
        "event_id":       event_id,
        "headline":       headline,
        "ticker":         ticker,
        "horizon":        horizon,
        "sar":            sar,
        "p_value":        p_value,
        "fdr_q":          fdr_q,
        "interpretation": interpretation,
    }


def _archive_payload(records: list[dict]) -> dict[str, Any]:
    return {
        "records_count": len(records),
        "examples":      list(records),
    }


def _contam_payload(event_ids: list[int]) -> dict[str, Any]:
    return {
        "examples": [
            {"event_id": int(i)} for i in event_ids
            if isinstance(i, int)
        ],
    }


def _patch_seams(*, archive: dict, contamination: dict | None = None):
    contamination = contamination if contamination is not None \
        else _contam_payload([])
    return (
        patch.object(
            cli, "_run_archive_stat_validation_short_horizon",
            return_value=archive,
        ),
        patch.object(
            cli, "_run_short_horizon_contamination_report",
            return_value=contamination,
        ),
    )


def _run(
    *, archive: dict | None = None,
    contamination: dict | None = None,
    **kwargs,
) -> dict:
    archive = archive if archive is not None else _archive_payload([])
    p1, p2 = _patch_seams(archive=archive, contamination=contamination)
    with p1, p2:
        return cli.summarize_short_horizon_showcase(**kwargs)


def _run_cli(
    argv: list[str],
    *, archive: dict | None = None,
    contamination: dict | None = None,
) -> tuple[int, str]:
    archive = archive if archive is not None else _archive_payload([])
    out = StringIO()
    p1, p2 = _patch_seams(archive=archive, contamination=contamination)
    with p1, p2:
        try:
            rc = cli.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
    return rc, out.getvalue()


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------


class TestTopLevelShape(unittest.TestCase):
    def test_top_level_keys_present_when_empty(self) -> None:
        result = _run()
        for k in _TOP_LEVEL_KEYS:
            self.assertIn(k, result, f"missing top-level key {k!r}")

    def test_ok_flag_is_true(self) -> None:
        result = _run()
        self.assertIs(result["ok"], True)

    def test_candidate_count_zero_when_no_records(self) -> None:
        result = _run()
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["candidates"], [])
        self.assertIsNone(result["top_abs_sar"])

    def test_excluded_contaminated_count_zero_when_no_overlap(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=1.5),
            ]),
            contamination=_contam_payload([99]),  # no overlap
        )
        self.assertEqual(result["excluded_contaminated_count"], 0)


# ---------------------------------------------------------------------------
# Per-candidate contract
# ---------------------------------------------------------------------------


class TestCandidateContract(unittest.TestCase):
    def test_each_candidate_has_exactly_nine_keys(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=2.0),
                _record(event_id=2, horizon=5, sar=-1.5),
            ]),
        )
        self.assertEqual(len(result["candidates"]), 2)
        for c in result["candidates"]:
            self.assertEqual(set(c.keys()), set(_CANDIDATE_KEYS),
                             f"unexpected keys: {c.keys()!r}")

    def test_horizon_1d_carries_through(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=2.5),
            ]),
        )
        self.assertEqual(result["candidates"][0]["horizon"], 1)

    def test_horizon_5d_carries_through(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=5, sar=2.5),
            ]),
        )
        self.assertEqual(result["candidates"][0]["horizon"], 5)

    def test_headline_and_ticker_carry_through(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=1.0,
                        headline="Real-looking headline", ticker="JPM"),
            ]),
        )
        c = result["candidates"][0]
        self.assertEqual(c["headline"], "Real-looking headline")
        self.assertEqual(c["ticker"], "JPM")

    def test_p_value_and_fdr_q_carry_through(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=1.0,
                        p_value=0.012, fdr_q=0.034),
            ]),
        )
        c = result["candidates"][0]
        self.assertEqual(c["p_value"], 0.012)
        self.assertEqual(c["fdr_q"], 0.034)


# ---------------------------------------------------------------------------
# Horizon restriction
# ---------------------------------------------------------------------------


class TestHorizonRestriction(unittest.TestCase):
    def test_horizon_20_records_are_ignored(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=20, sar=5.0),  # filtered out
                _record(event_id=2, horizon=1, sar=1.0),
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [2])

    def test_event_with_only_horizon_20_records_excluded(self) -> None:
        # An event where every record is horizon=20 must NOT appear as
        # a candidate, even if its |sar| would otherwise dominate.
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=20, sar=10.0),
            ]),
        )
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["candidate_count"], 0)


# ---------------------------------------------------------------------------
# Per-event aggregation
# ---------------------------------------------------------------------------


class TestPerEventAggregation(unittest.TestCase):
    def test_representative_horizon_is_max_abs_sar(self) -> None:
        # event 1: 1d sar=0.5, 5d sar=-2.0 → 5d is representative.
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=0.5,
                        p_value=0.40, fdr_q=0.50),
                _record(event_id=1, horizon=5, sar=-2.0,
                        p_value=0.01, fdr_q=0.02),
            ]),
        )
        c = result["candidates"][0]
        self.assertEqual(c["horizon"], 5)
        self.assertEqual(c["sar"], -2.0)
        self.assertEqual(c["p_value"], 0.01)
        self.assertEqual(c["fdr_q"], 0.02)

    def test_aggregation_skips_records_with_none_sar(self) -> None:
        # Only one record has a usable sar; that one wins.
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=None),
                _record(event_id=1, horizon=5, sar=1.7),
            ]),
        )
        c = result["candidates"][0]
        self.assertEqual(c["horizon"], 5)
        self.assertEqual(c["sar"], 1.7)

    def test_event_with_only_none_sar_records_excluded(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=None),
                _record(event_id=1, horizon=5, sar=None),
            ]),
        )
        self.assertEqual(result["candidates"], [])


# ---------------------------------------------------------------------------
# Contamination exclusion
# ---------------------------------------------------------------------------


class TestContaminationExclusion(unittest.TestCase):
    def test_contaminated_event_excluded_from_candidates(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=2.0),
                _record(event_id=2, horizon=1, sar=1.0),
            ]),
            contamination=_contam_payload([1]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [2])

    def test_excluded_contaminated_count_counts_only_present_overlap(self) -> None:
        # Contamination set contains 4 ids, but only 2 of them have
        # archive records — the count must reflect the overlap, not
        # the full contamination set.
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=1.0),
                _record(event_id=2, horizon=5, sar=1.0),
            ]),
            contamination=_contam_payload([1, 2, 99, 100]),
        )
        self.assertEqual(result["excluded_contaminated_count"], 2)
        self.assertEqual(result["candidates"], [])

    def test_contaminated_event_with_multiple_horizons_counted_once(self) -> None:
        # An event with multiple horizon records but a single contam
        # entry should increment the count by exactly one.
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=1.0),
                _record(event_id=1, horizon=5, sar=2.0),
                _record(event_id=2, horizon=1, sar=0.5),
            ]),
            contamination=_contam_payload([1]),
        )
        self.assertEqual(result["excluded_contaminated_count"], 1)


# ---------------------------------------------------------------------------
# showcase_score
# ---------------------------------------------------------------------------


class TestShowcaseScore(unittest.TestCase):
    def test_score_equals_abs_sar_when_not_significant(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=-2.4321,
                        interpretation="not_significant"),
            ]),
        )
        self.assertEqual(result["candidates"][0]["showcase_score"], 2.4321)

    def test_score_adds_significance_bonus(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=2.0,
                        interpretation="significant"),
            ]),
        )
        self.assertEqual(result["candidates"][0]["showcase_score"], 2.5)

    def test_score_rounded_to_four_decimals(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=1.123456789,
                        interpretation="not_significant"),
            ]),
        )
        self.assertEqual(result["candidates"][0]["showcase_score"], 1.1235)

    def test_top_abs_sar_reflects_max_across_candidates(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=0.5),
                _record(event_id=2, horizon=5, sar=-3.0),
                _record(event_id=3, horizon=1, sar=1.2),
            ]),
        )
        self.assertEqual(result["top_abs_sar"], 3.0)


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


class TestSortOrder(unittest.TestCase):
    def test_sort_by_score_desc_then_event_id_asc(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=5, horizon=1, sar=1.0,
                        interpretation="not_significant"),  # 1.0
                _record(event_id=2, horizon=5, sar=-2.0,
                        interpretation="not_significant"),  # 2.0
                _record(event_id=4, horizon=1, sar=1.0,
                        interpretation="not_significant"),  # 1.0
                _record(event_id=1, horizon=5, sar=3.0,
                        interpretation="significant"),       # 3.5
                _record(event_id=3, horizon=1, sar=1.0,
                        interpretation="not_significant"),  # 1.0
            ]),
        )
        ids = [c["event_id"] for c in result["candidates"]]
        self.assertEqual(ids, [1, 2, 3, 4, 5])

        scores = [c["showcase_score"] for c in result["candidates"]]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])


# ---------------------------------------------------------------------------
# Limit truncation
# ---------------------------------------------------------------------------


class TestLimitTruncation(unittest.TestCase):
    def test_limit_truncates_candidates_only(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=i, horizon=1, sar=float(i))
                for i in range(1, 11)
            ]),
            limit=3,
        )
        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(result["candidate_count"], 10)


# ---------------------------------------------------------------------------
# Conservative wording
# ---------------------------------------------------------------------------


class TestConservativeWording(unittest.TestCase):
    def test_recommendation_avoids_banned_words_when_empty(self) -> None:
        result = _run()
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec, f"banned word {w!r} in {rec!r}")

    def test_recommendation_avoids_banned_words_when_populated(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=2.0),
            ]),
        )
        rec = result["recommended_next_action"].lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, rec, f"banned word {w!r} in {rec!r}")

    def test_recommendation_mentions_short_horizon_evidence_when_populated(
        self,
    ) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=2.0),
            ]),
        )
        self.assertIn("short-horizon evidence",
                      result["recommended_next_action"].lower())

    def test_recommendation_mentions_manual_review_when_all_contaminated(
        self,
    ) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=2.0),
            ]),
            contamination=_contam_payload([1]),
        )
        rec = result["recommended_next_action"].lower()
        self.assertIn("manual review required", rec)

    def test_reason_avoids_banned_words(self) -> None:
        result = _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=2.0,
                        interpretation="significant"),
                _record(event_id=2, horizon=5, sar=-1.5,
                        interpretation="not_significant"),
            ]),
        )
        for c in result["candidates"]:
            reason = (c.get("reason") or "").lower()
            for w in _BANNED_WORDS:
                self.assertNotIn(w, reason,
                                 f"banned word {w!r} in reason: {reason!r}")


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------


class TestSeams(unittest.TestCase):
    def test_archive_seam_is_callable(self) -> None:
        self.assertTrue(callable(getattr(
            cli, "_run_archive_stat_validation_short_horizon")))

    def test_contamination_seam_is_callable(self) -> None:
        self.assertTrue(callable(getattr(
            cli, "_run_short_horizon_contamination_report")))

    def test_archive_seam_called_with_db_path(self) -> None:
        captured: dict = {}

        def fake_archive(*, db_path):
            captured["db_path"] = db_path
            return _archive_payload([])

        with patch.object(
            cli, "_run_archive_stat_validation_short_horizon",
            side_effect=fake_archive,
        ):
            with patch.object(
                cli, "_run_short_horizon_contamination_report",
                return_value=_contam_payload([]),
            ):
                cli.summarize_short_horizon_showcase(db_path="/sentinel.db")
        self.assertEqual(captured.get("db_path"), "/sentinel.db")

    def test_contamination_seam_called_with_db_path(self) -> None:
        captured: dict = {}

        def fake_contam(*, db_path):
            captured["db_path"] = db_path
            return _contam_payload([])

        with patch.object(
            cli, "_run_archive_stat_validation_short_horizon",
            return_value=_archive_payload([]),
        ):
            with patch.object(
                cli, "_run_short_horizon_contamination_report",
                side_effect=fake_contam,
            ):
                cli.summarize_short_horizon_showcase(db_path="/sentinel.db")
        self.assertEqual(captured.get("db_path"), "/sentinel.db")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCLI(unittest.TestCase):
    def test_json_mode_emits_parseable_json(self) -> None:
        rc, output = _run_cli(
            ["--json", "--limit", "5"],
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=2.0,
                        interpretation="significant"),
            ]),
        )
        self.assertEqual(rc, 0)
        parsed = json.loads(output)
        self.assertEqual(parsed["candidate_count"], 1)
        self.assertEqual(parsed["candidates"][0]["event_id"], 1)
        for k in _CANDIDATE_KEYS:
            self.assertIn(k, parsed["candidates"][0])

    def test_text_mode_default_does_not_raise(self) -> None:
        rc, output = _run_cli(
            [],
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=2.0),
            ]),
        )
        self.assertEqual(rc, 0)
        lower = output.lower()
        for w in _BANNED_WORDS:
            self.assertNotIn(w, lower,
                             f"text rendering used banned word {w!r}")


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
        before = {
            k for k in sys.modules
            if k in self._BLOCKED_MODULES
            or k.startswith("routes.")
            or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)
        }
        _run(
            archive=_archive_payload([
                _record(event_id=1, horizon=1, sar=1.0),
            ]),
        )
        after = {
            k for k in sys.modules
            if k in self._BLOCKED_MODULES
            or k.startswith("routes.")
            or any(k.startswith(b + ".") for b in self._BLOCKED_MODULES)
        }
        self.assertEqual(after - before, set(),
                         "default run imported a forbidden module")


if __name__ == "__main__":
    unittest.main()
