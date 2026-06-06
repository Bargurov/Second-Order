/**
 * ResearchPageShell — pins the chrome-harmonization contract.
 *
 * The shell carries TWO things on one root element:
 *   1. the ``--so-*`` Direction-C palette (so migrated chrome can use
 *      ``--so-*`` classes directly), and
 *   2. a remap of the shadcn theme tokens (``--card`` / ``--foreground`` /
 *      ``--primary`` / …) to the Direction-C values, so an existing
 *      shadcn-token page inherits the new look with no per-element edits.
 *
 * Rendered to static markup (no jsdom) — the same pattern as the other
 * presentational-component tests.
 */

import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { ResearchPageShell } from "../research-page-shell";

const html = renderToStaticMarkup(
  <ResearchPageShell>
    <span>child-content</span>
  </ResearchPageShell>,
);

describe("ResearchPageShell", () => {
  it("renders its children", () => {
    expect(html).toContain("child-content");
  });

  it("carries the Direction-C --so-* palette", () => {
    expect(html).toContain("--so-bg-1:#121212");
    expect(html).toContain("--so-citrine:#d4b343");
  });

  it("remaps the shadcn card surface to charcoal and primary to citrine", () => {
    expect(html).toContain("--card:0 0% 7%");
    expect(html).toContain("--primary:46 63% 55%");
  });

  it("warms the foreground ink token", () => {
    expect(html).toContain("--foreground:45 38% 90%");
  });
});
