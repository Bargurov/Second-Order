import { useEffect, useMemo, useState } from "react";
import type { Loaded } from "../api";
import { useLoad } from "../api";
import { overviewHref } from "../eventOverview";
import { utcStamp } from "../inbox";
import { Link } from "../router";
import {
  COMPLETENESS_SHORT, DEFAULT_FILTER, IMPORT_SHORT, fetchRecord, fetchSnapshot, filteredRows, openSnapshot,
  previewImport, runImport, toggledKey, type ImportResult, type Preview, type RecordView, type SnapshotFilter,
  type SnapshotRow, type SnapshotView,
} from "../snapshot";
import "../inbox.css";
import "../snapshot.css";

const PAGE = 25;
const short = (sha: string) => sha.slice(0, 12);
const PREVIEW_HEADS = { new: "New: will be added", existing: "Already imported: reused, nothing written",
  changed: "Changed since imported: choose what to do", unusable: "Unusable: not imported" } as const;

/**
 * The retained BIS snapshot: open it, browse and inspect its records, select some, preview what importing them would
 * do, and import them into the Event Inbox. Everything is local and free; nothing outside this server is requested,
 * and nothing is classified, summarized or analyzed.
 */
export function SnapshotPage() {
  const [loaded, retry] = useLoad((signal) => fetchSnapshot(signal), "bis-snapshot");
  const [view, setView] = useState<SnapshotView | null>(null);
  const [message, setMessage] = useState<{ text: string; tone: "done" | "error" } | null>(null);
  const [opening, setOpening] = useState(false);
  useEffect(() => { document.title = "Retained BIS snapshot · Second Order"; }, []);
  useEffect(() => { if (loaded.state === "ready") setView(loaded.data); }, [loaded]);

  const open = async () => {
    if (opening) return;
    setOpening(true);
    setMessage(null);
    const result = await openSnapshot();
    setOpening(false);
    if (result.state !== "done") {
      setMessage({ text: `The snapshot was not opened: ${result.message}`, tone: "error" });
      return;
    }
    setView(result.data);
    setMessage({ text: result.data.opened === "built"
      ? "The retained page verified against its acquisition record; its local index was built and will be reused."
      : "The retained page verified against its acquisition record; its existing local index was reused.", tone: "done" });
  };

  if (!view) {
    return (
      <section className="state-panel snapshot-page">
        {loaded.state === "loading" ? <p>Reading the retained snapshot…</p>
          : <><p className="inbox-state is-error" role="alert">The snapshot could not be read:{" "}
            {(loaded as Exclude<Loaded<SnapshotView>, { state: "loading" | "ready" }>).message}</p>
            <button type="button" className="button" onClick={retry}>Try again</button></>}
      </section>
    );
  }
  return (
    <article className="snapshot-page">
      <nav className="library-crumbs" aria-label="Event inbox"><Link to="/">← Event inbox</Link></nav>
      <header className="snapshot-head">
        <p className="kicker">Event inbox · retained snapshot</p>
        <h1>{view.label}</h1>
        <p className="lede">{view.statement}</p>
        <ul className="snapshot-labels" aria-label="What this page is">
          <li>Retained snapshot, not a live feed</li><li>Local and free</li><li>Nothing is requested</li>
          <li>No model reads these records</li>
        </ul>
      </header>
      {message && <p className={`inbox-message ${message.tone === "done" ? "is-done" : "is-error"}`}
        role={message.tone === "done" ? "status" : "alert"}>{message.text}</p>}
      {(view.state === "unavailable" || view.state === "refused") && (
        <p className="inbox-state is-error snapshot-problem" role="alert">{view.problem}</p>
      )}
      {view.package && <SourceLedger view={view} />}
      {view.state === "not_opened" && (
        <div className="card snapshot-open">
          <p>Opening checks the retained page against its acquisition record once more, then reads its embedded
            listing data into a local index (built once, reused afterwards). Nothing is requested and nothing enters the
            Event Inbox until you import records.</p>
          <button type="button" className="button" disabled={opening} onClick={open}>
            {opening ? "Opening…" : "Open the retained snapshot"}
          </button>
        </div>
      )}
      {view.state === "open" && <Records view={view} onView={setView} />}
    </article>
  );
}

