import { useEffect, type ReactNode } from "react";
import type { Brief, ClaimsView, Relevance, StoryPage, StorySource } from "../../contracts/stories.ts";
import type { Economics, Explanation, Ref } from "../../contracts/economics.ts";
import { Link } from "../../router";
import { useClient, zoneOf } from "../context";
import { href } from "../paths.ts";
import { INTEREST_LABEL, USE_TEXT, authorshipTag, briefSources, briefUpdated, coverageText, earlierLine, evidenceLine,
  figureDetails, inHotNow, originsLine, provenance, dimensionLabel, publishedText, relevanceBasisLine, relevanceLines,
  storyTimes, textLine, timeLine,
} from "../storiesView.ts";
import { useStoriesRead } from "../useRead.ts";
import { NoticeView } from "./NoticeView";

const ORIGIN_LABEL: Record<StoryPage["coverage"]["units"][number]["role"], string> = {
  news: "a newsroom's own reporting", official: "an official statement", company: "a company's statement",
};

/** One story: its shared brief (reported facts apart from possible implications), its sources with their own links,
 * the way into a deeper analysis of one's own, and the ongoing topic it belongs to. Reading it only reads. */
export function StoryView({ storyId }: { storyId: string }) {
  const [read, again] = useStoriesRead((api) => api.story(storyId), `story:${storyId}`);
  const { account } = useClient();
  const zone = zoneOf(account);
  const story = read.state === "ready" ? read.data.story : null;
  useEffect(() => { document.title = `${story?.title ?? "Story"} · Second Order`; }, [story?.title]);
  if (read.state === "loading") return <p className="client-status" role="status">Reading the story…</p>;
  if (read.state === "notice") {
    return (
      <section className="card client-card">
        <h1 className="client-title">Story</h1>
        <NoticeView notice={read.notice} onReadAgain={again} />
        <p><Link to={href.news}>Back to the news</Link></p>
      </section>
    );
  }
  const page = story as StoryPage;
  return (
    <article className="news-story-page" data-story={page.story_id} data-brief={page.brief_state}
             data-synthetic={page.synthetic || undefined}>
      <header className="client-header">
        <p className="client-sub"><Link to={href.news}>← News</Link></p>
        <p className="kicker">Story</p>
        <h1 className="client-title">{page.title}</h1>
        <p className="client-chips">
          {page.synthetic && <span className="client-chip is-warning">Synthetic example: invented, not real news</span>}
          {page.older && <span className="client-chip is-quiet">Older news</span>}
          {page.stale && <span className="client-chip is-warning">From an earlier retrieval</span>}
          {page.interests.map((slug) => <span key={slug} className="client-chip">{INTEREST_LABEL[slug]}</span>)}
        </p>
        <p className="client-sub" data-times>{storyTimes(page, zone).join(" · ")}</p>
        {page.merged && <p className="client-note" data-merged>The editors joined the story you opened into this
          one: they cover the same development.</p>}
      </header>
      {page.brief ? <BriefView brief={page.brief} sources={page.sources} zone={zone}
                               explanation={page.explanation} /> : (
        <section className="card client-card news-brief is-missing" aria-labelledby="brief-title">
          <h2 id="brief-title">Brief</h2>
          <p data-brief-note>{page.brief_note}</p>
          {["failed", "drafted"].includes(page.explanation.state) &&
            <p className="client-sub" data-explanation={page.explanation.state}>{page.explanation.statement}</p>}
        </section>
      )}
      <RelevanceView relevance={page.relevance} />
      <DeeperOffer page={page} />
      <section className="card client-card news-sources-list" aria-labelledby="sources-title">
        <h2 id="sources-title">Sources</h2>
        <p className="client-sub" data-coverage>{coverageText(page.coverage)}</p>
        <ol className="news-source-reports">
          {page.sources.map((source, index) => <SourceItem key={source.entry_id} source={source} zone={zone}
                                                           position={index + 1} />)}
        </ol>
        {page.brief?.economics && page.brief.economics.context.length > 0 && (
          <div className="news-context-sources" data-context-sources>
            <h3>Context used by the economic explanation</h3>
            <ul>{page.brief.economics.context.map((row) => (
              <li key={row.item_id} data-context={row.kind} data-context-role={row.role ?? undefined}
                data-retrospective={row.retrospective ? "" : undefined}>{row.publisher} · <a href={row.link}
                target="_blank" rel="noreferrer">{row.title ?? "the source's page"}</a>
                {row.role_label && <span className="client-chip is-quiet"> {row.role_label}</span>}
                {row.retrospective && <span className="client-chip is-warning"> Later context</span>}
                <span className="client-sub"> {row.kind === "publication" ? "Another story's report" : row.kind ===
                  "expectation" ? `An expectations benchmark as of ${row.as_of}` : row.kind === "methodology"
                  ? `Methodology as stated in a release of ${row.as_of}` : `An observation as of ${row.as_of}`}
                  {row.retrieved ? `, retrieved ${row.retrieved}` : ""}{row.attribution ? `. ${row.attribution}` : ""}.
                  {row.relevance ? ` Why it is used: ${row.relevance}` : ""}{row.timing_label ? ` ${row.timing_label}`
                  : ""}</span></li>
            ))}</ul>
          </div>
        )}
        <details className="news-origins" data-origins={page.coverage.origins}>
          <summary data-origins-line>{originsLine(page.coverage)}</summary>
          <p className="client-sub">One publisher, or several carrying the same text, is one origin. Only a newsroom's
            own reporting and an official statement count as independent; a company's statement does not.</p>
          <ol>{page.coverage.units.map((unit, index) => (
            <li key={unit.entries.join("|")} data-origin={unit.role} data-independence={unit.independence}>
              {unit.publishers.join(", ")} · {ORIGIN_LABEL[unit.role]}{unit.counted_together_because.length > 0
                ? ` · ${unit.entries.length} reports counted together: ${unit.counted_together_because.join(", ")}` : ""}
              {unit.independence === "unverified" && <span className="client-sub"> Independence not established:{" "}
                {unit.uncertain_because.join("; ")}.</span>}
              <span className="visually-hidden"> (origin {index + 1})</span>
            </li>
          ))}</ol>
        </details>
        <p className="client-basis">Each headline opens the publisher's own page in a new tab.</p>
      </section>
      {(page.topics.length > 0 || page.related.length > 0) && (
        <section className="card client-card" aria-labelledby="related-title">
          <h2 id="related-title">Related developments</h2>
          {page.topics.map((topic) => (
            <p key={topic.topic_id}>Part of the ongoing topic <Link to={href.topic(topic.topic_id)}>{topic.title}</Link>
              <span className="client-sub">{topic.developments} developments; the topic's timeline shows them in the
                order they happened</span></p>
          ))}
          {page.related.length > 0 && <p className="client-sub" data-related-order>Other developments, newest first</p>}
          <ul className="news-related">
            {page.related.map((row) => (
              <li key={row.story_id}><Link to={href.story(row.story_id)}>{row.label ?? row.title}</Link>
                <span className="client-sub">{row.label ? `${row.title} · ` : ""}
                  {timeLine(row.first_at, row.first_basis, zone, "first reported")}</span></li>
            ))}
          </ul>
        </section>
      )}
      {page.signals.length > 0 && (
        <details className="news-why card client-card">
          <summary>{inHotNow(page) ? "Why this story is in Hot now" : "How this story is ordered"}</summary>
          <ul>{page.signals.map((row) => <li key={row.signal}>{row.text}</li>)}</ul>
        </details>
      )}
      <p className="client-basis">{page.statement}</p>
    </article>
  );
}

