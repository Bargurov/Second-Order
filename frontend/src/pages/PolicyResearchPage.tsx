import { useEffect, type CSSProperties, type ReactNode } from "react";
import { useLoad } from "../api";
import { Skeleton } from "../components/Chrome";
import { shortHash } from "../format";
import {
  DIMENSIONS, STATUS_MARK, datedStatements, fetchResearch, listingDay, listingTime, stageColumns, stageNote,
  statedDate, statusesOf, type Comparison, type DimensionEntry, type Evidence, type Excerpt, type Publication,
  type ResearchView, type Statement, type Status,
} from "../policyResearch";
import { Link } from "../router";
import "../library.css";
import "../policyResearch.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

const SECTIONS = [
  ["chronology", "Chronology and date precision"],
  ["matrix", "What each release states"],
  ["stages", "Supply-chain stages named"],
  ["comparisons", "Comparisons"],
  ["publications", "The selected releases"],
  ["not-included", "Considered, not included"],
  ["not-claimed", "Claims not made"],
  ["provenance", "Sources and review status"],
] as const;
type SectionId = (typeof SECTIONS)[number][0];
/** The matrix shows the dimensions a reader compares across releases; timing has its own chronology, stages a grid. */
const MATRIX = ["instrument", "relation", "parties", "scope"] as const;

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

/** A status, worded as the view labels it, with a mark that does not depend on colour alone. */
function StatusTag({ status, label }: { status: Status; label: string }) {
  return <span className={`policy-status policy-status-${status}`} data-status={status}>{label}</span>;
}

function Quote({ excerpt, publication }: { excerpt: Excerpt; publication: Publication }) {
  return (
    <figure className="policy-quote">
      <blockquote>{excerpt.quote}</blockquote>
      <figcaption>
        Paragraph {excerpt.paragraph} of {publication.record.paragraphs} · {publication.short_title} ·{" "}
        <External href={publication.url}>bis.gov</External>
      </figcaption>
    </figure>
  );
}

export function PolicyResearchPage({ id }: { id: string }) {
  const [loaded, retry] = useLoad((signal) => fetchResearch(id, signal), `research:${id}`);
  useEffect(() => {
    document.title = loaded.state === "ready" ? `${loaded.data.title} · Research view · Second Order`
      : "Research view · Second Order";
  }, [loaded]);
  if (loaded.state === "loading") return <Skeleton />;
  if (loaded.state === "missing") {
    return (
      <section className="state-panel" aria-labelledby="missing-research-title">
        <p className="kicker">404 · Not found</p>
        <h1 id="missing-research-title">There is no research view at this address</h1>
        <p>No research view is called <code>{id}</code>.</p>
        <p><Link to="/library#research-views">Back to the research views</Link></p>
      </section>
    );
  }
  if (loaded.state !== "ready") {
    return (
      <section className="state-panel" role="alert">
        <p>This research view could not be read: {loaded.message}</p>
        <button type="button" className="button" onClick={retry}>Try again</button>
      </section>
    );
  }
  return <ResearchPage view={loaded.data} />;
}

