import { useClient } from "../context";
import { entitlements } from "../present.ts";
import { NoticeView } from "./NoticeView";

/** Credits, today's allowance and the reset time, exactly as the server last reported them. Full size it sits under
 * FirstUse, which lists every missing step; compact (beside an analysis) it names the first. */
export function Entitlements({ compact = false }: { compact?: boolean }) {
  const { account, readAccount } = useClient();
  if (account.state === "loading") return <p className="client-status" role="status">Reading your balance…</p>;
  if (account.state === "error") return <NoticeView notice={account.notice} onReadAgain={() => void readAccount()} />;
  const lines = entitlements(account.account, account.readAt);
  return (
    <section className={`card client-card client-entitlements${compact ? " is-compact" : ""}`} aria-label="Your allowance">
      {!compact && <h2>Your allowance</h2>}
      <dl className="ledger client-ledger">
        <div><dt>Credits</dt><dd data-entitlement="credits">{lines.credits}</dd></div>
        <div><dt>Today</dt><dd data-entitlement="daily">{lines.daily}</dd></div>
        <div><dt>Day resets</dt><dd data-entitlement="reset">{lines.reset}
          <span className="client-sub">{lines.resetUtc}</span></dd></div>
      </dl>
      {lines.held && <p className="client-note" data-entitlement="held">{lines.held}.</p>}
      {/* Full size, it sits under the list of every missing step (FirstUse); compact, it names the first. */}
      {compact && lines.availability &&
        <p className="client-advisory" data-entitlement="availability">{lines.availability}</p>}
      <p className="client-basis">{lines.basis}{" "}
        <button type="button" className="client-link-button" onClick={() => void readAccount()}>Read again</button></p>
    </section>
  );
}
