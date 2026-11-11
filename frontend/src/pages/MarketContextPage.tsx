import { useEffect, useState, type CSSProperties } from "react";
import { useLoad } from "../api";
import { DateSection, PlanSection, ViewSection } from "../components/EventMarketContext";
import {
  eventHref, fetchContextListing, fetchEventPage, formatBp, listedStatus, attemptLine, packageStatus, HORIZON_LABEL,
  VALIDATE_COMMAND, type ContextListing, type EventKind, type ListedEvent,
} from "../eventContext";
import { overviewHref } from "../eventOverview";
import { formatContextDate } from "../marketContext";
import { Link } from "../router";
import "../library.css";
import "../eventContext.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

/**
 * Market context: saved events with daily Treasury yields around their context dates, to reopen without files or
 * commands. The page only reads the server's saved events and verified retrievals; nothing is requested by opening it.
 */
export function MarketContextListPage() {
  const [listing, retry] = useLoad(fetchContextListing, "market-context-list");
  useEffect(() => {
    document.title = "Market context · Second Order";
  }, []);
  return (
    <article className="event-context">
      <header className="event-context-header reveal" style={order(0)}>
        <p className="kicker">Market context</p>
        <h1>Daily Treasury yields around selected macro events</h1>
        <p className="lede">
          Private, local context for Federal Reserve monetary-policy and BLS employment and inflation releases: the
          Federal Reserve Board's daily 2-year and 10-year yields from 14 days before to 14 days after each event's New
          York calendar date, with descriptive changes in basis points. Start from a Federal Reserve or BLS entry in the
          Event Inbox on the <Link to="/">Tracker</Link>, or from a saved event below.
        </p>
        <p className="event-context-meaning">
          Descriptive observations only: not an intraday reaction, a causal attribution, a hypothesis confirmation, a
          trading signal or a research score. Nothing here enters the case library or research summaries.
        </p>
      </header>
      {listing.state === "ready" ? <Listing listing={listing.data} /> : (
        <section className="card reveal" style={order(1)}>
          {listing.state === "loading" ? <p className="event-context-state" role="status">Reading saved market context…</p> : (
            <div role="alert">
              <p className="event-context-error">Saved market context could not be read: {listing.message}</p>
              <button className="button" type="button" onClick={retry}>Try again</button>
            </div>
          )}
        </section>
      )}
    </article>
  );
}

