import { useEffect, type CSSProperties, type ReactNode } from "react";
import { fetchLibraryCase, useLoad, type Loaded } from "../api";
import { discrepancies, fetchCaseEnrichment, fitsCase, type EnrichmentView } from "../caseEnrichment";
import { Skeleton } from "../components/Chrome";
import { DiscrepancyFlag, EnrichmentPanel } from "../components/CaseEnrichment";
import { LibraryLabels, LibraryState } from "../components/CaseLibrary";
import { MarketContextSection } from "../components/MarketContext";
import {
  categorySlug, filtersHref, formatDay, publishedLocal, type LibraryCase, type LibraryCaseView,
} from "../library";
import { Link } from "../router";
import "../library.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;

const SECTIONS = [
  ["check", "Source check and reading aid"],
  ["overview", "What the release says"],
  ["facts", "Key facts"],
  ["channels", "Possible channels to Treasury yields"],
  ["context", "Market context"],
  ["competing", "Competing explanations"],
  ["limits", "Assumptions, gaps and what would weaken this"],
  ["critique", "Editorial critique"],
  ["sources", "Sources and limits"],
  ["provenance", "Authorship and provenance"],
] as const;

type SectionId = (typeof SECTIONS)[number][0];
type SectionList = readonly (readonly [SectionId, string])[];

/**
 * The page's sections: the source check only for a case that has one (or a note saying why it is not shown), market
 * context only for a case the collection declares it for. A sector case's channels run to activity in its sectors,
 * not to Treasury yields, so that heading is neutral there.
 */
const sectionsFor = (view: LibraryCaseView, check: boolean): SectionList =>
  SECTIONS.filter(([key]) => (key !== "context" || view.market_context) && (key !== "check" || check))
    .map(([key, title]) => [key, key !== "channels" ? title : view.case.entry_kind === "proceedings"
      ? "Transmission channels" : view.sectors.length > 0 || view.case.entry_kind ? "Possible transmission channels"
      : title]);

/** The published line: the stated time in its own offset (and UTC), or the stated date for a date-only source. */
function publishedLine(view: LibraryCaseView): string {
  if (view.publication.precision === "date") {
    return `${formatDay(view.publication.date) ?? view.publication.date} (date only: the source states no time)`;
  }
  const time = publishedLocal(view.publication.at);
  return time ? `${time.day}, ${time.clock} ${time.offset} (${time.utc})` : view.publication.at;
}

function Section({ id, sections, children, note }:
                 { id: SectionId; sections: SectionList; children: ReactNode; note?: string }) {
  const index = sections.findIndex(([key]) => key === id);
  return (
    <section id={id} className="library-section-block" aria-labelledby={`${id}-title`}>
      <p className="kicker">{String(index + 1).padStart(2, "0")}</p>
      <h2 id={`${id}-title`}>{sections[index][1]}</h2>
      {note && <p className="library-section-note">{note}</p>}
      {children}
    </section>
  );
}

const External = ({ href, children }: { href: string; children: ReactNode }) => (
  <a className="library-external" href={href} target="_blank" rel="noreferrer">{children}</a>
);

/** The labels every case carries, from its own provenance: nothing here is reviewed, frozen or scored. */
function caseLabels(item: LibraryCase): string[] {
  return ["Retrospective", "AI-assisted editorial illustration",
          `Prepared after publication · ${item.provenance.prepared_on}`, "Not human-reviewed",
          "Never scored · not research evidence"];
}

export function LibraryCasePage({ id }: { id: string }) {
  const [loaded, retry] = useLoad((signal) => fetchLibraryCase(id, signal), `library-case:${id}`);
  const [enriched] = useLoad((signal) => fetchCaseEnrichment(id, signal), `case-enrichment:${id}`);
  useEffect(() => {
    document.title = loaded.state === "ready"
      ? `${loaded.data.case.title} · Case library · Second Order` : "Case library · Second Order";
  }, [loaded]);
  if (loaded.state === "loading") return <Skeleton />;
  if (loaded.state === "missing") {
    return (
      <section className="state-panel" aria-labelledby="missing-case-title">
        <p className="kicker">404 · Not found</p>
        <h1 id="missing-case-title">There is no case at this address</h1>
        <p>The case library has no case called <code>{id}</code>.</p>
        <p><Link to="/library">Back to the case library</Link></p>
      </section>
    );
  }
  if (loaded.state !== "ready") {
    return <section className="state-panel"><LibraryState library={loaded} onRetry={retry} /></section>;
  }
  return <CaseView view={loaded.data} enriched={enriched} />;
}