function SourceLedger({ view }: { view: SnapshotView }) {
  const pkg = view.package!;
  return (
    <dl className="ledger snapshot-source">
      <div><dt>Retained page</dt><dd><a href={pkg.url} target="_blank" rel="noreferrer">{pkg.url}</a> (not opened from
        here: this page reads the retained copy only)</dd></div>
      <div><dt>Retained</dt><dd>{utcStamp(pkg.retrieved_at)}, one request on approval {pkg.approval_id}</dd></div>
      <div><dt>Integrity</dt><dd>{pkg.bytes.toLocaleString("en-US")} bytes, SHA-256 <code>{pkg.sha256}</code>, verified
        against its acquisition record on this read</dd></div>
      {view.index && (
        <div><dt>Local index</dt><dd>{view.index.extractor_version}, built {utcStamp(view.index.built_at)};{" "}
          {view.index.release_pages.filter((page) => page.verified).length} separately retained release page(s) used
          to check text</dd></div>
      )}
    </dl>
  );
}

function Records({ view, onView }: { view: SnapshotView; onView: (view: SnapshotView) => void }) {
  const [filter, setFilter] = useState<SnapshotFilter>(DEFAULT_FILTER);
  const [shown, setShown] = useState(PAGE);
  const [selected, setSelected] = useState<string[]>([]);
  const [inspected, setInspected] = useState<string | null>(null);
  const rows = useMemo(() => filteredRows(view.rows, filter), [view.rows, filter]);
  const counts = view.counts!;
  const topics = Object.keys(counts.topics);
  const change = (next: Partial<SnapshotFilter>) => { setFilter({ ...filter, ...next }); setShown(PAGE); };
  const byKey = useMemo(() => new Map(view.rows.map((row) => [row.key, row])), [view.rows]);
  return (
    <>
      <p className="snapshot-summary">
        {counts.listed} records in the listing data: {counts.usable} usable, each a distinct press-release address,
        and {counts.unusable} unusable. {counts.completeness.checked + counts.completeness.checked_differs} checked
        against a separately retained release page, {counts.completeness.listing_text} with listing text that was not
        checked, {counts.completeness.title_only} title only. {counts.dates.listed} have a listing timestamp,{" "}
        {counts.dates.missing} none{counts.dates.ambiguous ? `, ${counts.dates.ambiguous} an inconsistent one` : ""}.{" "}
        {counts.external_links} point to another publisher's page; {counts.same_title_records} share a title with
        another record and stay separate documents.
      </p>
      <div className="inbox-filters snapshot-filters">
        <div className="inbox-filter-controls">
          <label className="inbox-filter snapshot-search"><span>Search</span>
            <input type="search" name="snapshot-query" value={filter.query} placeholder="Title or opening text"
              onChange={(event) => change({ query: event.target.value })} /></label>
          <label className="inbox-filter"><span>Keyword filter</span>
            <select name="snapshot-filter" value={filter.filter}
              onChange={(event) => change({ filter: event.target.value as SnapshotFilter["filter"] })}>
              <option value="semiconductors">{view.filters.semiconductors} ({counts.filters.semiconductors})</option>
              <option value="export_controls">{view.filters.export_controls} ({counts.filters.export_controls})</option>
              <option value="all">All records ({counts.usable})</option>
            </select></label>
          <label className="inbox-filter"><span>BIS topic</span>
            <select name="snapshot-topic" value={filter.topic} onChange={(event) => change({ topic: event.target.value })}>
              <option value="">Any topic</option>
              {topics.map((topic) => <option key={topic} value={topic}>{topic} ({counts.topics[topic]})</option>)}
            </select></label>
          <label className="inbox-filter"><span>Text</span>
            <select name="snapshot-text" value={filter.text}
              onChange={(event) => change({ text: event.target.value as SnapshotFilter["text"] })}>
              <option value="any">Any</option><option value="with_text">With text</option>
              <option value="title_only">Title only</option>
            </select></label>
          <label className="inbox-filter"><span>In the Inbox</span>
            <select name="snapshot-state" value={filter.state}
              onChange={(event) => change({ state: event.target.value as SnapshotFilter["state"] })}>
              <option value="any">Any</option><option value="new">Not imported</option>
              <option value="imported">Imported</option>
            </select></label>
        </div>
        <p className="inbox-filter-count" aria-live="polite">
          {rows.length} of {counts.usable} records match. {view.filters_note} Filters and search read only what the
          local index holds.
        </p>
      </div>
      {rows.length === 0 ? <p className="inbox-state inbox-filter-empty">No records match these filters.</p> : (
        <ol className="inbox-items snapshot-rows">
          {rows.slice(0, shown).map((row) => (
            <SnapshotEntry key={row.key} row={row} completeness={view.completeness_labels[row.completeness]}
              selected={selected.includes(row.key)}
              selectable={selected.includes(row.key) || selected.length < view.selection_limit}
              onToggle={() => setSelected((current) => toggledKey(current, row.key, view.selection_limit))}
              inspected={inspected === row.key}
              onInspect={() => setInspected((current) => current === row.key ? null : row.key)} />
          ))}
        </ol>
      )}
      {selected.length > 0 && (
        <div className="snapshot-selection-bar" role="status">
          <span>{selected.length} of at most {view.selection_limit} selected</span>
          <a href="#snapshot-import-title">Preview the import ↓</a>
        </div>
      )}
      {rows.length > shown && (
        <button type="button" className="button button-quiet snapshot-more" onClick={() => setShown(shown + PAGE)}>
          Show {Math.min(PAGE, rows.length - shown)} more of {rows.length - shown}
        </button>
      )}
      <ImportPanel selected={selected} byKey={byKey} limit={view.selection_limit} onClear={() => setSelected([])}
        onImported={async () => { const fresh = await fetchSnapshot(); if (fresh.state === "ready") onView(fresh.data); }} />
    </>
  );
}

