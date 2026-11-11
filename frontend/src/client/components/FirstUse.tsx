import { Link } from "../../router";
import { accountOf, useClient } from "../context";
import { href } from "../paths.ts";
import { missingSteps } from "../present.ts";

/** Before an analysis can be quoted and run: every step the server says is missing (analysis.reasons), in its order
 * and its own words, with who can put it in place. Shown only while the server reports one; it decides nothing. */
export function FirstUse() {
  const { account } = useClient();
  const current = accountOf(account);
  const steps = current ? missingSteps(current) : [];
  if (steps.length === 0) return null;
  return (
    <section className="card client-card client-first-use" aria-labelledby="first-use-title" data-first-use>
      <h2 id="first-use-title">Before an analysis can run</h2>
      <p className="card-note">The server reports {steps.length === 1 ? "one step" : `${steps.length} steps`} still
        missing. Adding a source, preparing an analysis and reading saved results use no credits meanwhile; the server
        checks everything again at each quote and run.</p>
      <ol className="client-steps">
        {steps.map((step) => (
          <li key={step.reason} data-reason={step.reason}>
            <p className="client-step-title">{step.title}</p>
            <p>{step.detail}</p>
            {step.held && <p className="client-note">{step.held}</p>}
            <p className="client-sub">{step.who}</p>
          </li>
        ))}
      </ol>
      <p className="client-sub"><Link to={href.credits}>How credits work</Link></p>
    </section>
  );
}
