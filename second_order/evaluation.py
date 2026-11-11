"""Explicit evaluation, primary-only research summaries and rolling placebos."""
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
import re
from .anchors import Anchors, DataPending, DataUnavailable, anchors
from .data import DAILY_DATE_CONVENTION, Series
from .registry import is_demo, resolve
from .schema import Hypothesis, Leg, utc
from .scoring import Rules, Score, fit_market_model, non_overlapping, reference_moves, score_at

RULES_HASH = re.compile(r"[a-f0-9]{64}")
DAILY_CONVENTION_NOTE = ("Daily measurement convention: observations are compared by America/New_York "
                         "calendar date; no intraday observation time is verified.")

def placebo(series: Series, leg: Leg, anchor: int, reference_end: int, rules: Rules,
            benchmark: Series | None = None) -> dict:
    return placebo_controls(series, leg.observable_id, leg.horizon, leg.expected, reference_end, rules, benchmark)


def placebo_controls(series: Series, observable_id: str, horizon: int, expected: str, reference_end: int,
                     rules: Rules, benchmark: Series | None = None) -> dict:
    """Select dates by calendar/history only. Refit and re-rank at every date."""
    observable = resolve(observable_id)
    earliest = series.observations[reference_end].at - timedelta(days=365)
    candidates = [
        i for i in range(max(0, reference_end - rules.reference_days), reference_end - horizon)
        if series.observations[i].at >= earliest
        and i >= rules.reference_days
        and (observable.measurement != "market_model" or i >= rules.estimation_days + rules.estimation_gap)
    ]
    count = min(len(candidates), rules.placebo_dates)
    indexes = ([candidates[(j * (len(candidates) - 1)) // max(1, count - 1)] for j in range(count)]
               if count else [])
    scores = [score_at(series, observable, i, i, horizon, expected, rules, benchmark) for i in indexes]
    eligible = [score for score in scores if score.verdict in {"supported", "contradicted", "inconclusive"}]
    counts = {state: sum(score.verdict == state for score in eligible)
              for state in ("supported", "contradicted", "inconclusive")}
    return {
        "selected_dates": [series.observations[i].at.isoformat() for i in indexes],
        "requested": rules.placebo_dates, "selected": count, "eligible": len(eligible),
        "unavailable": count - len(eligible), "counts": counts,
        "rates": {state: value / len(eligible) if eligible else None for state, value in counts.items()},
    }


def history_readiness(series: Series, reference_end: int, horizon: int, rules: Rules,
                      benchmark: Series | None = None) -> dict:
    """What the scorer would have at an event anchor at reference_end: the same windows and controls.

    Requirements come from running the procedure itself, not from a fixed session count.
    """
    observable = resolve(series.observable_id)
    model = None
    try:
        if observable.measurement == "market_model":
            model = fit_market_model(series, benchmark, reference_end, rules)
        values, starts = reference_moves(series, observable, reference_end, horizon, 1, rules, model, benchmark)
    except DataUnavailable as exc:
        return {"horizon": horizon, "scorable": False, "reason": str(exc), "reference_windows": 0,
                "required_reference_windows": rules.min_windows}
    controls = placebo_controls(series, series.observable_id, horizon, "up", reference_end, rules, benchmark)
    return {"horizon": horizon, "reference_windows": len(values),
            "non_overlapping_reference_windows": non_overlapping(starts, horizon),
            "required_reference_windows": rules.min_windows, "scorable": len(values) >= rules.min_windows,
            "placebo": {key: controls[key] for key in ("requested", "selected", "eligible")}}


def score_record(score: Score) -> dict:
    """Stored leg fields; a fitted market model is recorded separately as estimation_window."""
    record = asdict(score)
    record.pop("model")
    return record


def estimation_record(series: Series, score: Score) -> dict:
    model = score.model
    assert model is not None
    return {"first_price_at": series.observations[model.start].at.isoformat(),
            "last_price_at": series.observations[model.end].at.isoformat(),
            "returns": model.end - model.start, "alpha": model.alpha, "beta": model.beta}


def scored_window(hypothesis: Hypothesis, leg: Leg, series: Series) -> tuple[Anchors, int]:
    """A leg's anchors and the index of its target observation: the scoring anchor plus the horizon, counted in the
    series' observation grid (a missing session counts; an explained gap is not in the grid). Raises DataPending or
    DataUnavailable as the anchor policy does. The one definition evaluation and readiness both use."""
    anchor = anchors(hypothesis, series)
    return anchor, anchor.score_index + leg.horizon


def evaluate_leg(hypothesis: Hypothesis, leg: Leg, series: Series | None,
                 all_series: dict[str, Series], as_of: datetime, rules: Rules,
                 references: dict[str, tuple[float, ...]] | None = None) -> dict:
    result = {"leg_id": leg.id, "primary": leg.primary, "observable_id": leg.observable_id,
              "horizon": leg.horizon, "unit": resolve(leg.observable_id).unit}
    if series is None:
        return result | score_record(Score("unavailable", reason="Observable data not supplied"))
    if series.observable_id != leg.observable_id:
        raise ValueError("Leg and series IDs differ")
    try:
        anchor, target = scored_window(hypothesis, leg, series)
        event_at = series.observations[anchor.event_index].at
        score_at_time = series.observations[anchor.score_index].at
        result.update(event_anchor=event_at.isoformat(), score_anchor=score_at_time.isoformat(),
                      reference_end=series.observations[anchor.reference_end].at.isoformat(),
                      anchor_policy=anchor.reason, initial_reaction_scored=False)
        if series.timestamp_basis == DAILY_DATE_CONVENTION:
            result["measurement_convention"] = DAILY_CONVENTION_NOTE
        if leg.headline_reports_move and anchor.event_index == anchor.score_index:
            return result | score_record(Score("excluded", reason="Headline already reports this measured move"))
        if series.timestamp_basis != "observed" and hypothesis.usage == "research":
            return result | score_record(Score("unavailable",
                                               reason="Research requires verified observation timestamps"))
        if target >= len(series.observations):
            if series.open_ended:
                return result | score_record(Score("pending", reason="The scored horizon is not in the imported data yet"))
            return result | score_record(Score("unavailable", reason="Observation calendar does not cover horizon"))
        target_at = series.observations[target].at
        result["target_at"] = target_at.isoformat()
        if target_at > as_of:
            return result | score_record(Score("pending", reason="Scored horizon has not elapsed"))
        observable = resolve(leg.observable_id)
        benchmark = all_series.get(observable.benchmark) if observable.benchmark else None
        captured: list[float] = []
        # Equity fits end before the pre-publication event anchor, however late the freeze.
        score = score_at(series, observable, anchor.score_index, anchor.reference_end,
                         leg.horizon, leg.expected, rules, benchmark, anchor.available_end, captured,
                         estimation_anchor=anchor.event_index)
        if references is not None and score.percentile_rank is not None:
            references[leg.id] = tuple(captured)
        result.update(score_record(score))
        if score.model is not None:
            result["estimation_window"] = estimation_record(series, score)
        if leg.primary and score.verdict in {"supported", "contradicted", "inconclusive"}:
            result["placebo"] = placebo(series, leg, anchor.score_index, anchor.reference_end,
                                        rules, benchmark)
        return result
    except DataPending as exc:
        return result | score_record(Score("pending", reason=str(exc)))
    except DataUnavailable as exc:
        return result | score_record(Score("unavailable", reason=str(exc)))


def dossier_verdict(legs: list[dict]) -> str:
    primary = next(leg for leg in legs if leg["primary"])
    if primary["verdict"] == "supported":
        if any(leg["verdict"] == "contradicted" for leg in legs if not leg["primary"]):
            return "mixed"
        if any(leg["verdict"] in {"pending", "unavailable", "excluded"} for leg in legs if not leg["primary"]):
            return "incomplete"
    return primary["verdict"]


def evaluate(hypothesis: Hypothesis, series: dict[str, Series], as_of: datetime,
             rules: Rules | None = None, references: dict[str, tuple[float, ...]] | None = None) -> dict:
    """references, when given, collects each ranked leg's exact reference moves; the payload is unchanged."""
    as_of, rules = utc(as_of), rules or Rules()
    if as_of < hypothesis.effective_freeze:
        raise ValueError("Evaluation cannot precede effective freeze")
    legs = [evaluate_leg(hypothesis, leg, series.get(leg.observable_id), series, as_of, rules, references)
            for leg in hypothesis.legs]
    payload = {
        "hypothesis_id": hashlib.sha256(json.dumps(hypothesis.model_dump(mode="json"), sort_keys=True,
                                                   separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
        "supersedes": hypothesis.supersedes,
        "evidence_class": hypothesis.evidence_class, "usage": hypothesis.usage, "story_id": hypothesis.story_id,
        "as_of": as_of.isoformat(), "rules": asdict(rules), "rules_hash": rules.hash,
        "verdict": dossier_verdict(legs), "legs": legs,
    }
    snapshot = {
        key: {"source": value.source, "basis": value.basis, "timestamp_basis": value.timestamp_basis,
              "points": [(p.at.isoformat(), p.value, p.contract) for p in value.observations if p.at <= as_of],
              "sessions": [(s.opened_at.isoformat(), s.closed_at.isoformat()) for s in value.sessions]}
        for key, value in sorted(series.items())
    }
    payload["data_hash"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return payload


def rules_configurations(evaluations: list[dict]) -> list[dict]:
    """The rules configurations present, so a summary can select exactly one; never pooled."""
    found: dict[str, dict] = {}
    for row in evaluations:
        entry = found.setdefault(row["rules_hash"], {"rules_hash": row["rules_hash"],
                                                     "rules_version": row["rules"]["version"],
                                                     "evaluations": 0, "hypotheses": set()})
        entry["evaluations"] += 1
        entry["hypotheses"].add(row["hypothesis_id"])
    return [{**entry, "hypotheses": len(entry["hypotheses"])}
            for entry in sorted(found.values(), key=lambda entry: (entry["rules_version"], entry["rules_hash"]))]


def scoreboard(evaluations: list[dict], evidence_class: str, rules_hash: str) -> dict:
    """Primary-leg research summary for one evidence class under exactly one rules configuration. A hypothesis with
    any leg on a fictional demonstration series never counts, whatever its recorded usage."""
    if evidence_class not in {"prospective", "replay"}:
        raise ValueError("Choose one evidence class")
    if not isinstance(rules_hash, str) or not RULES_HASH.fullmatch(rules_hash):
        raise ValueError("Select one rules configuration by its 64-character hash")
    selected = [row for row in evaluations if row["rules_hash"] == rules_hash]
    versions = {row["rules"]["version"] for row in selected}
    rows = [row for row in selected if row["usage"] == "research"
            and row["evidence_class"] == evidence_class and not row.get("supersedes")
            and not any(is_demo(leg["observable_id"]) for leg in row["legs"])]
    latest = {}
    for row in rows:
        identity = row["hypothesis_id"]
        if identity not in latest or row["as_of"] > latest[identity]["as_of"]:
            latest[identity] = row
    rows = list(latest.values())
    primary = [next(leg for leg in row["legs"] if leg["primary"]) for row in rows]
    eligible = [leg for leg in primary if leg["verdict"] in {"supported", "contradicted", "inconclusive"}]
    counts = {state: sum(leg["verdict"] == state for leg in primary)
              for state in ("supported", "contradicted", "inconclusive", "unavailable", "pending", "excluded")}
    controls = [leg["placebo"]["rates"] for leg in eligible
                if leg.get("placebo", {}).get("eligible", 0)]
    return {
        "evidence_class": evidence_class, "rules_hash": rules_hash,
        "rules_version": versions.pop() if versions else None,
        "hypotheses": len(rows), "eligible_primary_legs": len(eligible),
        "story_groups": len({row["story_id"] for row in rows}), "counts": counts,
        "rates": {state: counts[state] / len(eligible) if eligible else None
                  for state in ("supported", "contradicted", "inconclusive")},
        "placebo_coverage": len(controls),
        "placebo_rates": {state: sum(control[state] for control in controls) / len(controls) if controls else None
                         for state in ("supported", "contradicted", "inconclusive")},
    }
