// Case enrichment client logic, against the views the backend serves for the two committed enrichments and for a case
// without one (captured by tests/test_case_enrichments.py into fixtures/library-enrichment-*.json, with no retained
// copy on the machine). Replies are read fail-closed, and an enrichment is shown only for the case whose claims it
// addresses, under their own labels.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  claimLabel, discrepancies, ENRICHMENT_VIEW_VERSION, fitsCase, isEnrichmentView, type EnrichmentView,
} from "../src/caseEnrichment.ts";
import type { LibraryCase } from "../src/library.ts";

const fixture = (name: string): EnrichmentView =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const committedCase = (id: string): LibraryCase =>
  JSON.parse(readFileSync(new URL(`../../content/case-library/${id}.json`, import.meta.url), "utf8"));
const uae = fixture("library-enrichment-bis-2026-07-10.json");
const amat = fixture("library-enrichment-bis-2026-02-12.json");
const none = fixture("library-enrichment-none.json");
const copy = (view: EnrichmentView): EnrichmentView => structuredClone(view);

test("the served views are read: two bound enrichments and a case without one", () => {
  for (const view of [uae, amat, none]) assert.equal(isEnrichmentView(view), true, view.case_id);
  assert.equal(uae.view_version, ENRICHMENT_VIEW_VERSION);
  assert.deepEqual([uae.state, amat.state, none.state], ["bound", "bound", "none"]);
  assert.equal(none.enrichment, null);
  assert.deepEqual(uae.enrichment!.counts, { consistent: 6, qualified: 4, discrepancy: 1, not_found: 0 });
  assert.deepEqual(amat.enrichment!.counts, { consistent: 7, qualified: 4, discrepancy: 2, not_found: 0 });
  for (const view of [uae, amat]) {
    assert.deepEqual(view.enrichment!.copies.map((item) => item.state), view.enrichment!.sources.map(() => "absent"));
  }
});

test("each enrichment fits its own case and no other, and its discrepancies are addressed by claim", () => {
  const uaeCase = committedCase("bis-2026-07-10");
  const amatCase = committedCase("bis-2026-02-12");
  assert.equal(fitsCase(uae.enrichment!, uaeCase), true);
  assert.equal(fitsCase(amat.enrichment!, amatCase), true);
  assert.equal(fitsCase(uae.enrichment!, amatCase), false);
  assert.deepEqual([...discrepancies(uae.enrichment).keys()], ["channels[2].source_fact"]);
  assert.deepEqual([...discrepancies(amat.enrichment).keys()],
                   ["competing_explanations[0].detail", "source_notes[2].detail"]);
  assert.equal(discrepancies(null).size, 0);
  assert.equal(claimLabel(amatCase, "source_notes[2].detail"), "Context: January 14, 2026");
  assert.equal(claimLabel(amatCase, "key_facts[9]"), null);
  assert.equal(claimLabel(amatCase, "overview[0]"), null);
  const relabelled = copy(uae);
  relabelled.enrichment!.claim_checks[2].label = "Penalty";
  assert.equal(fitsCase(relabelled.enrichment!, uaeCase), false);
  const reordered = copy(uae);
  reordered.enrichment!.examination.reverse();
  assert.equal(fitsCase(reordered.enrichment!, uaeCase), false);
});

test("chain placement is the curator's reading and nothing private is served", () => {
  for (const view of [uae, amat]) {
    assert.equal(view.enrichment!.chain.attribution, "curator_interpretation");
    const text = JSON.stringify(view);
    for (const privateWord of ["folder", "attempt", "sector-sources", "source.html"]) {
      assert.equal(text.includes(privateWord), false, privateWord);
    }
  }
});

test("a reply that breaks the contract is refused", () => {
  const broken: [EnrichmentView, (view: EnrichmentView) => void][] = [
    [uae, (view) => { view.enrichment!.counts.consistent += 1; }],
    [uae, (view) => { (view.enrichment!.claim_checks[0] as { status: string }).status = "verified"; }],
    [uae, (view) => { view.enrichment!.claim_checks[2].note = "Fine."; }],
    [uae, (view) => { view.enrichment!.claim_checks[10].note = null; }],
    [uae, (view) => { view.enrichment!.claim_checks[3].target = view.enrichment!.claim_checks[2].target; }],
    [uae, (view) => { view.enrichment!.claim_checks[2].source = "listing"; }],
    [uae, (view) => { view.enrichment!.readout[3].reference = "the-rule-text"; }],
    [uae, (view) => { view.enrichment!.readout[3].reference = null; }],
    [uae, (view) => { view.enrichment!.readout[7].reference = "federal-register-notice"; }],
    [uae, (view) => { view.enrichment!.readout = view.enrichment!.readout.filter((item) => item.aspect !== "timing"); }],
    [uae, (view) => { (view.enrichment!.references[0] as { read: boolean }).read = true; }],
    [uae, (view) => { (view.enrichment!.sources[0].retained as Record<string, unknown>).folder = "bis-2026-07-10"; }],
    [uae, (view) => { view.enrichment!.copies.push({ ...view.enrichment!.copies[0] }); }],
    [uae, (view) => { view.enrichment!.copies[0].state = "trusted"; }],
    [uae, (view) => { view.enrichment!.comparison!.href = "/library/bis-2022-10-07"; }],
    [uae, (view) => { (view.enrichment!.chain as { attribution: string }).attribution = "stated_by_source"; }],
    [uae, (view) => { (view.enrichment!.provenance as { human_review: string }).human_review = "reviewed"; }],
    [uae, (view) => { (view.enrichment! as { currency: string }).currency = "current"; }],
    [uae, (view) => { view.enrichment!.examination[0].observations = []; }],
    [uae, (view) => { view.note = "Shown."; }],
    [uae, (view) => { (view as { provider_called: boolean }).provider_called = true; }],
    [amat, (view) => { view.enrichment!.sources = view.enrichment!.sources.filter((source) => source.id !== "release"); }],
    [amat, (view) => { view.enrichment!.sources[1].id = "release"; }],
    [none, (view) => { view.enrichment = copy(uae).enrichment; }],
    [none, (view) => { (view as { state: string }).state = "shown"; }],
  ];
  for (const [view, change] of broken) {
    const changed = copy(view);
    change(changed);
    assert.equal(isEnrichmentView(changed), false, change.toString());
  }
});
