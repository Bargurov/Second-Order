import type { ReactNode } from "react";
import { YEARS_LABEL, type Chapter, type Series } from "../metals";
import { missingStage, relianceCount, stageOfSeries, type MetalParts } from "../metalsSections";
import { NO_PAIR, NO_RELIANCE, NO_RESERVES, reservesOf, type RiskChapter, type UseEntry } from "../metalsStage2";
import { yearsText } from "../metalsWords";
import { About, RelianceFigure, Withheld } from "./MetalsBlocks";
import { items, Leader, Missing, str, Why } from "./MetalsBits";
import type { Picked } from "./MetalsCompare";

const USGS_SOURCE = "USGS MCS 2026 data release";
const IEA_SOURCE = "IEA Critical Minerals Dataset 2026 · energy technologies";

function Item({ id, term, source, about, children }: {
  id: string; term: string; source: string; about?: ReactNode; children: ReactNode;
}) {
  return (
    <div className="mt-snap-item" data-snap={id}>
      <dt>{term}{about}</dt>
      <dd><div className="mt-snap-value">{children}</div><p className="mt-snap-source">{source}</p></dd>
    </div>
  );
}

/**
 * The snapshot, always open at the top of each metal: a compact grid of definitions, each naming its source. Every
 * value is one the reply holds (USGS figures through the risk part and the chapter, the IEA's through the uses part);
 * an item the retained sources do not hold says so, and a withheld part gives its problem once.
 */
export function MetalSnapshot({ pick, parts }: { pick: Picked; parts: MetalParts }) {
  return (
    <section className="mt-snapshot" data-snapshot="" aria-labelledby={`mt-${pick.id}-snapshot`}>
      <h4 id={`mt-${pick.id}-snapshot`} className="mt-snap-title">Snapshot</h4>
      <dl className="mt-snap-grid">
        {parts.risk.shown && pick.chapter !== null
          ? <UsgsItems chapter={pick.chapter} risk={parts.risk.value} name={pick.name} />
          : <Item id="usgs" term="USGS figures" source={USGS_SOURCE}>
            <Withheld problem={parts.risk.shown ? "" : parts.risk.problem} /></Item>}
        <Item id="iea" term="IEA energy-technology demand, 2025" source={IEA_SOURCE}>
          {parts.uses.shown ? <IeaTotals entries={parts.uses.value} /> : <Withheld problem={parts.uses.problem} />}
        </Item>
      </dl>
    </section>
  );
}

function UsgsItems({ chapter, risk, name }: { chapter: Chapter; risk: RiskChapter; name: string }) {
  const top = stageOfSeries(risk, risk.most_concentrated);
  const [reserves, years] = reservesOf(chapter, risk);
  const critical = str(chapter.critical);
  const issues = items<Series>(chapter.series).filter((series) => str(series.unit_issue) !== "");
  const reliance = risk.us.reliance;
  return (
    <>
      <Item id="leaders" term="Largest named producer, by stage" source={`${USGS_SOURCE} · world production, 2025`}
            about={<About name="the largest named country's share (CR1)" which="cr1" />}>
        {risk.stages.length === 0 ? <Missing>USGS's file has no 2025 production table for this metal</Missing> : (
          <ul className="mt-snap-list">{risk.stages.map((stage) => (
            <li key={stage.series}><span className="mt-snap-key">{stage.detail}</span>{" "}
              <Leader top={stage.leader} context={`${name}, ${stage.detail}, largest producer`} /></li>))}
            {risk.missing_stages.map((stage) => (
              <li key={stage} className="mt-snap-missing">{missingStage(stage)}</li>))}
          </ul>)}
      </Item>
      <Item id="concentrated" term="Largest single-country share, by stage"
            source={`${USGS_SOURCE} · world production, 2025`}>
        {top === null ? (risk.stages.length === 0 ? <Missing>No 2025 production table in the USGS file</Missing>
          : <Missing label="Not shown">No 2025 stage has a largest producer that can be ranked</Missing>) : (
          <><span className="mt-snap-key">{top.detail}</span>{" "}
            <Leader top={top.leader} /><About name="the largest single-country share, by stage" which="concentrated" /></>)}
      </Item>
      <Item id="reserves" term="Largest named reserves holder; years of reserves"
            source={`${USGS_SOURCE} · world reserves, 2025`}>
        {reserves === null ? <Missing>{NO_RESERVES}</Missing> : (
          <>
            <Leader top={reserves.leader} context={`${name}, reserves`} />
            <span className="mt-sub">of world reserves{reserves.detail !== "Reserves" ? ` · ${reserves.detail}` : ""}</span>
            <span className="mt-snap-line">{years === null ? <Missing>{NO_PAIR}</Missing>
              : years.shown === null ? <Why reason={years.reason} kind="years" context={`${name}, years of reserves`} />
                : <><span className="mt-years-value">{yearsText(years.shown)}</span>
                  <span className="mt-sub">{YEARS_LABEL}</span></>}</span>
          </>)}
      </Item>
      <Item id="reliance" term="US net import reliance, 2025" source={`${USGS_SOURCE} · as printed`}>
        {reliance === null ? <Missing>{NO_RELIANCE}</Missing> : (
          <RelianceFigure reliance={reliance} count={relianceCount(chapter)} basis={reliance.detail}
                          about={<About name="US net import reliance" which="reliance" />} />)}
      </Item>
      <Item id="critical" term="On the 2025 critical-minerals list" source={`${USGS_SOURCE} · as the file marks it`}>
        {critical === "" ? <Missing>The USGS file gives no mark for this chapter</Missing>
          : <span className="mt-snap-mark">{critical}</span>}
      </Item>
      {issues.length > 0 && (
        <Item id="unit" term="Unit issue" source="USGS data file against its printed chapter">
          {issues.map((series) => (
            <span key={series.id} className="mt-snap-line">
              <Why reason={series.unit_issue} label="Unit in doubt" context={`${name}, ${str(series.statistic)}`} />
              <span className="mt-sub">{str(series.statistic)} · {str(series.detail)} · {str(series.year)}</span>
            </span>))}
        </Item>)}
    </>
  );
}

function IeaTotals({ entries }: { entries: UseEntry[] }) {
  if (entries.length === 0) return <Missing>The IEA's energy-technology table has no entry for this metal</Missing>;
  const notes = [...new Set(entries.map((entry) => entry.scope_note).filter((note): note is string => !!note))];
  return (
    <>
      <ul className="mt-snap-list">{entries.map((entry) => (
        <li key={entry.name}><span className="mt-snap-key">{entry.name}</span>{" "}
          <span className="mt-printed">{str(entry.total["2025"])} kt</span></li>))}
      </ul>
      {notes.map((note) => <span key={note} className="mt-sub">{note}</span>)}
    </>
  );
}