function BriefView({ brief, sources, zone, explanation }: { brief: Brief; sources: StorySource[]; zone: string;
  explanation: Explanation }) {
  const number = (entry: string) => sources.findIndex((source) => source.entry_id === entry) + 1;
  const content = brief.content;
  const cite = (entries: string[]) => (
    <span className="news-cite">{entries.map((entry) => (
      <a key={entry} href={`#source-${number(entry)}`}>[{number(entry)}]</a>))}</span>
  );
  const economics = brief.economics?.status === "explained" ? brief.economics : null;
  return (
    <section className="card client-card news-brief" aria-labelledby="brief-title" data-method={brief.method}
             data-authorship={brief.authorship} data-review={brief.review.state} data-current={brief.current}
             data-explanation={explanation.state}>
      <p className="client-label">Brief{brief.synthetic ? " · SYNTHETIC example" : ""} · <span data-authorship-tag>
        {authorshipTag(brief)}</span></p>
      {!brief.current && brief.update_note && <p className="client-note news-brief-update" data-update-note>
        {brief.update_note}</p>}
      {briefUpdated(brief, zone) && <p className="client-note news-brief-updated" data-brief-updated>
        {briefUpdated(brief, zone)}</p>}
      <h2 id="brief-title" className="news-brief-headline">{content.headline}</h2>
      {economics && explanation.state === "outdated" && <p className="client-note news-explain-note"
        data-explanation-note="outdated">{explanation.statement}{explanation.reason ? ` ${explanation.reason}` : ""}</p>}
      {economics ? <ExplanationTop summary={content.summary} economics={economics} /> :
        <p className="news-brief-summary">{content.summary}</p>}
      {brief.claims && <WhoSaysWhat view={brief.claims} cite={cite} />}
      {!economics && <ExplanationNote explanation={explanation} economics={brief.economics} />}
      {!economics && content.implications.length > 0 && (
        <div className="news-brief-part is-implications">
          <h3>Why it may matter</h3>
          <p className="client-sub">Possibilities, not predictions or advice.</p>
          <ul>{content.implications.map((row) => <li key={row.text}>{row.text}</li>)}</ul>
        </div>
      )}
      {!economics && (content.uncertainties.length > 0 || content.missing.length > 0) && (
        <div className="news-brief-part is-unknowns">
          <h3>What is uncertain or missing</h3>
          <ul>{[...content.uncertainties, ...content.missing].map((row) => <li key={row}>{row}</li>)}</ul>
        </div>
      )}
      <p className="client-sub news-brief-from" data-brief-sources>Based on {briefSources(brief, number)}.</p>
      {brief.revisions.earlier.length > 0 && (
        <details className="news-brief-revisions" data-brief-revisions>
          <summary>What changed in this version, and {brief.revisions.earlier.length === 1 ? "the earlier version"
            : `the ${brief.revisions.earlier.length} earlier versions`}</summary>
          <ul data-brief-changes>{brief.revisions.changes.map((row) => <li key={row}>{row}</li>)}</ul>
          <ol className="news-brief-earlier">{brief.revisions.earlier.map((row) => (
            <li key={row.version} data-earlier-version={row.version}>
              <p className="client-sub">{earlierLine(row, zone)}</p>
              <p><strong>{row.headline}</strong></p>
              <p>{row.summary}</p>
            </li>))}</ol>
        </details>
      )}
      {economics && <ExplanationDetail economics={economics} cite={cite} uncertain={[...content.uncertainties,
        ...content.missing]} />}
      <details className="news-brief-more" data-brief-more>
        <summary>More detail: what was reported, sectors and themes, how this brief was prepared</summary>
        <div className="news-brief-part is-facts">
          <h3>What was reported</h3>
          <ul>{content.facts.map((fact) => <li key={fact.text}>{fact.text}{" "}
            {(fact.claims ?? []).map((id) => {
              const claim = brief.claims?.claims.find((row) => row.id === id);
              return claim && <span key={id} className="client-chip is-claim" data-fact-claim={claim.modality}>
                {claim.holder_label}: {claim.holder_name}
                {claim.modality === "asserted" ? "" : ` · ${claim.modality_label}`}</span>;
            })} {cite(fact.reports)}</li>)}</ul>
        </div>
        {content.themes.length > 0 && (
          <div className="news-brief-part">
            <h3>Sectors, companies and themes</h3>
            <ul>{content.themes.map((row) => (
              <li key={`${row.kind}:${row.name}`}><span className="client-chip">{row.kind}</span> {row.name}
                <span className="client-sub">{row.basis}</span></li>))}</ul>
          </div>
        )}
        <div className="news-brief-provenance" data-provenance>
          {provenance(brief, zone).map((line) => <p key={line} className="client-sub">{line}</p>)}
          {brief.context_statement && <p className="client-sub" data-context-statement>{brief.context_statement}</p>}
          {brief.material.not_used.length > 0 && (
            <p className="client-sub">Not used: {brief.material.not_used.map((row) => row.publisher).join(", ")},
              whose terms do not allow summaries.</p>
          )}
          <p className="client-sub">{brief.statement}</p>
        </div>
      </details>
    </section>
  );
}

