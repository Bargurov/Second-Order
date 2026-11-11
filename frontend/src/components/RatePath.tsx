import type { CSSProperties, ReactNode } from "react";
import { useLoad } from "../api";
import { formatDay, formatUtc, shortHash } from "../format";
import {
  fetchRatePath, prepareCommand, strip, type RatePathView, type RateWindow, type Statistic,
} from "../ratePath";
import "../ratePath.css";

type Variant = "overview" | "research";

/**
 * A saved event's market-implied rate path: the first four three-month SOFR reference windows the Atlanta Fed's
 * Market Probability Tracker lists on the last observation date before the statement, read from a separate, verified
 * record. It only reads: preparing is an explicit local command. Meeting-specific pricing stays visibly unavailable,
 * and on the research page the panel says plainly that the analysis's request never carried this context.
 */
export function RatePath({ captureId, variant, analysisSentAt = null }: { captureId: string; variant: Variant;
                                                                      analysisSentAt?: string | null }) {
  const [loaded, retry] = useLoad((signal) => fetchRatePath(captureId, signal), `rate-path:${captureId}`);
  const id = variant === "overview" ? "overview-rate-path" : "research-rate-path";
  let body: ReactNode;
  if (loaded.state === "loading") {
    body = <p className="event-context-state" role="status">Reading the saved rate-path record…</p>;
  } else if (loaded.state !== "ready") {
    body = (
      <>
        <p className="event-context-error" role="alert">The rate path could not be read: {loaded.message}</p>
        <p><button className="button button-quiet" type="button" onClick={retry}>Read it again</button></p>
      </>
    );
  } else {
    body = <Body view={loaded.data} variant={variant} analysisSentAt={analysisSentAt} />;
  }
  const state = loaded.state === "ready" ? loaded.data.state : loaded.state;
  return (
    <section id={id} className="card event-context-section overview-section rate-path" data-state={state}
             aria-labelledby={`${id}-title`}>
      <div className="rate-path-head">
        <h2 id={`${id}-title`}>Market-implied rate path</h2>
        <p className="rate-path-tag">Separate record · Atlanta Fed Market Probability Tracker</p>
      </div>
      <p className="rate-path-meaning">Estimated distributions of average SOFR over three-month windows, from CME
        3-month SOFR options, on the last observation date before this statement. Window dates are not meeting dates,
        and average SOFR is not the target rate on any date.</p>
      {body}
    </section>
  );
}

function Body({ view, variant, analysisSentAt }: { view: RatePathView; variant: Variant; analysisSentAt: string | null }) {
  const published = view.publication.new_york_date;
  if (view.state === "unsupported") {
    return <p className="overview-gap" data-gap="unsupported">Prepared only for Federal Reserve monetary-policy press
      releases; this saved event is not one, so no rate path is attached to it.</p>;
  }
  const meeting = (
    <div className="rate-path-meeting" data-meeting={view.meeting_specific.state}>
      <p className="rate-path-meeting-label">Meeting-specific pricing · Unavailable</p>
      <p>For the decision announced on {formatDay(published)}: {view.meeting_specific.statement}</p>
    </div>
  );
  if (view.state === "not_prepared") {
    return (
      <>
        <p className="overview-gap" data-gap="not_prepared">No rate-path context has been prepared for this saved event.
          It is prepared only by an explicit local command, never by opening a page:</p>
        <pre className="rate-path-command"><code>{prepareCommand(view.capture_id)}</code></pre>
        {meeting}
      </>
    );
  }
  if (view.state === "unreadable") {
    return (
      <>
        <p className="event-context-error" role="alert" data-gap="unreadable">This saved rate-path context does not
          verify, so none of it is shown: {view.problem} Nothing was changed.</p>
        {meeting}
      </>
    );
  }
  const selection = view.selection!;
  const provenance = view.provenance!;
  return (
    <>
      {view.state === "no_coverage" ? (
        <p className="overview-gap" data-gap="no_coverage">No observation is used. {selection.reason === "none_before"
          ? `The workbook's observations start on ${formatDay(selection.first_observation)}; none is dated before the ` +
            `statement's New York publication date, ${formatDay(published)}.`
          : `The workbook's observations end on ${formatDay(selection.last_observation)}, before the statement's New ` +
            `York publication date, ${formatDay(published)}, so its last observation cannot be shown to be the last ` +
            "one before the statement."}</p>
      ) : <Windows view={view} />}
      {meeting}
      <p className="rate-path-separate" data-variant={variant}>{variant === "research" && "Not part of this analysis. "}
        {view.separate}{" "}{timing(provenance.prepared_at, variant === "research" ? analysisSentAt : null)}</p>
      <h3>What this does not show</h3>
      <ul className="rate-path-limits">{view.limits.map((limit) => <li key={limit}>{limit}</li>)}</ul>
      <Provenance view={view} />
    </>
  );
}

