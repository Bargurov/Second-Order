"""SYNTHETIC inputs for the research-view tests and the browser test server: an invented retained BIS snapshot (see
bis_snapshot_fakes), one invented release page retained under the related-cases approval, and a research file written
against them. Nothing here is BIS's text. Record keys, record hashes and paragraph counts are taken from the synthetic
snapshot as built, so the file binds exactly the bytes written."""
import copy
import hashlib
import json
from pathlib import Path

import bis_snapshot_fakes as fakes
from second_order import bis_snapshot

RESEARCH_ID = "synthetic-policy"
RULE = "/press-release/synthetic-rule-advanced-chips"
UPDATE = "/press-release/synthetic-update-chips-rule"
FIRST = "/press-release/synthetic-repeated-title"
SECOND = "/press-release/synthetic-repeated-title-0"
OTHER = "/press-release/synthetic-not-selected"
RULE_TITLE = "Synthetic Rule on Advanced Chips"
RULE_BODY = ("<p>WASHINGTON, D.C. &mdash; Synthetic: BIS issued a rule adding license requirements for advanced "
             "computing chips.</p><p>Synthetic: the rule is effective on March 2, 2026.</p><p>Synthetic: comments "
             "are due 30 days after publication.</p><p>Synthetic: the text of the rule is available here.</p>"
             "<p>###</p>")
RELATED_APPROVAL = "related-cases-sources-01"
PAGE_FOLDER = "synthetic-rule"


def teasers(update_body: str | None = None) -> list:
    return [
        fakes.teaser(21, RULE_TITLE, RULE, published="2026-01-10T15:00:00+00:00", body=RULE_BODY,
                     created="2026-01-10T15:05:00+00:00", countries=("China",)),
        fakes.teaser(22, "Synthetic Update to the Chips Rule", UPDATE, published="2026-04-01T15:00:00+00:00",
                     body=update_body or ("<p>Synthetic: this rule modifies the rule of January 10, 2026.</p><p>"
                                          "Synthetic: it removes one parameter for chip-making equipment.</p>"
                                          "<p>###</p>"),
                     created="2026-04-01T14:00:00+00:00"),
        fakes.teaser(23, "Synthetic Repeated Title", FIRST, published="2026-05-01T15:00:00+00:00",
                     body="<p>Synthetic first document, about chip-making equipment.</p>",
                     created="2026-05-01T14:00:00+00:00"),
        fakes.teaser(24, "Synthetic Repeated Title", SECOND, published="2026-06-01T15:00:00+00:00",
                     body="<p>Synthetic second, different document.</p>", created="2026-06-01T14:00:00+00:00"),
        fakes.teaser(25, "Synthetic Not Selected Semiconductor Notice", OTHER, published="2026-07-01T15:00:00+00:00",
                     body="<p>Synthetic semiconductor notice that was not selected.</p>",
                     created="2026-07-01T14:00:00+00:00"),
    ]


def release_page() -> bytes:
    return fakes.release_page(RULE_TITLE, "January 10, 2026", RULE_BODY)


def write_sources(root: Path, update_body: str | None = None, page: bytes | None = None) -> dict:
    """The retained folders of both approvals under ``root``, as the research view reads them."""
    bis = fakes.write_snapshot(root / "bis", teasers=teasers(update_body))
    related = root / "related"
    data = release_page() if page is None else page
    (related / PAGE_FOLDER).mkdir(parents=True, exist_ok=True)
    (related / PAGE_FOLDER / "source.html").write_bytes(data)
    run = related / "acquisitions" / RELATED_APPROVAL
    run.mkdir(parents=True, exist_ok=True)
    record = {**fakes.outcome(1, f"https://www.bis.gov{RULE}", PAGE_FOLDER, data), "approval_id": RELATED_APPROVAL,
              "retained": f"data/sector-sources/related-cases/{PAGE_FOLDER}/source.html"}
    (run / "outcome-1.json").write_text(json.dumps(record), encoding="utf-8")
    return {"bis-semis-sources-01": bis, RELATED_APPROVAL: related}


def q(n: int, quote: str) -> dict:
    return {"paragraph": n, "quote": quote}


