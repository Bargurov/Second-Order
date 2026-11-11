import { useEffect, type CSSProperties, type ReactNode } from "react";
import { useLoad } from "../api";
import { Skeleton } from "../components/Chrome";
import { LibraryLabels } from "../components/CaseLibrary";
import { formatUtc } from "../format";
import {
  DIMENSIONS, SOURCE_CHECK_LABEL, dayLabel, factIndex, fetchRelatedCase, relatedCaseHref, type Fact,
  type RelatedCaseView,
} from "../relatedCases";
import { Link } from "../router";
import "../library.css";
import "../related.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

const SECTIONS = [
  ["account", "What the release states"],
  ["dates", "Dates, as the release states them"],
  ["scope", "Scope, exceptions and timing"],
  ["actors", "Actors, instruments and tags"],
  ["interpretation", "Interpretation"],
  ["unknowns", "What remains unknown"],
  ["provenance", "Source and review status"],
] as const;
type SectionId = (typeof SECTIONS)[number][0];

function Section({ id, children, note }: { id: SectionId; children: ReactNode; note?: string }) {
  const index = SECTIONS.findIndex(([key]) => key === id);
  return (
    <section id={id} className="library-section-block" aria-labelledby={`${id}-title`}>
      <p className="kicker">{String(index + 1).padStart(2, "0")}</p>
      <h2 id={`${id}-title`}>{SECTIONS[index][1]}</h2>
      {note && <p className="library-section-note">{note}</p>}
      {children}
    </section>
  );
}

const External = ({ href, children }: { href: string; children: ReactNode }) => (
  <a className="library-external" href={href} target="_blank" rel="noreferrer">{children}</a>
);

/** The facts an item cites, as links to their numbered entries under "What the release states". */
function Cites({ ids, facts }: { ids: string[]; facts: Map<string, { fact: Fact; number: number }> }) {
  return (
    <span className="related-cites">
      {ids.length === 1 ? "Fact " : "Facts "}
      {ids.map((id, index) => (
        <span key={id}>{index > 0 && ", "}<a href={`#fact-${id}`}>{facts.get(id)?.number ?? "?"}</a></span>
      ))}
    </span>
  );
}

export function HistoricalCasePage({ id }: { id: string }) {
  const [loaded, retry] = useLoad((signal) => fetchRelatedCase(id, signal), `related-case:${id}`);
  useEffect(() => {
    document.title = loaded.state === "ready"
      ? `${loaded.data.case.title} · Historical case · Second Order` : "Historical case · Second Order";
  }, [loaded]);
  if (loaded.state === "loading") return <Skeleton />;
  if (loaded.state === "missing") {
    return (
      <section className="state-panel" aria-labelledby="missing-case-title">
        <p className="kicker">404 · Not found</p>
        <h1 id="missing-case-title">There is no historical case at this address</h1>
        <p>The collection has no case called <code>{id}</code>.</p>
        <p><Link to="/library#historical-cases">Back to the historical cases</Link></p>
      </section>
    );
  }
  if (loaded.state !== "ready") {
    return (
      <section className="state-panel" role="alert">
        <p>This historical case could not be read: {loaded.message}</p>
        <button type="button" className="button" onClick={retry}>Try again</button>
      </section>
    );
  }
  return <CaseView view={loaded.data} />;
}

