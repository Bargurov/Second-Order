import {
  CHECKS_LIMITS, CHECKS_READ, NO_CHECKS, NOTHING_FLAGGED, checksRun, findingsShown,
} from "../checksView.ts";
import { useNewsRead } from "../useRead.ts";
import { NoticeView } from "./NoticeView";

/** The research checks of a recorded analysis (GET /api/user/analyses/{id}/quality, a read: no publisher, no analysis,
 * no credits): what the checks flagged, each with its place, detail and rule, and what only a person can judge. It
 * stands after the result and before the review, and asks for a look, never gives a verdict. A refused or unreadable
 * reply is said here alone: the result above and the review below are untouched. `resultSha256` keys the read, so a
 * changed result is checked again. */
export function ResearchChecks({ analysisId, resultSha256 }: { analysisId: string; resultSha256: string }) {
  const [read, again] = useNewsRead((news) => news.quality(analysisId), `quality:${analysisId}:${resultSha256}`);
  const quality = read.state === "ready" ? read.data.quality : undefined;
  return (
    <section className="card client-card client-checks" aria-labelledby="checks-title"
             data-checks={read.state === "ready" ? (quality === null ? "none" : String(quality!.flagged)) : read.state}>
      <h2 id="checks-title">Checks to examine</h2>
      {read.state === "loading" && <p className="client-status" role="status">Reading the checks…</p>}
      {read.state === "notice" && (
        <>
          <p className="client-note">The checks could not be shown. The result above and your review below are not
            affected.</p>
          <NoticeView notice={read.notice} onReadAgain={again} />
        </>
      )}
      {quality === null && <p className="client-note" data-checks-none>{NO_CHECKS}</p>}
      {quality && (
        <>
          <p className="client-label">They ask you to look; none of them is a verdict</p>
          <p className="client-checks-statement">{quality.statement}</p>
          <p className="client-advisory" data-checks-limits>{CHECKS_LIMITS}</p>
          {quality.findings.length === 0
            ? <p className="client-note" data-checks-nothing>{NOTHING_FLAGGED}</p>
            : (
              <>
                <h3>Flagged for you to look at ({quality.findings.length})</h3>
                <ol className="client-check-findings">
                  {findingsShown(quality).map((finding, index) => (
                    <li key={index} data-check={finding.check} data-where={finding.where}>
                      <p className="client-check-place">
                        {finding.place.anchor ? <a href={finding.place.anchor}>{finding.place.label}</a> : finding.place.label}
                        {" · "}<span className="client-check-name">{finding.name}</span>
                      </p>
                      <p className="client-check-detail">{finding.detail}</p>
                      <p className="client-sub">Rule: {finding.rule}</p>
                    </li>
                  ))}
                </ol>
              </>
            )}
          <h3>For you to judge, whatever the checks say</h3>
          <ul className="client-check-review">{quality.human_review.map((item) => <li key={item}>{item}</li>)}</ul>
          <details className="client-check-list">
            <summary>The {Object.keys(quality.checks).length} checks run ({quality.rubric_version})</summary>
            <dl>
              {checksRun(quality).map((check) => (
                <div key={check.name}><dt>{check.name}</dt><dd>{check.rule}</dd></div>
              ))}
            </dl>
          </details>
        </>
      )}
      {read.state === "ready" && (
        <p className="client-basis">{CHECKS_READ}{" "}
          <button type="button" className="client-link-button" onClick={again}>Read again</button></p>
      )}
    </section>
  );
}
