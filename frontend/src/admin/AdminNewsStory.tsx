// One story on the News desk: its reports with the rule or decision behind each membership, its ranking points, the
// operator's curation (headline, detach, merge, topic, major mark), and its brief: a $0 draft from the reports' own
// words, the editor, the versions with their guard findings and what still stops publication, publication and
// withdrawal, and, on a server started for it, a paid draft behind its cost preview and an explicit approval.
import { useState } from "react";
import { adminGet, adminPost, newKey, type AdminWrite } from "./adminApi.ts";
import { usd, when } from "./adminFormat.ts";
import { StoryRelevance } from "./AdminNewsRelevance";
import {
  authorshipText, fromEditor, newsPaths, providerNote, stageLine, toEditor, type BriefContent, type Desk,
  type DeskStory, type DraftingPreview, type EditorText, type TextPlanRow,
} from "./newsDesk.ts";

const EMPTY: EditorText = { headline: "", summary: "", facts: "", implications: "", themes: "", uncertainties: "",
                            missing: "" };

function Result({ result }: { result: AdminWrite<unknown> | null }) {
  if (!result) return null;
  return result.state === "saved" ? <p className="admin-ok" role="status">Done.</p>
    : <p className="admin-problem" role="alert">{result.message}</p>;
}

export function AdminNewsStory({ story, desk, done }: { story: DeskStory; desk: Desk; done: () => void }) {
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const post = async (path: string, body: object) => {
    const outcome = await adminPost(path, { ...body, idempotency_key: newKey() });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  const [title, setTitle] = useState(story.title);
  const [into, setInto] = useState("");
  const [topic, setTopic] = useState("");
  const [label, setLabel] = useState("");
  const [until, setUntil] = useState("");
  const needsReason = !reason.trim();
  return (
    <details className="admin-panel" data-desk-story={story.story_id} data-brief={story.brief.state}>
      <summary><strong>{story.title}</strong>{" "}
        <small>{story.reports} reports · {story.coverage_detail.confirmed_news + story.coverage_detail.confirmed_official} confirmed, {story.coverage_detail.possible_news + story.coverage_detail.possible_official} possible origins · {when(story.latest_at)} ·
          score {story.rank.score}{story.rank.hot ? " · hot" : ""} · brief {story.brief.state}
          {story.published_version ? ` v${story.published_version}` : ""}{story.synthetic ? " · SYNTHETIC" : ""}</small>
      </summary>
      <p><small>{story.story_id}{story.merged_from.length ? ` · merged from ${story.merged_from.join(", ")}` : ""}</small></p>
      <h3>Reports</h3>
      <ol>{story.reports_detail.map((report) => (
        <li key={report.entry_id} data-entry={report.entry_id}>
          <a href={report.link} target="_blank" rel="noreferrer">{report.title}</a>{" "}
          <small data-text={report.text?.state}>{report.publisher} ({report.role_label}) · {when(report.at)}
            {report.text?.state === "full_text" || report.text?.state === "partial_text"
              ? ` · ${report.text.state === "full_text" ? "full text" : "partial text"} ${report.text.characters
                ?.toLocaleString("en-US")} characters, retrieved ${when(report.text.retrieved_at ?? "")}`
              : report.text?.state === "failed" ? ` · text not readable: ${report.text.detail}` : ""}
            {report.at_basis === "first_seen"
            ? " (first seen; no stated time)" : report.at_basis === "dated" ? " (date stated; no time)" : ""} · {report.material === "permitted" ? "material" : "listed only"}
            {report.synthetic ? " · SYNTHETIC" : ""}</small>{" "}
          {story.reports > 1 && <button type="button" className="admin-link" disabled={needsReason}
                                        onClick={() => void post(newsPaths.story(story.story_id, "detach"),
                                                                 { entry_id: report.entry_id, reason })}>Detach</button>}
        </li>
      ))}</ol>
      <details><summary>Membership record</summary><ul>{story.history.map((row, index) => (
        <li key={index}><small>{row.action} {row.entry_id} · {String(row.basis.rule)} · {row.actor} · {when(row.at)} ·
          {row.reason}</small></li>))}</ul></details>
      <h3>Ranking points</h3>
      <ul>{story.rank.signals.map((row) => <li key={row.signal}><small>{row.points} · {row.text}</small></li>)}</ul>
      <h3>Curate</h3>
      <div className="admin-form">
        <label>Reason (for any action below)<input value={reason} maxLength={300}
                                                   onChange={(event) => setReason(event.target.value)} /></label>
      </div>
      <div className="admin-form">
        <label>Headline<input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} /></label>
        <button type="button" className="button" disabled={needsReason || !title.trim() || title === story.title}
                onClick={() => void post(newsPaths.story(story.story_id, "title"), { title, reason })}>Set headline</button>
      </div>
      <div className="admin-form">
        <label>Merge into story<select value={into} onChange={(event) => setInto(event.target.value)}>
          <option value="">Choose a story</option>
          {desk.stories.filter((row) => row.story_id !== story.story_id).map((row) => (
            <option key={row.story_id} value={row.story_id}>{row.title.slice(0, 80)}</option>))}
        </select></label>
        <button type="button" className="button" disabled={needsReason || !into}
                onClick={() => void post(newsPaths.story(story.story_id, "merge"), { into, reason })}>Merge</button>
      </div>
      <div className="admin-form">
        <label>Topic<select value={topic} onChange={(event) => setTopic(event.target.value)}>
          <option value="">Choose a topic</option>
          {desk.topics.map((row) => <option key={row.topic_id} value={row.topic_id}>{row.title}</option>)}
        </select></label>
        <label>Timeline label<input value={label} maxLength={120} onChange={(event) => setLabel(event.target.value)} /></label>
        <button type="button" className="button" disabled={needsReason || !topic}
                onClick={() => void post(newsPaths.links(topic), { story_id: story.story_id, action: "link", label,
                                                                   reason })}>Link as a development</button>
        <button type="button" className="button" disabled={needsReason || !topic}
                onClick={() => void post(newsPaths.links(topic), { story_id: story.story_id, action: "unlink",
                                                                   label: "", reason })}>Unlink</button>
      </div>
      <div className="admin-form">
        <label>Major until<input type="datetime-local" value={until} onChange={(event) => setUntil(event.target.value)} /></label>
        <button type="button" className="button" disabled={needsReason || !until}
                onClick={() => void post(newsPaths.priorities, { target_kind: "story", target_id: story.story_id,
                                                                 level: "major", until: new Date(until).toISOString(),
                                                                 reason })}>Mark as major</button>
        <button type="button" className="button" disabled={needsReason || story.priority?.level !== "major"}
                onClick={() => void post(newsPaths.priorities, { target_kind: "story", target_id: story.story_id,
                                                                 level: "none", until: null, reason })}>Clear the mark</button>
        {story.priority?.level === "major" && <small>Major until {when(story.priority.until)}</small>}
      </div>
      <Result result={result} />
      <TextsDesk story={story} done={done} />
      <BriefDesk story={story} done={done} reason={reason} />
      <StoryRelevance story={story} done={done} />
    </details>
  );
}

