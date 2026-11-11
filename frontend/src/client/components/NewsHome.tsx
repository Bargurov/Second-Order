import { useEffect } from "react";
import type { SourceRow, StoriesView, StoryCard, TopicCard } from "../../contracts/stories.ts";
import { Link } from "../../router";
import { useClient, zoneOf } from "../context";
import { href, type NewsTab } from "../paths.ts";
import { AWAITING_TEXT, BRIEF_STATE_TEXT, INTEREST_LABEL, briefPreview, briefTag, coverageText, storyTimes,
} from "../storiesView.ts";
import { inZone } from "../time.ts";
import { useStoriesRead } from "../useRead.ts";
import { NoticeView } from "./NoticeView";

const TABS: [NewsTab, string][] = [["hot", "Hot now"], ["coverage", "Most covered"], ["latest", "Latest"], ["topics", "Topics"],
  ["interests", "Your interests"]];

/** The News home: the stories this server's feeds brought, by the ranking the server explains, and the ongoing topics.
 * Opening it, switching tabs or opening a story only reads saved records: no publisher is contacted, no analysis is run
 * and nothing is counted or charged. */
export function NewsHome({ tab }: { tab: NewsTab }) {
  useEffect(() => { document.title = "News · Second Order"; }, []);
  return (
    <>
      <header className="client-header news-header">
        <p className="kicker">News</p>
        <h1 className="client-title">What is happening</h1>
        <p className="client-lede" data-lede>Short briefs and economic explanations, prepared in advance from the
          reports this server's feeds bring. Each one says how it was prepared (by an editor, or with AI) and whether an
          editor has read it. Open a story to read its brief and its sources; go deeper when you want an analysis of
          your own.</p>
        <nav className="news-tabs" aria-label="News views">
          {TABS.map(([key, label]) => (
            <Link key={key} to={href.newsTab(key)} className="news-tab" aria-current={tab === key ? "page" : undefined}>
              {label}</Link>
          ))}
          <Link to={href.reports} className="news-tab is-aside">Reports &amp; search</Link>
        </nav>
      </header>
      {tab === "topics" ? <TopicsList /> : <StoriesList key={tab} view={tab} />}
    </>
  );
}

function StoriesList({ view }: { view: Exclude<NewsTab, "topics"> }) {
  const [read, again] = useStoriesRead((api) => api.stories(view), `stories:${view}`);
  const { account } = useClient();
  const zone = zoneOf(account);
  if (read.state === "loading") return <p className="client-status" role="status">Reading the news…</p>;
  if (read.state === "notice") return <section className="card client-card"><NoticeView notice={read.notice}
                                                                                      onReadAgain={again} /></section>;
  const shown: StoriesView = read.data.stories;
  return (
    <>
      <section className="news-stories" aria-labelledby="stories-title" data-view={view}
               data-stories={shown.stories.length}>
        <h2 id="stories-title" className="visually-hidden">{TABS.find(([key]) => key === view)?.[1]}</h2>
        {view === "interests" && shown.interests.length > 0 && (
          <p className="client-sub" data-interests>Your interests: {shown.interests.map((slug) => INTEREST_LABEL[slug])
            .join(", ")}. <Link to={href.reports}>Change them</Link></p>
        )}
        {shown.notes.map((note) => <p key={note} className="client-advisory" data-news-note>{note}</p>)}
        {view === "coverage" && <p className="client-note" data-coverage-order>
          Economic stories with broader reporting coverage first. Copies count once; confirmed and possible origins
          are shown separately. <Link to={href.news}>Hot now</Link> also highlights important news first reported by
          one source.</p>}
        {shown.stories.length === 0 && shown.notes.length === 0 &&
          <p className="client-empty">No story to show here.</p>}
        <ol className="news-story-list">
          {shown.stories.map((story, index) => <StoryRow key={story.story_id} story={story} zone={zone}
                                                         lead={(view === "hot" || view === "coverage") && index === 0} />)}
        </ol>
        {(view === "hot" || view === "coverage") && shown.stories.length > 0 && (
          <details className="news-rank">
            <summary>{view === "coverage" ? "How coverage is counted" : "How Hot now is ordered"}</summary>
            <p>{shown.rank.statement}</p>
          </details>
        )}
      </section>
      {shown.awaiting.length > 0 && <AwaitingList stories={shown.awaiting} zone={zone} />}
      {view !== "interests" && (shown.left_out.outside_scope > 0 || shown.left_out.older_unassessed > 0) &&
        <p className="client-sub news-left-out" data-left-out>{shown.left_out.statement}</p>}
      {shown.topics.length > 0 && view !== "interests" && (
        <section className="card client-card news-topics-strip" aria-labelledby="ongoing-title">
          <h2 id="ongoing-title">Ongoing topics</h2>
          <ul className="news-topic-list">{shown.topics.map((topic) => <TopicRow key={topic.topic_id} topic={topic}
                                                                                zone={zone} />)}</ul>
          <p className="client-sub"><Link to={href.newsTab("topics")}>Every topic</Link></p>
        </section>
      )}
      <SourcesPanel sources={shown.sources} zone={zone} statement={shown.statement} />
    </>
  );
}

