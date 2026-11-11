import type { Block, Chapter, Mineral } from "../metals";
import { FINAL_PRODUCTS, ladder, missingStage, relianceCount, STAGE_WORDS, type MetalParts } from "../metalsSections";
import { NO_RELIANCE, type RiskChapter } from "../metalsStage2";
import {
  About, IEA_LABEL, Passages, QUOTED_LABEL, QUOTED_NOTE, RelianceFigure, SourceBlock, USGS_LABEL, Withheld,
} from "./MetalsBlocks";
import { Aside, Fold, items, Leader, Missing, percentOf, str, TopThree } from "./MetalsBits";
import type { Picked } from "./MetalsCompare";

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const IEA_APART = "A separate source with its own scope and definitions, never compared with the USGS stages above. "
  + "Countries are in the IEA's own order; this page does not re-rank them.";

/**
 * Supply chain: the stages USGS prints for 2025, mining then refining then any other printed stage, each with its
 * largest named country and three largest; a stage without a table is named as missing, never filled from another,
 * and final products always read as covered by no retained source. Then US import dependence and possible alternative
 * sources (USGS), the IEA's mining and refining countries in a block of their own (the six minerals), and recycling
 * and substitution where a retained source states them.
 */
export function SupplyChain({ pick, parts, mineral, ieaProblem, iea }: {
  pick: Picked; parts: MetalParts; mineral: Mineral | null; ieaProblem: string; iea: boolean;
}) {
  const { risk, research } = parts;
  const teaser = risk.shown ? `${count(risk.value.stages.length, "printed stage", "printed stages")} · final products not covered`
    : "USGS part withheld";
  const note = research.shown ? research.value : null;
  return (
    <Fold part="supply-chain" title="Supply chain" teaser={teaser}>
      <SourceBlock source="usgs" label={`${USGS_LABEL} · world production by stage, 2025`}>
        {risk.shown ? <Ladder risk={risk.value} name={pick.name} /> : <Withheld problem={risk.problem} />}
        <p className="mt-step mt-step-final" data-stage="final">{FINAL_PRODUCTS}</p>
        {risk.shown && risk.value.stages.length > 0 && (
          <p className="mt-series-foot mt-series-scope">Each stage's largest named country (CR1)<About
            name="the largest named country's share (CR1)" which="cr1" /> and three largest named (CR3)<About
            name="the three largest named countries' share (CR3)" which="cr3" /> are shares of the world total USGS
            prints for that stage, ranked among the countries it names.</p>)}
        {risk.shown && <Dependence risk={risk.value} chapter={pick.chapter} />}
        {risk.shown && <Alternatives risk={risk.value} name={pick.name} />}
      </SourceBlock>
      {iea && (
        <SourceBlock source="iea" label={`${IEA_LABEL} · mining and refining by country, base case, 2025`}
                     note={IEA_APART}>
          {mineral === null ? <Withheld problem={ieaProblem} />
            : <ul className="mt-steps-iea">{items<Block>(mineral.supply).map((block, at) => (
              <IeaStage key={at} block={block} />))}</ul>}
        </SourceBlock>)}
      <SourceBlock source="quoted" label={`${QUOTED_LABEL} · substitution and recycling`} note={QUOTED_NOTE}>
        {!research.shown ? <Withheld problem={research.problem} /> : (
          <>
            <h4>Substitution</h4>
            <Passages list={note?.substitution ?? []} none="No retained source on substitution for this metal." />
            <h4>Recycling</h4>
            <Passages list={note?.recycling ?? []} none="No retained source on recycling for this metal." />
          </>)}
      </SourceBlock>
    </Fold>
  );
}

function Ladder({ risk, name }: { risk: RiskChapter; name: string }) {
  return (
    <ol className="mt-ladder" aria-label={`${name}: stages USGS prints for 2025`}>
      {ladder(risk).map((step, at) => step.kind === "missing" ? (
        <li key={`missing-${step.stage}`} className="mt-step is-missing" data-stage={step.stage}>
          <span className="mt-step-tag">{STAGE_WORDS[step.stage]}</span>
          <span className="mt-step-body">{missingStage(step.stage)}</span>
        </li>) : (
        <li key={`${step.stage.series}-${at}`} className="mt-step" data-stage={step.stage.stage}>
          <span className="mt-step-tag">{STAGE_WORDS[step.stage.stage]}</span>
          <span className="mt-step-body">
            <span className="mt-step-name">{step.stage.detail}</span>
            <span className="mt-step-figures">Largest named: <Leader top={step.stage.leader}
              context={`${name}, ${step.stage.detail}, largest`} />{" "}<span className="mt-dot" aria-hidden="true">·</span>{" "}
              Three largest named: <TopThree top={step.stage.top3} context={`${name}, ${step.stage.detail}, three largest`} />
            </span>
          </span>
        </li>))}
    </ol>
  );
}

