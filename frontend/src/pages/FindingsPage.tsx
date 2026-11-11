import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useLoad } from "../api";
import { formatUtc } from "../format";
import {
  EVENT_STATE, fetchListing, occasionHref, occasionStatus, runCheck,
  type CheckResult, type EventRow, type Listing,
} from "../insights";
import { CrossSourceComparisons } from "../components/CrossSourceComparisons";
import { ElectricityFindings } from "../components/ElectricityFindings";
import { G17Findings } from "../components/G17Findings";
import { Link } from "../router";
import "../insights.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

/** Findings from retained evidence, three separate evidence types: the Treasury findings pilot (its latest check, dated
 * occasions and explicit local check), the industry findings from retained G.17 releases, and electricity by sector
 * from retained EIA Table 7.6; then descriptive comparisons across the last two sources. Loading only reads. */
export function FindingsPage() {
  const [version, setVersion] = useState(0);
  const [loaded, retry] = useLoad(fetchListing, `findings:${version}`);
  const [last, setLast] = useState<Listing | null>(null);
  useEffect(() => {
    if (loaded.state === "ready") setLast(loaded.data);
  }, [loaded]);
  useEffect(() => {
    document.title = "Findings · Second Order";
  }, []);
  const listing = loaded.state === "ready" ? loaded.data : last;
  return (
    <article className="findings">
      <header className="findings-header reveal" style={order(0)}>
        <p className="kicker">Findings · retrospective, from retained evidence</p>
        <h1>Findings from retained evidence</h1>
        <p className="lede">Quantified context from official releases kept on this computer, in three separate
          evidence types: how Treasury yields moved around retained releases; which industries moved against their
          parent and how revisions changed the reported picture; and where electricity sales to households, businesses
          and industry moved apart. A last part sets the G.17 and EIA figures side by side for the same periods.
          Nothing to write first; each is checked explicitly.</p>
      </header>
      <section className="findings-part findings-treasury" aria-labelledby="treasury-title">
        <header className="findings-part-head reveal" style={order(1)}>
          <p className="kicker">Evidence type 1 · Treasury yields · retrospective single-market pilot</p>
          <h2 id="treasury-title">Treasury yields around retained releases (H.15)</h2>
          {listing && <p className="findings-scope">{listing.scope}</p>}
        </header>
        {!listing && loaded.state === "loading" && <p className="state-panel" role="status">Reading stored findings…</p>}
        {!listing && loaded.state !== "loading" && loaded.state !== "ready" && (
          <section className="card" role="alert"><p>{loaded.message}</p>
            <button type="button" className="button" onClick={retry}>Try again</button></section>
        )}
        {listing && (
          <>
            <CheckCard listing={listing} onChecked={() => setVersion((value) => value + 1)} />
            <Occasions listing={listing} />
            <NotMeasured listing={listing} />
            <Method listing={listing} />
          </>
        )}
      </section>
      <G17Findings start={6} />
      <ElectricityFindings start={12} />
      <CrossSourceComparisons start={18} />
    </article>
  );
}

function CheckCard({ listing, onChecked }: { listing: Listing; onChecked: () => void }) {
  const [outcome, setOutcome] = useState<CheckResult | null>(null);
  const [pending, setPending] = useState(false);
  const inflight = useRef(false);
  const check = listing.check;
  return (
    <section className="card findings-check reveal" style={order(1)} aria-labelledby="findings-check-title">
      <h3 id="findings-check-title">Evidence</h3>
      {check ? (
        <dl className="ledger findings-ledger">
          <div><dt>Source</dt><dd>Federal Reserve Board, H.15 Selected Interest Rates (release package)</dd></div>
          <div><dt>Package</dt><dd><code>{check.package.package_id}</code></dd></div>
          <div><dt>Received</dt><dd>{formatUtc(check.package.received_at)}</dd></div>
          <div><dt>Data through</dt><dd>{check.package.last_date ?? "—"}{check.package.cutoff
            ? ` (read only to ${check.package.cutoff})` : ""}</dd></div>
          <div><dt>Checked</dt><dd>{formatUtc(check.checked_at)}</dd></div>
        </dl>
      ) : <p className="findings-empty">No check has been run yet. Nothing is measured until you ask.</p>}
      <p className="findings-note">A check is explicit and local: it reads the newest accepted H.15 package kept on
        this computer and the retained events, contacts no provider and costs nothing. Unchanged inputs reuse earlier
        results; a newer package is used only by the next check.</p>
      <button type="button" className="button findings-run" disabled={pending} onClick={async () => {
        if (inflight.current) return;
        inflight.current = true;
        setPending(true);
        const result = await runCheck();
        inflight.current = false;
        setPending(false);
        setOutcome(result);
        if (result.state === "done") onChecked();
      }}>{pending ? "Checking…" : "Check retained evidence"}</button>
      {outcome && (
        <p className={`findings-outcome is-${outcome.state}`} role="status">{outcome.state === "done"
          ? (outcome.data.created ? `Checked ${outcome.data.occasions} occasions; ${outcome.data.results_created} new `
            + `result${outcome.data.results_created === 1 ? "" : "s"}, the rest reused.`
            : "Nothing changed since the last check with these inputs; nothing was written.")
          : outcome.message}</p>
      )}
    </section>
  );
}

