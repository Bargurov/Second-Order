// Short words for the metals page. A cell that shows no figure gives a short label beside a button that opens the full
// reason, which is always the server's own words (or the page's fixed words); a label never states more than its reason.
import { YEARS_UNDER_ONE } from "./metals.ts";

/** What a cell would show: a ranking, a years figure, a share, or a figure a research link names. */
export type ReasonKind = "rank" | "years" | "share" | "figure";

const LABELS: [RegExp, string][] = [
  [/Unit in doubt/, "Unit in doubt"],
  [/^Printed as “.*”$/, ""],  // A share printed as a code: the print itself is the label.
  [/ is printed as “.*”, so the order is unknown$/, "Order unknown"],
  [/^The world total is printed as “.*”, not as a number$/, "World total not a number"],
  [/^The world total is printed as “.*”, so no share can be computed$/, "World total is zero"],
  [/^USGS prints no world total for this series$/, "No world total"],
  [/^USGS prints more than one world total for this series$/, "Two world totals"],
  [/^(?:USGS prints no country for this series|No countries are named)$/, "No countries named"],
  [/^Fewer than three countries are named$/, "Fewer than three named"],
  [/^(?:Not computed: no 2025 reserves series matches this stage|No matching 2025 reserves series)$/,
    "No matching series"],
  // The reasons a research link's figure is not shown (metals_research, re-resolved by metalsStage2.ts).
  [/^The (?:USGS|IEA) part is withheld(?::|$)/, "Withheld"],
  [/^USGS prints no 2025 production series at the (?:mining|refining) stage for this metal$/, "No such stage"],
  [/^USGS prints no 2025 net import reliance for this metal$/, "Not printed"],
  [/^No years figure for this pair$/, "No years figure"],
  [/^The IEA lists no .+ use for .+ in this table$/, "Not in the IEA table"],
  [/^The IEA's table gives no technology split for .+$/, "No technology split"],
  [/^The IEA's 2025 energy-technology total for .+ is not positive, so no share is computed$/, "No share"],
];
const PLAIN: Record<ReasonKind, string> = { rank: "Not ranked", years: "Not computed", share: "No share",
  figure: "Not shown" };

/** The short label for a reason; a years reason's "Reserves: " or "Production: " prefix names its series only. */
export function shortReason(reason: string, kind: ReasonKind): string {
  const text = reason.replace(/^(?:Reserves|Production): /, "");
  for (const [pattern, label] of LABELS) if (pattern.test(text)) return label === "" ? text : label;
  return PLAIN[kind];
}

/** A years figure as words: "43 years", "1 year", or "less than 1 year" for a ratio under one. */
export function yearsText(shown: string): string {
  return shown === YEARS_UNDER_ONE ? "less than 1 year" : shown === "1" ? "1 year" : `${shown} years`;
}