function Dependence({ risk, chapter }: { risk: RiskChapter; chapter: Chapter | null }) {
  const { reliance, secondary } = risk.us;
  return (
    <>
      <h4>US import dependence</h4>
      <dl className="mt-facts">
        <div><dt>US net import reliance, 2025<About name="US net import reliance" which="reliance" /></dt>
          <dd>{reliance === null ? <Missing>{NO_RELIANCE}</Missing> : (
            <RelianceFigure reliance={reliance} count={chapter === null ? 1 : relianceCount(chapter)}
                            basis={`${reliance.detail}, as printed`} />)}</dd></div>
        <div><dt>US secondary production, 2025</dt>
          <dd>{secondary.length === 0 ? <Missing>USGS prints no US secondary production row for this metal</Missing> : (
            <ul className="mt-list mt-list-tight">{secondary.map((row, at) => (
              <li key={at}>{row.detail}: <span className="mt-printed">{row.value}</span> {row.unit}</li>))}</ul>)}</dd></div>
      </dl>
    </>
  );
}

function Alternatives({ risk, name }: { risk: RiskChapter; name: string }) {
  const { alternatives, reserves_only: only } = risk;
  return (
    <>
      <h4>Possible alternative sources</h4>
      {alternatives === null ? <p><Missing label="Not shown">Not computed: the USGS file has no paired 2025 reserves and
        mine-production tables with shares for this metal</Missing></p> : (
        <>
          <p className="mt-plain">Named countries whose share of world reserves is larger than their share of world mine
            output, in USGS's paired 2025 tables. A larger share of reserves does not measure a capacity or a plan to
            produce more.<Aside label="About this comparison">Both shares are USGS's own, each against its table's
            printed world total; the comparison is made by the server, and only countries named in both tables are
            compared.</Aside></p>
          {alternatives.length === 0 ? <p className="mt-none">No named country holds a larger share of world reserves
            than of world mine output.</p> : (
            <table className="mt-table mt-narrow mt-alt-table" aria-label={`${name}, possible alternative sources`}>
                <thead><tr><th scope="col">Country</th><th scope="col" className="mt-num">Share of world reserves</th>
                  <th scope="col" className="mt-num">Share of world mine output</th></tr></thead>
                <tbody>{alternatives.map((row) => (
                  <tr key={row.country}><th scope="row">{row.country}</th>
                    <td className="mt-num"><span className="mt-share">{row.reserves}%</span></td>
                    <td className="mt-num"><span className="mt-share">{row.production}%</span></td></tr>))}
                </tbody>
              </table>)}
          {only !== null && only.length > 0 && (
            <p className="mt-plain">Named in the reserves table with no row in the mine-production table:{" "}
              {only.map((row, at) => (
                <span key={row.country}>{at > 0 && "; "}{row.country} <span className="mt-share">{row.reserves}%</span></span>))}
              {" "}of world reserves.</p>)}
        </>)}
    </>
  );
}

function IeaStage({ block }: { block: Block }) {
  const first = items<Block["countries"][number]>(block.countries).slice(0, 3);
  return (
    <li className="mt-step-iea">
      <span className="mt-step-name">{str(block.stage)}</span>
      <span className="mt-step-figures">
        {first.map((line, at) => (
          <span key={at}>{at > 0 && <>{" "}<span className="mt-dot" aria-hidden="true">·</span>{" "}</>}
            <span className="mt-country">{str(line.country)}</span>{" "}
            <span className="mt-share">{percentOf(line.shares?.["2025"])}</span></span>))}
        <span className="mt-sub">Listed first in the IEA's table (its order, not a ranking), each as a share of its
          total.</span>
        <span className="mt-sub">The IEA's own published top-3 share: {percentOf(block.top3_published?.["2025"])}.</span>
      </span>
    </li>
  );
}
