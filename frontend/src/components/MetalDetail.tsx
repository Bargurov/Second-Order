import { useState, type ReactNode } from "react";
import type { Block, Cell, Chapter, MetalsView, Mineral, Series } from "../metals";
import { DEMAND_YEARS, partsFor, relianceCount, SCENARIOS } from "../metalsSections";
import { ConcentrationRisk } from "./MetalsConcentration";
import { Exposure } from "./MetalExposure";
import {
  Fold, items, Leader, percentOf, Reason, Scroll, Share, str, strings, TabList, TopThree, YearCell, YearHead,
} from "./MetalsBits";
import type { Picked } from "./MetalsCompare";
import { MetalSnapshot } from "./MetalSnapshot";
import { SupplyChain } from "./MetalSupply";
import { Transmission } from "./MetalTransmission";
import { IndustrialUses } from "./MetalUses";

const SUPPLY_YEARS = ["2025", "2030", "2035", "2040"];
const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
/** The name of the USGS group of every country it does not name: one group, never split or ranked. */
const OTHER_LABEL = "Other countries (one group, not split by USGS)";

/**
 * By metal: the picked metals as tabs, and one metal at a time. Each metal opens on its snapshot (always shown); then
 * parts that open on demand, in this order: production and reserves (USGS), the supply chain, concentration and risk,
 * industrial uses, geopolitical exposure and economic transmission (each block naming its source), US imports and
 * reliance and the USGS file's notes, and the IEA part for the six minerals it covers. The two sources are never added,
 * compared or joined by country.
 */
export function MetalsByMetal({ view, picked, opened, onOpen, onPick }: {
  view: MetalsView; picked: Picked[]; opened: string | null; onOpen: (id: string) => void; onPick: () => void;
}) {
  if (picked.length === 0) {
    return <p className="mt-empty">No metal is picked. <button type="button" className="mt-text-button"
                                                               onClick={onPick}>Pick metals</button></p>;
  }
  const pick = picked.find((item) => item.id === opened) ?? picked[0];
  return (
    <div className="mt-bymetal">
      <TabList label="Picked metals" className="mt-chooser" tabs={picked.map((item) => ({ id: item.id, label: item.name }))}
               active={pick.id} onSelect={onOpen} idFor={(id) => `mt-metal-tab-${id}`} panelFor={() => "mt-metal-panel"} />
      <div role="tabpanel" id="mt-metal-panel" className="mt-metal-panel" aria-labelledby={`mt-metal-tab-${pick.id}`}
           data-metal={pick.id} tabIndex={0}>
        <MetalDetail key={pick.id} view={view} pick={pick} />
      </div>
    </div>
  );
}

function MetalDetail({ view, pick }: { view: MetalsView; pick: Picked }) {
  const frame = items<{ id: string; name: string; chapter: string }>(view.iea.minerals)
    .find((item) => item.chapter === pick.id);
  const mineral = frame !== undefined && view.iea.state === "available" ? frame as Mineral : null;
  const critical = pick.chapter === null ? "" : str(pick.chapter.critical);
  const parts = partsFor(view, pick.id);
  const ieaProblem = str(view.iea.problem);
  const iea = frame !== undefined;
  return (
    <>
      <header className="mt-metal-head">
        <h3>{pick.name}</h3>
        <p className="mt-metal-meta">USGS Mineral Commodity Summaries 2026{frame ? " · IEA Critical Minerals Dataset 2026"
          : ""}{critical !== "" && <> · <span className="mt-fact">2025 critical mineral, as the USGS file marks it:
          {" "}{critical}</span></>}</p>
      </header>
      <MetalSnapshot pick={pick} parts={parts} />
      <Usgs pick={pick} problem={str(view.usgs.problem)} />
      <section className="mt-part mt-research" data-research="" aria-label={`${pick.name}: supply chain and research`}>
        <p className="kicker">Supply chain and research · each block names its source</p>
        <SupplyChain pick={pick} parts={parts} mineral={mineral} ieaProblem={ieaProblem} iea={iea} />
        <ConcentrationRisk pick={pick} parts={parts} />
        <IndustrialUses pick={pick} parts={parts} mineral={mineral} ieaProblem={ieaProblem} iea={iea} />
        <Exposure pick={pick} parts={parts} />
        <Transmission pick={pick} parts={parts} />
      </section>
      {pick.chapter !== null && pick.chapter.present !== false && <UsgsMore chapter={pick.chapter} name={pick.name} />}
      {frame !== undefined && <Iea pick={pick} name={str(frame.name) || pick.name} mineral={mineral}
                                   problem={ieaProblem} />}
    </>
  );
}

