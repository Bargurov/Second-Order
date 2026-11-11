import { useEffect, type CSSProperties, type ReactNode } from "react";
import { useLoad } from "../api";
import {
  MODE_INFO, OUTPUT_LABEL, REVIEW_INFO, modeDetail, noteExcerpt, publicationTimes, reviewDetail, reviewKey,
} from "../analyses";
import { ViewSection } from "../components/EventMarketContext";
import { FindingsBand } from "../components/FindingsBand";
import { RatePath } from "../components/RatePath";
import { RelatedCases } from "../components/RelatedCases";
import { RelatedResearch } from "../components/RelatedResearch";
import { OUTCOME_INFO } from "../drafts";
import type { DraftOutcome } from "../draftTypes";
import {
  HISTORY_STEP, TRIAGE_STATUS, analysisGap, costLine, fetchOverview, historyStatement, marketSummary, originLine,
  overviewHref, researchHref, reviewFromOverview, triageGap, triageProvenance,
  type AnalysisSection, type CaptureSource, type EventOverview, type HistoryRow, type InboxSource, type LinkedCapture,
  type MarketSection, type OverviewKind, type ProcessingHistory, type TriageSection,
} from "../eventOverview";
import { formatUtc } from "../format";
import { textLine, utcStamp } from "../inbox";
import { Link } from "../router";
import "../analyses.css";
import "../library.css";
import "../eventContext.css";
import "../eventOverview.css";
import "../snapshot.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;
const short = (sha: string | null | undefined) => (sha ? sha.slice(0, 12) : "none");

/**
 * The private event overview: an Inbox entry or a saved capture with its source, saved headline triage, draft and
 * review, and market context. It only reads; every action is a link to the existing workflow that performs it.
 */
