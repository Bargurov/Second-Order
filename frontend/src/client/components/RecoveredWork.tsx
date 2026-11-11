import { Link } from "../../router";
import { useClient } from "../context";
import { href, type ClientRoute } from "../paths.ts";
import { SOURCE_KEY, type Recoverable } from "../recovery.ts";

/** The page a recovered draft goes back into. */
const pageOf = (draft: Recoverable) => (draft.kind === "source" ? href.newSource : href.analysis(draft.analysisId));

/** Whether `route` is that page, which takes the draft back itself. */
const opensHere = (draft: Recoverable, route: ClientRoute) => draft.kind === "source" ? route.view === "new-source"
  : route.view === "analysis" && route.analysisId === draft.analysisId;

/** Work given back after the same user signed in again, listed until its page takes it back or it is discarded. It is
 * kept in this tab only; opening it puts it back into its form, and saving stays the person's explicit act. */
export function RecoveredWork({ route }: { route: ClientRoute }) {
  const { recovered, releaseRecovered } = useClient();
  const waiting = Object.entries(recovered).filter(([, draft]) => !opensHere(draft, route));
  if (waiting.length === 0) return null;
  return (
    <section className="card client-card client-recovered" aria-labelledby="recovered-title" data-recovered-list>
      <h2 id="recovered-title">Unsaved work from before your session ended</h2>
      <p className="card-note">Kept in this tab only, and not saved. Open it to check it and save it yourself.</p>
      <ul className="client-recovered-list">
        {waiting.map(([key, draft]) => (
          <li key={key} data-recovered-key={key}>
            <span>{draft.kind === "source"
              ? `A source you were adding: “${draft.fields.headline.trim() || "untitled"}”`
              : `Your review of “${draft.headline}”`}{key !== SOURCE_KEY && key.endsWith(":stale")
              ? " (written for an earlier result)" : ""}</span>
            <span className="client-actions">
              <Link className="button button-quiet" to={pageOf(draft)}>Open</Link>
              <button type="button" className="client-link-button" onClick={() => releaseRecovered(key)}>Discard</button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
