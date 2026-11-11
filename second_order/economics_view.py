"""What readers see of a story's economic explanation (moved unchanged from story_economics, 29 October 2026).

story_economics checks an explanation and its guard reads it; this module renders a checked one for readers: each text
with its figures and calculations and their qualifiers, each statement with its kind and evidence, the framework notes
it was prepared with as background, and what was read beyond the story's own material. It was split out because
story_economics had reached 754 lines (AGENTS.md, rule 8); story_economics keeps ``reader_view``, ``background`` and
``context_statement`` as entry points for its callers.
"""
from . import brief_claims, econ_calc, econ_classification, econ_context, econ_fidelity, econ_framework
from .story_economics import ALTERNATIVE_SUPPORTS, ALTERNATIVES, HORIZONS, SCOPES, STAGES, SUPPORTS


def _ref_view(ref: str, economics: dict, facts: list[dict], context: dict[str, dict],
              claims: list[dict] | None = None) -> dict:
    kind, _, name = ref.partition(":")
    if kind == "fact":
        fact = facts[int(name) - 1]
        return {"kind": "fact", "label": f"Reported fact {name}", "reports": fact["reports"]}
    if kind == "report":
        return {"kind": "report", "label": "Report", "reports": [name]}
    noted = brief_claims.notes(economics["figures"], claims) if claims is not None else {}
    rows = {row["id"]: ({**row, "claim_note": noted[row["id"]]} if row["id"] in noted else row)
            for row in economics["figures"] + economics["calculations"]}
    if kind == "figure":
        row = rows[name]
        source = row["source"].partition(":")
        return {"kind": "figure", "label": econ_fidelity.reference(row, rows),
                "reports": [source[2]] if source[0] == "report" else []}
    if kind == "calc":
        return {"kind": "calculation", "label": econ_fidelity.reference(rows[name], rows), "reports": []}
    if kind == "claim":
        claim = brief_claims.by_id(claims).get(name, {})
        source = claim.get("source", "").partition(":")
        return {"kind": "claim", "label": f"Claim {name}: {claim.get('holder_name')} "
                                          f"({brief_claims.MODALITIES.get(claim.get('modality'), '').lower()})",
                "reports": [source[2]] if source[0] == "report" else []}
    item = context.get(name, {})
    later = " (published after this story was first reported)" if item.get("timing") == "after" else ""
    return {"kind": "context", "label": f"Context: {item.get('publisher') or item.get('source')}{later}",
            "reports": []}


BASIS_LABEL = {"nominal": "nominal", "real": "real (inflation-adjusted)", "not_applicable": None,
               "not_stated": "nominal or real not stated"}
SEASONAL_LABEL = {"seasonally_adjusted": "seasonally adjusted", "not_seasonally_adjusted": "not seasonally adjusted",
                  "not_applicable": None, "not_stated": "seasonal adjustment not stated"}
KIND_LABEL = {"reported": "Reported", "derived": "Calculated here", "reasoning": "General economic reasoning",
              "interpretation": "Interpretation, conditional"}


STATISTIC_LABEL = {"observed": None, "mean": "a mean of survey answers", "median": "a median of survey answers",
                   "other_summary": "a summary statistic", "not_stated": "summary statistic not stated"}
STOCK_FLOW_LABEL = {"stock": "a stock (at a point in time)", "flow_per_month": "a flow over a month",
                    "flow_per_quarter": "a flow over a quarter", "flow_per_year": "a flow over a year",
                    "flow_annual_rate": "a flow at an annual rate",
                    "flow_other_period": "a flow over the period stated",  # econ-calc-0.4
                    "not_applicable": None}
DIRECTION_LABEL = {"as_quoted": None, "consistent": None, "unstated": None,
                   "contradicted": "the quote's words describe a decline but the figure is positive",
                   "unclear": "the cited words do not establish its direction"}


def background(economics: dict, recorded: dict | None) -> dict:
    """The framework notes an explanation was prepared with: its own snapshot (0.2), or, for one saved before
    snapshots, the archived framework with its recorded SHA-256; never today's notes in their place."""
    snapshot = economics.get("framework")
    if snapshot:
        return {"state": "recorded", "notes": snapshot["notes"], "statement": snapshot["statement"],
                "framework_version": snapshot["framework_version"], "framework_sha256": snapshot["framework_sha256"]}
    sha = (recorded or {}).get("framework_sha256")
    found = econ_framework.archived(sha)
    if found is not None:
        used = {row["note"] for row in economics["channels"] if row["note"]}
        return {"state": "recovered", "notes": {name: note for name, note in found["notes"].items() if name in used},
                "statement": found["statement"], "framework_version": found["framework_version"],
                "framework_sha256": found["framework_sha256"]}
    return {"state": "unavailable", "notes": {}, "framework_version": (recorded or {}).get("framework_version"),
            "framework_sha256": sha, "statement": (
                f"The framework notes this explanation was prepared with (framework {str(sha)[:12]}) cannot be "
                "recovered, so their background is not shown; today's notes are not shown in their place.")}


