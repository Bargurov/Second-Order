import type { Chapter, MetalsView } from "../metals";
import {
  concentrationRows, importCoverageText, hhiText, relianceCount, riskOf, STAGE_WORDS, type MetalParts,
} from "../metalsSections";
import { NO_RELIANCE, type ImportGroup, type RiskChapter } from "../metalsStage2";
import { About, Hhi, RelianceFigure, SourceBlock, USGS_LABEL, Withheld } from "./MetalsBlocks";
import { Fold, Leader, MetalName, Missing, production2025, Reason, Scroll, TopThree, Why } from "./MetalsBits";
import type { Picked } from "./MetalsCompare";

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const NO_COMPOSITE = "Each indicator is shown on its own; none is combined into a score.";
/** The basis USGS prints for most chapters; the overview names a reliance basis only when it is another, or when the
 * chapter prints more than one 2025 figure (so the headline's basis is always beside the "one of" note). */
const USUAL_BASIS = "Net import reliance as a percentage of apparent consumption";

/** Column headings shared by the concentration tables: each indicator's name with its "About" note. */
function Cr1Head() {
  return <th scope="col">Largest named (CR1)<About name="the largest named country's share (CR1)" which="cr1" />
    <span className="mt-sub">share of the printed world total</span></th>;
}
function Cr3Head() {
  return <th scope="col">Three largest named (CR3)<About name="the three largest named countries' share (CR3)" which="cr3" />
    <span className="mt-sub">combined share of the printed world total</span></th>;
}
function HhiHead() {
  return <th scope="col">HHI<About name="the HHI and its two bounds" which="hhi" />
    <span className="mt-sub">low–high bound, with the named countries' coverage<About name="coverage" which="coverage" />
    </span></th>;
}

/**
 * Concentration and risk: for each 2025 production stage and the reserves, the largest named country's share (CR1),
 * the three largest named (CR3), and the HHI as its two bounds with the named countries' coverage beside it; then the
 * same measures over US import sources. Every figure is the server's, recomputed by the reader; no score combines them.
 */
