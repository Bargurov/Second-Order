"""Tests for scripts/reaction_profile_calibration_report.py — the read-only
empirical calibration audit of the production reaction_profile_v1
classification rules.

Contract under test
-------------------
* The audit-side classifier must be byte-equivalent to the production
  composer ``reaction_profile.compute_reaction_profile`` for every
  scorable observation (rounded values, labels, tie handling, final-zero,
  threshold inclusivity).
* The eligibility gate is the established accepted track-record gate
  (``db.NON_THESIS_STAGES`` + ``db.synthetic_seed_ids``), never a
  hand-picked event list.
* All analysis is read-only: no provider import, no network, no DB write.
* Output is JSON-safe (string keys only — no tuple keys) and
  deterministic across repeated runs.

Synthetic fixtures cover edge behavior; the real archive (guarded by a
skip when ``events.db`` is absent) provides the read-only audit proof.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import reaction_profile as rp  # noqa: E402
from scripts import reaction_profile_calibration_report as rpc  # noqa: E402
from scripts.event_date_quality_report import (  # noqa: E402
    _primary_ticker as edq_primary_ticker,
)

EVENTS_DB = ROOT / "events.db"

needs_real_db = pytest.mark.skipif(
    not EVENTS_DB.exists(), reason="live events.db not present"
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _weekdays(start_iso: str, n: int) -> list[str]:
    """n consecutive weekday ISO dates starting at start_iso (a weekday)."""
    d = _date.fromisoformat(start_iso)
    out: list[str] = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += _timedelta(days=1)
    return out


def _closes_from_pcts(anchor: float, pcts: list[float]) -> list[float]:
    return [anchor] + [anchor * (1.0 + p / 100.0) for p in pcts]


def _mk_db(path: Path, events=(), price_series=(), hygiene=()) -> str:
    """Create a minimal fixture archive with the tables the audit reads.

    ``events``: iterables of (id, event_date, stage, market_tickers_json).
    ``price_series``: iterables of (ticker, start_iso, closes, auto_adjust).
    ``hygiene``: iterables of (event_id, override_class).
    """
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE events ("
        " id INTEGER PRIMARY KEY, timestamp TEXT, event_date TEXT,"
        " stage TEXT, mechanism_family TEXT, headline TEXT,"
        " market_tickers TEXT)"
    )
    conn.execute(
        "CREATE TABLE event_hygiene (event_id INTEGER, override_class TEXT)"
    )
    conn.execute(
        "CREATE TABLE price_cache ("
        " ticker TEXT NOT NULL, date TEXT NOT NULL, close REAL, volume REAL,"
        " auto_adjust INTEGER NOT NULL, fetched_at TEXT NOT NULL,"
        " PRIMARY KEY (ticker, date, auto_adjust))"
    )
    for eid, event_date, stage, tickers_json in events:
        conn.execute(
            "INSERT INTO events (id, timestamp, event_date, stage,"
            " mechanism_family, headline, market_tickers)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                eid,
                f"2026-01-01T00:00:{eid:02d}",
                event_date,
                stage,
                None,
                f"fixture event {eid}",
                tickers_json,
            ),
        )
    for ticker, start_iso, closes, auto_adjust in price_series:
        for day, close in zip(_weekdays(start_iso, len(closes)), closes):
            conn.execute(
                "INSERT INTO price_cache"
                " (ticker, date, close, volume, auto_adjust, fetched_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, day, close, 1000.0, auto_adjust, "2026-01-01T00:00:00"),
            )
    for event_id, override_class in hygiene:
        conn.execute(
            "INSERT INTO event_hygiene (event_id, override_class) VALUES (?, ?)",
            (event_id, override_class),
        )
    conn.commit()
    conn.close()
    return str(path)


def _tk(symbol, **extra) -> dict:
    return {"symbol": symbol, **extra}


# Per-horizon percent paths (bars 1..N from a 100.0 anchor).
_PCTS_HOLD = [4.0, 3.8, 3.7, 3.6, 3.5] + [3.4, 3.3, 3.2, 3.1] + [3.0] * 11
_PCTS_FADE = [5.0, 4.0, 3.0, 2.0, 1.5] + [1.45, 1.4, 1.35, 1.3] + [1.2] * 11
_PCTS_REVERSE = [3.0, 1.5, 0.5, -0.5, -1.0] + [-1.2, -1.4, -1.6, -1.8] + [-2.0] * 11
_PCTS_FLAT = [0.5, 0.4, 0.3, 0.2, 0.1] + [0.1] * 15
_PCTS_QQQX = [3.0, 2.9, 2.8, 2.7, 2.6] + [2.55, 2.5, 2.45, 2.42] + [2.4] * 11
_PCTS_SPY = [round(0.05 * i, 4) for i in range(1, 21)]
_PCTS_THRESHOLD = [2.0, 1.9, 1.6, 1.5, 1.4]          # ratio exactly 0.70
_PCTS_ROUNDFLIP = [2.0, 1.396, 1.396, 1.396, 1.396]  # 1.40/2.0 vs 1.396/2.0


@pytest.fixture()
def fixture_db(tmp_path):
    events = [
        (1, "2024-03-05", "realized",
         json.dumps([_tk("AAA"), _tk("BBB")])),
        (2, "2024-03-05", "realized", json.dumps([_tk("AAA")])),
        (3, "2024-06-04", "realized", json.dumps([_tk("CCC")])),
        (4, "2024-09-03", "realized", json.dumps([_tk("DDD")])),
        (5, "2024-10-01", "realized", json.dumps([])),
        (6, "2024-10-08", "realized", json.dumps([_tk("ZZZ")])),
        (7, "2024-10-15", "curated_intake", json.dumps([])),
        (8, "2024-10-15", "z1a_candidate_pack", json.dumps([])),
        (9, "2024-10-15", "curated_observation", json.dumps([])),
        (10, "2024-10-15", "analysis_pending_review", json.dumps([])),
        (11, "2024-10-15", "realized", json.dumps([_tk("AAA")])),
        (12, "2024-11-05", "realized",
         json.dumps([_tk("SSS", stale=True)])),
        (13, "2024-11-12", "realized",
         json.dumps([_tk("FFB", same_day_fallback=True)])),
        (14, "2024-12-03", "realized",
         json.dumps([_tk("QQQX", validation_quality="quarantined")])),
        (15, "2025-01-07", "realized",
         json.dumps([42, {"x": 1}, {"symbol": ""}])),
        (16, "2025-01-14", "realized", "not json"),
        (17, "2025-02-04", "realized", json.dumps([_tk("EEE")])),
        (18, "2025-02-11", "realized", json.dumps([_tk("FFF")])),
    ]
    price_series = [
        ("AAA", "2024-03-05", _closes_from_pcts(100.0, _PCTS_HOLD), 0),
        ("AAA", "2024-03-05", _closes_from_pcts(50.0, _PCTS_HOLD), 1),
        ("BBB", "2024-03-05", _closes_from_pcts(100.0, _PCTS_FADE), 0),
        ("SPY", "2024-03-05", _closes_from_pcts(100.0, _PCTS_SPY), 0),
        ("CCC", "2024-06-04", _closes_from_pcts(100.0, _PCTS_REVERSE), 0),
        ("DDD", "2024-09-03", _closes_from_pcts(100.0, _PCTS_FLAT), 0),
        ("SSS", "2024-11-05", [100.0, 101.0, 102.0], 0),
        ("FFB", "2024-11-12", [100.0, 101.0], 0),
        ("QQQX", "2024-12-03", _closes_from_pcts(100.0, _PCTS_QQQX), 0),
        ("SPY", "2024-12-03", _closes_from_pcts(100.0, _PCTS_SPY), 0),
        ("EEE", "2025-02-04", _closes_from_pcts(100.0, _PCTS_THRESHOLD), 0),
        ("FFF", "2025-02-11", _closes_from_pcts(100.0, _PCTS_ROUNDFLIP), 0),
    ]
    hygiene = [(11, "synthetic_seed")]
    return _mk_db(tmp_path / "fixture.db", events, price_series, hygiene)


@pytest.fixture()
def empty_db(tmp_path):
    return _mk_db(tmp_path / "empty.db")


def _sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 1. Eligibility gate (accepted denominator; non-thesis + synthetic excluded)
# ---------------------------------------------------------------------------


def test_eligibility_gate_and_funnel(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    f = report["funnel"]
    assert f["archive_rows"] == 18
    assert f["excluded_non_thesis_stage"] == 4       # ids 7, 8, 9, 10
    assert f["excluded_synthetic_seed"] == 1         # id 11
    assert f["accepted"] == 13
    assert (
        f["accepted"]
        + f["excluded_non_thesis_stage"]
        + f["excluded_synthetic_seed"]
        == f["archive_rows"]
    )


def test_stage_checked_before_synthetic(fixture_db):
    # A row that is both non-thesis stage and synthetic must count once,
    # under the stage reason.
    ev = {"id": 99, "stage": "curated_intake"}
    cls = rpc.classify_eligibility(
        ev,
        synthetic_ids=frozenset({99}),
        non_thesis_stages=frozenset({"curated_intake"}),
    )
    assert cls == "excluded_non_thesis_stage"


def test_no_arbitrary_event_id_allowlist():
    src = Path(rpc.__file__).read_text(encoding="utf-8")
    # No literal multi-entry integer list constants (event-id allowlists).
    assert re.search(r"\[\s*\d+\s*(?:,\s*\d+\s*)+\]", src) is None


# ---------------------------------------------------------------------------
# 2. Current-classifier reproduction (byte-equivalence)
# ---------------------------------------------------------------------------


def _labels_match_production(closes) -> None:
    prod = rp.compute_reaction_profile(closes)
    audit = rpc.classify_observation(closes)
    for h in rpc.PEAK_HORIZONS:
        assert audit[h]["label_rounded"] == prod[f"fade_or_hold_label_{h}"], h
        assert audit[h]["peak_rounded"] == prod[f"peak_move_{h}"], h
        assert audit[h]["final_rounded"] == prod[f"return_{h}"], h
        assert audit[h]["time_to_peak"] == prod[f"time_to_peak_{h}"], h


def test_classifier_equivalence_flat(fixture_db):
    _labels_match_production(_closes_from_pcts(100.0, _PCTS_FLAT))


def test_classifier_equivalence_hold_fade_reverse():
    for pcts in (_PCTS_HOLD, _PCTS_FADE, _PCTS_REVERSE, _PCTS_QQQX):
        _labels_match_production(_closes_from_pcts(100.0, pcts))


def test_classifier_equivalence_negative_paths():
    for pcts in (_PCTS_HOLD, _PCTS_FADE):
        _labels_match_production(
            _closes_from_pcts(100.0, [-p for p in pcts])
        )


def test_hold_at_inclusive_threshold():
    closes = _closes_from_pcts(100.0, _PCTS_THRESHOLD)
    prod = rp.compute_reaction_profile(closes)
    assert prod["fade_or_hold_label_5d"] == "hold"
    audit = rpc.classify_observation(closes)
    assert audit["5d"]["label_rounded"] == "hold"


def test_fade_below_threshold():
    closes = _closes_from_pcts(100.0, [2.0, 1.9, 1.6, 1.5, 1.38])
    prod = rp.compute_reaction_profile(closes)
    assert prod["fade_or_hold_label_5d"] == "fade"
    audit = rpc.classify_observation(closes)
    assert audit["5d"]["label_rounded"] == "fade"


def test_final_zero_is_fade_not_reverse():
    closes = _closes_from_pcts(100.0, [3.0, 2.0, 1.0, 0.5, 0.0])
    prod = rp.compute_reaction_profile(closes)
    assert prod["fade_or_hold_label_5d"] == "fade"
    audit = rpc.classify_observation(closes)
    assert audit["5d"]["label_rounded"] == "fade"
    assert audit["5d"]["label_unrounded"] == "fade"


def test_peak_tie_selects_earliest_bar():
    closes = [100.0, 104.0, 96.0, 100.0, 100.0, 100.0]
    prod = rp.compute_reaction_profile(closes)
    assert prod["time_to_peak_5d"] == 1
    assert prod["peak_move_5d"] == 4.0
    audit = rpc.classify_observation(closes)
    assert audit["5d"]["time_to_peak"] == 1
    assert audit["5d"]["peak_rounded"] == 4.0


def test_insufficient_and_malformed_inputs():
    for closes in (None, [], [100.0], "nope", [100.0, float("nan")]):
        prod = rp.compute_reaction_profile(closes)
        audit = rpc.classify_observation(closes)
        for h in rpc.PEAK_HORIZONS:
            assert audit[h]["label_rounded"] == prod[f"fade_or_hold_label_{h}"]
            assert audit[h]["label_rounded"] == "insufficient"


def test_fixture_archive_zero_equivalence_mismatches(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    assert report["equivalence"]["checked"] > 0
    assert report["equivalence"]["mismatches"] == 0


# ---------------------------------------------------------------------------
# 3. Coverage, label distributions, weighting lenses
# ---------------------------------------------------------------------------


def test_label_distributions_ticker_weighted(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    d5 = report["label_distributions"]["5d"]["ticker_weighted"]
    assert d5["denominator_scorable"] == 8
    assert d5["counts"]["hold"] == 5     # AAA, AAA, QQQX, EEE, FFF(rounded)
    assert d5["counts"]["fade"] == 1     # BBB
    assert d5["counts"]["reverse"] == 1  # CCC
    assert d5["counts"]["flat"] == 1     # DDD
    d20 = report["label_distributions"]["20d"]["ticker_weighted"]
    assert d20["denominator_scorable"] == 6
    assert d20["counts"]["hold"] == 3    # AAA, AAA, QQQX
    d60 = report["label_distributions"]["60d"]["ticker_weighted"]
    assert d60["denominator_scorable"] == 0


def test_event_weighted_never_invents_winner(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    ew = report["label_distributions"]["20d"]["event_weighted"]
    assert ew["events"] == 5
    # Event 1 splits 0.5 hold / 0.5 fade; no winner-takes-all collapse.
    assert ew["share"]["hold"] == pytest.approx(0.5)
    assert ew["share"]["fade"] == pytest.approx(0.1)
    assert ew["mixed"] == 1
    assert ew["all_agree"] == 4


def test_primary_ticker_uses_existing_contract(fixture_db):
    assert rpc._primary_ticker is edq_primary_ticker
    report = rpc.build_report(db_path=fixture_db)
    po = report["label_distributions"]["20d"]["primary_only"]
    # Event 1 primary is AAA (first stored symbol) → hold, not BBB's fade.
    assert po["counts"]["hold"] == 3
    assert po["counts"]["fade"] == 0


def test_ticker_funnel_and_missingness(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    tf = report["ticker_funnel"]
    assert tf["stored_entries"] == 14
    assert tf["non_dict_entries"] == 1        # 42 in event 15
    assert tf["missing_symbol_entries"] == 2  # {"x":1}, {"symbol": ""}
    assert tf["valid_ticker_dicts"] == 11
    assert tf["hydration_status_counts"]["stale"] == 1
    assert tf["hydration_status_counts"]["cache_miss"] == 1
    assert tf["basis_counts"]["same_day_fallback"] == 1
    assert tf["basis_counts"]["stale"] == 1
    assert tf["scorable_by_horizon"]["5d"] == 8
    assert tf["scorable_by_horizon"]["20d"] == 6
    assert tf["scorable_by_horizon"]["60d"] == 0
    assert tf["quarantined_benchmark_tickers"] == 1


def test_stale_and_unscorable_retained_as_missingness(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    f = report["funnel"]
    reasons = f["events_without_hydrated_profile_reasons"]
    # Events 5 and 16 have no stored tickers; 15 has none valid; 6 is a
    # cache miss; 12 is stale-only.  All stay visible, none dropped.
    assert reasons["no_stored_tickers"] == 2
    assert reasons["no_valid_ticker_dicts"] == 1
    assert reasons["all_cache_miss"] == 1
    assert reasons["all_stale"] == 1
    assert f["accepted_with_hydrated_profile"] == 8
    assert f["events_scorable_20d"] == 5


def test_same_day_fallback_excluded_from_primary_distribution(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    # The SDF observation (event 13) must not enter any scorable label
    # count at the peak horizons; it stays in the basis split.
    for h in rpc.PEAK_HORIZONS:
        tw = report["label_distributions"][h]["ticker_weighted"]
        total_labeled = sum(tw["counts"].values())
        assert total_labeled == tw["denominator_scorable"]
    assert report["ticker_funnel"]["basis_counts"]["same_day_fallback"] == 1


def test_benchmark_quarantine_counted_and_excluded(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    br = report["benchmark_relative"]
    assert br["quarantined_observations"] == 1
    # QQQX itself is still raw-scorable (quarantine nulls only benchmark).
    assert report["ticker_funnel"]["scorable_by_horizon"]["20d"] == 6
    # AAA (x2 events) and BBB have SPY paths → matched at 5d.
    assert br["matched_by_horizon"]["5d"] == 3


def test_benchmark_relative_transition_matrix(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    br = report["benchmark_relative"]
    # At 20d, both AAA observations flip hold → fade under the
    # benchmark-relative lens (SPY drift erodes retention).
    assert br["transition_matrix"]["20d"].get("hold->fade", 0) == 2
    assert br["label_change_count"]["20d"] == 2
    # Matrix keys are JSON-safe strings, never tuples.
    for h in rpc.PEAK_HORIZONS:
        for key in br["transition_matrix"][h]:
            assert isinstance(key, str) and "->" in key


# ---------------------------------------------------------------------------
# 4. Retention-ratio behavior and transition curve
# ---------------------------------------------------------------------------


def test_retention_ratio_unrounded(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    ret = report["retention"]
    assert ret["eligible_total"] == 10
    assert ret["eligible_by_horizon"]["5d"] == 6
    assert ret["eligible_by_horizon"]["20d"] == 4
    # FFF sits at rounded 0.70 exactly but 0.698 unrounded.
    assert ret["boundary"]["exactly_070_rounded"] >= 1
    assert ret["rounding_dependent_count"] >= 1


def test_transition_curve_uses_observed_breakpoints_only(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    curve = report["retention"]["curve"]
    ratios = sorted({row["ratio"] for row in report["retention"]["ratios"]})
    thresholds = [pt["threshold"] for pt in curve]
    assert thresholds == sorted(thresholds)
    for t in thresholds:
        assert t in ratios
    # hold counts are monotonically non-increasing as the threshold rises.
    holds = [pt["hold"] for pt in curve]
    assert holds == sorted(holds, reverse=True)


def test_transition_curve_determinism(fixture_db):
    r1 = rpc.build_report(db_path=fixture_db)
    r2 = rpc.build_report(db_path=fixture_db)
    assert r1["retention"]["curve"] == r2["retention"]["curve"]
    assert r1["noise_floors"]["5d"]["curve"] == r2["noise_floors"]["5d"]["curve"]


def test_candidates_derive_only_from_observed_gaps():
    # Dense pile of ratios at the current threshold plus one wide empty
    # plateau elsewhere → exactly one data-derived retention candidate.
    ratios = [0.66, 0.67, 0.68, 0.69, 0.70, 0.71, 0.72,
              0.30, 0.31, 0.32, 0.95, 0.96]
    floors = {h: [] for h in rpc.PEAK_HORIZONS}
    cands = rpc.derive_candidates(ratios, floors)
    assert len(cands) == 1
    c = cands[0]
    assert c["kind"] == "retention_threshold"
    values = sorted(ratios)
    assert c["gap_low"] in values and c["gap_high"] in values
    assert c["proposed"] == pytest.approx((c["gap_low"] + c["gap_high"]) / 2)


def test_no_candidate_without_dense_boundary():
    # Sparse, well-separated ratios: current threshold sits in open space
    # → no admissible candidate (intuition-driven thresholds forbidden).
    ratios = [0.2, 0.4, 0.6, 0.8, 0.9]
    cands = rpc.derive_candidates(ratios, {h: [] for h in rpc.PEAK_HORIZONS})
    assert cands == []


# ---------------------------------------------------------------------------
# 5. Noise floors
# ---------------------------------------------------------------------------


def test_noise_floor_counts_and_curve(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    nf5 = report["noise_floors"]["5d"]
    assert nf5["current_floor"] == 1.0
    assert nf5["n"] == 8
    assert nf5["below_floor"] == 1   # DDD at |peak| 0.5
    floors = [pt["floor"] for pt in nf5["curve"]]
    assert floors == sorted(floors)
    nf60 = report["noise_floors"]["60d"]
    assert nf60["n"] == 0


def test_floor_coherence_with_validation_evidence(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    fc = report["floor_coherence"]
    assert fc["match_5d"] is True
    assert fc["match_20d"] is True
    assert report["noise_floors"]["60d"]["current_floor"] == 3.0


def test_volatility_floor_evaluability_reported(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    vol = report["volatility_floor_evaluability"]
    # Fixture cache has zero pre-anchor bars → the path is unavailable.
    assert vol["observations_with_20plus_pre_anchor_bars"] == 0
    assert vol["evaluable"] is False


# ---------------------------------------------------------------------------
# 6. Rounding sensitivity
# ---------------------------------------------------------------------------


def test_rounding_flip_detected_at_hold_threshold(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    rd = report["rounding"]
    assert rd["total_flips"] >= 1
    assert rd["transitions"].get("fade->hold", 0) >= 1
    assert rd["at_hold_threshold"] >= 1
    affected = {
        (row["event_id"], row["symbol"]) for row in rd["affected_observations"]
    }
    assert (18, "FFF") in affected


# ---------------------------------------------------------------------------
# 7. Basis availability
# ---------------------------------------------------------------------------


def test_adjusted_basis_matched_subset(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    adj = report["adjusted_basis"]
    # Only AAA carries adjusted rows (2 observations via events 1 and 2).
    assert adj["matched_by_horizon"]["5d"] == 2
    assert adj["transition_matrix"]["5d"].get("hold->hold", 0) == 2


# ---------------------------------------------------------------------------
# 8. Horizon and consumer sensitivity
# ---------------------------------------------------------------------------


def test_horizon_transitions_and_frontend_priority(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    hz = report["horizon"]
    assert hz["t5_vs_t20"]["matched"] == 6
    assert hz["t5_vs_t20"]["matrix"].get("hold->hold", 0) == 3
    fp = hz["frontend_priority"]
    # EEE and FFF: 20d label is insufficient while 5d carries signal —
    # the 20d-first display hides that signal.
    assert fp["displayed_insufficient_with_other_signal"] == 2
    assert fp["sixtyd_only_information"] == 0


def test_track_record_composition(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    tr = report["horizon"]["track_record"]
    assert tr["histogram_20d"]["hold"] == 3
    # Events 1+2 form the largest cluster; 3 of the 6 labeled-20d
    # observations come from it.
    assert tr["largest_cluster_share"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Clusters and independence-aware lens
# ---------------------------------------------------------------------------


def test_clusters_partition_accepted_events(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    cl = report["clusters"]
    assert cl["nominal_events"] == 13
    assert cl["cluster_count"] == 12          # events 1+2 merge
    assert cl["largest_size"] == 2
    assigned = set()
    for eid_str in cl["assignment"]:
        assert isinstance(eid_str, str)
        assigned.add(int(eid_str))
    assert len(cl["assignment"]) == 13
    assert assigned == {1, 2, 3, 4, 5, 6, 12, 13, 14, 15, 16, 17, 18}
    assert (
        cl["assignment"]["1"] == cl["assignment"]["2"]
    )


def test_denominators_reconcile(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    f = report["funnel"]
    tf = report["ticker_funnel"]
    # Ticker-weighted scorable at h == sum over events of scorable tickers.
    for h in rpc.PEAK_HORIZONS:
        tw = report["label_distributions"][h]["ticker_weighted"]
        assert tw["denominator_scorable"] == tf["scorable_by_horizon"][h]
    # Event lens denominators never exceed accepted.
    assert f["events_scorable_20d"] <= f["accepted"]
    assert report["clusters"]["nominal_events"] == f["accepted"]


# ---------------------------------------------------------------------------
# 9. Leave-out determinism
# ---------------------------------------------------------------------------


def test_leave_out_determinism_and_shapes(fixture_db):
    r1 = rpc.build_report(db_path=fixture_db)
    r2 = rpc.build_report(db_path=fixture_db)
    assert r1["leave_out"] == r2["leave_out"]
    lo = r1["leave_out"]
    assert lo["loeo"]["runs"] == 5           # events scorable at 20d
    assert lo["loco"]["runs"] == 4           # clusters scorable at 20d
    assert sorted(lo["loyo"]["years"]) == ["2024"]
    assert lo["no_single_ticker"]["events"] == 1  # only event 1 has ≥2 valid


# ---------------------------------------------------------------------------
# 10. Recommendation contract
# ---------------------------------------------------------------------------


def _clean_metrics(**over):
    m = {
        "equivalence_mismatches": 0,
        "accepted_n": 86,
        "events_scorable_20d": 50,
        "eligible_holdfade_total": 60,
        "boundary_share_pm005": 0.05,
        "rounding_flip_share": 0.01,
        "loeo_modal_flip": False,
        "loco_modal_flip": False,
        "admissible_candidates": 0,
    }
    m.update(over)
    return m


def test_recommend_keep_current_rule():
    out = rpc.recommend(_clean_metrics())
    assert out["verdict"] == "KEEP_CURRENT_RULE"
    assert out["blocker"] is False


def test_recommend_not_ready_on_sparse_coverage():
    out = rpc.recommend(_clean_metrics(events_scorable_20d=5))
    assert out["verdict"] == "NOT_CALIBRATION_READY"
    out = rpc.recommend(_clean_metrics(eligible_holdfade_total=3))
    assert out["verdict"] == "NOT_CALIBRATION_READY"


def test_recommend_not_ready_on_dense_boundary():
    out = rpc.recommend(_clean_metrics(boundary_share_pm005=0.40))
    assert out["verdict"] == "NOT_CALIBRATION_READY"


def test_recommend_not_ready_on_rounding_dominance():
    out = rpc.recommend(_clean_metrics(rounding_flip_share=0.25))
    assert out["verdict"] == "NOT_CALIBRATION_READY"


def test_recommend_not_ready_on_leave_out_flip():
    out = rpc.recommend(_clean_metrics(loco_modal_flip=True))
    assert out["verdict"] == "NOT_CALIBRATION_READY"


def test_recommend_adjust_one_rule_single_candidate():
    out = rpc.recommend(_clean_metrics(admissible_candidates=1))
    assert out["verdict"] == "ADJUST_ONE_RULE"


def test_recommend_not_ready_on_multiple_candidates():
    out = rpc.recommend(_clean_metrics(admissible_candidates=2))
    assert out["verdict"] == "NOT_CALIBRATION_READY"


def test_recommend_blocker_on_mismatch():
    out = rpc.recommend(_clean_metrics(equivalence_mismatches=1))
    assert out["blocker"] is True
    assert out["verdict"] not in (
        "KEEP_CURRENT_RULE", "ADJUST_ONE_RULE",
    )


def test_fixture_verdict_is_not_calibration_ready(fixture_db):
    # 10 eligible hold/fade observations < the documented floor of 15.
    report = rpc.build_report(db_path=fixture_db)
    assert report["recommendation"]["verdict"] == "NOT_CALIBRATION_READY"
    assert report["recommendation"]["blocker"] is False


# ---------------------------------------------------------------------------
# JSON safety, determinism, CLI
# ---------------------------------------------------------------------------


def _assert_string_keys(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert isinstance(k, str), f"non-string key {k!r} at {path}"
            _assert_string_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_string_keys(v, f"{path}[{i}]")


def test_json_serializable_string_keys_only(fixture_db):
    report = rpc.build_report(db_path=fixture_db)
    _assert_string_keys(report)
    payload = json.dumps(report, sort_keys=True, allow_nan=False)
    assert json.loads(payload)["contract_version"] == rpc.CONTRACT_VERSION


def test_deterministic_output_over_repeated_runs(fixture_db):
    r1 = rpc.build_report(db_path=fixture_db)
    r2 = rpc.build_report(db_path=fixture_db)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    assert rpc.render_markdown(r1) == rpc.render_markdown(r2)


def test_empty_archive(empty_db):
    report = rpc.build_report(db_path=empty_db)
    assert report["funnel"]["archive_rows"] == 0
    assert report["funnel"]["accepted"] == 0
    assert report["recommendation"]["verdict"] == "NOT_CALIBRATION_READY"
    json.dumps(report, allow_nan=False)
    assert "NOT_CALIBRATION_READY" in rpc.render_markdown(report)


def test_cli_text_and_json(fixture_db, capsys):
    assert rpc.main(["--db-path", fixture_db]) == 0
    text = capsys.readouterr().out
    assert "NOT_CALIBRATION_READY" in text
    assert rpc.main(["--db-path", fixture_db, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["contract_version"] == rpc.CONTRACT_VERSION


# ---------------------------------------------------------------------------
# Read-only and no-provider proofs
# ---------------------------------------------------------------------------


def test_no_database_writes(fixture_db):
    before = _sha256(fixture_db)
    rpc.build_report(db_path=fixture_db)
    assert _sha256(fixture_db) == before


def test_no_provider_modules_loaded_subprocess(fixture_db):
    code = (
        "import sys; sys.path.insert(0, {root!r});\n"
        "from scripts.reaction_profile_calibration_report import build_report\n"
        "build_report(db_path={db!r})\n"
        "banned = [m for m in ('yfinance', 'market_data') if m in sys.modules]\n"
        "sys.exit(1 if banned else 0)\n"
    ).format(root=str(ROOT), db=fixture_db)
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr


def test_no_provider_or_network_imports_in_source():
    src = Path(rpc.__file__).read_text(encoding="utf-8")
    for banned in ("yfinance", "market_data", "requests", "urllib",
                   "httpx", "socket"):
        assert not re.search(rf"^\s*(import|from)\s+{banned}\b", src, re.M), (
            banned
        )


# ---------------------------------------------------------------------------
# Read-only cache reader mirrors the production read path
# ---------------------------------------------------------------------------


def test_ro_cache_reader_mirrors_read_window_no_fetch(fixture_db, monkeypatch):
    import pandas as pd
    import db as _db
    import price_cache

    monkeypatch.setattr(_db, "DB_FILE", fixture_db)
    monkeypatch.setattr(price_cache, "_table_ready", False)
    reader = rpc.make_ro_cache_reader(fixture_db)
    for symbol, start in (("AAA", "2024-03-05"), ("MISSING", "2024-03-05")):
        prod = price_cache.read_window_no_fetch(
            symbol, start=start, auto_adjust=False
        )
        audit = reader(symbol, start=start, auto_adjust=False)
        pd.testing.assert_frame_equal(prod, audit)


# ---------------------------------------------------------------------------
# Real-archive audit proof (read-only, skipped when events.db is absent)
# ---------------------------------------------------------------------------


@needs_real_db
def test_real_archive_read_only_and_equivalent():
    before = _sha256(EVENTS_DB)
    report = rpc.build_report(db_path=str(EVENTS_DB))
    assert _sha256(EVENTS_DB) == before
    assert report["db_unchanged"] is True
    assert report["equivalence"]["mismatches"] == 0
    assert report["funnel"]["accepted"] >= 1
    assert report["recommendation"]["verdict"] in (
        "KEEP_CURRENT_RULE", "ADJUST_ONE_RULE", "NOT_CALIBRATION_READY",
    )
    json.dumps(report, sort_keys=True, allow_nan=False)
