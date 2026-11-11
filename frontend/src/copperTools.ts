// The copper tools (/api/tools/copper, copper-tools-view-0.1, second_order/copper_tools_view.py): the IEA coverage
// calculator's published baselines and the published producer unit-cost comparison, every figure checked by the
// server against its retained source on this machine. The reply is read fail-closed: a figure's value and a passage's
// text appear only when verified, and a source's state decides its items' states; every computed value is recomputed
// here exactly (BigInt fractions, copperNumbers.ts) from the figures it names and must equal what the server shows; an
// output with a missing figure must be withheld; perturbations keep their fixed order and kinds; producer rows must
// reconcile exactly to be shown. Each refusal names its place and rule, never a value. Nothing here requests anything
// outside this server.
import type { Loaded } from "./api";
import {
  add, div, equal, halfEven, int, make, mul, neg, ofPlain, POUND_KG, shownKt, sub, sum, type Rat,
} from "./copperNumbers.ts";
import { printed } from "./thesisNumbers.ts";

export const COPPER_VIEW_VERSION = "copper-tools-view-0.2";
export const CATALOG_VERSION = "copper-inputs-0.1";
export const ENGINE_VERSION = "copper-coverage-0.1";
export const PRODUCERS_VERSION = "copper-producers-0.2";
export const RECORD_VERSION = "copper-scenario-0.1";
export const ITEM_STATES = ["verified", "not_found", "unreadable", "source_changed", "source_missing"] as const;
export const SOURCE_STATES = ["verified", "changed", "missing"] as const;
export const RECORD_STATES = ["verified", "needs_revalidation", "unavailable", "invalid"] as const;
export const SCENARIO_IDS = ["cps", "steps", "hd"] as const;
export const YEARS = ["2030", "2035", "2040"] as const;
export const BASE_YEAR = "2025";
export const COMPONENT_IDS = ["solar", "wind", "other-low-emission", "ev", "grid-storage", "networks", "hydrogen"] as const;
export const LINE_IDS = [...COMPONENT_IDS, "energy", "other-uses", "total"] as const;
export const COUNTRY_IDS = ["chile", "drc", "peru", "china", "russia", "us", "rest"] as const;
export const DC_SCENARIOS = ["steps", "hd"] as const;
export const FLAG_IDS = ["hybrid", "technology_case", "user_value", "outside_published_spread",
  "reference_magnitude"] as const;
export const REFERENCE_IDS = ["ptfi-sales-change", "scco-guidance-change"] as const;
const PERTURBATION_ORDER = ["ev:published_scenario_value", "networks:published_scenario_value",
  "networks:published_technology_case", "mine:reference_magnitude", "mine:user_declared",
  "joint:published_totals"];
const SHA = /^[0-9a-f]{64}$/;
const UNREACHABLE = "The local API did not answer. Start it with: python -m second_order serve";

export type ItemState = (typeof ITEM_STATES)[number];
export type ScenarioId = (typeof SCENARIO_IDS)[number];
export type Year = (typeof YEARS)[number];

export interface FigureView {
  id: string; source: string; measure: string; unit: string; year: string | null; scenario: string | null;
  where: string; state: ItemState; problem: string | null; value: string | null; as_shown: string | null;
}
export interface PassageView { id: string; source: string; where: string; state: ItemState; problem: string | null;
  text: string | null }
export interface SourceView {
  id: string; publisher: string; title: string; edition: string; edition_date: string; url: string; kind: string;
  origin: string; terms: { licence: string; note: string }; retrieved_at: string; sha256: string;
  state: (typeof SOURCE_STATES)[number]; detail: string;
}
/** A computed value: the equation, the figures it uses, those not verified, and the exact value with its shown text. */
export interface Computed { equation: string; uses: string[]; withheld: string[]; value: string | null;
  shown: string | null; rounded?: boolean | null }
export interface Published { figure: string; value: string | null; withheld: string[] }
export interface Case { label: string; scenario?: string; reference?: string; value?: Published; effect?: Computed;
  magnitude?: Computed; effect_if_lower?: Computed; effect_if_higher?: Computed }