export function ConcentrationRisk({ pick, parts }: { pick: Picked; parts: MetalParts }) {
  const { risk } = parts;
  const rows = risk.shown && pick.chapter !== null ? concentrationRows(pick.chapter, risk.value) : [];
  const teaser = risk.shown ? `${count(rows.length, "table", "tables")} · ${count(risk.value.us.imports.length,
    "US import table", "US import tables")}` : "USGS part withheld";
  return (
    <Fold part="concentration" title="Concentration & risk" teaser={teaser}>
      <SourceBlock source="usgs" label={`${USGS_LABEL} · world production and reserves, 2025`}>
        {!risk.shown || pick.chapter === null ? <Withheld problem={risk.shown ? "" : risk.problem} /> : (
          <>
            {rows.length === 0 ? <p><Missing>USGS's file has no 2025 production or reserves table for this metal</Missing></p> : (
              <Scroll label={`${pick.name}, concentration by stage, 2025`}>
                <table className="mt-table mt-conc-detail">
                  <thead><tr><th scope="col">Table</th><Cr1Head /><Cr3Head /><HhiHead /></tr></thead>
                  <tbody>{rows.map(({ series, indicators, stage }) => {
                    const context = `${pick.name}, ${series.detail}`;
                    return (
                      <tr key={series.id} data-series={series.id}>
                        <th scope="row">{stage !== null ? STAGE_WORDS[stage.stage] : series.statistic}
                          <span className="mt-sub">{series.detail}</span></th>
                        <td><Leader top={series.leader} context={`${context}, CR1`} /></td>
                        <td><TopThree top={series.top3} context={`${context}, CR3`} /></td>
                        <td><Hhi item={indicators} context={`${context}, HHI`} /></td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </Scroll>)}
            <p className="mt-series-foot mt-series-scope">{NO_COMPOSITE} A reserves figure describes who holds known
              deposits, not who produces.</p>
            <h4>US import sources</h4>
            <Imports risk={risk.value} name={pick.name} />
          </>)}
      </SourceBlock>
    </Fold>
  );
}

function Imports({ risk, name }: { risk: RiskChapter; name: string }) {
  const groups = risk.us.imports;
  if (groups.length === 0) return <p className="mt-none">USGS prints no US import sources for this metal.</p>;
  return (
    <Scroll label={`${name}, US import sources`}>
      <table className="mt-table mt-conc-imports">
        <thead>
          <tr>
            <th scope="col">Imports<About name="US import-source concentration" which="imports" /></th>
            <th scope="col">Largest source<span className="mt-sub">share of US imports</span></th>
            <th scope="col">Three largest<span className="mt-sub">combined share of US imports</span></th>
            <th scope="col">HHI of sources<span className="mt-sub">low–high bound, with the named sources' coverage</span></th>
          </tr>
        </thead>
        <tbody>{groups.map((group, at) => <ImportRow key={at} group={group} name={name} />)}</tbody>
      </table>
    </Scroll>
  );
}

function ImportRow({ group, name }: { group: ImportGroup; name: string }) {
  const head = <th scope="row">{group.detail}<span className="mt-sub">{group.years}</span></th>;
  if (group.reason !== null) {
    return <tr>{head}<td colSpan={3}><Why reason={group.reason} kind="rank" context={`${name}, ${group.detail}`} /></td></tr>;
  }
  return (
    <tr>
      {head}
      <td>{group.leader === null ? <Reason>No named source</Reason>
        : <><span className="mt-country">{group.leader.country}</span> <span className="mt-share">{group.leader.value}%</span></>}</td>
      <td>{group.top3 === null ? <Reason>Fewer than three named</Reason> : <span className="mt-share">{group.top3}%</span>}</td>
      <td>{group.hhi_low === null || group.hhi_high === null || group.named_share === null ? <Reason>Not computed</Reason> : (
        <span className="mt-hhi"><span className="mt-share">{hhiText(group.hhi_low, group.hhi_high)}</span>
          <span className="mt-sub">{importCoverageText(group.named_share)}</span></span>)}</td>
    </tr>
  );
}

/**
 * The overview's concentration view: per picked metal and 2025 production stage, the three largest named countries'
 * share (CR3), the HHI bounds with their coverage, and US net import reliance for 2025 as printed, once per metal.
 * Withheld figures give a short label and "Why?", as in the leaders view.
 */
export function ConcentrationTable({ view, picked, problem, onOpen }: {
  view: MetalsView; picked: Picked[]; problem: string; onOpen: (id: string) => void;
}) {
  return (
    <div className="mt-table-wrap" role="region" aria-labelledby="compare-title" tabIndex={0}>
      <table className="mt-table mt-compare-table mt-conc-table" data-concentration="">
        <thead>
          <tr>
            <th scope="col">Metal</th>
            <th scope="col">Stage</th>
            <Cr3Head />
            <HhiHead />
            <th scope="col">US net import reliance<About name="US net import reliance" which="reliance" />
              <span className="mt-sub">2025, as printed</span></th>
          </tr>
        </thead>
        {picked.map((pick) => <ConcentrationRows key={pick.id} pick={pick} risk={riskOf(view, pick.id)}
                                                 problem={problem} onOpen={onOpen} />)}
      </table>
    </div>
  );
}

function Reliance({ risk, chapter }: { risk: RiskChapter; chapter: Chapter }) {
  const { reliance } = risk.us;
  if (reliance === null) return <Why reason={NO_RELIANCE} label="Not printed" />;
  const printed = relianceCount(chapter);
  return <RelianceFigure reliance={reliance} count={printed}
                         basis={reliance.detail !== USUAL_BASIS || printed > 1 ? reliance.detail : null} />;
}

function ConcentrationRows({ pick, risk, problem, onOpen }: {
  pick: Picked; risk: RiskChapter | null; problem: string; onOpen: (id: string) => void;
}) {
  const chapter: Chapter | null = pick.chapter;
  if (chapter === null || risk === null) {
    return (
      <tbody data-metal={pick.id} data-state="withheld">
        <tr><th scope="row"><MetalName pick={pick} onOpen={onOpen} /></th>
          <td colSpan={4}><Why reason={problem} label="Withheld" /></td></tr>
      </tbody>
    );
  }
  const rows = production2025(chapter);
  if (rows.length === 0) {
    return (
      <tbody data-metal={pick.id} data-state="none">
        <tr><th scope="row"><MetalName pick={pick} onOpen={onOpen} /></th>
          <td colSpan={3}><Reason>No 2025 production by country in the USGS file</Reason></td>
          <td><Reliance risk={risk} chapter={chapter} /></td></tr>
      </tbody>
    );
  }
  return (
    <tbody data-metal={pick.id} data-state="available">
      {rows.map((series, at) => {
        const context = `${pick.name}, ${series.detail}`;
        const indicators = risk.series[series.id];
        return (
          <tr key={series.id}>
            {at === 0 && <th scope="rowgroup" rowSpan={rows.length}><MetalName pick={pick} onOpen={onOpen} /></th>}
            <td className="mt-stage">{series.detail}</td>
            <td><TopThree top={series.top3} context={`${context}, three largest`} /></td>
            <td>{indicators === undefined ? <Reason>Not computed</Reason>
              : <Hhi item={indicators} context={`${context}, HHI`} />}</td>
            {at === 0 && <td rowSpan={rows.length}><Reliance risk={risk} chapter={chapter} /></td>}
          </tr>
        );
      })}
    </tbody>
  );
}