function Usgs({ pick, problem }: { pick: Picked; problem: string }) {
  const { chapter } = pick;
  return (
    <section className="mt-part" data-source="usgs" aria-label={`${pick.name}: USGS`}>
      <p className="kicker">USGS · Mineral Commodity Summaries 2026</p>
      {chapter === null ? <p className="mt-banner"><Reason>Withheld: {problem}</Reason></p>
        : chapter.present === false ? <p className="mt-none">The USGS file has no row in this chapter.</p>
          : <UsgsTables chapter={chapter} name={pick.name} />}
    </section>
  );
}

function UsgsTables({ chapter, name }: { chapter: Chapter; name: string }) {
  const series = items<Series>(chapter.series);
  const reserves = series.filter((item) => item.statistic === "Reserves");
  const output = series.filter((item) => item.statistic !== "Reserves");
  const none = <p className="mt-none">The USGS file has no world production or reserves table in this chapter.</p>;
  const unit = reserves.some((item) => str(item.unit_issue) !== "");
  return (
    <>
      <Fold part="production" title="Production" teaser={series.length === 0 ? "no world table"
        : count(output.length, "table", "tables")}>
        {series.length === 0 ? none : output.length === 0 ? <p className="mt-none">No production table in this chapter.</p>
          : output.map((item) => <SeriesTable key={item.id} name={name} series={item} />)}
      </Fold>
      <Fold part="reserves" title="Reserves" flag={unit ? "Unit in doubt" : null}
            teaser={series.length === 0 ? "no world table" : count(reserves.length, "table", "tables")}>
        {series.length === 0 ? none : reserves.length === 0 ? <p className="mt-none">No reserves table in this chapter.</p>
          : reserves.map((item) => <SeriesTable key={item.id} name={name} series={item} />)}
      </Fold>
    </>
  );
}

/** The USGS chapter's US import sources and reliance as printed, and the file's notes: after the research parts. */
function UsgsMore({ chapter, name }: { chapter: Chapter; name: string }) {
  const notes = strings(chapter.data_notes);
  const imports = items<Chapter["imports"][number]>(chapter.imports);
  const reliance = items<Chapter["reliance"][number]>(chapter.reliance);
  const named = relianceCount(chapter) > 1;  // Several 2025 figures: each row names its commodity, as printed.
  return (
    <section className="mt-part" data-usgs-more="" aria-label={`${name}: USGS imports and notes`}>
      <p className="kicker">USGS · Mineral Commodity Summaries 2026 · as printed</p>
      <Fold part="imports" title="US imports and reliance"
            teaser={`${count(imports.length, "source table", "source tables")} · ${count(reliance.length, "reliance figure",
              "reliance figures")}`}>
        <h4>US import sources</h4>
        {imports.length === 0 ? <p className="mt-none">None in this chapter.</p> : imports.map((group, at) => (
          <table key={at} className="mt-table mt-narrow">
            <caption>{str(group.detail)}{str(group.years) && <span className="mt-sub">{str(group.years)}</span>}</caption>
            <thead><tr><th scope="col">Country</th><th scope="col" className="mt-num">Value as printed</th></tr></thead>
            <tbody>{items<{ country: string; value: string }>(group.rows).map((row, line) => (
              <tr key={line}><th scope="row">{str(row.country)}</th><td className="mt-num">{str(row.value)}</td></tr>))}
            </tbody>
          </table>))}
        <h4>US net import reliance</h4>
        {reliance.length === 0 ? <p className="mt-none">None in this chapter.</p> : (
          <ul className="mt-list">{reliance.map((row, at) => (
            <li key={at}>{named && <><span className="mt-country">{str(row.commodity)}</span> · </>}{str(row.detail)},{" "}
              {str(row.year)}: <span className="mt-printed">{str(row.value)}</span></li>))}
          </ul>)}
      </Fold>
      <Fold part="notes" title="Notes in the USGS file" teaser={count(notes.length, "note", "notes")}>
        {notes.length === 0 ? <p className="mt-none">None in this chapter.</p>
          : <ul className="mt-list">{notes.map((note, at) => <li key={at}>{note}</li>)}</ul>}
      </Fold>
    </section>
  );
}

