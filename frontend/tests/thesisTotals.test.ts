// A balance table's demand and supply rows are named by what their figures measure, never by a fixed "Total supply":
// the published copper version's IEA table sets demand against base-case MINE supply (refined supply is its own line),
// and its United States table sets reported refined CONSUMPTION against domestic REFINERY output (imports, exports and
// stocks are their own lines). Both real structures are read from the committed version file itself
// (content/theses/copper/v1.json, unchanged by this rule); the synthetic reply covers the served shape.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { ThesisView } from "../src/thesis.ts";
import { sharedMeasure, totalNames } from "../src/thesisTotals.ts";

const read = <T>(path: string): T => JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
interface Stored { figures: { id: string; measure: string }[];
  balance: { tables: { id: string; rows: { demand_total: string; supply_total: string }[] }[] } }
const published = read<Stored>("../../content/theses/copper/v1.json");
const available = read<ThesisView>("./fixtures/thesis-available.json");

/** A committed table's rows with each total's figure id replaced by its stored figure, as the server resolves them. */
function storedRows(id: string) {
  const byId = new Map(published.figures.map((figure) => [figure.id, figure]));
  return published.balance.tables.find((table) => table.id === id)!.rows.map((row) => ({
    demand_total: byId.get(row.demand_total)!, supply_total: byId.get(row.supply_total)! }));
}

test("the IEA table names its demand and its base-case mine supply", () => {
  assert.deepEqual(totalNames(storedRows("balance-iea")),
    { demand: "IEA total copper demand", supply: "IEA base-case copper mine supply" });
});

test("the United States table names reported refined consumption and refinery output, its estimate kept per figure",
  () => {
    const rows = storedRows("us-refined-context");
    // 2025 is an estimate: its measures add ", estimated", which stays on that figure's own line and title.
    assert.deepEqual(rows.map((row) => row.supply_total.measure),
      ["USGS US refined copper production", "USGS US refined copper production, estimated"]);
    assert.deepEqual(totalNames(rows), { demand: "USGS US reported consumption of refined copper",
      supply: "USGS US refined copper production" });
  });

test("the synthetic served tables are named from their figures too", () => {
  assert.deepEqual(available.balance.tables.filter((table) => table.state === "available")
    .map((table) => [table.id, totalNames(table.rows!)]), [
    ["balance-steps", { demand: "Synthetic total demand", supply: "Synthetic total supply" }],
    ["balance-side-by-side", { demand: "Synthetic total demand", supply: "Synthetic world refinery production" }]]);
});

test("a shared measure is the whole of what every figure states, up to a qualifier one of them adds", () => {
  const of = (...measures: string[]) => sharedMeasure(measures.map((measure) => ({ measure })));
  assert.equal(of("Mine supply, base case", "Mine supply, base case"), "Mine supply, base case");
  assert.equal(of("Refined use, reported", "Refined use, reported, estimated"), "Refined use, reported");
  // A qualifier that differs between years is not shared: the name keeps only what all of them say.
  assert.equal(of("Supply, base case", "Supply, high case"), "Supply");
  // No common measure, or none at all: no single name can be given.
  assert.equal(of("Mine supply", "Refined supply"), null);
  assert.equal(of(), null);
});

test("figures that share no measure leave the row named only by its side, never by a quantity they are not", () => {
  const rows = [{ demand_total: { measure: "Demand A" }, supply_total: { measure: "Mine supply" } },
    { demand_total: { measure: "Demand A" }, supply_total: { measure: "Refined supply" } }];
  assert.deepEqual(totalNames(rows), { demand: "Demand A", supply: null });
});

test("the balance grid writes no fixed total label", () => {
  const sections = readFileSync(new URL("../src/components/ThesisSections.tsx", import.meta.url), "utf8");
  for (const label of ["Total demand", "Total supply"]) assert.ok(!sections.includes(`>${label}<`), label);
  assert.match(sections, /totalNames\(rows\)/);
});