function CaseView({ view }: { view: RelatedCaseView }) {
  const item = view.case;
  const source = item.source;
  const numbered = new Map([...factIndex(item)].map(([key, fact], index) => [key, { fact, number: index + 1 }]));
  const check = view.source_check;
  return (
    <article className="library-case historical-case" data-case={item.id}>
      <nav className="library-crumbs" aria-label="Case library">
        <Link to="/library#historical-cases">← Historical cases</Link>
        <span>Historical case {view.position} of {view.count}</span>
      </nav>
      <header className="library-case-header reveal" style={order(0)}>
        <p className="kicker">Historical announcement · {item.topic}</p>
        <h1>{item.title}</h1>
        <p className="lede">{item.summary.text} <Cites ids={item.summary.facts} facts={numbered} /></p>
        <LibraryLabels labels={view.labels} />
        <dl className="ledger library-source">
          <div><dt>Release</dt><dd>{source.title}</dd></div>
          <div><dt>Publisher</dt><dd>{source.publisher}</dd></div>
          <div><dt>Announced</dt><dd data-precision="date">{dayLabel(view.announced)} (date only: no time is stated)</dd></div>
          <div><dt>As stated</dt><dd>{source.date_as_stated}</dd></div>
          <div><dt>Official address</dt><dd><External href={source.url}>{source.url}</External></dd></div>
        </dl>
        <p className="related-historical" role="note">{view.historical_note}</p>
        <p className={`related-check related-check-${check.state}`} data-check={check.state}>
          <strong>{SOURCE_CHECK_LABEL[check.state]}.</strong> {check.detail}
        </p>
      </header>

      <div className="library-layout">
        <nav className="method-toc library-toc reveal" style={order(1)} aria-label="On this page">
          <p className="kicker">On this page</p>
          <ol>{SECTIONS.map(([key, title]) => <li key={key}><a href={`#${key}`}>{title}</a></li>)}</ol>
        </nav>
        <div className="library-body reveal" style={order(2)}>
          <Section id="account" note={view.facts_note}>
            <ol className="related-facts">
              {item.facts.map((fact) => (
                <li key={fact.id} id={`fact-${fact.id}`} className="related-fact">
                  <p><span className="related-label">Source fact</span> {fact.text}</p>
                  {fact.quotes.map((quote) => <blockquote key={quote}>“{quote}”</blockquote>)}
                </li>
              ))}
            </ol>
          </Section>

          <Section id="dates" note={"Announcement, action, effective, publication and deadline dates are kept apart. " +
            "Each is a calendar date as the release states it; a date it does not state stays unknown."}>
            <table className="library-facts related-dates">
              <thead><tr><th scope="col">Kind</th><th scope="col">What</th><th scope="col">Date</th>
                <th scope="col">As stated</th></tr></thead>
              <tbody>
                {item.dates.map((date) => (
                  <tr key={date.label} data-kind={date.kind}>
                    <th scope="row" data-label="Kind">{view.date_kinds[date.kind] ?? date.kind}</th>
                    <td data-label="What">{date.label} <Cites ids={date.facts} facts={numbered} /></td>
                    <td data-label="Date">{date.date ? dayLabel(date.date) : "Unknown"}</td>
                    <td data-label="As stated">
                      {date.as_stated ? `“${date.as_stated}”` : "Not stated"}
                      {date.note && <span className="related-date-note">{date.note}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section id="scope" note="Restatements of the facts they cite; nothing here is inferred from linked documents.">
            <ul className="library-points">
              {item.scope.map((entry) => <li key={entry.text}>{entry.text} <Cites ids={entry.facts} facts={numbered} /></li>)}
            </ul>
          </Section>

          <Section id="actors"
            note={`Tags are what Related cases matches events against (rules ${view.rules_version}); each cites the facts it rests on.`}>
            <ul className="library-points">
              {item.actors.map((actor) => (
                <li key={actor.name}><strong>{actor.name}.</strong> {actor.role}. <Cites ids={actor.facts} facts={numbered} /></li>
              ))}
            </ul>
            <dl className="ledger related-tags">
              {DIMENSIONS.map((dimension) => (
                <div key={dimension}>
                  <dt>{view.dimension_labels[dimension]}</dt>
                  <dd>{item.tags[dimension].length === 0 ? "None" : item.tags[dimension].map((tag, index) => (
                    <span key={tag.slug}>{index > 0 && "; "}{view.tag_labels[dimension][tag.slug] ?? tag.slug}{" "}
                      <Cites ids={tag.facts} facts={numbered} /></span>
                  ))}</dd>
                </div>
              ))}
            </dl>
          </Section>

          <Section id="interpretation" note={view.interpretation_label}>
            {item.interpretation.channels.map((channel) => (
              <div key={channel.title} className="library-channel related-channel">
                <h3>{channel.title}</h3>
                <p className="related-reading"><span className="related-label">Interpretation</span> {channel.text}</p>
                <p className="related-muted">Reads <Cites ids={channel.facts} facts={numbered} />.</p>
              </div>
            ))}
            <h3>Why someone researching a related event should read this</h3>
            <p className="related-reading"><span className="related-label">Interpretation</span> {item.interpretation.why_read}</p>
            <h3>Points to compare with a later event</h3>
            <ul className="library-points">
              {item.comparison_points.map((point) => (
                <li key={point.label}><strong>{point.label}:</strong> {point.case_value}{" "}
                  <Cites ids={point.facts} facts={numbered} /></li>
              ))}
            </ul>
          </Section>

          <Section id="unknowns" note="Unknown here means not in the retained page; nothing was inferred to fill it.">
            <ul className="library-points">{item.unknowns.map((text) => <li key={text}>{text}</li>)}</ul>
          </Section>

          <Section id="provenance">
            <dl className="ledger library-provenance">
              <div><dt>Prepared by</dt><dd>{item.provenance.prepared_by}</dd></div>
              <div><dt>Prepared on</dt><dd>{item.provenance.prepared_on}</dd></div>
              <div><dt>Human review</dt><dd>None: not reviewed by a person</dd></div>
              <div><dt>Research use</dt><dd>Excluded: never frozen, scored or counted</dd></div>
              <div><dt>Currency</dt><dd>Historical: an announcement as of its date, not current law or policy</dd></div>
              <div><dt>Retained copy</dt><dd>
                {source.retained.bytes.toLocaleString("en-US")} bytes · SHA-256 <code>{source.retained.sha256}</code>
              </dd></div>
              <div><dt>Acquisition</dt><dd>
                Approval {source.retained.approval_id}, request {source.retained.attempt}: requested{" "}
                {formatUtc(source.retained.requested_at)}, received {formatUtc(source.retained.received_at)}
                {" "}({source.retained.media_type}). Retrieval times are not the release's date.
              </dd></div>
              <div><dt>Acquisition record</dt><dd>{check.acquisition_record === "matches"
                ? "On this machine, and it agrees with this case" : check.acquisition_record === "absent"
                  ? "Not on this machine" : "On this machine, but it does not agree with this case"}</dd></div>
            </dl>
            <p className="library-method">{item.provenance.method}</p>
            <p className="library-method">The retained copy is kept privately and is not served by this app.</p>
          </Section>
        </div>
      </div>

      <nav className="library-pager" aria-label="Other historical cases">
        {view.previous
          ? <Link to={relatedCaseHref(view.previous.id)} rel="prev">← {view.previous.title}</Link> : <span />}
        <Link to="/library#historical-cases">All historical cases</Link>
        {view.next ? <Link to={relatedCaseHref(view.next.id)} rel="next">{view.next.title} →</Link> : <span />}
      </nav>
    </article>
  );
}
