// How credits work, from the server's own terms (GET /api/public/credit-terms, readable signed out or in): its rules
// in its own words, the offered Efforts, how a source's size counts, how long a quote holds and what it would quote now
// for three synthetic sources. Shown to visitors at /credits and, under their own allowance, to signed-in users. One
// read when it opens and one per "Read again"; every number is the server's, and none is shown without its terms.
import { useCallback, useEffect, useMemo, useState } from "react";
import { onboardingApi, type CreditTerms } from "../contracts/onboarding.ts";
import { EXAMPLES_CAPTION, termsView } from "./terms.ts";
import "./public.css";

type Shown = { state: "loading" } | { state: "unread"; message: string } | { state: "read"; terms: CreditTerms };

export function CreditsGuide() {
  const api = useMemo(() => onboardingApi(), []);
  const [shown, setShown] = useState<Shown>({ state: "loading" });
  const read = useCallback(async () => {
    setShown({ state: "loading" });
    const reply = await api.creditTerms();
    if (reply.state === "ok") setShown({ state: "read", terms: reply.data });
    else setShown({ state: "unread", message: reply.state === "refused" ? reply.error.detail : reply.message });
  }, [api]);
  useEffect(() => { void read(); }, [read]);

  if (shown.state === "loading") {
    return <p className="public-status" role="status" data-credit-terms="loading">Reading this server's credit terms…</p>;
  }
  if (shown.state === "unread") {
    return (
      <div className="public-notice is-unconfirmed" role="alert" data-credit-terms="unread">
        <p className="public-notice-title">The credit terms could not be read</p>
        <p>{shown.message}</p>
        <p className="public-actions">
          <button type="button" className="button button-quiet" onClick={() => void read()}>Read again</button></p>
      </div>
    );
  }
  const view = termsView(shown.terms);
  return (
    <div className="credits-guide" data-credit-terms={shown.terms.state}>
      <section className="card public-card" aria-labelledby="credit-rules-title">
        <h2 id="credit-rules-title">The rules</h2>
        <p className="card-note">This server's own wording. The rules hold under every credit policy.</p>
        <ol className="public-rules" data-credit-rules>{view.rules.map((rule) => <li key={rule}>{rule}</li>)}</ol>
      </section>

      {!view.configured && (
        <div className="public-notice" role="status" data-credit-detail>
          <p className="public-notice-title">No analysis can be quoted yet</p>
          <p>{view.detail}</p>
        </div>
      )}

      {view.configured && (
        <section className="card public-card" aria-labelledby="credit-effort-title">
          <h2 id="credit-effort-title">Effort, size and how long a quote holds</h2>
          <dl className="ledger public-facts">
            <div><dt>Efforts offered</dt><dd>{view.efforts.join(", ")}</dd></div>
            <div><dt>A quote holds for</dt><dd>{view.validity}</dd></div>
            <div><dt>Credit policy</dt><dd>{view.policy}</dd></div>
          </dl>
          {view.sizeNeutral && (
            <p data-credit-per-effort>Under the current terms the Effort decides the quote:{" "}
              {view.perEffort.map((item) => `${item.label} ${item.credits}`).join(", ")} credits, as this server quotes
              every example below whatever its length.</p>
          )}
          <p>{view.effortNote}</p>
          <p>{view.sizeNote}</p>
          <p>After a quote's time, ask for a new one; asking uses nothing, and nothing was reserved.</p>
        </section>
      )}

      {view.configured && (
        <section className="card public-card" aria-labelledby="credit-examples-title">
          <h2 id="credit-examples-title">Example quotes</h2>
          <div className="public-table-wrap">
            <table className="public-table" data-credit-examples>
              <caption>{EXAMPLES_CAPTION}</caption>
              <thead>
                <tr><th scope="col">Synthetic source</th>{view.columns.map((label) => <th key={label} scope="col">{label}</th>)}</tr>
              </thead>
              <tbody>
                {view.examples.map((row) => (
                  <tr key={row.key}>
                    <th scope="row">{row.label}<span className="public-small">{row.characters}</span></th>
                    {row.cells.map((cell, index) => <td key={view.columns[index]}>{cell}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="card-note">Figures are credits under the policy named above, read from the server just now.
            They change when the policy changes.</p>
        </section>
      )}

      <section className="card public-card" aria-labelledby="credit-allocation-title">
        <h2 id="credit-allocation-title">Who allocates credits</h2>
        <p>An administrator allocates credits and a daily allowance of runs to each approved account, as two separate
          steps; approving a registration allocates neither. The account page lists what you have and any step still
          missing.</p>
      </section>
    </div>
  );
}
