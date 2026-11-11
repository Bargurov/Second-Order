import type { ReactNode } from "react";
import { fetchMarketContext, useLoad } from "../api";
import { contextRows, discardedNote, formatContextDate, gapCounts, type MarketContextView } from "../marketContext";
import { ContextChart, ContextTable } from "./ContextChart";

const External = ({ href, children }: { href: string; children: ReactNode }) => (
  <a className="library-external" href={href} target="_blank" rel="noreferrer">{children}</a>
);

/**
 * A case's market context: the Board's daily H.15 2-year and 10-year yields around the publication date, read and
 * verified by the server. If it cannot be read or does not verify, the reason is shown instead; nothing is substituted.
 */
export function MarketContextSection({ caseId, statedTime }: { caseId: string; statedTime: string }) {
  const [loaded] = useLoad((signal) => fetchMarketContext(caseId, signal), `market-context:${caseId}`);
  if (loaded.state === "loading") return <p className="context-state" role="status">Loading market context…</p>;
  if (loaded.state !== "ready") {
    return (
      <div className="context-unavailable" role="status" data-state={loaded.state}>
        <p><strong>Market context is not available for this case.</strong> {loaded.message}</p>
        <p>The editorial case is shown without it. No substitute, estimated or synthetic data is shown in its place.</p>
      </div>
    );
  }
  return <ContextView view={loaded.data} statedTime={statedTime} />;
}

function ContextView({ view, statedTime }: { view: MarketContextView; statedTime: string }) {
  const rows = contextRows(view);
  const gaps = gapCounts(view).filter(({ count }) => count > 0);
  const published = formatContextDate(view.publication.new_york_date);
  const range = `${formatContextDate(view.window.start)} to ${formatContextDate(view.window.end)}`;
  const { provenance, source } = view;
  return (
    <div className="context" data-case={view.case_id}>
      <p>
        Daily 2-year and 10-year Treasury constant-maturity yields from the Federal Reserve Board's H.15 release, for
        the {view.window.days_before} calendar days before and {view.window.days_after} after the New York publication
        date, {published}. Each value is a date-labelled daily yield as the Board published it when retrieved; the
        source gives no time of day. These are not intraday prices, transaction prices, bond returns or a measured
        reaction to the release.
      </p>
      <p className="context-skip-row"><a href="#context-data">Go to the data table</a></p>
      <ContextChart view={view} marker="Publication date"
        markerLegend={`Publication date, ${published} (New York)`}
        desc={`Two lines in percent, with the publication date, ${published}, marked. Every value is listed in the table below the chart.`} />

      <ContextTable view={view} rows={rows} markerTag="Publication date"
        caption={`Daily values, ${range}, in percent per year as the Board published them`} />

      <h3>Source and provenance</h3>
      <dl className="ledger context-provenance">
        {view.series.map((series) => (
          <div key={series.id}>
            <dt>{series.short_label}</dt>
            <dd>
              {series.description.split(/\s+/).join(" ")}. H.15 series <code>{series.unique_identifier}</code>;{" "}
              {series.units_label.toLowerCase()} (the source's unit: {series.unit}); multiplier {series.multiplier};{" "}
              {series.frequency.toLowerCase().replace(/ /g, "-")} frequency. FRED republishes it as{" "}
              <External href={series.fred_page}>{series.fred_equivalent}</External>, per the Board's{" "}
              <External href={provenance.crosswalk_url}>DDP–FRED crosswalk</External>; no value here came from FRED.
            </dd>
          </div>
        ))}
        <div><dt>Publisher</dt><dd>
          <External href={provenance.release_url}>{provenance.publisher}, {provenance.release}</External>. The Board
          gives the {provenance.underlying_source} as the source of its Treasury constant-maturity yields.</dd></div>
        <div><dt>Rights</dt><dd>“{provenance.terms.statement}” (<External href={provenance.terms.url}>Board website
          disclaimer</External>). The notice excepts non-Board material marked as copyrighted or trademarked, and the
          Board's seals and logos; neither is used here, and nothing here is affiliated with or endorsed by the
          Board.</dd></div>
        <div><dt>Window</dt><dd>{range}: {view.window.days_before} calendar days either side of {published}, fixed before
          the data were read and the same for every case.</dd></div>
        <div><dt>Publication time</dt><dd>{statedTime}; the New York date is {view.publication.new_york_date}.</dd></div>
        <div><dt>Retrieved</dt><dd>Requested {source.requested_at}, received {source.received_at} (server date{" "}
          {source.response_date}); HTTP {source.http_status}, {source.content_type}. {discardedNote(provenance.discarded)}
          </dd></div>
        <div><dt>Acquisition run</dt><dd>Run {provenance.run} of {provenance.runs}, one of {provenance.run_cases.length}{" "}
          {provenance.run_cases.length === 1 ? "download" : "downloads"} made together; other runs were made at other
          times and are recorded separately. {provenance.method}</dd></div>
        <div><dt>Vintage</dt><dd>{provenance.vintage_note} (<External href={provenance.help_url}>Data Download Program
          help</External>)</dd></div>
        <div><dt>Calendar</dt><dd>{provenance.calendar.calendar} via {provenance.calendar.library}{" "}
          {provenance.calendar.library_version}, calendar exceptions version {provenance.calendar.exceptions_version}:
          it decides which dates were expected sessions.</dd></div>
        <div className="context-hash"><dt>Source file</dt><dd>{source.rows} rows, {source.returned_first} to{" "}
          {source.returned_last} (requested {source.requested_start} to {source.requested_end}); {source.bytes} bytes;
          SHA-256 <code>{source.sha256}</code>. Download address: <code>{source.url}</code>.</dd></div>
        <div className="context-hash"><dt>Integrity</dt><dd>Prepared view SHA-256 <code>{provenance.view_sha256}</code>;
          acquisition record ({provenance.acquisition_record}) SHA-256 <code>{provenance.acquisition_sha256}</code>;
          run manifest ({provenance.manifest}) SHA-256 <code>{provenance.manifest_sha256}</code>; index of runs SHA-256{" "}
          <code>{provenance.index_sha256}</code>; {provenance.preparation_version}. On this read the server re-derived
          every value and status above from the source file, and they matched.</dd></div>
      </dl>
      <ul className="library-points context-citations">
        {view.series.map((series) => <li key={series.id}>{series.citation}</li>)}
      </ul>

      <h3>What this shows and does not show</h3>
      <ul className="library-points">
        <li>It shows the Board's daily values around the publication date beside the case's interpretation. It does not
          attribute any movement to the release: daily data cannot separate the release from other news on the same
          or nearby days.</li>
        <li>Each value carries a date only; the source gives no time of day, so the chart cannot show whether a day's
          value came before or after the release. The marker shows the publication date, not a moment in the
          series.</li>
        <li>No change over a horizon is computed and nothing is labelled as support or contradiction. This is not
          an event study, a hypothesis or a score, and it never enters research summaries.</li>
        <li>These are the Board's values when retrieved, not a historical vintage; what was available on the
          publication date could have differed.</li>
        <li>Gaps stay gaps: nothing is interpolated or carried forward.{" "}
          {gaps.length === 0
            ? "In this window every expected session has a value for both series."
            : `Expected sessions without a value are marked on the chart and listed in the table: ${gaps.map(({ series, count }) =>
                `${count} for the ${series.short_label}`).join(", ")}.`}</li>
      </ul>
    </div>
  );
}
