import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { Loaded } from "../api";
import {
  NO_FILTER, countsLine, entryLink, fetchInbox, fetchProcessing, filtered, kindNote, linkLabel, officialLink,
  processingLabel, refreshInbox, refreshLines, retrievalLine, sourceStatus, textLine, topics, utcStamp,
  type InboxFilter, type InboxItem, type InboxSource, type InboxView, type ProcessingIndex,
} from "../inbox";
import { COMPLETENESS_SHORT, type Completeness } from "../snapshot";
import { OUTSIDE_SHORT, SUPPORTED_SOURCES, eventHref } from "../eventContext";
import { overviewHref } from "../eventOverview";
import { Link } from "../router";
import { MAX_SELECTION, toggled } from "../triage";
import { HeadlineTriage } from "./HeadlineTriage";
import "../inbox.css";
import "../snapshot.css";

/**
 * The Event Inbox: official releases, energy articles and trade news from five publisher feeds, as last retrieved by
 * an explicit refresh. Loading the page only reads the local cache, and the topic and source filters only narrow what
 * it holds. Choosing an entry fills the Analyze an event form below; nothing is captured, sent or analyzed by
 * browsing, filtering, refreshing or choosing. Selected entries can be triaged (see HeadlineTriage): that too sends
 * nothing until a response is explicitly approved.
 */
