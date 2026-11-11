import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  readInterestsState, SEARCH_RULES, type Interest, type Interests, type NewsEntry, type NewsSource, type NewsSourceKey,
  type QuotaNow, type SearchDone, type Scope,
} from "../../contracts/news.ts";
import { Link, navigate } from "../../router";
import { useClient, zoneOf } from "../context";
import { outcomeOf } from "../controller.ts";
import {
  coverageText, filtered, NO_FILTER, offerPaste, pasteOffer, quotaText, sameSelection, searchKey, searchProblem,
  selection, sourceStateText, type NewsFilter, type SearchBody, type SentSearch,
} from "../newsView.ts";
import { href } from "../paths.ts";
import type { Notice } from "../refusals.ts";
import { useNewsRead } from "../useRead.ts";
import { LimitsPanel } from "./LimitsPanel";
import { NewsEntryCard } from "./NewsEntryCard";
import { NoticeView } from "./NoticeView";

type Labels = Partial<Record<Interest, string>>;
type SourceMap = Partial<Record<NewsSourceKey, NewsSource>>;
interface SearchShown { search: SearchDone; entries: NewsEntry[]; statement: string; counted: boolean; quota: QuotaNow }

/** What the entry lists share: one import at a time, its refusal shown on its entry, and the paste step. */
interface EntryActions {
  busy: string | null; notices: Record<string, Notice>; importEntry: (entry: NewsEntry) => void;
  pasteEntry: (entry: NewsEntry) => void; readAgain: () => void;
}

/** Current entries from the official feeds this server retrieves, by the person's interests: read from the server's
 * cache only (no publisher is contacted and nothing is analysed by opening, filtering or reloading it). A search is a deliberate,
 * counted request; importing a publication or pasting it is the way from an entry to a source of one's own. */
export function NewsPage() {
  const { news, account, endSession } = useClient();
  const zone = zoneOf(account);
  const [interestsRead, readInterestsAgain] = useNewsRead((api) => api.interests(), "interests");
  const [interests, setInterests] = useState<Interests | null>(null);
  useEffect(() => { if (interestsRead.state === "ready") setInterests(interestsRead.data.interests); }, [interestsRead]);
  const [scopeChoice, setScopeChoice] = useState<Scope | null>(null);
  const [newsVersion, setNewsVersion] = useState(0);
  const [limitsVersion, setLimitsVersion] = useState(0);
  const [sources, setSources] = useState<SourceMap>({});
  const [results, setResults] = useState<SearchShown | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notices, setNotices] = useState<Record<string, Notice>>({});
  const acting = useRef(false);
  useEffect(() => { document.title = "Reports & search · Second Order"; }, []);

  const labels: Labels = Object.fromEntries((interests?.vocabulary ?? []).map((row) => [row.interest, row.label]));
  const selected = interests?.selected ?? [];
  const scope: Scope = scopeChoice ?? (selected.length > 0 ? "interests" : "all");

  const importEntry = async (entry: NewsEntry) => {
    if (acting.current) return;  // One import at a time, even for two presses delivered together.
    acting.current = true;
    setBusy(entry.entry_id);
    setNotices(({ [entry.entry_id]: _cleared, ...rest }) => rest);
    const reply = await news.previewImport(entry.entry_id, entry.version_sha256);
    acting.current = false;
    setBusy(null);
    const outcome = outcomeOf(reply, null, zone);
    if (outcome.kind === "ok") return navigate(href.newsImport(outcome.data.import.import_id));
    if (outcome.kind === "session") return endSession(outcome.reason);
    const notice = outcome.notice.tone === "unconfirmed" ? { ...outcome.notice, facts: [...outcome.notice.facts,
      "Pressing Import again shows the same preview if one was made; it is not counted twice."] } : outcome.notice;
    setNotices((current) => ({ ...current, [entry.entry_id]: notice }));
    setLimitsVersion((value) => value + 1);  // A refused preview may have counted (a request was made): read again.
  };
  const pasteEntry = (entry: NewsEntry) => {
    offerPaste(pasteOffer(entry, sources[entry.source]?.publisher ?? entry.source));
    navigate(href.newSource);
  };
  const actions: EntryActions = { busy, notices, importEntry: (entry) => void importEntry(entry), pasteEntry,
                                   readAgain: () => setNewsVersion((value) => value + 1) };

  return (
    <>
      <header className="client-header">
        <p className="client-sub"><Link to={href.news}>← News</Link></p>
        <p className="kicker">Reports &amp; search</p>
        <h1 className="client-title">Reports from the official feeds</h1>
        <p className="client-lede">Every entry of the official feeds this server retrieves, as it last retrieved them,
          with your interests, search and import. A headline opens its story's brief and sources. An entry points to a
          publication; it is not the publication. Import the publication or paste it as a source of your own to analyse
          that text itself.</p>
      </header>
      {interestsRead.state === "loading" && interests === null &&
        <p className="client-status" role="status">Reading your interests…</p>}
      {interestsRead.state === "notice" && interests === null && (
        <section className="card client-card"><NoticeView notice={interestsRead.notice} onReadAgain={readInterestsAgain} /></section>
      )}
      {interests && (
        <InterestsPanel interests={interests} sources={sources} onSaved={(next) => {
          setInterests(next);
          setScopeChoice(null);
        }} />
      )}
      {interests && (
        <SearchPanel selected={selected} sources={sources} labels={labels}
                     onResult={(shown) => setResults(shown)} onCounted={() => setLimitsVersion((value) => value + 1)} />
      )}
      {results && (
        <SearchResults shown={results} sources={sources} zone={zone} labels={labels} actions={actions}
                       onClose={() => setResults(null)} />
      )}
      {interests && !results && (
        <NewsList key={`${scope}:${selected.join(",")}:${newsVersion}`} scope={scope} selected={selected} labels={labels}
                  zone={zone} actions={actions} onScope={setScopeChoice} onSources={setSources}
                  onReadAgain={() => setNewsVersion((value) => value + 1)} />
      )}
      <LimitsPanel refresh={limitsVersion} compact />
    </>
  );
}

