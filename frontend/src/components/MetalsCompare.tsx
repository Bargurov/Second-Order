import { reservesFor, YEARS_LABEL, type Chapter, type MetalsView } from "../metals";
import { yearsText } from "../metalsWords";
import { ConcentrationTable } from "./MetalsConcentration";
import { Aside, items, Leader, MetalName, production2025, Reason, str, TopThree, Why } from "./MetalsBits";

/** Each picked metal's chapter, or null when the USGS part is withheld (its frame then gives only id and name). */
export interface Picked { id: string; name: string; chapter: Chapter | null }

/** What the overview table shows: the largest countries (leaders), or the concentration indicators. */
export type OverviewMode = "leaders" | "concentration";
const MODES: { id: OverviewMode; label: string }[] = [
  { id: "leaders", label: "Leaders" }, { id: "concentration", label: "Concentration" }];

/**
 * The overview: one row per picked metal and 2025 production series, in pick order then file order. A pick with no
 * 2025 production series, or a withheld USGS part, still has its row. A figure that is not shown gives a short label
 * and a "Why?" button with the full reason. Every share, ranking, concentration and years figure is the server's,
 * recomputed by the reader; this table only lays them out. A metal's name opens it under "By metal". A switch above the
 * table shows either the leaders (largest countries, reserves, years) or the concentration indicators.
 */
export function MetalsCompare({ view, picked, mode, onMode, onOpen, onPick }: {
  view: MetalsView; picked: Picked[]; mode: OverviewMode; onMode: (mode: OverviewMode) => void;
  onOpen: (id: string) => void; onPick: () => void;
}) {
  const problem = str(view.usgs.problem);
  const leaders = mode === "leaders";
  return (
    <section id="compare" className="mt-overview" data-compare="" data-mode={mode} aria-labelledby="compare-title">
      <div className="mt-overview-head">
        <h2 id="compare-title">{leaders ? "Production and reserves by country, 2025" : "Concentration by stage, 2025"}</h2>
        {leaders ? <LeadersScope /> : <ConcentrationScope />}
      </div>
      {view.usgs.state !== "available" && (
        <p className="mt-banner" data-banner="usgs" role="note"><strong>USGS figures withheld.</strong> {problem}</p>)}
      {picked.length === 0 ? (
        <p className="mt-empty">No metal is picked. <button type="button" className="mt-text-button"
                                                            onClick={onPick}>Pick metals</button></p>) : (
        <>
          <div className="mt-switch" role="group" aria-label="Overview table shows" data-switch="">
            {MODES.map((item) => (
              <button key={item.id} type="button" className="mt-switch-button" data-mode={item.id}
                      aria-pressed={mode === item.id} onClick={() => onMode(item.id)}>{item.label}</button>))}
          </div>
          {leaders ? <LeadersTable picked={picked} problem={problem} onOpen={onOpen} />
            : <ConcentrationTable view={view} picked={picked} problem={problem} onOpen={onOpen} />}
        </>
      )}
    </section>
  );
}

function ConcentrationScope() {
  return (
    <>
      <p className="mt-scope-line" data-concentration-scope="">Each figure is among the countries USGS names; the HHI is
        a range because “Other countries” is one group USGS does not split.</p>
      <details className="mt-howto" data-concentration-howto="">
        <summary>How to read this table</summary>
        <div className="mt-howto-body">
          <p>One row for each 2025 production stage of each picked metal. The three largest named countries' combined
            share (CR3) is of the world total USGS prints for that stage.</p>
          <p>The HHI adds up each named country's squared share, times 10,000. Its low bound treats “Other countries”
            as many small holders, its high bound as one; the named countries' coverage beside it says how much of the
            world total they hold, and the lower it is, the wider the range.</p>
          <p>US net import reliance is the 2025 figure as USGS prints it, codes and bounds included. It describes US
            supply, not world supply.</p>
          <p>No figure here is combined into a score. When a figure is not shown, its cell gives a short label; “Why?”
            opens the full reason.</p>
        </div>
      </details>
    </>
  );
}