export function EventInbox({ busy, onAnalyze, style }: {
  busy: boolean;
  onAnalyze: (item: InboxItem) => void;
  style?: CSSProperties;
}) {
  const [view, setView] = useState<Loaded<InboxView>>({ state: "loading" });
  const [processing, setProcessing] = useState<Loaded<ProcessingIndex>>({ state: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<{ text: string; tone: "done" | "error"; lines: string[] } | null>(null);
  const [selected, setSelected] = useState<string[]>([]);  // Entries checked for headline triage.
  const [showRetained, setShowRetained] = useState(false);
  const [filter, setFilter] = useState<InboxFilter>(NO_FILTER);
  const reads = useRef(0);  // The newest read or refresh; an older reply never replaces a newer one.

  useEffect(() => {
    const token = ++reads.current;
    const controller = new AbortController();
    fetchInbox(controller.signal).then((loaded) => { if (token === reads.current) setView(loaded); }, () => {});
    fetchProcessing(controller.signal).then(setProcessing, () => {});
    return () => controller.abort();
  }, []);

  const refresh = async () => {
    if (refreshing) return;
    const token = ++reads.current;
    setRefreshing(true);
    setMessage(null);
    const result = await refreshInbox();
    setRefreshing(false);
    if (token !== reads.current) return;
    if (result.state !== "done") {
      setMessage({ text: `The refresh did not complete: ${result.message}`, tone: "error", lines: [] });
      return;
    }
    setView({ state: "ready", data: result.view });
    fetchProcessing().then(setProcessing, () => {});  // A refresh processes nothing; this only reads the records again.
    const outcomes = result.view.refreshed ?? [];
    const failed = outcomes.filter((outcome) => outcome.outcome !== "ok").length;
    setMessage({
      text: (failed === 0 ? "Each feed was requested once and its entries were saved locally."
        : `Each feed was requested at most once; ${failed} of ${outcomes.length} sources did not refresh (see each source).`) +
        " Nothing was triaged or analyzed.",
      tone: failed === 0 ? "done" : "error", lines: refreshLines(outcomes, result.view.sources),
    });
  };

  const items = view.state === "ready" ? view.data.items : [];
  const retained = view.state === "ready" ? view.data.retained ?? [] : [];
  const imported = view.state === "ready" ? view.data.imported ?? [] : [];
  const held = useMemo(() => [...items, ...retained], [items, retained]);
  const shown = useMemo(() => filtered(items, filter), [items, filter]);
  const shownRetained = useMemo(() => filtered(retained, filter), [retained, filter]);
  const filtering = filter.topic !== "" || filter.source !== "";
  const hiddenSelected = selected.filter((id) => !shown.some((item) => item.id === id) &&
    !(showRetained && shownRetained.some((item) => item.id === id))).length;
  // An entry that is no longer held, current or retained, leaves the selection too.
  useEffect(() => {
    setSelected((current) => {
      const kept = current.filter((id) => held.some((item) => item.id === id));
      return kept.length === current.length ? current : kept;
    });
  }, [held]);
  const sources = view.state === "ready" ? view.data.sources : [];
  const entry = (item: InboxItem) => (
    <Entry key={item.id} item={item} busy={busy} onAnalyze={onAnalyze} selected={selected.includes(item.id)}
      selectable={selected.includes(item.id) || selected.length < MAX_SELECTION}
      onToggle={() => setSelected((current) => toggled(current, item.id))}
      fullText={sources.some((source) => source.key === item.source && !!source.full_text_element)}
      processing={processing.state === "ready" ? processingLabel(processing.data.items[item.id]) : null} />
  );
  return (
    <section className="card tracker-section event-inbox reveal" style={style} aria-labelledby="event-inbox-title">
      <div className="tracker-section-head">
        <h2 id="event-inbox-title">Event inbox</h2>
        <span className="tracker-count">{view.state === "ready" ? `${items.length} entries` : "Not loaded"} · manual refresh</span>
      </div>
      <p className="card-note">
        Monetary-policy announcements, employment and inflation releases, energy analysis articles and international
        trade news from five official publisher feeds, as retrieved by the last refresh. Only the BLS entries are
        formal statistical releases. Feeds are requested only when you choose Refresh events, never in the background.
        Analyze this event fills the form below with the entry's headline and official link; nothing is captured, sent
        or analyzed until you preview and approve it there. Market context, on Federal Reserve and BLS entries, opens
        daily Treasury yields around the date you confirm; it requests nothing until you approve a request there.
      </p>
      <div className="inbox-actions">
        <button className="button inbox-refresh" type="button" disabled={refreshing} onClick={refresh}>
          {refreshing ? "Refreshing events…" : "Refresh events"}
        </button>
        <span>Requests each of the five feeds once, with no retry.</span>
      </div>
      <p className="inbox-snapshot-link">
        <Link to="/inbox/bis-snapshot">Retained BIS snapshot</Link>: BIS's News &amp; Updates page as retained once on
        approval, not a live feed. Browse its records and choose which to import here; importing is local and free.
      </p>
      {message && (
        <div className={`inbox-message ${message.tone === "done" ? "is-done" : "is-error"}`}
          role={message.tone === "done" ? "status" : "alert"}>
          <p>{message.text}</p>
          {message.lines.length > 0 && <ul className="inbox-refresh-lines">
            {message.lines.map((line) => <li key={line}>{line}</li>)}</ul>}
        </div>
      )}
      {view.state === "loading" && <p className="inbox-state">Reading the local inbox…</p>}
      {view.state !== "loading" && view.state !== "ready" && (
        <p className="inbox-state is-error" role="alert">The inbox could not be read: {view.message}</p>
      )}
      {view.state === "ready" && (
        <>
          <ul className="inbox-sources">
            {view.data.sources.map((source) => <SourceCard key={source.key} source={source} />)}
          </ul>
          <HeadlineTriage current={held} selected={selected} onSelect={setSelected} onClear={() => setSelected([])}
            onAnalyze={onAnalyze} busy={busy} />
          {held.length > 0 && (
            <Filters sources={view.data.sources} filter={filter} onChange={setFilter} shown={shown.length}
              total={items.length} shownRetained={shownRetained.length} retained={retained.length}
              hiddenSelected={hiddenSelected} />
          )}
          {items.length === 0 ? (
            <p className="inbox-state">
              {view.data.sources.every((source) => source.state === "never_refreshed")
                ? "No entries yet: the inbox has never been refreshed. Choose Refresh events to request the feeds."
                : "No entries are held. Each source above says what its latest refresh found."}
            </p>
          ) : shown.length === 0 ? (
            <p className="inbox-state inbox-filter-empty">No current entries match this topic and source.</p>
          ) : (
            <ol className="inbox-items">{shown.map(entry)}</ol>
          )}
          {retained.length > 0 && (
            <div className="inbox-history">
              <button className="button button-quiet inbox-history-toggle" type="button" aria-expanded={showRetained}
                onClick={() => setShowRetained((open) => !open)}>
                {showRetained ? "Hide retained headlines"
                  : `Show retained headlines (${filtering ? `${shownRetained.length} of ${retained.length}` : retained.length})`}
              </button>
              <span>Kept locally after leaving their feeds; nothing is fetched to show them.</span>
              {showRetained && (shownRetained.length === 0
                ? <p className="inbox-state inbox-filter-empty">No retained headlines match this topic and source.</p>
                : <ol className="inbox-items inbox-retained-items">{shownRetained.map(entry)}</ol>)}
            </div>
          )}
          {(imported.length > 0 || (view.data.imports?.unreadable.length ?? 0) > 0) && (
            <div className="inbox-imported" aria-labelledby="inbox-imported-title">
              <h3 id="inbox-imported-title">Imported from a retained snapshot ({imported.length})</h3>
              <p className="inbox-imported-note">{view.data.imports?.statement}</p>
              {view.data.imports?.unreadable.map((entry) => (
                <p key={entry.key} className="inbox-state is-error">{entry.problem}</p>
              ))}
              <ol className="inbox-items inbox-imported-items">
                {imported.map((item) => <ImportedEntry key={item.id} item={item} busy={busy} onAnalyze={onAnalyze} />)}
              </ol>
            </div>
          )}
          <p className="inbox-retention">{view.data.retention.statement}</p>
        </>
      )}
    </section>
  );
}

/** Topic and source filters over the entries already held, current and retained. Changing them requests nothing. */
function Filters({ sources, filter, onChange, shown, total, shownRetained, retained, hiddenSelected }: {
  sources: InboxSource[];
  filter: InboxFilter;
  onChange: (filter: InboxFilter) => void;
  shown: number;
  total: number;
  shownRetained: number;
  retained: number;
  hiddenSelected: number;
}) {
  const active = filter.topic !== "" || filter.source !== "";
  return (
    <div className="inbox-filters">
      <div className="inbox-filter-controls">
        <label className="inbox-filter">
          <span>Topic</span>
          <select name="inbox-topic" value={filter.topic} onChange={(event) => onChange({ ...filter, topic: event.target.value })}>
            <option value="">All topics</option>
            {topics(sources).map((topic) => <option key={topic} value={topic}>{topic}</option>)}
          </select>
        </label>
        <label className="inbox-filter">
          <span>Source</span>
          <select name="inbox-source" value={filter.source} onChange={(event) => onChange({ ...filter, source: event.target.value })}>
            <option value="">All sources</option>
            {sources.map((source) => <option key={source.key} value={source.key}>{source.label}</option>)}
          </select>
        </label>
        {active && (
          <button type="button" className="button button-quiet inbox-filter-reset" onClick={() => onChange(NO_FILTER)}>
            Show all entries
          </button>
        )}
      </div>
      <p className="inbox-filter-count" aria-live="polite">
        {active ? `Showing ${shown} of ${total} current entries and ${shownRetained} of ${retained} retained.`
          : `Showing all ${total} current entries and ${retained} retained.`} Filters read only what is held locally.
        {hiddenSelected > 0 && ` ${hiddenSelected} selected ${hiddenSelected === 1 ? "entry is" : "entries are"} not shown; ` +
          "they stay selected for triage."}
      </p>
    </div>
  );
}

function SourceCard({ source }: { source: InboxSource }) {
  const status = sourceStatus(source);
  const attempt = source.last_attempt;
  const latest = source.acquisitions?.latest ?? null;
  return (
    <li className={`inbox-source is-${status.tone}`} data-source={source.key} data-state={source.state}>
      <div className="inbox-source-head">
        <a href={source.feed_url} target="_blank" rel="noreferrer">{source.label}</a>
        <span className="inbox-source-state">{status.label}</span>
      </div>
      <p className="inbox-source-kind" data-kind={source.kind}>{source.category} · {kindNote(source.kind)}</p>
      <p className="inbox-source-credit">
        {source.publisher} · {source.attribution ? <>credited as “{source.attribution}”, as its </> : null}
        <a href={source.terms_url} target="_blank" rel="noreferrer">{source.attribution ? "terms" : "Terms"}</a>
        {source.attribution ? " ask." : "."}
      </p>
      <p className="inbox-source-detail">
        {source.last_success
          ? `Last successful retrieval ${utcStamp(source.last_success.retrieved_at)}: ${source.last_success.item_count} ` +
            `entries kept of ${source.last_success.listed} listed` +
            `${source.last_success.skipped_count ? `, ${source.last_success.skipped_count} skipped` : ""}.`
          : "No successful retrieval is recorded."}
        {attempt && ` Latest attempt ${utcStamp(attempt.started_at)}: ${attempt.outcome === "ok" ? "succeeded" : attempt.outcome === "not_requested" ? "not requested" : "failed"}.`}
      </p>
      {attempt?.detail && <p className="inbox-source-error">{attempt.detail}</p>}
      {source.problem && <p className="inbox-source-error">{source.problem}</p>}
      {latest && (
        <p className={`inbox-source-retrieval${latest.kept_copy === "differs" || latest.kept_copy === "missing"
          ? " inbox-source-error" : ""}`}>
          {retrievalLine(latest)}{latest.counts ? ` Entries: ${countsLine(latest.counts)}.` : ""}{" "}
          {source.acquisitions!.count} recorded {source.acquisitions!.count === 1 ? "request" : "requests"}.
        </p>
      )}
      {(source.acquisitions?.unreadable_newer ?? []).map((problem) => (
        <p key={problem} className="inbox-source-error">{problem}</p>
      ))}
      {source.archive && source.archive.state !== "missing" && (
        <p className={`inbox-source-archive${source.archive.state === "unreadable" ? " inbox-source-error" : ""}`}>
          {source.archive.state === "ok"
            ? `Local archive: ${source.archive.entries} entries, ${source.archive.versions} versions; ` +
              `${source.archive.retained} no longer in the feed.`
            : `Local archive unreadable and left as it is: ${source.archive.problem}`}
        </p>
      )}
    </li>
  );
}

/** An entry imported from the retained BIS snapshot: never offered for triage or market context; its timestamp is
 * listing metadata, not the release's dateline. */
function ImportedEntry({ item, busy, onAnalyze }: { item: InboxItem; busy: boolean; onAnalyze: (item: InboxItem) => void }) {
  const stamp = item.feed_timestamp;
  const imported = item.imported!;
  return (
    <li className="inbox-item is-imported" data-item={item.id} data-source={item.source} data-kind={item.kind}>
      <p className="inbox-imported-label">{imported.label}</p>
      <h3>{item.title}</h3>
      <p className="inbox-item-meta">
        <span>{item.category}</span> · <span className="inbox-item-kind">{item.kind}</span> · <span>{item.publisher}</span>
        {imported.record.publisher.topics.length > 0 && <> · <span>BIS topics: {imported.record.publisher.topics.join(", ")}</span></>}
        {" · "}{entryLink(item) ? <a href={item.link} target="_blank" rel="noreferrer">Release page on bis.gov</a>
          : <span>No usable link</span>}
      </p>
      <p className="inbox-item-time">
        Listing timestamp ({stamp.origin}): <code>{stamp.raw ?? "none"}</code>. {stamp.problem}
        {imported.record.check?.dateline && ` The separately retained release page states ${imported.record.check.dateline}.`}
      </p>
      {item.excerpt && !item.excerpt_repeats_title && (
        <p className="inbox-item-excerpt"><span>Listing text</span> {item.excerpt}</p>
      )}
      <p className="inbox-item-fresh">
        {COMPLETENESS_SHORT[imported.record.completeness as Completeness] ?? imported.completeness}. Imported{" "}
        {utcStamp(imported.imported_at)}, version {imported.version} of {imported.versions}; snapshot retained{" "}
        {utcStamp(item.retrieved_at)}. Not offered for headline triage.
      </p>
      <div className="inbox-item-actions">
        <button type="button" className="button inbox-analyze" disabled={busy || !entryLink(item)}
          onClick={() => onAnalyze(item)}>Analyze this event</button>
        <span className="inbox-context-outside">Market context is not offered for snapshot records: daily Treasury
          yields are paired only with Federal Reserve monetary-policy and BLS releases.</span>
        <Link className="button button-quiet inbox-overview" to={overviewHref("inbox", item.id)}>Event overview</Link>
      </div>
    </li>
  );
}

function Entry({ item, busy, onAnalyze, selected, selectable, onToggle, fullText, processing }: {
  item: InboxItem;
  busy: boolean;
  onAnalyze: (item: InboxItem) => void;
  selected: boolean;
  selectable: boolean;
  onToggle: () => void;
  fullText: boolean;
  /** What the local records say was done with this entry; null while they are being read or cannot be read. */
  processing: { label: string; tone: string } | null;
}) {
  const stamp = item.feed_timestamp;
  return (
    <li className={`inbox-item${selected ? " is-selected" : ""}${item.history ? " is-retained" : ""}`} data-item={item.id}
      data-source={item.source} data-kind={item.kind}>
      <label className="inbox-select" title={selectable ? undefined : `At most ${MAX_SELECTION} entries can be triaged at once`}>
        <input type="checkbox" checked={selected} disabled={!selectable} onChange={onToggle} /> Select for triage
      </label>
      <h3>{item.title}</h3>
      <p className="inbox-item-meta">
        <span>{item.category}</span> · <span className="inbox-item-kind">{item.kind}</span> · <span>{item.publisher}</span>
        {item.attribution && <> · <span className="inbox-item-credit">credited as “{item.attribution}”</span></>} · {officialLink(item.link)
          ? <a href={item.link} target="_blank" rel="noreferrer">{linkLabel(item.kind)}</a> : <span>No usable link</span>}
      </p>
      <p className="inbox-item-time">
        Feed timestamp ({stamp.origin}): <code>{stamp.raw ?? "none"}</code>
        {stamp.instant_utc ? ` = ${utcStamp(stamp.instant_utc)}` : ""}. Not a verified release time.
        {stamp.problem && <span className="inbox-item-problem"> {stamp.problem}</span>}
      </p>
      {item.excerpt && !item.excerpt_repeats_title && (
        <p className="inbox-item-excerpt"><span>Feed excerpt</span> {item.excerpt}</p>
      )}
      <p className="inbox-item-text">{textLine(item.text, fullText)}</p>
      <p className="inbox-item-fresh">
        {item.history
          ? `Retained history: last seen in its feed ${utcStamp(item.retrieved_at)}, no longer in the latest retrieval.`
          : `Retrieved ${utcStamp(item.retrieved_at)}${item.stale ? " · the latest refresh of this source did not succeed" : ""}.`}
        {` First retrieved ${utcStamp(item.first_seen_at)}: when this inbox first saw it, not when it was published.`}
      </p>
      {processing && <p className={`inbox-item-processing is-${processing.tone}`} data-processing={processing.tone}>
        {processing.label}</p>}
      <div className="inbox-item-actions">
        <button type="button" className="button inbox-analyze" disabled={busy || !officialLink(item.link)}
          onClick={() => onAnalyze(item)}>Analyze this event</button>
        {SUPPORTED_SOURCES.has(item.source)
          ? <Link className="button button-quiet inbox-context" to={eventHref("inbox", item.id)}>Market context</Link>
          : <span className="inbox-context-outside">{OUTSIDE_SHORT}</span>}
        <Link className="button button-quiet inbox-overview" to={overviewHref("inbox", item.id)}>Event overview</Link>
      </div>
    </li>
  );
}
