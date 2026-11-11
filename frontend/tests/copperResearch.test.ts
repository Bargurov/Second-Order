// The copper research view, against replies the backend serves (captured by tests/test_copper_research_api.py into
// fixtures/copper-research-*.json): no note, four notes, and four notes with one changed document. The reader is
// fail-closed and names the place and rule of each refusal, so each test proves the rule it is about. A note save is
// one POST; a lost reply is settled from the saved notes and never sent again. Every note text here is a marked test
// value, never a view of the owner's.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { bindAdminAccount } from "../src/admin/adminApi.ts";
import {
  closedReason, copperResearchRefusal, fetchCopperResearch, HISTORICAL, latestNoteAbout, noteBody, notesAbout,
  openQuestions, priceLine, RESEARCH_NOTE_HEADER, SAME_MEASURE, saveNote, settleNote, subjectLabel, subjectPath,
  type ComparisonView, type CopperResearchView, type NoteBody, type NoteDraft, type NoteView, type Subject,
} from "../src/copperResearch.ts";

type Name = "empty" | "available" | "withheld" | "changed";
const fixture = (name: Name): CopperResearchView =>
  JSON.parse(readFileSync(new URL(`./fixtures/copper-research-${name}.json`, import.meta.url), "utf8"));
const copy = <T>(value: T): T => structuredClone(value);
const ID = "synthetic-annual-to-quarter";
const COMPARISON = `comparisons[${ID}]`;
const ROW = `${COMPARISON}.rows[0]`;
const NOTE = "notes.items[0]";
const loose = (value: unknown) => value as Record<string, unknown>;

function refusalOf(name: Name, change: (view: CopperResearchView) => void): string | null {
  const view = fixture(name);
  change(view);
  return copperResearchRefusal(view);
}
/** The reply is refused at `place`, and the refusal names the place and rule, never a served value. */
function refusedAt(place: string, name: Name, change: (view: CopperResearchView) => void): void {
  const refusal = refusalOf(name, change);
  assert.ok(refusal?.startsWith(`${place}: `), `expected a refusal at ${place}, got ${refusal}`);
  assert.doesNotMatch(refusal, /Synthetic|PTFI|TEST VALUE|85|80/, "a refusal names a place, never a value");
}
/** The comparison and its subject, changed together (the reader holds the two to one state). */
function both(view: CopperResearchView, change: (item: ComparisonView | Subject) => void): void {
  change(view.comparisons[0]);
  change(view.subjects.find((item) => item.kind === "comparison")!);
}

// ---------------------------------------------------------------- the reader

test("reads each captured fixture", () => {
  for (const name of ["empty", "available", "withheld", "changed"] as const) {
    assert.equal(copperResearchRefusal(fixture(name)), null, name);
  }
  assert.equal(fixture("empty").notes.items.length, 0);
  assert.equal(fixture("available").notes.items.length, 4);
  assert.equal(fixture("withheld").comparisons[0].state, "needs_revalidation");
  // A newer version of the comparison, one cited record edited and one removed: states no other fixture holds.
  const changed = fixture("changed");
  assert.equal(changed.comparisons[0].state, "evidence_changed");
  assert.deepEqual(changed.comparisons[0].rows.map((row) => row.later.state), ["record_gone", "record_changed"]);
  assert.deepEqual(changed.notes.items.map((note) => note.state),
    ["earlier_basis", "earlier_basis", "earlier_basis", "current"]);
});

test("refuses the wrong version, a provider call and an extra field of the reply", () => {
  refusedAt("view_version", "available", (view) => { view.view_version = "copper-research-view-0.2"; });
  refusedAt("provider_called", "available", (view) => { loose(view).provider_called = true; });
  refusedAt("provider_called", "available", (view) => { loose(view).provider_called = null; });
  refusedAt("reply", "available", (view) => { loose(view).extra = 1; });
  refusedAt("reply", "available", (view) => { delete loose(view).desk; });
  assert.equal(copperResearchRefusal(null), "reply: does not have exactly the expected fields");
});

test("refuses a row that carries a change: no row computes one", () => {
  for (const field of ["change_pct", "change", "difference", "ratio"]) {
    refusedAt(ROW, "available", (view) => { loose(view.comparisons[0].rows[0])[field] = "-5"; });
  }
  assert.match(refusalOf("available", (view) => { loose(view.comparisons[0].rows[0]).change_pct = "-5"; }) ?? "",
    /rows\[0\]: does not have exactly the expected fields$/);
  refusedAt(`${ROW}.later`, "available", (view) => { loose(view.comparisons[0].rows[0].later).change = "5 points"; });
});

test("refuses any object without exactly its expected fields", () => {
  refusedAt("comparisons[0]", "available", (view) => { loose(view.comparisons[0]).summary = "TEST VALUE."; });
  refusedAt(`${COMPARISON}.earlier`, "available", (view) => { delete loose(view.comparisons[0].earlier).form; });
  refusedAt(`${COMPARISON}.prices`, "available", (view) => { loose(view.comparisons[0].prices).change = "1.79"; });
  refusedAt(`${COMPARISON}.prices.figures[0]`, "available", (view) => {
    loose(view.comparisons[0].prices.figures[0]).change_pct = "37.7";
  });
  refusedAt(`${COMPARISON}.prices.figures[0].period`, "available", (view) => {
    loose(view.comparisons[0].prices.figures[0].period).days = 365;
  });
  refusedAt("desk", "available", (view) => { loose(view.desk).score = 1; });
  refusedAt("desk.pages[1]", "available", (view) => { loose(view.desk.pages[1]).score = 1; });
  refusedAt("subjects[0]", "available", (view) => { loose(view.subjects[0]).score = 1; });
  refusedAt("notes", "available", (view) => { loose(view.notes).score = 1; });
  refusedAt(NOTE, "available", (view) => { loose(view.notes.items[0]).score = 1; });
  refusedAt(`${NOTE}.expectation`, "available", (view) => { loose(view.notes.items[0].expectation).outcome = "met"; });
  refusedAt(`${NOTE}.basis`, "available", (view) => { loose(view.notes.items[0].basis).documents = []; });
  refusedAt(`${NOTE}.basis_documents[0]`, "available", (view) => {
    delete loose(view.notes.items[0].basis_documents[0]).detail;
  });
});

