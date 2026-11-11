// Selections and words for each metal's research sections on the metals page (Stage 2): the snapshot, the supply
// chain, concentration, industrial uses, geopolitical exposure and economic transmission. Nothing here does arithmetic
// on a figure: a helper picks what the reply holds (already read and recomputed by metals.ts and metalsStage2.ts), or
// writes a figure the server shows in the page's words.
import { USGS_NUMBER, type Chapter, type MetalsView, type Series } from "./metals.ts";
import { reservesOf, type CitedPassage, type Indicators, type Link, type Ref, type ResearchMetal, type RiskChapter,
  type Stage, type UseEntry } from "./metalsStage2.ts";

// The IEA workbook's own scenario names and years (metals_iea.py, metals_iea_uses.py); the reader checks every key.
export const SCENARIOS = [["cps", "Current Policies scenario"], ["steps", "Stated Policies scenario"],
  ["hd", "High Demand Scenario"]] as const;
export const DEMAND_YEARS = ["2030", "2035", "2040", "2045", "2050"];

export const FINAL_PRODUCTS = "Final products: no retained source covers this stage.";
export const NO_EVENT = "No verified event is retained for this metal. Events appear here only from a retained primary "
  + "source (an official publication or a filing), dated.";
/** A stage USGS prints no 2025 production table for: named as missing, never filled from another stage. */
export const missingStage = (stage: "mining" | "refining") => `USGS's file has no ${stage} table for this metal`;
export const STAGE_WORDS: Readonly<Record<Stage["stage"], string>> = {
  mining: "Mining", refining: "Refining", other: "Stage as USGS prints it" };
export const LINK_LABELS: Readonly<Record<Link["kind"], string>> = {
  measured: "Measured", stated: "Stated by a source",
  hypothesis: "Hypothesis — not measured or stated by a retained source" };

/** A part as one metal's sections read it: shown with its value, or withheld with its problem (shown once). */
export type Part<T> = { shown: true; value: T } | { shown: false; problem: string };
export interface MetalParts {
  /** The metal's concentration and supply-chain entry; available exactly when the USGS part is. */
  risk: Part<RiskChapter>;
  /** The IEA energy-technology entries mapped to this chapter (often none). */
  uses: Part<UseEntry[]>;
  /** The assistant-written notes for this metal, or null when none are written for it. */
  research: Part<ResearchMetal | null>;
  writtenBy: string;
}

const problemOf = (problem: string | null) => problem ?? "Not in the reply";

/** The metal's risk entry, or null when the risk part is withheld. */
export function riskOf(view: MetalsView, id: string): RiskChapter | null {
  if (view.risk.state !== "available") return null;
  return (view.risk.chapters as RiskChapter[]).find((item) => item.id === id) ?? null;
}

/** What each of a metal's research sections reads from the three Stage 2 parts. */
export function partsFor(view: MetalsView, id: string): MetalParts {
  const risk = riskOf(view, id);
  const { uses, research } = view;
  return {
    risk: risk !== null ? { shown: true, value: risk } : { shown: false, problem: problemOf(view.risk.problem) },
    uses: uses.state === "available"
      ? { shown: true, value: (uses.entries as UseEntry[]).filter((item) => item.chapter === id) }
      : { shown: false, problem: problemOf(uses.problem) },
    research: research.state === "available"
      ? { shown: true, value: Object.hasOwn(research.metals, id) ? research.metals[id] : null }
      : { shown: false, problem: problemOf(research.problem) },
    writtenBy: research.written_by,
  };
}

/** Python's f"{n:,}" on a whole-number string. */
const grouped = (digits: string) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** An HHI as the page writes it: its two bounds "1,037–1,206", or one number when they are equal. */
export function hhiText(low: string, high: string): string {
  const [a, b] = [grouped(low), grouped(high)];
  return a === b ? a : `${a}–${b}`;
}

/** The named countries' coverage, written beside every HHI. */
export function coverageText(namedShare: string, overTotal: boolean | null): string {
  return overTotal === true ? `named countries ${namedShare}%, over the printed total`
    : `named countries ${namedShare}% of the world total`;
}

/** The named sources' coverage of US imports, beside an import-source HHI (the whole is 100). */
export const importCoverageText = (namedShare: string) => `named sources ${namedShare}% of US imports`;

/** US net import reliance as printed: a plain number gets its percent sign; a code or a bound (">50") stays as printed. */
export const relianceText = (value: string) => (USGS_NUMBER.test(value.trim()) ? `${value}%` : value);