export interface Perturbation { control: "ev" | "networks" | "mine" | "joint"; kind: string; cases: Case[] }
export interface CoverageAt { demand: Published; mine: Published; residual: Computed; share_pct: Computed }
export interface Baseline {
  scenario: ScenarioId; year: Year; demand: (Published & { line: string })[]; epsilon: Computed; delta: Computed;
  mine: (Published & { country: string })[]; refining: Published; coverage: CoverageAt; base: CoverageAt;
  decomposition: { demand_rows: { line: string; change: Computed }[]; epsilon_change: Computed;
    delta_change: Computed; mine_change: Computed; residual_change: Computed };
  perturbations: Perturbation[];
}
export interface BaseYear { year: string; demand: (Published & { line: string })[]; epsilon: Computed; delta: Computed;
  mine: (Published & { country: string })[]; refining: Published; networks_dc: Published; coverage: CoverageAt }
export interface Control { id: "ev" | "networks" | "mine"; label: string; unit: string; meaning: string;
  options: string[]; not_offered: string }
export interface CostRow { id: string; producer: string; division: string; method: string;
  figures: { before: string; credits: string[]; other: string[]; net: string; co_product: string | null;
    revenue: string | null; gross_profit: string | null; volume: string; excluded: string | null };
  state: "available" | "withheld"; reconciles: boolean | null; withheld: string[]; problem: string | null }
export interface Margin extends Computed { row: string; gross_profit: string | null;
  state: "available" | "withheld" | "not_retained"; problem?: string }
export interface Project {
  id: string; name: string; company: string; type: "brownfield" | "greenfield"; type_text: string; capacity: string[];
  capacity_unit: "mlb_per_year" | "t_per_year"; capacity_label: string | null; capital: string | null;
  incentive: string[]; break_even: string[]; break_even_condition: string | null; construction: string | null;
  earlier_capital: string | null; by_product: string | null; passages: string[]; caveats: string[];
  statement: Statement | null; capital_per_annual_tonne: Computed[]; intensity_problem: string | null;
}
/** A Bagdad row's stamp: which company statement the row is, with its source's date and document. */
export interface Statement { kind: "company_estimates" | "earlier_statement"; text: string; date_text: string;
  date: string | null; document: string; source: string; terms: string | null }
/** A record of Bagdad's later statement, read from the verified FCX research (copper_linked on the server). */
export interface LinkedEntry { id: string; kind: "figure" | "passage"; role: string; state: "available" | "withheld";
  value: string | null; display: string | null; unit: string | null; approximate: boolean; source: string;
  page: number; quote: string | null; problem: string | null }
export interface LinkedSource { id: string; title: string; form: string; date: string | null; date_kind: string;
  state: string }
export interface LinkedBlock { state: "available" | "withheld"; problem: string | null;
  sources: Record<string, LinkedSource>; records: Record<string, LinkedEntry> }
export interface MatrixRow { dimension: string; fcx: string; scco: string; comparable: string; cites: string[] }
export interface RecordItem { id: string; created_at: string | null; label: string | null;
  baseline: { scenario: ScenarioId; year: Year } | null; assumptions: Assumptions | null;
  state: (typeof RECORD_STATES)[number]; problems: string[]; result: unknown; catalog_current: boolean }
export interface Assumptions {
  ev: null | { source: "scenario"; scenario: ScenarioId } | { source: "value"; kt: string };
  networks: null | { source: "scenario" | "technology_case"; scenario: ScenarioId } | { source: "value"; kt: string };
  mine: null | { source: "total"; kt: string; reference: string | null }
    | { source: "countries"; factors: Partial<Record<(typeof COUNTRY_IDS)[number], string>> };
}
export interface CopperToolsView {
  view_version: string;
  catalog: { version: string; sha256: string; items: number; verified: number };
  sources: SourceView[];
  figures: Record<string, FigureView>;
  passages: Record<string, PassageView>;
  coverage: {
    engine_version: string; definitions_sha256: string; base_year: string; years: Year[];
    scenarios: { id: ScenarioId; label: string }[]; components: { id: string; label: string }[];
    totals: { id: string; label: string }[]; countries: { id: string; label: string }[];
    dc_scenarios: string[]; dc_label: string; base: BaseYear; baselines: Baseline[];
    refining: { source_name: string; sheet_title: string; notes: string[]; unknowns: string[]; interpretation: string };
    controls: Control[]; flags: Record<string, string>; references: { id: string; label: string; uses: string[] }[];
    not_computed: string[];
  };
  producers: {
    version: string; title: string; matrix: MatrixRow[]; rows: CostRow[]; margins: Margin[]; projects: Project[];
    capital_panel: { rate_pct: null; years: null; ignores: string[]; rate_rule: string; years_rule: string };
    can_establish: string; cannot_establish: string[]; brownfield_greenfield: string;
    notes: { incentive_break_even: string; no_path: string };
  };
  linked: LinkedBlock;
  scenarios: { record_version: string; records: RecordItem[]; other_versions: number; labels: Record<string, string> };
  labels: { item_states: Record<string, string>; units: Record<string, string>; record_states: Record<string, string> };
  provider_called: false;
}

