/**
 * explicit-inbox-analysis.test.ts — A1-1 surface contract.
 *
 * Opening an event from the Event Inbox must not be the provider call.  The
 * analysis surface holds the candidate, states what a run would cover, and
 * waits for a separate explicit action; the identity fields travel with it so
 * the run that eventually happens is attributable to that exact candidate.
 *
 * Source-level scans, in the same style as the existing inbox surface tests:
 * they pin the wiring that the pure-logic suites (lib/analysis-launch,
 * lib/event-inbox) cannot see from outside the component.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const analysisView = () =>
  readFileSync(resolve(__dirname, "..", "analysis-view.tsx"), "utf-8");
const app = () =>
  readFileSync(resolve(__dirname, "..", "..", "..", "App.tsx"), "utf-8");

describe("opening a candidate is separate from paying for it", () => {
  it("gates the arrival effect on shouldAutoSubmit rather than always running", () => {
    const src = analysisView();
    expect(src).toMatch(/if \(shouldAutoSubmit\(initialLaunch\)\)/);
    // The pre-A1-1 form ran on any arriving headline, with no origin test.
    expect(src).not.toMatch(/if \(initialHeadline\) \{[\s\S]{0,200}submit\(/);
  });

  it("holds an un-run candidate instead of dropping it", () => {
    const src = analysisView();
    expect(src).toMatch(/setPendingCandidate\(initialLaunch as InboxLaunch\)/);
    expect(src).toContain("CandidateConfirmation");
  });

  it("builds every outgoing request through the launch layer", () => {
    const src = analysisView();
    expect(src).toMatch(/analyzeRequestFor\(/);
    // A null request means the action cannot be honestly served; the submit
    // path must return rather than fall back to an unconfirmed paid run.
    expect(src).toMatch(/if \(request === null\) return;/);
    // No hand-rolled request literal may bypass the confirmation.
    expect(src).not.toMatch(/api\.analyzeStream\(\s*\{\s*\n\s*headline: text/);
  });

  it("labels the free path and the paid path differently", () => {
    const src = analysisView();
    expect(src).toContain("View saved analysis");
    expect(src).toContain("Run analysis");
    expect(src).toMatch(/no provider call/);
  });

  it("offers no action at all when the candidate link conflicts", () => {
    const src = analysisView();
    expect(src).toMatch(/action === "blocked_conflict"/);
    expect(src).toMatch(/linked to more than one saved analysis/);
  });
});

describe("App routes the two origins differently", () => {
  it("opens inbox candidates through the candidate boundary", () => {
    const src = app();
    expect(src).toMatch(/onOpenCandidate=\{openInboxCandidate\}/);
    expect(src).toMatch(/launchFromInboxEvent\(ev\)/);
  });

  it("keeps every other origin on the direct-headline launch", () => {
    const src = app();
    expect(src).toMatch(/launchFromHeadline\(headline, opts\)/);
    expect(src).toMatch(/onAnalyze=\{analyzeHeadline\}/);
  });

  it("passes one typed launch to the analysis surface", () => {
    const src = app();
    expect(src).toMatch(/initialLaunch=\{pendingLaunch\}/);
    expect(src).not.toContain("initialHeadline=");
    expect(src).not.toContain("initialEventId=");
  });
});
