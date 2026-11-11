import type { CSSProperties } from "react";
import { useLoad } from "../api";
import { dayLabel, fetchRelatedCollection, relatedCaseHref } from "../relatedCases";
import { Link } from "../router";
import { LibraryLabels } from "./CaseLibrary";
import "../related.css";

/**
 * The case library's historical announcements: the cases Related Cases compares events with, each built from one
 * retained official page, and the coverage not built yet. They are listed apart from the release cases above them.
 */
export function HistoricalCases({ style }: { style?: CSSProperties }) {
  const [loaded, retry] = useLoad(fetchRelatedCollection, "related-collection");
  return (
    <section id="historical-cases" className="card historical-cases reveal" style={style}
             aria-labelledby="historical-cases-title">
      <div className="tracker-section-head">
        <h2 id="historical-cases-title">{loaded.state === "ready" ? loaded.data.title : "Historical policy announcements"}</h2>
        <span className="tracker-count">
          {loaded.state === "ready" ? `${loaded.data.cases.length} cases · used by Related cases` : "Related cases"}
        </span>
      </div>
      {loaded.state === "loading" && <p className="library-state" role="status">Loading the historical cases…</p>}
      {loaded.state !== "loading" && loaded.state !== "ready" && (
        <div className="library-state is-error" role="alert">
          <p>The historical cases could not be read: {loaded.message}</p>
          <button type="button" className="button" onClick={retry}>Try again</button>
        </div>
      )}
      {loaded.state === "ready" && (
        <>
          <p className="card-note">{loaded.data.introduction}</p>
          <LibraryLabels labels={loaded.data.labels} />
          <p className="library-selection">{loaded.data.historical_note} {loaded.data.coverage_note}</p>
          <ol className="historical-list">
            {loaded.data.cases.map((row) => (
              <li key={row.id} className="historical-entry" data-historical={row.id}>
                <p className="library-entry-meta">
                  <span className="library-category">{row.topic}</span>
                  <span>Announced {dayLabel(row.announced)}</span>
                  <span>{row.publisher}</span>
                </p>
                <Link to={relatedCaseHref(row.id)} className="library-entry-title">{row.title}</Link>
                <p className="library-entry-summary">{row.summary}</p>
              </li>
            ))}
          </ol>
          <div className="historical-unfinished">
            <h3>Not covered yet</h3>
            <ul>
              {loaded.data.unfinished.map((item) => (
                <li key={item.topic}><strong>{item.topic}.</strong> Planned source: {item.planned_source}. {item.outcome}</li>
              ))}
            </ul>
          </div>
          <p className="library-selection">{loaded.data.matching_note}</p>
        </>
      )}
    </section>
  );
}