test("holds the same three sentences as SAME_MEASURE in copper_research_view.py", () => {
  const source = readFileSync(new URL("../../second_order/copper_research_view.py", import.meta.url), "utf8");
  const block = /SAME_MEASURE = \{([^}]*)\}/.exec(source)?.[1] ?? "";
  const served = Object.fromEntries([...block.replace(/"\s*\n\s*"/g, "").matchAll(/"(\w+)":\s*"([^"]*)"/g)]
    .map((found) => [found[1], found[2]]));
  assert.deepEqual(served, SAME_MEASURE);
  assert.equal(Object.keys(SAME_MEASURE).length, 3);
});

test("the committed comparisons keep what the reader requires of the assistant's text", () => {
  // The fixtures are synthetic; these rules are also held to the committed content the real page serves.
  const folder = new URL("../../content/theses/copper/comparisons/", import.meta.url);
  const ids = readdirSync(folder);
  assert.ok(ids.length >= 1);
  for (const id of ids) {
    const index = JSON.parse(readFileSync(new URL(`${id}/index.json`, folder), "utf8"));
    for (const entry of index.versions) {
      const version = JSON.parse(readFileSync(new URL(`${id}/${entry.file}`, folder), "utf8"));
      const where = `${id}/${entry.file}`;
      assert.match(id, /^[a-z0-9]+(?:-[a-z0-9]+)*$/, where);
      assert.equal(version.provenance.ai_assisted, true, where);
      assert.doesNotMatch(version.title, /→|⟶|->/, where);
      for (const row of version.rows) {
        assert.doesNotMatch(row.label, /[0-9]|→|⟶|->/, `${where} ${row.id}`);
        assert.doesNotMatch(row.note ?? "", /→|⟶|->/, `${where} ${row.id}`);
        assert.ok(Object.hasOwn(SAME_MEASURE, row.same_measure), `${where} ${row.id}`);
        assert.ok(row.note !== null || row.same_measure === "not_applicable", `${where} ${row.id}`);
      }
    }
  }
});

test("refuses a row sentence that is not the fixed sentence of its same_measure", () => {
  refusedAt(`${ROW}.sentence`, "available", (view) => {
    view.comparisons[0].rows[0].sentence = "The later line is lower than the earlier one.";
  });
  // Another answer's fixed sentence is refused too: the sentence follows the row's own answer.
  refusedAt(`${ROW}.sentence`, "available", (view) => { view.comparisons[0].rows[0].sentence = SAME_MEASURE.no; });
  refusedAt(`${ROW}.same_measure`, "available", (view) => { loose(view.comparisons[0].rows[0]).same_measure = "yes"; });
  assert.equal(refusalOf("available", (view) => {
    view.comparisons[0].rows[0].same_measure = "no";
    view.comparisons[0].rows[0].sentence = SAME_MEASURE.no;
  }), null);
});

test("refuses a side that is not verified but carries a quote, and a verified side without one", () => {
  refusedAt(`${ROW}.later`, "withheld", (view) => {
    view.comparisons[0].rows[0].later.quote = "A quote that must stay withheld.";
  });
  assert.match(refusalOf("withheld", (view) => { view.comparisons[0].rows[1].later.quote = "A withheld quote."; })
    ?? "", /rows\[1\]\.later: carries a quote while it is not verified$/);
  // A record that changed since it was pinned is withheld whole as well, though its document verifies.
  refusedAt(`${ROW}.later`, "available", (view) => {
    Object.assign(view.comparisons[0].rows[0].later, { state: "record_changed", problem: "Withheld: it changed" });
  });
  refusedAt(`${ROW}.earlier.quote`, "available", (view) => { view.comparisons[0].rows[0].earlier.quote = null; });
  refusedAt(`${ROW}.earlier.problem`, "available", (view) => {
    view.comparisons[0].rows[0].earlier.problem = "Withheld: a problem on a verified side";
  });
  refusedAt(`${ROW}.later.problem`, "withheld", (view) => { view.comparisons[0].rows[0].later.problem = null; });
  // A side follows its document: verified while the document is changed, or another state than its document's.
  refusedAt(`${ROW}.later.state`, "withheld", (view) => {
    Object.assign(view.comparisons[0].rows[0].later, { state: "verified", quote: "A quote.", problem: null });
  });
  refusedAt(`${ROW}.later.state`, "withheld", (view) => { view.comparisons[0].rows[0].later.state = "missing"; });
  refusedAt(`${ROW}.later.document`, "withheld", (view) => {
    view.comparisons[0].rows[0].later.document.state = "verified";
  });
  refusedAt(`${ROW}.later.document`, "available", (view) => {
    view.comparisons[0].rows[0].later.document = copy(view.comparisons[0].rows[0].earlier.document);
  });
});

test("refuses the assistant's note on a row while one of its sides is not verified", () => {
  // The note says what each line states, so it is withheld with a withheld line, with or without a digit.
  const withheld = fixture("withheld").comparisons[0].rows[0];
  assert.deepEqual([withheld.note, withheld.note_withheld, withheld.later.state], [null, true, "changed"]);
  refusedAt(`${ROW}.note`, "withheld", (view) => {
    Object.assign(view.comparisons[0].rows[0], { note_withheld: false,
      note: "The earlier line is about production; the later about capacity." });
  });
  refusedAt(`${ROW}.note`, "withheld", (view) => {
    view.comparisons[0].rows[0].note = "The earlier line is about 85% of production; the later about capacity.";
  });
  // The same note is read while both sides verify.
  assert.equal(refusalOf("available", (view) => {
    view.comparisons[0].rows[0].note = "The earlier line is about 85% of production; the later about capacity.";
  }), null);
  refusedAt(`${ROW}.note_withheld`, "available", (view) => {
    Object.assign(view.comparisons[0].rows[0], { note: null, note_withheld: true });
  });
  refusedAt(`${ROW}.note`, "available", (view) => { view.comparisons[0].rows[0].note = null; });
  refusedAt(`${ROW}.label`, "available", (view) => { view.comparisons[0].rows[0].label = "From 85% to 80%"; });
});

