import { useLoad, type Loaded } from "../api";
import { fetchDraftLinks, linkForDraft } from "../assessment";
import type { ReviewHistory } from "../draftTypes";
import { REVIEW_STATUS } from "../drafts";
import { formatUtc } from "../format";
import { hypothesisHref } from "../lifecycle";
import { Link } from "../router";

/**
 * Whether this draft was frozen, derived from verified freeze records joined by the draft ID the freeze recorded,
 * never by title or date. The draft's own prepared view keeps the status it was prepared with and is not rewritten;
 * when the review used at freeze differs from the current one, both are named.
 */
export function DraftFreezeFlag({ draftId, fingerprint, history }: {
  draftId: string; fingerprint: string; history: Loaded<ReviewHistory>;
}) {
  const [links] = useLoad(fetchDraftLinks, "draft-links");
  if (links.state === "loading") return <p className="review-flag" role="status">Checking whether it was frozen…</p>;
  if (links.state !== "ready") {
    return <p className="review-flag">{REVIEW_STATUS} <small>(as prepared; whether it was frozen could not be read:
      {" "}{links.message})</small></p>;
  }
  const link = linkForDraft(links.data, draftId);
  if (!link) return <p className="review-flag">{REVIEW_STATUS}</p>;
  const current = history.state === "ready" ? history.data.reviews[history.data.reviews.length - 1] : null;
  const atFreeze = link.review_at_freeze;
  return (
    <div className="review-flag review-flag-frozen" data-frozen={link.hypothesis_id}>
      <p>Frozen as <Link to={hypothesisHref(link.hypothesis_id)}>hypothesis {link.hypothesis_id.slice(0, 12)}</Link>
        {" "}at {formatUtc(link.frozen_at)} · derived from its freeze record; this draft's own record is unchanged.</p>
      <p className="draft-note">
        Frozen with review version {atFreeze.sequence} ({atFreeze.status.replace(/_/g, " ")}, saved
        {" "}{formatUtc(atFreeze.saved_at)}).
        {current && current.review_id !== atFreeze.review_id
          ? ` The current review is version ${current.sequence} (${(current.status ?? "no status").replace(/_/g, " ")}); it does not change the frozen content.`
          : current ? " That is the current review." : ""}
        {link.draft_view_sha256 !== fingerprint ? " The prepared view served now differs from the one frozen." : ""}
      </p>
    </div>
  );
}
