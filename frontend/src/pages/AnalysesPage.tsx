import { useEffect, type CSSProperties } from "react";
import { fetchAnalyses, useLoad, type Loaded } from "../api";
import { fetchDraftLinks, linkForDraft, type DraftLink } from "../assessment";
import {
  MODE_INFO, MODE_ORDER, captureOverviewHref, OUTCOME_ORDER, OUTPUT_LABEL, REVIEW_INFO, REVIEW_ORDER, analysesHref, excerpt, facetCounts,
  filterAnalyses, modeDetail, noteExcerpt, publicationTimes, readAnalysesFilters, reviewDetail, reviewHref, reviewKey,
  sourceLink,
  type AnalysesFilters, type AnalysesLibrary, type AnalysisEntry, type UnreadableRecord,
} from "../analyses";
import { OUTCOME_INFO } from "../drafts";
import type { DraftOutcome } from "../draftTypes";
import { formatUtc } from "../format";
import { hypothesisHref } from "../lifecycle";
import { Link, navigate } from "../router";
import "../drafts.css";
import "../analyses.css";

const order = (i: number) => ({ "--i": i }) as CSSProperties;
const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

/**
 * My analyses: the Tracker's analyses with a published review view, searchable and filterable. The browsing state
 * lives in the address (?q=&outcome=&mode=&review=), replaced as it changes, so a reload, Back from a review or the
 * review screen's own link back restores it. Everything is filtered locally; the page only reads.
 */
export function AnalysesPage({ search }: { search: string }) {
  const [library, retry] = useLoad(fetchAnalyses, "analyses");
  useEffect(() => {
    document.title = "My analyses · Second Order";
  }, []);
  return (
    <article className="analyses">
      <header className="analyses-header reveal" style={order(0)}>
        <p className="kicker">My analyses</p>
        <h1>Events you analyzed, and where each review stands</h1>
        <p className="lede">
          Each analysis from Analyze an event that has a published review view: what the model returned, the response
          mode that produced it, and your saved review. Private and local, read from this computer's saved records and
          kept apart from the editorial Case library.
        </p>
        <p className="analyses-meaning">
          “Human-reviewed” records that a person reviewed the content. It does not confirm a mechanism, make a draft
          research evidence, show that a forecast succeeded or recommend a trade. Nothing here freezes, evaluates or
          scores; an analysis frozen on the Hypotheses page says so, read from its freeze record.
        </p>
      </header>
      <section className="card analyses-index reveal" style={order(1)} aria-label="Analyses">
        {library.state === "ready" ? <Browser library={library.data} filters={readAnalysesFilters(search)} />
          : <Unloaded library={library} onRetry={retry} />}
      </section>
    </article>
  );
}

function Unloaded({ library, onRetry }: { library: Loaded<AnalysesLibrary>; onRetry: () => void }) {
  if (library.state === "loading") return <p className="analyses-state" role="status">Loading your analyses…</p>;
  return (
    <div className="analyses-state" role="alert">
      <p>Your analyses could not be loaded. {"message" in library ? library.message : ""}</p>
      <button type="button" className="button" onClick={onRetry}>Try again</button>
    </div>
  );
}

