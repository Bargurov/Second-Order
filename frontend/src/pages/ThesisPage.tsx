import { useEffect, type CSSProperties } from "react";
import { useLoad } from "../api";
import { Skeleton } from "../components/Chrome";
import { ExposureSection } from "../components/ThesisExposure";
import {
  BalanceSection, ClaimsSection, ConditionsSection, DiffersSection, LogSection, NotClaimedSection, PlainSection,
  PriceSection, SECTIONS, ViewSection, anchorOf, reading,
} from "../components/ThesisSections";
import { formatUtc, shortHash } from "../format";
import { Link } from "../router";
import { dayText, elementsOf, fetchThesis, thesisHref, transcriptionText, type ThesisView } from "../thesis";
import "../library.css";
import "../policyResearch.css";
import "../thesis.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;
const CONFIDENCE = { low: "Low", medium: "Medium", high: "High" };

/**
 * A committed thesis at its latest version, or at one named version (/theses/:id[/versions/:n]), read from the local
 * API. The API checks each retained source on this machine against its acquisition record and looks for each figure and
 * passage cited from a page, a table or a workbook where it is cited; a figure or passage transcribed from a PDF is
 * bound to the PDF by its SHA-256 only. The reply is shown only after it passes the fail-closed reader (thesis.ts); the
 * page computes nothing and shows numbers as served.
 */
export function ThesisPage({ id, version }: { id: string; version: number | null }) {
  const [loaded, retry] = useLoad((signal) => fetchThesis(id, version, signal), `thesis:${id}:${version ?? "latest"}`);
  useEffect(() => {
    document.title = loaded.state === "ready" ? `${loaded.data.title} · Thesis · Second Order` : "Thesis · Second Order";
  }, [loaded]);
  if (loaded.state === "loading") return <Skeleton />;
  if (loaded.state === "missing") {
    return (
      <section className="state-panel" aria-labelledby="missing-thesis-title">
        <p className="kicker">404 · Not found</p>
        <h1 id="missing-thesis-title">There is no thesis at this address</h1>
        <p>{loaded.message}: <code>{id}</code>{version !== null && <>, version {version}</>}.</p>
        <p><Link to="/library#theses">Back to the theses</Link></p>
      </section>
    );
  }
  if (loaded.state !== "ready") {
    return (
      <section className="state-panel" role="alert">
        <p>This thesis could not be read: {loaded.message}</p>
        <button type="button" className="button" onClick={retry}>Try again</button>
      </section>
    );
  }
  return <Thesis view={loaded.data} />;
}

function Thesis({ view }: { view: ThesisView }) {
  const r = reading(view);
  return (
    <article className="library-case thesis" data-thesis={view.id} data-version={view.version}
             data-draft={view.draft || undefined}>
      <nav className="library-crumbs" aria-label="Case library">
        <Link to="/library#theses">← Case library</Link>
        {view.id === "copper" && <Link to="/copper" className="desk-link" data-desk-link="">Copper desk</Link>}
        <span>Thesis · version {view.version}{view.draft ? " · draft" : ""}</span>
      </nav>
      <Header view={view} />
      <div className="library-layout">
        <nav className="method-toc library-toc thesis-toc reveal" style={order(1)} aria-label="On this page">
          <p className="kicker">On this page</p>
          <ol>
            {SECTIONS.map(([key, title]) => <li key={key}><a href={`#${anchorOf(key)}`}>{title}</a></li>)}
            <li className="thesis-toc-footer"><a href="#sources">Sources</a></li>
          </ol>
        </nav>
        <div className="library-body thesis-body reveal" style={order(2)}>
          <ViewSection r={r} />
          <BalanceSection r={r} />
          <DiffersSection r={r} />
          <ClaimsSection r={r} kind="reason" />
          <ClaimsSection r={r} kind="risk" />
          <ConditionsSection r={r} />
          <ExposureSection r={r} />
          <LogSection r={r} />
          <PriceSection r={r} />
          <PlainSection r={r} />
          <NotClaimedSection r={r} />
          <Sources view={view} />
        </div>
      </div>
    </article>
  );
}

/** Section 1: the topic, the opening date, the last update, the confidence and what this page is, then the versions
 * and what this read found. */