function SeriesTable({ name, series }: { name: string; series: Series }) {
  const detail = str(series.detail);
  const year = str(series.year);
  // A series with a known unit issue (metals.ts UNIT_ISSUES) shows its words instead of its unit and its quantities;
  // its shares stay, since each divides two figures of the same column.
  const issue = str(series.unit_issue);
  const otherShare = series.other?.share?.shown;
  const line = (label: ReactNode, cell: Cell, share: ReactNode, key: string) => (
    <tr key={key}>
      <th scope="row">{label}</th>
      <td className="mt-num">{issue !== "" ? <Reason>not shown</Reason>
        : <span className="mt-printed">{str(cell.value)}</span>}</td>
      <td>{share}</td>
      <td className="mt-cell-notes">{str(cell.notes)}</td>
    </tr>
  );
  return (
    <div className="mt-series">
      {issue !== "" && <p className="mt-unit-issue" data-unit-issue="">{issue}</p>}
      <Scroll label={`${name}, ${detail}, ${year}`}>
        <table className="mt-table mt-series-table">
          <caption>{str(series.statistic)} · {detail} · {year}<span className="mt-sub">{issue !== ""
            ? "unit not shown" : str(series.unit)}</span></caption>
          <thead>
            <tr><th scope="col">Country</th><th scope="col" className="mt-num">Value as printed</th>
              <th scope="col">Share of world</th><th scope="col">Notes</th></tr>
          </thead>
          <tbody>
            {items<Cell>(series.countries).map((cell, at) =>
              line(str(cell.country), cell, <Share shown={cell.share?.shown} reason={cell.share?.reason} />, `c${at}`))}
            {series.other && line(OTHER_LABEL, series.other,
              <Share shown={series.other.share?.shown} reason={series.other.share?.reason} />, "other")}
          </tbody>
          {series.world && <tfoot>{line(series.world.rounded === true ? "World total (rounded by USGS)" : "World total",
            series.world, series.no_shares === null
              ? <span className="mt-none">the base of each share</span> : <span className="mt-none">—</span>, "world")}</tfoot>}
        </table>
      </Scroll>
      {series.no_shares === null && (<>
        <p className="mt-series-foot">Largest named country: <Leader top={series.leader} /> · Three largest named
          countries: <TopThree top={series.top3} /></p>
        <p className="mt-series-foot mt-series-scope">Ranked among the countries USGS names.{series.other !== null && (
          typeof otherShare === "string"
            ? <> “Other countries”, one group USGS does not split, holds {otherShare}% of the world total and is
              never ranked.</>
            : <> “Other countries” is one group USGS does not split, and it is never ranked.</>)}</p>
      </>)}
    </div>
  );
}

function Iea({ pick, name, mineral, problem }: { pick: Picked; name: string; mineral: Mineral | null; problem: string }) {
  return (
    <section className="mt-part mt-part-iea" data-source="iea" aria-labelledby={`mt-${pick.id}-iea`}>
      <p className="kicker">IEA · Critical Minerals Dataset 2026</p>
      <h4 id={`mt-${pick.id}-iea`} className="mt-iea-title">{name}: demand by technology, supply by country</h4>
      <p className="mt-apart">A separate source with its own scope: never added to the USGS figures or compared with
        them. Values in thousand tonnes (kt), as the IEA's sheets state; every year after 2025 is the IEA's projection.</p>
      {mineral === null ? <p><Reason>Withheld: {problem}</Reason></p>
        : <IeaParts pick={pick} name={name} mineral={mineral} />}
    </section>
  );
}

