// Part 0 of the copper tools design, as the short box on the calculator page: where copper sits in the question "AI
// and electrification: who feels it second-order?". Fixed content: each link of the chain with one evidence status
// from a fixed vocabulary, and links only to pages that already exist (a test resolves each through the router). The
// full map stays in the design document; this box claims no effect and states no figure.

export const LINK_STATUSES = {
  described: "Described: what a rule or a company states; its effects are not measured",
  measured_unattributed: "Measured, unattributed: a retained series measures it, but not the part AI accounts for",
  projected: "Projected: a published projection, not an outturn",
  missing: "Missing: no retained evidence",
} as const;
export type LinkStatus = keyof typeof LINK_STATUSES;

export interface ChainLink { id: string; text: string; status: LinkStatus; links: { href: string; label: string }[] }

export const CHAIN: ChainLink[] = [
  { id: "L1", text: "Chip export controls → where and when AI computing is built", status: "described",
    links: [{ href: "/library/research/semiconductor-policy", label: "Semiconductor research view" }] },
  { id: "L2", text: "AI computing → data-centre electricity use", status: "missing", links: [] },
  { id: "L3", text: "Data-centre electricity → US commercial retail electricity sales", status: "measured_unattributed",
    links: [{ href: "/findings", label: "Findings: electricity by sector" }] },
  { id: "L4", text: "Electricity demand → grid build-out", status: "measured_unattributed",
    links: [{ href: "/findings", label: "Findings: cross-source comparisons" },
            { href: "/findings/g17", label: "Industry findings (G.17)" }] },
  { id: "L5", text: "Grid build-out → copper demand", status: "projected",
    links: [{ href: "/theses/copper", label: "Copper thesis" }] },
  { id: "L6", text: "Electrification outside AI → copper demand", status: "projected",
    links: [{ href: "/theses/copper", label: "Copper thesis" }] },
  { id: "L7", text: "Copper demand against counted mine supply → the coverage residual", status: "projected",
    links: [] },
  { id: "L8", text: "Copper → companies", status: "described",
    links: [{ href: "/theses/copper", label: "Copper thesis" }] },
];

export const CHAIN_NOTE = "Electrification is measured in the retained sources; the AI part of the chain is named but "
  + "not measured.";
export const CHAIN_LINKS = ["/library/research/semiconductor-policy", "/findings", "/findings/g17", "/theses/copper"];