// ---------------------------------------------------------------- reading helpers

export class Refusal extends Error {}
export const refuse = (where: string, rule: string): never => { throw new Refusal(`${where}: ${rule}`); };
export const isRec = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
export const need = (condition: boolean, where: string, rule: string) => { if (!condition) refuse(where, rule); };
export const sameList = (a: readonly unknown[], b: readonly unknown[]) =>
  a.length === b.length && a.every((value, index) => value === b[index]);

export const demandId = (line: string, scenario: string | null, year: string) =>
  scenario === null ? `iea-demand-${line}-${BASE_YEAR}` : `iea-demand-${line}-${scenario}-${year}`;
export const mineId = (country: string, year: string) => `iea-mine-${country}-${year}`;
export const dcId = (scenario: string | null, year: string) =>
  scenario === null ? `iea-networks-dc-${BASE_YEAR}` : `iea-networks-dc-${scenario}-${year}`;

/** A reading context: the reply's verified figure values, as exact fractions. */
export class Figures {
  readonly values = new Map<string, Rat>();
  readonly view: CopperToolsView;
  constructor(view: CopperToolsView) {
    this.view = view;
    for (const [id, figure] of Object.entries(view.figures)) {
      if (figure.value !== null) this.values.set(id, ofPlain(figure.value) as Rat);
    }
    for (const [id, entry] of Object.entries(view.linked?.records ?? {})) {
      if (entry.kind === "figure" && entry.value !== null) this.values.set(id, ofPlain(entry.value) as Rat);
    }
  }
  has = (id: string) => this.values.has(id);
  at = (id: string): Rat => this.values.get(id) ?? refuse(id, "is used but not verified");
  unit = (id: string) => this.view.figures[id]?.unit ?? this.view.linked?.records[id]?.unit
    ?? refuse(id, "is not in the reply");
}

export function checkPublished(entry: Published, expected: string, figures: Figures, where: string) {
  need(entry.figure === expected, where, `names ${entry.figure}, not ${expected}`);
  const value = figures.view.figures[expected]?.value ?? null;
  need(entry.value === value, where, "does not carry the figure's verified value");
  need(sameList(entry.withheld, value === null ? [expected] : []), where, "withheld does not follow the figure");
}

/** A computed item: withheld lists exactly its unverified figures; with none withheld its exact value is `expected`
 * (or, for a ratio, its shown text is `ratio` at `places`), shown by the server's rule. */
export function checkComputed(item: Computed, where: string, figures: Figures, expected: () => Rat,
                       places: number | "kt" = "kt", ratio = false) {
  need(isRec(item) && Array.isArray(item.uses) && Array.isArray(item.withheld), where, "is not a computed value");
  const unverified = new Set(item.uses.filter((id) => !figures.has(id)));
  need(item.withheld.length === unverified.size && item.withheld.every((id) => unverified.has(id)), where,
       "withheld does not list exactly its unverified figures");
  if (unverified.size > 0) {
    need((item.value ?? null) === null && item.shown === null, where,
         "shows a value although a figure it uses is withheld");
    return;
  }
  const value = expected();
  if (ratio) {
    need((item.value ?? null) === null && item.shown === halfEven(value, places as number), where,
         "its shown value does not follow from its figures");
    return;
  }
  if (item.value !== undefined) {
    const served = ofPlain(item.value);
    need(served !== null && equal(served, value), where, "does not follow from the figures it uses");
  }
  const shown = places === "kt" ? shownKt(value) : { shown: halfEven(value, places), rounded: true };
  need(item.shown === shown.shown, where, "is not shown as the server's rule shows it");
  if (places === "kt" && item.rounded !== undefined) need(item.rounded === shown.rounded, where, "rounded flag differs");
}