function recordLine(event: EventRow, listing: Listing): string {
  const bases = [...new Set(event.records.map((record) => record.origin))].map((origin) => listing.origins[origin]);
  return bases.join(" · ");
}

function Occasions({ listing }: { listing: Listing }) {
  const events = new Map(listing.events.map((event) => [event.key, event]));
  return (
    <section className="card findings-occasions reveal" style={order(2)} aria-labelledby="findings-occasions-title">
      <h3 id="findings-occasions-title">Dated occasions</h3>
      <p className="findings-note">Each New York date is measured once; releases dated the same day share it, because
        daily data cannot tell them apart.</p>
      {listing.occasions.length === 0 ? <p className="findings-empty">No occasion has been checked.</p> : (
        <ol className="findings-list">
          {listing.occasions.map((row) => (
            <li key={row.date} data-date={row.date} data-state={row.state}>
              <Link to={occasionHref(row.date)} className="findings-date">{row.date}</Link>
              <span className={`findings-chip is-${row.state}${row.findings ? " has-findings" : ""}`}>
                {occasionStatus(row)}</span>
              <ul className="findings-events">
                {row.events.map((key) => events.get(key)).filter((event): event is EventRow => !!event).map((event) => (
                  <li key={event.key}>{event.title} <small>({event.family_label}; {recordLine(event, listing)})</small></li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function NotMeasured({ listing }: { listing: Listing }) {
  const unchecked = new Set(listing.unchecked);
  const rows = listing.events.filter((event) => event.state !== "dated" || unchecked.has(event.key));
  if (rows.length === 0) return null;
  const groups = new Map<string, EventRow[]>();
  for (const event of rows) {
    const label = unchecked.has(event.key) ? "Not checked yet" : EVENT_STATE[event.state];
    groups.set(label, [...(groups.get(label) ?? []), event]);
  }
  return (
    <section className="card findings-other reveal" style={order(3)} aria-labelledby="findings-other-title">
      <h3 id="findings-other-title">Not measured</h3>
      {[...groups].map(([label, events]) => (
        <details key={label} className="findings-group">
          <summary>{label} · {events.length}</summary>
          <ul>{events.map((event) => (
            <li key={event.key} data-event={event.key}>{event.title}{event.detail ? ` — ${event.detail}` : ""}
              {" "}<small>({recordLine(event, listing)})</small></li>
          ))}</ul>
        </details>
      ))}
    </section>
  );
}

function Method({ listing }: { listing: Listing }) {
  const comparison = listing.comparison;
  return (
    <section className="card findings-method reveal" style={order(4)} aria-labelledby="findings-method-title">
      <h3 id="findings-method-title">How these are measured</h3>
      <p>Changes run between grid dates in basis points: from the session before the event date to the first and the
        fifth session after it (these include the event date's own session, so they show everything that moved yields
        then, never an isolated response), and over the five sessions before it. Each change is ranked by absolute size
        against the 250 windows of the same span that end on or before it; ties count half. Missing values stay
        missing.</p>
      <ul className="findings-rules">{Object.entries(listing.definitions.rules).map(([rule, text]) => (
        <li key={rule}><strong>{rule}.</strong> {text}</li>
      ))}</ul>
      {comparison?.any && (
        <p className="findings-note">On {comparison.size} comparison sessions ({comparison.range[0]} to
          {" "}{comparison.range[1]}, recorded seed {comparison.seed}), at least one rule check was met on
          {" "}{comparison.any.met} of {comparison.any.evaluable}. These sessions are not news-free, and this is a
          description, not a probability.</p>
      )}
      <ul className="findings-limits">{listing.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
    </section>
  );
}
