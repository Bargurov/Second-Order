import { useEffect, useState } from "react";
import { useLoad } from "../api";
import { Skeleton } from "../components/Chrome";
import { Kind, SectionHead } from "../components/CopperBits";
import { AnalysisToggle, FuelsAnalysis } from "../components/FuelsAnalysis";
import { FuelsBarrel } from "../components/FuelsBarrel";
import { SourceLine, StatementKind } from "../components/FuelsBits";
import { FuelsDrivers } from "../components/FuelsDrivers";
import { FuelsPrices } from "../components/FuelsPrices";
import { FuelsSituation } from "../components/FuelsSituation";
import { FuelsTransmission } from "../components/FuelsTransmission";
import { isRec } from "../copperTools";
import { formatDay, formatUtc, shortHash } from "../format";
import { fetchFuels, isText, type FuelsView } from "../fuels";
import { barrelGeometry } from "../fuelsBarrel";
import { authorship, DRIVERS, noNewerText, noteRowLine, prose, publishedText, refreshedText } from "../fuelsNote";
import { mechanismSources, mechanismsNote, METHOD_COPY } from "../fuelsSituation";
import { BARREL_LABELS, CAPTION, GLOSSARY, NOT_LIST, SCOPE_TEXT, SYNTHETIC_TEXT, UNIT_SHORT } from "../fuelsText";
import "../library.css";
import "../copperTools.css";
import "../fuels.css";

const COMMAND = "python -m second_order fuels refresh";
/** A snapshot's provider as the refresh log names it; a FRED snapshot is kept, and its prices withheld. */
const PROVIDER_NAME: Record<string, string> = { eia: "EIA", fred: "FRED (kept; prices withheld)" };
const NO_NOTE_HEADLINE = "Brent spot and the New York Harbor 3-2-1 crack";
const NOTE_STATE: Record<string, string> = {
  current: "current: written for the prices shown", earlier: "earlier: written for an earlier refresh",
  unbound: "unbound: its prices are not available, so it is not shown",
};

/**
 * The fuels reference page (/fuels, admin build; spec 2026-11-05-fuels-page-design.md, slice 1): the barrel and the
 * situation note, the spot price tiles and the method; Stage 2 (2026-11-06-fuels-stage-2-design.md) adds Situation Now,
 * Market Drivers and Economic Transmission between them, each in its component. The reply is shown only after the
 * fail-closed reader (fuels.ts) has recomputed the barrel, its changes, the crack history and every Situation Now
 * figure; prices are refreshed only by the operator's command, never from this page, which has no button.
 */
export function FuelsPage() {
  const [loaded] = useLoad(fetchFuels, "fuels");
  useEffect(() => { document.title = "Fuels · Second Order"; }, []);
  if (loaded.state === "loading") return <Skeleton />;
  if (loaded.state !== "ready") {
    return (
      <section className="state-panel" role="alert">
        <p className="kicker">Fuels</p>
        <h1>The fuels page could not be read</h1>
        <p>{loaded.message}</p>
        <p className="muted">Reload the page to read it again. This page never fetches prices; the operator refreshes
          them with <code>{COMMAND}</code>.</p>
      </section>
    );
  }
  return <Fuels view={loaded.data} />;
}

function Fuels({ view }: { view: FuelsView }) {
  return (
    <article className="library-case fu-page" data-page="fuels">
      <header className="library-case-header fu-header" aria-labelledby="fu-title">
        <p className="kicker">Fuels · reference page</p>
        <h1 id="fu-title">Fuels: the barrel and the crack</h1>
        <p className="fu-page-label">{view.page_label}</p>
      </header>
      {view.synthetic && (
        <div className="fu-synthetic" data-synthetic="banner" role="note">
          <span className="stamp">{SYNTHETIC_TEXT.head}</span><p>{SYNTHETIC_TEXT.body}</p>
        </div>
      )}
      <nav className="fu-sections" aria-label="Sections of this page">
        <a href="#barrel">Barrel</a>
        <a href="#prices">Prices</a>
        <a href="#situation">Situation</a>
        <a href="#drivers">Drivers</a>
        <a href="#transmission">Transmission</a>
        <a href="#method">Method</a>
        {view.synthetic && <span className="fu-synthetic-stamp" data-synthetic="stamp">{SYNTHETIC_TEXT.stamp}</span>}
      </nav>
      <Hero view={view} />
      <FuelsPrices view={view} />
      <FuelsSituation view={view} />
      <FuelsDrivers drivers={view.drivers} events={view.events} />
      <FuelsTransmission transmission={view.transmission} />
      <Method view={view} />
    </article>
  );
}