/** The story's publication texts: what retrieving them would reuse or request, then one explicit retrieval. */
function TextsDesk({ story, done }: { story: DeskStory; done: () => void }) {
  const [plan, setPlan] = useState<TextPlanRow[] | null>(null);
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  if (!story.reports_detail.some((report) => report.material === "permitted")) return null;
  const check = async () => {
    const read = await adminGet<{ texts: { plan: TextPlanRow[] } }>(newsPaths.story(story.story_id, "texts"));
    if (read.state === "ready") setPlan(read.data.texts.plan);
  };
  const requests = plan?.filter((row) => row.action === "request").length ?? 0;
  const retrieve = async () => {
    const outcome = await adminPost(newsPaths.story(story.story_id, "texts"), {});
    setResult(outcome);
    setPlan(null);
    if (outcome.state === "saved") done();
  };
  return (
    <div data-texts-desk>
      <h3>Publication texts</h3>
      <p className="admin-form">
        <button type="button" className="admin-link" onClick={() => void check()}>Check what retrieving the texts
          would do (requests nothing)</button>
      </p>
      {plan && (
        <>
          <ul>{plan.map((row) => <li key={row.entry_id}><small>{row.publisher}: {row.title} · {{
            request: "would be requested once", reuse: "text kept; reused", reread: "kept copy read again",
            not_supported: "not read for its text" }[row.action]}</small></li>)}</ul>
          <button type="button" className="button" disabled={plan.every((row) => row.action === "reuse" ||
            row.action === "not_supported")} onClick={() => void retrieve()}>Retrieve ({requests} request{requests !==
            1 ? "s" : ""}, counted against today's publication requests)</button>
        </>
      )}
      <Result result={result} />
    </div>
  );
}

function BriefDesk({ story, done, reason }: { story: DeskStory; done: () => void; reason: string }) {
  const latest = story.versions.at(-1) ?? null;
  const [text, setText] = useState<EditorText>(() => latest ? toEditor(latest.content, story.material) : EMPTY);
  const [method, setMethod] = useState<"editorial" | "extract">("editorial");
  const [problems, setProblems] = useState<string[]>([]);
  const [result, setResult] = useState<AdminWrite<unknown> | null>(null);
  const [drafting, setDrafting] = useState<DraftingPreview | null>(null);
  const [approve, setApprove] = useState(false);
  const material = story.material;
  if (material.reports.length === 0) {
    return <><h3>Brief</h3><p className="muted" data-no-material>{material.statement}</p></>;
  }
  const assess = async (verdict: "insufficient" | "sufficient") => {
    const outcome = await adminPost(newsPaths.story(story.story_id, "assessment"), {
      material_sha256: material.material_sha256, verdict, reason, idempotency_key: newKey() });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  const review = async (version: number) => {
    const outcome = await adminPost(newsPaths.story(story.story_id, "reviews"), { version, note: "",
                                                                                  idempotency_key: newKey() });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  const field = (name: keyof EditorText) => (event: { target: { value: string } }) => {
    setText((typed) => ({ ...typed, [name]: event.target.value }));
    setMethod("editorial");
  };
  const startDraft = async () => {
    const read = await adminGet<{ draft: { content: BriefContent } }>(newsPaths.story(story.story_id, "draft"));
    if (read.state === "ready") {
      setText(toEditor(read.data.draft.content, material));
      setMethod("extract");
    }
  };
  const save = async () => {
    const parsed = fromEditor(text, material);
    setProblems(parsed.problems);
    if (!parsed.content) return;
    const outcome = await adminPost(newsPaths.story(story.story_id, "briefs"), { content: parsed.content, method,
                                                   based_on: latest?.version ?? null, idempotency_key: newKey() });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  const publish = async (version: number | null) => {
    const outcome = await adminPost(newsPaths.story(story.story_id, "publication"), { version, reason,
                                                                                      idempotency_key: newKey() });
    setResult(outcome);
    if (outcome.state === "saved") done();
  };
  const preview = async () => {
    const outcome = await adminPost<{ drafting: DraftingPreview }>(newsPaths.story(story.story_id, "drafting"), {});
    if (outcome.state === "saved") setDrafting(outcome.data.drafting);
    else setResult(outcome);
  };
  const send = async () => {
    if (!drafting || !approve) return;
    const outcome = await adminPost<{ drafting: { attempt: DraftingPreview["attempt"] } }>(
      newsPaths.approval(drafting.draft_id), { request_sha256: drafting.request_sha256, approve_paid_request: true,
        estimated_max_usd: drafting.estimate.estimated_real_run_if_output_reaches_max_usd });
    setApprove(false);
    setResult(outcome);
    if (outcome.state === "saved") {
      const next = await adminPost<{ drafting: DraftingPreview }>(newsPaths.story(story.story_id, "drafting"), {});
      if (next.state === "saved") setDrafting(next.data.drafting);  // The workflow now: stage 2 prepared, or done.
      done();
    }
  };
  return (
    <>
      <h3>Brief</h3>
      <p className="muted">{material.statement}</p>
      {(latest?.content as { economics?: unknown } | undefined)?.economics ? (
        <p className="admin-attention" data-economics-note>The latest version holds an economic explanation. These
          fields edit the brief only: a version saved here has no explanation, and the story shows it as pending until
          one is prepared through a batch (news batch preview).</p>) : null}
      {story.insufficient && <p className="admin-attention" data-insufficient>Not enough material: {story.insufficient}</p>}
      <p className="admin-form">
        <button type="button" className="admin-link" disabled={!reason.trim()} onClick={() => void assess("insufficient")}>
          Record that this material cannot support a useful brief</button>
        {story.insufficient && <button type="button" className="admin-link" disabled={!reason.trim()}
                                       onClick={() => void assess("sufficient")}>Record that it can</button>}
      </p>
      <ol>{material.reports.map((row) => <li key={row.entry_id}><small>{row.publisher}: {row.title}</small></li>)}</ol>
      {material.not_used.length > 0 && <p className="muted">Listed only, never used: {material.not_used.map((row) =>
        row.publisher).join(", ")}.</p>}
      <p className="admin-form">
        <button type="button" className="button" onClick={() => void startDraft()}>Start from the reports' own words
          ($0, nothing recorded)</button>
        <button type="button" className="button" onClick={() => void preview()}>Preview a paid model draft</button>
      </p>
      {drafting && (
        <div className="admin-attention" data-drafting={drafting.draft_id} data-drafting-state={drafting.state}>
          <p>Model {drafting.model}, in two requests, each approved on its own. {drafting.detail}</p>
          <ol data-drafting-stages>{drafting.stages.map((row) => (
            <li key={row.stage} data-drafting-stage={row.stage}>{stageLine(row)} <small className="muted">{row.does}
              </small></li>))}</ol>
          <p>Combined planning estimate {usd(drafting.combined.planning_estimate_usd)}; still to approve
            {" "}{usd(drafting.combined.remaining_planning_estimate_usd)}
            {drafting.combined.usage_cost_usd !== null ? `; reported usage so far ` +
              `$${drafting.combined.usage_cost_usd.toFixed(4)}` : ""}. {drafting.combined.statement}</p>
          {drafting.next_stage !== null && <p>Next: the exact saved request of stage {drafting.stage}
            {" "}({drafting.request_sha256.slice(0, 12)}…), at most {drafting.max_tokens.toLocaleString("en-US")} output
            tokens, planning estimate {usd(drafting.estimate.estimated_real_run_if_output_reaches_max_usd)}.
            {" "}{drafting.estimate.caveat}</p>}
          <p>Attempt: {drafting.attempt.state}{drafting.attempt.detail ? ` · ${drafting.attempt.detail}` : ""}</p>
          {providerNote(drafting.attempt) && <p className="muted" data-provider-error>{providerNote(drafting.attempt)}</p>}
          {drafting.sending.enabled && drafting.next_stage !== null && drafting.attempt.state === "not_attempted" ? (
            <>
              <label className="admin-effort"><input type="checkbox" checked={approve}
                                                     onChange={(event) => setApprove(event.target.checked)} /> I approve
                one billed request, stage {drafting.stage} only, at up to this estimate; it is sent once and never
                retried.{drafting.stage === 1 ? " Stage 2 is prepared from its checked reply and needs its own " +
                  "approval." : ""}</label>
              <button type="button" className="button" disabled={!approve} onClick={() => void send()}>Send stage
                {" "}{drafting.stage} once</button>
            </>
          ) : <p className="muted">{drafting.next_stage === null ? "Nothing to approve." : drafting.sending.detail}</p>}
        </div>
      )}
      <div className="admin-form admin-brief-editor">
        <label>Headline<input value={text.headline} maxLength={160} onChange={field("headline")} /></label>
        <label>Summary (reported facts)<textarea rows={3} value={text.summary} onChange={field("summary")} /></label>
        <label>What was reported: one per line, ending with the report numbers above, as [1] or [1, 2]
          <textarea rows={4} value={text.facts} onChange={field("facts")} /></label>
        <label>Why it may matter: one possibility per line (may, could, would, if…)
          <textarea rows={3} value={text.implications} onChange={field("implications")} /></label>
        <label>Themes: "sector | name | basis" (or company, or theme), one per line
          <textarea rows={2} value={text.themes} onChange={field("themes")} /></label>
        <label>What is uncertain, one per line<textarea rows={2} value={text.uncertainties}
                                                         onChange={field("uncertainties")} /></label>
        <label>What is missing, one per line<textarea rows={2} value={text.missing} onChange={field("missing")} /></label>
        <button type="button" className="button" onClick={() => void save()}>Save as version {(latest?.version ?? 0) + 1}
          ({method === "extract" ? "compiled from the reports, completed by you" : "written by you"})</button>
      </div>
      {problems.length > 0 && <ul className="admin-problem">{problems.map((row) => <li key={row}>{row}</li>)}</ul>}
      <Result result={result} />
      <h3>Versions</h3>
      {story.versions.length === 0 ? <p className="muted">No version yet.</p> : (
        <ul data-versions>{story.versions.map((row) => (
          <li key={row.version} data-version={row.version}>
            v{row.version} · {authorshipText(row)} · saved by {row.actor} · {when(row.at)}
            {row.version === story.published_version ? " · published" : ""}
            {row.covers_current_material ? "" : " · prepared from earlier material"}
            {row.reviews.length > 0 ? ` · read by ${row.reviews.map((item) => `${item.reviewer} (${when(item.at)})`)
              .join(", ")}` : row.authorship === "editor" ? "" : " · not read by an editor"}{" "}
            {row.authorship !== "editor" && <button type="button" className="admin-link"
              onClick={() => void review(row.version)}>I have read this version</button>}
            {row.problems.length > 0 ? <ul className="admin-problem">{row.problems.map((problem) =>
              <li key={problem}>{problem}</li>)}</ul> : <span className="admin-ok"> · publishable</span>}{" "}
            <button type="button" className="admin-link" disabled={!reason.trim() || row.problems.length > 0 ||
              row.version === story.published_version} onClick={() => void publish(row.version)}>Publish</button>
          </li>
        ))}</ul>
      )}
      {story.published_version !== null && (
        <button type="button" className="admin-link" disabled={!reason.trim()} onClick={() => void publish(null)}>Withdraw
          the published brief</button>
      )}
    </>
  );
}