function SnapshotEntry({ row, completeness, selected, selectable, onToggle, inspected, onInspect }: {
  row: SnapshotRow; completeness: string; selected: boolean; selectable: boolean; onToggle: () => void;
  inspected: boolean; onInspect: () => void;
}) {
  return (
    <li className={`inbox-item snapshot-entry${selected ? " is-selected" : ""}`} data-key={row.key}
      data-import={row.import.state}>
      <label className="inbox-select">
        <input type="checkbox" checked={selected} disabled={!selectable} onChange={onToggle} /> Select to import
      </label>
      <h3>{row.title}</h3>
      <p className="inbox-item-meta">
        <span>{row.date ? `Listed ${row.date} (UTC)` : row.date_state === "missing" ? "No listing date" : "Listing date inconsistent"}</span>
        {row.topics.length > 0 && <> · <span>BIS topics: {row.topics.join(", ")}</span></>}
        {row.external_host && <> · <span>Listed as a page on {row.external_host}</span></>}
        {" · "}<span className={`snapshot-text is-${row.completeness}`} title={completeness}>
          {COMPLETENESS_SHORT[row.completeness]}</span>
        {" · "}<span className={`snapshot-state is-${row.import.state}`}>{IMPORT_SHORT[row.import.state]}</span>
      </p>
      {(row.filters.semiconductors || row.filters.export_controls) && (
        <p className="snapshot-tags">Keyword filter: {[row.filters.semiconductors && "semiconductors and advanced " +
          "computing", row.filters.export_controls && "export-control terms"].filter(Boolean).join("; ")}</p>
      )}
      {row.opening && <p className="inbox-item-excerpt"><span>Listing text</span> {row.opening}</p>}
      {row.same_title > 0 && <p className="snapshot-note">{row.same_title} other record(s) share this title; each is
        a separate document at its own address and is never merged with this one.</p>}
      <div className="inbox-item-actions">
        <button type="button" className="button button-quiet snapshot-inspect" aria-expanded={inspected}
          onClick={onInspect}>{inspected ? "Close" : "Inspect"}</button>
        {row.import.state !== "new" && <Link className="button button-quiet" to={overviewHref("inbox", row.id)}>
          Event overview</Link>}
      </div>
      {inspected && <RecordDetail rowKey={row.key} />}
    </li>
  );
}

