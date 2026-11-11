// Verdict explanations must state what the rule decided, not more.
import assert from "node:assert/strict";
import { test } from "node:test";
import { authorshipNote, horizonLegend, verdictMeaning, vintageLabel } from "../src/format.ts";
import type { Hypothesis } from "../src/types.ts";

test("inconclusive states the rule outcome, not ordinariness", () => {
  const text = verdictMeaning("inconclusive", 0.8, 0.2);
  assert.equal(
    text,
    "The measured move does not meet the combined direction and percentile criteria for support or contradiction.",
  );
  // An extreme rank with the wrong sign is still inconclusive, so "ordinary" would overclaim.
  assert.doesNotMatch(text, /ordinary|distinguishable|typical/i);
});

test("supported and contradicted keep their thresholds", () => {
  assert.match(verdictMeaning("supported", 0.8, 0.2), /expected direction.*0\.80/);
  assert.match(verdictMeaning("contradicted", 0.8, 0.2), /against the expected direction.*0\.20/);
});

// Synthetic engine records; only the fields authorshipNote reads matter.
const synthetic = (provider: string, evidence_class: Hypothesis["evidence_class"]) =>
  ({ evidence_class, engine: { provider, model: "synthetic", prompt_hash: "0".repeat(64), schema_version: "0.2" } }) as
    Hypothesis;

test("manual means outside the model adapter, not that no AI was involved", () => {
  assert.equal(
    authorshipNote(synthetic("manual", "replay")),
    "Submitted manually after the event; not a run of the project's model adapter, which does not rule out AI " +
      "assistance. Not research evidence.",
  );
  assert.equal(
    authorshipNote(synthetic("manual", "prospective")),
    "Submitted manually and frozen before its outcome; not a run of the project's model adapter, which does not " +
      "rule out AI assistance. Not research evidence.",
  );
  for (const evidence of ["replay", "prospective"] as const) {
    // The affirmative claims the old copy made; honest disclosure may still name what it denies.
    assert.doesNotMatch(authorshipNote(synthetic("manual", evidence)) ?? "", /written by hand|not a model run/i);
  }
  assert.equal(authorshipNote(synthetic("anthropic", "prospective")), null);
});

test("the horizon legend claims a shaded window only when its end was evaluated", () => {
  assert.equal(horizonLegend("13 Oct 2026", 5), "Horizon end · 13 Oct 2026 (5-session scored window shaded)");
  assert.equal(horizonLegend(null, 5), "Horizon end · not in the evaluated data (5-session window, so nothing is shaded)");
});

test("a snapshot without a vintage says so and is never shown as a date", () => {
  assert.equal(vintageLabel("2025-06-02"), "2 Jun 2025");
  assert.equal(vintageLabel(null), "None: no historical vintage");  // The Board's H.15 package, not 1 Jan 1970.
});
