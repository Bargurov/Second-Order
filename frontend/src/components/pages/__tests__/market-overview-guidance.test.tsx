/**
 * Pins the P6B readability fix: the big "How to read this" accordion is
 * replaced by always-visible inline guidance, jargon labels carry a
 * plain-language meaning, and each section has short how-to-read copy.
 */

import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { ContextExplanation } from "@/lib/api";
import {
  ContextExplanationInline,
  plainMeaning,
  HOWTO_MARKET_BACKDROP,
  HOWTO_ARCHIVE,
  HOWTO_OUTCOME_LEDGER,
  HOWTO_EVIDENCE,
} from "../market-overview";

describe("inline guidance replaces the How-to-read accordion", () => {
  const html = renderToStaticMarkup(
    <ContextExplanationInline
      explanation={{ meaning: "the regime is risk-off" } as ContextExplanation}
    />,
  );
  it("renders an always-visible Plain meaning line", () => {
    expect(html.toLowerCase()).toContain("plain meaning");
    expect(html).toContain("the regime is risk-off");
  });
  it("no longer renders a How-to-read accordion", () => {
    expect(html).not.toContain("How to read this");
    expect(html).not.toContain("<details");
  });
});

describe("jargon plain-meaning glossary", () => {
  it("defines Credit-duration stress in plain language", () => {
    const m = plainMeaning("Credit duration stress");
    expect(m).toBeTruthy();
    expect(m!.toLowerCase()).toContain("credit");
  });
  it("defines other non-obvious backdrop labels", () => {
    expect(plainMeaning("duration stress")).toBeTruthy();
    expect(plainMeaning("Credit widening")).toBeTruthy();
    expect(plainMeaning("Dollar shortage")).toBeTruthy();
    expect(plainMeaning("Systemic")).toBeTruthy();
  });
  it("returns null for plain / unknown labels", () => {
    expect(plainMeaning("Calm")).toBeNull();
    expect(plainMeaning("")).toBeNull();
    expect(plainMeaning(null)).toBeNull();
  });
});

describe("section-level how-to-read guidance", () => {
  it("provides short guidance for all four sections", () => {
    for (const g of [HOWTO_MARKET_BACKDROP, HOWTO_ARCHIVE, HOWTO_OUTCOME_LEDGER, HOWTO_EVIDENCE]) {
      expect(g.length).toBeGreaterThan(15);
    }
  });
  it("guidance + jargon copy avoids banned words", () => {
    const blob = [
      HOWTO_MARKET_BACKDROP,
      HOWTO_ARCHIVE,
      HOWTO_OUTCOME_LEDGER,
      HOWTO_EVIDENCE,
      plainMeaning("Credit duration stress") ?? "",
    ]
      .join(" ")
      .toLowerCase();
    for (const w of ["buy", "sell", "alpha", "signal", "proof", "proves"]) {
      expect(blob).not.toContain(w);
    }
  });
});
