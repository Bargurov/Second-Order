// The copper tools' three POSTs (second_order/copper_tools_api.py): a scenario preview (writes nothing), one saved
// write-once record, and the capital-recovery panel (writes and stores nothing). Each reply is read fail-closed against
// the view the page already passed (copperTools.ts): D', M', R', its share and its change are recomputed exactly from
// the assumptions and the view's verified figures, the flags must be exactly those the assumptions set, the panel's
// capital recovery factor and every charge are recomputed as exact fractions (CRF(0, n) = 1/n at a zero rate). Nothing
// here requests anything outside this server.
import {
  BASE_YEAR, COUNTRY_IDS, FLAG_IDS, Figures, RECORD_STATES, SCENARIO_IDS, capitalUsd, checkComputed,
  checkPerturbations, dcId, demandId, isRec, mineId, need, poundsPerYear, referenceMagnitude, Refusal, sameList,
  type Assumptions, type Computed, type CopperToolsView, type Perturbation, type ScenarioId, type Year,
} from "./copperTools.ts";
import { add, div, equal, halfEven, int, lessThan, mul, ofPlain, pow, sub, sum, type Rat } from "./copperNumbers.ts";

export const PREVIEW_VERSION = "copper-scenario-preview-0.1";
export const SAVED_VERSION = "copper-scenario-saved-0.1";
export const SCENARIO_HEADER = "X-Second-Order-Scenario";

export interface AssessResult {
  scenario: ScenarioId; year: Year; assumptions: Assumptions; flags: { id: string; text: string }[];
  demand: Computed; mine: Computed; residual: Computed; share_pct: Computed; residual_change: Computed;
  mine_change: Computed | null; perturbations: Perturbation[];
}
export interface Preview { view_version: string; result: AssessResult; record: Record<string, unknown> | null;
  id: string | null; complete: boolean | null; exists: boolean; written: false; provider_called: false }
export interface Saved { view_version: string; status: "created" | "unchanged"; id: string; created_at: string;
  record: { label: string; baseline: { scenario: ScenarioId; year: Year }; result: Omit<AssessResult, "assumptions">;
    assumptions: Assumptions } & Record<string, unknown>;
  state: (typeof RECORD_STATES)[number]; problems: string[]; provider_called: false }
export interface Charge { equation: string; uses: string[]; withheld: string[]; shown: string | null }
export interface Panel { view_version: string; rate_pct: string; years: number; method: "annuity" | "limit_at_zero_rate";
  crf: string; projects: { project: string; charges: Charge[]; problem: string | null }[]; ignores: string[];
  stored: false; provider_called: false }

export type Action<T> = { state: "ready"; status: number; data: T } | { state: "failed" | "unconfirmed"; message: string };

const SHA = /^[0-9a-f]{64}$/;

/** One POST from this page: same-origin JSON with the scenario action header. A 4xx is a refusal made before anything
 * was written; a 5xx or no reply does not prove what happened. */