// ---------------------------------------------------------------- the coverage calculator

function epsilonOf(figures: Figures, scenario: string | null, year: string): Rat {
  return sub(figures.at(demandId("energy", scenario, year)),
             sum(COMPONENT_IDS.map((line) => figures.at(demandId(line, scenario, year)))));
}
function deltaOf(figures: Figures, scenario: string | null, year: string): Rat {
  return sub(figures.at(demandId("total", scenario, year)),
             add(figures.at(demandId("energy", scenario, year)), figures.at(demandId("other-uses", scenario, year))));
}

function checkCoverage(at: CoverageAt, scenario: string | null, year: string, figures: Figures, where: string) {
  const demand = demandId("total", scenario, year);
  const mine = mineId("total", year);
  checkPublished(at.demand, demand, figures, `${where}.demand`);
  checkPublished(at.mine, mine, figures, `${where}.mine`);
  need(sameList(at.residual.uses, [demand, mine]), `${where}.residual`, "does not use D and counted mine supply");
  checkComputed(at.residual, `${where}.residual`, figures, () => sub(figures.at(demand), figures.at(mine)));
  checkComputed(at.share_pct, `${where}.share_pct`, figures,
                () => mul(div(sub(figures.at(demand), figures.at(mine)), figures.at(demand)), int(100)), 1, true);
}

export function checkPerturbations(rows: Perturbation[], scenario: ScenarioId, year: Year, figures: Figures, where: string,
                            mineChange: Rat | null) {
  const kinds = rows.map((row) => `${row.control}:${row.kind}`);
  const expected = PERTURBATION_ORDER.filter((kind) => (kind !== "networks:published_technology_case"
    || (DC_SCENARIOS as readonly string[]).includes(scenario)) && (kind !== "mine:user_declared" || mineChange !== null));
  need(sameList(kinds, expected), where, "rows are not in the fixed order of controls and kinds");
  const others = SCENARIO_IDS.filter((key) => key !== scenario);
  rows.forEach((row, index) => {
    const place = `${where}[${index}]`;
    if (row.kind === "published_scenario_value" || row.kind === "published_totals") {
      const line = row.control === "ev" ? "ev" : row.control === "networks" ? "networks" : "total";
      need(sameList(row.cases.map((item) => item.scenario), others), place, "does not compare the other scenarios");
      row.cases.forEach((item, n) => {
        const other = demandId(line, item.scenario as string, year);
        const selected = demandId(line, scenario, year);
        checkPublished(item.value as Published, other, figures, `${place}.cases[${n}].value`);
        checkComputed(item.effect as Computed, `${place}.cases[${n}].effect`, figures,
                      () => sub(figures.at(other), figures.at(selected)));
      });
    } else if (row.kind === "published_technology_case") {
      const [item] = row.cases;
      need(row.cases.length === 1 && item.scenario === scenario, place, "is not the scenario's own technology case");
      checkPublished(item.value as Published, dcId(scenario, year), figures, `${place}.value`);
      checkComputed(item.effect as Computed, `${place}.effect`, figures,
                    () => sub(figures.at(dcId(scenario, year)), figures.at(demandId("networks", scenario, year))));
    } else if (row.kind === "reference_magnitude") {
      need(sameList(row.cases.map((item) => item.reference), REFERENCE_IDS), place, "names other references");
      row.cases.forEach((item, n) => {
        const magnitude = () => referenceMagnitude(figures, item.reference as string);
        checkComputed(item.magnitude as Computed, `${place}.cases[${n}].magnitude`, figures, magnitude);
        checkComputed(item.effect_if_lower as Computed, `${place}.cases[${n}].lower`, figures, magnitude);
        checkComputed(item.effect_if_higher as Computed, `${place}.cases[${n}].higher`, figures,
                      () => neg(magnitude()));
      });
    } else {
      const effect = row.cases[0]?.effect as Computed;
      need(mineChange !== null && row.cases.length === 1 && effect.value !== null &&
           equal(ofPlain(effect.value) as Rat, neg(mineChange as Rat)), place, "is not minus the entered change");
    }
  });
}

/** A company disclosure as copper kt: PTFI's sales change (billion lb x 1,000 x 0.45359237) or Southern Copper's
 * guidance change (tonnes / 1,000). */