test("refuses a price figure that is available without display and period, or withheld with a display", () => {
  const FIGURES = `${COMPARISON}.prices.figures`;
  refusedAt(`${FIGURES}[0]`, "available", (view) => { view.comparisons[0].prices.figures[0].display = null; });
  refusedAt(`${FIGURES}[0]`, "available", (view) => { view.comparisons[0].prices.figures[0].period = null; });
  refusedAt(`${FIGURES}[0]`, "available", (view) => { view.comparisons[0].prices.figures[0].unit = null; });
  refusedAt(`${FIGURES}[0]`, "available", (view) => {
    view.comparisons[0].prices.figures[0].problem = "Not shown: a problem beside a figure";
  });
  assert.equal(fixture("withheld").comparisons[0].prices.figures[1].state, "withheld");
  refusedAt(`${FIGURES}[1].display`, "withheld", (view) => { view.comparisons[0].prices.figures[1].display = "6.54"; });
  refusedAt(`${FIGURES}[1].problem`, "withheld", (view) => { view.comparisons[0].prices.figures[1].problem = null; });
  refusedAt(`${FIGURES}[1].state`, "withheld", (view) => {
    loose(view.comparisons[0].prices.figures[1]).state = "stale";
  });
  refusedAt(`${FIGURES}[0].period`, "available", (view) => {
    view.comparisons[0].prices.figures[0].period!.end = "2024-12-31";
  });
  refusedAt(FIGURES, "available", (view) => {
    view.comparisons[0].prices.figures[1].id = view.comparisons[0].prices.figures[0].id;
  });
});

test("refuses a covered_to that is not the latest period end of the available figures", () => {
  const PRICES = `${COMPARISON}.prices`;
  refusedAt(`${PRICES}.covered_to`, "available", (view) => { view.comparisons[0].prices.covered_to = "2026-11-06"; });
  refusedAt(`${PRICES}.covered_to`, "available", (view) => { view.comparisons[0].prices.covered_to = null; });
  // The withheld figure's period no longer counts: the fixture's day is the 10-K's, and the 10-Q's is refused.
  assert.equal(fixture("withheld").comparisons[0].prices.covered_to, "2025-12-31");
  refusedAt(`${PRICES}.covered_to`, "withheld", (view) => { view.comparisons[0].prices.covered_to = "2026-09-30"; });
  refusedAt(`${PRICES}.text`, "available", (view) => {
    view.comparisons[0].prices.text = "Retained prices cover up to 2026-11-06. No retained price covers a later date.";
  });
  // With no available figure nothing is covered, and the fixed sentence says so.
  const none = (view: CopperResearchView) => {
    for (const figure of view.comparisons[0].prices.figures) {
      Object.assign(figure, { state: "withheld", display: null, period: null, problem: "Not shown: a test problem" });
    }
    view.comparisons[0].prices.covered_to = null;
  };
  refusedAt(`${PRICES}.text`, "available", none);
  assert.equal(refusalOf("available", (view) => {
    none(view);
    view.comparisons[0].prices.text = "No retained price can be shown on this machine.";
  }), null);
});

test("refuses a historical comparison without the fixed historical sentence", () => {
  const PLACE = `${COMPARISON}.historical_note`;
  refusedAt(PLACE, "available", (view) => { view.comparisons[0].historical_note = null; });
  refusedAt(PLACE, "available", (view) => { view.comparisons[0].historical_note = "Historical."; });
  refusedAt(PLACE, "available", (view) => { view.comparisons[0].historical = false; });
  refusedAt(PLACE, "available", (view) => { loose(view.comparisons[0]).historical = "yes"; });
  assert.equal(fixture("available").comparisons[0].historical_note, HISTORICAL);
  assert.equal(refusalOf("available", (view) => {
    Object.assign(view.comparisons[0], { historical: false, historical_note: null });
  }), null);
});

test("refuses pages that are not the five expected ids and paths, in order", () => {
  refusedAt("desk.pages[0]", "available", (view) => { view.desk.pages.reverse(); });
  refusedAt("desk.pages[2]", "available", (view) => { view.desk.pages[2].path = "/companies/other"; });
  refusedAt("desk.pages[3]", "available", (view) => { view.desk.pages[3].id = "nickel"; });
  refusedAt("desk.pages[1]", "available", (view) => { view.desk.pages[1].path = "https://example.org/"; });
  refusedAt("desk.pages", "available", (view) => { view.desk.pages.pop(); });
  refusedAt("desk.pages", "available", (view) => { view.desk.pages.push(copy(view.desk.pages[0])); });
  refusedAt("desk.pages[2]", "available", (view) => { view.desk.pages[2].problem = "A problem beside a status."; });
  // A line that cannot be read is served as a problem, and the other lines are still read.
  assert.equal(refusalOf("available", (view) => {
    Object.assign(view.desk.pages[2], { status: null, problem: "This page's line could not be read on this machine." });
  }), null);
});

test("refuses a comparison whose state is milder than its documents and lines give, or unlike its subject's", () => {
  refusedAt(`${COMPARISON}.state`, "withheld", (view) => both(view, (item) => {
    Object.assign(item, { state: "available", reasons: [] });
  }));
  refusedAt(`${COMPARISON}.state`, "withheld", (view) => both(view, (item) => { item.state = "evidence_changed"; }));
  refusedAt(`${COMPARISON}.reasons`, "withheld", (view) => { view.comparisons[0].reasons = []; });
  refusedAt(`${COMPARISON}.reasons`, "available", (view) => { view.comparisons[0].reasons = ["A reason."]; });
  refusedAt(`${COMPARISON}.later.state`, "withheld", (view) => { view.comparisons[0].later.state = "verified"; });
  // The page's fixed mark says the assistant prepared the comparison: the reply says so by a flag (the content schema
  // requires it), and the line naming who prepared it is free text.
  refusedAt(`${COMPARISON}.ai_assisted`, "available", (view) => { view.comparisons[0].ai_assisted = false; });
  refusedAt(`${COMPARISON}.prepared_by`, "available", (view) => { view.comparisons[0].prepared_by = ""; });
  assert.equal(refusalOf("available", (view) => { view.comparisons[0].prepared_by = "Claude, an AI draft"; }), null);
  // The form opens by the subject's state, so a subject that is open while its comparison is closed is refused.
  refusedAt(`subjects[comparison:${ID}]`, "withheld", (view) => {
    Object.assign(view.subjects[2], { state: "available", reasons: [] });
  });
  refusedAt(`subjects[comparison:${ID}]`, "available", (view) => { view.subjects[2].sha256 = "0".repeat(64); });
  refusedAt(COMPARISON, "available", (view) => { view.subjects.pop(); view.notes = fixture("empty").notes; });
  refusedAt("subjects[chain:synthetic-world-chain].reasons", "withheld", (view) => { view.subjects[1].reasons = []; });
  refusedAt("subjects[thesis:copper].state", "available", (view) => { view.subjects[0].state = "thesis_newer"; });
  refusedAt("subjects", "available", (view) => { view.subjects.push(copy(view.subjects[0])); });
});