function Browser({ library, filters }: { library: AnalysesLibrary; filters: AnalysesFilters }) {
  const { entries, damaged } = library;
  const [links] = useLoad(fetchDraftLinks, "draft-links");  // Freezes, from verified freeze records only.
  const shown = filterAnalyses(entries, filters);
  const update = (change: Partial<AnalysesFilters>) =>
    navigate(analysesHref({ ...filters, ...change }), { replace: true });
  const clear = () => update({ query: "", outcome: null, mode: null, review: null });
  const filtered = filters.query.trim() !== "" || filters.outcome !== null || filters.mode !== null ||
    filters.review !== null;
  const counts = { outcome: facetCounts(entries, filters, "outcome"), mode: facetCounts(entries, filters, "mode"),
                   review: facetCounts(entries, filters, "review") };
  return (
    <>
      {entries.length === 0 ? (
        <div className="analyses-empty">
          <p className="analyses-empty-title">{damaged.length ? "No analysis could be shown." : "No analyses yet."}</p>
          <p>
            Analyze an event on the <Link to="/">Tracker</Link>. Once its response is recorded and published for review,
            it is listed here with its outcome, response mode and review status.
          </p>
        </div>
      ) : (
        <>
          <div className="analyses-controls">
            <label className="analyses-search" htmlFor="analyses-search">
              <span>Search headlines, source addresses, model output and your latest notes</span>
              <input id="analyses-search" type="search" value={filters.query} autoComplete="off" spellCheck={false}
                placeholder="For example: payrolls, refusal, second leg"
                onChange={(event) => update({ query: event.target.value })} />
            </label>
            <div className="analyses-filters">
              <Filter label="Outcome" name="outcome" value={filters.outcome} counts={counts.outcome}
                all="All outcomes" options={OUTCOME_ORDER.map((key) => [key, OUTCOME_INFO[key].label])}
                onChange={(value) => update({ outcome: value as DraftOutcome | null })} />
              <Filter label="Response mode" name="mode" value={filters.mode} counts={counts.mode} all="All modes"
                options={MODE_ORDER.map((key) => [key, MODE_INFO[key].label])}
                onChange={(value) => update({ mode: value as AnalysesFilters["mode"] })} />
              <Filter label="Review status" name="review" value={filters.review} counts={counts.review}
                all="All review states" options={REVIEW_ORDER.map((key) => [key, REVIEW_INFO[key].label])}
                onChange={(value) => update({ review: value as AnalysesFilters["review"] })} />
            </div>
          </div>
          <div className="analyses-results-head">
            <p className="analyses-result-count" role="status" aria-live="polite">
              {shown.length === entries.length ? `Showing all ${plural(entries.length, "analysis", "analyses")}`
                : `Showing ${shown.length} of ${plural(entries.length, "analysis", "analyses")}`}
              {filters.query.trim() ? ` matching “${filters.query.trim()}”` : ""}, most recently sent first.
            </p>
            {filtered && (
              <button type="button" className="button button-quiet analyses-reset" onClick={clear}>
                Clear search and filters
              </button>
            )}
          </div>
          {damaged.length > 0 && (
            <p className="analyses-unreadable-note">
              {plural(damaged.length, "record", "records")} could not be read; {damaged.length === 1 ? "it is" : "they are"}{" "}
              listed after the analyses, with the reason.
            </p>
          )}
          {shown.length > 0 ? (
            <ol className="analysis-list">
              {shown.map((entry) => <AnalysisCard key={entry.draft_id} entry={entry} filters={filters}
                frozen={links.state === "ready" ? linkForDraft(links.data, entry.draft_id) : null} />)}
            </ol>
          ) : (
            <div className="analyses-empty">
              <p className="analyses-empty-title">No analysis matches this search and these filters.</p>
              <button type="button" className="button analyses-reset" onClick={clear}>Show all analyses</button>
            </div>
          )}
        </>
      )}
      {damaged.length > 0 && <Unreadable records={damaged} />}
      <NotListed library={library} />
    </>
  );
}

function Filter({ label, name, value, counts, all, options, onChange }: {
  label: string;
  name: string;
  value: string | null;
  counts: Record<string, number>;
  all: string;
  options: [string, string][];
  onChange: (value: string | null) => void;
}) {
  return (
    <label className="analyses-filter">
      <span>{label}</span>
      <select name={name} value={value ?? ""} onChange={(event) => onChange(event.target.value || null)}>
        <option value="">{all} ({counts.all})</option>
        {options.map(([key, text]) => <option key={key} value={key}>{text} ({counts[key] ?? 0})</option>)}
      </select>
    </label>
  );
}