function IeaParts({ pick, name, mineral }: { pick: Picked; name: string; mineral: Mineral }) {
  const [scenario, setScenario] = useState<string>(SCENARIOS[0][0]);
  const [year, setYear] = useState(DEMAND_YEARS[0]);
  const scenarioName = SCENARIOS.find(([id]) => id === scenario)?.[1] ?? "";
  const key = `${scenario}-${year}`;
  const demand = mineral.demand ?? { rows: [], energy_share: {} };
  const share = demand.energy_share ?? {};
  const scope = str(mineral.scope_note);
  const notes = [...strings(mineral.notes?.demand), ...strings(mineral.notes?.supply)];
  const supply = items<Block>(mineral.supply);
  return (
    <>
      {scope !== "" && <p className="mt-scope" data-scope="">{scope}</p>}
      <Fold part="iea-demand" title="Demand by technology" teaser="2025 and IEA scenarios to 2050">
        <div className="mt-controls">
          <span className="mt-control">
            <label htmlFor={`mt-${pick.id}-scenario`}>Scenario</label>
            <select id={`mt-${pick.id}-scenario`} value={scenario} onChange={(event) => setScenario(event.target.value)}>
              {SCENARIOS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </span>
          <span className="mt-control">
            <label htmlFor={`mt-${pick.id}-year`}>Year</label>
            <select id={`mt-${pick.id}-year`} value={year} onChange={(event) => setYear(event.target.value)}>
              {DEMAND_YEARS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </span>
        </div>
        <Scroll label={`${name}, IEA demand by technology`} year={year}>
          <table className="mt-table mt-demand-table" data-demand={key}>
            <caption>Demand, kt</caption>
            <thead>
              <tr><th scope="col">Technology</th><YearHead year="2025" /><YearHead year={year} extra={scenarioName} /></tr>
            </thead>
            <tbody>{items<{ label: string; values: Record<string, string> }>(demand.rows).map((row, at) => (
              <tr key={at} className={str(row.label).startsWith("Total") ? "mt-total" : undefined}>
                <th scope="row">{str(row.label)}</th>
                <YearCell year="2025">{str(row.values?.["2025"]) || "—"}</YearCell>
                <YearCell year={year}>{str(row.values?.[key]) || "—"}</YearCell>
              </tr>))}
            </tbody>
          </table>
        </Scroll>
        <h5>Share of energy technologies in total demand</h5>
        <Scroll label={`${name}, IEA share of energy technologies in total demand`}>
          <table className="mt-table mt-share-table">
            <thead><tr><th scope="col">Scenario</th><YearHead year="2025" />
              {DEMAND_YEARS.map((item) => <YearHead key={item} year={item} />)}</tr></thead>
            <tbody>{SCENARIOS.map(([id, label], at) => (
              <tr key={id}>
                <th scope="row">{label}</th>
                {at === 0 && <YearCell year="2025" rowSpan={SCENARIOS.length}>{percentOf(share["2025"])}
                  <span className="mt-sub">one figure for every scenario</span></YearCell>}
                {DEMAND_YEARS.map((item) => (
                  <YearCell key={item} year={item}>{percentOf(share[`${id}-${item}`])}</YearCell>))}
              </tr>))}
            </tbody>
          </table>
        </Scroll>
      </Fold>
      <Fold part="iea-supply" title="Supply by country" teaser={supply.map((block) => str(block.stage)).join(" · ")}>
        {supply.map((block, at) => <SupplyTable key={at} name={name} block={block} />)}
      </Fold>
      {notes.length > 0 && (
        <Fold part="iea-notes" title="Notes in the IEA workbook" teaser={count(notes.length, "note", "notes")}>
          <ul className="mt-list">{notes.map((note, at) => <li key={at}>{note}</li>)}</ul>
        </Fold>)}
    </>
  );
}

function SupplyTable({ name, block }: { name: string; block: Block }) {
  const stage = str(block.stage);
  const cells = (values: Record<string, string> | undefined, shares: Record<string, string> | undefined) =>
    SUPPLY_YEARS.map((year) => (
      <YearCell key={year} year={year}>{str(values?.[year]) || "—"}
        {shares && <span className="mt-sub">{percentOf(shares[year])}</span>}</YearCell>));
  return (
    <>
      <h5>Supply · {stage}</h5>
      <Scroll label={`${name}, IEA supply, ${stage}`}>
        <table className="mt-table mt-supply-table">
          <caption>Base case, kt, with each line's share of the total</caption>
          <thead>
            <tr><th scope="col">Country</th>{SUPPLY_YEARS.map((year) => <YearHead key={year} year={year} />)}</tr>
          </thead>
          <tbody>
            {items<Block["countries"][number]>(block.countries).map((line, at) => (
              <tr key={at}><th scope="row">{str(line.country)}</th>{cells(line.values, line.shares)}</tr>))}
            {block.rest && <tr><th scope="row">Rest of world</th>{cells(block.rest.values, block.rest.shares)}</tr>}
          </tbody>
          <tfoot>
            <tr className="mt-total">
              <th scope="row">{str(block.total_label) || "Total"}</th>{cells(block.total, undefined)}
            </tr>
            <tr><th scope="row">Top 3 share, as the IEA publishes it</th>{SUPPLY_YEARS.map((year) => (
              <YearCell key={year} year={year}>{percentOf(block.top3_published?.[year])}</YearCell>))}</tr>
          </tfoot>
        </table>
      </Scroll>
    </>
  );
}