function timing(preparedAt: string, sentAt: string | null): string {
  if (!sentAt) return `This context was prepared on ${formatUtc(preparedAt)}.`;
  return `This analysis was sent on ${formatUtc(sentAt)}; this context was prepared on ${formatUtc(preparedAt)}` +
    `${Date.parse(preparedAt) > Date.parse(sentAt) ? ", after it" : ""}.`;
}

function Windows({ view }: { view: RatePathView }) {
  const selection = view.selection!;
  const target = view.target_range!;
  const observed = selection.observation_date!;
  const place = strip(view.windows);
  const days = selection.calendar_days_before!;
  return (
    <>
      <dl className="ledger rate-path-facts">
        <div><dt>Observation date</dt><dd data-observation={observed}>{formatDay(observed)}</dd></div>
        <div><dt>Statement published</dt><dd>{formatDay(view.publication.new_york_date)},{" "}
          {view.publication.new_york_time} New York, as supplied</dd></div>
        <div><dt>Days before</dt><dd>{days} calendar {days === 1 ? "day" : "days"}</dd></div>
        <div><dt>Target range that day</dt><dd>{target.percent[0]}%–{target.percent[1]}% ({target.bps[0]}–
          {target.bps[1]} bp), as the workbook reports it</dd></div>
      </dl>
      {selection.same_day_observation && (
        <p className="rate-path-note">The workbook also holds an observation dated {formatDay(selection
          .publication_new_york_date)}, the publication date itself. It is not used: its date has no time of day, so it
          may reflect prices after the release.</p>
      )}
      <table className="context-table rate-path-table">
        <caption>The first {view.windows.length} three-month SOFR reference windows the workbook lists for{" "}
          {formatDay(observed)}{view.windows_listed! > view.windows.length ? ` (of ${view.windows_listed})` : ""}, by
          start date, as the workbook labels them.</caption>
        <thead>
          <tr><th scope="col">Window starting</th><th scope="col">Mean average SOFR</th>
            <th scope="col">25th–75th percentile</th>
            <th scope="col" className="rate-path-strip-cell"><span className="visually-hidden">The 25th to 75th
              percentile range and the mean, on one scale for these windows</span></th></tr>
        </thead>
        <tbody>
          {view.windows.map((window) => <WindowRow key={window.reference_start} window={window} place={place} />)}
        </tbody>
      </table>
    </>
  );
}

const MISSING = <span className="rate-path-missing">Not listed in the workbook</span>;

function value(item: Statistic | null): ReactNode {
  return item ? <><span className="rate-path-value">{item.percent}%</span><span className="rate-path-bp">{item.bp} bp</span></>
    : MISSING;
}

function WindowRow({ window, place }: { window: RateWindow; place: ReturnType<typeof strip> }) {
  const { mean, p25, p75 } = window.statistics;
  const bar = place(window);
  return (
    <tr data-window={window.reference_start}>
      <th scope="row">{formatDay(window.reference_start)}</th>
      <td data-statistic="mean">{value(mean)}</td>
      <td data-statistic="range">{p25 && p75 ? (
        <><span className="rate-path-value">{p25.percent}%–{p75.percent}%</span>
          <span className="rate-path-bp">{p25.bp}–{p75.bp} bp</span></>
      ) : <>{value(p25)}{value(p75)}</>}</td>
      <td className="rate-path-strip-cell" aria-hidden="true">
        {bar && (
          <span className="rate-path-strip">
            <span className="rate-path-iqr" style={{ left: `${bar.low}%`, width: `${Math.max(bar.high - bar.low, 0.5)}%` }} />
            {bar.mean !== null && <span className="rate-path-mean" style={{ left: `${bar.mean}%` } as CSSProperties} />}
          </span>
        )}
      </td>
    </tr>
  );
}

