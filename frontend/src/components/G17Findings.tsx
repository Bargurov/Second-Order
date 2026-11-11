import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useLoad } from "../api";
import { formatUtc } from "../format";
import {
  G17_HREF, MARKER, RELATION, REVISION_KIND, fetchG17, points, rate, rowName, runG17Check,
  type DivergenceCard, type G17CheckOutcome, type G17CheckResult, type G17Listing, type Observed, type RevisionCard,
} from "../g17";
import { Link } from "../router";
import { BreadthSummary } from "./G17Breadth";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

/** Industry findings from retained G.17 releases, a separate evidence type on the Findings page. Loading only reads;
 * the one explicit check compares the retained releases locally. */
export function G17Findings({ start }: { start: number }) {
  const [version, setVersion] = useState(0);
  const [loaded, retry] = useLoad(fetchG17, `g17:${version}`);
  const [last, setLast] = useState<G17Listing | null>(null);
  useEffect(() => {
    if (loaded.state === "ready") setLast(loaded.data);
  }, [loaded]);
  const listing = loaded.state === "ready" ? loaded.data : last;
  return (
    <section className="findings-part findings-g17" aria-labelledby="g17-title">
      <header className="findings-part-head reveal" style={order(start)}>
        <p className="kicker">Evidence type 2 · industrial production</p>
        <h2 id="g17-title">Industries and revisions (Federal Reserve G.17)</h2>
        {listing && <p className="findings-scope g17-scope">{listing.scope}</p>}
      </header>
      {!listing && loaded.state === "loading" && <p className="state-panel" role="status">Reading G.17 findings…</p>}
      {!listing && loaded.state !== "loading" && loaded.state !== "ready" && (
        <section className="card" role="alert"><p>{loaded.message}</p>
          <button type="button" className="button" onClick={retry}>Try again</button></section>
      )}
      {listing && (
        <>
          <G17Check listing={listing} start={start + 1} onChecked={() => setVersion((value) => value + 1)} />
          {listing.state === "problem" && (
            <section className="card g17-problem" role="alert"><h3>Not shown</h3><p>{listing.detail}</p></section>
          )}
          {listing.state === "checked" && listing.divergence && listing.revisions && (
            <>
              {listing.breadth && <BreadthSummary breadth={listing.breadth} start={start + 2} />}
              <DivergenceCards listing={listing} start={start + 3} />
              <RevisionCards listing={listing} start={start + 4} />
              <G17Method listing={listing} start={start + 5} />
            </>
          )}
        </>
      )}
    </section>
  );
}

function G17Check({ listing, start, onChecked }: { listing: G17Listing; start: number; onChecked: () => void }) {
  const [outcome, setOutcome] = useState<G17CheckResult | null>(null);
  const [pending, setPending] = useState(false);
  const inflight = useRef(false);
  return (
    <section className="card g17-check reveal" style={order(start)} aria-labelledby="g17-check-title">
      <h3 id="g17-check-title">Retained releases</h3>
      {listing.releases.length > 0 ? (
        <table className="findings-table g17-releases">
          <thead><tr><th scope="col">Release</th><th scope="col">Months</th><th scope="col">Sources (SHA-256)</th>
            <th scope="col">Library case</th></tr></thead>
          <tbody>{listing.releases.map((row) => (
            <tr key={row.release} data-release={row.release}>
              <th scope="row"><a href={row.url} rel="noreferrer">{row.release_date_as_stated}</a>
                <small>release date as published; no time zone stated</small></th>
              <td>{row.months[0]?.label} – {row.months.at(-1)?.label} ({row.months.at(-1)?.marker === "p"
                ? "last preliminary" : "revised"})</td>
              <td>{row.sources.map((source) => (
                <span key={source.file} className="g17-source">{source.role}: <code>{source.sha256.slice(0, 12)}</code>
                  {source.retrieved_at && <small> retrieved {formatUtc(source.retrieved_at)}</small>}</span>
              ))}</td>
              <td>{row.library ? <Link to={row.library.href}>{row.library.title}</Link> : "—"}</td>
            </tr>
          ))}</tbody>
        </table>
      ) : (
        <p className="findings-empty">{listing.state === "not_checked"
          ? `No G.17 check has been run yet. ${listing.available.length} retained release${listing.available.length === 1
            ? " is" : "s are"} available; nothing is compared until you ask.` : "No release is shown."}</p>
      )}
      <p className="findings-note">The check reads only the G.17 pages kept on this computer by the approved
        acquisitions, verifies their recorded hashes, table structure, units and seasonal adjustment, and compares
        them. It contacts no provider and costs nothing; unchanged inputs reuse earlier results.</p>
      <button type="button" className="button g17-run" disabled={pending} onClick={async () => {
        if (inflight.current) return;
        inflight.current = true;
        setPending(true);
        const result = await runG17Check();
        inflight.current = false;
        setPending(false);
        setOutcome(result);
        if (result.state === "done") onChecked();
      }}>{pending ? "Checking…" : "Check retained G.17 releases"}</button>
      {outcome && (
        <p className={`findings-outcome g17-outcome is-${outcome.state}`} role="status">{outcome.state === "done"
          ? checkedText(outcome.data) : outcome.message}</p>
      )}
    </section>
  );
}