function Listing({ listing }: { listing: ContextListing }) {
  return (
    <>
      <section className="card event-context-section reveal" style={order(1)} aria-labelledby="saved-events-title">
        <h2 id="saved-events-title">Saved events</h2>
        {listing.events.length === 0 ? (
          <p className="event-context-state">
            No event has market context yet. Choose Market context on a Federal Reserve or BLS entry in the Event Inbox,
            confirm its context date, and it is listed here. Saved Tracker events whose official link is a Federal
            Reserve monetary-policy or BLS employment or inflation release are listed automatically.
          </p>
        ) : (
          <ol className="event-context-list">{listing.events.map((event) => <Entry key={event.key} event={event} />)}</ol>
        )}
        {listing.outside.length > 0 && (
          <p className="event-context-outside">
            {listing.outside.length} saved {listing.outside.length === 1 ? "event is" : "events are"} outside this first
            slice and {listing.outside.length === 1 ? "is" : "are"} not paired with Treasury yields:{" "}
            {listing.outside.map((event) => event.title).join("; ")}. {listing.outside_note}
          </p>
        )}
      </section>
      <section className="card event-context-section reveal" style={order(2)} aria-labelledby="local-data-title">
        <h2 id="local-data-title">Local observations</h2>
        <p className="card-note">
          Reusable local data, kept apart from any event: the committed case-library downloads, earlier two-series
          retrievals, and release packages that a local validation accepted. {listing.retrieval.detail}
        </p>
        {listing.retrievals.length === 0 ? <p className="event-context-state">No retrieval is held locally.</p> : (
          <ul className="library-points event-context-retrievals">
            {listing.retrievals.map((item) => (
              <li key={item.id} data-retrieval={item.id} data-origin={item.origin}>
                <strong>{item.origin_label}</strong>{item.case ? ` (${item.case})` : ""}: {item.returned_first} to{" "}
                {item.returned_last}, requested {item.requested_at}.
              </li>
            ))}
          </ul>
        )}
        {listing.packages.length > 0 && (
          <>
            <h3>Kept release packages</h3>
            <ul className="library-points event-context-packages">
              {listing.packages.map((item) => (
                <li key={item.id} data-package={item.package_id} data-status={item.status}>
                  <strong>{item.package_id}</strong>: {packageStatus(item)}. Requested {item.requested_at}; {item.bytes}{" "}
                  bytes, SHA-256 <code>{item.sha256}</code>
                  {item.coverage ? `; states ${item.coverage.first} to ${item.coverage.last}` : ""}. Network:{" "}
                  {item.client.transport}.
                  {item.status === "acquired_unvalidated" && <> Validate it locally with <code>{VALIDATE_COMMAND}</code>;
                    it fetches nothing.</>}
                </li>
              ))}
            </ul>
          </>
        )}
        {listing.store_problems.length > 0 && (
          <ul className="library-points event-context-problems" role="alert">
            {listing.store_problems.map((problem) => <li key={problem.retrieval}>{problem.problem}. Not used; left unchanged.</li>)}
          </ul>
        )}
        {listing.attempts.length > 0 && (
          <>
            <h3>Retrieval attempts</h3>
            <ul className="library-points event-context-attempts">
              {listing.attempts.map((attempt) => (
                <li key={`${attempt.plan_sha256}-${attempt.number}`} data-outcome={attempt.outcome?.outcome ?? "none"}>
                  {attemptLine(attempt)}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </>
  );
}

function Entry({ event }: { event: ListedEvent }) {
  const shown = event.changes?.filter((change) => change.change_bp !== null) ?? [];
  return (
    <li className="event-context-entry" data-key={event.key} data-complete={event.complete ? "true" : "false"}>
      <p className="event-context-entry-meta">
        <span>{event.family_label ?? "Unreadable"}</span>
        <span>{event.kind === "capture" ? "Saved event" : "Event Inbox"}</span>
        {event.context && <span>Context date {formatContextDate(event.context.date)}</span>}
      </p>
      {event.id ? (
        <Link className="event-context-entry-title" to={eventHref(event.kind, event.id)}>{event.title ?? event.key}</Link>
      ) : <span className="event-context-entry-title">{event.key}</span>}
      <p className="event-context-entry-status">{listedStatus(event)}</p>
      {event.id && <p className="event-context-entry-overview"><Link to={overviewHref(event.kind, event.id)}>Event overview</Link></p>}
      {shown.length > 0 && (
        <p className="event-context-entry-changes">
          {shown.map((change) => `${change.short_label}, ${HORIZON_LABEL[change.horizon]}: ${formatBp(change.change_bp)}`)
            .join(" · ")}
        </p>
      )}
    </li>
  );
}

/** One event's market context. A save or an approval reads the page again; nothing else changes what is shown. */
export function EventContextPage({ kind, id }: { kind: EventKind; id: string }) {
  const [page, reload] = useLoad((signal) => fetchEventPage(kind, id, signal), `event-context:${kind}:${id}`);
  const [message, setMessage] = useState<{ text: string; tone: "done" | "error" } | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  useEffect(() => {
    document.title = "Market context · Second Order";
  }, []);
  const ready = page.state === "ready" ? page.data : null;
  return (
    <article className="event-context">
      <header className="event-context-header reveal" style={order(0)}>
        <p className="kicker"><Link to="/market-context">Market context</Link></p>
        <h1>{ready?.event.title ?? "Market context"}</h1>
        {ready && (
          <p className="event-context-entry-meta">
            {ready.event.family_label && <span>{ready.event.family_label}</span>}
            {ready.event.publisher && <span>{ready.event.publisher}</span>}
            <span>{ready.event.kind === "capture" ? "Saved event" : "Event Inbox entry"}</span>
            {ready.event.link && <a href={ready.event.link} target="_blank" rel="noreferrer">Official release</a>}
            <Link to={overviewHref(kind, id)}>Event overview</Link>
          </p>
        )}
      </header>
      {page.state === "loading" && <p className="event-context-state" role="status">Reading this event's market context…</p>}
      {page.state !== "loading" && page.state !== "ready" && (
        <section className="card" role="alert">
          <p className="event-context-error">This event's market context could not be read: {page.message}</p>
          <p><Link to="/market-context">All saved market context</Link></p>
        </section>
      )}
      {ready && (
        <>
          {saved && <p className="event-context-message is-done" role="status">{saved}</p>}
          <DateSection page={ready} onSaved={(text) => { setSaved(text); setMessage(null); reload(); }} />
          {ready.plan && <PlanSection page={ready} message={message}
            onApproved={(result) => { setMessage(result); setSaved(null); reload(); }} />}
          {ready.view && <ViewSection view={ready.view} title={ready.event.title} />}
        </>
      )}
    </article>
  );
}