/** Who says what (story-brief-0.4): each claim the brief records, whose it is, how it was put and on what condition,
 * in its source's own words. Shown beside the summary, so a condition or a question the prose may compress stays in
 * view. A quote found in its source shows that the words are there, not that the claim is true. */
function WhoSaysWhat({ view, cite }: { view: ClaimsView; cite: (entries: string[]) => ReactNode }) {
  return (
    <div className="news-brief-part is-claims" data-claims>
      <h3>Who says what</h3>
      <ul>{view.claims.map((row) => (
        <li key={row.id} data-claim={row.id} data-modality={row.modality}>
          <span className="client-chip">{row.holder_label}</span> {row.holder_name}{" "}
          <span className="client-chip is-quiet">{row.modality_label}</span>
          {row.condition && <span data-claim-condition> Condition, in its own words: “{row.condition}”.</span>}{" "}
          <span className="client-sub">“{row.quote}”</span>{row.reports.length > 0 && cite(row.reports)}
        </li>))}</ul>
      <p className="client-sub">{view.statement}</p>
    </div>
  );
}

/** The explanation's first layer: what happened, why it matters economically, who may be affected and the main
 * uncertainty. Everything else is a click away on the same page. */
function ExplanationTop({ summary, economics }: { summary: string; economics: Economics }) {
  const top = economics.summary!;
  const evidence = evidenceLine(top);
  return (
    <div className="news-explain-top" data-explanation-top>
      <div className="news-explain-part"><h3>What happened</h3>
        <p className="news-brief-summary">{summary}</p>
        <p className="client-sub" data-stage={top.stage}><span className="client-chip">{top.stage_label}</span>{" "}
          {top.what_changed}</p>
        {evidence && <p className="client-sub" data-evidence-form={evidence.recorded ? "recorded" : "not-recorded"}>
          {evidence.text}</p>}</div>
      <div className="news-explain-part"><h3>Why it matters economically</h3><p data-why>{top.why_it_matters}</p></div>
      {top.who.length > 0 && <div className="news-explain-part"><h3>Who may be affected</h3>
        <p data-who>{top.who.join("; ")}</p></div>}
      <div className="news-explain-part"><h3>Main uncertainty</h3><p data-main-uncertainty>{top.main_uncertainty}</p>
      </div>
      <p className="client-sub">Possibilities and conditions, not predictions or advice.</p>
    </div>
  );
}

