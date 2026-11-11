import { useState } from "react";
import type { Mineral } from "../metals";
import { NOTES } from "../metalsNotes";
import { DEMAND_YEARS, SCENARIOS, type MetalParts } from "../metalsSections";
import type { UseEntry } from "../metalsStage2";
import { IEA_LABEL, Passages, QUOTED_LABEL, QUOTED_NOTE, SourceBlock, Withheld } from "./MetalsBlocks";
import { Fold, Missing, percentOf, Scroll, str, YearCell, YearHead } from "./MetalsBits";
import type { Picked } from "./MetalsCompare";

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const IMPORTANCE = NOTES.find((note) => note.id === "importance");
/** What the IEA table covers, said where it starts. */
export const USES_SCOPE = "Demand from energy technologies only, as the IEA scopes them; other industrial uses of this "
  + "metal are not in this table.";

/**
 * Industrial uses: the IEA's demand from energy technologies for each of its entries mapped to this chapter, by
 * technology, in 2025 and in a chosen scenario and year, with each technology's share of 2025 energy-technology demand;
 * for the six minerals, the IEA's share of energy technologies in total demand; the end uses a retained source states;
 * and a note on why industrial importance, strategic criticality and supply risk are different things.
 */
export function IndustrialUses({ pick, parts, mineral, ieaProblem, iea }: {
  pick: Picked; parts: MetalParts; mineral: Mineral | null; ieaProblem: string; iea: boolean;
}) {
  const [scenario, setScenario] = useState<string>(SCENARIOS[0][0]);
  const [year, setYear] = useState(DEMAND_YEARS[0]);
  const scenarioName = SCENARIOS.find(([id]) => id === scenario)?.[1] ?? "";
  const key = `${scenario}-${year}`;
  const { uses, research } = parts;
  const entries = uses.shown ? uses.value : [];
  const passages = research.shown ? research.value?.uses ?? [] : [];
  const teaser = !uses.shown ? "IEA part withheld" : entries.length === 0 ? "no IEA energy-technology entry"
    : count(entries.length, "IEA entry", "IEA entries");
  const critical = pick.chapter === null ? "" : str(pick.chapter.critical);
  const controls = entries.length > 0 || (iea && mineral !== null);
  return (
    <Fold part="uses" title="Industrial uses" teaser={`${teaser}${passages.length > 0 ? " · sourced end uses" : ""}`}>
      <SourceBlock source="iea" label={`${IEA_LABEL} · demand from energy technologies`} note={USES_SCOPE}>
        {controls && (
          <div className="mt-controls">
            <span className="mt-control">
              <label htmlFor={`mt-${pick.id}-uses-scenario`}>Scenario<span className="mt-sr"> for energy-technology
                uses</span></label>
              <select id={`mt-${pick.id}-uses-scenario`} value={scenario}
                      onChange={(event) => setScenario(event.target.value)}>
                {SCENARIOS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
              </select>
            </span>
            <span className="mt-control">
              <label htmlFor={`mt-${pick.id}-uses-year`}>Year<span className="mt-sr"> for energy-technology
                uses</span></label>
              <select id={`mt-${pick.id}-uses-year`} value={year} onChange={(event) => setYear(event.target.value)}>
                {DEMAND_YEARS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </span>
          </div>)}
        {!uses.shown ? <Withheld problem={uses.problem} />
          : entries.length === 0 ? <p><Missing>The IEA's energy-technology table has no entry for this metal</Missing></p>
            : entries.map((entry) => <UseTable key={entry.name} entry={entry} name={pick.name} year={year}
                                                scenario={scenarioName} valueKey={key} />)}
        {iea && !(mineral === null && !uses.shown && uses.problem === ieaProblem) && (
          <>
            <h4>Share of energy technologies in total demand</h4>
            {mineral === null ? <Withheld problem={ieaProblem} /> : (
              <p className="mt-share-line" data-energy-share={key}>
                <span data-year-label="">2025</span>:{" "}
                <span className="mt-share">{percentOf(mineral.demand?.energy_share?.["2025"])}</span>
                {" "}<span className="mt-dot" aria-hidden="true">·</span>{" "}
                {scenarioName}, <span data-year-label="">{year}</span>: <span className="mt-share" data-projection="">
                  {percentOf(mineral.demand?.energy_share?.[key])}</span> <span className="mt-proj-inline">IEA projection</span>
                <span className="mt-sub">Of the IEA's total demand for {str(mineral.name)}, the part that goes into energy
                  technologies; the IEA's demand table at the foot of this metal gives every year.</span>
              </p>)}
          </>)}
      </SourceBlock>
      <SourceBlock source="quoted" label={`${QUOTED_LABEL} · end uses`} note={QUOTED_NOTE}>
        {!research.shown ? <Withheld problem={research.problem} />
          : <Passages list={passages} none="No retained source states end uses for this metal." />}
      </SourceBlock>
      <aside className="mt-note-box" data-note="importance" aria-label={IMPORTANCE?.term}>
        <p className="mt-note-title">{IMPORTANCE?.term}</p>
        <p>{IMPORTANCE?.text}</p>
        {critical !== "" && <p className="mt-note-fact">On the 2025 critical-minerals list, as the USGS file marks this
          chapter: <strong>{critical}</strong>. Supply risk is under Concentration & risk.</p>}
      </aside>
    </Fold>
  );
}

function UseTable({ entry, name, year, scenario, valueKey }: {
  entry: UseEntry; name: string; year: string; scenario: string; valueKey: string;
}) {
  const technologies = entry.technologies;
  return (
    <div className="mt-use" data-use={entry.name}>
      <h4>{entry.name}</h4>
      {entry.scope_note !== null && <p className="mt-scope" data-use-scope="">{entry.scope_note}</p>}
      {technologies === null && <p className="mt-none">The IEA gives this entry's total only, with no split by
        technology.</p>}
      <Scroll label={`${name}, IEA energy-technology demand, ${entry.name}`} year={year}>
        <table className="mt-table mt-uses-table" data-uses={valueKey}>
          <caption>Demand from energy technologies, kt</caption>
          <thead>
            <tr>
              <th scope="col">Technology</th>
              <YearHead year="2025" />
              <th scope="col" className="mt-num">Share of 2025<span className="mt-sub">energy-technology demand</span></th>
              <YearHead year={year} extra={scenario} />
            </tr>
          </thead>
          {technologies !== null && technologies.length > 0 && (
            <tbody>{technologies.map((technology) => (
              <tr key={technology.label}>
                <th scope="row">{technology.label}</th>
                <YearCell year="2025">{str(technology.values["2025"]) || "—"}</YearCell>
                <td className="mt-num">{technology.share_2025 === null
                  ? <span className="mt-withheld">no share: the 2025 total is not positive</span>
                  : <span className="mt-share">{technology.share_2025}%</span>}</td>
                <YearCell year={year}>{str(technology.values[valueKey]) || "—"}</YearCell>
              </tr>))}
            </tbody>)}
          <tfoot>
            <tr className="mt-total">
              <th scope="row">Total energy technologies</th>
              <YearCell year="2025">{str(entry.total["2025"]) || "—"}</YearCell>
              <td className="mt-num mt-base">the base of each share</td>
              <YearCell year={year}>{str(entry.total[valueKey]) || "—"}</YearCell>
            </tr>
          </tfoot>
        </table>
      </Scroll>
    </div>
  );
}