function ResearchPage({ view }: { view: ResearchView }) {
  const byId = new Map(view.publications.map((item) => [item.id, item]));
  const counts = view.counts;
  const total = view.publications.length;
  return (
    <article className="library-case policy-research" data-research={view.id}>
      <nav className="library-crumbs" aria-label="Case library">
        <Link to="/library#research-views">← Case library</Link>
        <span>Research view</span>
      </nav>
      <header className="library-case-header reveal" style={order(0)}>
        <p className="kicker">Research view · Retrospective comparison</p>
        <h1>{view.title}</h1>
        <p className="lede">{view.question}</p>
        <p className="policy-scope" role="note">{view.scope_note}</p>
        <ul className="policy-corpus">{view.corpus_notes.map((note) => <li key={note}>{note}</li>)}</ul>
        <div className="policy-legend" aria-label="How statements are labelled">
          <p className="kicker">How to read the labels</p>
          <dl>
            <div><dt><StatusTag status="stated" label={view.labels.statuses.stated} /></dt>
              <dd>The release's own words, quoted with the paragraph they come from.</dd></div>
            <div><dt><StatusTag status="interpretation" label={view.labels.statuses.interpretation} /></dt>
              <dd>The curator's reading of the quoted words, never presented as the publisher's.</dd></div>
            <div><dt><StatusTag status="not_stated" label={view.labels.statuses.not_stated} /></dt>
              <dd>The retained text does not say it. That says nothing about other documents.</dd></div>
            <div><dt><StatusTag status="referenced_unread" label={view.labels.statuses.referenced_unread} /></dt>
              <dd>The release points to a document that was not retained or read.</dd></div>
            <div><dt><span className="policy-status policy-status-unknown">Unknown</span></dt>
              <dd>What a comparison leaves open, and the evidence that would settle more.</dd></div>
          </dl>
        </div>
        <p className={`policy-check policy-check-${view.snapshot.state}`} data-check={view.snapshot.state}>
          <strong>{view.labels.publication_states[view.snapshot.state]}.</strong>{" "}
          {counts.publications.verified} of {total} releases checked; {counts.comparisons.available} of{" "}
          {view.comparisons.length} comparisons available
          {counts.comparisons.needs_revalidation > 0 && `, ${counts.comparisons.needs_revalidation} needing revalidation`}
          {counts.comparisons.unavailable > 0 && `, ${counts.comparisons.unavailable} unavailable`}.{" "}
          {view.snapshot.filter_matches !== null &&
            `${view.snapshot.filter_matches} records of the snapshot matched its semiconductor keyword filter; ${total} were selected after reading.`}
        </p>
      </header>

      <div className="library-layout">
        <nav className="method-toc library-toc reveal" style={order(1)} aria-label="On this page">
          <p className="kicker">On this page</p>
          <ol>{SECTIONS.map(([key, title]) => <li key={key}><a href={`#${key}`}>{title}</a></li>)}</ol>
        </nav>
        <div className="library-body policy-body reveal" style={order(2)}>
          <Section id="chronology" note={"Ordered by BIS's listing time. Each date keeps its field: a listing time is " +
            "when BIS's site lists a release, a dateline is the date printed on a release page, and stated dates are " +
            "quoted from the text with their precision."}>
            <ol className="policy-timeline">
              {view.publications.map((item) => <TimelineEntry key={item.id} item={item} view={view} />)}
            </ol>
          </Section>

          <Section id="matrix" note={"One row per release. Each cell is a short label; its label shows whether it " +
            "rests on the publisher's words, the curator's reading, or the text's silence. Open a release below for " +
            "the quoted passages."}>
            <div className="policy-scroll">
              <table className="policy-matrix">
                <thead>
                  <tr><th scope="col">Release</th>
                    {MATRIX.map((name) => <th key={name} scope="col">{view.labels.dimensions[name]}</th>)}</tr>
                </thead>
                <tbody>
                  {view.publications.map((item) => (
                    <tr key={item.id} data-publication={item.id}>
                      <th scope="row"><a href={`#pub-${item.id}`}>{item.short_title}</a>
                        <span className="policy-when">Listed {listingDay(item.listing.published)}</span></th>
                      {MATRIX.map((name) => (
                        <td key={name} data-label={view.labels.dimensions[name]}>
                          {item.dimensions ? <Cell entry={item.dimensions[name]} view={view} />
                            : <span className="policy-unchecked">Not checked here</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section id="stages" note={"Which stages each release's text names items at. Placing an item at a stage is " +
            "the curator's reading of the quoted words; an empty cell means the retained text names nothing there, " +
            "not that the stage is unregulated."}>
            <StageGrid view={view} />
          </Section>

          <Section id="comparisons" note={"Each comparison names the releases it reads, states what the quoted " +
            "passages support, says why the distinction helps, and records what remains unknown. These are " +
            "observations about the texts, not findings about effects."}>
            <div className="policy-comparisons">
              {view.comparisons.map((comparison) => (
                <ComparisonCard key={comparison.id} comparison={comparison} view={view} byId={byId} />
              ))}
            </div>
          </Section>

          <Section id="publications" note={view.method_note}>
            {view.publications.map((item) => <PublicationDetail key={item.id} item={item} view={view} />)}
          </Section>

          <Section id="not-included" note={"Records of the snapshot that were read and left out, with the reason. " +
            "Not selected does not mean irrelevant."}>
            <ul className="policy-excluded">
              {view.not_included.map((item) => (
                <li key={item.url} data-state={item.state}>
                  <p className="library-entry-meta"><span>Listed {listingDay(item.listed)}</span>
                    {item.state !== "verified" && <span>{view.labels.publication_states[item.state]}</span>}</p>
                  <External href={item.url}>{item.title}</External>
                  <p>{item.reason}{item.case && <> <Link to={item.case.href}>{item.case.title}</Link>.</>}</p>
                </li>
              ))}
            </ul>
          </Section>

          <Section id="not-claimed" note="Deliberately not claimed anywhere on this page:">
            <ul className="library-points">{view.not_claimed.map((claim) => <li key={claim}>{claim}</li>)}</ul>
          </Section>

          <Section id="provenance">
            <dl className="ledger policy-ledger">
              <div><dt>Prepared</dt><dd>{view.provenance.prepared_by}, {view.provenance.prepared_on}</dd></div>
              <div><dt>Review</dt><dd>AI-assisted; not reviewed by a person; not used in the Tracker's research</dd></div>
              <div><dt>Snapshot</dt><dd><External href={view.snapshot.url}>{view.snapshot.url}</External>, retained{" "}
                {listingTime(view.snapshot.retrieved_at)} (approval {view.snapshot.approval_id})</dd></div>
              <div><dt>Snapshot SHA-256</dt><dd className="policy-hash">{view.snapshot.sha256}</dd></div>
              <div><dt>Snapshot check</dt><dd>{view.snapshot.detail}</dd></div>
              {view.release_pages.map((page) => (
                <div key={page.id}><dt>Release page</dt>
                  <dd>{page.dateline} · {view.labels.publication_states[page.state]} · approval {page.approval_id},
                    SHA-256 {shortHash(page.sha256, 12)}</dd></div>
              ))}
            </dl>
            <p className="library-section-note">{view.provenance.method}</p>
          </Section>
        </div>
      </div>
    </article>
  );
}

function Cell({ entry, view }: { entry: DimensionEntry; view: ResearchView }) {
  return (
    <>
      <span className="policy-cell-label">{entry.label}</span>
      <span className="policy-cell-marks">
        {statusesOf(entry).map((status) => (
          <span key={status} className={`policy-mark policy-status-${status}`} title={view.labels.statuses[status]}>
            {STATUS_MARK[status]}
          </span>
        ))}
      </span>
    </>
  );
}

function TimelineEntry({ item, view }: { item: Publication; view: ResearchView }) {
  const dated = datedStatements(item);
  const created = item.listing.created;
  const createdLater = created !== null && listingDay(created) !== listingDay(item.listing.published);
  return (
    <li className="policy-moment" data-publication={item.id}>
      <p className="policy-moment-day">{listingDay(item.listing.published)}</p>
      <div>
        <a className="policy-moment-title" href={`#pub-${item.id}`}>{item.short_title}</a>
        <dl className="policy-dates">
          <div><dt>{view.labels.listing_fields.published}</dt><dd>{listingTime(item.listing.published)}</dd></div>
          {createdLater && (
            <div><dt>{view.labels.listing_fields.created}</dt><dd>{listingTime(created)}</dd></div>
          )}
          {item.dateline && (
            <div><dt>Release dateline</dt>
              <dd>{item.dateline.value ?? `Not shown: ${item.dateline.detail}`}</dd></div>
          )}
          {item.dimensions === null ? (
            <div><dt>Stated dates</dt><dd className="policy-unchecked">Not checked here</dd></div>
          ) : dated.length === 0 ? (
            <div><dt>Stated dates</dt><dd>None stated in the text</dd></div>
          ) : dated.flatMap((statement, group) => statement.dates.map((date, index) => (
            <div key={`${group}-${index}`}><dt>{view.labels.date_kinds[date.kind]}</dt>
              <dd>{statedDate(date)} <span className="policy-precision">{view.labels.precisions[date.precision]}</span>
                {index === statement.dates.length - 1 && <span className="policy-date-of">{statement.text}</span>}</dd>
            </div>
          )))}
        </dl>
      </div>
    </li>
  );
}

function StageGrid({ view }: { view: ResearchView }) {
  const columns = stageColumns(view);
  return (
    <div className="policy-scroll">
      <table className="policy-stages">
        <thead>
          <tr><th scope="col">Release</th>
            {columns.map((column) => <th key={column.stage} scope="col"><span>{column.label}</span></th>)}</tr>
        </thead>
        <tbody>
          {view.publications.map((item) => (
            <tr key={item.id}>
              <th scope="row"><a href={`#pub-${item.id}`}>{item.short_title}</a></th>
              {columns.map((column) => (
                <td key={column.stage} data-stage={column.stage}>
                  {item.stages === null ? <span className="policy-unchecked" title="Not checked here">?</span>
                    : column.named.has(item.id) ? <span className="policy-named" role="img"
                        aria-label={`Named: ${column.label} (curator's reading)`}>●</span>
                      : <span className="policy-none" aria-label="Not named in this text">·</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceItem({ evidence, view, byId }: { evidence: Evidence; view: ResearchView;
                                                   byId: Map<string, Publication> }) {
  const item = byId.get(evidence.publication)!;
  if (evidence.kind === "quote") {
    return <li><Quote excerpt={{ paragraph: evidence.paragraph!, quote: evidence.quote! }} publication={item} /></li>;
  }
  if (evidence.kind === "field") {
    return (
      <li className="policy-metadata">
        <span className="policy-status policy-status-stated">Listing metadata</span>{" "}
        {item.short_title}: {view.labels.listing_fields[evidence.field!]} {listingTime(evidence.value!)}
      </li>
    );
  }
  return (
    <li className="policy-metadata">
      <span className="policy-status policy-status-not_stated">Checked absence</span>{" "}
      The retained text of {item.short_title} does not contain “{evidence.absent}”.
    </li>
  );
}

function ComparisonCard({ comparison, view, byId }: { comparison: Comparison; view: ResearchView;
                                                      byId: Map<string, Publication> }) {
  const releases = new Set(comparison.evidence?.map((evidence) => evidence.publication));
  return (
    <article className="policy-comparison" id={`cmp-${comparison.id}`} data-state={comparison.state}
             aria-labelledby={`cmp-${comparison.id}-title`}>
      <p className="policy-kind">{view.labels.comparison_kinds[comparison.kind] ?? comparison.kind}</p>
      <h3 id={`cmp-${comparison.id}-title`}>{comparison.question}</h3>
      <p className="policy-compared">
        <span className="policy-label">Compared</span>
        {comparison.publications.map((id, index) => {
          const item = byId.get(id)!;
          return <span key={id}>{index > 0 && " · "}<a href={`#pub-${id}`}>{item.short_title}</a>{" "}
            <span className="policy-when">({listingDay(item.listing.published)})</span></span>;
        })}
      </p>
      {comparison.state !== "available" ? (
        <div className="policy-withheld" role="note">
          <p><strong>{view.labels.comparison_states[comparison.state]}.</strong> The observation and its evidence are
            not shown until the sources check again.</p>
          <ul>{comparison.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
        </div>
      ) : (
        <>
          <div className="policy-observation">
            <p className="policy-part">Observation · a summary of the quoted statements</p>
            <p>{comparison.observation}</p>
          </div>
          <details className="policy-evidence">
            <summary>Evidence: {comparison.evidence!.length} items from {releases.size} releases</summary>
            <ol>{comparison.evidence!.map((evidence, index) => (
              <EvidenceItem key={index} evidence={evidence} view={view} byId={byId} />
            ))}</ol>
          </details>
          <div className="policy-why">
            <p className="policy-part">Why this distinction helps · <StatusTag status="interpretation"
              label={view.labels.statuses.interpretation} /></p>
            <p>{comparison.why}</p>
          </div>
          <div className="policy-unknown">
            <p className="policy-part"><span className="policy-status policy-status-unknown">Unknown</span></p>
            <p>{comparison.unknown}</p>
            <p><strong>Would establish more:</strong> {comparison.would_establish}</p>
          </div>
        </>
      )}
    </article>
  );
}

function StatementView({ statement, view, item }: { statement: Statement; view: ResearchView; item: Publication }) {
  return (
    <li className="policy-statement" data-status={statement.status}>
      <StatusTag status={statement.status} label={view.labels.statuses[statement.status]} />{" "}
      <span>{statement.text}</span>
      {statement.stage && stageNote(statement, view.labels.stages[statement.stage]) &&
        <span className="policy-stage-tag"> · Stage: {view.labels.stages[statement.stage]}</span>}
      {statement.dates.length > 0 && (
        <ul className="policy-stated-dates">
          {statement.dates.map((date, index) => (
            <li key={index}>{view.labels.date_kinds[date.kind]}: {statedDate(date)}{" "}
              <span className="policy-precision">{view.labels.precisions[date.precision]}</span></li>
          ))}
        </ul>
      )}
      {statement.excerpts.map((excerpt, index) => <Quote key={index} excerpt={excerpt} publication={item} />)}
    </li>
  );
}

function PublicationDetail({ item, view }: { item: Publication; view: ResearchView }) {
  return (
    <details className="policy-publication" id={`pub-${item.id}`} data-state={item.state}>
      <summary>
        <span className="policy-position">{String(item.position).padStart(2, "0")}</span>
        <span className="policy-summary-title">{item.short_title}</span>
        <span className="policy-when">Listed {listingDay(item.listing.published)}</span>
        {item.state !== "verified" && <span className="policy-unchecked">{view.labels.publication_states[item.state]}</span>}
      </summary>
      <dl className="ledger policy-ledger">
        <div><dt>Publisher's title</dt><dd>{item.title}</dd></div>
        <div><dt>Address</dt><dd><External href={item.url}>{item.url}</External></dd></div>
        {(["published", "created", "changed"] as const).map((field) => (
          <div key={field}><dt>{view.labels.listing_fields[field]}</dt>
            <dd>{item.listing[field] ? listingTime(item.listing[field]!) : "Not given"}</dd></div>
        ))}
        <div><dt>Release dateline</dt>
          <dd>{item.dateline ? item.dateline.value ?? `Not shown: ${item.dateline.detail}`
            : "Not retained: no release page of this address was kept"}</dd></div>
        <div><dt>Text</dt><dd>{item.text.detail}</dd></div>
        <div><dt>Record</dt><dd>{item.record.paragraphs} paragraphs · SHA-256 {shortHash(item.record.record_sha256, 12)}</dd></div>
      </dl>
      <p className="policy-selected"><span className="policy-label">Why selected</span>{item.why_included}</p>
      {item.cases.length > 0 && (
        <p className="policy-cases"><span className="policy-label">In the case library</span>
          {item.cases.map((link) => <span key={link.id}><Link to={link.href}>{link.title}</Link>. {link.note} </span>)}
        </p>
      )}
      {item.state !== "verified" ? (
        <div className="policy-withheld" role="note">
          <p><strong>{view.labels.publication_states[item.state]}.</strong> Its statements are not shown.</p>
          <ul>{item.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
        </div>
      ) : (
        <>
          <dl className="policy-dimensions">
            {DIMENSIONS.map((name) => (
              <div key={name} data-dimension={name}>
                <dt>{view.labels.dimensions[name]}<span className="policy-dimension-label">{item.dimensions![name].label}</span></dt>
                <dd><ul>{item.dimensions![name].statements.map((statement, index) => (
                  <StatementView key={index} statement={statement} view={view} item={item} />
                ))}</ul></dd>
              </div>
            ))}
          </dl>
          {item.references!.length > 0 && (
            <div className="policy-references">
              <h3>Linked documents not retained</h3>
              <ul>{item.references!.map((reference) => (
                <li key={reference.id}>{reference.description}
                  {reference.excerpts.map((excerpt, index) => <Quote key={index} excerpt={excerpt} publication={item} />)}
                </li>
              ))}</ul>
            </div>
          )}
        </>
      )}
    </details>
  );
}