function InterestsPanel({ interests, sources, onSaved }: {
  interests: Interests; sources: SourceMap; onSaved: (next: Interests) => void;
}) {
  const { news, endSession } = useClient();
  const [chosen, setChosen] = useState<Set<Interest>>(() => new Set(interests.selected));
  const [expected, setExpected] = useState<number | null>(interests.version);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const sending = useRef(false);
  const picked = selection(interests, chosen);
  const unchanged = sameSelection(picked, interests.selected) && expected === interests.version;
  const nameOf = (slugs: Interest[]) => slugs.length === 0 ? "none" : slugs.map((slug) =>
    interests.vocabulary.find((row) => row.interest === slug)?.label ?? slug).join(", ");

  const toggle = (slug: Interest, on: boolean) => setChosen((current) => {
    const next = new Set(current);
    if (on) next.add(slug); else next.delete(slug);
    return next;
  });

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setNotice(null);
    setNote(null);
    const reply = await news.saveInterests(picked, expected);
    sending.current = false;
    setBusy(false);
    const outcome = outcomeOf(reply);
    if (outcome.kind === "ok") {
      setExpected(outcome.data.interests.version);
      setNote(outcome.data.changed ? "Saved." : "These were already your interests; nothing changed.");
      return onSaved(outcome.data.interests);
    }
    if (outcome.kind === "session") return endSession(outcome.reason);
    if (reply.state === "refused" && reply.error.code === "interests_changed") {
      const current = readInterestsState(reply.error.interests);
      if (current.ok) {  // Another tab's newer save is shown, never overwritten; the person's choice stays to save again.
        setExpected(current.value.version);
        setNotice({ ...outcome.notice, facts: [...outcome.notice.facts, `Saved there: ${nameOf(current.value.selected)}. ` +
          "Your choice below is kept; save it again to replace them."] });
        return onSaved(current.value);
      }
    }
    setNotice(outcome.notice);
  };

  return (
    <details className="card client-card client-interests" open={interests.selected.length === 0}>
      <summary><span className="client-interests-title">Your interests</span>{" "}
        <span className="client-sub" data-interests-saved>{interests.selected.length === 0 ? "None chosen yet"
          : nameOf(interests.selected)}</span></summary>
      <form onSubmit={(event) => void save(event)}>
        <fieldset className="client-interest-options" disabled={busy}>
          <legend>Topics of the news on this server: they choose these entries and the stories under Your
            interests</legend>
          {interests.vocabulary.map((row) => (
            <label key={row.interest} className="client-interest">
              <input type="checkbox" name="interest" value={row.interest} checked={chosen.has(row.interest)}
                     onChange={(event) => toggle(row.interest, event.target.checked)} />
              <span><span className="client-interest-label">{row.label}</span>
                <span className="client-sub">{row.sources.length > 0
                  ? `${row.sources.map((key) => sources[key]?.label ?? key).join(", ")}; also entries naming `
                  : "Entries naming "}{row.terms.map((term) => `“${term}”`).join(", ")}</span></span>
            </label>
          ))}
        </fieldset>
        <p className="client-sub">{interests.rule}</p>
        {notice && <NoticeView notice={notice} />}
        {note && <p className="client-note" role="status">{note}</p>}
        <p className="client-actions">
          <button type="submit" className="button client-save-interests" disabled={busy || unchanged}>
            {busy ? "Saving…" : "Save interests"}</button>
        </p>
        <p className="client-sub">Your interests only choose which entries are shown; saving them counts nothing and
          requests nothing from a publisher. Other tabs keep their own choice until you save there.</p>
      </form>
    </details>
  );
}

