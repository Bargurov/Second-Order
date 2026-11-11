import type { MetalsView } from "../metals";
import { NOTES } from "../metalsNotes";
import { str } from "./MetalsBits";

export const PARTS = [{ key: "usgs", label: "the USGS data file" }, { key: "iea", label: "the IEA workbook" }] as const;
const STATE_WORDS: Record<string, string> = {
  verified: "matches its acquisition record",
  changed: "differs from its acquisition record",
  missing: "cannot be checked on this machine",
};
const STATE_LABELS: Record<string, string> = { verified: "Verified", changed: "Changed", missing: "Missing" };

/** One source's state on this read, in words, and whether its part is shown. */
export function readSentence(view: MetalsView, key: "usgs" | "iea", label: string): string {
  const source = view.sources[key === "usgs" ? 0 : 1];
  const state = str(source?.state);
  const words = STATE_WORDS[state] ?? "is in a state this page does not know";
  if (view[key].state === "available") return `${label} ${words}, and its figures are shown`;
  return `${label} ${words}, ${state === "verified" ? "but" : "so"} its figures are withheld`;
}

/** Method & sources: how the figures are read (the plain notes), this read's source check, and each file's terms. */
export function MetalsMethod({ view }: { view: MetalsView }) {
  return (
    <div className="mt-method">
      <section className="mt-method-block" aria-labelledby="mt-read-title">
        <h2 id="mt-read-title">On this read</h2>
        <p className="mt-read" data-read-detail="">{PARTS.map((part, at) => {
          const sentence = readSentence(view, part.key, part.label);
          return <span key={part.key}>{at > 0 ? `; ${sentence}` : sentence.charAt(0).toUpperCase() + sentence.slice(1)}</span>;
        })}.</p>
        <p className="mt-plain">Figures from two published sources, as printed or as shares of each source's own totals.
          No price view, no projection by this project, and no advice.</p>
      </section>
      <section id="notes" className="mt-method-block" aria-labelledby="notes-title">
        <h2 id="notes-title">Reading the figures</h2>
        <dl className="mt-notes" data-notes="">{NOTES.map((note) => (
          <div key={note.id} data-note={note.id}><dt>{note.term}</dt><dd>{note.text}</dd></div>))}
        </dl>
      </section>
      <Sources view={view} />
    </div>
  );
}

function Sources({ view }: { view: MetalsView }) {
  return (
    <footer id="sources" className="mt-method-block thesis-sources" aria-labelledby="sources-title">
      <h2 id="sources-title">Sources</h2>
      <ol className="thesis-source-list">{view.sources.map((source, at) => {
        const terms = source.terms as { licence?: unknown; note?: unknown } | null | undefined;
        const url = str(source.url);
        return (
          <li key={str(source.id) || at} data-source-file={str(source.id)} data-state={str(source.state)}>
            <p className="thesis-source-name"><strong>{str(source.publisher)}</strong> · {str(source.title)}</p>
            <dl className="thesis-source-facts">
              <div><dt>Edition</dt><dd>{str(source.edition)}</dd></div>
              <div><dt>Terms</dt><dd>{str(terms?.licence)}. {str(terms?.note)}</dd></div>
              <div><dt>State</dt><dd className="thesis-source-state">
                <strong>{STATE_LABELS[str(source.state)] ?? "Unknown"}.</strong> {str(source.detail)}</dd></div>
              {url.startsWith("https://") && (
                <div><dt>File</dt><dd><a className="library-external" href={url} target="_blank"
                                         rel="noreferrer">{url}</a></dd></div>)}
            </dl>
          </li>
        );
      })}</ol>
    </footer>
  );
}
