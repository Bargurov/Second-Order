import type { CSSProperties } from "react";
import { fetchLibrary, useLoad, type Loaded } from "../api";
import {
  LIBRARY_CATEGORIES, categoryCounts, filtersHref, latestPerCategory, publishedDay, sectorCounts, sectorLabel,
  type LibraryRow, type LibrarySector,
} from "../library";
import { Link } from "../router";
import "../library.css";

/** What every library case is, shown wherever cases are listed or read. */
export function LibraryLabels({ labels }: { labels: string[] }) {
  return (
    <ul className="library-labels" aria-label="What these cases are">
      {labels.map((label) => <li key={label}>{label}</li>)}
    </ul>
  );
}

/**
 * One entry per case: topic, publication date (in the publisher's own offset, or the stated date for a date-only
 * source), publisher, title, summary and the sectors the case covers, each sector a link to the library under it.
 */
export function CaseLibraryList({ rows, sectors = [] }: { rows: LibraryRow[]; sectors?: readonly LibrarySector[] }) {
  return (
    <ol className="library-list">
      {rows.map((row) => (
        <li key={row.id} className="library-entry" data-case={row.id}>
          <p className="library-entry-meta">
            <span className="library-category">{row.category}</span>
            <span data-precision={row.publication.precision}>
              {publishedDay(row.publication) ?? row.published_as_stated}
            </span>
            <span className="library-entry-publisher">{row.publisher}</span>
          </p>
          <Link to={`/library/${row.id}`} className="library-entry-title">{row.title}</Link>
          <p className="library-entry-summary">{row.summary}</p>
          {row.sectors.length > 0 && (
            <div className="library-entry-sectors">
              <span className="library-entry-sectors-label" aria-hidden="true">Sectors</span>
              <ul className="library-sector-chips" aria-label="Sectors">
                {row.sectors.map((slug) => (
                  <li key={slug}><Link to={filtersHref({ sector: slug })}>{sectorLabel(sectors, slug)}</Link></li>
                ))}
              </ul>
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

/** A read failure says so and offers to read again; editorial cases are never shown from a partial library. */
export function LibraryState({ library, onRetry }: { library: Exclude<Loaded<unknown>, { state: "ready" }>;
                                                    onRetry: () => void }) {
  if (library.state === "loading") return <p className="library-state" role="status">Loading the case library…</p>;
  return (
    <div className="library-state is-error" role="alert">
      <p>The case library could not be read: {library.message}</p>
      <button type="button" className="button" onClick={onRetry}>Try again</button>
    </div>
  );
}

/**
 * The Tracker's compact entry point: the latest case in each topic and links into the full, searchable library, by
 * topic and by sector. It loads on its own, with or without prepared Dossiers or runtime records.
 */
export function CaseLibrarySection({ style }: { style?: CSSProperties }) {
  const [library, retry] = useLoad(fetchLibrary, "library");
  return (
    <section id="case-library" className="card tracker-section library-section reveal" style={style}
      aria-labelledby="case-library-title">
      <div className="tracker-section-head">
        <h2 id="case-library-title">Case library</h2>
        <span className="tracker-count">
          {library.state === "ready" ? `${library.data.cases.length} cases · editorial, never scored` : "Editorial"}
        </span>
      </div>
      {library.state !== "ready" ? <LibraryState library={library} onRetry={retry} /> : (
        <>
          <p className="card-note">{library.data.introduction}</p>
          <LibraryLabels labels={library.data.labels} />
          <p className="library-latest-note">The latest case in each topic:</p>
          <CaseLibraryList rows={latestPerCategory(library.data.cases)} sectors={library.data.sectors} />
          <nav className="library-more" aria-label="Browse the case library">
            <Link to="/library">Browse all {library.data.cases.length} cases</Link>
            {LIBRARY_CATEGORIES.map((item) => (
              <Link key={item.slug} to={filtersHref({ category: item.slug })}>
                {item.label} ({categoryCounts(library.data.cases, "")[item.slug]})
              </Link>
            ))}
          </nav>
          {library.data.sectors.length > 0 && (
            <nav className="library-more library-more-sectors" aria-label="Browse the case library by sector">
              <span>By sector:</span>
              {library.data.sectors.map((item) => (
                <Link key={item.slug} to={filtersHref({ sector: item.slug })}>
                  {item.label} ({sectorCounts(library.data.cases, library.data.sectors, "")[item.slug]})
                </Link>
              ))}
            </nav>
          )}
        </>
      )}
    </section>
  );
}
