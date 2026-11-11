import { useEffect, type CSSProperties } from "react";
import { fetchLibrary, useLoad } from "../api";
import { CaseLibraryList, LibraryLabels, LibraryState } from "../components/CaseLibrary";
import { HistoricalCases } from "../components/HistoricalCases";
import { ResearchViews } from "../components/ResearchViews";
import { CompanyList } from "../components/CompanyList";
import { ThesisList } from "../components/ThesisList";
import {
  LIBRARY_CATEGORIES, categoryCounts, filterCases, filtersHref, readFilters, sectorCounts, unknownSector,
  type CaseLibraryIndex, type LibraryFilters,
} from "../library";
import { Link, navigate } from "../router";

const order = (i: number) => ({ "--i": i }) as CSSProperties;
const matching = (count: number) => count === 1 ? "1 case matches" : `${count} cases match`;

/**
 * The full collection with search, topic and sector controls. The browsing state lives in the address
 * (?q=&category=&sector=), replaced as it changes, so a reload, a shared link or Back from a case restores it.
 * Everything is filtered locally; a case under two sectors is one record shown under both. The collection's labels
 * stay in view; its longer description and selection rules sit in a disclosure, so browsing starts on the first screen.
 */
export function LibraryPage({ search }: { search: string }) {
  const [library, retry] = useLoad(fetchLibrary, "library");
  useEffect(() => {
    document.title = "Case library · Second Order";
  }, []);
  return (
    <article className="library">
      <header className="library-header reveal" style={order(0)}>
        <p className="kicker">Case library</p>
        <h1>Official releases, read closely</h1>
        {library.state === "ready" && (
          <>
            <LibraryLabels labels={library.data.labels} />
            <details className="library-about">
              <summary>About this collection and its selection</summary>
              <p className="library-about-text">{library.data.introduction}</p>
              <p className="library-selection">{library.data.selection}</p>
            </details>
          </>
        )}
      </header>
      <section className="card library-index reveal" style={order(1)} aria-label="Cases">
        {library.state === "ready" ? <Browser library={library.data} search={search} />
          : <LibraryState library={library} onRetry={retry} />}
      </section>
      <HistoricalCases style={order(2)} />
      <ThesisList style={order(3)} />
      <CompanyList style={order(4)} />
      <ResearchViews style={order(5)} />
      <p className="muted library-footnote">
        These cases are separate from the <Link to="/">Tracker</Link>'s frozen hypotheses: they have no legs, scores or
        evaluations and never enter research summaries. Library counts are editorial counts, not research denominators.
      </p>
    </article>
  );
}

