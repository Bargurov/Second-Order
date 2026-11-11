// The exposure map of a thesis page, read from the served reply's structured fields only: each company the thesis
// moves (its side and what its filing states), each company that moves a reason (the reason it names, and whether the
// figures it cites include that reason's latest measured figure), and each part's state. The map names no company and
// reads no wording to decide a link; it computes no number, and a part the server withholds gives the map its frame
// only (company, side, the reason it names, and that reason's title as served).
import type { Figure, Mover, Moved, Reason, ReasonState, Side, Statement, ThesisView } from "./thesis.ts";

/** The places a change in the copper price can reach in a company's accounts, kept apart. */
export type StageKey = "revenue" | "input_cost" | "selling_price" | "margin" | "cash_flow";
/** The kinds of line on the map: what a source states, a general mechanism and a link no retained figure measures. */
export type LinkKind = "stated" | "conditional" | "unmeasured";
/** A company that moves a reason: its figure is the reason's measure, it is related to the reason, or it is withheld. */
export type MoverKind = "measure" | "related" | "withheld";

/** The order in which a change in the copper price reaches each side, from the side the server labels. */
export const STAGES_OF: Record<Side, readonly StageKey[]> = {
  producer: ["revenue", "margin", "cash_flow"],
  consumer: ["input_cost", "selling_price", "margin", "cash_flow"],
};

/** Each stage in plain words: its name, what it is, and the condition under which a price change reaches it. */
export const STAGE_WORDS: Record<StageKey, { name: string; what: string; condition: string }> = {
  revenue: {
    name: "Revenue",
    what: "What it is paid for the copper it sells: the volume sold times the price it is sold at.",
    condition: "Moves with the copper price at the volumes and terms it sells on.",
  },
  input_cost: {
    name: "Input cost",
    what: "What it pays for the copper it buys and uses in what it makes.",
    condition: "Moves with the copper price where it buys at prices linked to the market.",
  },
  selling_price: {
    name: "Its own selling prices",
    what: "The prices it charges its own customers for what it makes.",
    condition: "Follow its input cost only as far, and as fast, as it passes the cost on.",
  },
  margin: {
    name: "Margin",
    what: "What is left after the cost of producing or buying; other costs move on their own, so a change in revenue " +
      "or in input cost is not the same change in margin.",
    condition: "Depends on how costs, volumes and selling prices move together, which the map does not measure.",
  },
  cash_flow: {
    name: "Operating cash flow",
    what: "The cash the operations bring in: margin after taxes, and after the cash tied up in working capital and " +
      "inventory.",
    condition: "Can differ from margin in timing: cash moves when goods are paid for, not when a price changes.",
  },
};

/** Each kind of line in plain words. */
export const LINK_WORDS: Record<LinkKind, { name: string; what: string }> = {
  stated: {
    name: "Stated in a source",
    what: "A retained source states it, or the company's own figure is what the reason measures; open it to read " +
      "the figure or passage.",
  },
  conditional: {
    name: "Conditional mechanism",
    what: "How an effect can travel if the condition named holds: general economics, not measured for this company.",
  },
  unmeasured: {
    name: "Not measured",
    what: "A relation the retained material names but does not measure: no size is known for it.",
  },
};

/** The three ideas the map is read with, in plain words. */
export const CONCEPTS = [
  {
    id: "incidence", term: "Incidence",
    text: "Who finally bears a cost, or keeps a gain, once prices have adjusted. It is not always the company that " +
      "first pays or first receives it: a cost passed on to customers is borne further along the chain.",
  },
  {
    id: "pass-through", term: "Pass-through",
    text: "A company passes a cost through when its own selling prices follow its input costs. Passing a cost on " +
      "does not by itself leave profit unchanged: selling prices can lag the cost (timing), the gap between the cost " +
      "of the material and the selling price can change (the spread), and inventory bought at an earlier cost can " +
      "move reported margins (inventory accounting such as FIFO). Each user's lane shows what its own filing states " +
      "about this, and the map adds nothing to it.",
  },
  {
    id: "operating-exposure", term: "Operating exposure",
    text: "How much of a company's revenue, costs, margin or cash flow moves with copper. A share of sales says how " +
      "much of the business copper is; a sensitivity says how much one stated line changes for a given change in " +
      "the price, under the assumptions the filing states. They answer different questions, and neither is a change " +
      "in profit unless the filing says so.",
  },
] as const;

export interface MapMover {
  id: string; company: string; reason: string; reasonTitle: string | null; reasonStatus: ReasonState | null;
  kind: MoverKind; link: LinkKind | null; mover: Mover; reasonOf: Reason | null;
}
export interface MapLane {
  id: string; company: string; side: Side; stages: readonly StageKey[]; shown: boolean; statement: Statement | null;
  stated: Figure | null; metric: string | null; computed: { usdPerUnit: string; sharePct: string | null } | null;
  moved: Moved;
}
export interface ExposureMap {
  movers: MapMover[]; lanes: MapLane[]; counts: { producer: number; consumer: number; movers: number };
}

/** Read only when the company and its reason both check; then it is the reason's measure when the figures it cites
 * include the reason's latest measured figure (the figure the reason's status is read from). */
function kindOf(mover: Mover, reason: Reason | null): MoverKind {
  if (mover.state !== "available" || reason === null || reason.state !== "available") return "withheld";
  return reason.measure !== null && mover.cites!.includes(reason.measure.latest.id) ? "measure" : "related";
}

const LINK_OF: Record<MoverKind, LinkKind | null> = { measure: "stated", related: "unmeasured", withheld: null };

export function exposureMap(view: ThesisView): ExposureMap {
  const reasons = new Map(view.reasons.map((reason) => [reason.id, reason]));
  const movers = view.exposure.movers.map((mover): MapMover => {
    const reason = reasons.get(mover.moves) ?? null;
    const kind = kindOf(mover, reason);
    return { id: mover.id, company: mover.company, reason: mover.moves, reasonTitle: reason?.title ?? null,
      reasonStatus: kind === "withheld" ? null : reason!.status, kind, link: LINK_OF[kind], mover, reasonOf: reason };
  });
  const lanes = view.exposure.moved.map((moved): MapLane => {
    const shown = moved.state === "available";
    const amount = shown ? moved.amount : null;
    return { id: moved.id, company: moved.company, side: moved.side, stages: STAGES_OF[moved.side], shown,
      statement: shown ? moved.how : null, stated: amount?.kind === "stated" ? amount.figure : null,
      metric: amount?.kind === "stated" ? amount.figure.measure : null,
      computed: amount?.kind === "computed" ? { usdPerUnit: moved.usd_per_unit!, sharePct: moved.share_pct } : null,
      moved };
  });
  return { movers, lanes, counts: { producer: lanes.filter((lane) => lane.side === "producer").length,
    consumer: lanes.filter((lane) => lane.side === "consumer").length, movers: movers.length } };
}

/** A lane's accessible name, from its frame only: the company and its side's short label ("producer"). */
export const laneLabel = (lane: Pick<MapLane, "company" | "side">, labels: Pick<ThesisView["labels"], "sides">) =>
  `${lane.company}, ${labels.sides[lane.side].split(":")[0].toLowerCase()}`;

/** A company's accessible name on the map, from its frame only: the company and the reason's title as served (null,
 * and so not named, when the title states a withheld figure). */
export const moverLabel = (mover: Pick<MapMover, "company" | "reasonTitle">) =>
  mover.reasonTitle === null ? `${mover.company}, moves a reason whose title is withheld`
    : `${mover.company}, moves the reason: ${mover.reasonTitle}`;
