import type { CSSProperties } from "react";
import { useLoad } from "../api";
import { fetchResearchCatalog } from "../researchCatalog";
import { Link } from "../router";
import "../library.css";

/**
 * The case library's research views: committed comparisons of selected retained publications. Listing them reads the
 * committed files only; each view checks its quoted passages against the retained sources when it is opened.
 */
export function ResearchViews({ style }: { style?: CSSProperties }) {
  const [loaded, retry] = useLoad(fetchResearchCatalog, "research-catalog");
  if (loaded.state === "ready" && loaded.data.views.length === 0) return null;
  return (
    <section id="research-views" className="card policy-views reveal" style={style}
             aria-labelledby="research-views-title">
      <div className="tracker-section-head">
        <h2 id="research-views-title">Research views</h2>
        <span className="tracker-count">Retrospective comparisons</span>
      </div>
      {loaded.state === "loading" && <p className="library-state" role="status">Loading the research views…</p>}
      {loaded.state !== "loading" && loaded.state !== "ready" && (
        <div className="library-state is-error" role="alert">
          <p>The research views could not be read: {loaded.message}</p>
          <button type="button" className="button" onClick={retry}>Try again</button>
        </div>
      )}
      {loaded.state === "ready" && (
        <ol className="policy-view-list">
          {loaded.data.views.map((view) => (
            <li key={view.id} className="policy-view-entry" data-research={view.id}>
              <p className="library-entry-meta">
                <span className="library-category">Research view</span>
                <span>{view.publications} releases · {view.comparisons} comparisons</span>
              </p>
              <Link to={view.href} className="library-entry-title">{view.title}</Link>
              <p className="library-entry-summary">{view.question}</p>
              <p className="library-selection">{view.scope_note}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