def st(status: str, text: str, *excerpts, reference=None, stage=None, dates=()) -> dict:
    return {"status": status, "text": text, "excerpts": list(excerpts), "reference": reference, "stage": stage,
            "dates": list(dates)}


def dim(label: str, *statements) -> dict:
    return {"label": label, "statements": list(statements)}


def not_stated(subject: str) -> dict:
    return dim("Not stated in this source", st("not_stated", subject))


def publication(index: dict, id_: str, path: str, short_title: str, dimensions: dict, references=(), page=None,
                cases=()) -> dict:
    record = next(item for item in index["records"] if item["document"]["path"] == path)
    return {"id": id_, "short_title": short_title, "title": record["publisher"]["title"], "url": record["identity"],
            "record": {"key": record["key"], "record_sha256": record["record_sha256"],
                       "paragraphs": len(record["text"]["paragraphs"])},
            "listing": {field: record["listing"][field]["time"] for field in ("published", "created", "changed")},
            "release_page": page, "why_included": f"Synthetic: {short_title.lower()} is part of the test selection.",
            "cases": list(cases), "dimensions": dimensions, "references": list(references)}


def evidence(publication_id: str, paragraph=None, quote=None, field=None, value=None, absent=None) -> dict:
    return {"publication": publication_id, "paragraph": paragraph, "quote": quote, "field": field, "value": value,
            "absent": absent}


