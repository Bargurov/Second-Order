/**
 * R2B — horizon-discipline + falsifier legibility on the Analyze
 * HorizonCheckpoints block.
 *
 * The section must (a) carry a compact horizon-discipline note framing the
 * read as an event-window transmission check, not a permanent forecast, and
 * (b) lift the clearest EXISTING ``falsifies_if`` into a "Thesis fails if"
 * summary — using payload text only, never invented — while keeping the full
 * per-horizon Expected / Confirms-if / Falsifies-if rows visible.
 */
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { HorizonCheckpointsBlock } from "../analysis-view";
import { HORIZON_DISCIPLINE_NOTE } from "@/lib/claim-copy";
import type { HorizonCheckpoints } from "@/lib/api";

function _data(over: Partial<HorizonCheckpoints> = {}): HorizonCheckpoints {
  return {
    timing_profile: "delayed_pass_through",
    horizons: [
      { horizon: "1d", expected: ["XLE up on the print"], confirms_if: ["XLE outperforms SPY 1d"], falsifies_if: ["XLE closes below its event-day level"] },
      { horizon: "5d", expected: ["sector spread holds"], confirms_if: ["spread widens by 5d"], falsifies_if: ["spread fully retraces by 5d"] },
      { horizon: "20d", expected: ["move persists"], confirms_if: ["20d move exceeds the 5d move"], falsifies_if: ["20d move reverts to zero"] },
    ],
    ...over,
  } as HorizonCheckpoints;
}

const html = renderToStaticMarkup(<HorizonCheckpointsBlock data={_data()} />);

describe("HorizonCheckpointsBlock — horizon discipline + falsifier summary (R2B)", () => {
  it("shows a horizon-discipline note: event-window read, not a permanent forecast", () => {
    expect(html).toContain(HORIZON_DISCIPLINE_NOTE);
    expect(HORIZON_DISCIPLINE_NOTE.toLowerCase()).toContain("not a permanent asset forecast");
    expect(HORIZON_DISCIPLINE_NOTE.toLowerCase()).toContain("event-window");
  });

  it("places the discipline note near the top, above the per-horizon rows", () => {
    // "XLE up on the print" is the 1d *expected* text — it appears only in the
    // rows, never in the summary, so it marks where the rows begin.
    expect(html.indexOf(HORIZON_DISCIPLINE_NOTE)).toBeLessThan(html.indexOf("XLE up on the print"));
  });

  it("shows a compact 'Thesis fails if' summary built from the first existing falsifies_if", () => {
    expect(html).toContain("Thesis fails if");
    // Payload text only — the 1d horizon's first falsifier.
    expect(html).toContain("XLE closes below its event-day level");
    // The summary sits above the rows, not buried after them.
    expect(html.indexOf("Thesis fails if")).toBeLessThan(html.indexOf("XLE up on the print"));
  });

  it("keeps the per-horizon Expected and all Falsifies-if rows visible (not collapsed)", () => {
    expect(html).toContain("XLE up on the print");          // expected (row)
    expect(html).toContain("spread fully retraces by 5d");  // 5d falsifier (row)
    expect(html).toContain("20d move reverts to zero");     // 20d falsifier (row)
  });

  it("the horizon-discipline note carries no banned framing", () => {
    const lc = HORIZON_DISCIPLINE_NOTE.toLowerCase();
    for (const w of ["buy", "sell", "long", "short", "alpha", "signal", "trade", "proof", "proves", "confirmed", "prediction", "live trading"]) {
      expect(lc, `banned word "${w}" in the horizon-discipline note`).not.toMatch(new RegExp(`\\b${w}\\b`));
    }
  });

  it("renders no 'Thesis fails if' summary when no falsifies_if exists (never fake text)", () => {
    const noFalsifiers = renderToStaticMarkup(
      <HorizonCheckpointsBlock
        data={_data({
          horizons: [
            { horizon: "1d", expected: ["x"], confirms_if: ["y"], falsifies_if: [] },
            { horizon: "5d", expected: ["x"], confirms_if: ["y"], falsifies_if: [] },
            { horizon: "20d", expected: ["x"], confirms_if: ["y"], falsifies_if: [] },
          ],
        })}
      />,
    );
    expect(noFalsifiers).not.toContain("Thesis fails if");
    // The horizon-discipline note still shows even with no falsifiers.
    expect(noFalsifiers).toContain(HORIZON_DISCIPLINE_NOTE);
  });
});
