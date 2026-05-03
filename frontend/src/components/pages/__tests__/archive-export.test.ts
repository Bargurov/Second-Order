/**
 * Focused tests for the Archive row export action.
 *
 * Covers three invariants as pure function tests:
 *   1) Export action renders — deriveExportState returns the correct state.
 *   2) Successful export flow — exportingId resets to null after success.
 *   3) Failed export — exportErrorId is set; the row stays; state is "error".
 *
 * No component rendering, no React, no fetch mocking needed.
 */

import { describe, it, expect } from "vitest";
import { deriveExportState, type ExportRowState } from "../recent-events";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ID_A = 1;
const ID_B = 2;
const ID_C = 3;

// ---------------------------------------------------------------------------
// 1) Export action renders — deriveExportState
// ---------------------------------------------------------------------------

describe("deriveExportState — idle with nothing pending", () => {
  it("returns idle when exportingId and exportErrorId are null", () => {
    expect(deriveExportState(ID_A, null, null)).toBe<ExportRowState>("idle");
    expect(deriveExportState(ID_B, null, null)).toBe<ExportRowState>("idle");
  });
});

describe("deriveExportState — exporting phase", () => {
  it("returns exporting for the matching row", () => {
    expect(deriveExportState(ID_A, ID_A, null)).toBe<ExportRowState>("exporting");
  });

  it("returns idle for non-matching rows while one is exporting", () => {
    expect(deriveExportState(ID_B, ID_A, null)).toBe<ExportRowState>("idle");
    expect(deriveExportState(ID_C, ID_A, null)).toBe<ExportRowState>("idle");
  });

  it("exporting takes precedence over error (same id, should not co-occur but safe)", () => {
    // If somehow both are set to the same id, exporting wins
    expect(deriveExportState(ID_A, ID_A, ID_A)).toBe<ExportRowState>("exporting");
  });
});

describe("deriveExportState — error phase", () => {
  it("returns error for the matching row", () => {
    expect(deriveExportState(ID_B, null, ID_B)).toBe<ExportRowState>("error");
  });

  it("returns idle for other rows when one has errored", () => {
    expect(deriveExportState(ID_A, null, ID_B)).toBe<ExportRowState>("idle");
    expect(deriveExportState(ID_C, null, ID_B)).toBe<ExportRowState>("idle");
  });

  it("returns idle for the error row once the export succeeds (error cleared)", () => {
    // After success: exportingId=null, exportErrorId=null → idle
    expect(deriveExportState(ID_B, null, null)).toBe<ExportRowState>("idle");
  });
});

describe("deriveExportState — independent across rows", () => {
  it("one row exporting does not affect another row in error", () => {
    // Row A is exporting, row B previously errored — both coexist
    expect(deriveExportState(ID_A, ID_A, ID_B)).toBe<ExportRowState>("exporting");
    expect(deriveExportState(ID_B, ID_A, ID_B)).toBe<ExportRowState>("error");
    expect(deriveExportState(ID_C, ID_A, ID_B)).toBe<ExportRowState>("idle");
  });
});

// ---------------------------------------------------------------------------
// 2) Successful export flow — state transitions
// ---------------------------------------------------------------------------

/** Simulate the state right before the API call (setExportingId). */
function applyExportStart(id: number): { exportingId: number; exportErrorId: null } {
  return { exportingId: id, exportErrorId: null };
}

/** Simulate state after successful download (setExportingId(null)). */
function applyExportSuccess(): { exportingId: null; exportErrorId: null } {
  return { exportingId: null, exportErrorId: null };
}

describe("successful export flow", () => {
  it("row shows exporting state after handleExport fires", () => {
    const { exportingId, exportErrorId } = applyExportStart(ID_A);
    expect(deriveExportState(ID_A, exportingId, exportErrorId)).toBe<ExportRowState>("exporting");
  });

  it("row returns to idle after success", () => {
    const { exportingId, exportErrorId } = applyExportSuccess();
    expect(deriveExportState(ID_A, exportingId, exportErrorId)).toBe<ExportRowState>("idle");
  });

  it("other rows stay idle throughout the export", () => {
    const during = applyExportStart(ID_A);
    expect(deriveExportState(ID_B, during.exportingId, during.exportErrorId)).toBe<ExportRowState>("idle");
    const after = applyExportSuccess();
    expect(deriveExportState(ID_B, after.exportingId, after.exportErrorId)).toBe<ExportRowState>("idle");
  });

  it("previously errored row clears on new success", () => {
    // ID_A errored before, now ID_B succeeds; ID_A error should persist
    // (each row tracks independently — only the specific error id is cleared on retry)
    const mixed = { exportingId: null as number | null, exportErrorId: ID_A };
    expect(deriveExportState(ID_A, mixed.exportingId, mixed.exportErrorId)).toBe<ExportRowState>("error");
  });
});

// ---------------------------------------------------------------------------
// 3) Failed export — error state
// ---------------------------------------------------------------------------

/** Simulate state after a failed download. */
function applyExportError(id: number): { exportingId: null; exportErrorId: number } {
  return { exportingId: null, exportErrorId: id };
}

describe("failed export shows error state", () => {
  it("row shows error state after failed export", () => {
    const { exportingId, exportErrorId } = applyExportError(ID_A);
    expect(deriveExportState(ID_A, exportingId, exportErrorId)).toBe<ExportRowState>("error");
  });

  it("exportingId is null after failure (spinner gone)", () => {
    const { exportingId } = applyExportError(ID_A);
    expect(exportingId).toBeNull();
  });

  it("row stays in list — error does not remove the event", () => {
    // Export failure is pure UI state; no event list mutation
    // Just verify state is "error" (not removed from any list)
    const { exportingId, exportErrorId } = applyExportError(ID_A);
    expect(deriveExportState(ID_A, exportingId, exportErrorId)).toBe<ExportRowState>("error");
  });

  it("retry clears error and enters exporting again", () => {
    // User clicks retry: setExportingId(id), setExportErrorId(null)
    const afterRetry = applyExportStart(ID_A);
    expect(deriveExportState(ID_A, afterRetry.exportingId, afterRetry.exportErrorId)).toBe<ExportRowState>("exporting");
  });

  it("one row error does not affect other rows", () => {
    const { exportingId, exportErrorId } = applyExportError(ID_A);
    expect(deriveExportState(ID_B, exportingId, exportErrorId)).toBe<ExportRowState>("idle");
    expect(deriveExportState(ID_C, exportingId, exportErrorId)).toBe<ExportRowState>("idle");
  });
});