test("refuses an arrow in the assistant's text and in served problems and reasons, never in a quote or a note", () => {
  for (const arrow of ["→", "⟶", "->"]) {
    const at = (place: string, name: Name, change: (view: CopperResearchView) => void) => {
      assert.equal(refusalOf(name, change), `${place}: holds an arrow character`, `${place} ${arrow}`);
    };
    at(`${COMPARISON}.title`, "available", (view) => both(view, (item) => { item.title = `Annual ${arrow} quarter`; }));
    at(`${ROW}.label`, "available", (view) => { view.comparisons[0].rows[0].label = `Before ${arrow} after`; });
    at(`${ROW}.note`, "available", (view) => { view.comparisons[0].rows[0].note = `Production ${arrow} capacity.`; });
    at(`${COMPARISON}.reasons[0]`, "withheld", (view) => both(view, (item) => { item.reasons[0] += ` ${arrow}`; }));
    at(`${ROW}.later.problem`, "withheld", (view) => { view.comparisons[0].rows[0].later.problem += ` ${arrow}`; });
    at(`${NOTE}.differs[0]`, "withheld", (view) => { view.notes.items[0].differs[0] += ` ${arrow}`; });
    // The source's words and the owner's own are never scanned for one.
    assert.equal(refusalOf("available", (view) => {
      view.comparisons[0].rows[0].earlier.quote += ` ${arrow} and more`;
      view.notes.items[0].text = `TEST VALUE: the earlier line ${arrow} the later line.`;
      view.notes.items[0].question = `TEST VALUE: does it go ${arrow} or back?`;
    }), null, arrow);
  }
});

test("refuses a notes history that is invalid but holds items or a latest id", () => {
  const invalid = (view: CopperResearchView) => {
    view.notes.state = "invalid";
    view.notes.problem = "The saved notes are inconsistent: note 1 does not follow the one before it";
  };
  refusedAt("notes.items", "available", invalid);
  refusedAt("notes.items", "available", (view) => { invalid(view); view.notes.items = []; });
  assert.equal(refusalOf("available", (view) => { invalid(view); view.notes.items = []; view.notes.latest = null; }),
    null);
  refusedAt("notes.problem", "available", (view) => { invalid(view); view.notes.problem = null; });
  refusedAt("notes.problem", "available", (view) => { view.notes.problem = "A problem in a valid history."; });
  refusedAt("notes.state", "available", (view) => { loose(view.notes).state = "unknown"; });
});

test("refuses notes whose parent ids or sequence do not chain, and a latest that is not the last note", () => {
  refusedAt("notes.items[1].parent_note_id", "available", (view) => { view.notes.items[1].parent_note_id = null; });
  refusedAt("notes.items[0].parent_note_id", "available", (view) => {
    view.notes.items[0].parent_note_id = view.notes.items[3].note_id;
  });
  refusedAt("notes.items[2].sequence", "available", (view) => { view.notes.items[2].sequence = 4; });
  refusedAt("notes.items[0].parent_note_id", "available", (view) => { view.notes.items.reverse(); });
  refusedAt("notes.latest", "available", (view) => { view.notes.latest = view.notes.items[0].note_id; });
  refusedAt("notes.latest", "available", (view) => { view.notes.latest = null; });
  refusedAt("notes.latest", "empty", (view) => { view.notes.latest = "a".repeat(64); });
  refusedAt("notes.items[3].note_id", "available", (view) => { view.notes.items[3].note_id = "not-an-id"; });
});

test("refuses a followed note that is not an earlier one about the same subject, and a wrong followed_by", () => {
  const view = fixture("available");
  assert.equal(view.notes.items[1].follows, view.notes.items[0].note_id);
  assert.equal(view.notes.items[0].followed_by, view.notes.items[1].note_id);
  const follows = (at: number, earlier: number) => (one: CopperResearchView) => {
    one.notes.items[at].follows = one.notes.items[earlier].note_id;
  };
  refusedAt("notes.items[1].follows", "available", follows(1, 3));  // A later note.
  refusedAt("notes.items[2].follows", "available", follows(2, 0));  // A note about another subject.
  refusedAt("notes.items[0].followed_by", "available", (one) => { one.notes.items[0].followed_by = null; });
  refusedAt("notes.items[3].followed_by", "available", (one) => {
    one.notes.items[3].followed_by = one.notes.items[0].note_id;
  });
});

test("refuses a masked flag that does not follow from the basis documents' states", () => {
  refusedAt(`${NOTE}.masked`, "withheld", (view) => { view.notes.items[0].masked = false; });
  refusedAt(`${NOTE}.masked`, "available", (view) => { view.notes.items[0].masked = true; });
  refusedAt(`${NOTE}.masked`, "available", (view) => { view.notes.items[0].basis_documents[1].state = "changed"; });
  refusedAt(`${NOTE}.mask_reason`, "withheld", (view) => { view.notes.items[0].mask_reason = null; });
  refusedAt(`${NOTE}.basis_documents`, "available", (view) => { view.notes.items[0].basis_documents = []; });
  // The thesis note rests on other documents: it stays unmasked while the 10-Q fails.
  assert.equal(fixture("withheld").notes.items[3].masked, false);
});

