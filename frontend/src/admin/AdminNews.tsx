// The News desk (admin-api-0.4, docs/news-stories-contract.md section 6): an update run connecting the steps below for
// fresh material (AdminNewsUpdate), the source registry with each source's freshness, the explicit publisher-feed
// refresh, grouping of new reports, the pairs of stories that may cover one development (applied only by a merge),
// every story with its records and brief versions (AdminNewsStory), and the ongoing topics. Each change is its own
// explicit POST with a reason and an idempotency key; reading changes nothing.
import { useEffect, useState, type FormEvent } from "react";
import { adminPost, newKey, useAdmin, type AdminWrite } from "./adminApi.ts";
import { when } from "./adminFormat.ts";
import { BatchPanel, CoveragePanel } from "./AdminNewsCoverage";
import { RelevancePanel } from "./AdminNewsRelevance";
import { AdminNewsStory } from "./AdminNewsStory";
import { UpdatePanel } from "./AdminNewsUpdate";
import { STATUS_LABEL, newsPaths, type Desk, type DeskTopic } from "./newsDesk.ts";

function Result({ result }: { result: AdminWrite<unknown> | null }) {
  if (!result) return null;
  return result.state === "saved" ? <p className="admin-ok" role="status">Done.</p>
    : <p className="admin-problem" role="alert">{result.message}</p>;
}