NET_LABEL = "a net percentage: the share of respondents reporting one direction minus the share reporting the other"


def _figure_view(row: dict, claims: dict[str, str] | None = None) -> dict:
    """A figure as readers see it; ``claims`` (a version that records claims) adds what its claim is, or None."""
    sign = row.get("sign")
    stated = econ_fidelity.margin(row)
    statistic = NET_LABEL if row["measure"] == "net_percentage" else STATISTIC_LABEL[row.get("statistic", "observed")]
    claim = {} if claims is None else {"claim_label": claims.get(row["id"])}
    return {"id": row["id"], "display": econ_calc.shown(row), "label": row["label"], "period": row["period"],
            "basis_label": BASIS_LABEL[row["basis"]] if econ_fidelity.shows_basis(row) else None,
            "seasonal_label": SEASONAL_LABEL[row["seasonal"]], "margin": stated["display"] if stated else None,
            "statistic_label": statistic,
            "stock_flow_label": STOCK_FLOW_LABEL[row.get("stock_flow", "not_applicable")],
            "bound": row.get("bound", "exact"), "measure": row["measure"], "quote": row["quote"],
            "vintage": row["vintage"], "kind": "reported",
            "sign_basis": f"Its direction is stated by the quote's words “{row['sign_words']}”."
            if sign == "from_words" else None,
            "direction_warning": DIRECTION_LABEL.get(row.get("direction_check", "as_quoted")),
            "reports": [row["source"].partition(":")[2]] if row["source"].startswith("report:") else [],
            "context": row["source"].partition(":")[2] if row["source"].startswith("context:") else None, **claim}