test("refuses a masked note whose text, expectation or question still holds a figure outside step references", () => {
  const masked = fixture("withheld").notes.items[0];
  assert.equal(masked.text, "TEST VALUE, not the owner's view: the two lines may not be one measure; "
    + "[figure withheld] against [figure withheld].");
  refusedAt(`${NOTE}.text`, "withheld", (view) => {
    view.notes.items[0].text = "TEST VALUE, not the owner's view: [figure withheld] against 80%.";
  });
  refusedAt(`${NOTE}.expectation.text`, "withheld", (view) => {
    view.notes.items[0].expectation!.text = "TEST VALUE, not the owner's view: a move of 5% before the next report.";
  });
  refusedAt(`${NOTE}.question`, "withheld", (view) => {
    view.notes.items[0].question = "TEST VALUE: does the next annual report keep the 80% line?";
  });
  // A step reference of a chain note is not a figure, by the step count the server names; elsewhere it is one.
  const chain = fixture("withheld").notes.items[2];
  assert.deepEqual([chain.about.kind, chain.steps, chain.text],
    ["chain", 5, "TEST VALUE: see step 3 and the [figure withheld]."]);
  refusedAt("notes.items[2].text", "withheld", (view) => { view.notes.items[2].text = "TEST VALUE: see step 9."; });
  refusedAt("notes.items[2].text", "withheld", (view) => { view.notes.items[2].steps = 2; });
  refusedAt(`${NOTE}.text`, "withheld", (view) => { view.notes.items[0].text = "TEST VALUE: see step 3."; });
  refusedAt(`${NOTE}.steps`, "withheld", (view) => { view.notes.items[0].steps = 5; });
  // The same texts are read while every basis document verifies.
  assert.equal(refusalOf("available", (view) => { view.notes.items[0].text = "TEST VALUE: 85% against 80%."; }), null);
});

test("refuses a note that is current with reasons, or on an earlier basis without any", () => {
  refusedAt(`${NOTE}.state`, "available", (view) => { view.notes.items[0].state = "earlier_basis"; });
  refusedAt(`${NOTE}.state`, "withheld", (view) => { view.notes.items[0].state = "current"; });
  refusedAt(`${NOTE}.state`, "available", (view) => { view.notes.items[0].differs = ["A reason on a current note."]; });
  refusedAt(`${NOTE}.state`, "available", (view) => { loose(view.notes.items[0]).state = "settled"; });
  // What differs is the subject's own reasons while the note names its current version, and never empty otherwise.
  refusedAt(`${NOTE}.differs`, "withheld", (view) => { view.notes.items[0].differs = ["Another reason."]; });
  refusedAt(`${NOTE}.differs`, "available", (view) => {
    both(view, (item) => { item.sha256 = "1".repeat(64); });
  });
  refusedAt(`${NOTE}.subject_title`, "available", (view) => { view.notes.items[0].subject_title = "Another title"; });
  refusedAt(`${NOTE}.basis.comparison`, "available", (view) => { view.notes.items[0].basis.comparison!.id = "other"; });
});

test("refuses an expectation whose state is not not_yet_checked", () => {
  for (const state of ["met", "missed", "checked", null]) {
    refusedAt(`${NOTE}.expectation.state`, "available", (view) => {
      loose(view.notes.items[0].expectation).state = state;
    });
  }
  refusedAt(`${NOTE}.expectation.status`, "available", (view) => {
    view.notes.items[0].expectation!.status = "Checked: the expectation was met.";
  });
  refusedAt(`${NOTE}.expectation`, "available", (view) => {
    view.notes.items[0].expectation!.check_by = "28/02/2027";
  });
  // The server's two lines: not yet checked, and the same once its check-by date has passed.
  const passed = "Not yet checked: nothing retained after this note was saved has been compared with it. Its check-by "
    + "date has passed.";
  assert.equal(refusalOf("available", (view) => { view.notes.items[0].expectation!.status = passed; }), null);
  refusedAt(`${NOTE}.expectation.status`, "available", (view) => {
    Object.assign(view.notes.items[0].expectation!, { status: passed, check_by: null });
  });
});

test("refuses a hindsight sentence that does not follow from the saving day and the later publication's date", () => {
  const PLACE = `${NOTE}.hindsight`;
  assert.equal(fixture("available").notes.items[0].hindsight,
    "Written after both publications were known: saved on 2026-11-10, the later publication is dated 2026-11-06.");
  refusedAt(PLACE, "available", (view) => { view.notes.items[0].hindsight = null; });
  refusedAt(PLACE, "available", (view) => {
    view.notes.items[0].hindsight = view.notes.items[0].hindsight!.replace("2026-11-10", "2026-11-01");
  });
  refusedAt(PLACE, "available", (view) => {
    view.notes.items[0].hindsight = view.notes.items[0].hindsight!.replace("2026-11-06", "2026-11-09");
  });
  refusedAt("notes.items[2].hindsight", "available", (view) => {
    view.notes.items[2].hindsight = view.notes.items[0].hindsight;
  });
  refusedAt(`${NOTE}.saved_at`, "available", (view) => { view.notes.items[0].saved_at = "yesterday"; });
  // A note saved before the later publication's date carries no such sentence.
  assert.equal(refusalOf("available", (view) => {
    for (const note of view.notes.items.slice(0, 2)) {
      Object.assign(note, { saved_at: "2026-11-05T09:00:00+00:00", hindsight: null });
    }
  }), null);
});

// ---------------------------------------------------------------- the save

type Call = { url: string; init: RequestInit };

async function withFetch<T>(fake: typeof fetch, run: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = fake;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}
const replying = (status: number, body: unknown, seen: Call[] = []) => (async (input: RequestInfo | URL,
  init?: RequestInit) => {
  seen.push({ url: String(input), init: init ?? {} });
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}) as typeof fetch;

const TEXT = "TEST VALUE: a note written for this test.";
const EXPECTATION = "TEST VALUE: an expectation written for this test.";
const QUESTION = "TEST VALUE: a question written for this test?";
const draft = (over: Partial<NoteDraft> = {}): NoteDraft =>
  ({ text: TEXT, expectation: "", checkBy: "", question: "", follows: null, ...over });
const subjectOf = (view: CopperResearchView, kind: Subject["kind"]): Subject =>
  view.subjects.find((item) => item.kind === kind)!;