function AnalysisCard({ entry, filters, frozen }: {
  entry: AnalysisEntry; filters: AnalysesFilters; frozen: DraftLink | null;
}) {
  const outcome = OUTCOME_INFO[entry.outcome];
  const mode = MODE_INFO[entry.mode];
  const review = REVIEW_INFO[reviewKey(entry.review)];
  const times = publicationTimes(entry);
  const link = sourceLink(entry.event.source_url);
  const output = excerpt(entry.model_output.text);
  const href = reviewHref(entry, filters);
  const current = entry.review.state === "current" ? entry.review : null;
  const note = noteExcerpt(entry.review);
  return (
    <li className="analysis-card" data-draft={entry.draft_id}>
      <div className="analysis-chips">
        <span className={`outcome-chip ${outcome.className}`}>{outcome.label}</span>
        <span className={`analysis-badge ${mode.className}`}>{mode.label}</span>
        <span className={`analysis-badge analysis-review-chip ${review.className}`}>{review.label}</span>
      </div>
      <h2 className="analysis-title"><Link to={href}>{entry.event.headline}</Link></h2>
      <dl className="analysis-facts">
        <div>
          <dt>Published</dt>
          <dd>
            {times.local ? <>{times.local} <span className="analysis-utc">· {times.utc}</span></>
              : <>{times.utc} <span className="analysis-utc">(the time as supplied has no recorded offset)</span></>}
          </dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>
            {link ? <a href={link.href} target="_blank" rel="noreferrer noopener" className="analysis-source">{link.label}</a>
              : <code className="analysis-source">{entry.event.source_url || "not recorded"}</code>}
          </dd>
        </div>
        <div><dt>Response</dt><dd>{modeDetail(entry)} Sent {formatUtc(entry.provenance.sent_at)}.</dd></div>
      </dl>
      <div className="analysis-layers">
        <section className="analysis-layer analysis-layer-model" aria-label="Model output">
          <h3>{OUTPUT_LABEL[entry.model_output.kind]}</h3>
          <p>{output ?? "No text was recorded."}</p>
        </section>
        <section className="analysis-layer analysis-layer-review" aria-label="Your review">
          <h3>Your review</h3>
          <p>{reviewDetail(entry.review)}</p>
          {note && <blockquote className="analysis-note" aria-label="Your latest note">{note}</blockquote>}
          {current && current.corrected_fields > 0 && (
            <p className="analysis-corrections">
              Corrects {plural(current.corrected_fields, "field", "fields")} of the model's proposal.
            </p>
          )}
        </section>
      </div>
      <p className="analysis-actions">
        <Link to={href} className="button">Open review</Link>
        <Link to={captureOverviewHref(entry)} className="button button-quiet analysis-overview">Event overview</Link>
        {frozen && <Link to={hypothesisHref(frozen.hypothesis_id)} className="button button-quiet analysis-frozen">
          Frozen as hypothesis {frozen.hypothesis_id.slice(0, 12)}</Link>}
      </p>
    </li>
  );
}

function Unreadable({ records }: { records: UnreadableRecord[] }) {
  return (
    <section className="analyses-unreadable" aria-labelledby="analyses-unreadable-title">
      <h2 id="analyses-unreadable-title">Records that could not be read ({records.length})</h2>
      <p>
        Listed so that nothing disappears silently. They are reported, never repaired, and no review status is shown
        for them.
      </p>
      <ul>
        {records.map((item, i) => (
          <li key={`${item.capture_id ?? "none"}-${item.draft_id ?? "none"}-${i}`}>
            <p className="analysis-ids">
              {item.capture_id ? `Capture ${item.capture_id}` : "No capture is stated"}
              {item.draft_id ? ` · view ${item.draft_id.slice(0, 12)}…` : ""}
            </p>
            <p>{item.problem}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function NotListed({ library }: { library: AnalysesLibrary }) {
  const { none, incomplete, awaiting_publication: awaiting } = library.not_listed.saved_events;
  const prepared = library.not_listed.prepared_drafts;
  const waiting = none + incomplete + awaiting;
  if (waiting === 0 && !prepared) return null;
  const reasons = [none && plural(none, "not sent", "not sent"), incomplete && `${incomplete} with an unfinished attempt`,
                   awaiting && `${awaiting} awaiting publication`].filter(Boolean).join(", ");
  return (
    <aside className="analyses-not-listed" aria-label="Not listed here">
      <h2>Not listed here</h2>
      <ul>
        {waiting > 0 && (
          <li>
            {plural(waiting, "saved event has", "saved events have")} no published review view yet ({reasons}). They
            stay under Saved events in Analyze an event on the <Link to="/">Tracker</Link>.
          </li>
        )}
        {prepared ? (
          <li>
            {plural(prepared, "prepared pilot draft is", "prepared pilot drafts are")} listed under Drafts for review on
            the Tracker. They come from offline pilot runs, not from Analyze an event.
          </li>
        ) : null}
      </ul>
    </aside>
  );
}