function StoryRow({ story, zone, lead }: { story: StoryCard; zone: string; lead: boolean }) {
  const ready = story.brief.state === "published";
  return (
    <li className={`news-story${lead ? " is-lead" : ""}${ready ? " has-brief" : " is-compact"}`}
        data-story={story.story_id} data-brief={story.brief.state} data-synthetic={story.synthetic || undefined}>
      <p className="client-label">{ready && <span className="news-brief-tag" data-brief-tag>{briefTag(story.brief)}
      </span>}{ready && story.brief.explained && <span className="news-brief-tag is-explained" data-explained-tag>
        Economic explanation</span>}{story.publishers.join(" · ")}</p>
      <h3 className="news-story-title"><Link to={href.story(story.story_id)}>{story.title}</Link></h3>
      <p className="client-chips">
        {story.synthetic && <span className="client-chip is-warning">Synthetic example, not real news</span>}
        {story.older && <span className="client-chip is-quiet">Older news</span>}
        {story.stale && <span className="client-chip is-warning">From an earlier retrieval</span>}
        {story.topics.map((topic) => <span key={topic.topic_id} className="client-chip is-topic">{topic.title}</span>)}
        {story.interests.map((slug) => <span key={slug} className="client-chip">{INTEREST_LABEL[slug]}</span>)}
      </p>
      {ready && story.brief.summary ? (
        <>
          <p className="news-story-summary" data-brief-preview>{briefPreview(story.brief.summary)}{" "}
            <Link to={href.story(story.story_id)} className="news-read-brief">Read the brief</Link></p>
          {story.brief.current === false && <p className="client-sub" data-brief-earlier>This brief was prepared from
            earlier material; an update is pending.</p>}
        </>
      ) : (
        <p className="news-story-nobrief">
          <span className={`news-state-tag is-${story.brief.state}`} data-state-tag>{BRIEF_STATE_TEXT[story.brief.state]}
          </span>
          {story.excerpt && <span className="news-story-excerpt"><span className="client-label">{story.excerpt.publisher}'s
            feed excerpt, not the article</span>{story.excerpt.text}</span>}
        </p>
      )}
      <p className="client-sub">{storyTimes(story, zone).join(" · ")} ·{" "}
        <span data-coverage-line>{coverageText({ ...story.coverage, reports: story.reports })}</span></p>
      {story.signals.length > 0 && (
        <details className="news-why">
          <summary>Why it is here</summary>
          <ul>{story.signals.map((row) => <li key={row.signal}>{row.text}</li>)}</ul>
        </details>
      )}
    </li>
  );
}