function SearchPanel({ selected, sources, labels, onResult, onCounted }: {
  selected: Interest[]; sources: SourceMap; labels: Labels; onResult: (shown: SearchShown) => void;
  onCounted: () => void;
}) {
  const { news, account, endSession } = useClient();
  const [query, setQuery] = useState("");
  const [mine, setMine] = useState(selected.length > 0);
  const [feed, setFeed] = useState<NewsSourceKey | "">("");
  const [retained, setRetained] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [tried, setTried] = useState(false);
  const last = useRef<SentSearch | null>(null);
  const sending = useRef(false);
  const problem = query.trim() === "" && !tried ? null : searchProblem(query);
  const feeds = Object.values(sources).filter((source): source is NewsSource => source !== undefined);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setTried(true);
    if (sending.current || searchProblem(query)) return;  // Said beside the field; nothing is sent or counted.
    const body: SearchBody = { query: query.trim(), interests: mine && selected.length > 0 ? selected : null,
                               sources: feed === "" ? null : [feed], listing: retained ? "all" : "current" };
    const key = searchKey(last.current, body);
    last.current = { body, key, confirmed: false };
    sending.current = true;
    setBusy(true);
    setNotice(null);
    const reply = await news.search({ ...body, request_key: key });
    sending.current = false;
    setBusy(false);
    if (reply.state !== "unconfirmed") last.current = { body, key, confirmed: true };
    const outcome = outcomeOf(reply, null, zoneOf(account));
    if (outcome.kind === "ok") {
      onCounted();
      return onResult(outcome.data);
    }
    if (outcome.kind === "session") return endSession(outcome.reason);
    setNotice(outcome.notice.tone === "unconfirmed" ? { ...outcome.notice, facts: [...outcome.notice.facts,
      "Pressing Search again with the same words and options repeats this search; it is not counted twice."] }
      : outcome.notice);
  };

  return (
    <form className="card client-card client-search" role="search" aria-labelledby="search-title"
          onSubmit={(event) => void submit(event)}>
      <h2 id="search-title">Search the news</h2>
      <label>Words to find
        <input name="query" value={query} onChange={(event) => setQuery(event.target.value)} disabled={busy}
               autoComplete="off" aria-invalid={problem ? true : undefined} />
        <span className={`client-sub${problem ? " is-over" : ""}`} data-search-note>{problem ??
          `Up to ${SEARCH_RULES.maxWords} words of letters or digits. An entry matches when its headline or excerpt ` +
          "contains every word."}</span>
      </label>
      <div className="client-search-options">
        <label className="client-check"><input type="checkbox" checked={mine && selected.length > 0}
          disabled={busy || selected.length === 0} onChange={(event) => setMine(event.target.checked)} />
          Only my interests{selected.length > 0 ? ` (${selected.map((slug) => labels[slug] ?? slug).join(", ")})` : ""}</label>
        <label>Feed
          <select value={feed} disabled={busy} onChange={(event) => setFeed(event.target.value as NewsSourceKey | "")}>
            <option value="">All feeds</option>
            {feeds.map((source) => <option key={source.source} value={source.source}>{source.label}</option>)}
          </select>
        </label>
        <label className="client-check"><input type="checkbox" checked={retained} disabled={busy}
          onChange={(event) => setRetained(event.target.checked)} /> Include entries no longer in the feeds</label>
      </div>
      {notice && <NoticeView notice={notice} />}
      <p className="client-actions">
        <button type="submit" className="button client-search-send" disabled={busy}>{busy ? "Searching…" : "Search"}</button>
      </p>
      <p className="client-sub">Each search you send counts as one of today's searches. It reads this server's copy of
        the feeds and contacts no publisher. Filtering the list below sends nothing and is never counted.</p>
    </form>
  );
}