/** What a check created and what it reused, for the industry comparisons and for breadth separately. */
function checkedText(data: G17CheckOutcome): string {
  const breadth = data.breadth;
  const created = data.created || data.extracts_created || data.release_results_created
    || data.revision_results_created || (breadth && (breadth.release_results_created || breadth.revision_results_created));
  if (!created) return "Nothing changed since the last check with these inputs; nothing was written.";
  const plural = (n: number, word: string) => `${n} new ${word}${n === 1 ? "" : "s"}`;
  return `Checked ${data.releases.length} releases. Industry comparisons: ${plural(data.release_results_created,
    "release result")} and ${plural(data.revision_results_created, "revision comparison")}. Breadth: `
    + (breadth ? `${plural(breadth.release_results_created, "release result")} and `
      + `${plural(breadth.revision_results_created, "revision comparison")}` : "not computed")
    + ". Everything else was reused.";
}

function Source({ item }: { item: Observed }) {
  return (
    <tr>
      <th scope="row">{rowName(item.path, item.naics)}<small>{item.path}</small></th>
      <td className="findings-num">{rate(item.rate)}</td>
      <td>{item.column}<small>{item.release_date_as_stated} release ({MARKER[item.marker]})</small></td>
      <td><a href={item.url} rel="noreferrer">{item.table}</a> <code>{item.sha256.slice(0, 12)}</code></td>
    </tr>
  );
}

function Divergence({ card }: { card: DivergenceCard }) {
  return (
    <article className="card g17-card" data-card={card.id}>
      <p className="kicker">Against the {card.kind === "group_vs_total" ? "total" : "parent"} · {card.month_label}</p>
      <h3>{card.title}</h3>
      <h4>Observed</h4>
      <table className="findings-table g17-observed">
        <thead><tr><th scope="col">Row</th><th scope="col" className="findings-num">Published rate</th>
          <th scope="col">Column</th><th scope="col">Source</th></tr></thead>
        <tbody>{card.observed.map((item) => <Source key={item.path} item={item} />)}</tbody>
      </table>
      <p className="findings-note">Difference: {points(card.gap_pp)} (row minus {card.kind === "group_vs_total"
        ? "total" : "parent"}).</p>
      <h4>What this adds</h4>
      <p>{card.adds}</p>
      <h4>Interpretation <small>(not observed)</small></h4>
      <p className="finding-inference">{card.interpretation}</p>
      {card.estimates.length > 1 && (
        <>
          <h4>Estimates of {card.month_label}</h4>
          <ul className="g17-estimates">{card.estimates.map((item) => (
            <li key={item.release}>{item.release_date_as_stated} ({MARKER[item.marker]}): {rate(item.row_rate)} against
              {" "}{rate(item.parent_rate)} — {RELATION[item.relation]}</li>
          ))}</ul>
        </>
      )}
      {card.limitations.length > 0 && (
        <><h4>Limitations</h4><ul className="g17-limits">{card.limitations.map((item) => <li key={item}>{item}</li>)}
        </ul></>
      )}
    </article>
  );
}

function DivergenceCards({ listing, start }: { listing: G17Listing; start: number }) {
  const divergence = listing.divergence!;
  return (
    <section className="card g17-divergence reveal" style={order(start)} aria-labelledby="g17-divergence-title">
      <h3 id="g17-divergence-title">Moved against the parent or the total</h3>
      <p className="g17-totals" data-total={divergence.total}>
        {divergence.total === 0 ? "No comparison in the latest estimates has opposing printed directions."
          : `Showing ${divergence.shown.length} of ${divergence.total} opposing comparisons`} among
        {" "}{divergence.comparisons} latest estimates (same direction {divergence.counts.same ?? 0}; no direction
        {" "}{divergence.counts.no_direction ?? 0}; not printed {divergence.counts.unavailable ?? 0}).</p>
      <p className="findings-note">{divergence.order}</p>
      <div className="g17-cards">{divergence.shown.map((card) => <Divergence key={card.id} card={card} />)}</div>
      {divergence.no_direction_parents.length > 0 && (
        <div className="g17-quiet">
          <h4>No directional comparison</h4>
          <ul>{divergence.no_direction_parents.map((item) => (
            <li key={`${item.parent}|${item.month}`} data-parent={item.parent}>{item.parent_label} printed
              {" "}{rate(item.parent_rate)} for {item.month_label} ({item.release_date_as_stated} release), so its
              {" "}{item.comparisons} comparison{item.comparisons === 1 ? " has" : "s have"} no direction to compare.</li>
          ))}</ul>
        </div>
      )}
    </section>
  );
}

