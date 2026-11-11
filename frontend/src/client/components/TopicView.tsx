import { useEffect } from "react";
import { Link } from "../../router";
import { useClient, zoneOf } from "../context";
import { href } from "../paths.ts";
import { BRIEF_STATE_TEXT, coverageText, storyTimes } from "../storiesView.ts";
import { useStoriesRead } from "../useRead.ts";
import { NoticeView } from "./NoticeView";

/** An ongoing topic: the developments the editors linked to it, in the order they were first reported, each its own
 * story with its own sources. Reading it only reads. */
export function TopicView({ topicId }: { topicId: string }) {
  const [read, again] = useStoriesRead((api) => api.topic(topicId), `topic:${topicId}`);
  const { account } = useClient();
  const zone = zoneOf(account);
  const topic = read.state === "ready" ? read.data.topic : null;
  useEffect(() => { document.title = `${topic?.title ?? "Topic"} · Second Order`; }, [topic?.title]);
  if (read.state === "loading") return <p className="client-status" role="status">Reading the topic…</p>;
  if (read.state === "notice" || topic === null) {
    return <section className="card client-card"><h1 className="client-title">Topic</h1>
      {read.state === "notice" && <NoticeView notice={read.notice} onReadAgain={again} />}
      <p><Link to={href.newsTab("topics")}>Every topic</Link></p></section>;
  }
  return (
    <article className="news-topic-page" data-topic={topic.topic_id}>
      <header className="client-header">
        <p className="client-sub"><Link to={href.newsTab("topics")}>← Topics</Link></p>
        <p className="kicker">Ongoing topic</p>
        <h1 className="client-title">{topic.title}</h1>
        {topic.synthetic && <p className="client-chips"><span className="client-chip is-warning">Synthetic example:
          invented, not real news</span></p>}
        {topic.summary && <p className="client-lede">{topic.summary}</p>}
        <p className="client-sub">{topic.statement}</p>
      </header>
      <section className="card client-card" aria-labelledby="timeline-title">
        <h2 id="timeline-title">Timeline</h2>
        {topic.timeline.length === 0 ? <p className="client-empty">No development is linked to this topic yet.</p> : (
          <ol className="news-timeline">
            {topic.timeline.map((story) => (
              <li key={story.story_id} data-story={story.story_id}>
                <p className="client-label">{storyTimes(story, zone)[0]}</p>
                {story.label && <p className="news-timeline-label">{story.label}</p>}
                <p className="news-story-title"><Link to={href.story(story.story_id)}>{story.title}</Link></p>
                <p className="client-sub">{story.brief.summary ?? `${BRIEF_STATE_TEXT[story.brief.state]}.`}</p>
                <p className="client-sub">{coverageText({ ...story.coverage, reports: story.reports })}</p>
              </li>
            ))}
          </ol>
        )}
      </section>
    </article>
  );
}
