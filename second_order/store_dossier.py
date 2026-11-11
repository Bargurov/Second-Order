"""Store-backed Dossier views: frozen hypotheses and their selected stored evaluations, read-only.

The stored evaluation is authoritative. It is never rescored under the current rules and never
re-pointed at a newer snapshot. Charts and reference distributions are rebuilt only from the
pinned baseline and outcome snapshots, the recorded rules and the recorded evaluation clock, and
the rebuilt evaluation must equal the stored one exactly, or preparation fails.

Provenance follows the provider of the pinned snapshots: FRED's views are unchanged, and a case bound to the Board's
H.15 release package is labelled and cited as the Board's data, with no vintage (the package has none) and its receipt
time as the time the data were held.
"""
from datetime import datetime
import json
import sqlite3
from .data import ny_date
from .evaluation import DAILY_CONVENTION_NOTE
from .registry import BOARD_H15, FRED, binding, resolve
from .schema import Hypothesis
from .scoring import Rules
from .snapshots import Snapshot, evaluate_bound, has_market_tables, load_snapshot, pinned_series
from .views import reference_view, series_view

FRED_ATTRIBUTION = ("This product uses the FRED® API but is not endorsed or certified by the "
                    "Federal Reserve Bank of St. Louis.")
BOARD_ATTRIBUTION = ("Source: Board of Governors of the Federal Reserve System, H.15 Selected Interest Rates, from the "
                     "release package on the Board's website, cited as the Board asks; no endorsement by the Board is "
                     "implied.")
# Per provider: the name shown, the attribution, the label in each chart caption, and the limitation texts.
PRESENTATION = {
    FRED: {"provider": "FRED", "attribution": FRED_ATTRIBUTION, "caption": "FRED",
           "convention": "FRED observations are compared by America/New_York date. Treasury quotes are taken at or "
                         "near 3:30 PM with no documented bound, so no intraday observation time is claimed.",
           "pinning": "Reference history comes only from the baseline snapshot bound at freeze; scored dates come "
                      "from the named outcome snapshot. A vintage date is FRED's real-time period, and a retrieval "
                      "time shows possession, not first publication."},
    BOARD_H15: {"provider": "Federal Reserve Board H.15", "attribution": BOARD_ATTRIBUTION, "caption": "Board H.15",
                "convention": "H.15 observations are compared by America/New_York date. The release package states "
                              "dates only, and Treasury quotes are taken at or near 3:30 PM with no documented bound, "
                              "so no intraday observation time is claimed.",
                "pinning": "Reference history comes only from the baseline snapshot bound at freeze; scored dates "
                           "come from the named outcome snapshot. The Board's release package has no historical "
                           "vintage: its values are as the Board published them when the package was received, and "
                           "the receipt time shows possession, not first publication."},
}
ANCHOR_KEYS = ("event_anchor", "reference_end", "score_anchor", "target_at")


def stored_cases(connection: sqlite3.Connection) -> list[tuple[str, Hypothesis, str]]:
    """Frozen hypotheses bound to a baseline snapshot (fixture showcases are prepared separately)."""
    if not has_market_tables(connection):
        return []
    rows = connection.execute("SELECT h.id, h.payload, b.baseline_snapshot_id FROM hypotheses h "
                              "JOIN freeze_bindings b ON b.hypothesis_id = h.id ORDER BY h.recorded_at, h.id")
    return [(identity, Hypothesis.model_validate_json(payload), baseline) for identity, payload, baseline in rows]


def select_evaluation(connection: sqlite3.Connection, hypothesis_id: str, chosen: str | None) -> tuple[str, dict] | None:
    rows = connection.execute("SELECT id, payload FROM evaluations WHERE hypothesis_id=? ORDER BY recorded_at, id",
                              (hypothesis_id,)).fetchall()
    if chosen is not None:
        match = [payload for identity, payload in rows if identity == chosen]
        if not match:
            raise ValueError(f"Evaluation {chosen} is not stored for hypothesis {hypothesis_id}")
        return chosen, json.loads(match[0])
    if len(rows) > 1:
        raise ValueError(f"Hypothesis {hypothesis_id} has {len(rows)} stored evaluations; choose one with "
                         f"--evaluation {hypothesis_id}=<evaluation id> from: {', '.join(row[0] for row in rows)}")
    return (rows[0][0], json.loads(rows[0][1])) if rows else None