/** The record the server answers a save with (research_notes.save): the sent fields, its basis, account and time. */
const savedFrom = (body: NoteBody, sequence: number) => ({
  record_version: "research-note-0.1", note_id: "a".repeat(64), parent_note_id: body.parent_note_id, sequence,
  about: body.about, follows: body.follows, text: body.text, expectation: body.expectation, question: body.question,
  basis: { [body.about.kind]: { id: body.about.id, sha256: body.subject_sha256, version: 1 },
           evidence_sha256: "b".repeat(64), documents: [] },
  account: { user_id: "local-operator", username: "operator" }, saved_at: "2026-11-11T09:00:00+00:00",
});

test("fetches the view and reads it fail-closed", async () => {
  const seen: Call[] = [];
  const loaded = await withFetch(replying(200, fixture("available"), seen), () => fetchCopperResearch());
  assert.equal(loaded.state, "ready");
  assert.equal(seen[0].url, "/api/theses/copper/research");
  assert.equal(seen[0].init.method, undefined);
  assert.deepEqual(await withFetch(replying(503, { detail: "No thesis" }), () => fetchCopperResearch()),
    { state: "error", message: "No thesis" });
  const bad = fixture("available");
  loose(bad.comparisons[0].rows[0]).change_pct = "-5";
  assert.deepEqual(await withFetch(replying(200, bad), () => fetchCopperResearch()), { state: "error",
    message: `The reply could not be read by this page (${ROW}: does not have exactly the expected fields).` });
  const down = await withFetch((async () => { throw new TypeError("refused"); }) as typeof fetch,
    () => fetchCopperResearch());
  assert.equal(down.state, "error");
});

test("builds the exact body of a note save", () => {
  const view = fixture("available");
  const comparison = subjectOf(view, "comparison");
  const latest = view.notes.items[3].note_id;
  const full = noteBody(view.notes, comparison, { text: `  ${TEXT}\n`, expectation: ` ${EXPECTATION} `,
    checkBy: "2027-02-28", question: `\n${QUESTION}  `, follows: view.notes.items[1].note_id });
  assert.deepEqual(full, { parent_note_id: latest, about: { kind: "comparison", id: ID },
    subject_sha256: comparison.sha256, follows: view.notes.items[1].note_id, text: TEXT,
    expectation: { text: EXPECTATION, check_by: "2027-02-28" }, question: QUESTION });
  assert.deepEqual(Object.keys(full),
    ["parent_note_id", "about", "subject_sha256", "follows", "text", "expectation", "question"]);
  assert.deepEqual(Object.keys(full.about), ["kind", "id"]);
  assert.deepEqual(Object.keys(full.expectation!), ["text", "check_by"]);
  // No expectation and no question are null; a check-by date goes only with an expectation, or is null with one.
  const plain = noteBody(view.notes, subjectOf(view, "thesis"), draft({ expectation: "  ", checkBy: "2027-02-28",
    question: " \n " }));
  assert.deepEqual(plain, { parent_note_id: latest, about: { kind: "thesis", id: "copper" },
    subject_sha256: subjectOf(view, "thesis").sha256, follows: null, text: TEXT, expectation: null, question: null });
  assert.deepEqual(noteBody(view.notes, comparison, draft({ expectation: EXPECTATION })).expectation,
    { text: EXPECTATION, check_by: null });
  // A first note has no parent; line breaks inside the text are kept.
  const first = noteBody(fixture("empty").notes, subjectOf(view, "chain"), draft({ text: "TEST VALUE: one.\ntwo. " }));
  assert.equal(first.parent_note_id, null);
  assert.equal(first.text, "TEST VALUE: one.\ntwo.");
  assert.deepEqual(first.about, { kind: "chain", id: "synthetic-world-chain" });
});

test("posts once with the action and account headers", async () => {
  const view = fixture("available");
  const body = noteBody(view.notes, subjectOf(view, "comparison"), draft({ expectation: EXPECTATION,
    checkBy: "2027-02-28", question: QUESTION }));
  bindAdminAccount("local-operator-id");
  const seen: Call[] = [];
  try {
    const result = await withFetch(replying(201, { record: savedFrom(body, 5) }, seen), () => saveNote(body));
    assert.equal(result.state, "ready");
  } finally {
    bindAdminAccount(null);
  }
  assert.equal(seen.length, 1);
  assert.equal(seen[0].url, "/api/theses/copper/research/notes");
  assert.equal(seen[0].init.method, "POST");
  assert.equal(RESEARCH_NOTE_HEADER, "X-Second-Order-Research-Note");
  assert.deepEqual(seen[0].init.headers, { "Content-Type": "application/json", Accept: "application/json",
    "X-Second-Order-Research-Note": "1", "X-Second-Order-Account": "local-operator-id" });
  assert.deepEqual(JSON.parse(String(seen[0].init.body)), body);
  // Without a bound account (local-operator mode) no account header is sent.
  const second: Call[] = [];
  await withFetch(replying(422, { detail: "no" }, second), () => saveNote(body));
  assert.deepEqual(second[0].init.headers, { "Content-Type": "application/json", Accept: "application/json",
    "X-Second-Order-Research-Note": "1" });
});

