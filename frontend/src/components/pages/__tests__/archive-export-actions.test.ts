/**
 * Focused tests for Archive row export actions.
 *
 * Covers four invariants as pure function tests:
 *   1) Export actions render — deriveExportMenuOpen returns the correct open state.
 *   2) Single export path triggers correctly — deriveExportFilename produces the
 *      right filename (and therefore URL segment) for each format.
 *   3) Bulk export path triggers correctly — deriveBulkExportFilename produces
 *      the right filename for CSV and JSON.
 *   4) Minimal error state on failed export — deriveExportState returns "error"
 *      when exportErrorId matches the row.
 *
 * No component rendering, no React, no fetch mocking needed.
 */

import { describe, it, expect } from "vitest";
import {
  deriveExportMenuOpen,
  deriveExportFilename,
  deriveBulkExportFilename,
  deriveExportState,
  EXPORT_FORMATS,
} from "../recent-events";
import type { ExportFormat } from "@/lib/api";

// ---------------------------------------------------------------------------
// 1) Export actions render — deriveExportMenuOpen
// ---------------------------------------------------------------------------

describe("deriveExportMenuOpen — closed by default", () => {
  it("returns false when menuId is null", () => {
    expect(deriveExportMenuOpen(1, null)).toBe(false);
    expect(deriveExportMenuOpen(2, null)).toBe(false);
    expect(deriveExportMenuOpen(99, null)).toBe(false);
  });

  it("returns false when menuId is a different row", () => {
    expect(deriveExportMenuOpen(1, 2)).toBe(false);
    expect(deriveExportMenuOpen(3, 2)).toBe(false);
  });
});

describe("deriveExportMenuOpen — open for matching row", () => {
  it("returns true when menuId matches eventId", () => {
    expect(deriveExportMenuOpen(1, 1)).toBe(true);
    expect(deriveExportMenuOpen(42, 42)).toBe(true);
  });

  it("only the matching row is open — all others are closed", () => {
    const openId = 5;
    for (const id of [1, 2, 3, 4, 6, 7]) {
      expect(deriveExportMenuOpen(id, openId)).toBe(false);
    }
    expect(deriveExportMenuOpen(openId, openId)).toBe(true);
  });
});

describe("deriveExportMenuOpen — EXPORT_FORMATS constant", () => {
  it("includes all four formats", () => {
    expect(EXPORT_FORMATS).toContain("text");
    expect(EXPORT_FORMATS).toContain("markdown");
    expect(EXPORT_FORMATS).toContain("csv");
    expect(EXPORT_FORMATS).toContain("json");
    expect(EXPORT_FORMATS.length).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// 2) Single export path — deriveExportFilename
// ---------------------------------------------------------------------------

describe("deriveExportFilename — extension per format", () => {
  const id = 7;
  const headline = "Fed raises rates by 50bp";

  it("text format produces .txt extension", () => {
    expect(deriveExportFilename(id, headline, "text")).toMatch(/\.txt$/);
  });

  it("markdown format produces .md extension", () => {
    expect(deriveExportFilename(id, headline, "markdown")).toMatch(/\.md$/);
  });

  it("csv format produces .csv extension", () => {
    expect(deriveExportFilename(id, headline, "csv")).toMatch(/\.csv$/);
  });

  it("json format produces .json extension", () => {
    expect(deriveExportFilename(id, headline, "json")).toMatch(/\.json$/);
  });
});

describe("deriveExportFilename — includes event id", () => {
  it("filename contains the event id", () => {
    const name = deriveExportFilename(123, "Some headline", "csv");
    expect(name).toContain("123");
  });
});

describe("deriveExportFilename — safe headline encoding", () => {
  it("spaces in headline become underscores", () => {
    const name = deriveExportFilename(1, "Fed raises rates", "text");
    expect(name).not.toContain(" ");
    expect(name).toContain("_");
  });

  it("special characters are removed", () => {
    const name = deriveExportFilename(1, "ECB: 50bp cut! (surprise)", "csv");
    expect(name).not.toMatch(/[:(!)]/);
  });

  it("long headline is truncated to ≤40 chars before extension", () => {
    const long = "A".repeat(80) + " more text";
    const name = deriveExportFilename(1, long, "json");
    // filename: "event_1_<safe_headline>.json" — safe headline ≤ 40 chars
    const body = name.replace(/^event_\d+_/, "").replace(/\.\w+$/, "");
    expect(body.length).toBeLessThanOrEqual(40);
  });

  it("deterministic — same inputs produce same filename", () => {
    const a = deriveExportFilename(5, "ECB rate cut", "markdown");
    const b = deriveExportFilename(5, "ECB rate cut", "markdown");
    expect(a).toBe(b);
  });
});

describe("deriveExportFilename — all formats covered", () => {
  it("produces distinct extensions for each format", () => {
    const names = EXPORT_FORMATS.map((fmt) => deriveExportFilename(1, "test", fmt));
    const exts = names.map((n) => n.split(".").pop());
    const unique = new Set(exts);
    expect(unique.size).toBe(EXPORT_FORMATS.length);
  });
});

// ---------------------------------------------------------------------------
// 3) Bulk export path — deriveBulkExportFilename
// ---------------------------------------------------------------------------

describe("deriveBulkExportFilename", () => {
  it("csv format produces events_export.csv", () => {
    expect(deriveBulkExportFilename("csv")).toBe("events_export.csv");
  });

  it("json format produces events_export.json", () => {
    expect(deriveBulkExportFilename("json")).toBe("events_export.json");
  });

  it("filenames are distinct across formats", () => {
    expect(deriveBulkExportFilename("csv")).not.toBe(deriveBulkExportFilename("json"));
  });

  it("both filenames start with events_export", () => {
    expect(deriveBulkExportFilename("csv")).toMatch(/^events_export/);
    expect(deriveBulkExportFilename("json")).toMatch(/^events_export/);
  });
});

// ---------------------------------------------------------------------------
// 4) Minimal error state — deriveExportState
// ---------------------------------------------------------------------------

describe("deriveExportState — error after failed export", () => {
  it("returns error when exportErrorId matches the row", () => {
    expect(deriveExportState(1, null, 1)).toBe("error");
    expect(deriveExportState(5, null, 5)).toBe("error");
  });

  it("returns idle for non-matching rows when one has errored", () => {
    expect(deriveExportState(2, null, 1)).toBe("idle");
    expect(deriveExportState(3, null, 1)).toBe("idle");
  });

  it("returns idle once error is cleared (both null)", () => {
    expect(deriveExportState(1, null, null)).toBe("idle");
  });

  it("exporting takes precedence over error when both set to same id", () => {
    expect(deriveExportState(1, 1, 1)).toBe("exporting");
  });

  it("other rows stay idle while one exports and one has errored", () => {
    // Row 1 exporting, row 2 errored, row 3 is unaffected
    expect(deriveExportState(3, 1, 2)).toBe("idle");
    expect(deriveExportState(1, 1, 2)).toBe("exporting");
    expect(deriveExportState(2, 1, 2)).toBe("error");
  });
});
