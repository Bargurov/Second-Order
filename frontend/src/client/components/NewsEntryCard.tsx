import type { Interest, NewsEntry, NewsSource, Topic } from "../../contracts/news.ts";
import { Link } from "../../router";
import { publishedText, retrievedText } from "../newsView.ts";
import { href } from "../paths.ts";
import type { Notice } from "../refusals.ts";
import { NoticeView } from "./NoticeView";

const basisText = (topic: Topic): string => topic.basis === "source" ? "this feed's topic"
  : `found by ${topic.terms.map((term) => `“${term.term}” in the ${term.field}`).join(", ")}`;

/** One feed entry as discovery metadata: the publisher's headline, opening the story it belongs to (its brief and
 * sources) once the editors grouped it, the feed's own publication time beside this server's retrieval time, the
 * feed's excerpt marked as not the publication, and the way to the publication itself: an import where the server
 * offers one, or the paste step, and a labelled link to the publisher's own page. Nothing here is a source until the
 * person saves one. */
export function NewsEntryCard({ entry, source, zone, labels, busy, notice, onImport, onPaste, onReadAgain }: {
  /** The entry's feed as the news last described it; null when this page has not read it (its key is shown). */
  entry: NewsEntry; source: NewsSource | null; zone: string; labels: Partial<Record<Interest, string>>;
  busy: string | null; notice: Notice | null; onImport: () => void; onPaste: () => void; onReadAgain: () => void;
}) {
  const published = publishedText(entry.published, zone);
  const reading = busy === entry.entry_id;
  return (
    <li className="client-news-entry" data-entry={entry.entry_id} data-listing={entry.listing}
        data-import={entry.import.state} data-published={entry.published.state}>
      <p className="client-label">{source ? `${source.publisher} · ${source.kind}` : entry.source}</p>
      <h3 className="client-news-title">
        {entry.story_id ? <Link to={href.story(entry.story_id)}>{entry.title}</Link> : <span>{entry.title}</span>}
        {!entry.story_id && <span className="client-sub">Not in a story yet: the editors group new reports.</span>}
        {entry.title_shortened && <span className="client-sub">This headline was shortened for the list.</span>}
      </h3>
      <p className="client-chips">
        {entry.topics.map((topic) => (
          <span key={topic.interest} className="client-chip" title={basisText(topic)}>
            {labels[topic.interest] ?? topic.interest}</span>
        ))}
        {entry.listing === "retained" && <span className="client-chip is-quiet">No longer in the feed</span>}
        {entry.stale && <span className="client-chip is-warning">From an earlier retrieval</span>}
      </p>
      <p className="client-news-times">
        <span className="client-news-published">{published.line}</span>
        <span className="client-sub">{retrievedText(entry, zone)}</span>
      </p>
      {published.note && <p className="client-sub client-news-time-note">{published.note}</p>}
      {entry.excerpt && !entry.excerpt_repeats_title && (
        <blockquote className="client-news-excerpt">
          <span className="client-label">The feed's excerpt, not the publication</span>
          {entry.excerpt}{entry.excerpt_shortened && <span className="client-sub">The excerpt was shortened.</span>}
        </blockquote>
      )}
      {source?.attribution && <p className="client-sub">{source.attribution}</p>}
      {notice && <NoticeView notice={notice} busy={busy !== null} onReadAgain={onReadAgain} />}
      <p className="client-actions">
        {entry.import.state === "supported" && (
          <button type="button" className="button client-import" disabled={busy !== null} onClick={onImport}>
            {reading ? "Reading the publication…" : "Import the publication"}</button>
        )}
        {entry.import.state === "imported" && entry.import.source_ids.map((sourceId) => (
          <Link key={sourceId} className="button button-quiet" to={href.source(sourceId)}>Open your saved source</Link>
        ))}
        {(entry.import.state !== "imported" || notice?.pasteInstead) && (
          <button type="button" className={entry.import.state === "supported" && !notice?.pasteInstead
            ? "client-link-button client-paste" : "button button-quiet client-paste"} disabled={busy !== null}
                  onClick={onPaste}>Paste it as a new source</button>
        )}
        <a href={entry.link} target="_blank" rel="noreferrer">Publisher's page (opens a new tab)</a>
      </p>
      {entry.import.state === "supported" && (
        <p className="client-sub">Importing reads the official page on this server (once; a kept copy is reused) and
          counts as one of today's publication imports. You check the text before anything is saved; nothing is
          analysed.</p>
      )}
      {entry.import.state === "unsupported" && entry.import.reason && <p className="client-sub">{entry.import.reason}</p>}
      {entry.import.state === "imported" && <p className="client-sub">Already saved as your source from this entry.</p>}
    </li>
  );
}