function Hero({ view }: { view: FuelsView }) {
  const { barrel, snapshot, note } = view;
  const geometry = barrelGeometry(barrel.basket ? Number(barrel.basket.value) : null,
                                  barrel.inputs ? Number(barrel.inputs.brent.value) : null);
  const placed = prose(note);
  const noNewer = noNewerText(note, barrel);
  const [analysisOpen, setAnalysisOpen] = useState(false);
  return (
    <section id="barrel" className="headline-row fu-hero" aria-labelledby="barrel-title">
      <div className="fu-hero-text">
        <div className="stamp-row fu-stamp-row">
          <span className="stamp">{barrel.date ? `Observed ${formatDay(barrel.date)}`
            : snapshot.state === "verified" ? "Barrel withheld" : "Prices missing"}</span>
          <span className="stamp-note">Brent spot · NY Harbor 3-2-1</span>
        </div>
        {barrel.date && (
          <p className="fu-dates">{publishedText(barrel.published_on)}
            {barrel.retrieved_at && <> · retrieved {formatDay(barrel.retrieved_at)}</>}</p>
        )}
        {placed ? (
          <>
            <h2 id="barrel-title" className="fu-headline">{placed.headline}</h2>
            <p className="fu-lede" data-summary={placed.analysis ? "analysis" : undefined}>{placed.lede}</p>
            {placed.columns && (
              <div className="fu-drivers">
                {DRIVERS.map(([key, title]) => (
                  <div key={key} className="fu-driver" data-driver={key}><h3>{title}</h3><p>{placed.columns?.[key]}</p></div>
                ))}
              </div>
            )}
            <p className="fu-note-meta">Written {formatDay(placed.written_on)} · covers data through{" "}
              {formatDay(placed.covers_through)} · written for prices as of {formatDay(placed.observation_date)}</p>
            <p className="fu-review">{authorship(placed.author, placed.review)}</p>
            {placed.analysis && <AnalysisToggle open={analysisOpen} earlier={note.state === "earlier"}
                                                onToggle={() => setAnalysisOpen((open) => !open)} />}
            {!placed.analysis && Array.isArray(placed.sources) && placed.sources.length > 0 && (
              <ul className="fu-note-sources" aria-label="Sources of this note">
                {placed.sources.map((source) => (
                  <li key={source.url + source.locator}>
                    <a className="library-external" href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
                    , {source.publisher}, {formatDay(source.date)} · {source.locator}
                  </li>
                ))}
              </ul>
            )}
            {note.state === "earlier" && <p className="fu-refreshed">{refreshedText(note)}
              {noNewer && <> <span className="fu-no-newer">{noNewer}</span></>}</p>}
          </>
        ) : (
          <>
            <h2 id="barrel-title" className="fu-headline">{NO_NOTE_HEADLINE}</h2>
            <p className="fu-lede" data-note="none">No situation note is bound to these prices.</p>
            {note.state === "unbound" && isText(note.problem) && <p className="fu-note-meta">{note.problem}</p>}
          </>
        )}
        {snapshot.state !== "verified" ? (
          <div className="fu-problem" data-snapshot={snapshot.state}>
            <p>{snapshot.problem}</p>
            {snapshot.state === "missing" && <pre><code>{COMMAND}</code></pre>}
          </div>
        ) : barrel.state === "withheld" && <div className="fu-problem" data-barrel="withheld"><p>{barrel.problem}</p></div>}
      </div>
      <figure className="fu-barrel-card">
        <div className="fu-barrel-frame"><FuelsBarrel barrel={barrel} geometry={geometry} /></div>
        <figcaption>{CAPTION}</figcaption>
      </figure>
      {placed?.analysis && <FuelsAnalysis prose={placed} earlier={note.state === "earlier"} open={analysisOpen} />}
    </section>
  );
}