/** Why a brief carries no economic explanation: not prepared yet, outdated, failed, or too little evidence. */
function ExplanationNote({ explanation, economics }: { explanation: Explanation; economics: Economics | null }) {
  const reason = economics?.status === "insufficient_evidence" ? economics.insufficient_reason : explanation.reason;
  const said = economics?.status === "insufficient_evidence"
    ? "No economic explanation: its sources do not give enough evidence for one." : explanation.statement;
  if (!said) return null;
  return <p className="client-note news-explain-note" data-explanation-note={explanation.state}>{said}
    {reason ? ` ${reason}` : ""}</p>;
}

/** The explanation's supporting layers, each expandable: channels, knock-on effects, evidence and calculations,
 * assumptions, alternatives, what to watch and the general mechanisms used. Each says what kind of statement it is. */
function ExplanationDetail({ economics, cite, uncertain }: { economics: Economics;
  cite: (entries: string[]) => ReactNode; uncertain: string[] }) {
  const basis = (rows: Ref[]) => rows.length > 0 && (
    <span className="client-sub news-basis"> Rests on: {rows.map((ref, index) => (
      <span key={`${ref.kind}:${ref.label}`}>{index > 0 ? "; " : ""}{ref.label}{ref.reports.length > 0 &&
        cite(ref.reports)}</span>))}.</span>
  );
  const kind = (key: string) => <span className="client-chip is-kind">{economics.kinds[key]}</span>;
  const assumed = (ids: string[]) => ids.length > 0 && (
    <p className="client-sub">Assumes: {ids.map((id) => economics.assumptions.find((row) => row.id === id)?.text ?? id)
      .join(" ")}</p>
  );
  return (
    <div className="news-explain-detail" data-explanation-detail>
      <details className="news-explain-section" data-section="channels">
        <summary>How it could work through the economy ({economics.channels.length})</summary>
        <p className="client-sub" data-steps-note>Each step could follow from the one before; the steps are not a
          timeline.</p>
        <ol className="news-channels">{economics.channels.map((row) => (
          <li key={row.id} data-channel={row.scope}>
            <p>{kind(row.kind)} <span className="client-chip">{row.scope_label}</span>{" "}
              <span className="client-chip is-quiet">{row.horizon_label}</span></p>
            {row.support_label && <p className="client-sub" data-support={row.support ?? undefined}>Supported by:{" "}
              {row.support_label}.</p>}
            <p>{row.text}</p>
            <ol className="news-steps">{row.steps.map((step) => <li key={step}>{step}</li>)}</ol>
            <ul className="news-affected">{row.affected.map((party) => (
              <li key={`${party.kind}:${party.name}`}><strong>{party.name}</strong> ({party.kind}): {party.how}</li>
            ))}</ul>
            {row.conditions && <p className="client-sub">Only if: {row.conditions}</p>}
            {row.note && <p className="client-sub">Mechanism: {row.note.title} (general reasoning, under
              Background).</p>}
            {assumed(row.assumptions)}
            {basis(row.basis)}
          </li>
        ))}</ol>
      </details>
      {economics.second_order.length > 0 && (
        <details className="news-explain-section" data-section="second-order">
          <summary>Possible knock-on effects ({economics.second_order.length})</summary>
          <ul>{economics.second_order.map((row) => (
            <li key={row.id}>{kind(row.kind)} <span className="client-chip is-quiet">{row.horizon_label}</span>{" "}
              {row.text} <span className="client-sub">Only if: {row.conditions}.</span>{assumed(row.assumptions)}
              {basis(row.basis)}</li>
          ))}</ul>
        </details>
      )}
      {(economics.figures.length > 0 || economics.calculations.length > 0) && (
        <details className="news-explain-section" data-section="evidence">
          <summary>Figures and calculations</summary>
          {economics.figures.length > 0 && <ul className="news-figures">{economics.figures.map((row) => (
            <li key={row.id} data-figure={row.id}>{kind(row.kind)} <span className="news-fig-id">{row.id}</span>{" "}
              <strong>{row.display}</strong> {row.label}
              {row.direction_warning && <span className="client-chip is-warning" data-direction-warning> Direction to
                confirm: {row.direction_warning}</span>}
              {row.claim_label && <span className="client-chip is-claim" data-figure-claim> {row.claim_label}</span>}
              <span className="client-sub" data-figure-details> · {figureDetails(row).join(" · ")} · quoted:
                {" "}“{row.quote}”
                {row.reports.length > 0 && cite(row.reports)}{row.sign_basis ? ` · ${row.sign_basis}` : ""}
                {row.context ? " (context)" : ""} · as published by {row.vintage.source}
                {row.vintage.published ? ` (${row.vintage.published.slice(0, 10)})` : ""}
                {row.vintage.label ? `, ${row.vintage.label}` : ""}</span></li>
          ))}</ul>}
          {economics.calculations.length > 0 && <ul className="news-calculations">{economics.calculations.map((row) => (
            <li key={row.id} data-calculation={row.id}>{kind(row.kind)} <span className="news-fig-id">{row.id}</span>{" "}
              <strong>{row.display}</strong> {row.label}
              <span className="client-sub"> · {row.formula}, where {row.inputs.join(" and ")} are the figures above ·
                {" "}{row.period}{row.basis_label ? ` · ${row.basis_label}` : ""}</span></li>
          ))}</ul>}
          <p className="client-sub">Figures are quoted from the sources with their units and periods; calculations are
            made by this server from those figures, never written by hand.</p>
        </details>
      )}
      {economics.assumptions.length > 0 && (
        <details className="news-explain-section" data-section="assumptions">
          <summary>Assumptions ({economics.assumptions.length})</summary>
          <ul>{economics.assumptions.map((row) => <li key={row.id}>{row.id}: {row.text}</li>)}</ul>
        </details>
      )}
      <details className="news-explain-section" data-section="alternatives">
        <summary>Other explanations and offsetting forces</summary>
        <ul>{economics.alternatives.map((row) => (
          <li key={row.text}><span className="client-chip">{row.label}</span> {row.text}
            {row.support_label && <span className="client-sub" data-support={row.support}> Supported by:{" "}
              {row.support_label}.</span>}{assumed(row.assumptions ?? [])}{basis(row.basis)}</li>
        ))}</ul>
        {uncertain.length > 0 && <><p className="client-sub">Also uncertain or missing:</p>
          <ul>{uncertain.map((row) => <li key={row}>{row}</li>)}</ul></>}
      </details>
      <details className="news-explain-section" data-section="watch">
        <summary>What to watch</summary>
        <ul>{economics.watch.map((row) => (
          <li key={row.observable}><strong>{row.observable}</strong>: {row.text}{" "}
            <span className="client-sub">(would {row.would} this reading)</span></li>
        ))}</ul>
      </details>
      {economics.background?.state === "unavailable" && (
        <details className="news-explain-section" data-section="background">
          <summary>Background: general economic mechanisms</summary>
          <p className="client-sub" data-background="unavailable">{economics.statement}</p>
        </details>
      )}
      {economics.notes.length > 0 && (
        <details className="news-explain-section" data-section="background">
          <summary>Background: general economic mechanisms</summary>
          <p className="client-sub" data-background={economics.background?.state}>{economics.statement}
            {economics.background?.state === "recovered" ? " These are the notes as they stood when it was prepared "
              + `(${economics.background.framework_version}).` : ""}</p>
          {economics.notes.map((note) => (
            <div key={note.id} className="news-note" data-note={note.id}>
              <p><strong>{note.title}</strong> {kind(note.kind)}</p>
              <p>{note.mechanism}</p>
              <p className="client-sub">Limits: {note.limits}</p>
              <p className="client-sub">Sources: {note.sources.map((source, index) => (
                <span key={source.url}>{index > 0 ? "; " : ""}<a href={source.url} target="_blank"
                  rel="noreferrer">{source.title}</a> ({source.publisher}{source.year ? `, ${source.year}` : ""})</span>
              ))}.</p>
            </div>
          ))}
        </details>
      )}
    </div>
  );
}