def reconstruct(connection: sqlite3.Connection, hypothesis_id: str, baseline_id: str,
                evaluation: dict) -> dict[str, tuple[float, ...]]:
    """Re-run a stored evaluation from its pinned inputs; it must reproduce the record exactly."""
    rules = Rules(**evaluation["rules"])
    if rules.hash != evaluation["rules_hash"]:
        raise ValueError(f"Stored evaluation for {hypothesis_id} has rules that do not match their recorded hash")
    pinned = evaluation.get("snapshots") or {}
    if pinned.get("baseline") != baseline_id or not pinned.get("outcome"):
        raise ValueError(f"Stored evaluation for {hypothesis_id} is not pinned to its freeze-time baseline")
    references: dict[str, tuple[float, ...]] = {}
    rebuilt = evaluate_bound(connection, hypothesis_id, pinned["outcome"], datetime.fromisoformat(evaluation["as_of"]),
                             rules, references)
    if {"hypothesis_id": hypothesis_id, **rebuilt} != evaluation:
        raise ValueError(f"Stored evaluation for {hypothesis_id} cannot be reproduced from its pinned snapshots, "
                         "recorded rules and evaluation clock; refusing to prepare it")
    return references


def snapshot_summary(snapshot: Snapshot) -> dict:
    return {"snapshot_id": snapshot.id, "vintage_date": snapshot.payload["vintage_date"],
            "retrieved_at": snapshot.payload["retrieved_at"], "adapter_version": snapshot.payload["adapter_version"]}


def snapshot_caption(snapshot: Snapshot) -> str:
    """A snapshot in a chart caption: its vintage for FRED; for a package, that it has none and when it was held."""
    if snapshot.provider == FRED:
        return f"{snapshot.id[:10]} (vintage {snapshot.payload['vintage_date']})"
    return f"{snapshot.id[:10]} (no vintage; package received {ny_date(snapshot.retrieved_at).isoformat()})"


def store_limitations(hypothesis: Hypothesis, provider: str = FRED) -> list[dict]:
    shown = PRESENTATION[provider]
    items = [
        {"title": "Daily measurement convention", "text": shown["convention"]},
        {"title": "Pinned snapshots", "text": shown["pinning"]},
        {"title": "Not independent evidence",
         "text": "Two maturities of one yield curve demonstrate the lifecycle; they are not independent "
                 "observations, and showcase cases never enter research scores."},
        {"title": "No causal proof",
         "text": "Labels describe whether later observations were consistent with the frozen hypothesis. "
                 "They do not show that the event caused the move and are not significance tests."},
    ]
    if hypothesis.engine.provider == "manual":
        items.insert(0, {"title": "Manual submission",
                         "text": "Submitted manually and frozen before its outcome, outside the project's model "
                                 "adapter, which does not rule out AI assistance; the engine record states how it "
                                 "was authored."})
    return items


def build_store_dossier(connection: sqlite3.Connection, hypothesis_id: str, hypothesis: Hypothesis,
                        baseline_id: str, selected: tuple[str, dict] | None, view: dict) -> dict:
    """`view` carries the shared fields; this adds the store-specific state, provenance and legs."""
    baseline = load_snapshot(connection, baseline_id)
    shown = PRESENTATION[baseline.provider]
    provenance = {"provider": shown["provider"], "attribution": shown["attribution"],
                  "measurement_convention": DAILY_CONVENTION_NOTE, "baseline": snapshot_summary(baseline), "outcome": None}
    published = ny_date(hypothesis.event.published_at)
    shared = {**view, "data_provenance": provenance, "published_date": published.isoformat(),
              "limitations": store_limitations(hypothesis, baseline.provider)}
    if selected is None:
        legs = [{"leg_id": leg.id, "unit": resolve(leg.observable_id).unit,
                 "measurement": resolve(leg.observable_id).measurement, "reference": None, "series": None,
                 "anchor_dates": None} for leg in hypothesis.legs]
        return {**shared, "state": "not_evaluated", "evaluation": None, "evaluation_id": None, "legs": legs}
    evaluation_id, evaluation = selected
    references = reconstruct(connection, hypothesis_id, baseline_id, evaluation)
    outcome = load_snapshot(connection, evaluation["snapshots"]["outcome"])
    provenance["outcome"] = snapshot_summary(outcome)
    labels = {node.id: node.label for node in hypothesis.nodes}
    as_of = datetime.fromisoformat(evaluation["as_of"])
    legs = []
    for leg, result in zip(hypothesis.legs, evaluation["legs"]):
        series_id = binding(leg.observable_id)[1]
        series = pinned_series(leg.observable_id, series_id, baseline, outcome, published)
        caption = (f"{shown['caption']} {series_id} · New York observation dates · baseline "
                   f"{snapshot_caption(baseline)} · outcome {snapshot_caption(outcome)}")
        legs.append({
            "leg_id": leg.id, "unit": resolve(leg.observable_id).unit,
            "measurement": resolve(leg.observable_id).measurement,
            "reference": reference_view(references[leg.id], result) if leg.id in references else None,
            "series": series_view(series, result, labels[leg.node_id], None, as_of, caption, shown["attribution"]),
            "anchor_dates": {key: ny_date(datetime.fromisoformat(result[key])).isoformat()
                             for key in ANCHOR_KEYS if key in result},
        })
    return {**shared, "state": "evaluated", "evaluation": evaluation, "evaluation_id": evaluation_id, "legs": legs}