function Header({ view }: { view: ThesisView }) {
  const elements = view.counts.elements;
  const withheld = [
    elements.needs_revalidation > 0 && `${elements.needs_revalidation} needing revalidation`,
    elements.unavailable > 0 && `${elements.unavailable} unavailable`,
  ].filter(Boolean);
  return (
    <header id="overview" data-thesis-section="header" className="library-case-header thesis-header reveal"
            style={order(0)} aria-labelledby="thesis-title">
      {view.draft && <p className="thesis-draft" role="note">Draft: not yet approved by the owner</p>}
      <p className="kicker">01 · Thesis · Research view</p>
      <h1 id="thesis-title">{view.title}</h1>
      <p className="thesis-disclaimer">A research view, not a recommendation to buy or sell</p>
      <dl className="ledger thesis-facts">
        <div><dt>Topic</dt><dd>{view.topic}</dd></div>
        <div><dt>Opened</dt><dd>{dayText(view.opened_on)}</dd></div>
        <div><dt>Last update</dt>
          <dd>{view.published_on ? dayText(view.published_on) : `Not published: a draft prepared ${dayText(view.prepared_on)}`}</dd></div>
        <div><dt>Confidence</dt><dd>{CONFIDENCE[view.confidence.level]}</dd></div>
      </dl>
      <p className="thesis-confidence"><span className="policy-label">Why this confidence</span>{view.confidence.basis}</p>
      <nav className="thesis-versions" aria-label="Versions of this thesis">
        <span className="policy-label">Versions</span>
        <ol>
          {view.versions.map((item) => (
            <li key={item.version}>
              <Link to={thesisHref(view.id, item.version)} aria-current={item.version === view.version ? "page" : undefined}>
                Version {item.version}
                <span className="thesis-version-day">{item.published_on ? dayText(item.published_on) : "draft"}</span>
              </Link>
            </li>
          ))}
        </ol>
      </nav>
      {view.id === "copper" && (
        <p className="thesis-tools"><Link to="/theses/copper/tools">Copper tools: coverage calculator and published
          producer unit-cost comparison</Link>, beside this thesis and separate from its view.{" "}
          <Link to="/metals">Where metals come from</Link>: production and reserves by country, for copper and the
          other metals you pick.{" "}<span data-tools="company"><Link to="/companies/fcx">Freeport-McMoRan (FCX)</Link>:
          one copper producer, from the copper price to its cash flow.</span>{" "}
          <span data-tools="events"><Link to="/theses/copper/events">Copper event chains</Link>: past events set
          against this thesis's reasons and risks, with the sources' own words and your review.</span></p>)}
      <p className="thesis-check" data-check={withheld.length > 0 ? "withheld" : "available"}>
        <strong>On this read:</strong> {elements.available} of {elementsOf(view).length} parts available;{" "}
        {view.counts.sources.verified} of {view.sources.length} sources match their acquisition records
        {withheld.length > 0 && `; ${withheld.join(", ")}`}.
      </p>
    </header>
  );
}

/** The footer: each source's state on this read, edition, terms and retrieval, and for a PDF the pages transcribed. */
function Sources({ view }: { view: ThesisView }) {
  return (
    <footer id="sources" className="library-section-block thesis-sources" aria-labelledby="sources-title">
      <p className="kicker">Where every figure comes from</p>
      <h2 id="sources-title">Sources</h2>
      <p className="library-section-note">Each source as retained on this machine and checked against its acquisition
        record on this read. A source that is not verified withholds every part that uses it.</p>
      <ol className="thesis-source-list">
        {view.sources.map((source) => {
          const transcription = transcriptionText(source);
          return (
            <li key={source.id} data-source={source.id} data-state={source.state}>
              <p className="thesis-source-name"><strong>{source.publisher}</strong> · {source.title}</p>
              <dl className="thesis-source-facts">
                <div><dt>Edition</dt><dd>{source.edition}</dd></div>
                <div><dt>State</dt><dd className="thesis-source-state">
                  <strong>{view.labels.source_states[source.state]}.</strong> {source.detail}</dd></div>
                <div><dt>Terms</dt><dd>{source.terms.licence}. {source.terms.note}</dd></div>
                <div><dt>Retrieved</dt><dd>{formatUtc(source.retrieved_at)}, {source.origin === "get"
                  ? "by one GET of the address below" : "downloaded by the owner and retained"}</dd></div>
                {transcription && (
                  <div><dt>Transcription</dt>
                    <dd>Figures and passages {transcription}; bound to the PDF by its SHA-256 only</dd></div>
                )}
                <div><dt>File</dt><dd><a className="library-external" href={source.url} target="_blank"
                  rel="noreferrer">{source.url}</a><span className="thesis-hash">SHA-256 {shortHash(source.sha256, 16)}</span></dd></div>
              </dl>
            </li>
          );
        })}
      </ol>
      <dl className="ledger thesis-provenance">
        <div><dt>Prepared</dt><dd>{view.provenance.prepared_by}, {dayText(view.prepared_on)}</dd></div>
        <div><dt>Review</dt><dd>AI-assisted; not reviewed by a person; excluded from research use</dd></div>
      </dl>
      <p className="library-section-note">{view.provenance.method}</p>
    </footer>
  );
}
