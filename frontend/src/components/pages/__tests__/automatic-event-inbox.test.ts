/**
 * automatic-event-inbox.test.ts — structural invariants for the reframed
 * headlines surface (InboxWorkbench → Automatic Event Inbox).
 *
 * Filesystem-based source checks, same style as single-inbox-surface.test.ts:
 * they pin what the mounted page renders and — just as important — what it
 * must never do (auto refresh, auto analysis, score/direction language).
 * Runtime rendering is covered by the browser smoke.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const PAGE_FILE = resolve(__dirname, "..", "inbox-workbench.tsx");
const LIB_FILE = resolve(__dirname, "../../../lib/event-inbox.ts");
const API_FILE = resolve(__dirname, "../../../lib/api.ts");

const page = () => readFileSync(PAGE_FILE, "utf-8");
const lib = () => readFileSync(LIB_FILE, "utf-8");

describe("page identity", () => {
  it("the headlines surface is titled Automatic Event Inbox", () => {
    expect(page()).toContain("Automatic Event");
    expect(page()).toContain("Inbox");
  });

  it("still exports the cache-only shouldAutoRefreshOnRender invariant", () => {
    expect(page()).toMatch(/export function shouldAutoRefreshOnRender/);
    expect(page()).toMatch(
      /shouldAutoRefreshOnRender\([^)]*\)\s*:\s*boolean\s*\{\s*return false;/,
    );
  });
});

describe("permanent explanations", () => {
  it("renders the surfacing non-claim and the absence disclosure", () => {
    // The exact wording lives in lib/event-inbox.ts; the page must import
    // and render both constants.
    expect(lib()).toContain(
      "Events are surfaced through explicit source, identity and economic-channel rules.",
    );
    expect(lib()).toContain(
      "Absence from the inbox does not prove that an event is economically irrelevant.",
    );
    expect(page()).toContain("INBOX_NON_CLAIM");
    expect(page()).toContain("INBOX_ABSENCE_NOTE");
  });

  it("renders the honest empty state verbatim", () => {
    expect(page()).toContain(
      "No newly detected events currently pass the materiality gate.",
    );
  });
});

describe("contract consumption is fail-closed", () => {
  it("parses through parseInboxPayload and refuses malformed payloads", () => {
    expect(page()).toContain("parseInboxPayload");
    expect(page()).toMatch(/failed validation|refusing to render|cannot be rendered/i);
  });

  it("fetches the inbox through the local-state-only GET", () => {
    const api = readFileSync(API_FILE, "utf-8");
    expect(api).toContain('"/news/inbox"');
    expect(page()).toContain("newsInbox");
  });
});

describe("lifecycle presentation", () => {
  it("active workflow sections appear before the resolved section", () => {
    const src = page();
    const iNew = src.indexOf('"NEW"');
    const iDev = src.indexOf('"DEVELOPING"');
    const iWatch = src.indexOf('"WATCH"');
    const iResolved = src.indexOf('"RESOLVED"');
    expect(iNew).toBeGreaterThan(-1);
    expect(iDev).toBeGreaterThan(-1);
    expect(iWatch).toBeGreaterThan(-1);
    expect(iResolved).toBeGreaterThan(-1);
    // RESOLVED renders collapsed so it never dominates the active view.
    expect(src).toMatch(/<details/);
  });
});

describe("analysis handoff", () => {
  it("opens events through the existing onAnalyze boundary with the analysis_target", () => {
    const src = page();
    expect(src).toContain("analysis_target");
    expect(src).toMatch(/onAnalyze\(\s*[a-zA-Z_.]*analysis_target\.headline/);
  });

  it("never invokes analysis from an effect (no auto-LLM on load)", () => {
    const src = page();
    const effects = src.match(/useEffect\(\s*\(\)\s*=>\s*\{[\s\S]*?\}\s*,\s*\[[^\]]*\]\s*\)/g) ?? [];
    for (const block of effects) {
      expect(block).not.toContain("onAnalyze");
      expect(block).not.toContain("newsRefresh");
    }
    expect(src).toContain("shouldAutoAnalyzeOnLoad");
  });
});

describe("no score or trade language in chrome copy", () => {
  it("authored page copy carries no directional or score vocabulary", () => {
    // The two permanent sentences live in lib/event-inbox.ts (the dedicated
    // non-claims wording), so the page source itself must stay clean.
    const src = page();
    for (const token of [
      "buy", "sell", "bullish", "bearish", "upside", "downside",
      "opportunity", "conviction", "urgency", "tradeable", "outperform",
    ]) {
      expect(src.toLowerCase()).not.toMatch(new RegExp(`\\b${token}\\b`));
    }
    expect(src.toLowerCase()).not.toContain("score");
  });
});

describe("keyboard navigation", () => {
  it("event rows are native buttons with expansion state", () => {
    const src = page();
    expect(src).toMatch(/<button[^>]*aria-expanded/);
  });
});