function LeadersScope() {
  return (
    <>
      <p className="mt-scope-line" data-ranking-scope="">Rankings are among the countries USGS names; “Other countries”
        is one group it does not split.</p>
      <details className="mt-howto" data-howto="">
        <summary>How to read this table</summary>
        <div className="mt-howto-body">
          <p>One row for each production stage of each picked metal. A share is the country's part of the world total
            USGS prints for that stage, and USGS rounds most world totals.</p>
          <p>“Other countries” is never ranked and can hold more than a named country does, so the three largest
            named producers are not a complete ranking of the world.</p>
          <p>Years of reserves divides world reserves by world output, {YEARS_LABEL}. Under one year it reads “less
            than 1 year”; where a table's unit is in doubt, it is not computed.</p>
          <p>When a figure is not shown, its cell gives a short label; “Why?” opens the full reason.</p>
        </div>
      </details>
    </>
  );
}

function LeadersTable({ picked, problem, onOpen }: { picked: Picked[]; problem: string; onOpen: (id: string) => void }) {
  return (
    <div className="mt-table-wrap" role="region" aria-labelledby="compare-title" tabIndex={0}>
      <table className="mt-table mt-compare-table">
        <thead>
          <tr>
            <th scope="col">Metal</th>
            <th scope="col">Stage</th>
            <th scope="col">Top named producer<span className="mt-sub">share of world output</span></th>
            <th scope="col">Three largest named<span className="mt-sub">combined share of world output</span></th>
            <th scope="col">Top named reserves holder<span className="mt-sub">share of world reserves</span></th>
            <th scope="col">Years of reserves<span className="mt-sub">{YEARS_LABEL}</span></th>
          </tr>
        </thead>
        {picked.map((pick) => <Rows key={pick.id} pick={pick} problem={problem} onOpen={onOpen} />)}
      </table>
    </div>
  );
}

function Rows({ pick, problem, onOpen }: { pick: Picked; problem: string; onOpen: (id: string) => void }) {
  const { chapter } = pick;
  if (chapter === null) {
    return (
      <tbody data-metal={pick.id} data-state="withheld">
        <tr><th scope="row"><MetalName pick={pick} onOpen={onOpen} /></th>
          <td colSpan={5}><Why reason={problem} label="Withheld" /></td></tr>
      </tbody>
    );
  }
  const rows = production2025(chapter);
  if (rows.length === 0) {
    return (
      <tbody data-metal={pick.id} data-state="none">
        <tr><th scope="row"><MetalName pick={pick} onOpen={onOpen} /></th>
          <td colSpan={5}><Reason>No 2025 production by country in the USGS file</Reason></td></tr>
      </tbody>
    );
  }
  return (
    <tbody data-metal={pick.id} data-state="available">
      {rows.map((series, at) => {
        const reserves = reservesFor(chapter, series);
        const years = items<{ production: string; shown: string | null; reason: string | null }>(chapter.years_of_reserves)
          .find((item) => item.production === series.id);
        const stage = str(series.detail);
        const context = `${pick.name}, ${stage}`;
        const reservesDetail = reserves === null ? "" : str(reserves.series.detail);
        // An unpaired series (the chapter's only 2025 reserves) is always named by its printed detail.
        const named = reservesDetail !== "" && (reserves?.paired === false || reservesDetail !== "Reserves");
        return (
          <tr key={series.id}>
            {at === 0 && <th scope="rowgroup" rowSpan={rows.length}><MetalName pick={pick} onOpen={onOpen} /></th>}
            <td className="mt-stage">{stage}</td>
            <td><Leader top={series.leader} context={`${context}, top producer`} /></td>
            <td><TopThree top={series.top3} context={`${context}, three largest`} /></td>
            <td>{reserves === null ? <Why reason="No matching 2025 reserves series" label="No matching series" /> : (
              <><Leader top={reserves.series.leader} context={`${context}, reserves`} />
                {named && <span className="mt-sub">{reservesDetail}</span>}</>)}</td>
            <td className="mt-years">{years === undefined
              ? <Why reason="Not computed: no 2025 reserves series matches this stage" kind="years" />
              : years.shown === null ? <Why reason={years.reason} kind="years" context={`${context}, years`} />
                : <><span className="mt-years-value">{yearsText(years.shown)}</span>
                  <Aside label={`About years of reserves: ${YEARS_LABEL}`}>{YEARS_LABEL}</Aside></>}</td>
          </tr>
        );
      })}
    </tbody>
  );
}