/** Why the story is (or is not) in the economic news: the decision in words, who made it, and the economic
 * dimensions its sources support. A completed assessment is a judgement, not a measured market impact; a missing or
 * unfinished one says so. */
function RelevanceView({ relevance }: { relevance: Relevance }) {
  const [statement, ...rest] = relevanceLines(relevance);
  return (
    <details className="card client-card news-relevance" data-relevance={relevance.state}
             data-basis={relevance.basis ?? undefined} open={relevance.state !== "relevant" || undefined}>
      <summary>{relevance.state === "relevant" ? "Why it is in the economic news" : statement}</summary>
      {relevance.state === "relevant" && <p>{statement}</p>}
      {rest.map((line) => <p key={line} className="client-sub">{line}</p>)}
      {relevance.dimensions.length > 0 && (
        <ul className="news-relevance-dimensions">
          {relevance.dimensions.map((row) => (
            <li key={row.dimension}><span className="client-chip">{dimensionLabel(row.dimension)}</span> {row.how}</li>
          ))}
        </ul>
      )}
      {relevance.missing.length > 0 && <p className="client-sub">Not stated in its sources:{" "}
        {relevance.missing.join(" ")}</p>}
      <p className="client-basis" data-relevance-basis>{relevanceBasisLine(relevance)}</p>
    </details>
  );
}