function SearchResults({ shown, sources, zone, labels, actions, onClose }: {
  shown: SearchShown; sources: SourceMap; zone: string; labels: Labels; actions: EntryActions; onClose: () => void;
}) {
  const { search } = shown;
  return (
    <section className="card client-card client-search-results" aria-labelledby="results-title" data-counted={shown.counted}>
      <h2 id="results-title">Search results for “{search.query}”</h2>
      <p className="client-sub" role="status">{search.matched === 0 ? "No entry contains every word."
        : `${search.matched} ${search.matched === 1 ? "entry matches" : "entries match"}${search.shown < search.matched
          ? `; the first ${search.shown} are shown` : ""}.`} {shown.statement}</p>
      <p className="client-note">{shown.counted ? "This search counted as one of today's searches."
        : "This repeated a search already sent, so it was not counted again."} {quotaText(shown.quota)}.</p>
      <p className="client-actions"><button type="button" className="button button-quiet client-search-close"
        onClick={onClose}>Back to the news</button></p>
      {shown.entries.length > 0 && (
        <ol className="client-news-list">
          {shown.entries.map((entry) => (
            <EntryRow key={entry.entry_id} entry={entry} sources={sources} zone={zone} labels={labels} actions={actions} />
          ))}
        </ol>
      )}
    </section>
  );
}

function EntryRow({ entry, sources, zone, labels, actions }: {
  entry: NewsEntry; sources: SourceMap; zone: string; labels: Labels; actions: EntryActions;
}) {
  return (
    <NewsEntryCard entry={entry} source={sources[entry.source] ?? null} zone={zone} labels={labels} busy={actions.busy}
                   notice={actions.notices[entry.entry_id] ?? null} onImport={() => actions.importEntry(entry)}
                   onPaste={() => actions.pasteEntry(entry)} onReadAgain={actions.readAgain} />
  );
}

