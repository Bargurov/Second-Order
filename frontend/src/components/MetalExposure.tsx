import type { Chapter } from "../metals";
import { leaderPair, NO_EVENT, splitEvents, type MetalParts } from "../metalsSections";
import { reservesOf, type RiskChapter } from "../metalsStage2";
import { EVENTS_NOTE, Passage, QUOTED_LABEL, SourceBlock, USGS_LABEL, Withheld } from "./MetalsBlocks";
import { Fold, Leader, Missing, Why } from "./MetalsBits";
import type { Picked } from "./MetalsCompare";

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * Geopolitical exposure: structural indicators only, from the reply (the largest named country at each 2025 stage and
 * in reserves, whether one country is largest at both mining and refining, the largest US import source of each
 * table); events only from the retained primary sources (official publications or filings, dated) the research notes
 * cite and only when the quote is verified on this read, each quoted with its source and place and dated as its quote
 * dates it (a past event, not news), else the fixed words
 * that no verified event is retained. A cited passage that is not verified is never shown or counted as an event: it is
 * listed apart, with its reason and no kind.
 */
export function Exposure({ pick, parts }: { pick: Picked; parts: MetalParts }) {
  const { risk, research } = parts;
  const { shown: events, unverified } = splitEvents(research.shown ? research.value?.events ?? [] : []);
  const teaser = `${risk.shown ? "structural" : "USGS part withheld"} · ${!research.shown ? "notes withheld"
    : events.length === 0 ? "no verified event" : count(events.length, "verified event", "verified events")}`;
  return (
    <Fold part="exposure" title="Geopolitical exposure" teaser={teaser}>
      <SourceBlock source="usgs" label={`${USGS_LABEL} · structural exposure, 2025`}
                   note="Where supply sits, not what has happened: a large share is an exposure, not an event.">
        {!risk.shown || pick.chapter === null ? <Withheld problem={risk.shown ? "" : risk.problem} />
          : <Structure chapter={pick.chapter} risk={risk.value} name={pick.name} />}
      </SourceBlock>
      <SourceBlock source="quoted" label={`${QUOTED_LABEL} · events`} note={EVENTS_NOTE}>
        {!research.shown ? <Withheld problem={research.problem} /> : (
          <>
            {events.length === 0 ? <p className="mt-none" data-no-event="">{NO_EVENT}</p> : (
              <div className="mt-quotes" data-events="">{events.map((event) => (
                <Passage key={event.passage} cited={event} kind={event.kind} when={event.when} />))}</div>)}
            {unverified.length > 0 && (
              <div className="mt-unverified" data-unverified="">
                <h4>Cited, not verified on this read</h4>
                <div className="mt-quotes">{unverified.map((event) => (
                  <Passage key={event.passage} cited={event} reason />))}</div>
              </div>)}
          </>)}
      </SourceBlock>
    </Fold>
  );
}

function Structure({ chapter, risk, name }: { chapter: Chapter; risk: RiskChapter; name: string }) {
  const [reserves] = reservesOf(chapter, risk);
  const pair = leaderPair(risk);
  const groups = risk.us.imports;
  return (
    <dl className="mt-facts">
      <div>
        <dt>Largest single-country share, by stage</dt>
        <dd>{risk.stages.length === 0 && reserves === null
          ? <Missing>USGS's file has no 2025 production or reserves table for this metal</Missing> : (
          <ul className="mt-list mt-list-tight">
            {risk.stages.map((stage) => (
              <li key={stage.series}>{stage.detail}: <Leader top={stage.leader}
                context={`${name}, ${stage.detail}, largest`} /></li>))}
            {reserves !== null && <li>{reserves.detail === "Reserves" ? "Reserves" : `Reserves (${reserves.detail})`}:{" "}
              <Leader top={reserves.leader} context={`${name}, reserves, largest`} /></li>}
          </ul>)}</dd>
      </div>
      <div>
        <dt>One country largest at several stages?</dt>
        <dd data-leaders-differ={String(risk.leaders_differ)}>{risk.leaders_differ === null || pair === null
          ? <Missing label={risk.missing_stages.length > 0 ? "Not in the retained sources" : "Not shown"}>No ranked
            mining and refining pair in USGS's file for this metal, so the stages cannot be compared</Missing>
          : risk.leaders_differ
            ? <>No: different countries are largest at mining ({pair.mining.leader.countries[0]}) and refining
              ({pair.refining.leader.countries[0]}).</>
            : <>Yes: {pair.mining.leader.countries[0]} is largest at both mining and refining.</>}</dd>
      </div>
      <div>
        <dt>Largest US import source</dt>
        <dd>{groups.length === 0 ? <Missing>USGS prints no US import sources for this metal</Missing> : (
          <ul className="mt-list mt-list-tight">{groups.map((group, at) => (
            <li key={at}>{group.detail} <span className="mt-sub-inline">({group.years})</span>:{" "}
              {group.reason !== null ? <Why reason={group.reason} kind="rank" context={`${name}, ${group.detail}`} />
                : group.leader === null ? <span className="mt-withheld">no named source</span>
                  : <><span className="mt-country">{group.leader.country}</span>{" "}
                    <span className="mt-share">{group.leader.value}%</span> of US imports</>}</li>))}
          </ul>)}</dd>
      </div>
    </dl>
  );
}
