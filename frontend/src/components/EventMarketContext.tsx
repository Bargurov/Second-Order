import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { Loaded } from "../api";
import {
  approveRetrieval, attemptLine, changeRows, confirmContextDate, fetchPlan, planSentences, resultMessage,
  timeNote, type Attempt, type EventPage, type EventView, type Plan, type Provenance,
} from "../eventContext";
import { STATUS_LABEL, contextRows, formatContextDate } from "../marketContext";
import { ContextChart, ContextTable } from "./ContextChart";

const External = ({ href, children }: { href: string; children: ReactNode }) => (
  <a className="library-external" href={href} target="_blank" rel="noreferrer">{children}</a>
);

type Message = { text: string; tone: "done" | "error" } | null;

/** The event, its context date (confirmed or supplied) and, for an Inbox entry, the confirmation form. */
export function DateSection({ page, onSaved }: { page: EventPage; onSaved: (message: string) => void }) {
  const { event } = page;
  return (
    <section className="card event-context-section" aria-labelledby="context-date-title">
      <h2 id="context-date-title">Context date</h2>
      <p className="event-context-time">{timeNote(event)}</p>
      {!event.supported && <p className="event-context-outside" role="note">{event.outside}</p>}
      {event.problem && <p className="event-context-error" role="alert">{event.problem}. It was left unchanged.</p>}
      {event.supported && event.kind === "capture" && event.context && (
        <p className="event-context-date">
          Context date <strong data-context-date={event.context.date}>{formatContextDate(event.context.date)}</strong>:
          the New York calendar date of the supplied publication time. Nothing needs confirming; the time and offset
          stay as supplied.
        </p>
      )}
      {event.supported && event.kind === "inbox" && !event.problem && <ConfirmDate page={page} onSaved={onSaved} />}
      <p className="event-context-convention"><span>Convention {page.convention.id}.</span> {page.convention.statement}</p>
    </section>
  );
}