test("maps 201, 409 (blocked) and 422 (failed), with 5xx and no reply unconfirmed", async () => {
  const view = fixture("available");
  const body = noteBody(view.notes, subjectOf(view, "comparison"), draft({ expectation: EXPECTATION,
    checkBy: "2027-02-28" }));
  const ok = savedFrom(body, 5);
  const run = (fake: typeof fetch) => withFetch(fake, () => saveNote(body));
  assert.deepEqual(await run(replying(201, { record: ok })), { state: "ready", status: 201, data: { record: ok } });
  assert.deepEqual(await run(replying(409, { detail: "The parent is not the latest note", latest: "f".repeat(64) })),
    { state: "blocked", message: "The parent is not the latest note", latest: "f".repeat(64) });
  assert.deepEqual(await run(replying(409, { detail: "The comparison is not available", latest: null })),
    { state: "blocked", message: "The comparison is not available", latest: null });
  assert.deepEqual(await run(replying(422, { detail: "the note must be 1 to 2000 characters" })),
    { state: "failed", message: "the note must be 1 to 2000 characters" });
  assert.deepEqual(await run(replying(404, { detail: "No comparison has this id" })),
    { state: "failed", message: "No comparison has this id" });
  assert.deepEqual(await run(replying(413, null)), { state: "failed", message: "Unexpected response (413)." });
  for (const status of [401, 403, 428]) {
    const refusal = { contract: "x", code: "account_binding_required", detail: "Sign in again" };
    const out = await run(replying(status, refusal));
    assert.deepEqual(out, { state: "failed", message: "Sign in again" }, String(status));
  }
  assert.deepEqual(await run(replying(500, { detail: "The local records could not be written (OSError)" })),
    { state: "unconfirmed", message: "The local records could not be written (OSError)" });
  assert.equal((await run(replying(503, null))).state, "unconfirmed");
  const lost = await run((async () => { throw new TypeError("network"); }) as typeof fetch);
  assert.deepEqual(lost, { state: "unconfirmed",
    message: "No reply arrived from the local server; nothing was sent again." });
  // A 409 that is not exactly {detail, latest}, and a 201 whose record is not the note that was sent, prove nothing.
  assert.equal((await run(replying(409, { detail: "x" }))).state, "unconfirmed");
  assert.equal((await run(replying(409, { detail: "x", latest: null, extra: 1 }))).state, "unconfirmed");
  for (const other of [{ ...ok, text: "TEST VALUE: another text." }, { ...ok, about: { kind: "thesis", id: "copper" } },
    { ...ok, parent_note_id: null }, { ...ok, question: QUESTION }, { ...ok, expectation: null },
    { ...ok, expectation: { text: EXPECTATION, check_by: "2027-03-01" } }, { ...ok, follows: "e".repeat(64) },
    { ...ok, basis: { comparison: { id: ID, sha256: "0".repeat(64), version: 1 } } }]) {
    assert.equal((await run(replying(201, { record: other }))).state, "unconfirmed");
  }
  assert.equal((await run(replying(200, { record: ok }))).state, "unconfirmed");
  assert.equal((await run(replying(201, { record: ok, extra: 1 }))).state, "unconfirmed");
});

// ---------------------------------------------------------------- settling a lost reply

/** The view after `sent` was saved as its next note: the note as the server would serve it, on a readable view. */
function withSaved(view: CopperResearchView, sent: NoteBody, over: Partial<NoteView> = {}): CopperResearchView {
  const next = copy(view);
  const like = next.notes.items.find((item) => item.about.kind === sent.about.kind)!;
  const note: NoteView = { ...copy(like), note_id: "c".repeat(64), parent_note_id: sent.parent_note_id,
    sequence: next.notes.items.length + 1, follows: sent.follows, followed_by: null, text: sent.text,
    question: sent.question, expectation: sent.expectation === null ? null : { ...sent.expectation,
      state: "not_yet_checked", status: view.notes.items[0].expectation!.status }, ...over };
  const followed = next.notes.items.find((item) => item.note_id === note.follows);
  if (followed !== undefined) followed.followed_by = note.note_id;
  next.notes.items.push(note);
  next.notes.latest = note.note_id;
  return next;
}

test("settles a lost save from the saved notes without sending again", async () => {
  const view = fixture("available");
  const sent = noteBody(view.notes, subjectOf(view, "comparison"), draft({ expectation: EXPECTATION,
    checkBy: "2027-02-28", question: QUESTION, follows: view.notes.items[1].note_id }));
  const seen: Call[] = [];
  const lost = (async (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ url: String(input), init: init ?? {} });
    throw new TypeError("connection lost");
  }) as typeof fetch;
  assert.equal((await withFetch(lost, () => saveNote(sent))).state, "unconfirmed");
  const next = withSaved(view, sent);
  assert.equal(copperResearchRefusal(next), null);  // The settled view is one the reader accepts.
  await withFetch(replying(500, {}, seen), async () => {
    assert.equal(settleNote(next, sent), "saved");
    assert.equal(settleNote(view, sent), "not-saved");
  });
  assert.equal(seen.length, 1);  // Exactly one POST; settling never sends.
});

test("settles saved, conflict, not-saved and unverifiable", () => {
  const view = fixture("available");
  const sent = noteBody(view.notes, subjectOf(view, "comparison"), draft({ expectation: EXPECTATION,
    checkBy: "2027-02-28", question: QUESTION }));
  assert.equal(settleNote(view, sent), "not-saved");
  assert.equal(settleNote(withSaved(view, sent), sent), "saved");
  // Later notes may follow it: it is still saved.
  const after = { ...sent, parent_note_id: "c".repeat(64), text: "TEST VALUE: later." };
  const later = withSaved(withSaved(view, sent), after, { note_id: "d".repeat(64) });
  assert.equal(copperResearchRefusal(later), null);
  assert.equal(settleNote(later, sent), "saved");
  // Another note took the place after the same parent: a conflict, never saved.
  const conflict = (over: Partial<NoteView>) => settleNote(withSaved(view, sent, over), sent);
  assert.equal(conflict({ text: "TEST VALUE: another tab's note." }), "conflict");
  assert.equal(conflict({ question: null }), "conflict");
  assert.equal(conflict({ question: "TEST VALUE: another question?" }), "conflict");
  assert.equal(conflict({ expectation: null }), "conflict");
  assert.equal(conflict({ expectation: { ...view.notes.items[0].expectation!, text: EXPECTATION, check_by: null } }),
    "conflict");
  assert.equal(conflict({ expectation: { ...view.notes.items[0].expectation!, text: "TEST VALUE: another.",
    check_by: "2027-02-28" } }), "conflict");
  assert.equal(conflict({ follows: view.notes.items[0].note_id }), "conflict");
  assert.equal(conflict({ about: { kind: "thesis", id: "copper" } }), "conflict");
  // The parent alone never identifies a save: the same texts bound to another version of the subject are a conflict.
  assert.equal(conflict({ basis: { comparison: { id: ID, sha256: "9".repeat(64), version: 2 },
    evidence_sha256: "b".repeat(64) } }), "conflict");
  // A first save has a null parent.
  const empty = fixture("empty");
  const first = noteBody(empty.notes, subjectOf(empty, "thesis"), draft());
  assert.equal(first.parent_note_id, null);
  assert.equal(settleNote(empty, first), "not-saved");
  const thesisNote = fixture("available").notes.items[3];
  const saved = copy(empty);
  saved.notes.items = [{ ...copy(thesisNote), parent_note_id: null, sequence: 1, text: TEXT }];
  saved.notes.latest = thesisNote.note_id;
  assert.equal(copperResearchRefusal(saved), null);
  assert.equal(settleNote(saved, first), "saved");
  // Saved notes that cannot be verified settle nothing.
  const invalid = copy(view);
  invalid.notes = { state: "invalid", problem: "The saved notes are inconsistent: unexpected file x", latest: null,
    items: [] };
  assert.equal(copperResearchRefusal(invalid), null);
  assert.equal(settleNote(invalid, sent), "unverifiable");
});