function Registry({ desk }: { desk: Desk }) {
  const freshness = new Map(desk.sources.map((row) => [row.source, row]));
  return (
    <div className="admin-table-wrap">
      <table className="admin-table" data-news="registry">
        <thead><tr><th>Publisher</th><th>Status</th><th>Shown</th><th>Material</th><th>Freshness</th>
          <th>What it needs</th></tr></thead>
        <tbody>{desk.registry.publishers.map((row) => {
          const fresh = freshness.get(row.source);
          return (
            <tr key={row.source} data-publisher={row.source} data-status={row.status}>
              <td>{row.publisher}<br /><small>{row.role_label}{row.synthetic ? " · SYNTHETIC" : ""}</small></td>
              <td>{STATUS_LABEL[row.status] ?? row.status}{row.live_verified
                ? <><br /><small>live retrieval verified {row.live_verified}</small></> : null}</td>
              <td>{row.display === "headline" ? "Headline and link" : "Headline, link and feed excerpt"}</td>
              <td>{row.material === "permitted" ? "May be summarised and analysed" : "Never summarised or sent"}
                {row.material_basis ? <><br /><small>{row.material_basis}</small></> : null}</td>
              <td>{fresh ? <>{fresh.state}{fresh.last_success_at ? `, ${when(fresh.last_success_at)}` : ""}
                {fresh.stale ? " (stale)" : ""}<br /><small>{fresh.reports} reports held</small></> : "Not requested"}</td>
              <td><small>{[row.agreement, row.credentials, row.note].filter(Boolean).join(" ")}</small>
                <br /><small><a href={row.terms_url} target="_blank" rel="noreferrer">Terms</a> · {row.checked}</small></td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}

function Actions({ desk, done }: { desk: Desk; done: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<AdminWrite<{ refresh?: { refreshed: { source: string; outcome: string;
    detail: string | null }[] } }> | null>(null);
  const act = async (name: string, path: string, body: object) => {
    if (busy) return;
    setBusy(name);
    const outcome = await adminPost<{ refresh?: { refreshed: { source: string; outcome: string; detail: string | null }[] } }>(
      path, body);
    setBusy(null);
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  const refreshed = result?.state === "saved" ? result.data.refresh?.refreshed ?? [] : [];
  return (
    <div className="admin-panel">
      <p>Refreshing requests each connected publisher feed once, under the usage limits' refresh cooldown and daily
        budget; the official feeds are refreshed from the Event Inbox. Grouping is local: it puts every report not yet
        in a story into one and requests nothing.</p>
      <p className="admin-form">
        <button type="button" className="button" disabled={busy !== null}
                onClick={() => void act("refresh", newsPaths.refresh, {})}>
          {busy === "refresh" ? "Refreshing…" : "Refresh publisher feeds"}</button>
        <button type="button" className="button" disabled={busy !== null}
                onClick={() => void act("group", newsPaths.group, { idempotency_key: newKey() })}>
          {busy === "group" ? "Grouping…" : `Group new reports (${desk.ungrouped.length} waiting)`}</button>
      </p>
      <Result result={result} />
      {refreshed.length > 0 && <ul data-refreshed>{refreshed.map((row) => (
        <li key={row.source}>{row.source}: {row.outcome}{row.detail ? ` · ${row.detail}` : ""}</li>))}</ul>}
    </div>
  );
}

function Suggestions({ desk, done }: { desk: Desk; done: () => void }) {
  const [reason, setReason] = useState("");
  const [topic, setTopic] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const decide = async (pair: [string, string], decision: "same" | "related" | "different") => {
    const outcome = await adminPost(newsPaths.matches, {
      story_a: pair[0], story_b: pair[1], decision, reason, topic_id: null,
      topic_title: decision === "related" ? topic : null, idempotency_key: newKey() });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  return (
    <>
      <p className="muted">Stories that share distinctive names or figures, suggested with the evidence; nothing is
        merged by itself. Same development: the later story merges into the earlier one, whose address then opens it.
        Related: both stay separate developments, linked to a new ongoing topic. Different: the pair is not suggested
        again. Each decision needs a reason.</p>
      <div className="admin-form">
        <label>Reason for a decision<input value={reason} maxLength={300}
                                           onChange={(event) => setReason(event.target.value)} /></label>
        <label>Topic title (for related)<input value={topic} maxLength={120}
                                               onChange={(event) => setTopic(event.target.value)} /></label>
      </div>
      {desk.suggestions.length === 0 ? <p className="muted">No pair of current stories shares distinctive names or
        figures.</p> : (
        <ul data-suggestions>{desk.suggestions.map((row) => (
          <li key={row.stories.join("|")} data-match={row.stories.join("|")}>
            {row.stories.map((id) => <span key={id}>“{row.titles[id]}” <small>({row.publishers[id].join(", ")})</small>
              {" "}</span>)}
            <br /><small>shared names: {row.evidence.names.join(", ") || "none"}; figures:{" "}
              {row.evidence.figures.join(", ") || "none"}; word overlap {row.evidence.word_overlap};{" "}
              {row.evidence.hours_apart} h apart{row.cross_publisher ? " · different publishers" : " · one publisher"}
              {row.assistant_may_judge ? "" : " · only an editor may judge (publisher terms)"}</small>{" "}
            <button type="button" className="admin-link" disabled={!reason.trim()}
                    onClick={() => void decide(row.stories, "same")}>Same development</button>{" "}
            <button type="button" className="admin-link" disabled={!reason.trim() || !topic.trim()}
                    onClick={() => void decide(row.stories, "related")}>Related (topic)</button>{" "}
            <button type="button" className="admin-link" disabled={!reason.trim()}
                    onClick={() => void decide(row.stories, "different")}>Different</button>
          </li>
        ))}</ul>
      )}
      {desk.match_decisions.length > 0 && (
        <details><summary>Recent decisions ({desk.match_decisions.length})</summary><ul>{desk.match_decisions.map((row) => (
          <li key={`${row.story_a}|${row.story_b}`}><small>{row.decision} · {row.method} · {row.actor} · {row.reason}
          </small></li>))}</ul></details>
      )}
      <Result result={result} />
    </>
  );
}

function TopicForm({ done }: { done: () => void }) {
  const [form, setForm] = useState({ title: "", summary: "", reason: "" });
  const [key, setKey] = useState(newKey);
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const outcome = await adminPost(newsPaths.topics, { ...form, idempotency_key: key });
    setResult(outcome);
    if (outcome.state === "saved") {
      setKey(newKey());
      setForm({ title: "", summary: "", reason: "" });
      done();
    }
  };
  const field = (name: keyof typeof form) => (event: { target: { value: string } }) => {
    setForm((typed) => ({ ...typed, [name]: event.target.value }));
    setKey(newKey());
  };
  return (
    <form className="admin-form" aria-label="New topic" onSubmit={(event) => void submit(event)}>
      <label>Title<input value={form.title} required maxLength={120} onChange={field("title")} /></label>
      <label>Summary<input value={form.summary} maxLength={600} onChange={field("summary")} /></label>
      <label>Reason<input value={form.reason} required maxLength={300} onChange={field("reason")} /></label>
      <button type="submit" className="button">Create the topic</button>
      <Result result={result} />
    </form>
  );
}

function TopicRow({ topic, done }: { topic: DeskTopic; done: () => void }) {
  const [until, setUntil] = useState("");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const mark = async (level: "major" | "none") => {
    const outcome = await adminPost(newsPaths.priorities, {
      target_kind: "topic", target_id: topic.topic_id, level, until: level === "major" ? new Date(until).toISOString()
        : null, reason, idempotency_key: newKey() });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  return (
    <li data-topic={topic.topic_id}>
      <strong>{topic.title}</strong> <small>{topic.topic_id} · created {when(topic.at)} · {topic.reason}</small>
      {topic.priority?.level === "major" && <p className="admin-state">Major until {when(topic.priority.until)}</p>}
      <ol>{topic.timeline.map((row) => <li key={row.story_id}>{row.label || row.title} <small>{when(row.first_at)} ·
        {row.story_id}</small></li>)}</ol>
      <div className="admin-form">
        <label>Major until<input type="datetime-local" value={until} onChange={(event) => setUntil(event.target.value)} /></label>
        <label>Reason<input value={reason} maxLength={300} onChange={(event) => setReason(event.target.value)} /></label>
        <button type="button" className="button" disabled={!until || !reason.trim()} onClick={() => void mark("major")}>
          Mark as major</button>
        <button type="button" className="button" disabled={!reason.trim() || topic.priority?.level !== "major"}
                onClick={() => void mark("none")}>Clear the mark</button>
        <Result result={result} />
      </div>
    </li>
  );
}

export function AdminNews() {
  const [version, setVersion] = useState(0);
  const read = useAdmin<{ desk: Desk }>(newsPaths.desk, version);
  // After an action the desk is read again; the last one read stays shown meanwhile, so an open story stays open.
  const [shown, setShown] = useState<Desk | null>(null);
  useEffect(() => { if (read.state === "ready") setShown(read.data.desk); }, [read]);
  const reload = () => setVersion((value) => value + 1);
  if (read.state === "error") return <p className="admin-problem" role="alert">{read.message}</p>;
  if (shown === null) return <p role="status">Loading the News desk…</p>;
  const desk = shown;
  return (
    <section className="admin-section" data-news-desk>
      <p className="kicker">News</p>
      <h1>News desk</h1>
      <p className="muted">{desk.match.statement} {desk.rank.statement}</p>
      <h2>Update run</h2>
      <UpdatePanel version={version} done={reload} />
      <h2>Sources</h2>
      <Registry desk={desk} />
      <h2>Refresh and group</h2>
      <Actions desk={desk} done={reload} />
      <h2>Economic relevance of current stories</h2>
      <RelevancePanel version={version} done={reload} />
      <h2>Brief coverage of the important stories</h2>
      <CoveragePanel version={version} />
      <h2>Prepare briefs</h2>
      <BatchPanel done={reload} />
      {!desk.newsroom.exists && <p className="admin-attention muted">No newsroom store exists yet; the first grouping
        creates it ({desk.newsroom.schema}).</p>}
      <h2>Possibly the same development</h2>
      <Suggestions desk={desk} done={reload} />
      <h2>Topics</h2>
      <TopicForm done={reload} />
      <ul className="admin-holds">{desk.topics.map((topic) => <TopicRow key={topic.topic_id} topic={topic}
                                                                        done={reload} />)}</ul>
      <h2>Stories ({desk.stories.length})</h2>
      <p className="muted">Latest first. Open a story to curate it and to prepare, check and publish its brief.
        {desk.drafting.enabled ? " Paid drafts are enabled on this server." : ` ${desk.drafting.detail}`}</p>
      {desk.stories.map((story) => <AdminNewsStory key={story.story_id} story={story} desk={desk} done={reload} />)}
    </section>
  );
}
