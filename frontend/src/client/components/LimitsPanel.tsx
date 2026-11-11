import { quotaText, resetText, storageText } from "../newsView.ts";
import { useNewsRead } from "../useRead.ts";
import { NoticeView } from "./NoticeView";

/** Today's counted searches, imports, new sources and prepared analyses, and what the account holds, exactly as the
 * server last reported them (GET /api/user/limits, a read that is never counted). `refresh` changes after a counted
 * action, so the figures are read again from the server rather than worked out here. */
export function LimitsPanel({ refresh = 0, compact = false }: { refresh?: number; compact?: boolean }) {
  const [read, again] = useNewsRead((news) => news.limits(), `limits:${refresh}`);
  return (
    <section className={`card client-card client-limits${compact ? " is-compact" : ""}`} aria-labelledby="limits-title"
             data-limits={read.state === "ready" ? read.data.limits.state : read.state}>
      <h2 id="limits-title">Your limits today</h2>
      {read.state === "loading" && <p className="client-status" role="status">Reading your limits…</p>}
      {read.state === "notice" && <NoticeView notice={read.notice} onReadAgain={again} />}
      {read.state === "ready" && (() => {
        const limits = read.data.limits;
        return (
          <>
            {limits.state === "no_policy" && <p className="client-advisory" data-limits-detail>{limits.detail}</p>}
            <ul className="client-limits-list">
              {limits.operations.map((quota) => (
                <li key={quota.operation} data-operation={quota.operation}
                    className={quota.remaining === 0 ? "is-used" : undefined}>{quotaText(quota)}</li>
              ))}
            </ul>
            {!compact && <ul className="client-limits-list is-storage">
              {storageText(limits).map((line) => <li key={line}>{line}</li>)}</ul>}
            <p className="client-basis">{resetText(limits)} These limits are the server's and separate from analysis
              credits; reading and filtering the news are never counted.{" "}
              <button type="button" className="client-link-button" onClick={again}>Read again</button></p>
          </>
        );
      })()}
    </section>
  );
}
