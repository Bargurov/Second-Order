import { Link } from "../../router";
import { NEXT_TEXT, type Notice } from "../refusals.ts";

/** A refusal or an unconfirmed reply, with its next step as an explicit control. Nothing here acts on its own. */
export function NoticeView({ notice, onNewQuote, onReadAgain, effortHref, busy = false }: {
  notice: Notice; onNewQuote?: () => void; onReadAgain?: () => void; effortHref?: string; busy?: boolean;
}) {
  const next = NEXT_TEXT[notice.next];
  return (
    <div className={`client-notice is-${notice.tone}`} role="alert" data-code={notice.code ?? notice.tone}>
      <p className="client-notice-title">{notice.title}</p>
      <p>{notice.detail}</p>
      {notice.facts.length > 0 && <ul className="client-notice-facts">{notice.facts.map((fact) => <li key={fact}>{fact}</li>)}</ul>}
      {next && <p className="client-notice-next">{next}</p>}
      <p className="client-actions">
        {notice.next === "new_quote" && onNewQuote &&
          <button type="button" className="button" disabled={busy} onClick={onNewQuote}>Get a new quote</button>}
        {notice.next === "read_again" && onReadAgain &&
          <button type="button" className="button button-quiet" disabled={busy} onClick={onReadAgain}>Read again</button>}
        {notice.next === "choose_effort" && effortHref && <Link className="button button-quiet" to={effortHref}>Choose an Effort</Link>}
      </p>
    </div>
  );
}