function Browser({ library, search }: { library: CaseLibraryIndex; search: string }) {
  const slugs = library.sectors.map((item) => item.slug);
  const filters = readFilters(search, slugs);
  const unknown = unknownSector(search, slugs);
  const shown = filterCases(library.cases, filters);
  const counts = categoryCounts(library.cases, filters.query, filters.sector);
  const perSector = sectorCounts(library.cases, library.sectors, filters.query, filters.category);
  const filtered = filters.query.trim() !== "" || filters.category !== null || filters.sector !== null;
  const update = (change: Partial<LibraryFilters>) =>
    navigate(filtersHref({ ...filters, ...change }), { replace: true });
  const reset = () => update({ query: "", category: null, sector: null });
  const categoryLabel = LIBRARY_CATEGORIES.find((item) => item.slug === filters.category)?.label;
  const sector = library.sectors.find((item) => item.slug === filters.sector);
  const scope = `${categoryLabel ? ` in ${categoryLabel}` : ""}${sector ? ` under ${sector.label}` : ""}`;
  // An empty result with both a topic and a sector: how many cases each would show without the other.
  const allTopics = sector && categoryLabel && counts.all > 0 ? counts.all : 0;
  const allSectors = categoryLabel && sector && perSector.all > 0 ? perSector.all : 0;
  return (
    <>
      <div className="library-controls">
        <label className="library-search" htmlFor="library-search">
          <span>Search titles, summaries, topics and publishers</span>
          <input id="library-search" type="search" value={filters.query} autoComplete="off" spellCheck={false}
            enterKeyHint="search" placeholder="e.g. payrolls, deposits, semiconductors"
            onChange={(event) => update({ query: event.target.value })} />
        </label>
        <div className="library-control-group">
          <p className="library-control-head">
            <span className="library-control-label" id="library-topic-label">Topic</span>
            <span className="library-control-hint" id="library-topic-hint">the kind of release</span>
          </p>
          <div className="library-categories" role="group" aria-labelledby="library-topic-label"
            aria-describedby="library-topic-hint">
            {[{ slug: null, label: "All" }, ...LIBRARY_CATEGORIES].map((item) => (
              <button key={item.label} type="button" className="library-category-button"
                data-empty={counts[item.slug ?? "all"] === 0 || undefined}
                aria-pressed={filters.category === item.slug} onClick={() => update({ category: item.slug })}>
                {item.label} <span className="library-category-count">{counts[item.slug ?? "all"]}</span>
              </button>
            ))}
          </div>
        </div>
        {library.sectors.length > 0 && (
          <div className="library-control-group">
            <p className="library-control-head">
              <span className="library-control-label" id="library-sector-label">Sector</span>
              <span className="library-control-hint" id="library-sector-hint">
                what a case covers; one case can be under several
              </span>
            </p>
            <div className="library-categories library-sectors" role="group" aria-labelledby="library-sector-label"
              aria-describedby="library-sector-hint">
              {[{ slug: null, label: "All sectors" }, ...library.sectors].map((item) => (
                <button key={item.label} type="button" className="library-category-button"
                  data-sector={item.slug ?? "all"} data-empty={perSector[item.slug ?? "all"] === 0 || undefined}
                  aria-pressed={filters.sector === item.slug} onClick={() => update({ sector: item.slug })}>
                  {item.label} <span className="library-category-count">{perSector[item.slug ?? "all"]}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      {unknown && (
        <p className="library-sector-note" role="note">
          The address names a sector, “{unknown}”, that the library does not have, so all sectors are shown.
        </p>
      )}
      {sector && (
        <div className="library-sector-scope" data-sector={sector.slug}>
          <p><strong>{sector.label}.</strong> {sector.coverage}</p>
          <details className="library-scope-more">
            <summary>How this sector's cases were chosen</summary>
            <p className="library-selection">{sector.selection}</p>
            {library.sector_membership && <p className="library-selection">{library.sector_membership}</p>}
          </details>
        </div>
      )}
      <div className="library-results-head">
        <p className="library-result-count" role="status" aria-live="polite">
          {shown.length === library.cases.length ? `Showing all ${library.cases.length} cases`
            : `Showing ${shown.length} of ${library.cases.length} cases`}
          {scope}
          {filters.query.trim() ? ` matching “${filters.query.trim()}”` : ""}, oldest first.
        </p>
        {filtered && shown.length > 0 && (
          <button type="button" className="button library-reset" onClick={reset}>Clear search, topic and sector</button>
        )}
      </div>
      {shown.length > 0 ? <CaseLibraryList rows={shown} sectors={library.sectors} /> : (
        <div className="library-empty">
          <p>
            No case {filters.query.trim() ? <>matches “{filters.query.trim()}”</> : "is listed"}
            {scope}. The search covers titles, summaries, topics and publishers, not the full text of each case.
          </p>
          {(allTopics > 0 || allSectors > 0) && (
            <ul className="library-widen">
              {sector && allTopics > 0 && (
                <li>
                  <span>{matching(allTopics)} under {sector.label} in all topics.</span>
                  <button type="button" className="button library-widen-button"
                    onClick={() => update({ category: null })}>Show all topics</button>
                </li>
              )}
              {categoryLabel && allSectors > 0 && (
                <li>
                  <span>{matching(allSectors)} in {categoryLabel} across all sectors.</span>
                  <button type="button" className="button library-widen-button"
                    onClick={() => update({ sector: null })}>Show all sectors</button>
                </li>
              )}
            </ul>
          )}
          <button type="button" className="button library-reset" onClick={reset}>Show all cases</button>
        </div>
      )}
    </>
  );
}