function NewsList({ scope, selected, labels, zone, actions, onScope, onSources, onReadAgain }: {
  scope: Scope; selected: Interest[]; labels: Labels; zone: string; actions: EntryActions;
  onScope: (scope: Scope) => void; onSources: (sources: SourceMap) => void; onReadAgain: () => void;
}) {
  const [read, again] = useNewsRead((api) => api.news(scope), `news:${scope}`);
  const [filter, setFilter] = useState<NewsFilter>(NO_FILTER);
  const view = read.state === "ready" ? read.data.news : null;
  useEffect(() => {
    if (view) onSources(Object.fromEntries(view.sources.map((source) => [source.source, source])));
  }, [view]);
  const sources: SourceMap = Object.fromEntries((view?.sources ?? []).map((source) => [source.source, source]));
  const shown = view ? filtered(view.entries, filter) : [];
  const topics = view ? [...new Set(view.entries.flatMap((entry) => entry.topics.map((topic) => topic.interest)))] : [];

  return (
    <>
      <section className="card client-card client-news" aria-labelledby="news-title" data-scope={scope}>
        <div className="client-news-head">
          <h2 id="news-title">{scope === "interests" ? "By your interests" : "All topics"}</h2>
          <fieldset className="client-scope">
            <legend className="client-sub">Show</legend>
            <label className="client-check"><input type="radio" name="scope" value="interests" checked={scope === "interests"}
              disabled={selected.length === 0} onChange={() => onScope("interests")} /> Your interests</label>
            <label className="client-check"><input type="radio" name="scope" value="all" checked={scope === "all"}
              onChange={() => onScope("all")} /> All topics</label>
          </fieldset>
        </div>
        {selected.length === 0 && <p className="client-advisory" data-no-interests>You have not chosen interests yet, so
          every topic is shown. Choose them above to see what concerns you first.</p>}
        {read.state === "loading" && <p className="client-status" role="status">Reading the news…</p>}
        {read.state === "notice" && <NoticeView notice={read.notice} onReadAgain={again} />}
        {view && (
          <>
            {view.entries.length > 0 && (
              <div className="client-news-filter" role="group" aria-label="Filter the entries shown (sends nothing)">
                <label>Topic
                  <select value={filter.interest ?? ""} onChange={(event) => setFilter((current) => ({ ...current,
                    interest: event.target.value === "" ? null : event.target.value as Interest }))}>
                    <option value="">All shown</option>
                    {topics.map((slug) => <option key={slug} value={slug}>{labels[slug] ?? slug}</option>)}
                  </select>
                </label>
                <label>Feed
                  <select value={filter.source ?? ""} onChange={(event) => setFilter((current) => ({ ...current,
                    source: event.target.value === "" ? null : event.target.value as NewsSourceKey }))}>
                    <option value="">All feeds</option>
                    {view.sources.filter((source) => source.entries > 0 || view.entries.some((entry) => entry.source === source.source))
                      .map((source) => <option key={source.source} value={source.source}>{source.label}</option>)}
                  </select>
                </label>
                <label className="client-check"><input type="checkbox" checked={filter.retained}
                  onChange={(event) => setFilter((current) => ({ ...current, retained: event.target.checked }))} />
                  Entries no longer in the feeds</label>
              </div>
            )}
            <p className="client-sub" role="status" data-news-count>{view.entries.length === 0 ? "No entries."
              : `Showing ${shown.length} of ${view.entries.length} ${view.entries.length === 1 ? "entry" : "entries"}.`}</p>
            {view.notes.map((note) => <p key={note} className="client-note" data-news-note>{note}</p>)}
            {view.entries.length > 0 && shown.length === 0 &&
              <p className="client-empty">No entry shown matches this filter.</p>}
            {shown.length > 0 && (
              <ol className="client-news-list">
                {shown.map((entry) => (
                  <EntryRow key={entry.entry_id} entry={entry} sources={sources} zone={zone} labels={labels} actions={actions} />
                ))}
              </ol>
            )}
            <p className="client-basis">{view.statement}{" "}
              <button type="button" className="client-link-button" onClick={onReadAgain}>Read again</button></p>
          </>
        )}
      </section>
      {view && (
        <section className="card client-card client-news-sources" aria-labelledby="feeds-title">
          <h2 id="feeds-title">The feeds and their last retrieval</h2>
          <p className="client-sub">{coverageText(view.sources)} An administrator refreshes them on this server; reading
            this page requests nothing from a publisher.</p>
          <ul className="client-feed-list">
            {view.sources.map((source) => {
              const state = sourceStateText(source, zone);
              return (
                <li key={source.source} data-source={source.source} data-state={source.state} data-tone={state.tone}>
                  <p className="client-feed-name">{source.label}{" "}
                    <span className="client-sub">{source.publisher} · {labels[source.interest] ?? source.interest} ·
                      {" "}{source.kind}</span></p>
                  <p className={`client-feed-state is-${state.tone}`}>{state.text}</p>
                  <p className="client-sub"><a href={source.catalogue_url} target="_blank" rel="noreferrer">Feed
                    catalogue</a> · <a href={source.terms_url} target="_blank" rel="noreferrer">Terms of reuse</a>
                    {source.attribution ? ` · ${source.attribution}` : ""}
                    {source.importable ? " · Publications can be imported" : " · Paste publications from their official pages"}</p>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </>
  );
}