const termsOf = (terms: unknown) => (Array.isArray(terms) ? terms : [])
  .filter((term): term is { id: string; title: string; url: string; read_on: string } =>
    isRec(term) && isText(term.title) && isText(term.url) && isText(term.read_on));

function Method({ view }: { view: FuelsView }) {
  const { barrel, snapshot, example } = view;
  const terms = termsOf(view.terms);
  const sources = mechanismSources(view.drivers, view.transmission);
  return (
    <section id="method" className="ct-section fu-section" aria-labelledby="method-title">
      <SectionHead id="method" kicker="Method" title="Method and glossary" />
      <div className="fu-formula" data-formula="crack">
        <p><span className="fu-formula-term">{BARREL_LABELS.basket}</span> = {barrel.definition.basket}</p>
        <p><span className="fu-formula-term">Crack 3-2-1</span> = {barrel.definition.crack}</p>
        <p className="fu-formula-note">In {barrel.definition.unit}. Gasoline and diesel are quoted per gallon; 42 gallons
          make a barrel. Spot prices only, on the latest date all three inputs share.</p>
      </div>
      <p className="fu-credit" data-notice="credit">{view.credit}</p>
      <p className="fu-page-label">{view.page_label}</p>
      <p className="fu-terms">Terms read for this use:{" "}
        {terms.map((term, index) => (
          <span key={term.id}>{index > 0 && " · "}<a className="library-external" href={term.url} target="_blank"
            rel="noreferrer">{term.title}</a> (read {formatDay(term.read_on)})</span>
        ))}</p>
      <p className="fu-refresh">{snapshot.retrieved_at
        ? <>Last refresh: retrieved {formatUtc(snapshot.retrieved_at)} with <code>{COMMAND}</code>.</>
        : <>No refresh is recorded on this machine. The operator runs <code>{COMMAND}</code>; this page never fetches.</>}
      </p>
      <p className="fu-mech-note" data-note="mechanisms">{mechanismsNote(view.drivers, view.transmission)}</p>

      <details className="fu-more">
        <summary>Full method and sources</summary>
        <h3>Every figure, its source and its dates</h3>
        <div className="ct-table-wrap">
          <table className="ct-table fu-sources-table">
            <thead><tr><th scope="col">Figure</th><th scope="col">Source</th><th scope="col">Cadence</th>
              <th scope="col">Observed</th><th scope="col">Published</th>
              <th scope="col">Retrieved</th><th scope="col">Terms and scope</th></tr></thead>
            <tbody>
              {view.series.map((row) => (
                <tr key={row.series_id} data-series={row.series_id} data-state={row.state}>
                  <th scope="row">{row.label} <span className="ct-unit">{UNIT_SHORT[row.unit]}</span>
                    <Kind kind={row.kind} title={view.labels.series_states?.[row.state] ?? row.state} /></th>
                  <td>EIA · <a className="library-external" href={row.url} target="_blank"
                    rel="noreferrer">{row.series_id}</a>
                    {isText(row.attribution) && <span className="fu-attribution" data-credit={row.series_id}>
                      {row.attribution}</span>}</td>
                  <td>{row.cadence}, published {row.publication}</td>
                  <td>{row.latest ? formatDay(row.latest.date) : row.problem}</td>
                  <td>{row.latest ? publishedText(row.latest.published_on, false) : "—"}</td>
                  <td>{row.latest && snapshot.retrieved_at ? formatUtc(snapshot.retrieved_at) : "—"}</td>
                  <td>{row.basis} <span className="fu-scope">{SCOPE_TEXT}.</span></td>
                </tr>
              ))}
              <tr data-series="crack" data-state={barrel.state}>
                <th scope="row">Crack 3-2-1 <span className="ct-unit">$/bbl</span>
                  {barrel.crack ? <Kind kind="computed" title="Computed by fixed code" />
                    : <Kind kind="missing" title="Withheld: an input is missing" />}</th>
                <td>Computed from Brent spot, NY Harbor gasoline and NY Harbor ULSD ({barrel.engine_version})</td>
                <td>daily, on dates all three inputs share</td>
                <td>{barrel.date ? formatDay(barrel.date) : barrel.problem}</td>
                <td>{barrel.date ? publishedText(barrel.published_on, false) : "—"}</td>
                <td>{barrel.date && barrel.retrieved_at ? formatUtc(barrel.retrieved_at) : "—"}</td>
                <td>Follows its three inputs.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="ct-note">Observed is the trading day a price describes. Published would be when EIA released it,
          but EIA's API does not give that date, so it is shown as not given and never inferred; EIA releases spot
          prices weekly. Retrieved is this machine's clock when the refresh received the last reply: it shows
          possession, not first public availability. A history is what EIA's file held when it was retrieved, not a
          record of what was known on the days it covers.</p>

        <h3>What the crack is not</h3>
        <ul className="fu-not-list">{NOT_LIST.map((text) => <li key={text}>{text}</li>)}</ul>

        <div className="fu-example" data-example="synthetic">
          <p className="fu-example-label">Synthetic unit example, not market data</p>
          <p>Gasoline at ${example.gasoline}/gal and diesel at ${example.diesel}/gal give a basket of (2 × {example.gasoline}
            {" "}× 42 + 1 × {example.diesel} × 42) / 3 = ${example.basket} per barrel of crude. With Brent at
            ${example.brent}, the crack is ${example.basket} − ${example.brent} = ${example.crack} per barrel.</p>
        </div>

        <h3>{METHOD_COPY.rulesHead}</h3>
        <ul className="fu-rules">{METHOD_COPY.rules.map((text) => <li key={text}>{text}</li>)}</ul>

        <h3>{METHOD_COPY.sourcesHead}</h3>
        <p className="ct-note">{METHOD_COPY.sourcesNote}</p>
        {sources.length === 0 ? <p className="ct-note">{METHOD_COPY.noSources}</p> : (
          <ul className="fu-mech-sources">{sources.map(({ source, citedBy }) => (
            <li key={source.url} data-source-url={source.url}><SourceLine source={source} locator={false} />
              {" · "}<span className="fu-cited">{METHOD_COPY.citedIn} {citedBy.join("; ")}</span></li>))}</ul>
        )}

        <h3>Refresh log</h3>
        {view.snapshots.length === 0 ? <p className="ct-note">No refresh is recorded on this machine.</p> : (
          <div className="ct-table-wrap">
            <table className="ct-table">
              <thead><tr><th scope="col">Snapshot</th><th scope="col">Retrieved</th><th scope="col">Source</th>
                <th scope="col">Series stored</th><th scope="col">Series refused</th></tr></thead>
              <tbody>{view.snapshots.map((row) => (
                <tr key={row.id} data-snapshot={row.id}>
                  <td><code>{shortHash(row.id, 12)}</code>{row.id === snapshot.id && " · shown"}</td>
                  <td>{formatUtc(row.retrieved_at)}</td><td>{PROVIDER_NAME[row.provider ?? ""] ?? "unknown"}</td>
                  <td>{row.stored}</td><td>{row.refused}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}

        <h3>Situation notes</h3>
        {view.notes.length === 0 ? <p className="ct-note">No situation note is committed.</p> : (
          <ol className="fu-notes">{view.notes.map((row) => (
            <li key={row.number} data-note={row.number} data-state={row.state}>
              Note {row.number} · {NOTE_STATE[row.state] ?? row.state} · written {formatDay(row.written_on)} for prices as
              of {formatDay(row.observation_date)} · {noteRowLine(row, view.note)}
            </li>))}</ol>
        )}

        <h3>Glossary</h3>
        <dl className="fu-glossary">{Object.entries(GLOSSARY).map(([term, text]) => (
          <div key={term}><dt>{term}</dt><dd>{text}</dd></div>))}</dl>

        <p className="ct-legend">Every number is marked: <Kind kind="published" title="Published" /> published in a
          retained source, <Kind kind="computed" title="Computed" /> computed by fixed code,{" "}
          <Kind kind="assumption" title="Assumption" /> your assumption (none on this page yet),{" "}
          <Kind kind="missing" title="Missing" /> missing, so no value is shown. {METHOD_COPY.statements}{" "}
          <StatementKind kind="explanation" label="Possible explanation" /> {METHOD_COPY.explanation}{" "}
          <StatementKind kind="sourced" label="Sourced claim" /> {METHOD_COPY.sourced}</p>
      </details>
    </section>
  );
}