/** Current headlines whose economic relevance is not established yet: listed apart, never hidden, each with why. */
function AwaitingList({ stories, zone }: { stories: StoryCard[]; zone: string }) {
  return (
    <details className="card client-card news-awaiting" data-awaiting={stories.length}>
      <summary>Other new headlines ({stories.length}), not yet established as economic news</summary>
      <p className="client-sub">These current headlines have not been assessed for economic relevance, or an editor
        has not decided yet. They are listed so nothing is hidden; open one to see its sources.</p>
      <ul className="news-awaiting-list">
        {stories.map((story) => (
          <li key={story.story_id} data-story={story.story_id} data-relevance={story.relevance.state}>
            <Link to={href.story(story.story_id)}>{story.title}</Link>
            <span className="client-sub">{story.publishers.join(" · ")} · {storyTimes(story, zone)[0]} ·{" "}
              <span data-awaiting-tag>{AWAITING_TEXT[story.relevance.state as keyof typeof AWAITING_TEXT]}</span>
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function TopicRow({ topic, zone }: { topic: TopicCard; zone: string }) {
  return (
    <li className="news-topic" data-topic={topic.topic_id}>
      <Link to={href.topic(topic.topic_id)} className="news-topic-title">{topic.title}</Link>
      {topic.synthetic && <span className="client-chip is-warning">Synthetic example</span>}
      <span className="client-sub">{topic.developments} {topic.developments === 1 ? "development" : "developments"}
        {topic.latest_at ? ` · latest ${inZone(topic.latest_at, zone)}: ${topic.latest_title}` : ""}</span>
    </li>
  );
}

function TopicsList() {
  const [read, again] = useStoriesRead((api) => api.topics(), "topics");
  const { account } = useClient();
  if (read.state === "loading") return <p className="client-status" role="status">Reading the topics…</p>;
  if (read.state === "notice") return <section className="card client-card"><NoticeView notice={read.notice}
                                                                                      onReadAgain={again} /></section>;
  const topics = read.data.topics;
  return (
    <section className="card client-card" aria-labelledby="topics-title" data-topics={topics.topics.length}>
      <h2 id="topics-title">Ongoing topics</h2>
      <p className="client-sub">{topics.statement}</p>
      {topics.notes.map((note) => <p key={note} className="client-advisory">{note}</p>)}
      {topics.topics.length === 0 ? <p className="client-empty">The editors follow no ongoing topic yet.</p> : (
        <ul className="news-topic-list">{topics.topics.map((topic) => <TopicRow key={topic.topic_id} topic={topic}
                                                                               zone={zoneOf(account)} />)}</ul>
      )}
    </section>
  );
}

const STATE_TEXT: Record<SourceRow["state"], string> = {
  ok: "Retrieved", failed: "Latest retrieval failed", not_requested: "Not requested on this server",
  never_refreshed: "Not retrieved yet", unreadable: "Record unreadable",
};

function SourcesPanel({ sources, zone, statement }: { sources: SourceRow[]; zone: string; statement: string }) {
  return (
    <details className="card client-card news-sources">
      <summary>Where the news comes from</summary>
      <p className="client-sub">{statement} An administrator refreshes the feeds; what each publisher's terms allow
        decides what is shown and what may be summarised.</p>
      <ul className="news-source-list">
        {sources.map((row) => (
          <li key={row.source} data-source={row.source} data-state={row.state}>
            <span className="news-source-name">{row.name}</span>{" "}
            <span className="client-sub">{row.role_label} · {STATE_TEXT[row.state]}
              {row.last_success_at ? `, last ${inZone(row.last_success_at, zone)}` : ""}
              {row.stale ? " (its reports come from an earlier retrieval)" : ""} ·{" "}
              {row.material === "permitted" ? "may be summarised" : row.display === "headline"
                ? "headlines and links only" : "shown as the feed gives it; never summarised"} ·{" "}
              <a href={row.terms_url} target="_blank" rel="noreferrer">terms</a>
              {row.synthetic ? " · SYNTHETIC test publisher" : ""}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