function originLine(origin: RatePathView["origin"]): string {
  if (!origin || origin.state === "none") return "the capture records no Inbox origin";
  return `the Inbox entry ${origin.item_id}, version ${origin.version ?? "?"} of ${origin.versions} (content SHA-256 ` +
    `${shortHash(origin.content_sha256, 12)}), through origin record ${shortHash(origin.link_sha256, 12)}`;
}

function Provenance({ view }: { view: RatePathView }) {
  const record = view.provenance!;
  const fields = view.definitions!.fields;
  const shown = ["reference_start", "target_range", "Rate: mean", "Rate: 25th percentile", "Rate: 75th percentile"];
  const withheld = Object.keys(fields).filter((name) => !shown.includes(name));
  return (
    <details className="rate-path-provenance">
      <summary>Source, definitions and provenance</summary>
      <dl className="ledger context-provenance rate-path-ledger">
        <div><dt>Source</dt><dd>{view.source.attribution}.{" "}
          <a href={view.source.page_url} target="_blank" rel="noreferrer">Tracker page</a> ·{" "}
          <a href={view.source.file_url} target="_blank" rel="noreferrer">workbook address</a>; neither is contacted by
          this app.</dd></div>
        <div><dt>Terms, from the workbook</dt><dd>“{view.license!.statement}”</dd></div>
        <div><dt>Workbook</dt><dd>{view.source.file}: obtained {formatDay(record.obtained_on)} ({record.method});
          retained {formatUtc(record.retained_at)}; {record.bytes.toLocaleString("en-US")} bytes, SHA-256{" "}
          <code>{shortHash(record.sha256, 16)}</code>; {record.workbook_rows.toLocaleString("en-US")} rows, observations{" "}
          {formatDay(record.first_observation)} to {formatDay(record.last_observation)}.</dd></div>
        <div><dt>Not recorded</dt><dd>{record.unknown}</dd></div>
        <div><dt>This record</dt><dd>Version {record.record_version} of {view.versions.length}, prepared{" "}
          {formatUtc(record.prepared_at)}; parser {record.parser_version}; validation record SHA-256{" "}
          <code>{shortHash(record.validation_sha256, 16)}</code>. Bound to capture <code>{view.capture_id}</code> and{" "}
          {originLine(view.origin)}.</dd></div>
      </dl>
      <h3>The workbook's own definitions</h3>
      <p className="rate-path-note">“{view.definitions!.description}”</p>
      <dl className="rate-path-definitions">
        {shown.map((name) => <div key={name}><dt>{name}</dt><dd>“{fields[name]}”</dd></div>)}
      </dl>
      {withheld.length > 0 && (
        <>
          <p className="rate-path-note">Defined in the workbook and not shown here: they describe average SOFR over a
            window against the target range, not a meeting decision.</p>
          <dl className="rate-path-definitions">
            {withheld.map((name) => <div key={name}><dt>{name}</dt><dd>“{fields[name]}”</dd></div>)}
          </dl>
        </>
      )}
      <h3>Measure and selection</h3>
      <p className="rate-path-note">{view.measure.statement}</p>
      <p className="rate-path-note">{view.rule.statement}</p>
      {view.windows.length > 0 && (
        <p className="rate-path-note rate-path-rows">Rows of the workbook's DATA sheet (mean, 25th, 75th):{" "}
          {view.windows.map((window) => `${window.reference_start}: ${["mean", "p25", "p75"].map((key) =>
            window.statistics[key as keyof RateWindow["statistics"]]?.row ?? "none").join(", ")}`).join("; ")}.</p>
      )}
      <details className="rate-path-license">
        <summary>The workbook's full license text ({view.license!.paragraphs.length} paragraphs)</summary>
        {view.license!.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
      </details>
    </details>
  );
}