function DeeperOffer({ page }: { page: StoryPage }) {
  return (
    <section className="card client-card news-deeper" aria-labelledby="deeper-title" data-deeper={page.deeper.available}>
      <h2 id="deeper-title">Go deeper</h2>
      {page.deeper.available ? (
        <>
          <p>An evidence-first analysis of your own: what this story's reports establish, quoted from them, apart from
            any interpretation and from what remains unknown. You see exactly what it uses, then a credit quote; nothing
            runs until you approve it.</p>
          <p className="client-actions"><Link className="button news-go-deeper" to={href.deeper(page.story_id)}>Go
            deeper</Link></p>
        </>
      ) : <p data-deeper-reason>{page.deeper.reason}</p>}
    </section>
  );
}

function SourceItem({ source, zone, position }: { source: StorySource; zone: string; position: number }) {
  return (
    <li id={`source-${position}`} className="news-source-report" data-entry={source.entry_id} data-use={source.use}
        data-role={source.role}>
      <p className="client-label">{source.publisher} · {source.role_label}</p>
      <p className="news-source-title"><a href={source.link} target="_blank" rel="noreferrer">{source.title}</a>
        {source.title_shortened && <span className="client-sub">The headline was shortened for the list.</span>}</p>
      <p className="client-sub">{publishedText(source, zone)}{source.listing === "retained"
        ? " · no longer in the feed" : ""}{source.stale ? " · from an earlier retrieval" : ""}</p>
      {source.excerpt && (
        <blockquote className="news-source-excerpt"><span className="client-label">The feed's excerpt, not the
          article</span>{source.excerpt}{source.excerpt_shortened && <span className="client-sub">Shortened.</span>}
        </blockquote>
      )}
      {textLine(source.text, zone) && <p className="client-sub" data-text-state={source.text.state}>
        {textLine(source.text, zone)}</p>}
      <p className="client-sub">{USE_TEXT[source.use]}{source.counted_together_because.length > 0
        ? ` Counted with another report as one source: ${source.counted_together_because.join(", ")}.` : ""}
        {source.attribution ? ` ${source.attribution}.` : ""}{source.synthetic ? " SYNTHETIC test publisher." : ""}</p>
    </li>
  );
}
