"""Prepared Dossier views. An explicit action builds them; read paths only serve the files.

Fixture showcases (fictional events) are evaluated offline from the committed FICTIONAL
demonstration series (fixtures/demo-market.json); nothing in them is a market observation.
When a store is named, its frozen cases are read through a read-only connection and shown with
their selected stored evaluation (see store_dossier); preparation never writes the store.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from .data import Series
from .demo import SHOWCASE_AS_OF, load_market, load_provenance, load_showcases
from .evaluation import evaluate
from .registry import resolve
from .schema import Hypothesis
from .scoring import Rules
from .store import connect_read_only
from .store_dossier import build_store_dossier, select_evaluation, stored_cases
from .views import reference_view, series_view  # noqa: F401  (re-exported for callers and tests)

# 0.3: fixture showcases are fictional events on the fictional demonstration series (series provenance names the
# description, generator and version instead of a capture; the limitation "Fictional demonstration data"; captions name
# fictional-demo and the generator version). A store case's view is unchanged from 0.2.
VIEW_VERSION = "dossier-view-0.3"
PREPARED_DIR = Path(__file__).resolve().parent.parent / "data" / "prepared"


def provenance_label(hypothesis: Hypothesis) -> str:
    if hypothesis.engine.provider == "manual":
        origin = ("Manually reconstructed replay" if hypothesis.evidence_class == "replay"
                  else "Manual prospective hypothesis")
    else:
        origin = f"{hypothesis.evidence_class.capitalize()} model hypothesis"
    return f"{origin} · {'showcase illustration' if hypothesis.usage == 'showcase' else 'research case'}"


def research_status(hypothesis: Hypothesis, rules: Rules) -> dict:
    if hypothesis.usage == "showcase":
        return {"enters_research_scores": False, "reason": "Showcase cases never enter research scores."}
    if hypothesis.supersedes:
        return {"enters_research_scores": False, "reason": "Revisions never improve research scores."}
    return {"enters_research_scores": True,
            "reason": f"Counts in the {hypothesis.evidence_class} summary under rules {rules.version}."}


def limitations(hypothesis: Hypothesis, provenance: list[dict]) -> list[dict]:
    items = [{"title": "Fictional demonstration data",
              "text": " ".join(sorted({f"{row['description']} Generator: {row['generator']} ({row['version']})."
                                       for row in provenance})) or "Not recorded."}]
    notes = sorted({row["timestamp_note"] for row in provenance if row["timestamp_basis"] != "observed"})
    if notes:
        items.append({"title": "Illustrative daily timestamps", "text": " ".join(notes)})
    if hypothesis.engine.provider == "manual":
        items.append({"title": "Retrospective hypothesis",
                      "text": "Submitted manually after the event from the committed recipe, outside the project's "
                              "model adapter, which does not rule out AI assistance; not a blinded model run."})
    items.append({"title": "No causal proof",
                  "text": "Labels describe whether later observations were consistent with the frozen hypothesis. "
                          "They do not show that the event caused the move and are not significance tests."})
    return items


def shared_view(identity: str, hypothesis: Hypothesis, rules: Rules) -> dict:
    return {"view_version": VIEW_VERSION, "id": identity, "label": provenance_label(hypothesis),
            "hypothesis": hypothesis.model_dump(mode="json"), "research": research_status(hypothesis, rules)}


def build_dossier(hypothesis: Hypothesis, market: dict[str, Series], provenance: dict[str, dict],
                  as_of: datetime = SHOWCASE_AS_OF, rules: Rules | None = None) -> dict:
    """A fixture showcase, evaluated offline from the committed fictional demonstration series."""
    rules = rules or Rules()
    references: dict[str, tuple[float, ...]] = {}
    evaluation = evaluate(hypothesis, market, as_of, rules, references)
    labels = {node.id: node.label for node in hypothesis.nodes}
    legs = []
    for leg, result in zip(hypothesis.legs, evaluation["legs"]):
        observable, series = resolve(leg.observable_id), market.get(leg.observable_id)
        legs.append({
            "leg_id": leg.id, "unit": observable.unit, "measurement": observable.measurement,
            "reference": reference_view(references[leg.id], result) if leg.id in references else None,
            "series": (series_view(series, result, labels[leg.node_id], provenance.get(leg.observable_id), as_of)
                       if series else None),
            "anchor_dates": None,
        })
    used = [provenance[leg.observable_id] for leg in hypothesis.legs if leg.observable_id in provenance]
    return {**shared_view(evaluation["hypothesis_id"], hypothesis, rules), "state": "evaluated",
            "evaluation": evaluation, "evaluation_id": None, "legs": legs, "data_provenance": None,
            "published_date": None, "limitations": limitations(hypothesis, used)}


def store_views(db: str, selections: dict[str, str]) -> list[dict]:
    """Frozen store cases with their selected evaluations, through a read-only connection."""
    connection = connect_read_only(db)
    try:
        cases = stored_cases(connection)
        unknown = set(selections) - {identity for identity, _, _ in cases}
        if unknown:
            raise ValueError(f"No frozen store case for the selected hypotheses: {', '.join(sorted(unknown))}")
        views = []
        for identity, hypothesis, baseline in cases:
            selected = select_evaluation(connection, identity, selections.get(identity))
            rules = Rules(**selected[1]["rules"]) if selected else Rules()
            views.append(build_store_dossier(connection, identity, hypothesis, baseline, selected,
                                             shared_view(identity, hypothesis, rules)))
        return views
    finally:
        connection.close()


def index_entry(view: dict, source: str) -> dict:
    evaluation = view["evaluation"]
    return {"id": view["id"], "headline": view["hypothesis"]["event"]["headline"],
            "published_at": view["hypothesis"]["event"]["published_at"], "label": view["label"], "source": source,
            "state": view["state"], "evidence_class": view["hypothesis"]["evidence_class"],
            "usage": view["hypothesis"]["usage"], "evaluation_id": view["evaluation_id"],
            "verdict": evaluation["verdict"] if evaluation else None,
            "rules_version": evaluation["rules"]["version"] if evaluation else None,
            "as_of": evaluation["as_of"] if evaluation else None}


def write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                         encoding="utf-8")
    os.replace(temporary, path)


def prepare(out_dir: Path = PREPARED_DIR, db: str | None = None, selections: dict[str, str] | None = None) -> dict:
    """Explicit preparation. Every view is built before any file is written."""
    market, provenance = load_market(), load_provenance()
    fixtures = sorted((build_dossier(hypothesis, market, provenance) for hypothesis in load_showcases()),
                      key=lambda view: view["hypothesis"]["event"]["published_at"])
    stored = store_views(db, selections or {}) if db is not None else []
    out_dir.mkdir(parents=True, exist_ok=True)
    for view in fixtures + stored:
        write_json(out_dir / f"{view['id']}.json", view)
    index = {
        "view_version": VIEW_VERSION, "fixture_as_of": SHOWCASE_AS_OF.isoformat(),
        "active_rules_version": Rules().version,
        "dossiers": [index_entry(view, "fixture") for view in fixtures]
                    + [index_entry(view, "store") for view in stored],
    }
    write_json(out_dir / "index.json", index)
    return index
