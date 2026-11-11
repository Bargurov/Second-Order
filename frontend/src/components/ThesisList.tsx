import type { CSSProperties } from "react";
import { useLoad } from "../api";
import { formatDay } from "../format";
import { Link } from "../router";
import { fetchThesisCatalog } from "../thesisCatalog";
import "../library.css";

/**
 * The case library's theses: committed, versioned research views. Listing them reads the committed files only. When a
 * thesis is opened, the server checks each source against its acquisition record and looks for each figure and passage
 * cited from a page, a table or a workbook where it is cited; a figure or passage transcribed from a PDF is bound to the
 * PDF by its SHA-256 only. The list imports the catalog only, so the library does not load the thesis reader until a
 * thesis is opened.
 */
export function ThesisList({ style }: { style?: CSSProperties }) {
  const [loaded, retry] = useLoad(fetchThesisCatalog, "thesis-catalog");
  if (loaded.state === "ready" && loaded.data.theses.length === 0) return null;
  return (
    <section id="theses" className="card policy-views reveal" style={style} aria-labelledby="theses-title">
      <div className="tracker-section-head">
        <h2 id="theses-title">Theses</h2>
        <span className="tracker-count">Versioned research views</span>
      </div>
      {loaded.state === "loading" && <p className="library-state" role="status">Loading the theses…</p>}
      {loaded.state !== "loading" && loaded.state !== "ready" && (
        <div className="library-state is-error" role="alert">
          <p>The theses could not be read: {loaded.message}</p>
          <button type="button" className="button" onClick={retry}>Try again</button>
        </div>
      )}
      {loaded.state === "ready" && (
        <ol className="policy-view-list">
          {loaded.data.theses.map((entry) => (
            <li key={entry.id} className="policy-view-entry" data-thesis={entry.id}>
              <p className="library-entry-meta">
                <span className="library-category">Thesis</span>
                <span>
                  Version {entry.latest_version} · {entry.published_on === null ? "draft, not yet approved by the owner"
                    : `published ${formatDay(`${entry.published_on}T00:00:00Z`)}`}
                </span>
              </p>
              <Link to={entry.href} className="library-entry-title">{entry.title}</Link>
              <p className="library-entry-summary">{entry.topic}</p>
              <p className="library-selection">
                A research view, not a recommendation to buy or sell. Each source is checked against its acquisition
                record when the thesis is opened; figures transcribed from a PDF are bound to it by its SHA-256 only.
              </p>
              {entry.id === "copper" && (
                <p className="library-selection" data-tools="copper"><Link to="/theses/copper/tools">Copper tools</Link>:
                  a coverage calculator and the published producer unit-cost comparison, separate from the
                  thesis's view.</p>)}
              {entry.id === "copper" && (
                <p className="library-selection" data-tools="metals"><Link to="/metals">Where metals come from</Link>:
                  production, reserves and their concentration by country for the metals you pick, from USGS and
                  the IEA.</p>)}
              {entry.id === "copper" && (
                <p className="library-selection" data-tools="events"><Link to="/theses/copper/events">Copper event
                  chains</Link>: past events set against the thesis's reasons and risks, each with the sources' own
                  words and your review.</p>)}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