function Revision({ card }: { card: RevisionCard }) {
  return (
    <article className="card g17-card" data-card={card.id}>
      <p className="kicker">Revision · {card.month_label}</p>
      <h3>{card.title}</h3>
      <h4>Published estimates of {card.month_label}</h4>
      <table className="findings-table g17-chain">
        <thead><tr><th scope="col">Release</th><th scope="col" className="findings-num">Published rate</th>
          <th scope="col">Column</th><th scope="col">Source</th></tr></thead>
        <tbody>{card.chain.map((item) => (
          <tr key={item.release} className={item.release === card.from.release || item.release === card.to.release
            ? "is-compared" : undefined}>
            <th scope="row">{item.release_date_as_stated}</th>
            <td className="findings-num">{rate(item.rate)} <small>{MARKER[item.marker]}</small></td>
            <td>{item.column}<small>{card.row}</small></td>
            <td><a href={item.url} rel="noreferrer">Table 1</a></td>
          </tr>
        ))}</tbody>
      </table>
      <p className="findings-note">Revision from the {card.from.release_date_as_stated} to the
        {" "}{card.to.release_date_as_stated} release: {points(card.revision_pp)}.</p>
      <h4>What this adds</h4>
      <p>{card.adds}</p>
      <h4>Interpretation <small>(not observed)</small></h4>
      <p className="finding-inference">{card.interpretation}</p>
      {card.limitations.length > 0 && (
        <><h4>Limitations</h4><ul className="g17-limits">{card.limitations.map((item) => <li key={item}>{item}</li>)}
        </ul></>
      )}
    </article>
  );
}

function RevisionCards({ listing, start }: { listing: G17Listing; start: number }) {
  const revisions = listing.revisions!;
  const counts = revisions.counts;
  return (
    <section className="card g17-revisions reveal" style={order(start)} aria-labelledby="g17-revisions-title">
      <h3 id="g17-revisions-title">Revisions that changed the reported direction</h3>
      <p className="g17-totals" data-total={revisions.total}>
        {revisions.total === 0 ? "No revision between consecutive releases reversed a printed direction."
          : `Showing ${revisions.shown.length} of ${revisions.total} strict reversals.`} Apart from reversals:
        {" "}{counts.to_printed_zero ?? 0} to a printed 0.0 and {counts.from_printed_zero ?? 0} from one (listed below),
        {" "}{counts.same_direction ?? 0} revised in the same direction, {counts.unchanged ?? 0} unchanged.</p>
      <p className="findings-note">{revisions.order}</p>
      <div className="g17-cards">{revisions.shown.map((card) => <Revision key={card.id} card={card} />)}</div>
      {revisions.printed_zero_transitions.length > 0 && (
        <details className="findings-group g17-zero">
          <summary>Changes to or from a printed 0.0 · {revisions.printed_zero_transitions.length}</summary>
          <ul>{revisions.printed_zero_transitions.map((item) => (
            <li key={`${item.row}|${item.month}|${item.earlier.release}`}>{rowName(item.row, null)}, {item.month_label}:
              {" "}{rate(item.earlier.rate)} ({item.earlier.release_date_as_stated}) to {rate(item.later.rate)}
              {" "}({item.later.release_date_as_stated}) — {REVISION_KIND[item.kind]}</li>
          ))}</ul>
        </details>
      )}
      <p><Link to={G17_HREF} className="g17-all">All comparisons and revision chains</Link></p>
    </section>
  );
}

function G17Method({ listing, start }: { listing: G17Listing; start: number }) {
  return (
    <section className="card g17-method reveal" style={order(start)} aria-labelledby="g17-method-title">
      <h3 id="g17-method-title">How these are compared</h3>
      <p>Rows are Table 1 rows identified by their full path (section and parent rows) and NAICS code where printed;
        broad Manufacturing and Manufacturing (NAICS) are different rows. Values are the published seasonally adjusted
        monthly rates, compared with exact decimals for the same reference month. Industry groups are compared with
        Total IP and NAICS subsectors with their durable or nondurable parent within one release; revisions compare the
        same row and month in consecutive releases.</p>
      {listing.table1 && <p className="findings-note">Table 1 notes, as published: {listing.table1.proportion_note}
        {" "}(Proportions are shown by the Board; nothing here uses them.)</p>}
      <ul className="findings-limits">{listing.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
    </section>
  );
}