export function referenceMagnitude(figures: Figures, reference: string): Rat {
  if (reference === "ptfi-sales-change") {
    return mul(mul(sub(figures.at("fcx-ptfi-sales-guidance-2025"), figures.at("fcx-ptfi-sales-guidance-2026")),
                   int(1000)), POUND_KG);
  }
  return div(sub(figures.at("scco-production-guidance-2025"), figures.at("scco-production-guidance-2026")),
             int(1000));
}

function checkBaseline(base: Baseline, figures: Figures, where: string) {
  const { scenario, year } = base;
  need((SCENARIO_IDS as readonly string[]).includes(scenario) && (YEARS as readonly string[]).includes(year), where,
       "names an unknown scenario or year");
  need(sameList(base.demand.map((row) => row.line), LINE_IDS), `${where}.demand`, "rows are not the published rows");
  base.demand.forEach((row) => checkPublished(row, demandId(row.line, scenario, year), figures,
                                              `${where}.demand.${row.line}`));
  need(sameList(base.mine.map((row) => row.country), [...COUNTRY_IDS, "total"]), `${where}.mine`, "rows differ");
  base.mine.forEach((row) => checkPublished(row, mineId(row.country, year), figures, `${where}.mine.${row.country}`));
  checkPublished(base.refining, `iea-refining-total-${year}`, figures, `${where}.refining`);
  checkComputed(base.epsilon, `${where}.epsilon`, figures, () => epsilonOf(figures, scenario, year));
  checkComputed(base.delta, `${where}.delta`, figures, () => deltaOf(figures, scenario, year));
  checkCoverage(base.coverage, scenario, year, figures, `${where}.coverage`);
  checkCoverage(base.base, null, BASE_YEAR, figures, `${where}.base`);
  const d = base.decomposition;
  need(sameList(d.demand_rows.map((row) => row.line), [...COMPONENT_IDS, "energy", "other-uses", "total"]),
       `${where}.decomposition`, "rows are not the published rows");
  d.demand_rows.forEach((row) => checkComputed(row.change, `${where}.decomposition.${row.line}`, figures,
    () => sub(figures.at(demandId(row.line, scenario, year)), figures.at(demandId(row.line, null, BASE_YEAR)))));
  checkComputed(d.epsilon_change, `${where}.decomposition.epsilon`, figures,
                () => sub(epsilonOf(figures, scenario, year), epsilonOf(figures, null, BASE_YEAR)));
  checkComputed(d.delta_change, `${where}.decomposition.delta`, figures,
                () => sub(deltaOf(figures, scenario, year), deltaOf(figures, null, BASE_YEAR)));
  checkComputed(d.mine_change, `${where}.decomposition.mine`, figures,
                () => sub(figures.at(mineId("total", year)), figures.at(mineId("total", BASE_YEAR))));
  checkComputed(d.residual_change, `${where}.decomposition.residual`, figures,
                () => sub(sub(figures.at(demandId("total", scenario, year)), figures.at(mineId("total", year))),
                          sub(figures.at(demandId("total", null, BASE_YEAR)), figures.at(mineId("total", BASE_YEAR)))));
  checkPerturbations(base.perturbations, scenario, year, figures, `${where}.perturbations`, null);
}

// ---------------------------------------------------------------- the producer comparison

