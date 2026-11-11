import { useLoad } from "../api";
import { dayLabel } from "../relatedCases";
import { fetchRelatedResearch, familyMoreHref, type ResearchLink } from "../relatedResearch";
import { Link } from "../router";
import "../related.css";

/**
 * The event overview's Related research section: links to existing library content, each labelled with how it relates
 * (coverage of this event, same release family or related topic), what differs, and what kind of content it is. It
 * navigates; it does not compare mechanisms, predict or establish cause. Selected by the server on each read.
 */
export function RelatedResearch({ kind, id }: { kind: string; id: string }) {
  const [loaded] = useLoad((signal) => fetchRelatedResearch(kind, id, signal), `research:${kind}:${id}`);
  let body;
  if (loaded.state === "loading") body = <p role="status">Reading the library…</p>;
  else if (loaded.state !== "ready") {
    body = <p className="related-problem" role="alert">Related research could not be read: {loaded.message}</p>;
  } else {
    const view = loaded.data;
    body = (
      <>
        {view.links.length === 0
          ? <p className="research-none" data-testid="research-none">No related research in the library for this event.</p>
          : <ol className="research-list">{view.links.map((link) => <ResearchRow key={link.target.href} link={link} />)}</ol>}
        {view.notes.length > 0 && <ul className="research-notes">{view.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
      </>
    );
  }
  return (
    <section id="overview-research" className="card event-context-section overview-section research-section"
             aria-labelledby="overview-research-title" data-state={loaded.state}>
      <h2 id="overview-research-title">Related research</h2>
      <p className="related-note">Navigation to existing library content, chosen from this event's own stored text,
        address and date. Not a historical comparison, a prediction or evidence of cause; saved headline
        classifications are not used.</p>
      {body}
    </section>
  );
}

function ResearchRow({ link }: { link: ResearchLink }) {
  const more = link.family && link.family.more_earlier > 0 ? familyMoreHref(link) : null;
  return (
    <li className="research-link" data-relation={link.relation} data-target={link.target.id}>
      <p className="related-case-meta">
        <span className="research-relation">{link.relation_label}</span>
        <span>{link.target.category}</span>
        <span>{dayLabel(link.target.date)}</span>
      </p>
      <Link to={link.target.href} className="related-case-title">{link.target.title}</Link>
      <p className="research-explanation">{link.explanation}</p>
      {link.differences.length > 0 && (
        <ul className="research-differences" aria-label="Differences">
          {link.differences.map((text) => <li key={text}>{text}</li>)}
        </ul>
      )}
      {link.unknown.length > 0 && <p className="related-muted">{link.unknown.join(" ")}</p>}
      <p className="research-status" data-status={link.status.kind}>
        {link.status.labels.join(" · ")}. {link.status.source} {link.status.timing}
      </p>
      {more && (
        <p className="related-muted">
          <Link to={more}>{link.family!.more_earlier} more earlier {link.family!.label} case
            {link.family!.more_earlier === 1 ? "" : "s"} in the library</Link>
        </p>
      )}
    </li>
  );
}