function RecordDetail({ rowKey }: { rowKey: string }) {
  const [loaded] = useLoad((signal) => fetchRecord(rowKey, signal), `bis-record:${rowKey}`);
  if (loaded.state === "loading") return <p className="inbox-state">Reading the record…</p>;
  if (loaded.state !== "ready") return <p className="inbox-state is-error" role="alert">{loaded.message}</p>;
  const { record, package: pkg } = loaded.data as RecordView;
  const listing = record.listing;
  return (
    <div className="snapshot-detail" data-detail={rowKey}>
      <dl className="ledger snapshot-facts">
        <div><dt>Address</dt><dd><a href={record.identity} target="_blank" rel="noreferrer">{record.identity}</a></dd></div>
        {record.publisher.external_link && <div><dt>Listed as</dt><dd>A page on {record.publisher.external_link.host}:{" "}
          <a href={record.publisher.external_link.url} target="_blank" rel="noreferrer">
            {record.publisher.external_link.url}</a></dd></div>}
        <div><dt>Listing timestamp</dt><dd>{listing.published.time ?? "none"}{listing.published.problem
          ? `. ${listing.published.problem}` : ". BIS's listing data, UTC: listing metadata, not the release's dateline."}</dd></div>
        <div><dt>Release dateline</dt><dd>{record.check?.dateline
          ? `${record.check.dateline}, as the separately retained release page states it.`
          : "Not in the listing data; no release page was retained for this record."}</dd></div>
        <div><dt>CMS times</dt><dd>Created {listing.created.time ?? "not given"}, updated {listing.changed.time ??
          "not given"}. Not publication times, and never used as one.</dd></div>
        <div><dt>Publisher fields</dt><dd>Topics: {record.publisher.topics.join(", ") || "none"}; country tags:{" "}
          {record.publisher.countries.join(", ") || "none"}{record.publisher.summary ? `; summary: ${record.publisher.summary}` : ""}</dd></div>
        <div><dt>Text</dt><dd>{loaded.data.completeness}{record.check?.result === "identical"
          ? " The listing omits the release page's dateline header." : record.check?.note ? ` ${record.check.note}` : ""}
          {record.text.truncated ? " The text was cut at the extractor's bounds." : ""}</dd></div>
        <div><dt>Provenance</dt><dd>Record {record.position} of the listing data in snapshot <code>{short(pkg.sha256)}…</code>;
          document {record.document.uuid ?? "without a valid UUID"}; source version <code>{short(record.record_sha256)}…</code></dd></div>
        {record.same_title.length > 0 && <div><dt>Same title</dt><dd>{record.same_title.map((other) =>
          `${other.path} (${other.date ?? "no listing date"}, ${other.relation})`).join("; ")}</dd></div>}
        {record.notes.length > 0 && <div><dt>Notes</dt><dd>{record.notes.join(" ")}</dd></div>}
      </dl>
      {record.text.paragraphs.length > 0 ? (
        <div className="snapshot-paragraphs" aria-label="The listing's text, as plain text">
          {record.text.paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
        </div>
      ) : <p className="inbox-state">The listing data gives no text for this record.</p>}
    </div>
  );
}

function ImportPanel({ selected, byKey, limit, onClear, onImported }: {
  selected: string[]; byKey: Map<string, SnapshotRow>; limit: number; onClear: () => void;
  onImported: () => Promise<void>;
}) {
  const [preview, setPreview] = useState<{ keys: string[]; data: Preview } | null>(null);
  const [decisions, setDecisions] = useState<Record<string, "keep" | "add_version">>({});
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const current = preview && preview.keys.join() === selected.join() ? preview.data : null;
  const changed = current?.rows.filter((row) => row.state === "changed") ?? [];
  const undecided = changed.filter((row) => !decisions[row.key]).length;
  const writes = (current?.counts.new ?? 0) + changed.filter((row) => decisions[row.key] === "add_version").length;

  const ask = async () => {
    setBusy(true); setProblem(null); setResult(null);
    const sent = await previewImport(selected);
    setBusy(false);
    if (sent.state !== "done") { setProblem(sent.message); return; }
    setPreview({ keys: [...selected], data: sent.data });
    setDecisions({});
  };
  const run = async () => {
    if (busy || !current) return;
    setBusy(true); setProblem(null);
    const sent = await runImport(selected, decisions);
    setBusy(false);
    if (sent.state !== "done") { setProblem(sent.message); return; }
    setResult(sent.data);
    setPreview(null);
    await onImported();
  };
  return (
    <section className="card snapshot-import" aria-labelledby="snapshot-import-title">
      <h2 id="snapshot-import-title">Import into the Event Inbox</h2>
      <p className="card-note">Local and free: importing writes the selected records into this machine's Event Inbox.
        Nothing is requested, sent, classified, summarized or analyzed, and an imported record's claims are not verified
        by importing it. Records already imported are reused, never duplicated or replaced.</p>
      <p className="snapshot-selection" aria-live="polite">
        {selected.length} of at most {limit} selected{selected.length > 0 && `: ${selected.map((key) =>
          byKey.get(key)?.title ?? key).join("; ")}`}.
      </p>
      <div className="inbox-actions">
        <button type="button" className="button snapshot-preview" disabled={busy || selected.length === 0} onClick={ask}>
          {busy && !current ? "Previewing…" : "Preview import"}</button>
        {selected.length > 0 && <button type="button" className="button button-quiet" disabled={busy} onClick={() => {
          onClear(); setPreview(null); }}>Clear selection</button>}
      </div>
      {problem && <p className="inbox-message is-error" role="alert">{problem}</p>}
      {current && (
        <div className="snapshot-preview-result">
          {(Object.keys(PREVIEW_HEADS) as (keyof typeof PREVIEW_HEADS)[]).filter((state) => current.counts[state] > 0)
            .map((state) => (
              <div key={state} className={`snapshot-group is-${state}`} data-group={state}>
                <h3>{PREVIEW_HEADS[state]} ({current.counts[state]})</h3>
                <ul>
                  {current.rows.filter((row) => row.state === state).map((row) => (
                    <li key={row.key}>
                      <strong>{row.title ?? row.id}</strong>
                      {row.reasons.length > 0 && <> {row.reasons.join(" ")}</>}
                      {row.state === "changed" && (
                        <fieldset className="snapshot-decision">
                          <legend>Changed: {row.changed?.join(", ")}. Version {row.version} is held.</legend>
                          <label><input type="radio" name={`decision-${row.key}`} checked={decisions[row.key] === "keep"}
                            onChange={() => setDecisions({ ...decisions, [row.key]: "keep" })} /> Keep the held version</label>
                          <label><input type="radio" name={`decision-${row.key}`}
                            checked={decisions[row.key] === "add_version"}
                            onChange={() => setDecisions({ ...decisions, [row.key]: "add_version" })} /> Add this as
                            version {(row.version ?? 0) + 1}, beside the held one</label>
                        </fieldset>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          <p className="card-note">{current.cost}</p>
          <button type="button" className="button snapshot-run" disabled={busy || undecided > 0 || writes === 0}
            onClick={run}>
            {busy ? "Importing…" : writes === 0 ? "Nothing new to import"
              : `Import ${writes} record${writes === 1 ? "" : "s"} into the Event Inbox (local, $0)`}</button>
          {undecided > 0 && <p className="inbox-state">Choose what to do with each changed record first.</p>}
        </div>
      )}
      {result && (
        <div className="snapshot-result" role="status">
          <p className="inbox-message is-done">
            {result.written ? `Import ${result.import_id} recorded at ${utcStamp(result.imported_at)}: ` : "Nothing was written: "}
            {result.counts.added} added, {result.counts.version_added} new version(s), {result.counts.reused} reused,{" "}
            {result.counts.kept} kept as held, {result.counts.unusable} unusable
            {result.counts.conflict ? `, ${result.counts.conflict} left as another import wrote them` : ""}. {result.cost}
          </p>
          <ul>
            {result.rows.filter((row) => row.outcome !== "unusable").map((row) => (
              <li key={row.key}><Link to={overviewHref("inbox", row.id)}>{row.title ?? row.id}</Link> · {row.outcome}</li>
            ))}
          </ul>
          <p><Link to="/">Back to the Event inbox</Link>, where imported records are listed apart from the feeds.</p>
        </div>
      )}
    </section>
  );
}
