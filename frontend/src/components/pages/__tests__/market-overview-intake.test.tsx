/**
 * Pins the P6 Market Overview headline-analysis intake.
 *
 *  - intakeSubmit: empty/whitespace input is ignored; non-empty calls
 *    onAnalyze with the trimmed headline.
 *  - HeadlineIntake renders the "Start an analysis" entry point (input +
 *    button + orientation); the Browse-inbox link appears only when a
 *    navigation handler is wired.
 *  - Intake copy carries none of the banned words, and the archive section
 *    headings remain present (the reframe spine is intact).
 */

import { describe, it, expect, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import {
  HeadlineIntake,
  intakeSubmit,
  INTAKE_TITLE,
  INTAKE_PLACEHOLDER,
  INTAKE_BUTTON,
  INTAKE_BROWSE_LINK,
  INTAKE_ORIENTATION,
  ARCHIVE_SECTION_TITLE,
  EVIDENCE_LIMITS_TITLE,
} from "../market-overview";

describe("HeadlineIntake entry point", () => {
  const html = renderToStaticMarkup(
    <HeadlineIntake onAnalyze={() => {}} onOpenHeadlines={() => {}} />,
  );

  it("exposes the Start an analysis entry point with input + button + orientation", () => {
    expect(html).toContain(INTAKE_TITLE);
    expect(html).toContain(INTAKE_PLACEHOLDER);
    expect(html).toContain(INTAKE_BUTTON);
    expect(html).toContain(INTAKE_ORIENTATION);
  });

  it("renders the Browse Headlines inbox link when navigation is wired", () => {
    expect(html).toContain(INTAKE_BROWSE_LINK);
  });

  it("omits the Browse link when no navigation handler is provided", () => {
    const bare = renderToStaticMarkup(<HeadlineIntake onAnalyze={() => {}} />);
    expect(bare).not.toContain(INTAKE_BROWSE_LINK);
  });
});

describe("intakeSubmit guard", () => {
  it("ignores empty / whitespace-only input", () => {
    const spy = vi.fn();
    expect(intakeSubmit("", spy)).toBe(false);
    expect(intakeSubmit("   ", spy)).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it("calls onAnalyze with the trimmed headline", () => {
    const spy = vi.fn();
    expect(intakeSubmit("  Fed signals a pause  ", spy)).toBe(true);
    expect(spy).toHaveBeenCalledWith("Fed signals a pause");
  });
});

describe("intake + archive copy", () => {
  it("intake copy avoids banned overclaim / trading words", () => {
    const blob = [
      INTAKE_TITLE,
      INTAKE_PLACEHOLDER,
      INTAKE_BUTTON,
      INTAKE_BROWSE_LINK,
      INTAKE_ORIENTATION,
    ]
      .join(" ")
      .toLowerCase();
    for (const w of ["buy", "sell", "alpha", "signal", "proof", "proves"]) {
      expect(blob).not.toContain(w);
    }
  });

  it("archive section headings remain present", () => {
    expect(ARCHIVE_SECTION_TITLE).toBe("The archive");
    expect(EVIDENCE_LIMITS_TITLE).toBe("Evidence & limits");
  });
});
