import { formatDay } from "../format";
import { ANALYSIS_COPY, ANALYSIS_SECTIONS, type AnalysisKind, type Prose } from "../fuelsNote";
import { Kind } from "./CopperBits";
import { StatementKind } from "./FuelsBits";

export const ANALYSIS_BODY_ID = "fu-analysis-body";

/** A statement's kind: the page's own badge (P, C, E or S) and its words, so an observation, a computed figure, a
 * possible explanation, a sourced claim and a projection attributed to its source never read alike. */
function KindOf({ kind }: { kind: AnalysisKind }) {
  const label = ANALYSIS_COPY.kinds[kind];
  const title = ANALYSIS_COPY.titles[kind];
  const badge = kind === "observation" ? <Kind kind="published" title={title} />
    : kind === "computed" ? <Kind kind="computed" title={title} />
      : kind === "hypothesis" ? <StatementKind kind="explanation" label={label} title={title} />
        : <StatementKind kind="sourced" label={label} title={title} />;
  return <span className="fu-an-kind" data-kind={kind}>{badge}<span className="fu-an-kind-label">{label}</span></span>;
}

/** The one button under the summary that opens and closes the analysis; an earlier note says so on it. */
export function AnalysisToggle({ open, earlier, onToggle }: { open: boolean; earlier: boolean; onToggle: () => void }) {
  return (
    <button type="button" className="fu-analysis-toggle" aria-expanded={open} aria-controls={ANALYSIS_BODY_ID}
            data-analysis={earlier ? "earlier" : "current"} onClick={onToggle}>
      {earlier ? ANALYSIS_COPY.summaryEarlier : ANALYSIS_COPY.summary}
    </button>
  );
}

/**
 * The analysis of a fuels-note-0.2, in its own row under the summary and the barrel (so opening it never stretches the
 * barrel's row): what happened, what it may mean, who it may touch and what to check next, each statement labelled by
 * kind, with its sources by number and the mechanism it draws on; then what it cannot tell and its sources with their
 * dates and places. Every figure, date and direction in it was filled by the server from the snapshot the note was
 * written for.
 */
export function FuelsAnalysis({ prose, earlier, open }: { prose: Prose; earlier: boolean; open: boolean }) {
  const analysis = prose.analysis;
  if (!analysis) return null;
  return (
    <div id={ANALYSIS_BODY_ID} className="fu-analysis" role="region" aria-label={ANALYSIS_COPY.region}
         data-analysis={earlier ? "earlier" : "current"} hidden={!open}>
      {ANALYSIS_SECTIONS.map(([key, title]) => (
        <section key={key} className="fu-an-part" data-part={key}>
          <h3>{title}</h3>
          <ul className="fu-an-list">
            {analysis[key].map((item, index) => (
              <li key={index} data-kind={item.kind}>
                <KindOf kind={item.kind} />
                <span className="fu-an-text">{item.text}
                  {item.sources.length > 0 && (
                    <span className="fu-an-refs">{" "}{item.sources.map((ref) => (
                      <a key={ref} href={`#fu-an-source-${ref + 1}`}
                         aria-label={`${ANALYSIS_COPY.source} ${ref + 1}`}>[{ref + 1}]</a>))}</span>)}
                </span>
                {item.mechanism && item.mechanism_title && (
                  <span className="fu-an-mech">{ANALYSIS_COPY.mechanism}{" "}
                    <a href={item.mechanism.startsWith("transmission:") ? "#transmission" : "#drivers"}>
                      {item.mechanism_title}</a></span>)}
              </li>))}
          </ul>
        </section>))}
      <section className="fu-an-part" data-part="caveats">
        <h3>{ANALYSIS_COPY.caveatsHead}</h3>
        <ul className="fu-an-caveats">{analysis.caveats.map((text, index) => <li key={index}>{text}</li>)}</ul>
      </section>
      <section className="fu-an-part" data-part="sources">
        <h3>{ANALYSIS_COPY.sourcesHead}</h3>
        <ol className="fu-an-sources">
          {prose.sources.map((source, index) => (
            <li key={index} id={`fu-an-source-${index + 1}`}>
              <a className="library-external" href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
              , {source.publisher}, {formatDay(source.date)} · {source.locator}
            </li>))}
        </ol>
      </section>
      <p className="fu-an-legend">{ANALYSIS_COPY.legend}</p>
    </div>
  );
}