test("settles a note the server shows masked as the sent note with its figures withheld", () => {
  const view = fixture("withheld");
  const chain = subjectOf(fixture("available"), "chain");
  const sent = noteBody(view.notes, chain, draft({ text: "TEST VALUE: see step 3, step 9 and the 85%.",
    expectation: "TEST VALUE: 4 of 5 by then.", question: "TEST VALUE: is it still 80%?" }));
  const masked = { text: "TEST VALUE: see step 3, step [figure withheld] and the [figure withheld].",
    question: "TEST VALUE: is it still [figure withheld]?", expectation: { ...view.notes.items[0].expectation!,
      check_by: null, text: "TEST VALUE: [figure withheld] of [figure withheld] by then." } };
  const next = withSaved(view, sent, masked);
  assert.equal(next.notes.items[4].masked, true);
  assert.equal(next.notes.items[4].steps, 5);
  assert.equal(copperResearchRefusal(next), null);
  assert.equal(settleNote(next, sent), "saved");
  // Another masked text is a conflict, and so is the masked text on a note that is not masked.
  assert.equal(settleNote(withSaved(view, sent, { ...masked, text: "TEST VALUE: see step 3 and [figure withheld]." }),
    sent), "conflict");
  assert.equal(settleNote(withSaved(view, sent, { ...masked, masked: false }), sent), "conflict");
});

// ---------------------------------------------------------------- the pages' plain rules

test("lists the open questions: a note's question until a later note follows it, newest first", () => {
  const view = fixture("available");
  assert.deepEqual(openQuestions(view.notes), []);  // The only question is on a note that a later note follows.
  const asked = copy(view);
  asked.notes.items[1].question = "TEST VALUE: a question on the later note?";
  asked.notes.items[3].question = "TEST VALUE: a question on the thesis note?";
  assert.deepEqual(openQuestions(asked.notes).map((note) => note.sequence), [4, 2]);
  const open = copy(view);
  Object.assign(open.notes.items[0], { followed_by: null });
  Object.assign(open.notes.items[1], { follows: null });  // No later note follows the first one any more.
  assert.deepEqual(openQuestions(open.notes).map((note) => note.question),
    ["TEST VALUE: does the next annual report keep the 80% line?"]);
  assert.deepEqual(openQuestions(fixture("empty").notes), []);
});

test("a question is closed by a later note that follows it or a later note on its subject", () => {
  // The form can only follow the latest note on a subject. A question on an earlier note of that subject must still
  // close when the owner follows the latest one, or it could never be closed.
  const view = fixture("available");
  const [first, second] = view.notes.items;  // Both about the comparison; the second follows the first.
  assert.deepEqual([first.question !== null, second.follows], [true, first.note_id]);
  // The second note does not follow the first: the first's question is open.
  Object.assign(second, { follows: null });
  first.followed_by = null;
  assert.deepEqual(openQuestions(view.notes).map((note) => note.sequence), [1]);
  // A third note on the same subject follows the second (the latest then): the first's question is closed too.
  const third = { ...copy(second), note_id: "c".repeat(64), parent_note_id: view.notes.items[3].note_id, sequence: 5,
    follows: second.note_id, followed_by: null, question: null };
  second.followed_by = third.note_id;
  view.notes.items.push(third);
  assert.deepEqual(openQuestions(view.notes), []);
  // A note on another subject closes nothing.
  third.about = view.notes.items[2].about;
  assert.deepEqual(openQuestions(view.notes).map((note) => note.sequence), [1]);
});

test("names subjects, their pages, a subject's notes and why its form is closed", () => {
  const view = fixture("withheld");
  assert.deepEqual(view.subjects.map(subjectLabel), [
    "Thesis: Synthetic copper: technology demand and the physical balance",
    "Chain: Synthetic sales, a halted pit and slow mine supply",
    "Comparison: Synthetic: the annual report against the quarterly report"]);
  assert.deepEqual(view.subjects.map(subjectPath),
    ["/theses/copper", "/theses/copper/events", `/copper/comparisons/${ID}`]);
  assert.deepEqual(view.subjects.map(closedReason), [null,
    "Notes are not accepted while the chain is in need of revalidation: The document fcx:10q-2026q3 differs from its "
      + "acquisition record.",
    "Notes are not accepted while the comparison is in need of revalidation: The document fcx:10q-2026q3 differs from "
      + "its acquisition record."]);
  assert.deepEqual(notesAbout(view.notes, { kind: "comparison", id: ID }).map((note) => note.sequence), [1, 2]);
  assert.equal(latestNoteAbout(view.notes, { kind: "comparison", id: ID })?.sequence, 2);
  assert.equal(latestNoteAbout(view.notes, { kind: "chain", id: "another-chain" }), null);
});

test("writes an available price figure with its period, and nothing for a withheld one", () => {
  const figures = fixture("withheld").comparisons[0].prices.figures;
  assert.equal(priceLine(figures[0]),
    "Average realized price per pound (copper), FY2025 (2025-01-01 to 2025-12-31): 4.75 USD per pound");
  assert.equal(priceLine(figures[1]), null);
  assert.equal(priceLine(figures[3]), "Price, annual average, cents per pound: U.S. producer, cathode (COMEX + "
    + "premium), 2025 (estimate) (2025-01-01 to 2025-12-31): 490 US cents per pound");
});