/** How many 2025 net import reliance figures USGS prints for a chapter. The headline is the first (ruling R10); where
 * there are more, each reliance figure is named by its commodity and the headline says it is one of them. */
export const relianceCount = (chapter: Chapter) => chapter.reliance.filter((row) => row.year === "2025").length;
/** Beside the headline reliance of a chapter that prints more than one 2025 figure. */
export const relianceOneOf = (count: number) => `One of ${count} 2025 figures USGS prints for this chapter`;

/** A cited passage's source and place as the page writes it: "Title · Publisher, edition · place", or null when the
 * thesis cannot be read (no source is known). The edition, not the edition date, which is an ordering key. */
export function passagePlace(evidence: CitedPassage["evidence"]): string | null {
  if (evidence.title === null || evidence.publisher === null || evidence.edition === null) return null;
  return `${evidence.title} · ${evidence.publisher}, ${evidence.edition} · ${evidence.where ?? ""}`;
}

/** The 2025 stage a series id names, or null (a reserves series, or no stage at all). */
export const stageOfSeries = (risk: RiskChapter, id: string | null): Stage | null =>
  risk.stages.find((stage) => stage.series === id) ?? null;

/** The first mining and the first refining stage that show a leader: the pair `leaders_differ` compares. */
export function leaderPair(risk: RiskChapter): { mining: Stage; refining: Stage } | null {
  const first = (name: Stage["stage"]) => risk.stages.find((stage) => stage.stage === name && stage.leader.shown !== null);
  const [mining, refining] = [first("mining"), first("refining")];
  return mining !== undefined && refining !== undefined ? { mining, refining } : null;
}

/** The stage ladder: mining, then refining (a missing one named in its place), then any other printed stage. */
export function ladder(risk: RiskChapter): ({ kind: "stage"; stage: Stage } | { kind: "missing"; stage: "mining" | "refining" })[] {
  const step = (name: "mining" | "refining") => {
    const found = risk.stages.filter((stage) => stage.stage === name);
    return found.length > 0 ? found.map((stage) => ({ kind: "stage" as const, stage }))
      : risk.missing_stages.includes(name) ? [{ kind: "missing" as const, stage: name }] : [];
  };
  return [...step("mining"), ...step("refining"),
    ...risk.stages.filter((stage) => stage.stage === "other").map((stage) => ({ kind: "stage" as const, stage }))];
}

/** Each 2025 production and reserves series with its indicators, in the file's order, and its stage when it has one. */
export function concentrationRows(chapter: Chapter, risk: RiskChapter):
  { series: Series; indicators: Indicators; stage: Stage | null }[] {
  return Object.entries(risk.series).flatMap(([id, indicators]) => {
    const series = chapter.series.find((item) => item.id === id);
    return series === undefined ? [] : [{ series, indicators, stage: stageOfSeries(risk, id) }];
  });
}

/** A passage whose quote is shown: verified on this read, with its quote. */
export const verified = (cited: CitedPassage) => cited.evidence.state === "verified" && cited.evidence.quote !== null;

/** How many links of each kind a chain holds, for its summary line: a stated link counts as stated only when its
 * quote is verified on this read, and as a withheld quote otherwise. */
export function linkCounts(links: Link[]): { measured: number; stated: number; withheld: number; hypothesis: number } {
  const counts = { measured: 0, stated: 0, withheld: 0, hypothesis: 0 };
  for (const link of links) {
    if (link.kind === "stated" && !verified(link)) counts.withheld += 1;
    else counts[link.kind] += 1;
  }
  return counts;
}

/** The events a metal's notes cite, split: those whose quote is verified on this read (the only events shown as
 * events), and those cited but not verified (shown apart, with their reasons). */
export function splitEvents<T extends CitedPassage>(events: T[]): { shown: T[]; unverified: T[] } {
  return { shown: events.filter(verified), unverified: events.filter((event) => !verified(event)) };
}

/**
 * The indicators of the series a measured HHI link names, so its coverage can stand beside its range: the first stage
 * entry of the link's stage, or for reserves the series of ruling R1 (the same resolution as metals_research and
 * metalsStage2). Null for any other link, or when no such series is held.
 */
export function linkIndicators(ref: Ref, chapter: Chapter, risk: RiskChapter): Indicators | null {
  if (!("stage" in ref) || ref.figure !== "hhi") return null;
  const id = ref.stage === "reserves" ? reservesOf(chapter, risk)[0]?.id
    : risk.stages.find((stage) => stage.stage === ref.stage)?.series;
  return id === undefined ? null : risk.series[id] ?? null;
}