function tonnesPerYear(figures: Figures, capacity: string, unit: string): Rat {
  const value = figures.at(capacity);
  return unit === "mlb_per_year" ? mul(mul(value, int(1000000)), div(POUND_KG, int(1000))) : value;
}
export function capitalUsd(figures: Figures, capital: string): Rat {
  const scale = figures.unit(capital) === "usd_billion" ? 1000000000 : figures.unit(capital) === "usd_million"
    ? 1000000 : refuse(capital, "is not stated in million or billion US dollars");
  return mul(figures.at(capital), int(scale));
}
export function poundsPerYear(figures: Figures, capacity: string, unit: string): Rat {
  const value = figures.at(capacity);
  return unit === "mlb_per_year" ? mul(value, int(1000000)) : div(mul(value, int(1000)), POUND_KG);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2001-02-03" as "3 Feb 2001", from the text itself (never a Date, so no time zone can move the day). */
export function statementDate(iso: string | null): string {
  const match = iso === null ? null : /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const month = match ? Number(match[2]) : 0;
  return match && month >= 1 && month <= 12 ? `${Number(match[3])} ${MONTHS[month - 1]} ${match[1]}`
    : "date not available";
}

/** The linked block is all available or all withheld, a withheld entry carries nothing from a document, and an
 * available figure's printed figure reads as its value. */
function checkLinked(view: CopperToolsView) {
  const block = view.linked;
  need(isRec(block) && (block.state === "available" || block.state === "withheld") && isRec(block.records), "linked",
       "is not the linked statement");
  for (const [id, entry] of Object.entries(block.records)) {
    const where = `linked.${id}`;
    need(entry.id === id && (entry.kind === "figure" || entry.kind === "passage"), where, "is not a linked entry");
    need(entry.state === "available" || (entry.value === null && entry.display === null && entry.quote === null),
         where, "a withheld entry carries a value");
    need(entry.kind === "figure" || (entry.value === null && entry.display === null), where,
         "a passage carries no value");
    if (entry.kind === "figure" && entry.state === "available") {
      const value = typeof entry.value === "string" ? ofPlain(entry.value) : null;
      const shown = typeof entry.display === "string" ? printed(entry.display) : null;
      need(value !== null && shown !== null && equal(value, make(shown.n, 10n ** BigInt(shown.s))), where,
           "its printed figure is not its value");
    }
  }
  need(Object.values(block.records).every((entry) => entry.state === block.state), "linked",
       "is not all available or all withheld");
  need((block.state === "available") === (block.problem === null), "linked", "its problem does not follow its state");
}

// The fields of a project row that name records: the roles a linked record may hold there (the later statement), and
// where a catalogue row finds it ("figures", "passages", or nowhere: break-even and construction are linked only).
const NAMED: [keyof Project, string[], "figures" | "passages" | null][] = [
  ["capital", ["capital"], "figures"], ["capacity", ["capacity"], "figures"], ["incentive", ["incentive"], "figures"],
  ["earlier_capital", [], "figures"], ["by_product", [], "figures"],
  ["break_even", ["break_even"], null], ["break_even_condition", ["break_even_condition"], null],
  ["construction", ["construction"], null],
  ["passages", ["decision", "start"], "passages"], ["caveats", ["caveat"], "passages"],
];

/** Each Bagdad row is one company statement: its figures, pairs and passages all come from the linked records (the
 * later statement) or all from the catalogue (the earlier one), and break-even is never an incentive price. Every
 * record a row names exists in its own statement, in the role of the field that names it. */
function checkStatements(view: CopperToolsView) {
  const linked = view.linked.records;
  const role = (id: string | null) => (id === null ? null : linked[id]?.role ?? null);
  for (const project of view.producers.projects) {
    const where = `producers.projects.${project.id}`;
    const later = project.statement?.kind === "company_estimates";
    const inFamily = (id: string) => (id in linked) === later;
    need(!project.incentive.some((id) => role(id) === "break_even" || role(id) === "break_even_condition"), where,
         "an incentive price is never a break-even record");
    need(project.break_even.every((id) => role(id) === "break_even")
      && (project.break_even_condition === null || role(project.break_even_condition) === "break_even_condition"),
         where, "break-even comes only from break-even records");
    const pairs = [[project.capital, ...project.capacity], ...project.capital_per_annual_tonne.map((item) => item.uses)];
    need(pairs.every((ids) => ids.filter((id): id is string => id !== null).every(inFamily)), where,
         "a pair spans two statements");
    need([...project.passages, ...project.caveats].every((id) => inFamily(id)
      && (later ? linked[id].kind === "passage" : id in view.passages)), where,
         "a passage comes from another statement");
    need(project.statement === null || ["company_estimates", "earlier_statement"].includes(project.statement.kind),
         where, "names an unknown statement");
    for (const [field, roles, catalogue] of NAMED) {
      const named = project[field];
      for (const id of Array.isArray(named) ? named : [named]) {
        if (id === null) continue;
        const own = later ? typeof id === "string" && id in linked && roles.includes(linked[id].role)
            && linked[id].kind === (catalogue === "passages" ? "passage" : "figure")
          : catalogue !== null && typeof id === "string" && id in view[catalogue];
        need(own, `${where}.${field}`, `names ${id}, not a record of its statement in this role`);
      }
    }
  }
}

function checkProducers(view: CopperToolsView, figures: Figures) {
  const p = view.producers;
  need(p.version === PRODUCERS_VERSION && p.title === "Published producer unit-cost comparison", "producers",
       "is not the published producer unit-cost comparison");
  need(p.capital_panel.rate_pct === null && p.capital_panel.years === null, "producers.capital_panel",
       "has a default input");
  const states = new Map<string, string>();
  for (const row of p.rows) {
    const ids = [row.figures.before, ...row.figures.credits, ...row.figures.other, row.figures.net];
    const missing = ids.filter((id) => !figures.has(id));
    const where = `producers.rows.${row.id}`;
    need(sameList(row.withheld, missing), where, "withheld does not list its unverified figures");
    let reconciles: boolean | null = null;
    if (missing.length === 0 && ids.length > 2) {
      reconciles = equal(sum(ids.slice(0, -1).map(figures.at)), figures.at(row.figures.net));
    }
    const available = missing.length === 0 && reconciles !== false;
    need(row.reconciles === (missing.length === 0 ? reconciles : null), where, "its reconciliation does not follow");
    need(row.state === (available ? "available" : "withheld"), where, "its state does not follow its figures");
    states.set(row.id, row.state);
  }
  for (const margin of p.margins) {
    const where = `producers.margins.${margin.row}`;
    if (margin.row === "scco") {
      need(margin.state === "not_retained" && margin.value === null && margin.shown === null, where,
           "shows a margin without the company's own revenue per pound");
      continue;
    }
    const [revenue, net] = margin.uses;
    const available = states.get(margin.row) === "available" && figures.has(revenue) && figures.has(net);
    need(margin.state === (available ? "available" : "withheld"), where, "its state does not follow its row");
    if (!available) {
      need(margin.value === null && margin.shown === null, where, "shows a withheld margin");
      continue;
    }
    checkComputed(margin, where, figures, () => sub(figures.at(revenue), figures.at(net)), 2);
  }
  checkStatements(view);
  for (const project of p.projects) {
    const where = `producers.projects.${project.id}`;
    need(project.capital === null ? project.capital_per_annual_tonne.length === 0
      : project.capital_per_annual_tonne.length === project.capacity.length, where, "capital intensity is misplaced");
    project.capital_per_annual_tonne.forEach((item, n) => {
      const capacity = project.capacity[n];
      need(sameList(item.uses, [project.capital as string, capacity]), `${where}[${n}]`, "uses other figures");
      checkComputed(item, `${where}[${n}]`, figures, () => div(capitalUsd(figures, project.capital as string),
        tonnesPerYear(figures, capacity, project.capacity_unit)), 0, true);
    });
  }
}

// ---------------------------------------------------------------- the whole reply

/** Null when the reply passes every check, else the first refusal's place and rule. */
export function copperRefusal(body: unknown): string | null {
  try {
    need(isRec(body), "reply", "is not an object");
    const view = body as unknown as CopperToolsView;
    need(view.view_version === COPPER_VIEW_VERSION, "view_version", `expected ${COPPER_VIEW_VERSION}`);
    need(view.provider_called === false, "provider_called", "a read never calls a provider");
    need(view.catalog?.version === CATALOG_VERSION, "catalog.version", `expected ${CATALOG_VERSION}`);
    need(SHA.test(view.catalog.sha256), "catalog.sha256", "expected a SHA-256");
    const sources = new Map(view.sources.map((source) => [source.id, source.state]));
    for (const source of view.sources) {
      need((SOURCE_STATES as readonly string[]).includes(source.state), `sources.${source.id}`, "unknown state");
    }
    const items = [...Object.values(view.figures), ...Object.values(view.passages)];
    for (const item of items) {
      const where = `items.${item.id}`;
      need((ITEM_STATES as readonly string[]).includes(item.state), where, "unknown state");
      const source = sources.get(item.source) ?? refuse(where, "names no listed source");
      const allowed = source === "missing" ? ["source_missing"] : source === "changed" ? ["source_changed"]
        : ["verified", "not_found", "unreadable"];
      need(allowed.includes(item.state), where, "its state does not follow its source's state");
      need((item.state === "verified") === (item.problem === null), where, "a problem goes with every other state");
    }
    for (const [id, figure] of Object.entries(view.figures)) {
      need(figure.id === id, `figures.${id}`, "is filed under another id");
      if (figure.state !== "verified") {
        need(figure.value === null && figure.as_shown === null, `figures.${id}`, "shows a value that is not verified");
        continue;
      }
      const value = ofPlain(figure.value);
      const parenthesised = /^\((.+)\)$/.exec(figure.as_shown ?? "");
      const shown = parenthesised ? printed(parenthesised[1]) : printed(figure.as_shown ?? "");
      need(value !== null && shown !== null && equal(value, parenthesised
        ? neg(make(shown.n, 10n ** BigInt(shown.s))) : make(shown.n, 10n ** BigInt(shown.s))), `figures.${id}`,
           "its printed value is not its value");
    }
    for (const [id, passage] of Object.entries(view.passages)) {
      need(passage.id === id && (passage.state === "verified") === (passage.text !== null), `passages.${id}`,
           "shows text that is not verified");
    }
    need(view.catalog.items === items.length, "catalog.items", "does not count the figures and passages");
    need(view.catalog.verified === items.filter((item) => item.state === "verified").length, "catalog.verified",
         "does not count the verified items");
    checkLinked(view);
    const figures = new Figures(view);
    const c = view.coverage;
    need(c.engine_version === ENGINE_VERSION && SHA.test(c.definitions_sha256), "coverage", "unknown engine");
    need(sameList(c.years, YEARS) && sameList(c.scenarios.map((s) => s.id), SCENARIO_IDS), "coverage", "grid differs");
    need(c.baselines.length === SCENARIO_IDS.length * YEARS.length, "coverage.baselines", "expected every pair");
    c.baselines.forEach((base, index) => {
      need(base.scenario === SCENARIO_IDS[Math.floor(index / YEARS.length)] && base.year === YEARS[index % 3],
           `coverage.baselines[${index}]`, "is out of order");
      checkBaseline(base, figures, `coverage.baselines.${base.scenario}-${base.year}`);
    });
    checkCoverage(c.base.coverage, null, BASE_YEAR, figures, "coverage.base");
    checkComputed(c.base.epsilon, "coverage.base.epsilon", figures, () => epsilonOf(figures, null, BASE_YEAR));
    checkPublished(c.base.networks_dc, dcId(null, BASE_YEAR), figures, "coverage.base.networks_dc");
    need(c.refining.source_name === "Copper - Refining" && c.refining.unknowns.length === 3, "coverage.refining",
         "is not shown under its source name with its three unknowns");
    need(c.refining.notes.every((id) => id in view.passages), "coverage.refining.notes", "names no passage");
    need(sameList(c.controls.map((control) => control.id), ["ev", "networks", "mine"]), "coverage.controls",
         "expected the three controls of this version");
    need(sameList(Object.keys(c.flags), FLAG_IDS), "coverage.flags", "expected the flags of this version");
    checkProducers(view, figures);
    need(view.scenarios.record_version === RECORD_VERSION, "scenarios", `expected ${RECORD_VERSION}`);
    for (const record of view.scenarios.records) {
      need((RECORD_STATES as readonly string[]).includes(record.state) && SHA.test(record.id), `scenarios.${record.id}`,
           "unknown state or id");
      need((record.state === "verified") === (record.result !== null), `scenarios.${record.id}`,
           "a result is shown only for a verified record");
    }
    return null;
  } catch (error) {
    if (error instanceof Refusal) return error.message;
    if (error instanceof TypeError || error instanceof RangeError) return `reply: is not shaped as expected (${error.name})`;
    throw error;
  }
}

export async function fetchCopperTools(signal: AbortSignal): Promise<Loaded<CopperToolsView>> {
  let response: Response;
  try {
    response = await fetch("/api/tools/copper", { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal.aborted) throw error;
    return { state: "error", message: UNREACHABLE };
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = isRec(body) && typeof body.detail === "string" ? body.detail : `Unexpected response (${response.status}).`;
    return { state: response.status === 503 ? "not-prepared" : "error", message };
  }
  const refusal = copperRefusal(body);
  return refusal === null ? { state: "ready", data: body as CopperToolsView }
    : { state: "error", message: `The reply could not be read by this page (${refusal}).` };
}