/** A bound enrichment that describes this very case, or why none is shown (null: nothing to say). */
function enrichmentFor(enriched: Loaded<EnrichmentView>, view: LibraryCaseView) {
  if (enriched.state === "error") {
    return { enrichment: null, note: `The source check could not be loaded: ${enriched.message}` };
  }
  if (enriched.state !== "ready") return { enrichment: null, note: null };
  const served = enriched.data;
  if (served.state === "stale") return { enrichment: null, note: served.note };
  if (served.state !== "bound" || !served.enrichment) return { enrichment: null, note: null };
  return fitsCase(served.enrichment, view.case) ? { enrichment: served.enrichment, note: null }
    : { enrichment: null, note: "A source check exists, but it does not match this case's claims, so it is not shown." };
}

function CaseView({ view, enriched }: { view: LibraryCaseView; enriched: Loaded<EnrichmentView> }) {
  const item = view.case;
  const source = item.source;
  const time = view.publication.precision === "time" ? publishedLocal(view.publication.at) : null;
  const { enrichment, note: checkNote } = enrichmentFor(enriched, view);
  const flags = discrepancies(enrichment);
  const sections = sectionsFor(view, enrichment !== null || checkNote !== null);
  const statedTime = time ? `${time.day}, ${time.clock} ${time.offset}` : source.published_at;
  return (
    <article className="library-case">
      <nav className="library-crumbs" aria-label="Case library">
        <Link to="/library">← Case library</Link>
        <span>Case {view.position} of {view.count}</span>
      </nav>
      <header className="library-case-header reveal" style={order(0)}>
        <p className="kicker">
          <Link to={filtersHref({ query: "", category: categorySlug(item.category) })}
            className="library-case-category">
            {item.category}
          </Link>
        </p>
        <h1>{item.title}</h1>
        {flags.has("title") && <p><DiscrepancyFlag check={flags.get("title")} /></p>}
        <p className="lede">{item.summary} <DiscrepancyFlag check={flags.get("summary")} /></p>
        {view.sectors.length > 0 && (
          <ul className="library-sector-chips library-case-sectors" aria-label="Sectors">
            {view.sectors.map((sector) => (
              <li key={sector.slug}><Link to={filtersHref({ sector: sector.slug })}>{sector.label}</Link></li>
            ))}
          </ul>
        )}
        <LibraryLabels labels={caseLabels(item)} />
        <dl className="ledger library-source">
          <div><dt>Release</dt><dd>{source.title}{source.document_id ? ` · ${source.document_id}` : ""}</dd></div>
          <div><dt>Publisher</dt><dd>{source.publisher}</dd></div>
          <div>
            <dt>Published</dt>
            <dd data-precision={view.publication.precision}>{publishedLine(view)}</dd>
          </div>
          <div><dt>As stated</dt><dd>{source.published_as_stated}</dd></div>
          <div><dt>Reference period</dt><dd>{source.reference_period}</dd></div>
          <div><dt>Official source</dt><dd><External href={source.url}>{source.url}</External></dd></div>
        </dl>
        <p className="library-timezone">{source.timezone_note}</p>
        <p className="library-benchmark" role="note">
          No sourced expectations benchmark is used, so this case does not say whether the release was a surprise.
          {view.market_context
            ? " Market context shows daily Treasury yields around the publication date as description only: no " +
              "reaction is measured or attributed to the release, and no outcome is shown."
            : view.sectors.length > 0
              ? " No market series is attached: Treasury yields do not measure activity in this case's sectors, and " +
                "the library holds no sector price or return series. This case shows no market data, chart or outcome."
              : " This case shows no market data, chart or outcome."}
        </p>
      </header>

      <div className="library-layout">
        <nav className="method-toc library-toc reveal" style={order(1)} aria-label="On this page">
          <p className="kicker">On this page</p>
          <ol>{sections.map(([key, title]) => <li key={key}><a href={`#${key}`}>{title}</a></li>)}</ol>
        </nav>
        <div className="library-body reveal" style={order(2)}>
          {(enrichment || checkNote) && (
            <Section sections={sections} id="check"
              note={enrichment ? `Added on ${enrichment.provenance.prepared_on}, after the case was written, from ` +
                "privately retained copies of BIS pages. The case's own text, provenance and review status below are " +
                `unchanged. ${enrichment.currency_note}` : undefined}>
              {enrichment
                ? <EnrichmentPanel enrichment={enrichment} />
                : <p className="library-no-channels" role="note">{checkNote}</p>}
            </Section>
          )}

          <Section sections={sections} id="overview">
            {item.overview.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
          </Section>

          <Section sections={sections} id="facts" note="As first published. The basis says how each figure is measured.">
            <table className="library-facts">
              <thead><tr><th scope="col">Measure</th><th scope="col">Value</th><th scope="col">Basis</th></tr></thead>
              <tbody>
                {item.key_facts.map((fact, index) => (
                  <tr key={fact.label}>
                    <th scope="row" data-label="Measure">
                      {fact.label} <DiscrepancyFlag check={flags.get(`key_facts[${index}]`)} />
                    </th>
                    <td data-label="Value">{fact.value}</td>
                    <td data-label="Basis">{fact.basis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section sections={sections} id="channels"
            note={"Each channel separates what the release says from a conditional interpretation. None is a " +
              "prediction or a measured effect."}>
            {item.channels.length === 0 && (
              <p className="library-no-channels" role="note">
                None: this entry reports meeting proceedings, so no market transmission channel is given. A discussion
                or proposal is not a decision, and the note's silence does not show that none was taken elsewhere.
              </p>
            )}
            {item.channels.map((channel, index) => (
              <div key={channel.title} className="library-channel">
                <h3>{channel.title}</h3>
                <dl>
                  <div className="library-fact-side"><dt>From the release</dt><dd>
                    {channel.source_fact} <DiscrepancyFlag check={flags.get(`channels[${index}].source_fact`)} />
                  </dd></div>
                  <div className="library-reading-side">
                    <dt>Conditional interpretation</dt><dd>{channel.interpretation}</dd>
                  </div>
                </dl>
              </div>
            ))}
          </Section>

          {view.market_context && (
            <Section sections={sections} id="context"
              note={"Description only: what two Treasury yields did on the days around the release, beside the " +
                "case. It is not a test of the channels above and is not a measured reaction."}>
              <MarketContextSection caseId={item.id} statedTime={statedTime} />
            </Section>
          )}

          <Section sections={sections} id="competing" note="Readings that compete with, or offset, the channels above.">
            <ul className="library-points">
              {item.competing_explanations.map((point, index) => (
                <li key={point.title}>
                  <strong>{point.title}.</strong> {point.detail}{" "}
                  <DiscrepancyFlag check={flags.get(`competing_explanations[${index}].detail`)} />
                </li>
              ))}
            </ul>
          </Section>

          <Section sections={sections} id="limits">
            <h3>Assumptions</h3>
            <ul className="library-points">{item.assumptions.map((text) => <li key={text}>{text}</li>)}</ul>
            <h3>Missing information</h3>
            <ul className="library-points">{item.missing_information.map((text) => <li key={text}>{text}</li>)}</ul>
            <h3>What would weaken this interpretation</h3>
            <ul className="library-points">{item.weakening_observations.map((text) => <li key={text}>{text}</li>)}</ul>
          </Section>

          <Section sections={sections} id="critique"
            note={"Part of this prepared case, written by the same AI assistant. It is not a saved human review: the " +
              "case library holds no review records."}>
            <ol className="library-critique">
              {item.critique.map((point) => (
                <li key={point.title}><h3>{point.title}</h3><p>{point.detail}</p></li>
              ))}
            </ol>
          </Section>

          <Section sections={sections} id="sources">
            <ul className="library-points">
              {item.source_notes.map((note, index) => (
                <li key={note.title}>
                  <strong>{note.title}.</strong> {note.detail}
                  {note.url && <> <External href={note.url}>Official source</External></>}
                  {" "}<DiscrepancyFlag check={flags.get(`source_notes[${index}].detail`)} />
                </li>
              ))}
            </ul>
          </Section>

          <Section sections={sections} id="provenance">
            <dl className="ledger library-provenance">
              <div><dt>Prepared by</dt><dd>{item.provenance.prepared_by}</dd></div>
              <div><dt>Prepared on</dt><dd>{item.provenance.prepared_on}</dd></div>
              <div><dt>Human review</dt><dd>None: not reviewed by a person</dd></div>
              <div><dt>Research use</dt><dd>Excluded: never frozen, scored or counted</dd></div>
              <div><dt>Source retrieved</dt><dd>{source.retrieved_on}</dd></div>
              <div><dt>Page last updated</dt><dd>{source.page_last_updated ?? "Not shown"}</dd></div>
              {source.retained && (
                <div><dt>Retained copy</dt><dd>
                  Kept privately, not served: {source.retained.bytes.toLocaleString("en-US")} bytes, SHA-256{" "}
                  <code>{source.retained.sha256}</code>, approval {source.retained.approval_id}, received{" "}
                  {source.retained.retrieved_at}; charset {source.retained.charset}
                </dd></div>
              )}
            </dl>
            {source.date_basis && <p className="library-method"><strong>Date basis.</strong> {source.date_basis}</p>}
            <p className="library-method">{item.provenance.method}</p>
            <p className="library-method">
              Sources read: {item.provenance.sources_read.map((url, index) => (
                <span key={url}>{index > 0 && ", "}<External href={url}>{url}</External></span>
              ))}
            </p>
          </Section>
        </div>
      </div>

      <nav className="library-pager" aria-label="Other cases">
        {view.previous
          ? <Link to={`/library/${view.previous.id}`} rel="prev">← {view.previous.title}</Link> : <span />}
        <Link to="/library">All cases</Link>
        {view.next ? <Link to={`/library/${view.next.id}`} rel="next">{view.next.title} →</Link> : <span />}
      </nav>
    </article>
  );
}