def reader_view(economics: dict | None, facts: list[dict], recorded: dict | None = None,
                claims: list[dict] | None = None) -> dict | None:
    """The explanation as readers see it: texts rendered with their figures and calculations, each statement with its
    kind and evidence, the framework notes it was prepared with as background, and how it was prepared. ``recorded``
    is the version's preparation record (its ``analysis``), for an explanation saved before snapshots. ``claims``: the
    brief's claims (story-brief-0.4); a figure bound to one is rendered with what it is. A version that records none
    is shown exactly as before."""
    if economics is None:
        return None
    if economics["status"] != "explained":
        return {"analysis_version": economics["analysis_version"], "status": economics["status"],
                "insufficient_reason": economics["insufficient_reason"], "summary": None, "channels": [],
                "second_order": [], "alternatives": [], "watch": [], "figures": [], "calculations": [],
                "assumptions": [], "notes": [], "context": [], "statement": None, "background": None,
                "kinds": KIND_LABEL}
    claim_notes = None if claims is None else brief_claims.notes(economics["figures"], claims)
    rows = {row["id"]: ({**row, "claim_note": claim_notes[row["id"]]} if claim_notes and row["id"] in claim_notes
                        else row) for row in economics["figures"] + economics["calculations"]}
    render = lambda text: econ_fidelity.render(text, rows)  # noqa: E731  (each value with its qualifiers)
    context = {row["item_id"]: row for row in economics["context"]}
    refs = lambda rows: [_ref_view(ref, economics, facts, context, claims) for ref in rows]  # noqa: E731
    found = background(economics, recorded)
    notes = found["notes"]
    used = [name for name in dict.fromkeys(row["note"] for row in economics["channels"]) if name in notes]
    channels = [{"id": row["id"], "scope": row["scope"], "scope_label": SCOPES[row["scope"]],
                 "support": row.get("support"), "support_label": SUPPORTS.get(row.get("support")),
                 "text": render(row["text"]), "steps": [render(step) for step in row["steps"]],
                 "affected": [{**party, "how": render(party["how"])} for party in row["affected"]],
                 "conditions": render(row["conditions"]) if row["conditions"] else None,
                 "horizon": row["horizon"], "horizon_label": HORIZONS[row["horizon"]], "kind": "interpretation",
                 "note": None if not row["note"] else {
                     "id": row["note"], "title": notes[row["note"]]["title"] if row["note"] in notes else
                     f"framework note {row['note']} (not recoverable)"},
                 "basis": refs(row["basis"]),
                 "assumptions": row["assumptions"]} for row in economics["channels"]]
    who = list(dict.fromkeys(party["name"] for row in economics["channels"] for party in row["affected"]))
    return {"analysis_version": economics["analysis_version"], "status": "explained", "insufficient_reason": None,
            "summary": {"stage": economics["change"]["stage"], "stage_label": STAGES[economics["change"]["stage"]],
                        **econ_classification.labels(economics["change"]),
                        "what_changed": render(economics["change"]["text"]),
                        "what_changed_basis": refs(economics["change"]["basis"]),
                        "why_it_matters": render(economics["significance"]["text"]),
                        "why_basis": refs(economics["significance"]["basis"]), "who": who[:6],
                        "main_uncertainty": render(economics["main_uncertainty"])},
            "channels": channels,
            "second_order": [{"id": row["id"], "from": row["from"], "text": render(row["text"]),
                              "conditions": render(row["conditions"]), "horizon": row["horizon"],
                              "horizon_label": HORIZONS[row["horizon"]], "kind": "interpretation",
                              "basis": refs(row["basis"]), "assumptions": row["assumptions"]}
                             for row in economics["second_order"]],
            "alternatives": [{"kind": row["kind"], "label": ALTERNATIVES[row["kind"]], "text": render(row["text"]),
                              "basis": refs(row["basis"]),
                              # 0.6: what supports it and what it assumes; an earlier one shows neither, as before.
                              **({"support": row["support"], "support_label": ALTERNATIVE_SUPPORTS[row["support"]],
                                  "assumptions": row["assumptions"]} if "support" in row else {})}
                             for row in economics["alternatives"]],
            "watch": [{**row, "text": render(row["text"])} for row in economics["watch"]],
            "figures": [_figure_view(row, claim_notes) for row in economics["figures"]],
            "calculations": [{"id": row["id"], "display": econ_calc.shown(row), "label": row["label"],
                              "formula": row["formula"], "inputs": row["inputs"], "period": row["period"],
                              "basis_label": BASIS_LABEL[row["basis"]], "bound": row.get("bound", "exact"),
                              "kind": "derived"} for row in economics["calculations"]],
            "assumptions": [{**row, "text": render(row["text"])} for row in economics["assumptions"]],
            "notes": [{"id": name, "title": notes[name]["title"], "mechanism": notes[name]["mechanism"],
                       "limits": notes[name]["limits"], "sources": notes[name]["sources"], "kind": "reasoning"}
                      for name in used],
            "context": [{"item_id": row["item_id"], "kind": row["kind"],
                         "publisher": row["publisher"] or row["source"], "title": row["title"],
                         "link": row["link"] or row["url"], "published": row["published"], "as_of": row["as_of"],
                         "attribution": row["attribution"] or row["terms"], "role": row.get("role"),
                         "role_label": econ_context.ROLES.get(row.get("role")), "relevance": row.get("relevance"),
                         "retrieved": row.get("retrieved"), "timing": row.get("timing"),
                         "timing_label": econ_context.TIMING.get(row.get("timing")),
                         "retrospective": row.get("timing") == "after"} for row in economics["context"]],
            "statement": found["statement"],
            "background": {key: found[key] for key in ("state", "framework_version", "framework_sha256")},
            "kinds": KIND_LABEL}


ROLE_WORDS = {"event_evidence": "on this development", "comparison": "for comparison", "methodology": "on methodology",
              "benchmark": "an expectations benchmark"}


def context_statement(economics: dict | None) -> str | None:
    """What the explanation read beyond the story's own material, said precisely: quoted passages of a document are
    not the document, and later context is named as such. None when it read nothing more."""
    rows = (economics or {}).get("context") or []
    if not rows:
        return None
    parts, sources = [], {}
    for row in rows:
        if row["kind"] != "publication":
            sources.setdefault(row.get("source") or row.get("publisher"), []).append(row)
    for source, items in sources.items():
        roles = ", ".join(dict.fromkeys(ROLE_WORDS.get(row.get("role"), "as evidence") for row in items))
        parts.append(f"{len(items)} quoted passage{'' if len(items) == 1 else 's'} of {source} ({roles})")
    stories = {row.get("story_title") or row.get("title") for row in rows if row["kind"] == "publication"}
    if stories:
        parts.append(f"the usable material of {len(stories)} other stor{'y' if len(stories) == 1 else 'ies'} "
                     f"({'; '.join(sorted(stories))})")
    text = ("The economic explanation also draws on " + "; ".join(parts) + ". Quoted passages are parts of those "
            "documents; the documents were not otherwise used.")
    later = sum(1 for row in rows if row.get("timing") == "after")
    if later:
        text += (f" {'One of these items was' if later == 1 else f'{later} of these items were'} published after "
                 "this story was first reported: later context, not what was known then.")
    return text