async function post(path: string, body: object): Promise<{ status: number; body: unknown } | Action<never>> {
  let response: Response;
  try {
    response = await fetch(path, { method: "POST", body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", Accept: "application/json", [SCENARIO_HEADER]: "1" } });
  } catch {
    return { state: "unconfirmed", message: "No reply arrived from the local server; nothing was retried." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = isRec(payload) && typeof payload.detail === "string" ? payload.detail
      : `Unexpected response (${response.status}).`;
    return { state: response.status >= 500 ? "unconfirmed" : "failed", message };
  }
  return { status: response.status, body: payload };
}

function read<T>(reply: { status: number; body: unknown } | Action<never>, check: (body: unknown) => void,
                 status: number[]): Action<T> {
  if ("state" in reply) return reply;
  try {
    need(status.includes(reply.status), "status", "is not a status this action answers with");
    check(reply.body);
  } catch (error) {
    if (error instanceof Refusal) return { state: "unconfirmed", message: `The reply could not be read (${error.message}).` };
    if (error instanceof TypeError || error instanceof RangeError) {
      return { state: "unconfirmed", message: "The reply could not be read (it is not shaped as expected)." };
    }
    throw error;
  }
  return { state: "ready", status: reply.status, data: reply.body as T };
}

// ---------------------------------------------------------------- an assessed scenario

const COMPONENT = { ev: "ev", networks: "networks" } as const;

/** The flags the assumptions set, in the server's order, and the recomputed D', M' and change in mine supply. */
function expected(result: AssessResult, figures: Figures) {
  const { scenario, year, assumptions } = result;
  const flags = new Set<string>();
  const uses = [demandId("total", scenario, year), mineId("total", year)];
  const use = (...ids: string[]) => ids.forEach((id) => { if (!uses.includes(id)) uses.push(id); });
  let demand = (): Rat => figures.at(uses[0]);
  for (const control of ["ev", "networks"] as const) {
    const entry = assumptions[control];
    if (entry === null) continue;
    const component = COMPONENT[control];
    const base = demandId(component, scenario, year);
    let chosen: () => Rat;
    if (entry.source === "value") {
      const value = ofPlain(entry.kt);
      need(value !== null && !lessThan(value, int(0)), `result.assumptions.${control}`, "is not a non-negative kt value");
      flags.add("user_value");
      const spread = SCENARIO_IDS.map((key) => demandId(component, key, year));
      use(base, ...spread.filter((id) => id !== base));
      if (spread.every(figures.has)) {
        const values = spread.map(figures.at);
        const low = values.reduce((a, b) => (lessThan(b, a) ? b : a));
        const high = values.reduce((a, b) => (lessThan(a, b) ? b : a));
        if (lessThan(value as Rat, low) || lessThan(high, value as Rat)) flags.add("outside_published_spread");
      }
      chosen = () => value as Rat;
    } else {
      const id = entry.source === "technology_case" ? dcId(entry.scenario, year) : demandId(component, entry.scenario, year);
      if (entry.source === "technology_case") flags.add("technology_case");
      if (entry.scenario !== scenario) flags.add("hybrid");
      use(id, base);
      chosen = () => figures.at(id);
    }
    const previous = demand;
    demand = () => add(previous(), sub(chosen(), figures.at(base)));
  }
  let change: (() => Rat) | null = null;
  const mine = assumptions.mine;
  if (mine !== null && mine.source === "total") {
    const kt = ofPlain(mine.kt);
    need(kt !== null, "result.assumptions.mine", "is not a signed kt value");
    change = () => kt as Rat;
    if (mine.reference !== null) {
      flags.add("reference_magnitude");
      const reference = mine.reference === "ptfi-sales-change"
        ? ["fcx-ptfi-sales-guidance-2025", "fcx-ptfi-sales-guidance-2026"]
        : ["scco-production-guidance-2025", "scco-production-guidance-2026"];
      use(...reference);
      if (reference.every(figures.has)) {
        const magnitude = referenceMagnitude(figures, mine.reference);
        need(equal(kt as Rat, magnitude) || equal(kt as Rat, sub(int(0), magnitude)), "result.assumptions.mine",
             "a tagged change must equal its reference magnitude");
      }
    }
  } else if (mine !== null) {
    const keys = Object.keys(mine.factors);
    need(keys.length > 0 && keys.every((key) => (COUNTRY_IDS as readonly string[]).includes(key)),
         "result.assumptions.mine", "names unknown countries");
    const countries = COUNTRY_IDS.filter((key) => key in mine.factors);
    use(...countries.map((key) => mineId(key, year)));
    change = () => sum(countries.map((key) => mul(sub(ofPlain(mine.factors[key]) as Rat, int(1)),
                                                  figures.at(mineId(key, year)))));
  }
  return { flags: FLAG_IDS.filter((flag) => flags.has(flag)), uses, demand, change };
}

/** An assessed scenario against the view it was computed on. */
export function checkResult(result: AssessResult, view: CopperToolsView, where = "result") {
  const figures = new Figures(view);
  need(isRec(result) && (SCENARIO_IDS as readonly string[]).includes(result.scenario), where, "unknown scenario");
  const { flags, uses, demand, change } = expected(result, figures);
  need(sameList(result.flags.map((flag) => flag.id), flags), `${where}.flags`, "are not the flags these inputs set");
  result.flags.forEach((flag) => need(flag.text === view.coverage.flags[flag.id], `${where}.flags`, "wording differs"));
  need(sameList(result.demand.uses, uses), `${where}.demand`, "does not name the figures these inputs use");
  const mine = () => add(figures.at(mineId("total", result.year)), change === null ? int(0) : change());
  const residual = () => sub(demand(), mine());
  const base = () => sub(figures.at(demandId("total", null, BASE_YEAR)), figures.at(mineId("total", BASE_YEAR)));
  checkComputed(result.demand, `${where}.demand`, figures, demand);
  checkComputed(result.mine, `${where}.mine`, figures, mine);
  checkComputed(result.residual, `${where}.residual`, figures, residual);
  checkComputed(result.share_pct, `${where}.share_pct`, figures, () => mul(div(residual(), demand()), int(100)), 1,
                true);
  checkComputed(result.residual_change, `${where}.residual_change`, figures, () => sub(residual(), base()));
  const withheld = result.residual.withheld.length > 0;
  need((result.mine_change === null) === (change === null), `${where}.mine_change`, "does not follow the mine control");
  if (result.mine_change !== null && change !== null) {
    checkComputed(result.mine_change, `${where}.mine_change`, figures, change);
  }
  checkPerturbations(result.perturbations, result.scenario, result.year, figures, `${where}.perturbations`,
                     change === null || withheld ? null : change());
}

const omit = (value: Record<string, unknown>, key: string) =>
  Object.fromEntries(Object.entries(value).filter(([name]) => name !== key));

export async function previewScenario(view: CopperToolsView, body: object): Promise<Action<Preview>> {
  return read<Preview>(await post("/api/tools/copper/preview", body), (raw) => {
    const preview = raw as Preview;
    need(preview.view_version === PREVIEW_VERSION, "view_version", `expected ${PREVIEW_VERSION}`);
    need(preview.written === false && preview.provider_called === false, "preview", "a preview writes nothing");
    checkResult(preview.result, view);
    if (preview.record !== null) {
      need(SHA.test(preview.id ?? ""), "id", "expected a SHA-256");
      need(JSON.stringify(preview.record.result) === JSON.stringify(omit(preview.result as unknown as
        Record<string, unknown>, "assumptions")), "record.result", "is not the result shown");
      need(JSON.stringify(preview.record.assumptions) === JSON.stringify(preview.result.assumptions),
           "record.assumptions", "are not the assumptions shown");
    } else {
      need(preview.id === null && preview.complete === null, "record", "an unlabelled preview has no record");
    }
  }, [200]);
}

/** Save the scenario a valid preview showed: the request sends exactly that preview's inputs, and the saved record
 * must be that scenario (its baseline, its normalised assumptions and its result), or the reply is not confirmed. */
export async function saveScenario(view: CopperToolsView, shown: AssessResult, label: string): Promise<Action<Saved>> {
  const body = { scenario: shown.scenario, year: shown.year, assumptions: shown.assumptions, label };
  return read<Saved>(await post("/api/tools/copper/scenarios", body), (raw) => {
    const saved = raw as Saved;
    need(saved.view_version === SAVED_VERSION && SHA.test(saved.id), "saved", "is not a saved record");
    need(["created", "unchanged"].includes(saved.status), "status", "unknown");
    need((RECORD_STATES as readonly string[]).includes(saved.state), "state", "unknown");
    checkResult({ ...saved.record.result, scenario: saved.record.baseline.scenario, year: saved.record.baseline.year,
                  assumptions: saved.record.assumptions } as AssessResult, view, "record.result");
    need(saved.record.label === label && saved.record.baseline.scenario === shown.scenario &&
         saved.record.baseline.year === shown.year &&
         JSON.stringify(saved.record.assumptions) === JSON.stringify(shown.assumptions), "record",
         "is not the scenario that was shown");
    need(JSON.stringify(saved.record.result) === JSON.stringify(omit(shown as unknown as Record<string, unknown>,
      "assumptions")), "record.result", "differs from the preview that was shown");
  }, [200, 201]);
}

// ---------------------------------------------------------------- the capital-recovery panel (E14)

/** CRF(r, n) = r(1 + r)^n / ((1 + r)^n - 1) for r > 0; CRF(0, n) = 1 / n, the limit as r falls to zero. */
export function crf(rate: Rat, years: number): Rat {
  if (rate.n === 0n) return div(int(1), int(years));
  const growth = pow(add(int(1), rate), years);
  return div(mul(rate, growth), sub(growth, int(1)));
}

export function checkPanel(panel: Panel, view: CopperToolsView, ratePct: string, years: string) {
  const figures = new Figures(view);
  const rate = div(ofPlain(ratePct) as Rat, int(100));
  const life = Number(years);
  need(panel.provider_called === false && panel.stored === false, "panel", "the panel stores nothing");
  need(panel.rate_pct === ratePct && panel.years === life, "panel", "answers other inputs");
  need(panel.method === (rate.n === 0n ? "limit_at_zero_rate" : "annuity"), "panel.method", "does not follow the rate");
  const factor = crf(rate, life);
  need(panel.crf === halfEven(factor, 6), "panel.crf", "does not follow from the rate and the life");
  need(panel.ignores.length > 0, "panel.ignores", "must say what it ignores");
  const projects = new Map(view.producers.projects.map((project) => [project.id, project]));
  for (const row of panel.projects) {
    const project = projects.get(row.project);
    need(project !== undefined, `panel.${row.project}`, "is not a listed project");
    if (project === undefined) continue;
    if (project.capital === null) {
      need(row.charges.length === 0 && row.problem !== null, `panel.${row.project}`, "computes without stated capital");
      continue;
    }
    need(row.charges.length === project.capacity.length, `panel.${row.project}`, "does not cover each stated capacity");
    row.charges.forEach((charge, n) => {
      const capacity = project.capacity[n];
      const where = `panel.${row.project}[${n}]`;
      need(sameList(charge.uses, [project.capital as string, capacity]), where, "uses other figures");
      need(charge.withheld.length === 0 || !charge.uses.every((id) => figures.has(id)), where,
           "withheld here but available in the loaded view; reload the page");
      checkComputed(charge as Computed, where, figures, () => {
        const capital = capitalUsd(figures, project.capital as string);
        const pounds = poundsPerYear(figures, capacity, project.capacity_unit);
        return rate.n === 0n ? div(capital, mul(int(life), pounds)) : div(mul(capital, factor), pounds);
      }, 3, true);
    });
  }
}

export async function capitalCharge(view: CopperToolsView, ratePct: string, years: string): Promise<Action<Panel>> {
  return read<Panel>(await post("/api/tools/copper/capital-charge", { rate_pct: ratePct, years }),
                     (raw) => checkPanel(raw as Panel, view, ratePct, years), [200]);
}