export function EventOverviewPage({ kind, id }: { kind: OverviewKind; id: string }) {
  const [page, retry] = useLoad((signal) => fetchOverview(kind, id, signal), `overview:${kind}:${id}`);
  useEffect(() => {
    document.title = "Event overview · Second Order";
  }, []);
  const ready = page.state === "ready" ? page.data : null;
  return (
    <article className="event-context overview" data-kind={kind} data-id={id}>
      <header className="event-context-header reveal" style={order(0)}>
        <p className="kicker">Event overview · {kind === "inbox" ? "Event Inbox entry" : "Saved event"}</p>
        <h1>{ready?.title ?? "Event overview"}</h1>
        {ready && <p className="event-context-meaning overview-not-dossier">{ready.not_a_dossier}</p>}
      </header>
      {page.state === "loading" && <p className="event-context-state" role="status">Reading this event's local records…</p>}
      {page.state !== "loading" && page.state !== "ready" && (
        <section className="card" role="alert">
          <p className="event-context-error">This event could not be read: {page.message}</p>
          <p><button className="button" type="button" onClick={retry}>Read it again</button></p>
        </section>
      )}
      {ready && (
        <>
          <nav className="overview-toc" aria-label="Sections of this overview">
            {ready.history && <a href="#overview-history">Processing history</a>}
            <a href="#overview-source">Source</a><a href="#overview-triage">Headline triage</a>
            <a href="#overview-analysis">Draft and review</a>
            {kind === "capture" && <a href="#overview-research-analysis">Research analysis</a>}
            <a href="#overview-market">Market context</a>
            {kind === "capture" && <a href="#overview-rate-path">Market-implied rate path</a>}
            <a href="#overview-findings">Treasury findings</a><a href="#overview-related">Related cases</a>
            <a href="#overview-research">Related research</a>
          </nav>
          {ready.history && <HistoryView history={ready.history} />}
          {ready.source.kind === "inbox" ? <InboxSourceView source={ready.source} />
            : <CaptureSourceView source={ready.source} />}
          <TriageView section={ready.triage} kind={kind} />
          <AnalysisView overview={ready} />
          {kind === "capture" && <ResearchAnalysisLink captureId={id} history={ready.history} />}
          <MarketView section={ready.market} title={ready.title} />
          {kind === "capture" && <RatePath captureId={id} variant="overview" />}
          <FindingsBand kind={kind} id={id} />
          <RelatedCases kind={kind} id={id} />
          <RelatedResearch kind={kind} id={id} />
        </>
      )}
    </article>
  );
}

/** What was done with this event, step by step, from the records each step keeps; each row links to the existing
 * record or page rather than repeating it. */
function HistoryView({ history }: { history: ProcessingHistory }) {
  return (
    <Section id="overview-history" title="Processing history">
      <p className={`overview-history-state is-${history.state}`} data-history={history.state}>
        {historyStatement(history)}</p>
      {history.steps.map(({ step, rows }) => (
        <div key={step} className="overview-history-step" data-step={step}>
          <h3>{HISTORY_STEP[step].title}</h3>
          {rows.length === 0 ? <p className="overview-note">{HISTORY_STEP[step].empty}</p> : (
            <ol className="overview-history-rows">
              {rows.map((row, index) => <HistoryLine key={index} row={row} />)}
            </ol>
          )}
        </div>
      ))}
      <details className="overview-history-limits">
        <summary>What this history cannot show ({history.limitations.length})</summary>
        <ul>{history.limitations.map((limit) => <li key={limit}>{limit}</li>)}</ul>
      </details>
    </Section>
  );
}

function HistoryLine({ row }: { row: HistoryRow }) {
  const internal = row.href !== null && !row.href.startsWith("/api/");
  return (
    <li className={`overview-history-row is-${row.tone}`} data-state={row.state} data-tone={row.tone}>
      <span className="overview-history-when">{row.at ? utcStamp(row.at) : "time not recorded"}</span>
      <span className="overview-history-label">{row.label}{row.current === false && row.step === "source"
        ? " (an earlier version)" : ""}</span>
      {row.detail && <span className="overview-history-detail">{row.detail}</span>}
      {row.cost && <span className="overview-history-cost">{costLine(row.cost)}</span>}
      {row.href && (internal
        ? <Link className="overview-history-link" to={row.href}>Open the record</Link>
        : <a className="overview-history-link" href={row.href} target="_blank" rel="noreferrer">Saved request (JSON)</a>)}
    </li>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="card event-context-section overview-section" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>{title}</h2>
      {children}
    </section>
  );
}

/** An entry imported from the retained BIS snapshot: its provenance, its dates as the listing and the release state
 * them, and the listing's text as plain paragraphs. */
function ImportedSourceView({ source }: { source: InboxSource }) {
  const entry = source.entry!;
  const imported = entry.imported!;
  const record = imported.record;
  const listing = record.listing;
  return (
    <Section id="overview-source" title="Source">
      <p className="overview-label">{imported.label}</p>
      <dl className="ledger overview-facts">
        <div><dt>Headline</dt><dd>{entry.title}</dd></div>
        <div><dt>Publisher</dt><dd>{entry.publisher} · {entry.category} · {entry.kind}
          {record.publisher.topics.length > 0 && ` · BIS topics: ${record.publisher.topics.join(", ")}`}</dd></div>
        <div><dt>Release page</dt><dd><a href={entry.link} target="_blank" rel="noreferrer">{entry.link}</a></dd></div>
        {record.publisher.external_link && (
          <div><dt>Listed as</dt><dd>A page on {record.publisher.external_link.host}:{" "}
            <a href={record.publisher.external_link.url} target="_blank" rel="noreferrer">
              {record.publisher.external_link.url}</a></dd></div>
        )}
        <div><dt>Listing timestamp</dt><dd>{listing.published.time ?? "none"} (BIS listing data, UTC).{" "}
          {entry.feed_timestamp.problem}</dd></div>
        {record.check?.dateline && (
          <div><dt>Release dateline</dt><dd>{record.check.dateline}, as the separately retained release page states it.
            </dd></div>
        )}
        <div><dt>CMS times</dt><dd>Created {listing.created.time ?? "not given"}, updated {listing.changed.time ??
          "not given"}: not publication times, and not used as one.</dd></div>
        <div><dt>Text</dt><dd>{imported.completeness}</dd></div>
        <div><dt>Snapshot</dt><dd>{imported.snapshot.package.url}, retained {utcStamp(imported.snapshot.package.retrieved_at)}
          (approval {imported.snapshot.package.approval_id}), SHA-256 <code>{short(imported.snapshot.package.sha256)}…</code>;
          extractor {imported.snapshot.extractor_version}</dd></div>
        <div><dt>Imported</dt><dd>{utcStamp(imported.imported_at)}, import {imported.import_id}; version{" "}
          {imported.version} of {imported.versions}, content SHA-256 <code>{short(source.content_sha256)}…</code></dd></div>
      </dl>
      {record.text.paragraphs.length > 0 ? (
        <details className="overview-imported-text">
          <summary>Listing text ({record.text.paragraphs.length} paragraphs, plain text)</summary>
          {record.text.paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
        </details>
      ) : <p className="overview-note">The listing gives no text for this record: title and metadata only.</p>}
      <p className="overview-note">{source.note}</p>
    </Section>
  );
}

function InboxSourceView({ source }: { source: InboxSource }) {
  if (source.entry?.imported) return <ImportedSourceView source={source} />;
  const entry = source.entry;
  const stamp = entry?.feed_timestamp;
  const current = source.versions.find((version) => version.current);
  return (
    <Section id="overview-source" title="Source">
      <p className="overview-label">Feed metadata, as the publisher's feed stated it</p>
      {entry ? (
        <dl className="ledger overview-facts">
          <div><dt>Headline</dt><dd>{entry.title}</dd></div>
          <div><dt>Publisher</dt><dd>{entry.publisher} · {entry.category} · {entry.kind}</dd></div>
          <div><dt>Official link</dt><dd><a href={entry.link} target="_blank" rel="noreferrer">{entry.link}</a></dd></div>
          <div><dt>Feed timestamp</dt><dd>{stamp?.raw ?? "none"} ({stamp?.origin}){stamp?.instant_utc
            ? ` = ${utcStamp(stamp.instant_utc)}` : ""}{stamp?.problem ? `. ${stamp.problem}` : ""}</dd></div>
          <div><dt>Held</dt><dd>{source.location === "retained" ? "Retained history: no longer in the latest retrieval"
            : "In the latest retrieval"}; {entry.history ? `last seen ${utcStamp(entry.retrieved_at)}`
            : `retrieved ${utcStamp(entry.retrieved_at)}`}.</dd></div>
          <div><dt>This version</dt><dd>Version {current?.number ?? "?"} of {source.versions.length}, content SHA-256{" "}
            <code>{short(source.content_sha256)}…</code></dd></div>
          <div><dt>Text held</dt><dd className="overview-text-held">{textLine(entry.text, !!source.full_text_element)}</dd></div>
          <div><dt>First retrieved</dt><dd>{utcStamp(entry.first_seen_at)}: when this inbox first saw the entry, not
            when it was published.</dd></div>
        </dl>
      ) : <p className="event-context-error">The entry is no longer in the inbox; its archived versions are listed below.</p>}
      {entry?.excerpt && !entry.excerpt_repeats_title && (
        <p className="overview-excerpt"><span className="overview-label">Feed excerpt, not the published text</span>{" "}
          {entry.excerpt}</p>
      )}
      <p className="overview-note">{source.note}</p>
      {source.versions.length > 1 && (
        <details className="overview-versions">
          <summary>Every archived version ({source.versions.length})</summary>
          <ol>
            {source.versions.map((version) => (
              <li key={version.content_sha256} data-current={version.current ? "true" : "false"}>
                Version {version.number}{version.current ? " (held now)" : ""}: “{version.title}”, seen{" "}
                {utcStamp(version.first_seen_at)} to {utcStamp(version.last_seen_at)}; <code>{short(version.content_sha256)}…</code>
              </li>
            ))}
          </ol>
        </details>
      )}
    </Section>
  );
}

function CaptureSourceView({ source }: { source: CaptureSource }) {
  const origin = source.origin;
  const text = source.source_text;
  return (
    <Section id="overview-source" title="Source">
      <p className="overview-label">Supplied with the saved event by its operator</p>
      <dl className="ledger overview-facts">
        <div><dt>Headline</dt><dd>{source.event.headline}</dd></div>
        <div><dt>Source address</dt><dd><a href={source.event.source_url} target="_blank" rel="noreferrer">
          {source.event.source_url}</a></dd></div>
        <div><dt>Publication time</dt><dd>{source.times.published_at_as_supplied} as supplied (
          {formatUtc(source.times.published_at)}). {source.times.published_at_note}</dd></div>
        <div><dt>Captured</dt><dd>{formatUtc(source.times.captured_at)}. {source.times.captured_at_note}</dd></div>
        <div><dt>Records</dt><dd>Capture <code>{source.id}</code>; captured text {source.source.bytes} bytes, SHA-256{" "}
          <code>{short(source.source.sha256)}…</code>; request SHA-256 <code>{short(source.request.sha256)}…</code>{" "}
          ({source.request.prompt_version}).</dd></div>
      </dl>
      <details className="overview-text">
        <summary>Captured text ({text.length.toLocaleString("en-US")} characters, as supplied; nothing was downloaded)</summary>
        <pre>{text}</pre>
      </details>
      <h3>Inbox origin</h3>
      <p className={`overview-origin is-${origin.state}`} data-origin={origin.state}>{originLine(origin)}</p>
      {origin.state === "verified" && origin.link && (
        <p className="overview-origin-link">
          <Link to={overviewHref("inbox", origin.link.inbox.item_id)}>Open the Inbox entry's overview</Link>{" "}
          <span>({origin.link.statement})</span>
        </p>
      )}
    </Section>
  );
}

function TriageView({ section, kind }: { section: TriageSection; kind: OverviewKind }) {
  const gap = triageGap(section);
  return (
    <Section id="overview-triage" title="Saved headline triage">
      {kind === "capture" && section.state === "results" && (
        <p className="overview-note">The triage of the Inbox entry version this event started from. It classifies the
          feed entry, not the captured text.</p>
      )}
      {gap && <p className="overview-gap" data-gap={section.state}>{gap}</p>}
      {section.modes.map((mode) => (
        <div key={mode.mode} className="overview-triage" data-mode={mode.mode} data-status={mode.status}>
          <p className="overview-label">{mode.mode === "paid" ? "Model response" : "Local simulation"} ·{" "}
            {TRIAGE_STATUS[mode.status]}</p>
          {mode.result ? (
            <dl className="ledger overview-facts">
              <div><dt>Category</dt><dd>{mode.result.category}</dd></div>
              <div><dt>Event type</dt><dd>{mode.result.event_type ?? "Not stated"}</dd></div>
              <div><dt>Summary</dt><dd>{mode.result.summary}</dd></div>
            </dl>
          ) : mode.claim ? <p className="overview-gap">Latest request {mode.claim.triage_id ?? ""}: {mode.claim.state}
            {mode.claim.detail ? `. ${mode.claim.detail}` : ""}</p> : null}
          <p className="overview-note">{mode.mode_note} {triageProvenance(mode)}</p>
          {mode.other_versions_with_results > 0 && (
            <p className="overview-note">{mode.other_versions_with_results} other{" "}
              {mode.other_versions_with_results === 1 ? "version" : "versions"} of this entry{" "}
              {mode.other_versions_with_results === 1 ? "has" : "have"} saved results; they are not shown as this
              version's.</p>
          )}
        </div>
      ))}
      {section.relations.length > 0 && (
        <>
          <h3>Suggested relations</h3>
          <p className="overview-note">Suggestions from one response about entries it compared. They are not proof that
            two entries are the same event, and nothing is merged because of them.</p>
          <ul className="library-points overview-relations">
            {section.relations.map((relation, i) => (
              <li key={i} data-relation={relation.relation}>
                <strong>{relation.label}</strong> with{" "}
                {relation.others.map((other, j) => (
                  <span key={other.item_id}>{j ? ", " : ""}<Link to={overviewHref("inbox", other.item_id)}>
                    {other.title ?? other.item_id}</Link>{other.same_version_held_now ? "" : " (compared at another version)"}</span>
                ))}: {relation.reason} ({relation.mode === "paid" ? "model response" : "local simulation"}{" "}
                {relation.provenance?.triage_id}{relation.scope_checked ? ", checked against its comparison scope"
                  : ", not checked against a comparison scope"}).
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  );
}

function CaptureRow({ row }: { row: LinkedCapture }) {
  const review = row.analysis?.review;
  return (
    <li className="overview-capture" data-capture={row.capture_id}>
      <Link to={overviewHref("capture", row.capture_id)} className="event-context-entry-title">
        {row.headline ?? `Capture ${row.capture_id}`}</Link>
      <p className="overview-note">
        {row.captured_at ? `Captured ${formatUtc(row.captured_at)}. ` : ""}{originLine(row.origin)}
      </p>
      {row.problem && <p className="event-context-error">{row.problem}</p>}
      {row.analysis && (
        <p className="overview-note">
          {row.analysis.outcome ? `${OUTCOME_INFO[row.analysis.outcome as DraftOutcome]?.label ?? row.analysis.outcome}; `
            : `${analysisGap(row.analysis.state, null)} `}
          {review ? REVIEW_INFO[reviewKey(review)].label : ""}
        </p>
      )}
    </li>
  );
}

function AnalysisView({ overview }: { overview: EventOverview }) {
  const section: AnalysisSection = overview.analysis;
  if (overview.kind === "inbox") {
    const captures = section.captures ?? [];
    return (
      <Section id="overview-analysis" title="Draft and human review">
        {captures.length === 0 ? (
          <p className="overview-gap" data-gap="none">No saved event records this entry as its origin, so no draft or
            review is linked. Analyze this event in the Event Inbox on the <Link to="/">Tracker</Link> starts one;
            nothing is captured or sent until you preview and approve it there.</p>
        ) : (
          <>
            <p className="overview-note">Saved events whose capture recorded this entry as its origin. Each is its own
              record, with its own draft and review.</p>
            <ol className="event-context-list overview-captures">{captures.map((row) => <CaptureRow key={row.capture_id} row={row} />)}</ol>
          </>
        )}
        {(section.unreadable_links ?? []).length > 0 && (
          <p className="event-context-error">{section.unreadable_links!.length} origin records cannot be read, so it is not
            known which entries they name: {section.unreadable_links!.join(", ")}. They were left unchanged.</p>
        )}
      </Section>
    );
  }
  const entry = section.entry;
  return (
    <Section id="overview-analysis" title="Draft and human review">
      {entry ? (
        <>
          <div className="analysis-chips">
            <span className={`outcome-chip ${OUTCOME_INFO[entry.outcome].className}`}>{OUTCOME_INFO[entry.outcome].label}</span>
            <span className={`analysis-badge ${MODE_INFO[entry.mode].className}`}>{MODE_INFO[entry.mode].label}</span>
            <span className={`analysis-badge analysis-review-chip ${REVIEW_INFO[reviewKey(entry.review)].className}`}>
              {REVIEW_INFO[reviewKey(entry.review)].label}</span>
          </div>
          <p className="overview-note">{modeDetail(entry)} Sent {formatUtc(entry.provenance.sent_at)}. Published as{" "}
            {publicationTimes(entry).local ?? publicationTimes(entry).utc}.</p>
          <div className="analysis-layers">
            <section className="analysis-layer analysis-layer-model" aria-label="Model output">
              <h3>{OUTPUT_LABEL[entry.model_output.kind]}</h3>
              <p>{entry.model_output.text ?? "No text was recorded."}</p>
            </section>
            <section className="analysis-layer analysis-layer-review" aria-label="Your review">
              <h3>Your review</h3>
              <p>{reviewDetail(entry.review)}</p>
              {noteExcerpt(entry.review) && <blockquote className="analysis-note">{noteExcerpt(entry.review)}</blockquote>}
            </section>
          </div>
          <p className="overview-note">Draft view SHA-256 <code>{short(entry.draft_view_sha256)}…</code>: a review counts
            as current only when it was saved against exactly this view.</p>
          <p className="analysis-actions">
            <Link className="button overview-open-review" to={reviewFromOverview(entry.draft_id, "capture", overview.id)}>
              Open review</Link>
          </p>
        </>
      ) : (
        <p className="overview-gap" data-gap={section.state}>{analysisGap(section.state, section.detail)}</p>
      )}
      {(section.siblings ?? []).length > 0 && (
        <>
          <h3>Other saved events from the same Inbox entry</h3>
          <p className="overview-note">Separate captures with their own drafts and reviews; nothing is shared between them.</p>
          <ol className="event-context-list overview-captures">
            {section.siblings!.map((row) => <CaptureRow key={row.capture_id} row={row} />)}
          </ol>
        </>
      )}
    </Section>
  );
}

/** Where the saved event's evidence-first research analysis lives, and what its history rows say; a link, never an
 * action: preparing or sending happens only on that page, by explicit approval. */
function ResearchAnalysisLink({ captureId, history }: { captureId: string; history?: ProcessingHistory }) {
  const rows = (history?.steps ?? []).flatMap((group) => group.rows).filter((row) => row.kind === "research");
  const results = rows.filter((row) => row.result);
  const line = rows.length === 0 ? "No research request is prepared for this saved event, so there is no research analysis."
    : results.length === 0 ? "A research request is prepared and nothing has been sent; a prepared request is not an analysis."
    : `${results.at(-1)!.label}.`;
  return (
    <Section id="overview-research-analysis" title="Evidence-first research analysis">
      <p className="overview-note">A separate analysis mode with its own request, result and review: what the source
        establishes, quoted and located in the captured text, with any interpretation labelled apart from it. It asks
        for no direction, horizon or trade.</p>
      <p className="overview-gap" data-gap={results.length ? "result" : rows.length ? "prepared" : "none"}>{line}</p>
      <p><Link className="button button-quiet overview-open-research" to={researchHref(captureId)}>
        Open the research analysis</Link></p>
    </Section>
  );
}

function MarketView({ section, title }: { section: MarketSection; title: string }) {
  return (
    <section id="overview-market" className="overview-market" aria-label="Market context" data-state={section.state}>
      <div className="card event-context-section overview-section">
        <h2>Market context</h2>
        <p className={`overview-gap is-${section.state}`} data-gap={section.state}>{marketSummary(section)}</p>
        {section.href && section.state !== "unsupported" && (
          <p><Link className="button button-quiet" to={section.href}>Open its market-context page</Link></p>
        )}
      </div>
      {section.view && <ViewSection view={section.view} title={title} />}
    </section>
  );
}