function ConfirmDate({ page, onSaved }: { page: EventPage; onSaved: (message: string) => void }) {
  const { event } = page;
  const current = event.context?.date ?? "";
  const [day, setDay] = useState(current || event.suggestion?.date || "");
  const [agreed, setAgreed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const inFlight = useRef(false);  // Two clicks in one instant both see the old state; this blocks the second.
  const version = event.confirmations.length + 1;
  const submit = async (submitted: FormEvent) => {
    submitted.preventDefault();
    if (inFlight.current || !agreed || !day || day === current) return;
    inFlight.current = true;
    setSaving(true);
    setMessage(null);
    const result = await confirmContextDate(event.id, day, version);
    inFlight.current = false;
    setSaving(false);
    if (result.state !== "done") {
      setMessage({ text: `The date was not saved: ${result.message}`, tone: "error" });
      return;
    }
    setAgreed(false);
    onSaved(result.value.saved_now ? `Context date ${formatContextDate(day)} saved as version ${result.value.version}.`
      : "That date was already saved; nothing was written.");
  };
  return (
    <>
      {event.suggestion ? (
        <p className="event-context-suggestion">
          Suggested: <strong>{formatContextDate(event.suggestion.date)}</strong> ({event.suggestion.new_york_time} New
          York time, UTC{event.suggestion.utc_offset}). {event.suggestion.basis}
        </p>
      ) : (
        <p className="event-context-suggestion">
          No date is suggested: {event.suggestion_problem} No time or offset is assumed; enter the date you verified
          against the release.
        </p>
      )}
      {event.confirmation_stale && (
        <p className="event-context-stale" role="note">
          Version {event.confirmation_stale.version} confirmed {formatContextDate(event.confirmation_stale.context_date)}
          for an earlier version of this entry (“{event.confirmation_stale.title}”). The entry has changed since, so that
          date does not carry over: confirm the date for the version held now.
        </p>
      )}
      {event.context && (
        <p className="event-context-date">
          Confirmed context date <strong data-context-date={event.context.date}>{formatContextDate(event.context.date)}
          </strong> (version {event.context.version}, saved {event.context.confirmed_at}).
          {event.confirmations.length > 1 && ` Earlier versions: ${event.confirmations.slice(0, -1).map((item) =>
            `${item.version}: ${formatContextDate(item.context_date)}`).join("; ")}; each stays saved.`}
        </p>
      )}
      <form className="event-context-form" onSubmit={submit}>
        <label className="event-context-field">
          <span>Context date (New York calendar date)</span>
          <input type="date" name="context-date" value={day} max={page.as_of} required
            onChange={(changed) => setDay(changed.target.value)} />
        </label>
        <label className="event-context-agree">
          <input type="checkbox" name="convention" checked={agreed} onChange={(changed) => setAgreed(changed.target.checked)} />
          I checked this date against the release, and it is the release's calendar date in New York
          ({page.convention.id}).
        </label>
        <button className="button" type="submit" disabled={saving || !agreed || !day || day === current}>
          {saving ? "Saving…" : event.context ? `Save as version ${version}` : "Confirm context date"}
        </button>
      </form>
      {message && <p className={`event-context-message is-${message.tone}`} role="alert">{message.text}</p>}
    </>
  );
}

/** Local data and the retrieval plan, with the one approval it may need. Previewing other events only reads. */
export function PlanSection({ page, message, onApproved }: {
  page: EventPage;
  message: Message;
  onApproved: (message: Message) => void;
}) {
  const own = page.plan!;
  const [extra, setExtra] = useState<string[]>([]);
  const [combined, setCombined] = useState<Loaded<Plan> | null>(null);
  const [sending, setSending] = useState(false);
  const inFlight = useRef(false);  // One approval at a time from this page, even for clicks in the same instant.
  useEffect(() => {
    if (extra.length === 0) {
      setCombined(null);
      return;
    }
    const controller = new AbortController();
    setCombined({ state: "loading" });
    fetchPlan([page.event.key, ...extra], controller.signal).then(setCombined, () => undefined);
    return () => controller.abort();
  }, [extra, page.event.key]);
  const plan = combined?.state === "ready" ? combined.data : extra.length ? null : own;
  const enabled = page.retrieval.enabled;
  const approve = async () => {
    if (!plan || inFlight.current || plan.requests !== 1 || !enabled) return;
    inFlight.current = true;
    setSending(true);
    const result = await approveRetrieval(plan);
    inFlight.current = false;
    setSending(false);
    setExtra([]);
    onApproved(result.state === "done" ? resultMessage(result.value)
      : { text: `${result.state === "refused" ? "Nothing was requested" : "The outcome is not confirmed"}: ${result.message}`,
          tone: "error" });
  };
  return (
    <section className="card event-context-section" aria-labelledby="context-plan-title">
      <h2 id="context-plan-title">Local data and retrieval</h2>
      <p className="card-note">
        Observations are kept apart from events and reused: the committed case-library downloads, earlier private
        retrievals and every validated release package are read before anything is planned, and opening, reloading or
        reopening this page never requests anything.
      </p>
      {page.others.length > 0 && (
        <fieldset className="event-context-others">
          <legend>Other saved events still missing data can share one request</legend>
          {page.others.map((other) => (
            <label key={other.key}>
              <input type="checkbox" checked={extra.includes(other.key)}
                onChange={(changed) => setExtra((keys) => changed.target.checked ? [...keys, other.key]
                  : keys.filter((key) => key !== other.key))} />
              {other.title ?? other.key} ({other.family_label}, {formatContextDate(other.context_date)}):{" "}
              {other.missing_sessions} sessions missing
            </label>
          ))}
        </fieldset>
      )}
      {combined?.state === "loading" && <p className="event-context-state" role="status">Previewing the combined plan…</p>}
      {combined && combined.state !== "loading" && combined.state !== "ready" && (
        <p className="event-context-error" role="alert">The combined plan could not be previewed: {combined.message}</p>
      )}
      {plan && <PlanDetails plan={plan} />}
      <div className="event-context-approve">
        <button className="button" type="button" onClick={approve}
          disabled={!plan || plan.requests !== 1 || !enabled || sending}>
          {sending ? "Downloading once…" : plan && plan.requests === 1
            ? `Approve 1 download of the Board's H.15 release package (attempt ${plan.next_attempt})` : "No request needed"}
        </button>
        <span>{page.retrieval.detail}</span>
      </div>
      {message && <p className={`event-context-message event-context-result is-${message.tone}`} role="alert">
        {message.text}</p>}
      <Attempts attempts={page.attempts} />
    </section>
  );
}

function PlanDetails({ plan }: { plan: Plan }) {
  const { source } = plan;
  return (
    <div className="event-context-plan" data-requests={plan.requests} data-plan={plan.plan_sha256}>
      <ul className="library-points">{planSentences(plan).map((sentence) => <li key={sentence}>{sentence}</li>)}</ul>
      <dl className="ledger event-context-source">
        <div><dt>Source</dt><dd>{source.label}</dd></div>
        <div><dt>Series</dt><dd>{source.series.map((series) => `${series.label} (${series.id})`).join("; ")}</dd></div>
        <div><dt>Download</dt><dd>{source.download}</dd></div>
        {plan.request && <div><dt>Address</dt><dd><code>{plan.request.url}</code></dd></div>}
        <div><dt>Key</dt><dd>{source.key}</dd></div>
        <div><dt>Charge</dt><dd>{source.charge}</dd></div>
        <div><dt>Terms</dt><dd>“{source.terms.statement}” (<External href={source.terms.url}>Board website
          disclaimer</External>)</dd></div>
        <div><dt>Restriction</dt><dd>{source.availability.statement} Checked {source.availability.checked_on}:{" "}
          {source.availability.urls.map((url, i) => <span key={url}>{i ? ", " : ""}<External href={url}>{url}</External></span>)}.
        </dd></div>
        <div><dt>Known behaviour</dt><dd>{source.known_behaviour}</dd></div>
        <div><dt>Plan SHA-256</dt><dd><code>{plan.plan_sha256}</code></dd></div>
      </dl>
    </div>
  );
}

function Attempts({ attempts }: { attempts: Attempt[] }) {
  if (attempts.length === 0) return <p className="event-context-attempts-none">No retrieval has been attempted for this event.</p>;
  return (
    <>
      <h3>Attempts for this event</h3>
      <ul className="library-points event-context-attempts">
        {attempts.map((attempt) => (
          <li key={`${attempt.plan_sha256}-${attempt.number}`} data-outcome={attempt.outcome?.outcome ?? "none"}>
            {attemptLine(attempt)}
            {attempt.started && <span className="event-context-transport"> Network: {attempt.started.client.transport}.</span>}
          </li>
        ))}
      </ul>
    </>
  );
}

/** The descriptive view: chart, changes in basis points, every date in words, and where each value came from. */
export function ViewSection({ view, title }: { view: EventView; title: string | null }) {
  const [allDates, setAllDates] = useState(true);  // A display setting: it filters what is held, and requests nothing.
  const rows = useMemo(() => contextRows(view), [view]);
  const shownRows = allDates ? rows : rows.filter((row) => view.days.find((day) => day.date === row.date)!.session);
  const day = formatContextDate(view.context.date);
  const changes = changeRows(view);
  // A retrieval records which network answered it; anything but the Board over the network is said up front.
  const simulated = [...new Set(view.retrievals.flatMap((item) =>
    item.client && !item.client.transport.startsWith("network:") ? [item.client.transport] : []))];
  return (
    <section className="card event-context-section event-context-view" aria-labelledby="context-view-title"
      data-complete={view.complete ? "true" : "false"}>
      <h2 id="context-view-title">Daily Treasury yields around {day}</h2>
      {simulated.length > 0 && (
        <p className="event-context-simulated" role="note">
          Some values below were not retrieved from the Board's server over the network. They were answered by:{" "}
          {simulated.join("; ")}.
        </p>
      )}
      <p>
        The Federal Reserve Board's daily H.15 2-year and 10-year Treasury constant-maturity yields, from{" "}
        {view.window.days_before} calendar days before to {view.window.days_after} after the context date
        {title ? ` of “${title}”` : ""}. Each value is a date-labelled daily yield as the Board published it when
        retrieved. {view.complete ? "Every expected session in the window is held locally."
          : "The window is partial: dates not held locally, and today or later, have no value."}
      </p>
      <h3>Descriptive changes</h3>
      <p className="event-context-rule">{view.endpoints.rule.statement}</p>
      <table className="context-table event-context-changes">
        <thead>
          <tr><th scope="col">Series</th><th scope="col">Horizon</th><th scope="col">From: session before</th>
            <th scope="col">To</th><th scope="col">Change</th></tr>
        </thead>
        <tbody>
          {changes.map((row) => (
            <tr key={row.key} data-change={row.key} data-available={row.available ? "true" : "false"}>
              <th scope="row">{row.series}</th>
              <td>{row.horizon}</td>
              <td>{row.from}</td>
              <td>{row.to}</td>
              <td>{row.available ? <strong>{row.change}</strong> : <span className="event-context-unavailable">
                Unavailable: {row.unavailable}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ContextChart view={view} marker="Context date" markerLegend={`Context date, ${day} (New York calendar date)`}
        desc={`Two lines in percent, with the context date, ${day}, marked. Every value is listed in the table below the chart.`}
        legendExtra={<li className="legend-note">Dates not held locally, and today or later, have no point and break
          the line; ≠ marks a date where retrieval versions disagree.</li>} />
      <label className="event-context-toggle">
        <input type="checkbox" checked={allDates} onChange={(changed) => setAllDates(changed.target.checked)} />
        Show weekends and holidays in the table
      </label>
      <ContextTable view={view} rows={shownRows} markerTag="Context date"
        caption={`Daily values, ${formatContextDate(view.window.start)} to ${formatContextDate(view.window.end)}, in percent per year`} />
      {view.conflicts.length > 0 && (
        <>
          <h3>Retrieval versions that disagree</h3>
          <ul className="library-points event-context-conflicts">
            {view.conflicts.map((conflict) => (
              <li key={`${conflict.date}-${conflict.series}`}>
                {formatContextDate(conflict.date)}, {conflict.series}: {conflict.versions.map((version) =>
                  `${version.raw ?? "no row"} in ${version.retrievals.join(", ")}`).join("; ")}. No value is chosen;
                every version stays saved.
              </li>
            ))}
          </ul>
        </>
      )}
      <Sources view={view} />
      <h3>What this shows and does not show</h3>
      <ul className="library-points">{view.limits.map((limit) => <li key={limit}>{limit}</li>)}</ul>
    </section>
  );
}

/** One retrieval's provenance: a two-series download's requested range, or a release package's coverage. */
function SourceLine({ item }: { item: Provenance }) {
  return (
    <li data-retrieval={item.id} data-origin={item.origin}>
      <strong>{item.origin_label}</strong>{item.case ? ` (${item.case}, run ${item.run})` : ""}:{" "}
      {item.origin === "package" ? <>
        the Board's full H.15 release package {item.package_id}, prepared {item.release_prepared ?? "at an unstated time"};
        it states {item.returned_first} to {item.returned_last} for both series; requested {item.requested_at}, HTTP{" "}
        {item.http_status} {item.content_type}; {item.bytes} bytes, SHA-256 <code>{item.sha256}</code>; read with parser{" "}
        {item.parser_version}, validated {item.validated_at}.
      </> : <>
        requested {item.requested_start} to {item.requested_end}, returned {item.returned_first} to {item.returned_last};
        requested {item.requested_at}, HTTP {item.http_status} {item.content_type}; {item.bytes} bytes, SHA-256{" "}
        <code>{item.sha256}</code>.
      </>}{item.client ? ` Network: ${item.client.transport}.` : ""}
    </li>
  );
}

function Sources({ view }: { view: EventView }) {
  return (
    <>
      <h3>Where each value came from</h3>
      {view.retrievals.length === 0 ? <p>No local retrieval covers this window yet.</p> : (
        <ul className="library-points event-context-retrievals">
          {view.retrievals.map((item) => <SourceLine key={item.id} item={item} />)}
        </ul>
      )}
      {view.store_problems.length > 0 && (
        <ul className="library-points event-context-problems" role="alert">
          {view.store_problems.map((problem) => (
            <li key={problem.retrieval}>{problem.problem}. It is not used, and it was left unchanged.</li>
          ))}
        </ul>
      )}
      <p className="event-context-source-note">
        <External href={view.source.release_url}>{view.source.publisher}, {view.source.release}</External>; source{" "}
        {view.source.underlying_source}. “{view.source.terms.statement}” (<External href={view.source.terms.url}>Board
        website disclaimer</External>). {view.source.vintage_note}{" "}
        Sessions: {view.calendar.calendar} via {view.calendar.library} {view.calendar.library_version}, calendar
        exceptions {view.calendar.exceptions_version}. Statuses: {Object.entries(view.status_counts).map(([status, count]) =>
          `${STATUS_LABEL[status] ?? status} ${count}`).join("; ")}.
      </p>
    </>
  );
}