def research(sources: dict) -> dict:
    """The SYNTHETIC research file, bound to the synthetic snapshot as written under ``sources``."""
    index = bis_snapshot.build(sources["bis-semis-sources-01"])
    page = release_page()
    rule = publication(index, "synthetic-rule", RULE, "Synthetic chips rule", {
        "instrument": dim("A rule", st("stated", "BIS issued a rule.",
                                       q(1, "BIS issued a rule adding license requirements for advanced computing "
                                            "chips"))),
        "relation": not_stated("Which earlier rule it amends."),
        "scope": dim("Advanced computing chips", st("stated", "License requirements for advanced computing chips.",
                                                    q(1, "adding license requirements for advanced computing chips"))),
        "parties": not_stated("Which destinations the requirements apply to."),
        "supply_chain": dim("Chips", st("interpretation", "Advanced computing chips.",
                                        q(1, "advanced computing chips"), stage="chips")),
        "timing": dim("Effective March 2, 2026; comments 30 days after publication",
                      st("stated", "The rule takes effect on March 2, 2026.",
                         q(2, "the rule is effective on March 2, 2026"),
                         dates=[{"kind": "effective", "value": "2026-03-02", "precision": "day",
                                 "as_stated": "March 2, 2026"}]),
                      st("stated", "Comments are due 30 days after publication.",
                         q(3, "comments are due 30 days after publication"),
                         dates=[{"kind": "comment_deadline", "value": None, "precision": "relative",
                                 "as_stated": "30 days after publication"}]),
                      st("not_stated", "The publication date.")),
        "conditions": dim("In the rule text, not retained",
                          st("referenced_unread", "The conditions are in the rule text.",
                             q(4, "the text of the rule is available here"), reference="synthetic-rule-text")),
    }, references=[{"id": "synthetic-rule-text", "description": "Synthetic rule text",
                    "excerpts": [q(4, "the text of the rule is available here")]}],
        page="synthetic-rule-page",
        cases=[{"kind": "historical", "id": "bis-2022-10-07", "note": "Synthetic link to a committed case."}])
    update = publication(index, "synthetic-update", UPDATE, "Synthetic update", {
        "instrument": dim("A rule modifying the January 10, 2026 rule",
                          st("stated", "A rule that modifies the earlier rule.",
                             q(1, "this rule modifies the rule of January 10, 2026"))),
        "relation": dim("Modifies the January 10, 2026 rule",
                        st("stated", "It says it modifies the rule of January 10, 2026.",
                           q(1, "this rule modifies the rule of January 10, 2026"))),
        "scope": dim("One parameter for chip-making equipment",
                     st("stated", "It removes one parameter.", q(2, "it removes one parameter for chip-making "
                                                                    "equipment"))),
        "parties": not_stated("Which parties it applies to."),
        "supply_chain": dim("Equipment", st("interpretation", "Chip-making equipment.",
                                            q(2, "chip-making equipment"), stage="equipment")),
        "timing": not_stated("An effective date."),
        "conditions": not_stated("Conditions."),
    })
    twins = []
    for id_, path, quote in (("synthetic-first", FIRST, "Synthetic first document, about chip-making equipment."),
                             ("synthetic-second", SECOND, "Synthetic second, different document.")):
        twins.append(publication(index, id_, path, f"Synthetic {id_.split('-')[1]} of two same-titled releases", {
            "instrument": dim("A document", st("stated", "A document.", q(1, quote))),
            **{name: not_stated("Not given.") for name in ("relation", "scope", "parties", "timing", "conditions")},
            "supply_chain": not_stated("No stage."),
        }))
    other = next(item for item in index["records"] if item["document"]["path"] == OTHER)
    return {
        "research_version": "policy-research-0.1", "id": RESEARCH_ID, "title": "Synthetic policy comparison",
        "question": "Synthetic: how do these invented releases relate?",
        "scope_note": "A synthetic comparison for tests; not BIS's text.",
        "corpus_notes": ["Synthetic: one publisher's invented releases."],
        "method_note": "Synthetic: chosen to exercise every state.",
        "snapshot": {"approval_id": "bis-semis-sources-01", "attempt": index["package"]["attempt"],
                     "url": index["package"]["url"], "sha256": index["package"]["sha256"],
                     "bytes": index["package"]["bytes"], "retrieved_at": index["package"]["retrieved_at"],
                     "extractor_version": index["extractor_version"]},
        "release_pages": [{"id": "synthetic-rule-page", "approval_id": RELATED_APPROVAL, "attempt": 1,
                           "folder": PAGE_FOLDER, "url": f"https://www.bis.gov{RULE}",
                           "sha256": hashlib.sha256(page).hexdigest(), "bytes": len(page),
                           "retrieved_at": fakes.RETRIEVED, "dateline": "January 10, 2026"}],
        "publications": [rule, update] + twins,
        "comparisons": [
            {"id": "synthetic-stated-change", "kind": "stated_change",
             "question": "Does the update say it changes the rule?", "publications": ["synthetic-rule", "synthetic-update"],
             "observation": "The update says it modifies the rule of January 10, 2026.",
             "evidence": [evidence("synthetic-rule", 1, "BIS issued a rule adding license requirements for advanced "
                                                        "computing chips"),
                          evidence("synthetic-rule", field="published", value=rule["listing"]["published"]),
                          evidence("synthetic-update", 1, "this rule modifies the rule of January 10, 2026")],
             "why": "The later text states the relationship itself.",
             "unknown": "Synthetic: what changed in detail.", "would_establish": "Synthetic: the rule texts."},
            {"id": "synthetic-same-title", "kind": "different_subjects",
             "question": "Are the two same-titled releases one document?",
             "publications": ["synthetic-first", "synthetic-second"],
             "observation": "They share a title but carry different texts.",
             "evidence": [evidence("synthetic-first", 1, "Synthetic first document, about chip-making equipment."),
                          evidence("synthetic-second", 1, "Synthetic second, different document."),
                          evidence("synthetic-second", absent="chip-making")],
             "why": "Merging them by title would lose one document.",
             "unknown": "Synthetic: why they share a title.", "would_establish": "Synthetic: the publisher's note."},
        ],
        "not_included": [{"title": other["publisher"]["title"], "url": other["identity"], "key": other["key"],
                          "record_sha256": other["record_sha256"], "listed": other["listing"]["published"]["time"],
                          "reason": "Synthetic: considered and not selected.",
                          "case": {"kind": "library", "id": "bis-2026-07-10", "note": "Synthetic case link."}}],
        "not_claimed": ["That the synthetic rule caused anything."],
        "provenance": {"prepared_by": "Synthetic test fixture", "prepared_on": "2026-10-12",
                       "method": "Synthetic: written by the test fixture.", "ai_assisted": True,
                       "human_review": "not_reviewed", "research_use": "excluded"},
    }


def write_research(content: Path, body: dict) -> Path:
    folder = content / body["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "research.json").write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return content


def changed(body: dict, change) -> dict:
    """A deep copy of ``body`` with ``change`` applied to it."""
    copied = copy.deepcopy(body)
    change(copied)
    return copied
